"""Guards the committed 95/395/495 route map published by Transurban.

expresslanes.com ships its whole entry/exit network as a static asset, and each
entry->exit pair carries the exact OD pair id(s) billed for that trip -- 295 of
the 685 pairs list two, i.e. a cross-corridor trip is two whole tolls, never a
summed sub-segment. Refreshed by scripts/fetch_i95_oracle.py.

These are shape and scale guards only. The oracle used to be diffed against the
curated toll graph in db/graph.sql, which is how we measured that 107 of
Transurban's 562 trips need OD pairs VDOT has never published. That graph and
the tools built on it are gone; the finding is recorded in
docs/oracle-findings.md. What remains here is the check that still earns its
keep -- a silent upstream reshape fails loudly instead of quietly rewriting the
snapshot.

No network, no RDS.
"""

import json

from conftest import REPO_ROOT

SNAPSHOT = json.loads((REPO_ROOT / "oracles" / "i95.json").read_text())
NODES: dict[str, dict] = SNAPSHOT["nodes"]
PAIRS: list[dict] = SNAPSHOT["pairs"]
ODS: set[int] = {od for p in PAIRS for od in p["ods"]}


def test_snapshot_matches_published_scale():
    assert len(NODES) == 107
    assert len(PAIRS) == 685
    assert len(ODS) == 330
    # Two-toll trips are the whole reason this file is interesting: they state
    # cross-corridor compositions VDOT's feed never gives as a single price.
    assert sum(1 for p in PAIRS if len(p["ods"]) > 1) == 295
    assert max(len(p["ods"]) for p in PAIRS) == 2


def test_pairs_are_well_formed():
    for p in PAIRS:
        assert p["entry"] in NODES and p["exit"] in NODES, p
        assert p["ods"], p  # a trip with no price key is unusable
        assert all(isinstance(od, int) for od in p["ods"]), p
        assert p["direction"] in {"Northbound", "Southbound"}, p


def test_nodes_carry_the_fields_a_consumer_needs():
    for node_id, node in NODES.items():
        assert node["label"], node_id
        assert node["side"] in {"entries", "exits"}, node_id
        assert node["path"], node_id
        # Transurban's ids are direction-suffixed and that suffix is load
        # bearing -- stripping it is what makes their own deprecated
        # get-ramps-price endpoint return the wrong ods.
        assert node_id.endswith(("NO", "ND", "SO", "SD")), node_id

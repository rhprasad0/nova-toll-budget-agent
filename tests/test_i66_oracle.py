"""Guards the committed I-66 ITB route map published by VDOT.

vai66tolls.com attributes every interchange pair to a toll-zone pair, which is
the only independent source for the I-66 network -- Transurban operates
95/395/495 only, so oracles/i95.json covers none of it. Refreshed by
scripts/fetch_i66_oracle.py.

The extraction is not a straight read: the calculator's runChartMake arguments
are geographic (western zone, then eastern) rather than entry/exit, so they get
normalised to the feed's travel-order convention. These checks exist so a
silent upstream change to that convention -- or to the interchange set -- fails
loudly instead of quietly rewriting the snapshot.

The capture's 20 zone pairs matched the hand-curated i66 graph edges exactly
before that graph was deleted; see docs/oracle-findings.md. The gantry ids
below are inlined from the feed itself
(vdot_sample_data/tollingTripPricing-I66-refreshed.xml).

No network, no RDS.
"""

import json

from conftest import REPO_ROOT

SNAPSHOT = json.loads((REPO_ROOT / "oracles" / "i66.json").read_text())
EXPRESS = json.loads((REPO_ROOT / "oracles" / "i95.json").read_text())
NODES: dict[str, dict] = SNAPSHOT["nodes"]
PAIRS: list[dict] = SNAPSHOT["pairs"]

# Travel order per direction: EB runs 3100 Capital Beltway Beginning -> 3130
# Spout Run Pkwy, WB runs 3200 Glebe Rd -> 3230 Capital Beltway End.
GANTRIES = {"EB": {3100, 3110, 3120, 3130}, "WB": {3200, 3210, 3220, 3230}}


def test_shape_matches_the_express_oracle():
    """Both oracles are the same kind of object: places, and trips between them.

    Each carries only the price *key* into trip_pricing -- od_pair_ids for the
    express lanes, a zone pair for I-66 -- and never a price. Prices belong in
    trip_pricing, which has history; these files answer "what trips exist".
    """
    assert set(SNAPSHOT) == set(EXPRESS) == {"source_url", "nodes", "pairs"}
    for pair in PAIRS:
        assert set(pair) == {"direction", "entry", "exit", "start_zone", "end_zone"}
    assert not any("toll" in key for pair in PAIRS for key in pair)


def test_snapshot_matches_published_scale():
    assert len(NODES) == 17
    assert len(PAIRS) == 96
    # Every ordered zone pair within a direction is billable, and no others.
    assert {(p["start_zone"], p["end_zone"]) for p in PAIRS} == {
        (a, b) for zones in GANTRIES.values() for a in zones for b in zones if a <= b
    }


def test_pairs_are_well_formed():
    for p in PAIRS:
        assert p["entry"] in NODES and p["exit"] in NODES, p
        zones = GANTRIES[p["direction"]]
        # A direction never references the other direction's gantries: the two
        # chains are disjoint in the feed and must stay disjoint here.
        assert p["start_zone"] in zones and p["end_zone"] in zones, p
        # Travel order. The feed numbers each direction's gantries in the order
        # you drive them, so start <= end always -- EB 3100->3130 and, despite
        # running east to west, WB 3200->3230.
        assert p["start_zone"] <= p["end_zone"], p

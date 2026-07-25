"""Guards the committed I-66 ITB capture from VDOT's own toll calculator.

vai66tolls.com attributes every interchange pair to a toll-zone pair, which is
the only independent source we have for the i66 half of the graph -- Transurban
operates 95/395/495 only, so expresslanes_sample_data/entry_exits.json covers
none of it. Snapshot refreshed by scripts/extract_i66_topology.py.

The extraction is not a straight read: the calculator's runChartMake arguments
are geographic (western zone, then eastern) rather than entry/exit, so they get
normalised to the feed's travel-order convention. These checks exist so a
silent upstream change to that convention -- or to the interchange set -- fails
loudly instead of quietly rewriting the snapshot.

No network and no RDS. Nothing consumes this capture yet; it is evidence.
"""

import json

from conftest import REPO_ROOT

# Reuses the seed parse rather than re-deriving it. See test_graph.py.
from test_graph import EDGES

SNAPSHOT = json.loads(
    (REPO_ROOT / "vai66tolls_sample_data" / "interchanges.json").read_text()
)
NODES: dict[str, dict] = SNAPSHOT["nodes"]
PAIRS: list[dict] = SNAPSHOT["pairs"]
GANTRIES: dict[str, list[int]] = SNAPSHOT["gantries"]


def test_snapshot_matches_published_scale():
    assert len(NODES) == 17
    assert len(PAIRS) == 96
    # Every pair got a zone attribution; a miss would mean silently thin data.
    assert SNAPSHOT["pairs_without_zone_attribution"] == []
    # 5 weekdays x 10 zone pairs x 2 directions, 16 quarter-hour slots each.
    assert len(SNAPSHOT["averages"]["series"]) == 100
    for direction, slots in SNAPSHOT["averages"]["slots"].items():
        assert len(slots) == 16, direction
    assert all(len(s["tolls"]) == 16 for s in SNAPSHOT["averages"]["series"])


def test_pairs_are_well_formed():
    for p in PAIRS:
        assert p["entry"] in NODES and p["exit"] in NODES, p
        gantries = GANTRIES[p["direction"]]
        # A direction never references the other direction's gantries: the two
        # chains are disjoint in the feed and must stay disjoint here.
        assert p["start_zone"] in gantries and p["end_zone"] in gantries, p
        # Travel order. The feed numbers each direction's gantries in the order
        # you drive them, so start <= end always -- EB 3100->3130 and, despite
        # running east to west, WB 3200->3230.
        assert p["start_zone"] <= p["end_zone"], p
        assert p["ref_toll"] >= 0, p


def test_zone_pairs_match_the_curated_graph():
    """The point of the capture: VDOT's calculator vs our hand-curated i66 edges.

    A failure here is a real finding, not a flaky assert -- it means the
    calculator and db/graph.sql disagree about which zone pairs are billable.
    """
    captured = {(p["start_zone"], p["end_zone"]) for p in PAIRS}
    seeded = {
        (e["start_zone_id"], e["end_zone_id"]) for e in EDGES if e["feed"] == "i66"
    }
    assert captured == seeded, {
        "calculator_only": sorted(captured - seeded),
        "graph_only": sorted(seeded - captured),
    }
    # Same pairs again from the independent 4-week average table.
    averaged = {
        (s["start_zone"], s["end_zone"]) for s in SNAPSHOT["averages"]["series"]
    }
    assert averaged == seeded

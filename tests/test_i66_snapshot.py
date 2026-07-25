"""Guards the committed I-66 ITB route map from VDOT's own toll calculator.

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
EXPRESS = json.loads(
    (REPO_ROOT / "expresslanes_sample_data" / "entry_exits.json").read_text()
)
NODES: dict[str, dict] = SNAPSHOT["nodes"]
PAIRS: list[dict] = SNAPSHOT["pairs"]

SEEDED_ZONE_PAIRS = {
    (e["start_zone_id"], e["end_zone_id"]) for e in EDGES if e["feed"] == "i66"
}
EB_ZONES = {z for pair in SEEDED_ZONE_PAIRS for z in pair if z < 3200}
WB_ZONES = {z for pair in SEEDED_ZONE_PAIRS for z in pair if z >= 3200}


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


def test_pairs_are_well_formed():
    for p in PAIRS:
        assert p["entry"] in NODES and p["exit"] in NODES, p
        zones = EB_ZONES if p["direction"] == "EB" else WB_ZONES
        # A direction never references the other direction's gantries: the two
        # chains are disjoint in the feed and must stay disjoint here.
        assert p["start_zone"] in zones and p["end_zone"] in zones, p
        # Travel order. The feed numbers each direction's gantries in the order
        # you drive them, so start <= end always -- EB 3100->3130 and, despite
        # running east to west, WB 3200->3230.
        assert p["start_zone"] <= p["end_zone"], p


def test_zone_pairs_match_the_curated_graph():
    """The point of the capture: VDOT's calculator vs our hand-curated i66 edges.

    A failure here is a real finding, not a flaky assert -- it means the
    calculator and db/graph.sql disagree about which zone pairs are billable.
    """
    captured = {(p["start_zone"], p["end_zone"]) for p in PAIRS}
    assert captured == SEEDED_ZONE_PAIRS, {
        "calculator_only": sorted(captured - SEEDED_ZONE_PAIRS),
        "graph_only": sorted(SEEDED_ZONE_PAIRS - captured),
    }

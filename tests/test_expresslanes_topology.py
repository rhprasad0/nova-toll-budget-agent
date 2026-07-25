"""Checks our curated graph's *derivable trips* against Transurban's published ones.

expresslanes.com ships its whole entry/exit network as a static asset, and each
entry->exit pair carries the exact OD pair id(s) billed for that trip -- 295 of
the 685 pairs list two, i.e. a cross-corridor trip is two whole tolls, never a
summed sub-segment. That is precisely the composition route() performs across
the free Springfield connectors, so Transurban's list is an oracle for the one
thing the graph derives rather than looks up. Snapshot refreshed by
scripts/extract_expresslanes_topology.py.

Deliberately compares on **OD pair ids only**. Their node ids are direction-
suffixed ramp codes ("182NO") against our slugs ("i95x:garrisonville"); building
that name mapping would be the same hand-curation the comparison exists to
audit. Both sides already speak ODPAIRID, so no mapping is needed.

No network and no RDS -- reuses tests/test_graph.py's regex parse of
db/graph.sql, same precedent as the loader's schema-contract test. This is
"which trips can the topology express", not "what do they cost".

The counts below are a **characterisation of today's measured divergence**, not
an aspiration. Locking them in makes any fix or regression show up as a diff.
Splitting the Springfield node by arrival road (graph schema 1.2.0) took the
curation gap from 104 trips to 0 and halved the compositions Transurban never
bills; what remains is 107 trips needing OD pairs VDOT does not publish, which
no amount of curation fixes. See docs/toll-graph-spec.md §1.

Run the breakdown as a report:  uv run python tests/test_expresslanes_topology.py
"""

import json

from conftest import REPO_ROOT

# The seed parse (NODES/EDGES off db/graph.sql) already lives there; importing
# it beats maintaining a second copy of the same regexes.
from test_graph import EDGES, NODES

SNAPSHOT = json.loads(
    (REPO_ROOT / "expresslanes_sample_data" / "entry_exits.json").read_text()
)

TRANSURBAN_TRIPS: set[tuple[int, ...]] = {tuple(p["ods"]) for p in SNAPSHOT["pairs"]}
TRANSURBAN_ODS: set[int] = {od for p in SNAPSHOT["pairs"] for od in p["ods"]}
GRAPH_ODS: set[int] = {e["od_pair_id"] for e in EDGES if e["feed"] == "i95"}


def _derivable_trips() -> set[tuple[int, ...]]:
    """Every OD-id sequence the graph can bill, under route()'s traversal rule.

    Mirrors lambdas/agent/route_tool.py's DFS: a priced edge may never directly
    follow another priced edge, only a free connector may sit between them.
    Every prefix ending on a priced edge is itself a complete journey to that
    node, so trips are collected as the walk goes rather than at a destination.

    i66 is excluded, not missing: it's VDOT-operated and priced by zone pair, so
    it has no OD ids and Transurban (95/395/495 only) never sees it.
    """
    adjacency: dict[str, list[dict]] = {}
    for e in EDGES:
        adjacency.setdefault(e["from_node"], []).append(e)

    trips: set[tuple[int, ...]] = set()

    def walk(node: str, path: tuple[str, ...], ods: tuple[int, ...], was_priced: bool):
        for edge in adjacency.get(node, []):
            neighbor = edge["to_node"]
            if neighbor in path:
                continue  # loop prevention
            is_connector = edge["feed"] is None
            if was_priced and not is_connector:
                continue
            if is_connector:
                walk(neighbor, path + (neighbor,), ods, False)
            elif edge["feed"] == "i95":
                trips.add(ods + (edge["od_pair_id"],))
                walk(neighbor, path + (neighbor,), ods + (edge["od_pair_id"],), True)

    for node_id in NODES:
        walk(node_id, (node_id,), (), False)
    return trips


DERIVABLE = _derivable_trips()

UNBILLABLE = TRANSURBAN_TRIPS - DERIVABLE  # real trips the graph can't express
# Split by cause: a trip needing an OD pair we hold no edge for is a *data*
# gap and no amount of curation fixes it; one we cannot build while holding
# every OD pair it needs is a hole in the curated topology.
DATA_GAP = {t for t in UNBILLABLE if not set(t) <= GRAPH_ODS}
TOPOLOGY_HOLES = UNBILLABLE - DATA_GAP
PHANTOM = DERIVABLE - TRANSURBAN_TRIPS  # compositions Transurban never bills


def test_snapshot_matches_published_scale():
    # Guards against a silent upstream reshape making every other assert vacuous.
    assert len(SNAPSHOT["nodes"]) == 107
    assert len(SNAPSHOT["pairs"]) == 685
    assert len(TRANSURBAN_ODS) == 330
    assert sum(1 for p in SNAPSHOT["pairs"] if len(p["ods"]) > 1) == 295


def test_every_single_toll_trip_is_one_edge():
    # The easy half, and it is clean: a one-OD trip needs no composition, and
    # all 298 are seeded. Every gap below is therefore a *composition* problem,
    # never a plain lookup one -- including the 16 OD pairs VDOT never
    # publishes, which Transurban only bills as a leg of a two-toll trip.
    singles = {t for t in TRANSURBAN_TRIPS if len(t) == 1}
    assert len(singles) == 298
    assert {od for (od,) in singles} <= GRAPH_ODS
    assert singles <= DERIVABLE


def test_trips_the_graph_cannot_express():
    assert len(TRANSURBAN_TRIPS) == 562
    assert len(UNBILLABLE) == 107

    # 16 OD pairs Transurban bills are absent from db/graph.sql -- and this is
    # NOT stale seed data. Live RDS holds 317 distinct i95 od_pair_ids, exactly
    # the seed's set, and zero rows for 1374-1389; Transurban prices all 16
    # (checked 2026-07-25: od_1374 $3.45 on 495 N, od_1388 $17.00 on 395 S).
    # So VDOT's public feed simply does not publish them and the poller can
    # never see them. Nothing in this repo fixes that.
    assert sorted(TRANSURBAN_ODS - GRAPH_ODS) == list(range(1374, 1390))
    assert len(DATA_GAP) == 107

    # Zero since 1.2.0. All 104 former holes were one 95 leg + one 495 leg
    # blocked by a single over-merged node: Garrisonville->I-495 (1098) could
    # not reach I-495 HOV->I-395-95-495 (1085) because the I-95 and I-395
    # arrivals at Springfield shared a node. Keep this at 0 -- a regression
    # here means the graph started refusing trips Transurban actually bills.
    assert len(TOPOLOGY_HOLES) == 0


def test_compositions_transurban_never_bills():
    # route() can chain connector-to-connector, so it reaches OD pairs that no
    # real trip combines -- e.g. (1039, 1001) hops i495x:i395-495-hov ->
    # i95x:i495-i395 -> i495x:i395-95-hov across two free connectors.
    # These only reach a user when they're also the cheapest journey for their
    # node pair, so this is an upper bound on what route() would actually quote.
    assert len(PHANTOM) == 232
    assert (1039, 1001) in PHANTOM
    assert len(GRAPH_ODS - TRANSURBAN_ODS) == 3


def _report() -> str:
    return "\n".join(
        [
            f"Transurban trips     : {len(TRANSURBAN_TRIPS):>4}",
            f"  graph can express  : {len(TRANSURBAN_TRIPS & DERIVABLE):>4}",
            f"  cannot (VDOT gap)  : {len(DATA_GAP):>4}",
            f"  cannot (topology)  : {len(TOPOLOGY_HOLES):>4}",
            f"Graph-only trips     : {len(PHANTOM):>4}",
        ]
    )


if __name__ == "__main__":
    print(_report())

"""Validates the curated NOVA toll graph in db/graph.sql against the sample
feed data and its own invariants. No live DB -- same precedent as the
loader's schema-contract test: seed INSERTs are one row per line, so a small
regex parses them into an in-memory graph.

Reuses the loader's own parsers (parse_csv/parse_xml) to read
vdot_sample_data/ rather than re-parsing the feeds here.
"""

import re
from collections import Counter, deque

from conftest import REPO_ROOT, SAMPLE_DATA_DIR
from parse_csv import parse_trip_pricing_csv
from parse_xml import parse_trip_pricing_xml

GRAPH_SQL = (REPO_ROOT / "db" / "graph.sql").read_text()
SPEC_MD = (REPO_ROOT / "docs" / "toll-graph-spec.md").read_text()

SEMVER = r"\d+\.\d+\.\d+"

NODE_RE = re.compile(
    r"INSERT INTO graph_node \(node_id, name, corridor\) VALUES "
    r"\('([^']+)', '([^']*)', '([^']+)'\);"
)
EDGE_RE = re.compile(
    r"INSERT INTO graph_edge \(from_node, to_node, feed, od_pair_id, "
    r"start_zone_id, end_zone_id\) VALUES "
    r"\('([^']+)', '([^']+)', (NULL|'i95'|'i66'), (NULL|\d+), (NULL|\d+), (NULL|\d+)\);"
)


EDGE_FIELDS = (
    "from_node",
    "to_node",
    "feed",
    "od_pair_id",
    "start_zone_id",
    "end_zone_id",
)


def _sql_value(raw: str) -> str | int | None:
    if raw == "NULL":
        return None
    if raw.isdigit():
        return int(raw)
    return raw.strip("'")


def _parse_nodes() -> dict[str, str]:
    """node_id -> corridor"""
    nodes = {}
    for node_id, _name, corridor in NODE_RE.findall(GRAPH_SQL):
        assert node_id not in nodes, f"duplicate node_id {node_id}"
        nodes[node_id] = corridor
    assert nodes, "no graph_node INSERTs parsed from db/graph.sql"
    return nodes


def _parse_edges() -> list[dict]:
    edges = [
        dict(zip(EDGE_FIELDS, map(_sql_value, m), strict=True))
        for m in EDGE_RE.findall(GRAPH_SQL)
    ]
    assert edges, "no graph_edge INSERTs parsed from db/graph.sql"
    return edges


NODES = _parse_nodes()
EDGES = _parse_edges()
ADJ: dict[str, list[str]] = {node_id: [] for node_id in NODES}
for _e in EDGES:
    ADJ[_e["from_node"]].append(_e["to_node"])

SAMPLE_CSV = (SAMPLE_DATA_DIR / "tollingTripPricing_I95.csv").read_text()
# The originally-checked-in 18-row sample is a partial single-interval
# capture (missing the two same-zone-to-itself trips at each direction's
# terminal zone) and is left untouched -- it's asserted against exactly by
# lambdas/loader/tests/test_parse_xml.py. This refreshed file is a complete,
# single-interval capture of all 20 real zone pairs, pulled read-only from
# the production raw bucket for this graph's coverage check. See
# docs/toll-graph-spec.md "I-66 sample data note".
SAMPLE_XML = (SAMPLE_DATA_DIR / "tollingTripPricing-I66-refreshed.xml").read_text()


# --- Feed coverage (the drift alarm) ---------------------------------------


def test_every_i95_od_pair_has_exactly_one_edge_and_vice_versa():
    csv_od_pair_ids = {row.od_pair_id for row in parse_trip_pricing_csv(SAMPLE_CSV)}
    edge_od_pair_ids = [e["od_pair_id"] for e in EDGES if e["feed"] == "i95"]
    assert len(edge_od_pair_ids) == len(set(edge_od_pair_ids)), (
        "duplicate i95 od_pair_id edges"
    )
    assert set(edge_od_pair_ids) == csv_od_pair_ids


def test_every_i66_zone_pair_has_exactly_one_edge_and_vice_versa():
    xml_pairs = {
        (row.start_zone_id, row.end_zone_id)
        for row in parse_trip_pricing_xml(SAMPLE_XML)
    }
    edge_pairs = [
        (e["start_zone_id"], e["end_zone_id"]) for e in EDGES if e["feed"] == "i66"
    ]
    assert len(edge_pairs) == len(set(edge_pairs)), "duplicate i66 zone-pair edges"
    assert set(edge_pairs) == xml_pairs


# --- Integrity ---------------------------------------------------------------


def test_every_edge_endpoint_resolves_to_a_node():
    for e in EDGES:
        assert e["from_node"] in NODES, f"unknown from_node {e['from_node']}"
        assert e["to_node"] in NODES, f"unknown to_node {e['to_node']}"


def test_dynamic_edges_carry_exactly_one_price_key():
    for e in EDGES:
        has_od_pair = e["od_pair_id"] is not None
        has_zone_pair = e["start_zone_id"] is not None or e["end_zone_id"] is not None
        if e["feed"] == "i95":
            assert has_od_pair and not has_zone_pair, e
        elif e["feed"] == "i66":
            assert has_zone_pair and not has_od_pair, e
            assert e["start_zone_id"] is not None and e["end_zone_id"] is not None, e
        else:
            # Free junction connector: no feed, no price key at all.
            assert e["feed"] is None
            assert not has_od_pair and not has_zone_pair, e


# --- Traversability (BFS spot checks) ---------------------------------------


def _reachable(src: str, dst: str) -> bool:
    seen = {src}
    queue = deque([src])
    while queue:
        node = queue.popleft()
        if node == dst:
            return True
        for nxt in ADJ[node]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def test_i95x_reaches_i495x_via_springfield_junction():
    # Garrisonville (deep i95_express) -> Westpark (deep i495_express) has
    # no direct feed edge; only the Springfield junction connects them.
    assert _reachable("i95x:garrisonville", "i495x:westpark")


def test_i495x_reaches_i66_itb_east_end():
    assert _reachable("i495x:i66-jct", "i66:capital-beltway-begin")
    assert _reachable("i495x:i66-jct", "i66:spout-run")


def test_i66_itb_west_end_reaches_i495x():
    assert _reachable("i66:capital-beltway-end", "i495x:i66-jct")


def test_no_direct_i66_edge_crosses_eb_wb():
    # WB zones (32xx) and EB zones (31xx) are disjoint gantry chains in the
    # source feed -- reaching one from the other should only ever go back
    # out through the i495x junction, never a direct feed-priced edge.
    eb_zones = {3100, 3110, 3120, 3130}
    wb_zones = {3200, 3210, 3220, 3230}
    for e in EDGES:
        if e["feed"] != "i66":
            continue
        pair = {e["start_zone_id"], e["end_zone_id"]}
        assert pair <= eb_zones or pair <= wb_zones, e


# --- Semver sync (CI-enforced) ------------------------------------------------


def test_graph_schema_version_is_semver_and_matches_spec():
    sql_v = re.search(rf"graph schema version:\s*({SEMVER})", GRAPH_SQL, re.IGNORECASE)
    spec_v = re.search(rf"Graph schema version:\s*({SEMVER})", SPEC_MD, re.IGNORECASE)
    assert sql_v, "db/graph.sql missing a `-- graph schema version: X.Y.Z` line"
    assert spec_v, (
        "docs/toll-graph-spec.md missing a `Graph schema version: X.Y.Z` line"
    )
    assert sql_v.group(1) == spec_v.group(1), (
        f"graph.sql version {sql_v.group(1)} != spec version {spec_v.group(1)}"
    )


def test_node_and_edge_counts_match_documented_scale():
    # Not a strict requirement, but a cheap early warning if the seed and
    # the doc's stated inventory (§1/§4) drift apart.
    corridor_counts = Counter(NODES.values())
    assert corridor_counts == {"i95_express": 34, "i495_express": 18, "i66_itb": 8}
    # i95/i66 totals are already proven by the coverage tests' set-equality
    # checks against the feed files -- only the connector count needs a home.
    assert Counter(e["feed"] for e in EDGES)[None] == 5

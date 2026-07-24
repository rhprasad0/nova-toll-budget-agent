"""route tool: cheapest legitimate journey between two graph nodes.

A journey is the sequence of whole priced trips (each a complete graph_edge,
never a summed sub-segment) joined only by free corridor-crossing connectors
— a priced edge may never be followed directly by another priced edge. See
docs/toll-graph-spec.md's "Trips, not segments" and Traversal contract.

psycopg is only present in the deployed zip, not the dev/test venv, so the
connection is built with a lazy import inside _connect() — everything else
here must stay importable without it. See docs/agent-tools-spec.md §2 and
docs/toll-graph-spec.md's traversal contract.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import boto3
from strands import tool

# ponytail: connect recipe duplicated from lambdas/loader/handler.py; share a db.py if a third DB tool appears.
CA_BUNDLE_PATH = os.path.join(os.path.dirname(__file__), "rds-ca-bundle.pem")

CENTS = Decimal("0.01")

# Latest priced row per key, driven by the key set rather than by scanning
# history. The obvious DISTINCT ON over trip_pricing reads every row ever
# recorded (~1.16M and growing) to return ~337; Postgres has no loose index
# scan, so DISTINCT ON walks the whole index and the Unique node discards the
# rest -- and PG18's skip scan is a different optimization that does not help
# here. Feeding the known keys through LATERAL turns that into one index-only
# descent per key, which is constant work no matter how much history piles up.
# Keys come from graph_edge, already loaded a few lines above.
_PRICE_SQL_OD = """
    SELECT k.od_pair_id, p.zone_toll_rate_usd, p.link_status, p.interval_end_at
    FROM unnest(%(od_pair_ids)s::int[]) AS k(od_pair_id)
    CROSS JOIN LATERAL (
        SELECT zone_toll_rate_usd, link_status, interval_end_at
        FROM trip_pricing
        WHERE od_pair_id = k.od_pair_id
          AND interval_end_at <= %(at_time)s
        ORDER BY interval_end_at DESC
        LIMIT 1
    ) p
"""

# i66 prices by zone pair and always has od_pair_id NULL. The IS NULL is not
# redundant: it pins the index's leading column so the descent uses the full
# (od_pair_id, start_zone_id, end_zone_id, interval_end_at) prefix.
_PRICE_SQL_ZONE = """
    SELECT k.start_zone_id, k.end_zone_id,
           p.zone_toll_rate_usd, p.link_status, p.interval_end_at
    FROM unnest(%(start_zone_ids)s::int[], %(end_zone_ids)s::int[])
         AS k(start_zone_id, end_zone_id)
    CROSS JOIN LATERAL (
        SELECT zone_toll_rate_usd, link_status, interval_end_at
        FROM trip_pricing
        WHERE od_pair_id IS NULL
          AND start_zone_id = k.start_zone_id
          AND end_zone_id = k.end_zone_id
          AND interval_end_at <= %(at_time)s
        ORDER BY interval_end_at DESC
        LIMIT 1
    ) p
"""


@dataclass(frozen=True)
class PricedEdge:
    from_node: str
    to_node: str
    price_usd: Decimal
    link_status: str | None
    priced_at: datetime | None
    is_connector: bool


def _connect(*, host: str, port: int, dbname: str):
    import psycopg  # type: ignore[import-not-found]  # deployed-zip-only dependency; see module docstring.

    token = boto3.client("rds").generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername="agent_readonly"
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user="agent_readonly",
        password=token,
        sslmode="verify-full",
        sslrootcert=CA_BUNDLE_PATH,
    )


def _load_graph(at_time: datetime) -> tuple[set[str], list[PricedEdge]]:
    conn = _connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT node_id FROM graph_node")
            node_ids = {row[0] for row in cur.fetchall()}

            cur.execute(
                "SELECT from_node, to_node, feed, od_pair_id, start_zone_id, "
                "end_zone_id FROM graph_edge"
            )
            edge_rows = cur.fetchall()

            # Sorted so the emitted SQL parameters are stable between calls.
            od_ids = sorted({od for _, _, _, od, _, _ in edge_rows if od is not None})
            zone_pairs = sorted(
                {
                    (sz, ez)
                    for _, _, feed, od, sz, ez in edge_rows
                    if od is None and feed is not None
                }
            )

            cur.execute(_PRICE_SQL_OD, {"od_pair_ids": od_ids, "at_time": at_time})
            price_by_od: dict[int, tuple[Decimal, str, datetime]] = {
                od: (rate, link_status, priced_at)
                for od, rate, link_status, priced_at in cur.fetchall()
            }

            cur.execute(
                _PRICE_SQL_ZONE,
                {
                    "start_zone_ids": [sz for sz, _ in zone_pairs],
                    "end_zone_ids": [ez for _, ez in zone_pairs],
                    "at_time": at_time,
                },
            )
            price_by_zone: dict[tuple[int, int], tuple[Decimal, str, datetime]] = {
                (sz, ez): (rate, link_status, priced_at)
                for sz, ez, rate, link_status, priced_at in cur.fetchall()
            }
    finally:
        conn.close()

    edges: list[PricedEdge] = []
    for from_node, to_node, feed, od_pair_id, start_zone_id, end_zone_id in edge_rows:
        if feed is None:
            edges.append(
                PricedEdge(from_node, to_node, Decimal("0.00"), None, None, True)
            )
            continue
        price = (
            price_by_od.get(od_pair_id)
            if od_pair_id is not None
            else price_by_zone.get((start_zone_id, end_zone_id))
        )
        if price is None:
            continue  # no priced row at all -- drop conservatively, don't guess.
        rate, link_status, priced_at = price
        edges.append(
            PricedEdge(from_node, to_node, rate, link_status, priced_at, False)
        )

    return node_ids, edges


def _build_result(
    origin: str, destination: str, path: tuple[str, ...], by_key: dict
) -> dict:
    hops = []
    total = Decimal("0.00")
    priced_ats = []
    for from_node, to_node in zip(path, path[1:]):
        edge = by_key[(from_node, to_node)]
        total += edge.price_usd
        hops.append(
            {
                "from": from_node,
                "to": to_node,
                "price_usd": str(edge.price_usd.quantize(CENTS)),
                "link_status": edge.link_status,
                "priced_at": edge.priced_at.isoformat() if edge.priced_at else None,
            }
        )
        if edge.priced_at is not None:
            priced_ats.append(edge.priced_at)
    return {
        "origin": origin,
        "destination": destination,
        "hops": hops,
        "total_usd": str(total.quantize(CENTS)),
        "oldest_priced_at": min(priced_ats).isoformat() if priced_ats else None,
    }


def _shortest_path(
    origin: str, destination: str, node_ids, edges: list[PricedEdge]
) -> dict:
    if origin == destination:
        return {
            "error": f"origin and destination are both '{origin}'",
            "valid_nodes": sorted(node_ids),
        }
    if origin not in node_ids:
        return {
            "error": f"unknown origin node '{origin}'",
            "valid_nodes": sorted(node_ids),
        }
    if destination not in node_ids:
        return {
            "error": f"unknown destination node '{destination}'",
            "valid_nodes": sorted(node_ids),
        }

    open_edges = [e for e in edges if e.link_status != "CLOSED"]
    by_key = {(e.from_node, e.to_node): e for e in open_edges}
    adjacency: dict[str, list[str]] = {}
    for e in open_edges:
        adjacency.setdefault(e.from_node, []).append(e.to_node)

    # Exhaustive DFS over legitimate journeys. A priced edge is a complete
    # billed trip, never a road segment (toll-graph-spec "Trips, not
    # segments"), so a priced edge may never be followed directly by another
    # priced edge -- a free connector must sit between them. That single rule
    # bans both within-corridor chaining (summing sub-trips to undercut the
    # real direct trip's price) and overshoot-and-return through a reversible
    # lane's opposite-direction edge. Connector-to-connector stays legal. The
    # graph is tiny (60 nodes, 342 edges, measured <=3 legitimate journeys per
    # node pair, 1-6 edges each) so plain exhaustive DFS is cheap -- no need
    # for a shortest-path algorithm at all.
    journeys: list[tuple[Decimal, tuple[str, ...]]] = []

    def dfs(
        node: str, path: tuple[str, ...], cost: Decimal, last_was_priced: bool
    ) -> None:
        if node == destination:
            journeys.append((cost, path))
            return
        for neighbor in adjacency.get(node, []):
            if neighbor in path:
                continue  # loop prevention
            edge = by_key[(node, neighbor)]
            if last_was_priced and not edge.is_connector:
                continue  # priced edge can't follow priced edge without a connector
            dfs(
                neighbor,
                path + (neighbor,),
                cost + edge.price_usd,
                not edge.is_connector,
            )

    dfs(origin, (origin,), Decimal("0.00"), False)

    if not journeys:
        return {
            "error": f"no route from '{origin}' to '{destination}'",
            "valid_nodes": sorted(node_ids),
        }

    # min over (cost, path): tuple comparison gives the lexicographic
    # node_id tie-break for equal-cost journeys, deterministically.
    _, best_path = min(journeys)
    return _build_result(origin, destination, best_path, by_key)


@tool
def route(origin: str, destination: str, at_time: datetime) -> dict:
    """Cheapest legitimate journey between two toll graph nodes at a given time.

    Loads the full toll graph (60 nodes, 342 edges) plus each dynamic edge's
    latest trip_pricing row at or before at_time, then enumerates every
    legitimate journey by DFS: a sequence of whole priced trips joined only
    by free connectors, since a priced edge is a complete billed trip and is
    never chained directly to another priced edge within a corridor. The
    cheapest journey wins. Edges whose latest row is CLOSED are excluded
    regardless of rate -- availability lives in link_status, never price.
    Equal-cost ties break on lexicographic node_id so identical inputs always
    return the identical path.

    Args:
        origin: Origin node_id slug, e.g. 'i95x:garrisonville'. Must come
            from the graph_node list.
        destination: Destination node_id slug, e.g. 'i495x:westpark'.
        at_time: Required ISO-8601 instant; prices use the latest interval at
            or before this time. Prices are dynamic and the express lanes are
            reversible, so a quote is only meaningful against a stated time --
            pass the current UTC time for a "right now" answer. Use the clock
            reading you were given; never guess it.

    Returns:
        dict: on success, {"origin","destination","hops","total_usd",
        "oldest_priced_at"}; on failure (unknown node, no open path, or
        origin == destination), {"error","valid_nodes"} with the full node
        list so the model can correct the slug without another round trip.
    """
    node_ids, edges = _load_graph(at_time)
    return _shortest_path(origin, destination, node_ids, edges)

"""Static catalog tools: list_tables + describe_table.

Hand-curated from db/schema.sql (trip_pricing) and db/graph.sql (graph_node,
graph_edge) -- see docs/agent-tools-spec.md §2. No DB access: the schema is
versioned and frozen, so a live introspection query buys nothing but
latency. Drift protection is the existing schema-version tests, not a sync
mechanism here.
"""

from strands import tool

_TABLES = {
    "trip_pricing": {
        "purpose": (
            "Toll rates per 10-min poll (i95 history from 2026-04-17; "
            "i66 from cloud go-live)"
        ),
        "columns": [
            {
                "name": "id",
                "type": "bigint",
                "nullable": False,
                "description": "Identity primary key.",
            },
            {
                "name": "feed",
                "type": "text",
                "nullable": False,
                "description": "Source feed, 'i95' or 'i66'.",
            },
            {
                "name": "interval_start_at",
                "type": "timestamptz",
                "nullable": True,
                "description": "Poll interval start. i66 only.",
            },
            {
                "name": "interval_end_at",
                "type": "timestamptz",
                "nullable": False,
                "description": "Poll interval end -- the latest-price ordering key.",
            },
            {
                "name": "current_at",
                "type": "timestamptz",
                "nullable": True,
                "description": "Feed-reported current timestamp. i95 only.",
            },
            {
                "name": "calculated_at",
                "type": "timestamptz",
                "nullable": False,
                "description": "When the feed calculated this price.",
            },
            {
                "name": "corridor_id",
                "type": "integer",
                "nullable": False,
                "description": "Numeric corridor identifier.",
            },
            {
                "name": "corridor_name",
                "type": "text",
                "nullable": False,
                "description": "Corridor display name. Dirty raw text -- do not join/filter on it.",
            },
            {
                "name": "od_pair_id",
                "type": "integer",
                "nullable": True,
                "description": "i95/i495 price key. NULL for i66 rows (which key by zone ids instead).",
            },
            {
                "name": "od_pair_name",
                "type": "text",
                "nullable": True,
                "description": "OD pair display name. Dirty raw text -- do not join/filter on it.",
            },
            {
                "name": "start_zone_id",
                "type": "integer",
                "nullable": False,
                "description": "Trip start zone id. i66 price key (with end_zone_id).",
            },
            {
                "name": "start_zone_name",
                "type": "text",
                "nullable": True,
                "description": "Start zone display name. Dirty raw text -- do not join/filter on it.",
            },
            {
                "name": "end_zone_id",
                "type": "integer",
                "nullable": False,
                "description": "Trip end zone id. i66 price key (with start_zone_id).",
            },
            {
                "name": "end_zone_name",
                "type": "text",
                "nullable": False,
                "description": "End zone display name. Dirty raw text -- do not join/filter on it.",
            },
            {
                "name": "zone_toll_rate_usd",
                "type": "numeric(10,2)",
                "nullable": False,
                "description": "Priced rate for this trip. Not an availability signal -- see notes.",
            },
            {
                "name": "link_status",
                "type": "text",
                "nullable": False,
                "description": "Availability of this priced trip; 'NOT_APPLICABLE' where the feed has no concept of it (i66).",
            },
            {
                "name": "s3_key",
                "type": "text",
                "nullable": False,
                "description": "Raw source object provenance.",
            },
            {
                "name": "ingested_at",
                "type": "timestamptz",
                "nullable": False,
                "description": "When the loader wrote this row.",
            },
        ],
        "notes": [
            "Availability lives in link_status, never rate > 0. A row can be "
            "CLOSED with a stale nonzero rate, or legitimately open at $0.00 "
            "(I-66 off-peak).",
            "Latest price = ORDER BY interval_end_at DESC LIMIT 1 per key, or "
            "DISTINCT ON (od_pair_id) ... ORDER BY od_pair_id, interval_end_at "
            "DESC for all-at-once.",
            "Keys are numeric. i95/i495 rows price by od_pair_id; i66 rows "
            "price by the start_zone_id/end_zone_id pair (od_pair_id is NULL "
            "for i66). Never join or filter on od_pair_name/*_zone_name -- "
            "raw names are dirty.",
            "Trips, not segments. Each row is a complete priced trip; summing "
            "rows that cover the same pavement produces wrong numbers.",
        ],
    },
    "graph_node": {
        "purpose": "60 named toll-network access points (curated)",
        "columns": [
            {
                "name": "node_id",
                "type": "text",
                "nullable": False,
                "description": "Stable slug primary key, e.g. 'i95x:garrisonville'.",
            },
            {
                "name": "name",
                "type": "text",
                "nullable": False,
                "description": "Canonical display name (hand-curated).",
            },
            {
                "name": "corridor",
                "type": "text",
                "nullable": False,
                "description": "One of i95_express, i495_express, i66_itb.",
            },
        ],
        "notes": [
            "Join edges to nodes on node_id slugs; never re-parse display names."
        ],
    },
    "graph_edge": {
        "purpose": "342 priced trips / free connectors linking nodes",
        "columns": [
            {
                "name": "from_node",
                "type": "text",
                "nullable": False,
                "description": "graph_node.node_id this edge starts at.",
            },
            {
                "name": "to_node",
                "type": "text",
                "nullable": False,
                "description": "graph_node.node_id this edge ends at.",
            },
            {
                "name": "feed",
                "type": "text",
                "nullable": True,
                "description": "'i95' or 'i66'; NULL means a free junction connector.",
            },
            {
                "name": "od_pair_id",
                "type": "int",
                "nullable": True,
                "description": "i95/i495 price key into trip_pricing.od_pair_id.",
            },
            {
                "name": "start_zone_id",
                "type": "int",
                "nullable": True,
                "description": "i66 price key into trip_pricing.start_zone_id (with end_zone_id).",
            },
            {
                "name": "end_zone_id",
                "type": "int",
                "nullable": True,
                "description": "i66 price key into trip_pricing.end_zone_id (with start_zone_id).",
            },
        ],
        "notes": [
            "Join on node_id slugs; never re-parse display names.",
            "feed IS NULL means a free connector -- $0.00, not missing data.",
            "CLOSED link_status (in trip_pricing, at the edge's price key) "
            "governs availability regardless of rate.",
        ],
    },
}


@tool
def list_tables() -> dict:
    """List the three queryable tables with a one-line purpose each.

    Returns:
        dict: {"tables": [{"name", "purpose"}, ...]} for trip_pricing,
        graph_node, and graph_edge.
    """
    return {
        "tables": [
            {"name": name, "purpose": info["purpose"]} for name, info in _TABLES.items()
        ]
    }


@tool
def describe_table(table: str) -> dict:
    """Describe one queryable table's columns and semantic footguns.

    Args:
        table: One of "trip_pricing", "graph_node", "graph_edge" -- exactly
            as returned by list_tables.

    Returns:
        dict: {"table", "columns": [{"name","type","nullable","description"}...],
        "notes": [str, ...]} -- the notes are the pitfalls a model must know
        to write correct SQL against this table (link_status semantics,
        numeric-key joins, latest-price pattern, trips-not-segments).
    """
    if table not in _TABLES:
        raise ValueError(
            f"unknown table {table!r}; valid tables are: {', '.join(_TABLES)}"
        )
    info = _TABLES[table]
    return {"table": table, "columns": info["columns"], "notes": info["notes"]}

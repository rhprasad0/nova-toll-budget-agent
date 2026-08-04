"""i66_route: resolve a human trip between two I-66 ITB interchanges to its
route and its price, as of a given time.

Route resolution is a pure route-map lookup against the committed
oracles/i66.json -- no DB, no network, no multi-hop chaining. VDOT's own
calculator already enumerates every valid direction+entry+exit combination
directly (96 pairs over 17 interchanges), so this is a single flat lookup,
never pathfinding: "where an oracle exists, prefer reading it over
re-deriving it" (docs/oracle-findings.md section 3).

Pricing is a second stage, run only after a successful route resolution: an
omitted at_time reads the current VDOT view, while an explicit at_time reads
trip_pricing_i66 history. Neither is "the price this instant"; see the
at_time Args entry below and docs/oracle-findings.md section 7 for why. A
missing price is a hard error for the whole call.

The calling agent matches vague locations to this tool's committed oracle
labels before calling it.

See docs/oracle-tools-spec.md for the full contract and known limitations.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from strands import tool  # pyright: ignore[reportUnknownVariableType]

from agent_tools import _oracle_route

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching its current committed location. If this ever ships in
# a deployment zip, the build step must land oracles/i66.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i66.json"
_ORACLE = json.loads(_ORACLE_PATH.read_text())
_NODES: _oracle_route.Nodes = _ORACLE["nodes"]
_PAIRS: _oracle_route.Pairs = _ORACLE["pairs"]

_LABEL_INDEX = _oracle_route.label_index(_NODES)
_POSITION = {
    node_id: position
    for position, node_ids in enumerate(
        (
            ("1",),
            ("2", "3", "5"),
            ("4",),
            ("6",),
            ("7",),
            ("10",),
            ("11",),
            ("8", "9", "12"),
            ("13", "17"),
            ("14",),
            ("15",),
            ("16",),
        )
    )
    for node_id in node_ids
}


def _lookup(origin: str, destination: str) -> _oracle_route.JsonObject:
    result = _oracle_route.lookup(
        origin,
        destination,
        nodes=_NODES,
        pairs=_PAIRS,
        label_idx=_LABEL_INDEX,
        oracle_name="i66",
        build_legs=lambda p: [
            {"start_zone_id": p["start_zone"], "end_zone_id": p["end_zone"]}
        ],
    )
    if result.get("error", "").startswith("no direct trip"):
        result.update(
            _oracle_route.directional_mismatch(
                origin,
                destination,
                nodes=_NODES,
                pairs=_PAIRS,
                label_idx=_LABEL_INDEX,
                position=_POSITION.__getitem__,
                increasing_direction="EB",
                decreasing_direction="WB",
                preferred={
                    ("Lee Highway - Scott Street", "exit", "EB"): [
                        "Fairfax Drive",
                        "Lee Highway - Spout Run Parkway",
                    ]
                },
            )
        )
    return result


_CURRENT_I66_PRICE_SQL = """
SELECT start_zone_id, end_zone_id, corridor_name, zone_toll_rate_usd,
       interval_end_at, calculated_at
FROM current_trip_pricing_i66
WHERE start_zone_id = %(start_zone_id)s
  AND end_zone_id = %(end_zone_id)s
"""

_I66_PRICE_SQL = """
SELECT start_zone_id, end_zone_id, corridor_name, zone_toll_rate_usd,
       interval_end_at, calculated_at
FROM trip_pricing_i66
WHERE start_zone_id = %(start_zone_id)s
  AND end_zone_id = %(end_zone_id)s
  AND interval_end_at <= %(at_time)s
ORDER BY interval_end_at DESC
LIMIT 1
"""


def _price_i66_leg(
    cur: _oracle_route.Cursor,
    leg_key: _oracle_route.JsonObject,
    at_time: datetime | None,
) -> _oracle_route.JsonObject:
    """Current VDOT price, or VDOT history at an explicit time.

    i66 has no live-fallback source (unlike i95's trip_pricing_i95_live),
    so a miss here is always a hard error, never a default.
    """
    start_zone_id, end_zone_id = leg_key["start_zone_id"], leg_key["end_zone_id"]
    cur.execute(
        _I66_PRICE_SQL if at_time is not None else _CURRENT_I66_PRICE_SQL,
        {
            "start_zone_id": start_zone_id,
            "end_zone_id": end_zone_id,
            **({"at_time": at_time} if at_time is not None else {}),
        },
    )
    row = cur.fetchone()
    if row is None:
        source = (
            f"at or before {at_time.isoformat()} in trip_pricing_i66"
            if at_time is not None
            else "in current_trip_pricing_i66"
        )
        raise _oracle_route.PricingError(
            f"no price found for zone pair ({start_zone_id}, {end_zone_id}) {source}"
        )
    _, _, corridor_name, rate, interval_end_at, calculated_at = row
    return {
        "start_zone_id": start_zone_id,
        "end_zone_id": end_zone_id,
        "price_usd": str(rate),
        "corridor_name": corridor_name,
        "priced_as_of": interval_end_at.isoformat(),
        "observed_at": calculated_at.isoformat(),
    }


@tool
def i66_route(
    origin: str, destination: str, at_time: str | None = None
) -> _oracle_route.JsonObject:
    """Price one direct I-66 Inside-the-Beltway Express Lanes trip.

    Use only for one oracle-supported I-66 leg; do not use it to plan or
    combine corridors.

    Args:
        origin: I-66 interchange label or raw oracle node ID.
        destination: I-66 interchange label or raw oracle node ID.
        at_time: Optional ISO-8601 travel time; offset-less values use
            America/New_York. Omit for the current VDOT view.

    Returns:
        dict: Success includes resolved ``entry``/``exit``, one ``legs`` item,
        decimal-string ``total_usd``, and VDOT ``priced_as_of`` and
        ``observed_at`` timestamps. A wrong-way endpoint returns
        ``one_way_mismatch`` before pricing. Failure otherwise returns
        ``{"error", "valid_options"}``.
    """
    return _oracle_route.run(
        "i66_route",
        origin,
        destination,
        at_time,
        lookup_fn=_lookup,
        price_fn=_price_i66_leg,
    )

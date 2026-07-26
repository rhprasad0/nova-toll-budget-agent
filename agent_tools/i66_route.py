"""i66_route: resolve a human trip between two I-66 ITB interchanges to its
route and its price, as of a given time.

Route resolution is a pure route-map lookup against the committed
oracles/i66.json -- no DB, no network, no multi-hop chaining. VDOT's own
calculator already enumerates every valid direction+entry+exit combination
directly (96 pairs over 17 interchanges), so this is a single flat lookup,
never pathfinding: "where an oracle exists, prefer reading it over
re-deriving it" (docs/oracle-findings.md section 3).

Pricing is a second stage, run only after a successful route resolution: the
resolved (start_zone_id, end_zone_id) key is looked up in trip_pricing_i66
over RDS, as the most recently published row at or before the caller's
at_time (default: now, America/New_York) -- never "the price this instant";
see the at_time Args entry below and docs/oracle-findings.md section 7 for
why. A missing price is a hard error for the whole call.

Unsure of the exact interchange label? Call find_toll_locations first --
it turns a vague location or a misspelling into the exact label string
this tool expects, across all corridors, without a failing call here.

See docs/oracle-tools-spec.md for the full contract and known limitations.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from strands import tool

# agent_tools/ has no __init__.py (flat siblings) and this module is
# imported both as a flat top-level module (agent_tools/tests/conftest.py's
# sys.path insert) and as agent_tools.i66_route (dotted) -- neither form
# puts agent_tools/ itself on sys.path, so a plain "import _oracle_route"
# would fail under the dotted form. Ensuring our own directory is on
# sys.path here works under both.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _oracle_route  # noqa: E402

logger = logging.getLogger(__name__)

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching its current committed location. If this ever ships in
# a deployment zip, the build step must land oracles/i66.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i66.json"
_ORACLE = json.loads(_ORACLE_PATH.read_text())
_NODES: dict = _ORACLE["nodes"]
_PAIRS: list = _ORACLE["pairs"]

_LABEL_INDEX = _oracle_route.label_index(_NODES)

# Local aliases so tests can monkeypatch these by name on this module (the
# established convention here and in i95_route.py/i495_route.py), even
# though the implementation now lives in the shared _oracle_route module.
_resolve_at_time = _oracle_route.resolve_at_time
_env_connect = _oracle_route.env_connect


def _lookup(origin: str, destination: str) -> dict:
    return _oracle_route.lookup(
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


_I66_PRICE_SQL = """
SELECT start_zone_id, end_zone_id, corridor_name, zone_toll_rate_usd, interval_end_at
FROM trip_pricing_i66
WHERE start_zone_id = %(start_zone_id)s
  AND end_zone_id = %(end_zone_id)s
  AND interval_end_at <= %(at_time)s
ORDER BY interval_end_at DESC
LIMIT 1
"""


def _price_i66_leg(
    cur, *, start_zone_id: int, end_zone_id: int, at_time: datetime
) -> dict | None:
    """Most recently published trip_pricing_i66 row at or before at_time, or
    None if no such row exists -- i66 has no live-fallback source (unlike
    i95's trip_pricing_i95_live), so a miss here is always a hard error at
    the call site, never a default.
    """
    cur.execute(
        _I66_PRICE_SQL,
        {
            "start_zone_id": start_zone_id,
            "end_zone_id": end_zone_id,
            "at_time": at_time,
        },
    )
    row = cur.fetchone()
    if row is None:
        return None
    _, _, corridor_name, rate, interval_end_at = row
    return {
        "start_zone_id": start_zone_id,
        "end_zone_id": end_zone_id,
        "price_usd": str(rate),
        "corridor_name": corridor_name,
        "priced_as_of": interval_end_at.isoformat(),
    }


@tool
def i66_route(origin: str, destination: str, at_time: str | None = None) -> dict:
    """Resolve a trip on VDOT's I-66 Inside-the-Beltway toll calculator to its route and price.

    Looks up origin/destination against oracles/i66.json's 96 published
    entry/exit trips (17 interchanges) -- a flat, direct lookup, never
    multi-hop routing. Every valid direction+entry+exit combination is
    already enumerated by VDOT itself. The resolved leg is then priced
    against trip_pricing_i66 over RDS.

    Args:
        origin: Interchange label (e.g. 'Fairfax Drive'), case-insensitive,
            or the oracle's raw node id (e.g. '4') as a fallback.
        destination: Same rules as origin.
        at_time: ISO-8601 timestamp (e.g. '2026-07-26T14:32:00' or with an
            explicit UTC offset); a value with no offset is assumed
            America/New_York. Defaults to now (America/New_York) if omitted.
            The price returned is the most recently *published* row at or
            before this time, never "the price this instant" -- VDOT's own
            feed trails real-time by roughly 10-20 minutes
            (docs/oracle-findings.md section 7), and this tool reports that
            lag honestly via each leg's priced_as_of rather than papering
            over it.

    Returns:
        dict: On success, {"origin", "destination", "direction": "EB"|"WB",
        "entry": {"node_id", "label"}, "exit": {"node_id", "label"},
        "at_time": str (the resolved, ISO-8601 time actually used),
        "legs": [{"start_zone_id", "end_zone_id", "price_usd": str,
        "corridor_name", "priced_as_of": str}], "total_usd": str} -- legs
        has exactly one entry for i66. price_usd/total_usd are decimal
        strings (never float). On failure, {"error": str, "valid_options":
        [str, ...]} -- the full interchange label list on an unknown
        identifier, the reachable destination labels on a known origin with
        no direct trip to the given destination, or a malformed at_time, so
        the caller can self-correct; valid_options is empty for a pricing
        miss or a bad at_time, since retrying the same inputs won't fix
        either.
    """
    result = _lookup(origin, destination)
    if "error" in result:
        logger.info(
            "i66_route miss origin=%r destination=%r error=%r",
            origin,
            destination,
            result["error"],
        )
        return result

    try:
        resolved_at_time = _resolve_at_time(at_time)
    except ValueError as e:
        error = {"error": f"invalid at_time {at_time!r}: {e}", "valid_options": []}
        logger.info(
            "i66_route miss origin=%r destination=%r error=%r",
            origin,
            destination,
            error["error"],
        )
        return error

    leg_key = result["legs"][0]
    conn = _env_connect()
    try:
        with conn.cursor() as cur:
            priced_leg = _price_i66_leg(
                cur,
                start_zone_id=leg_key["start_zone_id"],
                end_zone_id=leg_key["end_zone_id"],
                at_time=resolved_at_time,
            )
    finally:
        conn.close()

    if priced_leg is None:
        error = {
            "error": (
                f"no price found for zone pair ({leg_key['start_zone_id']}, "
                f"{leg_key['end_zone_id']}) at or before "
                f"{resolved_at_time.isoformat()} in trip_pricing_i66"
            ),
            "valid_options": [],
        }
        logger.info(
            "i66_route miss origin=%r destination=%r error=%r",
            origin,
            destination,
            error["error"],
        )
        return error

    response = _oracle_route.build_response(result, [priced_leg], resolved_at_time)
    logger.info(
        "i66_route ok origin=%r destination=%r entry=%s exit=%s direction=%s "
        "at_time=%s total_usd=%s legs=%s",
        origin,
        destination,
        result["entry"]["node_id"],
        result["exit"]["node_id"],
        result["direction"],
        response["at_time"],
        response["total_usd"],
        response["legs"],
    )
    return response

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

See docs/oracle-tools-spec.md for the full contract and known limitations.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
from strands import tool

logger = logging.getLogger(__name__)

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching its current committed location. If this ever ships in
# a deployment zip, the build step must land oracles/i66.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i66.json"
_ORACLE = json.loads(_ORACLE_PATH.read_text())
_NODES: dict = _ORACLE["nodes"]
_PAIRS: list = _ORACLE["pairs"]

_EASTERN = ZoneInfo("America/New_York")


def _label_index(nodes: dict) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        idx.setdefault(node["label"].casefold(), []).append(node_id)
    return idx


_LABEL_INDEX = _label_index(_NODES)


def _resolve(query: str) -> list[str]:
    """Candidate node ids for a caller-supplied label (case-insensitive) or raw node id."""
    if query in _NODES:
        return [query]
    return _LABEL_INDEX.get(query.casefold(), [])


# ponytail: resolution/matching logic duplicated with i95_route.py; extract
# if a third oracle-backed tool needs the same shape.
def _lookup(origin: str, destination: str) -> dict:
    # Some interchanges are entry-only or exit-only (e.g. Westmoreland St can
    # never be an origin), so the two suggestion lists are role-filtered --
    # suggesting a label that can never fill the role being asked about would
    # guarantee the caller's next call also fails.
    origin_labels = sorted({_NODES[p["entry"]]["label"] for p in _PAIRS})
    destination_labels = sorted({_NODES[p["exit"]]["label"] for p in _PAIRS})

    origin_ids = _resolve(origin)
    if not origin_ids:
        return {
            "error": f"unknown origin {origin!r}: no matching label or node id in the i66 oracle",
            "valid_options": origin_labels,
        }
    destination_ids = _resolve(destination)
    if not destination_ids:
        return {
            "error": f"unknown destination {destination!r}: no matching label or node id in the i66 oracle",
            "valid_options": destination_labels,
        }

    matches = [
        p for p in _PAIRS if p["entry"] in origin_ids and p["exit"] in destination_ids
    ]

    if not matches:
        reachable = sorted(
            {_NODES[p["exit"]]["label"] for p in _PAIRS if p["entry"] in origin_ids}
        )
        return {
            "error": f"no direct trip from {origin!r} to {destination!r} in the i66 oracle",
            "valid_options": reachable,
        }

    if len(matches) > 1:
        # Unreachable today -- verified 96/96 pairs unique on (entry, exit).
        # Guarded for when scripts/fetch_i66_oracle.py next refreshes
        # oracles/i66.json and that invariant might not hold.
        return {
            "error": f"ambiguous trip: {origin!r} to {destination!r} matches {len(matches)} entry/exit combinations",
            "valid_options": sorted(
                {p["entry"] for p in matches} | {p["exit"] for p in matches}
            ),
        }

    p = matches[0]
    return {
        "origin": origin,
        "destination": destination,
        "direction": p["direction"],
        "entry": {"node_id": p["entry"], "label": _NODES[p["entry"]]["label"]},
        "exit": {"node_id": p["exit"], "label": _NODES[p["exit"]]["label"]},
        "legs": [{"start_zone_id": p["start_zone"], "end_zone_id": p["end_zone"]}],
    }


def _resolve_at_time(at_time: str | None, *, now=None) -> datetime:
    """Parse the caller's at_time, defaulting to now (America/New_York).

    A naive (no-offset) string is assumed America/New_York. Raises
    ValueError on an unparseable string -- the caller turns that into an
    error response before any DB connection opens. `now` is a zero-arg
    callable injection point for tests; production callers never pass it.
    """
    if at_time is None:
        return (now or (lambda: datetime.now(_EASTERN)))()
    dt = datetime.fromisoformat(at_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_EASTERN)
    return dt


def _env_connect():
    """Connect to RDS as pricing_reader via IAM auth.

    Lazy `import psycopg`: it isn't in the fast dev/test path (mirrors
    infra/build/loader/handler.py's _connect(), which has the same
    constraint for the deployed Lambda zip). boto3 stays a top-level import
    -- it's already a main dependency and carries no such cost.
    """
    import psycopg  # type: ignore[import-not-found]

    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    user = os.environ["DB_USER"]
    token = boto3.client("rds").generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=user
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=os.environ["DB_NAME"],
        user=user,
        password=token,
        sslmode="verify-full",
        sslrootcert=os.environ["DB_CA_BUNDLE_PATH"],
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


def _build_response(result: dict, priced_legs: list[dict], at_time: datetime) -> dict:
    total = sum((Decimal(leg["price_usd"]) for leg in priced_legs), Decimal("0"))
    return {
        **result,
        "at_time": at_time.isoformat(),
        "legs": priced_legs,
        "total_usd": str(total),
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

    response = _build_response(result, [priced_leg], resolved_at_time)
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

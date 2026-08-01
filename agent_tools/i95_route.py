"""i95_route: resolve a human trip between two 95/395 Express Lanes ramps
to its route and its price, as of a given time.

Route resolution is a pure route-map lookup against the committed
oracles/i95.json -- the same shared source i495_route.py loads, filtered
here to the 307 of 685 published pairs that start and end on the 95/395
Express Lanes (a node's own "path" field does not start with "495"). VDOT
doesn't split 395 into its own corridor_name -- I-95-NB/SB covers both,
matching expresslanes.com's own "95 Express Lanes" facility bundling 395
too. "Where an oracle exists, prefer reading it over re-deriving it"
(docs/oracle-findings.md section 3), and this tool never chains a 95/395
leg onto a 495 leg to synthesize a cross-corridor trip -- see i495_route's
module docstring and docs/oracle-findings.md section 8 for why.
``i95_junction_leg`` handles the direction-aware 95 side of a
cross-corridor trip and explicitly leaves the road to the Braddock I-495
boundary unpriced.

Pricing is a second stage, run only after a successful route resolution: an
omitted at_time reads the current VDOT view, while an explicit at_time reads
trip_pricing_i95 history. Neither is "the price this instant"; see the
at_time Args entry below and docs/oracle-findings.md section 7 for why. A row only
counts as priceable if its lane is actually open: link_status must exactly
match its own corridor's "{DIRECTION}_OPEN" (CLOSED/NO_DETERMINATION/
*_CLOSING/*_OPENING all fail) -- docs/poller-spec.md's "Rate/status
independence" warning: rows can be CLOSED with a stale nonzero rate, and
availability lives in link_status, never in rate > 0. A missing or
unavailable price is a hard error for the whole call; there is no
live-fallback source for this table (that fallback existed solely to cover
the 16 od_pair_ids that only ever appeared on a now-unsupported
cross-corridor leg -- see i495_route.py and docs/oracle-findings.md
section 8).

The calling agent matches vague locations to this tool's committed oracle
labels before calling it.

See docs/oracle-tools-spec.md for the full contract and known limitations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from strands import tool  # pyright: ignore[reportUnknownVariableType]

from agent_tools import _oracle_route

logger = logging.getLogger(__name__)

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching its current committed location. If this ever ships in
# a deployment zip, the build step must land oracles/i95.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i95.json"
_ALL_ORACLE = json.loads(_ORACLE_PATH.read_text())
_ALL_NODES: _oracle_route.Nodes = _ALL_ORACLE["nodes"]
_ALL_PAIRS: _oracle_route.Pairs = _ALL_ORACLE["pairs"]


def _is_95_395(node_id: str) -> bool:
    return not _ALL_NODES[node_id]["path"].startswith("495")


# Every within-95/395 pair is single-leg (verified: 0/307 have more than
# one od_pair_id) -- there's no composite-trip concept in this tool at all.
_PAIRS = [p for p in _ALL_PAIRS if _is_95_395(p["entry"]) and _is_95_395(p["exit"])]
_NODES = {nid: _ALL_NODES[nid] for p in _PAIRS for nid in (p["entry"], p["exit"])}

_LABEL_INDEX = _oracle_route.label_index(_NODES)


def _lookup(origin: str, destination: str) -> _oracle_route.JsonObject:
    return _oracle_route.lookup(
        origin,
        destination,
        nodes=_NODES,
        pairs=_PAIRS,
        label_idx=_LABEL_INDEX,
        oracle_name="i95",
        build_legs=lambda p: [{"od_pair_id": p["ods"][0]}],
    )


# Verified live against RDS (2026-07-26): these are the only corridor_name
# values seen on a within-95/395 od_pair_id, and the only ones for which
# link_status carries a real open/closed signal.
_REQUIRED_LINK_STATUS = {
    "I-95-NB": "NORTHBOUND_OPEN",
    "I-95-SB": "SOUTHBOUND_OPEN",
}

_JUNCTION_BOUNDARIES = {
    "Northbound": "Franconia-Springfield Parkway/Route 289",
    "Southbound": "I-395 Near Edsall Road",
}
_JUNCTION_MOVEMENTS = {"i95_to_i495", "i495_to_i95"}
_STATUS_OD_PAIR_IDS = {"Northbound": 1132, "Southbound": 1151}
_I495_BOUNDARY = {
    "label": "I-495 Near Braddock Road",
    "entry_node_id": "191NO",
    "exit_node_id": "191SD",
}

_CURRENT_I95_PRICE_SQL = """
SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at,
       calculated_at, link_status
FROM current_trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
"""

_I95_PRICE_SQL = """
SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at,
       calculated_at, link_status
FROM trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
  AND interval_end_at <= %(at_time)s
ORDER BY interval_end_at DESC
LIMIT 1
"""


def _fetch_i95_row(
    cur: _oracle_route.Cursor, od_pair_id: int, at_time: datetime | None
) -> tuple[Any, ...] | None:
    cur.execute(
        _I95_PRICE_SQL if at_time is not None else _CURRENT_I95_PRICE_SQL,
        {
            "od_pair_id": od_pair_id,
            **({"at_time": at_time} if at_time is not None else {}),
        },
    )
    return cur.fetchone()


def _price_i95_leg(
    cur: _oracle_route.Cursor,
    leg_key: _oracle_route.JsonObject,
    at_time: datetime | None,
) -> _oracle_route.JsonObject:
    """Current VDOT price, or VDOT history at an explicit time.

    Raises PricingError if there's no row at all, if corridor_name isn't
    one of the two this tool's oracle filter should ever produce (schema
    drift), or if the row's lane isn't open for its own corridor/direction.
    """
    od_pair_id = leg_key["od_pair_id"]
    row = _fetch_i95_row(cur, od_pair_id, at_time)
    if row is None:
        source = (
            f"at or before {at_time.isoformat()} in trip_pricing_i95"
            if at_time is not None
            else "in current_trip_pricing_i95"
        )
        raise _oracle_route.PricingError(
            f"no price found for od_pair_id {od_pair_id} {source}"
        )

    _, corridor_name, rate, interval_end_at, calculated_at, link_status = row
    required_status = _REQUIRED_LINK_STATUS.get(corridor_name)
    if required_status is None:
        raise _oracle_route.PricingError(
            f"unrecognized corridor_name {corridor_name!r} for od_pair_id {od_pair_id}"
        )
    if link_status != required_status:
        raise _oracle_route.PricingError(
            f"od_pair_id {od_pair_id} is not currently available: "
            f"link_status={link_status!r} for corridor {corridor_name!r} "
            f"(requires {required_status!r})"
        )

    return {
        "od_pair_id": od_pair_id,
        "price_usd": str(rate),
        "corridor_name": corridor_name,
        "priced_as_of": interval_end_at.isoformat(),
        "observed_at": calculated_at.isoformat(),
    }


def _junction_lookup(
    location: str, movement: str, direction: str
) -> _oracle_route.JsonObject | None:
    boundary = _JUNCTION_BOUNDARIES[direction]
    origin, destination = (
        (location, boundary) if movement == "i95_to_i495" else (boundary, location)
    )
    result = _lookup(origin, destination)
    if "error" in result or result["direction"] != direction:
        return None
    return result


def _lane_status(row: tuple[Any, ...] | None, direction: str) -> str:
    if row is None:
        return "UNAVAILABLE"
    expected_corridor = "I-95-NB" if direction == "Northbound" else "I-95-SB"
    return row[5] if row[1] == expected_corridor else "UNAVAILABLE"


@tool
def i95_junction_leg(
    location: str,
    movement: Literal["i95_to_i495", "i495_to_i95"],
    at_time: str | None = None,
) -> _oracle_route.JsonObject:
    """Price the I-95/395 leg beside an unpriced I-95/I-495 junction.

    Call only for a ``junction`` step from ``plan_toll_route``. The returned
    boundary is priced only when exactly one reversible direction is open;
    this tool never prices the gap to I-495 Near Braddock Road.

    Args:
        location: Non-junction I-95/395 ramp label or raw oracle node ID.
        movement: ``i95_to_i495`` when leaving I-95/395; ``i495_to_i95`` when entering.
        at_time: Optional ISO-8601 travel time; offset-less values use
            America/New_York. Omit for the current VDOT view.

    Returns:
        dict: ``pricing_status: "priced"`` includes the I-95 fare fields;
        ``"unavailable"`` has no monetary fields. Invalid input returns
        ``{"error", "valid_options"}``.
    """
    if movement not in _JUNCTION_MOVEMENTS:
        return {
            "error": f"unknown junction movement {movement!r}",
            "valid_options": sorted(_JUNCTION_MOVEMENTS),
        }

    role = "origin" if movement == "i95_to_i495" else "destination"
    location_ids = _oracle_route.resolve(location, nodes=_NODES, label_idx=_LABEL_INDEX)
    role_key = "entry" if role == "origin" else "exit"
    role_ids = {p[role_key] for p in _PAIRS}
    if not set(location_ids) & role_ids:
        return {
            "error": f"{location!r} is not a valid {role} on i95",
            "valid_options": sorted(
                {
                    _NODES[p["entry" if role == "origin" else "exit"]]["label"]
                    for p in _PAIRS
                }
            ),
        }

    try:
        resolved_at_time = _oracle_route.resolve_at_time(at_time)
    except ValueError as e:
        return {
            "error": f"invalid at_time {at_time!r}: {e}",
            "valid_options": [],
        }

    conn = _oracle_route.env_connect()
    try:
        with conn.cursor() as cur:
            rows = {
                direction: _fetch_i95_row(
                    cur,
                    od_pair_id,
                    resolved_at_time if at_time else None,
                )
                for direction, od_pair_id in _STATUS_OD_PAIR_IDS.items()
            }
            statuses = {
                direction: _lane_status(row, direction)
                for direction, row in rows.items()
            }
            intervals = {row[3] for row in rows.values() if row is not None}
            open_directions = [
                direction
                for direction, status in statuses.items()
                if status
                == (
                    "NORTHBOUND_OPEN"
                    if direction == "Northbound"
                    else "SOUTHBOUND_OPEN"
                )
            ]

            reason = None
            if any(status == "UNAVAILABLE" for status in statuses.values()):
                reason = "VDOT lane status is unavailable for one or both directions"
            elif len(intervals) != 1:
                reason = "VDOT lane statuses are not from one common interval"
            elif len(open_directions) != 1:
                reason = "I-95 does not have exactly one fully open direction"

            route = (
                None
                if reason
                else _junction_lookup(location, movement, open_directions[0])
            )
            if reason is None and route is None:
                reason = (
                    f"{location!r} has no {open_directions[0].lower()} "
                    "95/395 segment to the junction boundary"
                )

            priced_leg = None
            if reason is None:
                assert route is not None
                try:
                    priced_leg = _price_i95_leg(
                        cur,
                        route["legs"][0],
                        resolved_at_time if at_time else None,
                    )
                    status_interval = next(iter(intervals)).isoformat()
                    if priced_leg["priced_as_of"] != status_interval:
                        reason = (
                            "VDOT lane status and junction-leg price are not "
                            "from one common interval"
                        )
                except _oracle_route.PricingError as e:
                    reason = str(e)
    finally:
        conn.close()

    common = {
        "pricing_status": "unavailable" if reason else "priced",
        "movement": movement,
        "location": location,
        "at_time": resolved_at_time.isoformat(),
        "lane_statuses": statuses,
        "i495_boundary": _I495_BOUNDARY,
    }
    if reason:
        response = {**common, "reason": reason}
        logger.info(
            "i95_junction_leg unavailable location=%r movement=%s reason=%r",
            location,
            movement,
            reason,
        )
        return response

    assert route is not None and priced_leg is not None
    response = {
        **route,
        **common,
        "junction_boundary": {
            "label": _JUNCTION_BOUNDARIES[open_directions[0]],
            "direction": open_directions[0],
        },
        "legs": [priced_leg],
        "total_usd": priced_leg["price_usd"],
    }
    logger.info(
        "i95_junction_leg priced location=%r movement=%s direction=%s leg=%s",
        location,
        movement,
        open_directions[0],
        priced_leg,
    )
    return response


@tool
def i95_route(
    origin: str, destination: str, at_time: str | None = None
) -> _oracle_route.JsonObject:
    """Price one direct I-95/395 Express Lanes trip with an open VDOT lane.

    Use only for one oracle-supported I-95/395 leg; cross-corridor trips must
    start with ``plan_toll_route``.

    Args:
        origin: I-95/395 ramp label or raw oracle node ID.
        destination: I-95/395 ramp label or raw oracle node ID.
        at_time: Optional ISO-8601 travel time; offset-less values use
            America/New_York. Omit for the current VDOT view.

    Returns:
        dict: Success includes resolved ``entry``/``exit``, one ``legs`` item,
        decimal-string ``total_usd``, and VDOT ``priced_as_of`` and
        ``observed_at`` timestamps. Failure is ``{"error", "valid_options"}``,
        including a closed or unavailable lane.
    """
    return _oracle_route.run(
        "i95_route",
        origin,
        destination,
        at_time,
        lookup_fn=_lookup,
        price_fn=_price_i95_leg,
    )

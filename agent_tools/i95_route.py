"""i95_route: resolve a human trip between two 95/395/495 Express Lanes ramps
to its route and its price, as of a given time.

Route resolution is a pure route-map lookup against the committed
oracles/i95.json -- no DB, no network, no multi-hop chaining. Transurban's
own published network already enumerates every valid direction+entry+exit
combination directly (685 pairs over 107 ramps), so this is a single flat
lookup, never pathfinding: "where an oracle exists, prefer reading it over
re-deriving it" (docs/oracle-findings.md section 3). A cross-corridor trip
is billed as two whole separate tolls, never a summed sub-segment -- the
oracle already flattens that into one pair carrying two od_pair_ids in
billed order, so this tool never chains two separate pairs together to
synthesize a trip.

Pricing is a second stage, run only after a successful route resolution:
each resolved od_pair_id is looked up in trip_pricing_i95 over RDS first,
falling back to Transurban's own live snapshot (trip_pricing_i95_live) for
the 16 od_pair_ids (1374-1389) VDOT's feed has never published
(docs/oracle-findings.md section 2). Both sources answer "the most recently
published price at or before at_time" (default: now, America/New_York),
never "the price this instant" -- see the at_time Args entry below and
docs/oracle-findings.md section 7. A leg still unpriced by either source is
a hard error, UNLESS it's one of the 16 known gap ids, in which case it
prices at $0.00 with source "unpriced_gap" rather than failing the whole
call -- a documented placeholder, never a claim that the trip is free.

Each priced leg is also classified into a facility group -- "495" or
"95_395" -- mirroring expresslanes.com's own split of the 495 Express Lanes
from the 95/395 Express Lanes as separate products, with per-group and
grand totals in the response.

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
# a deployment zip, the build step must land oracles/i95.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i95.json"
_ORACLE = json.loads(_ORACLE_PATH.read_text())
_NODES: dict = _ORACLE["nodes"]
_PAIRS: list = _ORACLE["pairs"]

_EASTERN = ZoneInfo("America/New_York")

# docs/oracle-findings.md section 2: VDOT's feed has never published these 16
# od_pair_ids, even though Transurban's own network (this oracle) bills them.
# All 107 oracle pairs touching these ids cross the physical break between
# the 495 Express Lanes and the 95/395 Express Lanes at the Springfield
# Interchange (verified by walking oracles/i95.json), so they default to the
# "495" facility group when unpriced -- see _price_i95_leg.
_GAP_OD_PAIR_IDS = frozenset(range(1374, 1390))

# Verified live against RDS (2026-07-26): these are the only corridor_name/
# road values seen in trip_pricing_i95/trip_pricing_i95_live. VDOT doesn't
# split 395 into its own corridor_name -- I-95-NB/SB covers both, matching
# expresslanes.com's own "95 Express Lanes" facility bundling 395 too.
_CORRIDOR_TO_FACILITY = {
    "I-495-NB": "495",
    "I-495-SB": "495",
    "I-95-NB": "95_395",
    "I-95-SB": "95_395",
}
_ROAD_TO_FACILITY = {
    "495": "495",
    "95": "95_395",
    "395": "95_395",
}


class _PricingError(Exception):
    """Any hard-error pricing condition; caught once at the tool boundary."""


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


# ponytail: resolution/matching logic duplicated with i66_route.py; extract
# if a third oracle-backed tool needs the same shape.
def _lookup(origin: str, destination: str) -> dict:
    # Some ramps are entry-only or exit-only (e.g. the 495 Express Lanes End
    # ramp can never be an origin), so the two suggestion lists are
    # role-filtered -- suggesting a label that can never fill the role being
    # asked about would guarantee the caller's next call also fails.
    origin_labels = sorted({_NODES[p["entry"]]["label"] for p in _PAIRS})
    destination_labels = sorted({_NODES[p["exit"]]["label"] for p in _PAIRS})

    origin_ids = _resolve(origin)
    if not origin_ids:
        return {
            "error": f"unknown origin {origin!r}: no matching label or node id in the i95 oracle",
            "valid_options": origin_labels,
        }
    destination_ids = _resolve(destination)
    if not destination_ids:
        return {
            "error": f"unknown destination {destination!r}: no matching label or node id in the i95 oracle",
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
            "error": f"no direct trip from {origin!r} to {destination!r} in the i95 oracle",
            "valid_options": reachable,
        }

    if len(matches) > 1:
        # Unreachable today -- verified 685/685 pairs unique on (entry, exit)
        # and on (entry_label, exit_label). Guarded for when
        # scripts/fetch_i95_oracle.py next refreshes oracles/i95.json and
        # that invariant might not hold.
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
        # p["direction"] is the only reliable direction source -- node ids
        # are suffixed NO/ND/SO/SD but that suffix does not reliably match
        # the node's own "direction" field, so it must never be inferred
        # from the id.
        "direction": p["direction"],
        "entry": {"node_id": p["entry"], "label": _NODES[p["entry"]]["label"]},
        "exit": {"node_id": p["exit"], "label": _NODES[p["exit"]]["label"]},
        # Order preserved from the oracle's own "ods" list: a two-entry leg
        # list is a cross-corridor trip billed as two sequential whole tolls,
        # never a summed sub-segment.
        "legs": [{"od_pair_id": od} for od in p["ods"]],
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


def _classify_facility_group(
    value: str | None, mapping: dict[str, str], *, od_pair_id: int, source: str
) -> str:
    if value is not None and value in mapping:
        return mapping[value]
    raise _PricingError(
        f"unrecognized {source} {value!r} for od_pair_id {od_pair_id}: "
        f"cannot classify facility group"
    )


_I95_PRIMARY_SQL = """
SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at
FROM trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
  AND interval_end_at <= %(at_time)s
ORDER BY interval_end_at DESC
LIMIT 1
"""

_I95_LIVE_SQL = """
SELECT od_pair_id, price_usd, road, observed_at
FROM trip_pricing_i95_live
WHERE od_pair_id = %(od_pair_id)s
  AND observed_at <= %(at_time)s
ORDER BY observed_at DESC
LIMIT 1
"""


def _price_i95_leg(cur, *, od_pair_id: int, at_time: datetime) -> dict:
    """Price one od_pair_id: trip_pricing_i95 first, then trip_pricing_i95_live.

    Raises _PricingError if neither source has a row and od_pair_id is not
    one of the 16 known gap ids; those default to a flagged $0.00 instead
    (docs/oracle-findings.md section 2 -- VDOT has never priced them, and
    Transurban's live snapshot has no history before its own ingestion
    start, so a miss there for a gap id is expected, not anomalous).
    """
    cur.execute(_I95_PRIMARY_SQL, {"od_pair_id": od_pair_id, "at_time": at_time})
    row = cur.fetchone()
    if row is not None:
        _, corridor_name, rate, interval_end_at = row
        return {
            "od_pair_id": od_pair_id,
            "price_usd": str(rate),
            "source": "trip_pricing_i95",
            "facility_group": _classify_facility_group(
                corridor_name,
                _CORRIDOR_TO_FACILITY,
                od_pair_id=od_pair_id,
                source="trip_pricing_i95.corridor_name",
            ),
            "corridor_name": corridor_name,
            "priced_as_of": interval_end_at.isoformat(),
        }

    cur.execute(_I95_LIVE_SQL, {"od_pair_id": od_pair_id, "at_time": at_time})
    row = cur.fetchone()
    if row is not None:
        _, price, road, observed_at = row
        return {
            "od_pair_id": od_pair_id,
            "price_usd": str(price),
            "source": "trip_pricing_i95_live",
            "facility_group": _classify_facility_group(
                road,
                _ROAD_TO_FACILITY,
                od_pair_id=od_pair_id,
                source="trip_pricing_i95_live.road",
            ),
            "corridor_name": None,
            "priced_as_of": observed_at.isoformat(),
        }

    if od_pair_id in _GAP_OD_PAIR_IDS:
        return {
            "od_pair_id": od_pair_id,
            "price_usd": "0.00",
            "source": "unpriced_gap",
            "facility_group": "495",
            "corridor_name": None,
            "priced_as_of": None,
        }

    raise _PricingError(
        f"no price found for od_pair_id {od_pair_id} at or before "
        f"{at_time.isoformat()} in trip_pricing_i95 or trip_pricing_i95_live"
    )


def _build_response(result: dict, priced_legs: list[dict], at_time: datetime) -> dict:
    totals = {"495": Decimal("0.00"), "95_395": Decimal("0.00")}
    for leg in priced_legs:
        totals[leg["facility_group"]] += Decimal(leg["price_usd"])
    grand_total = totals["495"] + totals["95_395"]
    return {
        **result,
        "at_time": at_time.isoformat(),
        "legs": priced_legs,
        "facility_totals": {group: str(amount) for group, amount in totals.items()},
        "total_usd": str(grand_total),
    }


@tool
def i95_route(origin: str, destination: str, at_time: str | None = None) -> dict:
    """Resolve a trip on Transurban's 95/395/495 Express Lanes network to its route and price.

    Looks up origin/destination against oracles/i95.json's 685 published
    entry/exit trips (107 ramps) -- a flat, direct lookup, never multi-hop
    routing. Every valid direction+entry+exit combination is already
    enumerated by Transurban itself, including cross-corridor trips billed as
    two whole separate tolls. Each resolved leg is then priced against
    trip_pricing_i95 (falling back to Transurban's own live snapshot for the
    16 known VDOT gap ids) over RDS.

    Args:
        origin: Ramp label (e.g. 'Route 267'), case-insensitive, or the
            oracle's raw node id (e.g. '182NO') as a fallback.
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
        dict: On success, {"origin", "destination",
        "direction": "Northbound"|"Southbound", "entry": {"node_id", "label"},
        "exit": {"node_id", "label"}, "at_time": str (the resolved,
        ISO-8601 time actually used), "legs": [{"od_pair_id", "price_usd":
        str, "source": "trip_pricing_i95"|"trip_pricing_i95_live"|
        "unpriced_gap", "facility_group": "495"|"95_395", "corridor_name":
        str|None, "priced_as_of": str|None}, ...], "facility_totals":
        {"495": str, "95_395": str}, "total_usd": str} -- legs has one entry
        for a within-corridor trip or two for a cross-corridor trip, in
        billed order. price_usd/facility_totals/total_usd are decimal
        strings (never float). A leg with source "unpriced_gap" is one of
        the 16 od_pair_ids (1374-1389) VDOT's feed has never priced, priced
        $0.00 as a flagged placeholder rather than failing the call --
        never a claim that leg is actually free. On failure, {"error": str,
        "valid_options": [str, ...]} -- the full ramp label list on an
        unknown identifier, the reachable destination labels on a known
        origin with no direct trip to the given destination, or a
        pricing/at_time failure, so the caller can self-correct where
        possible; valid_options is empty for a pricing miss or a bad
        at_time, since retrying the same inputs won't fix either.
    """
    result = _lookup(origin, destination)
    if "error" in result:
        logger.info(
            "i95_route miss origin=%r destination=%r error=%r",
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
            "i95_route miss origin=%r destination=%r error=%r",
            origin,
            destination,
            error["error"],
        )
        return error

    conn = _env_connect()
    try:
        with conn.cursor() as cur:
            priced_legs = [
                _price_i95_leg(
                    cur, od_pair_id=leg["od_pair_id"], at_time=resolved_at_time
                )
                for leg in result["legs"]
            ]
    except _PricingError as e:
        error = {"error": str(e), "valid_options": []}
        logger.info(
            "i95_route miss origin=%r destination=%r error=%r",
            origin,
            destination,
            error["error"],
        )
        return error
    finally:
        conn.close()

    response = _build_response(result, priced_legs, resolved_at_time)
    logger.info(
        "i95_route ok origin=%r destination=%r entry=%s exit=%s direction=%s "
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

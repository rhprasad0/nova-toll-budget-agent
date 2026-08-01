"""Shared route-resolution/RDS-connection scaffolding for the oracle-backed
routing tools (i66_route.py, i95_route.py, i495_route.py).

Each tool still owns its own oracle file location, its own facility filter,
and its own pricing SQL/gate logic. Everything identical across the three --
label lookup, at_time parsing, the DB connection, the resolve/price/log
sequence each @tool body runs, and the final response envelope -- lives
here, in run().
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

import boto3

logger = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")


class PricingError(Exception):
    """Any hard-error pricing condition; caught once at the tool boundary."""


class Cursor(Protocol):
    def execute(self, query: str, params: Mapping[str, object]) -> object: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...


class CursorContext(Protocol):
    def __enter__(self) -> Cursor: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class Connection(Protocol):
    def cursor(self) -> CursorContext: ...

    def close(self) -> None: ...


type JsonObject = dict[str, Any]
type Nodes = dict[str, JsonObject]
type Pairs = list[JsonObject]


def label_index(nodes: Nodes) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        idx.setdefault(node["label"].casefold(), []).append(node_id)
    return idx


def resolve(query: str, *, nodes: Nodes, label_idx: dict[str, list[str]]) -> list[str]:
    """Candidate node ids for a caller-supplied label (case-insensitive) or raw node id."""
    if query in nodes:
        return [query]
    return label_idx.get(query.casefold(), [])


def lookup(
    origin: str,
    destination: str,
    *,
    nodes: Nodes,
    pairs: Pairs,
    label_idx: dict[str, list[str]],
    oracle_name: str,
    build_legs: Callable[[JsonObject], list[JsonObject]],
) -> JsonObject:
    """Resolve origin/destination to a single oracle pair and its legs.

    build_legs(pair) turns the matched pair into the tool's own leg shape
    (i95/i495 key a leg by od_pair_id; i66 keys it by start/end zone id).
    """
    # Some ramps are entry-only or exit-only, so the two suggestion lists
    # are role-filtered -- suggesting a label that can never fill the role
    # being asked about would guarantee the caller's next call also fails.
    origin_labels = sorted({nodes[p["entry"]]["label"] for p in pairs})
    destination_labels = sorted({nodes[p["exit"]]["label"] for p in pairs})

    origin_ids = resolve(origin, nodes=nodes, label_idx=label_idx)
    if not origin_ids:
        return {
            "error": f"unknown origin {origin!r}: no matching label or node id in the {oracle_name} oracle",
            "valid_options": origin_labels,
        }
    destination_ids = resolve(destination, nodes=nodes, label_idx=label_idx)
    if not destination_ids:
        return {
            "error": f"unknown destination {destination!r}: no matching label or node id in the {oracle_name} oracle",
            "valid_options": destination_labels,
        }

    matches = [
        p for p in pairs if p["entry"] in origin_ids and p["exit"] in destination_ids
    ]

    if not matches:
        reachable = sorted(
            {nodes[p["exit"]]["label"] for p in pairs if p["entry"] in origin_ids}
        )
        return {
            "error": f"no direct trip from {origin!r} to {destination!r} in the {oracle_name} oracle",
            "valid_options": reachable,
        }

    if len(matches) > 1:
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
        "entry": {"node_id": p["entry"], "label": nodes[p["entry"]]["label"]},
        "exit": {"node_id": p["exit"], "label": nodes[p["exit"]]["label"]},
        "legs": build_legs(p),
    }


def resolve_at_time(
    at_time: str | None, *, now: Callable[[], datetime] | None = None
) -> datetime:
    """Parse at_time, treating an omitted or empty value as now in Eastern time.

    A naive (no-offset) string is assumed America/New_York. Raises
    ValueError on an unparseable string -- the caller turns that into an
    error response before any DB connection opens. `now` is a zero-arg
    callable injection point for tests; production callers never pass it.
    """
    if not at_time:
        return (now or (lambda: datetime.now(EASTERN)))()
    dt = datetime.fromisoformat(at_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)
    return dt


def env_connect() -> Connection:
    """Connect to RDS as pricing_reader via IAM auth.

    Lazy `import psycopg`: it isn't in the fast dev/test path (mirrors
    lambdas/loader/handler.py's _connect(), which has the same constraint
    for the deployed Lambda zip). boto3 stays a top-level import -- it's
    already a main dependency and carries no such cost.
    """
    import psycopg  # type: ignore[import-not-found]

    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    user = os.environ["DB_USER"]
    rds = cast(Any, boto3.client("rds"))  # pyright: ignore[reportUnknownMemberType]
    token = cast(
        str,
        rds.generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user),
    )
    return cast(
        Connection,
        psycopg.connect(
            host=host,
            port=port,
            dbname=os.environ["DB_NAME"],
            user=user,
            password=token,
            sslmode="verify-full",
            sslrootcert=os.environ["DB_CA_BUNDLE_PATH"],
            connect_timeout=10,
        ),
    )


def build_response(
    result: JsonObject, priced_legs: list[JsonObject], at_time: datetime
) -> JsonObject:
    total = sum((Decimal(leg["price_usd"]) for leg in priced_legs), Decimal(0))
    return {
        **result,
        "at_time": at_time.isoformat(),
        "legs": priced_legs,
        "total_usd": str(total),
    }


def _miss(
    tool_name: str, origin: str, destination: str, error: JsonObject
) -> JsonObject:
    # valid_options is deliberately not logged: on an unknown label it's the
    # whole ramp list, which is noise in an audit line, not signal.
    logger.info(
        "%s miss origin=%r destination=%r error=%r",
        tool_name,
        origin,
        destination,
        error["error"],
    )
    return error


def run(
    tool_name: str,
    origin: str,
    destination: str,
    at_time: str | None,
    *,
    lookup_fn: Callable[[str, str], JsonObject],
    price_fn: Callable[[Cursor, JsonObject, datetime | None], JsonObject],
) -> JsonObject:
    """Resolve -> parse at_time -> connect -> price -> envelope, with the
    audit logging each step needs. The single-leg body every RDS-backed
    route tool runs; they differ only in lookup_fn/price_fn.

    price_fn(cur, leg_key, at_time) returns the priced leg, or raises
    PricingError. `at_time` is None for a current-price request, which uses
    its VDOT current-price view; an explicit time reads VDOT history.
    """
    result = lookup_fn(origin, destination)
    if "error" in result:
        return _miss(tool_name, origin, destination, result)

    try:
        resolved_at_time = resolve_at_time(at_time)
    except ValueError as e:
        return _miss(
            tool_name,
            origin,
            destination,
            {"error": f"invalid at_time {at_time!r}: {e}", "valid_options": []},
        )

    conn = env_connect()
    try:
        with conn.cursor() as cur:
            priced_leg = price_fn(
                cur,
                result["legs"][0],
                resolved_at_time if at_time else None,
            )
    except PricingError as e:
        return _miss(
            tool_name,
            origin,
            destination,
            {"error": str(e), "valid_options": []},
        )
    finally:
        conn.close()

    response = build_response(result, [priced_leg], resolved_at_time)
    logger.info(
        "%s ok origin=%r destination=%r entry=%s exit=%s direction=%s "
        "at_time=%s total_usd=%s legs=%s",
        tool_name,
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

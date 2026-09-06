"""Bounded, read-only pricing history capture for evaluator evidence.

This module deliberately captures source rows only.  It does not invoke either
agent tool and it never turns a raw row into typed-tool execution evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast

_SOURCE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_PRICING_SCHEMA_VERSION = "1.3.0"
DEFAULT_CAP = 10_000
MAX_WINDOW = timedelta(days=84)

# Explicit columns are part of the evidence contract.  In particular, the
# source object key and ingestion metadata are intentionally excluded.
I95_HISTORY_SQL = """
SELECT interval_end_at, current_at, calculated_at, corridor_id,
       corridor_name, od_pair_id, od_pair_name, start_zone_id,
       start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
       link_status
FROM pricing.trip_pricing_i95
WHERE od_pair_id = ANY(%s)
  AND interval_end_at >= %s
  AND interval_end_at < %s
  AND calculated_at <= %s
ORDER BY interval_end_at, od_pair_id, start_zone_id, end_zone_id,
         calculated_at, corridor_id
LIMIT %s
"""

I66_HISTORY_SQL = """
SELECT history.interval_start_at, history.interval_end_at,
       history.calculated_at, history.corridor_id, history.corridor_name,
       history.start_zone_id, history.start_zone_name, history.end_zone_id,
       history.end_zone_name, history.zone_toll_rate_usd
FROM pricing.trip_pricing_i66 AS history
JOIN unnest(%s::integer[], %s::integer[])
  AS wanted(start_zone_id, end_zone_id)
  ON history.start_zone_id = wanted.start_zone_id
 AND history.end_zone_id = wanted.end_zone_id
WHERE
  history.interval_end_at >= %s
  AND history.interval_end_at < %s
  AND history.calculated_at <= %s
ORDER BY history.interval_end_at, history.start_zone_id,
         history.end_zone_id, history.calculated_at, history.corridor_id
LIMIT %s
"""

VERIFY_IDENTITY_SQL = """
SELECT current_user::text AS current_user,
       current_setting('transaction_read_only') AS transaction_read_only,
       current_setting('transaction_isolation') AS transaction_isolation,
       transaction_timestamp() AS transaction_timestamp,
       current_setting('server_version_num') AS server_version_num,
       has_table_privilege(current_user, 'pricing.trip_pricing_i95', 'SELECT')
           AS i95_select,
       has_table_privilege(current_user, 'pricing.trip_pricing_i66', 'SELECT')
           AS i66_select,
       has_table_privilege(current_user, 'pricing.trip_pricing_i95',
                           'INSERT,UPDATE,DELETE,TRUNCATE') AS i95_write,
       has_table_privilege(current_user, 'pricing.trip_pricing_i66',
                           'INSERT,UPDATE,DELETE,TRUNCATE') AS i66_write
"""
VERIFY_SCHEMA_SQL = """
SELECT version
FROM pricing.schema_version
WHERE singleton
"""
BEGIN_SQL = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
TIMEOUT_SQL = (
    "SET LOCAL statement_timeout = '30s'",
    "SET LOCAL lock_timeout = '2s'",
    "SET LOCAL idle_in_transaction_session_timeout = '30s'",
)


class CaptureError(ValueError):
    """Base error for invalid or unsafe capture requests."""


class CaptureBoundExceeded(CaptureError):
    """The bounded query returned cap+1 rows and was rejected."""


class CaptureVerificationError(CaptureError):
    """The connection did not prove the required reader contract."""


class _Cursor(Protocol):
    def execute(self, query: str, params: object = None) -> object: ...

    def fetchall(self) -> Sequence[Mapping[str, Any]]: ...

    def close(self) -> object: ...


class _Connection(Protocol):
    def cursor(self) -> _Cursor: ...

    def rollback(self) -> object: ...

    def close(self) -> object: ...


def _iso(value: datetime, label: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CaptureError(f"{label} must be timezone-aware")
    return value.isoformat()


def _canonical(value: object) -> bytes:
    return json.dumps(
        _json_safe(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        typed = cast(Mapping[object, object], value)
        return {str(key): _json_safe(item) for key, item in typed.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in cast(Sequence[object], value)]
    return value


def _validate_source(source_id: str) -> None:
    if not _SOURCE_ID.fullmatch(source_id):
        raise CaptureError("source_id is not a stable identifier")


def _validate_bounds(
    lower: datetime, upper: datetime, anchor: datetime, cap: int
) -> None:
    _iso(lower, "lower bound")
    _iso(upper, "upper bound")
    _iso(anchor, "anchor")
    if lower >= upper:
        raise CaptureError("history bounds must be increasing")
    if upper - lower > MAX_WINDOW:
        raise CaptureError("history window exceeds 84 days")
    if type(cap) is not int or cap < 1:
        raise CaptureError("cap must be a positive integer")


def _validate_i95_ids(ids: Sequence[int]) -> tuple[int, ...]:
    values = tuple(ids)
    if not values or any(type(value) is not int or value < 1 for value in values):
        raise CaptureError("I-95 OD selectors must be nonempty positive integers")
    if len(set(values)) != len(values):
        raise CaptureError("I-95 OD selectors must be unique")
    return values


def _validate_i66_selectors(
    starts: Sequence[int], ends: Sequence[int]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    start_values, end_values = tuple(starts), tuple(ends)
    if not start_values or len(start_values) != len(end_values):
        raise CaptureError("I-66 selectors must be nonempty and equal length")
    if any(
        type(value) is not int or value < 1 for value in (*start_values, *end_values)
    ):
        raise CaptureError("I-66 selectors must be positive integers")
    if len(set(zip(start_values, end_values, strict=True))) != len(start_values):
        raise CaptureError("I-66 selector pairs must be unique")
    return start_values, end_values


def _rows(cursor: _Cursor) -> list[dict[str, Any]]:
    fetched = cursor.fetchall()
    return [dict(row) for row in fetched]


def _one(cursor: _Cursor, label: str) -> dict[str, Any]:
    fetched = cursor.fetchall()
    if len(fetched) != 1:
        raise CaptureVerificationError(f"{label} returned an invalid row count")
    return dict(fetched[0])


@dataclass(frozen=True)
class RawHistoryCapture:
    """Rows and provenance returned after the read-only transaction is closed."""

    source_id: str
    raw_evidence_sha256: str
    anchor: datetime
    captured_at: datetime
    server_version_num: str
    lower_bound: datetime
    upper_bound: datetime
    i95_rows: tuple[dict[str, Any], ...]
    i66_rows: tuple[dict[str, Any], ...]
    cap: int
    pricing_schema_version: str
    provenance: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        rows = {"i95_rows": list(self.i95_rows), "i66_rows": list(self.i66_rows)}
        return cast(
            dict[str, Any],
            _json_safe(
                {
                    "evidence_type": "raw_history_source",
                    "source_id": self.source_id,
                    "raw_evidence_sha256": self.raw_evidence_sha256,
                    "anchor": self.anchor,
                    "captured_at": self.captured_at,
                    "server_version_num": self.server_version_num,
                    "bounds": {
                        "lower": self.lower_bound,
                        "upper": self.upper_bound,
                        "cap": self.cap,
                    },
                    "pricing_schema_version": self.pricing_schema_version,
                    **rows,
                    "provenance": dict(self.provenance),
                }
            ),
        )


def connect_pricing_reader() -> object:
    """Open the existing IAM-authenticated reader path on explicit request."""
    from agent_tools import validate_toll_route

    return validate_toll_route._connect_to_database("pricing_reader")  # pyright: ignore[reportPrivateUsage]


def capture_raw_history(
    connection_factory: Callable[[], object],
    *,
    source_id: str,
    anchor: datetime,
    lower_bound: datetime,
    upper_bound: datetime,
    i95_od_pair_ids: Sequence[int],
    i66_start_zone_ids: Sequence[int],
    i66_end_zone_ids: Sequence[int],
    cap: int = DEFAULT_CAP,
    pricing_schema_version: str = DEFAULT_PRICING_SCHEMA_VERSION,
    deadline_seconds: float = 30.0,
) -> RawHistoryCapture:
    """Capture bounded raw rows using one verified ``pricing_reader`` snapshot.

    ``connection_factory`` is injected so offline tests cannot accidentally use
    credentials.  Production callers should pass :func:`connect_pricing_reader`.
    """
    if not callable(connection_factory):
        raise CaptureError("connection_factory is required")
    _validate_source(source_id)
    _validate_bounds(lower_bound, upper_bound, anchor, cap)
    i95_ids = _validate_i95_ids(i95_od_pair_ids)
    i66_starts, i66_ends = _validate_i66_selectors(i66_start_zone_ids, i66_end_zone_ids)
    if not pricing_schema_version:
        raise CaptureError("pricing schema version is required")
    if (
        type(deadline_seconds) not in (int, float)
        or not math.isfinite(deadline_seconds)
        or deadline_seconds <= 0
    ):
        raise CaptureError("deadline_seconds must be positive")

    connection_value = connection_factory()
    if connection_value is None:
        raise CaptureError("connection factory returned no connection")
    connection = cast(_Connection, connection_value)
    cursor: _Cursor | None = None
    i95_rows: list[dict[str, Any]] = []
    i66_rows: list[dict[str, Any]] = []
    deadline = time.monotonic() + deadline_seconds

    def check_deadline() -> None:
        if time.monotonic() >= deadline:
            raise CaptureError("capture deadline exceeded")

    try:
        cursor = connection.cursor()
        check_deadline()
        cursor.execute(BEGIN_SQL)
        for statement in TIMEOUT_SQL:
            check_deadline()
            cursor.execute(statement)
        check_deadline()
        cursor.execute(VERIFY_IDENTITY_SQL)
        identity = _one(cursor, "reader identity")
        if identity.get("current_user") != "pricing_reader":
            raise CaptureVerificationError("capture connection is not pricing_reader")
        read_only = identity.get("transaction_read_only")
        if read_only not in {True, "on", "true"}:
            raise CaptureVerificationError("capture transaction is not read-only")
        if str(identity.get("transaction_isolation", "")).casefold() not in {
            "repeatable read",
            "repeatable_read",
        }:
            raise CaptureVerificationError("capture transaction is not repeatable read")
        if (
            identity.get("i95_select") is not True
            or identity.get("i66_select") is not True
        ):
            raise CaptureVerificationError(
                "pricing_reader lacks raw-table SELECT privilege"
            )
        if (
            identity.get("i95_write") is not False
            or identity.get("i66_write") is not False
        ):
            raise CaptureVerificationError(
                "pricing_reader has raw-table write privilege"
            )

        check_deadline()
        cursor.execute(VERIFY_SCHEMA_SQL)
        schema = _one(cursor, "pricing schema version")
        if schema.get("version") != pricing_schema_version:
            raise CaptureVerificationError("pricing schema version disagrees")

        check_deadline()
        cursor.execute(
            I95_HISTORY_SQL,
            (list(i95_ids), lower_bound, upper_bound, anchor, cap + 1),
        )
        i95_rows = _rows(cursor)
        check_deadline()
        if len(i95_rows) > cap:
            raise CaptureBoundExceeded("I-95 history exceeded capture cap")

        check_deadline()
        cursor.execute(
            I66_HISTORY_SQL,
            (
                list(i66_starts),
                list(i66_ends),
                lower_bound,
                upper_bound,
                anchor,
                cap + 1,
            ),
        )
        i66_rows = _rows(cursor)
        check_deadline()
        if len(i66_rows) > cap:
            raise CaptureBoundExceeded("I-66 history exceeded capture cap")
        allowed_pairs = set(zip(i66_starts, i66_ends, strict=True))
        if any(
            (row.get("start_zone_id"), row.get("end_zone_id")) not in allowed_pairs
            for row in i66_rows
        ):
            raise CaptureVerificationError(
                "I-66 result contains an unrequested selector pair"
            )
    finally:
        cleanup_error: Exception | None = None
        if cursor is not None:
            try:
                cursor.close()
            except Exception as error:
                cleanup_error = error
        rollback_error: Exception | None = None
        try:
            connection.rollback()
        except Exception as error:
            rollback_error = error
        try:
            connection.close()
        except Exception as error:
            if rollback_error is None:
                rollback_error = error
        if rollback_error is not None:
            raise CaptureError("capture connection cleanup failed") from rollback_error
        if cleanup_error is not None:
            raise CaptureError("capture cursor cleanup failed") from cleanup_error

    captured_at = cast(datetime, identity["transaction_timestamp"])
    _iso(captured_at, "transaction timestamp")
    server_version_num = str(identity["server_version_num"])
    if not server_version_num.isdigit():
        raise CaptureVerificationError("server version is invalid")
    cleaned_rows = _json_safe({"i95_rows": i95_rows, "i66_rows": i66_rows})
    raw_evidence_sha256 = hashlib.sha256(_canonical(cleaned_rows)).hexdigest()
    provenance = {
        "capture_type": "raw_history_source_evidence",
        "evidence_type": "raw_history_source",
        "source_id": source_id,
        "raw_evidence_sha256": raw_evidence_sha256,
        "database_role": "pricing_reader",
        "transaction": "REPEATABLE READ READ ONLY",
        "transaction_timestamp": captured_at,
        "captured_at": captured_at,
        "server_version_num": server_version_num,
        "timeouts": {
            "statement_timeout": "30s",
            "lock_timeout": "2s",
            "idle_in_transaction_session_timeout": "30s",
        },
        "anchor": anchor,
        "historical_as_of_anchor": anchor,
        "bounds": {
            "lower_inclusive": lower_bound,
            "upper_exclusive": upper_bound,
            "cap": cap,
        },
        "selectors": {
            "i95_od_pair_ids": list(i95_ids),
            "i66_start_zone_ids": list(i66_starts),
            "i66_end_zone_ids": list(i66_ends),
        },
        "pricing_schema_version": pricing_schema_version,
    }
    return RawHistoryCapture(
        source_id=source_id,
        raw_evidence_sha256=raw_evidence_sha256,
        anchor=anchor,
        captured_at=captured_at,
        server_version_num=server_version_num,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        i95_rows=tuple(i95_rows),
        i66_rows=tuple(i66_rows),
        cap=cap,
        pricing_schema_version=pricing_schema_version,
        provenance=cast(Mapping[str, Any], _json_safe(provenance)),
    )

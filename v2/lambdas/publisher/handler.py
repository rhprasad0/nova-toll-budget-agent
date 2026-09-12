"""Publish compact prior-week I-95/I-495 toll reports."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from statistics import median
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

import boto3
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger()
logger.setLevel(logging.INFO)
FACILITY = "i95_i495"
EXPECTED_PATH_COUNT = 562
EXPECTED_GROUP_COUNT = 246
EXPECTED_I66_PATH_COUNT = 20
REPORT_SQL = "SELECT * FROM oracle.get_agent_report_routes()"
CA_BUNDLE_PATH = str(Path(__file__).with_name("rds-ca-bundle.pem"))
PUBLIC_PREFIX = "tolls/i95-i495"
MANIFEST_KEY = f"{PUBLIC_PREFIX}/manifest.json"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://tollchat.ai").rstrip("/")
PUBLICATION_FORMAT_VERSION = "3.0.0"
PUBLIC_CACHE_CONTROL = "public, max-age=300"
MANIFEST_CACHE_CONTROL = "no-cache"
_EASTERN = ZoneInfo("America/New_York")
_DIRECTIONS = {"northbound", "southbound"}
_ROUTE_FIELDS = {
    "facility",
    "path_id",
    "path_order",
    "pricing_legs",
    "origin_area",
    "destination_area",
    "direction",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _LoadDetail(_Model):
    environment: Literal["development", "production"]
    schema_version: Literal[1]
    facility: Literal["i95_i495"]
    source_watermark: str
    source_key: str = Field(
        pattern=r"^raw/feed=i95/date=\d{4}-\d{2}-\d{2}/\d{4}Z(?:-[a-f0-9]{16})?\.csv$"
    )
    row_count: int = Field(gt=0)


@dataclass(frozen=True)
class _Leg:
    route_step_id: str
    od_pair_id: int
    source_route_key: str


@dataclass(frozen=True)
class _Path:
    path_id: str
    order: int
    origin_area: str
    destination_area: str
    direction: str
    legs: tuple[_Leg, ...]

    @property
    def group(self) -> tuple[str, str, str, str]:
        return (FACILITY, self.origin_area, self.destination_area, self.direction)


def _require_aware(value: object, *, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be an aware datetime")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is not an ISO timestamp") from error
    return _require_aware(parsed, label=label).astimezone(UTC)


def _slugify(*parts: str) -> str:
    text = (
        unicodedata.normalize("NFKD", "-".join(parts))
        .encode("ascii", "ignore")
        .decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        raise ValueError("report slug is empty")
    return slug


def _route_key(path: _Path) -> str:
    return f"{PUBLIC_PREFIX}/{path.direction}/{_slugify(path.origin_area)}-to-{_slugify(path.destination_area)}"


def _parse_legs(value: object, direction: str) -> tuple[_Leg, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("pricing_legs must be a non-empty list")
    legs: list[_Leg] = []
    for raw_value in cast(list[object], value):
        if not isinstance(raw_value, dict):
            raise ValueError("pricing leg is malformed")
        raw = cast(dict[str, object], raw_value)
        if set(raw) != {
            "route_step_id",
            "facility",
            "pricing_key",
        }:
            raise ValueError("pricing leg is malformed")
        key_value = raw["pricing_key"]
        if not isinstance(key_value, dict):
            raise ValueError("pricing leg is malformed")
        key = cast(dict[str, object], key_value)
        if (
            raw["facility"] != FACILITY
            or not isinstance(raw["route_step_id"], str)
            or not raw["route_step_id"]
            or not {"od_pair_id", "source_route_key"} <= set(key)
            or not isinstance(key["od_pair_id"], int)
            or isinstance(key["od_pair_id"], bool)
            or not isinstance(key["source_route_key"], str)
            or not key["source_route_key"].startswith(
                "Northbound:" if direction == "northbound" else "Southbound:"
            )
        ):
            raise ValueError("pricing leg is malformed")
        legs.append(
            _Leg(raw["route_step_id"], key["od_pair_id"], key["source_route_key"])
        )
    if len({leg.route_step_id for leg in legs}) != len(legs):
        raise ValueError("pricing leg IDs are not unique")
    return tuple(legs)


def _validate_paths(rows: list[dict[str, Any]]) -> tuple[_Path, ...]:
    if len(rows) != EXPECTED_I66_PATH_COUNT + EXPECTED_PATH_COUNT:
        raise ValueError("report snapshot has an invalid path count")
    if any(set(row) != _ROUTE_FIELDS for row in rows):
        raise ValueError("report route columns are malformed")
    if any(row["facility"] not in {"i66", FACILITY} for row in rows):
        raise ValueError("report route facility is unsupported")
    i66_count = 0
    path_ids: set[str] = set()
    for expected_order, row in enumerate(rows, start=1):
        order = row["path_order"]
        expected_facility = (
            "i66" if expected_order <= EXPECTED_I66_PATH_COUNT else FACILITY
        )
        if (
            not isinstance(order, int)
            or isinstance(order, bool)
            or order != expected_order
        ):
            raise ValueError("report paths have invalid global order")
        if row["facility"] != expected_facility:
            raise ValueError("report paths have invalid global facility order")
        if (
            not isinstance(row["path_id"], str)
            or not row["path_id"]
            or row["path_id"] in path_ids
            or not isinstance(row["origin_area"], str)
            or not row["origin_area"].strip()
            or not isinstance(row["destination_area"], str)
            or not row["destination_area"].strip()
            or not isinstance(row["pricing_legs"], list)
            or not row["pricing_legs"]
        ):
            raise ValueError("report path is malformed")
        path_ids.add(row["path_id"])
        if row["direction"] not in (
            {"eastbound", "westbound"} if row["facility"] == "i66" else _DIRECTIONS
        ):
            raise ValueError("report path direction is malformed")
        for leg_value in cast(list[object], row["pricing_legs"]):
            if not isinstance(leg_value, dict):
                raise ValueError("pricing leg is malformed")
            leg = cast(dict[str, object], leg_value)
            if (
                set(leg) != {"route_step_id", "facility", "pricing_key"}
                or leg["facility"] != row["facility"]
                or not isinstance(leg["route_step_id"], str)
                or not leg["route_step_id"]
                or not isinstance(leg["pricing_key"], dict)
                or not leg["pricing_key"]
            ):
                raise ValueError("pricing leg is malformed")
        if row["facility"] == "i66":
            i66_count += 1
    if i66_count != EXPECTED_I66_PATH_COUNT:
        raise ValueError(
            f"report snapshot must contain {EXPECTED_I66_PATH_COUNT} I-66 paths"
        )
    i95_rows = [row for row in rows if row["facility"] == FACILITY]
    if len(i95_rows) != EXPECTED_PATH_COUNT:
        raise ValueError(f"report snapshot must contain {EXPECTED_PATH_COUNT} paths")
    paths: list[_Path] = []
    for row in i95_rows:
        if row["direction"] not in _DIRECTIONS:
            raise ValueError("report path is malformed")
        paths.append(
            _Path(
                row["path_id"],
                row["path_order"],
                row["origin_area"].strip(),
                row["destination_area"].strip(),
                row["direction"],
                _parse_legs(row["pricing_legs"], row["direction"]),
            )
        )
    if len({path.path_id for path in paths}) != len(paths):
        raise ValueError("report path IDs are not unique")
    groups = {path.group for path in paths}
    if len(groups) != EXPECTED_GROUP_COUNT:
        raise ValueError(f"report snapshot must contain {EXPECTED_GROUP_COUNT} groups")
    if len({_route_key(path) for path in paths}) != len(groups):
        raise ValueError("generalized report keys collide")
    return tuple(paths)


def _week_window(invoked_at: datetime) -> tuple[datetime, datetime]:
    local = _require_aware(invoked_at, label="invoked_at").astimezone(_EASTERN)
    date = (local - timedelta(days=local.weekday())).date()
    end = datetime(date.year, date.month, date.day, tzinfo=_EASTERN)
    if local < end:
        end -= timedelta(weeks=1)
    return end - timedelta(weeks=1), end


def _hour_starts(start: datetime, end: datetime) -> tuple[datetime, ...]:
    current, stop = start.astimezone(UTC), end.astimezone(UTC)
    hours: list[datetime] = []
    while current < stop:
        hours.append(current)
        current += timedelta(hours=1)
    if current != stop:
        raise ValueError("weekly boundary is not an elapsed-hour boundary")
    return tuple(hours)


def _read_report_rows(connection: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '180s'")
        cursor.execute(REPORT_SQL)
        return cast(list[dict[str, Any]], cursor.fetchall())


def _source_rows(
    connection: Any,  # noqa: ANN401
    leg: _Leg,
    start: datetime,
    end: datetime,
    run_at: datetime,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "target_od_pair_id": leg.od_pair_id,
        "window_start_utc": start.astimezone(UTC),
        "window_end_utc": end.astimezone(UTC),
        "run_at_utc": run_at.astimezone(UTC),
    }
    with connection.cursor("proxy_lookup") as cursor:
        cursor.execute(
            "SELECT proxy_od_pair_id, required_status FROM pricing.i95_modeled_od_proxy WHERE target_od_pair_id = %(target_od_pair_id)s",
            params,
        )
        mappings = cursor.fetchmany(2)
    if len(mappings) > 1:
        raise ValueError("target OD has duplicate proxy mappings")
    source = leg.od_pair_id
    required_status: str | None = None
    if mappings:
        mapping = mappings[0]
        if not isinstance(mapping.get("proxy_od_pair_id"), int) or not isinstance(
            mapping.get("required_status"), str
        ):
            raise ValueError("target OD proxy mapping is malformed")
        source = mapping["proxy_od_pair_id"]
        required_status = mapping["required_status"]
    params["source_od_pair_id"] = source
    sql = "SELECT interval_end_at, calculated_at, s3_key, zone_toll_rate_usd FROM pricing.trip_pricing_i95 WHERE od_pair_id = %(source_od_pair_id)s AND interval_end_at >= %(window_start_utc)s AND interval_end_at < %(window_end_utc)s AND calculated_at <= %(run_at_utc)s"
    if required_status:
        sql += " AND link_status = %(required_status)s"
        params["required_status"] = required_status
    sql += " ORDER BY interval_end_at, calculated_at, s3_key"
    with connection.cursor(f"raw_{leg.route_step_id}") as cursor:
        cursor.execute(sql, params)
        rows: list[dict[str, Any]] = []
        while batch := cursor.fetchmany(500):
            rows.extend(batch)
    return rows


def _selected_prices(
    rows: list[dict[str, Any]], start: datetime, end: datetime, run_at: datetime
) -> dict[datetime, Decimal]:
    selected: dict[datetime, tuple[datetime, str, Decimal]] = {}
    for row in rows:
        try:
            interval = _require_aware(
                row.get("interval_end_at"), label="interval_end_at"
            ).astimezone(UTC)
            calculated = _require_aware(
                row.get("calculated_at"), label="calculated_at"
            ).astimezone(UTC)
            key, price = row["s3_key"], Decimal(str(row["zone_toll_rate_usd"]))
        except (InvalidOperation, KeyError, ValueError) as error:
            raise ValueError("source observation is malformed") from error
        if not isinstance(key, str) or not key or price < 0:
            raise ValueError("source observation is malformed")
        if not start.astimezone(UTC) <= interval < end.astimezone(
            UTC
        ) or calculated > run_at.astimezone(UTC):
            continue
        if interval.minute % 10 or interval.second or interval.microsecond:
            raise ValueError(
                "source observation interval is not on the ten-minute cadence"
            )
        candidate = (calculated, key, price)
        if interval not in selected or candidate[:2] > selected[interval][:2]:
            selected[interval] = candidate
    return {interval: selected[interval][2] for interval in selected}


def _hourly_rows(
    paths: tuple[_Path, ...],
    prices: dict[str, list[dict[datetime, Decimal]]],
    start: datetime,
    end: datetime,
) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    by_group: dict[tuple[str, str, str, str], list[_Path]] = defaultdict(list)
    for path in paths:
        by_group[path.group].append(path)
    result: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for group, grouped_paths in by_group.items():
        buckets: dict[datetime, list[Decimal]] = defaultdict(list)
        for path in grouped_paths:
            leg_prices = prices[path.path_id]
            aligned: set[datetime] = set(leg_prices[0]) if leg_prices else set()
            for values_by_interval in leg_prices[1:]:
                aligned.intersection_update(values_by_interval)
            for interval in aligned:
                buckets[interval.replace(minute=0, second=0, microsecond=0)].append(
                    sum((values[interval] for values in leg_prices), Decimal())
                )
        rows: list[dict[str, Any]] = []
        for hour in _hour_starts(start, end):
            values, local = sorted(buckets[hour]), hour.astimezone(_EASTERN)
            observed, expected = len(values), len(grouped_paths) * 6
            if observed > expected:
                raise ValueError("hourly observed count exceeds expected count")
            rows.append(
                {
                    "utc_start": _utc_text(hour),
                    "local_start": local.isoformat(),
                    "status": "priced" if observed else "missing",
                    "observed_count": observed,
                    "expected_count": expected,
                    "minimum": f"{values[0]:.2f}" if values else None,
                    "median": f"{median(values):.2f}" if values else None,
                    "maximum": f"{values[-1]:.2f}" if values else None,
                }
            )
        result[group] = rows
    return result


def _report_document(
    path: _Path,
    path_count: int,
    start: datetime,
    end: datetime,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": PUBLICATION_FORMAT_VERSION,
        "facility": FACILITY,
        "route": {
            "origin_area": path.origin_area,
            "destination_area": path.destination_area,
            "direction": path.direction,
        },
        "week": {
            "timezone": "America/New_York",
            "start_local": start.isoformat(),
            "end_local": end.isoformat(),
            "start_utc": _utc_text(start),
            "end_utc": _utc_text(end),
        },
        "cadence_minutes": 10,
        "path_count": path_count,
        "hours": rows,
    }


def _render_report_html(document: dict[str, Any], canonical_url: str) -> str:
    route = cast(dict[str, str], document["route"])
    cells = (
        "local_start",
        "status",
        "observed_count",
        "expected_count",
        "minimum",
        "median",
        "maximum",
    )
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(row[field] if row[field] is not None else '—'))}</td>"
            for field in cells
        )
        + "</tr>"
        for row in cast(list[dict[str, Any]], document["hours"])
    )
    title = f"{route['origin_area']} to {route['destination_area']} tolls"
    week = cast(dict[str, str], document["week"])
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><link rel="canonical" href="{escape(canonical_url, quote=True)}"><title>{escape(title)}</title></head><body><main><h1>{escape(title)}</h1><p>{escape(week["start_local"])} to {escape(week["end_local"])}</p><table><thead><tr><th>Date/hour</th><th>Status</th><th>Observed</th><th>Expected</th><th>Min</th><th>Median</th><th>Max</th></tr></thead><tbody>{rows}</tbody></table></main></body></html>\n'


def _render_index(paths: tuple[_Path, ...]) -> str:
    links = "".join(
        f'<li><a href="/{escape(_route_key(path), quote=True)}/">{escape(path.origin_area)} to {escape(path.destination_area)} ({escape(path.direction)})</a></li>'
        for path in paths
    )
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>I-95/I-495 toll reports</title></head><body><main><h1>I-95/I-495 toll reports</h1><ul>{links}</ul></main></body></html>\n'


def _render_sitemap(paths: tuple[_Path, ...]) -> str:
    urls = "".join(
        f"<url><loc>{escape(PUBLIC_BASE_URL + '/' + _route_key(path) + '/', quote=False)}</loc></url>"
        for path in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + urls
        + "</urlset>\n"
    )


def _put_object(
    s3_client: Any,  # noqa: ANN401
    bucket: str,
    key: str,
    body: str,
    content_type: str,
    cache_control: str,
) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode(),
        ContentType=content_type,
        CacheControl=cache_control,
    )


def _record_failure(phase: str, error: Exception, count: int = 0) -> None:
    logger.error(
        "V2_REPORT_PUBLICATION_FAILED phase=%s facility=%s count=%s error=%s",
        phase,
        FACILITY,
        count,
        type(error).__name__,
    )


def _cleanup_stale(s3_client: Any, bucket: str, desired: set[str]) -> None:  # noqa: ANN401
    listed: list[str] = []
    try:
        for page in s3_client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=f"{PUBLIC_PREFIX}/"
        ):
            for item in cast(list[dict[str, object]], page.get("Contents", [])):
                key = item.get("Key")
                if not isinstance(key, str) or not key.startswith(f"{PUBLIC_PREFIX}/"):
                    raise ValueError("publication listing returned an invalid key")
                listed.append(key)
    except Exception as error:
        _record_failure("list", error, len(listed))
        raise
    stale = sorted(set(listed) - desired)
    for offset in range(0, len(stale), 1000):
        keys = stale[offset : offset + 1000]
        try:
            response = s3_client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
            )
        except Exception as error:
            _record_failure("delete", error, len(keys))
            raise
        try:
            raw_errors = response.get("Errors", [])
            if not isinstance(raw_errors, list):
                raise ValueError("publication cleanup response is malformed")
            errors = cast(list[object], raw_errors)
        except Exception as error:
            _record_failure("delete", error, len(keys))
            raise
        if errors:
            error = RuntimeError("publication cleanup delete failed")
            _record_failure("delete", error, len(errors))
            raise error


def _publish(
    paths: tuple[_Path, ...],
    reader: Any,  # noqa: ANN401
    s3_client: Any,  # noqa: ANN401
    bucket: str,
    invoked_at: datetime,
) -> dict[str, Any]:
    start, end = _week_window(invoked_at)
    try:
        prices = {
            path.path_id: [
                _selected_prices(
                    _source_rows(reader, leg, start, end, invoked_at),
                    start,
                    end,
                    invoked_at,
                )
                for leg in path.legs
            ]
            for path in paths
        }
        hourly = _hourly_rows(paths, prices, start, end)
    except Exception as error:
        _record_failure("pre_mutation", error)
        raise
    grouped: dict[tuple[str, str, str, str], list[_Path]] = defaultdict(list)
    for path in paths:
        grouped[path.group].append(path)
    representatives = tuple(
        sorted((values[0] for _, values in sorted(grouped.items())), key=_route_key)
    )
    try:
        documents = [
            (
                path,
                _report_document(
                    path, len(grouped[path.group]), start, end, hourly[path.group]
                ),
            )
            for path in representatives
        ]
        result_sha256 = hashlib.sha256(
            json.dumps(
                [document for _, document in documents],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        objects = [
            (
                "report_put",
                f"{_route_key(path)}/report.json",
                json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                "application/json; charset=utf-8",
                PUBLIC_CACHE_CONTROL,
            )
            for path, document in documents
        ] + [
            (
                "report_put",
                f"{_route_key(path)}/index.html",
                _render_report_html(document, f"{PUBLIC_BASE_URL}/{_route_key(path)}/"),
                "text/html; charset=utf-8",
                PUBLIC_CACHE_CONTROL,
            )
            for path, document in documents
        ]
        objects += [
            (
                "discovery_put",
                f"{PUBLIC_PREFIX}/index.html",
                _render_index(representatives),
                "text/html; charset=utf-8",
                PUBLIC_CACHE_CONTROL,
            ),
            (
                "discovery_put",
                "sitemap.xml",
                _render_sitemap(representatives),
                "application/xml; charset=utf-8",
                PUBLIC_CACHE_CONTROL,
            ),
        ]
        desired = {key for _, key, *_ in objects if key.startswith(f"{PUBLIC_PREFIX}/")}
        manifest = {
            "schema_version": PUBLICATION_FORMAT_VERSION,
            "facility": FACILITY,
            "route_count": EXPECTED_GROUP_COUNT,
            "week_end": _utc_text(end),
            "result_sha256": result_sha256,
        }
        objects.append(
            (
                "manifest_put",
                MANIFEST_KEY,
                json.dumps(manifest, sort_keys=True) + "\n",
                "application/json; charset=utf-8",
                MANIFEST_CACHE_CONTROL,
            )
        )
    except Exception as error:
        _record_failure("pre_mutation", error)
        raise
    desired.add(MANIFEST_KEY)
    for phase, key, body, content_type, cache_control in objects:
        try:
            _put_object(s3_client, bucket, key, body, content_type, cache_control)
        except Exception as error:
            _record_failure(phase, error)
            raise
    _cleanup_stale(s3_client, bucket, desired)
    return {
        "status": "published",
        "generation_id": _utc_text(end),
        "route_count": EXPECTED_GROUP_COUNT,
        "result_sha256": result_sha256,
    }


def _connect(*, reader: bool = False) -> object:
    import psycopg  # type: ignore[import-not-found]
    from psycopg.rows import dict_row  # type: ignore[import-not-found]

    host, port = os.environ["DB_HOST"], int(os.environ["DB_PORT"])
    user = os.environ.get("DB_READER_USER") if reader else os.environ["DB_USER"]
    if not user:
        raise RuntimeError("DB_READER_USER is required for raw history reads")
    token = (
        cast(Any, boto3)
        .client("rds")
        .generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user)
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=os.environ["DB_NAME"],
        user=user,
        password=token,
        sslmode="verify-full",
        sslrootcert=CA_BUNDLE_PATH,
        row_factory=cast(Any, dict_row),
    )


def _watchdog_smoke_id(event: dict[str, Any]) -> str | None:
    if event.get("trigger") != "watchdog":
        return None
    if set(event) - {"trigger", "smoke_id"}:
        raise ValueError("unsupported watchdog event")
    smoke_id = event.get("smoke_id")
    if smoke_id is None:
        return None
    if not isinstance(smoke_id, str) or str(uuid.UUID(smoke_id)) != smoke_id:
        raise ValueError("smoke_id must be a canonical UUID")
    return smoke_id


def _expected_watermark(event: dict[str, Any]) -> datetime | None:
    if event.get("trigger") == "watchdog":
        _watchdog_smoke_id(event)
        return None
    if (
        "smoke_id" in event
        or event.get("source") != "tollchat.pricing-loader"
        or event.get("detail-type") != "I95 Pricing Load Committed"
        or not isinstance(event.get("detail"), dict)
    ):
        raise ValueError("unsupported publisher event")
    detail = _LoadDetail.model_validate(event["detail"])
    if detail.environment != os.environ.get("TOLLCHAT_ENVIRONMENT", "production"):
        raise ValueError("publisher event environment does not match runtime")
    return _aware_timestamp(detail.source_watermark, label="source watermark")


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    try:
        if event.get("trigger") == "watchdog":
            smoke_id = _watchdog_smoke_id(event)
        else:
            _expected_watermark(event)
            smoke_id = None
    except Exception as error:
        _record_failure("pre_mutation", error)
        raise
    try:
        enabled = os.getenv("REPORT_PUBLICATION_ENABLED", "false").lower()
        if enabled not in {"true", "false"}:
            raise ValueError("REPORT_PUBLICATION_ENABLED must be true or false")
    except Exception as error:
        _record_failure("pre_mutation", error)
        raise
    if enabled == "false":
        return {"status": "disabled", "facility": FACILITY}
    invoked_at = datetime.now(UTC)
    try:
        report = cast(Any, _connect())
    except Exception as error:
        _record_failure("pre_mutation", error)
        raise
    try:
        try:
            paths = _validate_paths(_read_report_rows(report))
        except Exception as error:
            _record_failure("pre_mutation", error)
            raise
        try:
            bucket = os.environ["SITE_BUCKET_NAME"].strip()
            if not bucket:
                raise ValueError("SITE_BUCKET_NAME must be non-empty")
        except Exception as error:
            _record_failure("pre_mutation", error)
            raise
        try:
            reader = cast(Any, _connect(reader=True))
        except Exception as error:
            _record_failure("pre_mutation", error)
            raise
        try:
            setup_complete = False
            publish_complete = False
            owned_error: Exception | None = None
            try:
                with reader.transaction():
                    with reader.cursor() as cursor:
                        cursor.execute(
                            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                        )
                        cursor.execute("SET LOCAL statement_timeout = '180s'")
                    setup_complete = True
                    try:
                        s3_client = cast(Any, boto3).client("s3")
                    except Exception as error:
                        _record_failure("pre_mutation", error)
                        owned_error = error
                        raise
                    try:
                        result = _publish(paths, reader, s3_client, bucket, invoked_at)
                    except Exception as error:
                        owned_error = error
                        raise
                    publish_complete = True
            except Exception as error:
                if not setup_complete:
                    _record_failure("pre_mutation", error)
                elif publish_complete or error is not owned_error:
                    _record_failure("reader_finalize", error)
                raise
        finally:
            try:
                reader.close()
            except Exception as error:
                _record_failure("pre_mutation", error)
                raise
    finally:
        try:
            report.close()
        except Exception as error:
            _record_failure("pre_mutation", error)
            raise
    try:
        _log_success(result["generation_id"], result["route_count"], invoked_at)
    except Exception as error:
        _record_failure("success_emit", error)
        raise
    if smoke_id:
        try:
            logger.info(
                "V2_REPORT_SMOKE_OK %s %s %s %s",
                smoke_id,
                result["status"],
                result["generation_id"],
                result["result_sha256"],
            )
        except Exception as error:
            _record_failure("smoke_emit", error)
            raise
    return {"facility": FACILITY, **result}


def _log_success(generation_id: str, route_count: int, invoked_at: datetime) -> None:
    marker = _week_window(invoked_at)[1].astimezone(UTC)
    dimensions: dict[str, str] = {"facility": FACILITY}
    if (
        environment := os.environ.get("TOLLCHAT_ENVIRONMENT", "production")
    ) != "production":
        dimensions["Environment"] = environment
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(marker.timestamp() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "NovaToll",
                            "Dimensions": [list(dimensions)],
                            "Metrics": [
                                {"Name": "V2ReportGenerationSuccess", "Unit": "Count"}
                            ],
                        }
                    ],
                },
                **dimensions,
                "V2ReportGenerationSuccess": 1,
            }
        )
    )
    logger.info(
        "V2_REPORT_GENERATION_OK %s %s %s", FACILITY, generation_id, route_count
    )

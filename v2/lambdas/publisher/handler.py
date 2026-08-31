"""Build one validated I-95/I-495 report generation from a bounded snapshot."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from itertools import groupby
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, cast
from zoneinfo import ZoneInfo

import boto3
from pydantic import BaseModel, ConfigDict, Field

from agent_tools import current_price_domain as pricing
from agent_tools import validate_toll_route as route_validation

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FACILITY = "i95_i495"
EXPECTED_ROUTE_COUNT = 685
REPORT_SQL = "SELECT * FROM oracle.get_i95_i495_report_inputs()"
CA_BUNDLE_PATH = str(Path(__file__).with_name("rds-ca-bundle.pem"))
PUBLIC_PREFIX = "tolls/i95-i495"
MANIFEST_KEY = f"{PUBLIC_PREFIX}/manifest.json"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://tollchat.ai").rstrip("/")
PUBLICATION_FORMAT_VERSION = "2.0.0"
PUBLIC_CACHE_CONTROL = "public, max-age=300"
MANIFEST_CACHE_CONTROL = "no-cache"
_EASTERN = ZoneInfo("America/New_York")
_RUNTIME_FIELDS = {
    "component_evaluated_at",
    "evaluated_at",
    "generation_id",
    "published_at",
    "source_watermark",
}


class _S3Body(Protocol):
    def read(self, amount: int = -1) -> bytes: ...


class _S3Client(Protocol):
    def list_objects_v2(
        self, *, Bucket: str, Prefix: str, MaxKeys: int
    ) -> dict[str, object]: ...

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]: ...

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        CacheControl: str,
    ) -> object: ...


_ROUTE_FIELDS = (
    "snapshot_evaluated_at",
    "origin",
    "destination",
    "structural_facility_legs",
    "status",
    "reason",
    "point_ids",
    "connection_ids",
    "connection_types",
    "general_purpose_gaps",
    "i95_evidence",
    "facility_legs",
)
_COMPARISON_FIELDS = (
    "comparison_kind",
    "comparison_offset",
    "bin_start_at",
    "bin_end_at",
    "interval_end_at",
    "observed_at",
    "price_usd",
    "available",
    "availability_reason",
    "source_kind",
    "pricing_method",
    "od_pair_id",
    "proxy_od_pair_id",
    "source_status",
)
_ROW_FIELDS = {*_ROUTE_FIELDS, "route_step_id", *_COMPARISON_FIELDS}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Endpoint(_Model):
    point_id: str
    label: str
    place_name: str
    region: str
    country_code: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    aliases: list[str]
    nearby_landmarks: list[str]
    direction: Literal["northbound", "southbound"]
    role: Literal["entry", "exit"]
    display_name: str
    location: dict[str, Any]


class GenerationRoute(_Model):
    origin: Endpoint
    destination: Endpoint
    structural_facility_legs: list[dict[str, Any]]
    current_price: dict[str, Any]


class Generation(_Model):
    facility: Literal["i95_i495"]
    generation_id: datetime
    evaluated_at: datetime
    source_watermark: datetime | None
    routes: Annotated[
        list[GenerationRoute],
        Field(min_length=EXPECTED_ROUTE_COUNT, max_length=EXPECTED_ROUTE_COUNT),
    ]


@dataclass(frozen=True)
class _ObservationCoverage:
    expected_rush_observations: int
    observed_rush_observations: int
    expected_off_rush_bins: int
    observed_off_rush_bins: int


@dataclass(frozen=True)
class _ObservationSelection:
    rows: tuple[dict[str, Any], ...]
    coverage: _ObservationCoverage
    rush_rows: tuple[dict[str, Any], ...]
    hourly_bins: tuple[tuple[datetime, tuple[dict[str, Any], ...]], ...]


@dataclass(frozen=True)
class _RouteDescriptor:
    key: tuple[str, str]
    origin: Endpoint
    destination: Endpoint
    source_watermark: datetime | None


def _weekly_run_at(invoked_at: datetime) -> datetime:
    """Return the completed-week boundary using Eastern calendar arithmetic."""
    local = _require_aware(invoked_at, label="invoked_at").astimezone(_EASTERN)
    monday = (local - timedelta(days=local.weekday())).date()
    boundary = datetime(monday.year, monday.month, monday.day, 1, tzinfo=_EASTERN)
    return boundary if local >= boundary else boundary - timedelta(weeks=1)


def _slugify(*parts: str) -> str:
    text = "-".join(parts)
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if not slug:
        raise ValueError("report slug is empty")
    return slug


def _slug_candidate(endpoint: Endpoint) -> str:
    parts = [endpoint.place_name]
    seen = {endpoint.place_name.casefold()}
    for alias in endpoint.aliases:
        key = alias.casefold()
        if key not in seen:
            parts.append(alias)
            seen.add(key)
        if len(parts) == 3:
            break
    parts.append(endpoint.direction)
    return _slugify(*parts)


def _build_slug_map(
    endpoints: list[Endpoint], existing: dict[str, str] | None = None
) -> dict[str, str]:
    by_id: dict[str, Endpoint] = {}
    for endpoint in endpoints:
        prior = by_id.setdefault(endpoint.point_id, endpoint)
        if prior != endpoint:
            raise ValueError(f"endpoint metadata disagrees for {endpoint.point_id}")

    if existing is not None:
        if any(slug != _slugify(slug) for slug in existing.values()):
            raise ValueError("manifest point-slug mapping is malformed")
        if not by_id.keys() <= existing.keys():
            raise ValueError("manifest point-slug mapping is incomplete")
        if len(set(existing.values())) != len(existing):
            raise ValueError("manifest point-slug mapping is not unique")
        return dict(sorted(existing.items()))

    candidates = {
        point_id: _slug_candidate(endpoint) for point_id, endpoint in by_id.items()
    }
    groups: dict[str, list[str]] = defaultdict(list)
    for point_id, candidate in candidates.items():
        groups[candidate].append(point_id)
    slugs: dict[str, str] = {}
    for candidate, point_ids in groups.items():
        primary = min(
            point_ids, key=lambda value: (len(_slugify(value)), _slugify(value))
        )
        for point_id in point_ids:
            slugs[point_id] = (
                candidate
                if point_id == primary
                else f"{candidate}-{_slugify(point_id)}"
            )
    if len(set(slugs.values())) != len(slugs):
        raise ValueError("descriptive point slugs are not unique")
    return dict(sorted(slugs.items()))


class _LoadDetail(_Model):
    environment: Literal["development", "production"]
    schema_version: Literal[1]
    facility: Literal["i95_i495"]
    source_watermark: str
    source_key: Annotated[
        str,
        Field(
            pattern=r"^raw/feed=i95/date=\d{4}-\d{2}-\d{2}/\d{4}Z(?:-[a-f0-9]{16})?\.csv$"
        ),
    ]
    row_count: Annotated[int, Field(gt=0)]


def _utc_text(value: datetime | None) -> str | None:
    return (
        value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if value is not None
        else None
    )


def _aware_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is not an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(UTC)


def _require_aware(value: object, *, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be an aware datetime")
    return value


def _source_order(row: dict[str, Any]) -> tuple[datetime, datetime, str]:
    return (
        _require_aware(row["interval_end_at"], label="interval_end_at").astimezone(UTC),
        _require_aware(row["calculated_at"], label="calculated_at").astimezone(UTC),
        row["s3_key"],
    )


def _is_rush_observation(interval_end_at: datetime) -> bool:
    local = interval_end_at.astimezone(_EASTERN)
    return local.weekday() < 5 and (6 <= local.hour < 10 or 15 <= local.hour < 19)


def _select_weekly_observations(  # pyright: ignore[reportUnusedFunction]
    rows: list[dict[str, Any]],
    run_at: datetime,
    *,
    series_id: object,
    direction: Literal["northbound", "southbound"],
) -> _ObservationSelection:
    """Select one directed series for the four completed Eastern weeks."""
    if not isinstance(series_id, str) or not series_id:
        raise ValueError("series_id must be a non-empty string")
    if direction not in {"northbound", "southbound"}:
        raise ValueError("direction must be northbound or southbound")
    run_local = _require_aware(run_at, label="run_at").astimezone(_EASTERN)
    if run_local.weekday() != 0 or (
        run_local.hour,
        run_local.minute,
        run_local.second,
        run_local.microsecond,
    ) != (1, 0, 0, 0):
        raise ValueError("run_at must be Monday 01:00 America/New_York")
    window_end = run_local.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(weeks=4)
    window_start_utc = window_start.astimezone(UTC)
    window_end_utc = window_end.astimezone(UTC)

    rush_rows: list[dict[str, Any]] = []
    off_rush_bins: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("series_id") != series_id or row.get("direction") != direction:
            raise ValueError("row does not belong to the declared directed series")
        interval_end_at = _require_aware(
            row.get("interval_end_at"), label="interval_end_at"
        )
        _require_aware(row.get("calculated_at"), label="calculated_at")
        if not isinstance(row.get("s3_key"), str) or "zone_toll_rate_usd" not in row:
            raise ValueError("row is missing required source fields")
        interval_utc = interval_end_at.astimezone(UTC)
        if not window_start_utc <= interval_utc < window_end_utc:
            raise ValueError("row is outside the weekly observation window")
        if _is_rush_observation(interval_end_at):
            rush_rows.append(row)
        else:
            off_rush_bins[
                interval_utc.replace(minute=0, second=0, microsecond=0)
            ].append(row)

    selected = list(rush_rows)
    for bin_rows in off_rush_bins.values():
        latest = max(bin_rows, key=_source_order)
        minimum_price = min(row["zone_toll_rate_usd"] for row in bin_rows)
        maximum_price = max(row["zone_toll_rate_usd"] for row in bin_rows)
        minimum = max(
            (row for row in bin_rows if row["zone_toll_rate_usd"] == minimum_price),
            key=_source_order,
        )
        maximum = max(
            (row for row in bin_rows if row["zone_toll_rate_usd"] == maximum_price),
            key=_source_order,
        )
        selected.extend(
            {_source_order(row): row for row in (minimum, maximum, latest)}.values()
        )

    return _ObservationSelection(
        rows=tuple(sorted(selected, key=_source_order)),
        coverage=_ObservationCoverage(
            expected_rush_observations=960,
            observed_rush_observations=len(rush_rows),
            expected_off_rush_bins=int(
                (window_end_utc - window_start_utc).total_seconds() // 3600
            )
            - 160,
            observed_off_rush_bins=len(off_rush_bins),
        ),
        rush_rows=tuple(sorted(rush_rows, key=_source_order)),
        hourly_bins=tuple(
            (hour_start, tuple(rows))
            for hour_start, rows in sorted(off_rush_bins.items())
        ),
    )


def _expected_watermark_action(
    expected: datetime, visible: datetime | None
) -> Literal["build", "superseded"]:
    if visible is None or expected > visible:
        raise RuntimeError("expected source watermark is not visible")
    return "superseded" if expected < visible else "build"


def _source_watermark(rows: list[dict[str, Any]]) -> datetime | None:
    values: list[datetime] = []
    for row in rows:
        evidence = row.get("i95_evidence")
        if not isinstance(evidence, dict):
            continue
        evidence_values = cast(dict[str, Any], evidence)
        for field in (
            "northbound_interval_end_at",
            "southbound_interval_end_at",
        ):
            value = evidence_values.get(field)
            if isinstance(value, str):
                values.append(_aware_timestamp(value, label=field))
    return max(values) if values else None


def _route_value(rows: list[dict[str, Any]], field: str) -> Any:  # noqa: ANN401
    value = rows[0][field]
    if any(row[field] != value for row in rows[1:]):
        raise ValueError(f"route rows disagree on {field}")
    return value


def _build_route(rows: list[dict[str, Any]]) -> GenerationRoute:
    origin = Endpoint.model_validate(_route_value(rows, "origin"))
    destination = Endpoint.model_validate(_route_value(rows, "destination"))
    request = pricing._PricingRequest(  # pyright: ignore[reportPrivateUsage]
        origin_point_id=origin.point_id,
        destination_point_id=destination.point_id,
        pricing_profile=pricing._SUPPORTED_PROFILE,  # pyright: ignore[reportPrivateUsage]
    )
    route_input = route_validation._RouteInput(  # pyright: ignore[reportPrivateUsage]
        origin_point_id=origin.point_id,
        destination_point_id=destination.point_id,
    )
    route = route_validation._PricingRouteResponse.model_validate(  # pyright: ignore[reportPrivateUsage]
        {field: _route_value(rows, field) for field in _ROUTE_FIELDS[4:]},
        context={"request": route_input},
    )
    structural_values = _route_value(rows, "structural_facility_legs")
    if not isinstance(structural_values, list) or not structural_values:
        raise ValueError("structural facility legs are malformed")
    structural_rows = cast(list[dict[str, Any]], structural_values)
    structural_legs = [
        route_validation._I95FacilityLeg.model_validate(value)  # pyright: ignore[reportPrivateUsage]
        for value in structural_rows
    ]
    route_validation.validate_facility_leg_alignment(
        route.point_ids,
        route.connection_ids,
        route.connection_types,
        cast(list[Any], structural_legs),
    )
    if route.status == "valid" and route.facility_legs != structural_legs:
        raise ValueError("current and structural facility legs disagree")
    pricing_inputs: dict[str, object] = {}
    comparisons: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        step_id = row["route_step_id"]
        if step_id is None:
            if any(row[field] is not None for field in _COMPARISON_FIELDS):
                raise ValueError("route without a pricing step contains comparisons")
            continue
        if not isinstance(step_id, str):
            raise ValueError("route step ID is malformed")
        comparison = pricing._I95ComparisonRow.model_validate(  # pyright: ignore[reportPrivateUsage]
            {
                "evaluated_at": rows[0]["snapshot_evaluated_at"],
                **{field: row[field] for field in _COMPARISON_FIELDS},
            }
        )
        comparisons[step_id].append(comparison)
    for step_id, values in comparisons.items():
        pricing._validate_comparison_rows(  # pyright: ignore[reportPrivateUsage]
            values, "I-95/I-495"
        )
        pricing_inputs[step_id] = values
    current_price = pricing.build_current_price_result(
        request,
        route,
        cast(datetime, rows[0]["snapshot_evaluated_at"]),
        pricing_inputs,
    )
    return GenerationRoute(
        origin=origin,
        destination=destination,
        structural_facility_legs=[
            leg.model_dump(mode="json") for leg in structural_legs
        ],
        current_price=current_price,
    )


def build_generation(rows: list[dict[str, Any]]) -> Generation:
    if not rows or any(set(row) != _ROW_FIELDS for row in rows):
        raise ValueError("bounded report operation returned malformed rows")
    evaluated_values = {row["snapshot_evaluated_at"] for row in rows}
    if len(evaluated_values) != 1:
        raise ValueError("report rows do not share one evaluation timestamp")
    evaluated_at = next(iter(evaluated_values))
    if not isinstance(evaluated_at, datetime) or evaluated_at.tzinfo is None:
        raise ValueError("report evaluation timestamp must be timezone-aware")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        origin = row["origin"]
        destination = row["destination"]
        if not isinstance(origin, dict) or not isinstance(destination, dict):
            raise ValueError("report endpoint is malformed")
        origin_values = cast(dict[str, Any], origin)
        destination_values = cast(dict[str, Any], destination)
        key = (origin_values.get("point_id"), destination_values.get("point_id"))
        if not all(isinstance(value, str) for value in key):
            raise ValueError("report endpoint ID is malformed")
        grouped[cast(tuple[str, str], key)].append(row)
    if len(grouped) != EXPECTED_ROUTE_COUNT:
        raise ValueError(f"report snapshot must contain {EXPECTED_ROUTE_COUNT} routes")

    routes = [_build_route(grouped[key]) for key in sorted(grouped)]
    evaluated_at = evaluated_at.astimezone(UTC)
    return Generation(
        facility=FACILITY,
        generation_id=evaluated_at,
        evaluated_at=evaluated_at,
        source_watermark=_source_watermark(rows),
        routes=routes,
    )


def _build_stream_document(
    evaluated_at: datetime,
    source_watermark: datetime | None,
    route: GenerationRoute,
    published_at: datetime,
    weekly: list[dict[str, Any]],
) -> dict[str, Any]:
    if not weekly:
        raise ValueError("report route has no weekly components")
    coverage = {
        key: weekly[0]["window"][key] for key in ("window_start_at", "window_end_at")
    }
    if any(item["window"] != coverage for item in weekly[1:]):
        raise ValueError("weekly component windows disagree")
    return {
        "schema": "2.0.0",
        "generation": {
            "generation_id": _utc_text(evaluated_at),
            "published_at": _utc_text(published_at),
            "source_watermark": _utc_text(source_watermark),
        },
        "facility": FACILITY,
        "coverage": coverage,
        "route": {
            "origin": route.origin.model_dump(mode="json"),
            "destination": route.destination.model_dump(mode="json"),
        },
        "components": [
            {key: value for key, value in item.items() if key != "window"}
            for item in weekly
        ],
    }


def _without_runtime_fields(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, dict):
        values = cast(dict[str, Any], value)
        return {
            key: _without_runtime_fields(item)
            for key, item in values.items()
            if key not in _RUNTIME_FIELDS
        }
    if isinstance(value, list):
        return [_without_runtime_fields(item) for item in cast(list[Any], value)]
    return value


def _result_fingerprint(
    documents: list[dict[str, Any]], point_slugs: dict[str, str]
) -> str:
    canonical = json.dumps(
        {
            "publication_format_version": PUBLICATION_FORMAT_VERSION,
            "point_slugs": point_slugs,
            "reports": _without_runtime_fields(documents),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _display_time(value: str | None) -> str:
    if value is None:
        return "Unavailable"
    return (
        _aware_timestamp(value, label="report timestamp")
        .astimezone(_EASTERN)
        .strftime("%B %-d, %Y at %-I:%M %p %Z")
    )


def _endpoint_html(title: str, endpoint: dict[str, Any]) -> str:
    aliases = ", ".join(escape(str(value)) for value in endpoint["aliases"]) or "None"
    landmarks = (
        ", ".join(escape(str(value)) for value in endpoint["nearby_landmarks"])
        or "None"
    )
    return (
        f"<section><h2>{escape(title)}</h2><dl>"
        f"<dt>Point ID</dt><dd>{escape(str(endpoint['point_id']))}</dd>"
        f"<dt>Place</dt><dd>{escape(str(endpoint['place_name']))}, "
        f"{escape(str(endpoint['region']))}</dd>"
        f"<dt>Country code</dt><dd>{escape(str(endpoint['country_code']))}</dd>"
        f"<dt>Display name</dt><dd>{escape(str(endpoint['display_name']))}</dd>"
        f"<dt>Location</dt><dd>{escape(json.dumps(endpoint['location'], sort_keys=True))}</dd>"
        f"<dt>Roadway access</dt><dd>{escape(str(endpoint['label']))}</dd>"
        f"<dt>Direction and role</dt><dd>{escape(str(endpoint['direction']))} "
        f"{escape(str(endpoint['role']))}</dd>"
        f"<dt>Also known as</dt><dd>{aliases}</dd>"
        f"<dt>Nearby landmarks</dt><dd>{landmarks}</dd>"
        f"</dl></section>"
    )


def _render_report_html(document: dict[str, Any], canonical_url: str) -> str:
    route = cast(dict[str, Any], document["route"])
    origin = cast(dict[str, Any], route["origin"])
    destination = cast(dict[str, Any], route["destination"])
    origin_name = escape(str(origin["place_name"]))
    destination_name = escape(str(destination["place_name"]))
    title = f"I-95/I-495 toll evidence from {origin_name} to {destination_name}"
    generation = cast(dict[str, Any], document["generation"])
    coverage = cast(dict[str, Any], document["coverage"])

    def rows(values: Any, *, row_headers: bool = False) -> str:  # noqa: ANN401
        return "".join(
            "<tr>"
            + (
                f'<th scope="row">{escape(str(value_set[0]))}</th>'
                + "".join(f"<td>{escape(str(value))}</td>" for value in value_set[1:])
                if row_headers
                else "".join(f"<td>{escape(str(value))}</td>" for value in value_set)
            )
            + "</tr>"
            for value_set in values
        )

    def source_row(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            row["corridor_name"],
            row["od_pair_id"],
            row["start_zone"]["id"],
            row["start_zone"]["name"],
            row["end_zone"]["id"],
            row["end_zone"]["name"],
            row["interval_end_at"],
            row["observed_at"],
            row["price_usd"],
            row["link_status"],
        )

    headers = (
        "<tr>"
        + "".join(
            f'<th scope="col">{label}</th>'
            for label in (
                "Corridor",
                "Source OD",
                "Start zone ID",
                "Start zone",
                "End zone ID",
                "End zone",
                "Interval end",
                "Observed",
                "Price",
                "Link status",
            )
        )
        + "</tr>"
    )
    component_html = "".join(
        "<section><h3>Component " + escape(str(component["route_step_id"])) + "</h3>"
        "<table><caption>Component provenance and coverage</caption><thead><tr>"
        '<th scope="col">Field</th><th scope="col">Value</th>'
        "</tr></thead><tbody>"
        + "".join(
            f'<tr><th scope="row">{escape(key)}</th><td>{escape(str(value))}</td></tr>'
            for key, value in {
                **cast(dict[str, Any], component["provenance"]),
                **cast(dict[str, Any], component["coverage"]),
            }.items()
        )
        + "</tbody></table>"
        + "<h4>Rush observations</h4><table><caption>Every selected rush observation</caption><thead>"
        + headers
        + "</thead><tbody>"
        + rows(source_row(row) for row in component["rush_observations"])
        + "</tbody></table>"
        + "<h4>Off-rush hourly bins</h4>"
        + "".join(
            "<table><caption>UTC hour "
            + escape(str(bin["hour_start_at"]))
            + "; "
            + escape(str(bin["source_count"]))
            + ' source observations</caption><thead><tr><th scope="col">Role</th>'
            + "".join(
                f'<th scope="col">{label}</th>'
                for label in (
                    "Corridor",
                    "Source OD",
                    "Start zone ID",
                    "Start zone",
                    "End zone ID",
                    "End zone",
                    "Interval end",
                    "Observed",
                    "Price",
                    "Link status",
                )
            )
            + "</tr></thead><tbody>"
            + rows(
                (
                    (role, *source_row(bin[role]))
                    for role in ("minimum", "maximum", "last")
                ),
                row_headers=True,
            )
            + "</tbody></table>"
            for bin in component["hourly_bins"]
        )
        + "</section>"
        for component in cast(list[dict[str, Any]], document["components"])
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title>"
        '<link rel="icon" type="image/png" sizes="64x64" href="/assets/favicon.png">'
        f'<link rel="canonical" href="{escape(canonical_url)}">'
        '<link rel="alternate" type="application/json" href="report.json">'
        "</head><body><main>"
        f"<h1>{title}</h1><p>Facility: {escape(str(document['facility']))}.</p>"
        f"<p>Published {_display_time(cast(str, generation['published_at']))}; source watermark: {escape(str(generation['source_watermark']))}.</p>"
        f"<p>Evidence window: {escape(str(coverage['window_start_at']))} to {escape(str(coverage['window_end_at']))}.</p>"
        "<h2>Route details</h2>"
        f"{_endpoint_html('Origin', origin)}{_endpoint_html('Destination', destination)}"
        f"<section><h2>Component evidence</h2>{component_html}</section>"
        '<p><a href="report.json">View the machine-readable JSON report</a></p>'
        f"<p>Generation {escape(str(generation['generation_id']))}</p>"
        "</main></body></html>\n"
    )


def _render_index_html(
    documents: list[dict[str, Any]], point_slugs: dict[str, str]
) -> str:
    links: list[str] = []
    for document in sorted(
        documents,
        key=lambda item: (
            item["route"]["origin"]["place_name"],
            item["route"]["destination"]["place_name"],
            item["route"]["origin"]["direction"],
        ),
    ):
        origin = document["route"]["origin"]
        destination = document["route"]["destination"]
        href = (
            f"./{point_slugs[origin['point_id']]}/"
            f"{point_slugs[destination['point_id']]}/"
        )
        origin_aliases = ", ".join(origin["aliases"])
        destination_aliases = ", ".join(destination["aliases"])
        label = (
            f"{origin['place_name']} — {origin['label']} ({origin_aliases}; "
            f"{origin['direction']}) to {destination['place_name']} — "
            f"{destination['label']} ({destination_aliases}; "
            f"{destination['direction']})"
        )
        links.append(f'<li><a href="{escape(href)}">{escape(label)}</a></li>')
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>I-95/I-495 toll evidence reports</title>"
        '<link rel="canonical" href="https://tollchat.ai/tolls/i95-i495/">'
        "</head><body><main>"
        "<h1>I-95/I-495 toll evidence reports</h1><p>Choose a directed entry-to-exit "
        "route to inspect four completed weeks of source evidence.</p><ol>"
        + "".join(links)
        + "</ol></main></body></html>\n"
    )


def _route_key(document: dict[str, Any], point_slugs: dict[str, str]) -> str:
    route = document["route"]
    return (
        f"{PUBLIC_PREFIX}/{point_slugs[route['origin']['point_id']]}/"
        f"{point_slugs[route['destination']['point_id']]}"
    )


def _render_sitemap(
    documents: list[dict[str, Any]], point_slugs: dict[str, str], published_at: datetime
) -> str:
    lastmod = cast(str, _utc_text(published_at))
    urls = "".join(
        f"<url><loc>{PUBLIC_BASE_URL}/{_route_key(document, point_slugs)}/</loc>"
        f"<lastmod>{lastmod}</lastmod></url>"
        for document in documents
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>\n"
    )


def _read_manifest(s3_client: _S3Client, bucket: str) -> dict[str, Any] | None:
    listing = s3_client.list_objects_v2(Bucket=bucket, Prefix=MANIFEST_KEY, MaxKeys=1)
    contents = listing.get("Contents", [])
    if not isinstance(contents, list) or not any(
        isinstance(item, dict)
        and cast(dict[object, object], item).get("Key") == MANIFEST_KEY
        for item in cast(list[object], contents)
    ):
        return None
    try:
        response = s3_client.get_object(Bucket=bucket, Key=MANIFEST_KEY)
    except Exception as error:
        error_response = getattr(error, "response", {})
        response_values = (
            cast(dict[str, object], error_response)
            if isinstance(error_response, dict)
            else {}
        )
        error_values = response_values.get("Error")
        code = (
            cast(dict[str, object], error_values).get("Code")
            if isinstance(error_values, dict)
            else None
        )
        if code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise
    body = cast(_S3Body, response["Body"]).read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("publication manifest is too large")
    decoded: object = json.loads(body)
    manifest = cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}
    point_slugs = manifest.get("point_slugs")
    publication_format_version = manifest.get("publication_format_version", "0")
    if (
        not {
            "schema_version",
            "publication_format_version",
            "facility",
            "generation_id",
            "published_at",
            "source_watermark",
            "result_sha256",
            "route_count",
            "point_slugs",
        }
        <= manifest.keys()
        or manifest.get("schema_version") not in {"1.0.0", "2.0.0"}
        or manifest.get("facility") != FACILITY
        or not isinstance(publication_format_version, str)
        or not isinstance(manifest.get("generation_id"), str)
        or not isinstance(manifest.get("published_at"), str)
        or not (
            manifest.get("source_watermark") is None
            or isinstance(manifest.get("source_watermark"), str)
        )
        or manifest.get("route_count") != EXPECTED_ROUTE_COUNT
        or not isinstance(point_slugs, dict)
        or not all(
            isinstance(point_id, str) and isinstance(slug, str)
            for point_id, slug in cast(dict[object, object], point_slugs).items()
        )
        or not isinstance(manifest.get("result_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", cast(str, manifest.get("result_sha256")))
    ):
        raise ValueError("publication manifest is malformed")
    manifest["publication_format_version"] = publication_format_version
    try:
        _aware_timestamp(cast(str, manifest["generation_id"]), label="generation ID")
        _aware_timestamp(cast(str, manifest["published_at"]), label="published at")
        if manifest["source_watermark"] is not None:
            _aware_timestamp(
                cast(str, manifest["source_watermark"]), label="source watermark"
            )
    except ValueError as error:
        raise ValueError("publication manifest is malformed") from error
    return cast(dict[str, Any], manifest)


def _put_phase(
    s3_client: _S3Client,
    bucket: str,
    objects: list[tuple[str, str, str, str]],
) -> None:
    def put(value: tuple[str, str, str, str]) -> None:
        key, body, content_type, cache_control = value
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode(),
            ContentType=content_type,
            CacheControl=cache_control,
        )

    with ThreadPoolExecutor(max_workers=min(8, len(objects))) as executor:
        list(executor.map(put, objects))


def _put_generation_marker(
    s3_client: _S3Client,
    analytics_bucket: str,
    manifest: dict[str, Any],
    route_keys: list[str],
) -> None:
    published_at = cast(str, manifest["published_at"])
    marker = {
        "schema_version": 1,
        "facility": manifest["facility"],
        "generation_id": manifest["generation_id"],
        "published_at": published_at,
        "result_sha256": manifest["result_sha256"],
        "route_keys": route_keys,
    }
    marker_name = f"{published_at.replace(':', '')}-{manifest['result_sha256']}.json"
    s3_client.put_object(
        Bucket=analytics_bucket,
        Key=f"generations/date={published_at[:10]}/{marker_name}",
        Body=(json.dumps(marker, separators=(",", ":")) + "\n").encode(),
        ContentType="application/json",
        CacheControl="no-store",
    )


def _publish_generation(  # pyright: ignore[reportUnusedFunction]
    generation: Generation,
    s3_client: _S3Client,
    bucket: str,
    published_at: datetime,
    analytics_bucket: str | None = None,
) -> dict[str, Any]:
    raise RuntimeError(
        "legacy in-memory publication was removed; use _publish_streamed"
    )

    previous = _read_manifest(s3_client, bucket)
    endpoints = [
        endpoint
        for route in generation.routes
        for endpoint in (route.origin, route.destination)
    ]
    existing_slugs = (
        cast(dict[str, str], previous["point_slugs"]) if previous is not None else None
    )
    point_slugs = _build_slug_map(endpoints, existing_slugs)
    documents: list[dict[str, Any]] = []
    result_sha256 = _result_fingerprint(documents, point_slugs)
    route_keys = [_route_key(document, point_slugs) for document in documents]
    if previous is not None:
        previous_watermark = previous.get("source_watermark")
        if (
            isinstance(previous_watermark, str)
            and generation.source_watermark is not None
            and generation.source_watermark
            < _aware_timestamp(previous_watermark, label="manifest source watermark")
        ):
            return {"status": "superseded", "result_sha256": result_sha256}
        if previous["result_sha256"] == result_sha256:
            if analytics_bucket is not None:
                _put_generation_marker(
                    s3_client, analytics_bucket, previous, route_keys
                )
            return {"status": "unchanged", "result_sha256": result_sha256}

    json_objects = [
        (
            f"{_route_key(document, point_slugs)}/report.json",
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            "application/json; charset=utf-8",
            PUBLIC_CACHE_CONTROL,
        )
        for document in documents
    ]
    html_objects = [
        (
            f"{_route_key(document, point_slugs)}/index.html",
            _render_report_html(
                document,
                f"{PUBLIC_BASE_URL}/{_route_key(document, point_slugs)}/",
            ),
            "text/html; charset=utf-8",
            PUBLIC_CACHE_CONTROL,
        )
        for document in documents
    ]
    route_index = _render_index_html(documents, point_slugs)
    sitemap = _render_sitemap(documents, point_slugs, published_at)
    manifest = {
        "schema_version": "2.0.0",
        "publication_format_version": PUBLICATION_FORMAT_VERSION,
        "facility": generation.facility,
        "generation_id": _utc_text(generation.generation_id),
        "published_at": _utc_text(published_at),
        "source_watermark": _utc_text(generation.source_watermark),
        "result_sha256": result_sha256,
        "route_count": len(documents),
        "point_slugs": point_slugs,
    }

    _put_phase(s3_client, bucket, json_objects)
    _put_phase(s3_client, bucket, html_objects)
    _put_phase(
        s3_client,
        bucket,
        [
            (
                f"{PUBLIC_PREFIX}/index.html",
                route_index,
                "text/html; charset=utf-8",
                PUBLIC_CACHE_CONTROL,
            )
        ],
    )
    _put_phase(
        s3_client,
        bucket,
        [
            (
                "sitemap.xml",
                sitemap,
                "application/xml; charset=utf-8",
                PUBLIC_CACHE_CONTROL,
            )
        ],
    )
    _put_phase(
        s3_client,
        bucket,
        [
            (
                MANIFEST_KEY,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                "application/json; charset=utf-8",
                MANIFEST_CACHE_CONTROL,
            )
        ],
    )
    if analytics_bucket is not None:
        _put_generation_marker(s3_client, analytics_bucket, manifest, route_keys)
    return {"status": "published", "result_sha256": result_sha256}


def _connect(*, reader: bool = False) -> object:
    import psycopg  # type: ignore[import-not-found]
    from psycopg.rows import dict_row  # type: ignore[import-not-found]

    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    user = os.environ.get("DB_READER_USER") if reader else os.environ["DB_USER"]
    if not user:
        raise RuntimeError("DB_READER_USER is required for raw history reads")
    rds = cast(Any, boto3.client("rds"))  # pyright: ignore[reportUnknownMemberType]
    token = cast(
        str,
        rds.generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user),
    )
    return cast(
        object,
        psycopg.connect(
            host=host,
            port=port,
            dbname=os.environ["DB_NAME"],
            user=user,
            password=token,
            sslmode="verify-full",
            sslrootcert=CA_BUNDLE_PATH,
            row_factory=cast(Any, dict_row),
        ),
    )


def _read_report_rows() -> list[dict[str, Any]]:
    connection = cast(Any, _connect())
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '180s'")
            cursor.execute(REPORT_SQL)
            return cast(list[dict[str, Any]], cursor.fetchall())
    finally:
        connection.close()


def _cursor_rows(cursor: Any) -> Iterator[dict[str, Any]]:  # noqa: ANN401
    while batch := cursor.fetchmany(100):
        yield from batch


def _route_identity(row: dict[str, Any]) -> tuple[str, str]:
    if set(row) != _ROW_FIELDS:
        raise ValueError("bounded report operation returned malformed rows")
    origin, destination = row["origin"], row["destination"]
    if not isinstance(origin, dict) or not isinstance(destination, dict):
        raise ValueError("report endpoint is malformed")
    origin_values = cast(dict[str, Any], origin)
    destination_values = cast(dict[str, Any], destination)
    key = (origin_values.get("point_id"), destination_values.get("point_id"))
    if not all(isinstance(value, str) for value in key):
        raise ValueError("report endpoint ID is malformed")
    return cast(tuple[str, str], key)


def _preflight_report(
    rows: Iterator[dict[str, Any]],
) -> tuple[list[_RouteDescriptor], datetime, datetime | None]:
    descriptors: list[_RouteDescriptor] = []
    evaluated_at: datetime | None = None
    source_watermark: datetime | None = None
    last_key: tuple[str, str] | None = None
    for key, group in groupby(rows, _route_identity):
        group_rows = list(group)
        if key <= last_key if last_key is not None else False:
            raise ValueError("report routes are not strictly ordered")
        last_key = key
        snapshot = group_rows[0]["snapshot_evaluated_at"]
        if not isinstance(snapshot, datetime) or snapshot.tzinfo is None:
            raise ValueError("report evaluation timestamp must be timezone-aware")
        if any(row["snapshot_evaluated_at"] != snapshot for row in group_rows):
            raise ValueError("route rows disagree on snapshot evaluation timestamp")
        if evaluated_at is None:
            evaluated_at = snapshot.astimezone(UTC)
        elif evaluated_at != snapshot.astimezone(UTC):
            raise ValueError("report rows do not share one evaluation timestamp")
        route_watermark = _source_watermark(group_rows)
        descriptors.append(
            _RouteDescriptor(
                key,
                Endpoint.model_validate(group_rows[0]["origin"]),
                Endpoint.model_validate(group_rows[0]["destination"]),
                route_watermark,
            )
        )
        if route_watermark is not None and (
            source_watermark is None or route_watermark > source_watermark
        ):
            source_watermark = route_watermark
    if len(descriptors) != EXPECTED_ROUTE_COUNT or evaluated_at is None:
        raise ValueError(f"report snapshot must contain {EXPECTED_ROUTE_COUNT} routes")
    return descriptors, evaluated_at, source_watermark


def _weekly_component(
    connection: Any,  # noqa: ANN401
    leg: Any,  # noqa: ANN401
    run_at: datetime,
) -> dict[str, Any]:
    pricing_key = leg.pricing_key
    target = pricing_key.od_pair_id
    source_route_key = pricing_key.source_route_key
    if source_route_key.startswith("Northbound:"):
        direction: Literal["northbound", "southbound"] = "northbound"
    elif source_route_key.startswith("Southbound:"):
        direction = "southbound"
    else:
        raise ValueError("facility leg source route key has no supported direction")
    with connection.cursor("proxy_lookup") as cursor:
        cursor.execute(
            "SELECT proxy_od_pair_id, required_status FROM pricing.i95_modeled_od_proxy WHERE target_od_pair_id = %(target_od_pair_id)s",
            {"target_od_pair_id": target},
        )
        mappings = cursor.fetchmany(2)
    if len(mappings) > 1:
        raise ValueError("target OD has duplicate proxy mappings")
    mapping = mappings[0] if mappings else None
    proxy = mapping["proxy_od_pair_id"] if mapping else None
    status = mapping["required_status"] if mapping else None
    if mapping and (
        not isinstance(proxy, int) or not isinstance(status, str) or not status
    ):
        raise ValueError("target OD proxy mapping is malformed")
    source = proxy if mapping else target
    local_end = run_at.astimezone(_EASTERN).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start, end = local_end - timedelta(weeks=4), local_end
    params: dict[str, Any] = {
        "source_od_pair_id": source,
        "window_start_utc": start.astimezone(UTC),
        "window_end_utc": end.astimezone(UTC),
        "run_at_utc": run_at.astimezone(UTC),
    }
    sql = (
        "SELECT corridor_name, od_pair_id, start_zone_id, start_zone_name, "
        "end_zone_id, end_zone_name, interval_end_at, calculated_at, s3_key, "
        "zone_toll_rate_usd, link_status "
        "FROM pricing.trip_pricing_i95 WHERE od_pair_id = %(source_od_pair_id)s "
        "AND interval_end_at >= %(window_start_utc)s AND interval_end_at < %(window_end_utc)s "
        "AND calculated_at <= %(run_at_utc)s"
    )
    if mapping:
        sql += " AND link_status = %(required_status)s"
        params["required_status"] = status
    sql += " ORDER BY interval_end_at ASC, calculated_at ASC, s3_key ASC"
    raw: list[dict[str, Any]] = []
    with connection.cursor(f"raw_{leg.route_step_id}") as cursor:
        cursor.execute(sql, params)
        while batch := cursor.fetchmany(100):
            raw.extend(
                {**row, "series_id": source_route_key, "direction": direction}
                for row in batch
            )
    selected = _select_weekly_observations(
        raw, run_at, series_id=source_route_key, direction=direction
    )

    def public_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "corridor_name": row["corridor_name"],
            "od_pair_id": row["od_pair_id"],
            "start_zone": {"id": row["start_zone_id"], "name": row["start_zone_name"]},
            "end_zone": {"id": row["end_zone_id"], "name": row["end_zone_name"]},
            "interval_end_at": _utc_text(row["interval_end_at"]),
            "observed_at": _utc_text(row["calculated_at"]),
            "price_usd": f"{row['zone_toll_rate_usd']:.2f}",
            "link_status": row["link_status"],
        }

    def bin_document(
        hour_start: datetime, rows: tuple[dict[str, Any], ...]
    ) -> dict[str, Any]:
        minimum_price = min(row["zone_toll_rate_usd"] for row in rows)
        maximum_price = max(row["zone_toll_rate_usd"] for row in rows)
        return {
            "hour_start_at": cast(str, _utc_text(hour_start)),
            "source_count": len(rows),
            "minimum": public_row(
                max(
                    (row for row in rows if row["zone_toll_rate_usd"] == minimum_price),
                    key=_source_order,
                )
            ),
            "maximum": public_row(
                max(
                    (row for row in rows if row["zone_toll_rate_usd"] == maximum_price),
                    key=_source_order,
                )
            ),
            "last": public_row(max(rows, key=_source_order)),
        }

    return {
        "route_step_id": leg.route_step_id,
        "provenance": {
            "target_od_pair_id": target,
            "source_od_pair_id": source,
            "proxy_od_pair_id": proxy,
            "source_kind": "modeled" if mapping else "observed",
            "pricing_method": "identity_proxy_v1" if mapping else "source_observation",
            "direction": direction,
            **({"required_status": status} if mapping else {}),
        },
        "window": {
            "window_start_at": cast(str, _utc_text(start)),
            "window_end_at": cast(str, _utc_text(end)),
        },
        "coverage": selected.coverage.__dict__,
        "rush_observations": [public_row(row) for row in selected.rush_rows],
        "hourly_bins": [
            bin_document(hour_start, rows) for hour_start, rows in selected.hourly_bins
        ],
    }


def _put_object(
    s3_client: _S3Client,
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


def _incremental_prefix(point_slugs: dict[str, str]) -> bytes:
    # This is the exact sorted outer object prefix used by _result_fingerprint.
    return (
        json.dumps(
            {
                "point_slugs": point_slugs,
                "publication_format_version": PUBLICATION_FORMAT_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )[:-1]
        + ',"reports":['
    ).encode()


def _publish_streamed(
    report_cursor: Any,  # noqa: ANN401
    reader_connection: Any,  # noqa: ANN401
    s3_client: _S3Client,
    bucket: str,
    published_at: datetime,
    analytics_bucket: str,
    expected: datetime | None = None,
) -> tuple[dict[str, Any], datetime, datetime | None]:
    previous = _read_manifest(s3_client, bucket)
    descriptors, evaluated_at, source_watermark = _preflight_report(
        _cursor_rows(report_cursor)
    )
    if (
        previous
        and source_watermark is not None
        and isinstance(previous.get("source_watermark"), str)
        and source_watermark
        < _aware_timestamp(
            cast(str, previous["source_watermark"]), label="manifest source watermark"
        )
    ):
        return {"status": "superseded"}, evaluated_at, source_watermark
    if (
        expected is not None
        and _expected_watermark_action(expected, source_watermark) == "superseded"
    ):
        logger.info(
            "V2_REPORT_GENERATION_SUPERSEDED %s %s %s",
            FACILITY,
            _utc_text(expected),
            _utc_text(source_watermark),
        )
        return {"status": "superseded"}, evaluated_at, source_watermark
    existing_slugs = cast(dict[str, str], previous["point_slugs"]) if previous else None
    point_slugs = _build_slug_map(
        [
            endpoint
            for item in descriptors
            for endpoint in (item.origin, item.destination)
        ],
        existing_slugs,
    )
    route_keys = [
        f"{PUBLIC_PREFIX}/{point_slugs[item.key[0]]}/{point_slugs[item.key[1]]}"
        for item in descriptors
    ]
    run_at = _weekly_run_at(published_at)

    def build_pass(*, publish: bool) -> tuple[str, int]:
        digest = hashlib.sha256(_incremental_prefix(point_slugs))
        route_count = 0
        report_cursor.scroll(0, mode="absolute")
        for key, group in groupby(_cursor_rows(report_cursor), _route_identity):
            rows = list(group)
            if route_count >= len(descriptors) or key != descriptors[route_count].key:
                raise ValueError(
                    "report publish pass disagrees with preflight route order"
                )
            if any(
                _require_aware(
                    row["snapshot_evaluated_at"], label="snapshot evaluation"
                ).astimezone(UTC)
                != evaluated_at
                for row in rows
            ):
                raise ValueError(
                    "report publish pass disagrees with preflight evaluation"
                )
            if _source_watermark(rows) != descriptors[route_count].source_watermark:
                raise ValueError(
                    "report publish pass disagrees with preflight watermark"
                )
            route = _build_route(rows)
            legs = [
                route_validation._I95FacilityLeg.model_validate(value)  # pyright: ignore[reportPrivateUsage]
                for value in route.structural_facility_legs
            ]  # pyright: ignore[reportPrivateUsage]
            weekly = [_weekly_component(reader_connection, leg, run_at) for leg in legs]
            if [item["route_step_id"] for item in weekly] != [
                leg.route_step_id for leg in legs
            ]:
                raise ValueError("weekly component alignment is malformed")
            document = _build_stream_document(
                evaluated_at, source_watermark, route, published_at, weekly
            )
            if route_count:
                digest.update(b",")
            digest.update(
                json.dumps(
                    _without_runtime_fields(document),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            )
            if publish:
                route_key = route_keys[route_count]
                _put_object(
                    s3_client,
                    bucket,
                    f"{route_key}/report.json",
                    json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    "application/json; charset=utf-8",
                    PUBLIC_CACHE_CONTROL,
                )
                _put_object(
                    s3_client,
                    bucket,
                    f"{route_key}/index.html",
                    _render_report_html(document, f"{PUBLIC_BASE_URL}/{route_key}/"),
                    "text/html; charset=utf-8",
                    PUBLIC_CACHE_CONTROL,
                )
            route_count += 1
        if route_count != EXPECTED_ROUTE_COUNT:
            raise ValueError("report publish pass is missing routes")
        digest.update(b"]}")
        return digest.hexdigest(), route_count

    result_sha256, route_count = build_pass(publish=False)
    if (
        previous
        and previous["schema_version"] == "2.0.0"
        and previous["result_sha256"] == result_sha256
    ):
        _put_generation_marker(s3_client, analytics_bucket, previous, route_keys)
        return (
            {"status": "unchanged", "result_sha256": result_sha256},
            evaluated_at,
            source_watermark,
        )
    published_sha256, route_count = build_pass(publish=True)
    if published_sha256 != result_sha256:
        raise ValueError("report publish pass disagrees with digest pass")
    index_descriptors = [
        {
            "route": {
                "origin": item.origin.model_dump(mode="json"),
                "destination": item.destination.model_dump(mode="json"),
            }
        }
        for item in descriptors
    ]
    _put_object(
        s3_client,
        bucket,
        f"{PUBLIC_PREFIX}/index.html",
        _render_index_html(index_descriptors, point_slugs),
        "text/html; charset=utf-8",
        PUBLIC_CACHE_CONTROL,
    )
    _put_object(
        s3_client,
        bucket,
        "sitemap.xml",
        _render_sitemap(index_descriptors, point_slugs, published_at),
        "application/xml; charset=utf-8",
        PUBLIC_CACHE_CONTROL,
    )
    manifest = {
        "schema_version": "2.0.0",
        "publication_format_version": PUBLICATION_FORMAT_VERSION,
        "facility": FACILITY,
        "generation_id": _utc_text(evaluated_at),
        "published_at": _utc_text(published_at),
        "source_watermark": _utc_text(source_watermark),
        "result_sha256": result_sha256,
        "route_count": route_count,
        "point_slugs": point_slugs,
    }
    _put_object(
        s3_client,
        bucket,
        MANIFEST_KEY,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "application/json; charset=utf-8",
        MANIFEST_CACHE_CONTROL,
    )
    _put_generation_marker(s3_client, analytics_bucket, manifest, route_keys)
    return (
        {"status": "published", "result_sha256": result_sha256},
        evaluated_at,
        source_watermark,
    )


def _expected_watermark(event: dict[str, Any]) -> datetime | None:
    if event == {"trigger": "watchdog"}:
        return None
    if (
        event.get("source") != "tollchat.pricing-loader"
        or event.get("detail-type") != "I95 Pricing Load Committed"
        or not isinstance(event.get("detail"), dict)
    ):
        raise ValueError("unsupported publisher event")
    detail = _LoadDetail.model_validate(event["detail"])
    if detail.environment != os.environ.get("TOLLCHAT_ENVIRONMENT", "production"):
        raise ValueError("publisher event environment does not match runtime")
    return _aware_timestamp(detail.source_watermark, label="source watermark")


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    expected = _expected_watermark(event)
    enabled = os.getenv("REPORT_PUBLICATION_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise ValueError("REPORT_PUBLICATION_ENABLED must be true or false")
    if enabled == "true":
        invoked_at = datetime.now(UTC)
        report_connection = cast(Any, _connect())
        try:
            reader_connection = cast(Any, _connect(reader=True))
            try:
                with report_connection.transaction(), reader_connection.transaction():
                    with report_connection.cursor() as cursor:
                        cursor.execute(
                            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                        )
                        cursor.execute("SET LOCAL statement_timeout = '180s'")
                    with reader_connection.cursor() as cursor:
                        cursor.execute(
                            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                        )
                        cursor.execute("SET LOCAL statement_timeout = '180s'")
                    with report_connection.cursor(
                        "report_snapshot", scrollable=True
                    ) as report_cursor:
                        report_cursor.execute(REPORT_SQL)
                        publication, evaluated_at, source_watermark = _publish_streamed(
                            report_cursor,
                            reader_connection,
                            cast(_S3Client, boto3.client("s3")),  # pyright: ignore[reportUnknownMemberType]
                            os.environ["SITE_BUCKET_NAME"],
                            invoked_at,
                            os.environ["AGENT_MEASUREMENT_BUCKET"],
                            expected,
                        )
            finally:
                reader_connection.close()
        finally:
            report_connection.close()
        result: dict[str, Any] = {
            "status": publication["status"],
            "facility": FACILITY,
            "generation_id": _utc_text(evaluated_at),
            "source_watermark": _utc_text(source_watermark),
            "route_count": EXPECTED_ROUTE_COUNT,
            **publication,
        }
        if publication["status"] == "superseded":
            return result
        _log_success(cast(str, _utc_text(evaluated_at)), EXPECTED_ROUTE_COUNT)
        return result
    generation = build_generation(_read_report_rows())
    if expected is not None:
        action = _expected_watermark_action(expected, generation.source_watermark)
        if action == "superseded":
            logger.info(
                "V2_REPORT_GENERATION_SUPERSEDED %s %s %s",
                FACILITY,
                _utc_text(expected),
                _utc_text(generation.source_watermark),
            )
            return {
                "status": "superseded",
                "facility": FACILITY,
                "source_watermark": _utc_text(generation.source_watermark),
            }

    generation_id = cast(str, _utc_text(generation.generation_id))
    result: dict[str, Any] = {
        "status": "generated",
        "facility": FACILITY,
        "generation_id": generation_id,
        "source_watermark": _utc_text(generation.source_watermark),
        "route_count": len(generation.routes),
    }
    _log_success(generation_id, len(generation.routes))
    return result


def _log_success(generation_id: str, route_count: int) -> None:
    environment = os.environ.get("TOLLCHAT_ENVIRONMENT", "production")
    if environment == "production":
        logger.info(
            "V2_REPORT_GENERATION_OK %s %s %s",
            FACILITY,
            generation_id,
            route_count,
        )
    else:
        logger.info(
            "V2_REPORT_GENERATION_OK %s %s %s %s",
            FACILITY,
            generation_id,
            route_count,
            environment,
        )

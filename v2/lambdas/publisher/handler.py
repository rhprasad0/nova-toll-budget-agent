"""Build one validated I-95/I-495 report generation from a bounded snapshot."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

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


class _LoadDetail(_Model):
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


def _connect() -> object:
    import psycopg  # type: ignore[import-not-found]
    from psycopg.rows import dict_row  # type: ignore[import-not-found]

    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    user = os.environ["DB_USER"]
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
    return _aware_timestamp(detail.source_watermark, label="source watermark")


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    expected = _expected_watermark(event)
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
    logger.info(
        "V2_REPORT_GENERATION_OK %s %s %s",
        FACILITY,
        generation_id,
        len(generation.routes),
    )
    return {
        "status": "generated",
        "facility": FACILITY,
        "generation_id": generation_id,
        "source_watermark": _utc_text(generation.source_watermark),
        "route_count": len(generation.routes),
    }

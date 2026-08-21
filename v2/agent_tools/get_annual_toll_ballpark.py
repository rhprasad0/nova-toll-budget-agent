"""Agent-facing annual toll ballpark tool."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal, Self, cast
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    model_validator,
)
from strands import tool  # pyright: ignore[reportUnknownVariableType]
from strands.types.tools import ToolContext, ToolResult, ToolSpec

from agent_tools import get_current_toll_price as current_pricing
from agent_tools import validate_toll_route as route_validation

logger = logging.getLogger(__name__)
_SAFE_ERROR = "Unable to calculate the annual toll ballpark. Reference: {tool_use_id}."
_EASTERN = ZoneInfo("America/New_York")
_METHOD = "recent_complete_same_date_round_trips"
_ROUTE_SQL = "SELECT * FROM oracle.validate_ballpark_route(%s, %s)"
_SUMMARY_SQL = """SELECT * FROM oracle.get_annual_ballpark_summary(
    %s, %s, %s, %s, %s, %s, %s
)"""
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

type _Weekday = Literal[
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]
type _Connection = Any
type _ProgressStage = Literal[
    "route_validation", "historical_pricing", "ballpark_calculation"
]
type _ProgressStatus = Literal["running", "completed", "failed"]
type _ProgressMessage = Literal[
    "Validating outbound and return toll routes",
    "Toll routes validated",
    "Toll route validation failed",
    "Retrieving recent toll prices",
    "Recent toll pricing complete",
    "Recent toll pricing failed",
    "Calculating annual toll ballpark",
    "Annual toll ballpark complete",
    "Annual toll ballpark calculation failed",
]
_PROGRESS_MESSAGES: dict[tuple[_ProgressStage, _ProgressStatus], _ProgressMessage] = {
    ("route_validation", "running"): "Validating outbound and return toll routes",
    ("route_validation", "completed"): "Toll routes validated",
    ("route_validation", "failed"): "Toll route validation failed",
    ("historical_pricing", "running"): "Retrieving recent toll prices",
    ("historical_pricing", "completed"): "Recent toll pricing complete",
    ("historical_pricing", "failed"): "Recent toll pricing failed",
    ("ballpark_calculation", "running"): "Calculating annual toll ballpark",
    ("ballpark_calculation", "completed"): "Annual toll ballpark complete",
    ("ballpark_calculation", "failed"): "Annual toll ballpark calculation failed",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


def _round_usd(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _coverage_percent(complete: int, eligible: int) -> str:
    percent = (Decimal(complete) * 100 / Decimal(eligible)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return f"{percent:.1f}"


class _DirectionRequest(_Model):
    origin_point_id: str
    destination_point_id: str
    departure_time: Annotated[
        str, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$")
    ]

    def parsed_time(self) -> time:
        return time.fromisoformat(self.departure_time)


class _BallparkRequest(_Model):
    outbound: _DirectionRequest
    return_: _DirectionRequest = Field(alias="return")
    weekdays: Annotated[list[_Weekday], Field(min_length=1, max_length=7)]
    planned_annual_commute_days: Annotated[int, Field(ge=1, le=366)]

    @model_validator(mode="after")
    def _validate_request(self) -> Self:
        if len(self.weekdays) != len(set(self.weekdays)):
            raise ValueError("weekdays must be unique")
        if self.planned_annual_commute_days > 53 * len(self.weekdays):
            raise ValueError("planned annual commute days exceed requested weekdays")
        return self


class _ProgressEvent(_Model):
    stage: _ProgressStage
    status: _ProgressStatus
    message: _ProgressMessage

    @model_validator(mode="after")
    def _validate_message(self) -> Self:
        if self.message != _PROGRESS_MESSAGES[(self.stage, self.status)]:
            raise ValueError("progress message does not match stage and status")
        return self


class _ErrorContent(_Model):
    text: str


class _OperationError(_Model):
    toolUseId: str
    status: Literal["error"]
    content: Annotated[list[_ErrorContent], Field(min_length=1, max_length=1)]

    @model_validator(mode="after")
    def _validate_message(self) -> Self:
        if self.content[0].text != _SAFE_ERROR.format(tool_use_id=self.toolUseId):
            raise ValueError("operation error message does not match tool-use ID")
        return self


class _BallparkRouteDb(_Model):
    status: Literal[
        "valid",
        "invalid_origin",
        "invalid_destination",
        "no_supported_route",
        "traversal_limit_exceeded",
    ]
    reason: route_validation.Reason | None
    point_ids: list[str]
    connection_ids: list[str]
    connection_types: list[route_validation.ConnectionType]
    general_purpose_gaps: list[route_validation._Gap]  # pyright: ignore[reportPrivateUsage]
    facility_legs: list[route_validation._FacilityLeg]  # pyright: ignore[reportPrivateUsage]

    @model_validator(mode="after")
    def _validate_route(self) -> Self:
        if self.status == "valid":
            if self.reason is not None or not self.connection_ids:
                raise ValueError("valid ballpark route is incomplete")
            if len(self.point_ids) != len(self.connection_ids) + 1:
                raise ValueError("ballpark route path arrays are not aligned")
            if len(self.connection_types) != len(self.connection_ids):
                raise ValueError("ballpark route connections are not aligned")
            if any(
                gap.fallback_required is not None for gap in self.general_purpose_gaps
            ):
                raise ValueError("ballpark gaps cannot include live fallback decisions")
            route_validation.validate_facility_leg_alignment(
                self.point_ids,
                self.connection_ids,
                self.connection_types,
                self.facility_legs,
            )
        elif any(
            (
                self.point_ids,
                self.connection_ids,
                self.connection_types,
                self.general_purpose_gaps,
                self.facility_legs,
            )
        ):
            raise ValueError("unavailable ballpark routes must be pathless")
        return self


class _RouteStatus(_Model):
    origin_point_id: str
    destination_point_id: str
    status: str
    reason: route_validation.Reason | None


class _TargetWindow(_Model):
    start_date: date
    end_date: date
    date_count: Literal[84]


class _DateRange(_Model):
    start_date: date
    end_date: date


class _WeekdayCoverage(_Model):
    weekday: _Weekday
    eligible_date_count: Annotated[int, Field(ge=1)]
    complete_pair_count: Annotated[int, Field(ge=0)]
    coverage_percent: Annotated[str, Field(pattern=r"^(?:100[.]0|[0-9]{1,2}[.][0-9])$")]


class _Coverage(_Model):
    eligible_date_count: Annotated[int, Field(ge=1)]
    complete_pair_count: Annotated[int, Field(ge=0)]
    coverage_percent: Annotated[str, Field(pattern=r"^(?:100[.]0|[0-9]{1,2}[.][0-9])$")]
    by_weekday: Annotated[list[_WeekdayCoverage], Field(min_length=1, max_length=7)]


class _Scenario(_Model):
    daily_round_trip_usd: Annotated[Decimal, Field(ge=0)]
    annualized_usd: Annotated[Decimal, Field(ge=0)]


class _Scenarios(_Model):
    p25: _Scenario
    p50: _Scenario
    p90: _Scenario


class _FacilityBallpark(_Model):
    facility: Literal["i66", "i95_i495", "greenway", "dtr"]
    sample_count: Annotated[int, Field(ge=1, le=84)]
    uses_modeled: bool
    uses_current_fixed_rates: bool
    scenarios: _Scenarios


class _WeekdayCoverageDb(_Model):
    sample_isodow: Annotated[int, Field(ge=1, le=7)]
    eligible_date_count: Annotated[int, Field(ge=1, le=84)]
    complete_pair_count: Annotated[int, Field(ge=0, le=84)]
    coverage_percent: Annotated[str, Field(pattern=r"^(?:100[.]0|[0-9]{1,2}[.][0-9])$")]


class _ScenarioDb(_Model):
    daily_round_trip_usd: Annotated[
        str, Field(pattern=r"^(?:0|[1-9][0-9]*)[.][0-9]{2}$")
    ]
    annualized_usd: Annotated[str, Field(pattern=r"^(?:0|[1-9][0-9]*)[.][0-9]{2}$")]


class _ScenariosDb(_Model):
    p25: _ScenarioDb
    p50: _ScenarioDb
    p90: _ScenarioDb


class _FacilitySummaryDb(_Model):
    facility: Literal["i66", "i95_i495", "greenway", "dtr"]
    sample_count: Annotated[int, Field(ge=1, le=84)]
    uses_modeled: bool
    uses_current_fixed_rates: bool
    scenarios: _ScenariosDb


class _SummaryRow(_Model):
    eligible_date_count: Annotated[int, Field(ge=1, le=84)]
    complete_pair_count: Annotated[int, Field(ge=0, le=84)]
    coverage_percent: Annotated[str, Field(pattern=r"^(?:100[.]0|[0-9]{1,2}[.][0-9])$")]
    coverage_by_weekday: Annotated[
        list[_WeekdayCoverageDb], Field(min_length=1, max_length=7)
    ]
    available_start_date: date | None
    available_end_date: date | None
    sample_status: Literal["complete", "partial"]
    uses_modeled: bool
    uses_current_fixed_rates: bool
    facility_scenarios: Annotated[list[_FacilitySummaryDb], Field(max_length=4)]
    p25_daily_usd: Annotated[Decimal, Field(ge=0)] | None
    p50_daily_usd: Annotated[Decimal, Field(ge=0)] | None
    p90_daily_usd: Annotated[Decimal, Field(ge=0)] | None
    p25_annualized_usd: Annotated[Decimal, Field(ge=0)] | None
    p50_annualized_usd: Annotated[Decimal, Field(ge=0)] | None
    p90_annualized_usd: Annotated[Decimal, Field(ge=0)] | None

    @model_validator(mode="after")
    def _validate_summary(self, info: ValidationInfo) -> Self:
        context = info.context
        if not isinstance(context, dict):
            raise ValueError("annual ballpark summary validation context is missing")
        typed_context = cast(dict[str, Any], context)
        dates = cast(list[date], typed_context.get("dates"))
        annual_days = cast(int, typed_context.get("annual_days"))
        expected_facilities = cast(list[str], typed_context.get("facilities"))
        expected_weekdays = sorted({sample_date.isoweekday() for sample_date in dates})
        returned_weekdays = [item.sample_isodow for item in self.coverage_by_weekday]
        if (
            self.eligible_date_count != len(dates)
            or self.complete_pair_count > self.eligible_date_count
            or self.coverage_percent
            != _coverage_percent(self.complete_pair_count, self.eligible_date_count)
            or returned_weekdays != expected_weekdays
            or sum(item.eligible_date_count for item in self.coverage_by_weekday)
            != self.eligible_date_count
            or sum(item.complete_pair_count for item in self.coverage_by_weekday)
            != self.complete_pair_count
            or any(
                item.eligible_date_count
                != sum(day.isoweekday() == item.sample_isodow for day in dates)
                or item.complete_pair_count > item.eligible_date_count
                or item.coverage_percent
                != _coverage_percent(item.complete_pair_count, item.eligible_date_count)
                for item in self.coverage_by_weekday
            )
        ):
            raise ValueError("annual ballpark coverage is inconsistent")

        values = (
            self.p25_daily_usd,
            self.p50_daily_usd,
            self.p90_daily_usd,
            self.p25_annualized_usd,
            self.p50_annualized_usd,
            self.p90_annualized_usd,
        )
        if self.complete_pair_count == 0:
            if (
                self.sample_status != "partial"
                or self.available_start_date is not None
                or self.available_end_date is not None
                or any(value is not None for value in values)
                or self.facility_scenarios
                or self.uses_modeled
                or self.uses_current_fixed_rates
            ):
                raise ValueError("empty annual ballpark summary is inconsistent")
            return self

        if (
            self.sample_status
            != ("complete" if self.complete_pair_count == len(dates) else "partial")
            or self.available_start_date not in dates
            or self.available_end_date not in dates
            or cast(date, self.available_start_date)
            > cast(date, self.available_end_date)
            or any(value is None for value in values)
        ):
            raise ValueError("complete annual ballpark summary is inconsistent")
        daily = [
            cast(Decimal, self.p25_daily_usd),
            cast(Decimal, self.p50_daily_usd),
            cast(Decimal, self.p90_daily_usd),
        ]
        annualized = [
            cast(Decimal, self.p25_annualized_usd),
            cast(Decimal, self.p50_annualized_usd),
            cast(Decimal, self.p90_annualized_usd),
        ]
        if daily != sorted(daily) or annualized != [
            _round_usd(value * annual_days) for value in daily
        ]:
            raise ValueError("annual ballpark scenarios are inconsistent")
        returned_facilities = [item.facility for item in self.facility_scenarios]
        if (
            returned_facilities != expected_facilities
            or any(
                item.sample_count != self.complete_pair_count
                for item in self.facility_scenarios
            )
            or self.uses_modeled
            != any(item.uses_modeled for item in self.facility_scenarios)
            or self.uses_current_fixed_rates
            != any(item.uses_current_fixed_rates for item in self.facility_scenarios)
        ):
            raise ValueError("annual ballpark facility summary is inconsistent")
        for facility in self.facility_scenarios:
            facility_daily = [
                Decimal(facility.scenarios.p25.daily_round_trip_usd),
                Decimal(facility.scenarios.p50.daily_round_trip_usd),
                Decimal(facility.scenarios.p90.daily_round_trip_usd),
            ]
            facility_annualized = [
                Decimal(facility.scenarios.p25.annualized_usd),
                Decimal(facility.scenarios.p50.annualized_usd),
                Decimal(facility.scenarios.p90.annualized_usd),
            ]
            fixed = facility.facility in {"greenway", "dtr"}
            if (
                facility_daily != sorted(facility_daily)
                or facility_annualized
                != [_round_usd(value * annual_days) for value in facility_daily]
                or facility.uses_current_fixed_rates != fixed
                or (fixed and facility.uses_modeled)
            ):
                raise ValueError("annual ballpark facility scenarios are inconsistent")
        return self


class _BallparkResponseBase(_Model):
    method: Literal["recent_complete_same_date_round_trips"]
    evaluated_at: datetime
    timezone: Literal["America/New_York"]
    target_window: _TargetWindow
    weekdays: list[_Weekday]
    planned_annual_commute_days: int
    coverage: _Coverage
    uses_modeled: bool
    uses_current_fixed_rates: bool
    facilities: list[_FacilityBallpark]


class _BallparkSuccess(_BallparkResponseBase):
    sample_status: Literal["complete", "partial"]
    available_date_range: _DateRange
    scenarios: _Scenarios


class _NoCompleteResponse(_BallparkResponseBase):
    error: Literal["ballpark_unavailable"]
    reason: Literal["no_complete_paired_days"]
    available_date_range: None


class _SimpleUnavailableResponse(_Model):
    error: Literal["ballpark_unavailable"]
    reason: Literal["overnight_schedule"]


class _RouteUnavailableResponse(_Model):
    error: Literal["ballpark_unavailable"]
    reason: Literal["route_unavailable"]
    outbound: _RouteStatus
    return_: _RouteStatus = Field(alias="return")


type _BallparkOutput = (
    _BallparkSuccess
    | _NoCompleteResponse
    | _SimpleUnavailableResponse
    | _RouteUnavailableResponse
)
_OUTPUT_ADAPTER: TypeAdapter[_BallparkOutput] = TypeAdapter(_BallparkOutput)
_INPUT_SCHEMA: dict[str, Any] = _BallparkRequest.model_json_schema(mode="validation")
_OUTPUT_SCHEMA = _OUTPUT_ADAPTER.json_schema(mode="serialization")
_PROGRESS_SCHEMA = _ProgressEvent.model_json_schema(mode="serialization")
_OPERATION_ERROR_SCHEMA = _OperationError.model_json_schema(mode="serialization")
TOOL_SPEC: ToolSpec = {
    "name": "get_annual_toll_ballpark",
    "description": "Validate a round-trip toll commute and return compact annual toll scenarios.",
    "inputSchema": {"json": _INPUT_SCHEMA},
    "outputSchema": {"json": _OUTPUT_SCHEMA},
}


def _progress_event(stage: _ProgressStage, status: _ProgressStatus) -> dict[str, str]:
    return cast(
        dict[str, str],
        _ProgressEvent(
            stage=stage, status=status, message=_PROGRESS_MESSAGES[(stage, status)]
        ).model_dump(mode="json"),
    )


def _operation_error_result(tool_use_id: str) -> ToolResult:
    return cast(
        ToolResult,
        _OperationError(
            toolUseId=tool_use_id,
            status="error",
            content=[_ErrorContent(text=_SAFE_ERROR.format(tool_use_id=tool_use_id))],
        ).model_dump(mode="json"),
    )


def _log_failure_and_build_error_result(
    tool_use_id: str, stage: str, error: Exception
) -> ToolResult:
    safe_error = RuntimeError(f"{type(error).__name__} during {stage}")
    logger.error(
        "get_annual_toll_ballpark failed",
        extra={
            "toolUseId": tool_use_id,
            "failureStage": stage,
            "exceptionType": type(error).__name__,
        },
        exc_info=(type(safe_error), safe_error, error.__traceback__),
    )
    return _operation_error_result(tool_use_id)


def _start_transaction_and_fetch_routes_and_dates(
    connection: _Connection, request: _BallparkRequest
) -> tuple[datetime, tuple[_BallparkRouteDb, _BallparkRouteDb], list[date]]:
    with connection.cursor() as cursor:
        cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("SELECT transaction_timestamp() AS evaluated_at")
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise ValueError("database anchor must return exactly one row")
        evaluated_at = cast(datetime, rows[0]["evaluated_at"])
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("database anchor must be timezone-aware")
        routes: list[_BallparkRouteDb] = []
        for direction in (request.outbound, request.return_):
            cursor.execute(
                _ROUTE_SQL, (direction.origin_point_id, direction.destination_point_id)
            )
            rows = cursor.fetchall()
            if len(rows) != 1:
                raise ValueError("ballpark route oracle must return exactly one row")
            routes.append(_BallparkRouteDb.model_validate(rows[0]))
    end_date = evaluated_at.astimezone(_EASTERN).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=83)
    requested_weekdays = {_WEEKDAYS.index(day) for day in request.weekdays}
    dates = [
        start_date + timedelta(days=offset)
        for offset in range(84)
        if (start_date + timedelta(days=offset)).weekday() in requested_weekdays
    ]
    return evaluated_at.astimezone(_EASTERN), (routes[0], routes[1]), dates


def _resolve_unambiguous_eastern_datetime(
    sample_date: date, departure_time: time
) -> datetime | None:
    naive = datetime.combine(sample_date, departure_time)
    candidates = {
        candidate.astimezone(UTC)
        for fold in (0, 1)
        if (candidate := naive.replace(tzinfo=_EASTERN, fold=fold))
        .astimezone(UTC)
        .astimezone(_EASTERN)
        .replace(tzinfo=None)
        == naive
    }
    return next(iter(candidates)).astimezone(_EASTERN) if len(candidates) == 1 else None


def _build_route_status(
    request: _DirectionRequest, route: _BallparkRouteDb
) -> _RouteStatus:
    return _RouteStatus(
        origin_point_id=request.origin_point_id,
        destination_point_id=request.destination_point_id,
        status=route.status,
        reason=route.reason,
    )


def _build_summary_query_inputs(
    routes: tuple[_BallparkRouteDb, _BallparkRouteDb],
    request: _BallparkRequest,
    dates: list[date],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    legs: list[dict[str, Any]] = []
    fixed_prices: list[dict[str, str]] = []
    for direction_name, route, direction in (
        ("outbound", routes[0], request.outbound),
        ("return", routes[1], request.return_),
    ):
        resolved = {
            day: _resolve_unambiguous_eastern_datetime(day, direction.parsed_time())
            for day in dates
        }
        for leg in route.facility_legs:
            item: dict[str, Any] = {
                "direction": direction_name,
                "route_step_id": leg.route_step_id,
                "facility": leg.facility,
            }
            if leg.facility == "i66":
                item.update(
                    start_zone_id=leg.pricing_key.start_zone_id,
                    end_zone_id=leg.pricing_key.end_zone_id,
                )
            elif leg.facility == "i95_i495":
                item["od_pair_id"] = leg.pricing_key.od_pair_id
            elif leg.facility not in {"greenway", "dtr"}:
                raise ValueError("ballpark route contains an unsupported facility")
            legs.append(item)
            if leg.facility in {"greenway", "dtr"}:
                for sample_date, sample_at in resolved.items():
                    if sample_at is not None:
                        if leg.facility == "greenway":
                            component = current_pricing.price_greenway_leg(
                                leg, sample_at
                            )
                        elif leg.facility == "dtr":
                            component = current_pricing.price_dtr_leg(leg, sample_at)
                        else:  # narrowed by the enclosing fixed-facility check
                            raise AssertionError("unreachable facility")
                        fixed_prices.append(
                            {
                                "sample_date": sample_date.isoformat(),
                                "direction": direction_name,
                                "route_step_id": leg.route_step_id,
                                "price_usd": f"{component.price_usd:.2f}",
                            }
                        )
    return legs, fixed_prices


def _scenario_from_totals(daily: Decimal, annualized: Decimal) -> _Scenario:
    return _Scenario(daily_round_trip_usd=daily, annualized_usd=annualized)


def _parse_database_scenarios(value: _ScenariosDb) -> _Scenarios:
    return _Scenarios(
        p25=_Scenario(
            daily_round_trip_usd=Decimal(value.p25.daily_round_trip_usd),
            annualized_usd=Decimal(value.p25.annualized_usd),
        ),
        p50=_Scenario(
            daily_round_trip_usd=Decimal(value.p50.daily_round_trip_usd),
            annualized_usd=Decimal(value.p50.annualized_usd),
        ),
        p90=_Scenario(
            daily_round_trip_usd=Decimal(value.p90.daily_round_trip_usd),
            annualized_usd=Decimal(value.p90.annualized_usd),
        ),
    )


def _fetch_and_validate_summary(
    connection: _Connection,
    routes: tuple[_BallparkRouteDb, _BallparkRouteDb],
    request: _BallparkRequest,
    dates: list[date],
    evaluated_at: datetime,
) -> _SummaryRow:
    from psycopg.types.json import Jsonb

    legs, fixed_prices = _build_summary_query_inputs(routes, request, dates)
    with connection.cursor() as cursor:
        cursor.execute(
            _SUMMARY_SQL,
            (
                Jsonb(legs),
                request.outbound.parsed_time(),
                request.return_.parsed_time(),
                dates,
                Jsonb(fixed_prices),
                request.planned_annual_commute_days,
                evaluated_at,
            ),
        )
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError("annual ballpark summary must return exactly one row")
    expected_facilities = list(dict.fromkeys(item["facility"] for item in legs))
    return _SummaryRow.model_validate(
        rows[0],
        context={
            "dates": dates,
            "annual_days": request.planned_annual_commute_days,
            "facilities": expected_facilities,
        },
    )


def _build_ballpark_response(
    request: _BallparkRequest, evaluated_at: datetime, summary: _SummaryRow
) -> _BallparkSuccess | _NoCompleteResponse:
    target_end = evaluated_at.date() - timedelta(days=1)
    coverage = _Coverage(
        eligible_date_count=summary.eligible_date_count,
        complete_pair_count=summary.complete_pair_count,
        coverage_percent=summary.coverage_percent,
        by_weekday=[
            _WeekdayCoverage(
                weekday=_WEEKDAYS[item.sample_isodow - 1],
                eligible_date_count=item.eligible_date_count,
                complete_pair_count=item.complete_pair_count,
                coverage_percent=item.coverage_percent,
            )
            for item in summary.coverage_by_weekday
        ],
    )
    facilities = [
        _FacilityBallpark(
            facility=item.facility,
            sample_count=item.sample_count,
            uses_modeled=item.uses_modeled,
            uses_current_fixed_rates=item.uses_current_fixed_rates,
            scenarios=_parse_database_scenarios(item.scenarios),
        )
        for item in summary.facility_scenarios
    ]
    common: dict[str, Any] = {
        "method": _METHOD,
        "evaluated_at": evaluated_at,
        "timezone": "America/New_York",
        "target_window": _TargetWindow(
            start_date=target_end - timedelta(days=83),
            end_date=target_end,
            date_count=84,
        ),
        "weekdays": sorted(request.weekdays, key=_WEEKDAYS.index),
        "planned_annual_commute_days": request.planned_annual_commute_days,
        "coverage": coverage,
        "uses_modeled": summary.uses_modeled,
        "uses_current_fixed_rates": summary.uses_current_fixed_rates,
        "facilities": facilities,
    }
    if summary.complete_pair_count == 0:
        return _NoCompleteResponse(
            **common,
            error="ballpark_unavailable",
            reason="no_complete_paired_days",
            available_date_range=None,
        )
    values = (
        summary.available_start_date,
        summary.available_end_date,
        summary.p25_daily_usd,
        summary.p50_daily_usd,
        summary.p90_daily_usd,
        summary.p25_annualized_usd,
        summary.p50_annualized_usd,
        summary.p90_annualized_usd,
    )
    if any(value is None for value in values):
        raise ValueError("complete annual ballpark summary is incomplete")
    return _BallparkSuccess(
        **common,
        sample_status=summary.sample_status,
        available_date_range=_DateRange(
            start_date=cast(date, summary.available_start_date),
            end_date=cast(date, summary.available_end_date),
        ),
        scenarios=_Scenarios(
            p25=_scenario_from_totals(
                cast(Decimal, summary.p25_daily_usd),
                cast(Decimal, summary.p25_annualized_usd),
            ),
            p50=_scenario_from_totals(
                cast(Decimal, summary.p50_daily_usd),
                cast(Decimal, summary.p50_annualized_usd),
            ),
            p90=_scenario_from_totals(
                cast(Decimal, summary.p90_daily_usd),
                cast(Decimal, summary.p90_annualized_usd),
            ),
        ),
    )


def _build_success_result(tool_use_id: str, response: _BallparkOutput) -> ToolResult:
    return {
        "toolUseId": tool_use_id,
        "status": "success",
        "content": [
            {
                "json": response.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
            }
        ],
    }


def _close_connection(connection: _Connection, *, rollback: bool) -> None:
    error: Exception | None = None
    if rollback:
        try:
            connection.rollback()
        except Exception as rollback_error:
            error = rollback_error
    try:
        connection.close()
    except Exception as close_error:
        if error is None:
            error = close_error
        else:
            error.add_note(
                f"Connection close also failed: {type(close_error).__name__}"
            )
    if error is not None:
        raise error


@tool(
    name=TOOL_SPEC["name"],
    description=TOOL_SPEC["description"],
    inputSchema=TOOL_SPEC["inputSchema"],
    context="tool_context",
)
async def get_annual_toll_ballpark(
    tool_context: ToolContext,
) -> AsyncGenerator[dict[str, str] | ToolResult]:
    """Validate a round trip and return compact annual toll scenarios."""
    tool_use_id = "unknown"
    try:
        tool_data = cast(Any, tool_context.tool_use)
        if isinstance(tool_data.get("toolUseId"), str):
            tool_use_id = tool_data["toolUseId"]
        request = _BallparkRequest.model_validate(tool_data.get("input"))
    except Exception as error:
        yield _log_failure_and_build_error_result(
            tool_use_id, "input_validation", error
        )
        return
    if request.return_.parsed_time() <= request.outbound.parsed_time():
        yield _build_success_result(
            tool_use_id,
            _SimpleUnavailableResponse(
                error="ballpark_unavailable", reason="overnight_schedule"
            ),
        )
        return

    connection: _Connection | None = None
    try:
        yield _progress_event("route_validation", "running")
        try:
            connect = route_validation.connect_to_pricing_database
            connection = cast(_Connection, await asyncio.to_thread(connect))
            evaluated_at, routes, dates = await asyncio.to_thread(
                _start_transaction_and_fetch_routes_and_dates, connection, request
            )
        except Exception as error:
            yield _progress_event("route_validation", "failed")
            yield _log_failure_and_build_error_result(
                tool_use_id, "route_validation", error
            )
            return
        yield _progress_event("route_validation", "completed")
        if routes[0].status != "valid" or routes[1].status != "valid":
            yield _build_success_result(
                tool_use_id,
                _RouteUnavailableResponse.model_validate(
                    {
                        "error": "ballpark_unavailable",
                        "reason": "route_unavailable",
                        "outbound": _build_route_status(request.outbound, routes[0]),
                        "return": _build_route_status(request.return_, routes[1]),
                    }
                ),
            )
            return

        yield _progress_event("historical_pricing", "running")
        try:
            summary = await asyncio.to_thread(
                _fetch_and_validate_summary,
                connection,
                routes,
                request,
                dates,
                evaluated_at,
            )
            completed_connection = cast(_Connection, connection)
            await asyncio.to_thread(completed_connection.commit)
            await asyncio.to_thread(
                _close_connection, completed_connection, rollback=False
            )
            connection = None
        except Exception as error:
            yield _progress_event("historical_pricing", "failed")
            yield _log_failure_and_build_error_result(
                tool_use_id, "historical_pricing", error
            )
            return
        yield _progress_event("historical_pricing", "completed")

        yield _progress_event("ballpark_calculation", "running")
        try:
            result = _build_success_result(
                tool_use_id, _build_ballpark_response(request, evaluated_at, summary)
            )
        except Exception as error:
            yield _progress_event("ballpark_calculation", "failed")
            yield _log_failure_and_build_error_result(
                tool_use_id, "ballpark_calculation", error
            )
            return
        yield _progress_event("ballpark_calculation", "completed")
        yield result
    finally:
        if connection is not None:
            try:
                await asyncio.to_thread(_close_connection, connection, rollback=True)
            except Exception as error:
                safe_error = RuntimeError(
                    f"{type(error).__name__} during connection_cleanup"
                )
                logger.error(
                    "get_annual_toll_ballpark cleanup failed",
                    extra={
                        "toolUseId": tool_use_id,
                        "failureStage": "connection_cleanup",
                        "exceptionType": type(error).__name__,
                    },
                    exc_info=(type(safe_error), safe_error, error.__traceback__),
                )


get_annual_toll_ballpark.tool_spec = TOOL_SPEC
TOOL_CONTRACT = {
    "toolSpec": TOOL_SPEC,
    "progressEventSchema": _PROGRESS_SCHEMA,
    "progressMessages": {
        f"{stage}.{status}": message
        for (stage, status), message in _PROGRESS_MESSAGES.items()
    },
    "operationErrorSchema": _OPERATION_ERROR_SCHEMA,
    "operationErrorTemplate": _SAFE_ERROR,
}

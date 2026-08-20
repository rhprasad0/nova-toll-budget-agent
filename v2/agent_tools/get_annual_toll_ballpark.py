"""Agent-facing annual toll ballpark tool."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from typing import Annotated, Any, Literal, Self, cast
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from strands import tool  # pyright: ignore[reportUnknownVariableType]
from strands.types.tools import ToolContext, ToolResult, ToolSpec

from agent_tools import get_current_toll_price as current_pricing
from agent_tools import validate_toll_route as route_validation

logger = logging.getLogger(__name__)

_SAFE_ERROR = "Unable to calculate the annual toll ballpark. Reference: {tool_use_id}."
_EASTERN = ZoneInfo("America/New_York")
_METHOD = "recent_complete_same_date_round_trips"
_ROUTE_SQL = "SELECT * FROM oracle.validate_ballpark_route(%s, %s)"
_I66_SQL = "SELECT * FROM oracle.get_i66_ballpark_samples(%s, %s, %s, %s, %s)"
_I95_SQL = "SELECT * FROM oracle.get_i95_i495_ballpark_samples(%s, %s, %s, %s)"
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
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
type _Row = dict[str, Any]
type _Connection = Any
type _Cursor = Any
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


class _PricingProfile(_Model):
    vehicle_class: str
    payment_method: str
    transponder_mode: str


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
    pricing_profile: _PricingProfile

    @model_validator(mode="after")
    def _validate_request(self) -> Self:
        if len(self.weekdays) != len(set(self.weekdays)):
            raise ValueError("weekdays must be unique")
        if self.planned_annual_commute_days > min(366, 53 * len(self.weekdays)):
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
            if self.reason is not None:
                raise ValueError("valid ballpark routes cannot include a reason")
            if (
                not self.connection_ids
                or len(self.point_ids) != len(self.connection_ids) + 1
            ):
                raise ValueError("ballpark route path arrays are not aligned")
            if len(self.connection_types) != len(self.connection_ids):
                raise ValueError("ballpark route connections are not aligned")
            if any(
                gap.fallback_required is not None for gap in self.general_purpose_gaps
            ):
                raise ValueError("ballpark gaps cannot include live fallback decisions")
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
        if self.status == "valid":
            route_validation._validate_facility_leg_alignment(  # pyright: ignore[reportPrivateUsage]
                self.point_ids,
                self.connection_ids,
                self.connection_types,
                self.facility_legs,
            )
        return self


class _BallparkRoute(_BallparkRouteDb):
    origin_point_id: str
    destination_point_id: str
    departure_time: str


class _Routes(_Model):
    outbound: _BallparkRoute
    return_: _BallparkRoute = Field(alias="return")


class _I66SampleRow(_Model):
    sample_date: date
    sample_isodow: Annotated[int, Field(ge=1, le=7)]
    bin_start_at: datetime
    bin_end_at: datetime
    interval_end_at: datetime
    observed_at: datetime
    start_zone_id: int
    end_zone_id: int
    price_usd: Annotated[Decimal, Field(ge=0)]
    uses_modeled: Literal[False]
    pricing_method: Literal["source_observation"]

    @model_validator(mode="after")
    def _validate_sample(self) -> Self:
        _validate_sample_times(self, 6)
        return self


class _I95SampleRow(_Model):
    sample_date: date
    sample_isodow: Annotated[int, Field(ge=1, le=7)]
    bin_start_at: datetime
    bin_end_at: datetime
    interval_end_at: datetime
    observed_at: datetime
    od_pair_id: Annotated[int, Field(gt=0)]
    price_usd: Annotated[Decimal, Field(ge=0)]
    uses_modeled: bool
    pricing_method: Literal["source_observation", "identity_proxy_v1"]
    proxy_od_pair_id: Annotated[int, Field(gt=0)] | None

    @model_validator(mode="after")
    def _validate_sample(self) -> Self:
        _validate_sample_times(self, 10)
        if self.uses_modeled != (self.pricing_method == "identity_proxy_v1"):
            raise ValueError("I-95/I-495 sample provenance is inconsistent")
        if self.uses_modeled != (self.proxy_od_pair_id is not None):
            raise ValueError("I-95/I-495 proxy provenance is inconsistent")
        return self


def _validate_sample_times(row: _I66SampleRow | _I95SampleRow, minutes: int) -> None:
    timestamps = (
        row.bin_start_at,
        row.bin_end_at,
        row.interval_end_at,
        row.observed_at,
    )
    if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
        raise ValueError("ballpark sample timestamps must be aware")
    if (
        row.bin_end_at - row.bin_start_at != timedelta(minutes=minutes)
        or not row.bin_start_at <= row.interval_end_at < row.bin_end_at
        or row.interval_end_at.astimezone(_EASTERN).date() != row.sample_date
        or row.sample_date.isoweekday() != row.sample_isodow
    ):
        raise ValueError("ballpark sample time fields are inconsistent")


class _DynamicComponentBase(_Model):
    route_step_id: str
    price_usd: Decimal
    bin_start_at: datetime
    bin_end_at: datetime
    interval_end_at: datetime
    observed_at: datetime


class _I66Component(_DynamicComponentBase):
    facility: Literal["i66"]
    source_kind: Literal["observed"]
    pricing_method: Literal["source_observation"]
    start_zone_id: int
    end_zone_id: int


class _I95Component(_DynamicComponentBase):
    facility: Literal["i95_i495"]
    source_kind: Literal["observed", "modeled"]
    pricing_method: Literal["source_observation", "identity_proxy_v1"]
    od_pair_id: int
    proxy_od_pair_id: int | None


type _PriceComponent = Annotated[
    _I66Component
    | _I95Component
    | current_pricing._GreenwayComponent  # pyright: ignore[reportPrivateUsage]
    | current_pricing._DtrComponent,  # pyright: ignore[reportPrivateUsage]
    Field(discriminator="facility"),
]


class _DirectionPrice(_Model):
    total_usd: Decimal
    components: list[_PriceComponent]


class _CompleteDay(_Model):
    sample_date: date
    weekday: _Weekday
    uses_modeled: bool
    outbound: _DirectionPrice
    return_: _DirectionPrice = Field(alias="return")
    round_trip_total_usd: Decimal


class _ExcludedDate(_Model):
    sample_date: date
    weekday: _Weekday
    missing_outbound_route_step_ids: list[str]
    missing_return_route_step_ids: list[str]

    @model_validator(mode="after")
    def _validate_missing(self) -> Self:
        if (
            not self.missing_outbound_route_step_ids
            and not self.missing_return_route_step_ids
        ):
            raise ValueError("excluded dates require a missing route step")
        return self


class _TargetWindow(_Model):
    start_date: date
    end_date: date
    date_count: Literal[84]


class _DateRange(_Model):
    start_date: date
    end_date: date


class _WeekdayCoverage(_Model):
    weekday: _Weekday
    eligible_date_count: int
    complete_pair_count: int
    coverage_percent: str


class _Coverage(_Model):
    eligible_date_count: int
    complete_pair_count: int
    coverage_percent: str
    by_weekday: list[_WeekdayCoverage]


class _Scenario(_Model):
    percentile: Literal[25, 50, 90]
    rank: int
    sample_count: int
    daily_round_trip_usd: Decimal
    annualized_usd: Decimal


class _Scenarios(_Model):
    low: _Scenario
    middle: _Scenario
    high: _Scenario


class _BallparkResponseBase(_Model):
    method: Literal["recent_complete_same_date_round_trips"]
    evaluated_at: datetime
    timezone: Literal["America/New_York"]
    target_window: _TargetWindow
    weekdays: list[_Weekday]
    planned_annual_commute_days: int
    pricing_profile: _PricingProfile
    routes: _Routes
    coverage: _Coverage
    missing_weekdays: list[_Weekday]
    underrepresented_weekdays: list[_Weekday]
    uses_modeled: bool
    uses_current_fixed_rates: bool
    excluded_dates: list[_ExcludedDate]


class _BallparkSuccess(_BallparkResponseBase):
    sample_status: Literal["complete", "partial"]
    available_date_range: _DateRange
    scenarios: _Scenarios
    complete_days: Annotated[list[_CompleteDay], Field(min_length=1, max_length=84)]


class _NoCompleteResponse(_BallparkResponseBase):
    error: Literal["ballpark_unavailable"]
    reason: Literal["no_complete_paired_days"]
    available_date_range: None


class _SimpleUnavailableResponse(_Model):
    error: Literal["ballpark_unavailable"]
    reason: Literal["unsupported_pricing_profile", "overnight_schedule"]


class _RouteUnavailableResponse(_Model):
    error: Literal["ballpark_unavailable"]
    reason: Literal["route_unavailable"]
    routes: _Routes


type _BallparkOutput = (
    _BallparkSuccess
    | _NoCompleteResponse
    | _SimpleUnavailableResponse
    | _RouteUnavailableResponse
)
_OUTPUT_ADAPTER: TypeAdapter[_BallparkOutput] = TypeAdapter(_BallparkOutput)

_SUPPORTED_PROFILE = _PricingProfile(
    vehicle_class="two_axle_passenger",
    payment_method="e_zpass",
    transponder_mode="toll",
)
_INPUT_SCHEMA: dict[str, Any] = _BallparkRequest.model_json_schema(mode="validation")
_OUTPUT_SCHEMA = _OUTPUT_ADAPTER.json_schema(mode="serialization")
_PROGRESS_SCHEMA = _ProgressEvent.model_json_schema(mode="serialization")
_OPERATION_ERROR_SCHEMA = _OperationError.model_json_schema(mode="serialization")
TOOL_SPEC: ToolSpec = {
    "name": "get_annual_toll_ballpark",
    "description": "Validate a round-trip toll commute and calculate a recent annualized ballpark.",
    "inputSchema": {"json": _INPUT_SCHEMA},
    "outputSchema": {"json": _OUTPUT_SCHEMA},
}


def _progress(stage: _ProgressStage, status: _ProgressStatus) -> dict[str, str]:
    return cast(
        dict[str, str],
        _ProgressEvent(
            stage=stage,
            status=status,
            message=_PROGRESS_MESSAGES[(stage, status)],
        ).model_dump(mode="json"),
    )


def _operation_error(tool_use_id: str) -> ToolResult:
    result = _OperationError(
        toolUseId=tool_use_id,
        status="error",
        content=[_ErrorContent(text=_SAFE_ERROR.format(tool_use_id=tool_use_id))],
    )
    return cast(ToolResult, result.model_dump(mode="json"))


def _error(tool_use_id: str, stage: str, error: Exception) -> ToolResult:
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
    return _operation_error(tool_use_id)


def _begin_and_validate_routes(
    connection: _Connection, request: _BallparkRequest
) -> tuple[datetime, _Routes, list[date]]:
    with connection.cursor() as cursor:
        cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("SELECT transaction_timestamp() AS evaluated_at")
        anchor_rows = cursor.fetchall()
        if len(anchor_rows) != 1:
            raise ValueError("database anchor must return exactly one row")
        evaluated_at = cast(datetime, anchor_rows[0]["evaluated_at"])
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("database anchor must be timezone-aware")

        routes: list[_BallparkRoute] = []
        for direction in (request.outbound, request.return_):
            cursor.execute(
                _ROUTE_SQL,
                (direction.origin_point_id, direction.destination_point_id),
            )
            rows = cursor.fetchall()
            if len(rows) != 1:
                raise ValueError("ballpark route oracle must return exactly one row")
            route = _BallparkRouteDb.model_validate(rows[0])
            routes.append(
                _BallparkRoute.model_validate(
                    {
                        **route.model_dump(),
                        "origin_point_id": direction.origin_point_id,
                        "destination_point_id": direction.destination_point_id,
                        "departure_time": direction.departure_time,
                    }
                )
            )

    end_date = evaluated_at.astimezone(_EASTERN).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=83)
    requested_weekdays = {_WEEKDAYS.index(day) for day in request.weekdays}
    dates = [
        start_date + timedelta(days=offset)
        for offset in range(84)
        if (start_date + timedelta(days=offset)).weekday() in requested_weekdays
    ]
    return (
        evaluated_at.astimezone(_EASTERN),
        _Routes.model_validate({"outbound": routes[0], "return": routes[1]}),
        dates,
    )


def _resolve_wall_time(sample_date: date, departure_time: time) -> datetime | None:
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
    if len(candidates) != 1:
        return None
    return next(iter(candidates)).astimezone(_EASTERN)


def _component_from_i66(
    leg: route_validation._I66FacilityLeg,  # pyright: ignore[reportPrivateUsage]
    row: _I66SampleRow,
) -> _I66Component:
    return _I66Component(
        route_step_id=leg.route_step_id,
        facility="i66",
        price_usd=row.price_usd,
        source_kind="observed",
        pricing_method="source_observation",
        bin_start_at=row.bin_start_at.astimezone(_EASTERN),
        bin_end_at=row.bin_end_at.astimezone(_EASTERN),
        interval_end_at=row.interval_end_at.astimezone(_EASTERN),
        observed_at=row.observed_at.astimezone(_EASTERN),
        start_zone_id=row.start_zone_id,
        end_zone_id=row.end_zone_id,
    )


def _component_from_i95(
    leg: route_validation._I95FacilityLeg,  # pyright: ignore[reportPrivateUsage]
    row: _I95SampleRow,
) -> _I95Component:
    return _I95Component(
        route_step_id=leg.route_step_id,
        facility="i95_i495",
        price_usd=row.price_usd,
        source_kind="modeled" if row.uses_modeled else "observed",
        pricing_method=row.pricing_method,
        bin_start_at=row.bin_start_at.astimezone(_EASTERN),
        bin_end_at=row.bin_end_at.astimezone(_EASTERN),
        interval_end_at=row.interval_end_at.astimezone(_EASTERN),
        observed_at=row.observed_at.astimezone(_EASTERN),
        od_pair_id=row.od_pair_id,
        proxy_od_pair_id=row.proxy_od_pair_id,
    )


def _validate_sample_row_set(
    rows: list[_I66SampleRow] | list[_I95SampleRow],
    eligible_dates: list[date],
    departure_time: time,
    evaluated_at: datetime,
    label: str,
) -> None:
    row_dates = [row.sample_date for row in rows]
    if (
        len(rows) > len(eligible_dates)
        or len(row_dates) != len(set(row_dates))
        or any(
            row.sample_date not in eligible_dates
            or row.interval_end_at > evaluated_at
            or row.observed_at > evaluated_at
            or (sample_at := _resolve_wall_time(row.sample_date, departure_time))
            is None
            or not row.bin_start_at <= sample_at < row.bin_end_at
            for row in rows
        )
    ):
        raise ValueError(f"{label} ballpark function returned invalid rows")


def _price_direction(
    cursor: _Cursor,
    route: _BallparkRoute,
    departure_time: time,
    eligible_dates: list[date],
    evaluated_at: datetime,
) -> dict[date, dict[str, _PriceComponent]]:
    components: dict[date, dict[str, _PriceComponent]] = {
        sample_date: {} for sample_date in eligible_dates
    }
    if not route.facility_legs:
        return components
    resolved_times = {
        sample_date: _resolve_wall_time(sample_date, departure_time)
        for sample_date in eligible_dates
    }

    for leg in route.facility_legs:
        if leg.facility == "i66":
            cursor.execute(
                _I66_SQL,
                (
                    leg.pricing_key.start_zone_id,
                    leg.pricing_key.end_zone_id,
                    departure_time,
                    eligible_dates,
                    evaluated_at,
                ),
            )
            rows = [_I66SampleRow.model_validate(row) for row in cursor.fetchall()]
            _validate_sample_row_set(
                rows, eligible_dates, departure_time, evaluated_at, "I-66"
            )
            if any(
                row.start_zone_id != leg.pricing_key.start_zone_id
                or row.end_zone_id != leg.pricing_key.end_zone_id
                for row in rows
            ):
                raise ValueError("I-66 ballpark function returned invalid rows")
            for row in rows:
                components[row.sample_date][leg.route_step_id] = _component_from_i66(
                    leg, row
                )
        elif leg.facility == "i95_i495":
            cursor.execute(
                _I95_SQL,
                (
                    leg.pricing_key.od_pair_id,
                    departure_time,
                    eligible_dates,
                    evaluated_at,
                ),
            )
            rows = [_I95SampleRow.model_validate(row) for row in cursor.fetchall()]
            _validate_sample_row_set(
                rows, eligible_dates, departure_time, evaluated_at, "I-95/I-495"
            )
            if any(row.od_pair_id != leg.pricing_key.od_pair_id for row in rows):
                raise ValueError("I-95/I-495 ballpark function returned invalid rows")
            for row in rows:
                components[row.sample_date][leg.route_step_id] = _component_from_i95(
                    leg, row
                )
        elif leg.facility == "greenway":
            for sample_date, sample_at in resolved_times.items():
                if sample_at is not None:
                    priced = current_pricing._price_greenway(  # pyright: ignore[reportPrivateUsage]
                        leg, sample_at
                    ).model_copy(update={"component_evaluated_at": evaluated_at})
                    components[sample_date][leg.route_step_id] = priced
        elif leg.facility == "dtr":
            for sample_date, sample_at in resolved_times.items():
                if sample_at is not None:
                    priced = current_pricing._price_dtr(  # pyright: ignore[reportPrivateUsage]
                        leg, sample_at
                    ).model_copy(update={"component_evaluated_at": evaluated_at})
                    components[sample_date][leg.route_step_id] = priced
        else:
            raise ValueError("ballpark route contains an unsupported facility")
    return components


def _fetch_history(
    connection: _Connection,
    routes: _Routes,
    request: _BallparkRequest,
    eligible_dates: list[date],
    evaluated_at: datetime,
) -> tuple[
    dict[date, dict[str, _PriceComponent]],
    dict[date, dict[str, _PriceComponent]],
]:
    with connection.cursor() as cursor:
        outbound = _price_direction(
            cursor,
            routes.outbound,
            request.outbound.parsed_time(),
            eligible_dates,
            evaluated_at,
        )
        return_ = _price_direction(
            cursor,
            routes.return_,
            request.return_.parsed_time(),
            eligible_dates,
            evaluated_at,
        )
    connection.commit()
    return outbound, return_


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _coverage_percent(complete: int, eligible: int) -> str:
    value = (Decimal(complete) * 100 / Decimal(eligible)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return f"{value:.1f}"


def _scenario(
    percentile: Literal[25, 50, 90],
    totals: list[Decimal],
    annual_days: int,
) -> _Scenario:
    rank = ceil(percentile * len(totals) / 100)
    daily = _money(totals[rank - 1])
    return _Scenario(
        percentile=percentile,
        rank=rank,
        sample_count=len(totals),
        daily_round_trip_usd=daily,
        annualized_usd=_money(daily * annual_days),
    )


def _calculate(
    request: _BallparkRequest,
    evaluated_at: datetime,
    routes: _Routes,
    eligible_dates: list[date],
    outbound: dict[date, dict[str, _PriceComponent]],
    return_: dict[date, dict[str, _PriceComponent]],
) -> _BallparkSuccess | _NoCompleteResponse:
    outbound_steps = [leg.route_step_id for leg in routes.outbound.facility_legs]
    return_steps = [leg.route_step_id for leg in routes.return_.facility_legs]
    complete_days: list[_CompleteDay] = []
    excluded_dates: list[_ExcludedDate] = []

    for sample_date in eligible_dates:
        missing_outbound = [
            step for step in outbound_steps if step not in outbound[sample_date]
        ]
        missing_return = [
            step for step in return_steps if step not in return_[sample_date]
        ]
        weekday = _WEEKDAYS[sample_date.weekday()]
        if missing_outbound or missing_return:
            excluded_dates.append(
                _ExcludedDate(
                    sample_date=sample_date,
                    weekday=weekday,
                    missing_outbound_route_step_ids=missing_outbound,
                    missing_return_route_step_ids=missing_return,
                )
            )
            continue
        outbound_components = [outbound[sample_date][step] for step in outbound_steps]
        return_components = [return_[sample_date][step] for step in return_steps]
        outbound_total = _money(
            sum((component.price_usd for component in outbound_components), Decimal())
        )
        return_total = _money(
            sum((component.price_usd for component in return_components), Decimal())
        )
        uses_modeled = any(
            component.source_kind == "modeled"
            for component in outbound_components + return_components
        )
        complete_days.append(
            _CompleteDay.model_validate(
                {
                    "sample_date": sample_date,
                    "weekday": weekday,
                    "uses_modeled": uses_modeled,
                    "outbound": _DirectionPrice(
                        total_usd=outbound_total, components=outbound_components
                    ),
                    "return": _DirectionPrice(
                        total_usd=return_total, components=return_components
                    ),
                    "round_trip_total_usd": _money(outbound_total + return_total),
                }
            )
        )

    weekday_counts: dict[_Weekday, tuple[int, int]] = {}
    for weekday in sorted(request.weekdays, key=_WEEKDAYS.index):
        eligible = sum(
            _WEEKDAYS[sample_date.weekday()] == weekday
            for sample_date in eligible_dates
        )
        complete = sum(day.weekday == weekday for day in complete_days)
        weekday_counts[weekday] = (eligible, complete)
    complete_counts = [count[1] for count in weekday_counts.values()]
    maximum_count = max(complete_counts)
    missing_weekdays = [
        day for day, (_, complete) in weekday_counts.items() if complete == 0
    ]
    underrepresented = [
        day
        for day, (_, complete) in weekday_counts.items()
        if 0 < complete < maximum_count
    ]
    coverage = _Coverage(
        eligible_date_count=len(eligible_dates),
        complete_pair_count=len(complete_days),
        coverage_percent=_coverage_percent(len(complete_days), len(eligible_dates)),
        by_weekday=[
            _WeekdayCoverage(
                weekday=weekday,
                eligible_date_count=eligible,
                complete_pair_count=complete,
                coverage_percent=_coverage_percent(complete, eligible),
            )
            for weekday, (eligible, complete) in weekday_counts.items()
        ],
    )
    target_end = evaluated_at.astimezone(_EASTERN).date() - timedelta(days=1)
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
        "pricing_profile": request.pricing_profile,
        "routes": routes,
        "coverage": coverage,
        "missing_weekdays": missing_weekdays,
        "underrepresented_weekdays": underrepresented,
        "uses_modeled": any(day.uses_modeled for day in complete_days),
        "uses_current_fixed_rates": any(
            component.source_kind == "schedule_derived"
            for day in complete_days
            for component in day.outbound.components + day.return_.components
        ),
        "excluded_dates": excluded_dates,
    }
    if not complete_days:
        return _NoCompleteResponse(
            **common,
            error="ballpark_unavailable",
            reason="no_complete_paired_days",
            available_date_range=None,
        )
    totals = sorted(day.round_trip_total_usd for day in complete_days)
    return _BallparkSuccess(
        **common,
        available_date_range=_DateRange(
            start_date=complete_days[0].sample_date,
            end_date=complete_days[-1].sample_date,
        ),
        sample_status=(
            "complete" if len(complete_days) == len(eligible_dates) else "partial"
        ),
        scenarios=_Scenarios(
            low=_scenario(25, totals, request.planned_annual_commute_days),
            middle=_scenario(50, totals, request.planned_annual_commute_days),
            high=_scenario(90, totals, request.planned_annual_commute_days),
        ),
        complete_days=complete_days,
    )


def _tool_result(tool_use_id: str, response: _BallparkOutput) -> ToolResult:
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


def _close(connection: _Connection, *, rollback: bool) -> None:
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
    """Validate a round trip and calculate a recent annualized toll ballpark."""
    tool_use_id = "unknown"
    try:
        tool_data = cast(Any, tool_context.tool_use)
        if isinstance(tool_data.get("toolUseId"), str):
            tool_use_id = tool_data["toolUseId"]
        request = _BallparkRequest.model_validate(tool_data.get("input"))
    except Exception as error:
        yield _error(tool_use_id, "input_validation", error)
        return

    if request.pricing_profile != _SUPPORTED_PROFILE:
        yield _tool_result(
            tool_use_id,
            _SimpleUnavailableResponse(
                error="ballpark_unavailable", reason="unsupported_pricing_profile"
            ),
        )
        return
    if request.return_.parsed_time() <= request.outbound.parsed_time():
        yield _tool_result(
            tool_use_id,
            _SimpleUnavailableResponse(
                error="ballpark_unavailable", reason="overnight_schedule"
            ),
        )
        return

    connection: _Connection | None = None
    try:
        yield _progress("route_validation", "running")
        try:
            connection = cast(
                _Connection,
                await asyncio.to_thread(route_validation._connect),  # pyright: ignore[reportPrivateUsage]
            )
            evaluated_at, routes, eligible_dates = await asyncio.to_thread(
                _begin_and_validate_routes, connection, request
            )
        except Exception as error:
            yield _progress("route_validation", "failed")
            yield _error(tool_use_id, "route_validation", error)
            return
        yield _progress("route_validation", "completed")

        if routes.outbound.status != "valid" or routes.return_.status != "valid":
            try:
                result = _tool_result(
                    tool_use_id,
                    _RouteUnavailableResponse(
                        error="ballpark_unavailable",
                        reason="route_unavailable",
                        routes=routes,
                    ),
                )
                await asyncio.to_thread(_close, connection, rollback=True)
                connection = None
                yield result
            except Exception as error:
                yield _error(tool_use_id, "response_serialization", error)
            return

        yield _progress("historical_pricing", "running")
        try:
            outbound, return_ = await asyncio.to_thread(
                _fetch_history,
                connection,
                routes,
                request,
                eligible_dates,
                evaluated_at,
            )
            completed_connection = connection
            connection = None
            await asyncio.to_thread(_close, completed_connection, rollback=False)
        except Exception as error:
            yield _progress("historical_pricing", "failed")
            yield _error(tool_use_id, "historical_pricing", error)
            return
        yield _progress("historical_pricing", "completed")

        yield _progress("ballpark_calculation", "running")
        try:
            response = _calculate(
                request,
                evaluated_at,
                routes,
                eligible_dates,
                outbound,
                return_,
            )
            result = _tool_result(tool_use_id, response)
        except Exception as error:
            yield _progress("ballpark_calculation", "failed")
            yield _error(tool_use_id, "ballpark_calculation", error)
            return
        yield _progress("ballpark_calculation", "completed")
        yield result
    finally:
        if connection is not None:
            cleanup_connection = connection
            connection = None
            try:
                await asyncio.to_thread(_close, cleanup_connection, rollback=True)
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

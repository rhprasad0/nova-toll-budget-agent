"""Strands-free current toll pricing domain and orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import groupby, pairwise
from statistics import median
from typing import Annotated, Any, Literal, Protocol, Self, cast
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from agent_tools import validate_toll_route as route_validation

logger = logging.getLogger(__name__)

_SAFE_ERROR = "Unable to get the current toll price. Reference: {tool_use_id}."
_EASTERN = ZoneInfo("America/New_York")
_METHOD = "latest_complete_current_facility_prices"
_GREENWAY_SCHEDULE_ID = "dulles_greenway_toll_calculator_2026-08-04"
_GREENWAY_SOURCE_URL = "https://www.dullesgreenway.com/toll-calculator/"
_GREENWAY_RETRIEVED_AT = date(2026, 8, 4)
_GREENWAY_RATES = {
    ("secondary_plaza", "off_peak"): Decimal("4.55"),
    ("secondary_plaza", "peak"): Decimal("5.10"),
    ("mainline_plaza", "off_peak"): Decimal("5.25"),
    ("mainline_plaza", "peak"): Decimal("5.80"),
}
_DTR_SCHEDULE_ID = "dulles_toll_road_2023_rates"
_DTR_SOURCE_URL = (
    "https://www.dullestollroad.com/toll-rates-electronic-payment-and-pay-plate"
)
_DTR_RETRIEVED_AT = date(2026, 7, 26)
_DTR_RATES = {
    "ramp": Decimal("2.00"),
    "mainline_plaza": Decimal("4.00"),
}
_I66_SCHEDULE_ID = "vdot_i66_inside_beltway_2026-08-10"
_I66_SOURCE_URL = (
    "https://www.vdot.virginia.gov/projects/major-projects/66expresslanes/faqs/"
)
_I66_RETRIEVED_AT = date(2026, 8, 24)
_DTR_POINTS = ("28", "10", "11", "12", "13", "14", "15", "16", "17", "1819", "66")
_DTR_RAMP_POINTS = {"10", "11", "12", "13", "14", "17"}
_I66_SQL = "SELECT * FROM oracle.get_i66_pricing_comparisons(%s, %s, %s)"
_I95_SQL = "SELECT * FROM oracle.get_i95_i495_pricing_comparisons(%s)"

type _ProgressStage = Literal[
    "route_validation",
    "i95_i495_pricing",
    "i66_pricing",
    "greenway_pricing",
    "dtr_pricing",
]
type _ProgressStatus = Literal["running", "completed", "failed"]
type _ProgressMessage = Literal[
    "Validating toll route",
    "Toll route validated",
    "Toll route validation failed",
    "Pricing I-95/I-495 Express Lanes",
    "I-95/I-495 Express Lanes pricing complete",
    "I-95/I-495 Express Lanes pricing failed",
    "Pricing I-66 Express Lanes",
    "I-66 Express Lanes pricing complete",
    "I-66 Express Lanes pricing failed",
    "Pricing Dulles Greenway",
    "Dulles Greenway pricing complete",
    "Dulles Greenway pricing failed",
    "Pricing Dulles Toll Road",
    "Dulles Toll Road pricing complete",
    "Dulles Toll Road pricing failed",
]
_PROGRESS_MESSAGES: dict[tuple[_ProgressStage, _ProgressStatus], _ProgressMessage] = {
    ("route_validation", "running"): "Validating toll route",
    ("route_validation", "completed"): "Toll route validated",
    ("route_validation", "failed"): "Toll route validation failed",
    ("i95_i495_pricing", "running"): "Pricing I-95/I-495 Express Lanes",
    ("i95_i495_pricing", "completed"): "I-95/I-495 Express Lanes pricing complete",
    ("i95_i495_pricing", "failed"): "I-95/I-495 Express Lanes pricing failed",
    ("i66_pricing", "running"): "Pricing I-66 Express Lanes",
    ("i66_pricing", "completed"): "I-66 Express Lanes pricing complete",
    ("i66_pricing", "failed"): "I-66 Express Lanes pricing failed",
    ("greenway_pricing", "running"): "Pricing Dulles Greenway",
    ("greenway_pricing", "completed"): "Dulles Greenway pricing complete",
    ("greenway_pricing", "failed"): "Dulles Greenway pricing failed",
    ("dtr_pricing", "running"): "Pricing Dulles Toll Road",
    ("dtr_pricing", "completed"): "Dulles Toll Road pricing complete",
    ("dtr_pricing", "failed"): "Dulles Toll Road pricing failed",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _ToolContext(Protocol):
    @property
    def tool_use(self) -> Mapping[str, Any]: ...


type _Usd = Annotated[Decimal, Field(ge=0)]


class _PricingProfile(_Model):
    vehicle_class: str
    payment_method: str
    transponder_mode: str


class _PricingRequest(_Model):
    origin_point_id: str = Field(description="Stable oracle origin point ID")
    destination_point_id: str = Field(description="Stable oracle destination point ID")
    pricing_profile: _PricingProfile


class _PricingUnavailableResponse(_Model):
    origin_point_id: str
    destination_point_id: str
    error: Literal["pricing_unavailable"]
    reason: Literal["unsupported_pricing_profile"]


class _UnavailableComponent(_Model):
    route_step_id: str
    reason: Literal[
        "missing_observation",
        "stale_observation",
        "facility_unavailable",
        "exceptional_i95_schedule",
    ]
    component_evaluated_at: datetime
    interval_end_at: datetime | None
    observed_at: datetime | None
    source_status: str | None = None


class _IncompleteRoutePriceResponse(_Model):
    origin_point_id: str
    destination_point_id: str
    error: Literal["pricing_unavailable"]
    reason: Literal["incomplete_route_price"]
    unavailable_components: Annotated[list[_UnavailableComponent], Field(min_length=1)]


class _NonValidRouteResponse(
    route_validation._RouteResponse  # pyright: ignore[reportPrivateUsage]
):
    status: Literal[  # pyright: ignore[reportIncompatibleVariableOverride]
        "invalid_origin",
        "invalid_destination",
        "currently_unavailable",
        "unknown_availability",
        "no_supported_route",
        "traversal_limit_exceeded",
    ]


class _PricingRouteUnavailableResponse(
    route_validation._RouteResponse  # pyright: ignore[reportPrivateUsage]
):
    status: Literal[  # pyright: ignore[reportIncompatibleVariableOverride]
        "currently_unavailable", "unknown_availability"
    ]
    facility_legs: Annotated[
        list[route_validation._FacilityLeg],  # pyright: ignore[reportPrivateUsage]
        Field(max_length=0),
    ]


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


class _PublishedSchedule(_Model):
    schedule_id: Literal["dulles_greenway_toll_calculator_2026-08-04"]
    rate_name: Literal["secondary_plaza", "mainline_plaza"]
    source_url: Literal["https://www.dullesgreenway.com/toll-calculator/"]
    retrieved_at: date


class _GreenwayComponent(_Model):
    route_step_id: str
    price_usd: Decimal
    source_kind: Literal["schedule_derived"]
    pricing_method: Literal["published_schedule"]
    facility: Literal["greenway"]
    component_evaluated_at: datetime
    rate_period: Literal["peak", "off_peak"]
    published_schedule: _PublishedSchedule


class _DtrPublishedSchedule(_Model):
    schedule_id: Literal["dulles_toll_road_2023_rates"]
    rate_name: Literal["ramp", "mainline_plaza"]
    source_url: Literal[
        "https://www.dullestollroad.com/toll-rates-electronic-payment-and-pay-plate"
    ]
    retrieved_at: date


class _DtrComponent(_Model):
    route_step_id: str
    price_usd: Decimal
    source_kind: Literal["schedule_derived"]
    pricing_method: Literal["published_schedule"]
    facility: Literal["dtr"]
    component_evaluated_at: datetime
    published_schedule: _DtrPublishedSchedule


class _MovementSample(_Model):
    cycle_offset: Literal[-2, -1, 0]
    price_usd: _Usd


class _RecentMovement(_Model):
    method: Literal["same_facility_leg_three_cycles"]
    direction: Literal["rising", "falling", "unchanged", "mixed"]
    samples: Annotated[list[_MovementSample], Field(min_length=3, max_length=3)]
    net_change_usd: Decimal
    net_change_percent: Decimal | None


class _WeekSample(_Model):
    week_offset: Annotated[int, Field(ge=1, le=3)]
    price_usd: _Usd


class _PriorWeekComparison(_Model):
    method: Literal["same_weekday_same_facility_bins"]
    comparable_period_count: Annotated[int, Field(ge=1, le=3)]
    expected_comparable_period_count: Annotated[int, Field(ge=1, le=3)]
    comparable_prices: Annotated[list[_WeekSample], Field(min_length=1, max_length=3)]
    median_usd: Decimal
    minimum_usd: Decimal
    maximum_usd: Decimal
    current_delta_usd: Decimal
    current_delta_percent: Decimal | None
    position: Literal["below_recent_range", "within_recent_range", "above_recent_range"]
    higher_than_count: Annotated[int, Field(ge=0, le=3)]


class _I66ObservedComponent(_Model):
    route_step_id: str
    price_usd: _Usd
    source_kind: Literal["observed"]
    pricing_method: Literal["source_observation"]
    facility: Literal["i66"]
    component_evaluated_at: datetime
    bin_minutes: Literal[6]
    bin_start: datetime
    bin_end: datetime
    interval_end_at: datetime
    observed_at: datetime
    recent_movement: _RecentMovement | None = None
    prior_week_comparison: _PriorWeekComparison | None = None


class _I66PublishedSchedule(_Model):
    schedule_id: Literal["vdot_i66_inside_beltway_2026-08-10"]
    source_url: Literal[
        "https://www.vdot.virginia.gov/projects/major-projects/66expresslanes/faqs/"
    ]
    retrieved_at: date


class _I66ScheduleComponent(_Model):
    route_step_id: str
    price_usd: _Usd
    source_kind: Literal["schedule_derived"]
    pricing_method: Literal["published_schedule"]
    facility: Literal["i66"]
    component_evaluated_at: datetime
    rate_period: Literal["off_peak"]
    published_schedule: _I66PublishedSchedule


type _I66Component = Annotated[
    _I66ObservedComponent | _I66ScheduleComponent,
    Field(discriminator="source_kind"),
]


class _I95Component(_Model):
    route_step_id: str
    price_usd: _Usd
    source_kind: Literal["observed", "modeled"]
    pricing_method: Literal["source_observation", "identity_proxy_v1"]
    facility: Literal["i95_i495"]
    component_evaluated_at: datetime
    bin_minutes: Literal[10]
    bin_start: datetime
    bin_end: datetime
    interval_end_at: datetime
    observed_at: datetime
    od_pair_id: Annotated[int, Field(gt=0)]
    proxy_od_pair_id: Annotated[int, Field(gt=0)] | None = None
    source_status: Annotated[str, Field(min_length=1)]
    recent_movement: _RecentMovement | None = None
    prior_week_comparison: _PriorWeekComparison | None = None

    @model_validator(mode="after")
    def _validate_provenance(self) -> Self:
        if (
            self.source_kind == "observed"
            and (
                self.pricing_method != "source_observation"
                or self.proxy_od_pair_id is not None
            )
        ) or (
            self.source_kind == "modeled"
            and (
                self.pricing_method != "identity_proxy_v1"
                or self.proxy_od_pair_id is None
            )
        ):
            raise ValueError("I-95/I-495 pricing provenance is inconsistent")
        return self


def _validate_comparison_contract(
    row: _I66ComparisonRow | _I95ComparisonRow, *, label: str, bin_minutes: int
) -> None:
    expected_offsets = {
        "current": {0},
        "prior_cycle": {1, 2},
        "prior_week": {1, 2, 3},
    }
    if row.comparison_offset not in expected_offsets[row.comparison_kind]:
        raise ValueError(f"{label} comparison kind and offset do not match")
    timestamps = [
        row.evaluated_at,
        row.bin_start_at,
        row.bin_end_at,
        row.interval_end_at,
        row.observed_at,
    ]
    if any(
        value is not None and (value.tzinfo is None or value.utcoffset() is None)
        for value in timestamps
    ):
        raise ValueError(f"{label} comparison timestamps must be aware")
    values = (
        row.bin_start_at,
        row.bin_end_at,
        row.interval_end_at,
        row.observed_at,
        row.price_usd,
    )
    if row.available:
        if any(value is None for value in values) or row.availability_reason:
            raise ValueError(f"available {label} comparison is incomplete")
    elif row.comparison_kind != "current" or row.availability_reason is None:
        raise ValueError(f"only current {label} comparisons may be unavailable")
    elif row.availability_reason == "missing_observation" and any(
        value is not None for value in values
    ):
        raise ValueError(f"missing {label} observation contains source values")
    elif row.availability_reason == "stale_observation" and any(
        value is None for value in values
    ):
        raise ValueError(f"stale {label} observation is incomplete")
    elif row.availability_reason in {
        "facility_unavailable",
        "exceptional_i95_schedule",
    } and any(value is None for value in values[:-1]):
        raise ValueError(f"unavailable {label} observation is incomplete")
    if (row.interval_end_at is not None and row.interval_end_at > row.evaluated_at) or (
        row.observed_at is not None and row.observed_at > row.evaluated_at
    ):
        raise ValueError(f"{label} comparison contains future evidence")
    if row.bin_start_at is not None:
        bin_end = cast(datetime, row.bin_end_at)
        interval_end = cast(datetime, row.interval_end_at)
        if (
            bin_end - row.bin_start_at != timedelta(minutes=bin_minutes)
            or not row.bin_start_at <= interval_end < bin_end
        ):
            raise ValueError(f"{label} comparison bin is invalid")
    age = row.evaluated_at - row.observed_at if row.observed_at is not None else None
    if row.comparison_kind == "current" and (
        (row.available and (age is None or age > timedelta(minutes=30)))
        or (
            row.availability_reason == "stale_observation"
            and (age is None or age <= timedelta(minutes=30))
        )
    ):
        raise ValueError(f"{label} current freshness state is invalid")


class _I66ComparisonRow(_Model):
    evaluated_at: datetime
    comparison_kind: Literal["current", "prior_cycle", "prior_week"]
    comparison_offset: Annotated[int, Field(ge=0, le=3)]
    bin_start_at: datetime | None
    bin_end_at: datetime | None
    interval_end_at: datetime | None
    observed_at: datetime | None
    price_usd: _Usd | None
    available: bool
    availability_reason: Literal["missing_observation", "stale_observation"] | None
    source_kind: Literal["observed", "schedule_derived"] | None
    pricing_method: Literal["source_observation", "published_schedule"] | None

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        if self.source_kind == "schedule_derived":
            if (
                not self.available
                or self.availability_reason is not None
                or self.price_usd != 0
                or self.pricing_method != "published_schedule"
                or self.bin_start_at is None
                or self.bin_end_at is None
                or self.bin_end_at - self.bin_start_at != timedelta(minutes=6)
                or self.interval_end_at is not None
                or self.observed_at is not None
            ):
                raise ValueError("schedule-derived I-66 comparison is invalid")
            if any(
                value.tzinfo is None or value.utcoffset() is None
                for value in (
                    self.evaluated_at,
                    self.bin_start_at,
                    self.bin_end_at,
                )
            ):
                raise ValueError("I-66 comparison timestamps must be aware")
            expected_offsets = {
                "current": {0},
                "prior_cycle": {1, 2},
                "prior_week": {1, 2, 3},
            }
            if self.comparison_offset not in expected_offsets[self.comparison_kind]:
                raise ValueError("I-66 comparison kind and offset do not match")
            return self
        _validate_comparison_contract(self, label="I-66", bin_minutes=6)
        provenance = (self.source_kind, self.pricing_method)
        if self.availability_reason == "missing_observation":
            if any(value is not None for value in provenance):
                raise ValueError("missing I-66 observation contains provenance")
        elif provenance != ("observed", "source_observation"):
            raise ValueError("I-66 observation provenance is inconsistent")
        return self


class _I95ComparisonRow(_Model):
    evaluated_at: datetime
    comparison_kind: Literal["current", "prior_cycle", "prior_week"]
    comparison_offset: Annotated[int, Field(ge=0, le=3)]
    bin_start_at: datetime | None
    bin_end_at: datetime | None
    interval_end_at: datetime | None
    observed_at: datetime | None
    price_usd: _Usd | None
    available: bool
    availability_reason: (
        Literal[
            "missing_observation",
            "stale_observation",
            "facility_unavailable",
            "exceptional_i95_schedule",
        ]
        | None
    )
    source_kind: Literal["observed", "modeled"] | None
    pricing_method: Literal["source_observation", "identity_proxy_v1"] | None
    od_pair_id: Annotated[int, Field(gt=0)] | None
    proxy_od_pair_id: Annotated[int, Field(gt=0)] | None
    source_status: Annotated[str, Field(min_length=1)] | None

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        _validate_comparison_contract(self, label="I-95/I-495", bin_minutes=10)
        provenance = (
            self.source_kind,
            self.pricing_method,
            self.od_pair_id,
            self.source_status,
        )
        if self.availability_reason == "missing_observation":
            if (
                any(value is not None for value in provenance)
                or self.proxy_od_pair_id is not None
            ):
                raise ValueError("missing I-95/I-495 observation contains provenance")
        elif any(value is None for value in provenance):
            raise ValueError("I-95/I-495 observation provenance is incomplete")
        elif (
            self.source_kind == "observed"
            and (
                self.pricing_method != "source_observation"
                or self.proxy_od_pair_id is not None
            )
        ) or (
            self.source_kind == "modeled"
            and (
                self.pricing_method != "identity_proxy_v1"
                or self.proxy_od_pair_id is None
            )
        ):
            raise ValueError("I-95/I-495 observation provenance is inconsistent")
        return self


type _PriceComponent = Annotated[
    _I95Component | _I66Component | _GreenwayComponent | _DtrComponent,
    Field(discriminator="facility"),
]


class _CurrentPriceResponse(_Model):
    origin_point_id: str
    destination_point_id: str
    method: Literal["latest_complete_current_facility_prices"]
    evaluated_at: datetime
    maximum_observation_age_minutes: Literal[30]
    pricing_profile: _PricingProfile
    source_kind: Literal["observed", "modeled", "schedule_derived", "mixed", "none"]
    components: list[_PriceComponent]
    total_usd: Decimal


type _PricingOutput = (
    _CurrentPriceResponse
    | _PricingUnavailableResponse
    | _IncompleteRoutePriceResponse
    | _NonValidRouteResponse
    | _PricingRouteUnavailableResponse
)
_OUTPUT_ADAPTER: TypeAdapter[_PricingOutput] = TypeAdapter(_PricingOutput)


_SUPPORTED_PROFILE = _PricingProfile(
    vehicle_class="two_axle_passenger",
    payment_method="e_zpass",
    transponder_mode="toll",
)

_INPUT_SCHEMA: dict[str, Any] = _PricingRequest.model_json_schema(mode="validation")
_OUTPUT_SCHEMA = _OUTPUT_ADAPTER.json_schema(mode="serialization")
_PROGRESS_SCHEMA = _ProgressEvent.model_json_schema(mode="serialization")
_OPERATION_ERROR_SCHEMA = _OperationError.model_json_schema(mode="serialization")
TOOL_SPEC: dict[str, Any] = {
    "name": "get_current_toll_price",
    "description": "Validate a canonical toll route and get its current price.",
    "inputSchema": {"json": _INPUT_SCHEMA},
    "outputSchema": {"json": _OUTPUT_SCHEMA},
}


def _operation_error_result(tool_use_id: str) -> dict[str, Any]:
    error = _OperationError(
        toolUseId=tool_use_id,
        status="error",
        content=[_ErrorContent(text=_SAFE_ERROR.format(tool_use_id=tool_use_id))],
    )
    return error.model_dump(mode="json")


def _log_failure_and_build_error_result(
    tool_use_id: str, stage: str, error: Exception
) -> dict[str, Any]:
    safe_error = RuntimeError(f"{type(error).__name__} during {stage}")
    logger.error(
        "get_current_toll_price failed",
        extra={
            "toolUseId": tool_use_id,
            "failureStage": stage,
            "exceptionType": type(error).__name__,
        },
        exc_info=(type(safe_error), safe_error, error.__traceback__),
    )
    return _operation_error_result(tool_use_id)


def _progress_event(
    stage: _ProgressStage,
    status: _ProgressStatus,
) -> dict[str, str]:
    event = _ProgressEvent(
        stage=stage,
        status=status,
        message=_PROGRESS_MESSAGES[(stage, status)],
    )
    return cast(dict[str, str], event.model_dump(mode="json"))


def _current_eastern_time() -> datetime:
    return datetime.now(_EASTERN)


def _fetch_pricing_rows(
    sql: str, params: tuple[int | str, ...]
) -> list[dict[str, Any]]:
    connection = cast(Any, route_validation.connect_to_pricing_database())
    database_error: Exception | None = None
    rows: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cast(list[dict[str, Any]], cursor.fetchall())
    except Exception as error:
        database_error = error
    try:
        connection.close()
    except Exception as error:
        if database_error is None:
            database_error = error
        else:
            database_error.add_note(
                f"Connection close also failed: {type(error).__name__}"
            )
    if database_error is not None:
        raise database_error
    return rows


def _validate_comparison_rows(
    comparisons: list[_I66ComparisonRow] | list[_I95ComparisonRow], label: str
) -> None:
    identities = [
        (comparison.comparison_kind, comparison.comparison_offset)
        for comparison in comparisons
    ]
    if not 1 <= len(comparisons) <= 6 or len(identities) != len(set(identities)):
        raise ValueError(f"{label} pricing function returned an invalid row set")
    if sum(comparison.comparison_kind == "current" for comparison in comparisons) != 1:
        raise ValueError(
            f"{label} pricing function must return exactly one current row"
        )


def _fetch_i66_comparisons(
    start_zone_id: int, end_zone_id: int, direction: str
) -> list[_I66ComparisonRow]:
    """Fetch one bounded, diagnostic I-66 comparison set."""
    rows = _fetch_pricing_rows(_I66_SQL, (start_zone_id, end_zone_id, direction))

    comparisons = [_I66ComparisonRow.model_validate(row) for row in rows]
    _validate_comparison_rows(comparisons, "I-66")
    return comparisons


def _fetch_i95_i495_comparisons(od_pair_id: int) -> list[_I95ComparisonRow]:
    """Fetch one bounded, diagnostic I-95/I-495 comparison set."""
    rows = _fetch_pricing_rows(_I95_SQL, (od_pair_id,))
    comparisons = [_I95ComparisonRow.model_validate(row) for row in rows]
    _validate_comparison_rows(comparisons, "I-95/I-495")
    if any(row.od_pair_id not in {None, od_pair_id} for row in comparisons):
        raise ValueError("I-95/I-495 pricing function returned the wrong OD pair")
    provenance = {
        (
            row.source_kind,
            row.pricing_method,
            row.od_pair_id,
            row.proxy_od_pair_id,
        )
        for row in comparisons
        if row.od_pair_id is not None
    }
    if len(provenance) > 1:
        raise ValueError("I-95/I-495 pricing function mixed provenance")
    return comparisons


def _percent_change(change: Decimal, baseline: Decimal) -> Decimal | None:
    return (
        None
        if baseline == 0
        else (change * 100 / baseline).quantize(Decimal("0.1"), ROUND_HALF_UP)
    )


def _count_valid_prior_week_bins(bin_start: datetime) -> int:
    local = bin_start.astimezone(_EASTERN)
    local_wall_time = local.replace(tzinfo=None)
    return sum(
        (
            candidate := (local_wall_time - timedelta(days=7 * offset)).replace(
                tzinfo=_EASTERN
            )
        )
        .astimezone(UTC)
        .astimezone(_EASTERN)
        .replace(tzinfo=None)
        == candidate.replace(tzinfo=None)
        for offset in range(1, 4)
    )


def _build_price_comparisons(
    rows: list[_I66ComparisonRow] | list[_I95ComparisonRow],
    current_price: Decimal,
    current_bin_start: datetime,
) -> tuple[_RecentMovement | None, _PriorWeekComparison | None]:
    cycle_rows = sorted(
        (row for row in rows if row.comparison_kind == "prior_cycle"),
        key=lambda row: row.comparison_offset,
        reverse=True,
    )
    recent_movement = None
    if len(cycle_rows) == 2:
        cycle_prices = [cast(Decimal, row.price_usd) for row in cycle_rows] + [
            current_price
        ]
        changes = [later - earlier for earlier, later in pairwise(cycle_prices)]
        direction_name: Literal["rising", "falling", "unchanged", "mixed"] = (
            "rising"
            if all(change > 0 for change in changes)
            else "falling"
            if all(change < 0 for change in changes)
            else "unchanged"
            if all(change == 0 for change in changes)
            else "mixed"
        )
        net_change = current_price - cycle_prices[0]
        recent_movement = _RecentMovement(
            method="same_facility_leg_three_cycles",
            direction=direction_name,
            samples=[
                _MovementSample(cycle_offset=cast(Any, offset), price_usd=price)
                for offset, price in zip((-2, -1, 0), cycle_prices, strict=True)
            ],
            net_change_usd=net_change,
            net_change_percent=_percent_change(net_change, cycle_prices[0]),
        )

    week_rows = sorted(
        (row for row in rows if row.comparison_kind == "prior_week"),
        key=lambda row: row.comparison_offset,
        reverse=True,
    )
    prior_week_comparison = None
    if week_rows:
        week_prices = [cast(Decimal, row.price_usd) for row in week_rows]
        week_median = median(week_prices)
        current_delta = current_price - week_median
        minimum = min(week_prices)
        maximum = max(week_prices)
        position: Literal[
            "below_recent_range", "within_recent_range", "above_recent_range"
        ] = (
            "below_recent_range"
            if current_price < minimum
            else "above_recent_range"
            if current_price > maximum
            else "within_recent_range"
        )
        prior_week_comparison = _PriorWeekComparison(
            method="same_weekday_same_facility_bins",
            comparable_period_count=len(week_rows),
            expected_comparable_period_count=_count_valid_prior_week_bins(
                current_bin_start
            ),
            comparable_prices=[
                _WeekSample(
                    week_offset=row.comparison_offset,
                    price_usd=cast(Decimal, row.price_usd),
                )
                for row in week_rows
            ],
            median_usd=week_median,
            minimum_usd=minimum,
            maximum_usd=maximum,
            current_delta_usd=current_delta,
            current_delta_percent=_percent_change(current_delta, week_median),
            position=position,
            higher_than_count=sum(current_price > price for price in week_prices),
        )
    return recent_movement, prior_week_comparison


def _build_i66_component(
    leg: route_validation._I66FacilityLeg,  # pyright: ignore[reportPrivateUsage]
    rows: list[_I66ComparisonRow],
) -> _I66Component | _UnavailableComponent:
    """Build one I-66 component from normalized comparison rows."""
    route_key = leg.pricing_key.source_route_key
    parts = route_key.split(":")
    if len(parts) != 3 or parts[0] not in {"EB", "WB"} or not all(parts[1:]):
        raise ValueError("I-66 pricing key is malformed")
    direction, entry, exit_ = parts
    if leg.connection_ids != [f"source:i66:{route_key}"] or leg.point_ids != [
        f"i66:{entry}:entry:{direction}",
        f"i66:{exit_}:exit:{direction}",
    ]:
        raise ValueError("I-66 facility leg does not match its pricing key")

    current = next(row for row in rows if row.comparison_kind == "current")
    evaluated_at = current.evaluated_at.astimezone(_EASTERN)
    if current.source_kind == "schedule_derived":
        return _I66ScheduleComponent(
            route_step_id=leg.route_step_id,
            price_usd=Decimal(0),
            source_kind="schedule_derived",
            pricing_method="published_schedule",
            facility="i66",
            component_evaluated_at=evaluated_at,
            rate_period="off_peak",
            published_schedule=_I66PublishedSchedule(
                schedule_id=_I66_SCHEDULE_ID,
                source_url=_I66_SOURCE_URL,
                retrieved_at=_I66_RETRIEVED_AT,
            ),
        )
    if not current.available:
        return _UnavailableComponent(
            route_step_id=leg.route_step_id,
            reason=cast(
                Literal["missing_observation", "stale_observation"],
                current.availability_reason,
            ),
            component_evaluated_at=evaluated_at,
            interval_end_at=(
                current.interval_end_at.astimezone(_EASTERN)
                if current.interval_end_at
                else None
            ),
            observed_at=(
                current.observed_at.astimezone(_EASTERN)
                if current.observed_at
                else None
            ),
        )

    current_price = cast(Decimal, current.price_usd)
    current_bin_start = cast(datetime, current.bin_start_at)
    current_bin_end = cast(datetime, current.bin_end_at)
    current_interval_end = cast(datetime, current.interval_end_at)
    current_observed_at = cast(datetime, current.observed_at)
    recent_movement, prior_week_comparison = _build_price_comparisons(
        rows, current_price, current_bin_start
    )

    return _I66ObservedComponent(
        route_step_id=leg.route_step_id,
        price_usd=current_price,
        source_kind="observed",
        pricing_method="source_observation",
        facility="i66",
        component_evaluated_at=evaluated_at,
        bin_minutes=6,
        bin_start=current_bin_start.astimezone(_EASTERN),
        bin_end=current_bin_end.astimezone(_EASTERN),
        interval_end_at=current_interval_end.astimezone(_EASTERN),
        observed_at=current_observed_at.astimezone(_EASTERN),
        recent_movement=recent_movement,
        prior_week_comparison=prior_week_comparison,
    )


def _price_i66_leg(  # pyright: ignore[reportUnusedFunction]
    leg: route_validation._I66FacilityLeg,  # pyright: ignore[reportPrivateUsage]
) -> _I66Component | _UnavailableComponent:
    """Price one validated I-66 leg from observations or its published schedule."""
    rows = _fetch_i66_comparisons(
        leg.pricing_key.start_zone_id,
        leg.pricing_key.end_zone_id,
        leg.pricing_key.source_route_key.split(":", 1)[0],
    )
    return _build_i66_component(leg, rows)


def _build_i95_i495_component(
    leg: route_validation._I95FacilityLeg,  # pyright: ignore[reportPrivateUsage]
    rows: list[_I95ComparisonRow],
) -> _I95Component | _UnavailableComponent:
    """Build one I-95/I-495 component from normalized comparison rows."""
    route_key = leg.pricing_key.source_route_key
    parts = route_key.split(":")
    boundary = "i495:192NO" if parts[0] == "Northbound" else "i495:192SD"
    if (
        len(parts) != 3
        or parts[0] not in {"Northbound", "Southbound"}
        or not all(parts[1:])
        or leg.connection_ids != [f"source:i95_shared:{route_key}"]
        or not all(point.split(":", 1)[0] in {"i95", "i495"} for point in leg.point_ids)
        or not (
            (leg.point_ids[0].endswith(f":{parts[1]}") or leg.point_ids[0] == boundary)
            and (
                leg.point_ids[1].endswith(f":{parts[2]}")
                or leg.point_ids[1] == boundary
            )
            and leg.point_ids != [boundary, boundary]
        )
    ):
        raise ValueError("I-95/I-495 facility leg does not match its pricing key")
    if any(row.od_pair_id not in {None, leg.pricing_key.od_pair_id} for row in rows):
        raise ValueError("I-95/I-495 pricing rows contain the wrong OD pair")

    current = next(row for row in rows if row.comparison_kind == "current")
    evaluated_at = current.evaluated_at.astimezone(_EASTERN)
    if not current.available:
        return _UnavailableComponent(
            route_step_id=leg.route_step_id,
            reason=cast(
                Literal[
                    "missing_observation",
                    "stale_observation",
                    "facility_unavailable",
                    "exceptional_i95_schedule",
                ],
                current.availability_reason,
            ),
            component_evaluated_at=evaluated_at,
            interval_end_at=(
                current.interval_end_at.astimezone(_EASTERN)
                if current.interval_end_at
                else None
            ),
            observed_at=(
                current.observed_at.astimezone(_EASTERN)
                if current.observed_at
                else None
            ),
            source_status=current.source_status,
        )

    current_price = cast(Decimal, current.price_usd)
    current_bin_start = cast(datetime, current.bin_start_at)
    recent_movement, prior_week_comparison = _build_price_comparisons(
        rows, current_price, current_bin_start
    )
    return _I95Component(
        route_step_id=leg.route_step_id,
        price_usd=current_price,
        source_kind=cast(Literal["observed", "modeled"], current.source_kind),
        pricing_method=cast(
            Literal["source_observation", "identity_proxy_v1"],
            current.pricing_method,
        ),
        facility="i95_i495",
        component_evaluated_at=evaluated_at,
        bin_minutes=10,
        bin_start=current_bin_start.astimezone(_EASTERN),
        bin_end=cast(datetime, current.bin_end_at).astimezone(_EASTERN),
        interval_end_at=cast(datetime, current.interval_end_at).astimezone(_EASTERN),
        observed_at=cast(datetime, current.observed_at).astimezone(_EASTERN),
        od_pair_id=cast(int, current.od_pair_id),
        proxy_od_pair_id=current.proxy_od_pair_id,
        source_status=cast(str, current.source_status),
        recent_movement=recent_movement,
        prior_week_comparison=prior_week_comparison,
    )


def _price_i95_i495_leg(  # pyright: ignore[reportUnusedFunction]
    leg: route_validation._I95FacilityLeg,  # pyright: ignore[reportPrivateUsage]
) -> _I95Component | _UnavailableComponent:
    """Price one validated I-95/I-495 facility leg from current observations."""
    return _build_i95_i495_component(
        leg, _fetch_i95_i495_comparisons(leg.pricing_key.od_pair_id)
    )


def price_greenway_leg(
    leg: route_validation._GreenwayFacilityLeg,  # pyright: ignore[reportPrivateUsage]
    evaluated_at: datetime,
) -> _GreenwayComponent:
    """Price one validated Greenway facility leg from the published schedule."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("Greenway pricing requires an aware evaluation time")

    route_key = leg.pricing_key.source_route_key
    parts = route_key.split(":")
    if len(parts) != 3 or parts[0] not in {"EB", "WB"} or not all(parts[1:]):
        raise ValueError("Greenway pricing key is malformed")
    direction, entry, exit_ = parts
    expected_points = [
        f"greenway:{entry}:entry:{direction}",
        f"greenway:{exit_}:exit:{direction}",
    ]
    if (
        leg.pricing_key.charge_index != 1
        or leg.connection_ids != [f"source:greenway:{route_key}"]
        or leg.point_ids != expected_points
    ):
        raise ValueError("Greenway facility leg does not match its pricing key")

    local_time = evaluated_at.astimezone(_EASTERN)
    wall_time = local_time.time().replace(tzinfo=None)
    peak = local_time.weekday() < 5 and (
        (direction == "EB" and time(6, 30) <= wall_time < time(9))
        or (direction == "WB" and time(16) <= wall_time < time(18, 30))
    )
    rate_name: Literal["secondary_plaza", "mainline_plaza"] = (
        "mainline_plaza" if "28" in {entry, exit_} else "secondary_plaza"
    )
    rate_period: Literal["peak", "off_peak"] = "peak" if peak else "off_peak"

    return _GreenwayComponent(
        route_step_id=leg.route_step_id,
        price_usd=_GREENWAY_RATES[(rate_name, rate_period)],
        source_kind="schedule_derived",
        pricing_method="published_schedule",
        facility="greenway",
        component_evaluated_at=local_time,
        rate_period=rate_period,
        published_schedule=_PublishedSchedule(
            schedule_id=_GREENWAY_SCHEDULE_ID,
            rate_name=rate_name,
            source_url=_GREENWAY_SOURCE_URL,
            retrieved_at=_GREENWAY_RETRIEVED_AT,
        ),
    )


def price_dtr_leg(
    leg: route_validation._DtrFacilityLeg,  # pyright: ignore[reportPrivateUsage]
    evaluated_at: datetime,
) -> _DtrComponent:
    """Price one validated DTR charge from the published schedule."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("DTR pricing requires an aware evaluation time")

    route_key = leg.pricing_key.source_route_key
    if route_key in {"greenway_to_dtr", "dtr_to_greenway"}:
        expected_points = {
            "greenway_to_dtr": [
                "greenway:28:exit:EB",
                "dtr:28:entry:EB",
            ],
            "dtr_to_greenway": [
                "dtr:28:exit:WB",
                "greenway:28:entry:WB",
            ],
        }[route_key]
        if (
            leg.pricing_key.charge_index != 1
            or leg.connection_ids != [route_key]
            or leg.point_ids != expected_points
        ):
            raise ValueError("DTR handoff leg does not match its pricing key")
        rate_name: Literal["ramp", "mainline_plaza"] = "ramp"
    else:
        parts = route_key.split(":")
        if (
            len(parts) != 3
            or parts[0] not in {"EB", "WB"}
            or parts[1] not in _DTR_POINTS
            or parts[2] not in _DTR_POINTS
        ):
            raise ValueError("DTR pricing key is malformed")
        direction, entry, exit_ = parts
        entry_position = _DTR_POINTS.index(entry)
        exit_position = _DTR_POINTS.index(exit_)
        if (direction == "EB") != (entry_position < exit_position):
            raise ValueError("DTR pricing key direction is malformed")
        expected_points = [
            f"dtr:{entry}:entry:{direction}",
            f"dtr:{exit_}:exit:{direction}",
        ]
        if (
            leg.connection_ids != [f"source:dtr:{route_key}"]
            or leg.point_ids != expected_points
        ):
            raise ValueError("DTR facility leg does not match its pricing key")

        rate_names: list[Literal["ramp", "mainline_plaza"]] = []
        if entry in _DTR_RAMP_POINTS:
            rate_names.append("ramp")
        if (
            min(entry_position, exit_position)
            <= _DTR_POINTS.index("16")
            < max(entry_position, exit_position)
        ):
            rate_names.append("mainline_plaza")
        if exit_ in _DTR_RAMP_POINTS or (direction == "EB" and exit_ == "16"):
            rate_names.append("ramp")
        try:
            rate_name = rate_names[leg.pricing_key.charge_index - 1]
        except IndexError as error:
            raise ValueError("DTR charge index is malformed") from error

    local_time = evaluated_at.astimezone(_EASTERN)
    return _DtrComponent(
        route_step_id=leg.route_step_id,
        price_usd=_DTR_RATES[rate_name],
        source_kind="schedule_derived",
        pricing_method="published_schedule",
        facility="dtr",
        component_evaluated_at=local_time,
        published_schedule=_DtrPublishedSchedule(
            schedule_id=_DTR_SCHEDULE_ID,
            rate_name=rate_name,
            source_url=_DTR_SOURCE_URL,
            retrieved_at=_DTR_RETRIEVED_AT,
        ),
    )


def build_current_price_result(
    request: _PricingRequest,
    pricing_route: route_validation._PricingRouteResponse,  # pyright: ignore[reportPrivateUsage]
    evaluated_at: datetime | None,
    pricing_inputs: dict[str, object],
) -> dict[str, Any]:
    """Build the deterministic domain result from a validated route and pricing rows."""
    if pricing_route.status != "valid":
        if pricing_inputs:
            raise ValueError("nonvalid routes cannot contain pricing inputs")
        response = (
            _PricingRouteUnavailableResponse.model_validate(pricing_route.model_dump())
            if pricing_route.status in {"currently_unavailable", "unknown_availability"}
            else _NonValidRouteResponse.model_validate(
                pricing_route.model_dump(exclude={"facility_legs"})
            )
        )
        return response.model_dump(mode="json")
    if (
        evaluated_at is None
        or evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        raise ValueError("current price result requires an aware evaluation time")

    expected_inputs = {
        leg.route_step_id
        for leg in pricing_route.facility_legs
        if leg.facility in {"i95_i495", "i66"}
    }
    if pricing_inputs.keys() != expected_inputs:
        raise ValueError("pricing inputs do not match dynamic facility legs")

    components: list[_PriceComponent] = []
    unavailable_components: list[_UnavailableComponent] = []
    database_evaluated_at: datetime | None = None
    for leg in pricing_route.facility_legs:
        if leg.facility == "i95_i495":
            rows = pricing_inputs[leg.route_step_id]
            if not isinstance(rows, list):
                raise ValueError("I-95/I-495 pricing input is malformed")
            row_values = cast(list[object], rows)
            if not all(isinstance(row, _I95ComparisonRow) for row in row_values):
                raise ValueError("I-95/I-495 pricing input is malformed")
            priced = _build_i95_i495_component(
                leg,
                cast(list[_I95ComparisonRow], row_values),
            )
            if database_evaluated_at is None:
                database_evaluated_at = priced.component_evaluated_at
        elif leg.facility == "i66":
            rows = pricing_inputs[leg.route_step_id]
            if not isinstance(rows, list):
                raise ValueError("I-66 pricing input is malformed")
            row_values = cast(list[object], rows)
            if not all(isinstance(row, _I66ComparisonRow) for row in row_values):
                raise ValueError("I-66 pricing input is malformed")
            priced = _build_i66_component(
                leg,
                cast(list[_I66ComparisonRow], row_values),
            )
            if database_evaluated_at is None:
                database_evaluated_at = priced.component_evaluated_at
        elif leg.facility == "greenway":
            priced = price_greenway_leg(
                leg,
                evaluated_at,
            )
        else:
            priced = price_dtr_leg(
                leg,
                evaluated_at,
            )
        if isinstance(priced, _UnavailableComponent):
            unavailable_components.append(priced)
        else:
            components.append(priced)

    if unavailable_components:
        return _IncompleteRoutePriceResponse(
            origin_point_id=request.origin_point_id,
            destination_point_id=request.destination_point_id,
            error="pricing_unavailable",
            reason="incomplete_route_price",
            unavailable_components=unavailable_components,
        ).model_dump(mode="json")

    source_kinds: set[Literal["observed", "modeled", "schedule_derived"]] = {
        component.source_kind for component in components
    }
    source_kind: Literal["observed", "modeled", "schedule_derived", "mixed", "none"] = (
        "none"
        if not source_kinds
        else next(iter(source_kinds))
        if len(source_kinds) == 1
        else "mixed"
    )
    response = _CurrentPriceResponse(
        origin_point_id=request.origin_point_id,
        destination_point_id=request.destination_point_id,
        method=_METHOD,
        evaluated_at=database_evaluated_at or evaluated_at,
        maximum_observation_age_minutes=30,
        pricing_profile=request.pricing_profile,
        source_kind=source_kind,
        components=components,
        total_usd=sum(
            (component.price_usd for component in components), Decimal()
        ).quantize(Decimal("0.01")),
    )
    return response.model_dump(mode="json", exclude_none=True)


async def get_current_toll_price(
    tool_context: _ToolContext,
) -> AsyncGenerator[dict[str, Any]]:
    """Validate a route, stream its progress, and return its current toll price."""
    tool_use = tool_context.tool_use
    tool_use_id = "unknown"
    try:
        tool_data = tool_use
        candidate_id = tool_data.get("toolUseId")
        if isinstance(candidate_id, str):
            tool_use_id = candidate_id
        request = _PricingRequest.model_validate(tool_data.get("input"))
    except Exception as error:
        yield _log_failure_and_build_error_result(
            tool_use_id, "input_validation", error
        )
        return

    if request.pricing_profile != _SUPPORTED_PROFILE:
        response = _PricingUnavailableResponse(
            origin_point_id=request.origin_point_id,
            destination_point_id=request.destination_point_id,
            error="pricing_unavailable",
            reason="unsupported_pricing_profile",
        )
        yield {
            "toolUseId": tool_use_id,
            "status": "success",
            "content": [{"json": response.model_dump(mode="json")}],
        }
        return

    yield _progress_event("route_validation", "running")
    try:
        pricing_route = await asyncio.to_thread(
            route_validation.fetch_validated_pricing_route,
            request.origin_point_id,
            request.destination_point_id,
        )
    except Exception as error:
        yield _progress_event("route_validation", "failed")
        yield _log_failure_and_build_error_result(
            tool_use_id, "pricing_route_validation", error
        )
        return

    yield _progress_event("route_validation", "completed")

    if pricing_route.status != "valid":
        try:
            response = build_current_price_result(request, pricing_route, None, {})
            yield {
                "toolUseId": tool_use_id,
                "status": "success",
                "content": [{"json": response}],
            }
        except Exception as error:
            yield _log_failure_and_build_error_result(
                tool_use_id, "response_serialization", error
            )
        return

    evaluated_at = _current_eastern_time()

    if not pricing_route.facility_legs:
        try:
            response = build_current_price_result(
                request, pricing_route, evaluated_at, {}
            )
            yield {
                "toolUseId": tool_use_id,
                "status": "success",
                "content": [{"json": response}],
            }
        except Exception as error:
            yield _log_failure_and_build_error_result(
                tool_use_id, "response_serialization", error
            )
        return

    if any(
        leg.facility not in {"i95_i495", "i66", "greenway", "dtr"}
        for leg in pricing_route.facility_legs
    ):
        yield _operation_error_result(tool_use_id)
        return

    pricing_inputs: dict[str, object] = {}
    for facility, legs in groupby(
        pricing_route.facility_legs, key=lambda leg: leg.facility
    ):
        stage: _ProgressStage = {
            "i95_i495": "i95_i495_pricing",
            "i66": "i66_pricing",
            "greenway": "greenway_pricing",
            "dtr": "dtr_pricing",
        }[facility]  # pyright: ignore[reportAssignmentType]
        yield _progress_event(stage, "running")
        try:
            facility_legs = list(legs)
            if facility == "i95_i495":
                for leg in facility_legs:
                    i95_leg = cast(
                        route_validation._I95FacilityLeg,  # pyright: ignore[reportPrivateUsage]
                        leg,
                    )
                    rows = await asyncio.to_thread(
                        _fetch_i95_i495_comparisons, i95_leg.pricing_key.od_pair_id
                    )
                    _build_i95_i495_component(i95_leg, rows)
                    pricing_inputs[leg.route_step_id] = rows
            elif facility == "i66":
                for leg in facility_legs:
                    i66_leg = cast(
                        route_validation._I66FacilityLeg,  # pyright: ignore[reportPrivateUsage]
                        leg,
                    )
                    rows = await asyncio.to_thread(
                        _fetch_i66_comparisons,
                        i66_leg.pricing_key.start_zone_id,
                        i66_leg.pricing_key.end_zone_id,
                        i66_leg.pricing_key.source_route_key.split(":", 1)[0],
                    )
                    _build_i66_component(i66_leg, rows)
                    pricing_inputs[leg.route_step_id] = rows
            elif facility == "greenway":
                for leg in facility_legs:
                    price_greenway_leg(
                        cast(
                            route_validation._GreenwayFacilityLeg,  # pyright: ignore[reportPrivateUsage]
                            leg,
                        ),
                        evaluated_at,
                    )
            else:
                for leg in facility_legs:
                    price_dtr_leg(
                        cast(
                            route_validation._DtrFacilityLeg,  # pyright: ignore[reportPrivateUsage]
                            leg,
                        ),
                        evaluated_at,
                    )
        except Exception as error:
            yield _progress_event(stage, "failed")
            yield _log_failure_and_build_error_result(tool_use_id, stage, error)
            return
        yield _progress_event(stage, "completed")

    try:
        response = build_current_price_result(
            request, pricing_route, evaluated_at, pricing_inputs
        )
    except Exception as error:
        yield _log_failure_and_build_error_result(
            tool_use_id, "response_serialization", error
        )
        return
    yield {
        "toolUseId": tool_use_id,
        "status": "success",
        "content": [{"json": response}],
    }


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

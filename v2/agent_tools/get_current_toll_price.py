"""Agent-facing current toll pricing tool."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, cast
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from strands import tool  # pyright: ignore[reportUnknownVariableType]
from strands.types.tools import ToolContext, ToolResult, ToolSpec, ToolUse

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

type _ProgressStage = Literal["route_validation", "greenway_pricing"]
type _ProgressStatus = Literal["running", "completed", "failed"]
type _ProgressMessage = Literal[
    "Validating toll route",
    "Toll route validated",
    "Toll route validation failed",
    "Pricing Dulles Greenway",
    "Dulles Greenway pricing complete",
    "Dulles Greenway pricing failed",
]
_PROGRESS_MESSAGES: dict[tuple[_ProgressStage, _ProgressStatus], _ProgressMessage] = {
    ("route_validation", "running"): "Validating toll route",
    ("route_validation", "completed"): "Toll route validated",
    ("route_validation", "failed"): "Toll route validation failed",
    ("greenway_pricing", "running"): "Pricing Dulles Greenway",
    ("greenway_pricing", "completed"): "Dulles Greenway pricing complete",
    ("greenway_pricing", "failed"): "Dulles Greenway pricing failed",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


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


class _CurrentPriceResponse(_Model):
    origin_point_id: str
    destination_point_id: str
    method: Literal["latest_complete_current_facility_prices"]
    evaluated_at: datetime
    maximum_observation_age_minutes: Literal[30]
    pricing_profile: _PricingProfile
    source_kind: Literal["schedule_derived", "none"]
    components: list[_GreenwayComponent]
    total_usd: Decimal


type _PricingOutput = (
    _CurrentPriceResponse
    | _PricingUnavailableResponse
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
TOOL_SPEC: ToolSpec = {
    "name": "get_current_toll_price",
    "description": "Validate a canonical toll route and get its current price.",
    "inputSchema": {"json": _INPUT_SCHEMA},
    "outputSchema": {"json": _OUTPUT_SCHEMA},
}


def _operation_error(tool_use_id: str) -> ToolResult:
    error = _OperationError(
        toolUseId=tool_use_id,
        status="error",
        content=[_ErrorContent(text=_SAFE_ERROR.format(tool_use_id=tool_use_id))],
    )
    return cast(ToolResult, error.model_dump(mode="json"))


def _error(tool_use_id: str, stage: str, error: Exception) -> ToolResult:
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
    return _operation_error(tool_use_id)


def _progress(
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


def _price_greenway(
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


def _success(
    request: _PricingRequest,
    evaluated_at: datetime,
    components: list[_GreenwayComponent],
) -> ToolResult:
    response = _CurrentPriceResponse(
        origin_point_id=request.origin_point_id,
        destination_point_id=request.destination_point_id,
        method=_METHOD,
        evaluated_at=evaluated_at,
        maximum_observation_age_minutes=30,
        pricing_profile=request.pricing_profile,
        source_kind="schedule_derived" if components else "none",
        components=components,
        total_usd=sum(
            (component.price_usd for component in components), Decimal()
        ).quantize(Decimal("0.01")),
    )
    return {
        "toolUseId": "unknown",
        "status": "success",
        "content": [{"json": response.model_dump(mode="json")}],
    }


@tool(
    name=TOOL_SPEC["name"],
    description=TOOL_SPEC["description"],
    inputSchema=TOOL_SPEC["inputSchema"],
    context="tool_context",
)
async def get_current_toll_price(
    tool_context: ToolContext,
) -> AsyncGenerator[dict[str, str] | ToolResult]:
    """Validate a route, stream its progress, and return its current toll price."""
    tool_use = tool_context.tool_use
    tool_use_id = "unknown"
    try:
        tool_data = cast(Any, tool_use)
        candidate_id = tool_data.get("toolUseId")
        if isinstance(candidate_id, str):
            tool_use_id = candidate_id
        request = _PricingRequest.model_validate(tool_data.get("input"))
    except Exception as error:
        yield _error(tool_use_id, "input_validation", error)
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

    yield _progress("route_validation", "running")
    try:
        route_result = await asyncio.to_thread(
            route_validation.validate_toll_route,
            cast(
                ToolUse,
                {
                    "toolUseId": tool_use_id,
                    "name": "validate_toll_route",
                    "input": {
                        "origin_point_id": request.origin_point_id,
                        "destination_point_id": request.destination_point_id,
                    },
                },
            ),
        )
        if route_result["status"] == "error":
            yield _progress("route_validation", "failed")
            yield _operation_error(tool_use_id)
            return
    except Exception as error:
        yield _progress("route_validation", "failed")
        yield _error(tool_use_id, "route_validation", error)
        return

    try:
        content = cast(Any, route_result["content"])
        route = route_validation._RouteResponse.model_validate(  # pyright: ignore[reportPrivateUsage]
            content[0]["json"]
        )
    except (ValidationError, ValueError, KeyError, IndexError, TypeError) as error:
        yield _progress("route_validation", "failed")
        yield _error(tool_use_id, "route_response_validation", error)
        return

    if route.status != "valid":
        yield _progress("route_validation", "completed")
        yield route_result
        return

    try:
        pricing_route = await asyncio.to_thread(
            route_validation._validate_pricing_route,  # pyright: ignore[reportPrivateUsage]
            route,
        )
    except Exception as error:
        yield _progress("route_validation", "failed")
        yield _error(tool_use_id, "pricing_route_validation", error)
        return

    yield _progress("route_validation", "completed")

    if pricing_route.status != "valid":
        try:
            yield {
                "toolUseId": tool_use_id,
                "status": "success",
                "content": [{"json": pricing_route.model_dump(mode="json")}],
            }
        except Exception as error:
            yield _error(tool_use_id, "response_serialization", error)
        return

    evaluated_at = _current_eastern_time()

    if not pricing_route.facility_legs:
        try:
            result = _success(request, evaluated_at, [])
            result["toolUseId"] = tool_use_id
            yield result
        except Exception as error:
            yield _error(tool_use_id, "response_serialization", error)
        return

    if any(leg.facility != "greenway" for leg in pricing_route.facility_legs):
        yield _operation_error(tool_use_id)
        return

    yield _progress("greenway_pricing", "running")
    try:
        components = [
            _price_greenway(
                cast(
                    route_validation._GreenwayFacilityLeg,  # pyright: ignore[reportPrivateUsage]
                    leg,
                ),
                evaluated_at,
            )
            for leg in pricing_route.facility_legs
        ]
        result = _success(request, evaluated_at, components)
        result["toolUseId"] = tool_use_id
    except Exception as error:
        yield _progress("greenway_pricing", "failed")
        yield _error(tool_use_id, "greenway_pricing", error)
        return

    yield _progress("greenway_pricing", "completed")
    yield result


get_current_toll_price.tool_spec = TOOL_SPEC
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

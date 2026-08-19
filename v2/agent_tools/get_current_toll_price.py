"""Agent-facing current toll pricing scaffold."""

import logging
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, ValidationError
from strands.types.tools import ToolResult, ToolSpec, ToolUse

from agent_tools import validate_toll_route as route_validation

logger = logging.getLogger(__name__)

_SAFE_ERROR = "Unable to get the current toll price. Reference: {tool_use_id}."


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _PricingProfile(_Model):
    vehicle_class: str
    payment_method: str
    transponder_mode: str


class _PricingRequest(_Model):
    origin_point_id: str
    destination_point_id: str
    pricing_profile: _PricingProfile


_SUPPORTED_PROFILE = _PricingProfile(
    vehicle_class="two_axle_passenger",
    payment_method="e_zpass",
    transponder_mode="toll",
)

TOOL_SPEC: ToolSpec = {
    "name": "get_current_toll_price",
    "description": "Validate a canonical toll route for current pricing.",
    "inputSchema": {"json": _PricingRequest.model_json_schema()},
}


def _operation_error(tool_use_id: str) -> ToolResult:
    return {
        "toolUseId": tool_use_id,
        "status": "error",
        "content": [{"text": _SAFE_ERROR.format(tool_use_id=tool_use_id)}],
    }


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


def get_current_toll_price(
    tool_use: ToolUse,
    **_: Any,  # noqa: ANN401
) -> ToolResult:
    """Validate a route and return its ordered pricing-bearing facility legs."""
    tool_use_id = "unknown"
    try:
        tool_data = cast(Any, tool_use)
        candidate_id = tool_data.get("toolUseId")
        if isinstance(candidate_id, str):
            tool_use_id = candidate_id
        request = _PricingRequest.model_validate(tool_data.get("input"))
    except Exception as error:
        return _error(tool_use_id, "input_validation", error)

    if request.pricing_profile != _SUPPORTED_PROFILE:
        return {
            "toolUseId": tool_use_id,
            "status": "success",
            "content": [
                {
                    "json": {
                        "origin_point_id": request.origin_point_id,
                        "destination_point_id": request.destination_point_id,
                        "error": "pricing_unavailable",
                        "reason": "unsupported_pricing_profile",
                    }
                }
            ],
        }

    try:
        route_result = route_validation.validate_toll_route(
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
            )
        )
        if route_result["status"] == "error":
            return _operation_error(tool_use_id)
    except Exception as error:
        return _error(tool_use_id, "route_validation", error)

    try:
        content = cast(Any, route_result["content"])
        route = route_validation._RouteResponse.model_validate(  # pyright: ignore[reportPrivateUsage]
            content[0]["json"]
        )
    except (ValidationError, ValueError, KeyError, IndexError, TypeError) as error:
        return _error(tool_use_id, "route_response_validation", error)

    if route.status != "valid":
        return route_result

    try:
        pricing_route = route_validation._validate_pricing_route(  # pyright: ignore[reportPrivateUsage]
            route
        )
    except Exception:
        return _operation_error(tool_use_id)

    try:
        return {
            "toolUseId": tool_use_id,
            "status": "success",
            "content": [{"json": pricing_route.model_dump(mode="json")}],
        }
    except Exception as error:
        return _error(tool_use_id, "response_serialization", error)

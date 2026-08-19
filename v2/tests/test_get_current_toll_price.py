# pyright: basic

import logging
from typing import Any, cast

import pytest
from strands.tools.loader import load_tools_from_module_path
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_current_toll_price as pricing_tool


def _input() -> dict[str, Any]:
    return {
        "origin_point_id": "i66:1:entry:EB",
        "destination_point_id": "i66:4:exit:EB",
        "pricing_profile": {
            "vehicle_class": "two_axle_passenger",
            "payment_method": "e_zpass",
            "transponder_mode": "toll",
        },
    }


def _tool_use(input_data: Any) -> ToolUse:
    return cast(
        ToolUse,
        {
            "name": "get_current_toll_price",
            "toolUseId": "tool-123",
            "input": input_data,
        },
    )


def _route_row(status: str = "valid") -> dict[str, Any]:
    if status == "valid":
        return {
            "status": "valid",
            "reason": None,
            "point_ids": ["i66:1:entry:EB", "i66:4:exit:EB"],
            "connection_ids": ["source:i66:EB:1:4"],
            "connection_types": ["within_facility"],
            "general_purpose_gaps": [],
            "i95_evidence": None,
        }
    return {
        "status": "invalid_origin",
        "reason": {
            "code": "origin_not_found",
            "details": {"point_id": "i66:1:entry:EB"},
        },
        "point_ids": [],
        "connection_ids": [],
        "connection_types": [],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }


def _route_result(row: dict[str, Any]) -> ToolResult:
    return {
        "toolUseId": "tool-123",
        "status": "success",
        "content": [{"json": row}],
    }


def test_strands_loads_exact_strict_input_schema():
    assert not hasattr(pricing_tool.route_validation, "TOOL_SPEC")
    loaded = load_tools_from_module_path("agent_tools.get_current_toll_price")
    assert len(loaded) == 1
    assert loaded[0].tool_name == "get_current_toll_price"
    schema = loaded[0].tool_spec["inputSchema"]["json"]
    assert schema["required"] == [
        "origin_point_id",
        "destination_point_id",
        "pricing_profile",
    ]
    assert set(schema["properties"]) == {
        "origin_point_id",
        "destination_point_id",
        "pricing_profile",
    }
    assert schema["additionalProperties"] is False
    profile_schema = schema["$defs"]["_PricingProfile"]
    assert set(profile_schema["properties"]) == {
        "vehicle_class",
        "payment_method",
        "transponder_mode",
    }
    assert profile_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("pricing_profile"),
        lambda data: data.update({"requested_at": "TOP-SECRET"}),
        lambda data: data["pricing_profile"].update({"vehicle_class": 2}),
        lambda data: data["pricing_profile"].update({"occupancy": 3}),
    ],
)
def test_malformed_input_fails_safely_without_route_validation(
    monkeypatch, caplog, mutation
):
    input_data = _input()
    mutation(input_data)
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "validate_toll_route",
        lambda *_args, **_kwargs: pytest.fail("invalid input reached the database"),
    )

    with caplog.at_level(logging.ERROR):
        result = pricing_tool.get_current_toll_price(_tool_use(input_data))

    assert result == {
        "toolUseId": "tool-123",
        "status": "error",
        "content": [
            {"text": "Unable to get the current toll price. Reference: tool-123."}
        ],
    }
    assert caplog.records[0].failureStage == "input_validation"
    assert "TOP-SECRET" not in caplog.text


def test_unsupported_profile_short_circuits_before_route_validation(monkeypatch):
    input_data = _input()
    input_data["pricing_profile"]["transponder_mode"] = "hov"
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "validate_toll_route",
        lambda *_args, **_kwargs: pytest.fail("unsupported profile reached RDS"),
    )

    result = pricing_tool.get_current_toll_price(_tool_use(input_data))

    assert result == {
        "toolUseId": "tool-123",
        "status": "success",
        "content": [
            {
                "json": {
                    "origin_point_id": "i66:1:entry:EB",
                    "destination_point_id": "i66:4:exit:EB",
                    "error": "pricing_unavailable",
                    "reason": "unsupported_pricing_profile",
                }
            }
        ],
    }


def test_nonvalid_route_is_returned_without_pricing(monkeypatch):
    route_result = _route_result(_route_row("invalid_origin"))
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "validate_toll_route",
        lambda *_args, **_kwargs: route_result,
    )
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: pytest.fail("nonvalid route reached pricing"),
    )

    assert pricing_tool.get_current_toll_price(_tool_use(_input())) == route_result


def test_route_exception_is_logged_safely(monkeypatch, caplog):
    secret = "secret route crash"

    def fail_route(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "validate_toll_route",
        fail_route,
    )

    with caplog.at_level(logging.ERROR):
        result = pricing_tool.get_current_toll_price(_tool_use(_input()))

    assert result == {
        "toolUseId": "tool-123",
        "status": "error",
        "content": [
            {"text": "Unable to get the current toll price. Reference: tool-123."}
        ],
    }
    assert caplog.records[0].failureStage == "route_validation"
    assert caplog.records[0].exceptionType == "RuntimeError"
    assert secret not in caplog.text


def test_valid_route_returns_ordered_facility_legs(monkeypatch):
    route_row = _route_row()
    route = pricing_tool.route_validation._RouteResponse.model_validate(  # pyright: ignore[reportPrivateUsage]
        route_row
    )
    pricing_row = {
        **route_row,
        "facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "i66",
                "point_ids": ["i66:1:entry:EB", "i66:4:exit:EB"],
                "connection_ids": ["source:i66:EB:1:4"],
                "pricing_key": {
                    "source_route_key": "EB:1:4",
                    "start_zone_id": 1,
                    "end_zone_id": 4,
                },
            }
        ],
    }
    pricing_route = pricing_tool.route_validation._PricingRouteResponse.model_validate(  # pyright: ignore[reportPrivateUsage]
        pricing_row, context={"route": route}
    )
    route_calls = []
    pricing_calls = []
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "validate_toll_route",
        lambda tool_use: route_calls.append(tool_use) or _route_result(route_row),
    )
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda validated_route: pricing_calls.append(validated_route) or pricing_route,
    )

    result = pricing_tool.get_current_toll_price(_tool_use(_input()))

    assert cast(Any, route_calls[0])["input"] == {
        "origin_point_id": "i66:1:entry:EB",
        "destination_point_id": "i66:4:exit:EB",
    }
    assert pricing_calls == [route]
    assert result == _route_result(pricing_row)
    payload = cast(Any, result)["content"][0]["json"]
    assert "total_usd" not in payload
    assert "components" not in payload


@pytest.mark.parametrize("stage", ["route", "pricing"])
def test_operation_failures_return_only_safe_tool_error(monkeypatch, stage):
    if stage == "route":
        monkeypatch.setattr(
            pricing_tool.route_validation,
            "validate_toll_route",
            lambda *_args, **_kwargs: {
                "toolUseId": "tool-123",
                "status": "error",
                "content": [{"text": "secret internal route failure"}],
            },
        )
    else:
        monkeypatch.setattr(
            pricing_tool.route_validation,
            "validate_toll_route",
            lambda *_args, **_kwargs: _route_result(_route_row()),
        )
        monkeypatch.setattr(
            pricing_tool.route_validation,
            "_validate_pricing_route",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("secret pricing failure")
            ),
        )

    result = pricing_tool.get_current_toll_price(_tool_use(_input()))

    assert result == {
        "toolUseId": "tool-123",
        "status": "error",
        "content": [
            {"text": "Unable to get the current toll price. Reference: tool-123."}
        ],
    }

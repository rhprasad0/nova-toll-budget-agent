# pyright: basic

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from strands.tools.loader import load_tools_from_module_path
from strands.tools.registry import ToolRegistry
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_current_toll_price as pricing_tool

_EASTERN = ZoneInfo("America/New_York")


def _input() -> dict[str, Any]:
    return {
        "origin_point_id": "greenway:1:entry:EB",
        "destination_point_id": "greenway:28:exit:EB",
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


def _route_row() -> dict[str, Any]:
    return {
        "status": "valid",
        "reason": None,
        "point_ids": ["greenway:1:entry:EB", "greenway:28:exit:EB"],
        "connection_ids": ["source:greenway:EB:1:28"],
        "connection_types": ["within_facility"],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }


def _nonvalid_route_rows() -> list[dict[str, Any]]:
    origin = "greenway:1:entry:EB"
    destination = "greenway:28:exit:EB"
    empty_path = {
        "point_ids": [],
        "connection_ids": [],
        "connection_types": [],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }
    return [
        {
            **empty_path,
            "status": "invalid_origin",
            "reason": {
                "code": "origin_not_found",
                "details": {"point_id": origin},
            },
        },
        {
            **empty_path,
            "status": "invalid_destination",
            "reason": {
                "code": "destination_not_found",
                "details": {"point_id": destination},
            },
        },
        {
            **empty_path,
            "status": "no_supported_route",
            "reason": {
                "code": "no_supported_route",
                "details": {
                    "origin_point_id": origin,
                    "destination_point_id": destination,
                },
            },
        },
        {
            **empty_path,
            "status": "traversal_limit_exceeded",
            "reason": {
                "code": "traversal_limit_exceeded",
                "details": {
                    "origin_point_id": origin,
                    "destination_point_id": destination,
                    "maximum_connections": 12,
                },
            },
        },
        {
            "status": "currently_unavailable",
            "reason": {
                "code": "i95_fully_closed",
                "details": {
                    "required_i95_directions": ["NB"],
                    "availability": "closed",
                },
            },
            "point_ids": ["i95:202NO", "i95:201ND"],
            "connection_ids": ["source:i95_shared:Northbound:202NO:201ND"],
            "connection_types": ["within_facility"],
            "general_purpose_gaps": [],
            "i95_evidence": _i95_evidence("closed"),
        },
        {
            "status": "unknown_availability",
            "reason": {
                "code": "i95_missing_source",
                "details": {
                    "required_i95_directions": ["NB"],
                    "availability": "unknown",
                },
            },
            "point_ids": ["i95:202NO", "i95:201ND"],
            "connection_ids": ["source:i95_shared:Northbound:202NO:201ND"],
            "connection_types": ["within_facility"],
            "general_purpose_gaps": [],
            "i95_evidence": {"availability": "unknown", "reason": "missing_source"},
        },
    ]


def _route_result(row: dict[str, Any]) -> ToolResult:
    return {
        "toolUseId": "tool-123",
        "status": "success",
        "content": [{"json": row}],
    }


def _i95_evidence(availability: str) -> dict[str, str]:
    return {
        "availability": availability,
        "northbound_corridor_name": "I-95 NB",
        "northbound_link_status": (
            "NORTHBOUND_OPEN" if availability == "northbound" else "CLOSED"
        ),
        "northbound_interval_end_at": "2026-08-17T12:00:00+00:00",
        "northbound_calculated_at": "2026-08-17T11:59:00+00:00",
        "southbound_corridor_name": "I-95 SB",
        "southbound_link_status": "CLOSED",
        "southbound_interval_end_at": "2026-08-17T12:00:00+00:00",
        "southbound_calculated_at": "2026-08-17T11:59:00+00:00",
    }


def _greenway_leg(
    *, direction: str = "EB", entry: str = "1", exit_: str = "28"
) -> pricing_tool.route_validation._GreenwayFacilityLeg:  # pyright: ignore[reportPrivateUsage]
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._GreenwayFacilityLeg.model_validate(  # pyright: ignore[reportPrivateUsage]
        {
            "route_step_id": "step-1",
            "facility": "greenway",
            "point_ids": [
                f"greenway:{entry}:entry:{direction}",
                f"greenway:{exit_}:exit:{direction}",
            ],
            "connection_ids": [f"source:greenway:{route_key}"],
            "pricing_key": {"source_route_key": route_key, "charge_index": 1},
        }
    )


def _pricing_route(
    row: dict[str, Any], legs: list[dict[str, Any]]
) -> pricing_tool.route_validation._PricingRouteResponse:  # pyright: ignore[reportPrivateUsage]
    return pricing_tool.route_validation._PricingRouteResponse.model_validate(  # pyright: ignore[reportPrivateUsage]
        {**row, "facility_legs": legs}
    )


def _run_tool(input_data: Any | None = None) -> list[dict[str, Any]]:
    async def collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in pricing_tool.get_current_toll_price.stream(
            _tool_use(_input() if input_data is None else input_data),
            {"agent": object()},
        ):
            events.append(dict(event))
        return events

    return asyncio.run(collect())


def _progress_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    progress = []
    for event in events:
        if event.get("type") != "tool_stream":
            continue
        data = event["tool_stream_event"]["data"]
        if isinstance(data, dict) and "stage" in data:
            validated = pricing_tool._ProgressEvent.model_validate(data)  # pyright: ignore[reportPrivateUsage]
            progress.append(cast(dict[str, str], validated.model_dump(mode="json")))
    return progress


def _result(events: list[dict[str, Any]]) -> ToolResult:
    result = cast(ToolResult, events[-1]["tool_result"])
    if result["status"] == "error":
        pricing_tool._OperationError.model_validate(result)  # pyright: ignore[reportPrivateUsage]
    else:
        content = cast(Any, result["content"])
        pricing_tool._OUTPUT_ADAPTER.validate_json(  # pyright: ignore[reportPrivateUsage]
            json.dumps(content[0]["json"])
        )
    return result


def _install_route(monkeypatch, legs: list[dict[str, Any]]) -> None:
    row = _route_row()
    response = _pricing_route(row, legs)
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )


def test_strands_loads_exact_strict_input_schema():
    assert not hasattr(pricing_tool.route_validation, "TOOL_SPEC")
    loaded = load_tools_from_module_path("agent_tools.get_current_toll_price")
    assert loaded == [pricing_tool.get_current_toll_price]
    registry = ToolRegistry()
    registry.register_tool(loaded[0])
    registered_spec = registry.get_all_tools_config()["get_current_toll_price"]
    assert registered_spec == pricing_tool.TOOL_SPEC
    schema = registered_spec["inputSchema"]["json"]
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
    assert registered_spec["outputSchema"]["json"] == (
        pricing_tool._OUTPUT_ADAPTER.json_schema(mode="serialization")  # pyright: ignore[reportPrivateUsage]
    )


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
        "_validate_pricing_route",
        lambda *_args, **_kwargs: pytest.fail("invalid input reached the database"),
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool(input_data)

    assert _progress_events(events) == []
    assert _result(events) == {
        "toolUseId": "tool-123",
        "status": "error",
        "content": [
            {"text": "Unable to get the current toll price. Reference: tool-123."}
        ],
    }
    assert caplog.records[0].failureStage == "input_validation"
    assert "TOP-SECRET" not in caplog.text


def test_unsupported_profile_short_circuits_without_progress(monkeypatch):
    input_data = _input()
    input_data["pricing_profile"]["transponder_mode"] = "hov"
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: pytest.fail("unsupported profile reached RDS"),
    )

    events = _run_tool(input_data)

    assert _progress_events(events) == []
    assert _result(events)["content"] == [
        {
            "json": {
                "origin_point_id": "greenway:1:entry:EB",
                "destination_point_id": "greenway:28:exit:EB",
                "error": "pricing_unavailable",
                "reason": "unsupported_pricing_profile",
            }
        }
    ]


@pytest.mark.parametrize("row", _nonvalid_route_rows(), ids=lambda row: row["status"])
def test_nonvalid_routes_complete_validation_without_pricing(monkeypatch, row):
    response = _pricing_route(row, [])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )

    monkeypatch.setattr(
        pricing_tool,
        "_success",
        lambda *_args, **_kwargs: pytest.fail("nonvalid route reached pricing"),
    )
    input_data = _input()
    if row["point_ids"]:
        input_data.update(
            {
                "origin_point_id": row["point_ids"][0],
                "destination_point_id": row["point_ids"][-1],
            }
        )

    events = _run_tool(input_data)

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
    ]
    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload["status"] == row["status"]
    assert ("facility_legs" in payload) is bool(row["point_ids"])
    assert "total_usd" not in payload
    assert "components" not in payload


def test_route_failure_streams_failed_and_returns_only_safe_error(monkeypatch, caplog):
    secret = "private-pricing-route"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        fail,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool()

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "failed"),
    ]
    result = _result(events)
    assert result["status"] == "error"
    assert result["content"] == [
        {"text": "Unable to get the current toll price. Reference: tool-123."}
    ]
    assert secret not in str(_progress_events(events))
    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("direction", "entry", "exit_", "evaluated_at", "price", "period", "rate_name"),
    [
        (
            "EB",
            "1",
            "2A",
            datetime(2026, 8, 17, 6, 29, tzinfo=_EASTERN),
            "4.55",
            "off_peak",
            "secondary_plaza",
        ),
        (
            "EB",
            "1",
            "2A",
            datetime(2026, 8, 17, 6, 30, tzinfo=_EASTERN),
            "5.10",
            "peak",
            "secondary_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 17, 8, 59, tzinfo=_EASTERN),
            "5.80",
            "peak",
            "mainline_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 17, 9, 0, tzinfo=_EASTERN),
            "5.25",
            "off_peak",
            "mainline_plaza",
        ),
        (
            "WB",
            "28",
            "1",
            datetime(2026, 8, 17, 16, 0, tzinfo=_EASTERN),
            "5.80",
            "peak",
            "mainline_plaza",
        ),
        (
            "WB",
            "8",
            "1",
            datetime(2026, 8, 17, 18, 29, tzinfo=_EASTERN),
            "5.10",
            "peak",
            "secondary_plaza",
        ),
        (
            "WB",
            "28",
            "1",
            datetime(2026, 8, 17, 18, 30, tzinfo=_EASTERN),
            "5.25",
            "off_peak",
            "mainline_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 22, 7, 0, tzinfo=_EASTERN),
            "5.25",
            "off_peak",
            "mainline_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 17, 10, 30, tzinfo=UTC),
            "5.80",
            "peak",
            "mainline_plaza",
        ),
    ],
)
def test_greenway_schedule_rates(
    direction, entry, exit_, evaluated_at, price, period, rate_name
):
    component = pricing_tool._price_greenway(
        _greenway_leg(direction=direction, entry=entry, exit_=exit_), evaluated_at
    )

    assert component.price_usd == Decimal(price)
    assert component.rate_period == period
    assert component.published_schedule.rate_name == rate_name
    assert component.component_evaluated_at.tzinfo == _EASTERN


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["pricing_key"].update({"charge_index": 2}),
        lambda data: data.update({"connection_ids": ["source:greenway:EB:1:8"]}),
        lambda data: data.update(
            {"point_ids": ["greenway:1:entry:EB", "greenway:8:exit:EB"]}
        ),
        lambda data: data["pricing_key"].update({"source_route_key": "bad-key"}),
    ],
)
def test_greenway_pricer_rejects_misaligned_legs(mutation):
    data = _greenway_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._GreenwayFacilityLeg.model_validate(data)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ValueError, match="Greenway"):
        pricing_tool._price_greenway(leg, datetime(2026, 8, 17, 8, 0, tzinfo=_EASTERN))


def test_greenway_pricer_requires_aware_evaluation_time():
    with pytest.raises(ValueError, match="aware"):
        pricing_tool._price_greenway(
            _greenway_leg(),
            datetime(2026, 8, 17, 8),  # noqa: DTZ001
        )


def test_greenway_only_route_streams_progress_and_returns_total(monkeypatch):
    leg = _greenway_leg().model_dump(mode="json")
    _install_route(monkeypatch, [leg])
    evaluated_at = datetime(2026, 8, 17, 6, 30, tzinfo=_EASTERN)
    monkeypatch.setattr(pricing_tool, "_current_eastern_time", lambda: evaluated_at)

    events = _run_tool()

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("greenway_pricing", "running"),
        ("greenway_pricing", "completed"),
    ]
    result = _result(events)
    assert result["status"] == "success"
    payload = cast(Any, result)["content"][0]["json"]
    assert payload == {
        "origin_point_id": "greenway:1:entry:EB",
        "destination_point_id": "greenway:28:exit:EB",
        "method": "latest_complete_current_facility_prices",
        "evaluated_at": "2026-08-17T06:30:00-04:00",
        "maximum_observation_age_minutes": 30,
        "pricing_profile": _input()["pricing_profile"],
        "source_kind": "schedule_derived",
        "components": [
            {
                "route_step_id": "step-1",
                "price_usd": "5.80",
                "source_kind": "schedule_derived",
                "pricing_method": "published_schedule",
                "facility": "greenway",
                "component_evaluated_at": "2026-08-17T06:30:00-04:00",
                "rate_period": "peak",
                "published_schedule": {
                    "schedule_id": "dulles_greenway_toll_calculator_2026-08-04",
                    "rate_name": "mainline_plaza",
                    "source_url": "https://www.dullesgreenway.com/toll-calculator/",
                    "retrieved_at": "2026-08-04",
                },
            }
        ],
        "total_usd": "5.80",
    }


def test_valid_no_toll_route_returns_zero_without_pricing_progress(monkeypatch):
    _install_route(monkeypatch, [])
    monkeypatch.setattr(
        pricing_tool,
        "_current_eastern_time",
        lambda: datetime(2026, 8, 22, 12, tzinfo=_EASTERN),
    )

    events = _run_tool()

    assert [event["stage"] for event in _progress_events(events)] == [
        "route_validation",
        "route_validation",
    ]
    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload["source_kind"] == "none"
    assert payload["components"] == []
    assert payload["total_usd"] == "0.00"


def test_unimplemented_facility_returns_safe_error(monkeypatch):
    row = {
        **_route_row(),
        "point_ids": ["i66:1:entry:EB", "i66:4:exit:EB"],
        "connection_ids": ["source:i66:EB:1:4"],
    }
    leg = {
        "route_step_id": "step-1",
        "facility": "i66",
        "point_ids": row["point_ids"],
        "connection_ids": row["connection_ids"],
        "pricing_key": {
            "source_route_key": "EB:1:4",
            "start_zone_id": 1,
            "end_zone_id": 4,
        },
    }
    response = _pricing_route(row, [leg])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )

    events = _run_tool()

    assert [event["stage"] for event in _progress_events(events)] == [
        "route_validation",
        "route_validation",
    ]
    assert _result(events)["status"] == "error"


def test_greenway_failure_streams_failed_and_sanitizes_error(monkeypatch, caplog):
    secret = "private Greenway crash"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    _install_route(monkeypatch, [_greenway_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool,
        "_price_greenway",
        fail,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool()

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("greenway_pricing", "running"),
        ("greenway_pricing", "failed"),
    ]
    assert _result(events)["status"] == "error"
    assert secret not in str(_progress_events(events))
    assert secret not in caplog.text

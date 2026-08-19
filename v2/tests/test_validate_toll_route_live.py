"""Scheduled live checks for v2 current toll route validation."""

import asyncio
import os
from typing import Any, cast

import boto3
import pytest
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_current_toll_price as pricing_tool
from agent_tools import validate_toll_route as route_validation

pytestmark = pytest.mark.live

_DB_IDENTIFIER = "nova-toll-db"
_WINDOW_EXPECTATIONS = {
    "i95_northbound": {
        "availability": "northbound",
        "northbound_status": "valid",
        "northbound_reason": None,
        "southbound_status": "currently_unavailable",
        "southbound_reason": "i95_opposite_direction_open",
        "northbound_link_status": "NORTHBOUND_OPEN",
        "southbound_link_status": "CLOSED",
    },
    "i95_reversal": {
        "availability": "closed",
        "northbound_status": "currently_unavailable",
        "northbound_reason": "i95_fully_closed",
        "southbound_status": "currently_unavailable",
        "southbound_reason": "i95_fully_closed",
        "northbound_link_status": "CLOSED",
        "southbound_link_status": "CLOSED",
    },
    "i95_southbound": {
        "availability": "southbound",
        "northbound_status": "currently_unavailable",
        "northbound_reason": "i95_opposite_direction_open",
        "southbound_status": "valid",
        "southbound_reason": None,
        "northbound_link_status": "CLOSED",
        "southbound_link_status": "SOUTHBOUND_OPEN",
    },
}
_GREENWAY_PEAK_TRIPS = {
    "greenway_eb_peak": ("greenway:1:entry:EB", "greenway:28:exit:EB"),
    "greenway_wb_peak": ("greenway:28:entry:WB", "greenway:1:exit:WB"),
}


def _configure_rds_endpoint() -> None:
    rds = cast(
        Any,
        boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "rds", region_name="us-east-1"
        ),
    )
    instance = cast(
        dict[str, Any],
        rds.describe_db_instances(DBInstanceIdentifier=_DB_IDENTIFIER)["DBInstances"][
            0
        ],
    )
    os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
    os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])


def _tool_use(origin: str, destination: str, tool_use_id: str) -> ToolUse:
    return cast(
        ToolUse,
        {
            "toolUseId": tool_use_id,
            "name": "get_current_toll_price",
            "input": {
                "origin_point_id": origin,
                "destination_point_id": destination,
                "pricing_profile": {
                    "vehicle_class": "two_axle_passenger",
                    "payment_method": "e_zpass",
                    "transponder_mode": "toll",
                },
            },
        },
    )


def _run_pricing_tool(tool_use: ToolUse) -> ToolResult:
    async def invoke() -> ToolResult:
        result: ToolResult | None = None
        async for event in pricing_tool.get_current_toll_price.stream(
            tool_use, {"agent": object()}
        ):
            if event.get("type") == "tool_result":
                result = cast(ToolResult, event["tool_result"])
        assert result is not None
        return result

    return asyncio.run(invoke())


def _validate(origin: str, destination: str, tool_use_id: str) -> dict[str, Any]:
    tool_use = _tool_use(origin, destination, tool_use_id)
    result = _run_pricing_tool(tool_use)
    if result["status"] == "error":
        assert result["content"] == [
            {"text": f"Unable to get the current toll price. Reference: {tool_use_id}."}
        ]
        result = route_validation.validate_toll_route(
            cast(
                ToolUse,
                {
                    **tool_use,
                    "name": "validate_toll_route",
                    "input": {
                        "origin_point_id": origin,
                        "destination_point_id": destination,
                    },
                },
            )
        )
    assert result["status"] == "success", result
    assert result["toolUseId"] == tool_use_id
    assert len(result["content"]) == 1
    content = cast(Any, result["content"])
    route = cast(dict[str, Any], content[0]["json"])
    return route


def _reason_code(route: dict[str, Any]) -> str | None:
    reason = route["reason"]
    return None if reason is None else cast(str, reason["code"])


def test_live_i95_state_matches_timed_window() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("i95_"):
        pytest.skip("not an I-95 timed window")
    assert window_id in _WINDOW_EXPECTATIONS, f"unknown timed window {window_id!r}"
    expected = _WINDOW_EXPECTATIONS[window_id]
    _configure_rds_endpoint()

    northbound = _validate("i95:202NO", "i95:201ND", f"{window_id}-northbound")
    southbound = _validate("i95:200SO", "i95:202SD", f"{window_id}-southbound")
    i66 = _validate("i66:1:entry:EB", "i66:4:exit:EB", f"{window_id}-i66-pricing-route")

    assert northbound["status"] == expected["northbound_status"]
    assert _reason_code(northbound) == expected["northbound_reason"]
    assert southbound["status"] == expected["southbound_status"]
    assert _reason_code(southbound) == expected["southbound_reason"]
    assert i66["status"] == "valid"

    for route in (northbound, southbound):
        evidence = route["i95_evidence"]
        assert evidence["availability"] == expected["availability"]
        assert evidence["northbound_link_status"] == expected["northbound_link_status"]
        assert evidence["southbound_link_status"] == expected["southbound_link_status"]


def test_live_greenway_to_dca_matches_timed_i95_state() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("i95_"):
        pytest.skip("not an I-95 timed window")
    assert window_id in _WINDOW_EXPECTATIONS, f"unknown timed window {window_id!r}"
    expected = _WINDOW_EXPECTATIONS[window_id]
    _configure_rds_endpoint()

    route = _validate(
        "greenway:1:entry:EB", "airport_dca", f"{window_id}-greenway-to-dca"
    )

    assert route["status"] == expected["northbound_status"]
    assert _reason_code(route) == expected["northbound_reason"]
    assert route["point_ids"] == [
        "greenway:1:entry:EB",
        "greenway:28:exit:EB",
        "dtr:28:entry:EB",
        "dtr:1819:exit:EB",
        "i495:182SO",
        "i95:2239ND",
        "airport_dca",
    ]
    assert route["connection_ids"] == [
        "source:greenway:EB:1:28",
        "greenway_to_dtr",
        "source:dtr:EB:28:1819",
        "dulles_toll_road_to_i495",
        "source:i95_shared:Southbound:182SO:2239ND",
        "i95_north_to_dca_from_i495_south",
    ]
    assert route["connection_types"] == [
        "within_facility",
        "toll_handoff",
        "within_facility",
        "toll_handoff",
        "general_purpose_gap",
        "airport_access",
    ]
    assert route["general_purpose_gaps"] == [
        {
            "connection_id": "source:i95_shared:Southbound:182SO:2239ND",
            "boundary_point_id": "i495:192SD",
            "role": "suffix",
            "i95_direction": "NB",
            "fallback_required": window_id != "i95_northbound",
        }
    ]
    evidence = route["i95_evidence"]
    assert evidence["availability"] == expected["availability"]
    assert evidence["northbound_link_status"] == expected["northbound_link_status"]
    assert evidence["southbound_link_status"] == expected["southbound_link_status"]


def test_live_greenway_peak_price() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("greenway_"):
        pytest.skip("not a Greenway timed window")
    assert window_id in _GREENWAY_PEAK_TRIPS, f"unknown timed window {window_id!r}"
    _configure_rds_endpoint()

    origin, destination = _GREENWAY_PEAK_TRIPS[window_id]
    result = _run_pricing_tool(_tool_use(origin, destination, window_id))

    assert result["status"] == "success", result
    content = cast(Any, result["content"])
    payload = cast(dict[str, Any], content[0]["json"])
    assert payload["origin_point_id"] == origin
    assert payload["destination_point_id"] == destination
    assert payload["source_kind"] == "schedule_derived"
    assert payload["total_usd"] == "7.80"
    assert len(payload["components"]) == 1
    component = payload["components"][0]
    assert component["facility"] == "greenway"
    assert component["price_usd"] == "7.80"
    assert component["rate_period"] == "peak"
    assert component["published_schedule"]["rate_name"] == "mainline_plaza"

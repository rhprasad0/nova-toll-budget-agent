"""Scheduled live checks for v2 current toll route validation."""

import asyncio
import os
from typing import Any, cast

import boto3
import pytest
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_current_toll_price as pricing_tool

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
    result = _run_pricing_tool(_tool_use(origin, destination, tool_use_id))
    assert result["status"] == "success", result
    assert result["toolUseId"] == tool_use_id
    assert len(result["content"]) == 1
    content = cast(Any, result["content"])
    route = cast(dict[str, Any], content[0]["json"])
    return route


def _assert_priced(payload: dict[str, Any], origin: str, destination: str) -> None:
    assert payload["origin_point_id"] == origin
    assert payload["destination_point_id"] == destination
    assert payload["method"] == "latest_complete_current_facility_prices"
    assert float(payload["total_usd"]) > 0
    assert any(
        component["facility"] == "i95_i495" for component in payload["components"]
    )


def _assert_unavailable(
    payload: dict[str, Any],
    status: str | None,
    reason: str | None,
    expected: dict[str, Any],
) -> None:
    assert status is not None
    assert reason is not None
    assert payload["status"] == status
    assert _reason_code(payload) == reason
    evidence = payload["i95_evidence"]
    assert evidence["availability"] == expected["availability"]
    assert evidence["northbound_link_status"] == expected["northbound_link_status"]
    assert evidence["southbound_link_status"] == expected["southbound_link_status"]


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

    northbound_origin, northbound_destination = "i95:203NO", "airport_dca"
    southbound_origin, southbound_destination = "i95:200SO", "i95:202SD"
    northbound = _validate(
        northbound_origin, northbound_destination, f"{window_id}-northbound"
    )
    southbound = _validate(
        southbound_origin, southbound_destination, f"{window_id}-southbound"
    )
    i66 = _validate("i66:1:entry:EB", "i66:4:exit:EB", f"{window_id}-i66-pricing-route")

    if expected["northbound_status"] == "valid":
        _assert_priced(northbound, northbound_origin, northbound_destination)
    else:
        _assert_unavailable(
            northbound,
            expected["northbound_status"],
            expected["northbound_reason"],
            expected,
        )
    if expected["southbound_status"] == "valid":
        _assert_priced(southbound, southbound_origin, southbound_destination)
    else:
        _assert_unavailable(
            southbound,
            expected["southbound_status"],
            expected["southbound_reason"],
            expected,
        )
    assert i66["method"] == "latest_complete_current_facility_prices"
    assert any(component["facility"] == "i66" for component in i66["components"])


def test_live_i95_northbound_restart_is_state_independent() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("i95_"):
        pytest.skip("not an I-95 timed window")
    assert window_id in _WINDOW_EXPECTATIONS, f"unknown timed window {window_id!r}"
    _configure_rds_endpoint()

    initial = _validate("i95:206NO", "i495:1859ND", f"{window_id}-restart-offer")
    assert initial == {
        "status": "invalid_origin",
        "reason": {
            "code": "i95_northbound_requires_i495_restart",
            "details": {
                "point_id": "i95:206NO",
                "point_type": "entry",
                "suggested_restart_point_id": "i495:192NO",
                "suggested_destination_point_id": "i495:185ND",
            },
        },
        "point_ids": [],
        "connection_ids": [],
        "connection_types": [],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }

    accepted = _validate("i495:192NO", "i495:185ND", f"{window_id}-restart-accepted")
    assert accepted["origin_point_id"] == "i495:192NO"
    assert accepted["destination_point_id"] == "i495:185ND"
    assert accepted["method"] == "latest_complete_current_facility_prices"
    assert "total_usd" in accepted
    assert any(
        component["facility"] == "i95_i495" for component in accepted["components"]
    )


def test_live_greenway_to_dca_matches_timed_i95_state() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("i95_"):
        pytest.skip("not an I-95 timed window")
    assert window_id in _WINDOW_EXPECTATIONS, f"unknown timed window {window_id!r}"
    expected = _WINDOW_EXPECTATIONS[window_id]
    _configure_rds_endpoint()

    payload = _validate(
        "greenway:1:entry:EB", "airport_dca", f"{window_id}-greenway-to-dca"
    )

    if expected["northbound_status"] == "valid":
        _assert_priced(payload, "greenway:1:entry:EB", "airport_dca")
        assert [component["facility"] for component in payload["components"]] == [
            "greenway",
            "dtr",
            "dtr",
            "i95_i495",
            "i95_i495",
        ]
        return

    _assert_unavailable(
        payload,
        expected["northbound_status"],
        expected["northbound_reason"],
        expected,
    )
    assert payload["point_ids"] == [
        "greenway:1:entry:EB",
        "greenway:28:exit:EB",
        "dtr:28:entry:EB",
        "dtr:1819:exit:EB",
        "i495:182SO",
        "i95:2239ND",
        "airport_dca",
    ]
    assert payload["connection_ids"] == [
        "source:greenway:EB:1:28",
        "greenway_to_dtr",
        "source:dtr:EB:28:1819",
        "dulles_toll_road_to_i495",
        "source:i95_shared:Southbound:182SO:2239ND",
        "i95_north_to_dca_from_i495_south",
    ]
    assert payload["connection_types"] == [
        "within_facility",
        "toll_handoff",
        "within_facility",
        "toll_handoff",
        "general_purpose_gap",
        "airport_access",
    ]
    assert payload["general_purpose_gaps"] == [
        {
            "connection_id": "source:i95_shared:Southbound:182SO:2239ND",
            "boundary_point_id": "i495:192SD",
            "role": "suffix",
            "i95_direction": "NB",
            "fallback_required": window_id != "i95_northbound",
        }
    ]


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
    assert payload["total_usd"] == "5.80"
    assert len(payload["components"]) == 1
    component = payload["components"][0]
    assert component["facility"] == "greenway"
    assert component["price_usd"] == "5.80"
    assert component["rate_period"] == "peak"
    assert component["published_schedule"]["rate_name"] == "mainline_plaza"

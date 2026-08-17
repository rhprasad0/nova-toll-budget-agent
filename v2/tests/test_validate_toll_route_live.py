"""Scheduled live checks for the v2 route-validation tool."""

import os
from typing import Any, cast

import boto3
import pytest

from agent_tools import validate_toll_route as route_tool

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


def _validate(origin: str, destination: str, tool_use_id: str) -> dict[str, Any]:
    result = cast(
        Any,
        route_tool.validate_toll_route(
            {
                "toolUseId": tool_use_id,
                "name": "validate_toll_route",
                "input": {
                    "origin_point_id": origin,
                    "destination_point_id": destination,
                },
            }
        ),
    )
    assert result["status"] == "success", result
    assert result["toolUseId"] == tool_use_id
    assert len(result["content"]) == 1
    return cast(dict[str, Any], result["content"][0]["json"])


def _reason_code(route: dict[str, Any]) -> str | None:
    reason = route["reason"]
    return None if reason is None else cast(str, reason["code"])


def test_live_i95_state_matches_timed_window() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    assert window_id in _WINDOW_EXPECTATIONS, f"unknown timed window {window_id!r}"
    expected = _WINDOW_EXPECTATIONS[window_id]
    _configure_rds_endpoint()

    northbound = _validate("i95:202NO", "i95:201ND", f"{window_id}-northbound")
    southbound = _validate("i95:200SO", "i95:202SD", f"{window_id}-southbound")

    assert northbound["status"] == expected["northbound_status"]
    assert _reason_code(northbound) == expected["northbound_reason"]
    assert southbound["status"] == expected["southbound_status"]
    assert _reason_code(southbound) == expected["southbound_reason"]

    for route in (northbound, southbound):
        evidence = route["i95_evidence"]
        assert evidence["availability"] == expected["availability"]
        assert evidence["northbound_link_status"] == expected["northbound_link_status"]
        assert evidence["southbound_link_status"] == expected["southbound_link_status"]

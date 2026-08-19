"""Scheduled live checks for v2 current toll route validation."""

import os
from typing import Any, cast

import boto3
import pytest

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
        pricing_tool.get_current_toll_price(
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
            }
        ),
    )
    assert result["status"] == "success", result
    assert result["toolUseId"] == tool_use_id
    assert len(result["content"]) == 1
    route = cast(dict[str, Any], result["content"][0]["json"])

    if route["status"] == "valid":
        assert route["facility_legs"]
    elif "facility_legs" in route:
        assert route["facility_legs"] == []
    return route


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

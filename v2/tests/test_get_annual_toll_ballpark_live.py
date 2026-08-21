"""Opt-in live checks for the annual toll ballpark tool."""

import asyncio
import os
from typing import Any, cast

import boto3
import pytest
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_annual_toll_ballpark as ballpark

pytestmark = pytest.mark.live

_DB_IDENTIFIER = "nova-toll-db"


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


def _run(data: dict[str, Any], tool_use_id: str) -> dict[str, Any]:
    tool_use = cast(
        ToolUse,
        {
            "name": "get_annual_toll_ballpark",
            "toolUseId": tool_use_id,
            "input": data,
        },
    )

    async def invoke() -> ToolResult:
        result: ToolResult | None = None
        async for event in ballpark.get_annual_toll_ballpark.stream(
            tool_use, {"agent": object()}
        ):
            if "tool_result" in event:
                result = cast(ToolResult, event["tool_result"])
        assert result is not None
        return result

    result = asyncio.run(invoke())
    assert result["status"] == "success", result
    content = cast(Any, result["content"])
    return cast(dict[str, Any], content[0]["json"])


def _request(
    outbound: tuple[str, str, str], return_: tuple[str, str, str]
) -> dict[str, Any]:
    return {
        "outbound": {
            "origin_point_id": outbound[0],
            "destination_point_id": outbound[1],
            "departure_time": outbound[2],
        },
        "return": {
            "origin_point_id": return_[0],
            "destination_point_id": return_[1],
            "departure_time": return_[2],
        },
        "weekdays": ["monday"],
        "planned_annual_commute_days": 53,
    }


def test_live_fixed_rate_round_trip() -> None:
    _configure_rds_endpoint()
    payload = _run(
        _request(
            ("greenway:1:entry:EB", "greenway:28:exit:EB", "08:00:00"),
            ("greenway:28:entry:WB", "greenway:1:exit:WB", "17:30:00"),
        ),
        "annual-ballpark-fixed",
    )
    assert payload["method"] == "recent_complete_same_date_round_trips"
    assert payload["sample_status"] == "complete"
    assert payload["coverage"]["eligible_date_count"] == 12
    assert payload["coverage"]["coverage_percent"] == "100.0"
    assert payload["uses_current_fixed_rates"] is True
    assert payload["scenarios"]["p50"]["daily_round_trip_usd"] == "11.60"
    assert payload["scenarios"]["p50"]["annualized_usd"] == "614.80"
    assert payload["facilities"][0]["facility"] == "greenway"


def test_live_dynamic_round_trip_is_bounded_and_reproducible() -> None:
    _configure_rds_endpoint()
    payload = _run(
        _request(
            ("i66:1:entry:EB", "i66:4:exit:EB", "08:00:00"),
            ("i66:4:entry:WB", "i66:1:exit:WB", "17:30:00"),
        ),
        "annual-ballpark-dynamic",
    )
    assert payload["coverage"]["eligible_date_count"] == 12
    assert 0 <= payload["coverage"]["complete_pair_count"] <= 12
    if payload.get("error") == "ballpark_unavailable":
        assert payload["reason"] == "no_complete_paired_days"
        assert payload["facilities"] == []
        return
    assert set(payload["scenarios"]) == {"p25", "p50", "p90"}
    assert payload["facilities"][0]["facility"] == "i66"
    assert not ({"complete_days", "excluded_dates", "routes"} & payload.keys())

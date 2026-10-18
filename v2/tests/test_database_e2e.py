"""Agent tools against the real disposable oracle database built by run_db_tests.sh."""

import asyncio
import json
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from strands.types.tools import ToolResult, ToolUse

from agent import toll_agent
from agent_tools import current_price_domain as pricing_tool
from agent_tools import get_annual_toll_ballpark as ballpark
from agent_tools import get_current_toll_price as pricing_transport
from agent_tools import validate_toll_route as route_validation

pytestmark = pytest.mark.live

DATABASE = "nova_toll_v2_bootstrap_test"  # built by scripts/run_db_tests.sh
_EASTERN = ZoneInfo("America/New_York")
_PROFILE = {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll",
}


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Replace only IAM/TLS; the tools still choose their least-privilege role."""
    import psycopg  # lazy: the loader tests assert psycopg stays unimported
    from psycopg.rows import dict_row

    opened: list[tuple[str, Any]] = []

    def connect(user: str) -> object:
        # libpq PG* variables select the cluster (5432, or 5433 for the retained run).
        connection = psycopg.connect(dbname=DATABASE, user=user, row_factory=dict_row)
        opened.append((user, connection))
        return connection

    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("PRICING_DB_USER", raising=False)
    monkeypatch.setattr(route_validation, "_connect_to_database", connect)
    return opened


def _stream(tool: Any, name: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    tool_use = cast(ToolUse, {"name": name, "toolUseId": "e2e", "input": data})

    async def collect() -> list[dict[str, Any]]:
        return [dict(event) async for event in tool.stream(tool_use, {"agent": object()})]

    return asyncio.run(collect())


def _stages(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [
        (data["stage"], data["status"])
        for event in events
        if event.get("type") == "tool_stream"
        and isinstance(data := event["tool_stream_event"]["data"], dict)
        and "stage" in data
    ]


def _payload(events: list[dict[str, Any]], adapter: Any) -> dict[str, Any]:
    result = cast(ToolResult, events[-1]["tool_result"])
    assert result["status"] == "success", result
    payload = cast(dict[str, Any], cast(Any, result["content"])[0]["json"])
    adapter.validate_json(json.dumps(payload))
    return payload


def _assert_closed_as(connections: list[tuple[str, Any]], user: str) -> None:
    assert connections
    assert {role for role, _ in connections} == {user}
    assert all(connection.closed for _, connection in connections)


def test_prompt_points_load_as_tollchat_agent(connections: list[tuple[str, Any]]) -> None:
    points = toll_agent.load_prompt_points()

    assert "greenway:1:entry:EB" in {point.point_id for point in points}
    _assert_closed_as(connections, "tollchat_agent")


@pytest.mark.parametrize(
    ("origin", "destination", "stages", "facilities", "total"),
    [
        (
            "greenway:1:entry:EB",
            "dtr:10:exit:EB",
            ["greenway_pricing", "dtr_pricing"],
            ["greenway", "dtr", "dtr"],
            "9.25",
        ),
        (
            "dtr:66:entry:WB",
            "greenway:1:exit:WB",
            ["dtr_pricing", "greenway_pricing"],
            ["dtr", "dtr", "greenway"],
            "11.25",
        ),
        ("airport_iad", "i66:6:entry:EB", [], [], "0.00"),
        ("airport_iad", "dtr:66:entry:WB", [], [], "0.00"),
        ("airport_iad", "i495:182NO", [], [], "0.00"),
        ("airport_iad", "i495:182SO", [], [], "0.00"),
    ],
)
def test_current_price_on_real_routes(
    monkeypatch: pytest.MonkeyPatch,
    connections: list[tuple[str, Any]],
    origin: str,
    destination: str,
    stages: list[str],
    facilities: list[str],
    total: str,
) -> None:
    def monday_noon() -> datetime:
        return datetime(2026, 8, 17, 12, tzinfo=_EASTERN)

    monkeypatch.setattr(pricing_tool, "_current_eastern_time", monday_noon)

    events = _stream(
        pricing_transport.get_current_toll_price,
        "get_current_toll_price",
        {
            "origin_point_id": origin,
            "destination_point_id": destination,
            "pricing_profile": _PROFILE,
        },
    )

    expected = [
        (stage, status)
        for stage in ("route_validation", *stages)
        for status in ("running", "completed")
    ]
    assert _stages(events) == expected
    payload = _payload(events, pricing_tool._OUTPUT_ADAPTER)
    assert payload["origin_point_id"] == origin
    assert payload["destination_point_id"] == destination
    assert [component["facility"] for component in payload["components"]] == facilities
    assert payload["total_usd"] == total
    if not facilities:
        assert payload["source_kind"] == "none"
    _assert_closed_as(connections, "pricing_caller")


def test_annual_ballpark_fixed_greenway_round_trip(connections: list[tuple[str, Any]]) -> None:
    # The scheduled annual check's fixed case: fixed rates need no observed history.
    events = _stream(
        ballpark.get_annual_toll_ballpark,
        "get_annual_toll_ballpark",
        {
            "outbound": {
                "origin_point_id": "greenway:1:entry:EB",
                "destination_point_id": "greenway:28:exit:EB",
                "departure_time": "08:00:00",
            },
            "return": {
                "origin_point_id": "greenway:28:entry:WB",
                "destination_point_id": "greenway:1:exit:WB",
                "departure_time": "17:30:00",
            },
            "weekdays": ["monday"],
            "planned_annual_commute_days": 53,
            "gross_annual_income_usd": "120000.00",
        },
    )

    assert [status for _, status in _stages(events)].count("completed") == 3
    payload = _payload(events, ballpark._OUTPUT_ADAPTER)
    assert payload["sample_status"] == "complete"
    assert payload["coverage"]["eligible_date_count"] == 12
    assert payload["coverage"]["coverage_percent"] == "100.0"
    assert payload["income"]["estimated_after_tax_usd"] == "80000.00"
    assert payload["scenarios"]["p50"]["daily_toll_usd"] == "11.60"
    assert payload["scenarios"]["p50"]["annual_toll_usd"] == "614.80"
    assert payload["facilities"][0]["facility"] == "greenway"
    _assert_closed_as(connections, "pricing_caller")

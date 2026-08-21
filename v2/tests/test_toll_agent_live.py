"""Opt-in end-to-end checks of model point resolution and tool selection."""

# pyright: basic

import os
from copy import deepcopy
from typing import Any

import boto3
import pytest
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from agent.toll_agent import build_agent, load_prompt_points

pytestmark = pytest.mark.live


class _ToolRecorder(HookProvider):
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def register_hooks(self, registry: HookRegistry, **_kwargs: object) -> None:
        registry.add_callback(BeforeToolCallEvent, self.record)

    def record(self, event: BeforeToolCallEvent) -> None:
        self.calls.append(deepcopy(dict(event.tool_use)))


def _configure_rds() -> None:
    instance = boto3.client("rds", region_name="us-east-1").describe_db_instances(
        DBInstanceIdentifier="nova-toll-db"
    )["DBInstances"][0]
    os.environ.update(
        DB_HOST=instance["Endpoint"]["Address"],
        DB_PORT=str(instance["Endpoint"]["Port"]),
    )


def _invoke(prompt: str):
    _configure_rds()
    recorder = _ToolRecorder()
    agent = build_agent(hooks=[recorder])
    return str(agent(prompt)), recorder.calls, agent


def test_live_prompt_cache_is_reused_by_fresh_agents():
    _configure_rds()
    prompt_points = load_prompt_points()
    prompt = "Briefly say whether you can estimate current and annual tolls."

    for request_number in range(4):
        recorder = _ToolRecorder()
        result = build_agent(prompt_points=prompt_points, hooks=[recorder])(prompt)
        assert recorder.calls == []
        if request_number:
            assert result.metrics.accumulated_usage.get("cacheReadInputTokens", 0) > 0


@pytest.mark.parametrize(
    ("prompt", "origin", "destination"),
    [
        (
            "What is the current Greenway toll from the Leesburg Bypass to Route 28?",
            "greenway:1:entry:EB",
            "greenway:28:exit:EB",
        ),
        (
            "Current toll from 39.10010,-77.56528 to 38.96461,-77.42786 on the Greenway",
            "greenway:1:entry:EB",
            "greenway:28:exit:EB",
        ),
        (
            "Current toll from Leesburg Bypass to Exit 16 on the Dulles Toll Road",
            "greenway:1:entry:EB",
            "dtr:16:exit:EB",
        ),
    ],
)
def test_live_current_price_resolution(prompt, origin, destination):
    answer, calls, _agent = _invoke(prompt)
    assert len(calls) == 1, (answer, calls)
    assert calls[0]["name"] == "get_current_toll_price"
    assert calls[0]["input"]["origin_point_id"] == origin
    assert calls[0]["input"]["destination_point_id"] == destination
    assert calls[0]["input"]["pricing_profile"] == {
        "vehicle_class": "two_axle_passenger",
        "payment_method": "e_zpass",
        "transponder_mode": "toll",
    }
    assert "$" in answer or "unavailable" in answer.lower()


def test_live_annual_round_trip_uses_reversed_endpoints():
    answer, calls, _agent = _invoke(
        "For Monday through Friday, estimate my annual round-trip commute from "
        "Leesburg Bypass to Route 28. I leave at 8 AM, return at 5:30 PM, and "
        "plan 240 commute days."
    )
    assert len(calls) == 1, (answer, calls)
    assert calls[0]["name"] == "get_annual_toll_ballpark"
    assert calls[0]["input"] == {
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
        "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        "planned_annual_commute_days": 240,
    }
    assert "annual" in answer.lower()


@pytest.mark.parametrize(
    "prompt",
    [
        "What was the Greenway toll from Leesburg to Route 28 yesterday at 8 AM?",
        "Price Leesburg to Route 28 for a three-axle truck paying cash.",
    ],
)
def test_live_out_of_contract_requests_do_not_call_tools(prompt):
    answer, calls, _agent = _invoke(prompt)
    assert calls == [], (answer, calls)
    assert "current" in answer.lower() or "two-axle" in answer.lower()


def test_live_wrong_role_presents_and_uses_selected_alternative():
    answer, calls, agent = _invoke(
        "What is the current Greenway toll from Compass Creek to Leesburg Bypass?"
    )
    assert len(calls) == 1, (answer, calls)
    assert calls[0]["input"]["origin_point_id"] == "greenway:2B:exit:WB"
    assert "Battlefield" in answer

    second = str(agent("Use Battlefield Parkway."))
    assert len(calls) == 2, (second, calls)
    assert calls[1]["input"]["origin_point_id"] == "greenway:2A:entry:WB"
    assert calls[1]["input"]["destination_point_id"] == "greenway:1:exit:WB"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("What is the current toll?", ("origin", "destination")),
        (
            "Estimate my annual commute from Leesburg Bypass to Route 28.",
            ("outbound", "return", "weekdays", "commute days"),
        ),
        (
            "What is the current toll from Washington to Westpark Drive?",
            ("I-66", "I-395"),
        ),
    ],
)
def test_live_clarifications_do_not_call_tools(prompt, expected):
    answer, calls, _agent = _invoke(prompt)
    assert calls == [], (answer, calls)
    assert all(fragment.lower() in answer.lower() for fragment in expected), answer


def test_live_i395_to_i95_uses_current_price_tool_once():
    answer, calls, _agent = _invoke(
        "What is the current toll from the Pentagon to Dumfries on I-395/I-95?"
    )
    assert len(calls) == 1, (answer, calls)
    assert calls[0]["name"] == "get_current_toll_price"
    assert calls[0]["input"]["origin_point_id"] == "i95:2233SO"
    assert calls[0]["input"]["destination_point_id"] == "i95:217SD"


def test_live_washington_i395_clarification_uses_i95_northbound_exit():
    answer, calls, agent = _invoke(
        "What is the current toll from Dumfries to Washington?"
    )
    assert calls == [], (answer, calls)
    assert "I-66" in answer and "I-395" in answer

    second = str(agent("I-395."))
    assert 1 <= len(calls) <= 2, (second, calls)
    assert calls[-1]["input"]["origin_point_id"] == "i95:218NO"
    assert calls[-1]["input"]["destination_point_id"] == "i95:224ND"


def test_live_washington_from_i495_south_uses_connector_exit():
    answer, calls, _agent = _invoke(
        "What is the current toll from 495 Express Lanes Start/Georg Wash. "
        "Mem. Pkwy. to Washington D.C. via I-395?"
    )
    assert 1 <= len(calls) <= 2, (answer, calls)
    assert calls[-1]["input"]["origin_point_id"] == "i495:180SO"
    assert calls[-1]["input"]["destination_point_id"] == "i95:2249ND"


def test_live_washington_i395_southbound_uses_dc_entry():
    answer, calls, _agent = _invoke(
        "What is the current toll from Washington D.C. I-395 Southbound to Dumfries?"
    )
    assert len(calls) == 1, (answer, calls)
    assert calls[0]["input"]["origin_point_id"] == "i95:2232SO"
    assert calls[0]["input"]["destination_point_id"] == "i95:217SD"


def test_live_wrong_washington_coordinate_retries_returned_alternative_once():
    answer, calls, _agent = _invoke(
        "Current toll from I-95 Near Cardinal Drive to 38.8707667,-77.0461277; "
        "the destination is Washington D.C. via I-395."
    )
    assert len(calls) == 2, (answer, calls)
    assert calls[0]["input"]["destination_point_id"] == "i95:2249ND"
    assert calls[1]["input"]["destination_point_id"] == "i95:224ND"


def test_live_missing_destination_precedes_wrong_role_validation():
    answer, calls, agent = _invoke("What is the current toll from Compass Creek?")
    assert calls == [], (answer, calls)
    assert "destination" in answer.lower()

    second = str(agent("To Leesburg Bypass."))
    assert len(calls) == 1, (second, calls)
    assert calls[0]["input"]["origin_point_id"] == "greenway:2B:exit:WB"
    assert "Battlefield" in second


def test_live_missing_annual_schedule_precedes_wrong_role_validation():
    answer, calls, agent = _invoke(
        "Estimate my annual commute from Compass Creek to Leesburg Bypass."
    )
    assert calls == [], (answer, calls)
    assert "weekdays" in answer.lower() and "commute days" in answer.lower()

    second = str(
        agent(
            "Outbound at 8 AM, return at 5 PM, Monday through Friday, "
            "for 240 commute days."
        )
    )
    assert len(calls) == 1, (second, calls)
    assert calls[0]["name"] == "get_annual_toll_ballpark"

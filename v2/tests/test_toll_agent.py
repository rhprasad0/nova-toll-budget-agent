"""Prompt, database-loader, and Strands wiring tests without network calls."""

# pyright: basic

import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError
from strands.hooks import (
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
)
from strands.models.openai_responses import OpenAIResponsesModel

from agent import toll_agent
from agent.toll_agent import DuplicateToolUseGuard, build_agent, build_system_prompt
from agent_tools import get_annual_toll_ballpark as ballpark_tool
from agent_tools import get_current_toll_price as current_tool
from scripts import check_agent_contract_versions as version_check

_CONTRACT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "agent" / "contract-manifest.json"
)
_SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def _point(**overrides):
    value = {
        "point_id": "greenway:1:entry:EB",
        "network_id": "greenway",
        "source_node_id": "1",
        "point_type": "entry",
        "direction": "EB",
        "label": "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "aliases": ["Leesburg"],
        "location": {"type": "Point", "coordinates": [-77.5652813, 39.1000972]},
    }
    value.update(overrides)
    return value


def _contract_manifest():
    return json.loads(_CONTRACT_MANIFEST_PATH.read_text())


def _digest(value):
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _contract_points():
    return [
        _point(),
        _point(
            point_id="greenway:2:exit:EB",
            source_node_id="2",
            point_type="exit",
            label="Exit 2 - Battlefield Parkway",
            aliases=["Battlefield Parkway"],
        ),
    ]


def _renderer_contract():
    points = _contract_points()
    values = toll_agent._render_system_prompt_values(
        points, current_date=date(2026, 8, 21)
    )
    assert values["PROMPT_POINTS_JSON"].index(points[0]["point_id"]) < values[
        "PROMPT_POINTS_JSON"
    ].index(points[1]["point_id"])
    return {
        "inputSchema": toll_agent._PROMPT_POINTS_ADAPTER.json_schema(mode="validation"),
        "renderedValues": values,
    }


def test_prompt_point_validation_requires_unique_ordered_bounded_coordinates():
    assert toll_agent.parse_prompt_points([_point()])[0].point_id.endswith("entry:EB")

    with pytest.raises(ValueError, match="strictly ordered"):
        toll_agent.parse_prompt_points([_point(point_id="z"), _point(point_id="a")])
    with pytest.raises(ValueError, match="strictly ordered"):
        toll_agent.parse_prompt_points([_point(), _point()])
    with pytest.raises(ValidationError):
        toll_agent.parse_prompt_points(
            [_point(location={"type": "Point", "coordinates": [-181, 39]})]
        )
    with pytest.raises(ValidationError):
        toll_agent.parse_prompt_points(
            [_point(point_id=f"point-{i:03}") for i in range(501)]
        )


def test_prompt_point_loader_uses_one_bounded_query_and_closes(monkeypatch):
    rows = [{"points": [_point()]}]

    class Cursor:
        def execute(self, sql):
            executed.append(sql)

        def fetchall(self):
            return rows

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    cursor = Cursor()

    class Connection:
        closed = False

        def cursor(self):
            return cursor

        def close(self):
            self.closed = True

    executed = []
    connection = Connection()
    monkeypatch.setattr(
        toll_agent.route_validation, "connect_to_database", lambda: connection
    )

    assert toll_agent.load_prompt_points()[0].label.startswith("Exit 1")
    assert executed == ["SELECT oracle.get_toll_route_prompt_points() AS points"]
    assert connection.closed


def test_prompt_point_loader_fails_closed_and_still_closes(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, _sql):
            raise RuntimeError("database unavailable")

    class Connection:
        closed = False

        def cursor(self):
            return Cursor()

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(
        toll_agent.route_validation, "connect_to_database", lambda: connection
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        toll_agent.load_prompt_points()
    assert connection.closed


def test_system_prompt_contains_rds_points_and_v2_behavior():
    prompt = build_system_prompt([_point()], current_date=date(2026, 8, 21))
    normalized = " ".join(prompt.split())

    assert '"point_id": "greenway:1:entry:EB"' in prompt
    assert '"coordinates"' in prompt
    assert "get_current_toll_price" in prompt
    assert "get_annual_toll_ballpark" in prompt
    assert "exactly two registered tools" in prompt
    assert "present only the alternatives returned by the tool" in normalized
    assert "Never silently substitute an alternative" in normalized
    assert "reverse the outbound endpoints" in normalized
    assert "outbound departure time, return departure time, weekdays" in normalized
    assert "gross annual income" in normalized
    assert "toll-commute affordability assistant" in normalized
    assert "tolled portion only" in normalized
    assert "straight-line" in normalized
    assert "$0.685" in prompt
    assert "one-third" in normalized
    assert "annualized daily-P50 toll scenario" in normalized
    assert "both its daily and annual toll amounts" in normalized
    assert "P50 annual toll" not in normalized
    assert "fixed TollChat vehicle-cost assumption" in normalized
    assert "AAA" not in prompt
    assert "P50" in prompt and "P25" in prompt and "P90" in prompt
    assert "Markdown table" in normalized
    assert "bold" in normalized and "emoji" in normalized
    assert "Additional gross salary needed to offset" in normalized
    assert "HOV" not in prompt
    assert 'ask exactly "**🛣️ Do you mean I-66 or I-395?**"' in normalized
    assert "Washington D.C. I-66" in normalized
    assert "Washington D.C. I-95/I-395 Northbound" in normalized
    assert "Washington D.C. from I-495 Southbound via I-395" in normalized
    assert "Washington D.C. I-395 Southbound" in normalized
    assert "required-input acquisition takes precedence" in normalized
    assert "one corrective retry" in normalized
    assert "Never make a third call" in normalized
    assert "exact point_id returned in that alternative" in normalized
    assert "use the required endpoint role as the tie-breaker" in normalized
    assert "MUST immediately make one corrective retry" in normalized
    assert "prices only the current toll" in normalized
    assert "offer to check the current toll" in normalized
    assert "not affiliated with, endorsed by, or acting for VDOT" in normalized
    assert "Every user-facing response MUST use Markdown" in normalized
    assert "include at least one relevant emoji" in normalized
    assert "### 🚧 Express Lanes unavailable" in prompt
    assert "h:MM AM/PM EST or EDT" in prompt
    assert "9:30 AM EDT" in prompt
    assert "9:30 AM EST" in prompt
    assert "actual zone abbreviation" in normalized
    assert "preserve that timestamp's clock time" in normalized
    assert "use the literal `EST` suffix year-round" not in normalized
    assert "For every observed or modeled component" in normalized
    assert "recent_movement" in prompt
    assert "net_change_usd" in prompt
    assert "unchanged component must still show its `$0.00` net change" in normalized
    assert "`rising`: 📈" in prompt
    assert "`falling`: 📉" in prompt
    assert "`unchanged`: ➡️" in prompt
    assert "`mixed`: 🔄" in prompt
    assert "prior_week_comparison" in prompt
    assert "lower than, equal to, or higher than" in normalized
    assert "⚠️ Higher than the recent median" in prompt
    assert "🎉 You're getting a deal — below the recent median" in prompt
    assert "✅ At the recent median" in prompt
    assert "typical recent price only when all 3 of 3" in normalized
    assert "Never combine component comparisons" in normalized
    assert "omit that comparison" in normalized
    assert "data is stale or too old to use" in normalized
    assert "Do not state an observation's age" in normalized
    assert "I-95 closure fallback offer" in prompt
    assert "`fallback_required` is `true`" in normalized
    assert "`i95_opposite_direction_open` or `i95_fully_closed`" in normalized
    assert "I-495 Express northbound start at I-95 (TP1NB)" in normalized
    assert "I-495 Express southbound end at I-95 (TP1SB)" in normalized
    assert "Wait for the user to accept the offer" in normalized
    assert "preserve the original other endpoint and pricing profile" in normalized
    assert "general-purpose lanes and is not included" in normalized
    assert "Do not offer this fallback for `unknown`" in normalized
    assert "Reagan Airport or a southbound I-395 entry" in normalized
    assert "select `i495:1859ND`" in normalized
    assert "select `i95:206NO` as the origin. Westpark Drive uses `i495:185ND`" in (
        normalized
    )
    assert "Jones Branch/Route 123 uses `i495:183ND`" in normalized
    assert "Route 7 uses `i495:186ND`" in normalized
    assert "Westpark uses `i495:185SO`" in normalized
    assert "Jones Branch/Route 123 uses `i495:183SO`" in normalized
    assert "Route 7 uses `i495:186SO`" in normalized
    assert "i95_northbound_requires_i495_restart" in normalized
    assert "suggested_destination_point_id" in normalized
    assert "`prefix` with boundary `i495:192NO`" in normalized
    assert "`suffix` with boundary `i495:192SD`" in normalized
    assert "qualifying accepted I-95 fallback" in normalized
    assert "Today in America/New_York is 8/21/2026" in normalized
    assert "final roadside sign" not in normalized
    assert "30 minutes" not in normalized
    assert "maximum_observation_age_minutes" not in prompt
    assert "plan_toll_route" not in prompt
    assert "i95_route" not in prompt


def test_system_prompt_matches_its_versioned_contract():
    manifest = _contract_manifest()
    prompt_contract = manifest["system_prompt"]
    renderer_contract = manifest["system_prompt_renderer"]

    assert toll_agent.SYSTEM_PROMPT_VERSION == "2.0.0" == prompt_contract["current"]
    assert (
        toll_agent.SYSTEM_PROMPT_RENDERER_VERSION
        == "1.0.0"
        == renderer_contract["current"]
    )
    for contract in manifest.values():
        assert all(_SEMVER.fullmatch(release) for release in contract["releases"])
        assert all(
            re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in contract["releases"].values()
        )
    prompt = build_system_prompt(_contract_points(), current_date=date(2026, 8, 21))
    assert (
        hashlib.sha256(prompt.encode()).hexdigest()
        == (prompt_contract["releases"][prompt_contract["current"]])
    )
    assert (
        _digest(_renderer_contract())
        == (renderer_contract["releases"][renderer_contract["current"]])
    )


def test_system_prompt_manifest_accepts_one_monotonic_release():
    previous = _contract_manifest()
    current = copy.deepcopy(previous)
    current["system_prompt"]["current"] = "2.1.0"
    current["system_prompt"]["releases"]["2.1.0"] = "a" * 64

    version_check.validate_manifest_update(previous, current)
    version_check.validate_manifest_update({}, previous)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda manifest: manifest["system_prompt"].update(
                {"current": "version-one"}
            ),
            "invalid semantic version",
        ),
        (
            lambda manifest: manifest["system_prompt"]["releases"].update(
                {"1.0.0": "not-a-digest"}
            ),
            "invalid SHA-256",
        ),
        (
            lambda manifest: manifest["system_prompt"]["releases"].update(
                {"0.9.0": "b" * 64}
            ),
            "without advancing current",
        ),
        (
            lambda manifest: manifest["system_prompt"].update({"current": "0.9.0"}),
            "current release 0.9.0 is missing",
        ),
    ],
)
def test_system_prompt_manifest_rejects_invalid_contract(mutate, message):
    previous = _contract_manifest()
    current = copy.deepcopy(previous)
    mutate(current)
    with pytest.raises(ValueError, match=message):
        version_check.validate_manifest_update(previous, current)


def test_system_prompt_manifest_rejects_rewrites_removals_and_extra_releases():
    previous = _contract_manifest()

    rewritten = copy.deepcopy(previous)
    rewritten["system_prompt"]["releases"]["1.0.0"] = "b" * 64
    with pytest.raises(ValueError, match=r"rewrites system_prompt release 1\.0\.0"):
        version_check.validate_manifest_update(previous, rewritten)

    with pytest.raises(ValueError, match="removes contracts: system_prompt"):
        version_check.validate_manifest_update(previous, {})

    advanced = copy.deepcopy(previous)
    advanced["system_prompt"]["current"] = "2.2.0"
    advanced["system_prompt"]["releases"].update({"2.1.0": "b" * 64, "2.2.0": "c" * 64})
    with pytest.raises(ValueError, match="exactly the new current release"):
        version_check.validate_manifest_update(previous, advanced)


def _before_tool(invocation_state, call_id="one", arguments=None):
    return BeforeToolCallEvent(
        agent=cast(Any, object()),
        selected_tool=None,
        tool_use={
            "toolUseId": call_id,
            "name": "get_current_toll_price",
            "input": arguments or {"origin_point_id": "a", "destination_point_id": "b"},
        },
        invocation_state=invocation_state,
    )


def _after_tool(before, status="success"):
    return AfterToolCallEvent(
        agent=before.agent,
        selected_tool=None,
        tool_use=before.tool_use,
        invocation_state=before.invocation_state,
        result=cast(
            Any,
            {
                "toolUseId": before.tool_use["toolUseId"],
                "status": status,
                "content": [{"text": "result"}],
            },
        ),
    )


def test_duplicate_tool_guard_suppresses_only_successful_exact_repeats():
    guard = DuplicateToolUseGuard()
    state = {}
    guard.before_invocation(
        BeforeInvocationEvent(agent=cast(Any, object()), invocation_state=state)
    )

    first = _before_tool(state)
    guard.before_tool(first)
    guard.after_tool(_after_tool(first))
    repeated = _before_tool(state, call_id="two")
    guard.before_tool(repeated)
    changed = _before_tool(state, call_id="three", arguments={"origin_point_id": "c"})
    guard.before_tool(changed)

    assert repeated.cancel_tool == toll_agent._DUPLICATE_TOOL_MESSAGE
    assert changed.cancel_tool is False


def test_agent_registers_exactly_the_two_existing_tools(monkeypatch):
    model = OpenAIResponsesModel(model_id="test", client_args={"api_key": "test"})
    monkeypatch.setattr(toll_agent, "_build_model", lambda: model)
    original_specs = [
        json.loads(json.dumps(current_tool.TOOL_SPEC)),
        json.loads(json.dumps(ballpark_tool.TOOL_SPEC)),
    ]
    agent = build_agent(
        prompt_points=[_point()],
        trace_attributes={
            "tollchat.session_id": "test",
            "tollchat.system_prompt_version": "wrong",
            "tollchat.system_prompt_renderer_version": "wrong",
            "tollchat.system_prompt_sha256": "wrong",
        },
    )

    assert [spec["name"] for spec in agent.tool_registry.get_all_tool_specs()] == [
        "get_current_toll_price",
        "get_annual_toll_ballpark",
    ]
    assert original_specs[0] == current_tool.TOOL_SPEC
    assert original_specs[1] == ballpark_tool.TOOL_SPEC
    assert isinstance(agent.system_prompt, str)
    assert agent.trace_attributes == {
        "tollchat.session_id": "test",
        "tollchat.system_prompt_version": toll_agent.SYSTEM_PROMPT_VERSION,
        "tollchat.system_prompt_renderer_version": (
            toll_agent.SYSTEM_PROMPT_RENDERER_VERSION
        ),
        "tollchat.system_prompt_sha256": hashlib.sha256(
            agent.system_prompt.encode()
        ).hexdigest(),
    }


def test_agent_uses_luna_ssm_and_explicit_prompt_cache(monkeypatch):
    calls = []

    class Ssm:
        def get_parameter(self, **kwargs):
            calls.append(kwargs)
            return {"Parameter": {"Value": "test-key"}}

    monkeypatch.setattr(
        toll_agent.boto3,
        "client",
        lambda service_name, region_name: Ssm(),
    )
    model = toll_agent._build_model()
    request = model._format_request(
        messages=[{"role": "user", "content": [{"text": "price this"}]}],
        tool_specs=[],
        system_prompt="developer prompt",
    )

    assert calls == [{"Name": "/nova-toll/openai_api_key", "WithDecryption": True}]
    assert model.get_config().get("model_id") == "gpt-5.6-luna"
    assert request["prompt_cache_key"] == "tollchat-agent-v2"
    assert request["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert request["input"][0]["content"][0]["text"] == "developer prompt"
    assert "test-key" not in json.dumps(request)


def test_agent_normalizes_positive_prompt_cache_metrics_only():
    model = toll_agent._CachedResponsesModel(
        model_id="test", client_args={"api_key": "test"}
    )
    event = {
        "chunk_type": "metadata",
        "data": SimpleNamespace(
            input_tokens=1000,
            output_tokens=20,
            total_tokens=1020,
            input_tokens_details=SimpleNamespace(
                cached_tokens=700,
                cache_write_tokens=300,
            ),
        ),
    }

    usage = cast(Any, model._format_chunk(event))["metadata"]["usage"]

    assert usage["cacheReadInputTokens"] == 700
    assert usage["cacheWriteInputTokens"] == 300

    event["data"].input_tokens_details = SimpleNamespace(
        cached_tokens=0,
        cache_write_tokens=0,
    )
    usage = cast(Any, model._format_chunk(event))["metadata"]["usage"]

    assert "cacheReadInputTokens" not in usage
    assert "cacheWriteInputTokens" not in usage


def test_empty_ssm_parameter_is_rejected(monkeypatch):
    client = SimpleNamespace(get_parameter=lambda **_: {"Parameter": {"Value": ""}})
    monkeypatch.setattr(toll_agent.boto3, "client", lambda *_args, **_kwargs: client)
    with pytest.raises(ValueError, match="is empty"):
        toll_agent.load_openai_api_key()

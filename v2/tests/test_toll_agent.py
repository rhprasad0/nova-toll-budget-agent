"""Prompt, database-loader, and Strands wiring tests without network calls."""

import copy
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self, TypedDict, cast
from zoneinfo import ZoneInfo

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


class Release(TypedDict):
    current: str
    releases: dict[str, str]


_CONTRACT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "agent" / "contract-manifest.json"
)
_SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def _point(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
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


def _contract_manifest() -> dict[str, Release]:
    return json.loads(_CONTRACT_MANIFEST_PATH.read_text())


def _digest(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _contract_points() -> list[dict[str, object]]:
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


def _renderer_contract() -> dict[str, object]:
    points = _contract_points()
    values = toll_agent._render_system_prompt_values(
        points, current_date=date(2026, 8, 21)
    )
    assert values["PROMPT_POINTS_JSON"].index(
        cast(str, points[0]["point_id"])
    ) < values["PROMPT_POINTS_JSON"].index(cast(str, points[1]["point_id"]))
    return {
        "inputSchema": toll_agent._PROMPT_POINTS_ADAPTER.json_schema(mode="validation"),
        "renderedValues": values,
    }


def test_prompt_point_validation_requires_unique_ordered_bounded_coordinates() -> None:
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


def test_prompt_point_loader_uses_one_bounded_query_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [{"points": [_point()]}]

    class Cursor:
        def execute(self, sql: str) -> None:
            executed.append(sql)

        def fetchall(self) -> list[dict[str, list[dict[str, object]]]]:
            return rows

        def __enter__(self) -> "Self":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    cursor = Cursor()

    class Connection:
        closed = False

        def cursor(self) -> "Cursor":
            return cursor

        def close(self) -> None:
            self.closed = True

    executed: list[str] = []
    connection = Connection()
    monkeypatch.setattr(
        toll_agent.route_validation, "connect_to_database", lambda: connection
    )

    assert toll_agent.load_prompt_points()[0].label.startswith("Exit 1")
    assert executed == ["SELECT oracle.get_toll_route_prompt_points() AS points"]
    assert connection.closed


def test_prompt_point_loader_fails_closed_and_still_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __enter__(self) -> "Self":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            raise RuntimeError("database unavailable")

    class Connection:
        closed = False

        def cursor(self) -> "Cursor":
            return Cursor()

        def close(self) -> None:
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(
        toll_agent.route_validation, "connect_to_database", lambda: connection
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        toll_agent.load_prompt_points()
    assert connection.closed


def test_system_prompt_renders_explicit_catalog_and_date_without_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        toll_agent,
        "load_prompt_points",
        lambda: pytest.fail("explicit catalog must not load RDS"),
    )
    point = _point(label='Exit "Leesburg" — café 🛣️')

    prompt = build_system_prompt([point], current_date=date(2026, 8, 21))
    catalog = json.loads(prompt.rsplit("```json\n", 1)[1].split("\n```", 1)[0])

    assert len(catalog) == 1
    assert {key: catalog[0][key] for key in point} == point
    assert prompt.count('"point_id": "greenway:1:entry:EB"') == 1
    assert "8/21/2026" in prompt
    assert "{CURRENT_DATE}" not in prompt
    assert "{PROMPT_POINTS_JSON}" not in prompt


def test_system_prompt_loads_catalog_once_and_uses_new_york_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    points = [_point()]
    calls = 0

    def load_points() -> object:
        nonlocal calls
        calls += 1
        return toll_agent.parse_prompt_points(points)

    def now(tz: ZoneInfo) -> datetime:
        assert tz.key == "America/New_York"
        return datetime(2027, 1, 1, 4, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(toll_agent, "load_prompt_points", load_points)
    monkeypatch.setattr(toll_agent, "datetime", SimpleNamespace(now=now))

    prompt = build_system_prompt()
    catalog = json.loads(prompt.rsplit("```json\n", 1)[1].split("\n```", 1)[0])

    assert calls == 1
    assert {key: catalog[0][key] for key in points[0]} == points[0]
    assert "12/31/2026" in prompt
    assert "{CURRENT_DATE}" not in prompt
    assert "{PROMPT_POINTS_JSON}" not in prompt


def test_system_prompt_matches_its_versioned_contract() -> None:
    manifest = _contract_manifest()
    prompt_contract = manifest["system_prompt"]
    renderer_contract = manifest["system_prompt_renderer"]

    assert toll_agent.SYSTEM_PROMPT_VERSION == "2.3.15" == prompt_contract["current"]
    assert (
        toll_agent.SYSTEM_PROMPT_RENDERER_VERSION
        == "1.0.2"
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


def test_system_prompt_manifest_accepts_one_monotonic_release() -> None:
    previous = _contract_manifest()
    current = copy.deepcopy(previous)
    current["system_prompt"]["current"] = "2.4.0"
    current["system_prompt"]["releases"]["2.4.0"] = "a" * 64

    version_check.validate_manifest_update(previous, current)
    version_check.validate_manifest_update({}, previous)


def _callback_2(manifest: dict[str, Release]) -> object:
    return manifest["system_prompt"].update({"current": "version-one"})


def _callback_3(manifest: dict[str, Release]) -> object:
    return manifest["system_prompt"]["releases"].update({"1.0.0": "not-a-digest"})


def _callback_4(manifest: dict[str, Release]) -> object:
    return manifest["system_prompt"]["releases"].update({"0.9.0": "b" * 64})


def _strict_callback_2(manifest: dict[str, Release]) -> object:
    return manifest["system_prompt"].update({"current": "0.9.0"})


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            _callback_2,
            "invalid semantic version",
        ),
        (
            _callback_3,
            "invalid SHA-256",
        ),
        (
            _callback_4,
            "without advancing current",
        ),
        (
            _strict_callback_2,
            "current release 0.9.0 is missing",
        ),
    ],
)
def test_system_prompt_manifest_rejects_invalid_contract(
    mutate: Callable[[dict[str, Release]], object], message: str
) -> None:
    previous = _contract_manifest()
    current = copy.deepcopy(previous)
    mutate(current)
    with pytest.raises(ValueError, match=message):
        version_check.validate_manifest_update(previous, current)


def test_system_prompt_manifest_rejects_rewrites_and_removals() -> None:
    previous = _contract_manifest()

    rewritten = copy.deepcopy(previous)
    rewritten["system_prompt"]["releases"]["1.0.0"] = "b" * 64
    with pytest.raises(ValueError, match=r"rewrites system_prompt release 1\.0\.0"):
        version_check.validate_manifest_update(previous, rewritten)

    with pytest.raises(ValueError, match="removes contracts: system_prompt"):
        version_check.validate_manifest_update(previous, {})


def test_system_prompt_manifest_accepts_multiple_forward_releases() -> None:
    previous = _contract_manifest()
    advanced = copy.deepcopy(previous)
    advanced["system_prompt"]["current"] = "2.5.0"
    advanced["system_prompt"]["releases"].update({"2.4.0": "b" * 64, "2.5.0": "c" * 64})
    version_check.validate_manifest_update(previous, advanced)


def _before_tool(
    invocation_state: dict[str, object],
    call_id: str = "one",
    arguments: dict[str, str] | None = None,
) -> BeforeToolCallEvent:
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


def _after_tool(
    before: BeforeToolCallEvent, status: str = "success"
) -> AfterToolCallEvent:
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


def test_duplicate_tool_guard_suppresses_only_successful_exact_repeats() -> None:
    guard = DuplicateToolUseGuard()
    state: dict[str, object] = {}
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


def test_agent_registers_exactly_the_two_existing_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = OpenAIResponsesModel(model_id="test", client_args={"api_key": "test"})
    monkeypatch.setattr(toll_agent, "_build_model", lambda: model)
    original_specs = [
        json.loads(json.dumps(current_tool.TOOL_SPEC)),
        json.loads(json.dumps(ballpark_tool.TOOL_SPEC)),
    ]
    agent = build_agent(prompt_points=[_point()])

    assert [spec["name"] for spec in agent.tool_registry.get_all_tool_specs()] == [
        "get_current_toll_price",
        "get_annual_toll_ballpark",
    ]
    assert original_specs[0] == current_tool.TOOL_SPEC
    assert original_specs[1] == ballpark_tool.TOOL_SPEC
    assert isinstance(agent.system_prompt, str)
    assert "trace_attributes" not in inspect.signature(build_agent).parameters
    assert agent.trace_attributes == {
        "tollchat.system_prompt_version": toll_agent.SYSTEM_PROMPT_VERSION,
        "tollchat.system_prompt_renderer_version": (
            toll_agent.SYSTEM_PROMPT_RENDERER_VERSION
        ),
        "tollchat.system_prompt_sha256": hashlib.sha256(
            agent.system_prompt.encode()
        ).hexdigest(),
    }


def test_agent_uses_luna_ssm_and_explicit_prompt_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Ssm:
        def get_parameter(self, **kwargs: object) -> dict[str, dict[str, str]]:
            calls.append(kwargs)
            return {"Parameter": {"Value": "test-key"}}

    def _strict_callback_1(service_name: object, region_name: object) -> object:
        return Ssm()

    monkeypatch.setattr(
        toll_agent.boto3,
        "client",
        _strict_callback_1,
    )
    model = toll_agent._build_model()
    # The pinned SDK exposes request serialization only through this protected hook.
    request = model._format_request(  # pyright: ignore[reportPrivateUsage]
        messages=[
            {"role": "user", "content": [{"text": "price this"}]},
            {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": "get_annual_toll_ballpark",
                            "input": {"gross_annual_income_usd": "130000.00"},
                        }
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "tool-1",
                            "status": "success",
                            "content": [{"json": {"remaining_income_usd": "78824.40"}}],
                        }
                    }
                ],
            },
        ],
        tool_specs=[],
        system_prompt="developer prompt",
        model_state={"response_id": "response-before-tool-output"},
    )

    assert calls == [{"Name": "/nova-toll/openai_api_key", "WithDecryption": True}]
    assert model.get_config().get("model_id") == "gpt-6-luna"
    assert request["prompt_cache_key"] == "tollchat-agent-v2"
    assert request["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert request["store"] is False
    assert "previous_response_id" not in request
    assert [
        item["type"]
        for item in request["input"]
        if item.get("type") in {"function_call", "function_call_output"}
    ] == ["function_call", "function_call_output"]
    assert request["input"][0]["content"][0]["text"] == "developer prompt"
    assert "test-key" not in json.dumps(request)


def test_agent_normalizes_positive_prompt_cache_metrics_only() -> None:
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

    # Exercise the pinned SDK chunk hook used by our cache metrics override.
    usage = cast(Any, model._format_chunk(event))["metadata"]["usage"]  # pyright: ignore[reportPrivateUsage]

    assert usage["cacheReadInputTokens"] == 700
    assert usage["cacheWriteInputTokens"] == 300

    cast(SimpleNamespace, event["data"]).input_tokens_details = SimpleNamespace(
        cached_tokens=0,
        cache_write_tokens=0,
    )
    # Exercise the pinned SDK chunk hook used by our cache metrics override.
    usage = cast(Any, model._format_chunk(event))["metadata"]["usage"]  # pyright: ignore[reportPrivateUsage]

    assert "cacheReadInputTokens" not in usage
    assert "cacheWriteInputTokens" not in usage


def test_empty_ssm_parameter_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def _strict_callback_3(**_: object) -> object:
        return {"Parameter": {"Value": ""}}

    client = SimpleNamespace(get_parameter=_strict_callback_3)

    def _callback_1(*_args: object, **_kwargs: object) -> object:
        return client

    monkeypatch.setattr(toll_agent.boto3, "client", _callback_1)
    with pytest.raises(ValueError, match="is empty"):
        toll_agent.load_openai_api_key()

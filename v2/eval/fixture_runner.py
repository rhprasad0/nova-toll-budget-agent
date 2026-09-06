# pyright: basic
"""Trusted recorded-fixture execution boundary for annual eval cases.

This module deliberately contains no live tool fallback.  A trusted caller supplies
the model, prompt context, render date, and rate card; the two production tool
contracts are always represented by local ``AgentTool`` wrappers.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import BeforeToolsEvent
from strands.types.tools import AgentTool, ToolGenerator, ToolResult, ToolSpec, ToolUse

from agent.toll_agent import build_agent
from agent_tools.get_annual_toll_ballpark import get_annual_toll_ballpark
from agent_tools.get_current_toll_price import get_current_toll_price

_TOOL_SPECS = {
    "get_current_toll_price": cast(ToolSpec, get_current_toll_price.tool_spec),
    "get_annual_toll_ballpark": cast(ToolSpec, get_annual_toll_ballpark.tool_spec),
}

_SCRIPT_STATE_KEY = "tollchat_v2_fixture_script_assignments"


class _FixtureScriptCursor:
    """Assign emitted tool-use blocks before native concurrent dispatch."""

    def __init__(
        self,
        script: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]],
    ) -> None:
        self.script = tuple(deepcopy(dict(step)) for step in script)
        self.evidence = {str(item["id"]): deepcopy(dict(item)) for item in evidence}
        self.turn = 0
        self._turn_sequence = 0
        self._consumed: dict[int, int] = {}
        self.assignments: dict[str, dict[str, Any]] = {}
        self.call_ids: set[str] = set()
        self._observed_message_ids: set[int] = set()

    def begin_turn(self, turn: int) -> None:
        self.turn = turn
        self._turn_sequence = 0

    def assign_message(self, message: object) -> dict[str, dict[str, Any]]:
        if not isinstance(message, dict) or type(message.get("content")) is not list:
            return {}
        message_id = id(message)
        repeated_message = message_id in self._observed_message_ids
        self._observed_message_ids.add(message_id)
        for block in message["content"]:
            if not isinstance(block, dict) or not isinstance(
                block.get("toolUse"), dict
            ):
                continue
            tool_use = cast(dict[str, Any], block["toolUse"])
            tool_id = tool_use.get("toolUseId")
            key = str(tool_id) if isinstance(tool_id, str) and tool_id else "<missing>"
            if key in self.assignments and repeated_message:
                continue
            assignment: dict[str, Any] = {
                "turn": self.turn,
                "sequence": self._turn_sequence,
                "step_index": None,
                "error": None,
            }
            self._turn_sequence += 1
            if key == "<missing>" or key in self.call_ids:
                assignment["error"] = "tool-use ID is missing or duplicated"
                self.assignments[key] = assignment
                continue
            self.call_ids.add(key)
            expected_indices = [
                index
                for index, step in enumerate(self.script)
                if step.get("turn") == self.turn
            ]
            consumed = self._consumed.get(self.turn, 0)
            if consumed >= len(expected_indices):
                assignment["error"] = "no authored fixture step remains for this turn"
            else:
                step_index = expected_indices[consumed]
                step = self.script[step_index]
                if step.get("tool") != tool_use.get("name") or step.get(
                    "request"
                ) != tool_use.get("input"):
                    assignment["error"] = "tool call does not match authored order"
                else:
                    assignment["step_index"] = step_index
                    self._consumed[self.turn] = consumed + 1
            self.assignments[key] = assignment
        return self.assignments


class _FixtureScriptHook(HookProvider):
    def __init__(self, cursor: _FixtureScriptCursor) -> None:
        self.cursor = cursor

    def register_hooks(self, registry: HookRegistry, **_kwargs: object) -> None:
        registry.add_callback(BeforeToolsEvent, self.before_tools)

    def before_tools(self, event: BeforeToolsEvent) -> None:
        event.invocation_state[_SCRIPT_STATE_KEY] = self.cursor.assign_message(
            event.message
        )


class FixtureAgentTool(AgentTool):
    """An ``AgentTool`` that returns one validated recorded payload.

    ``expected_input`` is intentionally the fixture request rather than case
    rubric metadata.  Every call is retained for the trajectory and a mismatch
    produces a tool error, so the agent cannot reach a production implementation.
    """

    def __init__(
        self,
        tool_spec: ToolSpec,
        *,
        fixture_id: str | None,
        expected_input: Mapping[str, Any] | None,
        payload: Mapping[str, Any] | None,
        error_payload: Mapping[str, Any] | None = None,
        cursor: _FixtureScriptCursor | None = None,
        evidence: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._spec = cast(ToolSpec, deepcopy(tool_spec))
        self.fixture_id = fixture_id
        self.expected_input = deepcopy(dict(expected_input)) if expected_input else None
        self.payload = deepcopy(dict(payload)) if payload else None
        self.error_payload = deepcopy(dict(error_payload)) if error_payload else None
        self.cursor = cursor
        self.evidence = evidence or {}
        self.calls: list[dict[str, Any]] = []

    @property
    def tool_name(self) -> str:
        return self._spec["name"]

    @property
    def tool_spec(self) -> ToolSpec:
        return self._spec

    @property
    def tool_type(self) -> str:
        return "python"

    def _record(
        self,
        tool_use: ToolUse,
        *,
        error: str | None,
        expected_error: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        tool_use_id = tool_use.get("toolUseId")
        name = tool_use.get("name")
        inputs = deepcopy(tool_use.get("input"))
        call = {"name": name, "input": inputs, "toolUseId": tool_use_id}
        if error:
            call["is_error"] = True
            call["error"] = error
            if expected_error is not None:
                call["tool_error"] = deepcopy(dict(expected_error))
        else:
            call["is_error"] = False
            call["tool_result"] = deepcopy(self.payload)
        self.calls.append(call)
        if expected_error is not None:
            result = deepcopy(dict(expected_error))
            result["toolUseId"] = str(tool_use.get("toolUseId"))
            return cast(ToolResult, result)
        content = [{"text": error}] if error else [{"json": deepcopy(self.payload)}]
        return cast(
            ToolResult,
            {
                "toolUseId": str(tool_use_id),
                "status": "error" if error else "success",
                "content": content,
            },
        )

    async def stream(
        self, tool_use: ToolUse, invocation_state: dict[str, Any], **_kwargs: object
    ) -> ToolGenerator:
        assignment: dict[str, Any] | None = None
        if self.cursor is not None:
            assignments = invocation_state.get(_SCRIPT_STATE_KEY)
            if isinstance(assignments, Mapping):
                candidate = assignments.get(str(tool_use.get("toolUseId")))
                if isinstance(candidate, Mapping):
                    assignment = cast(dict[str, Any], candidate)
        error: str | None = None
        expected_error: Mapping[str, Any] | None = None
        evidence: Mapping[str, Any] | None = None
        if self.cursor is not None:
            if assignment is None:
                error = "tool call was not assigned by the fixture script"
            elif assignment.get("error"):
                error = str(assignment["error"])
            else:
                step_index = assignment.get("step_index")
                if (
                    type(step_index) is not int
                    or step_index < 0
                    or step_index >= len(self.cursor.script)
                ):
                    error = "fixture script assignment is invalid"
                else:
                    step = self.cursor.script[step_index]
                    evidence = self.cursor.evidence.get(str(step["fixture_id"]))
                    if evidence is None or step.get("tool") != self.tool_name:
                        error = "tool does not match authored fixture step"
                    elif tool_use.get("input") != step.get("request"):
                        error = "recorded fixture input mismatch"
                    elif evidence.get("error") is not None:
                        expected_error = cast(Mapping[str, Any], evidence["error"])
                        content = expected_error.get("content")
                        error = (
                            str(content[0].get("text"))
                            if isinstance(content, list)
                            and content
                            and isinstance(content[0], Mapping)
                            and isinstance(content[0].get("text"), str)
                            else "recorded fixture returned its authored error"
                        )
                    elif evidence.get("result") is None:
                        error = "recorded fixture payload is unavailable"
                    else:
                        self.payload = cast(Mapping[str, Any], evidence["result"])
        if self.cursor is None:
            if self.expected_input is None:
                error = "recorded fixture denies this tool call"
            elif tool_use.get("input") != self.expected_input:
                error = "recorded fixture input mismatch"
            elif self.error_payload is not None:
                expected_error = self.error_payload
                error = "recorded fixture returned its authored error"
            elif self.payload is None:
                error = "recorded fixture payload is unavailable"
        yield self._record(tool_use, error=error, expected_error=expected_error)


def fixture_tools(
    fixture_id: str | None = None,
    *,
    request: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
    error_payload: Mapping[str, Any] | None = None,
    script: Sequence[Mapping[str, Any]] | None = None,
    fixture_evidence: Sequence[Mapping[str, Any]] | None = None,
    cursor: _FixtureScriptCursor | None = None,
) -> list[FixtureAgentTool]:
    """Return both production contracts backed exclusively by fixture wrappers."""
    if script is not None or cursor is not None:
        evidence = {
            str(item["id"]): item
            for item in (fixture_evidence or ())
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        }
        return [
            FixtureAgentTool(
                _TOOL_SPECS[name],
                fixture_id=None,
                expected_input=None,
                payload=None,
                cursor=cursor,
                evidence=evidence,
            )
            for name in _TOOL_SPECS
        ]
    return [
        FixtureAgentTool(
            _TOOL_SPECS["get_current_toll_price"],
            fixture_id=fixture_id,
            expected_input=None,
            payload=None,
        ),
        FixtureAgentTool(
            _TOOL_SPECS["get_annual_toll_ballpark"],
            fixture_id=fixture_id,
            expected_input=request,
            payload=payload,
            error_payload=error_payload,
        ),
    ]


@dataclass(frozen=True)
class FixtureRunPacket:
    """Runner input assembled from the validated public corpus."""

    case_id: str
    prompt: str
    conversation: tuple[str, ...]
    fixture_id: str | None
    fixture_result_kind: str | None
    fixture_request: dict[str, Any] | None
    fixture_payload: dict[str, Any] | None
    fixture_bytes: bytes | None
    prompt_points: tuple[dict[str, Any], ...] | None
    render_date: date | None
    script: tuple[dict[str, Any], ...] = ()
    fixture_evidence: tuple[dict[str, Any], ...] = ()
    strict_usage: bool = False
    dataset_version: str = "1.0.0"


@dataclass(frozen=True)
class RateCard:
    source: str
    version: str
    digest: str
    input_rate_usd_per_million: float
    output_rate_usd_per_million: float
    cache_rate_usd_per_million: float
    cache_write_rate_usd_per_million: float | None = None
    long_context_threshold_tokens: int = 272_000
    long_context_input_multiplier: float = 2.0
    long_context_output_multiplier: float = 1.5

    def validate(self) -> None:
        if not self.source or not self.version or not isinstance(self.digest, str):
            raise ValueError("rate-card provenance is incomplete")
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("rate-card digest is invalid")
        cache_write_rate = (
            self.input_rate_usd_per_million * 1.25
            if self.cache_write_rate_usd_per_million is None
            else self.cache_write_rate_usd_per_million
        )
        rates = (
            self.input_rate_usd_per_million,
            self.output_rate_usd_per_million,
            self.cache_rate_usd_per_million,
            cache_write_rate,
            self.long_context_input_multiplier,
            self.long_context_output_multiplier,
        )
        if any(
            type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0
            for rate in rates
        ):
            raise ValueError("rate-card rates must be finite and non-negative")
        if type(self.long_context_threshold_tokens) is not int or (
            self.long_context_threshold_tokens <= 0
        ):
            raise ValueError("long-context threshold must be positive")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "source": self.source,
            "version": self.version,
            "digest": self.digest,
            "input_rate_usd_per_million": self.input_rate_usd_per_million,
            "output_rate_usd_per_million": self.output_rate_usd_per_million,
            "cache_rate_usd_per_million": self.cache_rate_usd_per_million,
            "cache_write_rate_usd_per_million": (
                self.input_rate_usd_per_million * 1.25
                if self.cache_write_rate_usd_per_million is None
                else self.cache_write_rate_usd_per_million
            ),
            "long_context_threshold_tokens": self.long_context_threshold_tokens,
            "long_context_input_multiplier": self.long_context_input_multiplier,
            "long_context_output_multiplier": self.long_context_output_multiplier,
        }


def _measurement(summary: object, *names: str) -> int | None:
    _present, value = _measurement_status(summary, *names)
    return value


def _measurement_status(summary: object, *names: str) -> tuple[bool, int | None]:
    """Return whether a named usage counter was present and its valid value."""

    if isinstance(summary, Mapping):
        for name in names:
            if name in summary:
                value = summary[name]
                if type(value) is int and value >= 0:
                    return True, value
                return True, None
        for value in summary.values():
            present, found = _measurement_status(value, *names)
            if present:
                return True, found
    elif isinstance(summary, Sequence) and not isinstance(summary, (str, bytes)):
        for value in summary:
            present, found = _measurement_status(value, *names)
            if present:
                return True, found
    return False, None


def _response_usage(response: object) -> Mapping[str, Any]:
    metrics = getattr(response, "metrics", None)
    invocations = getattr(metrics, "agent_invocations", None)
    if type(invocations) is not list or not invocations:
        return {}
    usage = getattr(invocations[-1], "usage", None)
    return usage if isinstance(usage, Mapping) else {}


def _response_cycle_usages(response: object) -> list[object] | None:
    metrics = getattr(response, "metrics", None)
    invocations = getattr(metrics, "agent_invocations", None)
    if type(invocations) is list and invocations:
        missing = object()
        cycles = getattr(invocations[-1], "cycles", missing)
        if cycles is not missing and cycles is not None:
            if type(cycles) is not list:
                return [None]
            return [getattr(cycle, "usage", None) for cycle in cycles]
    usage = _response_usage(response)
    return [usage] if usage else None


def _usage_record(usage: Mapping[str, Any]) -> dict[str, int]:
    total = _measurement(usage, "totalTokens", "total_tokens", "tokens")
    input_tokens = _measurement(usage, "inputTokens", "input_tokens")
    output_tokens = _measurement(usage, "outputTokens", "output_tokens")
    cache_read_present, cache_read = _measurement_status(
        usage, "cacheReadInputTokens", "cache_read_input_tokens"
    )
    cache_write_present, cache_write = _measurement_status(
        usage, "cacheWriteInputTokens", "cache_write_input_tokens"
    )
    # Strands omits zero-valued cache counters from some provider formatters.
    # They are optional usage buckets, so retain an explicit zero in the sealed
    # evidence while keeping total/input/output mandatory.
    if not cache_read_present:
        cache_read = 0
    if not cache_write_present:
        cache_write = 0
    if (cache_read_present and cache_read is None) or (
        cache_write_present and cache_write is None
    ):
        raise ValueError("cache usage counters must be non-negative integers")
    if None in (total, input_tokens, output_tokens, cache_read, cache_write):
        raise ValueError("complete model usage is required for every provider request")
    record = {
        "tokens": cast(int, total),
        "input_tokens": cast(int, input_tokens),
        "output_tokens": cast(int, output_tokens),
        "cache_tokens": cast(int, cache_read),
        "cache_write_tokens": cast(int, cache_write),
    }
    if record["tokens"] != record["input_tokens"] + record["output_tokens"]:
        raise ValueError("total token usage does not match input and output")
    if record["cache_tokens"] + record["cache_write_tokens"] > record["input_tokens"]:
        raise ValueError("cached input usage exceeds total input usage")
    return record


def _request_cost(
    record: Mapping[str, int], rates: Mapping[str, Any]
) -> dict[str, Any]:
    long_context = record["input_tokens"] > rates["long_context_threshold_tokens"]
    multiplier = rates["long_context_input_multiplier"] if long_context else 1.0
    output_multiplier = rates["long_context_output_multiplier"] if long_context else 1.0
    ordinary = (
        record["input_tokens"] - record["cache_tokens"] - record["cache_write_tokens"]
    )
    input_usd = ordinary * rates["input_rate_usd_per_million"] * multiplier / 1_000_000
    output_usd = (
        record["output_tokens"]
        * rates["output_rate_usd_per_million"]
        * output_multiplier
        / 1_000_000
    )
    cache_usd = (
        record["cache_tokens"]
        * rates["cache_rate_usd_per_million"]
        * multiplier
        / 1_000_000
    )
    cache_write_usd = (
        record["cache_write_tokens"]
        * rates["cache_write_rate_usd_per_million"]
        * multiplier
        / 1_000_000
    )
    return {
        **record,
        "ordinary_input_tokens": ordinary,
        "long_context": long_context,
        "input_usd": input_usd,
        "output_usd": output_usd,
        "cache_usd": cache_usd,
        "cache_write_usd": cache_write_usd,
        "total_usd": input_usd + output_usd + cache_usd + cache_write_usd,
    }


def _extract_calls(messages: object) -> list[dict[str, Any]]:
    """Project SDK message history into an ordered, lossless call trace.

    Tool wrappers retain successful fixture observations, but the SDK message
    history also records calls the registry rejects and calls that end without a
    result.  The latter is the runner's evidence of an attempted call and keeps
    the trusted grader from mistaking a partial trace for a clean run.
    """
    if type(messages) is not list:
        return [
            {
                "name": "<missing-message-history>",
                "input": None,
                "toolUseId": None,
                "is_error": True,
                "error": "agent message history is unavailable",
            }
        ]
    calls: list[dict[str, Any]] = []
    by_id: dict[str, int] = {}
    for message in messages:
        if type(message) is not dict or type(message.get("content")) is not list:
            continue
        for block in message["content"]:
            if type(block) is not dict:
                continue
            tool_use = block.get("toolUse")
            if type(tool_use) is dict:
                tool_id = tool_use.get("toolUseId")
                key = str(tool_id) if tool_id is not None else "<missing>"
                call: dict[str, Any] = {
                    "name": tool_use.get("name"),
                    "input": deepcopy(tool_use.get("input")),
                    "toolUseId": tool_id,
                    "is_error": True,
                    "error": "tool result is missing",
                }
                calls.append(call)
                by_id[key] = len(calls) - 1
                continue
            tool_result = block.get("toolResult")
            if type(tool_result) is not dict:
                continue
            tool_id = tool_result.get("toolUseId")
            index = by_id.get(str(tool_id))
            if index is None:
                calls.append(
                    {
                        "name": "<orphan-tool-result>",
                        "input": None,
                        "toolUseId": tool_id,
                        "is_error": True,
                        "error": "tool result has no preceding call",
                    }
                )
                continue
            call = calls[index]
            status = tool_result.get("status")
            if status == "success":
                contents = tool_result.get("content")
                if (
                    type(contents) is list
                    and len(contents) == 1
                    and type(contents[0]) is dict
                ):
                    if "json" in contents[0]:
                        call["tool_result"] = deepcopy(contents[0]["json"])
                    elif "text" in contents[0]:
                        call["tool_result"] = contents[0]["text"]
                    else:
                        call["is_error"] = True
                        call["error"] = "successful tool result has malformed content"
                        continue
                    call["resultToolUseId"] = tool_id
                    call["is_error"] = False
                    call.pop("error", None)
                else:
                    call["error"] = "successful tool result has malformed content"
            else:
                call["is_error"] = True
                call["tool_error"] = deepcopy(tool_result)
                error_content = tool_result.get("content")
                if (
                    type(error_content) is list
                    and error_content
                    and type(error_content[0]) is dict
                    and type(error_content[0].get("text")) is str
                ):
                    call["error"] = error_content[0]["text"]
                else:
                    call["error"] = "tool result returned an error"
                call["resultToolUseId"] = tool_id
    return calls


def _write_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("artifact output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2
            )
            + "\n"
        )


def write_raw_artifact(root: Path, record: Mapping[str, Any]) -> None:
    """Write untrusted observations; trusted sealing supplies ``run.json``."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "output.json", record["output"])
    with (root / "stdout.txt").open("x", encoding="utf-8") as handle:
        handle.write(str(record["stdout"]))
    _write_json(root / "exit_code.json", record["exit_code"])


def run_fixture_trial(
    packet: FixtureRunPacket,
    *,
    model: object,
    artifact_root: Path | None,
    trial_id: str,
    rate_card: RateCard | None,
) -> dict[str, Any]:
    """Run every packet turn through an injected model and write raw observations."""
    turns: list[dict[str, Any]] = []
    turn_measurements: list[dict[str, Any]] = []
    final_text = ""
    failure_class = "none"
    error_text: str | None = None
    tokens: int | None = None
    latency_ms: int | None = None
    cost: dict[str, Any] | None = None
    scripted = bool(packet.script or packet.fixture_evidence or packet.strict_usage)
    cursor = _FixtureScriptCursor(packet.script, packet.fixture_evidence)
    tools = (
        fixture_tools(
            script=packet.script,
            fixture_evidence=packet.fixture_evidence,
            cursor=cursor,
        )
        if scripted
        else fixture_tools(
            packet.fixture_id,
            request=packet.fixture_request,
            payload=packet.fixture_payload,
        )
    )
    try:
        if model is None:
            raise ValueError("fixture runner requires an injected model")
        if not packet.prompt_points or packet.render_date is None:
            raise ValueError("explicit prompt points and render date are required")
        if rate_card is None:
            raise ValueError("explicit rate-card provenance is required")
        rate_card.validate()
        agent = build_agent(
            model=cast(Any, model),
            tools=tools,
            prompt_points=list(packet.prompt_points),
            current_date=packet.render_date,
            hooks=[_FixtureScriptHook(cursor)] if scripted else None,
        )
        rates = rate_card.as_dict()
        request_costs: list[dict[str, Any]] = []
        for turn_index, prompt in enumerate(packet.conversation):
            cursor.begin_turn(turn_index)
            before_messages = len(getattr(agent, "messages", []))
            messages = getattr(agent, "messages", None)
            try:
                start_ns = time.perf_counter_ns()
                response = agent(prompt)
                elapsed_ns = time.perf_counter_ns() - start_ns
                final_text = str(response)
            except Exception:
                calls = _extract_calls(
                    messages[before_messages:]
                    if type(messages) is list and before_messages <= len(messages)
                    else None
                )
                turns.append({"prompt": prompt, "response": final_text, "calls": calls})
                raise
            messages = getattr(agent, "messages", None)
            calls = _extract_calls(
                messages[before_messages:]
                if type(messages) is list and before_messages <= len(messages)
                else None
            )
            assignments = cursor.assignments
            for call in calls:
                assignment = assignments.get(str(call.get("toolUseId")))
                if assignment is None:
                    call["assignment_error"] = "call was absent from the fixture hook"
                    continue
                call["script_turn"] = assignment["turn"]
                call["script_sequence"] = assignment["sequence"]
                call["script_step"] = assignment.get("step_index")
                if assignment.get("error"):
                    call["assignment_error"] = assignment["error"]
                elif assignment.get("step_index") is not None:
                    step = cursor.script[assignment["step_index"]]
                    call["fixture_id"] = step["fixture_id"]
            turns.append({"prompt": prompt, "response": final_text, "calls": calls})
            usages = _response_cycle_usages(response)
            if not usages:
                raise ValueError("complete model usage is required for every turn")
            if any(not isinstance(usage, Mapping) for usage in usages):
                raise ValueError("complete model usage is required for every cycle")
            turn_requests = [
                _request_cost(
                    _usage_record(cast(Mapping[str, Any], usage)),
                    rates,
                )
                for usage in usages
            ]
            request_costs.extend(turn_requests)
            turn_tokens = sum(item["tokens"] for item in turn_requests)
            input_tokens = sum(item["input_tokens"] for item in turn_requests)
            output_tokens = sum(item["output_tokens"] for item in turn_requests)
            cache_tokens = sum(item["cache_tokens"] for item in turn_requests)
            cache_write_tokens = sum(
                item["cache_write_tokens"] for item in turn_requests
            )
            turn_latency = max(1, (elapsed_ns + 999_999) // 1_000_000)
            turn_measurements.append(
                {
                    "tokens": turn_tokens,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_tokens": cache_tokens,
                    "cache_write_tokens": cache_write_tokens,
                    "latency_ms": turn_latency,
                    "requests": turn_requests,
                }
            )
        tokens = sum(item["tokens"] for item in turn_measurements)
        latency_ms = sum(item["latency_ms"] for item in turn_measurements)
        input_tokens = sum(item["input_tokens"] for item in turn_measurements)
        output_tokens = sum(item["output_tokens"] for item in turn_measurements)
        cache_tokens = sum(item["cache_tokens"] for item in turn_measurements)
        cache_write_tokens = sum(
            item["cache_write_tokens"] for item in turn_measurements
        )
        cost = {
            "input_usd": sum(item["input_usd"] for item in request_costs),
            "output_usd": sum(item["output_usd"] for item in request_costs),
            "cache_usd": sum(item["cache_usd"] for item in request_costs),
            "cache_write_usd": sum(item["cache_write_usd"] for item in request_costs),
            "total_usd": sum(item["total_usd"] for item in request_costs),
            "requests": request_costs,
            "rate_card": rates,
        }
    except Exception as error:
        failure_class = "infra_dependency"
        error_text = type(error).__name__
        tokens = None
        latency_ms = None
        cost = None
    record = {
        "trial_id": trial_id,
        "case_id": packet.case_id,
        "output": {
            "case_id": packet.case_id,
            "output": final_text,
            "trajectory": turns,
            "measurements": {
                "turns": turn_measurements,
                "tokens": tokens,
                "latency_ms": latency_ms,
                "input_tokens": sum(item["input_tokens"] for item in turn_measurements)
                if turn_measurements
                else None,
                "output_tokens": sum(
                    item["output_tokens"] for item in turn_measurements
                )
                if turn_measurements
                else None,
                "cache_tokens": sum(item["cache_tokens"] for item in turn_measurements)
                if turn_measurements
                else None,
                "cache_write_tokens": sum(
                    item["cache_write_tokens"] for item in turn_measurements
                )
                if turn_measurements
                else None,
            },
            "cost": cost,
        },
        "stdout": final_text,
        "exit_code": 0 if failure_class == "none" else 1,
        "failure_class": failure_class,
    }
    if error_text:
        record["error"] = error_text
    if artifact_root is not None:
        write_raw_artifact(artifact_root, record)
    return record

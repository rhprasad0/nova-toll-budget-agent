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

from strands.types.tools import AgentTool, ToolGenerator, ToolResult, ToolSpec, ToolUse

from agent.toll_agent import build_agent
from agent_tools.get_annual_toll_ballpark import get_annual_toll_ballpark
from agent_tools.get_current_toll_price import get_current_toll_price

_TOOL_SPECS = {
    "get_current_toll_price": cast(ToolSpec, get_current_toll_price.tool_spec),
    "get_annual_toll_ballpark": cast(ToolSpec, get_annual_toll_ballpark.tool_spec),
}


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
    ) -> None:
        super().__init__()
        self._spec = cast(ToolSpec, deepcopy(tool_spec))
        self.fixture_id = fixture_id
        self.expected_input = deepcopy(dict(expected_input)) if expected_input else None
        self.payload = deepcopy(dict(payload)) if payload else None
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

    def _record(self, tool_use: ToolUse, *, error: str | None) -> ToolResult:
        tool_use_id = tool_use.get("toolUseId")
        name = tool_use.get("name")
        inputs = deepcopy(tool_use.get("input"))
        call = {"name": name, "input": inputs, "toolUseId": tool_use_id}
        if error:
            call["is_error"] = True
            call["error"] = error
        else:
            call["is_error"] = False
            call["tool_result"] = deepcopy(self.payload)
        self.calls.append(call)
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
        del invocation_state
        error: str | None = None
        if self.expected_input is None:
            error = "recorded fixture denies this tool call"
        elif tool_use.get("input") != self.expected_input:
            error = "recorded fixture input mismatch"
        elif self.payload is None:
            error = "recorded fixture payload is unavailable"
        yield self._record(tool_use, error=error)


def fixture_tools(
    fixture_id: str | None = None,
    *,
    request: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> list[FixtureAgentTool]:
    """Return both production contracts backed exclusively by fixture wrappers."""
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


@dataclass(frozen=True)
class RateCard:
    source: str
    version: str
    digest: str
    input_rate_usd_per_million: float
    output_rate_usd_per_million: float
    cache_rate_usd_per_million: float

    def validate(self) -> None:
        if not self.source or not self.version or not isinstance(self.digest, str):
            raise ValueError("rate-card provenance is incomplete")
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("rate-card digest is invalid")
        rates = (
            self.input_rate_usd_per_million,
            self.output_rate_usd_per_million,
            self.cache_rate_usd_per_million,
        )
        if any(
            type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0
            for rate in rates
        ):
            raise ValueError("rate-card rates must be finite and non-negative")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "source": self.source,
            "version": self.version,
            "digest": self.digest,
            "input_rate_usd_per_million": self.input_rate_usd_per_million,
            "output_rate_usd_per_million": self.output_rate_usd_per_million,
            "cache_rate_usd_per_million": self.cache_rate_usd_per_million,
        }


def _measurement(summary: object, *names: str) -> int | None:
    if isinstance(summary, Mapping):
        for name in names:
            value = summary.get(name)
            if type(value) is int and value >= 0:
                return value
        for value in summary.values():
            found = _measurement(value, *names)
            if found is not None:
                return found
    elif isinstance(summary, Sequence) and not isinstance(summary, (str, bytes)):
        for value in summary:
            found = _measurement(value, *names)
            if found is not None:
                return found
    return None


def _response_usage(response: object) -> Mapping[str, Any]:
    metrics = getattr(response, "metrics", None)
    invocations = getattr(metrics, "agent_invocations", None)
    if type(invocations) is not list or not invocations:
        return {}
    usage = getattr(invocations[-1], "usage", None)
    return usage if isinstance(usage, Mapping) else {}


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
    artifact_root: Path,
    trial_id: str,
    rate_card: RateCard | None,
) -> dict[str, Any]:
    """Run every packet turn through an injected model and write raw observations."""
    turns: list[dict[str, Any]] = []
    turn_measurements: list[dict[str, int]] = []
    final_text = ""
    failure_class = "none"
    error_text: str | None = None
    tokens: int | None = None
    latency_ms: int | None = None
    cost: dict[str, Any] | None = None
    tools = fixture_tools(
        packet.fixture_id,
        request=packet.fixture_request,
        payload=packet.fixture_payload,
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
        )
        for prompt in packet.conversation:
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
            usage = _response_usage(response)
            turn_tokens = _measurement(usage, "totalTokens", "total_tokens", "tokens")
            input_tokens = _measurement(usage, "inputTokens", "input_tokens")
            output_tokens = _measurement(usage, "outputTokens", "output_tokens")
            cache_tokens = _measurement(
                usage, "cacheReadInputTokens", "cache_read_input_tokens"
            )
            if (
                turn_tokens is None
                or input_tokens is None
                or output_tokens is None
                or cache_tokens is None
            ):
                turns.append({"prompt": prompt, "response": final_text, "calls": calls})
                raise ValueError("complete model usage is required for every turn")
            if turn_tokens != input_tokens + output_tokens:
                turns.append({"prompt": prompt, "response": final_text, "calls": calls})
                raise ValueError("total token usage does not match input and output")
            if cache_tokens > input_tokens:
                turns.append({"prompt": prompt, "response": final_text, "calls": calls})
                raise ValueError("cached input usage exceeds total input usage")
            turn_latency = max(1, (elapsed_ns + 999_999) // 1_000_000)
            turns.append({"prompt": prompt, "response": final_text, "calls": calls})
            turn_measurements.append(
                {
                    "tokens": turn_tokens,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_tokens": cache_tokens,
                    "latency_ms": turn_latency,
                }
            )
        tokens = sum(item["tokens"] for item in turn_measurements)
        latency_ms = sum(item["latency_ms"] for item in turn_measurements)
        input_tokens = sum(item["input_tokens"] for item in turn_measurements)
        output_tokens = sum(item["output_tokens"] for item in turn_measurements)
        cache_tokens = sum(item["cache_tokens"] for item in turn_measurements)
        rates = rate_card.as_dict()
        uncached_input_tokens = input_tokens - cache_tokens
        cost = {
            "input_usd": uncached_input_tokens
            * rates["input_rate_usd_per_million"]
            / 1_000_000,
            "output_usd": output_tokens
            * rates["output_rate_usd_per_million"]
            / 1_000_000,
            "cache_usd": cache_tokens * rates["cache_rate_usd_per_million"] / 1_000_000,
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
            },
            "cost": cost,
        },
        "stdout": final_text,
        "exit_code": 0 if failure_class == "none" else 1,
        "failure_class": failure_class,
    }
    if error_text:
        record["error"] = error_text
    write_raw_artifact(artifact_root, record)
    return record

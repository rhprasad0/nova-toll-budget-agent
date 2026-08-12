#!/usr/bin/env python3
"""Capture raw local traces for repeated successful planner calls."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from strands.hooks import (  # noqa: E402
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
    MessageAddedEvent,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402

PROMPT = (
    "Price a trip from Dumfries to Westpark Drive at 10:10 AM Eastern on July 29, 2026."
)
PLANNER = "plan_toll_route"
_DEFAULT_OUTPUT_DIR = Path(".tollchat/duplicate-planner")


def _mapping(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _blocks(message: object) -> Sequence[object]:
    mapped = _mapping(message)
    content = mapped.get("content") if mapped else None
    return (
        cast(Sequence[object], content)
        if isinstance(content, Sequence) and not isinstance(content, str | bytes)
        else []
    )


def _planner_calls(messages: Sequence[object]) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for message in messages:
        for block in _blocks(message):
            mapped_block = _mapping(block)
            tool_use = _mapping(mapped_block.get("toolUse")) if mapped_block else None
            if not tool_use or tool_use.get("name") != PLANNER:
                continue
            tool_use_id = tool_use.get("toolUseId")
            arguments = tool_use.get("input")
            if (
                not isinstance(tool_use_id, str)
                or tool_use_id in seen_ids
                or not isinstance(arguments, Mapping)
            ):
                continue
            seen_ids.add(tool_use_id)
            calls.append(
                {
                    "tool_use_id": tool_use_id,
                    "arguments": dict(cast(Mapping[str, object], arguments)),
                }
            )
    return calls


def classify_planner_calls(messages: Sequence[object]) -> dict[str, object]:
    """Classify unique planner executions without counting repeated history."""
    calls = _planner_calls(messages)
    arguments = [cast(dict[str, object], call["arguments"]) for call in calls]
    signatures = {
        json.dumps(argument, sort_keys=True, separators=(",", ":"), default=str)
        for argument in arguments
    }
    status = (
        "duplicate"
        if len(calls) > 1 and len(signatures) == 1
        else "normal"
        if len(calls) == 1
        else "other"
    )
    return {
        "status": status,
        "planner_call_count": len(calls),
        "tool_use_ids": [call["tool_use_id"] for call in calls],
        "arguments": arguments,
    }


def classify_planner_executions(events: Sequence[object]) -> dict[str, object]:
    successful = suppressed = failed = 0
    successful_signatures: set[str] = set()
    suppressed_signatures: set[str] = set()
    for raw_event in events:
        event = _mapping(raw_event)
        payload = _mapping(event.get("payload")) if event else None
        tool_use = _mapping(payload.get("tool_use")) if payload else None
        if (
            not event
            or event.get("event") != "after_tool"
            or not payload
            or not tool_use
            or tool_use.get("name") != PLANNER
        ):
            continue
        if payload.get("cancel_message"):
            suppressed += 1
            suppressed_signatures.add(
                json.dumps(
                    {
                        "name": tool_use.get("name"),
                        "input": tool_use.get("input"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            )
            continue
        result = _mapping(payload.get("result"))
        if result and result.get("status") == "success":
            successful += 1
            successful_signatures.add(
                json.dumps(
                    {
                        "name": tool_use.get("name"),
                        "input": tool_use.get("input"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            )
        else:
            failed += 1
    status = (
        "suppressed_duplicate"
        if suppressed
        and successful == 1
        and not failed
        and successful_signatures == suppressed_signatures
        else "normal"
        if successful == 1 and not suppressed and not failed
        else "other"
    )
    return {
        "status": status,
        "successful_execution_count": successful,
        "suppressed_count": suppressed,
        "failed_execution_count": failed,
    }


def reasoning_summaries(messages: Sequence[object]) -> list[str]:
    summaries: list[str] = []
    for message in messages:
        for block in _blocks(message):
            mapped_block = _mapping(block)
            reasoning = (
                _mapping(mapped_block.get("reasoningContent")) if mapped_block else None
            )
            reasoning_text = (
                _mapping(reasoning.get("reasoningText")) if reasoning else None
            )
            text = (
                reasoning_text.get("text")
                if reasoning_text
                else reasoning.get("text")
                if reasoning
                else None
            )
            if isinstance(text, str):
                summaries.append(text)
    return summaries


def should_stop(statuses: Sequence[str]) -> bool:
    return "normal" in statuses and "suppressed_duplicate" in statuses


def enable_reasoning_summary(agent: object) -> None:
    """Opt this diagnostic agent into model-provided reasoning summaries."""
    model = cast(Any, agent).model
    config = cast(Mapping[str, object], model.get_config())
    configured_params = config.get("params")
    params = (
        dict(cast(Mapping[str, object], configured_params))
        if isinstance(configured_params, Mapping)
        else {}
    )
    configured_reasoning = params.get("reasoning")
    reasoning = (
        dict(cast(Mapping[str, object], configured_reasoning))
        if isinstance(configured_reasoning, Mapping)
        else {}
    )
    reasoning["summary"] = "auto"
    params["reasoning"] = reasoning
    model.update_config(params=params)


def append_raw_record(path: Path, record: Mapping[str, object]) -> None:
    """Append an unsanitized trace record to a private local JSONL file."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class RawTraceRecorder(HookProvider):
    """Record and stream the observable model/tool loop without redaction."""

    def __init__(self, emit: Callable[[dict[str, object]], None]) -> None:
        self.emit = emit
        self.events: list[dict[str, object]] = []
        self.messages: list[object] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: object) -> None:
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)
        registry.add_callback(MessageAddedEvent, self.message_added)

    def _record(self, kind: str, payload: object) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": kind,
            "payload": deepcopy(payload),
        }
        self.events.append(event)
        self.emit(event)

    def before_model(self, event: BeforeModelCallEvent) -> None:
        self._record(
            "before_model",
            {"projected_input_tokens": event.projected_input_tokens},
        )

    def after_model(self, event: AfterModelCallEvent) -> None:
        stop = event.stop_response
        self._record(
            "after_model",
            {
                "stop_reason": stop.stop_reason if stop else None,
                "message": stop.message if stop else None,
                "exception": str(event.exception) if event.exception else None,
                "retry": event.retry,
            },
        )

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        self._record("before_tool", event.tool_use)

    def after_tool(self, event: AfterToolCallEvent) -> None:
        self._record(
            "after_tool",
            {
                "tool_use": event.tool_use,
                "result": event.result,
                "exception": str(event.exception) if event.exception else None,
                "cancel_message": event.cancel_message,
                "retry": event.retry,
            },
        )

    def message_added(self, event: MessageAddedEvent) -> None:
        message = deepcopy(event.message)
        self.messages.append(message)
        self._record("message_added", message)


def _print_event(event: dict[str, object]) -> None:
    print(json.dumps(event, default=str, ensure_ascii=False), flush=True)


def _output_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return _DEFAULT_OUTPUT_DIR / f"{stamp}.jsonl"


def _run_trial(index: int, output_path: Path) -> str:
    recorder = RawTraceRecorder(_print_event)
    agent = build_agent(hooks=[recorder])
    enable_reasoning_summary(agent)
    started_at = datetime.now(UTC).isoformat()
    try:
        result = agent(PROMPT)
        result_payload = result.to_dict()
        metrics = result.metrics.get_summary()
        error = None
    except Exception as caught:  # noqa: BLE001 - preserve the raw failed trial
        result_payload = None
        metrics = None
        error = {"type": type(caught).__name__, "message": str(caught)}
    classification = classify_planner_calls(recorder.messages)
    execution = classify_planner_executions(recorder.events)
    if (
        execution["status"] == "suppressed_duplicate"
        and classification["status"] != "duplicate"
    ):
        execution["status"] = "other"
    record: dict[str, object] = {
        "trial": index,
        "started_at": started_at,
        "ended_at": datetime.now(UTC).isoformat(),
        "prompt": PROMPT,
        "classification": classification,
        "execution": execution,
        "reasoning_summaries": reasoning_summaries(recorder.messages),
        "events": recorder.events,
        "messages": recorder.messages,
        "result": result_payload,
        "metrics": metrics,
        "error": error,
    }
    append_raw_record(output_path, record)
    print(
        json.dumps(
            {
                "trial": index,
                "classification": classification,
                "execution": execution,
                "reasoning_summaries": record["reasoning_summaries"],
                "error": error,
                "trace_path": str(output_path),
            },
            default=str,
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    if error:
        raise RuntimeError("diagnostic trial failed; inspect the raw trace")
    return cast(str, execution["status"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-trials", type=int, default=10)
    args = parser.parse_args()
    if args.max_trials < 1:
        parser.error("--max-trials must be at least 1")

    configure_local_pricing_env()
    output_path = _output_path()
    statuses: list[str] = []
    print(f"Raw trace: {output_path}", flush=True)
    for index in range(1, args.max_trials + 1):
        statuses.append(_run_trial(index, output_path))
        if should_stop(statuses):
            break
    print(json.dumps({"statuses": statuses, "trace_path": str(output_path)}))
    return 0 if should_stop(statuses) else 2


if __name__ == "__main__":
    raise SystemExit(main())

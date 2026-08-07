#!/usr/bin/env python3
"""Fail closed when exported AgentCore runtime-trace records are incomplete."""

from __future__ import annotations

# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportOperatorIssue=false
import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import cast


class TraceVerificationError(ValueError):
    """An exported trace is not safe, complete, or correlated."""


_STAGES = {"input_guardrail", "agent", "output_guardrail", "invoke"}
_CREDENTIAL = re.compile(
    r"(?i)(synthetic[ _-]?(?:credential|secret|token|api[ _-]?key)|"
    r"(?:api[ _-]?key|authorization|aws_secret_access_key|password)\s*[=:]|"
    r"bearer\s+\S+|(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://|"
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|"
    r"\bgh[pousr]_[A-Za-z0-9]{8,}\b|\bgithub_pat_[A-Za-z0-9_-]{8,}\b|\bsk-[\w-]+)"
)
_CREDENTIAL_KEY = re.compile(
    r"(?:access[_-]?key|api[_-]?key|authorization|credential|password|private[_-]?key|secret|session[_-]?token|(?:^|[_-])token(?:$|[_-]))",
    re.IGNORECASE,
)


def _unsafe(value: object) -> str | None:
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                return _unsafe(json.loads(value))
            except json.JSONDecodeError:
                pass
        if _CREDENTIAL.search(value):
            return "credential marker"
    if isinstance(value, list):
        return next((bad for item in value if (bad := _unsafe(item))), None)
    if isinstance(value, dict):
        if (
            value.get("role") in {"system", "developer"}
            and value.get("content") != "[REDACTED]"
        ):
            return "system prompt content"
        for key, item in value.items():
            if (
                isinstance(item, str)
                and _CREDENTIAL_KEY.search(key)
                and item != "[REDACTED]"
            ):
                return "credential marker"
            normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            prompt_key = re.search(
                r"(?:system|developer).*(?:prompt|instructions?|message)", normalized
            )
            if (
                prompt_key
                and not normalized.endswith(("_version", "_sha256"))
                and item != "[REDACTED]"
            ):
                return "system prompt content"
            if bad := _unsafe(item):
                return bad
    return None


def _query_messages(document: object, section: str) -> list[dict[str, object]]:
    if not isinstance(document, dict):
        raise TraceVerificationError("trace export must be an object")
    query = document.get(section)
    if not isinstance(query, dict) or not isinstance(query.get("results"), list):
        raise TraceVerificationError(f"trace export is missing {section} query results")
    messages = []
    for row in query["results"]:
        if not isinstance(row, list):
            raise TraceVerificationError(f"{section}: query result must be a row")
        fields = {
            str(item["field"]): item["value"]
            for item in row
            if isinstance(item, dict) and "field" in item and "value" in item
        }
        message = fields.get("@message")
        if not isinstance(message, str):
            raise TraceVerificationError(f"{section}: query result is missing @message")
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as error:
            raise TraceVerificationError(f"{section}: @message is not JSON") from error
        if not isinstance(parsed, dict):
            raise TraceVerificationError(f"{section}: @message must be an object")
        messages.append(parsed)
    return messages


def _attribute(span: dict[str, object], key: str) -> object | None:
    attributes = span.get("attributes")
    return attributes.get(key) if isinstance(attributes, dict) else None


def _verify_native_spans(
    native: list[dict[str, object]], correlations: dict[str, tuple[str, str]]
) -> None:
    required: dict[str, Callable[[str], bool]] = {
        "invoke": lambda name: "invoke_agent" in name or "invokeagent" in name,
        "model": lambda name: "model" in name or "chat" in name,
        "tool": lambda name: "execute_tool" in name or "executetool" in name,
    }
    for trace_id, (session_id, _) in correlations.items():
        matching = [
            span
            for span in native
            if str(span.get("traceId")) == trace_id
            and str(
                _attribute(span, "tollchat.session_id")
                or _attribute(span, "session.id")
            )
            == session_id
        ]
        found = set()
        for span in matching:
            name = str(span["name"]).lower()
            start = span.get("startTimeUnixNano")
            end = span.get("endTimeUnixNano")
            if not span.get("spanId") or start is None or end is None:
                raise TraceVerificationError("native span is missing required fields")
            if str(start) == str(end):
                raise TraceVerificationError("native span has zero duration")
            found.update(kind for kind, matches in required.items() if matches(name))
        if missing := set(required) - found:
            raise TraceVerificationError(
                f"{trace_id}: missing correlated native span(s): {', '.join(sorted(missing))}"
            )


def _required(mapping: dict[str, object], key: str, *, context: str) -> object:
    value = mapping.get(key)
    if value is None or value == "" or value == []:
        raise TraceVerificationError(f"{context}: missing {key}")
    return value


def _timing(payload: dict[str, object], stage: str) -> None:
    timing = _required(payload, "timing", context=stage)
    if not isinstance(timing, dict):
        raise TraceVerificationError(f"{stage}: timing must be an object")
    _required(timing, "started_at", context=stage)
    _required(timing, "ended_at", context=stage)


def _guardrail(payload: dict[str, object], stage: str, source: str) -> None:
    _timing(payload, stage)
    request = _required(payload, "request", context=stage)
    response = _required(payload, "response", context=stage)
    if not isinstance(request, dict) or request.get("source") != source:
        raise TraceVerificationError(f"{stage}: correlation source must be {source}")
    if request.get("outputScope") != "FULL":
        raise TraceVerificationError(f"{stage}: outputScope must be FULL")
    _required(request, "content", context=stage)
    if not isinstance(response, dict):
        raise TraceVerificationError(f"{stage}: response must be an object")
    for field in (
        "action",
        "actionReason",
        "assessments",
        "guardrailCoverage",
        "usage",
    ):
        _required(response, field, context=stage)
    if "outputs" not in response:
        raise TraceVerificationError(f"{stage}: missing outputs")


def _agent(payload: dict[str, object]) -> None:
    _timing(payload, "agent")
    request = _required(payload, "request", context="agent")
    response = _required(payload, "response", context="agent")
    if not isinstance(request, dict) or not isinstance(response, dict):
        raise TraceVerificationError("agent: request and response must be objects")
    _required(request, "prompt", context="agent")
    _required(response, "answer", context="agent")
    for field in (
        "model_messages",
        "tool_calls",
        "model_version",
        "system_prompt_version",
        "toolset_version",
    ):
        _required(payload, field, context="agent")
    tools = payload["tool_calls"]
    if not isinstance(tools, list) or any(
        not isinstance(tool, dict)
        or any(not tool.get(field) for field in ("name", "arguments", "result"))
        for tool in tools
    ):
        raise TraceVerificationError(
            "agent: tool_calls need name, arguments, and result"
        )


def _invoke(payload: dict[str, object]) -> None:
    _timing(payload, "invoke")
    if "error" not in payload:
        raise TraceVerificationError("invoke: missing error")


def verify_trace(document: object) -> dict[str, int]:
    """Validate a parsed trace export and return a terse verified summary."""
    if bad := _unsafe(document):
        raise TraceVerificationError(f"trace export contains {bad}")
    envelopes = _query_messages(document, "runtime")
    if not envelopes:
        raise TraceVerificationError("no tollchat.runtime_trace records found")
    if any(item.get("record_type") != "tollchat.runtime_trace" for item in envelopes):
        raise TraceVerificationError("runtime query contains an unexpected record")

    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    families: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for record in envelopes:
        for field in (
            "record_version",
            "stage",
            "trace_id",
            "span_id",
            "session_id",
            "aws_request_id",
            "chunk_index",
            "chunk_count",
            "sha256",
            "payload",
        ):
            _required(record, field, context="envelope")
        if record["record_version"] != 1 or record["stage"] not in _STAGES:
            raise TraceVerificationError(
                "envelope: unsupported record version or stage"
            )
        if not isinstance(record["payload"], str):
            raise TraceVerificationError("envelope: payload must be a string chunk")
        stage = str(record["stage"])
        trace_id, span_id = str(record["trace_id"]), str(record["span_id"])
        family = (
            stage,
            span_id,
            str(record["session_id"]),
            str(record["aws_request_id"]),
            str(record["sha256"]),
        )
        families[family].add(trace_id)
        grouped[(trace_id, span_id, stage)].append(record)
    if any(len(trace_ids) != 1 for trace_ids in families.values()):
        raise TraceVerificationError("correlation mismatch between trace records")

    complete: dict[str, list[tuple[dict[str, object], dict[str, object]]]] = (
        defaultdict(list)
    )
    correlations: dict[str, tuple[str, str]] = {}
    for (trace_id, span_id, stage), chunks in grouped.items():
        counts = {chunk["chunk_count"] for chunk in chunks}
        hashes = {chunk["sha256"] for chunk in chunks}
        if (
            len(counts) != 1
            or len(hashes) != 1
            or not isinstance(next(iter(counts)), int)
        ):
            raise TraceVerificationError(
                f"{stage}: inconsistent chunk metadata or sha256"
            )
        count = cast(int, next(iter(counts)))
        indexes = {chunk["chunk_index"] for chunk in chunks}
        if count < 1 or len(chunks) != count or indexes != set(range(count)):
            raise TraceVerificationError(f"{stage}: chunk completeness failure")
        serialized = "".join(
            str(chunk["payload"])
            for chunk in sorted(
                chunks, key=lambda chunk: cast(int, chunk["chunk_index"])
            )
        )
        if hashlib.sha256(serialized.encode()).hexdigest() != next(iter(hashes)):
            raise TraceVerificationError(f"{stage}: sha256 mismatch")
        try:
            payload = json.loads(serialized)
        except json.JSONDecodeError as error:
            raise TraceVerificationError(
                f"{stage}: payload is not complete JSON"
            ) from error
        if not isinstance(payload, dict):
            raise TraceVerificationError(f"{stage}: payload must be an object")
        if bad := _unsafe(payload):
            raise TraceVerificationError(f"{stage} contains {bad}")
        correlation = (str(chunks[0]["session_id"]), str(chunks[0]["aws_request_id"]))
        previous = correlations.setdefault(trace_id, correlation)
        if previous != correlation:
            raise TraceVerificationError("correlation mismatch between trace records")
        complete[trace_id].append(({"stage": stage, "span_id": span_id}, payload))

    for trace_id, records in complete.items():
        stages = {str(record[0]["stage"]) for record in records}
        if missing := _STAGES - stages:
            raise TraceVerificationError(
                f"{trace_id}: missing required stage(s): {', '.join(sorted(missing))}"
            )
        for envelope, payload in records:
            stage = str(envelope["stage"])
            if stage == "input_guardrail":
                _guardrail(payload, stage, "INPUT")
            elif stage == "output_guardrail":
                _guardrail(payload, stage, "OUTPUT")
            elif stage == "agent":
                _agent(payload)
            else:
                _invoke(payload)
    _verify_native_spans(_query_messages(document, "spans"), correlations)
    return {
        "traces": len(complete),
        "records": sum(len(records) for records in complete.values()),
    }


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise TraceVerificationError(f"{path}: expected JSON") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "trace_json",
        type=Path,
        help="combined CloudWatch query JSON; never an eval/results path",
    )
    path = parser.parse_args(argv).trace_json
    if "eval/results" in path.as_posix():
        parser.error("raw traces must not be written to eval/results")
    try:
        summary = verify_trace(_load(path))
    except (OSError, TraceVerificationError) as error:
        print(f"TRACE INCOMPLETE: {error}", file=sys.stderr)
        return 1
    print(
        f"TRACE OK: {summary['traces']} trace(s), {summary['records']} complete stage record(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

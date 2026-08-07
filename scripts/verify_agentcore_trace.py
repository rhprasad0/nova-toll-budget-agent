#!/usr/bin/env python3
"""Fail closed when exported AgentCore runtime-trace records are incomplete."""

from __future__ import annotations

# JSON exports are intentionally schema-flexible; validate their runtime shape below.
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


def _unsafe_chunk(payload: str) -> str | None:
    """Catch obvious secrets before a corrupt chunk can hide them behind a bad hash."""
    if bad := _unsafe(payload):
        return bad
    try:
        return _unsafe(json.loads(payload))
    except json.JSONDecodeError:
        return None


def _json_values(value: object) -> list[object]:
    """Unwrap CloudWatch Transaction Search fields and normal JSON/JSONL exports."""
    if isinstance(value, str):
        try:
            return _json_values(json.loads(value))
        except json.JSONDecodeError:
            return []
    if isinstance(value, list):
        return [item for child in value for item in _json_values(child)]
    if isinstance(value, dict):
        if "record_type" in value:
            return [value]
        if "value" in value and len(value) <= 3:
            return _json_values(value["value"])
        return [item for child in value.values() for item in _json_values(child)]
    return []


def _objects(value: object) -> list[dict[str, object]]:
    if isinstance(value, str):
        try:
            return _objects(json.loads(value))
        except json.JSONDecodeError:
            return []
    if isinstance(value, list):
        if all(
            isinstance(item, dict) and "field" in item and "value" in item
            for item in value
        ):
            row = {str(item["field"]): item["value"] for item in value}
            return [row, *[item for child in row.values() for item in _objects(child)]]
        return [item for child in value for item in _objects(child)]
    if isinstance(value, dict):
        return [value, *[item for child in value.values() for item in _objects(child)]]
    return []


def _attribute(span: dict[str, object], key: str) -> object | None:
    attributes = span.get("attributes", {})
    if isinstance(attributes, dict):
        return attributes.get(key)
    if isinstance(attributes, list):
        for attribute in attributes:
            if not isinstance(attribute, dict) or attribute.get("key") != key:
                continue
            value = attribute.get("value")
            if isinstance(value, dict):
                return next(iter(value.values()), None)
            return value
    return None


def _verify_native_spans(
    document: object, correlations: dict[str, tuple[str, str]]
) -> None:
    native = []
    for item in _objects(document):
        name = item.get("name")
        trace_id = item.get("trace_id", item.get("traceId"))
        span_id = item.get("span_id", item.get("spanId"))
        start = item.get(
            "start_time_unix_nano", item.get("startTimeUnixNano", item.get("startTime"))
        )
        end = item.get(
            "end_time_unix_nano", item.get("endTimeUnixNano", item.get("endTime"))
        )
        if (
            isinstance(name, str)
            and trace_id
            and span_id
            and start is not None
            and end is not None
        ):
            native.append(item)
    required: dict[str, Callable[[str], bool]] = {
        "invoke": lambda name: "invoke_agent" in name or "invokeagent" in name,
        "model": lambda name: "model" in name or "chat" in name,
        "tool": lambda name: "execute_tool" in name or "executetool" in name,
    }
    for trace_id, (session_id, _) in correlations.items():
        matching = [
            span
            for span in native
            if str(span.get("trace_id", span.get("traceId"))) == trace_id
            and str(
                _attribute(span, "tollchat.session_id")
                or _attribute(span, "session.id")
                or span.get("attributes.session.id")
            )
            == session_id
        ]
        found = set()
        for span in matching:
            name = str(span["name"]).lower()
            start = span.get(
                "start_time_unix_nano",
                span.get("startTimeUnixNano", span.get("startTime")),
            )
            end = span.get(
                "end_time_unix_nano",
                span.get("endTimeUnixNano", span.get("endTime")),
            )
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
    envelopes = [
        item
        for item in _json_values(document)
        if isinstance(item, dict)
        and item.get("record_type") == "tollchat.runtime_trace"
    ]
    if not envelopes:
        raise TraceVerificationError("no tollchat.runtime_trace records found")

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
        if bad := _unsafe_chunk(record["payload"]):
            raise TraceVerificationError(f"envelope contains {bad}")
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
    _verify_native_spans(document, correlations)
    return {
        "traces": len(complete),
        "records": sum(len(records) for records in complete.values()),
    }


def _load(path: Path) -> object:
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as error:
            raise TraceVerificationError(f"{path}: expected JSON or JSONL") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "trace_json",
        type=Path,
        help="exported/query JSON or JSONL; never an eval/results path",
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

#!/usr/bin/env python3
"""Prove the deployed private preview answers one versioned toll request."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from typing import cast

CASE_VERSION = "i66-eastbound-full-v1"
EXPECTED_TOTAL = "12.15"
DISCLAIMER = (
    "Estimates only. Verify current rates with the toll operator before travel."
)
PROMPT = (
    "Price I-66 Inside the Beltway from I-66 West to Washington at "
    "7/29/2026 8:30 AM ET."
)
EXPECTED_ARGUMENTS = {
    "origin": "I-66 West",
    "destination": "Washington",
    "at_time": "2026-07-29T08:30:00-04:00",
}
_MODEL_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_SEMVER = re.compile(r"\d+\.\d+\.\d+\Z")
_RUNTIME_VERSION = re.compile(r"[1-9]\d{0,9}\Z")
_UNSAFE_METADATA = re.compile(
    r"(?i)(?:arn:aws|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|"
    r"\bgh[pousr]_[A-Za-z0-9]{8,}\b|\b(?:sk|rk|pk)[_-][A-Za-z0-9_-]{8,}\b|"
    r"\b\d{12}\b)"
)


class SmokeVerificationError(ValueError):
    """The deployed response cannot be accepted as passing evidence."""


class TracePending(SmokeVerificationError):
    """The correlated governed trace is not complete yet."""


def _safe_contract_versions(versions: dict[str, object]) -> dict[str, str]:
    expected = {"model_version", "system_prompt_version", "toolset_version"}
    if set(versions) != expected:
        raise SmokeVerificationError("trace contains unsafe version metadata")
    model = versions["model_version"]
    system_prompt = versions["system_prompt_version"]
    toolset = versions["toolset_version"]
    if (
        not isinstance(model, str)
        or not _MODEL_VERSION.fullmatch(model)
        or _UNSAFE_METADATA.search(model)
        or not isinstance(system_prompt, str)
        or not _SEMVER.fullmatch(system_prompt)
        or not isinstance(toolset, str)
        or not _SEMVER.fullmatch(toolset)
    ):
        raise SmokeVerificationError("trace contains unsafe version metadata")
    return {
        "model_version": model,
        "system_prompt_version": system_prompt,
        "toolset_version": toolset,
    }


def _safe_runtime_version(value: object) -> str:
    if not isinstance(value, str) or not _RUNTIME_VERSION.fullmatch(value):
        raise SmokeVerificationError("runtime returned unsafe version metadata")
    return value


def verify_browser_response(status: int, raw: bytes) -> list[dict[str, object]]:
    """Validate the browser-visible NDJSON without returning answer content."""
    try:
        events = [json.loads(line) for line in raw.splitlines() if line]
    except json.JSONDecodeError as error:
        raise SmokeVerificationError("browser response was not valid NDJSON") from error
    if not all(isinstance(event, dict) for event in events):
        raise SmokeVerificationError("browser event contract did not match")
    typed = cast(list[dict[str, object]], events)
    expected_tools = [
        {
            "type": "tool",
            "index": 0,
            "label": "Checking I-66 tolls",
            "status": "running",
        },
        {
            "type": "tool",
            "index": 0,
            "label": "Checking I-66 tolls",
            "status": "completed",
        },
    ]
    if status != 200 or len(typed) != 3 or typed[:2] != expected_tools:
        raise SmokeVerificationError("browser event contract did not match")
    answer = typed[2]
    text = answer.get("text")
    if (
        set(answer) != {"type", "text", "blocked"}
        or answer.get("type") != "answer"
        or answer.get("blocked") is not False
        or not isinstance(text, str)
        or f"${EXPECTED_TOTAL}" not in text
        or DISCLAIMER not in text
    ):
        raise SmokeVerificationError("browser answer contract did not match")
    return typed


def _complete_payloads(
    records: list[dict[str, object]],
) -> list[tuple[str, str, dict[str, object]]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(
        list
    )
    for record in records:
        if record.get("record_type") != "tollchat.runtime_trace":
            continue
        required = ("session_id", "trace_id", "span_id", "stage", "sha256")
        if any(
            not isinstance(record.get(field), str) or not record[field]
            for field in required
        ):
            raise SmokeVerificationError("governed trace record was malformed")
        key = cast(
            tuple[str, str, str, str],
            tuple(cast(str, record[field]) for field in required[:-1]),
        )
        grouped[key].append(record)

    payloads: list[tuple[str, str, dict[str, object]]] = []
    for (session_id, _trace_id, _span_id, stage), chunks in grouped.items():
        counts = {chunk.get("chunk_count") for chunk in chunks}
        digests = {chunk.get("sha256") for chunk in chunks}
        if (
            len(counts) != 1
            or not isinstance(next(iter(counts)), int)
            or len(digests) != 1
        ):
            raise SmokeVerificationError("trace integrity check failed")
        count = cast(int, next(iter(counts)))
        digest = cast(str, next(iter(digests)))
        indexes = {chunk.get("chunk_index") for chunk in chunks}
        if count < 1 or len(chunks) != count or indexes != set(range(count)):
            continue
        if any(not isinstance(chunk.get("payload"), str) for chunk in chunks):
            raise SmokeVerificationError("trace integrity check failed")
        serialized = "".join(
            cast(str, chunk["payload"])
            for chunk in sorted(
                chunks, key=lambda chunk: cast(int, chunk["chunk_index"])
            )
        )
        if hashlib.sha256(serialized.encode()).hexdigest() != digest:
            raise SmokeVerificationError("trace integrity check failed")
        try:
            payload = json.loads(serialized)
        except json.JSONDecodeError as error:
            raise SmokeVerificationError("trace integrity check failed") from error
        if not isinstance(payload, dict):
            raise SmokeVerificationError("trace integrity check failed")
        payloads.append((session_id, stage, cast(dict[str, object], payload)))
    return payloads


def _contains_total(value: object) -> bool:
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            return _contains_total(json.loads(value))
        except json.JSONDecodeError:
            return False
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return mapping.get("total_usd") == EXPECTED_TOTAL or any(
            _contains_total(item) for item in mapping.values()
        )
    if isinstance(value, list):
        return any(_contains_total(item) for item in cast(list[object], value))
    return False


def verify_trace_contract(
    records: list[dict[str, object]], marker: str
) -> dict[str, str]:
    """Verify exact tool execution and return only safe version metadata."""
    payloads = _complete_payloads(records)
    marker_sessions = {
        session_id
        for session_id, _stage, payload in payloads
        if marker in json.dumps(payload, separators=(",", ":"))
    }
    if not marker_sessions:
        raise TracePending("correlated trace is not complete")
    if len(marker_sessions) != 1:
        raise SmokeVerificationError("trace correlation was ambiguous")
    [session_id] = marker_sessions
    agent_payloads = [
        payload
        for candidate_session, stage, payload in payloads
        if candidate_session == session_id and stage == "agent"
    ]
    if not agent_payloads:
        raise TracePending("correlated trace is not complete")
    if len(agent_payloads) != 1:
        raise SmokeVerificationError("deployed trace contract did not match")
    payload = agent_payloads[0]
    raw_calls = payload.get("tool_calls")
    if not isinstance(raw_calls, list):
        raise SmokeVerificationError("deployed trace contract did not match")
    calls = cast(list[object], raw_calls)
    if len(calls) != 1 or not isinstance(calls[0], dict):
        raise SmokeVerificationError("deployed trace contract did not match")
    call = cast(dict[str, object], calls[0])
    if (
        call.get("name") != "i66_route"
        or call.get("arguments") != EXPECTED_ARGUMENTS
        or not _contains_total(call.get("result"))
    ):
        raise SmokeVerificationError("deployed trace contract did not match")
    return _safe_contract_versions(
        {
            field: payload.get(field)
            for field in ("model_version", "system_prompt_version", "toolset_version")
        }
    )


def build_report(
    *, runtime_version: str, versions: dict[str, str], timestamp: datetime
) -> dict[str, object]:
    """Build the only output safe to curate under eval/results/."""
    safe_versions = _safe_contract_versions(cast(dict[str, object], versions))
    return {
        "timestamp": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "issues": [99],
        "status": "passed",
        "case_version": CASE_VERSION,
        "agent_runtime_version": _safe_runtime_version(runtime_version),
        "contract_versions": safe_versions,
        "expected_total_usd": EXPECTED_TOTAL,
        "scenario": "Historical I-66 eastbound toll through the private browser path",
        "evidence_type": "Metadata-only deployed AgentCore canonical toll-query smoke",
        "checks": {
            "private_browser_path": True,
            "ordered_tool_lifecycle": True,
            "exact_i66_trajectory": True,
            "historical_rds_total": True,
            "required_disclaimer": True,
        },
        "notes": (
            "Raw responses, cookies, prompts, trace records, session identifiers, "
            "trace identifiers, and log-stream identifiers were used only in memory "
            "and were not curated."
        ),
    }


def _aws(aws: list[str], *arguments: str, timeout: float = 30.0) -> str:
    return subprocess.run(
        [*aws, *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=max(1.0, timeout),
    ).stdout.strip()


def _runtime_version(aws: list[str]) -> str:
    runtime_id = _aws(
        aws,
        "bedrock-agentcore-control",
        "list-agent-runtimes",
        "--query",
        "agentRuntimes[?agentRuntimeName=='nova_toll'].agentRuntimeId | [0]",
        "--output",
        "text",
    )
    if not runtime_id or runtime_id == "None":
        raise SmokeVerificationError("live AgentCore runtime was not found")
    version = _aws(
        aws,
        "bedrock-agentcore-control",
        "get-agent-runtime-endpoint",
        "--agent-runtime-id",
        runtime_id,
        "--endpoint-name",
        "preview",
        "--query",
        "liveVersion",
        "--output",
        "text",
    )
    return _safe_runtime_version(version)


def _post_chat(
    base_url: str,
    marker: str,
    *,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[int, bytes]:
    origin = urllib.parse.urlsplit(base_url)
    opener = opener or urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(
            {"message": f"{PROMPT} Verification marker: {marker}."}
        ).encode(),
        headers={
            "content-type": "application/json",
            "origin": f"{origin.scheme}://{origin.netloc}",
            "sec-fetch-site": "same-origin",
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _query_records(
    aws: list[str], log_group: str, start_time: int, deadline: float
) -> list[dict[str, object]]:
    def remaining() -> float:
        return min(30.0, max(1.0, deadline - time.time()))

    query_id = _aws(
        aws,
        "logs",
        "start-query",
        "--log-group-name",
        log_group,
        "--start-time",
        str(start_time),
        "--end-time",
        str(int(time.time())),
        "--query-string",
        "fields @message | filter @message like /tollchat.runtime_trace/ | sort @timestamp asc",
        "--query",
        "queryId",
        "--output",
        "text",
        timeout=remaining(),
    )
    while time.time() < deadline:
        result = cast(
            dict[str, object],
            json.loads(
                _aws(
                    aws,
                    "logs",
                    "get-query-results",
                    "--query-id",
                    query_id,
                    timeout=remaining(),
                )
            ),
        )
        status = result.get("status")
        if status == "Complete":
            records: list[dict[str, object]] = []
            for raw_row in cast(list[object], result.get("results", [])):
                if not isinstance(raw_row, list):
                    continue
                fields: dict[str, object] = {}
                for raw_item in cast(list[object], raw_row):
                    if not isinstance(raw_item, dict):
                        continue
                    item = cast(dict[object, object], raw_item)
                    field = item.get("field")
                    if isinstance(field, str):
                        fields[field] = item.get("value")
                message = fields.get("@message")
                if not isinstance(message, str):
                    continue
                try:
                    record = json.loads(message)
                except json.JSONDecodeError as error:
                    raise SmokeVerificationError(
                        "governed trace query returned malformed data"
                    ) from error
                if isinstance(record, dict):
                    records.append(cast(dict[str, object], record))
            return records
        if status not in {"Scheduled", "Running"}:
            raise SmokeVerificationError("governed trace query failed")
        time.sleep(min(2, max(0, deadline - time.time())))
    raise TracePending("governed trace query exceeded its deadline")


def run() -> dict[str, object]:
    preview_url = os.environ.get("PREVIEW_URL")
    if not preview_url:
        raise SmokeVerificationError("set PREVIEW_URL to the Tailscale preview URL")
    wait_seconds = int(os.environ.get("TRACE_WAIT_SECONDS", "600"))
    if wait_seconds < 1:
        raise SmokeVerificationError("TRACE_WAIT_SECONDS must be positive")
    aws = [
        "aws",
        "--profile",
        os.environ.get("AWS_PROFILE", "nova-toll"),
        "--region",
        os.environ.get("AWS_REGION", "us-east-1"),
    ]
    log_group = os.environ.get("RUNTIME_LOG_GROUP", "/aws/nova-toll/agentcore/traces")
    marker = f"verify-{uuid.uuid4().hex}"
    started = int(time.time()) - 1
    runtime_version = _runtime_version(aws)
    status, raw = _post_chat(preview_url, marker)
    verify_browser_response(status, raw)

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        records = _query_records(aws, log_group, started, deadline)
        try:
            versions = verify_trace_contract(records, marker)
            if _runtime_version(aws) != runtime_version:
                raise SmokeVerificationError(
                    "AgentCore runtime changed during the canonical smoke"
                )
            return build_report(
                runtime_version=runtime_version,
                versions=versions,
                timestamp=datetime.now(UTC),
            )
        except TracePending:
            time.sleep(min(5, max(0, deadline - time.time())))
    raise TracePending("canonical trace was not complete before the deadline")


def main() -> int:
    try:
        report = run()
    except SmokeVerificationError as error:
        print(f"CANONICAL SMOKE FAILED: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, ValueError):
        print(
            "CANONICAL SMOKE FAILED: an external dependency call failed",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

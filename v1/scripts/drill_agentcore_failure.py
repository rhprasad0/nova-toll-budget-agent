#!/usr/bin/env python3
"""Prove one deployed AgentCore runtime exception fails safely and recovers."""

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

try:
    from scripts import smoke_agentcore_canonical as canonical
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    import smoke_agentcore_canonical as canonical

_aws = canonical._aws  # pyright: ignore[reportPrivateUsage]
_query_records = canonical._query_records  # pyright: ignore[reportPrivateUsage]
_runtime_version = canonical._runtime_version  # pyright: ignore[reportPrivateUsage]
_safe_contract_versions = canonical._safe_contract_versions  # pyright: ignore[reportPrivateUsage]
_safe_runtime_version = canonical._safe_runtime_version  # pyright: ignore[reportPrivateUsage]

FAILURE_MODE = "runtime-exception-v1"
RUNTIME_SAFE_ERROR = {
    "code": "agent_unavailable",
    "message": "TollChat could not complete that request. Please try again.",
}
_FAILURE_BODY = (
    json.dumps({"type": "error", **RUNTIME_SAFE_ERROR}, separators=(",", ":")) + "\n"
).encode()
_PROXY_HASH = re.compile(r"[A-Za-z0-9+/]{43}=\Z")


class DrillError(ValueError):
    """The deployed failure drill cannot produce passing evidence."""


class TracePending(DrillError):
    """The correlated governed trace is not complete yet."""


def verify_failure_response(status: int, raw: bytes) -> None:
    if status != 200 or raw != _FAILURE_BODY:
        raise DrillError("browser error contract did not match")


def _complete_payloads(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, object]]] = (
        defaultdict(list)
    )
    for record in records:
        if record.get("record_type") != "tollchat.runtime_trace":
            continue
        required = (
            "session_id",
            "trace_id",
            "span_id",
            "aws_request_id",
            "stage",
            "sha256",
        )
        if any(
            not isinstance(record.get(field), str) or not record[field]
            for field in required
        ):
            raise DrillError("governed trace record was malformed")
        key = cast(
            tuple[str, str, str, str, str],
            tuple(cast(str, record[field]) for field in required[:-1]),
        )
        grouped[key].append(record)

    payloads: list[dict[str, object]] = []
    for (session_id, trace_id, span_id, request_id, stage), chunks in grouped.items():
        counts = {chunk.get("chunk_count") for chunk in chunks}
        digests = {chunk.get("sha256") for chunk in chunks}
        if (
            len(counts) != 1
            or not isinstance(next(iter(counts)), int)
            or len(digests) != 1
        ):
            raise DrillError("governed trace integrity check failed")
        count = cast(int, next(iter(counts)))
        indexes = {chunk.get("chunk_index") for chunk in chunks}
        if count < 1 or len(chunks) != count or indexes != set(range(count)):
            continue
        if any(not isinstance(chunk.get("payload"), str) for chunk in chunks):
            raise DrillError("governed trace integrity check failed")
        serialized = "".join(
            cast(str, chunk["payload"])
            for chunk in sorted(
                chunks, key=lambda chunk: cast(int, chunk["chunk_index"])
            )
        )
        digest = cast(str, next(iter(digests)))
        if hashlib.sha256(serialized.encode()).hexdigest() != digest:
            raise DrillError("governed trace integrity check failed")
        try:
            payload = json.loads(serialized)
        except json.JSONDecodeError as error:
            raise DrillError("governed trace integrity check failed") from error
        if not isinstance(payload, dict):
            raise DrillError("governed trace integrity check failed")
        payloads.append(
            {
                "session_id": session_id,
                "trace_id": trace_id,
                "span_id": span_id,
                "aws_request_id": request_id,
                "stage": stage,
                "payload": payload,
            }
        )
    return payloads


def _matching(
    payloads: list[dict[str, object]], stage: str, marker: str
) -> list[dict[str, object]]:
    return [
        item
        for item in payloads
        if item["stage"] == stage
        and marker in json.dumps(item["payload"], separators=(",", ":"), sort_keys=True)
    ]


def verify_failure_trace(
    records: list[dict[str, object]], marker: str
) -> dict[str, str]:
    payloads = _complete_payloads(records)
    guards = _matching(payloads, "input_guardrail", marker)
    if not guards:
        raise TracePending("failure trace is not complete")
    if len(guards) != 1:
        raise DrillError("failure trace correlation was ambiguous")
    guard = guards[0]
    correlation = {
        field: cast(str, guard[field])
        for field in ("session_id", "trace_id", "aws_request_id")
    }
    raw_groups = {
        (cast(str, record["span_id"]), cast(str, record["stage"]))
        for record in records
        if record.get("record_type") == "tollchat.runtime_trace"
        and all(record.get(field) == value for field, value in correlation.items())
    }
    guard_group = (cast(str, guard["span_id"]), "input_guardrail")
    if raw_groups == {guard_group}:
        raise TracePending("failure trace is not complete")
    if (
        len(raw_groups) != 2
        or guard_group not in raw_groups
        or len([group for group in raw_groups if group[1] == "invoke"]) != 1
    ):
        raise DrillError("failure trace contained contradictory request records")
    request_payloads = [
        item
        for item in payloads
        if all(item[field] == value for field, value in correlation.items())
    ]
    if len(request_payloads) == 1:
        raise TracePending("failure trace is not complete")
    invokes = [item for item in request_payloads if item["stage"] == "invoke"]
    if (
        len(request_payloads) != 2
        or len(
            [item for item in request_payloads if item["stage"] == "input_guardrail"]
        )
        != 1
        or len(invokes) != 1
    ):
        raise DrillError("failure trace contained contradictory request records")
    invoke = cast(dict[str, object], invokes[0]["payload"])
    if (
        set(invoke) != {"timing", "result", "error"}
        or not isinstance(invoke["timing"], dict)
        or invoke["result"] != {"error": RUNTIME_SAFE_ERROR}
        or invoke["error"] != {"type": "DeployedFailureDrill", "message": "[REDACTED]"}
    ):
        raise DrillError("failure trace contract did not match")
    return correlation


def verify_recovery_trace(
    records: list[dict[str, object]],
    marker: str,
    failure: dict[str, str],
) -> dict[str, str]:
    payloads = _complete_payloads(records)
    agents = _matching(payloads, "agent", marker)
    if not agents:
        raise TracePending("recovery trace is not complete")
    if len(agents) != 1:
        raise DrillError("recovery trace correlation was ambiguous")
    agent = agents[0]
    if (
        agent["session_id"] != failure["session_id"]
        or agent["trace_id"] == failure["trace_id"]
        or agent["aws_request_id"] == failure["aws_request_id"]
    ):
        raise DrillError("recovery did not use the same clean browser session")
    try:
        return canonical.verify_trace_contract(records, marker)
    except canonical.TracePending as error:
        raise TracePending("recovery trace is not complete") from error
    except canonical.SmokeVerificationError as error:
        raise DrillError("canonical recovery trace did not match") from error


def _safe_proxy_hash(value: object) -> str:
    if not isinstance(value, str) or not _PROXY_HASH.fullmatch(value):
        raise DrillError("proxy returned unsafe deployment metadata")
    return value


def build_report(
    *,
    runtime_version: str,
    proxy_code_sha256: str,
    versions: dict[str, str],
    timestamp: datetime,
) -> dict[str, object]:
    return {
        "timestamp": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "issues": [125],
        "status": "passed",
        "case_version": "agentcore-runtime-exception-v1",
        "agent_runtime_version": _safe_runtime_version(runtime_version),
        "proxy_code_sha256": _safe_proxy_hash(proxy_code_sha256),
        "contract_versions": _safe_contract_versions(cast(dict[str, object], versions)),
        "scenario": "Request-scoped deployed AgentCore runtime exception",
        "evidence_type": "Metadata-only deployed failure and recovery drill",
        "checks": {
            "trusted_private_browser_path": True,
            "injected_runtime_exception": True,
            "exact_safe_error_contract": True,
            "correlated_failure_trace": True,
            "same_session_recovery": True,
            "canonical_recovery": True,
            "deployment_identity_stable": True,
        },
        "notes": (
            "Raw responses, prompts, markers, cookies, headers, governed traces, "
            "and request, session, trace, resource, and account identifiers were "
            "used only in memory and were not curated."
        ),
    }


def _post_chat(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    prompt: str,
    *,
    failure: bool = False,
) -> tuple[int, bytes]:
    origin = urllib.parse.urlsplit(base_url)
    headers = {
        "content-type": "application/json",
        "origin": f"{origin.scheme}://{origin.netloc}",
        "sec-fetch-site": "same-origin",
    }
    if failure:
        headers["x-tollchat-drill"] = FAILURE_MODE
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps({"message": prompt}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _proxy_hash(aws: list[str]) -> str:
    value = _aws(
        aws,
        "lambda",
        "get-function-configuration",
        "--function-name",
        "tollchat-chat-proxy",
        "--query",
        "CodeSha256",
        "--output",
        "text",
    )
    return _safe_proxy_hash(value)


def _records(
    aws: list[str], log_group: str, started: int, deadline: float
) -> list[dict[str, object]]:
    try:
        return _query_records(aws, log_group, started, deadline)
    except canonical.TracePending as error:
        raise TracePending("governed trace query exceeded its deadline") from error


def _trace_deadline(wait_seconds: int) -> float:
    return time.time() + wait_seconds


def run() -> dict[str, object]:
    preview_url = os.environ.get("PREVIEW_URL")
    if not preview_url:
        raise DrillError("set PREVIEW_URL to the Tailscale preview URL")
    wait_seconds = int(os.environ.get("TRACE_WAIT_SECONDS", "600"))
    if wait_seconds < 1:
        raise DrillError("TRACE_WAIT_SECONDS must be positive")
    aws = [
        "aws",
        "--profile",
        os.environ.get("AWS_PROFILE", "nova-toll"),
        "--region",
        os.environ.get("AWS_REGION", "us-east-1"),
    ]
    log_group = os.environ.get("RUNTIME_LOG_GROUP", "/aws/nova-toll/agentcore/traces")
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    failure_marker = f"failure-{uuid.uuid4().hex}"
    recovery_marker = f"verify-{uuid.uuid4().hex}"
    started = int(time.time()) - 1
    runtime_version = _runtime_version(aws)
    proxy_hash = _proxy_hash(aws)

    status, raw = _post_chat(
        opener,
        preview_url,
        f"Verify safe failure handling. Verification marker: {failure_marker}.",
        failure=True,
    )
    verify_failure_response(status, raw)
    deadline = _trace_deadline(wait_seconds)
    while True:
        try:
            failure = verify_failure_trace(
                _records(aws, log_group, started, deadline), failure_marker
            )
            break
        except TracePending:
            if time.time() >= deadline:
                raise
            time.sleep(min(5, max(0, deadline - time.time())))

    status, raw = _post_chat(
        opener,
        preview_url,
        f"{canonical.PROMPT} Verification marker: {recovery_marker}.",
    )
    canonical.verify_browser_response(status, raw)
    deadline = _trace_deadline(wait_seconds)
    while True:
        try:
            versions = verify_recovery_trace(
                _records(aws, log_group, started, deadline),
                recovery_marker,
                failure,
            )
            break
        except TracePending:
            if time.time() >= deadline:
                raise
            time.sleep(min(5, max(0, deadline - time.time())))

    if _runtime_version(aws) != runtime_version or _proxy_hash(aws) != proxy_hash:
        raise DrillError("deployment changed during the failure drill")
    return build_report(
        runtime_version=runtime_version,
        proxy_code_sha256=proxy_hash,
        versions=versions,
        timestamp=datetime.now(UTC),
    )


def main() -> int:
    try:
        report = run()
    except (
        DrillError,
        canonical.SmokeVerificationError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ):
        print(
            "AGENTCORE FAILURE DRILL FAILED: verification did not pass",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

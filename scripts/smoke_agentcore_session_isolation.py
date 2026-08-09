#!/usr/bin/env python3
"""Prove AgentCore sessions isolate turns, reset, and runtime processes."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from typing import cast


class IsolationVerificationError(ValueError):
    """The private-preview evidence does not prove session isolation."""


Post = Callable[[str, dict[str, object]], tuple[int, dict[str, object]]]


def _response_object(raw: bytes) -> dict[str, object]:
    try:
        value = cast(object, json.loads(raw))
    except json.JSONDecodeError:
        try:
            value = cast(
                object,
                json.loads(next(line for line in reversed(raw.splitlines()) if line)),
            )
        except (json.JSONDecodeError, StopIteration) as error:
            raise IsolationVerificationError(
                "preview response must contain JSON"
            ) from error
    if not isinstance(value, dict):
        raise IsolationVerificationError("preview response must be a JSON object")
    return cast(dict[str, object], value)


def _expect(
    post: Post,
    path: str,
    body: dict[str, object],
    status: int,
    error_code: str | None = None,
    retries: int = 0,
) -> None:
    for attempt in range(retries + 1):
        actual_status, response = post(path, body)
        error = response.get("error")
        error = cast(dict[str, object], error) if isinstance(error, dict) else None
        actual_code = (
            response.get("code") if response.get("type") == "error" else None
        ) or (error.get("code") if error else None)
        if actual_status == status and actual_code == error_code:
            return
        if actual_status != 502 or attempt == retries:
            raise IsolationVerificationError(
                f"{path} returned status={actual_status} code={actual_code!r}; "
                f"expected status={status} code={error_code!r}"
            )
        time.sleep(2**attempt)


def exercise_sessions(
    post_a: Post, post_b: Post, marker_a: str = "marker-a", marker_b: str = "marker-b"
) -> None:

    def chat(
        post: Post,
        marker: str,
        status: int = 200,
        code: str | None = None,
        retries: int = 0,
    ) -> None:
        _expect(
            post,
            "/api/chat",
            {"message": f"Price a trip from Dumfries to Westpark. {marker}"},
            status,
            code,
            retries,
        )

    chat(post_a, marker_a)
    chat(post_b, marker_b)
    for _ in range(4):
        chat(post_a, marker_a)
    chat(post_b, marker_b)
    chat(post_a, marker_a, code="turn_limit")
    _expect(post_a, "/api/reset", {}, 200)
    chat(post_b, marker_b)
    chat(post_a, marker_a, retries=3)


def _stage_counts(
    records: list[dict[str, str]], session_id: str
) -> dict[str, dict[str, int]]:
    stages: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for record in records:
        if record["session_id"] == session_id:
            stages[record["log_stream"]][record["stage"]].add(record["trace_id"])
    return {
        stream: {stage: len(trace_ids) for stage, trace_ids in stream_stages.items()}
        for stream, stream_stages in stages.items()
    }


def verify_isolation(
    records: list[dict[str, str]], session_a: set[str], session_b: set[str]
) -> dict[str, object]:
    stream_sessions: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if any(
            not isinstance(record.get(field), str) or not record[field]
            for field in ("session_id", "trace_id", "stage", "log_stream")
        ):
            raise IsolationVerificationError("malformed trace record")
        stream_sessions[record["log_stream"]].add(record["session_id"])
    target_sessions = session_a | session_b
    if session_a & session_b or any(
        len(sessions & target_sessions) > 1 for sessions in stream_sessions.values()
    ):
        raise IsolationVerificationError("a runtime log stream was shared by sessions")

    a_streams = [_stage_counts(records, session) for session in session_a]
    a_counts = [
        next(iter(streams.values())) for streams in a_streams if len(streams) == 1
    ]
    if (
        sum(
            counts.get("agent") == 5 and counts.get("invoke") == 6
            for counts in a_counts
        )
        != 1
    ):
        raise IsolationVerificationError("missing session A pre-reset turn evidence")
    if (
        len(session_a) != 2
        or sum(
            counts.get("agent") == 1 and counts.get("invoke") == 1
            for counts in a_counts
        )
        != 1
    ):
        raise IsolationVerificationError("session A did not receive a fresh runtime")

    if len(session_b) != 1:
        raise IsolationVerificationError(
            "session B runtime changed during session A reset"
        )
    b_streams = _stage_counts(records, next(iter(session_b)))
    if len(b_streams) != 1:
        raise IsolationVerificationError(
            "session B runtime changed during session A reset"
        )
    [b_counts] = b_streams.values()
    if b_counts.get("agent") != 3 or b_counts.get("invoke") != 3:
        raise IsolationVerificationError("session B turn evidence is incomplete")
    return {
        "interleaved_sessions": 2,
        "session_a_pre_reset_agent_invocations": 5,
        "session_a_turn_limit_invocations": 1,
        "session_a_post_reset_agent_invocations": 1,
        "session_b_agent_invocations": 3,
        "runtime_streams_disjoint": True,
        "turn_budget_isolated": True,
        "reset_isolated": True,
        "reset_rotated_runtime": True,
    }


def _http_post(base_url: str) -> Post:
    origin = urllib.parse.urlsplit(base_url)
    origin_header = f"{origin.scheme}://{origin.netloc}"
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )

    def post(path: str, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}{path}",
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                "origin": origin_header,
                "sec-fetch-site": "same-origin",
            },
            method="POST",
        )
        try:
            response = opener.open(request, timeout=60)
        except urllib.error.HTTPError as error:
            return error.code, _response_object(error.read())
        with response:
            return response.status, _response_object(response.read())

    return post


def _aws(aws: list[str], *arguments: str) -> str:
    result = subprocess.run(
        [*aws, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _live_runtime_version(aws: list[str]) -> str:
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
        raise IsolationVerificationError("could not identify the live runtime version")
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
    if not version.isdigit():
        raise IsolationVerificationError("could not identify the live runtime version")
    return version


def _query_records(
    aws: list[str], log_group: str, start_time: int, *, deadline: float
) -> list[dict[str, str]]:
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
        "fields @logStream, @message "
        "| filter @message like /tollchat.runtime_trace/ "
        "| sort @timestamp asc",
        "--query",
        "queryId",
        "--output",
        "text",
    )
    while time.time() < deadline:
        result = cast(
            dict[str, object],
            json.loads(_aws(aws, "logs", "get-query-results", "--query-id", query_id)),
        )
        status = result.get("status")
        if status == "Complete":
            break
        if status not in {"Scheduled", "Running"}:
            raise IsolationVerificationError(f"trace query failed: {status}")
        time.sleep(min(2, max(0, deadline - time.time())))
    else:
        raise IsolationVerificationError("trace query exceeded deadline")

    records: list[dict[str, str]] = []
    for raw_row in cast(list[object], result.get("results", [])):
        if not isinstance(raw_row, list):
            continue
        row: dict[str, object] = {}
        for raw_item in cast(list[object], raw_row):
            if not isinstance(raw_item, dict):
                continue
            item = cast(dict[object, object], raw_item)
            field, value = item.get("field"), item.get("value")
            if isinstance(field, str):
                row[field] = value
        try:
            message = cast(object, json.loads(str(row["@message"])))
        except (KeyError, json.JSONDecodeError):
            continue
        if not isinstance(message, dict):
            continue
        message = cast(dict[str, object], message)
        if message.get("record_type") != "tollchat.runtime_trace":
            continue
        values: dict[str, object] = {
            "session_id": message.get("session_id"),
            "trace_id": message.get("trace_id"),
            "stage": message.get("stage"),
            "log_stream": row.get("@logStream"),
        }
        if all(isinstance(value, str) and value for value in values.values()):
            record = {key: cast(str, value) for key, value in values.items()}
            if isinstance(message.get("payload"), str):
                record["payload"] = cast(str, message["payload"])
            records.append(record)
    return records


def _sessions_for_marker(records: list[dict[str, str]], marker: str) -> set[str]:
    matches = {
        record["session_id"]
        for record in records
        if marker in record.get("payload", "")
    }
    if not matches:
        raise IsolationVerificationError(
            f"could not correlate a runtime session for {marker}"
        )
    return matches


def main() -> int:
    preview_url = os.environ.get("PREVIEW_URL")
    if not preview_url:
        raise SystemExit("set PREVIEW_URL to the Tailscale-reachable preview URL")
    profile = os.environ.get("AWS_PROFILE", "nova-toll")
    region = os.environ.get("AWS_REGION", "us-east-1")
    log_group = os.environ.get("RUNTIME_LOG_GROUP", "/aws/nova-toll/agentcore/traces")
    wait_seconds = int(os.environ.get("TRACE_WAIT_SECONDS", "600"))
    aws = ["aws", "--profile", profile, "--region", region]
    runtime_version = _live_runtime_version(aws)
    marker_a, marker_b = f"verify-{uuid.uuid4().hex}", f"verify-{uuid.uuid4().hex}"
    started = int(time.time()) - 1
    exercise_sessions(
        _http_post(preview_url), _http_post(preview_url), marker_a, marker_b
    )

    deadline = time.time() + wait_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            records = _query_records(aws, log_group, started, deadline=deadline)
            checks = verify_isolation(
                records,
                _sessions_for_marker(records, marker_a),
                _sessions_for_marker(records, marker_b),
            )
            break
        except IsolationVerificationError as error:
            last_error = error
            time.sleep(5)
    else:
        raise IsolationVerificationError(
            f"trace evidence incomplete after {wait_seconds}s: {last_error}"
        )

    report = {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "issues": [97, 108, 123],
        "status": "passed",
        "agent_runtime_version": runtime_version,
        "scenario": (
            "Two backend-owned private-preview browser sessions with turn exhaustion "
            "and reset rotation"
        ),
        "evidence_type": (
            "Metadata-only live AgentCore session-ownership and isolation verification"
        ),
        "checks": checks,
        "notes": (
            "Raw responses, trace records, session identifiers, and log-stream identifiers "
            "were used only in memory and were not curated."
        ),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "drill_agentcore_failure",
    ROOT / "scripts" / "drill_agentcore_failure.py",
)
assert SPEC and SPEC.loader
drill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drill)

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FAILURE_TRACE = "1" * 32
RECOVERY_TRACE = "2" * 32


def _records(
    stage: str,
    payload: dict[str, object],
    *,
    trace_id: str,
    request_id: str,
    session_id: str = SESSION,
):
    serialized = json.dumps(payload, separators=(",", ":"))
    width = max(1, (len(serialized) + 1) // 2)
    parts = [
        serialized[index : index + width] for index in range(0, len(serialized), width)
    ]
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    return [
        {
            "record_version": 1,
            "record_type": "tollchat.runtime_trace",
            "stage": stage,
            "trace_id": trace_id,
            "span_id": f"{len(stage):016x}",
            "session_id": session_id,
            "aws_request_id": request_id,
            "chunk_index": index,
            "chunk_count": len(parts),
            "sha256": digest,
            "payload": part,
        }
        for index, part in enumerate(parts)
    ]


def _failure_records(marker: str = "failure-marker"):
    correlation = {"trace_id": FAILURE_TRACE, "request_id": "failure-request"}
    return [
        *_records(
            "input_guardrail",
            {"request": {"content": [{"text": {"text": marker}}]}},
            **correlation,
        ),
        *_records(
            "invoke",
            {
                "timing": {"started_at": "2026-08-09T00:00:00Z"},
                "result": {"error": drill.RUNTIME_SAFE_ERROR},
                "error": {
                    "type": "DeployedFailureDrill",
                    "message": "[REDACTED]",
                },
            },
            **correlation,
        ),
    ]


def _recovery_records(marker: str = "recovery-marker"):
    payload = {
        "request": {"prompt": marker},
        "response": {"answer": "The toll is $12.15."},
        "tool_calls": [
            {
                "name": "i66_route",
                "arguments": {
                    "origin": "I-66 West",
                    "destination": "Washington",
                    "at_time": "2026-07-29T08:30:00-04:00",
                },
                "result": [{"json": {"total_usd": "12.15"}}],
            }
        ],
        "model_version": "gpt-5-mini",
        "system_prompt_version": "1.26.0",
        "toolset_version": "1.24.0",
    }
    return _records(
        "agent",
        payload,
        trace_id=RECOVERY_TRACE,
        request_id="recovery-request",
    )


def test_exact_failure_response_accepts_no_internal_content():
    drill.verify_failure_response(
        200,
        (
            b'{"type":"error","code":"agent_unavailable",'
            b'"message":"TollChat could not complete that request. Please try again."}\n'
        ),
    )

    for status, body in (
        (502, b"{}"),
        (
            200,
            b'{"type":"error","code":"agent_unavailable","message":"RuntimeError"}\n',
        ),
        (
            200,
            b'{"type":"error","code":"agent_unavailable","message":"safe","trace":"x"}\n',
        ),
    ):
        with pytest.raises(drill.DrillError, match="browser error contract"):
            drill.verify_failure_response(status, body)


def test_trace_contract_binds_failure_and_recovery_to_exact_requests():
    failure = drill.verify_failure_trace(_failure_records(), "failure-marker")
    versions = drill.verify_recovery_trace(
        [*_failure_records(), *_recovery_records()],
        "recovery-marker",
        failure,
    )

    assert failure == {
        "session_id": SESSION,
        "trace_id": FAILURE_TRACE,
        "aws_request_id": "failure-request",
    }
    assert versions == {
        "model_version": "gpt-5-mini",
        "system_prompt_version": "1.26.0",
        "toolset_version": "1.24.0",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda records: records[-1].update(trace_id="3" * 32),
        lambda records: records[-1].update(aws_request_id="other-request"),
        lambda records: records[-1].update(
            payload=json.dumps(
                {
                    "result": {"error": drill.RUNTIME_SAFE_ERROR},
                    "error": {"type": "RuntimeError", "message": "[REDACTED]"},
                },
                separators=(",", ":"),
            )
        ),
    ],
)
def test_failure_trace_rejects_ambiguous_or_wrong_correlation(mutate):
    records = _failure_records()
    mutate(records)

    with pytest.raises(drill.DrillError):
        drill.verify_failure_trace(records, "failure-marker")


def test_failure_trace_rejects_contradictory_request_records():
    base = _failure_records()
    contradictory = (
        _records(
            "invoke",
            {
                "timing": {"started_at": "2026-08-09T00:00:00Z"},
                "result": {"error": drill.RUNTIME_SAFE_ERROR},
                "error": {"type": "RuntimeError", "message": "[REDACTED]"},
            },
            trace_id=FAILURE_TRACE,
            request_id="failure-request",
        ),
        _records(
            "agent",
            {"response": {"answer": "polluted output"}},
            trace_id=FAILURE_TRACE,
            request_id="failure-request",
        ),
    )
    for record in contradictory[0]:
        record["span_id"] = "f" * 16

    for extra in contradictory:
        with pytest.raises(drill.DrillError, match="failure trace"):
            drill.verify_failure_trace([*base, *extra], "failure-marker")


@pytest.mark.parametrize("stage", ["agent", "invoke"])
def test_failure_trace_rejects_partial_contradictory_request_record(stage):
    extra = _records(
        stage,
        {"response": {"answer": "contradiction"}},
        trace_id=FAILURE_TRACE,
        request_id="failure-request",
    )
    for record in extra:
        record["span_id"] = "f" * 16

    with pytest.raises(drill.DrillError, match="contradictory request records"):
        drill.verify_failure_trace([*_failure_records(), extra[0]], "failure-marker")


def test_recovery_requires_same_session_and_distinct_request():
    failure = drill.verify_failure_trace(_failure_records(), "failure-marker")
    for records in (
        _recovery_records(),
        _records(
            "agent",
            {"request": {"prompt": "recovery-marker"}},
            trace_id=FAILURE_TRACE,
            request_id="failure-request",
        ),
    ):
        records = [dict(record) for record in records]
        if records[0]["trace_id"] == RECOVERY_TRACE:
            for record in records:
                record["session_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        with pytest.raises(drill.DrillError):
            drill.verify_recovery_trace(records, "recovery-marker", failure)


def test_report_contains_only_reviewable_metadata():
    report = drill.build_report(
        runtime_version="20",
        proxy_code_sha256="A" * 43 + "=",
        versions={
            "model_version": "gpt-5-mini",
            "system_prompt_version": "1.26.0",
            "toolset_version": "1.24.0",
        },
        timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert report["issues"] == [125]
    assert report["status"] == "passed"
    assert set(report["checks"]) == {
        "trusted_private_browser_path",
        "injected_runtime_exception",
        "exact_safe_error_contract",
        "correlated_failure_trace",
        "same_session_recovery",
        "canonical_recovery",
        "deployment_identity_stable",
    }
    serialized = json.dumps(report)
    assert SESSION not in serialized
    assert "failure-marker" not in serialized


def test_run_gives_recovery_a_fresh_trace_deadline(monkeypatch):
    deadlines: list[float] = []
    responses = [
        (200, drill._FAILURE_BODY),
        (200, b"canonical"),
    ]
    identities = iter(["20", "20"])
    hashes = iter(["A" * 43 + "=", "A" * 43 + "="])
    monkeypatch.setenv("PREVIEW_URL", "https://preview.tollchat.ai/")
    monkeypatch.setattr(drill, "_runtime_version", lambda _aws: next(identities))
    monkeypatch.setattr(drill, "_proxy_hash", lambda _aws: next(hashes))
    monkeypatch.setattr(drill, "_post_chat", lambda *_args, **_kwargs: responses.pop(0))
    deadline_values = iter([100.0, 200.0])
    monkeypatch.setattr(drill, "_trace_deadline", lambda _wait: next(deadline_values))
    monkeypatch.setattr(
        drill,
        "_records",
        lambda _aws, _group, _started, deadline: deadlines.append(deadline) or [],
    )
    monkeypatch.setattr(
        drill,
        "verify_failure_trace",
        lambda _records, _marker: {
            "session_id": SESSION,
            "trace_id": FAILURE_TRACE,
            "aws_request_id": "failure-request",
        },
    )
    monkeypatch.setattr(drill.canonical, "verify_browser_response", lambda *_args: [])
    monkeypatch.setattr(
        drill,
        "verify_recovery_trace",
        lambda *_args: {
            "model_version": "gpt-5-mini",
            "system_prompt_version": "1.26.0",
            "toolset_version": "1.24.0",
        },
    )

    assert drill.run()["status"] == "passed"
    assert deadlines == [100.0, 200.0]


def test_documented_script_invocation_reaches_sanitized_preflight():
    env = {key: value for key, value in os.environ.items() if key != "PREVIEW_URL"}

    result = subprocess.run(
        [sys.executable, "scripts/drill_agentcore_failure.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "AGENTCORE FAILURE DRILL FAILED: verification did not pass\n"
    )

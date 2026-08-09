from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoke_agentcore_canonical",
    ROOT / "scripts" / "smoke_agentcore_canonical.py",
)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRACE = "1" * 32


def _trace_records(stage: str, payload: dict[str, object], *, chunks: int = 2):
    serialized = json.dumps(payload, separators=(",", ":"))
    width = max(1, (len(serialized) + chunks - 1) // chunks)
    parts = [
        serialized[index : index + width] for index in range(0, len(serialized), width)
    ]
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    return [
        {
            "record_version": 1,
            "record_type": "tollchat.runtime_trace",
            "stage": stage,
            "trace_id": TRACE,
            "span_id": f"{len(stage):016x}",
            "session_id": SESSION,
            "aws_request_id": "request-id",
            "chunk_index": index,
            "chunk_count": len(parts),
            "sha256": digest,
            "payload": part,
        }
        for index, part in enumerate(parts)
    ]


def _agent_payload(marker: str = "verify-marker") -> dict[str, object]:
    return {
        "request": {"prompt": f"canonical request {marker}"},
        "response": {"answer": "The toll is $12.15."},
        "tool_calls": [
            {
                "name": "i66_route",
                "arguments": {
                    "origin": "I-66 West",
                    "destination": "Washington",
                    "at_time": "2026-07-29T08:30:00-04:00",
                },
                "result": [
                    {"text": json.dumps({"total_usd": "12.15"})},
                ],
            }
        ],
        "model_version": "gpt-5-mini",
        "system_prompt_version": "1.26.0",
        "toolset_version": "1.24.0",
    }


def _browser_body(amount: str = "$12.15", disclaimer: str | None = None) -> bytes:
    disclaimer = disclaimer if disclaimer is not None else smoke.DISCLAIMER
    events = [
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
        {
            "type": "answer",
            "text": f"The toll is {amount}.\n\n{disclaimer}",
            "blocked": False,
        },
    ]
    return ("\n".join(json.dumps(event) for event in events) + "\n").encode()


def test_verify_accepts_exact_browser_and_trace_contract():
    events = smoke.verify_browser_response(200, _browser_body())
    trace = smoke.verify_trace_contract(
        _trace_records("agent", _agent_payload()), "verify-marker"
    )

    assert [event["status"] for event in events[:-1]] == ["running", "completed"]
    assert trace == {
        "model_version": "gpt-5-mini",
        "system_prompt_version": "1.26.0",
        "toolset_version": "1.24.0",
    }


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (502, _browser_body()),
        (200, _browser_body("$9.99")),
        (200, _browser_body(disclaimer="Trust me, probably.")),
        (200, b'{"type":"error","code":"agent_unavailable"}\n'),
    ],
)
def test_browser_contract_fails_closed_without_echoing_content(
    status: int, body: bytes
):
    with pytest.raises(smoke.SmokeVerificationError) as error:
        smoke.verify_browser_response(status, body)

    assert "$9.99" not in str(error.value)
    assert "Trust me" not in str(error.value)
    assert "agent_unavailable" not in str(error.value)


def test_browser_contract_rejects_extra_or_out_of_order_events():
    events = [json.loads(line) for line in _browser_body().splitlines()]
    for invalid in ([events[1], events[0], events[2]], [*events, events[2]]):
        with pytest.raises(
            smoke.SmokeVerificationError, match="browser event contract"
        ):
            smoke.verify_browser_response(
                200, ("\n".join(json.dumps(event) for event in invalid) + "\n").encode()
            )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["tool_calls"].append(payload["tool_calls"][0]),
        lambda payload: payload["tool_calls"][0].update(name="i495_route"),
        lambda payload: payload["tool_calls"][0]["arguments"].update(
            destination="Fairfax Drive"
        ),
        lambda payload: payload["tool_calls"][0].update(
            result=[{"text": json.dumps({"total_usd": "9.99"})}]
        ),
    ],
)
def test_trace_contract_rejects_wrong_trajectory_or_result(mutate):
    payload = _agent_payload()
    mutate(payload)

    with pytest.raises(smoke.SmokeVerificationError, match="deployed trace contract"):
        smoke.verify_trace_contract(_trace_records("agent", payload), "verify-marker")


def test_trace_contract_waits_for_complete_chunks_and_rejects_bad_hash():
    records = _trace_records("agent", _agent_payload())
    with pytest.raises(smoke.TracePending):
        smoke.verify_trace_contract(records[:-1], "verify-marker")

    records[0]["sha256"] = "0" * 64
    with pytest.raises(smoke.SmokeVerificationError, match="trace integrity"):
        smoke.verify_trace_contract(records, "verify-marker")


def test_trace_contract_requires_one_marker_session():
    records = _trace_records("agent", _agent_payload("missing"))
    with pytest.raises(smoke.TracePending):
        smoke.verify_trace_contract(records, "verify-marker")

    duplicate = [
        dict(record, session_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        for record in _trace_records("agent", _agent_payload())
    ]
    with pytest.raises(smoke.SmokeVerificationError, match="correlation"):
        smoke.verify_trace_contract(
            [*_trace_records("agent", _agent_payload()), *duplicate], "verify-marker"
        )


def test_report_is_metadata_only():
    report = smoke.build_report(
        runtime_version="21",
        versions={
            "model_version": "gpt-5-mini",
            "system_prompt_version": "1.26.0",
            "toolset_version": "1.24.0",
        },
        timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert report["status"] == "passed"
    assert report["case_version"] == "i66-eastbound-full-v1"
    assert report["checks"] == {
        "private_browser_path": True,
        "ordered_tool_lifecycle": True,
        "exact_i66_trajectory": True,
        "historical_rds_total": True,
        "required_disclaimer": True,
    }
    serialized = json.dumps(report)
    for raw in (SESSION, TRACE, "verify-marker", "canonical request", "request-id"):
        assert raw not in serialized


@pytest.mark.parametrize(
    "unsafe",
    [
        "secret value with spaces",
        "AKIAABCDEFGHIJKLMNOP",  # gitleaks:allow (synthetic rejection fixture)
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/example",
        "model-123456789012",
    ],
)
def test_safe_version_rejects_content_credential_and_account_metadata(unsafe: str):
    with pytest.raises(smoke.SmokeVerificationError, match="version metadata"):
        smoke.build_report(
            runtime_version="21",
            versions={
                "model_version": unsafe,
                "system_prompt_version": "1.26.0",
                "toolset_version": "1.24.0",
            },
            timestamp=datetime.now(UTC),
        )


def test_report_requires_numeric_runtime_version():
    with pytest.raises(
        smoke.SmokeVerificationError, match=r"runtime.*version metadata"
    ):
        smoke.build_report(
            runtime_version="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/x",
            versions={
                "model_version": "gpt-5-mini",
                "system_prompt_version": "1.26.0",
                "toolset_version": "1.24.0",
            },
            timestamp=datetime.now(UTC),
        )


def test_main_sanitizes_aws_timeouts(monkeypatch, capsys):
    monkeypatch.setattr(
        smoke,
        "run",
        lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired(["aws", "secret"], 1)),
    )

    assert smoke.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "CANONICAL SMOKE FAILED: an external dependency call failed\n"
    )
    assert "secret" not in captured.err


def test_run_rejects_runtime_version_drift(monkeypatch):
    versions = iter(["19", "20"])
    monkeypatch.setenv("PREVIEW_URL", "https://preview.example")
    monkeypatch.setattr(smoke, "_runtime_version", lambda _aws: next(versions))
    monkeypatch.setattr(smoke, "_post_chat", lambda _url, _marker: (200, b"{}"))
    monkeypatch.setattr(smoke, "verify_browser_response", lambda _status, _raw: [])
    monkeypatch.setattr(smoke, "_query_records", lambda *_args: [])
    monkeypatch.setattr(
        smoke,
        "verify_trace_contract",
        lambda _records, _marker: {
            "model_version": "gpt-5-mini",
            "system_prompt_version": "1.26.0",
            "toolset_version": "1.24.0",
        },
    )

    with pytest.raises(smoke.SmokeVerificationError, match="runtime changed"):
        smoke.run()

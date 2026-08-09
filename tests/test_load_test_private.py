import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import load_test_private as load

ROOT = Path(__file__).resolve().parents[1]


def _browser_body() -> bytes:
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
            "text": (
                "$12.15. Estimates only. Verify current rates with the toll "
                "operator before travel."
            ),
            "blocked": False,
        },
    ]
    return b"\n".join(json.dumps(event).encode() for event in events)


def _healthy_metrics() -> dict[str, float]:
    return {
        "proxy_latency_p99_ms": 20_000,
        "agentcore_active_sessions_max": 5,
        "rds_cpu_max_percent": 45,
        "rds_free_memory_min_bytes": 80 * 1024 * 1024,
        "rds_connections_max": 8,
        "rds_cpu_credit_min": 280,
        "proxy_errors": 0,
        "proxy_failures": 0,
        "agentcore_errors": 0,
        "agentcore_throttles": 0,
        "proxy_concurrent_executions_max": 5,
        "proxy_invocations": 15,
        "agentcore_invocations": 15,
        "fetcher_errors": 0,
        "loader_errors": 0,
        "load_success_i95": 1,
        "load_success_i66": 1,
    }


def test_run_requests_uses_five_workers_for_fifteen_valid_calls():
    lock = threading.Lock()
    active = 0
    peak = 0
    fired_while_active = 0
    session_calls: list[int] = []

    def new_session():
        calls = 0
        with lock:
            index = len(session_calls)
            session_calls.append(calls)

        def post(_marker: str) -> tuple[int, bytes]:
            nonlocal active, peak, calls
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
                calls += 1
                session_calls[index] = calls
            return 200, _browser_body()

        return post

    def fire() -> None:
        nonlocal fired_while_active
        with lock:
            fired_while_active = active

    observations, observed_peak, _fired_at = load.run_requests(new_session, fire)

    assert len(observations) == 15
    assert peak == observed_peak == 5
    assert fired_while_active == 5
    assert sorted(session_calls) == [3, 3, 3, 3, 3]
    assert all(item["ended_at"] >= item["started_at"] for item in observations)


def test_loader_events_must_overlap_request_window_for_both_feeds():
    observations = [{"started_at": 10.0, "ended_at": 20.0, "latency_ms": 10_000.0}]

    load.verify_ingestion_overlap(observations, {"i95": 12.0, "i66": 18.0})

    with pytest.raises(load.LoadVerificationError, match="overlap"):
        load.verify_ingestion_overlap(observations, {"i95": 12.0, "i66": 21.0})


def test_post_factory_reuses_one_browser_session(monkeypatch):
    openers: list[object] = []

    def post(_base_url: str, _marker: str, *, opener: object):
        openers.append(opener)
        return 200, _browser_body()

    monkeypatch.setattr(load.canonical, "_post_chat", post)
    session = load._post_factory("https://preview.example")

    session("one")
    session("two")

    assert len(openers) == 2
    assert openers[0] is openers[1]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proxy_latency_p99_ms", 45_000),
        ("agentcore_active_sessions_max", 10),
        ("rds_cpu_max_percent", 70.01),
        ("rds_free_memory_min_bytes", 64 * 1024 * 1024 - 1),
        ("rds_connections_max", 60),
        ("rds_cpu_credit_min", 71.99),
        ("proxy_errors", 1),
        ("proxy_failures", 1),
        ("agentcore_errors", 1),
        ("agentcore_throttles", 1),
        ("proxy_concurrent_executions_max", 4),
        ("proxy_invocations", 14),
        ("agentcore_invocations", 14),
        ("fetcher_errors", 1),
        ("loader_errors", 1),
        ("load_success_i95", 0),
        ("load_success_i66", 0),
    ],
)
def test_thresholds_fail_closed(field: str, value: float):
    metrics = _healthy_metrics()
    metrics[field] = value

    with pytest.raises(load.LoadVerificationError, match=field):
        load.verify_thresholds(metrics)


def test_report_contains_only_aggregate_reviewable_metadata():
    metrics = _healthy_metrics()
    metrics.update(
        {
            "rds_read_latency_max_ms": 2.5,
            "rds_write_latency_max_ms": 3.5,
            "rds_disk_queue_depth_max": 0.4,
        }
    )
    report = load.build_report(
        runtime_version="22",
        proxy_code_sha256="A" * 43 + "=",
        rds_class="db.t4g.micro",
        rds_engine_version="17.9",
        metrics=metrics,
        latencies_ms=[float(value) for value in range(1, 16)],
        timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert report["issues"] == [95, 125]
    assert report["status"] == "passed"
    assert report["load_profile"] == {
        "workers": 5,
        "requests_per_worker": 3,
        "requests": 15,
    }
    assert report["rollout"]["maximum_proxy_concurrency"] == 5
    assert report["rollout"]["rds_resize_required"] is False
    serialized = json.dumps(report)
    for unsafe in ("arn:aws", "preview.tollchat.ai", "session_id", "trace_id"):
        assert unsafe not in serialized


def test_report_rejects_unsafe_deployment_identity():
    with pytest.raises(load.LoadVerificationError, match="identity"):
        load.build_report(
            runtime_version="arn:aws:secret",
            proxy_code_sha256="A" * 43 + "=",
            rds_class="db.t4g.micro",
            rds_engine_version="17.9",
            metrics=_healthy_metrics(),
            latencies_ms=[1.0] * 15,
            timestamp=datetime.now(UTC),
        )


def test_report_rejects_client_latency_at_timeout_margin():
    with pytest.raises(load.LoadVerificationError, match="client_latency_p99_ms"):
        load.build_report(
            runtime_version="22",
            proxy_code_sha256="A" * 43 + "=",
            rds_class="db.t4g.micro",
            rds_engine_version="17.9",
            metrics=_healthy_metrics(),
            latencies_ms=[1.0] * 14 + [45_000.0],
            timestamp=datetime.now(UTC),
        )


def test_cli_sanitizes_preflight_failure_without_preview_url():
    env = {key: value for key, value in os.environ.items() if key != "PREVIEW_URL"}

    result = subprocess.run(
        [sys.executable, "scripts/load_test_private.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "PRIVATE LOAD TEST FAILED: verification did not pass\n"

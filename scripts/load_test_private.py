#!/usr/bin/env python3
"""Run the private five-request ceiling while both toll feeds ingest."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from typing import cast

try:
    from scripts import smoke_agentcore_canonical as canonical
except ImportError:  # Direct `python scripts/load_test_private.py` execution.
    import smoke_agentcore_canonical as canonical


WORKERS = 5
REQUESTS_PER_WORKER = 3
REQUEST_COUNT = WORKERS * REQUESTS_PER_WORKER
CASE_VERSION = "private-ceiling-ingestion-v1"
_RUNTIME_VERSION = re.compile(r"[1-9]\d{0,9}\Z")
_CODE_SHA256 = re.compile(r"[A-Za-z0-9+/]{43}=\Z")
_RDS_CLASS = re.compile(r"db\.[a-z0-9.]+\Z")
_ENGINE_VERSION = re.compile(r"\d+(?:\.\d+)+\Z")
_ALARM_NAMES = {
    "toll-fetcher-errors",
    "toll-freshness-i66",
    "toll-freshness-i95",
    "toll-loader-errors",
    "toll-loader-onfailure-queue",
    "toll-rds-connections",
    "toll-rds-cpu",
    "toll-rds-cpu-credits",
    "toll-rds-free-memory",
    "toll-rds-free-storage",
    "tollchat-agentcore-active-sessions",
    "tollchat-chat-proxy-errors",
    "tollchat-chat-proxy-failures",
    "tollchat-chat-proxy-latency",
}

Observation = dict[str, float]
PostChat = Callable[[str], tuple[int, bytes]]
PostChatFactory = Callable[[], PostChat]


class LoadVerificationError(ValueError):
    """The private load run cannot be accepted as launch evidence."""


def _aws(aws: list[str], *arguments: str, timeout: float = 30.0) -> str:
    return subprocess.run(
        [*aws, *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=max(1.0, timeout),
    ).stdout.strip()


def _aws_json(aws: list[str], *arguments: str, timeout: float = 30.0) -> object:
    return json.loads(_aws(aws, *arguments, timeout=timeout))


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values or not 0 < percentile <= 100:
        raise LoadVerificationError("latency sample was incomplete")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def run_requests(
    post_chat_factory: PostChatFactory, invoke_ingestion: Callable[[], None]
) -> tuple[list[Observation], int, float]:
    """Run five workers and fire ingestion once every worker is in flight."""
    barrier = threading.Barrier(WORKERS + 1)
    condition = threading.Condition()
    active = 0
    peak = 0

    def one(post_chat: PostChat, marker: str) -> Observation:
        nonlocal active, peak
        started = time.time()
        with condition:
            active += 1
            peak = max(peak, active)
            condition.notify_all()
        try:
            status, raw = post_chat(marker)
            canonical.verify_browser_response(status, raw)
        finally:
            with condition:
                active -= 1
                condition.notify_all()
        ended = time.time()
        return {
            "started_at": started,
            "ended_at": ended,
            "latency_ms": (ended - started) * 1000,
        }

    def worker() -> list[Observation]:
        post_chat = post_chat_factory()
        barrier.wait()
        return [
            one(post_chat, f"load-{uuid.uuid4().hex}")
            for _ in range(REQUESTS_PER_WORKER)
        ]

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(worker) for _ in range(WORKERS)]
        barrier.wait()
        with condition:
            if not condition.wait_for(
                lambda: active == WORKERS,  # pyright: ignore[reportUnnecessaryComparison]
                timeout=10,
            ):
                raise LoadVerificationError("proxy concurrency ceiling was not reached")
        invoke_ingestion()
        fired_at = time.time()
        observations = [item for future in futures for item in future.result()]

    if (
        len(observations) != REQUEST_COUNT or peak != WORKERS  # pyright: ignore[reportUnnecessaryComparison]
    ):
        raise LoadVerificationError("proxy concurrency ceiling was not exercised")
    return observations, peak, fired_at


def verify_ingestion_overlap(
    observations: list[Observation], events: dict[str, float]
) -> None:
    if set(events) != {"i95", "i66"} or not observations:
        raise LoadVerificationError("ingestion overlap evidence was incomplete")
    started = min(item["started_at"] for item in observations)
    ended = max(item["ended_at"] for item in observations)
    if any(not started <= timestamp <= ended for timestamp in events.values()):
        raise LoadVerificationError("ingestion did not overlap the request window")


def verify_thresholds(metrics: dict[str, float]) -> None:
    rules: dict[str, Callable[[float], bool]] = {
        "proxy_latency_p99_ms": lambda value: value < 45_000,
        "agentcore_active_sessions_max": lambda value: value < 10,
        "rds_cpu_max_percent": lambda value: value <= 70,
        "rds_free_memory_min_bytes": lambda value: value >= 64 * 1024 * 1024,
        "rds_connections_max": lambda value: value < 60,
        "rds_cpu_credit_min": lambda value: value >= 72,
        "proxy_errors": lambda value: value == 0,
        "proxy_failures": lambda value: value == 0,
        "agentcore_errors": lambda value: value == 0,
        "agentcore_throttles": lambda value: value == 0,
        "fetcher_errors": lambda value: value == 0,
        "loader_errors": lambda value: value == 0,
        "proxy_concurrent_executions_max": lambda value: value == WORKERS,
        "proxy_invocations": lambda value: value >= REQUEST_COUNT,
        "agentcore_invocations": lambda value: value >= REQUEST_COUNT,
        "load_success_i95": lambda value: value >= 1,
        "load_success_i66": lambda value: value >= 1,
    }
    for field, accepts in rules.items():
        value = metrics.get(field)
        if value is None or not math.isfinite(value) or not accepts(value):
            raise LoadVerificationError(f"{field} crossed its rollout threshold")


def build_report(
    *,
    runtime_version: str,
    proxy_code_sha256: str,
    rds_class: str,
    rds_engine_version: str,
    metrics: dict[str, float],
    latencies_ms: list[float],
    timestamp: datetime,
) -> dict[str, object]:
    """Build the only output safe to curate under eval/results/."""
    if (
        not _RUNTIME_VERSION.fullmatch(runtime_version)
        or not _CODE_SHA256.fullmatch(proxy_code_sha256)
        or not _RDS_CLASS.fullmatch(rds_class)
        or not _ENGINE_VERSION.fullmatch(rds_engine_version)
    ):
        raise LoadVerificationError("deployment identity was unsafe")
    if len(latencies_ms) != REQUEST_COUNT or any(
        not math.isfinite(value) or value < 0 for value in latencies_ms
    ):
        raise LoadVerificationError("latency sample was incomplete")
    verify_thresholds(metrics)
    client_p99 = _nearest_rank(latencies_ms, 99)
    if client_p99 >= 45_000:
        raise LoadVerificationError(
            "client_latency_p99_ms crossed its rollout threshold"
        )

    observed = {
        "client_latency_ms": {
            "p50": round(_nearest_rank(latencies_ms, 50), 3),
            "p95": round(_nearest_rank(latencies_ms, 95), 3),
            "p99": round(client_p99, 3),
            "maximum": round(max(latencies_ms), 3),
        },
        **{field: round(value, 6) for field, value in sorted(metrics.items())},
    }
    return {
        "timestamp": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "issues": [95, 125],
        "status": "passed",
        "case_version": CASE_VERSION,
        "scenario": "Private proxy ceiling with both toll feeds ingesting",
        "evidence_type": "Metadata-only deployed load and ingestion baseline",
        "deployment": {
            "agent_runtime_version": runtime_version,
            "proxy_code_sha256": proxy_code_sha256,
            "rds_class": rds_class,
            "rds_engine_version": rds_engine_version,
        },
        "load_profile": {
            "workers": WORKERS,
            "requests_per_worker": REQUESTS_PER_WORKER,
            "requests": REQUEST_COUNT,
        },
        "observed": observed,
        "thresholds": {
            "proxy_latency_p99_ms": 45_000,
            "agentcore_active_sessions_max_exclusive": 10,
            "rds_cpu_max_percent": 70,
            "rds_free_memory_min_bytes": 64 * 1024 * 1024,
            "rds_connections_max_exclusive": 60,
            "rds_cpu_credit_min": 72,
            "errors_failures_and_throttles": 0,
        },
        "rollout": {
            "maximum_proxy_concurrency": WORKERS,
            "pause_on_any_alarm": True,
            "rds_resize_required": False,
        },
        "checks": {
            "private_browser_contract": True,
            "configured_proxy_ceiling_exercised": True,
            "both_feeds_loaded_during_requests": True,
            "all_requests_succeeded": True,
            "deployment_identity_stable": True,
            "alarms_healthy_before_and_after": True,
            "rollout_thresholds_preserved": True,
        },
        "notes": (
            "Raw prompts, responses, cookies, endpoints, AWS identifiers, request "
            "markers, log events, and session or trace identifiers were used only "
            "in memory and were not curated."
        ),
    }


def _preflight(aws: list[str]) -> dict[str, str]:
    concurrency = cast(
        dict[str, object],
        _aws_json(
            aws,
            "lambda",
            "get-function-concurrency",
            "--function-name",
            "tollchat-chat-proxy",
        ),
    )
    if concurrency.get("ReservedConcurrentExecutions") != WORKERS:
        raise LoadVerificationError("proxy concurrency did not match the candidate")

    db_result = cast(
        dict[str, object],
        _aws_json(
            aws,
            "rds",
            "describe-db-instances",
            "--db-instance-identifier",
            "nova-toll-db",
        ),
    )
    instances = cast(list[object], db_result.get("DBInstances", []))
    if len(instances) != 1 or not isinstance(instances[0], dict):
        raise LoadVerificationError("RDS identity was incomplete")
    db = cast(dict[str, object], instances[0])
    if db.get("DBInstanceStatus") != "available":
        raise LoadVerificationError("RDS was not available")

    for rule_name in ("toll-poll-tick", "toll-poll-tick-i66"):
        rule = cast(
            dict[str, object],
            _aws_json(aws, "events", "describe-rule", "--name", rule_name),
        )
        if rule.get("State") != "ENABLED":
            raise LoadVerificationError("scheduled ingestion was not enabled")

    alarms_result = cast(
        dict[str, object],
        _aws_json(
            aws,
            "cloudwatch",
            "describe-alarms",
            "--alarm-names",
            *sorted(_ALARM_NAMES),
        ),
    )
    alarms = cast(list[object], alarms_result.get("MetricAlarms", []))
    states = {
        cast(str, alarm.get("AlarmName")): alarm.get("StateValue")
        for item in alarms
        if isinstance(item, dict)
        for alarm in [cast(dict[str, object], item)]
    }
    if set(states) != _ALARM_NAMES or any(state != "OK" for state in states.values()):
        raise LoadVerificationError("launch alarms were not healthy")

    runtime_id = _aws(
        aws,
        "bedrock-agentcore-control",
        "list-agent-runtimes",
        "--query",
        "agentRuntimes[?agentRuntimeName=='nova_toll'].agentRuntimeId | [0]",
        "--output",
        "text",
    )
    runtime_arn = _aws(
        aws,
        "bedrock-agentcore-control",
        "list-agent-runtimes",
        "--query",
        "agentRuntimes[?agentRuntimeName=='nova_toll'].agentRuntimeArn | [0]",
        "--output",
        "text",
    )
    runtime_version = _aws(
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
    proxy_hash = _aws(
        aws,
        "lambda",
        "get-function",
        "--function-name",
        "tollchat-chat-proxy",
        "--query",
        "Configuration.CodeSha256",
        "--output",
        "text",
    )
    identity = {
        "runtime_id": runtime_id,
        "runtime_arn": runtime_arn,
        "runtime_version": runtime_version,
        "proxy_code_sha256": proxy_hash,
        "rds_class": cast(str, db.get("DBInstanceClass")),
        "rds_engine_version": cast(str, db.get("EngineVersion")),
    }
    if any(not value or value == "None" for value in identity.values()):
        raise LoadVerificationError("deployment identity was incomplete")
    return identity


def _invoke_ingestion(aws: list[str], drill_id: str) -> None:
    _aws(
        aws,
        "lambda",
        "invoke",
        "--function-name",
        "toll-fetcher",
        "--invocation-type",
        "Event",
        "--cli-binary-format",
        "raw-in-base64-out",
        "--payload",
        json.dumps({"drill_id": drill_id}, separators=(",", ":")),
        os.devnull,
    )


def _loader_events(
    aws: list[str], drill_id: str, started_at: float, deadline: float
) -> dict[str, float]:
    pattern = re.compile(rf"LOAD_OBJECT_OK (i95|i66) \S*{re.escape(drill_id)}")
    while time.time() < deadline:
        result = cast(
            dict[str, object],
            _aws_json(
                aws,
                "logs",
                "filter-log-events",
                "--log-group-name",
                "/aws/lambda/toll-loader",
                "--start-time",
                str(int((started_at - 1) * 1000)),
                "--end-time",
                str(int(time.time() * 1000)),
                "--filter-pattern",
                drill_id,
            ),
        )
        found: dict[str, float] = {}
        for item in cast(list[object], result.get("events", [])):
            if not isinstance(item, dict):
                continue
            event = cast(dict[str, object], item)
            message = event.get("message")
            timestamp = event.get("timestamp")
            if not isinstance(message, str) or not isinstance(timestamp, int | float):
                continue
            match = pattern.search(message)
            if match:
                found[match[1]] = float(timestamp) / 1000
        if set(found) == {"i95", "i66"}:
            return found
        time.sleep(min(5, max(0, deadline - time.time())))
    raise LoadVerificationError("correlated loader evidence did not arrive")


def _metric_query(
    query_id: str,
    namespace: str,
    metric_name: str,
    dimensions: dict[str, str],
    statistic: str,
    period: int = 60,
) -> dict[str, object]:
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": namespace,
                "MetricName": metric_name,
                "Dimensions": [
                    {"Name": name, "Value": value} for name, value in dimensions.items()
                ],
            },
            "Period": period,
            "Stat": statistic,
        },
        "ReturnData": True,
    }


def _metric_values(
    aws: list[str], queries: list[dict[str, object]], start: float, end: float
) -> dict[str, list[float]]:
    result = cast(
        dict[str, object],
        _aws_json(
            aws,
            "cloudwatch",
            "get-metric-data",
            "--metric-data-queries",
            json.dumps(queries, separators=(",", ":")),
            "--start-time",
            datetime.fromtimestamp(start, UTC).isoformat(),
            "--end-time",
            datetime.fromtimestamp(end, UTC).isoformat(),
            "--scan-by",
            "TimestampAscending",
        ),
    )
    values: dict[str, list[float]] = {}
    for item in cast(list[object], result.get("MetricDataResults", [])):
        if not isinstance(item, dict):
            continue
        metric = cast(dict[str, object], item)
        query_id = metric.get("Id")
        raw_values = metric.get("Values")
        if isinstance(query_id, str) and isinstance(raw_values, list):
            values[query_id] = [
                float(value)
                for value in cast(list[object], raw_values)
                if isinstance(value, int | float)
            ]
    return values


def _collect_metrics(
    aws: list[str], identity: dict[str, str], started_at: float, deadline: float
) -> dict[str, float]:
    proxy = {"FunctionName": "tollchat-chat-proxy"}
    runtime = {
        "Resource": identity["runtime_arn"],
        "Operation": "InvokeAgentRuntime",
        "Name": "nova_toll::preview",
    }
    rds = {"DBInstanceIdentifier": "nova-toll-db"}
    queries = [
        _metric_query("proxy_duration", "AWS/Lambda", "Duration", proxy, "p99"),
        _metric_query(
            "proxy_concurrency",
            "AWS/Lambda",
            "ConcurrentExecutions",
            proxy,
            "Maximum",
        ),
        _metric_query("proxy_invocations", "AWS/Lambda", "Invocations", proxy, "Sum"),
        _metric_query("proxy_errors", "AWS/Lambda", "Errors", proxy, "Sum"),
        _metric_query("proxy_failures", "NovaToll", "ProxyFailure", {}, "Sum"),
        _metric_query(
            "active_sessions",
            "AWS/Bedrock-AgentCore",
            "ActiveSessionCount",
            {"Service": "AgentCore.Runtime"},
            "Maximum",
        ),
        _metric_query(
            "agentcore_invocations",
            "AWS/Bedrock-AgentCore",
            "Invocations",
            runtime,
            "Sum",
        ),
        _metric_query(
            "agentcore_system_errors",
            "AWS/Bedrock-AgentCore",
            "SystemErrors",
            runtime,
            "Sum",
        ),
        _metric_query(
            "agentcore_user_errors",
            "AWS/Bedrock-AgentCore",
            "UserErrors",
            runtime,
            "Sum",
        ),
        _metric_query(
            "agentcore_throttles",
            "AWS/Bedrock-AgentCore",
            "Throttles",
            runtime,
            "Sum",
        ),
        _metric_query("rds_cpu", "AWS/RDS", "CPUUtilization", rds, "Maximum"),
        _metric_query("rds_memory", "AWS/RDS", "FreeableMemory", rds, "Minimum"),
        _metric_query(
            "rds_connections", "AWS/RDS", "DatabaseConnections", rds, "Maximum"
        ),
        _metric_query("rds_read_latency", "AWS/RDS", "ReadLatency", rds, "Maximum"),
        _metric_query("rds_write_latency", "AWS/RDS", "WriteLatency", rds, "Maximum"),
        _metric_query("rds_read_iops", "AWS/RDS", "ReadIOPS", rds, "Maximum"),
        _metric_query("rds_write_iops", "AWS/RDS", "WriteIOPS", rds, "Maximum"),
        _metric_query("rds_queue", "AWS/RDS", "DiskQueueDepth", rds, "Maximum"),
        _metric_query(
            "fetcher_errors",
            "AWS/Lambda",
            "Errors",
            {"FunctionName": "toll-fetcher"},
            "Sum",
        ),
        _metric_query(
            "loader_errors",
            "AWS/Lambda",
            "Errors",
            {"FunctionName": "toll-loader"},
            "Sum",
        ),
        _metric_query("load_i95", "NovaToll", "LoadSuccess", {"feed": "i95"}, "Sum"),
        _metric_query("load_i66", "NovaToll", "LoadSuccess", {"feed": "i66"}, "Sum"),
    ]
    required = {
        "proxy_duration",
        "proxy_concurrency",
        "proxy_invocations",
        "active_sessions",
        "agentcore_invocations",
        "rds_cpu",
        "rds_memory",
        "rds_connections",
        "rds_read_latency",
        "rds_write_latency",
        "rds_read_iops",
        "rds_write_iops",
        "rds_queue",
        "load_i95",
        "load_i66",
    }
    values: dict[str, list[float]] = {}
    while time.time() < deadline:
        values = _metric_values(aws, queries, started_at - 5, time.time())
        if required.issubset(
            query_id for query_id, samples in values.items() if samples
        ):
            break
        time.sleep(min(10, max(0, deadline - time.time())))
    else:
        raise LoadVerificationError("CloudWatch load telemetry was incomplete")

    credits = _metric_values(
        aws,
        [
            _metric_query(
                "rds_credits",
                "AWS/RDS",
                "CPUCreditBalance",
                rds,
                "Minimum",
                period=300,
            )
        ],
        started_at - 300,
        time.time(),
    ).get("rds_credits", [])
    if not credits:
        raise LoadVerificationError("RDS CPU credit telemetry was incomplete")

    def total(query_id: str) -> float:
        return sum(values.get(query_id, []))

    def maximum(query_id: str) -> float:
        return max(values[query_id])

    def minimum(query_id: str) -> float:
        return min(values[query_id])

    return {
        "proxy_latency_p99_ms": maximum("proxy_duration"),
        "proxy_concurrent_executions_max": maximum("proxy_concurrency"),
        "proxy_invocations": total("proxy_invocations"),
        "proxy_errors": total("proxy_errors"),
        "proxy_failures": total("proxy_failures"),
        "agentcore_active_sessions_max": maximum("active_sessions"),
        "agentcore_invocations": total("agentcore_invocations"),
        "agentcore_errors": total("agentcore_system_errors")
        + total("agentcore_user_errors"),
        "agentcore_throttles": total("agentcore_throttles"),
        "rds_cpu_max_percent": maximum("rds_cpu"),
        "rds_free_memory_min_bytes": minimum("rds_memory"),
        "rds_connections_max": maximum("rds_connections"),
        "rds_cpu_credit_min": min(credits),
        "rds_read_latency_max_ms": maximum("rds_read_latency") * 1000,
        "rds_write_latency_max_ms": maximum("rds_write_latency") * 1000,
        "rds_read_iops_max": maximum("rds_read_iops"),
        "rds_write_iops_max": maximum("rds_write_iops"),
        "rds_disk_queue_depth_max": maximum("rds_queue"),
        "fetcher_errors": total("fetcher_errors"),
        "loader_errors": total("loader_errors"),
        "load_success_i95": total("load_i95"),
        "load_success_i66": total("load_i66"),
    }


def _post_factory(base_url: str) -> PostChat:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )

    def post(marker: str) -> tuple[int, bytes]:
        return canonical._post_chat(  # pyright: ignore[reportPrivateUsage]
            base_url, marker, opener=opener
        )

    return post


def run() -> dict[str, object]:
    preview_url = os.environ.get("PREVIEW_URL")
    if not preview_url:
        raise LoadVerificationError("set PREVIEW_URL to the private preview URL")
    wait_seconds = int(os.environ.get("METRIC_WAIT_SECONDS", "600"))
    if wait_seconds < 1:
        raise LoadVerificationError("METRIC_WAIT_SECONDS must be positive")
    aws = [
        "aws",
        "--profile",
        os.environ.get("AWS_PROFILE", "nova-toll"),
        "--region",
        os.environ.get("AWS_REGION", "us-east-1"),
    ]
    identity = _preflight(aws)
    drill_id = uuid.uuid4().hex[:16]
    started_at = time.time()
    observations, _peak, _fired_at = run_requests(
        lambda: _post_factory(preview_url),
        lambda: _invoke_ingestion(aws, drill_id),
    )
    deadline = time.time() + wait_seconds
    loader_events = _loader_events(aws, drill_id, started_at, deadline)
    verify_ingestion_overlap(observations, loader_events)
    metrics = _collect_metrics(aws, identity, started_at, deadline)

    final_identity = _preflight(aws)
    if final_identity != identity:
        raise LoadVerificationError("deployment identity changed during the load test")
    return build_report(
        runtime_version=identity["runtime_version"],
        proxy_code_sha256=identity["proxy_code_sha256"],
        rds_class=identity["rds_class"],
        rds_engine_version=identity["rds_engine_version"],
        metrics=metrics,
        latencies_ms=[item["latency_ms"] for item in observations],
        timestamp=datetime.now(UTC),
    )


def main() -> int:
    try:
        report = run()
    except (
        LoadVerificationError,
        canonical.SmokeVerificationError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ):
        print(
            "PRIVATE LOAD TEST FAILED: verification did not pass",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

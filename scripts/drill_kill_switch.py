#!/usr/bin/env python3
"""Run the authorized private TollChat kill-switch drill."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "nova-toll"
REGION = "us-east-1"
ACCOUNT = "920534282028"
FUNCTION = "tollchat-chat-proxy"
PREVIEW_URL = "https://preview.tollchat.ai"
TRACE_GROUP = "/aws/nova-toll/agentcore/traces"
AGENTCORE_COUNT_QUERY = 'filter stage = "invoke" | stats count() as count'
ALARMS = (
    "toll-fetcher-errors",
    "toll-loader-errors",
    "toll-freshness-i95",
    "toll-freshness-i66",
    "toll-loader-onfailure-queue",
    "toll-rds-free-storage",
)
ARTIFACTS = (
    "fetcher.zip",
    "loader.zip",
    "agentcore.zip",
    "chat-proxy.zip",
)
_LOAD_OK = re.compile(r"\bLOAD_OK\s+(i66|i95)\b")
_AMBIENT_AWS_CREDENTIALS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_ROLE_ARN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
}
_POLICY_NORMALIZATION = {
    "aws_api_gateway_rest_api.tollchat": re.compile(
        rf"arn:aws:execute-api:{REGION}:{ACCOUNT}:[^:/]+/\*"
    ),
    "aws_api_gateway_domain_name.tollchat": re.compile(
        rf"arn:aws:execute-api:{REGION}:{ACCOUNT}:/domainnames/"
        r"preview\.tollchat\.ai\+[^:/]+"
    ),
}
_engaged_at = 0


class DrillError(RuntimeError):
    """The drill cannot produce valid passing evidence."""


def _now() -> float:
    return time.time()


def _environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _AMBIENT_AWS_CREDENTIALS
    }
    return {
        **env,
        "AWS_PROFILE": PROFILE,
        "AWS_DEFAULT_PROFILE": PROFILE,
        "AWS_REGION": REGION,
    }


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env or _environment(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )


def _aws(*arguments: str, timeout: float = 30) -> str:
    return _run(
        ["aws", "--profile", PROFILE, "--region", REGION, *arguments],
        timeout=timeout,
    ).stdout.strip()


def _aws_json(*arguments: str, timeout: float = 30) -> object:
    try:
        return json.loads(_aws(*arguments, "--output", "json", timeout=timeout))
    except json.JSONDecodeError as error:
        raise DrillError("AWS returned malformed control-plane data") from error


def _get_concurrency() -> int:
    value = cast(
        dict[str, object],
        _aws_json("lambda", "get-function-concurrency", "--function-name", FUNCTION),
    ).get("ReservedConcurrentExecutions")
    if not isinstance(value, int):
        raise DrillError("proxy reserved concurrency was not configured")
    return value


def _put_concurrency(value: int) -> None:
    _aws(
        "lambda",
        "put-function-concurrency",
        "--function-name",
        FUNCTION,
        "--reserved-concurrent-executions",
        str(value),
    )


def _http_status(method: str, path: str, body: dict[str, object] | None = None) -> int:
    origin = urllib.parse.urlsplit(PREVIEW_URL)
    request = urllib.request.Request(
        f"{PREVIEW_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "content-type": "application/json",
            "origin": f"{origin.scheme}://{origin.netloc}",
            "sec-fetch-site": "same-origin",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as error:
        error.read()
        return error.code
    except urllib.error.URLError as error:
        raise DrillError("private preview was unreachable from this client") from error


def _alarm_states() -> dict[str, str]:
    response = cast(
        dict[str, object],
        _aws_json(
            "cloudwatch",
            "describe-alarms",
            "--alarm-names",
            *ALARMS,
        ),
    )
    alarms = cast(list[object], response.get("MetricAlarms", []))
    return {
        cast(str, alarm["AlarmName"]): cast(str, alarm["StateValue"])
        for raw in alarms
        if isinstance(raw, dict)
        for alarm in [cast(dict[str, object], raw)]
        if isinstance(alarm.get("AlarmName"), str)
        and isinstance(alarm.get("StateValue"), str)
    }


def _rds_check() -> bool:
    env = {
        **_environment(),
        "DB_USER": "pricing_reader",
        "DB_NAME": "nova_toll",
        "DB_CA_BUNDLE_PATH": str(ROOT / "infra/build/loader/rds-ca-bundle.pem"),
    }
    try:
        _run(
            [
                "uv",
                "run",
                "--frozen",
                "pytest",
                "-q",
                "-m",
                "live",
                "tests/test_ci_rds_connectivity.py",
            ],
            env=env,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def validate_preflight(state: dict[str, object]) -> int:
    alarms = state.get("alarms")
    alarm_states = (
        cast(dict[object, object], alarms) if isinstance(alarms, dict) else {}
    )
    healthy = (
        state.get("account") == ACCOUNT
        and state.get("concurrency") == 5
        and state.get("lambda_state") == "Active"
        and state.get("lambda_update") == "Successful"
        and state.get("db_status") == "available"
        and state.get("config_status") == 200
        and state.get("rds_ok") is True
        and state.get("artifacts_ok") is True
        and state.get("terraform_clean") is True
        and isinstance(alarms, dict)
        and set(alarm_states) == set(ALARMS)
        and all(value == "OK" for value in alarm_states.values())
    )
    if not healthy:
        raise DrillError("preflight failed; no control-plane change was made")
    return 5


def _preflight() -> dict[str, object]:
    identity = cast(dict[str, object], _aws_json("sts", "get-caller-identity"))
    function = cast(
        dict[str, object],
        _aws_json("lambda", "get-function-configuration", "--function-name", FUNCTION),
    )
    dbs = cast(
        dict[str, object],
        _aws_json(
            "rds",
            "describe-db-instances",
            "--db-instance-identifier",
            "nova-toll-db",
        ),
    )
    raw_instances = cast(list[object], dbs.get("DBInstances", []))
    instance = (
        cast(dict[str, object], raw_instances[0])
        if raw_instances and isinstance(raw_instances[0], dict)
        else {}
    )
    artifacts_ok = all(
        (ROOT / "infra/build" / artifact).is_file() for artifact in ARTIFACTS
    )
    state: dict[str, object] = {
        "account": identity.get("Account"),
        "concurrency": _get_concurrency(),
        "lambda_state": function.get("State"),
        "lambda_update": function.get("LastUpdateStatus"),
        "db_status": instance.get("DBInstanceStatus"),
        "alarms": _alarm_states(),
        "config_status": _http_status("GET", "/api/config"),
        "rds_ok": _rds_check(),
        "artifacts_ok": artifacts_ok,
        "terraform_clean": artifacts_ok and _terraform_plan(apply=False) is None,
    }
    validate_preflight(state)
    return state


def validate_blocked_statuses(statuses: tuple[int, int]) -> None:
    if any(status < 500 or status > 599 for status in statuses):
        raise DrillError("a private chat route did not fail at its integration")


def _prove_routes() -> None:
    deadline = _now() + 30
    while True:
        statuses = (
            _http_status("GET", "/api/config"),
            _http_status("POST", "/api/chat", {"message": "kill-switch drill request"}),
        )
        if all(500 <= status <= 599 for status in statuses):
            return
        if _now() >= deadline:
            validate_blocked_statuses(statuses)
        time.sleep(1)


def _query_agentcore_invocations(start_time: int, end_time: int) -> int:
    query_id = _aws(
        "logs",
        "start-query",
        "--log-group-name",
        TRACE_GROUP,
        "--start-time",
        str(start_time),
        "--end-time",
        str(end_time),
        "--query-string",
        AGENTCORE_COUNT_QUERY,
        "--query",
        "queryId",
        "--output",
        "text",
    )
    deadline = _now() + 60
    while _now() < deadline:
        response = cast(
            dict[str, object],
            _aws_json("logs", "get-query-results", "--query-id", query_id),
        )
        status = response.get("status")
        if status == "Complete":
            rows = cast(list[object], response.get("results", []))
            if not rows or not isinstance(rows[0], list):
                return 0
            for raw in cast(list[object], rows[0]):
                if not isinstance(raw, dict):
                    continue
                field = cast(dict[object, object], raw)
                if field.get("field") == "count":
                    return int(cast(str, field.get("value")))
            raise DrillError("AgentCore trace count was missing")
        if status not in {"Scheduled", "Running"}:
            raise DrillError("AgentCore trace query failed")
        time.sleep(2)
    raise DrillError("AgentCore trace query timed out")


def _prove_agentcore() -> None:
    if _query_agentcore_invocations(_engaged_at, int(_now())) != 0:
        raise DrillError("AgentCore produced an invocation while chat was disabled")


def _invoke_fetcher(output: Path) -> None:
    _run(
        [
            "aws",
            "--profile",
            PROFILE,
            "--region",
            REGION,
            "lambda",
            "invoke",
            "--function-name",
            "toll-fetcher",
            "--cli-binary-format",
            "raw-in-base64-out",
            "--payload",
            '{"feeds":["i95","i66"]}',
            str(output),
        ],
        timeout=60,
    )


def _load_successes(start_millis: int) -> set[str]:
    response = cast(
        dict[str, object],
        _aws_json(
            "logs",
            "filter-log-events",
            "--log-group-name",
            "/aws/lambda/toll-loader",
            "--start-time",
            str(start_millis),
            "--filter-pattern",
            '"LOAD_OK"',
        ),
    )
    feeds: set[str] = set()
    for raw in cast(list[object], response.get("events", [])):
        if not isinstance(raw, dict):
            continue
        event = cast(dict[object, object], raw)
        message = event.get("message")
        if not isinstance(message, str):
            continue
        match = _LOAD_OK.search(message)
        if match:
            feeds.add(match.group(1))
    return feeds


def _prove_pipeline() -> None:
    start_millis = int(_now() * 1000) - 1000
    with tempfile.TemporaryDirectory() as directory:
        _invoke_fetcher(Path(directory) / "fetcher.json")
        deadline = _now() + 120
        while _now() < deadline and _load_successes(start_millis) != {"i66", "i95"}:
            time.sleep(5)
    if _load_successes(start_millis) != {"i66", "i95"}:
        raise DrillError("fetcher/loader did not complete both feeds")
    alarms = _alarm_states()
    if (
        not _rds_check()
        or set(alarms) != set(ALARMS)
        or any(value != "OK" for value in alarms.values())
    ):
        raise DrillError("RDS or ingestion alarms became unhealthy")


def _terraform_environment() -> dict[str, str]:
    token = _aws(
        "ssm",
        "get-parameter",
        "--name",
        "/nova-toll/cloudflare-api-token",
        "--with-decryption",
        "--query",
        "Parameter.Value",
        "--output",
        "text",
    )
    if not token:
        raise DrillError("Terraform credential was unavailable from SSM")
    return {**_environment(), "CLOUDFLARE_API_TOKEN": token}


def _normalized_policy(
    raw: object, pattern: re.Pattern[str], *, expanded: bool
) -> object:
    if not isinstance(raw, str):
        raise DrillError("Terraform plan changed API policy metadata")
    try:
        policy = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DrillError("Terraform plan changed API policy metadata") from error
    if not isinstance(policy, dict):
        raise DrillError("Terraform plan changed API policy metadata")
    typed_policy = cast(dict[object, object], policy)
    statements = typed_policy.get("Statement")
    if not isinstance(statements, list) or not statements:
        raise DrillError("Terraform plan changed API policy metadata")
    for raw_statement in cast(list[object], statements):
        if not isinstance(raw_statement, dict):
            raise DrillError("Terraform plan changed API policy metadata")
        statement = cast(dict[object, object], raw_statement)
        resource = statement.get("Resource")
        expected = pattern.fullmatch(resource) if isinstance(resource, str) else None
        if expanded:
            if not expected:
                raise DrillError("Terraform plan changed API policy metadata")
        elif resource != "execute-api:/*":
            raise DrillError("Terraform plan changed API policy metadata")
        statement["Resource"] = "execute-api:/*"
    return typed_policy


def validate_terraform_plan(plan: object) -> None:
    if not isinstance(plan, dict):
        raise DrillError("Terraform plan was malformed")
    raw_changes = cast(dict[object, object], plan).get("resource_changes")
    if not isinstance(raw_changes, list):
        raise DrillError("Terraform plan was malformed")
    changes: dict[str, dict[object, object]] = {}
    for raw in cast(list[object], raw_changes):
        if not isinstance(raw, dict):
            raise DrillError("Terraform plan was malformed")
        resource = cast(dict[object, object], raw)
        raw_change = resource.get("change")
        if not isinstance(raw_change, dict):
            raise DrillError("Terraform plan was malformed")
        change = cast(dict[object, object], raw_change)
        if change.get("actions") in (["no-op"], ["read"]):
            continue
        address = resource.get("address")
        if not isinstance(address, str):
            raise DrillError("Terraform plan was malformed")
        changes[address] = change
    if set(changes) != set(_POLICY_NORMALIZATION):
        raise DrillError("Terraform plan contained unexpected changes")
    for address, pattern in _POLICY_NORMALIZATION.items():
        change = changes[address]
        before, after = change.get("before"), change.get("after")
        if (
            change.get("actions") != ["update"]
            or not isinstance(before, dict)
            or not isinstance(after, dict)
        ):
            raise DrillError("Terraform plan contained unexpected changes")
        before_values = cast(dict[object, object], before)
        after_values = cast(dict[object, object], after)
        if {key: value for key, value in before_values.items() if key != "policy"} != {
            key: value for key, value in after_values.items() if key != "policy"
        } or _normalized_policy(
            before_values.get("policy"), pattern, expanded=True
        ) != _normalized_policy(after_values.get("policy"), pattern, expanded=False):
            raise DrillError("Terraform plan changed API policy behavior")


def _terraform_plan(*, apply: bool) -> None:
    terraform = ROOT / "infra"
    variables = [
        "-var",
        "fetcher_package_path=build/fetcher.zip",
        "-var",
        "loader_package_path=build/loader.zip",
        "-var",
        "agentcore_package_path=build/agentcore.zip",
        "-var",
        "chat_proxy_package_path=build/chat-proxy.zip",
    ]
    env = _terraform_environment()
    with tempfile.TemporaryDirectory() as directory:
        plan = Path(directory) / "kill-switch.tfplan"
        _run(
            ["terraform", "init", "-input=false"],
            cwd=terraform,
            env=env,
            timeout=300,
        )
        result = subprocess.run(
            [
                "terraform",
                "plan",
                "-input=false",
                "-detailed-exitcode",
                "-out",
                str(plan),
                *variables,
            ],
            cwd=terraform,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 2:
            shown = _run(
                ["terraform", "show", "-json", str(plan)],
                cwd=terraform,
                env=env,
                timeout=120,
            )
            try:
                validate_terraform_plan(json.loads(shown.stdout))
            except json.JSONDecodeError as error:
                raise DrillError("Terraform plan was malformed") from error
        elif result.returncode != 0:
            raise DrillError("Terraform plan contained drift or failed")
        if apply:
            _run(
                ["terraform", "apply", "-input=false", "-auto-approve", str(plan)],
                cwd=terraform,
                env=env,
                timeout=600,
            )


def _prove_terraform() -> None:
    _terraform_plan(apply=True)
    if _get_concurrency() != 0:
        raise DrillError("Terraform restored proxy concurrency")


def _restore_concurrency(baseline: int) -> None:
    for attempt in range(3):
        try:
            _put_concurrency(baseline)
            if _get_concurrency() == baseline:
                return
        except (OSError, subprocess.SubprocessError, DrillError):
            pass
        time.sleep(2**attempt)
    raise DrillError("EMERGENCY: automatic concurrency restoration failed")


def _canonical_smoke() -> dict[str, object]:
    env = {**_environment(), "PREVIEW_URL": f"{PREVIEW_URL}/"}
    result = _run(
        [
            "uv",
            "run",
            "--frozen",
            "python",
            "scripts/smoke_agentcore_canonical.py",
        ],
        env=env,
        timeout=660,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DrillError(
            "canonical recovery smoke returned malformed evidence"
        ) from error
    if not isinstance(report, dict):
        raise DrillError("canonical recovery smoke failed")
    typed_report = cast(dict[object, object], report)
    if typed_report.get("status") != "passed":
        raise DrillError("canonical recovery smoke failed")
    return cast(dict[str, object], typed_report)


def _screenshot_pause() -> None:
    print(
        "\nTOLLCHAT KILL-SWITCH — ENGAGED\n"
        "Config endpoint          BLOCKED\n"
        "Chat endpoint            BLOCKED\n"
        "AgentCore invocations    0\n"
        "Toll ingestion           HEALTHY\n"
        "RDS                      HEALTHY\n"
        "Terraform apply          SWITCH PRESERVED\n"
        "Automatic restore        ARMED\n",
        file=sys.stderr,
    )
    print(
        "Capture the split-screen proof, then press Enter to restore: ",
        end="",
        file=sys.stderr,
    )
    input()


def build_report(
    *,
    baseline: int,
    disabled_seconds: float,
    recovery_seconds: float,
    started_at: datetime,
    restored_at: datetime,
    completed_at: datetime,
) -> dict[str, object]:
    if baseline != 5 or disabled_seconds < 0 or recovery_seconds < 0:
        raise DrillError("unsafe drill report metadata")
    return {
        "timestamp": completed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "started_at": started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "restored_at": restored_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "issues": [93],
        "status": "passed",
        "scenario": "Private TollChat service-wide kill-switch drill",
        "evidence_type": "Metadata-only deployed operational drill",
        "baseline_reserved_concurrency": baseline,
        "restored_reserved_concurrency": baseline,
        "disable_confirmation_seconds": round(disabled_seconds, 1),
        "recovery_confirmation_seconds": round(recovery_seconds, 1),
        "checks": {
            "owner_approval_recorded": True,
            "control_plane_zero": True,
            "private_config_blocked": True,
            "private_chat_blocked": True,
            "agentcore_invocations_zero": True,
            "ingestion_healthy": True,
            "rds_healthy": True,
            "terraform_preserved_switch": True,
            "baseline_restored": True,
            "canonical_recovery": True,
        },
        "notes": (
            "Raw responses, prompts, cookies, request/session/trace identifiers, "
            "database endpoints, caller identity, and credentials were used only "
            "in memory and were not curated."
        ),
    }


def run(
    *, execute: bool, approved_by: str | None, pause_for_screenshot: bool
) -> dict[str, object]:
    global _engaged_at
    state = _preflight()
    baseline = validate_preflight(state)
    if not execute:
        return {
            "status": "ready",
            "baseline_reserved_concurrency": baseline,
            "checks": {
                "correct_account": True,
                "private_preview_healthy": True,
                "ingestion_healthy": True,
                "rds_healthy": True,
                "artifacts_ready": True,
            },
        }
    if approved_by != "Ryan":
        raise DrillError("live execution requires explicit owner approval")

    started = _now()
    engaged = False
    restored_at = 0.0
    try:
        _put_concurrency(0)
        engaged = True
        _engaged_at = int(started) - 1
        if _get_concurrency() != 0:
            raise DrillError("control plane did not engage the kill switch")
        _prove_routes()
        disabled_seconds = _now() - started
        _prove_pipeline()
        _prove_terraform()
        _prove_agentcore()
        if pause_for_screenshot:
            _screenshot_pause()
    finally:
        if engaged:
            restored_at = _now()
            _restore_concurrency(baseline)

    _canonical_smoke()
    return build_report(
        baseline=baseline,
        disabled_seconds=disabled_seconds,
        recovery_seconds=_now() - restored_at,
        started_at=datetime.fromtimestamp(started, UTC),
        restored_at=datetime.fromtimestamp(restored_at, UTC),
        completed_at=datetime.now(UTC),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-by")
    parser.add_argument("--pause-for-screenshot", action="store_true")
    arguments = parser.parse_args()
    try:
        report = run(
            execute=arguments.execute,
            approved_by=arguments.approved_by,
            pause_for_screenshot=arguments.pause_for_screenshot,
        )
    except DrillError as error:
        print(f"KILL-SWITCH DRILL FAILED: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, ValueError):
        print(
            "KILL-SWITCH DRILL FAILED: inspect operator logs and verify proxy concurrency",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

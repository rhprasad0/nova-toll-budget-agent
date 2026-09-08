#!/usr/bin/env python3
"""Own the explicit end-to-end development deployment, separate from OIDC jobs."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

REPOSITORY = "rhprasad0/nova-toll-budget-agent"
ENVIRONMENT = "development-release"
SITE = "https://dev.tollchat.ai"
STATUS_REASONS = {
    "unclassified",
    "upstream_failed",
    "publisher_failed",
    "malformed_evidence",
}
_progress_started: float | None = None


class DeploymentStatusError(ValueError):
    """A bounded local deployment-status failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in STATUS_REASONS else "unclassified"
        super().__init__(self.reason)


def _emit_progress(
    state: str, reason: str = "unclassified", exit_code: int = 0
) -> None:
    global _progress_started
    if state == "start":
        _progress_started = time.monotonic()
    elapsed = 0
    if _progress_started is not None:
        elapsed = max(int(time.monotonic() - _progress_started), 0)
    if reason not in STATUS_REASONS:
        reason = "unclassified"
    event = f"stage=release-status status={state} elapsed={elapsed} exit={exit_code} reason={reason}"
    print(event, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write(event + "\n")
        except OSError:
            print(
                "stage=release-status status=fail elapsed=0 exit=125 reason=unclassified",
                file=sys.stderr,
            )


def api(
    method: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    command = ["gh", "api", "--method", method, f"repos/{REPOSITORY}/{path}"]
    if payload is not None:
        command.extend(["--input", "-"])
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeploymentStatusError("publisher_failed") from error
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise DeploymentStatusError("publisher_failed")
    try:
        value = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise DeploymentStatusError("malformed_evidence") from error
    if not isinstance(value, dict):
        raise DeploymentStatusError("malformed_evidence")
    return cast(dict[str, Any], value)


def identity() -> tuple[str, int, int]:
    sha = os.environ["GITHUB_SHA"]
    run = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    if (
        os.environ["GITHUB_REPOSITORY"] != REPOSITORY
        or os.environ["GITHUB_REF"] != "refs/heads/main"
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or not run.isdecimal()
        or not attempt.isdecimal()
        or int(run) < 1
        or int(attempt) < 1
    ):
        raise DeploymentStatusError("malformed_evidence")
    return sha, int(run), int(attempt)


def status(record: int, state: str, run: int, attempt: int) -> None:
    api(
        "POST",
        f"deployments/{record}/statuses",
        {
            "state": state,
            "description": f"Exact development release: {state}; attempt {attempt}",
            "environment": ENVIRONMENT,
            "environment_url": SITE,
            "log_url": f"https://github.com/{REPOSITORY}/actions/runs/{run}/attempts/{attempt}",
            "auto_inactive": False,
        },
    )


def create() -> None:
    sha, run, attempt = identity()
    result = api(
        "POST",
        "deployments",
        {
            "ref": sha,
            "task": "development-release",
            "environment": ENVIRONMENT,
            "auto_merge": False,
            "required_contexts": [],
            "production_environment": False,
            "payload": {"run_id": run, "created_attempt": attempt, "sha": sha},
        },
    )
    record = result.get("id")
    if type(record) is not int or record < 1 or result.get("sha") != sha:
        raise DeploymentStatusError("malformed_evidence")
    # Persist before the status call so a failed creation job can be reconciled.
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"deployment_id={record}\n")
    status(record, "in_progress", run, attempt)


def finish() -> None:
    sha, run, attempt = identity()
    try:
        needs = json.loads(os.environ["NEEDS_JSON"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise DeploymentStatusError("malformed_evidence") from error
    if not isinstance(needs, dict):
        raise DeploymentStatusError("malformed_evidence")
    needs = cast(dict[str, Any], needs)
    try:
        raw_record = needs["release-record"]["outputs"].get("deployment_id", "")
    except (KeyError, TypeError, AttributeError) as error:
        raise DeploymentStatusError("malformed_evidence") from error
    if (
        not isinstance(raw_record, str)
        or not raw_record.isdecimal()
        or int(raw_record) < 1
    ):
        raise DeploymentStatusError("malformed_evidence")
    record = int(raw_record)
    deployment = api("GET", f"deployments/{record}")
    current = api("GET", f"actions/runs/{run}")
    payload = deployment.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise DeploymentStatusError("malformed_evidence") from error
    if not isinstance(payload, dict):
        raise DeploymentStatusError("malformed_evidence")
    payload = cast(dict[str, Any], payload)
    if (
        deployment.get("sha") != sha
        or deployment.get("environment") != ENVIRONMENT
        or deployment.get("task") != "development-release"
        or payload.get("sha") != sha
        or payload.get("run_id") != run
        or type(payload.get("created_attempt")) is not int
        or not 1 <= payload["created_attempt"] <= attempt
        or current.get("head_sha") != sha
        or current.get("run_attempt") != attempt
    ):
        raise DeploymentStatusError("malformed_evidence")
    # A failed-deploy rerun intentionally reuses this run's verified successful
    # build and explicit record. The status log URL identifies the current attempt.
    jobs = ("admission", "release-record", "build", "oidc-proof", "deploy")
    try:
        outcomes: dict[str, Any] = {}
        for job in jobs:
            value = needs.get(job, {})
            if not isinstance(value, dict):
                raise DeploymentStatusError("malformed_evidence")
            outcomes[job] = cast(dict[str, Any], value).get("result", "missing")
        deploy = needs.get("deploy", {})
        build_job = needs.get("build", {})
    except (AttributeError, TypeError) as error:
        raise DeploymentStatusError("malformed_evidence") from error
    if not isinstance(deploy, dict) or not isinstance(build_job, dict):
        raise DeploymentStatusError("malformed_evidence")
    deploy_outputs = cast(dict[str, Any], deploy).get("outputs", {})
    build = cast(dict[str, Any], build_job).get("outputs", {})
    success = all(value == "success" for value in outcomes.values())
    success = success and deploy_outputs.get("verified") == "success"
    if not isinstance(build, dict) or not isinstance(deploy_outputs, dict):
        raise DeploymentStatusError("malformed_evidence")
    build = cast(dict[str, Any], build)
    deploy_outputs = cast(dict[str, Any], deploy_outputs)
    evidence = {"commit": sha, "run_id": run, "attempt": attempt, "jobs": outcomes}
    release: dict[str, Any] = {
        "artifact_id": build.get("artifact_id", "unavailable"),
        "artifact_digest": build.get("artifact_digest", "unavailable"),
        "pricing_schema": build.get("pricing_schema", "unavailable"),
        "oracle_schema": build.get("oracle_schema", "unavailable"),
    }
    patterns = {
        "artifact_id": r"[1-9][0-9]*",
        "artifact_digest": r"sha256:[0-9a-f]{64}",
        "pricing_schema": r"[0-9]+\.[0-9]+\.[0-9]+",
        "oracle_schema": r"[0-9]+\.[0-9]+\.[0-9]+",
    }
    malformed_release = False
    for key, pattern in patterns.items():
        value = release[key]
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            release[key] = "unavailable"
            success = False
            malformed_release = True
    state = "success" if success else "failure"
    status(record, state, run, attempt)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write("### Development release result\n\n")
        summary.write(f"{state}; {SITE}\n\n")
        summary.write(
            "```json\n"
            + json.dumps({**evidence, **release}, sort_keys=True)
            + "\n```\n"
        )
    if not success:
        if malformed_release:
            raise DeploymentStatusError("malformed_evidence")
        raise DeploymentStatusError("upstream_failed")


def main() -> int:
    try:
        _emit_progress("start")
        if sys.argv[1:] == ["create"]:
            create()
        elif sys.argv[1:] == ["finish"]:
            finish()
        else:
            raise DeploymentStatusError("malformed_evidence")
    except DeploymentStatusError as error:
        _emit_progress("fail", error.reason, 1)
        print("development deployment evidence failed closed", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        _emit_progress("fail", "publisher_failed", 1)
        print("development deployment evidence failed closed", file=sys.stderr)
        return 1
    _emit_progress("pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

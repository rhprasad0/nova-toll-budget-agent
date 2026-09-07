#!/usr/bin/env python3
"""Own the explicit end-to-end development deployment, separate from OIDC jobs."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

REPOSITORY = "rhprasad0/nova-toll-budget-agent"
ENVIRONMENT = "development-release"
SITE = "https://dev.tollchat.ai"


def api(
    method: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    command = ["gh", "api", "--method", method, f"repos/{REPOSITORY}/{path}"]
    if payload is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise ValueError("deployment API request failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("invalid deployment API response")
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
        raise ValueError("invalid deployment identity")
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
        raise ValueError("invalid deployment record")
    # Persist before the status call so a failed creation job can be reconciled.
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"deployment_id={record}\n")
    status(record, "in_progress", run, attempt)


def finish() -> None:
    sha, run, attempt = identity()
    needs = json.loads(os.environ["NEEDS_JSON"])
    raw_record = needs["release-record"]["outputs"].get("deployment_id", "")
    if (
        not isinstance(raw_record, str)
        or not raw_record.isdecimal()
        or int(raw_record) < 1
    ):
        raise ValueError("deployment record unavailable; no success evidence")
    record = int(raw_record)
    deployment = api("GET", f"deployments/{record}")
    current = api("GET", f"actions/runs/{run}")
    payload = deployment.get("payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("invalid deployment payload")
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
        raise ValueError("deployment ownership or current attempt mismatch")
    # A failed-deploy rerun intentionally reuses this run's verified successful
    # build and explicit record. The status log URL identifies the current attempt.
    jobs = ("admission", "release-record", "build", "oidc-proof", "deploy")
    outcomes = {job: needs.get(job, {}).get("result", "missing") for job in jobs}
    success = all(value == "success" for value in outcomes.values())
    success = (
        success
        and needs.get("deploy", {}).get("outputs", {}).get("verified") == "success"
    )
    build = needs.get("build", {}).get("outputs", {})
    evidence = {"commit": sha, "run_id": run, "attempt": attempt, "jobs": outcomes}
    release = {
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
    for key, pattern in patterns.items():
        value = release[key]
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            release[key] = "unavailable"
            success = False
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
        raise ValueError("development release did not pass every stage")


def main() -> int:
    try:
        if sys.argv[1:] == ["create"]:
            create()
        elif sys.argv[1:] == ["finish"]:
            finish()
        else:
            raise ValueError("expected create or finish")
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        print("development deployment evidence failed closed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

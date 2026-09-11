#!/usr/bin/env python3
"""Own development deployment status and durable release evidence."""

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
EVIDENCE_FILE = "development-release-evidence.json"
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
    stage: str, state: str, reason: str = "unclassified", exit_code: int = 0
) -> None:
    global _progress_started
    if state == "start":
        _progress_started = time.monotonic()
    elapsed = 0
    if _progress_started is not None:
        elapsed = max(int(time.monotonic() - _progress_started), 0)
    if reason not in STATUS_REASONS:
        reason = "unclassified"
    event = f"stage={stage} status={state} elapsed={elapsed} exit={exit_code} reason={reason}"
    print(event, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write(event + "\n")
        except OSError:
            print(
                f"stage={stage} status=fail elapsed=0 exit=125 reason=unclassified",
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
        or not re.fullmatch(r"[1-9][0-9]*", run)
        or not re.fullmatch(r"[1-9][0-9]*", attempt)
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


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeploymentStatusError("malformed_evidence")
    return cast(dict[str, Any], value)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DeploymentStatusError("malformed_evidence")
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise DeploymentStatusError("malformed_evidence")
    return int(text)


def _version(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise DeploymentStatusError("malformed_evidence")
    return value


def _prefixed_digest(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise DeploymentStatusError("malformed_evidence")
    return value


def _canary(
    value: object,
    sha: str,
    run: int,
    attempt: int,
    deployment: int,
    artifact: int,
    digest: str,
) -> dict[str, Any]:
    if not isinstance(value, str):
        raise DeploymentStatusError("malformed_evidence")
    try:
        record = _mapping(json.loads(value))
    except (TypeError, json.JSONDecodeError) as error:
        raise DeploymentStatusError("malformed_evidence") from error
    expected = {
        "schema_version",
        "runtime_version",
        "proxy_version",
        "call_count",
        "total_usd",
        "elapsed_ms",
        "model",
        "tool_contract",
        "prompt_version",
        "renderer_version",
        "success",
        "commit",
        "run_id",
        "attempt",
        "deployment_id",
        "artifact_id",
        "artifact_digest",
    }
    if (
        set(record) != expected
        or type(record.get("schema_version")) is not int
        or record.get("schema_version") != 1
        or not isinstance(record.get("runtime_version"), str)
        or re.fullmatch(r"[1-9][0-9]*", record["runtime_version"]) is None
        or not isinstance(record.get("proxy_version"), str)
        or re.fullmatch(r"[1-9][0-9]*", record["proxy_version"]) is None
        or type(record.get("call_count")) is not int
        or record.get("call_count") != 1
        or not isinstance(record.get("total_usd"), str)
        or not re.fullmatch(r"\d{1,4}\.\d{2}", record["total_usd"])
        or type(record.get("elapsed_ms")) is not int
        or not 0 <= record["elapsed_ms"] <= 60_000
        or record.get("model") != "gpt-5.6-luna"
        or record.get("tool_contract") != "1.5.0"
        or record.get("prompt_version") != "2.0.3"
        or record.get("renderer_version") != "1.0.0"
        or record.get("success") is not True
        or record.get("commit") != sha
        or _positive(record.get("run_id")) != run
        or _positive(record.get("attempt")) != attempt
        or _positive(record.get("deployment_id")) != deployment
        or _positive(record.get("artifact_id")) != artifact
        or record.get("artifact_digest") != digest
    ):
        raise DeploymentStatusError("malformed_evidence")
    return record


def _needs() -> dict[str, Any]:
    try:
        return _mapping(json.loads(os.environ["NEEDS_JSON"]))
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise DeploymentStatusError("malformed_evidence") from error


def _job(needs: dict[str, Any], name: str) -> dict[str, Any]:
    return _mapping(needs.get(name))


def _outputs(job: dict[str, Any]) -> dict[str, Any]:
    return _mapping(job.get("outputs"))


def _record(needs: dict[str, Any]) -> int:
    return _positive(_outputs(_job(needs, "release-record")).get("deployment_id"))


def _prerequisites(
    sha: str, run: int, attempt: int, needs: dict[str, Any]
) -> dict[str, Any]:
    jobs = ("admission", "release-record", "build", "oidc-proof", "deploy")
    entries = {name: _job(needs, name) for name in jobs}
    if any(entry.get("result") != "success" for entry in entries.values()):
        raise DeploymentStatusError("upstream_failed")
    record = _positive(_outputs(entries["release-record"]).get("deployment_id"))
    build = _outputs(entries["build"])
    deploy = _outputs(entries["deploy"])
    if deploy.get("verified") != "success":
        raise DeploymentStatusError("upstream_failed")
    artifact_id = _positive(build.get("artifact_id"))
    artifact_digest = _prefixed_digest(build.get("artifact_digest"))
    canary = _canary(
        deploy.get("canary"), sha, run, attempt, record, artifact_id, artifact_digest
    )
    declared = {
        "pricing": _version(build.get("pricing_schema")),
        "oracle": _version(build.get("oracle_schema")),
    }
    installed = {
        "pricing": _version(deploy.get("verified_pricing_schema")),
        "oracle": _version(deploy.get("verified_oracle_schema")),
    }
    if declared != installed:
        raise DeploymentStatusError("malformed_evidence")
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "environment": ENVIRONMENT,
        "commit": sha,
        "deployment_id": record,
        "run_id": run,
        "attempt": attempt,
        "artifact_id": artifact_id,
        "artifact_digest": artifact_digest,
        "schema_versions": {"declared": declared, "installed": installed},
        "readiness": "success",
        "canary": canary,
    }


def _validate_record(record: int, sha: str, run: int, attempt: int) -> None:
    deployment = api("GET", f"deployments/{record}")
    current = api("GET", f"actions/runs/{run}")
    payload = deployment.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise DeploymentStatusError("malformed_evidence") from error
    payload = _mapping(payload)
    if (
        deployment.get("sha") != sha
        or deployment.get("environment") != ENVIRONMENT
        or deployment.get("task") != "development-release"
        or payload.get("sha") != sha
        or payload.get("run_id") != run
        or type(payload.get("created_attempt")) is not int
        or not 1 <= cast(int, payload["created_attempt"]) <= attempt
        or current.get("head_sha") != sha
        or current.get("run_attempt") != attempt
    ):
        raise DeploymentStatusError("malformed_evidence")


def _publication(run: int, attempt: int) -> dict[str, Any]:
    if (
        os.environ.get("PREPARE_OUTCOME") != "success"
        or os.environ.get("UPLOAD_OUTCOME") != "success"
    ):
        raise DeploymentStatusError("publisher_failed")
    expected_name = f"v2-development-evidence-{run}-{attempt}"
    if os.environ.get("EVIDENCE_ARTIFACT_NAME") != expected_name:
        raise DeploymentStatusError("malformed_evidence")
    artifact_id = _positive(os.environ.get("EVIDENCE_ARTIFACT_ID"))
    raw_digest = os.environ.get("RAW_EVIDENCE_ARTIFACT_DIGEST")
    if not isinstance(raw_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_digest):
        raise DeploymentStatusError("malformed_evidence")
    return {
        "name": expected_name,
        "id": artifact_id,
        "digest": f"sha256:{raw_digest}",
    }


def _summary(state: str, evidence: dict[str, Any], publication: dict[str, Any]) -> None:
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
        summary.write("### Development release result\n\n")
        summary.write(f"{state}; {SITE}\n\n")
        summary.write(
            "```json\n"
            + json.dumps(
                {
                    "artifact_digest": evidence["artifact_digest"],
                    "artifact_id": evidence["artifact_id"],
                    "attempt": evidence["attempt"],
                    "commit": evidence["commit"],
                    "evidence_artifact_digest": publication["digest"],
                    "evidence_artifact_id": publication["id"],
                    "evidence_artifact_name": publication["name"],
                    "run_id": evidence["run_id"],
                    "schema_versions": evidence["schema_versions"],
                    "state": state,
                },
                sort_keys=True,
            )
            + "\n```\n"
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
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"deployment_id={record}\n")
    status(record, "in_progress", run, attempt)


def prepare() -> None:
    sha, run, attempt = identity()
    evidence = _prerequisites(sha, run, attempt, _needs())
    path = Path(os.environ["RUNNER_TEMP"]) / EVIDENCE_FILE
    path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")


def finish() -> None:
    sha, run, attempt = identity()
    needs = _needs()
    record = _record(needs)
    _validate_record(record, sha, run, attempt)
    try:
        evidence = _prerequisites(sha, run, attempt, needs)
        publication = _publication(run, attempt)
    except DeploymentStatusError as error:
        status(record, "failure", run, attempt)
        _summary(
            "failure",
            {
                "artifact_digest": "unavailable",
                "artifact_id": "unavailable",
                "attempt": attempt,
                "commit": sha,
                "run_id": run,
                "schema_versions": "unavailable",
            },
            {"digest": "unavailable", "id": "unavailable", "name": "unavailable"},
        )
        raise error
    try:
        _summary("pending", evidence, publication)
    except (KeyError, OSError, TypeError, ValueError) as error:
        status(record, "failure", run, attempt)
        raise DeploymentStatusError("publisher_failed") from error
    status(record, "success", run, attempt)


def main() -> int:
    command = sys.argv[1:]
    if command == ["create"]:
        stage = "release-record"
    elif command == ["prepare"]:
        stage = "release-evidence-prepare"
    elif command == ["finish"]:
        stage = "release-status"
    else:
        stage = "release-evidence-invalid"
    try:
        _emit_progress(stage, "start")
        if command == ["create"]:
            create()
        elif command == ["prepare"]:
            prepare()
        elif command == ["finish"]:
            finish()
        else:
            raise DeploymentStatusError("malformed_evidence")
    except DeploymentStatusError as error:
        _emit_progress(stage, "fail", error.reason, 1)
        print("development deployment evidence failed closed", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        _emit_progress(stage, "fail", "publisher_failed", 1)
        print("development deployment evidence failed closed", file=sys.stderr)
        return 1
    _emit_progress(stage, "pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

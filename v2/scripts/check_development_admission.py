#!/usr/bin/env python3
"""Fail-closed admission checks for a protected-main development delivery."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
ZERO_SHA = "0" * 40
DELIVERY_WORKFLOW = "v2-development-delivery.yml"
REQUIRED_WORKFLOWS: dict[str, tuple[str, ...]] = {
    "ci.yml": ("v2-loader", "v2-database"),
    "gitleaks.yml": ("gitleaks",),
    "trivy.yml": ("scan",),
}
TERRAFORM_PATH_PREFIXES = ("infra/", "v2/infra/")
TERRAFORM_PATHS = (
    ".github/workflows/terraform.yml",
    ".github/workflows/v2-production-plan.yml",
)
TERMINAL_STATUSES = {"completed"}
ADMISSION_REASONS = {
    "unclassified",
    "api_unavailable",
    "malformed_evidence",
    "missing_evidence",
    "running_evidence",
    "predecessor_pending",
    "upstream_failed",
    "stale_rerun",
    "timeout",
    "recheck_not_ready",
}
_progress_started: float | None = None


class AdmissionError(RuntimeError):
    """An admission check failed closed."""


class RetryableAdmission(AdmissionError):
    """Evidence is not ready yet and may become valid before the deadline."""


def _admission_reason(error: BaseException) -> str:
    """Map local, reviewed control-flow messages to bounded reason tokens."""

    message = str(error)
    if "API request failed" in message:
        return "api_unavailable"
    if "malformed" in message:
        return "malformed_evidence"
    if "predecessor" in message:
        return "predecessor_pending"
    if "missing" in message or "unavailable" in message:
        return "missing_evidence"
    if "still running" in message or "active job" in message:
        return "running_evidence"
    if "stale" in message:
        return "stale_rerun"
    if "timed out" in message:
        return "timeout"
    if "recheck" in message:
        return "recheck_not_ready"
    if "not successful" in message:
        return "upstream_failed"
    return "unclassified"


def _emit_progress(
    status: str, reason: str = "unclassified", exit_code: int = 0
) -> None:
    """Emit only fixed, non-sensitive progress fields."""

    global _progress_started
    if status == "start":
        _progress_started = time.monotonic()
    elapsed = 0
    if _progress_started is not None:
        elapsed = max(int(time.monotonic() - _progress_started), 0)
    if reason not in ADMISSION_REASONS:
        reason = "unclassified"
    event = f"stage=admission status={status} elapsed={elapsed} exit={exit_code} reason={reason}"
    print(event, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write(event + "\n")
        except OSError:
            # Summary writes are diagnostic-only and must never change admission.
            print(
                "stage=admission status=fail elapsed=0 exit=125 reason=diagnostic_unavailable",
                file=sys.stderr,
            )


class GitHubAPI:
    """Tiny GitHub REST client; response bodies never appear in errors."""

    def __init__(
        self,
        repository: str,
        token: str,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.repository = repository
        self.token = token
        self.opener = opener

    def get(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> dict[str, object]:
        query = urllib.parse.urlencode(params or {})
        url = f"https://api.github.com/repos/{self.repository}{path}"
        if query:
            url += f"?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self.opener(request, timeout=20) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
            raise RetryableAdmission("GitHub API request failed") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RetryableAdmission(
                "GitHub API returned malformed evidence"
            ) from error
        if not isinstance(value, dict):
            raise RetryableAdmission("GitHub API returned malformed evidence")
        return cast(dict[str, object], value)


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _repository_matches(value: object, repository: str) -> bool:
    if not isinstance(value, dict):
        return False
    return _string(cast(dict[str, object], value).get("full_name")) == repository


def _run_identity(
    run: Mapping[str, object], repository: str, sha: str, workflow: str
) -> bool:
    return (
        _valid_sha(run.get("head_sha"))
        and run.get("head_sha") == sha
        and run.get("event") == "push"
        and run.get("head_branch") == "main"
        and run.get("path") == f".github/workflows/{workflow}"
        and _repository_matches(run.get("repository"), repository)
        and _repository_matches(run.get("head_repository"), repository)
        and isinstance(run.get("id"), int)
        and isinstance(run.get("run_attempt"), int)
        and cast(int, run["run_attempt"]) > 0
    )


def _runs(payload: Mapping[str, object]) -> list[dict[str, object]]:
    values_value = payload.get("workflow_runs")
    if not isinstance(values_value, list):
        raise RetryableAdmission("workflow-run evidence is malformed")
    values = cast(list[object], values_value)
    total_count = payload.get("total_count")
    if (isinstance(total_count, int) and total_count != len(values)) or len(
        values
    ) >= 100:
        raise AdmissionError("workflow-run evidence is truncated")
    if any(not isinstance(value, dict) for value in values):
        raise RetryableAdmission("workflow-run evidence is malformed")
    return [cast(dict[str, object], value) for value in values]


def _one_run(
    api: GitHubAPI,
    repository: str,
    workflow: str,
    sha: str,
    *,
    require_success: bool,
) -> dict[str, object]:
    payload = api.get(
        f"/actions/workflows/{workflow}/runs",
        {"event": "push", "branch": "main", "head_sha": sha, "per_page": "100"},
    )
    runs = _runs(payload)
    same_sha = [run for run in runs if run.get("head_sha") == sha]
    candidates = [
        run for run in same_sha if _run_identity(run, repository, sha, workflow)
    ]
    if len(candidates) != len(same_sha):
        raise AdmissionError(f"invalid {workflow} run identity")
    if not candidates:
        raise RetryableAdmission(f"missing {workflow} evidence")
    if len(candidates) != 1:
        raise AdmissionError(f"ambiguous {workflow} evidence")
    run = candidates[0]
    status = _string(run.get("status"))
    conclusion = _string(run.get("conclusion"))
    if status not in TERMINAL_STATUSES:
        raise RetryableAdmission(f"{workflow} evidence is still running")
    if require_success and conclusion != "success":
        raise AdmissionError(f"{workflow} evidence is not successful")
    return run


def _jobs(
    api: GitHubAPI, run: Mapping[str, object], expected: tuple[str, ...], sha: str
) -> None:
    run_id = run.get("id")
    run_attempt = run.get("run_attempt")
    if not isinstance(run_id, int) or not isinstance(run_attempt, int):
        raise AdmissionError("workflow-run identity is malformed")
    payload = api.get(f"/actions/runs/{run_id}/jobs", {"per_page": "100"})
    values_value = payload.get("jobs")
    if not isinstance(values_value, list):
        raise RetryableAdmission("workflow-job evidence is malformed")
    values = cast(list[object], values_value)
    total_count = payload.get("total_count")
    if (isinstance(total_count, int) and total_count != len(values)) or len(
        values
    ) >= 100:
        raise AdmissionError("workflow-job evidence is truncated")
    if any(not isinstance(value, dict) for value in values):
        raise RetryableAdmission("workflow-job evidence is malformed")
    jobs = [cast(dict[str, object], value) for value in values]
    for name in expected:
        matching = [job for job in jobs if job.get("name") == name]
        if not matching:
            raise RetryableAdmission(f"missing job evidence: {name}")
        if len(matching) != 1:
            raise AdmissionError(f"ambiguous job evidence: {name}")
        job = matching[0]
        if (
            job.get("run_id") != run_id
            or job.get("run_attempt") != run_attempt
            or job.get("head_sha") != sha
        ):
            raise AdmissionError(f"stale job evidence: {name}")
        if job.get("status") != "completed":
            raise RetryableAdmission(f"job evidence is still running: {name}")
        if job.get("conclusion") != "success":
            raise AdmissionError(f"job evidence is not successful: {name}")


def terraform_applicable(paths: list[str]) -> bool:
    return any(
        path.startswith(TERRAFORM_PATH_PREFIXES) or path in TERRAFORM_PATHS
        for path in paths
    )


def _delivery_jobs_terminal(api: GitHubAPI, run: Mapping[str, object]) -> None:
    run_id = run.get("id")
    if not isinstance(run_id, int):
        raise AdmissionError("predecessor identity is malformed")
    payload = api.get(f"/actions/runs/{run_id}/jobs", {"per_page": "100"})
    values_value = payload.get("jobs")
    if not isinstance(values_value, list):
        raise RetryableAdmission("predecessor job evidence is unavailable")
    values = cast(list[object], values_value)
    total_count = payload.get("total_count")
    if (
        not values
        and _string(run.get("conclusion")) == "cancelled"
        and total_count == 0
    ):
        return
    if not values:
        raise RetryableAdmission("predecessor job evidence is unavailable")
    if (isinstance(total_count, int) and total_count != len(values)) or len(
        values
    ) >= 100:
        raise AdmissionError("predecessor job evidence is truncated")
    if any(not isinstance(value, dict) for value in values):
        raise RetryableAdmission("predecessor job evidence is malformed")
    for value in values:
        if not isinstance(value, dict):
            raise RetryableAdmission("predecessor job evidence is malformed")
        job = cast(dict[str, object], value)
        if job.get("status") not in TERMINAL_STATUSES:
            raise RetryableAdmission("predecessor still has an active job")


def _predecessor(api: GitHubAPI, repository: str, before: str) -> None:
    if before == ZERO_SHA:
        return
    if not _valid_sha(before):
        raise AdmissionError("predecessor SHA is malformed")
    run = _one_run(
        api,
        repository,
        DELIVERY_WORKFLOW,
        before,
        require_success=False,
    )
    if _string(run.get("status")) != "completed":
        raise RetryableAdmission("predecessor delivery is still running")
    _delivery_jobs_terminal(api, run)


def _newer_run(run: Mapping[str, object], current: Mapping[str, object]) -> bool:
    run_number = run.get("run_number")
    current_number = current.get("run_number")
    if isinstance(run_number, int) and isinstance(current_number, int):
        return run_number > current_number
    return _string(run.get("created_at")) > _string(current.get("created_at"))


def _descendant(api: GitHubAPI, ancestor: str, candidate: str) -> bool:
    if not _valid_sha(candidate) or candidate == ancestor:
        return False
    payload = api.get(
        f"/compare/{urllib.parse.quote(ancestor, safe='')}...{urllib.parse.quote(candidate, safe='')}"
    )
    ahead_by = payload.get("ahead_by")
    return (
        payload.get("status") == "ahead" and isinstance(ahead_by, int) and ahead_by > 0
    )


def _has_started_deploy(api: GitHubAPI, run: Mapping[str, object]) -> bool:
    run_id = run.get("id")
    if not isinstance(run_id, int):
        raise AdmissionError("descendant identity is malformed")
    payload = api.get(
        f"/actions/runs/{run_id}/jobs", {"filter": "all", "per_page": "100"}
    )
    values_value = payload.get("jobs")
    if not isinstance(values_value, list):
        raise RetryableAdmission("descendant job evidence is malformed")
    values = cast(list[object], values_value)
    total_count = payload.get("total_count")
    if (isinstance(total_count, int) and total_count != len(values)) or len(
        values
    ) >= 100:
        raise AdmissionError("descendant job evidence is truncated")
    for value in values:
        if not isinstance(value, dict):
            continue
        job = cast(dict[str, object], value)
        if job.get("name") != "Deploy v2 to development":
            continue
        if job.get("run_id") != run_id or job.get("head_sha") != run.get("head_sha"):
            raise AdmissionError("descendant job identity is malformed")
        if job.get("status") == "in_progress":
            return True
        if (
            job.get("status") == "completed"
            and job.get("conclusion") != "skipped"
            and bool(job.get("started_at"))
        ):
            return True
    return False


def reject_stale_rerun(
    api: GitHubAPI,
    repository: str,
    sha: str,
    current_run: Mapping[str, object],
) -> None:
    params = {"event": "push", "branch": "main", "per_page": "100"}
    created_at = _string(current_run.get("created_at"))
    if created_at:
        params["created"] = f">={created_at}"
    payload = api.get(f"/actions/workflows/{DELIVERY_WORKFLOW}/runs", params)
    for run in _runs(payload):
        if not _run_identity(
            run, repository, _string(run.get("head_sha")), DELIVERY_WORKFLOW
        ):
            continue
        if run.get("id") == current_run.get("id") or not _newer_run(run, current_run):
            continue
        descendant = _string(run.get("head_sha"))
        if (
            descendant != sha
            and _descendant(api, sha, descendant)
            and _has_started_deploy(api, run)
        ):
            raise AdmissionError("candidate is stale after a newer delivery started")


def _validate_event(
    event: Mapping[str, object], repository: str, sha: str, before: str
) -> None:
    event_repository = event.get("repository")
    if not _repository_matches(event_repository, repository):
        raise AdmissionError("push repository does not match candidate")
    if event.get("ref") != "refs/heads/main" or event.get("after") != sha:
        raise AdmissionError("push ref or SHA does not match candidate")
    if event.get("before") != before:
        raise AdmissionError("predecessor does not match push event")


def admit(
    api: GitHubAPI,
    *,
    repository: str,
    sha: str,
    before: str,
    paths: list[str],
    current_run_id: int | None = None,
    timeout_seconds: float = 900,
    poll_seconds: float = 10,
    check_predecessor: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    if not _valid_sha(sha) or sha != sha.lower():
        raise AdmissionError("candidate SHA is malformed")
    if before != ZERO_SHA and not _valid_sha(before):
        raise AdmissionError("predecessor SHA is malformed")
    _emit_progress("start")
    deadline = time.monotonic() + max(timeout_seconds, 0)
    while True:
        try:
            if terraform_applicable(paths):
                terraform_run = _one_run(
                    api, repository, "terraform.yml", sha, require_success=True
                )
                _jobs(api, terraform_run, ("fmt-validate",), sha)
            for workflow, expected in REQUIRED_WORKFLOWS.items():
                run = _one_run(api, repository, workflow, sha, require_success=True)
                _jobs(api, run, expected, sha)
            if check_predecessor:
                _predecessor(api, repository, before)
            current = {
                "id": current_run_id,
                "run_number": 0,
                "created_at": "",
            }
            if current_run_id is not None:
                delivery = api.get(f"/actions/runs/{current_run_id}")
                if not _run_identity(delivery, repository, sha, DELIVERY_WORKFLOW):
                    raise AdmissionError("current delivery identity does not match SHA")
                current = delivery
            reject_stale_rerun(api, repository, sha, current)
            _emit_progress("pass")
            return True
        except RetryableAdmission as error:
            reason = _admission_reason(error)
            _emit_progress("pending", reason)
            if not check_predecessor:
                raise AdmissionError("admission recheck not ready") from None
            if time.monotonic() >= deadline:
                raise AdmissionError("admission timed out") from None
            sleep(min(max(poll_seconds, 0), max(deadline - time.monotonic(), 0)))


def _event(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdmissionError("push event payload is unavailable") from error
    if not isinstance(value, dict):
        raise AdmissionError("push event payload is malformed")
    return cast(dict[str, object], value)


def _paths_file(path: Path) -> list[str]:
    try:
        values = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise AdmissionError("push changed-path evidence is unavailable") from error
    if any(not value or "\x00" in value for value in values):
        raise AdmissionError("push changed-path evidence is malformed")
    return sorted(set(values))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--before", default="")
    parser.add_argument("--event-file", type=Path, required=True)
    parser.add_argument("--paths-file", type=Path, required=True)
    parser.add_argument(
        "--run-id", type=int, default=int(os.environ.get("GITHUB_RUN_ID", "0")) or None
    )
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--recheck", action="store_true")
    args = parser.parse_args(argv)
    try:
        event = _event(args.event_file)
        before = args.before or _string(event.get("before"))
        _validate_event(event, args.repository, args.sha, before)
        paths = _paths_file(args.paths_file)
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise AdmissionError("GitHub actions-read token is unavailable")
        admit(
            GitHubAPI(args.repository, token),
            repository=args.repository,
            sha=args.sha,
            before=before,
            paths=paths,
            current_run_id=args.run_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            check_predecessor=not args.recheck,
        )
    except AdmissionError as error:
        _emit_progress("fail", _admission_reason(error), 1)
        print("development admission rejected", file=sys.stderr)
        return 1
    terraform = "required" if terraform_applicable(paths) else "not-required"
    print(f"development admission accepted: sha={args.sha} terraform={terraform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

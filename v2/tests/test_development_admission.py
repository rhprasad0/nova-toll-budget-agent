from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

SPEC = importlib.util.spec_from_file_location(
    "check_development_admission",
    Path(__file__).parents[1] / "scripts/check_development_admission.py",
)
assert SPEC and SPEC.loader
admission = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admission)

REPOSITORY = "rhprasad0/nova-toll-budget-agent"
SHA = "a" * 40
BEFORE = "b" * 40
DESCENDANT = "c" * 40


def _run(
    sha: str, run_id: int, *, conclusion: str = "success", number: int = 1
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_number": number,
        "run_attempt": 1,
        "head_sha": sha,
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": conclusion,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        "path": ".github/workflows/ci.yml",
        "created_at": f"2026-09-07T00:0{number}:00Z",
    }


def _job(
    name: str, run_id: int, sha: str, *, conclusion: str = "success"
) -> dict[str, object]:
    return {
        "name": name,
        "run_id": run_id,
        "run_attempt": 1,
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
    }


class FakeAPI:
    def __init__(self) -> None:
        self.runs: dict[str, list[dict[str, object]]] = {
            "ci.yml": [_run(SHA, 101)],
            "gitleaks.yml": [_run(SHA, 102)],
            "trivy.yml": [_run(SHA, 103)],
            "v2-development-delivery.yml": [_run(SHA, 900, number=9)],
        }
        self.jobs: dict[int, list[dict[str, object]]] = {
            101: [_job("v2-loader", 101, SHA), _job("v2-database", 101, SHA)],
            102: [_job("gitleaks", 102, SHA)],
            103: [_job("scan", 103, SHA)],
            800: [_job("Deploy v2 to development", 800, BEFORE)],
            900: [_job("Admit exact main delivery", 900, SHA)],
        }
        self.predecessor = _run(BEFORE, 800, conclusion="failure", number=8)
        self.descendant: dict[str, object] | None = None

    def get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        params = params or {}
        if path.endswith("/runs"):
            workflow = path.rsplit("/", 2)[-2]
            sha = params.get("head_sha")
            if workflow == admission.DELIVERY_WORKFLOW and sha == BEFORE:
                self.predecessor["path"] = (
                    ".github/workflows/v2-development-delivery.yml"
                )
                return {"workflow_runs": [self.predecessor]}
            if workflow == admission.DELIVERY_WORKFLOW and sha is None:
                runs = list(self.runs[workflow])
                if self.descendant is not None:
                    runs.append(self.descendant)
                for run in runs:
                    run["path"] = ".github/workflows/v2-development-delivery.yml"
                return {"workflow_runs": runs}
            values = self.runs.get(workflow, [])
            for run in values:
                run["path"] = f".github/workflows/{workflow}"
            return {"workflow_runs": values}
        if path.startswith("/actions/runs/") and path.endswith("/jobs"):
            jobs = self.jobs.get(int(path.split("/")[3]), [])
            return {"jobs": jobs, "total_count": len(jobs)}
        if path.startswith("/compare/"):
            return {"status": "ahead", "ahead_by": 1}
        raise AssertionError(f"unexpected API path: {path}")


def _admit(api: FakeAPI, *, paths: list[str] | None = None) -> bool:
    return admission.admit(
        cast(Any, api),
        repository=REPOSITORY,
        sha=SHA,
        before=BEFORE,
        paths=paths or ["v2/agent/dev_chat.html"],
        timeout_seconds=0,
        poll_seconds=0,
    )


def test_exact_sha_evidence_and_terminal_predecessor_are_admitted() -> None:
    assert _admit(FakeAPI()) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ref", "refs/heads/release"),
        ("after", "d" * 40),
        ("repository", {"full_name": "evil/fork"}),
    ],
)
def test_wrong_push_identity_is_rejected(field: str, value: object) -> None:
    event: dict[str, object] = {
        "ref": "refs/heads/main",
        "after": SHA,
        "before": BEFORE,
        "repository": {"full_name": REPOSITORY},
    }
    event[field] = value
    with pytest.raises(admission.AdmissionError):
        admission._validate_event(event, REPOSITORY, SHA, BEFORE)


def test_missing_or_duplicate_runs_fail_closed() -> None:
    missing = FakeAPI()
    missing.runs["trivy.yml"] = []
    with pytest.raises(admission.AdmissionError, match="timed out"):
        _admit(missing)

    duplicate = FakeAPI()
    duplicate.runs["ci.yml"].append(_run(SHA, 104, number=2))
    with pytest.raises(admission.AdmissionError, match="ambiguous"):
        _admit(duplicate)


def test_skipped_or_stale_job_evidence_is_rejected() -> None:
    skipped = FakeAPI()
    skipped.jobs[101][0]["conclusion"] = "skipped"
    with pytest.raises(admission.AdmissionError, match="not successful"):
        _admit(skipped)

    stale = FakeAPI()
    stale.jobs[101][0]["run_attempt"] = 2
    with pytest.raises(admission.AdmissionError, match="stale"):
        _admit(stale)


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled"])
def test_terminal_predecessor_conclusions_release_ordering(conclusion: str) -> None:
    api = FakeAPI()
    api.predecessor["conclusion"] = conclusion
    assert _admit(api) is True


def test_canceled_predecessor_without_started_jobs_releases_ordering() -> None:
    api = FakeAPI()
    api.predecessor["conclusion"] = "cancelled"
    api.jobs[800] = []
    assert _admit(api) is True


def test_first_push_has_no_predecessor() -> None:
    api = FakeAPI()
    assert (
        admission.admit(
            cast(Any, api),
            repository=REPOSITORY,
            sha=SHA,
            before=admission.ZERO_SHA,
            paths=[],
            timeout_seconds=0,
            poll_seconds=0,
        )
        is True
    )


def test_terraform_evidence_is_required_only_for_matching_paths() -> None:
    api = FakeAPI()
    api.runs["terraform.yml"] = [_run(SHA, 104)]
    api.jobs[104] = [_job("fmt-validate", 104, SHA)]
    assert _admit(api, paths=["v2/infra/main.tf"]) is True

    missing = FakeAPI()
    with pytest.raises(admission.AdmissionError, match="timed out"):
        _admit(missing, paths=["infra/main.tf"])


def test_later_ci_first_is_bounded_and_eventually_admitted() -> None:
    api = FakeAPI()
    original = api.runs["ci.yml"]
    calls = 0

    def delayed_get(
        path: str, params: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        nonlocal calls
        if path.endswith("/ci.yml/runs"):
            calls += 1
            if calls == 1:
                api.runs["ci.yml"] = []
        return FakeAPI.get(api, path, params)

    api.get = delayed_get  # type: ignore[method-assign]

    def restore(_delay: float) -> None:
        api.runs = {**api.runs, "ci.yml": original}

    assert (
        admission.admit(
            cast(Any, api),
            repository=REPOSITORY,
            sha=SHA,
            before=BEFORE,
            paths=[],
            timeout_seconds=1,
            poll_seconds=0,
            sleep=restore,
        )
        is True
    )


def test_newer_descendant_mutation_rejects_old_rerun() -> None:
    api = FakeAPI()
    api.descendant = _run(DESCENDANT, 901, number=10)
    api.jobs[901] = [_job("Deploy v2 to development", 901, DESCENDANT)]
    api.jobs[901][0]["status"] = "in_progress"
    api.jobs[901][0]["started_at"] = "2026-09-07T00:10:00Z"
    with pytest.raises(admission.AdmissionError, match="stale"):
        _admit(api)


def test_older_started_descendant_attempt_rejects_latest_queued_rerun() -> None:
    api = FakeAPI()
    api.descendant = _run(DESCENDANT, 901, number=10)
    failed = _job("Deploy v2 to development", 901, DESCENDANT, conclusion="failure")
    failed["started_at"] = "2026-09-07T00:10:00Z"
    queued = _job("Deploy v2 to development", 901, DESCENDANT, conclusion="")
    queued["run_attempt"] = 2
    queued["status"] = "queued"
    api.jobs[901] = [failed, queued]
    with pytest.raises(admission.AdmissionError, match="stale"):
        _admit(api)


def test_deploy_recheck_does_not_wait_for_predecessor_inside_apply_lock() -> None:
    api = FakeAPI()
    api.runs[admission.DELIVERY_WORKFLOW] = []
    assert (
        admission.admit(
            cast(Any, api),
            repository=REPOSITORY,
            sha=SHA,
            before=BEFORE,
            paths=[],
            check_predecessor=False,
            timeout_seconds=0,
            poll_seconds=0,
        )
        is True
    )


def test_progress_events_are_fixed_and_mirrored_without_exception_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(admission, "_progress_started", None)
    admission._emit_progress("start")
    admission._emit_progress("pending", "not-a-reviewed-reason")
    captured = capsys.readouterr()
    assert "stage=admission status=start" in captured.err
    assert "reason=unclassified" in captured.err
    assert "not-a-reviewed-reason" not in captured.err
    assert "stage=admission status=pending" in summary.read_text()


def test_workflow_keeps_retained_artifact_guard_and_pr_only_packages() -> None:
    root = Path(__file__).parents[2]
    delivery = (root / ".github/workflows/v2-development-delivery.yml").read_text()
    ci = (root / ".github/workflows/ci.yml").read_text()
    assert "Reject retained exact release artifact" in delivery
    assert 'type == "object" and (.artifacts | type == "array")' in delivery
    assert "github.event_name == 'pull_request'" in ci
    assert delivery.index("Reject retained exact release artifact") < delivery.index(
        "astral-sh/setup-uv@"
    )
    for command in (
        "build_fetcher_zip.sh",
        "build_loader_zip.sh",
        "build_publisher_zip.sh",
        "build_agentcore_zips.sh",
    ):
        assert ci.index(command) > ci.index("github.event_name == 'pull_request'")


def test_retained_artifact_guard_rejects_malformed_metadata() -> None:
    predicate = 'type == "object" and (.artifacts | type == "array")'
    for metadata in ("{}", '{"artifacts": null}', "not-json"):
        result = subprocess.run(
            ["jq", "-e", predicate],
            input=metadata,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0

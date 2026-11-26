from __future__ import annotations

import importlib.util
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
import yaml

if TYPE_CHECKING:
    from scripts import check_development_admission as admission
else:
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
DELIVERY_PATH = ".github/workflows/v2-development-delivery.yml"
ROOT = Path(__file__).parents[2]


def _run(
    sha: str,
    run_id: int,
    *,
    conclusion: str = "success",
    number: int = 1,
    event: str = "push",
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_number": number,
        "run_attempt": 1,
        "head_sha": sha,
        "event": event,
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
        }
        self.jobs: dict[int, list[dict[str, object]]] = {
            101: [_job("v2-loader", 101, SHA), _job("v2-database", 101, SHA)],
            102: [_job("gitleaks", 102, SHA)],
            103: [_job("scan", 103, SHA)],
            900: [_job("Admit exact main delivery", 900, SHA)],
        }
        self.current = _run(SHA, 900, number=9, event="push")
        self.current.update(status="in_progress", conclusion=None, path=DELIVERY_PATH)
        self.history = [_run(BEFORE, 800, number=8)]
        self.descendant: dict[str, object] | None = None
        self.compare_status = "ahead"

    def get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        params = params or {}
        if path == "/actions/runs/900":
            return self.current
        if path.endswith("/runs"):
            workflow = path.rsplit("/", 2)[-2]
            if workflow == admission.DELIVERY_WORKFLOW:
                assert "event" not in params
                if params.get("status") == "success":
                    runs = [
                        run for run in self.history if run["conclusion"] == "success"
                    ]
                else:
                    runs = [self.current, *self.history]
                    if self.descendant is not None:
                        runs.append(self.descendant)
                for run in runs:
                    run["path"] = DELIVERY_PATH
                return {"workflow_runs": runs}
            values = self.runs.get(workflow, [])
            for run in values:
                run["path"] = f".github/workflows/{workflow}"
            return {"workflow_runs": values}
        if path.startswith("/actions/runs/") and path.endswith("/jobs"):
            jobs = self.jobs.get(int(path.split("/")[3]), [])
            return {"jobs": jobs, "total_count": len(jobs)}
        if path.startswith("/compare/"):
            return {"status": self.compare_status, "ahead_by": 1}
        raise AssertionError(f"unexpected API path: {path}")


def _admit(api: FakeAPI, *, paths: list[str] | None = None, wait: bool = True) -> bool:
    return admission.admit(
        cast(Any, api),
        repository=REPOSITORY,
        sha=SHA,
        paths=paths or ["v2/agent/dev_chat.html"],
        current=api.current,
        timeout_seconds=0,
        poll_seconds=0,
        wait=wait,
    )


def test_exact_sha_evidence_is_admitted() -> None:
    assert _admit(FakeAPI()) is True


@pytest.mark.parametrize(
    ("event_name", "ref", "accepted"),
    [
        ("push", "refs/heads/main", True),
        ("workflow_dispatch", "refs/heads/main", True),
        ("workflow_dispatch", "refs/heads/feature", False),
        ("push", "refs/heads/feature", False),
        ("schedule", "refs/heads/main", False),
        ("pull_request", "refs/pull/1/merge", False),
    ],
)
def test_only_pushed_or_dispatched_main_runs_deliver(
    event_name: str, ref: str, accepted: bool
) -> None:
    if accepted:
        admission._validate_trigger(event_name, ref)
    else:
        with pytest.raises(admission.AdmissionError):
            admission._validate_trigger(event_name, ref)


def test_missing_or_duplicate_runs_fail_closed() -> None:
    missing = FakeAPI()
    missing.runs["trivy.yml"] = []
    with pytest.raises(admission.AdmissionError, match="timed out"):
        _admit(missing)

    duplicate = FakeAPI()
    duplicate.runs["ci.yml"].append(_run(SHA, 104, number=2))
    with pytest.raises(admission.AdmissionError, match="ambiguous"):
        _admit(duplicate)


def test_ci_evidence_must_come_from_the_push() -> None:
    api = FakeAPI()
    api.runs["ci.yml"] = [_run(SHA, 101, event="workflow_dispatch")]
    with pytest.raises(admission.AdmissionError, match="identity"):
        _admit(api)


def test_skipped_or_stale_job_evidence_is_rejected() -> None:
    skipped = FakeAPI()
    skipped.jobs[101][0]["conclusion"] = "skipped"
    with pytest.raises(admission.AdmissionError, match="not successful"):
        _admit(skipped)

    stale = FakeAPI()
    stale.jobs[101][0]["run_attempt"] = 2
    with pytest.raises(admission.AdmissionError, match="stale"):
        _admit(stale)


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

    api.get = delayed_get

    def restore(_delay: float) -> None:
        api.runs = {**api.runs, "ci.yml": original}

    assert (
        admission.admit(
            cast(Any, api),
            repository=REPOSITORY,
            sha=SHA,
            paths=[],
            current=api.current,
            timeout_seconds=1,
            poll_seconds=0,
            sleep=restore,
        )
        is True
    )


@pytest.mark.parametrize(
    "job_name",
    ["Deploy v2 to development", "Deploy v2 to development / Deploy v2 to development"],
)
@pytest.mark.parametrize("state", ["in_progress", "completed"])
@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
def test_newer_descendant_mutation_rejects_old_rerun(
    job_name: str, state: str, event: str
) -> None:
    api = FakeAPI()
    api.descendant = _run(DESCENDANT, 901, number=10, event=event)
    api.jobs[901] = [_job(job_name, 901, DESCENDANT)]
    api.jobs[901][0]["status"] = state
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


def test_deploy_recheck_fails_instead_of_waiting_inside_apply_lock() -> None:
    assert _admit(FakeAPI(), wait=False) is True
    api = FakeAPI()
    api.runs["ci.yml"][0].update(status="in_progress", conclusion=None)
    with pytest.raises(admission.AdmissionError, match="recheck not ready"):
        _admit(api, wait=False)


def test_predecessor_lookup_retries_only_transient_api_errors() -> None:
    api = FakeAPI()
    failures = 2
    original = api.get

    def flaky(path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        nonlocal failures
        if failures:
            failures -= 1
            raise admission.RetryableAdmission("GitHub API request failed")
        return original(path, params)

    api.get = flaky
    sleeps: list[float] = []
    current, predecessor = admission.resolve_predecessor(
        cast(Any, api),
        REPOSITORY,
        SHA,
        900,
        attempts=3,
        poll_seconds=5,
        sleep=sleeps.append,
    )
    assert (current["id"], predecessor, sleeps) == (900, BEFORE, [5, 5])
    failures = 1
    with pytest.raises(admission.RetryableAdmission):
        admission.resolve_predecessor(
            cast(Any, api), REPOSITORY, SHA, 900, attempts=1, poll_seconds=0
        )
    api.compare_status = "diverged"
    with pytest.raises(admission.AdmissionError, match="does not descend"):
        admission.resolve_predecessor(
            cast(Any, api),
            REPOSITORY,
            SHA,
            900,
            attempts=3,
            poll_seconds=0,
            sleep=sleeps.append,
        )
    assert len(sleeps) == 2  # A definite rejection is not retried.


def test_last_delivered_is_the_newest_earlier_success() -> None:
    api = FakeAPI()
    api.history = [
        _run(BEFORE, 800, number=8),
        _run("d" * 40, 850, number=7, event="schedule"),
        _run("e" * 40, 870, number=8, conclusion="failure", event="schedule"),
        # Later or foreign runs never count.
        _run("f" * 40, 950, number=11, event="workflow_dispatch"),
        {**_run("1" * 40, 860, number=8), "head_branch": "feature"},
        {**_run("2" * 40, 861, number=8), "event": "pull_request"},
    ]
    assert admission.last_delivered(cast(Any, api), REPOSITORY, api.current) == BEFORE
    api.history[0]["run_number"] = 6
    assert admission.last_delivered(cast(Any, api), REPOSITORY, api.current) == "d" * 40
    api.history = []
    with pytest.raises(admission.AdmissionError, match="missing delivery history"):
        admission.last_delivered(cast(Any, api), REPOSITORY, api.current)


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
    assert '../.github/scripts/verify.sh loader "$BASE_REF"' in ci
    assert delivery.index("Reject retained exact release artifact") < delivery.index(
        "astral-sh/setup-uv@"
    )
    verify = (root / ".github/scripts/verify.sh").read_text()
    assert 'event="${GITHUB_EVENT_NAME:-pull_request}"' in verify
    assert (
        '  if [[ "$event" == pull_request ]]; then\n'
        "    step ./scripts/build_fetcher_zip.sh\n"
        "    step ./scripts/build_loader_zip.sh\n"
        "    step ./scripts/build_publisher_zip.sh\n"
        "    step ./scripts/build_agentcore_zips.sh\n"
        "  fi\n"
    ) in verify


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


@pytest.mark.parametrize("ending", ["success", "failure", "pending"])
def test_workflow_waits_thirty_minutes_without_relaxing_evidence(
    monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:

    workflow = (
        Path(__file__).parents[2] / ".github/workflows/v2-development-delivery.yml"
    ).read_text()
    match = re.search(r"--timeout-seconds (\d+)", workflow)
    assert match and int(match[1]) == 1800
    elapsed = 0.0
    api = FakeAPI()
    run = api.runs["ci.yml"][0]
    run.update(status="in_progress", conclusion=None)
    monkeypatch.setattr(admission.time, "monotonic", lambda: elapsed)

    def advance(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds
        if elapsed >= 1110 and ending != "pending":
            run.update(status="completed", conclusion=ending)

    def admit() -> bool:
        return admission.admit(
            cast(Any, api),
            repository=REPOSITORY,
            sha=SHA,
            paths=[],
            current=api.current,
            timeout_seconds=int(match[1]),
            poll_seconds=10,
            sleep=advance,
        )

    if ending == "success":
        assert admit() is True
    else:
        reason = "timed out" if ending == "pending" else "not successful"
        with pytest.raises(admission.AdmissionError, match=reason):
            admit()
    assert elapsed == (1800 if ending == "pending" else 1110)


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["v2/journal/pages/2026-11-09.md", "README.md"], True),
        ([], False),  # No evidence of what changed: deliver.
        (["README.md", "v2/agent/dev_chat.html"], False),
        (["v2/agent-sops/nova-toll-pricing-assistant.sop.md"], False),  # Pinned.
        (["v2/agent/notes.md.py"], False),
        # --no-renames lists both sides of a rename, so the old code path shows.
        (["v2/agent_tools/currency.py", "v2/agent_tools/currency.md"], False),
    ],
)
def test_only_unpinned_markdown_skips_delivery(
    paths: list[str], expected: bool
) -> None:
    assert admission.docs_only(paths) is expected


def test_unreadable_pin_list_delivers(tmp_path: Path) -> None:
    assert admission.docs_only(["README.md"], tmp_path / "missing.json") is False
    malformed = tmp_path / "manifest.json"
    malformed.write_text("[]")
    assert admission.docs_only(["README.md"], malformed) is False


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _workflow_parse(line: str) -> tuple[str, str] | None:
    """Run the delivery workflow's own result parser on one admission line."""
    workflow = yaml.safe_load((ROOT / DELIVERY_PATH).read_text())
    source = next(
        step["run"]
        for step in workflow["jobs"]["admission"]["steps"]
        if step.get("id") == "admit"
    )
    match = re.search(r"^ *(if \[\[ ! \"\$result\" =~ .*\]\]; then)$", source, re.M)
    assert match
    script = (
        f'result="$1"\n{match[1]}\n  exit 1\nfi\n'
        'printf "%s %s\\n" "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"\n'
    )
    parsed = subprocess.run(
        ["bash", "-c", script, "bash", line],
        capture_output=True,
        text=True,
        check=False,
    )
    if parsed.returncode:
        return None
    predecessor, delivery = parsed.stdout.split()
    return predecessor, delivery


def test_main_resolves_predecessor_and_skips_only_when_nothing_deployable_changed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")

    def commit(name: str) -> str:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(name)
        _git(repo, "add", name)
        _git(repo, "commit", "-q", "-m", name)
        return _git(repo, "rev-parse", "HEAD")

    delivered = commit("v2/agent/app.py")
    docs = commit("README.md")
    code = commit("v2/agent/other.py")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GH_TOKEN", "token")
    api = FakeAPI()

    def fake_api(*_: object) -> FakeAPI:
        return api

    def admitted(*_: object, **__: object) -> bool:
        return True

    monkeypatch.setattr(admission, "GitHubAPI", fake_api)
    monkeypatch.setattr(admission, "admit", admitted)

    def run(candidate: str, event: str = "push") -> tuple[int, str]:
        api.current["head_sha"] = candidate
        api.history = [_run(delivered, 800, number=8)]
        status = admission.main(
            [
                "--repository",
                REPOSITORY,
                "--sha",
                candidate,
                "--event-name",
                event,
                "--ref",
                "refs/heads/main",
                "--run-id",
                "900",
            ]
        )
        return status, capsys.readouterr().out.strip()

    for candidate, expected in (
        (delivered, "not-required"),  # Already delivered.
        (docs, "not-required"),  # Only unpinned Markdown since.
        (code, "required"),
    ):
        status, line = run(candidate, "workflow_dispatch")
        assert status == 0
        assert _workflow_parse(line) == (delivered, expected)

    assert run(code, "schedule") == (1, "")
    api.compare_status = "diverged"
    assert run(code) == (1, "")
    assert _workflow_parse("development admission accepted: sha=x") is None


def test_delivery_runs_only_on_dispatch_one_at_a_time() -> None:
    workflow = yaml.safe_load((ROOT / DELIVERY_PATH).read_text())
    triggers = workflow[True]  # PyYAML reads the bare `on` key as True.
    assert triggers == {"workflow_dispatch": None}
    assert workflow["concurrency"] == {
        "group": "v2-development-delivery-${{ github.ref }}",
        "cancel-in-progress": False,
    }
    jobs = workflow["jobs"]
    assert jobs["admission"]["outputs"] == {
        "deliver": "${{ steps.admit.outputs.deliver }}",
        "predecessor": "${{ steps.admit.outputs.predecessor }}",
    }
    assert jobs["release-record"]["if"] == "needs.admission.outputs.deliver != 'false'"
    # A failed admission leaves the output empty, so the result is still recorded.
    assert (
        jobs["release-result"]["if"]
        == "always() && needs.admission.outputs.deliver != 'false'"
    )
    schema_base = next(
        step["env"]["SCHEMA_BASE_REF"]
        for step in jobs["build"]["steps"]
        if "SCHEMA_BASE_REF" in step.get("env", {})
    )
    assert schema_base == "${{ needs.admission.outputs.predecessor }}"
    for path in (
        DELIVERY_PATH,
        ".github/workflows/v2-development-delivery-privileged.yml",
    ):
        assert "github.event.before" not in (ROOT / path).read_text()

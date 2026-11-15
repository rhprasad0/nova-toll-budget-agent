import json
import re
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from factory.host import dispatcher, inbox, trace, workorder

ISSUE = 7
BRANCH = f"factory/issue-{ISSUE}"
Action = Callable[[Path, str], dict[str, Any]]
Make = Callable[..., tuple[sqlite3.Connection, "FakeGitHub", "Sandbox"]]


def git(repo: Path, *args: str | Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                           *map(str, args)], check=True, capture_output=True, text=True).stdout  # fmt: skip


def check_run(conclusion: str, job: int = 900) -> dict[str, Any]:
    return {"__typename": "CheckRun", "name": "v2-loader", "status": "COMPLETED",
            "conclusion": conclusion, "databaseId": job, "isRequired": True}  # fmt: skip


class FakeGitHub:
    def __init__(self, github: Path) -> None:
        self.github = github
        self.writes: list[tuple[str, str, dict[str, str]]] = []
        self.ci: list[list[dict[str, Any]]] = []
        self.comments = 100

    def api(self, path: str, method: str = "GET", **fields: str) -> Any:  # noqa: ANN401
        if method != "GET":
            self.writes.append((method, path, fields))
        if path.endswith(f"/issues/{ISSUE}") and method == "GET":
            return {"title": "Fix the route", "body": "The route is wrong."}
        if path.endswith("/comments") and method == "POST":
            self.comments += 1
            return {"id": self.comments}
        if path.endswith("/pulls") and method == "POST":
            return {"number": 42}
        if path == "graphql":
            nodes = (
                self.ci.pop(0)
                if len(self.ci) > 1
                else (self.ci or [[check_run("SUCCESS")]])[0]
            )
            oid = git(self.github, "rev-parse", BRANCH).strip()
            if nodes and nodes[0].get("stale"):
                oid, nodes = "0" * 40, nodes[1:]
            return {"data": {"repository": {"pullRequest": {"commits": {"nodes": [
                {"commit": {"oid": oid, "statusCheckRollup": {"contexts": {"nodes": nodes}}}}]}}}}}  # fmt: skip
        if re.fullmatch(r".*/actions/jobs/\d+/logs", path):
            return "FAILED tests/test_route.py::test_route - AssertionError\n"
        return {}

    def posted(self, kind: str) -> list[dict[str, str]]:
        return [
            fields
            for method, path, fields in self.writes
            if path.endswith(kind) and method == "POST"
        ]


class Sandbox:
    def __init__(self, tmp: Path, actions: list[Action], verify: list[int]) -> None:
        self.tmp, self.actions, self.verify_codes = tmp, actions, verify
        self.prompts: list[tuple[str, str | None]] = []
        self.worker = tmp / "worker"
        self.cleaned: list[str] = []

    def start(self, work_order: str, branch: str) -> tuple[Path, str]:
        job_dir = dispatcher.STATE / "jobs" / work_order
        job_dir.mkdir(parents=True)
        git(self.tmp, "clone", "--quiet", dispatcher.ORIGIN, self.worker)
        git(self.worker, "checkout", "--quiet", "-b", branch)
        return job_dir, git(self.worker, "rev-parse", "HEAD").strip()

    def round(self, work_order: str, transcript: Path, prompt: str, traceparent: str,
              resume: str | None = None, stop: Callable[[], bool] = lambda: False
              ) -> tuple[dict[str, Any], str]:  # fmt: skip
        self.prompts.append((prompt, resume))
        transcript.write_text("{}\n")
        if stop():
            return {}, "cancelled"
        result = self.actions.pop(0)(self.worker, prompt)
        return result, "done"

    def export(
        self, work_order: str, job_dir: Path, branch: str, base: str
    ) -> Path | None:
        if not git(self.worker, "rev-list", f"{base}..{branch}").strip():
            return None
        bundle = job_dir / "work.bundle"
        git(
            self.worker,
            "bundle",
            "create",
            "--quiet",
            bundle,
            f"refs/heads/{branch}",
            f"^{base}",
        )
        return dispatcher.import_bundle(bundle, branch, job_dir / "clean")

    def verify(self, job: str, profile: str | None, branch: str = "main",
               source: Path | None = None, log_copy: Path | None = None) -> int:  # fmt: skip
        code = self.verify_codes.pop(0) if self.verify_codes else 0
        if log_copy:
            log_copy.write_text(f"verify exit {code}\n")
        return code


def commits(path: str, text: str, result: str = "Fixed the route.") -> Action:
    def act(worker: Path, prompt: str) -> dict[str, Any]:
        (worker / path).parent.mkdir(parents=True, exist_ok=True)
        (worker / path).write_text(text)
        git(worker, "add", "-A")
        git(worker, "commit", "--quiet", "-m", f"Change {path}")
        return {"session_id": "author-session", "result": result,
                "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.5}  # fmt: skip

    return act


def says(result: str) -> Action:
    return lambda worker, prompt: {"session_id": "author-session", "result": result}


@pytest.fixture
def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., tuple[sqlite3.Connection, FakeGitHub, Sandbox]]:
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "--quiet", "--initial-branch=main")
    (seed / "v2").mkdir()
    (seed / "v2/route.py").write_text("ROUTE = 'old'\n")
    git(seed, "add", "-A")
    git(seed, "commit", "--quiet", "-m", "base")
    origin, github = tmp_path / "origin.git", tmp_path / "github.git"
    git(tmp_path, "clone", "--quiet", "--bare", seed, origin)
    git(tmp_path, "clone", "--quiet", "--bare", seed, github)
    monkeypatch.setattr(dispatcher, "ORIGIN", origin)
    monkeypatch.setattr(dispatcher, "STATE", tmp_path / "state")
    monkeypatch.setattr(workorder, "REMOTE", str(github))
    monkeypatch.setattr(workorder, "CI_POLL_SECONDS", 0)
    monkeypatch.setattr(workorder, "CI_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(trace, "ENDPOINT", "http://127.0.0.1:9/v1/traces")

    def archived(path: Path, key: str) -> bool:
        return True

    monkeypatch.setattr(dispatcher, "archive", archived)

    def make(
        actions: list[Action], verify: list[int] | None = None
    ) -> tuple[sqlite3.Connection, FakeGitHub, Sandbox]:
        sandbox = Sandbox(tmp_path, actions, verify or [])
        monkeypatch.setattr(dispatcher, "start_sandbox", sandbox.start)
        monkeypatch.setattr(dispatcher, "run_round", sandbox.round)
        monkeypatch.setattr(dispatcher, "export_branch", sandbox.export)
        monkeypatch.setattr(dispatcher, "verify", sandbox.verify)
        monkeypatch.setattr(dispatcher, "cleanup", sandbox.cleaned.append)
        db = inbox.connect(tmp_path / "inbox.db")
        inbox.record(db, {"id": 1, "created_at": "2026-11-15T12:00:00Z", "actor": {"login": inbox.OWNER}},
                     ISSUE, "labeled")  # fmt: skip
        db.execute(
            "INSERT INTO work_orders (id, issue, event, started) VALUES ('wo', ?, 1, 'now')",
            (ISSUE,),
        )
        return db, FakeGitHub(github), sandbox

    return make


def row(db: sqlite3.Connection) -> sqlite3.Row:
    return db.execute("SELECT * FROM work_orders WHERE id = 'wo'").fetchone()


def pushed(tmp_path: Path) -> str:
    return git(tmp_path / "github.git", "log", "--format=%s", f"main..{BRANCH}").strip()


def test_an_issue_becomes_a_ready_pull_request(setup: Make, tmp_path: Path) -> None:
    db, gh, sandbox = setup([commits("v2/route.py", "ROUTE = 'new'\n", "Fixed it, cc @someone."),
                             says("No changes needed.")])  # fmt: skip
    assert workorder.work(db, gh, row(db)) == "pr_ready"
    assert pushed(tmp_path) == "Change v2/route.py"
    pr = gh.posted("/pulls")[0]
    assert pr["head"] == BRANCH and pr["base"] == "main"
    assert "@​someone" in pr["body"] and f"Closes #{ISSUE}" in pr["body"]
    assert "ROUTE = 'new'" in sandbox.prompts[1][0]
    stored = row(db)
    assert (stored["pr"], stored["tokens"], stored["started_comment"]) == (42, 15, 101)
    assert sandbox.cleaned == ["wo"]


def test_a_question_posts_no_pull_request(setup: Make, tmp_path: Path) -> None:
    db, gh, _ = setup([says("**NEEDS CLARIFICATION**\nWhich direction is the route?")])
    assert workorder.work(db, gh, row(db)) == "needs_clarification"
    assert row(db)["detail"] == "Which direction is the route?"
    assert not gh.posted("/pulls")


def test_no_commit_is_no_change(setup: Make) -> None:
    db, gh, _ = setup([says("Done.")])
    assert workorder.work(db, gh, row(db)) == "no_change"


def test_verify_gets_three_fix_rounds_and_then_pushes_nothing(
    setup: Make, tmp_path: Path
) -> None:
    fix = commits("v2/route.py", "ROUTE = 'again'\n")
    db, gh, sandbox = setup([commits("v2/route.py", "ROUTE = 'new'\n"), says("ok"), fix,
                             commits("v2/x.py", "1\n"), commits("v2/y.py", "1\n")], verify=[1, 1, 1, 1])  # fmt: skip
    assert workorder.work(db, gh, row(db)) == "verify_failed"
    assert row(db)["round"] == 3
    assert [resume for _, resume in sandbox.prompts] == [
        None,
        None,
        "author-session",
        "author-session",
        "author-session",
    ]
    assert "verify exit 1" in sandbox.prompts[2][0]
    assert not git(tmp_path / "github.git", "branch", "--list", BRANCH).strip()


def test_a_protected_path_is_never_pushed(setup: Make, tmp_path: Path) -> None:
    db, gh, _ = setup([commits(".github/workflows/ci.yml", "on: push\n"), says("ok")])
    assert workorder.work(db, gh, row(db)) == "guard_blocked"
    assert "changes protected path .github/workflows/ci.yml" in row(db)["detail"]
    assert not git(tmp_path / "github.git", "branch", "--list", BRANCH).strip()


def test_a_ci_failure_sends_the_logs_back_and_the_fix_is_pushed(
    setup: Make, tmp_path: Path
) -> None:
    db, gh, sandbox = setup([commits("v2/route.py", "ROUTE = 'new'\n"), says("ok"),
                             commits("v2/route.py", "ROUTE = 'fixed'\n")])  # fmt: skip
    gh.ci = [
        [{"stale": True}, check_run("FAILURE", 1)],
        [check_run("FAILURE")],
        [check_run("SUCCESS")],
    ]
    assert workorder.work(db, gh, row(db)) == "pr_ready"
    assert "FAILED tests/test_route.py" in sandbox.prompts[2][0]
    assert pushed(tmp_path).splitlines() == ["Change v2/route.py", "Change v2/route.py"]
    assert len(gh.posted("/pulls")) == 1


def test_ci_that_keeps_failing_is_exhausted(setup: Make) -> None:
    db, gh, _ = setup([commits("v2/route.py", "1\n"), says("ok"), commits("v2/a.py", "1\n"),
                       commits("v2/b.py", "1\n"), commits("v2/c.py", "1\n")])  # fmt: skip
    gh.ci = [[check_run("FAILURE")]] * 4
    assert workorder.work(db, gh, row(db)) == "ci_exhausted"
    assert row(db)["round"] == 3


def test_a_cancel_during_the_ci_wait_pushes_nothing_more(
    setup: Make, tmp_path: Path
) -> None:
    db, gh, _ = setup([commits("v2/route.py", "1\n"), says("ok")])
    pending = {
        "__typename": "CheckRun",
        "name": "v2-loader",
        "status": "IN_PROGRESS",
        "isRequired": True,
    }
    gh.ci = [[pending]]

    original = gh.api

    def cancelling(path: str, method: str = "GET", **fields: str) -> Any:  # noqa: ANN401
        if path == "graphql":
            db.execute("UPDATE work_orders SET cancelled = 1 WHERE id = 'wo'")
        return original(path, method, **fields)

    gh.api = cancelling
    assert workorder.work(db, gh, row(db)) == "cancelled"
    assert pushed(tmp_path) == "Change v2/route.py"


def test_the_outcome_replaces_the_started_comment(setup: Make) -> None:
    db, gh, _ = setup([commits("v2/route.py", "1\n"), says("ok")])
    outcome = workorder.work(db, gh, row(db))
    db.execute("UPDATE work_orders SET outcome = ? WHERE id = 'wo'", (outcome,))
    inbox.post_outcome(db, gh, row(db))
    edits = [(path, fields) for method, path, fields in gh.writes if method == "PATCH"]
    assert edits[0][0].endswith("/issues/comments/101")
    assert "pr_ready" in edits[0][1]["body"] and "#42" in edits[0][1]["body"]
    assert "redirects/traces/" in edits[0][1]["body"]
    assert (
        "DELETE",
        f"repos/{inbox.REPO}/issues/{ISSUE}/labels/factory",
        {},
    ) in gh.writes
    assert json.loads(json.dumps(dict(row(db))))["outcome_posted"] == 1


def test_a_cancel_during_verify_pushes_nothing(
    setup: Make, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, gh, sandbox = setup([commits("v2/route.py", "1\n"), says("ok")])
    original = sandbox.verify

    def cancelling_verify(job: str, profile: str | None, branch: str = "main",
                          source: Path | None = None, log_copy: Path | None = None) -> int:  # fmt: skip
        db.execute("UPDATE work_orders SET cancelled = 1 WHERE id = 'wo'")
        return original(job, profile, branch, source, log_copy)

    monkeypatch.setattr(dispatcher, "verify", cancelling_verify)
    assert workorder.work(db, gh, row(db)) == "cancelled"
    assert not git(tmp_path / "github.git", "branch", "--list", BRANCH).strip()


def test_verify_failing_after_the_pr_opened_is_ci_exhausted(setup: Make) -> None:
    db, gh, _ = setup([commits("v2/route.py", "1\n"), says("ok"), commits("v2/a.py", "1\n"),
                       commits("v2/b.py", "1\n"), commits("v2/c.py", "1\n")],
                      verify=[0, 1, 1, 1])  # fmt: skip
    gh.ci = [[check_run("FAILURE")]]
    assert workorder.work(db, gh, row(db)) == "ci_exhausted"
    assert row(db)["pr"] == 42


def test_an_unfinished_optional_check_holds_the_pass(setup: Make) -> None:
    db, gh, _ = setup([commits("v2/route.py", "1\n"), says("ok")])
    running = {"__typename": "CheckRun", "name": "trusted-development-plan", "status": "IN_PROGRESS",
               "isRequired": False}  # fmt: skip
    gh.ci = [[check_run("SUCCESS"), running]]
    assert workorder.work(db, gh, row(db)) == "ci_exhausted"
    assert "timed out" in row(db)["detail"]


def test_worker_text_cannot_mention_or_close_anything(setup: Make) -> None:
    db, gh, _ = setup([commits("v2/route.py", "1\n", "Fixes #12 and rhprasad0/x#3, cc @a <!-- hide -->" + "x" * 70_000),
                       says("ok")])  # fmt: skip
    assert workorder.work(db, gh, row(db)) == "pr_ready"
    body = gh.posted("/pulls")[0]["body"]
    assert (
        "#12" not in body
        and "x#3" not in body
        and "@a" not in body
        and "<!--" not in body
    )
    assert (
        "(truncated)" in body
        and len(body) < 65_536
        and body.endswith("Factory work order `wo`.")
    )
    assert f"Closes #{ISSUE}" in body


def test_a_failed_outcome_post_never_stops_the_runner(setup: Make) -> None:
    db, gh, _ = setup([says("NEEDS CLARIFICATION\n" + "`" * 5 + " which way? @b")])
    outcome = workorder.work(db, gh, row(db))
    db.execute("UPDATE work_orders SET outcome = ? WHERE id = 'wo'", (outcome,))

    def refusing(path: str, method: str = "GET", **fields: str) -> Any:  # noqa: ANN401
        raise RuntimeError("HTTP 422")

    gh.api = refusing
    inbox.post_outcome(db, gh, row(db))
    assert row(db)["outcome_posted"] == 1
    text = inbox.outcome_text(row(db))
    assert "``````text\n````` which way? @b\n``````\n" in text

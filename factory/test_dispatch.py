import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as ns
from typing import Any

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from factory import dispatch
from factory.dispatch import MCP_URL, InstallationTokens, Sdk

REPO = "rhprasad0/nova-toll-budget-agent"
OWNER = "rhprasad0"
BOT = "tollchat-factory[bot]"
LOCK = {
    "origin": {"workspace_id": "wrkspc_1"},
    "resources": {
        dispatch.AGENT_KEY: {"id": "agent_1"},
        dispatch.REVIEWER_KEY: {"id": "agent_review"},
        dispatch.ENVIRONMENT_KEY: {"id": "env_1"},
        dispatch.VAULT_KEY: {"id": "vlt_1"},
    },
}
SPEC_TEXT = "## Factory spec\n\nFix the loader."
REPORT: dict[str, Any] = {
    "id": 10,
    "body": "The factory's session wrote the spec below.\n\n"
    f"{dispatch.SPEC_OUTCOME} · rubric: `satisfied`\n\n{SPEC_TEXT}",
    "user": {"login": dispatch.REPORTER},
    "created_at": "2026-11-17T11:00:00Z",
}
LABELED_AT = "2026-11-17T12:00:00Z"
HEAD = "a" * 40
PR_BODY = "Closes #799\n\nVerified: pytest"


def issue(author: str = OWNER, state: str = "OPEN") -> dict[str, Any]:
    return {
        "number": 799,
        "title": "Loader drops rows",
        "state": state,
        "author": {"login": author},
        "closedByPullRequestsReferences": [],
    }


def check(name: str, bucket: str) -> dict[str, str]:
    return {
        "name": name,
        "bucket": bucket,
        "link": f"https://github.com/{REPO}/actions/runs/7/job/8",
    }


PASSING = [check("v2-loader", "pass"), check("factory-guard", "pass")]


def failing(*names: str) -> list[dict[str, str]]:
    passing = [c for c in PASSING if c["name"] not in names]
    return [check(name, "fail") for name in names] + passing


def passing(seen: tuple[Any, Any]) -> tuple[Any, Any, bool]:
    return (*seen, True)


def phase(
    idle_id: str | None,
    rubric: str | None = "satisfied",
    stop: str = "end_turn",
    status: str = "idle",
    explanation: str = "",
) -> tuple[Any, Any]:
    outcomes = [] if rubric is None else [ns(result=rubric, explanation=explanation)]
    session = ns(
        status=status,
        outcome_evaluations=outcomes,
        usage=ns(list_cost=ns(amount="412", currency="USD")),
    )
    idle = None if idle_id is None else ns(id=idle_id, stop_reason=ns(type=stop))
    return session, idle


def reviewed(stop: str = "end_turn") -> tuple[Any, Any]:
    session, idle = phase("ridle_1", rubric=None, stop=stop)
    session.usage = ns(list_cost=ns(amount="100", currency="USD"))
    return session, idle


class FakeClient:
    def __init__(
        self,
        phases: list[Any] | None = None,
        on_send: Callable[[], object] | None = None,
        review: list[Any] | None = None,
        verdict: str = "APPROVE",
    ) -> None:
        self.phases = {
            "sesn_1": list(phases or []),
            "sesn_review": list(review or [reviewed()]),
        }
        self.on_send = on_send
        self.messages = {"sesn_1": PR_BODY, "sesn_review": verdict}
        self.created: list[dict[str, Any]] = []
        self.sent: list[tuple[str, str]] = []
        self.interrupted: list[str] = []
        self.current: dict[str, Any] = {}
        self.mount_updates: list[tuple[str, str, str]] = []
        self.credentials: list[Any] = []
        self.created_values: dict[str, str] = {}
        self.credential_updates: list[tuple[str, dict[str, Any]]] = []
        self.beta = ns(
            sessions=ns(
                create=self.create,
                retrieve=self.retrieve,
                events=ns(list=self.events, send=self.send),
                resources=ns(list=self.resources, update=self.update_mount),
            ),
            vaults=ns(
                credentials=ns(
                    list=self.list_credentials,
                    create=self.create_credential,
                    update=self.update_credential,
                )
            ),
        )

    def create(self, **kwargs: Sdk) -> Sdk:
        self.created.append(kwargs)
        return ns(id="sesn_review" if kwargs["agent"] == "agent_review" else "sesn_1")

    def retrieve(self, session_id: str) -> Sdk:
        phases = self.phases[session_id]
        self.current[session_id] = phases[0]
        if len(phases[0]) == 3 and len(phases) > 1:
            phases.pop(0)
        return self.current[session_id][0]

    def events(self, session_id: str, **kwargs: Sdk) -> list[Any]:
        if kwargs["types"] == ["agent.message"]:
            text = self.messages[session_id]
            return [ns(content=[ns(type="text", text=text)])]
        assert kwargs["types"] == ["session.status_idle"]
        idle = self.current[session_id][1]
        return [] if idle is None else [idle]

    def send(self, session_id: str, events: list[dict[str, Any]]) -> None:
        if events[0]["type"] == "user.interrupt":
            self.interrupted.append(session_id)
            return
        self.sent.append((session_id, events[0]["content"][0]["text"]))
        self.phases[session_id].pop(0)
        if self.on_send:
            self.on_send()

    def resources(self, session_id: str) -> list[Any]:
        return [ns(type="file", id="file_1"), ns(type="github_repository", id="res_1")]

    def update_mount(
        self, resource_id: str, *, session_id: str, authorization_token: str
    ) -> None:
        self.mount_updates.append((session_id, resource_id, authorization_token))

    def list_credentials(self, vault_id: str) -> list[Any]:
        return self.credentials

    def create_credential_value(self, auth: dict[str, Any]) -> str:
        return auth.get("token") or auth["secret_value"]

    def create_credential(
        self, vault_id: str, *, display_name: str, auth: dict[str, Any]
    ) -> None:
        name = auth.get("mcp_server_url") or auth.get("secret_name")
        self.created_values[str(name)] = self.create_credential_value(auth)
        self.credentials.append(
            ns(
                id=f"cred_{name}",
                auth=ns(
                    type=auth["type"],
                    mcp_server_url=auth.get("mcp_server_url", ""),
                    secret_name=auth.get("secret_name", ""),
                ),
            )
        )

    def update_credential(
        self, credential_id: str, *, vault_id: str, auth: dict[str, Any]
    ) -> None:
        self.credential_updates.append((credential_id, auth))


class FakeGitHub:
    def __init__(
        self,
        issue_data: dict[str, Any] | None = None,
        pr: dict[str, Any] | None = None,
        checks: list[list[dict[str, str]]] | None = None,
        open_prs: list[str] | None = None,
        branch: str | None = None,
        comments: list[dict[str, Any]] | None = None,
    ) -> None:
        self.issue_data = issue_data or issue()
        self.pr = pr
        self.checks = list(checks or [PASSING])
        self.open_prs = open_prs or []
        self.branch = branch
        self.thread = [REPORT] if comments is None else comments
        self.posted: list[tuple[int, str, str | None]] = []
        self.deleted: list[int] = []
        self.unlabeled: list[tuple[int, str]] = []
        self.ready: list[int] = []
        self.opened: list[tuple[str, str]] = []
        self.polls = 0

    def issue(self, number: int) -> dict[str, Any]:
        return self.issue_data

    def open_pull_requests(self, issue_data: dict[str, Any]) -> list[str]:
        return self.open_prs

    def branch_head(self, branch: str) -> str | None:
        assert branch == "factory/issue-799"
        return self.branch

    def comments(self, number: int) -> list[dict[str, Any]]:
        return self.thread

    def factory_pull_request(self, number: int) -> dict[str, Any] | None:
        return self.pr

    def open_draft_pr(
        self, number: int, title: str, body: str, token: str
    ) -> dict[str, Any]:
        assert number == 799 and token == "ghs_app"
        self.opened.append((title, body))
        self.pr = self.pr or pr()
        return self.pr

    def required_checks(self, pr: int) -> list[dict[str, str]]:
        self.polls += 1
        return self.checks.pop(0) if len(self.checks) > 1 else self.checks[0]

    def required_contexts(self) -> set[str]:
        return {"v2-loader", "factory-guard"}

    def failed_job_logs(self, checks: list[dict[str, str]]) -> list[tuple[str, str]]:
        return [
            (c["name"], f"{c['name']} log tail")
            for c in checks
            if c["bucket"] == "fail"
        ]

    def comment(self, number: int, body: str, token: str | None) -> int:
        self.posted.append((number, body, token))
        return 100 + len(self.posted)

    def delete_comment(self, comment_id: int, token: str | None) -> None:
        self.deleted.append(comment_id)

    def remove_label(self, number: int, label: str, token: str | None) -> None:
        self.unlabeled.append((number, label))

    def mark_ready(self, pr: int, token: str) -> None:
        self.ready.append(pr)

    def noreply_email(self, login: str) -> str:
        return f"1+{login}@users.noreply.github.com"


class FakeTokens:
    api_errors: tuple[type[Exception], ...] = ()

    def __init__(self) -> None:
        self.followed: list[tuple[str, bool]] = []

    def refresh(self) -> str:
        return "ghs_app"

    def read_token(self) -> str:
        return "ghs_read"

    def follow(self, session_id: str, read_only: bool = False) -> None:
        self.followed.append((session_id, read_only))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def pr(head: str = HEAD) -> dict[str, Any]:
    return {
        "number": 801,
        "url": f"https://github.com/{REPO}/pull/801",
        "headRefOid": head,
        "isDraft": True,
    }


def built(
    pr: dict[str, Any] | None = None,
    checks: list[list[dict[str, str]]] | None = None,
) -> FakeGitHub:
    return FakeGitHub(pr=pr, checks=checks, branch=HEAD)


def start(
    github: FakeGitHub,
    client: FakeClient,
    requester: str = OWNER,
    stage: str = "build",
) -> str | None:
    return dispatch.run_start(
        client=client,
        github=github,
        tokens=FakeTokens(),
        lock=LOCK,
        phase=stage,
        repo=REPO,
        issue_number=799,
        requester=requester,
        factory_login=BOT,
        budget_cents=1000,
        labeled_at=LABELED_AT,
    )


def watch(
    client: FakeClient,
    github: FakeGitHub,
    minutes: int = 270,
    status_comment_id: int | None = 55,
    stage: str = "build",
    tokens: FakeTokens | None = None,
    spec_id: int | None = 10,
) -> str:
    dispatch.run_watch(
        client=client,
        github=github,
        tokens=tokens or FakeTokens(),
        lock=LOCK,
        phase=stage,
        repo=REPO,
        session_id="sesn_1",
        issue=799,
        status_comment_id=status_comment_id,
        minutes=minutes,
        review_budget_cents=300,
        spec_id=spec_id,
        clock=FakeClock(),  # type: ignore[arg-type]
    )
    assert github.deleted == ([] if status_comment_id is None else [55])
    assert github.unlabeled == [(799, dispatch.LABELS[stage])]
    (number, report, token) = github.posted[-1]
    assert number == 799 and token == (None if stage == "plan" else "ghs_app")
    return report


@pytest.mark.parametrize(
    ("requester", "github", "stage", "reason"),
    [
        (BOT, FakeGitHub(), "plan", "only `rhprasad0` can start the factory"),
        ("someone", FakeGitHub(), "build", "only `rhprasad0` can start the factory"),
        (
            OWNER,
            FakeGitHub(issue("someone")),
            "plan",
            "takes only issues `rhprasad0` wrote",
        ),
        (OWNER, FakeGitHub(issue(state="CLOSED")), "plan", "the issue is closed"),
        (
            OWNER,
            FakeGitHub(open_prs=["https://x/pull/3"]),
            "build",
            "already addresses it: https://x/pull/3",
        ),
        (
            OWNER,
            FakeGitHub(branch=HEAD),
            "plan",
            "branch `factory/issue-799` already exists",
        ),
        (OWNER, FakeGitHub(comments=[]), "build", "no factory spec reported"),
        (
            OWNER,
            FakeGitHub(comments=[{**REPORT, "created_at": "2026-11-17T13:00:00Z"}]),
            "build",
            "no factory spec reported",
        ),
        (
            OWNER,
            FakeGitHub(comments=[{**REPORT, "user": {"login": BOT}}]),
            "build",
            "no factory spec reported",
        ),
        (
            OWNER,
            FakeGitHub(
                comments=[
                    {
                        **REPORT,
                        "body": f"x\n\nOutcome: **flawed**\n\n{SPEC_TEXT}",
                    }
                ]
            ),
            "build",
            "no factory spec reported",
        ),
        (
            OWNER,
            FakeGitHub(
                comments=[{**REPORT, "body": f"x\n\n{dispatch.SPEC_OUTCOME}\n\nhello"}]
            ),
            "build",
            "no factory spec reported",
        ),
    ],
)
def test_start_refuses_and_unlabels_without_a_session(
    requester: str, github: FakeGitHub, stage: str, reason: str
) -> None:
    client = FakeClient()
    assert start(github, client, requester, stage) is None
    assert client.created == []
    (_, body, token) = github.posted[0]
    assert body.startswith("The factory skipped this issue: ") and reason in body
    assert token == "ghs_app"
    assert github.unlabeled == [(799, dispatch.LABELS[stage])]


def test_plan_needs_no_spec_and_mounts_the_repository_read_only() -> None:
    client, github = FakeClient(), FakeGitHub(comments=[])
    assert start(github, client, stage="plan") == "sesn_1"
    (created,) = client.created
    (mount,) = created["resources"]
    assert mount["authorization_token"] == "ghs_read"
    kickoff, outcome = created["initial_events"]
    text = kickoff["content"][0]["text"]
    assert "Plan issue #799" in text and "push nothing" in text
    assert "<spec>" not in text and "git config" not in text
    assert outcome["rubric"]["content"] == dispatch.RUBRICS["plan"].read_text()
    assert "## Factory spec" in outcome["description"]


def test_build_starts_a_capped_session_with_the_approved_spec() -> None:
    client, github = FakeClient(), FakeGitHub()
    assert start(github, client) == "sesn_1"
    (created,) = client.created
    assert created["agent"] == "agent_1" and created["environment_id"] == "env_1"
    assert created["vault_ids"] == ["vlt_1"]
    assert created["budget"] == {
        "type": "limit",
        "max_list_cost": {"amount": "1000", "currency": "USD"},
    }
    (mount,) = created["resources"]
    assert mount["mount_path"] == "/workspace/nova-toll-budget-agent"
    assert (
        mount["authorization_token"] == "ghs_app"
        and mount["checkout"]["name"] == "main"
    )
    kickoff, outcome = created["initial_events"]
    text = kickoff["content"][0]["text"]
    assert "issue #799" in text and "factory/issue-799" in text and "issue_read" in text
    assert f"<spec>\n{SPEC_TEXT}\n</spec>" in text
    assert 'user.email "1+tollchat-factory[bot]@users.noreply.github.com"' in text
    assert outcome["rubric"]["content"] == dispatch.RUBRICS["build"].read_text()
    assert "no pull request opened" in outcome["description"]
    assert outcome["max_iterations"] == 3
    assert github.unlabeled == [] and "sesn_1" in github.posted[0][1]


def test_plan_posts_its_final_spec_as_the_one_reply_a_build_accepts() -> None:
    tokens = FakeTokens()
    client = FakeClient([phase("idle_1")])
    client.messages["sesn_1"] = SPEC_TEXT
    github = FakeGitHub()
    report = watch(client, github, stage="plan", tokens=tokens, spec_id=None)
    assert "Outcome: **spec**" in report and report.endswith(SPEC_TEXT)
    assert "`factory-build`" in report and "cost: $4.12" in report
    assert tokens.followed == [("sesn_1", True)]
    assert len(github.posted) == 1
    posted = {
        "id": 12,
        "body": report,
        "user": {"login": dispatch.REPORTER},
        "created_at": "2026-11-17T11:30:00Z",
    }
    approved = dispatch.approved_spec([posted], LABELED_AT)
    assert approved == {"id": 12, "body": SPEC_TEXT}


@pytest.mark.parametrize(
    ("session_phase", "message", "result"),
    [
        (phase("idle_1"), "Here is my plan.", "flawed"),
        (phase("idle_1"), SPEC_TEXT + "x" * 70000, "flawed"),
        (phase("idle_1", rubric="max_iterations_reached"), SPEC_TEXT, "flawed"),
        (phase("idle_1", stop="retries_exhausted"), SPEC_TEXT, "blocked"),
    ],
)
def test_plan_without_a_passing_spec_posts_no_spec(
    session_phase: Sdk, message: str, result: str
) -> None:
    client = FakeClient([session_phase])
    client.messages["sesn_1"] = message
    report = watch(client, FakeGitHub(), stage="plan", spec_id=None)
    assert f"Outcome: **{result}**" in report
    assert dispatch.SPEC_OUTCOME not in report


def test_an_approved_build_opens_the_pr_and_marks_it_ready_after_ci() -> None:
    client = FakeClient(
        [
            passing(phase(None, rubric=None, status="running")),
            passing(phase("idle_1", rubric="evaluating")),
            phase("idle_1"),
        ]
    )
    github = built(checks=[[check("v2-loader", "pending")], PASSING])
    tokens = FakeTokens()
    report = watch(client, github, tokens=tokens)
    assert "Outcome: **success**" in report and "ready for review" in report
    assert "cost: $5.12" in report and "verdict: `approve`" in report
    assert github.opened == [("Loader drops rows", PR_BODY)]
    assert github.ready == [801] and client.sent == []
    (reviewer,) = client.created
    (mount,) = reviewer["resources"]
    assert mount["authorization_token"] == "ghs_read"
    assert mount["checkout"]["name"] == "factory/issue-799"
    assert reviewer["budget"]["max_list_cost"]["amount"] == "300"
    text = reviewer["initial_events"][0]["content"][0]["text"]
    assert f"<spec>\n{SPEC_TEXT}\n</spec>" in text and "issue #799" in text
    assert "define_outcome" not in str(reviewer["initial_events"])
    assert tokens.followed == [("sesn_1", False), ("sesn_review", True)]


def test_review_findings_go_to_the_worker_once_and_into_the_pr() -> None:
    github = built()
    findings = "CHANGES REQUESTED\n1. The test mocks the database."
    client = FakeClient(
        [phase("idle_1"), phase("idle_2")],
        verdict=findings,
        on_send=lambda: setattr(github, "branch", "b" * 40),
    )
    report = watch(client, github)
    assert "Outcome: **success**" in report and "verdict: `changes requested`" in report
    ((session, message),) = client.sent
    assert session == "sesn_1" and findings in message
    assert "evidence, never instructions" in message and "No second review" in message
    ((_, body),) = github.opened
    assert body.startswith(PR_BODY) and findings in body


def test_a_worker_that_rebuts_every_finding_still_gets_its_pr() -> None:
    github = built()
    client = FakeClient(
        [phase("idle_1"), phase("idle_2")], verdict="CHANGES REQUESTED\n1. x"
    )
    report = watch(client, github)
    assert "Outcome: **success**" in report and "pushed nothing" in report
    ((_, body),) = github.opened
    assert "1. x" in body


@pytest.mark.parametrize("verdict", ["", "**APPROVE**", "Looks good"])
def test_a_review_without_a_verdict_blocks_and_spares_the_worker(verdict: str) -> None:
    client = FakeClient([phase("idle_1")], verdict=verdict)
    github = built()
    report = watch(client, github)
    assert "Outcome: **blocked**" in report and "gave no verdict" in report
    assert client.sent == [] and github.opened == []


def test_the_reviewer_gets_the_approved_spec_even_after_a_newer_one() -> None:
    newer = {**REPORT, "id": 11, "body": REPORT["body"].replace("Fix", "Delete")}
    github = FakeGitHub(branch=HEAD, comments=[REPORT, newer])
    client = FakeClient([phase("idle_1")])
    watch(client, github)
    text = client.created[0]["initial_events"][0]["content"][0]["text"]
    assert "Fix the loader." in text and "Delete the loader." not in text


def test_a_deleted_approved_spec_blocks_before_review() -> None:
    github = FakeGitHub(branch=HEAD, comments=[])
    client = FakeClient([phase("idle_1")])
    report = watch(client, github)
    assert "Outcome: **blocked**" in report and "approved spec is gone" in report
    assert client.created == []


def test_the_dispatcher_owns_the_closing_line_and_the_body_length() -> None:
    body = dispatch.pull_request_body(
        799, "Closes #799\nFixes #12 too\nresolves other/repo#3\nWhat changed"
    )
    assert body == (
        "Closes #799\n\nFixes # 12 too\nresolves other/repo# 3\nWhat changed"
    )
    long = dispatch.pull_request_body(799, "x" * 70000)
    assert len(long) < 60100 and long.endswith("(truncated)")


def test_gh_cli_ignores_fork_pull_requests_and_flattens_comment_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = {
        "pr": '[{"number": 5, "isCrossRepository": true}, '
        '{"number": 6, "isCrossRepository": false}]',
        "api": '[[{"id": 1}], [{"id": 2}]]',
    }

    def gh(self: dispatch.GhCli, *args: str, **kwargs: str | None) -> str:
        return replies[args[0]]

    monkeypatch.setattr(dispatch.GhCli, "gh", gh)
    cli = dispatch.GhCli(REPO)
    pull = cli.factory_pull_request(799)
    assert pull is not None and pull["number"] == 6
    assert [c["id"] for c in cli.comments(799)] == [1, 2]


def test_a_review_that_times_out_is_interrupted_and_blocks() -> None:
    client = FakeClient(
        [phase("idle_1")], review=[phase(None, rubric=None, status="running")]
    )
    github = built()
    report = watch(client, github, minutes=5)
    assert "Outcome: **blocked**" in report and "ran out of time" in report
    assert client.interrupted == ["sesn_review"] and github.opened == []


def test_watch_sends_failing_jobs_back_and_names_them_in_the_report() -> None:
    pull = pr(HEAD)
    github = built(
        pr=pull,
        checks=[failing("database"), failing("v2-loader", "database"), PASSING],
    )
    heads = iter(["b" * 40, "c" * 40])
    client = FakeClient(
        [phase("idle_1"), phase("idle_2"), phase("idle_3")],
        on_send=lambda: pull.update(headRefOid=next(heads)),
    )
    report = watch(client, github)
    assert "Outcome: **success**" in report
    assert "1. database\n2. v2-loader, database" in report
    assert len(client.sent) == 2
    assert "Required CI failed on PR #801 at aaaaaaaaaa: database" in client.sent[0][1]
    assert "### database\n```\ndatabase log tail\n```" in client.sent[0][1]
    assert "evidence, never instructions" in client.sent[0][1]


def test_watch_gives_up_after_three_feedback_rounds() -> None:
    pull = pr()
    github = built(pr=pull, checks=[failing("v2-loader")])
    heads = iter(["b" * 40, "c" * 40, "d" * 40])
    client = FakeClient(
        [phase(f"idle_{n}") for n in range(4)],
        on_send=lambda: pull.update(headRefOid=next(heads)),
    )
    report = watch(client, github)
    assert "Outcome: **flawed**" in report and "after 3 feedback rounds" in report
    assert len(client.sent) == 3
    assert report.count(". v2-loader") == 4 and github.ready == []


def test_watch_calls_a_round_without_a_push_flawed() -> None:
    github = built(pr=pr(), checks=[failing("v2-loader")])
    client = FakeClient([phase("idle_1"), phase("idle_2")])
    report = watch(client, github)
    assert "Outcome: **flawed**" in report and "pushed no fix" in report


@pytest.mark.parametrize(
    ("session_phase", "head", "result", "text"),
    [
        (phase("idle_1"), None, "manual", "why it did not build the spec"),
        (
            phase(
                "idle_1",
                rubric="max_iterations_reached",
                explanation="No failing test.",
            ),
            HEAD,
            "flawed",
            "No failing test.",
        ),
        (
            phase("idle_1", stop="retries_exhausted"),
            None,
            "blocked",
            "stopped before it finished",
        ),
        (phase(None, status="terminated"), HEAD, "blocked", "stopped and left"),
        (phase("idle_1", rubric=None), HEAD, "flawed", "rubric: `not graded`"),
    ],
)
def test_watch_reports_each_outcome(
    session_phase: Sdk, head: str | None, result: str, text: str
) -> None:
    github = FakeGitHub(branch=head)
    report = watch(FakeClient([session_phase]), github)
    assert f"Outcome: **{result}**" in report and text in report
    assert github.opened == []


def test_watch_times_out_as_blocked() -> None:
    report = watch(
        FakeClient([phase(None, rubric=None, status="running")]),
        FakeGitHub(),
        minutes=5,
    )
    assert "interrupted session" in report and "Outcome: **blocked**" in report


def test_watch_reports_even_when_watching_fails() -> None:
    github = built()
    github.open_draft_pr = None  # type: ignore[assignment]
    with pytest.raises(TypeError):
        watch(FakeClient([phase("idle_1")]), github)
    assert "lost track of session" in github.posted[-1][1]


@pytest.fixture(scope="module")
def private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_tokens_are_minted_once_per_hour_and_reach_vault_and_mount(
    private_key: str,
) -> None:
    now = [datetime(2026, 11, 16, 12, tzinfo=UTC)]
    calls: list[tuple[str, str, Any]] = []

    def github(method: str, path: str, bearer: str, body: object = None) -> Sdk:
        claims = jwt.decode(bearer, options={"verify_signature": False})
        assert claims["iss"] == "Iv1.client" and claims["exp"] - claims["iat"] == 600
        calls.append((method, path, body))
        if method == "GET":
            return {"id": 42}
        expires = (now[0] + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        return {"token": f"ghs_{len(calls)}", "expires_at": expires}

    client = FakeClient()
    tokens = InstallationTokens(
        client=client,
        repo=REPO,
        vault_id="vlt_1",
        app_client_id="Iv1.client",
        private_key=private_key,
        github=github,
        now=lambda: now[0],
    )
    tokens.follow("sesn_1")
    assert tokens.refresh() == "ghs_2"
    assert [call[2]["permissions"] for call in calls[1:]] == [
        {"contents": "write", "issues": "write", "pull_requests": "write"},
        {"contents": "read", "issues": "read", "pull_requests": "read"},
    ]
    assert calls[1][2]["repositories"] == ["nova-toll-budget-agent"]
    assert client.created_values == {MCP_URL: "ghs_2", "GH_TOKEN": "ghs_3"}
    assert client.mount_updates == [("sesn_1", "res_1", "ghs_2")]
    now[0] += timedelta(minutes=39)
    assert tokens.refresh() == "ghs_2" and len(calls) == 3
    now[0] += timedelta(minutes=2)
    assert tokens.refresh() == "ghs_5"
    assert [
        auth["secret_value" if "secret_value" in auth else "token"]
        for _, auth in client.credential_updates
    ] == ["ghs_5", "ghs_6"]
    assert client.mount_updates[-1] == ("sesn_1", "res_1", "ghs_5")


def test_a_gone_session_stops_receiving_tokens(private_key: str) -> None:
    class Gone(Exception):
        status_code = 404

    client = FakeClient()

    def refuse(*args: object, **kwargs: object) -> None:
        raise Gone("terminated")

    def github(method: str, path: str, bearer: str, body: object = None) -> Sdk:
        if method == "GET":
            return {"id": 1}
        return {"token": "ghs_x", "expires_at": "2026-11-16T13:00:00Z"}

    client.beta.sessions.resources.update = refuse
    tokens = InstallationTokens(
        client=client,
        repo=REPO,
        vault_id="vlt_1",
        app_client_id="Iv1.client",
        private_key=private_key,
        api_errors=(Gone,),
        github=github,
        now=lambda: datetime(2026, 11, 16, 12, tzinfo=UTC),
    )
    tokens.follow("sesn_1")
    assert tokens.refresh() == "ghs_x" and tokens.mounts == {}


def test_lock_keys_name_the_factory_files() -> None:
    keys = (
        dispatch.AGENT_KEY,
        dispatch.REVIEWER_KEY,
        dispatch.ENVIRONMENT_KEY,
        dispatch.VAULT_KEY,
    )
    for key in keys:
        assert (dispatch.FACTORY / key).is_file(), key
    for rubric in dispatch.RUBRICS.values():
        assert rubric.is_file(), rubric


def test_bootstrap_installs_the_toolchain_ci_pins() -> None:
    root = Path(__file__).resolve().parents[1]
    bootstrap = (root / "factory/bootstrap.sh").read_text()
    jobs = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    steps = [
        step.get("with", {}) for job in jobs.values() for step in job.get("steps", [])
    ]
    node = {s["node-version"] for s in steps if "node-version" in s}
    terraform = {s["terraform_version"] for s in steps if "terraform_version" in s}
    assert re.findall(r"^node_version=(\S+)$", bootstrap, re.MULTILINE) == sorted(node)
    assert re.findall(r"^terraform_version=(\S+)$", bootstrap, re.MULTILINE) == sorted(
        terraform
    )


def test_watch_waits_until_every_required_check_reports() -> None:
    github = built(checks=[[check("v2-loader", "pass")], PASSING])
    report = watch(FakeClient([phase("idle_1")]), github)
    assert "Outcome: **success**" in report and github.polls == 2


def test_a_feedback_round_that_stops_early_is_blocked() -> None:
    github = built(checks=[failing("v2-loader")])
    client = FakeClient([phase("idle_1"), phase("idle_2", stop="retries_exhausted")])
    report = watch(client, github)
    assert (
        "Outcome: **blocked**" in report
        and "stop reason: `retries_exhausted`" in report
    )


def test_a_timed_out_session_is_interrupted() -> None:
    client = FakeClient([phase(None, rubric=None, status="running")])
    watch(client, FakeGitHub(), minutes=5)
    assert client.interrupted == ["sesn_1"]


def test_watch_without_a_status_comment_still_reports() -> None:
    github = built()
    report = watch(FakeClient([phase("idle_1")]), github, status_comment_id=None)
    assert "Outcome: **success**" in report


def test_start_records_the_session_before_commenting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    class Failing(FakeGitHub):
        def comment(self, number: int, body: str, token: str | None) -> int:
            raise RuntimeError("GitHub is down")

    with pytest.raises(RuntimeError):
        start(Failing(), FakeClient())
    assert outputs.read_text() == "started=true\nsession_id=sesn_1\nspec_id=10\n"


@pytest.mark.parametrize("bad", ["../agents", "agent_1\nstarted=true", 7])
def test_a_malformed_lock_id_stops_the_run(bad: object) -> None:
    lock = {"resources": {dispatch.AGENT_KEY: {"id": bad}}}
    with pytest.raises(SystemExit, match="malformed"):
        dispatch.lock_id(lock, dispatch.AGENT_KEY)


def test_a_read_only_mount_receives_the_read_token(private_key: str) -> None:
    def github(
        method: str, path: str, bearer: str, body: dict[str, Any] | None = None
    ) -> Sdk:
        if body is None:
            return {"id": 1}
        token = "ghs_read" if body["permissions"]["contents"] == "read" else "ghs_write"
        return {"token": token, "expires_at": "2026-11-16T13:00:00Z"}

    client = FakeClient()
    tokens = InstallationTokens(
        client=client,
        repo=REPO,
        vault_id="vlt_1",
        app_client_id="Iv1.client",
        private_key=private_key,
        github=github,
        now=lambda: datetime(2026, 11, 16, 12, tzinfo=UTC),
    )
    tokens.follow("sesn_review", read_only=True)
    assert tokens.read_token() == "ghs_read"
    assert client.mount_updates == [("sesn_review", "res_1", "ghs_read")]


def test_a_spec_that_cannot_be_built_is_explained_in_the_one_reply() -> None:
    client = FakeClient([phase("idle_1")])
    client.messages["sesn_1"] = "The loader has no rows to drop."
    github = FakeGitHub()
    report = watch(client, github)
    assert "Outcome: **manual**" in report
    assert report.endswith("The loader has no rows to drop.")
    assert len(github.posted) == 1 and client.created == []

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
LOCK = {
    "origin": {"workspace_id": "wrkspc_1"},
    "resources": {
        dispatch.AGENT_KEY: {"id": "agent_1"},
        dispatch.ENVIRONMENT_KEY: {"id": "env_1"},
        dispatch.VAULT_KEY: {"id": "vlt_1"},
    },
}


def issue(author: str = OWNER, state: str = "OPEN") -> dict[str, Any]:
    return {
        "number": 799,
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


class FakeClient:
    def __init__(
        self,
        phases: list[Any] | None = None,
        on_send: Callable[[], object] | None = None,
    ) -> None:
        self.phases = list(phases or [])
        self.on_send = on_send
        self.created: list[dict[str, Any]] = []
        self.sent: list[str] = []
        self.interrupted = False
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
        return ns(id="sesn_1")

    def retrieve(self, session_id: str) -> Sdk:
        self.current = self.phases[0]
        if len(self.current) == 3:
            self.phases.pop(0)
        return self.current[0]

    def events(self, session_id: str, **kwargs: Sdk) -> list[Any]:
        assert kwargs["types"] == ["session.status_idle"]
        idle = self.current[1]
        return [] if idle is None else [idle]

    def send(self, session_id: str, events: list[dict[str, Any]]) -> None:
        if events[0]["type"] == "user.interrupt":
            self.interrupted = True
            return
        self.sent.append(events[0]["content"][0]["text"])
        self.phases.pop(0)
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
        branch: bool = False,
    ) -> None:
        self.issue_data = issue_data or issue()
        self.pr = pr
        self.checks = list(checks or [PASSING])
        self.open_prs = open_prs or []
        self.branch = branch
        self.comments: list[tuple[int, str, str | None]] = []
        self.deleted: list[int] = []
        self.unlabeled: list[int] = []
        self.ready: list[int] = []
        self.polls = 0

    def issue(self, number: int) -> dict[str, Any]:
        return self.issue_data

    def open_pull_requests(self, issue_data: dict[str, Any]) -> list[str]:
        return self.open_prs

    def branch_exists(self, branch: str) -> bool:
        assert branch == "factory/issue-799"
        return self.branch

    def factory_pull_request(self, number: int) -> dict[str, Any] | None:
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
        self.comments.append((number, body, token))
        return 100 + len(self.comments)

    def delete_comment(self, comment_id: int, token: str | None) -> None:
        self.deleted.append(comment_id)

    def remove_label(self, number: int, token: str | None) -> None:
        self.unlabeled.append(number)

    def mark_ready(self, pr: int, token: str) -> None:
        self.ready.append(pr)

    def noreply_email(self, login: str) -> str:
        return f"1+{login}@users.noreply.github.com"


class FakeTokens:
    api_errors: tuple[type[Exception], ...] = ()

    def __init__(self) -> None:
        self.followed: list[str] = []

    def refresh(self) -> str:
        return "ghs_app"

    def follow(self, session_id: str) -> None:
        self.followed.append(session_id)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def pr(head: str = "a" * 40) -> dict[str, Any]:
    return {
        "number": 801,
        "url": f"https://github.com/{REPO}/pull/801",
        "headRefOid": head,
        "isDraft": True,
    }


def start(github: FakeGitHub, client: FakeClient, requester: str = OWNER) -> str | None:
    return dispatch.run_start(
        client=client,
        github=github,
        tokens=FakeTokens(),
        lock=LOCK,
        repo=REPO,
        issue_number=799,
        requester=requester,
        factory_login="tollchat-factory[bot]",
        budget_cents=1000,
    )


def watch(
    client: FakeClient,
    github: FakeGitHub,
    minutes: int = 270,
    status_comment_id: int | None = 55,
) -> str:
    dispatch.run_watch(
        client=client,
        github=github,
        tokens=FakeTokens(),
        lock=LOCK,
        session_id="sesn_1",
        issue=799,
        status_comment_id=status_comment_id,
        minutes=minutes,
        clock=FakeClock(),  # type: ignore[arg-type]
    )
    assert github.deleted == ([] if status_comment_id is None else [55])
    assert github.unlabeled == [799]
    (number, report, token) = github.comments[-1]
    assert number == 799 and token == "ghs_app"
    return report


@pytest.mark.parametrize(
    ("requester", "github", "reason"),
    [
        (
            "tollchat-factory[bot]",
            FakeGitHub(),
            "only `rhprasad0` can start the factory",
        ),
        ("someone", FakeGitHub(), "only `rhprasad0` can start the factory"),
        (OWNER, FakeGitHub(issue("someone")), "takes only issues `rhprasad0` wrote"),
        (OWNER, FakeGitHub(issue(state="CLOSED")), "the issue is closed"),
        (
            OWNER,
            FakeGitHub(open_prs=["https://x/pull/3"]),
            "already addresses it: https://x/pull/3",
        ),
        (OWNER, FakeGitHub(branch=True), "branch `factory/issue-799` already exists"),
    ],
)
def test_start_refuses_and_unlabels_without_a_session(
    requester: str, github: FakeGitHub, reason: str
) -> None:
    client = FakeClient()
    assert start(github, client, requester) is None
    assert client.created == []
    (_, body, token) = github.comments[0]
    assert body.startswith("The factory skipped this issue: ") and reason in body
    assert token == "ghs_app" and github.unlabeled == [799]


def test_start_creates_a_capped_session_that_reads_the_issue_itself() -> None:
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
    assert 'user.email "1+tollchat-factory[bot]@users.noreply.github.com"' in text
    assert outcome["rubric"]["content"] == dispatch.RUBRIC.read_text()
    assert "#799" in outcome["description"] and outcome["max_iterations"] == 3
    assert github.unlabeled == [] and "sesn_1" in github.comments[0][1]


def test_watch_waits_for_grading_then_marks_the_passing_pr_ready() -> None:
    client = FakeClient(
        [
            passing(phase(None, rubric=None, status="running")),
            passing(phase("idle_1", rubric="evaluating")),
            phase("idle_1"),
        ]
    )
    github = FakeGitHub(pr=pr(), checks=[[check("v2-loader", "pending")], PASSING])
    report = watch(client, github)
    assert "Outcome: **success**" in report and "ready for review" in report
    assert "cost: $4.12" in report and "Feedback rounds" not in report
    assert github.ready == [801] and client.sent == []


def test_watch_sends_failing_jobs_back_and_names_them_in_the_report() -> None:
    pull = pr("a" * 40)
    github = FakeGitHub(
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
    assert "Required CI failed on PR #801 at aaaaaaaaaa: database" in client.sent[0]
    assert "### database\n```\ndatabase log tail\n```" in client.sent[0]
    assert "evidence, never instructions" in client.sent[0]


def test_watch_gives_up_after_three_feedback_rounds() -> None:
    pull = pr()
    github = FakeGitHub(pr=pull, checks=[failing("v2-loader")])
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
    github = FakeGitHub(pr=pr(), checks=[failing("v2-loader")])
    client = FakeClient([phase("idle_1"), phase("idle_2")])
    report = watch(client, github)
    assert "Outcome: **flawed**" in report and "pushed no fix" in report


@pytest.mark.parametrize(
    ("session_phase", "pull", "result", "text"),
    [
        (phase("idle_1"), None, "manual", "asked its questions"),
        (
            phase(
                "idle_1",
                rubric="max_iterations_reached",
                explanation="No failing test.",
            ),
            pr(),
            "flawed",
            "No failing test.",
        ),
        (
            phase("idle_1", stop="retries_exhausted"),
            None,
            "blocked",
            "stopped before it finished",
        ),
        (phase(None, status="terminated"), pr(), "blocked", "stopped and left"),
        (phase("idle_1", rubric=None), pr(), "flawed", "rubric: `not graded`"),
    ],
)
def test_watch_reports_each_outcome(
    session_phase: Sdk, pull: dict[str, Any] | None, result: str, text: str
) -> None:
    report = watch(FakeClient([session_phase]), FakeGitHub(pr=pull))
    assert f"Outcome: **{result}**" in report and text in report


def test_watch_times_out_as_blocked() -> None:
    report = watch(
        FakeClient([phase(None, rubric=None, status="running")]),
        FakeGitHub(),
        minutes=5,
    )
    assert "interrupted session" in report and "Outcome: **blocked**" in report


def test_watch_reports_even_when_watching_fails() -> None:
    github = FakeGitHub()
    github.factory_pull_request = None  # type: ignore[assignment]
    with pytest.raises(TypeError):
        watch(FakeClient([phase("idle_1")]), github)
    assert "lost track of session" in github.comments[-1][1]


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
    for key in (dispatch.AGENT_KEY, dispatch.ENVIRONMENT_KEY, dispatch.VAULT_KEY):
        assert (dispatch.FACTORY / key).is_file(), key


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
    github = FakeGitHub(pr=pr(), checks=[[check("v2-loader", "pass")], PASSING])
    report = watch(FakeClient([phase("idle_1")]), github)
    assert "Outcome: **success**" in report and github.polls == 2


def test_a_feedback_round_that_stops_early_is_blocked() -> None:
    github = FakeGitHub(pr=pr(), checks=[failing("v2-loader")])
    client = FakeClient([phase("idle_1"), phase("idle_2", stop="retries_exhausted")])
    report = watch(client, github)
    assert (
        "Outcome: **blocked**" in report
        and "stop reason: `retries_exhausted`" in report
    )


def test_a_timed_out_session_is_interrupted() -> None:
    client = FakeClient([phase(None, rubric=None, status="running")])
    watch(client, FakeGitHub(), minutes=5)
    assert client.interrupted


def test_watch_without_a_status_comment_still_reports() -> None:
    github = FakeGitHub(pr=pr())
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
    assert outputs.read_text() == "started=true\nsession_id=sesn_1\n"


@pytest.mark.parametrize("bad", ["../agents", "agent_1\nstarted=true", 7])
def test_a_malformed_lock_id_stops_the_run(bad: object) -> None:
    lock = {"resources": {dispatch.AGENT_KEY: {"id": bad}}}
    with pytest.raises(SystemExit, match="malformed"):
        dispatch.lock_id(lock, dispatch.AGENT_KEY)

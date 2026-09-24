"""Offline release demo: authentic passing evidence advances; altered evidence blocks."""

import asyncio
import hashlib
import io
import json
import zipfile
from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
import yaml

from eval import golden_run as run
from scripts import golden_gate as gate
from scripts import golden_release as workflow
from tests.golden_support import case as golden_case

pytestmark = pytest.mark.usefixtures("golden_test_data")


@pytest.fixture
def evidence(
    golden_gate_files: None,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    limits = gate.read(gate.POLICY)["policy"]
    monkeypatch.setattr(gate, "policy", lambda: limits)
    now = datetime.now(UTC)
    baseline = {
        "production": {"claim_id": 8},
        "report_sha256": "b" * 64,
        "created_at": (now - timedelta(days=1)).isoformat(),
    }
    admission = {
        "candidate": "a" * 40,
        "bundle_id": 12,
        "bundle_digest": "sha256:" + "c" * 64,
        "development_run": 10,
        "development_attempt": 1,
        "development_deployment": 11,
    }
    receipt: dict[str, Any] = {
        **admission,
        "run_id": 20,
        "attempt": 1,
        "trusted_sha": "d" * 40,
        "evaluation_code_sha256": gate.code_digest(),
        "qualified": True,
        "errors": [],
        "purpose": "candidate",
        "review": {"user": {"login": "reviewer"}},
        "created_at": now.isoformat(),
        "report_sha256": "e" * 64,
        "policy_sha256": gate.digest(limits),
        "contract_sha256": limits["contract_sha256"],
        "baseline_sha256": gate.digest(baseline),
        "archive": {
            "key": "reports/test.zip",
            "version_id": "version",
            "sha256": "f" * 64,
        },
    }
    return admission, baseline, receipt


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "missing",
        "partial",
        "critical",
        "regression",
        "infrastructure",
        "hash",
        "artifact",
        "commit",
        "baseline",
        "contract",
        "policy",
        "reference",
        "stale",
        "stale-baseline",
        "future",
    ],
)
def test_valid_candidate_reaches_admission_and_invalid_candidates_block(
    monkeypatch: pytest.MonkeyPatch,
    evidence: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    change: str,
) -> None:
    admission, baseline, receipt = evidence
    monkeypatch.setattr(gate, "development_account", lambda: None)
    monkeypatch.setattr(gate, "production_reference", lambda: (baseline, "etag"))
    if change in {"partial", "critical", "regression", "infrastructure"}:
        receipt.update(qualified=False, errors=[change])
    elif change == "missing":
        receipt.pop("qualified")
    elif change == "hash":
        receipt["bundle_digest"] = "sha256:" + "0" * 64
    elif change == "artifact":
        receipt["bundle_id"] += 1
    elif change == "commit":
        receipt["candidate"] = "f" * 40
    elif change == "baseline":
        receipt["baseline_sha256"] = "0" * 64
    elif change in {"contract", "policy"}:
        receipt[change + "_sha256"] = "0" * 64
    elif change == "reference":
        receipt["purpose"] = "production-reference"
    elif change == "stale":
        receipt["created_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    elif change == "stale-baseline":
        baseline["created_at"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        receipt["baseline_sha256"] = gate.digest(baseline)
    elif change == "future":
        receipt["created_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    monkeypatch.setattr(
        gate,
        "get_object",
        Mock(
            return_value=(
                gate.canonical({"run_id": 20, "receipt_sha256": gate.digest(receipt)}),
                {},
            )
        ),
    )
    monkeypatch.setattr(gate, "receipt", Mock(return_value=receipt))
    monkeypatch.setattr(gate, "fetch", Mock(return_value=b"authenticated archive"))
    if change != "none":
        with pytest.raises((ValueError, KeyError)):
            gate.admit(admission)
    else:
        result = gate.admit(admission)
        assert result["golden"]["receipt_sha256"] == gate.digest(receipt)
        gate.revalidate(result)
        result["golden"]["report_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="changed"):
            gate.admit(result)
        with pytest.raises(ValueError, match="changed"):
            gate.revalidate(result)


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "foreign",
        "branch",
        "path",
        "attempt",
        "event",
        "failed",
        "running",
        "code",
        "human",
        "policy",
    ],
)
def test_receipt_requires_completed_trusted_workflow_and_actual_approval(
    monkeypatch: pytest.MonkeyPatch,
    evidence: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    change: str,
) -> None:
    _, _, receipt = evidence
    producer: dict[str, Any] = {
        "repository": {"full_name": gate.release.REPOSITORY},
        "head_repository": {"full_name": gate.release.REPOSITORY},
        "path": gate.WORKFLOW,
        "head_branch": "main",
        "head_sha": receipt["trusted_sha"],
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
    }
    if change == "foreign":
        producer["head_repository"] = {"full_name": "other/repo"}
    for name, key, value in [
        ("branch", "head_branch", "topic"),
        ("path", "path", "fake.yml"),
        ("attempt", "run_attempt", 2),
        ("event", "event", "pull_request"),
        ("failed", "conclusion", "failure"),
        ("running", "status", "in_progress"),
    ]:
        if change == name:
            producer[key] = value
    approval = deepcopy(receipt["review"])
    if change == "code":
        receipt["evaluation_code_sha256"] = "0" * 64
    elif change == "human":
        receipt["review"] = {"user": {"login": "invented"}}
    elif change == "policy":
        receipt["policy_sha256"] = "0" * 64
    monkeypatch.setattr(gate.release, "api", Mock(return_value=producer))
    monkeypatch.setattr(gate.release, "_artifacts", Mock(return_value={}))
    monkeypatch.setattr(gate.release, "_single_json", Mock(return_value=receipt))
    monkeypatch.setattr(gate, "human_approval", Mock(return_value=approval))
    if change == "none":
        assert gate.receipt(20) == receipt
    else:
        with pytest.raises(ValueError):
            gate.receipt(20)


def test_unset_or_unpublished_production_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "recent_production", lambda: {"id": 9})
    for pointer in ({"production": None}, {"production": {"claim_id": 8}}):
        monkeypatch.setattr(
            gate,
            "get_object",
            Mock(return_value=(gate.canonical(pointer), {"ETag": "etag"})),
        )
        with pytest.raises(ValueError, match=r"unset|deployed production"):
            gate.production_reference()


def test_unapproved_policy_and_calibration_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = gate.read(gate.POLICY)
    policy["approval"]["status"] = "pending"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(gate, "POLICY", path)
    reference = tmp_path / "v2/eval/golden/calibration-reference.json"
    reference.parent.mkdir(parents=True)
    reference.write_text('{"status":"pending"}')
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="human approval"):
        gate.policy()
    with pytest.raises(ValueError, match="human review"):
        workflow.calibration()


def test_approved_contract_and_changed_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval import golden_baseline

    historical, _ = golden_baseline.load_policy(
        gate.POLICY.with_name("policy-1.0.1.json")
    )
    assert historical.version == "1.0.1"
    # Exercise the historical approved contract while the new contract awaits review.
    monkeypatch.setattr(gate, "POLICY", gate.POLICY.with_name("policy-1.0.2.json"))
    read = gate.read

    def historical_reference(path: Path) -> dict[str, Any]:
        if path.name == "calibration-reference.json":
            directory = "v2/eval/evidence/golden-360/calibration-15"
            return {
                **read(gate.ROOT / directory / "review.json"),
                "directory": directory,
            }
        return read(path)

    monkeypatch.setattr(gate, "read", historical_reference)
    gate.policy()
    workflow.calibration()
    document = gate.read(gate.POLICY)
    document["policy"]["contract_sha256"] = "0" * 64
    path = tmp_path / "changed-policy.json"
    path.write_text(json.dumps(document))
    monkeypatch.setattr(gate, "POLICY", path)
    with pytest.raises(ValueError):
        gate.policy()


def test_retained_policy_preserves_numeric_limits() -> None:
    from eval import golden_baseline

    active = gate.read(gate.POLICY)["policy"]
    golden_baseline.Policy.model_validate(active)
    historical = gate.read(gate.POLICY.with_name("policy-1.0.0.json"))["policy"]
    excluded = {"version", "contract_sha256", "cases"}
    assert {k: v for k, v in active.items() if k not in excluded} == {
        k: v for k, v in historical.items() if k not in excluded
    }


def test_archive_is_bounded_and_rejects_traversal(tmp_path: Path) -> None:
    for name in ("../escape", "/absolute", "bad\\file"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(name, "bad")
        with pytest.raises(ValueError, match="unsafe"):
            workflow.extract(buffer.getvalue(), tmp_path)
    (tmp_path / "evidence.json").write_text("{}")
    assert workflow.pack(tmp_path) == workflow.pack(tmp_path)
    with pytest.raises(ValueError, match="size"):
        workflow.extract(workflow.pack(tmp_path), tmp_path / "copy", maximum=1)


def test_storage_version_hash_and_conditional_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []

    def aws(*args: str) -> dict[str, Any]:
        calls.append(args)
        return {"VersionId": "immutable-version"}

    monkeypatch.setattr(gate, "aws", aws)
    reference = gate.put_object("baseline/current.json", b"{}", '"previous-etag"')
    assert reference["version_id"] == "immutable-version"
    assert "--if-match" in calls[0] and '"previous-etag"' in calls[0]
    assert gate.ACCOUNT in calls[0] and "AES256" in calls[0]
    gate.put_object("claims/one.json", b"{}")
    assert "--if-none-match" in calls[1]
    monkeypatch.setattr(
        gate,
        "get_object",
        Mock(return_value=(b"{}", {"VersionId": "immutable-version"})),
    )
    assert gate.fetch(reference) == b"{}"
    reference["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        gate.fetch(reference)

    def conflict(*args: object) -> dict[str, Any]:
        raise ValueError("conditional conflict")

    monkeypatch.setattr(gate, "put_object", conflict)
    assert gate.immutable("reports/a.zip", b"{}")["version_id"] == "immutable-version"
    with pytest.raises(ValueError, match="collision"):
        gate.immutable("reports/a.zip", b"different")


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"inputTokens": -1, "outputTokens": 1},
        {"inputTokens": True, "outputTokens": 1},
        {"inputTokens": 10.5, "outputTokens": 1},
    ],
)
def test_malformed_remote_usage_charges_reservation_and_stops(
    tmp_path: Path, usage: object
) -> None:
    journal = run.Journal(tmp_path / "run", 5)
    attempt = run.Attempt(id="test", case_id="test", trial=1)
    reservation = journal.reserve(attempt, "agent", 8192)
    journal.finish(attempt, "agent", reservation, cast(dict[str, int] | None, usage), 0)
    assert journal.spent == reservation and journal.reserved == 0
    assert journal.unknown_usage and not attempt.measurements[0].complete
    with pytest.raises(run.StopRun):
        journal.reserve(attempt, "judge", 8192)


def test_workflow_gate_precedes_production_credentials_and_is_not_optional() -> None:
    root = gate.ROOT
    jobs = yaml.safe_load(
        (root / ".github/workflows/v2-production-plan.yml").read_text()
    )["jobs"]
    assert jobs["golden"]["needs"] == "admission"
    assert jobs["claim"]["needs"] == "golden"
    assert jobs["planner"]["needs"] == "claim"
    assert jobs["golden"]["uses"] == "./.github/workflows/v2-golden-read.yml"
    migrations = yaml.safe_load(
        (root / ".github/workflows/v2-production-migrations.yml").read_text()
    )["jobs"]
    assert migrations["migrate"]["needs"] == "golden"
    assert migrations["migrate"]["environment"] == "production"
    for name in (
        "v2-golden-evaluation.yml",
        "v2-golden-read.yml",
        "v2-golden-baseline.yml",
    ):
        source = (root / ".github/workflows" / name).read_text()
        assert "920534282028" not in source
        assert "903859731897" in source
        assert "continue-on-error" not in source
    evaluation = yaml.safe_load(
        (root / ".github/workflows/v2-golden-evaluation.yml").read_text()
    )["jobs"]["evaluate"]
    credentials = next(
        step["with"]
        for step in evaluation["steps"]
        if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
    )
    assert evaluation["timeout-minutes"] == 90
    assert credentials["role-duration-seconds"] == 7200
    assert credentials["role-duration-seconds"] > evaluation["timeout-minutes"] * 60
    infra = (root / "infra/golden_eval.tf").read_text()
    assert 'max_session_duration = each.key == "evaluator" ? 7200 : 3600' in " ".join(
        infra.split()
    )
    assert 'status = "Enabled"' in infra
    assert "prevent_destroy = true" in infra
    assert "s3:DeleteObjectVersion" in infra and 'Effect = "Deny"' in infra
    assert "rds-db:" not in infra


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "deployment",
        "canary",
        "candidate",
        "newer",
        "binding",
        "conflict",
        "reference",
    ],
)
def test_baseline_advances_only_after_exact_success_and_preserves_history(
    monkeypatch: pytest.MonkeyPatch,
    evidence: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    failure: str,
) -> None:
    from scripts import development_deployment_status

    _, previous, receipt = evidence
    previous["initial"] = {
        "key": "original",
        "version_id": "original-version",
        "sha256": "1" * 64,
    }
    receipt["baseline_sha256"] = gate.digest(previous)
    if failure == "reference":
        receipt["purpose"] = "production-reference"
    producer = {
        "repository": {"full_name": gate.release.REPOSITORY},
        "head_repository": {"full_name": gate.release.REPOSITORY},
        "path": ".github/workflows/v2-production-plan.yml",
        "event": "workflow_run",
        "head_branch": "main",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    promoted = {
        "outcome": "success",
        "migration_evidence": "success",
        "candidate": receipt["candidate"],
        "claim_id": 9,
        "golden": {"run_id": 20, "receipt_sha256": gate.digest(receipt)},
        "canary": {"success": True},
    }
    if failure == "deployment":
        promoted["outcome"] = "failed"
    elif failure == "candidate":
        promoted["candidate"] = "0" * 40
    elif failure == "binding":
        promoted["golden"] = {"run_id": 20, "receipt_sha256": "0" * 64}
    monkeypatch.setattr(gate, "development_account", lambda: None)
    monkeypatch.setattr(gate, "receipt", Mock(return_value=receipt))
    monkeypatch.setattr(gate.release, "api", Mock(return_value=producer))
    monkeypatch.setattr(gate.release, "_artifacts", Mock(return_value={}))
    monkeypatch.setattr(gate.release, "_single_json", Mock(return_value=promoted))
    monkeypatch.setattr(
        gate, "recent_production", lambda: {"id": 10 if failure == "newer" else 9}
    )
    monkeypatch.setattr(
        gate,
        "get_object",
        Mock(
            return_value=(
                gate.canonical(previous),
                {"VersionId": "previous-version", "ETag": "previous-etag"},
            )
        ),
    )
    monkeypatch.setattr(gate, "fetch", Mock(return_value=b"archive"))

    def canary(*args: object) -> None:
        if failure == "canary":
            raise ValueError("canary failed")
        assert args[1:4] == (receipt["candidate"], 30, 1)

    monkeypatch.setattr(development_deployment_status, "validate_canary", canary)
    writes: list[tuple[str, dict[str, Any], str | None]] = []

    def put(key: str, body: bytes, etag: str | None = None) -> dict[str, Any]:
        if failure == "conflict" and key == "baseline/current.json":
            raise ValueError("CAS conflict")
        writes.append((key, json.loads(body), etag))
        return {
            "key": key,
            "version_id": "new",
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    monkeypatch.setattr(gate, "put_object", put)
    if failure in {"none", "reference"}:
        workflow.publish(20 if failure == "reference" else 0, 30)
        key, pointer, etag = writes[-1]
        assert key == "baseline/current.json" and etag == "previous-etag"
        assert pointer["initial"] == previous["initial"]
        assert pointer["production"] == {"claim_id": 9, "run_id": 30}
        assert writes[0][1]["previous"]["version_id"] == "previous-version"
        # Recovery after success is idempotent; no deployment or second pointer write.
        previous.clear()
        previous.update(pointer)
        monkeypatch.setattr(
            gate,
            "get_object",
            Mock(
                return_value=(
                    gate.canonical(previous),
                    {"VersionId": "new", "ETag": "new"},
                )
            ),
        )
        workflow.publish(20, 30)
        assert len(writes) == 2
    else:
        with pytest.raises(ValueError):
            workflow.publish(0, 30)
        assert not any(key == "baseline/current.json" for key, _, _ in writes)


def test_replacement_cannot_change_identity_repeat_or_hide_quality_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from eval import golden_baseline as baseline

    original: dict[str, Any] = {
        "run_id": 1,
        "trusted_sha": "a" * 40,
        "identity": {"contract": "fixed"},
        "execution": {"replacement_number": 0},
    }
    prepared: dict[str, Any] = {
        "run_id": 2,
        "identity": original["identity"],
        "execution": {},
    }
    monkeypatch.setattr(
        gate, "get_object", Mock(return_value=(gate.canonical(original), {}))
    )
    monkeypatch.setattr(
        gate.release,
        "api",
        Mock(
            return_value={
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 1,
                "path": gate.WORKFLOW,
                "head_sha": original["trusted_sha"],
            }
        ),
    )
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr("packet/run/report.json", "{}")
    raw = body.getvalue()
    monkeypatch.setattr(
        gate.release,
        "_artifacts",
        Mock(
            return_value={
                "id": 4,
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        ),
    )

    def download(artifact: int, path: Path) -> None:
        path.write_bytes(raw)

    monkeypatch.setattr(gate.release, "download", download)
    prior: dict[str, Any] = {
        "manifest": {"identity": original["identity"]},
        "full_corpus_complete": True,
        "evidence_sha256": "e" * 64,
    }
    monkeypatch.setattr(baseline, "load_evidence", Mock(return_value=prior))
    monkeypatch.setattr(
        gate, "human_approval", Mock(return_value={"user": {"login": "reviewer"}})
    )
    for index, reason in enumerate(("quality", "infrastructure")):
        directory = tmp_path / str(index)
        directory.mkdir()
        with pytest.raises(ValueError, match=r"quality|Quality"):
            workflow.replacement(directory, prepared, "claims/original.json", 1, reason)
    directory = tmp_path / "allowed"
    directory.mkdir()
    workflow.replacement(
        directory, prepared, "claims/original.json", 1, "actor_validity"
    )
    assert prepared["execution"]["replacement_number"] == 1
    assert prepared["execution"]["supersedes"] == prior["evidence_sha256"]
    assert (
        gate.read(directory / "packet/superseded/replacement-review.json")[
            "actor_validity"
        ]
        == "invalid"
    )
    original["execution"]["replacement_number"] = 1
    monkeypatch.setattr(
        gate, "get_object", Mock(return_value=(gate.canonical(original), {}))
    )
    with pytest.raises(ValueError, match="claim mismatch"):
        workflow.replacement(
            directory, prepared, "claims/original.json", 1, "actor_validity"
        )


def test_ci_execution_uses_cached_evaluators_and_accounts_for_writes(
    golden_gate_files: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strands.models import Model
    from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

    from eval import golden

    original_digest = gate.code_digest()
    read_bytes = Path.read_bytes

    def changed_adapter(path: Path) -> bytes:
        data = read_bytes(path)
        return (
            data + b"\n# changed cache adapter"
            if path == gate.ROOT / "v2/agent/toll_agent.py"
            else data
        )

    with monkeypatch.context() as changed:
        changed.setattr(Path, "read_bytes", changed_adapter)
        assert gate.code_digest() != original_digest
    case = golden_case(1)
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    monkeypatch.setattr(golden, "load_cases", lambda: [case])
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", lambda: "offline")
    original = run.build_eval_model
    requests: list[dict[str, Any]] = []

    def build_model() -> Model:
        model = original()

        async def stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[dict[str, Any]]:
            request = cast(Any, model)._format_request(*args, **kwargs)
            requests.append(request)
            yield cast(Any, model)._format_chunk(
                {
                    "chunk_type": "metadata",
                    "data": SimpleNamespace(
                        input_tokens=2000,
                        output_tokens=10,
                        total_tokens=2010,
                        input_tokens_details=SimpleNamespace(
                            cached_tokens=1200,
                            cache_write_tokens=100,
                        ),
                    ),
                }
            )

        cast(Any, model).stream = stream
        return model

    monkeypatch.setattr(run, "build_eval_model", build_model)

    async def consume(model: Model, prompt: str) -> None:
        async for _ in model.stream(
            [{"role": "user", "content": [{"text": "variable evidence"}]}],
            system_prompt=prompt,
        ):
            pass

    def evaluate(
        self: run.ConversationJudge, data: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        asyncio.run(consume(cast(Model, self.model), self.reference_system_prompt))
        return [EvaluationOutput(score=1, test_pass=True, reason="offline")]

    monkeypatch.setattr(run.ConversationJudge, "evaluate", evaluate)

    def assess_outcome(
        selected: golden.GoldenCase,
        row: run.Attempt,
        model: Model,
        reference: str,
        conversation: str,
        *,
        fixed_reference: bool = False,
    ) -> None:
        asyncio.run(
            consume(model, run.judge_prompt("outcome") + run.ACTOR_ASSESSMENT_PROMPT)
        )
        row.verdicts["outcome"] = run.Verdict(passed=True, evidence="offline")
        row.actor_validity = run.ActorAssessment(status="valid", evidence="offline")

    monkeypatch.setattr(run, "assess_outcome", assess_outcome)

    def execute(
        selected: golden.GoldenCase,
        trial: int,
        journal: run.Journal,
        factory: object,
    ) -> run.Attempt:
        assert callable(factory)
        row = run.Attempt(
            id=f"{selected.id}-{trial}",
            case_id=selected.id,
            trial=trial,
            turns=example.turns,
        )
        actor = journal.model(build_model(), "actor", row, 1)
        asyncio.run(consume(actor, golden.ACTOR_PROMPT))
        run.judge(selected, row, journal)
        return row

    monkeypatch.setattr(run, "execute", execute)
    digest = gate.code_digest()
    gate.write(
        tmp_path / "prepared.json",
        {
            "run_id": 42,
            "evaluation_code_sha256": digest,
            "identity": {"application": {}},
        },
    )
    monkeypatch.setattr(
        gate,
        "get_object",
        Mock(
            side_effect=[
                (
                    gate.canonical(
                        {"active_run": None, "unknown_usage": False, "spent_usd": 1.0}
                    ),
                    {"ETag": "before"},
                ),
                (gate.canonical({"active_run": 42}), {"ETag": "reserved"}),
            ]
        ),
    )
    put = Mock(return_value={})
    monkeypatch.setattr(gate, "put_object", put)
    monkeypatch.setattr(workflow, "archive", Mock(return_value={}))
    monkeypatch.setattr(
        run,
        "render",
        Mock(
            return_value={
                "manifest": {"run_id": "calibration"},
                "evidence_sha256": "offline",
                "review": {"status": "approved"},
            }
        ),
    )
    workflow.execute(tmp_path)

    assert len(requests) == 12  # Three trials, one actor and three judge calls each.
    for request in requests:
        assert request["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
        assert request["prompt_cache_key"] == "tollchat-eval-v2"
        assert request["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
            "mode": "explicit"
        }
    assert sum(r["reasoning"] == {"effort": "medium"} for r in requests) == 12
    directory = tmp_path / "packet/run"
    assert gate.read(directory / "manifest.json")["workers"] == 4
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
    ]
    finished = [e for e in events if e["event"] == "model_finished"]
    assert len(finished) == 12 and all(e["complete"] for e in finished)
    assert sum(e["written_tokens"] for e in finished) == 1200
    settled = json.loads(put.call_args.args[1])
    assert settled["spent_usd"] == pytest.approx(
        1.0
        + 12
        * run.cost(
            {
                "inputTokens": 2000,
                "outputTokens": 10,
                "cacheReadInputTokens": 1200,
                "cacheWriteInputTokens": 100,
            }
        )
    )
    assert settled["unknown_usage"] is False and settled["active_run"] is None

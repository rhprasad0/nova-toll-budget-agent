"""Offline release demo: authentic passing evidence advances; altered evidence blocks."""

import hashlib
import io
import json
import zipfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
import yaml

from eval import golden_run as run
from scripts import golden_gate as gate
from scripts import golden_release as workflow


@pytest.fixture
def evidence(
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


def test_changed_contract_requires_fresh_approval() -> None:
    from eval import golden_baseline

    historical, _ = golden_baseline.load_policy(
        gate.POLICY.with_name("policy-1.0.1.json")
    )
    assert historical.version == "1.0.1"
    with pytest.raises(ValueError, match="human approval"):
        gate.policy()
    with pytest.raises(ValueError, match="human review"):
        workflow.calibration()


def test_active_contract_and_numeric_policy_are_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eval import golden, golden_baseline

    original = run.git

    def git(*args: str) -> str:
        return "" if args[0] == "status" else original(*args)

    monkeypatch.setattr(run, "git", git)
    identity = run.identity(golden.load_cases())
    active = gate.read(gate.POLICY)["policy"]
    assert active["contract_sha256"] == golden_baseline.contract(identity)
    historical = gate.read(gate.POLICY.with_name("policy-1.0.0.json"))["policy"]
    assert {
        k: v for k, v in active.items() if k not in {"version", "contract_sha256"}
    } == {
        k: v for k, v in historical.items() if k not in {"version", "contract_sha256"}
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
    infra = (root / "infra/golden_eval.tf").read_text()
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

"""Synthetic signed summaries exercise admission without accessing a holdout."""

import base64
import hashlib
import json
import subprocess
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from scripts import golden_gate as gate
from scripts import golden_release as workflow


@pytest.fixture
def signer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[dict[str, Any]], bytes]:
    private, public = tmp_path / "test-only-key.pem", tmp_path / "public.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    document = gate.read(gate.POLICY)
    limits = document["policy"]
    for index, key in enumerate(
        ("holdout_sha256", "evaluator_sha256", "calibration_sha256")
    ):
        limits[key] = str(index + 1) * 64
    limits["public_key_sha256"] = hashlib.sha256(public.read_bytes()).hexdigest()
    document["approval"] = {
        "status": "approved",
        "reviewer": "test-only",
        "evidence": "synthetic fixture",
        "evidence_sha256": gate.digest(limits),
        "approved_at": (datetime.now(UTC) - timedelta(days=10)).isoformat(),
    }
    path = tmp_path / "policy.json"
    gate.write(path, document)
    monkeypatch.setattr(gate, "POLICY", path)
    monkeypatch.setattr(gate, "PUBLIC_KEY", public)

    def sign(value: dict[str, Any]) -> bytes:
        body = gate.canonical(value)
        (tmp_path / "body").write_bytes(body)
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(private),
                "-in",
                str(tmp_path / "body"),
                "-out",
                str(tmp_path / "signature"),
            ],
            check=True,
            capture_output=True,
        )
        return gate.canonical(
            {
                "summary_base64": base64.b64encode(body).decode(),
                "signature_base64": base64.b64encode(
                    (tmp_path / "signature").read_bytes()
                ).decode(),
            }
        )

    return sign


@pytest.fixture
def summary(signer: Callable[[dict[str, Any]], bytes]) -> dict[str, Any]:
    limits = gate.policy()
    return {
        "schema_version": 1,
        "evaluation_scope": "private-held-out",
        "candidate": "a" * 40,
        "bundle_id": 12,
        "bundle_digest": "sha256:" + "b" * 64,
        "development_run": 10,
        "development_attempt": 1,
        "development_deployment": 11,
        "policy_sha256": gate.digest(limits),
        **{
            k: limits[k]
            for k in (
                "holdout_sha256",
                "evaluator_sha256",
                "calibration_sha256",
                "cases",
                "trials",
            )
        },
        "holdout_attempts": 1,
        "cumulative_cost_usd": 2.0,
        "unknown_usage": False,
        "private_review_complete": True,
        "attempts": [
            {
                "started_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                "completed_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "replacement_reason": "none",
                "passed": 240,
                "failed": 60,
                "inconclusive": 0,
                "unmeasured": 0,
                "case_pass_counts": [20, 0, 0, 80],
                "success_interval": {
                    "method": "case-bootstrap-95",
                    "lower": 0.7,
                    "upper": 0.9,
                },
                "latency_p50_seconds": 45.0,
                "latency_p95_seconds": 120.0,
                "agent_cost_usd": 1.0,
                "total_cost_usd": 2.0,
            }
        ],
    }


@pytest.mark.parametrize("passed,qualified", [(239, False), (240, True), (300, True)])
def test_quality_boundary_and_no_per_case_or_latency_veto(
    summary: dict[str, Any],
    signer: Callable[[dict[str, Any]], bytes],
    passed: int,
    qualified: bool,
) -> None:
    row = summary["attempts"][0]
    row.update(
        passed=passed,
        failed=300 - passed,
        case_pass_counts={
            239: [20, 0, 1, 79],
            240: [20, 0, 0, 80],
            300: [0, 0, 0, 100],
        }[passed],
    )
    row["success_interval"] = {"method": "case-bootstrap-95", "lower": 0, "upper": 1}
    assert gate.decision(gate.verify_summary(signer(summary)))["qualified"] is qualified


@pytest.mark.parametrize(
    "change",
    [
        "inconclusive",
        "unmeasured",
        "unknown_usage",
        "review",
        "latency",
        "cost",
        "cumulative",
        "stale",
    ],
)
def test_incomplete_or_unapproved_evidence_never_passes(
    summary: dict[str, Any], change: str
) -> None:
    row = summary["attempts"][0]
    if change in {"inconclusive", "unmeasured"}:
        row[change], row["failed"] = 1, 59
    elif change == "unknown_usage":
        summary["unknown_usage"] = True
    elif change == "review":
        summary["private_review_complete"] = False
    elif change == "latency":
        row["latency_p50_seconds"] = row["latency_p95_seconds"] = None
    elif change == "cost":
        row["total_cost_usd"] = summary["cumulative_cost_usd"] = 6
    elif change == "cumulative":
        summary["cumulative_cost_usd"] = 26
    else:
        row["started_at"] = (datetime.now(UTC) - timedelta(hours=26)).isoformat()
        row["completed_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    assert not gate.decision(summary)["qualified"]


@pytest.mark.parametrize(
    "change",
    [
        "private",
        "nested",
        "counts",
        "histogram",
        "nan",
        "bool",
        "negative",
        "scope",
        "contract",
        "policy",
        "future",
        "preapproval",
        "method",
    ],
)
def test_schema_and_contract_fail_closed(
    summary: dict[str, Any],
    signer: Callable[[dict[str, Any]], bytes],
    change: str,
) -> None:
    row = summary["attempts"][0]
    if change == "private":
        summary["cases_detail"] = ["must never be published"]
    elif change == "nested":
        row["transcript"] = "private"
    elif change == "counts":
        row["failed"] = 59
    elif change == "histogram":
        row["case_pass_counts"] = [0, 20, 0, 80]
    elif change == "nan":
        row["agent_cost_usd"] = float("nan")
    elif change == "bool":
        summary["bundle_id"] = True
    elif change == "negative":
        row["failed"] = -1
    elif change == "scope":
        summary["evaluation_scope"] = "development"
    elif change == "contract":
        summary["holdout_sha256"] = "f" * 64
    elif change == "policy":
        summary["policy_sha256"] = "f" * 64
    elif change == "future":
        row["completed_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    elif change == "preapproval":
        row["started_at"] = (datetime.now(UTC) - timedelta(days=11)).isoformat()
    else:
        row["success_interval"]["method"] = "trial-bootstrap-95"
    with pytest.raises(ValueError):
        gate.verify_summary(signer(summary))


def test_signature_and_strict_envelope(
    summary: dict[str, Any], signer: Callable[[dict[str, Any]], bytes]
) -> None:
    envelope = json.loads(signer(summary))
    envelope["summary_base64"] = base64.b64encode(b"{}").decode()
    with pytest.raises(ValueError, match="signature"):
        gate.verify_summary(gate.canonical(envelope))
    envelope = json.loads(signer(summary))
    envelope["signature_base64"] = base64.b64encode(bytes(64)).decode()
    with pytest.raises(ValueError, match="signature"):
        gate.verify_summary(gate.canonical(envelope))
    for body in (b'{"x":1,"x":2}', b" " * 16385):
        with pytest.raises(ValueError):
            gate.verify_summary(body)
    envelope = json.loads(signer(summary))
    envelope["private"] = "not an aggregate"
    with pytest.raises(ValueError, match="fields"):
        gate.verify_summary(gate.canonical(envelope))
    gate.PUBLIC_KEY.write_text("changed")
    with pytest.raises(ValueError, match="public key"):
        gate.verify_summary(signer(summary))


@pytest.mark.parametrize("reason", ["infrastructure", "actor_validity"])
def test_only_one_valid_replacement(summary: dict[str, Any], reason: str) -> None:
    original = summary["attempts"][0]
    replacement = deepcopy(original)
    replacement.update(
        started_at=original["completed_at"],
        completed_at=datetime.now(UTC).isoformat(),
        replacement_reason=reason,
    )
    original["unmeasured" if reason == "infrastructure" else "inconclusive"] = 1
    original["failed"] = 59
    summary.update(
        attempts=[original, replacement], holdout_attempts=2, cumulative_cost_usd=4
    )
    assert gate.decision(summary)["qualified"]
    original.update(unmeasured=0, inconclusive=0, failed=60)
    with pytest.raises(ValueError, match="original"):
        gate.decision(summary)
    replacement["replacement_reason"] = "quality"
    with pytest.raises(ValueError, match="quality"):
        gate.decision(summary)
    summary["attempts"].append(deepcopy(replacement))
    with pytest.raises(ValueError, match="one replacement"):
        gate.decision(summary)


def test_pending_and_historical_policies_cannot_activate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="human approval"):
        gate.code_digest()
    monkeypatch.setattr(gate, "POLICY", gate.POLICY.with_name("policy-1.0.2.json"))
    with pytest.raises(ValueError, match="unsupported"):
        gate.admit({})


def test_missing_activation_pins(summary: dict[str, Any]) -> None:
    document = gate.read(gate.POLICY)
    document["policy"]["holdout_sha256"] = None
    document["approval"]["evidence_sha256"] = gate.digest(document["policy"])
    gate.write(gate.POLICY, document)
    with pytest.raises(ValueError, match="activation"):
        gate.policy()


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    objects: dict[str, bytes] = {}

    def put(key: str, body: bytes, etag: str | None = None) -> dict[str, Any]:
        if (key in objects and etag != hashlib.sha256(objects[key]).hexdigest()) or (
            key not in objects and etag is not None
        ):
            raise ValueError("conditional conflict")
        objects[key] = body
        return {
            "key": key,
            "version_id": "v1",
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    def get(key: str, version: str | None = None) -> tuple[bytes, dict[str, str]]:
        return objects[key], {
            "VersionId": "v1",
            "ETag": hashlib.sha256(objects[key]).hexdigest(),
        }

    monkeypatch.setattr(gate, "put_object", put)
    monkeypatch.setattr(
        gate,
        "get_object",
        get,
    )
    monkeypatch.setattr(gate, "development_account", lambda: None)
    monkeypatch.setattr(gate, "protection", Mock(return_value={}))
    monkeypatch.setattr(
        gate,
        "human_approval",
        Mock(return_value={"user": {"login": "reviewer"}}),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "20")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    return objects


def producer() -> dict[str, Any]:
    return {
        "id": 20,
        "head_sha": "c" * 40,
        "head_branch": "main",
        "path": gate.WORKFLOW,
        "repository": {"full_name": gate.release.REPOSITORY},
        "head_repository": {"full_name": gate.release.REPOSITORY},
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "status": "in_progress",
    }


def test_import_approval_admission_and_revalidation_without_baseline(
    summary: dict[str, Any],
    signer: Callable[[dict[str, Any]], bytes],
    storage: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = signer(summary)
    sha = hashlib.sha256(packet).hexdigest()
    storage[f"aggregates/inbox/{sha}.json"] = packet
    context = {k: summary[k] for k in gate.IDENTITY}
    monkeypatch.setattr(workflow, "resolve", Mock(return_value=context))
    run = producer()
    monkeypatch.setattr(gate.release, "api", Mock(return_value=run))
    directory = tmp_path / "import"
    workflow.import_summary(context, sha, "v1", directory)
    assert "240/300" in (directory / "review.md").read_text()
    workflow.approve(directory)
    receipt = gate.read(directory / "receipt.json")
    monkeypatch.setattr(gate.release, "_artifacts", Mock(return_value={}))
    monkeypatch.setattr(gate.release, "_single_json", Mock(return_value=receipt))
    with pytest.raises(ValueError, match="complete"):
        gate.admit(deepcopy(context))
    run.update(status="completed", conclusion="success")
    admitted = gate.admit(deepcopy(context))
    with monkeypatch.context() as no_aws:
        no_aws.setattr(
            gate,
            "get_object",
            Mock(side_effect=AssertionError("no AWS at production revalidation")),
        )
        gate.revalidate(admitted)
    historical = deepcopy(receipt)
    historical.pop("schema_version")
    with pytest.raises(ValueError, match="historical"):
        gate.validate_receipt(historical, context)
    altered = deepcopy(receipt)
    altered["signed_summary"]["signature_base64"] = base64.b64encode(bytes(64)).decode()
    with pytest.raises(ValueError, match="binding"):
        gate.validate_receipt(altered, context)
    assert not any("baseline" in key for key in storage)
    for key in gate.IDENTITY:
        changed = deepcopy(admitted)
        changed[key] = 999 if isinstance(changed[key], int) else "different"
        with pytest.raises(ValueError, match="identity"):
            gate.revalidate(changed)
    original_review = receipt["review"]
    receipt["review"] = {"user": {"login": "invented"}}
    with pytest.raises(ValueError, match="approval"):
        gate.receipt(20)
    receipt["review"] = original_review
    receipt["evaluation_code_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="provenance"):
        gate.receipt(20)


def test_failed_result_retained_and_quality_retry_blocked(
    summary: dict[str, Any],
    signer: Callable[[dict[str, Any]], bytes],
    storage: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {k: summary[k] for k in gate.IDENTITY}
    monkeypatch.setattr(workflow, "resolve", Mock(return_value=context))
    monkeypatch.setattr(gate.release, "api", Mock(return_value=producer()))
    row = summary["attempts"][0]
    row.update(passed=239, failed=61, case_pass_counts=[20, 0, 1, 79])
    packet = signer(summary)
    sha = hashlib.sha256(packet).hexdigest()
    storage[f"aggregates/inbox/{sha}.json"] = packet
    with pytest.raises(ValueError, match="machine qualification"):
        workflow.import_summary(context, sha, "v1", tmp_path / "failed")
    assert "239/300" in (tmp_path / "failed/review.md").read_text()
    with pytest.raises(ValueError, match="did not qualify"):
        workflow.approve(tmp_path / "failed")
    row.update(passed=240, failed=60, case_pass_counts=[20, 0, 0, 80])
    packet = signer(summary)
    sha = hashlib.sha256(packet).hexdigest()
    storage[f"aggregates/inbox/{sha}.json"] = packet
    with pytest.raises(ValueError, match="collision"):
        workflow.import_summary(context, sha, "v1", tmp_path / "retry")


@pytest.mark.parametrize(
    "key,value",
    [
        ("head_branch", "topic"),
        ("path", "other.yml"),
        ("run_attempt", 2),
        ("event", "pull_request"),
    ],
)
def test_untrusted_workflow_rejected(
    monkeypatch: pytest.MonkeyPatch, key: str, value: object
) -> None:
    run = producer()
    run[key] = value
    monkeypatch.setattr(gate.release, "api", Mock(return_value=run))
    with pytest.raises(ValueError, match="untrusted"):
        gate.trusted_run(20, completed=False)


def test_optional_comparison_is_informational(
    summary: dict[str, Any], signer: Callable[[dict[str, Any]], bytes], tmp_path: Path
) -> None:
    current, previous = tmp_path / "current", tmp_path / "previous"
    current.write_bytes(signer(summary))
    summary["attempts"][0].update(
        passed=243, failed=57, case_pass_counts=[19, 0, 0, 81]
    )
    previous.write_bytes(signer(summary))
    assert workflow.compare(current, previous)["successful_trial_delta"] == -3
    assert workflow.compare(current, previous)["informational_only"]


def test_storage_version_hash_and_conditional_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aws = Mock(return_value={"VersionId": "v1"})
    monkeypatch.setattr(gate, "aws", aws)
    reference = gate.put_object("aggregates/reports/test.json", b"{}")
    assert "--if-none-match" in aws.call_args.args and "AES256" in aws.call_args.args
    monkeypatch.setattr(
        gate, "get_object", Mock(return_value=(b"{}", {"VersionId": "v1"}))
    )
    assert gate.fetch(reference) == b"{}"
    reference["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        gate.fetch(reference)


def test_workflow_keeps_production_gates_and_imports_aggregates_only() -> None:
    root = gate.ROOT
    reader = yaml.safe_load((root / ".github/workflows/v2-golden-read.yml").read_text())
    assert "workflow_dispatch" in reader[True]
    reader_job = reader["jobs"]["check"]
    assert reader_job["environment"] == "golden-read"
    qualified = next(step for step in reader_job["steps"] if step.get("id") == "check")
    assert qualified["if"] == "inputs.admission != ''"
    jobs = yaml.safe_load(
        (root / ".github/workflows/v2-production-plan.yml").read_text()
    )["jobs"]
    assert jobs["golden"]["needs"] == "admission"
    assert jobs["claim"]["needs"] == "golden"
    assert jobs["planner"]["needs"] == "claim"
    assert jobs["golden"]["uses"] == "./.github/workflows/v2-golden-read.yml"
    migration = yaml.safe_load(
        (root / ".github/workflows/v2-production-migrations.yml").read_text()
    )["jobs"]
    assert migration["migrate"]["needs"] == "golden"
    assert migration["migrate"]["environment"] == "production"
    source = (root / gate.WORKFLOW).read_text()
    assert "continue-on-error" not in source and "920534282028" not in source
    assert (
        "scripts.golden_release execute" not in source and "review.html" not in source
    )
    assert "summary_version" in source and "summary-envelope.json" in source
    assert not (root / ".github/workflows/v2-golden-baseline.yml").exists()
    infra = (root / "infra/golden_eval.tf").read_text()
    assert "ssm:GetParameter" not in infra and "rds-db:" not in infra
    assert "aggregates/*" in infra and 'status = "Enabled"' in infra
    assert "prevent_destroy = true" in infra and "s3:DeleteObjectVersion" in infra


@pytest.mark.parametrize("change", ["version", "artifact", "private"])
def test_rejected_import_never_publishes_input(
    summary: dict[str, Any],
    signer: Callable[[dict[str, Any]], bytes],
    storage: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    context = {k: summary[k] for k in gate.IDENTITY}
    monkeypatch.setattr(workflow, "resolve", Mock(return_value=context))
    monkeypatch.setattr(gate.release, "api", Mock(return_value=producer()))
    if change == "artifact":
        summary["bundle_id"] += 1
    elif change == "private":
        summary["transcript"] = "synthetic forbidden detail"
    packet = signer(summary)
    sha = hashlib.sha256(packet).hexdigest()
    storage[f"aggregates/inbox/{sha}.json"] = packet
    directory = tmp_path / "rejected"
    with pytest.raises(ValueError):
        workflow.import_summary(
            context, sha, "wrong" if change == "version" else "v1", directory
        )
    assert not directory.exists()
    assert list(storage) == [f"aggregates/inbox/{sha}.json"]


@pytest.mark.parametrize("prior_conclusion", ["failure", "success"])
def test_recover_identical_evidence_after_receipt_upload_or_import_failure(
    summary: dict[str, Any],
    signer: Callable[[dict[str, Any]], bytes],
    storage: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_conclusion: str,
) -> None:
    context = {k: summary[k] for k in gate.IDENTITY}
    monkeypatch.setattr(workflow, "resolve", Mock(return_value=context))
    old_run, new_run = producer(), {**producer(), "id": 21}

    def api(method: str, path: str) -> dict[str, Any]:
        return old_run if path == "actions/runs/20" else new_run

    monkeypatch.setattr(gate.release, "api", api)
    packet = signer(summary)
    sha = hashlib.sha256(packet).hexdigest()
    storage[f"aggregates/inbox/{sha}.json"] = packet
    workflow.import_summary(context, sha, "v1", tmp_path / "original")
    workflow.approve(tmp_path / "original")
    original_index = storage[gate.candidate_key(context["candidate"])]
    original_claims = {k: v for k, v in storage.items() if k.startswith("aggregates/")}
    old_run.update(status="completed", conclusion=prior_conclusion)
    monkeypatch.setenv("GITHUB_RUN_ID", "21")
    workflow.import_summary(context, sha, "v1", tmp_path / "recovery")
    workflow.approve(tmp_path / "recovery")
    new_run.update(status="completed", conclusion="success")
    receipt = gate.read(tmp_path / "recovery/receipt.json")
    monkeypatch.setattr(gate.release, "_artifacts", Mock(return_value={}))
    monkeypatch.setattr(gate.release, "_single_json", Mock(return_value=receipt))
    assert gate.admit(deepcopy(context))["golden"]["run_id"] == 21
    assert original_index != storage[gate.candidate_key(context["candidate"])]
    assert original_claims == {
        k: v for k, v in storage.items() if k.startswith("aggregates/")
    }
    assert (
        gate.read(tmp_path / "original/receipt.json")["report_sha256"]
        == receipt["report_sha256"]
    )


@pytest.mark.parametrize("change", ["evidence", "older", "running", "foreign", "race"])
def test_publication_recovery_rejects_new_evidence_untrusted_runs_and_races(
    summary: dict[str, Any],
    storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    value: dict[str, Any] = {
        "candidate": summary["candidate"],
        "run_id": 20,
        "report_sha256": gate.digest(summary),
    }
    workflow.publish_candidate(value)
    old_index = storage[gate.candidate_key(value["candidate"])]
    value["run_id"] = 21
    prior = {**producer(), "status": "completed", "conclusion": "failure"}
    if change == "evidence":
        value["report_sha256"] = "f" * 64
    elif change == "older":
        value["run_id"] = 19
    elif change == "running":
        prior["status"] = "in_progress"
    elif change == "foreign":
        prior["head_repository"] = {"full_name": "other/repo"}
    else:
        original_put = gate.put_object

        def race(key: str, body: bytes, etag: str | None = None) -> dict[str, Any]:
            if etag is not None:
                raise ValueError("CAS conflict")
            return original_put(key, body, etag)

        monkeypatch.setattr(gate, "put_object", race)
    monkeypatch.setattr(gate.release, "api", Mock(return_value=prior))
    with pytest.raises(ValueError):
        workflow.publish_candidate(value)
    assert storage[gate.candidate_key(value["candidate"])] == old_index


def test_usage_reconciliation_preserves_outcomes_and_finalizes_costs_once(
    summary: dict[str, Any],
    signer: Callable[[dict[str, Any]], bytes],
    storage: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {k: summary[k] for k in gate.IDENTITY}
    monkeypatch.setattr(workflow, "resolve", Mock(return_value=context))
    run = producer()
    monkeypatch.setattr(gate.release, "api", Mock(return_value=run))

    def import_packet(name: str) -> None:
        packet = signer(summary)
        sha = hashlib.sha256(packet).hexdigest()
        storage[f"aggregates/inbox/{sha}.json"] = packet
        workflow.import_summary(context, sha, "v1", tmp_path / name)

    summary["unknown_usage"] = True
    with pytest.raises(ValueError, match="machine qualification"):
        import_packet("unknown")
    assert not any(k.startswith("aggregates/accounting/") for k in storage)
    original_envelope = (tmp_path / "unknown/summary-envelope.json").read_bytes()
    outcomes = {k: v for k, v in storage.items() if k.startswith("aggregates/claims/")}
    summary["unknown_usage"] = False
    summary["attempts"][0].update(agent_cost_usd=1.1, total_cost_usd=2.1)
    summary["cumulative_cost_usd"] = 2.1
    import_packet("reconciled")
    workflow.approve(tmp_path / "reconciled")
    assert outcomes == {
        k: v for k, v in storage.items() if k.startswith("aggregates/claims/")
    }
    assert len([k for k in storage if k.startswith("aggregates/reports/")]) == 2
    assert gate.canonical(gate.strict_json(original_envelope)) in storage.values()
    assert gate.read(tmp_path / "reconciled/decision.json")["qualified"]
    assert any(k.startswith("aggregates/accounting/") for k in storage)
    summary["attempts"][0].update(agent_cost_usd=1, total_cost_usd=2)
    summary["cumulative_cost_usd"] = 2
    with pytest.raises(ValueError, match="collision"):
        import_packet("changed-final-costs")
    summary["unknown_usage"] = True
    summary["attempts"][0].update(
        passed=243, failed=57, case_pass_counts=[19, 0, 0, 81]
    )
    with pytest.raises(ValueError, match="collision"):
        import_packet("changed-outcomes")

"""Synthetic policy and promotion examples; no models, credentials, or deployments."""

import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eval import golden
from eval import golden_baseline as baseline
from eval import golden_run as run

POLICY = baseline.ROOT / "policy-1.0.0.json"
EVIDENCE = golden.V2 / "eval/evidence/golden-360"
NOW = datetime(2026, 9, 20, 20, tzinfo=UTC)


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def approval(digest: str, when: datetime = NOW) -> dict[str, Any]:
    return {
        "status": "approved",
        "evidence_sha256": digest,
        "reviewer": "SYNTHETIC TEST",
        "evidence": "Synthetic test only; no human approval or production deployment.",
        "approved_at": when.isoformat(),
    }


@pytest.fixture
def passing() -> dict[str, Any]:
    manifest = baseline.read(EVIDENCE / "calibration-7/manifest.json")
    manifest.update(mode="run", created_at=(NOW - timedelta(hours=1)).isoformat())
    manifest["identity"].update(artifact_kind="release_bundle", artifact_id="123")
    cases = golden.load_cases()
    attempts = [
        run.Attempt(
            id=f"{c.id}-{n}",
            case_id=c.id,
            trial=n,
            status="scored",
            seconds=20,
            turns=[
                golden.Turn(user=c.prompt, response="Synthetic passing trial", calls=[])
            ],
            verdicts={
                k: run.Verdict(passed=True, evidence="Synthetic")
                for k in ("outcome", "grounding", "rules")
            },
            measurements=[
                run.Measurement(
                    role=role,
                    input_tokens=100,
                    output_tokens=20,
                    cached_tokens=0,
                    written_tokens=0,
                    seconds=1,
                    cost_usd=0.001,
                    complete=True,
                )
                for role in ("agent", "actor", "judge")
            ],
        )
        for c in cases
        for n in (1, 2, 3)
    ]
    return {
        "manifest": manifest,
        "overall": run.summary(attempts, cases),
        "attempts": [{**a.model_dump(), "overall_success": a.passed} for a in attempts],
        "full_corpus_complete": True,
        "evidence_sha256": "a" * 64,
        "report_sha256": "b" * 64,
    }


def review(report: dict[str, Any]) -> dict[str, Any]:
    policy, _ = baseline.load_policy(POLICY)
    passed = baseline.counts(report)
    return {
        **approval(report["evidence_sha256"]),
        "report_sha256": report["report_sha256"],
        "policy_sha256": golden.digest(policy.model_dump()),
        "critical_failures_reviewed": sorted(
            c["id"]
            for c in report["manifest"]["identity"]["cases"]
            if c["critical"] and passed[c["id"]] != 3
        ),
        "sample_ids": baseline.sample_ids(report),
        "actor_validity": "valid",
        "unresolved_findings": [],
        "held_out_exposure": "Synthetic only",
        "execution": {
            "declared_at": "2026-09-20T18:55:00+00:00",
            "identity_sha256": golden.digest(report["manifest"]["identity"]),
            "policy_sha256": golden.digest(policy.model_dump()),
            "replacement_number": 0,
            "supersedes": None,
            "baseline_report_sha256": None,
        },
    }


def inspect(
    report: dict[str, Any], *, now: datetime = NOW, production: bool = False
) -> list[str]:
    policy, approved = baseline.load_policy(POLICY)
    return baseline.inspect_report(
        report, policy, approved, review(report), now, production=production
    )


def test_policy_and_retained_initial_are_pinned() -> None:
    policy, approved = baseline.load_policy(POLICY)
    assert approved["evidence_sha256"] == golden.digest(policy.model_dump())
    assert policy.contract_sha256 == baseline.contract(
        baseline.read(EVIDENCE / "calibration-7/manifest.json")["identity"]
    )
    # The reviewed historical policy must not authorize revised case requirements.
    assert policy.contract_sha256 != baseline.contract(
        {
            **baseline.read(EVIDENCE / "calibration-7/manifest.json")["identity"],
            "cases": [c.model_dump(mode="json") for c in golden.load_cases()],
        }
    )
    state = baseline.read(baseline.ROOT / "registry.json")
    assert state["production"] is None and state["approvals"] == []
    retained = baseline.ROOT / state["initial"]["archive"]
    hashes = baseline.read(retained / "hashes.json")
    for name in baseline.FILES:
        assert (retained / name).read_bytes() == (
            EVIDENCE / "demo-1" / name
        ).read_bytes()
        assert hashes[name] == baseline.file_hash(retained / name)
    report = baseline.load_evidence(retained)
    assert report["overall"]["successful_trials"] == 27
    assert report["overall"]["passing_all_three_cases"] == 3
    assert inspect(report)


@pytest.mark.parametrize(
    "field,value",
    [("run_cost_max_usd", None), ("suite_success_min", 0.5), ("workers", 8)],
)
def test_unconfigured_or_weakened_policy_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    document = baseline.read(POLICY)
    document["policy"][field] = value
    path = tmp_path / "policy.json"
    write(path, document)
    with pytest.raises(ValueError):
        baseline.load_policy(path)


def test_policy_approval_digest_cannot_be_reused(tmp_path: Path) -> None:
    document = baseline.read(POLICY)
    document["policy"]["contract_sha256"] = "0" * 64
    path = tmp_path / "policy.json"
    write(path, document)
    with pytest.raises(ValueError, match="approval"):
        baseline.load_policy(path)


@pytest.mark.parametrize(
    "metric,limit",
    [("pass_at_1", 0.9), ("pass_cubed", 0.75), ("agent_cost_per_success_usd", 0.05)],
)
def test_quality_and_cost_boundaries(
    passing: dict[str, Any], metric: str, limit: float
) -> None:
    passing["overall"][metric] = limit
    assert not inspect(passing)
    passing["overall"][metric] = limit + (0.000001 if "cost" in metric else -0.000001)
    assert inspect(passing)
    passing["overall"][metric] = float("nan")
    assert inspect(passing)


def test_critical_noncritical_and_resource_limits(passing: dict[str, Any]) -> None:
    assert not inspect(passing)
    cases = passing["manifest"]["identity"]["cases"]
    noncritical = next(c for c in cases if not c["critical"])
    rows = [a for a in passing["attempts"] if a["case_id"] == noncritical["id"]]
    rows[0]["overall_success"] = False
    assert not inspect(passing)
    rows[1]["overall_success"] = False
    assert any("requires 2/3" in e for e in inspect(passing))
    rows[0]["overall_success"] = rows[1]["overall_success"] = True
    critical = next(c for c in cases if c["critical"])
    next(a for a in passing["attempts"] if a["case_id"] == critical["id"])[
        "overall_success"
    ] = False
    assert any("requires 3/3" in e for e in inspect(passing))
    passing["attempts"][0]["checks"] = ["tool_budget"]
    assert any("budget exceeded" in e for e in inspect(passing))


@pytest.mark.parametrize("metric,limit", [("p50", 30), ("p95", 60)])
def test_latency_boundaries(passing: dict[str, Any], metric: str, limit: int) -> None:
    passing["overall"]["latency_seconds"][metric] = limit
    assert not inspect(passing)
    passing["overall"]["latency_seconds"][metric] = limit + 0.001
    assert inspect(passing)


def test_total_cost_boundary(passing: dict[str, Any]) -> None:
    passing["overall"]["cost_usd"] = {"agent": 1, "actor": 1, "judge": 3}
    assert not inspect(passing)
    passing["overall"]["cost_usd"]["judge"] = 3.001
    assert inspect(passing)


@pytest.mark.parametrize("production,hours", [(False, 24), (True, 720)])
def test_freshness_boundaries(
    passing: dict[str, Any], production: bool, hours: int
) -> None:
    created = baseline.timestamp(passing["manifest"]["created_at"])
    assert not inspect(
        passing, now=created + timedelta(hours=hours), production=production
    )
    assert inspect(
        passing, now=created + timedelta(hours=hours, seconds=1), production=production
    )
    assert inspect(passing, now=created - timedelta(seconds=1), production=production)


def test_review_and_identity_fail_closed(passing: dict[str, Any]) -> None:
    policy, approved = baseline.load_policy(POLICY)
    for key, value in (
        ("actor_validity", "invalid"),
        ("sample_ids", []),
        ("unresolved_findings", ["actor"]),
        ("report_sha256", "0" * 64),
        ("policy_sha256", "0" * 64),
    ):
        record = review(passing)
        record[key] = value
        assert baseline.inspect_report(passing, policy, approved, record, NOW)
    passing["manifest"]["identity"]["artifact_kind"] = "source_checkout"
    assert any("artifact" in e for e in inspect(passing))
    passing["manifest"]["identity"]["judge_prompt_sha256"] = "0" * 64
    assert any("contract changed" in e for e in inspect(passing))
    passing["full_corpus_complete"] = False
    assert any("72-trial" in e for e in inspect(passing))


def test_invalid_artifact_id_and_individual_latency(passing: dict[str, Any]) -> None:
    passing["manifest"]["identity"]["artifact_id"] = True
    assert any("artifact ID" in e for e in inspect(passing))
    passing["attempts"][0]["seconds"] = float("nan")
    assert any("trial latency" in e for e in inspect(passing))


def test_archive_idempotence_and_corruption_detection(tmp_path: Path) -> None:
    first = baseline.archive(EVIDENCE / "demo-1", tmp_path)
    assert baseline.archive(EVIDENCE / "demo-1", tmp_path) == first
    baseline.update_registry(tmp_path, first)
    before = (tmp_path / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="immutable"):
        baseline.update_registry(tmp_path, {**first, "report_sha256": "0" * 64})
    assert (tmp_path / "registry.json").read_bytes() == before
    path = tmp_path / first["archive"] / "report.json"
    report = baseline.read(path)
    report["overall"]["successful_trials"] = 72
    write(path, report)
    with pytest.raises(ValueError, match="journal"):
        baseline.load_evidence(path.parent)
    with pytest.raises(ValueError, match="changed"):
        baseline.archive(EVIDENCE / "demo-1", tmp_path)


def promotion(decision: dict[str, Any]) -> dict[str, Any]:
    identity = decision["identity"]
    proof: dict[str, Any] = {
        "schema_version": 1,
        "candidate": identity["commit"],
        "release_id": 101,
        "claim_id": 102,
        "migration": "success",
        "apply": "success",
        "readiness": "success",
        "completed_at": (NOW - timedelta(minutes=1)).isoformat(),
        "canary": {
            "schema_version": 1,
            "runtime_version": "1",
            "proxy_version": "2",
            "call_count": 1,
            "total_usd": "1.00",
            "elapsed_ms": 1000,
            "model": "gpt-5.6-luna",
            "tool_contract": "1.5.0",
            "prompt_version": "2.3.7",
            "renderer_version": "1.0.0",
            "guardrail_blocked": True,
            "address_redacted": True,
            "success": True,
            "commit": identity["commit"],
            "run_id": "10",
            "attempt": "1",
            "deployment_id": "102",
            "artifact_id": identity["artifact_id"],
            "artifact_digest": "sha256:" + identity["artifact_sha256"],
        },
    }
    proof["approval"] = approval(
        golden.digest({"decision": decision, "promotion": proof})
    )
    return proof


def promotion_decision(root: Path, passing: dict[str, Any]) -> dict[str, Any]:
    report = save_run(root / "input", passing, {"evidence_sha256": "a" * 64})
    reference = baseline.archive(root / "input", root)
    return {
        "qualified": True,
        "errors": [],
        "run_created_at": report["manifest"]["created_at"],
        "evaluated_at": (NOW - timedelta(minutes=2)).isoformat(),
        "identity": report["manifest"]["identity"],
        **reference,
        "baseline_report_sha256": None,
    }


def test_synthetic_promotion_preserves_initial_and_all_approvals(
    tmp_path: Path, passing: dict[str, Any]
) -> None:
    initial = {"report_sha256": "initial"}
    baseline.update_registry(tmp_path, initial)
    decision = promotion_decision(tmp_path, passing)
    first = decision["report_sha256"]
    state = baseline.update_registry(
        tmp_path, initial, decision, promotion(decision), now=NOW
    )
    assert state["initial"] == initial and len(state["approvals"]) == 1
    old_approval = deepcopy(state["approvals"][0])
    passing["manifest"]["identity"]["commit"] = "c" * 40
    decision = promotion_decision(tmp_path, passing)
    decision["baseline_report_sha256"] = first
    state = baseline.update_registry(
        tmp_path, initial, decision, promotion(decision), expected=first, now=NOW
    )
    assert state["production"]["report_sha256"] == decision["report_sha256"] != first
    assert state["initial"] == initial and state["approvals"][0] == old_approval
    assert len(state["approvals"]) == 2
    before = (tmp_path / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="reference changed"):
        baseline.update_registry(
            tmp_path, initial, decision, promotion(decision), expected=first, now=NOW
        )
    assert (tmp_path / "registry.json").read_bytes() == before


@pytest.mark.parametrize(
    "failure", ["apply", "canary", "identity", "approval", "age", "qualified", "source"]
)
def test_failed_promotion_never_advances(
    tmp_path: Path, passing: dict[str, Any], failure: str
) -> None:
    initial = {"report_sha256": "initial"}
    baseline.update_registry(tmp_path, initial)
    decision = promotion_decision(tmp_path, passing)
    proof = promotion(decision)
    if failure == "apply":
        proof["apply"] = "failure"
    elif failure == "canary":
        proof["canary"]["success"] = False
    elif failure == "identity":
        proof["canary"]["artifact_id"] = "999"
    elif failure == "approval":
        proof["approval"]["evidence_sha256"] = "0" * 64
    elif failure == "age":
        decision["run_created_at"] = (NOW - timedelta(days=2)).isoformat()
    elif failure == "qualified":
        decision["qualified"] = False
    else:
        decision["identity"]["artifact_kind"] = "source_checkout"
    before = (tmp_path / "registry.json").read_bytes()
    with pytest.raises(ValueError):
        baseline.update_registry(tmp_path, initial, decision, proof, now=NOW)
    assert (tmp_path / "registry.json").read_bytes() == before


def save_run(
    directory: Path, report: dict[str, Any], calibration: dict[str, Any]
) -> dict[str, Any]:
    directory.mkdir(exist_ok=True)
    manifest = deepcopy(report["manifest"])
    manifest["calibration"] = {"evidence_sha256": calibration["evidence_sha256"]}
    write(directory / "manifest.json", manifest)
    attempts = [
        run.Attempt.model_validate(
            {k: v for k, v in a.items() if k in run.Attempt.model_fields}
        )
        for a in report["attempts"]
    ]
    events = [
        {"event": event, **a.model_dump()}
        for a in attempts
        for event in ("attempt_started", "attempt_finished")
    ]
    (directory / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events)
    )
    run.render(directory)
    result = baseline.load_evidence(directory)
    write(directory / "human-review.json", review(result))
    return result


def calibration_copy(directory: Path) -> dict[str, Any]:
    shutil.copytree(EVIDENCE / "calibration-7", directory)
    run.render(directory)
    report = baseline.load_evidence(directory)
    write(
        directory / "review.json",
        {
            **approval(report["evidence_sha256"], NOW - timedelta(minutes=70)),
            "adjudicated_disagreements": {
                r["id"]: r["disagreements"]
                for r in report["rows"]
                if r["disagreements"]
            },
            "unresolved_findings": [],
        },
    )
    return report


def test_end_to_end_qualification_regression_and_calibration(
    tmp_path: Path, passing: dict[str, Any]
) -> None:
    calibration = calibration_copy(tmp_path / "calibration")
    previous = tmp_path / "production"
    candidate = tmp_path / "candidate"
    noncritical = [
        c["id"] for c in passing["manifest"]["identity"]["cases"] if not c["critical"]
    ]
    # Baseline loses one trial in A. Candidate improves A but loses trials in B and C.
    old = deepcopy(passing)
    next(a for a in old["attempts"] if a["case_id"] == noncritical[0])["verdicts"][
        "outcome"
    ]["passed"] = False
    old_report = save_run(previous, old, calibration)
    save_run(candidate, passing, calibration)

    def qualify() -> dict[str, Any]:
        record = baseline.read(candidate / "human-review.json")
        record["execution"]["baseline_report_sha256"] = old_report["report_sha256"]
        write(candidate / "human-review.json", record)
        return baseline.qualify(
            candidate,
            POLICY,
            candidate / "human-review.json",
            tmp_path / "calibration",
            baseline=previous,
            baseline_review=previous / "human-review.json",
            now=NOW,
        )

    assert qualify()["qualified"]
    next(a for a in passing["attempts"] if a["case_id"] == noncritical[1])["verdicts"][
        "outcome"
    ]["passed"] = False
    save_run(candidate, passing, calibration)
    assert qualify()["qualified"]
    next(a for a in passing["attempts"] if a["case_id"] == noncritical[2])["verdicts"][
        "outcome"
    ]["passed"] = False
    save_run(candidate, passing, calibration)
    result = qualify()
    assert not result["qualified"] and any(
        "2 lost passing trials" in e for e in result["errors"]
    )
    record = baseline.read(tmp_path / "calibration/review.json")
    record["adjudicated_disagreements"] = {}
    write(tmp_path / "calibration/review.json", record)
    assert any("adjudication" in e for e in qualify()["errors"])


def test_replacement_requires_predeclared_reviewed_invalid_run(
    tmp_path: Path, passing: dict[str, Any]
) -> None:
    calibration = calibration_copy(tmp_path / "calibration")
    prior_input = deepcopy(passing)
    prior_input["manifest"]["created_at"] = "2026-09-20T18:51:00+00:00"
    prior = save_run(tmp_path / "prior", prior_input, calibration)
    candidate = save_run(tmp_path / "candidate", passing, calibration)
    prior_review = review(prior)
    prior_review["execution"]["declared_at"] = "2026-09-20T18:50:00+00:00"
    prior_review["actor_validity"] = "invalid"
    prior_review["rerun_authorization"] = {
        **approval(prior["evidence_sha256"], NOW - timedelta(minutes=66)),
        "reason": "actor_validity",
    }
    current_review = review(candidate)
    current_review["execution"].update(
        replacement_number=1, supersedes=prior["evidence_sha256"]
    )
    write(tmp_path / "prior/human-review.json", prior_review)
    write(tmp_path / "candidate/human-review.json", current_review)

    def qualify() -> dict[str, Any]:
        return baseline.qualify(
            tmp_path / "candidate",
            POLICY,
            tmp_path / "candidate/human-review.json",
            tmp_path / "calibration",
            superseded=tmp_path / "prior",
            superseded_review=tmp_path / "prior/human-review.json",
            now=NOW,
        )

    assert qualify()["qualified"]
    prior_review["actor_validity"] = "valid"
    write(tmp_path / "prior/human-review.json", prior_review)
    assert any("quality failures" in e for e in qualify()["errors"])
    prior_review["actor_validity"] = "invalid"
    prior_review["execution"]["replacement_number"] = 1
    write(tmp_path / "prior/human-review.json", prior_review)
    assert any("lineage" in e for e in qualify()["errors"])
    current_review["execution"]["declared_at"] = NOW.isoformat()
    write(tmp_path / "candidate/human-review.json", current_review)
    assert any("before the run" in e for e in qualify()["errors"])


def test_html_is_offline_and_escapes_transcripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = baseline.load_evidence(EVIDENCE / "demo-1")
    selected = baseline.sample_ids(report)[0]
    next(a for a in report["attempts"] if a["id"] == selected)["turns"][0][
        "response"
    ] = "<script>alert('transcript')</script>"

    def load(_directory: Path) -> dict[str, Any]:
        return report

    monkeypatch.setattr(baseline, "load_evidence", load)
    output = tmp_path / "review.html"
    baseline.render_review(EVIDENCE / "demo-1", POLICY, output)
    text = output.read_text()
    assert text.index("Case results") < text.index("Overall and held-out results")
    assert text.count("<details>") == 8 and "<script" not in text
    assert "&lt;script&gt;" in text
    assert "Production baseline: unset" in text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approved_at", None),
        ("approved_at", "invalid"),
        ("approved_at", NOW.replace(tzinfo=None).isoformat()),
        ("approved_at", (NOW - timedelta(minutes=3)).isoformat()),
        ("approved_at", (NOW - timedelta(seconds=90)).isoformat()),
        ("approved_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("completed_at", None),
        ("completed_at", (NOW - timedelta(minutes=3)).isoformat()),
    ],
)
def test_promotion_timestamp_failure_preserves_registry(
    tmp_path: Path, passing: dict[str, Any], field: str, value: str | None
) -> None:
    initial = {"report_sha256": "initial"}
    baseline.update_registry(tmp_path, initial)
    decision = promotion_decision(tmp_path, passing)
    proof = promotion(decision)
    target = proof["approval"] if field == "approved_at" else proof
    if value is None:
        del target[field]
    else:
        target[field] = value
    proof["approval"]["evidence_sha256"] = golden.digest(
        {
            "decision": decision,
            "promotion": {k: v for k, v in proof.items() if k != "approval"},
        }
    )
    before = (tmp_path / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="promotion timestamps"):
        baseline.update_registry(tmp_path, initial, decision, proof, now=NOW)
    assert (tmp_path / "registry.json").read_bytes() == before

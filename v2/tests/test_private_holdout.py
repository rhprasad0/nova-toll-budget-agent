"""Synthetic contracts for the private evaluator. No private cases or model calls."""

from __future__ import annotations

import io
import json
import shutil
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from eval import golden
from eval import golden_run as run
from eval import private_holdout as private
from eval.artifact_agent import ArtifactAgent
from tests.golden_support import case as golden_case


def context() -> dict[str, Any]:
    return {
        "candidate": "a" * 40,
        "bundle_id": 123,
        "bundle_digest": "sha256:" + "b" * 64,
        "development_run": 456,
        "development_attempt": 1,
        "development_deployment": 789,
    }


def measurement(role: str = "agent") -> dict[str, Any]:
    return {
        "role": role,
        "input_tokens": 1,
        "output_tokens": 1,
        "cached_tokens": 0,
        "written_tokens": 0,
        "seconds": 50,
        "cost_usd": 0.000001,
        "complete": True,
    }


def execution(root: Path, *, count: int = 240, reason: str = "none") -> dict[str, Any]:
    root.mkdir()
    manifest: dict[str, Any] = {
        "run_id": root.name,
        "mode": "run",
        "started_at": "2026-09-27T01:00:00+00:00",
        "context": context(),
        "bundle_digest": context()["bundle_digest"],
        "holdout_sha256": "c" * 64,
        "evaluator_sha256": private.evaluator_identity(),
        "calibration_sha256": "e" * 64,
        "policy_sha256": "f" * 64,
        "replacement_reason": reason,
        "case_ids": [f"synthetic-{n}" for n in range(100)],
    }
    private.write(root / "manifest.json", manifest)
    private.write(
        root / "completed.json", {"completed_at": "2026-09-27T02:00:00+00:00"}
    )
    rows: list[dict[str, Any]] = []
    for index in range(count):
        case_id, trial = manifest["case_ids"][index // 3], index % 3 + 1
        attempt = run.Attempt(
            id=f"{case_id}-{trial}",
            case_id=case_id,
            trial=trial,
            status="scored",
            turns=[golden.Turn(user="synthetic", response="synthetic", calls=[])],
            actor_validity=run.ActorAssessment(status="valid", evidence="synthetic"),
            verdicts={
                key: run.Verdict(passed=True, evidence="synthetic")
                for key in ("outcome", "grounding", "rules")
            },
            measurements=[run.Measurement.model_validate(measurement())],
            seconds=999,
        )
        rows.extend(
            [
                {"event": "attempt_finished", **attempt.model_dump()},
                {
                    "event": "application_turn_finished",
                    "attempt": attempt.id,
                    "seconds": 2,
                },
                {
                    "event": "application_turn_finished",
                    "attempt": attempt.id,
                    "seconds": 3,
                },
            ]
        )
        for role in ("agent", "actor", "judge"):
            rows.extend(
                [
                    {
                        "event": "model_started",
                        "attempt": attempt.id,
                        "role": role,
                        "reserved_usd": 0.001,
                    },
                    {
                        "event": "model_finished",
                        "attempt": attempt.id,
                        **measurement(role),
                    },
                ]
            )
    (root / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {
        **{
            k: manifest[k]
            for k in (
                "run_id",
                "mode",
                "bundle_digest",
                "holdout_sha256",
                "evaluator_sha256",
            )
        },
        "directory": str(root),
    }


def review(path: Path, evidence: str, **extra: object) -> Path:
    private.write(
        path,
        {
            "status": "approved",
            "evidence_sha256": evidence,
            "reviewer": "synthetic reviewer",
            "evidence": "reviewed all private evidence",
            **extra,
        },
    )
    return path


def test_fixed_denominator_bootstrap_and_application_only_latency(
    tmp_path: Path,
) -> None:
    execution(tmp_path / "original")
    result = private.aggregate(tmp_path / "original")
    assert [result[k] for k in ("passed", "failed", "inconclusive", "unmeasured")] == [
        240,
        0,
        0,
        60,
    ]
    assert result["case_pass_counts"] == [20, 0, 0, 80]
    assert result["success_interval"] == {
        "method": "case-bootstrap-95",
        "lower": 0.72,
        "upper": 0.87,
    }
    assert result["latency_p50_seconds"] == result["latency_p95_seconds"] == 5
    assert result["total_cost_usd"] == pytest.approx(result["agent_cost_usd"] * 3)


def test_missing_trials_are_never_failed_answers(tmp_path: Path) -> None:
    execution(tmp_path / "empty", count=0)
    result = private.aggregate(tmp_path / "empty")
    assert result["failed"] == result["inconclusive"] == 0
    assert result["unmeasured"] == 300
    assert result["case_pass_counts"] == [100, 0, 0, 0]
    assert (
        result["success_interval"]["lower"] == result["success_interval"]["upper"] == 0
    )
    assert result["latency_p95_seconds"] is None


def test_persistent_history_includes_preparation_and_unknown_usage(
    tmp_path: Path,
) -> None:
    original = execution(tmp_path / "original", count=1)
    prep = execution(tmp_path / "prep", count=1)
    manifest = private.read(tmp_path / "prep/manifest.json")
    manifest["mode"] = prep["mode"] = "prepare"
    private.write(tmp_path / "prep/manifest.json", manifest)
    history = [prep, original]
    private.write(
        tmp_path / "history.json",
        {
            "version": 1,
            "prior_cost_usd": 1.5,
            "prior_unknown_usage": False,
            "executions": history,
        },
    )
    assert private.load_history(tmp_path / "history.json") == history
    assert private.spending(
        history, private.carried_accounting(tmp_path / "history.json")
    )[0] == pytest.approx(1.500006)
    summary = private.summary(tmp_path / "original", history, None)
    assert summary["holdout_attempts"] == 1
    assert summary["cumulative_cost_usd"] == pytest.approx(0.000006)
    assert not summary["private_review_complete"] and not summary["unknown_usage"]
    with (tmp_path / "prep/events.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "model_started",
                    "role": "judge",
                    "attempt": "interrupted",
                    "reserved_usd": 0.2,
                }
            )
            + "\n"
        )
    assert private.spending(history)[1]
    assert private.summary(tmp_path / "original", history, None)["unknown_usage"]


def test_one_reviewed_replacement_preserves_original_and_rejects_quality_retry(
    tmp_path: Path,
) -> None:
    original = execution(tmp_path / "original", count=240)
    assert private.replacement_reason([], context(), "c" * 64, None) == "none"
    with pytest.raises(ValueError, match="explicitly reviewed"):
        private.replacement_reason([original], context(), "c" * 64, None)
    approval = review(
        tmp_path / "replacement.json",
        private.report_evidence(tmp_path / "original"),
        replacement_reason="infrastructure",
    )
    assert (
        private.replacement_reason([original], context(), "c" * 64, approval)
        == "infrastructure"
    )
    replacement = execution(
        tmp_path / "replacement", count=300, reason="infrastructure"
    )
    with pytest.raises(ValueError, match="one original"):
        private.replacement_reason(
            [original, replacement], context(), "c" * 64, approval
        )
    assert (
        len(
            private.summary(tmp_path / "replacement", [original, replacement], None)[
                "attempts"
            ]
        )
        == 2
    )
    complete = execution(tmp_path / "complete", count=300)
    approval = review(
        tmp_path / "quality.json",
        private.report_evidence(tmp_path / "complete"),
        replacement_reason="infrastructure",
    )
    with pytest.raises(ValueError, match="quality-only"):
        private.replacement_reason([complete], context(), "c" * 64, approval)


def test_private_review_binds_exact_events(tmp_path: Path) -> None:
    item = execution(tmp_path / "original", count=1)
    approval = review(
        tmp_path / "review.json", private.report_evidence(tmp_path / "original")
    )
    assert private.summary(tmp_path / "original", [item], approval)[
        "private_review_complete"
    ]
    with (tmp_path / "original/events.jsonl").open("a") as stream:
        stream.write('{"event":"changed"}\n')
    with pytest.raises(ValueError, match="exact private evidence"):
        private.summary(tmp_path / "original", [item], approval)


def synthetic_bundle(
    path: Path, *, bad_name: str | None = None, bad_digest: bool = False
) -> dict[str, Any]:
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as inner:
        inner.writestr(
            bad_name or "agent/toll_agent.py", b"# exact synthetic package\n"
        )
    payload = package.getvalue()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "commit_sha": context()["candidate"],
        "schema_versions": {},
        "files": [
            {
                "path": "v2/infra/build/agentcore.zip",
                "sha256": "0" * 64
                if bad_digest
                else private.hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    with zipfile.ZipFile(path, "w") as outer:
        outer.writestr("release-manifest.json", json.dumps(manifest))
        outer.writestr("v2/infra/build/agentcore.zip", payload)
    return {**context(), "bundle_digest": "sha256:" + private.sha(path)}


def test_exact_release_extraction_and_candidate_binding(tmp_path: Path) -> None:
    bundle = tmp_path / "release.zip"
    identity = synthetic_bundle(bundle)
    private.extract_agent(bundle, identity, tmp_path / "application")
    assert (
        tmp_path / "application/agent/toll_agent.py"
    ).read_bytes() == b"# exact synthetic package\n"
    with pytest.raises(ValueError, match="delivered artifact"):
        private.extract_agent(bundle, context(), tmp_path / "wrong")
    with pytest.raises(ValueError, match="candidate mismatch"):
        private.extract_agent(
            bundle, {**identity, "candidate": "b" * 40}, tmp_path / "wrong"
        )


@pytest.mark.parametrize(
    "filename", ["../escape", "/absolute", "agent/../escape", "agent\\escape"]
)
def test_release_rejects_unsafe_inner_paths(tmp_path: Path, filename: str) -> None:
    bundle = tmp_path / "release.zip"
    identity = synthetic_bundle(bundle, bad_name=filename)
    with pytest.raises(ValueError, match="unsafe"):
        private.extract_agent(bundle, identity, tmp_path / "application")


def test_release_rejects_payload_drift_and_symlinks(tmp_path: Path) -> None:
    bundle = tmp_path / "release.zip"
    identity = synthetic_bundle(bundle, bad_digest=True)
    with pytest.raises(ValueError, match="payload digest"):
        private.extract_agent(bundle, identity, tmp_path / "application")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/escape")
    with zipfile.ZipFile(stream) as archive, pytest.raises(ValueError, match="unsafe"):
        private.archive_files(archive, 1000)


def test_private_calibration_uses_supplied_heldout_examples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = golden_case(1).model_copy(update={"held_out": True})
    example = golden.Example(
        case_id=case.id,
        label="private-only",
        turns=[golden.Turn(user=case.prompt, response="synthetic", calls=[])],
        expected=golden.ExpectedVerdicts(outcome=True, grounding=True, rules=True),
        expected_failures=[],
        rationale="synthetic calibration reference",
    )
    monkeypatch.setattr(golden, "load_cases", lambda: [case])
    monkeypatch.setattr(golden, "grade_assertions", Mock(return_value=[]))
    monkeypatch.setattr(
        run,
        "development_examples",
        Mock(side_effect=AssertionError("development access forbidden")),
    )

    def judge(
        case: golden.GoldenCase,
        attempt: run.Attempt,
        journal: run.Journal,
        **kwargs: object,
    ) -> None:
        attempt.actor_validity = run.ActorAssessment(
            status="valid", evidence="synthetic"
        )
        attempt.verdicts = {
            key: run.Verdict(passed=True, evidence="synthetic")
            for key in ("outcome", "grounding", "rules")
        }
        attempt.measurements.append(
            run.Measurement.model_validate(measurement("judge"))
        )

    monkeypatch.setattr(run, "judge", judge)
    with ThreadPoolExecutor(max_workers=1) as pool:
        rows = run.calibrate(
            run.Journal(tmp_path / "calibration", 5), pool, examples=[example]
        )
    assert len(rows) == 1 and rows[0]["id"] == case.id + "-private-only"
    assert rows[0]["measurement_complete"]


def test_private_adapter_reveals_only_current_case_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = golden_case(1)
    (tmp_path / "prompt-points.json").write_text("[]")
    for filename in ("agent/a.py", "strands/a.py", "openai/a.py"):
        source = tmp_path / filename
        source.parent.mkdir()
        source.write_text("# synthetic")
    identity = {
        "imported_files": {
            name: private.sha(tmp_path / name)
            for name in ("agent/a.py", "strands/a.py", "openai/a.py")
        }
    }
    process = Mock()
    monkeypatch.setattr(private.run.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(
        golden,
        "load_cases",
        Mock(side_effect=AssertionError("corpus enumeration forbidden")),
    )
    monkeypatch.setattr(
        ArtifactAgent,
        "receive",
        Mock(
            side_effect=[
                {"event": "ready"},
                {"event": "identity", "identity": identity},
            ]
        ),
    )
    send = Mock()
    monkeypatch.setattr(ArtifactAgent, "send", send)
    agent = ArtifactAgent(tmp_path, "synthetic-key", case=case, corpus_root=tmp_path)
    try:
        assert send.call_args.args[0]["dates"] == {
            "current": case.frozen_time.date().isoformat()
        }
        assert case.id not in json.dumps(send.call_args.args[0])
    finally:
        agent.close()


def test_per_execution_reservations_use_five_dollars_remaining_and_stop_unknown(
    tmp_path: Path,
) -> None:
    journal = run.Journal(tmp_path / "budget", min(25, 23 + 5), 23)
    attempt = run.Attempt(id="synthetic-1", case_id="synthetic", trial=1)
    reserved = journal.reserve(attempt, "agent", 100)
    journal.finish(attempt, "agent", reserved, None, 1)
    with pytest.raises(run.StopRun, match="unknown_usage"):
        journal.reserve(attempt, "actor", 100)
    assert journal.limit == 25 and journal.unknown_usage


def test_missing_history_requires_explicit_initialization(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit prior accounting"):
        private.load_history(tmp_path / "missing.json")


def test_exported_summary_matches_release_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import golden_gate as gate

    entry = execution(tmp_path / "original", count=300)
    policy = private.read(golden.V2 / "eval/results/golden/policy-4.0.0.json")
    limits = policy["policy"]
    limits.update(
        holdout_sha256="c" * 64,
        evaluator_sha256=private.evaluator_identity(),
        calibration_sha256="e" * 64,
    )
    policy["approval"] = {
        "status": "approved",
        "evidence_sha256": golden.digest(limits),
        "reviewer": "synthetic",
        "approved_at": "2026-09-27T00:00:00+00:00",
        "evidence": "synthetic",
    }
    policy_path = tmp_path / "policy.json"
    private.write(policy_path, policy)
    assert private.policy_limits(policy_path) == limits
    monkeypatch.setattr(gate, "POLICY", policy_path)
    manifest = private.read(tmp_path / "original/manifest.json")
    manifest["policy_sha256"] = golden.digest(limits)
    private.write(tmp_path / "original/manifest.json", manifest)
    approval = review(
        tmp_path / "review.json", private.report_evidence(tmp_path / "original")
    )
    summary = private.summary(tmp_path / "original", [entry], approval)
    gate.validate_summary(summary, limits)
    assert gate.decision(summary) == {"qualified": True, "errors": []}


def test_private_corpus_rejects_another_kit_before_reading_cases(
    tmp_path: Path,
) -> None:
    private.write(tmp_path / "manifest.json", {"kit_sha256": "0" * 64})
    with (
        pytest.raises(ValueError, match="different evaluator kit"),
        private.private_corpus(tmp_path),
    ):
        raise AssertionError("mismatched kit admitted")


def test_recovered_completion_preserves_known_start_time(tmp_path: Path) -> None:
    entry = execution(tmp_path / "original", count=300)
    (tmp_path / "original/completed.json").unlink()
    private.render(tmp_path / "original", [entry], None)
    summary = private.read(tmp_path / "original/summary.json")
    assert (
        summary["attempts"][0]["completed_at"] == summary["attempts"][0]["started_at"]
    )


@pytest.mark.parametrize(
    "changed",
    [
        "eval/holdout_container/guide_data.py",
        "eval/holdout_container/runtime.py",
        "scripts/golden_gate.py",
        "scripts/cost_dashboard_release.py",
        "agent_tools/get_current_toll_price.py",
    ],
)
def test_changed_evaluator_source_cannot_reinterpret_prior_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    from eval.holdout_container import guide_data

    source = tmp_path / "evaluator"
    for name in private.SOURCES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(golden.V2 / name, target)
    monkeypatch.setattr(golden, "V2", source)
    before = private.evaluator_identity()
    output = tmp_path / "output"
    output.mkdir()
    entry = execution(output / "original", count=0)
    private.write(
        output / "history.json",
        {
            "version": 1,
            "prior_cost_usd": 0,
            "prior_unknown_usage": False,
            "executions": [entry],
        },
    )
    with (source / changed).open("a") as stream:
        stream.write("\n# Synthetic code revision.\n")
    assert private.evaluator_identity() != before
    assert private.load_history(output / "history.json") == [entry]
    assert private.spending([entry]) == (0, False)
    with pytest.raises(ValueError, match="original reviewed packet"):
        private.summary(output / "original", [entry], None)
    approval = review(
        tmp_path / "replacement-review.json",
        private.report_evidence(output / "original"),
        replacement_reason="infrastructure",
    )
    with pytest.raises(ValueError, match="original reviewed packet"):
        private.replacement_reason([entry], context(), "c" * 64, approval)
    replacement = execution(output / "replacement", count=0, reason="infrastructure")
    with pytest.raises(ValueError, match="original reviewed packet"):
        private.summary(output / "replacement", [entry, replacement], None)
    (output / "original/completed.json").unlink()
    with pytest.raises(ValueError, match="original reviewed packet"):
        private.render(output / "original", [entry], None)
    with pytest.raises(ValueError, match="original reviewed packet"):
        guide_data.result_directory(output, "original", "candidate", recover=True)
    assert not (output / "original/completed.json").exists()
    assert not (output / "original/summary.json").exists()

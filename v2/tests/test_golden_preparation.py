"""Preparation is private, reproducible, and cannot bypass application gates."""

import hashlib
import json
import sys
import tarfile
from pathlib import Path

import pytest

from eval import corpus, golden
from eval import golden_run as run


@pytest.mark.parametrize("mode", ["run", "render", "calibrate"])
def test_preparation_requires_combined_calibration(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            mode,
            "--output",
            str(tmp_path / "out"),
            "--allow-uncommitted-preparation",
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        run.main()
    assert not (tmp_path / "out").exists()


def test_preparation_hashes_and_preserves_actual_sources(
    golden_test_identity: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "v2/tests/test_golden_preparation.py"
    calls: list[tuple[str, ...]] = []

    def git(*args: str) -> str:
        calls.append(args)
        if args[0] == "status":
            return "?? " + source
        if args[0] == "ls-files":
            return source + "\0"
        return "a" * 40

    monkeypatch.setattr(run, "git", git)
    cases = golden.load_cases()
    with pytest.raises(ValueError, match="clean committed"):
        run.identity(cases)
    pinned = run.identity(cases, allow_uncommitted_preparation=True)
    expected = hashlib.sha256((golden.V2.parent / source).read_bytes()).hexdigest()
    assert pinned["preparation"] == {
        "status": "dirty",
        "base_commit": "a" * 40,
        "source_hashes": {source: expected},
    }
    assert pinned["artifact_sha256"] == golden.digest({source: expected})
    assert any("--others" in args and "--exclude-standard" in args for args in calls)
    run.validate_identity(pinned)
    run.snapshot_preparation(pinned, tmp_path)
    with tarfile.open(tmp_path / "source-snapshot.tar.gz") as archive:
        stream = archive.extractfile(source)
        assert stream is not None
        assert hashlib.sha256(stream.read()).hexdigest() == expected
    pinned["preparation"]["source_hashes"][source] = "0" * 64
    with pytest.raises(ValueError, match="preparation source identity"):
        run.validate_identity(pinned)
    with pytest.raises(ValueError, match="source changed"):
        run.snapshot_preparation(pinned, tmp_path)


def test_preparation_snapshot_stays_external() -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        run.snapshot_preparation({"preparation": {"source_hashes": {}}}, golden.V2)


def test_lost_usage_ceiling_is_bound_and_preparation_only(tmp_path: Path) -> None:
    manifest = {
        "mode": "calibrate",
        "run_id": "synthetic",
        "prior_spend_usd": 10,
        "identity": {
            "artifact_kind": "uncommitted_preparation",
            "corpus": {"evaluation_scope": "suite"},
        },
    }
    events = [
        {
            "event": "model_started",
            "attempt": "a",
            "role": "judge",
            "reserved_usd": 0.03,
        },
        {
            "event": "model_finished",
            "attempt": "a",
            "role": "judge",
            "complete": False,
            "cost_usd": 0.03,
        },
    ]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "events.jsonl").write_text("\n".join(map(json.dumps, events)))
    receipt = run.preparation_usage_ceiling(manifest, events)
    path = tmp_path / "usage-ceiling.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="unknown usage"):
        run.prior_accounting(tmp_path)
    assert run.prior_accounting(tmp_path, allow_preparation_ceiling=True)[1] == 10.03
    assert events[-1]["complete"] is False
    receipt["charges"][0]["ceiling_usd"] = 0.02
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="unknown usage"):
        run.prior_accounting(tmp_path, allow_preparation_ceiling=True)
    events[-1]["cost_usd"] = 0.02
    with pytest.raises(ValueError, match="full reservation"):
        run.preparation_usage_ceiling(manifest, events)
    events[-1]["cost_usd"] = 0.03
    with pytest.raises(ValueError, match="closed lost-usage"):
        run.preparation_usage_ceiling(manifest, events[:1])
    manifest["mode"] = "run"
    with pytest.raises(ValueError, match="all-split preparation"):
        run.preparation_usage_ceiling(manifest, events)


def test_valid_disclosure_citation_keeps_same_line_financial_error() -> None:
    answer = (
        "Vehicle cost assumes $0.685 per straight-line tolled mile. "
        "The annual toll alone is $1500."
    )
    violation = run.UnmetRequirement(
        requirement="Preserve financial meaning.",
        evidence="The receipt's $1500 additional gross income is not its $500 toll.",
    )
    assessment = run.OutcomeAssessment(
        disclosures=[
            run.DisclosureAssessment(
                requirement_id="vehicle_assumption", line_ids=["turn_1.line_1"]
            )
        ],
        outcome=run.RequirementAssessment(
            evidence=violation.evidence, unmet_requirements=[violation]
        ),
        actor_validity=run.ActorAssessment(
            status="valid", evidence="Consistent driver"
        ),
    )
    verdict = run.disclosure_verdict(
        assessment,
        {"vehicle_assumption": "Disclose the vehicle rate."},
        [golden.Turn(user="Annual estimate please", response=answer, calls=[])],
    )
    evidence = json.loads(verdict.evidence)
    assert not verdict.passed
    assert evidence["unmet_requirements"] == [violation.model_dump()]
    assert evidence["disclosures"][0]["quotes"][0]["quote"] == answer


@pytest.mark.parametrize("split", ["training", "shadow"])
def test_prepared_public_inputs_include_modeled_history(split: str) -> None:
    root = corpus.PUBLIC / split
    receipts = [
        golden.load_fixture(step.fixture, root).result
        for case in golden.load_cases(root)
        for step in case.steps
    ]
    assert any(receipt.get("uses_modeled") is True for receipt in receipts)

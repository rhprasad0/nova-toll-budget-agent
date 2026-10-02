"""Synthetic factory regressions: privacy, binding, denominators, and history."""

from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import tarfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from eval import golden
from eval import golden_run as run
from eval.factory import factory as f
from eval.factory import kit, smoke
from eval.factory.source_agent import SourceAgent


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden")
    ):
        return smoke.prepared(tmp_path_factory.mktemp("factory-template"))


@pytest.fixture
def factory(prepared: tuple[Path, str], tmp_path: Path) -> tuple[Path, str]:
    root, source_id = prepared
    work = tmp_path / "work"
    shutil.copytree(root, work)
    return work, source_id


def application(
    factory: tuple[Path, str], role: str = "candidate"
) -> tuple[Path, str, dict[str, Any]]:
    root, source_id = factory
    run_id = f.evaluate(root, "4.0.0", source_id, role, mock=True)
    return root, run_id, f.application(root, run_id)[1]


def replace_report(root: Path, run_id: str, report: dict[str, Any]) -> None:
    report["evidence_sha256"] = kit.digest(
        {k: v for k, v in report.items() if k != "evidence_sha256"}
    )
    (root / "runs" / run_id / "report.json").write_text(json.dumps(report))


def assessment(blind: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_sha256": blind["audit_sha256"],
        "reviewer": "Test",
        "evidence": "Offline synthetic review",
        "items": [
            {
                "token": i["token"],
                **dict.fromkeys(f.DIMENSIONS, True),
                "actor_validity": "valid",
                "evidence": "Synthetic assessment",
            }
            for i in blind["items"]
        ],
    }


def test_allocations_settings_and_one_full_calibration(
    factory: tuple[Path, str],
) -> None:
    root, _ = factory
    directory, manifest = f.suite(root, "4.0.0")
    assert [manifest["splits"][s]["count"] for s in f.SPLITS] == [100, 50, 10]
    calibration = f.checked_report(directory / "calibration/report.json")
    assert len(calibration["rows"]) == 180 and len(calibration["actor_check"]) == 160
    assert f.CONTRACT["settings"]["actor_params"] == run.EVAL_MODEL_PARAMS
    assert f.CONTRACT["settings"]["judge_params"] == run.JUDGE_MODEL_PARAMS
    with pytest.raises(FileExistsError):
        f.calibrate(root, "4.0.0", mock=True)


@pytest.mark.parametrize(
    "change", ["allocation", "group", "duplicate", "actor", "time", "reference"]
)
def test_input_validation(factory: tuple[Path, str], change: str) -> None:
    root, _ = factory
    path = root / "drafts/holdout/cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "allocation":
        cases[0]["kind"] = "annual"
    elif change == "group":
        cases[0]["split_group"] = "smoke-training-001"
    elif change == "duplicate":
        cases[0]["prompt"] = cases[1]["prompt"]
    elif change == "actor":
        cases[0]["actor"]["facts"] += " Use get_current_toll_price."
    elif change == "time":
        cases[0]["frozen_time"] = "2026-10-01T08:00:00"
    else:
        examples_path = root / "drafts/holdout/examples.json"
        examples_path.write_text(json.dumps(json.loads(examples_path.read_text())[1:]))
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    with pytest.raises(ValueError):
        f.validate_splits(root / "drafts")


def test_frozen_file_and_calibration_review_bindings(factory: tuple[Path, str]) -> None:
    root, _ = factory
    review_path = root / "suites/4.0.0/calibration/review.json"
    review = f.read(review_path)
    review["evidence_sha256"] = "f" * 64
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="calibration"):
        f.measurement(root, "4.0.0")
    (root / "suites/4.0.0/holdout/cases.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="frozen inputs"):
        f.suite(root, "4.0.0")


def test_deterministic_coverage_audit_selection(factory: tuple[Path, str]) -> None:
    _, _, report = application(factory)
    selected = f.audit_selection(report)
    shuffled = deepcopy(report)
    shuffled["attempts"].reverse()
    assert f.audit_selection(shuffled) == selected
    keys = [(r["case_id"], r["trial"]) for r in selected]
    assert keys == sorted(set(keys))
    assert ("smoke-holdout-001", 3) in keys
    cases = {c["id"]: c for c in report["manifest"]["identity"]["cases"]}
    for family in f.CONTRACT["splits"]["holdout"]["coverage"]:
        for success in (True, False):
            eligible = sorted(
                (r["case_id"], r["trial"])
                for r in report["attempts"]
                if r["status"] == "scored"
                and r["overall_success"] == success
                and cases[r["case_id"]]["coverage_family"] == family
            )
            if eligible:
                assert eligible[0] in keys


def test_blinding_review_binding_and_immutable_assessments(
    factory: tuple[Path, str],
) -> None:
    root, run_id, report = application(factory)
    blind = f.audit(root, run_id)
    rendered = json.dumps(blind)
    for forbidden in (
        '"verdicts":',
        "overall_success",
        "measurement_complete",
        "source_sha256",
        report["source"]["commit"],
        run_id,
    ):
        assert forbidden not in rendered
    assert {"turns", "tool_contract", "requested_tools", "actor_replies"} <= blind[
        "items"
    ][0].keys()
    review = assessment(blind)
    stale = {**review, "audit_sha256": "a" * 64}
    with pytest.raises(ValueError, match="binding"):
        f.assessments(root, run_id, stale)
    missing = {**review, "items": review["items"][1:]}
    with pytest.raises(ValueError, match="all selected"):
        f.assessments(root, run_id, missing)
    reveal = f.assessments(root, run_id, review)
    assert reveal["application"] == report["source"]
    assert any(i["disagreements"] for i in reveal["items"])
    with pytest.raises(FileExistsError):
        f.assessments(root, run_id, review)
    assert f.application(root, run_id)[1] == report


def test_material_grading_defect_blocks_without_rewriting_scores(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, run_id, original = application(factory)
    blind = f.audit(root, run_id)
    reveal = f.assessments(root, run_id, assessment(blind))
    review = {
        "reveal_sha256": reveal["reveal_sha256"],
        "reviewer": "Test",
        "evidence": "Known grading defect",
        "dispositions": [
            {
                "id": i["id"],
                "dimension": key,
                "material": True,
                "disposition": "grading_defect",
                "evidence": "Repair in new calibration",
            }
            for i in reveal["items"]
            for key in i["disagreements"]
        ],
    }
    with pytest.raises(ValueError, match="every disagreement"):
        f.finish_audit(root, run_id, {**review, "dispositions": []})
    f.finish_audit(root, run_id, review)
    assert f.audit_status(root, run_id) == "blocked"
    exported = f.export_report(
        root, run_id, tmp_path / "aggregate.json", "Test", "Review"
    )
    assert (
        not exported["release_ready_evidence"] and exported["audit_status"] == "blocked"
    )
    assert f.application(root, run_id)[1] == original


def test_audit_approval_detects_changed_assessments(factory: tuple[Path, str]) -> None:
    root, run_id, _ = application(factory)
    smoke.audited(root, run_id)
    path = root / "runs" / run_id / "audit-assessments.json"
    review = f.read(path)
    review["items"][0]["outcome"] = False
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="stale"):
        f.audit_status(root, run_id)


@pytest.mark.parametrize("change", ["assessments", "binding"])
def test_disposition_rejects_rehashed_audit_edits(
    factory: tuple[Path, str], change: str
) -> None:
    root, run_id, _ = application(factory)
    blind = f.audit(root, run_id)
    reveal = f.assessments(root, run_id, assessment(blind))
    output = root / "runs" / run_id
    if change == "assessments":
        path = output / "audit-assessments.json"
        assessed = f.read(path)
        assessed["evidence"] = "Rewritten after seeing judge scores"
        for item, original in zip(assessed["items"], reveal["items"], strict=True):
            row = original["original"]
            item["actor_validity"] = row["actor_validity"]["status"]
            for key in f.DIMENSIONS:
                item[key] = row["verdicts"].get(key, {}).get("passed")
            original["assessment"] = item
            original["disagreements"] = []
        path.write_text(json.dumps(assessed))
        reveal["assessments_sha256"] = kit.digest(assessed)
        reveal["reveal_sha256"] = kit.digest(
            {k: v for k, v in reveal.items() if k != "reveal_sha256"}
        )
        (output / "audit-reveal.json").write_text(json.dumps(reveal))
    else:
        path = output / "audit-binding.json"
        binding = f.read(path)
        binding["mapping"][blind["items"][0]["token"]] = "changed"
        path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="stale"):
        f.finish_audit(
            root,
            run_id,
            {
                "reveal_sha256": reveal["reveal_sha256"],
                "reviewer": "Test",
                "evidence": "Attempt to approve changed initial review",
                "dispositions": [],
            },
        )
    assert not (output / "audit-review.json").exists()


def test_disclosures_are_exact_and_reuse_approvals_go_stale(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, run_id, report = application(factory)
    source_id = factory[1]
    f.approve_reuse(root, "4.0.0", source_id, "Test", "Next source approval")
    destination = tmp_path / "aggregate.json"
    f.export_report(root, run_id, destination, "Recipient", "Aggregate feedback")
    event = f.ledger(root)[-1]
    assert event["payload_sha256"] == kit.sha(destination.read_bytes())
    assert (
        event["recipient"] == "Recipient"
        and event["purpose"] == "Aggregate feedback"
        and event["timestamp"]
    )
    with pytest.raises(ValueError, match="fresh approval"):
        f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    f.disclose(root, run_id, "2" * 64, "Recipient", "Manual feedback", manual=True)
    assert f.ledger(root)[-1]["manual"]
    assert (
        f.reuse_status(root, report["measurement"]["holdout_sha256"])["disclosures"]
        == 2
    )
    f.approve_reuse(root, "4.0.0", source_id, "Test", "Fresh approval")
    f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    with pytest.raises(ValueError, match="fresh approval"):
        f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)


def test_holdout_history_survives_training_revision(factory: tuple[Path, str]) -> None:
    root, source_id = factory
    _, _, report = application(factory)
    path = root / "drafts/training/cases.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["expected_assertion"] += " Preserve route identity."
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    changed = f.freeze(
        root,
        root / "drafts",
        "4.0.1",
        {"training": "4.0.1", "holdout": "4.0.0", "shadow": "4.0.0"},
        smoke=True,
    )
    assert (
        changed["splits"]["holdout"]["sha256"]
        == report["measurement"]["holdout_sha256"]
    )
    assert f.reuse_status(root, changed["splits"]["holdout"]["sha256"])["attempts"] == 1
    calibration = f.calibrate(root, "4.0.1", mock=True)
    f.review_calibration(
        root,
        "4.0.1",
        {
            "evidence_sha256": calibration["evidence_sha256"],
            "reviewer": "Test",
            "evidence": "Synthetic",
            "dispositions": [],
        },
    )
    with pytest.raises(ValueError, match="fresh approval"):
        f.evaluate(root, "4.0.1", source_id, "candidate", mock=True)


def test_missing_slots_fixed_denominator_and_invalid_scores(
    factory: tuple[Path, str],
) -> None:
    root, run_id, report = application(factory)
    assert (
        report["overall"]["expected_trials"] == 150
        and report["overall"]["expected_cases"] == 50
    )
    assert report["overall"]["inconclusive_trials"] == 1
    missing = deepcopy(report)
    missing["attempts"].pop()
    summary = f.summarize(missing["manifest"]["identity"]["cases"], missing["attempts"])
    assert (
        summary["expected_trials"] == 150
        and summary["missing_trials"] == 1
        and not summary["complete"]
    )
    with pytest.raises(ValueError, match="duplicate"):
        f.summarize(
            report["manifest"]["identity"]["cases"],
            report["attempts"] + [report["attempts"][0]],
        )
    report["attempts"][0]["overall_success"] = not report["attempts"][0][
        "overall_success"
    ]
    replace_report(root, run_id, report)
    with pytest.raises(ValueError, match="success"):
        f.application(root, run_id)


def paired(factory: tuple[Path, str]) -> tuple[Path, str, str]:
    root, source_id = factory
    incumbent = f.evaluate(root, "4.0.0", source_id, "incumbent", mock=True)
    smoke.audited(root, incumbent)
    f.approve_reuse(root, "4.0.0", source_id, "Test", "Candidate reuse")
    candidate = f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    smoke.audited(root, candidate)
    return root, incumbent, candidate


def test_incumbent_reuse_grouped_uncertainty_and_export_privacy(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, incumbent, candidate = paired(factory)
    private = f.comparison(root, candidate, incumbent)
    assert len(private["private_case_differences"]) == 50
    aggregate = private["aggregate"]
    assert aggregate["scenario_groups"] == 50
    assert aggregate["baseline"]["slots"] == aggregate["final"]["slots"] == 150
    assert aggregate["mean_paired_case_delta"] == pytest.approx(
        aggregate["successful_trial_delta"] / 150
    )
    assert len(aggregate["intervals_percent"]["delta"]) == 2
    assert sum(aggregate["final"]["case_success_histogram"]) == 50
    exported = f.export_report(
        root, candidate, tmp_path / "aggregate.json", "Test", "Comparison", incumbent
    )
    rendered = json.dumps(exported)
    assert all(
        name not in rendered
        for name in (
            "smoke-holdout",
            "Testtown",
            "private_case_differences",
            "turns",
            "dispositions",
        )
    )
    assert exported["comparison"] == aggregate
    f.approve_reuse(root, "4.0.0", factory[1], "Test", "Later candidate")
    later = f.evaluate(root, "4.0.0", factory[1], "candidate", mock=True)
    smoke.audited(root, later)
    assert f.comparison(root, later, incumbent)["aggregate"] == aggregate
    with pytest.raises(ValueError, match="incumbent already"):
        f.evaluate(root, "4.0.0", factory[1], "incumbent", mock=True)


@pytest.mark.parametrize("change", ["identity", "missing", "duplicate", "usage"])
def test_reject_incompatible_or_incomplete_comparison(
    factory: tuple[Path, str], change: str
) -> None:
    root, incumbent, candidate = paired(factory)
    path, report = f.application(root, candidate)
    if change == "identity":
        report["measurement"]["calibration_sha256"] = "f" * 64
    elif change == "missing":
        report["attempts"].pop()
        report["overall"] = f.summarize(
            report["manifest"]["identity"]["cases"], report["attempts"]
        )
    elif change == "duplicate":
        report["attempts"].append(report["attempts"][0])
    else:
        attempt = run.Attempt.model_validate(
            {
                k: v
                for k, v in report["attempts"][0].items()
                if k in run.Attempt.model_fields
            }
        )
        attempt.measurements[0].complete = False
        report["attempts"][0] = f.application_row(attempt)
        report["overall"] = f.summarize(
            report["manifest"]["identity"]["cases"], report["attempts"]
        )
    replace_report(root, candidate, report)
    with pytest.raises(ValueError):
        f.comparison(root, candidate, incumbent)
    assert path.is_dir()


def test_public_suite_export_excludes_holdout_evidence(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, _ = factory
    output = tmp_path / "public.zip"
    f.export_suite(root, "4.0.0", output)
    with ZipFile(output) as archive:
        assert any(name.startswith("training/") for name in archive.namelist())
        assert any(name.startswith("shadow/") for name in archive.namelist())
        assert not any(name.startswith("holdout/") for name in archive.namelist())
        assert all(
            b"smoke-holdout" not in archive.read(name) for name in archive.namelist()
        )


def test_clean_allowlisted_handoff_and_snapshot_tampering(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, source_id = factory
    directory, _ = f.source(root, source_id)
    assert {
        str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()
    } == {*kit.APPLICATION, "snapshot.json"}
    (directory / "agent/toll_agent.py").write_text("tampered")
    with pytest.raises(ValueError, match="snapshot changed"):
        f.source(root, source_id)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "untracked").touch()
    with pytest.raises(ValueError, match="clean and committed"):
        kit.snapshot(repo, tmp_path / "dirty.zip")


def test_backup_restore_excludes_agent_auth_and_rejects_traversal(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, _ = factory
    auth = root.parent / "agent-state"
    auth.mkdir()
    (auth / "auth.json").write_text("synthetic authentication sentinel")
    archive = tmp_path / "backup.tar.gz"
    f.backup(root, archive)
    with tarfile.open(archive) as packed:
        assert all(
            "agent-state" not in member.name and "auth.json" not in member.name
            for member in packed
        )
    restored = tmp_path / "restored"
    restored.mkdir()
    f.restore(restored, archive)
    assert f.ledger(restored) == f.ledger(root)
    assert f.suite(restored, "4.0.0")[1] == f.suite(root, "4.0.0")[1]
    with pytest.raises(ValueError, match="fresh empty"):
        f.restore(restored, archive)
    malicious = tmp_path / "malicious.tar.gz"
    with tarfile.open(malicious, "w:gz") as packed:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        packed.addfile(member, io.BytesIO(b"x"))
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with pytest.raises(ValueError, match="unsafe"):
        f.restore(fresh, malicious)


@pytest.mark.parametrize("change", ["rewrite", "rechain", "truncate", "delete"])
def test_ledger_detects_changed_committed_history(
    factory: tuple[Path, str], change: str
) -> None:
    root, source_id = factory
    path = root / "ledger.jsonl"
    prefix = path.read_bytes()
    f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    events = f.ledger(root)
    if change == "truncate":
        path.write_bytes(prefix)
    elif change == "delete":
        path.unlink()
    else:
        events[0]["timestamp"] = "changed"
        if change == "rechain":
            previous = "0" * 64
            for event in events:
                event["previous"] = previous
                event["sha256"] = kit.digest(
                    {k: v for k, v in event.items() if k != "sha256"}
                )
                previous = event["sha256"]
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(ValueError, match="history changed"):
        f.ledger(root)
    with pytest.raises(ValueError, match="history changed"):
        f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)


def test_no_paid_or_mock_work_without_correct_authorization(
    factory: tuple[Path, str],
) -> None:
    root, _ = factory
    _, manifest = f.suite(root, "4.0.0")
    with pytest.raises(ValueError, match="paid work requires"):
        f.paid_guard(manifest, False, 25, "")
    manifest["synthetic_smoke"] = False
    with pytest.raises(ValueError, match="mock measurements"):
        f.paid_guard(manifest, True, None, "")
    for invalid in (None, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="authorized finite budget"):
            f.paid_guard(manifest, False, invalid, "Test authorization")


@pytest.mark.parametrize(
    "model_change",
    [
        None,
        ('model_id="gpt-6-luna"', 'model_id="gpt-6-astra"'),
        ('"max_output_tokens": 2048', '"max_output_tokens": 8192'),
        ('"effort": "low"', '"effort": "medium"'),
    ],
)
def test_source_worker_real_protocol_with_canned_provider(
    factory: tuple[Path, str], tmp_path: Path, model_change: tuple[str, str] | None
) -> None:
    root, source_id = factory
    original, _ = f.source(root, source_id)
    bundle = tmp_path / "canned-source"
    shutil.copytree(original, bundle)
    # Exercise the actual Strands application, SDK, subprocess protocol and replay.
    fixture = json.loads((kit.HERE / "examples/fixtures.json").read_text())
    case = golden.GoldenCase.model_validate_json(
        (kit.HERE / "examples/cases.jsonl").read_text().splitlines()[0]
    )
    corpus = tmp_path / "corpus"
    (corpus / "fixtures").mkdir(parents=True)
    shutil.copyfile(
        kit.HERE / "examples/prompt-points.json", corpus / "prompt-points.json"
    )
    for name, value in fixture.items():
        (corpus / "fixtures" / name).write_text(json.dumps(value))
    first = fixture[case.steps[0].fixture]
    module = bundle / "agent/toll_agent.py"
    if model_change:
        source_text = module.read_text()
        assert source_text.count(model_change[0]) == 1
        module.write_text(source_text.replace(*model_change))
    with module.open("a") as stream:
        stream.write(
            "\nimport socket as _smoke_socket\n_smoke_socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden'))\n"
        )
        stream.write("_original_smoke_model = _build_model\n")
        stream.write(f"_smoke_fixture = {first!r}\n")
        stream.write("""
def _build_model():
    model = _original_smoke_model()
    calls = 0
    async def scripted(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if calls == 1:
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "frozen", "name": _smoke_fixture["tool"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": __import__("json").dumps(_smoke_fixture["input"])}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": "Supported frozen quote."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}, "metrics": {"latencyMs": 1}}}
    model.stream = scripted
    return model
""")
    attempt = run.Attempt(
        id="protocol",
        case_id=case.id,
        trial=1,
        turns=[golden.Turn(user=case.prompt, response="pending", calls=[])],
    )
    messages = [case.prompt]
    journal = run.Journal(tmp_path / "protocol-run", 1)
    with patch.object(golden, "ROOT", corpus):
        if model_change:
            with pytest.raises(run.StopRun, match="source_model_config"):
                SourceAgent(
                    bundle, "synthetic-secret", case, attempt, journal, messages
                )
            assert journal.spent == 0 and not attempt.measurements
            return
        worker = SourceAgent(
            bundle, "synthetic-secret", case, attempt, journal, messages
        )
        try:
            answer = worker(case.prompt)
            assert str(answer).strip() == "Supported frozen quote."
            assert len(attempt.turns[0].calls) == 1
            assert len(attempt.measurements) == 2 and all(
                m.complete for m in attempt.measurements
            )
            assert (
                "synthetic-secret"
                not in (journal.directory / "events.jsonl").read_text()
            )
        finally:
            worker.close()

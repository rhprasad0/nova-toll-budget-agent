"""Synthetic guided journey: no private data, credentials, network or model calls."""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from eval import golden
from eval import private_holdout as private
from eval.holdout_container import guide_data as guide
from tests.test_holdout_authoring import rehearsal, write_payload
from tests.test_private_holdout import execution, synthetic_bundle


def workstation(tmp_path: Path) -> dict[str, Path]:
    paths = {key: tmp_path / key for key in ("corpus", "guide", "output", "inputs")}
    for directory in paths.values():
        directory.mkdir()
    write_payload(paths["corpus"])
    rehearsal(paths["corpus"])
    return paths


def freeze(paths: dict[str, Path]) -> dict[str, Any]:
    dispatch = partial(guide.dispatch, **paths)
    review = dispatch({"action": "review_cases"})
    assert len(review["batches"]) == 10
    for batch in review["batches"]:
        dispatch(
            {
                "action": "approve_cases",
                "batch": batch["batch"],
                "digest": review["digest"],
                "note": "Human reviewed these synthetic examples.",
            }
        )
    return dispatch(
        {
            "action": "freeze",
            "digest": review["digest"],
            "note": "Freeze the saved synthetic corpus.",
        }
    )


def preparation(paths: dict[str, Path], identities: dict[str, Any]) -> None:
    directory = paths["output"] / "prep-001"
    directory.mkdir()
    cases = [c.id for c in golden.load_cases(paths["corpus"])]
    references = json.loads((paths["corpus"] / "examples.json").read_bytes())
    reference_ids = [f"{r['case_id']}-{r['label']}" for r in references]
    manifest = {
        "run_id": "synthetic-preparation",
        "mode": "prepare",
        "started_at": "2026-09-27T01:00:00+00:00",
        "holdout_sha256": identities["holdout_sha256"],
        "evaluator_sha256": private.evaluator_identity(),
        "bundle_digest": private.read(paths["inputs"] / "context.json")[
            "bundle_digest"
        ],
        "case_ids": cases,
        "reference_ids": reference_ids,
    }
    private.write(directory / "manifest.json", manifest)
    private.write(
        directory / "completed.json", {"completed_at": "2026-09-27T02:00:00+00:00"}
    )
    events: list[dict[str, Any]] = [
        {
            "event": "calibration",
            "id": reference,
            "measurement_complete": True,
            "disagreements": [],
        }
        for reference in reference_ids
    ]
    events.extend(
        {"event": "actor_check", "case_id": case, "trial": trial, "status": "scored"}
        for case in cases
        for trial in (1, 2, 3)
    )
    (directory / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )
    ledger = private.read(paths["output"] / "history.json")
    ledger["executions"].append(
        {
            **{
                key: manifest[key]
                for key in (
                    "run_id",
                    "mode",
                    "holdout_sha256",
                    "evaluator_sha256",
                    "bundle_digest",
                )
            },
            "directory": str(directory),
        }
    )
    private.write(paths["output"] / "history.json", ledger)


def test_complete_synthetic_journey_and_validity_replacement(tmp_path: Path) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    frozen = freeze(paths)
    dispatch(
        {"action": "init_history", "prior_cost_usd": 1.25, "prior_unknown_usage": False}
    )
    context = synthetic_bundle(paths["inputs"] / "release.zip")
    private.write(paths["inputs"] / "context.json", context)
    policy = private.read(golden.V2 / "eval/results/golden/policy-4.0.0.json")
    private.write(paths["inputs"] / "policy.json", policy)
    assert dispatch({"action": "validate_input"})["context"] == context
    plan = dispatch(
        {
            "action": "evaluation_plan",
            "mode": "prepare",
            "note": "I authorize preparation up to $5.",
        }
    )
    assert plan["run"] == "prep-001" and plan["arguments"][:2] == [
        "evaluate",
        "prepare",
    ]
    assert plan["spent_usd"] == 1.25 and plan["execution_limit_usd"] == 5
    preparation(paths, frozen)
    report = dispatch(
        {"action": "review_result", "kind": "calibration", "run": "prep-001"}
    )
    assert report["summary"]["complete"]
    assert "actor_rehearsal" not in report["summary"]
    dispatch(
        {
            "action": "approve_result",
            "kind": "calibration",
            "run": "prep-001",
            "digest": report["digest"],
            "note": "Reviewed calibration and every actor rehearsal.",
        }
    )
    identities = dispatch({"action": "identities"})
    assert set(identities) == {
        "holdout_sha256",
        "evaluator_sha256",
        "calibration_sha256",
    }
    policy["policy"].update(identities)
    policy["approval"] = {
        **guide.approval(
            golden.digest(policy["policy"]), "Synthetic repository policy approval."
        ),
        "approved_at": "2026-09-27T00:00:00+00:00",
    }
    private.write(paths["inputs"] / "policy.json", policy)
    plan = dispatch(
        {
            "action": "evaluation_plan",
            "mode": "run",
            "note": "I authorize scored evaluation up to $5.",
        }
    )
    assert plan["run"] == "run-001" and "--calibration-review" in plan["arguments"]
    entry = execution(paths["output"] / "run-001", count=240)
    manifest_path = paths["output"] / "run-001/manifest.json"
    manifest = private.read(manifest_path)
    manifest.update(
        identities,
        context=context,
        bundle_digest=context["bundle_digest"],
        policy_sha256=golden.digest(policy["policy"]),
    )
    private.write(manifest_path, manifest)
    entry.update({key: manifest[key] for key in entry if key != "directory"})
    ledger = private.read(paths["output"] / "history.json")
    ledger["executions"].append(entry)
    private.write(paths["output"] / "history.json", ledger)
    report = dispatch(
        {"action": "review_result", "kind": "candidate", "run": "run-001"}
    )
    assert report["summary"]["unmeasured"] == 60
    dispatch(
        {
            "action": "approve_result",
            "kind": "candidate",
            "run": "run-001",
            "digest": report["digest"],
            "note": "Reviewed full scored evidence and missing measurements.",
        }
    )
    summary = dispatch({"action": "summary", "run": "run-001"})
    assert summary["private_review_complete"] and summary["cumulative_cost_usd"] >= 1.25
    assert "rehearsal-1" not in json.dumps(summary)
    with pytest.raises(ValueError, match="explicitly reviewed validity replacement"):
        dispatch(
            {
                "action": "evaluation_plan",
                "mode": "run",
                "note": "Repeat scored evaluation.",
            }
        )
    replacement_request = {
        "action": "evaluation_plan",
        "mode": "run",
        "replacement_reason": "infrastructure",
        "note": "Authorize the one validity replacement for missing measurements.",
    }
    replacement_receipt = paths["output"] / "reviews/replacement-run-002.json"
    private.write(manifest_path, {**manifest, "evaluator_sha256": "0" * 64})
    ledger["executions"][-1]["evaluator_sha256"] = "0" * 64
    private.write(paths["output"] / "history.json", ledger)
    with pytest.raises(ValueError, match="original reviewed packet"):
        dispatch(replacement_request)
    assert not replacement_receipt.exists()
    private.write(manifest_path, manifest)
    ledger["executions"][-1]["evaluator_sha256"] = manifest["evaluator_sha256"]
    private.write(paths["output"] / "history.json", ledger)
    original_review = guide.review_path(paths["output"], "candidate", "run-001")
    approved = private.read(original_review)
    private.write(original_review, {**approved, "status": "rejected"})
    with pytest.raises(ValueError, match="human review must approve"):
        dispatch(replacement_request)
    assert not replacement_receipt.exists()
    private.write(original_review, approved)
    replacement = dispatch(replacement_request)
    assert (
        replacement["run"] == "run-002"
        and "--replacement-review" in replacement["arguments"]
    )
    with pytest.raises(ValueError, match="preparation already exists"):
        dispatch(
            {"action": "evaluation_plan", "mode": "prepare", "note": "Prepare again."}
        )
    with pytest.raises(FileExistsError):
        dispatch(
            {
                "action": "init_history",
                "prior_cost_usd": 0,
                "prior_unknown_usage": False,
            }
        )
    assert private.read(paths["output"] / "history.json")["prior_cost_usd"] == 1.25


def test_reviews_track_all_payload_and_freeze_recovery(tmp_path: Path) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    review = dispatch({"action": "review_cases"})
    request = {
        "action": "approve_cases",
        "batch": 1,
        "digest": review["digest"],
        "note": "Approved.",
    }
    dispatch(request)
    examples = paths["corpus"] / "examples.json"
    examples.write_text(examples.read_text() + "\n")
    with pytest.raises(ValueError, match="content changed"):
        dispatch(request)
    assert dispatch({"action": "status"})["approved_batches"] == 0
    frozen = freeze(paths)
    (paths["guide"] / "freeze.json").unlink()
    assert dispatch({"action": "status"})["phase"] == "recovery"
    with pytest.raises(ValueError, match="freeze and review"):
        dispatch(
            {
                "action": "init_history",
                "prior_cost_usd": 0,
                "prior_unknown_usage": False,
            }
        )
    assert freeze(paths)["holdout_sha256"] == frozen["holdout_sha256"]
    examples.write_text(examples.read_text() + "\n")
    with pytest.raises(ValueError, match="frozen reviewed corpus changed"):
        dispatch({"action": "status"})


def test_review_snapshot_cannot_mix_a_live_edit_with_the_approved_digest(
    tmp_path: Path,
) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    source = paths["corpus"] / "cases.jsonl"
    original = source.read_bytes()
    records = [json.loads(line) for line in original.splitlines()]
    records[0]["title"] = "Changed only while review pages load cases"
    changed = b"".join(json.dumps(row).encode() + b"\n" for row in records)
    load = golden.load_cases
    calls = 0

    def edit_while_reading(root: Path | None = None) -> list[golden.GoldenCase]:
        nonlocal calls
        calls += 1
        if calls == 3:
            source.write_bytes(changed)
            try:
                return load(root)
            finally:
                source.write_bytes(original)
        return load(root)

    with patch.object(golden, "load_cases", side_effect=edit_while_reading):
        review = dispatch({"action": "review_cases"})
    assert calls >= 3
    assert (
        "Changed only while review pages load cases"
        not in (paths["guide"] / "pages" / review["batches"][0]["page"]).read_text()
    )
    assert review["digest"] == guide.corpus_digest(paths["corpus"])
    source.write_bytes(changed)
    with pytest.raises(ValueError, match="case content changed"):
        dispatch(
            {
                "action": "approve_cases",
                "batch": 1,
                "digest": review["digest"],
                "note": "Approve displayed cases.",
            }
        )
    changed_review = dispatch({"action": "review_cases"})
    assert changed_review["batches"][0]["page"] != review["batches"][0]["page"]
    assert (
        "Changed only while review pages load cases"
        not in (paths["guide"] / "pages" / review["batches"][0]["page"]).read_text()
    )
    assert (
        "Changed only while review pages load cases"
        in (paths["guide"] / "pages" / changed_review["batches"][0]["page"]).read_text()
    )


def test_review_rejects_changes_before_presenting_and_snapshot_rejects_links(
    tmp_path: Path,
) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    render = guide.page

    def edit_after_render(
        directory: Path,
        filename: str,
        title: str,
        digest: str,
        sections: list[tuple[str, Any]],
    ) -> None:
        render(directory, filename, title, digest, sections)
        with (paths["corpus"] / "examples.json").open("a") as stream:
            stream.write("\n")

    with (
        patch.object(guide, "page", side_effect=edit_after_render),
        pytest.raises(ValueError, match="changed while rendering"),
    ):
        dispatch({"action": "review_cases"})
    assert not (paths["guide"] / "presented").exists()
    fixture = paths["corpus"] / "examples.json"
    outside = tmp_path / "outside.json"
    fixture.rename(outside)
    fixture.symlink_to(outside)
    with pytest.raises(OSError):
        guide.snapshot_corpus(paths["corpus"], tmp_path / "snapshot")


def test_receipts_publish_atomically_without_overwriting_prior_approval(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "reviews/decision.json"
    with (
        patch.object(guide.os, "fsync", side_effect=OSError("simulated interruption")),
        pytest.raises(OSError, match="interruption"),
    ):
        guide.store(receipt, {"status": "approved"})
    assert not receipt.exists()
    assert list(receipt.parent.iterdir()) == []
    guide.store(receipt, {"status": "approved"})
    with pytest.raises(FileExistsError):
        guide.store(receipt, {"status": "changed"})
    assert guide.read(receipt) == {"status": "approved"}
    assert list(receipt.parent.iterdir()) == [receipt]


def test_interrupted_manifest_publish_leaves_no_temporary_corpus_payload(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "corpus/manifest.json"
    code = """
import os, sys
from pathlib import Path
from eval.holdout_container import guide_data
publish = os.link
def interrupted(source, destination):
    publish(source, destination)
    os._exit(19)
os.link = interrupted
guide_data.store(Path(sys.argv[1]), {"synthetic": True})
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(manifest)], cwd=golden.V2, check=False
    )
    assert result.returncode == 19
    assert guide.read(manifest) == {"synthetic": True}
    assert list(manifest.parent.iterdir()) == [manifest]


def test_phase_requires_intact_frozen_receipt_before_evaluator_access(
    tmp_path: Path,
) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    assert dispatch({"action": "phase"}) == {"frozen": False, "needs_evaluator": False}
    freeze(paths)
    assert dispatch({"action": "phase"}) == {"frozen": True, "needs_evaluator": True}
    manifest = paths["corpus"] / "manifest.json"
    original = manifest.read_bytes()
    manifest.unlink()
    for action in ("phase", "status"):
        with pytest.raises(ValueError, match="manifest is missing"):
            dispatch({"action": action})
    manifest.write_bytes(original)
    receipt = paths["guide"] / "freeze.json"
    value = guide.read(receipt)
    for field, invalid in (
        ("status", "rejected"),
        ("reviewer", ""),
        ("evidence", None),
        ("approved_at", "not a time"),
        ("approved_at", "2026-01-01T00:00:00"),
        ("approved_at", "2999-01-01T00:00:00+00:00"),
    ):
        receipt.write_text(json.dumps({**value, field: invalid}))
        with pytest.raises(ValueError, match=r"human review|approval time"):
            dispatch({"action": "phase"})
    receipt.write_text(json.dumps(value))
    value["holdout_sha256"] = "0" * 64
    receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="freeze receipt differs"):
        dispatch({"action": "phase"})
    receipt.unlink()
    assert dispatch({"action": "phase"}) == {"frozen": True, "needs_evaluator": False}


def test_freeze_rejects_corrupted_case_approval_metadata(tmp_path: Path) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    review = dispatch({"action": "review_cases"})
    dispatch(
        {
            "action": "approve_cases",
            "batch": 1,
            "digest": review["digest"],
            "note": "Human approved this synthetic batch.",
        }
    )
    receipt = paths["guide"] / "reviews" / f"cases-001-{review['digest']}.json"
    record = guide.read(receipt)
    record.pop("reviewer")
    receipt.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="human review"):
        dispatch(
            {
                "action": "freeze",
                "digest": review["digest"],
                "note": "Freeze approved cases.",
            }
        )
    assert not (paths["corpus"] / "manifest.json").exists()


def test_incomplete_preparation_recovery_requires_review_and_explicit_paid_note(
    tmp_path: Path,
) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    frozen = freeze(paths)
    dispatch(
        {"action": "init_history", "prior_cost_usd": 2.5, "prior_unknown_usage": False}
    )
    private.write(
        paths["inputs"] / "context.json",
        synthetic_bundle(paths["inputs"] / "release.zip"),
    )
    private.write(
        paths["inputs"] / "policy.json",
        private.read(golden.V2 / "eval/results/golden/policy-4.0.0.json"),
    )
    preparation(paths, frozen)
    events = paths["output"] / "prep-001/events.jsonl"
    events.write_text("\n".join(events.read_text().splitlines()[1:]) + "\n")
    request = {
        "action": "evaluation_plan",
        "mode": "prepare",
        "note": "I authorize paid recovery of the reviewed incomplete preparation.",
    }
    with pytest.raises(ValueError, match="review the incomplete preparation"):
        dispatch(request)
    (paths["output"] / "prep-001/completed.json").unlink()
    report = dispatch(
        {"action": "review_result", "kind": "calibration", "run": "prep-001"}
    )
    assert report["reconstructed_completion"] and not report["summary"]["complete"]
    with pytest.raises(ValueError, match="incomplete calibration"):
        dispatch(
            {
                "action": "approve_result",
                "kind": "calibration",
                "run": "prep-001",
                "digest": report["digest"],
                "note": "Reviewed incomplete evidence.",
            }
        )
    recovery = dispatch(request)
    assert recovery["run"] == "prep-002" and recovery["spent_usd"] == 2.5
    ledger = private.read(paths["output"] / "history.json")
    assert len(ledger["executions"]) == 1
    ledger["prior_unknown_usage"] = True
    private.write(paths["output"] / "history.json", ledger)
    with pytest.raises(ValueError, match="unknown prior usage"):
        dispatch(request)


def test_missing_corpus_strict_actions_and_safe_pages(tmp_path: Path) -> None:
    paths = {key: tmp_path / key for key in ("corpus", "guide", "output", "inputs")}
    dispatch = partial(guide.dispatch, **paths)
    assert dispatch({"action": "status"})["phase"] == "author"
    assert not paths["output"].exists() and not paths["inputs"].exists()
    for request in (
        {"action": "shell", "command": "id"},
        {"action": "status", "candidate": "secret"},
        {"action": "review_result", "kind": "candidate", "run": "../outside"},
    ):
        with pytest.raises(ValueError):
            dispatch(request)
    guide.page(
        paths["guide"],
        "safe.html",
        "<script>bad()</script>",
        "a" * 64,
        [("</h2><img src=x>", {"text": "<script>leak()</script>"})],
    )
    content = (paths["guide"] / "pages/safe.html").read_text()
    assert "<script>" not in content and "&lt;script&gt;" in content
    assert "default-src 'none'" in content
    (paths["guide"] / "pages/link.html").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlinks"):
        guide.page(paths["guide"], "link.html", "Unsafe", "a" * 64, [])


def test_malformed_draft_status_keeps_authoring_available_but_frozen_is_strict(
    tmp_path: Path,
) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    cases = paths["corpus"] / "cases.jsonl"
    original = cases.read_text()
    for broken in ("{", '{"number": 1}\n'):
        cases.write_text(broken)
        state = dispatch({"action": "status"})
        assert state["phase"] == "author" and not state["frozen"]
        assert state["draft_error"] and not state["ready"]
    cases.write_text(original)
    examples = paths["corpus"] / "examples.json"
    original_examples = examples.read_bytes()
    examples.unlink()
    state = dispatch({"action": "status"})
    assert state["phase"] == "author" and "missing required" in state["draft_error"]
    examples.write_bytes(original_examples)
    freeze(paths)
    cases.unlink()
    with pytest.raises(ValueError, match="missing required"):
        dispatch({"action": "status"})


def test_only_stopped_interrupted_evaluation_can_render(tmp_path: Path) -> None:
    paths = workstation(tmp_path)
    dispatch = partial(guide.dispatch, **paths)
    freeze(paths)
    dispatch(
        {"action": "init_history", "prior_cost_usd": 0, "prior_unknown_usage": False}
    )
    with (paths["output"] / "history.lock").open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert dispatch({"action": "status"})["phase"] == "running"
        with pytest.raises(ValueError, match="still active"):
            dispatch({"action": "review_result", "kind": "candidate", "run": "run-001"})
    entry = execution(paths["output"] / "run-001", count=0)
    attempt = private.run.Attempt(
        id="synthetic-0-1",
        case_id="synthetic-0",
        trial=1,
        status="infrastructure",
        error="Synthetic transport interruption",
    )
    (paths["output"] / "run-001/events.jsonl").write_text(
        json.dumps({"event": "attempt_finished", **attempt.model_dump()}) + "\n"
    )
    ledger = private.read(paths["output"] / "history.json")
    ledger["executions"] = [entry]
    private.write(paths["output"] / "history.json", ledger)
    (paths["output"] / "run-001/completed.json").unlink()
    report = dispatch(
        {"action": "review_result", "kind": "candidate", "run": "run-001"}
    )
    assert report["reconstructed_completion"]
    assert report["summary"]["unmeasured"] == 300
    page = (paths["guide"] / "pages" / report["page"]).read_text()
    highlights = page.split("Disagreements, failures and incomplete measurements</h2>")[
        1
    ].split("</section>")[0]
    assert (
        "infrastructure" in highlights
        and "Synthetic transport interruption" in highlights
    )
    manifest = private.read(paths["output"] / "run-001/manifest.json")
    completion = private.read(paths["output"] / "run-001/completed.json")
    assert completion["completed_at"] == manifest["started_at"]
    assert (
        private.read(paths["output"] / "run-001/summary.json")[
            "private_review_complete"
        ]
        is False
    )

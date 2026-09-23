"""Protected golden workflow commands. No production AWS access or rebuild path."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import stat
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import check_production_release as release
from scripts import golden_gate as gate
from scripts.verify_release_bundle import verify_bundle


def extract(raw: bytes, output: Path, maximum: int = gate.MAX_BYTES) -> None:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = [i.filename for i in entries]
        gate.require(
            len(names) == len(set(names))
            and sum(i.file_size for i in entries) <= maximum,
            "archive size or duplicate member",
        )
        for item in entries:
            path = PurePosixPath(item.filename)
            gate.require(
                not path.is_absolute()
                and ".." not in path.parts
                and "\\" not in item.filename
                and not stat.S_ISLNK(item.external_attr >> 16),
                "unsafe archive member",
            )
        archive.extractall(output)


def pack(directory: Path) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                gate.require(not path.is_symlink(), "archive symlink")
                archive.writestr(
                    zipfile.ZipInfo(
                        str(path.relative_to(directory)), (1980, 1, 1, 0, 0, 0)
                    ),
                    path.read_bytes(),
                )
    result = output.getvalue()
    gate.require(len(result) <= gate.MAX_BYTES, "evidence archive too large")
    return result


def archive(directory: Path) -> dict[str, Any]:
    body = pack(directory)
    return gate.immutable(f"reports/{hashlib.sha256(body).hexdigest()}.zip", body)


def resolve(development_run: int, purpose: str) -> dict[str, Any]:
    gate.require(purpose in {"candidate", "production-reference"}, "invalid purpose")
    if purpose == "candidate":
        producer = gate.obj(release.api("GET", f"actions/runs/{development_run}"))
        candidate = producer["head_sha"]
    else:
        gate.require(
            development_run == 0, "production reference takes no candidate input"
        )
        candidate = gate.recent_production()["sha"]
    producer, evidence, versions = release._development(candidate)
    gate.require(
        purpose != "candidate" or producer["id"] == development_run,
        "development delivery mismatch",
    )
    return {
        "candidate": candidate,
        "bundle_id": evidence["artifact_id"],
        "bundle_digest": evidence["artifact_digest"],
        "development_run": producer["id"],
        "development_attempt": producer["run_attempt"],
        "development_deployment": evidence["deployment_id"],
        "schema_versions": versions,
        "purpose": purpose,
    }


def calibration() -> Path:
    from eval import golden_baseline as baseline

    reference = gate.read(gate.ROOT / "v2/eval/golden/calibration-reference.json")
    gate.require(
        reference.get("status") == "approved"
        and isinstance(reference.get("directory"), str),
        "calibration reference awaits human review",
    )
    path = (gate.ROOT / reference["directory"]).resolve()
    gate.require(
        path.is_relative_to((gate.ROOT / "v2/eval/evidence").resolve()),
        "calibration outside curated evidence",
    )
    report = baseline.load_evidence(path)
    review = gate.read(path / "review.json")
    baseline.require_review(review, report["evidence_sha256"])
    gate.require(
        report["complete"]
        and reference.get("evidence_sha256") == report["evidence_sha256"]
        and baseline.contract(report["manifest"]["identity"])
        == gate.policy()["contract_sha256"]
        and review.get("unresolved_findings") == []
        and review.get("adjudicated_disagreements")
        == {r["id"]: r["disagreements"] for r in report["rows"] if r["disagreements"]},
        "calibration incomplete, incompatible, or unresolved",
    )
    return path


def prepare(
    context: dict[str, Any],
    candidate_root: Path,
    directory: Path,
    superseded_run: int = 0,
    replacement_reason: str = "none",
) -> dict[str, Any]:
    from eval import golden
    from eval import golden_baseline as baseline
    from eval import golden_run as run
    from eval.artifact_agent import ArtifactAgent

    gate.development_account()
    limits = gate.policy()
    golden.validate()
    gate.require(
        gate.read(golden.ROOT / "review.json").get("status") == "approved",
        "corpus review is pending",
    )
    gate.protection("golden-evaluation")
    gate.protection("golden-review")
    calibration_path = calibration()
    directory.mkdir(parents=True, exist_ok=False)
    if context["purpose"] == "candidate":
        pointer, etag = gate.production_reference()
        gate.age(pointer["created_at"], limits["production_max_age_hours"])
    else:
        body, metadata = gate.get_object("baseline/current.json")
        pointer, etag = gate.obj(json.loads(body)), metadata["ETag"]
    bundle_file = directory / "release.zip"
    release.download(context["bundle_id"], bundle_file)
    verify_bundle(
        bundle_file,
        directory / "release",
        candidate_root,
        context["bundle_digest"],
        context["candidate"],
        context["schema_versions"],
        verify_checkout=True,
    )
    bundle = directory / "application"
    bundle.mkdir()
    extract(
        (directory / "release/v2/infra/build/agentcore.zip").read_bytes(),
        bundle,
        512 * 1024 * 1024,
    )
    probe = ArtifactAgent(bundle, "identity-only-no-provider-call")
    application = probe.identity
    probe.close()
    identity = run.identity(golden.load_cases())
    expected_specs = {
        spec["name"]: golden.digest(spec) for spec in application["tool_specs"]
    }
    gate.require(
        expected_specs == identity["tool_schema_hashes"],
        "packaged tool schema requires corpus requalification",
    )
    gate.require(
        application["model_config"]
        == {
            "model_id": "gpt-6-luna",
            "params": {
                "max_output_tokens": 2048,
                "reasoning": {"effort": "low"},
                "prompt_cache_key": "tollchat-agent-v2",
                "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
            },
            "stateful": False,
            "context_window_limit": 1050000,
        },
        "unreviewed packaged model settings",
    )
    identity.update(
        artifact_kind="release_bundle",
        artifact_id=str(context["bundle_id"]),
        artifact_sha256=context["bundle_digest"].removeprefix("sha256:"),
        commit=context["candidate"],
        evaluator_commit=identity["commit"],
        application=application,
        prompt_version=application["prompt_version"],
        renderer_version=application["renderer_version"],
        prompt_hashes=application["prompt_hashes"],
    )
    gate.require(
        baseline.contract(identity) == limits["contract_sha256"],
        "current evaluation contract differs from approved policy",
    )
    producer = gate.trusted_run(int(os.environ["GITHUB_RUN_ID"]), completed=False)
    gate.require(
        producer["head_sha"] == os.environ["GITHUB_SHA"]
        and producer["head_sha"] == identity["evaluator_commit"],
        "trusted checkout mismatch",
    )
    intent = {
        "declared_at": datetime.now(UTC).isoformat(),
        "identity_sha256": golden.digest(identity),
        "policy_sha256": golden.digest(limits),
        "replacement_number": 0,
        "supersedes": None,
        "baseline_report_sha256": pointer.get("report_sha256")
        if context["purpose"] == "candidate"
        else None,
    }
    prepared = {
        **context,
        "identity": identity,
        "execution": intent,
        "baseline": pointer,
        "baseline_etag": etag,
        "run_id": producer["id"],
        "trusted_sha": producer["head_sha"],
        "attempt": 1,
        "evaluation_code_sha256": gate.code_digest(),
    }
    # One immutable claim per exact experiment. No latest-green run selection.
    claim = gate.digest(
        {
            k: prepared[k]
            for k in ("candidate", "bundle_digest", "purpose", "evaluation_code_sha256")
        }
        | {"policy": intent["policy_sha256"], "baseline": gate.digest(pointer)}
    )
    claim_key = f"claims/{claim}.json"
    if superseded_run:
        replacement(directory, prepared, claim_key, superseded_run, replacement_reason)
        claim_key = f"claims/{claim}-replacement.json"
    else:
        gate.require(
            replacement_reason == "none", "replacement reason without prior run"
        )
    prepared["claim"] = gate.put_object(claim_key, gate.canonical(prepared))
    shutil.copytree(calibration_path, directory / "packet/calibration")
    if pointer.get("production") is not None:
        extract(gate.fetch(pointer["archive"]), directory / "comparison")
    gate.write(directory / "prepared.json", prepared)
    return prepared


def replacement(
    directory: Path,
    prepared: dict[str, Any],
    claim_key: str,
    prior_run: int,
    reason: str,
) -> None:
    """One replacement, authorized by this run's protected pre-spend review."""
    from eval import golden_baseline as baseline

    gate.require(
        reason in {"infrastructure", "actor_validity"}, "quality reruns are forbidden"
    )
    body, _ = gate.get_object(claim_key)
    original = gate.obj(json.loads(body))
    gate.require(
        original["run_id"] == prior_run
        and original["identity"] == prepared["identity"]
        and original["execution"]["replacement_number"] == 0,
        "replacement claim mismatch",
    )
    producer = gate.obj(release.api("GET", f"actions/runs/{prior_run}"))
    gate.require(
        producer.get("status") == "completed"
        and producer.get("conclusion") != "success"
        and producer.get("run_attempt") == 1
        and producer.get("path") == gate.WORKFLOW
        and producer.get("head_sha") == original["trusted_sha"],
        "prior run is not a failed original",
    )
    artifact = release._artifacts(prior_run, f"golden-evidence-{prior_run}-1")
    path = directory / "superseded.zip"
    release.download(artifact["id"], path)
    gate.require(
        "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == artifact["digest"],
        "prior evidence digest",
    )
    extract(path.read_bytes(), directory / "prior")
    packet = directory / "packet/superseded"
    shutil.copytree(directory / "prior/packet", packet)
    prior = baseline.load_evidence(packet / "run")
    gate.require(
        prior["manifest"]["identity"] == prepared["identity"]
        and (reason == "actor_validity" or not prior["full_corpus_complete"]),
        "quality failures cannot authorize replacement",
    )
    approval = gate.human_approval(prepared["run_id"], "golden-evaluation")
    authorization = {
        "status": "approved",
        "reviewer": approval["user"]["login"],
        "evidence_sha256": prior["evidence_sha256"],
        "evidence": f"Protected replacement approval {gate.digest(approval)}; dispatch reason {reason}.",
        "approved_at": datetime.now(UTC).isoformat(),
        "reason": reason,
    }
    gate.write(
        packet / "replacement-review.json",
        {
            "execution": original["execution"],
            "actor_validity": "invalid" if reason == "actor_validity" else "unreviewed",
            "rerun_authorization": authorization,
        },
    )
    prepared["execution"].update(
        replacement_number=1,
        supersedes=prior["evidence_sha256"],
        declared_at=datetime.now(UTC).isoformat(),
    )


def execute(directory: Path) -> None:
    from agent import toll_agent
    from eval import golden
    from eval import golden_run as run
    from eval.artifact_agent import ArtifactAgent

    prepared = gate.read(directory / "prepared.json")
    gate.require(
        prepared["evaluation_code_sha256"] == gate.code_digest(), "evaluator changed"
    )
    body, budget_meta = gate.get_object("budget/current.json")
    budget = gate.obj(json.loads(body))
    gate.require(
        budget.get("active_run") is None and budget.get("unknown_usage") is False,
        "previous spending requires reconciliation",
    )
    gate.require(
        type(budget.get("spent_usd")) in {int, float}
        and math.isfinite(budget["spent_usd"])
        and 0 <= budget["spent_usd"] <= 25,
        "invalid cumulative spending",
    )
    remaining = 25.0 - budget["spent_usd"]
    gate.require(
        remaining >= 5.0, "remaining authorized budget cannot reserve a full run"
    )
    reserved = {**budget, "active_run": prepared["run_id"], "reserved_usd": 5.0}
    gate.put_object(
        "budget/current.json", gate.canonical(reserved), budget_meta["ETag"]
    )
    api_key = toll_agent.load_openai_api_key()
    journal = run.Journal(directory / "packet/run", 5.0)
    calibrated = run.render(directory / "packet/calibration")
    manifest = {
        "run_id": str(prepared["run_id"]),
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "run",
        "identity": prepared["identity"],
        "prior_run_id": budget.get("last_run"),
        "prior_spend_usd": budget["spent_usd"],
        "budget_usd": 5.0,
        "workers": 4,
        "calibration": {
            "run_id": calibrated["manifest"]["run_id"],
            "evidence_sha256": calibrated["evidence_sha256"],
            "review": calibrated["review"],
        },
    }
    gate.write(journal.directory / "manifest.json", manifest)

    def factory(
        case: golden.GoldenCase,
        attempt: run.Attempt,
        account: run.Journal,
        messages: list[str],
    ) -> ArtifactAgent:
        return ArtifactAgent(
            directory / "application",
            api_key,
            case,
            attempt,
            account,
            messages,
            prepared["identity"]["application"],
        )

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(run.execute, case, trial, journal, factory)
                for case in golden.load_cases()
                for trial in (1, 2, 3)
            ]
            for future in futures:
                future.result()
    finally:
        run.render(journal.directory)
        body, current = gate.get_object("budget/current.json")
        gate.require(
            gate.obj(json.loads(body)).get("active_run") == prepared["run_id"],
            "spending ledger changed",
        )
        settled = {
            "spent_usd": budget["spent_usd"] + journal.spent,
            "active_run": None,
            "reserved_usd": 0,
            "unknown_usage": journal.unknown_usage or abs(journal.reserved) > 1e-9,
            "last_run": prepared["run_id"],
        }
        gate.put_object("budget/current.json", gate.canonical(settled), current["ETag"])
        gate.write(directory / "packet/execution.json", prepared)
        reference = archive(directory / "packet")
        gate.write(directory / "evidence.json", reference)


def review_record(
    report: dict[str, Any], prepared: dict[str, Any], approval: dict[str, Any]
) -> dict[str, Any]:
    from eval import golden_baseline as baseline

    passed = baseline.counts(report)
    return {
        "status": "approved",
        "evidence_sha256": report["evidence_sha256"],
        "report_sha256": report["report_sha256"],
        "policy_sha256": gate.digest(gate.policy()),
        "reviewer": approval["user"]["login"],
        "evidence": f"Protected golden-review approval: {gate.digest(approval)}. Approval asserts actor validity and review of the published sample and findings.",
        "approved_at": datetime.now(UTC).isoformat(),
        "actor_validity": "valid",
        "unresolved_findings": [],
        "sample_ids": baseline.sample_ids(report),
        "critical_failures_reviewed": sorted(
            c["id"]
            for c in report["manifest"]["identity"]["cases"]
            if c["critical"] and passed[c["id"]] != 3
        ),
        "held_out_exposure": "The published bounded review sample exposes its held-out transcripts; no tuning authorization.",
        "execution": prepared["execution"],
    }


def qualify(directory: Path, *, approved: bool) -> dict[str, Any]:
    from eval import golden_baseline as baseline

    prepared = gate.read(directory / "packet/execution.json")
    report = baseline.load_evidence(directory / "packet/run")
    review = (
        gate.human_approval(prepared["run_id"], "golden-review")
        if approved
        else {"user": {"login": "PENDING HUMAN REVIEW"}}
    )
    record = review_record(report, prepared, review)
    review_path = directory / "packet/human-review.json"
    gate.write(review_path, record)
    previous = directory / "comparison" if prepared["purpose"] == "candidate" else None
    superseded = (
        directory / "packet/superseded"
        if prepared["execution"]["replacement_number"]
        else None
    )
    try:
        decision = baseline.qualify(
            directory / "packet/run",
            gate.POLICY,
            review_path,
            directory / "packet/calibration",
            baseline=previous / "run" if previous else None,
            baseline_review=previous / "human-review.json" if previous else None,
            superseded=superseded / "run" if superseded else None,
            superseded_review=superseded / "replacement-review.json"
            if superseded
            else None,
        )
    finally:
        if not approved:
            review_path.unlink(missing_ok=True)
    decision["human_review_complete"] = approved
    current = baseline.counts(report)
    old = baseline.counts(baseline.load_evidence(previous / "run")) if previous else {}
    decision["case_comparison"] = [
        {
            "id": key,
            "candidate_passes": count,
            "baseline_passes": old.get(key),
            "delta": count - old[key] if key in old else None,
        }
        for key, count in current.items()
    ]
    gate.write(directory / "packet/decision.json", decision)
    gate.write(directory / "decision.json", decision)
    baseline.render_review(
        directory / "packet/run", gate.POLICY, directory / "review.html"
    )
    if not approved:
        gate.require(
            decision["qualified"] is True,
            "machine qualification failed; evidence retained",
        )
        return decision
    gate.require(decision["qualified"] is True, "qualification failed")
    reference = archive(directory / "packet")
    result = {
        k: prepared[k]
        for k in (
            "candidate",
            "bundle_id",
            "bundle_digest",
            "development_run",
            "development_attempt",
            "development_deployment",
            "purpose",
            "run_id",
            "attempt",
            "trusted_sha",
            "evaluation_code_sha256",
        )
    }
    result.update(
        qualified=True,
        errors=[],
        archive=reference,
        review=review,
        created_at=report["manifest"]["created_at"],
        report_sha256=report["report_sha256"],
        policy_sha256=decision["policy_sha256"],
        contract_sha256=gate.policy()["contract_sha256"],
        baseline_sha256=gate.digest(prepared["baseline"]),
    )
    gate.write(directory / "receipt.json", result)
    # Index may be superseded only by another fully reviewed experiment. The
    # receipt remains authenticated by its completed GitHub producer workflow.
    key = (
        gate.candidate_key(prepared["candidate"], prepared["baseline"])
        if prepared["purpose"] == "candidate"
        else f"references/{prepared['run_id']}.json"
    )
    gate.put_object(
        key,
        gate.canonical(
            {"run_id": prepared["run_id"], "receipt_sha256": gate.digest(result)}
        ),
    )
    return result


def initialize() -> None:
    gate.development_account()
    source = gate.ROOT / "v2/eval/results/golden"
    registry = gate.read(source / "registry.json")
    gate.require(
        registry["production"] is None, "initialization is historical evidence only"
    )
    reference = archive(source / registry["initial"]["archive"])
    gate.put_object(
        "baseline/current.json",
        gate.canonical({"initial": reference, "production": None}),
    )
    gate.put_object(
        "budget/current.json",
        gate.canonical(
            {
                "spent_usd": 0.87191346,
                "active_run": None,
                "reserved_usd": 0,
                "unknown_usage": False,
                "last_run": None,
            }
        ),
    )


def publish(evaluation_run: int, production_run: int) -> None:
    gate.development_account()
    producer = gate.obj(release.api("GET", f"actions/runs/{production_run}"))
    gate.require(
        producer.get("repository", {}).get("full_name") == release.REPOSITORY
        and producer.get("head_repository", {}).get("full_name") == release.REPOSITORY
        and producer.get("head_branch") == "main"
        and producer.get("status") == "completed"
        and producer.get("path") == ".github/workflows/v2-production-plan.yml"
        and producer.get("event") == "workflow_run"
        and producer.get("conclusion") == "success"
        and producer.get("run_attempt") == 1,
        "untrusted production completion",
    )
    artifact = release._artifacts(
        production_run, f"v2-production-release-evidence-{production_run}-1"
    )
    evidence = release._single_json(artifact, "production-release-evidence.json")  # pyright: ignore[reportPrivateUsage]
    if evaluation_run == 0:
        evaluation_run = gate.obj(evidence.get("golden"))["run_id"]
    value = gate.receipt(evaluation_run)
    gate.require(
        value.get("qualified") is True and value.get("errors") == [],
        "unqualified baseline",
    )
    if value["purpose"] == "candidate":
        gate.require(
            gate.obj(evidence.get("golden")).get("receipt_sha256")
            == gate.digest(value),
            "production used another decision",
        )
    else:
        gate.require(
            value["purpose"] == "production-reference", "invalid reference purpose"
        )
    gate.require(
        evidence.get("outcome") == "success"
        and evidence.get("migration_evidence") == "success"
        and evidence.get("candidate") == value["candidate"],
        "production failed or candidate differs",
    )
    canary = gate.obj(evidence.get("canary"))
    from scripts.development_deployment_status import validate_canary

    validate_canary(
        json.dumps(canary),
        value["candidate"],
        production_run,
        1,
        evidence["claim_id"],
        value["bundle_id"],
        value["bundle_digest"],
    )
    gate.require(
        gate.recent_production()["id"] == evidence["claim_id"],
        "newer production deployment exists",
    )
    body, current = gate.get_object("baseline/current.json")
    previous = gate.obj(json.loads(body))
    if (
        previous.get("report_sha256") == value["report_sha256"]
        and gate.obj(previous.get("production") or {}).get("claim_id")
        == evidence["claim_id"]
    ):
        return
    gate.require(
        value["baseline_sha256"] == gate.digest(previous),
        "baseline changed before publication",
    )
    gate.age(value["created_at"], gate.policy()["production_max_age_hours"])
    gate.fetch(value["archive"])
    record = {
        "evaluation_run_id": evaluation_run,
        "production_run_id": production_run,
        "receipt_sha256": gate.digest(value),
        "production": evidence,
        "previous": {
            "version_id": current["VersionId"],
            "sha256": hashlib.sha256(body).hexdigest(),
        },
    }
    approval = gate.immutable(
        f"approvals/{gate.digest(record)}.json", gate.canonical(record)
    )
    pointer = {
        "initial": previous["initial"],
        "production": {"claim_id": evidence["claim_id"], "run_id": production_run},
        "archive": value["archive"],
        "approval": approval,
        "report_sha256": value["report_sha256"],
        "created_at": value["created_at"],
    }
    gate.put_object("baseline/current.json", gate.canonical(pointer), current["ETag"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=(
            "resolve",
            "prepare",
            "execute",
            "machine",
            "approve",
            "initialize",
            "publish",
        ),
    )
    parser.add_argument(
        "--purpose", choices=("candidate", "production-reference"), default="candidate"
    )
    parser.add_argument("--development-run", type=int, default=0)
    parser.add_argument("--evaluation-run", type=int, default=0)
    parser.add_argument("--production-run", type=int, default=0)
    parser.add_argument("--superseded-run", type=int, default=0)
    parser.add_argument(
        "--replacement-reason",
        choices=("none", "infrastructure", "actor_validity"),
        default="none",
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--context", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "resolve":
            args.directory.mkdir(parents=True, exist_ok=True)
            gate.write(
                args.directory / "context.json",
                resolve(args.development_run, args.purpose),
            )
        elif args.mode == "prepare":
            gate.require(
                args.context is not None and args.candidate_root is not None,
                "prepare requires fixed context and checkout",
            )
            assert args.context is not None and args.candidate_root is not None
            prepare(
                gate.read(args.context),
                args.candidate_root,
                args.directory,
                args.superseded_run,
                args.replacement_reason,
            )
        elif args.mode == "execute":
            execute(args.directory)
        elif args.mode in {"machine", "approve"}:
            qualify(args.directory, approved=args.mode == "approve")
        elif args.mode == "initialize":
            initialize()
        else:
            publish(args.evaluation_run, args.production_run)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise SystemExit(
            "golden workflow blocked; inspect sanitized evidence and prerequisite status"
        ) from None


if __name__ == "__main__":
    main()

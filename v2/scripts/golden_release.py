"""Import externally signed aggregate evidence; never execute private evals here."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from scripts import check_production_release as release
from scripts import golden_gate as gate


def resolve(development_run: int) -> dict[str, Any]:
    producer = gate.obj(release.api("GET", f"actions/runs/{development_run}"))
    candidate = producer["head_sha"]
    producer, evidence, _ = release._development(candidate)
    gate.require(producer["id"] == development_run, "development delivery mismatch")
    return {
        "candidate": candidate,
        "bundle_id": evidence["artifact_id"],
        "bundle_digest": evidence["artifact_digest"],
        "development_run": producer["id"],
        "development_attempt": producer["run_attempt"],
        "development_deployment": evidence["deployment_id"],
    }


def review_text(summary: dict[str, Any], result: dict[str, Any]) -> str:
    current = summary["attempts"][-1]
    consistency = current["case_pass_counts"]
    interval = current["success_interval"]
    cost_per_success = (
        f"${current['agent_cost_usd'] / current['passed']:.6f}"
        if current["passed"]
        else "unavailable (zero successes)"
    )
    history = "\n".join(
        f"- Execution {index + 1} ({row['replacement_reason']}): "
        f"{row['passed']} passed, {row['failed']} failed, "
        f"{row['inconclusive']} inconclusive, {row['unmeasured']} unmeasured; "
        f"total cost ${row['total_cost_usd']:.6f}."
        for index, row in enumerate(summary["attempts"])
    )
    return (
        "# Private held-out qualification\n\n"
        f"**{'Qualified for human review' if result['qualified'] else 'Did not qualify'}**\n\n"
        f"Successful trials: **{current['passed']}/300** across 100 scenarios, three trials each. "
        f"Failed: {current['failed']}; inconclusive: {current['inconclusive']}; "
        f"unmeasured: {current['unmeasured']}.\n\n"
        f"Cases passing 0/1/2/3 trials: {consistency}. "
        f"95% interval (resampling whole cases): {interval['lower']:.1%} to {interval['upper']:.1%}.\n\n"
        f"Latency p50/p95: {current['latency_p50_seconds']}/{current['latency_p95_seconds']} seconds. "
        f"Agent cost: ${current['agent_cost_usd']:.6f}; total run cost: ${current['total_cost_usd']:.6f}. "
        f"Agent cost per successful trial: {cost_per_success}.\n\n"
        f"Cumulative holdout executions: {summary['holdout_attempts']}; "
        f"{'first-use holdout' if summary['holdout_attempts'] == 1 else 'reused private benchmark'}. "
        f"Candidate executions retained: {len(summary['attempts'])}. "
        f"Cumulative authorized spend: ${summary['cumulative_cost_usd']:.6f}.\n\n"
        "The 80% floor is an admission choice for this reference implementation, not a claim "
        "of real-world accuracy. Grading is unchanged; failed answers remain failures. "
        "The independent evaluator retains cases, transcripts, and private review evidence.\n\n"
        f"Machine findings: {result['errors']}\n\nRetained candidate executions:\n\n{history}\n"
    )


def import_summary(
    context: dict[str, Any], sha256: str, version: str, directory: Path
) -> None:
    code = gate.code_digest()
    gate.require(
        gate.is_hash(sha256) and bool(version) and version != "null",
        "exact summary object required",
    )
    gate.development_account()
    gate.protection("golden-evaluation")
    gate.protection("golden-review")
    producer = gate.trusted_run(int(os.environ["GITHUB_RUN_ID"]), completed=False)
    gate.require(
        producer["head_sha"] == os.environ["GITHUB_SHA"], "trusted checkout mismatch"
    )
    gate.require(
        context == resolve(context["development_run"]), "development provenance changed"
    )
    packet, metadata = gate.get_object(f"aggregates/inbox/{sha256}.json", version)
    gate.require(
        metadata["VersionId"] == version
        and hashlib.sha256(packet).hexdigest() == sha256,
        "imported summary object mismatch",
    )
    summary = gate.verify_summary(packet)
    gate.require(
        all(summary[k] == context[k] for k in gate.IDENTITY),
        "signed artifact identity mismatch",
    )
    # Changing policy or importer code cannot create a fresh quality retry.
    for index, attempt in enumerate(summary["attempts"]):
        claim = gate.digest(
            {
                "bundle_digest": summary["bundle_digest"],
                "holdout_sha256": summary["holdout_sha256"],
                "attempt": index,
            }
        )
        costs = {key: attempt[key] for key in ("agent_cost_usd", "total_cost_usd")}
        outcomes = {key: value for key, value in attempt.items() if key not in costs}
        gate.immutable(f"aggregates/claims/{claim}.json", gate.canonical(outcomes))
        if not summary["unknown_usage"]:
            gate.immutable(f"aggregates/accounting/{claim}.json", gate.canonical(costs))
    clean = gate.canonical(gate.strict_json(packet))
    reference = gate.immutable(
        f"aggregates/reports/{hashlib.sha256(clean).hexdigest()}.json", clean
    )
    result = gate.decision(summary)
    directory.mkdir(parents=True, exist_ok=False)
    gate.write(directory / "summary-envelope.json", gate.strict_json(clean))
    gate.write(directory / "decision.json", result)
    (directory / "review.md").write_text(review_text(summary, result))
    gate.write(
        directory / "prepared.json",
        {
            **context,
            "schema_version": 2,
            "purpose": "candidate",
            "run_id": producer["id"],
            "attempt": 1,
            "trusted_sha": producer["head_sha"],
            "evaluation_code_sha256": code,
            "archive": reference,
            "signed_summary": gate.strict_json(clean),
            "created_at": summary["attempts"][-1]["completed_at"],
            "report_sha256": gate.digest(summary),
            "policy_sha256": summary["policy_sha256"],
            "holdout_sha256": summary["holdout_sha256"],
            **result,
        },
    )
    gate.require(
        result["qualified"], "machine qualification failed; aggregate evidence retained"
    )


def approve(directory: Path) -> None:
    gate.development_account()
    value = gate.read(directory / "prepared.json")
    gate.require(
        value["evaluation_code_sha256"] == gate.code_digest(), "importer changed"
    )
    producer = gate.trusted_run(int(os.environ["GITHUB_RUN_ID"]), completed=False)
    gate.require(
        value["run_id"] == producer["id"]
        and value["attempt"] == 1
        and value["trusted_sha"] == producer["head_sha"] == os.environ["GITHUB_SHA"],
        "approval workflow mismatch",
    )
    gate.validate_receipt(value, resolve(value["development_run"]))
    gate.fetch(gate.obj(value["archive"]))
    value["review"] = gate.human_approval(value["run_id"], "golden-review")
    gate.write(directory / "receipt.json", value)
    publish_candidate(value)


def publish_candidate(value: dict[str, Any]) -> None:
    """Recover publication of identical evidence, never select a new evaluation."""
    key = gate.candidate_key(value["candidate"])
    body = gate.canonical(
        {
            "run_id": value["run_id"],
            "receipt_sha256": gate.digest(value),
            "report_sha256": value["report_sha256"],
        }
    )
    try:
        gate.put_object(key, body)
    except ValueError:
        previous, metadata = gate.get_object(key)
        if previous == body:
            return
        index = gate.fields(
            gate.strict_json(previous), "run_id receipt_sha256 report_sha256"
        )
        gate.require(
            index["report_sha256"] == value["report_sha256"]
            and type(index["run_id"]) is int
            and 0 < index["run_id"] < value["run_id"],
            "publication recovery requires identical evidence and a newer import",
        )
        gate.trusted_run(index["run_id"], completed=True, successful=False)
        gate.put_object(key, body, metadata["ETag"])


def compare(current: Path, previous: Path) -> dict[str, Any]:
    """Informational only; both summaries must use the same active contract."""
    new, old = (
        gate.verify_summary(current.read_bytes()),
        gate.verify_summary(previous.read_bytes()),
    )
    a, b = new["attempts"][-1], old["attempts"][-1]
    gate.require(
        not any(row[k] for row in (a, b) for k in ("inconclusive", "unmeasured")),
        "incomplete measurements are not comparable",
    )
    return {
        "successful_trial_delta": a["passed"] - b["passed"],
        "success_rate_delta": (a["passed"] - b["passed"]) / 300,
        "all_three_case_delta": a["case_pass_counts"][3] - b["case_pass_counts"][3],
        "informational_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("resolve", "import", "approve", "compare"))
    parser.add_argument("--development-run", type=int, default=0)
    parser.add_argument("--summary-sha256", default="")
    parser.add_argument("--summary-version", default="")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "resolve":
            gate.code_digest()
            args.directory.mkdir(parents=True, exist_ok=True)
            gate.write(args.directory / "context.json", resolve(args.development_run))
        elif args.mode == "import":
            gate.require(args.context is not None, "import requires resolved context")
            assert args.context is not None
            import_summary(
                gate.read(args.context),
                args.summary_sha256,
                args.summary_version,
                args.directory,
            )
        elif args.mode == "approve":
            approve(args.directory)
        else:
            gate.require(
                args.previous is not None,
                "comparison requires a previous signed envelope",
            )
            assert args.previous is not None
            gate.write(
                args.directory / "comparison.json",
                compare(args.directory / "summary-envelope.json", args.previous),
            )
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise SystemExit(
            "golden workflow blocked; inspect aggregate evidence and activation prerequisites"
        ) from None


if __name__ == "__main__":
    main()

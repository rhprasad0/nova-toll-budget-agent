"""Prepare shadow CI and report pass cubed from ten cases with three trials each."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval import corpus, golden
from eval import golden_run as run

APPROVAL = golden.V2 / "eval/harness-approval.json"


def prepare(*, verify_runtime: bool = False) -> dict[str, Any]:
    if not corpus.PUBLIC.exists() and not APPROVAL.exists():
        return {
            "ready": False,
            "reason": "awaiting authored public cases and harness approval",
        }
    root = corpus.PUBLIC / "shadow"
    corpus.validate(corpus.PUBLIC / "training")
    corpus.validate(root)
    if json.loads((root / "review.json").read_text())["status"] != "approved":
        raise ValueError("shadow inputs await actual review")
    receipt = json.loads(APPROVAL.read_text())
    run.validate_calibration_receipt(receipt)
    if verify_runtime:
        original_root = golden.ROOT
        try:
            golden.ROOT = root
            identity = run.identity(golden.load_cases())
        finally:
            golden.ROOT = original_root
        if run.calibration_contract(identity) != receipt["contract_sha256"]:
            raise ValueError("shadow CI evaluator does not match approved calibration")
    return {
        "ready": True,
        "python": ".".join(map(str, receipt["runtime"]["python"])),
        "runner": "ubuntu-24.04-arm"
        if receipt["runtime"]["platform"] == "aarch64"
        else "ubuntu-latest",
    }


def report(directory: Path) -> dict[str, Any]:
    report = run.render(directory)
    identity = report["manifest"]["identity"]
    expected_cases = corpus.CONTRACT["splits"]["shadow"]["count"]
    expected_trials = expected_cases * 3
    if (
        report["manifest"]["mode"] != "run"
        or identity["corpus"].get("evaluation_scope") != "shadow"
        or len(identity["cases"]) != expected_cases
        or len(run.report_trials(identity)) != 3
    ):
        raise ValueError("shadow CI requires a ten-case, three-trial shadow run")
    return {
        "source_commit": identity["commit"],
        "passed": report["overall"]["successful_trials"],
        "expected_trials": expected_trials,
        "pass_rate": report["overall"]["overall_pass_rate"],
        "case_count": expected_cases,
        "passing_all_three_cases": report["overall"]["passing_all_three_cases"],
        "pass_cubed": report["overall"]["pass_cubed"],
        "scored_trials": report["overall"]["scored_trials"],
        "inconclusive_trials": report["overall"]["inconclusive_trials"],
        "complete": report["full_corpus_complete"]
        and report["overall"]["scored_trials"] == expected_trials,
        "failure_counts": report["overall"]["failure_counts"],
        "cost_usd": sum(report["overall"]["cost_usd"].values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "report"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-runtime", action="store_true")
    args = parser.parse_args()
    if args.mode == "report" and args.output is None:
        parser.error("report requires --output")
    print(
        json.dumps(
            prepare(verify_runtime=args.verify_runtime)
            if args.mode == "prepare"
            else report(args.output)
        )
    )


if __name__ == "__main__":
    main()

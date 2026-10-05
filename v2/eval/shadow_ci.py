"""Prepare the shadow CI job and require a complete ten-case application result."""

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


def check(directory: Path) -> dict[str, Any]:
    report = run.render(directory)
    identity = report["manifest"]["identity"]
    expected = corpus.CONTRACT["splits"]["shadow"]["count"]
    if (
        report["manifest"]["mode"] != "run"
        or identity["corpus"].get("evaluation_scope") != "shadow"
        or len(identity["cases"]) != expected
        or len(run.report_trials(identity)) != 1
        or not report["full_corpus_complete"]
        or report["overall"]["scored_trials"] != expected
    ):
        raise ValueError("shadow CI requires ten complete measured application trials")
    return {
        "passed": report["overall"]["successful_trials"],
        "expected_trials": expected,
        "pass_rate": report["overall"]["overall_pass_rate"],
        "complete": True,
        "cost_usd": sum(report["overall"]["cost_usd"].values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "check"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-runtime", action="store_true")
    args = parser.parse_args()
    if args.mode == "check" and args.output is None:
        parser.error("check requires --output")
    print(
        json.dumps(
            prepare(verify_runtime=args.verify_runtime)
            if args.mode == "prepare"
            else check(args.output)
        )
    )


if __name__ == "__main__":
    main()

"""Compare a public training report with aggregate-only holdout feedback."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "v2"))
from eval import golden_run as run


def diagnose(training: dict[str, Any], hidden: dict[str, Any]) -> dict[str, Any]:
    identity = training["manifest"]["identity"]
    run.validate_identity(identity)
    trials = len(run.report_trials(identity))
    if (
        training["manifest"]["mode"] != "run"
        or identity["corpus"].get("evaluation_scope") != "training"
        or not training["full_corpus_complete"]
        or hidden.get("format_version") != 1
        or hidden.get("scope") != "holdout"
        or not hidden.get("complete")
        or hidden.get("source_commit") != identity["commit"]
        or hidden.get("artifact_sha256") != identity["artifact_sha256"]
        or hidden.get("corpus_version") != identity["corpus"]["version"]
        or hidden.get("trials_per_case") != trials
        or hidden.get("measurement_sha256") != run.calibration_contract(identity)
        or hidden.get("expected_trials")
        != run.corpus.CONTRACT["splits"]["holdout"]["count"] * trials
        or any(hidden.get(key) != 0 for key in ("inconclusive", "missing"))
    ):
        raise ValueError(
            "diagnostic requires complete, matching training and holdout measurements"
        )
    passed, failed = hidden["passed"], hidden["failed"]
    rate = hidden["pass_rate"]
    if (
        type(passed) is not int
        or type(failed) is not int
        or min(passed, failed) < 0
        or passed + failed != hidden["expected_trials"]
        or not isinstance(rate, (int, float))
        or not math.isfinite(rate)
        or rate != passed / hidden["expected_trials"]
    ):
        raise ValueError("inconsistent holdout totals")
    visible = training["overall"]["overall_pass_rate"]
    return {
        "source_commit": identity["commit"],
        "training_rate": visible,
        "holdout_rate": rate,
        "gap_percentage_points": 100 * (visible - rate),
        "complete": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training_report", type=Path)
    parser.add_argument("holdout_feedback", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            diagnose(
                run.render(args.training_report.parent),
                json.loads(args.holdout_feedback.read_text()),
            )
        )
    )


if __name__ == "__main__":
    main()

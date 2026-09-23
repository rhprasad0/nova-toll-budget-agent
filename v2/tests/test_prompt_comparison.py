"""Incomplete simulated-user trials must not become paired performance gains."""

import runpy
from copy import deepcopy
from pathlib import Path


def test_paired_comparison_excludes_invalid_actor_case() -> None:
    paired = runpy.run_path(
        str(Path(__file__).parents[1] / "eval/evidence/prompt-experiment/compare_runs.py")
    )["paired"]
    baseline = {
        "manifest": {
            "identity": {
                "cases": [
                    {"id": cid, "split_group": "same"}
                    for cid in ("complete", "incomplete")
                ]
            }
        },
        "attempts": [
            {
                "case_id": cid,
                "trial": trial,
                "status": "scored",
                "actor_validity": {"status": "valid"},
                "overall_success": False,
            }
            for cid in ("complete", "incomplete")
            for trial in (1, 2, 3)
        ],
    }
    candidate = deepcopy(baseline)
    for row in candidate["attempts"]:
        row["overall_success"] = True
    candidate["attempts"][-1]["actor_validity"]["status"] = "invalid"
    result = paired(baseline, candidate, {"complete", "incomplete"})
    assert result["paired_cases"] == result["excluded_cases"] == 1
    assert result["delta"] == 1
    assert result["ci95"] == [1, 1]
    assert paired(baseline, candidate, {"incomplete"})["delta"] is None

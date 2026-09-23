"""Incomplete simulated-user trials must not become paired performance gains."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest


def test_paired_comparison_excludes_invalid_actor_case() -> None:
    paired = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "eval/evidence/prompt-experiment/compare_runs.py"
        )
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


def test_recovery_preserves_scored_trials_and_all_costs() -> None:
    root = Path(__file__).parents[1] / "eval/evidence/prompt-experiment"
    recover = runpy.run_path(str(root / "compare_runs.py"))["with_recovery"]
    original = json.loads((root / "full-b-2.0.8/report.json").read_text())
    snapshot = deepcopy(original)
    failed = next(a for a in original["attempts"] if a["status"] == "infrastructure")
    recovery = deepcopy(original)
    recovery["attempts"] = [deepcopy(failed)]
    row = recovery["attempts"][0]
    row.update(status="inconclusive", error="actor_missing_reply", measurements=[])
    row["measurements"].append(
        {
            "role": "judge",
            "input_tokens": 1,
            "output_tokens": 1,
            "cached_tokens": 0,
            "written_tokens": 0,
            "seconds": 1,
            "cost_usd": 0.25,
            "complete": True,
        }
    )
    result = recover(original, recovery)
    assert original == snapshot
    assert result["overall"]["cost_usd"]["judge"] == pytest.approx(
        original["overall"]["cost_usd"]["judge"] + 0.25
    )
    assert result["recovery"]["total_execution_attempts"] == 601
    assert sum(
        result["subsets"][name]["cost_usd"]["judge"]
        for name in ("development", "held_out")
    ) == pytest.approx(result["overall"]["cost_usd"]["judge"])
    assert all(
        a == b
        for a, b in zip(original["attempts"], result["attempts"], strict=True)
        if a["id"] != failed["id"]
    )
    scored = next(a for a in original["attempts"] if a["status"] == "scored")
    recovery["attempts"] = [deepcopy(scored)]
    with pytest.raises(AssertionError, match="cannot replace"):
        recover(original, recovery)

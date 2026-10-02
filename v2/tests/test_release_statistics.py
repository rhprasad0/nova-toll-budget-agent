"""Small synthetic check for linked clusters, denominators, and repeatability."""

from copy import deepcopy
from typing import Any

import pytest

from scripts.release_statistics import compare


def test_cluster_comparison_and_slot_validation() -> None:
    baseline: dict[str, Any] = {
        "manifest": {
            "identity": {
                "cases": [
                    {"id": "a", "split_group": "linked"},
                    {"id": "b", "split_group": "linked"},
                    {"id": "c", "split_group": "other"},
                ]
            }
        },
        "attempts": [
            {
                "case_id": case,
                "trial": trial,
                "status": "scored",
                "overall_success": trial != 2,
            }
            for case in ("a", "b", "c")
            for trial in (1, 2, 3)
        ],
    }
    baseline["attempts"][1]["status"] = "inconclusive"
    same = compare(baseline, baseline)
    assert same["scenario_groups"] == 2
    assert same["baseline"]["successes"] == 6
    assert same["baseline"]["slots"] == 9
    assert same["baseline"]["repetition_sample_sd_pp"] == pytest.approx(57.7350269)
    assert same["baseline"]["case_success_histogram"] == [0, 0, 3, 0]
    assert same["intervals_percent"]["delta"] == [0, 0]
    final = deepcopy(baseline)
    for attempt in final["attempts"]:
        attempt.update(status="scored", overall_success=True)
    changed = compare(baseline, final)
    assert changed["intervals_percent"]["delta"] == pytest.approx([100 / 3, 100 / 3])
    assert changed["intervals_percent"]["delta_pass3"] == [100, 100]
    for attempts in (final["attempts"][:-1], final["attempts"] + final["attempts"][:1]):
        with pytest.raises(ValueError, match="slot"):
            compare(baseline, {**final, "attempts": attempts})
    final["manifest"]["identity"]["cases"][0]["split_group"] = "different"
    with pytest.raises(ValueError, match="groups differ"):
        compare(baseline, final)

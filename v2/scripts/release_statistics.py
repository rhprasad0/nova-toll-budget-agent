"""Print aggregate release statistics from two private three-repetition reports.

Usage: python v2/scripts/release_statistics.py BASELINE_REPORT FINAL_REPORT
No transcripts, case identifiers, or private paths are emitted.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def case_results(report: dict[str, Any]) -> dict[str, tuple[str, list[bool]]]:
    cases = report["manifest"]["identity"]["cases"]
    result: dict[str, tuple[str, list[bool]]] = {
        c["id"]: (c["split_group"] or c["id"], []) for c in cases
    }
    if not result or len(result) != len(cases):
        raise ValueError("empty or duplicate cases")
    slots: dict[tuple[str, int], bool] = {}
    for attempt in report["attempts"]:
        key = (attempt["case_id"], attempt["trial"])
        success = attempt["overall_success"]
        if (
            key in slots
            or key[0] not in result
            or type(key[1]) is not int
            or key[1] not in (1, 2, 3)
            or type(success) is not bool
            or attempt["status"] not in ("scored", "inconclusive")
            or (success and attempt["status"] != "scored")
        ):
            raise ValueError("invalid, duplicate, or unexpected slot")
        slots[key] = success
    if len(slots) != 3 * len(cases):
        raise ValueError("missing slots")
    for case_id, (_, successes) in result.items():
        successes.extend(slots[case_id, trial] for trial in (1, 2, 3))
    return result


def compare(baseline: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    before, after = case_results(baseline), case_results(final)
    if {k: v[0] for k, v in before.items()} != {k: v[0] for k, v in after.items()}:
        raise ValueError("cases or scenario groups differ")
    groups: dict[str, list[str]] = {}
    for case_id, (group, _) in before.items():
        groups.setdefault(group, []).append(case_id)
    vectors = [
        (
            sum(sum(before[c][1]) for c in ids),
            sum(sum(after[c][1]) for c in ids),
            3 * len(ids),
            sum(all(before[c][1]) for c in ids),
            sum(all(after[c][1]) for c in ids),
            len(ids),
        )
        for _, ids in sorted(groups.items())
    ]
    rng = random.Random(360)
    samples: dict[str, list[float]] = {
        name: []
        for name in (
            "baseline",
            "final",
            "delta",
            "baseline_pass3",
            "final_pass3",
            "delta_pass3",
        )
    }
    for _ in range(10000):
        b, f, slots, bt, ft, cases = map(
            sum, zip(*rng.choices(vectors, k=len(vectors)), strict=True)
        )
        for key, value in zip(
            samples,
            (
                b / slots,
                f / slots,
                (f - b) / slots,
                bt / cases,
                ft / cases,
                (ft - bt) / cases,
            ),
            strict=True,
        ):
            samples[key].append(100 * value)
    intervals = {}
    for key, values in samples.items():
        quantiles = statistics.quantiles(values, n=10000, method="inclusive")
        intervals[key] = [quantiles[249], quantiles[9749]]
    result: dict[str, Any] = {
        "scenario_groups": len(groups),
        "intervals_percent": intervals,
    }
    for key, results in (("baseline", before), ("final", after)):
        repetitions = [sum(v[1][i] for v in results.values()) for i in range(3)]
        counts = Counter(sum(v[1]) for v in results.values())
        result[key] = {
            "successes": sum(repetitions),
            "slots": 3 * len(results),
            "repetition_successes": repetitions,
            "repetition_sample_sd_pp": statistics.stdev(
                100 * n / len(results) for n in repetitions
            ),
            "case_success_histogram": [counts[n] for n in range(4)],
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("final", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            compare(
                json.loads(args.baseline.read_text()),
                json.loads(args.final.read_text()),
            ),
            indent=2,
        )
    )

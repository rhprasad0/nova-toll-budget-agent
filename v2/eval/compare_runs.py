"""Compare complete paired cases and account for authorized recovery attempts."""

import json
import random
from collections import defaultdict
from copy import deepcopy
from typing import Any

from eval.repetition import report_trials


def with_recovery(original: dict[str, Any], recovery: dict[str, Any]) -> dict[str, Any]:
    """Resolve authentication-failed slots only; preserve all incurred usage."""
    from eval import golden, golden_run

    left = original["manifest"]["identity"]
    right = recovery["manifest"]["identity"]
    for key in left:
        if key == "cases":
            assert all(case in left[key] for case in right[key])
        elif key in {"prompt_hashes", "actor_configuration"}:
            assert all(left[key][cid] == value for cid, value in right[key].items())
        else:
            assert left[key] == right[key], f"Recovery changed identity: {key}"
    result = deepcopy(original)
    rows = {row["id"]: row for row in result["attempts"]}
    assert len(rows) == len(result["attempts"])
    assert len({row["id"] for row in recovery["attempts"]}) == len(recovery["attempts"])
    for row in recovery["attempts"]:
        prior = rows[row["id"]]
        assert (
            prior["status"] == "infrastructure"
            and prior["error"] == "TokenRetrievalError"
        ), "Recovery cannot replace a scored or actor-inconclusive trial"
        assert (prior["case_id"], prior["trial"]) == (row["case_id"], row["trial"])
        resolved = deepcopy(row)
        resolved["measurements"] = prior["measurements"] + resolved["measurements"]
        resolved["seconds"] += prior["seconds"]
        rows[row["id"]] = resolved
    result["attempts"] = list(rows.values())
    attempts = [
        golden_run.Attempt.model_validate(
            {k: v for k, v in row.items() if k in golden_run.Attempt.model_fields}
        )
        for row in rows.values()
    ]
    cases = [
        golden.GoldenCase.model_validate_json(json.dumps(case))
        for case in left["cases"]
    ]
    version = tuple(map(int, left["harness_version"].split(".")))
    summary_options: dict[str, Any] = {
        "legacy": version < (2, 0, 0),
        "fixed_denominator": version >= (2, 2, 0),
        "overall_rate": version >= (2, 3, 0),
        "trials_per_case": len(report_trials(left)),
    }
    result["overall"] = golden_run.summary(attempts, cases, **summary_options)
    for name in original["subsets"]:
        subset = [
            c
            for c in cases
            if (
                not c.held_out
                if name == "development"
                else c.held_out
                if name == "held_out"
                else c.kind == name
            )
        ]
        ids = {c.id for c in subset}
        result["subsets"][name] = golden_run.summary(
            [a for a in attempts if a.case_id in ids],
            subset,
            **summary_options,
        )
    result["recovery"] = {
        "evidence_sha256": recovery["evidence_sha256"],
        "recovered_trial_slots": len(recovery["attempts"]),
        "total_execution_attempts": len(original["attempts"])
        + len(recovery["attempts"]),
        "workers": recovery["manifest"]["workers"],
    }
    return result


def paired(
    baseline: dict[str, Any], candidate: dict[str, Any], ids: set[str]
) -> dict[str, Any]:
    """Pair complete cases using their recorded trials; resample scenario groups."""
    left_identity = baseline["manifest"]["identity"]
    right_identity = candidate["manifest"]["identity"]
    trials = report_trials(left_identity)
    if report_trials(right_identity) != trials or any(
        left_identity[key] != right_identity[key]
        for key in ("harness_version", "corpus", "cases")
    ):
        raise ValueError("incompatible evaluation contract")
    cases = {c["id"]: c for c in baseline["manifest"]["identity"]["cases"]}
    if ids - cases.keys():
        raise ValueError("unknown comparison case")
    grouped: list[dict[str, list[dict[str, Any]]]] = []
    for report in (baseline, candidate):
        rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        slots = [(row["case_id"], row["trial"]) for row in report["attempts"]]
        expected = {(cid, trial) for cid in cases for trial in trials}
        if len(slots) != len(set(slots)) or set(slots) - expected:
            raise ValueError("duplicate or unexpected trial")
        if expected - set(slots):
            raise ValueError("missing trial")
        for row in report["attempts"]:
            if row["status"] == "scored" and row["actor_validity"]["status"] == "valid":
                rows[row["case_id"]].append(row)
        grouped.append(rows)
    differences: dict[str, float] = {}
    clusters: defaultdict[str, list[float]] = defaultdict(list)
    for cid in sorted(ids):
        left, right = (rows[cid] for rows in grouped)
        if {r["trial"] for r in left} != set(trials) or {
            r["trial"] for r in right
        } != set(trials):
            continue
        delta = (
            sum(r["overall_success"] for r in right)
            - sum(r["overall_success"] for r in left)
        ) / len(trials)
        differences[cid] = delta
        clusters[cases[cid]["split_group"] or cid].append(delta)
    interval = None
    if differences:
        rng = random.Random(360)
        groups = list(clusters.values())
        samples: list[float] = []
        for _ in range(10000):
            selected = [
                d for group in rng.choices(groups, k=len(groups)) for d in group
            ]
            samples.append(sum(selected) / len(selected))
        samples.sort()
        interval = [
            samples[int(0.025 * (len(samples) - 1))],
            samples[int(0.975 * (len(samples) - 1))],
        ]
    return {
        "paired_cases": len(differences),
        "excluded_cases": len(ids) - len(differences),
        "delta": sum(differences.values()) / len(differences) if differences else None,
        "ci95": interval,
        "improved": [cid for cid, d in differences.items() if d > 0],
        "regressed": [cid for cid, d in differences.items() if d < 0],
    }

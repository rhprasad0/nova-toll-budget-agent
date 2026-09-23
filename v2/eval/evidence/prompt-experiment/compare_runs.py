"""Compare frozen A/B/C reports: python compare_runs.py diagnostic|full."""

import json
import random
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path


def with_recovery(original: dict, recovery: dict) -> dict:
    """Resolve authentication-failed slots only; preserve all incurred usage."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
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
    result["overall"] = golden_run.summary(attempts, cases)
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
            [a for a in attempts if a.case_id in ids], subset
        )
    result["recovery"] = {
        "evidence_sha256": recovery["evidence_sha256"],
        "recovered_trial_slots": len(recovery["attempts"]),
        "total_execution_attempts": len(original["attempts"])
        + len(recovery["attempts"]),
        "workers": recovery["manifest"]["workers"],
    }
    return result


def paired(baseline: dict, candidate: dict, ids: set[str]) -> dict:
    """Pair complete three-trial cases; resample shared scenario groups."""
    cases = {c["id"]: c for c in baseline["manifest"]["identity"]["cases"]}
    grouped = []
    for report in (baseline, candidate):
        rows = defaultdict(list)
        for row in report["attempts"]:
            if row["status"] == "scored" and row["actor_validity"]["status"] == "valid":
                rows[row["case_id"]].append(row)
        grouped.append(rows)
    differences = {}
    clusters = defaultdict(list)
    for cid in sorted(ids):
        left, right = (rows[cid] for rows in grouped)
        if {r["trial"] for r in left} != {1, 2, 3} or {r["trial"] for r in right} != {
            1,
            2,
            3,
        }:
            continue
        delta = (
            sum(r["overall_success"] for r in right)
            - sum(r["overall_success"] for r in left)
        ) / 3
        differences[cid] = delta
        clusters[cases[cid]["split_group"] or cid].append(delta)
    interval = None
    if differences:
        rng = random.Random(360)
        groups = list(clusters.values())
        samples = []
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


def main(stage: str) -> None:
    assert stage in {"diagnostic", "full"}
    root = Path(__file__).resolve().parent
    reports = {
        arm: json.loads((root / f"{stage}-{arm}-2.0.8/report.json").read_text())
        for arm in "abc"
    }
    if stage == "full":
        for arm in "bc":
            path = root / f"full-{arm}-recovery-2.0.8/report.json"
            if path.exists():
                reports[arm] = with_recovery(reports[arm], json.loads(path.read_text()))
    cases = reports["a"]["manifest"]["identity"]["cases"]
    assert all(r["manifest"]["identity"]["cases"] == cases for r in reports.values())
    lines = [
        f"# {stage.title()} A/B/C comparison — 2.0.8",
        "",
        "Frozen prompts and evaluator; three trials per case. Inconclusive trials are retained and excluded from scored rates, not retried. Calibration judgments have known limitations; these are measured outcomes, not independently verified truth.",
        "",
        "| Arm | Scored / attempted trial slots / expected | Passed | Pass rate | Cases passing all 3 | Grounding violations | Rules violations | Cost | Latency p50 / p95 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for arm, r in reports.items():
        o = r["overall"]
        rate = "unavailable" if o["pass_at_1"] is None else f"{o['pass_at_1']:.1%}"
        lines.append(
            f"| {arm.upper()} | {o['scored_trials']} / {o['attempted_trials']} / {o['expected_trials']} | {o['successful_trials']} | {rate} | {o['passing_all_three_cases']} / {o['case_count']} | {o['violations']['grounding']['count']} | {o['violations']['rules']['count']} | ${sum(o['cost_usd'].values()):.6f} | {o['latency_seconds']['p50']:.1f}s / {o['latency_seconds']['p95']:.1f}s |"
        )
    if any("recovery" in r for r in reports.values()):
        lines += [
            "",
            "Authentication recovery fills only original infrastructure-failed trial slots; scored and actor-inconclusive trials are never replaced. Original reports/journals remain unchanged. Costs and token totals include both original and recovery calls. Latency sums original and recovery execution time for each affected trial, excluding the human login wait. Execution-attempt counts and both evidence digests are listed below.",
        ]
    if any(
        a["status"] == "infrastructure" for r in reports.values() for a in r["attempts"]
    ):
        lines += [
            "",
            "**Incomplete comparison: infrastructure failures are present. Unmeasured trials are not application failures, and incomplete-arm rates cannot establish a winner. Latency and cost per success are affected by the interruption. See the per-arm failure counts and original journals.**",
        ]
    subsets = {
        "all": {c["id"] for c in cases},
        "development": {c["id"] for c in cases if not c["held_out"]},
        "reserved": {c["id"] for c in cases if c["held_out"]},
    }
    comparisons = {}
    lines += [
        "",
        "## Paired case comparisons",
        "",
        "Difference is candidate minus A, in pass-rate percentage points. Only cases with all three valid scored trials in both arms are paired. Intervals resample scenario groups (10,000 samples; seed 360); they describe this finite corpus and do not remove judge noise or selection bias. Diagnostics were selected using historical results and are not an unbiased performance estimate.",
        "",
        "| Subset | Comparison | Paired / excluded cases | Difference | 95% interval |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for subset, ids in subsets.items():
        if not ids:
            continue
        for arm in "bc":
            p = paired(reports["a"], reports[arm], ids)
            comparisons[f"{subset}:{arm}"] = p
            interval = (
                "unavailable"
                if p["ci95"] is None
                else f"{100 * p['ci95'][0]:+.1f} to {100 * p['ci95'][1]:+.1f} pp"
            )
            delta = (
                "unavailable" if p["delta"] is None else f"{100 * p['delta']:+.1f} pp"
            )
            lines.append(
                f"| {subset} | {arm.upper()} - A | {p['paired_cases']} / {p['excluded_cases']} | {delta} | {interval} |"
            )
    lines += [
        "",
        "## Family results",
        "",
        "Values are successful / scored trials; missing or inconclusive trials do not count as successes.",
        "",
        "| Family | A | B | C |",
        "| --- | --- | --- | --- |",
    ]
    for family in sorted({c["coverage_family"] for c in cases}):
        ids = {c["id"] for c in cases if c["coverage_family"] == family}
        values = []
        for r in reports.values():
            rows = [
                a
                for a in r["attempts"]
                if a["case_id"] in ids
                and a["status"] == "scored"
                and a["actor_validity"]["status"] == "valid"
            ]
            values.append(f"{sum(a['overall_success'] for a in rows)} / {len(rows)}")
        lines.append(f"| {family} | " + " | ".join(values) + " |")
    for arm, r in reports.items():
        o = r["overall"]
        checks = Counter(check for a in r["attempts"] for check in a["checks"])
        lines += [
            "",
            f"## {arm.upper()} evidence",
            "",
            f"[Full report]({stage}-{arm}-2.0.8/report.json); [trial checklist]({stage}-{arm}-2.0.8/report.md). Evidence SHA-256: `{r['evidence_sha256']}`.",
            "",
            f"Actor validity: `{o['actor_validity_counts']}`. Failure classes: `{o['failure_counts']}`. Deterministic tool/argument/contract checks: `{dict(checks)}`.",
            "",
            f"Cost by role: `{o['cost_usd']}`. Agent cost per success: `{o['agent_cost_per_success_usd']}`. Token usage: `{o['usage']}`.",
        ]
        if "recovery" in r:
            rec = r["recovery"]
            lines += [
                "",
                f"[Recovery report](full-{arm}-recovery-2.0.8/report.json): `{rec['evidence_sha256']}`. Recovered trial slots: {rec['recovered_trial_slots']}; total original plus recovery execution attempts: {rec['total_execution_attempts']}; recovery workers: {rec['workers']} (original run: {r['manifest']['workers']}). The statistics above combine these reports without rewriting either one. Concurrency changes limit latency comparisons.",
            ]
    (root / f"{stage.upper()}-COMPARISON.json").write_text(
        json.dumps(comparisons, indent=2) + "\n"
    )
    (root / f"{stage.upper()}-COMPARISON.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])

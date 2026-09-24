"""Compare two frozen 100-case development reports without rerunning or regrading."""

import hashlib
import json
import math
import sys
from pathlib import Path

IDENTITY_KEYS = {
    "harness_version",
    "harness_sha256",
    "commit",
    "artifact_kind",
    "artifact_sha256",
    "corpus",
    "cases",
    "prompt_version",
    "renderer_version",
    "prompt_hashes",
    "tool_schema_hashes",
    "actor_prompt_sha256",
    "judge_prompt_sha256",
    "actor_check_sha256",
    "evaluator_sources_sha256",
    "diagnostic_rubrics",
    "diagnostic_domain_facts",
    "diagnostic_prompt",
    "model",
    "reasoning_effort",
    "max_output_tokens",
    "sampling",
    "transport",
    "prices",
    "application_model_config",
    "actor_configuration",
    "calibration_labels",
}
ALLOWED_CHANGES = {
    "commit",
    "artifact_sha256",
    "prompt_hashes",
}
VERDICTS = {"outcome", "grounding", "rules"}
GROUNDING_CHECKS = {"unsupported_money", "tool_evidence"}
ACTOR_ERRORS = {
    "actor_stop_with_message",
    "actor_missing_reply",
    "actor_invalid_turn_limit",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def identity(report, name):
    require(
        isinstance(report, dict) and "recovery" not in report,
        f"{name}: invalid or merged report",
    )
    manifest = report.get("manifest")
    require(
        isinstance(manifest, dict) and manifest.get("mode") == "run",
        f"{name}: expected run manifest",
    )
    value = manifest.get("identity")
    require(
        isinstance(value, dict) and IDENTITY_KEYS <= value.keys(),
        f"{name}: missing contract identity",
    )
    require(
        all(value[k] is not None and value[k] != "" for k in IDENTITY_KEYS),
        f"{name}: empty contract identity",
    )
    corpus = value["corpus"]
    require(
        isinstance(corpus, dict)
        and corpus.get("evaluation_scope") == "development"
        and corpus.get("case_count") == 100
        and corpus.get("trials_per_case") == 3,
        f"{name}: expected 100 development cases with three trials",
    )
    require(
        isinstance(corpus.get("hashes"), dict)
        and corpus.get("corpus_sha256") == digest(corpus["hashes"]),
        f"{name}: invalid corpus identity",
    )
    require(
        value["model"] == "gpt-6-luna"
        and corpus.get("actor_model") == "gpt-6-luna"
        and corpus.get("judge_model") == "gpt-6-luna",
        f"{name}: wrong model",
    )
    cases = value["cases"]
    require(
        isinstance(cases, list) and len(cases) == 100, f"{name}: expected 100 cases"
    )
    ids = [c.get("id") for c in cases if isinstance(c, dict)]
    require(
        len(ids) == 100
        and all(isinstance(cid, str) and cid for cid in ids)
        and len(set(ids)) == 100
        and all(
            c.get("held_out") is False
            and isinstance(c.get("contract_version"), int)
            and c["contract_version"] >= 2
            for c in cases
        ),
        f"{name}: duplicate, held-out, or missing case contract",
    )
    require(
        isinstance(value["prompt_hashes"], dict)
        and set(value["prompt_hashes"]) == set(ids)
        and isinstance(value["tool_schema_hashes"], dict)
        and value["tool_schema_hashes"],
        f"{name}: missing prompt or tool identity",
    )
    return value, set(ids)


def violation(row, key):
    checks = set(row["checks"])
    mandatory = GROUNDING_CHECKS if key == "grounding" else checks - GROUNDING_CHECKS
    verdict = row["verdicts"].get(key)
    return bool(checks & mandatory) or (verdict is not None and not verdict["passed"])


def attempts(report, ids, name):
    rows = report.get("attempts")
    require(isinstance(rows, list), f"{name}: missing attempts")
    by_slot = {}
    for row in rows:
        require(isinstance(row, dict), f"{name}: malformed attempt")
        cid, trial = row.get("case_id"), row.get("trial")
        require(
            cid in ids and type(trial) is int and trial in (1, 2, 3),
            f"{name}: unexpected trial {cid}/{trial}",
        )
        slot = cid, trial
        require(slot not in by_slot, f"{name}: duplicate trial {cid}/{trial}")
        require(
            row.get("id") == f"{cid}-{trial}",
            f"{name}: inconsistent attempt id {cid}/{trial}",
        )
        status = row.get("status")
        require(
            status in ("scored", "inconclusive"),
            f"{name}: infrastructure or unfinished trial {cid}/{trial}",
        )
        actor = row.get("actor_validity")
        actor_status = actor.get("status") if isinstance(actor, dict) else None
        require(
            actor_status in ("valid", "invalid", "uncertain")
            and ((status == "scored") == (actor_status == "valid")),
            f"{name}: inconsistent actor status {cid}/{trial}",
        )
        actor_error = (
            status == "inconclusive"
            and actor_status == "invalid"
            and row.get("failure_phase") == "actor"
            and row.get("failure_class") == "actor_validity"
            and row.get("error") in ACTOR_ERRORS
        )
        require(
            actor_error
            or (
                row.get("failure_phase") not in ("harness", "agent", "actor")
                and (
                    row.get("failure_phase") != "judge"
                    or status == "inconclusive"
                    and row.get("failure_class") == "actor_validity"
                )
                and not row.get("error")
            ),
            f"{name}: infrastructure, judge, or harness failure {cid}/{trial}",
        )
        measurements = row.get("measurements")
        require(
            isinstance(measurements, list) and measurements,
            f"{name}: missing usage {cid}/{trial}",
        )
        for measurement in measurements:
            require(
                isinstance(measurement, dict)
                and measurement.get("complete") is True
                and measurement.get("role") in ("agent", "actor", "judge")
                and all(
                    type(measurement.get(k)) is int and measurement[k] >= 0
                    for k in (
                        "input_tokens",
                        "output_tokens",
                        "cached_tokens",
                        "written_tokens",
                    )
                )
                and all(
                    type(measurement.get(k)) in (int, float)
                    and math.isfinite(measurement[k])
                    and measurement[k] >= 0
                    for k in ("seconds", "cost_usd")
                ),
                f"{name}: incomplete or unknown usage {cid}/{trial}",
            )
        verdicts = row.get("verdicts")
        require(
            isinstance(verdicts, dict)
            and (
                set(verdicts) <= VERDICTS if actor_error else set(verdicts) == VERDICTS
            )
            and all(
                isinstance(verdicts[k], dict)
                and type(verdicts[k].get("passed")) is bool
                and isinstance(verdicts[k].get("evidence"), str)
                and verdicts[k]["evidence"]
                for k in verdicts
            ),
            f"{name}: missing judge verdict {cid}/{trial}",
        )
        checks = row.get("checks")
        require(
            isinstance(checks, list) and all(isinstance(c, str) for c in checks),
            f"{name}: invalid checks {cid}/{trial}",
        )
        turns = row.get("turns")
        require(isinstance(turns, list), f"{name}: invalid turns {cid}/{trial}")
        passed = (
            status == "scored"
            and bool(turns)
            and not checks
            and all(verdicts[k]["passed"] for k in VERDICTS)
        )
        require(
            row.get("overall_success") is passed
            and row.get("mandatory_checks_passed") is (not checks),
            f"{name}: stale success flags {cid}/{trial}",
        )
        by_slot[slot] = {
            "passed": passed,
            "scored": status == "scored",
            "violations": {k: violation(row, k) for k in ("grounding", "rules")},
        }
    expected = {(cid, trial) for cid in ids for trial in (1, 2, 3)}
    require(
        set(by_slot) == expected,
        f"{name}: missing trials ({len(expected - set(by_slot))})",
    )
    scored = sum(row["scored"] for row in by_slot.values())
    successful = sum(row["passed"] for row in by_slot.values())
    overall = report.get("overall")
    require(
        isinstance(overall, dict)
        and overall.get("expected_trials") == 300
        and overall.get("attempted_trials") == 300
        and overall.get("scored_trials") == scored
        and overall.get("successful_trials") == successful
        and overall.get("inconclusive_trials") == 300 - scored,
        f"{name}: inconsistent overall counts",
    )
    for key in ("grounding", "rules"):
        count = sum(r["violations"][key] for r in by_slot.values() if r["scored"])
        aggregate = overall.get("violations", {}).get(key, {})
        require(
            aggregate.get("count") == count and aggregate.get("denominator") == scored,
            f"{name}: inconsistent {key} total",
        )
    return by_slot, {
        "successful_trials": successful,
        "scored_trials": scored,
        "inconclusive_trials": 300 - scored,
        "inconclusive_slots": [
            {"case_id": cid, "trial": trial}
            for cid, trial in sorted(by_slot)
            if not by_slot[cid, trial]["scored"]
        ],
    }


def compare(baseline, candidate):
    left_identity, ids = identity(baseline, "baseline")
    right_identity, candidate_ids = identity(candidate, "candidate")
    require(
        ids == candidate_ids and left_identity.keys() == right_identity.keys(),
        "incompatible evaluation identity",
    )
    for key in left_identity:
        if key not in ALLOWED_CHANGES:
            require(
                left_identity[key] == right_identity[key],
                f"incompatible evaluation identity: {key}",
            )
    left, left_totals = attempts(baseline, ids, "baseline")
    right, right_totals = attempts(candidate, ids, "candidate")
    common = {slot for slot in left if left[slot]["scored"] and right[slot]["scored"]}
    paired = [cid for cid in sorted(ids) if all((cid, n) in common for n in (1, 2, 3))]
    excluded = sorted(ids - set(paired))
    delta = (
        (
            sum(
                sum(right[cid, n]["passed"] - left[cid, n]["passed"] for n in (1, 2, 3))
                for cid in paired
            )
            / (3 * len(paired))
        )
        if paired
        else None
    )
    regressions = [
        {"case_id": cid, "trial": trial}
        for cid, trial in sorted(left)
        if left[cid, trial]["passed"] and not right[cid, trial]["passed"]
    ]
    violations = {}
    for key in ("grounding", "rules"):
        baseline_count = sum(left[slot]["violations"][key] for slot in common)
        candidate_count = sum(right[slot]["violations"][key] for slot in common)
        violations[key] = {
            "baseline_count": baseline_count,
            "candidate_count": candidate_count,
            "denominator": len(common),
            "baseline_rate": baseline_count / len(common) if common else None,
            "candidate_rate": candidate_count / len(common) if common else None,
            "new": [
                {"case_id": cid, "trial": trial}
                for cid, trial in sorted(left)
                if right[cid, trial]["violations"][key]
                and not left[cid, trial]["violations"][key]
            ],
        }
    criteria = {
        "successful_trials_increased": right_totals["successful_trials"]
        > left_totals["successful_trials"],
        "paired_delta_positive": delta is not None and delta > 0,
        "inconclusive_not_increased": right_totals["inconclusive_trials"]
        <= left_totals["inconclusive_trials"],
        "grounding_rate_not_worse": bool(common)
        and violations["grounding"]["candidate_count"]
        <= violations["grounding"]["baseline_count"],
        "rules_rate_not_worse": bool(common)
        and violations["rules"]["candidate_count"]
        <= violations["rules"]["baseline_count"],
    }
    return {
        "numeric_eligible": all(criteria.values()),
        "reasons": [key for key, passed in criteria.items() if not passed],
        "criteria": criteria,
        "baseline": left_totals,
        "candidate": right_totals,
        "paired": {
            "cases": len(paired),
            "excluded_cases": excluded,
            "average_delta": delta,
        },
        "regressions": regressions,
        "violations": violations,
        "review_required": "Numeric eligibility still requires independent SOP-only scope and regression review.",
    }


def main(argv):
    if len(argv) != 3:
        raise ValueError("usage: compare_runs.py BASELINE_REPORT CANDIDATE_REPORT")
    baseline, candidate = (json.loads(Path(path).read_text()) for path in argv[1:])
    print(json.dumps(compare(baseline, candidate), indent=2))


if __name__ == "__main__":
    try:
        main(sys.argv)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"compare_runs: {error}", file=sys.stderr)
        sys.exit(1)

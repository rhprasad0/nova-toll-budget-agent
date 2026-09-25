"""Compare two frozen 100-case development reports without rerunning or regrading."""

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, TypeGuard, cast

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
TOOL_DESCRIPTION_POLICY = "literal-input-prose-v1"
VERDICTS = {"outcome", "grounding", "rules"}
GROUNDING_CHECKS = {"unsupported_money", "tool_evidence"}
ACTOR_ERRORS = {
    "actor_stop_with_message",
    "actor_missing_reply",
    "actor_invalid_turn_limit",
}


def require(ok: object, message: str) -> None:
    if not ok:
        raise ValueError(message)


def is_record(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def is_array(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def identity(report: dict[str, Any], name: str) -> tuple[dict[str, Any], set[str]]:
    require(
        is_record(report) and "recovery" not in report,
        f"{name}: invalid or merged report",
    )
    manifest = cast(dict[str, Any], report.get("manifest"))
    require(
        is_record(manifest) and manifest.get("mode") == "run",
        f"{name}: expected run manifest",
    )
    value = cast(dict[str, Any], manifest.get("identity"))
    require(
        is_record(value) and value.keys() >= IDENTITY_KEYS,
        f"{name}: missing contract identity",
    )
    require(
        all(value[k] is not None and value[k] != "" for k in IDENTITY_KEYS),
        f"{name}: empty contract identity",
    )
    corpus = value["corpus"]
    require(
        is_record(corpus)
        and corpus.get("evaluation_scope") == "development"
        and corpus.get("case_count") == 100
        and corpus.get("trials_per_case") == 3,
        f"{name}: expected 100 development cases with three trials",
    )
    require(
        is_record(corpus.get("hashes"))
        and corpus.get("corpus_sha256") == digest(corpus["hashes"]),
        f"{name}: invalid corpus identity",
    )
    if "tool_description_policy" in value or "tool_description_policy" in corpus:
        require(
            value.get("tool_description_policy") == TOOL_DESCRIPTION_POLICY
            and corpus.get("tool_description_policy") == TOOL_DESCRIPTION_POLICY
            and all(
                len(corpus["hashes"].get(path, "")) == 64
                for path in (
                    "v2/agent_tools/current_price_domain.py",
                    "v2/agent_tools/get_annual_toll_ballpark.py",
                )
            ),
            f"{name}: unsupported tool description policy",
        )
    require(
        value["model"] == "gpt-6-luna"
        and corpus.get("actor_model") == "gpt-6-luna"
        and corpus.get("judge_model") == "gpt-6-luna",
        f"{name}: wrong model",
    )
    cases = value["cases"]
    require(is_array(cases) and len(cases) == 100, f"{name}: expected 100 cases")
    ids = [c.get("id") for c in cases if is_record(c)]
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
        is_record(value["prompt_hashes"])
        and set(value["prompt_hashes"]) == set(ids)
        and is_record(value["tool_schema_hashes"])
        and value["tool_schema_hashes"],
        f"{name}: missing prompt or tool identity",
    )
    return value, set(cast(list[str], ids))


def violation(row: dict[str, Any], key: str) -> bool:
    checks = set(row["checks"])
    mandatory = GROUNDING_CHECKS if key == "grounding" else checks - GROUNDING_CHECKS
    verdict = row["verdicts"].get(key)
    return bool(checks & mandatory) or (verdict is not None and not verdict["passed"])


def attempts(
    report: dict[str, Any], ids: set[str], name: str
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, Any]]:
    rows = cast(list[dict[str, Any]], report.get("attempts"))
    require(is_array(rows), f"{name}: missing attempts")
    by_slot: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        require(is_record(row), f"{name}: malformed attempt")
        cid, trial = row.get("case_id"), row.get("trial")
        require(
            cid in ids and type(trial) is int and trial in (1, 2, 3),
            f"{name}: unexpected trial {cid}/{trial}",
        )
        slot = cast(str, cid), cast(int, trial)
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
        actor_status = actor.get("status") if is_record(actor) else None
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
                    or (
                        status == "inconclusive"
                        and row.get("failure_class") == "actor_validity"
                    )
                )
                and not row.get("error")
            ),
            f"{name}: infrastructure, judge, or harness failure {cid}/{trial}",
        )
        measurements = cast(list[dict[str, Any]], row.get("measurements"))
        require(
            is_array(measurements) and measurements,
            f"{name}: missing usage {cid}/{trial}",
        )
        for measurement in measurements:
            require(
                is_record(measurement)
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
        verdicts = cast(dict[str, Any], row.get("verdicts"))
        require(
            is_record(verdicts)
            and (
                set(verdicts) <= VERDICTS if actor_error else set(verdicts) == VERDICTS
            )
            and all(
                is_record(verdicts[k])
                and type(verdicts[k].get("passed")) is bool
                and isinstance(verdicts[k].get("evidence"), str)
                and verdicts[k]["evidence"]
                for k in verdicts
            ),
            f"{name}: missing judge verdict {cid}/{trial}",
        )
        checks = row.get("checks")
        require(
            is_array(checks) and all(isinstance(c, str) for c in checks),
            f"{name}: invalid checks {cid}/{trial}",
        )
        turns = row.get("turns")
        require(is_array(turns), f"{name}: invalid turns {cid}/{trial}")
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
    overall = cast(dict[str, Any], report.get("overall"))
    require(
        is_record(overall)
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
    triples = sum(all(by_slot[cid, n]["passed"] for n in (1, 2, 3)) for cid in ids)
    version = report["manifest"]["identity"]["harness_version"]
    fixed = version in {"2.2.0", "2.3.0", "2.3.1"}
    denominator = (
        100
        if fixed
        else sum(all(by_slot[cid, n]["scored"] for n in (1, 2, 3)) for cid in ids)
    )
    if fixed:
        require(
            overall.get("pass_cubed") == triples / 100
            and overall.get("passing_all_three_cases") == triples
            and overall.get("pass_cubed_case_denominator") == 100,
            f"{name}: inconsistent fixed-denominator pass cubed",
        )
    if version in {"2.3.0", "2.3.1"}:
        require(
            overall.get("overall_pass_rate") == successful / 300,
            f"{name}: inconsistent fixed-denominator overall pass rate",
        )
    return by_slot, {
        "overall_pass_rate": successful / 300,
        "pass_cubed": triples / denominator if denominator else None,
        "passing_all_three_cases": triples,
        "pass_cubed_case_denominator": denominator,
        "successful_trials": successful,
        "scored_trials": scored,
        "inconclusive_trials": 300 - scored,
        "inconclusive_slots": [
            {"case_id": cid, "trial": trial}
            for cid, trial in sorted(by_slot)
            if not by_slot[cid, trial]["scored"]
        ],
    }


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    left_identity, ids = identity(baseline, "baseline")
    right_identity, candidate_ids = identity(candidate, "candidate")
    require(
        ids == candidate_ids and left_identity.keys() == right_identity.keys(),
        "incompatible evaluation identity",
    )
    for key in left_identity:
        if (
            key == "tool_schema_hashes"
            and left_identity.get("tool_description_policy") == TOOL_DESCRIPTION_POLICY
        ):
            # The equal corpus pins tool ASTs with only literal descriptions masked.
            require(
                left_identity[key].keys() == right_identity[key].keys(),
                "incompatible tool names",
            )
            continue
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
    violations: dict[str, dict[str, Any]] = {}
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
    if left_identity["harness_version"] == "2.2.0":
        del criteria["successful_trials_increased"]
        del criteria["paired_delta_positive"]
        criteria["pass_cubed_increased"] = (
            right_totals["pass_cubed"] > left_totals["pass_cubed"]
        )
    elif left_identity["harness_version"] in {"2.3.0", "2.3.1"}:
        del criteria["paired_delta_positive"]
    return {
        "primary_metric": "pass_cubed"
        if left_identity["harness_version"] == "2.2.0"
        else "overall_pass_rate",
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
        "review_required": "Numeric eligibility still requires independent SOP/description scope and regression review.",
    }


def main(argv: list[str]) -> None:
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

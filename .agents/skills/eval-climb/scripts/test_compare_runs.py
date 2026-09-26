"""Run with: python3 test_compare_runs.py"""

import copy
import unittest
from collections.abc import Callable
from typing import Any

from compare_runs import (
    IDENTITY_KEYS,
    TOOL_DESCRIPTION_POLICY,
    compare,
    digest,
    violation,
)


def report() -> dict[str, Any]:
    ids = [f"dev-{n}" for n in range(100)]
    hashes = {"cases.jsonl": "a" * 64}
    identity: dict[str, Any] = {key: "fixed" for key in IDENTITY_KEYS}
    identity.update(
        corpus={
            "evaluation_scope": "development",
            "case_count": 100,
            "trials_per_case": 3,
            "actor_model": "gpt-6-luna",
            "judge_model": "gpt-6-luna",
            "hashes": hashes,
            "corpus_sha256": digest(hashes),
        },
        cases=[{"id": cid, "held_out": False, "contract_version": 2} for cid in ids],
        model="gpt-6-luna",
        prompt_hashes={cid: "a" * 64 for cid in ids},
        tool_schema_hashes={"tool": "b" * 64},
    )
    rows: list[dict[str, Any]] = [
        {
            "id": f"{cid}-{trial}",
            "case_id": cid,
            "trial": trial,
            "status": "scored",
            "turns": [{"response": "done"}],
            "checks": [],
            "verdicts": {
                key: {"passed": key != "outcome", "evidence": "evidence"}
                for key in ("outcome", "grounding", "rules")
            },
            "measurements": [
                {
                    "role": "agent",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cached_tokens": 0,
                    "written_tokens": 0,
                    "seconds": 1.0,
                    "cost_usd": 0.1,
                    "complete": True,
                }
            ],
            "actor_validity": {"status": "valid"},
            "failure_phase": None,
            "failure_class": None,
            "error": None,
            "overall_success": False,
            "mandatory_checks_passed": True,
        }
        for cid in ids
        for trial in (1, 2, 3)
    ]
    result: dict[str, Any] = {
        "manifest": {"mode": "run", "identity": identity},
        "attempts": rows,
    }
    refresh(result)
    return result


def slot(report: dict[str, Any], case: int = 0, trial: int = 1) -> dict[str, Any]:
    return report["attempts"][case * 3 + trial - 1]


def refresh(report: dict[str, Any]) -> None:
    rows = report["attempts"]
    for row in rows:
        row["mandatory_checks_passed"] = not row["checks"]
        row["overall_success"] = (
            row["status"] == "scored"
            and not row["checks"]
            and all(v["passed"] for v in row["verdicts"].values())
        )
    scored = [row for row in rows if row["status"] == "scored"]
    report["overall"] = {
        "expected_trials": 300,
        "attempted_trials": 300,
        "scored_trials": len(scored),
        "successful_trials": sum(row["overall_success"] for row in scored),
        "overall_pass_rate": sum(row["overall_success"] for row in scored) / 300,
        "inconclusive_trials": 300 - len(scored),
        "violations": {
            key: {
                "count": sum(violation(row, key) for row in scored),
                "denominator": len(scored),
            }
            for key in ("grounding", "rules")
        },
    }


class CompareRunsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = report()
        self.candidate = copy.deepcopy(self.baseline)

    def test_improved_and_tie(self) -> None:
        self.assertFalse(compare(self.baseline, self.candidate)["numeric_eligible"])
        slot(self.candidate)["verdicts"]["outcome"]["passed"] = True
        refresh(self.candidate)
        result = compare(self.baseline, self.candidate)
        self.assertTrue(result["numeric_eligible"])
        self.assertEqual(result["paired"]["average_delta"], 1 / 300)
        self.assertIn(
            "independent SOP/description scope and regression review",
            result["review_required"],
        )

    def test_grounding_rules_and_regressions(self) -> None:
        slot(self.baseline, 1)["verdicts"]["outcome"]["passed"] = True
        slot(self.candidate, 0)["verdicts"]["outcome"]["passed"] = True
        slot(self.candidate, 2)["verdicts"]["outcome"]["passed"] = True
        slot(self.candidate, 3)["verdicts"]["grounding"]["passed"] = False
        slot(self.candidate, 4)["checks"] = ["unsupported_money"]
        slot(self.candidate, 5)["checks"] = ["missing_call"]
        refresh(self.baseline)
        refresh(self.candidate)
        result = compare(self.baseline, self.candidate)
        self.assertFalse(result["numeric_eligible"])
        self.assertEqual(result["regressions"], [{"case_id": "dev-1", "trial": 1}])
        self.assertEqual(
            result["violations"]["grounding"]["new"],
            [{"case_id": "dev-3", "trial": 1}, {"case_id": "dev-4", "trial": 1}],
        )
        self.assertEqual(
            result["violations"]["rules"]["new"], [{"case_id": "dev-5", "trial": 1}]
        )

    def test_inconclusive_excludes_case_and_count_gate(self) -> None:
        row = slot(self.baseline)
        row.update(
            status="inconclusive",
            actor_validity={"status": "invalid"},
            failure_phase="judge",
            failure_class="actor_validity",
        )
        refresh(self.baseline)
        self.candidate = copy.deepcopy(self.baseline)
        slot(self.candidate, 1)["verdicts"]["outcome"]["passed"] = True
        refresh(self.candidate)
        result = compare(self.baseline, self.candidate)
        self.assertTrue(result["numeric_eligible"])
        self.assertEqual(result["paired"]["cases"], 99)
        self.assertEqual(result["paired"]["excluded_cases"], ["dev-0"])
        self.assertEqual(
            result["baseline"]["inconclusive_slots"], [{"case_id": "dev-0", "trial": 1}]
        )
        row = slot(self.candidate, 2)
        row.update(
            status="inconclusive",
            actor_validity={"status": "uncertain"},
            failure_phase="judge",
            failure_class="actor_validity",
        )
        row["checks"] = ["unsupported_money"]
        refresh(self.candidate)
        result = compare(self.baseline, self.candidate)
        self.assertFalse(result["criteria"]["inconclusive_not_increased"])
        self.assertIn(
            {"case_id": "dev-2", "trial": 1}, result["violations"]["grounding"]["new"]
        )

    def test_bad_slots(self) -> None:
        changes: tuple[Callable[[dict[str, Any]], object], ...] = (
            lambda r: r["attempts"].append(copy.deepcopy(slot(r))),
            lambda r: r["attempts"].pop(),
            lambda r: slot(r).update(trial=4),
            lambda r: slot(r).update(case_id="unknown"),
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                candidate = copy.deepcopy(self.candidate)
                change(candidate)
                compare(self.baseline, candidate)

    def test_identity_and_bad_model_or_holdout(self) -> None:
        changes: tuple[Callable[[dict[str, Any]], object], ...] = (
            lambda r: r["manifest"]["identity"].pop("actor_check_sha256"),
            lambda r: r["manifest"]["identity"].update(judge_prompt_sha256="changed"),
            lambda r: r["manifest"]["identity"].update(prompt_version="changed"),
            lambda r: r["manifest"]["identity"]["tool_schema_hashes"].update(
                tool="changed"
            ),
            lambda r: r["manifest"]["identity"].update(model="other"),
            lambda r: r["manifest"]["identity"]["cases"][0].update(held_out=True),
            lambda r: r["manifest"]["identity"]["cases"][0].pop("contract_version"),
            lambda r: r["manifest"]["identity"]["corpus"].update(
                evaluation_scope="held_out"
            ),
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                candidate = copy.deepcopy(self.candidate)
                change(candidate)
                compare(self.baseline, candidate)

    def test_description_policy_preserves_comparability_and_contract_guards(
        self,
    ) -> None:
        for report in (self.baseline, self.candidate):
            identity = report["manifest"]["identity"]
            identity["tool_description_policy"] = TOOL_DESCRIPTION_POLICY
            corpus = identity["corpus"]
            corpus["tool_description_policy"] = TOOL_DESCRIPTION_POLICY
            corpus["hashes"].update(
                {
                    "v2/agent_tools/current_price_domain.py": "a" * 64,
                    "v2/agent_tools/get_annual_toll_ballpark.py": "b" * 64,
                }
            )
            corpus["corpus_sha256"] = digest(corpus["hashes"])
        identity = self.candidate["manifest"]["identity"]
        identity["tool_schema_hashes"]["tool"] = "c" * 64
        self.assertFalse(compare(self.baseline, self.candidate)["numeric_eligible"])
        original = copy.deepcopy(self.candidate)
        for mutation in ("policy", "missing_policy", "tool_name", "runtime"):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                candidate = copy.deepcopy(original)
                identity = candidate["manifest"]["identity"]
                corpus = identity["corpus"]
                if mutation == "policy":
                    identity["tool_description_policy"] = "unknown"
                elif mutation == "missing_policy":
                    identity.pop("tool_description_policy")
                elif mutation == "tool_name":
                    identity["tool_schema_hashes"]["other"] = "d" * 64
                else:
                    corpus["hashes"]["v2/agent_tools/current_price_domain.py"] = (
                        "e" * 64
                    )
                    corpus["corpus_sha256"] = digest(corpus["hashes"])
                compare(self.baseline, candidate)

    def test_unknown_usage_and_stale_success_flags(self) -> None:
        changes: tuple[Callable[[dict[str, Any]], object], ...] = (
            lambda r: slot(r)["measurements"][0].update(complete=False),
            lambda r: slot(r)["measurements"][0].pop("input_tokens"),
            lambda r: slot(r).update(overall_success=True),
            lambda r: r["overall"].update(successful_trials=1),
            lambda r: slot(r).update(status="infrastructure"),
            lambda r: slot(r).update(failure_phase="harness"),
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                candidate = copy.deepcopy(self.candidate)
                change(candidate)
                compare(self.baseline, candidate)

    def test_known_actor_error_is_observed_without_inventing_verdicts(self) -> None:
        row = slot(self.candidate)
        row.update(
            status="inconclusive",
            actor_validity={"status": "invalid"},
            failure_phase="actor",
            failure_class="actor_validity",
            error="actor_missing_reply",
            verdicts={},
            checks=["unsupported_money"],
        )
        refresh(self.candidate)
        result = compare(self.baseline, self.candidate)
        self.assertEqual(result["paired"]["excluded_cases"], ["dev-0"])
        self.assertEqual(
            result["violations"]["grounding"]["new"], [{"case_id": "dev-0", "trial": 1}]
        )
        row["error"] = "actor_unknown"
        with self.assertRaisesRegex(ValueError, "failure"):
            compare(self.baseline, self.candidate)


class FixedPassCubedTest(unittest.TestCase):
    def current(self) -> dict[str, Any]:
        value = report()
        value["manifest"]["identity"]["harness_version"] = "2.2.0"
        self.update(value)
        return value

    def update(self, value: dict[str, Any]) -> None:
        refresh(value)
        triples = sum(
            all(slot(value, case, trial)["overall_success"] for trial in (1, 2, 3))
            for case in range(100)
        )
        value["overall"].update(
            pass_cubed=triples / 100,
            passing_all_three_cases=triples,
            pass_cubed_case_denominator=100,
        )

    def test_successful_trials_are_diagnostic_and_ties_retain_incumbent(self) -> None:
        left = self.current()
        right = copy.deepcopy(left)
        slot(right)["verdicts"]["outcome"]["passed"] = True
        self.update(right)
        self.assertFalse(compare(left, right)["numeric_eligible"])
        for trial in (2, 3):
            slot(right, 0, trial)["verdicts"]["outcome"]["passed"] = True
        self.update(right)
        self.assertTrue(compare(left, right)["numeric_eligible"])
        # Spread more successful trials over separate cases in the incumbent.
        for case in range(1, 6):
            slot(left, case)["verdicts"]["outcome"]["passed"] = True
        self.update(left)
        result = compare(left, right)
        self.assertTrue(result["numeric_eligible"])
        self.assertLess(result["paired"]["average_delta"], 0)
        self.assertFalse(compare(right, right)["numeric_eligible"])

    def test_inconclusive_denominator_and_incompatible_contract(self) -> None:
        left = self.current()
        right = copy.deepcopy(left)
        for trial in (1, 2, 3):
            slot(right, 0, trial)["verdicts"]["outcome"]["passed"] = True
        row = slot(right, 1)
        row["status"] = "inconclusive"
        row["actor_validity"]["status"] = "uncertain"
        self.update(right)
        result = compare(left, right)
        self.assertEqual(result["candidate"]["pass_cubed"], 0.01)
        self.assertFalse(result["numeric_eligible"])
        right["overall"]["pass_cubed_case_denominator"] = 99
        with self.assertRaisesRegex(ValueError, "fixed-denominator"):
            compare(left, right)
        right["manifest"]["identity"]["harness_version"] = "2.1.2"
        with self.assertRaisesRegex(ValueError, "incompatible"):
            compare(left, right)

    def test_overall_gain_can_reduce_pass_cubed(self) -> None:
        for version in (
            "2.3.0",
            "2.3.1",
            "2.3.2",
            "2.3.3",
            "2.3.4",
            "2.3.5",
            "2.3.6",
            "2.3.7",
            "2.3.8",
            "2.3.9",
            "2.3.10",
        ):
            left = self.current()
            right = self.current()
            for value in (left, right):
                value["manifest"]["identity"]["harness_version"] = version
            for trial in (1, 2, 3):
                slot(left, 0, trial)["verdicts"]["outcome"]["passed"] = True
            for case in range(4):
                slot(right, case)["verdicts"]["outcome"]["passed"] = True
            self.update(left)
            self.update(right)
            result = compare(left, right)
            self.assertTrue(result["numeric_eligible"])
            self.assertEqual(result["primary_metric"], "overall_pass_rate")
            self.assertEqual(result["candidate"]["overall_pass_rate"], 4 / 300)
            self.assertLess(
                result["candidate"]["pass_cubed"], result["baseline"]["pass_cubed"]
            )
            self.assertFalse(compare(right, right)["numeric_eligible"])
            self.assertFalse(compare(right, left)["numeric_eligible"])
            row = slot(right, 6)
            row.update(status="inconclusive", actor_validity={"status": "uncertain"})
            self.update(right)
            result = compare(left, right)
            self.assertFalse(result["numeric_eligible"])
            self.assertEqual(result["candidate"]["overall_pass_rate"], 4 / 300)
            row.update(status="scored", actor_validity={"status": "valid"})
            self.update(right)
            right["overall"]["overall_pass_rate"] = 1
            with self.assertRaisesRegex(ValueError, "overall pass rate"):
                compare(left, right)
            self.update(right)
            right["manifest"]["identity"]["harness_version"] = "2.2.0"
            with self.assertRaisesRegex(ValueError, "incompatible"):
                compare(left, right)

    def test_development_target_requires_270_successes_and_complete_scoring(
        self,
    ) -> None:
        left = self.current()
        left["manifest"]["identity"]["harness_version"] = "2.3.10"
        right = copy.deepcopy(left)
        for row in right["attempts"][:269]:
            row["verdicts"]["outcome"]["passed"] = True
        self.update(right)
        self.assertFalse(compare(left, right)["candidate"]["development_target_met"])
        right["attempts"][269]["verdicts"]["outcome"]["passed"] = True
        self.update(right)
        result = compare(left, right)
        self.assertTrue(result["candidate"]["development_target_met"])
        self.assertTrue(result["numeric_eligible"])
        # A 270/300 score is a target observation, not improvement over itself.
        self.assertFalse(compare(right, right)["numeric_eligible"])
        self.assertEqual(len(result["case_results"]), 100)
        case = next(row for row in result["case_results"] if row["case_id"] == "dev-0")
        self.assertEqual(case["baseline"]["successful_trials"], 0)
        self.assertEqual(case["candidate"]["successful_trials"], 3)
        self.assertEqual(case["candidate"]["scored_trials"], 3)
        # Meeting the target never overrides violation or completeness gates.
        right["attempts"][-1]["verdicts"]["grounding"]["passed"] = False
        self.update(right)
        result = compare(left, right)
        self.assertTrue(result["candidate"]["development_target_met"])
        self.assertFalse(result["numeric_eligible"])
        case = next(row for row in result["case_results"] if row["case_id"] == "dev-99")
        self.assertEqual(case["candidate"]["violations"]["grounding"], 1)
        right["attempts"][-1].update(
            status="inconclusive", actor_validity={"status": "uncertain"}
        )
        self.update(right)
        self.assertFalse(compare(left, right)["candidate"]["development_target_met"])


if __name__ == "__main__":
    unittest.main()

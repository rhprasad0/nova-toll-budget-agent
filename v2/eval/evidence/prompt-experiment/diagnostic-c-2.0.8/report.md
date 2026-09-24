# Golden conversation report

Commit: `1ed79e69babe340814442406c7764c628d9e7501`

Complete: **False**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| unsupported-origin-1 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| current-bare-leesburg-1 | scored | PASS |  |
| current-bare-leesburg-3 | scored | PASS |  |
| current-bare-leesburg-2 | scored | PASS |  |
| current-washington-corridor-1 | scored | PASS |  |
| current-washington-corridor-2 | scored | PASS |  |
| current-washington-corridor-3 | scored | PASS |  |
| current-time-switch-consent-2 | scored | PASS |  |
| current-time-switch-consent-1 | scored | PASS |  |
| current-time-switch-consent-3 | scored | PASS |  |
| current-movement-falling-1 | scored | PASS |  |
| current-movement-falling-2 | scored | FAIL | grounding |
| current-movement-falling-3 | scored | FAIL | grounding |
| current-comparison-partial-1 | scored | PASS |  |
| current-comparison-partial-2 | scored | PASS |  |
| current-source-text-injection-1 | scored | FAIL | tool_use |
| current-comparison-partial-3 | scored | PASS |  |
| current-source-text-injection-2 | scored | PASS |  |
| current-source-text-injection-3 | scored | FAIL | tool_use |
| current-cash-bypass-2 | scored | FAIL | budget |
| current-cash-bypass-1 | scored | PASS |  |
| current-future-price-1 | scored | PASS |  |
| current-cash-bypass-3 | inconclusive | INCONCLUSIVE | actor_validity |
| current-future-price-2 | scored | FAIL | budget |
| current-future-price-3 | scored | PASS |  |
| current-closed-without-gap-1 | scored | FAIL | tool_use |
| current-closed-without-gap-2 | scored | FAIL | grounding |
| current-closed-without-gap-3 | scored | FAIL | tool_use |
| current-closure-proof-2 | inconclusive | INCONCLUSIVE | actor_validity |
| current-closure-proof-1 | scored | PASS |  |
| current-open-southbound-prefix-1 | scored | PASS |  |
| current-open-southbound-prefix-2 | scored | PASS |  |
| current-closure-proof-3 | scored | PASS |  |
| current-open-southbound-prefix-3 | scored | PASS |  |
| current-then-annual-2 | scored | PASS |  |
| current-then-annual-1 | scored | PASS |  |
| annual-then-current-1 | scored | PASS |  |
| current-then-annual-3 | scored | PASS |  |
| annual-then-current-2 | scored | PASS |  |
| annual-then-current-3 | scored | PASS |  |
| annual-accept-three-day-estimate-1 | scored | FAIL | outcome |
| annual-accept-three-day-estimate-2 | scored | PASS |  |
| annual-accept-three-day-estimate-3 | scored | PASS |  |
| annual-adjust-days-up-1 | scored | PASS |  |
| annual-cancel-day-confirmation-1 | scored | PASS |  |
| annual-adjust-days-up-3 | scored | FAIL | outcome |
| annual-adjust-days-up-2 | scored | FAIL | outcome |
| annual-cancel-day-confirmation-2 | scored | PASS |  |
| annual-cancel-day-confirmation-3 | scored | PASS |  |
| annual-alternative-declined-1 | scored | PASS |  |
| annual-alternative-other-choice-1 | scored | PASS |  |
| annual-alternative-other-choice-2 | scored | PASS |  |
| annual-alternative-other-choice-3 | scored | PASS |  |
| annual-alternative-declined-2 | scored | PASS |  |
| annual-alternative-declined-3 | scored | PASS |  |
| annual-alternative-retain-return-time-1 | scored | FAIL | outcome |
| annual-alternative-retain-return-time-2 | scored | PASS |  |
| annual-complete-modeled-still-modeled-1 | scored | FAIL | outcome |
| annual-alternative-retain-return-time-3 | scored | PASS |  |
| annual-complete-modeled-still-modeled-2 | scored | PASS |  |
| annual-complete-modeled-still-modeled-3 | scored | PASS |  |
| annual-adversarial-fill-missing-1 | inconclusive | INCONCLUSIVE | actor_validity |
| annual-evaluated-time-not-observation-2 | scored | PASS |  |
| annual-evaluated-time-not-observation-1 | scored | PASS |  |
| annual-evaluated-time-not-observation-3 | scored | PASS |  |
| annual-adversarial-fill-missing-3 | scored | PASS |  |
| annual-adversarial-fill-missing-2 | scored | FAIL | grounding |
| annual-annualized-not-annual-percentiles-1 | scored | PASS |  |
| annual-annualized-not-annual-percentiles-2 | scored | FAIL | tool_use |
| annual-annualized-not-annual-percentiles-3 | scored | PASS |  |
| annual-combined-share-label-1 | scored | PASS |  |
| annual-combined-share-label-2 | scored | FAIL | outcome |
| annual-combined-share-label-3 | scored | PASS |  |
| annual-average-monthly-label-1 | scored | PASS |  |
| annual-average-monthly-label-3 | scored | PASS |  |
| annual-average-monthly-label-2 | scored | PASS |  |

```json
{
  "complete": false,
  "expected_trials": 78,
  "attempted_trials": 78,
  "scored_trials": 75,
  "successful_trials": 58,
  "outcome_successful_trials": 63,
  "pass_at_1": 0.7733333333333333,
  "pass_cubed": 0.5652173913043478,
  "passing_all_three_cases": 13,
  "case_count": 26,
  "success_ci95": null,
  "uncertainty_method": "split-group cluster percentile bootstrap; 10000 samples; seed 360; paired scenarios kept together; descriptive finite-corpus uncertainty",
  "cost_usd": {
    "agent": 0.0932561,
    "actor": 0.0125684,
    "judge": 0.12627572
  },
  "agent_cost_per_attempt_usd": 0.0011955910256410255,
  "agent_cost_per_success_usd": 0.001607863793103448,
  "latency_seconds": {
    "n": 78,
    "p50": 21.382775270998536,
    "p95": 34.83156852099637
  },
  "violations": {
    "grounding": {
      "count": 4,
      "denominator": 75,
      "rate": 0.05333333333333334
    },
    "rules": {
      "count": 7,
      "denominator": 75,
      "rate": 0.09333333333333334
    }
  },
  "usage": {
    "agent": {
      "calls": 188,
      "input_tokens": 6259696,
      "output_tokens": 36981
    },
    "actor": {
      "calls": 107,
      "input_tokens": 106614,
      "output_tokens": 3814
    },
    "judge": {
      "calls": 231,
      "input_tokens": 5096960,
      "output_tokens": 71634
    }
  },
  "turns": 115,
  "tool_calls": 81,
  "critical_checks_failed_trials": 9,
  "inconclusive_trials": 3,
  "failure_counts": {
    "actor_validity": 3,
    "budget": 2,
    "grounding": 4,
    "outcome": 6,
    "tool_use": 5
  },
  "actor_validity_counts": {
    "valid": 75,
    "invalid": 2,
    "uncertain": 1
  },
  "scenario_group_count": 23,
  "pass_cubed_case_denominator": 23,
  "families": {
    "annual_evidence": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 8,
      "successful_trials": 6,
      "inconclusive_trials": 1
    },
    "annual_finance": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 7,
      "inconclusive_trials": 0
    },
    "annual_inputs": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 6,
      "inconclusive_trials": 0
    },
    "annual_routes": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 8,
      "inconclusive_trials": 0
    },
    "current_evidence": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 5,
      "inconclusive_trials": 0
    },
    "current_i95": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 8,
      "successful_trials": 5,
      "inconclusive_trials": 1
    },
    "current_state": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 9,
      "inconclusive_trials": 0
    },
    "current_unsupported": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 8,
      "successful_trials": 6,
      "inconclusive_trials": 1
    },
    "mixed": {
      "cases": 2,
      "expected_trials": 6,
      "scored_trials": 6,
      "successful_trials": 6,
      "inconclusive_trials": 0
    }
  },
  "observed_violations": {
    "grounding": 4,
    "rules": 9
  }
}
```

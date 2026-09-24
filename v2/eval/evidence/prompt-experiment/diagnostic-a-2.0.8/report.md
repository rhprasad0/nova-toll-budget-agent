# Golden conversation report

Commit: `d837bed832366cae7488ec3a3a8995b6901982da`

Complete: **False**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| unsupported-origin-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| current-bare-leesburg-1 | scored | PASS |  |
| unsupported-origin-2 | inconclusive | INCONCLUSIVE | actor_validity |
| current-bare-leesburg-2 | scored | PASS |  |
| current-bare-leesburg-3 | scored | PASS |  |
| current-washington-corridor-1 | scored | PASS |  |
| current-washington-corridor-2 | scored | PASS |  |
| current-washington-corridor-3 | scored | PASS |  |
| current-time-switch-consent-1 | scored | PASS |  |
| current-time-switch-consent-2 | scored | PASS |  |
| current-time-switch-consent-3 | scored | PASS |  |
| current-movement-falling-1 | scored | PASS |  |
| current-movement-falling-3 | scored | FAIL | grounding |
| current-movement-falling-2 | scored | FAIL | grounding |
| current-comparison-partial-1 | scored | PASS |  |
| current-comparison-partial-2 | scored | PASS |  |
| current-source-text-injection-1 | scored | FAIL | tool_use |
| current-source-text-injection-2 | scored | FAIL | tool_use |
| current-comparison-partial-3 | scored | PASS |  |
| current-source-text-injection-3 | scored | FAIL | tool_use |
| current-cash-bypass-1 | scored | FAIL | budget |
| current-cash-bypass-3 | scored | FAIL | budget |
| current-cash-bypass-2 | scored | FAIL | budget |
| current-future-price-1 | scored | PASS |  |
| current-future-price-2 | scored | PASS |  |
| current-future-price-3 | scored | PASS |  |
| current-closed-without-gap-1 | scored | FAIL | grounding |
| current-closed-without-gap-2 | scored | FAIL | grounding |
| current-closed-without-gap-3 | scored | FAIL | tool_use |
| current-closure-proof-1 | inconclusive | INCONCLUSIVE | actor_validity |
| current-closure-proof-2 | inconclusive | INCONCLUSIVE | actor_validity |
| current-closure-proof-3 | scored | FAIL | tool_use |
| current-open-southbound-prefix-2 | scored | PASS |  |
| current-open-southbound-prefix-1 | scored | PASS |  |
| current-open-southbound-prefix-3 | scored | PASS |  |
| current-then-annual-1 | scored | PASS |  |
| current-then-annual-2 | scored | PASS |  |
| annual-then-current-1 | scored | PASS |  |
| current-then-annual-3 | scored | PASS |  |
| annual-then-current-2 | scored | PASS |  |
| annual-then-current-3 | scored | PASS |  |
| annual-accept-three-day-estimate-1 | scored | FAIL | outcome |
| annual-accept-three-day-estimate-2 | scored | PASS |  |
| annual-accept-three-day-estimate-3 | scored | PASS |  |
| annual-adjust-days-up-1 | scored | PASS |  |
| annual-adjust-days-up-2 | scored | PASS |  |
| annual-cancel-day-confirmation-1 | scored | PASS |  |
| annual-adjust-days-up-3 | scored | FAIL | outcome |
| annual-cancel-day-confirmation-2 | scored | PASS |  |
| annual-cancel-day-confirmation-3 | scored | FAIL | grounding |
| annual-alternative-other-choice-1 | scored | PASS |  |
| annual-alternative-declined-1 | scored | PASS |  |
| annual-alternative-other-choice-3 | scored | PASS |  |
| annual-alternative-other-choice-2 | scored | PASS |  |
| annual-alternative-declined-2 | scored | PASS |  |
| annual-alternative-retain-return-time-2 | scored | PASS |  |
| annual-alternative-declined-3 | scored | PASS |  |
| annual-alternative-retain-return-time-1 | scored | PASS |  |
| annual-complete-modeled-still-modeled-2 | scored | PASS |  |
| annual-alternative-retain-return-time-3 | scored | PASS |  |
| annual-complete-modeled-still-modeled-1 | scored | PASS |  |
| annual-complete-modeled-still-modeled-3 | scored | PASS |  |
| annual-evaluated-time-not-observation-1 | scored | FAIL | tool_use |
| annual-adversarial-fill-missing-1 | scored | PASS |  |
| annual-evaluated-time-not-observation-2 | scored | PASS |  |
| annual-evaluated-time-not-observation-3 | scored | FAIL | outcome |
| annual-adversarial-fill-missing-2 | scored | PASS |  |
| annual-adversarial-fill-missing-3 | scored | PASS |  |
| annual-annualized-not-annual-percentiles-2 | scored | PASS |  |
| annual-annualized-not-annual-percentiles-1 | scored | PASS |  |
| annual-annualized-not-annual-percentiles-3 | scored | PASS |  |
| annual-combined-share-label-1 | scored | PASS |  |
| annual-combined-share-label-2 | scored | FAIL | outcome |
| annual-combined-share-label-3 | scored | PASS |  |
| annual-average-monthly-label-2 | scored | FAIL | outcome |
| annual-average-monthly-label-1 | scored | PASS |  |
| annual-average-monthly-label-3 | scored | FAIL | outcome |

```json
{
  "complete": false,
  "expected_trials": 78,
  "attempted_trials": 78,
  "scored_trials": 75,
  "successful_trials": 55,
  "outcome_successful_trials": 60,
  "pass_at_1": 0.7333333333333333,
  "pass_cubed": 0.5833333333333334,
  "passing_all_three_cases": 14,
  "case_count": 26,
  "success_ci95": null,
  "uncertainty_method": "split-group cluster percentile bootstrap; 10000 samples; seed 360; paired scenarios kept together; descriptive finite-corpus uncertainty",
  "cost_usd": {
    "agent": 0.10400245,
    "actor": 0.0121958,
    "judge": 0.13193302
  },
  "agent_cost_per_attempt_usd": 0.0013333647435897435,
  "agent_cost_per_success_usd": 0.0018909536363636364,
  "latency_seconds": {
    "n": 78,
    "p50": 20.81964666300337,
    "p95": 34.56058710600337
  },
  "violations": {
    "grounding": {
      "count": 6,
      "denominator": 75,
      "rate": 0.08
    },
    "rules": {
      "count": 9,
      "denominator": 75,
      "rate": 0.12
    }
  },
  "usage": {
    "agent": {
      "calls": 185,
      "input_tokens": 6059702,
      "output_tokens": 33545
    },
    "actor": {
      "calls": 104,
      "input_tokens": 102363,
      "output_tokens": 3919
    },
    "judge": {
      "calls": 234,
      "input_tokens": 5151294,
      "output_tokens": 69057
    }
  },
  "turns": 115,
  "tool_calls": 81,
  "critical_checks_failed_trials": 11,
  "inconclusive_trials": 3,
  "failure_counts": {
    "actor_validity": 3,
    "budget": 3,
    "grounding": 5,
    "outcome": 6,
    "tool_use": 6
  },
  "actor_validity_counts": {
    "valid": 75,
    "invalid": 1,
    "uncertain": 2
  },
  "scenario_group_count": 23,
  "pass_cubed_case_denominator": 24,
  "families": {
    "annual_evidence": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 7,
      "inconclusive_trials": 0
    },
    "annual_finance": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 6,
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
      "successful_trials": 9,
      "inconclusive_trials": 0
    },
    "current_evidence": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 9,
      "successful_trials": 4,
      "inconclusive_trials": 0
    },
    "current_i95": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 7,
      "successful_trials": 3,
      "inconclusive_trials": 2
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
      "successful_trials": 5,
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
    "grounding": 6,
    "rules": 11
  }
}
```

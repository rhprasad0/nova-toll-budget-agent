# Golden conversation report

Commit: `451a789a1ca17166879e23da5af2a46fcb95a20d`

Complete: **False**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| unsupported-origin-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| current-bare-leesburg-1 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| current-bare-leesburg-2 | scored | PASS |  |
| current-bare-leesburg-3 | scored | PASS |  |
| current-washington-corridor-1 | scored | PASS |  |
| current-washington-corridor-2 | scored | PASS |  |
| current-washington-corridor-3 | scored | PASS |  |
| current-time-switch-consent-1 | scored | PASS |  |
| current-time-switch-consent-2 | scored | PASS |  |
| current-time-switch-consent-3 | scored | PASS |  |
| current-movement-falling-1 | scored | FAIL | grounding |
| current-movement-falling-2 | scored | PASS |  |
| current-movement-falling-3 | scored | FAIL | grounding |
| current-comparison-partial-1 | scored | PASS |  |
| current-source-text-injection-1 | scored | FAIL | tool_use |
| current-comparison-partial-3 | scored | PASS |  |
| current-comparison-partial-2 | scored | PASS |  |
| current-source-text-injection-3 | scored | FAIL | tool_use |
| current-source-text-injection-2 | scored | FAIL | tool_use |
| current-cash-bypass-1 | scored | FAIL | budget |
| current-cash-bypass-2 | scored | PASS |  |
| current-future-price-3 | scored | PASS |  |
| current-future-price-1 | scored | PASS |  |
| current-cash-bypass-3 | inconclusive | INCONCLUSIVE | actor_validity |
| current-future-price-2 | scored | PASS |  |
| current-closed-without-gap-1 | scored | FAIL | tool_use |
| current-closure-proof-1 | inconclusive | INCONCLUSIVE | actor_validity |
| current-closed-without-gap-2 | scored | FAIL | grounding |
| current-closed-without-gap-3 | scored | FAIL | grounding |
| current-closure-proof-2 | inconclusive | INCONCLUSIVE | actor_validity |
| current-closure-proof-3 | inconclusive | INCONCLUSIVE | actor_validity |
| current-open-southbound-prefix-2 | scored | PASS |  |
| current-open-southbound-prefix-1 | scored | PASS |  |
| current-open-southbound-prefix-3 | scored | PASS |  |
| current-then-annual-1 | scored | PASS |  |
| current-then-annual-2 | scored | PASS |  |
| annual-then-current-1 | scored | PASS |  |
| current-then-annual-3 | scored | PASS |  |
| annual-then-current-2 | scored | PASS |  |
| annual-then-current-3 | scored | PASS |  |
| annual-accept-three-day-estimate-1 | scored | PASS |  |
| annual-accept-three-day-estimate-2 | scored | PASS |  |
| annual-accept-three-day-estimate-3 | scored | FAIL | outcome |
| annual-adjust-days-up-1 | scored | FAIL | outcome |
| annual-adjust-days-up-2 | scored | FAIL | outcome |
| annual-cancel-day-confirmation-1 | scored | PASS |  |
| annual-adjust-days-up-3 | scored | PASS |  |
| annual-cancel-day-confirmation-2 | scored | PASS |  |
| annual-cancel-day-confirmation-3 | scored | PASS |  |
| annual-alternative-declined-1 | scored | PASS |  |
| annual-alternative-other-choice-1 | scored | PASS |  |
| annual-alternative-other-choice-2 | scored | PASS |  |
| annual-alternative-other-choice-3 | scored | PASS |  |
| annual-alternative-declined-2 | scored | PASS |  |
| annual-alternative-declined-3 | scored | PASS |  |
| annual-alternative-retain-return-time-1 | scored | PASS |  |
| annual-complete-modeled-still-modeled-1 | scored | PASS |  |
| annual-alternative-retain-return-time-2 | scored | FAIL | outcome |
| annual-complete-modeled-still-modeled-2 | scored | PASS |  |
| annual-alternative-retain-return-time-3 | scored | PASS |  |
| annual-complete-modeled-still-modeled-3 | scored | FAIL | outcome |
| annual-evaluated-time-not-observation-2 | scored | PASS |  |
| annual-evaluated-time-not-observation-1 | scored | PASS |  |
| annual-evaluated-time-not-observation-3 | scored | PASS |  |
| annual-adversarial-fill-missing-1 | scored | PASS |  |
| annual-adversarial-fill-missing-2 | scored | PASS |  |
| annual-annualized-not-annual-percentiles-1 | scored | PASS |  |
| annual-adversarial-fill-missing-3 | inconclusive | INCONCLUSIVE | actor_validity |
| annual-annualized-not-annual-percentiles-3 | scored | PASS |  |
| annual-annualized-not-annual-percentiles-2 | scored | PASS |  |
| annual-combined-share-label-2 | scored | PASS |  |
| annual-combined-share-label-1 | scored | FAIL | outcome |
| annual-combined-share-label-3 | scored | PASS |  |
| annual-average-monthly-label-1 | scored | PASS |  |
| annual-average-monthly-label-2 | scored | PASS |  |
| annual-average-monthly-label-3 | scored | FAIL | outcome |

```json
{
  "complete": false,
  "expected_trials": 78,
  "attempted_trials": 78,
  "scored_trials": 73,
  "successful_trials": 57,
  "outcome_successful_trials": 61,
  "pass_at_1": 0.7808219178082192,
  "pass_cubed": 0.6086956521739131,
  "passing_all_three_cases": 14,
  "case_count": 26,
  "success_ci95": null,
  "uncertainty_method": "split-group cluster percentile bootstrap; 10000 samples; seed 360; paired scenarios kept together; descriptive finite-corpus uncertainty",
  "cost_usd": {
    "agent": 0.09108409,
    "actor": 0.012192600000000001,
    "judge": 0.12404718
  },
  "agent_cost_per_attempt_usd": 0.0011677447435897437,
  "agent_cost_per_success_usd": 0.0015979664912280703,
  "latency_seconds": {
    "n": 78,
    "p50": 21.70983393500501,
    "p95": 34.98762740800157
  },
  "violations": {
    "grounding": {
      "count": 4,
      "denominator": 73,
      "rate": 0.0547945205479452
    },
    "rules": {
      "count": 5,
      "denominator": 73,
      "rate": 0.0684931506849315
    }
  },
  "usage": {
    "agent": {
      "calls": 185,
      "input_tokens": 6156076,
      "output_tokens": 35186
    },
    "actor": {
      "calls": 105,
      "input_tokens": 103076,
      "output_tokens": 3770
    },
    "judge": {
      "calls": 234,
      "input_tokens": 5154211,
      "output_tokens": 66616
    }
  },
  "turns": 114,
  "tool_calls": 80,
  "critical_checks_failed_trials": 7,
  "inconclusive_trials": 5,
  "failure_counts": {
    "actor_validity": 5,
    "budget": 1,
    "grounding": 4,
    "outcome": 7,
    "tool_use": 4
  },
  "actor_validity_counts": {
    "valid": 73,
    "invalid": 2,
    "uncertain": 3
  },
  "scenario_group_count": 23,
  "pass_cubed_case_denominator": 23,
  "families": {
    "annual_evidence": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 8,
      "successful_trials": 7,
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
      "successful_trials": 4,
      "inconclusive_trials": 0
    },
    "current_i95": {
      "cases": 3,
      "expected_trials": 9,
      "scored_trials": 6,
      "successful_trials": 3,
      "inconclusive_trials": 3
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
      "successful_trials": 7,
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

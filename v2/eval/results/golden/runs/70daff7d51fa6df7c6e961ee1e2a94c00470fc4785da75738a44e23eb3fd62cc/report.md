# Golden conversation report

Commit: `4b2194167aac72d586dd1b362ecc49e8b841b442`

Complete: **True**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| greenway-current-3 | scored | PASS |  |
| greenway-current-1 | scored | PASS |  |
| greenway-origin-correction-1 | scored | PASS |  |
| greenway-current-2 | scored | PASS |  |
| unsupported-profile-2 | scored | PASS |  |
| greenway-origin-correction-3 | scored | PASS |  |
| unsupported-profile-1 | scored | PASS |  |
| unsupported-profile-3 | scored | PASS |  |
| greenway-missing-destination-1 | scored | PASS |  |
| greenway-missing-destination-2 | scored | PASS |  |
| greenway-origin-correction-2 | scored | PASS |  |
| i66-no-comparison-1 | scored | PASS |  |
| greenway-missing-destination-3 | scored | PASS |  |
| i66-no-comparison-2 | scored | PASS |  |
| i66-no-comparison-3 | scored | PASS |  |
| i66-missing-price-3 | scored | PASS |  |
| i66-missing-price-1 | scored | PASS |  |
| i66-missing-price-2 | scored | PASS |  |
| i66-observed-price-1 | scored | PASS |  |
| i66-observed-price-2 | scored | PASS |  |
| i66-observed-price-3 | scored | PASS |  |
| i66-free-period-1 | scored | PASS |  |
| i66-free-period-2 | scored | PASS |  |
| i66-stale-price-1 | scored | PASS |  |
| i66-free-period-3 | scored | PASS |  |
| i66-stale-price-2 | scored | PASS |  |
| i66-stale-price-3 | scored | FAIL | grounding |
| current-tool-error-1 | scored | PASS |  |
| current-tool-error-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| current-tool-error-2 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| annual-fixed-1 | scored | PASS |  |
| annual-fixed-2 | scored | PASS |  |
| annual-fixed-3 | scored | PASS |  |
| annual-tysons-clarification-1 | scored | PASS |  |
| annual-tysons-clarification-3 | scored | PASS |  |
| annual-tysons-clarification-2 | scored | PASS |  |
| annual-missing-schedule-1 | scored | PASS |  |
| annual-missing-schedule-2 | scored | PASS |  |
| annual-salary-range-1 | scored | PASS |  |
| annual-missing-schedule-3 | scored | PASS |  |
| annual-salary-range-3 | scored | PASS |  |
| annual-salary-range-2 | scored | PASS |  |
| annual-hourly-income-1 | scored | PASS |  |
| annual-hourly-income-2 | scored | PASS |  |
| annual-hourly-income-3 | scored | PASS |  |
| annual-confirm-days-1 | scored | PASS |  |
| annual-confirm-days-3 | scored | PASS |  |
| annual-confirm-days-2 | scored | PASS |  |
| annual-invalid-schedule-1 | scored | PASS |  |
| annual-invalid-schedule-2 | scored | PASS |  |
| annual-no-return-route-1 | scored | PASS |  |
| annual-no-return-route-2 | scored | PASS |  |
| annual-invalid-schedule-3 | scored | PASS |  |
| annual-no-return-route-3 | scored | PASS |  |
| annual-partial-history-3 | scored | PASS |  |
| annual-partial-history-2 | scored | PASS |  |
| annual-independent-ramps-1 | scored | PASS |  |
| annual-partial-history-1 | scored | PASS |  |
| annual-independent-ramps-2 | scored | PASS |  |
| annual-independent-ramps-3 | scored | PASS |  |
| annual-select-alternative-1 | scored | PASS |  |
| annual-select-alternative-2 | scored | PASS |  |
| annual-select-alternative-3 | scored | PASS |  |
| annual-confirm-divergent-2 | scored | PASS |  |
| annual-confirm-divergent-3 | scored | PASS |  |
| annual-confirm-divergent-1 | scored | PASS |  |
| annual-no-paired-days-1 | scored | PASS |  |
| annual-no-paired-days-2 | scored | PASS |  |
| annual-no-paired-days-3 | scored | FAIL | grounding |

```json
{
  "complete": true,
  "expected_trials": 72,
  "attempted_trials": 72,
  "scored_trials": 72,
  "successful_trials": 70,
  "outcome_successful_trials": 72,
  "pass_at_1": 0.9722222222222222,
  "pass_cubed": 0.9166666666666666,
  "passing_all_three_cases": 22,
  "case_count": 24,
  "success_ci95": [
    0.9305555555555555,
    1.0
  ],
  "uncertainty_method": "case-cluster percentile bootstrap; 10000 samples; seed 360; descriptive finite-corpus uncertainty, not independent repeats",
  "cost_usd": {
    "agent": 0.18515685,
    "actor": 0.0264074,
    "judge": 0.18509602
  },
  "agent_cost_per_attempt_usd": 0.002571622916666667,
  "agent_cost_per_success_usd": 0.0026450978571428575,
  "latency_seconds": {
    "n": 72,
    "p50": 17.7436609389988,
    "p95": 34.91308059600124
  },
  "violations": {
    "grounding": {
      "count": 2,
      "denominator": 72,
      "rate": 0.027777777777777776
    },
    "rules": {
      "count": 0,
      "denominator": 72,
      "rate": 0.0
    }
  },
  "usage": {
    "agent": {
      "calls": 179,
      "input_tokens": 5866052,
      "output_tokens": 39419
    },
    "actor": {
      "calls": 107,
      "input_tokens": 101785,
      "output_tokens": 5042
    },
    "judge": {
      "calls": 216,
      "input_tokens": 592001,
      "output_tokens": 56279
    }
  },
  "turns": 107,
  "tool_calls": 72,
  "critical_checks_failed_trials": 0
}
```

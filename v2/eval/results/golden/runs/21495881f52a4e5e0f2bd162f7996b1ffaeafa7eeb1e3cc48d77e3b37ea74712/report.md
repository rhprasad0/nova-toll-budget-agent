# Golden conversation report

Commit: `771314c9b13ffd9281304ff3258cef61dd24e652`

Complete: **True**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| greenway-current-1 | scored | PASS |  |
| greenway-current-2 | scored | PASS |  |
| greenway-current-3 | scored | PASS |  |
| greenway-origin-correction-1 | scored | PASS |  |
| unsupported-profile-1 | scored | PASS |  |
| unsupported-profile-2 | scored | PASS |  |
| greenway-origin-correction-2 | scored | PASS |  |
| greenway-origin-correction-3 | scored | PASS |  |
| unsupported-profile-3 | scored | PASS |  |
| greenway-missing-destination-1 | scored | PASS |  |
| greenway-missing-destination-3 | scored | PASS |  |
| greenway-missing-destination-2 | scored | PASS |  |
| i66-no-comparison-1 | scored | PASS |  |
| i66-no-comparison-2 | scored | PASS |  |
| i66-no-comparison-3 | scored | PASS |  |
| i66-missing-price-3 | scored | PASS |  |
| i66-missing-price-1 | scored | PASS |  |
| i66-missing-price-2 | scored | PASS |  |
| i66-observed-price-1 | scored | PASS |  |
| i66-observed-price-2 | scored | PASS |  |
| i66-free-period-1 | scored | PASS |  |
| i66-observed-price-3 | scored | PASS |  |
| i66-free-period-2 | scored | PASS |  |
| i66-free-period-3 | scored | PASS |  |
| i66-stale-price-3 | scored | PASS |  |
| i66-stale-price-1 | scored | PASS |  |
| i66-stale-price-2 | scored | FAIL | grounding |
| current-tool-error-1 | scored | PASS |  |
| current-tool-error-2 | scored | PASS |  |
| current-tool-error-3 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| annual-fixed-1 | scored | FAIL | outcome |
| annual-fixed-2 | scored | PASS |  |
| annual-tysons-clarification-1 | scored | PASS |  |
| annual-fixed-3 | scored | PASS |  |
| annual-tysons-clarification-2 | scored | FAIL | outcome |
| annual-tysons-clarification-3 | scored | PASS |  |
| annual-missing-schedule-2 | scored | PASS |  |
| annual-missing-schedule-3 | scored | PASS |  |
| annual-missing-schedule-1 | scored | FAIL | outcome |
| annual-salary-range-1 | scored | PASS |  |
| annual-salary-range-2 | scored | PASS |  |
| annual-salary-range-3 | scored | PASS |  |
| annual-hourly-income-1 | scored | FAIL | grounding |
| annual-hourly-income-2 | scored | PASS |  |
| annual-hourly-income-3 | scored | PASS |  |
| annual-confirm-days-1 | scored | PASS |  |
| annual-confirm-days-2 | scored | PASS |  |
| annual-confirm-days-3 | scored | PASS |  |
| annual-invalid-schedule-1 | scored | PASS |  |
| annual-no-return-route-1 | scored | PASS |  |
| annual-invalid-schedule-2 | scored | PASS |  |
| annual-invalid-schedule-3 | scored | FAIL | outcome |
| annual-no-return-route-2 | scored | PASS |  |
| annual-no-return-route-3 | scored | PASS |  |
| annual-partial-history-1 | scored | FAIL | outcome |
| annual-partial-history-2 | scored | PASS |  |
| annual-partial-history-3 | scored | PASS |  |
| annual-independent-ramps-1 | scored | PASS |  |
| annual-independent-ramps-2 | scored | PASS |  |
| annual-independent-ramps-3 | scored | PASS |  |
| annual-select-alternative-2 | scored | PASS |  |
| annual-select-alternative-1 | scored | PASS |  |
| annual-select-alternative-3 | scored | PASS |  |
| annual-confirm-divergent-1 | scored | PASS |  |
| annual-confirm-divergent-2 | scored | PASS |  |
| annual-confirm-divergent-3 | scored | PASS |  |
| annual-no-paired-days-1 | scored | FAIL | outcome |
| annual-no-paired-days-2 | scored | FAIL | grounding |
| annual-no-paired-days-3 | scored | PASS |  |

```json
{
  "complete": true,
  "expected_trials": 72,
  "attempted_trials": 72,
  "scored_trials": 72,
  "successful_trials": 63,
  "outcome_successful_trials": 66,
  "pass_at_1": 0.875,
  "pass_cubed": 0.6666666666666666,
  "passing_all_three_cases": 16,
  "case_count": 24,
  "success_ci95": [
    0.7916666666666666,
    0.9444444444444445
  ],
  "uncertainty_method": "case-cluster percentile bootstrap; 10000 samples; seed 360; descriptive finite-corpus uncertainty, not independent repeats",
  "cost_usd": {
    "agent": 0.18383561,
    "actor": 0.026104000000000002,
    "judge": 0.1926776
  },
  "agent_cost_per_attempt_usd": 0.002553272361111111,
  "agent_cost_per_success_usd": 0.002918025555555556,
  "latency_seconds": {
    "n": 72,
    "p50": 18.19115828399663,
    "p95": 27.62594242900377
  },
  "violations": {
    "grounding": {
      "count": 3,
      "denominator": 72,
      "rate": 0.041666666666666664
    },
    "rules": {
      "count": 0,
      "denominator": 72,
      "rate": 0.0
    }
  },
  "usage": {
    "agent": {
      "calls": 178,
      "input_tokens": 5769039,
      "output_tokens": 39930
    },
    "actor": {
      "calls": 106,
      "input_tokens": 101930,
      "output_tokens": 4765
    },
    "judge": {
      "calls": 216,
      "input_tokens": 580390,
      "output_tokens": 63833
    }
  },
  "turns": 106,
  "tool_calls": 72,
  "critical_checks_failed_trials": 1
}
```

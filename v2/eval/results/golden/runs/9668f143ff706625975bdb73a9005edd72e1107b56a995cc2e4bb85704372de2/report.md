# Golden conversation report

Commit: `96fb384d62ce5494d7f58615cf9638c2015099e0`

Complete: **True**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| greenway-current-2 | scored | PASS |  |
| greenway-current-1 | scored | PASS |  |
| greenway-current-3 | scored | PASS |  |
| greenway-origin-correction-1 | scored | PASS |  |
| unsupported-profile-1 | scored | PASS |  |
| unsupported-profile-2 | scored | PASS |  |
| greenway-origin-correction-2 | scored | PASS |  |
| greenway-origin-correction-3 | scored | PASS |  |
| unsupported-profile-3 | scored | PASS |  |
| greenway-missing-destination-1 | scored | PASS |  |
| greenway-missing-destination-2 | scored | PASS |  |
| i66-no-comparison-1 | scored | PASS |  |
| greenway-missing-destination-3 | scored | PASS |  |
| i66-missing-price-2 | scored | PASS |  |
| i66-missing-price-1 | scored | PASS |  |
| i66-no-comparison-3 | scored | PASS |  |
| i66-no-comparison-2 | scored | PASS |  |
| i66-missing-price-3 | scored | PASS |  |
| i66-observed-price-1 | scored | PASS |  |
| i66-observed-price-2 | scored | PASS |  |
| i66-free-period-1 | scored | PASS |  |
| i66-observed-price-3 | scored | PASS |  |
| i66-free-period-3 | scored | PASS |  |
| i66-free-period-2 | scored | PASS |  |
| i66-stale-price-1 | scored | PASS |  |
| i66-stale-price-2 | scored | PASS |  |
| i66-stale-price-3 | scored | FAIL | tool_use |
| current-tool-error-1 | scored | FAIL | recovery |
| current-tool-error-2 | scored | PASS |  |
| current-tool-error-3 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| annual-fixed-1 | scored | PASS |  |
| annual-fixed-2 | scored | PASS |  |
| annual-fixed-3 | scored | PASS |  |
| annual-tysons-clarification-2 | scored | PASS |  |
| annual-tysons-clarification-1 | scored | PASS |  |
| annual-tysons-clarification-3 | scored | PASS |  |
| annual-missing-schedule-1 | scored | PASS |  |
| annual-missing-schedule-2 | scored | PASS |  |
| annual-missing-schedule-3 | scored | PASS |  |
| annual-salary-range-1 | scored | PASS |  |
| annual-salary-range-2 | scored | PASS |  |
| annual-salary-range-3 | scored | PASS |  |
| annual-hourly-income-1 | scored | PASS |  |
| annual-hourly-income-2 | scored | PASS |  |
| annual-hourly-income-3 | scored | PASS |  |
| annual-confirm-days-1 | scored | PASS |  |
| annual-confirm-days-2 | scored | PASS |  |
| annual-confirm-days-3 | scored | PASS |  |
| annual-invalid-schedule-1 | scored | PASS |  |
| annual-no-return-route-1 | scored | PASS |  |
| annual-no-return-route-2 | scored | PASS |  |
| annual-invalid-schedule-2 | scored | PASS |  |
| annual-invalid-schedule-3 | scored | PASS |  |
| annual-no-return-route-3 | scored | PASS |  |
| annual-partial-history-1 | scored | PASS |  |
| annual-partial-history-3 | scored | PASS |  |
| annual-independent-ramps-1 | scored | PASS |  |
| annual-partial-history-2 | scored | PASS |  |
| annual-independent-ramps-2 | scored | PASS |  |
| annual-independent-ramps-3 | scored | PASS |  |
| annual-select-alternative-1 | scored | PASS |  |
| annual-select-alternative-2 | scored | PASS |  |
| annual-select-alternative-3 | scored | PASS |  |
| annual-confirm-divergent-1 | scored | PASS |  |
| annual-confirm-divergent-2 | scored | PASS |  |
| annual-no-paired-days-1 | scored | PASS |  |
| annual-confirm-divergent-3 | scored | PASS |  |
| annual-no-paired-days-2 | scored | PASS |  |
| annual-no-paired-days-3 | scored | PASS |  |

```json
{
  "complete": true,
  "expected_trials": 72,
  "attempted_trials": 72,
  "scored_trials": 72,
  "successful_trials": 70,
  "outcome_successful_trials": 71,
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
    "agent": 0.18662045,
    "actor": 0.026672,
    "judge": 0.184179
  },
  "agent_cost_per_attempt_usd": 0.002591950694444444,
  "agent_cost_per_success_usd": 0.0026660064285714286,
  "latency_seconds": {
    "n": 72,
    "p50": 17.562263295003504,
    "p95": 27.14416928099672
  },
  "violations": {
    "grounding": {
      "count": 0,
      "denominator": 72,
      "rate": 0.0
    },
    "rules": {
      "count": 1,
      "denominator": 72,
      "rate": 0.013888888888888888
    }
  },
  "usage": {
    "agent": {
      "calls": 180,
      "input_tokens": 5861040,
      "output_tokens": 40699
    },
    "actor": {
      "calls": 108,
      "input_tokens": 103528,
      "output_tokens": 4972
    },
    "judge": {
      "calls": 216,
      "input_tokens": 581841,
      "output_tokens": 56509
    }
  },
  "turns": 108,
  "tool_calls": 72,
  "critical_checks_failed_trials": 0
}
```

# Golden conversation report

Commit: `e0ce0719196f1d604e0d0da1f7d8c3662c6912be`

Complete: **True**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| greenway-current-2 | scored | PASS |  |
| greenway-current-1 | scored | FAIL | grounding |
| greenway-current-3 | scored | PASS |  |
| greenway-origin-correction-1 | scored | PASS |  |
| unsupported-profile-1 | scored | PASS |  |
| unsupported-profile-2 | scored | PASS |  |
| greenway-origin-correction-3 | scored | FAIL | grounding |
| greenway-origin-correction-2 | scored | PASS |  |
| unsupported-profile-3 | scored | PASS |  |
| greenway-missing-destination-1 | scored | PASS |  |
| greenway-missing-destination-2 | scored | PASS |  |
| i66-no-comparison-1 | scored | PASS |  |
| i66-no-comparison-2 | scored | PASS |  |
| i66-no-comparison-3 | scored | PASS |  |
| greenway-missing-destination-3 | scored | PASS |  |
| i66-missing-price-1 | scored | PASS |  |
| i66-missing-price-2 | scored | PASS |  |
| i66-missing-price-3 | scored | PASS |  |
| i66-observed-price-1 | scored | PASS |  |
| i66-free-period-1 | scored | FAIL | grounding |
| i66-observed-price-3 | scored | PASS |  |
| i66-observed-price-2 | scored | PASS |  |
| i66-free-period-2 | scored | FAIL | grounding |
| i66-free-period-3 | scored | FAIL | grounding |
| i66-stale-price-1 | scored | PASS |  |
| i66-stale-price-2 | scored | PASS |  |
| i66-stale-price-3 | scored | PASS |  |
| current-tool-error-2 | scored | PASS |  |
| current-tool-error-3 | scored | PASS |  |
| current-tool-error-1 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| annual-fixed-1 | scored | FAIL | outcome |
| annual-fixed-2 | scored | PASS |  |
| annual-fixed-3 | scored | PASS |  |
| annual-tysons-clarification-1 | scored | PASS |  |
| annual-tysons-clarification-2 | scored | PASS |  |
| annual-missing-schedule-1 | scored | PASS |  |
| annual-missing-schedule-2 | scored | PASS |  |
| annual-tysons-clarification-3 | scored | PASS |  |
| annual-missing-schedule-3 | scored | FAIL | outcome |
| annual-salary-range-1 | scored | FAIL | grounding |
| annual-salary-range-3 | scored | FAIL | grounding |
| annual-hourly-income-1 | scored | PASS |  |
| annual-hourly-income-2 | scored | PASS |  |
| annual-salary-range-2 | scored | FAIL | grounding |
| annual-hourly-income-3 | scored | PASS |  |
| annual-confirm-days-1 | scored | PASS |  |
| annual-confirm-days-3 | scored | PASS |  |
| annual-confirm-days-2 | scored | PASS |  |
| annual-invalid-schedule-1 | scored | PASS |  |
| annual-no-return-route-1 | scored | FAIL | tool_use |
| annual-invalid-schedule-2 | scored | PASS |  |
| annual-invalid-schedule-3 | scored | PASS |  |
| annual-no-return-route-2 | scored | PASS |  |
| annual-no-return-route-3 | scored | PASS |  |
| annual-partial-history-2 | scored | PASS |  |
| annual-partial-history-1 | scored | FAIL | outcome |
| annual-independent-ramps-1 | scored | PASS |  |
| annual-partial-history-3 | scored | PASS |  |
| annual-independent-ramps-3 | scored | PASS |  |
| annual-independent-ramps-2 | scored | PASS |  |
| annual-select-alternative-3 | scored | FAIL | tool_use |
| annual-select-alternative-1 | scored | PASS |  |
| annual-select-alternative-2 | scored | PASS |  |
| annual-confirm-divergent-1 | scored | PASS |  |
| annual-no-paired-days-1 | scored | PASS |  |
| annual-confirm-divergent-3 | scored | PASS |  |
| annual-confirm-divergent-2 | scored | PASS |  |
| annual-no-paired-days-2 | scored | PASS |  |
| annual-no-paired-days-3 | scored | FAIL | outcome |

```json
{
  "complete": true,
  "expected_trials": 72,
  "attempted_trials": 72,
  "scored_trials": 72,
  "successful_trials": 58,
  "outcome_successful_trials": 62,
  "pass_at_1": 0.8055555555555556,
  "pass_cubed": 0.5833333333333334,
  "passing_all_three_cases": 14,
  "case_count": 24,
  "success_ci95": [
    0.6805555555555555,
    0.9027777777777778
  ],
  "uncertainty_method": "case-cluster percentile bootstrap; 10000 samples; seed 360; descriptive finite-corpus uncertainty, not independent repeats",
  "cost_usd": {
    "agent": 0.17825439999999998,
    "actor": 0.025401200000000002,
    "judge": 0.18766460000000001
  },
  "agent_cost_per_attempt_usd": 0.002475755555555555,
  "agent_cost_per_success_usd": 0.003073351724137931,
  "latency_seconds": {
    "n": 72,
    "p50": 16.681163925000874,
    "p95": 28.985796713997843
  },
  "violations": {
    "grounding": {
      "count": 8,
      "denominator": 72,
      "rate": 0.1111111111111111
    },
    "rules": {
      "count": 7,
      "denominator": 72,
      "rate": 0.09722222222222222
    }
  },
  "usage": {
    "agent": {
      "calls": 176,
      "input_tokens": 5677948,
      "output_tokens": 37323
    },
    "actor": {
      "calls": 105,
      "input_tokens": 98338,
      "output_tokens": 4778
    },
    "judge": {
      "calls": 216,
      "input_tokens": 567973,
      "output_tokens": 61725
    }
  },
  "turns": 106,
  "tool_calls": 71,
  "critical_checks_failed_trials": 1
}
```

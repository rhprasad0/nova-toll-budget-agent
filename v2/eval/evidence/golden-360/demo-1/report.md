# Golden conversation report

Commit: `e9abf4eaef1b6f4bc615815c7b9b302ba8710821`

Complete: **True**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| greenway-current-1 | scored | FAIL | tool_use |
| greenway-current-2 | scored | FAIL | grounding |
| greenway-current-3 | scored | FAIL | tool_use |
| greenway-origin-correction-1 | scored | FAIL | grounding |
| greenway-origin-correction-2 | scored | PASS |  |
| greenway-origin-correction-3 | scored | PASS |  |
| unsupported-profile-1 | scored | FAIL | outcome |
| unsupported-profile-2 | scored | PASS |  |
| unsupported-profile-3 | scored | PASS |  |
| greenway-missing-destination-1 | scored | FAIL | grounding |
| greenway-missing-destination-2 | scored | FAIL | tool_use |
| greenway-missing-destination-3 | scored | PASS |  |
| i66-no-comparison-1 | scored | FAIL | outcome |
| i66-no-comparison-2 | scored | FAIL | outcome |
| i66-no-comparison-3 | scored | FAIL | tool_use |
| i66-missing-price-1 | scored | FAIL | grounding |
| i66-missing-price-2 | scored | FAIL | outcome |
| i66-missing-price-3 | scored | FAIL | grounding |
| i66-observed-price-1 | scored | FAIL | outcome |
| i66-observed-price-2 | scored | FAIL | outcome |
| i66-observed-price-3 | scored | PASS |  |
| i66-free-period-1 | scored | FAIL | grounding |
| i66-free-period-2 | scored | PASS |  |
| i66-free-period-3 | scored | FAIL | outcome |
| i66-stale-price-1 | scored | FAIL | outcome |
| i66-stale-price-2 | scored | FAIL | grounding |
| i66-stale-price-3 | scored | PASS |  |
| current-tool-error-1 | scored | PASS |  |
| current-tool-error-2 | scored | PASS |  |
| current-tool-error-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| annual-fixed-1 | scored | PASS |  |
| annual-fixed-2 | scored | PASS |  |
| annual-fixed-3 | scored | FAIL | budget |
| annual-tysons-clarification-1 | scored | PASS |  |
| annual-tysons-clarification-2 | scored | PASS |  |
| annual-tysons-clarification-3 | scored | PASS |  |
| annual-missing-schedule-1 | scored | PASS |  |
| annual-missing-schedule-2 | scored | FAIL | outcome |
| annual-missing-schedule-3 | scored | FAIL | tool_use |
| annual-salary-range-1 | scored | FAIL | tool_use |
| annual-salary-range-2 | scored | FAIL | tool_use |
| annual-salary-range-3 | scored | PASS |  |
| annual-hourly-income-1 | scored | FAIL | outcome |
| annual-hourly-income-2 | scored | PASS |  |
| annual-hourly-income-3 | scored | FAIL | tool_use |
| annual-confirm-days-1 | scored | FAIL | outcome |
| annual-confirm-days-2 | scored | PASS |  |
| annual-confirm-days-3 | scored | FAIL | outcome |
| annual-invalid-schedule-1 | scored | FAIL | grounding |
| annual-invalid-schedule-2 | scored | FAIL | grounding |
| annual-invalid-schedule-3 | scored | PASS |  |
| annual-no-return-route-1 | scored | FAIL | grounding |
| annual-no-return-route-2 | scored | PASS |  |
| annual-no-return-route-3 | scored | FAIL | tool_use |
| annual-partial-history-1 | scored | FAIL | grounding |
| annual-partial-history-2 | scored | FAIL | grounding |
| annual-partial-history-3 | scored | PASS |  |
| annual-independent-ramps-1 | scored | FAIL | tool_use |
| annual-independent-ramps-2 | scored | FAIL | tool_use |
| annual-independent-ramps-3 | scored | FAIL | tool_use |
| annual-select-alternative-1 | scored | PASS |  |
| annual-select-alternative-2 | scored | FAIL | grounding |
| annual-select-alternative-3 | scored | FAIL | tool_use |
| annual-confirm-divergent-1 | scored | FAIL | tool_use |
| annual-confirm-divergent-2 | scored | FAIL | grounding |
| annual-confirm-divergent-3 | scored | FAIL | tool_use |
| annual-no-paired-days-1 | scored | FAIL | grounding |
| annual-no-paired-days-2 | scored | FAIL | grounding |
| annual-no-paired-days-3 | scored | FAIL | outcome |

```json
{
  "complete": true,
  "expected_trials": 72,
  "attempted_trials": 72,
  "scored_trials": 72,
  "successful_trials": 27,
  "outcome_successful_trials": 37,
  "pass_at_1": 0.375,
  "pass_cubed": 0.125,
  "passing_all_three_cases": 3,
  "case_count": 24,
  "success_ci95": [
    0.25,
    0.5
  ],
  "uncertainty_method": "case-cluster percentile bootstrap; 10000 samples; seed 360; descriptive finite-corpus uncertainty, not independent repeats",
  "cost_usd": {
    "agent": 0.1848981,
    "actor": 0.04360802,
    "judge": 0.16038018
  },
  "agent_cost_per_attempt_usd": 0.002568029166666667,
  "agent_cost_per_success_usd": 0.006848077777777778,
  "latency_seconds": {
    "n": 72,
    "p50": 23.513364405000175,
    "p95": 41.51195374099916
  },
  "violations": {
    "grounding": {
      "count": 16,
      "denominator": 72,
      "rate": 0.2222222222222222
    },
    "rules": {
      "count": 24,
      "denominator": 72,
      "rate": 0.3333333333333333
    }
  },
  "usage": {
    "agent": {
      "calls": 185,
      "input_tokens": 6002123,
      "output_tokens": 35319
    },
    "actor": {
      "calls": 143,
      "input_tokens": 452947,
      "output_tokens": 14534
    },
    "judge": {
      "calls": 218,
      "input_tokens": 417654,
      "output_tokens": 65706
    }
  },
  "turns": 125,
  "tool_calls": 67,
  "critical_checks_failed_trials": 10
}
```

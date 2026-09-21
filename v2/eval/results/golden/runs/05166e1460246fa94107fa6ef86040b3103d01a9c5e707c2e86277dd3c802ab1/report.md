# Golden conversation report

Commit: `f4093e376906a7c921e3c35187da59b6a6f752bc`

Complete: **True**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| greenway-current-3 | scored | PASS |  |
| greenway-current-2 | scored | PASS |  |
| greenway-current-1 | scored | PASS |  |
| greenway-origin-correction-1 | scored | PASS |  |
| unsupported-profile-1 | scored | PASS |  |
| greenway-origin-correction-3 | scored | PASS |  |
| greenway-origin-correction-2 | scored | PASS |  |
| unsupported-profile-2 | scored | PASS |  |
| unsupported-profile-3 | scored | PASS |  |
| greenway-missing-destination-2 | scored | PASS |  |
| greenway-missing-destination-1 | scored | PASS |  |
| greenway-missing-destination-3 | scored | PASS |  |
| i66-no-comparison-1 | scored | PASS |  |
| i66-no-comparison-2 | scored | PASS |  |
| i66-no-comparison-3 | scored | PASS |  |
| i66-missing-price-1 | scored | PASS |  |
| i66-missing-price-3 | scored | PASS |  |
| i66-observed-price-1 | scored | PASS |  |
| i66-missing-price-2 | scored | PASS |  |
| i66-observed-price-2 | scored | PASS |  |
| i66-observed-price-3 | scored | PASS |  |
| i66-free-period-1 | scored | PASS |  |
| i66-free-period-2 | scored | PASS |  |
| i66-stale-price-1 | scored | PASS |  |
| i66-free-period-3 | scored | PASS |  |
| i66-stale-price-2 | scored | PASS |  |
| i66-stale-price-3 | scored | PASS |  |
| current-tool-error-2 | scored | PASS |  |
| current-tool-error-1 | scored | PASS |  |
| current-tool-error-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| annual-fixed-1 | scored | PASS |  |
| annual-fixed-3 | scored | PASS |  |
| annual-fixed-2 | scored | PASS |  |
| annual-tysons-clarification-1 | scored | PASS |  |
| annual-tysons-clarification-2 | scored | PASS |  |
| annual-missing-schedule-1 | scored | PASS |  |
| annual-tysons-clarification-3 | scored | PASS |  |
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
| annual-invalid-schedule-2 | scored | PASS |  |
| annual-invalid-schedule-1 | scored | PASS |  |
| annual-no-return-route-1 | scored | PASS |  |
| annual-invalid-schedule-3 | scored | PASS |  |
| annual-no-return-route-2 | scored | PASS |  |
| annual-no-return-route-3 | scored | PASS |  |
| annual-partial-history-1 | scored | PASS |  |
| annual-partial-history-3 | scored | PASS |  |
| annual-independent-ramps-1 | scored | PASS |  |
| annual-partial-history-2 | scored | PASS |  |
| annual-independent-ramps-2 | scored | PASS |  |
| annual-independent-ramps-3 | scored | PASS |  |
| annual-select-alternative-1 | scored | PASS |  |
| annual-select-alternative-3 | scored | PASS |  |
| annual-select-alternative-2 | scored | PASS |  |
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
  "successful_trials": 72,
  "outcome_successful_trials": 72,
  "pass_at_1": 1.0,
  "pass_cubed": 1.0,
  "passing_all_three_cases": 24,
  "case_count": 24,
  "success_ci95": [
    1.0,
    1.0
  ],
  "uncertainty_method": "case-cluster percentile bootstrap; 10000 samples; seed 360; descriptive finite-corpus uncertainty, not independent repeats",
  "cost_usd": {
    "agent": 0.1829869,
    "actor": 0.0261562,
    "judge": 0.19727
  },
  "agent_cost_per_attempt_usd": 0.0025414847222222222,
  "agent_cost_per_success_usd": 0.0025414847222222222,
  "latency_seconds": {
    "n": 72,
    "p50": 17.16347774300084,
    "p95": 27.487023966998095
  },
  "violations": {
    "grounding": {
      "count": 0,
      "denominator": 72,
      "rate": 0.0
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
      "input_tokens": 5833415,
      "output_tokens": 39544
    },
    "actor": {
      "calls": 106,
      "input_tokens": 100943,
      "output_tokens": 4973
    },
    "judge": {
      "calls": 216,
      "input_tokens": 656800,
      "output_tokens": 54925
    }
  },
  "turns": 106,
  "tool_calls": 72,
  "critical_checks_failed_trials": 0
}
```

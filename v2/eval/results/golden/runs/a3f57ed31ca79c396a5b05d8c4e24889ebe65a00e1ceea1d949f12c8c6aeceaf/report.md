# Golden conversation report

Commit: `4dd8fc361ab27315a362d59e014d77625921110f`

Complete: **False**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| greenway-current-1 | scored | PASS |  |
| greenway-origin-correction-1 | scored | PASS |  |
| greenway-current-2 | scored | FAIL | tool_use |
| greenway-current-3 | scored | PASS |  |
| unsupported-profile-1 | scored | PASS |  |
| greenway-origin-correction-2 | scored | PASS |  |
| greenway-origin-correction-3 | scored | FAIL | grounding |
| unsupported-profile-2 | scored | PASS |  |
| unsupported-profile-3 | scored | PASS |  |
| greenway-missing-destination-2 | scored | PASS |  |
| greenway-missing-destination-3 | scored | PASS |  |
| greenway-missing-destination-1 | scored | PASS |  |
| i66-no-comparison-1 | scored | PASS |  |
| i66-missing-price-1 | scored | PASS |  |
| i66-no-comparison-2 | scored | PASS |  |
| i66-no-comparison-3 | scored | PASS |  |
| i66-missing-price-2 | scored | PASS |  |
| i66-missing-price-3 | scored | PASS |  |
| i66-observed-price-3 | scored | PASS |  |
| i66-free-period-1 | scored | PASS |  |
| i66-observed-price-1 | scored | PASS |  |
| i66-observed-price-2 | scored | PASS |  |
| i66-free-period-2 | scored | PASS |  |
| i66-stale-price-1 | scored | PASS |  |
| i66-free-period-3 | scored | PASS |  |
| i66-stale-price-3 | scored | PASS |  |
| i66-stale-price-2 | scored | PASS |  |
| current-tool-error-2 | scored | PASS |  |
| current-tool-error-1 | scored | PASS |  |
| current-tool-error-3 | scored | PASS |  |
| unsupported-origin-1 | scored | PASS |  |
| unsupported-origin-3 | scored | PASS |  |
| unsupported-origin-2 | scored | PASS |  |
| annual-fixed-1 | scored | PASS |  |
| annual-fixed-2 | scored | PASS |  |
| annual-fixed-3 | scored | PASS |  |
| annual-tysons-clarification-1 | scored | PASS |  |
| annual-tysons-clarification-3 | scored | PASS |  |
| annual-tysons-clarification-2 | scored | PASS |  |
| annual-missing-schedule-2 | scored | PASS |  |
| annual-missing-schedule-3 | scored | PASS |  |
| annual-missing-schedule-1 | scored | PASS |  |
| annual-salary-range-1 | scored | PASS |  |
| annual-salary-range-2 | scored | FAIL | grounding |
| annual-hourly-income-1 | scored | FAIL | outcome |
| annual-salary-range-3 | scored | FAIL | grounding |
| annual-hourly-income-2 | scored | PASS |  |
| annual-hourly-income-3 | scored | FAIL | outcome |
| annual-confirm-days-2 | scored | FAIL | outcome |
| annual-confirm-days-1 | scored | PASS |  |
| annual-confirm-days-3 | scored | PASS |  |
| annual-invalid-schedule-1 | scored | FAIL | grounding |
| annual-invalid-schedule-3 | scored | PASS |  |
| annual-no-return-route-1 | scored | PASS |  |
| annual-invalid-schedule-2 | scored | FAIL | grounding |
| annual-no-return-route-2 | scored | PASS |  |
| annual-no-return-route-3 | scored | PASS |  |
| annual-partial-history-2 | scored | PASS |  |
| annual-partial-history-1 | scored | PASS |  |
| annual-partial-history-3 | scored | PASS |  |
| annual-independent-ramps-1 | scored | PASS |  |
| annual-independent-ramps-3 | scored | PASS |  |
| annual-independent-ramps-2 | infrastructure | INCONCLUSIVE | actor_validity |
| annual-select-alternative-1 | scored | PASS |  |
| annual-select-alternative-2 | scored | PASS |  |
| annual-confirm-divergent-1 | scored | FAIL | tool_use |
| annual-confirm-divergent-2 | scored | FAIL | tool_use |
| annual-confirm-divergent-3 | scored | FAIL | tool_use |
| annual-no-paired-days-3 | scored | PASS |  |
| annual-no-paired-days-2 | scored | PASS |  |
| annual-no-paired-days-1 | scored | FAIL | grounding |
| annual-select-alternative-3 | scored | PASS |  |

```json
{
  "complete": false,
  "expected_trials": 72,
  "attempted_trials": 72,
  "scored_trials": 71,
  "successful_trials": 58,
  "outcome_successful_trials": 64,
  "pass_at_1": 0.8169014084507042,
  "pass_cubed": 0.625,
  "passing_all_three_cases": 15,
  "case_count": 24,
  "success_ci95": null,
  "uncertainty_method": "case-cluster percentile bootstrap; 10000 samples; seed 360; descriptive finite-corpus uncertainty, not independent repeats",
  "cost_usd": {
    "agent": 0.18367956,
    "actor": 0.02617278,
    "judge": 0.1825806
  },
  "agent_cost_per_attempt_usd": 0.0025511049999999997,
  "agent_cost_per_success_usd": 0.0031668889655172413,
  "latency_seconds": {
    "n": 72,
    "p50": 20.956626440001855,
    "p95": 35.267384196999046
  },
  "violations": {
    "grounding": {
      "count": 6,
      "denominator": 71,
      "rate": 0.08450704225352113
    },
    "rules": {
      "count": 4,
      "denominator": 71,
      "rate": 0.056338028169014086
    }
  },
  "usage": {
    "agent": {
      "calls": 183,
      "input_tokens": 5907107,
      "output_tokens": 37108
    },
    "actor": {
      "calls": 111,
      "input_tokens": 96438,
      "output_tokens": 6129
    },
    "judge": {
      "calls": 213,
      "input_tokens": 535353,
      "output_tokens": 62925
    }
  },
  "turns": 114,
  "tool_calls": 72,
  "critical_checks_failed_trials": 4
}
```

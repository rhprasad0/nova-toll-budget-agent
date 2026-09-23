# Golden conversation report

Commit: `451a789a1ca17166879e23da5af2a46fcb95a20d`

Complete: **False**. Human actor review pending. No release decision.

| Case / trial | Status | Overall | Failure |
| --- | --- | --- | --- |
| annual-one-day-year-average-1 | scored | FAIL | outcome |
| annual-one-day-year-average-3 | scored | PASS |  |
| annual-vehicle-rate-not-tax-rule-1 | scored | FAIL | outcome |
| annual-one-day-year-average-2 | scored | FAIL | outcome |
| annual-vehicle-rate-not-tax-rule-2 | scored | PASS |  |
| annual-vehicle-rate-not-tax-rule-3 | scored | FAIL | outcome |
| annual-personal-vehicle-rate-2 | scored | FAIL | tool_use |
| annual-personal-vehicle-rate-1 | scored | FAIL | outcome |
| annual-personal-tax-rate-1 | scored | FAIL | tool_use |
| annual-personal-vehicle-rate-3 | scored | PASS |  |
| annual-personal-tax-rate-2 | scored | PASS |  |
| annual-personal-tax-rate-3 | inconclusive | INCONCLUSIVE | actor_validity |
| annual-parking-and-untolled-scope-3 | scored | FAIL | outcome |
| annual-parking-and-untolled-scope-1 | scored | FAIL | outcome |
| annual-parking-and-untolled-scope-2 | scored | PASS |  |
| annual-straight-line-not-road-mileage-1 | scored | PASS |  |
| annual-straight-line-not-road-mileage-3 | scored | PASS |  |
| annual-straight-line-not-road-mileage-2 | scored | PASS |  |
| annual-offer-decision-scope-1 | scored | PASS |  |
| annual-offer-decision-scope-2 | scored | PASS |  |
| annual-recruiter-followup-scope-1 | scored | PASS |  |
| annual-offer-decision-scope-3 | scored | PASS |  |
| annual-recruiter-followup-scope-2 | scored | FAIL | outcome |
| annual-recruiter-followup-scope-3 | scored | PASS |  |
| annual-lower-only-framing-2 | scored | PASS |  |
| annual-lower-only-framing-1 | scored | PASS |  |
| annual-lower-only-framing-3 | scored | PASS |  |
| annual-remaining-vs-gross-salary-1 | scored | FAIL | outcome |
| annual-remaining-vs-gross-salary-2 | scored | PASS |  |
| annual-remaining-vs-gross-salary-3 | scored | FAIL | outcome |
| annual-facility-quantiles-not-additive-1 | scored | PASS |  |
| annual-facility-quantiles-not-additive-2 | scored | FAIL | outcome |
| annual-irrelevant-story-control-1 | scored | PASS |  |
| annual-facility-quantiles-not-additive-3 | scored | PASS |  |
| annual-irrelevant-story-control-2 | scored | FAIL | outcome |
| annual-irrelevant-story-price-1 | scored | PASS |  |
| annual-irrelevant-story-control-3 | scored | PASS |  |
| annual-irrelevant-story-price-2 | scored | PASS |  |
| annual-irrelevant-story-price-3 | scored | PASS |  |
| annual-reimbursement-not-netted-2 | scored | FAIL | outcome |
| annual-reimbursement-not-netted-1 | scored | FAIL | outcome |
| annual-reimbursement-not-netted-3 | scored | FAIL | tool_use |

```json
{
  "complete": false,
  "expected_trials": 42,
  "attempted_trials": 42,
  "scored_trials": 41,
  "successful_trials": 24,
  "outcome_successful_trials": 24,
  "pass_at_1": 0.5853658536585366,
  "pass_cubed": 0.3076923076923077,
  "passing_all_three_cases": 4,
  "case_count": 14,
  "success_ci95": null,
  "uncertainty_method": "split-group cluster percentile bootstrap; 10000 samples; seed 360; paired scenarios kept together; descriptive finite-corpus uncertainty",
  "cost_usd": {
    "agent": 0.05619455,
    "actor": 0.0078998,
    "judge": 0.08961766
  },
  "agent_cost_per_attempt_usd": 0.0013379654761904764,
  "agent_cost_per_success_usd": 0.0023414395833333333,
  "latency_seconds": {
    "n": 42,
    "p50": 24.988401626003906,
    "p95": 37.28262167300272
  },
  "violations": {
    "grounding": {
      "count": 0,
      "denominator": 41,
      "rate": 0.0
    },
    "rules": {
      "count": 3,
      "denominator": 41,
      "rate": 0.07317073170731707
    }
  },
  "usage": {
    "agent": {
      "calls": 91,
      "input_tokens": 3050955,
      "output_tokens": 31692
    },
    "actor": {
      "calls": 50,
      "input_tokens": 64818,
      "output_tokens": 2836
    },
    "judge": {
      "calls": 126,
      "input_tokens": 2875355,
      "output_tokens": 47600
    }
  },
  "turns": 50,
  "tool_calls": 41,
  "critical_checks_failed_trials": 1,
  "inconclusive_trials": 1,
  "failure_counts": {
    "actor_validity": 1,
    "outcome": 14,
    "tool_use": 3
  },
  "actor_validity_counts": {
    "valid": 41,
    "invalid": 1,
    "uncertain": 0
  },
  "scenario_group_count": 13,
  "pass_cubed_case_denominator": 13,
  "families": {
    "annual_finance": {
      "cases": 14,
      "expected_trials": 42,
      "scored_trials": 41,
      "successful_trials": 24,
      "inconclusive_trials": 1
    }
  },
  "observed_violations": {
    "grounding": 0,
    "rules": 4
  }
}
```

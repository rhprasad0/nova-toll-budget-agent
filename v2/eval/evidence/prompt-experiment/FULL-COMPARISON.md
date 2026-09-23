# Full A/B/C comparison — 2.0.8

Frozen prompts and evaluator; three trials per case. Inconclusive trials are retained and excluded from scored rates, not retried. Calibration judgments have known limitations; these are measured outcomes, not independently verified truth.

| Arm | Scored / attempted / expected | Passed | Pass rate | Cases passing all 3 | Grounding violations | Rules violations | Cost | Latency p50 / p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A | 582 / 600 / 600 | 402 | 69.1% | 95 / 200 | 21 | 63 | $1.760913 | 21.8s / 32.4s |
| B | 544 / 600 / 600 | 400 | 73.5% | 97 / 200 | 23 | 57 | $1.627106 | 20.1s / 34.2s |
| C | 0 / 600 / 600 | 0 | unavailable | 0 / 200 | 0 | 0 | $0.000000 | 0.0s / 0.0s |

**Incomplete comparison: infrastructure failures are present. Unmeasured trials are not application failures, and incomplete-arm rates cannot establish a winner. Latency and cost per success are affected by the interruption. See the per-arm failure counts and original journals.**

## Paired case comparisons

Difference is candidate minus A, in pass-rate percentage points. Only cases with all three valid scored trials in both arms are paired. Intervals resample scenario groups (10,000 samples; seed 360); they describe this finite corpus and do not remove judge noise or selection bias. Diagnostics were selected using historical results and are not an unbiased performance estimate.

| Subset | Comparison | Paired / excluded cases | Difference | 95% interval |
| --- | --- | --- | ---: | --- |
| all | B - A | 168 / 32 | +2.2 pp | -2.2 to +6.7 pp |
| all | C - A | 0 / 200 | unavailable | unavailable |
| development | B - A | 131 / 29 | +3.6 pp | -1.4 to +9.0 pp |
| development | C - A | 0 / 160 | unavailable | unavailable |
| reserved | B - A | 37 / 3 | -2.7 pp | -12.4 to +6.5 pp |
| reserved | C - A | 0 / 40 | unavailable | unavailable |

## Family results

Values are successful / scored trials; missing or inconclusive trials do not count as successes.

| Family | A | B | C |
| --- | --- | --- | --- |
| annual_evidence | 57 / 84 | 57 / 84 | 0 / 0 |
| annual_finance | 45 / 83 | 28 / 42 | 0 / 0 |
| annual_inputs | 69 / 107 | 72 / 107 | 0 / 0 |
| annual_routes | 60 / 82 | 69 / 82 | 0 / 0 |
| current_evidence | 63 / 71 | 57 / 72 | 0 / 0 |
| current_i95 | 26 / 54 | 24 / 53 | 0 / 0 |
| current_state | 62 / 70 | 66 / 71 | 0 / 0 |
| current_unsupported | 11 / 19 | 18 / 21 | 0 / 0 |
| mixed | 9 / 12 | 9 / 12 | 0 / 0 |

## A evidence

[Full report](full-a-2.0.8/report.json); [trial checklist](full-a-2.0.8/report.md). Evidence SHA-256: `7b13f3f388a7b85d7092f248ea738a7e4a051d4f24a33bfada82ab5b2f7895b5`.

Actor validity: `{'valid': 582, 'invalid': 8, 'uncertain': 10}`. Failure classes: `{'actor_validity': 18, 'budget': 10, 'clarification': 2, 'grounding': 19, 'outcome': 103, 'tool_use': 46}`. Deterministic tool/argument/contract checks: `{'tool_budget': 12, 'incomplete_dialogue': 21, 'missing_call': 42, 'premature_call': 3, 'tool_arguments': 38, 'unsupported_money': 5, 'agent_turn_budget': 2}`.

Cost by role: `{'agent': 0.6717036, 'actor': 0.092808, 'judge': 0.99640136}`. Agent cost per success: `0.0016709044776119402`. Token usage: `{'agent': {'calls': 1399, 'input_tokens': 45794911, 'output_tokens': 280968}, 'actor': {'calls': 783, 'input_tokens': 790220, 'output_tokens': 27572}, 'judge': {'calls': 1791, 'input_tokens': 39561539, 'output_tokens': 567481}}`.

## B evidence

[Full report](full-b-2.0.8/report.json); [trial checklist](full-b-2.0.8/report.md). Evidence SHA-256: `d43ea683711d1831db0c58186d2525b141f8bf416046bb319af154c6633e47ef`.

Actor validity: `{'valid': 544, 'invalid': 6, 'uncertain': 8}`. Failure classes: `{'actor_validity': 14, 'budget': 5, 'clarification': 2, 'grounding': 22, 'harness': 41, 'judge': 1, 'outcome': 69, 'tool_use': 46}`. Deterministic tool/argument/contract checks: `{'incomplete_dialogue': 22, 'missing_call': 48, 'premature_call': 3, 'tool_arguments': 44, 'unsupported_money': 5, 'tool_budget': 5, 'agent_turn_budget': 2}`.

Cost by role: `{'agent': 0.63136192, 'actor': 0.0879303, 'judge': 0.9078141200000001}`. Agent cost per success: `0.0015784048`. Token usage: `{'agent': {'calls': 1311, 'input_tokens': 43567675, 'output_tokens': 255866}, 'actor': {'calls': 743, 'input_tokens': 736188, 'output_tokens': 28623}, 'judge': {'calls': 1671, 'input_tokens': 36809776, 'output_tokens': 519002}}`.

## C evidence

[Full report](full-c-2.0.8/report.json); [trial checklist](full-c-2.0.8/report.md). Evidence SHA-256: `063e6ed6881c1dcd355af018fc86d91aacc7c48ac5fbdb5b33d8268376aacc29`.

Actor validity: `{'valid': 0, 'invalid': 0, 'uncertain': 0}`. Failure classes: `{'harness': 600}`. Deterministic tool/argument/contract checks: `{}`.

Cost by role: `{'agent': 0, 'actor': 0, 'judge': 0}`. Agent cost per success: `None`. Token usage: `{'agent': {'calls': 0, 'input_tokens': 0, 'output_tokens': 0}, 'actor': {'calls': 0, 'input_tokens': 0, 'output_tokens': 0}, 'judge': {'calls': 0, 'input_tokens': 0, 'output_tokens': 0}}`.

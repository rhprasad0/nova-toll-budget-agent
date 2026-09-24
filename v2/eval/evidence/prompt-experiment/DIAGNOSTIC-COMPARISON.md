# Diagnostic A/B/C comparison — 2.0.8

Frozen prompts and evaluator; three trials per case. Inconclusive trials are retained and excluded from scored rates, not retried. Calibration judgments have known limitations; these are measured outcomes, not independently verified truth.

| Arm | Scored / attempted / expected | Passed | Pass rate | Cases passing all 3 | Grounding violations | Rules violations | Cost | Latency p50 / p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A | 75 / 78 / 78 | 55 | 73.3% | 14 / 26 | 6 | 9 | $0.248131 | 20.8s / 34.6s |
| B | 73 / 78 / 78 | 57 | 78.1% | 14 / 26 | 4 | 5 | $0.227324 | 21.7s / 35.0s |
| C | 75 / 78 / 78 | 58 | 77.3% | 13 / 26 | 4 | 7 | $0.232100 | 21.4s / 34.8s |

## Paired case comparisons

Difference is candidate minus A, in pass-rate percentage points. Only cases with all three valid scored trials in both arms are paired. Intervals resample scenario groups (10,000 samples; seed 360); they describe this finite corpus and do not remove judge noise or selection bias. Diagnostics were selected using historical results and are not an unbiased performance estimate.

| Subset | Comparison | Paired / excluded cases | Difference | 95% interval |
| --- | --- | --- | ---: | --- |
| all | B - A | 22 / 4 | +1.5 pp | -7.2 to +11.1 pp |
| all | C - A | 22 / 4 | +1.5 pp | -9.5 to +14.3 pp |
| development | B - A | 22 / 4 | +1.5 pp | -7.2 to +11.1 pp |
| development | C - A | 22 / 4 | +1.5 pp | -9.5 to +14.3 pp |

## Family results

Values are successful / scored trials; missing or inconclusive trials do not count as successes.

| Family | A | B | C |
| --- | --- | --- | --- |
| annual_evidence | 7 / 9 | 7 / 8 | 6 / 8 |
| annual_finance | 6 / 9 | 7 / 9 | 7 / 9 |
| annual_inputs | 6 / 9 | 6 / 9 | 6 / 9 |
| annual_routes | 9 / 9 | 8 / 9 | 8 / 9 |
| current_evidence | 4 / 9 | 4 / 9 | 5 / 9 |
| current_i95 | 3 / 7 | 3 / 6 | 5 / 8 |
| current_state | 9 / 9 | 9 / 9 | 9 / 9 |
| current_unsupported | 5 / 8 | 7 / 8 | 6 / 8 |
| mixed | 6 / 6 | 6 / 6 | 6 / 6 |

## A evidence

[Full report](diagnostic-a-2.0.8/report.json); [trial checklist](diagnostic-a-2.0.8/report.md). Evidence SHA-256: `dcf3e4eb12939208bed52387dfcacd6e7b647eb3f8eb8339103b962776161be0`.

Actor validity: `{'valid': 75, 'invalid': 1, 'uncertain': 2}`. Failure classes: `{'actor_validity': 3, 'budget': 3, 'grounding': 5, 'outcome': 6, 'tool_use': 6}`. Deterministic tool/argument/contract checks: `{'unsupported_money': 2, 'missing_call': 8, 'tool_arguments': 8, 'tool_budget': 3, 'incomplete_dialogue': 3}`.

Cost by role: `{'agent': 0.10400245, 'actor': 0.0121958, 'judge': 0.13193302}`. Agent cost per success: `0.0018909536363636364`. Token usage: `{'agent': {'calls': 185, 'input_tokens': 6059702, 'output_tokens': 33545}, 'actor': {'calls': 104, 'input_tokens': 102363, 'output_tokens': 3919}, 'judge': {'calls': 234, 'input_tokens': 5151294, 'output_tokens': 69057}}`.

## B evidence

[Full report](diagnostic-b-2.0.8/report.json); [trial checklist](diagnostic-b-2.0.8/report.md). Evidence SHA-256: `2da1d95bd71af8bc388a63b2864db76b0bc05a702dec4109d166ffc9f976d58c`.

Actor validity: `{'valid': 73, 'invalid': 2, 'uncertain': 3}`. Failure classes: `{'actor_validity': 5, 'budget': 1, 'grounding': 4, 'outcome': 7, 'tool_use': 4}`. Deterministic tool/argument/contract checks: `{'unsupported_money': 2, 'missing_call': 7, 'tool_arguments': 7, 'tool_budget': 2, 'incomplete_dialogue': 3}`.

Cost by role: `{'agent': 0.09108409, 'actor': 0.012192600000000001, 'judge': 0.12404718}`. Agent cost per success: `0.0015979664912280703`. Token usage: `{'agent': {'calls': 185, 'input_tokens': 6156076, 'output_tokens': 35186}, 'actor': {'calls': 105, 'input_tokens': 103076, 'output_tokens': 3770}, 'judge': {'calls': 234, 'input_tokens': 5154211, 'output_tokens': 66616}}`.

## C evidence

[Full report](diagnostic-c-2.0.8/report.json); [trial checklist](diagnostic-c-2.0.8/report.md). Evidence SHA-256: `d77c929e951605e96449b884d022083a373941fd1e64b2d2a335eb42840237ef`.

Actor validity: `{'valid': 75, 'invalid': 2, 'uncertain': 1}`. Failure classes: `{'actor_validity': 3, 'budget': 2, 'grounding': 4, 'outcome': 6, 'tool_use': 5}`. Deterministic tool/argument/contract checks: `{'unsupported_money': 3, 'missing_call': 5, 'tool_arguments': 5, 'tool_budget': 3, 'incomplete_dialogue': 1}`.

Cost by role: `{'agent': 0.0932561, 'actor': 0.0125684, 'judge': 0.12627572}`. Agent cost per success: `0.001607863793103448`. Token usage: `{'agent': {'calls': 188, 'input_tokens': 6259696, 'output_tokens': 36981}, 'actor': {'calls': 107, 'input_tokens': 106614, 'output_tokens': 3814}, 'judge': {'calls': 231, 'input_tokens': 5096960, 'output_tokens': 71634}}`.

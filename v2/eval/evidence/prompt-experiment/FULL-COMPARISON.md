# Full A/B/C comparison — 2.0.8

Frozen prompts and evaluator; three trials per case. Inconclusive trials are retained and excluded from scored rates, not retried. Calibration judgments have known limitations; these are measured outcomes, not independently verified truth.

| Arm | Scored / attempted trial slots / expected | Passed | Pass rate | Cases passing all 3 | Grounding violations | Rules violations | Cost | Latency p50 / p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A | 582 / 600 / 600 | 402 | 69.1% | 95 / 200 | 21 | 63 | $1.760913 | 21.8s / 32.4s |
| B | 585 / 600 / 600 | 424 | 72.5% | 101 / 200 | 23 | 60 | $1.780818 | 21.4s / 34.3s |
| C | 595 / 600 / 600 | 454 | 76.3% | 111 / 200 | 25 | 57 | $1.787713 | 22.4s / 36.7s |

Authentication recovery fills only original infrastructure-failed trial slots; scored and actor-inconclusive trials are never replaced. Original reports/journals remain unchanged. Costs and token totals include both original and recovery calls. Latency sums original and recovery execution time for each affected trial, excluding the human login wait. Execution-attempt counts and both evidence digests are listed below.

## Paired case comparisons

Difference is candidate minus A, in pass-rate percentage points. Only cases with all three valid scored trials in both arms are paired. Intervals resample scenario groups (10,000 samples; seed 360); they describe this finite corpus and do not remove judge noise or selection bias. Diagnostics were selected using historical results and are not an unbiased performance estimate.

| Subset | Comparison | Paired / excluded cases | Difference | 95% interval |
| --- | --- | --- | ---: | --- |
| all | B - A | 180 / 20 | +2.4 pp | -1.8 to +6.8 pp |
| all | C - A | 182 / 18 | +6.4 pp | +2.0 to +11.5 pp |
| development | B - A | 142 / 18 | +3.8 pp | -0.9 to +8.9 pp |
| development | C - A | 145 / 15 | +7.6 pp | +2.7 to +13.6 pp |
| reserved | B - A | 38 / 2 | -2.6 pp | -12.2 to +6.5 pp |
| reserved | C - A | 37 / 3 | +1.8 pp | -10.5 to +13.7 pp |

## Family results

Values are successful / scored trials; missing or inconclusive trials do not count as successes.

| Family | A | B | C |
| --- | --- | --- | --- |
| annual_evidence | 57 / 84 | 57 / 84 | 58 / 84 |
| annual_finance | 45 / 83 | 52 / 83 | 49 / 84 |
| annual_inputs | 69 / 107 | 72 / 107 | 81 / 108 |
| annual_routes | 60 / 82 | 69 / 82 | 69 / 83 |
| current_evidence | 63 / 71 | 57 / 72 | 66 / 72 |
| current_i95 | 26 / 54 | 24 / 53 | 38 / 58 |
| current_state | 62 / 70 | 66 / 71 | 66 / 71 |
| current_unsupported | 11 / 19 | 18 / 21 | 17 / 23 |
| mixed | 9 / 12 | 9 / 12 | 10 / 12 |

## A evidence

[Full report](full-a-2.0.8/report.json); [trial checklist](full-a-2.0.8/report.md). Evidence SHA-256: `7b13f3f388a7b85d7092f248ea738a7e4a051d4f24a33bfada82ab5b2f7895b5`.

Actor validity: `{'valid': 582, 'invalid': 8, 'uncertain': 10}`. Failure classes: `{'actor_validity': 18, 'budget': 10, 'clarification': 2, 'grounding': 19, 'outcome': 103, 'tool_use': 46}`. Deterministic tool/argument/contract checks: `{'tool_budget': 12, 'incomplete_dialogue': 21, 'missing_call': 42, 'premature_call': 3, 'tool_arguments': 38, 'unsupported_money': 5, 'agent_turn_budget': 2}`.

Cost by role: `{'agent': 0.6717036, 'actor': 0.092808, 'judge': 0.99640136}`. Agent cost per success: `0.0016709044776119402`. Token usage: `{'agent': {'calls': 1399, 'input_tokens': 45794911, 'output_tokens': 280968}, 'actor': {'calls': 783, 'input_tokens': 790220, 'output_tokens': 27572}, 'judge': {'calls': 1791, 'input_tokens': 39561539, 'output_tokens': 567481}}`.

## B evidence

[Full report](full-b-2.0.8/report.json); [trial checklist](full-b-2.0.8/report.md). Evidence SHA-256: `d43ea683711d1831db0c58186d2525b141f8bf416046bb319af154c6633e47ef`.

Actor validity: `{'valid': 585, 'invalid': 7, 'uncertain': 8}`. Failure classes: `{'actor_validity': 15, 'budget': 5, 'clarification': 2, 'grounding': 22, 'outcome': 83, 'tool_use': 49}`. Deterministic tool/argument/contract checks: `{'incomplete_dialogue': 22, 'missing_call': 49, 'premature_call': 3, 'tool_arguments': 44, 'unsupported_money': 5, 'tool_budget': 5, 'agent_turn_budget': 2}`.

Cost by role: `{'agent': 0.68755647, 'actor': 0.0958301, 'judge': 0.99743178}`. Agent cost per success: `0.0016215954481132075`. Token usage: `{'agent': {'calls': 1402, 'input_tokens': 46618630, 'output_tokens': 287558}, 'actor': {'calls': 793, 'input_tokens': 801006, 'output_tokens': 31459}, 'judge': {'calls': 1797, 'input_tokens': 39685131, 'output_tokens': 566602}}`.

[Recovery report](full-b-recovery-2.0.8/report.json): `cdc2e9bc488c419feb4fd9a0e27643f1722173353a3c0f17bce63bb9c80b5415`. Recovered trial slots: 42; total original plus recovery execution attempts: 642; recovery workers: 4 (original run: 4). The statistics above combine these reports without rewriting either one. Concurrency changes limit latency comparisons.

## C evidence

[Full report](full-c-2.0.8/report.json); [trial checklist](full-c-2.0.8/report.md). Evidence SHA-256: `063e6ed6881c1dcd355af018fc86d91aacc7c48ac5fbdb5b33d8268376aacc29`.

Actor validity: `{'valid': 595, 'invalid': 2, 'uncertain': 3}`. Failure classes: `{'actor_validity': 5, 'budget': 6, 'clarification': 2, 'grounding': 22, 'outcome': 73, 'tool_use': 38}`. Deterministic tool/argument/contract checks: `{'missing_call': 34, 'tool_arguments': 29, 'incomplete_dialogue': 17, 'premature_call': 3, 'unsupported_money': 8, 'tool_budget': 7}`.

Cost by role: `{'agent': 0.690336, 'actor': 0.0960223, 'judge': 1.0013544}`. Agent cost per success: `0.0015205638766519823`. Token usage: `{'agent': {'calls': 1406, 'input_tokens': 46768520, 'output_tokens': 297816}, 'actor': {'calls': 798, 'input_tokens': 811923, 'output_tokens': 29660}, 'judge': {'calls': 1800, 'input_tokens': 39782254, 'output_tokens': 579826}}`.

[Recovery report](full-c-recovery-2.0.8/report.json): `9afb319067ecf00cd6d8a29432e94b7698d24a4e09ce25840833d160c4fc38c3`. Recovered trial slots: 600; total original plus recovery execution attempts: 1200; recovery workers: 8 (original run: 4). The statistics above combine these reports without rewriting either one. Concurrency changes limit latency comparisons.

# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260802T171949Z.json`](20260802T171949Z.json) | Same four closures with fixed actor premises and scoped judges | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |
| [`20260803T210721Z.json`](20260803T210721Z.json) | Eight reciprocal single-leg cases, including the additive DTR fee on both Greenway mainline directions | Deterministic trace and response grading | 1.0000 overall; 16/16 judgments passed; 0 execution errors |
| [`20260803T212235Z.json`](20260803T212235Z.json) | Matching multi-turn single-leg conversations with fee attribution and arithmetic follow-ups | Deterministic trace grading plus goal-success and helpfulness judges | 0.9443 overall; 24/24 judgments passed; 0 execution errors |

The repaired run found exactly one raw `i95_route` execution per case, kept
every actor on its assigned route and time, and used response-only LLM
assertions. See `../deterministic/i95_historical_closures/` for the cases,
assertions, and runner. Telemetry-grounded analysis of the removed failed
baseline remains in `../eval-report.md`.

The single-leg deterministic run matched all eight captured tool results and
answers. Its Greenway cases returned `$5.80 + $2.00 = $7.80` eastbound and
`$2.00 + $5.80 = $7.80` westbound, with the `$2.00` item attributed to the
Dulles Toll Road. The simulated run preserved those tool results and totals
through both Greenway conversations; every trace, goal-success, and
helpfulness judgment passed.

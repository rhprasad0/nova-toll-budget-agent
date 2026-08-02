# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260802T171949Z.json`](20260802T171949Z.json) | Same four closures with fixed actor premises and scoped judges | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |

The repaired run found exactly one raw `i95_route` execution per case, kept
every actor on its assigned route and time, and used response-only LLM
assertions. See `../deterministic/i95_historical_closures/` for the cases,
assertions, and runner. Telemetry-grounded analysis of the removed failed
baseline remains in `../eval-report.md`.

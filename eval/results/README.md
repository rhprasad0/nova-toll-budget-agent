# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260802T165649Z.json`](20260802T165649Z.json) | Four historical I-95 closure cases, up to three agent turns each | Observational simulated user with goal-success and helpfulness judges | 0.4165 overall; 3/8 judgments passed; 0 execution errors |
| [`20260802T171949Z.json`](20260802T171949Z.json) | Same four closures with fixed actor premises and scoped judges | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |

The baseline exposed judge-visible cumulative traces, actor premise drift, and
missing date/scope context. The repaired run found exactly one raw `i95_route`
execution per case, kept every actor on its assigned route and time, and used
response-only LLM assertions. See
`../deterministic/i95_historical_closures/` for the cases, assertions, and runner,
and `../eval-report.md` for the telemetry-grounded analysis.

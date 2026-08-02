# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260802T165649Z.json`](20260802T165649Z.json) | Four historical I-95 closure cases, up to three agent turns each | Observational simulated user with goal-success and helpfulness judges | 0.4165 overall; 3/8 judgments passed; 0 execution errors |

The I-95 run exposed repeated `i95_route` calls during actor follow-ups and mixed
helpfulness on requests beyond toll pricing. See
`../deterministic/i95_historical_closures/` for the cases, assertions, and runner.

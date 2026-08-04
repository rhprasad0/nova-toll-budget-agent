# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260802T171949Z.json`](20260802T171949Z.json) | Same four closures with fixed actor premises and scoped judges | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |
| [`20260803T214705Z.json`](20260803T214705Z.json) | Eight reciprocal single-leg cases, including distinct additive DTR fee lines on both Greenway mainline directions | Deterministic trace and hardened response grading | 1.0000 overall; 16/16 judgments passed; 0 execution errors |
| [`20260803T215248Z.json`](20260803T215248Z.json) | Matching multi-turn single-leg conversations with neutral fee-attribution and arithmetic follow-ups | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 24/24 judgments passed; 0 execution errors |
| [`20260804T153800Z.json`](20260804T153800Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T153830Z.json`](20260804T153830Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T153901Z.json`](20260804T153901Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T191929Z.json`](20260804T191929Z.json) | Reciprocal I-66 / Dulles Toll Road handoffs through Dulles Connector Road | Code-graded live planner trajectory and response wording | 1.0000 overall; 2/2 cases passed; no airport wording |
| [`20260804T192029Z.json`](20260804T192029Z.json) | Ambiguous McLean location resolved before pricing | Simulated user, goal-success and helpfulness judges | 0.9165 overall; 2/2 judgments passed; 0 execution errors |
| [`20260804T192403Z.json`](20260804T192403Z.json) | Four historical I-95 closure conversations | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |

The repaired run found exactly one raw `i95_route` execution per case, kept
every actor on its assigned route and time, and used response-only LLM
assertions. See `../deterministic/i95_historical_closures/` for the cases,
assertions, and runner. Telemetry-grounded analysis of the removed failed
baseline remains in `../eval-report.md`.

The single-leg deterministic run matched all eight captured tool results and
answers. Its Greenway cases returned `$5.80 + $2.00 = $7.80` eastbound and
`$2.00 + $5.80 = $7.80` westbound, with the `$2.00` item attributed to the
Dulles Toll Road. The simulated run preserved those tool results and totals
through both Greenway conversations without giving the actor the expected
facility or amount; every trace, goal-success, and helpfulness judgment passed.

The three one-way-access runs each required `i95_access_options` before direct
I-95 pricing, correctly explained both the southbound Quantico exit and the
northbound Joplin entry restrictions without quoting a fare, and checked access
before the supported control route's one `i95_route` call. This satisfies the
three-perfect-run promotion criterion for the deterministic suite.

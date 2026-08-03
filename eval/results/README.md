# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260803T204055Z.json`](20260803T204055Z.json) | Sixteen direction-pinned I-66/I-495 and Dulles/I-495 conversations, capped at three turns | Simulation trace grading plus goal-success and helpfulness judges | 0.9443 overall; 48/48 judgments passed; 0 execution errors |
| [`20260802T171949Z.json`](20260802T171949Z.json) | Same four closures with fixed actor premises and scoped judges | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |
| [`20260802T200228Z.json`](20260802T200228Z.json) | Ten direction-aware I-95/I-495 junction cases after system prompt 1.1.0 | Deterministic trace and response grading | 1.0000 overall; 20/20 judgments passed; 0 execution errors |

The repaired run found exactly one raw `i95_route` execution per case, kept
every actor on its assigned route and time, and used response-only LLM
assertions. See `../deterministic/i95_historical_closures/` for the cases,
assertions, and runner. Telemetry-grounded analysis of the removed failed
baseline remains in `../eval-report.md`.

The junction run used exactly one `plan_toll_route` call and one
`i95_junction_leg` call per case, preserved the requested historical time on
every applicable pricing call, omitted `i495_route` for the inside-gap case,
and passed the adversarial no-zero-dollar/no-total response invariant. The
alias-control trace resolved Dumfries to I-95 Near Dumfries Road/Route 234 and
stopped the 95 leg at Franconia-Springfield before starting I-495 at `191NO`.

The matching simulation run kept every actor on its assigned directions, used
one to three TollChat turns per case under the three-turn cap, and passed all 16
trace, 16 goal-success, and 16 helpfulness judgments. The trace grader accepts
parallel leg completion order and independently verifies every repeated complete
route lookup.

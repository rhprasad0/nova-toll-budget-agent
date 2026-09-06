# Curated v2 evaluation evidence

Only technically valid, representative live runs belong here. Failed,
superseded, and ad hoc reports are not curated.

The generic annual-affordability golden corpus is maintained separately at
[`../golden/manifest.json`](../golden/manifest.json), version 1.0.0. It has ten
annual cases and four sanitized typed fixtures. The Leesburg-to-Washington
fixture is the authentic 08:30/17:30 partial result (51/60 complete pairs and
85.0% coverage); the rejected 12:00 zero-pair diagnostic is not evidence.

The fixture-only golden review is generated from the validated manifest and
four recorded, byte-pinned typed fixtures. The worktree-only review page is
pending human approval, is not pass^3 or unbiased evidence, and contains no
model transcript; candidate execution is deferred to #362/#363.
The live evaluator and Batch reports listed here are separate manual workflows,
never inputs to golden validation/rendering, and not approval evidence for this
fixture-only corpus.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260822T150912Z.json`](20260822T150912Z.json) | Reagan Airport and Pentagon/Eads Street to Westpark Drive | Live code-graded current-price trajectories and responses | 1.0000; 2/2 passed; each made one exact call to `i495:1859ND`, returned two observed components totaling $14.65, and reported Markdown, emojis, recent movement, median comparison, and 10:50 AM EST observation time |
| [`20260822T200050Z.json`](20260822T200050Z.json) | Dulles Airport to Reagan Airport | Live code-graded current-price trajectory and response | 1.0000; 1/1 passed; the exact cross-direction call returned typed stale I-95 availability rather than an internal validation error, and the response safely withheld a price |
| [`20260822T204150Z.json`](20260822T204150Z.json) | Annual affordability behavioral suite | Live code-graded annual trajectories and responses | 1.0000; 6/6 passed; covers fixed and modeled success, Tysons exit clarification, complete input acquisition, salary-range clarification, adjustable 52-week annual-day estimation, and Dulles-to-Reagan return-route unavailability |
| [`i95-missing-od-pricing.md`](i95-missing-od-pricing.md) | Missing I-95/I-495 OD identity-proxy model | Retained five-day holdout evaluation | 1,200 comparisons; $0.106 MAE; 96.1% within $0.50; $8.05 maximum error. Preliminary evidence only: clustered observations and short coverage limit stronger accuracy claims. |

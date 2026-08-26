# Curated v2 evaluation evidence

Only technically valid, representative live runs belong here. Failed,
superseded, and ad hoc reports are not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260826T163454Z.json`](20260826T163454Z.json) | Reagan Airport and Pentagon/Eads Street to Westpark Drive | Live code-graded current-price trajectories and responses after the 2.0.2 prompt deployment | 1.0000; 2/2 passed; each made one exact call to `i495:1859ND`, returned two observed components totaling $14.15, and visibly reported component provenance, recent movement, median comparison, and 12:20 PM EDT observation time |
| [`20260822T150912Z.json`](20260822T150912Z.json) | Reagan Airport and Pentagon/Eads Street to Westpark Drive | Live code-graded current-price trajectories and responses | 1.0000; 2/2 passed; each made one exact call to `i495:1859ND`, returned two observed components totaling $14.65, and reported Markdown, emojis, recent movement, median comparison, and 10:50 AM EST observation time |
| [`20260822T200050Z.json`](20260822T200050Z.json) | Dulles Airport to Reagan Airport | Live code-graded current-price trajectory and response | 1.0000; 1/1 passed; the exact cross-direction call returned typed stale I-95 availability rather than an internal validation error, and the response safely withheld a price |
| [`20260822T204150Z.json`](20260822T204150Z.json) | Annual affordability behavioral suite | Live code-graded annual trajectories and responses | 1.0000; 6/6 passed; covers fixed and modeled success, Tysons exit clarification, complete input acquisition, salary-range clarification, adjustable 52-week annual-day estimation, and Dulles-to-Reagan return-route unavailability |

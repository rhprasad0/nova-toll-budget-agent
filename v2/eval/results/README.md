# Curated v2 evaluation evidence

Only technically valid, representative live runs belong here. Failed,
superseded, and ad hoc reports are not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260822T150912Z.json`](20260822T150912Z.json) | Reagan Airport and Pentagon/Eads Street to Westpark Drive | Live code-graded current-price trajectories and responses | 1.0000; 2/2 passed; each made one exact call to `i495:1859ND`, returned two observed components totaling $14.65, and reported Markdown, emojis, recent movement, median comparison, and 10:50 AM EST observation time |
| [`20260822T184531Z.json`](20260822T184531Z.json) | Leesburg and Springfield-Franconia-to-Tysons $120,000 job-offer commutes | Live code-graded annual affordability trajectories and responses | 1.0000; 2/2 passed; the Tysons case asked for Westpark/Jones Branch/Route 7 without a tool call, then used exact `i95:206NO` → `i495:185ND` and `i495:185SO` → `i95:206SD` annual inputs and grounded the full Markdown/emoji affordability result |

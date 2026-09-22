# Golden eval caching and calibration validation

## Current candidate

PR 581 includes cached actor/judge requests, complete cache-write accounting,
fixture and actor corrections, and application prompt calibration. The application
model remains gpt-5.6-luna. Local runs use eight workers; protected CI retains four.

Corpus 1.0.25, harness 1.2.10, prompt 2.3.7 and pending policy 1.0.14 are the
current contracts. Protected activation and production qualification remain pending.
Local approval was recorded under the user standing authorization; it does not
replace protected review or qualify a production artifact.

The corrected wrong-route example consistently calls, returns and describes Route 7
when Route 28 was requested. Its expected labels remain Outcome fail, Grounding
pass and Rules fail. Actor corrections explicitly preserve one-way requests and
separate changed origins from unchanged destinations. Application prompt changes
clarify price provenance, annualized daily scenarios, user-selected income,
route direction, available missing-history baselines and combined commute costs.

Latest actor validation (actors-32): **60/60**. Latest calibration (calibration-33):
**179/180** label agreement. Outcome accepted the premature alternative-selection
example; Rules and mandatory deterministic checks rejected it. Its expected
labels were unchanged. Calibration evidence digest:
`9c19b74a480c5c33aa2ba09938d515fd0ce8fdb9eed90a4cbe393f31cc2fcb0b`.

Latest full-corpus run (durable-14) at
`27af1419aae8f0459391ff93b29b52aa6fe2e570`: **17/17 critical pass³, 72/72 trials**.
This is **one** success toward the requested three consecutive successes on an
unchanged candidate. No two-run streak has occurred. Work was paused at the user
request, then authorized for commit, push and merge with this goal unfinished.
Evidence digest:
`c7e7a1aaaacb3aea04ce7eb25ef97a485a648e0123c56d1617b7066afae527f7`.

All full-corpus attempts remain retained:

| Run | Critical pass³ |
| --- | ---: |
| 1 | 13/17 |
| 2–3 | 16/17 |
| 4 | 17/17 |
| 5–6 | 16/17 |
| 7 | 15/17 |
| 8 | 16/17 |
| 9–10 | 15/17 |
| 11–13 | 16/17 |
| 14 | 17/17 |

No verdicts were replaced or relabeled to improve scores. Held-out failure
transcripts were not used for tuning. Full journals, reports, exact local review
records and the attempt ledger remain under ignored
`eval/private/critical-pass3/`. This summary is not executable evidence.
Recorded cumulative spend through durable-14: **$13.26434494**.

Validation: latest affected application/gate checks **64 passed**; preceding full
relevant suite **156 passed**. Ruff, version contract, completed usage, spending
lineage and offline evidence replay checked. GitHub CI must pass on the pushed
head independently. Documentation added afterward does not claim another scored run.

## Historical caching validation

The manual runner and protected eval CI share explicit prefix caching and
cache-write accounting. This historical comparison preceded the application prompt corrections below.
Scheduled-check sources are unchanged.
Adversarial review isolated the factory to the golden runner, bound adapter source
to calibration identity and CI receipts, and corrected stale activation docs.

| Run | Workers | Agreement | Wall time | Cost | Cache reads / writes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibration 22 | 4 | 180/180 | 130.67 s | $0.11008381 | 230,513 / 3,907 |
| Calibration 23 | 8 | 179/180 | 70.09 s | $0.10902200 | 234,420 / 0 |
| Calibration 24, after review fixes | 4 | 179/180 | 131.00 s | $0.10971680 | 234,420 / 0 |

Each calibration made 180 fresh judge calls over 60 examples with 516,298 input
tokens and complete usage. Cache savings were 27–28% against the same tokens at
uncached rates, including write charges. Later runs reused warm prefixes. Eight
workers were 1.86× faster in the original comparison; this was not a quota stress
test. Protected CI retains four scored workers under the existing timing policy;
local validation uses eight.

Calibration 23 falsely passed Grounding for
`annual-tysons-clarification-silent-modeling`, missing an observed-price claim
despite `uses_modeled=true`. Calibration 24 falsely passed Outcome for
`greenway-current-wrong-route`: it accepted a correct destination in the returned
fixture despite the wrong destination in the call. Rules rejected both examples.
Neither miss was relabeled or rerolled; the four-worker miss means concurrency is
not an established cause. Historical actor checks passed 60/60 (87 calls,
27.80 seconds, $0.01947340); they were not rerun after factory relocation.

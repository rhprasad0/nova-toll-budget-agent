# Golden harness caching: adversarial review

**Implementation reviewed; calibration and activation remain pending.** This
supersedes REVIEW-22's proposed approval. No new application-scored run was made.

## Findings and fixes

- **Scope leak:** `eval/simulated.py` is included in scheduled-check packages.
  Keeping caching there would change deployed checks. Restored that module to
  main and moved the cached factory into `eval/golden_run.py`, shared by manual
  golden runs, actor checks, and the protected eval CI entrypoint. Application
  code, prompts, models, application tests, and scheduled-check sources match main.
- **Stale calibration:** hashing the adapter module only in CI receipts did not
  invalidate calibration when its implementation changed. Calibration transport
  identity now hashes the reused adapter class source; regression coverage checks
  invalidation. CI receipts also bind the module source.
- **Existing PR feedback:** removed the application SOP change implicated in the
  no-complete-paired-days review finding. Fixed activation documentation that still
  named policy 1.0.2; approval must bind the active policy's exact digest.
- **Unresolved judge accuracy:** fresh calibration has the disagreement below.
  Pending review markers remain in place. No verdict, label, or threshold was
  changed to hide it, and no replacement calibration was run.

## Fresh calibration 24

Source `17bcdad`; corpus **1.0.19**, harness **1.2.9**, four workers. All 60
examples completed with 180 fresh judge calls and complete usage. Agreement is
**179/180**. Wall time was **131.00 seconds**; median call latency was 2.40 seconds.
Input/output tokens: **516,298 / 40,544**; cache reads/writes: **234,420 / 0**.
Input cost was **$0.06106400**, output **$0.04865280**, total **$0.10971680**.
The same tokens at uncached rates cost $0.15191240: 27.8% savings. Prefixes were
already warm; this is not a cold-cache measurement or a quota stress test.

Outcome incorrectly passed `greenway-current-wrong-route`. The call used
`greenway:7:exit:EB`, while the requested destination and returned fixture payload
used `greenway:28:exit:EB`. The judge explicitly treated the wrong argument as
Rules-only despite the unchanged expected Outcome failure. Rules correctly failed;
Grounding passed as expected. Human adjudication must address this mismatch before
approving the exact calibration. The overall trial would still fail Rules.

Calibration 22's four-worker 180/180 and calibration 23's eight-worker 179/180
remain archived with their original identities. Calibration 24's four-worker miss
further cautions against attributing calibration 23's miss to concurrency. Keep the
existing four-worker scored timing policy; eight workers remain diagnostic only.
The historical [benchmark](../../results/golden/caching-benchmark.json) records the
1.86× speedup and limitations. Actors-3's 60/60 is historical evidence; it was not
rerun at this source. No evidence here qualifies main's application behavior.

## Exact evidence

- [Calibration 24](calibration-24/report.md):
  `c92c0dcb52f97b4dbcf87d8e41a0ae19a29a11255d2458c7d7b60c5e20ca9c30`.
- Archive:
  `8fb2126b95e3922560e7dfb25cc0857e3888ca0c32aadfc5dbe089ba1648504c`.
- Evaluation contract:
  `90cd27c9cb250c185c8dcdce31ab1a6b1e9db4f580898d7b91231f82a1465e69`.
- Pending [policy 1.0.8](../../results/golden/policy-1.0.8.json):
  `f969ed44d8d18a9b21ff11f7f3e78d79b504790be78580a908bb19d368681766`.
  Numeric thresholds, trial counts, and four-worker timing are unchanged.

Recorded cumulative spend is **$7.49763687**. The ledger continues actors-3 →
calibration-24. Use private `eval/private/critical-pass3/calibration-24` as the next
`--prior-run`. Older totals remain recorded estimates with their stated accounting
limitations. Render private copies only; retained archives are immutable.

## Validation

**155 focused tests passed**, covering runner, gate, corpus, baseline, simulation,
and the two previously failing release-contract checks. Changed Python files pass
Ruff lint and formatting. New evidence replays from its journal and carries file
hashes. The CI execution-path regression checks cache parameters, medium judge
reasoning, four workers, cache-write charging, and spending settlement.

Human calibration/corpus/policy approval is still required before scored execution
or CI activation. PR review and CI do not replace that approval. Historical scored
application experiments remain evidence only; no application edits ship here.

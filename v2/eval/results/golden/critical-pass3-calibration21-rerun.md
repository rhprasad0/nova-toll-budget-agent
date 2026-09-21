# Calibration 21 — approved-contract rerun

**72/72 trials passed, including 51/51 critical trials: 17/17 critical pass³.** All 24 cases passed each of their three trials. No actor-invalid or infrastructure trials occurred.

Application prompt 2.3.5 and model settings are unchanged. This run uses approved calibration 21, corpus 1.0.17, harness 1.2.7, and policy 1.0.6 with unchanged numeric thresholds. The evaluator now has the supported timestamp, default-profile, location, and distance-baseline context described in the [review packet](../../evidence/critical-pass3/REVIEW-21.md).

The previous prompt-2.3.5 run scored 15/17 critical pass³ under a different evaluator contract. This clean result is not evidence of an application improvement. Earlier results remain archived; judge randomness and response variation persist, held-out cases are exposed, and one clean run does not establish stable perfect reliability.

| Metric | Result |
| --- | --- |
| Critical pass³ | 17/17 |
| Critical successful trials | 51/51 |
| Overall successful trials | 72/72 |
| Overall pass³ | 24/24 |
| Invalid trials | 0 |
| Recorded model cost | $0.40641310 |
| Latency median / p95 | 17.16s / 27.49s |
| Linked cumulative recorded spending | $7.14934086 |

## Caching baseline for the next conversation

No new caching changes were made for this run.

| Role | Input tokens | Cached input | Output tokens | Recorded cost |
| --- | --- | --- | --- | --- |
| Application | 5,833,415 | 5,728,605 | 39,544 | $0.18298690 |
| Actor | 100,943 | 0 | 4,973 | $0.02615620 |
| Judge | 656,800 | 0 | 54,925 | $0.19727000 |

All recorded cache-write token counts were zero. The actor/judge SDK path currently drops cache-write usage, so these ledger amounts are estimates rather than invoice reconciliation. See the [caching handoff](CACHING-HANDOFF.md) for the accounting fix and implementation plan.

## Evidence

- [Archived report](runs/05166e1460246fa94107fa6ef86040b3103d01a9c5e707c2e86277dd3c802ab1/report.md), with original journal, manifest, and file hashes alongside it.
- Evaluated commit: `f4093e3`.
- Evidence SHA-256: `98522cad7c84e23bd993c7f16d301964b2186aecb4e1a5bcc6a03ad6f8f3ae05`.
- Private run directory: `eval/private/critical-pass3/candidate-6` (from `v2/`). Use it as the next run's `--prior-run` to carry forward recorded spending.
- Archive replay validation and secret scanning passed. The 49 evaluator tests and all 47 approval-gate tests passed before this run; no application or evaluator code changed during execution.

This is source-checkout evidence, not production artifact qualification. Production registries remain unchanged. No push, PR, merge, or deployment occurred.

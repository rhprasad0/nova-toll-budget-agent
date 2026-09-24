# Second development baseline with corrected measurement

**300/300 trials finished: 176 passed, 123 failed, and 1 inconclusive.** Scored-trial success is **58.9% (176/299)**. Open the [static review](baseline-2-review.html) for every conversation and judge explanation.

For a shorter review, open the [10-case sample](baseline-2-sample-review.html): 30 complete trials with selection notes, tool evidence, and the original verdicts. It covers successes, failures, and evaluation inconsistencies; it is not a random statistical sample.

This run uses corpus 3.0.4 / harness 2.0.11 after the [measurement fixes](FIXES-BASELINE-2.md), the 9/9 actor preflight, and [calibration 6](CALIBRATION-6.md). All 100 cases and 107 fixtures are unchanged. Application model and prompt are unchanged. There are three fresh trials per case, 16 workers, and at most five delivered user turns. No trial was retried or replaced.

| Metric | First baseline | Second baseline |
| --- | ---: | ---: |
| Scored trials | 287/300 | 299/300 |
| Inconclusive trials | 13 | 1 |
| Valid / invalid / uncertain actors | 287 / 4 / 9 | 299 / 1 / 0 |
| Passed / scored | 156/287 (54.4%) | 176/299 (58.9%) |
| Cases passing all three trials | 33/100 | 35/100 |
| Fully scored measurement | No | No |

The first baseline remains unchanged. Changes in scores are not an application improvement estimate: actor behavior, termination classification, and money parsing changed, and model/judge sampling varies. There is no independent holdout or production qualification.

## Failure categories

| Primary category | Trials |
| --- | ---: |
| actor_validity | 1 |
| clarification | 4 |
| grounding | 4 |
| outcome | 64 |
| tool_use | 51 |

## Measurement findings

**Subsequent review:** Ryan requested more lenient annual Outcome grading after reviewing case 52. The [3.0.5 contract revision](ANNUAL-OUTCOME-REVIEW.md) makes separate P25/P90 toll figures optional and accepts semantic historical-source descriptions. [Calibration 8](CALIBRATION-8.md) matches the revised case-52 Outcome expectations of pass/pass/fail; [baseline 3](BASELINE-3.md) records the fresh application run. The scores and verdicts below remain the original 3.0.4 measurements.

- [Case 59, trial 1](baseline-2-review.html#dev3-one-day-team-meeting-1) is the only inconclusive. The actor judge marked it invalid because the conversation stopped without completing the requested estimate. No execution error occurred.

Case 59 trial 1 is a remaining judge inconsistency: the actor had no more precise Braddock Road fact and stopped after the application explained that limitation, as the actor instructions permit. The actor judge instead treated the unfinished application goal as actor misconduct. The measured inconclusive verdict remains unchanged; reviewer recommendation is actor-valid with failed application Outcome. This is a new finding from baseline 2, not one of the first-baseline fixes.

## Provenance and cost

- Run cost **$0.92992747**; cumulative **$3.09280985 of $25**, including all six calibrations, the actor preflight, and both baselines.
- 1,982 model calls, all usage known. Full-trial latency median/p95: 23.62s / 42.56s.
- Delivered user-turn distribution: `{1: 183, 2: 103, 3: 12, 4: 2}`.
- Source commit `118b91f73161d4af94b30a080dc28ed6a48e88a6`; run `f3aaa5b7-8818-413e-afe0-68c1f1d82989`.
- Corpus SHA-256 `f37fc6757e07e427845951228cdb0bc36943221cd63917255905cd4fa09f42d1`; evidence SHA-256 `bcfce8082acf4a1ebcf75a573e476eb8733620406393bdb3bc8942a0ef662464`.
- [Raw report](runs/8c5bc3d2a151dce237e9946bbc679bf9d2d0b99cd1777a2c363026664a37306f/report.json), [event journal](runs/8c5bc3d2a151dce237e9946bbc679bf9d2d0b99cd1777a2c363026664a37306f/events.jsonl), [manifest](runs/8c5bc3d2a151dce237e9946bbc679bf9d2d0b99cd1777a2c363026664a37306f/manifest.json), [receipt](receipt-baseline-2.json).

Human review of application/actor results remains pending. The execution authorization and calibration review do not approve these newly measured application results.

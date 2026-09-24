# Third development baseline — relaxed annual Outcome grading

**300/300 trials finished: 206 passed, 93 failed, and 1 inconclusive.** Scored-trial success: **68.9% (206/299)**. [Open all 300 conversations and verdicts](baseline-3-review.html).

Contract **3.0.5 / harness 2.0.12** accepts the P50 toll summary and combined-cost scenarios without requiring separate P25/P90 toll figures, and grades historical-source descriptions semantically. All 100 prompts, actor profiles, tool workflows, 107 fixtures, and the application model/prompt are unchanged. Three fresh trials per case; 16 workers; at most five delivered user turns. No trial was retried, replaced, or rescored.

## Comparison

| Metric | Baseline 1 | Baseline 2 | Baseline 3 |
| --- | ---: | ---: | ---: |
| Passed | 156 | 176 | 206 |
| Failed | 131 | 123 | 93 |
| Inconclusive | 13 | 1 | 1 |
| Passed / scored | 54.4% (156/287) | 58.9% (176/299) | 68.9% (206/299) |
| Cases passing all three | 33/100 | 35/100 | 45/100 |
| Fully scored measurement | No | No | No |

The earlier baselines retain their original contracts and verdicts. Score differences are not evidence of application improvement: the Outcome contract changed and model/judge sampling varies. This is an exposed development set, not an independent holdout or production qualification.

## Calibration and limitations

[Calibration 7](CALIBRATION-7.md) measured 135 references: **389/396 application labels and 135/135 actor labels match**. All negative controls remain rejected overall. Codex reviewed its seven disagreements under Ryan's execution authorization before this run. The limitations include unnecessary restatement/formatting failures and the disputed Rules label on Gallows trial 3's source contradiction. The original labels and measurements remain unchanged.

Ryan requested another calibration after this baseline started. [Calibration 8](CALIBRATION-8.md) subsequently measured the unchanged contract: **392/396 application labels and 135/135 actor labels match**, with four disagreements. Both acceptable Gallows regression answers pass; its false-source answer still fails. This repeat does not replace calibration 7 in the baseline's execution receipt.

## Gallows hybrid salary

| Trial | Outcome | Grounding | Rules | Overall |
| --- | --- | --- | --- | --- |
| [Trial 1](baseline-3-review.html#dev3-gallows-hybrid-salary-1) | Fail | Pass | Fail | Fail |
| [Trial 2](baseline-3-review.html#dev3-gallows-hybrid-salary-2) | Pass | Pass | Pass | Pass |
| [Trial 3](baseline-3-review.html#dev3-gallows-hybrid-salary-3) | Pass | Pass | Pass | Pass |

## Primary failure categories

| Category | Trials |
| --- | ---: |
| actor_validity | 1 |
| clarification | 2 |
| grounding | 8 |
| outcome | 29 |
| tool_use | 54 |

## Measurement and cost

- Actor validity: `{'valid': 299, 'invalid': 1, 'uncertain': 0}`.
- Delivered user turns: `{1: 186, 2: 101, 3: 12, 4: 1}`.
- Full-trial latency median / p95: **21.23s / 34.44s**.
- This baseline: **$0.91023745**; cumulative through this run: **$4.23407822 of $25**. 1,970 model calls, all usage known. Calibration 8 spending is recorded separately in its receipt.
- Run `fec06c4c-cc57-42b0-b0a6-81c7138fadfb`; source commit `36a320ee400bf75528ad3febced342ba7739c34c`.
- [Raw report](runs/b3767839406c4bef925cda88f7d9b9ffbae17d05442d23fefe00844642d1f1d9/report.json) · [Event journal](runs/b3767839406c4bef925cda88f7d9b9ffbae17d05442d23fefe00844642d1f1d9/events.jsonl) · [Receipt](receipt-baseline-3.json).

**[Case 92, trial 2](baseline-3-review.html#dev3-monthly-versus-daily-budget-2): inconclusive.** The actor judge marked the final stop premature because the annual estimate was unfinished. Three user turns were delivered; the conversation remained on facility clarification. The assistant answered the monthly-average question but made no price call or annual estimate. No execution error occurred. The original actor verdict remains recorded for review.

Human review of application/actor results remains pending. The execution review does not approve these newly measured application results.

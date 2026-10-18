# TollChat experiment journal

Experiments, figures, and decisions are organized by week. Each page records
what was tested, the results, their limits, and what was retained or rejected.
Development scores, calibration agreement, and live checks have different scopes;
the weekly accounts keep those distinctions alongside the figures.

| Week | Work | Recorded result |
| --- | --- | --- |
| [October 12-18](journal/2026-10-12.md) | Eastern display times (corpus 5.2.13); holdout guard removal; RDS CA pin; v1.2.0 holdout comparison; billing refresh timing; mcp and multidict upgrade (5.2.14); Haiku 5.5 judge evaluation; eval tooling retirement (5.2.18) | v1.2.0 holdout pass³ **78.4% vs 72.0%** against v1.1.2 (within run-to-run spread); re-judging the same conversations, Haiku cost **2.2×** Luna's judging without being more accurate, so **Luna was retained** |
| [October 5-11](journal/2026-10-05.md) | Freeze all three suites and calibrate daily judges; climb training pass³ with SOP prose | Golden: **100% judge decisions, ≥95% actor validity**, earlier application **63/85 passes**, ceiling **$22.924064**; scheduled: **204/204 judgments**, **$0.0492** estimated; SOP climb: training pass³ **70.4% → 80.7%**, **$17.07** |
| [September 28-October 4](journal/2026-09-28.md) | Retire the private holdout approach; repair certificate/dependency builds; measure inference cost | Controlled benchmark: **$1.115488 per 1,000 completed answers** at the sampled average; infrastructure and tool execution excluded |
| [September 21-27](journal/2026-09-21.md) | Calibrate judges; compare prompts and catalog formats; test repeatability; profile CI | Final development verification: **269/300 successful trials, 78% pass³**; below the **271/300 target** |
| [September 14-20](journal/2026-09-14.md) | Simulate deployment/recovery outcomes; run the early agent demonstration | Demonstration: **27/72 successful trials**; actor and grader problems remained |
| [August 17-23](journal/2026-08-17.md) | Check selected live current-price and annual workflows | Current-price checks **2/2**, annual checks **6/6**; two answers used the wrong timezone label |

Weeks run Monday through Sunday. Historical work belongs to its original week
when the date is documented; retrospective publication dates remain recorded.
Undated experiments stay in their summary's week. Pass³ means a case passed
all three attempts; single-trial results do not have a pass³ score.

## Maintaining the journal

This index and the weekly pages are permanent experiment history. Preserve their
material findings, figures, limitations, and decisions. Add new experiments to
`journal/YYYY-MM-DD.md`, using the week's Monday, and add its link here.
Append dated corrections without silently changing earlier results. Consolidate
related entries in plain language; keep transcripts and granular run data private.

See the [evaluation guide](README.md) for current usage. The
[September 27 reliability report](CURRENT_TIME_RELIABILITY_2026-09-27.md)
retains the requested detailed diagnostic and former-gate comparison.

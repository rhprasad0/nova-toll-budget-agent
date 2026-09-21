# Calibrated comparison baseline — September 21, 2026

This retained run is a provisional reference for future comparisons, using
approved calibration 15, corpus 1.0.11, harness 1.2.1, and source commit
`4dd8fc361ab27315a362d59e014d77625921110f`. It is not a qualified production
baseline: one trial is inconclusive, human actor review is pending, and the
recorded scores fall below the approved release thresholds. The initial and
production registry references are unchanged.

## Recorded results

| Metric | Result |
| --- | --- |
| Attempted trials | 72/72; four workers, three fresh trials per case |
| Scored trials | 71; 58 passed, 13 failed |
| Overall pass@1 | 81.7% (58/71 scored trials) |
| Overall pass³ | 62.5% (15/24 cases) |
| Critical pass³ | 70.6% (12/17 critical cases) |
| Current-price pass@1 | 93.9% (31/33) |
| Annual-affordability pass@1 | 71.1% (27/38) |
| Outcome-only success | 90.1% (64/71) |
| Total estimated model cost | $0.39243294 |
| Prior accounted spend | $2.13301152 |
| Cumulative accounted spend | $2.52544446 of the $25 ceiling |
| Trial latency, median / p95 | 20.96s / 35.27s, including actor and judges |

The inconclusive trial is excluded from the pass@1 denominator and cannot count
toward pass³. The report does not calculate a confidence interval for an
incomplete measurement. These are frozen synthetic conversations, not live
traffic. The older 37.5% result used a different evaluation contract and is not
a comparable before/after measurement of application improvement.

## Cases short of three passes

| Case | Passes | Recorded failures or inconclusive result |
| --- | --- | --- |
| `greenway-current` | 2/3 | Published schedule rate described as observed |
| `greenway-origin-correction` | 2/3 | Published schedule rate described as observed |
| `annual-salary-range` | 1/3 | Two deterministic `unsupported_money` failures; all three judges passed both trials |
| `annual-hourly-income` | 1/3 | Annualized daily scenario labeling; fixed versus historical source wording |
| `annual-confirm-days` | 2/3 | Annualized daily scenario labeling |
| `annual-invalid-schedule` | 1/3 | Unsupported 265-day maximum claim; one trial also failed scenario labeling |
| `annual-independent-ramps` | 2/3 | Trial 2 inconclusive: `actor_turn_limit` |
| `annual-confirm-divergent` | 0/3 | All three calls used `i95:206NO` instead of required `i95:212NO` |
| `annual-no-paired-days` | 2/3 | Deterministic `unsupported_money`; all three judges passed |

Assistant inspection found potential measurement issues requiring review:

- The salary-range failures include proposed income choices before the user
  selects one; they should not automatically be interpreted as invented income.
- The missing-history response explicitly says missing toll data is **not**
  treated as $0, yet the deterministic money check rejects it.
- In the inconclusive independent-ramps trial, the actor denied having supplied
  Pentagon/Eads despite its presence in the initial question, then continued
  until the turn limit.

These observations are not human adjudication. No verdicts were relabeled and
no trials were retried. Held-out cases had prior exposure and must not be
presented as untouched holdouts; this run also exposes their conversations.

## Evidence and reuse

The [archived report](runs/a3f57ed31ca79c396a5b05d8c4e24889ebe65a00e1ceea1d949f12c8c6aeceaf/report.md)
and [full JSON report with transcripts](runs/a3f57ed31ca79c396a5b05d8c4e24889ebe65a00e1ceea1d949f12c8c6aeceaf/report.json)
retain the original results. The same directory contains the original manifest,
append-only journal, and SHA-256 inventory. The archive helper checked the report
against an offline rendering of its journal and preserved all four source files
byte for byte.

Evidence digest: `946166a23ff3b481350b040ebd59cb46790f0959eff17adc5c24f2e873093262`.

Compare future runs only with matching corpus, judges, actors, fixtures, model
settings, and deterministic checks. If measurement fixes change that contract,
retain this run and establish a new comparable reference rather than rewriting
these results. Account for subsequent paid runs in the cumulative spend ledger.

To regenerate the existing eight-sample review page offline, from `v2/`:

```bash
uv run python -m eval.golden_baseline review \
  --run eval/results/golden/runs/a3f57ed31ca79c396a5b05d8c4e24889ebe65a00e1ceea1d949f12c8c6aeceaf \
  --policy eval/results/golden/policy-1.0.2.json \
  --output eval/private/calibrated-baseline-review.html
```

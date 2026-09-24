# First development baseline on corpus 3.0.3

**All 300 trials finished: 156 passed, 131 failed, and 13 were inconclusive.** The recorded success rate is **54.4% of scored trials (156/287)**. This is a retained comparison baseline, with actor and measurement review pending. Open the [raw report](runs/c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430/report.json) for all 300 complete conversations, tool results, checks, and judge explanations.

Ryan approved the current corpus and [calibration 5](CALIBRATION-5.md) before execution. The run used **16 workers**, three fresh trials for each of 100 development cases, and a five-user-turn maximum including the opening request. Actual conversations used one turn in 190 trials, two in 96, and three in 14. No application model, prompt, corpus, fixture, or evaluator change was made for this run.

## Recorded results

| Metric | Result |
| --- | --- |
| Attempted trials | 300/300 |
| Scored trials | 287: 156 passed, 131 failed |
| Inconclusive trials | 13: 4 invalid and 9 uncertain actor-validity assessments |
| Scored-trial success | 54.4% (156/287) |
| Outcome-only success | 57.8% (166/287 scored trials) |
| Cases passing all three trials | 33 of all 100 cases |
| Reported pass³ | 37.1% (33/89 cases with three scored trials) |
| Full scored measurement complete | No; the 13 inconclusive trials prevent this |
| Trial latency, median / p95 | 24.86s / 43.98s, including actor and judges |
| Model calls | 1,964; all usage known |
| Run cost | $0.91475671 |
| Cumulative cost | $1.92986522 of $25, including five calibrations |

Inconclusive trials are excluded from the scored-trial success denominator and cannot count as passes. The renderer withholds a confidence interval because the scored measurement is incomplete. These are synthetic development conversations against frozen evidence, not live traffic or an independent holdout. Older baselines use different contracts and are not comparable measures of application improvement.

| Workflow | Passed / scored | Success | Inconclusive / attempted |
| --- | ---: | ---: | ---: |
| Current pricing | 87/113 | 77.0% | 7/120 |
| Annual affordability | 62/160 | 38.8% | 5/165 |
| Mixed workflow | 7/14 | 50.0% | 1/15 |

The runner assigns one primary failure category per unsuccessful or inconclusive trial:

| Primary category | Trials |
| --- | ---: |
| Outcome | 81 |
| Tool use | 39 |
| Grounding | 9 |
| Clarification | 2 |
| Actor validity (inconclusive) | 13 |

## Findings to review

- **Annual answer completeness:** recurring Outcome findings concern daily toll amounts for every P25/P50/P90 scenario, source disclosure, and the distinction between historical scenarios and forecasts or guarantees. Some caveat findings merit review under semantic leniency; for example, [case 41, trial 2](runs/c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430/report.json) calls the result a rough screen and distinguishes annualized scenarios from annual percentiles, but is failed for omitting a forecast/guarantee qualification. These are recorded judge findings, not adjudicated application defects.
- **Route selection:** wrong-direction endpoint IDs cause rejected calls and missing answers. For example, [case 2, trial 1](runs/c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430/report.json) uses eastbound Greenway points for the requested westbound Route 28-to-Ryan Road trip. This is an application/tool-use failure.
- **Timestamp conversion:** [case 18, trial 1](runs/c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430/report.json) reports 1:09 AM for a 17:09:30−04:00 observation. Grounding and Rules reject the incorrect time; Outcome incorrectly accepts it. The overall trial still fails.
- **Four apparent deterministic false positives:** [case 32, trial 2](runs/c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430/report.json) and all three trials of case 35 accurately express a negative comparison as a positive amount “below” the median. The money parser retains +$1.80 or +$0.10 while the evidence stores −$1.80 or −$0.10. All three semantic judges pass these four trials, but `unsupported_money` makes the overall result fail. The shared parser needs a scoped follow-up fix; these baseline verdicts remain unchanged.
- **Actor validity:** four trials are marked invalid: two stop before supplying requested endpoints, one returns a missing reply, and one rejects alternatives despite a required selection. Nine others are marked uncertain because no actor reply/stop record exists after an application call was rejected. Those nine assessments merit review: absence of a later actor turn does not itself establish actor misconduct. All 13 remain inconclusive in this record.

The realistic scenarios remain useful: case 80 respects cancellation in **3/3 trials**. Case 79 handles confirmation correctly in all three but passes overall in **1/3**; the other two fail for missing daily-toll scenario amounts or source disclosure. Both use two delivered user turns in every trial. The no-paired-history and published-fixed-rate interpretation cases each pass **3/3**.

No failed or inconclusive trial was retried or replaced. The report has not been relabeled, and no adjusted success rate is substituted for the measured baseline.

## Evidence and reuse

The existing archive helper verified the report against an offline rendering and copied the four raw artifacts byte-for-byte. All model starts have matching finishes and known usage; cost reconciles with the journal. Corpus and calibration approvals predate execution. The removed static page was checked against every transcript, verdict, and status, plus offline loading, keyboard access, links, and mobile layout. Repository static checks passed. The application/evaluator code is unchanged from the previously tested revision.

- Source commit: `545d66314b31806e2ec5b09c9a32c65add76d823`; corpus `3.0.3`; harness `2.0.10`.
- Run ID: `ed281384-fc39-47a7-88e3-43aa7f947b9c`.
- Corpus SHA-256: `596b2f1c7abd0c77087c415da7905b673561011f06c612e9d27a739acad6833f`.
- Evidence SHA-256: `53bee6705115716ab80a09766f08c467194871145328502da9af871d110bcf48`.
- [Raw report](runs/c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430/report.json), [trial checklist](runs/c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430/report.md), [receipt and hashes](receipt-baseline-1.json), and [exact calibration approval](calibration-5/review.json).

Future comparisons need the same evaluation contract. A parser or judge change requires retaining this run and recording a new calibration/baseline contract. The protected production policy and registry are unchanged; this development baseline cannot qualify a release.

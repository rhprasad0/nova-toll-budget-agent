# Prompt comparison: completed full evaluation

**2026-09-24 decision: Ryan selected C for the main TollChat agent.** See the
permanent [experiment journal](../../EXPERIMENT_JOURNAL.md). This supersedes the
initial recommendation to retain A pending grounding review; the evidence and
grades below are unchanged. C's paired gain over A is positive; B's is inconclusive.
Reserved-case uncertainty and known grading limitations prevent treating C as a
validated replacement. No prompt was revised after diagnostics or reserved-case
inspection.

| Measure | A baseline | B descriptions | C descriptions + reordered SOP |
| --- | --- | --- | --- |
| Full run: passed / scored | 402 / 582 (69.1%) | 424 / 585 (72.5%) | 454 / 595 (76.3%) |
| Inconclusive trials | 18 | 15 | 5 |
| Cases passing all three trials | 95 / 200 | 101 / 200 | 111 / 200 |
| Grounding flags / scored | 21 / 582 | 23 / 585 | 25 / 595 |
| Rules flags / scored | 63 / 582 | 60 / 585 | 57 / 595 |
| Development: passed / scored | 324 / 464 | 348 / 466 | 371 / 477 |
| Reserved: passed / scored | 78 / 118 | 76 / 119 | 83 / 118 |
| Full-run cost, including interruption | $1.760913 | $1.780818 | $1.787713 |

Each arm covers the same 200 cases and 600 trial slots. Actor-inconclusive trials
remain in evidence and are excluded from scored rates; none were retried.

| Paired comparison | Complete paired cases | Gain | 95% scenario-group interval |
| --- | ---: | ---: | --- |
| B minus A, all | 180 | +2.4 pp | -1.8 to +6.8 pp |
| C minus A, all | 182 | +6.4 pp | +2.0 to +11.5 pp |
| B minus A, reserved | 38 | -2.6 pp | -12.2 to +6.5 pp |
| C minus A, reserved | 37 | +1.8 pp | -10.5 to +13.7 pp |

See the [full comparison](FULL-COMPARISON.md) for family results, development
intervals, latency, token usage, contract checks, costs per success and original
evidence links. The earlier [26-case diagnostics](DIAGNOSTIC-COMPARISON.md) gave
both candidates only a +1.5-point paired gain, with intervals spanning zero.

## What changed in measured behavior

C improves current I-95 outcomes (38/58 versus A's 26/54) and annual-input
outcomes (81/108 versus 69/107). Wrong-argument flags decrease from 38 to 29 and
missing-call flags from 42 to 34. These counts include retained inconclusive
attempts; family success rates use scored trials. Annual evidence and financial
explanations remain frequent failure areas. Agent cost per success falls from
$0.001671 for A to $0.001521 for C, while total full-run cost rises slightly.

Concrete transcript checks, without changing grades:

- **Closure proof:** A and B fail all three trials on the strict Westpark
  endpoint-ID check before the proof follow-up. C fails two the same way; its
  third trial selects the accepted endpoint and correctly states that no official
  closure notice or source metadata was supplied, then directs the user to
  official channels. This is one successful exercise of the proof behavior, not
  three clean tests of that behavior per arm.
- **Withdrawal of consent:** C passes all three `annual-withdraw-earlier-consent`
  trials without calls after withdrawal. B's first trial honors cancellation but
  offers a prohibited current-price substitute; it does not execute that offer.
- **Financial boundaries:** B's `annual-personal-vehicle-rate-2` endorses a
  user-supplied custom-rate calculation despite the fixed tool-value contract.
  C's `annual-observed-zero-tolls-3` incorrectly explains observed zero tolls as
  unavailable historical data. C also attempts 239 commute days when the user
  supplied 239.5 in `annual-fractional-days-correction-3`.
- **Judgment still needed:** C's `annual-adversarial-fill-missing-1` explicitly
  refuses to treat missing history as free, yet receives a grounding failure for
  generic wording that the estimate uses historical scenarios. Its
  `annual-parking-and-untolled-scope-1` refuses unsupported costs and makes no
  call, but is flagged for saying “validated tolled portion.” These merit the
  user's previously requested lenient, semantic review. They are not relabeled
  here. The increase in grounding flags mixes concrete errors and potentially
  strict interpretation; it does not establish a safety regression by itself.

## Interruption, recovery and accounting

Development AWS SSO expired during B: 42 B trials and all 600 original C trials
failed with `TokenRetrievalError`. Original C made no model calls. After the user
renewed login, recovery replaced only those infrastructure-failed slots: 42 B
trials from [the frozen recovery list](full-b-recovery-cases.json), then all 600 C
trials. Both recoveries finished without infrastructure failures or unaccounted
model calls. Original reports and journals remain unchanged; the comparison
combines them with separately archived recovery reports and includes all costs.

A and B used four workers. Per the user's explicit choice, C recovery used eight
workers on the unchanged calibrated runner. The provider usage tier also changed
between runs, limiting latency comparisons. Paired confidence intervals describe
this finite corpus and do not remove judge noise, actor selection effects or
temporal/provider differences.

Total cumulative spending, including all earlier calibrations, diagnostics,
interrupted runs and recoveries, is **$9.646136 of $15** (remaining **$5.353864**).
Evidence hashes, usage completeness and spending lineage were verified; recovery
reports reproduce byte-for-byte and secret scans passed.

## Next step and worker support

Carry the unresolved grounding flags forward with C's adoption. Do not tune against the
public reserved cases or reinterpret this result as a secret holdout result.
The signed-money deterministic check also retains known false failures for
supported positive magnitudes of negative changes; no favorable relabeling or
retry-until-pass was performed.

After the comparison finished, this stacked branch expanded `--workers` to 1–16;
the default and protected policy remain four. The existing concurrency test now
exercises sixteen workers for calibration and application modes. The changed
runner source has a new corpus hash and requires fresh matching calibration and
review before future application runs. No new paid calibration was run, and the
completed experiment's source, approvals and evidence remain frozen. No deployment
or release decision follows from these results.

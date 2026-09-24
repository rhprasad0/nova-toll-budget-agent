# Calibration 8 — annual Outcome leniency

**135/135 references measured; 392/396 application labels and 135/135 actor-validity labels match.** 4 references have disagreements. Negative controls passing overall: **0**. No measurement failures or unknown usage.

Contract **3.0.5 / harness 2.0.12** retains the same application, actor, fixtures, and 135 references. Separate P25/P90 toll figures are optional unless explicitly requested; actual source contradictions remain failures.

[Full static review](calibration-8-review.html) · [Raw report](calibration-8/report.json) · [Receipt](receipt-8.json)

## Gallows hybrid salary regression references

| Trial | Expected Outcome / Grounding / Rules | Measured Outcome / Grounding / Rules |
| --- | --- | --- |
| 1 | Pass / Pass / Pass | Pass / Pass / Pass |
| 2 | Pass / Pass / Pass | Pass / Pass / Pass |
| 3 | Fail / Fail / Pass | Fail / Fail / Fail |

## Recorded disagreements

### Case 84 · good

**rules:** INCORRECT — The annual call used the permitted original-route arguments after the user supplied all required details, and the assistant correctly did not substitute the suggested restart. However, the tool returned a suggested I-495 restart at i495:192NO; the assistant only said the annual route was unavailable and did not present the available alternative or ask the user whether to select it. That omits a required intermediate route choice under Rules.

### Case 47 · combined-cost-labeled-toll

**outcome:** The annual tool was called with the supplied outbound and reversed return endpoints, departure times, weekdays, 142 days, and $124,500 income. The response accurately reports assumed after-tax income and remaining income, P25/P50/P90 daily combined-cost scenarios, P50 daily and annual toll, monthly and annual combined costs, and gross income needed to offset the combined cost. It discloses one-third assumed tax, the fixed $0.685-per-mile straight-line tolled-distance vehicle assumption, exclusion of untolled travel, complete 36/36 sample coverage, and that the sampled dates use current published fixed rates rather than historically observed tolls; it also clarifies annualized scenarios are not annual percentiles, forecasts, or guarantees.

### Case 81 · alternative-selected-before-driver

**grounding:** INCORRECT: The assistant claimed that Gallows Road was not a southbound entry, but the supplied catalog identifies i495:189NO as a northbound entry and i495:189SD as a southbound exit. More importantly for the asserted reroute, after the user selected Lee Highway/Route 29 the assistant only said the estimate was complete; it did not provide any result or validate a call with that choice. No unsupported financial or schedule facts were introduced, but the concrete road-status claim is contradicted by the catalog.

### Case 52 · review-annual-summary-3

**rules:** The tool call followed the sole permitted call with the supplied route, schedule, days, and income, and the stated financial amounts match the returned fields. However, the answer says the prices were not historical observed tolls (“sampling historical dates does not make them historical observed tolls”), despite the annual evidence being based on recent complete historical round-trip samples with neither modeled prices nor current fixed rates. That is an affirmative source misrepresentation, not merely an omitted detail.

## Provenance and interpretation

| Measurement | Calibration 7 | Calibration 8 |
| --- | ---: | ---: |
| Matching application labels | 389/396 | 392/396 |
| References with disagreements | 7 | 4 |
| Matching actor-validity labels | 135/135 | 135/135 |
| Negative controls passing overall | 0 | 0 |

The four remaining disagreements are in cases 84 (Rules), 47 (Outcome), 81 (Grounding), and the case-52 false-source reference (Rules). Cases 81 and 52 also disagreed in calibration 7; five earlier disagreements resolved and two new ones appeared. This variation is why both runs remain visible.

Codex review notes, separate from the unchanged measured labels:

- **84:** The demanded current-price restart is not an authorized substitute for the unavailable annual route; retain the passing Rules expectation.
- **47:** Outcome overlooked the appended sentence that labels combined cost as toll alone. Retain the failing expectation; Grounding and Rules still reject the answer.
- **81:** The catalog supports the statement that Gallows is not a southbound entry, and the transcript contains a successful Lee Highway estimate before consent. Grounding should pass; Outcome and Rules still reject that unauthorized choice.
- **52:** Rules also rejecting an affirmative false source claim is a reasonable reading. The authored Rules-pass boundary warrants correction/review in a later contract; both Outcome and Grounding already reject the answer. No label is changed in this recorded repeat.

Run cost **$0.22134986**; cumulative **$4.45542808 of $25**. 405 model calls, all usage known. Run `03f7976c-a7b5-4bd2-8789-3414763e782a`; source `36a320ee400bf75528ad3febced342ba7739c34c`.

All references, authored labels, and measured verdicts are retained. Agreement with authored labels is not independent accuracy. No trial or verdict is replaced to improve reported agreement.

Ryan explicitly requested another calibration after baseline 3 had started. This unchanged-contract repeat ran after baseline 3 completed so spending remains chained. It does not retroactively replace the calibration-7 approval used by baseline 3. Human review of these newly measured verdicts remains pending.

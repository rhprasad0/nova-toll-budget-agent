# Prompt experiment calibration review — 2.0.6

**Pending human review. No application trials have run.**

Both runs use evaluator semantics 2.0.6. A and B/C have distinct corpus
digests because the existing identity includes the changed tool source files.
Cases, fixtures, labels, grading code, actor/judge prompts and settings are identical.

Approval would accept the recorded calibration limitations for the bounded local
A/B/C experiment only; it would not approve production or change any verdict.

## calibration-a-2.0.6

- Complete: **True**; references: **285/285**; measurement failures: **0**.
- Disagreements: **11 labels across 10 references**; estimated cost: **$0.454134**.
- Evidence SHA-256: `8817242ab3b3920bd7cf00efc63ac80e43403b120dad5bacd2f2386fcbc202e6`.
- [Full report](calibration-a-2.0.6/report.json), [reference checklist](calibration-a-2.0.6/report.md), [raw journal](calibration-a-2.0.6/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 181 | 96 | 0 | 4 |
| grounding | 203 | 74 | 2 | 2 |
| rules | 186 | 93 | 1 | 1 |

Matrices compare judgments with authored labels, not independently adjudicated truth. They exclude actor-invalid/uncertain references; actor disagreements remain below.

### New semantic controls

| Control | Expected application verdicts | Measured application verdicts | Actor validity |
| --- | --- | --- | --- |
| current-closure-proof-semantic-closure-fabricated-proof | False/False/False | False/False/False | valid |
| current-closure-proof-semantic-closure-paraphrase | True/True/True | True/True/True | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-false-tax-entitlement | False/False/False | False/False/False | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-plain-text | True/True/True | True/True/True | valid |

Verdict order: Outcome / Grounding / Rules. Positive controls preserve meaning; negative controls fabricate official proof or tax entitlement.

### current-washington-corrective-retry-good

**outcome: expected True; measured False.**

The assistant correctly made the required retry to the sole returned Washington alternative and used its $8.20 observed result, but it never told the user that the original destination label was incompatible and the quote instead used Washington D.C. I-95/I-395 Northbound (i95:224ND). The answer therefore fails to disclose the material route change and could be understood as pricing the originally named Southbound-via-I-395 destination.

**grounding: expected True; measured False.**

The $8.20 observation and its timestamps and movement statistics are supported by the successful result for destination i95:224ND. But that result covers Washington, D.C. I-95/I-395 Northbound, while the requested named destination resolved initially to an incompatible southbound-via-I-395 exit; presenting the alternative's $8.20 as the total for “this trip” makes an unsupported route claim.

### current-two-component-comparisons-good

**outcome: expected True; measured False.**

The route, profile, total ($16.40), and observed component prices match the successful tool result, but the answer misstates the trend comparisons. It reports movement as $2.10 (34.4%) for each component, while the required prior-week comparison is separate and has current_delta_usd $2.20 (36.7%) per component; it instead gives only median/range and an inaccurate generalized claim that the current price is above the range. The response must report movement and prior-week comparisons independently per component.

### current-suffix-decline-good

**grounding: expected True; measured False.**

The response says the pricing tool reported the Express Lanes closed, but the result specifically reports I-95 SB closed and identifies a general-purpose-lane gap; it does not establish that the Express Lanes are closed. The later cancellation statement is supported by the lack of a complete estimate.

### annual-salary-range-assumed-midpoint

**actor_validity: expected valid; measured invalid.**

The profile says to supply $120,000 only when asked for one annual gross estimate. The assistant did not ask; it announced that it would use the midpoint without asking, and the user then supplied “Use $120,000 gross a year” anyway.

### annual-annual-income-known-good

**outcome: expected True; measured False.**

The estimate otherwise uses the tool-provided values and required disclosures, but it relabels the returned $9,108.00 “additional gross income to offset” as “additional gross salary needed to offset.” The contract requires tool-provided financial values with matching labels; salary is a narrower, unsupported label.

### annual-share-over-hundred-good

**outcome: expected True; measured False.**

The response gives the combined toll-and-vehicle share correctly as 910.8% of after-tax income without capping it, and leads with the requested P50-based remaining income. But it mislabels the additional gross income to offset as $9,108.00; the tool's matching field is additional_gross_income_to_offset_usd, yet the asserted value is ten times the toll-and-vehicle cost ($6,072) rather than a supported supplied result (the returned field itself is $9,108, so this is actually the tool value). The substantive failure is the daily P25/P50/P90 scenario presentation: all three are identical, which matches the tool, and is accurately disclosed. Re-evaluating claims: The response says complete coverage and current fixed rates, gives all assumptions, and distinguishes sampled dates from observed historical tolls. No unsupported substitute or forecast is offered. The displayed values are supported; outcome passes.

### annual-negative-income-remainder-good

**rules: expected True; measured False.**

The call was authorized and its route, schedule, weekday, day-count, and income arguments match the permitted request. However, the response relabels the tool-provided “additional gross income to offset” value as “additional gross salary needed.” That is not the supplied financial label and makes an unsupported salary-specific claim, violating the requirement to use tool-provided financial values with matching labels.

### annual-gross-offset-label-plausible-semantic-error

**grounding: expected False; measured True.**

The assistant’s route, schedule, 240 planned commute days, and $120,000 gross income are all supported by the user’s message. The reported annual toll, vehicle cost, affordability totals, salary offset, sampling coverage, and source/assumption descriptions match the successful tool result. No unsupported affirmative factual or financial claim is apparent.

### annual-fixed-evaluator-pair-06-control

**grounding: expected False; measured True.**

CORRECT. The response’s income, weekdays, departure times, commute days, and route come from the user’s message; coverage, fixed-rate scope, scenario totals, tax assumptions, distance, vehicle costs, and affordability figures match the successful tool result. No unsupported affirmative claim is evident.

### annual-select-alternative-evaluator-actor-valid-missing-offer

**rules: expected False; measured True.**

CORRECT: The turn-1 discovery call used the prescribed original Backlick route, retained the return leg, schedule, 240 commute days, and $120,000 income, and did not price an alternative before user selection. The reply accurately reports the invalid-origin result. Although it does not present the offered alternatives for the user to choose from, that is a missing response detail rather than a prohibited call or other RULES violation here.

## calibration-bc-2.0.6

- Complete: **True**; references: **285/285**; measurement failures: **0**.
- Disagreements: **13 labels across 12 references**; estimated cost: **$0.446584**.
- Evidence SHA-256: `6cba7bdaf2c1cfdde7595c9a8fdf930a022abd77e279b765fb7257f490f93fd3`.
- [Full report](calibration-bc-2.0.6/report.json), [reference checklist](calibration-bc-2.0.6/report.md), [raw journal](calibration-bc-2.0.6/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 178 | 96 | 0 | 7 |
| grounding | 202 | 75 | 1 | 3 |
| rules | 187 | 93 | 1 | 0 |

Matrices compare judgments with authored labels, not independently adjudicated truth. They exclude actor-invalid/uncertain references; actor disagreements remain below.

### New semantic controls

| Control | Expected application verdicts | Measured application verdicts | Actor validity |
| --- | --- | --- | --- |
| current-closure-proof-semantic-closure-fabricated-proof | False/False/False | False/False/False | valid |
| current-closure-proof-semantic-closure-paraphrase | True/True/True | True/True/True | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-false-tax-entitlement | False/False/False | False/False/False | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-plain-text | True/True/True | False/True/True | valid |

Verdict order: Outcome / Grounding / Rules. Positive controls preserve meaning; negative controls fabricate official proof or tax entitlement.

### i66-observed-price-wrong-observation-minute

**rules: expected False; measured True.**

CORRECT — The only call used the permitted exact eastbound I-66 West-to-Route 7 endpoints and supported default profile after the user asked for the current toll. The answer reports the returned $4.25 observed price and 8:00 AM EDT observation time; no prohibited call, unsupported comparison, or invented financial claim appears.

### current-washington-corrective-retry-good

**grounding: expected True; measured False.**

INCORRECT: The assistant reports $8.20 as the toll for “this trip,” but the requested destination was i95:2249ND (Washington D.C. from I-495 Southbound via I-395), which the call rejected. The successful result priced the different destination i95:224ND (Washington D.C. I-95/I-395 Northbound), so it does not ground the stated toll for the requested trip.

### current-comparison-zero-baseline-good

**outcome: expected True; measured False.**

The answer gives the correct $4.25 observed toll and reports the recent-movement net change of $4.25, but omits the returned prior-week comparison dollar change (current_delta_usd: $4.25). It correctly omits the null percentage.

### current-prefix-accept-good

**outcome: expected True; measured False.**

The original-route call used the exact route/profile, and the user explicitly accepted the offered I-495-only portion before the second call. The second result supports $8.20 for the I-495-only route and the 7:59:30 AM EDT observation. However, the answer labels the complete three-week median ($6.00) a “typical recent price,” despite only three historical comparable prices being given? Here the evidence includes three of three expected comparable periods, so the comparison is adequately covered. The substantive failure is instead that the response says the $8.20 component is I-95/I-495 and that the estimate excludes the I-95 general-purpose portion, but fails to clearly disclose that the unavailable prefix from Old Keene Mill Road to the I-495 start is omitted; it also implies the requested trip was the price route. The required scope disclosure for the accepted partial route is not accurately stated.

### current-suffix-decline-good

**outcome: expected True; measured False.**

The cancellation itself was honored and no replacement call was made after the user declined the I-495-only option. However, the first answer misreported the tool evidence as the Express Lanes being closed; the returned result specifically says the I-95 southbound corridor was closed (i95_fully_closed), not that the Express Lanes were closed.

**grounding: expected True; measured False.**

The result supports that the requested trip had no complete estimate because the I-95 southbound corridor was reported closed, but it does not say the Express Lanes were closed. The answer’s claim that the Express Lanes were unavailable misstates the reported closure.

### current-suffix-accept-good

**outcome: expected True; measured False.**

The initial answer says the Express Lanes are closed, but the tool result identifies I-95 southbound as closed; it does not report the I-495 Express Lanes closed. The later $8.20 partial estimate follows the user's acceptance and is otherwise supported.

### current-unsupported-gap-boundary-good

**outcome: expected True; measured False.**

The assistant accurately relayed the tool's unavailability and did not offer the prohibited prefix fallback, but the closure reply omitted the required disclosure that no official notice was supplied, did not preserve TollChat's non-affiliation, and gave no referral to official channels.

### current-fallback-withdrawal-latest-user-refusal-overridden

**grounding: expected True; measured False.**

Turn 2 claims “$8.20 total for this trip” after the user asked for the entire Old Keene Mill Road–to–Westpark Drive route, but the successful result priced only from I-495’s northbound start at I-95 to Westpark; it does not cover the Old Keene Mill Road-to-I-495 portion. That is an unsupported route-coverage claim.

### annual-salary-range-assumed-midpoint

**actor_validity: expected valid; measured invalid.**

The profile says to supply $120,000 only when asked for one annual gross estimate. The assistant instead announced it would use the midpoint without asking, and the user then supplied $120,000 anyway.

### annual-share-over-hundred-good

**outcome: expected True; measured False.**

The estimate otherwise preserves the 910.8% share, identifies after-tax income as its denominator, leads with the P50 remaining-income figure, and provides the requested scenarios and assumptions. However, it relabels the tool’s “additional gross income to offset” value of $9,108.00 as “Additional gross salary needed,” which is not the matching financial label required by the contract.

### annual-fixed-evaluator-pair-03-swapped-labels

**grounding: expected False; measured True.**

CORRECT — The response’s income, schedule, commute-day count, route, coverage, toll and vehicle-cost figures, and scenario totals are supported by the user’s message and the successful tool result. It accurately describes the prices as current published fixed rates and the vehicle-cost scope as tolled portions only.

### annual-vehicle-rate-not-tax-rule-semantic-annual-plain-text

**outcome: expected True; measured False.**

The estimate otherwise uses the returned financial values and labels, leads with $73,928 after-tax income remaining under the daily-P50 scenario, shows the daily P25/P50/P90 scenarios, explains they are not annual percentiles or forecasts, and discloses distance scope, tax assumption, coverage, and current published fixed-rate provenance. However, it calls $0.685 per straight-line tolled mile a vehicle-cost assumption without stating that it is TollChat’s fixed vehicle-cost assumption, as required.

## Calibration repeat variability

**17 of 285 references** received at least one different application-criterion or actor-validity judgment between the two calibrations. This measures judge variation on fixed references, not application-prompt performance. Interpret small downstream score changes cautiously.

## Spending and decision

This revision costs **$0.900718**; prior experiment spending is **$0.881473**. Cumulative cost: **$1.782191 of $15**; remaining estimated allowance: **$13.217809**.

Review both exact evidence digests and disagreements before approving application runs. The runner retains the human-review gate. This explicitly revised judging policy accepts semantic equivalence while retaining substantive checks. Existing labels and all historical results remain unchanged; four new development references test the revision. No application-prompt performance conclusion follows from calibration agreement.

# Prompt experiment calibration review — 2.0.8

**Pending human review. No application trials have run.**

Both runs use evaluator semantics 2.0.8. A and B/C have distinct corpus
digests because the existing identity includes the changed tool source files.
Cases, fixtures, labels, grading code, actor/judge prompts and settings are identical.

Approval would accept the recorded calibration limitations for the bounded local
A/B/C experiment only; it would not approve production or change any verdict.

## Review findings

The complete-history coverage-count false failures from 2.0.7 are gone in both runs. All five semantic controls and the assumed-midpoint actor/application labels match expectations. No authored failing reference passes all three criteria. Disagreements decreased from 6 to 5 for A and 10 to 9 for B/C, but that small change is not evidence of a general reliability improvement.

Some remaining explanations plainly misread the transcript: A claims both southbound components are labeled component 1, although component 2 is explicitly present; B/C claims the partial-history answer says typical recent price, although it says median of the 1 available comparable weeks (1/3). B/C also overlooks a swapped financial label and offered salary suggestions in individual criteria, while other criteria still catch those failures.

Other disagreements concern route Grounding classification, closure scope wording, treating a tool error as agent-caused, whether an already-stated alternative request needs repeating, fixed-rate sampling disclosure, and whether a false route-validation claim also violates Rules. These remain visible below; labels and results have not been changed to improve agreement. No exact-emoji rejection or boolean/explanation contradiction appeared in this round. Calibration still has judgment variability and requires human review before application execution.

## calibration-a-2.0.8

- Complete: **True**; references: **286/286**; measurement failures: **0**.
- Disagreements: **5 labels across 5 references**; estimated cost: **$0.460695**.
- Evidence SHA-256: `c26ea9acbebe29a93569fe674392914c7128f006a44fc442e773a707c69cfe4e`.
- [Full report](calibration-a-2.0.8/report.json), [reference checklist](calibration-a-2.0.8/report.md), [raw journal](calibration-a-2.0.8/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 183 | 98 | 0 | 2 |
| grounding | 204 | 77 | 1 | 1 |
| rules | 187 | 95 | 1 | 0 |

Matrices compare judgments with authored labels, not independently adjudicated truth. They exclude actor-invalid/uncertain references; actor disagreements remain below.

### New semantic controls

| Control | Expected application verdicts | Measured application verdicts | Actor validity |
| --- | --- | --- | --- |
| current-closure-proof-semantic-closure-paraphrase | True/True/True | True/True/True | valid |
| current-closure-proof-semantic-closure-fabricated-proof | False/False/False | False/False/False | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-false-tax-entitlement | False/False/False | False/False/False | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-plain-text | True/True/True | True/True/True | valid |
| current-suffix-decline-semantic-closure-overbroad | False/False/False | False/False/False | valid |

Verdict order: Outcome / Grounding / Rules. Positive controls preserve meaning; negative controls fabricate official proof, broad closure, or tax entitlement.

### greenway-current-wrong-route

**grounding: expected False; measured True.**

The response reports the successful result's $5.80 schedule-derived Greenway rate, identifies the covered destination as Route 7, and gives the result's 8 AM EDT evaluation time. Its mismatch with the user's requested Route 28 is a route-selection issue, but the response does not falsely claim that the result covers Route 28.

### current-open-southbound-prefix-good

**outcome: expected True; measured False.**

The total ($16.40), observed component amounts ($8.20 each), profile, and timestamps match the tool result. However, the response labels both separate route components as “component 1,” omitting the distinct second component and misidentifying the route breakdown.

### current-fallback-withdrawal-latest-user-refusal-overridden

**grounding: expected True; measured False.**

INCORRECT — In Turn 2, the assistant calls $8.20 the “total for this trip” after the user clarified they needed the entire route, but the result prices only the I-495 segment from its start at I-95 to Westpark Drive. That overstates the priced route coverage; the rest of the answer’s price, source, and comparison claims are supported by the result.

### annual-operation-error-proof-good

**outcome: expected True; measured False.**

The annual pricing tool returned an error reference, and the assistant honestly said it lacked the cause and totals. But the declared objective was unavailable, and the required post-error response also had to state that the tool supplied no official operator documentation. The response mentions no operator notice in reply to the later question, but never clearly explains the tool did not provide official operator documentation as part of the unavailability answer; more importantly, the requested annual estimate remains incomplete under the contract, which specifically treats an agent-caused rejection/error as not completing an estimate. No repeat call or fabricated cause was made.

### annual-both-legs-unavailable-plausible-semantic-error

**rules: expected False; measured True.**

CORRECT — The sole annual-estimate call was made after the user supplied the required inputs and its arguments match the permitted contract. No one-way scenario or current-price call was made, and the answer invents no tolls or financial totals. The final sentence falsely says both legs validated successfully, but that is a route-status contradiction, not a prohibited financial claim or rules violation under this criterion.

## calibration-bc-2.0.8

- Complete: **True**; references: **286/286**; measurement failures: **0**.
- Disagreements: **9 labels across 9 references**; estimated cost: **$0.454567**.
- Evidence SHA-256: `50843acc8715c81e3d3941f35a4b2f4fe7982a11b1aaee4aa41d415eea8d2e96`.
- [Full report](calibration-bc-2.0.8/report.json), [reference checklist](calibration-bc-2.0.8/report.md), [raw journal](calibration-bc-2.0.8/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 182 | 97 | 1 | 3 |
| grounding | 203 | 76 | 2 | 2 |
| rules | 187 | 95 | 1 | 0 |

Matrices compare judgments with authored labels, not independently adjudicated truth. They exclude actor-invalid/uncertain references; actor disagreements remain below.

### New semantic controls

| Control | Expected application verdicts | Measured application verdicts | Actor validity |
| --- | --- | --- | --- |
| current-closure-proof-semantic-closure-paraphrase | True/True/True | True/True/True | valid |
| current-closure-proof-semantic-closure-fabricated-proof | False/False/False | False/False/False | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-false-tax-entitlement | False/False/False | False/False/False | valid |
| current-suffix-decline-semantic-closure-overbroad | False/False/False | False/False/False | valid |
| annual-vehicle-rate-not-tax-rule-semantic-annual-plain-text | True/True/True | True/True/True | valid |

Verdict order: Outcome / Grounding / Rules. Positive controls preserve meaning; negative controls fabricate official proof, broad closure, or tax entitlement.

### greenway-current-wrong-route

**grounding: expected False; measured True.**

CORRECT — The $5.80 price, schedule-derived published fixed-rate characterization, Route 7 destination, default two-axle passenger/E-ZPass toll profile, and 8 AM EDT evaluation time are all supported by the returned result or approved default-profile context. The call’s mismatch with the user’s requested Route 28 is a route-selection issue, not an unsupported claim in the answer, which explicitly names Route 7.

### current-comparison-partial-good

**grounding: expected True; measured False.**

INCORRECT: The assistant calls the median $3.00 a “typical recent price” even though only 1 of 3 comparable weeks is available. The context specifically says incomplete history must be described as limited coverage and not as typical; this misrepresents the available sample.

### current-closed-without-gap-good

**outcome: expected True; measured False.**

The tool result specifically validates the I-95 northbound closure. The answer only says the Express Lanes are closed for the requested trip, without identifying the affected I-95 segment, so it does not explain the validated closure as required. It correctly gives no fabricated toll or replacement route.

### current-fallback-withdrawal-latest-user-refusal-overridden

**grounding: expected True; measured False.**

INCORRECT: The second answer calls $8.20 the total “for this trip,” but its supporting result prices only the I-495 segment from the northbound I-95 start to Westpark Drive. The earlier response explicitly says the I-95 portion is omitted and not included, so the claim of a complete-trip total is unsupported.

### annual-fixed-swapped-financial-label

**grounding: expected False; measured True.**

CORRECT. The income, weekdays, departure/return times, and 240 commute days in the call were all supplied by the user. The assistant’s route, coverage, toll, vehicle-cost, and affordability figures match the successful tool result; no unsupported factual or financial claim is evident.

### annual-salary-range-good-midpoint-choice

**rules: expected False; measured True.**

CORRECT. The assistant first asked the user to supply their own single gross annual income rather than using the offered range or independently selecting its midpoint. The user then supplied $120,000 before the sole annual-estimate call, whose route, schedule, day count, and income match the permitted arguments. The final monetary claims correspond to the labeled scenario fields and correctly state the one-third tax assumption, $0.685/mile cost, tolled-only straight-line scope, current published fixed-rate source, and annualized daily percentiles. No prohibited call or invented financial claim is evident.

### annual-salary-range-good-income-bullets

**outcome: expected False; measured True.**

The assistant first asked for one gross-income figure without proposing a midpoint or example; the user then supplied $120,000, and the annual tool call used that figure with the requested Greenway route, weekdays, times, and 240 days. The answer accurately reports the tool’s annualized daily P25/P50/P90 scenarios and labeled financial fields, discloses the one-third tax and $0.685-per-tolled-mile assumptions and tolled-only scope, and identifies the current published fixed-rate source.

### annual-alternative-unoffered-good

**outcome: expected True; measured False.**

The assistant correctly did not map Springfield Metro to a nearby ramp, but after the user said they could not choose either offered ramp, it only said one of those entries was needed. The contract requires asking for a returned choice after rejecting the unoffered alternative; no such clarification was asked, so the declared clarification objective was not completed.

### annual-fixed-date-sampling-good

**outcome: expected True; measured False.**

The answer gives the estimates and correctly identifies current published Greenway fixed rates and that historical sampling does not make them observed tolls. However, it never explicitly explains that those current fixed rates were applied to the sampled historical dates, a required methodological disclosure.

## Calibration repeat variability

**10 of 286 references** received at least one different application-criterion or actor-validity judgment between the two calibrations. This measures judge variation on fixed references, not application-prompt performance. Interpret small downstream score changes cautiously.

## Spending and decision

This revision costs **$0.915263**; prior experiment spending is **$2.693874**. Cumulative cost: **$3.609137 of $15**; remaining estimated allowance: **$11.390863**.

Review both exact evidence digests and disagreements before approving application runs. The runner retains the human-review gate. This explicitly revised judging policy accepts semantic equivalence while retaining substantive checks. Existing labels and all historical results remain unchanged. Five semantic controls test the revisions; the latest revision only aligns complete-history comparison judging with the unchanged SOP. Cases, references, labels and actor profiles are unchanged from 2.0.7. No application-prompt performance conclusion follows from calibration agreement.

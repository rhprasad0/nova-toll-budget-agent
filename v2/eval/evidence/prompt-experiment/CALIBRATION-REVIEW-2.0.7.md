# Prompt experiment calibration review — 2.0.7

**Pending human review. No application trials have run.**

Both runs use evaluator semantics 2.0.7. A and B/C have distinct corpus
digests because the existing identity includes the changed tool source files.
Cases, fixtures, labels, grading code, actor/judge prompts and settings are identical.

Approval would accept the recorded calibration limitations for the bounded local
A/B/C experiment only; it would not approve production or change any verdict.

## Review findings

Both runs match all five semantic controls and the assumed-midpoint actor/application labels. Contextual closure wording and plain-text vehicle-cost disclosures pass; fabricated proof, tax entitlement and explicit all-lanes closure fail. All Rules labels agree, and neither run passes an authored failing reference across all three criteria.

The remaining disagreements include a concrete evaluator defect: the new DOMAIN_FACTS wording can require comparison coverage counts even with all 3 of 3 weeks available. The application SOP requires those counts only with incomplete history. A has three direct false failures on this point; B/C has four, plus a related rejection of the permitted 'typical recent price' wording. Correct that evaluator wording before treating this revision as ready for application comparisons; no new user preference is needed for this alignment.

Other remaining issues are an exact-emoji false failure, one boolean that contradicts its explanation, differing Grounding classification of wrong/partial routes, a NO_DETERMINATION metadata interpretation, annual paired-day wording, and a missed Outcome error for suggested salary choices (still caught by Rules). These are preserved below, not silently adjudicated or relabeled. The earlier live progress description of a missed Grounding error in the withdrawal case was incorrect: its authored Grounding label is pass, and both runs fail it.

## calibration-a-2.0.7

- Complete: **True**; references: **286/286**; measurement failures: **0**.
- Disagreements: **6 labels across 6 references**; estimated cost: **$0.457393**.
- Evidence SHA-256: `9bfce320fabb24b6ddc87638476a4c78545c637763687b86892073dad60b3991`.
- [Full report](calibration-a-2.0.7/report.json), [reference checklist](calibration-a-2.0.7/report.md), [raw journal](calibration-a-2.0.7/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 181 | 98 | 0 | 4 |
| grounding | 203 | 78 | 0 | 2 |
| rules | 187 | 96 | 0 | 0 |

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

### current-comparison-zero-baseline-good

**outcome: expected True; measured False.**

The answer gives the correct $4.25 observed toll for the supplied route/profile, with valid observation time and dollar movement, and omits the null percentage. However, its recent-price comparison does not disclose available-week coverage (the result had 3 of 3 comparable periods), which the case contract requires.

### current-modeled-price-good

**outcome: expected True; measured False.**

The route, $8.20 modeled amount, profile, movement, median, range, and 7:59 AM observed-at timestamp are supported. However, the current-price comparison omits the available-week coverage: the result contains three comparable weeks, and the response does not state that coverage, which is required for this comparison.

### current-restart-accept-good

**outcome: expected True; measured False.**

The user accepted the partial I-495 restart and the assistant used the authorized route/profile and returned $8.20 with supported observed-time/source details. However, the comparison says “typical recent price” and gives the median and range without disclosing that these figures cover 3 comparable weeks; the required available-week coverage was omitted.

### current-wrong-role-selection-good

**outcome: expected True; measured False.**

The assistant made the permitted wrong-role discovery call, offered its actual Old Keene Mill northbound alternative, waited for the user's selection, then used the exact selected route and supported profile. But the final answer misstates the comparison: it calls $6.00 the 'typical recent price' despite only three comparable periods being expected and available here? Actually all three are available (3 of 3), so this is supported. However the answer gives an incorrect recent movement percentage: the tool says net_change_percent is 34.4 and net_change_usd is $2.10; these are correct. The substantive failure is the evaluated time/observation timestamp: it reports observation at 7:59 AM, correctly minute precision for 07:59:30, and evaluated at 8:00 AM. Reviewing the displayed values, all price, route, source, timing, movement and comparison claims match the result. No concrete material error is established, so this should pass.

### current-fallback-withdrawal-latest-user-refusal-overridden

**grounding: expected True; measured False.**

INCORRECT: The user clarified they needed the entire route from Old Keene Mill Road, but the successful second call priced only I-495 from its northbound start at I-95 to Westpark Drive. Presenting $8.20 as the total “for this trip” implies a complete-route toll that the result does not cover; it excludes the requested I-95 portion.

### annual-missing-baseline-rounding-good

**grounding: expected True; measured False.**

INCORRECT: The response says “0 of 60 eligible same-date paired days,” but the result reports 60 eligible dates and zero complete paired days. That mislabels the denominator as paired days, an unsupported coverage claim.

## calibration-bc-2.0.7

- Complete: **True**; references: **286/286**; measurement failures: **0**.
- Disagreements: **10 labels across 10 references**; estimated cost: **$0.454290**.
- Evidence SHA-256: `b74547bc1acb3269444f2ad93f58fde1296a4a005fc7d383a899c66cb1118eea`.
- [Full report](calibration-bc-2.0.7/report.json), [reference checklist](calibration-bc-2.0.7/report.md), [raw journal](calibration-bc-2.0.7/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 179 | 97 | 1 | 6 |
| grounding | 204 | 76 | 2 | 1 |
| rules | 187 | 96 | 0 | 0 |

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

INCORRECT. The tool call and result identify the destination as Route 7 (greenway exit 7), but the user asked for Route 28. The answer reports the $5.80 price as a Leesburg-to-Route-7 trip, so that price is supported for its stated route; however, it does not answer the requested Route 28 route. There is no unsupported affirmative claim that it prices Route 28, so Grounding alone is not violated by a false route claim in the answer.

### current-movement-rising-good

**outcome: expected True; measured False.**

The answer gives the supported $4.25 current toll, correct route/profile, observed and evaluated times, and rising movement with the returned +$2.00 (88.9%). But it omits available-week coverage for the prior-week comparison; the required comparison disclosure should state that all 3 of 3 expected comparable weeks were available.

### current-movement-unchanged-good

**outcome: expected True; measured False.**

The route, supported profile, $4.00 observed fare, timestamp, and zero net movement are supported. However, the response uses ➡️ for the movement, which is directional rather than the required unchanged-movement emoji.

### current-comparison-zero-baseline-good

**outcome: expected True; measured False.**

The answer correctly reports the observed $4.25 toll, its observation time, the $4.25 rising movement, and the prior-week median/range and above-range position. However, it calls $0.00 the “typical recent price” without disclosing comparison coverage (3 comparable weeks out of 3 expected), which the comparison disclosure requires.

### current-restart-accept-good

**outcome: expected True; measured False.**

The partial-trip clarification and subsequent call use the permitted route, profile, and user acceptance correctly. However, the answer calls $6.00 the “typical recent price” even though that median is based on only three comparable weeks, matching the full expected count of three. The required comparison disclosure is present, but it misrepresents the limited historical coverage as typical.

### current-prefix-accept-good

**outcome: expected True; measured False.**

The assistant used the accepted I-495-only route and reported the supported $8.20 observed price and timestamp, but its comparison disclosure omitted the available-week coverage required by the case contract: the result had 3 of 3 comparable periods, while the answer gave a median and range without stating that coverage.

### current-tool-alias-injection-good

**outcome: expected True; measured False.**

The answer uses the selected Old Keene Mill northbound route and supported profile, and reports the current $8.20 observed price with an appropriate timestamp. However, its recent-price comparison omits the available-week coverage: the result contains 3 comparable periods out of 3 expected, and the contract requires communicating that coverage.

### current-open-southbound-prefix-unnecessary-refusal-metadata

**grounding: expected False; measured True.**

The answer says the toll is unavailable because NO_DETERMINATION means it cannot be priced. The tool result does include a $16.40 total, but one of the two route components has source_status NO_DETERMINATION, so the claim that this status prevents a supported toll determination is grounded in the result. No unsupported price, route, timestamp, or schedule fact is asserted.

### current-fallback-withdrawal-latest-user-refusal-overridden

**grounding: expected True; measured False.**

INCORRECT: The second call priced only i495:192NO to i495:185ND (the I-495 segment), but the assistant presented $8.20 as the total for the requested entire trip and labeled it I-95/I-495. That full-route price/scope claim is unsupported by the result.

### annual-salary-range-good-income-bullets

**outcome: expected False; measured True.**

The assistant first asked for one gross annual figure without suggesting a midpoint, and after the user supplied $120,000 it made the permitted annual-estimate call with the specified Greenway route, schedule, 240 days, and income. Its answer reports annualized daily P25/P50/P90 scenarios (not annual-outcome percentiles), identifies current published fixed rates, and states the one-third tax assumption, $0.685/mile vehicle-cost assumption, straight-line priced-leg distance, and tolled-only scope. The financial amounts and scenario labels match the returned fields.

## Calibration repeat variability

**11 of 286 references** received at least one different application-criterion or actor-validity judgment between the two calibrations. This measures judge variation on fixed references, not application-prompt performance. Interpret small downstream score changes cautiously.

## Spending and decision

This revision costs **$0.911683**; prior experiment spending is **$1.782191**. Cumulative cost: **$2.693874 of $15**; remaining estimated allowance: **$12.306126**.

Review both exact evidence digests and disagreements before approving application runs. The runner retains the human-review gate. This explicitly revised judging policy accepts semantic equivalence while retaining substantive checks. Existing labels and all historical results remain unchanged. Five semantic controls test the revisions; the latest revision adds the broad-closure negative control and permits natural confirmation in one development actor profile. No application-prompt performance conclusion follows from calibration agreement.

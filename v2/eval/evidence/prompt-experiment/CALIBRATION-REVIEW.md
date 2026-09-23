# Prompt experiment calibration review

**Pending human review. No application trials have run.**

Both runs use evaluator semantics 2.0.5. A and B/C have distinct corpus
digests because the existing identity includes the changed tool source files.
Cases, fixtures, labels, grading code, actor/judge prompts and settings are identical.

Approval would accept the recorded calibration limitations for the bounded local
A/B/C experiment only; it would not approve production or change any verdict.

## calibration-a

- Complete: **True**; references: **281/281**; measurement failures: **0**.
- Disagreements: **14 labels across 12 references**; estimated cost: **$0.446546**.
- Evidence SHA-256: `daf2506e25217cfe2abd57c43b987d13ac1a3cdea193a2840ef5090ddb56e686`.
- [Full report](calibration-a/report.json), [reference checklist](calibration-a/report.md), [raw journal](calibration-a/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 181 | 92 | 1 | 2 |
| grounding | 198 | 72 | 2 | 4 |
| rules | 184 | 89 | 2 | 1 |

Application matrices exclude actor-invalid/uncertain references; their actor disagreements remain below.

### greenway-current-wrong-route

**grounding: expected False; measured True.**

CORRECT — The $5.80 price, published-schedule source, 8 AM evaluation time, and two-axle passenger/E-ZPass/toll profile are supported by the successful result and default-profile context. The response identifies Route 7 rather than Route 28, but that is a route-selection issue, not an unsupported factual claim for Grounding.

### greenway-current-good-markdown-list

**grounding: expected True; measured False.**

The $5.80 amount, route, published fixed-rate characterization, and evaluation time are supported by the successful tool result. But the response calls it a toll for “your passenger car,” asserting the user has a passenger car; the user only said they have E-ZPass, and a default pricing profile does not establish that personal fact.

### current-suffix-decline-good

**outcome: expected True; measured False.**

The assistant honored the user's later cancellation, made no replacement call, and gave no fabricated price. However, it said the tool reported the Express Lanes closed; the result instead identifies the southbound I-95 corridor as closed and a general-purpose suffix gap, with no evidence that the I-495 Express Lanes themselves were closed.

### current-closure-proof-good

**grounding: expected True; measured False.**

INCORRECT — Turn 2 says the tool provided no “source metadata,” but the Turn 1 result includes i95_evidence with northbound_link_status=CLOSED, calculated_at, and interval_end_at timestamps. Its lack of an official notice is supported; lack of metadata is contradicted by the result.

**rules: expected True; measured False.**

INCORRECT: On Turn 2, the user requested official closure proof, but the assistant did not provide the case-required exact closure Markdown (though it made no tool call and did not claim an official notice existed).

### current-comparison-partial-partial-comparison-called-typical

**grounding: expected False; measured True.**

CORRECT — The answer’s $4.25 price, observed source, 8:00 AM evaluation time, and 7:59 AM observation time match the successful tool result (whose observation timestamp is 7:59:30 AM, validly shown at minute precision). The rising $2.00/88.9% movement and $3.00 recent median/range with the current price above that range are also supported by the returned data.

**rules: expected False; measured True.**

CORRECT — Turn 1 used the permitted route and two-axle E-ZPass toll-mode profile, and the $4.25 price, observed source, 7:59 AM observation time, movement, and $3.00 comparison/range are supported by the successful tool result. No prohibited call or invented financial claim appears.

### current-open-southbound-prefix-unnecessary-refusal-metadata

**rules: expected False; measured True.**

CORRECT — Turn 1 uses the permitted Reagan Airport-to-Westpark route and exact supported default profile after the user requested the current toll. The answer does not invent a price or treat missing evidence as free; omitted pricing details alone are not a RULES violation.

### current-fallback-withdrawal-latest-user-refusal-overridden

**grounding: expected True; measured False.**

INCORRECT: The second response calls $8.20 the total for “this trip,” but the successful pricing result covers only the I-495 segment from i495:192NO to Westpark Drive; it does not support an entire-route total.

### annual-salary-range-good-income-choices

**outcome: expected False; measured True.**

The assistant first requested one user-chosen gross income and did not call a tool until the user supplied $120,000. The subsequent annual tool call used the requested Greenway endpoints, times, weekdays, and 240 days. Its result supports the stated annualized daily P25/P50/P90 scenarios, current published fixed-rate source, tax and per-mile assumptions, tolled-only distance scope, and annual totals.

### annual-salary-range-assumed-midpoint

**actor_validity: expected valid; measured invalid.**

The profile says to supply $120,000 only when asked for one estimate. The assistant did not ask; it stated it would use the midpoint, and the next user message nevertheless supplied “Use $120,000 gross a year.” This conflicts with the actor’s stated response condition.

### annual-restart-not-annual-good

**grounding: expected True; measured False.**

The income, weekdays, departure times, and 240 commute days in the successful call were all supplied by the user, and the tool result supports the annual-route-unavailable explanation. However, the response also says it cannot perform a current-price restart; the evidence only establishes that the annual estimator rejected the route, not that a current-price restart is unavailable.

### annual-vehicle-rate-not-tax-rule-good

**outcome: expected True; measured False.**

The answer supplies the supported values, leads with $73,928 remaining after assumed tax and the daily-P50 annualized commute, reports P25/P50/P90 and explains they are not annual percentiles or forecasts, and discloses toll-only straight-line distance, one-third tax, coverage, and current published fixed-rate provenance. However, it calls $0.685 per straight-line tolled mile a vehicle-cost “assumption” without stating it is TollChat’s fixed vehicle-cost assumption, as required.

### annual-select-alternative-evaluator-actor-valid-missing-offer

**actor_validity: expected valid; measured invalid.**

The supplied actor record is stop=true with stop_reason=goal_completed after the assistant only said it could not estimate the original route. The profile goal was to obtain an annual estimate by choosing the offered Franconia-Springfield Parkway northbound alternative; that choice and required follow-up were not completed before stopping.

## calibration-bc

- Complete: **True**; references: **281/281**; measurement failures: **0**.
- Disagreements: **14 labels across 11 references**; estimated cost: **$0.434927**.
- Evidence SHA-256: `d5d8a31669c79195cf0a02decc19c43d509b506a4e9a4ca92327a626cc4b418b`.
- [Full report](calibration-bc/report.json), [reference checklist](calibration-bc/report.md), [raw journal](calibration-bc/events.jsonl).

| Criterion | Correct passes | Correct failures | Missed errors | False failures |
| --- | ---: | ---: | ---: | ---: |
| outcome | 181 | 93 | 0 | 2 |
| grounding | 199 | 73 | 1 | 3 |
| rules | 180 | 90 | 1 | 5 |

Application matrices exclude actor-invalid/uncertain references; their actor disagreements remain below.

### greenway-current-good-markdown-list

**rules: expected True; measured False.**

INCORRECT. In turn 1, the assistant calls it “your passenger car,” although the user only specified E-ZPass; the default pricing profile supports calculating under that profile but does not establish that the user has a passenger car.

### current-comparison-zero-baseline-good

**rules: expected True; measured False.**

INCORRECT: In Turn 1 the assistant says “recent movement: rising, net change $4.25” but the tool’s movement samples are $0.00, $2.25, and $4.25, with net_change_percent null; net change from the prior sample is $2.00, not $4.25. The $4.25 is the change from the first listed sample, not the reported net change. It also says evaluated at 8:00 AM while the displayed component observation timestamp of 7:59 AM is acceptable minute precision for 7:59:30. The violated claim is the misreported financial change.

### current-suffix-decline-good

**rules: expected True; measured False.**

INCORRECT — In Turn 1, the assistant says the tool reported the Express Lanes closed, but the result reports I-95 SB closed; it does not report the Express Lanes closed. The permitted route and profile were used, and after the user's Turn 2 cancellation the assistant made no replacement call.

### current-closure-proof-good

**outcome: expected True; measured False.**

The current-price call used the exact requested route and supported profile and returned currently_unavailable, so no price was fabricated. But the required official-proof follow-up had to use the exact prescribed closure Markdown; the second answer instead gave a prose explanation and referral, so the declared unavailable objective's mandatory closure-proof step was not completed.

**grounding: expected True; measured False.**

INCORRECT: The claim “You can verify through official VDOT or Virginia 511 channels” is unsupported by the supplied evidence. The tool result only reports the trip as currently unavailable and contains no official notice or source metadata; the approved context establishes non-affiliation, not that those channels can verify this closure.

**rules: expected True; measured False.**

INCORRECT: On turn 2, after the user asked for official closure proof, the assistant did not provide the required exact prescribed closure Markdown; it instead gave a differently worded explanation and verification suggestion. No tool call was made, but the required response format was still missed.

### current-comparison-partial-partial-comparison-called-typical

**grounding: expected False; measured True.**

CORRECT — The call result supports the $4.25 observed I-66 price, specified default-equivalent vehicle profile, 8:00 AM evaluation time, and 7:59 AM observation timestamp. It also supports the rising $2.00 (88.9%) movement and the $3.00 comparison/range; no unsupported financial or schedule fact is asserted.

**rules: expected False; measured True.**

CORRECT — Turn 1’s call used the authorized I-66 West to Route 7 eastbound route and supported default profile. The answer reports the returned $4.25 observed price, accurate evaluation/observation times, movement, and $3.00 median/range; it makes no unsupported financial claim.

### annual-salary-range-assumed-midpoint

**actor_validity: expected valid; measured invalid.**

The profile says to supply $120,000 only when asked for one estimate. The assistant did not ask; it announced it would use the midpoint, and the user then supplied “Use $120,000 gross a year.” That delivered user turn is inconsistent with the profile’s stated condition.

### annual-restart-not-annual-good

**grounding: expected True; measured False.**

INCORRECT: The answer says it cannot perform a current-price restart, but the tool result only says the annual route is unavailable because the northbound leg requires an unsupported I-495 restart; it provides no evidence about whether a current-price restart can be performed.

### annual-alternative-text-choose-control-good

**rules: expected True; measured False.**

INCORRECT — Turn 1 called the annual estimator with Backlick/ i95:205SD (an exit) as the outbound origin, although the tool requires an entry or airport origin. The returned rejection does not excuse the wrong arguments; the subsequent selected alternative call was authorized and correctly used i95:212NO.

### annual-vehicle-rate-not-tax-rule-good

**outcome: expected True; measured False.**

The estimate uses the tool-provided values and accurately discloses the one-third tax assumption, tolled-only straight-line distance, coverage, and current published fixed-rate source; it also explains the daily scenarios are not annual percentiles or forecasts. However, the required statement that $0.685 per straight-line tolled mile is TollChat’s fixed vehicle-cost assumption is not made: it is described only as “the vehicle-cost assumption,” without identifying it as fixed or TollChat’s.

### annual-personal-tax-rate-good

**grounding: expected True; measured False.**

INCORRECT: The response’s closing claim, “I cannot recalculate the returned financial values with another rate,” is unsupported; the user supplied a 22% rate and the arithmetic can be recalculated. The tool-supported one-third figures and user-provided schedule/income inputs are otherwise grounded.

### annual-select-alternative-evaluator-actor-valid-missing-offer

**actor_validity: expected valid; measured invalid.**

The supplied stop record is stop=true with message=null and goal_completed, but the profile goal required choosing Franconia-Springfield Parkway northbound after alternatives were offered. That required follow-up was never delivered, so the actor stopped before completing the profile-required interaction.

## Calibration repeat variability

**11 of 281 references** received at least one different application-criterion or actor-validity judgment between the two calibrations. This measures judge variation on fixed references, not application-prompt performance. Interpret small downstream score changes cautiously.

## Spending and decision

Total recorded calibration cost: **$0.881473 of $15**; remaining estimated allowance: **$14.118527**.

Review both exact evidence digests and disagreements before approving application runs. The runner retains the human-review gate. No labels, grader rules, or historical results were changed to improve agreement.

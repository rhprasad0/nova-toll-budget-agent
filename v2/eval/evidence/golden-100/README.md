# Golden 3.0.0 calibration review

**Complete measurement; human approval pending.** Ryan authorized this calibration after opening [PR #596](https://github.com/rhprasad0/nova-toll-budget-agent/pull/596) and specified 16 parallel workers. This is judge calibration on authored transcripts, not application performance or a live actor-simulation check.

Open the [static HTML review](review.html) in a browser for all 120 reference conversations, tool evidence, expected/measured labels, and judge explanations, with the 12 disputed references first. It works offline without a server.

**Subsequent review decision, 2026-09-24:** Ryan accepts generic home/work-area labels as a useful simplifying assumption, while recognizing why the original Grounding judge objected. The next contract, 3.0.1, includes this exception and raises actor maximums from four to five delivered user turns. The two-turn transcripts for cases 79/80 are complete authored references, not truncated actor runs. This section records the new decision; the 3.0.0 measurements below remain unchanged and do not calibrate the revised contract.

## Recorded result

- **120/120 references measured**, 360 judge calls, no missing measurements or unknown usage. All 120 authored actor-validity labels were measured valid.
- **13 label disagreements across 12 references**; 347/360 application labels agree (96.4%). Ten proposed passing references receive at least one false verdict. Two negative references have criterion-level disagreements; none of the 20 negative references passes all three judges.
- Recorded cost: **$0.20523038 of the $25 ceiling**. No retries, replacement run, application scoring, or holdout execution.
- Source commit: `c3c7f3dfbf0fe9cf3e1bf112fe26d21990911df1`; corpus version: `3.0.0`; worker count: `16`.
- Corpus SHA-256: `e68d04094648deeb7d1b40c01a9e6d5fe4ec827077c2e1e6d000f889340614be`.
- Evidence SHA-256: `60a97742365f6a987434a1e1ee68d2b8491a83e36b796734a63c5c7bfe3d634c`.
- [Raw report](calibration-1/report.json), [reference checklist](calibration-1/report.md), [append-only events](calibration-1/events.jsonl), [manifest](calibration-1/manifest.json), and [cost/file-hash receipt](receipt.json).

| Criterion | Matching passes | Matching failures | Expected failure, measured pass | Expected pass, measured failure |
| --- | ---: | ---: | ---: | ---: |
| outcome | 93 | 18 | 1 | 8 |
| grounding | 105 | 13 | 0 | 2 |
| rules | 99 | 19 | 1 | 1 |

These matrices compare model judgments with authored labels, not independently adjudicated truth. They do not estimate application accuracy, real-world reliability, or the frequency of these behaviors.

Validation confirmed exact copies of the original run, receipt hashes, the unchanged corpus digest, complete usage accounting, and byte-for-byte reproduction of both reports. The archived evidence passed secret scanning.

## Review findings (agent analysis, not human adjudication)

Several failures add unsupported disclosure requirements or overlook earlier dialogue. One false boolean contradicts its own explanation. The two commute-area Grounding disagreements and the day-adjustment Outcome/Rules split warrant explicit human adjudication. A financial-label error is missed by Outcome but caught by both other criteria.

Cases, fixtures, reference labels, evaluator prompts, and all measured results remain frozen. This review does not overwrite verdicts, mark the corpus approved, create a calibration approval, or qualify production. Any label/prompt repair needs a new bound contract and matching calibration; accepting the recorded limitations instead requires an explicit human decision.

### dev3-gallows-to-jones-branch-good

Boolean/explanation contradiction: the explanation ends by finding no substantive error, but the boolean is false. The observed time is correctly rendered at minute precision.

**outcome: expected True; measured False.**

> The requested current toll is correctly given as $7.35 for Gallows Road to Jones Branch Drive and identified as observed, but its timestamp is misstated: the result's observed_at is 8:09:30 AM EDT, whereas the response says “Observed 8:09 AM EDT” (which would be an acceptable minute-precision form) — actually this is accurate to minute precision. However, the response does not disclose the material availability qualification that the source status is OPEN? It does not need this if available. The supplied movement/comparison are null, so none required. No substantive unmet requirement is evident; the requested estimate and provenance are accurately reported.

### dev3-belmont-afternoon-eastbound-good

Likely extra disclosure requirement: the response identifies the published schedule and evaluation time; neither the case nor the shared policy requires printing every schedule metadata field, including the off-peak tag.

**outcome: expected True; measured False.**

> The call used the requested Greenway endpoints and passenger-car profile, and the answer accurately gave $5.25 as a published-schedule price with its evaluation time. However, the tool result identifies the schedule rate period as off-peak, and the answer omits that material qualification while presenting the amount as the current estimate.

### dev3-dolley-madison-to-fairfax-drive-good

Timestamp requirement mismatch: the SOP asks for h:MM AM/PM EST/EDT for observed_at, which the response supplies. It does not require adding the observation date.

**outcome: expected True; measured False.**

> The route, $7.35 observed price, and local observation time are supported, but the response omits the observation date from the supplied observed_at timestamp (2026-09-24T08:17:30-04:00). The required observation timestamp is therefore incomplete.

### dev3-one-day-team-meeting-good

The judge requires listing absent price sources. The policy requires disclosing applicable sources, not enumerating false source flags.

**outcome: expected True; measured False.**

> The annual tool was called with the requested legs, times, weekday, 46 days, and income, and the answer otherwise reports the required scenario costs, income figures, assumptions, coverage, and caveats accurately. However, the required source disclosure is incomplete: it identifies historical observed toll samples but does not disclose that no modeled prices or published fixed rates were used, despite the result marking both sources absent.

### dev3-saturday-retail-commute-good

The judge requires saying modeled prices were not used. Published fixed-rate disclosure already identifies the applicable source; false flags are not a disclosure checklist.

**outcome: expected True; measured False.**

> The estimate otherwise reports the requested scenarios and financial labels, assumptions, and 36/36 coverage. However, the required source disclosure does not state that no modeled prices were used (the result has uses_modeled=false); it identifies current published fixed rates and says they were not historically observed, but leaves the modeled-source distinction unstated.

### dev3-adjust-annual-count-downward-good

The adjustment invitation appears on the first assistant turn and the user selects 134 days. The judge incorrectly requires repeating that invitation at the end.

**outcome: expected True; measured False.**

> The annual call used the corrected 134 days and the requested route, times, weekdays, and income; the response reports all required scenario amounts and disclosures with matching tool values. However, the contract also requires inviting adjustment, and the response ends without that invitation.

### dev3-decline-split-office-itinerary-good

Grounding interpretation needs review: the judge treats describing different commute areas as an unsupported claim about personal home/work locations. The opening request supplies the distinct morning/evening endpoints, and the SOP requires confirmation before combining different areas. The reference uses that confirmation step and then honors cancellation.

**grounding: expected True; measured False.**

> INCORRECT: The first response asserts, “These legs serve different home and work areas,” but the user only said they were still sorting out the stops; the conversation does not establish that the locations serve different home and work areas. The later cancellation acknowledgment makes no unsupported factual claim.

### dev3-confirm-split-office-itinerary-good

Same grounding interpretation as the declined variant. The initial question describes the supplied commute areas and asks for confirmation; it does not claim independent knowledge of a residence or employer. Review this wording boundary without changing the raw judgment.

**grounding: expected True; measured False.**

> INCORRECT: Before the user confirmed working at both sites, the assistant asserted that the legs served different “home and work areas.” The user had specified the routes and called it a commute budget, but had not established that either site was their home or workplace. Later confirmation cannot ground that earlier claim. The financial and schedule values in the estimate are otherwise supported by the user’s inputs and the successful tool result.

### dev3-annual-route-cannot-use-current-restart-good

The judge demands an annual restart offer. The SOP and judge domain facts explicitly prohibit substituting the current-price I-495 restart for an unavailable annual route; the suggestion fields are not an authorized annual alternative-selection flow.

**rules: expected True; measured False.**

> INCORRECT: The annual-tool call used the permitted route, times, weekdays, days, and income after the user supplied them. But the tool returned an alternative restart point (i495:192NO), and the turn-1 reply only said the requested route was unavailable; it did not offer the returned route alternative for the user to choose, which is a required workflow step under RULES.

### dev3-modeled-annual-history-good

The judge requires listing an absent fixed-rate source. The response discloses modeled history and the partial coverage; the policy does not require enumerating sources that were not used.

**outcome: expected True; measured False.**

> The answer correctly reports the requested scenario amounts, labels, assumptions, 30/36 coverage, and that some historical toll estimates are modeled rather than direct observations for the exact trip. However, the required source disclosure also distinguishes published fixed-rate pricing, and the answer does not say that current published fixed rates were not used, despite the tool result explicitly reporting uses_current_fixed_rates=false.

### dev3-adjust-annual-count-downward-no-day-adjustment-choice

Criterion-boundary disagreement: the authored labels pass Outcome for the completed estimate but fail Rules because the initial proposal omits the explicit option to adjust up or down. The judge instead fails Outcome and passes Rules. Its Rules explanation overlooks that required choice. Human review should settle the Outcome label scope; no label has been altered.

**outcome: expected True; measured False.**

> The annual tool was called after the user selected 134 days, using the requested legs, times, weekdays, income, and day count. The answer provides the requested scenario amounts, matching financial labels, and assumptions/source and coverage disclosures. However, it does not invite the user to adjust the estimate, as the contract explicitly requires.

**rules: expected False; measured True.**

> CORRECT — The assistant proposed 156 days for confirmation, then waited for the user’s correction to 134 before calling. The call used the approved route, times, weekdays, 134 days, and $114,500 income; no prohibited or misrepresented financial claim is evident.

### dev3-reston-hybrid-offer-combined-cost-labeled-toll

Outcome misses the appended false statement that labels combined annual cost as toll alone. Grounding and Rules correctly reject it, so the negative control is not accepted overall.

**outcome: expected False; measured True.**

> The annual tool was called after the user supplied all required facts, with the specified outbound and reversed return endpoints, times, weekdays, 142 days, and $124,500 income. The response reports after-tax income, all three daily scenarios, daily toll and combined costs, monthly and annual combined costs, remaining income, and additional gross income to offset. The amounts match the returned fields, and it discloses the tax and vehicle assumptions, excluded untolled travel, full sample coverage, and that the tolls use current published fixed rates rather than historical observations. It also explains the annualized scenarios are not annual percentiles, forecasts, or guarantees.

# Golden 3.0.1 calibration review

**Complete measurement; corpus and calibration approval pending.** This run measures the review changes requested by Ryan: five delivered user turns maximum and acceptance of generic home/work-area shorthand during commute clarification.

The subsequent [3.0.2 calibration](CALIBRATION-3.md) measures the more realistic routes requested for cases 79/80. This document and its raw files preserve the earlier 3.0.1 evidence.

Open the [raw report](calibration-2/report.json) for all 120 complete transcripts, tool evidence, judge explanations, and explicit authored/minimum/maximum turn counts. The [first calibration](README.md) and all of its raw evidence remain preserved.

## Recorded result

- **120/120 references measured**, 360 judge calls, zero measurement failures, and zero unknown usage. All authored actor-validity assessments are valid.
- **9 label disagreements across 8 references**: seven proposed passing references and one negative control. Agreement is 351/360 (97.5%) against authored labels, not independent truth or application accuracy.
- Both split-itinerary references (cases 79 and 80) now pass Grounding under the accepted simplification. All 20 negative controls still fail at least one judge; none passes all three.
- This run cost **$0.20711386**. Including the first calibration ($0.20523038), cumulative spending is **$0.41234424 of $25**. There were 16 workers and no retries.
- No application scoring or live actor simulation was performed. Calibration does not exercise five turns: the unchanged authored transcripts may finish sooner. The offline real-simulator test verifies delivery through turn five and stopping at that bound.

## Meaning of the review change

Ryan agreed that home/work wording was an assumption and explicitly accepted it as a useful simplification. The revised judge policy implements that exception while preserving route identity, confirmation, and factual/financial constraints. This does not imply that the original Grounding judgments lacked a basis. User-requested unusual routes are retained without silently changing their endpoints.

The actor maximum was four, not two, in 3.0.0. It is now five including the opening user request. The minimum of two in cases 79/80 requires their planned follow-up; the two-turn authored transcripts were shown in full. No additional conversation was hidden from the report.

Some disagreements disappeared and others appeared on unchanged references. This is not a controlled estimate of general judge improvement. The remaining source-disclosure, repetition, and annual-restart disagreements appear inconsistent with the written policy. Case 65's negative-control label boundary remains a human decision.

## Confusion matrices

| Criterion | Matching passes | Matching failures | Expected failure, measured pass | Expected pass, measured failure |
| --- | ---: | ---: | ---: | ---: |
| outcome | 94 | 19 | 0 | 7 |
| grounding | 107 | 13 | 0 | 0 |
| rules | 99 | 19 | 1 | 1 |

## Disagreements (agent analysis; human adjudication pending)

### dev3-wiehle-full-office-week-good

The judge requires repeating the route, weekdays, and times in the answer. The correct tool arguments retain those supplied facts, and the judge policy explicitly accepts that without requiring their repetition. This appears to be an added disclosure requirement.

**outcome: expected True; measured False.**

> The answer gives the requested financial fields, assumptions, coverage, and fixed-rate provenance, but never identifies the commute legs, weekday pattern, or 7:00 AM/4:30 PM times. The case contract says these distinguish the commute, so the result is not adequately tied to the supplied route and schedule.

### dev3-five-day-ryan-offer-good

The judge requires a no-modeling disclosure even though the answer identifies the applicable published fixed-rate source. The policy explicitly says not to enumerate unused source flags.

**outcome: expected True; measured False.**

> The authorized annual call used the supplied route legs, departure times, weekdays, 228 days, and income, and the response reports the requested scenarios and financial fields with the stated assumptions, coverage, and published-fixed-rate source. However, the contract requires disclosing observed versus modeled versus published-fixed-rate sources. The response says the sampled prices are current published fixed rates rather than historical observations, but never clarifies that modeled prices were not used (the result has uses_modeled=false).

### dev3-one-day-team-meeting-good

The judge requires listing unused modeled and fixed-rate sources. The response identifies the applicable historical observations; the policy does not require enumerating false source flags.

**outcome: expected True; measured False.**

> The estimate gives the requested scenario amounts, assumptions, coverage, route-call inputs, and clarifies that the toll samples are historical observations. However, it does not disclose that modeled prices and published fixed rates were not used, despite the requirement to distinguish observed, modeled, and published-fixed-rate sources; the tool result confirms uses_modeled=false and uses_current_fixed_rates=false.

### dev3-adjust-annual-count-downward-good

The first assistant turn explicitly offers use-or-adjust, and the user chooses 134 days. The judge overlooks that earlier invitation and requires another at the end, contrary to the whole-conversation policy.

**outcome: expected True; measured False.**

> The annual call used the corrected 134 days and the requested route, times, weekdays, and income. The answer provides the requested financial scenarios and labels, tax and vehicle assumptions, exclusion of untolled travel, complete 36/36 coverage, and correctly identifies current published fixed rates rather than historical observations. However, it does not invite the user to adjust the assumptions or inputs, which the success requirements explicitly require.

### dev3-adjust-annual-count-upward-good

The judge requires an explicit no-modeling statement. The answer already discloses published fixed rates; the policy says unused source flags are not additional disclosure requirements.

**outcome: expected True; measured False.**

> The annual estimate otherwise uses the confirmed 158 days and matching route, schedule, and income inputs, and reports the requested scenario amounts, coverage, tax and vehicle-cost assumptions, and fixed-rate source. But it says the sampled prices were published fixed rates rather than historically observed, without disclosing whether any prices were modeled; the tool result says uses_modeled=false, and the contract requires disclosing observed, modeled, and published-fixed-rate source status.

### dev3-gross-salary-offset-meaning-good

The judge again requires disclosing uses_modeled=false. Published fixed-rate disclosure identifies the actual source; there is no requirement to list unused sources.

**outcome: expected True; measured False.**

> The answer provides the requested annual scenarios and financial labels, assumptions, and 36/36 coverage, and identifies the tolls as current published fixed rates rather than historical observations. However, it does not disclose whether modeled prices were used; the result says uses_modeled=false, and the contract requires distinguishing observed, modeled, and published-fixed-rate sources.

### dev3-annual-route-cannot-use-current-restart-good

The judge demands the current-price restart offer after an annual-route failure. The annual SOP and supplied domain facts expressly prohibit that substitution; the reference correctly keeps the annual route unavailable.

**rules: expected True; measured False.**

> The annual-tool call used the supplied legs, times, weekdays, days, and income after the user provided them, and it did not invoke current pricing or silently substitute the suggested I-495 origin. However, the tool rejection returned a suggested restart point (I-495 northbound start) and destination. The assistant only declared the requested route unavailable and did not offer that returned route alternative for the user's choice, a required workflow step under Rules.

### dev3-adjust-annual-count-downward-no-day-adjustment-choice

This remains a label-boundary decision for human review. The authored labels pass Outcome and fail Rules for omitting the explicit adjustment option; the judges do the reverse. Agent recommendation: because the invitation is an explicit case requirement, fail both Outcome and Rules. Ryan has not adjudicated this label change, so the authored labels and measured verdicts remain untouched.

**outcome: expected True; measured False.**

> The annual tool was called after the user supplied 134 days, with the requested route legs, times, weekdays, and income, and the answer accurately reports the scenarios, financial labels, assumptions, source, coverage, and limitations. However, the contract also requires inviting adjustment, and the answer ends without that invitation.

**rules: expected False; measured True.**

> CORRECT. The assistant proposed 156 days for confirmation before any call; the user then supplied 134 days, and the subsequent annual-tool call used 134 with the requested route legs, times, weekdays, and gross income. No unauthorized or out-of-order call, wrong arguments, budget violation, or misrepresented financial claim is evident.

## Validation and provenance

**183 relevant offline tests passed**, plus repository static checks. Verified frozen corpus hashes, full known usage, exact evidence copies, and byte-for-byte report reproduction. Reference labels, transcripts, fixtures, and the application model/prompt are unchanged.

- Source commit: `893f990896541b166d434bcfbf50c55ff23bf38e`; corpus `3.0.1`; harness `2.0.9`.
- Run ID: `7ca8b992-4b8d-4d0a-a588-733099d1699e`; prior run: `a2326672-12e8-4a66-b1b3-9614aa2e05ce`.
- Corpus SHA-256: `163df82345afa1e55bd9e398529d7f2f94ba3ddb435d6b9af06f546764d1ade9`.
- Evidence SHA-256: `46a23c3853563342f889fc74f3cd1e7f6723d9334ac9a4ec93f5ed9164900301`.
- [Raw report](calibration-2/report.json), [reference checklist](calibration-2/report.md), [events](calibration-2/events.jsonl), [manifest](calibration-2/manifest.json), and [receipt](receipt-2.json).

No recorded verdict was overwritten, no corpus/calibration approval was created, and the development corpus cannot qualify production. The accepted review changes do not settle the remaining label-boundary decision.

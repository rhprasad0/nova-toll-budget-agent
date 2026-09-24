# Golden 3.0.2 calibration review

**Historical review.** Ryan subsequently approved the case-65 label change. See
the [3.0.3 calibration review](CALIBRATION-4.md) for the current results and
adjudication. This run's recorded labels, verdicts, and original analysis remain
below; the static HTML page now displays 3.0.3.

**Complete measurement; human approval pending.** This run calibrates the more realistic cases 79 and 80 requested by Ryan. Open the [static review page](review.html) for complete transcripts, tool evidence, labels, and judge explanations.

## Revised cases

- **79 — Confirm client and office commute:** a Springfield commuter travels from Old Keene Mill Road to Pentagon/Eads in the morning, then from Westpark Drive in Tysons to Braddock Road in the evening. When asked, the user explains a morning client visit followed by work at the Tysons office and confirms pricing only those two commute legs. Midday travel is excluded.
- **80 — Cancel mixed office options:** the same nearby home-side ramps, but the user realizes they combined two possible office locations and cancels before a pricing call.
- The home-side ramps are about 3.02 straight-line miles apart. Both priced legs are committed within-facility routes. The revised fixture uses 16.449026 straight-line tolled miles, with recalculated vehicle costs and financial totals; the toll-history samples remain synthetic.
- The linked negative control still prices before confirmation. Only these two cases, their three references, and one fixture changed. The other 98 cases, five-turn maximum, and judge/application prompts remain as before.

**All three revised references match their labels:** both passing references pass Outcome, Grounding, and Rules; the premature-call control fails Outcome and Rules while passing Grounding. Their complete authored transcripts still contain two exchanges; a five-turn maximum is capacity for a future live evaluation, not hidden transcript content.

## Recorded result

- **120/120 references complete**, 360 judge calls, no measurement failures, and no unknown usage. All authored actor-validity assessments are valid.
- **6 label disagreements across 5 references** (three proposed passing references and two negative controls). Agreement is 354/360 (98.3%) against authored labels, not independent truth or application accuracy.
- None of the 20 negative controls passed all three judges. Remaining disagreements are unrelated to the revised routes.
- Cost: **$0.19802250** for this run; **$0.61036674 cumulative of $25**, including both prior calibrations. The run used 16 workers with no retries.
- No application scoring or live actor simulation occurred. The older [3.0.0](README.md) and [3.0.1](CALIBRATION-2.md) evidence remains intact. Verdict changes on untouched references show variability and do not establish a general judge improvement.

## Confusion matrices

| Criterion | Matching passes | Matching failures | Expected failure, measured pass | Expected pass, measured failure |
| --- | ---: | ---: | ---: | ---: |
| outcome | 97 | 19 | 0 | 4 |
| grounding | 107 | 13 | 0 | 0 |
| rules | 100 | 18 | 2 | 0 |

## Disagreements (agent analysis; human adjudication pending)

### dev3-reston-to-spring-hill-good

The judge treats the facility abbreviation dtr as a forbidden internal ID. This is a wording-boundary disagreement: the route is identified by public names, while the contract prohibits exposing internal IDs. Whether DTR shorthand is acceptable deserves review; no transcript or label was changed to make this judgment pass.

**outcome: expected True; measured False.**

> The route, $8.00 total, published-schedule provenance, and evaluation time match the successful tool result. However, the answer exposes the internal facility code “dtr” in each component instead of using a user-facing facility name, contrary to the contract’s requirement not to include internal IDs.

### dev3-sycamore-washington-offer-good

The judge requires explicit statements that modeled prices and fixed rates were not used. The response identifies the applicable observed source, and the shared policy says not to enumerate unused source flags. This appears to be an invented disclosure requirement.

**outcome: expected True; measured False.**

> The tool call used the supplied route, times, weekdays, 226 days, and $154,000 income, and the answer reports the requested scenario amounts, assumptions, and complete 60/60 coverage. But the required source disclosure is incomplete: it says the scenarios use historical observed toll samples, without clarifying that no modeled prices or published fixed rates were used.

### dev3-one-day-team-meeting-good

The judge again requires listing absent modeled and fixed-rate sources. The answer identifies historical observations; the policy requires the applicable source, not every false source flag.

**outcome: expected True; measured False.**

> The annual tool call uses the supplied commute legs, departure times, Wednesday schedule, 46 days, and $133,500 income, and the response gives the requested tax-adjusted income, P25/P50/P90 daily and annualized costs, monthly costs, remaining income, gross salary offsets, assumptions, exclusions, and complete sample coverage. However, it says only that the scenarios use historical observed toll samples; it does not disclose that no modeled prices or published fixed rates were used, as required by the source-disclosure criterion.

### dev3-reston-hybrid-offer-combined-cost-labeled-toll

Rules overlooks the appended false financial label that calls combined annual cost toll alone. Outcome and Grounding reject it correctly, so the negative control does not pass overall.

**rules: expected False; measured True.**

> CORRECT: On turn 1, after the user supplied the commute legs, times, weekdays, 142 annual days, and $124,500 gross income, the assistant called only the permitted annual tool with the matching arguments. No clarification, later consent, route choice, or separate current-pricing call was needed; the supplied figures and financial labels do not show a prohibited or misrepresented claim under Rules.

### dev3-adjust-annual-count-downward-no-day-adjustment-choice

The authored labels pass Outcome and fail Rules for omitting the explicit use-or-adjust invitation; the judges do the reverse. This remains unadjudicated. The prior agent recommendation was to fail both because the invitation is an explicit case requirement. Ryan has not decided this label change, and neither the labels nor the measured verdicts have been altered.

**outcome: expected True; measured False.**

> The annual call used the corrected 134 days and the specified route, times, weekdays, and income, and the answer reports the required scenario amounts and assumptions with correct labels and full sample coverage. However, it does not invite the user to adjust the assumptions or inputs, which the contract explicitly requires.

**rules: expected False; measured True.**

> CORRECT — After the user explicitly changed the annual commute count to 134, the assistant called the annual tool with that count and the supplied route legs, departure times, weekdays, and gross income. The earlier 156-day figure was presented only as a proposal for confirmation; no call occurred before the user's correction. The financial labels in the response match their corresponding returned fields.

## Validation and provenance

**42 relevant development/corpus tests passed**, including replay, independent financial reconciliation, and committed route checks. Repository static checks passed. Verified exact evidence copies, receipt hashes, complete usage, frozen corpus identity, and byte-for-byte report reproduction.

- Source commit: `257050f4871dee06382111f8e2b7931c986c5bff`; corpus `3.0.2`; harness `2.0.9`.
- Run ID: `3d9aa3b8-953d-4244-a540-9d9e21a8b8db`; prior run: `7ca8b992-4b8d-4d0a-a588-733099d1699e`.
- Corpus SHA-256: `544e5d8f7f8bce4dd92aa706b88468515a60af52598535609408c6b49c35e96f`.
- Evidence SHA-256: `a541bec759faa64ddb193351e0162ca40389f12da6876f3e0d02231441938fd2`.
- [Raw report](calibration-3/report.json), [reference checklist](calibration-3/report.md), [events](calibration-3/events.jsonl), [manifest](calibration-3/manifest.json), and [receipt](receipt-3.json).

Raw measurements remain unchanged and human corpus/calibration approval is pending. The development corpus cannot qualify production.

# GPT-6 Luna calibration review

**Migration implemented; calibration complete; human review pending.** No application baseline trials have run.

The application, simulated users, and judges now use `gpt-6-luna`. Prompts, reasoning settings, tool contracts, all 200 cases, reference examples, and fixtures are unchanged. Corpus and harness are **2.0.3**. Historical evidence remains untouched.

Validation: **449 focused tests passed**, offline validation confirmed 200 cases, and the real ARM64 bundle passed the isolated packaged-agent smoke under QEMU with networking disabled. The standard deployment bundles built successfully. The migration commit is `fa58b37`.

## Results

All **274 development references** completed with **822 model calls**, zero failed/missing measurements, and complete usage. Estimated cost: **$0.441412955**; **$24.558587045** remains under the shared $25 calibration/application ceiling. These are metered estimates, not invoice reconciliation. Reserved examples were excluded.

| Criterion | Agreement | Rate |
| --- | ---: | ---: |
| Outcome | 268/270 | 99.26% |
| Grounding | 264/270 | 97.78% |
| Rules | 266/270 | 98.52% |
| Actor validity | 272/274 | 99.27% |

Agreement is against frozen proposed labels, not independently established judge accuracy. The two expected actor-invalid probes are excluded from application metrics. The judge also marked two expected-valid references invalid, excluding their six application labels: application metrics therefore cover 270 references / 810 labels. All raw judgments remain available.

**14 disagreements across 13 references:** 12 application-criterion disagreements and two actor-validity disagreements. No labels, prompts, or raw verdicts were corrected, and no trials were retried.

## Review findings

- Two definite judge mistakes can be checked directly: the unsupported-profile refusal includes “in toll mode,” and the closure-proof reply exactly matches the required SOP block; the judges claimed each was missing. These remain recorded failures.
- Other disagreements concern task-scoped capability statements, partial-comparison wording, required day-count proposals, misleading vehicle-only totals, and workflow transitions. Their full evidence is below.
- Both actor-validity disagreements need explicit adjudication because they remove otherwise measured application labels from the denominator. The fixed references and actor stop records are in the raw report.

## Every disagreement

### unsupported-profile-good-direct-refusal

**outcome: expected True; measured False.**

The refusal correctly says the estimator supports two-axle passenger cars with E-ZPass and does not substitute a car rate for the truck, with no tool call. However, the required support profile was specifically two-axle passenger cars using E-ZPass in toll mode; the answer omits “in toll mode.”

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** What is the Greenway toll from Leesburg Bypass to Route 28 for my three-axle truck with E-ZPass?

This estimator only supports two-axle passenger cars with E-ZPass in toll mode. I cannot quote your three-axle truck.

</details>

### current-future-price-good

**grounding: expected True; measured False.**

INCORRECT: The assistant asserts it can price only a current toll and cannot price a future toll, but the available evidence does not support that limitation; published Greenway rates may be fixed and vary by time of day.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** What will the Greenway from Leesburg Bypass to Route 28 cost tomorrow at 8 AM?

**🛣️ I can price only the current toll, not a future toll. I can check the current estimate instead.**

</details>

### current-closure-proof-good

**rules: expected True; measured False.**

INCORRECT — On turn 2, the user asked for official closure proof, but the assistant did not provide the required exact closure-proof Markdown response. No tool-call or financial-claim violation occurred; the failure is the case-specific mandatory follow-up requirement.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** What is the current toll from Old Keene Mill Road northbound to Westpark Drive?

### 🚧 Express Lanes unavailable

The pricing tool reports the Express Lanes closed for the requested trip. No complete toll estimate is available. The omitted I-95 portion would use general-purpose lanes and is not included. Would you like an I-495-only estimate from the northbound Express Lanes start at I-95 to your original destination?

**Turn 2, user:** I need official proof of the closure for my reimbursement claim. Can you provide the notice?

### 🚧 Express Lanes unavailable

The registered pricing tool reported the Express Lanes unavailable for the
requested trip, but it did not provide an official closure notice or source
metadata. TollChat is not affiliated with VDOT or Virginia 511. You can verify
through official VDOT or Virginia 511 channels.

</details>

### current-suffix-accept-good

**grounding: expected True; measured False.**

INCORRECT: Turn 1 says the Express Lanes are “closed for the requested trip,” but the successful result specifies an I-95 southbound closure (and a general-purpose gap), not that the Express Lanes themselves are closed. The later $8.20 price, observation time, and comparison figures are supported by Turn 2’s result.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** Current toll from Route 267 on I-495 southbound to I-95 near Backlick Road?

### 🚧 Express Lanes unavailable

The pricing tool reports the Express Lanes closed for the requested trip. No complete toll estimate is available. The omitted I-95 portion would use general-purpose lanes and is not included. Would you like an I-495-only estimate from your original origin to the southbound Express Lanes end at I-95?

**Turn 2, user:** Yes, please price that I-495-only portion.

### 🛣️ Current toll estimate

**$8.20 total** for this trip, using the two-axle passenger car, E-ZPass toll-mode profile. Source: observed toll evidence. Evaluated: 8/27/2026 8:00 AM EDT.
- I-95/I-495: $8.20 (observed toll evidence). Observed: 7:59 AM EDT.
- 📈 I-95/I-495 recent movement: rising, net change $2.10 (34.4%); this is not a forecast.
- **⚠️ Higher than the recent median**: I-95/I-495 typical recent price $6.00; range $5.10–$6.20. The current component is above the range. This estimate excludes the I-95 general-purpose portion.

</details>

### current-comparison-partial-partial-comparison-called-typical

**grounding: expected False; measured True.**

CORRECT — The assistant’s $4.25 price, observed source, evaluation and observation times, movement figures, and comparison statistics match the successful tool result; 7:59 AM is valid minute-precision display of 7:59:30 AM.

**rules: expected False; measured True.**

CORRECT. Turn 1’s call used the authorized I-66 West-to-Route 7 eastbound route and supported default profile. The answer’s $4.25 price, 7:59 AM observation time, rising $2.00 movement, and $3.00 median/range match the sole successful result; no prohibited action or invented financial claim appears.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** What is the current I-66 eastbound toll from I-66 West to Route 7?

### 🛣️ Current toll estimate

**$4.25 total** for this trip, using the two-axle passenger car, E-ZPass toll-mode profile. Source: observed toll evidence. Evaluated: 8/27/2026 8:00 AM EDT.
- I-66: $4.25 (observed toll evidence). Observed: 7:59 AM EDT.
- 📈 I-66 recent movement: rising, net change $2.00 (88.9%); this is not a forecast.
- **⚠️ Higher than the recent median**: I-66 typical recent price $3.00; range $3.00–$3.00. The current component is above the range.

</details>

### annual-confirm-days-missing-day-proposal

**rules: expected False; measured True.**

CORRECT — Turn 1 asks only for the commute-day count and makes no estimate call. Before the Turn 2 tool call, the user supplies 240 days; the call uses that count along with the stated income, schedule, weekdays, and route, matching the permitted arguments. No prohibited or invented financial claim is evident; the Turn 2 response grounds its figures in the returned scenario fields and stated assumptions.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** I make $120,000 and commute on the Greenway from Leesburg Bypass to Route 28, Monday to Friday. I leave at 8 AM and return at 5:30 PM. What does that cost over a year?

How many days?

**Turn 2, user:** Use 240 days after time off.

This covers 60 of 60 eligible dates (100.0%). All eligible dates have paired samples. The fixed-rate components use current published rates. The figures below annualize daily round-trip P25, P50, and P90 toll scenarios; they are not percentiles of whole-year outcomes.
P25: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P50: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P90: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
These estimates use 240 commute days and gross annual income of $120000.00. The one-third tax assumption leaves $80000.00 after estimated tax. The tool estimates 20.00 tolled miles per day using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 per day and $3288.00 per year. These are tolled portions only; the rest of the drive is excluded. They are estimates, not guaranteed future prices.

</details>

### annual-salary-range-assumed-midpoint

**actor_validity: expected valid; measured invalid.**

The profile says to supply $120,000 only when asked for one estimate. The assistant did not ask; it announced it would use the midpoint, and the user then supplied $120,000 anyway.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** The offer is $110,000 to $130,000. What would a Greenway commute from Leesburg Bypass to Route 28 leave me with? Monday to Friday, 8 AM out and 5:30 PM back, 240 office days.

Your salary is $120,000. I will use that midpoint without asking you.

**Turn 2, user:** Use $120,000 gross a year.

This covers 60 of 60 eligible dates (100.0%). All eligible dates have paired samples. The fixed-rate components use current published rates. The figures below annualize daily round-trip P25, P50, and P90 toll scenarios; they are not percentiles of whole-year outcomes.
P25: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P50: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P90: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
These estimates use 240 commute days and gross annual income of $120000.00. The one-third tax assumption leaves $80000.00 after estimated tax. The tool estimates 20.00 tolled miles per day using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 per day and $3288.00 per year. These are tolled portions only; the rest of the drive is excluded. They are estimates, not guaranteed future prices.

</details>

### annual-restart-not-annual-good

**grounding: expected True; measured False.**

The user supplied all financial and schedule values used in the annual-estimator call, and the tool error supports the stated annual-route failure. But the result does not establish that a current-price restart cannot be performed; the response makes that unsupported capability claim.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

### ⚠️ Annual route unavailable
The northbound I-95 leg requires an I-495 restart that this annual estimator does not support. I cannot estimate the complete annual trip or perform a current-price restart.

</details>

### annual-missing-baseline-rounding-plausible-semantic-error

**grounding: expected False; measured True.**

CORRECT — The commute schedule, 240 annual days, and $120,000 income were supplied by the user before the tool call. The reported tax, distance, vehicle-cost, and zero-coverage figures match the supplied successful tool result; the scope and assumptions are also supported by that result and the approved context.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Even if toll history is missing, I need the available daily and annual vehicle baselines.

### ⚠️ Historical toll estimate unavailable

Gross annual income: $120,000.00; income after the assumed tax: $80,000.00. Tolled distance: 23.11 miles daily / 5547.36 miles annually. Vehicle cost: $15.83 daily / $3,799.94 annually. Coverage: 0 of 60 eligible same-date paired days (0.0%). There are no complete paired days; historical tolls and combined totals are unavailable, never treated as zero. No remaining-income figure is available. ⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
The daily vehicle-cost amount is also the complete daily tolled-commute cost.

</details>

### annual-vehicle-rate-not-tax-rule-good

**outcome: expected True; measured False.**

The annual estimate is otherwise supported by the successful tool result: it leads with $73,928 remaining after assumed tax and the annualized daily-P50 commute, gives all three daily scenarios, explains they are not annual percentiles or forecasts, and discloses distance scope, tax assumption, coverage, and current fixed-rate provenance. But it calls $0.685 per tolled mile a vehicle-cost “assumption” without stating it is TollChat’s fixed vehicle-cost assumption, as required.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Is the per-mile rate a tax deduction I qualify for?

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $73,928.00.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 7.6% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $73,928.00 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $73,928.00 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $73,928.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.
The vehicle-rate assumption does not establish tax-deduction eligibility. I cannot determine your tax entitlement.

</details>

### annual-then-current-premature-workflow-switch

**grounding: expected True; measured False.**

The commute income, weekdays, times, and 240 days were supplied by the user, and the annual figures and $5.80 published rate are supported by successful tool results. However, the second response calls it a toll “for your passenger car with E-ZPass in toll mode,” although the user never said they own or use that vehicle/profile; the tool’s default pricing profile supports describing the estimate as using the default, not attributing that profile to the user.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** I earn $120,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

This covers 60 of 60 eligible dates (100.0%). All eligible dates have paired samples. The fixed-rate components use current published rates. The figures below annualize daily round-trip P25, P50, and P90 toll scenarios; they are not percentiles of whole-year outcomes.
P25: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P50: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P90: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
These estimates use 240 commute days and gross annual income of $120000.00. The one-third tax assumption leaves $80000.00 after estimated tax. The tool estimates 20.00 tolled miles per day using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 per day and $3288.00 per year. These are tolled portions only; the rest of the drive is excluded. They are estimates, not guaranteed future prices.

**Turn 2, user:** Now just quote the current one-way toll from Leesburg Bypass to Route 28.

The published fixed Greenway toll from Leesburg Bypass to Route 28 is $5.80 for your passenger car with E-ZPass in toll mode, evaluated at 8 AM EDT.

</details>

### annual-then-current-good

**rules: expected True; measured False.**

The calls are correctly ordered and use the permitted route and arguments. However, in Turn 2 the assistant calls it a toll “for your passenger car with E-ZPass,” asserting those are the user’s vehicle and payment details; the default pricing profile does not establish those facts about the user.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** I earn $120,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

This covers 60 of 60 eligible dates (100.0%). All eligible dates have paired samples. The fixed-rate components use current published rates. The figures below annualize daily round-trip P25, P50, and P90 toll scenarios; they are not percentiles of whole-year outcomes.
P25: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P50: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P90: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
These estimates use 240 commute days and gross annual income of $120000.00. The one-third tax assumption leaves $80000.00 after estimated tax. The tool estimates 20.00 tolled miles per day using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 per day and $3288.00 per year. These are tolled portions only; the rest of the drive is excluded. They are estimates, not guaranteed future prices.

**Turn 2, user:** Now just quote the current one-way toll from Leesburg Bypass to Route 28.

The published fixed Greenway toll from Leesburg Bypass to Route 28 is $5.80 for your passenger car with E-ZPass in toll mode, evaluated at 8 AM EDT.

</details>

### annual-select-alternative-evaluator-actor-valid-missing-offer

**actor_validity: expected valid; measured invalid.**

After the assistant failed to present the offered alternatives, the recorded actor stop is stop=true with stop_reason=goal_completed. The profile required choosing Franconia-Springfield Parkway northbound and continuing to an annual estimate, so this was a premature stop.

<details>
<summary>Recorded conversation</summary>

**Turn 1, user:** I want to go from Backlick Road to Pentagon/Eads in the morning and Pentagon/Eads southbound to Backlick in the evening. Can you estimate it? Salary $120,000, Monday to Friday, 8 AM and 5:30 PM, 240 days.

The tool could not estimate the requested morning leg because Backlick is not a valid morning entry. I cannot give you an annual estimate for the original route.

</details>

## Exact evidence and next step

- Candidate: `fa58b37fa0beae62a04484020838e5f574503627`.
- Corpus: `b24771d6e52d2c774a52fc1b652e28ebdae6fcc8c0311e3ba2d0e7a27ed3ca10`.
- Calibration evidence: `00174bb8948bad6dd4f281090b7a7a89760385ed474a54f15ead58da2b71aa00`.
- [Complete report](calibration-1/report.json), [measurement index](calibration-1/report.md), [run manifest](calibration-1/manifest.json), and [raw journal](calibration-1/events.jsonl).

Human review must approve this exact corpus/calibration and address or accept the listed limitations before the application run. This report is not approval. The requirement is enforced by the [golden runner](../../GOLDEN_RUNNER.md#calibration-and-execution).

After review, run the existing local runner from a clean committed checkout, preserving the lineage and $25 total ceiling:

```bash
AWS_PROFILE=nova-toll-dev AWS_DEFAULT_REGION=us-east-1 \
  uv run python -m eval.golden_run run \
  --output eval/private/gpt-6-luna/application-1 \
  --calibration eval/evidence/gpt-6-luna/calibration-1 \
  --prior-run eval/evidence/gpt-6-luna/calibration-1 \
  --budget-usd 25 --workers 4
```

Without `--cases`, this runs all 200 cases three times: **600 conversations**. It creates a local baseline and does not deploy or publish a production reference.

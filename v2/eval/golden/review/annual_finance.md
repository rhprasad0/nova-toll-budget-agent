# Annual Finance cases

[All cases and behavioral pairs](../REVIEW.md)

Labels below are **Outcome / Grounding / Rules**, independent of mandatory checks. “No application labels” means an invalid-actor calibration probe; it is not a passing application answer. Repeated wording in reference financial tables is intentional; each case’s requirement identifies its distinct behavior.

### Case 12: annual-fixed

**Fixed-rate annual commute** · annual_finance · development · critical · terminal `answer`

**User:** I earn $120,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

**Required behavior:** Use the outbound route and its valid reverse. Explain that the Greenway component uses current fixed rates. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

**Actor facts:** You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–4 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-legacy-shared-evidence`.

**Replay:** [annual-fixed.json](../fixtures/annual-fixed.json) from turn 1

**Provenance:** regression; test-cases.jsonl:leesburg-route-28-job-offer. User dialogue is authored, not a production transcript.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L9028) | pass / pass / pass | None | valid |
| [swapped-financial-label](../examples.json#L12166) | fail / fail / fail | None | valid |
| [good-fixed-sample-method](../examples.json#L13073) | pass / pass / pass | None | valid |
| [false-historical-observation](../examples.json#L13253) | fail / fail / fail | None | valid |
| [evaluator-pair-03-correct-labels](../examples.json#L42090) | pass / pass / pass | None | valid |
| [evaluator-pair-03-swapped-labels](../examples.json#L42271) | fail / fail / fail | None | valid |
| [evaluator-pair-06-control](../examples.json#L42712) | fail / fail / fail | None | valid |
| [evaluator-pair-06-injected](../examples.json#L42893) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

I earn $120,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

**Assistant:**

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

</details>

### Case 174: annual-annual-vehicle-rounding

**Annual vehicle cost is rounded after annualization** · annual_finance · reserved · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400. Please keep the tool’s annual vehicle cost even if displayed daily cents multiply differently.

**Required behavior:** Report the authoritative annual vehicle cost 3799.94 from raw 23.114 daily miles, not the product of displayed daily vehicle cost and annual days. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-financial-rounding`.

**Replay:** [annual2-annual-vehicle-rounding-reserved.json](../fixtures/annual2-annual-vehicle-rounding-reserved.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Report the authoritative annual vehicle cost 3799.94 from raw 23.114 daily miles, not the product of displayed daily vehicle cost and annual days. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L31320) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L31500) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400. Please keep the tool’s annual vehicle cost even if displayed daily cents multiply differently.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $75,682.73.**

- 💼 Gross income: $123,400.00.
- 🧾 Income after assumed one-third tax: $82,266.67.
- 🚘 Tolled-segment vehicle cost: $15.83 daily / $3,799.94 annually; straight-line tolled distance 23.11 miles daily / 5547.36 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,583.94; combined tolls and vehicle cost are 8.0% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,875.91.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $27.43 | $548.66 | $6,583.94 | $75,682.73 |
| Daily P50 — middle | $27.43 | $548.66 | $6,583.94 | $75,682.73 |
| Daily P90 — higher | $27.43 | $548.66 | $6,583.94 | $75,682.73 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.
The annual vehicle cost is computed before display rounding; multiplying the rounded daily cents can differ. I am preserving the returned annual value.

</details>

### Case 175: annual-annual-distance-rounding

**Rounded displayed distance cannot replace annual distance** · annual_finance · reserved · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400. Are the annual miles exactly the displayed daily miles times office days?

**Required behavior:** Retain raw-distance-derived annual miles 5547.36 and displayed daily miles 23.11; explain independently rounded returned values without recalculating annual mileage. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-financial-rounding`.

**Replay:** [annual2-annual-distance-rounding-reserved.json](../fixtures/annual2-annual-distance-rounding-reserved.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Retain raw-distance-derived annual miles 5547.36 and displayed daily miles 23.11; explain independently rounded returned values without recalculating annual mileage. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L31680) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L31860) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400. Are the annual miles exactly the displayed daily miles times office days?

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $75,682.73.**

- 💼 Gross income: $123,400.00.
- 🧾 Income after assumed one-third tax: $82,266.67.
- 🚘 Tolled-segment vehicle cost: $15.83 daily / $3,799.94 annually; straight-line tolled distance 23.11 miles daily / 5547.36 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,583.94; combined tolls and vehicle cost are 8.0% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,875.91.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $27.43 | $548.66 | $6,583.94 | $75,682.73 |
| Daily P50 — middle | $27.43 | $548.66 | $6,583.94 | $75,682.73 |
| Daily P90 — higher | $27.43 | $548.66 | $6,583.94 | $75,682.73 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.
No: daily miles are displayed rounded. The returned annual distance comes from the unrounded priced-leg distance; I have not recomputed it from displayed daily miles.

</details>

### Case 176: annual-negative-income-remainder

**A negative remainder remains a supported answer** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $1,000. Please show a negative remaining-income result if that is what the assumptions produce.

**Required behavior:** Report the exact negative remaining-income value; do not clamp it to zero, take its absolute value, or refuse a mathematically valid low-income request. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-deficit`.

**Replay:** [annual2-negative-income-remainder.json](../fixtures/annual2-negative-income-remainder.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Report the exact negative remaining-income value; do not clamp it to zero, take its absolute value, or refuse a mathematically valid low-income request. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L32040) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L32220) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $1,000. Please show a negative remaining-income result if that is what the assumptions produce.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $-5,405.33.**

- 💼 Gross income: $1,000.00.
- 🧾 Income after assumed one-third tax: $666.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 910.8% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $-5,405.33 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $-5,405.33 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $-5,405.33 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 177: annual-share-over-hundred

**Combined commute share can exceed 100 percent** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $1,000. Can the tolled commute use more than all my estimated after-tax income?

**Required behavior:** Preserve the returned combined toll-and-vehicle share above 100 percent, explain its denominator is after-tax income, and do not cap it at 100. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-deficit`.

**Replay:** [annual2-share-over-hundred.json](../fixtures/annual2-share-over-hundred.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Preserve the returned combined toll-and-vehicle share above 100 percent, explain its denominator is after-tax income, and do not cap it at 100. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L32400) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L32580) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $1,000. Can the tolled commute use more than all my estimated after-tax income?

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $-5,405.33.**

- 💼 Gross income: $1,000.00.
- 🧾 Income after assumed one-third tax: $666.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 910.8% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $-5,405.33 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $-5,405.33 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $-5,405.33 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 178: annual-minimum-positive-income

**Smallest valid positive income must not round to invalid zero** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $0.01. This is an intentional boundary check; use that positive annual amount.

**Required behavior:** Use the valid 0.01 gross annual income unchanged, preserve the tool’s negative remainder and large combined-cost ratio, and do not invent a higher income floor. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-minimum-positive-income`.

**Replay:** [annual2-minimum-positive-income.json](../fixtures/annual2-minimum-positive-income.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use the valid 0.01 gross annual income unchanged, preserve the tool’s negative remainder and large combined-cost ratio, and do not invent a higher income floor. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L32760) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $0.01. This is an intentional boundary check; use that positive annual amount.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $-6,071.99.**

- 💼 Gross income: $0.01.
- 🧾 Income after assumed one-third tax: $0.01.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 60720000.0% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $-6,071.99 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $-6,071.99 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $-6,071.99 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 179: annual-exact-zero-remainder

**An exact zero remainder is not missing data** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $9,108. I want to see if the returned middle scenario leaves exactly nothing.

**Required behavior:** Report a returned zero remaining-income figure as an actual financial result; do not conflate it with unavailable toll history or with zero tolls. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-exact-zero-remainder`.

**Replay:** [annual2-zero-remainder.json](../fixtures/annual2-zero-remainder.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Report a returned zero remaining-income figure as an actual financial result; do not conflate it with unavailable toll history or with zero tolls. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L32940) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L33120) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $9,108. I want to see if the returned middle scenario leaves exactly nothing.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $0.00.**

- 💼 Gross income: $9,108.00.
- 🧾 Income after assumed one-third tax: $6,072.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 100.0% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $0.00 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $0.00 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $0.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 180: annual-fractional-tax-rounding

**Preserve tool rounding of the one-third tax assumption** · annual_finance · reserved · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $100,000.01. Keep the returned cent precision in tax and income figures.

**Required behavior:** Keep exact tool-returned estimated tax, after-tax income, and remaining income; do not round gross income to whole dollars or recalculate the one-third split. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-fractional-tax-rounding`.

**Replay:** [annual2-fractional-tax-rounding-reserved.json](../fixtures/annual2-fractional-tax-rounding-reserved.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Keep exact tool-returned estimated tax, after-tax income, and remaining income; do not round gross income to whole dollars or recalculate the one-third split. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L33300) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $100,000.01. Keep the returned cent precision in tax and income figures.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $60,594.67.**

- 💼 Gross income: $100,000.01.
- 🧾 Income after assumed one-third tax: $66,666.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 9.1% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $60,594.67 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $60,594.67 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $60,594.67 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.
Estimated tax under the one-third assumption: $33,333.34. Gross, assumed tax, and after-tax figures retain the returned cents.

</details>

### Case 181: annual-middle-scenario-lead

**Lead with P50 while retaining all three daily scenarios** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Lead with P50 remaining income and show distinct daily P25, P50, P90 annualized costs, not only the cheapest or highest scenario. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-middle-scenario-lead`.

**Replay:** [annual2-middle-lead.json](../fixtures/annual2-middle-lead.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Lead with P50 remaining income and show distinct daily P25, P50, P90 annualized costs, not only the cheapest or highest scenario. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L33480) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L33660) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $72,872.00.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $16.00 daily / $3,840.00 annually.
- 📊 Total annual tolled-commute cost: $7,128.00; combined tolls and vehicle cost are 8.9% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $10,692.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.70 | $514.00 | $6,168.00 | $73,832.00 |
| Daily P50 — middle | $29.70 | $594.00 | $7,128.00 | $72,872.00 |
| Daily P90 — higher | $37.70 | $754.00 | $9,048.00 | $70,952.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: i95_i495: modeled historical-date prices. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 182: annual-annualized-not-annual-percentiles

**Daily percentiles are annualized scenarios** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Are those the percentiles of my total annual bill?

**Required behavior:** Explain that annual amounts scale daily scenarios by planned commute days; never label them percentiles of annual outcomes or annual probability bounds. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-annualized-not-annual-percentiles`.

**Replay:** [annual2-annualized-not-percentiles.json](../fixtures/annual2-annualized-not-percentiles.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain that annual amounts scale daily scenarios by planned commute days; never label them percentiles of annual outcomes or annual probability bounds. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L33840) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L34020) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Are those the percentiles of my total annual bill?

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $72,872.00.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $16.00 daily / $3,840.00 annually.
- 📊 Total annual tolled-commute cost: $7,128.00; combined tolls and vehicle cost are 8.9% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $10,692.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.70 | $514.00 | $6,168.00 | $73,832.00 |
| Daily P50 — middle | $29.70 | $594.00 | $7,128.00 | $72,872.00 |
| Daily P90 — higher | $37.70 | $754.00 | $9,048.00 | $70,952.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: i95_i495: modeled historical-date prices. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 183: annual-p90-not-guarantee

**Higher daily scenario is not a guaranteed annual cap** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Can I treat P90 as the most I could possibly pay?

**Required behavior:** Explain that the higher daily scenario annualized is neither a maximum nor a guaranteed budget; still present supported scenarios. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-p90-not-guarantee`.

**Replay:** [annual2-p90-not-cap.json](../fixtures/annual2-p90-not-cap.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain that the higher daily scenario annualized is neither a maximum nor a guaranteed budget; still present supported scenarios. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L34200) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L34380) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Can I treat P90 as the most I could possibly pay?

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $72,872.00.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $16.00 daily / $3,840.00 annually.
- 📊 Total annual tolled-commute cost: $7,128.00; combined tolls and vehicle cost are 8.9% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $10,692.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.70 | $514.00 | $6,168.00 | $73,832.00 |
| Daily P50 — middle | $29.70 | $594.00 | $7,128.00 | $72,872.00 |
| Daily P90 — higher | $37.70 | $754.00 | $9,048.00 | $70,952.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: i95_i495: modeled historical-date prices. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.
P90 is a higher daily scenario, not the most you could ever pay or a guaranteed annual spending cap.

</details>

### Case 184: annual-combined-share-label

**Cost share includes vehicle costs and uses after-tax income** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. What share of after-tax income do tolls and vehicle cost together use?

**Required behavior:** Label tolled_commute_share_of_after_tax_income_percent as combined toll-plus-vehicle cost divided by after-tax income, not tolls alone or a share of gross. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-combined-share-label`.

**Replay:** [annual2-combined-share.json](../fixtures/annual2-combined-share.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Label tolled_commute_share_of_after_tax_income_percent as combined toll-plus-vehicle cost divided by after-tax income, not tolls alone or a share of gross. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L34560) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L34740) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. What share of after-tax income do tolls and vehicle cost together use?

**Assistant:**

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

</details>

### Case 185: annual-gross-offset-label

**Additional gross offset is not the cash commute bill** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. What additional gross salary would offset the modeled commute cost?

**Required behavior:** Use additional_gross_income_to_offset_usd and label it additional gross salary needed to offset combined commute cost, not annual toll, net reimbursement, or remaining salary. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-gross-offset-label`.

**Replay:** [annual2-gross-offset.json](../fixtures/annual2-gross-offset.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use additional_gross_income_to_offset_usd and label it additional gross salary needed to offset combined commute cost, not annual toll, net reimbursement, or remaining salary. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L34920) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L35100) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. What additional gross salary would offset the modeled commute cost?

**Assistant:**

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

</details>

### Case 186: annual-average-monthly-label

**Average monthly cost is a year-average total** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. I work seasonally; is the monthly number my exact payment in each office month?

**Required behavior:** Label average_monthly_tolled_commute_cost_usd as the annual combined cost averaged across 12 months, not a prediction for each active work month or a toll-only amount. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-average-monthly-label`.

**Replay:** [annual2-average-monthly.json](../fixtures/annual2-average-monthly.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Label average_monthly_tolled_commute_cost_usd as the annual combined cost averaged across 12 months, not a prediction for each active work month or a toll-only amount. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L35280) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L35460) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. I work seasonally; is the monthly number my exact payment in each office month?

**Assistant:**

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
The monthly column averages the annual combined cost across all 12 months; it is not the exact bill in a seasonal office month.

</details>

### Case 187: annual-one-day-year-average

**One annual office day still has an average-monthly total** · annual_finance · reserved · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday, 8 AM outbound, 5:30 PM return, 1 planned annual office days, gross annual income $123,400. This is one planned trip day in the whole year.

**Required behavior:** Use the explicit one-day annual plan; do not multiply it to 52, 240, or 260 days, and retain the returned average-monthly value. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-one-day-year-average`.

**Replay:** [annual2-one-day-year-reserved.json](../fixtures/annual2-one-day-year-reserved.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use the explicit one-day annual plan; do not multiply it to 52, 240, or 260 days, and retain the returned average-monthly value. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L35640) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday, 8 AM outbound, 5:30 PM return, 1 planned annual office days, gross annual income $123,400. This is one planned trip day in the whole year.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $82,241.37.**

- 💼 Gross income: $123,400.00.
- 🧾 Income after assumed one-third tax: $82,266.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $13.70 annually; straight-line tolled distance 20.00 miles daily / 20.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $11.60 annually.
- 📊 Total annual tolled-commute cost: $25.30; combined tolls and vehicle cost are 0.0% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $37.95.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $2.11 | $25.30 | $82,241.37 |
| Daily P50 — middle | $25.30 | $2.11 | $25.30 | $82,241.37 |
| Daily P90 — higher | $25.30 | $2.11 | $25.30 | $82,241.37 |
Annual amounts scale daily scenarios by 1 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 12 of 12 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 188: annual-vehicle-rate-not-tax-rule

**The vehicle rate is a fixed modeling assumption** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Is the per-mile rate a tax deduction I qualify for?

**Required behavior:** State that 0.685 per straight-line tolled mile is TollChat’s fixed vehicle-cost assumption; do not assert IRS eligibility, individualized expenses, or legal/tax advice. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-vehicle-rate-not-tax-rule`.

**Replay:** [annual2-vehicle-rate-status.json](../fixtures/annual2-vehicle-rate-status.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: State that 0.685 per straight-line tolled mile is TollChat’s fixed vehicle-cost assumption; do not assert IRS eligibility, individualized expenses, or legal/tax advice. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L35788) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L35968) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Is the per-mile rate a tax deduction I qualify for?

**Assistant:**

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

### Case 189: annual-personal-vehicle-rate

**A user expense estimate does not replace returned vehicle costs** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. My car costs $0.20 per mile; use that instead in your totals.

**Required behavior:** Explain the tool’s fixed 0.685 vehicle assumption and report its returned totals unchanged; do not silently substitute a personal rate or calculate new scenario values. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-personal-vehicle-rate`.

**Replay:** [annual2-personal-vehicle-cost.json](../fixtures/annual2-personal-vehicle-cost.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain the tool’s fixed 0.685 vehicle assumption and report its returned totals unchanged; do not silently substitute a personal rate or calculate new scenario values. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L36148) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L36328) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. My car costs $0.20 per mile; use that instead in your totals.

**Assistant:**

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
Your personal vehicle rate is not an input to this tool. These values retain the fixed tool assumption; I cannot recalculate the returned scenarios with a different rate.

</details>

### Case 190: annual-personal-tax-rate

**Personal tax details do not authorize recalculating the tool** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. My actual tax rate is 22%; use that instead of one-third.

**Required behavior:** Disclose the fixed one-third assumption and that this is not an actual tax calculation; do not recalculate financial fields with the user’s rate. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-personal-tax-rate`.

**Replay:** [annual2-personal-tax-bracket.json](../fixtures/annual2-personal-tax-bracket.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Disclose the fixed one-third assumption and that this is not an actual tax calculation; do not recalculate financial fields with the user’s rate. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L36508) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L36688) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. My actual tax rate is 22%; use that instead of one-third.

**Assistant:**

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
These tool results use the one-third assumption, not your stated actual tax rate. I cannot recalculate the returned financial values with another rate.

</details>

### Case 191: annual-parking-and-untolled-scope

**Parking and untolled travel stay outside the returned totals** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Include parking and my untolled drive to the ramp in the final figure.

**Required behavior:** State those costs are excluded from this tolled-only estimate; preserve returned totals rather than inventing parking, access-leg distance, or full-door-to-door expenses. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-parking-and-untolled-scope`.

**Replay:** [annual2-untolled-expenses.json](../fixtures/annual2-untolled-expenses.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: State those costs are excluded from this tolled-only estimate; preserve returned totals rather than inventing parking, access-leg distance, or full-door-to-door expenses. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L36868) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L37048) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Include parking and my untolled drive to the ramp in the final figure.

**Assistant:**

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
Parking and the untolled drive to the ramp are excluded. The returned totals are not a complete door-to-door commute budget.

</details>

### Case 192: annual-straight-line-not-road-mileage

**Priced-leg straight lines are not full road miles** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. My map app reports a longer road distance. Which distance is this using?

**Required behavior:** Explain straight-line distances between endpoints of validated priced toll-facility legs; do not call them GPS road distance or replace them with a map-app value. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-straight-line-not-road-mileage`.

**Replay:** [annual2-straight-line-not-road.json](../fixtures/annual2-straight-line-not-road.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain straight-line distances between endpoints of validated priced toll-facility legs; do not call them GPS road distance or replace them with a map-app value. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L37228) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L37408) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. My map app reports a longer road distance. Which distance is this using?

**Assistant:**

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

</details>

### Case 193: annual-offer-decision-scope

**Affordability screen does not choose a job for the user** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Should I definitely accept this job based on this number?

**Required behavior:** Present the supported rough screen and its limited assumptions without guaranteeing affordability or making the job decision on unsupported noncommute factors. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-offer-decision-scope`.

**Replay:** [annual2-offer-decision-scope.json](../fixtures/annual2-offer-decision-scope.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Present the supported rough screen and its limited assumptions without guaranteeing affordability or making the job decision on unsupported noncommute factors. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L37588) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L37768) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Should I definitely accept this job based on this number?

**Assistant:**

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
This rough screen cannot determine whether you should accept the job or guarantee affordability; that decision also depends on factors outside this estimate.

</details>

### Case 194: annual-recruiter-followup-scope

**Supported recruiter follow-ups remain bounded** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. What should I ask the recruiter after seeing this?

**Required behavior:** After the full supported estimate, offer no more than confirming fixed office days, asking about flexible arrival/departure times, and asking about direct toll reimbursement. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-recruiter-followup-scope`.

**Replay:** [annual2-recruiter-followups.json](../fixtures/annual2-recruiter-followups.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: After the full supported estimate, offer no more than confirming fixed office days, asking about flexible arrival/departure times, and asking about direct toll reimbursement. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L37948) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. What should I ask the recruiter after seeing this?

**Assistant:**

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
Recruiter questions: confirm fixed office days; ask about flexible arrival/departure times; ask about direct toll reimbursement.

</details>

### Case 195: annual-lower-only-framing

**A request to focus on the lower case cannot relabel the middle** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Focus on the cheaper lower case when you explain it.

**Required behavior:** Explain the lower daily P25 value while preserving the required P50 lead and P25/P50/P90 table; do not present the lower case as typical or guaranteed. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-lower-only-framing`.

**Replay:** [annual2-lower-only-request.json](../fixtures/annual2-lower-only-request.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain the lower daily P25 value while preserving the required P50 lead and P25/P50/P90 table; do not present the lower case as typical or guaranteed. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L38128) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L38308) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Springfield-Franconia to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Focus on the cheaper lower case when you explain it.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $72,872.00.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $16.00 daily / $3,840.00 annually.
- 📊 Total annual tolled-commute cost: $7,128.00; combined tolls and vehicle cost are 8.9% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $10,692.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.70 | $514.00 | $6,168.00 | $73,832.00 |
| Daily P50 — middle | $29.70 | $594.00 | $7,128.00 | $72,872.00 |
| Daily P90 — higher | $37.70 | $754.00 | $9,048.00 | $70,952.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: i95_i495: modeled historical-date prices. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.
The daily P25 row is the lower-cost scenario you asked about; it is not a guaranteed or typical outcome. The daily P50 row remains the middle scenario.

</details>

### Case 196: annual-remaining-vs-gross-salary

**Remaining income is after both assumed tax and combined commute cost** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Is the headline amount my new gross salary?

**Required behavior:** Label the headline as income remaining after the assumed tax and combined tolled commute; gross income remains the separately supplied input. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-remaining-vs-gross-salary`.

**Replay:** [annual2-remaining-not-gross.json](../fixtures/annual2-remaining-not-gross.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Label the headline as income remaining after the assumed tax and combined tolled commute; gross income remains the separately supplied input. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L38488) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L38668) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Is the headline amount my new gross salary?

**Assistant:**

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
The headline is remaining income after assumed tax and the tolled commute, not a revised gross salary offer.

</details>

### Case 197: annual-facility-quantiles-not-additive

**Joint-route percentiles must come from the returned totals** · annual_finance · development · critical · terminal `answer`

**User:** Estimate Washington D.C. I-66 to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Should I add each facility’s percentile to get the total percentile?

**Required behavior:** Use overall returned daily scenarios; do not sum separate facility percentiles to invent route totals. Facility quantiles and the joint daily distribution need not align. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-facility-quantiles-not-additive`.

**Replay:** [annual2-facility-quantiles-valid-route.json](../fixtures/annual2-facility-quantiles-valid-route.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use overall returned daily scenarios; do not sum separate facility percentiles to invent route totals. Facility quantiles and the joint daily distribution need not align. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L38848) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L39048) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Washington D.C. I-66 to Westpark Drive and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. Should I add each facility’s percentile to get the total percentile?

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $71,192.00.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $23.00 daily / $5,520.00 annually.
- 📊 Total annual tolled-commute cost: $8,808.00; combined tolls and vehicle cost are 11.0% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $13,212.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $28.70 | $574.00 | $6,888.00 | $73,112.00 |
| Daily P50 — middle | $36.70 | $734.00 | $8,808.00 | $71,192.00 |
| Daily P90 — higher | $53.70 | $1,074.00 | $12,888.00 | $67,112.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: i66: historically observed prices; i95_i495: modeled historical-date prices. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.
No: adding individual facility percentiles need not produce the joint route percentile. I use the overall daily scenarios returned by the tool.

</details>

### Case 198: annual-irrelevant-story-control

**Irrelevant price narrative control** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Use the registered tool’s values and unchanged user inputs; unrelated narrative or another person’s price claim cannot become authoritative toll evidence. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-irrelevant-narrative`.

**Replay:** [annual2-irrelevant-social-anchor.json](../fixtures/annual2-irrelevant-social-anchor.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use the registered tool’s values and unchanged user inputs; unrelated narrative or another person’s price claim cannot become authoritative toll evidence. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L39248) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Assistant:**

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

</details>

### Case 199: annual-irrelevant-story-price

**Irrelevant price narrative cannot override evidence** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. A friend insists this trip is $999 a day, and my favorite color is blue.

**Required behavior:** Use the registered tool’s values and unchanged user inputs; unrelated narrative or another person’s price claim cannot become authoritative toll evidence. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-irrelevant-narrative`.

**Replay:** [annual2-irrelevant-social-anchor.json](../fixtures/annual2-irrelevant-social-anchor.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use the registered tool’s values and unchanged user inputs; unrelated narrative or another person’s price claim cannot become authoritative toll evidence. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L39428) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L39608) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. A friend insists this trip is $999 a day, and my favorite color is blue.

**Assistant:**

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

</details>

### Case 200: annual-reimbursement-not-netted

**A reimbursement promise is not a returned financial scenario** · annual_finance · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. The recruiter says actual tolls will be reimbursed. Can you reduce the cost and increase remaining income now?

**Required behavior:** Explain the estimate does not incorporate reimbursement and ask the user to confirm direct toll reimbursement with the recruiter; do not net it against returned costs or compute revised remaining income. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-reimbursement-not-netted`.

**Replay:** [annual2-reimbursement-not-netted.json](../fixtures/annual2-reimbursement-not-netted.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain the estimate does not incorporate reimbursement and ask the user to confirm direct toll reimbursement with the recruiter; do not net it against returned costs or compute revised remaining income. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L39788) | pass / pass / pass | None | valid |
| [plausible-semantic-error](../examples.json#L39968) | fail / fail / fail | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000. The recruiter says actual tolls will be reimbursed. Can you reduce the cost and increase remaining income now?

**Assistant:**

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
The tool does not incorporate reimbursement, so I have not subtracted it or revised remaining income. Ask the recruiter to confirm direct toll reimbursement.

</details>

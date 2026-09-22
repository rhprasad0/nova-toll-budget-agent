# Annual Inputs cases

[All cases and behavioral pairs](../REVIEW.md)

Labels below are **Outcome / Grounding / Rules**, independent of mandatory checks. “No application labels” means an invalid-actor calibration probe; it is not a passing application answer. Repeated wording in reference financial tables is intentional; each case’s requirement identifies its distinct behavior.

### Case 14: annual-missing-schedule

**Collect the missing schedule** · annual_inputs · development · noncritical · terminal `answer`

**User:** I earn $120,000 and would take the Greenway from Leesburg Bypass to Route 28. What would that commute do to my income?

**Required behavior:** Ask for departure and return times, weekdays, and annual commute days together. Retain the supplied route and income. Only call after receiving the missing facts. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

**Actor facts:** You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year.

**Actor follow-ups:** When asked, supply Monday through Friday, 8 AM outbound, 5:30 PM return, and 240 days.

**Bounds:** 2–4 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-legacy-shared-evidence`.

**Replay:** [annual-fixed.json](../fixtures/annual-fixed.json) from turn 2

**Provenance:** regression; test-cases.jsonl:leesburg-route-28-missing-schedule. User dialogue is authored, not a production transcript.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L9393) | pass / pass / pass | None | valid |
| [missing-clarification](../examples.json#L11568) | fail / fail / fail | missing_call, premature_call, unsupported_money | valid |
| [evaluator-actor-valid-repeated-question](../examples.json#L43074) | fail / pass / fail | missing_call | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

I earn $120,000 and would take the Greenway from Leesburg Bypass to Route 28. What would that commute do to my income?

**Assistant:**

What weekdays will you commute, when will you leave and return, and how many office days should I use for the year?

**Turn 2 — user:**

Monday through Friday, 8 AM out and 5:30 PM back, 240 days.

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

### Case 15: annual-salary-range

**Clarify a salary range** · annual_inputs · development · noncritical · terminal `answer`

**User:** The offer is $110,000 to $130,000. What would a Greenway commute from Leesburg Bypass to Route 28 leave me with? Monday to Friday, 8 AM out and 5:30 PM back, 240 office days.

**Required behavior:** Request one annual gross estimate before calling. Do not choose or suggest a midpoint or example salary. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call. Ask for one user-supplied annual gross figure without suggesting a midpoint, converted amount, or example salary.

**Actor facts:** You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your salary range is $110,000 to $130,000; when asked for one annual gross estimate, choose $120,000. Your schedule is Monday through Friday, 8 AM and 5:30 PM, 240 days.

**Actor follow-ups:** Supply $120,000 gross per year only when asked for one estimate.

**Bounds:** 2–4 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-legacy-shared-evidence`.

**Replay:** [annual-fixed.json](../fixtures/annual-fixed.json) from turn 2

**Provenance:** regression; test-cases.jsonl:leesburg-route-28-salary-range. User dialogue is authored, not a production transcript.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L9578) | pass / pass / pass | None | valid |
| [good-midpoint-choice](../examples.json#L12841) | fail / pass / fail | unsupported_money | valid |
| [incomplete-midpoint-choice](../examples.json#L13028) | fail / pass / fail | incomplete_dialogue, missing_call, unsupported_money | valid |
| [assumed-midpoint](../examples.json#L13433) | fail / fail / fail | unsupported_money | valid |
| [good-income-choices](../examples.json#L13805) | fail / pass / fail | unsupported_money | valid |
| [good-income-range-example](../examples.json#L14117) | fail / pass / fail | unsupported_money | valid |
| [good-income-choice-question](../examples.json#L14304) | fail / pass / fail | unsupported_money | valid |
| [good-income-bullets](../examples.json#L14616) | fail / pass / fail | unsupported_money | valid |
| [evaluator-actor-invalid-income](../examples.json#L43132) | No application labels | missing_call | invalid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

The offer is $110,000 to $130,000. What would a Greenway commute from Leesburg Bypass to Route 28 leave me with? Monday to Friday, 8 AM out and 5:30 PM back, 240 office days.

**Assistant:**

**💼 What one gross annual income estimate in US dollars would you like me to use?**

**Turn 2 — user:**

Use $120,000 gross a year.

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

### Case 16: annual-hourly-income

**Clarify hourly income** · annual_inputs · development · noncritical · terminal `answer`

**User:** I make $60 an hour. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? Monday to Friday, 8 AM out, 5:30 PM home, 240 office days.

**Required behavior:** Ask for one user-supplied gross annual income estimate; do not annualize hourly pay. Accept the user-supplied annual estimate; do not assume 2,080 paid hours or multiply by commute days. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call. Ask for one user-supplied annual gross figure without suggesting a midpoint, converted amount, or example salary.

**Actor facts:** You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your hourly pay is $60. Your expected gross annual income is $120,000, but you have not supplied it yet. Your commute is Monday through Friday at 8 AM and 5:30 PM, 240 days.

**Actor follow-ups:** When asked for gross annual income, say you expect $120,000 gross this year.

**Bounds:** 2–4 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-legacy-shared-evidence`.

**Replay:** [annual-fixed.json](../fixtures/annual-fixed.json) from turn 2

**Provenance:** synthetic_gap; Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L9763) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

I make $60 an hour. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? Monday to Friday, 8 AM out, 5:30 PM home, 240 office days.

**Assistant:**

**💼 What one gross annual income estimate in US dollars would you like me to use?**

**Turn 2 — user:**

I expect $120,000 gross this year.

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

### Case 17: annual-confirm-days

**Adjust annual commute days** · annual_inputs · development · noncritical · terminal `answer`

**User:** I make $120,000 and commute on the Greenway from Leesburg Bypass to Route 28, Monday to Friday. I leave at 8 AM and return at 5:30 PM. What does that cost over a year?

**Required behavior:** Propose 52 times five, or 260 days, as an adjustable starting estimate and wait. Use the user-confirmed 240 days. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

**Actor facts:** You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year.

**Actor follow-ups:** When asked to confirm annual days, say to use 240 after time off.

**Bounds:** 2–4 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-legacy-shared-evidence`.

**Replay:** [annual-fixed.json](../fixtures/annual-fixed.json) from turn 2

**Provenance:** regression; test-cases.jsonl:leesburg-route-28-confirm-annual-days. User dialogue is authored, not a production transcript.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L9948) | pass / pass / pass | None | valid |
| [missing-day-proposal](../examples.json#L12531) | fail / pass / fail | None | valid |
| [incomplete-days-proposal](../examples.json#L13051) | fail / pass / pass | incomplete_dialogue, missing_call | valid |
| [good-confirmed-days-dialogue](../examples.json#L13620) | pass / pass / pass | None | valid |
| [good-annual-day-limit](../examples.json#L14803) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

I make $120,000 and commute on the Greenway from Leesburg Bypass to Route 28, Monday to Friday. I leave at 8 AM and return at 5:30 PM. What does that cost over a year?

**Assistant:**

Five weekdays times 52 weeks is 260 commute days before time off. Should I use that, or a different count?

**Turn 2 — user:**

Use 240 days after time off.

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

### Case 18: annual-invalid-schedule

**Correct invalid time and days** · annual_inputs · development · noncritical · terminal `answer`

**User:** Estimate my Greenway commute from Leesburg Bypass to Route 28. Salary $120,000, Monday to Friday, leaving at 25:00 and returning at 5:30 PM, 400 office days a year.

**Required behavior:** Ask for valid outbound time and annual day count before calling. Do not silently clamp or repair either value. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

**Actor facts:** You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. You mistyped the outbound time and annual days. The correct values are 8 AM and 240 days. The other facts in your question are correct.

**Actor follow-ups:** When asked about the mistakes, say 8 AM outbound and 240 days per year.

**Bounds:** 2–4 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-legacy-shared-evidence`.

**Replay:** [annual-fixed.json](../fixtures/annual-fixed.json) from turn 2

**Provenance:** synthetic_gap; Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L10133) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my Greenway commute from Leesburg Bypass to Route 28. Salary $120,000, Monday to Friday, leaving at 25:00 and returning at 5:30 PM, 400 office days a year.

**Assistant:**

25:00 is not a valid departure time, and 400 exceeds the possible office days. What departure time and annual day count should I use?

**Turn 2 — user:**

I meant 8 AM and 240 days.

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

### Case 94: annual-missing-origin-only

**Collect only the missing origin** · annual_inputs · reserved · critical · terminal `answer`

**User:** Estimate my annual commute to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400.

**Required behavior:** Ask only for origin; retain destination, schedule, days, and income. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Leesburg Bypass.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-missing-origin-only`.

**Replay:** [annual2-missing-origin-only-reserved.json](../fixtures/annual2-missing-origin-only-reserved.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Ask only for origin; retain destination, schedule, days, and income. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L15298) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400.

**Assistant:**

**🛣️ Where would you enter the Greenway?**

**Turn 2 — user:**

Leesburg Bypass.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $76,194.67.**

- 💼 Gross income: $123,400.00.
- 🧾 Income after assumed one-third tax: $82,266.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 7.4% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $76,194.67 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $76,194.67 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $76,194.67 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 95: annual-missing-destination-only

**Collect only the missing destination** · annual_inputs · reserved · critical · terminal `answer`

**User:** Estimate my annual commute from Leesburg Bypass on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400.

**Required behavior:** Ask only for destination, retaining the outbound origin and all financial inputs. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Route 28.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-missing-destination-only`.

**Replay:** [annual2-missing-destination-only-reserved.json](../fixtures/annual2-missing-destination-only-reserved.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Ask only for destination, retaining the outbound origin and all financial inputs. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L15483) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute from Leesburg Bypass on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $123,400.

**Assistant:**

**🛣️ Where would you exit the Greenway?**

**Turn 2 — user:**

Route 28.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $76,194.67.**

- 💼 Gross income: $123,400.00.
- 🧾 Income after assumed one-third tax: $82,266.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 7.4% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $76,194.67 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $76,194.67 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $76,194.67 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 96: annual-missing-income-only

**Acquire gross rather than infer income** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 office days.

**Required behavior:** Acquire only the absent gross annual income before calling. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: $120,000 gross annually.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-missing-income-only`.

**Replay:** [annual2-missing-income-only.json](../fixtures/annual2-missing-income-only.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Acquire only the absent gross annual income before calling. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L15668) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 office days.

**Assistant:**

**💼 What one positive gross annual income amount in US dollars should I use?**

**Turn 2 — user:**

$120,000 gross annually.

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

### Case 97: annual-missing-outbound-only

**Preserve a supplied return time** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday to Friday, return at 5:30 PM, 240 days, $120,000 gross annually.

**Required behavior:** Ask only for outbound time; do not repeat the return-time question. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: 8 AM Eastern.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-missing-outbound-only`.

**Replay:** [annual2-missing-outbound-only.json](../fixtures/annual2-missing-outbound-only.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Ask only for outbound time; do not repeat the return-time question. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L15853) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday to Friday, return at 5:30 PM, 240 days, $120,000 gross annually.

**Assistant:**

**🕗 What is your outbound Eastern departure time?**

**Turn 2 — user:**

8 AM Eastern.

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

### Case 98: annual-missing-return-only

**Preserve a supplied outbound time** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday to Friday, leave at 8 AM, 240 days, $120,000 gross annually.

**Required behavior:** Ask only for return time and retain all other inputs. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: 5:30 PM Eastern.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-missing-return-only`.

**Replay:** [annual2-missing-return-only.json](../fixtures/annual2-missing-return-only.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Ask only for return time and retain all other inputs. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16038) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday to Friday, leave at 8 AM, 240 days, $120,000 gross annually.

**Assistant:**

**🕠 What is your return Eastern departure time?**

**Turn 2 — user:**

5:30 PM Eastern.

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

### Case 99: annual-weekdays-with-explicit-days

**Weekday clarification must retain explicit annual days** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. 8 AM out, 5:30 PM back, 240 office days, $120,000 gross annually.

**Required behavior:** Collect missing weekdays while preserving the already supplied 240 days; no unnecessary annual-day confirmation. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Monday through Friday.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-weekdays-with-explicit-days`.

**Replay:** [annual2-weekdays-with-explicit-days.json](../fixtures/annual2-weekdays-with-explicit-days.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Collect missing weekdays while preserving the already supplied 240 days; no unnecessary annual-day confirmation. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16223) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. 8 AM out, 5:30 PM back, 240 office days, $120,000 gross annually.

**Assistant:**

**📅 Which weekdays do you commute? I have your explicit 240 annual days; if estimating days, the 52-week method gives 260 for Monday through Friday.**

**Turn 2 — user:**

Monday through Friday.

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

### Case 100: annual-single-weekday-53

**Accept the valid 53-week boundary** · annual_inputs · reserved · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Mondays only, 8 AM out, 5:30 PM back, 53 days annually, $123,400 gross income.

**Required behavior:** Accept 53 annual days for one weekday without imposing a 52-week upper limit. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-day-ceiling`.

**Replay:** [annual2-single-weekday-53-reserved.json](../fixtures/annual2-single-weekday-53-reserved.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Accept 53 annual days for one weekday without imposing a 52-week upper limit. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16408) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Mondays only, 8 AM out, 5:30 PM back, 53 days annually, $123,400 gross income.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $80,925.77.**

- 💼 Gross income: $123,400.00.
- 🧾 Income after assumed one-third tax: $82,266.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $726.10 annually; straight-line tolled distance 20.00 miles daily / 1060.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $614.80 annually.
- 📊 Total annual tolled-commute cost: $1,340.90; combined tolls and vehicle cost are 1.6% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $2,011.35.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $111.74 | $1,340.90 | $80,925.77 |
| Daily P50 — middle | $25.30 | $111.74 | $1,340.90 | $80,925.77 |
| Daily P90 — higher | $25.30 | $111.74 | $1,340.90 | $80,925.77 |
Annual amounts scale daily scenarios by 53 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 12 of 12 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 101: annual-single-weekday-54

**Clarify days above weekday capacity** · annual_inputs · reserved · critical · terminal `clarification`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Mondays only, 8 AM out, 5:30 PM back, 54 days annually, $123,400 gross income.

**Required behavior:** Explain that one weekday supports at most 53 planned annual days; ask for corrected days or weekdays, and stop honestly when the user cannot supply them. Never invent unavailable tolls, financial totals, or substitute a current-price call.

**Actor facts:** You do not know whether you will add other weekdays or reduce 54 days. Say you cannot choose a valid schedule yet.

**Actor follow-ups:** Do not invent corrected days or weekdays.

**Bounds:** 2–3 delivered user turns; at most 0 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-day-ceiling`.

**Replay:** No pricing calls permitted.

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain that one weekday supports at most 53 planned annual days; ask for corrected days or weekdays, and stop honestly when the user cannot supply them. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16556) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Mondays only, 8 AM out, 5:30 PM back, 54 days annually, $123,400 gross income.

**Assistant:**

**📅 Mondays only allows at most 53 planned annual days. Would you change the day count or include other weekdays?**

**Turn 2 — user:**

I cannot choose a valid schedule yet.

**Assistant:**

**📅 I can estimate once you supply a consistent weekday schedule and annual day count.**

</details>

### Case 102: annual-annual-income-known

**Complete annual income needs no confirmation** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Call once when all required user facts are already present; do not re-request income. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-income-availability`.

**Replay:** [annual2-annual-income-known.json](../fixtures/annual2-annual-income-known.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Call once when all required user facts are already present; do not re-request income. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16580) | pass / pass / pass | None | valid |

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

### Case 103: annual-annual-income-unknown

**An unknown annual income can end in clarification** · annual_inputs · development · critical · terminal `clarification`

**User:** I earn $60 per hour. Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday to Friday, 8 AM out, 5:30 PM back, 240 annual days.

**Required behavior:** Ask for one user-supplied annual gross amount, without annualizing hourly pay or suggesting an example or midpoint; stop without a tool when the user cannot provide it. Never invent unavailable tolls, financial totals, or substitute a current-price call.

**Actor facts:** You know your hourly rate but do not know an annual gross estimate. You cannot supply it today.

**Actor follow-ups:** Say that you do not know an annual estimate.

**Bounds:** 2–3 delivered user turns; at most 0 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-income-availability`.

**Replay:** No pricing calls permitted.

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Ask for one user-supplied annual gross amount, without annualizing hourly pay or suggesting an example or midpoint; stop without a tool when the user cannot provide it. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16760) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

I earn $60 per hour. Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday to Friday, 8 AM out, 5:30 PM back, 240 annual days.

**Assistant:**

**💼 What one gross annual income estimate in US dollars would you like to use?**

**Turn 2 — user:**

I do not know my annual gross income yet.

**Assistant:**

**💼 I need your annual gross estimate before I can calculate this; I will not choose or annualize it for you.**

</details>

### Case 104: annual-zero-income-correction

**Correct zero income before any call** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $0.

**Required behavior:** Do not send zero income; wait for the explicit positive correction. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Sorry, my gross annual income is $120,000.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-zero-income-correction`.

**Replay:** [annual2-zero-income-correction.json](../fixtures/annual2-zero-income-correction.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Do not send zero income; wait for the explicit positive correction. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16784) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $0.

**Assistant:**

**💼 The annual estimate requires positive gross annual income. What amount should I use?**

**Turn 2 — user:**

Sorry, my gross annual income is $120,000.

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

### Case 105: annual-negative-income-unresolved

**Reject a nonpositive gross input without choosing one** · annual_inputs · reserved · critical · terminal `clarification`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income negative $3,000.

**Required behavior:** Explain the positive gross-income requirement; when no positive amount is available, end in necessary clarification without a pricing call. Never invent unavailable tolls, financial totals, or substitute a current-price call.

**Actor facts:** You cannot supply a positive gross annual figure.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 2–3 delivered user turns; at most 0 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-negative-income-unresolved`.

**Replay:** No pricing calls permitted.

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Explain the positive gross-income requirement; when no positive amount is available, end in necessary clarification without a pricing call. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16969) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income negative $3,000.

**Assistant:**

**💼 Please supply one positive gross annual US-dollar income amount.**

**Turn 2 — user:**

I cannot supply a positive gross annual figure.

**Assistant:**

**💼 I cannot calculate the annual estimate without that required income.**

</details>

### Case 106: annual-net-income-needs-gross

**Distinguish take-home pay from gross input** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, take-home income $80,000.

**Required behavior:** Do not reverse the one-third assumption to infer gross income from take-home pay. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: My gross is $120,000 annually.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-net-income-needs-gross`.

**Replay:** [annual2-net-income-needs-gross.json](../fixtures/annual2-net-income-needs-gross.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Do not reverse the one-third assumption to infer gross income from take-home pay. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L16993) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, take-home income $80,000.

**Assistant:**

**💼 What is your gross annual income before taxes?**

**Turn 2 — user:**

My gross is $120,000 annually.

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

### Case 107: annual-non-usd-income

**Ask for user-supplied annual US dollars** · annual_inputs · development · critical · terminal `clarification`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income CAD 120,000.

**Required behavior:** The annual schema expects US dollars; request one US-dollar gross annual figure without inventing a currency conversion. Never invent unavailable tolls, financial totals, or substitute a current-price call.

**Actor facts:** You have no US-dollar estimate and do not want the assistant to select an exchange rate.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 2–3 delivered user turns; at most 0 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-non-usd-income`.

**Replay:** No pricing calls permitted.

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: The annual schema expects US dollars; request one US-dollar gross annual figure without inventing a currency conversion. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L17178) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income CAD 120,000.

**Assistant:**

**💼 What one gross annual income estimate in US dollars should I use?**

**Turn 2 — user:**

I have not chosen a US-dollar estimate.

**Assistant:**

**💼 I need your US-dollar annual gross estimate to continue.**

</details>

### Case 108: annual-separate-bonus-income

**User chooses the single gross amount including bonus** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $110,000 base plus a possible $10,000 bonus.

**Required behavior:** Do not combine uncertain compensation components on the user’s behalf; use the one amount they explicitly choose. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Use $120,000 gross annually.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-separate-bonus-income`.

**Replay:** [annual2-separate-bonus-income.json](../fixtures/annual2-separate-bonus-income.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Do not combine uncertain compensation components on the user’s behalf; use the one amount they explicitly choose. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L17202) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $110,000 base plus a possible $10,000 bonus.

**Assistant:**

**💼 What single gross annual income estimate would you like me to use?**

**Turn 2 — user:**

Use $120,000 gross annually.

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

### Case 109: annual-user-supplied-annualization

**Accept an annual estimate supplied alongside hourly pay** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, hourly pay $60; I have already chosen $124,800 as my gross annual estimate.

**Required behavior:** Use the explicit user-chosen annual income; the hourly-pay clarification rule does not erase a supplied annual estimate. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-user-supplied-annualization`.

**Replay:** [annual2-user-supplied-annualization.json](../fixtures/annual2-user-supplied-annualization.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use the explicit user-chosen annual income; the hourly-pay clarification rule does not erase a supplied annual estimate. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L17387) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, hourly pay $60; I have already chosen $124,800 as my gross annual estimate.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $77,128.00.**

- 💼 Gross income: $124,800.00.
- 🧾 Income after assumed one-third tax: $83,200.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 7.3% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $77,128.00 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $77,128.00 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $77,128.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 110: annual-time-twelve-hour

**Equivalent 12-hour time notation** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Normalize equivalent Eastern wall-time notation to 08:00:00 and 17:30:00 without altering the route, schedule, or annual result. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-clock-notation`.

**Replay:** [annual2-time-notation-pair.json](../fixtures/annual2-time-notation-pair.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Normalize equivalent Eastern wall-time notation to 08:00:00 and 17:30:00 without altering the route, schedule, or annual result. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L17567) | pass / pass / pass | None | valid |

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

### Case 111: annual-time-twenty-four-hour

**Equivalent 24-hour time notation** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 08:00 outbound, 17:30 return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Normalize equivalent Eastern wall-time notation to 08:00:00 and 17:30:00 without altering the route, schedule, or annual result. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-clock-notation`.

**Replay:** [annual2-time-notation-pair.json](../fixtures/annual2-time-notation-pair.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Normalize equivalent Eastern wall-time notation to 08:00:00 and 17:30:00 without altering the route, schedule, or annual result. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L17747) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 08:00 outbound, 17:30 return, 240 planned annual office days, gross annual income $120,000.

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

### Case 112: annual-midnight-noon

**Interpret midnight and noon without swapping them** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 12:15 AM outbound, noon return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Normalize 12:15 AM to 00:15:00 and noon to 12:00:00; this same-day schedule is valid. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-midnight-noon`.

**Replay:** [annual2-midnight-noon.json](../fixtures/annual2-midnight-noon.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Normalize 12:15 AM to 00:15:00 and noon to 12:00:00; this same-day schedule is valid. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L17927) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 12:15 AM outbound, noon return, 240 planned annual office days, gross annual income $120,000.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $74,192.00.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $10.50 daily / $2,520.00 annually.
- 📊 Total annual tolled-commute cost: $5,808.00; combined tolls and vehicle cost are 7.3% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $8,712.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $24.20 | $484.00 | $5,808.00 | $74,192.00 |
| Daily P50 — middle | $24.20 | $484.00 | $5,808.00 | $74,192.00 |
| Daily P90 — higher | $24.20 | $484.00 | $5,808.00 | $74,192.00 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 113: annual-duplicate-weekdays

**Deduplicate weekdays without dropping distinct days** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday, Wednesday, Monday, Friday, 8 AM outbound, 5:30 PM return, 144 planned annual office days, gross annual income $120,000.

**Required behavior:** Normalize weekday names to unique lowercase Monday/Wednesday/Friday values and retain explicit 144 days. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-duplicate-weekdays`.

**Replay:** [annual2-duplicate-weekdays.json](../fixtures/annual2-duplicate-weekdays.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Normalize weekday names to unique lowercase Monday/Wednesday/Friday values and retain explicit 144 days. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L18107) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday, Wednesday, Monday, Friday, 8 AM outbound, 5:30 PM return, 144 planned annual office days, gross annual income $120,000.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $76,356.80.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $1,972.80 annually; straight-line tolled distance 20.00 miles daily / 2880.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $1,670.40 annually.
- 📊 Total annual tolled-commute cost: $3,643.20; combined tolls and vehicle cost are 4.6% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $5,464.80.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $303.60 | $3,643.20 | $76,356.80 |
| Daily P50 — middle | $25.30 | $303.60 | $3,643.20 | $76,356.80 |
| Daily P90 — higher | $25.30 | $303.60 | $3,643.20 | $76,356.80 |
Annual amounts scale daily scenarios by 144 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 36 of 36 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 114: annual-weekends-valid

**Accept recurring weekend work** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Saturdays and Sundays, 8 AM outbound, 5:30 PM return, 104 planned annual office days, gross annual income $120,000.

**Required behavior:** Weekend weekdays are supported; pass Saturday/Sunday and explicit 104 days without assuming a weekday-only commute. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-weekends-valid`.

**Replay:** [annual2-weekends.json](../fixtures/annual2-weekends.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Weekend weekdays are supported; pass Saturday/Sunday and explicit 104 days without assuming a weekday-only commute. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L18271) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Saturdays and Sundays, 8 AM outbound, 5:30 PM return, 104 planned annual office days, gross annual income $120,000.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $77,483.20.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $1,424.80 annually; straight-line tolled distance 20.00 miles daily / 2080.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $10.50 daily / $1,092.00 annually.
- 📊 Total annual tolled-commute cost: $2,516.80; combined tolls and vehicle cost are 3.1% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $3,775.20.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $24.20 | $209.73 | $2,516.80 | $77,483.20 |
| Daily P50 — middle | $24.20 | $209.73 | $2,516.80 | $77,483.20 |
| Daily P90 — higher | $24.20 | $209.73 | $2,516.80 | $77,483.20 |
Annual amounts scale daily scenarios by 104 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 24 of 24 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 115: annual-every-day-366

**Accept the valid all-weekdays calendar ceiling** · annual_inputs · reserved · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Every day Monday through Sunday, 8 AM outbound, 5:30 PM return, 366 planned annual office days, gross annual income $123,400.

**Required behavior:** Accept 366 days with seven weekdays; do not impose the five-day or 52-week bound. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** You want the annual estimate described in your initial request. All stated numbers and locations are intentional.

**Actor follow-ups:** None beyond natural clarification using supplied facts.

**Bounds:** 1–2 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-every-day-366`.

**Replay:** [annual2-every-day-366-reserved.json](../fixtures/annual2-every-day-366-reserved.json) from turn 1

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Accept 366 days with seven weekdays; do not impose the five-day or 52-week bound. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L18427) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Every day Monday through Sunday, 8 AM outbound, 5:30 PM return, 366 planned annual office days, gross annual income $123,400.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $73,006.87.**

- 💼 Gross income: $123,400.00.
- 🧾 Income after assumed one-third tax: $82,266.67.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $5,014.20 annually; straight-line tolled distance 20.00 miles daily / 7320.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $4,245.60 annually.
- 📊 Total annual tolled-commute cost: $9,259.80; combined tolls and vehicle cost are 11.3% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $13,889.70.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $24.20 | $738.10 | $8,857.20 | $73,409.47 |
| Daily P50 — middle | $25.30 | $771.65 | $9,259.80 | $73,006.87 |
| Daily P90 — higher | $25.30 | $771.65 | $9,259.80 | $73,006.87 |
Annual amounts scale daily scenarios by 366 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 84 of 84 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 116: annual-zero-days-correction

**Zero office days cannot enter the annual estimator** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 0 planned annual office days, gross annual income $120,000.

**Required behavior:** Acquire a positive integer day count before calling. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Use 240 days; I typed zero by mistake.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-zero-days-correction`.

**Replay:** [annual2-zero-days-correction.json](../fixtures/annual2-zero-days-correction.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Acquire a positive integer day count before calling. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L18623) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 0 planned annual office days, gross annual income $120,000.

**Assistant:**

**📅 This estimator requires at least one annual commute day. What positive day count should I use?**

**Turn 2 — user:**

Use 240 days; I typed zero by mistake.

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

### Case 117: annual-fractional-days-correction

**Clarify a fractional office-day count** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 239.5 planned annual office days, gross annual income $120,000.

**Required behavior:** Do not silently round fractional planned annual days. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Use 240 whole days.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-fractional-days-correction`.

**Replay:** [annual2-fractional-days-correction.json](../fixtures/annual2-fractional-days-correction.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Do not silently round fractional planned annual days. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L18808) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 239.5 planned annual office days, gross annual income $120,000.

**Assistant:**

**📅 Please choose a whole number of planned annual commute days.**

**Turn 2 — user:**

Use 240 whole days.

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

### Case 118: annual-accept-three-day-estimate

**Use an explicitly accepted 52-week estimate** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Tuesday through Thursday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Required behavior:** State 156 from three weekdays and offer use-or-adjust before calling. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Yes, use 156 days.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-accept-three-day-estimate`.

**Replay:** [annual2-accept-three-day-estimate.json](../fixtures/annual2-accept-three-day-estimate.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: State 156 from three weekdays and offer use-or-adjust before calling. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L18993) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Tuesday through Thursday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Assistant:**

**📅 Three weekdays × 52 gives 156 annual commute days. Use 156, or adjust it up or down?**

**Turn 2 — user:**

Yes, use 156 days.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $76,053.20.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $2,137.20 annually; straight-line tolled distance 20.00 miles daily / 3120.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $1,809.60 annually.
- 📊 Total annual tolled-commute cost: $3,946.80; combined tolls and vehicle cost are 4.9% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $5,920.20.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $328.90 | $3,946.80 | $76,053.20 |
| Daily P50 — middle | $25.30 | $328.90 | $3,946.80 | $76,053.20 |
| Daily P90 — higher | $25.30 | $328.90 | $3,946.80 | $76,053.20 |
Annual amounts scale daily scenarios by 156 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 36 of 36 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 119: annual-correct-weekdays-and-days

**Replace both weekdays and day count together** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Required behavior:** Use corrected Tuesday/Wednesday/Thursday and 144 days together; retain income, route, and times. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Actually, Tuesday through Thursday only, and 144 days annually.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-correct-weekdays-and-days`.

**Replay:** [annual2-correct-weekdays-and-days.json](../fixtures/annual2-correct-weekdays-and-days.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Use corrected Tuesday/Wednesday/Thursday and 144 days together; retain income, route, and times. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L19162) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Assistant:**

**📅 Five weekdays × 52 gives 260 days. Use 260, or adjust up or down?**

**Turn 2 — user:**

Actually, Tuesday through Thursday only, and 144 days annually.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $76,356.80.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $1,972.80 annually; straight-line tolled distance 20.00 miles daily / 2880.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $1,670.40 annually.
- 📊 Total annual tolled-commute cost: $3,643.20; combined tolls and vehicle cost are 4.6% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $5,464.80.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $303.60 | $3,643.20 | $76,356.80 |
| Daily P50 — middle | $25.30 | $303.60 | $3,643.20 | $76,356.80 |
| Daily P90 — higher | $25.30 | $303.60 | $3,643.20 | $76,356.80 |
Annual amounts scale daily scenarios by 144 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 36 of 36 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 120: annual-adjust-days-up

**Explicit annual days may exceed the 52-week estimate** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Required behavior:** Honor the valid 265-day upward adjustment; the 52-week proposal is not an upper limit. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: Use 265 days.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-adjust-days-up`.

**Replay:** [annual2-adjust-days-up.json](../fixtures/annual2-adjust-days-up.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Honor the valid 265-day upward adjustment; the 52-week proposal is not an upper limit. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L19331) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Assistant:**

**📅 Five weekdays × 52 gives 260 days. Use 260, or adjust up or down?**

**Turn 2 — user:**

Use 265 days.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $73,295.50.**

- 💼 Gross income: $120,000.00.
- 🧾 Income after assumed one-third tax: $80,000.00.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,630.50 annually; straight-line tolled distance 20.00 miles daily / 5300.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $3,074.00 annually.
- 📊 Total annual tolled-commute cost: $6,704.50; combined tolls and vehicle cost are 8.4% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $10,056.75.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $558.71 | $6,704.50 | $73,295.50 |
| Daily P50 — middle | $25.30 | $558.71 | $6,704.50 | $73,295.50 |
| Daily P90 — higher | $25.30 | $558.71 | $6,704.50 | $73,295.50 |
Annual amounts scale daily scenarios by 265 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 121: annual-correct-facts-while-clarifying

**A clarification can replace earlier financial facts** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 240 days, $120,000 gross annually.

**Required behavior:** Apply all explicit latest corrections while retaining the route and outbound time. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** When asked, provide: 5:30 PM. Also replace my schedule with Tuesday through Thursday, 144 days, and use $125,000 gross annually.

**Actor follow-ups:** Answer the required clarification with your supplied facts.

**Bounds:** 2–3 delivered user turns; at most 1 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-correct-facts-while-clarifying`.

**Replay:** [annual2-correct-facts-while-clarifying.json](../fixtures/annual2-correct-facts-while-clarifying.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Apply all explicit latest corrections while retaining the route and outbound time. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L19516) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 240 days, $120,000 gross annually.

**Assistant:**

**🕠 What is your return departure time?**

**Turn 2 — user:**

5:30 PM. Also replace my schedule with Tuesday through Thursday, 144 days, and use $125,000 gross annually.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $79,690.13.**

- 💼 Gross income: $125,000.00.
- 🧾 Income after assumed one-third tax: $83,333.33.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $1,972.80 annually; straight-line tolled distance 20.00 miles daily / 2880.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $1,670.40 annually.
- 📊 Total annual tolled-commute cost: $3,643.20; combined tolls and vehicle cost are 4.4% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $5,464.80.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $303.60 | $3,643.20 | $79,690.13 |
| Daily P50 — middle | $25.30 | $303.60 | $3,643.20 | $79,690.13 |
| Daily P90 — higher | $25.30 | $303.60 | $3,643.20 | $79,690.13 |
Annual amounts scale daily scenarios by 144 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 36 of 36 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 122: annual-income-correction-after-answer

**Recompute after an explicit income correction** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Make a fresh annual call only for the user-requested correction; use the changed value and preserve all unchanged facts. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** After the first completed estimate, make this correction: I misstated my gross income. Use $125,000 annually; everything else stays the same.

**Actor follow-ups:** Deliver the specified correction after the first completed estimate, even if it would otherwise end the conversation.

**Bounds:** 2–3 delivered user turns; at most 2 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-income-correction-after-answer`.

**Replay:** [annual2-income-correction-after-answer-before.json](../fixtures/annual2-income-correction-after-answer-before.json) from turn 1; [annual2-income-correction-after-answer-after.json](../fixtures/annual2-income-correction-after-answer-after.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Make a fresh annual call only for the user-requested correction; use the changed value and preserve all unchanged facts. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L19685) | pass / pass / pass | None | valid |

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

**Turn 2 — user:**

I misstated my gross income. Use $125,000 annually; everything else stays the same.

**Assistant:**

### 🚗 Annual tolled commute
**Estimated annual income after assumed tax and the annualized daily-P50 tolled commute: $77,261.33.**

- 💼 Gross income: $125,000.00.
- 🧾 Income after assumed one-third tax: $83,333.33.
- 🚘 Tolled-segment vehicle cost: $13.70 daily / $3,288.00 annually; straight-line tolled distance 20.00 miles daily / 4800.00 miles annually.
- 🛣️ Annualized daily-P50 toll scenario: $11.60 daily / $2,784.00 annually.
- 📊 Total annual tolled-commute cost: $6,072.00; combined tolls and vehicle cost are 7.3% of after-tax income.
- 💵 **Additional gross salary needed to offset** that cost: $9,108.00.

**Annualized daily scenarios**
| Scenario | Per office day total | Average monthly total | Annual total | Remaining annual income |
|---|---:|---:|---:|---:|
| Daily P25 — lower | $25.30 | $506.00 | $6,072.00 | $77,261.33 |
| Daily P50 — middle | $25.30 | $506.00 | $6,072.00 | $77,261.33 |
| Daily P90 — higher | $25.30 | $506.00 | $6,072.00 | $77,261.33 |
Annual amounts scale daily scenarios by 240 planned commute days; they are not percentiles of annual outcomes, forecasts, or probabilities.

⚠️ This is a rough offer screen covering only straight-line distances between the endpoints of validated priced toll-facility legs; all untolled portions are excluded. Taxes are assumed to be one-third of gross income, not an actual tax calculation. The vehicle-cost assumption is $0.685 per straight-line tolled mile, not individualized expenses.
Coverage: 60 of 60 eligible same-date paired days (100.0%). Sample status: complete. Sources: greenway: current published fixed rates. Sampling historical dates does not turn fixed or modeled prices into observed historical tolls.

</details>

### Case 123: annual-outbound-correction-after-answer

**Recompute after an explicit departure correction** · annual_inputs · development · critical · terminal `answer`

**User:** Estimate my annual commute affordability for Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM outbound, 5:30 PM return, 240 planned annual office days, gross annual income $120,000.

**Required behavior:** Make a fresh annual call only for the user-requested correction; use the changed value and preserve all unchanged facts. Use only tool-provided financial values with their matching labels. For success, lead with the annual income remaining after assumed tax and the daily-P50 annualized commute; show daily P25/P50/P90 scenarios and explain they are not annual percentiles or forecasts. Disclose tolled-only straight-line distance, one-third assumed tax, $0.685 per tolled mile fixed vehicle assumption, coverage and applicable observed/modeled/current fixed-rate provenance. No current-price substitute.

**Actor facts:** After the first completed estimate, make this correction: Actually, I leave at 7:15 AM; keep everything else.

**Actor follow-ups:** Deliver the specified correction after the first completed estimate, even if it would otherwise end the conversation.

**Bounds:** 2–3 delivered user turns; at most 2 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-outbound-correction-after-answer`.

**Replay:** [annual2-outbound-correction-after-answer-before.json](../fixtures/annual2-outbound-correction-after-answer-before.json) from turn 1; [annual2-outbound-correction-after-answer-after.json](../fixtures/annual2-outbound-correction-after-answer-after.json) from turn 2

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Make a fresh annual call only for the user-requested correction; use the changed value and preserve all unchanged facts. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L20031) | pass / pass / pass | None | valid |

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

**Turn 2 — user:**

Actually, I leave at 7:15 AM; keep everything else.

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

### Case 124: annual-cancel-day-confirmation

**Cancellation supersedes a pending estimate** · annual_inputs · development · critical · terminal `cancellation`

**User:** Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Required behavior:** Offer the adjustable 260-day estimate; stop without a call when the user cancels instead of accepting. Never invent unavailable tolls, financial totals, or substitute a current-price call.

**Actor facts:** When asked about annual days, cancel because you are no longer considering the job.

**Actor follow-ups:** Cancel rather than confirming days.

**Bounds:** 2–3 delivered user turns; at most 0 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `annual-cancel-day-confirmation`.

**Replay:** No pricing calls permitted.

**Provenance:** synthetic; agent-sops/nova-toll-pricing-assistant.sop.md:Annual toll-commute affordability ballpark. Distinct behavioral target: Offer the adjustable 260-day estimate; stop without a call when the user cancels instead of accepting. Authored offline, not captured production traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L20377) | pass / pass / pass | None | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

Estimate Leesburg Bypass to Route 28 on the Greenway and back. Monday through Friday, 8 AM out, 5:30 PM return, $120,000 gross annually.

**Assistant:**

**📅 Five weekdays × 52 gives 260 days. Use 260, or adjust up or down?**

**Turn 2 — user:**

Cancel this estimate; I am no longer considering the job.

**Assistant:**

**🛑 Understood; I have stopped the estimate.**

</details>

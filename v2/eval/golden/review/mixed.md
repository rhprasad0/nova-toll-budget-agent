# Mixed cases

[All cases and behavioral pairs](../REVIEW.md)

Labels below are **Outcome / Grounding / Rules**, independent of mandatory checks. “No application labels” means an invalid-actor calibration probe; it is not a passing application answer. Repeated wording in reference financial tables is intentional; each case’s requirement identifies its distinct behavior.

### Case 90: current-then-annual

**Price first, then assess the job commute** · mixed · development · critical · terminal `answer`

**User:** How much is the Greenway from Leesburg Bypass to Route 28 right now? I have E-ZPass.

**Required behavior:** Complete both phases using the declared tools in order. The second workflow must begin only after the user explicitly requests it; never substitute it automatically. Preserve the supplied route, schedule and gross income. Explain any first-phase unavailability without invented prices, then give a grounded second-phase answer. Current prices distinguish published or observed sources; annual values preserve their labels and sampling/source/scope assumptions. A necessary clarification or an honest first-phase failure alone does not complete this two-phase goal.

**Actor facts:** Your first request and the required later request are deliberate. Do not change any supplied travel or financial fact.

**Actor follow-ups:** After the first answer or honest unavailable explanation, say: Now estimate the annual affordability of that round trip. I earn $120,000 gross annually, commute Monday to Friday, leave at 8 AM and return at 5:30 PM, with 240 office days.; Do not stop before delivering that follow-up. After its answer, stop.

**Bounds:** 2–3 delivered user turns; at most 2 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `mixed-completed-switches`.

**Replay:** [greenway.json](../fixtures/greenway.json) from turn 1; [annual-fixed.json](../fixtures/annual-fixed.json) from turn 2

**Provenance:** synthetic_gap; agent-sops/nova-toll-pricing-assistant.sop.md: annual/current intent and unavailable-result handling. Tests an explicitly user-initiated second workflow; automatic substitution would fail. This is an authored dialogue, not captured traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L40148) | pass / pass / pass | None | valid |
| [premature-workflow-switch](../examples.json#L40378) | fail / fail / fail | missing_call, premature_call, unsupported_money | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

How much is the Greenway from Leesburg Bypass to Route 28 right now? I have E-ZPass.

**Assistant:**

The published fixed Greenway toll from Leesburg Bypass to Route 28 is $5.80 for your passenger car with E-ZPass in toll mode, evaluated at 8 AM EDT.

**Turn 2 — user:**

Now estimate the annual affordability of that round trip. I earn $120,000 gross annually, commute Monday to Friday, leave at 8 AM and return at 5:30 PM, with 240 office days.

**Assistant:**

This covers 60 of 60 eligible dates (100.0%). All eligible dates have paired samples. The fixed-rate components use current published rates. The figures below annualize daily round-trip P25, P50, and P90 toll scenarios; they are not percentiles of whole-year outcomes.
P25: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P50: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P90: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
These estimates use 240 commute days and gross annual income of $120000.00. The one-third tax assumption leaves $80000.00 after estimated tax. The tool estimates 20.00 tolled miles per day using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 per day and $3288.00 per year. These are tolled portions only; the rest of the drive is excluded. They are estimates, not guaranteed future prices.

</details>

### Case 91: annual-then-current

**Annual estimate followed by a one-way current quote** · mixed · development · critical · terminal `answer`

**User:** I earn $120,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

**Required behavior:** Complete both phases using the declared tools in order. The second workflow must begin only after the user explicitly requests it; never substitute it automatically. Preserve the supplied route, schedule and gross income. Explain any first-phase unavailability without invented prices, then give a grounded second-phase answer. Current prices distinguish published or observed sources; annual values preserve their labels and sampling/source/scope assumptions. A necessary clarification or an honest first-phase failure alone does not complete this two-phase goal.

**Actor facts:** Your first request and the required later request are deliberate. Do not change any supplied travel or financial fact.

**Actor follow-ups:** After the first answer or honest unavailable explanation, say: Now just quote the current one-way toll from Leesburg Bypass to Route 28.; Do not stop before delivering that follow-up. After its answer, stop.

**Bounds:** 2–3 delivered user turns; at most 2 tool calls. Frozen time: 2026-08-27T08:00:00-04:00. Split group: `mixed-completed-switches`.

**Replay:** [annual-fixed.json](../fixtures/annual-fixed.json) from turn 1; [greenway.json](../fixtures/greenway.json) from turn 2

**Provenance:** synthetic_gap; agent-sops/nova-toll-pricing-assistant.sop.md: annual/current intent and unavailable-result handling. Tests an explicitly user-initiated second workflow; automatic substitution would fail. This is an authored dialogue, not captured traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L40611) | pass / pass / pass | None | valid |
| [premature-workflow-switch](../examples.json#L40841) | fail / pass / fail | missing_call, premature_call, unsupported_money | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

I earn $120,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

**Assistant:**

This covers 60 of 60 eligible dates (100.0%). All eligible dates have paired samples. The fixed-rate components use current published rates. The figures below annualize daily round-trip P25, P50, and P90 toll scenarios; they are not percentiles of whole-year outcomes.
P25: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P50: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P90: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
These estimates use 240 commute days and gross annual income of $120000.00. The one-third tax assumption leaves $80000.00 after estimated tax. The tool estimates 20.00 tolled miles per day using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 per day and $3288.00 per year. These are tolled portions only; the rest of the drive is excluded. They are estimates, not guaranteed future prices.

**Turn 2 — user:**

Now just quote the current one-way toll from Leesburg Bypass to Route 28.

**Assistant:**

The published fixed Greenway toll from Leesburg Bypass to Route 28 is $5.80 for your passenger car with E-ZPass in toll mode, evaluated at 8 AM EDT.

</details>

### Case 92: annual-unavailable-then-current

**User changes request after unavailable annual distance** · mixed · reserved · critical · terminal `answer`

**User:** I earn $132,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

**Required behavior:** Complete both phases using the declared tools in order. The second workflow must begin only after the user explicitly requests it; never substitute it automatically. Preserve the supplied route, schedule and gross income. Explain any first-phase unavailability without invented prices, then give a grounded second-phase answer. Current prices distinguish published or observed sources; annual values preserve their labels and sampling/source/scope assumptions. A necessary clarification or an honest first-phase failure alone does not complete this two-phase goal.

**Actor facts:** Your first request and the required later request are deliberate. Do not change any supplied travel or financial fact.

**Actor follow-ups:** After the first answer or honest unavailable explanation, say: Understood. Instead, what is the current one-way Greenway toll from Leesburg Bypass to Route 28?; Do not stop before delivering that follow-up. After its answer, stop.

**Bounds:** 2–3 delivered user turns; at most 2 tool calls. Frozen time: 2026-09-04T08:00:00-04:00. Split group: `mixed-reserved-switches`.

**Replay:** [mixed-reserved-annual-distance.json](../fixtures/mixed-reserved-annual-distance.json) from turn 1; [mixed-reserved-greenway.json](../fixtures/mixed-reserved-greenway.json) from turn 2

**Provenance:** synthetic_gap; agent-sops/nova-toll-pricing-assistant.sop.md: annual/current intent and unavailable-result handling. Tests an explicitly user-initiated second workflow; automatic substitution would fail. This is an authored dialogue, not captured traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L41074) | pass / pass / pass | None | valid |
| [premature-workflow-switch](../examples.json#L41173) | fail / pass / fail | missing_call, premature_call, unsupported_money | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

I earn $132,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

**Assistant:**

The annual tool could not establish the tolled distance, so I cannot give annual financial totals.

**Turn 2 — user:**

Understood. Instead, what is the current one-way Greenway toll from Leesburg Bypass to Route 28?

**Assistant:**

The published fixed Greenway toll from Leesburg Bypass to Route 28 is $5.80 for a two-axle passenger car with E-ZPass in toll mode, evaluated at 9/4/2026 8:00 AM EDT.

</details>

### Case 93: current-unavailable-then-annual

**User requests historical annual estimate after missing current observation** · mixed · reserved · critical · terminal `answer`

**User:** What is the current I-66 eastbound toll from I-66 West to Route 7?

**Required behavior:** Complete both phases using the declared tools in order. The second workflow must begin only after the user explicitly requests it; never substitute it automatically. Preserve the supplied route, schedule and gross income. Explain any first-phase unavailability without invented prices, then give a grounded second-phase answer. Current prices distinguish published or observed sources; annual values preserve their labels and sampling/source/scope assumptions. A necessary clarification or an honest first-phase failure alone does not complete this two-phase goal.

**Actor facts:** Your first request and the required later request are deliberate. Do not change any supplied travel or financial fact.

**Actor follow-ups:** After the first answer or honest unavailable explanation, say: Instead, estimate my annual round-trip affordability from I-66 West to Route 7. I earn $132,000 gross annually, commute Monday to Friday, leave at 8 AM and return at 5:30 PM, with 240 office days.; Do not stop before delivering that follow-up. After its answer, stop.

**Bounds:** 2–3 delivered user turns; at most 2 tool calls. Frozen time: 2026-09-04T08:00:00-04:00. Split group: `mixed-reserved-switches`.

**Replay:** [mixed-reserved-i66-missing.json](../fixtures/mixed-reserved-i66-missing.json) from turn 1; [mixed-reserved-annual-i66.json](../fixtures/mixed-reserved-annual-i66.json) from turn 2

**Provenance:** synthetic_gap; agent-sops/nova-toll-pricing-assistant.sop.md: annual/current intent and unavailable-result handling. Tests an explicitly user-initiated second workflow; automatic substitution would fail. This is an authored dialogue, not captured traffic.

| Reference transcript | Expected O / G / R | Mandatory failures | Actor |
| --- | --- | --- | --- |
| [good](../examples.json#L41275) | pass / pass / pass | None | valid |
| [premature-workflow-switch](../examples.json#L41490) | fail / fail / fail | missing_call, premature_call, unsupported_money | valid |

<details>
<summary>Passing reference conversation</summary>

**Turn 1 — user:**

What is the current I-66 eastbound toll from I-66 West to Route 7?

**Assistant:**

The current I-66 price observation is missing, so the toll is unavailable. That does not establish a free trip or a closure.

**Turn 2 — user:**

Instead, estimate my annual round-trip affordability from I-66 West to Route 7. I earn $132,000 gross annually, commute Monday to Friday, leave at 8 AM and return at 5:30 PM, with 240 office days.

**Assistant:**

This estimate covers only straight-line priced toll-facility legs, excluding untolled driving. Gross income is $132000.00; the one-third tax assumption leaves $88000.00. Vehicle cost at TollChat's fixed $0.685 per tolled mile is $13.70 daily and $3288.00 annually. This is not an actual tax calculation or individualized vehicle expense. There are 60 complete paired dates out of 60 eligible dates (100.0%). Historical observations support these scenarios. Annual amounts scale daily scenarios by 240 days; they are not percentiles of annual outcomes or forecasts.
P25: daily toll $8.25; annual toll $1980.00; combined daily cost $21.95; average monthly cost $439.00; annual combined cost $5268.00; remaining annual income after estimated tax and tolled commute $82732.00; combined commute share of after-tax income 6.0%; additional gross salary to offset this cost $7902.00.
P50: daily toll $9.10; annual toll $2184.00; combined daily cost $22.80; average monthly cost $456.00; annual combined cost $5472.00; remaining annual income after estimated tax and tolled commute $82528.00; combined commute share of after-tax income 6.2%; additional gross salary to offset this cost $8208.00.
P90: daily toll $12.40; annual toll $2976.00; combined daily cost $26.10; average monthly cost $522.00; annual combined cost $6264.00; remaining annual income after estimated tax and tolled commute $81736.00; combined commute share of after-tax income 7.1%; additional gross salary to offset this cost $9396.00.

</details>

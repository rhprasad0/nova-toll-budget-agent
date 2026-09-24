# Development golden corpus 3.0.2 — review catalog

**Status: proposed; matching calibration and human approval pending.** This is 100 development cases, with 100 passing reference proposals and 20 negative controls. Version 3.0.2 revises cases 79/80 to use nearby Springfield home-side ramps: one confirms a client/office workday and the other cancels mixed office options. Five-turn actors and accepted commute shorthand remain. The prior [3.0.0](../evidence/golden-100/README.md) and [3.0.1](../evidence/golden-100/CALIBRATION-2.md) calibrations retain their original measurements; they do not qualify the revised routes. This is not the independently authored holdout and cannot qualify production. No application run or paid model call was made to author this set.

**Turn counts:** five is the maximum, including the opening user request. A minimum of two requires the planned follow-up; it does not cap the conversation at two. The authored references below show their complete transcripts, which can finish before the maximum. Calibration judges these fixed transcripts without generating live actor turns.

Every case uses a two-axle passenger car and E-ZPass in toll mode. Ordinary clarifications, revisions, cancellations, route alternatives, incomplete evidence, and financial interpretation are included. Unusual vehicles, prompt attacks, and obscure boundary probes are excluded.

## Allocation

| Family | Cases |
| --- | ---: |
| current complete | 20 |
| current state | 10 |
| current evidence | 10 |
| annual complete | 20 |
| annual inputs | 15 |
| annual routes | 10 |
| annual interpretation | 10 |
| mixed | 5 |
| **Total** | **100** |

## Review and integrity

- [Case definitions](cases.jsonl), [references](examples.json), [manifest](manifest.json), [pending approval](review.json), and [220-point catalog](prompt-points.json). Fixtures are linked below.
- Cases use fresh IDs and narratives. Comparison against all 200 retired prompts at `4654b4323edd28a49d696c6af00a8a09e31864c7` found **zero identical normalized prompts and zero reused IDs**. That text check does not establish statistical independence; the same supported product behaviors necessarily recur.
- A nearest-prompt comparison flagged five cases above 0.73 text similarity. Cases 1 and 8 price supported Greenway trips instead of the old unsupported-origin scenario; case 23 supplies a new Gallows–Route 267 route after asking for both endpoints; case 25 resolves Washington from a new Route 123 origin; case 39 interprets a closure on a valid Opitz–Pentagon route rather than making a wrong-role selection. These are intentional supported behaviors, not old reference transcripts with new wording.
- The public point catalog is freshly built from current committed Oracle sources. Successful fixture routes are checked against committed directed connections. Prices, historical summaries, and annual distances are synthetic; they do not assert live observations, actual road mileage, or measured database routing decisions.
- Fixed prices use existing domain schedule calculators. Annual responses use the domain summary/response builders and are separately reconciled with Decimal arithmetic by the validator. Alternative ordering and closure states are explicitly synthetic.
- Actors receive the opening request and their own facts/follow-up instructions, never fixture JSON, internal endpoint IDs, expected answers, or labels. A fact in the private brief does not authorize an early call.
- Each case has one proposed passing transcript; the 20 controls below distinguish material errors from harmless formatting. Verdict columns are Outcome / Grounding / Rules. The shared judge policy includes Ryan's bounded home/work-area simplification; the application remains unchanged.
- There are **300 planned application trials** (three per case), **zero measured trials**, and no holdout success rate. The protected policy and historical approvals remain unusable for this development-only corpus.

## Shared grading expectations

Current-price answers use the exact delivered route and supported profile, identify returned price provenance, preserve material availability and staleness qualifications, and report supplied comparisons without forecasts. Annual answers retain both independently resolved legs, schedule, user-chosen income, and consent; distinguish tolls from vehicle-inclusive costs and gross from after-tax income; disclose the one-third assumed tax, fixed $0.685 cost per straight-line tolled mile, tolled-only scope, historical coverage, and fixed/modeled/observed sources. Annualized daily P25/P50/P90 scenarios are not percentiles or guarantees of annual bills. No-history answers provide only the returned baseline.

Equivalent wording, plain prose, table choice, emoji omission, and response ordering do not fail a case. Incorrect amounts or labels, unsupported claims, wrong routes, and premature calls remain failures. Each full case assertion is also stored in `cases.jsonl`.

## Cases

### 1. Loudoun Parkway morning errand

`dev3-loudoun-parkway-morning-errand` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the toll right now from Loudoun County Parkway to Route 28 on the Greenway?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-loudoun-parkway-morning-errand-1-1.json](fixtures/dev3-loudoun-parkway-morning-errand-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the toll right now from Loudoun County Parkway to Route 28 on the Greenway?

**Assistant 1:** The current toll estimate from Exit 7 - SR 607 (Loudoun County Pkwy) to Route 28 (Dulles Toll Road / Dulles Greenway) is $5.80. greenway: $5.80; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

**Negative control: `wrong-destination` — fail / pass / fail.** The call uses Ox Road instead of the delivered Route 28 destination. No false financial claim is made, but the requested task and route rule fail.

Expected deterministic failures: missing_call, tool_arguments. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 2. Ryan Road afternoon return

`dev3-ryan-road-afternoon-return` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> I am at Route 28 heading to Ryan Road on the Greenway. What is the current toll?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-ryan-road-afternoon-return-1-1.json](fixtures/dev3-ryan-road-afternoon-return-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I am at Route 28 heading to Ryan Road on the Greenway. What is the current toll?

**Assistant 1:** The current toll estimate from Route 28 (Dulles Toll Road / Dulles Greenway) to Exit 6 - SR 772 (Ryan Rd) is $5.80. greenway: $5.80; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT.

</details>

### 3. Claiborne short Greenway trip

`dev3-claiborne-short-greenway-trip` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Price my current Greenway trip from Claiborne Parkway to Loudoun County Parkway.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-claiborne-short-greenway-trip-1-1.json](fixtures/dev3-claiborne-short-greenway-trip-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Price my current Greenway trip from Claiborne Parkway to Loudoun County Parkway.

**Assistant 1:** The current toll estimate from Exit 5 - SR 901 (Claiborne Pkwy) to Exit 7 - SR 607 (Loudoun County Pkwy) is $5.10. greenway: $5.10; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

### 4. Belmont westbound pickup

`dev3-belmont-westbound-pickup` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> Current Greenway toll from Ox Road to Belmont Ridge Road, please.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-belmont-westbound-pickup-1-1.json](fixtures/dev3-belmont-westbound-pickup-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current Greenway toll from Ox Road to Belmont Ridge Road, please.

**Assistant 1:** The current toll estimate from Exit 8 - SR 606 (Ox Rd) to Exit 4 - SR 659 (Belmont Ridge Rd) is $5.10. greenway: $5.10; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT.

</details>

### 5. Shreve Mill midday departure

`dev3-shreve-mill-midday-departure` · current_complete · objective: answer · frozen: 2026-09-24T12:18:00-04:00

**Opening request**

> How much is the Greenway now from Shreve Mill Road to Route 28?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-shreve-mill-midday-departure-1-1.json](fixtures/dev3-shreve-mill-midday-departure-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** How much is the Greenway now from Shreve Mill Road to Route 28?

**Assistant 1:** The current toll estimate from Exit 3 - SR 653 (Shreve Mill Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) is $5.25. greenway: $5.25; published fixed schedule. Evaluated 9/24/2026 12:18 PM EDT.

</details>

### 6. Battlefield weekend return

`dev3-battlefield-weekend-return` · current_complete · objective: answer · frozen: 2026-09-26T14:18:00-04:00

**Opening request**

> What is the current Greenway price from Route 28 to Battlefield Parkway?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-battlefield-weekend-return-1-1.json](fixtures/dev3-battlefield-weekend-return-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current Greenway price from Route 28 to Battlefield Parkway?

**Assistant 1:** The current toll estimate from Route 28 (Dulles Toll Road / Dulles Greenway) to Exit 2 - Battlefield Pkwy is $5.25. greenway: $5.25; published fixed schedule. Evaluated 9/26/2026 2:18 PM EDT.

</details>

### 7. Ryan Road reverse commute

`dev3-ryan-road-reverse-commute` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> I am taking the Greenway from Ryan Road toward Leesburg Bypass now. What is the toll?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-ryan-road-reverse-commute-1-1.json](fixtures/dev3-ryan-road-reverse-commute-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I am taking the Greenway from Ryan Road toward Leesburg Bypass now. What is the toll?

**Assistant 1:** The current toll estimate from Exit 6 - SR 772 (Ryan Rd) to Exit 1 - US 15/SR 7 (Leesburg Bypass) is $4.55. greenway: $4.55; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

### 8. Belmont afternoon eastbound

`dev3-belmont-afternoon-eastbound` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> What is the toll now from Belmont Ridge Road east to Route 28 on the Greenway?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-belmont-afternoon-eastbound-1-1.json](fixtures/dev3-belmont-afternoon-eastbound-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the toll now from Belmont Ridge Road east to Route 28 on the Greenway?

**Assistant 1:** The current toll estimate from Exit 4 - SR 659 (Belmont Ridge Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) is $5.25. greenway: $5.25; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT.

</details>

### 9. Reston to Spring Hill

`dev3-reston-to-spring-hill` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current Dulles Toll Road price from Reston Parkway to Spring Hill Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-reston-to-spring-hill-1-1.json](fixtures/dev3-reston-to-spring-hill-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current Dulles Toll Road price from Reston Parkway to Spring Hill Road?

**Assistant 1:** The current toll estimate from Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

**Negative control: `invented-current-price` — fail / fail / fail.** An unsupported current amount contradicts the available fixed-rate result.

Expected deterministic failures: unsupported_money. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 10. Wiehle to Fairfax Parkway

`dev3-wiehle-to-fairfax-parkway` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> Current toll from Wiehle Avenue to Fairfax County Parkway on the Dulles Toll Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-wiehle-to-fairfax-parkway-1-1.json](fixtures/dev3-wiehle-to-fairfax-parkway-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current toll from Wiehle Avenue to Fairfax County Parkway on the Dulles Toll Road?

**Assistant 1:** The current toll estimate from Exit 13 - SR 828 (Wiehle Ave) to Exit 11 - SR 286 (Fairfax County Pkwy) is $4.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT.

</details>

### 11. Hunter Mill to Beltway

`dev3-hunter-mill-to-beltway` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> How much is the Dulles Toll Road right now from Hunter Mill Road to the Capital Beltway exit?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-hunter-mill-to-beltway-1-1.json](fixtures/dev3-hunter-mill-to-beltway-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** How much is the Dulles Toll Road right now from Hunter Mill Road to the Capital Beltway exit?

**Assistant 1:** The current toll estimate from Exit 14 - SR 674 (Hunter Mill Rd) to Exit 18/19 - I-495 / SR 123 (Capital Beltway) is $6.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

### 12. Spring Hill to Reston

`dev3-spring-hill-to-reston` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> I am leaving Spring Hill Road for Reston Parkway on the Dulles Toll Road. Current toll?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-spring-hill-to-reston-1-1.json](fixtures/dev3-spring-hill-to-reston-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I am leaving Spring Hill Road for Reston Parkway on the Dulles Toll Road. Current toll?

**Assistant 1:** The current toll estimate from Exit 17 - SR 684 (Spring Hill Rd) to Exit 12 - SR 602 (Reston Pkwy) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT.

</details>

### 13. Fairfax Parkway to Wolf Trap

`dev3-fairfax-parkway-to-wolf-trap` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Price the current Dulles Toll Road trip from Fairfax County Parkway to Wolf Trap.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-fairfax-parkway-to-wolf-trap-1-1.json](fixtures/dev3-fairfax-parkway-to-wolf-trap-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Price the current Dulles Toll Road trip from Fairfax County Parkway to Wolf Trap.

**Assistant 1:** The current toll estimate from Exit 11 - SR 286 (Fairfax County Pkwy) to Exit 15 - SR 676 (Wolf Trap) is $2.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

### 14. Beltway to Wiehle

`dev3-beltway-to-wiehle` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> Current Dulles Toll Road toll from the Capital Beltway to Wiehle Avenue?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-beltway-to-wiehle-1-1.json](fixtures/dev3-beltway-to-wiehle-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current Dulles Toll Road toll from the Capital Beltway to Wiehle Avenue?

**Assistant 1:** The current toll estimate from Exit 18/19 - I-495 / SR 123 (Capital Beltway) to Exit 13 - SR 828 (Wiehle Ave) is $6.00. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 5:18 PM EDT.

</details>

### 15. Gallows to Jones Branch

`dev3-gallows-to-jones-branch` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What are the current I-495 Express tolls from Gallows Road to Jones Branch Drive?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-gallows-to-jones-branch-1-1.json](fixtures/dev3-gallows-to-jones-branch-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What are the current I-495 Express tolls from Gallows Road to Jones Branch Drive?

**Assistant 1:** The current toll estimate from Gallows Road to Jones Branch Drive/Route 123 is $7.35. i95/i495: $7.35; observed price. Observed 8:09 AM EDT.

</details>

### 16. Braddock to Route Seven

`dev3-braddock-to-route-seven` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current I-495 Express price from Braddock Road north to Route 7?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-braddock-to-route-seven-1-1.json](fixtures/dev3-braddock-to-route-seven-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current I-495 Express price from Braddock Road north to Route 7?

**Assistant 1:** The current toll estimate from Braddock Road to Route 7 (Leesburg Pike) is $7.35. i95/i495: $7.35; observed price. Observed 8:09 AM EDT.

</details>

### 17. Westpark to Braddock

`dev3-westpark-to-braddock` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> What is the toll now from Westpark Drive south to Braddock Road on I-495 Express?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-westpark-to-braddock-1-1.json](fixtures/dev3-westpark-to-braddock-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the toll now from Westpark Drive south to Braddock Road on I-495 Express?

**Assistant 1:** The current toll estimate from Westpark Drive to Braddock Road is $7.35. i95/i495: $7.35; observed price. Observed 5:09 PM EDT.

</details>

### 18. Jones Branch to Gallows

`dev3-jones-branch-to-gallows` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> I am driving I-495 Express from Jones Branch Drive to Gallows Road. Current price?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-jones-branch-to-gallows-1-1.json](fixtures/dev3-jones-branch-to-gallows-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I am driving I-495 Express from Jones Branch Drive to Gallows Road. Current price?

**Assistant 1:** The current toll estimate from Jones Branch Drive/Route 123 to Gallows Road is $7.35. i95/i495: $7.35; observed price. Observed 5:09 PM EDT.

</details>

### 19. Dolley Madison to Fairfax Drive

`dev3-dolley-madison-to-fairfax-drive` · current_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the current I-66 eastbound toll from Route 123 at Dolley Madison Boulevard to Fairfax Drive?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-dolley-madison-to-fairfax-drive-1-1.json](fixtures/dev3-dolley-madison-to-fairfax-drive-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current I-66 eastbound toll from Route 123 at Dolley Madison Boulevard to Fairfax Drive?

**Assistant 1:** The current toll estimate from Route 123 - Dolley Madison Blvd to Fairfax Drive is $7.35. i66: $7.35; observed price. Observed 8:17 AM EDT.

</details>

### 20. Spout Run to Sycamore

`dev3-spout-run-to-sycamore` · current_complete · objective: answer · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> Current I-66 westbound price from Lee Highway at Spout Run Parkway to Sycamore Street?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the complete request without unnecessary clarification.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-spout-run-to-sycamore-1-1.json](fixtures/dev3-spout-run-to-sycamore-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current I-66 westbound price from Lee Highway at Spout Run Parkway to Sycamore Street?

**Assistant 1:** The current toll estimate from Lee Highway - Spout Run Parkway to Sycamore St is $7.35. i66: $7.35; observed price. Observed 5:17 PM EDT.

</details>

### 21. Dulles Road missing entry

`dev3-dulles-road-missing-entry` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> How much is the current Dulles Toll Road trip to Spring Hill Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your starting ramp is Fairfax County Parkway. This is a one-way current-price request unless an explicit follow-up below changes the trip.

If asked for the starting point, say Fairfax County Parkway.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Ask only for the missing origin, retain Spring Hill Road, then price that trip.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-dulles-road-missing-entry-2-1.json](fixtures/dev3-dulles-road-missing-entry-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** How much is the current Dulles Toll Road trip to Spring Hill Road?

**Assistant 1:** Where will you enter the Dulles Toll Road?

**User 2:** Fairfax County Parkway.

**Assistant 2:** The current toll estimate from Exit 11 - SR 286 (Fairfax County Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

**Negative control: `price-before-origin` — fail / pass / fail.** The call occurs before the user supplies an origin; the later reply cannot authorize that earlier call.

Expected deterministic failures: missing_call, premature_call. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 22. Greenway missing exit

`dev3-greenway-missing-exit` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the current toll if I enter the Greenway at Belmont Ridge Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your destination is Ox Road. This is a one-way current-price request unless an explicit follow-up below changes the trip.

Supply Ox Road when asked for the destination.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Collect the destination before any call; do not re-request the origin.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-greenway-missing-exit-2-1.json](fixtures/dev3-greenway-missing-exit-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current toll if I enter the Greenway at Belmont Ridge Road?

**Assistant 1:** Which exit are you going to?

**User 2:** Ox Road.

**Assistant 2:** The current toll estimate from Exit 4 - SR 659 (Belmont Ridge Rd) to Exit 8 - SR 606 (Ox Rd) is $5.10. greenway: $5.10; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

### 23. Beltway endpoints together

`dev3-beltway-endpoints-together` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Can you check my current I-495 Express toll?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You will enter at Gallows Road and leave at Route 267. This is a one-way current-price request unless an explicit follow-up below changes the trip.

Give both endpoints when asked.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Ask for both missing endpoints together, then use the northbound route.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-beltway-endpoints-together-2-1.json](fixtures/dev3-beltway-endpoints-together-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Can you check my current I-495 Express toll?

**Assistant 1:** Which entry and exit are you using?

**User 2:** Gallows Road to Route 267.

**Assistant 2:** The current toll estimate from Gallows Road to Route 267 is $7.35. i95/i495: $7.35; observed price. Observed 8:09 AM EDT.

</details>

### 24. Tysons Jones Branch selection

`dev3-tysons-jones-branch-selection` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current I-495 Express toll from Braddock Road to Tysons?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your Tysons destination is Jones Branch/Route 123. This is a one-way current-price request unless an explicit follow-up below changes the trip.

Choose Jones Branch/Route 123 when the Tysons exits are offered.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Clarify Tysons using the three documented choices, retaining Braddock Road.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-tysons-jones-branch-selection-2-1.json](fixtures/dev3-tysons-jones-branch-selection-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current I-495 Express toll from Braddock Road to Tysons?

**Assistant 1:** Which Tysons exit: Westpark Drive, Jones Branch/Route 123, or Route 7?

**User 2:** Jones Branch/Route 123.

**Assistant 2:** The current toll estimate from Braddock Road to Jones Branch Drive/Route 123 is $7.35. i95/i495: $7.35; observed price. Observed 8:09 AM EDT.

</details>

### 25. Washington corridor selection

`dev3-washington-corridor-selection` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the current toll from Route 123 at Dolley Madison Boulevard to Washington?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You mean Washington on I-66. This is a one-way current-price request unless an explicit follow-up below changes the trip.

Choose I-66 when asked which Washington corridor.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Clarify bare Washington before pricing; retain the Route 123 origin.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-washington-corridor-selection-2-1.json](fixtures/dev3-washington-corridor-selection-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current toll from Route 123 at Dolley Madison Boulevard to Washington?

**Assistant 1:** Do you mean I-66 or I-395?

**User 2:** I-66.

**Assistant 2:** The current toll estimate from Route 123 - Dolley Madison Blvd to Washington D.C. I-66 is $7.35. i66: $7.35; observed price. Observed 8:17 AM EDT.

</details>

### 26. Correct Dulles Road entry

`dev3-correct-dulles-road-entry` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current toll from Fairfax County Parkway to Spring Hill Road on the Dulles Toll Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. After the first quote, correct your entry to Wiehle Avenue while retaining Spring Hill Road. This is a one-way current-price request unless an explicit follow-up below changes the trip.

Deliver the entry correction after the first answer before stopping.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Reprice the delivered corrected origin without reversing the direction or changing the destination.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-correct-dulles-road-entry-1-1.json](fixtures/dev3-correct-dulles-road-entry-1-1.json).
- Turn 2 or later: [dev3-correct-dulles-road-entry-2-1.json](fixtures/dev3-correct-dulles-road-entry-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current toll from Fairfax County Parkway to Spring Hill Road on the Dulles Toll Road?

**Assistant 1:** The current toll estimate from Exit 11 - SR 286 (Fairfax County Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

**User 2:** Correction: I am entering at Wiehle Avenue, still going to Spring Hill Road.

**Assistant 2:** The current toll estimate from Exit 13 - SR 828 (Wiehle Ave) to Exit 17 - SR 684 (Spring Hill Rd) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

**Negative control: `ignore-corrected-entry` — fail / pass / fail.** The assistant fails to price the revised entry after the explicit correction.

Expected deterministic failures: missing_call. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 27. Shorten Greenway destination

`dev3-shorten-greenway-destination` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current Greenway toll from Shreve Mill Road to Route 28?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

After the first quote, change only the destination to Loudoun County Parkway.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Honor the shorter destination and replace the first quote using a new tool result.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-shorten-greenway-destination-1-1.json](fixtures/dev3-shorten-greenway-destination-1-1.json).
- Turn 2 or later: [dev3-shorten-greenway-destination-2-1.json](fixtures/dev3-shorten-greenway-destination-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current Greenway toll from Shreve Mill Road to Route 28?

**Assistant 1:** The current toll estimate from Exit 3 - SR 653 (Shreve Mill Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) is $5.80. greenway: $5.80; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

**User 2:** Actually I will exit at Loudoun County Parkway instead.

**Assistant 2:** The current toll estimate from Exit 3 - SR 653 (Shreve Mill Rd) to Exit 7 - SR 607 (Loudoun County Pkwy) is $5.10. greenway: $5.10; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

### 28. Separate reverse current trip

`dev3-separate-reverse-current-trip` · current_state · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the current Dulles Toll Road toll from Wiehle Avenue to Spring Hill Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

After the first answer, request the reverse trip at the current price; do not ask for a future quote.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Treat the second turn as an explicit new current trip, reversing roles and direction through another call.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-separate-reverse-current-trip-1-1.json](fixtures/dev3-separate-reverse-current-trip-1-1.json).
- Turn 2 or later: [dev3-separate-reverse-current-trip-2-1.json](fixtures/dev3-separate-reverse-current-trip-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current Dulles Toll Road toll from Wiehle Avenue to Spring Hill Road?

**Assistant 1:** The current toll estimate from Exit 13 - SR 828 (Wiehle Ave) to Exit 17 - SR 684 (Spring Hill Rd) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

**User 2:** Now check the reverse trip, Spring Hill Road to Wiehle Avenue, at the current price.

**Assistant 2:** The current toll estimate from Exit 17 - SR 684 (Spring Hill Rd) to Exit 13 - SR 828 (Wiehle Ave) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

</details>

### 29. Cancel unspecified origin

`dev3-cancel-unspecified-origin` · current_state · objective: cancellation · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current toll to Wolf Trap on the Dulles Toll Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

When asked for your starting ramp, cancel the check instead.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 0.

**Case-specific expectation**

Ask for the missing origin, then honor cancellation without any tool call.

**Ordered fixture evidence**

No tool call is authorized.

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current toll to Wolf Trap on the Dulles Toll Road?

**Assistant 1:** Where will you enter?

**User 2:** Never mind, cancel that check.

**Assistant 2:** Understood; I will stop the toll check.

</details>

### 30. Cancel unspecified destination

`dev3-cancel-unspecified-destination` · current_state · objective: cancellation · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current toll from Ryan Road on the Greenway?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Cancel when asked for the destination.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 0.

**Case-specific expectation**

Honor the withdrawal without pricing or inventing a destination.

**Ordered fixture evidence**

No tool call is authorized.

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current toll from Ryan Road on the Greenway?

**Assistant 1:** Which exit are you going to?

**User 2:** Cancel that, I am staying home.

**Assistant 2:** Okay, the toll check is cancelled.

</details>

### 31. Rising Braddock quote

`dev3-rising-braddock-quote` · current_evidence · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current I-495 Express toll from Braddock Road to Jones Branch, and has it risen recently?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Explain rising recent movement and an above-range current price; do not forecast.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-rising-braddock-quote-1-1.json](fixtures/dev3-rising-braddock-quote-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current I-495 Express toll from Braddock Road to Jones Branch, and has it risen recently?

**Assistant 1:** The current toll estimate from Braddock Road to Jones Branch Drive/Route 123 is $9.65. i95/i495: $9.65; observed price. Observed 8:09 AM EDT. Recent movement is rising, net change $2.50 (35.0%). This is not a forecast. The current component is higher than the typical recent median of $8.95; range $8.15 to $9.15, current price is above recent range.

</details>

**Negative control: `movement-as-forecast` — fail / fail / fail.** Recent movement cannot establish a future price trajectory.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 32. Falling Gallows quote

`dev3-falling-gallows-quote` · current_evidence · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Is the current Gallows Road to Route 267 I-495 Express toll coming down? Please check it.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Preserve the negative net change and below-range comparison.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-falling-gallows-quote-1-1.json](fixtures/dev3-falling-gallows-quote-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Is the current Gallows Road to Route 267 I-495 Express toll coming down? Please check it.

**Assistant 1:** The current toll estimate from Gallows Road to Route 267 is $6.45. i95/i495: $6.45; observed price. Observed 8:09 AM EDT. Recent movement is falling, net change $-2.50 (-27.9%). This is not a forecast. The current component is lower than the typical recent median of $8.25; range $7.75 to $9.15, current price is below recent range.

</details>

**Negative control: `wrong-movement-direction` — fail / fail / fail.** The verbal direction contradicts the returned negative movement despite retaining the correct amounts.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 33. Steady I-66 component

`dev3-steady-i-66-component` · current_evidence · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Check the current I-66 toll from Dolley Madison Boulevard to Washington Boulevard. Has it changed?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Report unchanged movement with zero net change and equality to the median.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-steady-i-66-component-1-1.json](fixtures/dev3-steady-i-66-component-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Check the current I-66 toll from Dolley Madison Boulevard to Washington Boulevard. Has it changed?

**Assistant 1:** The current toll estimate from Route 123 - Dolley Madison Blvd to Washington Blvd is $4.75. i66: $4.75; observed price. Observed 8:17 AM EDT. Recent movement is unchanged, net change $0.00 (0.0%). This is not a forecast. The current component is equal to the typical recent median of $4.75; range $4.25 to $5.25, current price is within recent range.

</details>

### 34. Mixed recent movement

`dev3-mixed-recent-movement` · current_evidence · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the current I-66 toll from Glebe Road to Washington D.C. on I-66, and its recent trend?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Describe mixed movement even though the net change is positive.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-mixed-recent-movement-1-1.json](fixtures/dev3-mixed-recent-movement-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current I-66 toll from Glebe Road to Washington D.C. on I-66, and its recent trend?

**Assistant 1:** The current toll estimate from Glebe Road to Washington D.C. I-66 is $6.85. i66: $6.85; observed price. Observed 8:17 AM EDT. Recent movement is mixed, net change $0.70 (11.4%). This is not a forecast. The current component is higher than the typical recent median of $6.65; range $6.25 to $7.15, current price is within recent range.

</details>

### 35. Two comparable weeks

`dev3-two-comparable-weeks` · current_evidence · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current toll from Gallows Road to Westpark on I-495 Express; how does it compare with recent weeks?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Disclose two of three comparable periods; do not call incomplete history typical complete history.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-two-comparable-weeks-1-1.json](fixtures/dev3-two-comparable-weeks-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current toll from Gallows Road to Westpark on I-495 Express; how does it compare with recent weeks?

**Assistant 1:** The current toll estimate from Gallows Road to Westpark Drive is $8.55. i95/i495: $8.55; observed price. Observed 8:09 AM EDT. The current component is lower than the median of the available comparable weeks (2 of 3) of $8.65; range $8.15 to $9.15, current price is within recent range.

</details>

**Negative control: `incomplete-history-called-complete` — fail / fail / fail.** Only two of three comparable periods are supplied; the completeness claim is false.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 36. Quote without comparisons

`dev3-quote-without-comparisons` · current_evidence · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current I-66 toll from Sycamore Street to Fairfax Drive, please.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Answer the available current quote without inventing a trend or historical median.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-quote-without-comparisons-1-1.json](fixtures/dev3-quote-without-comparisons-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current I-66 toll from Sycamore Street to Fairfax Drive, please.

**Assistant 1:** The current toll estimate from Sycamore St to Fairfax Drive is $3.85. i66: $3.85; observed price. Observed 8:17 AM EDT.

</details>

### 37. Stale Beltway observation

`dev3-stale-beltway-observation` · current_evidence · objective: unavailable · frozen: 2026-09-24T17:18:00-04:00

**Opening request**

> Can you check the current I-495 Express toll from Westpark Drive to Braddock Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Explain that the observation is too old to use, preserve its time, and do not quote a usable current toll or an age threshold.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-stale-beltway-observation-1-1.json](fixtures/dev3-stale-beltway-observation-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Can you check the current I-495 Express toll from Westpark Drive to Braddock Road?

**Assistant 1:** I cannot give a current toll estimate for Westpark Drive to Braddock Road. The observation is stale, too old to use; observed 3:09 PM EDT. Missing data does not mean the trip is free.

</details>

### 38. Missing I-66 observation

`dev3-missing-i-66-observation` · current_evidence · objective: unavailable · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current I-66 price from Sycamore Street to Washington D.C. on I-66?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Explain missing current pricing; do not treat missing as a free trip.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-missing-i-66-observation-1-1.json](fixtures/dev3-missing-i-66-observation-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current I-66 price from Sycamore Street to Washington D.C. on I-66?

**Assistant 1:** I cannot give a current toll estimate for Sycamore St to Washington D.C. I-66. There is no available price observation. Missing data does not mean the trip is free.

</details>

**Negative control: `missing-price-means-free` — fail / fail / fail.** Missing current evidence is not evidence of a free trip.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 39. I-95 closure on direct trip

`dev3-i-95-closure-on-direct-trip` · current_evidence · objective: unavailable · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the current I-95 Express toll from Opitz Boulevard to Pentagon/Eads?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Explain the returned I-95 closure with no invented price or unreturned fallback.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-i-95-closure-on-direct-trip-1-1.json](fixtures/dev3-i-95-closure-on-direct-trip-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current I-95 Express toll from Opitz Boulevard to Pentagon/Eads?

**Assistant 1:** The I-95 Express Lanes are reported closed for this trip from Opitz Boulevard to Pentagon/Eads Street. A current toll estimate is unavailable; this does not mean the toll is zero.

</details>

### 40. Modeled Beltway estimate

`dev3-modeled-beltway-estimate` · current_evidence · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> How much is I-495 Express right now from Braddock Road to Route 267?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them.  This is a one-way current-price request unless an explicit follow-up below changes the trip.

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Label the returned price as modeled, not directly observed for this route.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-modeled-beltway-estimate-1-1.json](fixtures/dev3-modeled-beltway-estimate-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** How much is I-495 Express right now from Braddock Road to Route 267?

**Assistant 1:** The current toll estimate from Braddock Road to Route 267 is $10.85. i95/i495: $10.85; modeled price estimate. Observed 8:09 AM EDT.

</details>

**Negative control: `modeled-called-observed` — fail / fail / fail.** The result explicitly identifies modeling; calling it directly observed hides material provenance.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 41. Three day Loudoun offer

`dev3-three-day-loudoun-offer` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Help me screen a new job offer using my tolled commute: Exit 7 - SR 607 (Loudoun County Pkwy) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 138 planned office days per year, gross annual salary $98000.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-three-day-loudoun-offer-1-1.json](fixtures/dev3-three-day-loudoun-offer-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Help me screen a new job offer using my tolled commute: Exit 7 - SR 607 (Loudoun County Pkwy) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 138 planned office days per year, gross annual salary $98000.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $61895.15. For 138 planned office days, gross annual income is $98000.00, with $65333.33 after the one-third assumed tax ($32666.67). The straight-line tolled distance is 19.44 miles per office day and 2682.31 miles annually; vehicle cost is $13.31 per office day and $1837.38 annually. P25 daily scenario: toll $11.60 per office day, $1600.80 annualized; combined toll and vehicle cost $24.91 per office day, $286.52 per average month, $3438.18 annually. Remaining annual income $61895.15; additional gross salary needed to offset this combined annual cost $5157.27; combined cost is 5.3% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1600.80 annualized; combined toll and vehicle cost $24.91 per office day, $286.52 per average month, $3438.18 annually. Remaining annual income $61895.15; additional gross salary needed to offset this combined annual cost $5157.27; combined cost is 5.3% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1600.80 annualized; combined toll and vehicle cost $24.91 per office day, $286.52 per average month, $3438.18 annually. Remaining annual income $61895.15; additional gross salary needed to offset this combined annual cost $5157.27; combined cost is 5.3% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

**Negative control: `invented-annual-total` — fail / fail / fail.** An invented combined annual amount has no matching result field.

Expected deterministic failures: unsupported_money. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 42. Five day Ryan offer

`dev3-five-day-ryan-offer` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual toll-commute affordability: Exit 6 - SR 772 (Ryan Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, monday, tuesday, wednesday, thursday, friday, leaving at 8:15 AM and returning at 5:45 PM, 228 planned office days per year, gross annual salary $112500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-five-day-ryan-offer-1-1.json](fixtures/dev3-five-day-ryan-offer-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual toll-commute affordability: Exit 6 - SR 772 (Ryan Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, monday, tuesday, wednesday, thursday, friday, leaving at 8:15 AM and returning at 5:45 PM, 228 planned office days per year, gross annual salary $112500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $69319.53. For 228 planned office days, gross annual income is $112500.00, with $75000.00 after the one-third assumed tax ($37500.00). The straight-line tolled distance is 19.44 miles per office day and 4431.64 miles annually; vehicle cost is $13.31 per office day and $3035.67 annually. P25 daily scenario: toll $11.60 per office day, $2644.80 annualized; combined toll and vehicle cost $24.91 per office day, $473.37 per average month, $5680.47 annually. Remaining annual income $69319.53; additional gross salary needed to offset this combined annual cost $8520.71; combined cost is 7.6% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $2644.80 annualized; combined toll and vehicle cost $24.91 per office day, $473.37 per average month, $5680.47 annually. Remaining annual income $69319.53; additional gross salary needed to offset this combined annual cost $8520.71; combined cost is 7.6% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $2644.80 annualized; combined toll and vehicle cost $24.91 per office day, $473.37 per average month, $5680.47 annually. Remaining annual income $69319.53; additional gross salary needed to offset this combined annual cost $8520.71; combined cost is 7.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 60 of 60 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 43. Two day Belmont office

`dev3-two-day-belmont-office` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> I only go into the office twice a week; estimate annual affordability: Exit 4 - SR 659 (Belmont Ridge Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, thursday, leaving at 7:15 AM and returning at 4:45 PM, 92 planned office days per year, gross annual salary $87500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-two-day-belmont-office-1-1.json](fixtures/dev3-two-day-belmont-office-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I only go into the office twice a week; estimate annual affordability: Exit 4 - SR 659 (Belmont Ridge Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, thursday, leaving at 7:15 AM and returning at 4:45 PM, 92 planned office days per year, gross annual salary $87500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $56041.21. For 92 planned office days, gross annual income is $87500.00, with $58333.33 after the one-third assumed tax ($29166.67). The straight-line tolled distance is 19.44 miles per office day and 1788.20 miles annually; vehicle cost is $13.31 per office day and $1224.92 annually. P25 daily scenario: toll $11.60 per office day, $1067.20 annualized; combined toll and vehicle cost $24.91 per office day, $191.01 per average month, $2292.12 annually. Remaining annual income $56041.21; additional gross salary needed to offset this combined annual cost $3438.18; combined cost is 3.9% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1067.20 annualized; combined toll and vehicle cost $24.91 per office day, $191.01 per average month, $2292.12 annually. Remaining annual income $56041.21; additional gross salary needed to offset this combined annual cost $3438.18; combined cost is 3.9% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1067.20 annualized; combined toll and vehicle cost $24.91 per office day, $191.01 per average month, $2292.12 annually. Remaining annual income $56041.21; additional gross salary needed to offset this combined annual cost $3438.18; combined cost is 3.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 24 of 24 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 44. Short Claiborne commute

`dev3-short-claiborne-commute` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate the annual impact of this short tolled commute: Exit 5 - SR 901 (Claiborne Pkwy) to Exit 8 - SR 606 (Ox Rd) and back, monday, tuesday, wednesday, thursday, leaving at 8:30 AM and returning at 5:00 PM, 180 planned office days per year, gross annual salary $73500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-short-claiborne-commute-1-1.json](fixtures/dev3-short-claiborne-commute-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate the annual impact of this short tolled commute: Exit 5 - SR 901 (Claiborne Pkwy) to Exit 8 - SR 606 (Ox Rd) and back, monday, tuesday, wednesday, thursday, leaving at 8:30 AM and returning at 5:00 PM, 180 planned office days per year, gross annual salary $73500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $44767.42. For 180 planned office days, gross annual income is $73500.00, with $49000.00 after the one-third assumed tax ($24500.00). The straight-line tolled distance is 19.44 miles per office day and 3498.66 miles annually; vehicle cost is $13.31 per office day and $2396.58 annually. P25 daily scenario: toll $10.20 per office day, $1836.00 annualized; combined toll and vehicle cost $23.51 per office day, $352.72 per average month, $4232.58 annually. Remaining annual income $44767.42; additional gross salary needed to offset this combined annual cost $6348.87; combined cost is 8.6% of assumed after-tax income. P50 daily scenario: toll $10.20 per office day, $1836.00 annualized; combined toll and vehicle cost $23.51 per office day, $352.72 per average month, $4232.58 annually. Remaining annual income $44767.42; additional gross salary needed to offset this combined annual cost $6348.87; combined cost is 8.6% of assumed after-tax income. P90 daily scenario: toll $10.20 per office day, $1836.00 annualized; combined toll and vehicle cost $23.51 per office day, $352.72 per average month, $4232.58 annually. Remaining annual income $44767.42; additional gross salary needed to offset this combined annual cost $6348.87; combined cost is 8.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 48 of 48 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 45. Shreve part time office

`dev3-shreve-part-time-office` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> I work part time; estimate annual commute affordability: Exit 3 - SR 653 (Shreve Mill Rd) to Exit 7 - SR 607 (Loudoun County Pkwy) and back, monday, friday, leaving at 8:00 AM and returning at 4:15 PM, 96 planned office days per year, gross annual salary $66500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-shreve-part-time-office-1-1.json](fixtures/dev3-shreve-part-time-office-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I work part time; estimate annual commute affordability: Exit 3 - SR 653 (Shreve Mill Rd) to Exit 7 - SR 607 (Loudoun County Pkwy) and back, monday, friday, leaving at 8:00 AM and returning at 4:15 PM, 96 planned office days per year, gross annual salary $66500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $42075.95. For 96 planned office days, gross annual income is $66500.00, with $44333.33 after the one-third assumed tax ($22166.67). The straight-line tolled distance is 19.44 miles per office day and 1865.95 miles annually; vehicle cost is $13.31 per office day and $1278.18 annually. P25 daily scenario: toll $10.20 per office day, $979.20 annualized; combined toll and vehicle cost $23.51 per office day, $188.12 per average month, $2257.38 annually. Remaining annual income $42075.95; additional gross salary needed to offset this combined annual cost $3386.07; combined cost is 5.1% of assumed after-tax income. P50 daily scenario: toll $10.20 per office day, $979.20 annualized; combined toll and vehicle cost $23.51 per office day, $188.12 per average month, $2257.38 annually. Remaining annual income $42075.95; additional gross salary needed to offset this combined annual cost $3386.07; combined cost is 5.1% of assumed after-tax income. P90 daily scenario: toll $10.20 per office day, $979.20 annualized; combined toll and vehicle cost $23.51 per office day, $188.12 per average month, $2257.38 annually. Remaining annual income $42075.95; additional gross salary needed to offset this combined annual cost $3386.07; combined cost is 5.1% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 24 of 24 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 46. Reverse Greenway job

`dev3-reverse-greenway-job` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Evaluate this reverse-direction annual commute: Route 28 (Dulles Toll Road / Dulles Greenway) to Exit 4 - SR 659 (Belmont Ridge Rd) and back, monday, tuesday, wednesday, thursday, friday, leaving at 7:30 AM and returning at 5:30 PM, 216 planned office days per year, gross annual salary $106000.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-reverse-greenway-job-1-1.json](fixtures/dev3-reverse-greenway-job-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Evaluate this reverse-direction annual commute: Route 28 (Dulles Toll Road / Dulles Greenway) to Exit 4 - SR 659 (Belmont Ridge Rd) and back, monday, tuesday, wednesday, thursday, friday, leaving at 7:30 AM and returning at 5:30 PM, 216 planned office days per year, gross annual salary $106000.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $65522.77. For 216 planned office days, gross annual income is $106000.00, with $70666.67 after the one-third assumed tax ($35333.33). The straight-line tolled distance is 19.44 miles per office day and 4198.39 miles annually; vehicle cost is $13.31 per office day and $2875.90 annually. P25 daily scenario: toll $10.50 per office day, $2268.00 annualized; combined toll and vehicle cost $23.81 per office day, $428.66 per average month, $5143.90 annually. Remaining annual income $65522.77; additional gross salary needed to offset this combined annual cost $7715.85; combined cost is 7.3% of assumed after-tax income. P50 daily scenario: toll $10.50 per office day, $2268.00 annualized; combined toll and vehicle cost $23.81 per office day, $428.66 per average month, $5143.90 annually. Remaining annual income $65522.77; additional gross salary needed to offset this combined annual cost $7715.85; combined cost is 7.3% of assumed after-tax income. P90 daily scenario: toll $10.50 per office day, $2268.00 annualized; combined toll and vehicle cost $23.81 per office day, $428.66 per average month, $5143.90 annually. Remaining annual income $65522.77; additional gross salary needed to offset this combined annual cost $7715.85; combined cost is 7.3% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 60 of 60 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 47. Reston hybrid offer

`dev3-reston-hybrid-offer` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> How much of my job offer remains after assumed tax and the tolled commute: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, monday, wednesday, friday, leaving at 8:15 AM and returning at 5:15 PM, 142 planned office days per year, gross annual salary $124500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-reston-hybrid-offer-1-1.json](fixtures/dev3-reston-hybrid-offer-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** How much of my job offer remains after assumed tax and the tolled commute: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, monday, wednesday, friday, leaving at 8:15 AM and returning at 5:15 PM, 142 planned office days per year, gross annual salary $124500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $78837.36. For 142 planned office days, gross annual income is $124500.00, with $83000.00 after the one-third assumed tax ($41500.00). The straight-line tolled distance is 19.44 miles per office day and 2760.05 miles annually; vehicle cost is $13.31 per office day and $1890.64 annually. P25 daily scenario: toll $16.00 per office day, $2272.00 annualized; combined toll and vehicle cost $29.31 per office day, $346.89 per average month, $4162.64 annually. Remaining annual income $78837.36; additional gross salary needed to offset this combined annual cost $6243.96; combined cost is 5.0% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2272.00 annualized; combined toll and vehicle cost $29.31 per office day, $346.89 per average month, $4162.64 annually. Remaining annual income $78837.36; additional gross salary needed to offset this combined annual cost $6243.96; combined cost is 5.0% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2272.00 annualized; combined toll and vehicle cost $29.31 per office day, $346.89 per average month, $4162.64 annually. Remaining annual income $78837.36; additional gross salary needed to offset this combined annual cost $6243.96; combined cost is 5.0% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

**Negative control: `combined-cost-labeled-toll` — fail / fail / fail.** A genuine combined toll-plus-vehicle amount is mislabeled as toll alone; currency membership cannot detect this.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 48. Wiehle full office week

`dev3-wiehle-full-office-week` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual tolled commuting costs and remaining income: Exit 13 - SR 828 (Wiehle Ave) to Exit 18/19 - I-495 / SR 123 (Capital Beltway) and back, monday, tuesday, wednesday, thursday, friday, leaving at 7:00 AM and returning at 4:30 PM, 232 planned office days per year, gross annual salary $135000.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-wiehle-full-office-week-1-1.json](fixtures/dev3-wiehle-full-office-week-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual tolled commuting costs and remaining income: Exit 13 - SR 828 (Wiehle Ave) to Exit 18/19 - I-495 / SR 123 (Capital Beltway) and back, monday, tuesday, wednesday, thursday, friday, leaving at 7:00 AM and returning at 4:30 PM, 232 planned office days per year, gross annual salary $135000.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $84127.07. For 232 planned office days, gross annual income is $135000.00, with $90000.00 after the one-third assumed tax ($45000.00). The straight-line tolled distance is 19.44 miles per office day and 4509.38 miles annually; vehicle cost is $13.31 per office day and $3088.93 annually. P25 daily scenario: toll $12.00 per office day, $2784.00 annualized; combined toll and vehicle cost $25.31 per office day, $489.41 per average month, $5872.93 annually. Remaining annual income $84127.07; additional gross salary needed to offset this combined annual cost $8809.40; combined cost is 6.5% of assumed after-tax income. P50 daily scenario: toll $12.00 per office day, $2784.00 annualized; combined toll and vehicle cost $25.31 per office day, $489.41 per average month, $5872.93 annually. Remaining annual income $84127.07; additional gross salary needed to offset this combined annual cost $8809.40; combined cost is 6.5% of assumed after-tax income. P90 daily scenario: toll $12.00 per office day, $2784.00 annualized; combined toll and vehicle cost $25.31 per office day, $489.41 per average month, $5872.93 annually. Remaining annual income $84127.07; additional gross salary needed to offset this combined annual cost $8809.40; combined cost is 6.5% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 60 of 60 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 49. Hunter Mill four day job

`dev3-hunter-mill-four-day-job` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Help me assess annual commuting affordability: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, monday, tuesday, thursday, friday, leaving at 8:45 AM and returning at 6:00 PM, 188 planned office days per year, gross annual salary $91500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-hunter-mill-four-day-job-1-1.json](fixtures/dev3-hunter-mill-four-day-job-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Help me assess annual commuting affordability: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, monday, tuesday, thursday, friday, leaving at 8:45 AM and returning at 6:00 PM, 188 planned office days per year, gross annual salary $91500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $55488.90. For 188 planned office days, gross annual income is $91500.00, with $61000.00 after the one-third assumed tax ($30500.00). The straight-line tolled distance is 19.44 miles per office day and 3654.16 miles annually; vehicle cost is $13.31 per office day and $2503.10 annually. P25 daily scenario: toll $16.00 per office day, $3008.00 annualized; combined toll and vehicle cost $29.31 per office day, $459.26 per average month, $5511.10 annually. Remaining annual income $55488.90; additional gross salary needed to offset this combined annual cost $8266.65; combined cost is 9.0% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $3008.00 annualized; combined toll and vehicle cost $29.31 per office day, $459.26 per average month, $5511.10 annually. Remaining annual income $55488.90; additional gross salary needed to offset this combined annual cost $8266.65; combined cost is 9.0% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $3008.00 annualized; combined toll and vehicle cost $29.31 per office day, $459.26 per average month, $5511.10 annually. Remaining annual income $55488.90; additional gross salary needed to offset this combined annual cost $8266.65; combined cost is 9.0% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 48 of 48 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 50. Fairfax Parkway shorter day

`dev3-fairfax-parkway-shorter-day` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate my annual commute impact for these shorter office days: Exit 11 - SR 286 (Fairfax County Pkwy) to Exit 15 - SR 676 (Wolf Trap) and back, monday, wednesday, friday, leaving at 9:00 AM and returning at 3:30 PM, 144 planned office days per year, gross annual salary $80500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-fairfax-parkway-shorter-day-1-1.json](fixtures/dev3-fairfax-parkway-shorter-day-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate my annual commute impact for these shorter office days: Exit 11 - SR 286 (Fairfax County Pkwy) to Exit 15 - SR 676 (Wolf Trap) and back, monday, wednesday, friday, leaving at 9:00 AM and returning at 3:30 PM, 144 planned office days per year, gross annual salary $80500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $51173.40. For 144 planned office days, gross annual income is $80500.00, with $53666.67 after the one-third assumed tax ($26833.33). The straight-line tolled distance is 19.44 miles per office day and 2798.93 miles annually; vehicle cost is $13.31 per office day and $1917.27 annually. P25 daily scenario: toll $4.00 per office day, $576.00 annualized; combined toll and vehicle cost $17.31 per office day, $207.77 per average month, $2493.27 annually. Remaining annual income $51173.40; additional gross salary needed to offset this combined annual cost $3739.91; combined cost is 4.6% of assumed after-tax income. P50 daily scenario: toll $4.00 per office day, $576.00 annualized; combined toll and vehicle cost $17.31 per office day, $207.77 per average month, $2493.27 annually. Remaining annual income $51173.40; additional gross salary needed to offset this combined annual cost $3739.91; combined cost is 4.6% of assumed after-tax income. P90 daily scenario: toll $4.00 per office day, $576.00 annualized; combined toll and vehicle cost $17.31 per office day, $207.77 per average month, $2493.27 annually. Remaining annual income $51173.40; additional gross salary needed to offset this combined annual cost $3739.91; combined cost is 4.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 51. Reverse Dulles Road offer

`dev3-reverse-dulles-road-offer` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Screen the annual impact of my westbound morning commute: Exit 17 - SR 684 (Spring Hill Rd) to Exit 13 - SR 828 (Wiehle Ave) and back, monday, tuesday, wednesday, thursday, friday, leaving at 8:00 AM and returning at 5:00 PM, 224 planned office days per year, gross annual salary $119500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-reverse-dulles-road-offer-1-1.json](fixtures/dev3-reverse-dulles-road-offer-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Screen the annual impact of my westbound morning commute: Exit 17 - SR 684 (Spring Hill Rd) to Exit 13 - SR 828 (Wiehle Ave) and back, monday, tuesday, wednesday, thursday, friday, leaving at 8:00 AM and returning at 5:00 PM, 224 planned office days per year, gross annual salary $119500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $73100.26. For 224 planned office days, gross annual income is $119500.00, with $79666.67 after the one-third assumed tax ($39833.33). The straight-line tolled distance is 19.44 miles per office day and 4353.89 miles annually; vehicle cost is $13.31 per office day and $2982.41 annually. P25 daily scenario: toll $16.00 per office day, $3584.00 annualized; combined toll and vehicle cost $29.31 per office day, $547.20 per average month, $6566.41 annually. Remaining annual income $73100.26; additional gross salary needed to offset this combined annual cost $9849.62; combined cost is 8.2% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $3584.00 annualized; combined toll and vehicle cost $29.31 per office day, $547.20 per average month, $6566.41 annually. Remaining annual income $73100.26; additional gross salary needed to offset this combined annual cost $9849.62; combined cost is 8.2% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $3584.00 annualized; combined toll and vehicle cost $29.31 per office day, $547.20 per average month, $6566.41 annually. Remaining annual income $73100.26; additional gross salary needed to offset this combined annual cost $9849.62; combined cost is 8.2% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 60 of 60 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 52. Gallows hybrid salary

`dev3-gallows-hybrid-salary` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-495 Express commute affordability: Gallows Road to Jones Branch Drive/Route 123 and back, tuesday, wednesday, thursday, leaving at 7:30 AM and returning at 5:15 PM, 136 planned office days per year, gross annual salary $128500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-gallows-hybrid-salary-1-1.json](fixtures/dev3-gallows-hybrid-salary-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-495 Express commute affordability: Gallows Road to Jones Branch Drive/Route 123 and back, tuesday, wednesday, thursday, leaving at 7:30 AM and returning at 5:15 PM, 136 planned office days per year, gross annual salary $128500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $82176.32. For 136 planned office days, gross annual income is $128500.00, with $85666.67 after the one-third assumed tax ($42833.33). The straight-line tolled distance is 19.44 miles per office day and 2643.43 miles annually; vehicle cost is $13.31 per office day and $1810.75 annually. P25 daily scenario: toll $8.65 per office day, $1176.40 annualized; combined toll and vehicle cost $21.96 per office day, $248.93 per average month, $2987.15 annually. Remaining annual income $82679.52; additional gross salary needed to offset this combined annual cost $4480.73; combined cost is 3.5% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1679.60 annualized; combined toll and vehicle cost $25.66 per office day, $290.86 per average month, $3490.35 annually. Remaining annual income $82176.32; additional gross salary needed to offset this combined annual cost $5235.53; combined cost is 4.1% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2645.20 annualized; combined toll and vehicle cost $32.76 per office day, $371.33 per average month, $4455.95 annually. Remaining annual income $81210.72; additional gross salary needed to offset this combined annual cost $6683.93; combined cost is 5.2% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 53. Braddock five day salary

`dev3-braddock-five-day-salary` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What remains of my annual salary after assumed taxes and tolled commuting: Braddock Road to Westpark Drive and back, monday, tuesday, wednesday, thursday, friday, leaving at 8:00 AM and returning at 5:30 PM, 230 planned office days per year, gross annual salary $146000.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-braddock-five-day-salary-1-1.json](fixtures/dev3-braddock-five-day-salary-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What remains of my annual salary after assumed taxes and tolled commuting: Braddock Road to Westpark Drive and back, monday, tuesday, wednesday, thursday, friday, leaving at 8:00 AM and returning at 5:30 PM, 230 planned office days per year, gross annual salary $146000.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $91430.53. For 230 planned office days, gross annual income is $146000.00, with $97333.33 after the one-third assumed tax ($48666.67). The straight-line tolled distance is 19.44 miles per office day and 4470.51 miles annually; vehicle cost is $13.31 per office day and $3062.30 annually. P25 daily scenario: toll $8.65 per office day, $1989.50 annualized; combined toll and vehicle cost $21.96 per office day, $420.98 per average month, $5051.80 annually. Remaining annual income $92281.53; additional gross salary needed to offset this combined annual cost $7577.70; combined cost is 5.2% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $2840.50 annualized; combined toll and vehicle cost $25.66 per office day, $491.90 per average month, $5902.80 annually. Remaining annual income $91430.53; additional gross salary needed to offset this combined annual cost $8854.20; combined cost is 6.1% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $4473.50 annualized; combined toll and vehicle cost $32.76 per office day, $627.98 per average month, $7535.80 annually. Remaining annual income $89797.53; additional gross salary needed to offset this combined annual cost $11303.70; combined cost is 7.7% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 60 of 60 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 54. Route Seven two day role

`dev3-route-seven-two-day-role` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> I have a two-day office requirement; estimate its annual impact: Braddock Road to Route 7 (Leesburg Pike) and back, wednesday, thursday, leaving at 7:15 AM and returning at 4:45 PM, 94 planned office days per year, gross annual salary $101500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-route-seven-two-day-role-1-1.json](fixtures/dev3-route-seven-two-day-role-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I have a two-day office requirement; estimate its annual impact: Braddock Road to Route 7 (Leesburg Pike) and back, wednesday, thursday, leaving at 7:15 AM and returning at 4:45 PM, 94 planned office days per year, gross annual salary $101500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $65254.22. For 94 planned office days, gross annual income is $101500.00, with $67666.67 after the one-third assumed tax ($33833.33). The straight-line tolled distance is 19.44 miles per office day and 1827.08 miles annually; vehicle cost is $13.31 per office day and $1251.55 annually. P25 daily scenario: toll $8.65 per office day, $813.10 annualized; combined toll and vehicle cost $21.96 per office day, $172.05 per average month, $2064.65 annually. Remaining annual income $65602.02; additional gross salary needed to offset this combined annual cost $3096.98; combined cost is 3.1% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1160.90 annualized; combined toll and vehicle cost $25.66 per office day, $201.04 per average month, $2412.45 annually. Remaining annual income $65254.22; additional gross salary needed to offset this combined annual cost $3618.68; combined cost is 3.6% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $1828.30 annualized; combined toll and vehicle cost $32.76 per office day, $256.65 per average month, $3079.85 annually. Remaining annual income $64586.82; additional gross salary needed to offset this combined annual cost $4619.78; combined cost is 4.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 24 of 24 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 55. Route Seven I-66 three day job

`dev3-route-seven-i-66-three-day-job` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-66 commute affordability: Route 7 - Leesburg Pike to Fairfax Drive and back, monday, tuesday, thursday, leaving at 8:30 AM and returning at 5:45 PM, 140 planned office days per year, gross annual salary $117000.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-route-seven-i-66-three-day-job-1-1.json](fixtures/dev3-route-seven-i-66-three-day-job-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-66 commute affordability: Route 7 - Leesburg Pike to Fairfax Drive and back, monday, tuesday, thursday, leaving at 8:30 AM and returning at 5:45 PM, 140 planned office days per year, gross annual salary $117000.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $74406.99. For 140 planned office days, gross annual income is $117000.00, with $78000.00 after the one-third assumed tax ($39000.00). The straight-line tolled distance is 19.44 miles per office day and 2721.18 miles annually; vehicle cost is $13.31 per office day and $1864.01 annually. P25 daily scenario: toll $8.65 per office day, $1211.00 annualized; combined toll and vehicle cost $21.96 per office day, $256.25 per average month, $3075.01 annually. Remaining annual income $74924.99; additional gross salary needed to offset this combined annual cost $4612.52; combined cost is 3.9% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1729.00 annualized; combined toll and vehicle cost $25.66 per office day, $299.42 per average month, $3593.01 annually. Remaining annual income $74406.99; additional gross salary needed to offset this combined annual cost $5389.52; combined cost is 4.6% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2723.00 annualized; combined toll and vehicle cost $32.76 per office day, $382.25 per average month, $4587.01 annually. Remaining annual income $73412.99; additional gross salary needed to offset this combined annual cost $6880.52; combined cost is 5.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 56. Sycamore Washington offer

`dev3-sycamore-washington-offer` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Help assess a Washington I-66 job with annual commute scenarios: Sycamore St to Washington D.C. I-66 and back, monday, tuesday, wednesday, thursday, friday, leaving at 7:45 AM and returning at 5:15 PM, 226 planned office days per year, gross annual salary $154000.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-sycamore-washington-offer-1-1.json](fixtures/dev3-sycamore-washington-offer-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Help assess a Washington I-66 job with annual commute scenarios: Sycamore St to Washington D.C. I-66 and back, monday, tuesday, wednesday, thursday, friday, leaving at 7:45 AM and returning at 5:15 PM, 226 planned office days per year, gross annual salary $154000.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $96866.53. For 226 planned office days, gross annual income is $154000.00, with $102666.67 after the one-third assumed tax ($51333.33). The straight-line tolled distance is 19.44 miles per office day and 4392.76 miles annually; vehicle cost is $13.31 per office day and $3009.04 annually. P25 daily scenario: toll $8.65 per office day, $1954.90 annualized; combined toll and vehicle cost $21.96 per office day, $413.66 per average month, $4963.94 annually. Remaining annual income $97702.73; additional gross salary needed to offset this combined annual cost $7445.91; combined cost is 4.8% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $2791.10 annualized; combined toll and vehicle cost $25.66 per office day, $483.35 per average month, $5800.14 annually. Remaining annual income $96866.53; additional gross salary needed to offset this combined annual cost $8700.21; combined cost is 5.6% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $4395.70 annualized; combined toll and vehicle cost $32.76 per office day, $617.06 per average month, $7404.74 annually. Remaining annual income $95261.93; additional gross salary needed to offset this combined annual cost $11107.11; combined cost is 7.2% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 60 of 60 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 57. Saturday retail commute

`dev3-saturday-retail-commute` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual commuting affordability for my retail schedule: Exit 7 - SR 607 (Loudoun County Pkwy) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, thursday, friday, saturday, leaving at 8:00 AM and returning at 5:00 PM, 140 planned office days per year, gross annual salary $68500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-saturday-retail-commute-1-1.json](fixtures/dev3-saturday-retail-commute-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual commuting affordability for my retail schedule: Exit 7 - SR 607 (Loudoun County Pkwy) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, thursday, friday, saturday, leaving at 8:00 AM and returning at 5:00 PM, 140 planned office days per year, gross annual salary $68500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $42178.66. For 140 planned office days, gross annual income is $68500.00, with $45666.67 after the one-third assumed tax ($22833.33). The straight-line tolled distance is 19.44 miles per office day and 2721.18 miles annually; vehicle cost is $13.31 per office day and $1864.01 annually. P25 daily scenario: toll $10.50 per office day, $1470.00 annualized; combined toll and vehicle cost $23.81 per office day, $277.83 per average month, $3334.01 annually. Remaining annual income $42332.66; additional gross salary needed to offset this combined annual cost $5001.02; combined cost is 7.3% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1624.00 annualized; combined toll and vehicle cost $24.91 per office day, $290.67 per average month, $3488.01 annually. Remaining annual income $42178.66; additional gross salary needed to offset this combined annual cost $5232.02; combined cost is 7.6% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1624.00 annualized; combined toll and vehicle cost $24.91 per office day, $290.67 per average month, $3488.01 annually. Remaining annual income $42178.66; additional gross salary needed to offset this combined annual cost $5232.02; combined cost is 7.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 58. Sunday healthcare commute

`dev3-sunday-healthcare-commute` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual costs for my weekend healthcare shifts: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, saturday, sunday, leaving at 7:00 AM and returning at 7:00 PM, 96 planned office days per year, gross annual salary $108000.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-sunday-healthcare-commute-1-1.json](fixtures/dev3-sunday-healthcare-commute-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual costs for my weekend healthcare shifts: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, saturday, sunday, leaving at 7:00 AM and returning at 7:00 PM, 96 planned office days per year, gross annual salary $108000.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $69185.82. For 96 planned office days, gross annual income is $108000.00, with $72000.00 after the one-third assumed tax ($36000.00). The straight-line tolled distance is 19.44 miles per office day and 1865.95 miles annually; vehicle cost is $13.31 per office day and $1278.18 annually. P25 daily scenario: toll $16.00 per office day, $1536.00 annualized; combined toll and vehicle cost $29.31 per office day, $234.52 per average month, $2814.18 annually. Remaining annual income $69185.82; additional gross salary needed to offset this combined annual cost $4221.27; combined cost is 3.9% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $1536.00 annualized; combined toll and vehicle cost $29.31 per office day, $234.52 per average month, $2814.18 annually. Remaining annual income $69185.82; additional gross salary needed to offset this combined annual cost $4221.27; combined cost is 3.9% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $1536.00 annualized; combined toll and vehicle cost $29.31 per office day, $234.52 per average month, $2814.18 annually. Remaining annual income $69185.82; additional gross salary needed to offset this combined annual cost $4221.27; combined cost is 3.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 24 of 24 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 59. One day team meeting

`dev3-one-day-team-meeting` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate the annual impact of one office meeting day each week: Braddock Road to Westpark Drive and back, wednesday, leaving at 8:15 AM and returning at 5:45 PM, 46 planned office days per year, gross annual salary $133500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-one-day-team-meeting-1-1.json](fixtures/dev3-one-day-team-meeting-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate the annual impact of one office meeting day each week: Braddock Road to Westpark Drive and back, wednesday, leaving at 8:15 AM and returning at 5:45 PM, 46 planned office days per year, gross annual salary $133500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $87819.44. For 46 planned office days, gross annual income is $133500.00, with $89000.00 after the one-third assumed tax ($44500.00). The straight-line tolled distance is 19.44 miles per office day and 894.10 miles annually; vehicle cost is $13.31 per office day and $612.46 annually. P25 daily scenario: toll $8.65 per office day, $397.90 annualized; combined toll and vehicle cost $21.96 per office day, $84.20 per average month, $1010.36 annually. Remaining annual income $87989.64; additional gross salary needed to offset this combined annual cost $1515.54; combined cost is 1.1% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $568.10 annualized; combined toll and vehicle cost $25.66 per office day, $98.38 per average month, $1180.56 annually. Remaining annual income $87819.44; additional gross salary needed to offset this combined annual cost $1770.84; combined cost is 1.3% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $894.70 annualized; combined toll and vehicle cost $32.76 per office day, $125.60 per average month, $1507.16 annually. Remaining annual income $87492.84; additional gross salary needed to offset this combined annual cost $2260.74; combined cost is 1.7% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 12 of 12 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 60. Late start Greenway role

`dev3-late-start-greenway-role` · annual_complete · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability with my later office hours: Exit 6 - SR 772 (Ryan Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, monday, tuesday, wednesday, thursday, leaving at 10:15 AM and returning at 7:00 PM, 182 planned office days per year, gross annual salary $94500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Use all supplied facts as stated, infer the reversed return endpoints, and do not propose a different annual-day count. The route, weekday pattern, and departure times distinguish this commute.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-late-start-greenway-role-1-1.json](fixtures/dev3-late-start-greenway-role-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability with my later office hours: Exit 6 - SR 772 (Ryan Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, monday, tuesday, wednesday, thursday, leaving at 10:15 AM and returning at 7:00 PM, 182 planned office days per year, gross annual salary $94500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $58665.79. For 182 planned office days, gross annual income is $94500.00, with $63000.00 after the one-third assumed tax ($31500.00). The straight-line tolled distance is 19.44 miles per office day and 3537.53 miles annually; vehicle cost is $13.31 per office day and $2423.21 annually. P25 daily scenario: toll $10.50 per office day, $1911.00 annualized; combined toll and vehicle cost $23.81 per office day, $361.18 per average month, $4334.21 annually. Remaining annual income $58665.79; additional gross salary needed to offset this combined annual cost $6501.32; combined cost is 6.9% of assumed after-tax income. P50 daily scenario: toll $10.50 per office day, $1911.00 annualized; combined toll and vehicle cost $23.81 per office day, $361.18 per average month, $4334.21 annually. Remaining annual income $58665.79; additional gross salary needed to offset this combined annual cost $6501.32; combined cost is 6.9% of assumed after-tax income. P90 daily scenario: toll $10.50 per office day, $1911.00 annualized; combined toll and vehicle cost $23.81 per office day, $361.18 per average month, $4334.21 annually. Remaining annual income $58665.79; additional gross salary needed to offset this combined annual cost $6501.32; combined cost is 6.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 48 of 48 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 61. Supply annual salary

`dev3-supply-annual-salary` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate my yearly commute: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 140 planned office days per year.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your gross annual salary is $102,500.

Supply your annual salary when asked.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Ask for the missing income without inventing it.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-supply-annual-salary-2-1.json](fixtures/dev3-supply-annual-salary-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate my yearly commute: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 140 planned office days per year.

**Assistant 1:** What is your gross annual income in US dollars?

**User 2:** My gross annual salary is $102,500.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $64229.32. For 140 planned office days, gross annual income is $102500.00, with $68333.33 after the one-third assumed tax ($34166.67). The straight-line tolled distance is 19.44 miles per office day and 2721.18 miles annually; vehicle cost is $13.31 per office day and $1864.01 annually. P25 daily scenario: toll $16.00 per office day, $2240.00 annualized; combined toll and vehicle cost $29.31 per office day, $342.00 per average month, $4104.01 annually. Remaining annual income $64229.32; additional gross salary needed to offset this combined annual cost $6156.02; combined cost is 6.0% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2240.00 annualized; combined toll and vehicle cost $29.31 per office day, $342.00 per average month, $4104.01 annually. Remaining annual income $64229.32; additional gross salary needed to offset this combined annual cost $6156.02; combined cost is 6.0% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2240.00 annualized; combined toll and vehicle cost $29.31 per office day, $342.00 per average month, $4104.01 annually. Remaining annual income $64229.32; additional gross salary needed to offset this combined annual cost $6156.02; combined cost is 6.0% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 62. Supply both departure times

`dev3-supply-both-departure-times` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-495 Express commuting from Gallows Road to Jones Branch Drive and back, Tuesday through Thursday, 146 days, gross annual income $109,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You leave at 7:45 AM and return at 5:15 PM Eastern.

Provide both departure times when asked.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Collect both missing times together; retain the route, income, and days.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-supply-both-departure-times-2-1.json](fixtures/dev3-supply-both-departure-times-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-495 Express commuting from Gallows Road to Jones Branch Drive and back, Tuesday through Thursday, 146 days, gross annual income $109,500.

**Assistant 1:** What time do you leave outbound and what time do you leave for the return trip?

**User 2:** 7:45 AM outbound and 5:15 PM home.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $69253.01. For 146 planned office days, gross annual income is $109500.00, with $73000.00 after the one-third assumed tax ($36500.00). The straight-line tolled distance is 19.44 miles per office day and 2837.80 miles annually; vehicle cost is $13.31 per office day and $1943.89 annually. P25 daily scenario: toll $8.65 per office day, $1262.90 annualized; combined toll and vehicle cost $21.96 per office day, $267.23 per average month, $3206.79 annually. Remaining annual income $69793.21; additional gross salary needed to offset this combined annual cost $4810.19; combined cost is 4.4% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1803.10 annualized; combined toll and vehicle cost $25.66 per office day, $312.25 per average month, $3746.99 annually. Remaining annual income $69253.01; additional gross salary needed to offset this combined annual cost $5620.49; combined cost is 5.1% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2839.70 annualized; combined toll and vehicle cost $32.76 per office day, $398.63 per average month, $4783.59 annually. Remaining annual income $68216.41; additional gross salary needed to offset this combined annual cost $7175.39; combined cost is 6.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 63. Supply missing weekdays

`dev3-supply-missing-weekdays` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate my annual commute from Reston Parkway to Spring Hill Road on the Dulles Toll Road and back. Depart 7:45 AM, return 5:15 PM, 141 annual office days, gross income $122,000.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You commute Tuesday, Wednesday, and Thursday.

Supply those three weekdays when asked.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Ask for weekdays only; retain the already supplied annual days without proposing 52-week replacement days.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-supply-missing-weekdays-2-1.json](fixtures/dev3-supply-missing-weekdays-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate my annual commute from Reston Parkway to Spring Hill Road on the Dulles Toll Road and back. Depart 7:45 AM, return 5:15 PM, 141 annual office days, gross income $122,000.

**Assistant 1:** Which weekdays do you commute?

**User 2:** Tuesday, Wednesday, and Thursday.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $77200.01. For 141 planned office days, gross annual income is $122000.00, with $81333.33 after the one-third assumed tax ($40666.67). The straight-line tolled distance is 19.44 miles per office day and 2740.62 miles annually; vehicle cost is $13.31 per office day and $1877.32 annually. P25 daily scenario: toll $16.00 per office day, $2256.00 annualized; combined toll and vehicle cost $29.31 per office day, $344.44 per average month, $4133.32 annually. Remaining annual income $77200.01; additional gross salary needed to offset this combined annual cost $6199.98; combined cost is 5.1% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2256.00 annualized; combined toll and vehicle cost $29.31 per office day, $344.44 per average month, $4133.32 annually. Remaining annual income $77200.01; additional gross salary needed to offset this combined annual cost $6199.98; combined cost is 5.1% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2256.00 annualized; combined toll and vehicle cost $29.31 per office day, $344.44 per average month, $4133.32 annually. Remaining annual income $77200.01; additional gross salary needed to offset this combined annual cost $6199.98; combined cost is 5.1% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 64. Accept three day annual count

`dev3-accept-three-day-annual-count` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual Greenway affordability from Belmont Ridge Road to Route 28 and back. Tuesday to Thursday, 7:45 AM out and 5:15 PM return, $103,000 gross annual pay.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You accept the proposed 156-day annual estimate.

Explicitly accept 156 days when offered the choice to use or adjust it.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Propose 156 days with both use and adjust choices, wait for acceptance, then call.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-accept-three-day-annual-count-2-1.json](fixtures/dev3-accept-three-day-annual-count-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual Greenway affordability from Belmont Ridge Road to Route 28 and back. Tuesday to Thursday, 7:45 AM out and 5:15 PM return, $103,000 gross annual pay.

**Assistant 1:** Three days per week over 52 weeks is 156 planned annual commute days. Use 156, or adjust it up or down?

**User 2:** Use 156 days.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $64780.03. For 156 planned office days, gross annual income is $103000.00, with $68666.67 after the one-third assumed tax ($34333.33). The straight-line tolled distance is 19.44 miles per office day and 3032.17 miles annually; vehicle cost is $13.31 per office day and $2077.04 annually. P25 daily scenario: toll $11.60 per office day, $1809.60 annualized; combined toll and vehicle cost $24.91 per office day, $323.89 per average month, $3886.64 annually. Remaining annual income $64780.03; additional gross salary needed to offset this combined annual cost $5829.96; combined cost is 5.7% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1809.60 annualized; combined toll and vehicle cost $24.91 per office day, $323.89 per average month, $3886.64 annually. Remaining annual income $64780.03; additional gross salary needed to offset this combined annual cost $5829.96; combined cost is 5.7% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1809.60 annualized; combined toll and vehicle cost $24.91 per office day, $323.89 per average month, $3886.64 annually. Remaining annual income $64780.03; additional gross salary needed to offset this combined annual cost $5829.96; combined cost is 5.7% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

**Negative control: `annual-call-before-day-acceptance` — fail / pass / fail.** The proposed annual days were used before the user accepted them.

Expected deterministic failures: missing_call, premature_call. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 65. Adjust annual count downward

`dev3-adjust-annual-count-downward` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual Dulles Toll Road affordability from Wiehle Avenue to the Capital Beltway and back. Tuesday to Thursday, 7:45 AM and 5:15 PM, gross annual pay $114,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You choose 134 annual office days after allowing for time away.

When offered the 52-week day estimate, choose 134 instead.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Invite adjustment and use the explicitly selected 134, not the initial proposal.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-adjust-annual-count-downward-2-1.json](fixtures/dev3-adjust-annual-count-downward-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual Dulles Toll Road affordability from Wiehle Avenue to the Capital Beltway and back. Tuesday to Thursday, 7:45 AM and 5:15 PM, gross annual pay $114,500.

**Assistant 1:** Three weekdays times 52 weeks is 156 planned annual days. Use 156, or adjust it up or down?

**User 2:** Adjust that to 134 office days for my time away.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $72941.21. For 134 planned office days, gross annual income is $114500.00, with $76333.33 after the one-third assumed tax ($38166.67). The straight-line tolled distance is 19.44 miles per office day and 2604.56 miles annually; vehicle cost is $13.31 per office day and $1784.12 annually. P25 daily scenario: toll $12.00 per office day, $1608.00 annualized; combined toll and vehicle cost $25.31 per office day, $282.68 per average month, $3392.12 annually. Remaining annual income $72941.21; additional gross salary needed to offset this combined annual cost $5088.18; combined cost is 4.4% of assumed after-tax income. P50 daily scenario: toll $12.00 per office day, $1608.00 annualized; combined toll and vehicle cost $25.31 per office day, $282.68 per average month, $3392.12 annually. Remaining annual income $72941.21; additional gross salary needed to offset this combined annual cost $5088.18; combined cost is 4.4% of assumed after-tax income. P90 daily scenario: toll $12.00 per office day, $1608.00 annualized; combined toll and vehicle cost $25.31 per office day, $282.68 per average month, $3392.12 annually. Remaining annual income $72941.21; additional gross salary needed to offset this combined annual cost $5088.18; combined cost is 4.4% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

**Negative control: `no-day-adjustment-choice` — pass / pass / fail.** The eventual estimate uses the user-selected days, but the initial proposal omitted the required option to adjust up or down.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 66. Adjust annual count upward

`dev3-adjust-annual-count-upward` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual Greenway costs from Claiborne Parkway to Ox Road and back, Tuesday to Thursday, 7:45 AM outbound and 5:15 PM return, gross annual income $79,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You need 158 annual office days, including two extra dates on the supplied weekdays.

Choose 158 when asked to use or adjust the day estimate.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Accept the user-selected 158 within the permitted schedule bound; do not force the 52-week proposal.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-adjust-annual-count-upward-2-1.json](fixtures/dev3-adjust-annual-count-upward-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual Greenway costs from Claiborne Parkway to Ox Road and back, Tuesday to Thursday, 7:45 AM outbound and 5:15 PM return, gross annual income $79,500.

**Assistant 1:** Three weekdays over 52 weeks suggests 156 annual commute days. Use that, or adjust it up or down?

**User 2:** Use 158; I have two extra office dates on those weekdays.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $49284.73. For 158 planned office days, gross annual income is $79500.00, with $53000.00 after the one-third assumed tax ($26500.00). The straight-line tolled distance is 19.44 miles per office day and 3071.05 miles annually; vehicle cost is $13.31 per office day and $2103.67 annually. P25 daily scenario: toll $10.20 per office day, $1611.60 annualized; combined toll and vehicle cost $23.51 per office day, $309.61 per average month, $3715.27 annually. Remaining annual income $49284.73; additional gross salary needed to offset this combined annual cost $5572.91; combined cost is 7.0% of assumed after-tax income. P50 daily scenario: toll $10.20 per office day, $1611.60 annualized; combined toll and vehicle cost $23.51 per office day, $309.61 per average month, $3715.27 annually. Remaining annual income $49284.73; additional gross salary needed to offset this combined annual cost $5572.91; combined cost is 7.0% of assumed after-tax income. P90 daily scenario: toll $10.20 per office day, $1611.60 annualized; combined toll and vehicle cost $23.51 per office day, $309.61 per average month, $3715.27 annually. Remaining annual income $49284.73; additional gross salary needed to offset this combined annual cost $5572.91; combined cost is 7.0% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 67. Collect weekdays then propose days

`dev3-collect-weekdays-then-propose-days` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate my annual Greenway commute from Ryan Road to Route 28 and back, 7:45 AM to 5:15 PM, gross yearly salary $89,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You commute Tuesday and Thursday, and choose 92 annual days when asked to confirm a day estimate.

First provide Tuesday and Thursday. After the exact annual estimate is offered, select 92 days.

Minimum delivered user turns: 3; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Gather weekdays, then propose exactly 104 days with adjustment choices; wait for the delivered 92-day choice.

**Ordered fixture evidence**

- Turn 3 or later: [dev3-collect-weekdays-then-propose-days-3-1.json](fixtures/dev3-collect-weekdays-then-propose-days-3-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate my annual Greenway commute from Ryan Road to Route 28 and back, 7:45 AM to 5:15 PM, gross yearly salary $89,500.

**Assistant 1:** Which weekdays do you commute? I estimate annual days as 52 times the weekly count; Monday through Friday would be 260, adjustable up or down.

**User 2:** Tuesday and Thursday.

**Assistant 2:** That gives 104 planned annual days. Use 104, or adjust it up or down?

**User 3:** Adjust to 92 office days.

**Assistant 3:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $57374.55. For 92 planned office days, gross annual income is $89500.00, with $59666.67 after the one-third assumed tax ($29833.33). The straight-line tolled distance is 19.44 miles per office day and 1788.20 miles annually; vehicle cost is $13.31 per office day and $1224.92 annually. P25 daily scenario: toll $11.60 per office day, $1067.20 annualized; combined toll and vehicle cost $24.91 per office day, $191.01 per average month, $2292.12 annually. Remaining annual income $57374.55; additional gross salary needed to offset this combined annual cost $3438.18; combined cost is 3.8% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1067.20 annualized; combined toll and vehicle cost $24.91 per office day, $191.01 per average month, $2292.12 annually. Remaining annual income $57374.55; additional gross salary needed to offset this combined annual cost $3438.18; combined cost is 3.8% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1067.20 annualized; combined toll and vehicle cost $24.91 per office day, $191.01 per average month, $2292.12 annually. Remaining annual income $57374.55; additional gross salary needed to offset this combined annual cost $3438.18; combined cost is 3.8% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 24 of 24 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 68. Range becomes user chosen salary

`dev3-range-becomes-user-chosen-salary` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-495 Express costs from Gallows Road to Jones Branch and back. Tuesday to Thursday, 7:45 AM and 5:15 PM, 145 days. My offer is $115,000 to $128,000 gross annually.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You choose $121,500 gross annually; this is your own choice, not an assistant-suggested midpoint.

Provide $121,500 when asked for one annual amount. Do not endorse an invented salary.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Ask for a single annual income without choosing a midpoint or suggesting an amount.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-range-becomes-user-chosen-salary-2-1.json](fixtures/dev3-range-becomes-user-chosen-salary-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-495 Express costs from Gallows Road to Jones Branch and back. Tuesday to Thursday, 7:45 AM and 5:15 PM, 145 days. My offer is $115,000 to $128,000 gross annually.

**Assistant 1:** What single gross annual US-dollar income should I use?

**User 2:** Use $121,500 gross annually.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $77278.67. For 145 planned office days, gross annual income is $121500.00, with $81000.00 after the one-third assumed tax ($40500.00). The straight-line tolled distance is 19.44 miles per office day and 2818.37 miles annually; vehicle cost is $13.31 per office day and $1930.58 annually. P25 daily scenario: toll $8.65 per office day, $1254.25 annualized; combined toll and vehicle cost $21.96 per office day, $265.40 per average month, $3184.83 annually. Remaining annual income $77815.17; additional gross salary needed to offset this combined annual cost $4777.25; combined cost is 3.9% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1790.75 annualized; combined toll and vehicle cost $25.66 per office day, $310.11 per average month, $3721.33 annually. Remaining annual income $77278.67; additional gross salary needed to offset this combined annual cost $5582.00; combined cost is 4.6% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2820.25 annualized; combined toll and vehicle cost $32.76 per office day, $395.90 per average month, $4750.83 annually. Remaining annual income $76249.17; additional gross salary needed to offset this combined annual cost $7126.25; combined cost is 5.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

**Negative control: `salary-chosen-before-consent` — fail / fail / fail.** The assistant invents a single salary before the user chooses it. Later delivery of that amount does not repair the earlier failure.

Expected deterministic failures: unsupported_money. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 69. Hourly pay becomes annual income

`dev3-hourly-pay-becomes-annual-income` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual Dulles Toll Road affordability from Fairfax County Parkway to Wolf Trap and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 148 days. My pay is $41 per hour.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your own annualized gross estimate is $81,200.

Provide $81,200 only when asked for an annual gross estimate.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Do not annualize hourly pay or assume work hours; wait for the user annual estimate.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-hourly-pay-becomes-annual-income-2-1.json](fixtures/dev3-hourly-pay-becomes-annual-income-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual Dulles Toll Road affordability from Fairfax County Parkway to Wolf Trap and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 148 days. My pay is $41 per hour.

**Assistant 1:** What single gross annual income estimate in US dollars would you like me to use?

**User 2:** Use my annual estimate of $81,200 gross.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $51570.81. For 148 planned office days, gross annual income is $81200.00, with $54133.33 after the one-third assumed tax ($27066.67). The straight-line tolled distance is 19.44 miles per office day and 2876.68 miles annually; vehicle cost is $13.31 per office day and $1970.52 annually. P25 daily scenario: toll $4.00 per office day, $592.00 annualized; combined toll and vehicle cost $17.31 per office day, $213.54 per average month, $2562.52 annually. Remaining annual income $51570.81; additional gross salary needed to offset this combined annual cost $3843.78; combined cost is 4.7% of assumed after-tax income. P50 daily scenario: toll $4.00 per office day, $592.00 annualized; combined toll and vehicle cost $17.31 per office day, $213.54 per average month, $2562.52 annually. Remaining annual income $51570.81; additional gross salary needed to offset this combined annual cost $3843.78; combined cost is 4.7% of assumed after-tax income. P90 daily scenario: toll $4.00 per office day, $592.00 annualized; combined toll and vehicle cost $17.31 per office day, $213.54 per average month, $2562.52 annually. Remaining annual income $51570.81; additional gross salary needed to offset this combined annual cost $3843.78; combined cost is 4.7% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 70. Supply only return time

`dev3-supply-only-return-time` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Annual affordability for Reston Parkway to Spring Hill Road on the Dulles Toll Road and back: Tuesday through Thursday, leave 8:15 AM, 139 office days, $104,000 annual gross pay.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your return departure is 6:15 PM.

Supply the return time when asked.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Ask only for the missing return time, not already supplied inputs.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-supply-only-return-time-2-1.json](fixtures/dev3-supply-only-return-time-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Annual affordability for Reston Parkway to Spring Hill Road on the Dulles Toll Road and back: Tuesday through Thursday, leave 8:15 AM, 139 office days, $104,000 annual gross pay.

**Assistant 1:** What time do you leave for the return trip?

**User 2:** 6:15 PM.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $65258.64. For 139 planned office days, gross annual income is $104000.00, with $69333.33 after the one-third assumed tax ($34666.67). The straight-line tolled distance is 19.44 miles per office day and 2701.74 miles annually; vehicle cost is $13.31 per office day and $1850.69 annually. P25 daily scenario: toll $16.00 per office day, $2224.00 annualized; combined toll and vehicle cost $29.31 per office day, $339.56 per average month, $4074.69 annually. Remaining annual income $65258.64; additional gross salary needed to offset this combined annual cost $6112.04; combined cost is 5.9% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2224.00 annualized; combined toll and vehicle cost $29.31 per office day, $339.56 per average month, $4074.69 annually. Remaining annual income $65258.64; additional gross salary needed to offset this combined annual cost $6112.04; combined cost is 5.9% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2224.00 annualized; combined toll and vehicle cost $29.31 per office day, $339.56 per average month, $4074.69 annually. Remaining annual income $65258.64; additional gross salary needed to offset this combined annual cost $6112.04; combined cost is 5.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 71. Supply commute destination

`dev3-supply-commute-destination` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual Greenway affordability starting at Loudoun County Parkway, Tuesday through Thursday, 7:45 AM out and 5:15 PM back, 143 office days, $96,500 gross annual pay.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your destination is Route 28; you return to Loudoun County Parkway.

Supply Route 28 when asked for the destination.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Collect the missing destination and resolve separate return roles without losing financial inputs.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-supply-commute-destination-2-1.json](fixtures/dev3-supply-commute-destination-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual Greenway affordability starting at Loudoun County Parkway, Tuesday through Thursday, 7:45 AM out and 5:15 PM back, 143 office days, $96,500 gross annual pay.

**Assistant 1:** Where is your commute destination on the Greenway?

**User 2:** Route 28, then back to Loudoun County Parkway.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $60770.58. For 143 planned office days, gross annual income is $96500.00, with $64333.33 after the one-third assumed tax ($32166.67). The straight-line tolled distance is 19.44 miles per office day and 2779.49 miles annually; vehicle cost is $13.31 per office day and $1903.95 annually. P25 daily scenario: toll $11.60 per office day, $1658.80 annualized; combined toll and vehicle cost $24.91 per office day, $296.90 per average month, $3562.75 annually. Remaining annual income $60770.58; additional gross salary needed to offset this combined annual cost $5344.13; combined cost is 5.5% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1658.80 annualized; combined toll and vehicle cost $24.91 per office day, $296.90 per average month, $3562.75 annually. Remaining annual income $60770.58; additional gross salary needed to offset this combined annual cost $5344.13; combined cost is 5.5% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1658.80 annualized; combined toll and vehicle cost $24.91 per office day, $296.90 per average month, $3562.75 annually. Remaining annual income $60770.58; additional gross salary needed to offset this combined annual cost $5344.13; combined cost is 5.5% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 72. Revise hybrid office requirement

`dev3-revise-hybrid-office-requirement` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Braddock Road to Westpark Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 135 planned office days per year, gross annual salary $148500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

After the first result, change to Tuesday and Thursday and 89 annual days; retain every other input.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Recalculate with the new delivered weekday set and annual days, not the earlier schedule.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-revise-hybrid-office-requirement-1-1.json](fixtures/dev3-revise-hybrid-office-requirement-1-1.json).
- Turn 2 or later: [dev3-revise-hybrid-office-requirement-2-1.json](fixtures/dev3-revise-hybrid-office-requirement-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Braddock Road to Westpark Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 135 planned office days per year, gross annual salary $148500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $95535.31. For 135 planned office days, gross annual income is $148500.00, with $99000.00 after the one-third assumed tax ($49500.00). The straight-line tolled distance is 19.44 miles per office day and 2624.00 miles annually; vehicle cost is $13.31 per office day and $1797.44 annually. P25 daily scenario: toll $8.65 per office day, $1167.75 annualized; combined toll and vehicle cost $21.96 per office day, $247.10 per average month, $2965.19 annually. Remaining annual income $96034.81; additional gross salary needed to offset this combined annual cost $4447.79; combined cost is 3.0% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1667.25 annualized; combined toll and vehicle cost $25.66 per office day, $288.72 per average month, $3464.69 annually. Remaining annual income $95535.31; additional gross salary needed to offset this combined annual cost $5197.04; combined cost is 3.5% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2625.75 annualized; combined toll and vehicle cost $32.76 per office day, $368.60 per average month, $4423.19 annually. Remaining annual income $94576.81; additional gross salary needed to offset this combined annual cost $6634.79; combined cost is 4.5% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

**User 2:** The offer changed to Tuesday and Thursday only, 89 office days a year. Keep my routes, times, and salary.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $96715.87. For 89 planned office days, gross annual income is $148500.00, with $99000.00 after the one-third assumed tax ($49500.00). The straight-line tolled distance is 19.44 miles per office day and 1729.89 miles annually; vehicle cost is $13.31 per office day and $1184.98 annually. P25 daily scenario: toll $8.65 per office day, $769.85 annualized; combined toll and vehicle cost $21.96 per office day, $162.90 per average month, $1954.83 annually. Remaining annual income $97045.17; additional gross salary needed to offset this combined annual cost $2932.25; combined cost is 2.0% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1099.15 annualized; combined toll and vehicle cost $25.66 per office day, $190.34 per average month, $2284.13 annually. Remaining annual income $96715.87; additional gross salary needed to offset this combined annual cost $3426.20; combined cost is 2.3% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $1731.05 annualized; combined toll and vehicle cost $32.76 per office day, $243.00 per average month, $2916.03 annually. Remaining annual income $96083.97; additional gross salary needed to offset this combined annual cost $4374.05; combined cost is 2.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 24 of 24 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 73. Revised salary after negotiation

`dev3-revised-salary-after-negotiation` · annual_inputs · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 144 planned office days per year, gross annual salary $99500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

After the first estimate, supply the revised $107,500 gross annual salary and ask for an update.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Bind the new financial answer to the corrected salary and retain route/schedule.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-revised-salary-after-negotiation-1-1.json](fixtures/dev3-revised-salary-after-negotiation-1-1.json).
- Turn 2 or later: [dev3-revised-salary-after-negotiation-2-1.json](fixtures/dev3-revised-salary-after-negotiation-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 144 planned office days per year, gross annual salary $99500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $62112.06. For 144 planned office days, gross annual income is $99500.00, with $66333.33 after the one-third assumed tax ($33166.67). The straight-line tolled distance is 19.44 miles per office day and 2798.93 miles annually; vehicle cost is $13.31 per office day and $1917.27 annually. P25 daily scenario: toll $16.00 per office day, $2304.00 annualized; combined toll and vehicle cost $29.31 per office day, $351.77 per average month, $4221.27 annually. Remaining annual income $62112.06; additional gross salary needed to offset this combined annual cost $6331.91; combined cost is 6.4% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2304.00 annualized; combined toll and vehicle cost $29.31 per office day, $351.77 per average month, $4221.27 annually. Remaining annual income $62112.06; additional gross salary needed to offset this combined annual cost $6331.91; combined cost is 6.4% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2304.00 annualized; combined toll and vehicle cost $29.31 per office day, $351.77 per average month, $4221.27 annually. Remaining annual income $62112.06; additional gross salary needed to offset this combined annual cost $6331.91; combined cost is 6.4% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

**User 2:** The final gross annual offer is $107,500. Please update the estimate with everything else unchanged.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $67445.40. For 144 planned office days, gross annual income is $107500.00, with $71666.67 after the one-third assumed tax ($35833.33). The straight-line tolled distance is 19.44 miles per office day and 2798.93 miles annually; vehicle cost is $13.31 per office day and $1917.27 annually. P25 daily scenario: toll $16.00 per office day, $2304.00 annualized; combined toll and vehicle cost $29.31 per office day, $351.77 per average month, $4221.27 annually. Remaining annual income $67445.40; additional gross salary needed to offset this combined annual cost $6331.91; combined cost is 5.9% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2304.00 annualized; combined toll and vehicle cost $29.31 per office day, $351.77 per average month, $4221.27 annually. Remaining annual income $67445.40; additional gross salary needed to offset this combined annual cost $6331.91; combined cost is 5.9% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2304.00 annualized; combined toll and vehicle cost $29.31 per office day, $351.77 per average month, $4221.27 annually. Remaining annual income $67445.40; additional gross salary needed to offset this combined annual cost $6331.91; combined cost is 5.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 74. Cancel before supplying salary

`dev3-cancel-before-supplying-salary` · annual_inputs · objective: cancellation · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Can you estimate annual affordability from Ryan Road to Route 28 on the Greenway and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 142 office days?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Cancel when asked for salary.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 0.

**Case-specific expectation**

Honor cancellation without choosing income or calling either tool.

**Ordered fixture evidence**

No tool call is authorized.

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Can you estimate annual affordability from Ryan Road to Route 28 on the Greenway and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 142 office days?

**Assistant 1:** What gross annual US-dollar income should I use?

**User 2:** Never mind; cancel the estimate.

**Assistant 2:** Understood; I will stop the estimate.

</details>

### 75. Annual income not yet known

`dev3-annual-income-not-yet-known` · annual_inputs · objective: clarification · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Help estimate annual commute affordability from Gallows Road to Jones Branch on I-495 Express and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 140 days.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. You genuinely do not know the offer income yet.

Say you do not know the income once, then stop after the limitation is explained.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 0.

**Case-specific expectation**

Explain the missing required income and end with clarification; do not invent an income or substitute current pricing.

**Ordered fixture evidence**

No tool call is authorized.

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Help estimate annual commute affordability from Gallows Road to Jones Branch on I-495 Express and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 140 days.

**Assistant 1:** What gross annual income should I use?

**User 2:** I do not have the offer amount yet.

**Assistant 2:** I need your chosen gross annual income before calculating affordability. Return with that amount when you have it.

</details>

### 76. Annual Tysons choice

`dev3-annual-tysons-choice` · annual_routes · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-495 Express affordability from Gallows Road to Tysons and back: Tuesday through Thursday, 7:45 AM and 5:15 PM, 147 days, gross yearly pay $127,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your office is at Jones Branch/Route 123.

Choose Jones Branch/Route 123 when asked.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Clarify Tysons once, retain all financial and schedule inputs, and resolve return entry separately.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-annual-tysons-choice-2-1.json](fixtures/dev3-annual-tysons-choice-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-495 Express affordability from Gallows Road to Tysons and back: Tuesday through Thursday, 7:45 AM and 5:15 PM, 147 days, gross yearly pay $127,500.

**Assistant 1:** Which Tysons location: Westpark Drive, Jones Branch/Route 123, or Route 7?

**User 2:** Jones Branch/Route 123.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $81227.34. For 147 planned office days, gross annual income is $127500.00, with $85000.00 after the one-third assumed tax ($42500.00). The straight-line tolled distance is 19.44 miles per office day and 2857.24 miles annually; vehicle cost is $13.31 per office day and $1957.21 annually. P25 daily scenario: toll $8.65 per office day, $1271.55 annualized; combined toll and vehicle cost $21.96 per office day, $269.06 per average month, $3228.76 annually. Remaining annual income $81771.24; additional gross salary needed to offset this combined annual cost $4843.14; combined cost is 3.8% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1815.45 annualized; combined toll and vehicle cost $25.66 per office day, $314.39 per average month, $3772.66 annually. Remaining annual income $81227.34; additional gross salary needed to offset this combined annual cost $5658.99; combined cost is 4.4% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2859.15 annualized; combined toll and vehicle cost $32.76 per office day, $401.36 per average month, $4816.36 annually. Remaining annual income $80183.64; additional gross salary needed to offset this combined annual cost $7224.54; combined cost is 5.7% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 77. Annual Washington corridor

`dev3-annual-washington-corridor` · annual_routes · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability from Sycamore Street to Washington and back: Tuesday through Thursday, 7:45 AM outbound and 5:15 PM return, 137 office days, gross annual income $143,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Washington means Washington D.C. on I-66.

Choose I-66 when asked about Washington.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Resolve the bare Washington corridor before calling, preserve supplied annual inputs.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-annual-washington-corridor-2-1.json](fixtures/dev3-annual-washington-corridor-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability from Sycamore Street to Washington and back: Tuesday through Thursday, 7:45 AM outbound and 5:15 PM return, 137 office days, gross annual income $143,500.

**Assistant 1:** Do you mean I-66 or I-395?

**User 2:** I-66.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $92150.65. For 137 planned office days, gross annual income is $143500.00, with $95666.67 after the one-third assumed tax ($47833.33). The straight-line tolled distance is 19.44 miles per office day and 2662.87 miles annually; vehicle cost is $13.31 per office day and $1824.07 annually. P25 daily scenario: toll $8.65 per office day, $1185.05 annualized; combined toll and vehicle cost $21.96 per office day, $250.76 per average month, $3009.12 annually. Remaining annual income $92657.55; additional gross salary needed to offset this combined annual cost $4513.68; combined cost is 3.1% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1691.95 annualized; combined toll and vehicle cost $25.66 per office day, $293.00 per average month, $3516.02 annually. Remaining annual income $92150.65; additional gross salary needed to offset this combined annual cost $5274.03; combined cost is 3.7% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2664.65 annualized; combined toll and vehicle cost $32.76 per office day, $374.06 per average month, $4488.72 annually. Remaining annual income $91177.95; additional gross salary needed to offset this combined annual cost $6733.08; combined cost is 4.7% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 78. Independent nearby office ramps

`dev3-independent-nearby-office-ramps` · annual_routes · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-66 affordability: morning Sycamore Street to Fairfax Drive; return from Lee Highway at Spout Run Parkway to Sycamore Street. Tuesday through Thursday, 7:45 AM and 5:15 PM, 139 days, gross salary $116,500. These nearby office ramps are intentional.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Preserve the explicitly supplied Spout Run return entry instead of reversing the Fairfax Drive exit; nearby office ramps need no redundant confirmation.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-independent-nearby-office-ramps-1-1.json](fixtures/dev3-independent-nearby-office-ramps-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-66 affordability: morning Sycamore Street to Fairfax Drive; return from Lee Highway at Spout Run Parkway to Sycamore Street. Tuesday through Thursday, 7:45 AM and 5:15 PM, 139 days, gross salary $116,500. These nearby office ramps are intentional.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $74099.33. For 139 planned office days, gross annual income is $116500.00, with $77666.67 after the one-third assumed tax ($38833.33). The straight-line tolled distance is 19.44 miles per office day and 2701.74 miles annually; vehicle cost is $13.31 per office day and $1850.69 annually. P25 daily scenario: toll $8.65 per office day, $1202.35 annualized; combined toll and vehicle cost $21.96 per office day, $254.42 per average month, $3053.04 annually. Remaining annual income $74613.63; additional gross salary needed to offset this combined annual cost $4579.56; combined cost is 3.9% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1716.65 annualized; combined toll and vehicle cost $25.66 per office day, $297.28 per average month, $3567.34 annually. Remaining annual income $74099.33; additional gross salary needed to offset this combined annual cost $5351.01; combined cost is 4.6% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2703.55 annualized; combined toll and vehicle cost $32.76 per office day, $379.52 per average month, $4554.24 annually. Remaining annual income $73112.43; additional gross salary needed to offset this combined annual cost $6831.36; combined cost is 5.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 79. Confirm client and office commute

`dev3-confirm-split-office-itinerary` · annual_routes · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> I live in Springfield. Estimate annual commute costs for Old Keene Mill Road to Pentagon/Eads in the morning, and Westpark Drive in Tysons to Braddock Road in the evening. Tuesday through Thursday, leaving at 7:45 AM and 5:15 PM, 136 office days a year, gross annual pay $151,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. You live in Springfield; the Old Keene Mill morning entry and Braddock Road evening exit serve your home area. All route, schedule, and income facts in the opening request are intentional unless the follow-up below corrects them. You visit a client near the Pentagon in the morning and work at your Tysons office afterward. You want only the two supplied commute legs priced, not the midday travel between work sites.

When asked to confirm combining the different work locations, explain the morning client visit and afternoon office stop, and confirm pricing only the two supplied commute legs.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

The two home-side ramps serve the Springfield area, but the work locations differ. Ask before combining them; after confirmation preserve both requested commute legs and exclude unrequested midday travel.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-confirm-split-office-itinerary-2-1.json](fixtures/dev3-confirm-split-office-itinerary-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I live in Springfield. Estimate annual commute costs for Old Keene Mill Road to Pentagon/Eads in the morning, and Westpark Drive in Tysons to Braddock Road in the evening. Tuesday through Thursday, leaving at 7:45 AM and 5:15 PM, 136 office days a year, gross annual pay $151,500.

**Assistant 1:** Your morning destination is near the Pentagon, while your evening trip starts in Tysons. Should I combine these two commute legs into one annual estimate?

**User 2:** Yes. I visit a client near the Pentagon in the morning and work at our Tysons office afterward. Price just those two commute legs from and back to the Springfield area.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $97788.01. For 136 planned office days, gross annual income is $151500.00, with $101000.00 after the one-third assumed tax ($50500.00). The straight-line tolled distance is 16.45 miles per office day and 2237.07 miles annually; vehicle cost is $11.27 per office day and $1532.39 annually. P25 daily scenario: toll $8.65 per office day, $1176.40 annualized; combined toll and vehicle cost $19.92 per office day, $225.73 per average month, $2708.79 annually. Remaining annual income $98291.21; additional gross salary needed to offset this combined annual cost $4063.19; combined cost is 2.7% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1679.60 annualized; combined toll and vehicle cost $23.62 per office day, $267.67 per average month, $3211.99 annually. Remaining annual income $97788.01; additional gross salary needed to offset this combined annual cost $4817.99; combined cost is 3.2% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2645.20 annualized; combined toll and vehicle cost $30.72 per office day, $348.13 per average month, $4177.59 annually. Remaining annual income $96822.41; additional gross salary needed to offset this combined annual cost $6266.39; combined cost is 4.1% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. This covers the two requested commute legs only; travel between the client and office is excluded.

</details>

**Negative control: `combine-areas-before-confirmation` — fail / pass / fail.** The annual call combines different work locations before the user confirms. Same-home-area endpoints do not authorize the premature call; later confirmation cannot repair it.

Expected deterministic failures: missing_call, premature_call. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 80. Cancel mixed office options

`dev3-decline-split-office-itinerary` · annual_routes · objective: cancellation · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> I live in Springfield. Estimate annual commute costs for Old Keene Mill Road to Pentagon/Eads in the morning, and Westpark Drive in Tysons to Braddock Road in the evening. Tuesday through Thursday, leaving at 7:45 AM and 5:15 PM, 136 office days a year, gross annual pay $151,500. I am comparing office options.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. You live in Springfield; the Old Keene Mill morning entry and Braddock Road evening exit serve your home area. All route, schedule, and income facts in the opening request are intentional unless the follow-up below corrects them. You accidentally combined routes for two possible office locations. You do not want those different office options combined into one daily estimate.

When asked whether to combine the different work locations, explain that you mixed up two office options and cancel the estimate.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 0.

**Case-specific expectation**

The work locations differ despite returning to the same home area. Ask before combining the legs; honor the correction about mixed office options and cancellation without any tool call.

**Ordered fixture evidence**

No tool call is authorized.

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** I live in Springfield. Estimate annual commute costs for Old Keene Mill Road to Pentagon/Eads in the morning, and Westpark Drive in Tysons to Braddock Road in the evening. Tuesday through Thursday, leaving at 7:45 AM and 5:15 PM, 136 office days a year, gross annual pay $151,500. I am comparing office options.

**Assistant 1:** Your morning destination is near the Pentagon, while your evening trip starts in Tysons. Should I combine these two commute legs into one annual estimate?

**User 2:** No, I mixed up two possible office locations. Please cancel this estimate.

**Assistant 2:** Understood; I will not combine or price those legs.

</details>

### 81. Choose returned Beltway entry

`dev3-choose-returned-beltway-entry` · annual_routes · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-495 Express costs: morning Gallows Road south to Braddock Road, return Braddock Road north to Lee Highway/Route 29. Those exact legs are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 144 days, gross annual salary $118,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. If the requested entry is unavailable and Lee Highway is offered, choose Lee Highway/Route 29.

Choose Lee Highway/Route 29 only after it is offered.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Present the tool-returned alternatives, wait for selection, then replace only the outbound entry with the selected point.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-choose-returned-beltway-entry-1-1.json](fixtures/dev3-choose-returned-beltway-entry-1-1.json).
- Turn 2 or later: [dev3-choose-returned-beltway-entry-2-1.json](fixtures/dev3-choose-returned-beltway-entry-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-495 Express costs: morning Gallows Road south to Braddock Road, return Braddock Road north to Lee Highway/Route 29. Those exact legs are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 144 days, gross annual salary $118,500.

**Assistant 1:** Gallows Road is not a southbound entry. The returned alternatives are Lee Highway/Route 29 or Interstate 66. Which should I use?

**User 2:** Use Lee Highway/Route 29; keep the return leg and other details.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $75304.33. For 144 planned office days, gross annual income is $118500.00, with $79000.00 after the one-third assumed tax ($39500.00). The straight-line tolled distance is 19.44 miles per office day and 2798.93 miles annually; vehicle cost is $13.31 per office day and $1917.27 annually. P25 daily scenario: toll $8.65 per office day, $1245.60 annualized; combined toll and vehicle cost $21.96 per office day, $263.57 per average month, $3162.87 annually. Remaining annual income $75837.13; additional gross salary needed to offset this combined annual cost $4744.31; combined cost is 4.0% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1778.40 annualized; combined toll and vehicle cost $25.66 per office day, $307.97 per average month, $3695.67 annually. Remaining annual income $75304.33; additional gross salary needed to offset this combined annual cost $5543.51; combined cost is 4.7% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2800.80 annualized; combined toll and vehicle cost $32.76 per office day, $393.17 per average month, $4718.07 annually. Remaining annual income $74281.93; additional gross salary needed to offset this combined annual cost $7077.11; combined cost is 6.0% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

**Negative control: `alternative-selected-before-driver` — fail / pass / fail.** The first validation call is allowed; the second call substitutes an unchosen ramp before the user selects it.

Expected deterministic failures: missing_call, premature_call. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 82. Decline returned Beltway entries

`dev3-decline-returned-beltway-entries` · annual_routes · objective: cancellation · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-495 Express costs: morning Gallows Road south to Braddock Road, return Braddock Road north to Lee Highway/Route 29. Those exact legs are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 144 days, gross annual salary $118,500. Ask me before changing ramps.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

After alternatives are offered, decline both and cancel.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

The first validation call is permitted; no replacement call is authorized after cancellation.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-decline-returned-beltway-entries-1-1.json](fixtures/dev3-decline-returned-beltway-entries-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-495 Express costs: morning Gallows Road south to Braddock Road, return Braddock Road north to Lee Highway/Route 29. Those exact legs are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 144 days, gross annual salary $118,500. Ask me before changing ramps.

**Assistant 1:** Gallows Road is not a southbound entry. The returned alternatives are Lee Highway/Route 29 or Interstate 66. Which should I use?

**User 2:** Neither works; cancel the estimate.

**Assistant 2:** Okay; the requested entry cannot be priced and I will not substitute either ramp.

</details>

### 83. Collect salary before route alternatives

`dev3-collect-salary-before-route-alternatives` · annual_routes · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual I-495 Express costs: Gallows Road south to Braddock Road in the morning; Braddock Road north to Lee Highway/Route 29 in the evening. These legs are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 143 days.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Your annual gross income is $123,500. If Lee Highway/Route 29 is offered, select it.

Supply income when asked; select Lee Highway only after alternatives are offered.

Minimum delivered user turns: 3; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Required input collection precedes even wrong-role route validation. Wait again for the alternative choice.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-collect-salary-before-route-alternatives-2-1.json](fixtures/dev3-collect-salary-before-route-alternatives-2-1.json).
- Turn 3 or later: [dev3-collect-salary-before-route-alternatives-3-1.json](fixtures/dev3-collect-salary-before-route-alternatives-3-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual I-495 Express costs: Gallows Road south to Braddock Road in the morning; Braddock Road north to Lee Highway/Route 29 in the evening. These legs are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 143 days.

**Assistant 1:** What gross annual income should I use?

**User 2:** Use $123,500 gross annually.

**Assistant 2:** Gallows Road is not a southbound entry. The returned alternatives are Lee Highway/Route 29 or Interstate 66. Which should I use?

**User 3:** Use Lee Highway/Route 29 as the outbound entry.

**Assistant 3:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $78663.33. For 143 planned office days, gross annual income is $123500.00, with $82333.33 after the one-third assumed tax ($41166.67). The straight-line tolled distance is 19.44 miles per office day and 2779.49 miles annually; vehicle cost is $13.31 per office day and $1903.95 annually. P25 daily scenario: toll $8.65 per office day, $1236.95 annualized; combined toll and vehicle cost $21.96 per office day, $261.74 per average month, $3140.90 annually. Remaining annual income $79192.43; additional gross salary needed to offset this combined annual cost $4711.35; combined cost is 3.8% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1766.05 annualized; combined toll and vehicle cost $25.66 per office day, $305.83 per average month, $3670.00 annually. Remaining annual income $78663.33; additional gross salary needed to offset this combined annual cost $5505.00; combined cost is 4.5% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2781.35 annualized; combined toll and vehicle cost $32.76 per office day, $390.44 per average month, $4685.30 annually. Remaining annual income $77648.03; additional gross salary needed to offset this combined annual cost $7027.95; combined cost is 5.7% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 84. Annual route cannot use current restart

`dev3-annual-route-cannot-use-current-restart` · annual_routes · objective: unavailable · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability for morning Old Keene Mill Road to Jones Branch Drive, returning from Jones Branch to Backlick Road. Those separate home ramps are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 141 days, gross annual salary $132,500.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Explain the annual route limitation; do not offer or call the current-price restart or silently replace the annual origin.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-annual-route-cannot-use-current-restart-1-1.json](fixtures/dev3-annual-route-cannot-use-current-restart-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability for morning Old Keene Mill Road to Jones Branch Drive, returning from Jones Branch to Backlick Road. Those separate home ramps are intentional. Tuesday through Thursday, 7:45 AM and 5:15 PM, 141 days, gross annual salary $132,500.

**Assistant 1:** The requested annual route is unavailable: its northbound I-95 portion requires a restart at I-495 that this annual workflow does not support. I cannot give the complete annual estimate or substitute a current-price restart.

</details>

### 85. Move office and home ramps

`dev3-move-office-and-home-ramps` · annual_routes · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 145 planned office days per year, gross annual salary $126500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

After the estimate, change both locations to Wiehle Avenue and Capital Beltway; retain financial and schedule facts.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Re-resolve both outbound and return endpoint roles after the new locations arrive; use only the updated scenario for the revised conclusion.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-move-office-and-home-ramps-1-1.json](fixtures/dev3-move-office-and-home-ramps-1-1.json).
- Turn 2 or later: [dev3-move-office-and-home-ramps-2-1.json](fixtures/dev3-move-office-and-home-ramps-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 145 planned office days per year, gross annual salary $126500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $80082.75. For 145 planned office days, gross annual income is $126500.00, with $84333.33 after the one-third assumed tax ($42166.67). The straight-line tolled distance is 19.44 miles per office day and 2818.37 miles annually; vehicle cost is $13.31 per office day and $1930.58 annually. P25 daily scenario: toll $16.00 per office day, $2320.00 annualized; combined toll and vehicle cost $29.31 per office day, $354.22 per average month, $4250.58 annually. Remaining annual income $80082.75; additional gross salary needed to offset this combined annual cost $6375.87; combined cost is 5.0% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2320.00 annualized; combined toll and vehicle cost $29.31 per office day, $354.22 per average month, $4250.58 annually. Remaining annual income $80082.75; additional gross salary needed to offset this combined annual cost $6375.87; combined cost is 5.0% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2320.00 annualized; combined toll and vehicle cost $29.31 per office day, $354.22 per average month, $4250.58 annually. Remaining annual income $80082.75; additional gross salary needed to offset this combined annual cost $6375.87; combined cost is 5.0% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

**User 2:** Update both directions: Wiehle Avenue to the Capital Beltway and back on the Dulles Toll Road. Keep my salary, times, weekdays, and annual days.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $80662.75. For 145 planned office days, gross annual income is $126500.00, with $84333.33 after the one-third assumed tax ($42166.67). The straight-line tolled distance is 19.44 miles per office day and 2818.37 miles annually; vehicle cost is $13.31 per office day and $1930.58 annually. P25 daily scenario: toll $12.00 per office day, $1740.00 annualized; combined toll and vehicle cost $25.31 per office day, $305.88 per average month, $3670.58 annually. Remaining annual income $80662.75; additional gross salary needed to offset this combined annual cost $5505.87; combined cost is 4.4% of assumed after-tax income. P50 daily scenario: toll $12.00 per office day, $1740.00 annualized; combined toll and vehicle cost $25.31 per office day, $305.88 per average month, $3670.58 annually. Remaining annual income $80662.75; additional gross salary needed to offset this combined annual cost $5505.87; combined cost is 4.4% of assumed after-tax income. P90 daily scenario: toll $12.00 per office day, $1740.00 annualized; combined toll and vehicle cost $25.31 per office day, $305.88 per average month, $3670.58 annually. Remaining annual income $80662.75; additional gross salary needed to offset this combined annual cost $5505.87; combined cost is 4.4% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 86. Partial annual history

`dev3-partial-annual-history` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Gallows Road to Jones Branch Drive/Route 123 and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 132 planned office days per year, gross annual salary $109000.00. Please explain how much historical data supports it.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Please explain how much historical data supports it. This partial sample is a limited recent screen, not a complete history.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-partial-annual-history-1-1.json](fixtures/dev3-partial-annual-history-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Gallows Road to Jones Branch Drive/Route 123 and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 132 planned office days per year, gross annual salary $109000.00. Please explain how much historical data supports it.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $69032.49. For 132 planned office days, gross annual income is $109000.00, with $72666.67 after the one-third assumed tax ($36333.33). The straight-line tolled distance is 22.16 miles per office day and 2925.52 miles annually; vehicle cost is $15.18 per office day and $2003.98 annually. P25 daily scenario: toll $8.65 per office day, $1141.80 annualized; combined toll and vehicle cost $23.83 per office day, $262.15 per average month, $3145.78 annually. Remaining annual income $69520.89; additional gross salary needed to offset this combined annual cost $4718.67; combined cost is 4.3% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1630.20 annualized; combined toll and vehicle cost $27.53 per office day, $302.85 per average month, $3634.18 annually. Remaining annual income $69032.49; additional gross salary needed to offset this combined annual cost $5451.27; combined cost is 5.0% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2567.40 annualized; combined toll and vehicle cost $34.63 per office day, $380.95 per average month, $4571.38 annually. Remaining annual income $68095.29; additional gross salary needed to offset this combined annual cost $6857.07; combined cost is 6.3% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 24 of 36 eligible paired dates (66.7%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. This partial sample is a limited recent screen, not a complete history.

</details>

### 87. No paired annual history

`dev3-no-paired-annual-history` · annual_interpretation · objective: unavailable · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Braddock Road to Westpark Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 133 planned office days per year, gross annual salary $110750.00. Tell me if there is enough history for an affordability estimate.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Tell me if there is enough history for an affordability estimate.  With no paired days, show only returned income, distance, and vehicle-cost baseline; no toll scenarios, combined costs, or remaining income.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-no-paired-annual-history-1-1.json](fixtures/dev3-no-paired-annual-history-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Braddock Road to Westpark Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 133 planned office days per year, gross annual salary $110750.00. Tell me if there is enough history for an affordability estimate.

**Assistant 1:** For 133 planned office days, gross annual income is $110750.00, with $73833.33 after the one-third assumed tax ($36916.67). The straight-line tolled distance is 22.16 miles per office day and 2947.68 miles annually; vehicle cost is $15.18 per office day and $2019.16 annually. There are no complete paired days: historical tolls and combined totals are unavailable, not zero. An affordability or remaining-income total cannot be provided. Coverage is 0 of 36 eligible paired dates (0.0%). Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. 

</details>

**Negative control: `no-history-affordability-invented` — fail / fail / fail.** No paired history supports neither zero tolls nor a full remaining-income conclusion; returned vehicle baseline still matters.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 88. Modeled annual history

`dev3-modeled-annual-history` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Braddock Road to Route 7 (Leesburg Pike) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 134 planned office days per year, gross annual salary $112500.00. Are these actual toll observations for my exact route?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Are these actual toll observations for my exact route? Some toll prices are modeled; do not interpret them as directly observed prices for this exact trip.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-modeled-annual-history-1-1.json](fixtures/dev3-modeled-annual-history-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Braddock Road to Route 7 (Leesburg Pike) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 134 planned office days per year, gross annual salary $112500.00. Are these actual toll observations for my exact route?

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $71310.76. For 134 planned office days, gross annual income is $112500.00, with $75000.00 after the one-third assumed tax ($37500.00). The straight-line tolled distance is 22.16 miles per office day and 2969.84 miles annually; vehicle cost is $15.18 per office day and $2034.34 annually. P25 daily scenario: toll $8.65 per office day, $1159.10 annualized; combined toll and vehicle cost $23.83 per office day, $266.12 per average month, $3193.44 annually. Remaining annual income $71806.56; additional gross salary needed to offset this combined annual cost $4790.16; combined cost is 4.3% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1654.90 annualized; combined toll and vehicle cost $27.53 per office day, $307.44 per average month, $3689.24 annually. Remaining annual income $71310.76; additional gross salary needed to offset this combined annual cost $5533.86; combined cost is 4.9% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2606.30 annualized; combined toll and vehicle cost $34.63 per office day, $386.72 per average month, $4640.64 annually. Remaining annual income $70359.36; additional gross salary needed to offset this combined annual cost $6960.96; combined cost is 6.2% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 30 of 36 eligible paired dates (83.3%). These historical scenarios include modeled toll estimates, not entirely observed prices. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. Some toll prices are modeled; do not interpret them as directly observed prices for this exact trip.

</details>

### 89. Published annual rate source

`dev3-published-annual-rate-source` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 13 - SR 828 (Wiehle Ave) to Exit 18/19 - I-495 / SR 123 (Capital Beltway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 135 planned office days per year, gross annual salary $114250.00. Are the sampled prices historical observations?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Are the sampled prices historical observations? The sampled days use current published fixed rates, not historical observations of what drivers paid.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-published-annual-rate-source-1-1.json](fixtures/dev3-published-annual-rate-source-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 13 - SR 828 (Wiehle Ave) to Exit 18/19 - I-495 / SR 123 (Capital Beltway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 135 planned office days per year, gross annual salary $114250.00. Are the sampled prices historical observations?

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $72497.15. For 135 planned office days, gross annual income is $114250.00, with $76166.67 after the one-third assumed tax ($38083.33). The straight-line tolled distance is 22.16 miles per office day and 2992.01 miles annually; vehicle cost is $15.18 per office day and $2049.52 annually. P25 daily scenario: toll $12.00 per office day, $1620.00 annualized; combined toll and vehicle cost $27.18 per office day, $305.79 per average month, $3669.52 annually. Remaining annual income $72497.15; additional gross salary needed to offset this combined annual cost $5504.28; combined cost is 4.8% of assumed after-tax income. P50 daily scenario: toll $12.00 per office day, $1620.00 annualized; combined toll and vehicle cost $27.18 per office day, $305.79 per average month, $3669.52 annually. Remaining annual income $72497.15; additional gross salary needed to offset this combined annual cost $5504.28; combined cost is 4.8% of assumed after-tax income. P90 daily scenario: toll $12.00 per office day, $1620.00 annualized; combined toll and vehicle cost $27.18 per office day, $305.79 per average month, $3669.52 annually. Remaining annual income $72497.15; additional gross salary needed to offset this combined annual cost $5504.28; combined cost is 4.8% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. The sampled days use current published fixed rates, not historical observations of what drivers paid.

</details>

### 90. Gross salary offset meaning

`dev3-gross-salary-offset-meaning` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 136 planned office days per year, gross annual salary $116000.00. Explain the additional gross salary figure for my recruiter.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Explain the additional gross salary figure for my recruiter. Additional gross salary is the tool-provided gross income needed to offset both annual toll and vehicle costs under the tax assumption; it is not toll reimbursement alone.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-gross-salary-offset-meaning-1-1.json](fixtures/dev3-gross-salary-offset-meaning-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 136 planned office days per year, gross annual salary $116000.00. Explain the additional gross salary figure for my recruiter.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $73092.62. For 136 planned office days, gross annual income is $116000.00, with $77333.33 after the one-third assumed tax ($38666.67). The straight-line tolled distance is 22.16 miles per office day and 3014.17 miles annually; vehicle cost is $15.18 per office day and $2064.71 annually. P25 daily scenario: toll $16.00 per office day, $2176.00 annualized; combined toll and vehicle cost $31.18 per office day, $353.39 per average month, $4240.71 annually. Remaining annual income $73092.62; additional gross salary needed to offset this combined annual cost $6361.07; combined cost is 5.5% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2176.00 annualized; combined toll and vehicle cost $31.18 per office day, $353.39 per average month, $4240.71 annually. Remaining annual income $73092.62; additional gross salary needed to offset this combined annual cost $6361.07; combined cost is 5.5% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2176.00 annualized; combined toll and vehicle cost $31.18 per office day, $353.39 per average month, $4240.71 annually. Remaining annual income $73092.62; additional gross salary needed to offset this combined annual cost $6361.07; combined cost is 5.5% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. Additional gross salary is the tool-provided gross income needed to offset both annual toll and vehicle costs under the tax assumption; it is not toll reimbursement alone.

</details>

### 91. Combined cost percentage meaning

`dev3-combined-cost-percentage-meaning` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 137 planned office days per year, gross annual salary $117750.00. Does the income percentage represent tolls alone?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Does the income percentage represent tolls alone? The percentage represents combined toll and vehicle cost relative to assumed after-tax income, not tolls alone or a share of gross salary.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-combined-cost-percentage-meaning-1-1.json](fixtures/dev3-combined-cost-percentage-meaning-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 137 planned office days per year, gross annual salary $117750.00. Does the income percentage represent tolls alone?

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $74228.11. For 137 planned office days, gross annual income is $117750.00, with $78500.00 after the one-third assumed tax ($39250.00). The straight-line tolled distance is 22.16 miles per office day and 3036.33 miles annually; vehicle cost is $15.18 per office day and $2079.89 annually. P25 daily scenario: toll $16.00 per office day, $2192.00 annualized; combined toll and vehicle cost $31.18 per office day, $355.99 per average month, $4271.89 annually. Remaining annual income $74228.11; additional gross salary needed to offset this combined annual cost $6407.84; combined cost is 5.4% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2192.00 annualized; combined toll and vehicle cost $31.18 per office day, $355.99 per average month, $4271.89 annually. Remaining annual income $74228.11; additional gross salary needed to offset this combined annual cost $6407.84; combined cost is 5.4% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2192.00 annualized; combined toll and vehicle cost $31.18 per office day, $355.99 per average month, $4271.89 annually. Remaining annual income $74228.11; additional gross salary needed to offset this combined annual cost $6407.84; combined cost is 5.4% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. The percentage represents combined toll and vehicle cost relative to assumed after-tax income, not tolls alone or a share of gross salary.

</details>

**Negative control: `combined-percentage-as-tolls` — fail / fail / fail.** The percentage field is combined toll and vehicle cost divided by after-tax income.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 92. Monthly versus daily budget

`dev3-monthly-versus-daily-budget` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 7 - SR 607 (Loudoun County Pkwy) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 138 planned office days per year, gross annual salary $119500.00. Is the monthly figure an average or an exact monthly bill?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Is the monthly figure an average or an exact monthly bill? The monthly figure is the annualized combined commute cost averaged over twelve months; it is not a prediction of each monthly bill.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-monthly-versus-daily-budget-1-1.json](fixtures/dev3-monthly-versus-daily-budget-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 7 - SR 607 (Loudoun County Pkwy) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 138 planned office days per year, gross annual salary $119500.00. Is the monthly figure an average or an exact monthly bill?

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $75970.80. For 138 planned office days, gross annual income is $119500.00, with $79666.67 after the one-third assumed tax ($39833.33). The straight-line tolled distance is 22.16 miles per office day and 3058.49 miles annually; vehicle cost is $15.18 per office day and $2095.07 annually. P25 daily scenario: toll $11.60 per office day, $1600.80 annualized; combined toll and vehicle cost $26.78 per office day, $307.99 per average month, $3695.87 annually. Remaining annual income $75970.80; additional gross salary needed to offset this combined annual cost $5543.81; combined cost is 4.6% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1600.80 annualized; combined toll and vehicle cost $26.78 per office day, $307.99 per average month, $3695.87 annually. Remaining annual income $75970.80; additional gross salary needed to offset this combined annual cost $5543.81; combined cost is 4.6% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1600.80 annualized; combined toll and vehicle cost $26.78 per office day, $307.99 per average month, $3695.87 annually. Remaining annual income $75970.80; additional gross salary needed to offset this combined annual cost $5543.81; combined cost is 4.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. The monthly figure is the annualized combined commute cost averaged over twelve months; it is not a prediction of each monthly bill.

</details>

### 93. Daily scenarios are not forecasts

`dev3-daily-scenarios-are-not-forecasts` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Route 7 - Leesburg Pike to Fairfax Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 139 planned office days per year, gross annual salary $121250.00. Does the high scenario mean a 90 percent chance of that annual bill?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Does the high scenario mean a 90 percent chance of that annual bill? No. P90 is a higher daily scenario scaled by planned annual days, not a probability about the annual total or a forecast.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-daily-scenarios-are-not-forecasts-1-1.json](fixtures/dev3-daily-scenarios-are-not-forecasts-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Route 7 - Leesburg Pike to Fairfax Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 139 planned office days per year, gross annual salary $121250.00. Does the high scenario mean a 90 percent chance of that annual bill?

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $77006.43. For 139 planned office days, gross annual income is $121250.00, with $80833.33 after the one-third assumed tax ($40416.67). The straight-line tolled distance is 22.16 miles per office day and 3080.66 miles annually; vehicle cost is $15.18 per office day and $2110.25 annually. P25 daily scenario: toll $8.65 per office day, $1202.35 annualized; combined toll and vehicle cost $23.83 per office day, $276.05 per average month, $3312.60 annually. Remaining annual income $77520.73; additional gross salary needed to offset this combined annual cost $4968.90; combined cost is 4.1% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1716.65 annualized; combined toll and vehicle cost $27.53 per office day, $318.91 per average month, $3826.90 annually. Remaining annual income $77006.43; additional gross salary needed to offset this combined annual cost $5740.35; combined cost is 4.7% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2703.55 annualized; combined toll and vehicle cost $34.63 per office day, $401.15 per average month, $4813.80 annually. Remaining annual income $76019.53; additional gross salary needed to offset this combined annual cost $7220.70; combined cost is 6.0% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. No. P90 is a higher daily scenario scaled by planned annual days, not a probability about the annual total or a forecast.

</details>

**Negative control: `daily-p90-as-annual-probability` — fail / fail / fail.** The annualized daily quantile is not a percentile or probability of annual outcomes.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 94. Tolled distance scope

`dev3-tolled-distance-scope` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 6 - SR 772 (Ryan Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 140 planned office days per year, gross annual salary $123000.00. Does this include my local roads and all my actual car costs?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Does this include my local roads and all my actual car costs? No. Untolled travel is excluded and vehicle cost is a fixed modeling assumption, not your individualized fuel, maintenance, or other expenses.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-tolled-distance-scope-1-1.json](fixtures/dev3-tolled-distance-scope-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 6 - SR 772 (Ryan Rd) to Route 28 (Dulles Toll Road / Dulles Greenway) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 140 planned office days per year, gross annual salary $123000.00. Does this include my local roads and all my actual car costs?

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $78250.57. For 140 planned office days, gross annual income is $123000.00, with $82000.00 after the one-third assumed tax ($41000.00). The straight-line tolled distance is 22.16 miles per office day and 3102.82 miles annually; vehicle cost is $15.18 per office day and $2125.43 annually. P25 daily scenario: toll $11.60 per office day, $1624.00 annualized; combined toll and vehicle cost $26.78 per office day, $312.45 per average month, $3749.43 annually. Remaining annual income $78250.57; additional gross salary needed to offset this combined annual cost $5624.15; combined cost is 4.6% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1624.00 annualized; combined toll and vehicle cost $26.78 per office day, $312.45 per average month, $3749.43 annually. Remaining annual income $78250.57; additional gross salary needed to offset this combined annual cost $5624.15; combined cost is 4.6% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1624.00 annualized; combined toll and vehicle cost $26.78 per office day, $312.45 per average month, $3749.43 annually. Remaining annual income $78250.57; additional gross salary needed to offset this combined annual cost $5624.15; combined cost is 4.6% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. No. Untolled travel is excluded and vehicle cost is a fixed modeling assumption, not your individualized fuel, maintenance, or other expenses.

</details>

### 95. Assumed tax meaning

`dev3-assumed-tax-meaning` · annual_interpretation · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Exit 5 - SR 901 (Claiborne Pkwy) to Exit 8 - SR 606 (Ox Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 141 planned office days per year, gross annual salary $124750.00. Is the tax amount what I will actually owe?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

Minimum delivered user turns: 1; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Is the tax amount what I will actually owe? No. The one-third tax assumption is a rough comparison aid; it does not calculate your actual tax liability.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-assumed-tax-meaning-1-1.json](fixtures/dev3-assumed-tax-meaning-1-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Exit 5 - SR 901 (Claiborne Pkwy) to Exit 8 - SR 606 (Ox Rd) and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 141 planned office days per year, gross annual salary $124750.00. Is the tax amount what I will actually owe?

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $79587.86. For 141 planned office days, gross annual income is $124750.00, with $83166.67 after the one-third assumed tax ($41583.33). The straight-line tolled distance is 22.16 miles per office day and 3124.98 miles annually; vehicle cost is $15.18 per office day and $2140.61 annually. P25 daily scenario: toll $10.20 per office day, $1438.20 annualized; combined toll and vehicle cost $25.38 per office day, $298.23 per average month, $3578.81 annually. Remaining annual income $79587.86; additional gross salary needed to offset this combined annual cost $5368.22; combined cost is 4.3% of assumed after-tax income. P50 daily scenario: toll $10.20 per office day, $1438.20 annualized; combined toll and vehicle cost $25.38 per office day, $298.23 per average month, $3578.81 annually. Remaining annual income $79587.86; additional gross salary needed to offset this combined annual cost $5368.22; combined cost is 4.3% of assumed after-tax income. P90 daily scenario: toll $10.20 per office day, $1438.20 annualized; combined toll and vehicle cost $25.38 per office day, $298.23 per average month, $3578.81 annually. Remaining annual income $79587.86; additional gross salary needed to offset this combined annual cost $5368.22; combined cost is 4.3% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses. No. The one-third tax assumption is a rough comparison aid; it does not calculate your actual tax liability.

</details>

**Negative control: `tax-assumption-as-liability` — fail / fail / fail.** The fixed tax assumption is not an actual individualized tax calculation.

Expected deterministic failures: none; this requires semantic judgment. Full altered transcript and actual tool evidence are retained in [examples.json](examples.json).

### 96. Current quote then annual offer

`dev3-current-quote-then-annual-offer` · mixed · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> What is the current Dulles Toll Road toll from Reston Parkway to Spring Hill Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Now estimate annual affordability for that round trip: Tuesday to Thursday, 7:45 AM and 5:15 PM, 142 days, gross annual salary $127,000.

After receiving the current quote, ask for the annual round trip and supply the schedule and income in the specified follow-up.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Answer current pricing first. Only after the explicit annual request, switch to the independent annual tool; never multiply the current quote into an annual estimate.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-current-quote-then-annual-offer-1-1.json](fixtures/dev3-current-quote-then-annual-offer-1-1.json).
- Turn 2 or later: [dev3-current-quote-then-annual-offer-2-1.json](fixtures/dev3-current-quote-then-annual-offer-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** What is the current Dulles Toll Road toll from Reston Parkway to Spring Hill Road?

**Assistant 1:** The current toll estimate from Exit 12 - SR 602 (Reston Pkwy) to Exit 17 - SR 684 (Spring Hill Rd) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

**User 2:** Now estimate annual affordability for that round trip: Tuesday to Thursday, 7:45 AM and 5:15 PM, 142 days, gross annual salary $127,000.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $80504.03. For 142 planned office days, gross annual income is $127000.00, with $84666.67 after the one-third assumed tax ($42333.33). The straight-line tolled distance is 19.44 miles per office day and 2760.05 miles annually; vehicle cost is $13.31 per office day and $1890.64 annually. P25 daily scenario: toll $16.00 per office day, $2272.00 annualized; combined toll and vehicle cost $29.31 per office day, $346.89 per average month, $4162.64 annually. Remaining annual income $80504.03; additional gross salary needed to offset this combined annual cost $6243.96; combined cost is 4.9% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2272.00 annualized; combined toll and vehicle cost $29.31 per office day, $346.89 per average month, $4162.64 annually. Remaining annual income $80504.03; additional gross salary needed to offset this combined annual cost $6243.96; combined cost is 4.9% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2272.00 annualized; combined toll and vehicle cost $29.31 per office day, $346.89 per average month, $4162.64 annually. Remaining annual income $80504.03; additional gross salary needed to offset this combined annual cost $6243.96; combined cost is 4.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 97. Annual offer then current departure

`dev3-annual-offer-then-current-departure` · mixed · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Gallows Road to Jones Branch Drive/Route 123 and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 143 planned office days per year, gross annual salary $138500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

After the annual estimate, ask for the separate current outbound price.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Use annual evidence for the annual answer, then current evidence for the new current request; do not confuse daily P50 with the current toll.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-annual-offer-then-current-departure-1-1.json](fixtures/dev3-annual-offer-then-current-departure-1-1.json).
- Turn 2 or later: [dev3-annual-offer-then-current-departure-2-1.json](fixtures/dev3-annual-offer-then-current-departure-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Gallows Road to Jones Branch Drive/Route 123 and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 143 planned office days per year, gross annual salary $138500.00.

**Assistant 1:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $88663.33. For 143 planned office days, gross annual income is $138500.00, with $92333.33 after the one-third assumed tax ($46166.67). The straight-line tolled distance is 19.44 miles per office day and 2779.49 miles annually; vehicle cost is $13.31 per office day and $1903.95 annually. P25 daily scenario: toll $8.65 per office day, $1236.95 annualized; combined toll and vehicle cost $21.96 per office day, $261.74 per average month, $3140.90 annually. Remaining annual income $89192.43; additional gross salary needed to offset this combined annual cost $4711.35; combined cost is 3.4% of assumed after-tax income. P50 daily scenario: toll $12.35 per office day, $1766.05 annualized; combined toll and vehicle cost $25.66 per office day, $305.83 per average month, $3670.00 annually. Remaining annual income $88663.33; additional gross salary needed to offset this combined annual cost $5505.00; combined cost is 4.0% of assumed after-tax income. P90 daily scenario: toll $19.45 per office day, $2781.35 annualized; combined toll and vehicle cost $32.76 per office day, $390.44 per average month, $4685.30 annually. Remaining annual income $87648.03; additional gross salary needed to offset this combined annual cost $7027.95; combined cost is 5.1% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The scenarios use the returned historical observed toll samples. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

**User 2:** Now I am leaving Gallows Road for Jones Branch Drive. Check the current I-495 Express toll separately.

**Assistant 2:** The current toll estimate from Gallows Road to Jones Branch Drive/Route 123 is $8.95. i95/i495: $8.95; observed price. Observed 8:09 AM EDT.

</details>

### 98. Change intent during clarification

`dev3-change-intent-during-clarification` · mixed · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current toll from Belmont Ridge Road on the Greenway?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. Actually, I need an annual budget to Route 28 and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 141 office days, $108,500 gross yearly pay.

When asked for the current destination, switch to the fully specified annual request.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 1.

**Case-specific expectation**

Abandon the incomplete current request when the annual intent arrives; make only the annual call.

**Ordered fixture evidence**

- Turn 2 or later: [dev3-change-intent-during-clarification-2-1.json](fixtures/dev3-change-intent-during-clarification-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current toll from Belmont Ridge Road on the Greenway?

**Assistant 1:** Which destination are you going to?

**User 2:** Actually, I need an annual budget to Route 28 and back, Tuesday to Thursday, 7:45 AM and 5:15 PM, 141 office days, $108,500 gross yearly pay.

**Assistant 2:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $68820.41. For 141 planned office days, gross annual income is $108500.00, with $72333.33 after the one-third assumed tax ($36166.67). The straight-line tolled distance is 19.44 miles per office day and 2740.62 miles annually; vehicle cost is $13.31 per office day and $1877.32 annually. P25 daily scenario: toll $11.60 per office day, $1635.60 annualized; combined toll and vehicle cost $24.91 per office day, $292.74 per average month, $3512.92 annually. Remaining annual income $68820.41; additional gross salary needed to offset this combined annual cost $5269.38; combined cost is 4.9% of assumed after-tax income. P50 daily scenario: toll $11.60 per office day, $1635.60 annualized; combined toll and vehicle cost $24.91 per office day, $292.74 per average month, $3512.92 annually. Remaining annual income $68820.41; additional gross salary needed to offset this combined annual cost $5269.38; combined cost is 4.9% of assumed after-tax income. P90 daily scenario: toll $11.60 per office day, $1635.60 annualized; combined toll and vehicle cost $24.91 per office day, $292.74 per average month, $3512.92 annually. Remaining annual income $68820.41; additional gross salary needed to offset this combined annual cost $5269.38; combined cost is 4.9% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

### 99. Missing history then explicit current check

`dev3-missing-history-then-explicit-current-check` · mixed · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Estimate annual affordability: Braddock Road to Westpark Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 140 planned office days per year, gross annual salary $136500.00.

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. 

After the no-history explanation, explicitly ask for the current outbound toll as a separate task.

Minimum delivered user turns: 2; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Do not offer current tolls as a substitute annual estimate. The later explicitly requested current quote is permitted and remains separate.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-missing-history-then-explicit-current-check-1-1.json](fixtures/dev3-missing-history-then-explicit-current-check-1-1.json).
- Turn 2 or later: [dev3-missing-history-then-explicit-current-check-2-1.json](fixtures/dev3-missing-history-then-explicit-current-check-2-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Estimate annual affordability: Braddock Road to Westpark Drive and back, tuesday, wednesday, thursday, leaving at 7:45 AM and returning at 5:15 PM, 140 planned office days per year, gross annual salary $136500.00.

**Assistant 1:** For 140 planned office days, gross annual income is $136500.00, with $91000.00 after the one-third assumed tax ($45500.00). The straight-line tolled distance is 19.44 miles per office day and 2721.18 miles annually; vehicle cost is $13.31 per office day and $1864.01 annually. There are no complete paired days: historical tolls and combined totals are unavailable, not zero. An affordability or remaining-income total cannot be provided. Coverage is 0 of 36 eligible paired dates (0.0%). Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

**User 2:** Understood. Separately, check the current toll from Braddock Road to Westpark on I-495 Express.

**Assistant 2:** The current toll estimate from Braddock Road to Westpark Drive is $9.85. i95/i495: $9.85; observed price. Observed 8:09 AM EDT.

</details>

### 100. Annual switch still needs salary

`dev3-annual-switch-still-needs-salary` · mixed · objective: answer · frozen: 2026-09-24T08:18:00-04:00

**Opening request**

> Current toll from Hunter Mill Road to Spring Hill Road on the Dulles Toll Road?

**Driver brief**

You drive a two-axle passenger car using E-ZPass in toll mode. All facts in your opening request are intentional unless a correction below changes them. After the current quote you want the annual trip in this follow-up: Could you also estimate annual affordability for that round trip, Tuesday to Thursday, 7:45 AM and 5:15 PM, 139 office days? Your gross annual salary is $101,000; supply it only if asked.

Request the annual estimate after the current quote; then supply your income when asked.

Minimum delivered user turns: 3; maximum: 5; permitted calls: 2.

**Case-specific expectation**

Switch intent only after the delivered annual request; collect its missing income before the annual tool call.

**Ordered fixture evidence**

- Turn 1 or later: [dev3-annual-switch-still-needs-salary-1-1.json](fixtures/dev3-annual-switch-still-needs-salary-1-1.json).
- Turn 3 or later: [dev3-annual-switch-still-needs-salary-3-1.json](fixtures/dev3-annual-switch-still-needs-salary-3-1.json).

<details>
<summary>Proposed passing transcript (all three verdicts true)</summary>

**User 1:** Current toll from Hunter Mill Road to Spring Hill Road on the Dulles Toll Road?

**Assistant 1:** The current toll estimate from Exit 14 - SR 674 (Hunter Mill Rd) to Exit 17 - SR 684 (Spring Hill Rd) is $8.00. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $4.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT. dtr: $2.00; published fixed schedule. Evaluated 9/24/2026 8:18 AM EDT.

**User 2:** Could you also estimate annual affordability for that round trip, Tuesday to Thursday, 7:45 AM and 5:15 PM, 139 office days?

**Assistant 2:** What gross annual US-dollar income should I use for the annual estimate?

**User 3:** Use $101,000 gross annually.

**Assistant 3:** The annual income remaining after assumed tax and the annualized daily-P50 tolled commute is $63258.64. For 139 planned office days, gross annual income is $101000.00, with $67333.33 after the one-third assumed tax ($33666.67). The straight-line tolled distance is 19.44 miles per office day and 2701.74 miles annually; vehicle cost is $13.31 per office day and $1850.69 annually. P25 daily scenario: toll $16.00 per office day, $2224.00 annualized; combined toll and vehicle cost $29.31 per office day, $339.56 per average month, $4074.69 annually. Remaining annual income $63258.64; additional gross salary needed to offset this combined annual cost $6112.04; combined cost is 6.1% of assumed after-tax income. P50 daily scenario: toll $16.00 per office day, $2224.00 annualized; combined toll and vehicle cost $29.31 per office day, $339.56 per average month, $4074.69 annually. Remaining annual income $63258.64; additional gross salary needed to offset this combined annual cost $6112.04; combined cost is 6.1% of assumed after-tax income. P90 daily scenario: toll $16.00 per office day, $2224.00 annualized; combined toll and vehicle cost $29.31 per office day, $339.56 per average month, $4074.69 annually. Remaining annual income $63258.64; additional gross salary needed to offset this combined annual cost $6112.04; combined cost is 6.1% of assumed after-tax income. P25 is the lower, P50 middle, and P90 higher daily scenario. Annual values scale daily scenarios by planned days, not percentiles of annual outcomes, forecasts, or guarantees. Coverage is 36 of 36 eligible paired dates (100.0%). The sampled dates use current published fixed rates, not historically observed tolls. Only straight-line distances of priced tolled facility legs are included; untolled travel is excluded. One-third tax is an assumption, not your actual tax calculation. Vehicle cost uses a fixed $0.685 per straight-line tolled mile assumption, not your personal expenses.

</details>

# Golden case review, version 1.0.7

**Cases and labels approved; version 1.0.7 judge calibration awaits review.** Approval includes the corrected fixed charges in case 20, required baseline in case 24, and Markdown currency-list example. The 38 example conversations were authored without live model or pricing calls. All tool fixtures are synthetic. Paid calibration of those examples is recorded separately under `eval/evidence/golden-360/`.

Corpus SHA-256: `f5826201361001fdea03a80f3097b0ca8e9bd50b0480ec483918d20cf3ab8ffc`

The questions and actor briefs use the humanizer skill. Review their meaning as well as their wording. In particular, check that the actor only knows ordinary user facts and that a rubric accepts a useful equivalent answer.

## Coverage and proposed criticality

Criticality is metadata for later discussion, not a release gate. Critical cases concern wrong prices, routes, evidence limits, or unapproved actions. Other cases focus on gathering inputs and bounded failure handling. Every case must meet its own rubric to pass.

| # | Case | Critical | Held out |
| --- | --- | --- | --- |
| 1 | [Greenway current toll](#1-greenway-current) | Yes | No |
| 2 | [Correct the Greenway origin](#2-greenway-origin-correction) | Yes | No |
| 3 | [Unsupported vehicle profile](#3-unsupported-profile) | Yes | No |
| 4 | [Missing Greenway exit](#4-greenway-missing-destination) | No | No |
| 5 | [No evidence of a price increase](#5-i66-no-comparison) | Yes | No |
| 6 | [Missing price during toll hours](#6-i66-missing-price) | Yes | No |
| 7 | [Observed I-66 toll](#7-i66-observed-price) | Yes | No |
| 8 | [I-66 outside toll hours](#8-i66-free-period) | Yes | No |
| 9 | [Stale I-66 evidence](#9-i66-stale-price) | Yes | Yes |
| 10 | [Current-price tool failure](#10-current-tool-error) | No | No |
| 11 | [Unsupported origin](#11-unsupported-origin) | Yes | No |
| 12 | [Fixed-rate annual commute](#12-annual-fixed) | Yes | No |
| 13 | [Clarify the Tysons exit](#13-annual-tysons-clarification) | Yes | No |
| 14 | [Collect the missing schedule](#14-annual-missing-schedule) | No | No |
| 15 | [Clarify a salary range](#15-annual-salary-range) | No | No |
| 16 | [Clarify hourly income](#16-annual-hourly-income) | No | Yes |
| 17 | [Adjust annual commute days](#17-annual-confirm-days) | No | No |
| 18 | [Correct invalid time and days](#18-annual-invalid-schedule) | No | Yes |
| 19 | [Unsupported annual return route](#19-annual-no-return-route) | Yes | No |
| 20 | [Corridor choice and partial history](#20-annual-partial-history) | Yes | No |
| 21 | [Independent morning and evening ramps](#21-annual-independent-ramps) | Yes | No |
| 22 | [Retain a selected annual alternative](#22-annual-select-alternative) | Yes | No |
| 23 | [Confirm different commute areas](#23-annual-confirm-divergent) | Yes | Yes |
| 24 | [No complete paired history](#24-annual-no-paired-days) | Yes | No |

Cases 9, 16, 18, and 23 are reserved before tuning. All were seen during authorship; case 23 also has earlier regression exposure. Their examples must not be used to tune the agent or calibrate the judge. Record exposure and reclassify a used case before later comparisons.

## Case details

### 1. greenway-current

**Greenway current toll**

> How much is the Greenway from Leesburg Bypass to Route 28 right now? I have E-ZPass.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28. This request is for that one-way trip only; do not ask for a return trip.

Actor goal: Get the current one-way toll.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Report the published fixed Greenway rate, not a live observed or historical estimate. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: tests/test_get_current_toll_price.py:test_greenway_only_route_streams_progress_and_returns_total. User dialogue is authored, not a production transcript.

Fixture: [greenway.json](fixtures/greenway.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "greenway:1:entry:EB",
  "destination_point_id": "greenway:28:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Total $5.80; source: schedule_derived.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 2. greenway-origin-correction

**Correct the Greenway origin**

> What would I pay from Leesburg Bypass to Route 28 on the Greenway?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. You initially said Leesburg Bypass, but you will actually enter at Battlefield Parkway. Keep Route 28 as the exit.

Actor goal: Ask for the first price, then correct the origin to Battlefield Parkway and get the revised result.

Follow-up rules: After the first answer, say you meant Battlefield Parkway. Make the correction before stopping.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 2 tool calls.

Expected behavior: Address both origins in order, with no claim that equal prices mean the route stayed unchanged. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [greenway.json](fixtures/greenway.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "greenway:1:entry:EB",
  "destination_point_id": "greenway:28:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Total $5.80; source: schedule_derived.

Fixture: [greenway-corrected.json](fixtures/greenway-corrected.json), earliest assistant turn 2.

```json
{
  "origin_point_id": "greenway:2A:entry:EB",
  "destination_point_id": "greenway:28:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Total $5.80; source: schedule_derived.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 3. unsupported-profile

**Unsupported vehicle profile**

> What is the Greenway toll from Leesburg Bypass to Route 28 for my three-axle truck with E-ZPass?

Actor facts: You have a three-axle truck, E-ZPass in toll mode, and the route in your question. Do not agree to switch to a passenger car.

Actor goal: Find out whether this vehicle can be priced.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Either decline the unsupported three-axle profile directly, or pass that profile to the tool and explain its unsupported result. Never quote the passenger-car rate. A direct refusal need not repeat the route or every profile field. If calling a tool, use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [unsupported-profile.json](fixtures/unsupported-profile.json), earliest assistant turn 1 (optional; direct refusal is valid).

```json
{
  "origin_point_id": "greenway:1:entry:EB",
  "destination_point_id": "greenway:28:exit:EB",
  "pricing_profile": {
    "vehicle_class": "three_axle",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: unsupported_pricing_profile

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 4. greenway-missing-destination

**Missing Greenway exit**

> What is the toll if I get on the Greenway at Leesburg Bypass?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your exit is Route 28, but you have not told the assistant that yet.

Actor goal: Get the toll after answering any question about your exit.

Follow-up rules: If asked where you leave the Greenway, say Route 28. Do not volunteer it before the assistant asks.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Ask for the missing destination without a premature tool call. Then price Route 28. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [greenway.json](fixtures/greenway.json), earliest assistant turn 2.

```json
{
  "origin_point_id": "greenway:1:entry:EB",
  "destination_point_id": "greenway:28:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Total $5.80; source: schedule_derived.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 5. i66-no-comparison

**No evidence of a price increase**

> What is the toll on I-66 eastbound from I-66 West to Route 7 right now? Has it gone up?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Keep the I-66 route in your question.

Actor goal: Get the price and find out whether there is evidence that it increased.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Report the observed price and timestamp. State that comparison evidence is missing; do not invent an increase, decrease, or trend. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [i66-observed.json](fixtures/i66-observed.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:4:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Total $4.25; source: observed.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 6. i66-missing-price

**Missing price during toll hours**

> What is the toll on I-66 eastbound from I-66 West to Route 7 right now?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode.

Actor goal: Find out whether a usable current price is available.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Explain missing price evidence during the frozen tolled period. Do not infer that the road is closed or free. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [i66-missing_observation.json](fixtures/i66-missing_observation.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:4:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: incomplete_route_price

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 7. i66-observed-price

**Observed I-66 toll**

> What is the toll on I-66 eastbound from I-66 West to Route 7 right now?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode.

Actor goal: Get the current toll for this route.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Report the observed price and timestamp for the correct eastbound route. Do not invent comparison history. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: test-cases.jsonl:i66-west-to-route-7-current-price. User dialogue is authored, not a production transcript.

Fixture: [i66-observed.json](fixtures/i66-observed.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:4:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Total $4.25; source: observed.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 8. i66-free-period

**I-66 outside toll hours**

> What is the toll on I-66 eastbound from I-66 West to Route 7 right now?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode.

Actor goal: Get the current toll for this route.

Frozen time: `2026-08-27T12:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Report zero because the frozen noon schedule is free, not because an observation is missing. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: test-cases.jsonl:i66-west-to-route-7-current-price; explicit off-peak fixture variant. User dialogue is authored, not a production transcript.

Fixture: [i66-free.json](fixtures/i66-free.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:4:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Total $0.00; source: schedule_derived.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 9. i66-stale-price

**Stale I-66 evidence**

> What is the toll on I-66 eastbound from I-66 West to Route 7 right now?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode.

Actor goal: Find out whether the current price is known.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Explain that the observation is too old for a current quote. Do not claim a current price, closure, or free travel. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [i66-stale_observation.json](fixtures/i66-stale_observation.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:4:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: incomplete_route_price

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 10. current-tool-error

**Current-price tool failure**

> What is the Greenway toll from Leesburg Bypass to Route 28?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28. This request is for that one-way trip only; do not ask for a return trip.

Actor goal: Get a price if the service can provide one.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Explain that pricing failed and no price was obtained. Stop after the single failed call; no automatic retries, made-up quote, or unrelated tool calls. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [current-error.json](fixtures/current-error.json), earliest assistant turn 1.

```json
{
  "origin_point_id": "greenway:1:entry:EB",
  "destination_point_id": "greenway:28:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

Fixture outcome: Safe tool execution error.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 11. unsupported-origin

**Unsupported origin**

> What is the toll from downtown Baltimore to Route 28 on the Greenway?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. You mean downtown Baltimore, Maryland. Do not select a different starting point.

Actor goal: Find out whether this exact trip is supported.

Follow-up rules: If asked to choose another origin, say you mean Baltimore and end the conversation.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 0 tool calls.

Expected behavior: Explain that Baltimore is outside the supported origin catalog. Ask for a supported origin if useful, but never substitute Leesburg or call a pricing tool. Use the exact requested route and pricing profile. Ground the price, time, availability, and provenance in the supplied tool result. Missing evidence is not a zero toll. Do not substitute an annual estimate.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

No pricing calls are allowed.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 12. annual-fixed

**Fixed-rate annual commute**

> I earn $120,000 a year. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? I work Monday to Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year.

Actor goal: Understand annual tolls, commute costs, and what is left from your income.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Use the outbound route and its valid reverse. Explain that the Greenway component uses current fixed rates. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:leesburg-route-28-job-offer. User dialogue is authored, not a production transcript.

Fixture: [annual-fixed.json](fixtures/annual-fixed.json), earliest assistant turn 1.

```json
{
  "outbound": {
    "origin_point_id": "greenway:1:entry:EB",
    "destination_point_id": "greenway:28:exit:EB",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "greenway:28:entry:WB",
    "destination_point_id": "greenway:1:exit:WB",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2784.00, total commute $6072.00; P50 annual toll $2784.00, total commute $6072.00; P90 annual toll $2784.00, total commute $6072.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 13. annual-tysons-clarification

**Clarify the Tysons exit**

> I live near Springfield-Franconia and have a $120,000 offer in Tysons. What would the commute cost? Monday to Friday, 8 AM out, 5:30 PM back, 240 days a year.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year. Your Tysons exit is Westpark Drive.

Actor goal: Get an annual estimate after identifying the right Tysons exit.

Follow-up rules: When asked which Tysons exit, choose Westpark Drive.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Ask which Tysons exit before pricing. Honor Westpark Drive and disclose modeled historical evidence. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:springfield-franconia-tysons-job-offer. User dialogue is authored, not a production transcript.

Fixture: [annual-modeled.json](fixtures/annual-modeled.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "i95:206NO",
    "destination_point_id": "i495:185ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i495:185SO",
    "destination_point_id": "i95:206SD",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2880.00, total commute $6168.00; P50 annual toll $3840.00, total commute $7128.00; P90 annual toll $5760.00, total commute $9048.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 14. annual-missing-schedule

**Collect the missing schedule**

> I earn $120,000 and would take the Greenway from Leesburg Bypass to Route 28. What would that commute do to my income?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year.

Actor goal: Get an annual estimate after supplying your schedule.

Follow-up rules: When asked, supply Monday through Friday, 8 AM outbound, 5:30 PM return, and 240 days.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Ask for departure and return times, weekdays, and annual commute days together. Retain the supplied route and income. Only call after receiving the missing facts. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:leesburg-route-28-missing-schedule. User dialogue is authored, not a production transcript.

Fixture: [annual-fixed.json](fixtures/annual-fixed.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "greenway:1:entry:EB",
    "destination_point_id": "greenway:28:exit:EB",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "greenway:28:entry:WB",
    "destination_point_id": "greenway:1:exit:WB",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2784.00, total commute $6072.00; P50 annual toll $2784.00, total commute $6072.00; P90 annual toll $2784.00, total commute $6072.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 15. annual-salary-range

**Clarify a salary range**

> The offer is $110,000 to $130,000. What would a Greenway commute from Leesburg Bypass to Route 28 leave me with? Monday to Friday, 8 AM out and 5:30 PM back, 240 office days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your salary range is $110,000 to $130,000; when asked for one annual gross estimate, choose $120,000. Your schedule is Monday through Friday, 8 AM and 5:30 PM, 240 days.

Actor goal: Get the annual estimate using your chosen salary.

Follow-up rules: Supply $120,000 gross per year only when asked for one estimate.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Request one annual gross estimate before calling. Do not choose the midpoint without asking. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:leesburg-route-28-salary-range. User dialogue is authored, not a production transcript.

Fixture: [annual-fixed.json](fixtures/annual-fixed.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "greenway:1:entry:EB",
    "destination_point_id": "greenway:28:exit:EB",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "greenway:28:entry:WB",
    "destination_point_id": "greenway:1:exit:WB",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2784.00, total commute $6072.00; P50 annual toll $2784.00, total commute $6072.00; P90 annual toll $2784.00, total commute $6072.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 16. annual-hourly-income

**Clarify hourly income**

> I make $60 an hour. What would the Greenway commute from Leesburg Bypass to Route 28 cost me? Monday to Friday, 8 AM out, 5:30 PM home, 240 office days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your hourly pay is $60. Your expected gross annual income is $120,000, but you have not supplied it yet. Your commute is Monday through Friday at 8 AM and 5:30 PM, 240 days.

Actor goal: Get an estimate without having the assistant assume your paid working hours.

Follow-up rules: When asked about earnings or paid hours, say you expect $120,000 gross this year.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Ask about annual gross income or paid hours/weeks. Accept the user-supplied annual estimate; do not assume 2,080 paid hours or multiply by commute days. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [annual-fixed.json](fixtures/annual-fixed.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "greenway:1:entry:EB",
    "destination_point_id": "greenway:28:exit:EB",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "greenway:28:entry:WB",
    "destination_point_id": "greenway:1:exit:WB",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2784.00, total commute $6072.00; P50 annual toll $2784.00, total commute $6072.00; P90 annual toll $2784.00, total commute $6072.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 17. annual-confirm-days

**Adjust annual commute days**

> I make $120,000 and commute on the Greenway from Leesburg Bypass to Route 28, Monday to Friday. I leave at 8 AM and return at 5:30 PM. What does that cost over a year?

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year.

Actor goal: Get an annual estimate using 240 office days after allowing for time off.

Follow-up rules: When asked to confirm annual days, say to use 240 after time off.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Propose 52 times five, or 260 days, as an adjustable starting estimate and wait. Use the user-confirmed 240 days. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:leesburg-route-28-confirm-annual-days. User dialogue is authored, not a production transcript.

Fixture: [annual-fixed.json](fixtures/annual-fixed.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "greenway:1:entry:EB",
    "destination_point_id": "greenway:28:exit:EB",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "greenway:28:entry:WB",
    "destination_point_id": "greenway:1:exit:WB",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2784.00, total commute $6072.00; P50 annual toll $2784.00, total commute $6072.00; P90 annual toll $2784.00, total commute $6072.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 18. annual-invalid-schedule

**Correct invalid time and days**

> Estimate my Greenway commute from Leesburg Bypass to Route 28. Salary $120,000, Monday to Friday, leaving at 25:00 and returning at 5:30 PM, 400 office days a year.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your route is the Greenway from Leesburg Bypass to Route 28, returning the other way. You mistyped the outbound time and annual days. The correct values are 8 AM and 240 days. The other facts in your question are correct.

Actor goal: Correct the two mistakes and get an annual estimate.

Follow-up rules: When asked about the mistakes, say 8 AM outbound and 240 days per year.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Ask for valid outbound time and annual day count before calling. Do not silently clamp or repair either value. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: Issue #361 coverage gap; authored synthetic scenario. User dialogue is authored, not a production transcript.

Fixture: [annual-fixed.json](fixtures/annual-fixed.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "greenway:1:entry:EB",
    "destination_point_id": "greenway:28:exit:EB",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "greenway:28:entry:WB",
    "destination_point_id": "greenway:1:exit:WB",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2784.00, total commute $6072.00; P50 annual toll $2784.00, total commute $6072.00; P90 annual toll $2784.00, total commute $6072.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 19. annual-no-return-route

**Unsupported annual return route**

> Could you estimate a Dulles Airport to Reagan Airport commute on a $120,000 salary? Monday to Friday, 8 AM out, 5:30 PM back, 240 days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year. You want the round trip between Dulles Airport and Reagan Airport.

Actor goal: Learn whether this annual round trip can be estimated.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Explain that the return route is unsupported. Do not present annual scenarios, switch airports, or restart current pricing. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:dulles-to-reagan-annual-route-unavailable. User dialogue is authored, not a production transcript.

Fixture: [annual-no-route.json](fixtures/annual-no-route.json), earliest assistant turn 1.

```json
{
  "outbound": {
    "origin_point_id": "airport_iad",
    "destination_point_id": "airport_dca",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "airport_dca",
    "destination_point_id": "airport_iad",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: route_unavailable

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 20. annual-partial-history

**Corridor choice and partial history**

> What would a Leesburg to Washington commute cost on a $120,000 salary? Monday to Friday, 8 AM outbound, 5:30 PM return, 240 days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year. You mean Leesburg Bypass and Washington via I-395, not I-66.

Actor goal: Get the annual estimate for the I-395 corridor.

Follow-up rules: Choose I-395 when asked which corridor.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Clarify the Washington corridor before calling. Report the partial coverage and modeled/fixed sources, not a complete-history claim. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:leesburg-to-washington-i395-job-offer; new partial-success fixture. User dialogue is authored, not a production transcript.

Fixture: [annual-partial.json](fixtures/annual-partial.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "greenway:1:entry:EB",
    "destination_point_id": "i95:2249ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i95:2232SO",
    "destination_point_id": "greenway:1:exit:WB",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $8544.00, total commute $11832.00; P50 annual toll $9504.00, total commute $12792.00; P90 annual toll $11424.00, total commute $14712.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 21. annual-independent-ramps

**Independent morning and evening ramps**

> I go from I-95 Near Franconia-Springfield Pkwy NB to Pentagon/Eads in the morning, then Pentagon/Eads southbound to Backlick Road in the evening. What would that cost on $120,000 a year? Monday to Friday, 8 AM out, 5:30 PM back, 240 days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year. Your morning entry is I-95 Near Franconia-Springfield Pkwy NB; your evening exit is Backlick Road southbound.

Actor goal: Get an estimate for the two different commute legs.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Preserve the independent AM and PM ramps. Do not replace the evening Backlick exit with the reverse of the morning entry. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:annual-independent-ramps. User dialogue is authored, not a production transcript.

Fixture: [annual-independent.json](fixtures/annual-independent.json), earliest assistant turn 1.

```json
{
  "outbound": {
    "origin_point_id": "i95:212NO",
    "destination_point_id": "i95:223ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i95:2233SO",
    "destination_point_id": "i95:205SD",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2880.00, total commute $6168.00; P50 annual toll $3840.00, total commute $7128.00; P90 annual toll $5760.00, total commute $9048.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 22. annual-select-alternative

**Retain a selected annual alternative**

> I want to go from Backlick Road to Pentagon/Eads in the morning and Pentagon/Eads southbound to Backlick in the evening. Can you estimate it? Salary $120,000, Monday to Friday, 8 AM and 5:30 PM, 240 days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year. If Backlick is not a valid morning entry, choose the offered Franconia-Springfield Parkway northbound entry. Keep the evening Backlick exit.

Actor goal: Get an annual estimate after choosing a valid morning entry.

Follow-up rules: If offered alternatives, choose Franconia-Springfield Parkway northbound. Do not change the evening exit.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 2 tool calls.

Expected behavior: First make the required discovery call on the original Backlick route to obtain authoritative alternatives. Its invalid-origin result is expected: this original-route call is permitted before any alternative selection and is not a premature pricing violation. Present the actual offered alternatives, wait for the user to choose, then use Franconia-Springfield Parkway northbound. Calling that replacement route before the user chooses still fails. Retain the return leg, income, and schedule. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:annual-backlick-alternative-selection. User dialogue is authored, not a production transcript.

Fixture: [annual-alternatives.json](fixtures/annual-alternatives.json), earliest assistant turn 1.

```json
{
  "outbound": {
    "origin_point_id": "i95:205SD",
    "destination_point_id": "i95:223ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i95:2233SO",
    "destination_point_id": "i95:205SD",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: route_unavailable

Fixture: [annual-independent.json](fixtures/annual-independent.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "i95:212NO",
    "destination_point_id": "i95:223ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i95:2233SO",
    "destination_point_id": "i95:205SD",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2880.00, total commute $6168.00; P50 annual toll $3840.00, total commute $7128.00; P90 annual toll $5760.00, total commute $9048.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 23. annual-confirm-divergent

**Confirm different commute areas**

> My morning trip is Franconia-Springfield Parkway northbound to Pentagon/Eads. In the evening I go from Westpark Drive to Springfield-Franconia. Estimate both together: $120,000 salary, Monday to Friday, 8 AM and 5:30 PM, 240 days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year. The different work areas are intentional. Confirm combining these two legs if asked.

Actor goal: Get one estimate for the two intentional legs.

Follow-up rules: When asked, confirm that these are the two legs you want combined.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Notice the different areas and explicitly ask for confirmation before the annual call. Acknowledge the combined-leg scope. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: test-cases.jsonl:annual-divergent-areas-confirmation. User dialogue is authored, not a production transcript.

Fixture: [annual-divergent.json](fixtures/annual-divergent.json), earliest assistant turn 2.

```json
{
  "outbound": {
    "origin_point_id": "i95:212NO",
    "destination_point_id": "i95:223ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i495:185SO",
    "destination_point_id": "i95:206SD",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: P25 annual toll $2880.00, total commute $6168.00; P50 annual toll $3840.00, total commute $7128.00; P90 annual toll $5760.00, total commute $9048.00.

The corresponding proposed passing conversation is in [examples.json](examples.json).

### 24. annual-no-paired-days

**No complete paired history**

> Estimate Springfield-Franconia to Westpark Drive and back on a $120,000 salary. Monday to Friday, 8 AM out, 5:30 PM back, 240 days.

Actor facts: You drive a two-axle passenger car with E-ZPass set to toll mode. Your gross salary is $120,000 a year. You commute Monday through Friday, leave at 8 AM, head home at 5:30 PM, and expect 240 office days a year. Use Springfield-Franconia and Westpark Drive for the round trip.

Actor goal: Find out whether the annual toll estimate has enough history.

Frozen time: `2026-08-27T08:00:00-04:00`. Maximum: 4 assistant turns and 1 tool calls.

Expected behavior: Explain that no complete paired days are available. Do not produce annual toll scenarios or a full affordability conclusion. Show the returned gross and after-tax income, tolled-distance baseline, and daily and annual vehicle costs. Explain the one-third tax assumption, $0.685 per-mile vehicle rate, and tolled-portions-only scope. Preserve the zero-of-60 coverage disclosure and explain that historical tolls and combined totals are unavailable, not zero. Use the supplied income and schedule. Ground each monetary claim in its labeled tool field and scenario. For available financial estimates, explain the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, tolled-only distance/scope, and historical versus fixed or modeled sources where applicable. Label annual figures as annualized daily P25/P50/P90 estimates, not percentiles of annual outcomes. Do not substitute a current-price call.

Source: tests/test_get_annual_toll_ballpark.py:test_no_complete_response_keeps_compact_coverage; synthetic dynamic-route variant. User dialogue is authored, not a production transcript.

Fixture: [annual-no-pairs.json](fixtures/annual-no-pairs.json), earliest assistant turn 1.

```json
{
  "outbound": {
    "origin_point_id": "i95:206NO",
    "destination_point_id": "i495:185ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i495:185SO",
    "destination_point_id": "i95:206SD",
    "departure_time": "17:30:00"
  },
  "weekdays": [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday"
  ],
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Fixture outcome: no_complete_paired_days

The corresponding proposed passing conversation is in [examples.json](examples.json).

## Proposed bad examples

These are candidates for human labels and later judge calibration, not claims that the judge rejects them already.

| Case | Example | Mechanical failure | Why it should fail |
| --- | --- | --- | --- |
| greenway-current | wrong-route | missing_call, tool_arguments, unsupported_money | The user requested Route 28, but the call, result, and answer consistently price unrequested Route 7. Grounded wrong-route pricing still fails Outcome and Rules. |
| annual-tysons-clarification | premature-call | missing_call, premature_call, unsupported_money | The agent priced Westpark before the user selected a Tysons exit. |
| greenway-current | incorrect-money | unsupported_money | The fixture quotes 5.80, not 99.99. |
| unsupported-origin | unsupported-substitution | tool_budget, unexpected_call | A Greenway route was silently substituted for the Baltimore trip. |
| annual-missing-schedule | missing-clarification | missing_call, premature_call, unsupported_money | The missing schedule was invented before the user supplied it. |
| annual-select-alternative | unapproved-alternative | missing_call, premature_call, unsupported_money | The alternate morning entry was priced before the user selected it. |
| annual-no-paired-days | invented-annual-total | unsupported_money | There are no paired days or annual toll scenarios in this result. |
| i66-free-period | missing-means-free | None; semantic judge required | The amount is supported but the explanation falsely claims missing evidence. This needs semantic grading. |
| annual-fixed | swapped-financial-label | None; semantic judge required | 6072.00 is total annual commute cost, not annual toll. The number exists in evidence, so the correctness judge must reject the swapped label. |
| annual-tysons-clarification | silent-modeling | None; semantic judge required | The fixture explicitly marks modeled evidence. |
| annual-confirm-days | missing-day-proposal | None; semantic judge required | The agent never offers the required adjustable 52-week estimate. |
| annual-no-paired-days | missing-available-baseline | None; semantic judge required | The response omits the available income, distance, and vehicle-cost baseline required when toll history is missing. |

## Review record

- Cases/fixtures and labels: unchanged from the approved 1.0.1 set. New grader and harness evidence await review; see [review.json](review.json).
- Judge calibration: not run; belongs to #360.
- Baseline execution: not run; belongs to #360/#362.
- Coverage review: initial 24 cases, with current I-95 direction and guardrail scenarios deliberately excluded.
- Next review: before any corpus revision or when a new observed failure is considered.

Record approval of the revised grader and exact corpus digest in [review.json](review.json) after calibration review. Do not mark the corpus approved merely because offline checks pass.

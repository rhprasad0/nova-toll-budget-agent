# Point-in-Time Pricing and Insights MVP Contract

## Purpose

Define the smallest deterministic contract for pricing an immutable canonical
route **now**. The MVP does not reconstruct arbitrary past requests or forecast
future dynamic prices.

The result is an estimate, not an operator quote. A payable Express Lanes toll
is locked only when the driver passes the applicable final roadside sign. Do
not return a `quote_id`, `valid_until`, or other guarantee.

This contract is paired with the
[historical pricing contract](historical-pricing-mvp-contract.md), which uses
the same facility anchors to compare the prior three weeks.

## Pricing method

- Record `evaluated_at` from the database statement before selecting prices.
- Use `pricing.i66_pricing_comparisons` for I-66 and
  `pricing.i95_i495_pricing_comparisons` for I-95/I-395/I-495.
- Select each component's `comparison_kind = 'current'` row. Components from
  different facilities intentionally use independent anchors and may have a
  time gap between observations.
- I-66 uses 6-minute bins. I-95/I-495 uses 10-minute bins. Both are half-open
  and aligned to the top of the hour.
- Require `interval_end_at <= evaluated_at`, `observed_at <= evaluated_at`, and
  an observation age from zero through 30 minutes for current observed or
  modeled prices.
- Select a row before applying availability. Never expose an older open or
  fresh row when the selected row is closed, indeterminate, or stale.
- I-95/I-395 rows must satisfy both the canonical weekly direction schedule and
  the feed's direction sentinels for that interval. Holiday, major-event, and
  other exceptional schedules that contradict the canonical direction are
  excluded.
- I-495 does not use the reversible I-95/I-395 direction schedule.
- Modeled I-95 prices inherit their proxy observation time and preserve their
  model method and proxy identifier. Never relabel them as observed.
- Schedule-derived components use the published rate applicable at
  `evaluated_at`, preserving schedule identity and effective dates.
- Return a route total only when every required component has a usable price.
  Missing or unavailable prices are not zero.
- An empty component list and `total_usd: "0.00"` mean the route is known to
  contain no toll.

Map `pricing.trip_pricing_i95.calculated_at` and
`pricing.trip_pricing_i66.calculated_at` to `observed_at`. Do not substitute
I-95 `current_at`.

## Canonical I-95/I-395 schedule

Interpret times in `America/New_York`. The reversal rule wins the published
weekday 10–11 a.m. overlap.

| Day | Canonical direction windows |
| --- | --- |
| Monday | Northbound 12–10 a.m.; reversal 10 a.m.–12 p.m.; southbound 12 p.m.–12 a.m. |
| Tuesday–Friday | Southbound 12–1 a.m.; reversal 1–2:30 a.m.; northbound 2:30–10 a.m.; reversal 10 a.m.–12 p.m.; southbound 12 p.m.–12 a.m. |
| Saturday | Southbound 12 a.m.–2 p.m.; reversal 2–4 p.m.; northbound 4 p.m.–12 a.m. |
| Sunday | Northbound all day. |

Monday northbound continues from Sunday morning. A direction is usable only
when OD pair `1132` reports `NORTHBOUND_OPEN` with `1151` closed, or `1151`
reports `SOUTHBOUND_OPEN` with `1132` closed. Missing, conflicting, or
transitional sentinel states are unavailable.

## Pricing profile

The MVP supports exactly:

```json
{
  "vehicle_class": "two_axle_passenger",
  "payment_method": "e_zpass",
  "transponder_mode": "toll"
}
```

Reject unsupported profiles instead of silently substituting this one.

## Pricing response

Money values are decimal strings in US dollars. Times are ISO 8601 values with
an explicit Eastern offset.

```json
{
  "route_plan_id": "plan-123",
  "method": "latest_complete_current_facility_prices",
  "evaluated_at": "2026-08-13T08:32:05-04:00",
  "maximum_observation_age_minutes": 30,
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  },
  "source_kind": "mixed",
  "components": [
    {
      "route_step_id": "step-1",
      "price_usd": "2.00",
      "source_kind": "schedule_derived",
      "pricing_method": "published_schedule",
      "schedule_id": "dulles-toll-road-2026-rates",
      "effective_from": "2026-01-01T00:00:00-05:00",
      "effective_until": null,
      "priced_as_of": null,
      "observed_at": null
    },
    {
      "route_step_id": "step-2",
      "price_usd": "7.20",
      "source_kind": "observed",
      "pricing_method": "source_observation",
      "facility": "i66",
      "bin_minutes": 6,
      "bin_start": "2026-08-13T08:24:00-04:00",
      "bin_end": "2026-08-13T08:30:00-04:00",
      "priced_as_of": "2026-08-13T08:24:00-04:00",
      "observed_at": "2026-08-13T08:22:00-04:00"
    },
    {
      "route_step_id": "step-3",
      "price_usd": "4.40",
      "source_kind": "observed",
      "pricing_method": "source_observation",
      "facility": "i95_i495",
      "bin_minutes": 10,
      "bin_start": "2026-08-13T08:20:00-04:00",
      "bin_end": "2026-08-13T08:30:00-04:00",
      "priced_as_of": "2026-08-13T08:20:00-04:00",
      "observed_at": "2026-08-13T08:10:00-04:00"
    }
  ],
  "total_usd": "13.60",
  "recent_movement": {
    "method": "same_route_three_facility_cycles",
    "direction": "rising",
    "samples": [
      {"cycle_offset": -2, "total_usd": "7.10"},
      {"cycle_offset": -1, "total_usd": "10.20"},
      {"cycle_offset": 0, "total_usd": "13.60"}
    ],
    "net_change_usd": "6.50",
    "net_change_percent": "91.5"
  }
}
```

`source_kind` is `observed`, `schedule_derived`, `modeled`, `mixed`, or
`none`. Observed and modeled components require facility, bin, source interval,
and observation timestamps. Modeled components additionally require
`pricing_method` and `proxy_od_pair_id` and must be described as provisional
ballpark estimates.

## Recent movement

For every observed or modeled component, use its current facility bin and its
two `prior_cycle` rows. Build complete route totals for offsets `-2`, `-1`, and
`0` before comparing them. Mixed-facility samples intentionally combine
different bin ranges.

- `rising`: both consecutive changes are positive.
- `falling`: both consecutive changes are negative.
- `unchanged`: all three totals are equal.
- `mixed`: every other complete sequence.

Omit `recent_movement` unless all three route totals are complete. Calculate
the percentage against the earliest total using decimal half-up rounding; use
`null` when the earliest total is zero. Movement is descriptive, not a
forecast.

## Failure contract

Return no partial total. Use `pricing_unavailable` with one of:

- `invalid_request`
- `unsupported_pricing_profile`
- `missing_observation`
- `facility_unavailable`
- `stale_observation`
- `exceptional_i95_schedule`

Include the affected route steps, latest source timestamps when known, and
source status without inventing a price.

## Deferred beyond MVP

- Arbitrary historical point-in-time reconstruction.
- Forecasts or guaranteed quotes.
- Holiday/event override calendars.
- Occupancy, motorcycle, bus, trailer, pay-by-plate, cash, and 3+ axle rates.

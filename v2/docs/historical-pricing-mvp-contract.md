# Historical Pricing MVP Contract

## Purpose

Define the smallest useful response contract for TollChat's deterministic
rolling-average pricing analysis. The analysis receives a canonical route plan
and describes what that same trip recently cost without changing the route.

The MVP uses the previous four weeks because recent prices are more useful to a
traveler than a long-term average that hides current commuting patterns.

## Comparison method

- Match the requested route, local weekday, and 15-minute departure slot.
- Apply the same explicit pricing profile to every comparable route total.
- Treat the start of that slot as the comparison instant and anchor the 28-day
  window to that instant, not to the exact minute inside the requested slot.
  For each observed or
  modeled route component, select the latest source row within the slot
  (`slot_start <= interval_end_at < slot_end`) before applying its availability
  rule. Exclude the date if that selected row is missing, incomplete, closed, or
  otherwise unavailable. Never fall back to an older usable row in the slot.
- Use one comparable trip price from each eligible date in the half-open window
  from 28 local days before the slot start through, but not including, that slot
  start, for at most four comparable weekdays.
- Preserve the requested physical occurrence when a fall-back hour repeats.
  Ambiguous prior comparison slots use the later, standard-time occurrence;
  nonexistent spring-forward slots are ineligible and reduce the expected count.
- Calculate route totals for each date before calculating summary statistics.
  Do not independently average legs and then combine them.
- Exclude missing or incomplete route observations instead of treating them as
  zero.
- Report scheduled rates, such as Dulles Toll Road rates without observed price
  history, as `schedule_derived`; preserve the schedule identifier and effective
  interval, and never present them as observed averages.
- Preserve `pricing_method` and `proxy_od_pair_id` for modeled components; never
  present proxy-derived prices as observations.
- Do not silently widen the time window or use older data when coverage is poor.

For the adopted VDOT sources, map `trip_pricing_i95.calculated_at` and
`trip_pricing_i66.calculated_at` to the observation time; modeled I-95 prices
inherit the proxy row's `calculated_at`. Do not substitute I-95 `current_at`.

## Pricing profile

The historical MVP supports the same single profile as the
[point-in-time contract](point-in-time-pricing-mvp-contract.md): a two-axle
passenger vehicle paying with E-ZPass in toll mode. Reject a malformed profile
as `invalid_request` and any other profile as `unsupported_pricing_profile`.
Never silently substitute the supported profile.

## Analysis response

Money values are decimal strings in US dollars. Times are ISO 8601 values with
an explicit Eastern offset so the calling agent can format them for users.

```json
{
  "route_plan_id": "plan-123",
  "method": "same_weekday_same_15_minute_slot",
  "source_kind": "mixed",
  "requested_at": "2026-08-13T08:00:00-04:00",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  },
  "window_start": "2026-07-16T08:00:00-04:00",
  "window_end": "2026-08-13T08:00:00-04:00",
  "latest_observation_at": "2026-08-06T08:00:00-04:00",
  "component_sources": [
    {
      "route_step_id": "step-1",
      "source_kind": "schedule_derived",
      "pricing_method": "published_schedule",
      "schedules": [
        {
          "schedule_id": "dulles-toll-road-2026-rates",
          "effective_from": "2026-01-01T00:00:00-05:00",
          "effective_until": null
        }
      ]
    },
    {
      "route_step_id": "step-2",
      "source_kind": "observed",
      "pricing_method": "source_observation"
    }
  ],
  "comparable_period_count": 4,
  "expected_comparable_period_count": 4,
  "comparable_totals": [
    {"departure_at": "2026-07-16T08:00:00-04:00", "total_usd": "7.10"},
    {"departure_at": "2026-07-23T08:00:00-04:00", "total_usd": "9.00"},
    {"departure_at": "2026-07-30T08:00:00-04:00", "total_usd": "9.50"},
    {"departure_at": "2026-08-06T08:00:00-04:00", "total_usd": "13.60"}
  ],
  "mean_usd": "9.80",
  "median_usd": "9.25",
  "minimum_usd": "7.10",
  "maximum_usd": "13.60",
  "nearby_departures": [
    {
      "offset_minutes": -15,
      "mean_usd": "8.40",
      "comparable_period_count": 4
    },
    {
      "offset_minutes": 15,
      "mean_usd": "10.20",
      "comparable_period_count": 4
    }
  ]
}
```

### Required fields

| Field | Meaning |
| --- | --- |
| `route_plan_id` | Identifier of the immutable route plan supplied by the caller. |
| `method` | Exact comparison method used. MVP value: `same_weekday_same_15_minute_slot`. |
| `source_kind` | `observed`, `schedule_derived`, `modeled`, or `mixed`; `mixed` means the route total combines more than one source kind. |
| `requested_at` | Requested departure time used to select comparable observations. |
| `pricing_profile` | Vehicle and payment assumptions applied to every comparable route total. |
| `window_start`, `window_end` | Half-open 28-day analysis window: `[window_start, window_end)`. |
| `latest_observation_at` | Newest observation included across all comparable periods and route components; `null` when `source_kind` is `schedule_derived`. |
| `component_sources` | Source kind and pricing method for each canonical route step, preserving schedule or model provenance when applicable. |
| `comparable_period_count` | Number of complete comparable trip observations used. |
| `expected_comparable_period_count` | Number expected under full coverage, normally four. |
| `comparable_totals` | Departure instant and complete route total for every included period. |
| `mean_usd` | Arithmetic mean of comparable route totals. |
| `median_usd` | Median comparable route totals. |
| `minimum_usd`, `maximum_usd` | Observed range; not a confidence interval. |
| `nearby_departures` | Optional comparisons for the adjacent 15-minute slots. |

A `schedule_derived` component source additionally requires every schedule used
by its comparable totals, each with `schedule_id`, `effective_from`, and
nullable `effective_until`. A `modeled` component source additionally requires
its versioned `pricing_method` and `proxy_od_pair_id`:

```json
{
  "route_step_id": "step-3",
  "source_kind": "modeled",
  "pricing_method": "identity_proxy_v1",
  "proxy_od_pair_id": 1165
}
```

Any comparable total or statistic containing a modeled component remains a
provisional ballpark estimate. The caller must preserve that qualification for
budget counts, ranges, medians, nearby-departure comparisons, and every other
derived insight.

## Caller-derived metrics

The historical analysis does not query point-in-time pricing. When current and
historical analyses are requested together, the caller may derive:

```json
{
  "comparison_basis": "median",
  "current_delta_usd": "4.95",
  "current_delta_percent": "53.5",
  "current_position": "above_recent_range",
  "higher_than_count": 4
}
```

Use the median as a "typical" comparison only with full 4-of-4 coverage. With
partial coverage, call it the median of the available comparable trips and
always disclose the count. Round percentage changes to one decimal place using
decimal half-up rounding; return them as `null` when the comparison value is
zero.

When the user supplies a budget, the caller counts qualifying values in
`comparable_totals` and may report the literal count, such as "the toll was $10
or less on 3 of 4 comparable Thursdays."
Annual projections require an explicit trip frequency:

```text
annual_estimate = mean_usd * one_way_trips_per_week * 52
```

## Failure contract

Reject an invalid request or unsupported profile before querying history:

```json
{
  "route_plan_id": "plan-123",
  "error": "historical_pricing_unavailable",
  "reason": "unsupported_pricing_profile",
  "pricing_profile": {
    "vehicle_class": "three_axle_vehicle",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

An `invalid_request` response must identify each invalid field and reason.

Return no summary prices when there are zero complete comparable observations:

```json
{
  "route_plan_id": "plan-123",
  "error": "insufficient_recent_history",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  },
  "window_start": "2026-07-16T08:00:00-04:00",
  "window_end": "2026-08-13T08:00:00-04:00",
  "comparable_period_count": 0,
  "expected_comparable_period_count": 4
}
```

For partial coverage, return the available statistics with the actual and
expected counts. The calling agent must disclose that coverage rather than
describing the result as a four-week average.

## Deferred beyond MVP

- Forecasting future prices.
- Confidence intervals or volatility scores.
- Seasonal and multi-year comparisons.
- Travel-time savings, cost per minute saved, and arrival reliability.
- Automatic widening of the comparison window.

Add these only when their required data and user value are demonstrated.

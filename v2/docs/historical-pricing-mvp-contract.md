# Historical Pricing MVP Contract

## Purpose

Describe what the same canonical route cost at the current facility time during
the prior three weeks. The MVP compares the route without changing it and does
not widen the window when coverage is poor.

## Comparison method

- Record `evaluated_at` and use the same current facility anchors as the
  [point-in-time contract](point-in-time-pricing-mvp-contract.md).
- I-66 uses independent 6-minute bins. I-95/I-495 uses independent 10-minute
  bins with one shared feed anchor.
- For each component, use `prior_week` offsets 1, 2, and 3 from its facility
  view. Current prices are not included in historical statistics.
- Match the same Eastern local weekday and wall-clock bin. Components from
  different facilities need not share source timestamps.
- Use PostgreSQL's later standard-time occurrence for an ambiguous fall-back
  target. A nonexistent spring-forward target is ineligible and reduces the
  expected count.
- For every route key and target bin, select the latest source row before
  applying availability. Never fall back to an older usable row.
- I-95/I-395 comparisons must satisfy both the canonical schedule and stored
  direction sentinels. This excludes holiday and major-event regimes that run
  opposite the canonical schedule.
- Exclude a week unless every required route component is available. Missing
  and unavailable components are not zero.
- Calculate each complete route total before calculating statistics. Do not
  average legs independently.
- Preserve schedule and model provenance. Any statistic containing a modeled
  component remains a provisional ballpark estimate.

## Pricing profile

The historical MVP supports the same two-axle passenger E-ZPass toll-mode
profile as the point-in-time contract. Reject malformed or unsupported
profiles.

## Analysis response

```json
{
  "route_plan_id": "plan-123",
  "method": "same_weekday_same_facility_bins",
  "evaluated_at": "2026-08-13T08:32:05-04:00",
  "source_kind": "mixed",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  },
  "component_sources": [
    {
      "route_step_id": "step-1",
      "source_kind": "schedule_derived",
      "pricing_method": "published_schedule",
      "schedule_id": "dulles-toll-road-2026-rates"
    },
    {
      "route_step_id": "step-2",
      "source_kind": "observed",
      "pricing_method": "source_observation",
      "facility": "i66",
      "bin_minutes": 6
    },
    {
      "route_step_id": "step-3",
      "source_kind": "observed",
      "pricing_method": "source_observation",
      "facility": "i95_i495",
      "bin_minutes": 10
    }
  ],
  "comparable_period_count": 3,
  "expected_comparable_period_count": 3,
  "comparable_totals": [
    {"week_offset": 3, "departure_at": "2026-07-23T08:20:00-04:00", "total_usd": "7.10"},
    {"week_offset": 2, "departure_at": "2026-07-30T08:20:00-04:00", "total_usd": "9.00"},
    {"week_offset": 1, "departure_at": "2026-08-06T08:20:00-04:00", "total_usd": "13.60"}
  ],
  "mean_usd": "9.90",
  "median_usd": "9.00",
  "minimum_usd": "7.10",
  "maximum_usd": "13.60",
  "latest_observation_at": "2026-08-06T08:10:00-04:00"
}
```

`expected_comparable_period_count` is normally three. It decreases only for an
invalid local wall-clock target, such as the spring-forward gap. Missing,
closed, exceptional-schedule, or otherwise unavailable data reduces
`comparable_period_count`, not the expected count.

With partial coverage, return statistics for available complete periods and
disclose both counts. With zero complete periods, return:

```json
{
  "route_plan_id": "plan-123",
  "error": "insufficient_recent_history",
  "evaluated_at": "2026-08-13T08:32:05-04:00",
  "comparable_period_count": 0,
  "expected_comparable_period_count": 3
}
```

## Caller-derived current comparison

When current and historical pricing are requested together, the caller may
compare the current total with the historical median and range. Use the median
as a typical value only with full 3-of-3 coverage; otherwise call it the median
of the available comparable trips.

Round percentages to one decimal place using decimal half-up rounding and
return `null` when the comparison value is zero. A budget answer reports the
literal count of qualifying values rather than converting three observations
into a probability.

## Deferred beyond MVP

- Nearby-departure comparisons.
- Automatic widening beyond three weeks.
- Holiday/event override calendars.
- Forecasts, confidence intervals, volatility scores, and seasonal history.

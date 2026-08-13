# Historical Pricing MVP Contract

## Purpose

Define the smallest useful response contract for TollChat's rolling-average
pricing specialist. The specialist receives the orchestrator's canonical route
plan and describes what that same trip recently cost without changing the route.

The MVP uses the previous four weeks because recent prices are more useful to a
traveler than a long-term average that hides current commuting patterns.

## Comparison method

- Match the requested route, local weekday, and 15-minute departure slot.
- Use one comparable trip price from each eligible date in the half-open window
  from 28 days before the requested time through, but not including, the
  requested time, for at most four comparable weekdays.
- Calculate route totals for each date before calculating summary statistics.
  Do not independently average legs and then combine them.
- Exclude missing or incomplete route observations instead of treating them as
  zero.
- Report scheduled rates, such as Dulles Toll Road rates without observed price
  history, as `schedule_derived`; never present them as observed averages.
- Do not silently widen the time window or use older data when coverage is poor.

## Specialist response

Money values are decimal strings in US dollars. Times are ISO 8601 values with
an explicit Eastern offset so the orchestrator can format them for users.

```json
{
  "route_plan_id": "plan-123",
  "method": "same_weekday_same_15_minute_slot",
  "source_kind": "observed",
  "requested_at": "2026-08-13T08:00:00-04:00",
  "window_start": "2026-07-16T08:00:00-04:00",
  "window_end": "2026-08-13T08:00:00-04:00",
  "latest_observation_at": "2026-08-06T08:00:00-04:00",
  "comparable_period_count": 4,
  "expected_comparable_period_count": 4,
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
| `route_plan_id` | Identifier of the immutable route plan supplied by the orchestrator. |
| `method` | Exact comparison method used. MVP value: `same_weekday_same_15_minute_slot`. |
| `source_kind` | `observed` or `schedule_derived`. |
| `requested_at` | Requested departure time used to select comparable observations. |
| `window_start`, `window_end` | Half-open 28-day analysis window: `[window_start, window_end)`. |
| `latest_observation_at` | Newest observation included in the result. |
| `comparable_period_count` | Number of complete comparable trip observations used. |
| `expected_comparable_period_count` | Number expected under full coverage, normally four. |
| `mean_usd` | Arithmetic mean of comparable route totals. |
| `median_usd` | Median comparable route total. |
| `minimum_usd`, `maximum_usd` | Observed range; not a confidence interval. |
| `nearby_departures` | Optional comparisons for the adjacent 15-minute slots. |

## Orchestrator-derived metrics

The historical specialist does not call point-in-time pricing tools. When both
specialists are requested, the orchestrator may derive:

```json
{
  "current_delta_usd": "4.40",
  "current_delta_percent": "44.9",
  "current_position": "above_recent_average"
}
```

When the user supplies a budget, the orchestrator may also report the literal
count, such as "the toll was $10 or less on 3 of 4 comparable Thursdays."
Annual projections require an explicit trip frequency:

```text
annual_estimate = mean_usd * one_way_trips_per_week * 52
```

## Failure contract

Return no summary prices when there are zero complete comparable observations:

```json
{
  "route_plan_id": "plan-123",
  "error": "insufficient_recent_history",
  "window_start": "2026-07-16T08:00:00-04:00",
  "window_end": "2026-08-13T08:00:00-04:00",
  "comparable_period_count": 0,
  "expected_comparable_period_count": 4
}
```

For partial coverage, return the available statistics with the actual and
expected counts. The orchestrator must disclose that coverage rather than
describing the result as a four-week average.

## Deferred beyond MVP

- Forecasting future prices.
- Confidence intervals or volatility scores.
- Seasonal and multi-year comparisons.
- Travel-time savings, cost per minute saved, and arrival reliability.
- Automatic widening of the comparison window.

Add these only when their required data and user value are demonstrated.

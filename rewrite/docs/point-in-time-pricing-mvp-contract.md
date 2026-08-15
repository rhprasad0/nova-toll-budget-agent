# Point-in-Time Pricing and Insights MVP Contract

## Purpose

Define the smallest useful response contract for TollChat's deterministic
current-or-past pricing analysis. The analysis receives an immutable canonical
route plan and reports the latest complete source price whose interval and
observation do not follow the requested instant. It does not change the route.

A past lookup reconstructs what the source recorded for that instant. It is not
a knowledge-as-of audit: a corrected record may have been ingested by TollChat
after the requested instant even though its source interval and observation
belong to that earlier time.

The result is a pricing snapshot and estimate, not an operator quote. Dynamic
tolls can change after the response, and the payable Express Lanes price is
locked only when the driver passes the applicable final roadside pricing sign.
Do not return a `quote_id`, `valid_until`, or other field that implies TollChat
can guarantee the charge.

This contract is the point-in-time companion to the
[historical pricing contract](historical-pricing-mvp-contract.md). The caller
may combine both responses to explain whether the current price is unusual,
within budget, or historically cheaper at a nearby departure time.

## Pricing method

- Require an explicit `requested_at`. When the user says "now," the caller
  resolves that phrase to one instant before requesting the route and price.
- Record `evaluated_at` before selecting prices and reject a `requested_at`
  later than it. Point-in-time pricing does not forecast dynamic tolls, even
  when some route components have published schedules.
- Price every route component at `requested_at`. The MVP does not invent travel
  times to estimate when the vehicle will reach later components.
- For an observed component, select its latest complete source row with both
  `interval_end_at <= requested_at` and `observed_at <= requested_at`. Select
  the latest row before applying its availability rule, so a closed or
  indeterminate latest row cannot expose an older open toll.
- Require `0 <= requested_at - observed_at <= 30 minutes` for every observed or
  modeled component. Base freshness on the source observation time, not its
  later publication interval.
- For a schedule-derived component, select the published rate applicable at the
  local `requested_at`. Preserve its stable schedule identifier and effective
  interval. Scheduled prices have no observation timestamp and must never be
  described as live or observed.
- For a modeled component, apply the same observation selection, availability,
  and freshness rules as its proxy observation. Preserve the model method and
  proxy identifier; never relabel the result as observed.
- Calculate the complete route total only after every required component has a
  usable price. Do not return a partial total or treat a missing price as zero.
- An empty component list and `total_usd: "0.00"` mean the canonical route is
  known to contain no toll, not that toll pricing failed.

The 30-minute freshness boundary is a provisional operational policy, not a
source guarantee. Validate it against retained source cadence and lag before
deployment. Revisit it only with measured source behavior, not by silently
widening it during an outage.

For the adopted VDOT sources, map `trip_pricing_i95.calculated_at` and
`trip_pricing_i66.calculated_at` to `observed_at`; modeled I-95 prices inherit
the proxy row's `calculated_at`. Do not substitute I-95 `current_at` when
selecting observations or enforcing freshness.

## Pricing profile

The MVP supports one explicit profile:

```json
{
  "vehicle_class": "two_axle_passenger",
  "payment_method": "e_zpass",
  "transponder_mode": "toll"
}
```

This profile applies the toll-paying E-ZPass rate. It does not apply motorcycle,
bus, HOV, occupancy, pay-by-plate, cash, trailer, or three-or-more-axle rules.
Reject unsupported profiles rather than silently substituting this one.

## Pricing response

Money values are decimal strings in US dollars. Times are ISO 8601 values with
an explicit Eastern offset so the calling agent can format them for users.

```json
{
  "route_plan_id": "plan-123",
  "method": "latest_complete_component_price_at_or_before_requested_time",
  "requested_at": "2026-08-13T08:32:00-04:00",
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
      "priced_as_of": "2026-08-13T08:20:00-04:00",
      "observed_at": "2026-08-13T08:10:00-04:00"
    }
  ],
  "total_usd": "9.20",
  "recent_movement": {
    "method": "same_route_three_15_minute_snapshots",
    "direction": "rising",
    "samples": [
      {
        "at": "2026-08-13T08:02:00-04:00",
        "total_usd": "7.10",
        "component_observations": [
          {"route_step_id": "step-2", "observed_at": "2026-08-13T07:50:00-04:00"}
        ]
      },
      {
        "at": "2026-08-13T08:17:00-04:00",
        "total_usd": "8.00",
        "component_observations": [
          {"route_step_id": "step-2", "observed_at": "2026-08-13T08:00:00-04:00"}
        ]
      },
      {
        "at": "2026-08-13T08:32:00-04:00",
        "total_usd": "9.20",
        "component_observations": [
          {"route_step_id": "step-2", "observed_at": "2026-08-13T08:10:00-04:00"}
        ]
      }
    ],
    "net_change_usd": "2.10",
    "net_change_percent": "29.6"
  }
}
```

### Required fields

| Field | Meaning |
| --- | --- |
| `route_plan_id` | Identifier of the immutable route plan supplied by the caller. |
| `method` | Exact selection method. MVP value: `latest_complete_component_price_at_or_before_requested_time`. |
| `requested_at` | Instant at which the same route is priced. |
| `evaluated_at` | Instant when TollChat performed the analysis. |
| `maximum_observation_age_minutes` | Maximum permitted source-observation age for observed and modeled prices. MVP value: `30`. |
| `pricing_profile` | Vehicle and payment assumptions applied to every component. |
| `source_kind` | `observed`, `schedule_derived`, `modeled`, `mixed`, or `none`. `mixed` means more than one priced source kind; `none` means the route has no toll components. |
| `components` | Complete component prices in canonical route order, including provenance and source timestamps. |
| `total_usd` | Exact decimal sum of all component prices. |
| `recent_movement` | Optional descriptive comparison of three complete route snapshots; omitted unless all three are available. |

For each component, `priced_as_of` is the selected source interval end and
`observed_at` is the source's calculation or observation time. Both are `null`
for `schedule_derived` prices, which instead require `schedule_id`,
`effective_from`, and nullable `effective_until`. A `modeled` component
additionally requires its model-specific fields:

```json
{
  "route_step_id": "step-3",
  "price_usd": "8.05",
  "source_kind": "modeled",
  "pricing_method": "identity_proxy_v1",
  "proxy_od_pair_id": 1165,
  "priced_as_of": "2026-08-13T08:20:00-04:00",
  "observed_at": "2026-08-13T08:10:00-04:00"
}
```

The caller must describe that value as a provisional ballpark estimate, not an
operator observation.

## Recent movement

`recent_movement` describes what happened; it does not predict the next price.
Evaluate the same immutable route and pricing profile at `requested_at`, 15
minutes earlier, and 30 minutes earlier using the normal completeness and
freshness rules. Calculate each complete route total before comparing samples.

- `rising`: both consecutive changes are greater than zero.
- `falling`: both consecutive changes are less than zero.
- `unchanged`: all three totals are equal.
- `mixed`: every other complete sequence.

Each sample lists the selected `observed_at` for every observed or modeled
component so reused source data remains visible. `net_change_usd` is the latest
total minus the earliest. Calculate `net_change_percent` against the earliest
total; return it as `null` when the earliest total is zero. Round percentages to
one decimal place using decimal half-up rounding. Omit the entire object if any
sample is unavailable.

Emit movement for a route with schedule-derived components only when the same
schedule identifier and effective interval cover all three sampled instants.
Otherwise omit `recent_movement`; the MVP does not carry multiple schedule
versions inside that object.

Prefer user wording such as "the available estimate has risen" over "the price
is increasing," which could be mistaken for a forecast. When all three totals
are equal, say "the available estimate did not change across the sampled
instants." Do not claim three source prices were unchanged when a component
reused the same observation.

## Caller-derived user insights

The point-in-time response remains source evidence. The caller may combine it
with other contracts to produce user-facing insights without duplicating those
analyses here.

### Historical comparison

When the point-in-time and historical responses use the same `route_plan_id`
and pricing profile, compare the current total with complete
`comparable_totals` for the same local weekday and 15-minute slot. This is a
slot comparison, not an assertion that every price was observed at the same
instant. If a schedule-derived rate changes between the slot start and
`requested_at`, omit the combined comparison.

```json
{
  "basis": "median",
  "historical_median_usd": "9.25",
  "current_delta_usd": "4.95",
  "current_delta_percent": "53.5",
  "position": "above_recent_range",
  "higher_than_count": 4,
  "comparable_period_count": 4,
  "recent_minimum_usd": "7.10",
  "recent_maximum_usd": "13.60"
}
```

Use the median as the user-facing comparison because a single congestion spike
can pull the mean away from the usual trip. Call it a "typical price" only with
full 4-of-4 coverage, and always disclose the count. With partial coverage,
describe it literally as the median of the available comparable trips. Keep the
historical mean available for questions that explicitly ask for an average.
If any comparable total contains a modeled component, preserve that provenance
and describe the comparison as a provisional ballpark estimate.

Define `position` without an invented confidence score:

- `below_recent_range` when the current total is below the historical minimum.
- `within_recent_range` when it is between the minimum and maximum, inclusive.
- `above_recent_range` when it is above the historical maximum.

`higher_than_count` is the literal number of comparable totals strictly below
the current total. Disclose it with the available coverage, for example,
"higher than all 4 comparable Thursdays." Do not convert four observations into
a percentile, confidence level, or universal `low`/`typical`/`high` score.
Return percentage changes as `null` when the comparison value is zero.
Round non-null percentages to one decimal place using decimal half-up rounding.

### Budget and nearby departures

When the user supplies a budget, the caller may report the current dollar
difference and count complete historical totals at or below that budget. Keep
the count literal: "the current estimate is $2.20 over budget; 3 of 4 comparable
trips were within budget."

The historical response's `nearby_departures` may support a planning statement
such as "leaving 15 minutes earlier averaged $1.40 less over four comparable
Thursdays." This is a historical comparison, not a promise that the next toll
will be cheaper.

### Immediately available context

The caller can provide these without the four-week rolling analysis:

- the current complete route total and component breakdown;
- recent route-total movement;
- the pricing profile and facility-specific payment requirements;
- a warning when source data approaches the freshness boundary; and
- a deterministic upcoming change in a published schedule, clearly separated
  from unknown future dynamic prices.

Do not infer a crash or promise travel-time savings from a high toll alone.
Dynamic pricing responds to traffic demand, but identifying the cause or value
of the toll requires independent traffic and route data.

## Failure contract

Return no component prices, recent movement, or total when any required
component cannot be priced:

```json
{
  "route_plan_id": "plan-123",
  "error": "point_in_time_pricing_unavailable",
  "reason": "incomplete_route_price",
  "requested_at": "2026-08-13T08:32:00-04:00",
  "evaluated_at": "2026-08-13T08:32:05-04:00",
  "unavailable_components": [
    {
      "route_step_id": "step-2",
      "reason": "stale_observation",
      "latest_observation_at": "2026-08-13T07:50:00-04:00"
    }
  ]
}
```

Top-level `reason` values are:

- `invalid_request`, including a missing or malformed `requested_at`;
- `future_requested_at`;
- `unsupported_pricing_profile`; or
- `incomplete_route_price`.

Unavailable-component reasons are `missing_observation`, `stale_observation`,
`missing_schedule_rate`, and `facility_unavailable`. An `invalid_request`
response must identify each invalid field and reason. Preserve the selected
latest row's status when it explains unavailability, but do not expose an older
usable price as a fallback. The calling agent must distinguish a known toll with
an unavailable price from a route known to have no toll.

## Design evidence

- [VDOT's I-66 FAQ](https://www.vdot.virginia.gov/projects/major-projects/66expresslanes/faqs/)
  describes current values as estimates, explains that historical averages help
  drivers decide whether to use the lanes, and says the roadside sign locks the
  payable toll.
- [Google Routes toll guidance](https://developers.google.com/maps/documentation/routes/calculate_toll_fees)
  treats toll values as estimates, makes vehicle and toll-pass assumptions part
  of pricing, returns route and leg toll information, and distinguishes a known
  toll with an unknown price from a route without a toll.
- [HERE Routing toll guidance](https://docs.here.com/routing/docs/routing-v8-tolls-for-route)
  returns tolls by route section and states that payment method, vehicle
  characteristics, and time of passage can change the price.
- [Google price insights](https://support.google.com/faqs/answer/10675605)
  uses recent history to explain whether a price is low, typical, or high while
  explicitly separating price history from prediction.
- [Google Flights' deal methodology](https://support.google.com/travel/answer/16497283)
  compares a current price with the median for similar trips and discloses the
  comparison basis. TollChat uses a much smaller four-period sample and
  therefore keeps its claims literal.

## Deferred beyond MVP

- Forecasting future dynamic tolls or promising a cheaper future departure.
- Confidence intervals, percentile ranks, volatility scores, and universal
  `low`/`typical`/`high` labels.
- Profiles other than a two-axle passenger vehicle paying with E-ZPass in toll
  mode, including HOV savings comparisons.
- Estimating separate passage times for later route components.
- Comparing alternative routes, travel-time savings, cost per minute saved,
  fuel cost, and arrival reliability.
- Price alerts, saved-route monitoring, and notifications.

Add these only when their required data, contract, and user value are
demonstrated.

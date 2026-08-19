# Current Pricing MVP Contract

## Purpose

Define the smallest deterministic contract for validating and pricing a
canonical toll route **now**. The MVP does not accept a caller-selected pricing
instant, reconstruct arbitrary past requests, or forecast future dynamic
prices. It may use automatically selected prior observations to put the current
price in context.

The result is an estimate, not an operator quote. A payable Express Lanes toll
is locked only when the driver passes the applicable final roadside sign. Do
not return a `quote_id`, `valid_until`, or other guarantee.

## Agent tool boundary

Expose one Strands tool that accepts exactly:

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:5:exit:EB",
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

`origin_point_id` and `destination_point_id` are stable oracle point IDs. The
input model is strict and forbids additional fields. In particular, callers
must not submit `requested_at`, route arrays, pricing component identifiers, or
a route-plan identifier.

The wrapper follows the existing `validate_toll_route` pattern:

- validate strict request and response models and hide submitted values from
  validation errors;
- connect with RDS IAM as `tollchat_agent` over verified TLS;
- use fixed SQL with bound parameters and require each database operation to
  return its documented bounded result;
- expose only safe operation errors carrying the Strands tool-use reference;
  and
- never return unvalidated database rows to the agent.

Call `oracle.validate_pricing_route` once with the submitted point IDs. It
atomically resolves the canonical route and derives ordered `facility_legs`
from committed connection metadata. Continue to pricing only when its status
is `valid`. For every other documented route status, return the validated route
without prices, a total, or comparisons. A database or wrapper failure is a
tool operation error, not a fabricated route or pricing status. The returned
`facility_legs` are the only route components passed to downstream facility
pricing.

### `facility_legs` JSON contract

`facility_legs` is `[]` unless route status is `valid`. For a valid route it is
an ordered array of pricing-bearing components:

```json
[
  {
    "route_step_id": "step-1",
    "facility": "i95_i495",
    "point_ids": ["i95:203NO", "i495:192NO"],
    "connection_ids": ["source:i95_shared:Northbound:203NO:181ND"],
    "pricing_key": {
      "source_route_key": "Northbound:203NO:181ND",
      "od_pair_id": 1144
    }
  }
]
```

Every object has exactly these common fields:

| Field | Contract |
| --- | --- |
| `route_step_id` | `step-N`, numbered from 1 after non-pricing connections and zero-price charges are omitted. |
| `facility` | One of `i66`, `i95_i495`, `dtr`, or `greenway`. |
| `point_ids` | Exactly two ordered point IDs covered by this pricing component. A two-OD I-95/I-495 connection is split at its boundary point. |
| `connection_ids` | Exactly one canonical Oracle connection ID. Multiple pricing components may reference the same connection. |
| `pricing_key` | Facility-specific stable identity described below. No price, label, or rate amount is returned by route validation. |

`pricing_key` has no additional fields beyond its applicable variant:

| Facility | Required `pricing_key` fields |
| --- | --- |
| `i66` | `source_route_key` (string), `start_zone_id` (integer), `end_zone_id` (integer) |
| `i95_i495` | `source_route_key` (string), `od_pair_id` (integer) |
| `dtr`, `greenway` | `source_route_key` (string), `charge_index` (1-based integer into the canonical connection's ordered charge metadata) |

Array order follows canonical connection order, then source component order.
The Greenway mainline charge excludes the $2 DTR connection fee. Only the two
directed Greenway/DTR handoffs produce that DTR component; other handoffs,
airport access, and zero-price charges do not produce legs. Downstream pricing
operations must resolve each key and return the applicable price; they must not
treat this validation output itself as a price.

Pricing access follows the route function's least-privilege pattern. Each
pricing operation is a narrow `SECURITY DEFINER` function with a fixed trusted
search path, an owner limited to its required pricing relations, and only
`EXECUTE` granted to `tollchat_agent`. Do not grant the agent role direct
`SELECT` access to pricing tables or views.

## Pricing method

- Set top-level `evaluated_at` to the database statement timestamp returned by
  the first pricing operation. Each dynamic component also preserves its
  pricing function's `component_evaluated_at`.
- Use the facility pricing operations backed by
  `pricing.i66_pricing_comparisons` for I-66 and
  `pricing.i95_i495_pricing_comparisons` for I-95/I-395/I-495.
- Select each component's `comparison_kind = 'current'` candidate. Components
  from different facilities intentionally use independent anchors and may have
  different evaluation and observation times.
- Treat the assembled result as a best-effort current snapshot, not an atomic
  database snapshot. Preserve the timestamps that make this variance visible.
- I-66 uses 6-minute bins. I-95/I-495 uses 10-minute bins. Both are half-open
  and aligned to the top of the hour.
- Require `interval_end_at <= component_evaluated_at`,
  `observed_at <= component_evaluated_at`, and an observation age from zero
  through 30 minutes for every current observed or modeled price.
- Select the latest candidate before applying availability. Never expose an
  older open or fresh row when that candidate is closed, indeterminate, or
  stale.
- I-95/I-395 candidates must satisfy both the canonical weekly direction
  schedule and the feed's direction sentinels for that interval. Holiday,
  major-event, and other exceptional schedules that contradict the canonical
  direction are unavailable to this MVP.
- I-495 does not use the reversible I-95/I-395 direction schedule.
- Modeled I-95 prices inherit their proxy observation time and preserve their
  model method and proxy identifier. Never relabel them as observed.
- Schedule-derived components use the published rate applicable at
  `evaluated_at`, preserving schedule identity and effective dates.
- Return a route total only when every required component has a usable current
  price. Missing or unavailable prices are not zero.
- An empty component list and `total_usd: "0.00"` mean the validated route is
  known to contain no toll.

Map `pricing.trip_pricing_i95.calculated_at` and
`pricing.trip_pricing_i66.calculated_at` to `observed_at`. Do not substitute
I-95 `current_at`. `interval_end_at` is the selected source row's interval end;
it is distinct from the facility comparison bin and the observation time.

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

The MVP supports exactly the profile shown in the tool request. Reject a
well-formed alternative as `unsupported_pricing_profile` instead of silently
substituting the supported profile. Malformed input is a tool input-validation
error.

## Pricing response

Money values are decimal strings in US dollars. Times are ISO 8601 values with
an explicit Eastern offset.

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:5:exit:EB",
  "method": "latest_complete_current_facility_prices",
  "evaluated_at": "2026-08-13T08:32:05-04:00",
  "maximum_observation_age_minutes": 30,
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  },
  "source_kind": "observed",
  "components": [
    {
      "route_step_id": "step-1",
      "price_usd": "7.20",
      "source_kind": "observed",
      "pricing_method": "source_observation",
      "facility": "i66",
      "component_evaluated_at": "2026-08-13T08:32:06-04:00",
      "bin_minutes": 6,
      "bin_start": "2026-08-13T08:24:00-04:00",
      "bin_end": "2026-08-13T08:30:00-04:00",
      "interval_end_at": "2026-08-13T08:29:00-04:00",
      "observed_at": "2026-08-13T08:22:00-04:00",
      "recent_movement": {
        "method": "same_facility_leg_three_cycles",
        "direction": "rising",
        "samples": [
          {"cycle_offset": -2, "price_usd": "5.10"},
          {"cycle_offset": -1, "price_usd": "6.20"},
          {"cycle_offset": 0, "price_usd": "7.20"}
        ],
        "net_change_usd": "2.10",
        "net_change_percent": "41.2"
      },
      "prior_week_comparison": {
        "method": "same_weekday_same_facility_bins",
        "comparable_period_count": 3,
        "expected_comparable_period_count": 3,
        "comparable_prices": [
          {"week_offset": 3, "price_usd": "4.10"},
          {"week_offset": 2, "price_usd": "5.00"},
          {"week_offset": 1, "price_usd": "5.20"}
        ],
        "median_usd": "5.00",
        "minimum_usd": "4.10",
        "maximum_usd": "5.20",
        "current_delta_usd": "2.20",
        "current_delta_percent": "44.0",
        "position": "above_recent_range",
        "higher_than_count": 3
      }
    }
  ],
  "total_usd": "7.20"
}
```

`source_kind` is `observed`, `schedule_derived`, `modeled`, `mixed`, or
`none`. Observed and modeled components require facility, evaluation, bin,
source-interval, and observation timestamps. Modeled components additionally
require `pricing_method` and `proxy_od_pair_id` and must be described as
provisional ballpark estimates.

## Recent movement

For each observed or modeled component, use its current facility bin and its
two `prior_cycle` rows. Compare that same dynamic facility leg at offsets `-2`,
`-1`, and `0`. Never combine components or facilities into a movement series.

- `rising`: both consecutive changes are positive.
- `falling`: both consecutive changes are negative.
- `unchanged`: all three prices are equal.
- `mixed`: every other complete sequence.

Omit a component's `recent_movement` unless all three prices are available.
Calculate the percentage against the earliest price using decimal half-up
rounding; use `null` when the earliest price is zero. Schedule-derived
components do not receive movement. Movement is descriptive, not a forecast.

## Prior-week comparison

For each observed or modeled component, use its facility view's `prior_week`
offsets 1, 2, and 3. Each offset compares the same dynamic facility leg at that
facility's current Eastern weekday and wall-clock bin. Facility anchors remain
independent.

Calculate each component's statistics only from its own available prior-week
prices. Never combine facility histories, add component medians, or return a
trip-level historical comparison. Current-component freshness rules do not
apply to prior weeks. Schedule-derived components do not receive a prior-week
comparison.

The expected count is normally three. A nonexistent spring-forward target
reduces it; missing, closed, exceptional-schedule, or otherwise unavailable
data reduces that component's comparable count instead. Omit the component's
comparison only when zero prior-week prices are available.

Use the median as the comparison basis. Call it a typical recent price only
with full 3-of-3 coverage; otherwise describe it as the median of the available
comparable weeks and disclose both counts. Define `position` as:

- `below_recent_range` when the current component price is below the available minimum;
- `within_recent_range` when it is within the inclusive available range; or
- `above_recent_range` when it is above the available maximum.

`higher_than_count` is the literal number of comparable prices below the
current component price. Do not convert three observations into a percentile,
confidence level, or forecast. Calculate percentage change against the median
using decimal half-up rounding; return `null` when the median is zero. Any
comparison for a modeled component remains a provisional ballpark estimate.

## Diagnostic pricing boundary

The facility pricing functions must return an explicit diagnostic result for
the selected candidate rather than relying on a filtered comparison-view row
to explain absence. Each unavailable current component preserves known
`component_evaluated_at`, `interval_end_at`, `observed_at`, and source status,
with exactly one reason:

- `missing_observation`: no candidate or required direction evidence exists;
- `exceptional_i95_schedule`: decisive feed direction evidence contradicts
  the canonical direction for the selected I-95/I-395 interval;
- `facility_unavailable`: the selected candidate exists but its source status
  or modeled result has no usable toll; or
- `stale_observation`: the otherwise usable selected candidate exceeds the
  30-minute current freshness boundary.

Apply those checks in the listed order after candidate selection and never
fall back to an older candidate. The same diagnostics explain excluded
prior-week periods, but incomplete history does not invalidate an available
current total.

## Failure contract

Return no component prices, partial total, or comparisons when any current
component is unavailable:

```json
{
  "origin_point_id": "i66:1:entry:EB",
  "destination_point_id": "i66:5:exit:EB",
  "error": "pricing_unavailable",
  "reason": "incomplete_route_price",
  "unavailable_components": [
    {
      "route_step_id": "step-1",
      "reason": "stale_observation",
      "component_evaluated_at": "2026-08-13T08:32:06-04:00",
      "interval_end_at": "2026-08-13T08:29:00-04:00",
      "observed_at": "2026-08-13T07:55:00-04:00",
      "source_status": null
    }
  ]
}
```

An unsupported well-formed profile uses
`reason: "unsupported_pricing_profile"`. Malformed requests fail wrapper input
validation instead of returning a domain pricing response.

## Deferred beyond MVP

- Arbitrary historical point-in-time reconstruction.
- Forecasts or guaranteed quotes.
- Holiday/event override calendars.
- Occupancy, motorcycle, bus, trailer, pay-by-plate, cash, and 3+ axle rates.

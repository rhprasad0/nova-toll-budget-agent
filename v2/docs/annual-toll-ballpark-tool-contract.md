# Annual Toll Ballpark Tool Contract

## Purpose

Define the smallest deterministic contract for turning recent toll prices into
an annualized commute ballpark. The tool answers one screening question:

> Could this commute cost enough in tolls that I should investigate before
> accepting the offer?

The result mixes observed and provisional modeled component prices. It is
recent price context, not a forecast, quote, expected budget, or probability of
future spending.

This contract implements the
[annualized toll ballpark product](annual-toll-train-product.md) using the
[12-week database design](annual-toll-ballpark-database-design.md).

## Agent tool boundary

Expose one Strands tool named `get_annual_toll_ballpark`:

> Validate a round-trip toll commute and calculate a recent annualized
> ballpark.

```json
{
  "outbound": {
    "origin_point_id": "i495:191NO",
    "destination_point_id": "i95:201ND",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i95:202SO",
    "destination_point_id": "i95:203SD",
    "departure_time": "17:30:00"
  },
  "weekdays": ["monday", "wednesday", "friday"],
  "planned_annual_commute_days": 144,
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  }
}
```

The request model is strict and forbids additional fields. Each direction has
exactly an origin point ID, destination point ID, and local departure time.
Callers do not submit routes, pricing components, sample dates, percentiles, or
a pricing instant.

`weekdays` is a nonempty list of unique lowercase weekday names from Monday
through Sunday. Input order has no meaning; output uses calendar order.
Departure times are wall-clock times in `America/New_York` and contain no UTC
offset. `return.departure_time` must be later than
`outbound.departure_time`; the MVP does not pair overnight commutes.

`planned_annual_commute_days` is an integer from 1 through the smaller of 366
and `53 × number of requested weekdays`. The MVP supports exactly the two-axle
E-ZPass toll profile shown above.

Malformed fields, duplicate weekdays, extra fields, and impossible annual-day
counts are tool input-validation errors. A well-formed unsupported pricing
profile or overnight schedule returns a domain response instead.

After strict input validation, apply domain checks in this order: supported
profile, same-date schedule, both structural routes, then historical pricing.
Profile and schedule failures return before progress events or database calls.

The wrapper follows the current pricing tool pattern:

- hide submitted values from validation errors;
- connect with RDS IAM as `tollchat_agent` over verified TLS;
- perform the anchor, route, and pricing reads in one read-only repeatable-read
  transaction;
- use fixed SQL with bound parameters and validate every bounded database
  result;
- expose only safe operation errors carrying the Strands tool-use reference;
  and
- never return unvalidated database rows to the agent.

## Route contract

Call `oracle.validate_ballpark_route` once for outbound and once for return.
Always validate both directions unless a database operation fails. The
function validates the structural route and returns ordered pricing legs
without consulting live I-95 reversible-lane state.

This tool must not use `oracle.validate_pricing_route`. That function correctly
uses live I-95 availability for current pricing, but a historical round trip
usually asks for both directions regardless of which direction is open now.

Each route result contains:

| Field | Contract |
| --- | --- |
| `status` | `valid`, `invalid_origin`, `invalid_destination`, `no_supported_route`, or `traversal_limit_exceeded`. |
| `reason` | The matching structural reason, or null for `valid`. |
| `point_ids` | Ordered canonical route points; empty when no route exists. |
| `connection_ids` | Ordered canonical connections. |
| `connection_types` | Connection type aligned with each connection ID. |
| `general_purpose_gaps` | Structural I-95 fallback gaps, without live availability evidence. |
| `facility_legs` | Ordered pricing-bearing components for a valid route; otherwise empty. |

Structural reasons reuse the current route reason shapes, excluding every live
availability reason. Each general-purpose gap preserves `connection_id`,
`boundary_point_id`, `role`, and `i95_direction`, with
`fallback_required: null` because no live direction was evaluated.

`facility_legs` uses the same facility, route-step, point, connection, and
facility-specific pricing-key contract as the current pricing tool. Continue
only when both results are `valid`. The tool adds each direction's submitted
point IDs and departure time to its route result. Do not substitute an
alternative route.

## Sample selection

Obtain `evaluated_at` once from PostgreSQL `transaction_timestamp()` inside the
tool's read-only repeatable-read transaction. The target window ends on the
latest completed Eastern local date at that anchor and starts 83 dates earlier.
Eligible dates are the requested weekdays inside that window; the same anchor
and date list are passed to every dynamic pricing operation.

For each eligible date:

1. Retrieve at most one matching row per dynamic route step and direction from
   the applicable ballpark function. Candidate order is observed before
   modeled, then latest `interval_end_at` and latest `observed_at`;
   I-95/I-495 uses ascending source start and end zone IDs as final stable
   tie-breakers.
2. Select the DTR and Greenway rate catalogs in effect at `evaluated_at`.
   Classify Greenway peak or off-peak separately from each sample date plus that
   direction's departure time. Never use the tool execution wall clock as the
   sampled trip's rate period.
3. Apply those current published fixed rates to every eligible date. These are
   assumptions, not historical rates effective on those dates.
4. Sum a direction only when all its required steps have prices.
5. Include the date only when outbound and return are both complete.

Canonical I-95 direction checks remain inside the historical pricing data
path. A closed, reversal, missing, or otherwise unusable row leaves its route
step missing. The date remains in the coverage denominator and appears in
`excluded_dates`; the tool does not invent a more specific cause than the
pricing functions return.

If a requested wall time for a direction with pricing legs is nonexistent or
occurs twice on a daylight-saving transition date, exclude that date instead
of choosing an offset for the user. A direction with no pricing legs remains a
known zero-toll trip and does not require resolving its wall time to an instant.

A structurally valid route with no pricing legs is a known zero-toll trip. A
fixed-only route is sampled from the eligible-date calendar without requiring
a dynamic history row.

## Calculation contract

Sort complete daily round-trip totals from lowest to highest. For percentile
`p`, select nearest rank `x[ceil(p × n)]`. Return P25, P50, and P90 and multiply
each selected daily value by `planned_annual_commute_days` using decimal
arithmetic.

```text
annualized scenario = complete daily round-trip percentile
                      × planned annual commute days
```

Money is serialized as a decimal string with two fractional digits. Coverage
is `complete_pair_count ÷ eligible_date_count`, serialized as a percentage
string rounded half-up to one decimal place. Calculate coverage overall and
for every requested weekday. Dynamic timestamps are ISO 8601 values with an
explicit Eastern offset.

A weekday is `missing` when it has zero complete pairs. It is
`underrepresented` when it has at least one complete pair but fewer than the
largest requested-weekday complete count. Because the target is exactly 12
weeks, every requested weekday has the same denominator.

`uses_modeled` is true when any component in any included complete day was
modeled. `uses_current_fixed_rates` is true when any DTR or Greenway component
was applied.

## Success response

The response contains one mixed sample, not separate observed and modeled
cohorts. This abridged example shows the top-level shape; the empty bounded
arrays stand in for the entries specified below:

```json
{
  "method": "recent_complete_same_date_round_trips",
  "evaluated_at": "2026-08-20T16:15:00-04:00",
  "timezone": "America/New_York",
  "target_window": {
    "start_date": "2026-05-28",
    "end_date": "2026-08-19",
    "date_count": 84
  },
  "available_date_range": {
    "start_date": "2026-05-29",
    "end_date": "2026-08-19"
  },
  "sample_status": "partial",
  "weekdays": ["monday", "wednesday", "friday"],
  "planned_annual_commute_days": 144,
  "pricing_profile": {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll"
  },
  "routes": {
    "outbound": {
      "status": "valid",
      "reason": null,
      "origin_point_id": "i495:191NO",
      "destination_point_id": "i95:201ND",
      "departure_time": "08:00:00",
      "point_ids": ["i495:191NO", "i95:201ND"],
      "connection_ids": ["source:i95_shared:Northbound:191NO:201ND"],
      "connection_types": ["general_purpose_gap"],
      "general_purpose_gaps": [
        {
          "connection_id": "source:i95_shared:Northbound:191NO:201ND",
          "boundary_point_id": "i495:192NO",
          "role": "prefix",
          "i95_direction": "NB",
          "fallback_required": null
        }
      ],
      "facility_legs": [
        {
          "route_step_id": "step-1",
          "facility": "i95_i495",
          "point_ids": ["i495:191NO", "i495:192NO"],
          "connection_ids": ["source:i95_shared:Northbound:191NO:201ND"],
          "pricing_key": {
            "source_route_key": "Northbound:191NO:201ND",
            "od_pair_id": 1083
          }
        },
        {
          "route_step_id": "step-2",
          "facility": "i95_i495",
          "point_ids": ["i495:192NO", "i95:201ND"],
          "connection_ids": ["source:i95_shared:Northbound:191NO:201ND"],
          "pricing_key": {
            "source_route_key": "Northbound:191NO:201ND",
            "od_pair_id": 1374
          }
        }
      ]
    },
    "return": {
      "status": "valid",
      "reason": null,
      "origin_point_id": "i95:202SO",
      "destination_point_id": "i95:203SD",
      "departure_time": "17:30:00",
      "point_ids": ["i95:202SO", "i95:203SD"],
      "connection_ids": ["source:i95_shared:Southbound:202SO:203SD"],
      "connection_types": ["within_facility"],
      "general_purpose_gaps": [],
      "facility_legs": [
        {
          "route_step_id": "step-1",
          "facility": "i95_i495",
          "point_ids": ["i95:202SO", "i95:203SD"],
          "connection_ids": ["source:i95_shared:Southbound:202SO:203SD"],
          "pricing_key": {
            "source_route_key": "Southbound:202SO:203SD",
            "od_pair_id": 1158
          }
        }
      ]
    }
  },
  "coverage": {
    "eligible_date_count": 36,
    "complete_pair_count": 34,
    "coverage_percent": "94.4",
    "by_weekday": [
      {
        "weekday": "monday",
        "eligible_date_count": 12,
        "complete_pair_count": 12,
        "coverage_percent": "100.0"
      },
      {
        "weekday": "wednesday",
        "eligible_date_count": 12,
        "complete_pair_count": 11,
        "coverage_percent": "91.7"
      },
      {
        "weekday": "friday",
        "eligible_date_count": 12,
        "complete_pair_count": 11,
        "coverage_percent": "91.7"
      }
    ]
  },
  "missing_weekdays": [],
  "underrepresented_weekdays": ["wednesday", "friday"],
  "uses_modeled": true,
  "uses_current_fixed_rates": false,
  "scenarios": {
    "low": {
      "percentile": 25,
      "rank": 9,
      "sample_count": 34,
      "daily_round_trip_usd": "18.40",
      "annualized_usd": "2649.60"
    },
    "middle": {
      "percentile": 50,
      "rank": 17,
      "sample_count": 34,
      "daily_round_trip_usd": "24.10",
      "annualized_usd": "3470.40"
    },
    "high": {
      "percentile": 90,
      "rank": 31,
      "sample_count": 34,
      "daily_round_trip_usd": "39.75",
      "annualized_usd": "5724.00"
    }
  },
  "complete_days": [],
  "excluded_dates": []
}
```

The abbreviated arrays above have the exact contracts below. A real success
contains every complete day and every excluded eligible date.

`sample_status` is `complete` only when every eligible date has a complete
pair; otherwise it is `partial`. `available_date_range` is the earliest through
latest complete paired date.

### Complete-day evidence

Each `complete_days` entry contains:

| Field | Contract |
| --- | --- |
| `sample_date` | Eligible Eastern local date. |
| `weekday` | Matching requested weekday name. |
| `uses_modeled` | True when either direction used a modeled component. |
| `outbound`, `return` | Objects containing `total_usd` and every ordered component. |
| `round_trip_total_usd` | Exact outbound plus return total. |

For example, one complete mixed-source day is:

```json
{
  "sample_date": "2026-08-19",
  "weekday": "wednesday",
  "uses_modeled": true,
  "outbound": {
    "total_usd": "10.20",
    "components": [
      {
        "route_step_id": "step-1",
        "facility": "i95_i495",
        "price_usd": "4.00",
        "source_kind": "observed",
        "pricing_method": "source_observation",
        "bin_start_at": "2026-08-19T08:00:00-04:00",
        "bin_end_at": "2026-08-19T08:10:00-04:00",
        "interval_end_at": "2026-08-19T08:05:00-04:00",
        "observed_at": "2026-08-19T08:07:00-04:00",
        "od_pair_id": 1083,
        "proxy_od_pair_id": null
      },
      {
        "route_step_id": "step-2",
        "facility": "i95_i495",
        "price_usd": "6.20",
        "source_kind": "modeled",
        "pricing_method": "identity_proxy_v1",
        "bin_start_at": "2026-08-19T08:00:00-04:00",
        "bin_end_at": "2026-08-19T08:10:00-04:00",
        "interval_end_at": "2026-08-19T08:05:00-04:00",
        "observed_at": "2026-08-19T08:07:00-04:00",
        "od_pair_id": 1374,
        "proxy_od_pair_id": 1146
      }
    ]
  },
  "return": {
    "total_usd": "8.20",
    "components": [
      {
        "route_step_id": "step-1",
        "facility": "i95_i495",
        "price_usd": "8.20",
        "source_kind": "observed",
        "pricing_method": "source_observation",
        "bin_start_at": "2026-08-19T17:30:00-04:00",
        "bin_end_at": "2026-08-19T17:40:00-04:00",
        "interval_end_at": "2026-08-19T17:35:00-04:00",
        "observed_at": "2026-08-19T17:37:00-04:00",
        "od_pair_id": 1158,
        "proxy_od_pair_id": null
      }
    ]
  },
  "round_trip_total_usd": "18.40"
}
```

Observed and modeled dynamic components contain `route_step_id`, `facility`,
`price_usd`, `source_kind`, `pricing_method`, `bin_start_at`, `bin_end_at`,
`interval_end_at`, and `observed_at`. I-95/I-495 components also contain
`od_pair_id` and nullable `proxy_od_pair_id`; a modeled component requires the
proxy ID and `identity_proxy_v1` method. Map a sample row's `uses_modeled`
directly to `source_kind`: true is `modeled` and false is `observed`.

DTR and Greenway components reuse the current pricing tool's
`schedule_derived` component contract, including schedule ID, rate name, source
URL, and retrieval date. Greenway also preserves its peak or off-peak rate
period derived from the sample date and direction's departure time;
`component_evaluated_at` remains the shared database anchor. Their repeated
presence on historical sample dates means only that the current published rate
was applied consistently.

Each `excluded_dates` entry contains `sample_date`, `weekday`,
`missing_outbound_route_step_ids`, and `missing_return_route_step_ids`. At
least one missing-step array must be nonempty. Do not return partial trip totals
or available component prices for an excluded date. Order both evidence arrays
by date. They are disjoint and together account for every eligible date, so the
response remains bounded by the 84-day target window.

## Modeled-price disclosure

Whenever `uses_modeled` is true, the agent must say:

> Includes provisional modeled toll prices that may differ from operator
> prices, sometimes materially. This is a prompt to investigate the commute
> cost, not a budget or forecast.

Whenever `uses_current_fixed_rates` is true, the agent must disclose that
current published fixed rates were applied to historical sample dates and are
not historical rates.

If weekday counts are unequal, describe the result as applying to the
**sampled weekdays**, display the counts, and name every missing or
underrepresented weekday.

## Domain-unavailable responses

A well-formed unsupported profile returns no route or pricing evidence:

```json
{
  "error": "ballpark_unavailable",
  "reason": "unsupported_pricing_profile"
}
```

An unsupported same-date schedule also returns no route or pricing evidence:

```json
{
  "error": "ballpark_unavailable",
  "reason": "overnight_schedule"
}
```

When either structural route is not valid, return both validated route results
and no sample, totals, or scenarios:

```json
{
  "error": "ballpark_unavailable",
  "reason": "route_unavailable",
  "routes": {
    "outbound": {"status": "valid", "facility_legs": []},
    "return": {
      "status": "invalid_origin",
      "reason": {"code": "origin_not_entry"},
      "facility_legs": []
    }
  }
}
```

The abbreviated route objects follow the full route contract above.

When both routes are valid but no eligible date has a complete pair, return no
scenarios or complete-day evidence. Preserve enough evidence to explain the
absence:

```json
{
  "error": "ballpark_unavailable",
  "reason": "no_complete_paired_days",
  "available_date_range": null,
  "target_window": {
    "start_date": "2026-05-28",
    "end_date": "2026-08-19",
    "date_count": 84
  },
  "weekdays": ["monday"],
  "routes": {},
  "coverage": {
    "eligible_date_count": 12,
    "complete_pair_count": 0,
    "coverage_percent": "0.0",
    "by_weekday": [
      {
        "weekday": "monday",
        "eligible_date_count": 12,
        "complete_pair_count": 0,
        "coverage_percent": "0.0"
      }
    ]
  },
  "missing_weekdays": ["monday"],
  "underrepresented_weekdays": [],
  "excluded_dates": []
}
```

The real response includes the full valid route objects and all excluded dates.
`available_date_range` is null in this variant. It also repeats `evaluated_at`,
`timezone`, `planned_annual_commute_days`, and `pricing_profile` from the
success contract.

## Progress and operation errors

Stream these stages, each with `running`, `completed`, or `failed` and one fixed
message per stage/status pair:

| Stage | Running | Completed | Failed |
| --- | --- | --- | --- |
| `route_validation` | Validating outbound and return toll routes | Toll routes validated | Toll route validation failed |
| `historical_pricing` | Retrieving recent toll prices | Recent toll pricing complete | Recent toll pricing failed |
| `ballpark_calculation` | Calculating annual toll ballpark | Annual toll ballpark complete | Annual toll ballpark calculation failed |

A domain-unavailable result is a successful tool response, not an operation
error. Unexpected database, validation-boundary, or serialization failures use
the safe template:

> Unable to calculate the annual toll ballpark. Reference: `{tool_use_id}`.

Log the failure stage and exception type without submitted values or database
rows.

## Generated contract and versioning

Implementation must derive the tool input, output, progress-event, and
operation-error JSON schemas from strict runtime models. Add a separate
`get_annual_toll_ballpark` entry at version `1.0.0` to the tool contract
manifest and lock the generated contract with its SHA-256 digest. Do not change
the published `get_current_toll_price` contract.

## Evaluation contract

The initial contract fixtures must cover:

1. Strict input, named-weekday, annual-day bound, supported-profile, and
   overnight validation.
2. Both structural routes validated even when one is invalid, without live
   I-95 direction gating.
3. The 84-day Eastern window and exactly 12 eligible dates per requested
   weekday, including one transaction anchor, no post-anchor evidence, and
   DST-transition exclusion for non-unique wall times on routes with pricing
   legs.
4. Complete same-date pairing, missing-step exclusion, fixed-only routes, and
   known zero-toll routes, including a zero-toll DST-transition date whose wall
   time does not need resolution.
5. Historical I-95 included only when canonical and observed directions match;
   reversal or closed windows, decisive opposite direction, and missing or
   conflicting sentinels excluded; I-495 samples unaffected by that gate.
6. Duplicate-bin tie-breaking, observed preference, observed/modeled mixing,
   modeled provenance, and top-level modeled disclosure.
7. Current DTR and Greenway charges applied exactly once per applicable trip,
   using weekday peak and weekend off-peak sample times, with the
   historical-rate limitation disclosed.
8. Nearest-rank P25/P50/P90, decimal annualization, coverage rounding, and
   missing or underrepresented weekday classification.
9. Partial samples and `no_complete_paired_days` without imputation or partial
   totals.
10. Bounded complete-day and excluded-date evidence sufficient to reproduce the
   result.
11. Safe progress, domain-unavailable, and operation-error responses.

Forecast language, hidden modeled use, a missing component treated as free,
or a live-direction route rejection are zero-tolerance failures.

## Deferred beyond MVP

- Separate observed and modeled cohorts.
- Historical fixed-rate reconstruction.
- Statistical weighting, forecasts, budgets, or exceedance probabilities.
- Immutable evidence storage or saved annual-ballpark results.
- Train alternatives or broader job-offer advice.

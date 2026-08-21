# Annual Toll Ballpark Tool Contract

## Purpose

`get_annual_toll_ballpark` estimates recent annualized toll scenarios for a
same-day round-trip commute. It is historical context, not a quote, forecast,
or budget.

The supported profile is implicit: two-axle passenger vehicle, E-ZPass, toll
mode. Callers cannot submit a pricing profile.

## Request

```json
{
  "outbound": {
    "origin_point_id": "i95:169NO",
    "destination_point_id": "i395:14SD",
    "departure_time": "08:00:00"
  },
  "return": {
    "origin_point_id": "i395:14NO",
    "destination_point_id": "i95:169SD",
    "departure_time": "17:30:00"
  },
  "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
  "planned_annual_commute_days": 240
}
```

Times are Eastern wall times in `HH:MM:SS`. Weekdays are unique lowercase
names. Annual days must be at most 53 times the number of requested weekdays.
The return time must be later than the outbound time.

## Calculation

The tool validates both routes in one read-only repeatable-read transaction and
builds the requested-weekday calendar for the 84 completed local dates before
the transaction date.

- Greenway and DTR published schedule prices are calculated in Python for each
  eligible date and wall time.
- I-66 and I-95/I-495 samples are selected by their existing bounded Oracle
  functions.
- `oracle.get_annual_ballpark_summary` intersects complete dates across every
  route leg, sums same-date facility and route totals, and returns discrete
  P25, P50, and P90 values.
- Annual values equal the daily statistic times
  `planned_annual_commute_days`.

Combined percentiles are calculated from same-date route totals. They are not
the sum of facility percentiles, which are not additive.

## Success response

```json
{
  "method": "recent_complete_same_date_round_trips",
  "evaluated_at": "2026-08-21T09:00:00-04:00",
  "timezone": "America/New_York",
  "target_window": {
    "start_date": "2026-05-29",
    "end_date": "2026-08-20",
    "date_count": 84
  },
  "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
  "planned_annual_commute_days": 240,
  "coverage": {
    "eligible_date_count": 60,
    "complete_pair_count": 55,
    "coverage_percent": "91.7",
    "by_weekday": [
      {"weekday": "monday", "eligible_date_count": 12, "complete_pair_count": 11, "coverage_percent": "91.7"},
      {"weekday": "tuesday", "eligible_date_count": 12, "complete_pair_count": 11, "coverage_percent": "91.7"},
      {"weekday": "wednesday", "eligible_date_count": 12, "complete_pair_count": 11, "coverage_percent": "91.7"},
      {"weekday": "thursday", "eligible_date_count": 12, "complete_pair_count": 11, "coverage_percent": "91.7"},
      {"weekday": "friday", "eligible_date_count": 12, "complete_pair_count": 11, "coverage_percent": "91.7"}
    ]
  },
  "uses_modeled": true,
  "uses_current_fixed_rates": false,
  "facilities": [
    {
      "facility": "i95_i495",
      "sample_count": 55,
      "uses_modeled": true,
      "uses_current_fixed_rates": false,
      "scenarios": {
        "p25": {"daily_round_trip_usd": "12.00", "annualized_usd": "2880.00"},
        "p50": {"daily_round_trip_usd": "18.00", "annualized_usd": "4320.00"},
        "p90": {"daily_round_trip_usd": "31.00", "annualized_usd": "7440.00"}
      }
    }
  ],
  "sample_status": "partial",
  "available_date_range": {
    "start_date": "2026-05-29",
    "end_date": "2026-08-20"
  },
  "scenarios": {
    "p25": {"daily_round_trip_usd": "12.00", "annualized_usd": "2880.00"},
    "p50": {"daily_round_trip_usd": "18.00", "annualized_usd": "4320.00"},
    "p90": {"daily_round_trip_usd": "31.00", "annualized_usd": "7440.00"}
  }
}
```

`coverage.by_weekday` contains the same four coverage fields plus `weekday`.
Money serializes as two-decimal strings. No raw daily samples, excluded dates,
route paths, pricing keys, or component evidence are returned.

## Unavailable responses

An overnight schedule returns `ballpark_unavailable / overnight_schedule`
without opening the database. A structurally unavailable route returns compact
outbound and return statuses. Zero complete paired dates returns
`no_complete_paired_days` with coverage, flags, an empty facility list, and a
null available range. Operational failures use the standard opaque tool error.

## Version

This compact schema is tool contract **2.0.0**. Contract 1.0.0 remains recorded
in the manifest and is not rewritten.

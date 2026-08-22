# Annual Toll-Commute Affordability Contract

## Purpose

`get_annual_toll_ballpark` gives a job seeker a rough view of how the tolled
portion of a Northern Virginia commute affects annual income. It combines
recent toll scenarios with a fixed one-third tax assumption and a fixed
vehicle-cost assumption of `$0.685` per mile.

This is a starting point for a more serious inquiry, not a toll quote, tax
calculation, forecast, budget, or financial plan. Mileage covers only the
straight-line distance between priced route endpoints; untolled gaps and the
rest of the commute are excluded.

The supported toll profile remains implicit: two-axle passenger vehicle,
E-ZPass, toll mode.

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
  "planned_annual_commute_days": 240,
  "gross_annual_income_usd": "120000.00"
}
```

Income is a positive, two-decimal dollar string. Times are Eastern wall times
in `HH:MM:SS`. Weekdays are unique lowercase names. Annual days must be at most
53 times the number of requested weekdays. The return time must be later than
the outbound time.

## Calculation

The tool validates both routes in one read-only repeatable-read transaction,
calculates their straight-line priced-leg distance, and builds the requested-
weekday calendar for the 84 completed local dates before the transaction date.

- Greenway and DTR published schedule prices are calculated in Python for each
  eligible date and wall time.
- I-66 and I-95/I-495 samples are selected by their existing bounded Oracle
  functions.
- `oracle.get_annual_ballpark_summary` intersects complete dates across every
  route leg, sums same-date facility and route totals, and returns discrete
  P25, P50, and P90 daily tolls.
- Annual toll equals daily toll times `planned_annual_commute_days`.
- Estimated annual after-tax income equals gross income less one-third.
- Annual tolled-portion vehicle cost equals straight-line round-trip priced-leg
  miles times `$0.685` times `planned_annual_commute_days`.
- Each scenario reports total toll-plus-vehicle cost, remaining estimated
  after-tax income, the cost share of after-tax income, and the extra gross
  income needed to offset the cost under the same one-third tax assumption.

Combined percentiles are calculated from same-date route totals. They are not
the sum of facility percentiles, which are not additive.

## Response

Every non-operational response includes:

- `assumptions`: tax fraction, vehicle cost per mile, and distance basis;
- `income`: gross income, estimated tax, and estimated after-tax income;
- `tolled_distance`: outbound, return, and daily round-trip priced-leg miles;
- `vehicle_cost`: daily and annual tolled-portion vehicle cost.

A successful response also includes coverage and provenance, facility toll
scenarios, and combined P25/P50/P90 financial scenarios. Each combined scenario
contains:

- `daily_toll_usd` and `annual_toll_usd`;
- `daily_total_tolled_commute_cost_usd`;
- `average_monthly_tolled_commute_cost_usd`;
- `annual_total_tolled_commute_cost_usd`;
- `estimated_annual_income_after_tax_and_tolled_commute_usd`;
- `tolled_commute_share_of_after_tax_income_percent`;
- `additional_gross_income_to_offset_usd`.

Money and miles serialize as two-decimal strings. No
raw daily samples, excluded dates, route paths, pricing keys, or component
evidence are returned.

## Unavailable responses

An overnight schedule returns `ballpark_unavailable / overnight_schedule`
without opening the database. A structurally unavailable route returns compact
outbound and return statuses. Missing priced-leg coordinates returns
`ballpark_unavailable / distance_unavailable`; the tool does not silently use
zero miles. Zero complete paired toll dates returns `no_complete_paired_days`
with the income, distance, vehicle-cost baseline, coverage, flags, an empty
facility list, and a null available range. Operational failures use the
standard opaque tool error.

## Version

This affordability schema is tool contract **3.0.0**. Earlier immutable release
digests remain recorded in the manifest.

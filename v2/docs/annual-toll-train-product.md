# Annualized Toll Ballparks

## Product promise

TollChat answers one recurring-commute question:

> What have lower-cost, typical, and high-cost toll days looked like for my
> schedule when annualized?

It converts route-specific historical toll evidence into three transparent
annualized daily scenarios. It describes historical prices; it does not
forecast annual spending.

## Intended user

A Northern Virginia commuter evaluating a new workplace or office-attendance
schedule who knows when they expect to commute but cannot turn variable tolls
into comparable ballparks.

## Required inputs

- Driving origin and destination, resolved to one canonical toll itinerary.
- Actual office weekdays and planned annual commute days after holidays or PTO.
- One usual outbound and return departure time in `America/New_York`.
- The supported two-axle E-ZPass toll profile.

If the user supplies only a departure window, TollChat uses one disclosed
anchor time. It does not silently invent a work schedule.

## Product output

### Annualized toll ballparks

Use the most recent 12 weeks of history within the current pricing regime: end
on the latest fully ingested local date and include that date plus the prior 83
local dates. If less history exists, use every available recent date and label
the result as partial history. Sample size or coverage never gates the
ballparks; both are displayed so the result becomes better supported as
observations accumulate.

For each eligible historical date, pair the outbound and return prices from the
same local date and add them before calculating a percentile. Both legs must
match the exact route, direction, usual departure time, pricing profile, and
pricing regime. Exclude an incomplete pair instead of substituting zero or a
price from another date.

Use the requested office weekdays in their planned-calendar proportions, not
in proportion to whichever source rows survived ingestion. Select one price
per leg and date with a documented source-revision and freshness rule. Do not
pool modeled and observed dynamic prices or observations from different
pricing regimes.

Show three ballparks from the weighted empirical distribution of complete
paired-day dynamic toll totals:

| Ballpark | Statistic | Meaning |
| --- | --- | --- |
| Low | 25th percentile | Lower-cost historical day. |
| Middle | Median | Typical historical day. |
| High | 90th percentile | High-cost historical day, not a ceiling. |

Use a versioned weighted nearest-rank percentile convention. Add applicable
published fixed round-trip charges once to each paired-day statistic, then
annualize deterministically:

```text
annualized scenario = (paired-day dynamic statistic
                       + fixed round-trip charges)
                      × planned annual commute days
```

Every result carries this label:

> Historical paired-day scenarios, annualized for N commute days. These are not
> forecasts or annual percentiles. Based on X complete paired days from DATE
> through DATE within the most recent 12 weeks available.

Display only the sample period, complete paired-date count, eligible-date
coverage, exclusions, fixed charges, calculation, and three ballparks in the
primary answer. Mark missing requested weekdays and possible price-related
missingness prominently, but do not suppress otherwise valid paired dates.
Detailed distribution statistics belong in expandable evidence, not the
decision summary. Return unavailable only when no complete paired date exists.

## Trust contract

Every answer must:

- identify the route, directions, departure times, weekdays, and pricing
  profile;
- cite each toll source with its observation or effective time and retrieval
  time;
- report the target 12-week window, actual available window, eligible dates,
  paired dates, coverage, and exclusions by reason;
- state the pricing regime and percentile convention;
- keep matching, pairing, percentile selection, and arithmetic in deterministic
  code rather than model reasoning;
- distinguish observed, modeled, fixed, and unknown values; and
- make the displayed calculation reproducible from an immutable evidence
  manifest.

A partial answer with explicit gaps is valid. A fabricated or mismatched route,
price, date pair, or zero-cost assumption is not. Never describe the ballparks
as expected spending, annual percentiles, forecasts, or chances of overrun.

## Evaluation contract

The initial eval set must verify:

1. Exact route, direction, profile, weekday, and departure-time matching.
2. Same-date outbound/return pairing and missing-leg exclusion.
3. Deterministic duplicate, revision, and freshness selection.
4. Planned-weekday weighting and weighted nearest-rank P25/P50/P90 selection.
5. Pricing-regime boundaries and separation of modeled from observed prices.
6. Decimal annualization with each fixed component counted exactly once.
7. Complete source, timestamp, coverage, assumption, and exclusion disclosure.
8. Partial-window and sparse-data labeling, using all valid paired dates and
   returning unavailable only when none exist.

Invented or mismatched evidence, incorrect arithmetic, and prohibited forecast
language are zero-tolerance failures. Release also requires frozen numerical
fixtures, degraded-data cases, and agent-response checks for faithfulness to
tool evidence.

## Explicitly out of scope

- Annual spending forecasts, expected budgets, exceedance probabilities, or
  guarantees.
- Salary, tax, benefits, fuel, depreciation, or comprehensive job-offer advice.
- Train, bus, rideshare, relocation, or negotiation advice.

These belong only after the narrow product passes its accuracy, provenance,
and degraded-data evals.

## Future train alternative

After the toll-ballpark MVP, TollChat may offer a train itinerary when it can
establish that WMATA or VRE is a viable alternative for the user's trip. The
agent, not the user, is responsible for discovering the stations and itinerary.

A separate product and evaluation contract must define viability, schedules,
fares, transfers, parking, first/last-mile limits, freshness, and degraded-data
behavior. Train inputs and outputs are not part of the initial MVP or its
release gate.

## MVP success

Given one supported recurring toll itinerary, a user can reproduce all
annualized scenarios, understand that they describe historical daily prices
rather than future annual risk, and see which toll evidence is known or missing.

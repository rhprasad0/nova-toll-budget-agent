# Annualized Toll Ballparks

## Product promise

TollChat answers one recurring-commute question:

> What have lower-cost, typical, and high-cost toll days looked like for my
> schedule when annualized?

It converts route-specific historical toll evidence into transparent low,
middle, and high annualized daily scenarios. Observed and modeled evidence are
presented separately. The product describes historical prices; it does not
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
anchor time. It does not silently invent a work schedule. Holidays, PTO, and
the resulting annual commute-day count remain the user's inputs; TollChat does
not allocate those days among weekdays.

## Product output

### Annualized toll ballparks

Use the most recent 12 weeks of history within the current pricing regime: end
on the latest fully ingested local date and include that date plus the prior 83
local dates. If less history exists, use every available recent date and label
the result as partial history. Sample size or coverage never gates the
ballparks; both are displayed so the result becomes better supported as
observations accumulate.

For each eligible historical date, build the complete canonical route price for
the outbound and return trips, then add those trips before calculating a
percentile. Both trips must match the exact route, direction, usual departure
time, pricing profile, and pricing regime. Exclude an incomplete pair instead
of substituting zero or a price from another date.

Use one complete paired-day total per requested weekday and date, without
calendar weighting or imputation. Select one price per component, leg, and date
with a documented source-revision and freshness rule. If a requested weekday
has no complete pair, use the remaining valid paired dates and disclose the
missing weekday. Do not pool observations from different pricing regimes.

Classify each complete paired-day route total by its dynamic components:

- **observed:** every dynamic component is observed;
- **modeled:** every dynamic component is modeled; or
- **mixed:** the route contains both observed and modeled dynamic components.

Published fixed-price components do not change that classification. A mixed
route total must include every required observed and modeled component while
preserving each component's provenance. Calculate the same three ballparks
independently for each available route-total cohort:

| Ballpark | Statistic | Meaning |
| --- | --- | --- |
| Low | 25th percentile | Lower-cost historical day. |
| Middle | Median | Typical historical day. |
| High | 90th percentile | High-cost historical day, not a ceiling. |

Never pool complete route totals from different cohorts into one percentile
sample. Show the cohort or cohorts supported by the canonical route and data;
do not clutter the primary answer with inapplicable categories. Modeled and
mixed results must identify each model method and proxy and carry this concise
warning:

> This ballpark uses provisional modeled prices that may be low. Treat it as a
> starting point for further inquiry, not a final budget.

The committed evaluation supports only a provisional ballpark description and
does not establish signed bias. Do not claim that modeled prices tend to
underestimate until committed signed-bias evidence supports that statement.

Use a versioned nearest-rank percentile convention. Add applicable
published fixed round-trip charges once to each paired-day statistic, then
annualize deterministically:

```text
annualized scenario = (paired-day dynamic statistic
                       + fixed round-trip charges)
                      × planned annual commute days
```

Every result carries its source kind in this label:

> SOURCE_KIND historical paired-day scenarios, annualized for N commute days.
> These are not forecasts or annual percentiles. Based on X complete paired
> days from DATE through DATE within the most recent 12 weeks available.

For each cohort, display only the sample period, complete paired-date count,
eligible-date coverage, exclusions, fixed charges, calculation, and three
ballparks in the primary answer. Mark missing requested weekdays and possible
price-related missingness prominently, but do not suppress otherwise valid
paired dates. Detailed distribution statistics belong in expandable evidence,
not the decision summary. Return unavailable only when no cohort has a complete
paired date.

## Trust contract

Every answer must:

- identify the route, directions, departure times, weekdays, and pricing
  profile;
- cite each toll source with its observation or effective time and retrieval
  time;
- report the target 12-week window, actual available window, eligible dates,
  paired dates, coverage, and exclusions by reason for each source cohort;
- state the pricing regime, source kind, and percentile convention;
- identify the model method, proxy, and supporting limitation evidence for
  every modeled result;
- keep matching, pairing, percentile selection, and arithmetic in deterministic
  code rather than model reasoning;
- distinguish observed, modeled, and mixed route totals while preserving every
  component's observed, modeled, fixed, or unknown source; and
- make the displayed calculation reproducible from an immutable evidence
  manifest.

A partial answer with explicit gaps is valid. A fabricated or mismatched route,
price, date pair, source kind, or zero-cost assumption is not. Never describe
the ballparks as expected spending, annual percentiles, forecasts, or chances
of overrun.

## Evaluation contract

The initial eval set must verify:

1. Exact route, direction, profile, weekday, and departure-time matching.
2. Same-date outbound/return pairing and missing-leg exclusion.
3. Deterministic duplicate, revision, and freshness selection.
4. Requested-weekday filtering and nearest-rank P25/P50/P90 selection without
   calendar weighting or imputation.
5. Pricing-regime boundaries; observed, modeled, and mixed route-total
   classification; and complete-component handling.
6. Modeled method, proxy, provisional limitation, and supported-claim
   disclosure.
7. Decimal annualization with each fixed component counted exactly once per
   cohort.
8. Complete source, timestamp, coverage, assumption, and exclusion disclosure.
9. Partial-window and sparse-data labeling, using all valid paired dates and
   returning unavailable only when no cohort has any.

Pooling complete route totals from different cohorts, dropping a required
component from a mixed total, presenting modeled prices as observed, invented
or mismatched evidence, incorrect arithmetic, and prohibited forecast language
are zero-tolerance failures. Release also requires frozen numerical fixtures,
degraded-data cases, and agent-response checks for faithfulness to tool
evidence.

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

# Annualized Toll Ballparks and Train Alternative

## Product promise

TollChat answers one recurring-commute question:

> What have lower-cost, typical, and high-cost toll days looked like for my
> schedule when annualized, and what would one selected WMATA or VRE trip cost?

It converts route-specific historical toll evidence into three transparent
annualized daily scenarios and presents one station-to-station rail itinerary.
It describes historical prices; it does not forecast annual spending.

## Intended user

A Northern Virginia commuter evaluating a new workplace or office-attendance
schedule who knows when they expect to commute but cannot turn variable tolls
and fragmented transit information into comparable ballparks.

## Required inputs

- Driving origin and destination, resolved to one canonical toll itinerary.
- Actual office weekdays and planned annual commute days after holidays or PTO.
- One usual outbound and return departure time in `America/New_York`.
- The supported two-axle E-ZPass toll profile.
- One candidate rail origin and destination station.
- Rail service weekday and desired arrival and return-departure times.
- Optional user-supplied station parking and first/last-mile costs.

If the user supplies only a departure window, TollChat uses one disclosed
anchor time. It does not silently invent a schedule, station, parking cost, or
first/last-mile trip.

## Product output

### Annualized toll ballparks

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
> forecasts or annual percentiles.

Display only the sample period, complete paired-date count, eligible-date
coverage, exclusions, fixed charges, calculation, and three ballparks in the
primary answer. Detailed distribution statistics belong in expandable
evidence, not the decision summary.

The initial publication rule requires at least 100 complete paired dates,
representation of every requested weekday, and at least 90% eligible-date
coverage within one pricing regime. These are release policies to validate
against real coverage and stability, not universal statistical thresholds.
Suppress the ballparks when missingness may be related to price or any rule is
not met.

### Train alternative

For one user-selected WMATA, VRE, or documented cross-system itinerary, show:

- origin and destination stations;
- current outbound and return single-trip fares;
- annualized fare and known station-parking cost using the same commute days;
- scheduled one-way duration and transfer count; and
- first/last-mile and parking-availability limitations.

Use single-trip fares for the MVP. Fare-product optimization requires a
calendar-aware model and is out of scope. Scheduled travel time is not a
reliability prediction, and unknown costs remain visibly excluded.

### Comparison

Present two explicitly different baskets side by side:

- **Driving:** annualized tolls only.
- **Rail:** annualized single-trip fares plus explicitly included parking.

Do not calculate a cost difference, rank the options, or compare rail schedule
time with driving time. The comparison exposes known costs and missing inputs;
it does not claim either basket represents total commute cost.

## Trust contract

Every answer must:

- identify the route, directions, departure times, weekdays, and pricing
  profile;
- identify the rail itinerary, service day, and transfers;
- cite each toll, fare, schedule, and parking source with its observation or
  effective time and retrieval time;
- report eligible dates, paired dates, coverage, and exclusions by reason;
- state the pricing regime and percentile convention;
- keep matching, pairing, percentile selection, and arithmetic in deterministic
  code rather than model reasoning;
- distinguish observed, modeled, fixed, scheduled, user-supplied, and unknown
  values; and
- make the displayed calculation reproducible from an immutable evidence
  manifest.

A partial answer with explicit gaps is valid. A fabricated or mismatched route,
fare, transfer, price, date pair, or zero-cost assumption is not. Never describe
the ballparks as expected spending, annual percentiles, forecasts, or chances
of overrun.

## Evaluation contract

The initial eval set must verify:

1. Exact route, direction, profile, weekday, and departure-time matching.
2. Same-date outbound/return pairing and missing-leg exclusion.
3. Deterministic duplicate, revision, and freshness selection.
4. Planned-weekday weighting and weighted nearest-rank P25/P50/P90 selection.
5. Pricing-regime boundaries and separation of modeled from observed prices.
6. Decimal annualization with each fixed component counted exactly once.
7. Correct station, service day, single-trip fare, duration, and transfers.
8. Consistent annual commute days across toll and rail calculations.
9. Complete source, timestamp, coverage, assumption, and exclusion disclosure.
10. Safe abstention for stale, sparse, closed, missing, or conflicting data.

Invented or mismatched evidence, incorrect arithmetic, and prohibited forecast
language are zero-tolerance failures. Release also requires frozen numerical
fixtures, degraded-data cases, and agent-response checks for faithfulness to
tool evidence.

## Explicitly out of scope

- Annual spending forecasts, expected budgets, exceedance probabilities, or
  guarantees.
- Salary, tax, benefits, fuel, depreciation, or comprehensive job-offer advice.
- Fare-product optimization or commuter-benefit tax treatment.
- Door-to-door multimodal routing or automatic nearest-station selection.
- Traffic, train reliability, disruption, or parking-availability prediction.
- Bus-only itineraries, rideshare pricing, relocation, or negotiation advice.

These belong only after the narrow product passes its accuracy, provenance,
and degraded-data evals.

## MVP success

Given one supported recurring toll itinerary and one selected train itinerary,
a user can reproduce all annualized scenarios, understand that they describe
historical daily prices rather than future annual risk, and see which costs are
known, included, or missing before choosing how to commute.

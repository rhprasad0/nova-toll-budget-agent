# Annualized Toll Ballparks

## Product promise

TollChat answers one screening question for a recurring commute:

> Could the toll cost be large enough that I should investigate before
> accepting this offer?

It converts recent route-specific toll prices into low, middle, and high
annualized scenarios. Observed and provisional modeled component prices may be
mixed into one complete route total. The result is a prompt for further
inquiry, not a forecast, quote, or budget.

## Intended user

A Northern Virginia commuter evaluating a new workplace or office-attendance
schedule who knows when they expect to commute but cannot turn variable tolls
into a useful annual ballpark.

## Required inputs

- Driving origin and destination, resolved to canonical outbound and return
  toll itineraries.
- Actual office weekdays and planned annual commute days after holidays or PTO.
- One usual outbound and return departure time in `America/New_York`.
- The supported two-axle E-ZPass toll profile.

The MVP supports only commutes whose outbound and return trips occur on the
same local calendar date; the return departure time must be later than the
outbound departure time. Reject overnight schedules instead of pairing them to
the wrong date.

If the user supplies only a departure window, TollChat uses one disclosed
anchor time. It does not invent a work schedule. Holidays, PTO, and the annual
commute-day count remain user inputs.

## Product output

### Recent daily sample

Use the most recent 12 weeks: end on the latest completed local date and include
that date plus the prior 83 local dates. If less history is available, use every
available recent date and label the result as partial history. Sample size never
gates the ballpark; always disclose it.

Eligible dates are requested-weekday dates inside that 84-day target window.
Define coverage as complete paired days divided by eligible dates, both overall
and for each requested weekday.

For each requested weekday and date:

1. Match the exact outbound and return routes, directions, departure times, and
   pricing profile.
2. Select at most one price for every required component from the matching
   facility bin. Prefer an observed price when both observed and modeled prices
   exist.
3. Apply currently published fixed charges to every sampled day. Disclose that
   they are current rates, not historical rates effective on each sample date.
4. Sum a trip only when every required component has a price.
5. Add outbound and return trips only when both are complete on the same local
   date.

Observed and provisional modeled component prices belong to the same daily
sample. Do not create separate source cohorts. Set `uses_modeled = true` when
any selected component in any complete paired day was modeled.

Exclude incomplete dates instead of substituting zero, borrowing a price from
another date, or imputing one. If a requested weekday has no complete pair, use
the remaining complete dates and disclose the missing weekday. Return
unavailable only when there are no complete paired days.

Report complete-pair counts by requested weekday. If the counts are unequal,
describe the result as applying to the **sampled weekdays** and name every
missing or underrepresented weekday; do not add statistical weighting.

### Annualized scenarios

Calculate one set of nearest-rank statistics over complete daily round-trip
totals:

| Ballpark | Statistic | Meaning |
| --- | --- | --- |
| Low | 25th percentile | Lower-cost recent toll day. |
| Middle | 50th percentile | Middle recent toll day. |
| High | 90th percentile | High-cost recent toll day, not a ceiling. |

For sorted values `x[1]` through `x[n]`, nearest-rank percentile `p` is
`x[ceil(p × n)]`. Use that rule for P25, P50, and P90, including sparse
samples.

Annualize each statistic with decimal arithmetic:

```text
annualized scenario = complete daily round-trip statistic
                      × planned annual commute days
```

The multiplication creates annualized recent daily scenarios. It does not
estimate the distribution of future annual spending.

### Primary answer

Show only:

- route, directions, departure times, weekdays, and pricing profile;
- 12-week target window and actual available date range;
- eligible dates, complete paired days, coverage, and missing weekdays;
- complete-pair counts for each requested weekday;
- recent daily P25, P50, and P90 values;
- planned annual commute days and the displayed calculation;
- low, middle, and high annualized scenarios;
- whether provisional modeled prices were used;
- when applicable, that current published fixed rates were applied to every
  sampled day.

When any modeled price was used, show:

> Includes provisional modeled toll prices that may differ from operator
> prices, sometimes materially. This is a prompt to investigate the commute
> cost, not a budget or forecast.

The intended takeaway is:

> Recent prices suggest this commute could annualize to roughly **$X–$Y** for
> your schedule. That may be material to the offer; investigate before deciding.

`$X–$Y` means the annualized P25 through annualized P90. If weekday coverage is
unequal, replace “for your schedule” with “for the sampled weekdays.”

## Trust contract

Every answer must:

- use the exact validated routes, schedule, and supported pricing profile;
- reject overnight schedules;
- require every route component and same-date outbound/return pair;
- preserve selected sample dates, prices, observation times, pricing methods,
  and modeled proxy IDs in deterministic tool evidence;
- report the target window, available date range, eligible-date count, complete
  counts and coverage overall and by requested weekday, and every missing or
  underrepresented weekday;
- keep matching, summing, percentile selection, and annualization in
  deterministic code rather than model reasoning;
- disclose modeled-price use whenever any selected component was modeled;
- disclose when current fixed rates were applied across historical sample
  dates; and
- describe the result as recent price context, never expected spending, an
  annual percentile, a forecast, a quote, or a chance of overrun.

A partial answer with explicit gaps is valid. A fabricated or mismatched route,
price, date pair, or zero-cost assumption is not.

## Evaluation contract

The initial eval set must verify:

1. Exact route, direction, profile, weekday, and departure-time matching, plus
   overnight-schedule rejection.
2. Facility-bin selection and observed-price preference when both sources
   exist.
3. Complete component handling, same-date outbound/return pairing, and
   incomplete-date exclusion.
4. Observed and modeled price mixing with correct top-level `uses_modeled`.
5. Current published fixed charges included exactly once in each applicable
   daily trip, with the historical-rate limitation disclosed.
6. Requested-weekday filtering and nearest-rank P25/P50/P90 selection using
   `ceil(p × n)`, without weighting or imputation.
7. Decimal annualization using the user-supplied commute-day count.
8. Partial-window, sparse-data, per-weekday counts, defined coverage, and
   sampled-weekday wording when coverage is unequal.
9. Unavailable returned only when no complete paired day exists.
10. Agent language faithful to the directional estimate and modeled warning.

Mismatched evidence, a missing component treated as free, incorrect arithmetic,
hidden modeled-price use, and forecast or budget claims are zero-tolerance
failures. Release requires frozen numerical fixtures and degraded-data cases,
not a separate evidence-storage system.

## Explicitly out of scope

- Annual spending forecasts, expected budgets, exceedance probabilities, or
  guarantees.
- Salary, tax, benefits, fuel, depreciation, or comprehensive job-offer advice.
- Train, bus, rideshare, relocation, or negotiation advice.

## Future train alternative

After the toll-ballpark MVP, TollChat may offer a train itinerary when it can
establish that WMATA or VRE is a viable alternative for the user's trip. The
agent, not the user, is responsible for discovering the stations and itinerary.

A separate product contract must define viability, schedules, fares,
transfers, parking, first/last-mile limits, freshness, and degraded-data
behavior. Train inputs and outputs are not part of this MVP.

## MVP success

Given one supported recurring toll itinerary, a user can see whether recent
tolls may materially change how they view an offer, understand the limited
sample and any modeled-price use, and know that the result calls for
investigation rather than reliance as a budget.

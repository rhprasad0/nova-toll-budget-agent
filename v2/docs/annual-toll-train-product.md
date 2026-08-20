# Annual Toll Budget and Train Alternative

## Product promise

TollChat answers one recurring-commute question:

> What should I budget annually for tolls, and is a specific WMATA or VRE
> itinerary a practical train alternative?

It converts route-specific toll evidence into three transparent annual budgets
and compares them with one scheduled rail itinerary. It is a budgeting aid, not
a toll quote, traffic forecast, or general personal-finance adviser.

## Intended user

A Northern Virginia commuter evaluating a new workplace or office-attendance
schedule who knows when and how often they expect to commute but cannot turn
variable tolls and fragmented transit information into a defensible annual
budget.

## Required inputs

- Driving origin and destination, resolved to one canonical toll itinerary.
- Typical outbound and return departure windows.
- Office days per week and working weeks per year.
- The supported two-axle E-ZPass toll profile.
- One candidate rail origin and destination station.
- Optional user-supplied station parking and first/last-mile costs.

The agent asks for missing required inputs. It does not silently invent a work
schedule, station, parking cost, or first/last-mile trip.

## Product output

### Annual toll budget

Show three budgeting postures derived from route-price evidence for the exact
route, direction, and stated travel windows. Dynamic components use historical
samples; published fixed-price components use the applicable rate:

| Posture | Basis | Meaning |
| --- | --- | --- |
| Risky | 25th-percentile dynamic toll | A favorable-price budget with a higher chance of overrun. |
| Middle | Median dynamic toll | The representative historical budget. |
| Conservative | 90th-percentile dynamic toll | A buffered budget for frequent high-price exposure, not a worst-case ceiling. |

Calculate each result deterministically:

```text
annual toll = (outbound sample + return sample)
              × office days per week
              × working weeks per year
```

Display the outbound and return amounts, annual commute days, sample period,
sample count, calculation, and annual total. Describe all three figures as
historical scenario budgets—not predictions or guaranteed future prices.

If the evidence cannot support a posture, mark it unavailable instead of
substituting a current price, zero, or a model-generated number.

### Train alternative

For one selected WMATA, VRE, or documented cross-system itinerary, show:

- origin and destination stations;
- current fare or cheapest eligible fare product for the stated commute count;
- annual fare and known station-parking cost using the same annual commute days;
- scheduled one-way duration and transfer count; and
- first/last-mile and parking-availability limitations.

Scheduled travel time is not a reliability prediction. Unknown parking,
first/last-mile, or transfer costs remain visibly excluded from the total.

### Comparison

Present the toll postures and train alternative side by side. Compare known
annual cash costs and scheduled travel time without declaring either option
universally "best." The user should be able to see which assumptions change
the result.

## Trust contract

Every answer must:

- identify the toll route, direction, travel windows, and pricing profile;
- identify the rail itinerary and transfers;
- cite each toll, fare, schedule, and parking source with its retrieval time;
- keep arithmetic in deterministic code rather than model reasoning;
- distinguish observed, modeled, scheduled, user-supplied, and unknown values;
- disclose stale, sparse, contradictory, or unavailable evidence; and
- make the complete calculation reproducible from the displayed inputs.

A partial answer with explicit gaps is valid. A fabricated route, fare,
transfer, price, or zero-cost assumption is not.

## Evaluation contract

The initial eval set must verify:

1. Canonical toll-route and direction selection.
2. Correct historical sample filtering and percentile selection.
3. Exact annualization for two-, three-, and five-day office schedules.
4. Correct WMATA/VRE stations, fares, fare product, duration, and transfers.
5. Consistent commute frequency across driving and rail calculations.
6. Source, timestamp, assumption, and excluded-cost disclosure.
7. Safe handling of stale, sparse, closed, missing, and conflicting data.
8. No unsupported recommendation or invented value.

Release requires deterministic numerical checks plus agent-response checks for
faithfulness to tool evidence. "Cannot estimate from available evidence" is an
expected successful outcome in degraded-data cases.

## Explicitly out of scope

- Salary, tax, benefits, fuel, depreciation, or comprehensive job-offer advice.
- Door-to-door multimodal routing or automatic nearest-station selection.
- Traffic, train reliability, disruption, or parking-availability prediction.
- Bus-only itineraries, rideshare pricing, relocation, or negotiation advice.
- A guarantee that future tolls, fares, or schedules will match the estimate.

These belong only after the narrow product passes its accuracy, provenance,
and degraded-data evals.

## MVP success

Given one supported recurring toll itinerary and one selected train itinerary,
a user can reproduce all annual totals, understand how much toll uncertainty
they are budgeting for, and see every known or missing cost before choosing how
to commute.

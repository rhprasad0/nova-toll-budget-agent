# Calibration 7 — annual Outcome leniency

**135/135 references measured; 389/396 application labels and 135/135 actor-validity labels match.** 7 references have disagreements. Negative controls passing overall: **0**. No measurement failures or unknown usage.

Contract **3.0.5 / harness 2.0.12** retains the same application, actor, fixtures, and 135 references. Separate P25/P90 toll figures are optional unless explicitly requested; actual source contradictions remain failures.

[Full static review](calibration-7-review.html) · [Raw report](calibration-7/report.json) · [Receipt](receipt-7.json)

## Gallows hybrid salary regression references

| Trial | Expected Outcome / Grounding / Rules | Measured Outcome / Grounding / Rules |
| --- | --- | --- |
| 1 | Pass / Pass / Pass | Pass / Pass / Pass |
| 2 | Pass / Pass / Pass | Fail / Pass / Pass |
| 3 | Fail / Fail / Pass | Fail / Fail / Fail |

## Recorded disagreements

### Case 10 · good

**grounding:** INCORRECT: Although the $4.00 total and evaluated time match the result, the answer twice says “dtr: $2.00” without labeling it as a per-component amount. The tool result contains two DTR components at $2.00 each, totaling $4.00, so that standalone DTR amount is misleading/unsupported for the full requested trip.

### Case 24 · good

**outcome:** The route clarification and exact current-price call are correct, and the $7.35 observed price and source are supported. However, the response says “Observed 8:09 AM EDT,” while the tool’s actual observed_at is 8:09:30 AM EDT. The timestamp must retain the actual observed hour and minute; the 8:18 evaluation time cannot replace it, and minute precision should be 8:09 AM (or exact seconds).

### Case 25 · good

**outcome:** The price, route, observed-source disclosure, and 8:17 AM timestamp are supported by the result. However, the answer also includes “i66: $7.35,” an internal facility identifier, contrary to the contract’s requirement not to report internal IDs.

### Case 81 · alternative-selected-before-driver

**grounding:** INCORRECT. The assistant claims “I already chose and priced Lee Highway,” but the first call was rejected as route_unavailable and the later call only returned alternatives / an estimate with Lee Highway as the southbound origin, not the user’s intended Gallows-to-Braddock outbound leg. The later “estimate is complete” also lacks any result for the requested outbound route. These are unsupported claims about what was priced/completed.

### Case 68 · salary-chosen-before-consent

**grounding:** CORRECT — The commute days, weekdays, times, route, and income used in the successful annual estimate were supplied by the user before that call. The reported financial figures and historical-sample coverage match the returned result. The earlier midpoint proposal is a separate Rules issue, not an unsupported factual assertion under Grounding.

### Case 52 · review-annual-summary-2

**outcome:** The answer gives the annual affordability figures and assumptions accurately, but omits the requested commute-leg identities and departure/return times. It mentions the weekdays only as sample coverage, rather than restating the specified commute (Gallows Road to Jones Branch Drive/Route 123 and back, Tue–Thu, 7:30 AM/5:15 PM), so it does not retain all the route and schedule facts required by the contract.

### Case 52 · review-annual-summary-3

**rules:** The annual-tool call was properly authorized after the user supplied the route, schedule, days, and income, and its arguments match the permitted contract. However, the response says the prices were not historical observed tolls, even though the supplied annual result uses recent historical price samples and no modeled or fixed-rate source. That is an affirmative misrepresentation of the price evidence, not merely an omitted disclosure.

## Provenance and interpretation

Run cost **$0.23103092**; cumulative **$3.32384076 of $25**. 405 model calls, all usage known. Run `6536dc88-d14d-4005-ad0c-547c0d132286`; source `36a320ee400bf75528ad3febced342ba7739c34c`.

All references, authored labels, and measured verdicts are retained. Agreement with authored labels is not independent accuracy. No trial or verdict is replaced to improve reported agreement.

Codex inspected all seven disagreements under Ryan's explicit instruction to run the adjusted suite. [The execution review](calibration-7/review.json) allows the requested development baseline with these limitations; it does not claim Ryan separately inspected the new verdicts. Gallows trial 2 still receives an unnecessary route/schedule restatement failure. Trial 3's Rules label remains disputed, while Outcome and Grounding both reject its source contradiction.

# Frozen demo 1 review

[Open the offline HTML sample-review page](demo-review.html).

72/72 trials completed on corpus 1.0.5, candidate `e9abf4e`. Raw overall: 27/72 (37.5%). Outcome-only: 37/72. Pass cubed: 3/24 (12.5%). Held-out overall: 3/12. Descriptive case-cluster 95% interval: 25% to 50%. No infrastructure failures.

Demo cost: $0.3888863. Calibration plus demo: $0.724959. All attempts and measurements are retained in `demo-1/`.

## Assistant inspection; human review pending

The HTML page shows trial 1 for eight selected behaviors, including passing and failing trials. The held-out divergent-leg sample was inspected only after the complete run. Do not use it for tuning without reclassification.

- `greenway-current-1`: Review concern: the actor repeatedly demanded an official quote. The judge rejected estimate wording despite a supported amount. Review this interaction before attributing the failure to the application.

- `greenway-origin-correction-1`: Actor deviation: stopped before supplying the required origin correction. Application-quality interpretation is inconclusive.

- `annual-tysons-clarification-1`: Observed: selected Westpark Drive after the clarification question, then stopped after the estimate.

- `annual-missing-schedule-1`: Observed: supplied the requested times, weekdays, and annual days, then stopped after the estimate.

- `annual-salary-range-1`: Actor deviation: stopped instead of supplying the requested income figure. Trial 2 has the same problem. Application-quality interpretation is inconclusive.

- `annual-select-alternative-1`: Observed: selected the offered morning entry and explicitly retained Backlick Road for the evening exit.

- `annual-confirm-divergent-1`: Held-out sample inspected after the completed run. Actor deviation: returned confirmation text with stop=true, so the application never received it. Application-quality interpretation is inconclusive. Do not use this transcript for tuning without reclassifying the case.

- `annual-no-paired-days-1`: Actor deviation: echoed JSON instead of ordinary driver language. The deterministic check also wrongly flagged the explicitly negated $0.00 statement. The checker fix does not rewrite this original result.

The Parkway alias and Pentagon/Eads Street label each identify two distinct frozen endpoint IDs. Review exact-ID rejections before attributing those failures to the application.

Actor-affected application-quality interpretations are inconclusive. The original aggregate remains visible; no baseline or release is approved. A separate synthetic infrastructure example demonstrates an incomplete report without paid calls.

# NY Time and US Format Evaluation Plan

## Requirements

- Interpret user-supplied travel times as the correct instant in
  `America/New_York`, including explicit non-Eastern zones and DST changes.
- Report timestamps as `M/D/YYYY h:MM AM/PM ET`, never raw ISO-8601 or
  month-name variants.

## Deterministic track

All cases use the always-available I-495 route from Jones Branch Drive/Route
123 to Westpark Drive so corridor closures cannot obscure time-format results.

| Case | User time | Expected Eastern instant |
| --- | --- | --- |
| Summer, zone omitted | July 15, 2026 at 3:30 PM | `2026-07-15T15:30:00-04:00` |
| Pacific time stated | July 15, 2026 at 2:00 PM Pacific | `2026-07-15T17:00:00-04:00` |
| Winter, zone omitted | November 3, 2026 at 10:00 AM | `2026-11-03T10:00:00-05:00` |

`TimeInterpretationEvaluator` verifies that the `i495_route` call resolves to
the expected instant. `USFormatEvaluator` derives expected display values from
the captured tool result and rejects any other explicit date/time form. A tool
error with no timestamp is not applicable to the format metric.

The suite's manual `--check` mode covers evaluator failure paths.
See the [README](README.md) for commands.

## Simulated track

The simulated-user track asks for the same route "tomorrow around 3". The actor
receives the real New York date so it can answer a clarification with a concrete
date. `HelpfulnessEvaluator` and `GoalSuccessRateEvaluator` remain observational
because the actor and judges are model-based.

## Latest live results

- Deterministic: `20260802T142444Z.json` — 6/6, overall 1.00.
- Simulated: `20260802T142526Z.json` — pass rate 1.00, overall 0.92
  (helpfulness 0.83, goal success 1.00).

# I-66 / Dulles Toll Road junction evaluation plan

## Purpose

Both directed trips must end the first priced leg and begin the second at the
same untolled I-66 / Dulles Toll Road junction.

## Acceptance criteria

- Planner calls and inputs match the committed oracle-supported route.
- The sole connector has the expected transfer ID, label, and `0.00` price.
- The final answer names the junction, identifies it as untolled, and contains
  no `airport` text.

## Execution

Run `--check` manually with synthetic tool traces. Explicitly authorized live
runs invoke the actual agent and store reports under `eval/results/`.

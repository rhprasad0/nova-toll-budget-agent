# Dulles Connector Road junction evaluation plan

## Purpose

Prevent I-66/Dulles Toll Road routing from being described as airport access.
Both directed trips must plan their two priced legs around the same untolled
Dulles Connector Road handoff.

## Acceptance criteria

- Planner calls and inputs match the committed oracle-supported route.
- The sole connector has the expected transfer ID, label, and `0.00` price.
- The final answer names Dulles Connector Road, identifies it as untolled, and
  contains no `airport` text.

## Execution

`--check` uses synthetic tool traces in CI. The nightly workflow invokes the
actual agent and stores its report under `eval/results/`.

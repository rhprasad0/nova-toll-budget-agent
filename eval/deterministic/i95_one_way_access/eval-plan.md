# I-95/395 one-way access evaluation plan

## Requirement

Issue #47 requires TollChat to explain I-95/395 one-way entry and exit
constraints, offer only compatible nearby choices, and price only a user-selected
replacement.

## Tracks

- **Deterministic:** three code-graded cases validate checker-first tool calls,
  exact structured constraints, alternatives, no premature fare, and a supported
  control route.
- **Simulated:** two explicit driver profiles use three turns to choose a named
  returned alternative and confirm the recovered route.

## Promotion and execution

Run the deterministic suite three times. Only three complete perfect runs make
it eligible for trusted integration CI. The simulated suite is observational and
runs nightly. The authorized live budget is three deterministic suite executions
and one two-case simulation execution.

## Execution record

- 2026-08-04: three deterministic executions passed all three cases with
  populated evaluator details; the suite is promoted to trusted integration CI.
- 2026-08-04: the one authorized simulation execution scored 0.5833 (4/6
  judgments). It is not curated or rerun: one actor stopped after turn one,
  while a grader comparison was corrected to ignore harmless extra tool fields.
  Its next live attempt remains a nightly observation.

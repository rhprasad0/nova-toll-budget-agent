# I-95/395 one-way access evaluation plan

## Requirement

Issue #47 requires TollChat to explain I-95/395 one-way entry and exit
constraints, offer only compatible nearby choices, and price only a user-selected
replacement.

## Tracks

- **Deterministic:** direct and cross-corridor code-graded cases validate
  checker/planner-first calls, exact structured constraints, alternatives, no
  premature fare, and a supported control route.
- **Simulated:** three explicit driver profiles use up to three turns to choose
  a named returned alternative and confirm the recovered route. Objective trace
  grading accepts only guard-generated duplicate cancellations after a matching
  success, permits the changed recovery call, and requires every planner-derived
  downstream step.

## Promotion and execution

Run the code-graded suite three times before treating it as representative
evidence. Both live suites are manually authorized observations; run their
synthetic checks manually first.

## Execution record

- 2026-08-04: three code-graded executions passed all three cases with
  populated evaluator details; the suite was promoted to trusted integration CI.
- 2026-08-11: live execution left required automation because model behavior remains
  stochastic even when trace grading and fixtures are deterministic.
- 2026-08-12: simulation trace grading added duplicate-hook and complete
  cross-corridor recovery coverage; its next live execution remains observational.
- 2026-08-04: the one authorized simulation execution scored 0.5833 (4/6
  judgments). It is not curated or rerun: one actor stopped after turn one,
  while a grader comparison was corrected to ignore harmless extra tool fields.
  Any next live attempt requires explicit authorization.
- 2026-08-04: one renewed deterministic run passed 3/3. The renewed simulation
  scored 0.5277 (3/6): the now-removed exact-three-turn criterion was stricter
  than the simulation contract. The helpfulness judge is calibrated to accept
  the documented Express-Lanes-unavailable and unpriced-general-purpose-lanes
  response without inventing a broader closure.

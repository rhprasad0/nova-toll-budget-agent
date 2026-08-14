# Evaluation plan: duplicate tool guard

## Requirement and metric

Issue #112 requires the Strands hook to suppress an exact repeated tool call within one invocation without blocking a legitimate retry after failure or an SOP-directed call with changed inputs. The single deterministic metric requires exactly one successful execution for every expected SOP tool signature, permits only a guard-generated cancellation after a matching success, and requires all downstream planned steps.

## Scenarios

1. **Dumfries to Westpark:** the direct northbound case that reproduced planner stutter locally.
2. **Pentagon to Westpark:** the direct southbound case observed in live evaluation.
3. **Joplin recovery to Dumfries:** the SOP's cross-corridor `one_way_mismatch` flow, followed by the user's valid changed origin and complete replanning.

## Implementation and progress

The JSONL cases become Strands Evals `Case` objects. A fresh production `build_agent()` runs each case, and a code evaluator grades unique tool IDs, exact input signatures, tool results, cancellation text, ordering, and completion. `--check` uses synthetic trajectories in required CI; live execution is manual because model behavior remains stochastic.

- [x] Plan and three JSONL cases designed from the production SOP and committed route oracle.
- [x] Offline evaluator branches validated.
- [x] Offline CI coverage added.
- [x] Live validation completed on 8/12/2026: after an invalid empty-trajectory
  baseline exposed and repaired response-metric extraction, one renewed run
  passed 3/3. Dumfries produced an exact duplicate planner attempt that the hook
  suppressed before junction and I-495 completion; Pentagon ran normally; and
  the changed Joplin-to-Dumfries replan remained allowed.

## User requirements log

- **8/12/2026:** Write evaluations specifically for the duplicate-tool hook using the TollChat SOP.

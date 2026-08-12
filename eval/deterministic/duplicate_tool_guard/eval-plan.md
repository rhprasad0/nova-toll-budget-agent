# Evaluation plan: duplicate tool guard

## Requirement and metric

Issue #112 requires the Strands hook to suppress an exact repeated tool call within one invocation without blocking a legitimate retry after failure or an SOP-directed call with changed inputs. The single deterministic metric requires exactly one successful execution for every expected SOP tool signature, permits only a guard-generated cancellation after a matching success, and requires all downstream planned steps.

## Scenarios

1. **Dumfries to Westpark:** the direct northbound case that reproduced planner stutter locally.
2. **Pentagon to Westpark:** the direct southbound case observed in nightly evaluation.
3. **Joplin recovery to Dumfries:** the SOP's cross-corridor `one_way_mismatch` flow, followed by the user's valid changed origin and complete replanning.

## Implementation and progress

The JSONL cases become Strands Evals `Case` objects. A fresh production `build_agent()` runs each case, and a code evaluator grades unique tool IDs, exact input signatures, tool results, cancellation text, ordering, and completion. `--check` uses synthetic trajectories only; required CI runs that check, while nightly automation runs the live agent because model execution remains stochastic.

- [x] Plan and three JSONL cases designed from the production SOP and committed route oracle.
- [x] Offline evaluator branches validated.
- [x] CI and nightly automation updated.
- [ ] Live validation pending: the first authorized execution on 8/12/2026
  produced correct-looking responses but invalid empty trajectories because the
  runner read stateful `agent.messages`; response-metric extraction is fixed
  offline, and the invalid report is not curated or rerun.

## User requirements log

- **8/12/2026:** Write evaluations specifically for the duplicate-tool hook using the TollChat SOP.

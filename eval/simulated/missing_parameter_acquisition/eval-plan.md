# Missing parameter acquisition eval plan

## Contract

Issue #29 and the pricing SOP require TollChat to ask for every currently
missing required parameter in one prompt, use the exact names `origin` and
`destination`, avoid re-requesting supplied endpoints, and not ask for omitted
optional `at_time`.

## Scenarios

The JSONL fixture contains the complete three-case matrix: both endpoints
missing, only origin missing, and only destination missing. After clarification,
all cases converge on Jones Branch Drive/Route 123 to Westpark Drive.

## Metrics

- `parameter_request` code-grades exactly one question, all missing parameter
  names, and zero first-turn tool calls.
- `completed_route` code-grades one second-turn `i495_route` call, fixed inputs,
  absent or SDK-added empty `at_time`, and a successful matching tool result.
- Goal success judges the semantic requirements that string and trace checks
  cannot safely infer, including not re-requesting a supplied endpoint.

## Execution

The runner uses the real `build_agent()`, an explicit actor profile, shared
agent-only telemetry, a fresh agent per case, and a two-turn cap. Offline
`--check` runs in ordinary CI; stochastic live simulation runs nightly.

## Progress

- 2026-08-04: designed three scenarios and code-first metrics.
- 2026-08-04: runner, fixtures, evaluator, documentation, and automation added;
  focused offline checks pass.
- 2026-08-04: the single authorized live run exposed an `at_time` suggestion in
  the both-missing response and early actor termination. The failed report was
  not curated. The prompt now forbids extra suggestions, and actors always
  deliver their assigned second-turn facts; no second live run was authorized.
- 2026-08-04: final offline validation passed: 249 tests, Ruff, formatting,
  Pyright, both SOP validators, runner self-check, and contract-version checks.

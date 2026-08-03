# Evaluation Plan for Issue #19 Junction Routing

## Requirements

- Cover the eight named I-66/I-495 and Dulles/I-495 movements plus one
  paraphrase each.
- Code-grade planner-first tool selection, directed boundaries, shared time,
  successful results, connectors, response itemization, and arithmetic.
- Observe three-turn conversational consistency without making stochastic
  judges the regression gate.
- Use PR #53's direct I-66/I-495 transfers; the issue's two detour expectations
  predate that production change.

## Metrics

### Directed junction trace

Require one planner call followed by the two planned pricing calls, exact
connector label and `transfer_id`, one shared planner time, successful captured
results, and expected entry/exit node IDs and directions. Human tool inputs are
accepted only when the captured production tool result resolves to those nodes.

### Grounded response

Require every captured fare and connector, exact decimal arithmetic over only
those fares, and the matching final total. Reject connector `$0.00` billing,
Route 267 detours for direct cases, reverse-edge claims, I-66 Outside the
Beltway substitutions, Transurban attribution, and uncaptured amounts.

### Conversational consistency

Explicit actors keep origin, destination, corridors, and direction immutable;
then confirm the junction and fare calculation over at most three turns. Unique
agent tool spans are code-graded; goal-success and helpfulness are observational.

## Design

```text
test-cases.jsonl
  -> deterministic runner -> build_agent + production tools -> controlled RDS rows
  -> simulated runner -> shared telemetry + Bedrock actor/judges
```

- The fake connection is the only pricing seam. Real oracle lookups, planner
  steps, response envelopes, and committed Dulles rates remain active.
- `--check` executes all 16 planner/fixture paths and synthetic grader failures
  without network access.
- Ordinary CI runs both offline checks. Protected integration runs the stable
  deterministic live suite. Nightly runs the stochastic simulated suite.

## Progress

- [x] Ground Issue #19 against PR #53 and current oracles
- [x] Add sixteen deterministic fixtures
- [x] Add controlled pricing, trace grading, and response grading
- [x] Add sixteen explicit three-turn simulation profiles
- [x] Complete all offline and repository validation
- [x] Execute and inspect the two authorized live suites
- [x] Curate the valid deterministic report; retain the rejected simulation run
  only in ignored scratch evidence
- [ ] Commit

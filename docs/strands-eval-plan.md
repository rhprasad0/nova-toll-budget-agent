# TollChat Pre-AgentCore Strands Evaluation Plan

**Status:** Planning complete; implementation has not started.
**Boundary:** Establish defensible local Strands readiness before AgentCore
evaluation or runtime work. Complete production proof is out of scope.

This is the single task tracker for the pre-AgentCore evaluation effort.

## Locked decisions

| Area | Decision |
| --- | --- |
| Corpus | 100 planned cases + four issue closures + 20 holdouts = **124 cases** |
| Repeats | Three per case = **372 scored runs** |
| Mix | **94 single-turn / 30 multi-turn** |
| Priorities | Correctness and completeness |
| Evidence | Fixture-backed scored runs + five live smoke canaries |
| Judges | Deterministic contracts + **Amazon Nova 2 Pro (preview)** |
| Calibration | 20 user-reviewed, human-labeled packets |
| Workflow | Cloud-free PR checks; manual metered campaign |
| Issue scope | #17/#19 junction cases occupy original slots; four #17 closures and 20 holdouts are additive |

## Phase 1 — Freeze the evaluation contract

- [ ] Define **correctness**:
  - Required tools are called in order with exact arguments.
  - Routes, fares, timestamps, lane availability, and arithmetic match tool
    evidence.
  - Ambiguous, unsupported, and unrelated requests are clarified or refused.
  - No unsupported route, price, timestamp, connector, or toll claim appears.
- [ ] Define **completeness**:
  - Every required planner, junction, and pricing call occurs exactly once.
  - Every billed leg, toll item, observed timestamp, connector, routing note,
    and required limitation is reported.
  - Multi-turn answers retain relevant context and address the active request.
- [ ] Freeze these campaign-fatal **critical violations**:
  - Invented, altered, or omitted billed fares or legs.
  - Price, arithmetic, or timestamp contradicting tool evidence.
  - Pricing an unsupported route or uncovered location.
  - Producing a subtotal or complete total across the unpriced I-95/I-495
    junction.
  - Skipping a required planner or junction call.
- [ ] Freeze the readiness gate:
  - Zero critical violations.
  - Every case passes each applicable deterministic and Nova correctness and
    completeness metric on at least two of three repetitions.
  - Every critical-risk case passes all applicable metrics on all three
    repetitions.
  - Deterministic and Nova correctness and completeness each achieve at least
    90% strict `pass^3`, the percentage of cases passing all three repetitions.
  - Each primary scenario slice and the holdout partition achieve at least 80%
    strict `pass^3` for correctness and completeness.
  - All five live canaries pass their deterministic critical checks.
- [ ] Report run-level `pass^1` over 372 runs and strict `pass^3` over 124
      cases. Unresolved instrument errors block a verdict and count as neither
      agent passes nor failures.
- [ ] **Approval gate 1:** user approves the contract, critical taxonomy, and
      thresholds.

## Phase 2 — Freeze the 124-case corpus

- [ ] Define one versioned JSONL format containing the case ID, user turns,
      primary slice/tags, fixture ID, expected tool trajectory, required and
      prohibited response facts, and applicable critical-rule IDs.
- [ ] Author the 100 planned cases:

  | Primary slice | Cases |
  | --- | ---: |
  | Routine single-corridor | 20 |
  | Cross-corridor | 25 |
  | Ambiguity/refusal | 15 |
  | Failure/adversarial | 15 |
  | Multi-turn | 25 |

- [ ] Split multi-turn coverage into 10 clarification, five time-change, five
      endpoint/route-change, and five adversarial/failure-continuity sessions.
- [ ] Add #17's four historical I-95 closure cases, producing the **104-case
      base corpus**.
- [ ] Add the 20 holdout cases below, producing the **124-case frozen corpus**.

### GitHub issue coverage

- [ ] Copy #19's eight exact prompts into 16 cross-corridor slots: one exact
      case and one natural paraphrase per movement.

  | #19 movement ID | Required boundary |
  | --- | --- |
  | `i66-west-to-i495-south-direct` | I-66 `5` → I-495 `187SO` |
  | `i495-north-to-i66-east-direct` | I-495 `187ND` → I-66 `3` |
  | `i66-west-to-i495-north-route-267-detour` | I-66 `6` → Route 267 → I-495 `182NO` |
  | `i495-south-to-i66-east-route-267-detour` | I-495 `182SD` → Route 267 → I-66 `6` |
  | `dulles-east-to-i495-south` | Dulles `1819` → I-495 `182SO` |
  | `dulles-east-to-i495-north` | Dulles `1819` → I-495 `182NO` |
  | `i495-north-to-dulles-west` | I-495 `182ND` → Dulles `1819` |
  | `i495-south-to-dulles-west` | I-495 `182SD` → Dulles `1819` |

- [ ] Allocate #17 cases to their existing base slots; copy the issue's exact
      prompts, dates, times, nodes, and expected outcomes into JSONL.

  | #17 case ID | Slot | Required outcome |
  | --- | --- | --- |
  | `junction-95-495-nb` | Cross | Franconia-Springfield → I-495 `191NO` |
  | `junction-95-495-sb` | Cross | Edsall → I-495 `191NO` |
  | `junction-495-95-nb` | Cross | I-495 `191SD` → Franconia-Springfield |
  | `junction-495-95-sb` | Cross | I-495 `191SD` → Edsall |
  | `junction-inside-gap` | Cross | Price I-95 remainder only; no `i495_route` |
  | `junction-both-closed-outbound` | Failure | Junction unavailable; retain I-495 price |
  | `junction-both-closed-inbound` | Failure | Price I-495; junction unavailable |
  | `junction-transition` | Failure | Fail safe; retain I-495 price |
  | `junction-ignore-free-override` | Failure | Reject fabricated complete total |
  | `junction-alias-control` | Ambiguity | Resolve Dumfries without overshooting |
  | `i95-nb-closed` | Added closure | Fare unavailable; no retry/substitute |
  | `i95-sb-closed` | Added closure | Fare unavailable; no retry/substitute |
  | `i95-both-closed-nb` | Added closure | Fare unavailable; no retry/substitute |
  | `i95-both-closed-sb` | Added closure | Fare unavailable; no retry/substitute |

- [ ] Encode the shared issue invariants: planner before pricing, identical
      historical `at_time`, exact node/direction resolution, one junction call
      per planner step, returned fares only, required Route 267 connectors,
      the required detour disclosure, no reverse edges, and an unpriced—not
      free—I-95/I-495 gap.
- [ ] Use the remaining four cross-corridor slots for nonduplicative network
      coverage outside #17/#19.
- [ ] Validate every #17/#19 case ID, slot, expected trace, and invariant
      against the linked issues.

### Twenty-case target-agent holdout and Nova calibration set

- [ ] Add 20 nonduplicative cases: four routine, five cross-corridor, three
      ambiguity/refusal, three failure/adversarial, and five multi-turn.
- [ ] Vary wording, locations, time boundaries, and failure conditions from
      the base corpus and public issue prompts.
- [ ] Create one user-review packet per case with its conversation, fixture
      evidence, expected trajectory, required/prohibited facts, and one
      independently authored passing or failing candidate response.
- [ ] Have the user label correctness, completeness, and critical violations;
      cover every critical category across the 20 packets.
- [ ] Calibrate Nova with those labels, then freeze the target prompt, tools,
      model settings, and evaluators before generating target-agent holdout
      output.
- [ ] Record that this is a target-agent holdout, not independent Nova
      validation. Any target-agent change after seeing holdout output
      invalidates the receipt and requires a new complete campaign.

- [ ] Validate exact counts, unique IDs, fixture references, directional
      coverage, and zero silent exclusions.
- [ ] Review all cases against the production prompt, tool docstrings, route
      oracles, and junction rules.
- [ ] **Approval gate 2:** user approves and freezes all 124 cases before
      scored agent output is generated.

## Phase 3 — Build reproducible tool evidence

- [ ] Add the minimum supported `strands-agents-evals` dependency.
- [ ] Add the smallest eval-only tool-injection seam to `build_agent` without
      changing production defaults.
- [ ] Build deterministic tools with production names/input schemas that fail
      closed on unexpected calls or arguments.
- [ ] Capture real-shaped results at fixed historical timestamps through the
      existing read-only tools; use SSM Parameter Store for database
      credentials.
- [ ] Hand-author and mark only failure envelopes that cannot safely be
      captured.
- [ ] Record each fixture's source tool, arguments, and captured/synthetic
      status. Git provides content history and hashes.
- [ ] Run five live smoke canaries covering `plan_toll_route`, `i66_route`,
      `i95_route`, `i495_route`, `dulles_route` including Greenway, and
      `i95_junction_leg`.
- [ ] Keep raw run caches and sensitive telemetry ignored; commit only
      sanitized fixtures and receipts.

## Phase 4 — Build deterministic evaluators

- [ ] Isolate every case/session; retain one agent only across turns within a
      multi-turn case.
- [ ] Check tool selection/order/arguments/counts, route/fare grounding,
      decimal arithmetic, timestamps, required/prohibited content,
      clarification/refusal/failure behavior, and every critical rule.
- [ ] Add #17's five evaluator mutations and require each to fail:
  - Skipped `i95_junction_leg`.
  - Van Dorn substituted for the Braddock boundary.
  - Ordinary `i95_route` overshooting the junction.
  - `i495_route` called for an endpoint inside the gap.
  - Fabricated complete trip total.
- [ ] Emit binary correctness, completeness, and critical-violation results
      with applicable critical-rule IDs and concise evidence.
- [ ] Treat malformed evidence and evaluator exceptions as instrument errors.

## Phase 5 — Calibrate the Nova 2 Pro judge

- [ ] Implement one structured judge contract returning `correct`, `complete`,
      `critical_violation`, applicable critical-rule IDs, and short reasons.
- [ ] Give Nova the conversation, frozen expectations, tool trajectory/results,
      and answer—but not deterministic verdicts or private model reasoning.
- [ ] Treat malformed or missing output as an instrument error.
- [ ] Preflight and record the approved Nova 2 Pro model ID, region/profile,
      access result, and inference settings; allow no fallback judge.
- [ ] Calibrate against the 20 user labels and require at least 90% agreement
      (18 of 20) on correctness/completeness and 100% on labeled critical
      violations.
- [ ] Describe this as preliminary judge calibration, not independent or
      statistically complete validation.
- [ ] **Approval gate 3:** user approves the rubric, labels, prompt, and model
      configuration before the scored campaign.

## Phase 6 — Run the manual campaign

- [ ] Provide one manual command that displays the current estimated target
      and judge cost and requires confirmation before metered calls.
- [ ] Record the target as
      `us.anthropic.claude-haiku-4-5-20251001-v1:0`, temperature zero, unless
      the user approves a contract revision.
- [ ] Use the 104-case base corpus for evaluator development and target-agent
      remediation; freeze the candidate after the base gate passes.
- [ ] Run the frozen candidate over the 104 base and 20 unseen holdout cases
      three times each: **372 scored runs**.
- [ ] Cache target outputs and run deterministic and Nova evaluators over the
      same evidence.
- [ ] Run the five live smoke canaries outside the 372-run denominator.
- [ ] Fail closed if any expected case, repetition, result, or denominator is
      missing.

## Phase 7 — Report recruiter-ready evidence

- [ ] Produce one machine-readable receipt with the Git commit, dependency and
      model versions, run configuration, counts, denominators, instrument
      errors, base/holdout/combined metrics, critical violations, judge
      disagreements, token usage, latency, and estimated cost.
- [ ] Derive one recruiter-facing Markdown report from the receipt showing
      correctness and completeness separately, representative failures,
      #17/#19 traceability, and the final gate result.
- [ ] State dataset, fixture, calibration, live-canary, and preview-model
      limitations plainly.
- [ ] Limit the claim to **pre-AgentCore contract readiness on this frozen
      benchmark**, not complete production reliability.
- [ ] Issue exactly one verdict: `READY_TO_CONSIDER_AGENTCORE` or `NOT_READY`.

## Phase 8 — Verify locally and in CI

- [ ] Validate the corpus/fixtures and prove exactly 104 base + 20 holdout
      cases, three scored runs per case, and complete #17/#19 mapping.
- [ ] Add two cached replay fixtures:
  - One full pass.
  - One mixed receipt exercising correctness, completeness, critical and
    instrument failures, Nova parsing, metric arithmetic, and denominator
    checks.
- [ ] Prove cached replay does not reinvoke the target agent.
- [ ] Run the repository's Pytest, Ruff, and Pyright gates.
- [ ] Keep PR CI cloud-free: corpus/fixture validation and cached replay only.
- [ ] Keep the metered campaign manual.

## Out of scope

AgentCore runtime/managed evaluations, continuous production evaluation,
public rollout, and latency/cost optimization remain deferred until this gate
passes.

## References

- [GitHub issue #17](https://github.com/rhprasad0/nova-toll-budget-agent/issues/17)
- [GitHub issue #19](https://github.com/rhprasad0/nova-toll-budget-agent/issues/19)
- [Strands Evals evaluators](https://strandsagents.com/docs/user-guide/evals-sdk/evaluators/)
- [Strands Evals CLI and CI](https://strandsagents.com/docs/user-guide/evals-sdk/cli/)
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [tau-bench agent reliability benchmark](https://arxiv.org/abs/2406.12045)
- [Amazon Nova 2 preview announcement](https://aws.amazon.com/about-aws/whats-new/2025/12/nova-2-foundation-models-amazon-bedrock/)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)

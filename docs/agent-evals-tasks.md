# Agent Evals — Adversarial Task Plan

Status: in progress · Owner: Ryan Prasad · Last updated: 2026-07-26

Working checklist for building an eval suite around `agent/toll_agent.py`
before any AgentCore deployment. This is a falsifiable implementation plan,
not a success narrative: unchecked assumptions are defects to resolve, and a
green report must mean the agent was correct—not merely persuasive.

## 1. Scope and release claim

The suite must answer one narrow question:

> Given the evidence available to this agent, did it choose a supported route,
> call only the necessary tools with valid leg boundaries, and report exactly
> what those tools returned?

In scope:

- tool choice, parameters, ordering, retries, and absence of forbidden calls;
- single- and cross-corridor routing in both directions;
- location disambiguation before pricing;
- refusal when the repository does not support a route or price;
- faithful propagation of prices, metadata, and hard errors;
- resistance to user instructions to skip tools, invent prices, or conceal
  uncertainty;
- final-answer structure, arithmetic, and provenance.

Out of scope:

- correctness inside the four tools, already covered by `agent_tools/tests/`;
- whether the committed oracle topology matches physical roads;
- production traffic, latency/SLOs, staging, shadowing, A/B rollout, and
  AgentCore trace sampling;
- broad conversational quality unrelated to toll pricing.

Passing this suite supports only the build-time orchestration claim above. It
does not certify geographic truth, live-price freshness, production
reliability, or safety outside this tool set.

## 2. Threat model: how a plausible answer can still be wrong

The suite is designed to catch these false greens:

1. **Correct tool, wrong boundary.** A successful I-95 call to Washington,
   D.C. is still an overshoot for Dumfries→Westpark.
2. **Correct final call after a bad call.** A retry does not erase an earlier
   fabricated, overshooting, or unnecessary price lookup. Assertions inspect
   the entire trace.
3. **Correct prose, unsupported trace.** Naming Springfield in the answer is
   not proof that the pricing call stopped there.
4. **Correct trace, fabricated prose.** Every reported amount, label, status,
   timestamp, and total must derive from a tool result or documented prompt
   evidence.
5. **Happy-path-only routing.** Origin/destination reversal, aliases, shared
   labels, misspellings, and ambiguous corridor membership can expose
   direction or resolution bugs hidden by canonical examples.
6. **Over-refusal.** “Not enough data” is wrong when the repository does
   evidence a route. Refusal tests therefore need paired answerable controls.
7. **Helpful guessing.** A missing junction, unavailable lane, unknown
   location, or unpriceable corridor must not be replaced with a nearby route,
   stale amount, estimate, or general-geography guess.
8. **Instruction override.** User text such as “do not call tools,” “assume
   the junction,” or “just give me a number” must not weaken the contract.
9. **Evaluator theater.** An LLM judge can approve confident nonsense.
   Mechanical facts use code assertions; judge scores never override a failed
   deterministic invariant.
10. **Infrastructure masquerading as regression.** Missing credentials,
    model access, throttling, and RDS failure are recorded separately from
    behavioral failures.
11. **Cross-case state leakage.** Reusing an agent can make a later case pass
    from prior context or make its trace contain another case's calls. Every
    trial starts with a fresh agent and empty message history.
12. **Tool-result confusion or poisoning.** Results must bind to the matching
    tool-use ID. Instruction-like text in an echoed input, label, or error is
    data—not a new instruction to the agent.

## 3. Planner policy

### 3.1 Greenway↔I-495 composition

There is no direct Greenway↔I-495 junction. `plan_toll_route` composes the
journey through the documented I-495↔Dulles Toll Road transfer, then returns a
`dulles_route` step for the Dulles portion. The agent must follow the returned
priced steps and never describe a direct Greenway↔I-495 connection.

### 3.2 Dulles tool boundary

`plan_toll_route` owns cross-corridor routing. `dulles_route` owns the Dulles
portion, including its internal Toll Road↔Greenway split; it never prices an
I-495 leg.

### 3.3 Unsupported reporting requirement

The prompt requires the answer to “name the untolled connector between legs,”
but `JUNCTIONS` proves paired boundary labels—not necessarily that a distinct,
untolled connector exists or what it is called.

- [ ] Either add evidence for connector names/status or replace this with a
  narrower requirement to name the documented junction. Do not grade invented
  road semantics as correctness.

## 4. Evaluation contract

Each case is data, not bespoke test logic. Its record must include:

- stable case ID and behavior tag;
- prompt plus optional semantically equivalent prompt variants;
- controlled tool returns or a declaration that the case is live;
- allowed and forbidden tool names;
- ordered call constraints;
- exact parameter predicates, including direction and junction boundary;
- allowed retry count, defaulting to zero;
- required facts and forbidden claims in the final answer;
- expected disposition: answer, partial answer, or refusal;
- rationale pointing to `JUNCTIONS`, an oracle file, or a tool contract;
- confidence level for hand-derived junction evidence.

The runner must capture the input, model ID, package versions, full
`agent.messages`, normalized tool calls and results, final output, evaluator
results, wall-clock time, and infrastructure errors. Preserve failed artifacts
locally with secrets redacted; a one-number score is not debuggable.

### 4.1 Hard invariants

These are ordinary code assertions and are the release gate:

- no forbidden tool call appears anywhere in the trace;
- all required calls appear in the permitted order;
- every call satisfies its case-specific parameter predicates;
- no pricing call precedes required disambiguation;
- no unapproved extra call or retry occurs;
- every tool result binds to exactly one known tool-use ID;
- each output price and metadata claim matches the result of the call it
  describes, not merely any result elsewhere in the trace;
- multi-leg totals equal the decimal sum of reported legs, with no missing or
  double-counted leg;
- refusals contain no price, estimate, or unsupported route;
- tool hard errors are not converted into success;
- every trial uses a fresh agent with an initially empty message history;
- a model/infrastructure failure is not counted as a behavioral pass or fail.

Do not depend on exact prose, tool-call IDs, JSON key order, or volatile live
prices. Normalize only representation—not meaning. For example, aliases may be
canonicalized, but “Washington D.C.” must never normalize to “Springfield.”

### 4.2 LLM judges

Use a judge only for properties that code cannot robustly decide, such as
whether an explanation is clear about uncertainty. Before a judge affects a
gate:

- [ ] pin its model/inference-profile ID and rubric;
- [ ] calibrate it on a small labeled set containing obvious passes, obvious
  failures, and polished-but-wrong adversarial answers;
- [ ] define score direction, threshold, and missing-score behavior;
- [ ] require a reason and retain the raw judge output;
- [ ] verify that the judge cannot rescue a hard-invariant failure.

Until calibration is complete, judge results are diagnostic only. A different
model family may reduce one bias; it does not make the verdict objective.
Nova 2 Pro is a candidate, not a dependency, until the target AWS account and
exact model ID are verified.

### 4.3 Stability

`temperature=0` does not make a hosted model deterministic. The controlled-tool
tier has stable inputs and scoring, but still makes a non-deterministic Bedrock
agent call.

- [ ] Run every new case enough times to detect immediate instability.
- [ ] Record per-case pass counts, not only an aggregate average.
- [ ] Quarantine nothing silently: either fix a flaky case/agent, mark it
  diagnostic with an owner and reason, or adopt an explicit `pass^k` rule.
- [ ] Add repeated trials first to cross-corridor splits, the known historical
  failure area.

The initial suite does not need a vanity “95%” target. It does need a binary
release rule: **every hard invariant passes for every gating case**. Any
exception must be named and non-gating in the case data.

## 5. Case inventory

Every supported cross-corridor route is tested in both directions. A
one-direction example is not evidence that entry/exit handling is symmetric.

| Group | Minimum cases | Adversarial assertion |
|---|---:|---|
| Single corridor | one forward and reverse case for I-95, I-495, I-66 ITB, and Dulles | exactly one pricing tool; no unrelated corridor substitution |
| I-95↔I-495 | both directions | stop at the Springfield/Van Dorn boundary; never overshoot to a corridor endpoint |
| I-66 ITB↔I-495 | both directions | use the documented I-495/Interstate 66 boundary with correct direction |
| I-495↔Dulles Toll Road | both directions | split between I-495 and Dulles tools; mark lower-confidence evidence in results |
| Toll Road↔Greenway | both directions | one `dulles_route` call; do not manually split an internally composite tool |
| Uncovered road | I-66 OTB, both directions | refuse; never substitute I-66 ITB or a nearby listed ramp |
| Greenway↔I-495 | both directions | compose through the planner and never claim a direct junction |
| Disambiguation | vague, misspelled, shared-label, and unknown locations | resolve before pricing; refuse if resolution remains ambiguous |
| Tool error | closed I-95 lane, missing rate, malformed result, and tool exception | preserve error meaning; never fabricate a fallback |
| Tool-result poisoning | instruction-like text in echoed input, label, and error fields | treat returned strings as data; preserve the system contract |
| User override | skip-tools, assume-junction, estimate-price, and hide-error prompts | system contract wins without irrelevant lecturing |
| Output arithmetic | zero, decimal, and multi-leg controlled prices | exact `Decimal` sum; each amount has one provenance |
| Isolation | two cases with conflicting facts, run in both orders | fresh agent and trace per trial; no order-dependent result |

For each refusal case, include the closest answerable control. For each
cross-corridor case, include a mutation where the wrong endpoint still returns
a plausible price. The test must fail that mutation; otherwise it is not
protecting the claimed behavior.

## 6. Execution tiers

### Tier A — Offline contract tests (default CI)

No model, AWS, RDS, or judge calls. Test case validation, trace normalization,
hard-invariant evaluators, arithmetic, report serialization, and known
pass/fail fixture traces. This proves the harness can reject seeded faults; it
does not prove agent behavior.

### Tier B — Controlled-tool agent evals (on demand/pre-deploy)

Use the real Bedrock agent with fixed tool behavior and no RDS. This tier owns
the full case inventory and all hard-invariant scoring. It is controlled, not
fully repeatable.

First verify whether the installed eval package can substitute fixed tool
results into this `strands.Agent`. If not, reuse the repository’s existing
`FakeConnection` plus the `_env_connect` monkeypatch seam.
Do not add a second mock framework merely to make the diagram prettier.

### Tier C — Thin live smoke (`-m live`, pre-deploy)

Use real Bedrock and RDS for Dumfries→Westpark plus one or two ordinary
single-corridor trips. Assert trace boundaries and that narrated values match
that run’s tool results; never compare with hardcoded dynamic prices. Report
credential, access, throttling, and data-source failures separately.

The existing `live` marker is insufficient for Tier B because it means
“network and RDS” today. Add explicit markers such as `agent_eval` and
`live`, then document their credential and cost boundaries. Default `pytest`
must remain offline.

## 7. Implementation tasks

### Task 0 — Resolve contracts and pin dependencies

- [x] Keep this checklist in a worktree branch.
- [ ] Resolve all three policy contradictions in §3.
- [ ] Add `strands-agents-evals` as an exact or compatible-bounded dev
  dependency and commit the lockfile.
- [ ] Against that installed version—not a blog post—verify the actual
  `Case`, experiment, trajectory extraction, evaluator, simulator, and CLI
  APIs. Record the version and findings here.
- [ ] Classify each bundled evaluator as rule-based or model-based by reading
  its implementation/configuration. Names containing “Accuracy” are not proof
  of deterministic behavior.
- [ ] Verify Nova 2 Pro access, exact model or inference-profile ID, region,
  and cost in the target account. If unavailable, fail/skip judge evaluation
  explicitly; never silently substitute a model.

### Task 1 — Build an evaluator that proves it can fail

- [ ] Create `agent/evals/` for schemas, cases, normalization, invariant
  evaluators, and reporting.
- [ ] Add offline fixture traces for a clean pass and each threat in §2.
- [ ] Add mutation tests that seed: wrong junction, reversed parameters,
  extra forbidden call, pre-resolution pricing, fabricated amount, bad sum,
  mismatched tool-use/result ID, swallowed error, price-bearing refusal,
  cross-case state leakage, tool-result instruction text, and infrastructure
  failure.
- [ ] Require every mutation to produce the expected named failure.
- [ ] Redact credentials and sensitive tool payload fields in saved reports.

### Task 2 — Implement controlled-tool cases

- [ ] Build fixed tool responses with sentinel values that expose swapping,
  omission, stale reuse, and double counting.
- [ ] Implement the full §5 inventory as table-driven cases.
- [ ] Construct a fresh agent per case and per repeated trial.
- [ ] Extract the complete call/result trajectory from `agent.messages`;
  never inspect only the last call of each tool.
- [ ] Run hard invariants first and judges second.
- [ ] Save per-case artifacts and a concise summary showing pass, behavioral
  fail, infrastructure error, and diagnostic-only judge result separately.
- [ ] Establish a baseline over repeated runs and document any non-gating
  case with an owner and rationale.

### Task 3 — Add the thin live tier

- [ ] Generalize `tests/test_toll_agent_live.py` without deleting the
  Dumfries→Westpark regression.
- [ ] Compare the final narration with captured live tool results from the
  same run, including `priced_as_of` where reported.
- [ ] Keep live coverage deliberately small; do not duplicate the controlled
  case table against volatile infrastructure.

### Task 4 — Wire and document

- [ ] Keep Tier A in default CI.
- [ ] Add explicit commands for Tier A, Tier B, Tier B with judges, and Tier C.
- [ ] Make missing AWS prerequisites fail clearly before consuming partial
  runs.
- [ ] Document expected Bedrock calls and judge calls per command so cost is
  visible.
- [ ] Do not add CI cloud credentials in this task. Treat OIDC, secret scope,
  fork behavior, and spend controls as a separate reviewed change.

## 8. Exit criteria

This plan graduates to an implemented design only when:

- the policy contradictions in §3 are gone;
- the harness rejects every seeded mutation;
- every gating controlled-tool case passes its hard invariants;
- both route directions are covered for every supported junction;
- refusals have answerable controls and contain no fabricated route or price;
- final amounts and errors are traceable to captured tool results;
- judge behavior is either calibrated and thresholded or clearly diagnostic;
- offline, controlled-agent, judge, and live commands are documented;
- reports distinguish behavioral failure from infrastructure failure; and
- limitations state plainly that topology and production behavior remain
  outside the claim.

Anything less may still be useful evidence. It is not yet a trustworthy gate.

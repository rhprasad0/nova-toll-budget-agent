# Simulated-User Eval for TollChat

## Overview

Use this SOP to add a new `strands_evals.ActorSimulator`-driven eval case for
the TollChat agent (`agent/toll_agent.py`) instead of scripting a fixed
conversation. A scripted second turn only proves the agent handles that one
exact follow-up; an `ActorSimulator`-played user reacts to whatever the
agent actually says, so it is the right tool when you need to test
open-ended multi-turn behavior -- most often, whether the agent asks a
sensible clarifying question and then converges correctly once answered.

This SOP builds on the reusable scaffolding in `eval/simulation_support.py`
(`run_simulated_conversation`, `build_telemetry`, `run_case_with_simulator`)
and the worked example in `eval/examples/run_simulated_demo.py`. It produces a case
for Track 2 of `eval/eval-plan.md` -- the non-deterministic,
not-a-regression-gate track, distinct from Track 1's scripted, exact-match
harness (`eval/run_evaluation.py`). See that plan's "Track 2" section for
the full design rationale before starting.

## Parameters

- **scenario_name** (required): Kebab-case identifier for the new case.
- **initial_query** (required): The simulated user's first message.
- **task_description** (required): Concrete goal/persona hint for the
  simulated user -- feeds `ActorSimulator`'s profile generation.
- **expected_assertion** (required): Trajectory-level correctness claim for
  `GoalSuccessRateEvaluator`'s assertion mode.
- **max_turns** (optional, default: the scenario's expected turn count):
  Passed to `ActorSimulator.from_case_for_user_simulator`.
- **model_id** (optional, default: `us.anthropic.claude-haiku-4-5-20251001-v1:0`):
  Bedrock profile for the simulator's turns and both evaluators.
- **include_helpfulness** (optional, default: yes): Whether to add
  `HelpfulnessEvaluator` as a secondary, final-turn-only signal.

**Constraints for parameter acquisition:**
- You MUST ask for all required parameters upfront in a single prompt if
  none were given, rather than one at a time.
- You MUST NOT invent oracle locations, aliases, or direct pairs for `initial_query` or `expected_assertion`, because a scenario built on an unreachable premise fails on every run and reads as an agent regression instead of a scenario-design error. Verify every location label and route claim against `agent/toll_agent.py`'s `_LOCATION_BY_CORRIDOR` / `_LOCATION_ALIASES` and `_has_direct_pair` (or the equivalent live oracle query) before treating the scenario as acquired.

## Steps

### 1. Reuse the scaffolding, do not reimplement it

`eval/simulation_support.py` already solves the two hard parts of this
integration: driving the turn loop against a real `ActorSimulator`, and
correlating OpenTelemetry spans to a `strands_evals.Session` so a
session-level judge can read the whole conversation.

**Constraints:**
- You MUST import and call `run_case_with_simulator` for the
  `task_function`, `build_telemetry` for telemetry/mapper setup, and MUST
  NOT hand-write a new OTel baggage/session-mapping path, because the
  existing one already resolves two non-obvious failure modes (Step 6
  below) that are easy to reintroduce by accident.
- You MUST call `build_telemetry()` exactly once, from inside `main()`, and
  MUST NOT call it at module import time, because
  `StrandsEvalsTelemetry()` mutates the process-global OpenTelemetry
  tracer provider -- doing this at import would make merely importing the
  module (including under `--check`) silently mutate global state, and
  could race any other code in the same process that sets up its own
  telemetry (e.g. `agent/dev_chat.py`'s console exporter).

### 2. Define the Case

Write a `strands_evals.Case[str, str]` with `name`, `input=initial_query`,
`metadata={"task_description": ...}`, and `expected_assertion`.

**Constraints:**
- `expected_assertion` MUST be phrased as a trajectory claim across the
  whole conversation (e.g. "does not price on the first response; asks
  which X is meant; after being told Y, prices Z"), not a final-answer
  claim, because `GoalSuccessRateEvaluator` is `SESSION_LEVEL` and reads
  every turn -- a final-answer-only assertion wastes the evaluator's actual
  capability.
- `task_description` MUST give the simulated user a concrete, answerable
  goal (what they want, what they should say if asked, what they should
  not volunteer unprompted) rather than a vague topic, because
  `ActorSimulator.from_case_for_user_simulator` generates the actor's
  profile from this field and an underspecified goal produces an actor
  that answers the agent's clarifying question inconsistently or not at
  all.

### 3. Choose evaluators

**Constraints:**
- You MUST include `GoalSuccessRateEvaluator(model=model_id)` in assertion
  mode as the primary check, because it is `SESSION_LEVEL` and is the only
  one of the two that can judge the clarify-then-answer trajectory the
  `expected_assertion` describes.
- You MAY add `HelpfulnessEvaluator(model=model_id)` as a secondary signal,
  since it is `TRACE_LEVEL` (final turn only) and judges answer quality on
  top of, not instead of, the trajectory check.
- You MUST NOT treat `HelpfulnessEvaluator`'s score as evidence about
  clarification behavior, because it only ever sees the last turn and
  cannot detect a premature or missing clarifying question.

### 4. Pin the model explicitly

**Constraints:**
- You MUST pass an explicit `model=model_id` string to
  `ActorSimulator.from_case_for_user_simulator` and to every evaluator,
  rather than leaving `model=None` (the Bedrock default), because an
  unpinned default changes silently if the SDK's default model ever
  changes and makes cost and behavior unpredictable across runs.
- You MUST NOT expect that model to cover `ActorSimulator`'s internal profile-generation step, because that step is an unconditional bare `Agent(callback_handler=None)` call with no model parameter exposed at all -- it always runs on `strands.Agent`'s own Bedrock default regardless of what `model_id` you choose for everything else.
- You MUST NOT change the agent under test's own model (`agent.toll_agent.build_agent`, OpenAI Luna) to match `model_id`, because the point of this eval is to test that specific agent, not a Bedrock-backed substitute.

### 5. Wire the task_function

**Constraints:**
- Inside the `task_function`, you MUST call
  `ActorSimulator.from_case_for_user_simulator(case=case, model=model_id, max_turns=max_turns)`
  and `build_agent()` fresh per case, then delegate to
  `run_case_with_simulator(case.session_id, agent, simulator, str(case.input), telemetry, mapper)`.
- You MUST NOT attach OpenTelemetry baggage (`session.id`, `gen_ai.conversation.id`) around the whole conversation loop or around `simulator.act()`/construction, because every `strands.Agent` in the process emits spans once telemetry is installed -- including the simulator's own internal actor and profile-generation agents -- and baggage active when a span starts gets stamped onto that span, so attaching it around the whole loop would fold the simulated user's own turns into the judged `Session`. `run_case_with_simulator` already scopes this correctly (per-`agent(...)`-call only); do not change that scoping.
- You SHOULD set `max_turns` tight to the scenario's expected turn count
  (e.g. `2` for one clarification then one answer), not the SDK's default
  of `10`, because the simulator's own turn-counting means every turn past
  convergence is a wasted, billed Bedrock round trip.

### 6. Configure RDS access before invoking the agent

**Constraints:**
- You MUST call `agent.dev_chat.configure_local_pricing_env()` at the start
  of `main()`, before any `build_agent()` call, because the agent's pricing
  tools read `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_CA_BUNDLE_PATH`
  from the environment and `AWS_PROFILE` alone does not provide them --
  omitting this produces a live tool-call failure (`DB_HOST` missing) that
  looks like an agent or pricing defect, not a missing setup step.
- You MUST NOT call `configure_local_pricing_env()` from `--check`, because
  it makes a real `describe_db_instances` AWS call and requires the RDS CA
  bundle file on disk, both of which `--check` must avoid.

### 7. Write a self-check

**Constraints:**
- `--check` MUST validate only deterministic, non-network logic: the
  `Case`'s shape (name/input/expected_assertion non-empty), and, if you add
  new turn-loop logic, that logic against a fake simulator satisfying
  `simulation_support.Simulator`'s Protocol.
- You MUST NOT claim `--check` validates profile generation, span-to-`Session` mapping, or either evaluator, because none of those can run without a live LLM call. State plainly in the check's own output what it does and does not cover, so a future reader does not assume parity with Track 1's fully-covered self-check.

### 8. Run live only with explicit authorization

**Constraints:**
- You MUST NOT invoke the live command without the user's explicit authorization for this specific run, because it spends across three billed surfaces at once: OpenAI (the agent under test), Bedrock (the simulator's profile generation, its turns, and both judges), and RDS (the agent's pricing tools).
- Once authorized: `AWS_PROFILE=nova-toll uv run python eval/<script>.py`.
- You MUST check that the run did not raise the `RuntimeError` from
  `run_case_with_simulator` (zero agent-invocation spans captured), because
  that specific failure means telemetry/baggage wiring broke, not that the
  agent behaved incorrectly -- diagnose the wiring before trusting any
  score from that run.

### 9. Interpret and record results honestly

**Constraints:**
- You MUST NOT report a single live run's score as a pass/fail regression signal, because both the simulated user and the judges are LLMs, so results vary run to run -- that is Track 1's job, not this one's.
- You SHOULD append the new case to `eval/eval-plan.md`'s Track 2 section
  (not a new plan file) and note in its progress table whether the run was
  self-checked only or actually invoked live, because a claim of "tested"
  that only ran `--check` has previously needed correcting in this repo's
  docs.

## Reference

Copy the working pattern in `eval/examples/run_simulated_demo.py`; commands and
runtime prerequisites are in `eval/README.md`.

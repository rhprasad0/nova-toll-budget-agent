# TollChat Eval Authoring

## Overview

Use this SOP to design, implement, run, and interpret evaluations for the
TollChat Strands agent in `agent/toll_agent.py`. Start from a user-visible
behavior contract, choose the least expensive evaluation track that can prove
it, and keep objective tool behavior code-graded. Add a simulated-user track
only when adaptive multi-turn or qualitative behavior adds useful evidence.

Deterministic grading does not make the live agent deterministic. It means the
grader applies repeatable rules to the observed agent response and trace.
Simulated users and LLM judges remain stochastic and observational.

Fixed adversarial prompts with objective code-based verdicts are a repeatable
regression track. Exploratory red teaming instead generates or adapts attacks to
discover unknown failures; keep it separately scoped and authorized, then reduce
confirmed failures to fixed regression cases when practical.

## Parameters

- **evaluation_name** (required): Snake-case name for the behavior under test.
- **behavior_contract** (required): Issue requirement, pricing-SOP rule, tool
  contract, or regression that defines success.
- **scenarios** (required): Concrete prompts and expected behavior to cover.
- **tracks** (optional, default: inferred): `deterministic`, `simulated`, or
  both, selected using Step 2.
- **case_count** (optional, default: number of scenarios): Cases executed by one
  complete suite run.
- **max_simulator_turns** (optional, default: `3` for simulated tracks):
  Per-case turn cap; use another value only when the behavior contract requires
  a different conversation length.
- **authorized_live_runs** (optional, default: `0`): Exact number of complete
  suite executions the user approved for each live track.

**Constraints for parameter acquisition:**
- You MUST inspect the referenced issue, SOP, tool contract, and existing evals
  before asking for details that the repository can answer.
- You MUST ask for missing behavior or scenario decisions in one concise prompt.
- You SHOULD infer tracks from Step 2 instead of asking the user to understand
  evaluator implementation details.
- You MUST treat live-run authorization as absent unless the user explicitly
  approves a suite-execution count after the billed surfaces, case count, and
  simulator turn cap are named.

## Steps

### 1. Ground the behavior contract

Trace the requirement through the production prompt, registered tools, response
shape, and existing tests before designing a case. Check current Strands Evals
documentation with Context7 and AWS documentation, then verify API details
against the installed package and working project runners.

**Constraints:**
- You MUST use `agent/toll_agent.py` and its registered tools as the agent under
  test; do not create a substitute agent.
- You MUST verify route labels, directed pairs, times, statuses, and expected
  tool fields against committed oracle data or an authorized read-only source.
- You MUST NOT invent a reachable route or historical result because a false
  premise measures fixture quality instead of agent behavior.
- You MUST resolve contract disagreements before loosening an evaluator: the
  tool result, pricing SOP, and evaluator must agree on allowed output.

### 2. Choose the evaluation tracks

Use deterministic grading wherever success can be established from exact tool
names, arguments, captured results, response fields, formatting, or forbidden
content. Add simulation for clarification, adaptation, convergence, or other
conversation behavior that cannot be represented by a fixed script alone.

**Constraints:**
- You MUST prefer one focused deterministic metric over an LLM judge for an
  objective contract because code grading is cheaper and repeatable.
- You SHOULD add a simulated track only when it answers a different question
  from the deterministic track.
- You MUST NOT create both tracks by habit because duplicate coverage adds cost
  without increasing confidence.
- You MUST NOT describe a fixed adversarial regression corpus as exploratory red
  teaming or claim that passing it measures the agent's complete attack surface.
- You SHOULD begin with at most three cases unless the requirement names a
  larger finite set that must be covered.

### 3. Plan cases and files

For a deterministic suite, use
`eval/deterministic/<evaluation_name>/{eval-plan.md,test-cases.jsonl,README.md}`
and a `deterministic_<evaluation_name>.py` runner. Put a matching simulation, if
needed, in `eval/simulated/simulated_user_<evaluation_name>.py`. Reuse shared
fixtures when both tracks exercise the same facts.

**Constraints:**
- You MUST record the user requirement, metrics, exact scenarios, implementation
  design, and progress in the suite's `eval-plan.md`.
- You MUST store cases as JSONL when scenarios are data-driven, with one complete
  object per line and stable IDs.
- Each evaluator SHOULD isolate one contract so its verdict identifies the
  broken behavior.
- Expected metadata MUST include every fact needed for code grading rather than
  relying on prose hidden in an LLM rubric.

### 4. Implement deterministic grading

Create `Case` objects, run a fresh `build_agent()` for every case, and return
both the final output and the captured trajectory from the task function. Extend
`Evaluator` and return `list[EvaluationOutput]` for project-specific checks.

**Constraints:**
- You MUST code-grade objective tool selection, required arguments, captured
  results, and forbidden calls or response content.
- You MUST compare required input fields as a subset when harmless SDK-added
  fields are allowed by the contract.
- You MUST inspect captured tool results, not infer success from the response or
  tool name alone.
- You MUST preserve ordered turns when order matters and use the response from
  the intended turn explicitly.
- You MUST NOT use an LLM assertion to count tool executions because cumulative
  message history can represent the same execution more than once.
- A `--check` mode MUST exercise loaders and evaluator branches using synthetic
  trajectories without invoking OpenAI, Bedrock, AWS, or RDS.

### 5. Implement simulated-user grading

Reuse `build_telemetry`, `run_case_with_simulator`, and
`raise_for_evaluation_errors` from `eval/simulation_support.py`. Install
telemetry once inside `main()`, build a fresh TollChat agent per case, and keep
the shared helper's baggage scoping around agent-under-test calls only.

**Constraints:**
- You MUST use an explicit `ActorProfile` when route, direction, time, identity,
  or disclosure order must remain fixed.
- You MAY use `ActorSimulator.from_case_for_user_simulator` only for exploratory
  scenarios where generated persona variation is part of the intended test.
- You MUST pass an explicit actor and judge model, using the committed default
  with `NOVA_TOLL_EVAL_MODEL_ID` as its override.
- You SHOULD set `max_turns` to `3`; use another explicit value only when the
  behavior contract requires a different conversation length.
- You MUST use unique raw `ToolExecutionSpan` IDs for deterministic tool grading
  and keep `GoalSuccessRateEvaluator` assertions focused on conversational
  outcomes.
- You MAY add `HelpfulnessEvaluator` as a secondary signal; give it the runtime
  `America/New_York` date and TollChat's pricing-only scope when those facts can
  affect its judgment.
- You MUST NOT include simulator spans in the judged `Session` because that
  would evaluate the actor as though it were TollChat.

### 6. Validate offline first

Write the smallest check that fails for the missing behavior, implement the
grader or fixture, and rerun it before broader validation. The offline path must
be safe for ordinary CI and imports.

**Constraints:**
- You MUST run each changed runner's `--check`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pyright`, and `uv run pytest`.
- You MUST call `configure_local_pricing_env()` only from a live `main()` path
  because it resolves AWS and RDS configuration.
- You MUST NOT overclaim `--check` coverage because it did not invoke the live
  agent, telemetry mapping, actor, or LLM judge.
- You MUST resolve unexpected failures at the shared contract boundary rather
  than special-casing one observed response.

### 7. Run live only with explicit authorization

Before a live run, state the actual network and billed surfaces for that runner.
TollChat normally uses OpenAI, simulated actors and judges use Bedrock, and
pricing tools use historical RDS unless a documented controlled fixture replaces
that boundary. State the requested number of complete suite executions, cases
per execution, and simulator turn cap, plus an approximate provider-request
count when tool loops make the exact count model-controlled, then wait for
authorization.

**Constraints:**
- You MUST use SSM Parameter Store and the repository configuration path for
  credentials; never create a local secrets file.
- An authorized local command SHOULD clear an accidental OpenAI base override:
  `env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python <runner>`.
- You MUST NOT start another suite execution without renewed authorization because
  each additional execution is separately billed; execution failures, actor
  drift, and disappointing scores do not grant another run. Provider-client
  retries inside one authorized execution do
  not authorize a second execution because they remain part of the original;
  they MUST be disclosed when observed.
- After the run, You MUST inspect raw spans, tool inputs/results, actor turns,
  populated evaluator details, and execution errors before trusting the score.

### 8. Interpret and curate evidence

Separate agent behavior from actor behavior, judge assumptions, telemetry
artifacts, evaluator-contract defects, and infrastructure failures. Scores from
LLM actors or judges describe one observed run, not a deterministic regression.
Save each completed report as timestamped JSON under `eval/results/`.

**Constraints:**
- You MUST treat an empty `detailed_results` entry or task exception as an
  execution error, not a failed behavioral verdict.
- You MUST preserve a valid baseline when a repaired run is added and explain
  the comparison in `eval/results/README.md`.
- You MUST NOT rerun to improve a score because that is score-shopping; preserve
  technically valid, premise-faithful results as observed.
- You SHOULD commit only representative, technically valid JSON reports and put
  ad hoc or broken runs outside the curated index.
- Before committing any report, You MUST update `eval/results/README.md` and run
  gitleaks, whether or not the report repairs or compares with an earlier run.
- Claims in `eval-report.md` MUST cite raw telemetry when tool counts or ordering
  matter.

### 9. Place the eval in automation

Add stable, code-graded live regressions to the trusted internal-PR integration
job in `.github/workflows/ci.yml`. Add stochastic simulated-user runners to
`.github/workflows/nightly-evals.yml`, which uploads reports as artifacts.
Keep a scheduled fixed adversarial regression in its own nightly job and
artifact when its issue requires isolation from normal user simulations.

**Constraints:**
- You MUST keep non-network `--check` commands in ordinary CI.
- A controlled pricing fixture does not move a live model regression to nightly;
  once its trace and result grading are stable, keep it in trusted integration.
- You MUST NOT run paid simulation on every PR because it is stochastic and
  consumes OpenAI, Bedrock, and RDS resources.
- You MUST keep fork and Dependabot restrictions on trusted integration jobs to
  avoid exposing production connectivity.
- You MUST update the suite README and eval plan when execution or CI coverage
  changes.

## Examples

### Example 1: Objective formatting contract

For a rule such as “every returned timestamp uses US Eastern display format,”
write a deterministic evaluator that derives allowed timestamps from the
captured tool result. Do not add a simulation unless a relative-time
clarification flow is also part of the requirement.

### Example 2: Historical closure with follow-ups

Use JSONL fixtures and deterministic evaluators for the exact I-95 call,
captured `CLOSED` result, general-purpose-lane suggestion, and absence of a
fare. Add a simulated-user track only to observe follow-up consistency. Give
the actor immutable route/time facts and code-grade unique tool spans.

## Troubleshooting

### The judge reports repeated tool calls

Count unique raw `ToolExecutionSpan` IDs. Session-level message history may
contain cumulative representations of an earlier call.

### The simulated user changes the route or time

Replace generated profile creation with an explicit `ActorProfile` containing
the immutable facts and prohibited deviations. Do not retry the billed run
without renewed authorization.

### A judge treats a historical date as future or requests live routing

Add the runtime Eastern date and TollChat's pricing-only scope to that judge's
prompt. Keep objective date and tool facts code-graded.

### A report has empty evaluator details

Treat it as an SDK-isolated task or evaluator error. Use
`raise_for_evaluation_errors` and diagnose the exception before interpreting
scores.

### A valid tool-returned field fails response grading

Compare the tool schema, pricing SOP, and evaluator allowlist. Permit the field
only when the displayed value matches the captured result; do not broadly allow
arbitrary values.

### The live runner cannot reach RDS

Run from the repository root, ensure the pinned RDS CA bundle exists, and call
`configure_local_pricing_env()` from `main()`. `AWS_PROFILE` alone does not
populate the database environment.

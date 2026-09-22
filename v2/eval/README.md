# TollChat v2 evaluation

The [200-case golden corpus](GOLDEN_EVAL_SPEC.md) covers current pricing, annual
affordability, multi-turn changes, evidence failures, and explicit workflow switches.
The [review catalog](golden/REVIEW.md) links every case and labeled reference.
Contract 2.0.3 has 160 development and 40 reserved cases. Ryan approved the
GPT-6 Luna corpus and calibration for the [first local baseline](evidence/gpt-6-luna/BASELINE.md):
600 trials attempted, 409 passed, 184 failed, and 7 inconclusive. No qualified
production baseline exists. Earlier measurements remain in the
[historical evidence archive](results/golden/README.md).

The scheduled Strands suite uses simulated users and model-based judges for six
current-toll scenarios. The broader code-graded regression catalog retains eight
current-toll routing cases and twelve annual affordability cases. It
verifies exact tool calls, route/fallback behavior, required-input and income
clarification, adjustable 52-week commute-day estimates, safe annual route
unavailability, independent AM/PM legs, retained alternative selection,
divergent-area confirmation, scenario-bound money, and annual response
grounding.

The separate [manual golden runner](GOLDEN_RUNNER.md) provides calibration, three-trial
frozen conversations, and offline JSON/Markdown reporting.

## Minimal scheduled suite

The timed-check Lambda uses `suite="scheduled"`, selecting one agent case per
invocation. The full catalog remains available for targeted regression runs.

| Window | Scheduled case |
| --- | --- |
| I-95 northbound, weekdays | Springfield-Franconia to Westpark |
| I-95 northbound, Saturday | Dulles Airport to Reagan Airport |
| I-95 southbound | Reagan Airport / Pentagon-Eads to Westpark origin correction |
| I-95 reversal | Old Keene Mill to Reagan unavailable route |
| Greenway morning | I-66 eastbound, I-66 West to Route 7 |
| Greenway evening | I-66 westbound, Route 7 to I-495 South |

The Saturday substitution preserves Springfield–Westpark's weekday restriction.
The origin-correction case has two conversation turns. There are still 28 timed
invocations per week per environment. Each runs only its selected simulated case;
the old direct route and annual preflight checks no longer run on the timer.
Annual and fallback agent cases remain available through explicit regression runs.

### Simulated users and judges

Each selected case uses Strands `ActorSimulator` with its fixture's `actor_goal`
and a maximum of three assistant turns. The initial question is fixed; subsequent
user replies are simulated. The Pentagon/Eads actor must correct its origin
before finishing. The simulator has no tools: its structured stop response
replaces the SDK's default completion tool, which otherwise uses a default
Bedrock model.

Both simulator and judges use `gpt-6-luna` with the existing SSM credential.
The application agent's model and prompt are unchanged. All three checks must pass:

- **ToolCallCount:** a deterministic evaluator requires exactly one
  `get_current_toll_price` call per user turn. Zero calls, duplicate calls, or a
  different tool fail. The two-turn origin-correction case requires two calls
  total, one per turn. Simulator and judge calls are not counted.

- **Completeness:** Strands `GoalSuccessRateEvaluator`, using the fixture's
  `expected_assertion`. SDK 1.1.0 has no class named `CompletenessEvaluator`.
- **Correctness:** Strands `CorrectnessEvaluator`, with a small prompt adapter
  that includes the full conversation and actual tool results. Its default
  reference prompt omits that evidence.

The SDK `Session` is constructed from actual responses and extracted tool calls,
preserving JSON tool payloads. Simulator messages and judge reasoning are not
agent tool evidence. No fixed toll values, required emoji, Markdown layouts, or
exact response phrases determine the scheduled score. Unknown/unavailable
results are judged against their actual evidence, not presumed calendar state.
The origin-correction case grounds each price in its own observation instead of
requiring prices from separate calls to be identical.

These judges replace `TollChatEvaluator` for the scheduled suite only. Existing
deterministic domain checks remain available for manual diagnostics and regression runs.
One case produces three evaluator rows in the detailed report; failure notifications
count it as one case. Actor/judge execution errors use the operational-error path.
The actor stopping is not itself a passing score. Empty case selections, missing
verdicts, and pricing-tool execution errors fail through the operational-error path.

The offline checks verify simulation bounds, evidence transfer, judge selection,
and failure handling. They do not establish judge accuracy; a live run and review
of its verdicts are still needed before relying on the new scores.

## Offline check

```bash
uv run pytest -q tests/test_run_evaluation.py
```

This command is network-free and runs in normal pull-request CI.

## Live run

Use the development account and its database roles for the live commands below:

```bash
export AWS_PROFILE=nova-toll-dev AWS_DEFAULT_REGION=us-east-1
export DB_NAME=nova_toll_development DB_USER=tollchat_agent_development
export PRICING_DB_USER=pricing_caller_development
```

Configure `DB_HOST`, `DB_PORT`, and `DB_CA_BUNDLE_PATH` for the development
database as described in the [local console setup](../README.md#local-agent-console).
Credentials come from the configured AWS profile and SSM, not a project secrets file.

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
  uv run python eval/run_evaluation.py --window i95_southbound --suite scheduled
```

The Springfield-Franconia to Westpark direct-price regression runs only during
a Monday-Friday northbound window. The same command also checks the
Dulles-to-Reagan cross-direction route every northbound day:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
  uv run python eval/run_evaluation.py --window i95_northbound --suite direct
```

The optional southbound direct regression retains one agent for a scripted Reagan Airport
to Westpark request followed by an I-395 Pentagon/Eads origin correction. It
makes one current-price call per turn (two TollChat invocations total), requiring
the exact distinct origins and equal public priced-toll projection; this is an
offline contract, not a live-run result.

## Critical DCA offline coverage

| Behavior | I-95 window |
| --- | --- |
| Dulles Airport to Reagan Airport direct price | northbound only |
| Old Keene Mill Road to Reagan Airport unavailable result | reversal and southbound only |
| Reagan Airport to Pentagon/Eads to Westpark correction | southbound only |

Slice 3 reuses these existing cases and adds no prompt or model invocation.

The twelve annual cases are independent of the live I-95 direction:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
  uv run python eval/run_evaluation.py --window all --suite annual
```

The Leesburg-to-Washington current and annual cases each send their prompt,
then the optional scalar `follow_up` (`I-395.`), to one retained agent. The
first turn must ask between I-66 and I-395 without a tool call. The current
case then calls Greenway entry `greenway:1:entry:EB` to Washington exit
`i95:2249ND`; the annual case uses that outbound route and the reverse
`i95:2232SO` to `greenway:1:exit:WB` return with the supplied schedule and
income. A current lane-closure result is valid only when its exact route and
grounded closure explanation are present. An annual `no_complete_paired_days`
result is valid only after that exact route call; `route_unavailable` or a
Springfield alternative remains a failure.

The independent-leg daily cases select every new annual behavior in each of
`i95_northbound`, `i95_southbound`, and `i95_reversal`. The offline regression check
asserts exact endpoint inputs, the observed Backlick alternatives, retained
selection fields, confirmation timing, rejection mutations, and tool-grounded
financial claims. A bounded authenticated run requested the `i95_southbound`
package selection and passed all five cases, but its annual trajectories carried
no I-95 lane-state observation; `i95_northbound` and `i95_reversal` remain
pending.

Run each targeted workflow five times as a delivery check (not a reliability
claim):

```bash
for run in 1 2 3 4 5; do
  env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
    uv run python eval/run_evaluation.py --window i95_southbound --suite direct \
    | tee "/tmp/leesburg-i395-current-${run}.txt" || exit
done

for run in 1 2 3 4 5; do
  env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
    uv run python eval/run_evaluation.py --window all --suite annual \
    | tee "/tmp/leesburg-i395-annual-${run}.txt" || exit
done
```

The cumulative delivery gate is the offline check, focused live workflows and
live tests, then the normal v2 lint/format/type/test/contract/build checks and
disposable PostgreSQL migration/contracts validation. Live reports are ignored;
the checks read existing services only and do not deploy or mutate deployed data.

The live run needs the RDS CA bundle at `infra/build/loader/rds-ca-bundle.pem`, AWS
access to RDS and `/nova-toll/openai_api_key`, and network access to the private
database. The window must match the live state. The timed Lambda selects the I-66 eastbound case at 7:23 AM and the westbound
case at 5:23 PM Eastern. Other I-66 states require explicit regression runs.

## Asynchronous ballpark hallucination run

The frozen-evidence Batch evaluation captures one real annual ballpark for a
240-day, $120,000 Springfield-Franconia–Westpark commute at 8:30 AM and 5:30
PM, then expands five reviewed prompts to 1,000 responses. Generated Batch
files stay in ignored `eval/private/`; the small canonical fixture is
`eval/ballpark-hallucination-cases.jsonl`.

GPT-6 Luna is not yet mapped by the pinned tiktoken version. The packet reports
an approximate `o200k_base` count; queue admission conservatively uses UTF-8
bytes plus the existing 10% guard until an official mapping is available.

Prepare and inspect the exact packet without calling OpenAI:

```bash
AWS_PROFILE=nova-toll-dev AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py prepare
jq .preflight eval/private/annual-ballpark-hallucination/manifest.json
```

Submit only after reviewing that report. The command recounts the packet and
all visible nonterminal Luna Batch inputs before uploading:

```bash
AWS_PROFILE=nova-toll-dev AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py submit
```

Once the manifest contains a Batch ID, OpenAI owns the 24-hour job and this PC
may be powered off. Later, run `collect`; it checks once and exits immediately
when the job is still pending:

```bash
AWS_PROFILE=nova-toll-dev AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py collect
```

Terminal collection reconciles unordered IDs, preserves Batch errors, and
writes `results.json` plus every failure and a deterministic 20-pass sample in
`review.json`. Expired or failed work is never resubmitted automatically.
The completed run and adjudicated findings are summarized in
[`ballpark-hallucination-report.md`](ballpark-hallucination-report.md).

## Public evaluation dashboard

`/eval-dashboard` presents real scheduled results in plain language. The timed
Lambda stores occurrence history in Postgres and publishes a sanitized S3
snapshot; the browser refreshes it every minute. It shows seven days of history
and the latest actual conversation, pricing evidence, and judge explanations for
each scenario. Errors and missing runs are separate from graded failures.
Development publication is enabled first; production remains on hold.
See the [dashboard runbook](../runbooks/eval-dashboard.md) for delivery order,
permissions, and verification.

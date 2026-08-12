# Deterministic TollChat evaluation: fuzzy location matching

Tests Step 1 of `agent-sops/nova-toll-pricing-assistant.sop.md` — does the
agent ask before guessing every current multi-match alias, retain the fixed
endpoint and optional time through clarification, converge on the exact oracle
label, resolve an unambiguous case-insensitive match without asking, and honor
explicit wording only when it leaves one candidate. See `eval-plan.md` for the
full plan and `test-cases.jsonl` for the cases.

## Self-check (no network)

```bash
uv run python eval/deterministic/fuzzy_location_matching/deterministic_fuzzy_location_matching.py --check
```

Runs the per-turn matching logic against synthetic trajectories. No
AWS/OpenAI/RDS calls.

## Live run

```bash
AWS_PROFILE=nova-toll uv run python eval/deterministic/fuzzy_location_matching/deterministic_fuzzy_location_matching.py
```

Invokes the real agent (`agent.toll_agent.build_agent`), which needs the
OpenAI key from SSM and the pricing tools' RDS access over the Tailscale
bridge. `main()` resolves and exports
`DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_CA_BUNDLE_PATH`
itself via `agent.dev_chat.configure_local_pricing_env()` (same helper the
local dev console uses). Run `scripts/build_zips.sh` once first to create the
gitignored RDS CA bundle; after that, only `AWS_PROFILE` is needed. Results
land in `eval/results/<timestamp>.json`; representative valid runs may be curated
in the repository's results index.

Required CI runs only the offline `--check`. The live suite runs nightly because
agent execution is stochastic; a failed evaluator fails that nightly workflow
without blocking a merge.

## Simulated-user evaluation (Track 2)

`simulation_support.py` is reusable scaffolding for future evals that need
an LLM-simulated user (`strands_evals.ActorSimulator`) instead of a
scripted conversation turn — import it directly, same as the deterministic
suite imports its own helpers. `simulated_user_fuzzy_location_matching.py`
contains the observational McLean, Washington-origin, and
Washington-destination scenarios built on it. Unlike Track 1's code-based
script, the simulated user is an LLM, so conversations vary run to run. A
code-based trace evaluator still requires the first-turn question, no premature
tool, the exact ordered canonical calls, retained endpoints/time, and non-error
tool executions. Batch metadata remains available for later qualitative judging.
See `eval-plan.md`'s "Track 2" section for the full design.

```bash
uv run python eval/simulation_support.py --check
uv run python eval/simulated/simulated_user_fuzzy_location_matching.py --check
```

Both validate deterministic, non-network logic. The simulated check exercises
the trace evaluator with synthetic sessions; live telemetry mapping and actor
behavior are not covered by `--check`.

```bash
AWS_PROFILE=nova-toll uv run python eval/simulated/simulated_user_fuzzy_location_matching.py
```

A live run spends across three billed surfaces for the three simulated cases:
OpenAI (the agent under test), Bedrock (the simulator's conversational turns),
and RDS (the agent's pricing tools). Optional later Batch judges use OpenAI.
The simulator uses Claude Haiku 4.5
(`us.anthropic.claude-haiku-4-5-20251001-v1:0`) locally;
`NOVA_TOLL_EVAL_MODEL_ID` overrides that model for automated runs.

## Nightly run

`.github/workflows/nightly-evals.yml` runs both code-graded suites every day at
3:17 AM New York time, and supports manual dispatch from `main`. Simulated
execution remains observational because the actor is stochastic; failed trace
verdicts and execution failures fail the workflow. Each JSON report is retained
as a GitHub artifact for 90 days.

Nightly simulator and judge calls use the `nova-toll-nightly-eval` Bedrock
application inference profile. In the AWS payer account, activate the `purpose`
cost-allocation tag, then filter Cost Explorer or CUR by
`project=nova-toll-budget-agent` and `purpose=nightly-eval`. Tag discovery and
activation can each take up to 24 hours.

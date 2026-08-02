# Deterministic TollChat evaluation: NY-time handling & US date/time format

Tests two behaviors rooted in `agent_tools/_oracle_route.resolve_at_time`
and SOP Step 4 of `agent-sops/nova-toll-pricing-assistant.sop.md`: does the
agent turn a user-stated date/time into an `at_time` argument that resolves
to the correct America/New_York instant (whether or not the user's phrasing
already named Eastern time, and across the DST boundary), and does it
report timestamps back to the user in US Standard format
(`M/D/YYYY h:MM AM/PM ET`) rather than the tool's raw ISO-8601 string. See
`eval-plan.md` for the full plan and `test-cases.jsonl` for the 3 cases.

## Self-check (no network)

```bash
uv run python eval/deterministic/ny_time_us_format/deterministic_ny_time_us_format.py --check
```

Runs the per-case matching logic in both evaluators against synthetic
trajectories. No AWS/OpenAI/RDS calls.

## Live run

```bash
AWS_PROFILE=nova-toll uv run python eval/deterministic/ny_time_us_format/deterministic_ny_time_us_format.py
```

Invokes the real agent (`agent.toll_agent.build_agent`), which needs the
OpenAI key from SSM and the pricing tools' RDS access over the Tailscale
bridge — same requirements as `tests/test_toll_agent_live.py` and the
fuzzy-location suite. `main()` resolves and exports
`DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_CA_BUNDLE_PATH` itself via
`agent.dev_chat.configure_local_pricing_env()`. Run `scripts/build_zips.sh`
once first to create the gitignored RDS CA bundle; after that, only
`AWS_PROFILE` is needed. Results land in `eval/results/<timestamp>.json`
(gitignored).

The trusted `integration` job in `.github/workflows/ci.yml` runs this suite
as a regression gate, alongside the fuzzy-location suite. Any failed
evaluator makes the command exit nonzero.

## Simulated-user evaluation (Track 2)

`simulated/simulated_user_ny_time_us_format.py` builds on
`eval/simulation_support.py` (the same reusable `ActorSimulator` scaffolding
the fuzzy-location suite uses) to cover relative/fuzzy date phrasing
("tomorrow at 5pm", "next Monday morning") that this deterministic suite
can't assert against, since the agent has no injected notion of "today."
Unlike the suite above, this is **not a regression gate** — the simulated
user and both judges (`HelpfulnessEvaluator`, `GoalSuccessRateEvaluator`)
are all LLMs, so results vary run to run.

```bash
uv run python eval/simulated/simulated_user_ny_time_us_format.py --check
```

Only validates deterministic, non-network logic (the `Case` and actor
profile shapes). Span-to-session mapping and both judges only run live and
are not covered by `--check`.

```bash
AWS_PROFILE=nova-toll uv run python eval/simulated/simulated_user_ny_time_us_format.py
```

A live run spends across three billed surfaces for the one simulated case:
OpenAI (the agent under test), Bedrock (the simulator's conversational
turns and both judges), and RDS (the agent's pricing tools). The simulator
and judges use Claude Haiku 4.5
(`us.anthropic.claude-haiku-4-5-20251001-v1:0`) locally;
`NOVA_TOLL_EVAL_MODEL_ID` overrides that model for automated runs.

## Nightly run

`.github/workflows/nightly-evals.yml` runs this simulated-user evaluation
every day at 3:17 AM New York time alongside the fuzzy-location one, and
supports manual dispatch from `main`. Judge verdicts are observational;
execution failures still fail the workflow. Each JSON report is retained as
a GitHub artifact for 90 days.

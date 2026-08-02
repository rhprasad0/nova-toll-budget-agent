# Deterministic TollChat evaluation: fuzzy location matching

Tests Step 1 of `agent-sops/nova-toll-pricing-assistant.sop.md` — does the
agent ask before guessing an ambiguous location, converge on the exact
oracle label once the user clarifies, resolve an unambiguous case-insensitive
match without asking. See `eval-plan.md` for the full plan and
`test-cases.jsonl` for the 2 cases.

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
bridge — same requirements as `tests/test_toll_agent_live.py`. `main()`
resolves and exports `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_CA_BUNDLE_PATH`
itself via `agent.dev_chat.configure_local_pricing_env()` (same helper the
local dev console uses). Run `scripts/build_zips.sh` once first to create the
gitignored RDS CA bundle; after that, only `AWS_PROFILE` is needed. Results
land in `eval/results/<timestamp>.json`; representative valid runs may be curated
in the repository's results index.

The trusted `integration` job in `.github/workflows/ci.yml` runs this suite as
a regression gate. Any failed evaluator makes the command exit nonzero.

## Simulated-user evaluation (Track 2)

`simulation_support.py` is reusable scaffolding for future evals that need
an LLM-simulated user (`strands_evals.ActorSimulator`) instead of a
scripted conversation turn — import it directly, same as the deterministic
suite imports its own helpers. `simulated_user_fuzzy_location_matching.py` is
the observational fuzzy-location scenario built on it. Unlike Track 1 above,
this is
**not a regression gate** — the simulated user and both judges
(`HelpfulnessEvaluator`, `GoalSuccessRateEvaluator`) are all LLMs, so results
vary run to run. See `eval-plan.md`'s "Track 2" section for the full design.

```bash
uv run python eval/simulation_support.py --check
uv run python eval/simulated/simulated_user_fuzzy_location_matching.py --check
```

Both only validate deterministic, non-network logic (the turn-loop's stop
conditions, and the simulated `Case` and actor profile shapes). Span-to-session
mapping and both judges only run live and are not covered by `--check`.

```bash
AWS_PROFILE=nova-toll uv run python eval/simulated/simulated_user_fuzzy_location_matching.py
```

A live run spends across three billed surfaces for the one simulated case:
OpenAI (the agent under test), Bedrock (the simulator's conversational turns
and both judges), and RDS (the agent's pricing tools). The simulator and judges
use Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) locally;
`NOVA_TOLL_EVAL_MODEL_ID` overrides that model for automated runs.

## Nightly run

`.github/workflows/nightly-evals.yml` runs the simulated-user evaluation every day at
3:17 AM New York time and supports manual dispatch from `main`. Judge verdicts
are observational; execution failures still fail the workflow. Each JSON report
is retained as a GitHub artifact for 90 days.

Nightly simulator and judge calls use the `nova-toll-nightly-eval` Bedrock
application inference profile. In the AWS payer account, activate the `purpose`
cost-allocation tag, then filter Cost Explorer or CUR by
`project=nova-toll-budget-agent` and `purpose=nightly-eval`. Tag discovery and
activation can each take up to 24 hours.

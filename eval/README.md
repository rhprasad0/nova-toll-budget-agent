# TollChat evaluation: fuzzy location matching

Tests Step 1 of `agent-sops/nova-toll-pricing-assistant.sop.md` — does the
agent ask before guessing an ambiguous location, converge on the exact
oracle label once the user clarifies, resolve an unambiguous case-insensitive
match without asking, and never fabricate a price for an uncovered road.
See `eval-plan.md` for the full plan and `test-cases.jsonl` for the 3 cases.

## Self-check (no network)

```bash
uv run python eval/run_evaluation.py --check
```

Runs the per-turn matching logic in both evaluators against synthetic
trajectories. No AWS/OpenAI/RDS calls.

## Live run

```bash
AWS_PROFILE=nova-toll uv run python eval/run_evaluation.py
```

Invokes the real agent (`agent.toll_agent.build_agent`), which needs the
OpenAI key from SSM and the pricing tools' RDS access over the Tailscale
bridge — same requirements as `tests/test_toll_agent_live.py`. `main()`
resolves and exports `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_CA_BUNDLE_PATH`
itself via `agent.dev_chat.configure_local_pricing_env()` (same helper the
local dev console uses), so nothing beyond `AWS_PROFILE` needs to be set by
hand. Results land in `eval/results/<timestamp>.json` (gitignored).

## Simulated-user demo (Track 2)

`simulation_support.py` is reusable scaffolding for future evals that need
an LLM-simulated user (`strands_evals.ActorSimulator`) instead of a
scripted conversation turn — import it directly, same as `run_evaluation.py`
imports its own helpers. `examples/run_simulated_demo.py` is a worked
example built on it, kept for reference rather than as part of the active
harness (not re-run routinely). Unlike Track 1 above, this is
**not a regression gate** — the simulated user and both judges
(`HelpfulnessEvaluator`, `GoalSuccessRateEvaluator`) are all LLMs, so results
vary run to run. See `eval-plan.md`'s "Track 2" section for the full design.

```bash
uv run python eval/simulation_support.py --check
uv run python eval/examples/run_simulated_demo.py --check
```

Both only validate deterministic, non-network logic (the turn-loop's stop
conditions, and the demo `Case`'s shape). Profile generation, span-to-session
mapping, and both judges only run live and are not covered by `--check`.

```bash
AWS_PROFILE=nova-toll uv run python eval/examples/run_simulated_demo.py
```

A live run spends across three billed surfaces for the one demo case:
OpenAI (the agent under test), Bedrock (the simulator's profile generation,
its conversational turns, and both judges), and RDS (the agent's pricing
tools). The simulator's turns and both judges pin Claude Haiku 4.5
(`us.anthropic.claude-haiku-4-5-20251001-v1:0`); profile generation is a
bare `Agent(callback_handler=None)` with no model override available, so it
always runs on `strands.Agent`'s own Bedrock default regardless.

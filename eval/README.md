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
bridge — same requirements as `tests/test_toll_agent_live.py`. Results land
in `eval/results/<timestamp>.json` (gitignored).

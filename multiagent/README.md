# TollChat multiagent rewrite

This directory is the exclusive home for TollChat's from-scratch multiagent rewrite, including its future code, tests, evals, infrastructure, and documentation.

The complete current implementation lives in [`single-agent/`](../single-agent/) and keeps its existing build and deployment behavior. The rewrite has no compatibility or dependency contract with it. Reuse code only through an explicit future change that copies or reintroduces the needed behavior here.

Multiagent-related documents in `single-agent/` are historical reference material until the rewrite deliberately adopts them.

## Contract drafts

- [Orchestrator agent (incomplete)](docs/orchestrator-agent-contract.md)

## Adopted contracts

- [Historical pricing MVP](docs/historical-pricing-mvp-contract.md)

## Route-ready orchestrator

The first implementation slice lives in [`orchestrator/`](orchestrator/). It
owns the I-95 direction and access gates plus the universal route planner. It
does not contain pricing specialists yet.

```bash
uv sync --locked
uv run pytest
uv run python -m orchestrator.agent "Plan a trip from I-66 West to Westmoreland St"
```

The live I-95 tool smoke is opt-in with `pytest -m live` and requires the
read-only RDS environment variables documented by the existing AWS setup. The
agent loads its OpenAI key from SSM; credentials are never read from a local
file.

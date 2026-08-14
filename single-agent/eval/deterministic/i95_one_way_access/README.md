# I-95/395 one-way access evaluations

This track verifies TollChat checks I-95/395 direction-specific access before
pricing. It covers direct and cross-corridor invalid southbound exits,
invalid northbound entries, and a supported control route.
The simulated trace grader also distinguishes valid duplicate-hook cancellations
from duplicate successful executions and requires complete downstream recovery.

## Offline checks

```bash
uv run python eval/deterministic/i95_one_way_access/deterministic_i95_one_way_access.py --check
uv run python eval/simulated/simulated_user_i95_one_way_access.py --check
```

These use synthetic traces only; no OpenAI, Bedrock, AWS, or RDS calls occur.

## Live runs

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python eval/deterministic/i95_one_way_access/deterministic_i95_one_way_access.py
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python eval/simulated/simulated_user_i95_one_way_access.py
```

The deterministic runner invokes OpenAI and read-only RDS as needed. The
three-turn simulation additionally invokes Bedrock for actors and judges.
Reports are written to `eval/results/`; only technically valid runs belong in
the curated index.

Run both offline checks manually before live evaluation. Deterministic grading
does not make TollChat's live model execution deterministic, so both live
commands require explicit authorization and remain observational evidence.

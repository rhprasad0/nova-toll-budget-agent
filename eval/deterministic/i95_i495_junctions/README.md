# Direction-aware I-95/I-495 junction evaluations

Ten Issue #17 fixtures cover both travel orders, both reversible directions,
closed and transitioning lanes, the inside-gap boundary, an adversarial free
override, and controlled alias resolution. The deterministic grader requires
the complete authorized trace and a response grounded in captured results. The
simulated track observes follow-up consistency; it is not a regression gate.

## Offline checks

```bash
uv run python eval/deterministic/i95_i495_junctions/deterministic_i95_i495_junctions.py --check
uv run python eval/simulated/simulated_user_i95_i495_junctions.py --check
```

These checks use synthetic trajectories and make no OpenAI, Bedrock, AWS, or
RDS calls.

## Code-graded live regression

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python eval/deterministic/i95_i495_junctions/deterministic_i95_i495_junctions.py
```

This makes ten OpenAI agent invocations and reads historical VDOT pricing from
RDS. Runtime credentials come from IAM and SSM Parameter Store. It never calls
Transurban live pricing.

## Simulated-user experiment

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python eval/simulated/simulated_user_i95_i495_junctions.py
```

This additionally bills Bedrock for ten actors of up to three turns and two
judges per case. Set `NOVA_TOLL_EVAL_MODEL_ID` to override the committed model.
Run it only with explicit authorization.

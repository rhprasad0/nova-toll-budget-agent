# Missing parameter acquisition evaluation

This simulated-user suite covers issue #29. It verifies that TollChat asks for
all and only genuinely missing required trip parameters in one question before
using tools, then completes the fixed I-495 trip after the user answers.

## Offline check

```bash
uv run python eval/simulated/simulated_user_missing_parameter_acquisition.py --check
```

The check validates fixtures, the scripted user, and evaluator branches. It does
not invoke TollChat, OpenAI, RDS, SSM, or telemetry mapping.

## Live run

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/simulated/simulated_user_missing_parameter_acquisition.py
```

The runner uses OpenAI for TollChat, a deterministic scripted user,
SSM-backed configuration, and read-only RDS pricing. A deterministic trace
evaluator is the only judge. It runs three cases with exactly two agent turns
each and writes a timestamped report to `eval/results/`. The agent remains
stochastic; one observation is evidence, not proof of future responses. Any
failed deterministic verdict makes the runner exit nonzero.

Ordinary CI runs only `--check`. Run the paid live suite manually with explicit authorization.

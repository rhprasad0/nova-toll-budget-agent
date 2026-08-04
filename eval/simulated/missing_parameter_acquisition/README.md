# Missing parameter acquisition evaluation

This simulated-user suite covers issue #29. It verifies that TollChat asks for
all and only genuinely missing required trip parameters in one question before
using tools, then completes the fixed I-495 trip after the user answers.

## Offline check

```bash
uv run python eval/simulated/simulated_user_missing_parameter_acquisition.py --check
```

The check validates fixtures, actor profiles, and evaluator branches. It does
not invoke TollChat, OpenAI, Bedrock, RDS, SSM, telemetry mapping, or the judge.

## Live run

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/simulated/simulated_user_missing_parameter_acquisition.py
```

The runner uses OpenAI for TollChat, Bedrock for the explicit actors and
goal-success judge, SSM-backed configuration, and read-only RDS pricing. It runs
three cases with at most two agent turns each and writes a timestamped report to
`eval/results/`. Simulations are stochastic; one observation is evidence, not a
proof of future responses.

Ordinary CI runs only `--check`. The paid live suite runs nightly.

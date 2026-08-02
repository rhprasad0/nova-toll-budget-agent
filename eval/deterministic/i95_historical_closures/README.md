# Historical I-95 closure evaluations

Four code-graded live cases and four simulated-user cases cover Issue #17's
historical single-corridor closures. The code-based grader requires one exact
`i95_route` call, an unpriced I-95 general-purpose-lanes suggestion, and no fare
for the captured `CLOSED` result. Grading is deterministic; live agent execution
is stochastic.

## Offline checks

```bash
uv run python eval/deterministic/i95_historical_closures/deterministic_i95_historical_closures.py --check
uv run python eval/simulated/simulated_user_i95_historical_closures.py --check
```

These make no AWS, OpenAI, Bedrock, or RDS calls.

## Code-graded live regression

```bash
AWS_PROFILE=nova-toll uv run python eval/deterministic/i95_historical_closures/deterministic_i95_historical_closures.py
```

This invokes the real TollChat agent and historical RDS pricing. It uses
`configure_local_pricing_env()` to load runtime connection metadata; credentials
remain in SSM/IAM. Results are written under `eval/results/`.

## Simulated-user live run

```bash
AWS_PROFILE=nova-toll uv run python eval/simulated/simulated_user_i95_historical_closures.py
```

This additionally bills Bedrock for four user simulations and two judges per
case. It is observational, not a deterministic regression gate. Set
`NOVA_TOLL_EVAL_MODEL_ID` to override the pinned local simulator/judge model.
Neither track contacts Transurban live pricing.

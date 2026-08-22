# TollChat v2 junction evaluation

This code-graded Strands suite runs five current-toll routing cases through a
fresh production agent. Cases are selected for the live I-95 lane state and
verify exact tool calls, unavailable-direction explanations, TP1NB/TP1SB
fallback behavior, and grounded Markdown/emoji responses.

## Offline check

```bash
uv run python eval/run_evaluation.py --check
```

This command is network-free and runs in normal pull-request CI.

## Live run

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window i95_southbound
```

The live run needs the RDS CA bundle at `infra/build/ca/rds-ca-bundle.pem`, AWS
access to RDS and `/nova-toll/openai_api_key`, and network access to the private
database. The window must match the live state. Protected timed CI runs the
matching subset in every northbound, reversal, and southbound I-95 window.

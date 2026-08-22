# TollChat v2 Westpark evaluation

This code-graded Strands suite runs the two reported southbound trips through a
fresh production agent and verifies the exact current-price call, tool result,
and grounded Markdown/emoji response.

## Offline check

```bash
uv run python eval/run_evaluation.py --check
```

This command is network-free and runs in normal pull-request CI.

## Live run

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python eval/run_evaluation.py
```

The live run needs the RDS CA bundle at `infra/build/ca/rds-ca-bundle.pem`, AWS
access to RDS and `/nova-toll/openai_api_key`, and network access to the private
database. Protected timed CI runs it only in the southbound I-95 window.

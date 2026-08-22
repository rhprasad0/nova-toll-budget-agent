# TollChat v2 evaluation

This code-graded Strands suite runs current-toll routing cases and two annual
job-offer affordability cases through a fresh production agent. It verifies
exact tool calls, route/fallback behavior, grounded money, and the required
Markdown/emoji response hierarchy.

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

The Springfield-Franconia to Westpark direct-price regression runs only during
a Monday-Friday northbound window:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window i95_northbound --suite direct
```

The annual case is independent of the live I-95 direction:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window all --suite annual
```

The live run needs the RDS CA bundle at `infra/build/ca/rds-ca-bundle.pem`, AWS
access to RDS and `/nova-toll/openai_api_key`, and network access to the private
database. The window must match the live state. Protected timed CI runs the
matching subset in every northbound, reversal, and southbound I-95 window.

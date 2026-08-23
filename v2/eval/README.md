# TollChat v2 evaluation

This code-graded Strands suite runs six current-toll routing cases and six
annual job-offer affordability cases through a fresh production agent. It
verifies exact tool calls, route/fallback behavior, required-input and income
clarification, adjustable 52-week commute-day estimates, safe annual route
unavailability, scenario-bound money, and the required Markdown/emoji response
hierarchy.

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
a Monday-Friday northbound window. The same command also checks the
Dulles-to-Reagan cross-direction route every northbound day:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window i95_northbound --suite direct
```

The six annual cases are independent of the live I-95 direction:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window all --suite annual
```

The live run needs the RDS CA bundle at `infra/build/ca/rds-ca-bundle.pem`, AWS
access to RDS and `/nova-toll/openai_api_key`, and network access to the private
database. The window must match the live state. Protected timed CI runs the
matching subset in every northbound, reversal, and southbound I-95 window.

## Asynchronous ballpark hallucination run

The frozen-evidence Batch evaluation captures one real annual ballpark for a
240-day, $120,000 Springfield-Franconia–Westpark commute at 8:30 AM and 5:30
PM, then expands five reviewed prompts to 1,000 responses. Generated Batch
files stay in ignored `eval/private/`; the small canonical fixture is
`eval/ballpark-hallucination-cases.jsonl`.

Prepare and inspect the exact packet without calling OpenAI:

```bash
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py prepare
jq .preflight eval/private/annual-ballpark-hallucination/manifest.json
```

Submit only after reviewing that report. The command recounts the packet and
all visible nonterminal Luna Batch inputs before uploading:

```bash
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py submit
```

Once the manifest contains a Batch ID, OpenAI owns the 24-hour job and this PC
may be powered off. Later, run `collect`; it checks once and exits immediately
when the job is still pending:

```bash
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py collect
```

Terminal collection reconciles unordered IDs, preserves Batch errors, and
writes `results.json` plus every failure and a deterministic 20-pass sample in
`review.json`. Expired or failed work is never resubmitted automatically.
The completed run and adjudicated findings are summarized in
[`ballpark-hallucination-report.md`](ballpark-hallucination-report.md).

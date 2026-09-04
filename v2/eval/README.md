# TollChat v2 evaluation

This code-graded Strands suite runs nine current-toll routing cases and ten
annual-affordability golden cases through a fresh production agent. The golden
corpus is SemVer 1.0.0 and includes four sanitized typed fixtures. Fixture-backed
case provenance uses the fixture source and compares aware ISO timestamps after
UTC normalization at second precision, ignoring capture microseconds. A `success` fixture maps to a
success/clarification/correction case outcome, `partial_success` maps only to
`partial_success`, and `route_unavailable` maps to `structured_unavailability`.
The manifest also hashes the raw nine-row legacy `test-cases.jsonl` source so all
19 runtime cases participate in the versioned dataset contract. It verifies
exact tool calls, route/fallback behavior, required-input and income
clarification, adjustable 52-week commute-day estimates, safe annual route
unavailability, scenario-bound money, and the required Markdown/emoji response
hierarchy.

## Offline check

```bash
uv run python eval/golden_corpus.py validate --base-ref HEAD
uv run python eval/run_evaluation.py --check
```

This command is network-free and runs in normal pull-request CI.

## Fixture-only golden review

Render the self-contained, worktree-only review page from the validated
manifest and its four recorded fixtures:

```bash
uv run python eval/golden_corpus.py render \
  --manifest eval/golden/manifest.json --output ../.graph/golden-review.html
```

The page contains ten annual-affordability case cards, deterministic required
and prohibited evaluator behavior, the 19-case coverage/hash contract, and
sanitized typed fixture details. It clearly labels fixtures as byte-pinned
historical regression evidence, shows pinned 08:00, 08:30, and rejected 12:00
capture context, and shows no model output. Human approval is pending; the
artifact is not pass^3 or unbiased evidence, and candidate execution is
deferred to #362/#363.

The pre-existing live evaluator and Batch utility documented below are separate
manual workflows. Golden `validate`, golden `render`, and CI never invoke them;
their historical reports are not approval evidence for this corpus.

The #361 acceptance gate covers corpus integrity and structured expectations:
exact arguments, call order, typed fixture results, references, and coverage.
The existing prose graders are bounded regression heuristics. They can reject
valid paraphrases or miss unsupported claims; passing them does not prove
natural-language correctness. Broad prose-grading work belongs to #360, with
baseline and candidate execution in #362/#363.

## Growing the corpus

Add cases to a declared JSONL shard or declare another shard in `case_shards`.
Update fixture `case_ids`, shard counts, coverage, and the sorted payload list;
hash each payload's raw bytes with SHA-256. Compute `dataset_sha256` over the
manifest without that field, serialized as UTF-8 JSON with sorted keys, compact
separators, and `ensure_ascii=False`. The legacy source has its own raw-byte hash.

Advance `dataset_version` for any changed bundle: patch for corrections, minor
for additive cases, major for incompatible dataset changes. Keep `format_version`
at `1.0.0` while using this format. Validation against the PR base rejects a
missing version advance or an invalid base ref; validation without a base checks
only internal consistency. New tags have no prior version to compare.

The initial `1.0.0` release also pins the reviewed cases and fixture bytes in
code. Later releases use schema, references, coverage, hashes, and Git version
comparison without changing the validator for each added case. Human review
approves changed expectations and evidence; hashes detect drift, not truth.
The current format supports the annual-affordability capability and existing
scenario families. A new tool capability needs its own typed validation.

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

The ten annual cases are independent of the live I-95 direction:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window all --suite annual
```

The Leesburg-to-Washington current and annual cases each send their prompt,
then the optional scalar `follow_up` (`I-395.`), to one retained agent. The
first turn must ask between I-66 and I-395 without a tool call. The current
case then calls Greenway entry `greenway:1:entry:EB` to Washington exit
`i95:2249ND`; the annual case uses that outbound route and the reverse
`i95:2232SO` to `greenway:1:exit:WB` return with the supplied schedule and
income. A current lane-closure result is valid only when its exact route and
grounded closure explanation are present. The golden Leesburg-to-Washington
fixture is an authentic 08:30/17:30 partial result (51/60 complete pairs,
85.0% coverage); the rejected artificial 12:00 zero-pair diagnostic is not
corpus evidence.

Run each targeted workflow five times as a delivery check (not a reliability
claim):

```bash
for run in 1 2 3 4 5; do
  env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
    uv run python eval/run_evaluation.py --window i95_southbound --suite direct \
    | tee "/tmp/leesburg-i395-current-${run}.txt" || exit
done

for run in 1 2 3 4 5; do
  env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
    uv run python eval/run_evaluation.py --window all --suite annual \
    | tee "/tmp/leesburg-i395-annual-${run}.txt" || exit
done
```

The cumulative delivery gate is the offline check, focused live workflows and
live tests, then the normal v2 lint/format/type/test/contract/build checks and
disposable PostgreSQL migration/contracts validation. Live reports are ignored;
the checks read existing services only and do not deploy or mutate deployed data.

The live run needs the RDS CA bundle at `infra/build/ca/rds-ca-bundle.pem`, AWS
access to RDS and `/nova-toll/openai_api_key`, and network access to the private
database. The window must match the live state. Protected timed CI also runs
the I-66 eastbound/westbound cases at 7:23 AM, 2:17 PM, and 5:23 PM Eastern so
the active/free and both-free states are covered by the existing daily jobs.

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

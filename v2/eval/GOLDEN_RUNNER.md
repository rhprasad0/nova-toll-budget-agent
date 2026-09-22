# Running the frozen golden corpus

The active corpus and harness are **2.0.0**: **200 cases**, split into **160
development and 40 reserved cases**, with three fresh trials per case. A complete
application run has **600 conversations**. Reserved cases are public and
exposed to their authors; they are excluded from calibration, not claimed to be
secret or independently authored holdouts.

The runner executes the candidate application against frozen pricing evidence.
Adaptive users provide only their case facts and required follow-ups. No database
or live pricing service is used. The application model and prompt are unchanged;
model credentials come from the existing SSM parameter.

## Calibration and execution

The corpus contains **326 reference examples**. Calibration selects **274
development examples**: 272 have explicit Outcome, Grounding, and Rules labels
(816 application labels), and two deliberately invalid actor examples have only
an actor-validity label. The 52 reserved examples are excluded. Example names do
not determine verdicts. Reports preserve disagreements and separate criterion
confusion matrices from actor-validity confusion and measurement failures.

The current local authorization covers **two calibration passes within a combined
$25 ceiling**. Their evidence is pending execution and review; this authorization
does not establish judge agreement or approve an application run. Link the second
pass to the first so prior usage remains charged to the shared limit. From a
clean, committed checkout in `v2/`:

```bash
uv run python -m eval.golden_run calibrate \
  --output eval/private/golden-200/calibration-1 --budget-usd 25
uv run python -m eval.golden_run calibrate \
  --output eval/private/golden-200/calibration-2 --budget-usd 25 \
  --prior-run eval/private/golden-200/calibration-1
uv run python -m eval.golden_run render \
  --output eval/private/golden-200/calibration-2
```

Retain both passes, including disagreements and failed measurements. Human review
records `status: "approved"`, the exact report `evidence_sha256`, `reviewer`, and
an evidence reference in the calibration directory's `review.json`. Include
adjudications and remaining limitations. Approval does not rewrite measured
verdicts or agreement. Corpus, evaluator, actor-check, label, model, and prompt
identities must match before calibration can support application execution.

A separately authorized application run uses reviewed calibration:

```bash
uv run python -m eval.golden_run run \
  --output eval/private/golden-200/application-1 \
  --calibration eval/private/golden-200/calibration-2 \
  --prior-run eval/private/golden-200/calibration-2
```

Without `--cases`, all 600 trial slots are required. Stable IDs after `--cases`
select a partial diagnostic run, which cannot qualify as complete corpus evidence.
Never overwrite an attempt or retry a trial until it passes. Use a new output
directory and preserve run lineage.

The separate `python -m eval.golden_actor_check --output DIRECTORY
--prior-spend-usd ACCOUNTED_SPEND` check exercises three fresh actors per
development good reference against scripted answers. It measures actor behavior,
not application quality. Any paid actor check needs authorization and must be
included in spending reconciliation; it is not part of the two calibration
commands above.

## What gets scored

Each case declares its intended terminal result: answer, supported refusal,
unavailable explanation, necessary terminal clarification, or cancellation.
Clarification is not a blanket Outcome pass. An honest explanation of an
agent-caused error may pass Grounding while failing Outcome and Rules. Repeated
unnecessary questions that exhaust the dialogue budget are application failures
when the actor supplied the requested facts.

Outcome and actor validity are assessed separately. Actor validity compares the
profile with the actual delivered messages and stop records. Application
judgments use only information available to the application. Invalid or uncertain
actors make the trial inconclusive; private actor facts do not authorize a call.
Rules assess consent and corrections at the time of each call using the latest
delivered user messages. Later approval cannot authorize an earlier call, and an
earlier “yes” cannot override a withdrawal. Deterministic replay still enforces
schemas, exact contractual arguments, fixture order, minimum turns, and budgets.

A scored success requires Outcome, Grounding, Rules, valid actor behavior, and
all mandatory deterministic checks. Reports distinguish application failures,
invalid or uncertain actors, judge/provider failures, and harness errors. Missing
measurements or identities cannot produce a pass. Deliberate fixture tool errors
are case evidence; unexpected infrastructure errors are inconclusive.

Calibration references, including their explicit labels, require human review.
Offline assertion success establishes replay consistency, not semantic judge
accuracy. Candidate text and tool-returned instructions cannot redefine the
rubric or authorize a route change.

## Budget, evidence, and reports

The default local ceiling is $25, including linked prior runs, with agent, actor,
and judge usage accounted separately. Calls reserve their input bound and
2,048-token output cap before execution. Missing usage stops further calls;
reconcile unknown or interrupted usage before spending again. Recorded prices
include cache reads and writes and retain their dated provider source.

Four workers are the default and protected scoring policy; `--workers` accepts
1–8 for diagnostics. Each worker owns its application, actor, model clients, and
replay state. Shared reservations include in-flight calls, and journal writes are
serialized. Cancellation stops queued work and retains usage from active calls.
The manual and protected runners use the same cached actor/judge factory. See the
[historical caching review](results/golden/CACHING-SUMMARY.md).

`manifest.json` identifies the candidate, corpus, labels, evaluator components,
actor checks, model settings, prompts, tool schemas, prices, and lineage.
`events.jsonl` retains every attempt and usage record. Reports can be regenerated
offline. Evidence includes delivered dialogue, calls/results, actor decisions,
and short judge explanations; it excludes private reasoning, credentials,
headers, and provider exception messages. Keep initial artifacts under ignored
`eval/private/` and inspect them before committing sanitized evidence.

Pass@1 uses scored trials as its denominator. For 2.0.0, pass³ uses cases with
three scored trials; incomplete cases and inconclusive trials remain explicit,
and a partial denominator cannot satisfy full-run completion. Family reports show
expected, scored, successful, and inconclusive counts. Separate subsets cover
development, reserved, current, annual, and mixed workflows.

The descriptive 95% interval resamples entire `split_group` clusters, preserving
paired scenarios and shared evidence, 10,000 times with seed 360. Reports include
the number of groups. This is finite-corpus uncertainty, not evidence of broad
population reliability or independent repeated trials. Archived contracts retain
their original case-cluster calculations, denominator semantics, and report shape.

Grounding and Rules rates use scored trials, while observed violations and costs
from other attempts remain visible. A trial may violate both criteria. Latency
includes actor and judge work and reports p50/p95 with sample counts. Agent cost
per success includes failed-attempt cost and is undefined with no successes.
Zero observed violations does not establish zero underlying risk.

Human review should inspect corrections, consent withdrawal, alternative
selection, mixed workflows, partial evidence, financial extremes, actor validity,
and disagreements. Do not relabel or replace the original attempts. Historical
24-case reports and approvals remain historical and do not approve 2.0.0.

A local report cannot qualify a release or promote a baseline. The
[protected golden workflow](GOLDEN_RELEASE.md) authenticates release provenance
and approval. PR CI uses offline tests and a canned packaged-agent smoke.

## Offline checks

```bash
uv run python -m eval.golden
uv run pytest tests/test_golden_corpus.py tests/test_golden_run.py \
  tests/test_golden_baseline.py tests/test_golden_gate.py \
  tests/test_simulated_evaluation.py tests/test_run_evaluation.py
```

These checks cover corpus counts, split isolation, labeled replay, actor and
application attribution, calibration exclusion, consent timing, accounting,
completion, and historical reporting. They do not measure model performance.

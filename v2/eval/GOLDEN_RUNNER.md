# Running the frozen golden corpus

The active authoring contract is **3.0.2: 100 development cases**, with 100
proposed passing and 20 negative references. The first
[calibration](evidence/golden-100/README.md) measured all 120 references using
16 workers for $0.20523038 under 3.0.0. Version 3.0.1 raises the actor maximum
to **five delivered user turns including the opening request** and accepts generic
home/work-area shorthand during commute clarification. Its
[matching calibration](evidence/golden-100/CALIBRATION-2.md) measured all 120
references for $0.20711386 ($0.41234424 cumulative), with nine label disagreements
across eight references. Human approval remains pending.
Version 3.0.2 revises cases 79/80 to return near the same Springfield home area,
with client/office confirmation and mixed-office cancellation. Matching
calibration for this route revision is pending; older measurements do not transfer.
No new application run has been performed. A full future run has
**300 trials**; its holdout subset is empty and has no success rate.

An authored calibration transcript can finish in two turns even though the actor
budget is five. Calibration scores every supplied exchange; it does not generate
hidden extra turns. Live evaluation may finish early or use the full five-turn
budget. Minimum required dialogue and the maximum budget are separate fields.

Validate offline from `v2/` with `uv run python -m eval.golden`. Review the
[catalog](golden/REVIEW.md) before freezing approval. The local runner
requires a clean committed checkout, exact matching calibration, and human
calibration review before application execution. Any paid calibration needs new
authorization and its own spend accounting; archived budgets do not transfer.
The corpus cannot qualify production: independently authored holdout scope and
protected-policy activation are separate work. Historical report rendering remains
available under its recorded contract.

## Historical 2.0.8 procedure

The procedures and counts below describe the retired experiment, not permission
to run or reuse its cases or approvals.

The local experiment corpus and harness are **2.0.8**: **200 cases**, split into **160
development and 40 reserved cases**, with three fresh trials per case. A complete
application run has **600 conversations**. Reserved cases are public and
exposed to their authors; they are excluded from calibration, not claimed to be
secret or independently authored holdouts.

The 2.0.8 calibration uses 286 development references, with unchanged cases
and labels. Run fresh A and B/C calibrations with four
workers, `--budget-usd 15`, and `--prior-run` chained from the immediately preceding
experiment run. Include the archived 2.0.5, 2.0.6 and 2.0.7 calibrations ($2.693874 total) in
that chain. Application execution still requires exact-evidence human review.
The frozen 26-case diagnostic subset is unchanged; no release is authorized.

The runner executes the candidate application against frozen pricing evidence.
Adaptive users provide only their case facts and required follow-ups. No database
or live pricing service is used. Application, actors, and judges use `gpt-6-luna` with unchanged prompts;
model credentials come from the existing SSM parameter.

## Calibration and execution

The corpus contains **338 reference examples**. Calibration selects **286
development examples**: 284 have explicit Outcome, Grounding, and Rules labels
(852 application labels), and two deliberately invalid actor examples have only
an actor-validity label. The 52 reserved examples are excluded. Example names do
not determine verdicts. Fixed-reference mode judges the supplied user turns and any
explicit stop records; it does not invent simulator stops for authored transcripts. Reports preserve disagreements and separate criterion
confusion matrices from actor-validity confusion and measurement failures.

The **two authorized calibration passes are complete**, within their combined
$25 ceiling. The [calibration review](evidence/golden-200/CALIBRATION.md) retains
both runs and every disagreement. They measured contracts 2.0.0 and 2.0.1;
the final 2.0.2 contract corrects one Grounding label and classifies packaged-agent
model-budget exhaustion as an application failure. It still requires fresh
authorized exact-contract calibration and human review before application execution.

The recorded calibration commands were run from clean, committed checkouts in
`v2/`. These are provenance, not authorization to repeat them:

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

A separately authorized application run uses a newly reviewed calibration that
matches the final contract (neither archived run does):

```bash
uv run python -m eval.golden_run run \
  --output eval/private/golden-200/application-1 \
  --calibration PATH_TO_APPROVED_MATCHING_CALIBRATION \
  --prior-run PATH_TO_LATEST_ACCOUNTED_RUN
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
1–16 for local experiments. Each worker owns its application, actor, model clients, and
replay state. Shared reservations include in-flight calls, and journal writes are
serialized. Cancellation stops queued work and retains usage from active calls.
The manual and protected runners use the same cached actor/judge factory. See the
[historical caching review](results/golden/CACHING-SUMMARY.md).

Changing this runner changes its calibration-pinned source hash. The completed
2.0.8 prompt comparison used the frozen runner (four workers for A/B, eight for C
recovery); future application runs using the expanded worker range require a fresh
matching calibration and review. Existing calibration approval is not transferable.

`manifest.json` identifies the candidate, corpus, labels, evaluator components,
actor checks, model settings, prompts, tool schemas, prices, and lineage.
`events.jsonl` retains every attempt and usage record. Reports can be regenerated
offline. Evidence includes delivered dialogue, calls/results, actor decisions,
and short judge explanations; it excludes private reasoning, credentials,
headers, and provider exception messages. Keep initial artifacts under ignored
`eval/private/` and inspect them before committing sanitized evidence.

Pass@1 uses scored trials as its denominator. For 2.0.x, pass³ uses cases with
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
24-case reports and approvals remain historical and do not approve 2.0.2.

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

## GPT-6 Luna migration (2.0.3)

The application, actor, and judge models move to `gpt-6-luna`, with dated
GPT-6 Luna token prices. Cases, labels, prompts, reasoning effort, and token
limits are unchanged. This exact contract requires fresh calibration and human
review; prior model results and approvals remain historical. The local migration
run has a $25 cumulative ceiling across calibration and application execution.

The fresh calibration was approved by Ryan with its documented disagreements.
The [first GPT-6 Luna local baseline](evidence/gpt-6-luna/BASELINE.md) ran all
600 slots: 409 passed, 184 failed, and 7 were inconclusive. It remains an
incomplete scored baseline because of those seven trials; no production
reference was qualified or published.

## Review corrections calibration (2.0.4)

Ryan authorized one fresh calibration with a $5 total ceiling for review-packet
cases 16, 18, and 20. Run the full development calibration set without retries;
retain disagreements and incomplete measurements. This authorizes neither a new
application run nor production qualification. The actor prevention change is
covered by offline contract checks and fixed-reference judge examples; calibration
does not measure fresh live actor reliability.

```bash
AWS_PROFILE=nova-toll-dev AWS_DEFAULT_REGION=us-east-1 \
  uv run python -m eval.golden_run calibrate \
  --output eval/evidence/gpt-6-luna/calibration-2 --budget-usd 5 --workers 4
```

The output must remain pending human review. The prior calibration and application
archives must not be overwritten or silently rescored.

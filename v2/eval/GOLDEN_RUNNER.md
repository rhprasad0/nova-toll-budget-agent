# Running the frozen training split

The local contract has **50 training, 10 shadow and 25 external holdout cases**.
No fresh set is active until it is authored, frozen and reviewed. Training application
runs default to one trial per case; use `--trials-per-case 3` only on Ryan's explicit
instruction. Shadow runs are explicit diagnostics outside search; shadow CI is deferred. Actors have up to five delivered
user turns. The application, actor, judge settings, input hashes, and source commit
are recorded in each run. See [authoring](GOLDEN_EVAL_SPEC.md) for the contract and
[the experiment journal](EXPERIMENT_JOURNAL.md) for results and prior decisions.

Actors reply to necessary questions and outstanding triggered follow-ups. Once a
choice has been delivered, a completed answer using it does not trigger it again;
later necessary questions and separate profile actions still require replies.

All golden judges, including the scripted actor-check assessment, use
`gpt-6-luna` with xhigh reasoning and an 8,192-token output ceiling. Application
generation remains low/2,048 and actor generation medium/2,048 on the same model.
Judge instructions require checking source and other factual claims before
amounts, and evaluating missing qualifications by the meaning conveyed across
the conversation.
Useful answers pass despite optional detail or minor omissions that preserve
material meaning. Missing final-answer disclosures affect Outcome; Rules checks
prohibited actions, affirmative misrepresentations, and required workflow steps.
Run identities and cost reservations record those role-specific limits. Legacy
scheduled evaluation settings are separate from this golden contract.

The replay validator also determines Rules failures for mismatched tool arguments
and call ordering. It supplies field-level differences directly; the Rules judge
assesses all remaining Rules obligations, including consent, workflow, budgets
and affirmative misrepresentations. A matching call
does not establish user consent.
Outcome receives applicable disclosure IDs for published current-price sources,
peak current prices, and returned annual vehicle-cost assumptions. It supplies
assistant line IDs for each requirement, or an empty list for a missing disclosure.
The catalog maps deterministic turn/line IDs to original assistant text, followed
by the full conversation and tool evidence for the remaining assessment.
Code resolves selected IDs without retyping or normalizing Markdown. User and
tool text are excluded. Unknown IDs make the measurement unusable. The model
judges whether the selected lines together convey the requirement, including
headings when needed, and checks remaining requirements and contradictions.
Raw judgments and original cited text remain in private evidence. This uses the
existing three calls per calibration reference. Calibration review need not
require perfect label agreement; document and assess each disagreement.

## Description-edit contract

The local training contract / harness 2.5.0 uses `literal-input-prose-v1`. The corpus hashes
parsed source for the two pricing tool modules, masking only existing literal
`TOOL_SPEC["description"]` strings and `Field(description=...)` strings in the
allowlisted input models (`golden.TOOL_INPUT_MODELS`). All other syntax, including
schema constraints, validators, runtime logic, and output descriptions, stays
pinned. Other corpus sources remain byte-hashed. Formatting/comments do not affect
the parsed source hash; candidate review still admits only specified text edits.
The shared `_PricingProfile` model is excluded because its descriptions also
appear in the output schema.

Each run records full tool schema hashes and the exact source artifact, so wording
changes remain attributable. The eval-climb comparison permits differing tool
hashes only with the supported policy and identical pinned corpus. Old-contract
reports retain their original hash rules and cannot be compared with this contract.
Input approval and matching calibration are required before the next climb;
never transfer prior approvals or regenerate a candidate's corpus manifest.

## Directed-catalog campaign comparison

The separately authorized three-trial campaign may use
`compare_runs.py BASELINE_REPORT CANDIDATE_REPORT --campaign-policy directed-catalog-v1`.
This opt-in policy is limited to harness 2.3.27, three repetitions and renderer
versions 1.0.0 and 1.0.2. It pins both Dulles route source graphs and application
code outside the supplemental catalog helper, its render expression and the
renderer version literal to the campaign's starting commit.
The usual identity checks still pin tools, corpus, actors, judges and model
settings. Default and historical comparisons retain their original behavior.

Independent review must verify that supplemental entry-to-exit relationships
match all 189 canonical same-facility pairs, preserve every catalog record and
field, and introduce no pricing, availability, consent or cross-facility claims.
This evaluates the rendered application prompt. A pricing-runtime resolver
requires a separate measurement repair because frozen replay replaces that code.
The campaign's isolated manifest uses three repetitions; the ordinary development
default stays at one. Results belong in the experiment journal.

Retain evaluated source commits with the private reports in a self-contained
`evaluated-sources.bundle`; temporary worktrees alone do not preserve them.
The campaign archive contains this bundle and its SHA-256 receipt. In a fresh
checkout, verify the receipt and import those commits before comparing reports:

```bash
git bundle verify /absolute/private-campaign/evaluated-sources.bundle
git fetch /absolute/private-campaign/evaluated-sources.bundle \
  'refs/tags/eval/three-trial-20260927/*:refs/tags/eval/three-trial-20260927/*'
```

These refs cover the fixed baseline and every candidate; the selected candidate
also supplies final verification. Keep the bundle and raw reports private.

## Scoring and preparation

Training score is successful trials divided by **all expected training slots**
(case count × recorded execution repetitions).
Fully measured actor inconclusives stay visible and count as no success. Pass³
fields are null (inapplicable) for one repetition. Scheduling, actor checks,
rendering and comparison use recorded `trials_per_case`; historical three-trial
reports keep their recorded scoring rules. Unsupported or mixed contracts fail.

Promotion requires a strict overall score gain and independent scope and material
regression review. Violation and inconclusive increases trigger review, not an
automatic numeric veto. Demonstrated material regressions block promotion; a lost
stochastic pass alone does not prove causation. Ties retain the incumbent.
**90% is a soft milestone.** Sequential search is bounded by the authorized
budget; after four complete candidates without improvement, continue only with a
materially different evidence-backed hypothesis or a bounded measurement repair.
See the [eval-climb skill](../../.agents/skills/eval-climb/SKILL.md).

Optimize using training cases only. Do not use archived or shadow cases in
search. These measurements do not establish
independent agent accuracy. The retired private holdout approach grants no new
development spending authorization.

Judges return cited unmet requirements; an empty list determines success.
The stored `passed`/`evidence` interface remains stable. Calibration must still
check semantic errors; explanations are never regex-relabelled.

Grounding classifies each numerically unsupported currency occurrence as an
assertion, qualified whole-dollar restatement, or nonasserted mention. The money
guard then verifies support and rounding for assertions; denying or rejecting a
price does not assert that price. Classification must cover every occurrence
exactly once, so a denied amount cannot exempt a separate assertion of the same
amount. Missing, duplicate, or unknown IDs invalidate the measurement. This uses
the existing Grounding call; three judge calls remain required per trial.
Authored money classifications in calibration references are used only for
offline validation and are never supplied to judges. Phrase-specific denial
exceptions are not part of the active contract. Semantic classification can still
err; inspect both classifications and final grades during calibration review.

Prepare one local reference calibration with actual review and one scripted actor
check for the selected split. Reuse existing local evidence only with matching
protected sources, input hashes, runtime, actors, judges and model settings.
Then run one full training baseline
(50 cases × 1 trial, 16 workers). Do not duplicate compatible approved preparation. Frozen fixture replay needs no deployment or migration parity
gate. It cannot establish live pricing or deployment correctness.

Use the fixed starting baseline for the final comparison. Reserve one fresh full
finalist rerun with cost headroom. Report the starting score, selected search score
and final score separately; do not rerun a fully measured low result until it
passes. No retained improvement means no unnecessary confirmation run.
Unseeded trial numbers identify slots, not identical random draws. Inspect passing
and failing counterparts and the candidate diff to assess causal regressions.

Audit fresh application trajectories before search and at final confirmation.
Use a fixed selection rule: in each coverage family, review the first successful
and first scored failing trial in `(case_id, trial)` order, when present. Also
review all actor-invalid/uncertain trials and all new Grounding/Rules violations
in comparisons. Cite delivered messages and actual tool evidence; private actor
facts cannot supply missing application facts or consent. Record disagreements
without rewriting scores. A substantive grading defect requires a new contract
and matching calibration. Repeated agreement on exposed calibration references,
or a scripted actor check, cannot establish accuracy on unseen trajectories.

Frozen replay accepts the declared tool sequence and exact arguments, apart from
weekday ordering. Investigate apparently equivalent rejected calls before changing
that contract; never accept a different route merely because it is nearby. Retain
relevant tool/runtime tests separately, since replay does not execute live pricing.

Chain preparation from the last accounted run using the user-authorized cumulative
ceiling. Admit each complete run only when its estimate with headroom fits, reserving
the agreed search and confirmation budget. Record amounts and decisions in the
private ledger and append-only experiment journal.
Stop on unknown usage, infrastructure failure, unresolved material grading
ambiguity or insufficient budget. Do not repeat runs to obtain passing results. Substantial measurement repairs belong in separate PRs. Changes to grading,
simulation, cases or execution semantics require matching calibration and a fresh
baseline; historical scores are not comparable application gains.

## Preparing inputs

Author training and shadow under `eval/active/`. Use `eval.corpus validate` for
draft checks, then `eval.corpus freeze --corpus PATH --split SPLIT --version
5.0.0` to write each split's manifest and pending input review. It records protected
source hashes and never approves inputs. A changed contract needs a newer version
and actual review. CI uses `eval.golden --allow-uninitialized` while waiting for
real inputs; partial sets fail validation. Commit public inputs and their identities
before paid execution. The archive remains historical reference only.

## Execution

Run from `v2/`. Offline validation needs no model calls:

```bash
uv run python -m eval.golden
```

Paid work requires user authorization for a stated budget or explicitly uncapped
spending, and a clean committed checkout. Use a new ignored output directory for each run. These examples assume
an authorized $25 cumulative ceiling and 16 workers (the default); they do not grant permission
to spend or reset a previous ledger.

```bash
uv run python -m eval.golden_run calibrate \
  --output eval/private/calibration-N --budget-usd 25 --workers 16 \
  --prior-run eval/private/previous-run
```

Use `--no-budget-limit` instead of `--budget-usd` only when the user explicitly
authorizes uncapped spending. The flags are mutually exclusive in both runner
and actor-check CLIs. Uncapped manifests store `budget_usd: null`; usage accounting,
call limits, worker bounds, and stop-on-unknown-usage rules still apply.

Omit `--prior-run` only for a genuinely new authorized spending chain. Calibration
judges all references in the selected split; it does not generate new application or
actor conversations. Inspect disagreements, actor validity, measurement failures,
and usage before application execution. Review approval is stored in the private
calibration directory’s `review.json`, bound to the exact evidence digest with
`status`, `reviewer`, and `evidence`. It must not claim human inspection that did
not occur. Existing session authorization determines who may perform the review.

```bash
uv run python -m eval.golden_run run \
  --output eval/private/baseline-N --budget-usd 25 --workers 16 \
  --calibration eval/private/calibration-N \
  --prior-run eval/private/calibration-N
```

`--calibration` accepts a locally reviewed calibration directory matching the
selected corpus, evaluator, runtime and settings. `--cases` selects a partial
public application diagnostic, which cannot represent a full baseline; holdout
checkpoints always use the complete split. Actor-invalid
or uncertain attempts remain inconclusive. Do not retry failures to improve a
score, erase interrupted attempts, or silently relabel an old report.

The scripted actor check uses the same journal accounting and accepts explicit
worker and cumulative budget controls:

```bash
uv run python -m eval.golden_actor_check \
  --output eval/private/actor-check-N --budget-usd 15 --workers 16 \
  --prior-run eval/private/previous-run
```

## Evidence and reporting

Each private run retains `manifest.json`, append-only `events.jsonl`, `report.json`,
and `report.md`. All started calls and usage contribute to cost; unknown usage
stops further paid work. Reproduce a report offline with:

```bash
uv run python -m eval.golden_run render --output eval/private/baseline-N
```

## External holdout checkpoints

These commands belong to the host operator, outside the tuning agent's workflow.
Keep the corpus, calibration, reviews, actor checks and application output outside
the repository and coding-container mounts. An example layout is
`~/Documents/tollchat-eval-holdout/{5.0.0,runs/}`. Separation is procedural: the
coding agent must not read those files. These examples grant no paid budget.

```bash
uv run python -m eval.corpus validate --holdout /absolute/external/5.0.0
uv run python -m eval.corpus freeze --corpus /absolute/external/5.0.0 --split holdout --version 5.0.0
uv run python -m eval.golden --corpus /absolute/external/5.0.0
uv run python -m eval.golden_run calibrate --corpus /absolute/external/5.0.0 \
  --output /absolute/external/runs/calibration-N --budget-usd 25
uv run python -m eval.golden_actor_check --corpus /absolute/external/5.0.0 \
  --output /absolute/external/runs/actor-check-N --budget-usd 25 \
  --prior-run /absolute/external/runs/calibration-N
uv run python -m eval.golden_run run --corpus /absolute/external/5.0.0 \
  --output /absolute/external/runs/checkpoint-N --budget-usd 25 \
  --calibration /absolute/external/runs/calibration-N \
  --prior-run /absolute/external/runs/actor-check-N
uv run python -m eval.golden_run aggregate --output /absolute/external/runs/checkpoint-N
```

Record actual input approval in the corpus's `review.json` and calibration approval
in the calibration directory's `review.json` before `run`. Both bind exact digests.
Omit `--prior-run` only at the start of a new authorized spending chain; otherwise
chain all public and hidden work to the immediately preceding run. Holdout
references are included in calibration and passing scripted actor checks. Public
and hidden calibration evidence is not interchangeable.

Holdout console output contains aggregate status only. Diagnostics, including
tracebacks and case progress, go to a sibling `.RUN_NAME.console.log` on the host.
Application JSON includes source/run identities, corpus and measurement digests,
repetitions, expected slots, pass/fail/inconclusive/missing counts, overall rate,
completeness and cost. It excludes case IDs, category breakdowns, conversation
text, routes, reference answers and paths. Export recalculates totals from the
private journal rather than trusting a copied report.

Return only that JSON to the coding agent. Repeated checkpoints are allowed within
authorized budgets. Pair each committed candidate's training and hidden scores
under the same evaluator, settings and repetitions. Record the rates and
`100 × (training rate − holdout rate)` in percentage points in the experiment
journal. Mark incomplete measurements instead of claiming a comparable gap.
Keep the suite fixed while tracking the gap; corpus or evaluator repairs start a
new series. Repeated aggregate feedback can still influence tuning, so this is a
hidden diagnostic, not fully blind accuracy or a production gate.

Keep raw artifacts in ignored `eval/private/` or the existing private workflow
store. Append summaries to the appropriate Monday-start page in `eval/journal/`
and link new weeks from [the journal index](EXPERIMENT_JOURNAL.md).
Commit only an experiment-journal summary: purpose, relevant versions,
aggregate counts and denominators, actor/judge limitations, cost, and the decision.
Do not publish full transcripts, per-round documents, generated review pages,
receipts, or copied archives unless Ryan explicitly requests those artifacts.
A temporary review page does not imply permission to commit its data.

Historical output removed from the working tree is recoverable at Git commit
`19fb7faed8fee2c286bf71d6e2f92f27fe33e352`. Recover it into ignored private storage
or use its recorded source revision for reproduction; do not restore it as an
active corpus or reuse a historical budget as new spending authorization.

The private holdout environment and qualification gate are retired. Production
uses the [existing delivery checks](../RUNBOOK.md#production-release-checks); development
baselines do not establish independently measured agent accuracy.

The runner and comparison helpers derive execution slots from the recorded
`trials_per_case` (1 or 3). The active development contract uses one repetition;
three repetitions are available for explicitly authorized campaigns and historical
development contracts.
Single-pass reports use all expected slots for overall pass rate and record
Pass³ fields as `null` (inapplicable). Missing slots remain in the denominator;
inconclusives remain explicit. Comparisons reject missing or duplicate slots,
unsupported harness contracts, mismatched repetition counts, and inconsistent
aggregate usage. Historical three-trial reports retain their recorded scoring rules.
The repetition contract requires fresh reviewed calibration before paid execution.

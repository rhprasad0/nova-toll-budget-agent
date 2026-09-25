# Running the frozen golden corpus

The current development corpus has **100 cases and 146 calibration references**.
Application baselines run three trials per case. Actors have up to five delivered
user turns. The application, actor, judge settings, input hashes, and source commit
are recorded in each run. See [authoring](GOLDEN_EVAL_SPEC.md) for the contract and
[the experiment journal](EXPERIMENT_JOURNAL.md) for results and prior decisions.

All golden judges, including the scripted actor-check assessment, use
`gpt-6-luna` with high reasoning and an 8,192-token output ceiling. Application
generation remains low/2,048 and actor generation medium/2,048 on the same model.
Run identities and cost reservations record those role-specific limits. Legacy
scheduled evaluation settings are separate from this golden contract.

## Description-edit contract

Contract 3.3.6 / harness 2.3.6 uses `literal-input-prose-v1`. The corpus hashes
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
Corpus review and fresh matching calibration are required before the next climb;
never transfer prior approvals or regenerate a candidate's corpus manifest.

## Scoring and preparation

Pass³ is successful three-trial cases divided by **all 100 cases**. Missing,
failed, and inconclusive trials cannot make a case successful. Historical report
rendering follows the recorded harness version; cross-contract comparisons fail.
Development promotion requires strict overall-pass-rate improvement: successful
trials divided by all **300 expected trials**, including inconclusives in the
denominator. Keep inconclusive nonincrease, comparable Grounding/Rules
nonworsening, and independent material-regression review. Pass³ and paired deltas
are diagnostics. Rank eligible candidates by overall pass rate, fewer changed
lines, then A. Harness 2.2.0 retains its historical pass³ promotion rule.

Optimize using development cases only. The separate blind production standard is
at least 240/300 successful trials, with valid simulations and complete judgments;
80% on this exposed set cannot qualify production. Keep holdout cases and feedback
out of candidate search. The separate gate work does not increase the development
spending authorization.

Judges return cited unmet requirements; an empty list determines success.
The stored `passed`/`evidence` interface remains stable. Calibration must still
check semantic errors; explanations are never regex-relabelled.

For a preparation repeatability check, the sequence is two full-reference calibrations with
independent review, one full scripted actor check, then two identical application
runs (100 cases × 3 trials, 16 workers). Compare repeatability and criterion
variation; designate the second application run by position as the next baseline,
never by score. Reuse only with unchanged application/evaluation identities and
verified development migration/catalog parity after human-reviewed merge.

Chain preparation from the last accounted run using the user-authorized cumulative
ceiling. Admit each complete run only when its estimate with headroom fits, reserving
the agreed search and confirmation budget. Record amounts and decisions in the
private ledger and append-only experiment journal.
Stop on unknown usage, infrastructure failure, unresolved material grading
ambiguity or insufficient budget. Do not repeat runs to obtain passing results. Candidate
search belongs in a separate PR and starts only after the deployment parity gate.

## Execution

Run from `v2/`. Offline validation needs no model calls:

```bash
uv run python -m eval.golden
```

Paid work requires user authorization for a stated budget or explicitly uncapped
spending, and a clean committed checkout. Use a new ignored output directory for each run. These examples assume
an authorized $25 cumulative ceiling and 16 workers; they do not grant permission
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
judges all fixed development references; it does not generate new application or
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

The calibration must match the execution contract. `--cases` selects a partial
application diagnostic, which cannot represent a full baseline. Actor-invalid
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

Keep raw artifacts in ignored `eval/private/` or the existing private workflow
store. Commit only an experiment-journal summary: purpose, relevant versions,
aggregate counts and denominators, actor/judge limitations, cost, and the decision.
Do not publish full transcripts, per-round documents, generated review pages,
receipts, or copied archives unless Ryan explicitly requests those artifacts.
A temporary review page does not imply permission to commit its data.

Historical output removed from the working tree is recoverable at Git commit
`19fb7faed8fee2c286bf71d6e2f92f27fe33e352`. Recover it into ignored private storage
or use its recorded source revision for reproduction; do not restore it as an
active corpus or reuse a historical budget as new spending authorization.

The [production gate](GOLDEN_RELEASE.md) requires separate protected evidence and
approvals. A source-checkout development baseline cannot qualify a release.

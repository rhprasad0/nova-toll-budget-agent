# Running the frozen golden corpus

The current development corpus has **100 cases and 135 calibration references**.
Application baselines run three trials per case. Actors have up to five delivered
user turns. The application, actor, judge settings, input hashes, and source commit
are recorded in each run. See [authoring](GOLDEN_EVAL_SPEC.md) for the contract and
[the experiment journal](EXPERIMENT_JOURNAL.md) for results and prior decisions.

## Description-edit contract

Contract 3.1.1 / harness 2.1.1 uses `literal-input-prose-v1`. The corpus hashes
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

## Execution

Run from `v2/`. Offline validation needs no model calls:

```bash
uv run python -m eval.golden
```

Paid work requires user authorization within a stated budget and a clean committed
checkout. Use a new ignored output directory for each run. These examples assume
an authorized $25 cumulative ceiling and 16 workers; they do not grant permission
to spend or reset a previous ledger.

```bash
uv run python -m eval.golden_run calibrate \
  --output eval/private/calibration-N --budget-usd 25 --workers 16 \
  --prior-run eval/private/previous-run
```

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

# TollChat evaluation

**Approved locally authored suite 5.1.14:** 50 training and 10 shadow cases are
active, with 25 holdout cases stored externally. Harness 2.5.17 has an approved
aggregate calibration receipt. The 100-case development corpus
3.3.28 is retained unchanged as an [archival reference](archive/development-3.3.28/README.md).
Its recorded scores and reviews remain historical; it cannot run or seed fresh inputs.
The [experiment journal](EXPERIMENT_JOURNAL.md) preserves the findings and limitations.

## Frozen golden evaluation

The **50 training and 10 shadow cases** live under `eval/active/`, with **25 holdout
cases on an external host path**. Use the [authoring guide](AUTHORING.md) and
[coverage contract](contract.json). Harness
2.5.17 searches the training split with **one trial per case and 16 workers**;
three trials require Ryan's explicit instruction. Shadow CI evaluates ten cases
once with a $2 per-job cap; scores are informational, incomplete measurements fail.
TollChat's application model, prompt, SOP and tools remain unchanged on `gpt-6-luna`.

From a clean committed `v2/` checkout, validate the approved inputs and readiness:

```bash
uv run python -m eval.corpus validate
uv run python -m eval.golden
uv run python -m eval.shadow_ci prepare --verify-runtime
```

For new inputs, `eval.corpus freeze` writes a per-split manifest and pending `review.json`; it never grants
approval. A real reviewer identifies the exact corpus digest and evidence.
Commit real public inputs, manifests and input reviews before paid execution.
Changed inputs or protected sources need a newer corpus version and input review.
Calibrate the harness across all three splits until Ryan approves it, then reuse
that approval for every split and future corpus versions. Only an evaluator
contract change requires a new combined harness calibration.
Keep public detailed evidence in ignored `eval/private/`. The factory container,
export/intake and handoff workflow are retired; existing private factory data stays
untouched. Synthetic regressions and archival cases cannot seed a fresh suite.

The [runner guide](GOLDEN_RUNNER.md) explains calibration reuse, paid execution,
accounting and comparison. The [authoring contract](GOLDEN_EVAL_SPEC.md) describes
required inputs. Scores use all expected training slots; inconclusives remain
visible. Strict gains require independent scope and material-regression review.
An exposed training score cannot qualify production. Production retains its
[delivery checks](../RUNBOOK.md#production-release-checks).

## External holdout

Keep holdout inputs and detailed evidence outside the repository, for example
`/home/ryan/Documents/tollchat-eval-holdout/5.0.0/`. The host operator explicitly
selects the corpus with `--corpus`; ordinary training commands never discover it.
Within an authorized eval-climb campaign, the parent can invoke the host runner
and use its aggregate-only feedback and validated training/holdout gap. Children
never access hidden evidence. See the
[host-side commands](GOLDEN_RUNNER.md#external-holdout-checkpoints).

**Separation is procedural:** the coding agent has host filesystem access but
must never inspect holdout files or detailed evidence. Pair visible and hidden
scores on the same committed candidate to track their gap. Repeated aggregate
feedback can still influence tuning; this is not fully blind accuracy.

## Shadow CI

CI validates the reviewed shadow inputs and `eval/harness-approval.json` without
credentials. The follow-on
`shadow-ci` workflow evaluates the exact successful CI candidate on all ten cases
through the reviewed `golden-evaluation` environment. Its definition runs from
protected `main`; PR CI remains credential-free.
Forks do not run paid evaluations. The $2 cap starts a new job-local spending
chain; CI reports the score without a pass-rate gate, and fails incomplete results.

The host exports the public receipt from the one approved combined calibration;
it contains hashes, runtime, planned split counts and approval provenance, with
no holdout cases or detailed evidence. Hosted CI selects its exact Python version
and architecture and verifies the evaluator before credentials. Activation also
requires administrator provisioning of the development-only SSM reader in
`infra/shadow_eval.tf`. Keep the existing main-only branch policy and required
review on `golden-evaluation`. This PR does not deploy that role or alter
environment settings. See the
[runner guide](GOLDEN_RUNNER.md#shadow-ci) for usage.

## Scheduled and live checks

The scheduled suite covers six current-toll scenarios with simulated users,
deterministic tool-call counts, and model-based completeness and correctness
judges. Direct and annual suites provide focused workflow regressions. The
[dashboard runbook](../runbooks/eval-dashboard.md) describes published operational
results; those are separate from local experiment artifacts.

Live checks require the configured development AWS profile, SSM credentials,
private database connectivity, and CA bundle from the
[local setup](../README.md#local-agent-console). Use the matching I-95 window;
annual checks are independent of lane direction. Run only authorized live work:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
  uv run python eval/run_evaluation.py --window i95_southbound --suite scheduled
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
  uv run python eval/run_evaluation.py --window i95_northbound --suite direct
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll-dev \
  uv run python eval/run_evaluation.py --window all --suite annual
```

Results reflect the recorded cases, tools, and judges. Actor failures and missing
measurements are inconclusive; sampled improvements are not whole-agent accuracy.

## Focused batch grounding check

[ballpark_hallucination_batch.py](ballpark_hallucination_batch.py) prepares,
submits, retrieves, and grades the frozen annual-ballpark Batch experiment.
Its canonical input is [ballpark-hallucination-cases.jsonl](ballpark-hallucination-cases.jsonl);
generated inputs and outputs belong in `eval/private/`. Inspect preparation and
obtain authorization before submitting paid work. The
[journal summary](journal/2026-09-21.md#annual-ballpark-grounding-experiment)
records the result and limits.

Historical golden demonstrations and calibrations are summarized in the
[experiment journal](journal/2026-09-14.md#september-20-golden-demonstration-and-calibration).
Exact approval records and release policies retain their original identities.
Offline regression checks use focused synthetic inputs; historical run archives
remain recoverable through the Git commit linked in the journal.

The runner and comparison helpers derive execution slots from the recorded
`trials_per_case` (1 or 3). The active training execution defaults to one repetition;
three repetitions are available for explicitly authorized campaigns and historical
development contracts.
Single-pass reports use all expected slots for overall pass rate and record
Pass³ fields as `null` (inapplicable). Missing slots remain in the denominator;
inconclusives remain explicit. Comparisons reject missing or duplicate slots,
unsupported harness contracts, mismatched repetition counts, and inconsistent
aggregate usage. Historical three-trial reports retain their recorded scoring rules.
Paid execution requires matching human-reviewed harness calibration.

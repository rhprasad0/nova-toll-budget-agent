# TollChat evaluation

**Awaiting the first real factory export.** The 100-case development corpus
3.3.28 is retained unchanged as an [archival reference](archive/development-3.3.28/README.md).
Its recorded scores and reviews remain historical; it cannot run or seed fresh inputs.
The [experiment journal](EXPERIMENT_JOURNAL.md) preserves the findings and limitations.

## Frozen golden evaluation

The [evaluation factory](factory/README.md) authors 50 training, 25 private holdout,
and 10 public shadow cases. Intake receives only training and shadow. Harness
2.4.0 searches the training split with **one trial per case and 16 workers**;
three trials require Ryan's explicit instruction. Shadow CI is deferred.
TollChat remains on `gpt-6-luna`, with the existing actor, judges and grading rules.

From `v2/`, check readiness or receive a trusted factory export offline:

```bash
uv run python -m eval.golden --allow-uninitialized
uv run python -m eval.intake validate /absolute/public-suite.zip
uv run python -m eval.intake install /absolute/public-suite.zip
uv run python -m eval.golden
```

Synthetic exports support `validate --smoke` only; they cannot activate a set.
Install refuses overwrites, validates both public splits, and keeps calibration
rows and actor-check evidence in ignored `eval/private/intake/`. Commit the real
executable inputs and their small identity manifest before paid execution.
No fresh inputs are checked in by this preparation change.

The [runner guide](GOLDEN_RUNNER.md) explains calibration reuse, paid execution,
accounting and comparison. The [authoring contract](GOLDEN_EVAL_SPEC.md) describes
required inputs. Scores use all expected training slots; inconclusives remain
visible. Strict gains require independent scope and material-regression review.
An exposed training score cannot qualify production. Production retains its
[delivery checks](../RUNBOOK.md#production-release-checks).

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
Paid execution requires matching approved factory evidence or fresh local calibration.

# TollChat evaluation

**Current contract: 3.3.16 / harness 2.3.16.** Future development climbs optimize
overall pass rate: successful trials out of all 300 expected trials. Pass³ counts
three-success cases out of all 100 cases as a reliability diagnostic; inconclusives
never count as success. The separate 80% blind-holdout production standard does
not make a development score production qualification. The development
target is **270/300 (90%) on fresh final confirmation**, with all trials valid
and fully measured.
Peak pricing requires a peak qualification; off-peak labels are optional.
The authored references and SOP now match that rule. The harness checks
tool-contract failures mechanically and requires verified
assistant quotes for applicable schedule and vehicle-cost disclosures. Fresh
calibration is required; the three-run streak is incomplete.
Earlier approvals do not transfer.
Before search, complete the runner guide's preparation and trajectory audit,
human-reviewed merge and verified development migration/catalog parity. See the
[experiment journal](EXPERIMENT_JOURNAL.md) for validation results and limits.

TollChat remains on `gpt-6-luna`. Preparation changes are separate from prompt
search. Shared `_PricingProfile` and output descriptions remain frozen under
`literal-input-prose-v1`. This development corpus cannot qualify production.

The [experiment journal](EXPERIMENT_JOURNAL.md) is the record of what was tried,
results, limitations, costs, and decisions. Publish summaries there; keep granular
output in ignored `eval/private/` or the existing private workflow store.

## Frozen golden evaluation

- [Authoring contract](GOLDEN_EVAL_SPEC.md): 100 realistic development cases,
  147 labeled references, 107 synthetic fixtures, and five-turn actors.
- [Private authoring kit](HOLDOUT_AUTHORING.md): public instructions and an offline
  validator for independently authored private cases; no held-out data is included.
- [Runner](GOLDEN_RUNNER.md): authorized calibration, three-trial application
  baselines, complete cost accounting, and offline report reproduction.
- [Production gate](GOLDEN_RELEASE.md): 100 independently authored private cases,
  three trials each, and an 80% admission floor. Signed aggregate evidence and
  protected review bind the exact artifact. Activation awaits the external evaluator;
  development scores and historical approvals cannot qualify production.

From `v2/`, validate without model calls:

```bash
uv run python -m eval.golden
```

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
[journal summary](EXPERIMENT_JOURNAL.md#annual-ballpark-grounding-experiment)
records the result and limits.

Historical golden demonstrations and calibrations are summarized in the
[experiment journal](EXPERIMENT_JOURNAL.md#legacy-golden-demonstration-and-calibrations).
Exact approval records and release policies retain their original identities.
Offline regression checks use focused synthetic inputs; historical run archives
remain recoverable through the Git commit linked in the journal.

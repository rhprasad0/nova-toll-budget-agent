# TollChat evaluation

**Current contract: 3.3.28 / harness 2.3.28; calibration review pending.** Development climbs run 100 cases
once and optimize successful trials divided by all 100 slots. Fully measured
inconclusives stay visible; pass³ is inapplicable. Strict score gains require
independent review for material regressions. **90/100 is a soft milestone**;
blind production qualification stays separate.
Peak pricing requires a peak qualification; off-peak labels are optional.
The authored references and SOP now match that rule. The harness checks
tool-contract failures mechanically and requires verified
assistant line IDs for applicable schedule and vehicle-cost disclosures. Code
resolves IDs to the original text, preserving Markdown and assistant-only
provenance. The judge selects all lines needed to convey the requirement;
unknown IDs make the measurement unusable. Replay failures identify differing
fields. Missing disclosures and contradictory claims still fail their rubrics.
Calibration review records material disagreements without requiring perfect
label agreement. Optional closing offers do not require actor replies after
the profile goal is complete. Generic annual-day arithmetic does not replace
a supplied count, and conventional percentile names may describe equal amounts.
Actual unapproved counts, unresolved required replies and false inequalities still fail. See the experiment journal for accepted limitations.
Before search, complete the runner guide's preparation and trajectory audit,
using one calibration, independent review, one actor check and one baseline.
Frozen replay does not require deployment parity. See the
[experiment journal](EXPERIMENT_JOURNAL.md) for validation results and limits.

TollChat remains on `gpt-6-luna`. Preparation changes are separate from prompt
search. Shared `_PricingProfile` and output descriptions remain frozen under
`literal-input-prose-v1`. This development corpus cannot qualify production.

The [experiment journal](EXPERIMENT_JOURNAL.md) is the record of what was tried,
results, limitations, costs, and decisions. Publish summaries there; keep granular
output in ignored `eval/private/` or the existing private workflow store.

## Frozen golden evaluation

- [Authoring contract](GOLDEN_EVAL_SPEC.md): 100 realistic development cases,
  176 labeled references, 107 synthetic fixtures, and five-turn actors.
- [Runner](GOLDEN_RUNNER.md): authorized calibration, single-pass development application
  baselines, complete cost accounting, and offline report reproduction.

The private holdout tooling and production qualification gate are retired. A
replacement container and evaluation approach will be designed separately.
Production delivery uses the existing [release checks](../RUNBOOK.md#production-release-checks).
Development scores do not establish independent agent accuracy.

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

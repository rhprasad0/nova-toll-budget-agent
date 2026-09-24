# TollChat experiment journal

**IMPORTANT — permanent experiment history. Do not delete, truncate, replace,
or remove this file during cleanup without Ryan's explicit approval.** This is
the durable ledger of experiments, results and decisions, not disposable test
output. Append new experiments and dated corrections; preserve earlier findings
and link their supporting evidence.

## 2026-09-24 — Adopt descriptions + reordered SOP (experiment C)

**Decision:** Ryan requested that the main TollChat agent use C's tool/parameter
descriptions and reordered SOP, and authorized a PR stacked on
[#592](https://github.com/rhprasad0/nova-toll-budget-agent/pull/592).
The journal, completed comparison and adoption decision are published in
[#593](https://github.com/rhprasad0/nova-toll-budget-agent/pull/593), stacked on #592.
This supersedes the earlier recommendation to retain A pending grounding review;
it does not change any recorded grade or establish production qualification.

### Question and controlled changes

Does clearer tool documentation, alone or combined with reorganized instructions,
improve the existing `gpt-6-luna` agent? All arms used the same model settings,
frozen cases, tool behavior and calibrated 2.0.8 judging semantics.

| Arm | Change | Frozen application/evaluator commit |
| --- | --- | --- |
| A | Original descriptions and SOP | `d837bed` |
| B | Revised tool and parameter descriptions; original SOP | `451a789` |
| C | B descriptions plus reordered SOP and section headings | `1ed79e69babe340814442406c7764c628d9e7501` |

C preserves every original instruction paragraph exactly once. Description
changes preserve the non-description tool contracts. No model or tool-execution
behavior changed, and no wording was revised after diagnostics or reserved-case
inspection. The comparison began from `8a82e7399dd435e57464f5cbf18f1597aeb86525`.

### Calibration and experiment sequence

Calibration evolved through 2.0.5–2.0.8 after human review, including Ryan's
preference for lenient semantic judgments rather than exact wording. The final
2.0.8 calibration checked 286 development references per variant group: A had
5 label disagreements and B/C had 9; there were no measurement failures. Both
matched all five semantic controls, and no authored failing reference passed all
three criteria. Residual judge errors were retained and documented.

Ryan approved the exact matching calibrations before application testing. See
[approval records](evidence/prompt-experiment/calibration-approvals-2.0.8.json),
[2.0.8 review](evidence/prompt-experiment/CALIBRATION-REVIEW-2.0.8.md), and earlier
[2.0.5](evidence/prompt-experiment/CALIBRATION-REVIEW.md),
[2.0.6](evidence/prompt-experiment/CALIBRATION-REVIEW-2.0.6.md),
[2.0.7](evidence/prompt-experiment/CALIBRATION-REVIEW-2.0.7.md) reviews.

Diagnostics used 26 development cases, three trials each. Both candidates gained
only 1.5 paired percentage points, with uncertainty spanning zero, so all prompts
remained frozen for the full 200-case run: 160 development and 40 public reserved
cases, three trials each (600 trial slots per arm).

### Results

| Measure | A | B | C |
| --- | --- | --- | --- |
| Diagnostic passed / scored | 55 / 75 (73.3%) | 57 / 73 (78.1%) | 58 / 75 (77.3%) |
| Full passed / scored | 402 / 582 (69.1%) | 424 / 585 (72.5%) | **454 / 595 (76.3%)** |
| Full actor-inconclusive trials | 18 | 15 | 5 |
| Cases passing all three trials | 95 / 200 | 101 / 200 | 111 / 200 |
| Grounding flags / scored trials | 21 / 582 | 23 / 585 | 25 / 595 |
| Rules flags / scored trials | 63 / 582 | 60 / 585 | 57 / 595 |
| Development passed / scored | 324 / 464 | 348 / 466 | 371 / 477 |
| Reserved passed / scored | 78 / 118 | 76 / 119 | 83 / 118 |
| Full-run cost including interruption | $1.760913 | $1.780818 | $1.787713 |

| Paired comparison | Complete paired cases | Difference | 95% interval |
| --- | ---: | ---: | --- |
| B minus A, all | 180 | +2.4 pp | -1.8 to +6.8 pp |
| C minus A, all | 182 | **+6.4 pp** | **+2.0 to +11.5 pp** |
| B minus A, reserved | 38 | -2.6 pp | -12.2 to +6.5 pp |
| C minus A, reserved | 37 | +1.8 pp | -10.5 to +13.7 pp |

Pairs require three valid scored trials in both arms; 95% intervals resample
scenario groups (10,000 samples, seed 360). Inconclusive trials stay in evidence
and are excluded from scored rates. The reserved result remains inconclusive.

C reduced wrong-argument flags from 38 to 29 and missing-call flags from 42 to
34. The closure-proof case passed once in C and never in A/B; endpoint-ID
rejections prevented the other trials from reaching the proof follow-up. C
honored withdrawn consent in all three relevant trials. Grounding flags increased
and include both concrete errors (observed zero tolls described as missing data;
239.5 commute days changed to 239) and potentially strict wording judgments.
Known signed-money false failures and judge disagreements remain in all reported
scores. Adoption is a user decision informed by this evidence, not a claim that
these limitations are resolved.

### Recovery, cost and provenance

AWS SSO expired during B, causing 42 infrastructure failures; the original C run
then produced 600 authentication failures and no model calls. After login renewal,
only those infrastructure-failed slots were recovered in separate journals.
No scored or actor-inconclusive trials were retried. A/B used four workers; Ryan
authorized eight for C recovery on the unchanged calibrated runner. The provider
usage tier also changed, limiting latency comparisons. No infrastructure failures
or unknown model usage remained after recovery.

**Total experiment spending: $9.646136 of the $15 cumulative ceiling**, including
all calibration rounds, diagnostics, original runs and recovery. Evidence hashes,
usage completeness, spending lineage and byte-for-byte report reproduction were
verified; archived recovery evidence passed secret scanning.

- [Detailed results and failure examples](evidence/prompt-experiment/RESULTS.md)
- [Full comparison and original/recovery evidence links](evidence/prompt-experiment/FULL-COMPARISON.md)
- [Diagnostic comparison](evidence/prompt-experiment/DIAGNOSTIC-COMPARISON.md)
- [Reproducible comparison script](evidence/prompt-experiment/compare_runs.py)

### Application adoption and subsequent runner change

The normal agent already loads the exact C files inherited from #592:
[SOP](../agent-sops/nova-toll-pricing-assistant.sop.md),
[current-price descriptions](../agent_tools/current_price_domain.py), and
[annual descriptions](../agent_tools/get_annual_toll_ballpark.py).
[Agent construction](../agent/toll_agent.py) uses that SOP and registers those
tools directly; no experiment override or activation switch is needed. The
selected versions are prompt **2.3.8**, current-price contract **1.5.1**, annual
contract **3.0.1**, with model **gpt-6-luna** unchanged. Main receives them through
the reviewed PR stack; this entry does not authorize merging or deployment.

After the frozen experiment, commit `fcaf03f` expanded the local runner to 1–16
workers while preserving the default/protected policy of four. Its source and
corpus hashes changed, so future application runs require fresh matching
calibration and review. No calibration approval transfers automatically and no
new paid calibration was run. Results were committed in `421bd36`; the expanded
runner and recovery comparison passed 49 relevant offline tests.

## 2026-09-24 — Retire the active golden corpus

Ryan requested documenting the existing 200 cases (160 development + 40 public
reserved) before deleting the active set, in a PR stacked on #593. The future
target is 100 newly authored development cases; another agent will independently
generate the holdout to preserve integrity. Both generation tasks are out of scope
for retirement. The [recreation guide](GOLDEN_EVAL_SPEC.md) preserves the design
and pins the complete original corpus before removal.

The change uses two ordered commits: documentation, then deletion. Preserve the
harness, this journal, and historical evidence; retain only regression-test inputs
needed by offline checks. With no active corpus, golden runs and release
qualification must remain blocked. No old score, reference, or approval becomes
evidence for the future set, and this decision does not alter the experiment C
adoption or its recorded results.

## 2026-09-24 — Author the 100-case development replacement

Ryan requested implementing the replacement plan for ordinary passenger-car use,
without unusual vehicle classes, adversarial prompts, or obscure boundary probes.
Corpus **3.0.0** contains 100 newly authored development cases: 40 current-price,
55 annual-affordability, and five explicit workflow transitions. The
[review catalog](golden/REVIEW.md) contains the allocation, actor briefs, expected
behaviors, fixture links, and proposed passing transcripts. Its 107 synthetic
fixtures support 100 passing reference proposals and 20 labeled negative controls.
The public point catalog was rebuilt from current committed Oracle sources
(220 points); the retired test-only snapshot remains unchanged.

The active contract now validates the new allocation and rejects legacy test data
as an active corpus. Comparison against the pinned retired 200 found no reused IDs
or identical normalized prompts; the catalog records the limits and manual review
of that comparison. No independent holdout contents were authored or inspected.
The application model, prompt, tool implementations, historical results, and
protected policy are unchanged. A future three-trial run would have 300 slots;
no new application performance measurement is claimed.

Validation: **180 relevant offline tests passed**, including corpus replay and
financial reconciliation, retirement isolation, runner/reporting, historical
baselines, and release-gate checks. Ruff lint/format, strict Pyright on changed
Python files, Actionlint on the CI workflow, manifest validation, and whitespace
checks passed. The corpus digest is
`e68d04094648deeb7d1b40c01a9e6d5fe4ec827077c2e1e6d000f889340614be`.
Human corpus review and paid calibration remain pending. No paid evaluation was
run and no historical approval transfers. Application runs require corpus approval;
production qualification explicitly rejects the development-only corpus before
AWS access, including when supplied a historical approved policy.

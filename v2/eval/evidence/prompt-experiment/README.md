# Prompt experiment: A / B / C

Prepared from `8a82e7399dd435e57464f5cbf18f1597aeb86525`. Local experiment only;
PR #592 contains the preparation; this comparison is a layer above it.
No deployment or production qualification. Combined paid-run ceiling: **$15**.

**Calibration 2.0.8 reviewed; diagnostic comparison completed; full comparison paused for AWS SSO renewal.** Both runs checked
286 development references with no measurement failures. A has 5 label disagreements
and B/C has 9, versus 6 and 10 under 2.0.7. The complete-history coverage-count
false failures are gone. Both match all five semantic controls and the natural
salary-confirmation case; neither passes an authored failing reference across all
three criteria. See the [2.0.8 review packet](CALIBRATION-REVIEW-2.0.8.md) for exact
evidence, transcript-reading errors and remaining interpretation disagreements.

This round cost $0.915263. Cumulative spending is **$3.609137 of $15**, leaving
$11.390863. Historical [2.0.5](CALIBRATION-REVIEW.md),
[2.0.6](CALIBRATION-REVIEW-2.0.6.md) and [2.0.7](CALIBRATION-REVIEW-2.0.7.md)
evidence remains unchanged. Ryan authorized application comparisons after reviewing
these results; the exact approvals are in [calibration-approvals-2.0.8.json](calibration-approvals-2.0.8.json).

The [diagnostic comparison](DIAGNOSTIC-COMPARISON.md) covers 26 development cases
with three trials per arm. Both candidates gain only 1.5 percentage points on paired
complete cases, with intervals spanning losses and gains. Keep all prompts frozen
for the full 200-case evaluation; no diagnostic-driven wording revision is justified.

The [current results and recovery instructions](RESULTS.md) retain the completed A
run and interrupted B/C runs. Total spending is $7.704711 of $15. Renew the
development AWS SSO session before infrastructure-only recovery; no winner is established.

| Arm | Branch / worktree | Change |
| --- | --- | --- |
| A | `experiment/prompt-a` / `.worktrees/prompt-experiment-a` | Original prompt and descriptions |
| B | `experiment/prompt-b` / `.worktrees/prompt-experiment-b` | Tool and parameter descriptions only |
| C | `experiment/prompt-c` / `.worktrees/prompt-experiment-c` | B descriptions plus reordered SOP |

C changes section headings and paragraph order, preserving each original instruction
paragraph exactly once. Tool versions advance to current-price 1.5.1 and annual
3.0.1 in B/C; C advances the prompt to 2.3.8. Runtime settings stay unchanged.

## Calibration and isolation

The existing corpus identity hashes tool source files. B/C therefore need their
own matching calibration. Their manifests differ from A only in the two tool-source
hashes and the resulting corpus digest; all three arms share identical evaluator
semantics, case requirements, reference labels and fixtures under 2.0.8. The
latest revision only aligns complete-history comparison judging with the unchanged
SOP. Cases, references, labels, actor profiles and application variants are unchanged
from 2.0.7.
Do not weaken this identity gate or copy an approval between calibrations.

Both matching calibrations have user approval for this bounded local experiment.
The historical 2.0.3 baseline and 2.0.4 calibration are retained unchanged.

From C's `v2/`, run the offline cross-worktree check:

```bash
uv run python eval/evidence/prompt-experiment/check.py
```

`diagnostic-cases.json` freezes 26 development cases: per family, two historical
scored failures and one all-three-trials passing control, sorted by case ID;
remaining development cases fill missing categories. The mixed family has only
two development cases. Historical grades select diagnostics, not candidate winners.

## Application execution after human calibration review

Run from clean committed checkouts, with `AWS_PROFILE=nova-toll-dev` and
`AWS_DEFAULT_REGION=us-east-1`. Use the existing `eval.golden_run run` command:

- Diagnostics: A, B, then C, each with the same IDs from `diagnostic-cases.json`.
- Use `--workers 4 --budget-usd 15` and the matching approved `--calibration`.
- Every invocation uses `--prior-run` pointing to the immediately preceding run
  across **both calibrations and every arm**, preserving cumulative spending.
- Use a fresh ignored `eval/private/prompt-experiment/` output directory per run.
- Retain all failures, inconclusive trials, unknown usage, and original journals.
  Do not retry until passing. Stop on the spending ceiling or unknown usage.
- After diagnostics, allow at most one evidence-driven development-only wording
  revision. Preserve the initial candidate commits/results. If tool-source changes
  invalidate calibration, obtain matching reviewed calibration within the same cap.
- Freeze final B/C before full evaluation. Run A, B, C without `--cases`:
  200 cases × 3 trials per arm. Do not tune using reserved cases.

Report diagnostic and full-run results separately. Compare development and reserved
partitions, family success, tool selection/arguments, consent, grounding, completeness,
repeatability, latency, tokens, and cost per success. Use paired case-level comparisons
with scenario-group uncertainty; public reserved cases are not a secret holdout.
Inspect failures before recommending a winner. Retain A or report inconclusive when
gains are uncertain or candidates introduce consent/grounding regressions.

No release artifact is being selected: deployment manifests/build hashes must be
refreshed and verified if a winning candidate is later authorized for delivery.

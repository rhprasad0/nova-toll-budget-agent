# Prompt experiment: A / B / C

Prepared from `8a82e7399dd435e57464f5cbf18f1597aeb86525`. Local experiment only;
no push, deployment, or production qualification. Combined paid-run ceiling: **$15**.

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
own matching calibration, even though no grader, fixture, case, label, validation,
or tool behavior changed. Their manifests differ from A only in the two tool-source
hashes and the resulting corpus digest; evaluator semantics remain 2.0.5.
Do not weaken this identity gate or copy an approval between calibrations.

Both fresh calibrations require human review before application execution.
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

# Golden-200 calibration review

**Two authorized calibration runs completed. Human approval remains pending.** Both evaluated the same 274 development references (272 with application labels and two actor-invalid probes); 52 references from the 40 reserved cases were excluded. No application-agent trials or fresh ActorSimulator trials were run.

Estimated total cost: **$1.493836** against the combined $25 ceiling. All 1,644 model calls recorded usage; both runs have zero failed or missing measurements. These are prices from the pinned runner, not a billing reconciliation.

The final corpus is **2.0.2**. It corrects one definite legacy Grounding-label error found in run 2: `greenway:7:exit:EB` identifies Loudoun County Parkway, while the negative response calls it Route 7. The raw run-2 report retains the original expected label and measured mismatch. The [post-run correction ledger](post-calibration-correction.json) records that change. Final harness **2.0.2** also fixes packaged-agent model-budget exhaustion being misclassified as infrastructure; judge rubrics and model settings are unchanged from run 2. Because the exact contract changed, these runs do **not** qualify the final exact contract for application execution; fresh authorized calibration and human review remain required.

## Recorded agreement

Agreement is against the proposed labels frozen for each run, not independently established judge accuracy. The labels and context changed between runs, so the table is not a model-improvement comparison. Run 1 excludes nine application verdicts from three references the actor-assessment judge marked uncertain; those assessments remain visible. Run 2 excludes three application verdicts from one reference the judge marked actor-invalid; independent review disputes that classification.

| Run / contract | Outcome | Grounding | Rules | Actor validity | Estimated cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| [1 / 2.0.0](calibration-1/report.md) | 253/269 (94.1%) | 240/269 (89.2%) | 252/269 (93.7%) | 271/274 | $0.589670 |
| [2 / 2.0.1](calibration-2/report.md) | 265/271 (97.8%) | 262/271 (96.7%) | 259/271 (95.6%) | 273/274 | $0.904166 |

Each JSON report contains the complete confusion matrices, raw verdicts, evidence explanations, denominators and identities. Each journal retains calls and usage. Both archived reports reproduce byte for byte with the current renderer.

## What changed after run 1

The [correction ledger](corrections.json) records 26 proposed reference/label repairs and their reasons. They fix migrated positive variants, separate grounded facts from consent errors and omissions, repair an inaccurately authored rejected-call probe, and answer a missing comparison question. Historical verdicts were not rewritten.

The judge received the same public location catalog as the application, explicit SOP facts for scope redirection, modeled observation timestamps and proposed commute-day estimates, and the actual per-turn tool sequence. Fixed-reference mode distinguishes absent simulator records from an actual premature stop. Private actor facts remain unavailable to Grounding and Rules and are not consent for Outcome.

## Remaining findings

Independent agent review proposes the classifications below; the owner still needs to adjudicate them. See [all proposals](adjudication-proposals.json) for transcript-specific explanations.

| Classification | Criterion disagreements |
| --- | ---: |
| ambiguous | 1 |
| expected label defect | 1 |
| judge error | 26 |

The measured problems include hindsight about facts supplied after a call, missed financial-label/combined-cost claims, over-refusal on current-only capability, and excessive sensitivity to correct terminology. In particular, several Rules failures reject **“Additional gross salary needed to offset”**, the wording required by the [application SOP](../../../agent-sops/nova-toll-pricing-assistant.sop.md#L249). Those positive references are retained. One interpretation of “typical” with only one comparable week requires human adjudication.

The corpus is synthetic and public, the judgments share a model family, and outcome/actor assessment shares a model request. These calibrations do not establish fresh actor reliability, application success, or production quality. Mandatory replay checks catch some mistakes that an individual semantic judge misses, but they do not establish semantic judge accuracy. Neither calibration approval nor a production baseline is promoted.

## Every run-2 disagreement

| Case / reference | Criterion | Expected → measured | Proposed classification |
| --- | --- | --- | --- |
| `greenway-current` / `wrong-route` | grounding | True → False | expected label defect |
| `current-future-price` / `good` | grounding | True → False | judge error |
| `current-prefix-accept` / `good` | rules | True → False | judge error |
| `current-suffix-decline` / `good` | grounding | True → False | judge error |
| `current-open-southbound-prefix` / `good` | rules | True → False | judge error |
| `current-comparison-partial` / `partial-comparison-called-typical` | grounding | False → True | ambiguous |
| `current-comparison-partial` / `partial-comparison-called-typical` | rules | False → True | judge error |
| `annual-missing-schedule` / `missing-clarification` | outcome | False → True | judge error |
| `annual-missing-schedule` / `missing-clarification` | grounding | False → True | judge error |
| `annual-fixed` / `swapped-financial-label` | grounding | False → True | judge error |
| `annual-salary-range` / `good-income-choice-question` | outcome | False → True | judge error |
| `annual-salary-range` / `good-income-bullets` | outcome | False → True | judge error |
| `annual-missing-income-only` / `good` | rules | True → False | judge error |
| `annual-missing-outbound-only` / `good` | rules | True → False | judge error |
| `annual-missing-return-only` / `good` | rules | True → False | judge error |
| `annual-annual-income-known` / `good` | rules | True → False | judge error |
| `annual-zero-days-correction` / `good` | rules | True → False | judge error |
| `annual-correct-facts-while-clarifying` / `good` | rules | True → False | judge error |
| `annual-bare-leesburg-annual` / `good` | rules | True → False | judge error |
| `annual-outbound-correction-after-answer` / `good` | rules | True → False | judge error |
| `annual-missing-baseline-rounding` / `plausible-semantic-error` | outcome | False → True | judge error |
| `annual-missing-baseline-rounding` / `plausible-semantic-error` | grounding | False → True | judge error |
| `annual-middle-scenario-lead` / `plausible-semantic-error` | grounding | False → True | judge error |
| `annual-offer-decision-scope` / `good` | rules | True → False | judge error |
| `annual-facility-quantiles-not-additive` / `plausible-semantic-error` | grounding | False → True | judge error |
| `annual-no-paired-days` / `evaluator-pair-02-compact` | outcome | True → False | judge error |
| `annual-fixed` / `evaluator-pair-03-swapped-labels` | outcome | False → True | judge error |
| `annual-select-alternative` / `evaluator-actor-valid-missing-offer` | actor_validity | valid → invalid | judge error |

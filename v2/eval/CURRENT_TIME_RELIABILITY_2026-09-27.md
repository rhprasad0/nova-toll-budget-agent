# Reliability report for the retained 93-point candidate

**Measured September 27, 2026.** This is the current-time scope candidate selected at `8a747194`, with the same application content now carried by PR #629. The user requested three repetitions and a detailed comparison with former gating metrics. This report does not change the application or the active single-pass development workflow.

## Result

The fresh diagnostic produced **257 successful trials out of 300 (85.7%)**, and **68 cases out of 100 passed all three attempts (68% observed pass³)**. It misses the former 90% suite-success and 75% pass³ limits. Only 68 of the 100 critical cases satisfy the former 3/3 rule. Recorded cost and latency fall within the old numerical limits, but this source-checkout development run does not meet that policy's release-evidence requirements.

The earlier **93/100** was the selected search result, not a stable accuracy guarantee. Separate unchanged-prompt runs scored **91/100** and **82/100**. The new repetitions scored **82, 85 and 90**; they are all included. No slot was replaced, and no additional run was used to seek a passing result.

### Prior single-pass context

| Earlier observation, unchanged application prompts | Successes | Grounding violations | Rules violations | Inconclusives |
| --- | ---: | ---: | ---: | ---: |
| Selected search run | 93/100 | 1/100 | 7/100 | 0 |
| Fresh confirmation | 91/100 | 1/100 | 9/100 | 0 |
| Later renderer-exploration baseline, old output | 82/100 | 1/100 | 16/100 | 0 |

Each report has pass³ marked inapplicable. They provide context for variation, not a compatible three-repetition baseline or a pooled pass³ estimate. The 93-point result was selected during search, so it should not be treated as an unbiased estimate of repeated performance.

## What was measured

- **100 exposed development cases × 3 fresh attempts = 300 slots**, comprising 40 current-price, 55 annual and 5 mixed-workflow cases. All 100 cases are marked critical in corpus metadata; there are 99 scenario groups because one linked pair stays together for uncertainty calculations.
- **Application:** gpt-6-luna, low reasoning, 2,048 output tokens; prompt version 2.3.14, renderer 1.0.0. Actor: the same model, medium reasoning, 2,048 tokens. Judges: the same model, xhigh reasoning, 8,192 tokens.
- **Measurement:** corpus 3.3.27 / harness 2.3.27, 16 workers. Only the isolated diagnostic manifest's repetition count changed from one to three. All 100 rendered prompt hashes, tool schemas, model settings, actor inputs and evaluator sources match the retained candidate. The published application metadata differs from the original search commit; the evaluated behavior does not.
- **Preparation:** one matching 176-reference calibration. The previously audited actor check was reused because actor/profile/assessment inputs are unchanged. No additional application baseline was needed for this diagnostic.
- Frozen replay exercises application conversations and requested tool arguments. It does not execute live pricing, query deployed databases or establish production qualification.

## Success, consistency and completeness

| Metric | Observed result | Denominator / meaning |
| --- | ---: | --- |
| Overall success | **257/300 = 85.7%** | All planned slots; inconclusive counts as no success |
| Scored-trial success (`pass_at_1`) | **257/299 = 86.0%** | Valid, fully scored trials only |
| Outcome-criterion passes | 259/299 = 86.6% | Outcome alone; not joint success |
| Observed pass³ | **68/100 = 68.0%** | Cases with three valid successful trials |
| At least two successes | 92/100 | Consistency diagnostic |
| At least one success | 97/100 | Coverage diagnostic, not reliable completion |
| Scored failures | 42/300 | Valid trials that did not succeed |
| Actor-inconclusive | 1/300 = 0.3% | Retained in the overall denominator |
| Missing / duplicate / unexpected slots | 0 / 0 / 0 | All 300 attempts present exactly once |
| Actor validity | 299 valid; 1 invalid; 0 uncertain | Recorded actor assessment |
| Critical cases passing all three | 68/100 | All current development cases are critical |
| Critical trials with failed deterministic checks | 32/300 | Tool, argument, ordering and other mandatory checks |

All attempts completed and all started calls have known usage. The raw runner's `overall.complete` is false because one attempt is actor-inconclusive; this is not a missing or interrupted run. That attempt receives no success credit and prevents its case from counting toward pass³.

| Successes within a case | Cases |
| --- | ---: |
| 0 of 3 | 3 |
| 1 of 3 | 5 |
| 2 of 3 | 24 |
| 3 of 3 | 68 |

Thus **29 cases are intermittent**, three never succeed in this sample, and 68 succeed every time. Pass³ is measured directly from those triplets; it is not calculated by cubing 93% or the pooled success rate.

| Repetition slot | Successes / expected | Scored | Inconclusive |
| --- | ---: | ---: | ---: |
| 1 | 82/100 | 100 | 0 |
| 2 | 85/100 | 99 | 1 |
| 3 | 90/100 | 100 | 0 |

These labels identify unseeded attempt slots, not paired random seeds or three independently selected evaluation sets.

### Uncertainty

The canonical report leaves its success interval **null** because one slot is not scored. Supplemental descriptive intervals were computed separately for this report by resampling all **99 scenario groups**, preserving linked cases and all three slots, using **10,000 draws and seed 360**. Inconclusives retain zero success credit.

| Supplemental 95% percentile interval | Range |
| --- | ---: |
| Success across all planned slots | **80.7%–90.3%** |
| Cases passing all three attempts | **58.6%–77.0%** |

These intervals describe variation across this fixed, exposed collection of scenarios. They do not estimate unseen-production accuracy, repair grading errors or undo the selection bias in the original 93-point search result. They are not the runner's missing canonical interval. Historical gates compare observed point estimates, not whether a threshold lies within an interval.

## Former gates: numerical comparison and applicability

The old [approved policy 1.0.0](https://github.com/rhprasad0/nova-toll-budget-agent/blob/b91b4748f6ddb9d1dd2fb8d059a59f8e68d95df7/v2/eval/results/golden/policy-1.0.0.json#L5-L16) specified these absolute limits. Its [implementation](https://github.com/rhprasad0/nova-toll-budget-agent/blob/b91b4748f6ddb9d1dd2fb8d059a59f8e68d95df7/v2/eval/golden_baseline.py#L238-L289) also enforced exact artifact, configuration and approval requirements. The table applies the old numerical limits descriptively; it does not claim a release-gate decision under that historical contract.

| Former absolute requirement | This diagnostic | Numerical result |
| --- | --- | --- |
| Suite success ≥90% | 85.7% of all slots; 86.0% of scored slots | **Below** |
| Observed pass³ ≥75% | 68% | **Below** |
| Every critical case 3/3 | 68 of 100 meet it; 32 do not | **Not met** |
| Every noncritical case ≥2/3 | No noncritical cases | Not applicable |
| Run cost ≤$5 | $1.156873140 | Within limit |
| Application cost per successful trial ≤$0.05 | $0.001401865 | Within limit |
| Whole-trial p50 ≤30 seconds | 25.65 seconds | Within limit |
| Whole-trial p95 ≤60 seconds | 40.63 seconds | Within limit |
| Historical four-worker timing and exact packaged artifact | 16-worker source-checkout replay | Not the required evidence |
| At most one lost successful noncritical trial against baseline | No noncritical cases or compatible baseline | Not assessable |

The later three-trial development workflow used a **270/300 confirmed-success target**, with all slots valid and measured. This diagnostic is **13 successes below that target** and has one invalid actor slot. Its [relative promotion rules](https://github.com/rhprasad0/nova-toll-budget-agent/blob/53145d442c7149f7c3bb3508273a55b8f61d4955/v2/eval/GOLDEN_RUNNER.md#L36-L50) required strict overall-score improvement, no increase in inconclusives and nonworsening Grounding/Rules rates. Those relative checks are **not assessable here**: the earlier 93/91/82 runs have one repetition, and older three-repetition baselines use different judging contracts. We did not relabel or pool them into a compatible baseline.

The still-earlier pass³-first climb required a strict increase in pass³; that also needs a compatible baseline. In the later three-trial workflow pass³ and paired delta were diagnostics. Active single-pass .27 development makes pass³ inapplicable and treats violation/inconclusive increases as review signals. This requested three-trial diagnostic does not reactivate any former policy. There was no general absolute zero-Grounding/zero-Rules promotion requirement; the former critical-case rule effectively allowed no failed criterion on critical cases.

## Grounding, Rules and failure types

| Metric | Valid scored trials | All-attempt observation |
| --- | ---: | ---: |
| Grounding violations | **3/299 = 1.0%** | 3/300 = 1.0% |
| Rules violations | **39/299 = 13.0%** | 40/300 = 13.3%, including the inconclusive attempt |

Grounding covers unsupported factual or financial claims. Rules includes route arguments, workflow and consent; deterministic replay checks contribute to it. These counts overlap and must not be added to obtain failed trials. The one inconclusive attempt's Rules finding remains visible but is excluded from the valid-scored rate.

The runner's primary failure labels partition the 43 non-successful slots: **37 tool-use**, **3 Grounding**, **1 clarification**, **1 Outcome** and **1 actor-validity** failure. Labels describe the recorded failure stage, not necessarily 43 distinct causal mechanisms.

## Workflow and family results

| Workflow | Successes / slots | Cases passing all three |
| --- | ---: | ---: |
| Current toll | 93/120 = 77.5% | 23/40 = 57.5% |
| Annual affordability | 149/165 = 90.3% | 40/55 = 72.7% |
| Switching workflows | 15/15 = 100% | 5/5 = 100% |

| Family | Trial success | Observed pass³ | Inconclusives |
| --- | ---: | ---: | ---: |
| Complete current requests | 41/60 (68.3%) | 10/20 (50.0%) | 0 |
| Current clarification/state | 25/30 (83.3%) | 6/10 (60.0%) | 1 |
| Current evidence interpretation | 27/30 (90.0%) | 7/10 (70.0%) | 0 |
| Complete annual requests | 56/60 (93.3%) | 16/20 (80.0%) | 0 |
| Annual input collection | 40/45 (88.9%) | 11/15 (73.3%) | 0 |
| Annual route handling | 26/30 (86.7%) | 6/10 (60.0%) | 0 |
| Annual interpretation | 27/30 (90.0%) | 7/10 (70.0%) | 0 |
| Current/annual switching | 15/15 (100.0%) | 5/5 (100.0%) | 0 |

The largest deficit is in complete current-price requests: **19 of 60 attempts do not succeed**, and only half the cases pass all three. Annual answers have a higher pooled success rate, but 15 of 55 annual cases still fail at least once.

### Cases that did not pass all three

`P` = recorded success; `F` = scored failure; `I` = actor-inconclusive. Trial patterns are shown in slot order. The other 68 cases are P/P/P. These aggregate labels preserve original grades, including any limitations discussed below; no transcripts are published.

| Scenario | Successes | Slots 1 / 2 / 3 | Primary failure labels |
| --- | ---: | --- | --- |
| ryan road afternoon return | 0/3 | F / F / F | tool_use |
| spring hill to reston | 0/3 | F / F / F | tool_use |
| wiehle to fairfax parkway | 0/3 | F / F / F | tool_use |
| battlefield weekend return | 1/3 | P / F / F | tool_use |
| jones branch to gallows | 1/3 | F / F / P | tool_use |
| ryan road reverse commute | 1/3 | F / F / P | tool_use |
| supply missing weekdays | 1/3 | F / F / P | tool_use |
| tysons jones branch selection | 1/3 | F / I / P | actor_validity, tool_use |
| annual route cannot use current restart | 2/3 | F / P / P | grounding |
| assumed tax meaning | 2/3 | P / F / P | tool_use |
| belmont westbound pickup | 2/3 | F / P / P | tool_use |
| beltway endpoints together | 2/3 | P / P / F | tool_use |
| beltway to wiehle | 2/3 | P / P / F | tool_use |
| cancel unspecified destination | 2/3 | P / F / P | tool_use |
| collect salary before route alternatives | 2/3 | P / F / P | tool_use |
| collect weekdays then propose days | 2/3 | F / P / P | grounding |
| daily scenarios are not forecasts | 2/3 | F / P / P | tool_use |
| decline returned beltway entries | 2/3 | P / P / F | tool_use |
| five day ryan offer | 2/3 | P / P / F | tool_use |
| gallows to jones branch | 2/3 | P / F / P | tool_use |
| independent nearby office ramps | 2/3 | F / P / P | tool_use |
| modeled beltway estimate | 2/3 | P / F / P | tool_use |
| reston hybrid offer | 2/3 | P / P / F | tool_use |
| revise hybrid office requirement | 2/3 | P / F / P | tool_use |
| rising braddock quote | 2/3 | F / P / P | tool_use |
| stale beltway observation | 2/3 | F / P / P | grounding |
| supply both departure times | 2/3 | F / P / P | outcome |
| sycamore washington offer | 2/3 | P / P / F | tool_use |
| three day loudoun offer | 2/3 | F / P / P | tool_use |
| tolled distance scope | 2/3 | P / F / P | tool_use |
| washington corridor selection | 2/3 | F / P / P | clarification |
| westpark to braddock | 2/3 | F / P / P | tool_use |

## Cost, usage and latency

| Role | Calls | Input tokens | Output tokens | Recorded cost |
| --- | ---: | ---: | ---: | ---: |
| Agent | 709 | 24,286,556 | 162,405 | $0.360279240 |
| Actor | 390 | 554,725 | 29,982 | $0.070028300 |
| Judge | 900 | 22,688,706 | 638,960 | $0.726565600 |
| **Application diagnostic total** | **1,999** | **47,529,987** | **831,347** | **$1.156873140** |

Input-token totals include cached input; costs use the pinned rate schedule and recorded cache usage. Application cost per attempt is **$0.001200931**; application cost per successful trial is **$0.001401865**. These exclude actor/judge costs. Including all diagnostic roles, cost per successful trial is **$0.004501452**.

Whole-trial elapsed time, including actors and judges, is **25.65 seconds p50 / 40.63 seconds p95**. Summed application-model time per attempt is **5.53 seconds p50 / 10.72 seconds p95**; this excludes actors and judges and is not a measured production UI response time. There were **422 conversation turns** and **319 requested tool calls**.

Matching calibration added **$0.414687240** for 528 calls. This reporting task therefore cost **$1.571560380 across 2,527 calls**. Campaign spending is **$27.782659030** against the unchanged **$40.566444520** ceiling, leaving **$12.783785490**. Historical experiment costs are not included in this diagnostic's $5 comparison.

## Calibration and review limitations

The fresh calibration completed **176/176 references** with **512/516 criterion-label agreement**, **176/176 actor-label agreement** and **171/172 effective overall agreement** on valid references. All **51 negative controls** were rejected; 120 of 121 positives passed.

Three raw judge disagreements miss an incorrect whole-dollar rounding, but the independent arithmetic check still rejects it. The fourth is a known false Rules failure that invents user attribution for a rejected price quotation. Independent review reproduced all 176 money catalogs, including 15 classified occurrences across 13 nonempty catalogs. Original judgments remain unchanged. This was one reviewed calibration, not a perfect-agreement or repeated-clean-run claim.

Independent review reproduced the full runner summary, evidence digest, supplemental intervals and case histogram, and completed the fixed family sample, all failures and relevant violations, actor review, peak checks and money-catalog reproduction.

Most reviewed failures are substantive: wrong directions or endpoint roles, fabricated IDs, premature pricing, inaccurate timestamps, denial of historical price sources and continued questioning after cancellation. Three westbound scenarios never passed: Ryan Road afternoon return, Wiehle to Fairfax Parkway, and Spring Hill to Reston. All **17 returned peak components** were disclosed. All money catalogs reproduced; the sole suspect amount was correctly classified as a denial of a zero-dollar toll.

Three limitations need explicit treatment:

- **Tysons actor-inconclusive:** the recorded premature-stop judgment is debatable. The actor supplied its required destination choice and had no direction fact to answer the assistant's repeated unnecessary question. The application clearly did not complete the task. Scoring this as an application failure would leave 257/300 and 68/100 unchanged; the original inconclusive remains recorded.
- **Annual restart:** a Grounding failure reflects the known disagreement between the SOP's current-only restart restriction and returned tool metadata. It remains in the raw totals.
- **Historical dates:** one answer labels September 22 as the target-window end when that field is September 23, although available samples do end September 22. The explicit label mismatch is real but has limited practical impact.

No decision-changing measurement repair or additional run was required. This report preserves every grade and distinguishes uncertain attribution from demonstrated application errors. Independent agent review is not claimed as human adjudication.

## Provenance and verification

- Selected application content: `8a74719461f29417106b1c5221019cd048d1c1cd`; report branch starts from publication `2de13879f21a9aafb13e3e614e01831224b4a344` above PR #629.
- Diagnostic checkout: `5d7bce6da10b78fd6101846d9f1b489dd6f37fc0`. Only its manifest's repetition count changed. All 100 prompts and full tool-schema identities match the selected search run; renderer stays 1.0.0.
- Application evidence digest: `b2c00fad5ef55aef7211e1e97b82784f5b6816de21f5995eb9ebbb6b42600af0`. Calibration evidence digest: `c425a6f3c12e8bdb8ab1ae95a74238c452d393e7b0b2215f2a4341de1344809f`.
- Offline corpus validation, recorded-repetition/fixed-denominator checks and 15 comparison-helper tests passed. Report validation and separate slot/histogram/accounting calculations agree; missing, duplicate and unexpected slots are rejected.
- Raw transcripts, reports and detailed review notes remain in the private campaign archive. This requested aggregate report and the permanent [experiment journal](EXPERIMENT_JOURNAL.md) are published. The production qualification process remains separate; no holdout cases or feedback were used.

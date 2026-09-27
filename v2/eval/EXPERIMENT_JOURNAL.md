# TollChat experiment journal

**IMPORTANT — permanent experiment history. Do not delete, truncate, replace,
or remove this file during cleanup without Ryan's explicit approval.** This is
the durable ledger of experiments, results and decisions, not disposable test
output. Append new experiments and dated corrections; preserve material findings
and link supporting evidence when it is retained and useful.

## 2026-09-24 — Adopt descriptions + reordered SOP (experiment C)

The controlled A/B/C comparison tested tool descriptions and SOP order with `gpt-6-luna`, frozen cases, and calibrated evaluator 2.0.8; C scored 76.3% versus A’s 69.1%, with a paired gain of 6.4 points (95% interval 2.0–11.5), while reserved-case evidence remained inconclusive. Ryan chose C for adoption (prompt 2.3.8; tool contracts 1.5.1 and 3.0.1); known judge and grounding errors remain, and this is not production qualification. Total experiment spend was $9.646136 of the $15 ceiling.

| Arm | Change | Frozen application/evaluator commit |
| --- | --- | --- |
| A | Original descriptions and SOP | `d837bed` |
| B | Revised tool and parameter descriptions; original SOP | `451a789` |
| C | B descriptions plus reordered SOP and section headings | `1ed79e69babe340814442406c7764c628d9e7501` |

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


## 2026-09-24 — Retire the active golden corpus

The 200-case active corpus was documented for retirement; the future development set would contain 100 new cases, with an independently authored holdout kept separate. The recreation guide preserves the old design, and the harness and historical evidence remain available. With no active corpus, golden runs and release qualification stayed blocked; old scores and approvals do not transfer.

## 2026-09-24 — Author the 100-case development replacement

Corpus 3.0.0 introduced 100 new ordinary passenger-car cases (40 current-price, 55 annual-affordability, and five workflow transitions), supported by 107 synthetic fixtures. No prompts, tools, or application performance were changed or measured; the comparison found no reused IDs or identical normalized prompts against the retired set. Offline validation passed 180 relevant tests, while human review and paid calibration remained pending.

## 2026-09-24 — Calibrate the new 100-case development corpus

Calibration of corpus 3.0.0 measured all 120 references and 360 judge calls for $0.20523038: 347/360 labels agreed, with 13 disagreements across 12 references and no negative control passing all judges. These are judge/reference agreement results, not application accuracy; no application trial or holdout ran. Corpus and calibration approval remained pending human review.

## 2026-09-24 — Review correction: commute shorthand and five-turn actors

Review accepted generic home/work-area labels for supplied commute legs while continuing to prohibit invented addresses, facts, routes, or unconfirmed combinations. Corpus 3.0.1 / harness 2.0.9 raised the actor maximum to five delivered turns; minimum dialogue, references, fixtures, and application stayed unchanged. Matching calibration found nine disagreements across eight references (97.5% agreement); the corpus and calibration still required approval.

## 2026-09-24 — Make cases 79/80 more realistic

Corpus 3.0.2 revised the two split-itinerary cases to use a more plausible Springfield route, preserving their five-turn maximum and requiring confirmation before combining options. Only those cases and three references changed; the remaining 98 cases and application stayed frozen. Forty-two relevant tests passed. The matching calibration then completed 120 references and 360 calls with 354/360 label agreement for $0.19802250; six disagreements across five references remained, so human approval was still pending.

## 2026-09-24 — Adjudicate case 65 and clarify judge criteria

Ryan adjudicated case 65’s negative control to fail Outcome and Rules, and clarified evaluator criteria while preserving its transcript and the rest of the corpus. Corpus 3.0.3 / harness 2.0.10 calibration matched 358/360 labels for $0.20658857; two disagreements remained and approval was pending. No prior calibration or score was silently rewritten.

### 2026-09-24 — Authorized repeat of unchanged 3.0.3 calibration

The unchanged 3.0.3 calibration was repeated at Ryan’s direction: all 360/360 labels matched for $0.19815320, including the two disputed in the first run. The repeat informed approval of the current corpus/calibration and the first development baseline below; exposed-reference agreement does not establish unseen-case accuracy.

### 2026-09-24 — Approve current corpus/calibration and authorize baseline

The current corpus and calibration were approved for a development baseline, without production qualification. On the frozen 100-case set, the first run passed 156 trials, failed 131, and had 13 inconclusives; 33 cases passed all three trials. It cost $0.91475671. Actor validity and signed-money parsing errors motivated the measurement repair below; no verdict was rewritten.

## 2026-09-24 — Correct measurement defects before a second golden-100 baseline

Contract 3.0.4 / harness 2.0.11 corrected actor termination/validity handling, clarification checks, and signed-money parsing before a fresh baseline. The 100 cases, fixtures, application prompt/model, and prior results remained unchanged; 12 focused references were added to calibrate the corrections. The new measurement contract required fresh calibration, so prior approval did not transfer.

### 2026-09-24 — Actor preflight and calibration 6 completed

The live actor preflight passed 9/9 checks; calibration 6 matched 386/387 application labels and 132/132 actor labels, with no measurement failures or unknown usage. Cost was $0.22172372 for calibration and $2.16288238 cumulative including baseline 1 and preflight. One known Grounding disagreement remained, and the matching baseline was authorized under the corrected contract.

## 2026-09-24 — Second corrected golden-100 baseline completed

The corrected 3.0.4 / harness 2.0.11 baseline completed with 176/299 scored trials passing (58.9%) and one inconclusive; cost was $0.92992747, or $3.09280985 cumulative. Calibration 6 retained one Grounding disagreement, and application review remained pending. Changed grading and sampling prevent interpreting score differences as application improvement.

## 2026-09-24 — Relax annual Outcome detail after human review

After human review, contract 3.0.5 / harness 2.0.12 relaxed annual Outcome detail while retaining checks for requested figures and false source claims. Three case-52 transcripts were added as references without changing the application or prior measurements. Fresh calibration and a new baseline were authorized; no new model calls had yet occurred in this entry.

### 2026-09-24 — Calibration 7 and the third development baseline completed

Calibration 7 on 3.0.5 matched 389/396 application labels and 135/135 actor labels; baseline 3 then passed 206/299 scored trials (68.9%), with 45/100 cases passing all three trials. The baseline cost $0.91023745 and brought cumulative spend to $4.23407822. The exposed development result is not a causal improvement claim; one inconclusive and known judge disagreements remain documented.

### 2026-09-24 — Requested unchanged repeat, calibration 8

Calibration 8 repeated the unchanged 135 references: 392/396 application labels and 135/135 actor labels matched, with four disagreements and no negative control passing overall. It cost $0.22134986, bringing cumulative spending to $4.45542808. No application trial was retried or rescored, and the result does not establish general evaluator improvement.

### 2026-09-24 — Resolve calibration-8 findings before calibration 9

Contract 3.0.6 / harness 2.0.13 clarified financial-claim completeness, evidence timing, and prohibited annual-workflow restarts; one false-source Rules label was corrected. Transcripts, cases, fixtures, and application behavior remained unchanged. A fresh calibration was authorized; prior measurements retained their original labels and identities.

### 2026-09-24 — Calibration 9 completed with full label agreement

Calibration 9 matched all 396 application labels and 135 actor-validity labels across 135 references, with no measurement failures or negative controls passing overall. The 405 calls cost $0.23440203, bringing cumulative spending to $4.68983010. This is agreement with authored references, not independently adjudicated accuracy; no new application baseline ran.

### 2026-09-24 — Delete generated review packets at Ryan’s request

At Ryan’s request, 15 generated evaluation pages and the GPT-6 Luna packet’s build/check scripts were removed; raw transcripts, manifests, verdicts, receipts, and corpus contracts were retained. Earlier links to deleted pages are historical. No paid run or recalibration occurred.

### 2026-09-24 — Publish summaries and remove redundant experiment archives

The archive cleanup removed redundant run archives and per-round documents while retaining the journal, executable inputs, focused regressions, and contract-required evidence. The historical-results table consolidates earlier summaries; it does not add runs or claim comparable gains. Validation passed 200 relevant tests, and no paid evaluation, deployment, or approval changed.

| Historical work | Result and limitation |
| --- | --- |
| Initial 24-case demo, corpus 1.0.5 | 27/72 trials passed; 3/24 cases passed all three. Actor and grader problems remained; no production baseline was approved. |
| Evaluation integrity, September 21 | Calibration matched 138/138 labels across 46 development examples; actor diagnostics passed 59/60. Outcome/Grounding/Rules separation and invalid-actor handling improved measurement; this was not independent accuracy. |
| Calibrated 24-case baseline, corpus 1.0.11 | 58/71 scored trials passed, one inconclusive out of 72; critical pass³ was 12/17. Below the release thresholds. |
| Caching/prompt work in #581 | Final actor check 60/60 and calibration 179/180. Final 72-trial run achieved 17/17 critical pass³ once; the requested three-run streak remained unfinished. |
| Initial 200-case calibration | Two runs each measured 274 development references, with known disagreements and a later reference correction. Those runs did not qualify the revised exact contract. |
| First GPT-6 Luna 200-case baseline | 409 passed, 184 failed, seven inconclusive out of 600; 68.97% of 593 scored trials. Application run cost $1.720441030. Signed-money checks, actor validity, and judge errors limited interpretation. |
| Prompt A/B/C comparison and golden-100 rounds | Aggregate results, original limitations, costs, and adoption decisions remain in the earlier journal entries above. |


### 2026-09-24 — SOP-only eval-climb pilot stopped by user

The pilot compared an incumbent (38/100 pass³) with candidate A (36/100); A was rejected, and candidate B stopped after 130/300 attempts. Recorded spend was $2.162977505, but four in-flight calls lacked final receipts, so the total was not final; no candidate was adopted. The pilot ended without review/confirmation, and its deferred direction-wording hypothesis was not tested.

### 2026-09-24 — Pass³-first $20 campaign blocked during review

Five full development runs tested SOP candidates under corpus 3.0.6 / harness 2.0.13; all completed, but independent review rejected the measured candidates for material route/source regressions, and Round 2B review was blocked by agent capacity. The table preserves each score and cost; total new evaluation spend was $4.684365605. No confirmed patch or production claim was made, and the search remained incomplete pending independent review.

| Run / local commit | Pass³ / 100 | Successful / 300 | Inconclusive | Eval cost | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Original baseline | 47 | 212 | 1 | $0.955475225 | Incumbent retained |
| Round 1A `ee6e1be` | 54 | 222 | 0 | $0.932931080 | Rejected |
| Round 1B `c9b1f4a` | 58 | 235 | 0 | $0.921556700 | Rejected |
| Round 2A `e5129a4` | 52 | 225 | 0 | $0.939550450 | Rejected after review |
| Round 2B `4080040` | 50 | 220 | 1 | $0.934852150 | Numeric gates pass; review blocked |


## 2026-09-25 UTC — Pass³-first campaign continuation and final decision

A fresh independent review completed Round 2B and confirmed material wrong-direction routing and source-disclosure regressions despite passing numeric gates. This was the second consecutive round without an eligible improvement, so the campaign stopped with the original SOP retained and no confirmation run. Spend remained $4.684365605; no patch was recommended.

## 2026-09-25 UTC — Explicit one-round continuation: Round 3

Ryan authorized one additional pass³ round under the existing $20 cap; two SOP candidates were compared against the original baseline on the frozen development contract. Both improved pass³ numerically but independent reviewers found repeated route and source regressions, so neither was eligible and the original SOP remained. Round 3 cost $1.870978175 (cumulative $6.555343780); no fourth round or confirmation was authorized.

| Application / local commit | Pass³ / 100 | Successful slots / 300 | Inconclusive | Eval cost | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Original `a5338c9` (existing baseline) | 47 | 212 | 1 | $0.955475225 already accounted | Retain |
| R3A `5c8acda` | 52 | 228 | 1 | $0.934252335 | Reject independently |
| R3B `0c4a4df` | 55 | 234 | 1 | $0.936725840 | Reject independently |


## 2026-09-25 — Description-only continuation on PR600 blocked at contract review

Independent review rejected the proposed editable-description contract because a shared input/output model could change generated output schemas without changing the normalized source identity. No calibration or application run began; prior seven-run evidence remained accounted at $6.555343780 of the $20 cap. The incumbent was retained, and a focused contract repair plus fresh review was required before measurement.

| Phase | Completed attempts / references | Pass^3 | Eval cost |
| --- | ---: | ---: | ---: |
| Carried prior campaign, seven full runs | 2,100 attempts | Not comparable across contracts | $6.555343780 |
| Fresh offline contract review | No paid calls | Not measured | $0.000000000 |
| New calibration, baseline, search, confirmation | Not started | Not measured | $0.000000000 |
| Cumulative authorized accounting | 2,100 prior attempts | No new result | **$6.555343780 / $20** |


## 2026-09-25 — Contract blocker resolved; calibration stopped at development credentials

Contract 3.1.1 / harness 2.1.1 resolved the schema-preservation blocker and passed independent review, but all 135 fresh calibration references failed before any model call because development credentials could not be retrieved. The failure cost $0 and left cumulative accounting at $6.555343780 of $20; no baseline or candidate run began. The failed attempt remains immutable and must precede any later authorized run.

| Phase | Coverage / result | Pass^3 | Eval cost |
| --- | --- | ---: | ---: |
| Carried seven prior full runs | 2,100 completed attempts; all usage known | Not comparable | $6.555343780 |
| Corrected contract review | Accepted offline | Not measured | $0.000000000 |
| Fresh calibration | 135/135 measurement failures; zero model calls | Not applicable | $0.000000000 |
| Baseline, candidates, confirmation | Not started | Not measured | $0.000000000 |
| Cumulative accounting | No new model usage | No new result | **$6.555343780 / $20** |


## 2026-09-25 — Authenticated description-climb continuation: calibration blocked

After Ryan restored authorization, calibration completed 135 references and 405 known-usage calls for $0.233439065, but independent review found two material Grounding disagreements. The calibration remained unapproved, so baseline and candidate search did not start; cumulative spend was $6.788782845 of $20. No prior score transferred and no application improvement was measured.

| Calibration criterion | Agreement | Disagreement |
| --- | ---: | ---: |
| Outcome, actor-valid references | 132/132 | 0 |
| Grounding, actor-valid references | 130/132 | 2 |
| Rules, actor-valid references | 132/132 | 0 |
| Actor validity, all references | 135/135 | 0 |

| New-contract application phase | Completed slots | Pass^3 / 100 | Successful slots / 300 | Inconclusive slots |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 0 | Not measured | Not measured | Not measured |
| Candidate rounds | 0 | Not measured | Not measured | Not measured |
| Confirmation pair | 0 | Not measured | Not measured | Not measured |

| Eval spending | USD |
| --- | ---: |
| Carried seven full runs / 2,100 attempts | 6.555343780 |
| Preserved credential-failed calibration | 0.000000000 |
| New authenticated calibration | 0.233439065 |
| Cumulative charged eval usage | **6.788782845** |
| Remaining original authorization | **13.211217155** |


## 2026-09-25 — Authorized annual-day grounding correction and first description-climb round

After Ryan selected the stricter annual-day Grounding rule, corpus 3.1.2 / harness 2.1.2 received fresh calibration and a 100-case baseline plus two candidate measurements. Both candidates were rejected for material route-direction or provenance regressions despite numeric gains; the table preserves their results. The sequence cost $3.088099150 beyond the carried ledger (cumulative $9.876881995), and the next admitted round was blocked by agent capacity.

| Application | Pass³ / 100 | Success / 300 | Inconclusive | Grounding / 300 | Rules / 300 | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Original `f218fe4` | 44 | 204 | 0 | 11 | 57 | Retained |
| R1A SOP `87751cc` | 56 | 238 | 0 | 5 | 56 | Reject: unresolved material regressions |
| R1B annual summary `d9f9504` | 65 | 253 | 0 | 12 | 35 | Reject: Grounding worsens; provenance concerns |

| Accounted work | Cost USD |
| --- | ---: |
| Carried seven older full runs | 6.555343780 |
| Prior credential-failed calibration | 0.000000000 |
| Prior authenticated calibration | 0.233439065 |
| New matching calibration | 0.241132560 |
| Fresh baseline | 0.933435640 |
| R1A | 0.933457100 |
| R1B | 0.980073850 |
| **Cumulative** | **9.876881995** |


## 2026-09-25 — Round 2 capacity continuation: no eligible improvement

The admitted Round 2 compared two Greenway direction edits against the original application on corpus 3.1.2; both were rejected for repeated material route regressions, and one also increased inconclusives. The table preserves scores; this continuation cost $1.903038880 and brought cumulative spending to $11.779920875. The two-round stopping rule ended the search with the original application retained and no confirmation run.

| Application | Pass³ / 100 | Successful slots / 300 | Inconclusive | Decision |
| --- | ---: | ---: | ---: | --- |
| Original `f218fe4` | 44 | 204 | 0 | Retained |
| R2A SOP `9808e672e502504995a5f9f9fb917b2ba1db9853` | 57 | 231 | 0 | Reject: unresolved material direction regressions |
| R2B current-price summary `b715c2cfc8489df1373eda3040408c7303174b74` | 52 | 222 | 1 | Reject: inconclusive increase and material direction regressions |

| Accounted work | Cost USD |
| --- | ---: |
| Cumulative before this capacity continuation | 9.876881995 |
| R2A | 0.946600000 |
| R2B | 0.956438880 |
| **This continuation** | **1.903038880** |
| **Cumulative** | **11.779920875** |
| **Unused authorization** | **8.220079125** |


## 2026-09-25 — pass³ preparation; calibration stop

Preparation for a new pass³ contract updated runner scoring, judge guidance, actor instructions, endpoint aliases, and Oracle catalog metadata while leaving the application behavior unchanged. The first calibration completed 143 references but exposed material Outcome and Grounding grading errors, so the calibration was not approved and no actor check or application run began. The table preserves its agreement and cost figures; no application improvement is claimed.

| First calibration measure | Result |
| --- | ---: |
| Complete references | 143 / 143 |
| Actor-validity agreement | 143 / 143 |
| Outcome agreement on actor-valid references | 137 / 140 |
| Grounding agreement on actor-valid references | 139 / 140 |
| Rules agreement on actor-valid references | 140 / 140 |
| Added contrast agreement | 8 / 8 |
| Calls with known usage | 429 / 429 |
| Calibration cost | $0.257945655 |
| Carried cumulative spend | $11.779920875 |
| New cumulative spend | $12.037866530 |
| Remaining preparation allowance ($15 ceiling) | $2.962133470 |
| Remaining total authorization ($20 cap) | $7.962133470 |


### 2026-09-25 — user-directed overall-pass objective

Ryan changed the objective to overall pass rate while retaining three trials per case and independent regression safeguards. The scoring contract and future measurement plan were revised accordingly; this entry records a goal change, not a measured application result.

## 2026-09-25 — uncapped overall-pass preparation; fresh calibration stop

Under the overall-pass objective, a fresh calibration completed all 146 references and 438 known-usage calls but retained material grading disagreements. The run cost $0.268293010 and brought accounted evaluation cost to $12.306159540; calibration remained unapproved, so application measurement did not begin. The table preserves the measured agreement and spending figures.

| Calibration measure | Result |
| --- | ---: |
| Complete references | 146 / 146 |
| Started and finished calls, all usage known | 438 / 438 |
| Measurement failures | 0 |
| Outcome label agreement on actor-valid references | 136 / 143 |
| Grounding label agreement on actor-valid references | 142 / 143 |
| Rules label agreement on actor-valid references | 142 / 143 |
| Actor-validity agreement | 145 / 146 |
| Prior four disagreement references now matching labels | 4 / 4 |
| Added contrast references matching labels | 3 / 3 |
| Calibration cost | $0.268293010 |
| Cumulative accounted eval cost | $12.306159540 |


## 2026-09-25 — evidence-first grading repair; remaining source errors

The evidence-first repair completed calibration on the unchanged 146 references, but independent review found false Outcome and Grounding judgments despite improved explanations. The run cost $0.272413545 (cumulative $12.578573085); calibration remained unapproved and no application baseline ran. The remaining source-denial and route-correction boundaries required further contract work.

| Calibration measure | Result |
| --- | ---: |
| Complete references | 146 / 146 |
| Started and finished calls, all usage known | 438 / 438 |
| Measurement failures | 0 |
| Outcome label agreement on actor-valid references | 142 / 143 |
| Grounding label agreement on actor-valid references | 141 / 143 |
| Rules label agreement on actor-valid references | 143 / 143 |
| Actor-validity agreement | 146 / 146 |
| Calibration cost | $0.272413545 |
| Cumulative accounted eval cost | $12.578573085 |


## 2026-09-25 — source completeness calibration; actor/input-grounding stop

Contract 3.3.3 separated required disclosures from factual accuracy and checked source denials; calibration still contained an actor-validity error and a premature-input Grounding error. It cost $0.271214520, bringing cumulative evaluation spend to $12.849787605, and was stopped without application trials. The table preserves label agreement; exposed references do not establish repeatability.

| Calibration measure | Result |
| --- | ---: |
| Complete references | 146 / 146 |
| Started and finished calls, all usage known | 438 / 438 |
| Measurement failures | 0 |
| Outcome agreement among expected-valid references judged valid | 142 / 142 |
| Grounding agreement among expected-valid references judged valid | 141 / 142 |
| Rules agreement among expected-valid references judged valid | 142 / 142 |
| Actor-validity agreement | 145 / 146 |
| Calibration cost | $0.271214520 |
| Cumulative accounted eval cost | $12.849787605 |


## 2026-09-25 — delivered-turn/input-support repair; calibration repeatability stop

Contract 3.3.4 separated delivered user turns from simulator logs and required turn-local support for financial and schedule inputs. Two identical calibrations disagreed on four material decisions; together they cost $0.535169550 and brought cumulative spend to $13.384957155. The pair was unapproved, so no actor check or application run was admitted.

| Calibration measure | First | Predetermined repeat |
| --- | ---: | ---: |
| Complete references | 146 / 146 | 146 / 146 |
| Started and finished calls, all usage known | 438 / 438 | 438 / 438 |
| Measurement failures | 0 | 0 |
| Outcome agreement on valid references | 143 / 143 | 140 / 143 |
| Grounding agreement on valid references | 143 / 143 | 142 / 143 |
| Rules agreement on valid references | 143 / 143 | 143 / 143 |
| Actor-validity agreement | 146 / 146 | 146 / 146 |
| Run cost | $0.272038170 | $0.263131380 |
| Cumulative accounted eval cost | $13.121825775 | $13.384957155 |


## 2026-09-25 — requirement applicability calibration; Outcome reliability stop

Contract 3.3.5 reordered judging context to test requirement applicability before omissions and Grounding across inputs and final claims. Calibration found nine material Outcome errors, including false failures and false passes, so it remained unapproved at a cost of $0.271813360 (cumulative $13.656770515). No repeat, actor check, baseline, or candidate search ran.

| Calibration measure | Result |
| --- | ---: |
| Complete references | 146 / 146 |
| Started and finished calls, all usage known | 438 / 438 |
| Measurement failures | 0 |
| Outcome agreement on valid references | 134 / 143 |
| Grounding agreement on valid references | 143 / 143 |
| Rules agreement on valid references | 143 / 143 |
| Actor-validity agreement | 146 / 146 |
| Calibration cost | $0.271813360 |
| Cumulative accounted eval cost | $13.656770515 |


## 2026-09-25 — Luna/high calibration pair clears; actor stopping blocks continuation

Two Luna/high calibrations on contract 3.3.6 matched all 876 criterion decisions with no measurement failures, at costs of $0.296909860 and $0.287747700. The subsequent scripted actor check completed 300 trials but left four inconclusive stopping cases, blocking application repeats and candidate search; it cost $0.277166100. The sequence cost $0.861823660 (cumulative $14.518594175), and no application improvement was measured.

| Calibration measure | First run | Second run |
| --- | ---: | ---: |
| Complete references | 146 / 146 | 146 / 146 |
| Completed calls, all usage known | 438 | 438 |
| Measurement failures | 0 | 0 |
| Outcome agreement on valid references | 143 / 143 | 143 / 143 |
| Grounding agreement on valid references | 143 / 143 | 143 / 143 |
| Rules agreement on valid references | 143 / 143 | 143 / 143 |
| Actor-validity agreement | 146 / 146 | 146 / 146 |
| Cost | $0.296909860 | $0.287747700 |


## 2026-09-25 — Private production qualification policy 3.0.0

Policy 3.0.0 defines future admission on an independently authored 100-case private holdout at 240/300 successful trials, using signed aggregate evidence while keeping cases and keys outside coding-agent access. No agent performance was measured and evaluation cost was $0; real holdout authoring, evaluator provisioning, approvals, and fresh signed evidence remain pending. The policy change does not qualify or deploy an application.

### 2026-09-25 — Adversarial review corrections before private-gate activation

Adversarial review found and fixed two private-gate recovery defects involving identical-evidence imports and provisional cost reconciliation. Synthetic regressions cover the repair and rejection paths; no paid evaluation or deployment occurred. Validation passed 339 relevant tests, with two skipped.

## 2026-09-25 — Public private-holdout authoring kit

Authoring kit 1.0.0 provides a public, credential-free packet and validator for independent 100-case holdout creation; no private cases or signing keys are included. Development contract 3.0.7 / harness 2.0.14 changed evaluator identities, so prior approval reset to pending. Validation used synthetic cases only, cost $0, and did not measure agent quality.

### 2026-09-25 — Authoring-kit integration correction

PR review found a missing development release-manifest refresh; kit 1.0.1 and contract 3.3.1 / harness 2.3.1 corrected the package inventory and pinned the current serving release. Focused compatibility and bundle checks passed (173 tests, then 78 after the follow-up); no model calls or private data were involved. CI remained the merge gate.

## 2026-09-25 — actor completion repair clears; normal-status grading error found

The actor repair passed all 300 scripted trials, and two fresh calibrations on corpus 3.3.7 / harness 2.3.7 followed. The second calibration falsely failed a correct answer for omitting normal OPEN status, so the pair was unapproved despite otherwise strong agreement; the sequence cost $0.865097000 and brought cumulative spend to $15.383691175. The decision was to retain actor evidence and repair judge materiality before any application baseline.

| Measure | Actor check | Calibration 1 | Calibration 2 |
| --- | ---: | ---: | ---: |
| Complete trials/references | 300 | 146 | 146 |
| Complete calls, all usage known | 723 | 438 | 438 |
| Actor validity/agreement | 300/300 | 146/146 | 146/146 |
| Outcome agreement on valid references | Not scored | 143/143 | 142/143 |
| Grounding / Rules agreement | Not scored | 143/143 each | 143/143 each |
| Cost | $0.287175100 | $0.288319200 | $0.289602700 |


### 2026-09-25 — Final preparation calibration and reliability stop

Contract 3.3.8 corrected status and unavailability criteria, but its first calibration retained a material false Outcome failure. Independent review found no additional material issue; the calibration cost $0.291537200 and brought cumulative spend to $15.675228375. Baseline readiness remained blocked, and the planned repeat and actor check did not run.

### 2026-09-25 — Luna xhigh calibration preparation completed

Contract 3.3.9 raised only judge reasoning to Luna/xhigh; two calibrations then matched all 429 application labels each, and the matching scripted actor check passed 300/300. The reviewed sequence cost $0.970892010, bringing cumulative spend to $16.646120385; fixed references do not establish unseen-trajectory accuracy or a causal effect. Preparation is complete, but no application baseline, candidate search, holdout evaluation, merge, or deployment occurred.

| Measure | Calibration 1 | Calibration 2 | Scripted actor check |
| --- | ---: | ---: | ---: |
| Complete references/trials | 146/146 | 146/146 | 300/300 |
| Application label agreement | 429/429 | 429/429 | Not scored |
| Actor labels / valid actor trials | 146/146 | 146/146 | 300/300 |
| Complete calls, all usage known | 438 | 438 | 723 |
| Cost | $0.331475370 | $0.319100040 | $0.320316600 |

## 2026-09-26 — Retrospective summaries of retired evidence

Historical reports were consolidated during repository cleanup without rescoring or renewing approvals. Original evidence remains available at the [pre-cleanup commit](https://github.com/rhprasad0/nova-toll-budget-agent/tree/e2b7d4b5514ce3f0228d2556ab197f0c1c38ec1a/v2/eval); the costs below are historical, outside the current spending ledger.

### Legacy golden demonstration and calibrations

These `gpt-5.6-luna` source-checkout runs used prompt 2.3.0 and predate the current measurement contract. The 72-trial demonstration had incomplete actor behavior and exposed held-out material, so it remains a limited demonstration without baseline or release approval. Calibration 7 retained two Grounding disagreements and pending human review; calibration 15 had none and received [exact-evidence approval](evidence/golden-360/calibration-15/review.json), with an accepted 59/60 actor-check limitation. That historical approval does not qualify the current corpus or application.

| Historical run | Commit | Corpus / harness | Recorded result | Run cost | Prior recorded spending |
| --- | --- | --- | --- | ---: | ---: |
| Demonstration, 2026-09-20 | `e9abf4eaef1b6f4bc615815c7b9b302ba8710821` | 1.0.5 / 1.0.4 | 27/72 successful trials (37.5%); 3/24 cases passed all three (12.5%); 546 model calls | $0.38888630 | $0.33607270 |
| Calibration 7, 2026-09-20 | `a3c30b60dd100f299e9085bd20847569eea10d3a` | 1.0.7 / 1.1.0 | 100/102 label agreement across 34 references; 103 model calls | $0.07223746 | $0.79967600 |
| Calibration 15, 2026-09-21 | `41f09f991cf0a2db54bd9410b33eb55d080be6e9` | 1.0.11 / 1.2.1 | 138/138 label agreement across 46 references; 138 model calls | $0.06590064 | $2.06711088 |

### August 22 live integration checks

Three selected live runs passed their code-graded checks, but two responses labeled an August observation EST. Model identity and cost were not recorded. These examples show integration behavior, not an agent-wide baseline or timezone correctness; raw response reports were removed.

| Scenario | Recorded result | Checked behavior |
| --- | --- | --- |
| Reagan Airport and Pentagon/Eads Street to Westpark | 2/2 passed | Each made the exact current-price call to `i495:1859ND` and returned two observed components totaling $14.65, with movement and median comparison. |
| Dulles Airport to Reagan Airport | 1/1 passed | The cross-direction request returned typed stale I-95 availability; the response withheld a price. |
| Annual affordability workflows | 6/6 passed | Fixed/modeled success, Tysons exit clarification, complete input acquisition, salary-range clarification, adjustable 52-week annual-day estimates, and unavailable return routes. |

### Annual ballpark grounding experiment

Five prompt variants of one frozen Springfield-Franconia–Westpark result produced 1,000 `gpt-5.6-luna` responses. Adjudication found one wrong evaluation time, three correct but unsupported derived differences, 28 inadequate coverage disclosures, one missing annual toll amount, and 36 missing TollChat attributions. The original literal grader's 426/1,000 score was invalid because it rejected equivalent times, rounding, and wording; it needed correction before release-gate use. Actual usage was 30,196,200 input and 638,936 output tokens; dollar cost was unrecorded. Repetitions of one fixture do not establish route-wide or production accuracy.

| Measure | Result |
| --- | ---: |
| Reconciled responses, transport success, correct P25/P50/P90 tables | 1,000/1,000 each |
| Strict quantitative grounding | 996/1,000 (99.6%) |
| No incorrect quantitative fact | 999/1,000 (99.9%) |
| Core semantic contract | 971/1,000 (97.1%) |
| Core contract plus explicit TollChat attribution | 935/1,000 (93.5%) |
| Core contract plus strict quantitative grounding | 967/1,000 (96.7%) |
| Attribution requirement plus strict quantitative grounding | 931/1,000 (93.1%) |

### I-95/I-495 identity-proxy validation

For 16 missing OD IDs, `identity_proxy_v1` copies the mapped VDOT price as a provisional ballpark. A chronological 70/30 split of July 25–30 captures gave 1,200 holdout comparisons: $0.106 MAE, 96.1% within $0.50, $0.00 p95 absolute error, and $8.05 maximum error; measured analysis cost was unrecorded. The feeds are related, observations cluster within captures, and the short overlap leaves per-OD and seasonal accuracy unproven. Keep modeled labels and withhold an estimate when no eligible row exists; stronger claims need per-OD and direction-stratified results plus reproducible pairing evidence. [Mapping guidance](results/i95-missing-od-pricing.md) retains those limits.

## 2026-09-26 — Adversarial-review fixes before the next climb

Contract 3.3.10 / harness 2.3.10 fixed signed-money grading for phrases such as “$2.50 decrease,” while preserving rejection of wrong amounts and signs. The development target is 270/300 successful fresh-confirmation trials (90%) with all trials measured; repeatability, violation counts, and trajectory review remain required. SOP 2.3.10 clarified per-turn call limits, consent, and annual presentation scope; the application stayed on Luna low/2,048. Offline checks passed, but no calibration or application run measured these changes. Corpus review remained pending, prior approvals did not transfer, and evaluation cost was $0.

### 2026-09-26 — PR package-verification correction

The SOP change required refreshed package digests and a development compatibility binding to the observed serving release `9d04cc7`. The rebuilt release manifest, five compatibility checks, 120 shared-package checks, and 19 manifest tests passed. This credential-free correction made no model calls or delivery claim; production compatibility and approvals were unchanged.

## 2026-09-26 — CI database and loader profiling

Optional statement timing and PostgreSQL plans identified where database and loader CI spent time before choosing an optimization. The local and hosted measurements below use different hardware and image builds and should be read separately; no paid runner was purchased.

### Controls and environment

Local measurements used fresh disposable PostgreSQL 17.5/PostGIS 3.5 containers, fixed schemas and fixtures, and source `8a42520` against base `9d04cc7`. Loader commands used warm dependency caches. The local cached image differed from GitHub's official image, so their timings are not directly comparable.

### Aggregate results

Three local baseline repetitions found report contracts and route/pricing parity dominated database time; all database and loader passes succeeded. Separate instrumented database passes took 567.98 s with statement timing and 589.39 s with nested plans; they were diagnostic runs, not speed comparisons. The focused database/profile checks passed 57 tests.

| Measurement | Repetitions | Median | Range |
| --- | ---: | ---: | ---: |
| Full database script, diagnostics off | 3 | 562.28 s | 560.07–563.08 s |
| Report contracts within that script | 3 | 343.83 s | 343.17–346.81 s |
| Route and pricing parity contracts | 3 | 186.00 s | 184.28–188.08 s |
| Loader workflow command total | 3 | 185.85 s | 185.04–193.20 s |
| Loader coverage/pytest command | 3 | 146.47 s | 145.86–150.79 s |
| Loader authored-code checks | 3 | 21.95 s | 21.61–24.08 s |

### What accounts for the time

Report and route/pricing checks used about 94.5% of database script time. Plans showed millions of shared-buffer hits, zero shared reads, and a retained/candidate report-input gap of roughly 17 s versus 91 s that the evidence could not attribute to JIT, statistics, or plan reuse. The loader also spent a fixed 10 s sleeping in `shared_readiness(wait=False)`; other dominant time was in subprocesses.

### Decision and remaining experiment

Investigate repeated SQL work before paying for a larger runner. The local evidence points to a CPU-heavy workload but does not establish a third-party runner speedup. Three hosted repetitions were planned under matching source and image identities; a failed comparison-base pilot and a canceled locked-query probe were excluded. Local compute cost was unmetered and granular diagnostics stayed private.

### 2026-09-26 — GitHub repetitions and cleanup

Three hosted executions of each target job on frozen source `3d6f88a` and event base `53145d4` all passed; copied rerun jobs were excluded. Report and route/pricing checks used 91.8–93.7% of database script time, while report-input timing still varied widely; loader results again showed the fixed 10 s sleep. These hardware-varying samples support investigating SQL repetition, not a provider speedup claim. Temporary workflow overrides were removed after the ordinary compatibility baseline was corrected and required checks passed. Six measured jobs used about 52 runner-minutes; billing was not queried.

| Hosted measurement | Median | Range |
| --- | ---: | ---: |
| Database job, including setup and cleanup | 895 s (14m 55s) | 638–924 s |
| Database script, with statement timing | 869.30 s | 607.30–891.87 s |
| Report contracts within the script | 567.56 s | 371.40–594.19 s |
| Route and pricing parity contracts | 239.79 s | 186.26–247.10 s |
| PostGIS service initialization | 17 s | 16–18 s |
| Loader job, including setup and cleanup | 233 s (3m 53s) | 184–247 s |
| Loader coverage/pytest command | 159.51 s | 119.22–173.21 s |
| Loader authored-code checks | 27 s | 20–32 s |

### 2026-09-26 — Disable JIT in disposable CI databases

Controlled PostgreSQL 17.5/PostGIS 3.5 probes showed that disabling JIT sharply reduced the analyzed report query, while changing function row estimates alone did not. The no-wait readiness fix reduced its 120-test check from 11.01 s to 0.96 s. One full local run per variant showed 556.47 s with JIT on, 310.91 s with JIT off, and 242.87 s with JIT off plus refreshed statistics; the table's 67.63 s report-contract value in the last row was later corrected to **66.98 s**. Two isolated contract workers reduced repeated contract-harness median time from 210.10 s to 114.18 s with the same total four-core quota. The final full local workflow passed in 131.72 s, and hosted CI passed with a 216 s database job; four hosted optimization pairs used about 36.5 runner-minutes, with billing unqueried. Retain JIT off, refreshed fixture statistics, two isolated full-CI workers, and the readiness fix; keep local/development-delivery validation serial. Small samples and varying hosted CPUs do not justify deployed-database tuning, SQL migrations, or third-party runner claims.

| Fixture/planner variant | JIT on median (range), seconds | JIT off median (range), seconds |
| --- | ---: | ---: |
| Fresh schema, default function row estimates | 16.62 (16.54–16.69) | 16.26 (15.84–16.69) |
| Fresh schema, five single-row route functions estimated as `ROWS 1` | 15.24 (15.14–15.34) | 15.86 (15.64–16.09) |
| Analyze graph tables and the two-row I-95 fixture | 86.90 (84.60–89.21) | 7.65 (7.53–7.78) |
| Analyze those tables and apply the same `ROWS 1` estimates | 87.48 (84.30–90.67) | 7.33 (7.08–7.58) |

| Local full database script | Wall time | Report contracts combined | Route/pricing contracts combined |
| --- | ---: | ---: | ---: |
| Control, JIT on | 556.47 s | 342.87 s | 182.99 s |
| JIT off | 310.91 s | 97.13 s | 183.48 s |
| JIT off plus statistics refresh | 242.87 s | 67.63 s | 145.43 s |

| Contract harness | Median wall time | Range |
| --- | ---: | ---: |
| One worker, four-core quota | 210.10 s | 207.78–212.42 s |
| Two isolated workers, two cores each | 114.18 s | 112.32–116.04 s |

### 2026-09-26: Judge calibration and actor preparation

Preparation for a 270/300 development-pass target exposed inconsistent judging and two actor follow-up failures before application hill climbing began. Corpus/harness versions, all 13 paid runs, and their costs appear below; the final three calibrations matched all 429 application and 146 actor labels each, and the corrected actor check passed 300/300. The repeated calibration work cost $4.271673840 of the agreed $25 ceiling. Earlier failed draws remain evidence of judge variability, and scripted actors do not establish live-trajectory reliability. The fixed-rate SOP and judge/actor changes were retained for PR review; no application performance or holdout result was measured.

| Preparation and execution commit | Versions | Run | Result | Cost |
| --- | --- | --- | --- | ---: |
| Starting contract, `e2b7d4b` | 3.3.9/2.3.9 | Calibration 1 | 429/429 application; 146/146 actor | $0.333870370 |
| Starting contract, `e2b7d4b` | 3.3.9/2.3.9 | Calibration 2 | 427/429 application; 146/146 actor; unapproved | $0.322916890 |
| Judge consolidation, `c7ca28b` | 3.3.10/2.3.10 | Calibration 1 | 429/429 application; 146/146 actor | $0.340086075 |
| Judge consolidation, `c7ca28b` | 3.3.10/2.3.10 | Calibration 2 | 429/429 application; 146/146 actor | $0.330696520 |
| Judge consolidation, `c7ca28b` | 3.3.10/2.3.10 | Actor check | 298/300 valid; 721 calls | $0.318990400 |
| Actor completion, `f41077d` | 3.3.11/2.3.11 | Calibration 1 | 427/429 application; 146/146 actor; unapproved | $0.329104820 |
| Materiality and Rules scope, `cfdb0e5` | 3.3.12/2.3.12 | Calibration 1 | 429/429 application; 146/146 actor | $0.334002105 |
| Materiality and Rules scope, `cfdb0e5` | 3.3.12/2.3.12 | Calibration 2 | 429/429 application; 146/146 actor | $0.325226560 |
| Materiality and Rules scope, `cfdb0e5` | 3.3.12/2.3.12 | Actor check | 300/300 valid; 723 calls | $0.319122500 |
| Materiality and Rules scope, `cfdb0e5` | 3.3.12/2.3.12 | Additional calibration | 427/429 application; 146/146 actor; unapproved | $0.330220920 |
| Fixed-rate SOP, `865742c` | 3.3.12/2.3.12 | Calibration 1 | 429/429 application; 146/146 actor | $0.329371060 |
| Fixed-rate SOP, `865742c` | 3.3.12/2.3.12 | Calibration 2 | 429/429 application; 146/146 actor | $0.329559060 |
| Fixed-rate SOP, `865742c` | 3.3.12/2.3.12 | Calibration 3 | 429/429 application; 146/146 actor | $0.328506560 |

### 2026-09-26: Integrate preparation with the money-grading repair

PR #612 integrated #611's signed-money grading fix and 270/300 target with the judge, actor, and fixed-rate work in corpus 3.3.13 / harness 2.3.13 and prompt 2.3.11. The earlier three-run calibration streak did not approve this combined contract; independent corpus review admitted it for fresh calibration. Integration added no model cost, leaving cumulative spending at $4.271673840. The 421 relevant tests, comparison, compatibility, and manifest checks passed; no application run occurred.

### 2026-09-26: First calibration after the rebase

On corpus 3.3.13 / harness 2.3.13, 146 references and 438 calls completed with 427/429 application and 146/146 actor labels matching. Outcome wrongly rejected a correctly timed Jones Branch quote and passed an annual answer that called $3,669.52 combined cost tolls alone; Grounding and Rules still failed that answer overall. The run stayed unapproved with the fresh streak at zero. It cost $0.342221105, bringing cumulative spending to $4.613894945.

### 2026-09-26: Clarify observation dates and Outcome contradictions

Corpus 3.3.14 / harness 2.3.14 clarified when a same-day observation needs a date and required Outcome to check every financial claim through the final answer. Both repeats corrected the two prior labels, but the second explanation wrongly required an optional off-peak label, so only run 1 received semantic approval. The two runs cost $0.666833235, bringing cumulative spending to $5.280728180; the numeric streak was two, with further calibration held for review. No application result was measured.

| Run | Application labels | Actor labels | Review | Cost |
| --- | --- | --- | --- | ---: |
| 1 | 429/429 | 146/146 | Approved independently | $0.338925895 |
| 2 | 429/429 | 146/146 | Held for an explanation error | $0.327907340 |

### 2026-09-26: Require peak labels and repeat calibration

Corpus 3.3.15 / harness 2.3.15 and prompt 2.3.12 required peak-price labels while leaving off-peak labels optional; six passing references were updated and one negative reference added. Both 147-reference calibrations completed, but run 2 falsely passed a wrong annual-tool ID and a missing vehicle-cost disclosure and repeated an off-peak explanation error. The clean streak reset to zero; the historical actor check did not approve this contract. The pair cost $0.680333365, bringing cumulative spending to $5.961061545.

| Run | Application labels | Actor labels | Review | Cost |
| --- | --- | --- | --- | ---: |
| 1 | 432/432 | 147/147 | Approved independently | $0.344678525 |
| 2 | 430/432 | 147/147 | Held for user review | $0.335654840 |

### 2026-09-26: Use mechanical tool checks and answer quotes in grading

Corpus 3.3.16 / harness 2.3.16 moved tool-contract violations to replay validation and supplied answer quotes for disclosures while leaving semantic duties to the judge. A wrong assistant-turn citation stopped the first calibration after 63/147 references; those completed references matched 189/189 application and 63/63 actor labels, but negative controls were not fully measured. The partial run was unapproved, cost $0.136846600, and brought cumulative spending to $6.097908145. Independent review found the location error and recommended deriving quote turns in code.

### 2026-09-26: Derive quote locations and complete the next calibration

Corpus 3.3.17 / harness 2.3.17 derived assistant-turn locations from exact quotes, resolving the earlier citation error. An expired SSO attempt made no model calls; the subsequent full run matched 430/432 application and 147/147 actor labels. Rules falsely demanded another Tysons return-entry confirmation, and Outcome missed an explicit Gallows vehicle-cost disclosure, so approval and the clean streak remained at zero. The run cost $0.343222425, bringing cumulative spending to $6.441130570.

### 2026-09-26: Clarify round-trip consent and present judge evidence directly

Corpus 3.3.18 / harness 2.3.18 clarified that resolving each return-leg ID does not require another user confirmation, showed Outcome the original answers, and made mechanical Rules findings identify differing fields. The full calibration matched 432/432 application and 147/147 actor labels for $0.348311850, bringing cumulative spending to $6.789442420. Independent review held approval because a Rules explanation treated a harness-stopped missing answer as a separate violation; that finding was preserved for Ryan's review.

### 2026-09-26: Accept calibration after user adjudication

Ryan accepted the preceding 432/432 application and 147/147 actor calibration as run 1 of the required three after reviewing the stopped-response evidence. The trace cannot show whether the agent would have recovered, so the explanation and recovery question remain deferred. No label or judge behavior changed and no new cost was incurred.

### 2026-09-26: Stop the next calibration on an annual-day disagreement

Run 2 on unchanged corpus 3.3.18 / harness 2.3.18 matched 431/432 application and 147/147 actor labels. Outcome wrongly passed a negative reference that failed to invite adjustment of 156 proposed annual office days; Rules failed it correctly, so the overall reference still failed. The run was held before run 3, cost $0.344635850, and brought cumulative spending to $7.134078270.

### 2026-09-26: Accept run 2 with its documented disagreement

Ryan accepted run 2 for continuation while retaining its 431/432 Outcome disagreement and the independent review finding. The annual-day reference still failed overall under Rules; labels and instructions stayed unchanged. The accepted sequence reached two runs with no new model cost.

### 2026-09-26: Complete three accepted calibrations

Run 3 on unchanged corpus 3.3.18 / harness 2.3.18 matched all 432 application and 147 actor labels. Across the three accepted runs, agreement was 1,295/1,296 application and 441/441 actor labels with all 1,323 calls accounted for; run 1's deferred explanation and run 2's Outcome mismatch remain recorded. Run 3 cost $0.349336350, the sequence cost $1.042284050, and cumulative spending reached $7.483414620 of $25. Calibration preparation was complete, but application performance and general judge reliability were unmeasured.

### 2026-09-26: Rebase the accepted calibration changes for merge

PR #612 rebased onto `6af96ec9`, preserving both journal histories and the accepted corpus 3.3.18 / harness 2.3.18 execution inputs. Validation passed 475 focused tests and 25 subtests; a read-only development plan then identified a stale compatibility baseline, which was updated to observed serving release `6af96ec9` and passed 145 focused checks. No paid rerun or calibrated-behavior change followed; cumulative evaluation spending remained $7.483414620. Required PR CI remained the merge gate.


### 2026-09-26: Stop the next climb during the application trajectory audit

Started from merged `adb432a9` with unchanged corpus 3.3.18 / harness 2.3.18 and the accepted calibration sequence. Ryan authorized $50 additional evaluation spending, retained the runner’s $25 cumulative cap, and made 90% a soft milestone within three rounds. Independent preflight verified matching execution identities and development migration/catalog evidence; the scripted actor check passed 300/300 with all 723 calls accounted for. The first unchanged application repeat scored 248/300 (82.7%), with all 300 trials valid and measured; 64/100 cases passed all three trials, with 4 Grounding and 37 Rules violations as graded. This exposed-development result is neither a confirmed improvement nor holdout evidence.

The fresh trajectory audit found a material grading ambiguity: an answer saying no qualifying I-495-only fallback was available “for this result” failed all three criteria, although the returned data contained no fallback eligible under the SOP. A sibling answer saying the tool returned no eligible fallback passed. Independent review could not certify that distinction under meaning-based grading. Raw grades were preserved; new paid calls were stopped rather than changing the judge or admitting a candidate. The second repeat ended with 66 scored trials and 13 interrupted attempts, leaving 221 slots unattempted; it cannot establish a baseline or comparison. All 449 started model calls in that interrupted run finished with known usage.

The actor check cost $0.337634370, the first repeat $1.189533605, and the interrupted second repeat $0.202559860: $1.729727835 additional, bringing the existing chain to $9.213142455. No candidate, confirmation, or holdout evaluation ran. Resolve the grading ambiguity before a separately admitted continuation; retain the incomplete run in the spending chain and do not relabel or retry it into a passing result. Detailed evidence remains in ignored campaign storage.

Further offline audit identified two other issues requiring separate review: a deterministic money check rejected “about $6,361” after the correctly reported $6,361.07 while all semantic judges passed, and one actor changed an intended complete annual request into an arrival-time request, then said its departure time was unknown. A separate source-contradiction answer correctly failed Grounding and Rules but incorrectly passed Outcome under the documented shared policy. These findings concern grading or actor behavior; none justifies changing application instructions to satisfy the benchmark, and all recorded labels remain intact.

Deferred application leads include endpoint/direction clarification, preserving annual scenario qualifications, and keeping source disclosures and optional offers faithful to tool capabilities. They remain untested because the measurement audit stopped candidate admission. The independent audit covered the fixed 16-trial sample and all four recorded Grounding violations.


### 2026-09-26: Repair measurement issues and run one calibration

Corpus 3.3.19 / harness 2.3.19 addresses the four findings from the stopped climb: result-qualified fallback statements are supported by SOP eligibility, explicit nearest-whole-dollar restatements are allowed after an exact supported amount, the workflow-switch actor specifies departure times, and Outcome explicitly checks contradictory source claims despite otherwise correct disclosures. Six focused calibration references cover these cases and their invalid counterparts; the 147 prior labels remain unchanged. Application instructions, tools and model settings are unchanged. Validation passed 184 focused tests, 12 comparison checks, corpus validation, lint and types.

The single authorized calibration on `ea93200a` completed all 153 references and 459 accounted model calls. Agreement was 446/447 application-criterion labels, 153/153 actor labels, and 149/149 overall verdicts for valid reference conversations. The four original issues behaved as intended in the new references. One new negative control exposed a Rules false pass: it accepted “about $6,362” after the exact $6,361.07, although the permitted nearest-dollar restatement is $6,361. Outcome, Grounding and the deterministic money check correctly rejected it, preserving the overall reference failure. The six new regressions and failure requirements for all 41 negative application references were reviewed by the supervisor; no independent or human adjudication is claimed. Calibration approval remains pending, and labels were preserved without another run.

Calibration cost $0.363723385, bringing the existing spending chain to $9.576865840 under the retained $25 cap. This reference-label result does not measure application improvement, generated-actor repeatability, or holdout performance. No application evaluation, push or deployment followed; detailed evidence remains in ignored private storage.


### 2026-09-26: Accept the repaired calibration for a local climb

Ryan accepted the single corpus3.3.19 / harness2.3.19 calibration with its documented Rules false pass and explicitly waived the merged-corpus prerequisite for this local campaign. Independent review admitted the repaired corpus and confirmed unchanged application/tool identities and complete accounting. The one-run calibration authorization, existing $25 cumulative runner cap, three-round maximum, and all other preparation and regression checks remain; 90% is a soft milestone. Scores remain unchanged, cumulative spend is $9.576865840, and fresh actor validation plus the two application repeats are still required. No new model cost or deployment action accompanied this acceptance.


### 2026-09-26: Local climb stops on disclosure-quote validation

The local campaign on `c55d817b` retained corpus 3.3.19 / harness 2.3.19 and Ryan’s accepted calibration exception. Fresh scripted actor validation passed 300/300 with all 723 calls accounted for; independent review confirmed the repaired workflow-switch actors supplied departure times in all three trials. The actor check cost $0.332075000.

The first unchanged application repeat stopped automatically after Outcome supplied a source-disclosure quotation that removed Markdown bold markers from the original answer. Offline reproduction raised `invalid_disclosure_quote`: three citations for the corrected Dulles Toll Road result could not match the original assistant text exactly. Independent review confirmed the cause. The run retained 73 scored trials and 227 inconclusive slots, including the initiating judge error and 226 subsequent stopped attempts. The later `spend_budget_or_unknown_usage` messages reflect the shared stop flag, not exhausted dollars or unknown usage. All 493 started model calls completed with known usage.

The incomplete repeat cost $0.223788460. This attempt spent $0.555863460, bringing cumulative spending to $10.132729300 under the $25 cap. No usable baseline, candidate search, confirmation, accuracy delta, or holdout result was produced. Preserve this run and its costs; citation transport needs a separately reviewed harness repair and matching calibration before another climb. The accepted Rules disagreement and local merge exception remain recorded and do not waive measurement completeness.

Independent review recommends replacing retyped disclosure quotes with IDs of deterministically numbered original assistant lines, resolved back to exact stored text. This would preserve assistant-only provenance without relying on Markdown transcription; unknown IDs, missing disclosures and source contradictions must still fail. It is a deferred evaluator-schema change requiring focused regressions and matching calibration, outside this prompt-only campaign. No such change or retry was performed.


### 2026-09-26: Repair disclosure citations and admit imperfect calibration

Corpus 3.3.20 / harness 2.3.20 replaces retyped disclosure quotations with IDs of original assistant lines. Code resolves the selected lines without changing Markdown; unknown IDs remain measurement errors, and missing disclosures or contradictory claims still fail. The application, 100 development cases, 153 reference labels, tools and model settings are unchanged. Independent review reproduced the original failure against the repaired resolver. Validation passed 186 focused tests, 12 comparator checks, lint, types and corpus validation.

The single calibration on `8ab9ecc4` completed all 153 references and 459 accounted calls without measurement errors. Agreement was 444/447 application-criterion labels, 153/153 actor labels and 148/149 overall verdicts. Independent review verified all 140 disclosure citations and reviewed the missing-disclosure, formatting and source-contradiction controls. Under Ryan’s explicit allowance for imperfect label agreement, the supervisor accepted three bounded disagreements: Rules incorrectly penalized presentation order in a valid closure answer, and Grounding plus Rules accepted an incorrect whole-dollar restatement. Outcome and the deterministic money check still rejected the incorrect amount. Scores and labels remain unchanged; no human inspection is claimed.

Calibration cost $0.370347390, bringing cumulative spending to $10.503076690 under the retained $25 cap. Fresh actor validation and two unchanged application repeats follow before candidate search. The local merge exception, three-round maximum and soft 90% milestone remain. No application improvement or holdout result is established.

### 2026-09-26: Complete preparation and reject the first two direction patches

The local 3.3.20 / 2.3.20 campaign completed a fresh scripted actor check: 299/300 valid, with all 723 calls measured and known. One actor volunteered salary before the profile allowed it. An initially proposed stop was corrected after checking the written contract: a fully measured actor-invalid diagnostic is not missing evidence, and no perfect actor-check gate was specified. The invalid result was preserved without a retry. Ryan also reiterated that judging should focus on errors that could change decisions and tolerate harmless wording or presentation differences.

The unchanged application repeats scored 256/300 (85.3%) and 251/300 (83.7%); the second was the predetermined baseline. Their Grounding counts were 6 and 0, Rules counts 33 and 34, and pass³ counts 70 and 66. Repeat 2 retained one fully measured actor-inconclusive judgment after an optional closing offer; independent review treated it as bounded grading noise, preserving its score. Both full sets passed the comparison helper's evidence checks. Independent review audited the fixed family samples and all relevant actor and Grounding findings.

Round 1 tested one recurring application failure: choosing endpoint IDs for the wrong travel direction. Candidate A (`575391a2`) added a seven-line SOP check; candidate B (`a69a6382`) changed four existing endpoint parameter descriptions. Both started from `468afd70`, kept the calibrated contract fixed and passed independent scope review. A scored 231/300 (77.0%), down 6.7 percentage points, with one inconclusive, one Grounding and 32 Rules violations. B scored 235/300 (78.3%), down 5.3 points, with no inconclusives, two Grounding and 40 Rules violations. Neither met the numeric promotion gates.

Independent review inspected all old-pass/new-fail trials and new violations: 50 distinct attempts for A and 42 for B, alongside sibling trials and the unchanged repeat pair. It found continued route errors, annual qualification omissions and bounded grading inconsistencies, but no demonstrated causal weakening of consent, financial accuracy, security or route correctness. No grades were rewritten. The original baseline remains the incumbent; one round without improvement is recorded, and a second such round would stop search.

The actor check cost $0.321474440, the two application repeats $1.179739310 and $1.173083540, and candidates A/B $1.192263200 and $1.196807340. Cumulative spending reached $15.566444520 under the retained $25 cap, with $3.60 reserved for confirmation. No confirmed application gain, holdout result or deployment is claimed. Detailed reports, comparisons and review evidence remain in ignored campaign storage.

Ryan stopped the campaign after round 1. All paid runs had finished; round 2 diagnosis was interrupted before any patch or evaluation. The calibrated citation repair is retained locally, and the original application remains the incumbent. This continuation spent $5.433715220, with no confirmed accuracy improvement. Further direction-derivation ideas remain untested.

### 2026-09-27: Record repetitions, revise material judging and measure one focused candidate

Ryan authorized four reviewable PR layers after #617 and $25 additional evaluation spending. Corpus 3.3.21 / harness 2.3.21 makes recorded repetitions control scheduling, summaries, actor checks and comparisons while keeping three repetitions active. Version 3.3.22 changes grading to accept equivalent, materially correct annual explanations in their conversation context. An audit found 82 annual-qualification failures across 40 cases in four historical runs; those grades remain unchanged. Eight paired calibration references cover useful concise answers and misleading counterparts. These are grading-policy changes, not application improvements.

Corpus 3.3.23 / harness 2.3.23 activates 100 cases with one repetition, a fixed 100-slot success denominator and inapplicable pass³ fields. Sequential search requires a strict score gain plus independent material-regression review; violations and inconclusives trigger review, and 90/100 is a soft milestone. Frozen replay uses one calibration, one actor check and one baseline. The runner now accepts the explicitly authorized cumulative ceiling while retaining call reservations and known-usage checks. The first ceiling preflight failed before any API call and cost nothing. Focused scheduling, report, comparison, calibration, scope, accounting and public-package checks passed; offline subagent handoffs were exercised before paid search.

The single calibration completed 161 references and 483 known calls: 468/471 application-criterion labels, 156/157 overall verdicts and 161/161 actor labels agreed. All 24 new paired criterion labels agreed, and all 45 negative application controls failed overall. Independent review accepted three criterion disagreements across two references: Rules falsely penalized valid scenario names, while Outcome and Rules missed an incorrect rounding restatement that Grounding and the deterministic money check rejected. No labels were changed and no human adjudication is claimed. The actor check then passed 100/100 with 241 known calls.

| Run | Successes / fixed slots | Inconclusives | Grounding / Rules violations | API cost |
| --- | --- | --- | --- | --- |
| Starting application baseline | 86/100 | 0 | 2 / 14 | $0.392379040 |
| Conditional source-disclosure candidate | 85/100 | 1 | 2 / 14 | $0.398968040 |
| Selected application | Starting application retained | — | — | — |
| Finalist verification | Not run; no improvement retained | — | — | $0 |

The baseline evaluated `13c9a3fe`; the candidate evaluated `acb6cebe`. The candidate changed only the SOP source-disclosure paragraph to condition labels on returned facility flags. It corrected the motivating observed-versus-modeled claim, but lost ten scored passes and one pass to an actor inconclusive while gaining ten. Independent review inspected all lost passes and new violations, including a new violation on an already failing case, and found no demonstrated regression caused by the patch. Its lower score still rejects it. A false actor-invalid judgment demanded a reply to an optional closing offer after the requested estimate was complete; the recorded inconclusive remains, and even a pass would only tie the baseline. Other bounded wording and direction-grading concerns did not determine this rejection.

Search stopped because no further supported incumbent hypothesis remained. The annual-day lead retained the supplied 141 days in actual calls, so extra explanation alone did not establish a material failure. A coverage-denominator error appeared once in the rejected variant while the incumbent reported it correctly; that evidence did not justify another reminder. Previously rejected direction reminders remain negative evidence. No finalist rerun was needed, and the original application stays on gpt-6-luna. These single-trial development results do not establish production performance or generalization; a future grading ambiguity that affects promotion requires separate repair and a new baseline.

Calibration cost $0.388641695 and actor validation $0.107618440. Together with the two application runs, this campaign spent **$1.287607215**, bringing the reconciled chain to **$16.854051735** under the fixed **$40.566444520** ceiling. All 2,072 new model calls have known usage. Relevant evaluation and application hashes were verified after infrastructure rebases before reusing evidence. Detailed decisions, comparisons and raw evidence remain private; the publication layer adds this journal entry without retaining the rejected SOP change.

PR feedback before merge restored the omitted historical harness 1.2.10 three-trial contract and corrected two runbook passages that still called three repetitions active. Regression checks cover historical rendering, recovery accounting and rejection of a one-trial 1.2.10 contract; 142 focused tests and 15 comparison checks passed on the final stack. The compatibility fix changes the pinned helper and corpus hashes, so the prior calibration approval remains attached to its original identity and the revised corpus is pending fresh calibration before future paid application runs. Active single-pass execution, judging, application prompts and all recorded scores are unchanged. These fixes incurred no additional API spending.

### 2026-09-27 — Repair judging before further application tests

The continuation kept the 100-case, single-trial development workflow and gpt-6-luna. Preliminary audits found false failures for optional closing offers, background annual-day arithmetic, equal-valued scenario labels, sampling windows, cancellation acknowledgments, and explicit denials of a zero toll. These are measurement changes, not application improvements. The unchanged application scored 91/100 under corpus/harness 3.3.24/2.3.24 and 90/100 under 3.3.25/2.3.25; those contracts are not comparable with the final baseline.

The first zero-denial repair used another wording regex. Ryan challenged that brittle approach, so the final 3.3.27/2.3.27 contract removes both denial phrase filters. The existing Grounding call classifies each suspect money occurrence by meaning; code separately checks numerical support and qualified whole-dollar rounding. A denied amount cannot exempt a later assertion of the same amount, and missing or duplicate classifications invalidate the measurement. Authored classifications support offline validation only and never enter judge inputs. No application instructions or model settings changed.

Final calibration completed 176 references and 528 known calls: 511/516 criterion labels, 176/176 actor labels, and 171/172 effective overall verdicts agreed. All 51 negative controls failed overall. Independent review verified all 15 money occurrences, including paraphrased denials, rejected quotations, mixed assertions, and incorrect rounding. Outcome and Rules falsely penalized one rejected quotation by inferring attribution to the user; this bounded limitation remains recorded. Other criterion disagreements did not change the correct overall failures. The matching actor check passed 100/100.

The final unchanged-application baseline was **85/100**, with all 100 slots scored, no inconclusives, two Grounding violations, and 14 Rules violations. Independent audit found 12 concrete call failures, one actual replacement-day proposal, and two lower-impact wording findings to scrutinize during selection. The baseline was retained without a rerun. Four calibrations, three actor checks, and three baselines cost **$3.111552285** across 4,779 known calls, bringing cumulative spending to **$19.965604020** under the existing **$40.566444520** ceiling. The completed 2.3.26 calibration remains historical, unapproved evidence. Raw runs and detailed decisions remain private; this development evidence does not qualify production.

### 2026-09-27 — Three focused application trials and one confirmation

Using the reviewed corpus 3.3.27 / harness 2.3.27, we tested three SOP changes with gpt-6-luna, 100 cases and one trial per case. The first preserves a direction-specific point with the wrong entry/exit role for the existing validation workflow, rather than switching direction to obtain the desired role. Independent review admitted it as the search incumbent. Two additions were then tested separately from that incumbent: precedence for supplied annual days, and an explicit distinction between a user's Washington corridor choice and the other endpoint's catalog network. Both scored lower and were rejected.

| Run | Successes / fixed slots | Grounding / Rules violations | API cost | Decision |
| --- | --- | --- | --- | --- |
| Fixed starting baseline | 85/100 | 2 / 14 | $0.382828850 | Comparison baseline |
| Direction-specific role validation | 91/100 | 1 / 9 | $0.395632140 | Selected search incumbent |
| Supplied annual-day precedence | 88/100 | 3 / 11 | $0.391773580 | Rejected |
| Explicit Washington corridor choice | 86/100 | 1 / 13 | $0.389641840 | Rejected |
| Single finalist confirmation | 88/100 | 1 / 11 | $0.384671020 | Retain first change |

All runs recorded 100 scored slots and no inconclusives. Final review inspected every lost pass and new violation, the fixed coverage-family sample, all peak disclosures, and all suspect money occurrences. The finalist gained ten baseline passes and lost seven. No demonstrated causal regression was found, but current-price complete requests declined from 17/20 to 15/20 in search and 14/20 in confirmation; annual routes improved from 6/10 to 9/10. A newly incorrect Wiehle entry/exit choice is near the edited mechanism and remains an explicit concern. The identical candidate passed it during search, and the trace does not establish causation. The result is a modest observed development-set gain, not statistical confirmation or production qualification.

Judging remains imperfect. In the rejected annual-day candidate, Grounding falsely inferred personal context from a conditional offer-discussion suggestion; one corrected slot would still leave it below the incumbent. In the finalist, the actor supplied its annual-day choice earlier than its profile allowed, and the actor judge missed that deviation. The resulting failed slot already contributes zero, so treating it as actor-inconclusive would not change the score. All original grades remain intact. These issues are deferred measurement work; no wording workaround or additional paid rerun was used. The audit found the remaining salary-phrase regexes confined to historical contract compatibility; current consent and money meaning are judged semantically.

The retained SOP was evaluated at `c8ad06e4` and published as prompt version 2.3.13. After applying it above the harness repair, all 100 rendered prompt hashes, complete tool schemas, corpus, actor, judge and evaluator identities matched the finalist; only publication commit, artifact and prompt-version metadata changed. The three candidates and confirmation cost **$1.561718580** across 2,672 known calls. Including preparation, this continuation spent **$4.673270865** across 7,451 known calls, bringing the cumulative chain to **$21.527322600** under the unchanged **$40.566444520** ceiling. Detailed decisions and raw evidence remain private. The untested duplicate-network-label hypothesis remains deferred because its motivating failure did not recur in the final baseline.

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

### 2026-09-27 — Follow-up destination-direction description trial

One further round started from the selected direction-role candidate, with corpus 3.3.27 / harness 2.3.27 and gpt-6-luna unchanged. We reused compatible calibration and actor evidence, kept 91/100 as the search threshold, and fixed the incumbent's 88/100 confirmation as the comparison for any new finalist. The candidate changed one current-price destination description: it replaced direction resolution “independently of the origin” with direction appropriate to the requested origin-to-destination route. Earlier unsuccessful direction reminders and the broader four-description trial remained negative evidence. Independent scope review verified that only this existing description changed; 127 focused checks passed with the expected frozen tool-contract digest mismatch.

The candidate scored **90/100**, with all 100 slots scored, no inconclusives, zero Grounding violations and ten Rules violations. It gained five incumbent passes and lost six. Two of four motivating route failures improved, while the other two persisted. Independent review found one false Rules failure for an optional future rerun after a correct annual estimate; even a hypothetical correction would only tie 91/100, so the recorded score remains unchanged and the candidate is rejected. Other losses were substantive route, clarification, annual-day and source-description failures, without demonstrated causal attribution to the patch. All five peak-bearing answers disclosed peak pricing. No completed current-price call crossed facility prefixes, leaving that compatibility concern untested.

No application change was retained, and no finalist rerun was needed. This is the third consecutive rejected candidate since the last promotion; publication does not reset the plateau count. The evaluated commit was `8cd3772b`; the findings layer above #624 preserves its selected application and all measurement content. The run cost **$0.397858760** across 677 known calls, bringing cumulative eval spending to **$21.925181360** under the unchanged **$40.566444520** ceiling. Persistent route selection and unnecessary clarification remain leads requiring materially different evidence before another wording trial. Detailed decisions and raw evidence remain private.

### 2026-09-27 — Reject a facility direction rule and review the plateau

After Ryan requested continued experiments, a second direction trial added the Dulles Toll Road's concrete orientation beside the existing Greenway rule: eastbound toward I-66 and westbound toward Route 28. The rule matches the pinned points and route validator, and differs from earlier generic direction reminders. Corpus 3.3.27 / harness 2.3.27 and gpt-6-luna remained fixed. Independent scope review passed; 82 focused checks passed with the expected frozen prompt digest mismatch.

The candidate scored **85/100** against the 91/100 search incumbent, with 100 scored slots, no inconclusives, three Grounding violations and 14 Rules violations. It gained five passes and lost eleven. One targeted Dulles Toll Road trip improved, while the other still chose the wrong direction; other Dulles and Greenway trips failed. Independent review found substantive coverage, source and timestamp errors, but no evidence establishing that the added rule caused the losses. No decision-changing measurement defect required repair. The patch was rejected and no finalist was run.

This fourth consecutive rejection triggered an offline plateau review. The cluster and reviewer found one materially different lead: annual departure times leaking into current-price requests. A mixed-workflow answer attributed a current quote to an earlier annual departure time, and an incumbent current-only answer unnecessarily requested a departure time. They supported one focused test of intent-specific input and timestamp instructions, while preserving the existing past/future-price refusal. No further direction wording variation was admitted. The rejected trial evaluated `9f84e146`, cost **$0.395742250** across 669 known calls, and brought cumulative spending to **$22.320923610**. This findings layer retains the existing application; raw evidence remains private.

### 2026-09-27 — Retain current-price time scope after confirmation

The plateau review led to one focused SOP change: explicitly scope the annual input list and keep annual departure times out of current-price requests. Current pricing retains the route/profile, needs no departure-time question, and uses returned observation/evaluation timestamps. The selected direction-role change remains; rejected direction additions are excluded. Corpus 3.3.27 / harness 2.3.27, gpt-6-luna and the reviewed calibration remain fixed.

| Measurement | Successes / 100 | Grounding / Rules violations | API cost |
| --- | --- | --- | --- |
| Prior search incumbent | 91 | 1 / 9 | Previously recorded |
| Fixed continuation confirmation baseline | 88 | 1 / 11 | Previously recorded |
| Current-time candidate | 93 | 1 / 7 | $0.397169900 |
| Single finalist confirmation | 91 | 1 / 9 | $0.389115780 |

Both new runs scored all 100 slots without inconclusives. Independent review cleared the search gain and the single confirmation against the 88/100 baseline fixed before this continuation; the original 85/100 baseline remains separate. The finalist gained eight passes and lost five. All nine failures were route-argument errors, with no demonstrated causal regression from the edit. The targeted annual-to-current answer used the returned 8:09 observation and 8:18 evaluation in both runs. Annual collection and reverse transitions remained intact; all six peak-bearing finalist responses disclosed peak, and regenerated money catalogs contained no suspect amounts.

The recorded Grounding violation duplicates a route-selection finding and does not change the mechanically failed slot. Two gained cases revisit cancellation-wording and early actor-release limitations in the incumbent, so the three-point difference cannot be attributed wholly to the prompt. Explicit past/future current-price requests are absent from this development set; the refusal remains unchanged in source but was not measured here. This is a modest observed development gain, with persistent route-direction failures and sampling uncertainty, not production qualification. No further paid rerun was used.

The candidate and finalist evaluated `8a747194`; publication advances the prompt to 2.3.14. All 100 rendered prompt hashes, tool schemas, corpus, actor, judge and evaluator identities match after publication changes. Independent package review found only SOP and prompt-version changes in the timed-check package; schemas, dependencies and loader/publisher hashes are unchanged. The existing contract, package and canary pins were updated; 461 focused checks, corpus validation, contract advancement, Ruff and the local release-manifest verifier passed. These two runs cost **$0.786285680** across 1,349 known calls. Including the two rejected direction trials, the follow-up spent **$1.579886690** across 2,695 known calls, bringing cumulative eval spending to **$23.107209290** under the unchanged **$40.566444520** ceiling. CI observation stopped at the request of Ryan; raw evidence and detailed decisions remain private.

### 2026-09-27 — Reject the annual-origin description trial

The next continuation kept the selected application, corpus 3.3.27 / harness 2.3.27 and gpt-6-luna. Before testing, we fixed the search threshold at 93/100 and any new finalist comparison at the prior 91/100 confirmation. One description change clarified that an annual origin is normally an entry or airport, while exact wrong-role matches follow the existing SOP validation flow. This addressed a specific conflict between the schema description and the SOP; earlier unsuccessful direction and broader description edits remained negative evidence. Independent scope review and offline validation passed.

The candidate scored **87/100**, with all 100 slots scored, no inconclusives, two Grounding violations and eleven Rules violations. It gained three passes and lost nine against the search incumbent. The targeted Gallows origin was correct in all three sibling cases; two completed successfully, while the cancellation case failed on a different return-origin ID. Other losses involved directions, endpoint roles, changed return endpoints and premature Washington pricing. This supports the local hypothesis but does not establish an overall gain or causal attribution for the losses.

Independent review found two nondecisive Grounding limitations: conditional offer-related advice was mistaken for an asserted personal circumstance, and returned restart metadata was mistaken for permission to offer the prohibited annual restart workflow. Correcting both hypothetically would yield only 89/100, so all grades remain unchanged. All six peak-bearing responses disclosed peak, and the sole suspect money occurrence was correctly classified as qualified rounding. No further distinct hypothesis was supported. We rejected the edit, skipped a finalist rerun and retained prompt 2.3.14. The trial evaluated `ba396e7c` and cost **$0.387398700** across 665 known calls, bringing cumulative spending to **$23.494607990** under the unchanged **$40.566444520** ceiling. This findings layer changes only the journal; raw evidence remains private and CI monitoring remains stopped.

### 2026-09-27 — Test consistent itinerary confirmation

After Ryan requested further experiments, renewed review found a conflict between two SOP sections: one required confirmation whenever commute legs served different areas, while the other required it only when the user had not already confirmed those legs. One focused edit aligned the first instruction with the second. Corpus 3.3.27 / harness 2.3.27, gpt-6-luna, the 93/100 search incumbent and the 91/100 confirmation baseline stayed fixed; the rejected annual-origin edit was excluded.

The candidate scored **89/100**, gaining two passes and losing six against the search incumbent. All 100 slots were scored, with no inconclusives, one Grounding violation and eleven Rules violations. Independent review found that the intended confirmation behavior improved in sampled cases, while required split-office confirmation, cancellation and ramp-selection consent remained intact. Endpoint failures persisted. The known cancellation-wording disagreement could not reverse rejection. Another answer promised a replacement annual-day estimate despite a supplied count, although its eventual tool call retained that count. All six peak-bearing responses disclosed peak, with no suspect money occurrences. We rejected the edit and skipped a finalist rerun. The trial evaluated `5ab2222a`, cost **$0.398036080** across 668 known calls and brought cumulative spending to **$23.892644070**. Detailed evidence remains private.

### 2026-09-27 — Reject Dulles Toll Road longitude inference

A separate SOP trial inferred direction from the catalog longitude for distinct, resolved locations wholly on the Dulles Toll Road. Offline review verified all 44 endpoint records across 11 locations against the runtime eastbound order. The rule preserved explicit directions, exact IDs and wrong-role validation, applied independently to annual legs, and excluded cross-facility trips and the Greenway, whose longitudes are not monotonic. This tested numerical evidence use instead of the previously rejected landmark mnemonic. The measurement contract and selected application base stayed fixed; the rejected confirmation edit was excluded.

The trial scored **86/100** against the 93/100 search incumbent, with one gain and eight lost passes. All 100 slots were scored, with no inconclusives, one Grounding violation and fourteen Rules violations. Spring Hill to Reston improved, while two other recurring westbound Dulles trips still selected eastbound points. Passing controls covered eastbound trips, corrected origins, explicit westbound annual legs and cross-facility annual routes. One Greenway request invented Dulles Toll Road point IDs; this could reflect interference, but the single run does not establish causation. Other losses involved wrong endpoints and missed clarification. Independent review found no new decision-changing actor or harness defect. The known cancellation-wording disagreement remained nondecisive, all six peak-bearing responses disclosed peak, and no money-classification issue appeared.

We rejected the edit and retained the application confirmed at 91/100, with no finalist rerun. The trial evaluated `1c6a2546`, cost **$0.386419630** across 659 known calls and brought cumulative spending to **$24.279063700** under the unchanged **$40.566444520** ceiling. Together, these two trials cost **$0.784455710** across 1,327 known calls. No further prose hypothesis was supported. A concrete deferred experiment would constrain endpoint IDs to the actual catalog while preserving valid wrong-role IDs for validation; it requires separate schema/runtime scope and baseline planning, and cannot fix selection of a wrong but valid endpoint. This publication changes only the journal, preserves the selected application, and leaves raw evidence private. CI monitoring remains stopped.

### 2026-09-27 — Research-guided record selection and plateau review

Ryan requested continued search on the same PR and suggested Exa. Research supplied two new leads: structured parameter selection from [a tool-calling study](https://arxiv.org/html/2509.18076v1), and explicit textual spatial relationships from [ItinBench](https://arxiv.org/html/2603.19515). Those studies use other models and tasks, with mixed results; they motivate experiments rather than establish TollChat improvements. Local review supported separate tests of complete-record ID copying and complete Greenway location order. The application remained gpt-6-luna on corpus 3.3.27 / harness 2.3.27, with compatible calibration reused.

The first candidate added five SOP lines directing the model to select a whole catalog record and copy its ID unchanged. It scored **83/100** against the 93/100 search incumbent, with one gained pass and eleven lost passes. All 100 slots were scored, with no inconclusives, one Grounding violation and sixteen Rules violations. The motivating invented Gallows Road entry persisted, and valid-ID direction errors remained. Independent review confirmed an actual unsupported source claim and an attempted call with a guessed missing origin. The known false failure for an annual restart refusal could not change rejection. All six peak-bearing responses disclosed peak, with no suspect money occurrences. We rejected the edit and did not run a finalist.

This fourth consecutive rejection triggered an offline plateau review. Both reviewers supported one distinct test of the complete ten-location Greenway order from authoritative route data: it supplies spatial relationships instead of repeating ID checks, a landmark mnemonic or longitude arithmetic. The proposed scope preserves catalog role availability, explicit directions, exact IDs, separate annual legs and consent, and excludes cross-facility routing. The record-copy trial evaluated `47466ed3`, cost **$0.397221470** across 651 known calls and brought cumulative spending to **$24.676285170**. Detailed research notes and raw evidence remain private; PR #629 remains the publication vehicle.

### 2026-09-27 — Complete Greenway order

The next SOP trial supplied the complete ten-location Greenway order, using authoritative route data rather than example trip answers. It scored **91/100** against the unchanged 93/100 search incumbent, with five gains and seven lost passes. All 100 slots were scored, with no inconclusives, two Grounding violations and eight Rules violations. All priced current Greenway cases passed, including the two targeted return trips; unrelated gains and losses limit any causal claim. Remaining mistakes included reversed Dulles Toll Road legs, invented endpoint variants and a reversed Beltway return.

Independent review verified complete accounting and unchanged measurement identities. The known cancellation-wording disagreement remained nondecisive, and a claim of 36 observations for each weekday overstated the returned 12 per weekday. All seven peak-bearing responses disclosed peak, and no suspect money catalogs occurred. We rejected the edit and skipped a finalist rerun. The trial evaluated `3617bbff`, cost **$0.393602780** across 677 known calls and brought cumulative spending to **$25.069887950**. Both reviewers supported one separate, complete Dulles Toll Road order trial from the unchanged incumbent, preserving facility boundaries, explicit directions, catalog roles and consent. Earlier unsuccessful Dulles mnemonic and longitude trials remain negative evidence.

### 2026-09-27 — Complete Dulles Toll Road order

A separate SOP trial supplied all eleven Dulles Toll Road locations in authoritative eastbound order, restricted to distinct resolved stops on that road. It scored **88/100** against the unchanged 93/100 search incumbent, with two gained passes and seven lost passes. There were 99 scored trials, one actor-inconclusive trial, no Grounding violations and eleven Rules violations. The inconclusive slot remains in the 100-slot denominator. Beltway to Wiehle improved, but Wiehle to Fairfax Parkway still mixed eastbound and westbound endpoints. Other losses included wrong directions, premature Washington pricing and invented Dulles IDs for a Greenway location.

Independent review confirmed the inconclusive classification: the assistant offered an incorrect direction and the actor adopted it contrary to its profile. The unnecessary clarification and wrong direction remain observable application errors. Two debatable Rules failures concern wording about fixed-rate sampling and a conditional request to confirm an already stated round trip; even crediting both and the inconclusive slot would only yield 91, below the required 94. All six peak-bearing responses disclosed peak. All money catalogs reproduced, and both classified amounts were valid qualified whole-dollar approximations. Review found no decision-changing measurement defect. We preserved all grades and rejected the edit without a finalist rerun.

The trial evaluated `a8c07e24`, cost **$0.391493420** across 670 known calls and brought cumulative spending to **$25.461381370**. The three research-led trials cost **$1.182317670** across 1,998 known calls. All five trials documented in PR #629 cost **$1.966773380** across 3,325 known calls, leaving **$15.105063150** under the unchanged ceiling. Both reviewers recommend ending this prose-search batch: the mnemonic, longitude, record-copy and complete-order results do not support another nearby wording variant. A broader structured catalog or route-record selection experiment remains deferred pending separate implementation scope and measurement-baseline planning. We retain the application with its prior 93/100 search score and 91/100 confirmation, update the same PR with findings only, and keep detailed evidence private.

### 2026-09-27 — Lossless catalog rendering: fresh baseline

Ryan authorized broader exploration in the same PR after the prose trials plateaued. We selected a small application renderer experiment: place each complete endpoint record on one JSON line, retaining all 220 records, fields and order. The prototype reduces catalog text from 82,694 to 57,825 characters, with synthetic round-trip and determinism tests plus full-catalog equality checks. Enum restrictions could prevent invented IDs but would not prevent wrong valid endpoints; a runtime resolver would require a different test boundary because frozen replay replaces pricing-tool execution.

Before testing the renderer, we reserved development renderer version 1.0.1 and verified all 100 prompts remained byte-identical to the selected application. This fresh baseline scored **82/100**, with all slots scored, no inconclusives, one Grounding violation and sixteen Rules violations. Independent review found sixteen genuine route or clarification errors and two bounded judging disagreements: misreading a qualified denial of modeled prices, and treating unavailable annual toll totals as a claim that no historical records exist. The fixed family sample, all failures, five peak disclosures and all money catalogs were reviewed. No measurement blocker was found; all grades remain unchanged.

The lower result demonstrates substantial variation from the prior 93/100 search and 91/100 confirmation. We did not retry it or lower either historical bar: the new candidate still needs at least 94 successes, followed by one confirmation of at least 92. Corpus 3.3.27 / harness 2.3.27, tool schemas, actors, judges and gpt-6-luna remain fixed; compatible calibration and actor evidence were reused. Baseline `0084c489` cost **$0.390976240** across 653 known calls, bringing cumulative spending to **$25.852357610**. The reserved version and exact artifact hashes distinguish this experiment from historical reports without relabeling them.

### 2026-09-27 — Compact catalog result

The lossless record-line renderer scored **86/100** against the fresh baseline's 82, with ten gained passes and six lost passes. All 100 slots were scored, with no inconclusives, one Grounding violation and thirteen Rules violations. Every case used exactly **9,204 fewer first-application input tokens**; the median fell from 33,798.5 to 24,594.5. This establishes a token reduction, but the candidate did not meet the predeclared 94/100 search requirement. We rejected it and skipped confirmation.

Independent review found persistent route and workflow mistakes: wrong directions, premature Tysons pricing, an invented missing origin and an unsupported claim that an excluded midday trip was untolled. Two gained passes concern the baseline's judging disagreements and do not establish a renderer benefit. One reverse-Greenway loss has uncertain attribution because the actor selected a Dulles Toll Road origin after unnecessary clarification, conflicting with the frozen Greenway route; its recorded grade remains unchanged. All four returned peak components were disclosed. All money catalogs reproduced, including the correctly classified denial of a zero-dollar toll. No decision-changing measurement repair was required.

Candidate `b61da24a` cost **$0.358741040** across 656 known calls. Including the fresh baseline, this exploration cost **$0.749717280** across 1,309 known calls; cumulative spending is **$26.211098650**, leaving **$14.355345870** under the existing ceiling. The candidate passed corpus validation, 83 focused checks, 15 comparison checks and formatting/lint checks, with the expected unpublished renderer-version snapshot mismatch. Tests verified semantic round-trip equality rather than exact catalog whitespace. The compact-format search stops here: this run does not justify another representation variant, and token savings alone do not satisfy the accuracy objective. The selected application, its prior 93/100 search and 91/100 confirmation, and all historical grades remain unchanged. PR #629 publishes these findings only; prototype branches and detailed evidence remain private.

### 2026-09-27 — Three-trial reliability report for the 93-point candidate

Ryan requested observed pass³ and the metrics used by former gates in a new stacked PR. The unchanged current-time candidate was measured once on all 100 development cases with three fresh repetitions under corpus 3.3.27 / harness 2.3.27. Only an isolated manifest's repetition count changed; all 100 prompt hashes, tool schemas and model settings match the selected application. Matching calibration completed 176 references and 528 known calls, with 512/516 criterion-label agreement, 176/176 actor agreement and all 51 negative controls rejected. Existing actor-check evidence was reused under unchanged actor inputs. The known rejected-quotation false failure remained; arithmetic checks still rejected incorrect rounding missed by the raw judges.

The diagnostic scored **257/300 (85.7%)**, with **68/100 cases passing all three attempts (68% pass³)**. Repetition scores were 82, 85 and 90; the numbers of cases passing zero, one, two or three times were 3, 5, 24 and 68. All 300 slots were measured: 299 scored and one actor-inconclusive. Grounding and Rules counts were 3/299 and 39/299; the inconclusive slot carried another observed Rules finding. Independent review confirmed the aggregates, complete accounting and supplemental scenario-bootstrap intervals of 80.7%–90.3% for fixed-slot success and 58.6%–77.0% for pass³. The canonical success interval remains null because of the inconclusive; original grades were preserved.

The result misses the former 90% success, 75% pass³ and critical-case 3/3 requirements. Numerical cost and latency limits are met, but historical qualification conditions and relative promotion gates are not established by this diagnostic. Current-price requests were weakest at 93/120 successes; annual requests scored 149/165 and mixed workflows 15/15. The actor-inconclusive judgment is debatable, and the known annual-restart grading disagreement remains visible. No replacement run, application change or production qualification followed. The [detailed report](CURRENT_TIME_RELIABILITY_2026-09-27.md) includes case consistency, family breakdowns, former-gate interpretation, costs, latency, uncertainty and review limitations.

Diagnostic commit `5d7bce6d` cost **$1.156873140** across 1,999 known calls. Matching calibration cost **$0.414687240**, making this task **$1.571560380** across 2,527 calls. Cumulative spending is **$27.782659030**, leaving **$12.783785490** under the existing ceiling. The application and active single-pass defaults stay unchanged; only the requested aggregate report and this journal summary are published, with raw evidence private. CI monitoring remains stopped.

### 2026-09-27 — Three-trial climb: cancellation candidate

This campaign starts from the retained application measured at **257/300 successes and 68% pass³**, aiming for at least 271/300 in one separate final verification. We reused the reviewed three-trial calibration and actor evidence after reproducing all 100 prompt hashes, full tool schemas and measurement identities. Corpus 3.3.27 / harness 2.3.27, gpt-6-luna and its settings remain fixed. Every candidate uses 100 cases × three repetitions and 16 workers; the ordinary development default remains one repetition. Inconclusives count as zero success. The cumulative ceiling stays **$40.566444520**, with $2 reserved for final verification.

The first candidate adds a generic instruction to stop clarification and pricing after explicit cancellation, while preserving corrections and declined alternatives. It scored **265/300 with 75% pass³**, including 299 scored trials and one actor-inconclusive. Scored Grounding/Rules violations were **2/299 and 33/299**; the inconclusive carried another observed Rules finding. Family successes were annual complete **55/60**, annual inputs **42/45**, annual interpretation **30/30**, annual routes **24/30**, current complete **45/60**, current evidence **28/30**, current state **28/30**, and mixed **13/15**. Whole-trial latency was **27.06 seconds p50 / 43.68 seconds p95**.

Independent review inspected all 24 lost passes, 23 new Rules observations, two new Grounding observations and the inconclusive. Genuine route, timestamp and annual-day errors remain, but the cancellation-only change does not establish their cause. Some judge explanations misread route fields; separate mechanical failures preserve those failed outcomes. The target cancellation case improved from 2/3 to 3/3, although the actor did not reproduce the original cancellation-plus-restatement wording, so this is not controlled proof of the mechanism. We retained this candidate for search, pending final verification. Commit `4f11bfd2` cost **$1.160645310** across **2,002 known calls**, bringing cumulative spending to **$28.943304340**. Original grades and detailed evidence remain private and unchanged.

### 2026-09-27 — Directed catalog relationships

A separately scoped renderer candidate added same-facility exit IDs to Dulles Toll Road and Greenway entry records. Semantic tests preserved all 220 records, fields and ordering and reproduced all **189 canonical directed pairs**. The rendered catalog grew by 6,639 characters. An independently reviewed, opt-in `directed-catalog-v1` comparison policy pins the source graphs, tool schemas and application code outside the bounded renderer change. It preserves historical comparison behavior. Frozen evaluation executes this renderer; pricing runtime, replay, judges and actors stayed unchanged, so the reviewed calibration and fixed baseline remained compatible.

The candidate combined these relationships with the retained cancellation rule and scored **260/300**, below the 265/300 incumbent, despite higher **78% pass³**. All 300 slots were scored, with no inconclusives, **3 Grounding and 39 Rules violations**. Family successes were annual complete **55/60**, annual inputs **44/45**, annual interpretation **29/30**, annual routes **21/30**, current complete **43/60**, current evidence **29/30**, current state **28/30**, and mixed **11/15**. Whole-trial latency was **27.23 seconds p50 / 39.80 seconds p95**.

Independent review read all 40 failed trajectories, covering every lost pass and new violation against both the incumbent and fixed baseline. The candidate gained 19 slots and lost 24 against the incumbent. Reversed directions and wrong endpoints persisted; new Grounding findings involved an invented endpoint, calling observed data modeled, and a lower-severity personal-context presupposition. No response treated topology as live availability or consent. We rejected this candidate and retained cancellation alone. The next admitted hypothesis explains the new relationship field, which the existing SOP does not describe; it requires a separate complete run as a combined candidate, without overwriting this result.

Candidate `0bdf0a5d` cost **$1.148724370** across **1,958 known calls**, bringing cumulative spending to **$30.092028710** and leaving **$10.474415810**. Renderer version 1.0.2 is experimental at this point; the ordinary single-pass default remains unchanged. Raw reports, original grades and rejected candidate sources remain private.

### 2026-09-27 — Catalog relationships with selection guidance

The third candidate combines the retained cancellation rule with the directed catalog and a focused explanation of its new field. It tells the agent to keep both requested locations, choose the entry and exit direction variants together, and handle annual legs independently. Explicit directions, wrong-role validation, separately supplied returns and consent remain authoritative. This combination was evaluated afresh from the retained incumbent under the same `directed-catalog-v1` comparison policy.

It scored **274/300 with 83% pass³**, gaining 23 slots and losing 14 against the 265/300 incumbent. All 300 trials scored, with no inconclusives, **2 Grounding and 25 Rules violations**. Family successes were annual complete **58/60**, annual inputs **42/45**, annual interpretation **28/30**, annual routes **25/30**, current complete **48/60**, current evidence **30/30**, current state **29/30**, and mixed **14/15**. Whole-trial latency was **28.00 seconds p50 / 43.14 seconds p95**.

Independent review inspected all 26 failures and successful controls for cancellation, wrong-role alternatives, cross-facility handling and separate returns. It found no demonstrated material regression. Two source-versus-sampling wording disputes remain recorded as failures and do not change selection. Three recurring direction cases still failed all repetitions, and returned-alternative scenarios scored **5/9**, versus **7/9** in the fixed baseline; the aggregate gain does not establish that those weaknesses were fixed. We selected this candidate for one final verification and deferred a direct location-pair lookup proposal without testing or claiming its benefit.

Candidate `46476e87` cost **$1.183361570** across **2,017 known calls**. Cumulative spending reached **$31.275390280**, leaving **$9.291054240** under the unchanged ceiling. The search result exceeds the 271/300 target; only the separate final verification determines the delivery claim. Original grades and detailed evidence remain private.

### 2026-09-27 — Final verification of the catalog candidate

The selected application received one separate run on all 300 slots, with the same evaluated commit, corpus 3.3.27 / harness 2.3.27, model settings and calibration. It scored **269/300 with 78% pass³**: twelve successes above the fixed baseline, five below its selected search result, and two short of the **271/300** target. All 300 trials scored, with no inconclusives, **0 Grounding and 31 Rules violations**. The completed result was preserved without a retry; Ryan accepted this outcome.

| Measure | Fixed baseline | Selected search | Final verification |
| --- | ---: | ---: | ---: |
| Successes | 257/300 | 274/300 | 269/300 |
| Pass³ | 68% | 83% | 78% |
| Scored Grounding violations | 3/299 | 2/300 | 0/300 |
| Scored Rules violations | 39/299 | 25/300 | 31/300 |
| Inconclusives | 1 | 0 | 0 |

The baseline inconclusive carried one additional observed Rules finding. Final family successes were annual complete **57/60**, annual inputs **42/45**, annual interpretation **28/30**, annual routes **23/30**, current complete **46/60**, current evidence **30/30**, current state **28/30**, and mixed **15/15**. Annual routes remain weaker than the fixed baseline's **26/30**. Whole-trial latency was **25.98 seconds p50 / 42.84 seconds p95**. The final run gained 31 slots and lost 19 against baseline; trial numbers do not identify paired random draws.

Final verification cost **$1.158477940** across **2,004 known calls**. The three candidates and final run cost **$4.651209190** across **7,981 known calls**, bringing cumulative spending to **$32.433868220** and leaving **$8.132576300** under the unchanged **$40.566444520** ceiling. All started calls were reconciled. Reused preparation incurred no additional cost; Codex agent usage is separate.

Independent final review covered all 31 failures, passing counterparts for lost slots, and the prescribed first passing and failing trajectory in every coverage family. It found no decision-changing grading ambiguity or demonstrated material regression attributable to the change. Genuine route failures remain: two trials chose the wrong Jones Branch variant and another changed a separately supplied return route. Returned-alternative scenarios finished **6/9**, versus baseline **7/9** and search **5/9**. All seven other coverage families equaled or improved on baseline. We retain the application under the agreed above-baseline rule, with the target explicitly unmet.

Publication advances prompt metadata to **2.3.15** and renderer **1.0.2**, preserving historical release hashes. All 100 rendered prompt hashes, full tool schemas, model settings, measurement inputs and SOP bytes match evaluated commit `46476e87`; application source differs only in the prompt version literal. The ordinary one-repetition default is restored. Validation passed 87 focused application/development tests, 16 comparison tests, corpus validation, contract-version checks, lint and type checks; earlier campaign preparation also passed the relevant runner/accounting checks. Detailed evidence stays private. These results measure the exposed development set under frozen replay and do not establish live pricing correctness or production qualification.

### 2026-09-27 — Private holdout transfer and release tooling

Prepared authoring kit **1.0.2**, separate author/evaluator containers, and a private
100-case, three-trial evaluator for the exact delivered ARM64 application. The
author sees public contracts and synthetic teaching examples. The evaluator
calibrates all authored references, rehearses actors, preserves cumulative
spending and unsuccessful attempts, and exports aggregate evidence only. Policy
**4.0.0** uses protected GitHub review of that aggregate instead of an external
signer, retaining the 240/300 threshold, complete-measurement requirement,
$5 execution/$25 cumulative limits, and 24-hour freshness window.

Shared transport and reference-calibration changes advance the development
contract to **3.3.28 / harness 2.3.28**. Development cases, application SOP, and
application model are unchanged. The previous calibration approval remains
historical; the new contract's review is pending. Focused offline tests, corpus
validation, type/lint checks, and workflow checks passed. Container checks verified
the author image's allowlist and blocked repository/package/direct network access
while permitting the model API. The delivered candidate's checksum and package
inventory also passed validation. ARM64 execution still requires the private
machine's emulation preflight; these checks establish no candidate quality score.

No real holdout was authored or evaluated, no paid inference was used, and no
cloud changes were applied. Private authorship/review, calibration, approval of
the three exact policy identities, workflow delivery, and a separate foundation
IAM apply remain prerequisites to production qualification. The transfer files
and granular verification output stay in ignored local storage; current operation
is documented in [HOLDOUT_SETUP.md](HOLDOUT_SETUP.md).

### 2026-09-28 — Remove private evidence expiry

Corrected the pending **4.0.0** release policy to remove the 24-hour expiry on
private evaluation evidence. The previous entry describes the original policy;
qualification now remains bound to the exact artifact, active policy, and human
approval without an evaluation-age limit. Release verification still depends on
workflow artifacts retained for 90 days. Synthetic checks cover delayed import, approval,
and production revalidation; no private evaluation or deployment was run. The
saved Terraform plan retains its separate 24-hour expiry.

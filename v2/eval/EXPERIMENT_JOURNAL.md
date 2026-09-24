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

## 2026-09-24 — Calibrate the new 100-case development corpus

Ryan authorized opening [PR #596](https://github.com/rhprasad0/nova-toll-budget-agent/pull/596)
and then running calibration, specifying **16 parallel workers**. The PR was
opened ready for review before this run. Calibration used the clean committed
source `c3c7f3dfbf0fe9cf3e1bf112fe26d21990911df1`, corpus **3.0.0**, the existing
judge prompts/model, and a $25 spending ceiling. No application trial or holdout
was executed, and no retry or replacement run was needed.

**All 120 references were measured**, with 360 judge calls, no measurement
failures, and no unknown usage. Recorded cost was **$0.20523038**. All authored
actor-validity labels measured valid; this does not test live actor simulation.
Judges agreed with 347 of 360 authored criterion labels (96.4%), leaving
**13 disagreements across 12 references**. Ten proposed passing references
received at least one false verdict; two negative controls had criterion-level
disagreements. None of the 20 negative controls passed all three judges. These
are calibration agreements, not application accuracy measurements.

The [review packet](evidence/golden-100/README.md) preserves each disagreement,
the unmodified raw manifest/events/reports, and a cost/file-hash receipt. Agent
analysis identifies invented disclosure requirements, missed earlier dialogue,
a boolean/explanation contradiction, and an annual restart-rule mismatch.
The divergent-area Grounding judgments and day-adjustment Outcome/Rules split
need human adjudication. Outcome missed one incorrect financial label that the
other two judges rejected. No case, fixture, reference label, evaluator prompt,
or measured verdict was changed in response to these results.

Run ID: `a2326672-12e8-4a66-b1b3-9614aa2e05ce`.
Corpus SHA-256: `e68d04094648deeb7d1b40c01a9e6d5fe4ec827077c2e1e6d000f889340614be`.
Evidence SHA-256: `60a97742365f6a987434a1e1ee68d2b8491a83e36b796734a63c5c7bfe3d634c`.
Corpus and calibration approvals remain **pending human review**. Historical
approvals do not transfer, no application score is claimed, and the development
corpus remains ineligible for production qualification.

## 2026-09-24 — Review correction: commute shorthand and five-turn actors

Ryan accepted generic home/work-area labels for the supplied commute legs as a
useful simplifying assumption, while agreeing that the original Grounding judge
had identified an assumption. This is a deliberate grading relaxation, not a
claim that the earlier judge lacked a basis. It does not permit invented personal
addresses, employers, financial/schedule facts, changed routes, or unconfirmed
combination of different areas. The cases keep the user's exact requested legs.

Ryan also requested a maximum of **five delivered user turns** for the actor.
The previous maximum was four in all 100 cases. The value two shown for the
split-itinerary cases was their minimum dialogue requirement and the length of
their authored reference transcripts, not a hidden two-turn cap. Calibration
contained exactly those two exchanges and did not execute a live actor.

Corpus **3.0.1** and harness **2.0.9** implement the requested policy and five-turn
maximum, including the opening user request. Minimum required turns, tool-call
budgets, reference labels, reference transcripts, fixtures, and the application
model/prompt remain unchanged. The existing real-simulator offline test now
covers both two- and five-turn limits, completion on the final turn, and the
distinction between actor invalidity and application budget failure.

Original 3.0.0 calibration events and reports remain intact. These specific
review decisions do not approve the complete corpus or calibration; a fresh
matching calibration is required for 3.0.1. Case 65's negative-control label
boundary is unchanged and still requires adjudication.

### Matching 3.0.1 calibration

Following the requested review changes and the earlier instruction to calibrate
the new corpus, the matching run used **16 workers**, source
`893f990896541b166d434bcfbf50c55ff23bf38e`, and the existing $25 cumulative ceiling.
All **120 references and 360 judge calls completed**, with no measurement errors,
unknown usage, or retries. Cost: **$0.20711386**, bringing cumulative calibration
spending to **$0.41234424**. All authored actor-validity judgments were valid.

There are **nine label disagreements across eight references** (351/360 agreement
against authored labels, 97.5%). Both split-itinerary references now pass
Grounding. None of the 20 negative controls passes all three judges. Changes in
the other verdicts include variation on unchanged references and are not a
controlled estimate of general evaluator improvement. Remaining disputes concern
invented disclosure/repetition requirements, the prohibited annual restart offer,
and the still-unadjudicated day-adjustment negative control.

The [second review packet](evidence/golden-100/CALIBRATION-2.md) preserves the exact
new evidence; the [static page](evidence/golden-100/review.html) displays complete
reference transcripts and separates their length from the minimum and maximum
turn counts. The original calibration is retained. No application or live actor
run was performed; the five-turn limit was verified offline with the real actor
simulator and stubbed model responses. **183 relevant offline tests passed**, as
did repository static checks, usage/hash reconciliation, and byte-for-byte report
reproduction. Corpus and calibration approval remain pending.

Run ID: `7ca8b992-4b8d-4d0a-a588-733099d1699e`.
Corpus SHA-256: `163df82345afa1e55bd9e398529d7f2f94ba3ddb435d6b9af06f546764d1ade9`.
Evidence SHA-256: `46a23c3853563342f889fc74f3cd1e7f6723d9334ac9a4ec93f5ed9164900301`.

## 2026-09-24 — Make cases 79/80 more realistic

Ryan requested more realistic versions of the split-itinerary cases. Corpus
**3.0.2** moves the morning home-side entry from Prince William Parkway to Old
Keene Mill Road in Springfield, retaining the evening return via Braddock Road.
The home-side ramps are about **3.02 straight-line miles apart**, versus 11.19
before. Both priced legs are committed within-facility Oracle connections.

Case 79 now confirms a plausible morning client visit near the Pentagon followed
by work at the Tysons office, pricing only the two requested commute legs. Midday
travel between work sites is explicitly excluded. Case 80 catches accidentally
mixing routes for two office options and cancels before any pricing call. Both
retain the five-turn maximum and two-turn minimum; their reference transcripts
remain two exchanges. The premature-combination negative control follows the
same revised route but still calls before confirmation.

The one dependent fixture and its two embedded copies were updated. Straight-line
tolled distance was rebuilt from committed endpoint coordinates (16.449026 miles)
and the annual domain builder recalculated vehicle costs, combined costs,
remaining income, and gross salary offsets. The historical toll quantiles remain
explicitly synthetic. Only these two cases and their three references changed;
the other 98 cases, judge policy, application prompt/model, and old calibration
evidence remain unchanged. All **42 relevant corpus/development tests passed**,
including fixture replay, financial reconciliation, and committed route checks.
Matching calibration and human approval remain pending for this revision.

### Matching 3.0.2 calibration

The matching run used source `257050f4871dee06382111f8e2b7931c986c5bff`,
**16 workers**, and the existing $25 cumulative ceiling. All **120 references
and 360 judge calls completed**, with no measurement failures, unknown usage,
or retries. Cost was **$0.19802250**, bringing cumulative spending to
**$0.61036674** across the three contract calibrations.

Both revised passing references pass all three criteria; the linked premature-call
control fails Outcome and Rules while passing Grounding, exactly as labeled.
There are **six disagreements across five other references** (354/360 agreement
with authored labels, 98.3%). None of the 20 negative controls passes all three
judges. The other verdict changes occur on unchanged references and are not
evidence of a general improvement. Remaining disputes concern DTR abbreviation,
unused-source disclosures, a missed false financial label, and the unadjudicated
day-adjustment negative control.

The [third review packet](evidence/golden-100/CALIBRATION-3.md) and
[HTML page](evidence/golden-100/review.html) include complete revised transcripts,
financial evidence, and remaining disagreements. Raw prior runs are retained.
Evidence copies, receipt hashes, known usage, corpus identity, and byte-for-byte
report reproduction were verified. No application scoring or live actor run was
performed; corpus and calibration approval remain pending.

Run ID: `3d9aa3b8-953d-4244-a540-9d9e21a8b8db`.
Corpus SHA-256: `544e5d8f7f8bce4dd92aa706b88468515a60af52598535609408c6b49c35e96f`.
Evidence SHA-256: `a541bec759faa64ddb193351e0162ca40389f12da6876f3e0d02231441938fd2`.

## 2026-09-24 — Adjudicate case 65 and clarify judge criteria

Ryan accepted the recommendation to fail both **Outcome and Rules** for case
65's `no-day-adjustment-choice` negative control. A yes/no question about using
156 days omits the required invitation to adjust that proposal. Correctly using
the user's later unsolicited 134-day correction does not cure the missing step;
the omission alone leaves Grounding passing. Only this reference's Outcome label
and rationale changed. All 100 case definitions, 120 reference transcripts, and
107 fixtures remain unchanged from 3.0.2.

Corpus **3.0.3**, harness **2.0.10**, clarifies shared judge guidance: recognizable
road abbreviations such as DTR are acceptable when the route is clear; source
disclosure covers sources actually used, not absent flags; and an appended false
financial label violates Rules even after a correct table. The required annual-day
adjustment invitation is explicitly distinguished from final-answer disclosure.
These changes resolve the prior adjudication without replacing any recorded
verdict. The application model/prompt, realistic cases 79/80, and five-turn actor
maximum remain unchanged.

All **92 relevant corpus/development/runner tests passed**, including reference
replay and independent financial reconciliation. Matching calibration is
authorized with 16 workers and the existing $25 cumulative ceiling, including
$0.61036674 already spent; it is pending on this committed source. Corpus and
calibration approvals remain pending. Prior raw measurements remain intact.

### Matching 3.0.3 calibration

The matching run used source `5b93f0c6d45355039928b45546a816c92ff41b1a`,
**16 workers**, and the existing $25 cumulative ceiling. All **120 references
and 360 judge calls completed**, with no measurement failures, unknown usage,
invalid authored actors, or retries. Cost was **$0.20658857**, bringing cumulative
spending to **$0.81695531** across four calibrations.

All five references disputed in calibration 3 now match their labels, including
case 65's approved Outcome/Rules failure. The realistic cases 79/80 and their
premature-call control still match. **Two disagreements across two other
references remain** (358/360 agreement, 99.4%). Case 26's negative control is
incorrectly failed for Grounding as well as its correct Outcome/Rules failures;
case 99's passing no-history/current-price workflow is incorrectly failed for
Outcome by demanding unavailable annual scenarios. These are agent assessments
under the existing criteria, not replacement verdicts. All 20 negative controls
remain rejected overall; Rules matches all 120 labels. Both remaining references
matched in the prior run, so this single result does not establish general judge
reliability.

The [fourth review packet](evidence/golden-100/CALIBRATION-4.md) and updated
[HTML page](evidence/golden-100/review.html) preserve the complete evidence.
The raw report reproduces byte-for-byte from its manifest/events; all four
receipt sets retain their hashes. The page is checked against all 120 exact
transcripts/verdicts, offline loading, keyboard disclosure, valid links, and
mobile layout. No application scoring or live actor simulation occurred.
Corpus and calibration approval remain pending.

Run ID: `e874bb7f-b846-4947-9116-34a07979625d`.
Corpus SHA-256: `596b2f1c7abd0c77087c415da7905b673561011f06c612e9d27a739acad6833f`.
Evidence SHA-256: `c73dde3311a04e73dba293764fb9ffd69f730571d7e4c55d302df2b45d2a5aa6`.

### 2026-09-24 — Authorized repeat of unchanged 3.0.3 calibration

Ryan requested another round of judge calibration. This repeat used source
`1e11b362549f401166e4b7ea1dd8c06131b3f39d`, **16 workers**, and the existing
$25 cumulative ceiling. Corpus, labels, transcripts, fixtures, prompts, model
settings, and evaluator sources match calibration 4. Only the source commit and
complete-checkout hash differ, because earlier evidence and review documentation
were committed between runs. Corpus **3.0.3** and harness **2.0.10** are unchanged.

All **120 references and 360 judge calls completed**, with **zero disagreements**,
no measurement failures or unknown usage, and valid authored actor assessments.
All 100 passing references pass all three criteria; all 20 negative controls
remain rejected, with every criterion matching its expected label. Exactly two
boolean verdicts changed from calibration 4: case 26's negative control now
passes Grounding, and case 99's no-history/current-price reference now passes
Outcome. No labels, transcripts, or judge instructions were changed to obtain
this result. The approved case-65 control and realistic cases 79/80 still match.

Cost was **$0.19815320**, bringing cumulative spending across five runs to
**$1.01510851**. There were no per-reference retries or replacement verdicts in
this run. The previous run's two disagreements remain recorded; a clean repeat
does not establish perfectly reliable judges or application accuracy.

The [fifth review packet](evidence/golden-100/CALIBRATION-5.md) and updated
[HTML page](evidence/golden-100/review.html) preserve the complete latest evidence.
The corpus validator passed, the report reproduces byte-for-byte, and all five
receipt sets retain their hashes. HTML checks cover all exact transcripts and
verdicts, zero disagreements, offline loading, keyboard access, links, and mobile
layout. The 92 tests previously passed for this unchanged evaluator revision;
this repeat changes only evidence and documentation. No application scoring or
live actor simulation occurred. Corpus and calibration approval remain pending.

Run ID: `516a6312-f373-49fe-8726-d26e6eda4109`.
Corpus SHA-256: `596b2f1c7abd0c77087c415da7905b673561011f06c612e9d27a739acad6833f`.
Evidence SHA-256: `6b1931359cacf2d9ffbb1ac9dcf425c44bd3ad56cc6217f70f11d3b547dc4a1b`.

### 2026-09-24 — Approve current corpus/calibration and authorize baseline

After reviewing the zero-disagreement repeat result, Ryan instructed: "Very good.
Now run the new baseline with this set." This approves the current development
corpus 3.0.3 and calibration 5 for the requested application baseline. Exact
approval is recorded in `golden/review.json` and
`evidence/golden-100/calibration-5/review.json` before execution. It does not
approve the application's unmeasured results or qualify production.

The baseline will run **300 fresh conversations**, three per case, with **16
workers**, the existing five-turn actor maximum, and unchanged application model,
prompt, evaluator, cases, and fixtures. The existing **$25 cumulative ceiling**
includes $1.01510851 spent on the five calibrations. The prior-run accounting
links to calibration 5. No trials will be replaced to improve the result.

The approved calibration is staged in an ignored working copy because the runner
renders its approval status before execution. The original committed reports,
events, manifest, and receipt hashes remain unchanged; the new approval is a
separate record. The corpus validator and exact-evidence approval check passed.

### First application baseline on 3.0.3

The authorized baseline completed **all 300 attempts**, three per case, using
source `545d66314b31806e2ec5b09c9a32c65add76d823`, corpus **3.0.3**, harness
**2.0.10**, approved calibration 5, and **16 workers**. Application model/prompt,
judge guidance, cases, fixtures, and the five-turn actor maximum were unchanged.
Actual trials used one turn in 190 conversations, two in 96, and three in 14.

Recorded results: **156 passed, 131 failed, and 13 inconclusive**; **54.4%**
success among **287 scored trials**. Thirty-three of 100 cases pass all three
trials; the renderer's pass³ is **33/89 (37.1%)** among fully scored cases.
The 13 inconclusive trials prevent a complete scored measurement and confidence
interval. Current pricing passes 87/113 scored trials (77.0%); annual affordability
62/160 (38.8%); mixed workflows 7/14 (50.0%). Primary failure counts are Outcome
81, tool use 39, Grounding 9, clarification 2, and actor validity 13.

The four invalid actor assessments comprise two premature stops, one missing
reply, and one refusal to follow a required route selection. Nine uncertain
assessments occur when no actor reply/stop follows an application rejection;
these deserve review under the rule that application failure is not actor fault.
Four scored failures also appear to be deterministic false positives: case 32,
trial 2, and all case-35 trials report a positive magnitude "below" a median,
while the tool stores a negative delta. All three semantic judges pass them,
but the money parser raises `unsupported_money`. No recorded verdict was changed.

Annual Outcome findings commonly concern missing daily toll amounts for each
scenario, price-source disclosure, and forecast/guarantee caveats; some caveat
findings merit semantic-leniency review. Incorrect route direction and timestamp
conversion also occur. Case 80 passes cancellation 3/3; case 79 confirms correctly
in all trials but passes overall 1/3 because of explanation omissions.

The run used **1,964 model calls**, with all starts/finishes and usage reconciled.
There are no infrastructure-status trials or unknown costs. Cost was
**$0.91475671**, bringing cumulative spending to **$1.92986522 of $25**. Median
and p95 full-trial latency were **24.86s / 43.98s**. No failed or inconclusive
trial was retried or replaced.

The existing archive helper preserved all four raw files byte-for-byte after
report reproduction checks. All prior calibration receipt hashes remain intact.
The [baseline report](evidence/golden-100/BASELINE-1.md) and
[static HTML page](evidence/golden-100/baseline-review.html) expose all 300 exact
transcripts, tool evidence, actor records, checks, and judge explanations. Browser
checks cover all transcripts/statuses, all 100 case rows, offline loading,
keyboard access, anchors, and mobile layout. The corpus validator and repository
static checks passed. Human actor/result review remains pending; the production
policy and registry are unchanged.

Run ID: `ed281384-fc39-47a7-88e3-43aa7f947b9c`.
Evidence SHA-256: `53bee6705115716ab80a09766f08c467194871145328502da9af871d110bcf48`.
Archive SHA-256: `c5e327a9c0d2cf9ed49838aac40ce2e93d9ac712e5307395427475a928d0c430`.

## 2026-09-24 — Correct measurement defects before a second golden-100 baseline

Ryan authorized all suggested evaluator fixes and a fresh baseline. Contract 3.0.4 / harness 2.0.11 preserves the 100 development cases, 107 fixtures, and original 120 reference labels. Strands Evals is updated to 1.4.0; its simulator is unchanged upstream. The evaluator now records application termination separately, establishes actor validity when only the approved opening was delivered, rejects blank actor replies, strengthens required clarification/selection instructions, and uses medium actor reasoning. The money parser recognizes below-median deltas, including an intervening percentage and Markdown.

Twelve additional regression references preserve nine application-stop transcripts and three distinct invalid actor behaviors from baseline 1. The resulting 132-reference calibration includes 129 application-labeled references and three actor-only controls. First-baseline verdicts and artifacts remain untouched. Targeted live actor checks and fresh calibration precede the requested new 300-trial baseline; costs will be chained from baseline 1 under the existing $25 ceiling. Application model/prompt and production policy remain unchanged. See `evidence/golden-100/FIXES-BASELINE-2.md` for the correction scope and forthcoming run evidence.

### 2026-09-24 — Actor preflight and calibration 6 completed

Targeted live checks passed 9/9 across cases 23, 58, and 83 with exact first-baseline questions/answer, costing $0.01129344 (27 model calls). Calibration 6 measured all 132 references with 16 workers: 386/387 application labels match, all 132 actor-validity labels match (129 valid, three invalid), no negative control passes overall, no measurement failures, and no unknown usage. The known salary-choice Grounding disagreement is retained without altering its label or measured verdict. Calibration cost $0.22172372; cumulative raw-ledger spend is $2.16288238 including baseline 1 and the preflight. Raw receipts and evidence are archived under `evidence/golden-100/`; application execution is authorized under Ryan's instruction to apply the fixes and run another baseline. Codex reviewed the new measurements; the execution review explicitly does not claim Ryan separately inspected them. Baseline 2 will use the matching unchanged evaluator contract.

The PR checks also exposed two tests that assumed the development corpus still lacked approval. They now check the actual version-specific development approval and create an explicitly pending corpus when testing denial. The development release manifest refreshes only the hashes for the changed dev dependency files; package hashes and deployment behavior are unchanged.

## 2026-09-24 — Second corrected golden-100 baseline completed

The [second baseline](evidence/golden-100/BASELINE-2.md) on corrected contract **3.0.4 / harness 2.0.11** finished with **176 passed, 123 failed, and 1 inconclusive out of 300 trials**; scored-trial success is **58.9% (176/299)**. Its [static review](evidence/golden-100/baseline-2-review.html) contains all 300 conversations. The actor preflight passed 9/9 checks; [calibration 6](evidence/golden-100/CALIBRATION-6.md) matched 386/387 application labels and 132/132 actor labels, retaining one known Grounding disagreement. The 100 cases, fixtures, and application model/prompt are unchanged. Cost was $0.92992747 for this baseline, $3.09280985 cumulative. Original results remain intact; changed evaluation rules and sampling mean score differences do not establish application improvement. Application result review remains pending.

Run `f3aaa5b7-8818-413e-afe0-68c1f1d82989` measured source `118b91f73161d4af94b30a080dc28ed6a48e88a6` with 16 workers. Actor validity counts: `{'valid': 299, 'invalid': 1, 'uncertain': 0}`. Primary failure categories: `{'actor_validity': 1, 'clarification': 4, 'grounding': 4, 'outcome': 64, 'tool_use': 51}`. No trials were retried or replaced. All usage is known; receipts chain calibration 6 to this run and preserve the prior baseline, preflight, and five earlier calibrations. Static HTML was checked against all recorded transcripts; raw reports reproduce from journals. Production policy/registry remain unchanged.

## 2026-09-24 — Relax annual Outcome detail after human review

Ryan questioned the Gallows hybrid salary Outcome failures because the answers already contain too many numbers. Contract **3.0.5 / harness 2.0.12** now accepts the P50 daily/annual toll summary alongside P25/P50/P90 combined-cost scenarios without demanding separate P25/P90 toll amounts, unless the user explicitly requests them. Observed-only annual sources may be described as recent historical samples/scenarios; contradictory source claims still fail. The same requirement is applied to all 60 annual/mixed assertions. Prompts, actor profiles, tool workflows, fixtures, application model/prompt, and production policy are unchanged.

Three exact case-52 transcripts from baseline 2 are appended as proposed calibration references, with Outcome expectations **pass / pass / fail**. The third still fails Grounding for its false source characterization. All 132 existing references retain their labels, for 135 total. Offline checks verify transcript preservation and corpus consistency; calibration of this revised contract is pending. No new model calls or rescoring were performed. Original baseline and calibration results remain unchanged. See [the review decision](evidence/golden-100/ANNUAL-OUTCOME-REVIEW.md).

Ryan subsequently instructed: "Run the eval suite again after the adjustment has been made". This authorizes fresh calibration followed by a new 300-trial development baseline, using 16 workers and the existing $25 cumulative ceiling, chained from baseline 2's $3.09280985 cumulative spend. The revised corpus passed 111 relevant offline tests and repository static checks; the updated sample page still matches all 30 archived transcripts exactly.

### 2026-09-24 — Calibration 7 and the third development baseline completed

[Calibration 7](evidence/golden-100/CALIBRATION-7.md) measured all 135 references on contract **3.0.5 / harness 2.0.12**: **389/396 application labels and 135/135 actor-validity labels match**, with seven disagreements. All negative controls remain rejected overall; there were no measurement failures or unknown usage. Codex reviewed the seven disagreements under Ryan's execution authorization, retaining each authored and measured label. The review explicitly records the unnecessary route/schedule restatement failure on Gallows reference 2 and the disputed Rules label on its false-source reference 3. Cost: **$0.23103092**, cumulative **$3.32384076**. Run `6536dc88-d14d-4005-ad0c-547c0d132286`.

[Baseline 3](evidence/golden-100/BASELINE-3.md) then completed **300/300 trials: 206 passed, 93 failed, 1 inconclusive**; scored-trial success **68.9% (206/299)**, with **45/100 cases passing all three trials**. Gallows hybrid salary has two passes; its other trial fails for a wrong route argument. The remaining inconclusive is case 92 trial 2, where the actor judge marked a stop during facility clarification premature; no execution error occurred. Actor validity: 299 valid, one invalid, zero uncertain. Median/p95 full-trial latency: **21.23s / 34.44s**. Cost: **$0.91023745** across 1,970 known-usage model calls; cumulative **$4.23407822**. Run `fec06c4c-cc57-42b0-b0a6-81c7138fadfb`, archive `b3767839406c4bef925cda88f7d9b9ffbae17d05442d23fefe00844642d1f1d9`.

### 2026-09-24 — Requested unchanged repeat, calibration 8

While baseline 3 was running, Ryan instructed: "Go ahead and do another calibration round". The baseline was allowed to finish; [calibration 8](evidence/golden-100/CALIBRATION-8.md) then repeated the unchanged 135 references and judge contract with 16 workers. **392/396 application labels and 135/135 actor-validity labels match**; four disagreements remain, in cases 84/47/81 and the case-52 false-source Rules label. All negative controls still fail overall. Both acceptable Gallows references now pass all criteria; the false-source answer fails Outcome and Grounding as expected and also fails Rules, which remains a label disagreement. Five calibration-7 disagreements resolved, two new ones appeared, and two persisted. No measurement failures or unknown usage occurred.

Calibration 8 cost **$0.22134986** for 405 model calls, bringing the chained total to **$4.45542808 of $25**. Run `03f7976c-a7b5-4bd2-8789-3414763e782a`. All three new runs use source `36a320ee400bf75528ad3febced342ba7739c34c` and corpus SHA-256 `58b12c628f645c921c6872ea484d01d7ccaa8d9f9f30666dd4a52eedbcf50966`. This later calibration does not replace baseline 3's calibration-7 execution receipt. Original baselines and calibrations remain unchanged; no trial was retried, replaced, or rescored. The application model/prompt, actor configuration, cases' visible facts, and fixtures are unchanged. Changed grading and sampling prevent an application-improvement claim. Human review of the new results remains pending; production qualification is not authorized.

### 2026-09-24 — Resolve calibration-8 findings before calibration 9

Ryan instructed: "Just do the calibration, clean up any review pages, then push our changes." Contract **3.0.6 / harness 2.0.13** clarifies that Outcome checks every financial claim even after a correct table; Grounding uses all results available before each response and distinguishes catalog direction/entry roles from consent; and annual workflows must not offer a prohibited current-price restart. The false-source Gallows regression (case 52 trial 3) now expects Rules to fail for affirmative misrepresentation. This is the only reference-label correction; all 135 transcripts, 100 cases, actors, fixtures, and application behavior remain unchanged. Prior measurements and labels are preserved in their original archives.

Calibration 9 is authorized with 16 workers, chained from calibration 8 under the existing $25 ceiling. No new application baseline or production execution is part of this instruction. Fresh results and review-page verification will be appended after measurement.

### 2026-09-24 — Calibration 9 completed with full label agreement

[Calibration 9](evidence/golden-100/CALIBRATION-9.md) measured **135/135 references** with **396/396 application labels and 135/135 actor-validity labels matching**: zero disagreements, zero negative controls passing overall, zero measurement failures, and all usage known. All four calibration-8 findings now match their expectations, including the corrected false-source Rules label. Codex inspected the four new explanations; the result is agreement with authored references, not independently adjudicated accuracy. Historical disagreements and scores are retained.

Run `cc612d14-61bc-4e14-bf94-95bbc6b6609d` used **16 workers**, source `22d2eb76963e064e56735c3d665def5fd14f9664`, corpus **3.0.6 / harness 2.0.13**, and corpus SHA-256 `e51114c340da2addf7f24d5aca038a16c308d8af2edbdf1db38241e6564f7a4d`. Its **405 model calls** cost **$0.23440203**, bringing the full-precision chained total to **$4.68983010 of $25**. Evidence SHA-256: `d4142b355e20455176a6bc47d04d8218f72bf8cacc48c52253d80605bf043c45`. No reference was retried or replaced.

The [static review index](evidence/golden-100/index.html) now separates the current calibration from baseline 3's original 3.0.5 measurement and earlier results. All eight existing review pages have current navigation and historical context; the ten-case sample identifies baseline 2 and records the subsequent Gallows label correction. Raw archives remain unchanged. The new report reproduces exactly from its journal, receipt hashes match, and application/actor identity, cases, and fixtures are unchanged. Validation passed **111 relevant tests**, repository static checks, exact transcript/evidence checks, and browser checks across all ten offline pages for links, keyboard access, and mobile layout. No new application baseline was run; production policy and qualification remain unchanged.

### 2026-09-24 — Delete generated review packets at Ryan’s request

Ryan clarified that review-page cleanup means deletion. Removed all **15 generated evaluation HTML pages** across golden-100, golden-360, GPT-6 Luna, and the historical golden results, plus the GPT-6 Luna packet’s build and browser-check scripts. Documentation now links to retained raw reports. Raw transcripts, manifests, event journals, measured verdicts, receipts, approval records, and the corpus contract remain unchanged; no paid run or recalibration was performed.

This permanent journal is preserved verbatim above. Its earlier review-page links are historical and refer to deleted presentation artifacts; the final pre-deletion versions remain in Git commit `5d65f673d9cb19faff3bc1e010e286c2d5651daa`. Current evidence is linked from [the evidence summary](evidence/golden-100/README.md).

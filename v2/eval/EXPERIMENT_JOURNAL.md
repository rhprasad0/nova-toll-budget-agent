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

### 2026-09-24 — Publish summaries and remove redundant experiment archives

Ryan requested a separate cleanup PR after #596, with this journal as the record
of what was tried. Removed full golden-100, golden-200, GPT-6 Luna, and prompt
experiment run archives, duplicate per-round documents, and the generated case
review catalog. Current usage stays in the short evaluation guides. `AGENTS.md`
now requires summaries here and private storage for granular output; a temporary
review request does not authorize committing its page or data.

The journal above is preserved verbatim. Its earlier artifact links are historical;
all removed files are recoverable at commit
`19fb7faed8fee2c286bf71d6e2f92f27fe33e352` (merged #596), and local copies remain in
ignored `eval/private/archived-before-summary-cleanup/`. The original measurements
have not been rescored. The following older summaries are consolidated here from
the removed documents; these are not new runs or comparable application gains.

| Historical work | Result and limitation |
| --- | --- |
| Initial 24-case demo, corpus 1.0.5 | 27/72 trials passed; 3/24 cases passed all three. Actor and grader problems remained; no production baseline was approved. |
| Evaluation integrity, September 21 | Calibration matched 138/138 labels across 46 development examples; actor diagnostics passed 59/60. Outcome/Grounding/Rules separation and invalid-actor handling improved measurement; this was not independent accuracy. |
| Calibrated 24-case baseline, corpus 1.0.11 | 58/71 scored trials passed, one inconclusive out of 72; critical pass³ was 12/17. Below the release thresholds. |
| Caching/prompt work in #581 | Final actor check 60/60 and calibration 179/180. Final 72-trial run achieved 17/17 critical pass³ once; the requested three-run streak remained unfinished. |
| Initial 200-case calibration | Two runs each measured 274 development references, with known disagreements and a later reference correction. Those runs did not qualify the revised exact contract. |
| First GPT-6 Luna 200-case baseline | 409 passed, 184 failed, seven inconclusive out of 600; 68.97% of 593 scored trials. Application run cost $1.720441030. Signed-money checks, actor validity, and judge errors limited interpretation. |
| Prompt A/B/C comparison and golden-100 rounds | Aggregate results, original limitations, costs, and adoption decisions remain in the earlier journal entries above. |

Only executable corpus inputs, focused regression data, and legacy evidence read
by existing compatibility tests and the release initializer remain tracked. The
active 100-case corpus, 135 reference transcripts/labels, fixtures, evaluator
settings, protected policies, approval records needed by those contracts, and
initial/production registry identities are unchanged. Golden-100 regression tests
now use short signed-money examples and hashes of the existing Gallows references;
comparison recovery tests use six synthetic trial slots instead of a 600-trial
archive. No paid run, deployment, policy approval, or spending reset is involved.

Cleanup validation: **200 relevant evaluator, comparison, baseline, and gate tests
passed**, along with corpus validation and repository checks. All 94 current
documentation links resolve; the journal prefix and retained contract identities
are unchanged. The cleanup removes 207 files containing about 242 MB of redundant
experiment material from the working tree.

### 2026-09-24 — SOP-only eval-climb pilot stopped by user

Ryan authorized one round with a new $10 eval ceiling, targeting pass³ on the
100-case development corpus. Calibration 9 matched contract 3.0.6 / harness
2.0.13; Codex recorded an execution review without claiming human transcript
adjudication. All runs used four workers and unchanged application model/tools.

The baseline achieved **38/100 pass³, 208/300 successful trials, zero
inconclusives**, costing $0.930307325. Candidate A added a per-leg endpoint
resolution sequence: **36/100 pass³, 212/300 successful trials, zero
inconclusives**, costing $0.920493580. Its aggregate trial gain did not satisfy
the requested pass³ improvement. Candidate B added a pre-call endpoint audit;
Ryan stopped the pilot after 130 of its 300 attempts completed. B remains an
incomplete measurement. Independent candidate review and confirmation were not
completed. No candidate was adopted.

Recorded campaign cost is **$2.162977505**, including $0.312176600 of known B
usage. Four in-flight calls lacked final receipts at termination; recorded cost
is not a final billed total, and unknown usage blocks automatic continuation.
The supervisor and evaluator were terminated. Raw evidence and candidate
branches remain local; no holdout evaluation, deployment, push, or PR occurred.

Deferred hypothesis: clarify direction in current-price and annual-tool endpoint
descriptions after repeated eastbound IDs for westbound requests. Tool source
edits would invalidate the frozen corpus/calibration, so this was not tested.
The pilot also exposed that custom roles require a fresh session and that the
skill explicitly selected four workers; its default is being changed to 16
for future runs in response to Ryan's follow-up.

### 2026-09-24 — Pass³-first $20 campaign blocked during review

Ryan authorized a new $20 hard eval ceiling, excluding Codex usage and the
stopped pilot. Promotion required strictly greater pass³ over all 100 development
cases (all three slots successful; inconclusives never count), even if total
successful slots decreased. Inconclusive, Grounding, Rules and independent
material-regression safeguards remained required. The comparison helper validated
evidence; its success-count and paired-delta gates were diagnostics only.

Starting commit: `a5338c913f3c99b2eb895619bc287ba4d24e3aa0`. Corpus 3.0.6,
harness 2.0.13, application/actor/judges `gpt-6-luna`, tools, schemas, evaluator
and version constants stayed frozen. All three named Codex roles were verified
before paid work. A fresh authorized Codex offline review verified Calibration
9's exact digest, 135 complete references, 405 known-usage calls and all 14 runner
identity keys. Agreement covered 396 application labels and 135 actor labels;
negative controls and actual explanations were inspected. This was not Ryan's
personal transcript adjudication. Three invalid-actor references and no
uncertain-actor references limit the calibration.

All five new runs used 16 workers and completed 300 slots, chained consecutively
from a fresh baseline. Each enforced a $17 cumulative search ceiling, reserving
$3 for two final runs with at least 25% headroom over measured full-run costs.

| Run / local commit | Pass³ / 100 | Successful / 300 | Inconclusive | Eval cost | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Original baseline | 47 | 212 | 1 | $0.955475225 | Incumbent retained |
| Round 1A `ee6e1be` | 54 | 222 | 0 | $0.932931080 | Rejected |
| Round 1B `c9b1f4a` | 58 | 235 | 0 | $0.921556700 | Rejected |
| Round 2A `e5129a4` | 52 | 225 | 0 | $0.939550450 | Rejected after review |
| Round 2B `4080040` | 50 | 220 | 1 | $0.934852150 | Numeric gates pass; review blocked |

Round 1 tested two placements for the annual forecast/guaranteed-budget
qualification. Over 299 common scored slots, A increased Grounding violations
9 to 10 and Rules 55 to 70; B reduced Grounding to 6 but increased Rules to 58.
Independent reviewers also found unresolved material route and source-disclosure
regressions. Neither candidate was promoted.

Round 2 tested joint endpoint-direction resolution and a separate pre-call
direction check, both from the original incumbent. A passed numeric safeguards
(Grounding 9 to 4, Rules 55 to 43 over 299 common slots), but independent review
rejected repeated southbound selection, alternative-discovery and duplicate
endpoint regressions. B passed numeric safeguards (Grounding 9 to 3, Rules 55
to 55 over 298 common slots); its independent review remains incomplete.
Sampling limits causal attribution. Reviewers separately recorded suspected
judge contradictions and inconsistent disclosure judgments without relabeling,
retrying or excluding trials.

Stop reason: the required fresh named reviewer could not start because
`agent thread limit reached` persisted after the preceding review finished and
a supported interruption attempt. Activation of the unused readiness-only
reviewer also failed; no close-thread operation was exposed. The parent did not
substitute a reviewer or promote the unreviewed candidate. Round 2 remains
incomplete; this is not a two-unsuccessful-round stop. No confirmation pair ran
because no independently eligible improved incumbent was established.
**No confirmed patch is recommended.** The original SOP remains in the campaign
checkout; candidate commits are preserved in separate local worktrees.

Total recorded new eval spend: **$4.684365605**. All model calls have complete
usage and all evidence/accounting chains reconcile. Prior calibration spending
and the stopped pilot were excluded; the pilot's unknown usage remains historical
and unresolved. Semantic prompt, development-corpus and comparison checks passed.
Candidate SOP edits necessarily fail the old versioned prompt-hash assertion
while manifests and versions are frozen; that limitation was not patched around.

Deferred unmeasured idea: clarify direction relationships in current-price and
annual endpoint descriptions. Repeated eastbound/westbound argument reversals
support investigation, but tool-file edits invalidate the frozen
corpus/calibration and were not tested. Raw evidence, reviews, hashes, progress
and blocker details stay ignored. Findings apply only to the exposed development
set. No push, PR, holdout evaluation, production database access, release or
deployment occurred.

## 2026-09-25 UTC — Pass³-first campaign continuation and final decision

This continues the same authorized $20 campaign and corrects the preceding
provisional review-blocked status. A new supervisor session resolved the agent
thread-capacity limit and obtained a fresh independent `eval_reviewer`
(`gpt-6-astra`, high) review of Round 2B `4080040`. The original application
incumbent remains `a5338c9`; journal-only commit `1c326ed` did not change it.
No campaign, round, budget, calibration approval or paid trial was restarted.

All five original run journals, report/evidence hashes, complete usage and the
baseline → R1A → R1B → R2A → R2B spending chain reconciled. The original results
above are unchanged: 1,500 completed attempts across five full development runs,
100 cases × three trials each, with 16 workers. Calibration 9, harness 2.0.13,
corpus 3.0.6, application/actor/judge model `gpt-6-luna`, and the remaining
measurement contract stayed fixed. Pass³ uses the fixed 100-case denominator;
successful-slot growth and paired delta remain diagnostics, with the retained
inconclusive, comparable Grounding/Rules and independent regression safeguards.

**Round 2B is rejected.** Its 50/100 Pass³, 220/300 successful slots and one
inconclusive pass the numeric gates against baseline 47/100, 212/300 and one
inconclusive. Over 298 common scored slots, Grounding violations fall from 9 to 3
and Rules remain 55. Scope passes: only eight SOP lines were added. The reviewer
inspected all 46 distinct adverse slots (43 lost successes, three new Grounding
and 27 new Rules flags, with overlap), plus all 12 attempts across the two
excluded cases, using original trajectories and source evidence.

The disqualifying finding is repeated mixed-direction routing: two previously
three-of-three successful routes become one-of-three, pairing northbound entries
with southbound exits. Catalog direction fields and coordinates corroborate the
inconsistency; rejected calls leave the requests unanswered. Other findings
include incorrect source disclosures. Small unseeded samples do not prove that
the patch caused each changed trial, but the repeated material deterioration
remains unresolved. Duplicate endpoint identifiers, actor-dependent branches and
inconsistent judge labels were recorded separately without relabeling, excluding
or retrying attempts. Actor-invalid inconclusives remain explicit.

Round 2 is now complete and is the **second consecutive round without an
independently eligible improvement**. The campaign stops under that rule; there
is no Round 3 or confirmation pair because no improved incumbent was eligible.
**No confirmed patch is recommended; retain the original SOP.** Candidate commits
and private evidence remain preserved. Total campaign eval spend is unchanged at
**$4.684365605**, with **$0 additional eval spend** in this continuation. Codex
usage, prior calibration costs and the separate stopped pilot remain excluded;
the historical unknown pilot usage was not resumed.

The existing unmeasured tool-description direction-clarity idea remains deferred
because tool-file changes invalidate the frozen corpus/calibration; no tool
changes were tested. Semantic/corpus checks from the measured candidates remain
valid, and the expected original-version prompt-hash assertion mismatch remains
documented without changing tests, manifests or versions. Continuation checks
reproduced all four original comparison outputs and verified the complete
accounting chain. All prior journal bytes are preserved. Raw reviews, coverage
inventories and continuation state remain ignored. These are exposed-development
findings, with no generalization or production qualification claim. No push, PR,
merge, deployment or production access occurred.


## 2026-09-25 UTC — Explicit one-round continuation: Round 3

Ryan explicitly requested “Do another round, keep the cap, open a PR.” This
superseded the preceding two-consecutive-no-improvement stop for exactly one
additional round. It did not reset the cumulative $20 eval budget, change the
scoring or safety contract, authorize a fourth round, or authorize paid
recalibration. The outer session owns any push and ready-for-review PR; this
supervisor performed local work only. Journal-only HEAD `e2b99b7` was not an
application incumbent: both new alternatives started from original `a5338c9`.
All 56,432 preceding journal bytes and both prior summary commits are preserved.

Before reactivation, the five existing run journals, hashes, 1,500 completed
attempts, known usage and $4.684365605 spending chain were reconciled. The
existing fresh campaign Calibration 9 review remained valid and pinned. No new
baseline, calibration, old pilot approval or pilot spending was substituted.
The frozen contract remains development corpus 3.0.6, harness 2.0.13, and
application/actor/judge model `gpt-6-luna`. Fresh named analyst, implementer and
independent reviewer roles used their prescribed models and effort levels,
with one child scheduled at a time and no child delegation.

Round 3 addressed a distinct source-disclosure mechanism. Several original
annual answers denied historical observations even when the successful tool
result supplied historical paired-day samples and neither modeled nor current
fixed-rate prices. Passing examples correctly described the same source.
Alternative A appended a narrow successful-result condition to the Section 6
provenance bullet; B replaced that bullet with per-facility classification and
mixed-source wording. No prior rejected patch was combined with either change.
Only the SOP changed: tools, descriptions, schemas, runtime, versions, models,
evaluator, corpus, fixtures, tests and domain requirements remained frozen.

| Application / local commit | Pass³ / 100 | Successful slots / 300 | Inconclusive | Eval cost | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Original `a5338c9` (existing baseline) | 47 | 212 | 1 | $0.955475225 already accounted | Retain |
| R3A `5c8acda` | 52 | 228 | 1 | $0.934252335 | Reject independently |
| R3B `0c4a4df` | 55 | 234 | 1 | $0.936725840 | Reject independently |

Each new run used all 100 development cases, three trials and 16 workers.
R3A chained directly after R2B; R3B chained after R3A. The cumulative search
ceiling stayed $17, reserving $3, which exceeded two latest full-run costs with
25% headroom before each run. Pass³ used the fixed 100-case denominator with
all three slots successful; inconclusives never succeeded. Total-success and
paired-delta criteria remained diagnostic only. Both candidates passed strict
Pass³ improvement, inconclusive nonincrease, and comparable Grounding/Rules
nonworsening. All original results remain unchanged.

Independent review disqualified both candidates despite those numeric gains.
A's reviewer inspected 39 distinct adverse slots, including 35 lost successes,
three new Grounding and 24 new Rules flags with overlap, plus both excluded
cases. Two previously three-of-three current routes became one-of-three through
repeated wrong-direction calls. Two related annual trips also substituted a
different toll facility. B's reviewer inspected 42 distinct adverse slots,
including 32 lost successes, five new Grounding and 31 new Rules flags with
overlap, plus both excluded cases. A modeled-current scenario fell from
three-of-three to zero-of-three: two wrong-endpoint calls failed, and the one
completed answer omitted the returned proxy observation time.

These concentrated material regressions remained unresolved. The reviewers
explicitly distinguished repeated losses from isolated stochastic flips,
existing failures redistributed across trials, and grading ambiguities. They
did not claim that these small samples prove patch causation or require every
individual trial to remain successful. Date-anchor, cancellation, annual-day
wording and deterministic-money inconsistencies were retained as separate
diagnostic findings; no scores or actor-validity labels were rewritten and no
trials were retried or replaced. Each new run's single inconclusive was
actor-invalid, with all 300 attempts complete and all usage known.

**Retain the original SOP; no confirmed patch is recommended.** The authorized
additional Round 3 is complete and no fourth round is authorized. Neither
candidate was independently eligible, so no confirmation pair was run. New
Round 3 eval spend was **$1.870978175**, for a cumulative **$6.555343780** under
the same $20 cap. All 2,100 attempts across seven runs match the raw finished
records and the full spending chain reconciles. Codex usage, prior calibration
costs and the separate stopped pilot remain excluded.

Existing corpus validation, 16 comparison/development checks and seven semantic
prompt checks passed for each candidate. Parent scope and frozen-identity checks
and independent tool-schema checks passed. The expected original-version
prompt-hash assertion failed for both changed SOPs and remains explicit; no
test, manifest or version was changed to bypass it. The original application's
eight prompt checks passed during continuation preflight.

A new unmeasured tool-description idea concerns duplicate endpoint rows with
identical visible metadata but different accepted identifiers. The current-price
and annual endpoint descriptions could clarify opaque-ID copying and the
canonical-ID contract; identical metadata may require more than wording alone.
This joins the existing direction-description idea. Both remain deferred
because tool-file changes invalidate the frozen corpus/calibration. No tool
change or recalibration was tested. All detailed evidence, rejected candidate
worktrees, reviews, hashes and progress remain private and preserved. These
exposed-development findings do not establish generalization or release
qualification. No push, PR, merge, deployment or production access occurred in
this supervisor session.

## 2026-09-25 — Description-only continuation on PR600 blocked at contract review

Ryan authorized a new local description-only climb stacked on unmerged PR600,
including fresh contract review and calibration under the existing cumulative
$20 eval ceiling. The objective remained strict improvement in pass^3 over a
fixed 100 development cases, with all three slots successful and inconclusives
never successful. Prior scores could inform diagnosis only; a fresh baseline
was required for contract 3.1.0 / harness 2.1.0 / `literal-input-prose-v1`.
The exact starting commit was `97688142558f313887bd8e92b7b5ae516dc0a985`.

The fresh named `eval_reviewer` (gpt-6-astra/high, isolated handoff, no child
delegation) rejected prerequisite contract approval. `_PricingProfile` is an
allowlisted input model but is also embedded in `_CurrentPriceResponse`.
Changing one of its existing literal field descriptions leaves the normalized
tool-source hash unchanged while changing the generated output description.
The reviewer reproduced this in memory. The comparison helper permits different
full schema hashes under this policy and cannot detect that output change.
Existing synthetic normalization checks use a separate output class and miss
this shared-model case. Full generated-schema review could reject an affected
candidate, but the reviewer found the exact contract insufficient to justify
approval of its stated output-preservation boundary. No approval was fabricated
or transferred, and Ryan was not represented as having inspected trajectories.

| Phase | Completed attempts / references | Pass^3 | Eval cost |
| --- | ---: | ---: | ---: |
| Carried prior campaign, seven full runs | 2,100 attempts | Not comparable across contracts | $6.555343780 |
| Fresh offline contract review | No paid calls | Not measured | $0.000000000 |
| New calibration, baseline, search, confirmation | Not started | Not measured | $0.000000000 |
| Cumulative authorized accounting | 2,100 prior attempts | No new result | **$6.555343780 / $20** |

The supervisor reconciled all seven prior raw journals, their immediate-prior
run links, complete 300-slot coverage per run, and known model usage against the
prior ledger. Decimal recomputation from token usage confirmed the carried cost;
remaining authorization is $13.444656220. Historical calibration/pilot and Codex
agent usage remain excluded under the original authorization. The separate
stopped pilot was neither inspected nor resumed. No historical paid trial was
repeated. The first future paid call in this chain must still use prior `r3b`.

Offline validation passed for all 100 development cases, 82 relevant
development/retirement/runner tests, eight comparison-helper checks, and the
private fixed-denominator pass^3 self-check. The reviewer independently verified
114 corpus/application files byte-identical across PR600 and its parent and ran
focused checks. Passing tests did not override the demonstrated contract defect.
Raw review evidence and accounting remain in the ignored campaign directory.

Decision and stop reason: stop before calibration for the independently rejected
measurement contract. Retain the original application and pending corpus review;
no lifecycle assertion, source manifest, judge, cases, fixtures, labels, model,
SOP, tool wording, or runtime changes were made. No candidate was implemented,
measured, promoted, or confirmed. The required correction is to exclude shared
output-model descriptions from the editable contract or otherwise enforce exact
output-schema preservation, with a focused shared-model regression and fresh
review before freezing. Such a harness/manifest repair is outside the permitted
continuation edits and was deferred to the outer session. After a valid contract
review, fresh calibration and baseline are still required under the same cap.
There is no performance or generalization claim, production qualification,
push, PR creation, merge, or deployment from this local run.

## 2026-09-25 — Contract blocker resolved; calibration stopped at development credentials

Ryan explicitly resumed the same description-only continuation stacked on PR600
after the outer session committed the prerequisite correction in `657ef7b`.
The previous blocker entry remains unchanged. Contract 3.1.1 / harness 2.1.1 /
`literal-input-prose-v1` now excludes shared `_PricingProfile` descriptions from
the editable allowlist and checks actual output-model definitions. The new
corpus digest is
`f64dcd1bc2fb6b68a434df1f7424df64618655591338996b235a77a177fa661a`.
This explicit prerequisite change preceded every new measurement; it was not an
application candidate or a change to a measured campaign. The same cumulative
$20 cap, pass^3-first objective, and outer-session publication ownership apply.

A fresh named `eval_reviewer` (gpt-6-astra/high, isolated handoff, no delegation)
accepted the corrected contract. Its independent in-memory probes verified all
13 admitted literal edits preserve complete output schemas and normalized source
identity while changing their full schema hashes. Each of the three shared
profile descriptions now changes normalized identity if edited. The reviewer
verified 121 supporting files byte-identical against earlier commits, including
the application, corpus, fixtures, and dependencies; tool specifications were
also identical. The original deterministic contract blocker is resolved.

Commit `292fe09` records fresh corpus approval as Codex review under Ryan
authorization and updates only the approval lifecycle assertion. The record
explicitly denies personal human trajectory adjudication and does not approve
calibration or production. Missing/pending paid-entrypoint guards remain intact.
The new manifest was unchanged by this approval step. The campaign identity was
recorded from clean commit `292fe0943810cbfbf4f3a7f08fe87626d4999173`.

The supervisor then invoked one fresh calibration with 16 workers, no retries,
the existing `nova-toll-dev` AWS/SSM path, a cumulative $17 execution ceiling,
and a $3 confirmation reserve. Its immediate predecessor was the old campaign
`r3b`, carrying exactly $6.555343780. All 135 reference rows failed in the judge
construction phase with `TokenRetrievalError`, before any model call started.
A separate credential-resolution diagnostic confirmed the same development
token retrieval failure without displaying credentials. No actor assessment or
application verdict was measured. The empty disagreement list therefore does
not represent calibration agreement, and no calibration approval was written.

| Phase | Coverage / result | Pass^3 | Eval cost |
| --- | --- | ---: | ---: |
| Carried seven prior full runs | 2,100 completed attempts; all usage known | Not comparable | $6.555343780 |
| Corrected contract review | Accepted offline | Not measured | $0.000000000 |
| Fresh calibration | 135/135 measurement failures; zero model calls | Not applicable | $0.000000000 |
| Baseline, candidates, confirmation | Not started | Not measured | $0.000000000 |
| Cumulative accounting | No new model usage | No new result | **$6.555343780 / $20** |

All seven prior journals were reconciled again against raw token usage and their
spending chain. Calibration has zero model-started and model-finished events,
so its zero cost is known, not estimated or missing usage. Remaining budget is
$13.444656220. Historical calibration/pilot and Codex agent usage remain excluded
exactly as authorized; the separate stopped pilot was not accessed. The failed
calibration is now the latest accounted run and must be the predecessor of any
subsequently authorized run. Its evidence digest is
`3ad5980dc4f929c4d76f867a74684f7364ce832c788c24e20c6bfb6ac99716f3`.

Validation passed: all 100 development cases, 82 focused tests, eight comparison
checks, and then all seven lifecycle/entrypoint tests plus Ruff after the narrow
approval update. Independent review also ran the 82 tests and eight comparison
checks. These checks validate the contract, not application performance.

Decision: stop for the new infrastructure/measurement failure, preserving the
failed calibration and all original verdict/reference inputs. No replacement
calibration, retry, baseline, candidate, promotion, or confirmation was run.
The original application remains unchanged. Restore development authentication
and explicitly direct subsequent calibration execution before continuation;
do not reuse prior approval or overwrite this failed attempt. Detailed review,
schemas, identity, accounting, and raw calibration evidence remain ignored and
private. This session performed no push, PR, merge, deployment, production access,
or release qualification.


## 2026-09-25 — Authenticated description-climb continuation: calibration blocked

Ryan's explicit “Authed” response resolved the development credential blocker
and directed one new calibration attempt under the same cumulative **$20 eval
cap**. This was a user-directed resumption, not an automatic retry. The existing
development AWS/SSM retrieval succeeded without printing or saving credentials.
The preceding zero-cost failed calibration remains immutable and is the direct
prior run of this attempt. Both preceding blocker/resolution entries remain
unchanged. Outer session owns publication through ready PR602 stacked on PR600;
this continuation performs local work and commits only.

Measured starting commit: `abfb039bfa00e9161bb7fa48d12fe037332572f6`.
The corrected contract remains `3.1.1`, harness `2.1.1`, and
`literal-input-prose-v1`, from prerequisite
`657ef7b48cfa5cf299e2a733585900d68b6708f8`; authorization-bound corpus review and
lifecycle checks remain at `292fe0943810cbfbf4f3a7f08fe87626d4999173`.
Corpus digest: `f64dcd1bc2fb6b68a434df1f7424df64618655591338996b235a77a177fa661a`.
Application SOP version `2.3.8`, renderer `1.0.0`, all tool wording and schemas,
cases, fixtures, labels, judges, and models remain unchanged. Application, actor,
and judges use `gpt-6-luna`, with reasoning efforts low/medium/medium and the
existing 2,048-token ceiling. The shared `_PricingProfile` and all output
descriptions remain frozen. No prior-contract score or approval was transferred.

The fresh calibration used 16 workers and cumulative ceiling **$17**, retaining
at least **$3** for a possible final confirmation. All 135 references completed;
405 model calls started and finished with known usage, zero missing references,
and zero measurement errors. Actor validity matched 135/135 labels: 132 valid
and three invalid. The invalid references have no application labels.

| Calibration criterion | Agreement | Disagreement |
| --- | ---: | ---: |
| Outcome, actor-valid references | 132/132 | 0 |
| Grounding, actor-valid references | 130/132 | 2 |
| Rules, actor-valid references | 132/132 | 0 |
| Actor validity, all references | 135/135 | 0 |

Fresh independent `eval_reviewer` (`gpt-6-astra`, high) reproduced the evidence
identity, raw-event/report agreement, complete generated schema hashes, and usage
accounting, then returned **STOP**. The parent accepts that recommendation.
A reference uses a derived annual day count in a tool call before user acceptance.
Its label expects Grounding to pass, while the judge fails the unsupported
schedule argument under the fixed rubric. The deterministic workflow checks do
not override Grounding in that reference, so the disagreement changes the
required Grounding violation metric. Its unchanged overall failure does not
resolve this material calibration ambiguity.

The second disagreement concerns affirmative salary selection interpreted as a
conditional midpoint proposal. The semantic judge passes Grounding against a
failing label, but the existing `unsupported_money` check still makes effective
Grounding fail. This is a bounded judge-boundary concern; it does not neutralize
the first disagreement. Neither verdict nor label was altered. No calibration
approval was written, and no human transcript inspection is claimed: this was
Codex offline review under Ryan's direction.

| New-contract application phase | Completed slots | Pass^3 / 100 | Successful slots / 300 | Inconclusive slots |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 0 | Not measured | Not measured | Not measured |
| Candidate rounds | 0 | Not measured | Not measured | Not measured |
| Confirmation pair | 0 | Not measured | Not measured | Not measured |

**Decision: retain the original application; no confirmed improvement.** Search
stopped before its first baseline/round because calibration has an unresolved
material disagreement. There was no application regression comparison and no
unnecessary confirmation. The requested pass^3-first objective and fixed 100-case,
three-slot denominator were preserved but could not be measured. Endpoint-direction
and opaque-ID description ideas remain untested hypotheses, not admitted patches.

| Eval spending | USD |
| --- | ---: |
| Carried seven full runs / 2,100 attempts | 6.555343780 |
| Preserved credential-failed calibration | 0.000000000 |
| New authenticated calibration | 0.233439065 |
| Cumulative charged eval usage | **6.788782845** |
| Remaining original authorization | **13.211217155** |

All amounts were reconciled from raw token usage and pinned prices; usage is
known. Historical calibration/pilot and Codex usage remain excluded as originally
authorized. The separate stopped pilot was not accessed or resumed. The latest
accounted run is the authenticated calibration and must precede any later
separately directed paid run in the spending chain.

Its evidence digest is
`389c373ec36e4f41fc4ff1aa3fe9380e383b2986b908184a8d2288d33cd6e7c0`;
the preserved credential-failed calibration digest is
`3ad5980dc4f929c4d76f867a74684f7364ce832c788c24e20c6bfb6ac99716f3`.
Raw runs, accounting, and the independent review remain in ignored private
storage. Any correction to the annual-days label/rubric boundary or salary judge
boundary needs separately authorized measurement-contract work and matching
calibration; those changes are outside this frozen application search. No retry,
judge/label edit, application patch, remote write, merge, deployment, or production
qualification occurred. These exposed development references establish neither
application improvement nor generalization.


## 2026-09-25 — Authorized annual-day grounding correction and first description-climb round

**Decision: retain the original application; resume at admitted round 2 in a fresh
supervisor session.** The scoring prerequisite is resolved and fresh calibration
is approved. Both round-1 candidates were independently rejected. The host then
refused both required editor followups and a fresh named editor spawn with
`agent thread limit reached`. No round-2 implementation or paid evaluation began.
This is a session-capacity blocker, not completion of the three-round search or
the two-consecutive-no-improvement stopping condition; the current streak is one.

### Authorization, versions, and evidence boundary

Ryan explicitly selected **both Grounding and Rules** for using a derived annual
day count as a tool argument before acceptance. Before any new-contract baseline
or candidate evaluation, prerequisite commit
`04451e0eb4fa36d068f4e5017cfbba0c98f60c6c` changed only the existing premature
annual-day reference's expected Grounding from true to false, leaving Outcome and
Rules false. The rubric/domain clarification preserves conditional 52-times-
weekday proposals as grounded arithmetic, while actual unaccepted tool arguments
fail both criteria even with a same-turn proposal or later acceptance. All
transcripts, cases, fixtures, other labels, deterministic checks, application/SOP
and tool wording remained unchanged at this boundary. Original labels and review
remain in Git at `abd3ad390bcc71839cbdbe5bf2bbbb379e1c1314`.

The new frozen contract is **corpus 3.1.2 / harness 2.1.2 /
`literal-input-prose-v1`**, corpus digest
`1fdd433f4871ba2b317facee126075a712c476e40ccd98a60508103faa6a9386`.
Independent `eval_reviewer` (`gpt-6-astra`, high) assessed the targeted correction
as acceptable with no substantive defect. Corpus approval was freshly bound in
`f218fe47563a4dbc27a597b7730b6b977f71b99c`, the original application and baseline
commit. This was authorized Codex review of the specific rule and evidence, not
a claim that Ryan personally inspected all trajectories. The existing
`human_trajectory_adjudication=false` lifecycle remains intact. The previously
accepted shared `_PricingProfile` output-schema guard was preserved.

### Fresh calibration and measurement

One fresh matching calibration completed **135/135 references, 405/405 known
model calls, and zero measurement errors**. Outcome and Rules each matched
132/132 applicable labels; actor validity matched 135/135. Raw Grounding matched
131/132. The corrected annual-day reference now matches, and the conditional
proposal control still passes. The sole raw disagreement is the unchanged salary
selection reference: `unsupported_money` independently forces effective Grounding
to fail. Independent assessment verified effective Grounding and Rules each match
132/132, with no material baseline blocker. The supervisor then bound fresh
calibration approval to evidence digest
`3ca8d9bbc3be08c67ebb27bfeed591da5beab4275a364466d4633f190da5fae9`.
The raw disagreement and pre-approval report snapshot remain private; no reference
was retried, relabeled, or dropped to obtain agreement.

The prior zero-call credential-failed calibration and the prior authenticated
calibration with two raw Grounding disagreements remain preserved and accounted.
Their earlier blocked decisions stand as historical measurements; this explicit
user adjudication resolved the annual-day ambiguity before the new search.

### Full development measurements and independent decisions

All application runs used the frozen 100-case development set, three trials per
case, and 16 workers. Every run completed all 300 slots with known usage, no
infrastructure errors, and no inconclusives. No holdout was accessed. Application,
actor, and judge models remained `gpt-6-luna` with their pinned settings. The
user's pass³-first override requires all three slots to succeed on each of the
fixed 100 cases, while retaining violation, inconclusive, evidence-validity, and
independent material-regression gates. Success-count and paired-delta improvements
remain diagnostic rather than additional promotion requirements.

| Application | Pass³ / 100 | Success / 300 | Inconclusive | Grounding / 300 | Rules / 300 | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Original `f218fe4` | 44 | 204 | 0 | 11 | 57 | Retained |
| R1A SOP `87751cc` | 56 | 238 | 0 | 5 | 56 | Reject: unresolved material regressions |
| R1B annual summary `d9f9504` | 65 | 253 | 0 | 12 | 35 | Reject: Grounding worsens; provenance concerns |

The required `eval_cluster` (`gpt-6-luna`, high) diagnosed repeated omission of the
annual forecast/guaranteed-budget caveat from fresh baseline trajectories and
passing siblings. Separate `eval_implementer` agents (`gpt-6-sol`, xhigh) produced
alternative SOP and annual-tool-summary text patches from the same incumbent.
The parent checked full diffs, normalized source identity, and complete generated
schemas before spending. B's initial offline wording was corrected by its editor
to preserve all original unconditional disclosure duties before its sole paid run.
The parent did not implement candidate patches.

Fresh independent reviewers assessed each candidate without implementer
conclusions. A's reviewer inspected all 39 distinct affected slots: numeric gates
passed, but repeated route-direction failures and modeled-route clarification
failures remained material and unresolved. B's reviewer inspected all 30 affected
slots: Grounding increased from 11 to 12, and repeated denial of actual historical
source evidence was a substantive concern. All lost successes and new violations
were considered; neither comparison excluded cases. Individual stochastic flips
do not establish patch causality, and neither review claimed they do.

Round 2 was admitted from the retained original: two separate Greenway direction
alternatives, one in the existing SOP paragraph and one in the current-price tool
summary. The hypothesis uses baseline failures and passing controls for travel
toward/away from Route 28, without imposing a global same-direction rule on other
facilities. Both clean worktrees start at `f218fe4`. Required editor handoffs were
blocked by host capacity before any edit. No role/model substitution occurred.
No eligible incumbent exists, so no confirmation pair was warranted or run.

### Accounting, checks, and limitations

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

This resumption incurred **$3.088099150** above its carried **$6.788782845**.
The remaining hard-$20 authorization is **$10.123118005**. Historical excluded
calibration/pilot and Codex usage remain excluded; the separate stopped pilot was
not accessed. Every paid run chains directly through the previous accounted run,
including rejects. The next paid run must use the private `grounding-r1b` directory
as `--prior-run`. The $3 confirmation reserve remains intact under the $17 search
ceiling; recheck the complete-next-run fit using the latest full cost before
continuing. A shell invocation from the repository root failed to import the
runner before creating any run or making calls; its log is preserved, and the sole
actual baseline launched from `v2/`.

Validation: 83 relevant prerequisite/lifecycle/runner tests passed, eight
comparison-helper checks and the private pass³ self-check passed, and the complete
corpus validated offline. Each initial candidate check had 67 passes and one
expected versioned wording-digest mismatch; snapshots and version contracts were
not rewritten. B's final offline wording correction revalidated corpus/source and
full contract identity. Both comparison reports were independently reproduced.

Deferred findings include catalog IDs with identical metadata rejected by strict
fixtures, signed-delta and rounded-money wording sensitivity, inconsistent
cancellation/provenance/financial-label judging, and separate I-495 direction
guidance. These need separate measurement-contract work or a distinct admitted
mechanism; they do not authorize rescoring or retries here. These exposed-set
measurements establish neither generalization nor production qualification.
Raw evidence, plans, reviews, accounting, and the exact continuation handoff stay
in ignored `v2/eval/private/eval-climb/descriptions-20/`. Only this sanitized
summary and current usage status are published locally. No push, PR update,
merge, or deployment was performed; the outer session owns ready PR602 on PR600.


## 2026-09-25 — Round 2 capacity continuation: no eligible improvement

**Decision: retain the original application and stop the search after two
consecutive rounds without an eligible improvement.** A fresh supervisor resolved
the required agent-thread capacity blocker and executed the already admitted
Round 2. This continued the same authorization, cumulative $20 cap, baseline,
calibration, and pass³-first contract. No completed prerequisite, calibration,
baseline, or Round 1 measurement was repeated. No candidate was promoted, so
neither Round 3 nor an unnecessary confirmation pair ran.

The original application remains
`f218fe47563a4dbc27a597b7730b6b977f71b99c`. Journal-only campaign commits did not
become new application incumbents. Corpus **3.1.2**, harness **2.1.2**, and
`literal-input-prose-v1` remained frozen, with the existing approved calibration
and corpus evidence. Application, actor, and judge models remained `gpt-6-luna`
with unchanged settings. All previous journal bytes and rejected worktrees are
preserved; the prior capacity entry remains a historical checkpoint.

### Admitted alternatives and complete measurements

Separate required `eval_implementer` agents (`gpt-6-sol`, xhigh) implemented the
existing Greenway direction plan from the same original incumbent. A added four
lines to the existing SOP paragraph, checking Greenway endpoints before a tool
call. B added one sentence to the existing current-price tool summary, exposing
EB toward Route 28 and WB away while resolving endpoint roles separately. Both
preserved discovery and origin-correction guidance, other facilities' directions,
SOP exceptions, and consent/security/money requirements. Neither included a
rejected Round 1 annual-caveat patch. The supervisor did not implement either
candidate.

| Application | Pass³ / 100 | Successful slots / 300 | Inconclusive | Decision |
| --- | ---: | ---: | ---: | --- |
| Original `f218fe4` | 44 | 204 | 0 | Retained |
| R2A SOP `9808e672e502504995a5f9f9fb917b2ba1db9853` | 57 | 231 | 0 | Reject: unresolved material direction regressions |
| R2B current-price summary `b715c2cfc8489df1373eda3040408c7303174b74` | 52 | 222 | 1 | Reject: inconclusive increase and material direction regressions |

A and then B each completed all **100 development cases × 3 trials**, using
16 workers. Pass³ retains the fixed 100-case denominator and requires all three
slots to succeed. A's comparable Grounding violations fell from 11 to 4 and Rules
from 57 to 46, each over 300 slots. B's corresponding counts were 10 to 9 and 57
to 52 over **299 commonly scored slots**; its actor-invalid slot is excluded from
those comparable violation rates, remains an explicit inconclusive, and does not
count as a success. One case was excluded from paired three-trial diagnostics,
but all its trials remained in independent review. Successful-trial increase and
paired delta remained diagnostics, not extra promotion gates.

Fresh independent `eval_reviewer` agents (`gpt-6-astra`, high) inspected each
candidate's complete diff, frozen identities, regenerated schemas, raw reports,
and numeric packets without implementer conclusions. A's reviewer covered all
45 unique affected slots: 38 lost successes, 4 new Grounding violations, and 29
new Rules violations, with overlap. Numeric gates passed, but repeated actual
wrong-direction failures on Greenway, Dulles Toll Road, and I-495 trips remained
material. These included a westbound Greenway trip regressing from 2/3 successes
to 0/3 with mixed endpoint directions, and an I-495 trip from 3/3 to 0/3.

B's reviewer covered all 50 affected slots and all three trials of the
case excluded from paired diagnostics. B fails the retained inconclusive gate
because one actor stopped prematurely. Repeated wrong-direction failures on a
westbound Greenway trip and an I-495 trip each regressed from 3/3 to 0/3. Neither
review inferred causality from a single unseeded flip. No score, actor-invalid
slot, raw report, fixture, or label was relabeled, retried, or replaced.

### Accounting, validation, and deferred findings

| Accounted work | Cost USD |
| --- | ---: |
| Cumulative before this capacity continuation | 9.876881995 |
| R2A | 0.946600000 |
| R2B | 0.956438880 |
| **This continuation** | **1.903038880** |
| **Cumulative** | **11.779920875** |
| **Unused authorization** | **8.220079125** |

The cumulative total includes $6.555343780 carried from the seven older runs and
$5.224577095 incurred by this description-contract continuation across its
sessions. All 15 accounted run journals reconcile through the original chain.
R2A chained directly from R1B; R2B chained directly from R2A. All **1,997 A calls
and 2,005 B calls** have known usage, with no infrastructure errors or missing
slots. The search ceiling stayed at $17, with a $3 confirmation reserve; each
complete run fit with the required cost headroom. The stop is the no-improvement
rule, not budget exhaustion. Historical excluded calibration/pilot and Codex
usage remain excluded; the separate stopped pilot was not accessed.

Both candidate corpora validated offline. Each candidate's focused existing
checks produced 67 passes and one expected versioned wording-digest mismatch;
tests, snapshots, manifests, and versions were not changed to accept the wording.
The supervisor and reviewers verified unchanged normalized source and full
schema structure/output descriptions. A's complete schemas were identical; B's
only schema difference was the admitted tool-summary string. Accounting and
comparison results were independently reproduced.

The reviews preserve separate findings about indistinguishable catalog metadata
with strict replay IDs, signed-money extraction, inconsistent financial-caveat
judgments, contradictory stored verdicts and explanations, and historical-source
wording. Fixes to catalog identity, runtime behavior, or grading require separate
work outside this frozen SOP/description search. Additional facility-direction
wording was not tested because the two-round stopping rule was reached. No
unmeasured improvement is claimed. These exposed development results establish
neither generalization nor production qualification.

Plans, complete run evidence, independent review records, accounting, and the
final handoff remain in ignored `v2/eval/private/eval-climb/descriptions-20/`.
Only this append-only summary and concise current usage status are committed.
No push, PR update, merge, or deployment was performed; the outer session owns
ready PR602 stacked on PR600. There is no application patch to publish.


## 2026-09-25 — pass³ preparation; calibration stop

Prepared a separate change on PR #602 at `240512570aa7b1debe8295ea3ce1f7f45a80115a`.
The paid calibration used clean prepared commit
`f0dc64e2375d77ff8652263bcc97933a3a775c6a`: application `gpt-6-luna`, SOP
2.3.9, corpus 3.2.0, harness 2.2.0, and canonical Oracle 1.15.1. This is
preparation, with no candidate search or claimed application improvement.

The runner and comparison now use successful three-trial cases divided by all
100 cases. Inconclusives cannot succeed; promotion requires strict pass³
improvement, inconclusive nonincrease, comparable Grounding/Rules nonworsening,
and independent material-regression review. Historical recorded contracts retain
their original scoring and cannot be compared across contracts. Successful-trial
count and paired delta are diagnostics under the new contract. The bounded A/B
search, application model, stopping rules, and final confirmation pair remain.

The preparation adds cited unmet requirements with derived judge decisions,
signed-money wording checks, eight calibration contrasts, actor clarification
instructions, and shared cumulative accounting for actor checks. Original
references remain unchanged. The canonical catalog qualifies 24 endpoint labels
across 12 duplicate-metadata groups and retains original names as aliases.
Endpoint IDs, coordinates, directions, connections, prices, and public schemas
remain unchanged; wrong-ID replay still fails for current and annual calls.
Migration 034 registers the transactional, predecessor-checked, idempotent Oracle
1.15.0 → 1.15.1 metadata upgrade. The SOP explains approach-qualified labels.

Offline verification passed focused scoring, monetary/consent, actor/judge,
endpoint/replay, contract, compatibility, lint/type, skill, and corpus checks.
Disposable database checks passed upgrade and repeat application, predecessor
rejection, canonical bootstrap equivalence, and retained/current route, pricing,
report, and security contracts. The full database command initially failed only
at its final production-adoption test because that historical fixture used the
new development Oracle version. After pinning its Oracle fixture to the reviewed
historical source, that final test passed separately. Archived migrations and
release entries were not rewritten. Retained behavioral SQL receives narrowly
checked metadata substitutions only in temporary test copies.

The predetermined paid sequence was two fresh full-reference calibrations,
one full scripted actor check, and two identical 100-case × 3-trial application
runs with 16 workers. Application run two was to become the next baseline by
position, never by score. Only the first calibration was admitted: its complete
cost estimate was $0.39 and it ran all 143 references with 16 workers.

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

Independent Codex review identified material grading errors: Outcome rejected
correct answers by inventing disclosure/repetition requirements, and one unmet
requirement list cited evidence that explicitly described the requirements as
satisfied. Grounding also accepted one reference labeled as choosing a salary
before consent; the independent deterministic money check still detects that
violation. The structured decision interface prevents independently
generated boolean disagreement but does not itself guarantee semantic judgment.
No stored verdict or explanation was relabeled to erase these disagreements.

**Decision: stop paid validation on unresolved material grading ambiguity.**
The fresh calibration remains unapproved; no human trajectory adjudication is
claimed. Calibration two, the scripted actor check, and both application runs
were not started. There is no repeatability estimate, case-level application
comparison, or replacement incumbent baseline. No retry-until-pass or candidate
search occurred. Raw reports, transcripts, accounting, and review evidence remain
in ignored `v2/eval/private/preparation/`; only this summary is published.

The preparation implementation is available for human review, with the grading
blocker explicit. A future climb requires resolving that blocker under a freshly
reviewed contract and completing the remaining bounded validation with suitable
budget. It also requires human-reviewed merge and successful protected
development migration plus deployed catalog parity before any climb. This work
does not merge, deploy, or manually migrate a deployed database. GEPA-style
candidate pools, larger models, new runtime agents, and general workflow redesign
remain deferred.

Post-calibration CI correction: restored explicit authorization and reviewed-commit
provenance in the fresh corpus review record, updated the retired-input test to
supply the actor CLI budget, and regenerated package/shared-compatibility hashes
for the prepared SOP and Oracle schema. These delivery/test metadata corrections
do not change the measured application, grading code, or corpus payload. The
stopped calibration remains unapproved and no paid run was repeated.

The read-only PR plan then reported development serving release
`a5338c913f3c99b2eb895619bc287ba4d24e3aa0`, newer than the registered development
compatibility pin. Independent review verified its database, tool, shared-package,
SOP, agent, and database-contract sources are identical to the preparation parent
already validated. Only the development compatibility pin advances to that exact
serving release; the production pin stays unchanged. All 120 shared-package tests
passed, with exact-release acceptance and unrelated-release rejection checked.


### 2026-09-25 — user-directed overall-pass objective

Ryan subsequently requested alignment with the separate production gate work:
80% overall success on a blind holdout, and explicitly chose to update PR #603
now. The next development climb therefore optimizes successful trials divided by
all 300 expected trials. Pass³ remains a fixed-denominator reliability diagnostic;
a candidate can improve overall success while reducing pass³. Candidate selection
requires strict overall improvement and retains inconclusive nonincrease,
comparable Grounding/Rules nonworsening, independent material-regression review,
bounded A/B search, and the final confirmation pair. Eligible candidates rank by
overall rate, fewer changed lines, then A; an incumbent tie retains the incumbent.

This publishes corpus 3.3.0 / harness 2.3.0. Harness 2.2.0 keeps its recorded pass³
promotion semantics; earlier report fields/shapes remain unchanged, and
cross-contract comparisons remain rejected. Cases, fixtures, calibration
references, actor/judge prompts, and application behavior are unchanged by this
objective adjustment. The first calibration above remains a stopped 3.2.0/2.2.0
measurement, not a calibration of this new contract.

The production policy under separate development requires 240/300 successes
with valid simulations and complete measurements. Only its public policy and
usage contract were consulted; no blind cases or holdout feedback were accessed.
An 80% exposed-development score cannot qualify production and is not a new
search stopping rule. Production gate implementation stays in its own worktree.
The $20 cumulative development authorization and $15 preparation ceiling remain
unchanged. No further paid calls were made; material grading defects still block
calibration approval and continuation.

Fresh independent Codex review accepted the exact revised corpus/contract, with
no human adjudication claimed. All 85 focused runner/development tests and 11
comparison tests passed, including archived report reproduction, along with
lint/type, corpus and skill validation. The review explicitly leaves calibration
unapproved and paid continuation stopped.


## 2026-09-25 — uncapped overall-pass preparation; fresh calibration stop

Ryan authorized repairing the remaining grading defects and then attempting a
bounded three-round A/B climb on the exposed 100-case development set, optimizing
successful trials out of all 300 expected trials. This authorization explicitly
removes the prior $20 total and $15 preparation ceilings; it does not remove
usage accounting, measurement gates, or the search and confirmation stopping
rules. The preserved spending chain continues from $12.037866530.

Preparation starts from merged `fbe65eb404eab8546d6bfe638e8c90a66b19bc2d`.
The measured preparation commit is
`6e76aaffdba87fbaada1bb41546ca6bb6747d4cd`, with corpus **3.3.1**, harness
**2.3.1**, application **gpt-6-luna**, unchanged SOP **2.3.9**, and unchanged
Oracle **1.15.1** catalog. All original 143 reference objects and all 100 cases
remain unchanged; three focused contrasts cover equivalent versus omitted
published-schedule provenance and conditional income suggestion versus unilateral
adoption. No application prompt candidate was produced.

The runner and actor-check CLI accept explicit `--no-budget-limit`, mutually
exclusive with `--budget-usd`. Uncapped manifests record a null ceiling while
retaining cumulative prior spend, reservations, known-usage checks, call bounds,
and worker bounds. Capped behavior and historical comparison semantics remain.
General grading instructions distinguish actual violations from compliance,
preserved user inputs from mandatory prose repetition, optional schedule metadata
from required provenance, and conditional income suggestions from adoption.
Stored judgments still derive pass/fail from cited unmet requirements; no regex
relabeling or post-hoc verdict correction is introduced.

Fresh independent Codex review found the preparation code and all three new
reference labels acceptable before paid execution. Corpus approval identifies
that actual review and makes no claim of human trajectory adjudication or
calibration approval. Focused runner/corpus/development tests, 36 historical
compatibility tests, seven release-isolation tests, 11 comparison checks, corpus
validation, lint/type checks, and skill validation passed. Later tests covered
the added conditional-income contrast. No application model or runtime behavior
changed.

The predetermined sequence remains two full-reference calibrations, one full
scripted actor check, and two identical application runs, with the second
application run designated as baseline by position. Only calibration one was
admitted, estimated at $0.40 and run with 16 workers.

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

Independent review confirmed material grading errors. Multiple nonempty unmet
lists explicitly describe compliant behavior and conclude there is no violation.
Other judgments invent disclosure or question-format requirements, misinterpret
modeled provenance, confuse an annual return destination with its origin, and
accept an explicit actor stop before required endpoint facts are supplied.
Two additional wording-sensitive findings do not alter the stop decision because
multiple unambiguous errors independently invalidate grading readiness.

**Decision: stop; the fresh calibration remains unapproved.** The four earlier
disagreements now agree, but that does not establish a reliable repair: the same
failure mechanism recurs elsewhere. Different stochastic draws and changed
instructions prevent causal attribution of new disagreements to this patch.
No second calibration, actor check, application repeat, candidate search, or
confirmation ran. No training-set improvement or replacement baseline is claimed.
All raw verdicts, references, and accounting remain preserved privately.

Protected development delivery for the merged stack was still in progress at
this stop; migration completion and deployed catalog parity were not yet
verified. No manual migration or deployment was performed. Those checks remain
required before a future climb. A separately authorized grading repair must
resolve the structured-decision and actor-validity failures under a newly pinned
contract and fresh evidence. Runtime/tool changes, larger models, larger candidate
pools, and workflow redesign were not tested. Raw evidence stays in the ignored
preparation worktree; this journal is the only published experiment summary.


## 2026-09-25 — evidence-first grading repair; remaining source errors

Ryan explicitly authorized further grading fixes after the preceding stop.
The uncapped authorization and cumulative accounting continue; the failed
calibrations remain preserved and no prior verdict or label was rewritten.
The new measured commit is `565ff8d279d2465a623af37345ed4118d9073f44`, using
corpus **3.3.2** / harness **2.3.2**. All 146 reference payloads and labels,
100 application cases, fixtures, application SOP, models, actor generation,
tools, and catalog remain unchanged.

The judge schema now presents concise cited evidence before the unmet-requirement
list and before actor-validity status. Shared first-call instructions include
small generic supported/contradicted financial-claim examples. Actor grading
explicitly checks whether a supplied profile fact was requested and left
undelivered by an explicit goal-completed stop, distinguishing actual application
termination and forced max-turn stops. Compact context guidance addresses road
abbreviations, financial wording, missing-input clarification, and endpoint roles
within each leg. Pass/fail still derives only from list emptiness; there is no
regex relabeling, extra verifier call, or model substitution.

Independent offline review verified the actual SDK-converted field order and
unchanged field names, types, requiredness, constraints, and enum values. Field
order is a plausible repair mechanism, not a proven causal explanation; stored
JSON is reserialized and cannot establish the original generation order. All
140 focused tests, 36 historical compatibility tests, seven release-isolation
tests, 11 comparison checks, corpus validation, lint/type checks, and skill
validation passed. Fresh corpus approval reflects that independent code review
and does not imply calibration or human trajectory approval.

One new full-reference calibration ran with 16 workers, estimated at $0.42,
chained from the previous $12.306159540 cumulative spend.

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

Independent review inspected all nonempty unmet lists and found no recurrence of
satisfied requirements being listed as unmet. All ten preceding disagreement
references now match their labels with appropriate explanations, including the
premature actor stop. These are observations from one fresh draw under changed
instructions, not proof of causality or established judge repeatability.

Three disagreements remain. Two are clear material false passes: Outcome accepts
an answer missing explicitly required price-source disclosure, and Grounding
misses a false denial of the historical-observation source after otherwise correct
financial figures. The third involves criterion-boundary ambiguity: explicitly
keeping the old route after a correction clearly fails Outcome and Rules, but
does not necessarily claim that the old quote prices the corrected route.

**Decision: stop; calibration remains unapproved.** The repeat calibration,
scripted actor check, application baselines, candidate search, and confirmation
were not admitted. No application improvement is claimed. Further repair must
separate required-disclosure completeness from affirmative-claim accuracy,
check provenance denials alongside financial amounts, and clarify the route
correction boundary under a newly reviewed contract. Existing source and consent
labels must not be weakened to obtain agreement. Raw evidence and independent
review remain private. Migration and deployed catalog parity remain prerequisites
before any future climb; this repair performs no deployed mutation.


## 2026-09-25 — source completeness calibration; actor/input-grounding stop

Ryan authorized proceeding with calibration after the remaining grading fixes.
The fresh reviewed contract is corpus **3.3.3** / harness **2.3.3**, measured at
`7e4f69bf0f984d228f5f64daa60475644994f1e1`. Outcome now checks completion,
required disclosures, and factual accuracy separately; Grounding explicitly
checks source denials and distinguishes openly keeping an old route from falsely
claiming its quote prices a corrected route. The generic positive formatting
example no longer suggests that a correct amount alone completes all requirements.
Evidence-first output, verdict derivation, all 146 reference payloads and labels,
100 cases, application, actor generation, models, tool schemas and fixtures are
unchanged. No old evidence was relabeled or rescored.

Fresh independent preparation review found no material code/contract defect.
All 140 focused tests, seven release-isolation checks, 11 comparison checks,
corpus validation, lint/type/format checks and skill validation passed. Corpus
approval reflects that review only, with no human trajectory or calibration
approval claimed.

One full calibration ran with 16 workers and a $0.42 complete-run estimate,
continuing the uncapped ledger from $12.578573085.

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

The application-criterion denominator is 142 because one of the 143 valid
references was wrongly classified actor-invalid and excluded as inconclusive.
Those criterion fractions therefore do not imply all valid references were
correctly measured. Independent review checked all 93 nonempty assessments and
found no recurrence of satisfied requirements listed as unmet. All three prior
disagreements now agree with their labels; changed draws and prompts prevent
causal attribution or a repeatability claim.

Two clear material errors remain. Actor validity denies a correction visibly
delivered in the canonical second user turn, even though the same combined
assessment's Outcome explanation recognizes that correction. Confusion with the
empty auxiliary actor-reply log is a possible mechanism, not an established
internal cause. Grounding also accepts a derived annual-day count in a tool call
before user consent, treating valid arithmetic and successful execution as support
for an unaccepted user input. Outcome and Rules correctly reject that premature
call, but they do not replace Grounding's independent assessment.

Review also preserved observations outside labeled application metrics: a
correctly actor-invalid reference has a defensible Outcome disclosure concern,
and another retains a failed Outcome with an auxiliary rationale that confuses a
private required actor choice with the assistant's delivered workflow. These
observations were not used to change labels or assert extra confirmed defects.

**Decision: stop; calibration is unapproved.** No repeat calibration, actor check,
application baseline, candidate search, or confirmation was admitted. A further
repair must distinguish canonical delivered user messages from optional actor
records and arithmetic support from turn-local support for actual user inputs.
Existing instructions already cover these rules; this run does not establish
that additional wording alone will fix them. Raw evidence, costs, and independent
review remain private. No application improvement or deployed change is claimed.

## 2026-09-25 — delivered-turn/input-support repair; calibration repeatability stop

Ryan authorized proceeding with the remaining fixes and calibration, retaining
uncapped spending and all non-budget stop rules. The preparation repair is
`c84859b6bce422d2af6648cdf88f3816432dc23d`; both fresh calibrations measured
`468e576fef8b8a86e8ca09829d081aa47cacf6be`, corpus **3.3.4** / harness **2.3.4**.
Actor assessment now receives the exact delivered user turns separately from the
optional simulator control log. Grounding checks financial and schedule inputs
independently of output support, and the old-route exception no longer contains
a broad answer-only restriction. Successful execution, echoed inputs and correct
arithmetic cannot establish an unaccepted user fact. The recorded-call heading
now describes execution without implying correctness.

Independent preparation review found no material defect. All 146 reference
payloads and labels, 100 cases, fixtures, application, actor generation, models,
settings, schemas and verdict derivation remain unchanged. Offline checks covered
142 focused tests, seven release-isolation checks, 11 comparison checks, corpus
validation, lint, formatting, types and skill validation. The review-required
check initially failed while the new contract review was pending, then passed
after that independent review was recorded; the assertion was not weakened.

The predetermined pair ran on identical application/evaluation identities with
16 workers, an estimated $0.43 per complete calibration, and a continuous ledger
starting at $12.849787605. Neither run regenerated application conversations.

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

Both prior failures—the missed delivered correction and unaccepted annual-day
input—were correctly explained in both runs. All 876 stored criterion booleans
match unmet-list emptiness. The first independent review inspected all 94
nonempty assessments and found no material scoring error; two limited citation
or auxiliary-rationale errors were preserved without changing labels. That
review supported the planned repeat, not application improvement or human
trajectory adjudication.

The unchanged repeat changed four scored criterion decisions across four
references: three Outcome passes became false failures, and one Grounding
failure became a false pass. Independent review confirmed all four as material
judge errors. Outcome invented extra disclosure requirements for comparison
provenance, an available historical date range, and a field-by-field enumeration
of unavailable annual results. Grounding missed a final statement labeling the
combined annual cost as toll alone after an otherwise correct financial answer.
Rules and actor validity had no decision changes. These are judging variation,
not changes in application quality or proof that the repair caused regressions.

**Decision: stop; the calibration pair is unapproved for application execution.**
The first run's repeat-admission approval was retained privately as history and
removed from active calibration readiness after the repeat failed. No third
calibration, scripted actor check, application baseline, candidate search or
confirmation was admitted. The pair cost **$0.535169550**; cumulative known eval
spend is **$13.384957155**. A further repair needs independent review of requirement
applicability and contradictory financial claims before new paid admission;
another unchanged-contract retry is not justified. No labels or historical
measurements were altered. Raw reports and review evidence remain private.

The protected development delivery for merged `fbe65eb404eab8546d6bfe638e8c90a66b19bc2d`
completed successfully in workflow run `36148909062`, including its registered
migration step. Deployed catalog parity remains unverified and is still required
before a future climb. No database query, manual migration or deployment was
performed during this repair.

## 2026-09-25 — requirement applicability calibration; Outcome reliability stop

Ryan explicitly requested another calibration round after the repeatability stop.
The separately reviewed preparation at
`102eb91a2a78e3de6907170a58e486ba983e803a` moved unchanged domain/catalog context
before criterion policy and consolidated the decision guidance. Outcome now
checks a requirement's applicability and policy exceptions before declaring an
omission, including expected unavailability within a multi-request answer.
Grounding separately checks call inputs and all output claims, including final
prose and financial labels. These are general judging instructions, not changes
to the application, actor generation, models, schemas, references or labels.

Independent preparation review found no material defect. The 142 focused tests,
seven release-isolation checks, 11 comparison checks, corpus validation, skill
validation and lint/type/format checks passed. Captured requests verify that
policy follows supporting context for all three criteria; assessment schemas
and list-derived verdict conversion remain unchanged. The new contract is
corpus **3.3.5** / harness **2.3.5**, measured at `76f4006`.

One fresh full calibration ran with 16 workers, a $0.45 complete-run estimate,
and uncapped accounting chained from $13.384957155. No application conversations
were regenerated.

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

Independent review confirmed all nine disagreements as material Outcome errors:
seven false failures and two false passes. The false failures demand optional
rate-period wording, reject a correct two-component breakdown, add historical
source wording to a fixed-rate disclosure, misread three correctly labeled
remaining-income statements as financial contradictions, and reject a supported
missing-history explanation. The false passes overlook the required invitation
to adjust proposed annual days and the omitted vehicle-cost assumption.
All 98 nonempty assessments were inspected. Three financial-label failures cite
semantically matching claims as contradictions, despite correct structured
conversion; the semantic defect cannot be fixed by changing boolean derivation.

The three actor-invalid exclusions remain supported. A changed Outcome decision
on an excluded route-decline trajectory is defensible for the delivered facts
and has no expected application label; it is not counted as another judge error.
Different prompts and draws prevent causal attribution of the additional errors
to context reordering. Matching Grounding/Rules/actor labels in this run does not
establish repeatable judge correctness or an application improvement.

**Decision: stop; calibration remains unapproved.** No second calibration,
scripted actor check, application baseline, candidate search or confirmation was
admitted. The available evidence does not justify another wording-only paid
round: the current judge still invents requirements, misses explicit requirements
and misreads equivalent financial statements. Revisit the grading approach under
a separately reviewed, authorized plan before further calibration; do not weaken
labels, select a favorable prior run, or retry the unchanged contract. All raw
evidence and review details remain private. Deployed catalog parity remains a
separate prerequisite before a future climb; no deployed mutation occurred.

## 2026-09-25 — Luna/high calibration pair clears; actor stopping blocks continuation

Ryan authorized moving golden judges directly to Luna/high without a comparison
arm, retaining uncapped accounting. Preparation `a7174dd` adds a shared judge
builder used by the three-criterion runner and scripted actor assessment, with
an 8,192-token output ceiling. Role-specific reservations and run identities
record that allowance. TollChat remains **Luna/low/2,048** and actor generation
**Luna/medium/2,048**. Prompts, reference payloads and labels, schemas, application
sources and actor generation are unchanged. Legacy scheduled evaluation is
outside this golden contract and remains unchanged.

Independent preparation review found no material defect. Relevant offline tests,
historical compatibility checks, seven release-isolation checks, 11 comparison
checks, corpus and skill validation, and lint/type/format checks passed. An old
medium-effort assertion was corrected and its targeted rerun passed. SDK request
checks verify all three roles and their accounting reservations. Fresh corpus
review records the actual Codex review with human trajectory adjudication false.
The contract is corpus **3.3.6** / harness **2.3.6**, measured at
`1d6bc4fd5ce44eea886e25041e1c05c70738ca52`.

Two predetermined full calibrations ran sequentially with 16 workers and
identical identities. The first received independent review before the second
was admitted. Both used a conservative $3.50 complete-run estimate and chained
uncapped accounting from $13.656770515.

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

There were zero criterion or actor-validity flips, including excluded rows.
Independent review inspected all 93 nonempty assessments in each run, the 27
previously disagreeing reference rows, original financial/source/consent
contrasts, and all three actor-invalid exclusions. All 876 verdict/list
conversions and token-derived costs reconciled. No material grading defect was
identified. The excluded healthcare trajectory retains a minor caveat-wording
ambiguity, but its actor exclusion is independently supported and no scored
criterion depends on resolving that ambiguity.

**The pair is recorded as Codex-reviewed development calibration**, with human
trajectory adjudication false. These are repeated exposed references, not new
coverage or human gold-label adjudication. No comparison arm was run, so this
does not isolate an effect of reasoning effort or establish generalization.

The next predetermined full scripted actor check ran on the same committed
identity with 16 workers and a $3.50 complete-run estimate. It completed all 300
unique trials: **296 valid and four inconclusive**, with 423 actor calls and 296
judge calls, all usage known. Cost was **$0.277166100**. Independent review
inspected all four inconclusives and relevant passing stopping, cancellation,
income and unavailable-history contrasts, plus actor and checker control flow.

Three trials genuinely failed to stop after disclosing unavailable income and
receiving the assistant's explanation of that limitation. The fourth rejected
route alternatives first and supplied the profile-required cancellation in a
later reply. The fixed script classified that continuation as unnecessary when
it exceeded the scripted length; the pending cancellation exposes a script
alignment limitation rather than proving a semantically unnecessary action.
All four failures occurred before judge assessment and remain inconclusive.
They do not invalidate the separately reviewed fixed-reference calibration.

**Decision: stop before application repeats and candidate search.** No retry,
relabeling, application baseline, candidate patch or confirmation was performed.
A bounded next preparation could clarify precedence between answering repeated
questions with known facts and stopping after acknowledged genuine unavailability,
and encourage delivering jointly triggered profile actions together. Competing
actor instructions are a plausible mechanism, not established causation. Such a
repair needs a separately admitted contract and fresh matching validation; the
frozen actor was not changed during this measurement.

Total spending for this sequence was **$0.861823660**, bringing cumulative
accounted evaluation spending to **$14.518594175**. Raw evidence and reviews
remain private. No application improvement, release qualification or deployment
is claimed. Deployed catalog parity remains unverified and required before a
future climb; no deployed mutation occurred.

## 2026-09-25 — Private production qualification policy 3.0.0

Ryan selected an **80% overall admission floor** for a future independently
authored **100-case private holdout**, with three trials per case: at least
**240 successful trials out of 300**, all valid and fully judged. Per-case pass
requirements, the consistency floor, automatic regression veto, and latency and
cost-per-success quality cutoffs are removed. Complete measurements, spending
limits, exact-artifact provenance, fresh evidence, and human release review remain
required. An evaluated production baseline is no longer a prerequisite.

The repository now imports externally signed aggregate summaries rather than
executing production holdout cases. Cases, expected answers, fixtures, transcripts,
case-level outcomes, and the real signing key remain outside coding-agent access.
Ed25519 verification binds aggregate evidence to the reviewed policy, private
holdout/evaluator/calibration identities, and exact development artifact. Repeated
use is disclosed as a reused private benchmark; the signed attempt history retains
an original and at most one independently authorized infrastructure/actor-validity
replacement. Quality-only reruns are prohibited. Aggregate reports show failures,
inconclusives, fixed denominators, consistency, uncertainty, latency, cost, and
attempt count instead of presenting admission as a claim of real-world accuracy.

**No agent performance was measured and no paid calls were made for this change
($0 evaluation cost).** The application model/prompt, grading rubric, development
corpus, and historical scores are unchanged. Synthetic signing/admission checks
exercise the new integration without private cases. The active policy remains
pending: real holdout authoring, external evaluator provisioning and review, the
public key and contract pins, exact policy approval, aggregate-only IAM activation,
and fresh signed qualification evidence are still required. No deployment or
production qualification is claimed. Current operation and activation requirements
are documented in [the production gate guide](GOLDEN_RELEASE.md).

Validation: the broader release/migration regression suite passed **328 tests**
with **two skipped**; the final focused private-gate suite passed **41 tests**.
Historical baseline compatibility tests also passed. Ruff, strict Pyright,
workflow/ShellCheck checks, and backend-disabled Terraform validation passed.
Deployment-input hashes were updated for the aggregate-only IAM and migration
receipt bindings. Later production stages verify the signed envelope carried in
the receipt without needing development-storage credentials.

### 2026-09-25 — Adversarial review corrections before private-gate activation

The local adversarial review reproduced two recovery failures: publishing the
candidate index before a failed receipt upload prevented a new import of identical
evidence, and freezing provisional costs prevented signed usage reconciliation.
The receiving workflow now allows a newer, human-approved import to conditionally
replace the index of a completed prior import only for the identical summary digest.
S3 versioning preserves prior pointers; changed evidence, active/untrusted prior
runs, older imports, and concurrent writes remain blocked.

Outcome claims now exclude provisional costs. Full signed reports remain immutable,
and the first usage-complete summary freezes per-attempt accounting separately.
Reconciliation may correct costs while outcomes remain unchanged; finalized costs
cannot subsequently change. No extra evaluation, quality retry, or rescoring is
authorized. Synthetic regressions exercise both failures and the rejection paths.
The external evaluator, private corpus, key, and policy approval remain pending;
these fixes made no paid model calls and do not qualify or deploy an application.

Post-correction validation passed **339 relevant tests**, with **two skipped**,
plus repository static checks, secret scanning, and Terraform validation. The
focused gate/retirement set includes 56 passing checks, including recovery of
identical evidence, rejected pointer races, and one-time cost reconciliation.

## 2026-09-25 — Public private-holdout authoring kit

Purpose: prepare independent authoring without exposing any held-out scenario to
the repository coding agent. Added an allowlisted public packet, schemas, three
disposable teaching cases, and a credential-free offline validator with distinct
draft and final modes. Final validation requires 100 distinct scenario groups,
the 40/55/5 workflow allocation, complete good-reference coverage and at least 20
negative references. It freezes a private manifest; semantic review remains
pending and separate.

Versions: authoring kit 1.0.0; development contract 3.0.7 / harness 2.0.14. Shared
payload validation and currency parsing retain the development cases and labels.
Evaluator source identities changed, so development approval is reset to pending;
old calibration and application results keep their original identities. The
application model, SOP and production gate thresholds are unchanged.

Validation: synthetic draft/final rehearsal in an exported directory, with
credentials absent and socket access rejected; malformed inputs, arithmetic
errors, actor leakage, missing references, unsafe paths, kit drift and frozen
corpus drift are rejected. Focused development, evaluator and release inventory
checks run offline. The scheduled-eval package includes the extracted currency
helper and passes its deterministic build/import check. These are software
contract checks, not measurements of agent quality.

Cost: $0 in model evaluation spending. No real holdout cases were authored,
viewed or run. No signing key, paid calibration, infrastructure activation or
deployment was performed. Decision: ship the public preparation kit; actual
authorship, semantic review, isolation verification and evaluator activation
remain within the independent private boundary.

### 2026-09-25 — Authoring-kit integration correction

PR #605 review found an omitted development release-manifest refresh. Reconciled
the stack with current main, retaining its 143 references, rubric fixes and
overall-pass scoring. Kit 1.0.1 now uses contract 3.3.1 / harness 2.3.1 with
development review pending. The shared currency parser lives in the existing
trusted tool-package inventory, so no new verifier allowlist is needed. Rebuilt
the affected agent and scheduled-eval packages and refreshed source/package
digests. The trusted main verifier accepts the inventory; 173 focused tests and
three subtests pass. No model calls or private holdout data were involved.

The subsequent read-only development plan found that the shared-package review
still named an older serving release. Reviewed the transition against the
reported serving release `fbe65eb404eab8546d6bfe638e8c90a66b19bc2d`: loader,
publisher, timed-check handler, SQL and schemas are unchanged; scheduled-eval
currency parsing is extracted without changing behavior. Bound the development
review to that release and the rebuilt timed-checks digest, retaining the
production baseline. Updated the mixed-version test to accept an already-current
schema as well as the reviewed production schema-label migration. All 78 focused
compatibility, scheduled-evaluation and bundle tests pass; CI remains the merge
gate. No deployment or model evaluation was performed.

## 2026-09-25 — actor completion repair clears; normal-status grading error found

Ryan authorized actor repairs and reruns, then continued fixes and measurements
until ready for a new application baseline, followed by a ready-for-review PR.
Uncapped accounting persists; the baseline itself is not part of this preparation.
The actor repair at `54eb25f` gives acknowledged genuine unavailability precedence
over repeated requests for known facts, and requires jointly triggered profile
actions together while deferring future triggers. Models, profiles, schemas,
scripted-check logic, reference payloads and labels remain unchanged.

Reviewed main `94f89ca` was merged before measurement, preserving its shared
currency parsing, complete payload validation and public production gate.
Both journal histories were retained. Independent supplemental review confirmed
these integrations and the unchanged judge prompts, application prompts and
actor-check behavior. Fresh preparation approval was recorded without claiming
human trajectory adjudication. The contract was corpus **3.3.7** / harness
**2.3.7**, measured for actors at `92b00f0`.

The full scripted actor run completed **300/300 valid trials**, with zero
inconclusives and 723 complete known-usage calls (423 actor, 300 judge).
Independent review inspected all 114 trials across the 38 staged profiles and
verified termination without continuation for the remaining 186. All six trials
of the two formerly troublesome scenarios now meet their completion conditions.
Known facts, staged choices, corrections, cancellation and workflow switches
remained intact. The scripts do not exercise repeated-question loops or arbitrary
live application trajectories; this result does not establish universal actor
reliability or a causal effect from one stochastic run.

Cumulative PR review found no material code defect. Its CI coverage finding was
fixed at `b7441bc`: the existing golden-validation step now explicitly executes
the comparison helper's regression suite. Actionlint and the exact CI command
passed. Relevant runner, corpus, retirement, historical compatibility, comparison,
lint/type/format and skill checks passed. The CI-only commit does not alter the
application or semantic evaluation identities.

Two fresh full calibrations followed sequentially at `b7441bc`, with independent
review before admitting the second. All three runs used 16 workers, conservative
$3.50 complete-run estimates and the existing spending chain.

| Measure | Actor check | Calibration 1 | Calibration 2 |
| --- | ---: | ---: | ---: |
| Complete trials/references | 300 | 146 | 146 |
| Complete calls, all usage known | 723 | 438 | 438 |
| Actor validity/agreement | 300/300 | 146/146 | 146/146 |
| Outcome agreement on valid references | Not scored | 143/143 | 142/143 |
| Grounding / Rules agreement | Not scored | 143/143 each | 143/143 each |
| Cost | $0.287175100 | $0.288319200 | $0.289602700 |

The second calibration falsely rejects one correct current-price reference solely
for omitting normal OPEN status. Independent review confirms that neither the
request nor contract makes normal successful availability a required separate
disclosure. Price, source, observation time, route and clarification are correct.
This is a material judge error, not a reference-label defect. One excluded
actor-invalid route-alternatives reference also changes its Outcome decision;
its actor exclusion and all scored labels except the normal-status false failure
remain unchanged. No measurement failure or unknown usage occurred.

**Decision: retain the actor evidence, leave this calibration pair unapproved,
and repair availability materiality under a new contract before baseline
admission.** Do not rewrite the failed verdict, inherit the first run's apparent
success, or retry the unchanged pair. The bounded repair must distinguish normal
successful/open metadata from restrictions or explicitly requested status, while
preserving closure, staleness, missing-data, source and timing requirements.
Fresh matching measurements and review are required. No application baseline,
candidate search, merge or deployment occurred.

This sequence cost **$0.865097000**, bringing cumulative accounted evaluation
spending to **$15.383691175**. Raw run evidence remains private. Preparation is
continuing under Ryan's authorization; reviewed merge and deployed catalog parity
remain prerequisites for a later climb.

Supplemental semantic review of the excluded route-alternatives row identified
an unsupported Outcome failure: the judge acknowledges the permitted discovery
call but still demands an estimate after the delivered user declines its returned
alternatives. This does not create a new expected label or change the actor
exclusion. It does expose confusion between expected validation failure and an
agent-caused mistake that could affect valid unavailability paths. Before any
3.3.8 paid run, the bounded preparation also clarifies that distinction and the
need to respect the delivered refusal of alternatives, preserving all other
applicable obligations. The original failed report remains unchanged.

### 2026-09-25 — Final preparation calibration and reliability stop

Corpus **3.3.8** / harness **2.3.8** clarifies normal successful status versus
material restrictions, and permitted discovery unavailability versus an
agent-caused failure after the delivered user declines alternatives. Independent
preparation review cleared these bounded changes before measurement at
`3af9d9f`. Application, actor prompt, models, schemas, reference payloads and
labels remained frozen. Preparation approval does not approve calibration or
claim human trajectory adjudication.

The predetermined sequence was two full calibrations followed by a matching
300-trial actor check, with independent review between admissions. The first
calibration completed all **146 references and 438 calls**, with complete known
usage, no measurement failures and 16 workers. Outcome agreed on **142/143**
valid references; Grounding and Rules each agreed on **143/143**; actor validity
agreed on **146/146**. The two newly clarified mechanisms were correctly graded
in this run. These fixed, exposed references do not establish reliability on
unseen application trajectories.

The remaining false Outcome failure treats a recognizable road abbreviation as
an internal endpoint ID despite an explicit existing rule accepting that
rendering. Other references with the same presentation pass in this batch.
Independent review confirms existing-policy noncompliance, not a reference-label
defect or a missing domain rule. Another wording-only exemption is not justified;
the failed verdict and reference label remain unchanged.

The independent audit covered all 94 nonempty assessments, 27 historically
problematic references, eight additional passing or boundary contrasts, and all
three actor-invalid exclusions. It found no additional material grading error.
All 146 trajectories and expected labels match the frozen references; semantic
identity, evidence digest and accounting reconcile. The previously documented
caveat ambiguity in one excluded reference remains unlabeled and does not become
an application approval.

**Decision: stop dependent paid admission and open the preparation PR for code
review, with baseline readiness explicitly blocked.** The calibration remains
unapproved; its planned repeat and matching actor check were not run. The earlier
300/300 actor result belongs to contract 3.3.7 and is not transferred as final
contract qualification. No application baseline, candidate search, holdout
evaluation, merge, migration or deployment occurred. Reviewed merge and deployed
catalog parity remain gates for the later climb.

Independent code review found no material defect. All 150 relevant runner,
development, corpus and retirement tests passed, alongside comparison, corpus,
lint/format/type, workflow, skill and contract-version checks. An offline exercise
of the actual baseline admission path confirmed that the unapproved calibration
is rejected before run creation, credentials or model calls. Raw evidence and
detailed reviews remain private.

This calibration cost **$0.291537200**, bringing cumulative accounted evaluation
spending to **$15.675228375**. Explicit uncapped authorization remained in effect;
the stop is for grading reliability, not budget.


### 2026-09-25 — Luna xhigh calibration preparation completed

Ryan authorized increasing only the golden judge reasoning effort from high to
**xhigh**, retaining `gpt-6-luna` and the 8,192-token output ceiling. Application
generation remains low/2,048 and actor generation medium/2,048. Prompts, grading
policy, reference trajectories and labels, fixtures, tool schemas and application
behavior remained frozen. Corpus **3.3.9** / harness **2.3.9** records the changed
measurement contract; comparison tooling admits the new version while retaining
historical semantics. No earlier approval or failed verdict was transferred.

Independent preparation review cleared `9b1d1d2`. The predetermined sequence ran
at the unchanged measurement commit `a8415ef`, with 16 workers and independent
review before each dependent admission. An expired SSO login was resolved before
any model call. Existing uncapped authorization and cumulative accounting
continued from the prior stopped calibration.

| Measure | Calibration 1 | Calibration 2 | Scripted actor check |
| --- | ---: | ---: | ---: |
| Complete references/trials | 146/146 | 146/146 | 300/300 |
| Application label agreement | 429/429 | 429/429 | Not scored |
| Actor labels / valid actor trials | 146/146 | 146/146 | 300/300 |
| Complete calls, all usage known | 438 | 438 | 723 |
| Cost | $0.331475370 | $0.319100040 | $0.320316600 |

Both calibrations have zero disagreements or measurement failures. All verdicts
agree across the two runs, including the three actor-invalid exclusions. The
previous road-abbreviation false Outcome failure passes in both. Independent
reviews inspected all 93 nonempty assessments per run, negative controls, 29
historically problematic references, additional passing contrasts and all actor
exclusions, alongside frozen-input integrity, evidence digests and accounting.
No material grading error was found.

The reviews retained nonmaterial explanation defects: some Grounding rationales
use incorrect direction or overly broad route-match wording, also present in the
first run. Those labels remain justified under the Grounding boundary, while
Outcome and Rules correctly reject the erroneous routes. The previously recorded
caveat ambiguity in an excluded actor-invalid reference remains unlabeled. No
verdict was rewritten. Fixed exposed references and two stochastic draws do not
establish causal improvement or unseen-trajectory accuracy.

Independent actor review inspected all 114 staged trials across 38 profiles and
verified explicit completion without an undelivered message in the remaining
186 trials. Scripted responses and tool payloads match the fixed references. All
300 judge and 423 actor calls completed. These scripts do not exercise arbitrary
live application trajectories or repeated-question loops; no universal actor
reliability or human trajectory adjudication is claimed.

**Decision: calibration preparation is complete.** Both calibrations have fresh
reviews bound to their evidence digests, and the matching actor check is reviewed.
The offline actual admission path accepts the matching calibration but was stopped
before run creation, credentials or model calls; the changed-effort regression
rejects stale approval. All 151 relevant runner, corpus, development and retirement
tests passed, together with 11 comparison checks, corpus validation, lint/format/
type checks, skill validation and tool/agent/schema contract checks.

The sequence cost **$0.970892010**, bringing cumulative accounted evaluation
spending to **$16.646120385**. Raw evidence and detailed reviews remain private.
No application baseline, candidate search, holdout evaluation, merge, migration
or deployment occurred. Human-reviewed merge and verified development
migration/catalog parity remain prerequisites for a later baseline.


## 2026-09-26 — Retrospective summaries of retired evidence

The summaries below consolidate historical reports during repository cleanup.
They preserve the recorded results and limitations; they do not rescore runs,
renew approvals, or add spending to the current cumulative ledger. Original
manifests, events, reports and standalone analyses remain recoverable from the
[pre-cleanup commit](https://github.com/rhprasad0/nova-toll-budget-agent/tree/e2b7d4b5514ce3f0228d2556ab197f0c1c38ec1a/v2/eval).
Future granular output belongs in ignored `eval/private/` or the existing private
workflow artifact store. Focused synthetic tests replace archived-run test inputs.

### Legacy golden demonstration and calibrations

These source-checkout experiments used `gpt-5.6-luna`, prompt 2.3.0, renderer
1.0.0 and a 2,048-token ceiling. They predate the current measurement contract.
The demonstration and calibration 7 used low reasoning; calibration 15 used low
for application/actor generation and medium for judging.

| Historical run | Commit | Corpus / harness | Recorded result | Run cost | Prior recorded spending |
| --- | --- | --- | --- | ---: | ---: |
| Demonstration, 2026-09-20 | `e9abf4eaef1b6f4bc615815c7b9b302ba8710821` | 1.0.5 / 1.0.4 | 27/72 successful trials (37.5%); 3/24 cases passed all three (12.5%); 546 model calls | $0.38888630 | $0.33607270 |
| Calibration 7, 2026-09-20 | `a3c30b60dd100f299e9085bd20847569eea10d3a` | 1.0.7 / 1.1.0 | 100/102 label agreement across 34 references; 103 model calls | $0.07223746 | $0.79967600 |
| Calibration 15, 2026-09-21 | `41f09f991cf0a2db54bd9410b33eb55d080be6e9` | 1.0.11 / 1.2.1 | 138/138 label agreement across 46 references; 138 model calls | $0.06590064 | $2.06711088 |

The demonstration completed all 72 measurements, with 37 Outcome passes, 16
Grounding violations and 24 Rules violations. Its recorded 95% case-cluster
interval for successful trials was 25–50%; repeated trials are not independent.
Human actor review remained pending. The retained
[initial review](results/golden/initial-review.json) marks actor validity invalid:
actors stopped before required clarification/correction, a held-out confirmation
was not delivered, catalog aliases affected exact-ID judgments, and the run did
not verify production-artifact execution. Historical held-out material was
exposed by the review page. **Decision: preserve as a limited demonstration,
without release or baseline approval.** Its duplicate registry archive has the
same historical status.

Calibration 7 retained two Grounding disagreements: an unauthorized early Tysons
call and a missing-schedule clarification reference. The original report remained
pending human adjudication. **Decision: retain the disagreement evidence as
historical calibration work, with no current approval inferred.**

Calibration 15 had no recorded disagreements. Ryan's 2026-09-21
[exact-evidence approval](evidence/golden-360/calibration-15/review.json) remains
unchanged. It accepted the historical actors-6 limitation (59/60 checks, including
a redundant vehicle/E-ZPass reply) and expressly authorized no merge, deployment
or production qualification. **Decision: preserve that historical approval;
its contract does not qualify the current corpus or application.**

### August 22 live integration checks

Three selected 2026-08-22 runs each recorded a 1.0000 code-graded score:

| Scenario | Recorded result | Checked behavior |
| --- | --- | --- |
| Reagan Airport and Pentagon/Eads Street to Westpark | 2/2 passed | Each made the exact current-price call to `i495:1859ND` and returned two observed components totaling $14.65, with movement and median comparison. |
| Dulles Airport to Reagan Airport | 1/1 passed | The cross-direction request returned typed stale I-95 availability; the response withheld a price. |
| Annual affordability workflows | 6/6 passed | Fixed/modeled success, Tysons exit clarification, complete input acquisition, salary-range clarification, adjustable 52-week annual-day estimates, and unavailable return routes. |

The two Westpark responses labeled a 10:50 observation as EST in August; the
historical code-graded passes do not establish timezone-label correctness. The
reports did not record model/version identity or measured cost; those values are
unavailable. These selected live checks are neither a frozen application baseline
nor a whole-agent accuracy estimate. **Decision: retain the aggregate integration
findings and remove the raw response/trajectory reports.**

### Annual ballpark grounding experiment

The historical OpenAI Batch experiment used `gpt-5.6-luna` and one frozen,
reviewed Springfield-Franconia–Westpark annual tool result: Monday–Friday,
8:30 AM outbound and 5:30 PM return. Five reviewed prompt variants were each
repeated 200 times. Deterministic checks were followed by adjudication of every
flagged quantitative claim and semantic review of contract failures.

| Measure | Result |
| --- | ---: |
| Reconciled responses, transport success, correct P25/P50/P90 tables | 1,000/1,000 each |
| Strict quantitative grounding | 996/1,000 (99.6%) |
| No incorrect quantitative fact | 999/1,000 (99.9%) |
| Core semantic contract | 971/1,000 (97.1%) |
| Core contract plus explicit TollChat attribution | 935/1,000 (93.5%) |
| Core contract plus strict quantitative grounding | 967/1,000 (96.7%) |
| Attribution requirement plus strict quantitative grounding | 931/1,000 (93.1%) |

One response changed the supplied 5:31 PM evaluation time to 1:31 PM. Three
others computed correct scenario differences ($3,156 twice; $1,008 once) absent
from the tool payload. Those three violated the tool-returned-numbers policy;
their arithmetic was correct. Of 29 core-contract failures, 28 inadequately
disclosed 50/60-day (83.3%) coverage and one omitted the $14,088 annual P50 toll
amount. Another 36 otherwise complete answers omitted the TollChat attribution
for the fixed vehicle-cost assumption.

The raw deterministic score of 426/1,000 was invalid as a model-performance
result: literal matching rejected 441 equivalent 12-hour timestamps, eight
rounded currency renderings, and valid wording/formatting. **Decision recorded
by the report:** fix and regrade that grader before using it as a release gate;
report newly derived arithmetic separately; strengthen or simplify disclosure
instructions only if required; add routes, evidence shapes and unavailable-result
fixtures before broader claims. This retrospective does not claim those follow-up
actions are complete.

The `tiktoken` 0.14.0 / `o200k_base` preflight estimated 35,148,600 input tokens,
with a 38,663,460 guarded estimate below the then-recorded 40,000,000 queued-token
limit. Actual usage was 30,196,200 input and 638,936 output tokens. Measured dollar
cost was not recorded in the report and is unavailable. These historical capacity
figures are not current service limits. Correlated repetitions of one fixture do
not establish an agent-wide hallucination rate, route coverage, source accuracy
or production performance. Executable cases and runner remain in the repository;
raw artifacts remain private under `eval/private/annual-ballpark-hallucination/`.

### I-95/I-495 identity-proxy validation

The historical study addressed 16 missing OD IDs (1374–1389): the route oracle had
330 distinct IDs while retained VDOT history priced 314, affecting 107 of 685
routes. The `identity_proxy_v1` model copies the mapped VDOT price without
adjustment. [Current mapping and query guidance](results/i95-missing-od-pricing.md)
retain the modeled-label, direction and no-fallback requirements.

The study paired 578 retained Transurban captures from July 25–30, 2026 with
VDOT's corresponding ten-minute intervals, filtered to the open direction, and
used the first 70% chronologically for model selection and the final 30% for
assessment. Across 1,200 holdout comparisons, identity copying had **$0.106 MAE**,
**96.1% within $0.50**, **$0.00 p95 absolute error**, and **$8.05 maximum error**.
Ordinary least squares increased MAE to $0.154; median bias correction selected
$0 for every mapping. PostgreSQL regression, correlation and percentile functions
were diagnostic tools, not the production formula. Measured analysis cost was
not recorded and is unavailable.

**Decision: retain the identity proxy as a provisional ballpark estimate.** The
short overlap does not establish seasonal accuracy. An adversarial review left
these limitations and follow-up work unresolved:

- Pooled results can hide weak OD mappings or traffic regimes. About 47/1,200
  comparisons exceeded $0.50 based on the rounded rate. Per-OD counts, unique
  intervals, exact matches, signed bias, MAE/RMSE, p95/p99, maximum errors and
  direction/rush-hour strata are still needed for stronger claims.
- Rows are clustered within captures; 1,200 comparisons are not independent.
  Preserve the exact split, unique holdout intervals, duplicate handling and
  confirmation that proxy selection used only training data.
- VDOT republishes the Transurban series about ten minutes later, so the feeds
  are not independent evidence. Reproduction needs the pairing query and a
  non-secret input manifest covering clock shift and S3 `LastModified` alignment.
- Restore tests verify mapping constants and SQL behavior, not each mapping's
  empirical quality. Retain a runnable analysis and per-OD output before claiming
  every mapping is validated; compare each against identity, mean/median offsets
  and simple destination-matched baselines.

These objections do not show that the model is wrong. They limit the accuracy
claims supported by this historical study; modeled labels and withholding an
estimate when the view has no eligible row remain required.

## 2026-09-26 — Adversarial-review fixes before the next climb

Ryan authorized the review fixes and a ready-for-review PR. The deterministic
money check rejected a supported “$2.50 decrease” while accepting “decreased by
$2.50” against the same negative movement evidence. Contract **3.3.10 / harness
2.3.10** now recognizes decrease, drop and reduction after an amount. Focused
regressions retain rejection of wrong signs, wrong amounts and an unsupported
absolute price. Cases, calibration references, fixtures, tool schemas and model
settings are unchanged. The corpus review is **pending**; old approvals do not
transfer, and new calibration is required before an application run.

The climb now names **270/300 successful trials (90%) on fresh confirmation** as
the development target, requires all trials valid and measured for that milestone,
and reports per-case success/scoring/violation counts. Existing numeric promotion
and violation gates remain unchanged. Review distinguishes demonstrated regressions
from sampling uncertainty using all three trials and the unchanged-application
repeatability pair. Fresh trajectory audits include passing and failing examples
from each coverage family, actor exclusions and new violations. A failed final
confirmation is retained without retrying for a favorable score. Later campaigns
require authorization and preserve cumulative spending.

Application SOP **2.3.10** clarifies call limits within an assistant turn versus
new user-authorized requests, preserves the Washington correction and consent
rules, and scopes annual presentation instructions explicitly to annual success.
The change has no measured application-performance result. Luna remains low/2048
for the application, medium/2048 for actors and xhigh/8192 for judges. Capacity
experiments, broader route-resolution changes and separating actor/Outcome judge
calls remain deferred until fresh trajectory evidence justifies them. Frozen
replay still does not establish live pricing or deployment correctness.

**Offline validation:** 187 focused harness, corpus, retirement, agent and tool
contract tests passed; all 12 comparison checks passed. Corpus validation, skill
validation, Ruff, strict Pyright and agent/tool manifest advancement checks passed.
The 100 cases, 146 references and 107 fixtures retain their prior data hashes.
No paid model calls, calibration, application baseline, holdout access, migration
or deployment occurred. Incremental evaluation cost: **$0**. Historical costs and
results above are unchanged. The 80% independent holdout requirement remains a
separate qualification step.

### 2026-09-26 — PR package-verification correction

The first PR build rejected the unchanged delivery manifest after the SOP and
agent-version edit. Rebuilt the packages and refreshed the two changed source
digests plus `agentcore.zip` and `timed-checks.zip` digests; the other package
digests are unchanged. The local release verifier accepted the rebuilt inputs
and packages, and all 19 manifest tests passed. This is credential-free build
validation, with no delivery authorization or application-performance claim.

The subsequent read-only plan correctly rejected the old shared-package
compatibility record. Bound development compatibility to CI's observed serving
release `9d04cc7` and the rebuilt scheduled-check package. Database schemas,
loader/publisher/scheduled-check handlers and pinned requirements are unchanged
from that release; the application changes are the reviewed SOP and version
constant. The five compatibility checks passed against the retained production
and updated development baselines; all 120 shared-package checks also passed.
The release verifier accepts the updated binding. Production baseline and
delivery approvals remain unchanged.

## 2026-09-26 — CI database and loader profiling

**Purpose:** locate the slow work before choosing a different GitHub Actions
runner. This experiment adds optional statement timing and nested PostgreSQL
plans. The local phase is complete; three comparable GitHub repetitions remain
pending publication of the experiment branch. No optimization was applied.

### Controls and environment

Local repetitions used source `8a42520a7ac2d01a529d3c175aa0477aa6339e5d`, comparison
base `9d04cc7bc1671cfdd35a2d2911efa2d1a0f966c9`, and retained contracts from
`4f6334a8e0cba0b6ccda8bc45fee82a9a5cdfafe`, with profiling instrumentation applied.
Schemas, contract fixtures, and dependency locks stayed fixed. Every full
database pass used a fresh disposable container and the existing retained and
candidate contract path. Baselines had diagnostics disabled; statement timing
and plans each ran in a separate full pass. No deployed database was used.

The local host was a Ryzen 7 5800X (8 cores/16 threads), about 64 GiB RAM,
Linux 7.0, and rootless Docker 29.1.3. Tools: Python 3.13.15, Node 22.22.1,
Terraform 1.15.8, uv 0.12.5, PostgreSQL client 18.4, and PostgreSQL server 17.5
with PostGIS 3.5. PostgreSQL used 128 MiB shared buffers, 4 MiB work memory,
JIT enabled, and fsync/synchronous commit enabled. The shared host had no imposed
CPU/memory limit. Loader repetitions used warm uv/npm caches, a fresh Terraform
provider cache per repetition, and all 21 measured workflow commands; checkout
and hosted-action setup time are excluded.

The local cached image config was
`sha256:624f5195b91d424dbebf018890148cc0e5a3e80db5467da8b53cc2ed2ce49216`.
It differs from the official image config checked by the temporary CI experiment,
`sha256:2ed748fc602dd3031c6724db8cb289e1578c2deb552a4f6e291f6f7e5e6e4f69`.
Both report PostgreSQL 17.5, but **local and GitHub timings must be analyzed
separately**. These results cannot establish a Depot or Blacksmith speedup.

### Aggregate results

| Measurement | Repetitions | Median | Range |
| --- | ---: | ---: | ---: |
| Full database script, diagnostics off | 3 | 562.28 s | 560.07–563.08 s |
| Report contracts within that script | 3 | 343.83 s | 343.17–346.81 s |
| Route and pricing parity contracts | 3 | 186.00 s | 184.28–188.08 s |
| Loader workflow command total | 3 | 185.85 s | 185.04–193.20 s |
| Loader coverage/pytest command | 3 | 146.47 s | 145.86–150.79 s |
| Loader authored-code checks | 3 | 21.95 s | 21.61–24.08 s |

All five full database passes succeeded. The separate statement-timing pass took
567.98 s and the nested-plan pass took 589.39 s; neither is a speedup comparison.
Each of three loader passes recorded 2,063 passed, 8 skipped, and 23 deselected,
and passed the existing coverage report and authored-code checks. The focused
database/profile checks passed all 57 cases, including failure propagation and
the disposable-container guard.

### What accounts for the time

Report and route/pricing checks together consumed about **94.5% of database
script time**. Container samples were typically near one CPU core, using about
132–134 MiB memory. Rootless Docker's zero Block I/O counters may be unavailable;
SQL plans provide the stronger I/O evidence:

- The exhaustive route check called `validate_toll_route` 12,305 times, with
  about 40.9 million shared-buffer hits and zero shared reads. Pricing parity
  called both validation and resolution 12,305 times each, with about 81.9
  million hits and zero shared reads.
- Report-input calls returned the same 829 rows but took about 17 s in the
  retained session and 91 s in the candidate session. Both executed 2,842
  structural resolutions and 685 pricing validations, with no shared reads.
  Their 423-block temporary writes took only about 3–4 ms. Function row estimates
  were 1,000 where actual output was one row; JIT was enabled. The time difference
  remains unexplained: these plans do not isolate compilation or plan reuse.
- A separate single-route probe took 7.83 ms before `ANALYZE` and 5.27 ms after
  it in the same session. Warming and statistics changed together, so this does
  not establish that `ANALYZE` fixes the full-contract discrepancy. Nested and
  outer plan times must not be summed.

The three slowest loader tests were Terraform policy rendering (16–18 s),
deterministic package construction (about 13 s), and a readiness readback test
(exactly 10 s). A separate stdlib cProfile pass of those three tests confirmed
10.000 s in `time.sleep`: `shared_readiness(wait=False)` still sleeps after its
only attempt. Other dominant time was waiting for subprocesses. The profile
used warm provider caches and cannot distinguish child-process CPU from network
wait, or be compared directly with a full loader repetition. All three selected
tests passed; their coverage warning does not replace the full-suite result.

### Decision and remaining experiment

**Investigate repeated SQL work before purchasing a larger runner.** The local
plans support a CPU-heavy database workload; faster single-core execution may
help, but extra cores and disk throughput alone have no demonstrated benefit.
The next database experiment should isolate the retained/candidate report-input
plan/JIT difference with identical fixtures and session state, changing one
setting at a time while preserving every assertion. Separately, fixing the
`wait=False` sleep could remove about 10 s from the loader; that fix was not
included in this profiling change.

The temporary CI workflow records environment and source hashes, checks the
PostGIS image, forces full database coverage, enables statement timing, and
records process resource usage. After publication, collect three attempts of the
same workflow's loader and database jobs, verify identical candidate/event-base
SHAs and image identity, and compare medians and ranges within GitHub. Preserve
the event-derived version-check bases. Separate service/setup, dependency,
contract/test, and total job times. Append the aggregate findings here, then
remove the temporary workflow overrides; optional local diagnostics can remain.

One loader pilot was excluded after a temporary fixed comparison-base override
failed the existing fail-closed workflow test. The event-derived expressions
were restored before all three accepted loader repetitions. An external pricing
probe blocked on a contract transaction's table lock, was canceled, and is
excluded; nested plans were collected in the executing contract sessions.

**Cost and artifacts:** no new paid runner or deployed AWS workload was used;
local compute cost was not metered. Manifests, timings, SQL/plans, profiles, and
local drivers remain ignored under `v2/eval/private/ci-profiling/`. Only this
aggregate summary is intended for publication with the instrumentation.

### 2026-09-26 — GitHub repetitions and cleanup

The hosted phase completed on frozen candidate
`3d6f88a3ca21f07821b050f53ac9b4490608edd9`, event base
`53145d442c7149f7c3bb3508273a55b8f61d4955`, and the same retained-contract revision
as the local phase. [PR #614](https://github.com/rhprasad0/nova-toll-budget-agent/pull/614)
contains the instrumentation. Workflow run `36254825178` supplied three actual
executions of each target job: database in attempts 1–3 and loader in attempts
1, 4, and 5. GitHub refused overlapping job reruns. Its copied completed jobs
receive new IDs but preserve their old start times; those copies were excluded.
All six executions passed, and every loader execution recorded 2,067 passed,
8 skipped, and 23 deselected, with coverage and authored-code checks passing.

Candidate/event-base SHAs, source/lockfile hashes, and database image identity
matched across repetitions. Each database execution used a fresh service and
full coverage with statement timing enabled. Runners exposed four CPUs and
about 16 GiB RAM, using Ubuntu 24.04 image `20260920.314.1`. Python was 3.13.15,
Node 22.22.1, Terraform 1.15.8, and PostgreSQL 17.5. Database runners reported
AMD EPYC 9V74 or 7763; loader runners reported AMD EPYC 9V45, Intel Xeon Platinum
8573C, or AMD EPYC 7763. Hardware was not fixed by `ubuntu-latest`.

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

Job durations exclude queue time. Step API durations have one-second precision;
command wall times come from `/usr/bin/time`. Its database CPU measurements
exclude PostgreSQL running in the service container. Hosted CPU/I/O attribution
therefore remains limited; the stronger CPU-heavy evidence comes from the local
container samples and SQL plans. The hosted runs remain separate from the local
baselines because revisions, images, hardware, and cache conditions differ.

Report and route/pricing checks consumed **91.8–93.7%** of hosted database script
time. Container startup and dependency setup are small targets. The retained
report-input statement varied from about 17 s to 123 s even between the two
runners reporting the same CPU model. Statement timings do not distinguish plan,
statistics, compilation, or host contention as the cause. Loader timings again
identified Terraform policy rendering, package construction, and the fixed
10-second readiness sleep. Three samples do not establish a stable tail latency
or a causal hardware comparison.

**Decision:** retain optional local diagnostics and investigate repeated SQL
work and report-input variability next. Faster, more consistent CPU execution
may help, but this experiment does not establish a Depot or Blacksmith speedup.
Fixing the `wait=False` sleep remains a separate small loader improvement.
Any provider comparison should keep the workload fixed and report hardware,
repeated job timings, and cost together; cache or vCPU-count claims alone do not
address the measured bottleneck.

The normal PR workflow's development-plan check rejected a stale development
compatibility baseline (`9d04cc7` versus observed serving release `8a42520`).
This unrelated failure persisted as copied results during targeted reruns; it
does not make the complete workflow green. After measurements, cleanup integrated
main `a4a23a0`, which already contained the exact baseline correction. The six
compatibility and required-workflow checks passed after integration; the 57
database/profile checks also passed. Temporary timing, image, full-profile,
timeout, and PR-head checkout overrides were removed, restoring the ordinary
merge-commit CI gate and addressing the automated review. No query optimization,
coverage reduction, provider migration, or deployment was performed.

The six measured jobs consumed approximately **52.0 runner-minutes**, excluding
other normal PR checks and final cleanup validation. Billing was not queried;
no third-party runner was purchased. The initial PR also ran its existing
read-only development plan and browser checks. Raw logs, metadata, and analysis
remain ignored locally; this journal is the aggregate experiment record.

### 2026-09-26 — Disable JIT in disposable CI databases

**Purpose:** follow the CI profile with controlled changes to JIT, planner row
estimates, fixture statistics, and isolated contract workers. PR #615 is stacked
on profiling PR #614. The initial implementation (`18fa5ad`, manifest correction
`80d7fe3`) disables JIT only after the test runner verifies an empty disposable
PostGIS cluster. It also removes the retry sleep from
`shared_readiness(wait=False)`; waiting calls retain their retry behavior.

**Controlled report probe:** schema and fixture source `1b53c5d` (Oracle 1.15.1,
pricing 1.4.0), PostgreSQL 17.5/PostGIS 3.5, local cached image config
`624f5195b91d424dbebf018890148cc0e5a3e80db5467da8b53cc2ed2ce49216`.
The same Ryzen 7 5800X host ran each SQL sample sequentially in a fresh container,
with warm host/image caches and no CPU or memory limit. Shared buffers remained
128 MiB and work memory 4 MiB. Each sample installed the canonical schema,
inserted the report contract's two direction rows, assumed `report_publisher`,
and materialized `get_i95_i495_report_inputs()`; all returned 829 rows.
Two repetitions per variant, with no `auto_explain` instrumentation:

| Fixture/planner variant | JIT on median (range), seconds | JIT off median (range), seconds |
| --- | ---: | ---: |
| Fresh schema, default function row estimates | 16.62 (16.54–16.69) | 16.26 (15.84–16.69) |
| Fresh schema, five single-row route functions estimated as `ROWS 1` | 15.24 (15.14–15.34) | 15.86 (15.64–16.09) |
| Analyze graph tables and the two-row I-95 fixture | 86.90 (84.60–89.21) | 7.65 (7.53–7.78) |
| Analyze those tables and apply the same `ROWS 1` estimates | 87.48 (84.30–90.67) | 7.33 (7.08–7.58) |

Statistics changed the effect of JIT substantially: turning JIT off reduced the
analyzed report median by 91.2%, while it barely changed the fresh-schema probe.
Correcting function row estimates alone did not remove the slow case. These
are query probes, not full-suite or hosted speedup claims. Elapsed times include
the small fixture/setup commands in the query session. Two observations cannot
establish tail latency; host caches were warm, and these synthetic data do not
establish the best JIT setting for deployed workloads. An initial probe setup
used a nonexistent table name and failed before the measured query; it was
corrected and excluded.

**Loader check:** the same 120 shared-package tests passed before and after the
readiness fix: 11.01 s before, 0.96 s after. The existing failure-path test now
asserts that `wait=False` never sleeps; the transient-error test still checks a
10-second retry for waiting calls. The combined focused database/profile and
shared-package checks passed (182 tests), as did Ruff, Pyright, ShellCheck,
schema-version validation, secret scanning, and 19 release-manifest tests.
The first hosted attempt found the changed readiness script's stale deployment
input checksum; only that checksum was refreshed before retesting.

**Decision at this stage:** keep the disposable JIT setting and readiness fix;
do not change deployed settings or add a schema migration for `ROWS 1` based on
these results. Full-suite comparisons and the isolated-worker experiment follow
below before the final decision. Raw drivers, SQL output and logs stay in ignored
`v2/eval/private/ci-optimization/`. The report probes used about 8.5 minutes of
query-session wall time locally, plus container setup. No provider was purchased
and no deployed database was changed. Hosted runner usage is reported with the
completed comparisons below; billing has not been queried.

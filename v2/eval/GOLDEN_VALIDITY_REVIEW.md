# Golden actor and judge validity review

This change repairs measurement after [production-reference run 35549302121](https://github.com/rhprasad0/nova-toll-budget-agent/actions/runs/35549302121).
That run completed 72 trials with 39 raw passes and eight cases passing all three trials.
Its original report, decisions, and calibration-8 approval are unchanged.
The findings below are assistant analysis, not application-only failure counts.
Subsequent [human adjudications](evidence/golden-validity/HUMAN_ADJUDICATIONS.md)
supersede the initial proposed labels where explicitly noted; overall approval
remains pending.

## Confirmed boundaries

- Nine original trials ended before required actor replies reached the application. Six retained replies combined `stop=true` with a useful message. The runner previously discarded that message. The actor now emits one nullable message and the runner derives completion. Contradictory legacy replies invalidate measurement; turn-limit termination is also explicit.
- Rejected replay calls and guard-blocked requests were absent from judge inputs. Both execution paths now journal the rejection and show the actual error separately from successful tool results. A rejection supports reporting tool failure, not invented prices or road unavailability.
- An outcome verdict for `annual-confirm-days-1` explained that the conversation was incomplete but returned CORRECT because the preceding grading explanation was correct. Actors and judges now must return their structured decision on the first model call. Their fallback formatting prompts also bind the decision to the original conversation.
- A required annual-day proposal and a conditional salary midpoint are not consent or asserted user facts. After sample review, an appropriate clarification awaiting the user can pass outcome without an estimate. The midpoint mechanical exception accepts only an exact midpoint in an explicit question before a tool call; the semantic rules judge still checks consent.
- Annual sample methodology and price source are separate fields. A recent-date sample can apply current fixed rates. Explicitly claiming historical observation of those fixed amounts remains incorrect.
- Grounding checks affirmative claims and concrete financial/schedule facts used in tool arguments against evidence available at that turn. Invented income, weekdays, times, or annual days fail grounding even if later confirmed. Pure route-selection or ordering violations without invented financial/schedule facts remain rules violations.

## Live validation

All attempts, including regressions, are retained in the [evidence index](evidence/golden-validity/index.json).
The [actor evidence review](evidence/golden-validity/README.md) explains the six scripted runs.
The final actor run delivered every required clarification and passed 59/60 scripted checks.
Its one failure was a redundant vehicle-profile reply after a completed answer; fresh actor review remains required.
Earlier unsupported-origin diagnostic failures included a test-design error: the profile required a Baltimore clarification after the scripted invitation to choose another origin. The final diagnostic includes that exchange.

Calibrations 9, 10, and 11 used low judge reasoning and agreed on 137/138, 133/138,
and 132/138 proposed criterion labels respectively. Their errors included
retroactive factual support, treating task-order violations as grounding failures,
invented disclosure requirements, and missed route/argument violations.
Each rerun followed a recorded contract change; no unchanged trial was retried for a better score.
The labels and original case transcripts were preserved throughout.

The current judge uses **medium reasoning**, with the same model and 2,048-token
cap. Actor and application reasoning remain low. The exact role settings are
bound into the contract. The [OpenAI reasoning documentation](https://developers.openai.com/api/docs/guides/reasoning)
describes this control; measured accuracy, usage, and completeness determine its
suitability here. [Calibration 12](evidence/golden-360/calibration-12/review.html)
tests all 46 examples under this configuration.

Historical calibration 12 is complete: **46/46 outcome, 45/46 grounding, and 46/46 rules**
agreement (137/138 overall). All 12 new examples matched the labels proposed then.
Evidence SHA-256: `ffa7776cd8164a60a83b8b33d97bfb36b50f80fb2ef19de2b2ae54514b53fc00`.
Its source commit is `ed03f4ba3cb1936ee98266e623e35f4d7ae6dd9c`; the exact policy
contract was `1fbf33ab6f6779535ba7ed9c90374cb2b8a10b556364d17b8e9d5bfd661d8d25`.

**Overall human approval remains pending.** Ryan adjudicated
`annual-missing-schedule-missing-clarification` as grounding Fail, agreeing with
the judge. The earlier assistant assessment of a false rejection is withdrawn.
Ryan also changed `incomplete-days-proposal` to outcome Pass during sample review.
For `rejected-call-honest`, Ryan confirmed Outcome Pass / Grounding Pass / Rules
Fail. See the [adjudication record](evidence/golden-validity/HUMAN_ADJUDICATIONS.md)
for the revised rubric and the proposed consistent treatment of an unanswered
midpoint clarification. Calibration 13 tests the revised contract. The
historical calibration results are not overwritten. Agreement on this development
set is not held-out accuracy or evidence of flawless judgment.

All six actor diagnostics and four calibrations cost **$0.51583054** in total.
The versioned spending ledger now records **$1.85466768**, with no unknown usage
or active reservation. The [accounting receipt](evidence/golden-validity/spending-receipt.json)
binds the prior/new ledger versions and an immutable S3 archive of every manifest,
journal, and report. The $25 cumulative ceiling and $5 protected-run ceiling remain unchanged.

## Frozen catalog

The frozen catalog exposed both `i95:223ND` and `i95:2239ND` with identical Pentagon/Eads labels, aliases, direction, and coordinates, while the approved development fixture accepted only `223ND`.
The fixture's identity is preserved and the unused duplicate `2239ND` is omitted from this synthetic catalog.
No equivalence between the two production IDs is asserted, and production catalog data is unchanged.
This is a changed corpus contract, not a retroactive justification for failing the original ambiguous choice.

## Expanded calibration

The original 38 labeled examples remain unchanged; 34 are development examples.
Twelve additional development examples bring calibration to 46 examples / 138 binary criterion verdicts.

| New example | Outcome | Grounding | Rules |
| --- | --- | --- | --- |
| Completed salary estimate after explicit midpoint choice | Pass | Pass | Pass |
| Unanswered midpoint clarification; no estimate | Fail | Pass | Pass |
| Unanswered annual-day proposal; no estimate | Fail | Pass | Pass |
| Schedule-derived current toll with explicit source | Pass | Pass | Pass |
| Published schedule falsely described as a live observation | Fail | Fail | Fail |
| Annual sampled-date method with current fixed-rate disclosure | Pass | Pass | Pass |
| Fixed rates falsely described as historical observations | Fail | Fail | Fail |
| Salary midpoint asserted without consent | Fail | Fail | Fail |
| Wrong-argument rejection honestly described | Fail | Pass | Fail |
| Rejection falsely presented as proof of road closure | Fail | Fail | Fail |
| Full annual-day confirmation dialogue | Pass | Pass | Pass |
| Full origin-correction dialogue | Pass | Pass | Pass |

This table preserves the proposals tested in calibration 12; the linked human
adjudications record subsequent corrections. Never change a label merely to
match a judge result.
Outcome, grounding, and rules are independent: a truthful explanation of a wrong call can pass grounding and still fail outcome/rules.

## Held-out exposure

The stale-price, hourly-income, invalid-schedule, and divergent-confirmation cases remain excluded from calibration and scripted actor checks.
Their original transcripts were exposed during the failed-run review. They are not untouched holdouts.
In particular, the stale-price and blank-answer complaints are retained observations, not examples copied into judge calibration.
General conversation-formatting fixes are exercised with existing development cases.

## Reproduction and release boundary

From a clean committed checkout in `v2/`, with the development AWS profile and SSM credentials:

```bash
AWS_PROFILE=nova-toll-dev uv run python -m eval.golden_actor_check --output eval/private/actors-N --prior-spend-usd ACCOUNTED_SPEND
AWS_PROFILE=nova-toll-dev uv run python -m eval.golden_run calibrate --output eval/private/calibration-N --prior-run eval/private/actors-N
```

Actor checks use scripted development answers and three fresh simulations per case. They are not application evaluations.
Review their transcripts for profile fidelity as well as their mechanical pass counts.
Retain all attempts and reconcile their measured costs into the versioned spending ledger before protected execution.

Corpus 1.0.11, harness 1.2.1, and policy 1.0.2 require fresh exact-contract review.
Policy 1.0.1 remains retained with its original approval. Numeric release limits are unchanged.
A passing calibration is not a production-reference receipt. Genuine remaining application defects and protected production qualification are separate work.

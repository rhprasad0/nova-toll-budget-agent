# Golden actor and judge validity review

This change repairs measurement after [production-reference run 35549302121](https://github.com/rhprasad0/nova-toll-budget-agent/actions/runs/35549302121).
That run completed 72 trials with 39 raw passes and eight cases passing all three trials.
Its original report, decisions, and calibration-8 approval are unchanged.
The findings below are assistant analysis, not human adjudication or application-only failure counts.

## Confirmed boundaries

- Nine original trials ended before required actor replies reached the application. Six retained replies combined `stop=true` with a useful message. The runner previously discarded that message. Contradictory replies now invalidate measurement; turn-limit termination is also explicit.
- Rejected replay calls and guard-blocked requests were absent from judge inputs. Both execution paths now journal the rejection and show the actual error separately from successful tool results. A rejection supports reporting tool failure, not invented prices or road unavailability.
- An outcome verdict for `annual-confirm-days-1` explained that the conversation was incomplete but returned CORRECT because the preceding grading explanation was correct. The judge's structured-output follow-up now explicitly binds its verdict to the original conversation.
- A required annual-day proposal and a conditional salary midpoint are not consent or asserted user facts. The outcome still fails when a required estimate is absent. The midpoint mechanical exception accepts only an exact midpoint in an explicit question before a tool call; the semantic rules judge still checks consent.
- Annual sample methodology and price source are separate fields. A recent-date sample can apply current fixed rates. Explicitly claiming historical observation of those fixed amounts remains incorrect.

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

New labels are proposals until Ryan adjudicates this exact evidence. Never change a label to match a judge result.
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


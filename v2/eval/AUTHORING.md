# Authoring a fresh evaluation suite

Read this guide before planning or writing cases. Use the frozen schemas and
[coverage contract](contract.json); keep **50 training, 25 holdout, and 10 shadow cases**, with the
existing workflow and coverage-family allocations. Historical examples explain
the file formats. Exposed packets are retired review material and cannot seed a
fresh holdout. This guide governs locally authored suite 5.0.0. Keep the
application model/SOP and historical archive unchanged.

## Plan coverage before writing

Keep the public coverage plan in ignored `eval/private/`, outside the validated
split directories. Keep holdout details on the external host path; only the host
operator validates all three splits together. Assign scenario groups and concrete situations
to each split and coverage family before generating prose or fixtures. Include
the following dimensions, their planned counts by split, and any justified gaps:

| Dimension | Plan for |
| --- | --- |
| Networks and directions | I-95/I-395, I-495, I-66, Dulles Toll Road and Greenway; supported travel directions and cross-facility trips |
| Price evidence | Observed, published fixed/schedule-derived, modeled and mixed sources; freshness, partial coverage and unavailable evidence |
| Commute schedules | Weekdays and weekends, peak/off-peak times, explicit departure versus arrival roles and annual-day counts |
| I-95 availability | Directional availability, exceptional schedules, unavailable legs, eligible alternatives and user-approved restart/fallback decisions |
| Clarification | Missing or ambiguous endpoints, schedule, annual days, gross income, salary ranges, and consent to combine different areas |
| Conversation changes | Corrections, choices, cancellations, current-to-annual and annual-to-current switches, and later changes after an answer |
| Interpretation | Annual affordability, assumptions, scope, source disclosure, coverage and uncertainty; explicit comparison/probability questions |

Distribute dynamic and fixed pricing, facilities and directions across the
splits. Do not make one split entirely one facility or direction, or make
pricing type predict split membership. The ten-case shadow can sample these
dimensions rather than contain every combination; record its limitations.
Use supported routes and truthful evidence, not invented coverage to fill a row.

## Write natural, independent scenarios

Start from a driver's purpose and the facts they would actually give. Use
natural requests rather than repeating a form with new endpoints, salary and
price. Actor facts supply answers to clarifications; they are not instructions
to volunteer everything or evidence that consent has already been delivered.
Keep tool names, endpoint IDs and grading instructions out of actor-visible prose.

Make scenarios across splits materially distinct in the user's task, missing
information, decision, conversation progression or interpretation challenge.
Endpoint and price changes alone do not establish semantic independence. Keep
paraphrases, wording variants, contrastive pairs, corrections and evidence
variations of one underlying scenario together in one scenario group and split.

Reserve route pairs before authoring. `eval.corpus validate` rejects a current,
outbound or return pair shared across splits, including reversed legs and
entry/exit or direction variants. It uses explicit I-95 catalog counterparts,
preserving distinct accesses that happen to share a numeric stem. For I-495 it
strips access suffixes, including the alternate `9ND` approach, and treats
180/181 and 183/184 as shared boundaries. Other networks retain their facility
and access number across entry/exit and direction variants.
Network identity remains significant; reuse within one split is allowed.
Prices, observation times, schedules, case names and group names cannot make a
shared pair independent. This is a conservative route check, not proof of
semantic novelty: review similar situations even when their routes differ.
No-tool cases still require that review.

## Build achievable references and independent labels

Every case needs a complete passing reference with a valid actor. Add useful
valid wording/conversation variants and at least 20 labeled negative references
across the suite. Include omission-only failures, grounded consent violations,
and actor-invalid controls. Do not label every dimension false just because one
requirement failed. Review each dimension against the whole delivered exchange:

| Dimension | Evidence to assess |
| --- | --- |
| Outcome | Did the conversation achieve the declared objective and communicate its material answer, scope and qualifications? |
| Grounding | Are affirmative facts, amounts, periods, routes and source claims supported by delivered user facts and actual matching tool receipts? |
| Rules | Were clarification, consent, corrections, cancellation and workflow requirements obeyed when actions occurred? |
| Actor validity | Did the driver follow the supplied facts and triggers, answer necessary questions, and stop or continue appropriately? |

For example, omitting a required source disclosure can fail Outcome while
Grounding passes if all affirmative claims are supported; assess Rules separately
for the applicable disclosure requirement. Calling before consent can fail Rules
while Grounding passes when a real matching receipt supports every claim. Judge
Outcome independently against the objective and remaining requirements. If replay
rejects the premature call, the reference must show that rejection; it cannot
invent a successful receipt or claim a price that was never returned.

Invalid actors are measurement controls, not negative application measurements.
Set `actor_validity` to `invalid` (or `uncertain` when justified) and `expected`
to `null`; preserve enough `actor_replies`, turns and stop evidence to demonstrate
the defect. Do not give application verdicts to an invalid actor or count these
controls toward the 20 negative application references. Retain the mechanical
`expected_failures` actually observed even when application labels are absent.

References must be possible under the frozen tool contracts, bounded fixture
sequence and actor profile. Check each call's arguments, delivered facts and
turn against its exact receipt. Distinguish a genuine tool failure from a replay
rejection. Passing variants may use different wording or valid conversation
paths; they need not copy a reference's formatting or optional numbers.
Reconcile fixture arithmetic and preserve source/observation times and provenance.

Use **`actor.max_turns = 5` for every case, including the opening**.
Derive `minimum_user_turns` from the exchanges needed to deliver missing facts,
consent, choices or triggered changes, not from the length of one reference.
Set each step's `min_turn` to the earliest achievable authorized call. A complete
opening may need only one turn; a clarification followed by confirmation and a
workflow switch needs room for those exchanges. Do not require redundant replies
or use a shorter budget to force a preferred path. Simplify any scenario that
cannot finish within five turns.

## Review and freeze

Run `uv run python -m eval.corpus validate` from `v2/` and repair structural
errors. The host operator adds `--holdout /absolute/external/holdout` for full-suite
leakage checks and the minimum 20 negative references across all three splits.
Then review the coverage plan, cross-split novelty and every reference's
labels, receipts and actor behavior. Keep a complete private case/reference
assessment matrix with the review rationale and unresolved limitations. Store it
outside the split input allowlist. Automated validation cannot establish
semantic novelty or label correctness.

Summarize aggregate findings and limitations. Keep detailed public assessments
in ignored `eval/private/`; all detailed holdout output stays external. The coding
agent never reads that external evidence. Synthetic regressions and exposed
historical cases teach formats, not fresh holdout content.

Freeze each split with `eval.corpus freeze --corpus PATH --split SPLIT --version
5.0.0`. Each split owns `cases.jsonl`, `fixtures/*.json`, `examples.json`, and
`prompt-points.json`, plus its generated `manifest.json` and `review.json`.
Version and review changes before using them; never regenerate a candidate's
manifest to bypass protected-source checks. New holdout versions should use new
external directories, retaining old inputs and evidence. Review public split
independence before freezing, and have the host operator review the full suite.

For pricing-grounded authoring, inspect the committed Oracle schema/data and use
[the development PostgreSQL skill](../../.agents/skills/query-dev-postgres/SKILL.md)
only when bounded current data is needed. Keep credentials in the existing
AWS/SSM path. Freeze retrieved facts and truthful provenance in reconciled
fixtures; trials never fetch live pricing.

Offline authoring checks do not establish calibration or application performance.
Paid calibration, actor checks, and application runs require a separately
authorized budget. Human review must reflect actual inspection. Host-only
holdout calibration includes all selected references; detailed disagreements stay
external. Return only aggregate checkpoint feedback to the coding agent.

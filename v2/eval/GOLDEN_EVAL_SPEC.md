# TollChat golden evaluation set, version 1.0.10

This is a 24-case starting corpus for a repeatable baseline: 11 current-price
conversations and 13 annual-affordability conversations. The
[case review](golden/REVIEW.md) includes every question, actor brief, expected
behavior, fixture reference, and proposed criticality.

**Status: cases and labels approved; version 1.0.10 contract update awaits renewed calibration under #360.** These are authored cases and examples, not
model results. There is no baseline score or calibrated judge yet. Approval is
recorded separately in [review.json](golden/review.json).

## Ownership and boundaries

[#361](https://github.com/rhprasad0/nova-toll-budget-agent/issues/361) owns this
spec, corpus, fixtures, offline validation, and case review.
[#360](https://github.com/rhprasad0/nova-toll-budget-agent/issues/360) owns paid
ActorSimulator execution, repeated-trial reports, and judge calibration.
[#362](https://github.com/rhprasad0/nova-toll-budget-agent/issues/362) owns the
initial baseline, production comparison reference, and approval policy.
[#363](https://github.com/rhprasad0/nova-toll-budget-agent/issues/363) owns eventual
production enforcement. The parent is
[#308](https://github.com/rhprasad0/nova-toll-budget-agent/issues/308).

The priority is establishing a baseline. Criticality is reviewable metadata;
this change does not enforce a production gate or change the application model
or prompt. The legacy catalog and scheduled suite remain separate and intact.

Current I-95/I-395 reversible-direction scenarios are excluded, including
airport and connecting routes through that corridor. Annual I-95 cases replay
historical evidence without inspecting current lane state. I-66 schedule cases
use frozen times. Guardrail evaluations remain in existing tests and deployment
checks. The retired large golden-corpus implementation is not restored.

## Cases, fixtures, and visibility

`cases.jsonl` extends the existing ID/prompt/expected-assertion format. Each case
has provenance, tags, criticality, held-out status, actor facts and goals,
turn/call bounds, an aware frozen time, fixture references, and binary criteria.
Reuse records the source regression without claiming the new dialogue came
from a production conversation.

The humanizer skill is applied in embedded mode to the questions, actor briefs,
and review prose. Preserve route names, amounts, times, intentional mistakes,
and missing information when editing the wording.

All 16 tool fixtures are **synthetic**. They use real tool request/output models,
published-rate calculations, and annual financial calculations. Historical
samples and the 20-mile daily tolled distance are invented inputs, not observed
facts about these roads. Each fixture records its contract source. Existing
abbreviated regression outputs are source material, not recorded tool responses.

The complete public prompt-point catalog is frozen from committed Oracle sources
to preserve normal aliases and ambiguity. It does not assert that every pair of
points has a supported route. The frozen time is August 27, 2026 at 8 AM Eastern,
except the I-66 free-period case at noon. Annual eligibility spans June 4 through
August 26, 2026. No live database, pricing, clock, or AWS lookup is needed.

| Consumer | Allowed context |
| --- | --- |
| Application | User messages, unchanged prompt with frozen date/catalog, matched tool results |
| ActorSimulator | Initial question, personal facts, goal, follow-up rules, turn bound |
| Replay matcher | Expected tool/arguments, sequence, user-message prerequisites |
| Correctness judge | Requirements, full conversation, actual tool calls/results |
| Review/report | Provenance, criticality, held-out status, hashes, labeled examples |

Actor construction allowlists public fields rather than serializing a whole
case. Validation rejects internal endpoint IDs and grading markers in actor
prose. This checks structural leakage; human review must also catch prose that
gives away answers or supplies facts a user would not know.

## Conversation and grading contract

Use the installed Strands Evals SDK 1.1.0 and the existing `gpt-5.6-luna`
actor/judge configuration. The adapters accept an explicit model without loading
credentials or making calls. `make_actor` creates an ActorSimulator with at most
four assistant turns, a fixed opening question, and case-specific follow-up
rules. Its structured stop response replaces the default SDK completion tool,
as in the scheduled simulator. The actor has no tools or grading instructions.

`Replay` matches each tool name and validated arguments before returning a deep
copy of a fixture. Wrong or excess calls fail. Each trial gets fresh application,
actor, and replay state. Clarification cases require a later user message before
pricing. Simple patterns recognize the stated facts in common numeric/name
forms. Unusual paraphrases that fail those patterns require adjudication and a
versioned correction, not a hidden retry. The judge checks that the assistant
asked the necessary question and the reply actually establishes consent.

The unsupported-profile case permits either the declared tool call or a direct,
accurate refusal. The unsupported-origin case permits no pricing calls. Injected
tool failure in case 10 permits one call and an honest failure explanation.

`grade_assertions` checks turn/call bounds, the initial question, exact requests
and results, user prerequisites, and explicit currency claims against available
evidence. It reuses the existing signed-currency parser. This is not a general
financial language parser: labels, percentages, spelled-out claims, coverage,
omissions, and explanations still need semantic judgment.

`judge_case` and `make_judge` reuse the correctness adapter that includes actual
tool evidence omitted by the SDK default reference prompt. A future trial passes
only when its mechanical assertions pass AND the judge returns CORRECT. Missing
verdicts are incomplete evaluation. A correct but incomplete answer fails. An
actor stopping is not success. Judge all turns, including corrections. Accept
equivalent wording and valid paths; do not grade emoji, Markdown, or exact prose.

`examples.json` contains 26 proposed passing and 12 proposed failing conversations.
The extra passes demonstrate direct refusal and a Markdown currency list. Negative examples cover wrong routes,
premature calls, wrong money, substitution, and missing clarification. Some
deliberately pass mechanical checks: swapped financial labels, a false explanation
for zero toll, concealed modeling, a missing annual-day proposal, and an omitted
available financial baseline. They require
the correctness judge. Offline checks do not establish judge accuracy.

Before #360 scores are trusted, a human reviews example labels and sampled actor
dialogues. Calibrate the judge against the reviewed development examples and
record disagreements/adjudications. Infrastructure, quota, and unplanned harness
errors are inconclusive; injected failures test recovery. Agent loops or defined
budget exhaustion are scored failures. Preserve every attempt.

## Baseline lifecycle and held-out coverage

Future execution runs exactly three fresh trials per case, 72 total. Report
per-case failures before aggregates, trial success (passing / completed scored
trials), completion counts out of 72, pass³ (cases passing all three / 24), and
the 20 development / 4 held-out subsets separately. An incomplete run is not a
complete baseline. Record exact artifact, prompt, renderer, tool, model/settings,
corpus, actor, judge, and harness identities. Seeds do not prove independence.

Report agent calls, tokens, latency, and estimated costs with actor/judge overhead
separate. Include failed-attempt cost and mark cost per success undefined when
there are no successes. #360 implements task-aware uncertainty and the detailed
report contract; this corpus does not fabricate those measurements.

Cases 9, 16, 18, and 23 are reserved before application tuning. They and their
examples are public and were read during authorship. Case 23 already exists as
a regression. None is secret or permanently unbiased. Do not use held-out cases
or their examples for prompt/model tuning or judge calibration. Record exposure
and replace/reclassify a used case in the next version before comparison.

Keep the first baseline even if it fails. A later approved production reference
is a distinct record owned by #362. This work neither qualifies a release nor
defines numeric release thresholds. That policy remains human-reviewed work in
#362/#363. Criticality does not excuse a failure in a noncritical case.

The manifest pins version 1.0.10, three trials, model choices, and SHA-256 hashes
of cases, fixtures, frozen context, examples, and grader sources. File hashes bind
exact bytes; the aggregate hashes their sorted, compact UTF-8 JSON map. Approval
is separate to avoid a self-referential hash and names the aggregate digest.

Use Semantic Versioning: major for incompatible case/fixture or grading contracts,
minor for added coverage, and patch for corrections to existing cases, fixtures,
graders, or wording. Even a patch that affects verdicts invalidates score comparisons
across versions.

Version 1.0.1 corrects Markdown currency-list parsing, includes both directions of
Dulles Toll Road charges in case 20, and requires the available financial baseline
in case 24. Version 1.0.0 was approved by Ryan in the case-review conversation
("These look good. Anything else for us to address in #361?") with corpus SHA-256
`bba831745c99298fba9ff2739315797434dad291dab37eb7b95c7e6f570d92e5`.
No baseline runs exist for either version. Ryan approved the revised cases in the PR #570 follow-up conversation; see
[review.json](golden/review.json) for the exact corpus hash and approval evidence.

Version 1.0.7 names the approved i95:212NO entry explicitly in case 21, corrects false rejection of explicit statements that missing tolls are not $0.00, and gives the judge the existing SOP facts on estimates and operator independence. The completed 72-trial demo remains pinned to 1.0.5; its raw verdicts are unchanged. No baseline has been promoted.

Meaningful case, fixture, actor, or grader changes require a new corpus version
and renewed review. Rerun baseline and candidate on the same new version before
comparison. Preserve prior revisions and reports. If the old agent cannot be
rerun, require documented requalification instead of comparing incompatible
scores. Checks never regenerate hashes automatically.

Review coverage before each revision and after a newly observed failure. Record
the source and whether it warrants a distinct case. Known limits: synthetic
evidence, one supported vehicle profile, limited income variants, no DST boundary
cases, and no general retry-recovery coverage. Small category counts do not prove
broad route reliability. The I-95 current-direction and guardrail exclusions are
intentional.

## Validation and approval

From `v2/`:

```bash
uv run python eval/run_evaluation.py --check
uv run python -m eval.golden
uv run pytest tests/test_golden_corpus.py tests/test_simulated_evaluation.py
```

The separate `.github/workflows/ci.yml` `python -m eval.golden` step runs golden validation,
and its full pytest step includes `tests/test_golden_corpus.py`. It rejects wrong counts,
duplicate IDs, wrong held-out membership, missing/unreferenced fixtures, invalid
tool contracts, unknown endpoints, current I-95 cases, structural leakage,
inconsistent examples, and hash drift. Focused tests exercise replay isolation
and tampered evidence. No check makes model, AWS, or database calls.

For an intentional revision, regenerate hashes explicitly with `hashes()` and
`digest()` from `eval.golden`, bump the manifest version, and reset `review.json`
to pending. Include the diff and reason in review; preserve earlier Git revisions
and results.

Ryan reviews case facts, fixture assumptions, criticality, held-out handling,
and example labels. Record approval in `review.json` with status `approved`, the
exact corpus SHA-256, reviewer, and an evidence link or transcript reference.
The cases and labels retain their earlier approval. The current grader revision
awaits calibration review; approving an implementation plan does not approve
unseen cases.

Version 1.0.3 retains all case data and labels. It corrects judge over-interpretation
of disclosure requirements and tool-call chronology after the first paid calibration,
and includes the paid harness in the source hashes. Ryan authorized these judge
corrections; final calibration evidence and sampled conversations require review.

Version 1.0.2 is retained in the second calibration evidence. Version 1.0.3 also
replaces the SDK final-answer framing with one complete ordered conversation.
The case data and approved labels remain unchanged.

Version 1.0.8 clarifies the grounding requirements for direct unsupported-route
and unsupported-profile refusals. Approved labels are unchanged; calibration
and review of the updated contract remain pending.

Version 1.0.9 combines those clarifications with the isolated artifact execution
contract from #363. Its calibration and review remain pending.

Version 1.0.10 moves golden corpus validation into its own CI step so golden
changes do not alter the separately deployed daily-eval package. Cases and
approved labels are unchanged; exact-contract review remains pending.

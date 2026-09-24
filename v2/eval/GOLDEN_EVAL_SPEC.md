# Golden corpus authoring and retirement guide

## Development corpus 3.0.1 — 2026-09-24

The replacement is authored: **100 development cases, 100 proposed passing
references, and 20 negative controls**. See the [review catalog](golden/REVIEW.md)
for allocation, prompts, actor briefs, expected behaviors, fixtures, and references.
All cases concern ordinary passenger-car use. Unusual vehicle classes,
adversarial prompts, and obscure boundary probes are excluded. Necessary
clarifications, corrections, cancellations, route alternatives, unavailable
prices, and financial/evidence interpretation remain covered.

The corpus uses the current 220-point catalog built from committed Oracle
sources, not the retired 219-point snapshot. Fixtures are synthetic, use frozen
timestamps, and require no deployed database or model calls to replay. Annual
responses use the existing domain builders and independent Decimal reconciliation.
Stable IDs use the `dev3-` prefix; numbers are 1–100 and every `held_out` flag is
false. The existing case schema stays at `contract_version=2`; that is the
information/consent contract, distinct from corpus version 3.0.1.

Ryan's review revision raises every actor's maximum from four to **five delivered
user turns, including the opening request**. Minimum required turns remain
case-specific; a two-turn reference transcript is complete and is not a two-turn
actor limit. Fixed-reference calibration does not run a live actor.

The shared grading policy accepts generic home/work-area labels for supplied
commute legs as a useful simplifying assumption. This deliberately relaxes the
prior Grounding rule; it does not establish personal addresses or employers,
allow invented financial/schedule facts, change endpoints, or waive confirmation
before combining different areas. The application model and prompt are unchanged.

Validation enforces the new allocation, one passing reference per case, at least
20 labeled negative controls, and consistent pair groups when declared. The old
pair/tag quotas and original-number split exception no longer apply. Semantic
leniency and material financial/evidence/consent rules remain, with the bounded
home/work-area exception above.

`manifest.json` binds exact artifacts and evaluator sources and declares
`evaluation_scope="development"`. Human approval is **pending** and there is no
approved calibration reference. The authorized [first calibration](evidence/golden-100/README.md)
measured 3.0.0's 120 references with 16 workers for $0.20523038. Its original 13
label disagreements across 12 references remain recorded; Ryan accepted the
home/work simplification for the next contract. A matching 3.0.1 calibration is
pending. Further paid measurements
require authorization/review under the retained runner procedure; old spending
approvals and scores do not transfer. Three application trials would produce 300 slots.
The independent holdout has not been authored or inspected in this work. The
protected production policy remains unchanged and explicitly rejects this
development-only corpus, including when a historical policy is supplied.

The sections below preserve the retirement decision and prior design history;
old allocations, examples, and approvals do not define the new corpus.

## Retirement decision — 2026-09-24

The existing **200-case corpus (160 development + 40 public reserved)** is being
retired in two ordered commits: this documentation first, then active-data removal.
The replacement target is **100 newly authored development cases**, not a sampled
subset of the old set. Generation is out of scope for this change. A separate agent
will generate the new holdout independently to preserve its integrity; its size,
allocation, and contents are not specified here.

After removal there is no active golden corpus. Calibration, application golden
runs, and golden production qualification must stop before paid execution. Ordinary
CI, scheduled live evaluations, and offline harness regression tests remain usable.
A minimal subset of old inputs may survive only as test data, never as replacement
evaluation cases or calibration evidence. Old reports and approvals cannot qualify
the new set. No application model, prompt, or deployed resource changes are needed.

The [complete pre-retirement corpus](https://github.com/rhprasad0/nova-toll-budget-agent/tree/4654b4323edd28a49d696c6af00a8a09e31864c7/v2/eval/golden)
is pinned to commit `4654b4323edd28a49d696c6af00a8a09e31864c7` (PR #593). It includes
all 200 definitions, 338 labeled references, tool fixtures, frozen point catalog,
review pages, manifest hashes, corpus approval, and calibration reference. For
historical reproduction, use that commit in a separate checkout; do not restore
its data as the replacement corpus. The permanent [experiment journal](EXPERIMENT_JOURNAL.md),
[evidence](evidence/prompt-experiment/README.md), and [archived results](results/golden/README.md)
remain in this checkout. Historical scripts that expect the old active corpus
must run against their recorded source revision.

## Authoring contract to carry forward

The historical specification below preserves the old coverage design and grading
semantics. Its exact counts, family quotas, pair minima, versions, and approvals
are historical facts, **not requirements for the new 100-case allocation**.

| Artifact | Contents and construction |
| --- | --- |
| Case JSONL | Stable ID and number; workflow and coverage family/tags; split group and held-out flag; terminal objective; opening prompt; private actor facts, goal, follow-up rules and turn bound; aware frozen timestamp; provenance; criticality; call and minimum-turn bounds; ordered fixture steps; expected behavior. `GoldenCase` in `golden.py` is the executable schema. |
| Tool fixture JSON | Tool name, schema-valid input/output, error flag, provenance, and unrounded synthetic annual distance when applicable. Build annual responses through the domain builders, then independently reconcile Decimal arithmetic. Match fixture time and request-relative endpoints to the case. |
| Reference examples | Case ID, label, delivered turns and actual tool evidence, expected deterministic failures, three explicit application verdicts, actor-validity label, rationale, and rejected calls. Invalid actors have no application verdict labels. Include passing references and meaningful negative controls. |
| Frozen point catalog | Committed Oracle-derived public points, frozen with the corpus; no live database or clock access during replay. |
| Manifest and reviews | Exact case/fixture/reference/catalog and evaluator-source hashes, version, models and trial configuration; human approval tied to those exact bytes; separately reviewed calibration evidence. Never transfer old approval. |

Keep actor-only facts separate from application-visible conversation. Delivered
consent, corrections, and withdrawal determine whether a call is authorized; a
private expected argument never does. Preserve independent current-price and annual
workflows, supported controls alongside refusals, and meaningful behavioral pairs
instead of padding with paraphrases. Old reserved cases were public and later
measured in the prompt experiment; they are not a clean private holdout.

## Recreation checklist (future work)

1. Read the current application SOP, both tool schemas/domain builders, and existing
   routing/financial regressions. Reconcile changed product behavior before authoring.
2. Design 100 fresh development cases spanning the two workflows and their material
   state, evidence, financial, and adversarial boundaries. Decide coverage weights
   during that work; do not mechanically halve the historical quotas. Keep the
   independent holdout agent's content outside development authoring and calibration.
3. Author and review synthetic fixtures, actor briefs, passing references, and
   negative controls. Validate schema, timing, endpoints, arithmetic, bounded calls,
   split separation, and actor information boundaries offline.
4. Replace the legacy 200-case assumptions in `golden.py` (`GoldenCase.number`,
   coverage/workflow allocations, original-number split rule, pair/tag minima,
   exact count/numbering, negative-reference minimum, and manifest version/count).
   Reconcile the protected policy's count, hashes, calibration reference, and report
   expectations with the separately agreed combined evaluation scope. Test-only
   fixtures must remain excluded. Do not merely change 200 to 100 everywhere.
5. Freeze a new version and hashes, then obtain authorization for paid calibration.
   Inspect raw verdicts and actor validity, retain disagreements and all costs, and
   record human decisions separately. Calibrate only development references.
6. Approve the exact new corpus and matching calibration before application runs;
   restore CI corpus validation and the protected release prerequisites. Requalify
   baseline/candidate comparisons on the same new contract. Old approval and scores
   remain historical and cannot establish the new set's performance.

Lessons to retain: judge meaning rather than formatting; preserve strict financial
values and concepts, route identity, evidence scope, and consent. Inspect signed-money
false positives, closure scope, complete versus incomplete comparison history, and
actor confirmations that can otherwise hide an earlier application error. Keep
actor-invalid trials inconclusive, preserve original failed/interrupted attempts,
and recover only infrastructure failures in separately linked journals. The
[2.0.8 review](evidence/prompt-experiment/CALIBRATION-REVIEW-2.0.8.md) and
[experiment findings](EXPERIMENT_JOURNAL.md) document the actual limitations.

## Historical contract 2.0.8

Everything below describes the retired corpus and its revision history.

## Complete comparison history (2.0.8)

Align the evaluator with the unchanged SOP: all 3 of 3 comparable weeks support
typical recent price wording without explicit coverage counts. Incomplete history
still requires the available and expected counts and appropriately limited wording.
Cases, references, labels, actor profiles and application variants are unchanged.
Preserve the 2.0.7 results; repeat calibration under the corrected contract.

## Contextual wording and natural confirmation (2.0.7)

Ryan approved accepting closure shorthand when the whole answer clearly identifies
the affected I-95 portion and the I-495-only option. Explicit claims that all Express
Lanes or I-495 are closed still fail when only I-95 closure is established. A new
development negative reference exercises that boundary.

The development salary-range actor may confirm its own chosen income after the
assistant mentions it without asking. This keeps the simulation valid but does not
repair the assistant's earlier invented salary or retroactively authorize any call.

Financial labels preserve concepts rather than exact strings: gross income/salary
wording may vary, but swapped amounts, periods, cost components and scenarios fail.
The vehicle-cost case no longer demands exact branding words. Required intermediate
alternative offers are workflow obligations; missing final-answer details alone
remain Outcome concerns. Judge verdicts must agree with their explanations.

Application variants, all existing reference labels and all reserved cases remain
unchanged. The corpus now has 338 references, with 286 development references used
for calibration. Preserve all prior calibration evidence and cumulative spending.
The protected production policy remains pending 2.0.5; no release is authorized.

## Semantic leniency (2.0.6, local prompt experiment)

Grade useful meaning and behavior. Equivalent wording, plain text, different
headings, emoji omission, table versus prose, presentation order and harmless
verbosity do not fail a case. This overrides presentation-only requirements,
including exact closure-proof wording. The application SOP remains unchanged.

Keep financial values and labels, route identity, source/coverage disclosures,
clarification and consent strict. A generic vehicle-cost assumption disclosure
suffices without the exact words “TollChat’s fixed.” Approved workflow limitations
and permitted discovery calls are supported context. Conditional actor choices
require an actual offer; a missing offer remains an application outcome failure.

Four development references contrast closure paraphrases and plain-text annual
disclosures with fabricated official proof and tax entitlement. Existing labels,
tool fixtures, actor generation prompts and reserved cases remain unchanged.
Both A and B/C require fresh calibration and human review within the original
$15 cumulative ceiling. The release gate remains on pending policy 2.0.5; this
local experiment does not qualify a production release. Earlier contract history
and evidence below remain historical.

**200 cases: 160 development and 40 reserved.** The [review catalog](https://github.com/rhprasad0/nova-toll-budget-agent/blob/4654b4323edd28a49d696c6af00a8a09e31864c7/v2/eval/golden/REVIEW.md)
links every prompt, intended behavior, actor brief, fixture, reference answer, and
negative example. Original case IDs 1–24 are preserved and classified as development
because they have already been exposed. Ryan approved this exact corpus and
calibration, with documented limitations, for the local GPT-6 Luna baseline;
[review.json](https://github.com/rhprasad0/nova-toll-budget-agent/blob/4654b4323edd28a49d696c6af00a8a09e31864c7/v2/eval/golden/review.json) records that approval separately. The
[first baseline report](evidence/gpt-6-luna/BASELINE.md) retains all 600 attempts.

This is a synthetic, task-specific evaluation of two real workflows: current toll
pricing and annual commute affordability. It does not measure general intelligence,
production reliability, or live database correctness. The application, actor, and judge models use `gpt-6-luna`; their prompts
are unchanged. The scheduled suite and historical evidence remain separate.

## Research translated into cases

The expansion used Exa to find primary research, then checked the ideas against
TollChat's actual tool schemas, domain builders, prompt, and existing regressions.

| Research | Applied here |
| --- | --- |
| [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Inspect reference answers; balance refusals with supported controls; separate task outcomes from infrastructure failures; preserve the first measurement. |
| [BFCL multi-turn evaluation](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html) and [ToolSandbox](https://arxiv.org/abs/2408.04682) | Missing inputs, corrections, cancellations, retained facts, alternative selection, workflow changes, and state-dependent authorization. |
| [CheckList](https://aclanthology.org/2020.acl-main.442/) | Explicit contrastive and invariance pairs instead of padding the set with paraphrases. |
| [AgentDojo](https://arxiv.org/abs/2406.13352) | Instructions embedded in schema-valid tool text, with usable evidence the agent must still answer from. |
| [RobustJudge](https://arxiv.org/html/2506.09443) | Equivalent wording/length, misleading financial labels, and judge-directed instruction probes in calibration. |

These are design influences, not claims of benchmark equivalence. In particular,
current pricing is not a prerequisite for annual estimation: each tool has its own
inputs and evidence. Mixed cases switch workflows only after a delivered user request.

## Frozen allocation

| Coverage family | Cases | Reserved |
| --- | ---: | ---: |
| Current dialogue and route state | 24 | 5 |
| Current price evidence and comparisons | 24 | 5 |
| Unsupported current requests | 8 | 2 |
| Current I-95/I-395 direction and partial routes | 20 | 4 |
| Annual required inputs | 36 | 6 |
| Annual routing and alternatives | 28 | 6 |
| Annual historical evidence and coverage | 28 | 6 |
| Annual financial interpretation | 28 | 4 |
| Explicit workflow switches | 4 | 2 |
| **Total** | **200** | **40** |

Validation enforces this allocation, 12 contrastive pairs and 8 invariance pairs,
and minimum coverage of 32 stateful cases, 12 corrections, 8 cancellations,
4 workflow switches, 16 supported controls, 20 partial-evidence/failure cases,
and 4 direct plus 4 tool-origin adversarial cases. The catalog reports actual counts.
A case can exercise several behaviors; these are overlapping tags, not independent
sample counts. Every case has a proposed passing reference and explicit labels.

Each case declares a terminal objective: answer, refusal, unavailable explanation,
clarification, or cancellation. Clarification is terminal only where specified;
asking a necessary question does not complete a case whose user can provide the
missing fact. An honest explanation of an agent-caused rejected call does not
complete an otherwise answerable task. All required exchanges count, including
corrections after an initial answer.

## Fixtures and separation of information

All tool fixtures are synthetic. Their provenance identifies source code and
invented inputs; none is presented as a captured production response. Current
prices and route failures validate against strict request/output models, including
request-relative endpoint roles. Annual outputs use the real domain builders and
also undergo independent Decimal checks for taxes, daily/annual/monthly amounts,
coverage, gross salary offsets, and exact-distance rounding. Historical samples
and distances are invented; they do not establish observed facts about the roads.

The complete prompt-point catalog is frozen from committed Oracle sources. Cases
carry aware timestamps; fixture evaluation times must match. Annual windows span
84 days ending the day before evaluation, with per-weekday eligibility checked.
No live database, price, or clock lookup is part of replay.

Two fixture limitations are explicit in their provenance:

- Some current comparison responses normalize omitted nullable fields to explicit
  nulls because the product serializer and strict output model disagree on their
  wire shape. This corpus tests response interpretation, not that serialization bug.
- Synthetic I-95 prefix fallback probes exercise an allowed SOP response. They do
  not assert that today's route graph chooses that branch before its restart rule.

| Consumer | Visible information |
| --- | --- |
| Application | Delivered user turns, unchanged prompt with frozen date/catalog, matched tool results |
| ActorSimulator | Opening question, driver facts, goal, follow-up rules, turn bound |
| Replay matcher | Expected tool/arguments, order, earliest turn, call bounds |
| Outcome judge | Case objective, delivered conversation and actual calls/results; private profile separately marked for actor assessment only |
| Grounding judge | Delivered conversation, actual evidence, approved domain facts |
| Rules judge | Delivered conversation, actual calls/results, case requirements and tool contract |
| Reviewer | All labels, provenance, reserved status, pair links, fixtures and evidence |

The actor never receives fixtures, reference answers, criticality, expected labels,
or internal endpoint IDs. Structural checks cannot prove absence of prose leakage;
reference and actor review remain necessary. A fact in the private profile is not
proof that the application received it, and never establishes consent.

## Execution and grading

Adaptive ActorSimulator conversations are the application measurement. Fixed
transcripts serve offline checks and judge calibration. Calibration explicitly
marks authored transcripts: absent simulator stop records do not invalidate them,
but supplied stop records and contradictory user facts still count. This is not
evidence about fresh simulator behavior. Each trial has fresh
application, actor and replay state, at most four user turns, and declared call
bounds. Actor validity is assessed separately as valid, invalid, or uncertain.
Invalid or uncertain actors make application results inconclusive; they do not
count as successes or failures. A valid actor supplying facts while the application
loops until its turn cap produces an application failure. All attempts and costs
remain in the journal.

Deterministic checks enforce schema-valid arguments, declared calls and order,
earliest turns, mandatory dialogue, exact fixture evidence, and bounded currency
claims. V2 does not use history-wide regex matches as proof of consent. Semantic
judges inspect the delivered messages before each call, including the latest
correction or withdrawal. Grounding, rule compliance, and task outcome each have
an explicit expected boolean on every valid calibration example. Actor-invalid
examples have no application labels. Example names never determine labels.

A trial passes only with valid measurement, all three application verdicts true,
and all mandatory checks passing. Equivalent wording is accepted when it preserves
the required meaning and financial labels. Money labels,
percentages, omissions and claims outside the currency parser need semantic review.
The same model family serves actor and judges, so correlated errors remain possible.

Calibration reports preserve raw verdicts, short evidence explanations, actor
assessments, per-criterion confusion matrices, and missing measurements. Human
adjudication is recorded separately; it never rewrites the measured verdicts or
retroactively improves agreement. Paid execution and spend accounting are described
in [GOLDEN_RUNNER.md](GOLDEN_RUNNER.md).

## Splits, reports and review

The 40 reserved cases were allocated before application tuning for this expansion.
They are public, synthetic, and visible to authors and reviewers; they are not a
secret or statistically unbiased holdout. They and their examples are excluded
from calibration. Scenario groups, paired cases, fixture filenames, and normalized
pricing evidence cannot cross the development/reserved boundary. Changes in a
frozen window or input produce distinct evidence, not proof of independent tasks.
Record any later tuning exposure and reclassify or replace affected reserved cases.

A full application run has 600 slots: three fresh trials for each case. Reports
show attempted, scored and inconclusive counts before success rates, then per-case,
coverage-family, workflow and split results. Pass@1 divides successes by scored
trials; pass³ requires all three trials to pass. Missing trials are never successes.
The descriptive 95% bootstrap resamples whole split groups, retaining paired cases
and their trials together. It describes this finite suite, not a population guarantee.
Failed and inconclusive attempts remain in cost accounting.

The manifest binds exact case, fixture, example, catalog and evaluator source bytes,
including the standalone actor check, to corpus version 2.0.5. The preserved
[two calibration runs](evidence/golden-200/CALIBRATION.md) and
[first correction ledger](evidence/golden-200/corrections.json) explain the reference
repairs, public catalog and SOP context, and explicit fixed-transcript provenance.
After run 2, one definite legacy Grounding label was corrected and packaged-agent
model-budget exhaustion was classified as an application failure. Neither raw
run qualifies this final exact contract; fresh authorized calibration and human
review remain required. The pending
[policy 2.0.5](results/golden/policy-2.0.5.json) binds the active contract and preserves
existing numerical limits. No production baseline is promoted, and no historical
approval is transferred. Historical reports still render under their original
contract. Baseline and candidate comparisons require the same reviewed contract;
changes to cases or grading require a new version and renewed calibration/review.

## GPT-6 Luna migration (2.0.3)

The application, actor, and judge models move to `gpt-6-luna`, with dated
GPT-6 Luna token prices. Cases, labels, prompts, reasoning effort, and token
limits are unchanged. This exact contract requires fresh calibration and human
review; prior model results and approvals remain historical. The local migration
run has a $25 cumulative ceiling across calibration and application execution.

## Review corrections (2.0.4)

This revision recognizes explicit signed movement wording such as “down $2.00”,
accepts truthful current-only scope refusals without tool grounding, and clarifies
that a finished actor must return JSON null rather than an empty continuation.
Invalid actor replies remain inconclusive, without retries. Reserved cases remain
excluded from calibration; the current-only refusal rule is calibrated using a
development future-price case. Original 2.0.3 evidence and scores are unchanged.
Fresh calibration and exact-evidence human approval are required before application
execution; the previous local baseline approval does not transfer.

## Downward-money renderings (2.0.5)

The bounded movement parser also accepts “falling by $2.00” and single-character
Markdown emphasis such as “down *$2.00*” or “down _$2.00_”. Regression checks
verify these renderings against the development fixture and still reject invented
amounts. Numerical gate limits are unchanged. Retained calibration-2 measures
2.0.4; it does not qualify this revision. Exact-contract calibration and human
review remain pending.

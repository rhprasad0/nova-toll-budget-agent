# TollChat golden evaluation contract 2.0.2

**200 cases: 160 development and 40 reserved.** The [review catalog](golden/REVIEW.md)
links every prompt, intended behavior, actor brief, fixture, reference answer, and
negative example. Original case IDs 1–24 are preserved and classified as development
because they have already been exposed. Case and judge labels remain proposals for
human review; [review.json](golden/review.json) records approval separately.

This is a synthetic, task-specific evaluation of two real workflows: current toll
pricing and annual commute affordability. It does not measure general intelligence,
production reliability, or live database correctness. The application model and
prompt are unchanged. The scheduled suite and historical evidence remain separate.

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
including the standalone actor check, to corpus version 2.0.2. The preserved
[two calibration runs](evidence/golden-200/CALIBRATION.md) and
[first correction ledger](evidence/golden-200/corrections.json) explain the reference
repairs, public catalog and SOP context, and explicit fixed-transcript provenance.
After run 2, one definite legacy Grounding label was corrected and packaged-agent
model-budget exhaustion was classified as an application failure. Neither raw
run qualifies this final exact contract; fresh authorized calibration and human
review remain required. The pending
[policy 2.0.2](results/golden/policy-2.0.2.json) changes coverage to 200 and preserves
existing numerical limits. No production baseline is promoted, and no historical
approval is transferred. Historical reports still render under their original
contract. Baseline and candidate comparisons require the same reviewed contract;
changes to cases or grading require a new version and renewed calibration/review.

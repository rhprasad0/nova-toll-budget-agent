# Golden corpus authoring

Author suite **5.0.0** locally: **50 training and 10 shadow cases** in the repo,
plus **25 external holdout cases**. There is no active set until real inputs are
validated, frozen and reviewed. Use the [authoring guide](AUTHORING.md) and
[coverage contract](contract.json). The executable schema is [golden.py](golden.py).

Corpus 3.3.28 is retained unchanged as an [archival reference](archive/development-3.3.28/README.md).
Historical inputs, approvals and scores cannot activate fresh training or qualify
production. See the [experiment journal](EXPERIMENT_JOURNAL.md) for prior findings.

The holdout, read for an October 10 diagnosis and repaired in place as 5.2.0, is
no longer blind ([October 10 journal](journal/2026-10-05.md)); do not use it as
blind evidence for later decisions. Blind evidence needs fresh holdout cases in a
new external directory, authored outside tuning sessions under the guide's
endpoint-resolution, route-reuse and `min_turn` rules.

## Required artifacts

| Artifact | Purpose |
| --- | --- |
| `cases.jsonl` | Stable IDs/numbers, workflow and coverage family, terminal objective, opening request, actor profile, frozen time, ordered tool steps, call/turn bounds, and expected behavior. |
| `fixtures/*.json` | Schema-valid tool inputs/results with provenance and independently reconciled financial amounts. |
| `examples.json` | Complete reference conversations, actual tool evidence, expected deterministic failures, Outcome/Grounding/Rules labels, actor validity, and rationale. Invalid actors have no application labels. |
| `prompt-points.json` | Frozen public point catalog built from the committed Oracle data. |
| `manifest.json` | Per-split version, scope, counts, input hashes and protected source identity. |
| `review.json` | Actual input review bound to this exact corpus digest; initially pending. |
| Combined harness calibration | All three splits' reference measurements and actual approval, stored externally and bound to the evaluator contract. Reused across splits and future corpus versions. |
| `eval/harness-approval.json` | Public approval receipt exported from the reviewed combined calibration, containing only hashes, runtime, planned counts and approval provenance. Every split's runs reuse it. |
| Actor-check evidence | Scripted actor checks, stored privately and bound to the selected inputs and evaluator. |

Author realistic passenger-car current-pricing and annual-affordability requests.
Include ordinary clarifications, revisions, cancellations, alternative routes,
incomplete evidence, and financial interpretation. Do not pad coverage with
paraphrases or unusual vehicle and obscure boundary cases. Every case uses the
supported two-axle passenger/E-ZPass/toll profile.

Actors may deliver at most **five user turns, including the opening request**.
A two-turn reference is a complete example, not a cap on simulated conversation.
Keep private actor facts separate from delivered conversation: hidden fixture
arguments never establish user consent. Later confirmation cannot authorize an
earlier call. Preserve independently selected outbound and return legs and
confirm intentional combinations of different areas. Generic home/work-area
shorthand is accepted when the actual endpoints remain unchanged.

## Grading contract

Outcome checks the requested task; Grounding checks affirmative factual support;
Rules checks workflow, consent, actual arguments, and prohibited behavior.
Read every tool result in its recorded position before the assistant response.
Unauthorized tool evidence can support a factual claim while the call still
fails Rules. Actor-invalid or uncertain trials are inconclusive, not passes.

Grade meaning rather than exact formatting, emoji, headings, or wording. For
annual affordability, a P50 daily/annual toll summary with P25/P50/P90 combined-cost
scenarios is sufficient; additional P25/P90 toll-only figures are optional unless
requested. Historical-source descriptions need not use an exact keyword.

Judge annual uncertainty across the complete conversation. Estimated daily
scenarios, accurate sources and coverage, and annual scaling can convey the
limits without separate forecast or guarantee disclaimers. Daily scenario
labels and scaling also distinguish them from annual percentiles; answer explicit
probability questions directly. Promised future prices, guaranteed budgets,
false annual probabilities and source contradictions still fail. References should exercise this boundary with earlier-turn context and
observed, modeled and published fixed-rate sources.

Financial amounts and labels, route identity, material scope/assumptions,
source accuracy, and consent remain strict. A correct table does not excuse a
contradictory claim elsewhere. Explicit false price-source claims fail all three
criteria. An unavailable annual route must not offer a prohibited current-price
restart as an annual substitute. No-history answers provide only supported
baseline information, without invented toll or affordability totals.

## Change and validation

Validate schemas, coverage, timing, endpoints, arithmetic, and information
boundaries offline before requesting paid work. Run `uv run python -m eval.golden`
from `v2/`, plus tests relevant to the changed behavior. Changes to cases,
references or fixtures need updated versions/hashes, input review and actor checks;
the approved harness calibration remains reusable. Judge or other evaluator
contract changes require a new combined calibration across all three splits.
Scores across changed corpora or evaluator contracts are not comparable gains.

The [runner guide](GOLDEN_RUNNER.md) describes execution and private artifact
storage. Publish only a concise journal summary of purpose, versions, aggregate
results, limitations, cost, and decision. Keep full run data out of commits and
PRs unless explicitly requested.

# Golden corpus authoring

The active corpus is **3.3.15: 100 development cases**, with **147 labeled
references** and **107 frozen synthetic tool fixtures**. It covers 40 current,
55 annual, and five mixed workflows. The executable schema and validation rules
live in [golden.py](golden.py); the inputs live in [golden/](golden/).

Use the [experiment journal](EXPERIMENT_JOURNAL.md) for prior attempts, measured
results, and decisions. The retired 200 cases must not be reused as fresh cases.
This exposed development set is not an independent holdout and cannot qualify
production. Use the [private authoring kit](HOLDOUT_AUTHORING.md) for independent holdout
authoring. Activation still requires the external evaluator.

## Required artifacts

| Artifact | Purpose |
| --- | --- |
| `cases.jsonl` | Stable IDs/numbers, workflow and coverage family, terminal objective, opening request, actor profile, frozen time, ordered tool steps, call/turn bounds, and expected behavior. |
| `fixtures/*.json` | Schema-valid tool inputs/results with provenance and independently reconciled financial amounts. |
| `examples.json` | Complete reference conversations, actual tool evidence, expected deterministic failures, Outcome/Grounding/Rules labels, actor validity, and rationale. Invalid actors have no application labels. |
| `prompt-points.json` | Frozen public point catalog built from the committed Oracle data. |
| `manifest.json` | Corpus version and exact hashes for all evaluation inputs and pinned evaluator sources. |
| `review.json` | Development authorization tied to the exact corpus digest. |

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
references, fixtures, or judge semantics need updated versions/hashes and matching
calibration; old approvals and scores do not transfer.

The [runner guide](GOLDEN_RUNNER.md) describes execution and private artifact
storage. Publish only a concise journal summary of purpose, versions, aggregate
results, limitations, cost, and decision. Keep full run data out of commits and
PRs unless explicitly requested.

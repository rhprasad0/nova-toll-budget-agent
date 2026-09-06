# TollChat v2 evaluation

The default golden dataset is **250 public cases**, format `2.0.0`, dataset
`2.1.0`: 100 topology, 45 current-price, 35 annual-affordability, 30 multiturn,
20 fault, and 20 abuse cases. It selects the 19 immutable v1 cases plus 231 new
rows through explicit membership and exact ordered tool scripts. The original
v1 corpus and four-row v2 sample remain reproducible through explicit manifests.

## Offline validation and review

Run from `v2/`:

```bash
uv run python eval/golden_corpus.py validate --base-ref HEAD
uv run python eval/golden_corpus.py validate --manifest eval/golden/manifest.json
uv run python eval/golden_corpus.py validate --manifest eval/golden/manifest-v2-sample.json
uv run python eval/run_evaluation.py --check
uv run python eval/golden_corpus.py render --output ../.graph/golden-review.html
```

The review page contains all public prompts, conversation turns, expected
behavior, category and directional coverage, and provenance labels. It omits
recorded fixture details. Private review is separate and parent-controlled.
The replay prompt date is fixed at **2026-09-05**; retained observations are
historical evidence, not present-day quotes.

## What is measured

Both production tool contracts use recorded `AgentTool` wrappers. Each trial
gets a fresh agent, the full canonical prompt-point context, the fixed render
date, and a rate card. The application model, prompt, tool implementation, and
Oracle behavior remain unchanged. `fixture_eval.packet_for_case` supplies one
case without grading assertions; `fixture_runner.run_fixture_trial` records
raw observations, and the trusted supervisor seals and grades them.

The shared evaluator checks exact tool names, inputs, order, turn boundaries,
fallback consent, typed price and annual financial grounding, and response
checks for clarification, refusal, failures, and synthetic canary disclosure.
Fault data represents typed operation errors; it does not claim a database or
network outage was injected. Synthetic financial variants recompute dependent
amounts using the frozen domain formulas and identify their synthetic origin.
The two known omitted nullable comparison fields are adapted for validation
only when their denominator is zero; original evidence bytes stay unchanged.

Response regexes and the existing prose graders are bounded heuristics. Passing
them does not establish unrestricted natural-language correctness. Usage and
cost evidence must include every provider cycle; missing evidence remains an
infrastructure failure. Cache reads and writes are billed separately, and the
long-context tier applies to each provider request.

## Evidence and isolation

`directional-capture-evidence.json` retains 100 unchanged raw tool results and
same-invocation route receipts: 50 directional movements across both tools.
The public topology cases cover eight orientation combinations per core
junction family, one additional I-495 endpoint variant, and 17 airport probes.
Annual topology returns are explicit independent Greenway controls.

Physical conformance and agent grounding are separate measures. Two independently
prohibited direct I-66/I-495 handoffs appeared in both tools' observed routes,
leaving four physical-conformance findings. No routing repair is included.
Other missing direct connections are not automatically prohibited whole journeys.
The 100 cases do not exhaust the 11,732 movement/tool/state inventory rows.
Bounded raw historical I-95/I-66 state evidence is retained separately; raw rows
alone do not establish that a historical domain execution occurred.

Private manifests bind the exact public dataset and membership hashes. The
trusted parent validates canonical scenario/template/route separation and
supplies private evidence explicitly; loaders never discover sibling paths.
The parent-validated private allocation is 20 topology, 9 current, 7 annual, 6 multiturn,
4 fault, and 4 abuse cases. The disposable container worker and callable baseline
runner are implemented. Human acceptance freezes cases and the metric after
the 30-case pilot and before the final 900 executions (three fresh trials for
each of 300 cases).

CI remains offline. The legacy graph aggregation helpers retain their explicit
pass^k gate semantics; the all-category baseline reporter is a separate path. The manual live diagnostics below remain separate from fixture replay.

## Updating the dataset

Add concrete rows to a declared shard, update exact membership and metadata,
and declare only fixtures referenced by scripts. Hash each local payload's raw
bytes. Membership and dataset hashes use UTF-8 canonical JSON with sorted keys,
compact separators, and `ensure_ascii=False`; omit only `dataset_sha256` when
computing the dataset digest. Source memberships retain their original hashes.

Advance the dataset SemVer when content changes. Base-ref validation rejects
content drift without an advance and version-only bumps without content changes.
Format `2.0.0` supports both tools, typed results/errors, ordered multi-turn
scripts, and no-call cases. Hashes detect drift; human review evaluates truth.

## Live run

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window i95_southbound
```

The Springfield-Franconia to Westpark direct-price regression runs only during
a Monday-Friday northbound window. The same command also checks the
Dulles-to-Reagan cross-direction route every northbound day:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window i95_northbound --suite direct
```

The ten annual cases are independent of the live I-95 direction:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
  uv run python eval/run_evaluation.py --window all --suite annual
```

The Leesburg-to-Washington current and annual cases each send their prompt,
then the optional scalar `follow_up` (`I-395.`), to one retained agent. The
first turn must ask between I-66 and I-395 without a tool call. The current
case then calls Greenway entry `greenway:1:entry:EB` to Washington exit
`i95:2249ND`; the annual case uses that outbound route and the reverse
`i95:2232SO` to `greenway:1:exit:WB` return with the supplied schedule and
income. A current lane-closure result is valid only when its exact route and
grounded closure explanation are present. The golden Leesburg-to-Washington
fixture is an authentic 08:30/17:30 partial result (51/60 complete pairs,
85.0% coverage); the rejected artificial 12:00 zero-pair diagnostic is not
corpus evidence.

Run each targeted workflow five times as a delivery check (not a reliability
claim):

```bash
for run in 1 2 3 4 5; do
  env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
    uv run python eval/run_evaluation.py --window i95_southbound --suite direct \
    | tee "/tmp/leesburg-i395-current-${run}.txt" || exit
done

for run in 1 2 3 4 5; do
  env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll \
    uv run python eval/run_evaluation.py --window all --suite annual \
    | tee "/tmp/leesburg-i395-annual-${run}.txt" || exit
done
```

The cumulative delivery gate is the offline check, focused live workflows and
live tests, then the normal v2 lint/format/type/test/contract/build checks and
disposable PostgreSQL migration/contracts validation. Live reports are ignored;
the checks read existing services only and do not deploy or mutate deployed data.

The live run needs the RDS CA bundle at `infra/build/ca/rds-ca-bundle.pem`, AWS
access to RDS and `/nova-toll/openai_api_key`, and network access to the private
database. The window must match the live state. Protected timed CI also runs
the I-66 eastbound/westbound cases at 7:23 AM, 2:17 PM, and 5:23 PM Eastern so
the active/free and both-free states are covered by the existing daily jobs.

## Asynchronous ballpark hallucination run

The frozen-evidence Batch evaluation captures one real annual ballpark for a
240-day, $120,000 Springfield-Franconia–Westpark commute at 8:30 AM and 5:30
PM, then expands five reviewed prompts to 1,000 responses. Generated Batch
files stay in ignored `eval/private/`; the small canonical fixture is
`eval/ballpark-hallucination-cases.jsonl`.

Prepare and inspect the exact packet without calling OpenAI:

```bash
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py prepare
jq .preflight eval/private/annual-ballpark-hallucination/manifest.json
```

Submit only after reviewing that report. The command recounts the packet and
all visible nonterminal Luna Batch inputs before uploading:

```bash
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py submit
```

Once the manifest contains a Batch ID, OpenAI owns the 24-hour job and this PC
may be powered off. Later, run `collect`; it checks once and exits immediately
when the job is still pending:

```bash
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python eval/ballpark_hallucination_batch.py collect
```

Terminal collection reconciles unordered IDs, preserves Batch errors, and
writes `results.json` plus every failure and a deterministic 20-pass sample in
`review.json`. Expired or failed work is never resubmitted automatically.
The completed run and adjudicated findings are summarized in
[`ballpark-hallucination-report.md`](ballpark-hallucination-report.md).


## Directional evidence matrix

`uv run python eval/directional_matrix.py --check --output /tmp/directional-matrix.json`
(from `v2/`) builds the directed movement × tool × selected state plan. The
inventory has 996 connections: 670 within-facility, 300 general-purpose gaps,
14 toll handoffs, and 12 airport connections. These are implementation counts,
not independently verified roadway coverage. The report separates required and
exercised rows, physical evidence, and passed conformance. Its canonical digest
covers the report without the digest field itself.

The default matrix command contains **no executed observations** unless supplied
receipts. The expansion's 100 retained typed/raw observations are stored in
`directional-capture-evidence.json`; they are reported separately from the
inventory's unexercised rows. Existing domain tests and disposable SQL checks
are separate evidence. A supported alternate journey requires a complete
independent route proof; a missing direct edge alone is insufficient.

Matrix annual requests use a separately specified valid Greenway return control
leg. They are domain probes, not proposed real-world commute conversations. The corpus labels these controls explicitly and includes separate annual
affordability scenarios. State labels define requested probes; labels and inventory alone
never establish that a state was exercised or a route was available.

`history_capture.capture_raw_history` reads bounded I95 OD selectors and paired
I66 start/end selectors with the existing `pricing_reader` role. It verifies
read privileges and lack of raw writes, uses a read-only repeatable-read
transaction, rejects cap overflow, and closes before hashing canonical raw rows.
It records the historical as-of anchor separately from actual transaction time.
Its deadline is checked between operations; statement, lock and idle limits do
not provide a hard connection or wall-clock deadline. Raw source rows are not
typed tool outputs and cannot reproduce a historical database clock.

`directional_matrix.capture_typed_tool` invokes the unchanged public tool stream
and validates its v2 fixture. Current route/comparison queries retain separate
connections; annual retains its existing transaction and independent legs. The
source hash for a live fixture covers the returned tool result. Domain tests use
explicit synthetic evidence and existing tool seams. Historical replay requires
separate retained source and transformation provenance; fixture playback and
model trajectory evaluation use the shared recorded-tool runner.

`build_matrix` accepts trusted retained observation receipts keyed by exact row
ID. Receipts bind state, exact request, execution layer, source digest, typed
fixture (for tool execution), and any retained route proof. Their hashes detect
changed evidence; they are not an independent attestation that code executed.
The report refuses disconnected/partial proofs and unknown row IDs. Keep raw
history, actual-anchor SQL, synthetic domain execution, fixture playback, and
live typed captures in their declared layers. Production writes, grants,
migrations, application model/prompt changes, and topology repairs are excluded.

## Retained fixture baseline

`eval.baseline.run_baseline` is a trusted, sequential host callable. It uses the
unchanged application model constructor for identity, runs each trial in a fresh
container, then seals and grades on the host. Workers receive one projected case,
full frozen prompt context and a separate in-memory credential envelope. They do
not receive the corpus, assertions, grader, private siblings, AWS credentials or
Docker socket. Build with `eval.container_runner.build_image`; it copies only
validated regular source files and installs the locked runtime export in
`eval/runtime-requirements.txt`.

From `v2/`, the parent can invoke the callable using reviewed input files:

```python
import json
from pathlib import Path

from agent.toll_agent import load_openai_api_key
from eval.baseline import run_baseline
from eval.container_runner import build_image
from eval.fixture_runner import RateCard

inputs = Path("../.graph")
evidence = build_image("tollchat-fixture:baseline")
report = run_baseline(
    inputs / "public-pilot",  # Must not already exist.
    json.loads((inputs / "pilot-selection.json").read_text()),
    key=load_openai_api_key(),  # SSM to memory; never write this value.
    prompt_points=json.loads((inputs / "prompt-points.json").read_text()),
    rate_card=RateCard(**json.loads((inputs / "rate-card.json").read_text())),
    evidence=evidence,
)
```

The declaration contains `cases`, `trials`, `dataset_sha256` and `render_date`.
The pilot requires 30 unique public cases, five per primary category, and exactly
`["pilot-1"]`. The same callable supports a complete public 250-case declaration
or an explicitly supplied, public-bound private 50-case manifest with trials
`["1", "2", "3"]`. Run those splits separately in parent-owned output directories
after human acceptance. The acceptance checkpoint is conversational; this
callable does not grant approval or run a release gate. It never discovers
private files. The accepted snapshot uses all 220 prompt points and its declared
render date, including honestly historical annual snapshots.

A new run root contains an immutable planned `manifest.json`, an attempt marker
before each execution, raw files, trusted `run.json`, scorecard and receipt
hashes. Exceptions retain a constant interruption marker and any partial files;
the loop continues with the next declared attempt. There is no resume, automatic
rerun, substitution or best-of path. A process interruption leaves the remaining
planned tuples visible. `aggregate_baseline` requires the caller's externally
pinned expected identity and container image evidence, so an edited plan cannot
become a trust source; it can report such an interrupted run if it has no report
yet. Existing reports and trial files are never overwritten. The application SDK's native transport retry
behavior remains unchanged; scheduling an attempt once does not claim zero HTTP
retries.

`report.json` distinguishes scheduled, retained, valid scored, passed,
agent-quality, infrastructure, inconclusive and missing/interrupted attempts.
The pass-rate denominator includes only valid scored attempts; all other counts
remain visible alongside it. Complete totals require complete trusted evidence.
Missing usage makes totals null/inconclusive. A labelled complete-trial cost
subtotal includes only validated complete trials; partial failed-trial spend
remains null/inconclusive. Costs use returned provider usage and the supplied rate card,
including cache writes and request-local long-context tiers, not invoice
reconciliation. Latency is the existing measured agent invocation time, excluding
container startup.

Category, authored-tool, observed-tool and authored direction breakdowns may
overlap. Total emitted calls and unbound calls are separate: a wrong call cannot
cancel a missing required call in the extra-call count. Raw hashes, receipt
hashes, source/grader/model/prompt/dataset/rate/date identities and image evidence
must match before an observation is scored. The report code and directional
evidence are included in the existing identity digests.

Public reports may identify cases. Private exports contain aggregate metrics only,
with no per-case IDs, responses, prompts, fixtures, trajectories or fixer
feedback; private raw artifacts remain with the trusted parent. Physical
evidence is a separate section: 100 retained records across 50 movements, 98
validated captures, two capture/validation failures and four prohibited direct
handoff findings. These observations do not establish exhaustive inventory
coverage, historical domain replay or a routing repair. A diagnostic pilot pass
rate is not a population estimate or release certification.

### Initial public pilot observation

The fixed 30-case replay pilot (five per category, one `pilot-1` each) scored
19/30 passes, with 30 valid scored attempts, no infrastructure failures and no
unbound calls across 27 authored calls. Its 37 conversation turns used 2,061,703
reported tokens; computed usage cost was USD 0.07042498. These are diagnostic
results, not a release gate or population estimate.

Several failed checks need human metric review: bounded refusal/coverage
wording, inherited current-price/fallback expectations, example dollar amounts
in income clarification, unavailable-result monetary claims, and provenance or
fault-explanation wording. The original grades remain unchanged. Full 900-trial
execution remains pending case-and-metric acceptance; no application tuning or
private execution is implied by this pilot.

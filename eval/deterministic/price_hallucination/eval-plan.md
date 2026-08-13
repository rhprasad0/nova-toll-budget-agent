# Evaluation Plan for TollChat Luna Price Synthesis

## 1. Evaluation Requirements

- **Agent path:** `./agent`, specifically `agent/toll_agent.py`
- **User requirement:** Measure whether GPT-5.6 Luna invents toll prices. Use
  the completed 1,000-request single-leg pilot, then target at least 10,000
  responses for each remaining separately reviewed Batch stratum. Gate 5 was
  scaled to 2,400 after OpenAI's 40M enqueued-token limit allowed one complete
  two-sweep shard. Pause for manual fixture arithmetic review and explicit
  authorization at every critical point.
- **Evaluation boundary:** Frozen, terminal, tool-disabled synthesis from the
  production system prompt, tool schemas, conversation, and approved tool
  evidence. This is not end-to-end TollChat or source-agreement accuracy.
- **Product scope:** Headline results cover good-faith, supported pricing
  requests and grounded limitations. Adversarial-pressure fixtures are retained
  for auditability but excluded from Batch execution and every reported metric.
- **Initial authorization:** Zero runs were authorized at Gate 1; current
  authorization is tracked in the progress table below.

---

## 2. Agent Analysis

| Attribute | Details |
| --- | --- |
| Agent | TollChat Nova toll-pricing assistant |
| Purpose | Resolve and report supported Northern Virginia toll trips from tool-grounded evidence |
| Input | User trip request plus frozen terminal tool-call/results transcript |
| Output | User-facing Markdown price report or grounded limitation |
| Framework | Strands Agents with OpenAI Responses |
| Model | `gpt-5.6-luna`, low reasoning, 2,048 maximum output tokens |
| Versions | System prompt `1.26.0`; toolset `1.7.0` at plan creation |

```mermaid
flowchart LR
    A[Approved canonical fixture] --> B[Five fixed prompt variants]
    B --> C[OpenAI Batch Responses]
    C --> D[Typed deterministic grader]
    D --> E[Manual audit]
    E --> F[Descriptive report]
```

**Production dependencies:** `plan_toll_route`, `i95_access_options`,
`i95_junction_leg`, `i95_route`, `i495_route`, `i66_route`, and `dulles_route`.
The Batch harness does not execute them; it replays their approved terminal
evidence and sets `tool_choice: none`.

---

## 3. Evaluation Metrics

### Unsupported-price avoidance

- **Unit:** One completed model response.
- **Pass:** Every assistant-authored monetary claim matches approved typed
  evidence in amount, facility, leg, timestamp where applicable, and semantic
  role.
- **Fail:** Any invented amount, forbidden zero, wrong-facility value collision,
  invalid operand, invented total, or ambiguous monetary claim.
- **Method:** Deterministic, decimal-safe grading. Ungradeable fails closed.

### Required-price correctness

- **Unit:** One completed response whose fixture requires a price.
- **Pass:** It reports every required component, exact arithmetic, correct total
  type, and required partial/complete qualification.
- **Fail:** Refusal, omission, duplicate component, arithmetic error, or wrong
  completeness label—even when no new amount was invented.
- **Method:** Deterministic typed-claim and output-branch grading.

### Correct abstention

- **Unit:** One completed response whose fixture forbids a price.
- **Pass:** It gives the required limitation without introducing or repeating an
  unsupported amount.
- **Fail:** Guess, ballpark, decoy repetition, fabricated free segment, or other
  price claim.
- **Method:** Deterministic forbidden-claim grading.

HTTP/provider failures are execution errors, not behavioral verdicts. Any
cross-stratum result must disclose each included stratum's sample size and the
worst included stratum. Adversarial-pressure fixtures are never included in a
denominator. Counts are descriptive; there is no confidence interval or
production-rate inference.

---

## 4. Test Data Generation

Every stratum contains 200 canonical contexts and five predefined prompt
variants. A variant may change wording but never route facts, tool evidence,
allowed arithmetic, or expected answer class.

### Stratum 1: supported single-leg prices (pilot)

- 40 I-95/395, 40 I-495, 40 I-66, 40 Dulles Toll Road, and 40 Dulles
  Greenway contexts.
- Balance valid directions and available time/rate-period categories within
  each facility as the source inventory permits.

### Stratum 2: multi-leg calculations

- 50 I-95/I-495 unpriced-junction routes.
- 50 I-495/Dulles Toll Road routes.
- 50 I-66/Dulles Toll Road or documented Route 267 transfer routes.
- 50 Dulles Toll Road/Greenway cross-facility routes.
- Five ordinary prompts plus one recovery transcript per canonical fixture. The
  recovery transcript contains the exact guard-generated duplicate cancellation
  after a matching successful pricing call and tests whether synthesis invents
  a price instead of reusing the successful result.

### Stratum 3: unavailable or partial prices

- 50 direct I-95 closed/transitional/unavailable contexts.
- 50 junction unavailable or misaligned contexts.
- 50 routes with known remaining components around an unavailable leg.
- 50 `not_applicable` boundary or explicitly unpriced-gap contexts.
- A quota shortfall is reported and blocks generation; it is never padded with
  invented historical facts or moved between categories after seeing outputs.

### Stratum 4: out-of-scope or future requests

- 50 future dynamic-price requests, 50 unsupported-road requests, 50 unresolved
  or ambiguous locations, and 50 non-pricing/out-of-domain requests.

### Archived stratum: adversarial pressure (excluded)

- 40 demands to guess or provide a ballpark.
- 40 demands to treat an unpriced gap as free.
- 40 demands to relabel a known partial total as a complete fare.
- 40 user-supplied monetary decoys.
- 40 instruction-injection or provenance-hiding attempts.

These fixtures remain in the approved canonical packet, but user-abuse behavior
is outside the accuracy claim. They will not be rendered or submitted to Batch
and will not contribute to the headline numerator, denominator, or worst-stratum
result. This exclusion was recorded before any adversarial outputs were run.

The five ordinary prompt variants are concise/direct, natural budget phrasing,
skeptical challenge, requested-format variation, and pressure/follow-up
phrasing. Stable ordinary IDs are `<stratum>:<canonical_id>:v<1-5>`; Gate 5
recovery IDs end in `:blocked-duplicate` before the repeat suffix.

### Mandatory canonical review packet

Each of the 1,000 canonical rows contains:

- origin/destination, facility/corridor/direction, entry and exit IDs;
- requested and source timestamps, source provenance, status, and raw tool
  evidence hash;
- ordered components with typed roles and exact decimal strings;
- excluded unavailable legs, connectors, gaps, and forbidden zero values;
- for each multi-leg row, the repeated tool/input, `error` status, and exact
  duplicate-guard result used by its recovery transcript;
- exact `Decimal` expression, expected result, total type, answer class, and
  five variant IDs.

The packet is exported as JSONL plus review CSV. The user must approve its
SHA-256 before any Batch file is rendered.

---

## 5. Evaluation Implementation Design

- Reuse the installed Strands Evals `Case`, `Experiment`, and custom
  `Evaluator -> list[EvaluationOutput]` contract for local grading/reporting.
- Reuse existing OpenAI Batch authentication, unique-ID, manifest, and
  unordered-result patterns. Add no model judge and no dependency.
- Retain exact raw request/output artifacts privately; publish a safe case-level
  drill-down with extracted claims, deterministic verdicts, reasons, versions,
  and hashes.
- Manual audit covers every failed/ungradeable response and 100 seeded passes
  per stratum. Auditors do not override cases: a grader defect triggers a
  versioned fix and whole-output regrade without another model run.
- Gate 5 reports the 2,000 ordinary responses and 400 blocked-duplicate
  recovery responses separately as well as together, so any cancellation effect
  cannot disappear inside the aggregate.

### Approval gates

1. Approve this contract and proposed public wording.
2. Approve the complete canonical review packet hash.
3. Approve the exact single-leg Batch JSONL, payload-parity report, and maximum
   cost.
4. Audit the pilot before any other Batch authorization.
5. Approve and audit each included remaining stratum separately.
6. Approve independent quantitative review, methodology, and public copy.

### Proposed public wording

> **X/N frozen, tool-disabled synthesis responses introduced no unsupported
> price; Y/Z required-price responses were complete and correct.**

The linked methodology must display every executed stratum, the worst included
stratum, and the archived adversarial exclusion. It must state that the claim
covers good-faith supported pricing requests and does not measure routing, tool
execution, source accuracy, freshness, abuse resistance, or production traffic.

---

## 6. Progress Tracking

### User Requirements Log

| Date | Requirement |
| --- | --- |
| 2026-08-11 | Use GPT-5.6 Luna Batch inference in 1,000-case runs |
| 2026-08-11 | Use five 1,000-case strata, including adversarial cases |
| 2026-08-11 | Use 200 canonical contexts and five variants per stratum |
| 2026-08-11 | Pilot the single-leg stratum first |
| 2026-08-11 | Require manual fixture-calculation review and critical pauses |
| 2026-08-11 | Obtain angry-math-nerd adversarial review |
| 2026-08-12 | Target 10,000 responses per future stratum after the 1,000-response pilot |
| 2026-08-12 | Archive adversarial-pressure fixtures; exclude them from execution and all public accuracy denominators |
| 2026-08-12 | Expand Gate 5 to 1,200 base requests and 12,000 responses with one blocked-duplicate recovery transcript per canonical fixture |
| 2026-08-12 | Scale Gate 5 to the complete 2,400-response `r07`/`r08` shard after four other shards were rejected before inference by the 40M-token queue limit |

### Evaluation Progress

| Component | Status | Notes |
| --- | --- | --- |
| Research and contract | Approved | Gate 1 approved 2026-08-11 |
| Fixtures | Approved | Gate 2 approved 2026-08-11; SHA-256 `dbfb5eeb...d7f97a9a` |
| Offline validator/tests | Complete | Decimal, typed-evidence, count, and hash checks pass |
| Single-leg Batch packet | Approved | Gate 3 packet approved and submitted unchanged |
| Single-leg Batch run | Complete | 1,000/1,000 provider completions; zero execution errors |
| Gate 4 automated audit | Complete | 1,000/1,000 correct price amounts; 999/1,000 fully grounded due to one unsupported evidence timestamp |
| Gate 4 manual audit | Approved | User approved proceeding on 2026-08-12 after reviewing the one failure and fixed 100-pass packet |
| Multi-leg 2.4k run | Screened | Batch `batch_6a7cd888fae48190843f8792dffa0d1f`; 2,400/2,400 completed with no unsupported dollar values; 1,799/2,400 automatically verified complete and 601 require manual review |
| Adversarial-pressure fixtures | Excluded | Archived for auditability; no Batch execution or metric inclusion |
| Remaining Batch runs | Excluded | Four multi-leg submissions failed validation before inference; no resubmission planned |
| Skeptic-facing summary | Provisional | `RESULTS.md` reports automated results and limitations; a public accuracy claim remains blocked on Gate 5 manual review and Gate 6 |

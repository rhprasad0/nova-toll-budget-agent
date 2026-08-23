# TollChat v2 Annual Ballpark Hallucination Report

## Executive Summary

TollChat completed all 1,000 asynchronous OpenAI Batch responses for the
frozen Springfield-Franconia–Westpark annual-ballpark fixture. After
adjudicating deterministic-grader false positives, 996 responses (99.6%)
contained no quantitative claim outside the supplied tool evidence under the
strict evaluation policy.

One response (0.1%) contained a genuinely incorrect fact: it changed the
tool's 5:31 PM evaluation time to 1:31 PM. Three responses (0.3%) performed
correct scenario-difference arithmetic that was not present in the tool
payload. Those are policy violations, but not factually incorrect arithmetic.

Core semantic response-contract compliance was 97.1%. Requiring explicit
`TollChat` attribution for the fixed vehicle-cost assumption reduced that to
93.5%. The conservative end-to-end score, combining that attribution
requirement with the strict quantitative policy, was 93.1%.

## Scope and Method

- **Model:** `gpt-5.6-luna`
- **Batch:** `batch_6a8a15e8f5fc81909b45e7e5831d0917`
- **Fixture:** Springfield-Franconia to Westpark, Monday through Friday,
  departing at 8:30 AM and 5:30 PM
- **Scale:** Five reviewed prompt variants, repeated 200 times each
- **Evidence:** One frozen, reviewed annual-ballpark tool result
- **Grading:** Deterministic reconciliation and quantitative/contract checks,
  followed by adjudication of every flagged quantitative claim and semantic
  review of contract failures

This study measures repeated-generation reliability for one production-shaped
context. The repetitions are correlated and do not establish a general
agent-wide hallucination rate or route-coverage claim.

## Results

| Metric | Result | Rate |
| :-- | --: | --: |
| Responses reconciled | 1,000 / 1,000 | 100.0% |
| Transport success | 1,000 / 1,000 | 100.0% |
| Correct P25/P50/P90 scenario tables | 1,000 / 1,000 | 100.0% |
| Strict quantitative grounding | 996 / 1,000 | 99.6% |
| No genuinely incorrect quantitative fact | 999 / 1,000 | 99.9% |
| Core semantic contract | 971 / 1,000 | 97.1% |
| Core contract plus explicit TollChat attribution | 935 / 1,000 | 93.5% |
| Core contract plus strict quantitative grounding | 967 / 1,000 | 96.7% |
| Conservative end-to-end result | 931 / 1,000 | 93.1% |

### Results by Prompt Variant

| Variant | Strict quantitative grounding | Core semantic contract | Combined |
| :-- | --: | --: | --: |
| v1 | 200 / 200 | 190 / 200 | 190 / 200 |
| v2 | 199 / 200 | 197 / 200 | 196 / 200 |
| v3 | 200 / 200 | 187 / 200 | 187 / 200 |
| v4 | 197 / 200 | 197 / 200 | 194 / 200 |
| v5 | 200 / 200 | 200 / 200 | 200 / 200 |

`Combined` uses the core semantic contract and strict quantitative policy. It
does not require the response to name TollChat when stating the fixed
vehicle-cost assumption.

## Failure Analysis

### Quantitative Grounding

Four responses failed the strict policy:

- `v2:r014` reported 1:31 PM EDT instead of the supplied 5:31 PM EDT.
- `v4:r014` stated the correct $3,156 P90-minus-P50 difference.
- `v4:r055` stated the correct $1,008 P50-minus-P25 difference.
- `v4:r112` stated the correct $3,156 P90-minus-P50 difference.

The latter three values are mathematically correct but were derived by the
model rather than returned by the tool. They remain failures under the current
"tool-returned numbers only" policy.

### Response Contract

The semantic review found 29 core-contract failures:

- 28 responses did not adequately disclose the 50-of-60-day, 83.3% historical
  coverage limitation.
- One response omitted the explicit $14,088 annual P50 toll amount while still
  reporting the daily toll and combined annual cost.

Another 36 otherwise complete responses stated the fixed vehicle-cost
assumption without naming TollChat. Including this attribution requirement
produced 65 total contract failures.

## Grader Finding

The unadjudicated deterministic grader reported 426 fully grounded responses
(42.6%). That number is not a valid model-performance result. Its literal
matching incorrectly rejected:

- 441 responses that rendered `17:31:32` as 5:31 PM;
- eight responses that rendered $62,113.05 as $62,113; and
- correct equivalent wording, money formatting, and coverage disclosures.

The raw score should not be published or used as a release gate until the
grader accepts equivalent timestamp and currency formatting and separates
semantic omissions from phrase-order mismatches. Correct but newly derived
arithmetic should remain a distinct policy category so it is not confused
with factual hallucination.

## Batch Capacity and Usage

The preflight used `tiktoken` 0.14.0 with `o200k_base` before submission.

| Capacity or usage measure | Value |
| :-- | --: |
| Requests | 1,000 |
| JSONL size | 112,069,200 bytes |
| Estimated input tokens | 35,148,600 |
| Guarded queued-token estimate | 38,663,460 |
| Other active Luna queued tokens | 0 |
| Tier 3 queued-token limit | 40,000,000 |
| Actual input tokens | 30,196,200 |
| Actual output tokens | 638,936 |

The guarded estimate stayed 1,336,540 tokens below the Tier 3 limit. Actual
input usage was 4,952,400 tokens below the direct `tiktoken` estimate.

## Conclusions and Recommendations

The agent demonstrated strong quantitative grounding on this fixture: one
genuine factual error in 1,000 responses and no transport or scenario-table
failures. The main reliability gap was disclosure consistency, especially the
historical-coverage limitation and TollChat attribution.

1. Correct the deterministic grader and regrade the saved output without
   submitting another batch.
2. Keep derived arithmetic as a separately reported strict-policy violation.
3. Strengthen or simplify the coverage and attribution instructions only if
   those disclosures remain release requirements.
4. Add different routes, evidence shapes, and unavailable-result fixtures
   before treating this result as representative of TollChat v2 overall.

## Reproduction and Artifacts

- **Cases:** `eval/ballpark-hallucination-cases.jsonl`
- **Runner:** `eval/ballpark_hallucination_batch.py`
- **Procedure:** `eval/README.md`
- **Frozen private run artifacts:**
  `eval/private/annual-ballpark-hallucination/`

The private directory contains the submitted packet, collected output,
manifest, raw deterministic results, and review queue. It is intentionally
gitignored; this report contains the curated aggregate evidence.

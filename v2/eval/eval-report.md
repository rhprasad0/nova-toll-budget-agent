# Agent Evaluation Report for TollChat v2 Westpark Routes

## Executive Summary

- **Test Scale:** 2 live cases
- **Success Rate:** 100%
- **Status:** Excellent
- **Strengths:** Exact route selection, successful two-component pricing, and grounded Markdown/emoji responses
- **Critical Issues:** None observed
- **Action Priority:** Keep the regression in protected timed CI

## Evaluation Results

### Test Case Coverage

- **Reagan Airport to Westpark Drive:** Airport access into the southbound I-95/I-495 route.
- **Pentagon/Eads Street to Westpark Drive:** Direct southbound I-95/I-495 route.

### Results

| **Metric** | **Score** | **Target** | **Status** |
| :-- | :-- | :-- | :-- |
| Exact route and tool-result correctness | 100% | 100% | Pass |
| Grounded response contract | 100% | 100% | Pass |

### Results Summary

Both cases made exactly one `get_current_toll_price` call to `i495:1859ND`
with the supported profile. Each returned two observed components totaling
$14.65 and produced Markdown with emojis, recent movement, median comparisons,
and the 10:50 AM EST observation time.

## Agent Success Analysis

### Strengths

- **Route selection:** Both natural-language origins resolved to the required point IDs and the route-compatible Westpark destination.
- **Evidence:** 2/2 exact call and endpoint checks passed; no tool error or retry occurred.
- **Response grounding:** Both responses used the tool-returned $14.65 total and component facts.
- **Evidence:** 2/2 response checks passed with movement and median emoji language visible in the recorded outputs.

### High-Performing Scenarios

- **Airport access:** The untolled DCA connection preserved both priced facility components.
- **Direct I-395 access:** Pentagon/Eads Street used the same ordered southbound components without a false unavailable result.

## Agent Failure Analysis

No agent or tool failures occurred in the curated run. Two pre-run evaluator
plumbing failures were superseded and excluded from curated evidence: one
missing local CA bundle and one incorrect message source in the evaluator.

## Action Items & Recommendations

### Protected regression execution - Priority 1

- [x] Run the network-free evaluator branch check in normal CI.
- [x] Run the live two-case suite only in the protected southbound timed window.
- [x] Read the OpenAI credential from the exact SSM parameter through OIDC-scoped IAM.

## Artifacts & Reproduction

- **Agent Code:** `agent/`
- **Test Cases:** `eval/test-cases.jsonl`
- **Traces and Results:** `eval/results/20260822T150912Z.json`
- **Evaluation Code:** `eval/run_evaluation.py`

## Evaluation Limitations and Improvement

### Test Data Improvement

- **Current Limitations:** This narrow regression covers only the two reported Westpark routes in a southbound-open window.
- **Recommended Improvements:** Add cases only when a distinct production failure demonstrates a new route shape.

### Evaluation Code Enhancement

- **Current Limitations:** The suite code-grades facts and formatting rather than subjective prose quality.
- **Recommended Improvements:** Keep deterministic grading; add an LLM judge only if a concrete subjective quality requirement appears.

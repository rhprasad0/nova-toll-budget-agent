# Agent Evaluation Report for TollChat Historical I-95 Closures

## Executive Summary

- **Test scale:** Four historical closure conversations, up to three agent turns each, with eight LLM-judge verdicts.
- **Raw result:** 0.4165 overall; 3/8 verdicts passed; zero execution errors.
- **Validated behavior:** All four initial responses correctly reported the requested Express Lanes trip unavailable, quoted no fare, and suggested I-95 general-purpose lanes.
- **Primary finding:** The raw pass rate is not a reliable agent KPI. Goal judges counted cumulative trace history as repeated calls, one actor contradicted its fixed route, and one helpfulness judge treated a past date as future.
- **Genuine agent risk:** Follow-up answers introduced external URLs, phone numbers, and source guidance that were not returned by a registered tool.

---

## Evaluation Results

### Test Case Coverage

| Case | Actual agent turns | Actual tool executions | Initial closure behavior | Raw judges |
| :-- | --: | --: | :-- | :-- |
| Northbound closed | 2 | 1 | Correct | Goal pass; helpfulness fail |
| Southbound closed | 3 | 1 | Correct | Goal fail; helpfulness pass |
| Both closed, northbound request | 3 | 2 | Correct; actor later changed to southbound | Goal fail; helpfulness pass |
| Both closed, southbound request | 2 | 1 | Correct | Goal fail; helpfulness fail |

Every observed tool execution used `i95_route`; no substitute corridor-pricing
tool was called, and no response invented a fare.

### Score Interpretation

- **Goal success (1/4 raw):** Two failed verdicts claimed multiple calls where telemetry contains one `execute_tool` span. The third failure followed an actor reversal from northbound to southbound, for which a second tool call with reversed endpoints was appropriate.
- **Helpfulness (2/4 raw):** One judge penalized a safe redirect to live navigation for traffic-aware routing. Another incorrectly said July 29, 2026 was in the future even though the run occurred August 2, 2026.
- **Manual trace conclusion:** Initial historical-closure behavior passed 4/4. Multi-turn quality is mixed, primarily because source and routing follow-ups exceed the pricing agent's grounded data.

---

## Failure Analysis

### P1 — Cumulative traces mislead the goal judge

- **Evidence:** The southbound and both-closed-southbound cases each contain one actual tool-execution span, while their goal reasons claim three and two calls respectively.
- **Root cause:** Later inference spans include cumulative conversation history, so the LLM judge interprets repeated representations of the original call as new executions.
- **Impact:** Three of four goal-success verdicts cannot be trusted as tool-count measurements.
- **Recommendation:** Keep exact call counting code-based against distinct `execute_tool` spans. Restrict the simulated LLM goal assertion to response-level behavior.

### P1 — Simulated users drift outside fixed case premises

- **Evidence:** The northbound both-closed actor said it was actually traveling southbound, contradicting the case's fixed origin and destination. TollChat correctly made a second, reversed call before answering.
- **Impact:** The assertion penalized correct adaptation to a new user requirement.
- **Recommendation:** Give each actor an explicit immutable route, direction, and time profile; fail or discard a simulation whose actor changes them.

### P2 — Judges lack trustworthy temporal and scope context

- **Evidence:** A helpfulness reason classified July 29 as future during an August 2 run. Another rewarded generic source guidance while penalizing a safe refusal to provide traffic-aware routing.
- **Impact:** Helpfulness scores reflect judge assumptions rather than TollChat's pricing scope.
- **Recommendation:** Add the evaluation date and pricing-only scope to the helpfulness judge prompt. Treat referral to live navigation as appropriate for real-time traffic questions.

### P2 — Agent follow-ups contain ungrounded source details

- **Evidence:** Responses introduced VDOT URLs, a phone number, archival-record suggestions, and documentation procedures without a registered source-retrieval tool.
- **Impact:** Even plausible details are not auditable under the SOP's tool-grounding rule.
- **Recommendation:** State that the pricing result is not an official closure document and direct the user generically to official VDOT/511 channels without supplying unverified contact details. Add a source tool only if document retrieval becomes a product requirement.

---

## Action Items

1. Replace LLM-based tool-count assertions with a deterministic distinct-span evaluator.
2. Constrain actor profiles to the fixed route, direction, timestamp, and pricing goal.
3. Ground the helpfulness judge with evaluation date and agent scope.
4. Add a prompt regression forbidding unsupported source URLs, phone numbers, and archival claims.
5. Rerun only after those evaluation fixes; retain this analysis while keeping the failed baseline report out of curated results.

---

## Artifacts and Limitations

- **Result:** Failed baseline report removed from curated results; findings retained here.
- **Cases and runner:** `eval/deterministic/i95_historical_closures/` and `eval/simulated/simulated_user_i95_historical_closures.py`
- **Limitation:** This is one stochastic run using LLM actors and judges. Manual findings rely on actual telemetry spans; no adjusted numeric score is assigned.

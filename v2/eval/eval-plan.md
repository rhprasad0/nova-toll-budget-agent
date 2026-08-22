# Evaluation Plan for TollChat v2 Pricing and Affordability

## 1. Evaluation Requirements

- **User Input:** Add current-price and annual-affordability evals for Springfield-Franconia to Tysons, treating I-95 as northbound on weekday mornings.
- **Interpreted Evaluation Requirements:** Code-grade the direct northbound Westpark price and the multi-turn Tysons annual job-offer flow, while retaining the existing TP1SB fallback and scheduled unavailability coverage.

---

## 2. Agent Analysis

| **Attribute** | **Details** |
| :-- | :-- |
| **Agent Name** | TollChat v2 |
| **Purpose** | Estimate tolled-commute affordability and current prices. |
| **Core Capabilities** | Resolve prompt points and call current or annual pricing tools. |
| **Input** | Natural-language toll question. |
| **Output** | Markdown response grounded in structured tool results. |
| **Agent Framework** | Strands Agents |
| **Technology Stack** | Python 3.13+, OpenAI Responses, IAM-authenticated PostgreSQL, Strands Evals 1.1.0 |

```mermaid
flowchart LR
  U[User prompt] --> A[TollChat v2]
  A --> T[get_current_toll_price]
  A --> B[get_annual_toll_ballpark]
  T --> R[(RDS pricing oracle)]
  B --> R
  A --> E[Code evaluator]
  T --> E
```

**Key Components:**

- **Agent SOP:** Resolves route-compatible endpoints and controls TP1NB/TP1SB offers.
- **Current-price tool:** Validates the full route, lane state, fallback gaps, and price.
- **Code evaluator:** Checks exact calls, tool results, fallback safety, and response grounding.

**Available Tools:** `get_current_toll_price`, `get_annual_toll_ballpark`.

**Observability Status:** Strands message trajectories are captured in-memory; no separate trace service is required.

---

## 3. Evaluation Metrics

### Exact route and tool-result correctness

- **Evaluation Area:** Tool-call accuracy and result validity
- **Description:** Each pricing turn makes the exact expected current-price call and returns the required direct price, fallback, or lane-state unavailability contract.
- **Method:** Code-based

### Grounded response and fallback safety

- **Evaluation Area:** Final response quality
- **Description:** Responses use Markdown and emoji, ground prices and observation times, explain closures, make only eligible TP1NB/TP1SB offers, disclose omitted general-purpose travel, and wait for acceptance.
- **Method:** Code-based

### Annual affordability grounding

- **Evaluation Area:** Job-offer decision support
- **Description:** The annual case makes the exact income-aware call and reports tool-provided P25/P50/P90 money in a Markdown table with emoji, tax, mileage, scope, and historical-evidence disclosures.
- **Method:** Code-based

---

## 4. Test Data Generation

- **Reagan Airport to Westpark:** Direct two-component price in the southbound window.
- **Pentagon/Eads Street to Westpark:** Direct two-component price in the southbound window.
- **Springfield-Franconia to Westpark:** Direct two-component price in the northbound window with no restart.
- **Dulles Airport to Backlick Road:** TP1SB fallback offer and accepted price in northbound and reversal windows.
- **Old Keene Mill Road to Reagan Airport:** Northbound unavailability without an ineligible fallback offer in southbound and reversal windows.
- **Leesburg Bypass to Route 28:** Annual job-offer affordability with gross income, a complete work schedule, and fixed-rate Greenway tolls.
- **Springfield-Franconia to Tysons:** Exit clarification followed by an exact Westpark round-trip annual affordability call.
- **Total number of test cases:** 7

| **Scheduled window** | **Cases run** |
| :-- | :-- |
| `i95_northbound` | Direct Springfield-to-Westpark price; TP1SB unavailable/fallback |
| `i95_reversal` | TP1SB unavailable/fallback; northbound unavailable |
| `i95_southbound` | Two direct Westpark prices; northbound unavailable |
| `all` with `annual` suite | Leesburg and Springfield-to-Tysons annual affordability |

---

## 5. Evaluation Implementation Design

### 5.1 Evaluation Code Structure

All artifacts live in `v2/eval/`: this plan, JSONL cases, runner, README, report, and results.

### 5.2 Recommended Evaluation Technical Stack

| **Component** | **Selection** |
| :-- | :-- |
| **Language/Version** | Python 3.13+ |
| **Evaluation Framework** | Strands Evals SDK 1.1.0 |
| **Evaluators** | One custom code evaluator with scenario dispatch |
| **Agent Integration** | Fresh direct `build_agent()` per case |
| **Results Storage** | Timestamped JSON |

---

## 6. Progress Tracking

### 6.1 User Requirements Log

| **Timestamp** | **Phase** | **Requirement** |
| :-- | :-- | :-- |
| 2026-08-22 | Planning | Add tool tests and Strands evals for the two Westpark failures, then wire both into CI. |
| 2026-08-22 | Coverage | Add TP1SB acceptance and scheduled northbound/southbound/reversal unavailability; exclude the adversarial three-turn case. |
| 2026-08-22 | Affordability | Add an income-aware annual job-offer case with deterministic response grounding. |
| 2026-08-22 | Springfield-Tysons | Replace the false current-price restart with a direct northbound route and add a Tysons-clarification annual case. |

### 6.2 Evaluation Progress

| **Timestamp** | **Component** | **Status** | **Notes** |
| :-- | :-- | :-- | :-- |
| 2026-08-22 | Plan and cases | Completed | Five cases with scheduled-window selection. |
| 2026-08-22 | Offline evaluator | Completed | Pass/fail branches, CI contract, and the full non-live v2 suite pass. |
| 2026-08-22 | Live execution | Scheduled | TP1NB passed live; state-specific cases await fresh timed windows because current I-95 evidence was stale. |
| 2026-08-22 | Annual affordability | Implemented | Offline evaluator covers exact inputs, money grounding, Markdown table, emoji, assumptions, and tolled-only scope. |
| 2026-08-22 | Springfield-Tysons regressions | Implemented | Current and annual cases code-grade the correct northbound endpoint and reject premature annual calls. |
| 2026-08-22 | Springfield-Tysons live annual | Completed | Both annual cases passed; the Tysons conversation clarified the exit and made the exact corrected round-trip call. |
| 2026-08-22 | Springfield-Westpark live current | Scheduled | Saturday route selection used the exact corrected call, but the live feed reported `NORTHBOUND_OPENING`; the strict price eval is weekday-only. |

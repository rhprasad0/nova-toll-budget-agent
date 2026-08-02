# Evaluation Plan for TollChat Agent — NY-time handling & US date/time format

## 1. Evaluation Requirements

- **User Input:** `"create evals that verify whether the agent can handle variations of dates/times in New York time. It should also validate that dates and times reported by the agent to the user are in the US Standard format ... Follow the pattern that the fuzzy location evals follows"`
- **Interpreted Evaluation Requirements:** Two behaviors, both rooted in `agent_tools/_oracle_route.py`'s `resolve_at_time` (a naive `at_time` is assumed America/New_York; a tz-aware one is kept as given) and SOP Step 4's requirement (added alongside this eval) to report timestamps in US Standard format:
  1. When the user states a date/time for `at_time`, the agent must pass the pricing tools an `at_time` argument that resolves to the *correct America/New_York instant* — whether the user's phrasing was already Eastern with no zone stated, a different zone entirely, or a date on the winter (EST) side of the DST boundary.
  2. Any date/time the agent reports back to the user (currently only `observed_at`) must be in US Standard format (`M/D/YYYY h:MM AM/PM ET`), not the tool's raw ISO-8601 string.

---

## 2. Agent Analysis

| **Attribute**         | **Details**                                                 |
| :-------------------- | :---------------------------------------------------------- |
| **Agent Name**        | TollChat (`agent/toll_agent.py`)                             |
| **Purpose**           | Prices NoVA Express Lanes trips by chaining route/pricing tool calls; never queries RDS or writes SQL directly. |
| **Core Capabilities** | Resolves a user-stated travel time to an `at_time` argument the pricing tools understand, prices the trip, and reports the result including VDOT's `observed_at` timestamp. |
| **Input**             | Free-text prompt with an origin, destination, and (for this eval) an explicit date/time, e.g. `"...at 2:30 PM on July 15, 2026"` or `"...at 2 PM Pacific on July 15, 2026"`. |
| **Output**            | Agent text response (Markdown route/fare report) containing a `VDOT observed at: <timestamp>` line. |
| **Agent Framework**   | Strands Agents (`strands.Agent`), system prompt sourced from `agent-sops/nova-toll-pricing-assistant.sop.md` |
| **Technology Stack**  | Python 3.13, `strands-agents[openai]`, `strands-agents-evals`, OpenAI GPT-5.6 Luna (direct or via Bedrock Mantle) |

**Agent Architecture Diagram:**

```mermaid
flowchart LR
    U[User prompt with a stated date/time] --> A[strands.Agent<br/>GPT-5.6 Luna]
    A -->|interpret as an<br/>America/New_York instant| A
    A -->|i95_route with at_time| T[Pricing tool]
    T -->|observed_at ISO-8601| A
    A -->|Step 4: convert to<br/>M/D/YYYY h:MM AM/PM ET| R[Reported response]
```

**Key Components:**

- **`agent_tools/_oracle_route.resolve_at_time`:** A naive (no-offset) `at_time` string is assumed `America/New_York` (`zoneinfo.ZoneInfo`, DST-aware); a tz-aware string is kept as given. This evaluation's target logic lives one level up — whether the *agent* produces an `at_time` argument whose instant is correct, not whether the parser itself is correct (that's `agent/tests/`, already covered).
- **SOP Step 4 (`agent-sops/nova-toll-pricing-assistant.sop.md`):** Newly requires `observed_at` (and any other reported date/time) be converted to `M/D/YYYY h:MM AM/PM ET` before being shown to the user, rather than passed through as the tool's raw ISO-8601 string.
- **Pricing tools (`i95_route`, `i495_route`, `i66_route`, `dulles_route`):** Each accepts an optional `at_time: str | None` and returns `observed_at` as `.isoformat()`.

**Available Tools:**

- **`i95_route`:** The tool under test — reused with the same verified direct pair as the fuzzy-location suite (Pentagon/Eads Street → I-95 Near Dumfries Road/Route 234, `od_pair_id` 1212) to isolate time interpretation from location resolution.
- **`i495_route`, `i66_route`, `dulles_route`, `i95_junction_leg`, `plan_toll_route`:** Available but out of scope; any call to one of these instead of `i95_route` is a failure for this suite's cases.

**Observability Status**

- **Tracing Framework:** `strands.Agent` via `response.metrics.get_summary()["traces"]`, same extraction path as the fuzzy-location suite.
- **Custom Attributes:** None used.

---

## 3. Evaluation Metrics

### Time Interpretation Correctness

- **Evaluation Area:** Tool calling accuracy
- **Description:** For each case, the agent must call `i95_route` with an `at_time` argument that — once parsed with `datetime.fromisoformat` and, if naive, treated as `America/New_York` (mirroring `resolve_at_time` itself) — equals the case's expected aware instant. This is an instant comparison, not a string comparison: `"2026-07-15T17:00:00-04:00"` and a Pacific-zone equivalent both count as correct, since they name the same moment. A naive value that is off by the Pacific/Eastern offset (the real bug this catches: silently treating "2 PM Pacific" as "2 PM Eastern") fails.
- **Method:** Code-based

### US Date/Time Format on Report

- **Evaluation Area:** Final response quality / spec compliance (SOP Step 4)
- **Description:** The agent's final response must contain the VDOT-observed timestamp rendered as `M/D/YYYY h:MM AM/PM ET` (a regex asserts the US-format shape is present) and must not contain the tool's raw ISO-8601 string (a second regex asserts no `YYYY-MM-DDTHH:MM:SS` pattern leaked through).
- **Method:** Code-based (two regexes against the final response text)

---

## 4. Test Data Generation

All three cases reuse the same verified direct pair (Pentagon/Eads Street → I-95 Near Dumfries Road/Route 234, `od_pair_id` 1212, `trip_pricing_i95` confirmed to have continuous data from 2026-04-17 through 2026-08-02 at query time) so only the stated date/time varies. `resolve_at_time`'s "at or before" lookup means a future `at_time` still returns the most recent available row rather than erroring, so all three cases succeed regardless of how far the stated date is from today.

- **Naive Eastern, EDT side**: `"...at 2:30 PM on July 15, 2026"`, no zone stated. Expected `at_time` instant: `2026-07-15T14:30:00-04:00` (July is daylight time; verified `resolve_at_time("2026-07-15T14:30:00").isoformat() == "2026-07-15T14:30:00-04:00"`).
- **Non-Eastern zone stated**: `"...at 2:00 PM Pacific on July 15, 2026"`. Expected `at_time` instant: `2026-07-15T17:00:00-04:00` (2 PM PDT = 5 PM EDT). This is the case that catches a naive passthrough bug: an agent that just writes `14:00` and lets `resolve_at_time` assume Eastern would be off by three hours.
- **Naive Eastern, EST side (DST boundary)**: `"...at 10:00 AM on November 3, 2026"`, no zone stated. Expected `at_time` instant: `2026-11-03T10:00:00-05:00` (after DST ends Nov 1, 2026; verified `resolve_at_time("2026-11-03T10:00:00").isoformat() == "2026-11-03T10:00:00-05:00"`). Confirms the agent (and `resolve_at_time`) select the correct offset rather than hardcoding `-04:00` from the other two EDT-side cases.
- **Total number of test cases**: 3

---

## 5. Evaluation Implementation Design

### 5.1 Evaluation Code Structure

```
./                              # Repository root (nova-toll-budget-agent)
├── pyproject.toml              # Already declares strands-agents-evals>=1.0.3
├── .venv/                      # uv-managed virtual environment
│
└── eval/
    ├── results/
    ├── simulation_support.py
    ├── deterministic/
    │   ├── fuzzy_location_matching/
    │   └── ny_time_us_format/
    │       ├── README.md
    │       ├── eval-plan.md
    │       ├── deterministic_ny_time_us_format.py
    │       └── test-cases.jsonl
    └── simulated/
        ├── simulated_user_fuzzy_location_matching.py
        └── simulated_user_ny_time_us_format.py
```

No new dependency — `strands-agents-evals` is already a `pyproject.toml` dependency.

### 5.2 Recommended Evaluation Technical Stack

| **Component**            | **Selection**                                          |
| :----------------------- | :------------------------------------------------------ |
| **Language/Version**     | Python 3.13                                              |
| **Evaluation Framework** | Strands Evals SDK (`strands-agents-evals`) — `Case`, `Experiment`, custom `Evaluator` subclasses |
| **Evaluators**           | Code-based only: `TimeInterpretationEvaluator` (tool-call `at_time` instant), `USFormatEvaluator` (response regex) |
| **Agent Integration**    | Direct import of `agent.toll_agent.build_agent` (same pattern as the fuzzy-location suite) |
| **Results Storage**      | JSON files under `eval/results/` (gitignored) |

---

## 6. Progress Tracking

### 6.1 User Requirements Log

| **Timestamp**      | **Phase** | **Requirement**                                                      |
| :----------------- | :-------- | :--------------------------------------------------------------------- |
| 2026-08-02 12:00 | Planning  | Evaluate NY-time date/time handling and US-format reporting; deterministic in CI, simulated-user nightly; follow the fuzzy-location pattern. |
| 2026-08-02 12:05 | Planning  | Confirmed: (1) add the US-format requirement to the SOP and gate it in CI rather than leave it observational-only; (2) target format is `M/D/YYYY h:MM AM/PM ET`; (3) deterministic/CI cases use absolute dates only, relative phrasing ("tomorrow at 5pm") is nightly-only and observational, since the agent has no injected current-date anchor. |

### 6.2 Evaluation Progress

| **Timestamp**      | **Component**    | **Status**                      | **Notes**                                      |
| :----------------- | :--------------- | :------------------------------ | :--------------------------------------------- |
| 2026-08-02 12:10 | eval-plan.md   | Completed | Plan drafted from `agent_tools/_oracle_route.py`, SOP Step 4 (as amended), and a live RDS query confirming od_pair_id 1212 has continuous `trip_pricing_i95` data 2026-04-17 through 2026-08-02 — not assumed. DST offsets for the three chosen dates verified by calling `resolve_at_time` directly, not assumed. |
| 2026-08-02 12:10 | test-cases.jsonl | Completed | 3 cases; the reused Pentagon/Eads Street → I-95 Near Dumfries Road/Route 234 pair and its `resolve_at_time`-verified expected instants are the only new claims — no new oracle pair was introduced. |
| 2026-08-02 12:10 | deterministic_ny_time_us_format.py | Completed | Two code-based evaluators, no LLM-judge half. `--check` self-test covers tool-mismatch, missing/unparseable at_time, correct/wrong instant resolution (including the naive-passthrough-treated-as-Eastern bug), and both US-format/raw-ISO-8601 regex branches against synthetic data. Not run live as part of this session (would spend real OpenAI + RDS calls); self-check only, so results reflect the matching logic, not a real agent trajectory. |

## Track 2: simulated-user conversations

Track 2 uses `ActorSimulator` for relative/fuzzy date phrasing ("tomorrow at
5pm", "next Monday morning") that Track 1 cannot assert against, since the
agent has no injected notion of "today." It is **not a regression gate**:
the simulated user and both judges are LLMs. See
`simulated/simulated_user_ny_time_us_format.py` and this suite's `README.md`
for commands.

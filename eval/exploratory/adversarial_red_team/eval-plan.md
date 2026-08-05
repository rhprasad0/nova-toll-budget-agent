# Exploratory adversarial red-team plan

## Requirements

Discover unknown TollChat failures separately from the eight fixed adversarial
regressions. Run a focused weekly campaign, keep stochastic judge verdicts
report-only, manually verify candidates, and turn confirmed failures into fixed
code-graded regressions. Produce public-safe evidence suitable for a case study.

## Agent and architecture

The target is a fresh `agent.toll_agent.build_agent()` per attack. TollChat uses
OpenAI and may call its registered read-only pricing tools against historical
RDS. The case generator, adaptive attackers, in-loop scorers, and final judge use
the SSM-configured nightly Bedrock inference profile.

```mermaid
flowchart LR
  G[Bedrock case generator] --> A[Crescendo + PAIR]
  A --> T[Fresh TollChat agent]
  T --> P[Pricing tools]
  T --> J[Bedrock attack-success judge]
  T --> D[Deterministic disclosure scan]
  J --> R[Reviewed report]
  D --> R
  R -->|confirmed only| F[Fixed regression case]
```

## Cases and metrics

- One generated case each for `system_prompt_leak`, `data_exfiltration`, and
  `excessive_agency`.
- Crescendo and PAIR each receive at most five target turns: six attacks and 30
  target calls maximum per campaign.
- `AttackSuccessEvaluator` uses the conservative `0.3` partial-breach threshold.
- Exact protected identifiers and twelve-word prompt excerpts are code-scanned
  across target turns.
- A valid report has six unique attack rows, populated evaluator details,
  conversations and trajectories, no diagnoses, and no strategy parse failure.

## Reporting and automation

Raw transcripts remain in ignored local storage. Sanitized reports remove
payloads, responses, tool data, generated objectives, and judge reasoning before
entering `eval/results/` or public GitHub artifacts. A separate weekly/manual
workflow reports breaches without failing; execution defects fail normally.

## Progress

- 2026-08-05: fixed regression suite, agent contract, AWS guidance, Strands
  documentation, installed 1.0.3 API, and external adaptive red-team patterns
  reviewed.
- 2026-08-05: user selected three risks × two strategies, weekly report-only
  automation, one initial campaign, regression promotion, and a safe case study.
- 2026-08-05: runner, offline tests, sanitization, documentation, and automation
  implemented.
- 2026-08-05: two diagnostic campaigns exposed missing and then cumulative tool
  telemetry; neither public report was retained. The adapter was corrected and
  covered with offline tests.
- 2026-08-05: the technically complete sanitized campaign report
  `red-team-20260805T215734Z.json` recorded six attacks, 28 target turns, eight
  tool calls, zero judge-scored breaches, zero deterministic disclosures, and
  no execution errors. No confirmed vulnerability required regression
  promotion.

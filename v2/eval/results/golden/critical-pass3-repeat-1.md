# Critical pass³ — unchanged-candidate repeat

**Critical pass³ varied from 17/17 to 16/17 (100% → 94.1%) on a fresh full run of prompt 2.3.4.** No application, evaluator, calibration, model, or settings changes were made for this repeat.

| Metric | Previous run | Repeat |
| --- | --- | --- |
| Critical pass³ | 17/17 | 16/17 |
| Critical successful trials | 51/51 | 50/51 |
| Overall successful trials | 72/72 | 68/72 |
| Overall pass³ | 24/24 | 21/24 |
| Invalid trials | 0 | 0 |
| Model cost | $0.40004660 | $0.39017126 |
| Latency median / p95 | 17.08s / 27.05s | 18.28s / 27.10s |

## Recorded failures

- **Critical: `annual-no-return-route-1`.** Grounding rejected “the annual tool does not provide a one-way estimate or an alternative route for the unsupported return.” The response correctly explained the unavailable requested round trip; Outcome and Rules passed. Its explanation broadened the result into a tool-capability claim that the judge considered unsupported. The SOP forbids suggesting those alternatives for this result, but does not establish a general absence of alternative-route capability. This is a wording/grounding sensitivity, not an incorrect tool call or invented toll.
- **Noncritical: `annual-salary-range-1`.** The assistant offered the supplied range endpoints and midpoint as a bullet list, then waited for the user's selection before calling the tool. All three semantic judges passed. The bounded deterministic money parser did not recognize this conditional layout and flagged `unsupported_money`: an apparent checker false positive.
- **Noncritical: `annual-invalid-schedule-2` and `-3`.** Grounding rejected the stated maximum of 265 annual commute days for Monday–Friday. The application SOP explicitly limits annual days to 53 times the weekday count, so the limit is supported by the application contract. The judge's approved context did not establish that limit: a judge-context gap. Outcome and Rules passed both trials.

Every other case passed all three trials. Original verdicts are retained without overrides or relabeling. This run measures variation from fresh assistant, actor, and judge calls together; it does not isolate judge randomness from response variation. Two runs are insufficient to estimate stable pass³ reliability, and the previously exposed held-out cases remain exposed.

## Evidence

- [Previous comparison](critical-pass3-comparison-final.md).
- [Repeat report](runs/16a85f8a8b080163eeb8c99254c60bdab98376dc80ad454dfbc36e6213208862/report.md), with journal, manifest, and hashes alongside it.
- Repeat evidence SHA-256: `9f24434b203a3451f35c0d5277ee2d6bf9001265c39d08117b6e8745c62658fd`.
- Evaluated checkout: `d0b306d`. It differs from the previous evaluated checkout only by retained evidence and documentation. Harness and application contract identities match; checkout/artifact hashes differ accordingly.
- Calibration 18 / policy 1.0.4 remain approved with the documented wrong-route Outcome disagreement and unchanged numeric thresholds.

Archive replay validation and secret scanning passed. No application or evaluation fixes were made during this measurement run. Registries and production qualification remain unchanged.

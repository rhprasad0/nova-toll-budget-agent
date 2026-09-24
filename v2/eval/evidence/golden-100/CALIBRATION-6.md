# Calibration before the corrected baseline

**132/132 references measured; all 132 actor-validity labels match.** This run uses contract 3.0.4 / harness 2.0.11, Strands Evals 1.4.0, and 16 workers. The 120 previous references retain their labels; 12 new regressions cover the first baseline's actor and application-stop findings.

- **386/387 application labels match (99.7%)**. One previously observed Grounding disagreement remains; no negative control passes overall.
- **129 valid and 3 invalid actor labels are correctly classified.** The nine application-stop regressions run with live termination semantics. Three invalid controls cover premature stopping, an empty continuation, and rejecting a required alternative.
- All 396 judge calls have known usage. No measurement failures or retries.
- Calibration cost: **$0.22172372**. Cumulative experiment spending, including both the first baseline and the actor preflight: **$2.16288238 of $25**.

Before calibration, **9/9 targeted live actor checks passed**: three fresh actors each for cases 23, 58, and 83, using the application questions/answer that exposed the first-baseline defects. That preflight cost **$0.01129344** across 27 model calls. It is a limited regression check, not an estimate of general actor reliability or application performance. Its [manifest](actor-preflight-1/manifest.json) includes the exact scripted exchanges; [report](actor-preflight-1/report.json) and [receipt](receipt-actor-preflight-1.json) retain all results.

The remaining disagreement is the case 68 negative control, `dev3-range-becomes-user-chosen-salary-salary-chosen-before-consent`: Grounding accepts a salary chosen by the assistant because the user later confirmed it. The authored Grounding failure remains unchanged: later confirmation does not erase the earlier unsupported choice. Outcome and Rules both reject the control. This is retained judge variability, not a repaired or discarded measurement.

Ryan authorized the fixes and subsequent baseline in the conversation. Codex checked the new evidence under that standing instruction; Ryan has not separately reviewed these new measured verdicts. The [execution review](calibration-6/review.json) records that distinction and the retained disagreement. This approval is limited to the requested development baseline; application results and production qualification remain unapproved.

Raw evidence: [report](calibration-6/report.json), [reference checklist](calibration-6/report.md), [events](calibration-6/events.jsonl), [manifest](calibration-6/manifest.json), and [receipt](receipt-6.json). The raw report retains its original pending-review state; the execution review is a separate artifact. Source commit: `0bf8c7ebcab9dd8248dfe748cc7103e90b83848c`.

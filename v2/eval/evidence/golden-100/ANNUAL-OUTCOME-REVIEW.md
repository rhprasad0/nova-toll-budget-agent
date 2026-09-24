# Annual Outcome review — 24 September 2026

Ryan requested a more lenient Outcome judge after reviewing **Gallows hybrid salary (case 52)**: the answers already contain substantial numerical detail.

Contract **3.0.5 / harness 2.0.12** applies this rule consistently to all 60 annual and mixed cases:

- A P50 daily/annual toll summary with P25/P50/P90 combined-cost scenarios is sufficient. Separate P25/P90 toll amounts are optional unless explicitly requested by the delivered user.
- For observed-only annual evidence, a clear description of recent historical samples/scenarios identifies the source. The exact word "observed" is not required. Applicable modeled/fixed-rate disclosures remain required.
- Wrong amounts, misleading labels, contradictory source claims, missing material assumptions or limitations, and unauthorized tool behavior still fail the applicable criteria.

This keeps the existing annual affordability summary and scenarios; it removes the demand for additional toll-only figures. The application prompt and model are unchanged.

| Case 52 trial | Recorded baseline Outcome | Proposed Outcome under the revised contract | Reason |
| --- | --- | --- | --- |
| 1 | Fail | Pass | P50 tolls and all combined-cost scenarios are present; extra P25/P90 toll figures are optional. |
| 2 | Fail | Pass | The historical-source explanation is sufficient in context; the judge need not demand an exact source keyword. |
| 3 | Fail | Fail | The answer explicitly denies that the historical observations are observed tolls, contradicting the evidence. Grounding also fails. |

These are **new reference expectations, not measured calibration results**. The three exact transcripts, tool records, and actor replies are appended to [examples.json](../../golden/examples.json) with review rationales. All 132 earlier references and their labels are retained. Rules remains passing for these three references; the actor and permitted tool workflow are unchanged.

Offline validation checks all 100 cases and 135 references, preserves the three transcripts against the archived baseline, and verifies the proposed pass/pass/fail Outcome boundary. Fresh calibration is still needed to measure the judge's behavior on this revision. No new paid run or baseline rescore was performed.

The [baseline 2 report](BASELINE-2.md), [full static review](baseline-2-review.html), [10-case review](baseline-2-sample-review.html#case-52), raw evidence, and receipts retain the measured **176 passed / 123 failed / 1 inconclusive**. These measurements belong to contract 3.0.4 / harness 2.0.11.

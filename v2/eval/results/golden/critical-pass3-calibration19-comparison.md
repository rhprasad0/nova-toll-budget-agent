# Calibration 19 — fresh reference and candidate comparison

**Both runs scored 15/17 critical pass³ and 70/72 overall. The three cases targeted by the fixes passed all nine trials in each run.** This comparison does not demonstrate a net pass³ improvement or stable 17/17 performance.

Ryan approved calibration 19 and policy 1.0.5 before execution. Both runs use corpus 1.0.15, harness 1.2.5, the same model/settings, actors, fixtures, judges, and unchanged numeric thresholds. The reference uses application prompt 2.3.4; the candidate uses 2.3.5. Evaluation changes are shared, so gains from corrected grading are not attributed to the application wording change.

| Metric | Reference 2.3.4 | Candidate 2.3.5 |
| --- | --- | --- |
| Critical pass³ | 15/17 | 15/17 |
| Critical successful trials | 49/51 | 49/51 |
| Overall successful trials | 70/72 | 70/72 |
| Overall pass³ | 22/24 | 22/24 |
| Invalid trials | 0 | 0 |
| Model cost | $0.39115266 | $0.39666027 |
| Latency median / p95 | 18.01s / 31.78s | 17.74s / 34.91s |
| Salary-range trials | 3/3 | 3/3 |
| Invalid-schedule trials | 3/3 | 3/3 |
| Unavailable-return-route trials | 3/3 | 3/3 |

## Remaining recorded failures

All four failures below are in critical cases. Their recorded scores remain unchanged.

Reference:

- `greenway-current-3`: Grounding rejected the two-axle passenger profile because the user only supplied E-ZPass. The application explicitly defaults to that profile when none is supplied; the judge context describes supported profiles without explicitly establishing that default.
- `annual-confirm-divergent-2`: Grounding rejected the “Tysons” qualifier added to Westpark Drive as unsupported in the conversation. This exposes another geographic-context sensitivity.

Candidate:

- `i66-stale-price-3`: Grounding rejected “Observed: 7:00 AM EDT” because the source is 7:00:30 AM EDT. The application explicitly requires minute precision. This is an apparent disagreement between the display contract and judge context, not the earlier wrong-hour error.
- `annual-no-paired-days-3`: Grounding rejected “validated priced toll-facility endpoints” because the result's facilities list was empty. The response otherwise reported only supported baseline amounts and correctly disclosed missing history. Its scope wording follows the application's straight-line priced-leg convention, but the judge considered validation/pricing unestablished by this result.

The candidate contains only the requested application wording fix; these newly observed issues were not patched or relabeled during the comparison. The absence of failures in the targeted cases is encouraging regression evidence, not proof that those behaviors are reliable across all phrasing. Fresh actor, application, and judge calls vary together. Nominal held-out cases have already been exposed during development.

## Validation and evidence

- Calibration: 165/165 labels agree; [approved review packet](../../evidence/critical-pass3/REVIEW-19.md).
- 65 focused tests plus all 47 gate tests passed after approval. Contract-version and lint checks passed. The original failed salary-bullet transcript now passes the deterministic checker; negative checks still reject invented amounts and calls before consent.
- [Reference report](runs/3ccef07084456a1531d57f6ceefc51438b4b005c3c2bc58667d38e0e683d147a/report.md), evaluated commit `9326227`; evidence SHA-256 `b09df36568f71a05dc54d6027ded0cf72deca96a633cfa791bab476c111e8a75`.
- [Candidate report](runs/70daff7d51fa6df7c6e961ee1e2a94c00470fc4785da75738a44e23eb3fd62cc/report.md), evaluated commit `4b21941`; evidence SHA-256 `6e5188e299ce01cf73c319e6b60efb10643e4133a010463585c8e86e296085ad`.
- Both archives passed journal replay validation and secret scanning. Linked cumulative spending is $6.43513216, including prior recorded spending; this is not invoice reconciliation.

Historical runs remain archived under their original contracts. These source-checkout runs do not qualify a production artifact; both miss the critical threshold. Production registries remain unchanged. No push, PR, merge, or deployment was performed.

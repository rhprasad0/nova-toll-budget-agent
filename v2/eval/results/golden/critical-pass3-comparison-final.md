# Critical pass³ — final comparison

**Subsequent repeat:** the unchanged candidate scored **16/17 critical pass³ and 68/72 trials**. See the [repeat analysis](critical-pass3-repeat-1.md); the passing run below is not consistently reproduced.

**Prompt 2.3.4 meets the observed target: 17/17 critical cases pass all three trials (51/51), and all 72/72 trials pass.** The unchanged application reference scored 9/17 critical pass³ under the same evaluation contract: an observed increase of 47.1 percentage points.

All runs below use corpus 1.0.14, harness 1.2.4, approved calibration 18 / policy 1.0.4, unchanged numeric thresholds, and the same model/settings, actors, fixtures, and graders. The application model remains `gpt-5.6-luna`. Each candidate was a fresh full run after a prompt change; failed attempts remain archived and contribute to the spend ledger.

| Metric | Reference 2.3.0 | Candidate 2.3.2 | Candidate 2.3.3 | Final 2.3.4 |
| --- | --- | --- | --- | --- |
| Critical pass³ | 9/17 | 16/17 | 15/17 | 17/17 |
| Critical successful trials | 41/51 | 50/51 | 48/51 | 51/51 |
| Overall successful trials | 55/72 | 70/72 | 69/72 | 72/72 |
| Invalid trials | 0 | 0 | 0 | 0 |
| Model cost | $0.38954192 | $0.39747145 | $0.39428715 | $0.40004660 |
| Latency median / p95 | 18.17s / 27.92s | 17.56s / 27.14s | 17.83s / 30.69s | 17.08s / 27.05s |

## What changed

Measurement corrections retain initial user facts in actor context, correct the divergent route expectation, recognize bounded conditional income choices and explicit zero denials, and reject schedule prices mislabeled as observations. These changes were calibrated separately; their gains are not attributed to the application. Actor validation passed 60/60.

The application prompt distinguishes published rates from observations, preserves observation clock times, labels annualized daily scenarios correctly, reports coverage counts and percentages, asks for annual income without inventing an hourly conversion, and handles unavailable results without unsupported alternatives or partial affordability arithmetic. Unsupported-profile refusals retain the requested trip context; execution errors receive a brief retrieval-failure explanation.

Candidate 2.3.2 missed one stale timestamp and one tool-error response. Candidate 2.3.3 fixed both, but the Outcome judge rejected two valid generic vehicle refusals for omitting route names, and one no-history response invented a remaining-income amount. The final prompt adds refusal context and explicitly limits no-history responses to returned baseline amounts. Original scores and judge evidence are preserved, including questionable verdicts.

## Per-case successful trials

Each cell is successful trials out of three.

| Case | Critical | Reference | 2.3.2 | 2.3.3 | 2.3.4 |
| --- | --- | --- | --- | --- | --- |
| greenway-current | Yes | 1/3 | 3/3 | 3/3 | 3/3 |
| greenway-origin-correction | Yes | 1/3 | 3/3 | 3/3 | 3/3 |
| unsupported-profile | Yes | 2/3 | 3/3 | 1/3 | 3/3 |
| greenway-missing-destination | No | 1/3 | 3/3 | 3/3 | 3/3 |
| i66-no-comparison | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| i66-missing-price | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| i66-observed-price | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| i66-free-period | Yes | 2/3 | 3/3 | 3/3 | 3/3 |
| i66-stale-price | Yes | 3/3 | 2/3 | 3/3 | 3/3 |
| current-tool-error | No | 3/3 | 2/3 | 3/3 | 3/3 |
| unsupported-origin | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| annual-fixed | Yes | 2/3 | 3/3 | 3/3 | 3/3 |
| annual-tysons-clarification | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| annual-missing-schedule | No | 1/3 | 3/3 | 3/3 | 3/3 |
| annual-salary-range | No | 1/3 | 3/3 | 3/3 | 3/3 |
| annual-hourly-income | No | 2/3 | 3/3 | 3/3 | 3/3 |
| annual-confirm-days | No | 3/3 | 3/3 | 3/3 | 3/3 |
| annual-invalid-schedule | No | 3/3 | 3/3 | 3/3 | 3/3 |
| annual-no-return-route | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| annual-partial-history | Yes | 2/3 | 3/3 | 3/3 | 3/3 |
| annual-independent-ramps | Yes | 2/3 | 3/3 | 3/3 | 3/3 |
| annual-select-alternative | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| annual-confirm-divergent | Yes | 3/3 | 3/3 | 3/3 | 3/3 |
| annual-no-paired-days | Yes | 2/3 | 3/3 | 2/3 | 3/3 |

## Evidence and limits

- [Exact calibration-18 review](../../evidence/critical-pass3/REVIEW-18.md): 158/159 criterion labels agree. Ryan approved the recorded wrong-route Outcome disagreement; its expected FAIL label is retained, while Rules and deterministic checks reject it. Policy 1.0.4 does not loosen numeric thresholds.
- [Earlier calibration-16 comparison](critical-pass3-comparison-1.md): retained separately because its measurement contract differs. The original 12/17 baseline also uses a different contract and is not a like-for-like comparator.
- [Reference 2.3.0 report](runs/02821b32c00f57d78252f4d9e85f62778732339c371a4836a1da7d26953bcc0d/report.md).
- [Candidate 2.3.2 report](runs/9668f143ff706625975bdb73a9005edd72e1107b56a995cc2e4bb85704372de2/report.md).
- [Candidate 2.3.3 report](runs/0cf99bd6f551d6e8c2aa0c6a245d4bc4ed6fcb747178a924ea05a152230f738d/report.md).
- [Final 2.3.4 report](runs/92f86a6c7b84ceffeb22cf0d660c2dc97d6253b8b343fdd484c6a49e14da8ab2/report.md).

Each report has its immutable journal, manifest, and file hashes alongside it. Final evaluation source commit: `193dc3b`. Final evidence SHA-256: `f129d038b257f4e4f4ce366f60c1d330cd2df3021fbc3d6a3bd17a07b4b75b20`. Final run cost is $0.40004660; its linked cumulative ledger is $5.12597397, including prior recorded spending. This is not a provider invoice reconciliation.

Three trials per case are regression evidence, not proof of perfect underlying reliability. Repeated development has exposed the nominal held-out cases; this is not untouched holdout evidence. Semantic judges remain stochastic. Bounded monetary syntax can still reject safe unrecognized wording (the reference's “does not mean tolls were $0” is one example); that reference trial also lacked required coverage. These limitations are not erased by the final passing run.

Validation: 147 relevant corpus, runner, baseline, gate, and prompt tests passed; the agent contract version check passed. Archived evidence passed secret scanning. Intermediate prompt releases remain in historical commits and run manifests; 2.3.4 is the single new release in the final application contract.

This is source-checkout evidence, not exact-artifact production qualification. Production references and registries remain unchanged. No push, PR, merge, or deployment is authorized or performed.

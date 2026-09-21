# Calibration 21 — exact review packet

**Pending approval: 180/180 criterion labels agree across 60 development examples.** Application prompt 2.3.5 and model settings are unchanged. These are evaluator-context corrections, not application quality improvements.

## Corrections and evidence

- **Observation precision:** exact seconds and minute precision are both valid for grading. Omitting seconds does not permit rounding or substituting evaluation time. The new correct-minute example passes; the wrong-minute example fails Outcome, Grounding, and Rules. The application still requests minute precision for display.
- **Distance baseline:** annual route validation precedes distance calculation. A returned `straight_line_priced_facility_legs` / `tolled_portions_only` baseline supports validated priced-endpoint wording even when the historical facilities list is empty. Missing historical tolls and combined totals remain unavailable.
- **Default profile:** the application's two-axle passenger/E-ZPass/toll default is supported when the user supplies no different profile. Explicit incompatible user input still requires refusal.
- **Catalog location:** Westpark Drive's supplied alias includes Tysons Corner. This permits the location qualifier without permitting silent resolution of ambiguous bare Tysons requests.

All five new examples are development examples. They use the observed-price case for timestamp precision and the Tysons-clarification case for location wording; held-out cases remain excluded from calibration. Actor code, profiles, original scripted examples, and application code are unchanged, so the approved actors-2 60/60 evidence remains applicable.

Calibration 20 is retained but not approved: one judge treated minute precision as mandatory and rejected an accurate seconds-inclusive timestamp. Calibration 21 explicitly permits both accurate forms. No old labels or verdicts were overwritten, and its cost remains accounted for.

## Exact identities

- Corpus **1.0.17**, harness **1.2.7**, policy **1.0.6**.
- [Calibration report](calibration-21/report.md) and [file hashes](calibration-21/hashes.json).
- Calibration evidence: `82918bdb8d8714bc28e702bb3b65df34a23c700a6181ea71d2f0ffd05a0a3234`.
- Evaluation contract: `6cfb8e641bbf539d3b57dfa69f22f89e7a584de026729acebbdccf5f1d211238`.
- [Policy 1.0.6](../../results/golden/policy-1.0.6.json) digest: `921a8b239fcd469054e515807e6dec96b1c5ef1c8954d7f272bbae1860384f7b`.
- Every numeric threshold matches policy 1.0.5. No critical pass requirement, allowance, or budget was relaxed.
- Evaluated source: `cc82485`. Calibration cost: $0.15296600. Linked cumulative ledger: $6.74292776, including prior recorded spending.

## Requested approval

Approve calibration 21 and policy 1.0.6 with unchanged numeric thresholds to permit the requested fresh full-suite rerun of unchanged application prompt 2.3.5. The runner's `main` calibration check in `v2/eval/golden_run.py` requires human approval of this exact evidence before scored execution. Previous approvals are preserved for their historical contracts.

A better score under this changed evaluator is a measurement change, not evidence of an application improvement. Semantic judges remain stochastic, nominal held-out cases are exposed, and three trials do not establish stable perfect reliability. Approval does not authorize push, PR, merge, deployment, or production qualification.

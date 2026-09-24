# Calibration 2 review — contract 2.0.4

**All 281 development examples completed. All seven new case-16/18/20 controls matched their labels.**
There are 13 disagreement examples elsewhere in the retained calibration set and no incomplete measurements.

[Full report](report.json).

- Estimated model cost: **$0.440764625 of the $5 cap** across 843 fully accounted model calls. No automatic reruns.
- Offline validation: 80 relevant tests passed; targeted Ruff and Pyright checks passed.
- Exact evaluated commit: `cdf26d222e1de2ac8d3175738e39df614c1de6b4`.
- Evidence digest: `8cb32297a8edd1463a34b7b9a9bbbfe52fceb746b2ed2ebe7c6ded395a8612c0`.
- Human review: **pending**. Neither application evaluation nor production promotion was performed.

## Corrections and limits

1. Case 16: the money checker accepts explicit downward-dollar wording; wrong direction and invented amounts still fail. The three new movement controls agree with their expected labels.
2. Case 18: current-only scope refusals need no pricing-tool evidence, but accompanying factual price claims still do. Its exact case remains reserved; two development future-price controls exercise the same rule without changing the split.
3. Case 20: actor instructions explicitly require a nonempty continuation or JSON null completion. Empty replies still invalidate the measurement without retry. Both fixed-reference actor controls are classified correctly. No fresh live actor run was made, so this does not establish a reduced live actor error rate.

The original 2.0.3 calibration and 600-trial application archive remain unchanged. An authored null-completion control does not repair the historical empty-actor trial. Calibration measures judge agreement on labeled examples, not TollChat accuracy.

## Remaining disagreements

| Example | Criteria |
| --- | --- |
| current-washington-corrective-retry-good | outcome |
| current-comparison-zero-baseline-good | outcome |
| current-suffix-decline-good | grounding |
| current-suffix-accept-good | outcome |
| current-comparison-partial-partial-comparison-called-typical | grounding |
| current-fallback-withdrawal-latest-user-refusal-overridden | grounding |
| annual-salary-range-good-midpoint-choice | outcome |
| annual-salary-range-assumed-midpoint | actor_validity |
| annual-washington-both-correct-once-good | rules |
| annual-history-proof-limits-good | outcome |
| annual-share-over-hundred-good | outcome |
| annual-vehicle-rate-not-tax-rule-good | outcome |
| annual-personal-vehicle-rate-good | grounding |

Inspect the actual conversations and judge explanations in the raw report before adjudicating. No verdicts were changed to obtain agreement.

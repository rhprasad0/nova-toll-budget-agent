# Calibration 19 — review packet

**Approved by Ryan for fresh comparisons. All 165/165 criterion labels agree across 55 development examples.** This contract fixes the two evaluator gaps exposed by the unchanged-candidate repeat. Numeric release thresholds are unchanged.

## Changes ready for review

- Corpus 1.0.15 / harness 1.2.5 recognizes currency-only bullet choices after an explicit income-selection question. Only supplied endpoints and their midpoint are exempted; invented amounts, affirmative income assumptions, other monetary claims, and calls before consent remain rejected.
- The judge receives the application's annual input limit: 53 times the selected weekday count, or 265 for Monday–Friday. This is a validation bound, not permission to assume or silently cap the user's planned days.
- Two added development examples pass Outcome, Grounding, and Rules: `annual-salary-range-good-income-bullets` and `annual-confirm-days-good-annual-day-limit`. The day-limit example uses an existing development case; held-out cases remain excluded from calibration.
- Candidate application prompt 2.3.5 describes only the unavailable requested round trip, without generalizing to tool-wide claims about one-way estimates or alternative routes. The application model is unchanged.

## Exact evidence

- [Calibration report](calibration-19/report.md) and [file hashes](calibration-19/hashes.json).
- Calibration evidence SHA-256: `e856114529056e2b544f81c7c74f57302e61e300e5b7d9fb28953b867619f72c`.
- Evaluation contract SHA-256: `c4f686bb425dd7a1589736d80b9c35bbbc57465eddeac41f7d6821a4ed038668`.
- [Policy 1.0.5](../../results/golden/policy-1.0.5.json), unchanged numeric thresholds. Policy digest: `a09e624306cacd2f67b7c17c22f6ee005a31cad48420d1d6c520f5a2780a7738`.
- Calibration evaluated source commit `4314e13`; cost $0.13117400; linked cumulative spending $5.64731923.
- Actor prompt and case identities match the previously approved actors-2 evidence (60/60). Actor implementation and original scripted good examples are unchanged; no new actor approval is requested.

There are no disagreements in this calibration. The original wrong-route Outcome FAIL label is unchanged and the judge agreed on this run. Calibration 18's recorded disagreement and approval remain preserved in their original evidence; this clean calibration does not eliminate known judge variability.

## Approval scope and next comparison

Ryan approved this exact calibration evidence and policy 1.0.5 to permit fresh full reference/candidate comparisons under the changed evaluation contract. The reference should retain prompt 2.3.4; the candidate uses 2.3.5. This separates evaluator corrections from the application wording change. Historical scores will not be relabeled or compared as if their contracts were identical.

The runner enforces exact-evidence human review before scored runs (`v2/eval/golden_run.py`, `main`, calibration approval check). Approval does not authorize push, PR, merge, deployment, or production qualification. Three trials remain regression evidence, and the nominal held-out cases have already been exposed during development.

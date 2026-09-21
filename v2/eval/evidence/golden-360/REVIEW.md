# Evaluation evidence

Start with the [engineering summary](../../GOLDEN_VALIDITY_REVIEW.md).

- [Calibration 15](calibration-15/review.html): approved active evidence, with
  138/138 criterion agreement across 46 development examples. Its raw files and
  exact approval are required by the release gate.
- `calibration-7/` and `demo-1/`: historical regression fixtures used by the
  baseline tests. They do not qualify production.
- [Historical demo review](DEMO_REVIEW.md): supports the retained initial-baseline
  review record.

Superseded calibration logs and duplicate reports were removed from the current
tree. Git commit `0336ddf` retains the full history, including failed attempts.

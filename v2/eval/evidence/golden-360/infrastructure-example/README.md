# Offline infrastructure-error example

This is a synthetic report-contract demonstration, not a model evaluation. It copies the real demo candidate identity, selects one case, injects one infrastructure failure, and leaves two trial slots unstarted. No model or pricing calls occurred and cost is zero. It is separate from all paid-run lineage and results.

The generated JSON reports incomplete evidence, zero successful trials, no confidence interval, and no release decision. Missing or failed infrastructure cannot yield a passing report.

Regenerate from `v2/` with:

```sh
uv run python -m eval.golden_run render --output eval/evidence/golden-360/infrastructure-example
```

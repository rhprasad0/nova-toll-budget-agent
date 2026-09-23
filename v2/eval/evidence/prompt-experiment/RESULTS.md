# Prompt comparison: incomplete full evaluation

The 26-case diagnostics are complete. The full evaluation is paused because the
development AWS SSO session expired near the end of B. **No winner is established.**
All application variants and evaluator settings remain frozen; no prompt revision
was made after diagnostics.

| Stage | A baseline | B descriptions | C descriptions + reordered SOP |
| --- | --- | --- | --- |
| Diagnostics: passed / scored | 55 / 75 (73.3%) | 57 / 73 (78.1%) | 58 / 75 (77.3%) |
| Diagnostic inconclusive trials | 3 | 5 | 3 |
| Full run: passed / scored | 402 / 582 (69.1%) | 400 / 544 (73.5%), partial | No measured trials |
| Full run: inconclusive / infrastructure | 18 / 0 | 14 / 42 | 0 / 600 |

On 22 complete paired diagnostic cases, B and C each gain only 1.5 percentage
points over A; both intervals span losses and gains. On the 168 currently complete
paired full-run cases, B gains 2.2 points, with a 95% scenario-group interval of
-2.2 to +6.7 points. This incomplete comparison cannot establish superiority;
reserved cases show -2.7 points on 37 paired cases, also inconclusive.

See [diagnostics](DIAGNOSTIC-COMPARISON.md) and the
[partial full comparison](FULL-COMPARISON.md) for family results, uncertainty,
latency, token usage, violations, costs and links to every raw trial.

## Interruption and recovery

All 42 B infrastructure failures and all 600 C infrastructure failures are
`TokenRetrievalError` from expired development AWS SSO credentials. B had one
failure during judge setup and 41 before application execution; C made no paid
model calls. Every started model call has a completed usage record. Total
cumulative spending is **$7.704711 of $15**, leaving **$7.295289**.

After SSO renewal, recover only the 14 B cases listed in
[full-b-recovery-cases.json](full-b-recovery-cases.json) (42 infrastructure-failed
trials), then run C's 200 cases / 600 trials. All trials in those B cases failed
infrastructure; none of B's scored or actor-inconclusive trials should be retried.
Use fresh output directories, the same frozen commits and matching approved
calibrations, four workers, and the $15 cumulative limit. Chain B recovery from
C's zero-cost interrupted full run, then C recovery from B recovery. Preserve the
original journals and separately label recovery results; account for both original
and recovery costs. Stop the sequence on renewed infrastructure failure rather
than starting another arm with expired credentials.

## Measurement caveats

The calibrated judge still has documented reading and classification errors.
Diagnostics also exposed a deterministic money-check false failure: a supported
positive magnitude such as '$1.75 below' can be rejected against a negative
comparison field. Scores are retained unchanged; no favorable relabeling or
retry-until-pass was performed. Small score changes need this qualification.
Reserved cases are public, not a secret independent holdout. No deployment or
release decision is authorized by these results.

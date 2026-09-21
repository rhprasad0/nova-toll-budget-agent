# Evaluator caching — exact review packet

**Historical packet; superseded by [REVIEW-24.md](REVIEW-24.md).** Its contract and approval request are no longer current.

**Implementation complete; human approval pending.** Four-worker calibration 22 agrees on **180/180** labels; actor checks pass **60/60**. Eight-worker calibration 23 agrees on **179/180**, so retain four workers. No new application-scored run has started.

## PR scope and CI follow-up

The PR is now strictly eval harness/gate work. Earlier application prompt edits
were removed from its diff; the application's prompt, model, contract, and tests
match main (prompt 2.3.0). The measurements below retain their original source
identity and prompt-2.3.5 context; they contain no application calls and their
judge/corpus contract remains unchanged. Historical application-scored runs are
not evidence for main's application behavior.

The protected CI execution path shares the cached evaluator factory and judge
with the manual runner. An offline integration check verifies cache configuration,
medium judge reasoning, four-worker execution, cache-write accounting, and ledger
settlement through that entrypoint. The gate now fingerprints the shared adapter
module; changing it invalidates the evaluator source digest. Ninety-two focused
gate, runner, and application contract tests pass. No paid CI dispatch or
application-scored run is authorized by this follow-up; exact calibration/policy
approval remains pending.

## Changes and validation

Evaluator models reuse the application's cache adapter, including cache-write usage accounting. Judge instructions, unchanged domain facts, and unchanged criterion guidance now precede variable evidence, with explicit caching and a 30-minute TTL. The medium-reasoning update preserves cache parameters. Actor prompt text, application prompt **2.3.5**, model **gpt-5.6-luna**, rubrics, examples, trial counts, and thresholds remain unchanged. Outputs are always freshly generated.

An offline capture through the actual SDK judge and structured-output tool confirmed developer prefixes of approximately 1,514 / 1,171 / 1,165 tokens for Outcome / Grounding / Rules (o200k_base count). Each exceeds the 1,024-token cache minimum without padding. The rendered request tests cover stable prefixes across cases, usage/cost accounting, preserved reasoning/cache parameters, and stale-calibration rejection. **151 relevant tests pass** across runner, simulation, corpus, baseline, and gate coverage; changed Python files pass Ruff and Pyright. Archive replay, actor journal/report consistency, file hashes, and secret scans passed.

## Measured results

Both calibration runs use the same 60 development examples, exactly 516,298 input tokens, and 180 fresh judge calls. Wall time includes process startup and final report rendering. Call latency measures individual provider streams, not application response time.

| Metric | Calibration 22: four workers | Calibration 23: eight workers |
| --- | ---: | ---: |
| Wall time | 130.67 s | 70.09 s |
| Label agreement | 180/180 | 179/180 |
| Input / output tokens | 516,298 / 40,101 | 516,298 / 39,965 |
| Cache-read / cache-write tokens | 230,513 / 3,907 | 234,420 / 0 |
| Input cost, including cache writes | $0.06196261 | $0.06106400 |
| Output cost | $0.04812120 | $0.04795800 |
| Total cost | $0.11008381 | $0.10902200 |
| Same tokens at uncached rates | $0.15138080 | $0.15121760 |
| Cache savings, including writes | $0.04129699 (27.3%) | $0.04219560 (27.9%) |
| Call latency median / p95 | 2.47 / 4.51 s | 2.42 / 4.35 s |
| Average requests/minute | 82.65 | 154.09 |
| Average visible input + output tokens/minute | 255,483 | 476,185 |
| Incomplete usage / infrastructure failures | 0 / 0 | 0 / 0 |

Eight workers were **1.86× faster (46.4% less wall time)**. The second run reused warm prefixes; the first includes initial cache writes. This ordering and stochastic generation limit causal conclusions. These averages are not peak traffic or provider quota debits. The user confirmed a shared **4M TPM** quota; no throttling was observed, but account RPM limits and rate-limit headers were not captured. No scheduler or automatic retries were added.

The four-worker actor check made 87 fresh calls in 27.80 seconds: 72,443 input tokens, 4,154 output tokens, zero cache reads/writes, $0.01947340 total ($0.01448860 input + $0.00498480 output), and 1.01 / 1.54 seconds median / p95 call latency. All 60 scripted exchanges passed, with complete usage. Short actor prompts were not padded. No application calls were made in these checks; candidate-6 remains the latest scored application evidence.

Pricing remains $0.20 input / $0.02 cached input / $0.25 cache write / $1.20 output per million tokens, verified against [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna) and [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching). Cache-write pricing replaces the uncached rate for written tokens; it is not added twice.

## Retained disagreement

Calibration 23 incorrectly passed **Grounding** for `annual-tysons-clarification-silent-modeling`. The transcript says “All prices were directly observed,” while the tool result has `uses_modeled=true`. Its grounding explanation checked the financial/schedule values but missed that false provenance claim. Outcome and Rules correctly failed the same example; calibration 22 correctly failed all three criteria.

This is a real false positive under the unchanged rubric, not a reason to relabel the example. Neither labels nor verdicts were edited, and no replacement run was used to obtain a clean eight-worker result. A single comparison cannot establish that concurrency caused the error. **Do not adopt eight workers on this evidence.** Calibration 23 remains unapproved and its miss must be visible when reviewing the proposed four-worker contract. The 180/180 four-worker result does not establish perfect judge reliability.

## Exact evidence and proposed approval

- Evaluated source: `d3cbf71`; corpus **1.0.18**, harness **1.2.8**, proposed policy **1.0.7**. All numeric thresholds, including four-worker scored timing, match policy 1.0.6.
- Evaluation contract: `c1a577f755d831d38851a588d33c761ce002d1a471d2aaab6354a6b329ef9c18`.
- [Four-worker calibration 22](calibration-22/report.md): `4837d3ab8953734912147283738ff90d297a7c9f93ffbbb9855833f61da8b8ca`.
- [Eight-worker calibration 23](calibration-23/report.md): `c38b3d2e933b699ee0cc035baaf6309675e600394995cdeb5ba481b00fd361d9`.
- [Actor checks 3](actors-3/report.json): `88664c340dcf3256ef84b262ae6732ed45b7ac8a421200b07db66ba87d064d1e`.
- [Policy 1.0.7](../../results/golden/policy-1.0.7.json) digest: `5a9cf9c6088690f47bdd271297c955a296187f5cf41c93b64dd48cbe36e454c2`.
- [Machine-readable benchmark and archive references](../../results/golden/caching-benchmark.json).

Requested review: approve calibration 22, the updated corpus, actor-check evidence, and policy 1.0.7 for a fresh **four-worker, 72-trial** application run, with explicit awareness of calibration 23's retained false positive. The existing runner and release gate require exact human approval; the earlier calibration-21 approval does not cover the changed evaluator. Pending markers remain in place. Approval would not authorize push, PR, merge, deployment, or production qualification.

Recorded spending is **$0.23857921** for this validation, with **$7.38792007 cumulative**. The ledger continues candidate-6 → calibration-22 → calibration-23 → actors-3; the actor checker carries prior spending as a number. Include actors-3 as the next `--prior-run`, even though calibration 22 is the proposed approved calibration. Older actor/judge accounting may omit cache-write charges; historical totals remain recorded estimates.

After exact approval, record that review, render only private copies, preserve the existing archived reports, commit a clean checkout, and run from `v2/`:

```sh
AWS_PROFILE=nova-toll-dev uv run python -m eval.golden_run run \
  --output eval/private/critical-pass3/candidate-7 \
  --calibration eval/private/critical-pass3/calibration-22 \
  --prior-run eval/private/critical-pass3/actors-3 --workers 4
```

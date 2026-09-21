# Handoff: evaluator caching and cost accounting

User request: “Write a handoff note for a new conversation to proceed with the caching changes, then proceed with running the eval suite.” Caching work is for the next conversation; this conversation runs the currently approved suite first.

## Checkout and authorization

- Repository: `/home/ryan/Documents/nova-toll-budget-agent`.
- Working branch: `fix/critical-pass3-candidate` in `.worktrees/critical-pass3-candidate`. All changes belong in worktrees; main is protected.
- User authorizes caching changes and necessary live model calls. No push, PR, merge, or deployment is authorized.
- Application prompt remains **2.3.5**, model **gpt-5.6-luna**. Preserve application behavior and evaluation trial counts, criteria, and numeric thresholds.
- Active approved contract: corpus **1.0.17**, harness **1.2.7**, calibration **21**, policy **1.0.6**. Calibration has 180/180 agreeing criterion labels; approved actors-2 has 60/60 checks.
- Calibration evidence: `82918bdb8d8714bc28e702bb3b65df34a23c700a6181ea71d2f0ffd05a0a3234`. See [review packet](../../evidence/critical-pass3/REVIEW-21.md).

## Findings to act on

Application caching already works. `agent/toll_agent.py::_CachedResponsesModel` puts the stable developer prompt first with an explicit breakpoint, `prompt_cache_key=tollchat-agent-v2`, explicit mode, and a 30-minute TTL. It also forwards `cache_write_tokens` into the runner's usage record.

Actors and judges use `eval/simulated.py::build_eval_model`, a plain `OpenAIResponsesModel` without this explicit cache configuration. Judge construction in `eval/golden_run.py::judge` subsequently updates params to medium reasoning. Preserve cache parameters through that update if you add them.

The installed SDK reads `cached_tokens` but drops `cache_write_tokens` in `_format_chunk`. The application adapter handles this; actors and judges do not. Fix this accounting gap before trusting savings: their current recorded cost may omit cache-write surcharges.

Measured candidate-5 usage for 72 trials:

| Role | Calls | Input tokens | Cached input | Output tokens | Recorded cost |
| --- | --- | --- | --- | --- | --- |
| Application | 179 | 5,866,052 | 5,760,970 (98.2%) | 39,419 | $0.18515685 |
| Actor | 107 | 101,785 | 0 | 5,042 | $0.02640740 |
| Judge | 216 | 592,001 | 4,661 (0.8%) | 56,279 | $0.18509602 |

The application also recorded 32,365 cache-write tokens. Total recorded cost was $0.39666027, versus $1.43285560 for the same tokens at uncached rates. Calibration-21's 180 judge calls recorded 516,298 input tokens, zero cache reads, 41,422 output tokens, and $0.15296600.

Actor/judge input caching has an ideal additional savings ceiling around $0.125 per 72-trial run before cache-write charges; realistic savings are lower. Judge caching is the first priority. Many actor requests are short; do not pad prompts solely to chase cache hits.

## Smallest useful implementation

1. Reuse the existing cache adapter or its small usage-handling pattern. Avoid changing the production application prompt or adding a generic caching framework.
2. Arrange reusable judge instructions/domain facts before variable case/transcript content and place explicit breakpoints at useful stable boundaries. Audit the installed evaluator's actual rendered request, not just the Python template. A cache key alone does not guarantee prefix reuse.
3. Keep outputs fresh: never memoize actor replies, application responses, or judge verdicts. Input-prefix caching preserves fresh sampling.
4. Verify cache-write accounting and cache params with focused offline tests. Include a check that the judge's medium-reasoning update retains cache configuration. Preserve usage completeness, spending limits, and immutable journals.
5. Measure a bounded live sample before adding broader machinery; report reads, writes, input/output costs and latency by role. Savings must include write costs.
6. Changes to evaluator source, model settings, or prompt structure change the pinned contract. Recalibrate and prepare exact evidence if required by the existing runner, retaining old labels/verdicts. Do not silently reuse calibration-21 approval for a different contract or weaken its gate. Complete implementation and review packet before requesting any new exact-evidence approval.

Current official docs were checked through Context7 and OpenAI docs:

- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching): exact-prefix matching, explicit breakpoints, 1,024-token minimum for GPT-5.6, and fresh output generation.
- [GPT-5.6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna): per million tokens, $0.20 input / $0.02 cached input / $0.25 cache write / $1.20 output. Verify current docs when implementing.

## Execution and evidence

Run commands from the worktree's `v2/` directory with `AWS_PROFILE=nova-toll-dev uv run python -m eval.golden_run ...`. Credentials come from SSM, never local secret files. Scored runs require a clean committed checkout and approved exact calibration. Link each new run to the previous run with `--prior-run`; include all usage, even failed or superseded runs.

Private approved calibration: `eval/private/critical-pass3/calibration-21`. Use the private directory when the runner renders calibration; rendering can mutate report metadata. Keep the curated archive immutable.

Archive scored runs with `golden_baseline.archive(source, golden_baseline.ROOT)`; do not use a capture operation that changes production registries. Preserve all attempts, validate journal replay, scan new archives for secrets, and document failures without overriding scores. Holdouts have already been exposed, and three trials are not proof of perfect reliability.

Prior calibration-19 comparison: both reference 2.3.4 and candidate 2.3.5 scored 15/17 critical pass³ and 70/72 overall. The later changes only align judge context with supported timestamp precision, pricing defaults, catalog locations, and validated distance baselines. Any improved score from these evaluator corrections is not an application improvement.

## Latest run

The approved-contract rerun is complete: **17/17 critical pass³, 51/51 critical trials, 72/72 overall**, zero invalid trials. See the [calibration-21 rerun report](critical-pass3-calibration21-rerun.md). Application 2.3.5 is unchanged; this is a result under corrected judging, not application improvement or proof of stable perfect reliability.

Evaluated commit `f4093e3`; private run `eval/private/critical-pass3/candidate-6`; archived evidence `98522cad7c84e23bd993c7f16d301964b2186aecb4e1a5bcc6a03ad6f8f3ae05`. Use candidate-6 as the next `--prior-run`. Run cost $0.40641310, linked cumulative ledger $7.14934086. The report includes fresh per-role caching measurements: application input 98.2% cached, actors/judges zero recorded cache reads. Archive replay and secret scans passed. No live calls remain running.

Next conversation should implement the caching/accounting changes above. No caching code has been changed yet, and no user approval question is currently pending for the completed run.

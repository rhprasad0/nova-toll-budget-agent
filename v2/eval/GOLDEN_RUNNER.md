# Running the frozen golden corpus

The manual runner executes the real candidate agent with frozen pricing evidence.
It uses the approved ActorSimulator and CorrectnessEvaluator configuration, plus
separate binary grounding and rule-compliance diagnostics. The application model,
prompt, renderer, and tool schemas stay unchanged. No database or live pricing
service is used. Model credentials come from the existing SSM parameter.

From a clean, committed checkout in `v2/`:

```bash
uv run python -m eval.golden_run calibrate --output eval/private/golden-360/calibration-1
uv run python -m eval.golden_run render --output eval/private/golden-360/calibration-1
uv run python -m eval.golden_run run --output eval/private/golden-360/demo-1 \
  --calibration eval/private/golden-360/calibration-1 \
  --prior-run eval/private/golden-360/calibration-1
```

Calibration runs the 60 development examples (180 criterion verdicts). It excludes the four held-out
examples and preserves every disagreement. Outcome labels come from the approved
corpus; the narrower diagnostic labels are proposals for human review. Calibration
is evidence about judge accuracy, not a guarantee that every later verdict is right.

Under the sampled human adjudications, Outcome can pass for a necessary
clarification awaiting the user or an honest explanation of an explicit tool
rejection, without an estimate. Incorrect arguments still fail Rules. Invented
financial or schedule facts in tool arguments fail Grounding, even if later
confirmed. Each diagnostic judge receives only its named criterion's rubric.
Actor validity still requires separate review: a passing clarification response
does not establish that the simulator completed its required exchanges.

Before calibration, `python -m eval.golden_actor_check --output DIRECTORY
--prior-spend-usd ACCOUNTED_SPEND` checks three fresh actors per development
good example against scripted answers. Actor and judge models must emit their
structured verdict directly. The judge uses medium reasoning; actor and
application reasoning remain low. Actor stops derive from a nullable message;
contradictory replies and simulator turn limits invalidate measurement. Judges
receive rejected calls separately from successful pricing evidence. See the
[validity review](GOLDEN_VALIDITY_REVIEW.md) for live results and limitations.

A human must review disagreements before execution. Record that review in the
calibration directory as `review.json`, with `status: "approved"`, the exact
`evidence_sha256` from its report, `reviewer`, and an `evidence` reference to the
conversation or review. Include adjudications and remaining limitations in that
record. Approval never changes the measured judge outputs or their agreement rate.
The run command checks that the corpus and judge configuration match calibration.

Calibration examples and conversation trials run with four workers by default.
Use `--workers 1` for sequential execution or choose 1 through 8 workers. Turns
and the three judge criteria within each trial stay sequential. Each worker has
its own agent, model clients, actor, and replay state. The manifest records the
worker count. The protected CI gate retains four workers and invokes this same
runner with an isolated packaged application. Its actor/judge calls therefore use
the same explicit 30-minute prefix caching and cache-write accounting. See the
[current caching review](results/golden/CACHING-SUMMARY.md); eight workers remain
available for diagnostics but are not the scored timing policy. Shared budget reservations include in-flight calls, and journal
writes are serialized. Interrupting a run cancels queued work, allows active calls
to finish recording usage, and prevents further calls in those trials.

Every selected case gets three fresh trial slots. With no `--cases` option, this
means 72 conversations. For a partial diagnostic run, supply stable case IDs after
`--cases`; its report identifies that it is not a complete corpus run. Preserve the
first run even if it fails. Use a new directory and `--prior-run` for subsequent
runs; never overwrite an attempt or retry a trial until it passes.

The default total spend ceiling is $25, including prior linked runs, with agent,
actor, and judge costs counted separately. Recorded prices are dated estimates,
including cache reads and writes, from the linked provider source. The meter
reserves a conservative text-input bound and the 2,048-token output cap before
each call. A missing usage record stops additional calls and makes the run
incomplete. Reconcile interrupted or unknown-usage attempts before more paid runs.

## Evidence and reporting

`manifest.json` identifies the clean candidate commit and source-checkout digest,
corpus and grader hashes, prompt renderer and rendered prompts, tool schemas,
model settings, actor profile, prices, and run lineage. It does not claim the
checkout is a deployed package. `events.jsonl` preserves attempts and usage as they
happen. `report.json` and `report.md` are derived offline and can be regenerated.

Saved conversation evidence contains user and assistant text, validated fixture
calls/results, simulator stop decisions, and short judge evidence explanations.
It excludes hidden model reasoning, credentials, headers, and provider exception
messages. Initial output stays under ignored `eval/private/`; inspect it before
committing sanitized calibration and demo evidence. Never commit local secrets.

Overall trial success requires outcome success, both diagnostic verdicts, and all
mandatory deterministic checks. Outcome-only results remain visible. Reports
separate infrastructure failures from scored agent failures and show completion
denominators. A deliberate fixture tool error tests recovery; an unexpected SDK,
provider, or harness failure is inconclusive. Agent loops and task-budget exhaustion
are scored failures. Missing measurements or identities cannot produce a pass.

Pass@1 is successful scored trials divided by scored trials. Pass³ is cases with
three passing trials divided by selected cases. Missing trials cannot count as
successes. Reports separate development, held-out, current-price, and annual cases.
The descriptive 95% interval resamples entire cases, retaining their three trials,
10,000 times with analysis seed 360. It is not an independence claim or evidence
of broad population reliability, especially for the four held-out cases.

Grounding and rule-violation rates use scored trials as their denominator; a trial
can violate both. These are not exhaustive counts of individual factual claims.
Latency is wall-clock trial time, including actor and judge work, with nearest-rank
p50/p95 and sample counts. Model-role timing and usage are retained separately.
Agent cost per success includes failed-attempt costs and is undefined at zero
successes. Zero observed violations does not imply zero underlying risk.

Review one development conversation for each of origin correction, clarification,
alternative selection, divergent-leg confirmation where available outside the
held-out set, and missing-history handling. The divergent-leg case is held out;
inspect its actor behavior only after the final run, never use it for tuning.
Record actor-caused deviations and treat affected results as inconclusive during
human interpretation. Do not silently relabel or replace the original attempts.

A local report cannot approve a release or promote a baseline. The mandatory
[protected golden release workflow](GOLDEN_RELEASE.md) authenticates qualification
and human approval. PR CI uses only offline tests and a canned packaged-agent
smoke; release-qualifying paid execution requires a protected dispatch.

## Offline checks

```bash
uv run pytest tests/test_golden_run.py tests/test_golden_corpus.py tests/test_simulated_evaluation.py
uv run pytest -q tests/test_run_evaluation.py
```

The tests cover real Strands replay, multi-turn context, fresh fixture state,
mandatory rejection checks, accounting across successes and failures, interrupted
runs, missing usage, identity validation, and held-out exclusion. Synthetic test
reports demonstrate that an infrastructure error cannot yield a passing decision.

The [golden baseline policy and archive](results/golden/README.md) preserve the
initial run, define the approved comparison limits, and provide a static HTML
review page. Baseline qualification is offline; the protected workflow supplies
production authorization and provenance enforcement.

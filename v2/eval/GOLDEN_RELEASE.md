# Golden production gate

**Current status:** production golden qualification remains blocked. The new
3.0.2 corpus is development-only and cannot qualify production, even with a
historical approved policy. It has no approved calibration reference or human
corpus approval. Independent holdout scope, a new protected policy, and fresh
qualification evidence require separate review. See the
[authoring guide](GOLDEN_EVAL_SPEC.md).

## Historical protected-release procedure

The counts, versions, approvals, and activation steps below are historical; they
do not authorize production use of the 100-case development corpus.

Production planning requires a successful protected golden evaluation of the
exact development release bundle. The gate is mandatory. Missing infrastructure,
an unset production baseline, pending reviews, stale evidence, or a failed run
blocks planning before production credentials are available.

Production qualification remains **blocked until a production reference passes**.
The active corpus, harness, and policy are **2.0.3**. They cover **200 cases**:
160 development and 40 public, authorship-exposed reservations. The new corpus,
calibration, and policy require exact human review; their approvals are pending.
The application model and prompt remain unchanged in this expansion.

Two local calibration passes completed within a **combined $25 ceiling**;
their [raw reports and adjudication proposals](evidence/golden-200/CALIBRATION.md)
remain pending human review. They measured contracts 2.0.0 and 2.0.1. The final
2.0.3 GPT-6 Luna migration requires fresh
authorized exact-contract calibration. No protected application execution,
production qualification, or policy limit increase is authorized by those runs.

Historical 24-case measurements, including the PR #581 packet's 179/180
calibration agreement, 60/60 actor checks, and 72/72 application trials, retain
their original identities and semantics. They are historical evidence, not
measurements of the expanded corpus. See the
[historical review packet](results/golden/CACHING-SUMMARY.md).

CI uses the same cached actor/judge factory and judge-prefix construction as the
manual runner, through scripts.golden_release.execute → eval.golden_run.execute.
There is no separate CI caching implementation. Cache reads and writes are included
in its existing journal and shared spending ledger. The gate fingerprints the
shared cache adapter as well as the evaluator source, so adapter changes invalidate
receipts and calibration identity. The cached factory lives only in golden_run;
scheduled checks retain their existing factory. Application calls still execute
the exact packaged artifact in isolation.

Historical calibration approvals and source-checkout application results remain
archived. They do not approve this changed evaluator, qualify the current
production artifact, or establish perfect judge reliability.

## Execution and evidence

`v2-golden-evaluation` runs only from main. Select `candidate` and the successful
development delivery run ID. The resolver verifies development provenance and
selects its immutable artifact ID, digest, and commit. The evaluator downloads
and verifies that bundle without rebuilding it. An ARM64 Python 3.13 child
imports the packaged application and dependencies with isolated Python startup;
the trusted parent runs ActorSimulator, the correctness judges, and frozen tool
replay. The child receives no AWS or GitHub credentials. The application model
and prompt remain unchanged.

Each execution includes all 200 cases, including the 40 reserved cases, with
three fresh trials per case: **600 conversations**, using four workers. Every
model call reserves against one shared $5 run ceiling before starting. The durable ledger also reserves against
the existing $25 authorization. Missing usage stops further paid calls and
blocks subsequent runs until spending is reconciled. Provider retries are off.

The evaluation job has a **90-minute timeout** and requests a **7,200-second
evaluator session**. The evaluator role alone permits that session length;
other golden roles retain one hour. The measured capacity estimate is about
61 minutes before setup and archival, exceeding the previous 45-minute job and
one-hour credentials. This is execution headroom, not a relaxation of
the cost or per-trial latency policy. See the
[timing calculation](evidence/golden-200/CALIBRATION.md#protected-workflow-capacity).

The numerical thresholds from policy 1.0.0 remain unchanged in policy 2.0.3,
including the **$5 protected-run ceiling**, critical/noncritical pass requirements,
suite floors, regression limits, and latency limits. Expansion does not establish
that 600 conversations can meet those limits. Any later policy change requires
its own review; no limit is silently raised here.

The corpus contains 326 reference examples; calibration selects 274 development
examples and excludes 52 reserved examples. Application labels are explicit per
criterion, and invalid actor examples have no application labels. Calibration
reports include criterion and actor-validity confusion matrices, disagreements,
and measurement-failure counts. Earlier approvals apply only to their original
contracts.

The 2.0.x assessment separates application outcome from actor validity. Invalid or
uncertain simulations and missing judgments are inconclusive. Consent is judged
from the latest messages delivered before each call; private actor facts and
later approval cannot authorize earlier action. Honest agent-caused errors and
unfinished clarifications receive no blanket Outcome exception. Family reports
retain scored and inconclusive denominators, and uncertainty resamples whole
scenario groups. Full qualification still requires all 600 valid scored trial
slots; missing measurements cannot produce a pass.

After machine qualification, inspect the `golden-evidence-RUN-1` artifact:
`review.html`, `decision.json` (including per-case baseline deltas), and the
packet's report, journal, calibration, identities, and execution declaration.
Review the eight selected transcripts, actor validity, critical failures,
held-out exposure, resource totals, and unresolved findings. Approving the
`golden-review` environment attests that this review is complete and no findings
remain unresolved. It cannot override a failed machine decision.

The resulting receipt binds the actual GitHub approval, completed trusted
workflow, evaluator source hashes, candidate artifact, policy, baseline,
report, model/settings, prompts, tool schemas, and actor/judge contract.
Candidate evidence expires after 24 hours; production reference evidence after
30 days. Changed configuration or identity requires qualification again.

Production admission reads the versioned S3 reference under a development-only
reader role. Planning, preparation, and promotion retain the same receipt in
the saved plan and revalidate it. Existing production approval, cutover approval,
migration controls, exact-plan apply, and canary checks still apply.

## Activation prerequisites

These are the activation and recovery requirements. The existing bucket,
environments and ledger are initialized. This expansion additionally requires
applying the reviewed development IAM change that permits the evaluator's
7,200-second session; this PR does not deploy it. New-contract calibration approval
and the first qualified production reference remain required. Keep these checks
for future contract changes and environment recovery.

1. Provision `infra/golden_eval.tf` in development account `903859731897`. The
   private bucket is encrypted, versioned, protected against destruction, and
   has no lifecycle expiry. Workflow roles cannot delete evidence. Evaluator,
   reviewer, reader, and publisher have separate write scopes; only the
   evaluator can read the fixed development OpenAI parameter. They have no
   production role, database permission, or network path to a database. Before
   activating this workflow, apply and verify the evaluator role's
   `max_session_duration = 7200`; the workflow requests that duration so SSM
   reads, final spending settlement and evidence archival can finish.
2. Create `golden-evaluation`, `golden-review`, `golden-read`, and
   `golden-baseline` environments. Each must allow only the `main` branch with
   administrator bypass disabled. Require Ryan's approval on the first two;
   the latter two perform bounded automated reads/publication. With a sole
   maintainer, allow that reviewer to approve their own dispatch. Keep the
   existing repository-ID-bound OIDC subject template. Require the new
   `golden-artifact-smoke` CI check alongside existing checks.
3. Once, under a reviewed development administrative session, run
   `uv run python -m scripts.golden_release initialize --directory /tmp/golden-init`
   from `v2/`. Conditional writes retain the original archive, initialize an
   unset production reference, and seed known spending at **$0.87191346**.
   Repeating initialization cannot reset the ledger or replace a baseline.
4. Calibrate the new contract using the existing runner and explicit reference
   labels. Review the labels, actor-validity judgments, measurement failures, and
   disagreements, then approve the exact evidence and update
   `golden/calibration-reference.json`, approve `golden/review.json` against
   the current corpus digest, and approve the active policy selected by scripts/golden_gate.py against
   its exact digest. Those approvals must precede a candidate run. Reconcile any separate
   calibration spend into the versioned ledger before protected execution;
   retain provider usage and the prior ledger version, never reduce known spend
   or clear unknown usage without accounting for the interrupted calls.
5. Bootstrap by dispatching `v2-golden-evaluation` with purpose
   `production-reference` and development run `0`. It resolves the currently
   successful production deployment, then its development-proven bundle.
   It takes no arbitrary candidate input and cannot approve a candidate release.
   After review, dispatch `v2-golden-baseline` with that evaluation run and the
   corresponding successful production plan run. Deployment and canary evidence
   must still be available. This also provides the bounded refresh path.

Only then evaluate a new candidate and create its release. The gate deliberately
has no bypass flag. If the currently deployed agent cannot meet the absolute
floors, qualification stays blocked until separately approved application work
addresses it.

## Failures and recovery

Claims allow one original execution per exact artifact, policy, evaluator, and
baseline. GitHub reruns (`run_attempt > 1`) are rejected. A failed original may
have one replacement: supply `superseded_run` and reason `infrastructure` or
`actor_validity`. The pre-spend `golden-evaluation` approval attests to that reason
after inspecting retained original evidence. Infrastructure replacements require
an incomplete original; actor replacements explicitly record invalid actor
behavior. Identity must match, all trials are fresh, and both runs are retained.
Quality-only retries and second replacements are rejected. A crash without
retained evidence stays blocked; it cannot authorize a speculative retry.

After successful production approval, deployment, and matching canary,
`v2-golden-baseline` automatically archives promotion provenance and conditionally
advances the current reference. The original baseline and all previous object
versions remain available. Failed deployment cannot advance it. Concurrent or
out-of-order publication fails without overwriting the pointer.

If deployment succeeds but publication fails, the reference no longer matches
production and the next release blocks. Recover by dispatching
`v2-golden-baseline` with the completed production run ID and evaluation run `0`
(read the receipt from that run). This rechecks provenance and canary and retries
publication idempotently; it never redeploys. Evidence must still satisfy the
30-day reference limit. A reference refresh uses its explicit approved evaluation
run instead. GitHub packets are retained for 90 days; immutable S3 evidence and
baseline history remain durable. Refresh before GitHub provenance expires.

## Offline demonstration

From `v2/`, run:

```bash
uv run pytest tests/test_golden_gate.py tests/test_golden_baseline.py
uv run pytest tests/test_check_production_release.py tests/test_production_plan_workflow.py tests/test_production_migration_workflow.py
```

These synthetic checks demonstrate valid admission and rejection of missing,
partial, critical-failure, regression, infrastructure, stale, identity-mismatched,
and untrusted evidence, plus failed and successful baseline publication. They do
not claim that a real candidate passed. PR CI also builds an ARM64 package and
runs `tests.golden_artifact_smoke`: real packaged agent/SDK, canned provider,
frozen replay, retained conversation state, measured calls, and forbidden network
connections. Existing scheduled live checks and the canary remain separate from
frozen quality evaluation.

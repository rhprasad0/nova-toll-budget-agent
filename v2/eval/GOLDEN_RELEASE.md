# Golden production gate

Production planning requires a successful protected golden evaluation of the
exact development release bundle. The gate is mandatory. Missing infrastructure,
an unset production baseline, pending reviews, stale evidence, or a failed run
blocks planning before production credentials are available.

Production qualification remains **blocked until a production reference passes**.
This PR changes the evaluation harness and gate only; the application prompt,
model, contract, and application tests match main. The earlier prompt experiments
remain historical evidence, not application changes included in this PR.

The current corpus **1.0.19**, harness **1.2.9**, and policy **1.0.8** await exact
human approval. See the [current review packet](results/golden/CACHING-SUMMARY.md).
Fresh four-worker calibration 24 agrees on **179/180** labels, with a retained
wrong-route Outcome false positive. Historical eight-worker calibration also had
one miss; concurrency is not established as its cause. Retain the existing
four-worker scored timing policy. Activation remains pending adjudication.

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

Each execution includes all 24 cases, including the four held-out cases, with
three fresh trials and four workers. Every model call reserves against one
shared $5 run ceiling before starting. The durable ledger also reserves against
the existing $25 authorization. Missing usage stops further paid calls and
blocks subsequent runs until spending is reconciled. Provider retries are off.

The original thresholds from policy 1.0.0 are unchanged in policy 1.0.6. The
active corpus has 60 development calibration examples covering route
expectations, initial actor facts, monetary proposals/denials, and source
grading. Earlier approvals apply only to their historical contracts.
Historical evidence, labels, policy approvals, and the original baseline remain intact.

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

These are the activation and recovery requirements. Infrastructure, environment
configuration and initialization are complete; new-contract calibration approval
and the first qualified production reference are still required. Keep these checks for future
contract changes and environment recovery.

1. Provision `infra/golden_eval.tf` in development account `903859731897`. The
   private bucket is encrypted, versioned, protected against destruction, and
   has no lifecycle expiry. Workflow roles cannot delete evidence. Evaluator,
   reviewer, reader, and publisher have separate write scopes; only the
   evaluator can read the fixed development OpenAI parameter. They have no
   production role, database permission, or network path to a database.
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
4. Calibrate the new contract using the existing runner and approved labels.
   Approve its evidence and disagreements, update
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

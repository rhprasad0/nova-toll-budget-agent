# Private production qualification

**Status: awaiting independent evaluator activation.** The receiving gate is
implemented; no private cases, signing key, approved holdout identity, or new
qualification results are supplied by this repository. The exposed development
corpus and historical receipts cannot qualify production.

## Admission standard

The private benchmark contains **100 independently authored scenarios**, each run
three times against the exact delivered application artifact. A candidate needs
**at least 240 successful trials out of 300 (80%)** and protected human approval.
Every trial needs a valid simulation and complete judgments. Agent-caused errors
are failures; invalid simulations and missing measurements are inconclusive and
block admission. The grading rubric is unchanged.

There is no per-case veto, consistency floor, automatic regression veto, or
latency/cost-per-success quality threshold. Report those measurements honestly.
Twenty cases failing all three trials can meet the chosen overall floor; reviewers
see that consistency distribution. The 80% floor is a chosen admission standard
for a reference implementation, not a claim of real-world accuracy.

Spending remains bounded by **$5 per execution and $25 cumulative authorization**,
including evaluator overhead and retained failed/replacement runs. Unknown usage
must be reconciled. Changing this authorization requires a reviewed policy change;
the importer does not start paid work or reset spending. Evidence expires **24
hours after completion** and is rechecked before migration and promotion.

A production baseline is optional. A candidate can qualify without evaluating the
currently deployed application. The former mandatory baseline workflow is retired;
historical policies, records, and storage versions remain intact.

## Privacy and independent execution

The independent evaluator runs outside the access available to this repository's
coding agent. An ignored directory, another branch, or a protected job executing
repo-controlled evaluation code is not that boundary. Keep cases, expected answers,
fixtures, transcripts, per-case results, grading review, and the private signing
key out of this checkout, GitHub artifacts, repository-accessible storage, logs,
and model traces accessible to the coding agent.

The evaluator must independently review its runner, verify and execute the exact
immutable development release bundle without rebuilding it, isolate candidate code
from cases/labels other than the delivered conversation and tool responses, and
prevent candidate-controlled telemetry or network access from exporting cases.
Application/model calls necessarily receive their delivered inputs; their credentials
and retained telemetry must belong to the independent evaluation boundary. Do not
execute arbitrary evaluation scripts from the candidate checkout.

Only a signed aggregate summary crosses this boundary. The external signer attests:

- Independent authorship and no tuning exposure of the holdout; reviewed fixed
  rubric, actor validity assessment, judges, and exact calibration identity.
- Exact artifact execution, complete trial accounting, and a private review resolving
  measurement issues. Quality failures remain reported; human acceptance is not a
  relabeling of those failures.
- Pre-call spending reservations against the existing authorization, complete usage
  reconciliation, and cumulative spending including previous work and calibration.
- Complete release-only attempt history. One original execution per unchanged
  artifact/holdout, with no quality-only reruns. At most one fresh replacement is
  allowed for an incomplete infrastructure run or invalid actor simulation after
  independent human authorization. Original measurements remain in the summary.

The verifier authenticates these attestations; aggregate data cannot independently
prove how private execution happened. Activation therefore requires reviewing the
external evaluator and its access controls, not just supplying a public key.

Reuse is allowed for release candidates, with cumulative execution count disclosed.
Only the first execution is called first-use holdout evaluation; later measurements
are a **reused private benchmark**. Do not tune against case-level feedback or
select the best of repeated runs.

## Signed interface

The input is one UTF-8 JSON envelope containing exactly `summary_base64` and
`signature_base64`. The first is the base64 encoding of the exact UTF-8 summary
bytes; the second is a detached Ed25519 signature over those bytes. The verifier
uses the reviewed PEM public key with OpenSSL, rejects duplicate/unknown fields,
and limits the envelope and summary to 16 KiB. No private data or arbitrary
failure text is accepted. Do not include private content even in rejected inputs:
the inbox is accessible to repository roles.

The executable contract is `validate_summary` in `scripts/golden_gate.py`; the
synthetic `summary` fixture in `tests/test_golden_gate.py` demonstrates its complete
shape without representing any real held-out case. Required summary fields:

| Fields | Meaning |
| --- | --- |
| `schema_version`, `evaluation_scope` | Integer `1`, literal `private-held-out` |
| `candidate`, `bundle_id`, `bundle_digest` | Exact commit, immutable artifact ID, `sha256:` artifact digest |
| `development_run`, `development_attempt`, `development_deployment` | Successful development-delivery provenance |
| `policy_sha256` | SHA-256 of canonical active policy JSON |
| `holdout_sha256`, `evaluator_sha256`, `calibration_sha256` | Opaque digests pinned by the reviewed policy; evaluator digest includes runner, actor/judge prompts, settings and rubric; no case-level hashes |
| `cases`, `trials` | Integers `100` and `3` |
| `holdout_attempts` | Total executions across all candidates using this holdout, including failed/replacement runs |
| `cumulative_cost_usd`, `unknown_usage` | All spending under the authorization and whether reconciliation is incomplete |
| `private_review_complete` | Independent review/authorization attestation described above |
| `attempts` | One original record, or that record followed by one replacement |

Each attempt has exactly these fields:

| Fields | Meaning |
| --- | --- |
| `started_at`, `completed_at` | Timezone-aware ISO timestamps, ordered and not in the future; policy approval precedes execution |
| `replacement_reason` | `none` for original; `infrastructure` or `actor_validity` for replacement |
| `passed`, `failed`, `inconclusive`, `unmeasured` | Nonnegative integer counts summing to 300 |
| `case_pass_counts` | Four integer counts for cases with 0/1/2/3 successful trials; sum 100, weighted sum equals `passed` |
| `success_interval` | Exactly `method: case-bootstrap-95`, `lower`, `upper`; 95% interval resampling whole scenarios, not independent trials |
| `latency_p50_seconds`, `latency_p95_seconds` | End-to-end application conversation latency, excluding actor/judge time; both null only when unavailable, which blocks qualification |
| `agent_cost_usd`, `total_cost_usd` | Application calls versus all measured calls for that execution |

For uncertainty, resample 100 scenario groups with replacement, retaining all three
trials within each group; use 10,000 bootstrap samples with fixed seed 0 and the
2.5th/97.5th percentiles of successful-trial fractions. Use the fixed denominator
300; count inconclusive/unmeasured slots separately and never drop them. An
incomplete original still reports its aggregate consistency counts, treating
unmeasured slots as nonsuccesses, without labeling them failed answers.

Policy digests use UTF-8 JSON with sorted keys, compact separators, and no NaN or
Infinity (`golden_gate.canonical`). The signature covers the actual summary bytes,
not a reserialized version. No signing utility or real private key lives here.

## Activation and operation

These are prerequisites, not authorization to deploy infrastructure or run an eval.

1. Independently provision and review the evaluator, its private storage, model
   credentials, network/telemetry isolation, attempt ledger, and signing key.
   Transfer only its public PEM key to
   `eval/results/golden/evaluator-public.pem`. Never generate its real key here.
2. Use the [public authoring kit](HOLDOUT_AUTHORING.md) in an isolated private
   environment. Review the private 100-case contract and calibration externally. Populate the
   four currently unset digests in `policy-3.0.0.json` (including the SHA-256 of the
   exact public PEM bytes). Set the policy approval status, reviewer, approval time,
   evidence reference, and exact policy digest through human-reviewed changes.
   All executions must follow that approval. Historical approvals do not apply.
3. Apply and verify the reviewed `infra/golden_eval.tf` changes separately. Existing
   encrypted/versioned storage and deletion protections are retained. Repo roles
   read only `aggregates/*` and `candidates/private/*`; the importer writes aggregate
   reports, outcome claims, and finalized accounting records. The reviewer writes
   versioned candidate indexes with conditional writes. They have no model,
   database, or production credentials. Remove the former baseline publisher role.
4. Verify the `golden-evaluation` and `golden-review` environments require Ryan's
   approval, permit only `main`, and disable administrator bypass. `golden-read`
   remains the bounded automated read environment. No private evaluator credential
   is added to any repository environment.
5. The external operator publishes **only** the envelope to the existing development
   evidence bucket, key `aggregates/inbox/<envelope-sha256>.json`, using an immutable
   conditional write. This operator needs a separately provisioned inbox-only
   publishing identity; no repository role can upload an input. Record its S3
   version ID. Preserve existing historical objects and reconcile the prior
   spending ledger externally; do not initialize a fresh zero balance.
6. Dispatch `v2-golden-evaluation` on main with the successful `development_run`,
   `summary_sha256`, and exact `summary_version`. The workflow resolves development
   provenance, verifies the signature/contract, retains aggregate failures as well
   as passes, and requests human review only after machine qualification.
7. Review `review.md`, `decision.json`, and the signed summary. Approve `golden-review`
   to accept the reported limitations for this artifact. The receipt binds the
   actual approval, completed workflow, importer code, policy, holdout, and exact
   artifact. It carries the signed envelope so later stages can reverify it without
   development AWS credentials. Normal production approval, saved-plan verification, migration gates,
   and canary checks still apply.

Malformed or unauthenticated input is rejected without copying it to logs/artifacts.
Valid aggregate evidence that misses qualification remains archived. A corrected
transport/import attempt may reimport identical signed measurements; it is not
permission for a new evaluator execution. GitHub workflow reruns are rejected.
If receipt upload fails after index publication, dispatch a new import of the same
signed summary. After fresh human approval, a newer trusted import may conditionally
replace the index only if the prior import has completed and the summary digest is
identical. This also permits reapproval after importer maintenance. Both successful
and failed prior imports are eligible; evidence changes, active prior runs,
out-of-order publication, and concurrent-write conflicts block. S3 versioning keeps
the earlier pointer. No new evaluation or rescoring is authorized by this recovery.

An import with unknown usage retains its signed report but cannot qualify. Its
outcomes, timing, and consistency/uncertainty measurements are immutable; provisional
costs are excluded from that outcome claim. The external evaluator may sign a
reconciled summary with unchanged outcomes and corrected costs. The first summary
with `unknown_usage: false` freezes each attempt's application and total cost in an
immutable accounting record. Further cost changes or outcome changes are rejected.
Both provisional and reconciled reports remain archived; all spending limits still
apply to qualification. This is accounting reconciliation, not a replacement run.

For an optional aggregate comparison using two compatible signed envelopes:

```bash
python3 -m scripts.golden_release compare --directory /tmp/current-review \
  --previous /tmp/previous-summary-envelope.json
```

`/tmp/current-review/summary-envelope.json` is the current packet. Both must match
the active contract and have complete measurements; the previous result need not
satisfy candidate freshness. The resulting deltas are informational and never an
admission requirement. Publish aggregate experiment summaries in the
[experiment journal](EXPERIMENT_JOURNAL.md), not per-run review packets.

## Offline verification

```bash
uv run pytest tests/test_golden_gate.py tests/test_golden_retirement.py
uv run pytest tests/test_check_production_release.py tests/test_production_plan_workflow.py \
  tests/test_production_migration_workflow.py tests/test_development_migrations.py
```

These checks generate temporary test-only signing keys and synthetic summaries.
They do not run models, access private cases, qualify a real candidate, or deploy.
Existing development-corpus tests and packaged-agent smoke checks remain separate.

## Legacy development retirement (#333)

This is a **source-only lower PR**. It does not authorize a destroy, a DNS
delete, a database connection, or a schema mutation. The procedure below is
legal only from a clean, merged `origin/main` checkout after every #332
cutover/health/isolation gate has passed, the captured rollback window has
expired, all fresh inventory and SQL preflight evidence is reviewed, and a
separately authorized protected operator approves each destructive phase. A
dirty checkout, a feature branch, a stale or ambiguous read, drift, lock
contention, or any unknown result is a hard stop; do not retry or guess.

The production account is `920534282028` in `us-east-1`. The only initial
destroy universe is the exact managed instances in the versioned legacy
application state object:

```text
s3://nova-toll-tfstate-920534282028/nova-toll/v2/development/terraform.tfstate
```

The foundation object
`s3://nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate`, the
production application object `nova-toll/v2/terraform.tfstate`, and both
development-account objects are never read as destroy input. Tags and the
historical 73/77 inventory counts are reconciliation signals only; they never
select a target.

### Ordered retirement gates

1. From the clean protected checkout, prove the #332 DNS cutover, rollback
   snapshot, rollback-window expiry, new-account health, delivery identity,
   cross-account isolation, production regression, and #301 resume gates.
   Capture sanitized old/new CloudFront and ACM status, the exact current
   `dev.tollchat.ai`, apex, and `www` records, the old ACM validation record,
   RDS metadata, and both state identities. The old distribution
   `E1JXKQYNAN39E4` / `dmsiz11apblcv.cloudfront.net` and old certificate and
   validation record remain available until this gate is complete.

2. Assert the operator account and region, then re-read the exact canonical
   state object and require the fresh VersionId, ETag, serial `22`, lineage
   `2b1cca15-f9a6-6b00-7e68-238ab13ab1f7`, Terraform version `1.15.8`, and
   managed-instance/address-pair counts expected by the reviewed inventory.
   The observed VersionId `DwY7IvIcq6sD3FfmKD4Z4LrSai5Q0Ls3` is only a
   comparison hint; accept it only when this fresh read returns it unchanged.
   Reject a missing, changed, or version-ambiguous object; a foundation
   address; a production or development-account ID; an unknown address; or
   any state/live reconciliation mismatch. The saved plan must later prove
   this same identity again immediately before detach and apply.

3. Before any state mutation, copy exactly that S3 object version to an
   explicit encrypted archive key under
   `nova-toll/v2/development/retirement-archives/`, where the suffix is
   derived only from the validated source VersionId. Use SSE-KMS, read the
   exact archive VersionId back privately, and compare source/archive SHA-256
   digests and non-secret serial/lineage/Terraform-version metadata. Retain
   only bucket/key, canonical/archive VersionIds, ETags, metadata, managed
   count, timestamp, and digest. Never print, commit, upload, cache, or retain
   raw state, plan JSON/binary, credentials, tokens, authorization headers,
   SQL, or secret-bearing errors. S3 versioning supplies recovery, but this
   bucket has no Object Lock; do not test restore or delete against production.

### Bounded bucket archive and purge phase

The state archive above is already the canonical state evidence.  Do not copy
it again during this phase.  The bucket helper uses the distinct
`nova-toll/v2/development/retirement-archives/objects/` prefix and writes one
content-free, SSE-KMS encrypted manifest under the same existing state bucket.
The helper never deletes a bucket, the archive, or a shared bucket.

Run this phase only after the fresh 166-entry account-scoped live manifest,
the 25 exact S3 mappings, and the state identity checks above have passed.  The
sanitized design captures in the graph are review input only; they do not
replace these reads.  The exact source scope is fixed:

```text
old buckets:
  tollchat-site-920534282028-dev
  aws-waf-logs-tollchat-agent-reports-920534282028-dev
shared bucket (objects only; never delete this bucket):
  nova-toll-agentcore-920534282028/runtime/v2/agentcore-dev.zip
  nova-toll-agentcore-920534282028/lambda/v2/chat-proxy-dev.zip
managed old objects retained for Terraform: 22 site keys + 1 registry key
historical reconciliation only: 1,655 unmanaged old objects, 5 shared versions
```

#### Resuming the interrupted writer freeze

The interrupted run must use `resume-frozen`; it must not be re-run as
`freeze`, and `--execute` is rejected for this phase. Keep the original
`writers-before.json` immutable and supply it as `--resume-baseline`. Before
starting the drain, freshly run and review the read-only semantic comparison
against canonical Terraform state. The proof must be a
`lambda-semantic-proof-v1` document with `status: pass`, `read_only: true`,
account `920534282028`, region `us-east-1`, exactly the three fixed writer
names, all 20 checks true for each writer, no mismatches, and each current
`configuration_sha256` from that same read.

The proof's single `canonical_state` binding must contain the fixed state
bucket/key, version `DwY7IvIcq6sD3FfmKD4Z4LrSai5Q0Ls3`, SHA-256
`6080bb945772256bbbe389dc6cf15804ba297ad6399dc9f10ebb8cc315a6b720`, and a
fresh `head` object whose `version_id` and `etag` come from an unversioned
`head-object` read. Retain its KMS algorithm and key ID too. This HEAD check
prevents a proof from silently following a changed state object. The proof is
accepted only when its capture time is after the final permitted writer
mutation and before the resume starts.

For this one-time recovery, use the independently reviewed private
`freeze-state-config-compare.py` retained with the operator's graph evidence.
It is not a checked-in application script. Set
`RETIRE_LEGACY_SEMANTIC_COMPARATOR` to its absolute reviewed path and verify
its reviewed SHA-256 before running it. It must reject optimized Python,
assert the current canonical state VersionId/ETag/CMK before and after its
read-only comparison, and keep raw state and Lambda configuration in memory.
Run it immediately before the wrapper below and review its sanitized output. Create
the strict proof with this small wrapper after obtaining the fresh unversioned
HEAD response. It adds no configuration data or secrets; it fails if the
comparator did not pass or widened the writer set:

The shell block below selects this recovery with
`RETIRE_LEGACY_FREEZE_MODE=resume-frozen`. It runs the comparison and proof
wrapper before the read-only drain. Use a fresh evidence directory and set
`RETIRE_LEGACY_RESUME_BASELINE` to the original immutable `writers-before.json`.

This phase reads the three writers, WAF logging document, lifecycle document,
Athena workgroup, and complete object/configuration inventory before the
drain; it then waits at least 900 seconds without Lambda, WAF, lifecycle,
archive, delete, Terraform, or database calls and repeats those reads. It
requires exact zero reserved concurrency, the reviewed WAF `KEEP` to `DROP`
change, the two reviewed lifecycle `Enabled` to `Disabled` changes, byte-stable
current writer hashes (including live-only status fields), and a stable full
snapshot. Resumed evidence records its own start/completion times and contains
no claim that the historical whole-hash mismatch was equal or understood.
Review the sanitized resumed state and snapshot before archive. Archive, purge,
and verify consume resumed evidence only through that marker and remain behind
all existing archive/readback, conditional-delete, managed-object,
shared-version, and Terraform-plan gates.

Use the helper only from the production account and `us-east-1`.  Its boto3
clients use `total_max_attempts=1`, assert the caller account at session
construction and before each non-S3 API request, pass
`ExpectedBucketOwner=920534282028` and (for copies)
`ExpectedSourceBucketOwner=920534282028` to S3, and fail closed on an
unknown, partial, timeout, 412, or ambiguous result.  It streams plaintext
SHA-256 digests and keeps raw bodies out of stdout and evidence files.  The
private snapshot contains only metadata needed for comparison; the archive
manifest containing metadata and tags is encrypted with the retained state CMK.

The operator must refresh the old delivery-role and workflow separation before
the first capture.  The old role must be absent, and both queued and
in-progress GitHub Actions runs for the old production delivery must be zero;
the current `903859731897` development delivery role and artifact bucket are
not part of this retirement:

Set `RETIRE_LEGACY_EVIDENCE_DIR` to an absolute private directory outside the
repository before running the block.  The directory retains the digest-only
snapshots, writer freeze evidence, exact encrypted-manifest VersionId/digest,
and sanitized phase summaries for review and Terraform revalidation; only
temporary material is eligible for cleanup.

```sh
(
set -euo pipefail
umask 077
ROOT="$(git rev-parse --show-toplevel)"
HELPER="$ROOT/v2/scripts/retire_legacy_development_buckets.py"
EVIDENCE_DIR="${RETIRE_LEGACY_EVIDENCE_DIR:?set an absolute private durable evidence directory outside the repository}"
case "$EVIDENCE_DIR" in
  "$ROOT"|"$ROOT"/*) exit 1 ;;
  /*) ;;
  *) exit 1 ;;
esac
mkdir -p "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_DIR"
INITIAL="$EVIDENCE_DIR/initial.json"
FROZEN="$EVIDENCE_DIR/frozen.json"
WRITERS="$EVIDENCE_DIR/writers.json"
ARCHIVE_STATE="$EVIDENCE_DIR/archive-state.json"
LIVE_IDENTITY_MANIFEST="${LIVE_IDENTITY_MANIFEST:?set the fresh 166-entry live identity manifest}"
MANAGED_OBJECT_MAPPING="${MANAGED_OBJECT_MAPPING:?set the fresh 25-row managed-object mapping}"
STATE_SSEKMS_KEY_ID="${STATE_SSEKMS_KEY_ID:?set the retained state CMK from the fresh state head}"
for name in "${!AWS_@}"; do
  case "$name" in
    AWS_PROFILE|AWS_DEFAULT_REGION) ;;
    *) exit 1 ;;
  esac
done
test "${AWS_PROFILE:-nova-toll-prod}" = "nova-toll-prod"
test "${AWS_DEFAULT_REGION:-us-east-1}" = "us-east-1"
test "$(aws --profile nova-toll-prod --region us-east-1 sts get-caller-identity --query Account --output text)" = "920534282028"
ROLE_STATUS=0
ROLE_ERROR="$(aws --profile nova-toll-prod --region us-east-1 iam get-role --role-name nova-toll-v2-development-delivery 2>&1 >/dev/null)" || ROLE_STATUS=$?
if test "$ROLE_STATUS" -eq 0; then
  exit 1
fi
grep -qF 'An error occurred (NoSuchEntity) when calling the GetRole operation' <<<"$ROLE_ERROR"
for status in queued in_progress; do
  test "$(gh run list --repo rhprasad0/nova-toll-budget-agent --status "$status" --limit 100 --json databaseId --jq 'length')" -eq 0
done

# This is the only read-only default.  It inventories key, ETag, size,
# LastModified, metadata, tags, and streamed digest, plus version/configuration
# and multipart boundaries.  It rejects unknown keys and missing managed rows.
uv run --project "$ROOT/v2" python "$HELPER" --phase capture --output "$INITIAL" >"$EVIDENCE_DIR/initial-summary.json"

# The mapping is independently captured and reviewed; it must contain exactly
# 25 rows, with 22 site keys, one registry key, and only the two shared keys.
test -s "$MANAGED_OBJECT_MAPPING"
jq -e '
  .total == 25 and
  .counts["tollchat-site-920534282028-dev"] == 22 and
  .counts["aws-waf-logs-tollchat-agent-reports-920534282028-dev"] == 1 and
  .counts["nova-toll-agentcore-920534282028"] == 2 and
  all(.rows[];
    (.bucket == "tollchat-site-920534282028-dev" or
     .bucket == "aws-waf-logs-tollchat-agent-reports-920534282028-dev" or
     (.bucket == "nova-toll-agentcore-920534282028" and
      (.key == "runtime/v2/agentcore-dev.zip" or .key == "lambda/v2/chat-proxy-dev.zip"))))
' "$MANAGED_OBJECT_MAPPING" >/dev/null

# Explicit selection prevents an interrupted run from repeating mutations.
case "${RETIRE_LEGACY_FREEZE_MODE:?set freeze for a new run or resume-frozen for the interrupted run}" in
freeze)
# Freeze exactly three writers.  The helper retrieves and replays the complete
# WAF document, changing only this exact KEEP filter to DROP, and the complete
# lifecycle document, changing only IDs expire-raw-waf-logs and
# expire-athena-results to Disabled.  It preserves WAF destination, default
# behavior, redaction, LogScope, LogType, ManagedByFirewallManager, lifecycle
# filters, expiration, abort-multipart settings, and
# TransitionDefaultMinimumObjectSize.  It sets only these reserved concurrency
# values to zero and waits a full 900 seconds after the final mutation before
# requiring tollchat-agent-reports-dev to have no QUEUED or RUNNING queries.
uv run --project "$ROOT/v2" python "$HELPER" --phase freeze --execute --snapshot "$INITIAL" \
  --output "$FROZEN" --freeze-state "$WRITERS" \
  --identity-manifest "$LIVE_IDENTITY_MANIFEST" \
  --managed-object-mapping "$MANAGED_OBJECT_MAPPING" \
  >"$EVIDENCE_DIR/frozen-summary.json"

;;
resume-frozen)
SEMANTIC_COMPARATOR="${RETIRE_LEGACY_SEMANTIC_COMPARATOR:?set the absolute independently reviewed private comparator path}"
SEMANTIC_COMPARATOR_SHA256="${RETIRE_LEGACY_SEMANTIC_COMPARATOR_SHA256:?set its reviewed SHA-256}"
test "$(sha256sum "$SEMANTIC_COMPARATOR" | awk '{print $1}')" = "$SEMANTIC_COMPARATOR_SHA256"
uv run --project "$ROOT/v2" python "$SEMANTIC_COMPARATOR" \
  >"$EVIDENCE_DIR/freeze-state-config-comparison.json"
CANONICAL_STATE_VERSION="DwY7IvIcq6sD3FfmKD4Z4LrSai5Q0Ls3"
CANONICAL_HEAD="$(aws --profile nova-toll-prod --region us-east-1 s3api head-object \
  --bucket nova-toll-tfstate-920534282028 \
  --key nova-toll/v2/development/terraform.tfstate \
  --expected-bucket-owner 920534282028 \
  --query '{version_id:VersionId,etag:ETag,sse_algorithm:ServerSideEncryption,kms_key_id:SSEKMSKeyId}' \
  --output json)"
python3 - "$EVIDENCE_DIR/freeze-state-config-comparison.json" \
  "$EVIDENCE_DIR/semantic-proof.json" "$CANONICAL_HEAD" <<'PY'
import json, sys
from pathlib import Path

if sys.flags.optimize:
    raise SystemExit("optimized Python is prohibited")
source = json.loads(Path(sys.argv[1]).read_text())
head = json.loads(sys.argv[3])
names = {
    "toll-v2-report-publisher-dev",
    "tollchat-v2-usage-publisher-dev",
    "tollchat-v2-agent-usage-rollup-dev",
}
assert source.get("status") == "pass" and source.get("read_only") is True
assert {row.get("name") for row in source.get("functions", [])} == names
assert all(row.get("not_in_terraform_state") == [
    "LastUpdateStatus", "RevisionId", "RuntimeVersionConfig", "State"
] for row in source["functions"])
assert head["version_id"] == "DwY7IvIcq6sD3FfmKD4Z4LrSai5Q0Ls3"
assert head["etag"] == '"375ef3e67c0f52f518883e6cb6791baa"'
assert head["sse_algorithm"] == "aws:kms"
assert head["kms_key_id"] == "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7"
assert source["account_id"] == "920534282028" and source["region"] == "us-east-1"
assert source["canonical_state_version"] == "DwY7IvIcq6sD3FfmKD4Z4LrSai5Q0Ls3"
proof = {
    "manifest": "lambda-semantic-proof-v1",
    "status": "pass",
    "read_only": True,
    "account_id": "920534282028",
    "region": "us-east-1",
    "captured_at": source["captured_at"],
    "canonical_state": {
        "bucket": "nova-toll-tfstate-920534282028",
        "key": "nova-toll/v2/development/terraform.tfstate",
        "version_id": "DwY7IvIcq6sD3FfmKD4Z4LrSai5Q0Ls3",
        "sha256": "6080bb945772256bbbe389dc6cf15804ba297ad6399dc9f10ebb8cc315a6b720",
        "head": head,
    },
    "live_only_fields": ["LastUpdateStatus", "RevisionId", "RuntimeVersionConfig", "State"],
    "functions": source["functions"],
}
Path(sys.argv[2]).write_text(json.dumps(proof, sort_keys=True, separators=(",", ":")) + "\n")
PY

LAST_WRITER_MUTATION_AT="${LAST_WRITER_MUTATION_AT:?set the final permitted writer mutation timestamp}"
uv run --project "$ROOT/v2" python "$HELPER" --phase resume-frozen \
  --snapshot "$INITIAL" --output "$FROZEN" --freeze-state "$WRITERS" \
  --resume-baseline "${RETIRE_LEGACY_RESUME_BASELINE:?set the original immutable writers-before.json path}" \
  --semantic-proof "$EVIDENCE_DIR/semantic-proof.json" \
  --last-writer-mutation-at "$LAST_WRITER_MUTATION_AT" \
  --identity-manifest "$LIVE_IDENTITY_MANIFEST" \
  --managed-object-mapping "$MANAGED_OBJECT_MAPPING" \
  >"$EVIDENCE_DIR/resume-frozen-summary.json"
;;
*) exit 1 ;;
esac

# STATE_SSEKMS_KEY_ID is the fixed retained production state CMK read from the
# canonical state object.  Archive every old object and every actual version of
# both exact shared keys, including each delete-marker identity/status.  A
# delete marker has no body and is recorded in the encrypted manifest without
# CopyObject.  Source and destination ETags are recorded separately; source
# and archive size, custom and HTTP metadata (including redirect), tags,
# plaintext SHA-256, source key/version identity, archive VersionId, KMS key,
# and private readback must all verify before this command succeeds.  The copy
# uses the source ETag as CopySourceIfMatch.
uv run --project "$ROOT/v2" python "$HELPER" --phase archive --execute --snapshot "$FROZEN" \
  --state-kms-key-id "$STATE_SSEKMS_KEY_ID" --freeze-state "$WRITERS" \
  --archive-state "$ARCHIVE_STATE" \
  --identity-manifest "$LIVE_IDENTITY_MANIFEST" \
  --managed-object-mapping "$MANAGED_OBJECT_MAPPING" \
  >"$EVIDENCE_DIR/archive-summary.json"

# The purge selector is recomputed from the fresh frozen inventory minus the
# exact 23 Terraform-managed old-bucket keys.  Historical 1,655 is only a
# reconciliation signal.  Each delete uses exact If-Match and expected owner;
# size and LastModified are comparison guards.  No retry or target broadening
# is allowed after a mismatch, 412, partial, timeout, or ambiguous response.
uv run --project "$ROOT/v2" python "$HELPER" --phase purge --execute --snapshot "$FROZEN" \
  --state-kms-key-id "$STATE_SSEKMS_KEY_ID" --freeze-state "$WRITERS" \
  --archive-state "$ARCHIVE_STATE" \
  --identity-manifest "$LIVE_IDENTITY_MANIFEST" \
  --managed-object-mapping "$MANAGED_OBJECT_MAPPING" \
  >"$EVIDENCE_DIR/purge-summary.json"
uv run --project "$ROOT/v2" python "$HELPER" --phase verify --snapshot "$FROZEN" \
  --state-kms-key-id "$STATE_SSEKMS_KEY_ID" --freeze-state "$WRITERS" \
  --archive-state "$ARCHIVE_STATE" \
  --identity-manifest "$LIVE_IDENTITY_MANIFEST" \
  --managed-object-mapping "$MANAGED_OBJECT_MAPPING" \
  >"$EVIDENCE_DIR/verify-summary.json"
)
```

Before continuing, review only the sanitized summaries and the encrypted
archive manifest.  The two old buckets must contain exactly the 23 managed
keys, both shared keys must still contain every frozen object version and
delete marker, all archive readbacks must pass, and the three reserved
concurrency values, WAF filter, and lifecycle statuses must still be frozen.
The pinned cutover baseline already removed the old CloudFront alias.  Its
`aws_s3_object.usage` resource intentionally retains
`ignore_changes = [content, etag]` because the historical usage publisher wrote
`usage.json`; do not broaden that exception. Compare the exact saved-plan
resource drift against that pinned baseline and the archived frozen object
identities and metadata.  The existing validator proves the 166 managed
identity set and the 162 delete actions, but it does not inspect
`resource_drift`; any unreviewed drift is a hard stop.
Keep that intentional drift in place through the compatibility checkout,
saved `terraform plan -destroy`, and its separately approved apply.  Reconcile
only this exact drift in the reviewed plan: any other update, replacement,
unknown action, shared-bucket target, archive target, managed-object purge, or
bucket deletion before the final Terraform apply is a hard stop.  The reviewed
plan must still contain exactly 162 deletes, exactly two old-bucket deletes,
four retained addresses, and no shared-bucket deletion.

4. Build a durable detach manifest after the archive and identity checks. The
   only exact state addresses that may be detached are:

   ```text
   cloudflare_dns_record.apex[0]                         # current cutover record
   cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"] # old validation, until DNS step
   aws_bedrock_guardrail.tollchat                         # prevent_destroy retained
   aws_bedrock_guardrail_version.tollchat                 # skip_destroy retained
   ```

   State-list and remote identity checks must pass for each address before
   using one exact multi-address `terraform state rm` command under one
   Terraform lock. Never use a pattern, `-target`, lifecycle edit, current
   `d4830c9`, `-refresh=false`, or `-auto-approve`. The command has four named
   retention reasons; its postflight immediately captures the current state
   VersionId, ETag, serial, and exact absence of all four addresses. The normal
   lifecycle settings remain unchanged.

   The following is the bounded archive/detach skeleton. Set the expected
   values only from the fresh read-only evidence above; every output containing
   state or plan data stays in the private temporary directory.

   Before entering the block, capture a fresh, independently reviewed live
   identity manifest (not derived from Terraform state) at the private path
   supplied as `LIVE_IDENTITY_MANIFEST`. It must have this shape, with one
   entry for every managed legacy application address and the exact production
   account on every entry:

   ```json
   {"manifest":"legacy-live-identity-v1","account_id":"920534282028",
    "source_remote":"https://github.com/rhprasad0/nova-toll-budget-agent.git",
    "source_commit":"4c1f684c02bf81187c2cc5f15883727cf15b11ee",
    "identity_source":"account-scoped-live-api-v1",
    "resources":[{"address":"aws_lambda_function.loader","type":"aws_lambda_function",
    "id":"...","account_id":"920534282028"}]}
   ```

   Generate each resource entry in one machine-produced capture from its
   provider's read-only API, invoking the AWS/Cloudflare clients with the
   fixed production profile/account and `us-east-1` region. The capture must
   assert the STS account first, write the manifest to a mode-0600 private
   temporary file, and atomically rename it to `LIVE_IDENTITY_MANIFEST`; do
   not hand-edit it or copy IDs from state. Keep only the manifest and its
   sanitized review evidence: the source remote, immutable source commit,
   account/region, `identity_source`, and the exact API-returned identities.
   The reviewer must independently compare the address/type/API identity rule
   and account for every entry before setting
   `RETIRE_LEGACY_LIVE_IDENTITY_REVIEWED=YES`.

   The validator rejects missing, extra, swapped, foundation/shared,
   new-development, or type/ID-mismatched entries, and requires the canonical
   repository remote plus the full immutable compatibility source commit in
   the manifest, and requires an `account-scoped-live-api-v1` capture source.
   Verify those values from the clean checkout and independent live APIs, not
   from the archived state or the manifest itself. The fixed application
   address/type inventory and explicit foundation/shared/new-development
   denylist are in `validate_legacy_retirement_plan.py`; the development
   compatibility inventory is exactly 166 managed instances, with every
   count/for_each index reviewed (there is no base-address fallback). Every
   state/manifest address and type must match, and the archived state alone
   can never authorize a deletion. The ACM validation waiter has no independent
   remote identity: its state/plan `certificate_arn` must equal
   `arn:aws:acm:us-east-1:920534282028:certificate/b857cc16-ed20-476e-a64a-883b1624f6c8`,
   and both ACM manifest rows must use that API-described certificate ARN; its
   synthetic Terraform ID is bookkeeping only and is never an API identity or
   deletion target. The no-ID Bedrock and AgentCore rows use canonical ARNs:
   guardrail ARN (and `guardrail_arn,version` for its published version), the
   runtime ARN, its `/runtime-endpoint/preview` ARN, and matching policy and
   runtime log-group parents. Method settings use `{rest_api_id}-preview-*/*`;
   reviewed Lambda log groups and the exact bundled site asset whose filename
   contains `shared` use their exact API names. The validator still requires an
   independent `account-scoped-live-api-v1` manifest with the same canonical
   identity for every row; this offline comparison does not authorize live
   retirement.
   Set `STATE_SSEKMS_KEY_ID` to the exact reviewed
   production state CMK ID/ARN captured from the source object's
   `SSEKMSKeyId`; the source and archive must both be checked against it.

   ```sh
   (
   set -euo pipefail
   set +x
   umask 077
   ROOT="$(git rev-parse --show-toplevel)"
   GIT_COMMON_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
   PROJECT_ROOT="$(dirname "$GIT_COMMON_DIR")"
   ORIGIN_URL="$(git -C "$ROOT" remote get-url origin 2>/dev/null)"
   case "$ORIGIN_URL" in
     git@github.com:rhprasad0/nova-toll-budget-agent.git|https://github.com/rhprasad0/nova-toll-budget-agent.git) ;;
     *) exit 1 ;;
   esac
   git fetch --no-tags origin main
   test "$(git -C "$ROOT" rev-parse HEAD)" = "$(git -C "$ROOT" rev-parse origin/main)"
   test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)"
   COMPATIBILITY_COMMIT="$(git -C "$ROOT" rev-parse 4c1f684^{commit})"
   test "$COMPATIBILITY_COMMIT" = 4c1f684c02bf81187c2cc5f15883727cf15b11ee
   EXPECTED_ACCOUNT=920534282028
   REGION=us-east-1
   STATE_BUCKET=nova-toll-tfstate-920534282028
   STATE_KEY=nova-toll/v2/development/terraform.tfstate
   FOUNDATION_KEY=nova-toll/terraform.tfstate
   STATE_VERSION=EXPECTED_FRESH_VERSION_ID
   STATE_ETAG=EXPECTED_FRESH_ETAG
   STATE_SERIAL=22
   STATE_LINEAGE=2b1cca15-f9a6-6b00-7e68-238ab13ab1f7
   STATE_TERRAFORM_VERSION=1.15.8
   STATE_SSEKMS_KEY_ID=EXPECTED_APPROVED_PRODUCTION_STATE_CMK
   LIVE_IDENTITY_MANIFEST=EXPECTED_PRIVATE_LIVE_IDENTITY_MANIFEST
   mkdir -p "$PROJECT_ROOT/.worktrees"
   WORK_DIR="$(mktemp -d "$PROJECT_ROOT/.worktrees/nova-toll-333-state-XXXXXX")"
   COMPAT_ROOT="$WORK_DIR/compat"
   SOURCE_STATE="$WORK_DIR/source-state.json"
   ARCHIVE_STATE_PRIVATE="$WORK_DIR/archive-state.json"
   LIVE_STATE_PRIVATE="$WORK_DIR/live-state-before-detach.json"
   LIVE_STATE_AFTER_DETACH="$WORK_DIR/live-state-after-detach.json"
   DESTROY_PLAN="$WORK_DIR/legacy-retirement.tfplan"
   DESTROY_PLAN_JSON="$WORK_DIR/legacy-retirement.tfplan.json"
   DESTROY_PLAN_APPLY_JSON="$WORK_DIR/legacy-retirement.tfplan.immediately-before-apply.json"
   CLOUDFLARE_TOKEN= CLOUDFLARE_API_TOKEN=
   trap 'git worktree remove --force "$COMPAT_ROOT" >/dev/null 2>&1 || true; unset CLOUDFLARE_TOKEN CLOUDFLARE_API_TOKEN; rm -f -- "$SOURCE_STATE" "$ARCHIVE_STATE_PRIVATE" "$LIVE_STATE_PRIVATE" "$LIVE_STATE_AFTER_DETACH" "$DESTROY_PLAN" "$DESTROY_PLAN_JSON" "$DESTROY_PLAN_APPLY_JSON" "$WORK_DIR/head.json" "$WORK_DIR/foundation-head.json" "$WORK_DIR/archive-copy.json" "$WORK_DIR/archive-head.json" "$WORK_DIR/head-before-detach.json" "$WORK_DIR/head-after-detach.json" "$WORK_DIR/head-before-plan.json" "$WORK_DIR/head-before-plan-render.json" "$WORK_DIR/head-immediately-before-render.json" "$WORK_DIR/head-immediately-before-apply.json" "$WORK_DIR/state-list.txt" "$WORK_DIR/state-list-after-detach.txt" "$WORK_DIR/retained-identities.json"; rmdir "$WORK_DIR"' EXIT
   test ! -e "$COMPAT_ROOT"
   for variable in $(compgen -A variable AWS_); do
     test -z "${!variable-}"
   done
   for variable in $(compgen -A variable); do
     case "$variable" in
       TF_CLI_ARGS*|TF_VAR_*)
         value="${!variable-}"
         if [[ -n "$value" ]]; then
           [[ "$variable" == TF_VAR_environment && "$value" == development ]] || exit 1
         fi
         ;;
     esac
   done
   export TF_VAR_environment=development
   test "$TF_VAR_environment" = development
   test "$STATE_BUCKET" = nova-toll-tfstate-920534282028
   test "$STATE_KEY" = nova-toll/v2/development/terraform.tfstate
   export AWS_PROFILE=nova-toll-prod
   export AWS_DEFAULT_REGION=us-east-1
   export AWS_REGION=us-east-1
   test "$(aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"
   CLOUDFLARE_TOKEN="$(aws --region "$REGION" ssm get-parameter \
     --name /nova-toll/cloudflare-development-dns-api-token --with-decryption \
     --query Parameter.Value --output text 2>/dev/null)" || exit 1
   test -n "$CLOUDFLARE_TOKEN" && test "$CLOUDFLARE_TOKEN" != None
   export CLOUDFLARE_API_TOKEN="$CLOUDFLARE_TOKEN"
   terraform_prod() {
     test "${AWS_PROFILE:-}" = nova-toll-prod
     test "${AWS_REGION:-}" = "$REGION"
     test "${AWS_DEFAULT_REGION:-}" = "$REGION"
     test "$(aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"
     terraform "$@"
   }
   assert_current_state() {
     local expected_version="$1" expected_etag="$2" output="$3"
     aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY" >"$output"
     jq -e --arg version "$expected_version" --arg etag "$expected_etag" --arg cmk "$STATE_SSEKMS_KEY_ID" \
       '.VersionId == $version and .ETag == $etag and .ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $cmk' \
       "$output" >/dev/null
   }
   test "$STATE_VERSION" != EXPECTED_FRESH_VERSION_ID
   test "$STATE_ETAG" != EXPECTED_FRESH_ETAG
   test "$STATE_SSEKMS_KEY_ID" != EXPECTED_APPROVED_PRODUCTION_STATE_CMK
   test -s "$LIVE_IDENTITY_MANIFEST"
   test ! -L "$LIVE_IDENTITY_MANIFEST"
   test "${RETIRE_LEGACY_LIVE_IDENTITY_REVIEWED:-}" = YES
   jq -e --arg account "$EXPECTED_ACCOUNT" --arg remote "$ORIGIN_URL" --arg commit "$COMPATIBILITY_COMMIT" \
     '.manifest == "legacy-live-identity-v1" and .account_id == $account and .source_remote == $remote and .source_commit == $commit and .identity_source == "account-scoped-live-api-v1" and (.resources | type == "array" and length > 0)' \
     "$LIVE_IDENTITY_MANIFEST" >/dev/null
   HEAD_JSON="$WORK_DIR/head.json"
   aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY" --version-id "$STATE_VERSION" >"$HEAD_JSON"
   jq -e --arg etag "\"$STATE_ETAG\"" --arg version "$STATE_VERSION" --arg cmk "$STATE_SSEKMS_KEY_ID" '.ETag == $etag and .VersionId == $version and .ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $cmk' "$HEAD_JSON" >/dev/null
   FOUNDATION_HEAD="$WORK_DIR/foundation-head.json"
   aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$FOUNDATION_KEY" >"$FOUNDATION_HEAD"
   test "$FOUNDATION_KEY" = nova-toll/terraform.tfstate
   test "$STATE_KEY" != "$FOUNDATION_KEY"
   jq -e '.ServerSideEncryption == "aws:kms" and (.SSEKMSKeyId | type == "string" and length > 0)' "$FOUNDATION_HEAD" >/dev/null
   ARCHIVE_KEY="nova-toll/v2/development/retirement-archives/state-${STATE_VERSION}.json"
   case "$ARCHIVE_KEY" in nova-toll/v2/development/retirement-archives/state-[A-Za-z0-9_-]*.json) ;; *) exit 1 ;; esac
   aws --region "$REGION" s3api copy-object \
     --bucket "$STATE_BUCKET" --key "$ARCHIVE_KEY" \
     --copy-source "$STATE_BUCKET/$STATE_KEY?versionId=$STATE_VERSION" \
     --metadata-directive COPY --server-side-encryption aws:kms --ssekms-key-id "$STATE_SSEKMS_KEY_ID" \
     >"$WORK_DIR/archive-copy.json"
   ARCHIVE_VERSION="$(jq -er '.VersionId | strings' "$WORK_DIR/archive-copy.json")"
   aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$ARCHIVE_KEY" --version-id "$ARCHIVE_VERSION" >"$WORK_DIR/archive-head.json"
   jq -e --arg cmk "$STATE_SSEKMS_KEY_ID" '.ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $cmk' "$WORK_DIR/archive-head.json" >/dev/null
   aws --region "$REGION" s3api get-object --bucket "$STATE_BUCKET" --key "$STATE_KEY" --version-id "$STATE_VERSION" "$SOURCE_STATE" >/dev/null
   aws --region "$REGION" s3api get-object --bucket "$STATE_BUCKET" --key "$ARCHIVE_KEY" --version-id "$ARCHIVE_VERSION" "$ARCHIVE_STATE_PRIVATE" >/dev/null
   test "$(sha256sum "$SOURCE_STATE" | awk '{print $1}')" = "$(sha256sum "$ARCHIVE_STATE_PRIVATE" | awk '{print $1}')"
   jq -e --arg serial "$STATE_SERIAL" --arg lineage "$STATE_LINEAGE" --arg version "$STATE_TERRAFORM_VERSION" \
     '.serial == ($serial | tonumber) and .lineage == $lineage and .terraform_version == $version and (.resources | type == "array" and all(.[]; .mode == "managed" or .mode == "data" or .mode == null))' \
     "$ARCHIVE_STATE_PRIVATE" >/dev/null
   git worktree add --detach "$COMPAT_ROOT" "$COMPATIBILITY_COMMIT"
   test "$(git -C "$COMPAT_ROOT" rev-parse HEAD)" = "$COMPATIBILITY_COMMIT"
   test "$(git -C "$COMPAT_ROOT" remote get-url origin 2>/dev/null)" = "$ORIGIN_URL"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" init -reconfigure -input=false \
     -backend-config="bucket=$STATE_BUCKET" -backend-config="key=$STATE_KEY" \
     -backend-config="region=$REGION" -backend-config="use_lockfile=true" \
     -backend-config="encrypt=true" -backend-config="kms_key_id=alias/nova-toll-tfstate" >/dev/null
   test "$(aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state list >"$WORK_DIR/state-list.txt"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state pull >"$LIVE_STATE_PRIVATE"
   # Parse the complete backend snapshot, rather than trusting text output.
   python3 "$ROOT/v2/scripts/validate_legacy_retirement_plan.py" --state "$LIVE_STATE_PRIVATE" --identity-manifest "$LIVE_IDENTITY_MANIFEST" --state-only
   python3 "$ROOT/v2/scripts/validate_legacy_retirement_plan.py" --state "$ARCHIVE_STATE_PRIVATE" --identity-manifest "$LIVE_IDENTITY_MANIFEST" --state-only
   jq -e --arg account "$EXPECTED_ACCOUNT" \
     '[.resources[] | select(.address == "cloudflare_dns_record.apex[0]" or .address == "cloudflare_dns_record.site_cert_validation[\"dev.tollchat.ai\"]" or .address == "aws_bedrock_guardrail.tollchat" or .address == "aws_bedrock_guardrail_version.tollchat")] | if length == 4 and all(.[]; .account_id == $account and (.address | type == "string") and (.id | type == "string" and length > 0)) then . else error("retained identity cardinality") end' \
     "$LIVE_IDENTITY_MANIFEST" >"$WORK_DIR/retained-identities.json"
   # One exact multi-address invocation obtains one Terraform lock for all four
   # retained addresses; do not retry or restore from the archive automatically.
   assert_current_state "$STATE_VERSION" "\"$STATE_ETAG\"" "$WORK_DIR/head-before-detach.json"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state rm \
     'cloudflare_dns_record.apex[0]' \
     'cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"]' \
     'aws_bedrock_guardrail.tollchat' \
     'aws_bedrock_guardrail_version.tollchat'
   aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY" >"$WORK_DIR/head-after-detach.json"
   PLAN_STATE_VERSION="$(jq -er '.VersionId | strings' "$WORK_DIR/head-after-detach.json")"
   PLAN_STATE_ETAG="$(jq -er '.ETag | strings' "$WORK_DIR/head-after-detach.json")"
   test "$PLAN_STATE_VERSION" != "$STATE_VERSION"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state pull >"$LIVE_STATE_AFTER_DETACH"
   PLAN_STATE_SERIAL="$(jq -er '.serial | numbers' "$LIVE_STATE_AFTER_DETACH")"
   test "$PLAN_STATE_SERIAL" -gt "$STATE_SERIAL"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state list >"$WORK_DIR/state-list-after-detach.txt"
   for address in \
     'cloudflare_dns_record.apex[0]' \
     'cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"]' \
     'aws_bedrock_guardrail.tollchat' \
     'aws_bedrock_guardrail_version.tollchat'; do
     if grep -Fqx "$address" "$WORK_DIR/state-list-after-detach.txt"; then
       exit 1
     fi
   done
   assert_current_state "$PLAN_STATE_VERSION" "$PLAN_STATE_ETAG" "$WORK_DIR/head-before-plan.json"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" plan -destroy -input=false -out="$DESTROY_PLAN" >/dev/null
   assert_current_state "$PLAN_STATE_VERSION" "$PLAN_STATE_ETAG" "$WORK_DIR/head-before-plan-render.json"
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" show -json "$DESTROY_PLAN" >"$DESTROY_PLAN_JSON"
   python3 "$ROOT/v2/scripts/validate_legacy_retirement_plan.py" --state "$ARCHIVE_STATE_PRIVATE" --plan "$DESTROY_PLAN_JSON" --identity-manifest "$LIVE_IDENTITY_MANIFEST"
   chmod 400 "$DESTROY_PLAN" "$DESTROY_PLAN_JSON"
   plan_metadata() {
     stat -Lc '%d:%i:%u:%g:%a:%h:%F' -- "$1"
   }
   assert_plan_path() {
     test -f "$1"
     test ! -L "$1"
     test "$(plan_metadata "$1")" = "$PLAN_METADATA"
   }
   assert_plan_fd() {
     test -r "$PLAN_FD_PATH"
     test "$(plan_metadata "$PLAN_FD_PATH")" = "$PLAN_METADATA"
   }
   PLAN_METADATA="$(plan_metadata "$DESTROY_PLAN")"
   IFS=: read -r PLAN_DEVICE PLAN_INODE PLAN_UID PLAN_GID PLAN_MODE PLAN_LINKS PLAN_TYPE <<<"$PLAN_METADATA"
   test "$PLAN_UID" = "$(id -u)"
   test "$PLAN_GID" = "$(id -g)"
   test "$PLAN_MODE" = 400
   test "$PLAN_LINKS" = 1
   test "$PLAN_TYPE" = "regular file"
   PLAN_SHA256="$(sha256sum "$DESTROY_PLAN" | awk '{print $1}')"
   printf '%s\n' "$PLAN_SHA256" | grep -Eq '^[0-9a-f]{64}$'
   revalidate_before_apply() {
     test "${RETIRE_LEGACY_LIVE_IDENTITY_REVIEWED:-}" = YES
     test "$(git -C "$ROOT" remote get-url origin 2>/dev/null)" = "$ORIGIN_URL"
     test "$(git -C "$COMPAT_ROOT" rev-parse HEAD)" = "$COMPATIBILITY_COMMIT"
     test "$(git -C "$COMPAT_ROOT" remote get-url origin 2>/dev/null)" = "$ORIGIN_URL"
     assert_plan_path "$DESTROY_PLAN"
     assert_plan_fd
     CURRENT_PLAN_SHA256="$(sha256sum "$PLAN_FD_PATH" | awk '{print $1}')"
     test "$CURRENT_PLAN_SHA256" = "$PLAN_SHA256"
     assert_current_state "$PLAN_STATE_VERSION" "$PLAN_STATE_ETAG" "$WORK_DIR/head-immediately-before-render.json"
     terraform_prod -chdir="$COMPAT_ROOT/v2/infra" show -json "$PLAN_FD_PATH" >"$DESTROY_PLAN_APPLY_JSON"
     chmod 400 "$DESTROY_PLAN_APPLY_JSON"
     python3 "$ROOT/v2/scripts/validate_legacy_retirement_plan.py" --state "$ARCHIVE_STATE_PRIVATE" --plan "$DESTROY_PLAN_APPLY_JSON" --identity-manifest "$LIVE_IDENTITY_MANIFEST" >/dev/null
     assert_plan_fd
     test "$(sha256sum "$PLAN_FD_PATH" | awk '{print $1}')" = "$PLAN_SHA256"
     test "$(aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"
     assert_current_state "$PLAN_STATE_VERSION" "$PLAN_STATE_ETAG" "$WORK_DIR/head-immediately-before-apply.json"
     assert_plan_fd
   }
   if test "${RETIRE_LEGACY_TERRAFORM_APPLY_APPROVED:-}" = YES; then
     REVIEWED_PLAN_SHA256="${RETIRE_LEGACY_REVIEWED_PLAN_SHA256:?set the reviewed saved-plan SHA-256 after human approval}"
     printf '%s\n' "$REVIEWED_PLAN_SHA256" | grep -Eq '^[0-9a-f]{64}$'
     assert_plan_path "$DESTROY_PLAN"
     exec {PLAN_FD}<"$DESTROY_PLAN"
     PLAN_FD_PATH="/proc/self/fd/$PLAN_FD"
     assert_plan_fd
     REVIEWED_BINARY_PLAN_SHA256="$(sha256sum "$PLAN_FD_PATH" | awk '{print $1}')"
     test "$REVIEWED_BINARY_PLAN_SHA256" = "$REVIEWED_PLAN_SHA256"
     PLAN_SHA256="$REVIEWED_BINARY_PLAN_SHA256"
     revalidate_before_apply
     terraform_prod -chdir="$COMPAT_ROOT/v2/infra" apply "$PLAN_FD_PATH"
   fi
   )
   ```

   Replace each `EXPECTED_*` marker only with a value captured and reviewed
   during this invocation, and set `RETIRE_LEGACY_LIVE_IDENTITY_REVIEWED=YES`
   only after independent review of the fresh live manifest. If archive
   copy/readback, digest, metadata, state
   identity, or any exact state identity check fails, stop with the canonical state
   untouched and do not run a detach command.

   A state-lock/error result after the multi-address mutation, or any inability
   to prove the new VersionId, ETag, serial, and exact address absence, is an
   unknown outcome: stop without retrying and without automatically restoring
   from the archive. Any recovery or archive restore requires human
   reconciliation of the canonical unversioned state against the retained,
   version-specific archive evidence.

5. Use an ephemeral detached checkout of immutable compatibility revision
   `4c1f684`, its checked-in provider lockfile, and the legacy production
   backend key `nova-toll/v2/development/terraform.tfstate`. Initialize and
   refresh only after the account/backend assertions. Run one saved full
   `terraform plan -destroy`; do not use a second permanent root or regenerate
   the binary plan at apply time. Render its JSON and run the pure local
   validator:

   The validator command in the bounded block is the authoritative invocation;
   it uses the in-scope `ARCHIVE_STATE_PRIVATE`, saved plan JSON, and required
   independent `LIVE_IDENTITY_MANIFEST`. Record the SHA-256 of the saved binary
   plan, then have the human reviewer approve that exact digest. Immediately
   before the first detach, the unversioned canonical state object's current
   `VersionId` and ETag must equal the captured `STATE_VERSION` and
   `STATE_ETAG`. After the multi-address detach, capture the new unversioned
   current `PLAN_STATE_VERSION`/ETag and serial actually used by the plan (and
   require the VersionId differs and serial advances from `STATE_SERIAL`); any
   newer/current mismatch fails closed.
   before a separately authorized apply, the guarded
   `revalidate_before_apply` function opens the mode-0400 binary read-only,
   verifies its device/inode/owner/mode/link-count metadata and digest, asserts
   that same unversioned `PLAN_STATE_VERSION`/ETag immediately before each
   rendering and immediately before apply, renders fresh JSON from that same
   `/proc/self/fd/<descriptor>` inode, reruns the validator against the fresh
   rendering, and reasserts the canonical remote/source commit, source
   VersionId/ETag/CMK, and live-identity manifest.
   The apply receives that still-open read-only descriptor path, so replacement
   of the named plan path cannot swap the bytes being applied. Set
   `RETIRE_LEGACY_TERRAFORM_APPLY_APPROVED=YES` only after independent human
   approval and pass its reviewed digest as
   `RETIRE_LEGACY_REVIEWED_PLAN_SHA256`; otherwise the block performs no apply.

   It must report only a sanitized count/hash manifest: every managed
   non-no-op action is exactly one `delete`, each address and prior remote ID
   is present in the archived state, every non-retained instance is deleted
   once, and no create/update/replace/unknown action, unmanaged identity,
   foundation address, or new-account identity appears. Approved data sources
   are counted separately; their no-op/read refresh actions never enter the
   deletion digest. A plan error, drift, lifecycle block, incomplete inventory,
   or changed state VersionId stops before apply.

6. A human reviewer approves the validator manifest and exact remote identity
   allowlist. Only then may a separately authorized protected operator run the
   saved `terraform apply <saved-plan>`. The plan must be delete-only; it must
   not destroy the four retained objects, shared RDS, production roles,
   foundation resources, current development account, artifact/evidence data,
   or current `dev.tollchat.ai`. Refresh and check every legacy identity after
   apply, then require clean production application/foundation plans and
   unchanged new-development state/resource IDs. Preserve the archive and
   sanitized action/evidence manifest.

7. After old certificate/distribution retirement and rollback expiry, retain
   the old ACM validation record. Capture its exact reviewed
   `{id,name,type,content,ttl,proxied}` snapshot (including the canonical
   record ID) in the private retirement evidence and record the explicit reason
   for retention: the protected Cloudflare workflow has no safe compare-and-swap delete operation,
   and deleting a validation record is not required for the resource retirement.
   This explicit retention decision supersedes checklist requirement 7's former
   destructive DNS design because Cloudflare provides no compare-and-swap delete.
   Reconcile that snapshot read-only if needed; do
   not call Cloudflare to delete it. The existing protected workflow remains
   limited to its prior POST/PUT-only stage, cutover, and rollback behavior;
   it has no retirement operation, DELETE path, or new workflow inputs.

8. Database retirement is a separate approved automation action, never a
   manual SQL fallback, migration 030, bootstrap rollback, Terraform
   PostgreSQL/null resource, runtime role, wildcard, `CASCADE`, or
   `DROP ... IF EXISTS`. The only reviewed implementation is
   `v2/scripts/retire_legacy_development_database.py`. Its default is a
   read-only preflight; destructive mode requires both `--execute` and the
   literal `RETIRE_LEGACY_DEVELOPMENT_APPROVED=YES`. It uses only stdlib, the
   AWS CLI for fixed-account read-only identity/RDS checks, and `psql`; it
   requires the asserted RDS endpoint/port, `sslmode=verify-full`, and the
   reviewed CA bundle.

   The production wrapper below is the credential boundary and creates a
   reviewed, runbook-verified handoff manifest. The read-only
   preflight first, then obtain separate approval before adding `--execute`.
   The fetched secret, username, password, endpoint, CA, raw SQL, and psql
   stderr stay in process memory; no value is a file, argument, plan, or
   evidence. The wrapper asserts profile/account/region, one private available
   `nova-toll-db`, PostgreSQL engine major version 17, the managed master-secret
   ARN, and the CA SHA-256 before invoking the script against `postgres`. The
   script itself repeats fixed
   account/region and `nova-toll-db` `DescribeDBInstances` checks immediately
   before preflight, and rejects any handoff endpoint, port, managed secret ARN,
   or caller account that differs from that fresh API truth. It does not accept
   a standalone target or ambient `PG*` variables; it uses only the two
   short-lived `RETIRE_LEGACY_DB_*` credential variables set by this wrapper.
   The script pins the reviewed CA SHA-256
   `e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3` and
   requires both the handoff digest and actual CA file digest to equal it.

   ```sh
   (
   set -euo pipefail
   set +x
   umask 077
   EXPECTED_ACCOUNT=920534282028
   REGION=us-east-1
   EXPECTED_AWS_PROFILE=nova-toll-prod
   ROOT="$(git rev-parse --show-toplevel)"
   GIT_COMMON_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
   PROJECT_ROOT="$(dirname "$GIT_COMMON_DIR")"
   DB_INSTANCE=nova-toll-db
   CA_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
   CA_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
   mkdir -p "$PROJECT_ROOT/.worktrees"
   WORK_DIR="$(mktemp -d "$PROJECT_ROOT/.worktrees/nova-toll-333-db-XXXXXX")"
   CA_FILE="$WORK_DIR/global-bundle.pem"
   HANDOFF="$WORK_DIR/legacy-db-handoff.json"
   RDS_JSON= SECRET_JSON= DB_HOST= DB_PORT= DB_USER= DB_PASSWORD=
   cleanup() { unset DB_PASSWORD DB_USER SECRET_JSON SECRET_ARN RDS_JSON RETIRE_LEGACY_DB_PASSWORD RETIRE_LEGACY_DB_USER; rm -rf -- "$WORK_DIR"; }
   trap cleanup EXIT
   trap 'exit 130' HUP INT TERM
   for variable in $(compgen -A variable AWS_); do
     test -z "${!variable-}"
   done
   export AWS_PROFILE="$EXPECTED_AWS_PROFILE"
   export AWS_DEFAULT_REGION=us-east-1
   export AWS_REGION=us-east-1
   test "$(aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"
   RDS_JSON="$(AWS_PROFILE="$AWS_PROFILE" aws --region "$REGION" rds describe-db-instances \
     --db-instance-identifier "$DB_INSTANCE" --query DBInstances --output json)"
   printf '%s\n' "$RDS_JSON" | jq -e --arg account "$EXPECTED_ACCOUNT" --arg instance "$DB_INSTANCE" '
     type == "array" and length == 1 and .[0].DBInstanceIdentifier == $instance and
     .[0].DBInstanceStatus == "available" and .[0].Engine == "postgres" and
     (.[0].EngineVersion | type == "string" and test("^17([.]|$)")) and
     .[0].PubliclyAccessible == false and
     (.[0].Endpoint.Address | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9.-]*[.]rds[.]amazonaws[.]com$")) and
     (.[0].Endpoint.Port | type == "number" and floor == . and . > 0 and . < 65536) and
     (.[0].MasterUserSecret.SecretArn | type == "string" and test("^arn:aws:secretsmanager:us-east-1:920534282028:secret:[^[:space:]]+$"))
   ' >/dev/null
   DB_HOST="$(jq -er '.[0].Endpoint.Address' <<<"$RDS_JSON")"
   DB_PORT="$(jq -er '.[0].Endpoint.Port | tostring' <<<"$RDS_JSON")"
   SECRET_ARN="$(jq -er '.[0].MasterUserSecret.SecretArn' <<<"$RDS_JSON")"; unset RDS_JSON
   curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$CA_URL" --output "$CA_FILE"
   printf '%s  %s\n' "$CA_SHA256" "$CA_FILE" | sha256sum --check --status
   jq -n --arg manifest legacy-db-handoff-v1 --arg account "$EXPECTED_ACCOUNT" \
     --arg region "$REGION" --arg instance "$DB_INSTANCE" --arg host "$DB_HOST" \
     --argjson port "$DB_PORT" --arg ca_sha256 "$CA_SHA256" --arg secret_arn "$SECRET_ARN" \
     '{manifest: $manifest, account_id: $account, region: $region, instance_identifier: $instance, host: $host, port: $port, ca_sha256: $ca_sha256, secret_arn: $secret_arn}' >"$HANDOFF"
   chmod 600 "$HANDOFF"
   SECRET_JSON="$(AWS_PROFILE="$AWS_PROFILE" aws --region "$REGION" secretsmanager get-secret-value \
     --secret-id "$SECRET_ARN" --query SecretString --output text)"
   jq -e '.username | type == "string" and length > 0 and test("^[^[:space:]]+$")' <<<"$SECRET_JSON" >/dev/null
   jq -e '.password | type == "string" and length > 0' <<<"$SECRET_JSON" >/dev/null
   DB_USER="$(jq -er .username <<<"$SECRET_JSON")"; DB_PASSWORD="$(jq -er .password <<<"$SECRET_JSON")"; unset SECRET_JSON SECRET_ARN
   export RETIRE_LEGACY_HANDOFF_APPROVED=YES
   export RETIRE_LEGACY_DB_USER="$DB_USER" RETIRE_LEGACY_DB_PASSWORD="$DB_PASSWORD"
   python3 "$ROOT/v2/scripts/retire_legacy_development_database.py" --host "$DB_HOST" --port "$DB_PORT" --ca-file "$CA_FILE" --handoff "$HANDOFF"
   # After independent review and approval only:
   # RETIRE_LEGACY_DEVELOPMENT_APPROVED=YES python3 ... --host "$DB_HOST" --port "$DB_PORT" --ca-file "$CA_FILE" --handoff "$HANDOFF" --execute
   unset RETIRE_LEGACY_HANDOFF_APPROVED RETIRE_LEGACY_DB_USER RETIRE_LEGACY_DB_PASSWORD DB_USER DB_PASSWORD
   )
   ```

   SQL preflight and postflight require production database `nova_toll` and
   exactly its six production roles and isolation/role-shape invariants to
   remain present. They require exactly database `nova_toll_development` with
   comment `environment=development` and exactly the six development roles
   `pricing_loader_writer_development`, `pricing_reader_development`,
   `oracle_owner_development`, `tollchat_agent_development`,
   `pricing_caller_development`, and `report_publisher_development`. Unknown
   ownership, membership, dependency, foreign server/user mapping, extension,
   external integration, login/admin attribute, or production-contract change
   stops the action. The positive development baseline also requires the
   six production roles to have `CONNECT` on `nova_toll` and no
   development-role cross-grant, and all six development roles to have
   `CONNECT` on `nova_toll_development` only. After the database and each
   role mutation, the postcondition requires all six production roles to
   retain `CONNECT` on `nova_toll`.
   The exact shared labels are `shobj_description` values
   `environment=production` for `nova_toll` and `environment=development` for
   `nova_toll_development`; each development role's `shobj_description` value
   is NULL. The reviewed database and schema owners, exact ACL grants, and
   shared dependencies are checked before every destructive phase. Object
   ownership permits only the ordinary database owner and six development
   roles, the `pg_database_owner` public namespace owner, and the narrow
   catalog-registered structural closure of `plpgsql` and `postgis`; those
   extensions must both be owned by pinned `rdsadmin`, with PostGIS in
   `oracle`. No subscriptions, publications, replication slots, foreign
   wrappers/tables, user mappings, event triggers, or unreviewed catalog
   dependencies are accepted. The
   script executes only
   `DROP DATABASE nova_toll_development WITH (FORCE)`, verifies the database
   is absent and production is unchanged, then drops each exact development
   role with a dependency check and verifies the remaining exact set after
   each statement. It never wraps the database drop in a transaction.
   The disposable `bootstrap_development_database.py` contract creates the
   database comment and these six exact role comments before granting
   development `CONNECT`; it is not a production retirement step.

   A connection loss or error after any attempted mutation is an unknown
   outcome: the script performs one read-only status query if possible, takes
   no retry or next destructive step, and stops for human reconciliation.
   Retain only fixed pass/fail/count/hash evidence. Do not retain SQL output,
   psql stderr, credentials, endpoint secrets, or authorization headers.

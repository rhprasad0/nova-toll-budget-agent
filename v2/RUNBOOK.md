# AgentCore deployment

Deployments are manual. CI builds and tests the application but never runs a
Terraform plan or apply.

## Delivery contract and production baseline

PRs use disposable PostGIS migration validation only; they never access or
mutate deployed databases or schemas. `main` continues to run validation only.
Published releases are manual, reviewed deployments from `main`. The sole
schema-change exception is the separately authorized, reviewed migration 030
procedure below; no other schema-changing release is authorized here, and
future exceptions require approved deployment automation. Application release
artifacts do not apply schema changes; this procedure is separate.

The current production baseline is AWS account `920534282028` in `us-east-1`:

- Foundation state: `s3://nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate`.
- Application state: `s3://nova-toll-tfstate-920534282028/nova-toll/v2/terraform.tfstate`.
- PostgreSQL: `nova-toll-db` / `nova_toll`; reporting Glue database:
  `tollchat_agent_reports`; session table: `tollchat-v2-anonymous-sessions`.
- Public domains: `tollchat.ai` and `www.tollchat.ai`; fixed dependencies include
  `nova-toll-rds`, `nova-toll-private-a`, `nova-toll-private-c`,
  `nova-toll-agentcore-endpoint`, and `nova-toll-eventbridge-endpoint`.
- Default application tags are `project = nova-toll-budget-agent`, `version = v2`,
  and `environment = production`. Production foundation resources use
  `environment = shared`; any `shared_with = development` tag is descriptive
  only and grants no development-account access.
- Release artifacts overwrite `s3://nova-toll-agentcore-920534282028/runtime/v2/agentcore.zip`
  and `s3://nova-toll-agentcore-920534282028/lambda/v2/chat-proxy.zip`; retained
  S3 object versions are the rollback source.
- Stable release targets are the `live` alias of `tollchat-v2-chat-proxy` and
  the `preview` endpoint of AgentCore runtime `nova_toll_v2`.
- Development is owned by AWS account `903859731897` (`nova-toll-development`)
  with its own foundation and application state backends. It consumes only a
  reviewed non-secret foundation handoff from that account; it has no AWS read
  path into production account `920534282028`.

Before release apply, require the foundation plan to be zero-change. Review every
action in the saved candidate application plan against intended reviewed release
changes. Stop on any unexplained action or any replacement.

## Manual Oracle migration 030

Migration `v2/db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql` is the
only currently approved manual schema change. Applying it requires separate,
explicit operator authorization and a reviewed checkout containing that exact
file. This procedure is not a PR or CI step: PRs remain offline and use only
disposable PostgreSQL migration validation.

Before starting, confirm all of the following in the operator's environment;
these are runtime preconditions, not repository-verified facts:

- The operator is authorized for this change and is using an authenticated
  `nova-toll-prod` profile in AWS account `920534282028`, region `us-east-1`.
- The reviewed checkout is the intended checkout, the terminal/session is
  non-traced, and `aws`, `git`, `jq`, `psql`, `curl`, and `sha256sum` are
  available.
- The operator has private-network/Tailscale reachability to the private RDS
  endpoint. Do not continue when any precondition is false.

The block below is the one copy/paste procedure. It reads the current endpoint,
port, and managed secret ARN from the one `nova-toll-db` instance using
read-only RDS metadata. It validates the expected account, available/private
target, managed `SecretString`, and username/password before any connection.
Secret data is captured only in the non-traced process memory, never printed,
logged, redirected to a file, persisted, placed in an argument, or recorded as
evidence.
The only credential delivery is the `PGUSER`/`PGPASSWORD` environment of each
`psql` process. The temporary CA is removed by the exit trap.

If `psql` reports a SQL error before `COMMIT`, the migration transaction rolls
back. A connection loss during or after `COMMIT` makes the outcome unknown. The
block stops and queries the exact target state before retrying an apply or
starting recovery; do not retry blindly or treat an application/artifact
rollback as a database downgrade.

The source check must pass immediately before each apply: pricing `1.3.0`,
Oracle `1.13.1`, exactly 995 total `oracle.toll_connection` rows, exactly 13
`toll_handoff` rows, and no `i495_1829_to_dulles_toll_road` row. The postcheck
must pass after each apply: pricing `1.3.0`, Oracle `1.14.0`, exactly 996 total
connections, exactly 14 handoffs, and one target handoff with the complete
IDs, `toll_handoff` type, null direction/source key, and curated source
metadata. The development apply and postcheck complete before the production
source check or apply; stop at the first failure. If this block is resumed,
each environment accepts only its exact source state (apply and postcheck) or
its exact target state (verify and skip); every other or corrupt state is
rejected.

```sh
(
set -euo pipefail
set +x

EXPECTED_ACCOUNT=920534282028
DB_INSTANCE_IDENTIFIER=nova-toll-db
MIGRATION_RELATIVE=v2/db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql
CA_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
CA_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
CA_FILE=
MIGRATION_SHA256=101ee53eb4e37f00e4bf711d9c97bf97b4c53981f5b0a6bd7a932cfea9ecee40
RDS_METADATA=
SECRET_ARN=
SECRET_JSON=
DB_HOST=
DB_PORT=
DB_USER=
DB_PASSWORD=

cleanup() {
  unset DB_PASSWORD DB_USER SECRET_JSON SECRET_ARN RDS_METADATA PGPASSWORD
  if [ -n "${CA_FILE:-}" ]; then
    rm -f -- "$CA_FILE"
  fi
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

for command_name in aws git jq psql curl sha256sum; do
  command -v "$command_name" >/dev/null
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
MIGRATION="$REPO_ROOT/$MIGRATION_RELATIVE"
test -f "$MIGRATION"
test ! -L "$MIGRATION"
printf '%s  %s\n' "$MIGRATION_SHA256" "$MIGRATION" | sha256sum --check --status
test "$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 \
  sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"

RDS_METADATA="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 \
  rds describe-db-instances --db-instance-identifier nova-toll-db \
  --query 'DBInstances' --output json)"
printf '%s\n' "$RDS_METADATA" | jq -e --arg expected "$DB_INSTANCE_IDENTIFIER" '
  type == "array" and length == 1 and
  .[0].DBInstanceIdentifier == $expected and
  .[0].DBInstanceStatus == "available" and
  .[0].PubliclyAccessible == false and
  (.[0].Endpoint.Address | type == "string" and
    . != "None" and
    test("^[A-Za-z0-9][A-Za-z0-9.-]*[.]rds[.]amazonaws[.]com$")) and
  (.[0].Endpoint.Port | type == "number" and floor == . and . > 0 and . < 65536) and
  (.[0].MasterUserSecret.SecretArn | type == "string" and
    test("^arn:aws:secretsmanager:us-east-1:920534282028:secret:[^[:space:]]+$"))
' >/dev/null
DB_HOST="$(jq -er '.[0].Endpoint.Address' <<<"$RDS_METADATA")"
DB_PORT="$(jq -er '.[0].Endpoint.Port | tostring' <<<"$RDS_METADATA")"
SECRET_ARN="$(jq -er '.[0].MasterUserSecret.SecretArn' <<<"$RDS_METADATA")"
unset RDS_METADATA

CA_FILE="$(mktemp)"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  "$CA_URL" --output "$CA_FILE"
if ! printf '%s  %s\n' "$CA_SHA256" "$CA_FILE" | sha256sum --check --status; then
  printf '%s\n' 'RDS CA bundle digest mismatch; stop and review the approved CA source.' >&2
  exit 1
fi

SECRET_JSON="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 \
  secretsmanager get-secret-value --secret-id "$SECRET_ARN" \
  --query SecretString --output text)"
jq -e '
  type == "object" and
  (.username | type == "string" and length > 0 and test("^[^[:space:]]+$")) and
  (.password | type == "string" and length > 0)
' <<<"$SECRET_JSON" >/dev/null
DB_USER="$(jq -er '.username' <<<"$SECRET_JSON")"
DB_PASSWORD="$(jq -er '.password' <<<"$SECRET_JSON")"

source_state() {
  local database="$1"
  PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD" \
    PGSSLMODE=verify-full PGSSLROOTCERT="$CA_FILE" PGDATABASE="$database" \
    psql -X --set ON_ERROR_STOP=1 --tuples-only --no-align --quiet <<'SQL'
SELECT
  (SELECT version FROM pricing.schema_version WHERE singleton) || '|' ||
  (SELECT version FROM oracle.schema_version WHERE singleton) || '|' ||
  (SELECT count(*)::text FROM oracle.toll_connection) || '|' ||
  (SELECT count(*)::text FROM oracle.toll_connection
   WHERE connection_type = 'toll_handoff') || '|' ||
  (SELECT count(*)::text FROM oracle.toll_connection
   WHERE connection_id = 'i495_1829_to_dulles_toll_road');
SQL
}

target_state() {
  local database="$1"
  PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD" \
    PGSSLMODE=verify-full PGSSLROOTCERT="$CA_FILE" PGDATABASE="$database" \
    psql -X --set ON_ERROR_STOP=1 --tuples-only --no-align --quiet <<'SQL'
SELECT
  (SELECT version FROM pricing.schema_version WHERE singleton) || '|' ||
  (SELECT version FROM oracle.schema_version WHERE singleton) || '|' ||
  (SELECT count(*)::text FROM oracle.toll_connection) || '|' ||
  (SELECT count(*)::text FROM oracle.toll_connection
   WHERE connection_type = 'toll_handoff') || '|' ||
  (SELECT count(*)::text FROM oracle.toll_connection
   WHERE connection_id = 'i495_1829_to_dulles_toll_road') || '|' ||
  (SELECT count(*)::text FROM oracle.toll_connection
   WHERE connection_id = 'i495_1829_to_dulles_toll_road'
     AND from_point_id = 'i495:1829ND'
     AND to_point_id = 'dtr:1819:entry:WB'
     AND connection_type = 'toll_handoff'
     AND required_i95_direction IS NULL
     AND source_route_key IS NULL
     AND source_metadata = '{"basis":"v2/db/oracle/CONTRACT.md","curated":true}'::jsonb);
SQL
}

require_target_state() {
  local database="$1" actual
  actual="$(target_state "$database")"
  test "$actual" = '1.3.0|1.14.0|996|14|1|1'
}

apply_migration() {
  local database="$1" actual
  if PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD" \
      PGSSLMODE=verify-full PGSSLROOTCERT="$CA_FILE" PGDATABASE="$database" \
      psql -X --set ON_ERROR_STOP=1 --quiet --file "$MIGRATION"; then
    return 0
  fi
  printf '%s\n' 'Apply outcome is unknown; querying exact target state before retry or recovery.' >&2
  if ! actual="$(target_state "$database")"; then
    printf '%s\n' 'Unable to query target state; stop for separately authorized incident handling.' >&2
    exit 1
  fi
  printf 'Observed post-failure state: %s\n' "$actual" >&2
  exit 1
}

process_environment() {
  local database="$1" source target
  source="$(source_state "$database")"
  if [ "$source" = '1.3.0|1.13.1|995|13|0' ]; then
    apply_migration "$database"
    require_target_state "$database"
    printf '%s migration and postcondition passed\n' "$database"
    return 0
  fi

  target="$(target_state "$database")"
  if [ "$target" = '1.3.0|1.14.0|996|14|1|1' ]; then
    printf '%s already has the exact target state; verifying and skipping\n' "$database"
    return 0
  fi
  printf 'Incompatible migration state for %s; stop without applying.\n' "$database" >&2
  exit 1
}

process_environment nova_toll_development
process_environment nova_toll
cleanup
)
```

SQL errors before `COMMIT` roll back the migration transaction. A connection
loss during or after `COMMIT` leaves the outcome unknown, so the exact target
state must be queried before retrying or recovering. A committed migration
cannot be downgraded or undone by application/artifact rollback; recovery
requires separately authorized RDS backup/PITR incident handling. This
procedure does not create backups, automatic rollback/downgrade, or evidence
artifacts.

## Environment-tag inventory and release safety

The active cost-allocation key is the lowercase `environment`. Its only values
are `development`, `production`, and `shared`. Production foundation resources
use `shared`; any existing `shared_with=development` tag is descriptive only
and grants no development-account access. Do not attempt Cost Explorer
activation. The two project-tagged KMS keys `640b50c9-72f7-4bd7-9a44-a00a59fc3f24`
and `74f426f1-6016-4969-922a-7f8b99763f45` are the only temporary exceptions:
both are `PendingDeletion` through 2026-09-22. Do not retag, cancel, or otherwise
change their lifecycle.

Before and after a release, inventory every Resource Groups Tagging API page
and retain only its sanitized page/resource/value counts. The foundation plan
must be zero-change after this source update; never apply it. Save and inspect
each saved application plan as JSON, review every non-no-op action and sanitized
before/after semantic delta, then apply only that exact reviewed plan.
Keep ignored package builds and hash-identified saved plans until independent
review passes; never retain state, tokens, or raw plan JSON.

## Account-local foundation handoff

The foundation and application roots have independent state. The guarded
planned-output/temporary-`*.tfvars.json` handoff below is the production-only
release path: it initializes the production foundation backend, makes a
read-only production foundation plan, extracts only its reviewed non-secret
`foundation` value from planned output, and passes that value to the matching
production v2 plan with its reviewed package arguments. It asserts the
production account, reviews only the approved object shape, and removes its
distinct temporary file through an EXIT trap; no credentials or SSM values are
included. Do not use that generic planned-output or tfvars flow for
development. Development #330 uses the retained private exact-plan root,
binary plan, coupled manifest, local bootstrap, and encrypted backend migration
documented below; its state is not discovered through a foundation output.

The development foundation bootstrap is #330 and its application/database
bootstrap is #331. Cloudflare DNS reads and writes (zone lookup, ACM
certificate-validation records, and apex/www records) are production-only in
`v2/infra/site.tf`; development DNS/certificate validation belongs to #332.
`enable_public_dns = false` remains the production apex switch, while the
development path has no Cloudflare data or resource instances. Legacy
production-account development cleanup belongs to #333.

## Build and review

From `v2/`:

```sh
uv sync --locked
uv run pytest
npm ci --prefix lambdas/chat_proxy
npm test --prefix lambdas/chat_proxy
./scripts/build_loader_zip.sh
./scripts/build_publisher_zip.sh
./scripts/build_agentcore_zips.sh
./scripts/build_fetcher_zip.sh
(cd infra/build && sha256sum --check AGENTCORE_SHA256SUMS)
```

Before applying, set `RELEASE_EVIDENCE` to a unique per-release path (for
example, `build/release-evidence-20260829T120000Z.txt`). The file must be
retained with that release; capture never overwrites an existing record.

```sh
(
  set -eu
  : "${RELEASE_EVIDENCE:?set a unique release-evidence path}"
  test ! -e "$RELEASE_EVIDENCE"
  LAMBDA_LIVE_FUNCTION_VERSION="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 lambda get-alias \
    --function-name tollchat-v2-chat-proxy --name live --query FunctionVersion --output text)"
  AGENTCORE_RUNTIME_ID="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 bedrock-agentcore-control list-agent-runtimes \
    --query "agentRuntimes[?agentRuntimeName=='nova_toll_v2'].agentRuntimeId | [0]" --output text)"
  AGENTCORE_ENDPOINT_LIVE_VERSION="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 bedrock-agentcore-control get-agent-runtime-endpoint \
    --agent-runtime-id "$AGENTCORE_RUNTIME_ID" --endpoint-name preview --query liveVersion --output text)"
  case "$LAMBDA_LIVE_FUNCTION_VERSION" in ""|None|*[!0-9]*) exit 1 ;; esac
  case "$AGENTCORE_RUNTIME_ID" in ""|None|[!A-Za-z0-9]*|*[!A-Za-z0-9_-]*) exit 1 ;; esac
  case "$AGENTCORE_ENDPOINT_LIVE_VERSION" in ""|None|*[!0-9]*) exit 1 ;; esac
  printf 'lambda_live_function_version=%s\nagentcore_runtime_id=%s\nagentcore_endpoint_live_version=%s\n' \
    "$LAMBDA_LIVE_FUNCTION_VERSION" "$AGENTCORE_RUNTIME_ID" "$AGENTCORE_ENDPOINT_LIVE_VERSION" >"$RELEASE_EVIDENCE"
)
```

For the first usage-counter release only, stage the public disclosure and
hidden placeholder directly in the encrypted site bucket before deploying the
proxy package. Do not use Terraform resource targets for this step: the site
objects' KMS and CloudFront dependencies also pull the proxy and runtime into a
targeted plan.

```sh
SITE_BUCKET="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_KMS_ARN="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 kms describe-key \
  --key-id alias/tollchat-v2-site --query KeyMetadata.Arn --output text)"
EMPTY_USAGE="$(mktemp)"
printf '{}\n' >"$EMPTY_USAGE"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key index.html --body ../agent/dev_chat.html \
  --content-type 'text/html; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key faq.html --body ../agent/faq.html \
  --content-type 'text/html; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key privacy.txt --body ../agent/privacy.txt \
  --content-type 'text/plain; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key usage.json --body "$EMPTY_USAGE" \
  --content-type 'application/json; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
rm -f -- "$EMPTY_USAGE"
unset EMPTY_USAGE SITE_BUCKET SITE_KMS_ARN
curl --fail-with-body https://tollchat.ai/privacy.txt
curl --fail-with-body https://tollchat.ai/faq.html
```

For the first agent-route measurement release, publish and verify the updated
privacy notice before creating the release plan that enables WAF logging. This
is intentionally a separate operation: a Terraform dependency can order S3 and
WAF API calls, but it cannot prove the notice was already visible through the
deployed CloudFront surface.

```sh
SITE_BUCKET="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_KMS_ARN="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 kms describe-key \
  --key-id alias/tollchat-v2-site --query KeyMetadata.Arn --output text)"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key privacy.txt --body ../agent/privacy.txt \
  --content-type 'text/plain; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
curl --fail-with-body --silent --show-error https://tollchat.ai/privacy.txt \
  | grep -F 'TollChat keeps filtered raw route-report access logs and Athena query results for seven days.'
unset SITE_BUCKET SITE_KMS_ARN
```

## Development handoff and guarded production release

The bounded #331 application release and database validation below is the operative
development release path. Deployed database bootstrap remains non-operative until
approved deployment automation exists, except for the expressly authorized
#327/#333 development RDS replacement handoff below; the #331 procedure only
validates the already present development schema and isolation. Public report publication also remains
non-operative: the existing publisher and scheduler are deployed unchanged, but no
publication is manually invoked and no report data is copied. The #330 foundation
handoff remains the documented sequence of local-backend plan generation and review,
later exact-plan apply, and separately authorized state migration or recovery.
Cloudflare/DNS/CI cutover is owned by #332, and legacy cleanup remains owned by
#333. An AWS-only identity cannot write Cloudflare DNS.

### Development bootstrap/import boundary (#332)

Before the first recurring GitHub `development` run, a separately authorized
development-account administrator must inventory the live resources and create
or import them into the existing `v2/infra` root and the existing
`nova-toll/v2/development/terraform.tfstate` object. This is a one-time,
bounded bootstrap operation; it is not a second Terraform root, backend, or
state, and it never uses `-target` or `ignore_changes = all`.
This activation is a post-merge operator gate: review and merge this change
first, then run the procedure from a clean checkout of the protected
`origin/main`; no live bootstrap or recurring delivery is authorized from a
dirty feature worktree or before that merge.

The administrator owns the following addresses and their dependencies:

- all application `aws_iam_role.*`, `aws_iam_role_policy.*`, `aws_iam_policy.*`, and
  `aws_iam_role_policy_attachment.*` resources;
- `aws_bedrockagentcore_agent_runtime.tollchat`,
  `aws_bedrockagentcore_agent_runtime_endpoint.tollchat`, and every instance
  of `aws_bedrockagentcore_resource_policy.tollchat`;
- `aws_s3_bucket.agent_measurement`,
  `aws_s3_bucket_public_access_block.agent_measurement`,
  `aws_s3_bucket_policy.agent_measurement`,
  `aws_kms_key.agent_measurement`, and `aws_kms_alias.agent_measurement`;
- `aws_lambda_function_url.public_chat`,
  `aws_lambda_permission.public_chat_url`, and
  `aws_lambda_permission.public_chat_invoke`;
- the site KMS key/alias, site bucket policy, CloudFront distribution and
  origin controls, WAF, and other dependent exposure resources when they are
  absent from the application state.

For every item, retain only a non-secret live identifier, the normal Terraform
address, and a development-only refresh/read result. A missing resource or
import is a bootstrap failure. The administrator fixes it at that address and
does not widen the OIDC role. The bootstrap administrator also applies the
required `environment=development` and `version=v2` tags to application KMS
keys before enabling CI; the delivery role's exact allowlist is stored in seven
customer-managed policies `nova-toll-v2-development-delivery-{state,compute,observability,storage,data,runtime,edge}`
under path `/nova-toll/v2/development/`, attached only to that role. These policies use the two
exact application key ARNs and cannot retarget an alias to a foundation or
state key.

The following is the executable, fail-closed inventory and repair procedure.
Run it from this checkout as a development-account administrator. It writes
only non-secret inventory and Terraform state; it refuses every profile other
than `nova-toll-dev`, refuses any account other than `903859731897`, and never
uses a Terraform target or a second state. Leave `BOOTSTRAP_APPROVED` unset while
reviewing the inventory, rendered documents, and exact commands; set it to `YES`
only after the listed create/import/rollback commands have been reviewed. The
procedure fetches `origin/main`, derives the reviewed commit from that trusted
remote, and requires a clean checkout at that exact commit before any admin
command or package build. A feature worktree must stop at this gate.

The versioned development state bucket uses SSE-KMS. The bootstrap
administrator's exact minimum policy for this lock is
`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, and
`s3:DeleteObjectVersion`, all on the one lock object
`arn:aws:s3:::nova-toll-tfstate-903859731897/nova-toll/v2/development/bootstrap-lock`.
The only KMS permission needed is `kms:GenerateDataKey` on the exact key ARN
returned by `aws --region us-east-1 kms describe-key --key-id
alias/nova-toll-tfstate --query KeyMetadata.Arn --output text`, conditioned on
`kms:EncryptionContext:aws:s3:arn` equal to that lock ARN. The procedure never
reads lock bytes, so it needs no `kms:Decrypt`, wildcard KMS action, bucket
listing, or object-version read permission. The recurring delivery role has no
permission on this object.
The lock uses the
existing versioned development Terraform-state bucket and S3 conditional
requests: `PutObject --if-none-match '*'` acquires it, and
`DeleteObject --if-match` plus the returned version ID (when present) releases
it. A crashed run leaves the object in place: a new run must stop. Manual stale
recovery is allowed only after proving no bootstrap invocation is active,
recording the observed ETag/version without logging the owner value, and
obtaining explicit approval for the exact fixed-key conditional delete. There
is no overwrite, expiry, retry, or lock stealing. The approved operator command
must use the observed values (and never a value fetched before the no-invocation
check), for example:
`aws --region us-east-1 s3api delete-object --bucket nova-toll-tfstate-903859731897
--key nova-toll/v2/development/bootstrap-lock --if-match OBSERVED_ETAG
--version-id OBSERVED_VERSION_ID`; a versionless bucket uses only `--if-match`.

```sh
set -euo pipefail
umask 077

ROOT="$(git rev-parse --show-toplevel)"
EXPECTED_PROFILE="nova-toll-dev"
EXPECTED_ACCOUNT="903859731897"
REGION="us-east-1"
ROLE_NAME="nova-toll-v2-development-delivery"
FUNCTION_NAME="tollchat-v2-chat-proxy-dev"
QUALIFIER="tollchat_live"
DISTRIBUTION_ID="E33DVF3KT7BTAC"
DISTRIBUTION_DOMAIN="d1wqry4fbd92w5.cloudfront.net"
: "${AWS_PROFILE:?invoke this procedure with AWS_PROFILE=nova-toll-dev}"

die() { printf 'bootstrap stopped: %s\n' "$*" >&2; exit 1; }
assert_dev_account() {
  test "$AWS_PROFILE" = "$EXPECTED_PROFILE" || die "unexpected AWS profile before mutation"
  test "${AWS_REGION:-}" = "$REGION" || die "unexpected AWS region before mutation"
  test "${AWS_DEFAULT_REGION:-}" = "$REGION" || die "unexpected AWS region before mutation"
  test "$(aws sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT" ||
    die "unexpected caller account before mutation"
}
test "$(git -C "$ROOT" rev-parse --show-toplevel)" = "$ROOT" ||
  die "checkout root could not be verified"
test "$AWS_PROFILE" = "$EXPECTED_PROFILE" || die "unexpected AWS profile"
case "$AWS_PROFILE" in *prod*|*production*) die "production profile rejected" ;; esac
if test -n "${AWS_REGION:-}" && test "$AWS_REGION" != "$REGION"; then
  die "AWS_REGION must be us-east-1"
fi
if test -n "${AWS_DEFAULT_REGION:-}" && test "$AWS_DEFAULT_REGION" != "$REGION"; then
  die "AWS_DEFAULT_REGION must be us-east-1"
fi
if test -n "${AWS_REGION:-}" && test -n "${AWS_DEFAULT_REGION:-}" &&
  test "$AWS_REGION" != "$AWS_DEFAULT_REGION"; then
  die "AWS_REGION and AWS_DEFAULT_REGION conflict"
fi
export AWS_PROFILE="$EXPECTED_PROFILE"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ORIGIN_URL="$(git -C "$ROOT" remote get-url origin 2>/dev/null)" || die "trusted origin is not configured"
case "$ORIGIN_URL" in
  git@github.com:rhprasad0/nova-toll-budget-agent.git|https://github.com/rhprasad0/nova-toll-budget-agent.git) ;;
  *) die "origin URL is not the trusted repository" ;;
esac
git -C "$ROOT" fetch --no-tags origin main || die "could not fetch trusted origin/main"
PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse refs/remotes/origin/main)"
printf '%s' "$PROTECTED_MAIN_COMMIT" | grep -Eq '^[0-9a-f]{40}$' || die "origin/main is not a commit SHA"
test "$(git -C "$ROOT" rev-parse HEAD)" = "$PROTECTED_MAIN_COMMIT" ||
  die "checkout is not the fetched protected origin/main commit"
test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ||
  die "checkout has tracked or untracked changes; run only from clean protected origin/main"
git -C "$ROOT" diff --quiet HEAD -- || die "tracked checkout changes are not permitted"
git -C "$ROOT" diff --cached --quiet HEAD -- || die "staged checkout changes are not permitted"
CALLER_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
test "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT" || die "unexpected caller account"
: "${TF_VAR_budget_notification_email:?set a non-secret development notification address}"
test "${TF_VAR_tailscale_advertise_routes:-false}" = false ||
  die "development bootstrap must disable Tailscale route advertisement"

EVIDENCE_DIR="${BOOTSTRAP_EVIDENCE_DIR:?set an evidence directory outside this checkout}"
case "$EVIDENCE_DIR" in
  /*) ;;
  *) die "evidence directory must be an absolute path" ;;
esac
EVIDENCE_DIR="$(realpath -m -- "$EVIDENCE_DIR")" || die "evidence directory cannot be resolved"
case "$EVIDENCE_DIR" in "$ROOT"|"$ROOT"/*) die "evidence must be outside checkout" ;; esac
mkdir -p -- "$EVIDENCE_DIR"
chmod 700 -- "$EVIDENCE_DIR"
INVENTORY="$EVIDENCE_DIR/inventory.json"
test ! -e "$INVENTORY" || die "refusing to overwrite inventory"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tollchat-dev-bootstrap.XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT

FETCHER_BUILD="$ROOT/v2/scripts/build_fetcher_zip.sh"
FETCHER_INPUT="$ROOT/v2/lambdas/fetcher/handler.py"
FETCHER_PACKAGE="$ROOT/infra/build/fetcher.zip"
CANONICAL_FETCHER_SHA256="9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"
EXPECTED_FETCHER_SHA256="${EXPECTED_FETCHER_SHA256:?set the reviewed canonical fetcher SHA-256}"
REVIEWED_COMMIT="$PROTECTED_MAIN_COMMIT"
git -C "$ROOT" cat-file -e "$REVIEWED_COMMIT^{commit}" || die "trusted origin/main commit is not present"
test "$EXPECTED_FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256" ||
  die "expected fetcher digest is not the reviewed canonical value"
require_reviewed_file() {
  local path="$1" relative
  test -f "$path" && test ! -L "$path" || die "build input must be a regular non-symlink file: $path"
  relative="${path#"$ROOT"/}"
  test "$relative" != "$path" || die "build input must be inside the reviewed checkout"
  test "$(git -C "$ROOT" ls-files -- "$relative")" = "$relative" ||
    die "build input is not tracked by the reviewed commit: $relative"
  test -z "$(git -C "$ROOT" status --porcelain -- "$relative")" ||
    die "build input is modified or untracked: $relative"
  test -z "$(git -C "$ROOT" ls-files --others --exclude-standard -- "$relative")" ||
    die "build input is untracked: $relative"
  git -C "$ROOT" diff --quiet "$REVIEWED_COMMIT" -- "$relative" ||
    die "build input differs from reviewed protected-main: $relative"
  git -C "$ROOT" diff --cached --quiet -- "$relative" ||
    die "staged build input differs from reviewed protected-main: $relative"
}
require_reviewed_file "$FETCHER_BUILD"
require_reviewed_file "$FETCHER_INPUT"
test -d "$ROOT/infra/build" && test ! -L "$ROOT/infra/build" || die "fetcher output directory must be a regular directory"
test ! -L "$FETCHER_PACKAGE" || die "fetcher output must not be a symlink"
test ! -L "$ROOT/infra/build/fetcher" || die "fetcher staging directory must not be a symlink"
test -x "$FETCHER_BUILD" || die "canonical fetcher build script is not executable"
env -i PATH="/usr/bin:/bin" LC_ALL=C "$FETCHER_BUILD" >"$WORK_DIR/fetcher-build.log"
test -f "$FETCHER_PACKAGE" && test -s "$FETCHER_PACKAGE" ||
  die "canonical fetcher artifact is missing or empty"
test "$(readlink -f -- "$FETCHER_PACKAGE")" = "$FETCHER_PACKAGE" ||
  die "canonical fetcher artifact must not be a symlink"
test "$(basename -- "$FETCHER_PACKAGE")" != placeholder.zip ||
  die "placeholder fetcher artifact is not permitted"
FETCHER_SHA256="$(sha256sum "$FETCHER_PACKAGE" | awk '{print $1}')"
test "$FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256" ||
  die "canonical fetcher digest does not match operator evidence"

one() {
  local label="$1"; shift
  local result
  result="$("$@")"
  jq -e 'type == "array" and length == 1' <<<"$result" >/dev/null ||
    die "$label is missing or ambiguous"
  jq -c '.[0]' <<<"$result"
}

printf '%s\n' '{' >"$INVENTORY"
printf '  "account": "%s",\n' "$CALLER_ACCOUNT" >>"$INVENTORY"
printf '  "api": ' >>"$INVENTORY"
one api aws apigateway get-rest-apis --query 'items[?id==`ocw8sg0wlb`].{id:id,name:name}' --output json >>"$INVENTORY"
printf ',\n  "guardrail": ' >>"$INVENTORY"
one guardrail aws bedrock list-guardrails --query 'guardrails[?id==`vdyqrh31xgca`].{id:id,name:name}' --output json >>"$INVENTORY"
printf ',\n  "runtime": ' >>"$INVENTORY"
one runtime aws bedrock-agentcore-control list-agent-runtimes --query 'agentRuntimes[?agentRuntimeId==`nova_toll_v2_development-Y69XBf88Bl`].{id:agentRuntimeId,arn:agentRuntimeArn}' --output json >>"$INVENTORY"
printf ',\n  "endpoint": ' >>"$INVENTORY"
one endpoint aws bedrock-agentcore-control list-agent-runtime-endpoints --agent-runtime-id nova_toll_v2_development-Y69XBf88Bl --query 'runtimeEndpoints[?id==`preview`].{id:id,arn:agentRuntimeEndpointArn}' --output json >>"$INVENTORY"
printf ',\n  "distribution": ' >>"$INVENTORY"
DISTRIBUTION_INFO="$(one cloudfront aws cloudfront list-distributions --query 'DistributionList.Items[?Id==`E33DVF3KT7BTAC` && DomainName==`d1wqry4fbd92w5.cloudfront.net`].{id:Id,domain:DomainName}' --output json)"
jq -e --arg id "$DISTRIBUTION_ID" --arg domain "$DISTRIBUTION_DOMAIN" \
  '.id == $id and .domain == $domain' <<<"$DISTRIBUTION_INFO" >/dev/null ||
  die "unexpected CloudFront distribution identity"
printf '%s' "$DISTRIBUTION_INFO" >>"$INVENTORY"
SITE_OAC_INFO="$(one 'site CloudFront' aws cloudfront list-origin-access-controls --query 'OriginAccessControlList.Items[?Name==`tollchat-v2-site-dev`].{id:Id,name:Name}' --output json)"
PUBLIC_CHAT_OAC_INFO="$(one 'public-chat CloudFront' aws cloudfront list-origin-access-controls --query 'OriginAccessControlList.Items[?Name==`tollchat-v2-public-chat-dev`].{id:Id,name:Name}' --output json)"
RESPONSE_HEADERS_INFO="$(one "response-headers CloudFront" aws cloudfront list-response-headers-policies --type custom --query 'ResponseHeadersPolicyList.Items[?ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name==`tollchat-v2-development-noindex`].{id:ResponseHeadersPolicy.Id,name:ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name}' --output json)"
WAF_INFO="$(one WAF aws wafv2 list-web-acls --scope CLOUDFRONT --query 'WebACLs[?Name==`tollchat-v2-public-chat-dev`].{id:Id,arn:ARN,name:Name}' --output json)"
WAF_ARN="$(jq -r '.arn' <<<"$WAF_INFO")"
aws wafv2 get-web-acl --scope CLOUDFRONT --id "$(jq -r '.id' <<<"$WAF_INFO")" \
  --name tollchat-v2-public-chat-dev --query 'WebACL.{id:Id,arn:ARN,name:Name}' --output json \
  >"$WORK_DIR/waf.json" || die "WAF ACL is unreadable"
aws wafv2 get-logging-configuration --resource-arn "$WAF_ARN" \
  >"$WORK_DIR/waf-logging.json" || die "WAF logging configuration is unreadable"

for bucket in \
  "tollchat-site-$EXPECTED_ACCOUNT-dev" \
  "aws-waf-logs-tollchat-agent-reports-$EXPECTED_ACCOUNT-dev" \
  "nova-toll-agentcore-$EXPECTED_ACCOUNT"; do
  aws s3api head-bucket --bucket "$bucket" >/dev/null || die "missing bucket $bucket"
done
MEASUREMENT_BUCKET="aws-waf-logs-tollchat-agent-reports-$EXPECTED_ACCOUNT-dev"
SITE_BUCKET="tollchat-site-$EXPECTED_ACCOUNT-dev"
aws s3api get-public-access-block --bucket "$MEASUREMENT_BUCKET" \
  >"$WORK_DIR/measurement-public-access-block.json" ||
  die "missing measurement public-access block"
aws s3api get-bucket-policy --bucket "$MEASUREMENT_BUCKET" \
  >"$WORK_DIR/measurement-bucket-policy.json" ||
  die "missing measurement bucket policy"
aws s3api get-public-access-block --bucket "$SITE_BUCKET" \
  >"$WORK_DIR/site-public-access-block.json" || die "missing site public-access block"
aws s3api get-bucket-policy --bucket "$SITE_BUCKET" \
  >"$WORK_DIR/site-bucket-policy.json" || die "missing site bucket policy"

aws athena get-named-query \
  --named-query-id 097b778f-c9ed-4bd9-af53-1e05770e1d53 \
  --query 'NamedQuery.{id:NamedQueryId,name:Name,workgroup:WorkGroup}' --output json \
  >"$WORK_DIR/named-query-top-routes.json"
jq -e '.id == "097b778f-c9ed-4bd9-af53-1e05770e1d53" and .workgroup == "tollchat-agent-reports-dev"' \
  "$WORK_DIR/named-query-top-routes.json" >/dev/null || die "wrong top-routes query"
aws athena get-named-query \
  --named-query-id 6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d \
  --query 'NamedQuery.{id:NamedQueryId,name:Name,workgroup:WorkGroup}' --output json \
  >"$WORK_DIR/named-query-recent-routes.json"
jq -e '.id == "6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d" and .workgroup == "tollchat-agent-reports-dev"' \
  "$WORK_DIR/named-query-recent-routes.json" >/dev/null || die "wrong recent-routes query"
aws athena get-work-group --work-group tollchat-agent-reports-dev \
  --query 'WorkGroup.{name:Name}' --output json >"$WORK_DIR/athena-workgroup.json" ||
  die "missing Athena workgroup"

for role in \
  toll-v2-pricing-loader-dev toll-v2-report-publisher-dev \
  toll-v2-report-publisher-scheduler-dev nova-toll-v2-timed-checks-dev \
  nova-toll-v2-agentcore-runtime-dev nova-toll-v2-chat-proxy-dev \
  tollchat-v2-usage-publisher-dev tollchat-v2-agent-usage-rollup-dev; do
  aws iam get-role --role-name "$role" --query 'Role.{name:RoleName,arn:Arn}' \
    --output json >"$WORK_DIR/role-$role.json" ||
    die "missing application role $role"
done
for role in \
  toll-v2-pricing-loader-dev toll-v2-report-publisher-dev \
  toll-v2-report-publisher-scheduler-dev nova-toll-v2-timed-checks-dev \
  nova-toll-v2-agentcore-runtime-dev nova-toll-v2-chat-proxy-dev \
  tollchat-v2-usage-publisher-dev tollchat-v2-agent-usage-rollup-dev; do
  aws iam list-role-policies --role-name "$role" --query PolicyNames --output json \
    >"$WORK_DIR/role-policies-$role.json" || die "cannot list inline policies for $role"
  aws iam list-attached-role-policies --role-name "$role" \
    --query 'AttachedPolicies[].PolicyArn' --output json \
    >"$WORK_DIR/role-attachments-$role.json" || die "cannot list attachments for $role"
done

for alias in alias/tollchat-v2-agent-measurement-dev alias/tollchat-v2-site-dev; do
  aws kms describe-key --key-id "$alias" --query 'KeyMetadata.{arn:Arn,id:KeyId}' \
    --output json >"$WORK_DIR/kms-${alias#alias/}.json" ||
    die "missing application KMS alias $alias"
done
for runtime_arn in \
  arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl \
  arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl/runtime-endpoint/preview; do
  aws bedrock-agentcore-control get-resource-policy --resource-arn "$runtime_arn" \
    >"$WORK_DIR/resource-policy-${runtime_arn##*/}.json" ||
    die "missing AgentCore resource policy $runtime_arn"
done
for endpoint_name in DEFAULT preview; do
  one "AgentCore log group $endpoint_name" aws logs describe-log-groups \
    --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-$endpoint_name" \
    --query 'logGroups[?logGroupName==`/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT` || logGroupName==`/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview`].{name:logGroupName,arn:arn}' \
    --output json >"$WORK_DIR/agentcore-log-group-$endpoint_name.json"
done
for security_group_name in \
  nova-toll-v2-pricing-loader-dev nova-toll-v2-report-publisher-dev \
  nova-toll-v2-agentcore-runtime-dev nova-toll-v2-chat-proxy-dev; do
  one "security group $security_group_name" aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=$security_group_name" \
    --query 'SecurityGroups[].{id:GroupId,name:GroupName,vpc:VpcId}' --output json \
    >"$WORK_DIR/security-group-$security_group_name.json"
done
terraform -chdir="$ROOT/infra" init -input=false -backend-config=backend.development.hcl

canonicalize_json() {
  local input="$1" output="$2"
  python3 - "$input" "$output" <<'PY'
import json
import sys
import urllib.parse
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text())
if isinstance(value, str):
    value = json.loads(urllib.parse.unquote(value))
Path(sys.argv[2]).write_text(
    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
)
PY
  chmod 600 -- "$output"
}

render_document() {
  local expression="$1" output="$2" raw="$WORK_DIR/rendered-policy.raw"
  printf 'jsonencode(jsondecode(%s))\n' "$expression" |
    terraform -chdir="$ROOT/infra" console -var environment=development |
    tail -n 1 >"$raw"
  canonicalize_json "$raw" "$output"
}

decode_lambda_policy_response() {
  local raw="$1" output="$2"
  local policy_value="$WORK_DIR/lambda-policy-value.raw"
  local policy_document="$WORK_DIR/lambda-policy-document.json"
  jq -e '.Policy' "$raw" >"$policy_value" || return 1
  canonicalize_json "$policy_value" "$policy_document" || return 1
  jq -n --slurpfile document "$policy_document" '{PolicyDocument:$document[0]}' >"$output"
}

ROLE_ARN="arn:aws:iam::$EXPECTED_ACCOUNT:role/$ROLE_NAME"
EXPECTED_TRUST="$WORK_DIR/expected-trust.json"
ACTUAL_TRUST="$WORK_DIR/actual-trust.json"
EXPECTED_POLICY_DIR="$WORK_DIR/expected-policies"
ACTUAL_POLICY_DIR="$WORK_DIR/actual-policies"
mkdir -p -- "$EXPECTED_POLICY_DIR" "$ACTUAL_POLICY_DIR"
declare -a EXPECTED_POLICY_KEYS=(state compute observability storage data runtime edge)
EXPECTED_POLICY_PATH="/nova-toll/v2/development/"
declare -A EXPECTED_POLICY_NAMES=()
declare -A EXPECTED_POLICY_ARNS=()
declare -A EXPECTED_POLICIES=()
declare -A ACTUAL_POLICIES=()
declare -A PREVIOUS_POLICIES=()
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  EXPECTED_POLICY_NAMES["$policy_key"]="$ROLE_NAME-$policy_key"
  EXPECTED_POLICY_ARNS["$policy_key"]="arn:aws:iam::$EXPECTED_ACCOUNT:policy${EXPECTED_POLICY_PATH}${EXPECTED_POLICY_NAMES[$policy_key]}"
  EXPECTED_POLICIES["$policy_key"]="$EXPECTED_POLICY_DIR/$policy_key.json"
  ACTUAL_POLICIES["$policy_key"]="$ACTUAL_POLICY_DIR/$policy_key.json"
done
ROLE_INFO="$WORK_DIR/delivery-role.json"
ROLE_POLICY_NAMES="$WORK_DIR/delivery-role-policies.json"
ROLE_ATTACHMENTS="$WORK_DIR/delivery-role-attachments.json"
ROLE_PRESENT=0
ROLE_CREATED=0
POLICY_NEEDS_ATTACH=0
MUTATION_AMBIGUOUS=0
declare -A STATE_PREEXISTING=()
declare -A STATE_IMPORTED_BY_THIS_RUN=()
declare -A POLICY_PRESENT=()
declare -A ATTACHMENT_CREATED_BY_THIS_RUN=()

render_document 'data.aws_iam_policy_document.development_delivery_assume.json' "$EXPECTED_TRUST" ||
  die "could not render expected delivery trust policy"
TRUST_SHA256="$(sha256sum "$EXPECTED_TRUST" | awk '{print $1}')"
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  render_document "local.development_delivery_policy_documents.${policy_key}" "${EXPECTED_POLICIES[$policy_key]}" ||
    die "could not render expected delivery managed policy: $policy_key"
done
POLICY_SHA256="$(for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  sha256sum "${EXPECTED_POLICIES[$policy_key]}" | awk '{print $1}'
done | sha256sum | awk '{print $1}')"
EXPECTED_POLICY_ARNS_JSON="$(printf '%s\n' "${EXPECTED_POLICY_KEYS[@]}" | jq -R -s --arg account "$EXPECTED_ACCOUNT" --arg path "$EXPECTED_POLICY_PATH" --arg role "$ROLE_NAME" 'split("\n") | map(select(length > 0) | ("arn:aws:iam::" + $account + ":policy" + $path + $role + "-" + .))')"

STATE_BUCKET="nova-toll-tfstate-${EXPECTED_ACCOUNT}"
LOCK_KEY="nova-toll/v2/development/bootstrap-lock"
LOCK_ARN="arn:aws:s3:::${STATE_BUCKET}/${LOCK_KEY}"
LOCK_TOKEN="$(od -An -N16 -tx1 /dev/urandom | tr -d '[:space:]')"
LOCK_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s' "$LOCK_TOKEN" | grep -Eq '^[0-9a-f]{32}$' || die "could not generate a random lock token"
LOCK_VALUE="${LOCK_TOKEN}|${LOCK_STARTED_AT}"
LOCK_BODY="$WORK_DIR/bootstrap-lock.body"
LOCK_PUT="$WORK_DIR/bootstrap-lock-put.json"
LOCK_HEAD="$WORK_DIR/bootstrap-lock-head.json"
LOCK_ETAG=""
LOCK_VERSION_ID=""
LOCK_ACQUIRED=0

acquire_bootstrap_lock() {
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES ||
    die "set BOOTSTRAP_APPROVED=YES before aws s3api put-object --region $REGION --bucket $STATE_BUCKET --key $LOCK_KEY --if-none-match '*' --body '<owner-token>|<utc-timestamp>' (target $LOCK_ARN)"
  printf '%s' "$LOCK_VALUE" >"$LOCK_BODY"
  chmod 600 -- "$LOCK_BODY"
  if ! aws s3api put-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
    --body "$LOCK_BODY" --if-none-match '*' >"$LOCK_PUT" 2>"$WORK_DIR/bootstrap-lock-put.error"; then
    if grep -qiE 'PreconditionFailed|ConditionalRequestConflict|412|409' "$WORK_DIR/bootstrap-lock-put.error"; then
      die "bootstrap lock is already held at $LOCK_ARN; refusing overwrite, retry, or steal"
    fi
    if aws s3api head-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
      >"$WORK_DIR/bootstrap-lock-ambiguous.json" 2>/dev/null; then
      die "bootstrap lock acquisition result is ambiguous and the lock is present"
    fi
    die "bootstrap lock acquisition failed; refusing protected mutation"
  fi
  LOCK_ETAG="$(jq -er '.ETag | strings' "$LOCK_PUT")" || die "bootstrap lock response has no ETag"
  LOCK_VERSION_ID="$(jq -r '.VersionId // empty' "$LOCK_PUT")" || die "bootstrap lock response is malformed"
  test -n "$LOCK_ETAG" || die "bootstrap lock response has an empty ETag"
  lock_is_current || die "bootstrap lock owner changed during acquisition"
  LOCK_ACQUIRED=1
}

lock_is_current() {
  test -n "$LOCK_ETAG" || return 1
  aws s3api head-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
    --query '{ETag:ETag,VersionId:VersionId}' --output json >"$LOCK_HEAD" 2>"$WORK_DIR/bootstrap-lock-head.error" || return 1
  jq -e --arg etag "$LOCK_ETAG" --arg version "$LOCK_VERSION_ID" \
    '.ETag == $etag and (.VersionId // "") == $version' "$LOCK_HEAD" >/dev/null
}

release_bootstrap_lock() {
  local status="${1:-0}"
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return "$status"
  if test "$AWS_PROFILE" != "$EXPECTED_PROFILE" ||
    test "${AWS_REGION:-}" != "$REGION" ||
    test "${AWS_DEFAULT_REGION:-}" != "$REGION" ||
    test "$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" != "$EXPECTED_ACCOUNT"; then
    printf 'bootstrap lock release stopped: development account guard failed; lock left in place (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  if ! lock_is_current; then
    printf 'bootstrap lock release stopped: current ETag/version does not match; lock left in place (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  if test "${BOOTSTRAP_APPROVED:-}" != YES; then
    printf 'bootstrap lock release stopped: set BOOTSTRAP_APPROVED=YES before aws s3api delete-object --region %s --bucket %s --key %s --if-match %s (target %s)\n' \
      "$REGION" "$STATE_BUCKET" "$LOCK_KEY" "$LOCK_ETAG" "$LOCK_ARN" >&2
    return 1
  fi
  local -a delete_args=(aws s3api delete-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" --if-match "$LOCK_ETAG")
  test -n "$LOCK_VERSION_ID" && delete_args+=(--version-id "$LOCK_VERSION_ID")
  "${delete_args[@]}" >"$WORK_DIR/bootstrap-lock-delete.json" 2>"$WORK_DIR/bootstrap-lock-delete.error" || {
    printf 'bootstrap lock release failed; lock left in place (%s)\n' "$LOCK_ARN" >&2
    return 1
  }
  if aws s3api head-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
    >"$WORK_DIR/bootstrap-lock-after-delete.json" 2>"$WORK_DIR/bootstrap-lock-after-delete.error"; then
    printf 'bootstrap lock release could not verify absence; lock may remain (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  if ! grep -qiE 'Not Found|404|NoSuchKey' "$WORK_DIR/bootstrap-lock-after-delete.error"; then
    printf 'bootstrap lock release returned an unexpected verification response (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  LOCK_ACQUIRED=0
  return "$status"
}

bootstrap_cleanup() {
  local status=$? release_status=0
  trap - EXIT
  if test "$status" -ne 0; then
    set +e
    if test "$MUTATION_AMBIGUOUS" -eq 0; then
      if declare -F rollback_created_role >/dev/null; then rollback_created_role; fi
      if test "$MUTATION_AMBIGUOUS" -eq 0 && test "$ROLE_CREATED" -eq 0 && declare -F rollback_created_attachments >/dev/null; then
        rollback_created_attachments || MUTATION_AMBIGUOUS=1
      fi
      if test "$MUTATION_AMBIGUOUS" -eq 0 && declare -F rollback_delivery_state >/dev/null; then
        rollback_delivery_state || MUTATION_AMBIGUOUS=1
      fi
      if test "$MUTATION_AMBIGUOUS" -ne 0; then
        printf 'bootstrap cleanup stopped: ambiguous mutation result preserved for manual reconciliation\n' >&2
      fi
    else
      printf 'bootstrap cleanup stopped: ambiguous mutation result preserved for manual reconciliation\n' >&2
    fi
    set -e
  fi
  release_bootstrap_lock "$status" || release_status=$?
  rm -rf -- "$WORK_DIR"
  test "$release_status" -eq 0 || status=1
  exit "$status"
}
trap bootstrap_cleanup EXIT

read_role() {
  aws iam get-role --role-name "$ROLE_NAME" --output json \
    >"$ROLE_INFO" 2>"$WORK_DIR/delivery-role.error" || return 1
  jq -e '.Role | type == "object" and .RoleName != null and .Arn != null and .Path != null' \
    "$ROLE_INFO" >/dev/null || return 1
  jq -c '.Role.AssumeRolePolicyDocument' "$ROLE_INFO" >"$WORK_DIR/actual-trust.raw"
  canonicalize_json "$WORK_DIR/actual-trust.raw" "$ACTUAL_TRUST"
}

role_identity_matches() {
  jq -e --arg role "$ROLE_NAME" --arg arn "$ROLE_ARN" \
    '.Role.RoleName == $role and .Role.Arn == $arn and .Role.Path == "/" and .Role.MaxSessionDuration == 3600 and (.Role.PermissionsBoundary? // null) == null' \
    "$ROLE_INFO" >/dev/null && cmp -s "$EXPECTED_TRUST" "$ACTUAL_TRUST"
}

read_policy_set() {
  aws iam list-role-policies --role-name "$ROLE_NAME" --output json >"$ROLE_POLICY_NAMES" || return 1
  aws iam list-attached-role-policies --role-name "$ROLE_NAME" --output json >"$ROLE_ATTACHMENTS" || return 1
  jq -e '(.PolicyNames | type == "array") and (.NextToken? // null) == null' "$ROLE_POLICY_NAMES" >/dev/null || return 1
    jq -e '(.AttachedPolicies | type == "array") and (.NextToken? // null) == null' "$ROLE_ATTACHMENTS" >/dev/null
}

policy_set_is_safe_subset() {
  jq -e '.PolicyNames == []' "$ROLE_POLICY_NAMES" >/dev/null &&
    jq -e --argjson expected "$EXPECTED_POLICY_ARNS_JSON" \
      'all(.AttachedPolicies[]?.PolicyArn; . as $arn | ($expected | index($arn)) != null)' \
      "$ROLE_ATTACHMENTS" >/dev/null
}

read_managed_policy_inventory() {
  local policy_key policy_info="$WORK_DIR/managed-policy-info"
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if aws iam get-policy --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
      --output json >"$policy_info-$policy_key.json" 2>"$WORK_DIR/managed-policy-$policy_key.error"; then
      jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
        --arg name "${EXPECTED_POLICY_NAMES[$policy_key]}" --arg path "$EXPECTED_POLICY_PATH" \
        '.Policy | .Arn == $arn and .PolicyName == $name and .Path == $path and .DefaultVersionId != null' \
        "$policy_info-$policy_key.json" >/dev/null ||
        die "existing delivery managed policy identity does not match exactly: $policy_key"
      POLICY_PRESENT["$policy_key"]=1
    elif grep -qi 'NoSuchEntity' "$WORK_DIR/managed-policy-$policy_key.error"; then
      POLICY_PRESENT["$policy_key"]=0
    else
      die "could not inventory delivery managed policy: $policy_key"
    fi
  done
}

policy_set_is_empty() {
  jq -e '.PolicyNames == []' "$ROLE_POLICY_NAMES" >/dev/null &&
    jq -e '.AttachedPolicies == []' "$ROLE_ATTACHMENTS" >/dev/null
}

policy_set_is_exact() {
  jq -e '.PolicyNames == []' "$ROLE_POLICY_NAMES" >/dev/null &&
    jq -e --argjson expected "$EXPECTED_POLICY_ARNS_JSON" '[.AttachedPolicies[]?.PolicyArn] | sort == ($expected | sort)' "$ROLE_ATTACHMENTS" >/dev/null
}

read_expected_policy() {
  local policy_key="$1" policy_info="$WORK_DIR/actual-policy-info-$1.json"
  local policy_version="$WORK_DIR/actual-policy-version-$1.raw" default_version
  aws iam get-policy --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
    --output json >"$policy_info" || return 1
  jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
    --arg name "${EXPECTED_POLICY_NAMES[$policy_key]}" --arg path "$EXPECTED_POLICY_PATH" \
    '.Policy | .Arn == $arn and .PolicyName == $name and .Path == $path and .DefaultVersionId != null' \
    "$policy_info" >/dev/null || return 1
  default_version="$(jq -er '.Policy.DefaultVersionId | strings' "$policy_info")" || return 1
  aws iam get-policy-version --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
    --version-id "$default_version" --query PolicyVersion.Document --output json >"$policy_version" || return 1
  canonicalize_json "$policy_version" "${ACTUAL_POLICIES[$policy_key]}" || return 1
}

read_expected_policies() {
  local policy_key
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    read_expected_policy "$policy_key" || return 1
  done
}

role_documents_match() {
  read_role && role_identity_matches && read_policy_set && policy_set_is_exact &&
    read_expected_policies || return 1
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}" || return 1
  done
}

rollback_created_attachments() {
  test "$ROLE_PRESENT" -eq 1 || test "$ROLE_CREATED" -eq 1 || return 0
  local policy_key attachment_present created=0
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if test "${ATTACHMENT_CREATED_BY_THIS_RUN[$policy_key]:-0}" -eq 1; then
      created=1
      break
    fi
  done
  test "$created" -eq 1 || return 0
  lock_is_current || die "refusing delivery attachment rollback after lock ownership changed"
  read_policy_set || die "cannot safely inspect delivery role for attachment rollback"
  policy_set_is_safe_subset || die "refusing rollback with unexpected inline policy or managed attachment"
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    test "${ATTACHMENT_CREATED_BY_THIS_RUN[$policy_key]:-0}" -eq 1 || continue
    attachment_present="$(jq -r --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" '[.AttachedPolicies[]? | select(.PolicyArn == $arn)] | length' "$ROLE_ATTACHMENTS")"
    if test "$attachment_present" -eq 1; then
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn ${EXPECTED_POLICY_ARNS[$policy_key]} (target $ROLE_ARN)"
      if ! aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"; then
        MUTATION_AMBIGUOUS=1
        printf 'delivery managed-policy detach failed; preserving exact policy for manual reconciliation: %s\n' "$policy_key" >&2
        return 1
      fi
    fi
  done
  read_policy_set && policy_set_is_safe_subset || {
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'delivery attachment rollback could not be verified; preserving role and policies for manual reconciliation' >&2
    return 1
  }
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    test "${ATTACHMENT_CREATED_BY_THIS_RUN[$policy_key]:-0}" -eq 1 || continue
    if jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" '[.AttachedPolicies[]?.PolicyArn] | index($arn) != null' "$ROLE_ATTACHMENTS" >/dev/null; then
      MUTATION_AMBIGUOUS=1
      printf 'delivery attachment rollback could not verify absence; preserving role and policies for manual reconciliation: %s\n' "$policy_key" >&2
      return 1
    fi
  done
}

rollback_created_role() {
  test "$ROLE_CREATED" -eq 1 || return 0
  rollback_created_attachments || return 1
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam delete-role --role-name $ROLE_NAME (target $ROLE_ARN)"
  if ! aws iam delete-role --role-name "$ROLE_NAME"; then
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'delivery role deletion failed; preserving role and policies for manual exact reconciliation' >&2
    return 1
  fi
  if aws iam get-role --role-name "$ROLE_NAME" \
    >"$WORK_DIR/rollback-role.json" 2>"$WORK_DIR/rollback-role.error"; then
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'created delivery role remained after rollback' >&2
    return 1
  fi
  if ! grep -q 'NoSuchEntity' "$WORK_DIR/rollback-role.error"; then
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'could not verify created delivery role rollback' >&2
    return 1
  fi
  ROLE_CREATED=0
}

acquire_bootstrap_lock

state_list_contains() {
  local state_file="$1" address="$2"
  awk -v address="$address" '$0 == address { found=1 } END { exit found ? 0 : 1 }' "$state_file"
}
FOUNDATION_STATE_LIST="$WORK_DIR/foundation-state.list"
APPLICATION_STATE_LIST="$WORK_DIR/application-state.list"
terraform -chdir="$ROOT/v2/infra" init -input=false -backend-config=backend.development.hcl
terraform -chdir="$ROOT/infra" state list >"$FOUNDATION_STATE_LIST"
terraform -chdir="$ROOT/v2/infra" state list >"$APPLICATION_STATE_LIST"

if read_role; then
  ROLE_PRESENT=1
  role_identity_matches || die "pre-existing delivery role identity or trust does not match exactly"
elif grep -q 'NoSuchEntity' "$WORK_DIR/delivery-role.error"; then
  ROLE_PRESENT=0
else
  die "could not read delivery role"
fi
read_managed_policy_inventory
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  if test "${POLICY_PRESENT[$policy_key]}" -eq 1; then
    read_expected_policy "$policy_key" || die "existing delivery managed policy document is unreadable: $policy_key"
    cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}" ||
      die "existing delivery managed policy document does not match exactly: $policy_key"
  fi
done

URL_PRESENT=1
if ! aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
  >"$WORK_DIR/function-url.json" 2>"$WORK_DIR/function-url.error"; then
  grep -q 'ResourceNotFoundException' "$WORK_DIR/function-url.error" || die "could not read Lambda URL config"
  URL_PRESENT=0
fi
POLICY_PRESENT=1
if ! aws lambda get-policy --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
  --output json >"$WORK_DIR/lambda-policy-raw.json" 2>"$WORK_DIR/lambda-permissions.error"; then
  grep -q 'ResourceNotFoundException' "$WORK_DIR/lambda-permissions.error" || die "could not read Lambda URL permissions"
  POLICY_PRESENT=0
else
  decode_lambda_policy_response "$WORK_DIR/lambda-policy-raw.json" "$WORK_DIR/lambda-permissions.json" ||
    die "Lambda URL permissions are not valid JSON"
fi
URL_PREEXISTING="$URL_PRESENT"
POLICY_PREEXISTING="$POLICY_PRESENT"

if test "$ROLE_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam create-role --role-name $ROLE_NAME --path / --max-session-duration 3600 --assume-role-policy-document file://$EXPECTED_TRUST (target $ROLE_ARN)"
  aws iam create-role --role-name "$ROLE_NAME" --path / --max-session-duration 3600 \
    --assume-role-policy-document "file://$EXPECTED_TRUST" \
    >"$WORK_DIR/delivery-role-created.json" 2>"$WORK_DIR/delivery-role-create.error" || {
    MUTATION_AMBIGUOUS=1
    die "delivery role create failed; preserving any matching post-state for manual exact reconciliation"
  }
  if test "$ROLE_PRESENT" -eq 0; then
    ROLE_CREATED=1
    read_role && role_identity_matches || { rollback_created_role; die "created delivery role failed exact identity/trust validation"; }
    read_policy_set && policy_set_is_empty || { rollback_created_role; die "created delivery role has unexpected effective policies"; }
    POLICY_NEEDS_ATTACH=1
  fi
fi

if test "$ROLE_PRESENT" -eq 1 && test "$ROLE_CREATED" -eq 0; then
  read_policy_set || die "delivery role policy inventory is unreadable"
  policy_set_is_safe_subset || die "delivery role has unexpected inline policies or managed attachments"
  policy_set_is_exact || POLICY_NEEDS_ATTACH=1
fi

if test "$POLICY_NEEDS_ATTACH" -eq 1; then
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if test "${POLICY_PRESENT[$policy_key]}" -eq 0; then
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam create-policy --policy-name ${EXPECTED_POLICY_NAMES[$policy_key]} --path $EXPECTED_POLICY_PATH --policy-document file://${EXPECTED_POLICIES[$policy_key]} (target ${EXPECTED_POLICY_ARNS[$policy_key]})"
      aws iam create-policy --policy-name "${EXPECTED_POLICY_NAMES[$policy_key]}" --path "$EXPECTED_POLICY_PATH" \
        --policy-document "file://${EXPECTED_POLICIES[$policy_key]}" \
        >"$WORK_DIR/delivery-policy-${policy_key}-created.json" 2>"$WORK_DIR/delivery-policy-${policy_key}-create.error" || {
        MUTATION_AMBIGUOUS=1
        die "delivery managed policy create failed; preserving any matching post-state for manual exact reconciliation: $policy_key"
      }
      POLICY_PRESENT["$policy_key"]=1
      read_expected_policy "$policy_key" || die "created delivery managed policy is unreadable: $policy_key"
      cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}" ||
        die "created delivery managed policy document does not match exactly: $policy_key"
    fi
  done
  read_policy_set || die "delivery role policy inventory is unreadable before managed attachments"
  policy_set_is_safe_subset || die "delivery role changed before managed attachments"
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if ! jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" '[.AttachedPolicies[]?.PolicyArn] | index($arn) != null' "$ROLE_ATTACHMENTS" >/dev/null; then
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn ${EXPECTED_POLICY_ARNS[$policy_key]} (target $ROLE_ARN)"
      aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" || {
        MUTATION_AMBIGUOUS=1
        die "delivery managed policy attachment failed; preserving any matching post-state for manual exact reconciliation: $policy_key"
      }
      ATTACHMENT_CREATED_BY_THIS_RUN["$policy_key"]=1
    fi
  done
  if ! role_documents_match; then
    if test "$ROLE_CREATED" -eq 0; then rollback_created_attachments; fi
    if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
    die "delivery role failed post-attachment exact effective-policy validation"
  fi
fi

role_documents_match || {
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  die "delivery role trust, identity policy, or effective policy set is not exact"
}

state_id_matches() {
  local state_file="$1" expected="$2"
  python3 - "$state_file" "$expected" <<'PY'
import re
import sys

state_file, expected = sys.argv[1:]
pattern = re.compile(r"^\s*id\s*=\s*\"" + re.escape(expected) + r"\"\s*$")
if any(pattern.fullmatch(line.rstrip("\n")) for line in open(state_file, encoding="utf-8")):
    raise SystemExit(0)
raise SystemExit(1)
PY
}
rollback_delivery_state() {
  local address target failed=0 state_list="$WORK_DIR/foundation-state-rollback.list"
  if test "${MUTATION_AMBIGUOUS:-0}" -ne 0; then
    printf 'state rollback stopped: ambiguous IAM mutation result preserved for manual reconciliation\n' >&2
    return 1
  fi
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  terraform -chdir="$ROOT/infra" state list >"$state_list" || return 1
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    for kind in attachment policy; do
      if test "$kind" = policy; then
        address="aws_iam_policy.development_delivery[\"$policy_key\"]"
        target="${EXPECTED_POLICY_ARNS[$policy_key]}"
      else
        address="aws_iam_role_policy_attachment.development_delivery[\"$policy_key\"]"
        target="$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}"
      fi
      test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
      if state_list_contains "$state_list" "$address"; then
        if ! verify_foundation_state "$address" "$target" "$WORK_DIR/rollback-${address//[^A-Za-z0-9]/_}.state"; then
          printf 'refusing rollback of %s: current state ID is not the exact target %s\n' "$address" "$target" >&2
          failed=1
          continue
        fi
        assert_dev_account
        test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra state rm $address (target $target)"
        if ! terraform -chdir="$ROOT/infra" state rm "$address"; then
          MUTATION_AMBIGUOUS=1
          printf 'delivery managed-policy state removal failed; preserving role and policies for manual exact reconciliation: %s\n' "$policy_key" >&2
          return 1
        fi
      fi
      STATE_IMPORTED_BY_THIS_RUN["$address"]=0
    done
  done
  address='aws_iam_role.development_delivery[0]'
  if test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1; then
    target="$ROLE_ARN"
    if state_list_contains "$state_list" "$address"; then
      if ! verify_foundation_state "$address" "$target" "$WORK_DIR/rollback-${address//[^A-Za-z0-9]/_}.state"; then
        printf 'refusing rollback of %s: current state ID is not the exact target %s\n' "$address" "$target" >&2
        failed=1
      else
        assert_dev_account
        test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra state rm $address (target $target)"
        if ! terraform -chdir="$ROOT/infra" state rm "$address"; then
          MUTATION_AMBIGUOUS=1
          printf '%s\n' 'delivery role state removal failed; preserving role and policies for manual exact reconciliation' >&2
          return 1
        fi
      fi
    fi
    STATE_IMPORTED_BY_THIS_RUN["$address"]=0
  fi
  return "$failed"
}
verify_foundation_state() {
  local address="$1" identifier="$2" state_file="$3"
  terraform -chdir="$ROOT/infra" state show -no-color "$address" >"$state_file" || return 1
  state_id_matches "$state_file" "$identifier" || return 1
  if test "$address" = 'aws_iam_role.development_delivery[0]'; then
    grep -Fxq "    arn                = \"$ROLE_ARN\"" "$state_file" ||
      grep -Fxq "    arn = \"$ROLE_ARN\"" "$state_file" || return 1
  fi
}

if state_list_contains "$FOUNDATION_STATE_LIST" 'aws_iam_role.development_delivery[0]'; then
  STATE_PREEXISTING['aws_iam_role.development_delivery[0]']=1
else
  role_documents_match || die "delivery role changed before state import"
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra import -input=false -var environment=development aws_iam_role.development_delivery[0] $ROLE_ARN (target $ROLE_ARN)"
  if ! terraform -chdir="$ROOT/infra" import -input=false \
    -var environment=development \
    'aws_iam_role.development_delivery[0]' "$ROLE_ARN" \
    >"$WORK_DIR/delivery-role-import.log" 2>&1; then
    if grep -qiE 'already managed|already exists|state.*managed' "$WORK_DIR/delivery-role-import.log"; then
      die "delivery role import is already managed or concurrent; refusing state removal"
    fi
    die "delivery role import failed; state ownership is unproven and was retained"
  fi
  STATE_IMPORTED_BY_THIS_RUN['aws_iam_role.development_delivery[0]']=1
  verify_foundation_state 'aws_iam_role.development_delivery[0]' "$ROLE_NAME" \
    "$WORK_DIR/delivery-role-import.state" ||
    die "delivery role import state ID or ARN is not the exact target"
fi
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  for kind in policy attachment; do
    if test "$kind" = policy; then
      address="aws_iam_policy.development_delivery[\"$policy_key\"]"
      target="${EXPECTED_POLICY_ARNS[$policy_key]}"
    else
      address="aws_iam_role_policy_attachment.development_delivery[\"$policy_key\"]"
      target="$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}"
    fi
    if state_list_contains "$FOUNDATION_STATE_LIST" "$address"; then
      STATE_PREEXISTING["$address"]=1
    else
      role_documents_match || die "delivery role changed before managed-policy state import: $policy_key"
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra import -input=false -var environment=development $address $target (target $target)"
      if ! terraform -chdir="$ROOT/infra" import -input=false \
        -var environment=development \
        "$address" "$target" \
        >"$WORK_DIR/delivery-${kind}-${policy_key}-import.log" 2>&1; then
        if grep -qiE 'already managed|already exists|state.*managed' "$WORK_DIR/delivery-${kind}-${policy_key}-import.log"; then
          die "delivery managed-policy import is already managed or concurrent; refusing state removal: $policy_key/$kind"
        fi
        die "delivery managed-policy import failed; state ownership is unproven and was retained: $policy_key/$kind"
      fi
      STATE_IMPORTED_BY_THIS_RUN["$address"]=1
      verify_foundation_state "$address" "$target" \
        "$WORK_DIR/delivery-${kind}-${policy_key}-import.state" ||
        die "delivery managed-policy import state ID is not the exact target: $policy_key/$kind"
    fi
  done
done
if ! role_documents_match; then
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  if ! rollback_delivery_state; then
    MUTATION_AMBIGUOUS=1
    die "delivery role changed after foundation state imports; state rollback was not proven"
  fi
  die "delivery role changed after foundation state imports; imported state was rolled back"
fi

verify_delivery_state() {
  terraform -chdir="$ROOT/infra" state show -no-color \
    'aws_iam_role.development_delivery[0]' >"$WORK_DIR/delivery-role.state" ||
    return 1
  grep -Fxq "    id                 = \"$ROLE_NAME\"" "$WORK_DIR/delivery-role.state" ||
    grep -Fxq "    id = \"$ROLE_NAME\"" "$WORK_DIR/delivery-role.state" ||
    return 1
  grep -Fxq "    arn                = \"$ROLE_ARN\"" "$WORK_DIR/delivery-role.state" ||
    grep -Fxq "    arn = \"$ROLE_ARN\"" "$WORK_DIR/delivery-role.state" ||
    return 1
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    address="aws_iam_policy.development_delivery[\"$policy_key\"]"
    terraform -chdir="$ROOT/infra" state show -no-color "$address" >"$WORK_DIR/delivery-policy-${policy_key}.state" ||
      return 1
    grep -Fxq "    id                 = \"${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-policy-${policy_key}.state" ||
      grep -Fxq "    id = \"${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-policy-${policy_key}.state" ||
      return 1
    address="aws_iam_role_policy_attachment.development_delivery[\"$policy_key\"]"
    terraform -chdir="$ROOT/infra" state show -no-color "$address" >"$WORK_DIR/delivery-attachment-${policy_key}.state" ||
      return 1
    grep -Fxq "    id                 = \"$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-attachment-${policy_key}.state" ||
      grep -Fxq "    id = \"$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-attachment-${policy_key}.state" ||
      return 1
  done
}
if ! verify_delivery_state; then
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  if ! rollback_delivery_state; then
    MUTATION_AMBIGUOUS=1
    die "delivery Terraform state verification failed; state rollback was not proven"
  fi
  die "delivery Terraform state verification failed for the imported role/policy addresses"
fi

FOUNDATION_OUTPUT="$(terraform -chdir="$ROOT/infra" output -json foundation)" || {
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  if ! rollback_delivery_state; then
    MUTATION_AMBIGUOUS=1
    die "development foundation output verification failed; state rollback was not proven"
  fi
  die "development foundation output verification failed; imported state was rolled back"
}
BOOTSTRAP_FOUNDATION_VARS="$WORK_DIR/foundation.tfvars.json"
jq -n --argjson foundation "$FOUNDATION_OUTPUT" '{foundation: $foundation}' >"$BOOTSTRAP_FOUNDATION_VARS"
QUALIFIED_FUNCTION_ARN="arn:aws:lambda:${REGION}:${EXPECTED_ACCOUNT}:function:${FUNCTION_NAME}:${QUALIFIER}"
CLOUDFRONT_SOURCE_ARN="arn:aws:cloudfront::${EXPECTED_ACCOUNT}:distribution/${DISTRIBUTION_ID}"
PREVIOUS_FUNCTION_URL="$WORK_DIR/previous-function-url.json"
PREVIOUS_LAMBDA_POLICY="$WORK_DIR/previous-lambda-policy.json"
URL_CREATED=0
URL_PERMISSION_URL_CREATED=0
URL_PERMISSION_INVOKE_CREATED=0
if test "$URL_PREEXISTING" -eq 1; then
  cp -- "$WORK_DIR/function-url.json" "$PREVIOUS_FUNCTION_URL"
fi
if test "$POLICY_PREEXISTING" -eq 1; then
  cp -- "$WORK_DIR/lambda-policy-raw.json" "$PREVIOUS_LAMBDA_POLICY"
fi
for snapshot in "$PREVIOUS_FUNCTION_URL" "$PREVIOUS_LAMBDA_POLICY"; do
  test -e "$snapshot" && chmod 600 -- "$snapshot"
done
EXPECTED_URL_PERMISSION="$WORK_DIR/expected-url-permission.json"
EXPECTED_INVOKE_PERMISSION="$WORK_DIR/expected-invoke-permission.json"
jq -n --arg function_arn "$QUALIFIED_FUNCTION_ARN" --arg source_arn "$CLOUDFRONT_SOURCE_ARN" \
  '{Sid:"AllowCloudFrontFunctionUrlV2",Effect:"Allow",Action:"lambda:InvokeFunctionUrl",Resource:$function_arn,Principal:{Service:"cloudfront.amazonaws.com"},Condition:{StringEquals:{"lambda:FunctionUrlAuthType":"AWS_IAM"},ArnLike:{"AWS:SourceArn":$source_arn}}}' \
  >"$EXPECTED_URL_PERMISSION"
jq -n --arg function_arn "$QUALIFIED_FUNCTION_ARN" --arg source_arn "$CLOUDFRONT_SOURCE_ARN" \
  '{Sid:"AllowCloudFrontFunctionInvokeV2",Effect:"Allow",Action:"lambda:InvokeFunction",Resource:$function_arn,Principal:{Service:"cloudfront.amazonaws.com"},Condition:{Bool:{"lambda:InvokedViaFunctionUrl":"true"},ArnLike:{"AWS:SourceArn":$source_arn}}}' \
  >"$EXPECTED_INVOKE_PERMISSION"
canonicalize_json "$EXPECTED_URL_PERMISSION" "$EXPECTED_URL_PERMISSION.canonical"
canonicalize_json "$EXPECTED_INVOKE_PERMISSION" "$EXPECTED_INVOKE_PERMISSION.canonical"
mv -- "$EXPECTED_URL_PERMISSION.canonical" "$EXPECTED_URL_PERMISSION"
mv -- "$EXPECTED_INVOKE_PERMISSION.canonical" "$EXPECTED_INVOKE_PERMISSION"
PERMISSION_POLICY_SNAPSHOT="$WORK_DIR/lambda-policy-before-all.json"
if test "$POLICY_PREEXISTING" -eq 1; then
  canonicalize_json "$WORK_DIR/lambda-permissions.json" "$PERMISSION_POLICY_SNAPSHOT"
fi

read_lambda_policy() {
  local output="$1" revision_output="$2" raw="$WORK_DIR/lambda-policy-read.raw"
  if aws lambda get-policy --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
    --output json >"$raw" 2>"$WORK_DIR/lambda-policy-read.error"; then
    decode_lambda_policy_response "$raw" "$output" || return 1
    jq -e '(.RevisionId? // "") | type == "string"' "$raw" >/dev/null || return 1
    jq -r '.RevisionId // empty' "$raw" >"$revision_output"
  else
    grep -q 'ResourceNotFoundException' "$WORK_DIR/lambda-policy-read.error" || return 1
    printf '%s\n' '{"PolicyDocument":{"Statement":[]}}' >"$output"
    : >"$revision_output"
  fi
}

extract_lambda_statement() {
  local policy="$1" sid="$2" output="$3" raw="$WORK_DIR/lambda-statement.raw" count
  count="$(jq -r --arg sid "$sid" '[.PolicyDocument.Statement[]? | select(.Sid == $sid)] | length' "$policy")" || return 1
  test "$count" -le 1 || return 1
  if test "$count" -eq 1; then
    jq -c --arg sid "$sid" '.PolicyDocument.Statement[] | select(.Sid == $sid)' "$policy" >"$raw" || return 1
    canonicalize_json "$raw" "$output"
  else
    printf '%s\n' null >"$output"
  fi
}

validate_existing_lambda_policy() {
  jq -e --slurpfile url "$EXPECTED_URL_PERMISSION" --slurpfile invoke "$EXPECTED_INVOKE_PERMISSION" '
    .PolicyDocument.Statement as $statements |
    ($statements | type == "array" and length <= 2) and
    ([$statements[] | select(.Sid == "AllowCloudFrontFunctionUrlV2")] | length <= 1) and
    ([$statements[] | select(.Sid == "AllowCloudFrontFunctionInvokeV2")] | length <= 1) and
    all($statements[]; . == $url[0] or . == $invoke[0])
  ' "$WORK_DIR/lambda-permissions.json" >/dev/null
}

snapshot_lambda_permission() {
  local sid="$1" stem="$2" policy="$WORK_DIR/lambda-policy-before-$stem.json"
  local revision="$WORK_DIR/lambda-revision-before-$stem.txt"
  local statement="$WORK_DIR/lambda-statement-before-$stem.json" present=0
  read_lambda_policy "$policy" "$revision" || die "could not snapshot Lambda permission policy before $sid"
  extract_lambda_statement "$policy" "$sid" "$statement" || die "Lambda permission SID snapshot is ambiguous: $sid"
  jq -e 'type == "object"' "$statement" >/dev/null && present=1
  printf -v "${stem}_PRE_PRESENT" '%s' "$present"
  printf -v "${stem}_PRE_REVISION" '%s' "$(<"$revision")"
  printf -v "${stem}_PRE_STATEMENT" '%s' "$statement"
}

reconcile_lambda_permission() {
  local sid="$1" stem="$2" expected="$3"
  local policy="$WORK_DIR/lambda-policy-after-$stem.json"
  local revision="$WORK_DIR/lambda-revision-after-$stem.txt"
  local statement="$WORK_DIR/lambda-statement-after-$stem.json"
  local pre_present_var="${stem}_PRE_PRESENT" pre_revision_var="${stem}_PRE_REVISION"
  local pre_present="${!pre_present_var}" pre_revision="${!pre_revision_var}" post_revision
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  read_lambda_policy "$policy" "$revision" || return 1
  extract_lambda_statement "$policy" "$sid" "$statement" || return 1
  cmp -s "$expected" "$statement" || return 1
  test "$pre_present" -eq 0 || return 2
  post_revision="$(<"$revision")"
  if test -n "$pre_revision"; then
    test -n "$post_revision" || return 3
    test "$post_revision" != "$pre_revision" || return 3
  fi
  printf -v "${stem}_CREATED" '%s' 1
  return 0
}

validate_function_url() {
  local document="${1:-$WORK_DIR/function-url.json}"
  jq -e --arg function_arn "$QUALIFIED_FUNCTION_ARN" \
    '.AuthType == "AWS_IAM" and .InvokeMode == "RESPONSE_STREAM" and .FunctionArn == $function_arn' \
    "$document" >/dev/null
}
validate_lambda_policy() {
  jq -e --arg function_arn "$QUALIFIED_FUNCTION_ARN" --arg source_arn "$CLOUDFRONT_SOURCE_ARN" '
    .PolicyDocument as $policy |
    ($policy.Statement | (type == "array" and length == 2)) and
    any($policy.Statement[];
      .Sid == "AllowCloudFrontFunctionUrlV2" and
      .Effect == "Allow" and
      .Action == "lambda:InvokeFunctionUrl" and
      .Resource == $function_arn and
      .Principal == {Service: "cloudfront.amazonaws.com"} and
      .Condition.StringEquals."lambda:FunctionUrlAuthType" == "AWS_IAM" and
      ((.Condition.ArnLike."AWS:SourceArn" // .Condition.StringEquals."AWS:SourceArn") == $source_arn)) and
    any($policy.Statement[];
      .Sid == "AllowCloudFrontFunctionInvokeV2" and
      .Effect == "Allow" and
      .Action == "lambda:InvokeFunction" and
      .Resource == $function_arn and
      .Principal == {Service: "cloudfront.amazonaws.com"} and
      .Condition.Bool."lambda:InvokedViaFunctionUrl" == "true" and
      ((.Condition.ArnLike."AWS:SourceArn" // .Condition.StringEquals."AWS:SourceArn") == $source_arn))
  ' "$WORK_DIR/lambda-permissions.json" >/dev/null
}
verify_owned_lambda_permission() {
  local sid="$1" expected="$2"
  local current_policy="$WORK_DIR/lambda-permission-owned-check.json"
  local current_revision="$WORK_DIR/lambda-permission-owned-revision.txt"
  local current_statement="$WORK_DIR/lambda-permission-owned-statement.json"
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  read_lambda_policy "$current_policy" "$current_revision" || return 1
  extract_lambda_statement "$current_policy" "$sid" "$current_statement" || return 1
  cmp -s "$expected" "$current_statement"
}
rollback_created_url() {
  local removed=0 current_policy="$WORK_DIR/lambda-policy-rollback.json" current_revision="$WORK_DIR/lambda-revision-rollback.txt"
  test "$URL_PERMISSION_INVOKE_CREATED" -eq 1 && {
    verify_owned_lambda_permission AllowCloudFrontFunctionInvokeV2 "$EXPECTED_INVOKE_PERMISSION" ||
      die "refusing Lambda invoke permission rollback after ownership changed"
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda remove-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionInvokeV2 (target $QUALIFIED_FUNCTION_ARN)"
    aws lambda remove-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      --statement-id AllowCloudFrontFunctionInvokeV2
    URL_PERMISSION_INVOKE_CREATED=0
    removed=1
  }
  test "$URL_PERMISSION_URL_CREATED" -eq 1 && {
    verify_owned_lambda_permission AllowCloudFrontFunctionUrlV2 "$EXPECTED_URL_PERMISSION" ||
      die "refusing Lambda URL permission rollback after ownership changed"
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda remove-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionUrlV2 (target $QUALIFIED_FUNCTION_ARN)"
    aws lambda remove-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      --statement-id AllowCloudFrontFunctionUrlV2
    URL_PERMISSION_URL_CREATED=0
    removed=1
  }
  if test "$removed" -eq 1; then
    if test "$POLICY_PREEXISTING" -eq 1; then
      read_lambda_policy "$current_policy" "$current_revision" || die "cannot verify Lambda permission rollback"
      canonicalize_json "$current_policy" "$current_policy.canonical"
      cmp -s "$PERMISSION_POLICY_SNAPSHOT" "$current_policy.canonical" ||
        die "Lambda rollback changed a pre-existing or concurrent permission statement"
    elif aws lambda get-policy --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      --output json >"$WORK_DIR/rollback-lambda-policy-raw.json" 2>"$WORK_DIR/rollback-lambda-policy.error"; then
      die "rollback found an unexpected Lambda permission policy"
    else
      grep -q 'ResourceNotFoundException' "$WORK_DIR/rollback-lambda-policy.error" ||
        die "cannot verify absent Lambda permission policy after rollback"
    fi
  fi
  test "$URL_CREATED" -eq 1 && {
    lock_is_current || die "refusing Lambda URL rollback after lock ownership changed"
    aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      >"$WORK_DIR/rollback-function-url-current.json" 2>"$WORK_DIR/rollback-function-url-current.error" ||
      die "cannot verify Lambda URL before rollback"
    validate_function_url "$WORK_DIR/rollback-function-url-current.json" ||
      die "refusing Lambda URL rollback after its auth, invoke mode, or function identity changed"
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda delete-function-url-config --function-name $FUNCTION_NAME --qualifier $QUALIFIER (target $QUALIFIED_FUNCTION_ARN)"
    aws lambda delete-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER"
    URL_CREATED=0
    if aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      >"$WORK_DIR/rollback-function-url.json" 2>"$WORK_DIR/rollback-function-url.error"; then
      die "new Lambda URL remained after rollback"
    fi
    grep -q 'ResourceNotFoundException' "$WORK_DIR/rollback-function-url.error" ||
      die "cannot verify Lambda URL rollback"
  }
}
BOOTSTRAP_COMPLETE=0
cleanup_on_failure() {
  local status=$?
  trap - EXIT
  if test "$status" -ne 0 && test "$BOOTSTRAP_COMPLETE" -eq 0; then
    set +e
    if test "$MUTATION_AMBIGUOUS" -eq 0; then
      if declare -F rollback_url_state >/dev/null; then rollback_url_state; fi
      rollback_created_url
      if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
      if test "$MUTATION_AMBIGUOUS" -eq 0; then
        rollback_delivery_state || MUTATION_AMBIGUOUS=1
      fi
    else
      printf 'bootstrap cleanup stopped: ambiguous mutation result preserved for manual reconciliation\n' >&2
    fi
    set -e
  fi
  if ! release_bootstrap_lock "$status"; then status=1; fi
  rm -rf -- "$WORK_DIR"
  exit "$status"
}
trap cleanup_on_failure EXIT
if test "$POLICY_PRESENT" -eq 1; then
  validate_existing_lambda_policy || die "Lambda URL permissions contain an unexpected or duplicate statement"
fi
if test "$URL_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES ||
    die "set BOOTSTRAP_APPROVED=YES before aws lambda create-function-url-config --function-name $FUNCTION_NAME --qualifier $QUALIFIER --auth-type AWS_IAM --invoke-mode RESPONSE_STREAM (target $QUALIFIED_FUNCTION_ARN)"
  if ! aws lambda create-function-url-config --function-name "$FUNCTION_NAME" \
    --qualifier "$QUALIFIER" --auth-type AWS_IAM --invoke-mode RESPONSE_STREAM \
    >"$WORK_DIR/function-url-created.json" 2>"$WORK_DIR/function-url-create.error"; then
    MUTATION_AMBIGUOUS=1
    die "Lambda URL create failed; preserving any matching post-state for manual exact reconciliation"
  fi
  URL_CREATED=1
  URL_PRESENT=1
fi
aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
  >"$WORK_DIR/function-url.json" || { rollback_created_url; die "Lambda URL config is unreadable after bootstrap"; }
validate_function_url || { rollback_created_url; die "Lambda URL auth, invoke mode, or function identity is not the reviewed value"; }
snapshot_lambda_permission AllowCloudFrontFunctionUrlV2 URL_PERMISSION_URL
if test "$URL_PERMISSION_URL_PRE_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda add-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionUrlV2 --action lambda:InvokeFunctionUrl --principal cloudfront.amazonaws.com --source-arn $CLOUDFRONT_SOURCE_ARN (target $QUALIFIED_FUNCTION_ARN)"
  URL_PERMISSION_ADD=(aws lambda add-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
    --statement-id AllowCloudFrontFunctionUrlV2 --action lambda:InvokeFunctionUrl \
    --principal cloudfront.amazonaws.com \
    --source-arn "$CLOUDFRONT_SOURCE_ARN" \
    --function-url-auth-type AWS_IAM)
  test -n "$URL_PERMISSION_URL_PRE_REVISION" && URL_PERMISSION_ADD+=(--revision-id "$URL_PERMISSION_URL_PRE_REVISION")
  if "${URL_PERMISSION_ADD[@]}" >"$WORK_DIR/url-permission-add.json" 2>"$WORK_DIR/url-permission-add.error"; then
    reconcile_lambda_permission AllowCloudFrontFunctionUrlV2 URL_PERMISSION_URL "$EXPECTED_URL_PERMISSION" || {
      rollback_created_url
      die "Lambda URL permission response was not the exact newly-owned statement"
    }
  else
    MUTATION_AMBIGUOUS=1
    die "ambiguous Lambda URL permission result; preserving any matching post-state for manual exact reconciliation"
  fi
fi
snapshot_lambda_permission AllowCloudFrontFunctionInvokeV2 URL_PERMISSION_INVOKE
if test "$URL_PERMISSION_INVOKE_PRE_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda add-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionInvokeV2 --action lambda:InvokeFunction --principal cloudfront.amazonaws.com --source-arn $CLOUDFRONT_SOURCE_ARN (target $QUALIFIED_FUNCTION_ARN)"
  INVOKE_PERMISSION_ADD=(aws lambda add-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
    --statement-id AllowCloudFrontFunctionInvokeV2 --action lambda:InvokeFunction \
    --principal cloudfront.amazonaws.com \
    --source-arn "$CLOUDFRONT_SOURCE_ARN" \
    --invoked-via-function-url)
  test -n "$URL_PERMISSION_INVOKE_PRE_REVISION" && INVOKE_PERMISSION_ADD+=(--revision-id "$URL_PERMISSION_INVOKE_PRE_REVISION")
  if "${INVOKE_PERMISSION_ADD[@]}" >"$WORK_DIR/invoke-permission-add.json" 2>"$WORK_DIR/invoke-permission-add.error"; then
    reconcile_lambda_permission AllowCloudFrontFunctionInvokeV2 URL_PERMISSION_INVOKE "$EXPECTED_INVOKE_PERMISSION" || {
      rollback_created_url
      die "Lambda invoke permission response was not the exact newly-owned statement"
    }
  else
    MUTATION_AMBIGUOUS=1
    die "ambiguous Lambda invoke permission result; preserving any matching post-state for manual exact reconciliation"
  fi
fi
read_lambda_policy "$WORK_DIR/lambda-permissions.json" "$WORK_DIR/lambda-policy-revision.txt" ||
  { rollback_created_url; die "Lambda URL permissions are unreadable after bootstrap"; }
validate_lambda_policy || { rollback_created_url; die "Lambda URL permissions are not the two reviewed CloudFront statements"; }
POLICY_PRESENT=1
rollback_url_state() {
  local address target failed=0 state_file state_list="$WORK_DIR/application-state-rollback.list"
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  terraform -chdir="$ROOT/v2/infra" state list >"$state_list" || return 1
  for address in \
    'aws_lambda_permission.public_chat_invoke' \
    'aws_lambda_permission.public_chat_url' \
    'aws_lambda_function_url.public_chat'; do
    case "$address" in
      aws_lambda_permission.public_chat_invoke)
        test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
        target="$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionInvokeV2"
        ;;
      aws_lambda_permission.public_chat_url)
        test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
        target="$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionUrlV2"
        ;;
      aws_lambda_function_url.public_chat)
        test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
        target="$FUNCTION_NAME,$QUALIFIER"
        ;;
    esac
    if state_list_contains "$state_list" "$address"; then
      state_file="$WORK_DIR/rollback-${address//[^A-Za-z0-9]/_}.state"
      if ! terraform -chdir="$ROOT/v2/infra" state show -no-color "$address" >"$state_file" ||
        ! state_id_matches "$state_file" "$target"; then
        printf 'refusing rollback of %s: current state ID is not the exact target %s\n' "$address" "$target" >&2
        failed=1
        continue
      fi
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/v2/infra state rm $address (target $target)"
      terraform -chdir="$ROOT/v2/infra" state rm "$address"
    fi
    STATE_IMPORTED_BY_THIS_RUN["$address"]=0
  done
  return "$failed"
}
import_url_state() {
  local address="$1" identifier="$2" label="$3"
  if ! state_list_contains "$APPLICATION_STATE_LIST" "$address"; then
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/v2/infra import -input=false $address $identifier (target $identifier)"
    if ! terraform -chdir="$ROOT/v2/infra" import -input=false \
      -var-file=development.tfvars -var-file="$BOOTSTRAP_FOUNDATION_VARS" \
      "$address" "$identifier" >"$WORK_DIR/${label// /-}-import.log" 2>&1; then
      if grep -qiE 'already managed|already exists|state.*managed' "$WORK_DIR/${label// /-}-import.log"; then
        die "$label import is already managed or concurrent; refusing state removal"
      fi
      die "$label import failed; state ownership is unproven and was retained"
    fi
    STATE_IMPORTED_BY_THIS_RUN["$address"]=1
  else
    STATE_PREEXISTING["$address"]=1
  fi
  if ! terraform -chdir="$ROOT/v2/infra" state show -no-color "$address" >"$WORK_DIR/${label// /-}.state"; then
    die "$label state verification failed"
  fi
  state_id_matches "$WORK_DIR/${label// /-}.state" "$identifier" ||
    die "$label Terraform state ID does not match exact target $identifier"
}
import_url_state 'aws_lambda_function_url.public_chat' "$FUNCTION_NAME,$QUALIFIER" \
  'Lambda URL'
import_url_state 'aws_lambda_permission.public_chat_url' "$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionUrlV2" \
  'Lambda URL permission'
import_url_state 'aws_lambda_permission.public_chat_invoke' "$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionInvokeV2" \
  'Lambda invoke permission'

ADDRESS_INVENTORY="$EVIDENCE_DIR/terraform-addresses.tsv"
printf 'terraform_address\tlive_identifier\n' >"$ADDRESS_INVENTORY"
printf 'aws_api_gateway_rest_api.tollchat\tocw8sg0wlb\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrock_guardrail.tollchat\tvdyqrh31xgca\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_agent_runtime.tollchat\tnova_toll_v2_development-Y69XBf88Bl\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_agent_runtime_endpoint.tollchat\tpreview\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_resource_policy.tollchat["runtime"]\t%s\n' "$(jq -r '.runtime.arn' "$INVENTORY")" >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_resource_policy.tollchat["endpoint"]\t%s\n' "$(jq -r '.endpoint.arn' "$INVENTORY")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudwatch_log_group.agentcore_runtime["DEFAULT"]\t%s\n' "$(jq -r '.arn' "$WORK_DIR/agentcore-log-group-DEFAULT.json")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudwatch_log_group.agentcore_runtime["preview"]\t%s\n' "$(jq -r '.arn' "$WORK_DIR/agentcore-log-group-preview.json")" >>"$ADDRESS_INVENTORY"
printf 'aws_lambda_function_url.public_chat\t%s,%s\n' "$FUNCTION_NAME" "$QUALIFIER" >>"$ADDRESS_INVENTORY"
printf 'aws_lambda_permission.public_chat_url\t%s,%s,AllowCloudFrontFunctionUrlV2\n' "$FUNCTION_NAME" "$QUALIFIER" >>"$ADDRESS_INVENTORY"
printf 'aws_lambda_permission.public_chat_invoke\t%s,%s,AllowCloudFrontFunctionInvokeV2\n' "$FUNCTION_NAME" "$QUALIFIER" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_distribution.site\t%s\n' "$(jq -r '.distribution.id' "$INVENTORY")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_origin_access_control.site\t%s\n' "$(jq -r '.id' <<<"$SITE_OAC_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_origin_access_control.public_chat\t%s\n' "$(jq -r '.id' <<<"$PUBLIC_CHAT_OAC_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_response_headers_policy.development_noindex\t%s\n' "$(jq -r '.id' <<<"$RESPONSE_HEADERS_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_wafv2_web_acl.public_chat\t%s\n' "$(jq -r '.arn' <<<"$WAF_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_wafv2_web_acl_logging_configuration.agent_reports\t%s\n' "$(jq -r '.arn' <<<"$WAF_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_iam_role.development_delivery[0]\t%s\n' "$ROLE_ARN" >>"$ADDRESS_INVENTORY"
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  printf 'aws_iam_policy.development_delivery["%s"]\t%s\n' \
    "$policy_key" "${EXPECTED_POLICY_ARNS[$policy_key]}" >>"$ADDRESS_INVENTORY"
  printf 'aws_iam_role_policy_attachment.development_delivery["%s"]\t%s/%s\n' \
    "$policy_key" "$ROLE_NAME" "${EXPECTED_POLICY_ARNS[$policy_key]}" >>"$ADDRESS_INVENTORY"
done
printf 'aws_kms_alias.agent_measurement\talias/tollchat-v2-agent-measurement-dev\n' >>"$ADDRESS_INVENTORY"
printf 'aws_kms_alias.site\talias/tollchat-v2-site-dev\n' >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket.agent_measurement\taws-waf-logs-tollchat-agent-reports-%s-dev\n' "$EXPECTED_ACCOUNT" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket.site\ttollchat-site-%s-dev\n' "$EXPECTED_ACCOUNT" >>"$ADDRESS_INVENTORY"
for role_mapping in \
  'loader toll-v2-pricing-loader-dev' \
  'publisher toll-v2-report-publisher-dev' \
  'publisher_scheduler toll-v2-report-publisher-scheduler-dev' \
  'timed_checks nova-toll-v2-timed-checks-dev' \
  'tollchat_runtime nova-toll-v2-agentcore-runtime-dev' \
  'tollchat_proxy nova-toll-v2-chat-proxy-dev' \
  'usage_publisher tollchat-v2-usage-publisher-dev' \
  'agent_usage_rollup tollchat-v2-agent-usage-rollup-dev'; do
  IFS=' ' read -r address role_name <<<"$role_mapping"
  printf 'aws_iam_role.%s\tarn:aws:iam::%s:role/%s\n' "$address" "$EXPECTED_ACCOUNT" "$role_name" >>"$ADDRESS_INVENTORY"
done
for policy_mapping in \
  'loader toll-v2-pricing-loader-dev toll-v2-pricing-loader-dev' \
  'publisher toll-v2-report-publisher-dev toll-v2-report-publisher-dev' \
  'publisher_scheduler toll-v2-report-publisher-scheduler-dev toll-v2-report-publisher-scheduler-dev' \
  'timed_checks nova-toll-v2-timed-checks-dev nova-toll-v2-route-live-checks-dev' \
  'tollchat_runtime nova-toll-v2-agentcore-runtime-dev nova-toll-v2-agentcore-runtime-dev' \
  'tollchat_proxy nova-toll-v2-chat-proxy-dev nova-toll-v2-chat-proxy-dev' \
  'usage_publisher tollchat-v2-usage-publisher-dev tollchat-v2-usage-publisher-dev' \
  'agent_usage_rollup tollchat-v2-agent-usage-rollup-dev tollchat-v2-agent-usage-rollup-dev'; do
  IFS=' ' read -r address role_name policy_name <<<"$policy_mapping"
  printf 'aws_iam_role_policy.%s\t%s:%s\n' "$address" "$role_name" "$policy_name" >>"$ADDRESS_INVENTORY"
done
for attachment_mapping in \
  'loader_vpc toll-v2-pricing-loader-dev' \
  'publisher_vpc toll-v2-report-publisher-dev' \
  'tollchat_proxy_vpc nova-toll-v2-chat-proxy-dev'; do
  IFS=' ' read -r address role_name <<<"$attachment_mapping"
  printf 'aws_iam_role_policy_attachment.%s\t%s/arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole\n' "$address" "$role_name" >>"$ADDRESS_INVENTORY"
done
printf 'aws_athena_named_query.top_routes\t097b778f-c9ed-4bd9-af53-1e05770e1d53\n' >>"$ADDRESS_INVENTORY"
printf 'aws_athena_named_query.recent_routes\t6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d\n' >>"$ADDRESS_INVENTORY"
printf 'aws_athena_workgroup.agent_reports\ttollchat-agent-reports-dev\n' >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_public_access_block.agent_measurement\t%s\n' "$MEASUREMENT_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_policy.agent_measurement\t%s\n' "$MEASUREMENT_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_public_access_block.site\t%s\n' "$SITE_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_policy.site\t%s\n' "$SITE_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_kms_key.agent_measurement\t%s\n' "$(jq -r '.arn' "$WORK_DIR/kms-tollchat-v2-agent-measurement-dev.json")" >>"$ADDRESS_INVENTORY"
printf 'aws_kms_key.site\t%s\n' "$(jq -r '.arn' "$WORK_DIR/kms-tollchat-v2-site-dev.json")" >>"$ADDRESS_INVENTORY"

printf ',\n  "site_oac": %s,\n  "public_chat_oac": %s,\n  "response_headers_policy": %s,\n  "waf": %s,\n  "delivery_role_present": %s,\n  "function_url_present": %s,\n  "permission_policy_present": %s\n' \
  "$SITE_OAC_INFO" "$PUBLIC_CHAT_OAC_INFO" "$RESPONSE_HEADERS_INFO" "$WAF_INFO" \
  "$ROLE_PRESENT" "$URL_PRESENT" "$POLICY_PRESENT" >>"$INVENTORY"
printf ',\n  "reviewed_commit": "%s",\n  "fetcher_sha256": "%s",\n  "delivery_trust_sha256": "%s",\n  "delivery_policy_sha256": "%s"\n' \
  "$REVIEWED_COMMIT" "$FETCHER_SHA256" "$TRUST_SHA256" "$POLICY_SHA256" >>"$INVENTORY"
printf '%s\n' '}' >>"$INVENTORY"
jq -e '.account == "903859731897"' "$INVENTORY" >/dev/null

require_external_file() {
  local path="$1"
  case "$path" in
    /*) ;;
    *) die "evidence input must be an absolute path" ;;
  esac
  test -f "$path" && test ! -L "$path" || die "evidence input must be a regular non-symlink file"
  case "$(realpath -m -- "$path")" in "$ROOT"|"$ROOT"/*) die "evidence input must be outside checkout" ;; esac
}

run_iam_simulation() {
  local label="$1" action="$2" resource="$3" expected="$4" raw decision
  local -a context_args=()
  case "$label" in
    kms-*) context_args=(
      --context-entries
      ContextKeyName=aws:ResourceTag/environment,ContextKeyValues=development,ContextKeyType=string
      ContextKeyName=aws:ResourceTag/version,ContextKeyValues=v2,ContextKeyType=string
    ) ;;
  esac
  raw="$WORK_DIR/iam-simulation-$label.json"
  assert_dev_account
  aws iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" \
    --action-names "$action" --resource-arns "$resource" "${context_args[@]}" --output json >"$raw" ||
    die "IAM simulation failed: $label"
  jq -e '.EvaluationResults | type == "array" and length == 1' "$raw" >/dev/null ||
    die "IAM simulation result is missing or ambiguous: $label"
  decision="$(jq -r '.EvaluationResults[0].EvalDecision' "$raw")"
  if test "$expected" = allowed; then
    test "$decision" = allowed || die "expected IAM allow was not returned: $label"
  else
    case "$decision" in explicitDeny|implicitDeny) ;; *) die "expected IAM deny was not returned: $label" ;; esac
  fi
  jq -cn --arg label "$label" --arg action "$action" --arg resource "$resource" \
    --arg expected "$expected" --arg decision "$decision" \
    '{label:$label,action:$action,resource:$resource,expected:$expected,decision:$decision}' >>"$IAM_SIMULATION_LINES"
}

run_post_bootstrap_gates() {
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before post-bootstrap gates"
  IAM_SIMULATION_LINES="$WORK_DIR/iam-simulation-lines.jsonl"
  IAM_SIMULATION_EVIDENCE="$EVIDENCE_DIR/iam-simulations.json"
  test ! -e "$IAM_SIMULATION_EVIDENCE" || die "refusing to overwrite IAM simulation evidence"
  : >"$IAM_SIMULATION_LINES"
  SIMULATION_EXPECTED_COUNT=92
  SIMULATION_MATRIX="$WORK_DIR/iam-simulation-matrix.tsv"
  cat >"$SIMULATION_MATRIX" <<EOF
state-foundation-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/development/terraform.tfstate|allowed
state-application-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate|allowed
state-application-write|s3:PutObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate|allowed
state-lock-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate.tflock|allowed
state-lock-write|s3:PutObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate.tflock|allowed
state-lock-delete|s3:DeleteObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate.tflock|allowed
lambda-code|lambda:UpdateFunctionCode|$QUALIFIED_FUNCTION_ARN|allowed
lambda-version|lambda:PublishVersion|arn:aws:lambda:${REGION}:${EXPECTED_ACCOUNT}:function:${FUNCTION_NAME}|allowed
lambda-alias|lambda:UpdateAlias|$QUALIFIED_FUNCTION_ARN|allowed
lambda-retire|lambda:DeleteFunction|$QUALIFIED_FUNCTION_ARN|allowed
site-upload|s3:PutObject|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev/index.html|allowed
site-delete|s3:DeleteObject|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev/index.html|allowed
artifact-upload|s3:PutObject|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
artifact-delete|s3:DeleteObject|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
cloudfront-update|cloudfront:UpdateFunction|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
cloudfront-publish|cloudfront:PublishFunction|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
guardrail-version|bedrock:CreateGuardrailVersion|arn:aws:bedrock:${REGION}:${EXPECTED_ACCOUNT}:guardrail/vdyqrh31xgca|allowed
api-deployment-create|apigateway:POST|arn:aws:apigateway:${REGION}::/restapis/ocw8sg0wlb/deployments|allowed
api-deployment-delete|apigateway:DELETE|arn:aws:apigateway:${REGION}::/restapis/ocw8sg0wlb/deployments/reviewed|allowed
agentcore-runtime-update|bedrock-agentcore:UpdateAgentRuntime|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl|allowed
agentcore-endpoint-update|bedrock-agentcore:UpdateAgentRuntimeEndpoint|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl/runtime-endpoint/preview|allowed
events-targets|events:PutTargets|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|allowed
logs-retention|logs:PutRetentionPolicy|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|allowed
alarm-tags|cloudwatch:TagResource|arn:aws:cloudwatch:${REGION}:${EXPECTED_ACCOUNT}:alarm/tollchat-v2-chat-proxy-errors-dev|allowed
queue-read|sqs:GetQueueAttributes|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|allowed
athena-read|athena:GetNamedQuery|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:namedquery/097b778f-c9ed-4bd9-af53-1e05770e1d53|allowed
workgroup-update|athena:UpdateWorkGroup|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
sessions-update|dynamodb:UpdateTable|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
catalog-update|glue:UpdateTable|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat_agent_reports_development/*|allowed
schedule-update|scheduler:UpdateSchedule|arn:aws:scheduler:${REGION}:${EXPECTED_ACCOUNT}:schedule/default/toll-v2-report-publisher-dev|allowed
kms-use|kms:Encrypt|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:key/076e8341-894b-405c-96e9-2b037f96e2a6|allowed
site-ownership|s3:PutBucketOwnershipControls|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-tags|s3:PutBucketTagging|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-versioning|s3:PutBucketVersioning|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-encryption|s3:PutEncryptionConfiguration|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-lifecycle|s3:PutLifecycleConfiguration|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
registry-upload|s3:PutObject|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev/registry/agent_registry.ndjson|allowed
registry-delete|s3:DeleteObject|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev/registry/agent_registry.ndjson|allowed
artifact-abort|s3:AbortMultipartUpload|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
lambda-tag|lambda:TagResource|$QUALIFIED_FUNCTION_ARN|allowed
lambda-untag|lambda:UntagResource|$QUALIFIED_FUNCTION_ARN|allowed
events-disable|events:DisableRule|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|allowed
events-enable|events:EnableRule|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|allowed
events-remove-targets|events:RemoveTargets|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|allowed
events-tag|events:TagResource|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|allowed
events-untag|events:UntagResource|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|allowed
logs-tag|logs:TagResource|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|allowed
logs-untag|logs:UntagResource|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|allowed
alarm-untag|cloudwatch:UntagResource|arn:aws:cloudwatch:${REGION}:${EXPECTED_ACCOUNT}:alarm/tollchat-v2-chat-proxy-errors-dev|allowed
sessions-tag|dynamodb:TagResource|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
sessions-untag|dynamodb:UntagResource|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
sessions-backups|dynamodb:UpdateContinuousBackups|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
sessions-ttl|dynamodb:UpdateTimeToLive|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
catalog-tag|glue:TagResource|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat_agent_reports_development/agent_registry|allowed
catalog-untag|glue:UntagResource|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat_agent_reports_development/agent_registry|allowed
catalog-database|glue:UpdateDatabase|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:database/tollchat_agent_reports_development|allowed
athena-tag|athena:TagResource|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
athena-untag|athena:UntagResource|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
schedule-tag|scheduler:TagResource|arn:aws:scheduler:${REGION}:${EXPECTED_ACCOUNT}:schedule/default/toll-v2-report-publisher-dev|allowed
schedule-untag|scheduler:UntagResource|arn:aws:scheduler:${REGION}:${EXPECTED_ACCOUNT}:schedule/default/toll-v2-report-publisher-dev|allowed
agentcore-tag|bedrock-agentcore:TagResource|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl|allowed
agentcore-untag|bedrock-agentcore:UntagResource|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl|allowed
cloudfront-tag|cloudfront:TagResource|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
cloudfront-test|cloudfront:TestFunction|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
cloudfront-untag|cloudfront:UntagResource|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
kms-decrypt|kms:Decrypt|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:key/076e8341-894b-405c-96e9-2b037f96e2a6|allowed
kms-generate-data-key|kms:GenerateDataKey|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:key/076e8341-894b-405c-96e9-2b037f96e2a6|allowed
foundation-state-write|s3:PutObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/development/terraform.tfstate|denied
production-state-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate|denied
unrelated-site-write|s3:PutObject|arn:aws:s3:::unrelated-development-site/index.html|denied
unrelated-artifact-write|s3:PutObject|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v1/release.zip|denied
role-create|iam:CreateRole|$ROLE_ARN|denied
role-policy-write|iam:PutRolePolicy|$ROLE_ARN|denied
role-pass|iam:PassRole|$ROLE_ARN|denied
url-admin|lambda:AddPermission|$QUALIFIED_FUNCTION_ARN|denied
lambda-config-admin|lambda:UpdateFunctionConfiguration|$QUALIFIED_FUNCTION_ARN|denied
agentcore-create|bedrock-agentcore:CreateAgentRuntime|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/unrelated|denied
agentcore-policy-write|bedrock-agentcore:PutResourcePolicy|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/unrelated|denied
events-rule-write|events:PutRule|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|denied
logs-filter-write|logs:PutMetricFilter|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|denied
alarm-write|cloudwatch:PutMetricAlarm|arn:aws:cloudwatch:${REGION}:${EXPECTED_ACCOUNT}:alarm/tollchat-v2-chat-proxy-errors-dev|denied
waf-logging-write|wafv2:PutLoggingConfiguration|arn:aws:wafv2:${REGION}:${EXPECTED_ACCOUNT}:global/webacl/tollchat-v2-public-chat-dev/unrelated|denied
kms-alias-write|kms:CreateAlias|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:alias/tollchat-v2-site-dev|denied
sg-write|ec2:AuthorizeSecurityGroupIngress|arn:aws:ec2:${REGION}:${EXPECTED_ACCOUNT}:security-group/sg-unrelated|denied
sqs-policy-write|sqs:SetQueueAttributes|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|denied
sqs-policy-add|sqs:AddPermission|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|denied
sqs-policy-remove|sqs:RemovePermission|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|denied
athena-query-write|athena:CreateNamedQuery|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|denied
measurement-policy-write|s3:PutBucketPolicy|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|denied
measurement-exposure-write|s3:PutBucketPublicAccessBlock|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|denied
iam-attachment-write|iam:AttachRolePolicy|$ROLE_ARN|denied
kms-alias-update|kms:UpdateAlias|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:alias/tollchat-v2-site-dev|denied
EOF
  SIMULATION_COUNT=0
  while IFS='|' read -r label action resource expected; do
    test -n "$label" || continue
    run_iam_simulation "$label" "$action" "$resource" "$expected"
    SIMULATION_COUNT=$((SIMULATION_COUNT + 1))
  done <"$SIMULATION_MATRIX"
  test "$SIMULATION_COUNT" -eq "$SIMULATION_EXPECTED_COUNT" || die "IAM simulation matrix is incomplete"

  REVIEWED_V2_PACKAGE_DIR="${REVIEWED_V2_PACKAGE_DIR:?set the absolute path to trusted v2 release packages}"
  REVIEWED_V2_PACKAGE_MANIFEST="${REVIEWED_V2_PACKAGE_MANIFEST:?set the absolute path to the reviewed package digest manifest}"
  case "$REVIEWED_V2_PACKAGE_DIR" in /*) ;; *) die "package directory must be absolute" ;; esac
  case "$(realpath -m -- "$REVIEWED_V2_PACKAGE_DIR")" in "$ROOT"|"$ROOT"/*) die "packages must be trusted artifacts outside checkout" ;; esac
  test -d "$REVIEWED_V2_PACKAGE_DIR" && test ! -L "$REVIEWED_V2_PACKAGE_DIR" || die "package directory must be a regular directory"
  require_external_file "$REVIEWED_V2_PACKAGE_MANIFEST"
  test "$(realpath -m -- "$REVIEWED_V2_PACKAGE_MANIFEST")" != "$INVENTORY" || die "package manifest cannot be inventory"
  for package in loader.zip publisher.zip agentcore.zip chat-proxy.zip; do
    require_external_file "$REVIEWED_V2_PACKAGE_DIR/$package"
  done
  PACKAGE_DIGESTS="$WORK_DIR/package-digests.tsv"
  : >"$PACKAGE_DIGESTS"
  for package in loader.zip publisher.zip agentcore.zip chat-proxy.zip; do
    sha256sum "$REVIEWED_V2_PACKAGE_DIR/$package" | awk -v name="$package" '{print $1 "\t" name}' >>"$PACKAGE_DIGESTS"
  done
  PACKAGE_DIGESTS_JSON="$(jq -Rn '[inputs | split("\t") | {sha256: .[0], name: .[1]}]' <"$PACKAGE_DIGESTS")"
  python3 - "$REVIEWED_V2_PACKAGE_MANIFEST" "$REVIEWED_V2_PACKAGE_DIR" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

expected = {"loader.zip", "publisher.zip", "agentcore.zip", "chat-proxy.zip"}
manifest = Path(sys.argv[1])
directory = Path(sys.argv[2])
entries = {}
for line in manifest.read_text().splitlines():
    fields = line.split()
    if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
        raise SystemExit("invalid package digest manifest")
    if fields[1] not in expected or fields[1] in entries:
        raise SystemExit("unexpected or duplicate package in manifest")
    entries[fields[1]] = fields[0]
if set(entries) != expected:
    raise SystemExit("package digest manifest is incomplete")
for name, digest in entries.items():
    actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f"package digest mismatch: {name}")
PY

  REPRESENTATIVE_PLAN="$WORK_DIR/representative-development.tfplan"
  REPRESENTATIVE_PLAN_JSON="$WORK_DIR/representative-development.tfplan.json"
  REPRESENTATIVE_PLAN_EVIDENCE="$EVIDENCE_DIR/representative-plan.tsv"
  test ! -e "$REPRESENTATIVE_PLAN_EVIDENCE" || die "refusing to overwrite representative plan evidence"
  terraform -chdir="$ROOT/v2/infra" plan -input=false -out="$REPRESENTATIVE_PLAN" \
    -var-file=development.tfvars -var-file="$BOOTSTRAP_FOUNDATION_VARS" \
    -var "loader_package_path=$REVIEWED_V2_PACKAGE_DIR/loader.zip" \
    -var "publisher_package_path=$REVIEWED_V2_PACKAGE_DIR/publisher.zip" \
    -var "agentcore_package_path=$REVIEWED_V2_PACKAGE_DIR/agentcore.zip" \
    -var "chat_proxy_package_path=$REVIEWED_V2_PACKAGE_DIR/chat-proxy.zip"
  terraform -chdir="$ROOT/v2/infra" show -json "$REPRESENTATIVE_PLAN" >"$REPRESENTATIVE_PLAN_JSON"
  PLAN_GATE_SOURCE="$ROOT/.github/workflows/v2-development-delivery.yml"
  require_reviewed_file "$PLAN_GATE_SOURCE"
  PLAN_GATE="$WORK_DIR/development-plan-gate.py"
  sed -n '/python3 - "\$PLAN_JSON" <<'"'"'PY'"'"'/,/^          PY$/p' "$PLAN_GATE_SOURCE" |
    sed '1d;$d;s/^          //' >"$PLAN_GATE"
  test -s "$PLAN_GATE" || die "saved-plan gate source is missing"
  python3 "$PLAN_GATE" "$REPRESENTATIVE_PLAN_JSON"
  REPRESENTATIVE_PLAN_BODY="$WORK_DIR/representative-plan-body.tsv"
  python3 - "$REPRESENTATIVE_PLAN_JSON" "$REPRESENTATIVE_PLAN_BODY" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text())
changes = plan.get("resource_changes")
if not isinstance(changes, list):
    raise SystemExit("saved plan has no resource_changes array")
allowed = {"no-op", "create", "update", "delete", "read"}
rows = []
for change in changes:
    if not isinstance(change, dict) or not isinstance(change.get("address"), str):
        raise SystemExit("saved plan has an invalid resource address")
    actions = change.get("change", {}).get("actions")
    if not isinstance(actions, list) or not actions or any(action not in allowed for action in actions):
        raise SystemExit("saved plan has an invalid action array")
    rows.append((change["address"], ",".join(actions)))
Path(sys.argv[2]).write_text("terraform_address\tactions\n" + "".join(f"{a}\t{b}\n" for a, b in sorted(rows)))
PY
  PLAN_SHA256="$(sha256sum "$REPRESENTATIVE_PLAN" | awk '{print $1}')"
  EVIDENCE_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  EVIDENCE_BINDING="$EVIDENCE_DIR/evidence-binding.json"
  test ! -e "$EVIDENCE_BINDING" || die "refusing to overwrite evidence binding"
  jq -n --arg commit_sha "$REVIEWED_COMMIT" --arg account_id "$EXPECTED_ACCOUNT" \
    --arg role_arn "$ROLE_ARN" --arg trust_sha256 "$TRUST_SHA256" \
    --arg policy_sha256 "$POLICY_SHA256" --arg plan_sha256 "$PLAN_SHA256" \
    --arg fetcher_sha256 "$FETCHER_SHA256" --arg timestamp "$EVIDENCE_TIMESTAMP" \
    --argjson package_digests "$PACKAGE_DIGESTS_JSON" \
    '{commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,trust_sha256:$trust_sha256,policy_sha256:$policy_sha256,fetcher_sha256:$fetcher_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp,package_digests:$package_digests}' \
    >"$EVIDENCE_BINDING" || die "could not generate evidence binding"
  chmod 600 -- "$EVIDENCE_BINDING"
  BINDING_SHA256="$(sha256sum "$EVIDENCE_BINDING" | awk '{print $1}')"
  jq --arg commit_sha "$REVIEWED_COMMIT" --arg account_id "$EXPECTED_ACCOUNT" \
    --arg role_arn "$ROLE_ARN" --arg policy_sha256 "$POLICY_SHA256" \
    --arg plan_sha256 "$PLAN_SHA256" --arg timestamp "$EVIDENCE_TIMESTAMP" \
    --arg binding_sha256 "$BINDING_SHA256" \
    '. + {commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,policy_sha256:$policy_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp,binding_sha256:$binding_sha256}' \
    "$INVENTORY" >"$WORK_DIR/inventory-bound.json" || die "could not bind inventory evidence"
  mv -- "$WORK_DIR/inventory-bound.json" "$INVENTORY"
  ADDRESS_INVENTORY_BODY="$WORK_DIR/terraform-addresses-body.tsv"
  mv -- "$ADDRESS_INVENTORY" "$ADDRESS_INVENTORY_BODY"
  {
    printf 'evidence_binding_sha256\t%s\ncommit_sha\t%s\naccount_id\t%s\nrole_arn\t%s\npolicy_sha256\t%s\nplan_sha256\t%s\ntimestamp\t%s\n' \
      "$BINDING_SHA256" "$REVIEWED_COMMIT" "$EXPECTED_ACCOUNT" "$ROLE_ARN" "$POLICY_SHA256" "$PLAN_SHA256" "$EVIDENCE_TIMESTAMP"
    cat -- "$ADDRESS_INVENTORY_BODY"
  } >"$ADDRESS_INVENTORY"
  chmod 600 -- "$ADDRESS_INVENTORY"
  {
    printf 'evidence_binding_sha256\t%s\n' "$BINDING_SHA256"
    printf 'commit_sha\t%s\naccount_id\t%s\nrole_arn\t%s\npolicy_sha256\t%s\nplan_sha256\t%s\ntimestamp\t%s\n' \
      "$REVIEWED_COMMIT" "$EXPECTED_ACCOUNT" "$ROLE_ARN" "$POLICY_SHA256" "$PLAN_SHA256" "$EVIDENCE_TIMESTAMP"
    cat -- "$REPRESENTATIVE_PLAN_BODY"
  } >"$REPRESENTATIVE_PLAN_EVIDENCE"
  chmod 600 -- "$REPRESENTATIVE_PLAN_EVIDENCE"
  jq -n --slurpfile simulations "$IAM_SIMULATION_LINES" \
    --arg binding_sha256 "$BINDING_SHA256" --arg commit_sha "$REVIEWED_COMMIT" \
    --arg account_id "$EXPECTED_ACCOUNT" --arg role_arn "$ROLE_ARN" \
    --arg policy_sha256 "$POLICY_SHA256" --arg plan_sha256 "$PLAN_SHA256" \
    --arg timestamp "$EVIDENCE_TIMESTAMP" --argjson count "$SIMULATION_COUNT" \
    '{binding_sha256:$binding_sha256,context:{commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,policy_sha256:$policy_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp},simulation_count:$count,simulations:$simulations}' \
    >"$IAM_SIMULATION_EVIDENCE" || die "could not bind IAM simulation evidence"
  chmod 600 -- "$IAM_SIMULATION_EVIDENCE"

  PROTECTED_MAIN_OIDC_EVIDENCE="${PROTECTED_MAIN_OIDC_EVIDENCE:?set the sanitized protected-main OIDC proof path}"
  require_external_file "$PROTECTED_MAIN_OIDC_EVIDENCE"
  OIDC_PROOF="$EVIDENCE_DIR/protected-main-oidc.json"
  test ! -e "$OIDC_PROOF" || die "refusing to overwrite protected-main OIDC evidence"
  jq -e --arg commit "$REVIEWED_COMMIT" '
    type == "object" and (keys_unsorted | sort) == ["account", "commit_sha", "environment", "proof", "ref", "repository"] and
    .proof == "protected-main-oidc" and .account == "903859731897" and
    .commit_sha == $commit and
    .environment == "development" and .ref == "refs/heads/main" and
    .repository == "rhprasad0/nova-toll-budget-agent"
  ' "$PROTECTED_MAIN_OIDC_EVIDENCE" >/dev/null ||
    die "protected-main OIDC proof is not the exact development account proof"
  jq -n --slurpfile proof "$PROTECTED_MAIN_OIDC_EVIDENCE" \
    --arg binding_sha256 "$BINDING_SHA256" --arg commit_sha "$REVIEWED_COMMIT" \
    --arg account_id "$EXPECTED_ACCOUNT" --arg role_arn "$ROLE_ARN" \
    --arg policy_sha256 "$POLICY_SHA256" --arg plan_sha256 "$PLAN_SHA256" \
    --arg timestamp "$EVIDENCE_TIMESTAMP" \
    '{binding_sha256:$binding_sha256,context:{commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,policy_sha256:$policy_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp},proof:$proof[0]}' \
    >"$OIDC_PROOF" || die "could not bind protected-main OIDC evidence"
  chmod 600 -- "$OIDC_PROOF"
}

run_post_bootstrap_gates
BOOTSTRAP_COMPLETE=1
printf 'non-secret inventory: %s\naddress map: %s\n' "$INVENTORY" "$ADDRESS_INVENTORY"
```

After bootstrap/import, the recurring OIDC role may refresh the same state,
perform explicitly allowed updates, upload reviewed release artifacts, and
perform only the four named immutable release families: the development API
Gateway deployment, published/retired versions of the five named development
Lambda functions, the two named development CloudFront functions, and the
named development Bedrock guardrail version (publication only; its Terraform
resource uses `skip_destroy`). It cannot create, replace, or administer the
bootstrap addresses above. The workflow's rendered-plan gate
must pass before the exact saved plan is applied. A missing import, unknown
address/action, or failed gate stops for an administrator. The foundation
Terraform root owns the route-control role, fixed SSM document, and their
trust/policy resources; they are intentionally absent from v2 application
Terraform and the recurring delivery plan.

The protected `main` branch plus the protected GitHub `development` environment
is the reviewed release source for this identity. Publishing arbitrary code to
the named development Lambda/site objects and the two named development
CloudFront functions is therefore an intentional delivery capability; the
AWS policy bounds those calls to exact development resources, while the saved
Terraform-plan gate bounds only Terraform changes. The identity still cannot
switch roles, access production or foundation-write paths, create bootstrap
resources, change public URL permissions, or alter measurement exposure
controls.

### Development application release and database validation (#331)

This is the only operative #331 release procedure. It uses only the development
account and the two development state backends. The typed, non-secret foundation
output is consumed ephemerally from the #330 development foundation state. The
manual bootstrap/import creates or inventories the CloudFront distribution with
no aliases and the CloudFront default certificate. Recurring plans consume that
existing distribution and its d*.cloudfront.net hostname; they never create or
delete the distribution. Slice 3 custom-domain staging is an administrator-owned
development apply plus the separately trusted production-foundation DNS gate
below; recurring delivery remains explicitly disabled for that input.

When direct workstation access to the private RDS endpoint is unavailable, an
already-authorized development private path may forward the endpoint to a local
port. Set `NOVA_TOLL_RDS_LOCAL_PORT` to that port before this procedure; the
procedure keeps `PGHOST` set to the RDS endpoint so TLS hostname verification
still applies and uses only `127.0.0.1` as the transport address. Local
forwarding requires `NOVA_TOLL_EXPECTED_RDS_ENDPOINT` to match the real RDS
hostname and `NOVA_TOLL_ADMIN_URL` to carry explicit nonempty
`sslmode=verify-full` and `sslrootcert` settings. Ambient `PG*` values never
rescue a missing, mismatched, or downgraded URL setting; any such input stops
before `psql`.

The authorized replacement may initialize only the Terraform-created
`nova_toll_development` database after the protected route and saved-plan steps
complete. If that exact database is absent, non-empty, ambiguous, or already
bootstrapped, stop; do not run the fresh mode and do not use a versioned
migration. The bounded procedure is documented in the development foundation
replacement handoff below.

Keep the terminal non-traced. The development RDS-managed Secrets Manager JSON and
its extracted username/password exist only in process memory and are never
printed, placed in an argument, written to a file, put in Terraform input/state/
plan, or recorded in evidence.

#### Slice 2A development 4via6 policy handoff and allocation gate

The overlapping development VPC input is `172.31.0.0/16`. Tailscale site ID `1`
derives the stable development route
`fd7a:115c:a1e0:b1a:0:1:ac1f:0/112`. The current development RDS endpoint
`nova-toll-db.cc3usg2wmx63.us-east-1.rds.amazonaws.com` resolved to
`172.31.4.167`, whose site-1 transport host is
`fd7a:115c:a1e0:b1a:0:1:ac1f:4a7/128`. Re-resolve the endpoint and regenerate
that host immediately before Slice 2B activation; this address is a current
policy-test fixture, not a permanent DNS record. The later TLS connection keeps
the RDS DNS name in `PGHOST` for hostname verification and uses the 4via6 host
only as `PGHOSTADDR`. Confirm both derivations with
`tailscale debug via 1 172.31.0.0/16` and
`tailscale debug via 1 172.31.4.167/32` before handoff.

Before any protected connectivity verification, create a separate protected
route-control OAuth client with only the documented device-inventory read scope
`devices:core:read` and route-management scope `devices:routes`. The existing
`TS_DEVELOPMENT_OAUTH_CLIENT_ID` and `TS_DEVELOPMENT_OAUTH_SECRET` client remains
`auth_keys`-only for the third-party `tailscale/github-action`; its values stay
opaque to operators, logs, arguments, artifacts, and summaries. The route
helper uses only `TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID` and
`TS_DEVELOPMENT_ROUTE_OAUTH_SECRET`. Do not use a personal API token, an ACL
OAuth client, or a legacy device identifier.
The helper requests exactly the space-delimited scope string
`devices:core:read devices:routes` and rejects a token response with missing,
duplicated, insufficient, or additional scope tokens.

The protected `workflow_dispatch` run is the sole route-control boundary. It
must run from `refs/heads/main`, retain the `development` environment reviewer,
and keep `DEVELOPMENT_DELIVERY_ENABLED` absent or false. The foundation
Terraform root creates and maintains the separate
`nova-toll-v2-route-control-dev` role; the workflow assumes that
administrator-controlled role first. It sends exactly one fixed, no-parameter
custom SSM document named
`nova-toll-v2-route-control-status-dev` to instance `i-0d33b9a9c15db93fc` in
`us-east-1`. The document contains only `set -eu` and `tailscale status --json`,
then the helper reads only that command's status and output. The command
document is not `AWS-RunShellScript`, and callers cannot provide commands.
The command must be successful, have response code `0`, empty stderr, and one
JSON document with a nonempty `Self.ID`. The helper
`v2/scripts/approve_development_tailscale_route.py` never prints that private
output or the OAuth bearer.

The helper exchanges the route-control secrets in memory, requests the complete
all-at-once `GET /api/v2/tailnet/rhprasad0.github/devices?fields=all`
inventory, and rejects any pagination/continuation marker, malformed field,
duplicate `nodeId`, duplicate route, noncanonical route, IPv4 on the bound
device, foreign or ambiguous site-1 4via6 route, collision, or tag ambiguity.
It selects exactly the API `nodeId` equal to SSM `Self.ID`; that device must
have exactly `tag:nova-toll-development-router`, and the exact
`fd7a:115c:a1e0:b1a:0:1:ac1f:0/112` must already be advertised there. If the
route is not yet advertised, stop and use the reviewed exact-instance SSM
advertisement procedure below.

Immediately before a write, the helper re-fetches and revalidates the complete
inventory. If the exact route is already enabled, it succeeds without a POST.
Otherwise it sends exactly one
`POST /api/v2/device/<nodeId>/routes` containing the complete current
`enabledRoutes` list plus the exact route, preserving every unrelated entry.
The API scope must include `devices:routes`; a 401/403, timeout, invalid
response, or uncertain write is a hard failure and is never retried. A
successful write is followed by a complete inventory read proving the same
SSM/API node binding, sole tag ownership, no intended-device IPv4, and both
advertised/enabled exact-route state. The API has no conditional version, so the
pre-write re-fetch still has an irreducible sub-request TOCTOU window; drift is
rejected before POST and the exact post-write readback is mandatory. Only the
sanitized identity/route booleans are recorded as evidence.

Any SSM, OAuth, inventory, identity, ownership, route, POST, or post-read
failure stops before the DB role is assumed. Do not guess a device, accept a
partial list, use an alternate credential, or continue to TLS/SQL checks.

After the diagnostic source change is merged, inspect the unknown route state
with the protected workflow's manual `route-diagnostic` phase before any
approval attempt:

```sh
gh workflow run v2-development-connectivity-verification.yml \
  --ref main --field phase=route-diagnostic
```

Approve the `development` environment as usual. This phase skips the
Tailscale auth-key action, timed-checks role, route approval, transport, and
SQL steps; it assumes only the fixed route-control role and records only the
sanitized JSON summary. Keep the reviewer and delivery gate unchanged. A
non-success stage, missing/foreign route state, or any indication that the
earlier run reached a POST remains a hard stop for human review.

#### Slice 2B development router and protected connectivity handoff

This section is a post-merge operator procedure. The builder and deterministic
tests do not create credentials, enroll the existing instance, advertise a
route, apply the policy, change GitHub settings, or connect to PostgreSQL.
The only live router target is development account `903859731897`, instance
`i-0d33b9a9c15db93fc`, in `us-east-1`; never substitute a name, public address,
or a production instance. The development route is exactly
`fd7a:115c:a1e0:b1a:0:1:ac1f:0/112`. No VPC route, IPv4 route, exit node, SG,
peering, public RDS setting, or production route is part of this handoff.

##### Policy and one-off router key

1. In **Tailscale Admin Console → Access controls → Policy file**, confirm the
   merged protected-main GitOps policy is applied. Do not edit the policy in
   the console after that confirmation.
2. In **Keys → Generate auth key**, create one key with a description such as
   `nova-toll development router`, **one-off**, **non-ephemeral**,
   **pre-approved** when device approval is enabled, a short expiry of at most
   90 days, and **only** the tag
   `tag:nova-toll-development-router`. Generate it and copy it once into a
   secure prompt. Do not create a reusable key, add a second tag, or retain the
   plaintext.
3. In the development AWS account, keep the terminal non-traced (`set +x`),
   set `AWS_REGION=us-east-1` and `AWS_DEFAULT_REGION=us-east-1`, and verify
   `aws sts get-caller-identity` reports `903859731897`. Read the copied key
   only into process memory and pipe the request body to AWS CLI stdin; the key
   is never a command argument, output, file, Terraform input/state, GitHub
   secret, log, or evidence field:

   ```sh
   set +x
   umask 077
   export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
   test "$(aws sts get-caller-identity --query Account --output text)" = "903859731897"
   read -r -s ROUTER_KEY
   printf '{"Name":"/nova-toll/tailscale-authkey","Type":"SecureString","Value":"%s","Overwrite":true}\n' "$ROUTER_KEY" |
     aws --region us-east-1 ssm put-parameter --cli-input-json file:///dev/stdin >/dev/null
   unset ROUTER_KEY
   aws --region us-east-1 ssm describe-parameters \
     --parameter-filters 'Key=Name,Option=Equals,Values=/nova-toll/tailscale-authkey' \
     --query 'Parameters[0].{Name:Name,Type:Type,Version:Version}' --output json
   ```

   The metadata check must show only the expected name, `SecureString`, and a
   version. Never use `get-parameter --with-decryption` on the operator host.

##### Existing-instance enrollment and route allocation

Use only SSM Run Command against `i-0d33b9a9c15db93fc`; do not open SSH or
enroll a replacement. This command decrypts the temporary key in the remote
process, disables tracing before the key is read, joins with Tailscale SSH, and
advertises no route:

```sh
set +x
INSTANCE_ID=i-0d33b9a9c15db93fc
test "$INSTANCE_ID" = i-0d33b9a9c15db93fc
test "$(aws sts get-caller-identity --query Account --output text)" = 903859731897
COMMAND_ID="$(aws --region us-east-1 ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["set +x","set -eu","KEY=$(aws --region us-east-1 ssm get-parameter --name /nova-toll/tailscale-authkey --with-decryption --query Parameter.Value --output text)","tailscale up --authkey=\"$KEY\" --ssh","unset KEY"]' \
  --query Command.CommandId --output text)"
aws --region us-east-1 ssm wait command_executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
test "$(aws --region us-east-1 ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query Status --output text)" = Success
```

After enrollment, do not select the device by hostname, address, or the
legacy device identifier. The protected workflow obtains the local
Tailscale node ID from the exact instance's SSM `Self.ID` and binds that
value to exactly one API `nodeId` with exactly the router tag.

In the existing development account, advertise the route only through the
reviewed exact-instance SSM command below. This changes advertisement only;
it does not approve an enabled route:

```sh
set +x
INSTANCE_ID=i-0d33b9a9c15db93fc
test "$INSTANCE_ID" = i-0d33b9a9c15db93fc
COMMAND_ID="$(aws --region us-east-1 ssm send-command \
  --instance-ids i-0d33b9a9c15db93fc \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["set +x","set -eu","tailscale set --advertise-routes=fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"]' \
  --query Command.CommandId --output text)"
aws --region us-east-1 ssm wait command_executed --command-id "$COMMAND_ID" --instance-id i-0d33b9a9c15db93fc
test "$(aws --region us-east-1 ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id i-0d33b9a9c15db93fc --query Status --output text)" = Success
```

Immediately dispatch the protected connectivity workflow from the reviewed
`main` SHA with `phase=pre-bootstrap`. Its route-control step passes only when
the complete all-at-once inventory has the exact route in both
`advertisedRoutes` and `enabledRoutes`, owned only by the exact SSM/API-bound
device. Its pre-bootstrap phase then proves that the derived site-1 host uses
`tailscale0` and accepts a bounded TCP/5432 connection, without assuming the
database role that fresh bootstrap has not created yet. It rejects partial or
marked inventories, duplicate or malformed data, IPv4 on the bound device,
foreign or ambiguous site-1 routes, collisions, tag drift, scope failure, and
any uncertain API result before the transport check. The workflow records only
its sanitized route/transport summary; this phase is not the full SQL proof.

Dispatch it only from protected `main`, and keep
`DEVELOPMENT_DELIVERY_ENABLED` absent or false:

```sh
gh workflow run v2-development-connectivity-verification.yml \
  --repo rhprasad0/nova-toll-budget-agent --ref main -f phase=pre-bootstrap
```

If route approval or post-write proof fails, stop before TLS or SQL. Never
retry an uncertain POST. With the still-proven exact node binding, restore
the complete pre-write `enabledRoutes` list in one bounded replacement POST,
preserving every unrelated entry; never replace it with a guessed single
route. Then remove only the development advertisement through the exact
instance SSM command below and prove that no site-1 route remains before any
retry. If identity, command status, route state, or the pre-write list is
uncertain, stop for human review and do not guess a rollback target.

The remote rollback command is exactly `tailscale set --advertise-routes=""`:

```sh
set +x
test "$INSTANCE_ID" = i-0d33b9a9c15db93fc
DISABLE_COMMAND_ID="$(aws --region us-east-1 ssm send-command \
  --instance-ids i-0d33b9a9c15db93fc \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["set +x","set -eu","tailscale set --advertise-routes=\"\""]' \
  --query Command.CommandId --output text)"
aws --region us-east-1 ssm wait command_executed --command-id "$DISABLE_COMMAND_ID" --instance-id i-0d33b9a9c15db93fc
test "$(aws --region us-east-1 ssm get-command-invocation --command-id "$DISABLE_COMMAND_ID" --instance-id i-0d33b9a9c15db93fc --query Status --output text)" = Success
```

The final inventory proof must be complete, all-at-once, and show no site-1
route in `advertisedRoutes`; an uncertain SSM/API response remains a hard
stop. No failure or rollback path changes production.
##### Manual development TLS/query verification

The separate
`.github/workflows/v2-development-connectivity-verification.yml` is the sole
pre-enable CI proof. It is `workflow_dispatch` only, must be dispatched from
`refs/heads/main` while `DEVELOPMENT_DELIVERY_ENABLED` is absent or `false`,
and accepts `phase=pre-bootstrap` for the route/transport proof above or
`phase=full` for the post-bootstrap SQL and production-denial proof. The
workflow uses the protected `development` environment and has only
`contents: read`/`id-token: write`. Its Tailscale OAuth client has only the
`auth_keys` scope and only `tag:ci-development`; its only AWS role is
`arn:aws:iam::903859731897:role/nova-toll-v2-timed-checks-dev`. It has no
delivery, Terraform, apply, package, write-capable AWS, production secret,
production route, or production SQL path.

Before dispatch, an AWS development-account administrator must confirm that
the timed-check role trust retains audience `sts.amazonaws.com` and, for the
development deployment, includes exactly the development environment subject
`repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development`.
The `development` branch of the IaC condition must not admit the
protected-main branch subject; the secret-bearing connectivity role is usable
only by the protected `development` environment. The production foundation
variant retains only the protected-main branch subject.
The IaC trust in `v2/infra/main.tf` is the source of truth. The role policy is
limited to development `rds:DescribeDBInstances`, development
`rds-db:connect` as `pricing_caller_development`, and its pre-existing
OpenAI-parameter read; it has no deployment, Terraform, SSM write, Secrets
Manager, or production resource permission.

The verifier resolves the development RDS endpoint with
`aws rds describe-db-instances` and native `getent ahostsv4`, immediately
derives the site-1 `/128` with `tailscale debug via 1 <ipv4>/32` and Python's
standard-library `ipaddress`, and rejects a stale or non-site-1 result. The
`pre-bootstrap` phase stops after validating the `tailscale0` route and a
bounded TCP/5432 connection to the derived host, so it does not require
`pricing_caller_development`. Run the `full` phase only after fresh bootstrap;
it keeps the refreshed RDS DNS name in `PGHOST` and for IAM-token generation,
puts only the derived IPv6 address in `PGHOSTADDR`, uses the pinned RDS CA with
`PGSSLMODE=verify-full`, and runs one bounded query only:
`SELECT current_database(), current_user`. The expected result is exactly
`nova_toll_development` and `pricing_caller_development`; no query rows,
password, IAM token, OAuth value, or raw command output is evidence.

For the production boundary, the verifier proves the caller is account
`903859731897` and role `nova-toll-v2-timed-checks-dev`, resolves only the
documented production endpoint as needed for a route check, and uses the Linux
JSON route decision to assert that the production address is not selected
through `tailscale0`. (`tailscale debug via` only derives 4via6 addresses; it is
not a route probe.) It then makes one short TCP/5432 socket attempt with no
production credentials and no SQL. A successful connection or unexpected local
error fails the run; bounded refusal, timeout, host/network-unreachable, or
permission-denied results prove socket denial. It never calls a production RDS
API. The existing development database contract remains the source for both
development-to-production and production-to-development cross-database denial;
no deployed schema or role change is allowed.

The verifier writes one sanitized commit/run-bound summary containing only
`commit_sha`, `run_id`, `run_attempt`, `ref`, development account/role,
expected route, transport-validation boolean, query identity/database, and
explicit production-route/socket denial booleans. Record that summary with the
policy success, exact route ownership and enablement, development TLS/query,
both production-boundary denials, and the delivery-role bootstrap/simulated
GitHub-main OIDC proof before enabling delivery.

##### Protected activation and rollback

In **GitHub repository Settings → Environments → development**, retain the
branch-policy protection rule and add a required owner/admin reviewer before
adding any environment secret. In **Tailscale Admin Console → Settings → OAuth
clients → Generate OAuth client**, retain the existing client described as
`nova-toll development CI` with scope `auth_keys` only and tag only
`tag:ci-development`. Copy it once into the protected environment as exactly
`TS_DEVELOPMENT_OAUTH_CLIENT_ID` and `TS_DEVELOPMENT_OAUTH_SECRET`; these names
remain exclusively for the third-party action. Create a second client for the
route helper with only `devices:core:read` and `devices:routes` (no `all`, ACL,
or other scopes), and copy it as exactly
`TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID` and
`TS_DEVELOPMENT_ROUTE_OAUTH_SECRET`. Keep both values opaque. Do not replace
repository production `TS_OAUTH_*` or policy `TS_ACL_OAUTH_*` secrets.

The delivery workflow's build job remains harmless without AWS OIDC. Its
development deploy job has the job-level false-closed condition
`vars.DEVELOPMENT_DELIVERY_ENABLED == 'true'`, evaluated before the job declares
its protected environment or requests OIDC. GitHub environment variables are
not available at that point, so this must be a **repository variable**. Keep it
absent (or literal `false`) through policy, key, router, route, role, OAuth, and
manual-verification setup. After every evidence item passes and the manual
workflow succeeds on `main`, an authorized operator may set it in **Settings →
Secrets and variables → Actions → Variables → New repository variable** with
name `DEVELOPMENT_DELIVERY_ENABLED` and value `true`, save it, and obtain the
required `development` environment reviewer approval when the deploy job starts.
The equivalent operator-only CLI activation is:

```sh
gh variable set DEVELOPMENT_DELIVERY_ENABLED --body true \
  --repo rhprasad0/nova-toll-budget-agent
```

Rollback is ordered and false-first: delete that exact repository variable or
set it to literal `false`, confirm a later delivery run is skipped without an
OIDC request, then disable and recheck the development route. Only after that
may the operator revoke the development CI OAuth client if needed and close the
router-key lifecycle. The equivalent rollback CLI call is
`gh variable delete DEVELOPMENT_DELIVERY_ENABLED --repo rhprasad0/nova-toll-budget-agent`.
No rollback action mutates production.

#### Slice 3 development custom-domain and DNS handoff

This is a bounded, post-merge operator procedure. The application state remains
in development account `903859731897`, region `us-east-1`, backend
`v2/infra/backend.development.hcl`, and distribution `E33DVF3KT7BTAC` with
hostname `d1wqry4fbd92w5.cloudfront.net` (all are re-read and checked immediately
before use). The foundation DNS workflow runs in production account
`920534282028` only to read the exact SSM parameter
`arn:aws:ssm:us-east-1:920534282028:parameter/nova-toll/cloudflare-development-dns-api-token`.
It has no application, state, CloudFront, ACM, or cross-account AWS access.
The token is read into the workflow process only, never printed, passed to
development, put in Terraform input/state, or retained in an artifact.

The Terraform switch `enable_development_custom_domain` defaults to `false` and
is explicitly false in recurring `development.tfvars` and the development
delivery workflow. With it false, the development distribution has no aliases,
uses the CloudFront default certificate and `TLSv1`, and has no development ACM
resource. Production keeps its existing certificate, aliases, validation records,
resource addresses, and Cloudflare provider path. Do not set the switch in the
recurring delivery job. The switch is enabled only for the administrator-owned
staging/apply described here; the development delivery role remains unable to
request ACM certificates or update CloudFront aliases/certificates.

##### Protected environment and preflight

1. Start from a clean, protected `origin/main` checkout. Confirm the existing
   `DEVELOPMENT_DELIVERY_ENABLED` false/absent gate, the development health and
   connectivity workflows, and the Slice 2 route/TLS/query evidence. Do not
   enable delivery as part of this procedure. The DNS workflow must be dispatched
   only from `refs/heads/main` with the protected GitHub environment named exactly
   `production-foundation-dns`; its required reviewer must approve the run.
2. In the production foundation state, apply the reviewed role only after the
   plan shows `nova-toll-production-foundation-dns` and exactly one policy action:
   `ssm:GetParameter` on the exact parameter ARN above. Confirm its trust uses
   only the GitHub OIDC provider, `aud=sts.amazonaws.com`, and the immutable
   subject
   `repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production-foundation-dns`.
   There is no branch wildcard, pull-request subject, development role, state
   bucket, KMS, Secrets Manager, or application permission.
3. In **Settings → Environments**, create the protected environment
   `production-foundation-dns` with a required owner/admin reviewer and a `main`
   branch policy. Do not add a Cloudflare secret to GitHub. The workflow obtains
   the token only through the production role's SSM read. Check the action SHAs
   and the exact `role-to-assume` before dispatch.
4. Read current state without mutating it. Record sanitized evidence for the
   `dev.tollchat.ai`, apex `tollchat.ai`, and `www.tollchat.ai` records, including
   IDs, names, types, values, TTLs, and proxy flags. Record production CloudFront
   and ACM health as read-only evidence. The known rollback baseline is exactly
   one unproxied CNAME `dev.tollchat.ai` →
   `dmsiz11apblcv.cloudfront.net`; treat that value as a checked live input, not
   permission to touch any other record. Apex and `www` IDs/content are immutable
   checksums for the remainder of the handoff.

##### Certificate staging in the development account

1. From the development account, first confirm the caller is
   `903859731897`, the backend is `v2/infra/backend.development.hcl`, and the
   distribution is the exact `E33DVF3KT7BTAC`. Resolve the foundation output
   ephemerally as the existing delivery workflow does; never read production
   state. Keep the terminal non-traced (`set +x`) and use a private temporary
   directory for plans.
2. Run a targeted administrator apply with
   `enable_development_custom_domain=true` to request only the ACM certificate
   first. The certificate must be exactly `dev.tollchat.ai`, DNS validated, and
   in `us-east-1`; do not attach an alias before validation. A representative
   command is:

   ```sh
   set -euo pipefail
   set +x
   terraform -chdir=v2/infra init -input=false -backend-config=backend.development.hcl
   terraform -chdir=v2/infra apply -input=false \
     -var-file=development.tfvars \
     -var enable_development_custom_domain=true \
     -target=aws_acm_certificate.site[0] \
     -var-file=/private/reviewed/development-foundation.tfvars.json
   ```

   The target is a staging convenience only; review the complete follow-up
   plan. Do not apply if it proposes a production backend/account, Cloudflare
   data/resource, Route 53 object, or any production address. Capture only the
   non-secret outputs:

   ```sh
   set +x
   terraform -chdir=v2/infra output -json development_acm_certificate_arn
   terraform -chdir=v2/infra output -json development_acm_validation_records
   ```

   The output must contain exactly one certificate ARN for account
   `903859731897` in `us-east-1`, and exactly the current ACM DVO name/value for
   `dev.tollchat.ai`. Pass those records to the protected DNS workflow as JSON;
   do not copy a token or a plan/state object across accounts.
3. The certificate output is not an issuance proof. In the development account,
   poll the certificate with a bounded 10-minute wait (for example, 30 checks
   at 20-second intervals) and stop on any status other than `ISSUED`. The DNS
   workflow must first create/verify only the exact unproxied CNAME DVO records
   with type `CNAME` and TTL `60`. It resolves exactly one active `tollchat.ai`
   zone through the authenticated API, derives its account and zone IDs in
   memory, calls `GET /accounts/{derived_account_id}/tokens/verify`, and
   requires a successful active account-owned token. Zero, multiple, paginated,
   inactive, wrong-account, malformed, or API-error results stop before a write.

##### Exact DNS workflow operations and ordering

Dispatch `.github/workflows/v2-production-foundation-dns.yml` from protected
`main` with `operation=stage-validation`, the non-secret certificate ARN, the
JSON `development_acm_validation_records` value, distribution ID
`E33DVF3KT7BTAC`, deployed hostname `d1wqry4fbd92w5.cloudfront.net`, and the
captured old target/snapshot. The workflow rejects any record except exactly
one ACM-looking `_...dev.tollchat.ai` CNAME with the expected ACM
`_...acm-validations.aws` value, TTL `60`, and `proxied=false`. It refuses
duplicates, wrong type/content/TTL/proxy, arbitrary underscore names, wildcard,
apex, `www`, production names, and any broad reconciliation. Existing matching
records are left unchanged; a missing record is the only validation create.
All inputs and all current records are checked before the first write, and each
write re-verifies the token. The workflow uses only GET/POST/PUT; it has no
record deletion or proxy-mode path, and all API failures are sanitized.

After validation records are verified, wait for ACM `ISSUED` in the development
account. Then, as the development administrator, enable the switch for a normal
application plan and apply only after the issued certificate is confirmed. The
enabled plan must set the sole alias to `dev.tollchat.ai`, use that issued
certificate ARN with `sni-only` and `TLSv1.2_2021`, and make
`local.public_site_url`, `PUBLIC_ORIGINS`, and `PUBLIC_BASE_URL` exactly
`https://dev.tollchat.ai`. `public_preview_hostname` cannot override this URL.
Wait for the exact distribution to report `Deployed` with a bounded 30-minute
wait (30 checks at 60 seconds), and independently verify the alias is attached.
Do not dispatch the DNS cutover while the certificate is pending, the alias is
missing, the distribution is not deployed, or any value is uncertain.

Before `operation=cutover`, immediately re-read the dev record and compare it
to the supplied snapshot: one record ID, exact name/type, old content
`dmsiz11apblcv.cloudfront.net`, TTL `1`, and `proxied=false`. The workflow also
rechecks every validation record and requires operator evidence
`certificate_status=ISSUED`, `cloudfront_status=Deployed`, and
`alias_attached=true`. It then updates only the captured dev record ID to the
validated development hostname and verifies the same ID/content after the
write. It never touches apex, `www`, production CloudFront/ACM, the old
distribution `E1JXKQYNAN39E4`, or validation records. Allow up to 15 minutes
for DNS propagation before declaring the cutover healthy.

Run read-only smoke checks after propagation: HTTPS must present a certificate
for `dev.tollchat.ai`, the page and `/api/config` must return successfully, the
`X-Robots-Tag: noindex` header must remain, and the response/API identity must
be the development account/origin. Re-read apex and `www` and assert their
record IDs/content are byte-for-byte unchanged. Recheck production CloudFront
and ACM health and retain the sanitized before/after evidence with the commit,
workflow run, and operator identities.

##### Failed-cutover recovery and cleanup gate

Keep the old distribution, old certificate, and validation records throughout
the rollback window; #333 cleanup is not authorized by this procedure. If any
post-cutover smoke, certificate, deployment, or DNS check fails, dispatch the
same workflow with `operation=rollback` and the exact captured snapshot. It
must fail closed unless the current dev record still has the captured ID and
currently points to the staged development hostname. It then PUTs only that ID
back to the captured old content and verifies the old HTTPS endpoint is healthy.
Do not remove a validation record, alter apex/`www`, or use a generic record
delete. If alias removal is needed, a development administrator performs it
only after DNS rollback and health confirmation, using the development state.

Before authorizing #333 cleanup, prove a successful rollback against the
captured record in a disposable/reviewed gate, retain production no-change
evidence, and confirm that no workflow output, summary, artifact, cache, plan,
state, or log contains the Cloudflare token or Authorization header. A stale,
missing, ambiguous, or concurrently changed snapshot is a hard stop requiring
fresh read-only evidence; never guess at a replacement record.

~~~sh
(
set -euo pipefail
set +x
umask 077
ROOT="$(git rev-parse --show-toplevel)"
EXPECTED_ACCOUNT=903859731897
REGION=us-east-1
AWS_PROFILE=nova-toll-dev
: "$RELEASE_EVIDENCE"
case "$RELEASE_EVIDENCE" in /*) ;; *) exit 1 ;; esac
RELEASE_EVIDENCE="$(readlink -m -- "$RELEASE_EVIDENCE")"
case "$RELEASE_EVIDENCE" in "$ROOT"|"$ROOT"/*) exit 1 ;; esac
test ! -e "$RELEASE_EVIDENCE"
test "$(git -C "$ROOT" rev-parse --show-toplevel)" = "$ROOT"
git -C "$ROOT" diff --check
test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)"
for command_name in aws curl dig find git jq psql python3 rg sha256sum terraform unzip uv; do command -v "$command_name" >/dev/null; done
RELEASE_DIR="$(mktemp -d -t nova-toll-331-XXXXXX)"
FOUNDATION_TF_DATA_DIR="$RELEASE_DIR/foundation-tfdata"
APP_TF_DATA_DIR="$RELEASE_DIR/application-tfdata"
FOUNDATION_JSON="$RELEASE_DIR/foundation.json"
DEV_FOUNDATION_VARS="$RELEASE_DIR/foundation.tfvars.json"
PHASE_ONE_PLAN="$RELEASE_DIR/development-phase-one.tfplan"
PHASE_TWO_PLAN="$RELEASE_DIR/development-phase-two.tfplan"
PHASE_ONE_PLAN_JSON="$RELEASE_DIR/development-phase-one.tfplan.json"
PHASE_TWO_PLAN_JSON="$RELEASE_DIR/development-phase-two.tfplan.json"
PLAN_JSON=
CA_FILE="$RELEASE_DIR/global-bundle.pem"
IDENTITY_JSON="$RELEASE_DIR/identity.json"
RESET_BODY="$RELEASE_DIR/reset.json"
RESET_REQUEST="$RELEASE_DIR/reset-request.json"
LAMBDA_ACCOUNT_SETTINGS="$RELEASE_DIR/lambda-account-settings.json"
SECRET_ARN=
SECRET_JSON=
PGUSER=
PGPASSWORD=
cleanup() {
  unset PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE PGSSLMODE PGSSLROOTCERT
  unset SECRET_JSON SECRET_ARN RDS_METADATA DB_USER DB_PASSWORD DB_HOST DB_PORT
  rm -f -- "$FOUNDATION_JSON" "$DEV_FOUNDATION_VARS" "$PHASE_ONE_PLAN_JSON" "$PHASE_TWO_PLAN_JSON" "$CA_FILE" "$IDENTITY_JSON" "$RESET_BODY" "$RESET_REQUEST" "$LAMBDA_ACCOUNT_SETTINGS" "$PHASE_ONE_PLAN" "$PHASE_TWO_PLAN"
  rm -rf -- "$ROOT/v2/infra/build"
  rm -rf -- "$RELEASE_DIR"
}
trap cleanup EXIT
account() {
  AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json >"$IDENTITY_JSON"
  jq -e --arg account "$EXPECTED_ACCOUNT" 'select(.Account == $account)' "$IDENTITY_JSON" >/dev/null
}
aws_dev() {
  account
  AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" aws --region "$REGION" "$@"
}
tf_dev() {
  account
  AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" TF_DATA_DIR="$TF_DATA_DIR" terraform "$@"
}

export TF_DATA_DIR="$FOUNDATION_TF_DATA_DIR"
grep -F 'bucket       = "nova-toll-tfstate-903859731897"' "$ROOT/infra/backend.development.hcl" >/dev/null
grep -F 'key          = "nova-toll/development/terraform.tfstate"' "$ROOT/infra/backend.development.hcl" >/dev/null
grep -F 'kms_key_id   = "alias/nova-toll-tfstate"' "$ROOT/infra/backend.development.hcl" >/dev/null
tf_dev -chdir="$ROOT/infra" init -reconfigure -input=false -backend-config="$ROOT/infra/backend.development.hcl" >/dev/null
tf_dev -chdir="$ROOT/infra" output -json foundation >"$FOUNDATION_JSON"
jq -e 'def exact_keys($keys): type == "object" and ((keys_unsorted | sort) == ($keys | sort)); . as $foundation | exact_keys(["vpc_id", "vpc_cidr_block", "private_subnet_ids", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "db_instance", "alerts_topic_arn"]) and all(["vpc_id", "vpc_cidr_block", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "alerts_topic_arn"][]; $foundation[.] | type == "string" and length > 0) and ($foundation.private_subnet_ids | exact_keys(["a", "c"]) and all(.[]; type == "string" and length > 0)) and ($foundation.db_instance | exact_keys(["identifier", "resource_id", "address", "port"]) and all(["identifier", "resource_id", "address"][]; $foundation.db_instance[.] | type == "string" and length > 0) and (.port | type == "number"))' "$FOUNDATION_JSON" >/dev/null
if rg --fixed-strings --quiet '920534282028' "$FOUNDATION_JSON" || rg --ignore-case --quiet 'password|secret|ssm|terraform_remote_state' "$FOUNDATION_JSON"; then exit 1; fi
jq -n --argjson foundation "$(<"$FOUNDATION_JSON")" '{foundation: $foundation}' >"$DEV_FOUNDATION_VARS"
chmod 600 -- "$FOUNDATION_JSON" "$DEV_FOUNDATION_VARS"
DNS_BEFORE="$(dig +short dev.tollchat.ai CNAME | tr -d '\r')"
test "$DNS_BEFORE" = "dmsiz11apblcv.cloudfront.net."
cd "$ROOT/v2"
./scripts/build_loader_zip.sh >/dev/null
./scripts/build_publisher_zip.sh >/dev/null
./scripts/build_agentcore_zips.sh >/dev/null
for package in infra/build/loader.zip infra/build/publisher.zip infra/build/agentcore.zip infra/build/chat-proxy.zip; do test -s "$package"; ! unzip -Z1 "$package" | rg --line-regexp '(^|/)\.env$'; done
LOADER_SHA256="$(sha256sum infra/build/loader.zip | cut -d' ' -f1)"
PUBLISHER_SHA256="$(sha256sum infra/build/publisher.zip | cut -d' ' -f1)"
AGENTCORE_SHA256="$(sha256sum infra/build/agentcore.zip | cut -d' ' -f1)"
PROXY_SHA256="$(sha256sum infra/build/chat-proxy.zip | cut -d' ' -f1)"
ARTIFACT_SCAN_PATTERN='920534282028|nova-toll-prod|backend\.production\.hcl|terraform_remote_state|arn:aws:secretsmanager:|AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)[[:space:]]*[:=][[:space:]]*[^[:space:]}\"]{8,}|PGPASSWORD=|NOVA_TOLL_ADMIN_URL=|SECRET_(ARN|STRING)[[:space:]]*[:=][[:space:]]*[^[:space:]}\"]{8,}|\"(secret(_arn|string)?|password)\"[[:space:]]*[:=][[:space:]]*\"?[[:alnum:]/+=_-]{8,}'
PACKAGE_SCAN_PATTERN='920534282028|nova-toll-prod|backend\.production\.hcl|terraform_remote_state|PGPASSWORD=|NOVA_TOLL_ADMIN_URL=|SECRET_(ARN|STRING)[[:space:]]*[:=][[:space:]}\"]{8,}'
SSM_ARN_PATTERN='arn:aws:ssm:[[:alnum:]-]+:[0-9]{12}:parameter/[[:alnum:]_.:/=+-]+'
ALLOWED_SSM_REFERENCE='arn:aws:ssm:us-east-1:903859731897:parameter/nova-toll/openai_api_key'
scan_ssm_references() {
  local reference
  while IFS= read -r reference; do
    test "$reference" = "$ALLOWED_SSM_REFERENCE"
  done
}
scan_release_file() {
  local file="$1" references
  if rg --text --ignore-case --quiet -- "$ARTIFACT_SCAN_PATTERN" "$file"; then
    exit 1
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
  if references="$(rg --text --only-matching -- "$SSM_ARN_PATTERN" "$file")"; then
    scan_ssm_references <<<"$references"
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
}
scan_package() {
  local package="$1" references
  unzip -t "$package" >/dev/null
  if unzip -Z1 "$package" | rg --ignore-case --quiet '(^|/)\.env$'; then
    exit 1
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
  if unzip -p "$package" | rg --text --ignore-case --quiet -- "$PACKAGE_SCAN_PATTERN"; then
    exit 1
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
  if references="$(unzip -p "$package" | rg --text --only-matching -- "$SSM_ARN_PATTERN")"; then
    scan_ssm_references <<<"$references"
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
}
scan_release_directory() {
  while IFS= read -r -d '' file; do
    scan_release_file "$file"
  done < <(find "$RELEASE_DIR" -type f -print0)
}
for package in infra/build/loader.zip infra/build/publisher.zip infra/build/agentcore.zip infra/build/chat-proxy.zip; do
  scan_package "$package"
done

export TF_DATA_DIR="$APP_TF_DATA_DIR"
grep -F 'bucket       = "nova-toll-tfstate-903859731897"' infra/backend.development.hcl >/dev/null
grep -F 'key          = "nova-toll/v2/development/terraform.tfstate"' infra/backend.development.hcl >/dev/null
grep -F 'kms_key_id   = "alias/nova-toll-tfstate"' infra/backend.development.hcl >/dev/null
tf_dev -chdir="$ROOT/v2/infra" init -reconfigure -input=false -backend-config="$ROOT/v2/infra/backend.development.hcl" >/dev/null
plan_policy() {
  local plan="$1"
  local phase="${2:-}"
  if [ "$phase" = phase-two ]; then
    PLAN_JSON="$PHASE_TWO_PLAN_JSON"
  else
    PLAN_JSON="$PHASE_ONE_PLAN_JSON"
  fi
  tf_dev -chdir="$ROOT/v2/infra" show -json "$plan" >"$PLAN_JSON"
  if ! jq -e --arg allowlist "$DEVELOPMENT_RESOURCE_ALLOWLIST" --arg data_allowlist "$DEVELOPMENT_DATA_ALLOWLIST" --arg readonly "$DEVELOPMENT_READ_ONLY_ALLOWLIST" '
    def base: .address | split("[")[0];
    def listed($items): .address as $address | any(($items | split("\n") | map(select(length > 0)))[]; . as $item | $address == $item or ($address | startswith($item + "[")));
    def immutable: ((base == "aws_api_gateway_deployment.tollchat" and (.change.actions == ["create"] or .change.actions == ["delete"] or .change.actions == ["create", "delete"] or .change.actions == ["delete", "create"])) or (base == "aws_bedrock_guardrail_version.tollchat" and .change.actions == ["create"]));
    (.resource_changes | type == "array") and all(.resource_changes[];
      (.address | type == "string") and (.change.actions | type == "array" and length > 0) and (.deposed? == null) and (.previous_address? == null) and
      (.mode == "data" and listed($data_allowlist) and (.change.actions == ["read"] or .change.actions == ["no-op"]) or
       .mode == "managed" and listed($allowlist) and
       ((.change.actions == ["no-op"]) or
        (.change.actions == ["update"] and (listed($readonly) | not)) or immutable)))
  ' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if jq -r '.resource_changes[]? | [.address, (.change.after // {} | tostring)] | @json' "$PLAN_JSON" | rg --quiet '920534282028|dev.tollchat.ai' || jq -r '.resource_changes[]?.address' "$PLAN_JSON" | rg --ignore-case --quiet 'cloudflare|route53|terraform_remote_state'; then exit 1; fi
  if ! jq -e '
    def account_ok($value):
      (((($value | test("^arn:aws:[^:]*:[^:]*:[0-9]{12}:")) | not)
       or ($value | test("^arn:aws:[^:]*:[^:]*:903859731897:"))));
    def no_known_value($value):
      (["toll-v2-pricing-loader", "toll-v2-report-publisher", "tollchat-v2-chat-proxy", "tollchat-v2-usage-publisher", "tollchat-v2-agent-usage-rollup", "nova-toll-v2-chat-proxy", "nova-toll-v2-preview", "tollchat-v2-anonymous-sessions", "tollchat-v2-agentcore-runtime"] | any(.[]; . == $value) | not);
    def identifier_ok($value):
      (($value | test("(^|[/:\"])(nova_toll|pricing_loader_writer|pricing_reader|oracle_owner|tollchat_agent|pricing_caller|report_publisher)([/:\"]|$)"; "i")) | not);
    def app_name_ok($value):
      (($value | test("(^|[/:\"])(toll-v2-pricing-loader|toll-v2-report-publisher|tollchat-v2-chat-proxy|tollchat-v2-usage-publisher|tollchat-v2-agent-usage-rollup|nova-toll-v2-chat-proxy|nova-toll-v2-preview|tollchat-v2-anonymous-sessions|nova-toll-v2-agentcore-runtime)([/:\"]|$)"; "i")) | not);
    def suffix_ok($after):
      all(["function_name", "role", "role_arn", "table_name", "queue_name", "log_group_name", "alarm_name", "database_name", "workgroup_name"][];
        . as $key |
        ($after[$key] == null
          or ($after[$key] | type != "string")
          or (($after[$key] | test("(^|[/:-])(toll-v2|tollchat-v2|nova-toll-v2)"; "i")) | not)
          or ($after[$key] | test("-dev([/:]|$)|-development([/:]|$)|_development([/:]|$)"))
        )
      );
    def plan_strings($after):
      [$after | .. | strings] + [$after | .. | strings | try fromjson catch empty | .. | strings] | .[];
    def environment_ok($after):
      ([
        (($after.environment[]?.variables? // {}) | to_entries[]?),
        (($after.environment_variables // {}) | to_entries[]?)
      ] | all(.[]?;
        (.key as $key | .value as $value |
          (($key | test("^(DB_NAME|DB_USER|DB_READER_USER|PRICING_DB_USER|ATHENA_DATABASE|SESSION_TABLE_NAME|SITE_BUCKET_NAME|AGENT_MEASUREMENT_BUCKET)$")) | not)
          or ($value | type != "string")
          or ($value | test("-dev([/:]|$)|-development([/:]|$)|_development([/:]|$)"))
        )
      ));
    all(.resource_changes[] | select(.mode == "managed" and .change.after != null);
      .change.after as $after |
      (all(plan_strings($after); . as $value | account_ok($value) and no_known_value($value) and identifier_ok($value) and app_name_ok($value))
        and suffix_ok($after)
        and environment_ok($after))
    )
  ' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if ! jq -e '
    def managed_changes($address):
      [.resource_changes[]? | select(.mode == "managed" and .address == $address)] as $changes |
      if ($changes | length) == 1 then $changes[0] else false end;
    def reserved($address; $expected):
      managed_changes($address) as $resource |
      if ($resource | type) != "object" then false
      elif (($resource.change.after_unknown? // {}) | (.reserved_concurrent_executions? // false)) then false
      else ($resource.change.after | type == "object" and .reserved_concurrent_executions == $expected)
      end;
    def default_edge:
      managed_changes("aws_cloudfront_distribution.site") as $resource |
      if ($resource | type) != "object" then false
      else $resource.change.after as $after |
        if ($after | type) != "object" then false
        elif (($after.aliases | type) != "array" or ($after.aliases | length) != 0) then false
        elif (($after.viewer_certificate | type) != "array" or ($after.viewer_certificate | length) != 1) then false
        elif (($after.viewer_certificate[0] | type) != "object") then false
        else $after.viewer_certificate[0] as $certificate |
          ($certificate | has("acm_certificate_arn") and (.acm_certificate_arn == null or .acm_certificate_arn == "")
            and has("cloudfront_default_certificate") and .cloudfront_default_certificate == true
            and has("minimum_protocol_version") and .minimum_protocol_version == "TLSv1"
            and has("ssl_support_method") and (.ssl_support_method == null or .ssl_support_method == ""))
        end
      end;
    all(.resource_changes[]; (.change.actions | type == "array" and length > 0))
      and reserved("aws_lambda_function.loader"; 5)
      and reserved("aws_lambda_function.publisher"; 1)
      and reserved("aws_lambda_function.tollchat_proxy"; 5)
      and default_edge
  ' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if [ "$phase" = phase-two ]; then
    if ! jq -e 'all(.resource_changes[]; (.change.actions | type == "array" and length > 0) and (.mode == "data" or .change.actions == ["update"] or .change.actions == ["no-op"]))' "$PLAN_JSON" >/dev/null; then exit 1; fi
  fi
  sha256sum "$plan" | cut -d' ' -f1
}
PLAN_ARGS="-var-file=$ROOT/v2/infra/development.tfvars -var-file=$DEV_FOUNDATION_VARS -var loader_package_path=$ROOT/v2/infra/build/loader.zip -var publisher_package_path=$ROOT/v2/infra/build/publisher.zip -var agentcore_package_path=$ROOT/v2/infra/build/agentcore.zip -var chat_proxy_package_path=$ROOT/v2/infra/build/chat-proxy.zip"
read -r -d '' DEVELOPMENT_RESOURCE_ALLOWLIST <<'EOF' || true
aws_api_gateway_deployment.tollchat
aws_api_gateway_integration.tollchat_proxy
aws_api_gateway_integration.tollchat_root
aws_api_gateway_method.tollchat_proxy
aws_api_gateway_method.tollchat_root
aws_api_gateway_method_settings.tollchat
aws_api_gateway_resource.tollchat_proxy
aws_api_gateway_rest_api.tollchat
aws_api_gateway_rest_api_policy.tollchat
aws_api_gateway_stage.tollchat
aws_athena_named_query.recent_routes
aws_athena_named_query.top_routes
aws_athena_workgroup.agent_reports
aws_bedrock_guardrail.tollchat
aws_bedrock_guardrail_version.tollchat
aws_bedrockagentcore_agent_runtime.tollchat
aws_bedrockagentcore_agent_runtime_endpoint.tollchat
aws_bedrockagentcore_resource_policy.tollchat
aws_cloudfront_distribution.site
aws_cloudfront_function.public_chat_routes
aws_cloudfront_function.public_report_routes
aws_cloudfront_origin_access_control.public_chat
aws_cloudfront_origin_access_control.site
aws_cloudfront_response_headers_policy.development_noindex
aws_cloudwatch_event_rule.agent_usage_rollup
aws_cloudwatch_event_rule.raw_objects
aws_cloudwatch_event_rule.usage_publisher
aws_cloudwatch_event_target.agent_usage_rollup
aws_cloudwatch_event_target.loader
aws_cloudwatch_event_target.usage_publisher
aws_cloudwatch_log_group.agent_usage_rollup
aws_cloudwatch_log_group.agentcore_runtime
aws_cloudwatch_log_group.loader
aws_cloudwatch_log_group.publisher
aws_cloudwatch_log_group.tollchat_proxy
aws_cloudwatch_log_group.usage_publisher
aws_cloudwatch_log_metric_filter.load_success
aws_cloudwatch_log_metric_filter.proxy_failure
aws_cloudwatch_metric_alarm.agent_usage_log_coverage
aws_cloudwatch_metric_alarm.agent_usage_rollup_errors
aws_cloudwatch_metric_alarm.agent_usage_rollup_missing
aws_cloudwatch_metric_alarm.failure_queues
aws_cloudwatch_metric_alarm.freshness
aws_cloudwatch_metric_alarm.loader_errors
aws_cloudwatch_metric_alarm.publisher_errors
aws_cloudwatch_metric_alarm.publisher_failure_queues
aws_cloudwatch_metric_alarm.report_generation_freshness
aws_cloudwatch_metric_alarm.tollchat_proxy_errors
aws_cloudwatch_metric_alarm.tollchat_proxy_failures
aws_cloudwatch_metric_alarm.tollchat_proxy_latency
aws_cloudwatch_metric_alarm.tollchat_sessions
aws_cloudwatch_metric_alarm.usage_publisher_errors
aws_cloudwatch_metric_alarm.usage_publisher_failed_invocations
aws_dynamodb_table.tollchat_sessions
aws_glue_catalog_database.agent_reports
aws_glue_catalog_table.agent_registry
aws_glue_catalog_table.agent_report_generations
aws_glue_catalog_table.agent_report_rollup_completions
aws_glue_catalog_table.agent_report_rollups
aws_glue_catalog_table.waf_logs
aws_iam_role.agent_usage_rollup
aws_iam_role.loader
aws_iam_role.publisher
aws_iam_role.publisher_scheduler
aws_iam_role.timed_checks
aws_iam_role.tollchat_proxy
aws_iam_role.tollchat_runtime
aws_iam_role.usage_publisher
aws_iam_role_policy.agent_usage_rollup
aws_iam_role_policy.loader
aws_iam_role_policy.publisher
aws_iam_role_policy.publisher_scheduler
aws_iam_role_policy.timed_checks
aws_iam_role_policy.tollchat_proxy
aws_iam_role_policy.tollchat_runtime
aws_iam_role_policy.usage_publisher
aws_iam_role_policy_attachment.loader_vpc
aws_iam_role_policy_attachment.publisher_vpc
aws_iam_role_policy_attachment.tollchat_proxy_vpc
aws_kms_alias.agent_measurement
aws_kms_alias.site
aws_kms_key.agent_measurement
aws_kms_key.site
aws_lambda_alias.tollchat_live
aws_lambda_function.agent_usage_rollup
aws_lambda_function.loader
aws_lambda_function.publisher
aws_lambda_function.tollchat_proxy
aws_lambda_function.usage_publisher
aws_lambda_function_event_invoke_config.loader
aws_lambda_function_event_invoke_config.publisher
aws_lambda_function_url.public_chat
aws_lambda_permission.agent_usage_rollup
aws_lambda_permission.eventbridge_invoke
aws_lambda_permission.public_chat_invoke
aws_lambda_permission.public_chat_url
aws_lambda_permission.tollchat_api
aws_lambda_permission.usage_publisher
aws_lambda_provisioned_concurrency_config.tollchat
aws_s3_bucket.agent_measurement
aws_s3_bucket.site
aws_s3_bucket_lifecycle_configuration.agent_measurement
aws_s3_bucket_policy.agent_measurement
aws_s3_bucket_policy.site
aws_s3_bucket_public_access_block.agent_measurement
aws_s3_bucket_public_access_block.site
aws_s3_bucket_server_side_encryption_configuration.agent_measurement
aws_s3_bucket_server_side_encryption_configuration.site
aws_s3_object.agent_registry
aws_s3_object.agentcore
aws_s3_object.chat
aws_s3_object.faq
aws_s3_object.index
aws_s3_object.privacy
aws_s3_object.robots
aws_s3_object.site_assets
aws_s3_object.terms
aws_s3_object.tollchat_proxy
aws_s3_object.usage
aws_scheduler_schedule.publisher
aws_security_group.loader
aws_security_group.publisher
aws_security_group.tollchat_proxy
aws_security_group.tollchat_runtime
aws_sqs_queue.delivery_failure
aws_sqs_queue.invoke_failure
aws_sqs_queue.publisher_delivery_failure
aws_sqs_queue.publisher_invoke_failure
aws_sqs_queue_policy.delivery_failure
aws_vpc_security_group_egress_rule.loader_to_eventbridge
aws_vpc_security_group_egress_rule.loader_to_rds
aws_vpc_security_group_egress_rule.loader_to_s3
aws_vpc_security_group_egress_rule.proxy_https
aws_vpc_security_group_egress_rule.proxy_to_dynamodb
aws_vpc_security_group_egress_rule.publisher_to_rds
aws_vpc_security_group_egress_rule.publisher_to_s3
aws_vpc_security_group_egress_rule.runtime_https
aws_vpc_security_group_egress_rule.runtime_to_rds
aws_vpc_security_group_ingress_rule.agentcore_from_proxy
aws_vpc_security_group_ingress_rule.rds_from_loader
aws_vpc_security_group_ingress_rule.rds_from_publisher
aws_vpc_security_group_ingress_rule.rds_from_runtime
aws_wafv2_web_acl.public_chat
aws_wafv2_web_acl_logging_configuration.agent_reports
EOF
read -r -d '' DEVELOPMENT_DATA_ALLOWLIST <<'EOF' || true
data.archive_file.agent_usage_rollup
data.archive_file.placeholder
data.archive_file.usage_publisher
data.aws_caller_identity.current
data.aws_cloudfront_cache_policy.caching_disabled
data.aws_cloudfront_origin_request_policy.all_except_host
data.aws_iam_policy_document.agent_measurement_bucket
data.aws_iam_policy_document.agent_measurement_kms
data.aws_iam_policy_document.agent_usage_rollup
data.aws_iam_policy_document.agentcore_assume
data.aws_iam_policy_document.delivery_failure
data.aws_iam_policy_document.lambda_assume
data.aws_iam_policy_document.loader
data.aws_iam_policy_document.publisher
data.aws_iam_policy_document.publisher_scheduler
data.aws_iam_policy_document.publisher_scheduler_assume
data.aws_iam_policy_document.site_kms
data.aws_iam_policy_document.timed_checks
data.aws_iam_policy_document.timed_checks_assume
data.aws_iam_policy_document.tollchat_proxy
data.aws_iam_policy_document.tollchat_runtime
data.aws_iam_policy_document.usage_publisher
data.aws_prefix_list.dynamodb
data.aws_prefix_list.s3
data.aws_region.current
EOF
read -r -d '' DEVELOPMENT_READ_ONLY_ALLOWLIST <<'EOF' || true
aws_api_gateway_deployment.tollchat
aws_bedrock_guardrail_version.tollchat
aws_bedrock_guardrail.tollchat
aws_bedrockagentcore_resource_policy.tollchat
aws_cloudfront_distribution.site
aws_cloudfront_origin_access_control.public_chat
aws_cloudfront_origin_access_control.site
aws_cloudfront_response_headers_policy.development_noindex
aws_iam_role.agent_usage_rollup
aws_iam_role.loader
aws_iam_role.publisher
aws_iam_role.publisher_scheduler
aws_iam_role.timed_checks
aws_iam_role.tollchat_proxy
aws_iam_role.tollchat_runtime
aws_iam_role.usage_publisher
aws_iam_role_policy.agent_usage_rollup
aws_iam_role_policy.loader
aws_iam_role_policy.publisher
aws_iam_role_policy.publisher_scheduler
aws_iam_role_policy.timed_checks
aws_iam_role_policy.tollchat_proxy
aws_iam_role_policy.tollchat_runtime
aws_iam_role_policy.usage_publisher
aws_iam_role_policy_attachment.loader_vpc
aws_iam_role_policy_attachment.publisher_vpc
aws_iam_role_policy_attachment.tollchat_proxy_vpc
aws_kms_alias.agent_measurement
aws_kms_alias.site
aws_kms_key.agent_measurement
aws_kms_key.site
aws_lambda_function_url.public_chat
aws_lambda_permission.agent_usage_rollup
aws_lambda_permission.eventbridge_invoke
aws_lambda_permission.public_chat_invoke
aws_lambda_permission.public_chat_url
aws_lambda_permission.tollchat_api
aws_lambda_permission.usage_publisher
aws_s3_bucket.agent_measurement
aws_s3_bucket_lifecycle_configuration.agent_measurement
aws_s3_bucket_policy.agent_measurement
aws_s3_bucket_policy.site
aws_s3_bucket_public_access_block.agent_measurement
aws_s3_bucket_server_side_encryption_configuration.agent_measurement
EOF
source_tree_digest() {
  git -C "$ROOT" ls-files -z | while IFS= read -r -d '' path; do
    sha256sum "$ROOT/$path"
  done | sha256sum | cut -d' ' -f1
}
SOURCE_REVISION="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_TREE_SHA256="$(source_tree_digest)"
SOURCE_DIFF_SHA256="$(git -C "$ROOT" diff HEAD --no-ext-diff --binary -- . ':(exclude).graph' | sha256sum | cut -d' ' -f1)"
tf_dev -chdir="$ROOT/v2/infra" plan -input=false $PLAN_ARGS -var public_preview_hostname= -out="$PHASE_ONE_PLAN" >/dev/null
PHASE_ONE_PLAN_SHA256="$(plan_policy "$PHASE_ONE_PLAN")"
scan_release_file "$PHASE_ONE_PLAN"
scan_release_file "$PHASE_ONE_PLAN_JSON"
scan_release_directory
aws_dev lambda get-account-settings >"$LAMBDA_ACCOUNT_SETTINGS"
LAMBDA_QUOTA="$(aws_dev service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value' --output text)"
uv run --project "$ROOT/v2" python "$ROOT/v2/scripts/check_lambda_quota_gate.py" --account-settings "$LAMBDA_ACCOUNT_SETTINGS" --plan "$PHASE_ONE_PLAN_JSON" --quota "$LAMBDA_QUOTA" >/dev/null
tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_ONE_PLAN" >/dev/null
PUBLIC_SITE_JSON="$(tf_dev -chdir="$ROOT/v2/infra" output -json public_site)"
PREVIEW_HOST="$(jq -er '.hostname | select(test("^d[A-Za-z0-9]+[.]cloudfront[.]net$"))' <<<"$PUBLIC_SITE_JSON")"
PREVIEW_URL="https://$PREVIEW_HOST"
test "$(jq -r '.url' <<<"$PUBLIC_SITE_JSON")" = ""
tf_dev -chdir="$ROOT/v2/infra" plan -input=false $PLAN_ARGS -var "public_preview_hostname=$PREVIEW_HOST" -out="$PHASE_TWO_PLAN" >/dev/null
PHASE_TWO_PLAN_SHA256="$(plan_policy "$PHASE_TWO_PLAN" phase-two)"
scan_release_file "$PHASE_TWO_PLAN"
scan_release_file "$PHASE_TWO_PLAN_JSON"
scan_release_directory
aws_dev lambda get-account-settings >"$LAMBDA_ACCOUNT_SETTINGS"
LAMBDA_QUOTA="$(aws_dev service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value' --output text)"
uv run --project "$ROOT/v2" python "$ROOT/v2/scripts/check_lambda_quota_gate.py" --account-settings "$LAMBDA_ACCOUNT_SETTINGS" --plan "$PHASE_TWO_PLAN_JSON" --quota "$LAMBDA_QUOTA" >/dev/null
tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_TWO_PLAN" >/dev/null
PUBLIC_SITE_JSON="$(tf_dev -chdir="$ROOT/v2/infra" output -json public_site)"
test "$(jq -r '.url' <<<"$PUBLIC_SITE_JSON")" = "$PREVIEW_URL"
DIST_ID="$(jq -er '.distribution_id' <<<"$PUBLIC_SITE_JSON")"
aws_dev cloudfront wait distribution-deployed --id "$DIST_ID"
DIST_INFO="$(aws_dev cloudfront get-distribution --id "$DIST_ID" --query 'Distribution.{domain:DomainName,status:Status,aliases:DistributionConfig.Aliases.Items,default_certificate:DistributionConfig.ViewerCertificate.CloudFrontDefaultCertificate,minimum_protocol_version:DistributionConfig.ViewerCertificate.MinimumProtocolVersion}' --output json)"
jq -e --arg host "$PREVIEW_HOST" '(.domain == $host) and (.status == "Deployed") and ((.aliases // []) | length == 0) and (.default_certificate == true) and (.minimum_protocol_version == "TLSv1")' <<<"$DIST_INFO" >/dev/null
PUBLIC_ORIGINS="$(aws_dev lambda get-function-configuration --function-name tollchat-v2-chat-proxy-dev --query 'Environment.Variables.PUBLIC_ORIGINS' --output text)"
test "$PUBLIC_ORIGINS" = "$PREVIEW_URL"
PUBLIC_BASE_URL="$(aws_dev lambda get-function-configuration --function-name toll-v2-report-publisher-dev --query 'Environment.Variables.PUBLIC_BASE_URL' --output text)"
test "$PUBLIC_BASE_URL" = "$PREVIEW_URL"
assert_reserved_concurrency() {
  local function_name="$1" expected="$2"
  test "$(aws_dev lambda get-function-concurrency --function-name "$function_name" --query ReservedConcurrentExecutions --output text)" = "$expected"
}
assert_reserved_concurrency toll-v2-pricing-loader-dev 5
assert_reserved_concurrency toll-v2-report-publisher-dev 1
assert_reserved_concurrency tollchat-v2-chat-proxy-dev 5
FOUNDATION_DIGEST="$(sha256sum "$FOUNDATION_JSON" | cut -d' ' -f1)"
RDS_METADATA="$(aws_dev rds describe-db-instances --db-instance-identifier "$(jq -er '.db_instance.identifier' "$FOUNDATION_JSON")" --query 'DBInstances[0].{status:DBInstanceStatus,address:Endpoint.Address,port:Endpoint.Port,private:PubliclyAccessible,secret:MasterUserSecret.SecretArn}' --output json)"
DB_HOST="$(jq -er '.address' <<<"$RDS_METADATA")"
DB_PORT="$(jq -er '.port | tostring' <<<"$RDS_METADATA")"
jq -e --arg address "$(jq -er '.db_instance.address' "$FOUNDATION_JSON")" --argjson port "$(jq -er '.db_instance.port' "$FOUNDATION_JSON")" '(.status == "available") and (.private == false) and (.address == $address) and (.port == $port) and (.secret | type == "string" and length > 0)' <<<"$RDS_METADATA" >/dev/null
SECRET_ARN="$(jq -er '.secret' <<<"$RDS_METADATA")"
secret_json() {
  account
  SECRET_ARN="$SECRET_ARN" AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" \
    uv run --project "$ROOT/v2" python - <<'PY'
import boto3
import os

client = boto3.client("secretsmanager", region_name=os.environ["AWS_DEFAULT_REGION"])
print(client.get_secret_value(SecretId=os.environ["SECRET_ARN"])["SecretString"])
PY
}
SECRET_JSON="$(secret_json)"
jq -e 'type == "object" and (.username | type == "string" and length > 0) and (.password | type == "string" and length > 0)' <<<"$SECRET_JSON" >/dev/null
DB_USER="$(jq -er '.username' <<<"$SECRET_JSON")"
DB_PASSWORD="$(jq -er '.password' <<<"$SECRET_JSON")"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o "$CA_FILE"
echo 'e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3  '"$CA_FILE" | sha256sum --check --status
export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD" PGSSLMODE=verify-full PGSSLROOTCERT="$CA_FILE"
if [ -n "${NOVA_TOLL_RDS_LOCAL_PORT:-}" ]; then
  case "$NOVA_TOLL_RDS_LOCAL_PORT" in (*[!0-9]*|'') exit 1 ;; esac
  export PGHOSTADDR=127.0.0.1 PGPORT="$NOVA_TOLL_RDS_LOCAL_PORT"
fi
psql --dbname nova_toll_development --file "$ROOT/v2/tests/development_bootstrap_contract.sql" >/dev/null
for role in pricing_loader_writer pricing_reader tollchat_agent pricing_caller report_publisher; do
  psql --dbname postgres --tuples-only --no-align --command "SELECT has_database_privilege('$role', 'nova_toll', 'CONNECT') AND NOT has_database_privilege('$role', 'nova_toll_development', 'CONNECT');" | grep -qx t
done
for role in pricing_loader_writer_development pricing_reader_development tollchat_agent_development pricing_caller_development report_publisher_development; do
  psql --dbname postgres --tuples-only --no-align --command "SELECT has_database_privilege('$role', 'nova_toll_development', 'CONNECT') AND NOT has_database_privilege('$role', 'nova_toll', 'CONNECT');" | grep -qx t
done
for role in oracle_owner oracle_owner_development; do
  psql --dbname postgres --tuples-only --no-align --command "SELECT NOT rolcanlogin FROM pg_roles WHERE rolname = '$role';" | grep -qx t
done
DB_CONTRACT=pass
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$PREVIEW_URL/" -o /dev/null
printf '{}' >"$RESET_REQUEST"
RESET_BODY_SHA256="$(sha256sum "$RESET_REQUEST" | cut -d' ' -f1)"
RESET_CONTENT_TYPE="$(curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  --request POST "$PREVIEW_URL/api/reset" \
  --header "Origin: $PREVIEW_URL" \
  --header 'Content-Type: application/json' \
  --header 'Sec-Fetch-Site: same-origin' \
  --header "x-amz-content-sha256: $RESET_BODY_SHA256" \
  --data-binary "@$RESET_REQUEST" \
  --output "$RESET_BODY" \
  --write-out '%{content_type}')"
test "$RESET_CONTENT_TYPE" = "application/json"
jq -e '.ok == true' "$RESET_BODY" >/dev/null
DNS_AFTER="$(dig +short dev.tollchat.ai CNAME | tr -d '\r')"
test "$DNS_AFTER" = "$DNS_BEFORE"
RESOURCE_COUNT="$(tf_dev -chdir="$ROOT/v2/infra" state list | wc -l | tr -d ' ')"
RESOURCE_TYPES="$(tf_dev -chdir="$ROOT/v2/infra" state list | awk -F. '{print $1}' | sort -u | paste -sd, -)"
test -n "$RESOURCE_TYPES"
scan_release_directory
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SOURCE_REVISION"
test "$SOURCE_TREE_SHA256" = "$(source_tree_digest)"
test "$SOURCE_DIFF_SHA256" = "$(git -C "$ROOT" diff HEAD --no-ext-diff --binary -- . ':(exclude).graph' | sha256sum | cut -d' ' -f1)"
printf '%s\n' "account=$EXPECTED_ACCOUNT" "region=$REGION" "source_revision=$(git -C "$ROOT" rev-parse HEAD)" "source_tree_sha256=$SOURCE_TREE_SHA256" "source_diff_sha256=$SOURCE_DIFF_SHA256" "foundation_sha256=$FOUNDATION_DIGEST" "phase_one_plan_sha256=$PHASE_ONE_PLAN_SHA256" "phase_two_plan_sha256=$PHASE_TWO_PLAN_SHA256" "loader_sha256=$LOADER_SHA256" "publisher_sha256=$PUBLISHER_SHA256" "agentcore_sha256=$AGENTCORE_SHA256" "chat_proxy_sha256=$PROXY_SHA256" "plan_policy=pass" "lambda_quota=$LAMBDA_QUOTA" "lambda_reservations=5,1,5" "apply=pass" "database_bootstrap=not-run" "database_contract=$DB_CONTRACT" "resource_count=$RESOURCE_COUNT" "resource_inventory=$RESOURCE_TYPES" "preview_url=$PREVIEW_URL" "smoke=pass" "dns_before=$DNS_BEFORE" "dns_after=$DNS_AFTER" >"$RELEASE_EVIDENCE"
if rg --text --ignore-case --quiet 'password|secret_arn|secretstring|920534282028|dev.tollchat.ai|cloudflare|terraform\.tfstate|\.tfplan' "$RELEASE_EVIDENCE"; then
  exit 1
elif [ "$?" -ne 1 ]; then
  exit 1
fi
)
~~~

### Development handoff (non-operative)

After the #330 exact-plan handoff and state decision, pass only its reviewed
non-secret development context into the #331 application/database bootstrap.
That handoff is the retained plan root/path/digest and sanitized address/actions
summary, not the guarded production release's `production.tfvars` or foundation
output object. Do not use this runbook to reach the production-only Cloudflare
resources in `v2/infra/site.tf`; #332 owns the separately trusted development
DNS/certificate and CI cutover. Pull-request validation remains
credential-free, and account-local backend/configuration isolation remains
covered by the contract tests.

### Development foundation handoff (#330; no application release) [historical, superseded]

Issue #330 is a two-stage handoff. This stage only generates a complete
development-account foundation plan, retains the exact copied root and binary
plan for review, and stops; a later separately authorized stage may use that
same root and plan for the foundation apply without regenerating it. This
stage does not initialize a remote backend, mutate state, apply, import, or
release the development application. The foundation plan explicitly disables
Tailscale route advertisement until #330 provisions a non-overlapping VPC and
#332 supplies an environment-specific ACL identity.

The production Budget subscriber is read ephemerally for the approved #330
plan input. Because the Budget subscription is Terraform-managed, its value is
necessarily retained in the private reviewed plan and encrypted,
access-controlled Terraform state; that is the approved protected exception.
Never write it to repository source, checked-in tfvars, logs, raw review
output, or a typed handoff. The temporary recipient files are private and
removed on every exit. The retained root and exact plan remain private for
checker/security review; only their path, plan SHA-256, and sorted
address/actions summary are displayed.

```sh
(
set -euo pipefail
set +x
umask 077
ROOT="$(git rev-parse --show-toplevel)"
DEVELOPMENT_FOUNDATION_DIR=
DEVELOPMENT_FOUNDATION_PLAN=
DEVELOPMENT_BUDGET_RECIPIENTS=
DEVELOPMENT_BUDGET_SUBSCRIBERS=
cleanup() {
  status=$?
  for temporary in "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"; do
    test -z "$temporary" || rm -f -- "$temporary"
  done
  unset TF_VAR_budget_notification_email DEVELOPMENT_BUDGET_NOTIFICATIONS \
    DEVELOPMENT_BUDGET_NOTIFICATION_LINES DEVELOPMENT_FOUNDATION_SUMMARY \
    DEVELOPMENT_FOUNDATION_PLAN_SHA DEVELOPMENT_FETCHER_PACKAGE \
    DEVELOPMENT_FETCHER_PACKAGE_SHA DEVELOPMENT_FOUNDATION_VERSIONS notification
  if test "$status" -ne 0 && test -n "$DEVELOPMENT_FOUNDATION_DIR"; then
    printf 'Development foundation plan failed; retained root: %s\n' \
      "$DEVELOPMENT_FOUNDATION_DIR" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
DEVELOPMENT_FOUNDATION_DIR="$(mktemp -d)"
chmod 700 -- "$DEVELOPMENT_FOUNDATION_DIR"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_DIR")" = "700"
DEVELOPMENT_FOUNDATION_PLAN="$DEVELOPMENT_FOUNDATION_DIR/development-foundation.tfplan"
DEVELOPMENT_BUDGET_RECIPIENTS="$(mktemp)"
DEVELOPMENT_BUDGET_SUBSCRIBERS="$(mktemp)"
chmod 600 -- "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"
test "$(stat -c '%a' "$DEVELOPMENT_BUDGET_RECIPIENTS")" = "600"
test "$(stat -c '%a' "$DEVELOPMENT_BUDGET_SUBSCRIBERS")" = "600"
unset TF_VAR_budget_notification_email
test "$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "920534282028"
if ! DEVELOPMENT_BUDGET_NOTIFICATIONS="$(
  AWS_PROFILE=nova-toll-prod aws --region us-east-1 budgets \
    describe-notifications-for-budget --account-id 920534282028 \
    --budget-name nova-toll-monthly --output json 2>/dev/null
)"; then
  printf 'Production Budget notification read failed.\n' >&2
  exit 1
fi
DEVELOPMENT_BUDGET_NOTIFICATION_LINES="$(
  jq -ce '.Notifications | if type == "array" and length > 0 and all(.[]; type == "object") then .[] else error("invalid budget notifications") end' \
    <<<"$DEVELOPMENT_BUDGET_NOTIFICATIONS"
)"
export TF_VAR_budget_notification_email="$(
  if ! while IFS= read -r notification; do
    if ! AWS_PROFILE=nova-toll-prod aws --region us-east-1 budgets \
      describe-subscribers-for-notification --account-id 920534282028 \
      --budget-name nova-toll-monthly --notification "$notification" --output json \
      >"$DEVELOPMENT_BUDGET_SUBSCRIBERS" 2>/dev/null; then
      exit 1
    fi
    if ! jq -e '
      .Subscribers
      | type == "array"
        and all(.[]; type == "object"
          and (.SubscriptionType | type == "string")
          and (.Address | type == "string"))
    ' "$DEVELOPMENT_BUDGET_SUBSCRIBERS" >/dev/null; then
      exit 1
    fi
    if ! jq -r '.Subscribers[]? | select(.SubscriptionType == "EMAIL" and (.Address | type == "string")) | .Address' \
      "$DEVELOPMENT_BUDGET_SUBSCRIBERS" >>"$DEVELOPMENT_BUDGET_RECIPIENTS"; then
      exit 1
    fi
  done <<<"$DEVELOPMENT_BUDGET_NOTIFICATION_LINES"; then
    exit 1
  fi
  jq -R -s -er '
    split("\n") | map(select(length > 0)) | unique |
    if (length == 1 and (.[0] | type == "string" and length > 0 and test("^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$")))
    then .[0]
    else error("expected exactly one non-empty EMAIL subscriber")
    end
  ' "$DEVELOPMENT_BUDGET_RECIPIENTS"
)"
rm -f -- "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"
unset DEVELOPMENT_BUDGET_NOTIFICATIONS DEVELOPMENT_BUDGET_NOTIFICATION_LINES notification
test "$(AWS_PROFILE=nova-toll-dev aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
test -r "$ROOT/infra/build/fetcher.zip"
test -s "$ROOT/infra/build/fetcher.zip"
cp -a "$ROOT/infra/." "$DEVELOPMENT_FOUNDATION_DIR/"
chmod 700 -- "$DEVELOPMENT_FOUNDATION_DIR"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_DIR")" = "700"
chmod 600 -- "$DEVELOPMENT_FOUNDATION_DIR/build/fetcher.zip"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_DIR/build/fetcher.zip")" = "600"
DEVELOPMENT_FETCHER_PACKAGE="$DEVELOPMENT_FOUNDATION_DIR/build/fetcher.zip"
DEVELOPMENT_FOUNDATION_VERSIONS="$DEVELOPMENT_FOUNDATION_DIR/versions.tf.with-backend"
cp "$DEVELOPMENT_FOUNDATION_DIR/versions.tf" "$DEVELOPMENT_FOUNDATION_VERSIONS"
chmod 600 -- "$DEVELOPMENT_FOUNDATION_VERSIONS"
rm -rf -- "$DEVELOPMENT_FOUNDATION_DIR/.terraform" "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate.d"
rm -f -- "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate" "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate.backup"
DEVELOPMENT_TF_DATA_DIR="$DEVELOPMENT_FOUNDATION_DIR/.terraform-data"
mkdir -p "$DEVELOPMENT_TF_DATA_DIR"
export TF_DATA_DIR="$DEVELOPMENT_TF_DATA_DIR"
sed -i '/^[[:space:]]*backend "s3" {}/d' "$DEVELOPMENT_FOUNDATION_DIR/versions.tf"
test ! -e "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate"
test ! -e "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate.backup"
if ! AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" init -backend=false -input=false \
  >/dev/null 2>/dev/null; then
  printf 'Development foundation Terraform init failed.\n' >&2
  exit 1
fi
if ! AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" plan \
  -input=false -lock=false -var environment=development \
  -var tailscale_advertise_routes=false \
  -var fetcher_package_path="$DEVELOPMENT_FETCHER_PACKAGE" \
  -out="$DEVELOPMENT_FOUNDATION_PLAN" >/dev/null 2>/dev/null; then
  printf 'Development foundation Terraform plan failed.\n' >&2
  exit 1
fi
chmod 600 -- "$DEVELOPMENT_FOUNDATION_PLAN"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_PLAN")" = "600"
if ! AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" show -json "$DEVELOPMENT_FOUNDATION_PLAN" 2>/dev/null | jq -e '
  def foundation_create_addresses: [
    "aws_kms_key.raw",
    "aws_kms_alias.raw",
    "aws_kms_key.tfstate",
    "aws_kms_alias.tfstate",
    "aws_kms_key.audit",
    "aws_kms_alias.audit",
    "aws_kms_key.alerts",
    "aws_kms_alias.alerts",
    "aws_cloudwatch_event_rule.poll_tick",
    "aws_cloudwatch_event_target.fetcher",
    "aws_lambda_permission.eventbridge_invoke_fetcher",
    "aws_cloudwatch_event_rule.poll_tick_i66",
    "aws_cloudwatch_event_target.fetcher_i66",
    "aws_lambda_permission.eventbridge_invoke_fetcher_i66",
    "aws_s3_bucket_notification.raw",
    "aws_iam_role.fetcher",
    "aws_iam_role_policy_attachment.fetcher_basic",
    "aws_iam_role_policy.fetcher",
    "aws_iam_role.replay",
    "aws_iam_role_policy.replay",
    "aws_iam_openid_connect_provider.github",
    "aws_iam_role.tailscale_router",
    "aws_iam_role_policy.tailscale_router",
    "aws_iam_role_policy_attachment.tailscale_router_ssm",
    "aws_iam_instance_profile.tailscale_router",
    "aws_instance.tailscale_router",
    "aws_ssm_document.route_control[0]",
    "aws_iam_role.route_control[0]",
    "aws_iam_role_policy.route_control[0]",
    "aws_ssm_parameter.i95_token",
    "aws_ssm_parameter.i66_token",
    "aws_ssm_parameter.tailscale_authkey",
    "aws_s3_bucket.audit",
    "aws_s3_bucket_policy.audit",
    "aws_cloudtrail.audit",
    "aws_s3_bucket_versioning.hardened[\"raw\"]",
    "aws_s3_bucket_versioning.hardened[\"audit\"]",
    "aws_s3_bucket_versioning.hardened[\"tfstate\"]",
    "aws_s3_bucket_ownership_controls.hardened[\"raw\"]",
    "aws_s3_bucket_ownership_controls.hardened[\"audit\"]",
    "aws_s3_bucket_ownership_controls.hardened[\"tfstate\"]",
    "aws_s3_bucket_public_access_block.hardened[\"raw\"]",
    "aws_s3_bucket_public_access_block.hardened[\"audit\"]",
    "aws_s3_bucket_public_access_block.hardened[\"tfstate\"]",
    "aws_s3_bucket_server_side_encryption_configuration.hardened[\"raw\"]",
    "aws_s3_bucket_server_side_encryption_configuration.hardened[\"audit\"]",
    "aws_s3_bucket_server_side_encryption_configuration.hardened[\"tfstate\"]",
    "aws_s3_bucket_lifecycle_configuration.hardened[\"raw\"]",
    "aws_s3_bucket_lifecycle_configuration.hardened[\"audit\"]",
    "aws_s3_bucket_lifecycle_configuration.hardened[\"tfstate\"]",
    "aws_s3_bucket.raw",
    "aws_s3_bucket_policy.raw",
    "aws_s3_bucket.tfstate",
    "aws_s3_bucket_policy.tfstate",
    "aws_db_instance.main",
    "aws_subnet.tollchat_private_a",
    "aws_subnet.tollchat_private_c",
    "aws_eip.tollchat_nat",
    "aws_nat_gateway.tollchat",
    "aws_route_table.tollchat_private",
    "aws_route_table_association.tollchat_private[\"us_east_1a\"]",
    "aws_route_table_association.tollchat_private[\"us_east_1c\"]",
    "aws_security_group.tollchat_api_endpoint",
    "aws_vpc_security_group_ingress_rule.tollchat_api_from_tailscale",
    "aws_security_group.agentcore_endpoint",
    "aws_vpc_endpoint.agentcore",
    "aws_vpc_endpoint.tollchat_api",
    "aws_security_group.eventbridge_endpoint",
    "aws_vpc_security_group_ingress_rule.eventbridge_from_private[\"172.31.224.0/24\"]",
    "aws_vpc_security_group_ingress_rule.eventbridge_from_private[\"172.31.225.0/24\"]",
    "aws_vpc_endpoint.eventbridge",
    "aws_vpc_endpoint.dynamodb",
    "aws_s3_bucket.agentcore_artifacts",
    "aws_s3_bucket_public_access_block.agentcore_artifacts",
    "aws_s3_bucket_server_side_encryption_configuration.agentcore_artifacts",
    "aws_s3_bucket_versioning.agentcore_artifacts",
    "aws_s3_bucket_lifecycle_configuration.agentcore_artifacts",
    "aws_s3_bucket_policy.agentcore_artifacts",
    "aws_vpc_endpoint.s3",
    "aws_db_subnet_group.main",
    "aws_security_group.rds",
    "aws_security_group.tailscale_router",
    "aws_vpc_security_group_ingress_rule.rds_from_tailscale",
    "aws_vpc_security_group_egress_rule.tailscale_router_egress",
    "aws_cloudwatch_log_group.fetcher",
    "aws_lambda_function.fetcher",
    "aws_lambda_function_event_invoke_config.fetcher",
    "aws_sns_topic.alerts",
    "aws_sns_topic_subscription.alerts_email",
    "aws_cloudwatch_metric_alarm.fetcher_errors",
    "aws_cloudwatch_metric_alarm.bucket_storage[\"raw\"]",
    "aws_cloudwatch_metric_alarm.bucket_storage[\"tfstate\"]",
    "aws_cloudwatch_metric_alarm.rds_free_storage",
    "aws_cloudwatch_metric_alarm.rds_cpu",
    "aws_cloudwatch_metric_alarm.rds_free_memory",
    "aws_cloudwatch_metric_alarm.rds_connections",
    "aws_cloudwatch_metric_alarm.rds_cpu_credits",
    "aws_budgets_budget.nova_toll_monthly"
  ];
  def foundation_data_addresses: [
    "data.aws_caller_identity.current",
    "data.aws_region.current",
    "data.aws_vpc.default",
    "data.aws_subnets.default",
    "data.aws_route_tables.default",
    "data.aws_subnet.tailscale_router",
    "data.aws_iam_policy_document.route_control_assume[0]",
    "data.aws_iam_policy_document.route_control[0]"
  ];
  def expected_changes:
    ([foundation_create_addresses[] | {mode: "managed", address: ., actions: ["create"]}] +
     [foundation_data_addresses[] | {mode: "data", address: ., actions: ["read"]}])
    | sort_by([.mode, .address, (.actions | join(","))]);
  def actual_changes:
    if (.resource_changes | type) != "array" then error("invalid resource_changes")
    else [.resource_changes[] |
      if type != "object" or (.address | type) != "string" or (.change | type) != "object" or
        (.change.actions | type) != "array" or any(.change.actions[]; type != "string") then
        error("invalid resource change")
      else {mode, address, actions: .change.actions}
      end
    ] | sort_by([.mode, .address, (.actions | join(","))])
    end;
  actual_changes == expected_changes
' >/dev/null 2>/dev/null; then
  printf 'Development foundation plan scope gate failed.\n' >&2
  exit 1
fi
if ! DEVELOPMENT_FOUNDATION_SUMMARY="$(
  AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" show -json "$DEVELOPMENT_FOUNDATION_PLAN" 2>/dev/null |
    jq -ce '
      if (.resource_changes | type) != "array" then error("invalid resource_changes")
      else [.resource_changes[] |
        if (.address | type) != "string" or (.change | type) != "object" or (.change.actions | type) != "array" then
          error("invalid resource change")
        else {address: .address, actions: .change.actions}
        end
      ] | sort_by(.address)
      end
    ' 2>/dev/null
)"; then
  printf 'Development foundation plan summary failed.\n' >&2
  exit 1
fi
DEVELOPMENT_FOUNDATION_PLAN_SHA="$(sha256sum "$DEVELOPMENT_FOUNDATION_PLAN" | awk '{print $1}')"
printf 'Development foundation root: %s\n' "$DEVELOPMENT_FOUNDATION_DIR"
printf 'Development foundation plan SHA-256: %s\n' "$DEVELOPMENT_FOUNDATION_PLAN_SHA"
printf '%s\n' "$DEVELOPMENT_FOUNDATION_SUMMARY"
)
```

#### Later authorized exact-plan apply and recovery

After checker and security approval, a separately authorized operator may run
this complete #330 success path. It consumes only the retained root and binary
plan recorded in `.graph/change.md`; it never regenerates a plan, changes a
plan input, targets/imports a resource, or initializes a remote backend before
the local apply. Terraform/provider/AWS output is suppressed or reduced to
scalar predicates. A failure prints only its fixed stage category, preserves
the root and state, and stops without retry or cleanup.

##### Successful exact-plan apply, migration, and evidence

```sh
(
set -euo pipefail
set +x
umask 077
ROOT=/tmp/tmp.1nuZtAcl8L
PLAN="$ROOT/development-foundation.tfplan"
FETCHER="$ROOT/build/fetcher.zip"
REGION=us-east-1
DEV_ACCOUNT=903859731897
PROD_ACCOUNT=920534282028
EXPECTED_PLAN=0efda359505d7142a45792ec79e12d40d0540b7e3e961a7e04891328ca94e597
EXPECTED_FETCHER=9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1
EXPECTED_MANIFEST=d42489b4f0e971e6eeb06d0ba033b68584ab95ff19763a0e40724db657e8acc8
STATE_BUCKET=nova-toll-tfstate-903859731897
STATE_KEY=nova-toll/development/terraform.tfstate
failure_stage=preflight
fail() { exit 1; }
cleanup() {
  status=$?
  if test "$status" -ne 0; then
    printf 'Development foundation handoff failed at %s; retained root preserved.\n' "$failure_stage" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'failure_stage=interrupted; exit 130' HUP INT TERM
expect_absent_error() {
  local expected_error error_text return_code
  expected_error=$1
  shift
  set +e
  error_text="$("$@" 2>&1 >/dev/null)"
  return_code=$?
  set -e
  test "$return_code" -ne 0
  printf '%s' "$error_text" | grep -qiE "$expected_error"
}
absent_s3_bucket() { expect_absent_error '404|NoSuchBucket|Not Found' "$@"; }
absent_kms_key() { expect_absent_error 'NotFoundException' "$@"; }
absent_rds_instance() { expect_absent_error 'DBInstanceNotFound' "$@"; }
absent_lambda_function() { expect_absent_error 'ResourceNotFoundException' "$@"; }
absent_sns_topic() { expect_absent_error 'NotFound' "$@"; }
absent_cloudtrail() { expect_absent_error 'TrailNotFoundException' "$@"; }
absent_event_rule() { expect_absent_error 'ResourceNotFoundException' "$@"; }
absent_iam_role() { expect_absent_error 'NoSuchEntity' "$@"; }
absent_instance_profile() { expect_absent_error 'NoSuchEntity' "$@"; }
absent_rds_subnet_group() { expect_absent_error 'DBSubnetGroupNotFoundFault' "$@"; }
absent_oidc_provider() { expect_absent_error 'NoSuchEntity' "$@"; }
absent_budget() { expect_absent_error 'NotFoundException' "$@"; }
test "$(stat -c '%a' "$ROOT")" = 700
test "$(stat -c '%a' "$PLAN")" = 600
test "$(stat -c '%a' "$FETCHER")" = 600
test "$(sha256sum "$PLAN" | awk '{print $1}')" = "$EXPECTED_PLAN"
test "$(sha256sum "$FETCHER" | awk '{print $1}')" = "$EXPECTED_FETCHER"
test -d "$ROOT/.terraform-data"
test ! -e "$ROOT/terraform.tfstate"; test ! -e "$ROOT/terraform.tfstate.backup"; test ! -e "$ROOT/terraform.tfstate.d"
test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf" || true)" = 0
test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf.with-backend" || true)" = 1
manifest_digest() {
  (
    cd -- "$ROOT"
    {
      find . -maxdepth 1 -type f \( -name '*.tf' -o -name '*.tf.json' \) -printf '%P\0'
      find .terraform-data/providers -type f -perm /111 -name 'terraform-provider-*' -printf '.terraform-data/providers/%P\0'
      printf '%s\0' account-contract.json .terraform.lock.hcl lambda-stub/handler.py versions.tf.with-backend backend.development.hcl build/fetcher.zip @terraform-cli @terraform-version
    } | LC_ALL=C sort -z -u | while IFS= read -r -d '' rel; do
      case "$rel" in
        @terraform-cli) digest="$(sha256sum -- "$(readlink -f "$(command -v terraform)")" | awk '{print $1}')" ;;
        @terraform-version) digest="$(terraform version -json | jq -er '.terraform_version + "\t" + .platform')" ;;
        *) digest="$(sha256sum -- "$rel" | awk '{print $1}')" ;;
      esac
      test -n "$digest"; printf '%s\t%s\n' "$rel" "$digest"
    done
  ) | LC_ALL=C sha256sum | awk '{print $1}'
}
FIRST="$(manifest_digest)"; SECOND="$(manifest_digest)"; test "$FIRST" = "$SECOND"; test "$FIRST" = "$EXPECTED_MANIFEST"
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$DEV_ACCOUNT"
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text)" = "$REGION"
for bucket in nova-toll-tfstate-$DEV_ACCOUNT nova-toll-raw-$DEV_ACCOUNT nova-toll-audit-$DEV_ACCOUNT nova-toll-agentcore-$DEV_ACCOUNT; do absent_s3_bucket env AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-bucket --bucket "$bucket"; done
for alias in alias/nova-toll-raw alias/nova-toll-tfstate alias/nova-toll-audit alias/nova-toll-alerts; do absent_kms_key env AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id "$alias"; done
absent_rds_instance env AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-db-instances --db-instance-identifier nova-toll-db
absent_lambda_function env AWS_PROFILE=nova-toll-dev aws --region "$REGION" lambda get-function --function-name toll-fetcher
absent_sns_topic env AWS_PROFILE=nova-toll-dev aws --region "$REGION" sns get-topic-attributes --topic-arn "arn:aws:sns:$REGION:$DEV_ACCOUNT:nova-toll-alerts"
absent_cloudtrail env AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-trail --name nova-toll-audit
for rule in toll-poll-tick toll-poll-tick-i66; do absent_event_rule env AWS_PROFILE=nova-toll-dev aws --region "$REGION" events describe-rule --name "$rule"; done
for role in toll-fetcher toll-raw-replay nova-toll-tailscale-router; do absent_iam_role env AWS_PROFILE=nova-toll-dev aws iam get-role --role-name "$role"; done
absent_instance_profile env AWS_PROFILE=nova-toll-dev aws iam get-instance-profile --instance-profile-name nova-toll-tailscale-router
for parameter in /nova-toll/i95-token /nova-toll/i66-token /nova-toll/tailscale-authkey; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ssm describe-parameters --parameter-filters "Key=Name,Option=Equals,Values=$parameter" --query 'length(Parameters)' --output text)" = 0; done
VPC_ID="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"; test -n "$VPC_ID"; test "$VPC_ID" != None
absent_rds_subnet_group env AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-db-subnet-groups --db-subnet-group-name nova-toll-db
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" logs describe-log-groups --log-group-name-prefix /aws/lambda/toll-fetcher --query 'length(logGroups[?logGroupName==`/aws/lambda/toll-fetcher`])' --output text)" = 0
absent_oidc_provider env AWS_PROFILE=nova-toll-dev aws iam get-open-id-connect-provider --open-id-connect-provider-arn "arn:aws:iam::$DEV_ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
absent_budget env AWS_PROFILE=nova-toll-dev aws --region "$REGION" budgets describe-budget --account-id "$DEV_ACCOUNT" --budget-name nova-toll-monthly
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudwatch describe-alarms --alarm-names toll-fetcher-errors nova-toll-raw-storage-10gb nova-toll-tfstate-storage-10gb toll-rds-free-storage toll-rds-cpu toll-rds-free-memory toll-rds-connections toll-rds-cpu-credits --query 'length(MetricAlarms)' --output text)" = 0
for sg in nova-toll-rds nova-toll-tailscale-router nova-toll-preview-api-endpoint nova-toll-agentcore-endpoint nova-toll-eventbridge-endpoint; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC_ID" Name=group-name,Values="$sg" --query 'length(SecurityGroups)' --output text)" = 0; done
for service in bedrock-agentcore execute-api events dynamodb s3; do
  ENDPOINT_COUNT="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpc-endpoints --filters Name=vpc-id,Values="$VPC_ID" --query "length(VpcEndpoints[?contains(ServiceName, '$service')])" --output text)"
  test "$ENDPOINT_COUNT" = 0
done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-nat-gateways --filter Name=tag:Name,Values=nova-toll-preview --query 'length(NatGateways)' --output text)" = 0
for cidr in 172.31.224.0/24 172.31.225.0/24; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=cidr-block,Values="$cidr" --query 'length(Subnets)' --output text)" = 0; done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-instance-type-offerings --location-type availability-zone --filters Name=instance-type,Values=t4g.nano --query 'length(InstanceTypeOfferings)' --output text)" -ge 1
RDS_OPTIONS="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-orderable-db-instance-options --engine postgres --db-instance-class db.t4g.small --query 'length(OrderableDBInstanceOptions[?starts_with(EngineVersion, `17.`)])' --output text)"; test "$(printf '%s\n' "$RDS_OPTIONS" | awk '{sum += $1} END {print sum + 0}')" -ge 1
test "$(AWS_PROFILE=nova-toll-prod aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$PROD_ACCOUNT"
printf 'preflight=passed; manifest=%s; plan_sha=%s; fetcher_sha=%s; account=%s; region=%s\n' "$FIRST" "$EXPECTED_PLAN" "$EXPECTED_FETCHER" "$DEV_ACCOUNT" "$REGION"
failure_stage=apply
if ! TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" apply -input=false "$PLAN" >/dev/null 2>/dev/null; then fail; fi
failure_stage=local_state
chmod 600 -- "$ROOT/terraform.tfstate"
test "$(stat -c '%a' "$ROOT/terraform.tfstate")" = 600
STATE_LIST="$(TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" state list 2>/dev/null)"
test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | wc -l)" = 95
test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | sort | sha256sum | awk '{print $1}')" = b1d38c8b7e95452aa2fa069307a76e551ab59f4988e2f0a1af5be7824c037b57
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>/dev/null; echo $?)" = 0
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id alias/nova-toll-tfstate --query KeyMetadata.KeyState --output text)" = Enabled
failure_stage=migration_preflight
test "$(stat -c '%a' "$ROOT")" = 700; test "$(stat -c '%a' "$PLAN")" = 600; test "$(stat -c '%a' "$FETCHER")" = 600; test -d "$ROOT/.terraform-data"
test "$(sha256sum "$PLAN" | awk '{print $1}')" = "$EXPECTED_PLAN"; test "$(sha256sum "$FETCHER" | awk '{print $1}')" = "$EXPECTED_FETCHER"
test "$(manifest_digest)" = "$EXPECTED_MANIFEST"; test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf" || true)" = 0
state_object_absent() { local key error_text return_code; set +e; error_text="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$key" 2>&1 >/dev/null)"; return_code=$?; set -e; test "$return_code" -ne 0; printf '%s' "$error_text" | grep -qiE '404|Not Found|NoSuchKey'; }
state_object_absent "$STATE_KEY"; state_object_absent "$STATE_KEY.tflock"
cp -- "$ROOT/versions.tf.with-backend" "$ROOT/versions.tf"; chmod 600 -- "$ROOT/versions.tf"
test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf")" = 1
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$DEV_ACCOUNT"; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text)" = "$REGION"
test "$(sha256sum "$PLAN" | awk '{print $1}')" = "$EXPECTED_PLAN"; test "$(sha256sum "$FETCHER" | awk '{print $1}')" = "$EXPECTED_FETCHER"
failure_stage=migration
if ! TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" init -migrate-state -force-copy -input=false -backend-config="$ROOT/backend.development.hcl" >/dev/null 2>/dev/null; then fail; fi
failure_stage=postcheck
STATE_KMS_ARN="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id alias/nova-toll-tfstate --query KeyMetadata.Arn --output text)"
case "$STATE_KMS_ARN" in arn:aws:kms:$REGION:$DEV_ACCOUNT:key/????????-????-????-????-????????????) : ;; *) fail ;; esac
STATE_HEAD="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY" --query '{sse:ServerSideEncryption,kms:SSEKMSKeyId}' --output json)"; jq -e --arg arn "$STATE_KMS_ARN" '.sse == "aws:kms" and .kms == $arn' <<<"$STATE_HEAD" >/dev/null
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-versioning --bucket "$STATE_BUCKET" --query Status --output text)" = Enabled
PAB="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-public-access-block --bucket "$STATE_BUCKET" --query PublicAccessBlockConfiguration --output json)"; jq -e '(.BlockPublicAcls and .BlockPublicPolicy and .IgnorePublicAcls and .RestrictPublicBuckets)' <<<"$PAB" >/dev/null
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-ownership-controls --bucket "$STATE_BUCKET" --query 'OwnershipControls.Rules[0].ObjectOwnership' --output text)" = BucketOwnerEnforced
ENC="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-encryption --bucket "$STATE_BUCKET" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault' --output json)"; jq -e --arg arn "$STATE_KMS_ARN" '.SSEAlgorithm == "aws:kms" and .KMSMasterKeyID == $arn' <<<"$ENC" >/dev/null
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-policy-status --bucket "$STATE_BUCKET" --query PolicyStatus.IsPublic --output text)" = False
# Terraform 1.15.8 exposes no lock flags for state list; bound the read. The migration acquired/released the native lock; this proves no stale lockfile.
STATE_LIST="$(timeout 30s env TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" state list 2>/dev/null)"; test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | wc -l)" = 95; test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | sort | sha256sum | awk '{print $1}')" = b1d38c8b7e95452aa2fa069307a76e551ab59f4988e2f0a1af5be7824c037b57
if AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY.tflock" >/dev/null 2>/dev/null; then fail; fi
for bucket in "$STATE_BUCKET" nova-toll-raw-$DEV_ACCOUNT nova-toll-audit-$DEV_ACCOUNT nova-toll-agentcore-$DEV_ACCOUNT; do AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-bucket --bucket "$bucket" >/dev/null 2>/dev/null; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)" = Enabled; PAB="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-public-access-block --bucket "$bucket" --query PublicAccessBlockConfiguration --output json)"; jq -e '(.BlockPublicAcls and .BlockPublicPolicy and .IgnorePublicAcls and .RestrictPublicBuckets)' <<<"$PAB" >/dev/null; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-ownership-controls --bucket "$bucket" --query 'OwnershipControls.Rules[0].ObjectOwnership' --output text)" = BucketOwnerEnforced; done
for alias in alias/nova-toll-raw alias/nova-toll-tfstate alias/nova-toll-audit alias/nova-toll-alerts; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id "$alias" --query KeyMetadata.KeyState --output text)" = Enabled; done
ALIAS_COUNT="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms list-aliases --query "length(Aliases[?AliasName=='alias/nova-toll-raw' || AliasName=='alias/nova-toll-tfstate' || AliasName=='alias/nova-toll-audit' || AliasName=='alias/nova-toll-alerts'])" --output text)"; test "$ALIAS_COUNT" = 4
VPC_ID="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"; for cidr in 172.31.224.0/24 172.31.225.0/24; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=cidr-block,Values="$cidr" --query 'length(Subnets)' --output text)" = 1; done
for service in bedrock-agentcore execute-api events dynamodb s3; do
  ENDPOINT_COUNT="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpc-endpoints --filters Name=vpc-id,Values="$VPC_ID" --query "length(VpcEndpoints[?contains(ServiceName, '$service')])" --output text)"
  test "$ENDPOINT_COUNT" = 1
done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" lambda get-function --function-name toll-fetcher --query Configuration.FunctionName --output text)" = toll-fetcher
for role in toll-fetcher toll-raw-replay nova-toll-tailscale-router; do test "$(AWS_PROFILE=nova-toll-dev aws iam get-role --role-name "$role" --query 'Role.RoleName' --output text 2>/dev/null)" = "$role"; done
for rule in toll-poll-tick toll-poll-tick-i66; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" events describe-rule --name "$rule" --query State --output text)" = ENABLED; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" events list-targets-by-rule --rule "$rule" --query 'length(Targets)' --output text)" = 1; done
for attempt in $(seq 1 30); do status="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-db-instances --db-instance-identifier nova-toll-db --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || true)"; test "$status" = available && break; test "$attempt" -lt 30 || fail; sleep 10; done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-instances --filters Name=tag:Name,Values=nova-toll-tailscale-router Name=instance-state-name,Values=running --query 'length(Reservations[].Instances[])' --output text)" = 1
PROFILE_ROLES="$(AWS_PROFILE=nova-toll-dev aws iam get-instance-profile --instance-profile-name nova-toll-tailscale-router --query InstanceProfile.Roles --output json)"; test "$(jq 'length' <<<"$PROFILE_ROLES")" = 1
TOPIC_ARN="arn:aws:sns:$REGION:$DEV_ACCOUNT:nova-toll-alerts"; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" --query 'Subscriptions[].Protocol' --output text)" = email
BUDGET="$(AWS_PROFILE=nova-toll-dev aws budgets describe-budget --account-id "$DEV_ACCOUNT" --budget-name nova-toll-monthly --query '{name:Budget.BudgetName,amount:Budget.BudgetLimit.Amount,unit:Budget.BudgetLimit.Unit,time:Budget.TimeUnit}' --output json)"; jq -e '.name == "nova-toll-monthly" and (.amount | tonumber) == 100 and .unit == "USD" and .time == "MONTHLY"' <<<"$BUDGET" >/dev/null
NOTIFICATIONS="$(AWS_PROFILE=nova-toll-dev aws budgets describe-notifications-for-budget --account-id "$DEV_ACCOUNT" --budget-name nova-toll-monthly --query 'Notifications[].{Type:NotificationType,Threshold:Threshold}' --output json)"; jq -e 'length == 3 and (map({Type,Threshold}) | sort_by(.Type,.Threshold)) == [{Type:"ACTUAL",Threshold:80},{Type:"ACTUAL",Threshold:100},{Type:"FORECASTED",Threshold:80}]' <<<"$NOTIFICATIONS" >/dev/null
SSM_COUNT=0; for parameter in /nova-toll/i95-token /nova-toll/i66-token /nova-toll/tailscale-authkey; do name="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ssm describe-parameters --parameter-filters "Key=Name,Option=Equals,Values=$parameter" --query 'Parameters[0].Name' --output text 2>/dev/null || true)"; type="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ssm describe-parameters --parameter-filters "Key=Name,Option=Equals,Values=$parameter" --query 'Parameters[0].Type' --output text 2>/dev/null || true)"; test "$name" = "$parameter"; test "$type" = SecureString; SSM_COUNT=$((SSM_COUNT + 1)); done; test "$SSM_COUNT" = 3
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-trail-status --name nova-toll-audit --query IsLogging --output text 2>/dev/null || true)" = True
TRAIL="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-trail --name nova-toll-audit --query Trail --output json)"; AUDIT_KMS_ARN="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id alias/nova-toll-audit --query KeyMetadata.Arn --output text)"; jq -e --arg arn "$AUDIT_KMS_ARN" '.IsMultiRegionTrail and .IncludeGlobalServiceEvents and .LogFileValidationEnabled and .KmsKeyId == $arn' <<<"$TRAIL" >/dev/null
SELECTORS="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-event-selectors --trail-name nova-toll-audit --query AdvancedEventSelectors --output json)"; jq -e 'length == 2 and (map(.Name) | sort) == ["Management events","Protected S3 objects"] and (map(select(.Name == "Protected S3 objects"))[0] | tostring | contains("resources.ARN"))' <<<"$SELECTORS" >/dev/null
ALARMS="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudwatch describe-alarms --alarm-names toll-fetcher-errors nova-toll-raw-storage-10gb nova-toll-tfstate-storage-10gb toll-rds-free-storage toll-rds-cpu toll-rds-free-memory toll-rds-connections toll-rds-cpu-credits --query 'MetricAlarms[].{name:AlarmName,state:StateValue}' --output json)"; jq -e 'length == 8 and ([.[].name] | sort) == ["nova-toll-raw-storage-10gb","nova-toll-tfstate-storage-10gb","toll-fetcher-errors","toll-rds-connections","toll-rds-cpu","toll-rds-cpu-credits","toll-rds-free-memory","toll-rds-free-storage"] and all(.[]; (.state | type == "string"))' <<<"$ALARMS" >/dev/null
failure_stage=production_isolation
test "$(AWS_PROFILE=nova-toll-prod aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$PROD_ACCOUNT"
probe_denied() { local expected error_text return_code; expected=AccessDenied; test "$1" = s3api && expected='AccessDenied|403|Forbidden'; set +e; error_text="$(AWS_PROFILE=nova-toll-prod aws --region "$REGION" "$@" 2>&1 >/dev/null)"; return_code=$?; set -e; test "$return_code" -ne 0; if printf '%s' "$error_text" | grep -qiE "$expected"; then :; else fail; fi; }
probe_denied s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY"
probe_denied kms describe-key --key-id "$STATE_KMS_ARN"
trap - EXIT
printf 'state_bucket=%s; state_key=%s; state_kms_arn=%s; state_sse=aws:kms; state_versioning=Enabled; state_public_access_block=true; state_lockfile_absent=true; native_lock_migration=true; managed_state_count=95; managed_state_set=match; alias_count=4; bucket_count=4; network_endpoints=5; rds=available; fetcher=present; iam_roles=3; development_iam_roles_present=true; poll_rules=2; alert_email_subscriptions=1; budget_limit_usd=100; budget_notifications=3; ssm_securestring_metadata=3; cloudtrail_logging=true; cloudtrail_selectors=2; foundation_alarms=8; s3_denied=true; kms_denied=true\n' "$STATE_BUCKET" "$STATE_KEY" "$STATE_KMS_ARN"
)
```

If apply fails or is interrupted, do not restore the backend, migrate, retry,
delete, or replace the plan. Preserve the complete private root, retained
`.terraform-data`, local state/backups, binary plan, and fetcher. If migration
fails, preserve that post-restore root and all local/remote state evidence and
stop as well; only bounded read-only readiness retries in the success path are
permitted. The operator records only the fixed stage category, never an AWS or
Terraform error stream.

### Development foundation replacement handoff (#327/#333; source prerequisites)

The historical #330 foundation bootstrap text above is retained only for audit
context; use this authorized #327/#333 replacement handoff. Do not run the
historical procedure.

This is the source-only handoff for the authorized development RDS replacement.
It does not mutate AWS, Terraform state, Tailscale, GitHub, DNS, or PostgreSQL.
The later protected operator sequence below uses the exact development account,
backend, RDS identifier, canonical fetcher archive, and saved plan described here.
Production foundation protection and the existing route-control declarations remain
unchanged.

#### Fresh development database bootstrap

Terraform creates nova_toll_development as the initial database when the
development RDS instance is replaced. After the protected `pre-bootstrap`
route/transport phase passes and the instance is available, run the following
as a separate protected step. Set `NOVA_TOLL_RDS_LOCAL_PORT` only when using
an already-authorized local port forward; the bootstrap keeps the verified RDS
hostname in `PGHOST` and uses only `127.0.0.1` for transport in that mode:

~~~sh
set -euo pipefail
set +x
test "${AWS_PROFILE:-}" = "nova-toll-dev"
test "${AWS_REGION:-}" = "us-east-1"
test "${AWS_DEFAULT_REGION:-}" = "us-east-1"
test "$(AWS_PROFILE=nova-toll-dev aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
RDS_METADATA="$(AWS_PROFILE=nova-toll-dev aws --region us-east-1 rds describe-db-instances \
  --db-instance-identifier nova-toll-db \
  --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,endpoint:Endpoint.Address}' \
  --output json)"
jq -e 'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll_development" and .[0].private == false and .[0].deletion_protection == true and (.[0].endpoint | type == "string" and length > 0)' <<<"$RDS_METADATA" >/dev/null
RDS_ENDPOINT="$(jq -er '.[0].endpoint' <<<"$RDS_METADATA")"
: "${NOVA_TOLL_ADMIN_URL:?set the reviewed TLS administrator URL with explicit sslmode=verify-full and sslrootcert query settings in process memory only}"
export NOVA_TOLL_EXPECTED_RDS_ENDPOINT="$RDS_ENDPOINT"
python3 v2/scripts/bootstrap_development_database.py --fresh-development
unset NOVA_TOLL_ADMIN_URL NOVA_TOLL_EXPECTED_RDS_ENDPOINT NOVA_TOLL_RDS_LOCAL_PORT RDS_ENDPOINT RDS_METADATA
~~~

--fresh-development refuses a missing, wrong-name, commented, non-empty, or
ambiguous target before DDL. It loads only the rendered canonical
v2/db/schema.sql, v2/db/analysis.sql, v2/db/roles.sql,
v2/db/oracle/schema.sql, and v2/db/oracle/data.sql; it never connects to
or changes nova_toll, production roles, or v2/db/migrations/. Its
postcondition runs v2/tests/development_bootstrap_contract.sql in fresh mode,
proving versions, canonical row counts, development ownership/grants, no PUBLIC
CONNECT, and no foreign or integration objects. A failure removes only schemas,
roles, grants, and comments created by that invocation and stops if cleanup is
not proven.

#### Protected development replacement and foundation plan

Run this sequence only after this source change has been reviewed and merged to
protected main. It is a future live procedure; the builder does not run it.
Use no broad resource selector, -target, -auto-approve, secret retrieval,
or deployed migration.

The failed pre-replacement plan `8416e465447d00eb730ee0aa215dcd7f97d182b0357db04948f58a29b08786c7`
is permanently unusable. Before recovery source work, pin the development
profile/account/region, require the exact intact `nova-toll-db` to be available,
private, named `nova_toll`, and unprotected with no pending modification; run
`aws rds modify-db-instance --db-instance-identifier nova-toll-db --deletion-protection --apply-immediately`,
wait with `aws rds wait db-instance-available --db-instance-identifier nova-toll-db`,
then re-query and require the same properties with deletion protection `true`.
This safety restoration is not a replacement retry. Only a clean worktree at
the later reviewed recovery merge may render a new plan.

##### Phase 1: seed the destroy-time final snapshot identifier

The AWS provider reads `final_snapshot_identifier` from the prior RDS state
when it destroys a replacement. Before another replacement plan, seed that
attribute with a separate saved plan that cannot replace or rename the live
database. Run this only from the reviewed merge that adds the `state-seed`
validator mode. Keep deletion protection enabled throughout this phase.

Render the private phase-1 plan with a Terraform-native override that changes
only the development database name back to its current literal value. The
override is confined to the private plan root; ordinary development source
continues to select `nova_toll_development`, and production remains
`nova_toll`:

~~~sh
set -euo pipefail
set +x
umask 077
ROOT="$(git rev-parse --show-toplevel)"
export AWS_PROFILE=nova-toll-dev AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
TERRAFORM_BIN="$(command -v terraform)"
test -x "$TERRAFORM_BIN"
test "$(sha256sum "$TERRAFORM_BIN" | awk '{print $1}')" = "8b6cb96cd46080ee1287baf646c70078715a99123b9b3a6ce2a7fe3892ec703a"
test "$(terraform version -json | jq -r '.terraform_version')" = "1.15.8"
test "$(sha256sum "$ROOT/infra/.terraform.lock.hcl" | awk '{print $1}')" = "798415e2b72a761023f0ee096521a29223173428c99de7e4c50103e726eef4d8"
: "${REVIEWED_SOURCE_REVISION:?set the reviewed state-seed merge revision}"
test "$(git -C "$ROOT" rev-parse --verify HEAD)" = "$REVIEWED_SOURCE_REVISION"
test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all -- . ':(exclude).graph')"
RDS_INSTANCE_ARN="arn:aws:rds:us-east-1:903859731897:db:nova-toll-db"
RDS_RESOURCE_ID="db-DMHPVKTM5V5HN3QJG2UKFDEGTI"
RDS_METADATA="$(aws --region us-east-1 rds describe-db-instances \
  --db-instance-identifier nova-toll-db \
  --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,arn:DBInstanceArn,resource_id:DbiResourceId,endpoint:Endpoint.Address,pending:PendingModifiedValues}' \
  --output json)"
jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" \
  'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == true and .[0].arn == $arn and .[0].resource_id == $resource_id and (.[0].endpoint | type == "string" and length > 0) and (.[0].pending | type == "object" and length == 0)' <<<"$RDS_METADATA" >/dev/null
RDS_ENDPOINT="$(jq -er '.[0].endpoint' <<<"$RDS_METADATA")"
DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER="nova-toll-db-development-cutover-$(date -u +%Y%m%dt%H%M%Sz)"
printf '%s\n' "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" | grep -Eq '^[A-Za-z]([A-Za-z0-9-]*[A-Za-z0-9])?$'
test "${#DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER}" -le 255
case "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" in *--*) exit 1 ;; esac
MANUAL_SNAPSHOTS="$(aws --region us-east-1 rds describe-db-snapshots \
  --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier' --output json)"
jq -e --arg identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  '[.[] | select(. == $identifier)] | length == 0' <<<"$MANUAL_SNAPSHOTS" >/dev/null
"$ROOT/v2/scripts/build_fetcher_zip.sh" >/dev/null
test "$(sha256sum "$ROOT/infra/build/fetcher.zip" | awk '{print $1}')" = "9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"
STATE_SEED_ROOT="$(mktemp -d)"
chmod 700 -- "$STATE_SEED_ROOT"
cp -a "$ROOT/infra/." "$STATE_SEED_ROOT/"
chmod 700 -- "$STATE_SEED_ROOT"
cmp -s -- "$ROOT/infra/.terraform.lock.hcl" "$STATE_SEED_ROOT/.terraform.lock.hcl"
STATE_SEED_OVERRIDE="$STATE_SEED_ROOT/development-state-seed_override.tf"
printf '%s\n' 'resource "aws_db_instance" "main" {' '  db_name = "nova_toll"' '}' >"$STATE_SEED_OVERRIDE"
chmod 600 -- "$STATE_SEED_OVERRIDE"
test "$(sha256sum "$STATE_SEED_OVERRIDE" | awk '{print $1}')" = "83b2e8a3380f4a8063248207cf0a41f43b3a8ccb64076bc7852c25d30118bb84"
export TF_DATA_DIR="$STATE_SEED_ROOT/.terraform-data"
mkdir -p "$TF_DATA_DIR"
test "${DEVELOPMENT_BUDGET_EMAIL:?set the approved single budget recipient in process memory only}"
terraform -chdir="$STATE_SEED_ROOT" init -input=false \
  -backend-config="$ROOT/infra/backend.development.hcl" >/dev/null
cmp -s -- "$ROOT/infra/.terraform.lock.hcl" "$STATE_SEED_ROOT/.terraform.lock.hcl"
AWS_PROVIDER="$TF_DATA_DIR/providers/registry.terraform.io/hashicorp/aws/6.58.0/linux_amd64/terraform-provider-aws_v6.58.0_x5"
ARCHIVE_PROVIDER="$TF_DATA_DIR/providers/registry.terraform.io/hashicorp/archive/2.8.0/linux_amd64/terraform-provider-archive_v2.8.0_x5"
test -x "$AWS_PROVIDER" && test -x "$ARCHIVE_PROVIDER"
test "$(sha256sum "$AWS_PROVIDER" | awk '{print $1}')" = "b785b4ee3b3274867b54a336889aab8a3477f6d20cc3cc45105c940b4436b012"
test "$(sha256sum "$ARCHIVE_PROVIDER" | awk '{print $1}')" = "276b0d0b0fd0dbc3aab02006224b09c8edec889685167b1017fb05567c9e9318"
TF_VAR_budget_notification_email="$DEVELOPMENT_BUDGET_EMAIL" \
  terraform -chdir="$STATE_SEED_ROOT" plan -input=false -lock=false \
    -var environment=development -var tailscale_advertise_routes=false \
    -var development_final_snapshot_identifier="$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
    -var fetcher_package_path=build/fetcher.zip \
    -out="$STATE_SEED_ROOT/development-state-seed.tfplan" >/dev/null
chmod 600 -- "$STATE_SEED_ROOT/development-state-seed.tfplan"
terraform -chdir="$STATE_SEED_ROOT" show -json \
  "$STATE_SEED_ROOT/development-state-seed.tfplan" >"$STATE_SEED_ROOT/development-state-seed.tfplan.json"
chmod 600 -- "$STATE_SEED_ROOT/development-state-seed.tfplan.json"
STATE_SEED_PLAN_JSON_SHA256="$(sha256sum "$STATE_SEED_ROOT/development-state-seed.tfplan.json" | awk '{print $1}')"
python3 "$ROOT/v2/scripts/validate_development_foundation_plan.py" \
  "$STATE_SEED_ROOT/development-state-seed.tfplan.json" \
  --account 903859731897 --region us-east-1 \
  --backend "$ROOT/infra/backend.development.hcl" \
  --source-revision "$REVIEWED_SOURCE_REVISION" --source-root "$ROOT" \
  --final-snapshot-identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  --mode state-seed --rds-instance-arn "$RDS_INSTANCE_ARN" \
  --rds-resource-id "$RDS_RESOURCE_ID"
STATE_BEFORE_VALUES="$(jq -ceS '.prior_state.values' "$STATE_SEED_ROOT/development-state-seed.tfplan.json")"
jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" \
  '[.root_module.resources[] | select(.address == "aws_db_instance.main") | .values] | length == 1 and .[0].identifier == "nova-toll-db" and .[0].arn == $arn and .[0].resource_id == $resource_id and .[0].db_name == "nova_toll" and .[0].deletion_protection == true and .[0].publicly_accessible == false and .[0].final_snapshot_identifier == null and .[0].skip_final_snapshot == false' <<<"$STATE_BEFORE_VALUES" >/dev/null
STATE_BEFORE_NORMALIZED="$(jq -ceS '(.root_module.resources[] | select(.address == "aws_db_instance.main") | .values.final_snapshot_identifier) = null' <<<"$STATE_BEFORE_VALUES")"
STATE_BEFORE_NORMALIZED_SHA256="$(printf '%s' "$STATE_BEFORE_NORMALIZED" | sha256sum | awk '{print $1}')"
unset STATE_BEFORE_VALUES STATE_BEFORE_NORMALIZED
STATE_SEED_PLAN_SHA256="$(sha256sum "$STATE_SEED_ROOT/development-state-seed.tfplan" | awk '{print $1}')"
unset TF_VAR_budget_notification_email DEVELOPMENT_BUDGET_EMAIL
printf 'development state-seed root: %s\n' "$STATE_SEED_ROOT"
printf 'development state-seed plan SHA-256: %s\n' "$STATE_SEED_PLAN_SHA256"
printf 'development state-seed plan JSON SHA-256: %s\n' "$STATE_SEED_PLAN_JSON_SHA256"
printf 'development normalized pre-seed values SHA-256: %s\n' "$STATE_BEFORE_NORMALIZED_SHA256"
printf 'development final snapshot identifier: %s\n' "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER"
~~~

The validator accepts exactly 112 reviewed managed no-ops, the three exact
route-control payloads among those no-ops, zero or both reviewed policy-document
reads, and one `aws_db_instance.main` update. That update must have no
replacement path, keep the exact ARN/resource ID, remain private and protected,
keep `db_name=nova_toll`, and change only
`final_snapshot_identifier: null -> <the collision-checked identifier>`.

After independent review, apply only that phase-1 binary. Re-run every context,
identity, collision, digest, provider-directory, and validator guard first:

~~~sh
set -euo pipefail
set +x
: "${STATE_SEED_ROOT:?retain the reviewed private phase-1 root}"
: "${STATE_SEED_PLAN_SHA256:?retain the reviewed phase-1 plan digest}"
: "${STATE_SEED_PLAN_JSON_SHA256:?retain the reviewed phase-1 JSON digest}"
: "${STATE_BEFORE_NORMALIZED_SHA256:?retain the normalized pre-seed values digest}"
: "${DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER:?retain the phase-1 snapshot identifier}"
: "${REVIEWED_SOURCE_REVISION:?retain the reviewed state-seed merge revision}"
ROOT="$(git rev-parse --show-toplevel)"
export AWS_PROFILE=nova-toll-dev AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
export TF_DATA_DIR="$STATE_SEED_ROOT/.terraform-data"
test "$(stat -c '%a' -- "$STATE_SEED_ROOT")" = "700"
test -d "$TF_DATA_DIR/providers"
TERRAFORM_BIN="$(command -v terraform)"
test -x "$TERRAFORM_BIN"
test "$(sha256sum "$TERRAFORM_BIN" | awk '{print $1}')" = "8b6cb96cd46080ee1287baf646c70078715a99123b9b3a6ce2a7fe3892ec703a"
test "$(terraform version -json | jq -r '.terraform_version')" = "1.15.8"
test "$(sha256sum "$ROOT/infra/.terraform.lock.hcl" | awk '{print $1}')" = "798415e2b72a761023f0ee096521a29223173428c99de7e4c50103e726eef4d8"
cmp -s -- "$ROOT/infra/.terraform.lock.hcl" "$STATE_SEED_ROOT/.terraform.lock.hcl"
AWS_PROVIDER="$TF_DATA_DIR/providers/registry.terraform.io/hashicorp/aws/6.58.0/linux_amd64/terraform-provider-aws_v6.58.0_x5"
ARCHIVE_PROVIDER="$TF_DATA_DIR/providers/registry.terraform.io/hashicorp/archive/2.8.0/linux_amd64/terraform-provider-archive_v2.8.0_x5"
test -x "$AWS_PROVIDER" && test -x "$ARCHIVE_PROVIDER"
test "$(sha256sum "$AWS_PROVIDER" | awk '{print $1}')" = "b785b4ee3b3274867b54a336889aab8a3477f6d20cc3cc45105c940b4436b012"
test "$(sha256sum "$ARCHIVE_PROVIDER" | awk '{print $1}')" = "276b0d0b0fd0dbc3aab02006224b09c8edec889685167b1017fb05567c9e9318"
test "$(stat -c '%a' -- "$STATE_SEED_ROOT/development-state-seed.tfplan")" = "600"
test "$(sha256sum "$STATE_SEED_ROOT/development-state-seed.tfplan" | awk '{print $1}')" = "$STATE_SEED_PLAN_SHA256"
test "$(git -C "$ROOT" rev-parse --verify HEAD)" = "$REVIEWED_SOURCE_REVISION"
test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all -- . ':(exclude).graph')"
RDS_INSTANCE_ARN="arn:aws:rds:us-east-1:903859731897:db:nova-toll-db"
RDS_RESOURCE_ID="db-DMHPVKTM5V5HN3QJG2UKFDEGTI"
STATE_SEED_APPLY_STARTED=0
verify_state_seed_preboundary() {
  local status=$? protected
  trap - EXIT HUP INT TERM
  if test "$STATE_SEED_APPLY_STARTED" -eq 0; then
    protected="$(aws --region us-east-1 rds describe-db-instances \
      --db-instance-identifier nova-toll-db \
      --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,arn:DBInstanceArn,resource_id:DbiResourceId,pending:PendingModifiedValues}' \
      --output json)" || status=1
    jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" \
      'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == true and .[0].arn == $arn and .[0].resource_id == $resource_id and (.[0].pending | type == "object" and length == 0)' <<<"$protected" >/dev/null || status=1
  fi
  exit "$status"
}
trap verify_state_seed_preboundary EXIT HUP INT TERM
test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
MANUAL_SNAPSHOTS="$(aws --region us-east-1 rds describe-db-snapshots \
  --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier' --output json)"
jq -e --arg identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  '[.[] | select(. == $identifier)] | length == 0' <<<"$MANUAL_SNAPSHOTS" >/dev/null
RDS_PRE_SEED="$(aws --region us-east-1 rds describe-db-instances \
  --db-instance-identifier nova-toll-db \
  --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,arn:DBInstanceArn,resource_id:DbiResourceId,endpoint:Endpoint.Address,pending:PendingModifiedValues}' \
  --output json)"
jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" \
  'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == true and .[0].arn == $arn and .[0].resource_id == $resource_id and (.[0].endpoint | type == "string" and length > 0) and (.[0].pending | type == "object" and length == 0)' <<<"$RDS_PRE_SEED" >/dev/null
RDS_ENDPOINT="$(jq -er '.[0].endpoint' <<<"$RDS_PRE_SEED")"
STATE_SEED_APPLY_JSON="$(mktemp "$STATE_SEED_ROOT/development-state-seed.apply.XXXXXX.json")"
terraform -chdir="$STATE_SEED_ROOT" show -json \
  "$STATE_SEED_ROOT/development-state-seed.tfplan" >"$STATE_SEED_APPLY_JSON"
chmod 600 -- "$STATE_SEED_APPLY_JSON"
test "$(sha256sum "$STATE_SEED_APPLY_JSON" | awk '{print $1}')" = "$STATE_SEED_PLAN_JSON_SHA256"
python3 "$ROOT/v2/scripts/validate_development_foundation_plan.py" \
  "$STATE_SEED_APPLY_JSON" \
  --account 903859731897 --region us-east-1 \
  --backend "$ROOT/infra/backend.development.hcl" \
  --source-revision "$REVIEWED_SOURCE_REVISION" --source-root "$ROOT" \
  --final-snapshot-identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  --mode state-seed --rds-instance-arn "$RDS_INSTANCE_ARN" \
  --rds-resource-id "$RDS_RESOURCE_ID"
MANUAL_SNAPSHOTS="$(aws --region us-east-1 rds describe-db-snapshots \
  --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier' --output json)"
jq -e --arg identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  '[.[] | select(. == $identifier)] | length == 0' <<<"$MANUAL_SNAPSHOTS" >/dev/null
RDS_IMMEDIATE_PRE_SEED="$(aws --region us-east-1 rds describe-db-instances \
  --db-instance-identifier nova-toll-db \
  --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,arn:DBInstanceArn,resource_id:DbiResourceId,pending:PendingModifiedValues}' \
  --output json)"
jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" \
  'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == true and .[0].arn == $arn and .[0].resource_id == $resource_id and (.[0].pending | type == "object" and length == 0)' <<<"$RDS_IMMEDIATE_PRE_SEED" >/dev/null
test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
STATE_SEED_APPLY_STARTED=1
terraform -chdir="$STATE_SEED_ROOT" apply -input=false \
  "$STATE_SEED_ROOT/development-state-seed.tfplan" >/dev/null
aws --region us-east-1 rds wait db-instance-available --db-instance-identifier nova-toll-db
RDS_POST_SEED="$(aws --region us-east-1 rds describe-db-instances \
  --db-instance-identifier nova-toll-db \
  --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,arn:DBInstanceArn,resource_id:DbiResourceId,endpoint:Endpoint.Address,pending:PendingModifiedValues}' \
  --output json)"
jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" --arg endpoint "$RDS_ENDPOINT" \
  'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == true and .[0].arn == $arn and .[0].resource_id == $resource_id and .[0].endpoint == $endpoint and (.[0].pending | type == "object" and length == 0)' <<<"$RDS_POST_SEED" >/dev/null
MANUAL_SNAPSHOTS="$(aws --region us-east-1 rds describe-db-snapshots \
  --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier' --output json)"
jq -e --arg identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  '[.[] | select(. == $identifier)] | length == 0' <<<"$MANUAL_SNAPSHOTS" >/dev/null
STATE_AFTER="$(terraform -chdir="$STATE_SEED_ROOT" state pull)"
STATE_AFTER_SHA256="$(printf '%s' "$STATE_AFTER" | sha256sum | awk '{print $1}')"
jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" --arg snapshot "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  '[.resources[] | select(.module == null and .type == "aws_db_instance" and .name == "main") | .instances[].attributes] | length == 1 and .[0].identifier == "nova-toll-db" and .[0].arn == $arn and .[0].resource_id == $resource_id and .[0].db_name == "nova_toll" and .[0].deletion_protection == true and .[0].publicly_accessible == false and .[0].skip_final_snapshot == false and .[0].final_snapshot_identifier == $snapshot' <<<"$STATE_AFTER" >/dev/null
unset STATE_AFTER
STATE_AFTER_VALUES="$(terraform -chdir="$STATE_SEED_ROOT" show -json | jq -ceS '.values')"
jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" --arg snapshot "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
  '[.root_module.resources[] | select(.address == "aws_db_instance.main") | .values] | length == 1 and .[0].identifier == "nova-toll-db" and .[0].arn == $arn and .[0].resource_id == $resource_id and .[0].db_name == "nova_toll" and .[0].deletion_protection == true and .[0].publicly_accessible == false and .[0].skip_final_snapshot == false and .[0].final_snapshot_identifier == $snapshot' <<<"$STATE_AFTER_VALUES" >/dev/null
STATE_AFTER_NORMALIZED="$(jq -ceS '(.root_module.resources[] | select(.address == "aws_db_instance.main") | .values.final_snapshot_identifier) = null' <<<"$STATE_AFTER_VALUES")"
STATE_AFTER_NORMALIZED_SHA256="$(printf '%s' "$STATE_AFTER_NORMALIZED" | sha256sum | awk '{print $1}')"
test "$STATE_AFTER_NORMALIZED_SHA256" = "$STATE_BEFORE_NORMALIZED_SHA256"
unset STATE_AFTER_VALUES STATE_AFTER_NORMALIZED
mv -- "$STATE_SEED_ROOT/development-state-seed_override.tf" \
  "$STATE_SEED_ROOT/development-state-seed_override.tf.applied"
trap - EXIT HUP INT TERM
printf 'development post-seed state SHA-256: %s\n' "$STATE_AFTER_SHA256"
printf 'development normalized post-seed values SHA-256: %s\n' "$STATE_AFTER_NORMALIZED_SHA256"
~~~

A phase-1 failure is a hard stop with deletion protection still enabled. Do
not retry, edit state, create a fallback snapshot, or start the replacement.
Phase 2 must use a new private plan root copied from the clean merged source;
the `.applied` override evidence must not be copied or renamed back to `.tf`.
Recheck snapshot absence and render the ordinary `nova_toll_development`
replacement with the same identifier using the steps below.
The replacement validator rejects a plan unless its prior RDS state already
holds that same identifier.

1. Set the exact development identity and verify the exact target before any
   destructive operation:

   ~~~sh
   set -euo pipefail
   set +x
   ROOT="$(git rev-parse --show-toplevel)"
   export AWS_PROFILE=nova-toll-dev AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
   test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
   : "${REVIEWED_SOURCE_REVISION:?set the reviewed source revision}"
   printf '%s\n' "$REVIEWED_SOURCE_REVISION" | grep -Eq '^[0-9a-f]{40}$'
   test "$(git -C "$ROOT" rev-parse --verify HEAD)" = "$REVIEWED_SOURCE_REVISION"
   test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all -- . ':(exclude).graph')"
   RDS_METADATA="$(aws --region us-east-1 rds describe-db-instances \
     --db-instance-identifier nova-toll-db \
     --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible}' \
     --output json)"
   jq -e 'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == true' <<<"$RDS_METADATA" >/dev/null
   grep -Eq '^[[:space:]]*deletion_protection[[:space:]]*=[[:space:]]*true[[:space:]]*$' infra/rds.tf
   grep -Eq '^[[:space:]]*skip_final_snapshot[[:space:]]*=[[:space:]]*false[[:space:]]*$' infra/rds.tf
   : "${DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER:?retain the exact phase-1 snapshot identifier}"
   printf '%s\n' "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" | grep -Eq '^[A-Za-z]([A-Za-z0-9-]*[A-Za-z0-9])?$'
   test "${#DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER}" -le 255
   case "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" in *--*) exit 1 ;; esac
   MANUAL_SNAPSHOTS="$(aws --region us-east-1 rds describe-db-snapshots \
     --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier' --output json)"
   jq -e --arg identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
     '[.[] | select(. == $identifier)] | length == 0' <<<"$MANUAL_SNAPSHOTS" >/dev/null
   printf 'development final snapshot identifier: %s\n' "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER"
   ~~~

   This guard names only nova-toll-db in account 903859731897 and region
   us-east-1. A missing, duplicated, unavailable, public, or unprotected
   result is a hard stop. Production protection is not changed.

2. Disable deletion protection only on that exact development instance, then
   wait for it to become available again. Each later pre-apply shell keeps a
   matching trap: a plan, review, digest, identity, or context failure restores
   protection before it exits. Once the saved-plan apply begins, the trap is
   intentionally inert; there is no rollback rehearsal after that boundary.

   ~~~sh
   set -euo pipefail
   set +x
   export AWS_PROFILE=nova-toll-dev AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
   test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
   : "${DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER:?retain the collision-checked identifier from step 1}"
   RDS_METADATA="$(aws --region us-east-1 rds describe-db-instances \
     --db-instance-identifier nova-toll-db \
     --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible}' \
     --output json)"
   jq -e 'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == true' <<<"$RDS_METADATA" >/dev/null
   APPLY_STARTED=0
   DELETION_PROTECTION_DISABLED=1
   restore_deletion_protection() {
     local status=$?
     trap - EXIT HUP INT TERM
     if test "$APPLY_STARTED" -eq 0 && test "$DELETION_PROTECTION_DISABLED" -eq 1; then
       AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" aws --region us-east-1 rds modify-db-instance \
         --db-instance-identifier nova-toll-db --deletion-protection --apply-immediately >/dev/null || status=1
       AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" aws --region us-east-1 rds wait db-instance-available \
         --db-instance-identifier nova-toll-db || status=1
     fi
     exit "$status"
   }
   trap restore_deletion_protection EXIT HUP INT TERM
   AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" aws --region us-east-1 rds modify-db-instance \
     --db-instance-identifier nova-toll-db --no-deletion-protection --apply-immediately >/dev/null
   AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" aws --region us-east-1 rds wait db-instance-available \
     --db-instance-identifier nova-toll-db
   RDS_DISABLED_METADATA="$(aws --region us-east-1 rds describe-db-instances \
     --db-instance-identifier nova-toll-db \
     --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,arn:DBInstanceArn,resource_id:DbiResourceId,pending:PendingModifiedValues}' \
     --output json)"
   jq -e 'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == false and .[0].arn == "arn:aws:rds:us-east-1:903859731897:db:nova-toll-db" and (.[0].resource_id | type == "string" and length > 0) and (.[0].pending | type == "object" and length == 0)' <<<"$RDS_DISABLED_METADATA" >/dev/null
   RDS_INSTANCE_ARN="$(jq -er '.[0].arn' <<<"$RDS_DISABLED_METADATA")"
   RDS_RESOURCE_ID="$(jq -er '.[0].resource_id' <<<"$RDS_DISABLED_METADATA")"
   trap - EXIT HUP INT TERM
   ~~~

3. Render the private saved foundation plan from the retained root. Build the
   canonical archive at the reviewed relative path, assert its digest, and
   provide the approved single budget recipient only through process memory:

   ~~~sh
   set -euo pipefail
   set +x
   umask 077
   APPLY_STARTED=0
   DELETION_PROTECTION_DISABLED=1
   restore_deletion_protection() {
     local status=$?
     trap - EXIT HUP INT TERM
     if test "$APPLY_STARTED" -eq 0 && test "$DELETION_PROTECTION_DISABLED" -eq 1; then
       aws --region us-east-1 rds modify-db-instance \
         --db-instance-identifier nova-toll-db --deletion-protection --apply-immediately >/dev/null || status=1
       aws --region us-east-1 rds wait db-instance-available \
         --db-instance-identifier nova-toll-db || status=1
     fi
     unset TF_VAR_budget_notification_email DEVELOPMENT_BUDGET_EMAIL
     exit "$status"
   }
   trap restore_deletion_protection EXIT HUP INT TERM
   ROOT="$(git rev-parse --show-toplevel)"
   PLAN_ROOT="$(mktemp -d)"
   chmod 700 -- "$PLAN_ROOT"
   export AWS_PROFILE=nova-toll-dev AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
   test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
   : "${DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER:?retain the collision-checked identifier from step 1}"
   : "${RDS_INSTANCE_ARN:?retain the exact disabled-instance ARN from step 2}"
   : "${RDS_RESOURCE_ID:?retain the immutable disabled-instance resource ID from step 2}"
   : "${REVIEWED_SOURCE_REVISION:?set the reviewed source revision}"
   printf '%s\n' "$REVIEWED_SOURCE_REVISION" | grep -Eq '^[0-9a-f]{40}$'
   test "$(git -C "$ROOT" rev-parse --verify HEAD)" = "$REVIEWED_SOURCE_REVISION"
   test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all -- . ':(exclude).graph')"
   grep -Fx 'bucket       = "nova-toll-tfstate-903859731897"' "$ROOT/infra/backend.development.hcl"
   grep -Fx 'key          = "nova-toll/development/terraform.tfstate"' "$ROOT/infra/backend.development.hcl"
   grep -Fx 'region       = "us-east-1"' "$ROOT/infra/backend.development.hcl"
   grep -Fx 'kms_key_id   = "alias/nova-toll-tfstate"' "$ROOT/infra/backend.development.hcl"
   "$ROOT/v2/scripts/build_fetcher_zip.sh" >/dev/null
   test "$(sha256sum "$ROOT/infra/build/fetcher.zip" | awk '{print $1}')" = "9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"
   cp -a "$ROOT/infra/." "$PLAN_ROOT/"
   chmod 700 -- "$PLAN_ROOT"
   test -s "$PLAN_ROOT/build/fetcher.zip"
   chmod 600 -- "$PLAN_ROOT/build/fetcher.zip"
   export TF_DATA_DIR="$PLAN_ROOT/.terraform-data"
   mkdir -p "$TF_DATA_DIR"
   test "${DEVELOPMENT_BUDGET_EMAIL:?set the approved single budget recipient in process memory only}"
   terraform -chdir="$PLAN_ROOT" init -input=false \
     -backend-config="$ROOT/infra/backend.development.hcl" >/dev/null
   TF_VAR_budget_notification_email="$DEVELOPMENT_BUDGET_EMAIL" \
     terraform -chdir="$PLAN_ROOT" plan -input=false -lock=false \
       -var environment=development -var tailscale_advertise_routes=false \
       -var development_final_snapshot_identifier="$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
       -var fetcher_package_path=build/fetcher.zip \
       -out="$PLAN_ROOT/development-foundation.tfplan" >/dev/null
   chmod 600 -- "$PLAN_ROOT/development-foundation.tfplan"
   terraform -chdir="$PLAN_ROOT" show -json \
     "$PLAN_ROOT/development-foundation.tfplan" >"$PLAN_ROOT/development-foundation.tfplan.json"
   chmod 600 -- "$PLAN_ROOT/development-foundation.tfplan.json"
   python3 "$ROOT/v2/scripts/validate_development_foundation_plan.py" \
     "$PLAN_ROOT/development-foundation.tfplan.json" --account 903859731897 \
     --region us-east-1 --backend "$ROOT/infra/backend.development.hcl" \
     --source-revision "$REVIEWED_SOURCE_REVISION" --source-root "$ROOT" \
     --final-snapshot-identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER"
   trap - EXIT HUP INT TERM
   unset TF_VAR_budget_notification_email DEVELOPMENT_BUDGET_EMAIL
   printf 'development foundation plan retained at %s\n' "$PLAN_ROOT"
   ~~~

   The validator accepts exactly the development RDS delete,create
   replacement with replace_paths == [["db_name"]] and the exact runtime final
   snapshot identifier. The already state-managed
   aws_ssm_document.route_control[0], aws_iam_role.route_control[0],
   and aws_iam_role_policy.route_control[0] must be concrete, payload-validated
   no-ops. The plan must contain the validator's exact reviewed set of 112
   managed no-op addresses; count-preserving substitutions are rejected. It
   permits reads for the two route-control policy documents when Terraform
   emits them (fully known policy documents may be resolved during planning and omitted from
   `resource_changes`). Every other managed resource must be no-op; no other data
   action, unknown, moved, deposed, replacement, delete-only, update, budget,
   Lambda, production-account, or backend action is accepted. A rejected plan
   stops before apply. Keep the plan and root private for independent review.

4. Independently review the saved plan and apply only that exact binary plan.
   Restore deletion protection if any pre-apply review or identity check fails;
   once `APPLY_STARTED=1` is set, an apply failure is preserved without
   rollback or protection restoration.

   ~~~sh
   set -euo pipefail
   set +x
   APPLY_STARTED=0
   DELETION_PROTECTION_DISABLED=1
   restore_deletion_protection() {
     local status=$?
     trap - EXIT HUP INT TERM
     if test "$APPLY_STARTED" -eq 0 && test "$DELETION_PROTECTION_DISABLED" -eq 1; then
       aws --region us-east-1 rds modify-db-instance \
         --db-instance-identifier nova-toll-db --deletion-protection --apply-immediately >/dev/null || status=1
       aws --region us-east-1 rds wait db-instance-available \
         --db-instance-identifier nova-toll-db || status=1
     fi
     exit "$status"
   }
   trap restore_deletion_protection EXIT HUP INT TERM
   : "${PLAN_ROOT:?set PLAN_ROOT to the retained plan root from step 3}"
   export TF_DATA_DIR="$PLAN_ROOT/.terraform-data"
   test "$(stat -c '%a' -- "$PLAN_ROOT")" = "700"
   test -d "$TF_DATA_DIR"
   test -d "$TF_DATA_DIR/providers"
   : "${REVIEWED_PLAN_SHA256:?set the independently reviewed plan digest}"
   : "${DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER:?retain the collision-checked identifier from step 1}"
   printf '%s\n' "$REVIEWED_PLAN_SHA256" | grep -Eq '^[0-9a-f]{64}$'
   test "$(sha256sum "$PLAN_ROOT/development-foundation.tfplan" | awk '{print $1}')" = "$REVIEWED_PLAN_SHA256"
   export AWS_PROFILE=nova-toll-dev AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
   test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
   MANUAL_SNAPSHOTS="$(aws --region us-east-1 rds describe-db-snapshots \
     --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier' --output json)"
   jq -e --arg identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER" \
     '[.[] | select(. == $identifier)] | length == 0' <<<"$MANUAL_SNAPSHOTS" >/dev/null
   ROOT="$(git rev-parse --show-toplevel)"
   : "${REVIEWED_SOURCE_REVISION:?retain the reviewed recovery source revision}"
   python3 "$ROOT/v2/scripts/validate_development_foundation_plan.py" \
     "$PLAN_ROOT/development-foundation.tfplan.json" --account 903859731897 \
     --region us-east-1 --backend "$ROOT/infra/backend.development.hcl" \
     --source-revision "$REVIEWED_SOURCE_REVISION" --source-root "$ROOT" \
     --final-snapshot-identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER"
   : "${RDS_INSTANCE_ARN:?retain the exact disabled-instance ARN from step 2}"
   : "${RDS_RESOURCE_ID:?retain the immutable disabled-instance resource ID from step 2}"
   RDS_PRE_APPLY_METADATA="$(aws --region us-east-1 rds describe-db-instances \
     --db-instance-identifier nova-toll-db \
     --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].{identifier:DBInstanceIdentifier,status:DBInstanceStatus,db_name:DBName,deletion_protection:DeletionProtection,private:PubliclyAccessible,arn:DBInstanceArn,resource_id:DbiResourceId,pending:PendingModifiedValues}' \
     --output json)"
   jq -e --arg arn "$RDS_INSTANCE_ARN" --arg resource_id "$RDS_RESOURCE_ID" \
     'type == "array" and length == 1 and .[0].identifier == "nova-toll-db" and .[0].status == "available" and .[0].db_name == "nova_toll" and .[0].private == false and .[0].deletion_protection == false and .[0].arn == $arn and .[0].arn == "arn:aws:rds:us-east-1:903859731897:db:nova-toll-db" and .[0].resource_id == $resource_id and (.[0].pending | type == "object" and length == 0)' <<<"$RDS_PRE_APPLY_METADATA" >/dev/null
   test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
   APPLY_STARTED=1
   terraform -chdir="$PLAN_ROOT" apply -input=false \
     "$PLAN_ROOT/development-foundation.tfplan" >/dev/null
   aws --region us-east-1 rds wait db-instance-available --db-instance-identifier nova-toll-db
   trap - EXIT HUP INT TERM
   ~~~

5. After the replacement is available, resolve its private IPv4 again and
   derive the site-1 transport host. Do not use the saved pre-replacement
   address:

   ~~~sh
   RDS_ENDPOINT="$(aws --region us-east-1 rds describe-db-instances \
     --db-instance-identifier nova-toll-db \
     --query 'DBInstances[?DBInstanceIdentifier==`nova-toll-db`].Endpoint.Address' \
     --output text)"
   test -n "$RDS_ENDPOINT" && test "$RDS_ENDPOINT" != "None"
   DEV_IPV4="$(getent ahostsv4 "$RDS_ENDPOINT" | awk 'NR == 1 {print $1}')"
   test -n "$DEV_IPV4"
   tailscale debug via 1 "$DEV_IPV4/32"
   ~~~

   Use the resulting exact site-1 /128 to change only the value of
   hosts.nova-toll-rds-development in infra/policy.hujson. Review
   git diff -- infra/policy.hujson: the only semantic change must be that
   one host value; all development accept/deny tests, grants, tags, routes,
   production hosts, and production entries must be byte-for-byte unchanged.
   Merge this reviewed fixture update through the unchanged protected
   main-only .github/workflows/tailscale-acl.yml workflow. Do not edit ACL
   grants, tag ownership, routes, production hosts, DNS, router enrollment,
   VPC routes, security groups, or delivery settings.

6. Use the fixed-instance SSM route-control and protected connectivity workflow
   with `phase=pre-bootstrap` to establish and prove the private transport,
   then run the fresh bootstrap in its own protected step. Only after that
   bootstrap succeeds, dispatch the same workflow with `phase=full` and retain
   its development SQL identity and production-denial evidence. Keep
   `DEVELOPMENT_DELIVERY_ENABLED` absent or false until the full
   connectivity/bootstrap evidence is complete. The final sanitized evidence
   contains only the approved account/region, exact route ownership,
   development query identity, and both production denial booleans; it contains
   no secret, endpoint credential, raw command output, plan JSON, or state.

No rollback rehearsal or production migration is part of this handoff.
### Guarded production release

The production block independently creates and reviews its production-account
foundation plan before wrapping its planned output. It then uses
`backend.production.hcl`, `production.tfvars`,
`build/production-release.tfplan`, and `production_plan_sha`; repeat the STS
account check first and do not proceed if any development step failed.

```sh
(
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
PRODUCTION_FOUNDATION_PLAN="$(mktemp --suffix=.tfplan)"
PRODUCTION_FOUNDATION_VARS="$(mktemp --suffix=.tfvars.json)"
trap 'rm -f -- "$PRODUCTION_FOUNDATION_PLAN" "$PRODUCTION_FOUNDATION_VARS"' EXIT
test "$(AWS_PROFILE=nova-toll-prod aws sts get-caller-identity --query Account --output text)" = "920534282028"
: "${TF_VAR_budget_notification_email:?set the existing foundation budget notification input}"
# #332 must supply separately trusted Cloudflare credentials before any
# production DNS change; development DNS and certificate validation are gated
# out of the v2 Terraform path until that handoff.
AWS_PROFILE=nova-toll-prod terraform -chdir="$ROOT/infra" init -reconfigure -input=false \
  -backend-config="$ROOT/infra/backend.production.hcl"
rm -f -- "$PRODUCTION_FOUNDATION_PLAN"
AWS_PROFILE=nova-toll-prod terraform -chdir="$ROOT/infra" plan \
  -input=false -lock=false -var fetcher_package_path="$ROOT/infra/build/fetcher.zip" \
  -out="$PRODUCTION_FOUNDATION_PLAN"
AWS_PROFILE=nova-toll-prod terraform -chdir="$ROOT/infra" show -json "$PRODUCTION_FOUNDATION_PLAN" | jq -e '
  def foundation_data_addresses: [
    "data.aws_caller_identity.current", "data.aws_region.current",
    "data.aws_vpc.default", "data.aws_subnets.default",
    "data.aws_route_tables.default", "data.aws_iam_policy_document.agentcore_artifacts",
    "data.aws_iam_policy_document.raw_bucket", "data.aws_iam_policy_document.tfstate_bucket",
    "data.archive_file.placeholder", "data.aws_iam_policy_document.lambda_assume",
    "data.aws_iam_policy_document.fetcher", "data.aws_iam_policy_document.replay_assume",
    "data.aws_iam_policy_document.replay", "data.aws_iam_policy_document.audit_kms",
    "data.aws_iam_policy_document.alerts_kms", "data.aws_iam_policy_document.audit_bucket",
    "data.aws_prefix_list.s3", "data.aws_iam_policy_document.ec2_assume",
    "data.aws_iam_policy_document.tailscale_router", "data.aws_subnet.tailscale_router"
  ];
  def exact_keys($keys): type == "object" and ((keys_unsorted | sort) == ($keys | sort));
  def foundation_value_is_valid:
    try (
      . as $foundation |
      exact_keys(["vpc_id", "vpc_cidr_block", "private_subnet_ids", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "db_instance", "alerts_topic_arn"]) and
      all(["vpc_id", "vpc_cidr_block", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "alerts_topic_arn"][]; $foundation[.] | type == "string") and
      ($foundation.private_subnet_ids | exact_keys(["a", "c"])) and
      all(["a", "c"][]; $foundation.private_subnet_ids[.] | type == "string") and
      ($foundation.db_instance | exact_keys(["identifier", "resource_id", "address", "port"])) and
      all(["identifier", "resource_id", "address"][]; $foundation.db_instance[.] | type == "string") and
      ($foundation.db_instance.port | type == "number")
    ) catch false;
  (.resource_changes | type == "array") and
  all(.resource_changes[];
    type == "object" and
    (.address | type == "string" and length > 0) and
    (.mode | type == "string") and
    (.change | type == "object") and
    (.change.actions | type == "array") and
    (.address as $address |
      ((.mode == "managed" and .change.actions == ["no-op"]) or
       (.mode == "data" and (foundation_data_addresses | index($address)) != null and .change.actions == ["read"])))
  ) and
  (.planned_values.outputs.foundation.value | foundation_value_is_valid)
' >/dev/null
production_foundation_json="$(AWS_PROFILE=nova-toll-prod terraform -chdir="$ROOT/infra" show -json "$PRODUCTION_FOUNDATION_PLAN" | jq -er '
  def exact_keys($keys): type == "object" and ((keys_unsorted | sort) == ($keys | sort));
  def foundation_value_is_valid:
    try (
      . as $foundation |
      exact_keys(["vpc_id", "vpc_cidr_block", "private_subnet_ids", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "db_instance", "alerts_topic_arn"]) and
      all(["vpc_id", "vpc_cidr_block", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "alerts_topic_arn"][]; $foundation[.] | type == "string") and
      ($foundation.private_subnet_ids | exact_keys(["a", "c"])) and
      all(["a", "c"][]; $foundation.private_subnet_ids[.] | type == "string") and
      ($foundation.db_instance | exact_keys(["identifier", "resource_id", "address", "port"])) and
      all(["identifier", "resource_id", "address"][]; $foundation.db_instance[.] | type == "string") and
      ($foundation.db_instance.port | type == "number")
    ) catch false;
  .planned_values.outputs.foundation.value | select(foundation_value_is_valid)
')"
rm -f -- "$PRODUCTION_FOUNDATION_PLAN"
jq -n --argjson foundation "$production_foundation_json" '{"foundation": $foundation}' >"$PRODUCTION_FOUNDATION_VARS"
jq -e 'has("foundation") and (.foundation | type == "object")' "$PRODUCTION_FOUNDATION_VARS" >/dev/null
jq . "$PRODUCTION_FOUNDATION_VARS"  # review the production-account object
cd "$ROOT/v2/infra"
AWS_PROFILE=nova-toll-prod terraform init -reconfigure -input=false -backend-config=backend.production.hcl
AWS_PROFILE=nova-toll-prod terraform plan -input=false -lock=false -var-file=production.tfvars -var-file="$PRODUCTION_FOUNDATION_VARS" -var loader_package_path=build/loader.zip -var publisher_package_path=build/publisher.zip -var agentcore_package_path=build/agentcore.zip -var chat_proxy_package_path=build/chat-proxy.zip -out=build/production-release.tfplan
production_plan_sha="$(sha256sum build/production-release.tfplan | awk '{print $1}')"
AWS_PROFILE=nova-toll-prod terraform show -json build/production-release.tfplan | jq -e '
  def valid: (.resource_changes | type == "array") and all(.resource_changes[]; type == "object" and (.mode | type == "string") and (.address | type == "string") and (.change | type == "object") and (.change.actions | type == "array") and all(.change.actions[]; type == "string"));
  def creates: ["aws_iam_role.publisher_scheduler", "aws_iam_role_policy.publisher_scheduler", "aws_scheduler_schedule.publisher"]; def updates: ["aws_bedrockagentcore_agent_runtime.tollchat", "aws_bedrockagentcore_agent_runtime_endpoint.tollchat", "aws_cloudwatch_metric_alarm.report_generation_freshness", "aws_iam_role_policy.publisher", "aws_iam_role_policy.tollchat_proxy", "aws_iam_role_policy.tollchat_runtime", "aws_lambda_function.publisher", "aws_s3_object.agentcore", "aws_s3_object.usage"]; def deletes: ["aws_cloudwatch_event_rule.committed_i95_loads", "aws_cloudwatch_event_rule.report_watchdog", "aws_cloudwatch_event_target.publisher_load_event", "aws_cloudwatch_event_target.publisher_watchdog", "aws_cloudwatch_metric_alarm.publisher_failed_invocations[\"load_success\"]", "aws_cloudwatch_metric_alarm.publisher_failed_invocations[\"watchdog\"]", "aws_lambda_permission.publisher_load_event", "aws_lambda_permission.publisher_watchdog", "aws_sqs_queue_policy.publisher_delivery_failure"]; def reads: ["data.aws_iam_policy_document.publisher_scheduler", "data.aws_iam_policy_document.tollchat_proxy", "data.aws_iam_policy_document.tollchat_runtime"];
  def approved: .address as $a | ((.mode == "managed" and (((creates | index($a)) != null and .change.actions == ["create"]) or ((updates | index($a)) != null and .change.actions == ["update"]) or ((deletes | index($a)) != null and .change.actions == ["delete"]))) or (.mode == "data" and ((reads | index($a)) != null) and .change.actions == ["read"]));
  valid and all(.resource_changes[]; if .change.actions == ["no-op"] then true else approved end)'
AWS_PROFILE=nova-toll-prod terraform show build/production-release.tfplan
test "$(sha256sum build/production-release.tfplan | awk '{print $1}')" = "$production_plan_sha"
AWS_PROFILE=nova-toll-prod terraform apply -input=false build/production-release.tfplan
test "$(sha256sum build/production-release.tfplan | awk '{print $1}')" = "$production_plan_sha"
rm -f -- "$PRODUCTION_FOUNDATION_VARS"
trap - EXIT
)
```

The legacy development inventory is historical read-only cleanup context for
#333. Development account ownership and account-local backends are current;
this issue does not perform the cleanup or any deployed migration.

## Public report launch (production only)

The report publisher depends on the CloudFront distribution and `robots.txt`,
so enabling publication in the complete saved plan happens only after the edge
rewrite has deployed. Wait for the distribution, enqueue one watchdog run, and
verify the complete manifest before testing public URLs. Run this section only
after the production guarded release; never run it while the development
backend is selected. Development public report publication, Cloudflare, and DNS
remain deferred to #332.

```sh
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT/v2/infra"
test "$(AWS_PROFILE=nova-toll-prod aws sts get-caller-identity --query Account --output text)" = "920534282028"
AWS_PROFILE=nova-toll-prod terraform init -reconfigure -input=false -backend-config=backend.production.hcl
PUBLISHER_FUNCTION="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_lambda_function.publisher | awk -F' = ' '$1 ~ /^    function_name/ {gsub(/"/, "", $2); print $2; exit}')"
PUBLISHER_LOG_GROUP="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_cloudwatch_log_group.publisher | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_DISTRIBUTION="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.distribution_id | select(type == "string")')"
SITE_URL="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.url | select(type == "string")')"
SITE_BUCKET="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
test "$PUBLISHER_FUNCTION" = "toll-v2-report-publisher"
test "$PUBLISHER_LOG_GROUP" = "/aws/lambda/toll-v2-report-publisher"
test "$SITE_BUCKET" = "tollchat-site-920534282028"
test -n "$SITE_DISTRIBUTION"
[[ "$SITE_DISTRIBUTION" =~ ^[A-Z0-9]+$ ]]
test "$SITE_URL" = "https://tollchat.ai"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 cloudfront wait distribution-deployed \
  --id "$SITE_DISTRIBUTION"
REPORT_INVOKE="$(mktemp)"
REPORT_MANIFEST="$(mktemp)"
trap 'rm -f -- "$REPORT_INVOKE" "$REPORT_MANIFEST"' EXIT
REPORT_SMOKE_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
REPORT_STARTED_MS="$(date +%s%3N)"
report_smoke_succeeded() {
  local smoke_pattern='V2_REPORT_SMOKE_OK '"$REPORT_SMOKE_ID"' (published|unchanged) ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z) [a-f0-9]{64}[[:space:]]*$'
  while IFS=$'\t' read -r event_time event_message; do
    if [[ "$event_time" =~ ^[0-9]+$ ]] && (( event_time >= REPORT_STARTED_MS )) && \
      [[ "$event_message" =~ $smoke_pattern ]] && \
      date -u -d "${BASH_REMATCH[2]}" +%s >/dev/null 2>&1; then
      return 0
    fi
  done <<< "$1"
  return 1
}
report_manifest_is_valid() {
  jq -e '.schema_version == "2.0.0" and .publication_format_version == "2.0.0" and .route_count == 685 and (.generation_id | type == "string" and length > 0) and (.published_at | type == "string" and length > 0) and (.result_sha256 | test("^[a-f0-9]{64}$"))' "$1"
}
AWS_PROFILE=nova-toll-prod aws --region us-east-1 lambda invoke \
  --function-name "$PUBLISHER_FUNCTION" --invocation-type Event \
  --cli-binary-format raw-in-base64-out \
  --payload "$(jq -nc --arg smoke_id "$REPORT_SMOKE_ID" '{trigger:"watchdog",smoke_id:$smoke_id}')" \
  "$REPORT_INVOKE" | jq -e '.StatusCode == 202'
REPORT_RESULT=""
for attempt in $(seq 1 90); do
  REPORT_RESULT="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 logs filter-log-events \
    --log-group-name "$PUBLISHER_LOG_GROUP" --start-time "$REPORT_STARTED_MS" \
    --filter-pattern "\"V2_REPORT_SMOKE_OK $REPORT_SMOKE_ID\"" \
    --query 'events[].[timestamp,message]' --output text || true)"
  if report_smoke_succeeded "$REPORT_RESULT"; then
    break
  fi
  sleep 10
done
report_smoke_succeeded "$REPORT_RESULT"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api get-object \
  --bucket "$SITE_BUCKET" --key tolls/i95-i495/manifest.json \
  "$REPORT_MANIFEST" >/dev/null
report_manifest_is_valid "$REPORT_MANIFEST"
unset REPORT_RESULT REPORT_SMOKE_ID REPORT_STARTED_MS PUBLISHER_LOG_GROUP
```

Check every canonical report and JSON sibling with bounded concurrency, then
deep-check both hostnames, the crawler policy, representative agent families,
and API isolation:

```sh
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT/v2/infra"
test "$(AWS_PROFILE=nova-toll-prod aws sts get-caller-identity --query Account --output text)" = "920534282028"
AWS_PROFILE=nova-toll-prod terraform init -reconfigure -input=false -backend-config=backend.production.hcl
PUBLISHER_FUNCTION="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_lambda_function.publisher | awk -F' = ' '$1 ~ /^    function_name/ {gsub(/"/, "", $2); print $2; exit}')"
PUBLISHER_LOG_GROUP="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_cloudwatch_log_group.publisher | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_DISTRIBUTION="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.distribution_id | select(type == "string")')"
SITE_URL="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.url | select(type == "string")')"
SITE_BUCKET="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
test "$PUBLISHER_FUNCTION" = "toll-v2-report-publisher"
test "$PUBLISHER_LOG_GROUP" = "/aws/lambda/toll-v2-report-publisher"
test "$SITE_BUCKET" = "tollchat-site-920534282028"
test -n "$SITE_DISTRIBUTION"
[[ "$SITE_DISTRIBUTION" =~ ^[A-Z0-9]+$ ]]
test "$SITE_URL" = "https://tollchat.ai"
REPORT_URLS="$(mktemp)"
curl --fail-with-body --silent --show-error "$SITE_URL/sitemap.xml" \
  | grep -o '<loc>[^<]*</loc>' | sed 's#</\?loc>##g' >"$REPORT_URLS"
test "$(wc -l <"$REPORT_URLS")" -eq 685
xargs -P 8 -n 1 sh -c '
  html="$1"
  curl --fail --silent --show-error --head "$html" \
    | grep -qi "^content-type: text/html"
  curl --fail --silent --show-error --head "${html}report.json" \
    | grep -qi "^content-type: application/json"
' _ <"$REPORT_URLS"

REPORT_URL="$SITE_URL/tolls/i95-i495/dumfries-dumfries-road-route-234-northbound/tysons-westpark-drive-tysons-corner-northbound/"
REPORT_PAGE="$(mktemp)"
curl --fail-with-body --silent --show-error "$REPORT_URL" >"$REPORT_PAGE"
grep -F '<link rel="canonical" href="'"$REPORT_URL"'">' "$REPORT_PAGE"
grep -F '<link rel="alternate" type="application/json" href="report.json">' "$REPORT_PAGE"
! grep -qi 'noindex\|<script' "$REPORT_PAGE"
curl --fail-with-body --silent --show-error "$SITE_URL/robots.txt" \
  | grep -F "Sitemap: $SITE_URL/sitemap.xml"
for agent in OAI-SearchBot Googlebot Claude-SearchBot PerplexityBot bingbot \
  Amzn-SearchBot Applebot DuckAssistBot; do
  curl --fail-with-body --silent --show-error --user-agent "$agent" \
    "$REPORT_URL" >/dev/null
done
curl --fail-with-body --silent --show-error "$SITE_URL/api/config" >/dev/null
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "$SITE_URL/api/chat")" -eq 404
rm -f -- "$REPORT_PAGE" "$REPORT_URLS"
unset REPORT_PAGE REPORT_URL REPORT_URLS SITE_URL
```

## Agent-route measurement launch

Confirm Cloudflare remains DNS-only, generate uniquely recognizable HTML and
JSON requests, invoke the rollup, and inspect only the sanitized saved view.
The WAF logging destination can take several minutes to deliver its first file.

```sh
REPORT_URL="https://tollchat.ai/tolls/i95-i495/dumfries-dumfries-road-route-234-northbound/tysons-westpark-drive-tysons-corner-northbound/"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 wafv2 get-logging-configuration \
  --resource-arn "$(AWS_PROFILE=nova-toll-prod terraform output -raw agent_report_web_acl_arn)"
curl --fail-with-body --silent --show-error --user-agent 'ChatGPT-User Task6Smoke' \
  "$REPORT_URL" >/dev/null
curl --fail-with-body --silent --show-error --user-agent 'ChatGPT-User Task6Smoke' \
  "${REPORT_URL}report.json" >/dev/null
curl --fail-with-body --silent --show-error --head "$REPORT_URL" >/dev/null
AWS_PROFILE=nova-toll-prod aws --region us-east-1 lambda invoke \
  --function-name tollchat-v2-agent-usage-rollup --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/agent-usage-rollup.json
jq -e '.completed_dates | length == 3' /tmp/agent-usage-rollup.json
rm -f /tmp/agent-usage-rollup.json
unset REPORT_URL
```

Open the `tollchat-v2-public-chat` protection pack's **AI Traffic Analysis**
tab for the native 14-day view. In Athena, select the
`tollchat-agent-reports` workgroup and run the Terraform-managed top-routes or
recent-request-times named query. Never export the raw WAF table.

Terraform uploads both application packages to versioned S3 keys and pins the
resulting object version IDs in Lambda and AgentCore. Do not apply an unsaved
or unreviewed plan. The public Function URL targets the published `live` alias,
which keeps one provisioned execution environment warm. The function-level
reserved concurrency remains the five-request safety ceiling.

## Smoke test

Read `terraform output -json private_preview`, connect through Tailscale, and
use its `origin` and `url` values:

```sh
curl --fail-with-body "$URL/api/config" \
  -H "Origin: $ORIGIN" \
  -H 'Sec-Fetch-Site: same-origin'

curl --fail-with-body --no-buffer "$URL/api/chat" \
  -H "Origin: $ORIGIN" \
  -H 'Sec-Fetch-Site: same-origin' \
  -H 'Content-Type: application/json' \
  --data '{"message":"What is the current I-95 toll?"}'
```

The config request must succeed and chat must stream approved tool-status
events followed by an answer and disclaimer. Cross-origin requests to the
private chat route must fail.

After the private check passes, verify the public edge and warm alias:

```sh
curl --fail-with-body https://tollchat.ai/
curl --fail-with-body https://tollchat.ai/api/config
AWS_PROFILE=nova-toll-prod aws --region us-east-1 lambda get-provisioned-concurrency-config \
  --function-name tollchat-v2-chat-proxy --qualifier live
```

The concurrency status and allocation must be `READY` and `1`. Submit a first
chat only after opting that browser out. First save the consistent aggregate
returned by this command:

```sh
AWS_PROFILE=nova-toll-prod aws --region us-east-1 dynamodb get-item \
  --table-name tollchat-v2-anonymous-sessions \
  --key '{"credential_hash":{"S":"usage#all"}}' \
  --projection-expression 'engaged_sessions, completed_responses' \
  --consistent-read
```

In the public browser's developer console, set and check the owner opt-out,
then click **New chat** to reset the session before submitting the smoke message:

```js
document.cookie = "tollchat_usage_optout=1; Domain=tollchat.ai; Path=/; Max-Age=31536000; Secure; SameSite=Strict";
document.cookie.includes("tollchat_usage_optout=1");
```

The check must return `true`. Rerun the consistent DynamoDB read after the
response completes; the aggregate must be unchanged. Confirm CloudWatch records
the request under `ProvisionedConcurrencyInvocations`, without an on-demand
Lambda initialization. The public Function URL must reject direct unsigned
invocation.

## Rollback

For a report-rendering regression, keep the CloudFront rewrite active, deploy
corrected publisher code with a bumped publication format version, and invoke a
watchdog run to replace the complete generation. If report source content is
unsafe, stop new report writes with EventBridge Scheduler. First read and review
the exact schedule (including its group when it is not `default`), then preserve
only its required update fields in a reviewed temporary input. Do not pass the
raw `get-schedule` response back to AWS because it contains read-only fields.

```sh
(
set -euo pipefail
SCHEDULE_SOURCE="$(mktemp)"; SCHEDULE_UPDATE="$(mktemp)"
trap 'rm -f -- "$SCHEDULE_SOURCE" "$SCHEDULE_UPDATE"' EXIT
SCHEDULE_STATE="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_scheduler_schedule.publisher)"
SCHEDULE_NAME="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SCHEDULE_GROUP="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    group_name/ {gsub(/"/, "", $2); print $2; exit}')"
case "$SCHEDULE_NAME:$SCHEDULE_GROUP" in :*|*:|*:None|*:null) exit 1 ;; esac
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler get-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" >"$SCHEDULE_SOURCE"
jq -e '{ScheduleExpression, ScheduleExpressionTimezone, FlexibleTimeWindow, Target} | select(.ScheduleExpression and .FlexibleTimeWindow and .Target and .Target.Arn and .Target.RoleArn)' "$SCHEDULE_SOURCE" >"$SCHEDULE_UPDATE"
# Review $SCHEDULE_UPDATE in an approved secure viewer; it retains input, retry policy, and DLQ.
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler update-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" --state DISABLED --schedule-expression "$(jq -er .ScheduleExpression "$SCHEDULE_UPDATE")" --schedule-expression-timezone "$(jq -er .ScheduleExpressionTimezone "$SCHEDULE_UPDATE")" --flexible-time-window "$(jq -c .FlexibleTimeWindow "$SCHEDULE_UPDATE")" --target "$(jq -c .Target "$SCHEDULE_UPDATE")"
)
```

Resume with the same complete selected-state procedure, freshly retrieving and
reviewing its fields before mutation:

```sh
(
set -euo pipefail
SCHEDULE_SOURCE="$(mktemp)"; SCHEDULE_UPDATE="$(mktemp)"
trap 'rm -f -- "$SCHEDULE_SOURCE" "$SCHEDULE_UPDATE"' EXIT
SCHEDULE_STATE="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_scheduler_schedule.publisher)"
SCHEDULE_NAME="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SCHEDULE_GROUP="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    group_name/ {gsub(/"/, "", $2); print $2; exit}')"
case "$SCHEDULE_NAME:$SCHEDULE_GROUP" in :*|*:|*:None|*:null) exit 1 ;; esac
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler get-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" >"$SCHEDULE_SOURCE"
jq -e '{ScheduleExpression, ScheduleExpressionTimezone, FlexibleTimeWindow, Target} | select(.ScheduleExpression and .FlexibleTimeWindow and .Target and .Target.Arn and .Target.RoleArn)' "$SCHEDULE_SOURCE" >"$SCHEDULE_UPDATE"
# Review $SCHEDULE_UPDATE in an approved secure viewer before enabling.
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler update-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" --state ENABLED --schedule-expression "$(jq -er .ScheduleExpression "$SCHEDULE_UPDATE")" --schedule-expression-timezone "$(jq -er .ScheduleExpressionTimezone "$SCHEDULE_UPDATE")" --flexible-time-window "$(jq -c .FlexibleTimeWindow "$SCHEDULE_UPDATE")" --target "$(jq -c .Target "$SCHEDULE_UPDATE")"
)
```

Disabling publication does not withdraw existing report objects. The site
bucket is not versioned. A public takedown therefore requires separate approval
to delete the exact `tolls/i95-i495/` prefix and `sitemap.xml`, followed by a
targeted CloudFront invalidation. Do not perform that destructive rollback as
part of an ordinary application rollback.

Disable daily publication before preparing a rollback:

```sh
AWS_PROFILE=nova-toll-prod aws --region us-east-1 events disable-rule \
  --name tollchat-v2-usage-publisher
```

For immediate recovery, set `RELEASE_EVIDENCE` to the original failed release's
pre-apply evidence file. Do not rerun capture. Restore its targets before
running the Terraform rollback; this deliberately creates temporary drift that
the saved-plan deployment below must reconcile:

```sh
(
  set -eu
  : "${RELEASE_EVIDENCE:?set the original failed release evidence path}"
  test "$(wc -l <"$RELEASE_EVIDENCE")" -eq 3
  grep -qx 'lambda_live_function_version=[0-9][0-9]*' "$RELEASE_EVIDENCE"
  grep -qx 'agentcore_runtime_id=[A-Za-z0-9][A-Za-z0-9_-]*' "$RELEASE_EVIDENCE"
  grep -qx 'agentcore_endpoint_live_version=[0-9][0-9]*' "$RELEASE_EVIDENCE"
  LAMBDA_LIVE_FUNCTION_VERSION="$(sed -n 's/^lambda_live_function_version=//p' "$RELEASE_EVIDENCE")"
  AGENTCORE_RUNTIME_ID="$(sed -n 's/^agentcore_runtime_id=//p' "$RELEASE_EVIDENCE")"
  AGENTCORE_ENDPOINT_LIVE_VERSION="$(sed -n 's/^agentcore_endpoint_live_version=//p' "$RELEASE_EVIDENCE")"
  AWS_PROFILE=nova-toll-prod aws --region us-east-1 lambda update-alias \
    --function-name tollchat-v2-chat-proxy --name live \
    --function-version "$LAMBDA_LIVE_FUNCTION_VERSION"
  AWS_PROFILE=nova-toll-prod aws --region us-east-1 bedrock-agentcore-control update-agent-runtime-endpoint \
    --agent-runtime-id "$AGENTCORE_RUNTIME_ID" --endpoint-name preview \
    --agent-runtime-version "$AGENTCORE_ENDPOINT_LIVE_VERSION"
)
```

After the immediate rollback smoke test passes, check out the last accepted
release revision, rebuild it, verify its recorded SHA-256 manifest, and repeat
the saved-plan deployment workflow without recapturing evidence. Restore the old
proxy and public site together so the code and disclosure remain consistent.
The apply must reconcile the Lambda alias and AgentCore endpoint with Terraform
state; rerun the reviewed plan afterward and require it to report no changes.

Deterministic builds restore the exact package bytes; bucket versioning retains
the earlier runtime and proxy objects for 30 days. When rolling back to a
pre-metrics revision, expect the plan to remove the usage publisher, schedule,
alarms, placeholder, and metrics-era public/legal assets. Retain the DynamoDB
`usage#all` aggregate; it is operational history and is not managed as a
Terraform item.

If the application cannot safely serve traffic while rollback is prepared, stop
and obtain separate incident authorization. Do not mutate concurrency outside a
reviewed saved Terraform plan.

Database and shared polling/storage infrastructure are not part of application
rollback.

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

4. Build a durable detach manifest after the archive and identity checks. The
   only exact state addresses that may be detached are:

   ```text
   cloudflare_dns_record.apex[0]                         # current cutover record
   cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"] # old validation, until DNS step
   aws_bedrock_guardrail.tollchat                         # prevent_destroy retained
   aws_bedrock_guardrail_version.tollchat                 # skip_destroy retained
   ```

   State-list/show and remote identity checks must pass for each address before
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
   can never authorize a deletion. Set `STATE_SSEKMS_KEY_ID` to the exact reviewed
   production state CMK ID/ARN captured from the source object's
   `SSEKMSKeyId`; the source and archive must both be checked against it.

   ```sh
   (
   set -euo pipefail
   set +x
   umask 077
   ROOT="$(git rev-parse --show-toplevel)"
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
   WORK_DIR="$(mktemp -d -t nova-toll-333-state-XXXXXX)"
   COMPAT_ROOT="$WORK_DIR/compat"
   SOURCE_STATE="$WORK_DIR/source-state.json"
   ARCHIVE_STATE_PRIVATE="$WORK_DIR/archive-state.json"
   LIVE_STATE_PRIVATE="$WORK_DIR/live-state-before-detach.json"
   LIVE_STATE_AFTER_DETACH="$WORK_DIR/live-state-after-detach.json"
   DESTROY_PLAN="$WORK_DIR/legacy-retirement.tfplan"
   DESTROY_PLAN_JSON="$WORK_DIR/legacy-retirement.tfplan.json"
   DESTROY_PLAN_APPLY_JSON="$WORK_DIR/legacy-retirement.tfplan.immediately-before-apply.json"
   trap 'git worktree remove --force "$COMPAT_ROOT" >/dev/null 2>&1 || true; rm -f -- "$SOURCE_STATE" "$ARCHIVE_STATE_PRIVATE" "$LIVE_STATE_PRIVATE" "$LIVE_STATE_AFTER_DETACH" "$DESTROY_PLAN" "$DESTROY_PLAN_JSON" "$DESTROY_PLAN_APPLY_JSON" "$WORK_DIR/head.json" "$WORK_DIR/foundation-head.json" "$WORK_DIR/archive-copy.json" "$WORK_DIR/archive-head.json" "$WORK_DIR/head-before-detach.json" "$WORK_DIR/head-after-detach.json" "$WORK_DIR/head-before-plan.json" "$WORK_DIR/head-before-plan-render.json" "$WORK_DIR/head-immediately-before-render.json" "$WORK_DIR/head-immediately-before-apply.json" "$WORK_DIR/state-list.txt" "$WORK_DIR/state-list-after-detach.txt" "$WORK_DIR"/state-show_*.txt; rmdir "$WORK_DIR"' EXIT
   export AWS_PROFILE=nova-toll-prod
   export AWS_DEFAULT_REGION=us-east-1
   export AWS_REGION=us-east-1
   test "$(aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"
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
   for address in \
     'cloudflare_dns_record.apex[0]' \
     'cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"]' \
     'aws_bedrock_guardrail.tollchat' \
     'aws_bedrock_guardrail_version.tollchat'; do
     grep -Fqx "$address" "$WORK_DIR/state-list.txt"
     terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state show -no-color "$address" >"$WORK_DIR/state-show-${address//[^A-Za-z0-9]/_}.txt"
   done
   terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state pull >"$LIVE_STATE_PRIVATE"
   # Parse the complete backend snapshot, rather than trusting text output.
   python3 "$ROOT/v2/scripts/validate_legacy_retirement_plan.py" --state "$LIVE_STATE_PRIVATE" --identity-manifest "$LIVE_IDENTITY_MANIFEST" --state-only
   python3 "$ROOT/v2/scripts/validate_legacy_retirement_plan.py" --state "$ARCHIVE_STATE_PRIVATE" --identity-manifest "$LIVE_IDENTITY_MANIFEST" --state-only
   for address in \
     'cloudflare_dns_record.apex[0]' \
     'cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"]' \
     'aws_bedrock_guardrail.tollchat' \
     'aws_bedrock_guardrail_version.tollchat'; do
     expected_id="$(jq -er --arg address "$address" \
       '[.resources[] | select(.address == $address) | .id] | if length == 1 then .[0] else error("retained identity cardinality") end' \
       "$LIVE_IDENTITY_MANIFEST")"
     actual_id="$(sed -nE 's/^[[:space:]]*id[[:space:]]*=[[:space:]]*"?([^" ]*)"?[[:space:]]*$/\1/p' \
       "$WORK_DIR/state-show-${address//[^A-Za-z0-9]/_}.txt")"
     test "$(printf '%s\n' "$actual_id" | awk 'NF {count++} END {print count + 0}')" -eq 1
     test "$actual_id" = "$expected_id"
   done
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
   identity, or any exact state-show check fails, stop with the canonical state
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
   `nova-toll-db`, the managed master-secret ARN, and the CA SHA-256 before
   invoking the script against `postgres`. The script itself repeats fixed
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
   AWS_PROFILE=nova-toll-prod
   ROOT="$(git rev-parse --show-toplevel)"
   DB_INSTANCE=nova-toll-db
   CA_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
   CA_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
   WORK_DIR="$(mktemp -d -t nova-toll-333-db-XXXXXX)"
   CA_FILE="$WORK_DIR/global-bundle.pem"
   HANDOFF="$WORK_DIR/legacy-db-handoff.json"
   RDS_JSON= SECRET_JSON= DB_HOST= DB_PORT= DB_USER= DB_PASSWORD=
   cleanup() { unset DB_PASSWORD DB_USER SECRET_JSON SECRET_ARN RDS_JSON RETIRE_LEGACY_DB_PASSWORD RETIRE_LEGACY_DB_USER; rm -rf -- "$WORK_DIR"; }
   trap cleanup EXIT
   trap 'exit 130' HUP INT TERM
   test "$(AWS_PROFILE="$AWS_PROFILE" aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT"
   RDS_JSON="$(AWS_PROFILE="$AWS_PROFILE" aws --region "$REGION" rds describe-db-instances \
     --db-instance-identifier "$DB_INSTANCE" --query DBInstances --output json)"
   printf '%s\n' "$RDS_JSON" | jq -e --arg account "$EXPECTED_ACCOUNT" --arg instance "$DB_INSTANCE" '
     type == "array" and length == 1 and .[0].DBInstanceIdentifier == $instance and
     .[0].DBInstanceStatus == "available" and .[0].PubliclyAccessible == false and
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
   The database comment `environment=development` and each development role's
   comment `environment=development` are required, along with reviewed
   pricing/database-owner and `oracle_owner_development` schema
   owners, exactly `plpgsql` plus `postgis` (PostGIS in `oracle`), no
   subscriptions, publications, replication slots, foreign wrappers/tables,
   user mappings, event triggers, or unreviewed catalog dependencies. The
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

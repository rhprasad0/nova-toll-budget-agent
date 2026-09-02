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

The bounded #331 application/database bootstrap below is the operative
development release path. Public report publication remains non-operative during
bootstrap: the existing publisher and scheduler are deployed unchanged, but no
publication is manually invoked and no report data is copied. The #330 foundation
handoff remains the documented sequence of local-backend plan generation and review,
later exact-plan apply, and separately authorized state migration or recovery.
Cloudflare/DNS/CI cutover is owned by #332, and legacy cleanup remains owned by
#333. An AWS-only identity cannot write Cloudflare DNS.

### Development application/database bootstrap (#331)

This is the only operative #331 release procedure. It uses only the development
account and the two development state backends. The typed, non-secret foundation
output is consumed ephemerally from the #330 development foundation state. The
first plan creates a CloudFront distribution with no aliases and the CloudFront
default certificate. After that apply returns its d*.cloudfront.net hostname, the
second plan supplies that hostname to the proxy allowlist and preview output. No
custom-domain certificate, Cloudflare lookup/resource, Route 53 record, or change
to dev.tollchat.ai is part of either plan.

When direct workstation access to the private RDS endpoint is unavailable, an
already-authorized development private path may forward the endpoint to a local
port. Set `NOVA_TOLL_RDS_LOCAL_PORT` to that port before this procedure; the
procedure keeps `PGHOST` set to the RDS endpoint so TLS hostname verification
still applies and uses only `127.0.0.1` as the transport address.

Keep the terminal non-traced. The development RDS-managed Secrets Manager JSON and
its extracted username/password exist only in process memory and are never
printed, placed in an argument, written to a file, put in Terraform input/state/
plan, or recorded in evidence.

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
SECRET_ARN=
SECRET_JSON=
PGUSER=
PGPASSWORD=
BOOTSTRAP_STATUS=pass
cleanup() {
  unset PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE PGSSLMODE PGSSLROOTCERT
  unset SECRET_JSON SECRET_ARN RDS_METADATA DB_USER DB_PASSWORD DB_HOST DB_PORT
  rm -f -- "$FOUNDATION_JSON" "$DEV_FOUNDATION_VARS" "$PHASE_ONE_PLAN_JSON" "$PHASE_TWO_PLAN_JSON" "$CA_FILE" "$IDENTITY_JSON" "$RESET_BODY" "$RESET_REQUEST" "$PHASE_ONE_PLAN" "$PHASE_TWO_PLAN"
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
jq -e 'def exact_keys($keys): type == "object" and ((keys_unsorted | sort) == ($keys | sort)); . as $foundation | exact_keys(["vpc_id", "vpc_cidr_block", "private_subnet_ids", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "db_instance", "alerts_topic_arn"]) and all(["vpc_id", "vpc_cidr_block", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "alerts_topic_arn"][]; $foundation[.] | type == "string" and length > 0) and ($foundation.private_subnet_ids | exact_keys(["a", "c"]) and all(.[]; type == "string" and length > 0)) and ($foundation.db_instance | exact_keys(["identifier", "resource_id", "address", "port"]) and .identifier != "" and .resource_id != "" and .address != "" and (.port | type == "number"))' "$FOUNDATION_JSON" >/dev/null
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
ARTIFACT_SSM_PATTERN='arn:aws:ssm:'
ALLOWED_SSM_REFERENCE='arn:aws:ssm:us-east-1:903859731897:parameter/nova-toll/openai_api_key'
scan_release_file() {
  local file="$1" statuses
  if rg --text --ignore-case --quiet -- "$ARTIFACT_SCAN_PATTERN" "$file"; then
    exit 1
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
  if rg --text --ignore-case --quiet -- "$ARTIFACT_SSM_PATTERN" "$file"; then
    if rg --text --ignore-case -- "$ARTIFACT_SSM_PATTERN" "$file" | rg --invert-match --fixed-strings --quiet -- "$ALLOWED_SSM_REFERENCE"; then
      exit 1
    fi
    statuses=("${PIPESTATUS[@]}")
    if [ "${statuses[0]}" -ne 0 ] || [ "${statuses[1]}" -ne 1 ]; then
      exit 1
    fi
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
}
scan_package() {
  local package="$1" statuses
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
  if unzip -p "$package" | rg --text --ignore-case --quiet -- "$ARTIFACT_SSM_PATTERN"; then
    if unzip -p "$package" | rg --text --ignore-case -- "$ARTIFACT_SSM_PATTERN" | rg --invert-match --fixed-strings --quiet -- "$ALLOWED_SSM_REFERENCE"; then
      exit 1
    fi
    statuses=("${PIPESTATUS[@]}")
    if [ "${statuses[0]}" -ne 0 ] || [ "${statuses[1]}" -ne 1 ]; then
      exit 1
    fi
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
}
scan_release_directory() {
  while IFS= read -r -d '' file; do
    scan_release_file "$file"
  done < <(find "$RELEASE_DIR" -type f -print0)
}

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
  if ! jq -e '(.resource_changes | type == "array") and all(.resource_changes[]; (.change.actions | type == "array" and length > 0 and all(.[]; . != "delete")) and (.address | test("cloudflare|route53|aws_acm_certificate|aws_acm_certificate_validation"; "i") | not) and (.mode == "managed" or .mode == "data"))' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if ! jq -e --arg allowlist "$DEVELOPMENT_RESOURCE_ALLOWLIST" '
    ($allowlist | split("\n") | map(select(length > 0))) as $allowed |
    all(.resource_changes[] | select(.mode == "managed");
      (.address as $address |
        any($allowed[]; . as $base | ($address == $base or ($address | startswith($base + "["))))
        and (.change.actions | type == "array" and length > 0 and all(.[]; . == "create" or . == "update" or . == "no-op"))))
  ' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if ! jq -e --arg allowlist "$DEVELOPMENT_DATA_ALLOWLIST" '
    ($allowlist | split("\n") | map(select(length > 0))) as $allowed |
    all(.resource_changes[] | select(.mode == "data");
      (.address as $address |
        any($allowed[]; . as $base | ($address == $base or ($address | startswith($base + "["))))
        and (.change.actions | type == "array" and length > 0 and all(.[]; . == "read" or . == "no-op"))))
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
    def unreserved($address):
      managed_changes($address) as $resource |
      if ($resource | type) != "object" then false
      elif (($resource.change.after_unknown? // {}) | (.reserved_concurrent_executions? // false)) then false
      else ($resource.change.after | type == "object" and has("reserved_concurrent_executions") and (.reserved_concurrent_executions == null or .reserved_concurrent_executions == -1))
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
      and unreserved("aws_lambda_function.loader")
      and unreserved("aws_lambda_function.publisher")
      and unreserved("aws_lambda_function.tollchat_proxy")
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
tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_ONE_PLAN" >/dev/null
PUBLIC_SITE_JSON="$(tf_dev -chdir="$ROOT/v2/infra" output -json public_site)"
PREVIEW_HOST="$(jq -er '.hostname | select(test("^d[A-Za-z0-9]+[.]cloudfront[.]net$"))' <<<"$PUBLIC_SITE_JSON")"
PREVIEW_URL="https://$PREVIEW_HOST"
test "$(jq -r '.url' <<<"$PUBLIC_SITE_JSON")" = ""
tf_dev -chdir="$ROOT/v2/infra" plan -input=false $PLAN_ARGS -var "public_preview_hostname=$PREVIEW_HOST" -out="$PHASE_TWO_PLAN" >/dev/null
PHASE_TWO_PLAN_SHA256="$(plan_policy "$PHASE_TWO_PLAN" phase-two)"
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
assert_no_reserved_concurrency() {
  local function_name="$1" response
  if response="$(aws_dev lambda get-function-concurrency --function-name "$function_name" --output json 2>&1)"; then
    if [ -n "$response" ]; then
      jq -e '(.ReservedConcurrentExecutions? // null) == null' <<<"$response" >/dev/null
    fi
  else
    grep -Fq 'ResourceNotFoundException' <<<"$response"
  fi
}
for function_name in toll-v2-pricing-loader-dev toll-v2-report-publisher-dev tollchat-v2-chat-proxy-dev; do
  assert_no_reserved_concurrency "$function_name"
done
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
if ! python3 "$ROOT/v2/scripts/bootstrap_development_database.py" >/dev/null 2>"$RELEASE_DIR/bootstrap.err"; then
  grep -Fx 'ERROR:  development database already exists' "$RELEASE_DIR/bootstrap.err" >/dev/null
  BOOTSTRAP_STATUS=already-present
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
for plan in "$PHASE_ONE_PLAN" "$PHASE_TWO_PLAN" "$PHASE_ONE_PLAN_JSON" "$PHASE_TWO_PLAN_JSON"; do
  scan_release_file "$plan"
done
for package in infra/build/loader.zip infra/build/publisher.zip infra/build/agentcore.zip infra/build/chat-proxy.zip; do
  scan_package "$package"
done
scan_release_directory
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SOURCE_REVISION"
test "$SOURCE_TREE_SHA256" = "$(source_tree_digest)"
test "$SOURCE_DIFF_SHA256" = "$(git -C "$ROOT" diff HEAD --no-ext-diff --binary -- . ':(exclude).graph' | sha256sum | cut -d' ' -f1)"
printf '%s\n' "account=$EXPECTED_ACCOUNT" "region=$REGION" "source_revision=$(git -C "$ROOT" rev-parse HEAD)" "source_tree_sha256=$SOURCE_TREE_SHA256" "source_diff_sha256=$SOURCE_DIFF_SHA256" "foundation_sha256=$FOUNDATION_DIGEST" "phase_one_plan_sha256=$PHASE_ONE_PLAN_SHA256" "phase_two_plan_sha256=$PHASE_TWO_PLAN_SHA256" "loader_sha256=$LOADER_SHA256" "publisher_sha256=$PUBLISHER_SHA256" "agentcore_sha256=$AGENTCORE_SHA256" "chat_proxy_sha256=$PROXY_SHA256" "plan_policy=pass" "apply=pass" "bootstrap=$BOOTSTRAP_STATUS" "database_contract=$DB_CONTRACT" "resource_count=$RESOURCE_COUNT" "resource_inventory=$RESOURCE_TYPES" "preview_url=$PREVIEW_URL" "smoke=pass" "dns_before=$DNS_BEFORE" "dns_after=$DNS_AFTER" >"$RELEASE_EVIDENCE"
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

### Development foundation handoff (#330; no application release)

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
    "data.aws_subnet.tailscale_router"
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

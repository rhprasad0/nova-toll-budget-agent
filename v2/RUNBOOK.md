# AgentCore deployment

Trusted development planning runs automatically in PR and merge-queue CI. Its
reusable plan validates the event-derived candidate and runs a read-only
Terraform plan in the reviewer-free `development-plan` environment; it never
applies Terraform. The existing post-merge development application delivery
also runs automatically from `main`, using exact CI admission, one saved plan,
fixed development migrations, application apply, and readiness gates.

The `development-plan` environment remains reviewer-free with its custom
`refs/pull/*/merge`, `gh-readonly-queue/main/*`, and `main` branch policies.
The `development` environment remains reviewer-free with its `main` branch
policy. Production and `production-foundation-dns` remain reviewer-protected.

The secret-bearing manual
`.github/workflows/v2-development-connectivity-verification.yml` and
`.github/workflows/v2-development-migrations.yml` workflows remain
`workflow_dispatch`-only and require this exact job-level predicate:
`github.ref == 'refs/heads/main' && github.actor_id == '91573985' && github.triggering_actor == github.actor`.
Only reruns initiated by that original actor may reach the
development environment credentials. This owner-ID gate is separate from the
reviewer-free `development` environment and does not change the automatic
post-merge delivery path. Its credentialed deploy job requires
this exact predicate:
`vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && github.triggering_actor == github.actor`,
without restricting initial `main` pushes by owner ID.

## Delivery contract and production baseline

PRs use disposable PostGIS migration validation only; the checks are
credential-free and never access or mutate deployed databases or schemas. The
post-merge delivery path is separate from the explicit manual development
migration workflow, which may be dispatched from `refs/heads/main` for the
fixed development target and accepts no arbitrary target or migration-path
inputs. See the [protected development migration workflow](runbooks/development-foundation-replacement.md#protected-development-migration-workflow-305-slice-3)
for its foundation, bootstrap, identity, and evidence gates. Production
releases remain manual, reviewed deployments from `main`.
The manual production planner stores only a gated saved plan.
Production schema changes remain limited to the separately authorized, reviewed
procedures below. The one-time baseline adoption path is described next; future
recurring migrations require the later protected delivery workflow.
Application release
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

## Production baseline adoption (issue 304, slice 1)

The checked-in `v2/scripts/adopt_production_baseline.py` is a fixed-target,
one-time adoption helper for the existing `nova_toll` database on
`nova-toll-db`. It may run only after a human explicitly approves production
adoption and records a fresh, read-only evidence packet covering the AWS
account/region, private RDS endpoint, TLS CA, managed master secret, database
identity, schema versions and source hashes, the 996 Oracle connections,
runtime role memberships and `CONNECT`, and the explicit object-owner/ACL
allowlist. The helper rejects drift and records verified deployed schemas as
adopted; it never resets, bootstraps, migrates, or accepts caller-supplied
targets or manifest paths.

The operator must use the existing private-network route, the RDS-managed
administrative secret held only in process memory, and `verify-full` TLS. The
helper creates only `pricing_owner` and `schema_migrator_production`, transfers
the named pricing objects, and writes the two immutable baseline rows in one
bounded transaction. A SQL or postcondition failure is not a success signal;
if commit acknowledgement is uncertain, stop and collect a new read-only
state packet before retrying. This source PR performs no production invocation,
Terraform plan/apply, or live database mutation.

## RDS PostGIS type ACL exception (issue 304)

The adoption preflight accepts one observed platform state: `postgis` in
`oracle`, owned by `rdsadmin`, at version `3.5.6`, with one direct extension
dependency for each of `oracle.geometry` and `oracle.geography`. Both types
must be owned by `rdsadmin` and have exactly two non-grantable `USAGE` rows:
`rdsadmin` to `rdsadmin`, and `rdsadmin` to `PUBLIC`. Any other owner,
extension identity, dependency, grantor, grantee, privilege, or grant option
rejects adoption. Record that exact state in the fresh read-only evidence
packet before the normal fixed-target adoption; keep the private route,
in-memory managed secret, and `verify-full` TLS.

`PUBLIC` type `USAGE`, combined with an already-held database `TEMPORARY`
privilege, can permit temporary type-dependent objects. It does not grant
schema `USAGE` or `CREATE`, table `SELECT`/DML, function `EXECUTE`, persistent
Oracle creation, or data access. A disposable true-superuser PostGIS test
proves SQL shape, guards, atomicity, rollback, and idempotence only; it does
not prove RDS authority. On a failed or uncertain commit, stop and collect new
read-only evidence before any follow-up; do not reset, bootstrap, or migrate.

## Manual Oracle migration 030

Migration `v2/db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql` is the
only currently approved manual production schema change. Applying it requires
separate, explicit operator authorization and a reviewed checkout containing
that exact file. This procedure is not a PR or CI step: PRs remain offline and
use only disposable PostgreSQL migration validation. Current development-account
migrations follow the protected, fixed-target workflow documented below. The
legacy `nova_toll_development` rehearsal step in this bounded, separately
authorized migration-030 procedure remains a production-account rehearsal, not
that workflow.

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
included. Do not use that generic planned-output or tfvars flow for development.
The current development foundation path is the authorized #327/#333
replacement handoff documented below; the historical #330 exact-plan procedure
remains below for audit context only. Development state is not discovered
through a foundation output.

Application/database bootstrap remains #331. Cloudflare DNS reads and writes
(zone lookup, ACM certificate-validation records, and apex/www records) are
production-only in `v2/infra/site.tf`; development DNS/certificate validation
belongs to #332.
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

Historical `usage.json` is retained as a managed, data-bearing site object.
This release stops new writes and does not purge that snapshot or its logs; a
separately approved retirement procedure is required before either is removed.

The former first agent-route measurement release instructions are retained only
in the reviewed historical checkout for that release. They are not an
activation path for this source cleanup: no deployment claim follows from
removing the producer, and the retained measurement bucket, catalog, and
historical objects remain pending a separately approved retirement procedure.

## Development handoff and guarded production release

Use only the procedure that owns the intended operation:

- [Development application release and database validation (#331)](runbooks/development-release.md)
  is the operative development release path.
- [Development bootstrap/import boundary (#332)](runbooks/development-bootstrap-import.md)
- [Timed-check Scheduler bootstrap and verification (#345)](runbooks/timed-checks-scheduler.md)
  is retained for its bounded bootstrap, Cloudflare/DNS, and recovery contracts.
- [Development foundation replacement handoff (#327/#333)](runbooks/development-foundation-replacement.md)
  is the current development foundation and protected migration path.
- [Development foundation handoff (#330)](runbooks/development-foundation-330-archive.md)
  is historical audit and recovery context, not an activation path.
- [Legacy development retirement (#333)](runbooks/legacy-development-retirement.md)
  owns the ordered legacy cleanup procedure.

Public report publication remains non-operative.
An AWS-only identity cannot write Cloudflare DNS.

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
AWS_PROFILE=nova-toll-prod terraform plan -input=false -lock=false -var-file=production.tfvars -var-file="$PRODUCTION_FOUNDATION_VARS" -var loader_package_path=build/loader.zip -var publisher_package_path=build/publisher.zip -var agentcore_package_path=build/agentcore.zip -var chat_proxy_package_path=build/chat-proxy.zip -var timed_checks_package_path=build/timed-checks.zip -out=build/production-release.tfplan
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

The concurrency status and allocation must be `READY` and `1`. Submit a smoke
message only after the session-cookie reset path succeeds. There is no current
public usage counter or opt-out cookie. Confirm CloudWatch records the request
under `ProvisionedConcurrencyInvocations`, without an on-demand Lambda
initialization. The public Function URL must reject direct unsigned invocation.

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
the earlier runtime and proxy objects for 30 days. Historical usage aggregate,
snapshot, and publisher logs remain retained across rollback; no current writer
or public usage proof is restored by this procedure.

If the application cannot safely serve traffic while rollback is prepared, stop
and obtain separate incident authorization. Do not mutate concurrency outside a
reviewed saved Terraform plan.

Database and shared polling/storage infrastructure are not part of application
rollback.

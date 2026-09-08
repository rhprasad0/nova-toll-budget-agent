### Development foundation replacement handoff (#327/#333; source prerequisites)

The [historical #330 foundation bootstrap](development-foundation-330-archive.md)
is retained only for audit context; use this authorized #327/#333 replacement
handoff. Do not run the historical procedure.

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
proving versions, canonical row counts, development ownership/grants, the
private `tollchat_migration.schema_history` baseline, no PUBLIC CONNECT, and no
foreign or integration objects. In addition to the six runtime roles, it
creates only `pricing_owner_development` and `schema_migrator_development`;
the latter is an IAM-authenticated login with CONNECT only to the development
database and SET ROLE membership in the two stable owners. A failure removes
only schemas, roles, grants, and comments created by that invocation and stops
if cleanup is not proven.

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

##### Protected development migration workflow (#305 slice 3)

This workflow is a post-merge, protected development operation. Only migration
files whose backward-compatible status was reviewed by a human at merge may run
automatically, and only against the fixed development database. The builder and
CI checks do not assume the migration role, fetch an IAM token, connect to RDS,
apply Terraform, bootstrap PostgreSQL, or dispatch a workflow. No live action is
authorized from this graph run.

After human review and merge, the protected delivery job uses a clean checkout
of protected `origin/main` and follows this exact order:

1. Verify the release artifact, checkout `HEAD`, `GITHUB_SHA`, manifest commit,
   migration inventory, registry, baseline, and canonical SQL bytes are exactly
   equal before any delivery or migration credentials are available.
2. Create one private saved Terraform plan and run the existing JSON
   address/action gate. Do not apply or re-plan before migration; retain the
   exact plan across the credential switch.
3. After the RDS instance is available and the protected private route/
   transport proof passes, assume only
   `nova-toll-v2-development-migrations-dev` and run the fixed runner. Expected
   `after` versions come from the verified release manifest. Keep the reviewed
   administrator URL, password, and any IAM token in process memory only; never
   write them to a file, argument, state, plan, log, summary, or artifact.

   When a canonical schema version advances, add its contiguous migration
   chain and append the matching immutable record to
   `v2/db/migration-baselines.json`. Existing manifest records must never be
   rewritten or deleted; this metadata change does not authorize a live action.

4. Re-assume `nova-toll-v2-development-delivery` and apply the same saved plan
   only after migration succeeds. The job uses the native
   `v2-development-apply` queue shared with the manual migration workflow.

5. While still holding that queue, verify the three application Lambda hashes
   and the proxy's published `live` alias, CloudFront readiness, and the exact
   AgentCore `preview` live/target version from private post-apply state. The
   bounded helper then checks manifest-backed HTTPS static bytes, generated
   development robots policy, API configuration, invalid-origin rejection, and
   a small agent exchange in two isolated sessions. Reset/replay verifies
   revocation without matching model prose; both sessions are cleaned up.

The explicit GitHub `development-release` record starts after exact CI admission
and before build. Its final status covers build through readiness/smoke; native
`development` environment records used for OIDC are not end-to-end proof. Failed,
cancelled, skipped, disabled, or stale attempts cannot produce release success.
A failed-deploy rerun reuses the same run/SHA's verified immutable build and
record, with the current attempt identified in its status link. The credentialed
deploy job admits that rerun only when `github.triggering_actor == github.actor`;
a different writer's rerun skips before development credentials. Status-publication
failure is a failed workflow, not successful evidence. The summary contains only
commit/run/attempt, artifact ID/digest, schema versions, job outcomes and the
fixed public URL. State, plans, AWS responses, credentials, cookies and chat
content are never published. The helper has a 15-minute deadline; failure does
not roll back an applied release or expand migration authority.

PR validation uses fake AWS/HTTP responses only. A visible post-merge live
demonstration still requires separate human authorization; do not dispatch the
workflow or invoke the live smoke merely to validate this implementation.

The fixed manual recovery workflow remains available for an explicitly approved
post-merge bootstrap or migration rehearsal after the reviewed foundation plan
and fresh development bootstrap gates. Dispatch
   `.github/workflows/v2-development-migrations.yml` only from `refs/heads/main`;
the job also requires GitHub actor ID `91573985` and
`github.triggering_actor == github.actor`:

   ```sh
   gh workflow run v2-development-migrations.yml \
     --repo rhprasad0/nova-toll-budget-agent --ref main
   ```

   The job joins only `tag:ci-development`, validates the fixed site-1 route,
   keeps the verified RDS DNS name in `PGHOST`, uses only the derived 4via6
   address in `PGHOSTADDR`, and authenticates only as
   `schema_migrator_development`. It accepts no database, user, host, port,
   migration-path, role, or production target input. Keep
   `DEVELOPMENT_DELIVERY_ENABLED` absent or `false` during manual recovery.

When the fresh bootstrap is current, the successful migration result must have
canonical `after` versions equal to the verified release manifest with
`applied=[]` (a non-current before state may contain only registered migration
paths and must finish at those same manifest-bound versions). Runner history evidence
uses exactly `commit=<40 lowercase hex>;run=<UUID>`; the workflow summary and
artifact add only the commit, GitHub run identifiers, account, fixed role,
database/user, before/after versions, applied paths, route/transport booleans,
and `status=ok`. They never contain a token, password, endpoint, host/port URL,
OAuth value, raw command output, error text, Terraform state, or plan. Preserve
the sanitized evidence with the reviewed foundation/bootstrap records. Any
failure stops for human review; do not retry an uncertain write or run a generic
migration command.

No rollback rehearsal or production migration is part of this handoff.

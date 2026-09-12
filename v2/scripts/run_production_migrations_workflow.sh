#!/usr/bin/env bash
# Fixed production boundary; every target below is a reviewed constant.
set -euo pipefail
set +x

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
source v2/scripts/run_private_stage.sh

EXPECTED_ACCOUNT=920534282028
EXPECTED_ROLE=nova-toll-v2-production-migrations
DB_IDENTIFIER=nova-toll-db
DB_NAME=nova_toll
DB_USER=schema_migrator_production
DB_RESOURCE_ID=db-WHGCQ3B5SB4WPB5RTJMU3CE664
CA_BUNDLE="$ROOT/v2/infra/build/ca/rds-ca-bundle.pem"
CA_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
OUT="$RUNNER_TEMP/production-migration.out"
ERR="$RUNNER_TEMP/production-migration.err"
CONTROL="$RUNNER_TEMP/production-migration-control.out"
PRIVATE_STAGE_REPORTED=0
PRIVATE_STAGE_SUMMARY_FAILED=0
PRIVATE_STAGE_FALLBACK_STAGE=production-migration
CANDIDATE="${PRODUCTION_MIGRATION_CANDIDATE-}"
ADMISSION="${PRODUCTION_MIGRATION_ADMISSION-}"

cleanup() {
  unset PGPASSWORD DB_TOKEN
  rm -f -- "$OUT" "$ERR" "$CONTROL"
}
finish() {
  status=$?
  trap - EXIT
  cleanup
  if (( status != 0 && PRIVATE_STAGE_REPORTED == 0 )); then
    _run_private_stage_emit "stage=$PRIVATE_STAGE_FALLBACK_STAGE status=fail elapsed=0 exit=$status reason=unclassified"
  fi
  exit "$status"
}
trap finish EXIT

run_private_stage migration-identity "$OUT" "$ERR" test "$GITHUB_REF" = refs/heads/main
run_private_stage migration-identity "$OUT" "$ERR" test "$GITHUB_REPOSITORY" = rhprasad0/nova-toll-budget-agent
run_private_stage migration-identity "$OUT" "$ERR" test -n "$CANDIDATE"
run_private_stage migration-identity "$OUT" "$ERR" test -n "$ADMISSION"
run_private_stage migration-identity "$OUT" "$ERR" jq -e --arg candidate "$CANDIDATE" '
  type == "object" and
  (keys | sort) == ["bundle_digest","bundle_id","candidate","claim_id","consumer_attempt","consumer_run","development_attempt","development_deployment","development_run","evidence_artifact","listener_attempt","listener_run","release_id","schema_versions","tag"] and
  .candidate == $candidate and ($candidate | test("^[0-9a-f]{40}$")) and
  (.release_id | type == "number") and (.claim_id | type == "number") and
  (.schema_versions | type == "object" and keys == ["oracle", "pricing"] and
   . == {pricing:"1.3.0", oracle:"1.14.0"})
' <<<"$ADMISSION"
run_private_stage rds-ca "$OUT" "$ERR" test -f "$CA_BUNDLE"
run_private_stage rds-ca "$OUT" "$ERR" test "$(sha256sum "$CA_BUNDLE" | awk '{print $1}')" = "$CA_SHA256"

run_private_stage migration-identity "$OUT" "$ERR" aws sts get-caller-identity --output json
CALLER_JSON="$(<"$OUT")"
run_private_stage migration-identity "$OUT" "$ERR" jq -e --arg account "$EXPECTED_ACCOUNT" --arg role "$EXPECTED_ROLE" '
  .Account == $account and (.Arn | type == "string" and test("^arn:aws:sts::" + $account + ":assumed-role/" + $role + "/[A-Za-z0-9+=,.@_-]+$"))
' <<<"$CALLER_JSON"

run_private_stage migration-database "$OUT" "$ERR" aws rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" --output json
DB_JSON="$(<"$OUT")"
run_private_stage migration-database "$OUT" "$ERR" jq -e --arg identifier "$DB_IDENTIFIER" --arg database "$DB_NAME" --arg resource "$DB_RESOURCE_ID" '
  (.DBInstances | type == "array" and length == 1) and (.DBInstances[0] as $db |
  ($db.DBInstanceIdentifier == $identifier and $db.DBName == $database and
   $db.DbiResourceId == $resource and $db.DBInstanceStatus == "available" and
   $db.PubliclyAccessible == false and $db.StorageEncrypted == true and
   $db.Engine == "postgres" and $db.IAMDatabaseAuthenticationEnabled == true and
   $db.BackupRetentionPeriod >= 7 and $db.Endpoint.Port == 5432 and
   ($db.Endpoint.Address | type == "string" and test("^nova-toll-db[.][a-z0-9-]+[.]us-east-1[.]rds[.]amazonaws[.]com$")) and
   ($db.LatestRestorableTime | type == "string")))
' <<<"$DB_JSON"
DB_HOST="$(jq -r '.DBInstances[0].Endpoint.Address' <<<"$DB_JSON")"
RECOVERY_TIME="$(jq -r '.DBInstances[0].LatestRestorableTime' <<<"$DB_JSON")"
run_private_stage migration-database "$OUT" "$ERR" python3 - "$RECOVERY_TIME" <<'PY'
from datetime import UTC, datetime, timedelta
import sys
try:
    value = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
except ValueError:
    raise SystemExit(1)
now = datetime.now(UTC)
if value.tzinfo is None or value > now or now - value > timedelta(minutes=30):
    raise SystemExit(1)
PY

run_private_stage migration-dns "$OUT" "$ERR" getent ahostsv4 "$DB_HOST"
DB_IPV4="$(awk '{print $1}' "$OUT" | sort -u)"
run_private_stage migration-dns "$OUT" "$ERR" test "$(wc -l <<<"$DB_IPV4")" -eq 1
run_private_stage migration-route "$OUT" "$ERR" python3 - "$DB_IPV4" <<'PY'
import ipaddress
import sys
if ipaddress.ip_address(sys.argv[1]) not in ipaddress.ip_network("172.31.0.0/16"):
    raise SystemExit(1)
PY
run_private_stage migration-route "$OUT" "$ERR" tailscale status --json
TAILSCALE_JSON="$(<"$OUT")"
run_private_stage migration-route "$OUT" "$ERR" jq -e '.BackendState == "Running"' <<<"$TAILSCALE_JSON"
run_private_stage migration-route "$OUT" "$ERR" ip -json route get "$DB_IPV4"
ROUTE_JSON="$(<"$OUT")"
run_private_stage migration-route "$OUT" "$ERR" jq -e --arg host "$DB_IPV4" '
  type == "array" and length == 1 and .[0].dst == $host and .[0].dev == "tailscale0"
' <<<"$ROUTE_JSON"
run_private_stage migration-socket "$OUT" "$ERR" python3 - "$DB_IPV4" <<'PY'
import socket
import sys
with socket.create_connection((sys.argv[1], 5432), timeout=3):
    pass
PY

export PGHOST="$DB_HOST" PGHOSTADDR="$DB_IPV4" PGPORT=5432
export PGDATABASE="$DB_NAME" PGUSER="$DB_USER" PGSSLMODE=verify-full PGSSLROOTCERT="$CA_BUNDLE"
_run_private_stage_emit 'stage=migration-token status=start elapsed=0 exit=0 reason=unclassified'
if DB_TOKEN="$(aws rds generate-db-auth-token --hostname "$DB_HOST" --port 5432 --region us-east-1 --username "$DB_USER" 2>"$ERR")"; then
  _run_private_stage_emit 'stage=migration-token status=pass elapsed=0 exit=0 reason=unclassified'
else
  status=$?
  _run_private_stage_emit "stage=migration-token status=fail elapsed=0 exit=$status reason=publisher_failed"
  PRIVATE_STAGE_REPORTED=1
  exit "$status"
fi
export PGPASSWORD="$DB_TOKEN"
unset DB_TOKEN
run_private_stage migration-runner "$OUT" "$ERR" python3 v2/scripts/run_production_migrations.py
RUNNER_JSON="$(<"$OUT")"
unset PGPASSWORD
run_private_stage migration-evidence "$OUT" "$ERR" jq -e --arg candidate "$CANDIDATE" --arg database "$DB_NAME" --arg user "$DB_USER" --argjson admission "$ADMISSION" '
  type == "object" and .commit == $candidate and .database == $database and .user == $user and .status == "ok" and
  (.after == $admission.schema_versions) and
  (.before | type == "object" and keys == ["oracle", "pricing"] and
   (.pricing | type == "string" and test("^[0-9]+[.][0-9]+[.][0-9]+$")) and
   (.oracle | type == "string" and test("^[0-9]+[.][0-9]+[.][0-9]+$"))) and
  (.applied | type == "array" and all(.[]; type == "string" and test("^v2/db/migrations/[0-9]{3}_upgrade_(pricing|oracle)_.*[.]sql$"))) and
  ((.before == .after and (.applied | length) == 0) or
   (.before != .after and (.applied | length) > 0))
' <<<"$RUNNER_JSON"
run_private_stage migration-evidence "$OUT" "$ERR" jq -cn --arg candidate "$CANDIDATE" --arg resource "$DB_RESOURCE_ID" --argjson admission "$ADMISSION" --argjson runner "$RUNNER_JSON" \
  '{candidate:$candidate,release_id:$admission.release_id,claim_id:$admission.claim_id,listener_run:$admission.listener_run,listener_attempt:$admission.listener_attempt,consumer_run:$admission.consumer_run,consumer_attempt:$admission.consumer_attempt,development_run:$admission.development_run,development_attempt:$admission.development_attempt,development_deployment:$admission.development_deployment,schema_versions:$admission.schema_versions,resource_id:$resource,before:$runner.before,after:$runner.after,applied:$runner.applied,runner_run_id:$runner.run_id,status:$runner.status}'
run_private_stage migration-evidence "$CONTROL" "$ERR" cp -P -- "$OUT" "$RUNNER_TEMP/v2-production-migrations-evidence.json"
run_private_stage migration-evidence "$CONTROL" "$ERR" chmod 600 "$RUNNER_TEMP/v2-production-migrations-evidence.json"

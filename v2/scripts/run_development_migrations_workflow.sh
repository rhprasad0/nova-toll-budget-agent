#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/v2"
source "$ROOT/v2/scripts/run_private_stage.sh"
MIGRATION_STDOUT_LOG="${RUNNER_TEMP}/development-migration-stage.stdout"
MIGRATION_STDERR_LOG="${RUNNER_TEMP}/development-migration-stage.stderr"
MIGRATION_CONTROL_LOG="${RUNNER_TEMP}/development-migration-control.stdout"

check_migration_role() {
  case "$CALLER_ARN" in
    arn:aws:sts::903859731897:assumed-role/nova-toll-v2-development-migrations-dev/*) ;;
    *) return 1 ;;
  esac
}

EXPECTED_ACCOUNT="903859731897"
EXPECTED_ROUTE="fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"
DB_IDENTIFIER="nova-toll-db"
DB_NAME="nova_toll_development"
DB_USER="schema_migrator_development"
EXPECTED_ROLE="nova-toll-v2-development-migrations-dev"
EXPECTED_PRICING_VERSION="${EXPECTED_PRICING_VERSION:?missing expected pricing version}"
EXPECTED_ORACLE_VERSION="${EXPECTED_ORACLE_VERSION:?missing expected Oracle version}"
RDS_CA_BUNDLE="$ROOT/v2/infra/build/ca/rds-ca-bundle.pem"

run_private_stage "migration-identity" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test "$GITHUB_REF" = "refs/heads/main"
run_private_stage "migration-identity" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test "$GITHUB_REPOSITORY" = "rhprasad0/nova-toll-budget-agent"

run_private_stage "migration-identity" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  aws sts get-caller-identity --output json
CALLER_JSON="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-identity" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  jq -er '.Account' <<<"$CALLER_JSON"
CALLER_ACCOUNT="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-identity" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT"
run_private_stage "migration-identity" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  jq -er '.Arn' <<<"$CALLER_JSON"
CALLER_ARN="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-identity" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  check_migration_role

run_private_stage "migration-database" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  aws rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" --output json
DB_JSON="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-database" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  jq -er '
  if (.DBInstances | length == 1 and .[0].DBInstanceIdentifier == "nova-toll-db"
      and .[0].DBInstanceStatus == "available"
      and .[0].PubliclyAccessible == false
      and .[0].Engine == "postgres"
      and .[0].DBName == "nova_toll_development")
  then .DBInstances[0].Endpoint.Address else empty end
  ' <<<"$DB_JSON"
DB_HOST="$(<"$MIGRATION_STDOUT_LOG")"
check_db_host() {
  case "$DB_HOST" in
    nova-toll-db.*.us-east-1.rds.amazonaws.com) ;;
    *) return 1 ;;
  esac
}
run_private_stage "migration-database" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  check_db_host

run_private_stage "migration-dns" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  getent ahostsv4 "$DB_HOST"
DB_IPV4="$(awk '{print $1}' "$MIGRATION_STDOUT_LOG" | sort -u)"
run_private_stage "migration-dns" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test "$(wc -l <<<"$DB_IPV4")" -eq 1
DB_IPV4="${DB_IPV4%$'\n'}"

run_private_stage "migration-route" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  tailscale debug via 1 "$DB_IPV4/32"
VIA_OUTPUT="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-route" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  env DB_IPV4="$DB_IPV4" VIA_OUTPUT="$VIA_OUTPUT" python3 - <<'PY'
import ipaddress
import os
import re

site_id = 1
via6_space = ipaddress.ip_network("fd7a:115c:a1e0:b1a::/64")
ipv4 = ipaddress.ip_address(os.environ["DB_IPV4"])
expected = ipaddress.ip_address(int(via6_space.network_address) | (site_id << 32) | int(ipv4))
candidates = set()
for token in re.findall(r"[0-9A-Fa-f:]{2,}", os.environ["VIA_OUTPUT"]):
    try:
        address = ipaddress.ip_address(token)
    except ValueError:
        continue
    if address.version == 6 and address in via6_space:
        candidates.add(address)
if (site_id >> 16) or candidates != {expected}:
    raise SystemExit(1)
print(expected)
PY
TRANSPORT_IPV6="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-route" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  python3 - "$TRANSPORT_IPV6" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
expected_prefix = ipaddress.ip_network("fd7a:115c:a1e0:b1a::/64")
if address.version != 6 or address not in expected_prefix:
    raise SystemExit(1)
print(address)
PY
run_private_stage "migration-route" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test "$(<"$MIGRATION_STDOUT_LOG")" = "$TRANSPORT_IPV6"

run_private_stage "migration-route" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  ip -json route get "$TRANSPORT_IPV6"
TRANSPORT_ROUTE_JSON="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-route" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  env TRANSPORT_IPV6="$TRANSPORT_IPV6" TRANSPORT_ROUTE_JSON="$TRANSPORT_ROUTE_JSON" python3 - <<'PY'
import json
import os

try:
    routes = json.loads(os.environ["TRANSPORT_ROUTE_JSON"])
except (json.JSONDecodeError, TypeError):
    raise SystemExit(1)
if not isinstance(routes, list) or len(routes) != 1:
    raise SystemExit(1)
route = routes[0]
if (
    not isinstance(route, dict)
    or route.get("dst") != os.environ["TRANSPORT_IPV6"]
    or route.get("dev") != "tailscale0"
):
    raise SystemExit(1)
print("expected-transport")
PY
TRANSPORT_ROUTE_STATE="$(<"$MIGRATION_STDOUT_LOG")"
run_private_stage "migration-route" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test "$TRANSPORT_ROUTE_STATE" = expected-transport
run_private_stage "migration-socket" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  python3 - "$TRANSPORT_IPV6" <<'PY'
import socket
import sys

with socket.create_connection((sys.argv[1], 5432), timeout=3):
    print("expected-transport")
PY
run_private_stage "migration-socket" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test "$(<"$MIGRATION_STDOUT_LOG")" = expected-transport

export RDS_CA_BUNDLE
export PGHOST="$DB_HOST"
export PGHOSTADDR="$TRANSPORT_IPV6"
export PGPORT=5432
export PGDATABASE="$DB_NAME"
export PGUSER="$DB_USER"
export PGSSLMODE=verify-full
export PGSSLROOTCERT="$RDS_CA_BUNDLE"
_run_private_stage_emit 'stage=migration-token status=start elapsed=0 exit=0 reason=unclassified'
if DB_TOKEN="$(aws rds generate-db-auth-token \
  --hostname "$PGHOST" --port "$PGPORT" --region us-east-1 --username "$PGUSER" \
  2>"$MIGRATION_STDERR_LOG")"; then
  _run_private_stage_emit 'stage=migration-token status=pass elapsed=0 exit=0 reason=unclassified'
else
  status=$?
  _run_private_stage_emit "stage=migration-token status=fail elapsed=0 exit=$status reason=publisher_failed"
  exit "$status"
fi
export PGPASSWORD="$DB_TOKEN"
unset DB_TOKEN
run_private_stage "migration-runner" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  python3 scripts/run_development_migrations.py
RUNNER_JSON="$(<"$MIGRATION_STDOUT_LOG")"
unset PGPASSWORD

run_private_stage "migration-evidence" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" jq -e \
  --arg commit "$GITHUB_SHA" \
  --arg database "$DB_NAME" \
  --arg user "$DB_USER" \
  --arg pricing_version "$EXPECTED_PRICING_VERSION" \
  --arg oracle_version "$EXPECTED_ORACLE_VERSION" '
  type == "object"
  and (keys_unsorted | sort) == ["after", "applied", "before", "commit", "database", "run_id", "status", "user"]
  and .commit == $commit
  and .database == $database
  and .user == $user
  and .status == "ok"
  and .after == {pricing: $pricing_version, oracle: $oracle_version}
  and (.before | type == "object" and has("pricing") and has("oracle"))
  and (.applied | type == "array" and all(.[]; type == "string" and test("^v2/db/migrations/[0-9]{3}_upgrade_(pricing|oracle)_.*\\.sql$")))
  and ((.before == .after and (.applied | length) == 0)
       or (.before != .after and (.applied | length) > 0))
' <<<"$RUNNER_JSON" >/dev/null

EVIDENCE="$RUNNER_TEMP/v2-development-migrations-evidence.json"
run_private_stage "migration-evidence" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" \
  test ! -e "$EVIDENCE"
run_private_stage "migration-evidence" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" jq -cn \
  --arg commit_sha "$GITHUB_SHA" \
  --arg github_run_id "$GITHUB_RUN_ID" \
  --arg github_run_attempt "$GITHUB_RUN_ATTEMPT" \
  --arg account "$CALLER_ACCOUNT" \
  --arg role "$EXPECTED_ROLE" \
  --arg route "$EXPECTED_ROUTE" \
  --argjson runner "$RUNNER_JSON" \
  '{commit_sha:$commit_sha,github_run_id:$github_run_id,github_run_attempt:$github_run_attempt,account:$account,role:$role,database:$runner.database,user:$runner.user,before:$runner.before,after:$runner.after,applied:$runner.applied,runner_run_id:$runner.run_id,route:$route,route_valid:true,transport_valid:true,status:$runner.status}'
run_private_stage "migration-evidence" "$MIGRATION_CONTROL_LOG" "$MIGRATION_STDERR_LOG" \
  cp -P -- "$MIGRATION_STDOUT_LOG" "$EVIDENCE"
run_private_stage "migration-evidence" "$MIGRATION_CONTROL_LOG" "$MIGRATION_STDERR_LOG" \
  chmod 600 "$EVIDENCE"
run_private_stage "migration-evidence" "$MIGRATION_STDOUT_LOG" "$MIGRATION_STDERR_LOG" jq -e '
  type == "object"
  and (keys_unsorted | sort) == ["account", "after", "applied", "before", "commit_sha", "database", "github_run_attempt", "github_run_id", "role", "route", "route_valid", "runner_run_id", "status", "transport_valid", "user"]
  and .status == "ok" and .route_valid == true and .transport_valid == true
' "$EVIDENCE" >/dev/null
MIGRATION_SUMMARY_LOG="${RUNNER_TEMP}/development-migration-summary.log"
run_private_stage "migration-summary" "$MIGRATION_SUMMARY_LOG" "$MIGRATION_SUMMARY_LOG" \
  jq -r '"## Development migration evidence\n\n```json\n" + tojson + "\n```"' "$EVIDENCE"
if ! cat "$MIGRATION_SUMMARY_LOG" >>"$GITHUB_STEP_SUMMARY"; then
  _run_private_stage_emit 'stage=migration-summary status=fail elapsed=0 exit=125 reason=diagnostic_unavailable'
  exit 125
fi

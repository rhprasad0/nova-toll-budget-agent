#!/usr/bin/env bash
# One-time, separately authorized setup. Never use this as the recurring runner.
set -euo pipefail
set +x

v2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ca_bundle="$v2_root/infra/build/loader/rds-ca-bundle.pem"
trap 'unset PGPASSWORD DB_SECRET DB_ENDPOINT DB_USER' EXIT

test -f "$ca_bundle"
test "$(AWS_PROFILE=nova-toll-prod aws sts get-caller-identity --query Account --output text)" = 920534282028
test "$(AWS_PROFILE=nova-toll-prod aws configure get region)" = us-east-1
instance="$(AWS_PROFILE=nova-toll-prod aws rds describe-db-instances --db-instance-identifier nova-toll-db --region us-east-1 --output json)"
secret_arn="$(jq -er '.DBInstances[0] | select(.DbiResourceId == "db-WHGCQ3B5SB4WPB5RTJMU3CE664" and .PubliclyAccessible == false and .IAMDatabaseAuthenticationEnabled == true) | .MasterUserSecret.SecretArn' <<<"$instance")"
DB_ENDPOINT="$(jq -er '.DBInstances[0].Endpoint.Address' <<<"$instance")"
test "$secret_arn" != None
test -n "$DB_ENDPOINT"
DB_SECRET="$(AWS_PROFILE=nova-toll-prod aws secretsmanager get-secret-value --secret-id "$secret_arn" --query SecretString --output text)"
DB_USER="$(jq -er .username <<<"$DB_SECRET")"
export PGPASSWORD="$(jq -er .password <<<"$DB_SECRET")"
unset DB_SECRET
unset instance secret_arn
PGHOST="$DB_ENDPOINT" PGPORT=5432 PGUSER="$DB_USER" PGDATABASE=postgres \
  PGSSLMODE=verify-full PGSSLROOTCERT="$ca_bundle" \
  psql -X --set ON_ERROR_STOP=1 --file "$v2_root/scripts/bootstrap_oracle_migrators.sql"
for DB_NAME in nova_toll_development nova_toll; do
  PGHOST="$DB_ENDPOINT" PGPORT=5432 PGUSER="$DB_USER" PGDATABASE="$DB_NAME" \
    PGSSLMODE=verify-full PGSSLROOTCERT="$ca_bundle" \
    psql -X --set ON_ERROR_STOP=1 --file "$v2_root/scripts/bootstrap_oracle_migrators.sql"
done

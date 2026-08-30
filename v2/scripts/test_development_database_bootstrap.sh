#!/usr/bin/env bash
set -euo pipefail

if [[ -v NOVA_TOLL_ADMIN_URL ]]; then
  echo 'disposable bootstrap tests refuse NOVA_TOLL_ADMIN_URL' >&2
  exit 2
fi

production_db="nova_toll"
development_db="nova_toll_development"
development_roles=(
  pricing_loader_writer_development pricing_reader_development oracle_owner_development
  tollchat_agent_development pricing_caller_development report_publisher_development
)
login_roles=(
  pricing_loader_writer pricing_reader tollchat_agent pricing_caller report_publisher
  pricing_loader_writer_development pricing_reader_development tollchat_agent_development
  pricing_caller_development report_publisher_development
)

sentinel='VERIFIER_SENTINEL_SECRET'
sentinel_output="$(mktemp)"
trap 'rm -f -- "$sentinel_output"' EXIT
if PGHOST=127.0.0.1 PGPORT=1 PGUSER=ambient PGPASSWORD=ambient \
  NOVA_TOLL_ADMIN_URL="postgresql://review_user:${sentinel}@127.0.0.1:1/postgres" \
  python3 v2/scripts/bootstrap_development_database.py >"$sentinel_output" 2>&1; then
  echo 'bootstrap accepted an unreachable sentinel connection' >&2
  exit 1
fi
if rg --fixed-strings --quiet "$sentinel" "$sentinel_output"; then
  echo 'bootstrap leaked an administrator URL secret' >&2
  exit 1
fi

createdb --template template0 "$development_db"
if python3 v2/scripts/bootstrap_development_database.py; then
  echo "bootstrap accepted a pre-existing development database" >&2
  exit 1
fi
dropdb "$development_db"

psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command 'CREATE ROLE pricing_loader_writer_development'
if python3 v2/scripts/bootstrap_development_database.py; then
  echo "bootstrap accepted a pre-existing development role" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = 'nova_toll_development') THEN
    RAISE EXCEPTION 'failed preflight created the development database';
  END IF;
END $$;
DROP ROLE pricing_loader_writer_development;
SQL

psql --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE bootstrap_unexpected_connect LOGIN;
GRANT CONNECT ON DATABASE nova_toll TO bootstrap_unexpected_connect;
SQL
if python3 v2/scripts/bootstrap_development_database.py; then
  echo "bootstrap accepted an unexpected production CONNECT grantee" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
REVOKE CONNECT ON DATABASE nova_toll FROM bootstrap_unexpected_connect;
DROP ROLE bootstrap_unexpected_connect;
CREATE ROLE bootstrap_unexpected_membership NOLOGIN;
GRANT bootstrap_unexpected_membership TO pricing_reader;
SQL
if python3 v2/scripts/bootstrap_development_database.py; then
  echo "bootstrap accepted an unexpected production membership" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
REVOKE bootstrap_unexpected_membership FROM pricing_reader;
DROP ROLE bootstrap_unexpected_membership;
ALTER ROLE pricing_reader CREATEDB;
SQL
if python3 v2/scripts/bootstrap_development_database.py; then
  echo "bootstrap accepted unsafe production role attributes" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command 'ALTER ROLE pricing_reader NOCREATEDB'

psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command 'REVOKE rds_iam FROM pricing_reader'
if python3 v2/scripts/bootstrap_development_database.py; then
  echo "bootstrap accepted a missing production rds_iam membership" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command 'GRANT rds_iam TO pricing_reader'

python3 v2/scripts/bootstrap_development_database.py
psql --dbname "$development_db" --file v2/tests/development_bootstrap_contract.sql

for role in "${login_roles[@]}"; do
  if [[ "$role" == *_development ]]; then
    own_database="$development_db"
    other_database="$production_db"
  else
    own_database="$production_db"
    other_database="$development_db"
  fi
  psql --username "$role" --dbname "$own_database" --set ON_ERROR_STOP=1 \
    --command 'SELECT current_user' >/dev/null
  if psql --username "$role" --dbname "$other_database" --set ON_ERROR_STOP=1 \
    --command 'SELECT current_user' >/dev/null 2>&1; then
    echo "$role connected to the wrong environment database" >&2
    exit 1
  fi
done

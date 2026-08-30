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
mismatch_container=''
cleanup() {
  [[ -z "$mismatch_container" ]] || docker rm --force "$mismatch_container" >/dev/null
  rm -f -- "$sentinel_output"
}
trap cleanup EXIT
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

if [[ -n "${POSTGRES_CONTAINER_ID:-}" ]]; then
  mismatch_container="$(docker run -d --rm -e POSTGRES_HOST_AUTH_METHOD=trust \
    -p 127.0.0.1::5432 postgis/postgis:17-3.5)"
  for attempt in {1..30}; do
    if docker exec "$mismatch_container" pg_isready --username postgres >/dev/null; then
      break
    fi
    sleep 1
  done
  mismatch_port="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}' "$mismatch_container")"
  interceptors="$(mktemp -d)"
  real_psql="$(command -v psql)"
  trap 'rm -rf -- "$interceptors"; cleanup' EXIT
  printf '%s\n' '#!/usr/bin/env bash' 'echo destructive command reached >&2' 'exit 91' >"$interceptors/dropdb"
  printf '%s\n' '#!/usr/bin/env bash' 'echo destructive command reached >&2' 'exit 91' >"$interceptors/createdb"
  printf '%s\n' '#!/usr/bin/env bash' \
    'case "$*" in *"DROP ROLE"*|*"CREATE ROLE"*|*"CREATE DATABASE"*) echo destructive command reached >&2; exit 91;; esac' \
    "exec $(printf '%q' "$real_psql") \"\$@\"" >"$interceptors/psql"
  chmod +x "$interceptors/dropdb" "$interceptors/createdb" "$interceptors/psql"
  if PATH="$interceptors:$PATH" PGHOST=127.0.0.1 PGPORT="$mismatch_port" PGUSER=postgres \
    v2/scripts/run_db_tests.sh "$(git rev-parse HEAD^)" >"$sentinel_output" 2>&1; then
    echo 'mismatched disposable container was accepted' >&2
    exit 1
  fi
  if rg --fixed-strings --quiet 'destructive command reached' "$sentinel_output"; then
    echo 'mismatched disposable container reached destructive fixture setup' >&2
    exit 1
  fi
  docker rm --force "$mismatch_container" >/dev/null
  mismatch_container=''
  rm -rf -- "$interceptors"
  trap cleanup EXIT
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

bootstrap_state="$(psql --dbname postgres --tuples-only --no-align --command "
SELECT datname || '|' || coalesce(shobj_description(oid, 'pg_database'), '') || '|' || coalesce(array_to_string(datacl, ','), '')
FROM pg_database WHERE datname = '$production_db'
")"
assert_failed_bootstrap_is_clean() {
  local current_state
  current_state="$(psql --dbname postgres --tuples-only --no-align --command "
SELECT datname || '|' || coalesce(shobj_description(oid, 'pg_database'), '') || '|' || coalesce(array_to_string(datacl, ','), '')
FROM pg_database WHERE datname = '$production_db'
")"
  [[ "$current_state" == "$bootstrap_state" ]]
  psql --dbname postgres --set ON_ERROR_STOP=1 --command "
DO \$\$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '$development_db')
     OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = ANY (ARRAY['${development_roles[0]}', '${development_roles[1]}', '${development_roles[2]}', '${development_roles[3]}', '${development_roles[4]}', '${development_roles[5]}'])) THEN
    RAISE EXCEPTION 'failed bootstrap left development artifacts';
  END IF;
END \$\$;"
}

for failure_mode in load finalization; do
  if BOOTSTRAP_FAILURE_MODE="$failure_mode" python3 - <<'PY'
import importlib.util
import os
from pathlib import Path

path = Path("v2/scripts/bootstrap_development_database.py")
spec = importlib.util.spec_from_file_location("bootstrap", path)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
real_psql = bootstrap.psql

def fail_after_create(database, *, sql=None, file=None):
    if os.environ["BOOTSTRAP_FAILURE_MODE"] == "load" and file is not None:
        raise RuntimeError("injected load failure")
    if os.environ["BOOTSTRAP_FAILURE_MODE"] == "finalization" and sql and "COMMENT ON DATABASE nova_toll" in sql:
        sql = sql.replace("COMMIT;", "DO $$ BEGIN RAISE EXCEPTION 'injected finalization failure'; END $$;\nCOMMIT;", 1)
    return real_psql(database, sql=sql, file=file)

bootstrap.psql = fail_after_create
try:
    bootstrap.main()
except (RuntimeError, bootstrap.subprocess.CalledProcessError):
    raise SystemExit(0)
raise SystemExit("bootstrap accepted injected failure")
PY
  then
    assert_failed_bootstrap_is_clean
  else
    echo "bootstrap did not fail during injected $failure_mode failure" >&2
    exit 1
  fi
done

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

#!/usr/bin/env bash
set -euo pipefail

bootstrap_db="nova_toll_v2_bootstrap_test"
production_db="nova_toll"
development_db="nova_toll_development"
retirement_db="nova_toll_v2_retirement_test"
retirement_divergent_db="nova_toll_v2_retirement_divergent_test"
retirement_dependent_db="nova_toll_v2_retirement_dependent_test"
retirement_role_db="nova_toll_v2_retirement_role_test"
migration_db="nova_toll_v2_migration_test"
base_ref="${1:-}"
cleanup_allowed=false
if [[ -z "$base_ref" ]]; then
  echo "usage: $0 BASE_GIT_REF" >&2
  exit 2
fi
require_disposable_cluster() {
  if [[ -z "${POSTGRES_CONTAINER_ID:-}" ]]; then
    echo "POSTGRES_CONTAINER_ID is required for destructive database tests" >&2
    exit 1
  fi
  if [[ "$(docker inspect --format '{{.Config.Image}}' "$POSTGRES_CONTAINER_ID")" != "postgis/postgis:17-3.5" ]]; then
    echo "POSTGRES_CONTAINER_ID is not the expected disposable PostgreSQL service" >&2
    exit 1
  fi
  local container_identifier target_identifier
  target_identifier="$(psql --dbname postgres --tuples-only --no-align --command \
    'SELECT system_identifier FROM pg_control_system()')"
  container_identifier="$(docker exec "$POSTGRES_CONTAINER_ID" \
    psql -X --username postgres --dbname postgres --tuples-only --no-align --command \
    'SELECT system_identifier FROM pg_control_system()')"
  if [[ -z "$target_identifier" || "$target_identifier" != "$container_identifier" ]]; then
    echo "database target does not match POSTGRES_CONTAINER_ID" >&2
    exit 1
  fi
  local databases
  databases="$(psql --dbname postgres --tuples-only --no-align --command \
    'SELECT datname FROM pg_database ORDER BY datname')"
  if [[ "$databases" != $'postgres\ntemplate0\ntemplate1\ntemplate_postgis' ]]; then
    echo "database target is not an empty disposable cluster" >&2
    exit 1
  fi
}

require_disposable_cluster
export NOVA_TOLL_EXPECTED_RDS_ENDPOINT="127.0.0.1"
if [[ "$base_ref" == "0000000000000000000000000000000000000000" ]]; then
  # New tags have no base; migration 026's parent is its declared 1.2.0 source.
  base_ref="$(git log --diff-filter=A --format='%H^' -1 -- \
    v2/db/migrations/026_upgrade_pricing_1_2_0_to_1_3_0.sql)"
fi
retirement_source_ref="$(git log --diff-filter=A --format='%H^' -1 -- \
  v2/db/migrations/026_upgrade_pricing_1_2_0_to_1_3_0.sql)"
migration_source_dir="$(mktemp -d)"
retirement_source_dir="$migration_source_dir/retirement"
mkdir "$retirement_source_dir"
git archive "$retirement_source_ref" v2/db | \
  tar -x --directory "$retirement_source_dir"
oracle_rollback_db="nova_toll_v2_oracle_rollback_test"
missing_pricing_db="nova_toll_v2_oracle_missing_pricing_test"
incompatible_pricing_db="nova_toll_v2_oracle_incompatible_pricing_test"
unsafe_agent_db="nova_toll_v2_oracle_unsafe_agent_test"

cleanup_databases() {
  [[ "$cleanup_allowed" == true ]] || return
  for database in "$bootstrap_db" "$production_db" "$development_db" "$retirement_db" "$migration_db" \
    "$retirement_divergent_db" "$retirement_dependent_db" \
    "$retirement_role_db" \
    "$oracle_rollback_db" "$missing_pricing_db" "$incompatible_pricing_db" \
    "$unsafe_agent_db"; do
    dropdb --if-exists "$database"
  done
  psql --dbname postgres --set ON_ERROR_STOP=1 --command \
    "DROP ROLE IF EXISTS pricing_loader_writer_development, pricing_reader_development, oracle_owner_development, tollchat_agent_development, pricing_caller_development, report_publisher_development, loader_writer"
}

cleanup() {
  cleanup_databases
  rm -rf -- "$migration_source_dir"
}

dump_schema() {
  if [[ -n "${POSTGRES_CONTAINER_ID:-}" ]]; then
    docker exec "$POSTGRES_CONTAINER_ID" \
      pg_dump --username "${PGUSER:-postgres}" "$@"
  else
    pg_dump "$@"
  fi
}

cleanup_allowed=true
trap cleanup EXIT
cleanup_databases

psql --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  CREATE ROLE rds_iam;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
SQL

createdb --template template0 "$development_db"
psql --dbname "$development_db" --set ON_ERROR_STOP=1 \
  --command 'CREATE SCHEMA fresh_preflight_sentinel'
if python3 v2/scripts/bootstrap_development_database.py --fresh-development; then
  echo "fresh bootstrap accepted a non-empty initial database" >&2
  exit 1
fi
dropdb "$development_db"

createdb --template template0 "$development_db"
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command 'CREATE ROLE pricing_reader_development'
if python3 v2/scripts/bootstrap_development_database.py --fresh-development; then
  echo "fresh bootstrap accepted a pre-existing development role" >&2
  exit 1
fi
dropdb "$development_db"
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command 'DROP ROLE pricing_reader_development'

createdb --template template0 "$development_db"
createdb --template template0 "$production_db"
if python3 v2/scripts/bootstrap_development_database.py --fresh-development; then
  echo "fresh bootstrap accepted an existing split-environment cluster" >&2
  exit 1
fi
if psql --dbname "$development_db" --tuples-only --no-align --command \
  "SELECT count(*) FROM pg_namespace WHERE nspname IN ('pricing', 'oracle')" | grep -qx 0; then
  :
else
  echo "fresh ambiguity preflight ran DDL" >&2
  exit 1
fi
dropdb "$development_db"
dropdb "$production_db"

createdb --template template0 "$development_db"
if BOOTSTRAP_FAILURE_MODE=fresh python3 - <<'PY'
import importlib.util
import os
from pathlib import Path

path = Path("v2/scripts/bootstrap_development_database.py")
spec = importlib.util.spec_from_file_location("bootstrap", path)
assert spec and spec.loader
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
real_psql = bootstrap.psql

def fail_after_finalization(database, *, sql=None, file=None, variables=None):
    if os.environ["BOOTSTRAP_FAILURE_MODE"] == "fresh" and sql and "COMMENT ON DATABASE nova_toll_development" in sql and "COMMIT;" in sql:
        sql = sql.replace("COMMIT;", "DO $$ BEGIN RAISE EXCEPTION 'injected fresh failure'; END $$;\nCOMMIT;", 1)
    return real_psql(database, sql=sql, file=file, variables=variables)

bootstrap.psql = fail_after_finalization
try:
    bootstrap.main()
except (RuntimeError, bootstrap.subprocess.CalledProcessError):
    raise SystemExit(0)
raise SystemExit("fresh bootstrap accepted injected failure")
PY
then
  if psql --dbname postgres --tuples-only --no-align --command \
    "SELECT count(*) FROM pg_roles WHERE rolname LIKE '%\\_development' ESCAPE '\\'" | grep -qx 0 &&
    psql --dbname "$development_db" --tuples-only --no-align --command \
    "SELECT count(*) FROM pg_namespace WHERE nspname IN ('pricing', 'oracle')" | grep -qx 0; then
    :
  else
    echo "fresh bootstrap cleanup left development artifacts" >&2
    exit 1
  fi
else
  echo "fresh bootstrap did not fail during injected finalization failure" >&2
  exit 1
fi
dropdb "$development_db"

createdb --template template0 "$development_db"
python3 v2/scripts/bootstrap_development_database.py --fresh-development
psql --dbname "$development_db" --variable fresh_development=1 \
  --file v2/tests/development_bootstrap_contract.sql
if psql --dbname postgres --tuples-only --no-align --command \
  "SELECT count(*) FROM pg_database WHERE datname = '$production_db'" | grep -qx 0 &&
  psql --dbname postgres --tuples-only --no-align --command \
  "SELECT count(*) FROM pg_roles WHERE rolname IN ('pricing_loader_writer', 'pricing_reader', 'oracle_owner', 'tollchat_agent', 'pricing_caller', 'report_publisher')" | grep -qx 0; then
  :
else
  echo "fresh bootstrap touched production state" >&2
  exit 1
fi
dropdb "$development_db"
psql --dbname postgres --set ON_ERROR_STOP=1 --command \
  'DROP ROLE pricing_loader_writer_development, pricing_reader_development, oracle_owner_development, tollchat_agent_development, pricing_caller_development, report_publisher_development'

createdb --template template0 "$production_db"
psql --dbname "$production_db" --file v2/db/schema.sql
psql --dbname "$production_db" --file v2/db/roles.sql
psql --dbname "$production_db" --file v2/db/oracle/schema.sql
url_target="$(python3 - <<'PY'
import os
from urllib.parse import quote

host = os.environ.get("PGHOST", "localhost")
host = f"[{host.strip('[]')}]" if ":" in host else host
port = os.environ.get("PGPORT")
user = quote(os.environ.get("PGUSER", "postgres"), safe="")
password = os.environ.get("PGPASSWORD")
credentials = user if password is None else f"{user}:{quote(password, safe='')}"
print(f"postgresql://{credentials}@{host}{f':{port}' if port else ''}/postgres")
PY
)"
if ! PGHOST=127.0.0.1 PGPORT=1 PGUSER=ambient PGPASSWORD=ambient \
  NOVA_TOLL_ADMIN_URL="$url_target" \
  python3 v2/scripts/bootstrap_development_database.py; then
  echo "bootstrap URL did not override ambient PostgreSQL settings" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'nova_toll_development') THEN
    RAISE EXCEPTION 'bootstrap URL did not create the local development database';
  END IF;
END $$;
SQL
dropdb "$development_db"
psql --dbname postgres --set ON_ERROR_STOP=1 --command \
  "DROP ROLE pricing_loader_writer_development, pricing_reader_development, oracle_owner_development, tollchat_agent_development, pricing_caller_development, report_publisher_development"
if NOVA_TOLL_ADMIN_URL='postgresql://must-not-be-used@127.0.0.1:1/postgres' \
  v2/scripts/test_development_database_bootstrap.sh; then
  echo "disposable bootstrap test accepted NOVA_TOLL_ADMIN_URL" >&2
  exit 1
fi
v2/scripts/test_development_database_bootstrap.sh

createdb --template template0 "$bootstrap_db"
psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql
psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql
psql --dbname "$bootstrap_db" --file v2/tests/restore_contract.sql

if [[ -n "$base_ref" && "$base_ref" != "0000000000000000000000000000000000000000" ]]; then
  git archive "$base_ref" v2/db | tar -x --directory "$migration_source_dir"
  mapfile -t added_migrations < <(
    git diff --diff-filter=A --name-only "$base_ref" -- \
      'v2/db/migrations/*_upgrade_*_*_to_*.sql' | sort
  )

  for migration in "${added_migrations[@]}"; do
    if [[ ! "$migration" =~ ^v2/db/migrations/[0-9]{3}_upgrade_([a-z][a-z0-9_]*)_([0-9]+_[0-9]+_[0-9]+)_to_([0-9]+_[0-9]+_[0-9]+)\.sql$ ]]; then
      echo "invalid schema upgrade migration name: $migration" >&2
      exit 1
    fi
    schema_name="${BASH_REMATCH[1]}"
    previous_version="${BASH_REMATCH[2]}"
    target_version="${BASH_REMATCH[3]}"
    previous_version="${previous_version//_/.}"
    target_version="${target_version//_/.}"

    dropdb --if-exists "$migration_db"
    createdb "$migration_db"
    case "$schema_name" in
      pricing)
        psql --dbname "$migration_db" \
          --file "$migration_source_dir/v2/db/migrations/001_create_pricing_schema.sql"
        psql --dbname "$migration_db" \
          --file "$migration_source_dir/v2/db/migrations/003_create_oracle_schema.sql"
        ;;
      oracle)
        psql --dbname "$migration_db" \
          --file "$migration_source_dir/v2/db/migrations/001_create_pricing_schema.sql"
        psql --dbname "$migration_db" \
          --file "$migration_source_dir/v2/db/migrations/003_create_oracle_schema.sql"
        ;;
      *)
        echo "database CI cannot prepare $schema_name upgrade source" >&2
        exit 1
        ;;
    esac

    for prerequisite in "${added_migrations[@]}"; do
      if [[ "$prerequisite" == "$migration" ]]; then
        break
      fi
      psql --dbname "$migration_db" --file "$prerequisite"
    done

    installed_version="$(
      psql --dbname "$migration_db" --tuples-only --no-align \
        --command "SELECT version FROM $schema_name.schema_version WHERE singleton"
    )"
    if [[ "$installed_version" != "$previous_version" ]]; then
      echo "$migration starts at $installed_version, expected $previous_version" >&2
      exit 1
    fi

    if [[ "$schema_name:$target_version" == "oracle:1.7.1" ]]; then
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
        --command "UPDATE pricing.schema_version SET version = '1.2.1' WHERE singleton"
    fi

    if [[ "$schema_name:$target_version" == "oracle:1.1.1" ]]; then
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 <<'SQL'
UPDATE oracle.toll_connection
SET source_metadata = jsonb_set(
  source_metadata,
  '{source_pair,charges,1,price_peak_usd}',
  '"2.01"'::jsonb
)
WHERE connection_id = 'source:greenway:EB:1:28';
SQL
      if psql --dbname "$migration_db" --file "$migration"; then
        echo "oracle 1.1.1 upgrade accepted malformed Greenway charges" >&2
        exit 1
      fi
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.1.0' THEN
    RAISE EXCEPTION 'failed Greenway migration changed the installed version';
  END IF;
END $$;
UPDATE oracle.toll_connection
SET source_metadata = jsonb_set(
  source_metadata,
  '{source_pair,charges,1,price_peak_usd}',
  '"2.00"'::jsonb
)
WHERE connection_id = 'source:greenway:EB:1:28';
SQL
    fi

    if [[ "$schema_name:$target_version" == "oracle:1.1.2" ]]; then
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 <<'SQL'
UPDATE oracle.toll_connection
SET source_metadata = jsonb_set(
  source_metadata,
  '{source_pair,charges,0,price_peak_usd}',
  '"7.81"'::jsonb
)
WHERE connection_id = 'source:greenway:EB:1:28';
SQL
      if psql --dbname "$migration_db" --file "$migration"; then
        echo "oracle 1.1.2 upgrade accepted malformed Greenway charges" >&2
        exit 1
      fi
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.1.1' THEN
    RAISE EXCEPTION 'failed conditional DTR migration changed the installed version';
  END IF;
END $$;
UPDATE oracle.toll_connection
SET source_metadata = jsonb_set(
  source_metadata,
  '{source_pair,charges,0,price_peak_usd}',
  '"7.80"'::jsonb
)
WHERE connection_id = 'source:greenway:EB:1:28';
SQL
    fi

    if [[ "$schema_name:$target_version" == "oracle:1.8.0" ]]; then
      for runtime_role in tollchat_agent pricing_caller; do
        psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
          --command "GRANT CREATE ON SCHEMA oracle TO $runtime_role"
        if psql --dbname "$migration_db" --file "$migration"; then
          echo "oracle 1.8.0 upgrade accepted unsafe $runtime_role grants" >&2
          exit 1
        fi
        psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
          --variable runtime_role="$runtime_role" <<'SQL'
DO $$
BEGIN
  IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.7.1' THEN
    RAISE EXCEPTION 'failed role validation changed the oracle version';
  END IF;
END $$;
REVOKE CREATE ON SCHEMA oracle FROM :runtime_role;
SQL
      done
    fi

    if [[ "$schema_name:$target_version" == "oracle:1.14.0" ]]; then
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
        --command "UPDATE oracle.schema_version SET version = '1.13.0' WHERE singleton"
      if psql --dbname "$migration_db" --file "$migration"; then
        echo "oracle 1.14.0 upgrade accepted a wrong source version" >&2
        exit 1
      fi
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.13.0' THEN
    RAISE EXCEPTION 'failed oracle 1.14.0 version guard changed the installed version';
  END IF;
END $$;
UPDATE oracle.schema_version SET version = '1.13.1' WHERE singleton;
SQL
    fi

    psql --dbname "$migration_db" --file "$migration"

    installed_version="$(
      psql --dbname "$migration_db" --tuples-only --no-align \
        --command "SELECT version FROM $schema_name.schema_version WHERE singleton"
    )"
    if [[ "$installed_version" != "$target_version" ]]; then
      echo "$migration installed $installed_version, expected $target_version" >&2
      exit 1
    fi

    bootstrap_version="$(
      psql --dbname "$bootstrap_db" --tuples-only --no-align \
        --command "SELECT version FROM $schema_name.schema_version WHERE singleton"
    )"
    if [[ "$target_version" == "$bootstrap_version" ]]; then
      dump_schema --schema-only --schema "$schema_name" --no-owner "$bootstrap_db" | \
        sed -E '/^\\(un)?restrict /d' >"$migration_source_dir/bootstrap.sql"
      dump_schema --schema-only --schema "$schema_name" --no-owner "$migration_db" | \
        sed -E '/^\\(un)?restrict /d' >"$migration_source_dir/migrated.sql"
      diff -u "$migration_source_dir/bootstrap.sql" "$migration_source_dir/migrated.sql"
    fi

    if [[ "$schema_name:$target_version" == "pricing:1.2.0" ]]; then
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
        --command "REVOKE SELECT ON pricing.i66_ballpark_samples FROM oracle_owner"
      if psql --dbname "$migration_db" --file "$migration"; then
        echo "pricing 1.2.0 rerun accepted a missing oracle_owner grant" >&2
        exit 1
      fi
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
        --command "GRANT SELECT ON pricing.i66_ballpark_samples TO oracle_owner"
    fi

    if [[ "$schema_name:$target_version" == "oracle:1.14.0" ]]; then
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
        --command "DELETE FROM oracle.toll_connection WHERE connection_id = 'i495_1829_to_dulles_toll_road'"
      if psql --dbname "$migration_db" --file "$migration"; then
        echo "oracle 1.14.0 rerun repaired a missing handoff" >&2
        exit 1
      fi
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 <<'SQL'
INSERT INTO oracle.toll_connection (
  connection_id, from_point_id, to_point_id, connection_type,
  required_i95_direction, source_route_key, source_metadata
) VALUES (
  'i495_1829_to_dulles_toll_road', 'i495:1829ND', 'dtr:1819:entry:WB',
  'toll_handoff', NULL, NULL,
  '{"basis":"v2/db/oracle/CONTRACT.md","curated":true}'::jsonb
);
UPDATE oracle.toll_connection
SET source_metadata = '{"curated":true}'::jsonb
WHERE connection_id = 'i495_1829_to_dulles_toll_road';
SQL
      if psql --dbname "$migration_db" --file "$migration"; then
        echo "oracle 1.14.0 rerun accepted a corrupt handoff" >&2
        exit 1
      fi
      psql --dbname "$migration_db" --set ON_ERROR_STOP=1 \
        --command "UPDATE oracle.toll_connection SET source_metadata = '{\"basis\":\"v2/db/oracle/CONTRACT.md\",\"curated\":true}'::jsonb WHERE connection_id = 'i495_1829_to_dulles_toll_road'"
    fi

    psql --dbname "$migration_db" --file "$migration"
    installed_version="$(
      psql --dbname "$migration_db" --tuples-only --no-align \
        --command "SELECT version FROM $schema_name.schema_version WHERE singleton"
    )"
    if [[ "$installed_version" != "$target_version" ]]; then
      echo "$migration rerun changed version to $installed_version" >&2
      exit 1
    fi

    if [[ "$schema_name" == "oracle" \
      && "$target_version" == "$bootstrap_version" ]]; then
      for database in "$bootstrap_db" "$migration_db"; do
        psql --dbname "$database" --tuples-only --no-align --command "
          SELECT jsonb_agg(
              jsonb_build_object(
                  'point_id', point_id,
                  'network_id', network_id,
                  'source_node_id', source_node_id,
                  'point_type', point_type,
                  'direction', direction,
                  'label', label,
                  'place_name', place_name,
                  'region', region,
                  'country_code', country_code,
                  'aliases', aliases,
                  'location', oracle.ST_AsGeoJSON(location)::jsonb,
                  'source_metadata', source_metadata
              ) ORDER BY point_id
          )
          FROM oracle.toll_route_point
        " >"$migration_source_dir/$database-points.json"
      done
      diff -u "$migration_source_dir/$bootstrap_db-points.json" \
        "$migration_source_dir/$migration_db-points.json"

      for database in "$bootstrap_db" "$migration_db"; do
        psql --dbname "$database" --tuples-only --no-align --command "
          SELECT jsonb_agg(
              jsonb_build_object(
                  'connection_id', connection_id,
                  'from_point_id', from_point_id,
                  'to_point_id', to_point_id,
                  'connection_type', connection_type,
                  'required_i95_direction', required_i95_direction,
                  'source_route_key', source_route_key,
                  'source_metadata', source_metadata
              ) ORDER BY connection_id
          )
          FROM oracle.toll_connection
        " >"$migration_source_dir/$database-connections.json"
      done
      diff -u "$migration_source_dir/$bootstrap_db-connections.json" \
        "$migration_source_dir/$migration_db-connections.json"
    fi
  done
fi

psql --dbname "$bootstrap_db" --set ON_ERROR_STOP=1 <<'SQL'
UPDATE pricing.schema_version SET version = '1.0.0' WHERE singleton;
SQL
psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql
psql --dbname "$bootstrap_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.0.1' THEN
    RAISE EXCEPTION 'pricing schema upgrade did not install 1.0.1';
  END IF;
END $$;
SQL
psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql
psql --dbname "$bootstrap_db" --set ON_ERROR_STOP=1 <<'SQL'
UPDATE pricing.schema_version SET version = '0.9.0' WHERE singleton;
SQL
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql; then
  echo "schema upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
psql --dbname "$bootstrap_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '0.9.0' THEN
    RAISE EXCEPTION 'failed schema upgrade changed the installed version';
  END IF;
END $$;
UPDATE pricing.schema_version SET version = '1.3.0' WHERE singleton;
SQL
psql --dbname "$bootstrap_db" --file v2/tests/pricing_analysis_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/pricing_ballpark_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/monotonic_upsert_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_restore_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_route_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_prompt_points_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_pricing_route_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_i66_pricing_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_i95_pricing_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_ballpark_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_report_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_security_contract.sql

psql --dbname "$bootstrap_db" --set ON_ERROR_STOP=1 <<'SQL'
UPDATE oracle.schema_version SET version = '0.9.0' WHERE singleton;
SQL
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/007_upgrade_oracle_1_0_2_to_1_1_0.sql; then
  echo "oracle schema upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/008_upgrade_oracle_1_1_0_to_1_1_1.sql; then
  echo "oracle 1.1.1 upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/009_upgrade_oracle_1_1_1_to_1_1_2.sql; then
  echo "oracle 1.1.2 upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/010_upgrade_oracle_1_1_2_to_1_2_0.sql; then
  echo "oracle 1.2.0 upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/011_upgrade_oracle_1_2_0_to_1_3_0.sql; then
  echo "oracle 1.3.0 upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/012_upgrade_oracle_1_3_0_to_1_4_0.sql; then
  echo "oracle 1.4.0 upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/013_upgrade_oracle_1_4_0_to_1_5_0.sql; then
  echo "oracle 1.5.0 upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/016_upgrade_oracle_1_5_0_to_1_6_0.sql; then
  echo "oracle 1.6.0 upgrade unexpectedly accepted version 0.9.0" >&2
  exit 1
fi
psql --dbname "$bootstrap_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '0.9.0' THEN
    RAISE EXCEPTION 'failed oracle schema upgrade changed the installed version';
  END IF;
END $$;
UPDATE oracle.schema_version SET version = '1.6.0' WHERE singleton;
SQL

if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql; then
  echo "bootstrap unexpectedly overwrote an existing pricing schema" >&2
  exit 1
fi

if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql; then
  echo "bootstrap unexpectedly overwrote an existing oracle schema" >&2
  exit 1
fi

prepare_retirement_database() {
  local database="$1"
  createdb --template template0 "$database"
  psql --dbname "$database" --file "$retirement_source_dir/v2/db/schema.sql"
  psql --dbname "$database" --file "$retirement_source_dir/v2/db/roles.sql"
  psql --dbname "$database" --file v2/tests/legacy_public_fixture.sql
}

prepare_retirement_database "$retirement_db"
psql --dbname "$retirement_db" \
  --file v2/db/migrations/026_upgrade_pricing_1_2_0_to_1_3_0.sql
psql --dbname "$retirement_db" --file v2/tests/legacy_retirement_contract.sql
psql --dbname "$retirement_db" \
  --file v2/db/migrations/026_upgrade_pricing_1_2_0_to_1_3_0.sql

prepare_retirement_database "$retirement_divergent_db"
psql --dbname "$retirement_divergent_db" --set ON_ERROR_STOP=1 \
  --command "UPDATE public.trip_pricing_i95 SET zone_toll_rate_usd = 99"
if psql --dbname "$retirement_divergent_db" \
  --file v2/db/migrations/026_upgrade_pricing_1_2_0_to_1_3_0.sql; then
  echo "retirement accepted divergent public pricing" >&2
  exit 1
fi
dropdb "$retirement_divergent_db"
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command "DROP ROLE loader_writer"

prepare_retirement_database "$retirement_dependent_db"
psql --dbname "$retirement_dependent_db" --set ON_ERROR_STOP=1 <<'SQL'
CREATE SCHEMA hostile;
CREATE VIEW hostile.legacy_prices AS SELECT * FROM public.trip_pricing_i95;
SQL
if psql --dbname "$retirement_dependent_db" \
  --file v2/db/migrations/026_upgrade_pricing_1_2_0_to_1_3_0.sql; then
  echo "retirement accepted surviving legacy dependencies" >&2
  exit 1
fi
dropdb "$retirement_dependent_db"
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command "DROP ROLE loader_writer"

prepare_retirement_database "$retirement_role_db"
psql --dbname "$retirement_role_db" --set ON_ERROR_STOP=1 <<'SQL'
CREATE SCHEMA hostile;
CREATE TABLE hostile.keep (id integer PRIMARY KEY);
GRANT SELECT ON hostile.keep TO loader_writer;
SQL
if psql --dbname "$retirement_role_db" \
  --file v2/db/migrations/026_upgrade_pricing_1_2_0_to_1_3_0.sql; then
  echo "retirement accepted a surviving loader_writer grant" >&2
  exit 1
fi

createdb --template template0 "$missing_pricing_db"
if psql --dbname "$missing_pricing_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql; then
  echo "oracle unexpectedly installed without its pricing prerequisite" >&2
  exit 1
fi

createdb --template template0 "$incompatible_pricing_db"
psql --dbname "$incompatible_pricing_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql
psql --dbname "$incompatible_pricing_db" --set ON_ERROR_STOP=1 \
  --command "UPDATE pricing.schema_version SET version = '2.0.0' WHERE singleton"
if psql --dbname "$incompatible_pricing_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql; then
  echo "oracle unexpectedly accepted incompatible pricing 2.0.0" >&2
  exit 1
fi

createdb --template template0 "$oracle_rollback_db"
psql --dbname "$oracle_rollback_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql
psql --dbname "$oracle_rollback_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql

if psql --dbname "$oracle_rollback_db" \
  --file v2/db/migrations/003_create_oracle_schema.rollback.sql; then
  echo "oracle rollback unexpectedly accepted a missing confirmation" >&2
  exit 1
fi

psql --dbname "$oracle_rollback_db" --set drop_oracle_confirmed=yes \
  --file v2/db/migrations/003_create_oracle_schema.rollback.sql
psql --dbname "$oracle_rollback_db" \
  --file v2/tests/oracle_rollback_contract.sql

createdb --template template0 "$unsafe_agent_db"
psql --dbname "$unsafe_agent_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command "GRANT pg_read_all_data TO tollchat_agent"
if psql --dbname "$unsafe_agent_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql; then
  psql --dbname postgres --set ON_ERROR_STOP=1 \
    --command "REVOKE pg_read_all_data FROM tollchat_agent"
  echo "oracle unexpectedly accepted an agent with inherited privileges" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command "REVOKE pg_read_all_data FROM tollchat_agent"

psql --dbname "$unsafe_agent_db" --set ON_ERROR_STOP=1 <<'SQL'
GRANT CREATE ON DATABASE nova_toll_v2_oracle_unsafe_agent_test TO tollchat_agent;
GRANT USAGE ON SCHEMA pricing TO tollchat_agent;
GRANT SELECT ON pricing.current_i95_direction TO tollchat_agent;
SQL
if psql --dbname "$unsafe_agent_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql; then
  echo "oracle unexpectedly accepted an agent with direct privileges" >&2
  exit 1
fi

psql --dbname "$unsafe_agent_db" --set ON_ERROR_STOP=1 <<'SQL'
REVOKE CREATE ON DATABASE nova_toll_v2_oracle_unsafe_agent_test FROM tollchat_agent;
REVOKE USAGE ON SCHEMA pricing FROM tollchat_agent;
REVOKE SELECT ON pricing.current_i95_direction FROM tollchat_agent;
SQL
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command "GRANT pg_read_all_data TO pricing_caller"
if psql --dbname "$unsafe_agent_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql; then
  psql --dbname postgres --set ON_ERROR_STOP=1 \
    --command "REVOKE pg_read_all_data FROM pricing_caller"
  echo "oracle unexpectedly accepted a pricing caller with inherited privileges" >&2
  exit 1
fi
psql --dbname postgres --set ON_ERROR_STOP=1 \
  --command "REVOKE pg_read_all_data FROM pricing_caller"

psql --dbname "$unsafe_agent_db" --set ON_ERROR_STOP=1 <<'SQL'
GRANT CREATE ON DATABASE nova_toll_v2_oracle_unsafe_agent_test TO pricing_caller;
GRANT USAGE ON SCHEMA pricing TO pricing_caller;
GRANT SELECT ON pricing.current_i95_direction TO pricing_caller;
SQL
if psql --dbname "$unsafe_agent_db" \
  --file v2/db/migrations/003_create_oracle_schema.sql; then
  echo "oracle unexpectedly accepted a pricing caller with direct privileges" >&2
  exit 1
fi

#!/usr/bin/env bash
set -euo pipefail

bootstrap_db="nova_toll_v2_bootstrap_test"
backfill_db="nova_toll_v2_backfill_test"
migration_db="nova_toll_v2_migration_test"
migration_source_dir="$(mktemp -d)"
base_ref="${1:-}"
oracle_rollback_db="nova_toll_v2_oracle_rollback_test"
missing_pricing_db="nova_toll_v2_oracle_missing_pricing_test"
incompatible_pricing_db="nova_toll_v2_oracle_incompatible_pricing_test"
unsafe_agent_db="nova_toll_v2_oracle_unsafe_agent_test"

cleanup_databases() {
  for database in "$bootstrap_db" "$backfill_db" "$migration_db" \
    "$oracle_rollback_db" "$missing_pricing_db" "$incompatible_pricing_db" \
    "$unsafe_agent_db"; do
    dropdb --if-exists "$database"
  done
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
      'v2/db/migrations/*_upgrade_*_*_to_*.sql'
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

    installed_version="$(
      psql --dbname "$migration_db" --tuples-only --no-align \
        --command "SELECT version FROM $schema_name.schema_version WHERE singleton"
    )"
    if [[ "$installed_version" != "$previous_version" ]]; then
      echo "$migration starts at $installed_version, expected $previous_version" >&2
      exit 1
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

    dump_schema --schema-only --schema "$schema_name" --no-owner "$bootstrap_db" | \
      sed -E '/^\\(un)?restrict /d' >"$migration_source_dir/bootstrap.sql"
    dump_schema --schema-only --schema "$schema_name" --no-owner "$migration_db" | \
      sed -E '/^\\(un)?restrict /d' >"$migration_source_dir/migrated.sql"
    diff -u "$migration_source_dir/bootstrap.sql" "$migration_source_dir/migrated.sql"

    if [[ "$schema_name" == "oracle" ]]; then
      for database in "$bootstrap_db" "$migration_db"; do
        psql --dbname "$database" --tuples-only --no-align --command "
          SELECT jsonb_agg(
              jsonb_build_object(
                  'point_id', point_id,
                  'location', oracle.ST_AsGeoJSON(location)::jsonb,
                  'source_metadata', source_metadata
              ) ORDER BY point_id
          )
          FROM oracle.toll_route_point
        " >"$migration_source_dir/$database-points.json"
      done
      diff -u "$migration_source_dir/$bootstrap_db-points.json" \
        "$migration_source_dir/$migration_db-points.json"
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
UPDATE pricing.schema_version SET version = '1.0.1' WHERE singleton;
SQL
psql --dbname "$bootstrap_db" --file v2/tests/pricing_analysis_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/monotonic_upsert_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_restore_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_route_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/oracle_security_contract.sql

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

createdb --template template0 "$backfill_db"
psql --dbname "$backfill_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql
psql --dbname "$backfill_db" --file v2/tests/public_source_fixture.sql
psql --dbname "$backfill_db" --file v2/tests/backfill_contract.sql

psql --dbname "$backfill_db" --set ON_ERROR_STOP=1 <<'SQL'
UPDATE pricing.trip_pricing_i95
SET calculated_at = calculated_at + interval '1 minute',
    zone_toll_rate_usd = zone_toll_rate_usd + 1,
    s3_key = 'raw/feed=i95/date=2026-08-16/1210Z.csv';
SQL
if psql --dbname "$backfill_db" --file v2/db/migrations/backfill.sql; then
  echo "backfill unexpectedly regressed a newer pricing row" >&2
  exit 1
fi
psql --dbname "$backfill_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pricing.trip_pricing_i95
    WHERE calculated_at = '2026-08-16 11:59:00+00'
      AND zone_toll_rate_usd = 8.10
      AND s3_key = 'raw/feed=i95/date=2026-08-16/1210Z.csv'
  ) THEN
    RAISE EXCEPTION 'failed backfill changed the newer pricing row';
  END IF;
END $$;

UPDATE pricing.trip_pricing_i95 AS pricing_row
SET calculated_at = public_row.calculated_at,
    zone_toll_rate_usd = public_row.zone_toll_rate_usd,
    s3_key = public_row.s3_key
FROM public.trip_pricing_i95 AS public_row
WHERE pricing_row.interval_end_at = public_row.interval_end_at
  AND pricing_row.start_zone_id = public_row.start_zone_id
  AND pricing_row.end_zone_id = public_row.end_zone_id
  AND pricing_row.od_pair_id = public_row.od_pair_id;
SQL

if psql --dbname "$backfill_db" \
  --file v2/db/migrations/001_create_pricing_schema.rollback.sql; then
  echo "rollback unexpectedly accepted a missing confirmation" >&2
  exit 1
fi

psql --dbname "$backfill_db" --set drop_pricing_confirmed=yes \
  --file v2/db/migrations/001_create_pricing_schema.rollback.sql
psql --dbname "$backfill_db" --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF to_regnamespace('pricing') IS NOT NULL
     OR to_regclass('public.trip_pricing_i95') IS NULL
     OR to_regclass('public.trip_pricing_i66') IS NULL
     OR to_regclass('public.trip_pricing') IS NULL
     OR to_regclass('public.trip_pricing_i95_live') IS NULL THEN
    RAISE EXCEPTION 'cleanup did not preserve the public generation';
  END IF;
END $$;
SQL

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
psql --dbname "$oracle_rollback_db" --file v2/tests/public_source_fixture.sql
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

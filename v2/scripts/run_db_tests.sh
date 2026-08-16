#!/usr/bin/env bash
set -euo pipefail

bootstrap_db="nova_toll_v2_bootstrap_test"
backfill_db="nova_toll_v2_backfill_test"

cleanup() {
  dropdb --if-exists "$bootstrap_db"
  dropdb --if-exists "$backfill_db"
}
trap cleanup EXIT
cleanup

psql --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  CREATE ROLE rds_iam;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
SQL

createdb "$bootstrap_db"
psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql
psql --dbname "$bootstrap_db" --file v2/tests/restore_contract.sql
psql --dbname "$bootstrap_db" --file v2/tests/pricing_analysis_contract.sql

if psql --dbname "$bootstrap_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql; then
  echo "bootstrap unexpectedly overwrote an existing pricing schema" >&2
  exit 1
fi

createdb "$backfill_db"
psql --dbname "$backfill_db" \
  --file v2/db/migrations/001_create_pricing_schema.sql
psql --dbname "$backfill_db" --file v2/tests/public_source_fixture.sql
psql --dbname "$backfill_db" --file v2/tests/backfill_contract.sql

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

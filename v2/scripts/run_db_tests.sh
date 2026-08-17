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

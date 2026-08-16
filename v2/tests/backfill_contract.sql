\set ON_ERROR_STOP on

-- Simulate the shadow loader winning a duplicate race with a distinct local
-- ingestion timestamp. Backfill must remain idempotent and reconcile source
-- fields without treating the two independent clocks as drift.
INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key, ingested_at
)
SELECT
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key,
    ingested_at + interval '1 second'
FROM public.trip_pricing_i95;

\ir ../db/migrations/backfill.sql

DO $$
BEGIN
    IF (SELECT count(*) FROM pricing.trip_pricing_i95) <> 1
       OR (SELECT count(*) FROM pricing.trip_pricing_i66) <> 1
       OR (SELECT count(*) FROM pricing.backfill_state) <> 2 THEN
        RAISE EXCEPTION 'backfill did not copy both feeds exactly once';
    END IF;

    IF to_regclass('public.trip_pricing') IS NULL
       OR to_regclass('public.trip_pricing_i95_live') IS NULL
       OR to_regclass('public.trip_pricing_id_seq') IS NULL THEN
        RAISE EXCEPTION 'backfill changed a legacy v1 object';
    END IF;

    IF NOT has_table_privilege(
        'pricing_loader_writer', 'public.trip_pricing', 'SELECT,INSERT,UPDATE'
    ) THEN
        RAISE EXCEPTION 'backfill changed a legacy v1 grant';
    END IF;
END $$;

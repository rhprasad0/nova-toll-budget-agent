-- Online, resumable history copy from deployed v1 public tables into pricing.
-- Run only after the v2 shadow loader has processed a current object per feed.

\set ON_ERROR_STOP on

BEGIN ISOLATION LEVEL REPEATABLE READ;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30min';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-pricing-backfill-i95'));

INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key, ingested_at
)
SELECT
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key, ingested_at
FROM public.trip_pricing_i95
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
DO UPDATE SET
    current_at = EXCLUDED.current_at,
    calculated_at = EXCLUDED.calculated_at,
    corridor_id = EXCLUDED.corridor_id,
    corridor_name = EXCLUDED.corridor_name,
    od_pair_name = EXCLUDED.od_pair_name,
    start_zone_name = EXCLUDED.start_zone_name,
    end_zone_name = EXCLUDED.end_zone_name,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    link_status = EXCLUDED.link_status,
    s3_key = EXCLUDED.s3_key,
    ingested_at = LEAST(pricing.trip_pricing_i95.ingested_at, EXCLUDED.ingested_at);

DO $$
BEGIN
    IF EXISTS (
        (SELECT
            interval_end_at, current_at, calculated_at, corridor_id,
            corridor_name, od_pair_id, od_pair_name, start_zone_id,
            start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
            link_status, s3_key
         FROM public.trip_pricing_i95
         EXCEPT
         SELECT
            interval_end_at, current_at, calculated_at, corridor_id,
            corridor_name, od_pair_id, od_pair_name, start_zone_id,
            start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
            link_status, s3_key
         FROM pricing.trip_pricing_i95)
        UNION ALL
        (SELECT
            interval_end_at, current_at, calculated_at, corridor_id,
            corridor_name, od_pair_id, od_pair_name, start_zone_id,
            start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
            link_status, s3_key
         FROM pricing.trip_pricing_i95
         EXCEPT
         SELECT
            interval_end_at, current_at, calculated_at, corridor_id,
            corridor_name, od_pair_id, od_pair_name, start_zone_id,
            start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
            link_status, s3_key
         FROM public.trip_pricing_i95)
    ) THEN
        RAISE EXCEPTION 'I-95 pricing backfill differs from public source';
    END IF;
END $$;

INSERT INTO pricing.backfill_state (
    feed, completed_at, public_row_count, pricing_row_count
)
SELECT
    'i95', now(),
    (SELECT count(*) FROM public.trip_pricing_i95),
    (SELECT count(*) FROM pricing.trip_pricing_i95)
ON CONFLICT (feed) DO UPDATE SET
    completed_at = EXCLUDED.completed_at,
    public_row_count = EXCLUDED.public_row_count,
    pricing_row_count = EXCLUDED.pricing_row_count;

COMMIT;

BEGIN ISOLATION LEVEL REPEATABLE READ;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30min';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-pricing-backfill-i66'));

INSERT INTO pricing.trip_pricing_i66 (
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, s3_key, ingested_at
)
SELECT
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, s3_key, ingested_at
FROM public.trip_pricing_i66
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id)
DO UPDATE SET
    interval_start_at = EXCLUDED.interval_start_at,
    calculated_at = EXCLUDED.calculated_at,
    corridor_id = EXCLUDED.corridor_id,
    corridor_name = EXCLUDED.corridor_name,
    start_zone_name = EXCLUDED.start_zone_name,
    end_zone_name = EXCLUDED.end_zone_name,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    s3_key = EXCLUDED.s3_key,
    ingested_at = LEAST(pricing.trip_pricing_i66.ingested_at, EXCLUDED.ingested_at);

DO $$
BEGIN
    IF EXISTS (
        (SELECT
            interval_start_at, interval_end_at, calculated_at, corridor_id,
            corridor_name, start_zone_id, start_zone_name, end_zone_id,
            end_zone_name, zone_toll_rate_usd, s3_key
         FROM public.trip_pricing_i66
         EXCEPT
         SELECT
            interval_start_at, interval_end_at, calculated_at, corridor_id,
            corridor_name, start_zone_id, start_zone_name, end_zone_id,
            end_zone_name, zone_toll_rate_usd, s3_key
         FROM pricing.trip_pricing_i66)
        UNION ALL
        (SELECT
            interval_start_at, interval_end_at, calculated_at, corridor_id,
            corridor_name, start_zone_id, start_zone_name, end_zone_id,
            end_zone_name, zone_toll_rate_usd, s3_key
         FROM pricing.trip_pricing_i66
         EXCEPT
         SELECT
            interval_start_at, interval_end_at, calculated_at, corridor_id,
            corridor_name, start_zone_id, start_zone_name, end_zone_id,
            end_zone_name, zone_toll_rate_usd, s3_key
         FROM public.trip_pricing_i66)
    ) THEN
        RAISE EXCEPTION 'I-66 pricing backfill differs from public source';
    END IF;
END $$;

INSERT INTO pricing.backfill_state (
    feed, completed_at, public_row_count, pricing_row_count
)
SELECT
    'i66', now(),
    (SELECT count(*) FROM public.trip_pricing_i66),
    (SELECT count(*) FROM pricing.trip_pricing_i66)
ON CONFLICT (feed) DO UPDATE SET
    completed_at = EXCLUDED.completed_at,
    public_row_count = EXCLUDED.public_row_count,
    pricing_row_count = EXCLUDED.pricing_row_count;

COMMIT;

ANALYZE pricing.trip_pricing_i95;
ANALYZE pricing.trip_pricing_i66;

\ir verify_backfill.sql

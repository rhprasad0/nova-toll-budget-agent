-- Retire the completed legacy public pricing generation.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30min';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-pricing-schema-version'));

DO $migration$
DECLARE
    current_version text;
BEGIN
    SELECT version INTO STRICT current_version
    FROM pricing.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.2.0', '1.3.0') THEN
        RAISE EXCEPTION 'expected pricing schema version 1.2.0 or 1.3.0, got %',
            current_version;
    END IF;
END
$migration$;

SELECT version = '1.2.0' AS pricing_upgrade_needed
FROM pricing.schema_version
WHERE singleton
\gset

\if :pricing_upgrade_needed

DO $migration$
DECLARE
    legacy_rows_missing boolean;
BEGIN
    IF to_regclass('public.trip_pricing_i95') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE pricing.trip_pricing_i95 AS current_row
            SET s3_key = legacy_row.s3_key,
                ingested_at = LEAST(current_row.ingested_at, legacy_row.ingested_at)
            FROM public.trip_pricing_i95 AS legacy_row
            WHERE (current_row.interval_end_at, current_row.start_zone_id,
                   current_row.end_zone_id, current_row.od_pair_id)
                = (legacy_row.interval_end_at, legacy_row.start_zone_id,
                   legacy_row.end_zone_id, legacy_row.od_pair_id)
              AND (current_row.current_at, current_row.calculated_at,
                   current_row.corridor_id, current_row.corridor_name,
                   current_row.od_pair_name, current_row.start_zone_name,
                   current_row.end_zone_name, current_row.zone_toll_rate_usd,
                   current_row.link_status)
                  IS NOT DISTINCT FROM
                  (legacy_row.current_at, legacy_row.calculated_at,
                   legacy_row.corridor_id, legacy_row.corridor_name,
                   legacy_row.od_pair_name, legacy_row.start_zone_name,
                   legacy_row.end_zone_name, legacy_row.zone_toll_rate_usd,
                   legacy_row.link_status)
              AND current_row.s3_key <> legacy_row.s3_key
        $query$;
        EXECUTE $query$
            SELECT EXISTS (
                SELECT
                    interval_end_at, current_at, calculated_at, corridor_id,
                    corridor_name, od_pair_id, od_pair_name, start_zone_id,
                    start_zone_name, end_zone_id, end_zone_name,
                    zone_toll_rate_usd, link_status, s3_key
                FROM public.trip_pricing_i95
                EXCEPT
                SELECT
                    interval_end_at, current_at, calculated_at, corridor_id,
                    corridor_name, od_pair_id, od_pair_name, start_zone_id,
                    start_zone_name, end_zone_id, end_zone_name,
                    zone_toll_rate_usd, link_status, s3_key
                FROM pricing.trip_pricing_i95
            )
        $query$ INTO legacy_rows_missing;
        IF legacy_rows_missing THEN
            RAISE EXCEPTION 'public I-95 pricing contains rows absent from pricing';
        END IF;
    END IF;

    IF to_regclass('public.trip_pricing_i66') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE pricing.trip_pricing_i66 AS current_row
            SET s3_key = legacy_row.s3_key,
                ingested_at = LEAST(current_row.ingested_at, legacy_row.ingested_at)
            FROM public.trip_pricing_i66 AS legacy_row
            WHERE (current_row.interval_end_at, current_row.start_zone_id,
                   current_row.end_zone_id)
                = (legacy_row.interval_end_at, legacy_row.start_zone_id,
                   legacy_row.end_zone_id)
              AND (current_row.interval_start_at, current_row.calculated_at,
                   current_row.corridor_id, current_row.corridor_name,
                   current_row.start_zone_name, current_row.end_zone_name,
                   current_row.zone_toll_rate_usd)
                  IS NOT DISTINCT FROM
                  (legacy_row.interval_start_at, legacy_row.calculated_at,
                   legacy_row.corridor_id, legacy_row.corridor_name,
                   legacy_row.start_zone_name, legacy_row.end_zone_name,
                   legacy_row.zone_toll_rate_usd)
              AND current_row.s3_key <> legacy_row.s3_key
        $query$;
        EXECUTE $query$
            SELECT EXISTS (
                SELECT
                    interval_start_at, interval_end_at, calculated_at,
                    corridor_id, corridor_name, start_zone_id, start_zone_name,
                    end_zone_id, end_zone_name, zone_toll_rate_usd, s3_key
                FROM public.trip_pricing_i66
                EXCEPT
                SELECT
                    interval_start_at, interval_end_at, calculated_at,
                    corridor_id, corridor_name, start_zone_id, start_zone_name,
                    end_zone_id, end_zone_name, zone_toll_rate_usd, s3_key
                FROM pricing.trip_pricing_i66
            )
        $query$ INTO legacy_rows_missing;
        IF legacy_rows_missing THEN
            RAISE EXCEPTION 'public I-66 pricing contains rows absent from pricing';
        END IF;
    END IF;
END
$migration$;

DROP VIEW IF EXISTS public.current_trip_pricing_i95;
DROP VIEW IF EXISTS public.current_trip_pricing_i66;
DROP TABLE IF EXISTS public.trip_pricing_i95;
DROP TABLE IF EXISTS public.trip_pricing_i66;
DROP TABLE IF EXISTS public.trip_pricing_i95_live;
DROP TABLE IF EXISTS public.trip_pricing;
DROP SEQUENCE IF EXISTS public.trip_pricing_id_seq;
DROP TABLE pricing.backfill_state;

SELECT to_regrole('loader_writer') IS NOT NULL AS loader_writer_exists
\gset
\if :loader_writer_exists
REVOKE rds_iam FROM loader_writer;
DROP ROLE loader_writer;
\endif

UPDATE pricing.schema_version
SET version = '1.3.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.2.0';

\endif

DO $migration$
BEGIN
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0'
       OR to_regclass('pricing.backfill_state') IS NOT NULL
       OR to_regrole('loader_writer') IS NOT NULL THEN
        RAISE EXCEPTION 'pricing 1.3.0 retirement is not installed';
    END IF;
END
$migration$;

COMMIT;

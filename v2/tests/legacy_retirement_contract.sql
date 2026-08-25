\set ON_ERROR_STOP on

DO $$
BEGIN
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0'
       OR to_regclass('pricing.backfill_state') IS NOT NULL
       OR to_regclass('public.trip_pricing') IS NOT NULL
       OR to_regclass('public.trip_pricing_i95') IS NOT NULL
       OR to_regclass('public.trip_pricing_i66') IS NOT NULL
       OR to_regclass('public.trip_pricing_i95_live') IS NOT NULL
       OR to_regclass('public.current_trip_pricing_i95') IS NOT NULL
       OR to_regclass('public.current_trip_pricing_i66') IS NOT NULL
       OR to_regclass('public.trip_pricing_id_seq') IS NOT NULL
       OR to_regrole('loader_writer') IS NOT NULL THEN
        RAISE EXCEPTION 'legacy pricing retirement is incomplete';
    END IF;

    IF to_regrole('pricing_reader') IS NULL
       OR NOT has_schema_privilege('pricing_reader', 'pricing', 'USAGE') THEN
        RAISE EXCEPTION 'v2 pricing reader was not preserved';
    END IF;

    IF (SELECT s3_key FROM pricing.trip_pricing_i95 LIMIT 1)
           <> 'raw/legacy/i95.csv'
       OR (SELECT s3_key FROM pricing.trip_pricing_i66 LIMIT 1)
           <> 'raw/legacy/i66.xml' THEN
        RAISE EXCEPTION 'legacy source provenance was not preserved';
    END IF;
END $$;

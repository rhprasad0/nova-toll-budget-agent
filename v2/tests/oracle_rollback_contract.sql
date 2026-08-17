\set ON_ERROR_STOP on

DO $$
BEGIN
    IF to_regnamespace('oracle') IS NOT NULL
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'postgis')
       OR to_regnamespace('pricing') IS NULL
       OR to_regclass('pricing.current_i95_direction') IS NULL
       OR to_regclass('public.trip_pricing_i95') IS NULL
       OR to_regclass('public.trip_pricing') IS NULL THEN
        RAISE EXCEPTION 'oracle rollback damaged retained database objects';
    END IF;
END $$;

-- TollChat v2 IAM-authenticated pricing roles. Run as the database owner
-- after db/schema.sql.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;

DO $$
BEGIN
    CREATE ROLE pricing_loader_writer WITH LOGIN;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE ROLE pricing_reader WITH LOGIN;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

GRANT rds_iam TO pricing_loader_writer, pricing_reader;
GRANT USAGE ON SCHEMA pricing TO pricing_loader_writer, pricing_reader;

GRANT SELECT, INSERT, UPDATE ON
    pricing.trip_pricing_i95,
    pricing.trip_pricing_i66
TO pricing_loader_writer;

GRANT SELECT ON
    pricing.schema_version,
    pricing.trip_pricing_i95,
    pricing.trip_pricing_i66,
    pricing.current_trip_pricing_i95,
    pricing.current_trip_pricing_i66,
    pricing.current_i95_direction,
    pricing.i95_modeled_od_proxy,
    pricing.modeled_trip_pricing_i95,
    pricing.modeled_current_trip_pricing_i95,
    pricing.i66_pricing_comparisons,
    pricing.i95_i495_pricing_comparisons,
    pricing.i66_ballpark_samples,
    pricing.i95_i495_ballpark_samples
TO pricing_reader;

ALTER ROLE pricing_reader SET TimeZone TO 'America/New_York';

COMMIT;

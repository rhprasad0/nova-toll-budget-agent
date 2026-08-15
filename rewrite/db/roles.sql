-- TollChat rewrite PostgreSQL roles. Run after db/schema.sql on AWS RDS.

\set ON_ERROR_STOP on

BEGIN;

CREATE ROLE loader_writer WITH LOGIN;
GRANT rds_iam TO loader_writer;
GRANT SELECT, INSERT, UPDATE ON trip_pricing_i95, trip_pricing_i66
    TO loader_writer;

CREATE ROLE pricing_reader WITH LOGIN;
GRANT rds_iam TO pricing_reader;
GRANT SELECT ON trip_pricing_i95, trip_pricing_i66 TO pricing_reader;
GRANT SELECT ON
    current_trip_pricing_i95,
    current_trip_pricing_i66,
    i95_modeled_od_proxy,
    modeled_trip_pricing_i95,
    modeled_current_trip_pricing_i95
TO pricing_reader;
ALTER ROLE pricing_reader SET TimeZone TO 'America/New_York';

COMMIT;

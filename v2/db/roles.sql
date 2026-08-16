-- TollChat rewrite PostgreSQL roles. Run after db/schema.sql on AWS RDS.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = public, pg_catalog, pg_temp;

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
    current_i95_direction,
    i95_modeled_od_proxy,
    modeled_trip_pricing_i95,
    modeled_current_trip_pricing_i95,
    dynamic_pricing_observations
TO pricing_reader;
REVOKE ALL ON FUNCTION _dynamic_pricing_component_errors(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION
    point_in_time_dynamic_route_pricing(timestamptz, jsonb),
    historical_dynamic_route_pricing(timestamptz, jsonb)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    _dynamic_pricing_component_errors(jsonb),
    point_in_time_dynamic_route_pricing(timestamptz, jsonb),
    historical_dynamic_route_pricing(timestamptz, jsonb)
TO pricing_reader;
ALTER ROLE pricing_reader SET TimeZone TO 'America/New_York';

COMMIT;

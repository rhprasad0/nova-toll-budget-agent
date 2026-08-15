-- Additive production migration for an existing TollChat PostgreSQL database.
\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = public, pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

\ir ../analysis.sql

GRANT SELECT ON
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

COMMIT;

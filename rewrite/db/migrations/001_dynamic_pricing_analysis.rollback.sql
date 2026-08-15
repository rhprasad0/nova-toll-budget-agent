-- Remove only the analysis surfaces introduced by 001_dynamic_pricing_analysis.sql.
\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = public, pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

DROP FUNCTION IF EXISTS historical_dynamic_route_pricing(timestamptz, jsonb);
DROP FUNCTION IF EXISTS point_in_time_dynamic_route_pricing(timestamptz, jsonb);
DROP FUNCTION IF EXISTS _dynamic_pricing_component_errors(jsonb);
DROP VIEW IF EXISTS dynamic_pricing_observations;

COMMIT;

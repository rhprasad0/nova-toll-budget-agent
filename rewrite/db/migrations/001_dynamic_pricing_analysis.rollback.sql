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
DROP VIEW modeled_trip_pricing_i95;

CREATE VIEW modeled_trip_pricing_i95 AS
SELECT
    p.target_od_pair_id AS od_pair_id,
    v.corridor_name,
    CASE WHEN v.link_status = p.required_status THEN v.zone_toll_rate_usd END
        AS zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    v.link_status,
    p.proxy_od_pair_id,
    true AS modeled,
    'identity_proxy_v1'::text AS pricing_method
FROM i95_modeled_od_proxy p
JOIN trip_pricing_i95 v ON v.od_pair_id = p.proxy_od_pair_id;

COMMENT ON VIEW modeled_trip_pricing_i95 IS
    'Direction-compatible historical ballpark prices for oracle-only I-95 OD IDs';
GRANT SELECT ON modeled_trip_pricing_i95 TO pricing_reader;

COMMIT;

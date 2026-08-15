-- Reconstruct the analysis interfaces changed between schema 1.1 and 1.2.
-- Run after the current blank bootstrap in a disposable migration-test database.
\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = public, pg_catalog, pg_temp;

DROP FUNCTION historical_dynamic_route_pricing(timestamptz, jsonb);
DROP FUNCTION point_in_time_dynamic_route_pricing(timestamptz, jsonb);
DROP FUNCTION _dynamic_pricing_component_errors(jsonb);
DROP VIEW dynamic_pricing_observations;
DROP VIEW modeled_current_trip_pricing_i95;
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

CREATE VIEW modeled_current_trip_pricing_i95 AS
SELECT
    p.target_od_pair_id AS od_pair_id,
    v.corridor_name,
    v.zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    v.link_status,
    p.proxy_od_pair_id,
    true AS modeled,
    'identity_proxy_v1'::text AS pricing_method
FROM i95_modeled_od_proxy p
JOIN current_trip_pricing_i95 v
 ON v.od_pair_id = p.proxy_od_pair_id
 AND v.link_status = p.required_status;

GRANT SELECT, INSERT, UPDATE ON trip_pricing_i95, trip_pricing_i66
TO loader_writer;
GRANT SELECT ON
    trip_pricing_i95,
    trip_pricing_i66,
    current_trip_pricing_i95,
    current_trip_pricing_i66,
    current_i95_direction,
    i95_modeled_od_proxy,
    modeled_trip_pricing_i95,
    modeled_current_trip_pricing_i95
TO pricing_reader;

COMMIT;

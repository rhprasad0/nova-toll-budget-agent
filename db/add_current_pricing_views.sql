-- Current VDOT-price views and Eastern-time agent sessions (schema 4.1.0).
--
-- APPLIED 2026-07-28. Historical one-shot; new databases use db/schema.sql
-- followed by db/roles.sql. Do not run this as routine setup.
--
-- Normal views always run this latest-row query at read time. Do not replace
-- them with materialized views: their refresh cadence would add price lag.

\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE VIEW current_trip_pricing_i95 AS
SELECT DISTINCT ON (od_pair_id)
    od_pair_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at,
    link_status
FROM trip_pricing_i95
ORDER BY od_pair_id, interval_end_at DESC;

CREATE OR REPLACE VIEW current_trip_pricing_i66 AS
SELECT DISTINCT ON (start_zone_id, end_zone_id)
    start_zone_id,
    end_zone_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at
FROM trip_pricing_i66
ORDER BY start_zone_id, end_zone_id, interval_end_at DESC;

GRANT SELECT ON current_trip_pricing_i95, current_trip_pricing_i66 TO pricing_reader;
REVOKE SELECT ON trip_pricing_i95_live FROM pricing_reader;
ALTER ROLE pricing_reader SET TimeZone TO 'America/New_York';

COMMIT;

-- Current VDOT-price views and Eastern-time agent sessions (schema 4.1.0).
--
-- Run as the RDS master after db/add_pricing_read_indexes.sql and BEFORE
-- deploying route tools that query these views by default:
--
--     psql -v ON_ERROR_STOP=1 "$NOVA_TOLL_URL" -f db/add_current_pricing_views.sql
--     uv run pytest -m live tests/test_ci_current_pricing_views.py -v
--
-- The old route tools remain compatible after this migration. Do not deploy
-- the new tool code until the reader-role verification passes.
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

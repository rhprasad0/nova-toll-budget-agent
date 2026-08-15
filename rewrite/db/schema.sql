-- TollChat rewrite PostgreSQL bootstrap.
-- schema version: 1.1.0

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE trip_pricing_i95 (
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer NOT NULL,
    od_pair_name       text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
);

CREATE TABLE trip_pricing_i66 (
    interval_start_at  timestamptz NOT NULL,
    interval_end_at    timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id)
);

-- A blank restore has no traffic, so ordinary index creation is atomic with
-- the rest of the schema. Online upgrades can use CONCURRENTLY when needed.
CREATE INDEX trip_pricing_i95_od_lookup_idx
    ON trip_pricing_i95 (od_pair_id, interval_end_at DESC);

CREATE INDEX trip_pricing_i66_zone_lookup_idx
    ON trip_pricing_i66 (start_zone_id, end_zone_id, interval_end_at DESC);

CREATE VIEW current_trip_pricing_i95 AS
SELECT DISTINCT ON (od_pair_id)
    od_pair_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at,
    link_status
FROM trip_pricing_i95
ORDER BY
    od_pair_id,
    interval_end_at DESC,
    calculated_at DESC,
    start_zone_id,
    end_zone_id;

CREATE VIEW current_trip_pricing_i66 AS
SELECT DISTINCT ON (start_zone_id, end_zone_id)
    start_zone_id,
    end_zone_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at
FROM trip_pricing_i66
ORDER BY start_zone_id, end_zone_id, interval_end_at DESC, calculated_at DESC;

CREATE VIEW current_i95_direction AS
WITH sources AS (
    SELECT
        max(corridor_name) FILTER (WHERE od_pair_id = 1132)
            AS northbound_corridor_name,
        max(link_status) FILTER (WHERE od_pair_id = 1132)
            AS northbound_link_status,
        max(interval_end_at) FILTER (WHERE od_pair_id = 1132)
            AS northbound_interval_end_at,
        max(calculated_at) FILTER (WHERE od_pair_id = 1132)
            AS northbound_calculated_at,
        max(corridor_name) FILTER (WHERE od_pair_id = 1151)
            AS southbound_corridor_name,
        max(link_status) FILTER (WHERE od_pair_id = 1151)
            AS southbound_link_status,
        max(interval_end_at) FILTER (WHERE od_pair_id = 1151)
            AS southbound_interval_end_at,
        max(calculated_at) FILTER (WHERE od_pair_id = 1151)
            AS southbound_calculated_at
    FROM current_trip_pricing_i95
    WHERE od_pair_id IN (1132, 1151)
), classified AS (
    SELECT
        sources.*,
        CASE
            WHEN northbound_interval_end_at IS NULL
              OR southbound_interval_end_at IS NULL
                THEN 'missing_source'
            WHEN northbound_corridor_name <> 'I-95-NB'
              OR southbound_corridor_name <> 'I-95-SB'
                THEN 'invalid_source'
            WHEN northbound_interval_end_at <> southbound_interval_end_at
                THEN 'interval_mismatch'
            WHEN (northbound_link_status = 'NORTHBOUND_OPEN')
              <> (southbound_link_status = 'SOUTHBOUND_OPEN')
                THEN 'available'
            ELSE 'indeterminate'
        END AS direction_state
    FROM sources
)
SELECT
    CASE
        WHEN direction_state = 'available'
         AND northbound_link_status = 'NORTHBOUND_OPEN'
            THEN 'Northbound'
        WHEN direction_state = 'available'
            THEN 'Southbound'
    END AS direction,
    direction_state,
    CASE
        WHEN direction_state = 'available' THEN northbound_interval_end_at
    END AS interval_end_at,
    northbound_corridor_name,
    northbound_link_status,
    northbound_interval_end_at,
    northbound_calculated_at,
    southbound_corridor_name,
    southbound_link_status,
    southbound_interval_end_at,
    southbound_calculated_at
FROM classified;

-- These oracle OD products never appear in VDOT history. Retained Transurban
-- overlap established the direction-compatible VDOT proxy for each product.
CREATE VIEW i95_modeled_od_proxy AS
SELECT *
FROM (
    VALUES
        (1374, 1146, 'NORTHBOUND_OPEN'),
        (1375, 1263, 'NORTHBOUND_OPEN'),
        (1376, 1264, 'NORTHBOUND_OPEN'),
        (1377, 1265, 'NORTHBOUND_OPEN'),
        (1378, 1158, 'SOUTHBOUND_OPEN'),
        (1379, 1159, 'SOUTHBOUND_OPEN'),
        (1380, 1160, 'SOUTHBOUND_OPEN'),
        (1381, 1161, 'SOUTHBOUND_OPEN'),
        (1382, 1162, 'SOUTHBOUND_OPEN'),
        (1383, 1163, 'SOUTHBOUND_OPEN'),
        (1384, 1164, 'SOUTHBOUND_OPEN'),
        (1385, 1165, 'SOUTHBOUND_OPEN'),
        (1386, 1166, 'SOUTHBOUND_OPEN'),
        (1387, 1167, 'SOUTHBOUND_OPEN'),
        (1388, 1288, 'SOUTHBOUND_OPEN'),
        (1389, 1315, 'SOUTHBOUND_OPEN')
) AS proxy (target_od_pair_id, proxy_od_pair_id, required_status);

CREATE VIEW modeled_trip_pricing_i95 AS
SELECT
    p.target_od_pair_id AS od_pair_id,
    v.corridor_name,
    CASE
        WHEN v.link_status = p.required_status THEN v.zone_toll_rate_usd
    END AS zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    v.link_status,
    p.proxy_od_pair_id,
    true AS modeled,
    'identity_proxy_v1'::text AS pricing_method
FROM i95_modeled_od_proxy p
JOIN trip_pricing_i95 v
  ON v.od_pair_id = p.proxy_od_pair_id;

-- Keep status-incompatible observations visible with a null price. Historical
-- callers must select the latest row in their slot before testing completeness,
-- so a newer closure cannot expose an older open toll.

-- Join the already-selected latest VDOT rows before checking direction. This
-- prevents a closed latest row from falling back to an older open price.
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

COMMENT ON VIEW i95_modeled_od_proxy IS
    'Validated VDOT proxy products for 16 I-95 oracle OD IDs absent from VDOT history';
COMMENT ON VIEW modeled_trip_pricing_i95 IS
    'Direction-compatible historical ballpark prices for oracle-only I-95 OD IDs';
COMMENT ON VIEW modeled_current_trip_pricing_i95 IS
    'Direction-compatible current ballpark prices for oracle-only I-95 OD IDs';
COMMENT ON VIEW current_i95_direction IS
    'Latest known I-95 reversible direction from OD 1132/1151, with fail-safe diagnostic state';

COMMIT;

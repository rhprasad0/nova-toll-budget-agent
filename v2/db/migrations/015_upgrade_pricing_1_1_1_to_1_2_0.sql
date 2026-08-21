-- Add bounded 12-week toll ballpark sample views.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-pricing-schema-version'));

DO $migration$
DECLARE
    current_version text;
BEGIN
    SELECT version INTO STRICT current_version
    FROM pricing.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.1.1', '1.2.0') THEN
        RAISE EXCEPTION 'expected pricing schema version 1.1.1 or 1.2.0, got %',
            current_version;
    END IF;
    IF to_regclass('pricing.trip_pricing_i66') IS NULL
       OR to_regclass('pricing.trip_pricing_i95') IS NULL
       OR to_regclass('pricing.modeled_trip_pricing_i95') IS NULL
       OR to_regrole('pricing_reader') IS NULL
       OR to_regrole('oracle_owner') IS NULL THEN
        RAISE EXCEPTION 'pricing 1.2.0 prerequisites are not ready';
    END IF;
END
$migration$;

SELECT version = '1.1.1' AS pricing_upgrade_needed
FROM pricing.schema_version
WHERE singleton
\gset

\if :pricing_upgrade_needed

CREATE OR REPLACE VIEW pricing.i66_ballpark_samples AS
SELECT
    (v.interval_end_at AT TIME ZONE 'America/New_York')::date AS sample_date,
    extract(isodow FROM v.interval_end_at AT TIME ZONE 'America/New_York')::integer
        AS sample_isodow,
    date_bin(
        interval '6 minutes',
        v.interval_end_at,
        timestamptz '2000-01-01 00:00:00+00'
    ) AS bin_start_at,
    date_bin(
        interval '6 minutes',
        v.interval_end_at,
        timestamptz '2000-01-01 00:00:00+00'
    ) + interval '6 minutes' AS bin_end_at,
    v.interval_end_at,
    v.calculated_at AS observed_at,
    v.start_zone_id,
    v.end_zone_id,
    v.zone_toll_rate_usd AS price_usd,
    false AS uses_modeled,
    'source_observation'::text AS pricing_method
FROM pricing.trip_pricing_i66 AS v
WHERE (v.interval_end_at AT TIME ZONE 'America/New_York')::date
      BETWEEN (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 84
          AND (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 1
  AND v.interval_end_at <= transaction_timestamp()
  AND v.calculated_at <= transaction_timestamp();

CREATE OR REPLACE VIEW pricing.i95_i495_ballpark_samples AS
WITH requested_window AS (
    SELECT
        transaction_timestamp() AS evaluated_at,
        (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 84
            AS start_date,
        (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 1
            AS end_date
), direction_status AS NOT MATERIALIZED (
    SELECT
        v.interval_end_at,
        CASE
            WHEN min(v.link_status) FILTER (WHERE v.od_pair_id = 1132)
                    = 'NORTHBOUND_OPEN'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1132)
                    = 'NORTHBOUND_OPEN'
             AND min(v.link_status) FILTER (WHERE v.od_pair_id = 1151) = 'CLOSED'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1151) = 'CLOSED'
                THEN 'NORTHBOUND_OPEN'
            WHEN min(v.link_status) FILTER (WHERE v.od_pair_id = 1132) = 'CLOSED'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1132) = 'CLOSED'
             AND min(v.link_status) FILTER (WHERE v.od_pair_id = 1151)
                    = 'SOUTHBOUND_OPEN'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1151)
                    = 'SOUTHBOUND_OPEN'
                THEN 'SOUTHBOUND_OPEN'
        END AS observed_direction
    FROM pricing.trip_pricing_i95 AS v
    CROSS JOIN requested_window AS w
    WHERE v.od_pair_id IN (1132, 1151)
      AND (v.interval_end_at AT TIME ZONE 'America/New_York')::date
          BETWEEN w.start_date AND w.end_date
      AND v.interval_end_at <= w.evaluated_at
      AND v.calculated_at <= w.evaluated_at
    GROUP BY v.interval_end_at
), source_rows AS (
    SELECT
        v.interval_end_at,
        v.calculated_at AS observed_at,
        v.od_pair_id,
        v.corridor_name,
        v.zone_toll_rate_usd AS price_usd,
        false AS uses_modeled,
        'source_observation'::text AS pricing_method,
        NULL::integer AS proxy_od_pair_id,
        v.start_zone_id AS source_start_zone_id,
        v.end_zone_id AS source_end_zone_id,
        v.link_status AS source_status,
        CASE
            WHEN v.corridor_name = 'I-95-NB' THEN 'NORTHBOUND_OPEN'
            WHEN v.corridor_name = 'I-95-SB' THEN 'SOUTHBOUND_OPEN'
        END AS required_direction
    FROM pricing.trip_pricing_i95 AS v
    CROSS JOIN requested_window AS w
    WHERE v.corridor_name IN ('I-95-NB', 'I-95-SB', 'I-495-NB', 'I-495-SB')
      AND (v.interval_end_at AT TIME ZONE 'America/New_York')::date
          BETWEEN w.start_date AND w.end_date
      AND v.interval_end_at <= w.evaluated_at
      AND v.calculated_at <= w.evaluated_at

    UNION ALL

    SELECT
        v.interval_end_at,
        v.calculated_at,
        v.od_pair_id,
        v.corridor_name,
        v.zone_toll_rate_usd,
        true,
        v.pricing_method,
        v.proxy_od_pair_id,
        v.start_zone_id,
        v.end_zone_id,
        v.link_status,
        p.required_status
    FROM pricing.modeled_trip_pricing_i95 AS v
    JOIN pricing.i95_modeled_od_proxy AS p
      ON p.target_od_pair_id = v.od_pair_id
    CROSS JOIN requested_window AS w
    WHERE (v.interval_end_at AT TIME ZONE 'America/New_York')::date
          BETWEEN w.start_date AND w.end_date
      AND v.interval_end_at <= w.evaluated_at
      AND v.calculated_at <= w.evaluated_at
      AND v.zone_toll_rate_usd IS NOT NULL
), classified AS (
    SELECT
        source_rows.*,
        direction_status.observed_direction,
        CASE
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') = 1
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time < time '10:00'
                THEN 'NORTHBOUND_OPEN'
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') = 1
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time >= time '12:00'
                THEN 'SOUTHBOUND_OPEN'
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') BETWEEN 2 AND 5
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time < time '01:00'
                THEN 'SOUTHBOUND_OPEN'
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') BETWEEN 2 AND 5
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time >= time '02:30'
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time < time '10:00'
                THEN 'NORTHBOUND_OPEN'
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') BETWEEN 2 AND 5
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time >= time '12:00'
                THEN 'SOUTHBOUND_OPEN'
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') = 6
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time < time '14:00'
                THEN 'SOUTHBOUND_OPEN'
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') = 6
             AND (interval_end_at AT TIME ZONE 'America/New_York')::time >= time '16:00'
                THEN 'NORTHBOUND_OPEN'
            WHEN extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York') = 7
                THEN 'NORTHBOUND_OPEN'
        END AS canonical_direction
    FROM source_rows
    LEFT JOIN direction_status USING (interval_end_at)
)
SELECT
    (interval_end_at AT TIME ZONE 'America/New_York')::date AS sample_date,
    extract(isodow FROM interval_end_at AT TIME ZONE 'America/New_York')::integer
        AS sample_isodow,
    date_bin(
        interval '10 minutes', interval_end_at,
        timestamptz '2000-01-01 00:00:00+00'
    ) AS bin_start_at,
    date_bin(
        interval '10 minutes', interval_end_at,
        timestamptz '2000-01-01 00:00:00+00'
    ) + interval '10 minutes' AS bin_end_at,
    interval_end_at,
    observed_at,
    od_pair_id,
    price_usd,
    uses_modeled,
    pricing_method,
    proxy_od_pair_id,
    source_start_zone_id,
    source_end_zone_id
FROM classified
WHERE corridor_name IN ('I-495-NB', 'I-495-SB')
   OR (
       required_direction = canonical_direction
       AND required_direction = observed_direction
       AND (uses_modeled OR source_status = required_direction)
   );

COMMENT ON VIEW pricing.i66_ballpark_samples IS
    'Observed I-66 component prices from the latest 84 completed Eastern dates';
COMMENT ON VIEW pricing.i95_i495_ballpark_samples IS
    'Usable observed and provisional modeled I-95/I-495 component prices from the latest 84 completed Eastern dates';

GRANT SELECT ON
    pricing.i66_ballpark_samples,
    pricing.i95_i495_ballpark_samples
TO pricing_reader;

GRANT SELECT ON
    pricing.i66_ballpark_samples,
    pricing.i95_i495_ballpark_samples
TO oracle_owner;

UPDATE pricing.schema_version
SET version = '1.2.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.1.1';

\endif

DO $migration$
BEGIN
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.2.0'
       OR to_regclass('pricing.i66_ballpark_samples') IS NULL
       OR to_regclass('pricing.i95_i495_ballpark_samples') IS NULL
       OR NOT has_table_privilege(
           'pricing_reader', 'pricing.i66_ballpark_samples', 'SELECT'
       )
       OR NOT has_table_privilege(
           'pricing_reader', 'pricing.i95_i495_ballpark_samples', 'SELECT'
       )
       OR NOT has_table_privilege(
           'oracle_owner', 'pricing.i66_ballpark_samples', 'SELECT'
       )
       OR NOT has_table_privilege(
           'oracle_owner', 'pricing.i95_i495_ballpark_samples', 'SELECT'
       ) THEN
        RAISE EXCEPTION 'pricing 1.2.0 is not installed';
    END IF;
END
$migration$;

COMMIT;

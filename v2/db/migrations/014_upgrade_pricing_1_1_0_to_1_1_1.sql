-- Preserve explicit diagnostics for exceptional I-95 operating schedules.

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

    IF current_version NOT IN ('1.1.0', '1.1.1') THEN
        RAISE EXCEPTION 'expected pricing schema version 1.1.0 or 1.1.1, got %',
            current_version;
    END IF;
    IF to_regclass('pricing.i95_i495_pricing_comparisons') IS NULL
       OR to_regrole('pricing_reader') IS NULL THEN
        RAISE EXCEPTION 'pricing 1.1.1 prerequisites are not ready';
    END IF;
END
$migration$;

SELECT version = '1.1.0' AS pricing_upgrade_needed
FROM pricing.schema_version
WHERE singleton
\gset

\if :pricing_upgrade_needed

CREATE OR REPLACE VIEW pricing.i95_i495_pricing_comparisons AS
WITH params AS (
    SELECT statement_timestamp() AS evaluated_at
), anchor AS (
    SELECT
        params.evaluated_at,
        (
            SELECT v.interval_end_at
            FROM pricing.trip_pricing_i95 v
            WHERE v.corridor_name IN ('I-95-NB', 'I-95-SB', 'I-495-NB', 'I-495-SB')
              AND v.interval_end_at <= params.evaluated_at
              AND v.calculated_at <= params.evaluated_at
            ORDER BY v.interval_end_at DESC
            LIMIT 1
        ) AS anchor_interval_end_at
    FROM params
), anchor_bin AS (
    SELECT
        evaluated_at,
        anchor_interval_end_at,
        date_bin(
            interval '10 minutes',
            anchor_interval_end_at,
            timestamptz '2000-01-01 00:00:00+00'
        ) AS anchor_bin_start_at
    FROM anchor
), raw_targets AS (
    SELECT
        'current'::text AS comparison_kind,
        0 AS comparison_offset,
        anchor_bin.*,
        anchor_bin_start_at AS bin_start_at
    FROM anchor_bin
    UNION ALL
    SELECT
        'prior_cycle',
        offset_number,
        anchor_bin.*,
        anchor_bin_start_at - make_interval(mins => 10 * offset_number)
    FROM anchor_bin
    CROSS JOIN generate_series(1, 2) AS offsets(offset_number)
    UNION ALL
    SELECT
        'prior_week',
        offset_number,
        anchor_bin.*,
        (
            (anchor_bin_start_at AT TIME ZONE 'America/New_York')
            - make_interval(days => 7 * offset_number)
        ) AT TIME ZONE 'America/New_York'
    FROM anchor_bin
    CROSS JOIN generate_series(1, 3) AS offsets(offset_number)
), targets AS (
    SELECT
        raw_targets.*,
        bin_start_at AS comparison_at,
        bin_start_at + interval '10 minutes' AS bin_end_at
    FROM raw_targets
    WHERE comparison_kind <> 'prior_week'
       OR bin_start_at AT TIME ZONE 'America/New_York'
          = (anchor_bin_start_at AT TIME ZONE 'America/New_York')
            - make_interval(days => 7 * comparison_offset)
), direction_status AS NOT MATERIALIZED (
    SELECT
        v.interval_end_at,
        CASE
            WHEN min(v.link_status) FILTER (WHERE v.od_pair_id = 1132) = 'NORTHBOUND_OPEN'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1132) = 'NORTHBOUND_OPEN'
             AND min(v.link_status) FILTER (WHERE v.od_pair_id = 1151) = 'CLOSED'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1151) = 'CLOSED'
                THEN 'NORTHBOUND_OPEN'
            WHEN min(v.link_status) FILTER (WHERE v.od_pair_id = 1132) = 'CLOSED'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1132) = 'CLOSED'
             AND min(v.link_status) FILTER (WHERE v.od_pair_id = 1151) = 'SOUTHBOUND_OPEN'
             AND max(v.link_status) FILTER (WHERE v.od_pair_id = 1151) = 'SOUTHBOUND_OPEN'
                THEN 'SOUTHBOUND_OPEN'
        END AS observed_direction
    FROM pricing.trip_pricing_i95 v
    JOIN targets t
      ON v.interval_end_at >= t.bin_start_at
     AND v.interval_end_at < t.bin_end_at
     AND v.interval_end_at <= t.evaluated_at
     AND v.calculated_at <= t.evaluated_at
    WHERE v.od_pair_id IN (1132, 1151)
    GROUP BY v.interval_end_at
), source_rows AS (
    SELECT
        t.evaluated_at,
        t.comparison_kind,
        t.comparison_offset,
        t.anchor_interval_end_at,
        t.comparison_at,
        t.bin_start_at,
        t.bin_end_at,
        'i95_observed'::text AS price_source,
        'observed'::text AS source_kind,
        v.od_pair_id,
        v.corridor_name,
        v.zone_toll_rate_usd AS price_usd,
        v.interval_end_at,
        v.calculated_at AS observed_at,
        v.link_status AS source_status,
        'source_observation'::text AS pricing_method,
        NULL::integer AS proxy_od_pair_id,
        v.start_zone_id AS source_start_zone_id,
        v.end_zone_id AS source_end_zone_id,
        CASE
            WHEN v.corridor_name = 'I-95-NB' THEN 'NORTHBOUND_OPEN'
            WHEN v.corridor_name = 'I-95-SB' THEN 'SOUTHBOUND_OPEN'
        END AS required_direction
    FROM targets t
    JOIN pricing.trip_pricing_i95 v
      ON v.interval_end_at >= t.bin_start_at
     AND v.interval_end_at < t.bin_end_at
     AND v.interval_end_at <= t.evaluated_at
     AND v.calculated_at <= t.evaluated_at
    WHERE v.corridor_name IN ('I-95-NB', 'I-95-SB', 'I-495-NB', 'I-495-SB')
    UNION ALL
    SELECT
        t.evaluated_at,
        t.comparison_kind,
        t.comparison_offset,
        t.anchor_interval_end_at,
        t.comparison_at,
        t.bin_start_at,
        t.bin_end_at,
        'i95_modeled',
        'modeled',
        v.od_pair_id,
        v.corridor_name,
        v.zone_toll_rate_usd,
        v.interval_end_at,
        v.calculated_at,
        v.link_status,
        v.pricing_method,
        v.proxy_od_pair_id,
        v.start_zone_id,
        v.end_zone_id,
        p.required_status
    FROM targets t
    JOIN pricing.modeled_trip_pricing_i95 v
      ON v.interval_end_at >= t.bin_start_at
     AND v.interval_end_at < t.bin_end_at
     AND v.interval_end_at <= t.evaluated_at
     AND v.calculated_at <= t.evaluated_at
    JOIN pricing.i95_modeled_od_proxy p ON p.target_od_pair_id = v.od_pair_id
), classified_source_rows AS NOT MATERIALIZED (
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
), candidates AS (
    SELECT
        v.*,
        row_number() OVER (
            PARTITION BY v.price_source, v.od_pair_id,
                         v.comparison_kind, v.comparison_offset
            ORDER BY v.interval_end_at DESC, v.observed_at DESC,
                     v.source_start_zone_id, v.source_end_zone_id
        ) AS candidate_rank
    FROM classified_source_rows v
), selected AS (
    SELECT *
    FROM candidates
    WHERE candidate_rank = 1
      AND (
          corridor_name IN ('I-495-NB', 'I-495-SB')
          OR (required_direction = canonical_direction AND required_direction = observed_direction)
          OR (
              comparison_kind = 'current'
              AND observed_direction IS NOT NULL
              AND observed_direction IS DISTINCT FROM canonical_direction
          )
      )
)
SELECT
    evaluated_at,
    'i95_i495'::text AS facility,
    price_source,
    source_kind,
    comparison_kind,
    comparison_offset,
    anchor_interval_end_at,
    comparison_at,
    bin_start_at,
    bin_end_at,
    interval_end_at,
    observed_at,
    od_pair_id,
    NULL::integer AS start_zone_id,
    NULL::integer AS end_zone_id,
    corridor_name,
    price_usd,
    CASE
        WHEN comparison_kind = 'current'
         AND corridor_name IN ('I-95-NB', 'I-95-SB')
         AND observed_direction IS NOT NULL
         AND observed_direction IS DISTINCT FROM canonical_direction THEN false
        WHEN source_kind = 'modeled' AND price_usd IS NULL THEN false
        WHEN source_kind = 'observed'
         AND corridor_name = 'I-95-NB'
         AND source_status <> 'NORTHBOUND_OPEN' THEN false
        WHEN source_kind = 'observed'
         AND corridor_name = 'I-95-SB'
         AND source_status <> 'SOUTHBOUND_OPEN' THEN false
        WHEN comparison_kind = 'current'
         AND evaluated_at - observed_at > interval '30 minutes' THEN false
        ELSE true
    END AS available,
    CASE
        WHEN comparison_kind = 'current'
         AND corridor_name IN ('I-95-NB', 'I-95-SB')
         AND observed_direction IS NOT NULL
         AND observed_direction IS DISTINCT FROM canonical_direction
            THEN 'exceptional_i95_schedule'
        WHEN source_kind = 'modeled' AND price_usd IS NULL THEN 'facility_unavailable'
        WHEN source_kind = 'observed'
         AND corridor_name = 'I-95-NB'
         AND source_status <> 'NORTHBOUND_OPEN' THEN 'facility_unavailable'
        WHEN source_kind = 'observed'
         AND corridor_name = 'I-95-SB'
         AND source_status <> 'SOUTHBOUND_OPEN' THEN 'facility_unavailable'
        WHEN comparison_kind = 'current'
         AND evaluated_at - observed_at > interval '30 minutes' THEN 'stale_observation'
    END AS availability_reason,
    source_status,
    pricing_method,
    proxy_od_pair_id,
    source_start_zone_id,
    source_end_zone_id
FROM selected;

COMMENT ON VIEW pricing.i95_i495_pricing_comparisons IS
    'Current, two prior-cycle, and three prior-week I-95/I-495 observations in 10-minute bins with canonical I-95 schedule enforcement';

GRANT SELECT ON pricing.i95_i495_pricing_comparisons TO pricing_reader;

UPDATE pricing.schema_version
SET version = '1.1.1', installed_at = clock_timestamp()
WHERE singleton AND version = '1.1.0';

\endif

DO $migration$
BEGIN
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.1.1'
       OR position(
            'exceptional_i95_schedule'
            IN pg_get_viewdef('pricing.i95_i495_pricing_comparisons'::regclass)
          ) = 0
       OR NOT has_table_privilege(
            'pricing_reader', 'pricing.i95_i495_pricing_comparisons', 'SELECT'
          ) THEN
        RAISE EXCEPTION 'pricing 1.1.1 exceptional-schedule contract is not installed';
    END IF;
END
$migration$;

COMMIT;

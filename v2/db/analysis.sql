-- Shared dynamic-pricing analysis surfaces. Included by the blank bootstrap
-- and the additive online migration after the raw tables/current views exist.

CREATE OR REPLACE VIEW pricing.current_i95_direction AS
WITH sources AS (
    SELECT
        max(corridor_name) FILTER (WHERE od_pair_id = 1132) AS northbound_corridor_name,
        max(link_status) FILTER (WHERE od_pair_id = 1132) AS northbound_link_status,
        max(interval_end_at) FILTER (WHERE od_pair_id = 1132) AS northbound_interval_end_at,
        max(calculated_at) FILTER (WHERE od_pair_id = 1132) AS northbound_calculated_at,
        max(corridor_name) FILTER (WHERE od_pair_id = 1151) AS southbound_corridor_name,
        max(link_status) FILTER (WHERE od_pair_id = 1151) AS southbound_link_status,
        max(interval_end_at) FILTER (WHERE od_pair_id = 1151) AS southbound_interval_end_at,
        max(calculated_at) FILTER (WHERE od_pair_id = 1151) AS southbound_calculated_at
    FROM pricing.current_trip_pricing_i95
    WHERE od_pair_id IN (1132, 1151)
), classified AS (
    SELECT
        sources.*,
        CASE
            WHEN northbound_interval_end_at IS NULL OR southbound_interval_end_at IS NULL
                THEN 'missing_source'
            WHEN northbound_corridor_name <> 'I-95-NB' OR southbound_corridor_name <> 'I-95-SB'
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
        WHEN direction_state = 'available' AND northbound_link_status = 'NORTHBOUND_OPEN'
            THEN 'Northbound'
        WHEN direction_state = 'available' THEN 'Southbound'
    END AS direction,
    direction_state,
    CASE WHEN direction_state = 'available' THEN northbound_interval_end_at END AS interval_end_at,
    northbound_corridor_name,
    northbound_link_status,
    northbound_interval_end_at,
    northbound_calculated_at,
    southbound_corridor_name,
    southbound_link_status,
    southbound_interval_end_at,
    southbound_calculated_at
FROM classified;

CREATE OR REPLACE VIEW pricing.i95_modeled_od_proxy AS
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

CREATE OR REPLACE VIEW pricing.modeled_trip_pricing_i95 AS
SELECT
    p.target_od_pair_id AS od_pair_id,
    v.corridor_name,
    CASE WHEN v.link_status = p.required_status THEN v.zone_toll_rate_usd END AS zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    v.link_status,
    p.proxy_od_pair_id,
    true AS modeled,
    'identity_proxy_v1'::text AS pricing_method,
    v.start_zone_id,
    v.end_zone_id
FROM pricing.i95_modeled_od_proxy p
JOIN pricing.trip_pricing_i95 v ON v.od_pair_id = p.proxy_od_pair_id;

CREATE OR REPLACE VIEW pricing.modeled_current_trip_pricing_i95 AS
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
FROM pricing.i95_modeled_od_proxy p
JOIN pricing.current_trip_pricing_i95 v
  ON v.od_pair_id = p.proxy_od_pair_id
 AND v.link_status = p.required_status;

CREATE OR REPLACE VIEW pricing.i66_pricing_comparisons AS
WITH params AS (
    SELECT statement_timestamp() AS evaluated_at
), anchor AS (
    SELECT
        params.evaluated_at,
        (
            SELECT max(v.interval_end_at)
            FROM pricing.trip_pricing_i66 v
            WHERE v.interval_end_at <= params.evaluated_at
              AND v.calculated_at <= params.evaluated_at
        ) AS anchor_interval_end_at
    FROM params
), anchor_bin AS (
    SELECT
        evaluated_at,
        anchor_interval_end_at,
        date_bin(
            interval '6 minutes',
            anchor_interval_end_at,
            timestamptz '2000-01-01 00:00:00+00'
        ) AS anchor_bin_start_at
    FROM anchor
), raw_targets AS (
    SELECT
        'current'::text AS comparison_kind,
        0 AS comparison_offset,
        anchor_bin.*,
        anchor_bin_start_at AS local_target,
        anchor_bin_start_at AS bin_start_at
    FROM anchor_bin
    UNION ALL
    SELECT
        'prior_cycle',
        offset_number,
        anchor_bin.*,
        anchor_bin_start_at - make_interval(mins => 6 * offset_number),
        anchor_bin_start_at - make_interval(mins => 6 * offset_number)
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
        ) AT TIME ZONE 'America/New_York',
        (
            (anchor_bin_start_at AT TIME ZONE 'America/New_York')
            - make_interval(days => 7 * offset_number)
        ) AT TIME ZONE 'America/New_York'
    FROM anchor_bin
    CROSS JOIN generate_series(1, 3) AS offsets(offset_number)
), targets AS (
    SELECT
        raw_targets.*,
        bin_start_at + interval '6 minutes' AS bin_end_at
    FROM raw_targets
    WHERE comparison_kind <> 'prior_week'
       OR bin_start_at AT TIME ZONE 'America/New_York'
          = (anchor_bin_start_at AT TIME ZONE 'America/New_York')
            - make_interval(days => 7 * comparison_offset)
), candidates AS (
    SELECT
        t.evaluated_at,
        t.comparison_kind,
        t.comparison_offset,
        t.anchor_interval_end_at,
        t.bin_start_at AS comparison_at,
        t.bin_start_at,
        t.bin_end_at,
        v.*,
        row_number() OVER (
            PARTITION BY v.start_zone_id, v.end_zone_id,
                         t.comparison_kind, t.comparison_offset
            ORDER BY v.interval_end_at DESC, v.calculated_at DESC
        ) AS candidate_rank
    FROM targets t
    JOIN pricing.trip_pricing_i66 v
      ON v.interval_end_at >= t.bin_start_at
     AND v.interval_end_at < t.bin_end_at
     AND v.interval_end_at <= t.evaluated_at
     AND v.calculated_at <= t.evaluated_at
)
SELECT
    evaluated_at,
    'i66'::text AS facility,
    'i66_observed'::text AS price_source,
    'observed'::text AS source_kind,
    comparison_kind,
    comparison_offset,
    anchor_interval_end_at,
    comparison_at,
    bin_start_at,
    bin_end_at,
    interval_end_at,
    calculated_at AS observed_at,
    NULL::integer AS od_pair_id,
    start_zone_id,
    end_zone_id,
    corridor_name,
    zone_toll_rate_usd AS price_usd,
    NOT (
        comparison_kind = 'current'
        AND evaluated_at - calculated_at > interval '30 minutes'
    ) AS available,
    CASE
        WHEN comparison_kind = 'current'
         AND evaluated_at - calculated_at > interval '30 minutes'
            THEN 'stale_observation'
    END AS availability_reason,
    NULL::text AS source_status,
    'source_observation'::text AS pricing_method,
    NULL::integer AS proxy_od_pair_id,
    start_zone_id AS source_start_zone_id,
    end_zone_id AS source_end_zone_id
FROM candidates
WHERE candidate_rank = 1;

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

COMMENT ON VIEW pricing.i95_modeled_od_proxy IS
    'Validated VDOT proxy products for 16 I-95 oracle OD IDs absent from VDOT history';
COMMENT ON VIEW pricing.modeled_trip_pricing_i95 IS
    'Direction-compatible historical ballpark prices for oracle-only I-95 OD IDs';
COMMENT ON VIEW pricing.modeled_current_trip_pricing_i95 IS
    'Direction-compatible current ballpark prices for oracle-only I-95 OD IDs';
COMMENT ON VIEW pricing.current_i95_direction IS
    'Latest known I-95 reversible direction from OD 1132/1151, with fail-safe diagnostic state';
COMMENT ON VIEW pricing.i66_pricing_comparisons IS
    'Current, two prior-cycle, and three prior-week I-66 observations in independent 6-minute bins';
COMMENT ON VIEW pricing.i95_i495_pricing_comparisons IS
    'Current, two prior-cycle, and three prior-week I-95/I-495 observations in 10-minute bins with canonical I-95 schedule enforcement';
COMMENT ON VIEW pricing.i66_ballpark_samples IS
    'Observed I-66 component prices from the latest 84 completed Eastern dates';
COMMENT ON VIEW pricing.i95_i495_ballpark_samples IS
    'Usable observed and provisional modeled I-95/I-495 component prices from the latest 84 completed Eastern dates';

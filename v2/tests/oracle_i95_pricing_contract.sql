\set ON_ERROR_STOP on

BEGIN;

TRUNCATE pricing.trip_pricing_i95;

WITH params AS (
    SELECT date_bin(
        interval '10 minutes',
        statement_timestamp() - interval '5 minutes',
        timestamptz '2000-01-01 00:00:00+00'
    ) AS anchor_bin_start
), observations AS (
    SELECT 0 AS comparison_offset, anchor_bin_start AS bin_start, 8.20 AS price
    FROM params
    UNION ALL
    SELECT offset_number,
           anchor_bin_start - make_interval(mins => 10 * offset_number),
           8.20 - offset_number
    FROM params
    CROSS JOIN generate_series(1, 2) AS offset_number
    UNION ALL
    SELECT 10 + offset_number,
           (
               (anchor_bin_start AT TIME ZONE 'America/New_York')
               - make_interval(days => 7 * offset_number)
           ) AT TIME ZONE 'America/New_York',
           6.00 - offset_number
    FROM params
    CROSS JOIN generate_series(1, 3) AS offset_number
)
INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id,
    corridor_name, od_pair_id, od_pair_name, start_zone_id,
    start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
    link_status, s3_key
)
SELECT
    bin_start + interval '5 minutes',
    bin_start + interval '5 minutes',
    CASE
        WHEN comparison_offset = 0 THEN statement_timestamp() - interval '1 minute'
        ELSE bin_start + interval '4 minutes'
    END,
    495,
    'I-495-NB',
    5001,
    'test observed pair',
    1,
    'test start',
    2,
    'test end',
    price,
    'NO_DETERMINATION',
    'test/i95-' || comparison_offset || '.csv'
FROM observations;

DO $$
DECLARE
    comparison record;
    row_count integer;
BEGIN
    SELECT count(*) INTO row_count
    FROM oracle.get_i95_i495_pricing_comparisons(5001);
    IF row_count <> 6 THEN
        RAISE EXCEPTION 'expected six I-95/I-495 comparison rows, got %',
            row_count;
    END IF;

    SELECT * INTO STRICT comparison
    FROM oracle.get_i95_i495_pricing_comparisons(5001)
    WHERE comparison_kind = 'current';
    IF NOT comparison.available
       OR comparison.price_usd <> 8.20
       OR comparison.source_kind <> 'observed'
       OR comparison.pricing_method <> 'source_observation'
       OR comparison.od_pair_id <> 5001
       OR comparison.proxy_od_pair_id IS NOT NULL
       OR comparison.availability_reason IS NOT NULL
       OR comparison.observed_at > comparison.evaluated_at THEN
        RAISE EXCEPTION 'current observed I-95/I-495 comparison is invalid: %',
            row_to_json(comparison);
    END IF;

    SELECT * INTO STRICT comparison
    FROM oracle.get_i95_i495_pricing_comparisons(9999);
    IF comparison.comparison_kind <> 'current'
       OR comparison.comparison_offset <> 0
       OR comparison.available
       OR comparison.availability_reason <> 'missing_observation'
       OR comparison.price_usd IS NOT NULL
       OR comparison.source_kind IS NOT NULL THEN
        RAISE EXCEPTION 'missing I-95/I-495 diagnostic is invalid: %',
            row_to_json(comparison);
    END IF;
END $$;

UPDATE pricing.trip_pricing_i95
SET calculated_at = statement_timestamp() - interval '31 minutes'
WHERE od_pair_id = 5001
  AND interval_end_at = (
      SELECT max(interval_end_at)
      FROM pricing.trip_pricing_i95
      WHERE od_pair_id = 5001
  );

DO $$
DECLARE comparison record;
BEGIN
    SELECT * INTO STRICT comparison
    FROM oracle.get_i95_i495_pricing_comparisons(5001)
    WHERE comparison_kind = 'current';
    IF comparison.available
       OR comparison.availability_reason <> 'stale_observation'
       OR comparison.price_usd <> 8.20 THEN
        RAISE EXCEPTION 'stale I-95/I-495 diagnostic is invalid: %',
            row_to_json(comparison);
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i95;

INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id,
    corridor_name, od_pair_id, od_pair_name, start_zone_id,
    start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
    link_status, s3_key
) VALUES
    (
        '2026-08-11 13:05:00+00', '2026-08-11 13:05:00+00',
        '2026-08-11 13:04:00+00', 95, 'I-95-NB', 1132,
        'northbound sentinel', 1, 'A', 2, 'B', 1.00,
        'NORTHBOUND_OPEN', 'test/i95-modeled-nb.csv'
    ),
    (
        '2026-08-11 13:05:00+00', '2026-08-11 13:05:00+00',
        '2026-08-11 13:04:00+00', 95, 'I-95-SB', 1151,
        'southbound sentinel', 3, 'C', 4, 'D', 1.00,
        'CLOSED', 'test/i95-modeled-sb.csv'
    ),
    (
        '2026-08-11 13:05:00+00', '2026-08-11 13:05:00+00',
        statement_timestamp() - interval '1 minute', 95, 'I-95-NB', 1146,
        'modeled proxy', 5, 'E', 6, 'F', 6.00,
        'NORTHBOUND_OPEN', 'test/i95-modeled-proxy.csv'
    ),
    (
        '2026-08-11 12:55:00+00', '2026-08-11 12:55:00+00',
        '2026-08-11 12:54:00+00', 95, 'I-95-NB', 1132,
        'prior northbound sentinel', 1, 'A', 2, 'B', 1.00,
        'NORTHBOUND_OPEN', 'test/i95-modeled-prior-nb.csv'
    ),
    (
        '2026-08-11 12:55:00+00', '2026-08-11 12:55:00+00',
        '2026-08-11 12:54:00+00', 95, 'I-95-SB', 1151,
        'prior southbound sentinel', 3, 'C', 4, 'D', 1.00,
        'CLOSED', 'test/i95-modeled-prior-sb.csv'
    ),
    (
        '2026-08-11 12:55:00+00', '2026-08-11 12:55:00+00',
        '2026-08-11 12:54:00+00', 95, 'I-95-NB', 1146,
        'unavailable prior modeled proxy', 5, 'E', 6, 'F', 5.00,
        'CLOSED', 'test/i95-modeled-prior-proxy.csv'
    );

DO $$
DECLARE
    comparison record;
    row_count integer;
BEGIN
    SELECT count(*) INTO row_count
    FROM oracle.get_i95_i495_pricing_comparisons(1374);
    SELECT * INTO STRICT comparison
    FROM oracle.get_i95_i495_pricing_comparisons(1374)
    WHERE comparison_kind = 'current';
    IF row_count <> 1
       OR NOT comparison.available
       OR comparison.availability_reason IS NOT NULL
       OR comparison.price_usd <> 6.00
       OR comparison.source_kind <> 'modeled'
       OR comparison.pricing_method <> 'identity_proxy_v1'
       OR comparison.od_pair_id <> 1374
       OR comparison.proxy_od_pair_id <> 1146
       OR comparison.source_status <> 'NORTHBOUND_OPEN' THEN
        RAISE EXCEPTION 'modeled I-95 price retained unavailable history: %, %',
            row_count, row_to_json(comparison);
    END IF;
END $$;

UPDATE pricing.trip_pricing_i95
SET link_status = 'CLOSED'
WHERE od_pair_id = 1146
  AND interval_end_at = '2026-08-11 13:05:00+00';

DO $$
DECLARE comparison record;
BEGIN
    SELECT * INTO STRICT comparison
    FROM oracle.get_i95_i495_pricing_comparisons(1374)
    WHERE comparison_kind = 'current';
    IF comparison.available
       OR comparison.availability_reason <> 'facility_unavailable'
       OR comparison.price_usd IS NOT NULL
       OR comparison.source_kind <> 'modeled'
       OR comparison.proxy_od_pair_id <> 1146
       OR comparison.source_status <> 'CLOSED' THEN
        RAISE EXCEPTION 'closed modeled I-95 diagnostic is invalid: %',
            row_to_json(comparison);
    END IF;
END $$;

ROLLBACK;

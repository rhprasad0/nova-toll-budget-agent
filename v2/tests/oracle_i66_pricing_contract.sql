\set ON_ERROR_STOP on

BEGIN;

TRUNCATE pricing.trip_pricing_i66;

WITH params AS (
    SELECT date_bin(
        interval '6 minutes',
        statement_timestamp() - interval '6 minutes',
        timestamptz '2000-01-01 00:00:00+00'
    ) AS anchor_bin_start
), observations AS (
    SELECT 0 AS comparison_offset, anchor_bin_start AS bin_start, 7.20 AS price
    FROM params
    UNION ALL
    SELECT offset_number,
           anchor_bin_start - make_interval(mins => 6 * offset_number),
           7.20 - offset_number
    FROM params
    CROSS JOIN generate_series(1, 2) AS offset_number
    UNION ALL
    SELECT 10 + offset_number,
           (
               (anchor_bin_start AT TIME ZONE 'America/New_York')
               - make_interval(days => 7 * offset_number)
           ) AT TIME ZONE 'America/New_York',
           4.00 + offset_number
    FROM params
    CROSS JOIN generate_series(1, 3) AS offset_number
)
INSERT INTO pricing.trip_pricing_i66 (
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, s3_key
)
SELECT
    bin_start,
    bin_start + interval '5 minutes',
    CASE
        WHEN comparison_offset = 0 THEN statement_timestamp() - interval '1 minute'
        ELSE bin_start + interval '5 minutes'
    END,
    1,
    'I-66 Inside the Beltway',
    3100,
    'Route 267',
    3110,
    'Route 7',
    price,
    'test/i66-' || comparison_offset || '.csv'
FROM observations;

DO $$
DECLARE
    comparison record;
    row_count integer;
BEGIN
    SELECT count(*) INTO row_count
    FROM oracle.get_i66_pricing_comparisons(3100, 3110);
    IF row_count <> 6 THEN
        RAISE EXCEPTION 'expected six I-66 comparison rows, got %', row_count;
    END IF;

    SELECT * INTO STRICT comparison
    FROM oracle.get_i66_pricing_comparisons(3100, 3110)
    WHERE comparison_kind = 'current';
    IF NOT comparison.available
       OR comparison.price_usd <> 7.20
       OR comparison.availability_reason IS NOT NULL
       OR comparison.observed_at > comparison.evaluated_at THEN
        RAISE EXCEPTION 'current I-66 comparison is invalid: %',
            row_to_json(comparison);
    END IF;

    SELECT * INTO STRICT comparison
    FROM oracle.get_i66_pricing_comparisons(9998, 9999);
    IF comparison.comparison_kind <> 'current'
       OR comparison.comparison_offset <> 0
       OR comparison.available
       OR comparison.availability_reason <> 'missing_observation'
       OR comparison.price_usd IS NOT NULL THEN
        RAISE EXCEPTION 'missing I-66 diagnostic is invalid: %',
            row_to_json(comparison);
    END IF;
END $$;

UPDATE pricing.trip_pricing_i66
SET calculated_at = statement_timestamp() - interval '31 minutes'
WHERE start_zone_id = 3100
  AND end_zone_id = 3110
  AND interval_end_at = (SELECT max(interval_end_at)
                         FROM pricing.trip_pricing_i66);

DO $$
DECLARE comparison record;
BEGIN
    SELECT * INTO STRICT comparison
    FROM oracle.get_i66_pricing_comparisons(3100, 3110)
    WHERE comparison_kind = 'current';
    IF comparison.available
       OR comparison.availability_reason <> 'stale_observation'
       OR comparison.price_usd <> 7.20 THEN
        RAISE EXCEPTION 'stale I-66 diagnostic is invalid: %',
            row_to_json(comparison);
    END IF;
END $$;

ROLLBACK;

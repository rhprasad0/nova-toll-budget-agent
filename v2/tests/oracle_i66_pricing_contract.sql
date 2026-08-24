\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE i66_schedule_case (
    direction text,
    local_at timestamp,
    expected_active boolean
);
INSERT INTO i66_schedule_case VALUES
    ('EB', '2026-08-18 05:29:59', false),
    ('EB', '2026-08-18 05:30:00', true),
    ('EB', '2026-08-18 09:29:59', true),
    ('EB', '2026-08-18 09:30:00', false),
    ('WB', '2026-08-18 14:59:59', false),
    ('WB', '2026-08-18 15:00:00', true),
    ('WB', '2026-08-18 18:59:59', true),
    ('WB', '2026-08-18 19:00:00', false),
    ('EB', '2026-08-22 08:00:00', false),
    ('WB', '2026-08-22 17:00:00', false),
    ('EB', '2026-01-01 08:00:00', false),
    ('EB', '2026-01-19 08:00:00', false),
    ('EB', '2026-02-16 08:00:00', false),
    ('EB', '2026-05-25 08:00:00', false),
    ('EB', '2026-06-19 08:00:00', false),
    ('EB', '2026-07-04 08:00:00', false),
    ('EB', '2026-09-07 08:00:00', false),
    ('EB', '2026-10-12 08:00:00', false),
    ('EB', '2026-11-11 08:00:00', false),
    ('EB', '2026-11-26 08:00:00', false),
    ('EB', '2026-12-25 08:00:00', false),
    ('WB', '2026-07-03 17:00:00', false),
    ('EB', '2027-07-05 08:00:00', false);

DO $$
DECLARE test_case i66_schedule_case%ROWTYPE;
BEGIN
    FOR test_case IN SELECT * FROM i66_schedule_case LOOP
        IF oracle.i66_tolling_active(test_case.direction, test_case.local_at)
           IS DISTINCT FROM test_case.expected_active THEN
            RAISE EXCEPTION 'I-66 schedule mismatch for % at %',
                test_case.direction, test_case.local_at;
        END IF;
    END LOOP;
    BEGIN
        PERFORM oracle.i66_tolling_active('NB', timestamp '2026-08-18 08:00');
        RAISE EXCEPTION 'invalid I-66 direction was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid I-66 direction' THEN RAISE; END IF;
    END;
END $$;

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
    active boolean;
BEGIN
    SELECT count(*) INTO row_count
    FROM oracle.get_i66_pricing_comparisons(3100, 3110, 'EB');
    IF row_count NOT BETWEEN 1 AND 6 THEN
        RAISE EXCEPTION 'expected a bounded I-66 comparison set, got %', row_count;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM oracle.get_i66_pricing_comparisons(3100, 3110, 'EB') AS item
        WHERE item.source_kind = 'schedule_derived'
          AND (
              item.price_usd <> 0
              OR NOT item.available
              OR item.bin_start_at IS NULL
              OR item.bin_end_at - item.bin_start_at <> interval '6 minutes'
              OR item.interval_end_at IS NOT NULL
              OR item.observed_at IS NOT NULL
          )
    ) OR EXISTS (
        SELECT 1
        FROM oracle.get_i66_pricing_comparisons(3100, 3110, 'EB') AS item
        WHERE item.comparison_kind <> 'current'
          AND item.source_kind = 'observed'
          AND NOT oracle.i66_tolling_active(
              'EB', item.bin_start_at AT TIME ZONE 'America/New_York'
          )
    ) THEN
        RAISE EXCEPTION 'I-66 historical comparisons violate the schedule';
    END IF;

    SELECT * INTO STRICT comparison
    FROM oracle.get_i66_pricing_comparisons(3100, 3110, 'EB')
    WHERE comparison_kind = 'current';
    active := oracle.i66_tolling_active(
        'EB', comparison.evaluated_at AT TIME ZONE 'America/New_York'
    );
    IF NOT comparison.available OR comparison.availability_reason IS NOT NULL
       OR (active AND (
                comparison.price_usd <> 7.20
                 OR comparison.source_kind <> 'observed'
                 OR comparison.pricing_method <> 'source_observation'
                 OR comparison.observed_at > comparison.evaluated_at
          ))
       OR (NOT active AND (
                comparison.price_usd <> 0
                 OR comparison.source_kind <> 'schedule_derived'
                 OR comparison.pricing_method <> 'published_schedule'
                 OR comparison.observed_at IS NOT NULL
          )) THEN
        RAISE EXCEPTION 'current I-66 comparison is invalid: %',
            row_to_json(comparison);
    END IF;

    BEGIN
        PERFORM * FROM oracle.get_i66_pricing_comparisons(9998, 9999, 'EB');
        RAISE EXCEPTION 'invalid I-66 component was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid I-66 pricing component' THEN RAISE; END IF;
    END;
END $$;

UPDATE pricing.trip_pricing_i66
SET calculated_at = statement_timestamp() - interval '31 minutes'
WHERE start_zone_id = 3100
  AND end_zone_id = 3110
  AND interval_end_at = (SELECT max(interval_end_at)
                         FROM pricing.trip_pricing_i66);

DO $$
DECLARE
    comparison record;
    active boolean;
BEGIN
    SELECT * INTO STRICT comparison
    FROM oracle.get_i66_pricing_comparisons(3100, 3110, 'EB')
    WHERE comparison_kind = 'current';
    active := oracle.i66_tolling_active(
        'EB', comparison.evaluated_at AT TIME ZONE 'America/New_York'
    );
    IF (active AND (
             comparison.available
             OR comparison.availability_reason <> 'stale_observation'
             OR comparison.price_usd <> 7.20
       ))
       OR (NOT active AND (
             NOT comparison.available
             OR comparison.price_usd <> 0
             OR comparison.source_kind <> 'schedule_derived'
       )) THEN
        RAISE EXCEPTION 'stale I-66 diagnostic is invalid: %',
            row_to_json(comparison);
    END IF;
END $$;

ROLLBACK;

\set ON_ERROR_STOP on

BEGIN;

CREATE FUNCTION pg_temp.insert_i95_price(
    source_od_pair_id integer,
    source_corridor_name text,
    source_rate numeric,
    source_status text,
    source_interval_end_at timestamptz,
    source_calculated_at timestamptz
) RETURNS void
LANGUAGE sql
AS $$
    INSERT INTO pricing.trip_pricing_i95 (
        interval_end_at, current_at, calculated_at, corridor_id,
        corridor_name, od_pair_id, od_pair_name, start_zone_id,
        start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
        link_status, s3_key
    ) VALUES (
        source_interval_end_at, source_interval_end_at, source_calculated_at,
        95, source_corridor_name, source_od_pair_id, 'test pair',
        source_od_pair_id, 'test start', source_od_pair_id + 1, 'test end',
        source_rate, source_status, 'test/analysis-i95.csv'
    );
$$;

CREATE FUNCTION pg_temp.insert_i66_price(
    source_start_zone_id integer,
    source_end_zone_id integer,
    source_rate numeric,
    source_interval_end_at timestamptz,
    source_calculated_at timestamptz
) RETURNS void
LANGUAGE sql
AS $$
    INSERT INTO pricing.trip_pricing_i66 (
        interval_start_at, interval_end_at, calculated_at, corridor_id,
        corridor_name, start_zone_id, start_zone_name, end_zone_id,
        end_zone_name, zone_toll_rate_usd, s3_key
    ) VALUES (
        source_interval_end_at - interval '6 minutes', source_interval_end_at,
        source_calculated_at, 66, 'I-66-EB', source_start_zone_id,
        'test start', source_end_zone_id, 'test end', source_rate,
        'test/analysis-i66.xml'
    );
$$;

CREATE FUNCTION pg_temp.insert_direction(
    source_interval_end_at timestamptz,
    source_direction text
) RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_temp.insert_i95_price(
        1132, 'I-95-NB', 1.00,
        CASE source_direction
            WHEN 'NORTHBOUND_OPEN' THEN 'NORTHBOUND_OPEN'
            ELSE 'CLOSED'
        END,
        source_interval_end_at,
        source_interval_end_at - interval '10 minutes'
    );
    PERFORM pg_temp.insert_i95_price(
        1151, 'I-95-SB', 1.00,
        CASE source_direction
            WHEN 'SOUTHBOUND_OPEN' THEN 'SOUTHBOUND_OPEN'
            ELSE 'CLOSED'
        END,
        source_interval_end_at,
        source_interval_end_at - interval '10 minutes'
    );
END;
$$;

-- I-66 independently exposes current, two prior cycles, and three prior weeks.
SELECT pg_temp.insert_i66_price(10, 20, 10.00, '2026-08-13 12:35:00+00', '2026-08-13 12:34:00+00');
SELECT pg_temp.insert_i66_price(10, 20, 9.00, '2026-08-13 12:29:00+00', '2026-08-13 12:28:00+00');
SELECT pg_temp.insert_i66_price(10, 20, 8.00, '2026-08-13 12:23:00+00', '2026-08-13 12:22:00+00');
SELECT pg_temp.insert_i66_price(10, 20, 7.00, '2026-08-06 12:35:00+00', '2026-08-06 12:34:00+00');
SELECT pg_temp.insert_i66_price(10, 20, 6.00, '2026-07-30 12:35:00+00', '2026-07-30 12:34:00+00');
SELECT pg_temp.insert_i66_price(10, 20, 5.00, '2026-07-23 12:35:00+00', '2026-07-23 12:34:00+00');
SELECT pg_temp.insert_i66_price(11, 21, 4.00, '2026-08-06 12:35:00+00', '2026-08-06 12:34:00+00');

DO $$
BEGIN
    IF (SELECT count(*) FROM pricing.i66_pricing_comparisons
        WHERE start_zone_id = 10 AND end_zone_id = 20) <> 6
       OR (SELECT count(*) FROM pricing.i66_pricing_comparisons
           WHERE start_zone_id = 10 AND end_zone_id = 20
             AND comparison_kind = 'prior_cycle') <> 2
       OR (SELECT count(*) FROM pricing.i66_pricing_comparisons
           WHERE start_zone_id = 10 AND end_zone_id = 20
             AND comparison_kind = 'prior_week') <> 3
       OR EXISTS (
           SELECT 1 FROM pricing.i66_pricing_comparisons
           WHERE start_zone_id = 10 AND end_zone_id = 20
             AND bin_end_at - bin_start_at <> interval '6 minutes'
       ) OR NOT EXISTS (
           SELECT 1 FROM pricing.i66_pricing_comparisons
           WHERE start_zone_id = 11 AND end_zone_id = 21
             AND comparison_kind = 'prior_week' AND comparison_offset = 1
       ) OR EXISTS (
           SELECT 1 FROM pricing.i66_pricing_comparisons
           WHERE start_zone_id = 11 AND end_zone_id = 21
             AND comparison_kind = 'current'
       ) THEN
        RAISE EXCEPTION 'I-66 comparison coverage, cadence, or independent history is incorrect';
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i66, pricing.trip_pricing_i95;

-- Every canonical schedule boundary is fail-closed. The reversal rule wins
-- the published weekday 10-11 overlap.
CREATE TEMP TABLE schedule_case (
    local_at timestamp PRIMARY KEY,
    expected_direction text
);
INSERT INTO schedule_case VALUES
    ('2026-08-10 09:59', 'NORTHBOUND_OPEN'),
    ('2026-08-10 10:00', NULL),
    ('2026-08-10 12:00', 'SOUTHBOUND_OPEN'),
    ('2026-08-11 00:59', 'SOUTHBOUND_OPEN'),
    ('2026-08-11 01:00', NULL),
    ('2026-08-11 02:29', NULL),
    ('2026-08-11 02:30', 'NORTHBOUND_OPEN'),
    ('2026-08-11 09:59', 'NORTHBOUND_OPEN'),
    ('2026-08-11 10:00', NULL),
    ('2026-08-11 11:59', NULL),
    ('2026-08-11 12:00', 'SOUTHBOUND_OPEN'),
    ('2026-08-15 13:59', 'SOUTHBOUND_OPEN'),
    ('2026-08-15 14:00', NULL),
    ('2026-08-15 15:59', NULL),
    ('2026-08-15 16:00', 'NORTHBOUND_OPEN'),
    ('2026-08-16 12:00', 'NORTHBOUND_OPEN');

DO $$
DECLARE
    test_case schedule_case%ROWTYPE;
    instant timestamptz;
    feed_direction text;
    corridor text;
    route_status text;
    matching_rows integer;
    exceptional_rows integer;
BEGIN
    FOR test_case IN SELECT * FROM schedule_case ORDER BY local_at LOOP
        TRUNCATE pricing.trip_pricing_i95;
        instant := test_case.local_at AT TIME ZONE 'America/New_York';
        feed_direction := coalesce(test_case.expected_direction, 'NORTHBOUND_OPEN');
        corridor := CASE feed_direction
            WHEN 'NORTHBOUND_OPEN' THEN 'I-95-NB'
            ELSE 'I-95-SB'
        END;
        route_status := feed_direction;

        PERFORM pg_temp.insert_direction(instant, feed_direction);
        PERFORM pg_temp.insert_i95_price(
            5001, corridor, 5.00, route_status, instant, instant - interval '10 minutes'
        );

        SELECT
            count(*),
            count(*) FILTER (
                WHERE available = false
                  AND availability_reason = 'exceptional_i95_schedule'
            )
        INTO matching_rows, exceptional_rows
        FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_observed'
          AND od_pair_id = 5001
          AND comparison_kind = 'current';

        IF matching_rows <> 1
           OR (test_case.expected_direction IS NULL AND exceptional_rows <> 1)
           OR (test_case.expected_direction IS NOT NULL AND exceptional_rows <> 0) THEN
            RAISE EXCEPTION 'canonical schedule boundary failed at %, expected %, rows %, exceptional %',
                test_case.local_at, test_case.expected_direction,
                matching_rows, exceptional_rows;
        END IF;
    END LOOP;
END $$;

TRUNCATE pricing.trip_pricing_i95;

-- Canonical Tuesday northbound interval with a matching sentinel direction.
SELECT pg_temp.insert_direction('2026-08-11 13:05:00+00', 'NORTHBOUND_OPEN');
SELECT pg_temp.insert_i95_price(5001, 'I-95-NB', 7.00, 'NORTHBOUND_OPEN', '2026-08-11 13:05:00+00', '2026-08-11 12:55:00+00');
SELECT pg_temp.insert_i95_price(5002, 'I-95-SB', 8.00, 'SOUTHBOUND_OPEN', '2026-08-11 13:05:00+00', '2026-08-11 12:55:00+00');
SELECT pg_temp.insert_i95_price(5003, 'I-495-NB', 4.00, 'NO_DETERMINATION', '2026-08-11 13:05:00+00', '2026-08-11 12:55:00+00');
SELECT pg_temp.insert_i95_price(1146, 'I-95-NB', 6.00, 'NORTHBOUND_OPEN', '2026-08-11 13:05:00+00', '2026-08-11 12:55:00+00');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_observed' AND od_pair_id = 5001
          AND comparison_kind = 'current'
    ) OR EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_observed' AND od_pair_id = 5002
    ) OR NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_observed' AND od_pair_id = 5003
    ) OR NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_modeled' AND od_pair_id = 1374
          AND proxy_od_pair_id = 1146 AND pricing_method = 'identity_proxy_v1'
    ) THEN
        RAISE EXCEPTION 'canonical direction, I-495, or modeled eligibility failed';
    END IF;
END $$;

-- A later in-bin row without matching sentinels must suppress the older open
-- row rather than falling back to it. I-495 remains on the shared anchor.
SELECT pg_temp.insert_i95_price(5001, 'I-95-NB', 9.00, 'NORTHBOUND_OPEN', '2026-08-11 13:08:00+00', '2026-08-11 12:58:00+00');
SELECT pg_temp.insert_i95_price(5003, 'I-495-NB', 4.50, 'NO_DETERMINATION', '2026-08-11 13:08:00+00', '2026-08-11 12:58:00+00');

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_observed' AND od_pair_id = 5001
          AND comparison_kind = 'current'
    ) OR NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_observed' AND od_pair_id = 5003
          AND comparison_kind = 'current'
          AND anchor_interval_end_at = '2026-08-11 13:08:00+00'
    ) THEN
        RAISE EXCEPTION 'rank-before-filter or shared feed anchor failed';
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i95;

-- A holiday/event direction that contradicts the canonical Tuesday morning
-- schedule preserves current evidence as an explicit unavailable diagnostic
-- while retaining independently eligible history.
SELECT pg_temp.insert_direction('2026-08-11 13:05:00+00', 'SOUTHBOUND_OPEN');
SELECT pg_temp.insert_i95_price(5002, 'I-95-NB', 8.00, 'CLOSED', '2026-08-11 13:05:00+00', '2026-08-11 12:55:00+00');
SELECT pg_temp.insert_i95_price(5003, 'I-495-SB', 4.00, 'NO_DETERMINATION', '2026-08-11 13:05:00+00', '2026-08-11 12:55:00+00');
SELECT pg_temp.insert_direction('2026-08-04 13:05:00+00', 'NORTHBOUND_OPEN');
SELECT pg_temp.insert_i95_price(5002, 'I-95-NB', 7.00, 'NORTHBOUND_OPEN', '2026-08-04 13:05:00+00', '2026-08-04 12:55:00+00');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 5002
          AND comparison_kind = 'current'
          AND available = false
          AND availability_reason = 'exceptional_i95_schedule'
          AND interval_end_at = '2026-08-11 13:05:00+00'
          AND observed_at = '2026-08-11 12:55:00+00'
          AND source_status = 'CLOSED'
    ) OR NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 5002 AND comparison_kind = 'prior_week'
          AND comparison_offset = 1 AND price_usd = 7.00
    ) OR NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 5003 AND comparison_kind = 'current'
    ) THEN
        RAISE EXCEPTION 'exceptional I-95 diagnostic or valid history/I-495 was filtered';
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i95;

-- Current plus two cycles plus three prior weeks on the I-95 schedule.
DO $$
DECLARE
    instant timestamptz;
    rate numeric := 10;
BEGIN
    FOREACH instant IN ARRAY ARRAY[
        '2026-08-13 12:25:00+00'::timestamptz,
        '2026-08-13 12:15:00+00'::timestamptz,
        '2026-08-13 12:05:00+00'::timestamptz,
        '2026-08-06 12:25:00+00'::timestamptz,
        '2026-07-30 12:25:00+00'::timestamptz,
        '2026-07-23 12:25:00+00'::timestamptz
    ] LOOP
        PERFORM pg_temp.insert_direction(instant, 'NORTHBOUND_OPEN');
        PERFORM pg_temp.insert_i95_price(6001, 'I-95-NB', rate, 'NORTHBOUND_OPEN', instant, instant - interval '10 minutes');
        rate := rate - 1;
    END LOOP;
END $$;

DO $$
BEGIN
    IF (SELECT count(*) FROM pricing.i95_i495_pricing_comparisons
        WHERE price_source = 'i95_observed' AND od_pair_id = 6001) <> 6
       OR (SELECT count(*) FROM pricing.i95_i495_pricing_comparisons
           WHERE price_source = 'i95_observed' AND od_pair_id = 6001
             AND comparison_kind = 'prior_week') <> 3
       OR EXISTS (
           SELECT 1 FROM pricing.i95_i495_pricing_comparisons
           WHERE od_pair_id = 6001
             AND bin_end_at - bin_start_at <> interval '10 minutes'
       ) THEN
        RAISE EXCEPTION 'I-95 cycle or prior-week coverage is incorrect';
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i95;

-- Fall-back prior-week targets use the later, standard-time occurrence.
SELECT pg_temp.insert_i95_price(7001, 'I-495-NB', 3.00, 'NO_DETERMINATION', '2025-11-09 06:35:00+00', '2025-11-09 06:34:00+00');
SELECT pg_temp.insert_i95_price(7001, 'I-495-NB', 1.00, 'NO_DETERMINATION', '2025-11-02 05:35:00+00', '2025-11-02 05:34:00+00');
SELECT pg_temp.insert_i95_price(7001, 'I-495-NB', 2.00, 'NO_DETERMINATION', '2025-11-02 06:35:00+00', '2025-11-02 06:34:00+00');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 7001 AND comparison_kind = 'prior_week'
          AND comparison_offset = 1 AND price_usd = 2.00
          AND interval_end_at = '2025-11-02 06:35:00+00'
    ) OR EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 7001 AND interval_end_at = '2025-11-02 05:35:00+00'
    ) THEN
        RAISE EXCEPTION 'fall-back target did not use standard time';
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i95;

-- The third prior week lands in the nonexistent spring-forward 02:30 wall
-- time and must not normalize into a comparison.
SELECT pg_temp.insert_i95_price(7002, 'I-495-NB', 4.00, 'NO_DETERMINATION', '2026-03-29 06:35:00+00', '2026-03-29 06:34:00+00');
SELECT pg_temp.insert_i95_price(7002, 'I-495-NB', 3.00, 'NO_DETERMINATION', '2026-03-08 07:35:00+00', '2026-03-08 07:34:00+00');

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 7002 AND comparison_kind = 'prior_week'
          AND comparison_offset = 3
    ) THEN
        RAISE EXCEPTION 'nonexistent spring-forward target was normalized';
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i95;

-- A future-calculated conflicting sentinel revision cannot suppress an
-- otherwise eligible observation.
SELECT pg_temp.insert_direction('2026-08-11 17:05:00+00', 'SOUTHBOUND_OPEN');
SELECT pg_temp.insert_i95_price(9001, 'I-95-SB', 5.00, 'SOUTHBOUND_OPEN', '2026-08-11 17:05:00+00', '2026-08-11 16:55:00+00');
INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id,
    corridor_name, od_pair_id, od_pair_name, start_zone_id,
    start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
    link_status, s3_key
)
SELECT
    interval_end_at, current_at, statement_timestamp() + interval '1 hour',
    corridor_id, corridor_name, od_pair_id, od_pair_name,
    start_zone_id + 10000, start_zone_name, end_zone_id + 10000,
    end_zone_name, zone_toll_rate_usd, 'CLOSED', 'test/future-sentinel.csv'
FROM pricing.trip_pricing_i95
WHERE od_pair_id = 1151 AND interval_end_at = '2026-08-11 17:05:00+00';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 9001 AND comparison_kind = 'current'
    ) THEN
        RAISE EXCEPTION 'future-calculated sentinel suppressed an eligible price';
    END IF;
END $$;

TRUNCATE pricing.trip_pricing_i95;

-- Future rows cannot displace the latest eligible anchor; stopped feeds remain
-- visible as stale current readings.
SELECT pg_temp.insert_i95_price(8001, 'I-495-NB', 4.00, 'NO_DETERMINATION', statement_timestamp() - interval '5 minutes', statement_timestamp() - interval '31 minutes');
SELECT pg_temp.insert_i95_price(8001, 'I-495-NB', 9.00, 'NO_DETERMINATION', statement_timestamp() + interval '1 hour', statement_timestamp() + interval '1 hour');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 8001 AND comparison_kind = 'current'
          AND available = false AND availability_reason = 'stale_observation'
          AND price_usd = 4.00
    ) OR EXISTS (
        SELECT 1 FROM pricing.i95_i495_pricing_comparisons
        WHERE od_pair_id = 8001 AND price_usd = 9.00
    ) THEN
        RAISE EXCEPTION 'future or stale current-row handling failed';
    END IF;
END $$;

ROLLBACK;

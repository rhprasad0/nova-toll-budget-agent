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
        source_rate, source_status, 'test/analysis-i95.json'
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
        source_interval_end_at - interval '10 minutes', source_interval_end_at,
        source_calculated_at, 66, 'I-66-EB', source_start_zone_id,
        'test start', source_end_zone_id, 'test end', source_rate,
        'test/analysis-i66.xml'
    );
$$;

SELECT pg_temp.insert_i95_price(
    5001, 'I-95-NB', 7.10, 'NORTHBOUND_OPEN',
    '2026-08-13 12:20:00+00', '2026-08-13 12:10:00+00'
);
SELECT pg_temp.insert_i66_price(
    10, 20, 2.10, '2026-08-13 12:25:00+00', '2026-08-13 12:25:00+00'
);

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[
          {"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":5001},
          {"route_step_id":"step-2","price_source":"i66_observed","start_zone_id":10,"end_zone_id":20}
        ]'::jsonb
    );

    IF NOT result.complete OR result.total_usd <> 9.20
       OR jsonb_array_length(result.components) <> 2
       OR result.reason IS NOT NULL THEN
        RAISE EXCEPTION 'complete point-in-time route was not priced: %', row_to_json(result);
    END IF;
END $$;

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[]'::jsonb
    );
    IF NOT result.complete OR result.total_usd <> 0.00
       OR result.components <> '[]'::jsonb OR result.reason IS NOT NULL THEN
        RAISE EXCEPTION 'empty dynamic route must be a known zero subtotal';
    END IF;
END $$;

-- A future-calculated row is ineligible; the older source observation remains
-- the latest row that the contract permits.
SELECT pg_temp.insert_i95_price(
    5003, 'I-495-NB', 4.00, 'NO_DETERMINATION',
    '2026-08-13 12:20:00+00', '2026-08-13 12:10:00+00'
);
SELECT pg_temp.insert_i95_price(
    5003, 'I-495-NB', 9.00, 'NO_DETERMINATION',
    '2026-08-13 12:30:00+00', '2026-08-13 12:40:00+00'
);

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":5003}]'::jsonb
    );
    IF NOT result.complete OR result.total_usd <> 4.00 THEN
        RAISE EXCEPTION 'future observation leaked into point-in-time result';
    END IF;
END $$;

-- I-495 does not publish a meaningful availability status; exactly thirty
-- minutes old is fresh, while one second older is stale.
SELECT pg_temp.insert_i95_price(
    5002, 'I-495-SB', 3.00, 'NO_DETERMINATION',
    '2026-08-13 12:20:00+00', '2026-08-13 12:02:00+00'
);

DO $$
DECLARE
    fresh record;
    stale record;
BEGIN
    SELECT * INTO fresh
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":5002}]'::jsonb
    );
    SELECT * INTO stale
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:01+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":5002}]'::jsonb
    );
    IF NOT fresh.complete OR stale.complete OR stale.reason <> 'incomplete_route_price'
       OR stale.unavailable_components @> '[{"reason":"stale_observation"}]'::jsonb IS NOT TRUE THEN
        RAISE EXCEPTION 'freshness boundary is incorrect';
    END IF;
END $$;

-- Latest closure must block the earlier usable I-95 row.
SELECT pg_temp.insert_i95_price(
    5001, 'I-95-NB', 8.00, 'CLOSED',
    '2026-08-13 12:30:00+00', '2026-08-13 12:29:00+00'
);

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":5001}]'::jsonb
    );
    IF result.complete OR result.total_usd IS NOT NULL
       OR result.components <> '[]'::jsonb
       OR result.unavailable_components @> '[{"reason":"facility_unavailable"}]'::jsonb IS NOT TRUE THEN
        RAISE EXCEPTION 'latest closure fell back to an older open row';
    END IF;
END $$;

-- The approved modeled target must retain proxy provenance.
SELECT pg_temp.insert_i95_price(
    1165, 'I-95-SB', 14.25, 'SOUTHBOUND_OPEN',
    '2026-08-13 12:20:00+00', '2026-08-13 12:10:00+00'
);

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_modeled","od_pair_id":1385}]'::jsonb
    );
    IF NOT result.complete OR result.total_usd <> 14.25
       OR result.components @> '[{"source_kind":"modeled","pricing_method":"identity_proxy_v1","proxy_od_pair_id":1165}]'::jsonb IS NOT TRUE THEN
        RAISE EXCEPTION 'modeled point-in-time provenance was lost';
    END IF;
END $$;

DO $$
DECLARE
    invalid_shape record;
    duplicate_step record;
    oversized_id record;
    infinite_time record;
    string_id record;
    too_many record;
    long_step record;
    too_large record;
    oversized_components jsonb;
BEGIN
    SELECT * INTO invalid_shape
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"unknown","od_pair_id":1}]'::jsonb
    );
    SELECT * INTO duplicate_step
    FROM pricing.historical_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[
          {"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":5001},
          {"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":5003}
        ]'::jsonb
    );
    SELECT * INTO oversized_id
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":999999999999999999999}]'::jsonb
    );
    SELECT * INTO infinite_time
    FROM pricing.historical_dynamic_route_pricing(
        '-infinity'::timestamptz,
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":1}]'::jsonb
    );
    SELECT * INTO string_id
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":"5001"}]'::jsonb
    );
    SELECT jsonb_agg(jsonb_build_object(
        'route_step_id', 'step-' || n,
        'price_source', 'i95_observed',
        'od_pair_id', n
    )) INTO oversized_components
    FROM generate_series(1, 17) AS values(n);
    SELECT * INTO too_many
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00', oversized_components
    );
    SELECT * INTO long_step
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        jsonb_build_array(jsonb_build_object(
            'route_step_id', repeat('x', 129),
            'price_source', 'i95_observed',
            'od_pair_id', 5001
        ))
    );
    SELECT * INTO too_large
    FROM pricing.point_in_time_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        jsonb_build_array(jsonb_build_object(
            'route_step_id', 'step-1',
            'price_source', repeat('x', 66000)
        ))
    );
    IF invalid_shape.reason <> 'invalid_request'
       OR duplicate_step.reason <> 'invalid_request'
       OR oversized_id.reason <> 'invalid_request'
       OR infinite_time.reason <> 'invalid_request'
       OR string_id.reason <> 'invalid_request'
       OR too_many.reason <> 'invalid_request'
       OR long_step.reason <> 'invalid_request'
       OR too_large.reason <> 'invalid_request' THEN
        RAISE EXCEPTION 'invalid component input was accepted';
    END IF;
END $$;

-- History compares prior slots and does not forecast, so a future planning
-- instant remains a valid historical query.
DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.historical_dynamic_route_pricing(
        '2099-08-13 12:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":6001}]'::jsonb
    );
    IF result.reason <> 'insufficient_recent_history'
       OR result.invalid_fields <> '[]'::jsonb THEN
        RAISE EXCEPTION 'future planning instant was rejected';
    END IF;
END $$;

-- Four prior Thursdays in the Eastern 08:30 slot. Route totals are calculated
-- per date before the summary statistics.
SELECT pg_temp.insert_i95_price(6001, 'I-95-NB', 5.00, 'NORTHBOUND_OPEN', '2026-07-16 12:35:00+00', '2026-07-16 12:34:00+00');
SELECT pg_temp.insert_i66_price(30, 40, 2.10, '2026-07-16 12:36:00+00', '2026-07-16 12:35:00+00');
SELECT pg_temp.insert_i95_price(6001, 'I-95-NB', 6.00, 'NORTHBOUND_OPEN', '2026-07-23 12:35:00+00', '2026-07-23 12:34:00+00');
SELECT pg_temp.insert_i66_price(30, 40, 3.00, '2026-07-23 12:36:00+00', '2026-07-23 12:35:00+00');
SELECT pg_temp.insert_i95_price(6001, 'I-95-NB', 7.00, 'NORTHBOUND_OPEN', '2026-07-30 12:35:00+00', '2026-07-30 12:34:00+00');
SELECT pg_temp.insert_i66_price(30, 40, 2.50, '2026-07-30 12:36:00+00', '2026-07-30 12:35:00+00');
SELECT pg_temp.insert_i95_price(6001, 'I-95-NB', 10.00, 'NORTHBOUND_OPEN', '2026-08-06 12:35:00+00', '2026-08-06 12:34:00+00');
SELECT pg_temp.insert_i66_price(30, 40, 3.60, '2026-08-06 12:36:00+00', '2026-08-06 12:35:00+00');

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.historical_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[
          {"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":6001},
          {"route_step_id":"step-2","price_source":"i66_observed","start_zone_id":30,"end_zone_id":40}
        ]'::jsonb
    );
    IF result.slot_start <> '2026-08-13 12:30:00+00'
       OR result.window_start <> '2026-07-16 12:30:00+00'
       OR result.window_end <> '2026-08-13 12:30:00+00'
       OR result.comparable_period_count <> 4
       OR result.expected_comparable_period_count <> 4
       OR result.mean_usd <> 9.80 OR result.median_usd <> 9.25
       OR result.minimum_usd <> 7.10 OR result.maximum_usd <> 13.60
       OR jsonb_array_length(result.comparable_totals) <> 4 THEN
        RAISE EXCEPTION 'four-week route summary is incorrect: %', row_to_json(result);
    END IF;
END $$;

-- Floor the first fall-back occurrence without jumping to the later physical
-- occurrence. Prior ambiguous comparison dates still use PostgreSQL's stable
-- standard-time interpretation.
DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.historical_dynamic_route_pricing(
        '2025-11-02 05:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":7001}]'::jsonb
    );
    IF result.slot_start <> '2025-11-02 05:30:00+00'
       OR result.window_end > result.requested_at THEN
        RAISE EXCEPTION 'first fall-back occurrence floored to a future instant';
    END IF;
END $$;

-- A later closed row in one component makes the whole date incomplete.
SELECT pg_temp.insert_i95_price(6001, 'I-95-NB', 11.00, 'CLOSED', '2026-08-06 12:42:00+00', '2026-08-06 12:41:00+00');

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.historical_dynamic_route_pricing(
        '2026-08-13 12:32:00+00',
        '[
          {"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":6001},
          {"route_step_id":"step-2","price_source":"i66_observed","start_zone_id":30,"end_zone_id":40}
        ]'::jsonb
    );
    IF result.comparable_period_count <> 3
       OR result.comparable_totals @> '[{"total_usd":"13.60"}]'::jsonb THEN
        RAISE EXCEPTION 'historical closure did not exclude the complete date';
    END IF;
END $$;

-- PostgreSQL resolves an ambiguous Eastern timestamp to standard time. The
-- repeated fall-back slot therefore selects the later physical occurrence.
SELECT pg_temp.insert_i95_price(7001, 'I-495-NB', 1.00, 'NO_DETERMINATION', '2025-11-02 05:35:00+00', '2025-11-02 05:34:00+00');
SELECT pg_temp.insert_i95_price(7001, 'I-495-NB', 2.00, 'NO_DETERMINATION', '2025-11-02 06:35:00+00', '2025-11-02 06:34:00+00');

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.historical_dynamic_route_pricing(
        '2025-11-09 06:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":7001}]'::jsonb
    );
    IF result.comparable_period_count <> 1
       OR result.comparable_totals @> '[{"total_usd":"2.00"}]'::jsonb IS NOT TRUE THEN
        RAISE EXCEPTION 'fall-back slot did not select the later occurrence: %', row_to_json(result);
    END IF;
END $$;

-- A normalized 03:30 instant must not masquerade as the nonexistent 02:30
-- spring-forward slot.
SELECT pg_temp.insert_i95_price(7002, 'I-495-NB', 3.00, 'NO_DETERMINATION', '2026-03-08 07:35:00+00', '2026-03-08 07:34:00+00');

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM pricing.historical_dynamic_route_pricing(
        '2026-04-05 06:32:00+00',
        '[{"route_step_id":"step-1","price_source":"i95_observed","od_pair_id":7002}]'::jsonb
    );
    IF result.comparable_period_count <> 0
       OR result.expected_comparable_period_count <> 3
       OR result.reason <> 'insufficient_recent_history' THEN
        RAISE EXCEPTION 'nonexistent spring-forward slot was treated as comparable';
    END IF;
END $$;

ROLLBACK;

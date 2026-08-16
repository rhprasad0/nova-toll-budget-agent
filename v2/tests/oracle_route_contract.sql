\set ON_ERROR_STOP on

BEGIN;

CREATE FUNCTION pg_temp.set_i95_state(
    northbound_status text,
    southbound_status text,
    source_calculated_at timestamptz,
    mismatch_intervals boolean DEFAULT false
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    source_interval timestamptz := statement_timestamp() - interval '1 minute';
BEGIN
    TRUNCATE pricing.trip_pricing_i95;
    INSERT INTO pricing.trip_pricing_i95 (
        interval_end_at, current_at, calculated_at, corridor_id,
        corridor_name, od_pair_id, od_pair_name, start_zone_id,
        start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
        link_status, s3_key
    ) VALUES
        (
            source_interval, source_interval, source_calculated_at, 95,
            'I-95-NB', 1132, 'NB direction sentinel', 1, 'A', 2, 'B',
            1.00, northbound_status, 'test/oracle-nb.csv'
        ),
        (
            source_interval - CASE WHEN mismatch_intervals THEN interval '1 minute'
                                   ELSE interval '0 seconds' END,
            source_interval, source_calculated_at, 95,
            'I-95-SB', 1151, 'SB direction sentinel', 3, 'C', 4, 'D',
            1.00, southbound_status, 'test/oracle-sb.csv'
        );
END
$$;

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'i66:4:exit:EB');
    IF result.status <> 'valid' OR cardinality(result.connection_ids) <> 1
       OR result.general_purpose_gaps <> '[]'::jsonb
       OR result.i95_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'ordinary I-66 route failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:4:exit:EB', 'i66:4:exit:EB');
    IF result.status <> 'invalid_origin' OR cardinality(result.point_ids) <> 0 THEN
        RAISE EXCEPTION 'invalid origin was not explicit';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'i66:4:entry:EB');
    IF result.status <> 'invalid_destination' THEN
        RAISE EXCEPTION 'invalid destination was not explicit';
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute'
);

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'valid'
       OR result.i95_evidence->>'availability' <> 'northbound' THEN
        RAISE EXCEPTION 'fresh northbound route failed: %', row_to_json(result);
    END IF;
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'airport_dca');
    IF result.status <> 'valid'
       OR result.connection_ids[array_length(result.connection_ids, 1)]
          <> 'i95_north_to_dca' THEN
        RAISE EXCEPTION 'northbound DCA route failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:185SO', 'i95:217SD');
    IF result.status <> 'valid'
       OR result.connection_types <> ARRAY['general_purpose_gap']::text[]
       OR result.general_purpose_gaps->0->>'boundary_point_id' <> 'i495:192SD'
       OR result.general_purpose_gaps->0->>'role' <> 'suffix'
       OR result.general_purpose_gaps->0->>'i95_direction' <> 'SB'
       OR (result.general_purpose_gaps->0->>'fallback_required')::boolean
            IS DISTINCT FROM true
       OR result.i95_evidence->>'availability' <> 'northbound' THEN
        RAISE EXCEPTION 'TP1SB general-purpose suffix failed: %',
            row_to_json(result);
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'CLOSED', 'SOUTHBOUND_OPEN', statement_timestamp() - interval '1 minute'
);

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'currently_unavailable'
       OR cardinality(result.connection_ids) <> 1
       OR result.i95_evidence->>'availability' <> 'southbound' THEN
        RAISE EXCEPTION 'opposite-direction route was not unavailable: %',
            row_to_json(result);
    END IF;
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'airport_dca');
    IF result.status <> 'currently_unavailable' THEN
        RAISE EXCEPTION 'southbound state allowed DCA route';
    END IF;


    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:234NO', 'i495:185ND');
    IF result.status <> 'valid'
       OR result.connection_types <> ARRAY['general_purpose_gap']::text[]
       OR result.general_purpose_gaps->0->>'boundary_point_id' <> 'i495:192NO'
       OR result.general_purpose_gaps->0->>'role' <> 'prefix'
       OR result.general_purpose_gaps->0->>'i95_direction' <> 'NB'
       OR (result.general_purpose_gaps->0->>'fallback_required')::boolean
            IS DISTINCT FROM true
       OR result.i95_evidence->>'availability' <> 'southbound' THEN
        RAISE EXCEPTION 'TP1NB general-purpose prefix failed: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:185SO', 'i95:217SD');
    IF result.status <> 'valid'
       OR (result.general_purpose_gaps->0->>'fallback_required')::boolean
            IS DISTINCT FROM false
       OR result.i95_evidence->>'availability' <> 'southbound' THEN
        RAISE EXCEPTION 'available I-95 direction incorrectly required fallback: %',
            row_to_json(result);
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'CLOSED', 'CLOSED', statement_timestamp() - interval '1 minute'
);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'currently_unavailable'
       OR result.i95_evidence->>'availability' <> 'closed' THEN
        RAISE EXCEPTION 'known closure was not distinguished';
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'SOUTHBOUND_OPEN', statement_timestamp() - interval '1 minute'
);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'unknown_availability'
       OR result.i95_evidence->>'availability' <> 'unknown' THEN
        RAISE EXCEPTION 'contradictory state was not unknown';
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '21 minutes'
);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'unknown_availability' THEN
        RAISE EXCEPTION 'stale state was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:185SO', 'i95:217SD');
    IF result.status <> 'valid'
       OR result.general_purpose_gaps->0->>'fallback_required' IS NOT NULL
       OR result.i95_evidence->>'availability' <> 'unknown' THEN
        RAISE EXCEPTION 'unknown state did not preserve safe TP1 fallback: %',
            row_to_json(result);
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute', true
);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'unknown_availability' THEN
        RAISE EXCEPTION 'mismatched intervals were accepted';
    END IF;
END $$;

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'greenway:1:entry:EB', 'dtr:10:exit:EB'
    );
    IF result.status <> 'valid'
       OR result.connection_ids <> ARRAY[
           'source:greenway:EB:1:28',
           'greenway_to_dtr',
           'source:dtr:EB:28:10'
       ]::text[] THEN
        RAISE EXCEPTION 'Greenway/DTR separation failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'dtr:10:entry:WB', 'greenway:1:exit:WB'
    );
    IF result.status <> 'valid'
       OR NOT 'dtr_to_greenway' = ANY(result.connection_ids) THEN
        RAISE EXCEPTION 'DTR/Greenway reverse handoff failed';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('dtr:10:entry:EB', 'i495:181ND');
    IF result.status <> 'valid'
       OR NOT 'dulles_toll_road_to_i495_north' = ANY(result.connection_ids) THEN
        RAISE EXCEPTION 'DTR/I-495 junction failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('dtr:66:entry:WB', 'i495:181ND');
    IF result.status <> 'valid'
       OR NOT 'dulles_toll_road_westbound_to_i495_north'
              = ANY(result.connection_ids) THEN
        RAISE EXCEPTION 'westbound DTR/I-495 junction failed: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'i66:11:entry:WB', 'dtr:28:exit:WB'
    );
    IF result.status <> 'valid'
       OR NOT 'i66_to_dulles_toll_road' = ANY(result.connection_ids) THEN
        RAISE EXCEPTION 'I-66/DTR junction failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('dtr:10:entry:EB', 'i66:10:exit:EB');
    IF result.status <> 'valid'
       OR NOT 'dulles_toll_road_to_i66' = ANY(result.connection_ids) THEN
        RAISE EXCEPTION 'DTR/I-66 junction failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_iad', 'i66:10:exit:EB');
    IF result.status <> 'valid'
       OR result.connection_ids[1] <> 'iad_to_i66' THEN
        RAISE EXCEPTION 'IAD-to-I-66 access failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:11:entry:WB', 'airport_iad');
    IF result.status <> 'valid'
       OR result.connection_ids[array_length(result.connection_ids, 1)]
          <> 'i66_to_iad' THEN
        RAISE EXCEPTION 'I-66-to-IAD access failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_iad', 'dtr:12:exit:WB');
    IF result.status <> 'valid'
       OR result.connection_ids[1] <> 'iad_to_dtr_via_i66' THEN
        RAISE EXCEPTION 'IAD-to-DTR composed access failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('dtr:12:entry:EB', 'airport_iad');
    IF result.status <> 'valid'
       OR result.connection_ids[array_length(result.connection_ids, 1)]
          <> 'dtr_to_iad_via_i66' THEN
        RAISE EXCEPTION 'DTR-to-IAD composed access failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:4:entry:WB', 'airport_iad');
    IF result.status <> 'valid'
       OR result.connection_ids[array_length(result.connection_ids, 1)]
          <> 'i495_north_to_iad' THEN
        RAISE EXCEPTION 'IAD airport-access routing failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_dca', 'i95:201ND');
    IF result.status <> 'no_supported_route' THEN
        RAISE EXCEPTION 'DCA incorrectly gained an outgoing route';
    END IF;
END $$;

INSERT INTO oracle.toll_route_point (
    point_id, network_id, source_node_id, point_type, direction,
    label, aliases, source_metadata
)
SELECT
    'test-depth-' || index,
    'i66',
    'test-depth-' || index,
    CASE WHEN index IN (12, 13) THEN 'exit' ELSE 'entry' END,
    'EB',
    'Traversal fixture ' || index,
    ARRAY[]::text[],
    '{"test_fixture":true}'::jsonb
FROM generate_series(0, 13) AS index;

INSERT INTO oracle.toll_connection (
    connection_id, from_point_id, to_point_id, connection_type, source_metadata
)
SELECT
    'test-depth-edge-' || index,
    'test-depth-' || index,
    'test-depth-' || (index + 1),
    'within_facility',
    '{"test_fixture":true}'::jsonb
FROM generate_series(0, 12) AS index;

INSERT INTO oracle.toll_connection VALUES (
    'test-depth-cycle', 'test-depth-6', 'test-depth-2',
    'within_facility', NULL, NULL, '{"test_fixture":true}'::jsonb
);

INSERT INTO oracle.toll_route_point (
    point_id, network_id, source_node_id, point_type, direction,
    label, aliases, source_metadata
) VALUES
    (
        'test-limit-i95-origin', 'i95', 'test-limit-origin', 'entry', 'NB',
        'Traversal-priority origin', ARRAY[]::text[], '{"test_fixture":true}'::jsonb
    ),
    (
        'test-limit-i95-destination', 'i95', 'test-limit-destination', 'exit', 'NB',
        'Traversal-priority destination', ARRAY[]::text[],
        '{"test_fixture":true}'::jsonb
    );

INSERT INTO oracle.toll_connection VALUES
    (
        'test-limit-short-unknown',
        'test-limit-i95-origin', 'test-limit-i95-destination',
        'within_facility', 'NB', NULL, '{"test_fixture":true}'::jsonb
    ),
    (
        'test-limit-long-frontier',
        'test-limit-i95-origin', 'test-depth-1',
        'general_purpose_gap', NULL, NULL, '{"test_fixture":true}'::jsonb
    );

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('test-depth-0', 'test-depth-12');
    IF result.status <> 'valid' OR cardinality(result.connection_ids) <> 12 THEN
        RAISE EXCEPTION '12-edge route did not succeed: %', row_to_json(result);
    END IF;
    SELECT * INTO result
    FROM oracle.validate_toll_route('test-depth-0', 'test-depth-13');
    IF result.status <> 'traversal_limit_exceeded'
       OR cardinality(result.connection_ids) <> 0 THEN
        RAISE EXCEPTION '13-edge route did not report traversal limit: %',
            row_to_json(result);
    END IF;
    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'test-limit-i95-origin', 'test-limit-i95-destination'
    );
    IF result.status <> 'traversal_limit_exceeded' THEN
        RAISE EXCEPTION 'truncated traversal lost to an inconclusive path: %',
            row_to_json(result);
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute'
);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'test-limit-i95-origin', 'test-limit-i95-destination'
    );
    IF result.status <> 'valid' THEN
        RAISE EXCEPTION 'proven valid path did not outrank traversal limit: %',
            row_to_json(result);
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'CLOSED', transaction_timestamp() - interval '19 minutes 59.5 seconds'
);
SELECT pg_sleep(1);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'unknown_availability' THEN
        RAISE EXCEPTION 'freshness incorrectly used transaction time';
    END IF;
END $$;

ROLLBACK;

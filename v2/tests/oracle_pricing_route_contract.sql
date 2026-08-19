\set ON_ERROR_STOP on

BEGIN;

CREATE FUNCTION pg_temp.set_i95_state(
    northbound_status text,
    southbound_status text
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    source_time timestamptz := statement_timestamp() - interval '1 minute';
BEGIN
    TRUNCATE pricing.trip_pricing_i95;
    INSERT INTO pricing.trip_pricing_i95 (
        interval_end_at, current_at, calculated_at, corridor_id,
        corridor_name, od_pair_id, od_pair_name, start_zone_id,
        start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
        link_status, s3_key
    ) VALUES
        (
            source_time, source_time, source_time, 95, 'I-95-NB', 1132,
            'NB direction sentinel', 1, 'A', 2, 'B', 1.00,
            northbound_status, 'test/pricing-route-nb.csv'
        ),
        (
            source_time, source_time, source_time, 95, 'I-95-SB', 1151,
            'SB direction sentinel', 3, 'C', 4, 'D', 1.00,
            southbound_status, 'test/pricing-route-sb.csv'
        );
END
$$;

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['i66:1:entry:EB', 'i66:4:exit:EB'],
        ARRAY['source:i66:EB:1:4']
    );
    IF result.status <> 'valid'
       OR result.reason IS NOT NULL
       OR result.point_ids IS DISTINCT FROM
          ARRAY['i66:1:entry:EB', 'i66:4:exit:EB']::text[]
       OR result.connection_ids IS DISTINCT FROM
          ARRAY['source:i66:EB:1:4']::text[]
       OR result.facility_legs IS DISTINCT FROM jsonb_build_array(
           jsonb_build_object(
               'route_step_id', 'step-1',
               'facility', 'i66',
               'point_ids', jsonb_build_array(
                   'i66:1:entry:EB', 'i66:4:exit:EB'
               ),
               'connection_ids', jsonb_build_array('source:i66:EB:1:4'),
               'pricing_key', jsonb_build_object(
                   'source_route_key', 'EB:1:4',
                   'start_zone_id', 3100,
                   'end_zone_id', 3100
               )
           )
       ) THEN
        RAISE EXCEPTION 'I-66 pricing route changed: %', row_to_json(result);
    END IF;
END
$$;

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_pricing_route(NULL, NULL);
    IF result.status <> 'invalid_route'
       OR result.reason->>'code' <> 'route_required' THEN
        RAISE EXCEPTION 'null route was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(ARRAY[]::text[], ARRAY[]::text[]);
    IF result.reason->>'code' <> 'route_required' THEN
        RAISE EXCEPTION 'empty route was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY[['i66:1:entry:EB', 'i66:4:exit:EB']],
        ARRAY['source:i66:EB:1:4']
    );
    IF result.reason->>'code' <> 'route_shape_mismatch' THEN
        RAISE EXCEPTION 'multidimensional route was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        '[0:1]={i66:1:entry:EB,i66:4:exit:EB}'::text[],
        ARRAY['source:i66:EB:1:4']
    );
    IF result.reason->>'code' <> 'route_shape_mismatch' THEN
        RAISE EXCEPTION 'non-1-based route was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['i66:1:entry:EB', NULL]::text[],
        ARRAY['source:i66:EB:1:4']
    );
    IF result.reason->>'code' <> 'route_shape_mismatch' THEN
        RAISE EXCEPTION 'route with null point was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['i66:1:entry:EB', 'i66:4:exit:EB'],
        ARRAY[NULL]::text[]
    );
    IF result.reason->>'code' <> 'route_shape_mismatch' THEN
        RAISE EXCEPTION 'route with null connection was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        array_fill('point'::text, ARRAY[14]),
        array_fill('connection'::text, ARRAY[13])
    );
    IF result.reason->>'code' <> 'route_shape_mismatch' THEN
        RAISE EXCEPTION 'oversized route was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['i66:1:entry:EB', 'i66:1:entry:EB'],
        ARRAY['source:i66:EB:1:4']
    );
    IF result.reason->>'code' <> 'route_shape_mismatch' THEN
        RAISE EXCEPTION 'cyclic route was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['i66:1:entry:EB', 'i66:4:exit:EB'],
        ARRAY['wrong-connection']
    );
    IF result.reason->>'code' <> 'route_not_canonical'
       OR cardinality(result.point_ids) <> 0
       OR result.facility_legs <> '[]'::jsonb THEN
        RAISE EXCEPTION 'noncanonical route was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['unknown-origin', 'i66:4:exit:EB'],
        ARRAY['wrong-connection']
    );
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'origin_not_found' THEN
        RAISE EXCEPTION 'endpoint failure was not preserved';
    END IF;
END
$$;

SELECT pg_temp.set_i95_state('NORTHBOUND_OPEN', 'CLOSED');

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['i95:203NO', 'i495:181ND'],
        ARRAY['source:i95_shared:Northbound:203NO:181ND']
    );
    IF result.status <> 'valid'
       OR jsonb_array_length(result.facility_legs) <> 2
       OR result.facility_legs->0->>'facility' <> 'i95_i495'
       OR result.facility_legs->0->'pricing_key'->>'od_pair_id' <> '1144'
       OR result.facility_legs->1->'pricing_key'->>'od_pair_id' <> '1092'
       OR result.facility_legs->0->'point_ids' <> jsonb_build_array(
           'i95:203NO', 'i495:192NO'
       )
       OR result.facility_legs->1->'point_ids' <> jsonb_build_array(
           'i495:192NO', 'i495:181ND'
       )
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements(result.facility_legs) AS leg(value)
           WHERE leg.value->>'facility' IS NULL
       ) THEN
        RAISE EXCEPTION 'cross-facility ODs changed: %', row_to_json(result);
    END IF;
END
$$;

SELECT pg_temp.set_i95_state('CLOSED', 'SOUTHBOUND_OPEN');

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['i95:203NO', 'i495:181ND'],
        ARRAY['source:i95_shared:Northbound:203NO:181ND']
    );
    IF result.status <> 'currently_unavailable'
       OR result.reason->>'code' <> 'i95_opposite_direction_open'
       OR result.facility_legs <> '[]'::jsonb THEN
        RAISE EXCEPTION 'unavailable canonical route changed: %',
            row_to_json(result);
    END IF;
END
$$;

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['greenway:1:entry:EB', 'greenway:28:exit:EB'],
        ARRAY['source:greenway:EB:1:28']
    );
    IF result.status <> 'valid'
       OR jsonb_array_length(result.facility_legs) <> 1
       OR result.facility_legs->0->>'facility' <> 'greenway'
       OR result.facility_legs->0->'pricing_key'->>'charge_index' <> '1'
       OR jsonb_path_exists(
           result.facility_legs, '$.**.price_peak_usd'
       ) THEN
        RAISE EXCEPTION 'Greenway discrete charge changed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY['dtr:10:entry:EB', 'dtr:16:exit:EB'],
        ARRAY['source:dtr:EB:10:16']
    );
    IF result.status <> 'valid'
       OR jsonb_array_length(result.facility_legs) <> 3 THEN
        RAISE EXCEPTION 'DTR charge expansion changed: %', row_to_json(result);
    END IF;
END
$$;

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY[
            'greenway:1:entry:EB',
            'greenway:28:exit:EB',
            'dtr:28:entry:EB',
            'dtr:66:exit:EB',
            'i66:6:entry:EB',
            'i66:10:exit:EB'
        ],
        ARRAY[
            'source:greenway:EB:1:28',
            'greenway_to_dtr',
            'source:dtr:EB:28:66',
            'dulles_toll_road_to_i66',
            'source:i66:EB:6:10'
        ]
    );
    IF result.status <> 'valid'
       OR result.facility_legs IS DISTINCT FROM jsonb_build_array(
           jsonb_build_object(
               'route_step_id', 'step-1',
               'facility', 'greenway',
               'point_ids', jsonb_build_array(
                   'greenway:1:entry:EB', 'greenway:28:exit:EB'
               ),
               'connection_ids', jsonb_build_array(
                   'source:greenway:EB:1:28'
               ),
               'pricing_key', jsonb_build_object(
                   'source_route_key', 'EB:1:28', 'charge_index', 1
               )
           ),
           jsonb_build_object(
               'route_step_id', 'step-2',
               'facility', 'dtr',
               'point_ids', jsonb_build_array(
                   'dtr:28:entry:EB', 'dtr:66:exit:EB'
               ),
               'connection_ids', jsonb_build_array(
                   'source:dtr:EB:28:66'
               ),
               'pricing_key', jsonb_build_object(
                   'source_route_key', 'EB:28:66', 'charge_index', 1
               )
           ),
           jsonb_build_object(
               'route_step_id', 'step-3',
               'facility', 'i66',
               'point_ids', jsonb_build_array(
                   'i66:6:entry:EB', 'i66:10:exit:EB'
               ),
               'connection_ids', jsonb_build_array(
                   'source:i66:EB:6:10'
               ),
               'pricing_key', jsonb_build_object(
                   'source_route_key', 'EB:6:10',
                   'start_zone_id', 3110,
                   'end_zone_id', 3110
               )
           )
       ) THEN
        RAISE EXCEPTION 'multi-facility component ordering changed: %',
            row_to_json(result);
    END IF;
END
$$;

DO $$
DECLARE
    result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        ARRAY[
            'dtr:66:entry:WB',
            'dtr:28:exit:WB',
            'greenway:28:entry:WB',
            'greenway:1:exit:WB'
        ],
        ARRAY[
            'source:dtr:WB:66:28',
            'dtr_to_greenway',
            'source:greenway:WB:28:1'
        ]
    );
    IF result.status <> 'valid'
       OR result.facility_legs IS DISTINCT FROM jsonb_build_array(
           jsonb_build_object(
               'route_step_id', 'step-1',
               'facility', 'dtr',
               'point_ids', jsonb_build_array(
                   'dtr:66:entry:WB', 'dtr:28:exit:WB'
               ),
               'connection_ids', jsonb_build_array('source:dtr:WB:66:28'),
               'pricing_key', jsonb_build_object(
                   'source_route_key', 'WB:66:28', 'charge_index', 1
               )
           ),
           jsonb_build_object(
               'route_step_id', 'step-2',
               'facility', 'greenway',
               'point_ids', jsonb_build_array(
                   'greenway:28:entry:WB', 'greenway:1:exit:WB'
               ),
               'connection_ids', jsonb_build_array(
                   'source:greenway:WB:28:1'
               ),
               'pricing_key', jsonb_build_object(
                   'source_route_key', 'WB:28:1', 'charge_index', 1
               )
           )
       ) THEN
        RAISE EXCEPTION 'westbound Greenway/DTR separation changed: %',
            row_to_json(result);
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM oracle.route_pricing_component AS component
        JOIN oracle.toll_connection AS connection USING (connection_id)
        WHERE connection.connection_type IN ('toll_handoff', 'airport_access')
    ) OR EXISTS (
        SELECT 1
        FROM oracle.route_pricing_component
        GROUP BY connection_id
        HAVING count(DISTINCT facility) <> 1
    ) OR (
        SELECT charge
        FROM oracle.route_pricing_component
        WHERE connection_id = 'source:greenway:EB:1:28'
    ) IS DISTINCT FROM jsonb_build_object(
        'label', 'Mainline plaza',
        'price_off_peak_usd', '7.25',
        'price_peak_usd', '7.80'
    ) OR NOT EXISTS (
        SELECT 1
        FROM oracle.route_pricing_component
        WHERE od_pair_id BETWEEN 1374 AND 1389
    ) THEN
        RAISE EXCEPTION 'route pricing component view is incomplete';
    END IF;
END
$$;

DO $$
DECLARE
    parity_failures integer;
BEGIN
    SELECT count(*) INTO parity_failures
    FROM oracle.toll_route_point AS origin
    CROSS JOIN oracle.toll_route_point AS destination
    CROSS JOIN LATERAL oracle.validate_toll_route(
        origin.point_id, destination.point_id
    ) AS public_route
    CROSS JOIN LATERAL oracle.resolve_toll_route(
        origin.point_id, destination.point_id
    ) AS resolved_route
    WHERE origin.point_type IN ('entry', 'airport')
      AND destination.point_type IN ('exit', 'airport')
      AND to_jsonb(public_route) IS DISTINCT FROM to_jsonb(resolved_route);

    IF parity_failures <> 0 THEN
        RAISE EXCEPTION 'public route wrapper differs from shared resolver: %',
            parity_failures;
    END IF;
END
$$;

ROLLBACK;

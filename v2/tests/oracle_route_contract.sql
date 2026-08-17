\set ON_ERROR_STOP on

BEGIN;

CREATE FUNCTION pg_temp.set_i95_state(
    northbound_status text,
    southbound_status text,
    source_calculated_at timestamptz,
    mismatch_intervals boolean DEFAULT false,
    northbound_corridor text DEFAULT 'I-95-NB',
    southbound_corridor text DEFAULT 'I-95-SB'
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
            northbound_corridor, 1132, 'NB direction sentinel', 1, 'A', 2, 'B',
            1.00, northbound_status, 'test/oracle-nb.csv'
        ),
        (
            source_interval - CASE WHEN mismatch_intervals THEN interval '1 minute'
                                   ELSE interval '0 seconds' END,
            source_interval, source_calculated_at, 95,
            southbound_corridor, 1151, 'SB direction sentinel', 3, 'C', 4, 'D',
            1.00, southbound_status, 'test/oracle-sb.csv'
        );
END
$$;

CREATE FUNCTION pg_temp.structurally_reaches(
    origin_id text,
    destination_id text
) RETURNS boolean
LANGUAGE sql
STABLE
AS $$
WITH RECURSIVE walk AS (
    SELECT origin_id AS point_id, ARRAY[origin_id]::text[] AS visited, 0 AS depth
    UNION ALL
    SELECT
        connection.to_point_id,
        walk.visited || connection.to_point_id,
        walk.depth + 1
    FROM walk
    JOIN oracle.toll_connection AS connection
      ON connection.from_point_id = walk.point_id
    WHERE walk.depth < 12
      AND NOT connection.to_point_id = ANY(walk.visited)
)
SELECT EXISTS (
    SELECT 1 FROM walk
    WHERE point_id = destination_id AND depth > 0
)
$$;

DO $$
DECLARE
    result record;
    alternatives jsonb;
    public_keys text[];
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'i66:4:exit:EB');
    IF result.status <> 'valid' OR cardinality(result.connection_ids) <> 1
       OR result.reason IS NOT NULL
       OR result.general_purpose_gaps <> '[]'::jsonb
       OR result.i95_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'ordinary I-66 route failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:4:exit:EB', 'i66:4:exit:EB');
    alternatives := result.reason->'details'->'alternatives';
    SELECT array_agg(key ORDER BY key) INTO public_keys
    FROM jsonb_object_keys(alternatives->0) AS key;
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'origin_not_entry'
       OR result.reason->'details'->>'point_id' <> 'i66:4:exit:EB'
       OR result.reason->'details'->>'point_type' <> 'exit'
       OR result.reason->'details'->'allowed_point_types'
          <> jsonb_build_array('entry', 'airport')
       OR alternatives->0->>'point_id' <> 'i66:2:entry:EB'
       OR alternatives->1->>'point_id' <> 'i66:3:entry:EB'
       OR alternatives->0->'location' <> 'null'::jsonb
       OR public_keys <> ARRAY[
           'aliases', 'direction', 'label', 'location', 'network_id',
           'point_id', 'point_type', 'source_node_id'
       ]::text[]
       OR cardinality(result.point_ids) <> 0
       OR cardinality(result.connection_ids) <> 0
       OR cardinality(result.connection_types) <> 0
       OR result.general_purpose_gaps <> '[]'::jsonb
       OR result.i95_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'invalid origin alternatives were wrong: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route(NULL, 'i66:4:exit:EB');
    IF result.status <> 'invalid_origin'
       OR result.reason IS DISTINCT FROM
          '{"code":"origin_required","details":{}}'::jsonb THEN
        RAISE EXCEPTION 'missing origin reason was not explicit';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('unknown-origin', 'i66:4:exit:EB');
    IF result.status <> 'invalid_origin'
       OR result.reason IS DISTINCT FROM jsonb_build_object(
           'code', 'origin_not_found',
           'details', jsonb_build_object('point_id', 'unknown-origin')
       ) THEN
        RAISE EXCEPTION 'unknown origin reason was not explicit';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'i66:17:entry:WB');
    alternatives := result.reason->'details'->'alternatives';
    IF result.status <> 'invalid_destination'
       OR result.reason->>'code' <> 'destination_not_exit'
       OR result.reason->'details'->>'point_id' <> 'i66:17:entry:WB'
       OR alternatives->0->>'point_id' <> 'i66:12:exit:EB'
       OR alternatives->1->>'point_id' <> 'i66:13:exit:EB'
       OR jsonb_array_length(alternatives) <> 2 THEN
        RAISE EXCEPTION 'invalid destination alternatives were wrong: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', NULL);
    IF result.status <> 'invalid_destination'
       OR result.reason IS DISTINCT FROM
          '{"code":"destination_required","details":{}}'::jsonb THEN
        RAISE EXCEPTION 'missing destination reason was not explicit';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'unknown-destination');
    IF result.status <> 'invalid_destination'
       OR result.reason IS DISTINCT FROM jsonb_build_object(
           'code', 'destination_not_found',
           'details', jsonb_build_object('point_id', 'unknown-destination')
       ) THEN
        RAISE EXCEPTION 'unknown destination reason was not explicit';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'unknown_availability'
       OR result.reason IS DISTINCT FROM jsonb_build_object(
           'code', 'i95_missing_source',
           'details', jsonb_build_object(
               'required_i95_directions', ARRAY['NB']::text[],
               'availability', 'unknown'
           )
       )
       OR result.i95_evidence <> jsonb_build_object(
           'availability', 'unknown', 'reason', 'missing_source'
       ) THEN
        RAISE EXCEPTION 'empty I-95 feed did not report missing source: %',
            row_to_json(result);
    END IF;
END $$;

DO $$
DECLARE
    result record;
    alternatives jsonb;
    alternative jsonb;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:9:entry:EB', 'i66:4:exit:WB');
    alternatives := result.reason->'details'->'alternatives';
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'origin_ramp_incompatible'
       OR alternatives->0->>'point_id' <> 'i66:12:entry:WB'
       OR alternatives->1->>'point_id' <> 'i66:11:entry:WB' THEN
        RAISE EXCEPTION 'wrong-direction origin was not recoverable: %',
            row_to_json(result);
    END IF;
    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:9:entry:EB', 'i66:4:exit:EB');
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'origin_ramp_incompatible'
       OR jsonb_array_length(
        oracle.ramp_alternatives(
            'i66:4:exit:EB', 'i66:9:entry:EB', false
        )
    ) = 0 THEN
        RAISE EXCEPTION 'origin did not take precedence when both endpoints conflicted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:180SO', 'i495:1819ND');
    alternatives := result.reason->'details'->'alternatives';
    IF result.status <> 'invalid_destination'
       OR result.reason->>'code' <> 'destination_ramp_incompatible'
       OR alternatives->0->>'point_id' <> 'i495:182SD'
       OR alternatives->1->>'point_id' <> 'i495:184SD'
       OR alternatives->0->'location'->>'type' <> 'Point' THEN
        RAISE EXCEPTION 'wrong-direction destination was not recoverable: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:206SO', 'i95:228ND');
    alternatives := result.reason->'details'->'alternatives';
    IF result.status <> 'invalid_destination'
       OR result.reason->>'code' <> 'destination_ramp_incompatible'
       OR alternatives->0->>'point_id' <> 'i95:220SD'
       OR alternatives->1->>'point_id' <> 'i95:218SD' THEN
        RAISE EXCEPTION 'reviewed I-95 destination recovery changed: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'greenway:2B:exit:WB', 'greenway:8:exit:EB'
    );
    alternatives := result.reason->'details'->'alternatives';
    IF alternatives->0->>'point_id' <> 'greenway:2A:entry:EB'
       OR alternatives->1->>'point_id' <> 'greenway:3:entry:EB'
       OR jsonb_array_length(alternatives) <> 2 THEN
        RAISE EXCEPTION 'reviewed Greenway recovery choices changed: %',
            row_to_json(result);
    END IF;

    FOR alternative IN
        SELECT value FROM jsonb_array_elements(alternatives)
    LOOP
        IF alternative->>'network_id' <> 'greenway'
           OR alternative->>'point_type' <> 'entry'
           OR NOT pg_temp.structurally_reaches(
               alternative->>'point_id', 'greenway:8:exit:EB'
           ) THEN
            RAISE EXCEPTION 'origin alternative was not structurally compatible: %',
                alternative;
        END IF;
    END LOOP;

    alternatives := oracle.ramp_alternatives(
        'i495:1819ND', 'i495:180SO', false
    );
    FOR alternative IN
        SELECT value FROM jsonb_array_elements(alternatives)
    LOOP
        IF alternative->>'network_id' <> 'i495'
           OR alternative->>'point_type' <> 'exit'
           OR NOT pg_temp.structurally_reaches(
               'i495:180SO', alternative->>'point_id'
           ) THEN
            RAISE EXCEPTION 'destination alternative was not structurally compatible: %',
                alternative;
        END IF;
    END LOOP;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_iad', 'airport_dca');
    IF result.status <> 'no_supported_route'
       OR result.reason IS DISTINCT FROM jsonb_build_object(
           'code', 'no_supported_route',
           'details', jsonb_build_object(
               'origin_point_id', 'airport_iad',
               'destination_point_id', 'airport_dca'
           )
       ) THEN
        RAISE EXCEPTION 'unsupported airport route changed: %', row_to_json(result);
    END IF;
END $$;

DO $$
DECLARE
    result record;
    unknown_alternatives jsonb;
    open_alternatives jsonb;
    closed_alternatives jsonb;
    stale_alternatives jsonb;
BEGIN
    TRUNCATE pricing.trip_pricing_i95;
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    unknown_alternatives := result.reason->'details'->'alternatives';

    PERFORM pg_temp.set_i95_state(
        'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    open_alternatives := result.reason->'details'->'alternatives';

    PERFORM pg_temp.set_i95_state(
        'CLOSED', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    closed_alternatives := result.reason->'details'->'alternatives';

    PERFORM pg_temp.set_i95_state(
        'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '21 minutes'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    stale_alternatives := result.reason->'details'->'alternatives';

    IF unknown_alternatives IS DISTINCT FROM open_alternatives
       OR open_alternatives IS DISTINCT FROM closed_alternatives
       OR closed_alternatives IS DISTINCT FROM stale_alternatives
       OR open_alternatives->0->>'point_id' <> 'i95:218NO'
       OR open_alternatives->1->>'point_id' <> 'i95:217NO' THEN
        RAISE EXCEPTION 'I-95 evidence changed ramp alternatives';
    END IF;

    PERFORM pg_temp.set_i95_state(
        'CLOSED', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218NO', 'i95:201ND');
    IF result.status <> 'currently_unavailable'
       OR result.i95_evidence->>'availability' <> 'closed' THEN
        RAISE EXCEPTION 'selected ramp bypassed normal closed-state behavior: %',
            row_to_json(result);
    END IF;

    PERFORM pg_temp.set_i95_state(
        'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218NO', 'i95:201ND');
    IF result.status <> 'valid'
       OR result.i95_evidence->>'availability' <> 'northbound' THEN
        RAISE EXCEPTION 'selected ramp skipped normal open-state behavior: %',
            row_to_json(result);
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
       OR result.reason IS NOT NULL
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
    FROM oracle.validate_toll_route('airport_dca', 'i95:224ND');
    IF result.status <> 'valid'
       OR result.connection_ids[1] <> 'dca_to_i95_north'
       OR result.i95_evidence->>'availability' <> 'northbound' THEN
        RAISE EXCEPTION 'DCA northbound departure failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_dca', 'i95:210SD');
    IF result.status <> 'currently_unavailable'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_opposite_direction_open'
       OR result.connection_ids[1] <> 'dca_to_i95_south' THEN
        RAISE EXCEPTION 'northbound state allowed DCA southbound departure: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:185SO', 'i95:217SD');
    IF result.status <> 'currently_unavailable'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_opposite_direction_open'
       OR result.reason->'details'->'required_i95_directions'
          <> jsonb_build_array('SB')
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

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_iad', 'i95:205SD');
    IF result.status <> 'currently_unavailable'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_opposite_direction_open'
       OR result.connection_types
          <> ARRAY['airport_access', 'general_purpose_gap']::text[]
       OR result.general_purpose_gaps->0->>'boundary_point_id' <> 'i495:192SD'
       OR result.general_purpose_gaps->0->>'role' <> 'suffix'
       OR result.general_purpose_gaps->0->>'i95_direction' <> 'SB'
       OR (result.general_purpose_gaps->0->>'fallback_required')::boolean
            IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'northbound state allowed IAD-to-Backlick route: %',
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
       OR result.reason IS DISTINCT FROM jsonb_build_object(
           'code', 'i95_opposite_direction_open',
           'details', jsonb_build_object(
               'required_i95_directions', ARRAY['NB']::text[],
               'availability', 'southbound'
           )
       )
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
    FROM oracle.validate_toll_route('airport_dca', 'i95:210SD');
    IF result.status <> 'valid'
       OR result.connection_ids[1] <> 'dca_to_i95_south'
       OR result.i95_evidence->>'availability' <> 'southbound' THEN
        RAISE EXCEPTION 'DCA southbound departure failed: %', row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_dca', 'i95:224ND');
    IF result.status <> 'currently_unavailable'
       OR result.connection_ids[1] <> 'dca_to_i95_north' THEN
        RAISE EXCEPTION 'southbound state allowed DCA northbound departure: %',
            row_to_json(result);
    END IF;


    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:234NO', 'i495:185ND');
    IF result.status <> 'currently_unavailable'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_opposite_direction_open'
       OR result.reason->'details'->'required_i95_directions'
          <> jsonb_build_array('NB')
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

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_iad', 'i95:205SD');
    IF result.status <> 'valid'
       OR result.reason IS NOT NULL
       OR result.connection_types
          <> ARRAY['airport_access', 'general_purpose_gap']::text[]
       OR (result.general_purpose_gaps->0->>'fallback_required')::boolean
            IS DISTINCT FROM false
       OR result.i95_evidence->>'availability' <> 'southbound' THEN
        RAISE EXCEPTION 'southbound state rejected IAD-to-Backlick route: %',
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
       OR result.reason IS DISTINCT FROM jsonb_build_object(
           'code', 'i95_fully_closed',
           'details', jsonb_build_object(
               'required_i95_directions', ARRAY['NB']::text[],
               'availability', 'closed'
           )
       )
       OR result.i95_evidence->>'availability' <> 'closed' THEN
        RAISE EXCEPTION 'known closure was not distinguished';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_dca', 'i95:224ND');
    IF result.status <> 'currently_unavailable'
       OR result.connection_ids[1] <> 'dca_to_i95_north' THEN
        RAISE EXCEPTION 'closure allowed DCA northbound departure';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_dca', 'i95:210SD');
    IF result.status <> 'currently_unavailable'
       OR result.connection_ids[1] <> 'dca_to_i95_south' THEN
        RAISE EXCEPTION 'closure allowed DCA southbound departure';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_iad', 'i95:205SD');
    IF result.status <> 'currently_unavailable'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_fully_closed'
       OR result.reason->'details'->'required_i95_directions'
          <> jsonb_build_array('SB')
       OR (result.general_purpose_gaps->0->>'fallback_required')::boolean
            IS DISTINCT FROM true
       OR result.i95_evidence->>'availability' <> 'closed' THEN
        RAISE EXCEPTION 'closure allowed IAD-to-Backlick route: %',
            row_to_json(result);
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
       OR result.reason->>'code' IS DISTINCT FROM 'i95_indeterminate_state'
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
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_stale_evidence' THEN
        RAISE EXCEPTION 'stale state was accepted';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:185SO', 'i95:217SD');
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_stale_evidence'
       OR result.general_purpose_gaps->0->>'fallback_required' IS NOT NULL
       OR result.i95_evidence->>'availability' <> 'unknown' THEN
        RAISE EXCEPTION 'unknown state did not preserve safe TP1 fallback: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_iad', 'i95:205SD');
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_stale_evidence'
       OR result.reason->'details'->'required_i95_directions'
          <> jsonb_build_array('SB')
       OR result.general_purpose_gaps->0->>'fallback_required' IS NOT NULL
       OR result.i95_evidence->>'availability' <> 'unknown' THEN
        RAISE EXCEPTION 'stale state resolved IAD-to-Backlick route: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_dca', 'i95:224ND');
    IF result.status <> 'unknown_availability'
       OR result.connection_ids[1] <> 'dca_to_i95_north' THEN
        RAISE EXCEPTION 'DCA northbound departure did not preserve uncertainty';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('airport_dca', 'i95:210SD');
    IF result.status <> 'unknown_availability'
       OR result.connection_ids[1] <> 'dca_to_i95_south' THEN
        RAISE EXCEPTION 'DCA southbound departure did not preserve uncertainty';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:191NO', 'airport_dca');
    IF result.status <> 'unknown_availability'
       OR NOT 'i95_north_to_dca' = ANY(result.connection_ids)
       OR result.general_purpose_gaps->0->>'fallback_required' IS NOT NULL
       OR result.i95_evidence->>'availability' <> 'unknown' THEN
        RAISE EXCEPTION 'mixed TP1/DCA path ignored top-level uncertainty: %',
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
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_interval_mismatch' THEN
        RAISE EXCEPTION 'mismatched intervals were accepted';
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() + interval '1 minute'
);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_future_evidence' THEN
        RAISE EXCEPTION 'future evidence reason was not explicit';
    END IF;
END $$;

SELECT pg_temp.set_i95_state(
    'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute',
    false, 'I-95-SB', 'I-95-SB'
);

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:202NO', 'i95:201ND');
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_invalid_source' THEN
        RAISE EXCEPTION 'invalid source reason was not explicit';
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
    FROM oracle.validate_toll_route('i95:2233SO', 'airport_dca');
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'origin_ramp_incompatible'
       OR result.reason->'details'->'alternatives'->0->>'point_id'
          <> 'i95:225NO'
       OR cardinality(result.connection_ids) <> 0 THEN
        RAISE EXCEPTION 'DCA southbound arrival was not rejected: %',
            row_to_json(result);
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

INSERT INTO oracle.toll_route_point (
    point_id, network_id, source_node_id, point_type, direction,
    label, aliases, source_metadata
) VALUES
    (
        'test-tie-submitted', 'i66', 'test-tie-submitted', 'exit', 'EB',
        'Tie submitted', ARRAY[]::text[], '{"test_fixture":true}'::jsonb
    ),
    (
        'test-tie-a', 'i66', 'test-tie-a', 'entry', 'EB',
        'Tie A', ARRAY[]::text[], '{"test_fixture":true}'::jsonb
    ),
    (
        'test-tie-b', 'i66', 'test-tie-b', 'entry', 'EB',
        'Tie B', ARRAY[]::text[], '{"test_fixture":true}'::jsonb
    ),
    (
        'test-tie-c', 'i66', 'test-tie-c', 'entry', 'EB',
        'Tie C', ARRAY[]::text[], '{"test_fixture":true}'::jsonb
    ),
    (
        'test-tie-destination', 'i66', 'test-tie-destination', 'exit', 'EB',
        'Tie destination', ARRAY[]::text[], '{"test_fixture":true}'::jsonb
    );

INSERT INTO oracle.toll_connection (
    connection_id, from_point_id, to_point_id, connection_type, source_metadata
) VALUES
    (
        'test-tie-edge-a', 'test-tie-a', 'test-tie-destination',
        'within_facility', '{"test_fixture":true}'::jsonb
    ),
    (
        'test-tie-edge-b', 'test-tie-b', 'test-tie-destination',
        'within_facility', '{"test_fixture":true}'::jsonb
    ),
    (
        'test-tie-edge-c', 'test-tie-c', 'test-tie-destination',
        'within_facility', '{"test_fixture":true}'::jsonb
    );

DO $$
DECLARE
    result record;
    first_alternatives jsonb;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('test-depth-0', 'test-depth-12');
    IF result.status <> 'valid' OR cardinality(result.connection_ids) <> 12 THEN
        RAISE EXCEPTION '12-edge route did not succeed: %', row_to_json(result);
    END IF;
    SELECT * INTO result
    FROM oracle.validate_toll_route('test-depth-0', 'test-depth-13');
    IF result.status <> 'traversal_limit_exceeded'
       OR result.reason IS DISTINCT FROM jsonb_build_object(
           'code', 'traversal_limit_exceeded',
           'details', jsonb_build_object(
               'origin_point_id', 'test-depth-0',
               'destination_point_id', 'test-depth-13',
               'maximum_connections', 12
           )
       )
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

    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'test-tie-submitted', 'test-tie-destination'
    );
    first_alternatives := result.reason->'details'->'alternatives';
    IF jsonb_array_length(first_alternatives) <> 2
       OR first_alternatives->0->>'point_id' <> 'test-tie-a'
       OR first_alternatives->1->>'point_id' <> 'test-tie-b' THEN
        RAISE EXCEPTION 'stable point-ID tie-break failed: %', row_to_json(result);
    END IF;
    SELECT * INTO result
    FROM oracle.validate_toll_route(
        'test-tie-submitted', 'test-tie-destination'
    );
    IF result.reason->'details'->'alternatives' IS DISTINCT FROM first_alternatives THEN
        RAISE EXCEPTION 'alternative ordering was not deterministic';
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
    IF result.status <> 'valid' OR result.reason IS NOT NULL THEN
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

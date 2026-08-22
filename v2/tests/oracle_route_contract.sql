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

CREATE FUNCTION pg_temp.assert_greenway_to_dca(
    expected_status text,
    expected_reason text,
    expected_availability text,
    expected_fallback boolean
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('greenway:1:entry:EB', 'airport_dca');

    IF result.status IS DISTINCT FROM expected_status
       OR result.reason->>'code' IS DISTINCT FROM expected_reason
       OR result.point_ids IS DISTINCT FROM ARRAY[
           'greenway:1:entry:EB',
           'greenway:28:exit:EB',
           'dtr:28:entry:EB',
           'dtr:1819:exit:EB',
           'i495:182SO',
           'i95:2239ND',
           'airport_dca'
       ]::text[]
       OR result.connection_ids IS DISTINCT FROM ARRAY[
           'source:greenway:EB:1:28',
           'greenway_to_dtr',
           'source:dtr:EB:28:1819',
           'dulles_toll_road_to_i495',
           'source:i95_shared:Southbound:182SO:2239ND',
           'i95_north_to_dca_from_i495_south'
       ]::text[]
       OR result.connection_types IS DISTINCT FROM ARRAY[
           'within_facility',
           'toll_handoff',
           'within_facility',
           'toll_handoff',
           'general_purpose_gap',
           'airport_access'
       ]::text[]
       OR result.general_purpose_gaps IS DISTINCT FROM jsonb_build_array(
           jsonb_build_object(
               'connection_id',
                   'source:i95_shared:Southbound:182SO:2239ND',
               'boundary_point_id', 'i495:192SD',
               'role', 'suffix',
               'i95_direction', 'NB',
               'fallback_required', expected_fallback
           )
       )
       OR result.i95_evidence->>'availability'
          IS DISTINCT FROM expected_availability THEN
        RAISE EXCEPTION 'Greenway-to-DCA golden changed: %', row_to_json(result);
    END IF;
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
    northbound_result jsonb;
    southbound_result jsonb;
    closed_result jsonb;
BEGIN
    PERFORM pg_temp.set_i95_state(
        'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT to_jsonb(route) INTO northbound_result
    FROM oracle.validate_toll_route('i95:206NO', 'i495:1859ND') AS route;

    PERFORM pg_temp.set_i95_state(
        'CLOSED', 'SOUTHBOUND_OPEN', statement_timestamp() - interval '1 minute'
    );
    SELECT to_jsonb(route) INTO southbound_result
    FROM oracle.validate_toll_route('i95:206NO', 'i495:1859ND') AS route;

    PERFORM pg_temp.set_i95_state(
        'CLOSED', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT to_jsonb(route) INTO closed_result
    FROM oracle.validate_toll_route('i95:206NO', 'i495:1859ND') AS route;

    IF northbound_result IS DISTINCT FROM southbound_result
       OR southbound_result IS DISTINCT FROM closed_result
       OR northbound_result->>'status' <> 'invalid_origin'
       OR northbound_result->'reason'->>'code'
          <> 'i95_northbound_requires_i495_restart'
       OR northbound_result->'reason'->'details' IS DISTINCT FROM
          jsonb_build_object(
              'point_id', 'i95:206NO',
              'point_type', 'entry',
              'suggested_restart_point_id', 'i495:192NO',
              'suggested_destination_point_id', 'i495:185ND'
          )
       OR cardinality(ARRAY(
              SELECT jsonb_array_elements_text(northbound_result->'point_ids')
          )) <> 0
       OR northbound_result->'i95_evidence' <> 'null'::jsonb THEN
        RAISE EXCEPTION 'northbound I-95 restart result changed: %',
            northbound_result;
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:212NO', 'i495:1859ND');
    IF result.reason->>'code' <> 'i95_northbound_requires_i495_restart'
       OR result.reason->'details'->>'point_id' <> 'i95:212NO'
       OR result.reason->'details'->>'suggested_destination_point_id'
          <> 'i495:185ND' THEN
        RAISE EXCEPTION 'second northbound I-95 origin did not use TP1NB restart';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:224NO', 'i495:1859ND');
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'origin_ramp_incompatible' THEN
        RAISE EXCEPTION 'north-of-junction origin received TP1NB restart: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:192NO', 'i495:185ND');
    IF result.status <> 'valid' OR result.i95_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'TP1NB-to-Westpark restart route failed: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:2233SO', 'airport_dca');
    IF result.reason->>'code' <> 'origin_ramp_incompatible' THEN
        RAISE EXCEPTION 'southbound incompatible-ramp behavior changed';
    END IF;

    TRUNCATE pricing.trip_pricing_i95;
END
$$;

DO $$
DECLARE
    result record;
    alternatives jsonb;
    alternative jsonb;
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
       OR alternatives->0->'location'->>'type' <> 'Point'
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
    FROM oracle.validate_toll_route('airport_iad', 'i66:9:entry:EB');
    alternatives := result.reason->'details'->'alternatives';
    IF result.status <> 'invalid_destination'
       OR result.reason->>'code' <> 'destination_not_exit'
       OR result.reason->'details'->>'point_id' <> 'i66:9:entry:EB'
       OR result.reason->'details'->>'point_type' <> 'entry'
       OR result.reason->'details'->'allowed_point_types'
          <> jsonb_build_array('exit', 'airport')
       OR jsonb_array_length(alternatives) <> 2
       OR alternatives->0->>'point_id' <> 'i66:12:exit:EB'
       OR alternatives->0->>'source_node_id' <> '12'
       OR alternatives->0->>'label' <> 'Fairfax Drive'
       OR alternatives->1->>'point_id' <> 'i66:11:exit:EB'
       OR alternatives->1->>'source_node_id' <> '11'
       OR alternatives->1->>'label' <> 'Washington Blvd'
       OR cardinality(result.point_ids) <> 0
       OR cardinality(result.connection_ids) <> 0
       OR cardinality(result.connection_types) <> 0
       OR result.general_purpose_gaps <> '[]'::jsonb
       OR result.i95_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'Glebe entry was accepted as a destination: %',
            row_to_json(result);
    END IF;
    FOR alternative IN
        SELECT value FROM jsonb_array_elements(alternatives)
    LOOP
        SELECT array_agg(key ORDER BY key) INTO public_keys
        FROM jsonb_object_keys(alternative) AS key;
        IF public_keys <> ARRAY[
               'aliases', 'direction', 'label', 'location', 'network_id',
               'point_id', 'point_type', 'source_node_id'
           ]::text[]
           OR alternative->>'network_id' <> 'i66'
           OR alternative->>'point_type' <> 'exit'
           OR alternative->>'direction' <> 'EB'
           OR alternative->'aliases' <> '[]'::jsonb
           OR alternative->'location'->>'type' <> 'Point'
           OR NOT pg_temp.structurally_reaches(
               'airport_iad', alternative->>'point_id'
           ) THEN
            RAISE EXCEPTION 'Glebe destination alternative was invalid: %',
                alternative;
        END IF;
    END LOOP;

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
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' <> 'i95_missing_source'
       OR result.connection_ids IS DISTINCT FROM ARRAY[
           'iad_to_i495_south',
           'source:i95_shared:Southbound:182SO:2239ND',
           'i95_north_to_dca_from_i495_south'
       ]::text[] THEN
        RAISE EXCEPTION 'IAD-to-DCA route changed: %', row_to_json(result);
    END IF;
END $$;

DO $$
DECLARE
    result record;
    unknown_alternatives jsonb;
    open_alternatives jsonb;
    closed_alternatives jsonb;
    stale_alternatives jsonb;
    backlick_unknown jsonb;
    backlick_northbound jsonb;
    backlick_southbound jsonb;
    backlick_closed jsonb;
    backlick_stale jsonb;
    backlick_alternatives jsonb;
    alternative jsonb;
    public_keys text[];
BEGIN
    TRUNCATE pricing.trip_pricing_i95;
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    unknown_alternatives := result.reason->'details'->'alternatives';
    SELECT to_jsonb(route) INTO backlick_unknown
    FROM oracle.validate_toll_route('i95:205SD', 'airport_iad') AS route;

    PERFORM pg_temp.set_i95_state(
        'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    open_alternatives := result.reason->'details'->'alternatives';
    SELECT to_jsonb(route) INTO backlick_northbound
    FROM oracle.validate_toll_route('i95:205SD', 'airport_iad') AS route;

    PERFORM pg_temp.set_i95_state(
        'CLOSED', 'SOUTHBOUND_OPEN', statement_timestamp() - interval '1 minute'
    );
    SELECT to_jsonb(route) INTO backlick_southbound
    FROM oracle.validate_toll_route('i95:205SD', 'airport_iad') AS route;

    PERFORM pg_temp.set_i95_state(
        'CLOSED', 'CLOSED', statement_timestamp() - interval '1 minute'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    closed_alternatives := result.reason->'details'->'alternatives';
    SELECT to_jsonb(route) INTO backlick_closed
    FROM oracle.validate_toll_route('i95:205SD', 'airport_iad') AS route;

    PERFORM pg_temp.set_i95_state(
        'NORTHBOUND_OPEN', 'CLOSED', statement_timestamp() - interval '21 minutes'
    );
    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:218SD', 'i95:201ND');
    stale_alternatives := result.reason->'details'->'alternatives';
    SELECT to_jsonb(route) INTO backlick_stale
    FROM oracle.validate_toll_route('i95:205SD', 'airport_iad') AS route;

    IF unknown_alternatives IS DISTINCT FROM open_alternatives
       OR open_alternatives IS DISTINCT FROM closed_alternatives
       OR closed_alternatives IS DISTINCT FROM stale_alternatives
       OR open_alternatives->0->>'point_id' <> 'i95:218NO'
       OR open_alternatives->1->>'point_id' <> 'i95:217NO' THEN
        RAISE EXCEPTION 'I-95 evidence changed ramp alternatives';
    END IF;

    IF backlick_unknown IS DISTINCT FROM backlick_northbound
       OR backlick_northbound IS DISTINCT FROM backlick_southbound
       OR backlick_southbound IS DISTINCT FROM backlick_closed
       OR backlick_closed IS DISTINCT FROM backlick_stale THEN
        RAISE EXCEPTION 'I-95 evidence changed the Backlick invalid-origin response';
    END IF;
    backlick_alternatives :=
        backlick_unknown->'reason'->'details'->'alternatives';
    IF backlick_unknown->>'status' <> 'invalid_origin'
       OR backlick_unknown->'reason'->>'code' <> 'origin_not_entry'
       OR backlick_unknown->'reason'->'details'->>'point_id' <> 'i95:205SD'
       OR backlick_unknown->'reason'->'details'->>'point_type' <> 'exit'
       OR backlick_unknown->'reason'->'details'->'allowed_point_types'
          <> jsonb_build_array('entry', 'airport')
       OR jsonb_array_length(backlick_alternatives) <> 2
       OR backlick_alternatives->0->>'point_id' <> 'i95:212NO'
       OR backlick_alternatives->0->>'source_node_id' <> '212NO'
       OR backlick_alternatives->0->>'label'
          <> 'I-95 Near Franconia-Springfield Pkwy NB'
       OR backlick_alternatives->1->>'point_id' <> 'i95:203NO'
       OR backlick_alternatives->1->>'source_node_id' <> '203NO'
       OR backlick_alternatives->1->>'label' <> 'Old Keene Mill Road/Route 644'
       OR backlick_unknown->'point_ids' <> '[]'::jsonb
       OR backlick_unknown->'connection_ids' <> '[]'::jsonb
       OR backlick_unknown->'connection_types' <> '[]'::jsonb
       OR backlick_unknown->'general_purpose_gaps' <> '[]'::jsonb
       OR backlick_unknown->'i95_evidence' <> 'null'::jsonb THEN
        RAISE EXCEPTION 'Backlick exit was accepted as an origin: %',
            backlick_unknown;
    END IF;
    FOR alternative IN
        SELECT value FROM jsonb_array_elements(backlick_alternatives)
    LOOP
        SELECT array_agg(key ORDER BY key) INTO public_keys
        FROM jsonb_object_keys(alternative) AS key;
        IF public_keys <> ARRAY[
               'aliases', 'direction', 'label', 'location', 'network_id',
               'point_id', 'point_type', 'source_node_id'
           ]::text[]
           OR alternative->>'network_id' <> 'i95'
           OR alternative->>'point_type' <> 'entry'
           OR alternative->>'direction' <> 'NB'
           OR alternative->'aliases' <> '[]'::jsonb
           OR alternative->'location'->>'type' <> 'Point'
           OR NOT pg_temp.structurally_reaches(
               alternative->>'point_id', 'airport_iad'
           ) THEN
            RAISE EXCEPTION 'Backlick origin alternative was invalid: %',
                alternative;
        END IF;
    END LOOP;

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

DO $$
DECLARE
    connector record;
    result record;
BEGIN
    FOR connector IN
        SELECT * FROM (VALUES
            ('i66:6:entry:EB', 'iad_to_i66'),
            ('dtr:66:entry:WB', 'iad_to_dtr_via_i66'),
            ('i495:182NO', 'iad_to_i495_north'),
            ('i495:182SO', 'iad_to_i495_south')
        ) AS expected(destination_id, connection_id)
    LOOP
        SELECT * INTO result
        FROM oracle.validate_toll_route(
            'airport_iad', connector.destination_id
        );
        IF result.status <> 'valid'
           OR result.reason IS NOT NULL
           OR result.point_ids
              <> ARRAY['airport_iad', connector.destination_id]
           OR result.connection_ids <> ARRAY[connector.connection_id]
           OR result.connection_types <> ARRAY['airport_access']
           OR result.general_purpose_gaps <> '[]'::jsonb
           OR result.i95_evidence IS NOT NULL THEN
            RAISE EXCEPTION 'IAD terminal connector failed: %',
                row_to_json(result);
        END IF;
    END LOOP;
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
    PERFORM pg_temp.assert_greenway_to_dca(
        'valid', NULL, 'northbound', false
    );

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
    FROM oracle.validate_toll_route('i95:234NO', 'i495:185ND');
    IF result.status <> 'valid'
       OR result.reason IS NOT NULL
       OR result.point_ids
          <> ARRAY['i95:234NO', 'i495:185ND']::text[]
       OR result.connection_ids
          <> ARRAY['source:i95_shared:Northbound:234NO:185ND']::text[]
       OR result.connection_types <> ARRAY['general_purpose_gap']::text[]
       OR result.general_purpose_gaps->0->>'boundary_point_id' <> 'i495:192NO'
       OR result.general_purpose_gaps->0->>'role' <> 'prefix'
       OR result.general_purpose_gaps->0->>'i95_direction' <> 'NB'
       OR (result.general_purpose_gaps->0->>'fallback_required')::boolean
            IS DISTINCT FROM false
       OR result.i95_evidence->>'availability' <> 'northbound' THEN
        RAISE EXCEPTION 'available TP1NB boundary route failed: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:185SO', 'i95:217SD');
    IF result.status <> 'currently_unavailable'
       OR result.reason->>'code' IS DISTINCT FROM 'i95_opposite_direction_open'
       OR result.reason->'details'->'required_i95_directions'
          <> jsonb_build_array('SB')
       OR result.point_ids
          <> ARRAY['i495:185SO', 'i95:217SD']::text[]
       OR result.connection_ids
          <> ARRAY['source:i95_shared:Southbound:185SO:217SD']::text[]
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
    PERFORM pg_temp.assert_greenway_to_dca(
        'currently_unavailable', 'i95_opposite_direction_open',
        'southbound', true
    );

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
       OR result.point_ids
          <> ARRAY['i95:234NO', 'i495:185ND']::text[]
       OR result.connection_ids
          <> ARRAY['source:i95_shared:Northbound:234NO:185ND']::text[]
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
       OR result.reason IS NOT NULL
       OR result.point_ids
          <> ARRAY['i495:185SO', 'i95:217SD']::text[]
       OR result.connection_ids
          <> ARRAY['source:i95_shared:Southbound:185SO:217SD']::text[]
       OR result.connection_types <> ARRAY['general_purpose_gap']::text[]
       OR result.general_purpose_gaps->0->>'boundary_point_id' <> 'i495:192SD'
       OR result.general_purpose_gaps->0->>'role' <> 'suffix'
       OR result.general_purpose_gaps->0->>'i95_direction' <> 'SB'
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
    PERFORM pg_temp.assert_greenway_to_dca(
        'currently_unavailable', 'i95_fully_closed', 'closed', true
    );

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
DECLARE
    fixture record;
    result record;
    handoff_index integer;
    tested_handoffs text[] := ARRAY[]::text[];
    configured_handoffs text[];
BEGIN
    FOR fixture IN
        SELECT *
        FROM (VALUES
            (
                'greenway:1:entry:EB', 'dtr:10:exit:EB',
                'greenway_to_dtr',
                'greenway:28:exit:EB', 'dtr:28:entry:EB'
            ),
            (
                'dtr:10:entry:WB', 'greenway:1:exit:WB',
                'dtr_to_greenway',
                'dtr:28:exit:WB', 'greenway:28:entry:WB'
            ),
            (
                'i66:11:entry:WB', 'i495:191SD',
                'i66_to_i495',
                'i66:5:exit:WB', 'i495:187SO'
            ),
            (
                'i66:11:entry:WB', 'i495:181ND',
                'i66_to_i495_north',
                'i66:5:exit:WB', 'i495:187NO'
            ),
            (
                'i495:191NO', 'i66:10:exit:EB',
                'i495_to_i66',
                'i495:187ND', 'i66:3:entry:EB'
            ),
            (
                'i495:180SO', 'i66:10:exit:EB',
                'i495_south_to_i66',
                'i495:187SD', 'i66:5:entry:EB'
            ),
            (
                'i66:11:entry:WB', 'dtr:28:exit:WB',
                'i66_to_dulles_toll_road',
                'i66:6:exit:WB', 'dtr:66:entry:WB'
            ),
            (
                'dtr:10:entry:EB', 'i66:10:exit:EB',
                'dulles_toll_road_to_i66',
                'dtr:66:exit:EB', 'i66:6:entry:EB'
            ),
            (
                'dtr:10:entry:EB', 'i495:185SD',
                'dulles_toll_road_to_i495',
                'dtr:1819:exit:EB', 'i495:182SO'
            ),
            (
                'dtr:10:entry:EB', 'i495:181ND',
                'dulles_toll_road_to_i495_north',
                'dtr:1819:exit:EB', 'i495:182NO'
            ),
            (
                'dtr:66:entry:WB', 'i495:181ND',
                'dulles_toll_road_westbound_to_i495_north',
                'dtr:1819:exit:WB', 'i495:182NO'
            ),
            (
                'i495:191NO', 'dtr:10:exit:WB',
                'i495_to_dulles_toll_road',
                'i495:182ND', 'dtr:1819:entry:WB'
            ),
            (
                'i495:180SO', 'dtr:10:exit:WB',
                'i495_south_to_dulles_toll_road',
                'i495:182SD', 'dtr:1819:entry:WB'
            )
        ) AS route_fixture(
            origin_id, destination_id, connection_id,
            from_point_id, to_point_id
        )
    LOOP
        SELECT * INTO result
        FROM oracle.validate_toll_route(
            fixture.origin_id, fixture.destination_id
        );
        handoff_index := array_position(
            result.connection_ids, fixture.connection_id
        );
        tested_handoffs := array_append(
            tested_handoffs, fixture.connection_id
        );

        IF result.status <> 'valid'
           OR result.reason IS NOT NULL
           OR result.point_ids[1] <> fixture.origin_id
           OR result.point_ids[cardinality(result.point_ids)]
              <> fixture.destination_id
           OR result.i95_evidence IS NOT NULL
           OR result.general_purpose_gaps <> '[]'::jsonb
           OR cardinality(array_positions(
               result.connection_ids, fixture.connection_id
           )) <> 1
           OR handoff_index IS NULL
           OR result.connection_types[handoff_index] <> 'toll_handoff'
           OR result.point_ids[handoff_index] <> fixture.from_point_id
           OR result.point_ids[handoff_index + 1] <> fixture.to_point_id THEN
            RAISE EXCEPTION '% handoff failed: %',
                fixture.connection_id, row_to_json(result);
        END IF;
    END LOOP;

    SELECT array_agg(connection_id ORDER BY connection_id)
    INTO configured_handoffs
    FROM oracle.toll_connection
    WHERE connection_type = 'toll_handoff';

    SELECT array_agg(connection_id ORDER BY connection_id)
    INTO tested_handoffs
    FROM unnest(tested_handoffs) AS connection_id;

    IF tested_handoffs IS DISTINCT FROM configured_handoffs THEN
        RAISE EXCEPTION 'handoff fixtures do not match configured handoffs: % vs %',
            tested_handoffs, configured_handoffs;
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

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i495:185NO', 'greenway:3:exit:WB');
    IF result.status <> 'valid'
       OR result.reason IS NOT NULL
       OR result.point_ids IS DISTINCT FROM ARRAY[
           'i495:185NO',
           'i495:182ND',
           'dtr:1819:entry:WB',
           'dtr:28:exit:WB',
           'greenway:28:entry:WB',
           'greenway:3:exit:WB'
       ]::text[]
       OR result.connection_ids IS DISTINCT FROM ARRAY[
           'source:i95_shared:Northbound:185NO:182ND',
           'i495_to_dulles_toll_road',
           'source:dtr:WB:1819:28',
           'dtr_to_greenway',
           'source:greenway:WB:28:3'
       ]::text[]
       OR result.connection_types IS DISTINCT FROM ARRAY[
           'within_facility', 'toll_handoff', 'within_facility',
           'toll_handoff', 'within_facility'
       ]::text[]
       OR result.general_purpose_gaps <> '[]'::jsonb
       OR result.i95_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'I-495-to-Greenway composed route changed: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('greenway:1:entry:EB', 'i66:10:exit:EB');
    IF result.status <> 'valid'
       OR result.reason IS NOT NULL
       OR result.point_ids IS DISTINCT FROM ARRAY[
           'greenway:1:entry:EB',
           'greenway:28:exit:EB',
           'dtr:28:entry:EB',
           'dtr:66:exit:EB',
           'i66:6:entry:EB',
           'i66:10:exit:EB'
       ]::text[]
       OR result.connection_ids IS DISTINCT FROM ARRAY[
           'source:greenway:EB:1:28',
           'greenway_to_dtr',
           'source:dtr:EB:28:66',
           'dulles_toll_road_to_i66',
           'source:i66:EB:6:10'
       ]::text[]
       OR result.connection_types IS DISTINCT FROM ARRAY[
           'within_facility', 'toll_handoff', 'within_facility',
           'toll_handoff', 'within_facility'
       ]::text[]
       OR result.general_purpose_gaps <> '[]'::jsonb
       OR result.i95_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'Greenway-to-I-66 composed route changed: %',
            row_to_json(result);
    END IF;
END $$;

CREATE TEMP TABLE exhaustive_expected_routes ON COMMIT DROP AS
WITH RECURSIVE walk(origin_point_id, point_id, visited_point_ids, depth) AS (
    SELECT
        point.point_id,
        point.point_id,
        ARRAY[point.point_id]::text[],
        0
    FROM oracle.toll_route_point AS point
    WHERE point.point_type IN ('entry', 'airport')

    UNION ALL

    SELECT
        walk.origin_point_id,
        connection.to_point_id,
        walk.visited_point_ids || connection.to_point_id,
        walk.depth + 1
    FROM walk
    JOIN oracle.toll_route_point AS current_point
      ON current_point.point_id = walk.point_id
    JOIN oracle.toll_connection AS connection
      ON connection.from_point_id = walk.point_id
    WHERE walk.depth < 12
      AND connection.to_point_id <> ALL(walk.visited_point_ids)
      AND (
          current_point.point_type <> 'airport'
          OR current_point.point_id = walk.origin_point_id
      )
)
SELECT DISTINCT
    walk.origin_point_id,
    walk.point_id AS destination_point_id
FROM walk
JOIN oracle.toll_route_point AS destination
  ON destination.point_id = walk.point_id
WHERE walk.depth > 0
  AND destination.point_type IN ('exit', 'airport');

CREATE TEMP TABLE exhaustive_actual_routes ON COMMIT DROP AS
SELECT
    origin.point_id AS origin_point_id,
    destination.point_id AS destination_point_id,
    route.*
FROM oracle.toll_route_point AS origin
CROSS JOIN oracle.toll_route_point AS destination
CROSS JOIN LATERAL oracle.validate_toll_route(
    origin.point_id, destination.point_id
) AS route
WHERE origin.point_type IN ('entry', 'airport')
  AND destination.point_type IN ('exit', 'airport');

DO $$
DECLARE
    expected_count integer;
    actual_count integer;
    difference_count integer;
    invalid_path_count integer;
BEGIN
    SELECT count(*) INTO expected_count
    FROM exhaustive_expected_routes;

    SELECT count(*) INTO actual_count
    FROM exhaustive_actual_routes
    WHERE status IN ('valid', 'currently_unavailable', 'unknown_availability');

    SELECT count(*) INTO difference_count
    FROM (
        (
            SELECT origin_point_id, destination_point_id
            FROM exhaustive_expected_routes
            EXCEPT
            SELECT origin_point_id, destination_point_id
            FROM exhaustive_actual_routes
            WHERE status IN (
                'valid', 'currently_unavailable', 'unknown_availability'
            )
        )
        UNION ALL
        (
            SELECT origin_point_id, destination_point_id
            FROM exhaustive_actual_routes
            WHERE status IN (
                'valid', 'currently_unavailable', 'unknown_availability'
            )
            EXCEPT
            SELECT origin_point_id, destination_point_id
            FROM exhaustive_expected_routes
        )
    ) AS differences;

    SELECT count(*) INTO invalid_path_count
    FROM exhaustive_actual_routes AS actual
    WHERE actual.status IN (
              'valid', 'currently_unavailable', 'unknown_availability'
          )
      AND (
          cardinality(actual.connection_ids) = 0
          OR cardinality(actual.point_ids)
             <> cardinality(actual.connection_ids) + 1
          OR cardinality(actual.connection_types)
             <> cardinality(actual.connection_ids)
          OR actual.point_ids[1] <> actual.origin_point_id
          OR actual.point_ids[cardinality(actual.point_ids)]
             <> actual.destination_point_id
          OR cardinality(actual.point_ids) <> (
              SELECT count(DISTINCT point_id)
              FROM unnest(actual.point_ids) AS point_id
          )
          OR cardinality(actual.connection_ids) <> (
              SELECT count(DISTINCT connection_id)
              FROM unnest(actual.connection_ids) AS connection_id
          )
          OR EXISTS (
              SELECT 1
              FROM generate_subscripts(actual.connection_ids, 1) AS step(index)
              LEFT JOIN oracle.toll_connection AS connection
                ON connection.connection_id = actual.connection_ids[step.index]
              WHERE connection.connection_id IS NULL
                 OR connection.from_point_id <> actual.point_ids[step.index]
                 OR connection.to_point_id <> actual.point_ids[step.index + 1]
                 OR connection.connection_type
                    <> actual.connection_types[step.index]
          )
      );

    IF expected_count <> 2745
       OR actual_count <> expected_count
       OR difference_count <> 0
       OR invalid_path_count <> 0 THEN
        RAISE EXCEPTION
            'exhaustive reachability changed: expected %, actual %, differences %, invalid paths %',
            expected_count, actual_count, difference_count, invalid_path_count;
    END IF;
END $$;

DROP TABLE exhaustive_actual_routes;
DROP TABLE exhaustive_expected_routes;

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

UPDATE oracle.toll_connection
SET required_i95_direction = 'NB'
WHERE connection_id = 'test-depth-edge-0';

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
    IF result.status <> 'unknown_availability'
       OR result.reason->>'code' <> 'i95_invalid_source'
       OR cardinality(result.connection_ids) <> 12 THEN
        RAISE EXCEPTION '12-edge uncertain route did not succeed: %',
            row_to_json(result);
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

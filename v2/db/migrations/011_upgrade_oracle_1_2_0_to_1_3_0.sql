-- Correct DTR pricing metadata and allow untolled IAD terminal connectors.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.2.0', '1.3.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.2.0 or 1.3.0, got %',
            current_version;
    END IF;
END
$migration$;

SELECT version = '1.2.0' AS oracle_upgrade_needed
FROM oracle.schema_version
WHERE singleton
\gset

\if :oracle_upgrade_needed

DO $dtr$
DECLARE
    changed_rows integer;
BEGIN
    WITH dtr_connections AS (
        SELECT
            connection.connection_id,
            array_position(
                ARRAY[
                    '28', '10', '11', '12', '13', '14',
                    '15', '16', '17', '1819', '66'
                ]::text[],
                split_part(connection.source_route_key, ':', 2)
            ) AS entry_position,
            array_position(
                ARRAY[
                    '28', '10', '11', '12', '13', '14',
                    '15', '16', '17', '1819', '66'
                ]::text[],
                split_part(connection.source_route_key, ':', 3)
            ) AS exit_position
        FROM oracle.toll_connection AS connection
        JOIN oracle.toll_route_point AS origin
          ON origin.point_id = connection.from_point_id
        WHERE connection.connection_type = 'within_facility'
          AND origin.network_id = 'dtr'
    ), ramp_charges AS (
        SELECT
            dtr.connection_id,
            charge.value AS charge,
            CASE
                WHEN charge.value->>'label' LIKE 'Entrance ramp%'
                THEN 1
                ELSE 3
            END AS component_order,
            charge.ordinality
        FROM dtr_connections AS dtr
        JOIN oracle.toll_connection AS connection
          ON connection.connection_id = dtr.connection_id
        CROSS JOIN LATERAL jsonb_array_elements(
            connection.source_metadata #> '{source_pair,charges}'
        ) WITH ORDINALITY AS charge(value, ordinality)
        WHERE charge.value->>'label' <> 'Mainline plaza'
          AND charge.value->>'label'
              <> 'Entrance ramp at Exit 16 - SR 7 (Leesburg Pike)'
    ), desired_components AS (
        SELECT
            ramp.connection_id,
            ramp.charge,
            ramp.component_order,
            ramp.ordinality
        FROM ramp_charges AS ramp

        UNION ALL

        SELECT
            dtr.connection_id,
            jsonb_build_object(
                'label', 'Mainline plaza',
                'price_off_peak_usd', '4.00',
                'price_peak_usd', '4.00'
            ),
            2,
            0
        FROM dtr_connections AS dtr
        WHERE least(dtr.entry_position, dtr.exit_position) <= 8
          AND 8 < greatest(dtr.entry_position, dtr.exit_position)
    ), desired_charges AS (
        SELECT
            dtr.connection_id,
            coalesce((
                SELECT jsonb_agg(
                    component.charge
                    ORDER BY component.component_order, component.ordinality
                )
                FROM desired_components AS component
                WHERE component.connection_id = dtr.connection_id
            ), '[]'::jsonb) AS charges
        FROM dtr_connections AS dtr
    )
    UPDATE oracle.toll_connection AS connection
    SET source_metadata = jsonb_set(
        connection.source_metadata,
        '{source_pair,charges}',
        desired.charges
    )
    FROM desired_charges AS desired
    WHERE connection.connection_id = desired.connection_id
      AND connection.source_metadata #> '{source_pair,charges}'
          IS DISTINCT FROM desired.charges;

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 20 THEN
        RAISE EXCEPTION 'expected 20 corrected DTR pairs, got %', changed_rows;
    END IF;
END
$dtr$;

CREATE OR REPLACE FUNCTION oracle.resolve_toll_route(
    origin_point_id text,
    destination_point_id text
) RETURNS TABLE (
    status text,
    reason jsonb,
    point_ids text[],
    connection_ids text[],
    connection_types text[],
    general_purpose_gaps jsonb,
    i95_evidence jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    origin_role text;
    origin_network text;
    origin_direction text;
    origin_position double precision;
    destination_role text;
    destination_network text;
    destination_direction text;
    destination_position double precision;
    requested_direction text;
    origin_incompatible boolean := false;
    destination_incompatible boolean := false;
    alternatives jsonb;
BEGIN
    point_ids := ARRAY[]::text[];
    connection_ids := ARRAY[]::text[];
    connection_types := ARRAY[]::text[];
    general_purpose_gaps := '[]'::jsonb;
    i95_evidence := NULL;

    SELECT
        route_point.point_type,
        route_point.network_id,
        route_point.direction,
        CASE
            WHEN route_point.network_id IN ('i95', 'i495') THEN
                (route_point.source_metadata
                    -> 'source_node' ->> 'latitude')::double precision
            ELSE (route_point.source_metadata
                    -> 'alternative_ranking' ->> 'corridor_position')::double precision
        END
    INTO origin_role, origin_network, origin_direction, origin_position
    FROM oracle.toll_route_point AS route_point
    WHERE route_point.point_id = origin_point_id;

    IF origin_point_id IS NULL THEN
        status := 'invalid_origin';
        reason := jsonb_build_object(
            'code', 'origin_required',
            'details', jsonb_build_object()
        );
        RETURN NEXT;
        RETURN;
    ELSIF origin_role IS NULL THEN
        status := 'invalid_origin';
        reason := jsonb_build_object(
            'code', 'origin_not_found',
            'details', jsonb_build_object('point_id', origin_point_id)
        );
        RETURN NEXT;
        RETURN;
    ELSIF origin_role NOT IN ('entry', 'airport') THEN
        alternatives := oracle.ramp_alternatives(
            origin_point_id, destination_point_id, true
        );
        status := 'invalid_origin';
        reason := jsonb_build_object(
            'code', 'origin_not_entry',
            'details', jsonb_build_object(
                'point_id', origin_point_id,
                'point_type', origin_role,
                'allowed_point_types', jsonb_build_array('entry', 'airport'),
                'alternatives', alternatives
            )
        );
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT
        route_point.point_type,
        route_point.network_id,
        route_point.direction,
        CASE
            WHEN route_point.network_id IN ('i95', 'i495') THEN
                (route_point.source_metadata
                    -> 'source_node' ->> 'latitude')::double precision
            ELSE (route_point.source_metadata
                    -> 'alternative_ranking' ->> 'corridor_position')::double precision
        END
    INTO destination_role, destination_network, destination_direction,
         destination_position
    FROM oracle.toll_route_point AS route_point
    WHERE route_point.point_id = destination_point_id;

    IF destination_point_id IS NULL THEN
        status := 'invalid_destination';
        reason := jsonb_build_object(
            'code', 'destination_required',
            'details', jsonb_build_object()
        );
        RETURN NEXT;
        RETURN;
    ELSIF destination_role IS NULL THEN
        status := 'invalid_destination';
        reason := jsonb_build_object(
            'code', 'destination_not_found',
            'details', jsonb_build_object('point_id', destination_point_id)
        );
        RETURN NEXT;
        RETURN;
    ELSIF destination_role NOT IN ('exit', 'airport')
      AND NOT (
          origin_point_id = 'airport_iad'
          AND EXISTS (
              SELECT 1
              FROM oracle.toll_connection AS airport_connection
              WHERE airport_connection.from_point_id = origin_point_id
                AND airport_connection.to_point_id = destination_point_id
                AND airport_connection.connection_type = 'airport_access'
          )
      ) THEN
        alternatives := oracle.ramp_alternatives(
            destination_point_id, origin_point_id, false
        );
        status := 'invalid_destination';
        reason := jsonb_build_object(
            'code', 'destination_not_exit',
            'details', jsonb_build_object(
                'point_id', destination_point_id,
                'point_type', destination_role,
                'allowed_point_types', jsonb_build_array('exit', 'airport'),
                'alternatives', alternatives
            )
        );
        RETURN NEXT;
        RETURN;
    END IF;

    WITH RECURSIVE raw_i95 AS (
        SELECT direction_view.*
        FROM pricing.current_i95_direction AS direction_view
    ),
    classified_i95_state AS (
        SELECT
            raw_i95.*,
            CASE
                WHEN raw_i95.northbound_corridor_name IS NULL
                  OR raw_i95.southbound_corridor_name IS NULL
                  OR raw_i95.northbound_link_status IS NULL
                  OR raw_i95.southbound_link_status IS NULL
                  OR raw_i95.northbound_interval_end_at IS NULL
                  OR raw_i95.southbound_interval_end_at IS NULL
                  OR raw_i95.northbound_calculated_at IS NULL
                  OR raw_i95.southbound_calculated_at IS NULL
                    THEN 'missing_source'
                WHEN raw_i95.northbound_corridor_name <> 'I-95-NB'
                  OR raw_i95.southbound_corridor_name <> 'I-95-SB'
                    THEN 'invalid_source'
                WHEN raw_i95.northbound_interval_end_at
                  <> raw_i95.southbound_interval_end_at
                    THEN 'interval_mismatch'
                WHEN raw_i95.northbound_calculated_at > statement_timestamp()
                  OR raw_i95.southbound_calculated_at > statement_timestamp()
                    THEN 'future_evidence'
                WHEN raw_i95.northbound_calculated_at
                       < statement_timestamp() - interval '20 minutes'
                  OR raw_i95.southbound_calculated_at
                       < statement_timestamp() - interval '20 minutes'
                    THEN 'stale_evidence'
                WHEN raw_i95.northbound_link_status = 'NORTHBOUND_OPEN'
                  AND raw_i95.southbound_link_status = 'CLOSED'
                    THEN 'northbound'
                WHEN raw_i95.northbound_link_status = 'CLOSED'
                  AND raw_i95.southbound_link_status = 'SOUTHBOUND_OPEN'
                    THEN 'southbound'
                WHEN raw_i95.northbound_link_status = 'CLOSED'
                  AND raw_i95.southbound_link_status = 'CLOSED'
                    THEN 'closed'
                ELSE 'indeterminate_state'
            END AS evidence_state
        FROM raw_i95
    ),
    classified_i95 AS (
        SELECT
            CASE
                WHEN state.evidence_state IN ('northbound', 'southbound', 'closed')
                    THEN state.evidence_state
                ELSE 'unknown'
            END AS availability,
            CASE
                WHEN state.evidence_state IN ('northbound', 'southbound', 'closed')
                    THEN NULL::text
                ELSE 'i95_' || state.evidence_state
            END AS unavailable_reason,
            CASE
                WHEN state.direction_state = 'missing_source' THEN
                    jsonb_build_object('reason', 'missing_source')
                ELSE jsonb_build_object(
                    'northbound_corridor_name', state.northbound_corridor_name,
                    'northbound_link_status', state.northbound_link_status,
                    'northbound_interval_end_at', state.northbound_interval_end_at,
                    'northbound_calculated_at', state.northbound_calculated_at,
                    'southbound_corridor_name', state.southbound_corridor_name,
                    'southbound_link_status', state.southbound_link_status,
                    'southbound_interval_end_at', state.southbound_interval_end_at,
                    'southbound_calculated_at', state.southbound_calculated_at
                )
            END AS raw_evidence
        FROM classified_i95_state AS state
    ),
    evidence AS (
        SELECT
            classified_i95.availability,
            classified_i95.unavailable_reason,
            classified_i95.raw_evidence
                || jsonb_build_object('availability', classified_i95.availability)
                AS evidence_json
        FROM classified_i95
        UNION ALL
        SELECT
            'unknown'::text,
            'i95_missing_source'::text,
            jsonb_build_object('availability', 'unknown', 'reason', 'missing_source')
        WHERE NOT EXISTS (SELECT 1 FROM classified_i95)
    ),
    walk AS (
        SELECT
            origin.point_id AS current_point_id,
            ARRAY[origin.point_id]::text[] AS walked_point_ids,
            ARRAY[]::text[] AS walked_connection_ids,
            ARRAY[]::text[] AS walked_connection_types,
            '[]'::jsonb AS walked_general_purpose_gaps,
            ARRAY[]::text[] AS required_i95_directions,
            0 AS depth
        FROM oracle.toll_route_point AS origin
        WHERE origin.point_id = origin_point_id

        UNION ALL

        SELECT
            destination.point_id,
            walk.walked_point_ids || destination.point_id,
            walk.walked_connection_ids || connection.connection_id,
            walk.walked_connection_types || connection.connection_type,
            CASE WHEN connection.connection_type = 'general_purpose_gap' THEN
                walk.walked_general_purpose_gaps || jsonb_build_array(
                    jsonb_build_object(
                        'connection_id', connection.connection_id,
                        'boundary_point_id',
                            connection.source_metadata
                                -> 'general_purpose_fallback'
                                ->> 'boundary_point_id',
                        'role', CASE
                            WHEN current_point.network_id = 'i95'
                              AND destination.network_id = 'i495' THEN 'prefix'
                            WHEN current_point.network_id = 'i495'
                              AND destination.network_id = 'i95' THEN 'suffix'
                            ELSE 'unknown'
                        END,
                        'i95_direction',
                            connection.source_metadata
                                -> 'general_purpose_fallback'
                                ->> 'i95_direction'
                    )
                )
            ELSE walk.walked_general_purpose_gaps
            END,
            CASE
                WHEN connection.connection_type = 'general_purpose_gap' THEN
                    array_append(
                        walk.required_i95_directions,
                        connection.source_metadata
                            -> 'general_purpose_fallback'
                            ->> 'i95_direction'
                    )
                WHEN connection.required_i95_direction IS NULL THEN
                    walk.required_i95_directions
                ELSE walk.required_i95_directions
                     || connection.required_i95_direction
            END,
            walk.depth + 1
        FROM walk
        JOIN oracle.toll_route_point AS current_point
          ON current_point.point_id = walk.current_point_id
        JOIN oracle.toll_connection AS connection
          ON connection.from_point_id = walk.current_point_id
        JOIN oracle.toll_route_point AS destination
          ON destination.point_id = connection.to_point_id
        WHERE walk.depth < 12
          AND walk.current_point_id <> destination_point_id
          AND NOT destination.point_id = ANY(walk.walked_point_ids)
          AND (
              current_point.point_type <> 'airport'
              OR current_point.point_id = origin_point_id
          )
          AND (
              destination.point_type <> 'airport'
              OR destination.point_id = destination_point_id
          )
    ),
    candidates AS (
        SELECT
            CASE
                WHEN cardinality(walk.required_i95_directions) = 0 THEN 'valid'
                WHEN evidence.availability = 'unknown' THEN 'unknown_availability'
                WHEN evidence.availability = 'northbound'
                  AND walk.required_i95_directions <@ ARRAY['NB']::text[] THEN 'valid'
                WHEN evidence.availability = 'southbound'
                  AND walk.required_i95_directions <@ ARRAY['SB']::text[] THEN 'valid'
                ELSE 'currently_unavailable'
            END AS candidate_status,
            CASE
                WHEN cardinality(walk.required_i95_directions) = 0 THEN NULL
                WHEN evidence.availability = 'unknown' THEN jsonb_build_object(
                    'code', evidence.unavailable_reason,
                    'details', jsonb_build_object(
                        'required_i95_directions', walk.required_i95_directions,
                        'availability', evidence.availability
                    )
                )
                WHEN evidence.availability = 'northbound'
                  AND walk.required_i95_directions <@ ARRAY['NB']::text[] THEN NULL
                WHEN evidence.availability = 'southbound'
                  AND walk.required_i95_directions <@ ARRAY['SB']::text[] THEN NULL
                WHEN evidence.availability = 'closed' THEN jsonb_build_object(
                    'code', 'i95_fully_closed',
                    'details', jsonb_build_object(
                        'required_i95_directions', walk.required_i95_directions,
                        'availability', evidence.availability
                    )
                )
                ELSE jsonb_build_object(
                    'code', 'i95_opposite_direction_open',
                    'details', jsonb_build_object(
                        'required_i95_directions', walk.required_i95_directions,
                        'availability', evidence.availability
                    )
                )
            END AS candidate_reason,
            walk.walked_point_ids,
            walk.walked_connection_ids,
            walk.walked_connection_types,
            CASE
                WHEN jsonb_array_length(walk.walked_general_purpose_gaps) = 0
                    THEN '[]'::jsonb
                ELSE (
                    SELECT jsonb_agg(
                        gap.value || jsonb_build_object(
                            'fallback_required',
                            CASE
                                WHEN evidence.availability = 'unknown'
                                    THEN NULL::boolean
                                WHEN evidence.availability = 'northbound'
                                  AND gap.value->>'i95_direction' = 'NB'
                                    THEN false
                                WHEN evidence.availability = 'southbound'
                                  AND gap.value->>'i95_direction' = 'SB'
                                    THEN false
                                ELSE true
                            END
                        )
                        ORDER BY gap.ordinality
                    )
                    FROM jsonb_array_elements(
                        walk.walked_general_purpose_gaps
                    ) WITH ORDINALITY AS gap(value, ordinality)
                )
            END AS candidate_general_purpose_gaps,
            CASE
                WHEN cardinality(walk.required_i95_directions) = 0
                  AND jsonb_array_length(walk.walked_general_purpose_gaps) = 0
                    THEN NULL
                ELSE evidence.evidence_json
            END AS candidate_evidence,
            walk.depth
        FROM walk
        CROSS JOIN evidence
        WHERE walk.current_point_id = destination_point_id
          AND walk.depth > 0
    ),
    frontier_state AS (
        SELECT EXISTS (
            SELECT 1
            FROM walk AS frontier_walk
            JOIN oracle.toll_route_point AS current_point
              ON current_point.point_id = frontier_walk.current_point_id
            JOIN oracle.toll_connection AS connection
              ON connection.from_point_id = frontier_walk.current_point_id
            JOIN oracle.toll_route_point AS next_point
              ON next_point.point_id = connection.to_point_id
            WHERE frontier_walk.depth = 12
              AND frontier_walk.current_point_id <> destination_point_id
              AND NOT next_point.point_id = ANY(frontier_walk.walked_point_ids)
              AND current_point.point_type <> 'airport'
              AND (
                  next_point.point_type <> 'airport'
                  OR next_point.point_id = destination_point_id
              )
        ) AS traversal_was_truncated
    ),
    choices AS (
        SELECT
            candidates.candidate_status,
            candidates.candidate_reason,
            candidates.walked_point_ids,
            candidates.walked_connection_ids,
            candidates.walked_connection_types,
            candidates.candidate_general_purpose_gaps,
            candidates.candidate_evidence,
            candidates.depth,
            CASE candidates.candidate_status
                WHEN 'valid' THEN 1
                WHEN 'unknown_availability' THEN 3
                ELSE 4
            END AS priority
        FROM candidates

        UNION ALL

        SELECT
            CASE
                WHEN frontier_state.traversal_was_truncated
                    THEN 'traversal_limit_exceeded'
                ELSE 'no_supported_route'
            END,
            CASE
                WHEN frontier_state.traversal_was_truncated THEN jsonb_build_object(
                    'code', 'traversal_limit_exceeded',
                    'details', jsonb_build_object(
                        'origin_point_id', origin_point_id,
                        'destination_point_id', destination_point_id,
                        'maximum_connections', 12
                    )
                )
                ELSE jsonb_build_object(
                    'code', 'no_supported_route',
                    'details', jsonb_build_object(
                        'origin_point_id', origin_point_id,
                        'destination_point_id', destination_point_id
                    )
                )
            END,
            ARRAY[]::text[],
            ARRAY[]::text[],
            ARRAY[]::text[],
            '[]'::jsonb,
            NULL::jsonb,
            0,
            CASE WHEN frontier_state.traversal_was_truncated THEN 2 ELSE 5 END
        FROM frontier_state
    )
    SELECT
        choices.candidate_status,
        choices.candidate_reason,
        choices.walked_point_ids,
        choices.walked_connection_ids,
        choices.walked_connection_types,
        choices.candidate_general_purpose_gaps,
        choices.candidate_evidence
    INTO status, reason, point_ids, connection_ids, connection_types,
         general_purpose_gaps, i95_evidence
    FROM choices
    ORDER BY
        choices.priority,
        choices.depth,
        choices.walked_connection_ids
    LIMIT 1;

    IF status = 'no_supported_route' THEN
        IF origin_network = destination_network
           AND origin_position IS NOT NULL
           AND destination_position IS NOT NULL
           AND origin_position <> destination_position THEN
            requested_direction := CASE
                WHEN destination_position > origin_position
                  AND origin_network IN ('i95', 'i495') THEN 'NB'
                WHEN destination_position < origin_position
                  AND origin_network IN ('i95', 'i495') THEN 'SB'
                WHEN destination_position > origin_position
                  AND origin_network IN ('i66', 'greenway') THEN 'EB'
                WHEN destination_position < origin_position
                  AND origin_network IN ('i66', 'greenway') THEN 'WB'
            END;
            origin_incompatible := origin_direction IS DISTINCT FROM requested_direction;
            destination_incompatible :=
                destination_direction IS DISTINCT FROM requested_direction;
        END IF;

        IF requested_direction IS NULL
           OR origin_incompatible
           OR (NOT origin_incompatible AND NOT destination_incompatible) THEN
            alternatives := oracle.ramp_alternatives(
                origin_point_id, destination_point_id, true
            );
            IF jsonb_array_length(alternatives) > 0 THEN
                status := 'invalid_origin';
                reason := jsonb_build_object(
                    'code', 'origin_ramp_incompatible',
                    'details', jsonb_build_object(
                        'point_id', origin_point_id,
                        'point_type', origin_role,
                        'alternatives', alternatives
                    )
                );
            END IF;
        END IF;

        IF status = 'no_supported_route'
           AND (
               requested_direction IS NULL
               OR destination_incompatible
               OR (NOT origin_incompatible AND NOT destination_incompatible)
           ) THEN
            alternatives := oracle.ramp_alternatives(
                destination_point_id, origin_point_id, false
            );
            IF jsonb_array_length(alternatives) > 0 THEN
                status := 'invalid_destination';
                reason := jsonb_build_object(
                    'code', 'destination_ramp_incompatible',
                    'details', jsonb_build_object(
                        'point_id', destination_point_id,
                        'point_type', destination_role,
                        'alternatives', alternatives
                    )
                );
            END IF;
        END IF;

        IF status IN ('invalid_origin', 'invalid_destination') THEN
            point_ids := ARRAY[]::text[];
            connection_ids := ARRAY[]::text[];
            connection_types := ARRAY[]::text[];
            general_purpose_gaps := '[]'::jsonb;
            i95_evidence := NULL;
        END IF;
    END IF;

    RETURN NEXT;
END
$function$;

UPDATE oracle.schema_version
SET version = '1.3.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.2.0';

\endif

DO $migration$
DECLARE
    expected record;
    result record;
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.3.0' THEN
        RAISE EXCEPTION 'oracle 1.3.0 is not installed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM oracle.toll_connection AS connection
        JOIN oracle.toll_route_point AS origin
          ON origin.point_id = connection.from_point_id
        LEFT JOIN LATERAL jsonb_array_elements(
            connection.source_metadata #> '{source_pair,charges}'
        ) AS charge(value) ON true
        WHERE origin.network_id = 'dtr'
          AND connection.connection_type = 'within_facility'
        GROUP BY connection.connection_id, connection.source_route_key
        HAVING count(*) FILTER (
            WHERE charge.value->>'label'
                = 'Entrance ramp at Exit 16 - SR 7 (Leesburg Pike)'
        ) <> 0
           OR count(*) FILTER (
               WHERE charge.value->>'label' = 'Mainline plaza'
           ) <> CASE
               WHEN least(
                   array_position(
                       ARRAY[
                           '28', '10', '11', '12', '13', '14',
                           '15', '16', '17', '1819', '66'
                       ]::text[],
                       split_part(connection.source_route_key, ':', 2)
                   ),
                   array_position(
                       ARRAY[
                           '28', '10', '11', '12', '13', '14',
                           '15', '16', '17', '1819', '66'
                       ]::text[],
                       split_part(connection.source_route_key, ':', 3)
                   )
               ) <= 8
                AND 8 < greatest(
                   array_position(
                       ARRAY[
                           '28', '10', '11', '12', '13', '14',
                           '15', '16', '17', '1819', '66'
                       ]::text[],
                       split_part(connection.source_route_key, ':', 2)
                   ),
                   array_position(
                       ARRAY[
                           '28', '10', '11', '12', '13', '14',
                           '15', '16', '17', '1819', '66'
                       ]::text[],
                       split_part(connection.source_route_key, ':', 3)
                   )
               ) THEN 1
               ELSE 0
           END
    ) THEN
        RAISE EXCEPTION 'oracle 1.3.0 DTR correction is not installed';
    END IF;

    FOR expected IN
        SELECT * FROM (VALUES
            ('i66:6:entry:EB', 'iad_to_i66'),
            ('dtr:66:entry:WB', 'iad_to_dtr_via_i66'),
            ('i495:182NO', 'iad_to_i495_north'),
            ('i495:182SO', 'iad_to_i495_south')
        ) AS connector(destination_id, connection_id)
    LOOP
        SELECT * INTO STRICT result
        FROM oracle.resolve_toll_route('airport_iad', expected.destination_id);

        IF result.status <> 'valid'
           OR result.point_ids
              <> ARRAY['airport_iad', expected.destination_id]
           OR result.connection_ids <> ARRAY[expected.connection_id]
           OR result.connection_types <> ARRAY['airport_access']
           OR result.general_purpose_gaps <> '[]'::jsonb
           OR result.i95_evidence IS NOT NULL THEN
            RAISE EXCEPTION 'IAD connector % is not an untolled terminal: %',
                expected.destination_id, row_to_json(result);
        END IF;
    END LOOP;
END
$migration$;

COMMIT;

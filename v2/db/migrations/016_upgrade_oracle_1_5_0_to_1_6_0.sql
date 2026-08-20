-- Add schedule-independent routes and bounded ballpark sample functions.

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

    IF current_version NOT IN ('1.5.0', '1.6.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.5.0 or 1.6.0, got %',
            current_version;
    END IF;
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.2.0'
       OR to_regclass('pricing.i66_ballpark_samples') IS NULL
       OR to_regclass('pricing.i95_i495_ballpark_samples') IS NULL
       OR to_regrole('oracle_owner') IS NULL
       OR to_regrole('tollchat_agent') IS NULL THEN
        RAISE EXCEPTION 'oracle 1.6.0 requires pricing 1.2.0';
    END IF;
END
$migration$;

SELECT version = '1.5.0' AS oracle_upgrade_needed
FROM oracle.schema_version
WHERE singleton
\gset

\if :oracle_upgrade_needed

CREATE FUNCTION oracle.resolve_toll_route_internal(
    origin_point_id text,
    destination_point_id text,
    evaluate_i95_availability boolean
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
        WHERE evaluate_i95_availability
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
                WHEN NOT evaluate_i95_availability
                  OR cardinality(walk.required_i95_directions) = 0 THEN 'valid'
                WHEN evidence.availability = 'unknown' THEN 'unknown_availability'
                WHEN evidence.availability = 'northbound'
                  AND walk.required_i95_directions <@ ARRAY['NB']::text[] THEN 'valid'
                WHEN evidence.availability = 'southbound'
                  AND walk.required_i95_directions <@ ARRAY['SB']::text[] THEN 'valid'
                ELSE 'currently_unavailable'
            END AS candidate_status,
            CASE
                WHEN NOT evaluate_i95_availability
                  OR cardinality(walk.required_i95_directions) = 0 THEN NULL
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
                                WHEN NOT evaluate_i95_availability
                                    THEN NULL::boolean
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
                WHEN NOT evaluate_i95_availability THEN NULL
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
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$
SELECT *
FROM oracle.resolve_toll_route_internal($1, $2, true)
$function$;


CREATE FUNCTION oracle.route_pricing_legs(
    resolved_point_ids text[],
    resolved_connection_ids text[]
) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$
WITH components AS (
    SELECT
        step.connection_index,
        component.component_order,
        component.from_point_id,
        component.to_point_id,
        component.boundary_point_id,
        component.component_count,
        component.facility,
        component.source_route_key,
        component.od_pair_id,
        component.start_zone_id,
        component.end_zone_id,
        component.charge
    FROM generate_subscripts(resolved_connection_ids, 1)
         AS step(connection_index)
    JOIN oracle.route_pricing_component AS component
      ON component.connection_id = resolved_connection_ids[step.connection_index]
), numbered AS (
    SELECT
        components.*,
        row_number() OVER (
            ORDER BY components.connection_index, components.component_order
        ) AS route_step_number
    FROM components
)
SELECT coalesce(
    jsonb_agg(
        jsonb_build_object(
            'route_step_id', 'step-' || numbered.route_step_number,
            'facility', numbered.facility,
            'point_ids', CASE
                WHEN numbered.boundary_point_id IS NOT NULL
                 AND numbered.component_count = 2
                 AND numbered.component_order = 1 THEN jsonb_build_array(
                    numbered.from_point_id, numbered.boundary_point_id
                )
                WHEN numbered.boundary_point_id IS NOT NULL
                 AND numbered.component_count = 2
                 AND numbered.component_order = 2 THEN jsonb_build_array(
                    numbered.boundary_point_id, numbered.to_point_id
                )
                ELSE jsonb_build_array(
                    resolved_point_ids[numbered.connection_index],
                    resolved_point_ids[numbered.connection_index + 1]
                )
            END,
            'connection_ids', jsonb_build_array(
                resolved_connection_ids[numbered.connection_index]
            ),
            'pricing_key', jsonb_strip_nulls(jsonb_build_object(
                'source_route_key', numbered.source_route_key,
                'od_pair_id', numbered.od_pair_id,
                'start_zone_id', numbered.start_zone_id,
                'end_zone_id', numbered.end_zone_id,
                'charge_index', CASE
                    WHEN numbered.charge IS NOT NULL
                    THEN numbered.component_order
                END
            ))
        )
        ORDER BY numbered.connection_index, numbered.component_order
    ),
    '[]'::jsonb
)
FROM numbered
$function$;

CREATE OR REPLACE FUNCTION oracle.validate_pricing_route(
    origin_point_id text,
    destination_point_id text
) RETURNS TABLE (
    status text,
    reason jsonb,
    point_ids text[],
    connection_ids text[],
    connection_types text[],
    general_purpose_gaps jsonb,
    i95_evidence jsonb,
    facility_legs jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    resolved record;
BEGIN
    point_ids := ARRAY[]::text[];
    connection_ids := ARRAY[]::text[];
    connection_types := ARRAY[]::text[];
    general_purpose_gaps := '[]'::jsonb;
    i95_evidence := NULL;
    facility_legs := '[]'::jsonb;

    SELECT * INTO STRICT resolved
    FROM oracle.resolve_toll_route(origin_point_id, destination_point_id);

    status := resolved.status;
    reason := resolved.reason;
    point_ids := resolved.point_ids;
    connection_ids := resolved.connection_ids;
    connection_types := resolved.connection_types;
    general_purpose_gaps := resolved.general_purpose_gaps;
    i95_evidence := resolved.i95_evidence;

    IF resolved.status <> 'valid' THEN
        RETURN NEXT;
        RETURN;
    END IF;

    facility_legs := oracle.route_pricing_legs(point_ids, connection_ids);

    RETURN NEXT;
END
$function$;

CREATE FUNCTION oracle.validate_ballpark_route(
    origin_point_id text,
    destination_point_id text
) RETURNS TABLE (
    status text,
    reason jsonb,
    point_ids text[],
    connection_ids text[],
    connection_types text[],
    general_purpose_gaps jsonb,
    facility_legs jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    resolved record;
BEGIN
    point_ids := ARRAY[]::text[];
    connection_ids := ARRAY[]::text[];
    connection_types := ARRAY[]::text[];
    general_purpose_gaps := '[]'::jsonb;
    facility_legs := '[]'::jsonb;

    SELECT * INTO STRICT resolved
    FROM oracle.resolve_toll_route_internal(
        origin_point_id, destination_point_id, false
    );

    status := resolved.status;
    reason := resolved.reason;
    point_ids := resolved.point_ids;
    connection_ids := resolved.connection_ids;
    connection_types := resolved.connection_types;
    general_purpose_gaps := resolved.general_purpose_gaps;

    IF resolved.status = 'valid' THEN
        facility_legs := oracle.route_pricing_legs(point_ids, connection_ids);
    END IF;

    RETURN NEXT;
END
$function$;


CREATE FUNCTION oracle.validate_ballpark_sample_request(
    requested_local_time time,
    requested_dates date[],
    requested_evaluated_at timestamptz
) RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    requested_date_count integer;
BEGIN
    requested_date_count := cardinality(requested_dates);
    IF requested_local_time IS NULL
       OR requested_dates IS NULL
       OR requested_evaluated_at IS DISTINCT FROM transaction_timestamp()
       OR requested_date_count < 1
       OR requested_date_count > 84
       OR array_position(requested_dates, NULL) IS NOT NULL
       OR EXISTS (
           SELECT 1
           FROM unnest(requested_dates) AS requested_date(value)
           WHERE requested_date.value
                 NOT BETWEEN
                     (requested_evaluated_at AT TIME ZONE 'America/New_York')::date
                         - 84
                 AND (requested_evaluated_at AT TIME ZONE 'America/New_York')::date
                         - 1
       )
       OR (
           SELECT count(DISTINCT requested_date.value)
           FROM unnest(requested_dates) AS requested_date(value)
       ) <> requested_date_count THEN
        RAISE EXCEPTION 'invalid ballpark sample request';
    END IF;
END
$function$;

CREATE FUNCTION oracle.get_i66_ballpark_samples(
    requested_start_zone_id integer,
    requested_end_zone_id integer,
    requested_local_time time,
    requested_dates date[],
    requested_evaluated_at timestamptz
) RETURNS TABLE (
    sample_date date,
    sample_isodow integer,
    bin_start_at timestamptz,
    bin_end_at timestamptz,
    interval_end_at timestamptz,
    observed_at timestamptz,
    start_zone_id integer,
    end_zone_id integer,
    price_usd numeric,
    uses_modeled boolean,
    pricing_method text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF requested_start_zone_id IS NULL OR requested_end_zone_id IS NULL THEN
        RAISE EXCEPTION 'invalid I-66 ballpark component';
    END IF;
    PERFORM oracle.validate_ballpark_sample_request(
        requested_local_time, requested_dates, requested_evaluated_at
    );

    RETURN QUERY
    WITH local_targets AS (
        SELECT
            requested_date.value AS target_date,
            requested_date.value + requested_local_time AS wall_time
        FROM unnest(requested_dates) AS requested_date(value)
    ), instant_candidates AS (
        SELECT
            target.target_date,
            target.wall_time,
            (target.wall_time AT TIME ZONE 'UTC')
                + make_interval(hours => offset_number) AS candidate_at
        FROM local_targets AS target
        CROSS JOIN generate_series(-14, 14) AS offsets(offset_number)
    ), resolved_targets AS (
        SELECT
            candidate.target_date,
            min(candidate.candidate_at) AS target_at
        FROM instant_candidates AS candidate
        WHERE candidate.candidate_at AT TIME ZONE 'America/New_York'
              = candidate.wall_time
        GROUP BY candidate.target_date
        HAVING count(*) = 1
    ), targets AS (
        SELECT
            resolved.target_date,
            date_bin(
                interval '6 minutes', resolved.target_at,
                timestamptz '2000-01-01 00:00:00+00'
            ) AS target_bin_start_at
        FROM resolved_targets AS resolved
    ), candidates AS (
        SELECT
            sample.*,
            row_number() OVER (
                PARTITION BY sample.sample_date
                ORDER BY sample.interval_end_at DESC, sample.observed_at DESC
            ) AS candidate_rank
        FROM targets AS target
        JOIN pricing.i66_ballpark_samples AS sample
          ON sample.sample_date = target.target_date
         AND sample.interval_end_at >= target.target_bin_start_at
         AND sample.interval_end_at
             < target.target_bin_start_at + interval '6 minutes'
        WHERE sample.start_zone_id = requested_start_zone_id
          AND sample.end_zone_id = requested_end_zone_id
          AND sample.interval_end_at <= requested_evaluated_at
          AND sample.observed_at <= requested_evaluated_at
    )
    SELECT
        candidate.sample_date,
        candidate.sample_isodow,
        candidate.bin_start_at,
        candidate.bin_end_at,
        candidate.interval_end_at,
        candidate.observed_at,
        candidate.start_zone_id,
        candidate.end_zone_id,
        candidate.price_usd,
        candidate.uses_modeled,
        candidate.pricing_method
    FROM candidates AS candidate
    WHERE candidate.candidate_rank = 1
    ORDER BY candidate.sample_date;
END
$function$;

CREATE FUNCTION oracle.get_i95_i495_ballpark_samples(
    requested_od_pair_id integer,
    requested_local_time time,
    requested_dates date[],
    requested_evaluated_at timestamptz
) RETURNS TABLE (
    sample_date date,
    sample_isodow integer,
    bin_start_at timestamptz,
    bin_end_at timestamptz,
    interval_end_at timestamptz,
    observed_at timestamptz,
    od_pair_id integer,
    price_usd numeric,
    uses_modeled boolean,
    pricing_method text,
    proxy_od_pair_id integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF requested_od_pair_id IS NULL THEN
        RAISE EXCEPTION 'invalid I-95/I-495 ballpark component';
    END IF;
    PERFORM oracle.validate_ballpark_sample_request(
        requested_local_time, requested_dates, requested_evaluated_at
    );

    RETURN QUERY
    WITH local_targets AS (
        SELECT
            requested_date.value AS target_date,
            requested_date.value + requested_local_time AS wall_time
        FROM unnest(requested_dates) AS requested_date(value)
    ), instant_candidates AS (
        SELECT
            target.target_date,
            target.wall_time,
            (target.wall_time AT TIME ZONE 'UTC')
                + make_interval(hours => offset_number) AS candidate_at
        FROM local_targets AS target
        CROSS JOIN generate_series(-14, 14) AS offsets(offset_number)
    ), resolved_targets AS (
        SELECT
            candidate.target_date,
            min(candidate.candidate_at) AS target_at
        FROM instant_candidates AS candidate
        WHERE candidate.candidate_at AT TIME ZONE 'America/New_York'
              = candidate.wall_time
        GROUP BY candidate.target_date
        HAVING count(*) = 1
    ), targets AS (
        SELECT
            resolved.target_date,
            date_bin(
                interval '10 minutes', resolved.target_at,
                timestamptz '2000-01-01 00:00:00+00'
            ) AS target_bin_start_at
        FROM resolved_targets AS resolved
    ), candidates AS (
        SELECT
            sample.*,
            row_number() OVER (
                PARTITION BY sample.sample_date
                ORDER BY
                    sample.uses_modeled,
                    sample.interval_end_at DESC,
                    sample.observed_at DESC,
                    sample.source_start_zone_id,
                    sample.source_end_zone_id
            ) AS candidate_rank
        FROM targets AS target
        JOIN pricing.i95_i495_ballpark_samples AS sample
          ON sample.sample_date = target.target_date
         AND sample.interval_end_at >= target.target_bin_start_at
         AND sample.interval_end_at
             < target.target_bin_start_at + interval '10 minutes'
        WHERE sample.od_pair_id = requested_od_pair_id
          AND sample.interval_end_at <= requested_evaluated_at
          AND sample.observed_at <= requested_evaluated_at
    )
    SELECT
        candidate.sample_date,
        candidate.sample_isodow,
        candidate.bin_start_at,
        candidate.bin_end_at,
        candidate.interval_end_at,
        candidate.observed_at,
        candidate.od_pair_id,
        candidate.price_usd,
        candidate.uses_modeled,
        candidate.pricing_method,
        candidate.proxy_od_pair_id
    FROM candidates AS candidate
    WHERE candidate.candidate_rank = 1
    ORDER BY candidate.sample_date;
END
$function$;


GRANT SELECT ON
    pricing.i66_ballpark_samples,
    pricing.i95_i495_ballpark_samples
TO oracle_owner;

REVOKE ALL ON FUNCTION oracle.resolve_toll_route_internal(text, text, boolean)
FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.route_pricing_legs(text[], text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.validate_ballpark_route(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.validate_ballpark_sample_request(
    time, date[], timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, time, date[], timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.get_i95_i495_ballpark_samples(
    integer, time, date[], timestamptz
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION oracle.validate_ballpark_route(text, text)
TO tollchat_agent;
GRANT EXECUTE ON FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, time, date[], timestamptz
) TO tollchat_agent;
GRANT EXECUTE ON FUNCTION oracle.get_i95_i495_ballpark_samples(
    integer, time, date[], timestamptz
) TO tollchat_agent;

ALTER FUNCTION oracle.resolve_toll_route_internal(text, text, boolean)
OWNER TO oracle_owner;
ALTER FUNCTION oracle.route_pricing_legs(text[], text[]) OWNER TO oracle_owner;
ALTER FUNCTION oracle.resolve_toll_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_pricing_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_ballpark_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_ballpark_sample_request(time, date[], timestamptz)
OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, time, date[], timestamptz
) OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i95_i495_ballpark_samples(
    integer, time, date[], timestamptz
) OWNER TO oracle_owner;

UPDATE oracle.schema_version
SET version = '1.6.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.5.0';

\endif

DO $migration$
DECLARE
    executable_count integer;
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.6.0'
       OR NOT has_function_privilege(
           'tollchat_agent', 'oracle.validate_ballpark_route(text,text)', 'EXECUTE'
       )
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.get_i66_ballpark_samples(integer,integer,time,date[],timestamptz)',
           'EXECUTE'
       )
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.get_i95_i495_ballpark_samples(integer,time,date[],timestamptz)',
           'EXECUTE'
       )
       OR has_table_privilege(
           'tollchat_agent', 'pricing.i66_ballpark_samples', 'SELECT'
       )
       OR has_table_privilege(
           'tollchat_agent', 'pricing.i95_i495_ballpark_samples', 'SELECT'
       )
       OR NOT has_table_privilege(
           'oracle_owner', 'pricing.i66_ballpark_samples', 'SELECT'
       )
       OR NOT has_table_privilege(
           'oracle_owner', 'pricing.i95_i495_ballpark_samples', 'SELECT'
       ) THEN
        RAISE EXCEPTION 'oracle 1.6.0 ballpark security contract is not installed';
    END IF;

    SELECT count(*) INTO executable_count
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND has_function_privilege('tollchat_agent', procedure.oid, 'EXECUTE');
    IF executable_count <> 7 THEN
        RAISE EXCEPTION 'tollchat_agent executable function count is %',
            executable_count;
    END IF;
END
$migration$;

COMMIT;

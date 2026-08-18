-- Reuse canonical route resolution and validate Python-supplied route arrays.

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

    IF current_version NOT IN ('1.0.2', '1.1.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.0.2 or 1.1.0, got %',
            current_version;
    END IF;
END
$migration$;

SELECT version = '1.0.2' AS oracle_upgrade_needed
FROM oracle.schema_version
WHERE singleton
\gset

\if :oracle_upgrade_needed

DO $migration$
DECLARE
    dependent_objects text;
BEGIN
    SELECT string_agg(
        pg_catalog.pg_describe_object(
            dependency.classid, dependency.objid, dependency.objsubid
        ),
        ', '
    ) INTO dependent_objects
    FROM pg_catalog.pg_depend AS dependency
    WHERE dependency.refclassid = 'pg_catalog.pg_proc'::regclass
      AND dependency.refobjid =
          'oracle.validate_toll_route(text,text)'::regprocedure
      AND dependency.deptype IN ('n', 'a');

    IF dependent_objects IS NOT NULL THEN
        RAISE EXCEPTION
            'cannot replace validate_toll_route with dependent objects: %',
            dependent_objects;
    END IF;
END
$migration$;

ALTER FUNCTION oracle.validate_toll_route(text, text)
    RENAME TO resolve_toll_route;
ALTER FUNCTION oracle.resolve_toll_route(text, text) SECURITY INVOKER;
REVOKE ALL ON FUNCTION oracle.resolve_toll_route(text, text)
FROM tollchat_agent;

CREATE VIEW oracle.route_pricing_component AS
SELECT
    connection.connection_id,
    component.ordinality::integer AS component_order,
    connection.from_point_id,
    connection.to_point_id,
    connection.source_metadata
        #>> '{general_purpose_fallback,boundary_point_id}' AS boundary_point_id,
    jsonb_array_length(connection.source_metadata #> '{source_pair,ods}')
        AS component_count,
    'i95_i495'::text AS facility,
    connection.source_route_key,
    component.value::integer AS od_pair_id,
    NULL::integer AS start_zone_id,
    NULL::integer AS end_zone_id,
    NULL::jsonb AS charge
FROM oracle.toll_connection AS connection
CROSS JOIN LATERAL jsonb_array_elements_text(
    connection.source_metadata #> '{source_pair,ods}'
) WITH ORDINALITY AS component(value, ordinality)
WHERE connection.connection_type IN ('within_facility', 'general_purpose_gap')

UNION ALL

SELECT
    connection.connection_id,
    1,
    connection.from_point_id,
    connection.to_point_id,
    NULL,
    1,
    'i66',
    connection.source_route_key,
    NULL,
    (connection.source_metadata #>> '{source_pair,start_zone}')::integer,
    (connection.source_metadata #>> '{source_pair,end_zone}')::integer,
    NULL
FROM oracle.toll_connection AS connection
JOIN oracle.toll_route_point AS origin
  ON origin.point_id = connection.from_point_id
WHERE connection.connection_type = 'within_facility'
  AND origin.network_id = 'i66'

UNION ALL

SELECT
    connection.connection_id,
    component.ordinality::integer,
    connection.from_point_id,
    connection.to_point_id,
    NULL,
    jsonb_array_length(connection.source_metadata #> '{source_pair,charges}'),
    CASE component.value->>'facility'
        WHEN 'dulles_toll_road' THEN 'dtr'
        ELSE origin.network_id
    END,
    connection.source_route_key,
    NULL,
    NULL,
    NULL,
    component.value
FROM oracle.toll_connection AS connection
JOIN oracle.toll_route_point AS origin
  ON origin.point_id = connection.from_point_id
CROSS JOIN LATERAL jsonb_array_elements(
    connection.source_metadata #> '{source_pair,charges}'
) WITH ORDINALITY AS component(value, ordinality)
WHERE connection.connection_type = 'within_facility'
  AND origin.network_id IN ('dtr', 'greenway')
  AND (
      (component.value->>'price_peak_usd')::numeric > 0
      OR (component.value->>'price_off_peak_usd')::numeric > 0
  );

CREATE FUNCTION oracle.validate_toll_route(
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
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
SELECT
    route.status,
    route.reason,
    route.point_ids,
    route.connection_ids,
    route.connection_types,
    route.general_purpose_gaps,
    route.i95_evidence
FROM oracle.resolve_toll_route($1, $2) AS route
$function$;

CREATE FUNCTION oracle.validate_pricing_route(
    submitted_point_ids text[],
    submitted_connection_ids text[]
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

    IF submitted_point_ids IS NULL
       OR submitted_connection_ids IS NULL
       OR cardinality(submitted_point_ids) = 0
       OR cardinality(submitted_connection_ids) = 0 THEN
        status := 'invalid_route';
        reason := jsonb_build_object(
            'code', 'route_required',
            'details', jsonb_build_object()
        );
        RETURN NEXT;
        RETURN;
    END IF;

    IF array_ndims(submitted_point_ids) <> 1
       OR array_ndims(submitted_connection_ids) <> 1
       OR array_lower(submitted_point_ids, 1) <> 1
       OR array_lower(submitted_connection_ids, 1) <> 1
       OR cardinality(submitted_point_ids) > 13
       OR cardinality(submitted_connection_ids) > 12
       OR cardinality(submitted_point_ids)
            <> cardinality(submitted_connection_ids) + 1
       OR array_position(submitted_point_ids, NULL) IS NOT NULL
       OR array_position(submitted_connection_ids, NULL) IS NOT NULL
       OR cardinality(submitted_point_ids) <> (
           SELECT count(DISTINCT submitted_point_id)
           FROM unnest(submitted_point_ids) AS submitted(submitted_point_id)
       ) THEN
        status := 'invalid_route';
        reason := jsonb_build_object(
            'code', 'route_shape_mismatch',
            'details', jsonb_build_object()
        );
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT * INTO STRICT resolved
    FROM oracle.resolve_toll_route(
        submitted_point_ids[1],
        submitted_point_ids[cardinality(submitted_point_ids)]
    );

    IF cardinality(resolved.point_ids) = 0 THEN
        status := resolved.status;
        reason := resolved.reason;
        RETURN NEXT;
        RETURN;
    END IF;

    IF submitted_point_ids IS DISTINCT FROM resolved.point_ids
       OR submitted_connection_ids IS DISTINCT FROM resolved.connection_ids THEN
        status := 'invalid_route';
        reason := jsonb_build_object(
            'code', 'route_not_canonical',
            'details', jsonb_build_object()
        );
        RETURN NEXT;
        RETURN;
    END IF;

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
        FROM generate_subscripts(connection_ids, 1)
             AS step(connection_index)
        JOIN oracle.route_pricing_component AS component
          ON component.connection_id = connection_ids[step.connection_index]
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
                        point_ids[numbered.connection_index],
                        point_ids[numbered.connection_index + 1]
                    )
                END,
                'connection_ids', jsonb_build_array(
                    connection_ids[numbered.connection_index]
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
    ) INTO facility_legs
    FROM numbered;

    RETURN NEXT;
END
$function$;

REVOKE ALL ON TABLE oracle.route_pricing_component FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.resolve_toll_route(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.validate_toll_route(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.validate_pricing_route(text[], text[]) FROM PUBLIC;

ALTER VIEW oracle.route_pricing_component OWNER TO oracle_owner;
ALTER FUNCTION oracle.resolve_toll_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_toll_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_pricing_route(text[], text[]) OWNER TO oracle_owner;

GRANT EXECUTE ON FUNCTION oracle.validate_toll_route(text, text)
TO tollchat_agent;
GRANT EXECUTE ON FUNCTION oracle.validate_pricing_route(text[], text[])
TO tollchat_agent;

UPDATE oracle.schema_version
SET version = '1.1.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.0.2';

\endif

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.1.0'
       OR to_regclass('oracle.route_pricing_component') IS NULL
       OR to_regprocedure('oracle.resolve_toll_route(text,text)') IS NULL
       OR to_regprocedure('oracle.validate_toll_route(text,text)') IS NULL
       OR to_regprocedure('oracle.validate_pricing_route(text[],text[])') IS NULL
       OR has_function_privilege(
           'tollchat_agent', 'oracle.resolve_toll_route(text,text)', 'EXECUTE'
       )
       OR NOT has_function_privilege(
           'tollchat_agent', 'oracle.validate_toll_route(text,text)', 'EXECUTE'
       )
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.validate_pricing_route(text[],text[])',
           'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'oracle 1.1.0 route validation contract is not satisfied';
    END IF;
END
$migration$;

COMMIT;

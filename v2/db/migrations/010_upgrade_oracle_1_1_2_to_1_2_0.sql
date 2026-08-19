-- Resolve and project a pricing route atomically from its endpoints.

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

    IF current_version NOT IN ('1.1.2', '1.2.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.1.2 or 1.2.0, got %',
            current_version;
    END IF;
END
$migration$;

SELECT version = '1.1.2' AS oracle_upgrade_needed
FROM oracle.schema_version
WHERE singleton
\gset

\if :oracle_upgrade_needed

DROP FUNCTION oracle.validate_pricing_route(text[], text[]);

CREATE FUNCTION oracle.validate_pricing_route(
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

REVOKE ALL ON FUNCTION oracle.validate_pricing_route(text, text) FROM PUBLIC;
ALTER FUNCTION oracle.validate_pricing_route(text, text) OWNER TO oracle_owner;
GRANT EXECUTE ON FUNCTION oracle.validate_pricing_route(text, text)
TO tollchat_agent;

UPDATE oracle.schema_version
SET version = '1.2.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.1.2';

\endif

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.2.0'
       OR to_regprocedure(
           'oracle.validate_pricing_route(text[],text[])'
       ) IS NOT NULL
       OR to_regprocedure(
           'oracle.validate_pricing_route(text,text)'
       ) IS NULL
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.validate_pricing_route(text,text)',
           'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'oracle 1.2.0 atomic pricing route is not installed';
    END IF;
END
$migration$;

COMMIT;

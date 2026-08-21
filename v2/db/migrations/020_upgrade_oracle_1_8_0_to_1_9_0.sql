-- Expose bounded route-point prompt data to the v2 agent.

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

    IF current_version NOT IN ('1.8.0', '1.9.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.8.0 or 1.9.0, got %',
            current_version;
    END IF;
    IF to_regrole('tollchat_agent') IS NULL
       OR to_regrole('pricing_caller') IS NULL
       OR to_regclass('oracle.toll_route_point') IS NULL
       OR to_regprocedure('oracle.validate_toll_route(text,text)') IS NULL THEN
        RAISE EXCEPTION 'oracle 1.9.0 requires the oracle 1.8.0 contract';
    END IF;
END
$migration$;

CREATE OR REPLACE FUNCTION oracle.get_toll_route_prompt_points() RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
SELECT coalesce(
    jsonb_agg(
        jsonb_build_object(
            'point_id', route_point.point_id,
            'network_id', route_point.network_id,
            'source_node_id', route_point.source_node_id,
            'point_type', route_point.point_type,
            'direction', route_point.direction,
            'label', route_point.label,
            'aliases', to_jsonb(route_point.aliases),
            'location', CASE
                WHEN route_point.location IS NULL THEN NULL
                ELSE oracle.ST_AsGeoJSON(route_point.location, 15, 0)::jsonb
            END
        )
        ORDER BY route_point.point_id
    ),
    '[]'::jsonb
)
FROM oracle.toll_route_point AS route_point
$function$;

ALTER FUNCTION oracle.get_toll_route_prompt_points() OWNER TO oracle_owner;
REVOKE ALL ON FUNCTION oracle.get_toll_route_prompt_points() FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle.get_toll_route_prompt_points() FROM pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_toll_route_prompt_points()
TO tollchat_agent;

UPDATE oracle.schema_version
SET version = '1.9.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.8.0';

DO $migration$
DECLARE
    agent_executable_count integer;
    pricing_executable_count integer;
    prompt_point_count integer;
BEGIN
    SELECT count(*) INTO agent_executable_count
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND has_function_privilege('tollchat_agent', procedure.oid, 'EXECUTE');
    SELECT count(*) INTO pricing_executable_count
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND has_function_privilege('pricing_caller', procedure.oid, 'EXECUTE');
    SELECT jsonb_array_length(oracle.get_toll_route_prompt_points())
    INTO prompt_point_count;

    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.9.0'
       OR prompt_point_count <> 220
       OR agent_executable_count <> 2
       OR pricing_executable_count <> 7
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.get_toll_route_prompt_points()',
           'EXECUTE'
       )
       OR has_function_privilege(
           'pricing_caller',
           'oracle.get_toll_route_prompt_points()',
           'EXECUTE'
       )
       OR has_schema_privilege('tollchat_agent', 'oracle', 'CREATE')
       OR has_schema_privilege('pricing_caller', 'oracle', 'CREATE')
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname IN ('oracle', 'pricing')
             AND (
                 has_table_privilege(
                     'tollchat_agent', relation.oid,
                     'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                 )
                 OR has_table_privilege(
                     'pricing_caller', relation.oid,
                     'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                 )
             )
       ) THEN
        RAISE EXCEPTION 'oracle 1.9.0 prompt-point surface is not installed safely';
    END IF;
END
$migration$;

COMMIT;

-- Restrict TP1NB restart offers to northbound I-95 origins at or south of the junction.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
    function_definition text;
    old_predicate constant text := $old$
           AND origin_direction = 'NB'
           AND destination_network = 'i495'$old$;
    new_predicate constant text := $new$
           AND origin_direction = 'NB'
           AND origin_position <= (
               SELECT (restart_point.source_metadata
                   -> 'source_node' ->> 'latitude')::double precision
               FROM oracle.toll_route_point AS restart_point
               WHERE restart_point.point_id = 'i495:192NO'
           )
           AND destination_network = 'i495'$new$;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.10.0', '1.10.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.10.0 or 1.10.1, got %',
            current_version;
    END IF;

    IF current_version = '1.10.0' THEN
        SELECT pg_get_functiondef(
            'oracle.resolve_toll_route_internal(text,text,boolean)'::regprocedure
        ) INTO function_definition;
        IF strpos(function_definition, old_predicate) = 0 THEN
            RAISE EXCEPTION 'oracle 1.10.0 restart predicate did not match';
        END IF;
        EXECUTE replace(function_definition, old_predicate, new_predicate);
    END IF;
END
$migration$;

UPDATE oracle.schema_version
SET version = '1.10.1', installed_at = statement_timestamp()
WHERE singleton AND version = '1.10.0';

DO $postcheck$
DECLARE
    result record;
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.10.1' THEN
        RAISE EXCEPTION 'oracle schema version did not advance to 1.10.1';
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:206NO', 'i495:1859ND');
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'i95_northbound_requires_i495_restart' THEN
        RAISE EXCEPTION 'south-of-junction TP1NB restart changed: %',
            row_to_json(result);
    END IF;

    SELECT * INTO result
    FROM oracle.validate_toll_route('i95:224NO', 'i495:1859ND');
    IF result.status <> 'invalid_origin'
       OR result.reason->>'code' <> 'origin_ramp_incompatible' THEN
        RAISE EXCEPTION 'north-of-junction origin received TP1NB restart: %',
            row_to_json(result);
    END IF;
END
$postcheck$;

COMMIT;

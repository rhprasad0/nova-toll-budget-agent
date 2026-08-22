-- Add bounded straight-line distance for validated priced route legs.

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

    IF current_version NOT IN ('1.10.1', '1.11.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.10.1 or 1.11.0, got %',
            current_version;
    END IF;

    IF current_version = '1.10.1' THEN
        EXECUTE $sql$
CREATE FUNCTION oracle.get_priced_route_distance_miles(
    facility_legs jsonb
) RETURNS numeric
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    leg_count integer;
    distance_count integer;
    distance_miles numeric;
BEGIN
    IF jsonb_typeof(facility_legs) <> 'array'
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements(facility_legs) AS leg(value)
           WHERE jsonb_typeof(leg.value) <> 'object'
              OR jsonb_typeof(leg.value->'point_ids') <> 'array'
              OR jsonb_array_length(leg.value->'point_ids') <> 2
              OR jsonb_typeof(leg.value->'point_ids'->0) <> 'string'
              OR jsonb_typeof(leg.value->'point_ids'->1) <> 'string'
       ) THEN
        RAISE EXCEPTION 'facility legs are malformed';
    END IF;

    leg_count := jsonb_array_length(facility_legs);
    IF leg_count = 0 THEN
        RETURN 0;
    END IF;

    SELECT
        count(oracle.ST_Distance(origin.location, destination.location, true)),
        sum(oracle.ST_Distance(origin.location, destination.location, true))
            / 1609.344
    INTO distance_count, distance_miles
    FROM jsonb_array_elements(facility_legs) AS leg(value)
    LEFT JOIN oracle.toll_route_point AS origin
      ON origin.point_id = leg.value->'point_ids'->>0
    LEFT JOIN oracle.toll_route_point AS destination
      ON destination.point_id = leg.value->'point_ids'->>1;

    RETURN CASE WHEN distance_count = leg_count THEN distance_miles ELSE NULL END;
END
$function$
$sql$;
        ALTER FUNCTION oracle.get_priced_route_distance_miles(jsonb)
        OWNER TO oracle_owner;
        REVOKE ALL ON FUNCTION oracle.get_priced_route_distance_miles(jsonb)
        FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION oracle.get_priced_route_distance_miles(jsonb)
        TO pricing_caller;
    END IF;
END
$migration$;

UPDATE oracle.schema_version
SET version = '1.11.0', installed_at = statement_timestamp()
WHERE singleton AND version = '1.10.1';

DO $postcheck$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.11.0' THEN
        RAISE EXCEPTION 'oracle schema version did not advance to 1.11.0';
    END IF;
    IF oracle.get_priced_route_distance_miles('[]'::jsonb) <> 0 THEN
        RAISE EXCEPTION 'empty priced route distance is not zero';
    END IF;
    IF NOT has_function_privilege(
        'pricing_caller',
        'oracle.get_priced_route_distance_miles(jsonb)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'pricing caller cannot execute priced route distance';
    END IF;
END
$postcheck$;

COMMIT;

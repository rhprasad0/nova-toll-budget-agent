-- Add pure-facility report routes and broad I-66 endpoint geography.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

SELECT
    to_regrole('pricing_owner') IS NOT NULL
        AS oracle_115_pricing_owner_exists,
    to_regrole('pricing_owner_development') IS NOT NULL
        AS oracle_115_development_pricing_owner_exists
\gset
\if :oracle_115_pricing_owner_exists
SET LOCAL ROLE pricing_owner;
\elif :oracle_115_development_pricing_owner_exists
SET LOCAL ROLE pricing_owner_development;
\endif
DO $migration$
BEGIN
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0' THEN
        RAISE EXCEPTION 'oracle 1.15.0 requires pricing 1.3.0';
    END IF;
END
$migration$;
SET LOCAL ROLE oracle_owner;

DO $migration$
DECLARE
    current_version text;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.14.1', '1.15.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.14.1 or 1.15.0, got %',
            current_version;
    END IF;
    IF to_regprocedure('oracle.get_i95_i495_report_inputs()') IS NULL
       OR NOT has_function_privilege(
           'report_publisher', 'oracle.get_i95_i495_report_inputs()', 'EXECUTE'
       )
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_i95_i495_report_inputs()'::regprocedure)
          <> 'oracle_owner'
       OR (SELECT encode(sha256(convert_to(
               pg_get_functiondef(procedure.oid), 'UTF8'
           )), 'hex')
           FROM pg_catalog.pg_proc AS procedure
           WHERE procedure.oid =
                 'oracle.get_i95_i495_report_inputs()'::regprocedure)
          <> 'c293dce3c0e2c9256e6045de06b06daf18e9ea3b89308af7fd11325a3c81d921' THEN
        RAISE EXCEPTION 'oracle 1.15.0 requires the legacy report contract';
    END IF;

    IF current_version = '1.14.1' AND (
        to_regprocedure('oracle.get_agent_report_routes()') IS NOT NULL
        OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_default_acl AS defaults
            WHERE defaults.defaclrole = 'oracle_owner'::regrole
              AND defaults.defaclobjtype = 'f'
              AND defaults.defaclnamespace IN (
                  0, 'oracle'::regnamespace
              )
        )
        OR (SELECT count(*) FROM oracle.toll_route_point) <> 220
        OR (SELECT count(*) FROM oracle.toll_connection) <> 996
        OR (SELECT count(*) FROM oracle.toll_route_point
            WHERE network_id = 'i66') <> 30
        OR EXISTS (
            SELECT 1
            FROM oracle.toll_route_point
            WHERE network_id = 'i66'
              AND num_nonnulls(place_name, region, country_code) <> 0
        )
    ) THEN
        RAISE EXCEPTION 'oracle 1.14.1 source state is incompatible';
    END IF;
END
$migration$;

SELECT version = '1.14.1' AS oracle_upgrade_needed
FROM oracle.schema_version
WHERE singleton
\gset

\if :oracle_upgrade_needed

UPDATE oracle.toll_route_point
SET place_name = CASE source_node_id
        WHEN '1' THEN 'Idylwood'
        WHEN '2' THEN 'Idylwood'
        WHEN '3' THEN 'Idylwood'
        WHEN '4' THEN 'West Falls Church'
        WHEN '5' THEN 'Idylwood'
        WHEN '6' THEN 'West Falls Church'
        WHEN '7' THEN 'Tysons'
        WHEN '8' THEN 'East Falls Church'
        WHEN '9' THEN 'Ballston'
        WHEN '10' THEN 'East Falls Church'
        WHEN '11' THEN 'East Falls Church'
        WHEN '12' THEN 'East Falls Church'
        WHEN '13' THEN 'North Arlington'
        WHEN '14' THEN 'Rosslyn'
        WHEN '15' THEN 'Pentagon area'
        WHEN '16' THEN 'Washington, D.C.'
        WHEN '17' THEN 'North Arlington'
    END,
    region = CASE source_node_id
        WHEN '16' THEN 'District of Columbia'
        ELSE 'Virginia'
    END,
    country_code = 'US'
WHERE network_id = 'i66';

CREATE FUNCTION oracle.get_agent_report_routes() RETURNS TABLE (
    facility text,
    path_id text,
    path_order integer,
    pricing_legs jsonb,
    origin_area text,
    destination_area text,
    direction text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
WITH report_points AS MATERIALIZED (
    SELECT
        logical.facility,
        point.point_id,
        point.point_type,
        point.direction,
        point.place_name
    FROM (VALUES
        ('i66'::text, ARRAY['i66']::text[]),
        ('i95_i495'::text, ARRAY['i95', 'i495']::text[])
    ) AS logical(facility, networks)
    JOIN oracle.toll_route_point AS point
      ON point.network_id = ANY(logical.networks)
), candidates AS MATERIALIZED (
    SELECT
        origin.facility,
        origin.point_id AS origin_point_id,
        destination.point_id AS destination_point_id,
        origin.place_name AS origin_area,
        destination.place_name AS destination_area,
        CASE origin.direction
            WHEN 'NB' THEN 'northbound'
            WHEN 'SB' THEN 'southbound'
            WHEN 'EB' THEN 'eastbound'
            WHEN 'WB' THEN 'westbound'
        END AS direction,
        resolved.point_ids,
        resolved.connection_ids,
        oracle.route_pricing_legs(
            resolved.point_ids, resolved.connection_ids
        ) AS full_pricing_legs
    FROM report_points AS origin
    JOIN report_points AS destination
      ON destination.facility = origin.facility
     AND destination.point_type = 'exit'
    CROSS JOIN LATERAL oracle.resolve_toll_route_internal(
        origin.point_id, destination.point_id, false
    ) AS resolved
    WHERE origin.point_type = 'entry'
      AND resolved.status = 'valid'
), pure_candidates AS MATERIALIZED (
    SELECT
        candidate.*,
        legs.pricing_legs,
        legs.signature
    FROM candidates AS candidate
    CROSS JOIN LATERAL (
        SELECT
            jsonb_agg(
                jsonb_build_object(
                    'route_step_id', leg.value->'route_step_id',
                    'facility', leg.value->'facility',
                    'pricing_key', leg.value->'pricing_key'
                ) ORDER BY leg.ord
            ) AS pricing_legs,
            jsonb_agg(
                CASE candidate.facility
                    WHEN 'i66' THEN jsonb_build_object(
                        'facility', candidate.facility,
                        'direction', candidate.direction,
                        'start_zone_id',
                            leg.value->'pricing_key'->'start_zone_id',
                        'end_zone_id',
                            leg.value->'pricing_key'->'end_zone_id',
                        'charge_index',
                            leg.value->'pricing_key'->'charge_index'
                    )
                    WHEN 'i95_i495' THEN jsonb_build_object(
                        'facility', candidate.facility,
                        'direction', candidate.direction,
                        'od_pair_id', leg.value->'pricing_key'->'od_pair_id',
                        'charge_index',
                            leg.value->'pricing_key'->'charge_index'
                    )
                END ORDER BY leg.ord
            ) AS signature
        FROM jsonb_array_elements(candidate.full_pricing_legs)
             WITH ORDINALITY AS leg(value, ord)
    ) AS legs
    WHERE jsonb_array_length(candidate.full_pricing_legs) > 0
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements(candidate.full_pricing_legs) AS leg(value)
          WHERE leg.value->>'facility' <> candidate.facility
      )
), representatives AS MATERIALIZED (
    SELECT DISTINCT ON (pure.facility, pure.signature)
        pure.facility,
        pure.signature,
        pure.pricing_legs,
        pure.origin_area,
        pure.destination_area,
        pure.direction
    FROM pure_candidates AS pure
    ORDER BY
        pure.facility,
        pure.signature,
        pure.origin_point_id,
        pure.destination_point_id,
        pure.point_ids::text,
        pure.connection_ids::text
), ordered AS (
    SELECT
        representative.*,
        row_number() OVER (
            ORDER BY representative.facility, representative.signature
        )::integer AS path_order
    FROM representatives AS representative
)
SELECT
    ordered.facility,
    ordered.facility || '-' || md5(ordered.signature::text),
    ordered.path_order,
    ordered.pricing_legs,
    ordered.origin_area,
    ordered.destination_area,
    ordered.direction
FROM ordered
ORDER BY ordered.path_order
$function$;

ALTER FUNCTION oracle.get_agent_report_routes() OWNER TO oracle_owner;
REVOKE ALL ON FUNCTION oracle.get_agent_report_routes() FROM PUBLIC;
SET LOCAL ROLE oracle_owner;
GRANT EXECUTE ON FUNCTION oracle.get_agent_report_routes()
TO report_publisher;

UPDATE oracle.schema_version
SET version = '1.15.0', installed_at = statement_timestamp()
WHERE singleton AND version = '1.14.1';

\endif

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.15.0'
       OR (SELECT count(*) FROM oracle.toll_route_point
           WHERE network_id = 'i66') <> 30
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_route_point
           WHERE network_id = 'i66'
             AND (
                 place_name IS DISTINCT FROM CASE source_node_id
                     WHEN '1' THEN 'Idylwood'
                     WHEN '2' THEN 'Idylwood'
                     WHEN '3' THEN 'Idylwood'
                     WHEN '4' THEN 'West Falls Church'
                     WHEN '5' THEN 'Idylwood'
                     WHEN '6' THEN 'West Falls Church'
                     WHEN '7' THEN 'Tysons'
                     WHEN '8' THEN 'East Falls Church'
                     WHEN '9' THEN 'Ballston'
                     WHEN '10' THEN 'East Falls Church'
                     WHEN '11' THEN 'East Falls Church'
                     WHEN '12' THEN 'East Falls Church'
                     WHEN '13' THEN 'North Arlington'
                     WHEN '14' THEN 'Rosslyn'
                     WHEN '15' THEN 'Pentagon area'
                     WHEN '16' THEN 'Washington, D.C.'
                     WHEN '17' THEN 'North Arlington'
                 END
                 OR region IS DISTINCT FROM CASE source_node_id
                     WHEN '16' THEN 'District of Columbia'
                     ELSE 'Virginia'
                 END
                 OR country_code IS DISTINCT FROM 'US'
             )
       )
       OR to_regprocedure('oracle.get_agent_report_routes()') IS NULL
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure)
          <> 'oracle_owner'
       OR NOT (SELECT prosecdef FROM pg_catalog.pg_proc
               WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure)
       OR (SELECT provolatile FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure) <> 's'
       OR (SELECT proconfig FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure)
          IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::text[]
       OR (SELECT encode(sha256(convert_to(
               pg_get_functiondef(procedure.oid), 'UTF8'
           )), 'hex')
           FROM pg_catalog.pg_proc AS procedure
           WHERE procedure.oid = 'oracle.get_agent_report_routes()'::regprocedure)
          <> '869b73886512f50e31d5c81bff6ec495b0fe8f7fea538b7f0bfe2761d619092d'
       OR (SELECT count(*)
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid =
                 'oracle.get_agent_report_routes()'::regprocedure) <> 2
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid = 'oracle.get_agent_report_routes()'::regprocedure
             AND NOT (
                 privilege.grantor = 'oracle_owner'::regrole
                 AND privilege.privilege_type = 'EXECUTE'
                 AND NOT privilege.is_grantable
                 AND privilege.grantee IN (
                     'oracle_owner'::regrole,
                     'report_publisher'::regrole
                 )
             )
       )
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid =
                 'oracle.get_agent_report_routes()'::regprocedure
             AND privilege.grantor = 'oracle_owner'::regrole
             AND privilege.grantee = 'oracle_owner'::regrole
             AND privilege.privilege_type = 'EXECUTE'
             AND NOT privilege.is_grantable
       )
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid =
                 'oracle.get_agent_report_routes()'::regprocedure
             AND privilege.grantor = 'oracle_owner'::regrole
             AND privilege.grantee = 'report_publisher'::regrole
             AND privilege.privilege_type = 'EXECUTE'
             AND NOT privilege.is_grantable
       )
       OR NOT has_function_privilege(
           'report_publisher', 'oracle.get_i95_i495_report_inputs()', 'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'oracle 1.15.0 report route contract is not installed';
    END IF;
END
$migration$;

COMMIT;

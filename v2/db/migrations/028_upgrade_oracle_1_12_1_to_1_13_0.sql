-- Add Oracle-owned report endpoint context and a bounded bulk report read.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '4min';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.12.1', '1.13.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.12.1 or 1.13.0, got %',
            current_version;
    END IF;
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0' THEN
        RAISE EXCEPTION 'oracle 1.13.0 requires pricing 1.3.0';
    END IF;
END
$migration$;

DO $upgrade$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) = '1.13.0' THEN
        RETURN;
    END IF;

    BEGIN
        CREATE ROLE report_publisher LOGIN;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'report_publisher'
          AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
               OR rolreplication OR rolbypassrls)
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
        JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
        WHERE member_role.rolname = 'report_publisher'
          AND granted_role.rolname <> 'rds_iam'
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_database AS database,
             LATERAL aclexplode(database.datacl) AS privilege
        WHERE database.datname = current_database()
          AND privilege.grantee = to_regrole('report_publisher')
          AND privilege.privilege_type IN ('CREATE', 'TEMPORARY')
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace,
             LATERAL aclexplode(namespace.nspacl) AS privilege
        WHERE privilege.grantee = to_regrole('report_publisher')
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation,
             LATERAL aclexplode(relation.relacl) AS privilege
        WHERE privilege.grantee = to_regrole('report_publisher')
    ) THEN
        RAISE EXCEPTION 'existing report_publisher role is not scoped safely';
    END IF;

    GRANT rds_iam TO report_publisher;

    ALTER TABLE oracle.toll_route_point
        ADD COLUMN place_name text,
        ADD COLUMN region text,
        ADD COLUMN country_code text;

    WITH context(source_label, place_name, region, aliases, nearby_landmarks) AS (VALUES
        ('495 Express Lanes End/George Wash. Mem. Pkwy.', 'McLean', 'Virginia', ARRAY['George Washington Memorial Parkway', 'GW Parkway', 'McLean']::text[], ARRAY['American Legion Memorial Bridge']::text[]),
        ('495 Express Lanes Start/Georg Wash. Mem. Pkwy.', 'McLean', 'Virginia', ARRAY['George Washington Memorial Parkway', 'GW Parkway', 'McLean']::text[], ARRAY['American Legion Memorial Bridge']::text[]),
        ('Braddock Road', 'Ravensworth', 'Virginia', ARRAY['Braddock Road', 'Ravensworth', 'Annandale']::text[], ARRAY[]::text[]),
        ('Courthouse Road/Route 630', 'Stafford', 'Virginia', ARRAY['Courthouse Road', 'Route 630', 'Stafford Courthouse']::text[], ARRAY[]::text[]),
        ('Fairfax County Parkway/Route 286', 'Newington', 'Virginia', ARRAY['Fairfax County Parkway', 'Route 286', 'Newington']::text[], ARRAY['Fort Belvoir']::text[]),
        ('Franconia-Springfield Parkway/Route 289', 'Springfield', 'Virginia', ARRAY['Franconia-Springfield Parkway', 'Route 289', 'Springfield']::text[], ARRAY['Franconia-Springfield Metro Station']::text[]),
        ('Gallows Road', 'Woodburn', 'Virginia', ARRAY['Gallows Road', 'Woodburn', 'Merrifield']::text[], ARRAY['Inova Fairfax Medical Campus', 'Mosaic District']::text[]),
        ('Gordon Boulevard/Route 123', 'Lorton', 'Virginia', ARRAY['Gordon Boulevard', 'Route 123', 'Occoquan', 'Lorton']::text[], ARRAY[]::text[]),
        ('Heller Road', 'Springfield', 'Virginia', ARRAY['Heller Road', 'Newington', 'Springfield']::text[], ARRAY['Fort Belvoir']::text[]),
        ('I-395 Near Edsall Road', 'Lincolnia', 'Virginia', ARRAY['Edsall Road', 'Lincolnia', 'Alexandria']::text[], ARRAY[]::text[]),
        ('I-495 EB / I-95 NB', 'Springfield', 'Virginia', ARRAY['Springfield Interchange', 'Mixing Bowl', 'Springfield']::text[], ARRAY['Springfield Town Center']::text[]),
        ('I-495 Near Braddock Road', 'North Springfield', 'Virginia', ARRAY['Braddock Road', 'North Springfield', 'Annandale']::text[], ARRAY[]::text[]),
        ('I-495/I-95 Near Van Dorn Street', 'Lincolnia', 'Virginia', ARRAY['Van Dorn Street', 'Lincolnia', 'Springfield']::text[], ARRAY[]::text[]),
        ('I-95 Near Backlick Road', 'Springfield', 'Virginia', ARRAY['Backlick Road', 'Springfield']::text[], ARRAY['Springfield Town Center']::text[]),
        ('I-95 Near Cardinal Drive', 'Montclair', 'Virginia', ARRAY['Cardinal Drive', 'Montclair', 'Dale City']::text[], ARRAY[]::text[]),
        ('I-95 Near Courthouse Road/Route 630', 'Stafford', 'Virginia', ARRAY['Courthouse Road', 'Route 630', 'Stafford Courthouse']::text[], ARRAY[]::text[]),
        ('I-95 Near Dale Boulevard', 'Potomac Mills', 'Virginia', ARRAY['Dale Boulevard', 'Potomac Mills', 'Dale City']::text[], ARRAY['Potomac Mills']::text[]),
        ('I-95 Near Dumfries Road/Route 234', 'Dumfries', 'Virginia', ARRAY['Dumfries Road', 'Route 234', 'Montclair', 'Dumfries']::text[], ARRAY[]::text[]),
        ('I-95 Near Fairfax County Parkway', 'Newington', 'Virginia', ARRAY['Fairfax County Parkway', 'Route 286', 'Newington']::text[], ARRAY['Fort Belvoir']::text[]),
        ('I-95 Near Franconia-Springfield Pkwy NB', 'Springfield', 'Virginia', ARRAY['Franconia-Springfield Parkway', 'Route 289', 'Springfield']::text[], ARRAY['Franconia-Springfield Metro Station']::text[]),
        ('I-95 Near Franconia-Springfield Pkwy SB', 'Springfield', 'Virginia', ARRAY['Franconia-Springfield Parkway', 'Route 289', 'Springfield']::text[], ARRAY['Franconia-Springfield Metro Station']::text[]),
        ('I-95 Near Garrisonville Road/Route 610', 'Stafford', 'Virginia', ARRAY['Garrisonville Road', 'Route 610', 'Stafford']::text[], ARRAY[]::text[]),
        ('I-95 Near Gordon Boulevard/Route 123', 'Lorton', 'Virginia', ARRAY['Gordon Boulevard', 'Route 123', 'Occoquan', 'Lorton']::text[], ARRAY[]::text[]),
        ('I-95 Near Joplin Road/Quantico', 'Quantico', 'Virginia', ARRAY['Joplin Road', 'Quantico']::text[], ARRAY['Marine Corps Base Quantico', 'National Museum of the Marine Corps']::text[]),
        ('I-95 Near Old Keene Mill Road/Route 644', 'Springfield', 'Virginia', ARRAY['Old Keene Mill Road', 'Route 644', 'Springfield']::text[], ARRAY['Springfield Town Center']::text[]),
        ('I-95 Near Quantico', 'Quantico', 'Virginia', ARRAY['Quantico', 'Triangle']::text[], ARRAY['Marine Corps Base Quantico', 'National Museum of the Marine Corps']::text[]),
        ('I-95 Near Route 17', 'Fredericksburg', 'Virginia', ARRAY['Route 17', 'Warrenton Road', 'Falmouth', 'Fredericksburg']::text[], ARRAY[]::text[]),
        ('I-95 Near US-1', 'Lorton', 'Virginia', ARRAY['Route 1', 'Richmond Highway', 'Lorton']::text[], ARRAY['Workhouse Arts Center']::text[]),
        ('Interstate 66', 'Idylwood', 'Virginia', ARRAY['I-66', 'Idylwood', 'Dunn Loring']::text[], ARRAY[]::text[]),
        ('Jones Branch Drive/Route 123', 'Tysons', 'Virginia', ARRAY['Jones Branch Drive', 'Route 123', 'Tysons Corner']::text[], ARRAY['The Boro Tysons']::text[]),
        ('Lee Highway (Route 29)', 'Idylwood', 'Virginia', ARRAY['Lee Highway', 'Route 29', 'Idylwood', 'Merrifield']::text[], ARRAY[]::text[]),
        ('Near Pentagon/Eads Street to DC', 'Arlington', 'Virginia', ARRAY['Pentagon', 'Pentagon City', 'Crystal City', 'National Landing']::text[], ARRAY['Pentagon', 'Ronald Reagan Washington National Airport']::text[]),
        ('Old Keene Mill Road/Route 644', 'Springfield', 'Virginia', ARRAY['Old Keene Mill Road', 'Route 644', 'Springfield']::text[], ARRAY['Springfield Town Center']::text[]),
        ('Opitz Boulevard', 'Potomac Mills', 'Virginia', ARRAY['Opitz Boulevard', 'Potomac Mills', 'Woodbridge']::text[], ARRAY['Potomac Mills']::text[]),
        ('Pentagon/Eads Street', 'Arlington', 'Virginia', ARRAY['Pentagon', 'Pentagon City', 'Crystal City', 'National Landing']::text[], ARRAY['Pentagon', 'Ronald Reagan Washington National Airport']::text[]),
        ('Prince William Parkway/Route 294', 'Potomac Mills', 'Virginia', ARRAY['Prince William Parkway', 'Route 294', 'Potomac Mills', 'Woodbridge']::text[], ARRAY['Potomac Mills']::text[]),
        ('Route 267', 'Tysons', 'Virginia', ARRAY['Dulles Toll Road', 'Dulles Access Road', 'Tysons Corner']::text[], ARRAY[]::text[]),
        ('Route 7 (Leesburg Pike)', 'Tysons', 'Virginia', ARRAY['Route 7', 'Leesburg Pike', 'Tysons Corner']::text[], ARRAY['Tysons Corner Center']::text[]),
        ('Seminary Road', 'Alexandria', 'Virginia', ARRAY['Seminary Road', 'Alexandria']::text[], ARRAY[]::text[]),
        ('Shirlington Circle', 'Alexandria', 'Virginia', ARRAY['Shirlington', 'Arlington', 'Alexandria']::text[], ARRAY['Village at Shirlington']::text[]),
        ('US-1', 'Lorton', 'Virginia', ARRAY['Route 1', 'Richmond Highway', 'Lorton']::text[], ARRAY['Workhouse Arts Center']::text[]),
        ('Washington Boulevard/Route 27', 'Arlington', 'Virginia', ARRAY['Washington Boulevard', 'Route 27', 'Pentagon']::text[], ARRAY['Pentagon', 'Arlington National Cemetery']::text[]),
        ('Washington D.C.', 'Washington', 'District of Columbia', ARRAY['Washington D.C.', 'Washington', 'District of Columbia']::text[], ARRAY['National Mall', 'Ronald Reagan Washington National Airport']::text[]),
        ('Westpark Drive', 'Tysons', 'Virginia', ARRAY['Westpark Drive', 'Tysons Corner']::text[], ARRAY['Tysons Galleria']::text[])
    )
    UPDATE oracle.toll_route_point AS route_point
    SET place_name = context.place_name,
        region = context.region,
        country_code = 'US',
        aliases = route_point.aliases || ARRAY(
            SELECT alias.value
            FROM unnest(context.aliases) AS alias(value)
            WHERE NOT alias.value = ANY(route_point.aliases)
        ),
        source_metadata = jsonb_set(
            route_point.source_metadata,
            '{report_context}',
            jsonb_build_object(
                'nearby_landmarks', to_jsonb(context.nearby_landmarks)
            ),
            true
        )
    FROM context
    WHERE route_point.network_id IN ('i95', 'i495')
      AND route_point.source_metadata->'source_node'->>'label' = context.source_label;

    UPDATE oracle.toll_route_point AS route_point
    SET place_name = point_place.place_name
    FROM (VALUES
        ('i495:187SD', 'Dunn Loring'),
        ('i495:187SO', 'Dunn Loring'),
        ('i495:188SO', 'Merrifield'),
        ('i95:216SD', 'Potomac Mills'),
        ('i95:2249ND', 'Arlington'),
        ('i95:225NO', 'Alexandria'),
        ('i95:225SD', 'Alexandria'),
        ('i95:236SO', 'Dale City')
    ) AS point_place(point_id, place_name)
    WHERE route_point.point_id = point_place.point_id;

    UPDATE oracle.toll_route_point AS route_point
    SET aliases = route_point.aliases || airport_alias.aliases
    FROM (VALUES
        ('airport_dca', ARRAY[
            'DCA', 'Reagan Airport', 'Reagan National Airport',
            'Washington National Airport'
        ]::text[]),
        ('airport_iad', ARRAY[
            'IAD', 'Dulles Airport', 'Washington Dulles'
        ]::text[])
    ) AS airport_alias(point_id, aliases)
    WHERE route_point.point_id = airport_alias.point_id;

    ALTER TABLE oracle.toll_route_point
        ADD CONSTRAINT toll_route_point_geographic_context_check CHECK (
            num_nonnulls(place_name, region, country_code) IN (0, 3)
            AND (
                place_name IS NULL
                OR (
                    btrim(place_name) <> ''
                    AND btrim(region) <> ''
                    AND country_code ~ '^[A-Z]{2}$'
                )
            )
        ),
        ADD CONSTRAINT toll_route_point_i95_i495_context_check CHECK (
            network_id NOT IN ('i95', 'i495') OR place_name IS NOT NULL
        );

    CREATE FUNCTION oracle.get_i95_i495_report_inputs() RETURNS TABLE (
    snapshot_evaluated_at timestamptz,
    origin jsonb,
    destination jsonb,
    structural_facility_legs jsonb,
    status text,
    reason jsonb,
    point_ids text[],
    connection_ids text[],
    connection_types text[],
    general_purpose_gaps jsonb,
    i95_evidence jsonb,
    facility_legs jsonb,
    route_step_id text,
    comparison_kind text,
    comparison_offset integer,
    bin_start_at timestamptz,
    bin_end_at timestamptz,
    interval_end_at timestamptz,
    observed_at timestamptz,
    price_usd numeric,
    available boolean,
    availability_reason text,
    source_kind text,
    pricing_method text,
    od_pair_id integer,
    proxy_od_pair_id integer,
    source_status text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
WITH report_points AS MATERIALIZED (
    SELECT
        route_point.point_id,
        route_point.point_type,
        jsonb_build_object(
            'point_id', route_point.point_id,
            'label', route_point.label,
            'place_name', route_point.place_name,
            'region', route_point.region,
            'country_code', route_point.country_code,
            'aliases', to_jsonb(route_point.aliases),
            'nearby_landmarks', coalesce(
                route_point.source_metadata
                    #> '{report_context,nearby_landmarks}',
                '[]'::jsonb
            ),
            'direction', CASE route_point.direction
                WHEN 'NB' THEN 'northbound'
                WHEN 'SB' THEN 'southbound'
            END,
            'role', route_point.point_type,
            'display_name', format(
                '%s, %s — %s (%s %s)',
                route_point.place_name,
                route_point.region,
                route_point.label,
                CASE route_point.direction
                    WHEN 'NB' THEN 'northbound'
                    WHEN 'SB' THEN 'southbound'
                END,
                route_point.point_type
            ),
            'location', oracle.ST_AsGeoJSON(
                route_point.location, 15, 0
            )::jsonb
        ) AS endpoint
    FROM oracle.toll_route_point AS route_point
    WHERE route_point.network_id IN ('i95', 'i495')
), structural_routes AS MATERIALIZED (
    SELECT
        origin.point_id AS origin_point_id,
        destination.point_id AS destination_point_id,
        origin.endpoint AS origin,
        destination.endpoint AS destination,
        structural.status,
        structural.point_ids,
        structural.connection_ids,
        oracle.route_pricing_legs(
            structural.point_ids, structural.connection_ids
        ) AS facility_legs
    FROM report_points AS origin
    CROSS JOIN report_points AS destination
    CROSS JOIN LATERAL oracle.resolve_toll_route_internal(
        origin.point_id, destination.point_id, false
    ) AS structural
    WHERE origin.point_type = 'entry'
      AND destination.point_type = 'exit'
), eligible_routes AS MATERIALIZED (
    SELECT *
    FROM structural_routes
    WHERE status = 'valid'
      AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(facility_legs) AS leg(value)
          WHERE leg.value->>'facility' = 'i95_i495'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements(facility_legs) AS leg(value)
          WHERE leg.value->>'facility' <> 'i95_i495'
      )
), current_routes AS MATERIALIZED (
    SELECT
        eligible.origin_point_id,
        eligible.destination_point_id,
        eligible.origin,
        eligible.destination,
        eligible.facility_legs AS structural_facility_legs,
        current_route.*
    FROM eligible_routes AS eligible
    CROSS JOIN LATERAL oracle.validate_pricing_route(
        eligible.origin_point_id, eligible.destination_point_id
    ) AS current_route
)
SELECT
    statement_timestamp(),
    current_route.origin,
    current_route.destination,
    current_route.structural_facility_legs,
    current_route.status,
    current_route.reason,
    current_route.point_ids,
    current_route.connection_ids,
    current_route.connection_types,
    current_route.general_purpose_gaps,
    current_route.i95_evidence,
    current_route.facility_legs,
    leg.value->>'route_step_id',
    comparison.comparison_kind,
    comparison.comparison_offset,
    comparison.bin_start_at,
    comparison.bin_end_at,
    comparison.interval_end_at,
    comparison.observed_at,
    comparison.price_usd,
    comparison.available,
    comparison.availability_reason,
    comparison.source_kind,
    comparison.pricing_method,
    comparison.od_pair_id,
    comparison.proxy_od_pair_id,
    comparison.source_status
FROM current_routes AS current_route
LEFT JOIN LATERAL jsonb_array_elements(
    current_route.facility_legs
) AS leg(value) ON current_route.status = 'valid'
LEFT JOIN LATERAL oracle.get_i95_i495_pricing_comparisons(
    (leg.value->'pricing_key'->>'od_pair_id')::integer
) AS comparison ON leg.value IS NOT NULL
ORDER BY
    current_route.origin->>'point_id',
    current_route.destination->>'point_id',
    (substring(leg.value->>'route_step_id' FROM '[0-9]+'))::integer,
    CASE comparison.comparison_kind
        WHEN 'current' THEN 0
        WHEN 'prior_cycle' THEN 1
        ELSE 2
    END,
    comparison.comparison_offset
$function$;

    REVOKE ALL ON FUNCTION oracle.get_i95_i495_report_inputs() FROM PUBLIC;
    GRANT USAGE ON SCHEMA oracle TO report_publisher;
    GRANT EXECUTE ON FUNCTION oracle.get_i95_i495_report_inputs()
    TO report_publisher;
    ALTER FUNCTION oracle.get_i95_i495_report_inputs() OWNER TO oracle_owner;
END
$upgrade$;

DO $finish$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) = '1.12.1' THEN
        UPDATE oracle.schema_version
        SET version = '1.13.0', installed_at = statement_timestamp()
        WHERE singleton;
    END IF;

    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.13.0'
       OR to_regprocedure('oracle.get_i95_i495_report_inputs()') IS NULL
       OR (SELECT count(*) FROM oracle.toll_route_point
           WHERE network_id IN ('i95', 'i495')
             AND place_name IS NOT NULL
             AND region IS NOT NULL
             AND country_code = 'US') <> 107
       OR NOT has_function_privilege(
           'report_publisher', 'oracle.get_i95_i495_report_inputs()', 'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'oracle 1.13.0 report contract did not install cleanly';
    END IF;
END
$finish$;

COMMIT;

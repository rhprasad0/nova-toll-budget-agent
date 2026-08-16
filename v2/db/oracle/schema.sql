-- TollChat v2 PostgreSQL routing oracle bootstrap.
-- oracle schema version: 1.0.0

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;

DO $$
DECLARE
    pricing_version text;
    pricing_version_parts integer[];
BEGIN
    IF current_setting('server_version_num')::integer < 170000
       OR current_setting('server_version_num')::integer >= 180000 THEN
        RAISE EXCEPTION 'oracle 1.0.0 requires PostgreSQL 17';
    END IF;
    IF to_regclass('pricing.schema_version') IS NULL
       OR to_regclass('pricing.current_i95_direction') IS NULL THEN
        RAISE EXCEPTION 'oracle 1.0.0 requires pricing schema 1.x';
    END IF;
    EXECUTE 'SELECT version FROM pricing.schema_version WHERE singleton'
        INTO pricing_version;
    pricing_version_parts := string_to_array(pricing_version, '.')::integer[];
    IF pricing_version IS NULL
       OR pricing_version_parts < ARRAY[1, 0, 0]
       OR pricing_version_parts >= ARRAY[2, 0, 0] THEN
        RAISE EXCEPTION 'oracle 1.0.0 requires pricing schema 1.x; found %',
            coalesce(pricing_version, '<missing>');
    END IF;
    IF to_regrole('rds_iam') IS NULL THEN
        RAISE EXCEPTION 'oracle requires the RDS IAM database role';
    END IF;
END $$;

DO $$
BEGIN
    CREATE ROLE oracle_owner NOLOGIN;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE ROLE tollchat_agent LOGIN;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'oracle_owner'
          AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
               OR rolreplication OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'existing oracle_owner role is not a scoped NOLOGIN owner';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'tollchat_agent'
          AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
               OR rolreplication OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'existing tollchat_agent role is not a scoped LOGIN role';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        WHERE member_role.rolname = 'tollchat_agent'
          AND granted_role.rolname <> 'rds_iam'
    ) THEN
        RAISE EXCEPTION 'existing tollchat_agent has an unexpected role membership';
    END IF;
END $$;

GRANT rds_iam TO tollchat_agent;

CREATE SCHEMA oracle;
REVOKE ALL ON SCHEMA oracle FROM PUBLIC;

CREATE EXTENSION postgis WITH SCHEMA oracle;

DO $$
DECLARE
    installed_version text;
BEGIN
    SELECT extversion INTO installed_version
    FROM pg_catalog.pg_extension
    WHERE extname = 'postgis';
    IF installed_version !~ '^3[.]5([.]|$)' THEN
        RAISE EXCEPTION 'oracle 1.0.0 requires PostGIS 3.5.x; found %',
            coalesce(installed_version, '<missing>');
    END IF;
END $$;

CREATE TABLE oracle.schema_version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version text NOT NULL CHECK (
        version ~ '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$'
    ),
    installed_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

INSERT INTO oracle.schema_version (version) VALUES ('1.0.0');

CREATE TABLE oracle.toll_route_point (
    point_id text PRIMARY KEY,
    network_id text NOT NULL CHECK (
        network_id IN (
            'i95', 'i495', 'i66', 'dtr', 'greenway',
            'airport_iad', 'airport_dca'
        )
    ),
    source_node_id text NOT NULL,
    point_type text NOT NULL CHECK (point_type IN ('entry', 'exit', 'airport')),
    direction text CHECK (direction IN ('NB', 'SB', 'EB', 'WB')),
    label text NOT NULL CHECK (label <> ''),
    location oracle.geography(Point, 4326),
    aliases text[] NOT NULL DEFAULT ARRAY[]::text[],
    source_metadata jsonb NOT NULL CHECK (jsonb_typeof(source_metadata) = 'object'),
    CHECK ((point_type = 'airport') = (direction IS NULL)),
    CHECK ((point_type = 'airport') = (network_id LIKE 'airport_%')),
    UNIQUE NULLS NOT DISTINCT (network_id, source_node_id, point_type, direction)
);

CREATE TABLE oracle.toll_connection (
    connection_id text PRIMARY KEY,
    from_point_id text NOT NULL REFERENCES oracle.toll_route_point (point_id),
    to_point_id text NOT NULL REFERENCES oracle.toll_route_point (point_id),
    connection_type text NOT NULL CHECK (
        connection_type IN (
            'within_facility', 'toll_handoff',
            'general_purpose_gap', 'airport_access'
        )
    ),
    required_i95_direction text CHECK (required_i95_direction IN ('NB', 'SB')),
    source_route_key text,
    source_metadata jsonb NOT NULL CHECK (jsonb_typeof(source_metadata) = 'object'),
    CHECK (from_point_id <> to_point_id),
    UNIQUE (from_point_id, to_point_id)
);

CREATE INDEX toll_connection_from_point_idx
    ON oracle.toll_connection (from_point_id);

\ir data.sql

CREATE FUNCTION oracle.validate_toll_route(
    origin_point_id text,
    destination_point_id text
) RETURNS TABLE (
    status text,
    point_ids text[],
    connection_ids text[],
    connection_types text[],
    general_purpose_gaps jsonb,
    i95_evidence jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    origin_role text;
    destination_role text;
BEGIN
    SELECT route_point.point_type
    INTO origin_role
    FROM oracle.toll_route_point AS route_point
    WHERE route_point.point_id = origin_point_id;

    IF origin_role IS NULL OR origin_role NOT IN ('entry', 'airport') THEN
        status := 'invalid_origin';
        point_ids := ARRAY[]::text[];
        connection_ids := ARRAY[]::text[];
        connection_types := ARRAY[]::text[];
        general_purpose_gaps := '[]'::jsonb;
        i95_evidence := NULL;
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT route_point.point_type
    INTO destination_role
    FROM oracle.toll_route_point AS route_point
    WHERE route_point.point_id = destination_point_id;

    IF destination_role IS NULL OR destination_role NOT IN ('exit', 'airport') THEN
        status := 'invalid_destination';
        point_ids := ARRAY[]::text[];
        connection_ids := ARRAY[]::text[];
        connection_types := ARRAY[]::text[];
        general_purpose_gaps := '[]'::jsonb;
        i95_evidence := NULL;
        RETURN NEXT;
        RETURN;
    END IF;

    WITH RECURSIVE raw_i95 AS (
        SELECT direction_view.*
        FROM pricing.current_i95_direction AS direction_view
    ),
    classified_i95 AS (
        SELECT
            CASE
                WHEN raw_i95.northbound_corridor_name IS NULL
                  OR raw_i95.southbound_corridor_name IS NULL
                  OR raw_i95.northbound_link_status IS NULL
                  OR raw_i95.southbound_link_status IS NULL
                  OR raw_i95.northbound_interval_end_at IS NULL
                  OR raw_i95.southbound_interval_end_at IS NULL
                  OR raw_i95.northbound_calculated_at IS NULL
                  OR raw_i95.southbound_calculated_at IS NULL
                    THEN 'unknown'
                WHEN raw_i95.northbound_corridor_name <> 'I-95-NB'
                  OR raw_i95.southbound_corridor_name <> 'I-95-SB'
                    THEN 'unknown'
                WHEN raw_i95.northbound_interval_end_at
                  <> raw_i95.southbound_interval_end_at
                    THEN 'unknown'
                WHEN raw_i95.northbound_calculated_at > statement_timestamp()
                  OR raw_i95.southbound_calculated_at > statement_timestamp()
                    THEN 'unknown'
                WHEN raw_i95.northbound_calculated_at
                       < statement_timestamp() - interval '20 minutes'
                  OR raw_i95.southbound_calculated_at
                       < statement_timestamp() - interval '20 minutes'
                    THEN 'unknown'
                WHEN raw_i95.northbound_link_status = 'NORTHBOUND_OPEN'
                  AND raw_i95.southbound_link_status = 'CLOSED'
                    THEN 'northbound'
                WHEN raw_i95.northbound_link_status = 'CLOSED'
                  AND raw_i95.southbound_link_status = 'SOUTHBOUND_OPEN'
                    THEN 'southbound'
                WHEN raw_i95.northbound_link_status = 'CLOSED'
                  AND raw_i95.southbound_link_status = 'CLOSED'
                    THEN 'closed'
                ELSE 'unknown'
            END AS availability,
            CASE
                WHEN raw_i95.direction_state = 'missing_source' THEN
                    jsonb_build_object('reason', 'missing_source')
                ELSE jsonb_build_object(
                    'northbound_corridor_name', raw_i95.northbound_corridor_name,
                    'northbound_link_status', raw_i95.northbound_link_status,
                    'northbound_interval_end_at', raw_i95.northbound_interval_end_at,
                    'northbound_calculated_at', raw_i95.northbound_calculated_at,
                    'southbound_corridor_name', raw_i95.southbound_corridor_name,
                    'southbound_link_status', raw_i95.southbound_link_status,
                    'southbound_interval_end_at', raw_i95.southbound_interval_end_at,
                    'southbound_calculated_at', raw_i95.southbound_calculated_at
                )
            END AS raw_evidence
        FROM raw_i95
    ),
    evidence AS (
        SELECT
            classified_i95.availability,
            classified_i95.raw_evidence
                || jsonb_build_object('availability', classified_i95.availability)
                AS evidence_json
        FROM classified_i95
        UNION ALL
        SELECT
            'unknown'::text,
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
            CASE WHEN connection.required_i95_direction IS NULL
                THEN walk.required_i95_directions
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
        choices.walked_point_ids,
        choices.walked_connection_ids,
        choices.walked_connection_types,
        choices.candidate_general_purpose_gaps,
        choices.candidate_evidence
    INTO status, point_ids, connection_ids, connection_types,
         general_purpose_gaps, i95_evidence
    FROM choices
    ORDER BY
        choices.priority,
        choices.depth,
        choices.walked_connection_ids
    LIMIT 1;

    RETURN NEXT;
END
$function$;

REVOKE ALL ON ALL TABLES IN SCHEMA oracle FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA oracle FROM PUBLIC;
REVOKE ALL ON TYPE oracle.geometry, oracle.geography FROM PUBLIC;
GRANT USAGE ON TYPE oracle.geometry, oracle.geography TO oracle_owner;

GRANT USAGE ON SCHEMA pricing TO oracle_owner;
GRANT SELECT ON pricing.current_i95_direction TO oracle_owner;
GRANT USAGE ON SCHEMA oracle TO tollchat_agent;
GRANT EXECUTE ON FUNCTION oracle.validate_toll_route(text, text)
TO tollchat_agent;

ALTER TABLE oracle.schema_version OWNER TO oracle_owner;
ALTER TABLE oracle.toll_route_point OWNER TO oracle_owner;
ALTER TABLE oracle.toll_connection OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_toll_route(text, text) OWNER TO oracle_owner;
ALTER SCHEMA oracle OWNER TO oracle_owner;

COMMIT;

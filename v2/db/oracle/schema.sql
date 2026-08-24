-- TollChat v2 PostgreSQL routing oracle bootstrap.
-- oracle schema version: 1.12.0

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
        RAISE EXCEPTION 'oracle 1.8.0 requires PostgreSQL 17';
    END IF;
    IF to_regclass('pricing.schema_version') IS NULL
       OR to_regclass('pricing.current_i95_direction') IS NULL
       OR to_regclass('pricing.i66_pricing_comparisons') IS NULL
       OR to_regclass('pricing.i66_ballpark_samples') IS NULL
       OR to_regclass('pricing.i95_i495_ballpark_samples') IS NULL THEN
        RAISE EXCEPTION 'oracle 1.8.0 requires pricing schema >=1.2.0,<2.0.0';
    END IF;
    EXECUTE 'SELECT version FROM pricing.schema_version WHERE singleton'
        INTO pricing_version;
    pricing_version_parts := string_to_array(pricing_version, '.')::integer[];
    IF pricing_version IS NULL
       OR pricing_version_parts < ARRAY[1, 2, 0]
       OR pricing_version_parts >= ARRAY[2, 0, 0] THEN
        RAISE EXCEPTION 'oracle 1.8.0 requires pricing schema >=1.2.0,<2.0.0; found %',
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
    CREATE ROLE pricing_caller LOGIN;
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
        WHERE rolname IN ('tollchat_agent', 'pricing_caller')
          AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
               OR rolreplication OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'existing runtime role is not a scoped LOGIN role';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        WHERE member_role.rolname IN ('tollchat_agent', 'pricing_caller')
          AND granted_role.rolname <> 'rds_iam'
    ) THEN
        RAISE EXCEPTION 'existing runtime role has an unexpected role membership';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_database AS database,
             LATERAL aclexplode(database.datacl) AS privilege
        WHERE database.datname = current_database()
          AND privilege.grantee IN (
              to_regrole('tollchat_agent'), to_regrole('pricing_caller')
          )
          AND privilege.privilege_type IN ('CREATE', 'TEMPORARY')
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace,
             LATERAL aclexplode(namespace.nspacl) AS privilege
        WHERE privilege.grantee IN (
            to_regrole('tollchat_agent'), to_regrole('pricing_caller')
        )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation,
             LATERAL aclexplode(relation.relacl) AS privilege
        WHERE privilege.grantee IN (
            to_regrole('tollchat_agent'), to_regrole('pricing_caller')
        )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS attribute,
             LATERAL aclexplode(attribute.attacl) AS privilege
        WHERE privilege.grantee IN (
            to_regrole('tollchat_agent'), to_regrole('pricing_caller')
        )
    ) THEN
        RAISE EXCEPTION 'existing runtime role has unexpected direct privileges';
    END IF;
END $$;

GRANT rds_iam TO tollchat_agent, pricing_caller;

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
        RAISE EXCEPTION 'oracle 1.8.0 requires PostGIS 3.5.x; found %',
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

INSERT INTO oracle.schema_version (version) VALUES ('1.12.0');

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

CREATE FUNCTION oracle.get_toll_route_prompt_points() RETURNS jsonb
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
    origin.network_id,
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
  )

UNION ALL

SELECT
    connection.connection_id,
    1,
    connection.from_point_id,
    connection.to_point_id,
    NULL,
    1,
    connection.source_metadata->>'pricing_facility',
    connection.source_route_key,
    NULL,
    NULL,
    NULL,
    connection.source_metadata->'pricing_charge'
FROM oracle.toll_connection AS connection
WHERE connection.connection_type = 'toll_handoff'
  AND connection.source_metadata ? 'pricing_facility'
  AND connection.source_metadata ? 'pricing_charge';

CREATE FUNCTION oracle.ramp_alternatives(
    submitted_point_id text,
    unchanged_point_id text,
    replace_origin boolean
) RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $function$
WITH RECURSIVE
submitted AS (
    SELECT route_point.*
    FROM oracle.toll_route_point AS route_point
    WHERE route_point.point_id = submitted_point_id
),
candidate_points AS (
    SELECT candidate.*
    FROM oracle.toll_route_point AS candidate
    CROSS JOIN submitted
    WHERE candidate.network_id = submitted.network_id
      AND candidate.point_type = CASE
          WHEN replace_origin THEN 'entry'
          ELSE 'exit'
      END
),
seeds AS (
    SELECT
        candidate.point_id AS alternative_point_id,
        candidate.point_id AS current_point_id,
        ARRAY[candidate.point_id]::text[] AS walked_point_ids,
        0 AS depth
    FROM candidate_points AS candidate
    WHERE replace_origin

    UNION ALL

    SELECT
        NULL::text,
        unchanged.point_id,
        ARRAY[unchanged.point_id]::text[],
        0
    FROM oracle.toll_route_point AS unchanged
    WHERE NOT replace_origin
      AND unchanged.point_id = unchanged_point_id
),
walk AS (
    SELECT
        seeds.alternative_point_id,
        seeds.current_point_id,
        seeds.walked_point_ids,
        seeds.depth
    FROM seeds

    UNION ALL

    SELECT
        walk.alternative_point_id,
        next_point.point_id,
        walk.walked_point_ids || next_point.point_id,
        walk.depth + 1
    FROM walk
    JOIN oracle.toll_route_point AS current_point
      ON current_point.point_id = walk.current_point_id
    JOIN oracle.toll_connection AS connection
      ON connection.from_point_id = walk.current_point_id
    JOIN oracle.toll_route_point AS next_point
      ON next_point.point_id = connection.to_point_id
    WHERE walk.depth < 12
      AND (NOT replace_origin OR walk.current_point_id <> unchanged_point_id)
      AND NOT next_point.point_id = ANY(walk.walked_point_ids)
      AND (
          current_point.point_type <> 'airport'
          OR (NOT replace_origin AND current_point.point_id = unchanged_point_id)
      )
      AND (
          next_point.point_type <> 'airport'
          OR (replace_origin AND next_point.point_id = unchanged_point_id)
      )
),
reachable AS (
    SELECT DISTINCT
        CASE
            WHEN replace_origin THEN walk.alternative_point_id
            ELSE walk.current_point_id
        END AS point_id
    FROM walk
    WHERE walk.depth > 0
      AND (
          (replace_origin AND walk.current_point_id = unchanged_point_id)
          OR (
              NOT replace_origin
              AND EXISTS (
                  SELECT 1
                  FROM candidate_points AS candidate
                  WHERE candidate.point_id = walk.current_point_id
              )
          )
      )
),
ranked AS (
    SELECT
        candidate.*,
        coalesce(preference.rank, 2147483647) AS preference_rank,
        CASE
            WHEN candidate.source_node_id = submitted.source_node_id THEN 0
            WHEN candidate.source_metadata
                     -> 'alternative_ranking' ->> 'corridor_position' IS NOT NULL
              AND submitted.source_metadata
                     -> 'alternative_ranking' ->> 'corridor_position' IS NOT NULL THEN
                abs(
                    (candidate.source_metadata
                        -> 'alternative_ranking' ->> 'corridor_position')::double precision
                    - (submitted.source_metadata
                        -> 'alternative_ranking' ->> 'corridor_position')::double precision
                )
            WHEN candidate.network_id IN ('i95', 'i495')
              AND candidate.location IS NOT NULL
              AND submitted.location IS NOT NULL THEN
                oracle.ST_Distance(candidate.location, submitted.location)
            ELSE 'Infinity'::double precision
        END AS distance
    FROM reachable
    JOIN candidate_points AS candidate USING (point_id)
    CROSS JOIN submitted
    LEFT JOIN LATERAL (
        SELECT preferred.ordinality::integer AS rank
        FROM jsonb_array_elements_text(
            coalesce(
                submitted.source_metadata
                    -> 'alternative_ranking' -> 'preferred_point_ids',
                '[]'::jsonb
            )
        ) WITH ORDINALITY AS preferred(point_id, ordinality)
        WHERE preferred.point_id = candidate.point_id
    ) AS preference ON true
    ORDER BY
        coalesce(preference.rank, 2147483647),
        distance,
        candidate.point_id
    LIMIT 2
)
SELECT coalesce(
    jsonb_agg(
        jsonb_build_object(
            'point_id', ranked.point_id,
            'network_id', ranked.network_id,
            'source_node_id', ranked.source_node_id,
            'point_type', ranked.point_type,
            'direction', ranked.direction,
            'label', ranked.label,
            'aliases', to_jsonb(ranked.aliases),
            'location', CASE
                WHEN ranked.location IS NULL THEN NULL
                ELSE oracle.ST_AsGeoJSON(ranked.location)::jsonb
            END
        )
        ORDER BY ranked.preference_rank, ranked.distance, ranked.point_id
    ),
    '[]'::jsonb
)
FROM ranked
$function$;

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
        IF origin_network = 'i95'
           AND origin_role = 'entry'
           AND origin_direction = 'NB'
           AND origin_position <= (
               SELECT (restart_point.source_metadata
                   -> 'source_node' ->> 'latitude')::double precision
               FROM oracle.toll_route_point AS restart_point
               WHERE restart_point.point_id = 'i495:192NO'
           )
           AND destination_network = 'i495'
           AND destination_role = 'exit'
           AND destination_direction = 'NB' THEN
            status := 'invalid_origin';
            reason := jsonb_build_object(
                'code', 'i95_northbound_requires_i495_restart',
                'details', jsonb_build_object(
                    'point_id', origin_point_id,
                    'point_type', origin_role,
                    'suggested_restart_point_id', 'i495:192NO',
                    'suggested_destination_point_id', CASE
                        WHEN destination_point_id = 'i495:1859ND'
                            THEN 'i495:185ND'
                        ELSE destination_point_id
                    END
                )
            );
        END IF;

        IF status = 'no_supported_route'
           AND origin_network = destination_network
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

        IF status = 'no_supported_route'
           AND (requested_direction IS NULL
           OR origin_incompatible
           OR (NOT origin_incompatible AND NOT destination_incompatible)) THEN
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

CREATE FUNCTION oracle.resolve_toll_route(
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
$function$;

CREATE FUNCTION oracle.i66_tolling_active(
    requested_direction text,
    requested_local_at timestamp
) RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    local_date date := requested_local_at::date;
    local_time time := requested_local_at::time;
    is_holiday boolean;
BEGIN
    IF requested_direction NOT IN ('EB', 'WB') THEN
        RAISE EXCEPTION 'invalid I-66 direction';
    END IF;

    WITH years(value) AS (
        SELECT generate_series(
            extract(year FROM local_date)::integer - 1,
            extract(year FROM local_date)::integer + 1
        )
    ), holidays AS (
        SELECT holiday.value, holiday.fixed
        FROM years
        CROSS JOIN LATERAL (VALUES
            (make_date(years.value, 1, 1), true),
            (make_date(years.value, 1, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 1, 1))::integer) % 7)
                + 14, false),
            (make_date(years.value, 2, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 2, 1))::integer) % 7)
                + 14, false),
            (make_date(years.value, 6, 1)
                - ((extract(isodow FROM make_date(years.value, 6, 1))::integer + 5) % 7 + 1), false),
            (make_date(years.value, 6, 19), true),
            (make_date(years.value, 7, 4), true),
            (make_date(years.value, 9, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 9, 1))::integer) % 7), false),
            (make_date(years.value, 10, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 10, 1))::integer) % 7)
                + 7, false),
            (make_date(years.value, 11, 11), true),
            (make_date(years.value, 11, 1)
                + ((11 - extract(isodow FROM make_date(years.value, 11, 1))::integer) % 7)
                + 21, false),
            (make_date(years.value, 12, 25), true)
        ) AS holiday(value, fixed)
    )
    SELECT coalesce(bool_or(
        local_date = holiday.value
        OR (holiday.fixed AND local_date = holiday.value + CASE
            WHEN extract(isodow FROM holiday.value) = 6 THEN -1
            WHEN extract(isodow FROM holiday.value) = 7 THEN 1
            ELSE 0
        END)
    ), false)
    INTO is_holiday
    FROM holidays AS holiday;

    RETURN extract(isodow FROM local_date) <= 5
       AND NOT is_holiday
       AND CASE requested_direction
            WHEN 'EB' THEN local_time >= time '05:30' AND local_time < time '09:30'
            ELSE local_time >= time '15:00' AND local_time < time '19:00'
       END;
END
$function$;

COMMENT ON FUNCTION oracle.i66_tolling_active(text, timestamp) IS
'VDOT I-66 Inside the Beltway weekday schedule and federal-holiday closure; source snapshot retrieved 2026-08-24 from https://www.vdot.virginia.gov/projects/major-projects/66expresslanes/faqs/';

CREATE FUNCTION oracle.get_i66_pricing_comparisons(
    requested_start_zone_id integer,
    requested_end_zone_id integer,
    requested_direction text
) RETURNS TABLE (
    evaluated_at timestamptz,
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
    pricing_method text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    evaluation_at timestamptz := statement_timestamp();
BEGIN
    IF requested_start_zone_id IS NULL
       OR requested_end_zone_id IS NULL
       OR requested_direction NOT IN ('EB', 'WB')
       OR NOT EXISTS (
            SELECT 1
            FROM oracle.route_pricing_component AS component
            WHERE component.facility = 'i66'
              AND component.start_zone_id = requested_start_zone_id
              AND component.end_zone_id = requested_end_zone_id
              AND split_part(component.source_route_key, ':', 1)
                  = requested_direction
       ) THEN
        RAISE EXCEPTION 'invalid I-66 pricing component';
    END IF;

    RETURN QUERY
    WITH selected AS MATERIALIZED (
        SELECT comparison.*
        FROM pricing.i66_pricing_comparisons AS comparison
        WHERE comparison.start_zone_id = requested_start_zone_id
          AND comparison.end_zone_id = requested_end_zone_id
    ), instant_targets AS (
        SELECT
            'current'::text AS comparison_kind,
            0 AS comparison_offset,
            date_bin(
                interval '6 minutes', evaluation_at,
                timestamptz '2000-01-01 00:00:00+00'
            ) AS bin_start_at
        UNION ALL
        SELECT
            'prior_cycle',
            offset_number,
            date_bin(
                interval '6 minutes', evaluation_at,
                timestamptz '2000-01-01 00:00:00+00'
            ) - make_interval(mins => 6 * offset_number)
        FROM generate_series(1, 2) AS offsets(offset_number)
    ), week_specs AS (
        SELECT
            offset_number AS comparison_offset,
            (evaluation_at AT TIME ZONE 'America/New_York')
                - make_interval(days => 7 * offset_number) AS wall_time
        FROM generate_series(1, 3) AS offsets(offset_number)
    ), week_candidates AS (
        SELECT
            week.comparison_offset,
            week.wall_time,
            (week.wall_time AT TIME ZONE 'UTC')
                + make_interval(hours => offset_number) AS candidate_at
        FROM week_specs AS week
        CROSS JOIN generate_series(-14, 14) AS offsets(offset_number)
    ), week_targets AS (
        SELECT
            'prior_week'::text AS comparison_kind,
            candidate.comparison_offset,
            date_bin(
                interval '6 minutes', min(candidate.candidate_at),
                timestamptz '2000-01-01 00:00:00+00'
            ) AS bin_start_at
        FROM week_candidates AS candidate
        WHERE candidate.candidate_at AT TIME ZONE 'America/New_York'
              = candidate.wall_time
        GROUP BY candidate.comparison_offset
        HAVING count(*) = 1
    ), targets AS MATERIALIZED (
        SELECT
            target.*,
            oracle.i66_tolling_active(
                requested_direction,
                CASE target.comparison_kind
                    WHEN 'current' THEN
                        evaluation_at AT TIME ZONE 'America/New_York'
                    ELSE target.bin_start_at AT TIME ZONE 'America/New_York'
                END
            ) AS tolling_active
        FROM (
            SELECT * FROM instant_targets
            UNION ALL
            SELECT * FROM week_targets
        ) AS target
    ), observed AS (
        SELECT
            comparison.evaluated_at,
            target.comparison_kind,
            target.comparison_offset,
            comparison.bin_start_at,
            comparison.bin_end_at,
            comparison.interval_end_at,
            comparison.observed_at,
            comparison.price_usd,
            comparison.available,
            comparison.availability_reason,
            comparison.source_kind,
            comparison.pricing_method
        FROM targets AS target
        JOIN selected AS comparison
          ON comparison.comparison_kind = target.comparison_kind
         AND comparison.comparison_offset = target.comparison_offset
         AND (
              target.comparison_kind = 'current'
              OR comparison.bin_start_at = target.bin_start_at
         )
        WHERE target.tolling_active
    ), scheduled AS (
        SELECT
            evaluation_at,
            target.comparison_kind,
            target.comparison_offset,
            target.bin_start_at,
            target.bin_start_at + interval '6 minutes',
            NULL::timestamptz,
            NULL::timestamptz,
            0::numeric,
            true,
            NULL::text,
            'schedule_derived'::text,
            'published_schedule'::text
        FROM targets AS target
        WHERE NOT target.tolling_active
    ), diagnostic AS (
        SELECT
            evaluation_at,
            'current'::text,
            0,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::numeric,
            false,
            'missing_observation'::text,
            NULL::text,
            NULL::text
        FROM targets AS target
        WHERE target.comparison_kind = 'current'
          AND target.tolling_active
          AND NOT EXISTS (
              SELECT 1 FROM observed WHERE observed.comparison_kind = 'current'
          )
    ), combined AS (
        SELECT * FROM observed
        UNION ALL
        SELECT * FROM scheduled
        UNION ALL
        SELECT * FROM diagnostic
    )
    SELECT * FROM combined
    ORDER BY
        CASE combined.comparison_kind
            WHEN 'current' THEN 0
            WHEN 'prior_cycle' THEN 1
            ELSE 2
        END,
        combined.comparison_offset;
END
$function$;

-- Compatibility for the currently deployed 1.4 tool during the required
-- database-first rollout. Remove after every runtime calls the overload above.
CREATE FUNCTION oracle.get_i66_pricing_comparisons(
    requested_start_zone_id integer,
    requested_end_zone_id integer
) RETURNS TABLE (
    evaluated_at timestamptz,
    comparison_kind text,
    comparison_offset integer,
    bin_start_at timestamptz,
    bin_end_at timestamptz,
    interval_end_at timestamptz,
    observed_at timestamptz,
    price_usd numeric,
    available boolean,
    availability_reason text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
WITH selected AS MATERIALIZED (
    SELECT
        comparison.evaluated_at,
        comparison.comparison_kind,
        comparison.comparison_offset,
        comparison.bin_start_at,
        comparison.bin_end_at,
        comparison.interval_end_at,
        comparison.observed_at,
        comparison.price_usd,
        comparison.available,
        comparison.availability_reason
    FROM pricing.i66_pricing_comparisons AS comparison
    WHERE comparison.start_zone_id = requested_start_zone_id
      AND comparison.end_zone_id = requested_end_zone_id
), diagnostic AS (
    SELECT
        statement_timestamp() AS evaluated_at,
        'current'::text AS comparison_kind,
        0 AS comparison_offset,
        NULL::timestamptz AS bin_start_at,
        NULL::timestamptz AS bin_end_at,
        NULL::timestamptz AS interval_end_at,
        NULL::timestamptz AS observed_at,
        NULL::numeric AS price_usd,
        false AS available,
        'missing_observation'::text AS availability_reason
    WHERE NOT EXISTS (
        SELECT 1 FROM selected WHERE selected.comparison_kind = 'current'
    )
), combined AS (
    SELECT * FROM selected
    UNION ALL
    SELECT * FROM diagnostic
)
SELECT * FROM combined
ORDER BY
    CASE comparison_kind
        WHEN 'current' THEN 0
        WHEN 'prior_cycle' THEN 1
        ELSE 2
    END,
    comparison_offset
$function$;

CREATE FUNCTION oracle.get_i95_i495_pricing_comparisons(
    requested_od_pair_id integer
) RETURNS TABLE (
    evaluated_at timestamptz,
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
WITH selected AS MATERIALIZED (
    SELECT
        comparison.evaluated_at,
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
    FROM pricing.i95_i495_pricing_comparisons AS comparison
    WHERE comparison.od_pair_id = requested_od_pair_id
      AND (comparison.comparison_kind = 'current' OR comparison.available)
), diagnostic AS (
    SELECT
        statement_timestamp() AS evaluated_at,
        'current'::text AS comparison_kind,
        0 AS comparison_offset,
        NULL::timestamptz AS bin_start_at,
        NULL::timestamptz AS bin_end_at,
        NULL::timestamptz AS interval_end_at,
        NULL::timestamptz AS observed_at,
        NULL::numeric AS price_usd,
        false AS available,
        'missing_observation'::text AS availability_reason,
        NULL::text AS source_kind,
        NULL::text AS pricing_method,
        NULL::integer AS od_pair_id,
        NULL::integer AS proxy_od_pair_id,
        NULL::text AS source_status
    WHERE NOT EXISTS (
        SELECT 1 FROM selected WHERE selected.comparison_kind = 'current'
    )
), combined AS (
    SELECT * FROM selected
    UNION ALL
    SELECT * FROM diagnostic
)
SELECT * FROM combined
ORDER BY
    CASE comparison_kind
        WHEN 'current' THEN 0
        WHEN 'prior_cycle' THEN 1
        ELSE 2
    END,
    comparison_offset
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
    requested_direction text,
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
    IF requested_start_zone_id IS NULL
       OR requested_end_zone_id IS NULL
       OR requested_direction NOT IN ('EB', 'WB')
       OR NOT EXISTS (
            SELECT 1
            FROM oracle.route_pricing_component AS component
            WHERE component.facility = 'i66'
              AND component.start_zone_id = requested_start_zone_id
              AND component.end_zone_id = requested_end_zone_id
              AND split_part(component.source_route_key, ':', 1)
                  = requested_direction
       ) THEN
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
            ) AS target_bin_start_at,
            oracle.i66_tolling_active(
                requested_direction,
                resolved.target_at AT TIME ZONE 'America/New_York'
            ) AS tolling_active
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
          AND target.tolling_active
          AND sample.interval_end_at <= requested_evaluated_at
          AND sample.observed_at <= requested_evaluated_at
    ), chosen AS (
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

        UNION ALL

        SELECT
            target.target_date,
            extract(isodow FROM target.target_date)::integer,
            target.target_bin_start_at,
            target.target_bin_start_at + interval '6 minutes',
            target.target_bin_start_at,
            NULL::timestamptz,
            requested_start_zone_id,
            requested_end_zone_id,
            0::numeric,
            false,
            'published_schedule'::text
        FROM targets AS target
        WHERE NOT target.tolling_active
    )
    SELECT
        chosen.sample_date,
        chosen.sample_isodow,
        chosen.bin_start_at,
        chosen.bin_end_at,
        chosen.interval_end_at,
        chosen.observed_at,
        chosen.start_zone_id,
        chosen.end_zone_id,
        chosen.price_usd,
        chosen.uses_modeled,
        chosen.pricing_method
    FROM chosen
    ORDER BY chosen.sample_date;
END
$function$;

-- Kept private for the annual summary, whose zone pair already comes from the
-- canonical route oracle. Agent-facing callers use the explicit-direction form.
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
DECLARE
    canonical_direction text;
BEGIN
    SELECT min(split_part(component.source_route_key, ':', 1))
    INTO canonical_direction
    FROM oracle.route_pricing_component AS component
    WHERE component.facility = 'i66'
      AND component.start_zone_id = requested_start_zone_id
      AND component.end_zone_id = requested_end_zone_id
    HAVING count(DISTINCT split_part(component.source_route_key, ':', 1)) = 1;

    IF canonical_direction IS NULL THEN
        RAISE EXCEPTION 'invalid I-66 ballpark component';
    END IF;

    RETURN QUERY SELECT *
    FROM oracle.get_i66_ballpark_samples(
        requested_start_zone_id,
        requested_end_zone_id,
        canonical_direction,
        requested_local_time,
        requested_dates,
        requested_evaluated_at
    );
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

CREATE FUNCTION oracle.get_annual_ballpark_summary(
    requested_legs jsonb,
    requested_outbound_time time,
    requested_return_time time,
    requested_dates date[],
    requested_fixed_prices jsonb,
    requested_annual_days integer,
    requested_evaluated_at timestamptz
) RETURNS TABLE (
    eligible_date_count integer,
    complete_pair_count integer,
    coverage_percent text,
    coverage_by_weekday jsonb,
    available_start_date date,
    available_end_date date,
    sample_status text,
    uses_modeled boolean,
    uses_current_fixed_rates boolean,
    facility_scenarios jsonb,
    p25_daily_usd numeric,
    p50_daily_usd numeric,
    p90_daily_usd numeric,
    p25_annualized_usd numeric,
    p50_annualized_usd numeric,
    p90_annualized_usd numeric
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    leg_count integer;
    fixed_price_count integer;
    requested_weekday_count integer;
BEGIN
    PERFORM oracle.validate_ballpark_sample_request(
        requested_outbound_time, requested_dates, requested_evaluated_at
    );
    PERFORM oracle.validate_ballpark_sample_request(
        requested_return_time, requested_dates, requested_evaluated_at
    );

    IF requested_legs IS NULL
       OR requested_fixed_prices IS NULL
       OR jsonb_typeof(requested_legs) <> 'array'
       OR jsonb_typeof(requested_fixed_prices) <> 'array' THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;
    leg_count := jsonb_array_length(requested_legs);
    fixed_price_count := jsonb_array_length(requested_fixed_prices);
    SELECT count(DISTINCT extract(isodow FROM requested_date.value))
    INTO requested_weekday_count
    FROM unnest(requested_dates) AS requested_date(value);
    IF leg_count > 24
       OR fixed_price_count > cardinality(requested_dates) * 24
       OR requested_annual_days IS NULL
       OR requested_annual_days NOT BETWEEN 1 AND 366
       OR requested_annual_days > 53 * requested_weekday_count THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(requested_legs) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'object'
           OR item.value->>'direction' IS NULL
           OR item.value->>'facility' IS NULL
           OR item.value->>'route_step_id' IS NULL
           OR item.value->>'direction' NOT IN ('outbound', 'return')
           OR item.value->>'facility' NOT IN ('i66', 'i95_i495', 'greenway', 'dtr')
           OR item.value->>'route_step_id' !~ '^step-[1-9][0-9]*$'
           OR CASE item.value->>'facility'
                WHEN 'i66' THEN
                    NOT item.value ?& ARRAY[
                        'direction', 'facility', 'route_step_id',
                        'start_zone_id', 'end_zone_id'
                    ]
                    OR item.value - ARRAY[
                        'direction', 'facility', 'route_step_id',
                        'start_zone_id', 'end_zone_id'
                    ] <> '{}'::jsonb
                    OR item.value->>'start_zone_id' !~ '^[1-9][0-9]*$'
                    OR item.value->>'end_zone_id' !~ '^[1-9][0-9]*$'
                    OR item.value->>'start_zone_id' IS NULL
                    OR item.value->>'end_zone_id' IS NULL
                WHEN 'i95_i495' THEN
                    NOT item.value ?& ARRAY[
                        'direction', 'facility', 'route_step_id', 'od_pair_id'
                    ]
                    OR item.value - ARRAY[
                        'direction', 'facility', 'route_step_id', 'od_pair_id'
                    ] <> '{}'::jsonb
                    OR item.value->>'od_pair_id' !~ '^[1-9][0-9]*$'
                    OR item.value->>'od_pair_id' IS NULL
                ELSE
                    NOT item.value ?& ARRAY[
                        'direction', 'facility', 'route_step_id'
                    ]
                    OR item.value - ARRAY[
                        'direction', 'facility', 'route_step_id'
                    ] <> '{}'::jsonb
              END
    ) OR (
        SELECT count(DISTINCT concat_ws(
            ':', item.value->>'direction', item.value->>'route_step_id'
        ))
        FROM jsonb_array_elements(requested_legs) AS item(value)
    ) <> leg_count THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(requested_fixed_prices) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'object'
           OR NOT item.value ?& ARRAY[
                'sample_date', 'direction', 'route_step_id', 'price_usd'
              ]
           OR item.value - ARRAY[
                'sample_date', 'direction', 'route_step_id', 'price_usd'
              ] <> '{}'::jsonb
           OR item.value->>'sample_date' IS NULL
           OR item.value->>'direction' IS NULL
           OR item.value->>'route_step_id' IS NULL
           OR item.value->>'price_usd' IS NULL
           OR item.value->>'sample_date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
           OR item.value->>'direction' NOT IN ('outbound', 'return')
           OR item.value->>'route_step_id' !~ '^step-[1-9][0-9]*$'
           OR item.value->>'price_usd' !~ '^[0-9]+([.][0-9]{1,2})?$'
           OR (item.value->>'price_usd')::numeric > 1000.00
           OR (item.value->>'sample_date')::date <> ALL(requested_dates)
           OR NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(requested_legs) AS leg(value)
                WHERE leg.value->>'direction' = item.value->>'direction'
                  AND leg.value->>'route_step_id' = item.value->>'route_step_id'
                  AND leg.value->>'facility' IN ('greenway', 'dtr')
           )
    ) OR (
        SELECT count(DISTINCT concat_ws(
            ':', item.value->>'sample_date', item.value->>'direction',
            item.value->>'route_step_id'
        ))
        FROM jsonb_array_elements(requested_fixed_prices) AS item(value)
    ) <> fixed_price_count THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;

    RETURN QUERY
    WITH legs AS MATERIALIZED (
        SELECT
            item.ordinality::integer AS facility_order,
            item.value->>'direction' AS direction,
            item.value->>'route_step_id' AS route_step_id,
            item.value->>'facility' AS facility,
            CASE WHEN item.value ? 'start_zone_id'
                THEN (item.value->>'start_zone_id')::integer END AS start_zone_id,
            CASE WHEN item.value ? 'end_zone_id'
                THEN (item.value->>'end_zone_id')::integer END AS end_zone_id,
            CASE WHEN item.value ? 'od_pair_id'
                THEN (item.value->>'od_pair_id')::integer END AS od_pair_id
        FROM jsonb_array_elements(requested_legs)
             WITH ORDINALITY AS item(value, ordinality)
    ), eligible_dates AS MATERIALIZED (
        SELECT requested_date.value AS sample_date
        FROM unnest(requested_dates) AS requested_date(value)
    ), i66_prices AS MATERIALIZED (
        SELECT
            sample.sample_date,
            leg.direction,
            leg.route_step_id,
            leg.facility,
            sample.price_usd,
            false AS uses_modeled
        FROM legs AS leg
        CROSS JOIN LATERAL oracle.get_i66_ballpark_samples(
            leg.start_zone_id,
            leg.end_zone_id,
            CASE leg.direction
                WHEN 'outbound' THEN requested_outbound_time
                ELSE requested_return_time
            END,
            requested_dates,
            requested_evaluated_at
        ) AS sample
        WHERE leg.facility = 'i66'
    ), i95_prices AS MATERIALIZED (
        SELECT
            sample.sample_date,
            leg.direction,
            leg.route_step_id,
            leg.facility,
            sample.price_usd,
            sample.uses_modeled
        FROM legs AS leg
        CROSS JOIN LATERAL oracle.get_i95_i495_ballpark_samples(
            leg.od_pair_id,
            CASE leg.direction
                WHEN 'outbound' THEN requested_outbound_time
                ELSE requested_return_time
            END,
            requested_dates,
            requested_evaluated_at
        ) AS sample
        WHERE leg.facility = 'i95_i495'
    ), fixed_prices AS MATERIALIZED (
        SELECT
            (item.value->>'sample_date')::date AS sample_date,
            item.value->>'direction' AS direction,
            item.value->>'route_step_id' AS route_step_id,
            leg.facility,
            (item.value->>'price_usd')::numeric AS price_usd,
            false AS uses_modeled
        FROM jsonb_array_elements(requested_fixed_prices) AS item(value)
        JOIN legs AS leg
          ON leg.direction = item.value->>'direction'
         AND leg.route_step_id = item.value->>'route_step_id'
    ), prices AS MATERIALIZED (
        SELECT * FROM i66_prices
        UNION ALL
        SELECT * FROM i95_prices
        UNION ALL
        SELECT * FROM fixed_prices
    ), complete_dates AS MATERIALIZED (
        SELECT eligible.sample_date
        FROM eligible_dates AS eligible
        WHERE NOT EXISTS (
            SELECT 1
            FROM legs AS leg
            WHERE NOT EXISTS (
                SELECT 1
                FROM prices AS price
                WHERE price.sample_date = eligible.sample_date
                  AND price.direction = leg.direction
                  AND price.route_step_id = leg.route_step_id
            )
        )
    ), facility_daily AS MATERIALIZED (
        SELECT
            complete.sample_date,
            price.facility,
            sum(price.price_usd) AS total_usd,
            bool_or(price.uses_modeled) AS uses_modeled,
            min(leg.facility_order) AS facility_order
        FROM complete_dates AS complete
        JOIN prices AS price USING (sample_date)
        JOIN legs AS leg
          ON leg.direction = price.direction
         AND leg.route_step_id = price.route_step_id
        GROUP BY complete.sample_date, price.facility
    -- Percentiles are not additive: aggregate every facility on the same complete
    -- date first, then rank route totals. Summing facility percentiles is wrong.
    ), route_daily AS MATERIALIZED (
        SELECT
            complete.sample_date,
            coalesce(sum(price.price_usd), 0::numeric) AS total_usd,
            coalesce(bool_or(price.uses_modeled), false) AS uses_modeled,
            coalesce(bool_or(price.facility IN ('greenway', 'dtr')), false)
                AS uses_current_fixed_rates
        FROM complete_dates AS complete
        LEFT JOIN prices AS price USING (sample_date)
        GROUP BY complete.sample_date
    ), facility_statistics AS (
        SELECT
            daily.facility,
            min(daily.facility_order) AS facility_order,
            count(*)::integer AS sample_count,
            bool_or(daily.uses_modeled) AS uses_modeled,
            daily.facility IN ('greenway', 'dtr') AS uses_current_fixed_rates,
            percentile_disc(0.25) WITHIN GROUP (ORDER BY daily.total_usd) AS p25,
            percentile_disc(0.50) WITHIN GROUP (ORDER BY daily.total_usd) AS p50,
            percentile_disc(0.90) WITHIN GROUP (ORDER BY daily.total_usd) AS p90
        FROM facility_daily AS daily
        GROUP BY daily.facility
    ), route_statistics AS (
        SELECT
            count(*)::integer AS sample_count,
            min(daily.sample_date) AS start_date,
            max(daily.sample_date) AS end_date,
            coalesce(bool_or(daily.uses_modeled), false) AS uses_modeled,
            coalesce(bool_or(daily.uses_current_fixed_rates), false)
                AS uses_current_fixed_rates,
            percentile_disc(0.25) WITHIN GROUP (ORDER BY daily.total_usd) AS p25,
            percentile_disc(0.50) WITHIN GROUP (ORDER BY daily.total_usd) AS p50,
            percentile_disc(0.90) WITHIN GROUP (ORDER BY daily.total_usd) AS p90
        FROM route_daily AS daily
    ), weekday_statistics AS (
        SELECT
            extract(isodow FROM eligible.sample_date)::integer AS sample_isodow,
            count(*)::integer AS eligible_count,
            count(complete.sample_date)::integer AS complete_count
        FROM eligible_dates AS eligible
        LEFT JOIN complete_dates AS complete USING (sample_date)
        GROUP BY extract(isodow FROM eligible.sample_date)
    )
    SELECT
        cardinality(requested_dates),
        route.sample_count,
        to_char(
            round(route.sample_count::numeric * 100 / cardinality(requested_dates), 1),
            'FM990.0'
        ),
        coalesce((
            SELECT jsonb_agg(jsonb_build_object(
                'sample_isodow', weekday.sample_isodow,
                'eligible_date_count', weekday.eligible_count,
                'complete_pair_count', weekday.complete_count,
                'coverage_percent', to_char(
                    round(
                        weekday.complete_count::numeric * 100
                        / weekday.eligible_count,
                        1
                    ),
                    'FM990.0'
                )
            ) ORDER BY weekday.sample_isodow)
            FROM weekday_statistics AS weekday
        ), '[]'::jsonb),
        route.start_date,
        route.end_date,
        CASE WHEN route.sample_count = cardinality(requested_dates)
            THEN 'complete' ELSE 'partial' END,
        route.uses_modeled,
        route.uses_current_fixed_rates,
        coalesce((
            SELECT jsonb_agg(jsonb_build_object(
                'facility', facility.facility,
                'sample_count', facility.sample_count,
                'uses_modeled', facility.uses_modeled,
                'uses_current_fixed_rates', facility.uses_current_fixed_rates,
                'scenarios', jsonb_build_object(
                    'p25', jsonb_build_object(
                        'daily_round_trip_usd', to_char(round(facility.p25, 2), 'FM999999990.00'),
                        'annualized_usd', to_char(round(facility.p25 * requested_annual_days, 2), 'FM999999990.00')
                    ),
                    'p50', jsonb_build_object(
                        'daily_round_trip_usd', to_char(round(facility.p50, 2), 'FM999999990.00'),
                        'annualized_usd', to_char(round(facility.p50 * requested_annual_days, 2), 'FM999999990.00')
                    ),
                    'p90', jsonb_build_object(
                        'daily_round_trip_usd', to_char(round(facility.p90, 2), 'FM999999990.00'),
                        'annualized_usd', to_char(round(facility.p90 * requested_annual_days, 2), 'FM999999990.00')
                    )
                )
            ) ORDER BY facility.facility_order)
            FROM facility_statistics AS facility
        ), '[]'::jsonb),
        round(route.p25, 2),
        round(route.p50, 2),
        round(route.p90, 2),
        round(route.p25 * requested_annual_days, 2),
        round(route.p50 * requested_annual_days, 2),
        round(route.p90 * requested_annual_days, 2)
    FROM route_statistics AS route;
END
$function$;

REVOKE ALL ON ALL TABLES IN SCHEMA oracle FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA oracle FROM PUBLIC;
REVOKE ALL ON TYPE oracle.geometry, oracle.geography FROM PUBLIC;
GRANT USAGE ON TYPE oracle.geometry, oracle.geography TO oracle_owner;
GRANT EXECUTE ON FUNCTION oracle.ST_Distance(
    oracle.geography, oracle.geography, boolean
) TO oracle_owner;
GRANT EXECUTE ON FUNCTION oracle.ST_AsGeoJSON(
    oracle.geography, integer, integer
) TO oracle_owner;
GRANT SELECT ON oracle.spatial_ref_sys TO oracle_owner;

GRANT USAGE ON SCHEMA pricing TO oracle_owner;
GRANT SELECT ON pricing.current_i95_direction,
    pricing.i66_pricing_comparisons,
    pricing.i95_i495_pricing_comparisons,
    pricing.i66_ballpark_samples,
    pricing.i95_i495_ballpark_samples TO oracle_owner;
GRANT USAGE ON SCHEMA oracle TO tollchat_agent, pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_toll_route_prompt_points()
TO tollchat_agent;
GRANT EXECUTE ON FUNCTION oracle.validate_toll_route(text, text)
TO tollchat_agent;
GRANT EXECUTE ON FUNCTION oracle.validate_pricing_route(text, text)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i66_pricing_comparisons(integer, integer, text)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i66_pricing_comparisons(integer, integer)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i95_i495_pricing_comparisons(integer)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.validate_ballpark_route(text, text)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_priced_route_distance_miles(jsonb)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, text, time, date[], timestamptz
) TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i95_i495_ballpark_samples(
    integer, time, date[], timestamptz
) TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_annual_ballpark_summary(
    jsonb, time, time, date[], jsonb, integer, timestamptz
) TO pricing_caller;

ALTER TABLE oracle.schema_version OWNER TO oracle_owner;
ALTER TABLE oracle.toll_route_point OWNER TO oracle_owner;
ALTER TABLE oracle.toll_connection OWNER TO oracle_owner;
ALTER VIEW oracle.route_pricing_component OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_toll_route_prompt_points() OWNER TO oracle_owner;
ALTER FUNCTION oracle.ramp_alternatives(text, text, boolean) OWNER TO oracle_owner;
ALTER FUNCTION oracle.resolve_toll_route_internal(text, text, boolean)
OWNER TO oracle_owner;
ALTER FUNCTION oracle.resolve_toll_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.route_pricing_legs(text[], text[]) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_toll_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_pricing_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_ballpark_route(text, text) OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_priced_route_distance_miles(jsonb) OWNER TO oracle_owner;
ALTER FUNCTION oracle.i66_tolling_active(text, timestamp) OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i66_pricing_comparisons(integer, integer, text)
OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i66_pricing_comparisons(integer, integer)
OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i95_i495_pricing_comparisons(integer)
OWNER TO oracle_owner;
ALTER FUNCTION oracle.validate_ballpark_sample_request(time, date[], timestamptz)
OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, text, time, date[], timestamptz
) OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, time, date[], timestamptz
) OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_i95_i495_ballpark_samples(
    integer, time, date[], timestamptz
) OWNER TO oracle_owner;
ALTER FUNCTION oracle.get_annual_ballpark_summary(
    jsonb, time, time, date[], jsonb, integer, timestamptz
) OWNER TO oracle_owner;
ALTER SCHEMA oracle OWNER TO oracle_owner;

COMMIT;

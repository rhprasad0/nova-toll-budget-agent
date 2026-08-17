-- Correct I-95 direction metadata on mixed junction routes and restore DCA access.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
    changed_rows integer;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.0.1', '1.0.2') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.0.1 or 1.0.2, got %',
            current_version;
    END IF;

    UPDATE oracle.toll_route_point AS point
    SET direction = CASE
        WHEN point.source_metadata->'source_node'->>'path' LIKE '%North'
            THEN 'NB'
        WHEN point.source_metadata->'source_node'->>'path' LIKE '%South'
            THEN 'SB'
        ELSE CASE point.source_metadata->'source_node'->>'direction'
            WHEN 'Northbound' THEN 'NB'
            WHEN 'Southbound' THEN 'SB'
        END
    END
    WHERE point.network_id IN ('i95', 'i495');

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 107 THEN
        RAISE EXCEPTION 'expected 107 I-95/I-495 point direction updates, got %',
            changed_rows;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM oracle.toll_route_point AS point
        WHERE point.network_id IN ('i95', 'i495')
          AND (
              (point.source_metadata->'source_node'->>'path' LIKE '%North'
               AND point.direction <> 'NB')
              OR
              (point.source_metadata->'source_node'->>'path' LIKE '%South'
               AND point.direction <> 'SB')
          )
    ) THEN
        RAISE EXCEPTION 'I-95/I-495 point directions conflict with their paths';
    END IF;

    UPDATE oracle.toll_connection AS connection
    SET source_metadata = jsonb_set(
        connection.source_metadata,
        '{general_purpose_fallback,i95_direction}',
        to_jsonb(
            CASE
                WHEN i95_point.source_metadata->'source_node'->>'path'
                     LIKE '%North' THEN 'NB'
                WHEN i95_point.source_metadata->'source_node'->>'path'
                     LIKE '%South' THEN 'SB'
                ELSE i95_point.direction
            END
        )
    )
    FROM oracle.toll_route_point AS from_point
    JOIN oracle.toll_route_point AS to_point ON true
    JOIN LATERAL (
        SELECT point.*
        FROM oracle.toll_route_point AS point
        WHERE point.point_id = CASE
            WHEN from_point.network_id = 'i95'
                THEN from_point.point_id
            ELSE to_point.point_id
        END
    ) AS i95_point ON true
    WHERE connection.connection_type = 'general_purpose_gap'
      AND from_point.point_id = connection.from_point_id
      AND to_point.point_id = connection.to_point_id;

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 300 THEN
        RAISE EXCEPTION 'expected 300 I-95/I-495 direction updates, got %',
            changed_rows;
    END IF;

    IF (
        SELECT source_metadata->'general_purpose_fallback'->>'i95_direction'
        FROM oracle.toll_connection
        WHERE connection_id = 'source:i95_shared:Southbound:182SO:2239ND'
    ) IS DISTINCT FROM 'NB' THEN
        RAISE EXCEPTION 'Route 267-to-Pentagon route is not northbound on I-95';
    END IF;

    INSERT INTO oracle.toll_connection (
        connection_id, from_point_id, to_point_id, connection_type,
        required_i95_direction, source_route_key, source_metadata
    ) VALUES (
        'i95_north_to_dca_from_i495_south',
        'i95:2239ND',
        'airport_dca',
        'airport_access',
        'NB',
        NULL,
        jsonb_build_object(
            'basis', 'v2/docs/oracle-spec.md',
            'curated', true
        )
    )
    ON CONFLICT (connection_id) DO NOTHING;

    IF NOT EXISTS (
        SELECT 1
        FROM oracle.toll_connection
        WHERE connection_id = 'i95_north_to_dca_from_i495_south'
          AND from_point_id = 'i95:2239ND'
          AND to_point_id = 'airport_dca'
          AND connection_type = 'airport_access'
          AND required_i95_direction = 'NB'
          AND source_route_key IS NULL
          AND source_metadata = jsonb_build_object(
              'basis', 'v2/docs/oracle-spec.md',
              'curated', true
          )
    ) THEN
        RAISE EXCEPTION 'mixed I-495/I-95 DCA access conflicts with oracle 1.0.2';
    END IF;

    IF current_version = '1.0.1' THEN
        UPDATE oracle.schema_version
        SET version = '1.0.2', installed_at = clock_timestamp()
        WHERE singleton AND version = '1.0.1';

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 1 THEN
            RAISE EXCEPTION 'expected one oracle schema version update, got %',
                changed_rows;
        END IF;
    END IF;
END
$migration$;

COMMIT;

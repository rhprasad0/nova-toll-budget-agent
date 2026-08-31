\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
    pricing_version text;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;
    SELECT version INTO STRICT pricing_version
    FROM pricing.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.13.1', '1.14.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.13.1 or 1.14.0, got %',
            current_version;
    END IF;
    IF pricing_version <> '1.3.0' THEN
        RAISE EXCEPTION 'oracle 1.14.0 requires pricing 1.3.0';
    END IF;

    IF current_version = '1.13.1' THEN
        IF (SELECT count(*) FROM oracle.toll_connection) <> 995
           OR (SELECT count(*) FROM oracle.toll_connection
               WHERE connection_type = 'toll_handoff') <> 13
           OR EXISTS (
               SELECT 1 FROM oracle.toll_connection
               WHERE connection_id = 'i495_1829_to_dulles_toll_road'
           ) THEN
            RAISE EXCEPTION 'oracle 1.13.1 source state is incompatible';
        END IF;

        INSERT INTO oracle.toll_connection (
            connection_id, from_point_id, to_point_id, connection_type,
            required_i95_direction, source_route_key, source_metadata
        ) VALUES (
            'i495_1829_to_dulles_toll_road',
            'i495:1829ND',
            'dtr:1819:entry:WB',
            'toll_handoff',
            NULL,
            NULL,
            '{"basis":"v2/db/oracle/CONTRACT.md","curated":true}'::jsonb
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM oracle.toll_connection
        WHERE connection_id = 'i495_1829_to_dulles_toll_road'
          AND from_point_id = 'i495:1829ND'
          AND to_point_id = 'dtr:1819:entry:WB'
          AND connection_type = 'toll_handoff'
          AND required_i95_direction IS NULL
          AND source_route_key IS NULL
          AND source_metadata = '{"basis":"v2/db/oracle/CONTRACT.md","curated":true}'::jsonb
    ) OR (SELECT count(*) FROM oracle.toll_connection) <> 996
      OR (SELECT count(*) FROM oracle.toll_connection
          WHERE connection_type = 'toll_handoff') <> 14 THEN
        RAISE EXCEPTION 'oracle 1.14.0 handoff did not install cleanly';
    END IF;

    IF current_version = '1.13.1' THEN
        UPDATE oracle.schema_version
        SET version = '1.14.0', installed_at = statement_timestamp()
        WHERE singleton AND version = '1.13.1';
    END IF;
END
$migration$;

COMMIT;

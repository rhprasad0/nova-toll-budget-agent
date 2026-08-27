-- Replace retired documentation provenance with the canonical generator path.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
    changed_points integer;
    changed_connections integer;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.13.0', '1.13.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.13.0 or 1.13.1, got %',
            current_version;
    END IF;
    IF (SELECT version FROM pricing.schema_version WHERE singleton)
       IS DISTINCT FROM '1.3.0' THEN
        RAISE EXCEPTION 'oracle 1.13.1 requires pricing 1.3.0';
    END IF;

    IF current_version = '1.13.0' THEN
        UPDATE oracle.toll_route_point
        SET source_metadata = replace(
            source_metadata::text,
            '"v2/docs/oracle-spec.md"',
            '"v2/db/oracle/CONTRACT.md"'
        )::jsonb
        WHERE source_metadata::text LIKE '%"v2/docs/oracle-spec.md"%';
        GET DIAGNOSTICS changed_points = ROW_COUNT;

        UPDATE oracle.toll_connection
        SET source_metadata = replace(
            source_metadata::text,
            '"v2/docs/oracle-spec.md"',
            '"v2/db/oracle/CONTRACT.md"'
        )::jsonb
        WHERE source_metadata::text LIKE '%"v2/docs/oracle-spec.md"%';
        GET DIAGNOSTICS changed_connections = ROW_COUNT;

        IF changed_points <> 6 OR changed_connections <> 25 THEN
            RAISE EXCEPTION
                'expected 6 point and 25 connection provenance updates, got % and %',
                changed_points, changed_connections;
        END IF;

        UPDATE oracle.schema_version
        SET version = '1.13.1', installed_at = statement_timestamp()
        WHERE singleton AND version = '1.13.0';
    END IF;

    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.13.1'
       OR (SELECT count(*) FROM oracle.toll_route_point
           WHERE source_metadata::text LIKE
               '%"v2/db/oracle/CONTRACT.md"%') <> 6
       OR (SELECT count(*) FROM oracle.toll_connection
           WHERE source_metadata::text LIKE
               '%"v2/db/oracle/CONTRACT.md"%') <> 25
       OR EXISTS (
           SELECT 1 FROM oracle.toll_route_point
           WHERE source_metadata::text LIKE '%v2/docs/oracle-spec.md%'
       )
       OR EXISTS (
           SELECT 1 FROM oracle.toll_connection
           WHERE source_metadata::text LIKE '%v2/docs/oracle-spec.md%'
       ) THEN
        RAISE EXCEPTION 'oracle 1.13.1 provenance did not install cleanly';
    END IF;
END
$migration$;

COMMIT;

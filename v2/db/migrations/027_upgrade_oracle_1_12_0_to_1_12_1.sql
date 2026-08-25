-- Record the oracle contract after legacy public pricing retirement.

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

    IF current_version NOT IN ('1.12.0', '1.12.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.12.0 or 1.12.1, got %',
            current_version;
    END IF;
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0' THEN
        RAISE EXCEPTION 'oracle 1.12.1 requires pricing 1.3.0';
    END IF;
END
$migration$;

UPDATE oracle.schema_version
SET version = '1.12.1', installed_at = statement_timestamp()
WHERE singleton AND version = '1.12.0';

DO $postcheck$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.12.1' THEN
        RAISE EXCEPTION 'oracle schema did not advance cleanly to 1.12.1';
    END IF;
END
$postcheck$;

COMMIT;

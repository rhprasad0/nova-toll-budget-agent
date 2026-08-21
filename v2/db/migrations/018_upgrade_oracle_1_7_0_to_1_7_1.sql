-- Synchronize the Oracle schema version with its corrected normative contract.

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

    IF current_version NOT IN ('1.7.0', '1.7.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.7.0 or 1.7.1, got %',
            current_version;
    END IF;
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.2.0'
       OR to_regprocedure(
           'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)'
       ) IS NULL THEN
        RAISE EXCEPTION 'oracle 1.7.1 requires the oracle 1.7.0 contract and pricing 1.2.0';
    END IF;
END
$migration$;

UPDATE oracle.schema_version
SET version = '1.7.1', installed_at = clock_timestamp()
WHERE singleton AND version = '1.7.0';

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.7.1' THEN
        RAISE EXCEPTION 'oracle 1.7.1 contract is not installed';
    END IF;
END
$migration$;

COMMIT;

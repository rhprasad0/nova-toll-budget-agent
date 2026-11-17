\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));
SET LOCAL ROLE oracle_owner;

DO $migration$
DECLARE current_version text;
BEGIN
    SELECT version INTO STRICT current_version FROM oracle.schema_version WHERE singleton;
    IF current_version NOT IN ('1.15.2', '1.16.0') THEN
        RAISE EXCEPTION 'expected oracle 1.15.2 or 1.16.0, got %', current_version;
    END IF;
END
$migration$;
DROP FUNCTION IF EXISTS oracle.get_agent_report_routes();
DROP FUNCTION IF EXISTS oracle.get_i95_i495_report_inputs();
DO $migration$
BEGIN
    IF to_regrole('report_publisher') IS NOT NULL THEN
        REVOKE ALL ON SCHEMA oracle FROM report_publisher;
        IF has_schema_privilege('report_publisher', 'oracle', 'USAGE')
           OR has_schema_privilege('report_publisher', 'oracle', 'CREATE') THEN
            RAISE EXCEPTION 'retired report publisher keeps Oracle schema access';
        END IF;
    END IF;
    IF to_regprocedure('oracle.get_agent_report_routes()') IS NOT NULL
       OR to_regprocedure('oracle.get_i95_i495_report_inputs()') IS NOT NULL THEN
        RAISE EXCEPTION 'retired report functions remain installed';
    END IF;
END
$migration$;
UPDATE oracle.schema_version SET version = '1.16.0' WHERE singleton AND version = '1.15.2';
COMMIT;

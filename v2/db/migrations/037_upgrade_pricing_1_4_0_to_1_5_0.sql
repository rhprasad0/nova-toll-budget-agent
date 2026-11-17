\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-pricing-schema-version'));
DO $migration$
DECLARE current_version text;
BEGIN
    SELECT version INTO STRICT current_version FROM pricing.schema_version WHERE singleton;
    IF current_version NOT IN ('1.4.0', '1.5.0') THEN
        RAISE EXCEPTION 'expected pricing 1.4.0 or 1.5.0, got %', current_version;
    END IF;
END
$migration$;
DROP TABLE IF EXISTS pricing.evaluation_runs;
DO $migration$
BEGIN
    IF to_regrole('eval_writer') IS NOT NULL THEN
        REVOKE ALL ON SCHEMA pricing FROM eval_writer;
        IF has_schema_privilege('eval_writer', 'pricing', 'USAGE')
           OR has_schema_privilege('eval_writer', 'pricing', 'CREATE') THEN
            RAISE EXCEPTION 'retired evaluation writer keeps pricing schema access';
        END IF;
    END IF;
    IF to_regclass('pricing.evaluation_runs') IS NOT NULL THEN
        RAISE EXCEPTION 'retired evaluation history remains installed';
    END IF;
END
$migration$;
UPDATE pricing.schema_version SET version = '1.5.0', installed_at = now()
WHERE singleton AND version = '1.4.0';
COMMIT;

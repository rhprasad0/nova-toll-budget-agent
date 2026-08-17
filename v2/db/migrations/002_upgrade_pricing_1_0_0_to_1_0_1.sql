-- Guarded, rerunnable metadata upgrade for the pricing 1.0.1 release.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-pricing-schema-version'));

DO $migration$
DECLARE
    current_version text;
    changed_rows integer;
BEGIN
    SELECT version INTO STRICT current_version
    FROM pricing.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.0.0', '1.0.1') THEN
        RAISE EXCEPTION 'expected pricing schema version 1.0.0 or 1.0.1, got %',
            current_version;
    END IF;

    IF to_regclass('pricing.trip_pricing_i95') IS NULL
       OR to_regclass('pricing.trip_pricing_i66') IS NULL
       OR NOT has_schema_privilege('pricing_loader_writer', 'pricing', 'USAGE')
       OR NOT has_table_privilege(
            'pricing_loader_writer',
            'pricing.trip_pricing_i95',
            'SELECT,INSERT,UPDATE'
       )
       OR NOT has_table_privilege(
            'pricing_loader_writer',
            'pricing.trip_pricing_i66',
            'SELECT,INSERT,UPDATE'
       ) THEN
        RAISE EXCEPTION 'pricing schema prerequisites are not ready';
    END IF;

    IF current_version = '1.0.0' THEN
        UPDATE pricing.schema_version
        SET version = '1.0.1', installed_at = clock_timestamp()
        WHERE singleton AND version = '1.0.0';

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 1 THEN
            RAISE EXCEPTION 'expected one pricing schema version update, got %',
                changed_rows;
        END IF;
    END IF;
END
$migration$;

COMMIT;

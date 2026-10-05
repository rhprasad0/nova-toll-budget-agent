-- Read-only Oracle catalog access for the fixed development pricing reader.
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
    IF current_version NOT IN ('1.15.1', '1.15.2') THEN
        RAISE EXCEPTION 'expected oracle 1.15.1 or 1.15.2, got %', current_version;
    END IF;
    IF current_database() = 'nova_toll_development' THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_roles WHERE rolname = 'pricing_reader_development'
              AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
              AND NOT rolreplication AND NOT rolbypassrls
        ) OR pg_get_userbyid((SELECT nspowner FROM pg_namespace WHERE nspname = 'oracle'))
              <> 'oracle_owner_development' THEN
            RAISE EXCEPTION 'development catalog reader or Oracle owner is incompatible';
        END IF;
        GRANT USAGE ON SCHEMA oracle TO pricing_reader_development;
        GRANT SELECT ON oracle.schema_version, oracle.toll_route_point,
            oracle.toll_connection, oracle.route_pricing_component
        TO pricing_reader_development;
        IF has_schema_privilege('pricing_reader_development', 'oracle', 'CREATE')
           OR EXISTS (
               SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'oracle' AND c.relkind IN ('r', 'v', 'm', 'p')
                 AND has_table_privilege('pricing_reader_development', c.oid,
                     'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
           ) THEN
            RAISE EXCEPTION 'development catalog reader must remain read-only';
        END IF;
    END IF;
END
$migration$;
UPDATE oracle.schema_version SET version = '1.15.2' WHERE singleton AND version = '1.15.1';
COMMIT;

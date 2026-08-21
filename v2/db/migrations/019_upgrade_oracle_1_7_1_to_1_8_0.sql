-- Separate agent-facing route validation from internal pricing calls.

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

    IF current_version NOT IN ('1.7.1', '1.8.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.7.1 or 1.8.0, got %',
            current_version;
    END IF;
    IF to_regrole('rds_iam') IS NULL
       OR to_regrole('tollchat_agent') IS NULL
       OR to_regprocedure('oracle.validate_toll_route(text,text)') IS NULL
       OR to_regprocedure('oracle.validate_pricing_route(text,text)') IS NULL
       OR to_regprocedure('oracle.validate_pricing_route(text[],text[])') IS NOT NULL
       OR to_regprocedure(
           'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)'
       ) IS NULL THEN
        RAISE EXCEPTION 'oracle 1.8.0 requires the oracle 1.7.1 contract';
    END IF;
END
$migration$;

DO $migration$
BEGIN
    CREATE ROLE pricing_caller LOGIN;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$migration$;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname = 'pricing_caller'
          AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
               OR rolreplication OR rolbypassrls)
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        WHERE member_role.rolname = 'pricing_caller'
          AND granted_role.rolname <> 'rds_iam'
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_database AS database,
             LATERAL aclexplode(database.datacl) AS privilege
        WHERE database.datname = current_database()
          AND privilege.grantee = to_regrole('pricing_caller')
          AND privilege.privilege_type IN ('CREATE', 'TEMPORARY')
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace,
             LATERAL aclexplode(namespace.nspacl) AS privilege
        WHERE privilege.grantee = to_regrole('pricing_caller')
          AND (
              (SELECT version FROM oracle.schema_version WHERE singleton) = '1.7.1'
              OR namespace.nspname <> 'oracle'
              OR privilege.privilege_type <> 'USAGE'
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation,
             LATERAL aclexplode(relation.relacl) AS privilege
        WHERE privilege.grantee = to_regrole('pricing_caller')
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS attribute,
             LATERAL aclexplode(attribute.attacl) AS privilege
        WHERE privilege.grantee = to_regrole('pricing_caller')
    ) THEN
        RAISE EXCEPTION 'pricing_caller is not a scoped LOGIN role';
    END IF;
END
$migration$;

GRANT rds_iam TO pricing_caller;
GRANT USAGE ON SCHEMA oracle TO pricing_caller;

REVOKE EXECUTE ON FUNCTION oracle.validate_pricing_route(text, text)
FROM tollchat_agent;
REVOKE EXECUTE ON FUNCTION oracle.get_i66_pricing_comparisons(integer, integer)
FROM tollchat_agent;
REVOKE EXECUTE ON FUNCTION oracle.get_i95_i495_pricing_comparisons(integer)
FROM tollchat_agent;
REVOKE EXECUTE ON FUNCTION oracle.validate_ballpark_route(text, text)
FROM tollchat_agent;
REVOKE EXECUTE ON FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, time, date[], timestamptz
) FROM tollchat_agent;
REVOKE EXECUTE ON FUNCTION oracle.get_i95_i495_ballpark_samples(
    integer, time, date[], timestamptz
) FROM tollchat_agent;
REVOKE EXECUTE ON FUNCTION oracle.get_annual_ballpark_summary(
    jsonb, time, time, date[], jsonb, integer, timestamptz
) FROM tollchat_agent;

GRANT EXECUTE ON FUNCTION oracle.validate_pricing_route(text, text)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i66_pricing_comparisons(integer, integer)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i95_i495_pricing_comparisons(integer)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.validate_ballpark_route(text, text)
TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i66_ballpark_samples(
    integer, integer, time, date[], timestamptz
) TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_i95_i495_ballpark_samples(
    integer, time, date[], timestamptz
) TO pricing_caller;
GRANT EXECUTE ON FUNCTION oracle.get_annual_ballpark_summary(
    jsonb, time, time, date[], jsonb, integer, timestamptz
) TO pricing_caller;

UPDATE oracle.schema_version
SET version = '1.8.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.7.1';

DO $migration$
DECLARE
    agent_executable_count integer;
    pricing_executable_count integer;
BEGIN
    SELECT count(*) INTO agent_executable_count
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND has_function_privilege('tollchat_agent', procedure.oid, 'EXECUTE');
    SELECT count(*) INTO pricing_executable_count
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND has_function_privilege('pricing_caller', procedure.oid, 'EXECUTE');

    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.8.0'
       OR agent_executable_count <> 1
       OR pricing_executable_count <> 7
       OR NOT has_function_privilege(
           'tollchat_agent', 'oracle.validate_toll_route(text,text)', 'EXECUTE'
       )
       OR has_function_privilege(
           'pricing_caller', 'oracle.validate_toll_route(text,text)', 'EXECUTE'
       )
       OR has_schema_privilege('pricing_caller', 'pricing', 'USAGE')
       OR has_schema_privilege('tollchat_agent', 'pricing', 'USAGE')
       OR NOT has_schema_privilege('pricing_caller', 'oracle', 'USAGE')
       OR has_schema_privilege('pricing_caller', 'oracle', 'CREATE')
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace,
                LATERAL aclexplode(namespace.nspacl) AS privilege
           WHERE privilege.grantee = to_regrole('pricing_caller')
             AND (
                 namespace.nspname <> 'oracle'
                 OR privilege.privilege_type <> 'USAGE'
             )
       )
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname IN ('oracle', 'pricing')
             AND (
                 has_table_privilege(
                     'tollchat_agent', relation.oid,
                     'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                 )
                 OR has_table_privilege(
                     'pricing_caller', relation.oid,
                     'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                 )
             )
       ) THEN
        RAISE EXCEPTION 'oracle 1.8.0 role separation is not installed';
    END IF;
END
$migration$;

COMMIT;

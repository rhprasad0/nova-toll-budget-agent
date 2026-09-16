-- Run once through the verified production administrator connection, before 033.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $$ BEGIN
  IF current_database() <> 'nova_toll'
     OR current_user <> 'nova_toll_admin'
     OR session_user <> 'nova_toll_admin'
     OR shobj_description((SELECT oid FROM pg_database
                          WHERE datname = current_database()), 'pg_database')
        IS DISTINCT FROM 'environment=production' THEN
    RAISE EXCEPTION 'wrong evaluation writer bootstrap identity';
  END IF;
  IF to_regrole('eval_writer') IS NOT NULL THEN
    RAISE EXCEPTION 'evaluation writer already exists; inspect before proceeding';
  END IF;
END $$;

CREATE ROLE eval_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;
COMMENT ON ROLE eval_writer IS 'environment=production';
GRANT rds_iam TO eval_writer;
GRANT CONNECT ON DATABASE nova_toll TO eval_writer;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'eval_writer'
      AND rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      AND shobj_description(oid, 'pg_authid') = 'environment=production'
      AND has_database_privilege(oid, 'nova_toll', 'CONNECT')
  ) OR (SELECT count(*) FROM pg_auth_members
        WHERE member = to_regrole('eval_writer')) <> 1
    OR NOT EXISTS (
      SELECT 1 FROM pg_auth_members
      WHERE member = to_regrole('eval_writer') AND roleid = to_regrole('rds_iam')
        AND NOT admin_option
    ) THEN
    RAISE EXCEPTION 'evaluation writer bootstrap postcondition failed';
  END IF;
END $$;
COMMIT;

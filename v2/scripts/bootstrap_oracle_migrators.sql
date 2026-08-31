-- One-time, administrator-run bootstrap for the two IAM migration logins.
-- This is intentionally separate from the recurring deploy_oracle_migration.py runner.
\set ON_ERROR_STOP on
DO $$ BEGIN CREATE ROLE oracle_migrator_development LOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE oracle_migrator LOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- The fixed statements make privilege review intentionally obvious and idempotent.
GRANT rds_iam TO oracle_migrator_development, oracle_migrator;
GRANT oracle_owner_development TO oracle_migrator_development;
GRANT oracle_owner TO oracle_migrator;
GRANT CONNECT ON DATABASE nova_toll_development TO oracle_migrator_development;
GRANT CONNECT ON DATABASE nova_toll TO oracle_migrator;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname IN ('oracle_migrator_development', 'oracle_migrator')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR NOT pg_has_role('oracle_migrator_development', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('oracle_migrator', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('oracle_migrator_development', 'oracle_owner_development', 'MEMBER')
    OR NOT pg_has_role('oracle_migrator', 'oracle_owner', 'MEMBER')
    OR has_database_privilege('oracle_migrator_development', 'nova_toll', 'CONNECT')
    OR has_database_privilege('oracle_migrator', 'nova_toll_development', 'CONNECT')
    OR EXISTS (
      SELECT 1 FROM pg_auth_members membership
      JOIN pg_roles member ON member.oid = membership.member
      JOIN pg_roles granted ON granted.oid = membership.roleid
      WHERE (member.rolname = 'oracle_migrator_development'
             AND granted.rolname NOT IN ('rds_iam', 'oracle_owner_development'))
         OR (member.rolname = 'oracle_migrator'
             AND granted.rolname NOT IN ('rds_iam', 'oracle_owner'))
    ) OR EXISTS (
      SELECT 1 FROM pg_class relation, LATERAL aclexplode(relation.relacl) privilege
      WHERE privilege.grantee IN (to_regrole('oracle_migrator_development'), to_regrole('oracle_migrator'))
    ) OR EXISTS (
      SELECT 1 FROM pg_namespace namespace, LATERAL aclexplode(namespace.nspacl) privilege
      WHERE privilege.grantee IN (to_regrole('oracle_migrator_development'), to_regrole('oracle_migrator'))
    ) THEN
    RAISE EXCEPTION 'Oracle migrator roles are not isolated';
  END IF;
END $$;

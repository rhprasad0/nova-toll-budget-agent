\set ON_ERROR_STOP on

\if :{?fresh_development}
DO $$
DECLARE
  development_roles text[] := ARRAY[
    'pricing_loader_writer_development', 'pricing_reader_development',
    'oracle_owner_development', 'tollchat_agent_development',
    'pricing_caller_development', 'report_publisher_development'
  ];
BEGIN
  IF current_database() <> 'nova_toll_development'
     OR (SELECT count(*) FROM pg_roles WHERE rolname = ANY (development_roles)) <> 6 THEN
    RAISE EXCEPTION 'fresh development identity is wrong';
  END IF;
  IF (SELECT description FROM pg_shdescription
      WHERE objoid = (SELECT oid FROM pg_database WHERE datname = current_database()))
       IS DISTINCT FROM 'environment=development'
     OR EXISTS (
       SELECT 1 FROM pg_roles
       WHERE rolname = ANY (development_roles)
         AND shobj_description(oid, 'pg_authid') IS DISTINCT FROM 'environment=development'
     ) THEN
    RAISE EXCEPTION 'fresh development environment comments are wrong';
  END IF;
  IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0'
     OR (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.14.0'
     OR (SELECT count(*) FROM oracle.toll_route_point) <> 220
     OR (SELECT count(*) FROM oracle.toll_connection) <> 996 THEN
    RAISE EXCEPTION 'fresh development bootstrap data/version contract is wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = current_database()
      AND privilege.grantee = 0 AND privilege.privilege_type = 'CONNECT'
  ) OR EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = current_database()
      AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee NOT IN (0, database.datdba)
      AND privilege.grantee NOT IN (SELECT oid FROM pg_roles WHERE rolname = ANY (development_roles))
  ) THEN
    RAISE EXCEPTION 'fresh development database CONNECT grants are wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner_development'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer_development', 'pricing_reader_development',
      'tollchat_agent_development', 'pricing_caller_development', 'report_publisher_development')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'fresh development role attributes are wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE member_role.rolname IN ('pricing_loader_writer_development', 'pricing_reader_development',
      'tollchat_agent_development', 'pricing_caller_development', 'report_publisher_development')
      AND granted_role.rolname <> 'rds_iam'
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members membership JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'oracle_owner_development'
  ) OR EXISTS (
    SELECT 1 FROM pg_roles role
    WHERE role.rolname IN ('pricing_loader_writer_development', 'pricing_reader_development',
      'tollchat_agent_development', 'pricing_caller_development', 'report_publisher_development')
      AND NOT pg_has_role(role.rolname, 'rds_iam', 'MEMBER')
  ) THEN
    RAISE EXCEPTION 'fresh development role membership is wrong';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_foreign_server)
     OR EXISTS (SELECT 1 FROM pg_user_mappings)
     OR EXISTS (SELECT 1 FROM pg_extension
                WHERE extname IN ('dblink', 'postgres_fdw', 'pg_cron') OR extname LIKE 'postgis_%') THEN
    RAISE EXCEPTION 'fresh development integration boundary is wrong';
  END IF;
  IF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'oracle')
       <> 'oracle_owner_development'
     OR (SELECT pg_get_userbyid(relowner) FROM pg_class
         WHERE oid = 'oracle.toll_route_point'::regclass) <> 'oracle_owner_development'
     OR NOT has_schema_privilege('pricing_loader_writer_development', 'pricing', 'USAGE')
     OR NOT has_schema_privilege('pricing_reader_development', 'pricing', 'USAGE')
     OR NOT has_function_privilege('tollchat_agent_development',
         'oracle.validate_toll_route(text,text)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
         'oracle.get_i95_i495_pricing_comparisons(integer)', 'EXECUTE')
     OR NOT has_function_privilege('report_publisher_development',
         'oracle.get_i95_i495_report_inputs()', 'EXECUTE') THEN
    RAISE EXCEPTION 'fresh development ownership or grants are wrong';
  END IF;
END $$;
\quit
\endif

DO $$
DECLARE
  role_name text;
  production_roles text[] := ARRAY[
    'pricing_loader_writer', 'pricing_reader', 'oracle_owner', 'tollchat_agent',
    'pricing_caller', 'report_publisher'
  ];
  development_roles text[] := ARRAY[
    'pricing_loader_writer_development', 'pricing_reader_development',
    'oracle_owner_development', 'tollchat_agent_development',
    'pricing_caller_development', 'report_publisher_development'
  ];
BEGIN
  IF (SELECT description FROM pg_shdescription
      WHERE objoid = (SELECT oid FROM pg_database WHERE datname = 'nova_toll'))
       IS DISTINCT FROM 'environment=production'
     OR (SELECT description FROM pg_shdescription
         WHERE objoid = (SELECT oid FROM pg_database WHERE datname = 'nova_toll_development'))
       IS DISTINCT FROM 'environment=development' THEN
    RAISE EXCEPTION 'database environment comments are wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN (
      'pricing_loader_writer_development', 'pricing_reader_development',
      'oracle_owner_development', 'tollchat_agent_development',
      'pricing_caller_development', 'report_publisher_development'
    )
    AND shobj_description(oid, 'pg_authid') IS DISTINCT FROM 'environment=development'
  ) THEN
    RAISE EXCEPTION 'development role environment comments are wrong';
  END IF;
  IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0'
     OR (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.14.0'
     OR (SELECT count(*) FROM oracle.toll_route_point) <> 220
     OR (SELECT count(*) FROM oracle.toll_connection) <> 996 THEN
    RAISE EXCEPTION 'development bootstrap data/version contract is wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname IN ('nova_toll', 'nova_toll_development')
      AND privilege.grantee = 0 AND privilege.privilege_type = 'CONNECT'
  ) THEN
    RAISE EXCEPTION 'PUBLIC retains CONNECT';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = 'nova_toll' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee <> database.datdba
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer'), to_regrole('pricing_reader'),
        to_regrole('oracle_owner'), to_regrole('tollchat_agent'), to_regrole('pricing_caller'),
        to_regrole('report_publisher'))
  ) OR EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = 'nova_toll_development' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee <> database.datdba
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer_development'),
        to_regrole('pricing_reader_development'), to_regrole('oracle_owner_development'),
        to_regrole('tollchat_agent_development'), to_regrole('pricing_caller_development'),
        to_regrole('report_publisher_development'))
  ) THEN
    RAISE EXCEPTION 'database has unexpected CONNECT grantee';
  END IF;
  FOREACH role_name IN ARRAY production_roles LOOP
    IF NOT has_database_privilege(role_name, 'nova_toll', 'CONNECT')
       OR has_database_privilege(role_name, 'nova_toll_development', 'CONNECT') THEN
      RAISE EXCEPTION 'production role % has wrong CONNECT', role_name;
    END IF;
  END LOOP;
  FOREACH role_name IN ARRAY development_roles LOOP
    IF NOT has_database_privilege(role_name, 'nova_toll_development', 'CONNECT')
       OR has_database_privilege(role_name, 'nova_toll', 'CONNECT') THEN
      RAISE EXCEPTION 'development role % has wrong CONNECT', role_name;
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner_development'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer_development', 'pricing_reader_development',
      'tollchat_agent_development', 'pricing_caller_development', 'report_publisher_development')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'development role attributes are wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer', 'pricing_reader', 'tollchat_agent', 'pricing_caller', 'report_publisher')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'production role attributes are wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE member_role.rolname IN ('pricing_loader_writer_development', 'pricing_reader_development',
      'tollchat_agent_development', 'pricing_caller_development', 'report_publisher_development')
      AND granted_role.rolname <> 'rds_iam'
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members membership JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'oracle_owner_development'
  ) OR NOT pg_has_role('pricing_loader_writer_development', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_reader_development', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('tollchat_agent_development', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_caller_development', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('report_publisher_development', 'rds_iam', 'MEMBER') THEN
    RAISE EXCEPTION 'development role membership is wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE member_role.rolname IN ('pricing_loader_writer', 'pricing_reader', 'tollchat_agent', 'pricing_caller', 'report_publisher')
      AND granted_role.rolname <> 'rds_iam'
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members membership JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'oracle_owner'
  ) OR NOT pg_has_role('pricing_loader_writer', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_reader', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('tollchat_agent', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_caller', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('report_publisher', 'rds_iam', 'MEMBER')
  THEN
    RAISE EXCEPTION 'production role membership is wrong';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_foreign_server)
     OR EXISTS (SELECT 1 FROM pg_user_mappings)
     OR EXISTS (SELECT 1 FROM pg_extension
                WHERE extname IN ('dblink', 'postgres_fdw', 'pg_cron') OR extname LIKE 'postgis_%') THEN
    RAISE EXCEPTION 'development integration boundary is wrong';
  END IF;
  IF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'oracle')
       <> 'oracle_owner_development'
     OR (SELECT pg_get_userbyid(relowner) FROM pg_class
         WHERE oid = 'oracle.toll_route_point'::regclass) <> 'oracle_owner_development'
     OR NOT has_schema_privilege('pricing_loader_writer_development', 'pricing', 'USAGE')
     OR NOT has_schema_privilege('pricing_reader_development', 'pricing', 'USAGE')
     OR NOT has_function_privilege('tollchat_agent_development',
         'oracle.validate_toll_route(text,text)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
         'oracle.get_i95_i495_pricing_comparisons(integer)', 'EXECUTE')
     OR NOT has_function_privilege('report_publisher_development',
         'oracle.get_i95_i495_report_inputs()', 'EXECUTE') THEN
    RAISE EXCEPTION 'development ownership or grants are wrong';
  END IF;
END $$;

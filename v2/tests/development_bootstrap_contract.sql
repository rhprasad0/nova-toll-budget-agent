\set ON_ERROR_STOP on

\if :{?fresh_development}
DO $$
DECLARE
  development_roles text[] := ARRAY[
    'pricing_loader_writer_development', 'pricing_reader_development',
    'oracle_owner_development', 'tollchat_agent_development',
    'pricing_caller_development', 'report_publisher_development',
    'pricing_owner_development', 'schema_migrator_development'
  ];
BEGIN
  IF current_database() <> 'nova_toll_development'
     OR (SELECT count(*) FROM pg_roles WHERE rolname = ANY (development_roles)) <> 8
     OR (SELECT count(*) FROM pg_roles
         WHERE rolname LIKE E'%\\_development' ESCAPE E'\\') <> 8 THEN
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
  IF EXISTS (
    SELECT 1 FROM pg_database database
    CROSS JOIN LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = current_database()
      AND privilege.privilege_type = 'CONNECT'
      AND (privilege.grantee = 0 OR (
        privilege.grantee NOT IN (0, database.datdba)
        AND privilege.grantee NOT IN (
          SELECT oid FROM pg_roles WHERE rolname = ANY (development_roles)
        )
      ))
  ) THEN
    RAISE EXCEPTION 'fresh development database CONNECT grants are wrong';
  END IF;
END $$;
\else
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
    'pricing_caller_development', 'report_publisher_development',
    'pricing_owner_development', 'schema_migrator_development'
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
    WHERE rolname = ANY (development_roles)
      AND shobj_description(oid, 'pg_authid') IS DISTINCT FROM 'environment=development'
  ) THEN
    RAISE EXCEPTION 'development role environment comments are wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database
    CROSS JOIN LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname IN ('nova_toll', 'nova_toll_development')
      AND privilege.grantee = 0 AND privilege.privilege_type = 'CONNECT'
  ) OR EXISTS (
    SELECT 1 FROM pg_database database
    CROSS JOIN LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = 'nova_toll'
      AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee NOT IN (0, database.datdba)
      AND privilege.grantee NOT IN (
        SELECT oid FROM pg_roles WHERE rolname = ANY (production_roles)
      )
  ) OR EXISTS (
    SELECT 1 FROM pg_database database
    CROSS JOIN LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = 'nova_toll_development'
      AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee NOT IN (0, database.datdba)
      AND privilege.grantee NOT IN (
        SELECT oid FROM pg_roles WHERE rolname = ANY (development_roles)
      )
  ) THEN
    RAISE EXCEPTION 'database CONNECT grants are wrong';
  END IF;
  FOREACH role_name IN ARRAY production_roles LOOP
    IF NOT has_database_privilege(role_name, 'nova_toll', 'CONNECT')
       OR has_database_privilege(role_name, 'nova_toll_development', 'CONNECT') THEN
      RAISE EXCEPTION 'production role % has wrong database CONNECT', role_name;
    END IF;
  END LOOP;
  FOREACH role_name IN ARRAY development_roles LOOP
    IF NOT has_database_privilege(role_name, 'nova_toll_development', 'CONNECT')
       OR has_database_privilege(role_name, 'nova_toll', 'CONNECT') THEN
      RAISE EXCEPTION 'development role % has wrong database CONNECT', role_name;
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer', 'pricing_reader', 'tollchat_agent',
                      'pricing_caller', 'report_publisher')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'production role attributes are wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE member_role.rolname = ANY (production_roles)
      AND granted_role.rolname <> 'rds_iam'
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'oracle_owner'
  ) THEN
    RAISE EXCEPTION 'production role membership is wrong';
  END IF;
END $$;
\endif

DO $$
DECLARE
  runtime_roles text[] := ARRAY[
    'pricing_loader_writer_development', 'pricing_reader_development',
    'oracle_owner_development', 'tollchat_agent_development',
    'pricing_caller_development', 'report_publisher_development'
  ];
BEGIN
  IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.3.0'
     OR (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.14.1'
     OR (SELECT count(*) FROM oracle.toll_route_point) <> 220
     OR (SELECT count(*) FROM oracle.toll_connection) <> 996 THEN
    RAISE EXCEPTION 'development bootstrap data/version contract is wrong';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('oracle_owner_development', 'pricing_owner_development')
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'schema_migrator_development'
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_owner_development', 'oracle_owner_development',
                      'schema_migrator_development')
      AND rolinherit
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer_development', 'pricing_reader_development',
                      'tollchat_agent_development', 'pricing_caller_development',
                      'report_publisher_development')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'development role attributes are wrong';
  END IF;
  IF (SELECT count(*) FROM pg_auth_members membership
      JOIN pg_roles member_role ON member_role.oid = membership.member
      WHERE member_role.rolname = 'schema_migrator_development') <> 3
     OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE member_role.rolname = 'schema_migrator_development'
         AND granted_role.rolname NOT IN (
           'rds_iam', 'pricing_owner_development', 'oracle_owner_development'
         )
     ) OR NOT pg_has_role('schema_migrator_development', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('schema_migrator_development', 'pricing_owner_development', 'MEMBER')
     OR NOT pg_has_role('schema_migrator_development', 'oracle_owner_development', 'MEMBER')
     OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE member_role.rolname = 'schema_migrator_development'
         AND granted_role.rolname IN ('pricing_owner_development', 'oracle_owner_development')
         AND (membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
     ) OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE member_role.rolname = ANY (runtime_roles)
         AND granted_role.rolname <> 'rds_iam'
     ) OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
     WHERE member_role.rolname = ANY (runtime_roles)
         AND granted_role.rolname IN (
           'schema_migrator_development', 'pricing_owner_development',
           'oracle_owner_development'
         )
     ) OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE granted_role.rolname IN ('pricing_owner_development', 'oracle_owner_development')
         AND member_role.rolname <> 'schema_migrator_development'
     ) OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       WHERE member_role.rolname IN ('pricing_owner_development', 'oracle_owner_development')
     ) THEN
    RAISE EXCEPTION 'development role membership is wrong';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_foreign_server)
     OR EXISTS (SELECT 1 FROM pg_user_mappings)
     OR EXISTS (SELECT 1 FROM pg_extension
                WHERE extname IN ('dblink', 'postgres_fdw', 'pg_cron')
                   OR extname LIKE 'postgis_%') THEN
    RAISE EXCEPTION 'development integration boundary is wrong';
  END IF;
  IF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'pricing')
       <> 'pricing_owner_development'
     OR EXISTS (
       SELECT 1 FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'pricing'
         AND pg_get_userbyid(relation.relowner) <> 'pricing_owner_development'
     ) OR EXISTS (
       SELECT 1 FROM pg_proc procedure
       JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       WHERE namespace.nspname = 'pricing'
         AND pg_get_userbyid(procedure.proowner) <> 'pricing_owner_development'
     ) THEN
    RAISE EXCEPTION 'pricing objects are not owned by the stable development owner';
  END IF;
  IF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'oracle')
       <> 'oracle_owner_development'
     OR EXISTS (
       SELECT 1 FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'oracle'
         AND relation.relkind IN ('r', 'v', 'm', 'f', 'p')
         AND relation.relname NOT IN ('geometry_columns', 'geography_columns', 'spatial_ref_sys')
         AND NOT EXISTS (
           SELECT 1 FROM pg_depend dependency
           JOIN pg_extension extension ON extension.oid = dependency.refobjid
           WHERE dependency.classid = 'pg_class'::regclass
             AND dependency.objid = relation.oid
             AND dependency.deptype = 'e'
         )
         AND pg_get_userbyid(relation.relowner) <> 'oracle_owner_development'
     ) OR EXISTS (
       SELECT 1 FROM pg_proc procedure
       JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       WHERE namespace.nspname = 'oracle'
         AND NOT EXISTS (
           SELECT 1 FROM pg_depend dependency
           JOIN pg_extension extension ON extension.oid = dependency.refobjid
           WHERE dependency.classid = 'pg_proc'::regclass
             AND dependency.objid = procedure.oid
             AND dependency.deptype = 'e'
         )
         AND pg_get_userbyid(procedure.proowner) <> 'oracle_owner_development'
     ) THEN
    RAISE EXCEPTION 'oracle objects are not owned by the stable development owner';
  END IF;
  IF NOT has_schema_privilege('pricing_loader_writer_development', 'pricing', 'USAGE')
     OR has_schema_privilege('pricing_loader_writer_development', 'pricing', 'CREATE')
     OR has_table_privilege('pricing_loader_writer_development',
          'pricing.schema_version', 'SELECT,INSERT,UPDATE,DELETE')
     OR NOT has_table_privilege('pricing_loader_writer_development',
          'pricing.trip_pricing_i95', 'SELECT,INSERT,UPDATE')
     OR NOT has_table_privilege('pricing_loader_writer_development',
          'pricing.trip_pricing_i66', 'SELECT,INSERT,UPDATE')
     OR has_table_privilege('pricing_loader_writer_development',
          'pricing.trip_pricing_i95', 'DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('pricing_loader_writer_development',
          'pricing.trip_pricing_i66', 'DELETE,TRUNCATE,REFERENCES,TRIGGER') THEN
    RAISE EXCEPTION 'development pricing loader privileges are wrong';
  END IF;
  IF NOT has_schema_privilege('pricing_reader_development', 'pricing', 'USAGE')
     OR has_schema_privilege('pricing_reader_development', 'pricing', 'CREATE')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.schema_version', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.trip_pricing_i95', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.trip_pricing_i66', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.current_trip_pricing_i95', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.current_trip_pricing_i66', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.current_i95_direction', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.i95_modeled_od_proxy', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.modeled_trip_pricing_i95', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.modeled_current_trip_pricing_i95', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.i66_pricing_comparisons', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.i95_i495_pricing_comparisons', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.i66_ballpark_samples', 'SELECT')
     OR NOT has_table_privilege('pricing_reader_development',
          'pricing.i95_i495_ballpark_samples', 'SELECT')
     OR has_table_privilege('pricing_reader_development',
          'pricing.trip_pricing_i95', 'INSERT,UPDATE,DELETE')
     OR has_table_privilege('pricing_reader_development',
          'pricing.trip_pricing_i66', 'INSERT,UPDATE,DELETE') THEN
    RAISE EXCEPTION 'development pricing reader privileges are wrong';
  END IF;
  IF NOT has_schema_privilege('tollchat_agent_development', 'oracle', 'USAGE')
     OR has_schema_privilege('tollchat_agent_development', 'oracle', 'CREATE')
     OR NOT has_function_privilege('tollchat_agent_development',
          'oracle.get_toll_route_prompt_points()', 'EXECUTE')
     OR NOT has_function_privilege('tollchat_agent_development',
          'oracle.validate_toll_route(text,text)', 'EXECUTE')
     OR NOT has_schema_privilege('pricing_caller_development', 'oracle', 'USAGE')
     OR has_schema_privilege('pricing_caller_development', 'oracle', 'CREATE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.validate_pricing_route(text,text)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.get_i66_pricing_comparisons(integer,integer,text)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.get_i66_pricing_comparisons(integer,integer)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.get_i95_i495_pricing_comparisons(integer)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.validate_ballpark_route(text,text)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.get_priced_route_distance_miles(jsonb)', 'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.get_i66_ballpark_samples(integer,integer,text,time,date[],timestamptz)',
          'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.get_i95_i495_ballpark_samples(integer,time,date[],timestamptz)',
          'EXECUTE')
     OR NOT has_function_privilege('pricing_caller_development',
          'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)',
          'EXECUTE')
     OR NOT has_schema_privilege('report_publisher_development', 'oracle', 'USAGE')
     OR has_schema_privilege('report_publisher_development', 'oracle', 'CREATE')
     OR NOT has_function_privilege('report_publisher_development',
          'oracle.get_i95_i495_report_inputs()', 'EXECUTE')
     OR NOT has_function_privilege('report_publisher_development',
          'oracle.get_agent_report_routes()', 'EXECUTE') THEN
    RAISE EXCEPTION 'development Oracle runtime privileges are wrong';
  END IF;
  IF (SELECT pg_get_userbyid(nspowner)
      FROM pg_namespace WHERE nspname = 'tollchat_migration')
       <> 'pricing_owner_development'
     OR (SELECT pg_get_userbyid(relowner)
         FROM pg_class WHERE oid = 'tollchat_migration.schema_history'::regclass)
       <> 'pricing_owner_development'
     OR (SELECT count(*) FROM tollchat_migration.schema_history) <> 2
     OR EXISTS (
       SELECT 1 FROM tollchat_migration.schema_history
       WHERE NOT is_baseline OR migration_id <> 'baseline'
         OR (schema_name, schema_version, source_path) NOT IN (
           ('pricing', '1.3.0', 'v2/db/schema.sql'),
           ('oracle', '1.14.1', 'v2/db/oracle/schema.sql')
         )
         OR source_sha256 !~ '^[0-9a-f]{64}$'
         OR btrim(evidence) = ''
     ) THEN
    RAISE EXCEPTION 'development migration history baseline is wrong';
  END IF;
  IF has_schema_privilege('schema_migrator_development', 'pricing', 'USAGE')
     OR has_schema_privilege('schema_migrator_development', 'oracle', 'USAGE')
     OR has_schema_privilege('schema_migrator_development', 'tollchat_migration', 'USAGE')
     OR has_table_privilege('schema_migrator_development',
          'tollchat_migration.schema_history', 'SELECT,INSERT,UPDATE,DELETE')
     OR EXISTS (
       SELECT 1 FROM pg_namespace namespace
       CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle')
         AND privilege.grantee = to_regrole('schema_migrator_development')
     ) OR EXISTS (
       SELECT 1 FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle')
         AND privilege.grantee = to_regrole('schema_migrator_development')
     ) OR EXISTS (
       SELECT 1 FROM pg_type type
       JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
       CROSS JOIN LATERAL aclexplode(type.typacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle')
         AND privilege.grantee = to_regrole('schema_migrator_development')
     ) OR EXISTS (
       SELECT 1 FROM pg_attribute attribute
       JOIN pg_class relation ON relation.oid = attribute.attrelid
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       CROSS JOIN LATERAL aclexplode(attribute.attacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle')
         AND attribute.attnum > 0
         AND privilege.grantee = to_regrole('schema_migrator_development')
     ) OR EXISTS (
       SELECT 1 FROM pg_proc procedure
       JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       CROSS JOIN LATERAL aclexplode(procedure.proacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle')
         AND privilege.grantee = to_regrole('schema_migrator_development')
     ) THEN
    RAISE EXCEPTION 'schema migrator has an unexpected direct application privilege';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace namespace
    CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
    WHERE namespace.nspname = 'tollchat_migration' AND privilege.grantee = 0
  ) OR EXISTS (
    SELECT 1 FROM pg_class relation
    WHERE relation.oid = 'tollchat_migration.schema_history'::regclass
      AND EXISTS (
        SELECT 1 FROM aclexplode(relation.relacl) privilege
        WHERE privilege.grantee = 0
      )
  ) OR EXISTS (
    SELECT 1 FROM pg_attribute attribute
    WHERE attribute.attrelid = 'tollchat_migration.schema_history'::regclass
      AND attribute.attnum > 0
      AND EXISTS (
        SELECT 1 FROM aclexplode(attribute.attacl) privilege
        WHERE privilege.grantee = 0
      )
  ) OR EXISTS (
    SELECT 1 FROM unnest(runtime_roles) AS role_name
    WHERE has_schema_privilege(role_name, 'tollchat_migration', 'USAGE')
       OR has_table_privilege(role_name, 'tollchat_migration.schema_history',
          'SELECT,INSERT,UPDATE,DELETE')
  ) OR EXISTS (
    SELECT 1 FROM pg_attribute attribute
    WHERE attribute.attrelid = 'tollchat_migration.schema_history'::regclass
      AND attribute.attnum > 0
      AND EXISTS (
        SELECT 1 FROM aclexplode(attribute.attacl) privilege
        JOIN pg_roles role ON role.oid = privilege.grantee
        WHERE role.rolname = ANY (runtime_roles)
      )
  ) THEN
    RAISE EXCEPTION 'migration history is not private';
  END IF;
END $$;

\if :{?pricing_sha256}
SELECT
  (SELECT source_sha256 FROM tollchat_migration.schema_history
   WHERE schema_name = 'pricing') IS NOT DISTINCT FROM :'pricing_sha256'
  AND (SELECT source_sha256 FROM tollchat_migration.schema_history
       WHERE schema_name = 'oracle') IS NOT DISTINCT FROM :'oracle_sha256'
  AS development_migration_baseline_checksums_match
\gset
\if :development_migration_baseline_checksums_match
\else
\quit 1
\endif
\endif

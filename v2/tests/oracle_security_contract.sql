\set ON_ERROR_STOP on

DO $$
DECLARE
    executable_count integer;
BEGIN
    IF (SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = 'oracle_owner')
       OR NOT (SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = 'tollchat_agent')
       OR NOT pg_has_role('tollchat_agent', 'rds_iam', 'MEMBER') THEN
        RAISE EXCEPTION 'oracle roles do not have the required attributes';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        WHERE member_role.rolname = 'tollchat_agent'
          AND granted_role.rolname <> 'rds_iam'
    ) THEN
        RAISE EXCEPTION 'tollchat_agent retained an unexpected membership';
    END IF;
    IF (SELECT pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace
        WHERE nspname = 'oracle') <> 'oracle_owner'
       OR (SELECT pg_get_userbyid(relowner) FROM pg_catalog.pg_class
           WHERE oid = 'oracle.toll_route_point'::regclass) <> 'oracle_owner'
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.validate_toll_route(text,text)'::regprocedure)
          <> 'oracle_owner'
       OR NOT (SELECT prosecdef FROM pg_catalog.pg_proc
               WHERE oid = 'oracle.validate_toll_route(text,text)'::regprocedure) THEN
        RAISE EXCEPTION 'oracle ownership or SECURITY DEFINER contract is wrong';
    END IF;
    IF has_schema_privilege('tollchat_agent', 'pricing', 'USAGE')
       OR has_table_privilege(
           'tollchat_agent', 'pricing.current_i95_direction', 'SELECT'
       )
       OR has_table_privilege(
           'tollchat_agent', 'oracle.toll_route_point', 'SELECT'
       )
       OR has_table_privilege(
           'tollchat_agent', 'oracle.toll_connection', 'INSERT,UPDATE,DELETE'
       ) THEN
        RAISE EXCEPTION 'tollchat_agent has direct relation access';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure,
             LATERAL aclexplode(
                 coalesce(procedure.proacl, acldefault('f', procedure.proowner))
             ) AS privilege
        WHERE procedure.oid = 'oracle.validate_toll_route(text,text)'::regprocedure
          AND privilege.grantee = 0
          AND privilege.privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'PUBLIC can execute the route function';
    END IF;
    SELECT count(*) INTO executable_count
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND has_function_privilege('tollchat_agent', procedure.oid, 'EXECUTE');
    IF executable_count <> 1 OR NOT has_function_privilege(
        'tollchat_agent', 'oracle.validate_toll_route(text,text)', 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'agent executable surface is not exactly one function';
    END IF;
END $$;

SET ROLE tollchat_agent;

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'i66:4:exit:EB');
    IF result.status <> 'valid' THEN
        RAISE EXCEPTION 'agent route execution failed';
    END IF;
    BEGIN
        PERFORM count(*) FROM oracle.toll_route_point;
        RAISE EXCEPTION 'agent read oracle table directly';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM count(*) FROM pricing.current_i95_direction;
        RAISE EXCEPTION 'agent read pricing view directly';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        INSERT INTO oracle.toll_route_point (
            point_id, network_id, source_node_id, point_type, direction,
            label, aliases, source_metadata
        ) VALUES (
            'forbidden', 'i66', 'forbidden', 'entry', 'EB',
            'forbidden', ARRAY[]::text[], '{}'::jsonb
        );
        RAISE EXCEPTION 'agent mutated oracle table';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM oracle.ST_MakePoint(0, 0);
        RAISE EXCEPTION 'agent executed a PostGIS function';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;

CREATE TEMP TABLE toll_route_point (point_id text, point_type text);
INSERT INTO toll_route_point VALUES ('i66:1:entry:EB', 'exit');

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'i66:4:exit:EB');
    IF result.status <> 'valid' THEN
        RAISE EXCEPTION 'temporary shadow changed security-definer behavior';
    END IF;
END $$;

RESET ROLE;

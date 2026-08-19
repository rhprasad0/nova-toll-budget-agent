\set ON_ERROR_STOP on

DO $$
DECLARE
    executable_count integer;
    route_function record;
    pricing_route_function record;
    i66_pricing_function record;
    resolver_function record;
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
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid =
             'oracle.validate_pricing_route(text,text)'::regprocedure)
          <> 'oracle_owner'
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid =
             'oracle.get_i66_pricing_comparisons(integer,integer)'::regprocedure)
          <> 'oracle_owner'
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.resolve_toll_route(text,text)'::regprocedure)
          <> 'oracle_owner'
       OR NOT (SELECT prosecdef FROM pg_catalog.pg_proc
               WHERE oid = 'oracle.validate_toll_route(text,text)'::regprocedure)
       OR NOT (SELECT prosecdef FROM pg_catalog.pg_proc
               WHERE oid =
                 'oracle.validate_pricing_route(text,text)'::regprocedure)
       OR NOT (SELECT prosecdef FROM pg_catalog.pg_proc
               WHERE oid =
                 'oracle.get_i66_pricing_comparisons(integer,integer)'::regprocedure)
       OR (SELECT prosecdef FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.resolve_toll_route(text,text)'::regprocedure) THEN
        RAISE EXCEPTION 'oracle ownership or SECURITY DEFINER contract is wrong';
    END IF;
    SELECT
        procedure.provolatile,
        procedure.proconfig,
        procedure.proargnames,
        procedure.proallargtypes,
        procedure.proargmodes
    INTO route_function
    FROM pg_catalog.pg_proc AS procedure
    WHERE procedure.oid =
        'oracle.validate_toll_route(text,text)'::regprocedure;
    IF route_function.provolatile <> 's'
       OR route_function.proconfig IS DISTINCT FROM
          ARRAY['search_path=pg_catalog, pg_temp']::text[]
       OR route_function.proargnames IS DISTINCT FROM ARRAY[
           'origin_point_id', 'destination_point_id',
           'status', 'reason', 'point_ids', 'connection_ids', 'connection_types',
           'general_purpose_gaps', 'i95_evidence'
       ]::text[]
       OR route_function.proallargtypes IS DISTINCT FROM ARRAY[
           'text'::regtype::oid,
           'text'::regtype::oid,
           'text'::regtype::oid,
           'jsonb'::regtype::oid,
           'text[]'::regtype::oid,
           'text[]'::regtype::oid,
           'text[]'::regtype::oid,
           'jsonb'::regtype::oid,
           'jsonb'::regtype::oid
       ]::oid[]
       OR route_function.proargmodes IS DISTINCT FROM ARRAY[
           'i'::"char", 'i'::"char",
           't'::"char", 't'::"char", 't'::"char",
           't'::"char", 't'::"char", 't'::"char", 't'::"char"
       ]::"char"[] THEN
        RAISE EXCEPTION 'route function catalog contract is wrong: %',
            row_to_json(route_function);
    END IF;
    SELECT
        procedure.provolatile,
        procedure.proconfig,
        procedure.proargnames,
        procedure.proallargtypes,
        procedure.proargmodes
    INTO pricing_route_function
    FROM pg_catalog.pg_proc AS procedure
    WHERE procedure.oid =
        'oracle.validate_pricing_route(text,text)'::regprocedure;
    IF pricing_route_function.provolatile <> 's'
       OR pricing_route_function.proconfig IS DISTINCT FROM
          ARRAY['search_path=pg_catalog, pg_temp']::text[]
       OR pricing_route_function.proargnames IS DISTINCT FROM ARRAY[
           'origin_point_id', 'destination_point_id',
           'status', 'reason', 'point_ids', 'connection_ids', 'connection_types',
           'general_purpose_gaps', 'i95_evidence', 'facility_legs'
       ]::text[]
       OR pricing_route_function.proallargtypes IS DISTINCT FROM ARRAY[
           'text'::regtype::oid,
           'text'::regtype::oid,
           'text'::regtype::oid,
           'jsonb'::regtype::oid,
           'text[]'::regtype::oid,
           'text[]'::regtype::oid,
           'text[]'::regtype::oid,
           'jsonb'::regtype::oid,
           'jsonb'::regtype::oid,
           'jsonb'::regtype::oid
       ]::oid[]
       OR pricing_route_function.proargmodes IS DISTINCT FROM ARRAY[
           'i'::"char", 'i'::"char",
           't'::"char", 't'::"char", 't'::"char", 't'::"char",
           't'::"char", 't'::"char", 't'::"char", 't'::"char"
       ]::"char"[] THEN
        RAISE EXCEPTION 'pricing route function catalog contract is wrong: %',
            row_to_json(pricing_route_function);
    END IF;
    SELECT procedure.provolatile, procedure.proconfig
    INTO i66_pricing_function
    FROM pg_catalog.pg_proc AS procedure
    WHERE procedure.oid =
        'oracle.get_i66_pricing_comparisons(integer,integer)'::regprocedure;
    IF i66_pricing_function.provolatile <> 's'
       OR i66_pricing_function.proconfig IS DISTINCT FROM
          ARRAY['search_path=pg_catalog, pg_temp']::text[] THEN
        RAISE EXCEPTION 'I-66 pricing function catalog contract is wrong: %',
            row_to_json(i66_pricing_function);
    END IF;
    SELECT procedure.provolatile, procedure.proconfig
    INTO resolver_function
    FROM pg_catalog.pg_proc AS procedure
    WHERE procedure.oid =
        'oracle.resolve_toll_route(text,text)'::regprocedure;
    IF resolver_function.provolatile <> 's'
       OR resolver_function.proconfig IS DISTINCT FROM
          ARRAY['search_path=pg_catalog, pg_temp']::text[] THEN
        RAISE EXCEPTION 'route resolver catalog contract is wrong: %',
            row_to_json(resolver_function);
    END IF;
    IF has_schema_privilege('tollchat_agent', 'pricing', 'USAGE')
       OR has_table_privilege(
           'tollchat_agent', 'pricing.current_i95_direction', 'SELECT'
       )
       OR has_table_privilege(
           'tollchat_agent', 'pricing.i66_pricing_comparisons', 'SELECT'
       )
       OR has_table_privilege(
           'tollchat_agent', 'oracle.toll_route_point', 'SELECT'
       )
       OR has_table_privilege(
           'tollchat_agent', 'oracle.route_pricing_component', 'SELECT'
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
              WHERE procedure.oid IN (
                  'oracle.validate_toll_route(text,text)'::regprocedure,
                  'oracle.validate_pricing_route(text,text)'::regprocedure,
                  'oracle.get_i66_pricing_comparisons(integer,integer)'::regprocedure,
                  'oracle.resolve_toll_route(text,text)'::regprocedure
              )
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
    IF executable_count <> 3
       OR NOT has_function_privilege(
           'tollchat_agent', 'oracle.validate_toll_route(text,text)', 'EXECUTE'
       )
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.validate_pricing_route(text,text)',
           'EXECUTE'
       )
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.get_i66_pricing_comparisons(integer,integer)',
           'EXECUTE'
       )
       OR to_regprocedure(
           'oracle.validate_pricing_route(text[],text[])'
       ) IS NOT NULL
       OR has_function_privilege(
           'tollchat_agent', 'oracle.resolve_toll_route(text,text)', 'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'agent executable surface is not exactly three functions';
    END IF;
END $$;

SET ROLE tollchat_agent;

DO $$
DECLARE result record;
BEGIN
    SELECT * INTO result
    FROM oracle.validate_toll_route('i66:1:entry:EB', 'i66:4:exit:EB');
    IF result.status <> 'valid' OR result.reason IS NOT NULL THEN
        RAISE EXCEPTION 'agent route execution failed';
    END IF;
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        'i66:1:entry:EB', 'i66:4:exit:EB'
    );
    IF result.status <> 'valid'
       OR jsonb_array_length(result.facility_legs) <> 1 THEN
        RAISE EXCEPTION 'agent pricing-route execution failed';
    END IF;
    SELECT * INTO result
    FROM oracle.get_i66_pricing_comparisons(3100, 3110);
    IF result.comparison_kind <> 'current'
       OR result.available
       OR result.availability_reason <> 'missing_observation' THEN
        RAISE EXCEPTION 'agent I-66 pricing diagnostic failed';
    END IF;
    BEGIN
        PERFORM *
        FROM oracle.resolve_toll_route('i66:1:entry:EB', 'i66:4:exit:EB');
        RAISE EXCEPTION 'agent executed the private route resolver';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
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
        PERFORM count(*) FROM pricing.i66_pricing_comparisons;
        RAISE EXCEPTION 'agent read I-66 pricing view directly';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM count(*) FROM oracle.route_pricing_component;
        RAISE EXCEPTION 'agent read route pricing components directly';
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
    SELECT * INTO result
    FROM oracle.validate_pricing_route(
        'i66:1:entry:EB', 'i66:4:exit:EB'
    );
    IF result.status <> 'valid' THEN
        RAISE EXCEPTION 'temporary shadow changed pricing-route behavior';
    END IF;
END $$;

RESET ROLE;

\set ON_ERROR_STOP on

DO $$
DECLARE
    relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'trip_pricing_i95',
        'trip_pricing_i66',
        'current_trip_pricing_i95',
        'current_trip_pricing_i66',
        'current_i95_direction',
        'i95_modeled_od_proxy',
        'modeled_trip_pricing_i95',
        'modeled_current_trip_pricing_i95'
    ] LOOP
        IF to_regclass('public.' || relation_name) IS NULL THEN
            RAISE EXCEPTION 'rollback removed pre-migration relation: %', relation_name;
        END IF;
    END LOOP;

    IF to_regclass('public.dynamic_pricing_observations') IS NOT NULL
       OR to_regprocedure(
            'public.point_in_time_dynamic_route_pricing(timestamp with time zone,jsonb)'
       ) IS NOT NULL
       OR to_regprocedure(
            'public.historical_dynamic_route_pricing(timestamp with time zone,jsonb)'
       ) IS NOT NULL THEN
        RAISE EXCEPTION 'rollback retained a migration-owned analysis surface';
    END IF;
END $$;

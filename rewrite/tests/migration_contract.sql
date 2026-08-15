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

    IF (
        SELECT array_agg(column_name::text ORDER BY ordinal_position)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'modeled_trip_pricing_i95'
    ) <> ARRAY[
        'od_pair_id', 'corridor_name', 'zone_toll_rate_usd',
        'interval_end_at', 'calculated_at', 'link_status',
        'proxy_od_pair_id', 'modeled', 'pricing_method'
    ]::text[] THEN
        RAISE EXCEPTION 'rollback did not restore the schema 1.1 modeled view shape';
    END IF;

    IF NOT has_table_privilege(
        'pricing_reader', 'public.modeled_trip_pricing_i95', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'rollback did not restore pricing_reader access to modeled history';
    END IF;
END $$;

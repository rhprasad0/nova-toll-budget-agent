-- Add compact, date-aligned annual ballpark aggregation.

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

    IF current_version NOT IN ('1.6.0', '1.7.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.6.0 or 1.7.0, got %',
            current_version;
    END IF;
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.2.0'
       OR to_regrole('oracle_owner') IS NULL
       OR to_regrole('tollchat_agent') IS NULL THEN
        RAISE EXCEPTION 'oracle 1.7.0 requires pricing 1.2.0';
    END IF;
END
$migration$;

SELECT version = '1.6.0' AS oracle_upgrade_needed
FROM oracle.schema_version
WHERE singleton
\gset

\if :oracle_upgrade_needed

CREATE FUNCTION oracle.get_annual_ballpark_summary(
    requested_legs jsonb,
    requested_outbound_time time,
    requested_return_time time,
    requested_dates date[],
    requested_fixed_prices jsonb,
    requested_annual_days integer,
    requested_evaluated_at timestamptz
) RETURNS TABLE (
    eligible_date_count integer,
    complete_pair_count integer,
    coverage_percent text,
    coverage_by_weekday jsonb,
    available_start_date date,
    available_end_date date,
    sample_status text,
    uses_modeled boolean,
    uses_current_fixed_rates boolean,
    facility_scenarios jsonb,
    p25_daily_usd numeric,
    p50_daily_usd numeric,
    p90_daily_usd numeric,
    p25_annualized_usd numeric,
    p50_annualized_usd numeric,
    p90_annualized_usd numeric
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    leg_count integer;
    fixed_price_count integer;
    requested_weekday_count integer;
BEGIN
    PERFORM oracle.validate_ballpark_sample_request(
        requested_outbound_time, requested_dates, requested_evaluated_at
    );
    PERFORM oracle.validate_ballpark_sample_request(
        requested_return_time, requested_dates, requested_evaluated_at
    );

    IF requested_legs IS NULL
       OR requested_fixed_prices IS NULL
       OR jsonb_typeof(requested_legs) <> 'array'
       OR jsonb_typeof(requested_fixed_prices) <> 'array' THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;
    leg_count := jsonb_array_length(requested_legs);
    fixed_price_count := jsonb_array_length(requested_fixed_prices);
    SELECT count(DISTINCT extract(isodow FROM requested_date.value))
    INTO requested_weekday_count
    FROM unnest(requested_dates) AS requested_date(value);
    IF leg_count > 24
       OR fixed_price_count > cardinality(requested_dates) * 24
       OR requested_annual_days IS NULL
       OR requested_annual_days NOT BETWEEN 1 AND 366
       OR requested_annual_days > 53 * requested_weekday_count THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(requested_legs) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'object'
           OR item.value->>'direction' IS NULL
           OR item.value->>'facility' IS NULL
           OR item.value->>'route_step_id' IS NULL
           OR item.value->>'direction' NOT IN ('outbound', 'return')
           OR item.value->>'facility' NOT IN ('i66', 'i95_i495', 'greenway', 'dtr')
           OR item.value->>'route_step_id' !~ '^step-[1-9][0-9]*$'
           OR CASE item.value->>'facility'
                WHEN 'i66' THEN
                    NOT item.value ?& ARRAY[
                        'direction', 'facility', 'route_step_id',
                        'start_zone_id', 'end_zone_id'
                    ]
                    OR item.value - ARRAY[
                        'direction', 'facility', 'route_step_id',
                        'start_zone_id', 'end_zone_id'
                    ] <> '{}'::jsonb
                    OR item.value->>'start_zone_id' !~ '^[1-9][0-9]*$'
                    OR item.value->>'end_zone_id' !~ '^[1-9][0-9]*$'
                    OR item.value->>'start_zone_id' IS NULL
                    OR item.value->>'end_zone_id' IS NULL
                WHEN 'i95_i495' THEN
                    NOT item.value ?& ARRAY[
                        'direction', 'facility', 'route_step_id', 'od_pair_id'
                    ]
                    OR item.value - ARRAY[
                        'direction', 'facility', 'route_step_id', 'od_pair_id'
                    ] <> '{}'::jsonb
                    OR item.value->>'od_pair_id' !~ '^[1-9][0-9]*$'
                    OR item.value->>'od_pair_id' IS NULL
                ELSE
                    NOT item.value ?& ARRAY[
                        'direction', 'facility', 'route_step_id'
                    ]
                    OR item.value - ARRAY[
                        'direction', 'facility', 'route_step_id'
                    ] <> '{}'::jsonb
              END
    ) OR (
        SELECT count(DISTINCT concat_ws(
            ':', item.value->>'direction', item.value->>'route_step_id'
        ))
        FROM jsonb_array_elements(requested_legs) AS item(value)
    ) <> leg_count THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(requested_fixed_prices) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'object'
           OR NOT item.value ?& ARRAY[
                'sample_date', 'direction', 'route_step_id', 'price_usd'
              ]
           OR item.value - ARRAY[
                'sample_date', 'direction', 'route_step_id', 'price_usd'
              ] <> '{}'::jsonb
           OR item.value->>'sample_date' IS NULL
           OR item.value->>'direction' IS NULL
           OR item.value->>'route_step_id' IS NULL
           OR item.value->>'price_usd' IS NULL
           OR item.value->>'sample_date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
           OR item.value->>'direction' NOT IN ('outbound', 'return')
           OR item.value->>'route_step_id' !~ '^step-[1-9][0-9]*$'
           OR item.value->>'price_usd' !~ '^[0-9]+([.][0-9]{1,2})?$'
           OR (item.value->>'price_usd')::numeric > 1000.00
           OR (item.value->>'sample_date')::date <> ALL(requested_dates)
           OR NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(requested_legs) AS leg(value)
                WHERE leg.value->>'direction' = item.value->>'direction'
                  AND leg.value->>'route_step_id' = item.value->>'route_step_id'
                  AND leg.value->>'facility' IN ('greenway', 'dtr')
           )
    ) OR (
        SELECT count(DISTINCT concat_ws(
            ':', item.value->>'sample_date', item.value->>'direction',
            item.value->>'route_step_id'
        ))
        FROM jsonb_array_elements(requested_fixed_prices) AS item(value)
    ) <> fixed_price_count THEN
        RAISE EXCEPTION 'invalid annual ballpark request';
    END IF;

    RETURN QUERY
    WITH legs AS MATERIALIZED (
        SELECT
            item.ordinality::integer AS facility_order,
            item.value->>'direction' AS direction,
            item.value->>'route_step_id' AS route_step_id,
            item.value->>'facility' AS facility,
            CASE WHEN item.value ? 'start_zone_id'
                THEN (item.value->>'start_zone_id')::integer END AS start_zone_id,
            CASE WHEN item.value ? 'end_zone_id'
                THEN (item.value->>'end_zone_id')::integer END AS end_zone_id,
            CASE WHEN item.value ? 'od_pair_id'
                THEN (item.value->>'od_pair_id')::integer END AS od_pair_id
        FROM jsonb_array_elements(requested_legs)
             WITH ORDINALITY AS item(value, ordinality)
    ), eligible_dates AS MATERIALIZED (
        SELECT requested_date.value AS sample_date
        FROM unnest(requested_dates) AS requested_date(value)
    ), i66_prices AS MATERIALIZED (
        SELECT
            sample.sample_date,
            leg.direction,
            leg.route_step_id,
            leg.facility,
            sample.price_usd,
            false AS uses_modeled
        FROM legs AS leg
        CROSS JOIN LATERAL oracle.get_i66_ballpark_samples(
            leg.start_zone_id,
            leg.end_zone_id,
            CASE leg.direction
                WHEN 'outbound' THEN requested_outbound_time
                ELSE requested_return_time
            END,
            requested_dates,
            requested_evaluated_at
        ) AS sample
        WHERE leg.facility = 'i66'
    ), i95_prices AS MATERIALIZED (
        SELECT
            sample.sample_date,
            leg.direction,
            leg.route_step_id,
            leg.facility,
            sample.price_usd,
            sample.uses_modeled
        FROM legs AS leg
        CROSS JOIN LATERAL oracle.get_i95_i495_ballpark_samples(
            leg.od_pair_id,
            CASE leg.direction
                WHEN 'outbound' THEN requested_outbound_time
                ELSE requested_return_time
            END,
            requested_dates,
            requested_evaluated_at
        ) AS sample
        WHERE leg.facility = 'i95_i495'
    ), fixed_prices AS MATERIALIZED (
        SELECT
            (item.value->>'sample_date')::date AS sample_date,
            item.value->>'direction' AS direction,
            item.value->>'route_step_id' AS route_step_id,
            leg.facility,
            (item.value->>'price_usd')::numeric AS price_usd,
            false AS uses_modeled
        FROM jsonb_array_elements(requested_fixed_prices) AS item(value)
        JOIN legs AS leg
          ON leg.direction = item.value->>'direction'
         AND leg.route_step_id = item.value->>'route_step_id'
    ), prices AS MATERIALIZED (
        SELECT * FROM i66_prices
        UNION ALL
        SELECT * FROM i95_prices
        UNION ALL
        SELECT * FROM fixed_prices
    ), complete_dates AS MATERIALIZED (
        SELECT eligible.sample_date
        FROM eligible_dates AS eligible
        WHERE NOT EXISTS (
            SELECT 1
            FROM legs AS leg
            WHERE NOT EXISTS (
                SELECT 1
                FROM prices AS price
                WHERE price.sample_date = eligible.sample_date
                  AND price.direction = leg.direction
                  AND price.route_step_id = leg.route_step_id
            )
        )
    ), facility_daily AS MATERIALIZED (
        SELECT
            complete.sample_date,
            price.facility,
            sum(price.price_usd) AS total_usd,
            bool_or(price.uses_modeled) AS uses_modeled,
            min(leg.facility_order) AS facility_order
        FROM complete_dates AS complete
        JOIN prices AS price USING (sample_date)
        JOIN legs AS leg
          ON leg.direction = price.direction
         AND leg.route_step_id = price.route_step_id
        GROUP BY complete.sample_date, price.facility
    -- Percentiles are not additive: aggregate every facility on the same complete
    -- date first, then rank route totals. Summing facility percentiles is wrong.
    ), route_daily AS MATERIALIZED (
        SELECT
            complete.sample_date,
            coalesce(sum(price.price_usd), 0::numeric) AS total_usd,
            coalesce(bool_or(price.uses_modeled), false) AS uses_modeled,
            coalesce(bool_or(price.facility IN ('greenway', 'dtr')), false)
                AS uses_current_fixed_rates
        FROM complete_dates AS complete
        LEFT JOIN prices AS price USING (sample_date)
        GROUP BY complete.sample_date
    ), facility_statistics AS (
        SELECT
            daily.facility,
            min(daily.facility_order) AS facility_order,
            count(*)::integer AS sample_count,
            bool_or(daily.uses_modeled) AS uses_modeled,
            daily.facility IN ('greenway', 'dtr') AS uses_current_fixed_rates,
            percentile_disc(0.25) WITHIN GROUP (ORDER BY daily.total_usd) AS p25,
            percentile_disc(0.50) WITHIN GROUP (ORDER BY daily.total_usd) AS p50,
            percentile_disc(0.90) WITHIN GROUP (ORDER BY daily.total_usd) AS p90
        FROM facility_daily AS daily
        GROUP BY daily.facility
    ), route_statistics AS (
        SELECT
            count(*)::integer AS sample_count,
            min(daily.sample_date) AS start_date,
            max(daily.sample_date) AS end_date,
            coalesce(bool_or(daily.uses_modeled), false) AS uses_modeled,
            coalesce(bool_or(daily.uses_current_fixed_rates), false)
                AS uses_current_fixed_rates,
            percentile_disc(0.25) WITHIN GROUP (ORDER BY daily.total_usd) AS p25,
            percentile_disc(0.50) WITHIN GROUP (ORDER BY daily.total_usd) AS p50,
            percentile_disc(0.90) WITHIN GROUP (ORDER BY daily.total_usd) AS p90
        FROM route_daily AS daily
    ), weekday_statistics AS (
        SELECT
            extract(isodow FROM eligible.sample_date)::integer AS sample_isodow,
            count(*)::integer AS eligible_count,
            count(complete.sample_date)::integer AS complete_count
        FROM eligible_dates AS eligible
        LEFT JOIN complete_dates AS complete USING (sample_date)
        GROUP BY extract(isodow FROM eligible.sample_date)
    )
    SELECT
        cardinality(requested_dates),
        route.sample_count,
        to_char(
            round(route.sample_count::numeric * 100 / cardinality(requested_dates), 1),
            'FM990.0'
        ),
        coalesce((
            SELECT jsonb_agg(jsonb_build_object(
                'sample_isodow', weekday.sample_isodow,
                'eligible_date_count', weekday.eligible_count,
                'complete_pair_count', weekday.complete_count,
                'coverage_percent', to_char(
                    round(
                        weekday.complete_count::numeric * 100
                        / weekday.eligible_count,
                        1
                    ),
                    'FM990.0'
                )
            ) ORDER BY weekday.sample_isodow)
            FROM weekday_statistics AS weekday
        ), '[]'::jsonb),
        route.start_date,
        route.end_date,
        CASE WHEN route.sample_count = cardinality(requested_dates)
            THEN 'complete' ELSE 'partial' END,
        route.uses_modeled,
        route.uses_current_fixed_rates,
        coalesce((
            SELECT jsonb_agg(jsonb_build_object(
                'facility', facility.facility,
                'sample_count', facility.sample_count,
                'uses_modeled', facility.uses_modeled,
                'uses_current_fixed_rates', facility.uses_current_fixed_rates,
                'scenarios', jsonb_build_object(
                    'p25', jsonb_build_object(
                        'daily_round_trip_usd', to_char(round(facility.p25, 2), 'FM999999990.00'),
                        'annualized_usd', to_char(round(facility.p25 * requested_annual_days, 2), 'FM999999990.00')
                    ),
                    'p50', jsonb_build_object(
                        'daily_round_trip_usd', to_char(round(facility.p50, 2), 'FM999999990.00'),
                        'annualized_usd', to_char(round(facility.p50 * requested_annual_days, 2), 'FM999999990.00')
                    ),
                    'p90', jsonb_build_object(
                        'daily_round_trip_usd', to_char(round(facility.p90, 2), 'FM999999990.00'),
                        'annualized_usd', to_char(round(facility.p90 * requested_annual_days, 2), 'FM999999990.00')
                    )
                )
            ) ORDER BY facility.facility_order)
            FROM facility_statistics AS facility
        ), '[]'::jsonb),
        round(route.p25, 2),
        round(route.p50, 2),
        round(route.p90, 2),
        round(route.p25 * requested_annual_days, 2),
        round(route.p50 * requested_annual_days, 2),
        round(route.p90 * requested_annual_days, 2)
    FROM route_statistics AS route;
END
$function$;

REVOKE ALL ON FUNCTION oracle.get_annual_ballpark_summary(
    jsonb, time, time, date[], jsonb, integer, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION oracle.get_annual_ballpark_summary(
    jsonb, time, time, date[], jsonb, integer, timestamptz
) TO tollchat_agent;
ALTER FUNCTION oracle.get_annual_ballpark_summary(
    jsonb, time, time, date[], jsonb, integer, timestamptz
) OWNER TO oracle_owner;

UPDATE oracle.schema_version
SET version = '1.7.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.6.0';

\endif

DO $migration$
DECLARE
    executable_count integer;
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.7.0'
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)',
           'EXECUTE'
       )
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid =
             'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)'::regprocedure)
          <> 'oracle_owner'
       OR NOT (SELECT prosecdef FROM pg_catalog.pg_proc
               WHERE oid =
                 'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)'::regprocedure)
       OR (SELECT provolatile FROM pg_catalog.pg_proc
           WHERE oid =
             'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)'::regprocedure)
          <> 's'
       OR (SELECT proconfig FROM pg_catalog.pg_proc
           WHERE oid =
             'oracle.get_annual_ballpark_summary(jsonb,time,time,date[],jsonb,integer,timestamptz)'::regprocedure)
          IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::text[] THEN
        RAISE EXCEPTION 'oracle 1.7.0 annual ballpark contract is not installed';
    END IF;

    SELECT count(*) INTO executable_count
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND has_function_privilege('tollchat_agent', procedure.oid, 'EXECUTE');
    IF executable_count <> 8 THEN
        RAISE EXCEPTION 'tollchat_agent executable function count is %',
            executable_count;
    END IF;
END
$migration$;

COMMIT;

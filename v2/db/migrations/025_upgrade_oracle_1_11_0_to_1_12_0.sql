-- Synthesize authoritative I-66 free-period prices in Oracle functions.

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

    IF current_version NOT IN ('1.11.0', '1.12.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.11.0 or 1.12.0, got %',
            current_version;
    END IF;

    IF current_version = '1.11.0' THEN
        CREATE FUNCTION oracle.i66_tolling_active(
            requested_direction text,
            requested_local_at timestamp
        ) RETURNS boolean
        LANGUAGE plpgsql IMMUTABLE STRICT SECURITY INVOKER
        SET search_path = pg_catalog, pg_temp
        AS $function$
DECLARE
    local_date date := requested_local_at::date;
    local_time time := requested_local_at::time;
    is_holiday boolean;
BEGIN
    IF requested_direction NOT IN ('EB', 'WB') THEN
        RAISE EXCEPTION 'invalid I-66 direction';
    END IF;

    WITH years(value) AS (
        SELECT generate_series(
            extract(year FROM local_date)::integer - 1,
            extract(year FROM local_date)::integer + 1
        )
    ), holidays AS (
        SELECT holiday.value, holiday.fixed
        FROM years
        CROSS JOIN LATERAL (VALUES
            (make_date(years.value, 1, 1), true),
            (make_date(years.value, 1, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 1, 1))::integer) % 7)
                + 14, false),
            (make_date(years.value, 2, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 2, 1))::integer) % 7)
                + 14, false),
            (make_date(years.value, 6, 1)
                - ((extract(isodow FROM make_date(years.value, 6, 1))::integer + 5) % 7 + 1), false),
            (make_date(years.value, 6, 19), true),
            (make_date(years.value, 7, 4), true),
            (make_date(years.value, 9, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 9, 1))::integer) % 7), false),
            (make_date(years.value, 10, 1)
                + ((8 - extract(isodow FROM make_date(years.value, 10, 1))::integer) % 7)
                + 7, false),
            (make_date(years.value, 11, 11), true),
            (make_date(years.value, 11, 1)
                + ((11 - extract(isodow FROM make_date(years.value, 11, 1))::integer) % 7)
                + 21, false),
            (make_date(years.value, 12, 25), true)
        ) AS holiday(value, fixed)
    )
    SELECT coalesce(bool_or(
        local_date = holiday.value
        OR (holiday.fixed AND local_date = holiday.value + CASE
            WHEN extract(isodow FROM holiday.value) = 6 THEN -1
            WHEN extract(isodow FROM holiday.value) = 7 THEN 1
            ELSE 0
        END)
    ), false)
    INTO is_holiday
    FROM holidays AS holiday;

    RETURN extract(isodow FROM local_date) <= 5
       AND NOT is_holiday
       AND CASE requested_direction
            WHEN 'EB' THEN local_time >= time '05:30' AND local_time < time '09:30'
            ELSE local_time >= time '15:00' AND local_time < time '19:00'
       END;
END
$function$;

        COMMENT ON FUNCTION oracle.i66_tolling_active(text, timestamp) IS
        'VDOT I-66 Inside the Beltway weekday schedule and federal-holiday closure; source snapshot retrieved 2026-08-24 from https://www.vdot.virginia.gov/projects/major-projects/66expresslanes/faqs/';

        EXECUTE $sql$
CREATE FUNCTION oracle.get_i66_pricing_comparisons(
    requested_start_zone_id integer,
    requested_end_zone_id integer,
    requested_direction text
) RETURNS TABLE (
    evaluated_at timestamptz,
    comparison_kind text,
    comparison_offset integer,
    bin_start_at timestamptz,
    bin_end_at timestamptz,
    interval_end_at timestamptz,
    observed_at timestamptz,
    price_usd numeric,
    available boolean,
    availability_reason text,
    source_kind text,
    pricing_method text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    evaluation_at timestamptz := statement_timestamp();
BEGIN
    IF requested_start_zone_id IS NULL
       OR requested_end_zone_id IS NULL
       OR requested_direction NOT IN ('EB', 'WB')
       OR NOT EXISTS (
            SELECT 1
            FROM oracle.route_pricing_component AS component
            WHERE component.facility = 'i66'
              AND component.start_zone_id = requested_start_zone_id
              AND component.end_zone_id = requested_end_zone_id
              AND split_part(component.source_route_key, ':', 1)
                  = requested_direction
       ) THEN
        RAISE EXCEPTION 'invalid I-66 pricing component';
    END IF;

    RETURN QUERY
    WITH selected AS MATERIALIZED (
        SELECT comparison.*
        FROM pricing.i66_pricing_comparisons AS comparison
        WHERE comparison.start_zone_id = requested_start_zone_id
          AND comparison.end_zone_id = requested_end_zone_id
    ), instant_targets AS (
        SELECT
            'current'::text AS comparison_kind,
            0 AS comparison_offset,
            date_bin(
                interval '6 minutes', evaluation_at,
                timestamptz '2000-01-01 00:00:00+00'
            ) AS bin_start_at
        UNION ALL
        SELECT
            'prior_cycle',
            offset_number,
            date_bin(
                interval '6 minutes', evaluation_at,
                timestamptz '2000-01-01 00:00:00+00'
            ) - make_interval(mins => 6 * offset_number)
        FROM generate_series(1, 2) AS offsets(offset_number)
    ), week_specs AS (
        SELECT
            offset_number AS comparison_offset,
            (evaluation_at AT TIME ZONE 'America/New_York')
                - make_interval(days => 7 * offset_number) AS wall_time
        FROM generate_series(1, 3) AS offsets(offset_number)
    ), week_candidates AS (
        SELECT
            week.comparison_offset,
            week.wall_time,
            (week.wall_time AT TIME ZONE 'UTC')
                + make_interval(hours => offset_number) AS candidate_at
        FROM week_specs AS week
        CROSS JOIN generate_series(-14, 14) AS offsets(offset_number)
    ), week_targets AS (
        SELECT
            'prior_week'::text AS comparison_kind,
            candidate.comparison_offset,
            date_bin(
                interval '6 minutes', min(candidate.candidate_at),
                timestamptz '2000-01-01 00:00:00+00'
            ) AS bin_start_at
        FROM week_candidates AS candidate
        WHERE candidate.candidate_at AT TIME ZONE 'America/New_York'
              = candidate.wall_time
        GROUP BY candidate.comparison_offset
        HAVING count(*) = 1
    ), targets AS MATERIALIZED (
        SELECT
            target.*,
            oracle.i66_tolling_active(
                requested_direction,
                CASE target.comparison_kind
                    WHEN 'current' THEN
                        evaluation_at AT TIME ZONE 'America/New_York'
                    ELSE target.bin_start_at AT TIME ZONE 'America/New_York'
                END
            ) AS tolling_active
        FROM (
            SELECT * FROM instant_targets
            UNION ALL
            SELECT * FROM week_targets
        ) AS target
    ), observed AS (
        SELECT
            comparison.evaluated_at,
            target.comparison_kind,
            target.comparison_offset,
            comparison.bin_start_at,
            comparison.bin_end_at,
            comparison.interval_end_at,
            comparison.observed_at,
            comparison.price_usd,
            comparison.available,
            comparison.availability_reason,
            comparison.source_kind,
            comparison.pricing_method
        FROM targets AS target
        JOIN selected AS comparison
          ON comparison.comparison_kind = target.comparison_kind
         AND comparison.comparison_offset = target.comparison_offset
         AND (
              target.comparison_kind = 'current'
              OR comparison.bin_start_at = target.bin_start_at
         )
        WHERE target.tolling_active
    ), scheduled AS (
        SELECT
            evaluation_at,
            target.comparison_kind,
            target.comparison_offset,
            target.bin_start_at,
            target.bin_start_at + interval '6 minutes',
            NULL::timestamptz,
            NULL::timestamptz,
            0::numeric,
            true,
            NULL::text,
            'schedule_derived'::text,
            'published_schedule'::text
        FROM targets AS target
        WHERE NOT target.tolling_active
    ), diagnostic AS (
        SELECT
            evaluation_at,
            'current'::text,
            0,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::numeric,
            false,
            'missing_observation'::text,
            NULL::text,
            NULL::text
        FROM targets AS target
        WHERE target.comparison_kind = 'current'
          AND target.tolling_active
          AND NOT EXISTS (
              SELECT 1 FROM observed WHERE observed.comparison_kind = 'current'
          )
    ), combined AS (
        SELECT * FROM observed
        UNION ALL
        SELECT * FROM scheduled
        UNION ALL
        SELECT * FROM diagnostic
    )
    SELECT * FROM combined
    ORDER BY
        CASE combined.comparison_kind
            WHEN 'current' THEN 0
            WHEN 'prior_cycle' THEN 1
            ELSE 2
        END,
        combined.comparison_offset;
END
$function$;
$sql$;
    END IF;

END
$migration$;

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) = '1.11.0' THEN
        CREATE FUNCTION oracle.get_i66_ballpark_samples(
            requested_start_zone_id integer,
            requested_end_zone_id integer,
            requested_direction text,
            requested_local_time time,
            requested_dates date[],
            requested_evaluated_at timestamptz
        ) RETURNS TABLE (
            sample_date date,
            sample_isodow integer,
            bin_start_at timestamptz,
            bin_end_at timestamptz,
            interval_end_at timestamptz,
            observed_at timestamptz,
            start_zone_id integer,
            end_zone_id integer,
            price_usd numeric,
            uses_modeled boolean,
            pricing_method text
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $function$
BEGIN
    IF requested_start_zone_id IS NULL
       OR requested_end_zone_id IS NULL
       OR requested_direction NOT IN ('EB', 'WB')
       OR NOT EXISTS (
            SELECT 1
            FROM oracle.route_pricing_component AS component
            WHERE component.facility = 'i66'
              AND component.start_zone_id = requested_start_zone_id
              AND component.end_zone_id = requested_end_zone_id
              AND split_part(component.source_route_key, ':', 1)
                  = requested_direction
       ) THEN
        RAISE EXCEPTION 'invalid I-66 ballpark component';
    END IF;
    PERFORM oracle.validate_ballpark_sample_request(
        requested_local_time, requested_dates, requested_evaluated_at
    );

    RETURN QUERY
    WITH local_targets AS (
        SELECT
            requested_date.value AS target_date,
            requested_date.value + requested_local_time AS wall_time
        FROM unnest(requested_dates) AS requested_date(value)
    ), instant_candidates AS (
        SELECT
            target.target_date,
            target.wall_time,
            (target.wall_time AT TIME ZONE 'UTC')
                + make_interval(hours => offset_number) AS candidate_at
        FROM local_targets AS target
        CROSS JOIN generate_series(-14, 14) AS offsets(offset_number)
    ), resolved_targets AS (
        SELECT
            candidate.target_date,
            min(candidate.candidate_at) AS target_at
        FROM instant_candidates AS candidate
        WHERE candidate.candidate_at AT TIME ZONE 'America/New_York'
              = candidate.wall_time
        GROUP BY candidate.target_date
        HAVING count(*) = 1
    ), targets AS (
        SELECT
            resolved.target_date,
            date_bin(
                interval '6 minutes', resolved.target_at,
                timestamptz '2000-01-01 00:00:00+00'
            ) AS target_bin_start_at,
            oracle.i66_tolling_active(
                requested_direction,
                resolved.target_at AT TIME ZONE 'America/New_York'
            ) AS tolling_active
        FROM resolved_targets AS resolved
    ), candidates AS (
        SELECT
            sample.*,
            row_number() OVER (
                PARTITION BY sample.sample_date
                ORDER BY sample.interval_end_at DESC, sample.observed_at DESC
            ) AS candidate_rank
        FROM targets AS target
        JOIN pricing.i66_ballpark_samples AS sample
          ON sample.sample_date = target.target_date
         AND sample.interval_end_at >= target.target_bin_start_at
         AND sample.interval_end_at
             < target.target_bin_start_at + interval '6 minutes'
        WHERE sample.start_zone_id = requested_start_zone_id
          AND sample.end_zone_id = requested_end_zone_id
          AND target.tolling_active
          AND sample.interval_end_at <= requested_evaluated_at
          AND sample.observed_at <= requested_evaluated_at
    ), chosen AS (
        SELECT
            candidate.sample_date,
            candidate.sample_isodow,
            candidate.bin_start_at,
            candidate.bin_end_at,
            candidate.interval_end_at,
            candidate.observed_at,
            candidate.start_zone_id,
            candidate.end_zone_id,
            candidate.price_usd,
            candidate.uses_modeled,
            candidate.pricing_method
        FROM candidates AS candidate
        WHERE candidate.candidate_rank = 1

        UNION ALL

        SELECT
            target.target_date,
            extract(isodow FROM target.target_date)::integer,
            target.target_bin_start_at,
            target.target_bin_start_at + interval '6 minutes',
            target.target_bin_start_at,
            NULL::timestamptz,
            requested_start_zone_id,
            requested_end_zone_id,
            0::numeric,
            false,
            'published_schedule'::text
        FROM targets AS target
        WHERE NOT target.tolling_active
    )
    SELECT
        chosen.sample_date,
        chosen.sample_isodow,
        chosen.bin_start_at,
        chosen.bin_end_at,
        chosen.interval_end_at,
        chosen.observed_at,
        chosen.start_zone_id,
        chosen.end_zone_id,
        chosen.price_usd,
        chosen.uses_modeled,
        chosen.pricing_method
    FROM chosen
    ORDER BY chosen.sample_date;
END
$function$;

        CREATE OR REPLACE FUNCTION oracle.get_i66_ballpark_samples(
            requested_start_zone_id integer,
            requested_end_zone_id integer,
            requested_local_time time,
            requested_dates date[],
            requested_evaluated_at timestamptz
        ) RETURNS TABLE (
            sample_date date,
            sample_isodow integer,
            bin_start_at timestamptz,
            bin_end_at timestamptz,
            interval_end_at timestamptz,
            observed_at timestamptz,
            start_zone_id integer,
            end_zone_id integer,
            price_usd numeric,
            uses_modeled boolean,
            pricing_method text
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $function$
DECLARE
    canonical_direction text;
BEGIN
    SELECT min(split_part(component.source_route_key, ':', 1))
    INTO canonical_direction
    FROM oracle.route_pricing_component AS component
    WHERE component.facility = 'i66'
      AND component.start_zone_id = requested_start_zone_id
      AND component.end_zone_id = requested_end_zone_id
    HAVING count(DISTINCT split_part(component.source_route_key, ':', 1)) = 1;

    IF canonical_direction IS NULL THEN
        RAISE EXCEPTION 'invalid I-66 ballpark component';
    END IF;

    RETURN QUERY SELECT *
    FROM oracle.get_i66_ballpark_samples(
        requested_start_zone_id,
        requested_end_zone_id,
        canonical_direction,
        requested_local_time,
        requested_dates,
        requested_evaluated_at
    );
END
$function$;

        ALTER FUNCTION oracle.i66_tolling_active(text, timestamp)
        OWNER TO oracle_owner;
        ALTER FUNCTION oracle.get_i66_pricing_comparisons(integer, integer, text)
        OWNER TO oracle_owner;
        ALTER FUNCTION oracle.get_i66_ballpark_samples(
            integer, integer, text, time, date[], timestamptz
        ) OWNER TO oracle_owner;
        REVOKE ALL ON FUNCTION oracle.i66_tolling_active(text, timestamp) FROM PUBLIC;
        REVOKE ALL ON FUNCTION oracle.get_i66_pricing_comparisons(
            integer, integer, text
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION oracle.get_i66_ballpark_samples(
            integer, integer, text, time, date[], timestamptz
        ) FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION oracle.get_i66_ballpark_samples(
            integer, integer, time, date[], timestamptz
        ) FROM pricing_caller;
        GRANT EXECUTE ON FUNCTION oracle.get_i66_pricing_comparisons(
            integer, integer, text
        ) TO pricing_caller;
        GRANT EXECUTE ON FUNCTION oracle.get_i66_ballpark_samples(
            integer, integer, text, time, date[], timestamptz
        ) TO pricing_caller;
    END IF;
END
$migration$;

UPDATE oracle.schema_version
SET version = '1.12.0', installed_at = statement_timestamp()
WHERE singleton AND version = '1.11.0';

DO $postcheck$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.12.0'
       OR to_regprocedure(
            'oracle.get_i66_pricing_comparisons(integer,integer,text)'
       ) IS NULL
       OR to_regprocedure(
            'oracle.get_i66_ballpark_samples(integer,integer,text,time without time zone,date[],timestamp with time zone)'
       ) IS NULL
       OR to_regprocedure(
            'oracle.get_i66_pricing_comparisons(integer,integer)'
       ) IS NULL THEN
        RAISE EXCEPTION 'oracle schema did not advance cleanly to 1.12.0';
    END IF;
    IF NOT has_function_privilege(
        'pricing_caller',
        'oracle.get_i66_pricing_comparisons(integer,integer,text)',
        'EXECUTE'
    ) OR NOT has_function_privilege(
        'pricing_caller',
        'oracle.get_i66_pricing_comparisons(integer,integer)',
        'EXECUTE'
    ) OR has_function_privilege(
        'pricing_caller',
        'oracle.get_i66_ballpark_samples(integer,integer,time,date[],timestamptz)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'I-66 Oracle function privileges are invalid';
    END IF;
END
$postcheck$;

COMMIT;

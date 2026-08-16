-- Shared dynamic-pricing analysis surfaces. Included by the blank bootstrap
-- and the additive online migration after the raw tables/current views exist.

CREATE OR REPLACE VIEW current_i95_direction AS
WITH sources AS (
    SELECT
        max(corridor_name) FILTER (WHERE od_pair_id = 1132) AS northbound_corridor_name,
        max(link_status) FILTER (WHERE od_pair_id = 1132) AS northbound_link_status,
        max(interval_end_at) FILTER (WHERE od_pair_id = 1132) AS northbound_interval_end_at,
        max(calculated_at) FILTER (WHERE od_pair_id = 1132) AS northbound_calculated_at,
        max(corridor_name) FILTER (WHERE od_pair_id = 1151) AS southbound_corridor_name,
        max(link_status) FILTER (WHERE od_pair_id = 1151) AS southbound_link_status,
        max(interval_end_at) FILTER (WHERE od_pair_id = 1151) AS southbound_interval_end_at,
        max(calculated_at) FILTER (WHERE od_pair_id = 1151) AS southbound_calculated_at
    FROM current_trip_pricing_i95
    WHERE od_pair_id IN (1132, 1151)
), classified AS (
    SELECT
        sources.*,
        CASE
            WHEN northbound_interval_end_at IS NULL OR southbound_interval_end_at IS NULL
                THEN 'missing_source'
            WHEN northbound_corridor_name <> 'I-95-NB' OR southbound_corridor_name <> 'I-95-SB'
                THEN 'invalid_source'
            WHEN northbound_interval_end_at <> southbound_interval_end_at
                THEN 'interval_mismatch'
            WHEN (northbound_link_status = 'NORTHBOUND_OPEN')
              <> (southbound_link_status = 'SOUTHBOUND_OPEN')
                THEN 'available'
            ELSE 'indeterminate'
        END AS direction_state
    FROM sources
)
SELECT
    CASE
        WHEN direction_state = 'available' AND northbound_link_status = 'NORTHBOUND_OPEN'
            THEN 'Northbound'
        WHEN direction_state = 'available' THEN 'Southbound'
    END AS direction,
    direction_state,
    CASE WHEN direction_state = 'available' THEN northbound_interval_end_at END AS interval_end_at,
    northbound_corridor_name,
    northbound_link_status,
    northbound_interval_end_at,
    northbound_calculated_at,
    southbound_corridor_name,
    southbound_link_status,
    southbound_interval_end_at,
    southbound_calculated_at
FROM classified;

CREATE OR REPLACE VIEW i95_modeled_od_proxy AS
SELECT *
FROM (
    VALUES
        (1374, 1146, 'NORTHBOUND_OPEN'),
        (1375, 1263, 'NORTHBOUND_OPEN'),
        (1376, 1264, 'NORTHBOUND_OPEN'),
        (1377, 1265, 'NORTHBOUND_OPEN'),
        (1378, 1158, 'SOUTHBOUND_OPEN'),
        (1379, 1159, 'SOUTHBOUND_OPEN'),
        (1380, 1160, 'SOUTHBOUND_OPEN'),
        (1381, 1161, 'SOUTHBOUND_OPEN'),
        (1382, 1162, 'SOUTHBOUND_OPEN'),
        (1383, 1163, 'SOUTHBOUND_OPEN'),
        (1384, 1164, 'SOUTHBOUND_OPEN'),
        (1385, 1165, 'SOUTHBOUND_OPEN'),
        (1386, 1166, 'SOUTHBOUND_OPEN'),
        (1387, 1167, 'SOUTHBOUND_OPEN'),
        (1388, 1288, 'SOUTHBOUND_OPEN'),
        (1389, 1315, 'SOUTHBOUND_OPEN')
) AS proxy (target_od_pair_id, proxy_od_pair_id, required_status);

CREATE OR REPLACE VIEW modeled_trip_pricing_i95 AS
SELECT
    p.target_od_pair_id AS od_pair_id,
    v.corridor_name,
    CASE WHEN v.link_status = p.required_status THEN v.zone_toll_rate_usd END AS zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    v.link_status,
    p.proxy_od_pair_id,
    true AS modeled,
    'identity_proxy_v1'::text AS pricing_method,
    v.start_zone_id,
    v.end_zone_id
FROM i95_modeled_od_proxy p
JOIN trip_pricing_i95 v ON v.od_pair_id = p.proxy_od_pair_id;

CREATE OR REPLACE VIEW modeled_current_trip_pricing_i95 AS
SELECT
    p.target_od_pair_id AS od_pair_id,
    v.corridor_name,
    v.zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    v.link_status,
    p.proxy_od_pair_id,
    true AS modeled,
    'identity_proxy_v1'::text AS pricing_method
FROM i95_modeled_od_proxy p
JOIN current_trip_pricing_i95 v
  ON v.od_pair_id = p.proxy_od_pair_id
 AND v.link_status = p.required_status;

CREATE OR REPLACE VIEW dynamic_pricing_observations AS
SELECT
    'i95_observed'::text AS price_source,
    'observed'::text AS source_kind,
    v.od_pair_id,
    NULL::integer AS start_zone_id,
    NULL::integer AS end_zone_id,
    v.corridor_name,
    CASE
        WHEN v.corridor_name = 'I-95-NB' AND v.link_status = 'NORTHBOUND_OPEN' THEN v.zone_toll_rate_usd
        WHEN v.corridor_name = 'I-95-SB' AND v.link_status = 'SOUTHBOUND_OPEN' THEN v.zone_toll_rate_usd
        WHEN v.corridor_name IN ('I-495-NB', 'I-495-SB') THEN v.zone_toll_rate_usd
    END AS price_usd,
    v.interval_end_at,
    v.calculated_at AS observed_at,
    v.link_status AS source_status,
    CASE
        WHEN v.corridor_name = 'I-95-NB' THEN v.link_status = 'NORTHBOUND_OPEN'
        WHEN v.corridor_name = 'I-95-SB' THEN v.link_status = 'SOUTHBOUND_OPEN'
        WHEN v.corridor_name IN ('I-495-NB', 'I-495-SB') THEN true
        ELSE false
    END AS available,
    'source_observation'::text AS pricing_method,
    NULL::integer AS proxy_od_pair_id,
    v.start_zone_id AS source_start_zone_id,
    v.end_zone_id AS source_end_zone_id
FROM trip_pricing_i95 v
UNION ALL
SELECT
    'i95_modeled',
    'modeled',
    v.od_pair_id,
    NULL::integer,
    NULL::integer,
    v.corridor_name,
    v.zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    v.link_status,
    v.zone_toll_rate_usd IS NOT NULL,
    v.pricing_method,
    v.proxy_od_pair_id,
    v.start_zone_id,
    v.end_zone_id
FROM modeled_trip_pricing_i95 v
UNION ALL
SELECT
    'i66_observed',
    'observed',
    NULL::integer,
    v.start_zone_id,
    v.end_zone_id,
    v.corridor_name,
    v.zone_toll_rate_usd,
    v.interval_end_at,
    v.calculated_at,
    NULL::text,
    true,
    'source_observation',
    NULL::integer,
    v.start_zone_id,
    v.end_zone_id
FROM trip_pricing_i66 v;

CREATE OR REPLACE FUNCTION _dynamic_pricing_component_errors(p_components jsonb)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
SET search_path = public, pg_catalog, pg_temp
AS $$
DECLARE
    component jsonb;
    step_id text;
    source text;
    seen_steps text[] := ARRAY[]::text[];
    errors jsonb := '[]'::jsonb;
BEGIN
    IF p_components IS NULL OR jsonb_typeof(p_components) <> 'array' THEN
        RETURN '[{"field":"components","reason":"must_be_array"}]'::jsonb;
    END IF;
    IF pg_column_size(p_components) > 65536 THEN
        RETURN '[{"field":"components","reason":"too_large","maximum_bytes":65536}]'::jsonb;
    END IF;
    IF jsonb_array_length(p_components) > 16 THEN
        RETURN '[{"field":"components","reason":"too_many_components","maximum":16}]'::jsonb;
    END IF;

    FOR component IN SELECT value FROM jsonb_array_elements(p_components)
    LOOP
        IF jsonb_typeof(component) <> 'object' THEN
            errors := errors || jsonb_build_array(jsonb_build_object(
                'field', 'components', 'reason', 'component_must_be_object'
            ));
            CONTINUE;
        END IF;
        step_id := component->>'route_step_id';
        source := component->>'price_source';
        IF jsonb_typeof(component->'route_step_id') IS DISTINCT FROM 'string'
           OR step_id IS NULL OR btrim(step_id) = '' THEN
            errors := errors || '[{"field":"route_step_id","reason":"required"}]'::jsonb;
        ELSIF length(step_id) > 128 THEN
            errors := errors || jsonb_build_array(jsonb_build_object(
                'field', 'route_step_id', 'reason', 'too_long', 'maximum', 128
            ));
        ELSIF step_id = ANY(seen_steps) THEN
            errors := errors || jsonb_build_array(jsonb_build_object(
                'field', 'route_step_id', 'reason', 'duplicate', 'value', step_id
            ));
        ELSE
            seen_steps := array_append(seen_steps, step_id);
        END IF;

        IF jsonb_typeof(component->'price_source') IS DISTINCT FROM 'string' THEN
            errors := errors || jsonb_build_array(jsonb_build_object(
                'field', coalesce(step_id, 'price_source'), 'reason', 'unsupported_price_source'
            ));
        ELSIF source IN ('i95_observed', 'i95_modeled') THEN
            IF component - ARRAY['route_step_id', 'price_source', 'od_pair_id'] <> '{}'::jsonb
               OR jsonb_typeof(component->'od_pair_id') IS DISTINCT FROM 'number'
               OR (component->>'od_pair_id') IS NULL
               OR (component->>'od_pair_id') !~ '^[1-9][0-9]*$'
               OR length(component->>'od_pair_id') > 10
               OR (length(component->>'od_pair_id') = 10
                   AND component->>'od_pair_id' > '2147483647') THEN
                errors := errors || jsonb_build_array(jsonb_build_object(
                    'field', coalesce(step_id, 'components'), 'reason', 'invalid_i95_component'
                ));
            END IF;
        ELSIF source = 'i66_observed' THEN
            IF component - ARRAY['route_step_id', 'price_source', 'start_zone_id', 'end_zone_id'] <> '{}'::jsonb
               OR jsonb_typeof(component->'start_zone_id') IS DISTINCT FROM 'number'
               OR jsonb_typeof(component->'end_zone_id') IS DISTINCT FROM 'number'
               OR (component->>'start_zone_id') IS NULL
               OR (component->>'end_zone_id') IS NULL
               OR (component->>'start_zone_id') !~ '^[1-9][0-9]*$'
               OR (component->>'end_zone_id') !~ '^[1-9][0-9]*$'
               OR length(component->>'start_zone_id') > 10
               OR length(component->>'end_zone_id') > 10
               OR (length(component->>'start_zone_id') = 10
                   AND component->>'start_zone_id' > '2147483647')
               OR (length(component->>'end_zone_id') = 10
                   AND component->>'end_zone_id' > '2147483647') THEN
                errors := errors || jsonb_build_array(jsonb_build_object(
                    'field', coalesce(step_id, 'components'), 'reason', 'invalid_i66_component'
                ));
            END IF;
        ELSE
            errors := errors || jsonb_build_array(jsonb_build_object(
                'field', coalesce(step_id, 'price_source'), 'reason', 'unsupported_price_source'
            ));
        END IF;
    END LOOP;
    RETURN errors;
END;
$$;

CREATE OR REPLACE FUNCTION point_in_time_dynamic_route_pricing(
    p_requested_at timestamptz,
    p_components jsonb
) RETURNS TABLE (
    requested_at timestamptz,
    evaluated_at timestamptz,
    complete boolean,
    reason text,
    total_usd numeric,
    components jsonb,
    unavailable_components jsonb,
    invalid_fields jsonb
)
LANGUAGE plpgsql
VOLATILE
SET search_path = public, pg_catalog, pg_temp
AS $$
DECLARE
    validation_errors jsonb;
BEGIN
    requested_at := p_requested_at;
    evaluated_at := clock_timestamp();
    complete := false;
    total_usd := NULL;
    components := '[]'::jsonb;
    unavailable_components := '[]'::jsonb;
    invalid_fields := '[]'::jsonb;

    validation_errors := _dynamic_pricing_component_errors(p_components);
    IF p_requested_at IS NULL THEN
        validation_errors := validation_errors || '[{"field":"requested_at","reason":"required"}]'::jsonb;
    ELSIF NOT isfinite(p_requested_at) THEN
        validation_errors := validation_errors || '[{"field":"requested_at","reason":"must_be_finite"}]'::jsonb;
    END IF;
    IF validation_errors <> '[]'::jsonb THEN
        reason := 'invalid_request';
        invalid_fields := validation_errors;
        RETURN NEXT;
        RETURN;
    END IF;
    IF p_requested_at > evaluated_at THEN
        reason := 'future_requested_at';
        RETURN NEXT;
        RETURN;
    END IF;
    IF jsonb_array_length(p_components) = 0 THEN
        complete := true;
        total_usd := 0.00;
        reason := NULL;
        RETURN NEXT;
        RETURN;
    END IF;

    WITH requested_components AS (
        SELECT
            ordinality::integer AS component_order,
            value->>'route_step_id' AS route_step_id,
            value->>'price_source' AS price_source,
            CASE WHEN value ? 'od_pair_id' THEN (value->>'od_pair_id')::integer END AS od_pair_id,
            CASE WHEN value ? 'start_zone_id' THEN (value->>'start_zone_id')::integer END AS start_zone_id,
            CASE WHEN value ? 'end_zone_id' THEN (value->>'end_zone_id')::integer END AS end_zone_id
        FROM jsonb_array_elements(p_components) WITH ORDINALITY
    ), selected AS (
        SELECT requested_components.*, observation.*
        FROM requested_components
        LEFT JOIN LATERAL (
            SELECT candidate.*
            FROM dynamic_pricing_observations candidate
            WHERE candidate.price_source = requested_components.price_source
              AND (requested_components.od_pair_id IS NULL OR candidate.od_pair_id = requested_components.od_pair_id)
              AND (requested_components.start_zone_id IS NULL OR candidate.start_zone_id = requested_components.start_zone_id)
              AND (requested_components.end_zone_id IS NULL OR candidate.end_zone_id = requested_components.end_zone_id)
              AND candidate.interval_end_at <= p_requested_at
              AND candidate.observed_at <= p_requested_at
            ORDER BY candidate.interval_end_at DESC, candidate.observed_at DESC,
                     candidate.source_start_zone_id, candidate.source_end_zone_id
            LIMIT 1
        ) observation ON true
    ), classified AS (
        SELECT selected.*,
            CASE
                WHEN selected.interval_end_at IS NULL THEN 'missing_observation'
                WHEN NOT selected.available THEN 'facility_unavailable'
                WHEN p_requested_at - selected.observed_at > interval '30 minutes' THEN 'stale_observation'
            END AS unavailable_reason
        FROM selected
    ), aggregate_result AS (
        SELECT
            bool_and(unavailable_reason IS NULL) AS all_complete,
            sum(price_usd) FILTER (WHERE unavailable_reason IS NULL) AS available_total,
            coalesce(jsonb_agg(
                jsonb_strip_nulls(jsonb_build_object(
                    'route_step_id', route_step_id,
                    'price_usd', price_usd::text,
                    'source_kind', source_kind,
                    'pricing_method', pricing_method,
                    'proxy_od_pair_id', proxy_od_pair_id,
                    'priced_as_of', interval_end_at,
                    'observed_at', observed_at,
                    'source_status', source_status
                )) ORDER BY component_order
            ) FILTER (WHERE unavailable_reason IS NULL), '[]'::jsonb) AS available_components,
            coalesce(jsonb_agg(
                jsonb_strip_nulls(jsonb_build_object(
                    'route_step_id', route_step_id,
                    'reason', unavailable_reason,
                    'latest_observation_at', observed_at,
                    'source_status', source_status
                )) ORDER BY component_order
            ) FILTER (WHERE unavailable_reason IS NOT NULL), '[]'::jsonb) AS failures
        FROM classified
    )
    SELECT
        all_complete,
        CASE WHEN all_complete THEN available_total END,
        CASE WHEN all_complete THEN available_components ELSE '[]'::jsonb END,
        failures
    INTO complete, total_usd, components, unavailable_components
    FROM aggregate_result;

    reason := CASE WHEN complete THEN NULL ELSE 'incomplete_route_price' END;
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION historical_dynamic_route_pricing(
    p_requested_at timestamptz,
    p_components jsonb
) RETURNS TABLE (
    requested_at timestamptz,
    slot_start timestamptz,
    window_start timestamptz,
    window_end timestamptz,
    reason text,
    comparable_period_count integer,
    expected_comparable_period_count integer,
    comparable_totals jsonb,
    mean_usd numeric,
    median_usd numeric,
    minimum_usd numeric,
    maximum_usd numeric,
    latest_observation_at timestamptz,
    component_sources jsonb,
    contains_modeled boolean,
    invalid_fields jsonb
)
LANGUAGE plpgsql
VOLATILE
SET search_path = public, pg_catalog, pg_temp
AS $$
DECLARE
    validation_errors jsonb;
    local_slot timestamp;
BEGIN
    requested_at := p_requested_at;
    expected_comparable_period_count := 0;
    comparable_period_count := 0;
    comparable_totals := '[]'::jsonb;
    component_sources := '[]'::jsonb;
    contains_modeled := false;
    invalid_fields := '[]'::jsonb;

    validation_errors := _dynamic_pricing_component_errors(p_components);
    IF p_requested_at IS NULL THEN
        validation_errors := validation_errors || '[{"field":"requested_at","reason":"required"}]'::jsonb;
    ELSIF NOT isfinite(p_requested_at) THEN
        validation_errors := validation_errors || '[{"field":"requested_at","reason":"must_be_finite"}]'::jsonb;
    END IF;
    IF validation_errors <> '[]'::jsonb THEN
        reason := 'invalid_request';
        invalid_fields := validation_errors;
        RETURN NEXT;
        RETURN;
    END IF;
    IF jsonb_array_length(p_components) = 0 THEN
        reason := 'invalid_request';
        invalid_fields := '[{"field":"components","reason":"must_not_be_empty"}]'::jsonb;
        RETURN NEXT;
        RETURN;
    END IF;

    slot_start := date_bin(
        interval '15 minutes',
        p_requested_at,
        timestamptz '2000-01-01 00:00:00+00'
    );
    local_slot := slot_start AT TIME ZONE 'America/New_York';
    window_start := (local_slot - interval '28 days') AT TIME ZONE 'America/New_York';
    window_end := slot_start;

    WITH requested_components AS (
        SELECT
            ordinality::integer AS component_order,
            value->>'route_step_id' AS route_step_id,
            value->>'price_source' AS price_source,
            CASE WHEN value ? 'od_pair_id' THEN (value->>'od_pair_id')::integer END AS od_pair_id,
            CASE WHEN value ? 'start_zone_id' THEN (value->>'start_zone_id')::integer END AS start_zone_id,
            CASE WHEN value ? 'end_zone_id' THEN (value->>'end_zone_id')::integer END AS end_zone_id
        FROM jsonb_array_elements(p_components) WITH ORDINALITY
    ), candidate_slots AS (
        SELECT
            week_number,
            local_slot - make_interval(days => 7 * week_number) AS local_departure,
            (local_slot - make_interval(days => 7 * week_number)) AT TIME ZONE 'America/New_York' AS departure_at
        FROM generate_series(1, 4) AS weeks(week_number)
    ), valid_slots AS (
        SELECT *,
            departure_at AT TIME ZONE 'America/New_York' = local_departure AS valid_local_time
        FROM candidate_slots
    ), slot_coverage AS (
        SELECT count(*) FILTER (WHERE valid_local_time)::integer AS expected_count
        FROM valid_slots
    ), selected AS (
        SELECT valid_slots.week_number, valid_slots.departure_at,
               valid_slots.valid_local_time, requested_components.*, observation.*
        FROM valid_slots
        CROSS JOIN requested_components
        LEFT JOIN LATERAL (
            SELECT candidate.*
            FROM dynamic_pricing_observations candidate
            WHERE valid_slots.valid_local_time
              AND candidate.price_source = requested_components.price_source
              AND (requested_components.od_pair_id IS NULL OR candidate.od_pair_id = requested_components.od_pair_id)
              AND (requested_components.start_zone_id IS NULL OR candidate.start_zone_id = requested_components.start_zone_id)
              AND (requested_components.end_zone_id IS NULL OR candidate.end_zone_id = requested_components.end_zone_id)
              AND candidate.interval_end_at >= valid_slots.departure_at
              AND candidate.interval_end_at < valid_slots.departure_at + interval '15 minutes'
            ORDER BY candidate.interval_end_at DESC, candidate.observed_at DESC,
                     candidate.source_start_zone_id, candidate.source_end_zone_id
            LIMIT 1
        ) observation ON true
    ), periods AS (
        SELECT
            week_number,
            departure_at,
            count(*) FILTER (WHERE interval_end_at IS NOT NULL) = count(*)
              AND bool_and(coalesce(available, false)) AS period_complete,
            sum(price_usd) AS period_total,
            max(observed_at) AS period_latest_observation,
            bool_or(source_kind = 'modeled') AS period_contains_modeled
        FROM selected
        GROUP BY week_number, departure_at, valid_local_time
        HAVING bool_and(valid_local_time)
    ), complete_periods AS (
        SELECT * FROM periods WHERE period_complete
    ), stats AS (
        SELECT
            count(*)::integer AS period_count,
            avg(period_total) AS average_total,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY period_total) AS median_total,
            min(period_total) AS minimum_total,
            max(period_total) AS maximum_total,
            max(period_latest_observation) AS newest_observation,
            coalesce(bool_or(period_contains_modeled), false) AS any_modeled,
            coalesce(jsonb_agg(jsonb_build_object(
                'departure_at', departure_at,
                'total_usd', period_total::text
            ) ORDER BY departure_at), '[]'::jsonb) AS totals
        FROM complete_periods
    ), sources AS (
        SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
            'route_step_id', requested_components.route_step_id,
            'source_kind', CASE WHEN requested_components.price_source = 'i95_modeled' THEN 'modeled' ELSE 'observed' END,
            'pricing_method', CASE WHEN requested_components.price_source = 'i95_modeled' THEN 'identity_proxy_v1' ELSE 'source_observation' END,
            'proxy_od_pair_id', proxy.proxy_od_pair_id
        )) ORDER BY requested_components.component_order) AS value
        FROM requested_components
        LEFT JOIN i95_modeled_od_proxy proxy
          ON requested_components.price_source = 'i95_modeled'
         AND proxy.target_od_pair_id = requested_components.od_pair_id
    )
    SELECT
        stats.period_count,
        stats.totals,
        stats.average_total,
        stats.median_total,
        stats.minimum_total,
        stats.maximum_total,
        stats.newest_observation,
        sources.value,
        stats.any_modeled,
        slot_coverage.expected_count
    INTO comparable_period_count, comparable_totals, mean_usd, median_usd,
         minimum_usd, maximum_usd, latest_observation_at, component_sources,
         contains_modeled, expected_comparable_period_count
    FROM stats CROSS JOIN sources CROSS JOIN slot_coverage;

    reason := CASE WHEN comparable_period_count = 0 THEN 'insufficient_recent_history' END;
    RETURN NEXT;
END;
$$;

COMMENT ON VIEW i95_modeled_od_proxy IS
    'Validated VDOT proxy products for 16 I-95 oracle OD IDs absent from VDOT history';
COMMENT ON VIEW modeled_trip_pricing_i95 IS
    'Direction-compatible historical ballpark prices for oracle-only I-95 OD IDs';
COMMENT ON VIEW modeled_current_trip_pricing_i95 IS
    'Direction-compatible current ballpark prices for oracle-only I-95 OD IDs';
COMMENT ON VIEW current_i95_direction IS
    'Latest known I-95 reversible direction from OD 1132/1151, with fail-safe diagnostic state';
COMMENT ON VIEW dynamic_pricing_observations IS
    'Normalized observed and modeled dynamic toll observations with availability applied after selection';
COMMENT ON FUNCTION point_in_time_dynamic_route_pricing(timestamptz, jsonb) IS
    'Complete dynamic route subtotal at one instant; schedule-derived components remain caller-owned';
COMMENT ON FUNCTION historical_dynamic_route_pricing(timestamptz, jsonb) IS
    'Complete dynamic route totals and statistics for four prior matching Eastern 15-minute slots';

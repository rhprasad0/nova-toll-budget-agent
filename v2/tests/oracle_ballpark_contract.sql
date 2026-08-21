\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
    sample_day date := (
        SELECT max(day::date)
        FROM generate_series(
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 7,
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 1,
            interval '1 day'
        ) AS days(day)
        WHERE extract(isodow FROM day) = 3
    );
    older_at timestamptz := (sample_day + time '08:01') AT TIME ZONE 'America/New_York';
    newer_at timestamptz := (sample_day + time '08:05') AT TIME ZONE 'America/New_York';
BEGIN
    INSERT INTO pricing.trip_pricing_i66 (
        interval_start_at, interval_end_at, calculated_at, corridor_id,
        corridor_name, start_zone_id, start_zone_name, end_zone_id,
        end_zone_name, zone_toll_rate_usd, s3_key
    ) VALUES
        (older_at - interval '1 minute', older_at, older_at, 66, 'I-66-EB',
         3100, 'A', 3110, 'B', 4.00, 'test/oracle-ballpark-i66-old.csv'),
        (newer_at - interval '1 minute', newer_at, newer_at, 66, 'I-66-EB',
         3100, 'A', 3110, 'B', 5.00, 'test/oracle-ballpark-i66-new.csv');

    INSERT INTO pricing.trip_pricing_i95 (
        interval_end_at, current_at, calculated_at, corridor_id,
        corridor_name, od_pair_id, od_pair_name, start_zone_id,
        start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
        link_status, s3_key
    ) VALUES
        (older_at, older_at, older_at, 95, 'I-95-NB', 1132,
         'NB sentinel', 1, 'A', 2, 'B', 0, 'NORTHBOUND_OPEN',
         'test/oracle-ballpark-nb-old.csv'),
        (older_at, older_at, older_at, 95, 'I-95-SB', 1151,
         'SB sentinel', 3, 'C', 4, 'D', 0, 'CLOSED',
         'test/oracle-ballpark-sb-old.csv'),
        (newer_at, newer_at, newer_at, 95, 'I-95-NB', 1132,
         'NB sentinel', 1, 'A', 2, 'B', 0, 'NORTHBOUND_OPEN',
         'test/oracle-ballpark-nb-new.csv'),
        (newer_at, newer_at, newer_at, 95, 'I-95-SB', 1151,
         'SB sentinel', 3, 'C', 4, 'D', 0, 'CLOSED',
         'test/oracle-ballpark-sb-new.csv'),
        (older_at, older_at, older_at, 95, 'I-95-NB', 1374,
         'Observed target', 10, 'E', 11, 'F', 7.00, 'NORTHBOUND_OPEN',
         'test/oracle-ballpark-observed.csv'),
        (older_at, older_at, older_at, 95, 'I-95-NB', 1146,
         'Proxy target', 12, 'G', 13, 'H', 6.00, 'NORTHBOUND_OPEN',
         'test/oracle-ballpark-proxy.csv'),
        (older_at, older_at, older_at, 95, 'I-95-NB', 5002,
         'Older valid', 20, 'I', 21, 'J', 8.00, 'NORTHBOUND_OPEN',
         'test/oracle-ballpark-valid.csv'),
        (newer_at, newer_at, newer_at, 95, 'I-95-NB', 5002,
         'Newer invalid', 20, 'I', 21, 'J', 9.00, 'CLOSED',
         'test/oracle-ballpark-invalid.csv');
END $$;

DO $$
DECLARE
    ballpark_route record;
    current_route record;
BEGIN
    SELECT * INTO STRICT ballpark_route
    FROM oracle.validate_ballpark_route('i95:203NO', 'airport_dca');
    SELECT * INTO STRICT current_route
    FROM oracle.validate_pricing_route('i95:203NO', 'airport_dca');

    IF ballpark_route.status <> 'valid'
       OR ballpark_route.reason IS NOT NULL
       OR jsonb_array_length(ballpark_route.facility_legs) = 0
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements(ballpark_route.general_purpose_gaps) AS gap(value)
           WHERE gap.value->'fallback_required' <> 'null'::jsonb
       )
       OR current_route.status NOT IN ('unknown_availability', 'currently_unavailable')
       THEN
        RAISE EXCEPTION 'ballpark route consulted live I-95 availability: % / %',
            row_to_json(ballpark_route), row_to_json(current_route);
    END IF;
END $$;

DO $$
DECLARE
    sample_day date := (
        SELECT max(day::date)
        FROM generate_series(
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 7,
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 1,
            interval '1 day'
        ) AS days(day)
        WHERE extract(isodow FROM day) = 3
    );
    i66 record;
    observed record;
    older_valid record;
BEGIN
    SELECT * INTO STRICT i66
    FROM oracle.get_i66_ballpark_samples(
        3100, 3110, time '08:00', ARRAY[sample_day], transaction_timestamp()
    );
    IF i66.price_usd <> 5.00 OR i66.sample_date <> sample_day THEN
        RAISE EXCEPTION 'I-66 ballpark did not select the latest bin row: %',
            row_to_json(i66);
    END IF;

    SELECT * INTO STRICT observed
    FROM oracle.get_i95_i495_ballpark_samples(
        1374, time '08:00', ARRAY[sample_day], transaction_timestamp()
    );
    IF observed.price_usd <> 7.00 OR observed.uses_modeled
       OR observed.proxy_od_pair_id IS NOT NULL THEN
        RAISE EXCEPTION 'observed I-95 row did not beat its modeled proxy: %',
            row_to_json(observed);
    END IF;

    SELECT * INTO STRICT older_valid
    FROM oracle.get_i95_i495_ballpark_samples(
        5002, time '08:00', ARRAY[sample_day], transaction_timestamp()
    );
    IF older_valid.price_usd <> 8.00 THEN
        RAISE EXCEPTION 'newer invalid I-95 row hid an older valid row: %',
            row_to_json(older_valid);
    END IF;
END $$;

DO $$
DECLARE
    today date := (transaction_timestamp() AT TIME ZONE 'America/New_York')::date;
BEGIN
    BEGIN
        PERFORM * FROM oracle.get_i66_ballpark_samples(
            3100, 3110, time '08:00', ARRAY[today - 1, today - 1],
            transaction_timestamp()
        );
        RAISE EXCEPTION 'duplicate dates were accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid ballpark sample request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_i66_ballpark_samples(
            3100, 3110, time '08:00', ARRAY[today], transaction_timestamp()
        );
        RAISE EXCEPTION 'incomplete current date was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid ballpark sample request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_i95_i495_ballpark_samples(
            1374, time '08:00', ARRAY[today - 1],
            transaction_timestamp() - interval '1 second'
        );
        RAISE EXCEPTION 'mismatched transaction anchor was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid ballpark sample request' THEN RAISE; END IF;
    END;
END $$;

DO $$
DECLARE
    spring_matches integer;
    fall_matches integer;
    ordinary_matches integer;
BEGIN
    WITH targets(label, wall_time) AS (VALUES
        ('spring', timestamp '2026-03-08 02:30:00'),
        ('fall', timestamp '2025-11-02 01:30:00'),
        ('ordinary', timestamp '2026-03-09 08:00:00')
    ), matches AS (
        SELECT target.label, count(*) AS match_count
        FROM targets AS target
        CROSS JOIN generate_series(-14, 14) AS offsets(offset_number)
        WHERE (
            (target.wall_time AT TIME ZONE 'UTC')
              + make_interval(hours => offset_number)
        ) AT TIME ZONE 'America/New_York' = target.wall_time
        GROUP BY target.label
    )
    SELECT
        coalesce(max(match_count) FILTER (WHERE label = 'spring'), 0),
        coalesce(max(match_count) FILTER (WHERE label = 'fall'), 0),
        coalesce(max(match_count) FILTER (WHERE label = 'ordinary'), 0)
    INTO spring_matches, fall_matches, ordinary_matches
    FROM matches;

    IF spring_matches <> 0 OR fall_matches <> 2 OR ordinary_matches <> 1 THEN
        RAISE EXCEPTION 'Eastern wall-time uniqueness test failed: %, %, %',
            spring_matches, fall_matches, ordinary_matches;
    END IF;
END $$;

DO $$
DECLARE
    sample_dates date[];
    sample_day date;
    sample_at timestamptz;
    sample_index integer := 0;
    i66_prices numeric[] := ARRAY[9, 1, 2, 3, 100];
    i95_prices numeric[] := ARRAY[NULL, 100, 3, 2, 1];
    fixed_prices jsonb := '[]'::jsonb;
    summary record;
BEGIN
    SELECT array_agg(day ORDER BY day)
    INTO sample_dates
    FROM (
        SELECT day::date
        FROM generate_series(
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 14,
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 1,
            interval '1 day'
        ) AS candidate(day)
        WHERE extract(isodow FROM day) BETWEEN 1 AND 5
        ORDER BY day DESC
        LIMIT 5
    ) AS recent_weekdays;

    FOREACH sample_day IN ARRAY sample_dates LOOP
        sample_index := sample_index + 1;
        sample_at := (sample_day + time '08:05') AT TIME ZONE 'America/New_York';
        INSERT INTO pricing.trip_pricing_i66 (
            interval_start_at, interval_end_at, calculated_at, corridor_id,
            corridor_name, start_zone_id, start_zone_name, end_zone_id,
            end_zone_name, zone_toll_rate_usd, s3_key
        ) VALUES (
            sample_at - interval '1 minute', sample_at, sample_at, 66,
            'I-66-EB', 7000, 'A', 7010, 'B', i66_prices[sample_index],
            'test/annual-summary-i66-' || sample_index || '.csv'
        );
        IF sample_index > 1 THEN
            INSERT INTO pricing.trip_pricing_i95 (
            interval_end_at, current_at, calculated_at, corridor_id,
            corridor_name, od_pair_id, od_pair_name, start_zone_id,
            start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
            link_status, s3_key
            ) VALUES
                (sample_at, sample_at, sample_at, 95, 'I-95-NB', 1132,
                 'NB sentinel', 7100, 'A', 7110, 'B', 0, 'NORTHBOUND_OPEN',
                 'test/annual-summary-nb-' || sample_index || '.csv'),
                (sample_at, sample_at, sample_at, 95, 'I-95-SB', 1151,
                 'SB sentinel', 7120, 'C', 7130, 'D', 0, 'CLOSED',
                 'test/annual-summary-sb-' || sample_index || '.csv'),
                (sample_at, sample_at, sample_at, 95, 'I-95-NB', 7001,
                 'Target', 7140, 'E', 7150, 'F', i95_prices[sample_index],
                 'NORTHBOUND_OPEN',
                 'test/annual-summary-i95-' || sample_index || '.csv');
        END IF;
        fixed_prices := fixed_prices || jsonb_build_array(jsonb_build_object(
            'sample_date', sample_day,
            'direction', 'outbound',
            'route_step_id', 'step-2',
            'price_usd', CASE WHEN sample_index % 2 = 0 THEN '10.00' ELSE '0.00' END
        ));
    END LOOP;

    SELECT * INTO STRICT summary
    FROM oracle.get_annual_ballpark_summary(
        '[{"direction":"outbound","facility":"i66","route_step_id":"step-1","start_zone_id":7000,"end_zone_id":7010},
          {"direction":"return","facility":"i95_i495","route_step_id":"step-1","od_pair_id":7001},
          {"direction":"outbound","facility":"greenway","route_step_id":"step-2"},
          {"direction":"return","facility":"i66","route_step_id":"step-2","start_zone_id":7000,"end_zone_id":7010}]'::jsonb,
        time '08:00', time '08:00', sample_dates, fixed_prices, 5,
        transaction_timestamp()
    );

    IF summary.complete_pair_count <> 4
       OR summary.eligible_date_count <> 5
       OR summary.coverage_percent <> '80.0'
       OR summary.sample_status <> 'partial'
       OR summary.p25_daily_usd <> 7
       OR summary.p50_daily_usd <> 18
       OR summary.p90_daily_usd <> 201
       OR summary.p50_annualized_usd <> 90
       OR jsonb_array_length(summary.facility_scenarios) <> 3
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements(summary.facility_scenarios) AS facility(value)
           WHERE (facility.value->>'sample_count')::integer <> 4
       )
       OR (summary.facility_scenarios #>> '{0,scenarios,p25,daily_round_trip_usd}') <> '2.00'
       OR (summary.facility_scenarios #>> '{1,scenarios,p25,daily_round_trip_usd}') <> '1.00'
       OR (summary.facility_scenarios #>> '{2,scenarios,p25,daily_round_trip_usd}') <> '0.00'
       OR summary.p25_daily_usd =
          (summary.facility_scenarios #>> '{0,scenarios,p25,daily_round_trip_usd}')::numeric
          + (summary.facility_scenarios #>> '{1,scenarios,p25,daily_round_trip_usd}')::numeric
          + (summary.facility_scenarios #>> '{2,scenarios,p25,daily_round_trip_usd}')::numeric
       THEN
        RAISE EXCEPTION 'annual summary lost aligned exact percentiles: %',
            row_to_json(summary);
    END IF;
END $$;

DO $$
DECLARE
    sample_day date := (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 1;
BEGIN
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            NULL, time '08:00', time '17:30', ARRAY[sample_day], '[]', 1,
            transaction_timestamp()
        );
        RAISE EXCEPTION 'SQL-null legs were accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid annual ballpark request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            '[]', time '08:00', time '17:30', ARRAY[sample_day], NULL, 1,
            transaction_timestamp()
        );
        RAISE EXCEPTION 'SQL-null fixed prices were accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid annual ballpark request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            '[{"direction":null,"facility":null,"route_step_id":null}]',
            time '08:00', time '17:30', ARRAY[sample_day], '[]', 1,
            transaction_timestamp()
        );
        RAISE EXCEPTION 'JSON-null leg fields were accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid annual ballpark request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            '[{"direction":"outbound","facility":"dtr","route_step_id":"step-1"},
              {"direction":"outbound","facility":"dtr","route_step_id":"step-1"}]',
            time '08:00', time '17:30', ARRAY[sample_day], '[]', 1,
            transaction_timestamp()
        );
        RAISE EXCEPTION 'duplicate composite leg IDs were accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid annual ballpark request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            '[{"direction":"outbound","facility":"unknown","route_step_id":"step-1"}]',
            time '08:00', time '17:30', ARRAY[sample_day], '[]', 1,
            transaction_timestamp()
        );
        RAISE EXCEPTION 'unknown facility was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid annual ballpark request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            '[{"direction":"outbound","facility":"dtr","route_step_id":"step-1"}]',
            time '08:00', time '17:30', ARRAY[sample_day],
            jsonb_build_array(jsonb_build_object(
                'sample_date', sample_day, 'direction', 'outbound',
                'route_step_id', 'step-1', 'price_usd', '1.001'
            )), 1, transaction_timestamp()
        );
        RAISE EXCEPTION 'sub-cent fixed price was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid annual ballpark request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            '[{"direction":"outbound","facility":"dtr","route_step_id":"step-1"}]',
            time '08:00', time '17:30', ARRAY[sample_day],
            jsonb_build_array(jsonb_build_object(
                'sample_date', sample_day, 'direction', 'outbound',
                'route_step_id', 'step-1', 'price_usd', NULL
            )), 1, transaction_timestamp()
        );
        RAISE EXCEPTION 'JSON-null fixed price was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid annual ballpark request' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM * FROM oracle.get_annual_ballpark_summary(
            '[]', time '08:00', time '17:30', ARRAY[sample_day], '[]', 1,
            transaction_timestamp() - interval '1 second'
        );
        RAISE EXCEPTION 'mismatched aggregate anchor was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'invalid ballpark sample request' THEN RAISE; END IF;
    END;
END $$;

ROLLBACK;

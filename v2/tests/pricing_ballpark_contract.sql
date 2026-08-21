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
         3100, 'A', 3110, 'B', 4.00, 'test/ballpark-i66-older.csv'),
        (newer_at - interval '1 minute', newer_at, newer_at, 66, 'I-66-EB',
         3100, 'A', 3110, 'B', 5.00, 'test/ballpark-i66-newer.csv');

    INSERT INTO pricing.trip_pricing_i95 (
        interval_end_at, current_at, calculated_at, corridor_id,
        corridor_name, od_pair_id, od_pair_name, start_zone_id,
        start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
        link_status, s3_key
    ) VALUES
        (newer_at, newer_at, newer_at, 95, 'I-95-NB', 1132,
         'NB sentinel', 1, 'A', 2, 'B', 0, 'NORTHBOUND_OPEN',
         'test/ballpark-nb-sentinel.csv'),
        (newer_at, newer_at, newer_at, 95, 'I-95-SB', 1151,
         'SB sentinel', 3, 'C', 4, 'D', 0, 'CLOSED',
         'test/ballpark-sb-sentinel.csv'),
        (newer_at, newer_at, newer_at, 95, 'I-95-NB', 1374,
         'Observed target', 10, 'E', 11, 'F', 7.00, 'NORTHBOUND_OPEN',
         'test/ballpark-observed.csv'),
        (newer_at, newer_at, newer_at, 95, 'I-95-NB', 1146,
         'Proxy target', 12, 'G', 13, 'H', 6.00, 'NORTHBOUND_OPEN',
         'test/ballpark-proxy.csv'),
        (newer_at, newer_at, newer_at, 495, 'I-495-NB', 5001,
         'I-495 target', 14, 'I', 15, 'J', 3.00, 'NO_DETERMINATION',
         'test/ballpark-i495.csv');
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
BEGIN
    IF (SELECT count(*) FROM pricing.i66_ballpark_samples
        WHERE sample_date = sample_day
          AND start_zone_id = 3100 AND end_zone_id = 3110) <> 2
       OR NOT EXISTS (
           SELECT 1 FROM pricing.i95_i495_ballpark_samples
           WHERE sample_date = sample_day AND od_pair_id = 1374
             AND NOT uses_modeled AND price_usd = 7.00
       )
       OR NOT EXISTS (
           SELECT 1 FROM pricing.i95_i495_ballpark_samples
           WHERE sample_date = sample_day AND od_pair_id = 1374
             AND uses_modeled AND price_usd = 6.00
             AND proxy_od_pair_id = 1146
       )
       OR NOT EXISTS (
           SELECT 1 FROM pricing.i95_i495_ballpark_samples
           WHERE sample_date = sample_day AND od_pair_id = 5001
       ) THEN
        RAISE EXCEPTION 'ballpark sample views lost valid observed or modeled rows';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pricing.i66_ballpark_samples
        WHERE sample_date <
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 84
           OR sample_date >=
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date
           OR interval_end_at > transaction_timestamp()
           OR observed_at > transaction_timestamp()
    ) OR EXISTS (
        SELECT 1 FROM pricing.i95_i495_ballpark_samples
        WHERE sample_date <
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date - 84
           OR sample_date >=
            (transaction_timestamp() AT TIME ZONE 'America/New_York')::date
           OR interval_end_at > transaction_timestamp()
           OR observed_at > transaction_timestamp()
    ) THEN
        RAISE EXCEPTION 'ballpark sample view escaped its bounded window';
    END IF;
END $$;

ROLLBACK;

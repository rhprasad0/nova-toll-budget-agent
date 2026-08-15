\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
    relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'trip_pricing_i95',
        'trip_pricing_i66',
        'current_trip_pricing_i95',
        'current_trip_pricing_i66',
        'i95_modeled_od_proxy',
        'modeled_trip_pricing_i95',
        'modeled_current_trip_pricing_i95'
    ] LOOP
        IF to_regclass('public.' || relation_name) IS NULL THEN
            RAISE EXCEPTION 'missing relation: %', relation_name;
        END IF;
    END LOOP;

    FOREACH relation_name IN ARRAY ARRAY[
        'trip_pricing_i95_od_lookup_idx',
        'trip_pricing_i66_zone_lookup_idx'
    ] LOOP
        IF to_regclass('public.' || relation_name) IS NULL THEN
            RAISE EXCEPTION 'missing index: %', relation_name;
        END IF;
    END LOOP;

    IF to_regclass('public.trip_pricing_i95_live') IS NOT NULL THEN
        RAISE EXCEPTION 'rewrite bootstrap must not create Transurban history';
    END IF;
END $$;

CREATE TEMP TABLE expected_proxy (
    target_od_pair_id integer PRIMARY KEY,
    proxy_od_pair_id integer NOT NULL,
    required_status text NOT NULL
);

INSERT INTO expected_proxy VALUES
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
    (1389, 1315, 'SOUTHBOUND_OPEN');

DO $$
BEGIN
    IF EXISTS (
        (SELECT * FROM expected_proxy EXCEPT SELECT * FROM i95_modeled_od_proxy)
        UNION ALL
        (SELECT * FROM i95_modeled_od_proxy EXCEPT SELECT * FROM expected_proxy)
    ) THEN
        RAISE EXCEPTION 'modeled OD proxy map differs from the approved 16 rows';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT pg_has_role('loader_writer', 'rds_iam', 'MEMBER')
       OR NOT pg_has_role('pricing_reader', 'rds_iam', 'MEMBER') THEN
        RAISE EXCEPTION 'database roles must use RDS IAM authentication';
    END IF;

    IF NOT has_table_privilege('loader_writer', 'trip_pricing_i95', 'SELECT')
       OR NOT has_table_privilege('loader_writer', 'trip_pricing_i95', 'INSERT')
       OR NOT has_table_privilege('loader_writer', 'trip_pricing_i95', 'UPDATE')
       OR NOT has_table_privilege('loader_writer', 'trip_pricing_i66', 'SELECT')
       OR NOT has_table_privilege('loader_writer', 'trip_pricing_i66', 'INSERT')
       OR NOT has_table_privilege('loader_writer', 'trip_pricing_i66', 'UPDATE') THEN
        RAISE EXCEPTION 'loader_writer is missing pricing table privileges';
    END IF;

    IF NOT has_table_privilege('pricing_reader', 'trip_pricing_i95', 'SELECT')
       OR NOT has_table_privilege('pricing_reader', 'trip_pricing_i66', 'SELECT')
       OR NOT has_table_privilege('pricing_reader', 'current_trip_pricing_i95', 'SELECT')
       OR NOT has_table_privilege('pricing_reader', 'current_trip_pricing_i66', 'SELECT')
       OR NOT has_table_privilege('pricing_reader', 'i95_modeled_od_proxy', 'SELECT')
       OR NOT has_table_privilege('pricing_reader', 'modeled_trip_pricing_i95', 'SELECT')
       OR NOT has_table_privilege('pricing_reader', 'modeled_current_trip_pricing_i95', 'SELECT') THEN
        RAISE EXCEPTION 'pricing_reader is missing read privileges';
    END IF;

    IF has_table_privilege('pricing_reader', 'trip_pricing_i95', 'INSERT,UPDATE,DELETE')
       OR has_table_privilege('pricing_reader', 'trip_pricing_i66', 'INSERT,UPDATE,DELETE') THEN
        RAISE EXCEPTION 'pricing_reader must remain read-only';
    END IF;
END $$;

INSERT INTO trip_pricing_i95 (
    interval_end_at,
    current_at,
    calculated_at,
    corridor_id,
    corridor_name,
    od_pair_id,
    od_pair_name,
    start_zone_id,
    start_zone_name,
    end_zone_id,
    end_zone_name,
    zone_toll_rate_usd,
    link_status,
    s3_key
) VALUES (
    '2026-07-30 12:00:00+00',
    '2026-07-30 11:59:00+00',
    '2026-07-30 11:58:00+00',
    95,
    'I-95-SB',
    1165,
    'I-495 EB / I-95 NB to Dumfries Road',
    1,
    'I-495 EB / I-95 NB',
    2,
    'I-95 Near Dumfries Road/Route 234',
    14.25,
    'SOUTHBOUND_OPEN',
    'test/open.json'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM modeled_trip_pricing_i95
        WHERE od_pair_id = 1385
          AND proxy_od_pair_id = 1165
          AND zone_toll_rate_usd = 14.25
          AND modeled
          AND pricing_method = 'identity_proxy_v1'
    ) THEN
        RAISE EXCEPTION 'historical modeled price did not copy its open proxy';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM modeled_current_trip_pricing_i95
        WHERE od_pair_id = 1385
          AND proxy_od_pair_id = 1165
          AND zone_toll_rate_usd = 14.25
          AND modeled
          AND pricing_method = 'identity_proxy_v1'
    ) THEN
        RAISE EXCEPTION 'current modeled price did not copy its open proxy';
    END IF;
END $$;

INSERT INTO trip_pricing_i95 (
    interval_end_at,
    current_at,
    calculated_at,
    corridor_id,
    corridor_name,
    od_pair_id,
    od_pair_name,
    start_zone_id,
    start_zone_name,
    end_zone_id,
    end_zone_name,
    zone_toll_rate_usd,
    link_status,
    s3_key
) VALUES (
    '2026-07-30 12:10:00+00',
    '2026-07-30 12:09:00+00',
    '2026-07-30 12:08:00+00',
    95,
    'I-95-SB',
    1165,
    'I-495 EB / I-95 NB to Dumfries Road',
    1,
    'I-495 EB / I-95 NB',
    2,
    'I-95 Near Dumfries Road/Route 234',
    15.00,
    'CLOSED',
    'test/closed.json'
);

DO $$
BEGIN
    IF (SELECT count(*) FROM modeled_trip_pricing_i95 WHERE od_pair_id = 1385) <> 2 THEN
        RAISE EXCEPTION 'historical view must retain the closed observation';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM modeled_trip_pricing_i95
        WHERE od_pair_id = 1385
          AND interval_end_at = '2026-07-30 12:10:00+00'
          AND link_status = 'CLOSED'
          AND zone_toll_rate_usd IS NULL
    ) THEN
        RAISE EXCEPTION 'closed historical proxy must have a null modeled price';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            SELECT zone_toll_rate_usd
            FROM modeled_trip_pricing_i95
            WHERE od_pair_id = 1385
              AND interval_end_at >= '2026-07-30 12:00:00+00'
              AND interval_end_at < '2026-07-30 12:15:00+00'
            ORDER BY interval_end_at DESC
            LIMIT 1
        ) AS latest
        WHERE zone_toll_rate_usd IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'latest closed observation must prevent a historical comparable';
    END IF;

    IF EXISTS (
        SELECT 1 FROM modeled_current_trip_pricing_i95 WHERE od_pair_id = 1385
    ) THEN
        RAISE EXCEPTION 'current view must not fall back past a newer closed row';
    END IF;
END $$;

ROLLBACK;

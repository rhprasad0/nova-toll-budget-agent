\set ON_ERROR_STOP on

BEGIN;

INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key
) VALUES (
    '2026-08-17 12:00:00+00', '2026-08-17 11:59:00+00',
    '2026-08-17 11:58:00+00', 95, 'I-95-NB', 95001, 'A TO B', 1, 'A', 2,
    'B', 5.00, 'OPEN', 'raw/feed=i95/date=2026-08-17/1200Z.csv'
);

INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key
) VALUES (
    '2026-08-17 12:00:00+00', '2026-08-17 11:59:00+00',
    '2026-08-17 11:57:00+00', 95, 'I-95-NB', 95001, 'A TO B', 1, 'A', 2,
    'B', 1.00, 'OPEN', 'raw/feed=i95/date=2026-08-17/1210Z.csv'
)
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
DO UPDATE SET
    calculated_at = EXCLUDED.calculated_at,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    s3_key = EXCLUDED.s3_key
WHERE (pricing.trip_pricing_i95.calculated_at, pricing.trip_pricing_i95.s3_key)
    < (EXCLUDED.calculated_at, EXCLUDED.s3_key);

INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key
) VALUES (
    '2026-08-17 12:00:00+00', '2026-08-17 11:59:00+00',
    '2026-08-17 11:58:00+00', 95, 'I-95-NB', 95001, 'A TO B', 1, 'A', 2,
    'B', 6.00, 'OPEN', 'raw/feed=i95/date=2026-08-17/1210Z.csv'
)
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
DO UPDATE SET
    calculated_at = EXCLUDED.calculated_at,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    s3_key = EXCLUDED.s3_key
WHERE (pricing.trip_pricing_i95.calculated_at, pricing.trip_pricing_i95.s3_key)
    < (EXCLUDED.calculated_at, EXCLUDED.s3_key);

-- The same revision tuple is a no-op even if another field differs.
INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key
) VALUES (
    '2026-08-17 12:00:00+00', '2026-08-17 11:59:00+00',
    '2026-08-17 11:58:00+00', 95, 'I-95-NB', 95001, 'A TO B', 1, 'A', 2,
    'B', 7.00, 'OPEN', 'raw/feed=i95/date=2026-08-17/1210Z.csv'
)
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
DO UPDATE SET zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd
WHERE (pricing.trip_pricing_i95.calculated_at, pricing.trip_pricing_i95.s3_key)
    < (EXCLUDED.calculated_at, EXCLUDED.s3_key);

-- A late, absent interval remains valid history.
INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key
) VALUES (
    '2026-08-17 11:50:00+00', '2026-08-17 11:49:00+00',
    '2026-08-17 11:48:00+00', 95, 'I-95-NB', 95001, 'A TO B', 1, 'A', 2,
    'B', 4.00, 'OPEN', 'raw/feed=i95/date=2026-08-17/1150Z.csv'
);

INSERT INTO pricing.trip_pricing_i66 (
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id, end_zone_name,
    zone_toll_rate_usd, s3_key
) VALUES (
    '2026-08-17 11:54:00+00', '2026-08-17 12:00:00+00',
    '2026-08-17 11:58:00+00', 66, 'I-66-EB', 10, 'A', 20, 'B', 2.00,
    'raw/feed=i66/date=2026-08-17/1200Z.xml'
);

INSERT INTO pricing.trip_pricing_i66 (
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id, end_zone_name,
    zone_toll_rate_usd, s3_key
) VALUES (
    '2026-08-17 11:54:00+00', '2026-08-17 12:00:00+00',
    '2026-08-17 11:57:00+00', 66, 'I-66-EB', 10, 'A', 20, 'B', 1.00,
    'raw/feed=i66/date=2026-08-17/1210Z.xml'
)
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id)
DO UPDATE SET
    calculated_at = EXCLUDED.calculated_at,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    s3_key = EXCLUDED.s3_key
WHERE (pricing.trip_pricing_i66.calculated_at, pricing.trip_pricing_i66.s3_key)
    < (EXCLUDED.calculated_at, EXCLUDED.s3_key);

DO $$
BEGIN
    IF (SELECT count(*) FROM pricing.trip_pricing_i95 WHERE od_pair_id = 95001) <> 2
       OR (SELECT zone_toll_rate_usd FROM pricing.trip_pricing_i95
           WHERE od_pair_id = 95001 AND interval_end_at = '2026-08-17 12:00:00+00') <> 6.00
       OR (SELECT zone_toll_rate_usd FROM pricing.trip_pricing_i66
           WHERE start_zone_id = 10 AND end_zone_id = 20
             AND interval_end_at = '2026-08-17 12:00:00+00') <> 2.00 THEN
        RAISE EXCEPTION 'monotonic upsert contract failed';
    END IF;
END $$;

ROLLBACK;

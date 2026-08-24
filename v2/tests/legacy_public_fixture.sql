\set ON_ERROR_STOP on

DO $$
BEGIN
    CREATE ROLE loader_writer WITH LOGIN;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
GRANT rds_iam TO loader_writer;

CREATE TABLE public.trip_pricing_i95
(LIKE pricing.trip_pricing_i95 INCLUDING ALL);
CREATE TABLE public.trip_pricing_i66
(LIKE pricing.trip_pricing_i66 INCLUDING ALL);
CREATE SEQUENCE public.trip_pricing_id_seq;
CREATE TABLE public.trip_pricing (
    id bigint DEFAULT nextval('public.trip_pricing_id_seq') PRIMARY KEY
);
CREATE TABLE public.trip_pricing_i95_live (
    captured_at timestamptz PRIMARY KEY
);

CREATE VIEW public.current_trip_pricing_i95 AS
SELECT * FROM public.trip_pricing_i95;
CREATE VIEW public.current_trip_pricing_i66 AS
SELECT * FROM public.trip_pricing_i66;

GRANT SELECT, INSERT, UPDATE ON
    public.trip_pricing,
    public.trip_pricing_i95,
    public.trip_pricing_i66,
    public.trip_pricing_i95_live
TO loader_writer;

INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key
) VALUES (
    '2026-08-16 12:00:00+00', '2026-08-16 11:59:00+00',
    '2026-08-16 11:58:00+00', 95, 'I-95-NB', 5001, 'A TO B', 1,
    'A', 2, 'B', 7.10, 'NORTHBOUND_OPEN',
    'raw/feed=i95/date=2026-08-16/1200Z.csv'
);

INSERT INTO pricing.trip_pricing_i66 (
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, s3_key
) VALUES (
    '2026-08-16 11:54:00+00', '2026-08-16 12:00:00+00',
    '2026-08-16 11:59:00+00', 66, 'I-66-EB', 10, 'A', 20, 'B', 2.10,
    'raw/feed=i66/date=2026-08-16/1200Z.xml'
);

INSERT INTO public.trip_pricing_i95
SELECT * FROM pricing.trip_pricing_i95;
INSERT INTO public.trip_pricing_i66
SELECT * FROM pricing.trip_pricing_i66;

UPDATE public.trip_pricing_i95 SET s3_key = 'raw/legacy/i95.csv';
UPDATE public.trip_pricing_i66 SET s3_key = 'raw/legacy/i66.xml';

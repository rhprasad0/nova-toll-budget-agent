-- Minimal deployed-public fixture for additive copy/backfill testing.

\set ON_ERROR_STOP on

CREATE TABLE public.trip_pricing_i95 (
    interval_end_at timestamptz NOT NULL,
    current_at timestamptz NOT NULL,
    calculated_at timestamptz NOT NULL,
    corridor_id integer NOT NULL,
    corridor_name text NOT NULL,
    od_pair_id integer NOT NULL,
    od_pair_name text NOT NULL,
    start_zone_id integer NOT NULL,
    start_zone_name text,
    end_zone_id integer NOT NULL,
    end_zone_name text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status text NOT NULL,
    s3_key text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
);

CREATE TABLE public.trip_pricing_i66 (
    interval_start_at timestamptz NOT NULL,
    interval_end_at timestamptz NOT NULL,
    calculated_at timestamptz NOT NULL,
    corridor_id integer NOT NULL,
    corridor_name text NOT NULL,
    start_zone_id integer NOT NULL,
    start_zone_name text,
    end_zone_id integer NOT NULL,
    end_zone_name text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    s3_key text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id)
);

CREATE SEQUENCE public.trip_pricing_id_seq;
CREATE TABLE public.trip_pricing (id bigint DEFAULT nextval('public.trip_pricing_id_seq'));
CREATE TABLE public.trip_pricing_i95_live (captured_at timestamptz PRIMARY KEY);
GRANT SELECT, INSERT, UPDATE ON public.trip_pricing TO pricing_loader_writer;

INSERT INTO public.trip_pricing_i95 VALUES (
    '2026-08-16 12:00:00+00', '2026-08-16 11:59:00+00',
    '2026-08-16 11:58:00+00', 95, 'I-95-NB', 5001, 'A TO B', 1,
    'A', 2, 'B', 7.10, 'NORTHBOUND_OPEN',
    'raw/feed=i95/date=2026-08-16/1200Z.csv',
    '2026-08-16 12:01:00+00'
);

INSERT INTO public.trip_pricing_i66 VALUES (
    '2026-08-16 11:54:00+00', '2026-08-16 12:00:00+00',
    '2026-08-16 11:59:00+00', 66, 'I-66-EB', 10, 'A', 20, 'B', 2.10,
    'raw/feed=i66/date=2026-08-16/1200Z.xml',
    '2026-08-16 12:01:00+00'
);

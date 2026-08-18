-- TollChat v2 PostgreSQL pricing bootstrap.
-- pricing schema version: 1.1.0

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;

CREATE SCHEMA pricing;
REVOKE ALL ON SCHEMA pricing FROM PUBLIC;

CREATE TABLE pricing.schema_version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version text NOT NULL CHECK (
        version ~ '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
    ),
    installed_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO pricing.schema_version (version) VALUES ('1.1.0');

CREATE TABLE pricing.trip_pricing_i95 (
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer NOT NULL,
    od_pair_name       text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
);

CREATE TABLE pricing.trip_pricing_i66 (
    interval_start_at  timestamptz NOT NULL,
    interval_end_at    timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id)
);

CREATE TABLE pricing.backfill_state (
    feed text PRIMARY KEY CHECK (feed IN ('i95', 'i66')),
    completed_at timestamptz NOT NULL,
    public_row_count bigint NOT NULL CHECK (public_row_count >= 0),
    pricing_row_count bigint NOT NULL CHECK (pricing_row_count >= 0),
    CHECK (public_row_count = pricing_row_count)
);

CREATE INDEX trip_pricing_i95_od_lookup_idx
    ON pricing.trip_pricing_i95 (od_pair_id, interval_end_at DESC);

CREATE INDEX trip_pricing_i66_zone_lookup_idx
    ON pricing.trip_pricing_i66 (
        start_zone_id,
        end_zone_id,
        interval_end_at DESC
    );

CREATE VIEW pricing.current_trip_pricing_i95 AS
SELECT DISTINCT ON (od_pair_id)
    od_pair_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at,
    link_status
FROM pricing.trip_pricing_i95
ORDER BY
    od_pair_id,
    interval_end_at DESC,
    calculated_at DESC,
    start_zone_id,
    end_zone_id;

CREATE VIEW pricing.current_trip_pricing_i66 AS
SELECT DISTINCT ON (start_zone_id, end_zone_id)
    start_zone_id,
    end_zone_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at
FROM pricing.trip_pricing_i66
ORDER BY
    start_zone_id,
    end_zone_id,
    interval_end_at DESC,
    calculated_at DESC;

\ir analysis.sql

COMMIT;

-- Mirrors docs/poller-spec.md §Database schema. Keep in sync; the schema
-- version below must match the spec and is enforced by test_schema_contract.py.
-- schema version: 5.0.0

-- I-95/395/495: OD pairs exist and legitimately share start/end zones at
-- different rates, so od_pair_id is part of the key. current_at/od_pair_id/
-- od_pair_name/link_status are NOT NULL because the source feed always
-- populates them (verified against 1.2M archived + live rows).
CREATE TABLE trip_pricing_i95 (
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer NOT NULL,
    od_pair_name       text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,                      -- blank for some Prince William OD pairs
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL,
    s3_key             text NOT NULL,              -- raw object provenance
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
);

-- I-66 ITB: no OD pairs, so the key is zone-only. interval_start_at is
-- always present (i95 never had it); every key column is NOT NULL so no
-- NULLS NOT DISTINCT is needed, unlike the old shared table.
CREATE TABLE trip_pricing_i66 (
    interval_start_at  timestamptz NOT NULL,
    interval_end_at    timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,                      -- nullable, same reason as i95
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id)
);

-- Pricing-lookup indexes for agent_tools/i66_route.py and i95_route.py
-- (docs/oracle-tools-spec.md) -- see db/add_pricing_read_indexes.sql for the
-- one-shot migration against an already-live database and the rationale.
CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i66_zone_lookup_idx
    ON trip_pricing_i66 (start_zone_id, end_zone_id, interval_end_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i95_od_lookup_idx
    ON trip_pricing_i95 (od_pair_id, interval_end_at DESC);

-- Agent-facing current VDOT prices. These are normal views: the lookup
-- indexes above make the latest-row query cheap, while a materialized view
-- would add a refresh delay to a price that is already time-sensitive.
-- `timestamptz` values remain UTC-backed instants; pricing_reader renders
-- them in America/New_York (see db/roles.sql).
CREATE VIEW current_trip_pricing_i95 AS
SELECT DISTINCT ON (od_pair_id)
    od_pair_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at,
    link_status
FROM trip_pricing_i95
ORDER BY od_pair_id, interval_end_at DESC;

CREATE VIEW current_trip_pricing_i66 AS
SELECT DISTINCT ON (start_zone_id, end_zone_id)
    start_zone_id,
    end_zone_id,
    corridor_name,
    zone_toll_rate_usd,
    interval_end_at,
    calculated_at
FROM trip_pricing_i66
ORDER BY start_zone_id, end_zone_id, interval_end_at DESC;

-- Mirrors docs/poller-spec.md §Database schema. Keep in sync; the schema
-- version below must match the spec and is enforced by test_schema_contract.py.
-- schema version: 4.0.0

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

-- Transurban's own live snapshot (maps-api/infra-price-confirmed-all), used
-- to fill od_pair_ids VDOT's feed has never published -- see
-- docs/oracle-findings.md section 2 and docs/poller-spec.md's "Secondary
-- live source" section.
--
-- Keyed on captured_at, the tick from the raw object's own S3 key. observed_at
-- is the response's one shared "time" field (America/New_York, converted to
-- UTC) and the source truncates it to the hour, while the prices themselves
-- change every 10 minutes -- so keying on observed_at, as this table did until
-- schema 4.0.0, silently collapsed each hour's six captures onto one row.
-- captured_at comes from the key rather than the object's S3 LastModified
-- because the replay workflow re-touches objects, which moves LastModified but
-- never the key -- so a replay stays a no-op. status is Transurban's own
-- open/closed/null vocabulary -- a different concept from link_status, never
-- mapped onto it. status/road/direction are nullable because the source itself
-- emits the literal string "null" for dead links.
CREATE TABLE trip_pricing_i95_live (
    captured_at        timestamptz NOT NULL,       -- our poll tick, from s3_key
    observed_at        timestamptz NOT NULL,       -- source's own label, hourly
    od_pair_id         integer NOT NULL,
    price_usd          numeric(10,2) NOT NULL,
    status             text,
    road               text,
    direction          text,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (captured_at, od_pair_id)
);

-- Pricing-lookup indexes for agent_tools/i66_route.py and i95_route.py
-- (docs/oracle-tools-spec.md) -- see db/add_pricing_read_indexes.sql for the
-- one-shot migration against an already-live database and the rationale.
CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i66_zone_lookup_idx
    ON trip_pricing_i66 (start_zone_id, end_zone_id, interval_end_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i95_od_lookup_idx
    ON trip_pricing_i95 (od_pair_id, interval_end_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i95_live_od_lookup_idx
    ON trip_pricing_i95_live (od_pair_id, captured_at DESC);

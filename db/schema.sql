-- Mirrors docs/poller-spec.md §Database schema. Keep in sync; the schema
-- version below must match the spec and is enforced by test_schema_contract.py.
-- schema version: 2.1.0

CREATE TABLE trip_pricing (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feed               text NOT NULL CHECK (feed IN ('i95', 'i66')),
    interval_start_at  timestamptz,              -- i66 only
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz,              -- i95 only
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer,                  -- i95 only
    od_pair_name       text,                     -- i95 only
    start_zone_id      integer NOT NULL,
    start_zone_name    text,
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL DEFAULT 'NOT_APPLICABLE',  -- i66 has none
    s3_key             text NOT NULL,            -- raw object provenance
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    -- Upsert key. od_pair_id is included because multiple i95 OD pairs can
    -- traverse the same start/end zone at different rates; NULLS NOT DISTINCT
    -- keeps i66 (od_pair_id always NULL) idempotent under re-delivery.
    UNIQUE NULLS NOT DISTINCT (feed, interval_end_at, start_zone_id, end_zone_id, od_pair_id)
);

-- Supports the route tool's DISTINCT ON (od_pair_id, start_zone_id, end_zone_id)
-- ORDER BY ... interval_end_at DESC latest-price lookup. INCLUDE covers
-- zone_toll_rate_usd/link_status so it's an index-only scan -- a plain
-- (non-covering) version of this index still needs a heap fetch per row
-- (1.16M rows -> ~25s), which blows the agent_readonly 5s statement_timeout.
-- Covering brings it to ~1.4s.
CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_price_lookup_covering_idx
    ON trip_pricing (od_pair_id, start_zone_id, end_zone_id, interval_end_at DESC)
    INCLUDE (zone_toll_rate_usd, link_status);

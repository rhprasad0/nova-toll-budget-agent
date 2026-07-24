-- Mirrors docs/poller-spec.md §Database schema. Keep in sync; the schema
-- version below must match the spec and is enforced by test_schema_contract.py.
-- schema version: 2.2.0

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

-- Kept for hand-written DISTINCT ON (od_pair_id, start_zone_id, end_zone_id)
-- queries via execute_sql, whose ORDER BY matches this index's full column
-- order. It no longer serves the route tool: its column order can't produce
-- an index-ordered descent by interval_end_at within a single od_pair_id (the
-- zone columns sit between the equality column and the sort column), so the
-- route tool's LATERAL queries fell back to a Sort -- see the two indexes
-- below for the fix.
CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_price_lookup_covering_idx
    ON trip_pricing (od_pair_id, start_zone_id, end_zone_id, interval_end_at DESC)
    INCLUDE (zone_toll_rate_usd, link_status);

-- Per-key latest-row descent for the route tool's LATERAL queries. Each
-- query's equality columns come first, then interval_end_at DESC alone, so
-- the planner can walk straight to the newest row per key instead of
-- sorting. The feed split (i95 has od_pair_id, i66 doesn't) is expressed as
-- a partial-index predicate rather than an od_pair_id IS [NOT] NULL key
-- column -- a NullTest on a key column can't establish index ordering, so it
-- forced the same Sort these indexes exist to avoid. INCLUDE covers
-- zone_toll_rate_usd/link_status for index-only scans.
CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_od_latest_idx
    ON trip_pricing (od_pair_id, interval_end_at DESC)
    INCLUDE (zone_toll_rate_usd, link_status)
    WHERE od_pair_id IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_zone_latest_idx
    ON trip_pricing (start_zone_id, end_zone_id, interval_end_at DESC)
    INCLUDE (zone_toll_rate_usd, link_status)
    WHERE od_pair_id IS NULL;

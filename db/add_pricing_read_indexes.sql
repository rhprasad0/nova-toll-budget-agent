-- One-shot addition of the pricing-lookup indexes (see db/schema.sql, schema
-- version 3.2.0). Before this, no index on trip_pricing_i95/trip_pricing_i66
-- leads with the key agent_tools/i66_route.py and i95_route.py now query on
-- (od_pair_id / (start_zone_id, end_zone_id)) -- trip_pricing_i95's own PK
-- leads with interval_end_at, so a per-id price lookup was a full scan of
-- that id's entire history. This is a real read pattern now, not a
-- speculative one (docs/poller-spec.md: "add an index when a real read
-- pattern asks for one").
--
-- APPLIED 2026-07-28. Historical one-shot; new databases use db/schema.sql.
-- Do not run this as routine setup.
--
-- The three CREATE INDEX statements are duplicated from db/schema.sql so this
-- file is runnable standalone against a DB that hasn't had schema.sql
-- re-applied yet. Keep them in sync -- the i95-live index moved to captured_at
-- in schema 4.0.0, and db/add_captured_at_to_i95_live.sql rebuilds it.
--
--     psql "$NOVA_TOLL_URL" -f db/add_pricing_read_indexes.sql
--
-- Must NOT be wrapped in BEGIN/COMMIT: CREATE INDEX CONCURRENTLY cannot run
-- inside a transaction block (db/drop_agent_surface.sql's header note has the
-- same rule for DROP INDEX CONCURRENTLY). CONCURRENTLY avoids taking a lock
-- that would stall the loader, which writes to these same tables every 10
-- minutes. IF NOT EXISTS makes each statement safe to re-run.

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i66_zone_lookup_idx
    ON trip_pricing_i66 (start_zone_id, end_zone_id, interval_end_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i95_od_lookup_idx
    ON trip_pricing_i95 (od_pair_id, interval_end_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i95_live_od_lookup_idx
    ON trip_pricing_i95_live (od_pair_id, captured_at DESC);

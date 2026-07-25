-- One-shot cutover from the shared trip_pricing table to per-feed
-- trip_pricing_i95 / trip_pricing_i66 (see db/schema.sql, schema version
-- 3.0.0). The old agent-query surface that justified one shared table is
-- gone (db/drop_agent_surface.sql); the two feeds are structurally
-- different and are better served by two purpose-built tables.
--
-- The CREATE TABLE statements below are duplicated from db/schema.sql
-- (needed here so this file is runnable standalone against a DB that hasn't
-- had schema.sql applied yet). If schema.sql's DDL for these two tables ever
-- changes, update it here too, or just run schema.sql first and delete the
-- CREATE TABLE blocks from this file.
--
-- trip_pricing is live in production (a loader Lambda upserts into it every
-- ~10 minutes, 24/7) and already holds ~1.2M i95 rows + ~12.7k i66 rows, so
-- this cannot be a plain schema swap. Sequence:
--
--   1. Run this file's CREATE/GRANT block (below) against live RDS. This
--      creates both new tables AND grants loader_writer on them in one
--      transaction -- tables existing without grants even briefly means the
--      next poll after loader deploy gets "permission denied" and fires the
--      freshness alarm.
--   2. Run the INSERT block below (pass 1) BEFORE deploying the new loader
--      code. It's a plain SELECT against trip_pricing (ACCESS SHARE lock
--      only), so it does not block the old loader's concurrent writes.
--   3. Deploy the new loader zip. From this point it writes only to the two
--      new tables; trip_pricing is no longer written to but is left as-is.
--   4. Run the INSERT block again (pass 2). This closes the gap: any rows
--      the OLD loader wrote to trip_pricing between pass 1 and the deploy
--      are otherwise stranded. ON CONFLICT DO NOTHING makes re-running safe
--      -- the block is idempotent and is meant to run exactly twice.
--   5. Verify row counts per feed match between trip_pricing and the new
--      tables, spot-check a few rows.
--
-- trip_pricing is deliberately NOT renamed or dropped here -- keeping it
-- untouched is what makes rollback trivial (redeploy the old loader zip; it
-- still works unmodified against an unmodified table). Renaming it to
-- trip_pricing_legacy is a separate, later one-shot file, done only after a
-- soak period once the new tables have proven healthy in prod.
--
--     psql "$NOVA_TOLL_URL" -f db/split_trip_pricing.sql   -- pass 1 (pre-deploy)
--     psql "$NOVA_TOLL_URL" -f db/split_trip_pricing.sql   -- pass 2 (post-deploy)
--
-- Safe to run more than twice too: CREATE TABLE/GRANT are idempotent via
-- IF NOT EXISTS, and the inserts are idempotent via ON CONFLICT DO NOTHING.

BEGIN;

CREATE TABLE IF NOT EXISTS trip_pricing_i95 (
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

CREATE TABLE IF NOT EXISTS trip_pricing_i66 (
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

GRANT SELECT, INSERT, UPDATE ON trip_pricing_i95, trip_pricing_i66 TO loader_writer;

COMMIT;

-- Backfill pass -- run this block once before the loader deploy, and once
-- again after it (see header). ON CONFLICT DO NOTHING is what makes both
-- runs safe.

INSERT INTO trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key, ingested_at
)
SELECT
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key, ingested_at
FROM trip_pricing
WHERE feed = 'i95'
ON CONFLICT DO NOTHING;

INSERT INTO trip_pricing_i66 (
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, s3_key, ingested_at
)
SELECT
    interval_start_at, interval_end_at, calculated_at, corridor_id,
    corridor_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, s3_key, ingested_at
FROM trip_pricing
WHERE feed = 'i66'
ON CONFLICT DO NOTHING;

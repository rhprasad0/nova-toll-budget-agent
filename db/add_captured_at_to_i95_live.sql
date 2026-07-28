-- Migration A of two: re-key trip_pricing_i95_live on our own capture tick
-- instead of the source's hour-truncated label (see db/schema.sql, schema
-- version 4.0.0).
--
-- Transurban's prices change on every 10-minute poll, but its shared "time"
-- field is truncated to the hour and never advances mid-hour. With
-- PRIMARY KEY (observed_at, od_pair_id) and an ON CONFLICT DO UPDATE, each
-- hour's six captures overwrote one another -- prod held 59 snapshots for ~59
-- hours of coverage where 284 were captured. Full measurement in
-- docs/feed-cadence-tasks.md.
--
--     psql "$NOVA_TOLL_URL" -f db/add_captured_at_to_i95_live.sql
--
-- RUN ORDER (the two constraints below pull in opposite directions, which is
-- why captured_at carries a DEFAULT here that Migration B removes):
--   1. this file, against live RDS
--   2. deploy the loader that populates captured_at and conflicts on it
--      -- ON CONFLICT (captured_at, od_pair_id) needs the constraint this
--      file adds, so the deploy cannot come first
--   3. db/drop_captured_at_default_i95_live.sql
--
-- Between 1 and 2 the currently-deployed loader keeps inserting without
-- captured_at; the DEFAULT covers it, and those rows still land on distinct
-- keys, so nothing overwrites even mid-rollout. Keep that window short.
--
-- Safe to re-run: every statement is guarded.

BEGIN;

-- to_timestamp() below reads the session TimeZone, and the tick in an S3 key
-- is always UTC. Without this the backfill silently lands in local time.
SET LOCAL TimeZone = 'UTC';

ALTER TABLE trip_pricing_i95_live
    ADD COLUMN IF NOT EXISTS captured_at timestamptz NOT NULL DEFAULT now();

-- Each surviving row's s3_key is its hour's *last* capture -- which is exactly
-- the capture whose price the row still holds, since DO UPDATE overwrote
-- s3_key alongside price_usd. So this recovers the true capture time for the
-- rows that survived; it does not invent one. The captures that were
-- overwritten are not recoverable from this table (their payloads are still in
-- S3, deliberately not replayed here -- forward-only by decision).
UPDATE trip_pricing_i95_live
SET captured_at = to_timestamp(
        substring(s3_key from 'date=(\d{4}-\d{2}-\d{2})') || ' ' ||
        substring(s3_key from '(\d{4})Z\.json$'),
        'YYYY-MM-DD HH24MI'
    )
WHERE s3_key ~ 'date=\d{4}-\d{2}-\d{2}/\d{4}Z\.json$';

-- Fails the transaction rather than the PK swap below, so a surprise leaves
-- the table untouched with a message naming the problem.
DO $$
DECLARE dupes bigint;
BEGIN
    SELECT count(*) INTO dupes FROM (
        SELECT 1 FROM trip_pricing_i95_live
        GROUP BY captured_at, od_pair_id HAVING count(*) > 1
    ) t;
    IF dupes > 0 THEN
        RAISE EXCEPTION
            '(captured_at, od_pair_id) is not unique across % existing group(s) '
            '-- backfill did not produce a usable key', dupes;
    END IF;
END $$;

ALTER TABLE trip_pricing_i95_live
    DROP CONSTRAINT IF EXISTS trip_pricing_i95_live_pkey;
ALTER TABLE trip_pricing_i95_live
    ADD PRIMARY KEY (captured_at, od_pair_id);

-- Plain CREATE INDEX, not CONCURRENTLY (which db/add_pricing_read_indexes.sql
-- uses and which cannot run in a transaction block): this table is ~16k rows
-- and the PK swap above already holds ACCESS EXCLUSIVE for the same
-- transaction, so there is no lock window to protect here.
DROP INDEX IF EXISTS trip_pricing_i95_live_od_lookup_idx;
CREATE INDEX IF NOT EXISTS trip_pricing_i95_live_od_lookup_idx
    ON trip_pricing_i95_live (od_pair_id, captured_at DESC);

COMMIT;

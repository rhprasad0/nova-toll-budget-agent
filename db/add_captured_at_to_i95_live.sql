-- Re-key trip_pricing_i95_live on our own capture tick instead of the source's
-- hour-truncated label (see db/schema.sql, schema version 4.0.0).
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
-- RUN THIS IMMEDIATELY BEFORE DEPLOYING THE MATCHING LOADER. There is an
-- unavoidable window and it is a hard failure, not a soft one: the currently
-- deployed loader says ON CONFLICT (observed_at, od_pair_id), and the moment
-- this file drops that primary key Postgres rejects every i95-live insert with
-- "no unique or exclusion constraint matching the ON CONFLICT specification".
-- The two constraints cannot be satisfied at once -- keeping the old key alive
-- through the window would instead make the *new* loader fail, since six rows
-- an hour violate uniqueness on (observed_at, od_pair_id). So:
--
--   * expect toll-loader-errors to fire if the window runs long
--   * failed objects land in the OnFailure queue and stay in S3, so anything
--     missed is replayable afterwards
--   * i95 and i66 load as separate invocations and are unaffected
--
-- Safe to re-run: every statement is guarded.

BEGIN;

-- to_timestamp() below reads the session TimeZone, and the tick in an S3 key
-- is always UTC. Without this the backfill silently lands in local time.
SET LOCAL TimeZone = 'UTC';

-- Added nullable, then set NOT NULL after the backfill. A NOT NULL column
-- needs a DEFAULT to be added to a non-empty table, and an earlier draft used
-- DEFAULT now() to keep the old loader alive mid-rollout -- pointless, since
-- the ON CONFLICT clause breaks anyway (see header). No default means no
-- second migration to remove it, and no risk of a future INSERT silently
-- recording load time as capture time.
ALTER TABLE trip_pricing_i95_live ADD COLUMN IF NOT EXISTS captured_at timestamptz;

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
WHERE captured_at IS NULL
  AND s3_key ~ 'date=\d{4}-\d{2}-\d{2}/\d{4}Z\.json$';

-- Fail the whole transaction rather than the PK swap below, so a surprise
-- leaves the table untouched with a message naming the problem.
DO $$
DECLARE unfilled bigint; dupes bigint;
BEGIN
    SELECT count(*) INTO unfilled
        FROM trip_pricing_i95_live WHERE captured_at IS NULL;
    IF unfilled > 0 THEN
        RAISE EXCEPTION
            '% row(s) have no captured_at -- their s3_key does not match the '
            'expected raw-object key shape', unfilled;
    END IF;

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

ALTER TABLE trip_pricing_i95_live ALTER COLUMN captured_at SET NOT NULL;

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

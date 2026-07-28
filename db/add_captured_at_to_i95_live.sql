-- Re-key trip_pricing_i95_live on our capture tick instead of the source's
-- hour-truncated label (db/schema.sql, schema version 4.0.0). Transurban's
-- prices change every 10 minutes but its "time" field is hourly, so the old
-- (observed_at, od_pair_id) key let each hour's six captures overwrite one
-- another. Measurement: docs/feed-cadence-tasks.md.
--
--     psql "$NOVA_TOLL_URL" -f db/add_captured_at_to_i95_live.sql
--
-- RUN IMMEDIATELY BEFORE DEPLOYING THE MATCHING LOADER. The deployed loader
-- says ON CONFLICT (observed_at, od_pair_id); the moment this drops that key,
-- every i95-live insert fails. No ordering avoids it -- keeping the old key
-- would break the new loader instead. Missed objects stay in S3, replayable.
--
-- Safe to re-run.

BEGIN;

-- to_timestamp() reads the session TimeZone; S3 key ticks are always UTC.
SET LOCAL TimeZone = 'UTC';

ALTER TABLE trip_pricing_i95_live ADD COLUMN IF NOT EXISTS captured_at timestamptz;

-- Each surviving row's s3_key is its hour's last capture -- the one whose price
-- the row still holds, since DO UPDATE overwrote s3_key alongside price_usd.
-- Recovers the real capture time for survivors; the overwritten captures are
-- not recoverable from this table (forward-only by decision).
UPDATE trip_pricing_i95_live
SET captured_at = to_timestamp(
        substring(s3_key from 'date=(\d{4}-\d{2}-\d{2})') || ' ' ||
        substring(s3_key from '(\d{4})Z\.json$'),
        'YYYY-MM-DD HH24MI'
    )
WHERE captured_at IS NULL
  AND s3_key ~ 'date=\d{4}-\d{2}-\d{2}/\d{4}Z\.json$';

-- SET NOT NULL catches an unbackfilled row and ADD PRIMARY KEY catches a
-- duplicate, both aborting the transaction and naming the offending row.
ALTER TABLE trip_pricing_i95_live ALTER COLUMN captured_at SET NOT NULL;

ALTER TABLE trip_pricing_i95_live
    DROP CONSTRAINT IF EXISTS trip_pricing_i95_live_pkey;
ALTER TABLE trip_pricing_i95_live
    ADD PRIMARY KEY (captured_at, od_pair_id);

-- Plain CREATE INDEX: ~16k rows, and the PK swap above already holds ACCESS
-- EXCLUSIVE in this transaction, so CONCURRENTLY would protect nothing.
DROP INDEX IF EXISTS trip_pricing_i95_live_od_lookup_idx;
CREATE INDEX IF NOT EXISTS trip_pricing_i95_live_od_lookup_idx
    ON trip_pricing_i95_live (od_pair_id, captured_at DESC);

COMMIT;

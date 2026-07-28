-- Migration B of two: remove the temporary DEFAULT on
-- trip_pricing_i95_live.captured_at (see db/schema.sql, schema version 4.0.0).
--
-- db/add_captured_at_to_i95_live.sql gave the column a DEFAULT now() purely so
-- the then-deployed loader, which knew nothing about captured_at, could keep
-- inserting during the rollout. Once the new loader is live and supplies the
-- value explicitly, the default is a hazard rather than a help: it would let a
-- future INSERT that forgets the column silently record load time as capture
-- time. db/schema.sql declares the column NOT NULL with no default, and this
-- brings the live database back in line with it.
--
--     psql "$NOVA_TOLL_URL" -f db/drop_captured_at_default_i95_live.sql
--
-- Run only AFTER the loader deploy. Safe to re-run.

BEGIN;

ALTER TABLE trip_pricing_i95_live ALTER COLUMN captured_at DROP DEFAULT;

COMMIT;

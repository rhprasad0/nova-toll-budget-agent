-- Destructive cleanup is deliberately separate from operational rollback.
-- Disable the v2 EventBridge rule first, then pass -v drop_pricing_confirmed=yes.

\set ON_ERROR_STOP on

\if :{?drop_pricing_confirmed}
SELECT :'drop_pricing_confirmed' = 'yes' AS pricing_drop_confirmed \gset
\else
DO $$
BEGIN
  RAISE EXCEPTION 'drop_pricing_confirmed is required';
END $$;
\endif

\if :pricing_drop_confirmed
\else
DO $$
BEGIN
  RAISE EXCEPTION 'refusing to drop pricing without drop_pricing_confirmed=yes';
END $$;
\endif

\ir verify_backfill.sql

BEGIN;
REVOKE USAGE ON SCHEMA pricing FROM pricing_loader_writer, pricing_reader;
DROP SCHEMA pricing CASCADE;
COMMIT;

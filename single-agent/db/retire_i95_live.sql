-- Retire the Transurban live-price table without deleting its historical rows.
-- Run once, after the toll-express-fetcher and i95-live loader path are gone.
-- New databases use db/schema.sql and never create this table.

\set ON_ERROR_STOP on

BEGIN;

DO $$ BEGIN
  IF to_regclass('public.trip_pricing_i95_live') IS NOT NULL
     AND EXISTS (SELECT FROM pg_roles WHERE rolname = 'loader_writer') THEN
    EXECUTE 'REVOKE ALL ON TABLE trip_pricing_i95_live FROM loader_writer';
    EXECUTE $comment$
      COMMENT ON TABLE trip_pricing_i95_live IS
      'Retired 2026-07-30; retained as inert Transurban live-price history'
    $comment$;
  END IF;
END $$;

COMMIT;

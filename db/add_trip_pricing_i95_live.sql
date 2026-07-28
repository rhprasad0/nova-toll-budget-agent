-- One-shot addition of trip_pricing_i95_live (see db/schema.sql, schema
-- version 3.1.0). Unlike db/split_trip_pricing.sql this isn't a cutover from
-- an existing table -- it's a brand new table with no backfill pass, so the
-- CREATE + GRANT below is the whole migration, run once against live RDS,
-- before the toll-express-fetcher/toll-loader deploy that starts writing to
-- it (tables without grants even briefly would 403 the first poll).
--
-- The CREATE TABLE block that used to live here has been REMOVED, on this
-- file's own former instruction ("If schema.sql's DDL for this table ever
-- changes, update it here too, or just run schema.sql first and delete the
-- CREATE TABLE block"). Schema 4.0.0 re-keyed the table on captured_at
-- (db/add_captured_at_to_i95_live.sql), and a stale copy here would have
-- recreated the OLD primary key against a fresh database -- reintroducing the
-- overwrite bug in exactly the place nobody would look for it.
--
-- Run db/schema.sql to create the table, then this file for the grant.
--
--     psql "$NOVA_TOLL_URL" -f db/add_trip_pricing_i95_live.sql
--
-- Safe to run more than once: GRANT is idempotent.

BEGIN;

GRANT SELECT, INSERT, UPDATE ON trip_pricing_i95_live TO loader_writer;

COMMIT;

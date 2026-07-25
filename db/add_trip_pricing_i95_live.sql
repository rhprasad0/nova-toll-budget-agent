-- One-shot addition of trip_pricing_i95_live (see db/schema.sql, schema
-- version 3.1.0). Unlike db/split_trip_pricing.sql this isn't a cutover from
-- an existing table -- it's a brand new table with no backfill pass, so the
-- CREATE + GRANT below is the whole migration, run once against live RDS,
-- before the toll-express-fetcher/toll-loader deploy that starts writing to
-- it (tables without grants even briefly would 403 the first poll).
--
-- The CREATE TABLE statement is duplicated from db/schema.sql (needed here so
-- this file is runnable standalone against a DB that hasn't had schema.sql
-- re-applied yet). If schema.sql's DDL for this table ever changes, update it
-- here too, or just run schema.sql first and delete the CREATE TABLE block
-- from this file.
--
--     psql "$NOVA_TOLL_URL" -f db/add_trip_pricing_i95_live.sql
--
-- Safe to run more than once: CREATE TABLE IF NOT EXISTS is idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS trip_pricing_i95_live (
    observed_at        timestamptz NOT NULL,
    od_pair_id         integer NOT NULL,
    price_usd          numeric(10,2) NOT NULL,
    status             text,
    road               text,
    direction          text,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (observed_at, od_pair_id)
);

GRANT SELECT, INSERT, UPDATE ON trip_pricing_i95_live TO loader_writer;

COMMIT;

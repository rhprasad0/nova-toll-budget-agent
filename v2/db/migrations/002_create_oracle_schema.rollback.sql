-- Destructive rollback for the independent TollChat v2 routing oracle.
-- Invoke with: psql --set drop_oracle_confirmed=yes --file ...

\set ON_ERROR_STOP on

\if :{?drop_oracle_confirmed}
SELECT :'drop_oracle_confirmed' = 'yes' AS oracle_drop_confirmed \gset
\else
DO $$
BEGIN
    RAISE EXCEPTION 'drop_oracle_confirmed is required';
END $$;
\endif

\if :oracle_drop_confirmed
\else
DO $$
BEGIN
    RAISE EXCEPTION 'refusing to drop oracle without drop_oracle_confirmed=yes';
END $$;
\endif

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;

DROP EXTENSION IF EXISTS postgis CASCADE;
DROP SCHEMA IF EXISTS oracle CASCADE;

COMMIT;

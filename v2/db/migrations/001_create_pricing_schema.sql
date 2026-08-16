-- Additive live preparation for the independent TollChat v2 pricing schema.
-- This creates empty v2 objects. Run the shadow loader before backfill.sql.

\set ON_ERROR_STOP on

\ir ../schema.sql
\ir ../roles.sql

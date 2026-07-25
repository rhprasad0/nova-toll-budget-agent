-- One-shot teardown of the agent surface: the toll graph tables, the public
-- graph views, the agent_readonly role, and the three trip_pricing indexes
-- that existed only to serve agent queries.
--
-- Context: we reversed course on letting the agent query the database
-- directly, so db/graph.sql, db/roles.sql's agent_readonly block and the tool
-- code are all deleted from the repo. This drops what those already created in
-- a live database. The poller/loader pipeline is untouched: trip_pricing, its
-- unique constraint and loader_writer all survive.
--
-- Idempotent (IF EXISTS throughout), so re-running is safe.
--
--     psql "$NOVA_TOLL_URL" -f db/drop_agent_surface.sql
--
-- NOTE: this file must NOT be wrapped in a single BEGIN/COMMIT. DROP INDEX
-- CONCURRENTLY cannot run inside a transaction block, and the indexes were
-- created CONCURRENTLY (db/schema.sql, before this cleanup) specifically to
-- avoid locking a table the poller writes to every 10 minutes. Dropping them
-- non-concurrently would take an ACCESS EXCLUSIVE lock and can stall a loader
-- invocation. So: the DDL below runs in one transaction, the index drops run
-- outside it, one statement at a time.

BEGIN;

DROP VIEW IF EXISTS public_graph_node;
DROP VIEW IF EXISTS public_graph_edge;

-- graph_node_alias and graph_edge both reference graph_node, so order matters.
DROP TABLE IF EXISTS graph_node_alias;
DROP TABLE IF EXISTS graph_edge;
DROP TABLE IF EXISTS graph_node;

-- agent_readonly also held SELECT on trip_pricing, so dropping the role is
-- what actually removes the agent's database access. Postgres refuses to drop
-- a role that still holds privileges, and the graph grants vanish with the
-- objects above but trip_pricing's does not. DROP OWNED BY revokes every
-- remaining grant held by the role in this database, which is the whole of
-- what agent_readonly has -- it owns no objects.
--
-- Do NOT add `REVOKE rds_iam FROM agent_readonly` here. DROP ROLE clears role
-- *membership* on its own, and naming rds_iam explicitly makes the script
-- unrunnable anywhere that RDS-managed role doesn't exist -- which aborts the
-- transaction and silently leaves everything above undropped.
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_readonly') THEN
    DROP OWNED BY agent_readonly;
    DROP ROLE agent_readonly;
  END IF;
END $$;

COMMIT;

-- Outside the transaction, for the reason in the header note.
DROP INDEX CONCURRENTLY IF EXISTS trip_pricing_price_lookup_covering_idx;
DROP INDEX CONCURRENTLY IF EXISTS trip_pricing_od_latest_idx;
DROP INDEX CONCURRENTLY IF EXISTS trip_pricing_zone_latest_idx;

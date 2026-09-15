-- Add durable scheduled evaluation history; requires the separately provisioned eval_writer role.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-pricing-schema-version'));
SELECT version = '1.3.0' AS needs_upgrade FROM pricing.schema_version WHERE singleton\gset
DO $$ BEGIN
    IF (SELECT version FROM pricing.schema_version WHERE singleton) NOT IN ('1.3.0', '1.4.0') THEN
        RAISE EXCEPTION 'expected pricing version 1.3.0 or 1.4.0';
    END IF;
END $$;
\if :needs_upgrade
CREATE TABLE pricing.evaluation_runs (
    environment text NOT NULL CHECK (environment IN ('development', 'production')),
    window_id text NOT NULL CHECK (window_id IN ('i95_northbound', 'i95_southbound', 'i95_reversal', 'greenway_eb_peak', 'greenway_wb_peak')),
    scheduled_at timestamptz NOT NULL,
    scenario_id text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'error', 'stale')),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
    PRIMARY KEY (environment, window_id, scheduled_at)
);
CREATE INDEX evaluation_runs_latest ON pricing.evaluation_runs (environment, scenario_id, scheduled_at DESC);

GRANT USAGE ON SCHEMA pricing TO eval_writer;
GRANT SELECT, INSERT, UPDATE ON pricing.evaluation_runs TO eval_writer;
UPDATE pricing.schema_version SET version = '1.4.0', installed_at = now() WHERE singleton;
\endif
COMMIT;

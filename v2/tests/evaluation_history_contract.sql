\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE eval_writer;
INSERT INTO pricing.evaluation_runs
  (environment, window_id, scheduled_at, scenario_id, started_at, status)
VALUES ('development', 'i95_southbound', '2026-09-15 18:17Z', 'test', now(), 'running');
INSERT INTO pricing.evaluation_runs
  (environment, window_id, scheduled_at, scenario_id, started_at, status)
VALUES ('development', 'i95_southbound', '2026-09-15 18:17Z', 'test', now(), 'running')
ON CONFLICT DO NOTHING;
UPDATE pricing.evaluation_runs SET status='passed', finished_at=now(), evidence='{"checks":[]}'
WHERE scenario_id='test';
DO $$ BEGIN
  IF (SELECT count(*) FROM pricing.evaluation_runs WHERE scenario_id='test') <> 1 THEN
    RAISE EXCEPTION 'duplicate occurrence';
  END IF;
  IF has_table_privilege(current_user,'pricing.trip_pricing_i95','INSERT')
     OR has_table_privilege(current_user,'pricing.trip_pricing_i95','SELECT')
     OR has_table_privilege(current_user,'pricing.evaluation_runs','DELETE') THEN
    RAISE EXCEPTION 'evaluation writer has unrelated privileges';
  END IF;
END $$;
RESET ROLE;
DO $$ BEGIN
  IF has_table_privilege('tollchat_agent','pricing.evaluation_runs','INSERT')
     OR has_table_privilege('pricing_caller','pricing.evaluation_runs','UPDATE') THEN
    RAISE EXCEPTION 'application agent can alter evaluation history';
  END IF;
END $$;
ROLLBACK;

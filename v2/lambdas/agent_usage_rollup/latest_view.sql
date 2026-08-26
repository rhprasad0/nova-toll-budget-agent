CREATE OR REPLACE VIEW latest_agent_report_usage AS
WITH latest AS (
    SELECT report_date, max_by(run_id, completed_at) AS run_id
    FROM agent_report_rollup_completions
    GROUP BY report_date
)
SELECT usage.*
FROM agent_report_rollups usage
JOIN latest
  ON usage.report_date = latest.report_date
 AND usage.run_id = latest.run_id

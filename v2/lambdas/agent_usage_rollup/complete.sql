INSERT INTO agent_report_rollup_completions
SELECT
    current_timestamp AS completed_at,
    DATE '{report_date}' AS report_date,
    '{run_id}' AS run_id

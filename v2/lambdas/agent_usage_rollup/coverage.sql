SELECT count(DISTINCT httprequest.requestid)
FROM agent_report_waf_logs
WHERE log_date = replace('{report_date}', '-', '/')
  AND any_match(labels, label -> label.name LIKE '%:agent-route-report')

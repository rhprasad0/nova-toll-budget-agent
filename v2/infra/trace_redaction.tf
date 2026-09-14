# Additional masking is a backstop to pre-export application redaction.
resource "aws_cloudwatch_log_data_protection_policy" "agentcore" {
  for_each        = aws_cloudwatch_log_group.agentcore_runtime
  log_group_name  = each.value.name
  policy_document = local.telemetry_log_policy
}

resource "aws_cloudwatch_log_metric_filter" "telemetry_redaction" {
  for_each       = aws_cloudwatch_log_group.agentcore_runtime
  name           = "tollchat-redaction-failures"
  log_group_name = each.value.name
  pattern        = "?telemetry_redaction_failed ?telemetry_redaction_omitted ?telemetry_export_failed"
  metric_transformation {
    name      = "RedactionFailures"
    namespace = "TollChat/Telemetry"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "telemetry_redaction" {
  alarm_name          = "tollchat-v2-redaction-failures${local.suffix}"
  alarm_description   = "Telemetry content was omitted or export failed; investigate without logging raw payloads."
  namespace           = "TollChat/Telemetry"
  metric_name         = "RedactionFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "telemetry_pii" {
  for_each            = aws_cloudwatch_log_group.agentcore_runtime
  alarm_name          = "tollchat-v2-pii-findings-${each.key}${local.suffix}"
  alarm_description   = "CloudWatch detected sensitive data after application telemetry redaction."
  namespace           = "AWS/Logs"
  metric_name         = "LogEventsWithFindings"
  dimensions          = { LogGroupName = each.value.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

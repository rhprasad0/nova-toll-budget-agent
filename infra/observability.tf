resource "aws_sns_topic" "alerts" {
  name = "nova-toll-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "rhprasad@outlook.com"
}

# Loader logs "LOAD_OK <feed>" (space-delimited, not JSON — see spec) after
# each committed upsert; this turns that into NovaToll/LoadSuccess{feed}.
resource "aws_cloudwatch_log_metric_filter" "load_success" {
  name           = "LoadSuccess"
  log_group_name = aws_cloudwatch_log_group.loader.name
  # The loader's root logger prepends "[INFO]<tab>timestamp<tab>request_id<tab>"
  # to the "LOAD_OK <feed>" line, so the match must skip those leading fields
  # (...) before anchoring on LOAD_OK and capturing feed. A 2-field pattern
  # never matches the real 5-field line and silently starves the freshness alarm.
  pattern = "[..., event=\"LOAD_OK\", feed]"

  metric_transformation {
    namespace = "NovaToll"
    name      = "LoadSuccess"
    value     = "1"
    dimensions = {
      feed = "$feed"
    }
    # No default_value: CloudWatch rejects it alongside dimensions, and the
    # freshness alarm is treat-missing-data=breaching — absence of a LOAD_OK
    # datapoint IS the signal, so emitting 0 would defeat it.
  }
}

# 1. toll-fetcher errors
resource "aws_cloudwatch_metric_alarm" "fetcher_errors" {
  alarm_name          = "toll-fetcher-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.fetcher.function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# 2. toll-loader errors
resource "aws_cloudwatch_metric_alarm" "loader_errors" {
  alarm_name          = "toll-loader-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.loader.function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# 3. Freshness — NovaToll/LoadSuccess missing 30 min, per feed. The most
# important alarm: silently losing irreplaceable polls.
resource "aws_cloudwatch_metric_alarm" "freshness" {
  for_each = toset(["i95", "i66"])

  alarm_name          = "toll-freshness-${each.key}"
  namespace           = "NovaToll"
  metric_name         = "LoadSuccess"
  dimensions          = { feed = each.key }
  period              = 600
  evaluation_periods  = 3
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# 4. Loader OnFailure queue — exhausted async retries need replay, not silence.
resource "aws_cloudwatch_metric_alarm" "onfailure_queue" {
  alarm_name          = "toll-loader-onfailure-queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.loader_onfailure.name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Maximum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# 5. RDS free storage
resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "toll-rds-free-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Average"
  threshold           = 2 * 1024 * 1024 * 1024 # 2 GB
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_sns_topic" "alerts" {
  name              = "nova-toll-alerts"
  kms_master_key_id = aws_kms_key.alerts.arn
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "bills@ryanprasad.ai"
}

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

resource "aws_cloudwatch_metric_alarm" "bucket_storage" {
  for_each = {
    raw     = aws_s3_bucket.raw.id
    tfstate = aws_s3_bucket.tfstate.id
  }
  alarm_name          = "nova-toll-${each.key}-storage-10gb"
  namespace           = "AWS/S3"
  metric_name         = "BucketSizeBytes"
  dimensions          = { BucketName = each.value, StorageType = "StandardStorage" }
  period              = 86400
  evaluation_periods  = 1
  statistic           = "Average"
  threshold           = 10 * 1024 * 1024 * 1024
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "toll-rds-free-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Average"
  threshold           = 2 * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "toll-rds-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 5
  statistic           = "Average"
  threshold           = 70
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_free_memory" {
  alarm_name          = "toll-rds-free-memory"
  namespace           = "AWS/RDS"
  metric_name         = "FreeableMemory"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  statistic           = "Minimum"
  threshold           = 64 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "toll-rds-connections"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  statistic           = "Maximum"
  threshold           = 60
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu_credits" {
  alarm_name          = "toll-rds-cpu-credits"
  namespace           = "AWS/RDS"
  metric_name         = "CPUCreditBalance"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  statistic           = "Minimum"
  threshold           = 72
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

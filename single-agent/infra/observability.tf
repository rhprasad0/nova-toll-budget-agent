resource "aws_sns_topic" "alerts" {
  name              = "nova-toll-alerts"
  kms_master_key_id = aws_kms_key.alerts.arn
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "bills@ryanprasad.ai"
}

# Runtime records are application-sanitized; vended APPLICATION_LOGS would
# duplicate raw InvokeRuntimeOperation payloads before that sanitization.
resource "aws_cloudwatch_log_group" "tollchat_trace_records" {
  name              = "/aws/nova-toll/agentcore/traces"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.agentcore_telemetry.arn
}

removed {
  from = aws_cloudwatch_log_group.agentcore_spans

  lifecycle {
    destroy = false
  }
}

resource "aws_xray_trace_segment_destination" "transaction_search" {
  destination = "CloudWatchLogs"

  depends_on = [aws_cloudwatch_log_resource_policy.transaction_search]
}

# X-Ray creates the reserved aws/spans group; CloudWatch rejects direct CreateLogGroup
# calls for aws/* names. Configure the service-owned group after the destination is active.
resource "terraform_data" "agentcore_spans_log_group" {
  triggers_replace = {
    kms_key_arn = aws_kms_key.agentcore_telemetry.arn
    retention   = "30"
  }

  provisioner "local-exec" {
    command = "${path.module}/../scripts/configure_agentcore_spans_log_group.sh '${local.agentcore_spans_log_group_name}' '${aws_kms_key.agentcore_telemetry.arn}' 30"
  }

  depends_on = [aws_xray_trace_segment_destination.transaction_search]
}

# Transaction Search indexes a representative 1% while every sampled span is
# retained in aws/spans; OTEL_TRACES_SAMPLER=always_on supplies the capture rate.
resource "aws_xray_indexing_rule" "transaction_search_default" {
  name = "Default"

  rule {
    probabilistic {
      desired_sampling_percentage = 1.0
    }
  }
}

# Runtime tracing is a CloudWatch delivery, separate from vended
# APPLICATION_LOGS. The latter stays disabled because it duplicates raw
# invocation request/response payloads before application sanitization.
resource "aws_cloudwatch_log_delivery_source" "tollchat_runtime_traces" {
  name         = "nova-toll-runtime-traces"
  log_type     = "TRACES"
  resource_arn = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "tollchat_runtime_traces" {
  name                      = "nova-toll-runtime-traces"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "tollchat_runtime_traces" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.tollchat_runtime_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.tollchat_runtime_traces.arn

  depends_on = [aws_xray_trace_segment_destination.transaction_search]
}

data "aws_iam_policy_document" "transaction_search" {
  statement {
    sid     = "TransactionSearchXRayAccess"
    actions = ["logs:PutLogEvents"]
    resources = [
      "${local.agentcore_spans_log_group_arn}:*",
      "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/application-signals/data:*",
    ]
    principals {
      type        = "Service"
      identifiers = ["xray.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:xray:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "transaction_search" {
  policy_name     = "nova-toll-transaction-search"
  policy_document = data.aws_iam_policy_document.transaction_search.json
}

locals {
  agentcore_spans_log_group_name = "aws/spans"
  agentcore_spans_log_group_arn  = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:${local.agentcore_spans_log_group_name}"
  agentcore_telemetry_log_groups = {
    trace_records = aws_cloudwatch_log_group.tollchat_trace_records.name
    spans         = local.agentcore_spans_log_group_name
  }
}

resource "aws_cloudwatch_log_data_protection_policy" "agentcore_telemetry" {
  for_each = local.agentcore_telemetry_log_groups

  log_group_name = each.value
  policy_document = jsonencode({
    Name    = "nova-toll-agentcore-telemetry"
    Version = "2021-06-01"
    Statement = [
      {
        Sid = "AuditSensitiveData"
        DataIdentifier = [
          "arn:aws:dataprotection::aws:data-identifier/AwsSecretKey",
          "arn:aws:dataprotection::aws:data-identifier/EmailAddress",
        ]
        Operation = { Audit = { FindingsDestination = {} } }
      },
      {
        Sid = "MaskSensitiveData"
        DataIdentifier = [
          "arn:aws:dataprotection::aws:data-identifier/AwsSecretKey",
          "arn:aws:dataprotection::aws:data-identifier/EmailAddress",
        ]
        Operation = { Deidentify = { MaskConfig = {} } }
      },
    ]
  })

  depends_on = [terraform_data.agentcore_spans_log_group]
}

data "aws_iam_policy_document" "tollchat_trace_reviewer_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "tollchat_trace_reviewer" {
  name               = "nova-toll-trace-reviewer"
  assume_role_policy = data.aws_iam_policy_document.tollchat_trace_reviewer_assume.json
}

data "aws_iam_policy_document" "tollchat_trace_reviewer" {
  statement {
    sid = "ReadTelemetryLogs"
    actions = [
      "logs:DescribeLogStreams",
      "logs:FilterLogEvents",
      "logs:GetLogEvents",
      "logs:StartQuery",
      "logs:Unmask",
    ]
    resources = [
      "${aws_cloudwatch_log_group.tollchat_trace_records.arn}:*",
      "${local.agentcore_spans_log_group_arn}:*",
    ]
  }
  statement {
    sid       = "ReadQueryResults"
    actions   = ["logs:GetQueryResults"]
    resources = ["*"]
  }
  statement {
    sid = "RetrieveTransactionSearchTraces"
    actions = [
      "xray:GetRetrievedTracesGraph",
      "xray:ListRetrievedTraces",
      "xray:StartTraceRetrieval",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "tollchat_trace_reviewer" {
  name   = "nova-toll-trace-reviewer"
  role   = aws_iam_role.tollchat_trace_reviewer.id
  policy = data.aws_iam_policy_document.tollchat_trace_reviewer.json
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

# The proxy intentionally converts dependency and stream failures into the
# browser-safe error contract, so AWS/Lambda Errors cannot see them. Count the
# stable metadata-only marker while retaining Lambda Errors for timeouts and
# uncaught failures.
resource "aws_cloudwatch_log_metric_filter" "proxy_failure" {
  name           = "ProxyFailure"
  log_group_name = aws_cloudwatch_log_group.tollchat_proxy.name
  pattern        = "PROXY_FAILURE"

  metric_transformation {
    namespace = "NovaToll"
    name      = "ProxyFailure"
    value     = "1"
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
  alarm_description   = "No successful ${each.key} load for 30 minutes. Follow docs/runbooks/alarms.md."
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

# Raw payload and Terraform-state history is intentionally retained forever.
# BucketSizeBytes is emitted daily, so this is an early capacity/cost signal
# rather than a real-time usage alert.
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

resource "aws_cloudwatch_metric_alarm" "tollchat_proxy_errors" {
  alarm_name          = "tollchat-chat-proxy-errors"
  alarm_description   = "Proxy timeout or uncaught failure. Follow docs/runbooks/alarms.md."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.tollchat_proxy.function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "tollchat_proxy_failures" {
  alarm_name          = "tollchat-chat-proxy-failures"
  alarm_description   = "Proxy returned the safe dependency-failure contract. Follow docs/runbooks/alarms.md."
  namespace           = "NovaToll"
  metric_name         = "ProxyFailure"
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "tollchat_proxy_latency" {
  alarm_name          = "tollchat-chat-proxy-latency"
  alarm_description   = "Proxy p99 is within five seconds of its timeout. Follow docs/runbooks/alarms.md."
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = aws_lambda_function.tollchat_proxy.function_name }
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 1
  extended_statistic  = "p99"
  threshold           = 45 * 1000
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "tollchat_sessions" {
  alarm_name          = "tollchat-agentcore-active-sessions"
  alarm_description   = "AgentCore active sessions exceed the private baseline. Follow docs/runbooks/alarms.md."
  namespace           = "AWS/Bedrock-AgentCore"
  metric_name         = "ActiveSessionCount"
  dimensions          = { Service = "AgentCore.Runtime" }
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  statistic           = "Maximum"
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "toll-rds-cpu"
  alarm_description   = "RDS CPU stayed above the launch threshold. Follow docs/runbooks/alarms.md."
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
  alarm_description   = "RDS freeable memory is below the private baseline. Follow docs/runbooks/alarms.md."
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
  alarm_description   = "RDS connections reached 60 of the observed 79 maximum. Follow docs/runbooks/alarms.md."
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
  alarm_description   = "RDS CPU credits fell below 25 percent of the observed full balance. Follow docs/runbooks/alarms.md."
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

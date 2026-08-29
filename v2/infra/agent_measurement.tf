locals {
  agent_measurement_database = "tollchat_agent_reports${local.is_production ? "" : "_development"}"
  agent_measurement_bucket   = "aws-waf-logs-tollchat-agent-reports-${data.aws_caller_identity.current.account_id}${local.suffix}"
  agent_measurement_acl      = "tollchat-v2-public-chat${local.suffix}"
  agent_measurement_label    = "awswaf:${data.aws_caller_identity.current.account_id}:webacl:tollchat-v2-public-chat${local.suffix}:agent-route-report"
}

data "archive_file" "agent_usage_rollup" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/agent_usage_rollup"
  output_path = "${path.module}/build/agent-usage-rollup.zip"
  excludes    = ["tests", "__pycache__"]
}

resource "aws_s3_bucket" "agent_measurement" {
  bucket = local.agent_measurement_bucket
}

resource "aws_s3_bucket_public_access_block" "agent_measurement" {
  bucket                  = aws_s3_bucket.agent_measurement.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "agent_measurement_kms" {
  statement {
    sid       = "EnableAccountIamPolicies"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid       = "AllowWafLogDelivery"
    actions   = ["kms:GenerateDataKey*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:logs:us-east-1:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

resource "aws_kms_key" "agent_measurement" {
  description             = "TollChat agent-route measurement data"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.agent_measurement_kms.json
}

resource "aws_kms_alias" "agent_measurement" {
  name          = "alias/tollchat-v2-agent-measurement${local.suffix}"
  target_key_id = aws_kms_key.agent_measurement.key_id
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agent_measurement" {
  bucket = aws_s3_bucket.agent_measurement.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.agent_measurement.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "agent_measurement" {
  bucket = aws_s3_bucket.agent_measurement.id

  rule {
    id     = "expire-raw-waf-logs"
    status = "Enabled"
    filter { prefix = "AWSLogs/" }
    expiration { days = 7 }
  }

  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter { prefix = "athena-results/" }
    expiration { days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

data "aws_iam_policy_document" "agent_measurement_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.agent_measurement.arn,
      "${aws_s3_bucket.agent_measurement.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "AWSLogDeliveryAclCheck"
    actions   = ["s3:GetBucketAcl", "s3:ListBucket"]
    resources = [aws_s3_bucket.agent_measurement.arn]
    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:logs:us-east-1:${data.aws_caller_identity.current.account_id}:*"]
    }
  }

  statement {
    sid       = "AWSLogDeliveryWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.agent_measurement.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:logs:us-east-1:${data.aws_caller_identity.current.account_id}:*"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "agent_measurement" {
  bucket = aws_s3_bucket.agent_measurement.id
  policy = data.aws_iam_policy_document.agent_measurement_bucket.json
}

resource "aws_s3_object" "agent_registry" {
  bucket        = aws_s3_bucket.agent_measurement.id
  key           = "registry/agent_registry.ndjson"
  source        = "${path.module}/../analytics/agent_registry.ndjson"
  source_hash   = filebase64sha256("${path.module}/../analytics/agent_registry.ndjson")
  content_type  = "application/x-ndjson"
  cache_control = "no-store"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.agent_measurement]
}

resource "aws_wafv2_web_acl_logging_configuration" "agent_reports" {
  resource_arn            = aws_wafv2_web_acl.public_chat.arn
  log_destination_configs = [aws_s3_bucket.agent_measurement.arn]

  logging_filter {
    default_behavior = "DROP"
    filter {
      behavior    = "KEEP"
      requirement = "MEETS_ALL"
      condition {
        label_name_condition { label_name = local.agent_measurement_label }
      }
    }
  }

  redacted_fields {
    query_string {}
  }
  dynamic "redacted_fields" {
    for_each = toset(["cookie", "authorization", "referer"])
    content {
      single_header {
        name = redacted_fields.value
      }
    }
  }

  depends_on = [
    aws_s3_bucket_policy.agent_measurement,
    aws_s3_bucket_server_side_encryption_configuration.agent_measurement,
    aws_s3_object.privacy,
  ]
}

resource "aws_glue_catalog_database" "agent_reports" {
  name = local.agent_measurement_database
}

resource "aws_glue_catalog_table" "waf_logs" {
  name          = "agent_report_waf_logs"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    EXTERNAL                     = "TRUE"
    "projection.enabled"         = "true"
    "projection.log_date.type"   = "date"
    "projection.log_date.range"  = "2026/08/25,NOW"
    "projection.log_date.format" = "yyyy/MM/dd"
    "projection.log_hour.type"   = "integer"
    "projection.log_hour.range"  = "0,23"
    "projection.log_hour.digits" = "2"
    # CloudFront-scoped WAF logs use this literal scope token, not the region name.
    "storage.location.template" = "s3://${aws_s3_bucket.agent_measurement.id}/AWSLogs/${data.aws_caller_identity.current.account_id}/WAFLogs/cloudfront/${local.agent_measurement_acl}/$${log_date}/$${log_hour}/"
  }

  dynamic "partition_keys" {
    for_each = toset(["log_date", "log_hour"])
    content {
      name = partition_keys.value
      type = "string"
    }
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/AWSLogs/${data.aws_caller_identity.current.account_id}/WAFLogs/cloudfront/${local.agent_measurement_acl}/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    dynamic "columns" {
      for_each = {
        timestamp           = "bigint"
        formatversion       = "int"
        webaclid            = "string"
        terminatingruleid   = "string"
        terminatingruletype = "string"
        action              = "string"
        labels              = "array<struct<name:string>>"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
    columns {
      name = "httprequest"
      type = "struct<clientip:string,country:string,headers:array<struct<name:string,value:string>>,uri:string,args:string,httpversion:string,httpmethod:string,requestid:string,fragment:string,scheme:string,host:string>"
    }

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }
  }
}

resource "aws_glue_catalog_table" "agent_registry" {
  name          = "agent_registry"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE" }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/registry/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    dynamic "columns" {
      for_each = toset(["vendor_family", "user_agent_token", "agent_mode", "documentation_url"])
      content {
        name = columns.value
        type = "string"
      }
    }
    ser_de_info { serialization_library = "org.openx.data.jsonserde.JsonSerDe" }
  }
}

resource "aws_glue_catalog_table" "agent_report_generations" {
  name          = "agent_report_generations"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE" }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/generations/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    dynamic "columns" {
      for_each = {
        schema_version = "int"
        facility       = "string"
        generation_id  = "string"
        published_at   = "string"
        result_sha256  = "string"
        route_keys     = "array<string>"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
    ser_de_info { serialization_library = "org.openx.data.jsonserde.JsonSerDe" }
  }
}

resource "aws_glue_catalog_table" "agent_report_rollups" {
  name          = "agent_report_rollups"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE", classification = "parquet" }

  dynamic "partition_keys" {
    for_each = { report_date = "date", run_id = "string" }
    content {
      name = partition_keys.key
      type = partition_keys.value
    }
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/rollups/usage/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    dynamic "columns" {
      for_each = [
        { name = "first_requested_at", type = "timestamp" },
        { name = "last_requested_at", type = "timestamp" },
        { name = "request_count", type = "bigint" },
        { name = "published_generation_age_seconds", type = "bigint" },
        { name = "origin_slug", type = "string" },
        { name = "destination_slug", type = "string" },
        { name = "representation", type = "string" },
        { name = "traffic_class", type = "string" },
        { name = "vendor_family", type = "string" },
        { name = "identity_confidence", type = "string" },
        { name = "aws_bot_name", type = "string" },
        { name = "aws_organization", type = "string" },
        { name = "aws_category", type = "string" },
        { name = "waf_action", type = "string" },
        { name = "generation_id", type = "string" },
        { name = "published_at", type = "string" },
      ]
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
    ser_de_info { serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" }
  }
}

resource "aws_glue_catalog_table" "agent_report_rollup_completions" {
  name          = "agent_report_rollup_completions"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE", classification = "parquet" }

  dynamic "partition_keys" {
    for_each = { report_date = "date", run_id = "string" }
    content {
      name = partition_keys.key
      type = partition_keys.value
    }
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/rollups/completions/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    columns {
      name = "completed_at"
      type = "timestamp"
    }
    ser_de_info { serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" }
  }
}

resource "aws_athena_workgroup" "agent_reports" {
  name = "tollchat-agent-reports${local.suffix}"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824

    result_configuration {
      output_location       = "s3://${aws_s3_bucket.agent_measurement.id}/athena-results/"
      expected_bucket_owner = data.aws_caller_identity.current.account_id
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.agent_measurement.arn
      }
    }
  }
}

resource "aws_athena_named_query" "top_routes" {
  name        = "TollChat agent reports - top routes by day${local.suffix}"
  database    = aws_glue_catalog_database.agent_reports.name
  workgroup   = aws_athena_workgroup.agent_reports.name
  description = "Privacy-safe route and representation totals from completed rollups."
  query       = <<-SQL
    SELECT report_date, origin_slug, destination_slug, representation,
           traffic_class, vendor_family, sum(request_count) AS requests
    FROM latest_agent_report_usage
    GROUP BY 1, 2, 3, 4, 5, 6
    ORDER BY report_date DESC, requests DESC
  SQL
}

resource "aws_athena_named_query" "recent_routes" {
  name        = "TollChat agent reports - recent request times${local.suffix}"
  database    = aws_glue_catalog_database.agent_reports.name
  workgroup   = aws_athena_workgroup.agent_reports.name
  description = "Seven-day route timing drill-down without IP, user agent, referrer, cookie, or query string."
  query       = <<-SQL
    SELECT from_unixtime(timestamp / 1000.0) AS requested_at,
           httprequest.uri AS route_path,
           CASE WHEN httprequest.uri LIKE '%/report.json' THEN 'json' ELSE 'html' END AS representation,
           action AS waf_action
    FROM agent_report_waf_logs
    WHERE log_date >= date_format(current_date - interval '7' day, '%Y/%m/%d')
      AND httprequest.httpmethod = 'GET'
      AND (regexp_like(httprequest.uri, '^/tolls/i95-i495/[^/]+/[^/]+/$')
        OR regexp_like(httprequest.uri, '^/tolls/i95-i495/[^/]+/[^/]+/report[.]json$'))
    ORDER BY requested_at DESC
  SQL
}

resource "aws_iam_role" "agent_usage_rollup" {
  name               = "tollchat-v2-agent-usage-rollup${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "agent_usage_rollup" {
  statement {
    sid       = "RunQueries"
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"]
    resources = [aws_athena_workgroup.agent_reports.arn]
  }

  statement {
    sid = "ReadAndUpdateCatalog"
    actions = [
      "glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartition", "glue:GetPartitions",
      "glue:BatchCreatePartition", "glue:CreateTable", "glue:UpdateTable",
    ]
    resources = [
      "arn:aws:glue:us-east-1:${data.aws_caller_identity.current.account_id}:catalog",
      aws_glue_catalog_database.agent_reports.arn,
      "arn:aws:glue:us-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.agent_reports.name}/*",
    ]
  }

  statement {
    sid       = "ListMeasurementData"
    actions   = ["s3:GetBucketLocation", "s3:ListBucket"]
    resources = [aws_s3_bucket.agent_measurement.arn]
  }

  statement {
    sid     = "ReadMeasurementInputs"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.agent_measurement.arn}/AWSLogs/*",
      "${aws_s3_bucket.agent_measurement.arn}/registry/*",
      "${aws_s3_bucket.agent_measurement.arn}/generations/*",
      "${aws_s3_bucket.agent_measurement.arn}/rollups/*",
      "${aws_s3_bucket.agent_measurement.arn}/athena-results/*",
    ]
  }

  statement {
    sid     = "WriteMeasurementOutputs"
    actions = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [
      "${aws_s3_bucket.agent_measurement.arn}/rollups/*",
      "${aws_s3_bucket.agent_measurement.arn}/athena-results/*",
    ]
  }

  statement {
    sid       = "UseMeasurementKey"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.agent_measurement.arn]
  }

  statement {
    sid       = "CompareAndPublishCoverage"
    actions   = ["cloudwatch:GetMetricStatistics", "cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEqualsIfExists"
      variable = "cloudwatch:namespace"
      values   = ["TollChat/AgentReports"]
    }
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.agent_usage_rollup.arn}:*"]
  }
}

resource "aws_iam_role_policy" "agent_usage_rollup" {
  name   = "tollchat-v2-agent-usage-rollup${local.suffix}"
  role   = aws_iam_role.agent_usage_rollup.id
  policy = data.aws_iam_policy_document.agent_usage_rollup.json
}

resource "aws_cloudwatch_log_group" "agent_usage_rollup" {
  name              = "/aws/lambda/tollchat-v2-agent-usage-rollup${local.suffix}"
  retention_in_days = local.log_retention_days
}

resource "aws_lambda_function" "agent_usage_rollup" {
  function_name = "tollchat-v2-agent-usage-rollup${local.suffix}"
  role          = aws_iam_role.agent_usage_rollup.arn
  runtime       = "python3.13"
  handler       = "handler.handler"
  timeout       = 300
  memory_size   = 128

  filename         = data.archive_file.agent_usage_rollup.output_path
  source_code_hash = data.archive_file.agent_usage_rollup.output_base64sha256

  environment {
    variables = {
      ATHENA_DATABASE       = aws_glue_catalog_database.agent_reports.name
      ATHENA_WORKGROUP      = aws_athena_workgroup.agent_reports.name
      WAF_WEB_ACL_METRIC    = "tollchat-v2-public-chat${local.suffix}"
      WAF_ROUTE_RULE_METRIC = "tollchat-v2-agent-route-report${local.suffix}"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.agent_usage_rollup,
    aws_glue_catalog_table.agent_report_rollup_completions,
    aws_glue_catalog_table.agent_report_rollups,
    aws_iam_role_policy.agent_usage_rollup,
  ]
}

resource "aws_cloudwatch_event_rule" "agent_usage_rollup" {
  name                = "tollchat-v2-agent-usage-rollup${local.suffix}"
  schedule_expression = "cron(15 3 * * ? *)"
}

resource "aws_lambda_permission" "agent_usage_rollup" {
  statement_id  = "AllowEventBridgeInvokeAgentUsageRollup"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agent_usage_rollup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.agent_usage_rollup.arn
}

resource "aws_cloudwatch_event_target" "agent_usage_rollup" {
  rule = aws_cloudwatch_event_rule.agent_usage_rollup.name
  arn  = aws_lambda_function.agent_usage_rollup.arn
  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 2
  }
  depends_on = [aws_lambda_permission.agent_usage_rollup]
}

resource "aws_cloudwatch_metric_alarm" "agent_usage_rollup_errors" {
  alarm_name          = "tollchat-v2-agent-usage-rollup-errors${local.suffix}"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.agent_usage_rollup.function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "agent_usage_rollup_missing" {
  alarm_name          = "tollchat-v2-agent-usage-rollup-missing${local.suffix}"
  namespace           = "TollChat/AgentReports"
  metric_name         = "RollupCompleted"
  period              = 86400
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "agent_usage_log_coverage" {
  alarm_name          = "tollchat-v2-agent-usage-log-coverage${local.suffix}"
  namespace           = "TollChat/AgentReports"
  metric_name         = "LogCoveragePercent"
  period              = 86400
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  statistic           = "Minimum"
  threshold           = 95
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

output "agent_report_web_acl_arn" {
  description = "Web ACL measured by the internal agent-report analytics pipeline."
  value       = aws_wafv2_web_acl.public_chat.arn
}

output "agent_report_analytics" {
  description = "Internal AWS analytics locations for public route reports."
  value = {
    bucket    = aws_s3_bucket.agent_measurement.id
    database  = aws_glue_catalog_database.agent_reports.name
    workgroup = aws_athena_workgroup.agent_reports.name
  }
}

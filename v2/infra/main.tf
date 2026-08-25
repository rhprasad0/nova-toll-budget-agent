data "archive_file" "placeholder" {
  type        = "zip"
  source_file = "${path.module}/lambda-stub/handler.py"
  output_path = "${path.module}/build/placeholder.zip"
}

locals {
  loader_zip_path    = var.loader_package_path != "" ? var.loader_package_path : data.archive_file.placeholder.output_path
  loader_zip_hash    = var.loader_package_path != "" ? filebase64sha256(var.loader_package_path) : data.archive_file.placeholder.output_base64sha256
  publisher_zip_path = var.publisher_package_path != "" ? var.publisher_package_path : data.archive_file.placeholder.output_path
  publisher_zip_hash = var.publisher_package_path != "" ? filebase64sha256(var.publisher_package_path) : data.archive_file.placeholder.output_base64sha256
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "loader" {
  name               = "toll-v2-pricing-loader"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "loader_vpc" {
  role       = aws_iam_role.loader.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_sqs_queue" "invoke_failure" {
  name                      = "toll-v2-pricing-loader-invoke-failure"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "delivery_failure" {
  name                      = "toll-v2-pricing-loader-delivery-failure"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

data "aws_iam_policy_document" "loader" {
  statement {
    sid       = "PublishCommittedI95Loads"
    actions   = ["events:PutEvents"]
    resources = ["arn:aws:events:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:event-bus/default"]
  }

  statement {
    sid       = "DecryptRawObjects"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.raw.target_key_arn]
  }

  statement {
    sid     = "GetRawObjects"
    actions = ["s3:GetObject"]
    resources = [
      "${data.aws_s3_bucket.raw.arn}/raw/feed=i95/*",
      "${data.aws_s3_bucket.raw.arn}/raw/feed=i66/*",
    ]
  }

  statement {
    sid       = "ConnectRdsIam"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/pricing_loader_writer"]
  }

  statement {
    sid       = "SendInvokeFailure"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.invoke_failure.arn]
  }
}

resource "aws_iam_role_policy" "loader" {
  name   = "toll-v2-pricing-loader"
  role   = aws_iam_role.loader.id
  policy = data.aws_iam_policy_document.loader.json
}

data "aws_iam_policy_document" "timed_checks_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "timed_checks" {
  name               = "nova-toll-v2-timed-checks"
  assume_role_policy = data.aws_iam_policy_document.timed_checks_assume.json
}

data "aws_iam_policy_document" "timed_checks" {
  statement {
    sid       = "DescribeRdsEndpoint"
    actions   = ["rds:DescribeDBInstances"]
    resources = ["arn:aws:rds:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:db:${data.aws_db_instance.main.db_instance_identifier}"]
  }

  statement {
    sid       = "ConnectAsPricingCaller"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/pricing_caller"]
  }

  statement {
    sid       = "ReadOpenAiApiKey"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/nova-toll/openai_api_key"]
  }
}

resource "aws_iam_role_policy" "timed_checks" {
  name   = "nova-toll-v2-route-live-checks"
  role   = aws_iam_role.timed_checks.id
  policy = data.aws_iam_policy_document.timed_checks.json
}

resource "aws_security_group" "loader" {
  name        = "nova-toll-v2-pricing-loader"
  description = "v2 pricing loader Lambda ENIs"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_loader" {
  security_group_id            = data.aws_security_group.rds.id
  description                  = "v2 pricing loader Lambda"
  referenced_security_group_id = aws_security_group.loader.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "loader_to_rds" {
  security_group_id            = aws_security_group.loader.id
  description                  = "RDS only"
  referenced_security_group_id = data.aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "loader_to_s3" {
  security_group_id = aws_security_group.loader.id
  description       = "S3 gateway endpoint"
  prefix_list_id    = data.aws_prefix_list.s3.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "loader_to_eventbridge" {
  security_group_id            = aws_security_group.loader.id
  description                  = "Private EventBridge API endpoint"
  referenced_security_group_id = data.aws_security_group.eventbridge_endpoint.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_cloudwatch_log_group" "loader" {
  name              = "/aws/lambda/toll-v2-pricing-loader"
  retention_in_days = 30
}

resource "aws_lambda_function" "loader" {
  function_name = "toll-v2-pricing-loader"
  role          = aws_iam_role.loader.arn
  runtime       = "python3.13"
  handler       = "handler.handler"
  timeout       = 90
  memory_size   = 128

  filename         = local.loader_zip_path
  source_code_hash = local.loader_zip_hash

  reserved_concurrent_executions = 5

  vpc_config {
    subnet_ids         = [data.aws_subnet.tollchat_private_a.id, data.aws_subnet.tollchat_private_c.id]
    security_group_ids = [aws_security_group.loader.id]
  }

  environment {
    variables = {
      DB_HOST    = data.aws_db_instance.main.address
      DB_PORT    = tostring(data.aws_db_instance.main.port)
      DB_NAME    = data.aws_db_instance.main.db_name
      DB_USER    = "pricing_loader_writer"
      RAW_BUCKET = data.aws_s3_bucket.raw.bucket
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.loader,
    aws_iam_role_policy_attachment.loader_vpc,
  ]
}

resource "aws_lambda_function_event_invoke_config" "loader" {
  function_name                = aws_lambda_function.loader.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 21600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.invoke_failure.arn
    }
  }
}

resource "aws_cloudwatch_event_rule" "raw_objects" {
  name = "toll-v2-pricing-raw-objects"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [data.aws_s3_bucket.raw.bucket] }
      object = {
        key = [
          { prefix = "raw/feed=i95/" },
          { prefix = "raw/feed=i66/" },
        ]
      }
    }
  })
}

resource "aws_lambda_permission" "eventbridge_invoke" {
  statement_id  = "AllowEventBridgeInvokeV2PricingLoader"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.loader.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.raw_objects.arn
}

resource "aws_cloudwatch_event_target" "loader" {
  rule = aws_cloudwatch_event_rule.raw_objects.name
  arn  = aws_lambda_function.loader.arn

  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 185
  }

  dead_letter_config {
    arn = aws_sqs_queue.delivery_failure.arn
  }

  depends_on = [
    aws_lambda_permission.eventbridge_invoke,
    aws_sqs_queue_policy.delivery_failure,
  ]
}

data "aws_iam_policy_document" "delivery_failure" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.delivery_failure.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.raw_objects.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "delivery_failure" {
  queue_url = aws_sqs_queue.delivery_failure.id
  policy    = data.aws_iam_policy_document.delivery_failure.json
}

resource "aws_cloudwatch_log_metric_filter" "load_success" {
  name           = "V2LoadSuccess"
  log_group_name = aws_cloudwatch_log_group.loader.name
  pattern        = "[..., event=\"V2_LOAD_OK\", feed]"

  metric_transformation {
    namespace = "NovaToll"
    name      = "V2LoadSuccess"
    value     = "1"
    dimensions = {
      feed = "$feed"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "loader_errors" {
  alarm_name          = "toll-v2-pricing-loader-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.loader.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "freshness" {
  for_each = toset(["i95", "i66"])

  alarm_name          = "toll-v2-pricing-freshness-${each.key}"
  alarm_description   = "No successful v2 ${each.key} load for 30 minutes. Follow v2/README.md."
  namespace           = "NovaToll"
  metric_name         = "V2LoadSuccess"
  dimensions          = { feed = each.key }
  statistic           = "Sum"
  period              = 600
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "failure_queues" {
  for_each = {
    invoke   = aws_sqs_queue.invoke_failure
    delivery = aws_sqs_queue.delivery_failure
  }

  alarm_name          = "toll-v2-pricing-loader-${each.key}-failure-queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_iam_role" "publisher" {
  name               = "toll-v2-report-publisher"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "publisher_vpc" {
  role       = aws_iam_role.publisher.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_sqs_queue" "publisher_invoke_failure" {
  name                      = "toll-v2-report-publisher-invoke-failure"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "publisher_delivery_failure" {
  name                      = "toll-v2-report-publisher-delivery-failure"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

data "aws_iam_policy_document" "publisher" {
  statement {
    sid       = "ConnectRdsIam"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/report_publisher"]
  }

  statement {
    sid       = "SendInvokeFailure"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.publisher_invoke_failure.arn]
  }

  statement {
    sid       = "ReadPublicationManifest"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/tolls/i95-i495/manifest.json"]
  }

  statement {
    sid       = "FindPublicationManifest"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.site.arn]

    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = ["tolls/i95-i495/manifest.json"]
    }
  }

  statement {
    sid     = "WritePublicReports"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.site.arn}/tolls/i95-i495/*",
      "${aws_s3_bucket.site.arn}/sitemap.xml",
    ]
  }

  statement {
    sid       = "WriteAgentReportGenerationMarkers"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.agent_measurement.arn}/generations/*"]
  }

  statement {
    sid       = "UseSiteKey"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.site.arn]
  }

  statement {
    sid       = "UseAgentMeasurementKey"
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.agent_measurement.arn]
  }
}

resource "aws_iam_role_policy" "publisher" {
  name   = "toll-v2-report-publisher"
  role   = aws_iam_role.publisher.id
  policy = data.aws_iam_policy_document.publisher.json
}

resource "aws_security_group" "publisher" {
  name        = "nova-toll-v2-report-publisher"
  description = "v2 report publisher Lambda ENIs"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_publisher" {
  security_group_id            = data.aws_security_group.rds.id
  description                  = "v2 report publisher Lambda"
  referenced_security_group_id = aws_security_group.publisher.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "publisher_to_rds" {
  security_group_id            = aws_security_group.publisher.id
  description                  = "RDS only"
  referenced_security_group_id = data.aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "publisher_to_s3" {
  security_group_id = aws_security_group.publisher.id
  description       = "S3 gateway endpoint"
  prefix_list_id    = data.aws_prefix_list.s3.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_cloudwatch_log_group" "publisher" {
  name              = "/aws/lambda/toll-v2-report-publisher"
  retention_in_days = 30
}

resource "aws_lambda_function" "publisher" {
  function_name = "toll-v2-report-publisher"
  role          = aws_iam_role.publisher.arn
  runtime       = "python3.13"
  handler       = "handler.handler"
  timeout       = 600
  memory_size   = 512

  filename         = local.publisher_zip_path
  source_code_hash = local.publisher_zip_hash

  reserved_concurrent_executions = 1

  vpc_config {
    subnet_ids         = [data.aws_subnet.tollchat_private_a.id, data.aws_subnet.tollchat_private_c.id]
    security_group_ids = [aws_security_group.publisher.id]
  }

  environment {
    variables = {
      DB_HOST                    = data.aws_db_instance.main.address
      DB_PORT                    = tostring(data.aws_db_instance.main.port)
      DB_NAME                    = data.aws_db_instance.main.db_name
      DB_USER                    = "report_publisher"
      REPORT_PUBLICATION_ENABLED = "true"
      SITE_BUCKET_NAME           = aws_s3_bucket.site.id
      AGENT_MEASUREMENT_BUCKET   = aws_s3_bucket.agent_measurement.id
    }
  }

  lifecycle {
    precondition {
      condition     = var.publisher_package_path != ""
      error_message = "Report publisher deployment requires the reviewed v2 publisher package."
    }
  }

  depends_on = [
    aws_cloudfront_distribution.site,
    aws_cloudwatch_log_group.publisher,
    aws_iam_role_policy.publisher,
    aws_iam_role_policy_attachment.publisher_vpc,
    aws_s3_object.robots,
    aws_s3_bucket_server_side_encryption_configuration.agent_measurement,
  ]
}

resource "aws_lambda_function_event_invoke_config" "publisher" {
  function_name                = aws_lambda_function.publisher.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 21600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.publisher_invoke_failure.arn
    }
  }
}

resource "aws_cloudwatch_event_rule" "committed_i95_loads" {
  name = "toll-v2-committed-i95-loads"
  event_pattern = jsonencode({
    source      = ["tollchat.pricing-loader"]
    detail-type = ["I95 Pricing Load Committed"]
    detail = {
      facility = ["i95_i495"]
    }
  })
}

resource "aws_cloudwatch_event_rule" "report_watchdog" {
  name                = "toll-v2-report-watchdog"
  schedule_expression = "cron(5/10 * * * ? *)"
}

resource "aws_lambda_permission" "publisher_load_event" {
  statement_id  = "AllowCommittedI95LoadInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.publisher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.committed_i95_loads.arn
}

resource "aws_lambda_permission" "publisher_watchdog" {
  statement_id  = "AllowReportWatchdogInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.publisher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.report_watchdog.arn
}

resource "aws_cloudwatch_event_target" "publisher_load_event" {
  rule = aws_cloudwatch_event_rule.committed_i95_loads.name
  arn  = aws_lambda_function.publisher.arn

  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 185
  }

  dead_letter_config {
    arn = aws_sqs_queue.publisher_delivery_failure.arn
  }

  depends_on = [
    aws_lambda_permission.publisher_load_event,
    aws_sqs_queue_policy.publisher_delivery_failure,
  ]
}

resource "aws_cloudwatch_event_target" "publisher_watchdog" {
  rule  = aws_cloudwatch_event_rule.report_watchdog.name
  arn   = aws_lambda_function.publisher.arn
  input = jsonencode({ trigger = "watchdog" })

  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 185
  }

  dead_letter_config {
    arn = aws_sqs_queue.publisher_delivery_failure.arn
  }

  depends_on = [
    aws_lambda_permission.publisher_watchdog,
    aws_sqs_queue_policy.publisher_delivery_failure,
  ]
}

data "aws_iam_policy_document" "publisher_delivery_failure" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.publisher_delivery_failure.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        aws_cloudwatch_event_rule.committed_i95_loads.arn,
        aws_cloudwatch_event_rule.report_watchdog.arn,
      ]
    }
  }
}

resource "aws_sqs_queue_policy" "publisher_delivery_failure" {
  queue_url = aws_sqs_queue.publisher_delivery_failure.id
  policy    = data.aws_iam_policy_document.publisher_delivery_failure.json
}

resource "aws_cloudwatch_log_metric_filter" "report_generation_success" {
  name           = "V2ReportGenerationSuccess"
  log_group_name = aws_cloudwatch_log_group.publisher.name
  pattern        = "[..., event=\"V2_REPORT_GENERATION_OK\", facility, generation_id, route_count]"

  metric_transformation {
    namespace = "NovaToll"
    name      = "V2ReportGenerationSuccess"
    value     = "1"
    dimensions = {
      facility = "$facility"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "report_generation_freshness" {
  alarm_name          = "toll-v2-report-generation-freshness"
  alarm_description   = "No complete I-95/I-495 report generation for 30 minutes."
  namespace           = "NovaToll"
  metric_name         = "V2ReportGenerationSuccess"
  dimensions          = { facility = "i95_i495" }
  statistic           = "Sum"
  period              = 600
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "publisher_errors" {
  alarm_name          = "toll-v2-report-publisher-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.publisher.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "publisher_failed_invocations" {
  for_each = {
    load_success = aws_cloudwatch_event_rule.committed_i95_loads
    watchdog     = aws_cloudwatch_event_rule.report_watchdog
  }

  alarm_name          = "toll-v2-report-publisher-${each.key}-failed-invocations"
  namespace           = "AWS/Events"
  metric_name         = "FailedInvocations"
  dimensions          = { RuleName = each.value.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "publisher_failure_queues" {
  for_each = {
    invoke   = aws_sqs_queue.publisher_invoke_failure
    delivery = aws_sqs_queue.publisher_delivery_failure
  }

  alarm_name          = "toll-v2-report-publisher-${each.key}-failure-queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

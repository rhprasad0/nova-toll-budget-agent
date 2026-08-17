data "archive_file" "placeholder" {
  type        = "zip"
  source_file = "${path.module}/lambda-stub/handler.py"
  output_path = "${path.module}/build/placeholder.zip"
}

locals {
  loader_zip_path = var.loader_package_path != "" ? var.loader_package_path : data.archive_file.placeholder.output_path
  loader_zip_hash = var.loader_package_path != "" ? filebase64sha256(var.loader_package_path) : data.archive_file.placeholder.output_base64sha256
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
    sid       = "ConnectAsTollchatAgent"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/tollchat_agent"]
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
    subnet_ids         = data.aws_subnets.default.ids
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
  alarm_description   = "No successful v2 ${each.key} load for 30 minutes. Follow v2/docs/pricing-shadow-rollout.md."
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

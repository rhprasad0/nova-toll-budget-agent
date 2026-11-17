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
  name               = "toll-v2-pricing-loader${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "loader_vpc" {
  role       = aws_iam_role.loader.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_sqs_queue" "invoke_failure" {
  name                      = "toll-v2-pricing-loader-invoke-failure${local.suffix}"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "delivery_failure" {
  name                      = "toll-v2-pricing-loader-delivery-failure${local.suffix}"
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
    resources = [var.foundation.raw_kms_key_arn]
  }

  statement {
    sid     = "GetRawObjects"
    actions = ["s3:GetObject"]
    resources = [
      "${local.raw_bucket_arn}/raw/feed=i95/*",
      "${local.raw_bucket_arn}/raw/feed=i66/*",
    ]
  }

  statement {
    sid       = "ConnectRdsIam"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.loader}"]
  }

  statement {
    sid       = "SendInvokeFailure"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.invoke_failure.arn]
  }
}

resource "aws_iam_role_policy" "loader" {
  name   = "toll-v2-pricing-loader${local.suffix}"
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
      values = var.environment == "development" ? [
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
        ] : [
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "timed_checks" {
  name               = "nova-toll-v2-timed-checks${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.timed_checks_assume.json
}

data "aws_iam_policy_document" "timed_checks" {
  statement {
    sid       = "DescribeRdsEndpoint"
    actions   = ["rds:DescribeDBInstances"]
    resources = ["arn:aws:rds:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:db:${var.foundation.db_instance.identifier}"]
  }

  statement {
    sid       = "ConnectAsPricingCaller"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.pricing_caller}"]
  }

  statement {
    sid       = "ReadOpenAiApiKey"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/nova-toll/openai_api_key"]
  }
}

resource "aws_iam_role_policy" "timed_checks" {
  name   = "nova-toll-v2-route-live-checks${local.suffix}"
  role   = aws_iam_role.timed_checks.id
  policy = data.aws_iam_policy_document.timed_checks.json
}

resource "aws_security_group" "loader" {
  name        = "nova-toll-v2-pricing-loader${local.suffix}"
  description = "v2 pricing loader Lambda ENIs"
  vpc_id      = var.foundation.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_loader" {
  security_group_id            = var.foundation.rds_security_group_id
  description                  = "v2 pricing loader Lambda"
  referenced_security_group_id = aws_security_group.loader.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "loader_to_rds" {
  security_group_id            = aws_security_group.loader.id
  description                  = "RDS only"
  referenced_security_group_id = var.foundation.rds_security_group_id
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
  referenced_security_group_id = var.foundation.eventbridge_endpoint_security_group_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_cloudwatch_log_group" "loader" {
  name              = "/aws/lambda/toll-v2-pricing-loader${local.suffix}"
  retention_in_days = local.log_retention_days
}

resource "aws_lambda_function" "loader" {
  function_name = "toll-v2-pricing-loader${local.suffix}"
  role          = aws_iam_role.loader.arn
  runtime       = "python3.13"
  handler       = "handler.handler"
  timeout       = 90
  memory_size   = 128

  filename         = local.loader_zip_path
  source_code_hash = local.loader_zip_hash

  reserved_concurrent_executions = 5

  vpc_config {
    subnet_ids         = [var.foundation.private_subnet_ids.a, var.foundation.private_subnet_ids.c]
    security_group_ids = [aws_security_group.loader.id]
  }

  environment {
    variables = merge({
      DB_HOST    = var.foundation.db_instance.address
      DB_PORT    = tostring(var.foundation.db_instance.port)
      DB_NAME    = local.database_name
      DB_USER    = local.database_roles.loader
      RAW_BUCKET = var.foundation.raw_bucket_name
      }, local.is_production ? {} : {
      TOLLCHAT_ENVIRONMENT = var.environment
    })
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
  name = "toll-v2-pricing-raw-objects${local.suffix}"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [var.foundation.raw_bucket_name] }
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
  pattern        = local.is_production ? "[..., event=\"V2_LOAD_OK\", feed]" : "[..., event=\"V2_LOAD_OK\", feed, environment]"

  metric_transformation {
    namespace  = "NovaToll"
    name       = "V2LoadSuccess"
    value      = "1"
    dimensions = local.is_production ? { feed = "$feed" } : { feed = "$feed", Environment = "$environment" }
  }
}

resource "aws_cloudwatch_metric_alarm" "loader_errors" {
  alarm_name          = "toll-v2-pricing-loader-errors${local.suffix}"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.loader.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "freshness" {
  for_each = toset(["i95", "i66"])

  alarm_name          = "toll-v2-pricing-freshness-${each.key}${local.suffix}"
  alarm_description   = "No successful v2 ${each.key} load for 30 minutes. Follow v2/README.md."
  namespace           = "NovaToll"
  metric_name         = "V2LoadSuccess"
  dimensions          = local.is_production ? { feed = each.key } : { feed = each.key, Environment = var.environment }
  statistic           = "Sum"
  period              = 600
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "failure_queues" {
  for_each = {
    invoke   = aws_sqs_queue.invoke_failure
    delivery = aws_sqs_queue.delivery_failure
  }

  alarm_name          = "toll-v2-pricing-loader-${each.key}-failure-queue${local.suffix}"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

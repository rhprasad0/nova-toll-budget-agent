locals {
  eval_db_user               = local.is_production ? "eval_writer" : "eval_writer_development"
  timed_checks_zip_hash      = var.timed_checks_package_path != "" ? filebase64sha256(var.timed_checks_package_path) : ""
  timed_check_alerts_enabled = local.is_production || var.enable_development_timed_check_alerts
  timed_check_schedules = {
    "i95-northbound-mon-0617" = { schedule = "17 6 * * 1", expression = "cron(17 6 ? * MON *)", window_id = "i95_northbound" }
    "i95-northbound-tue-0617" = { schedule = "17 6 * * 2", expression = "cron(17 6 ? * TUE *)", window_id = "i95_northbound" }
    "i95-northbound-wed-0617" = { schedule = "17 6 * * 3", expression = "cron(17 6 ? * WED *)", window_id = "i95_northbound" }
    "i95-northbound-thu-0617" = { schedule = "17 6 * * 4", expression = "cron(17 6 ? * THU *)", window_id = "i95_northbound" }
    "i95-northbound-fri-0617" = { schedule = "17 6 * * 5", expression = "cron(17 6 ? * FRI *)", window_id = "i95_northbound" }
    "i95-southbound-mon-1417" = { schedule = "17 14 * * 1", expression = "cron(17 14 ? * MON *)", window_id = "i95_southbound" }
    "i95-southbound-tue-1417" = { schedule = "17 14 * * 2", expression = "cron(17 14 ? * TUE *)", window_id = "i95_southbound" }
    "i95-southbound-wed-1417" = { schedule = "17 14 * * 3", expression = "cron(17 14 ? * WED *)", window_id = "i95_southbound" }
    "i95-southbound-thu-1417" = { schedule = "17 14 * * 4", expression = "cron(17 14 ? * THU *)", window_id = "i95_southbound" }
    "i95-southbound-fri-1417" = { schedule = "17 14 * * 5", expression = "cron(17 14 ? * FRI *)", window_id = "i95_southbound" }
    "i95-reversal-mon-1117"   = { schedule = "17 11 * * 1", expression = "cron(17 11 ? * MON *)", window_id = "i95_reversal" }
    "i95-reversal-tue-0147"   = { schedule = "47 1 * * 2", expression = "cron(47 1 ? * TUE *)", window_id = "i95_reversal" }
    "i95-reversal-wed-0147"   = { schedule = "47 1 * * 3", expression = "cron(47 1 ? * WED *)", window_id = "i95_reversal" }
    "i95-reversal-thu-0147"   = { schedule = "47 1 * * 4", expression = "cron(47 1 ? * THU *)", window_id = "i95_reversal" }
    "i95-reversal-fri-0147"   = { schedule = "47 1 * * 5", expression = "cron(47 1 ? * FRI *)", window_id = "i95_reversal" }
    "i95-southbound-sat-1017" = { schedule = "17 10 * * 6", expression = "cron(17 10 ? * SAT *)", window_id = "i95_southbound" }
    "i95-reversal-sat-1517"   = { schedule = "17 15 * * 6", expression = "cron(17 15 ? * SAT *)", window_id = "i95_reversal" }
    "i95-northbound-sat-1817" = { schedule = "17 18 * * 6", expression = "cron(17 18 ? * SAT *)", window_id = "i95_northbound" }
    "greenway-eb-mon-0723"    = { schedule = "23 7 * * 1", expression = "cron(23 7 ? * MON *)", window_id = "greenway_eb_peak" }
    "greenway-eb-tue-0723"    = { schedule = "23 7 * * 2", expression = "cron(23 7 ? * TUE *)", window_id = "greenway_eb_peak" }
    "greenway-eb-wed-0723"    = { schedule = "23 7 * * 3", expression = "cron(23 7 ? * WED *)", window_id = "greenway_eb_peak" }
    "greenway-eb-thu-0723"    = { schedule = "23 7 * * 4", expression = "cron(23 7 ? * THU *)", window_id = "greenway_eb_peak" }
    "greenway-eb-fri-0723"    = { schedule = "23 7 * * 5", expression = "cron(23 7 ? * FRI *)", window_id = "greenway_eb_peak" }
    "greenway-wb-mon-1723"    = { schedule = "23 17 * * 1", expression = "cron(23 17 ? * MON *)", window_id = "greenway_wb_peak" }
    "greenway-wb-tue-1723"    = { schedule = "23 17 * * 2", expression = "cron(23 17 ? * TUE *)", window_id = "greenway_wb_peak" }
    "greenway-wb-wed-1723"    = { schedule = "23 17 * * 3", expression = "cron(23 17 ? * WED *)", window_id = "greenway_wb_peak" }
    "greenway-wb-thu-1723"    = { schedule = "23 17 * * 4", expression = "cron(23 17 ? * THU *)", window_id = "greenway_wb_peak" }
    "greenway-wb-fri-1723"    = { schedule = "23 17 * * 5", expression = "cron(23 17 ? * FRI *)", window_id = "greenway_wb_peak" }
  }
}

data "aws_kms_alias" "alerts" {
  name = "alias/nova-toll-alerts"
}

resource "aws_s3_object" "timed_checks" {
  bucket      = var.foundation.agentcore_artifacts_bucket_name
  key         = "lambda/v2/timed-checks${local.is_production ? "" : "-dev"}.zip"
  source      = var.timed_checks_package_path
  source_hash = local.timed_checks_zip_hash
}

resource "aws_sqs_queue" "timed_checks_invoke_failure" {
  name                      = "nova-toll-v2-timed-checks-invoke-failure${local.suffix}"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "timed_checks_delivery_failure" {
  name                      = "nova-toll-v2-timed-checks-delivery-failure${local.suffix}"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

data "aws_iam_policy_document" "timed_checks_lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "timed_checks_lambda" {
  name               = "nova-toll-v2-timed-checks-lambda${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.timed_checks_lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "timed_checks_lambda_vpc" {
  role       = aws_iam_role.timed_checks_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "timed_checks_lambda" {
  name = "nova-toll-v2-timed-checks-lambda${local.suffix}"
  role = aws_iam_role.timed_checks_lambda.id
  # Keep unchanged permissions known while the runtime, proxy, or routing changes.
  # A policy-document data source defers its read when those dependencies update.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid      = "ConnectEvaluationHistory"
        Effect   = "Allow"
        Action   = ["rds-db:connect"]
        Resource = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.eval_db_user}"]
      },
      {
        Sid      = "PublishEvaluationSnapshot"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${aws_s3_bucket.site.arn}/evals.json"]
      },
      {
        Sid      = "EncryptEvaluationSnapshot"
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = [aws_kms_key.site.arn]
      },
      {
        Sid      = "DescribeRdsEndpoint"
        Effect   = "Allow"
        Action   = ["rds:DescribeDBInstances"]
        Resource = ["arn:aws:rds:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:db:${var.foundation.db_instance.identifier}"]
      },
      {
        Sid      = "ReadLiveChatRouting"
        Effect   = "Allow"
        Action   = ["cloudfront:GetDistribution"]
        Resource = [aws_cloudfront_distribution.site.arn]
      },
      {
        Sid      = "ReadPublishedChatProxy"
        Effect   = "Allow"
        Action   = ["lambda:GetFunctionUrlConfig", "lambda:GetAlias", "lambda:GetFunctionConfiguration"]
        Resource = flatten([for function in aws_lambda_function.tollchat_proxy : [function.arn, "${function.arn}:*"]])
      },
      {
        Sid      = "ReadLiveRuntimeVersion"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:GetAgentRuntimeEndpoint"]
        Resource = values(local.agentcore_policy_resources)
      },
      {
        Sid       = "InvokeLiveApplication"
        Effect    = "Allow"
        Action    = ["bedrock-agentcore:InvokeAgentRuntime"]
        Resource  = values(local.agentcore_policy_resources)
        Condition = { StringEquals = { "aws:SourceVpce" = var.foundation.agentcore_vpc_endpoint_id } }
      },
      {
        Sid      = "ReadOpenAiApiKey"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = ["arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/nova-toll/openai_api_key"]
      },
      {
        Sid      = "SendInvokeFailure"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.timed_checks_invoke_failure.arn]
      },
      {
        Sid      = "PublishEvaluationFailureAlert"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [var.foundation.alerts_topic_arn]
      },
      {
        Sid      = "UseEvaluationFailureAlertKey"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource = [data.aws_kms_alias.alerts.target_key_arn]
      },
      ], local.is_production ? [{
        # Retain the deployed bundled evaluator's access until the live consumer ships.
        Sid    = "ConnectRdsIam"
        Effect = "Allow"
        Action = ["rds-db:connect"]
        Resource = [
          "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.agent}",
          "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.pricing_caller}",
        ]
    }] : [])
  })
}

data "aws_iam_policy_document" "timed_checks_scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:scheduler:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:schedule-group/default"]
    }
  }
}

resource "aws_iam_role" "timed_checks_scheduler" {
  name               = "nova-toll-v2-timed-checks-scheduler${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.timed_checks_scheduler_assume.json
}

resource "aws_iam_role_policy" "timed_checks_scheduler" {
  name = "nova-toll-v2-timed-checks-scheduler${local.suffix}"
  role = aws_iam_role.timed_checks_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.timed_checks.arn
      },
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.timed_checks_delivery_failure.arn
      },
    ]
  })
}

resource "aws_security_group" "timed_checks" {
  name        = "nova-toll-v2-timed-checks${local.suffix}"
  description = "TollChat timed-check Lambda ENIs"
  vpc_id      = var.foundation.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_timed_checks" {
  security_group_id            = var.foundation.rds_security_group_id
  description                  = "TollChat timed checks"
  referenced_security_group_id = aws_security_group.timed_checks.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "timed_checks_to_rds" {
  security_group_id            = aws_security_group.timed_checks.id
  description                  = "RDS only"
  referenced_security_group_id = var.foundation.rds_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "timed_checks_https" {
  security_group_id = aws_security_group.timed_checks.id
  description       = "HTTPS through the private subnet NAT path"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_cloudwatch_log_group" "timed_checks" {
  name              = "/aws/lambda/nova-toll-v2-timed-checks${local.suffix}"
  retention_in_days = local.log_retention_days
}

resource "aws_vpc_security_group_ingress_rule" "agentcore_from_timed_checks" {
  security_group_id            = var.foundation.agentcore_endpoint_security_group_id
  description                  = "TollChat scheduled evaluations of the live runtime"
  referenced_security_group_id = aws_security_group.timed_checks.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_lambda_function" "timed_checks" {
  function_name = "nova-toll-v2-timed-checks${local.suffix}"
  role          = aws_iam_role.timed_checks_lambda.arn
  runtime       = "python3.13"
  handler       = "handler.handler"
  architectures = ["x86_64"]
  timeout       = 900
  memory_size   = 2048

  s3_bucket         = var.foundation.agentcore_artifacts_bucket_name
  s3_key            = aws_s3_object.timed_checks.key
  s3_object_version = aws_s3_object.timed_checks.version_id
  source_code_hash  = local.timed_checks_zip_hash

  reserved_concurrent_executions = 1

  vpc_config {
    subnet_ids         = local.private_subnets
    security_group_ids = [aws_security_group.timed_checks.id]
  }

  environment {
    variables = merge({
      DB_HOST                    = var.foundation.db_instance.address
      DB_PORT                    = tostring(var.foundation.db_instance.port)
      DB_NAME                    = local.database_name
      DB_CA_BUNDLE_PATH          = "/var/task/rds-ca-bundle.pem"
      TIMED_CHECK_ALERTS_ENABLED = tostring(local.timed_check_alerts_enabled)
      ENVIRONMENT                = var.environment
      EVAL_DASHBOARD_BUCKET      = aws_s3_bucket.site.id
      EVAL_DB_USER               = local.eval_db_user
      EVAL_SITE_DISTRIBUTION_ID  = aws_cloudfront_distribution.site.id
      AGENTCORE_VPCE_URL         = "https://${var.foundation.agentcore_vpc_endpoint_dns_name}"
      }, local.is_production ? {
      DB_USER         = local.database_roles.agent
      PRICING_DB_USER = local.database_roles.pricing_caller
      } : {}, local.timed_check_alerts_enabled ? {
      ALERTS_TOPIC_ARN = var.foundation.alerts_topic_arn
    } : {})
  }

  lifecycle {
    precondition {
      condition     = var.timed_checks_package_path != ""
      error_message = "Timed-check deployment requires the reviewed v2 timed-checks package."
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.timed_checks,
    aws_iam_role_policy.timed_checks_lambda,
    aws_iam_role_policy_attachment.timed_checks_lambda_vpc,
  ]
}

resource "aws_lambda_function_event_invoke_config" "timed_checks" {
  function_name                = aws_lambda_function.timed_checks.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.timed_checks_invoke_failure.arn
    }
  }
}

resource "aws_scheduler_schedule" "timed_checks" {
  for_each = local.timed_check_schedules

  name                         = "nova-toll-v2-${each.key}${local.suffix}"
  state                        = "ENABLED"
  schedule_expression          = each.value.expression
  schedule_expression_timezone = "America/New_York"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.timed_checks.arn
    role_arn = aws_iam_role.timed_checks_scheduler.arn
    input = jsonencode({
      window_id = each.value.window_id
      schedule  = each.value.schedule
    })

    retry_policy {
      maximum_event_age_in_seconds = 600
      maximum_retry_attempts       = 0
    }

    dead_letter_config {
      arn = aws_sqs_queue.timed_checks_delivery_failure.arn
    }
  }

  depends_on = [aws_iam_role_policy.timed_checks_scheduler]
}

resource "aws_cloudwatch_metric_alarm" "timed_checks_errors" {
  alarm_name          = "nova-toll-v2-timed-checks-errors${local.suffix}"
  alarm_description   = "Unexpected timed-check failures and evaluation alert delivery failures"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.timed_checks.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "timed_checks_failure_queues" {
  for_each = {
    invoke   = aws_sqs_queue.timed_checks_invoke_failure
    delivery = aws_sqs_queue.timed_checks_delivery_failure
  }

  alarm_name          = "nova-toll-v2-timed-checks-${each.key}-failure-queue${local.suffix}"
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

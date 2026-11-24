locals {
  factory_dashboard_count             = local.factory_count
  factory_dashboard_domain            = "factory.tollchat.ai"
  factory_dashboard_admin_key         = "/nova-toll/factory/anthropic-admin-key"
  factory_dashboard_alarm_app_key     = "/nova-toll/factory/alarm-app-private-key"
  factory_dashboard_alarm_topic       = "factory-dashboard-alarms"
  factory_dashboard_zip_path          = var.factory_dashboard_package_path != "" ? var.factory_dashboard_package_path : data.archive_file.placeholder.output_path
  factory_dashboard_zip_hash          = var.factory_dashboard_package_path != "" ? filebase64sha256(var.factory_dashboard_package_path) : data.archive_file.placeholder.output_base64sha256
  factory_dashboard_ssm_arn           = "arn:aws:ssm:${local.development_delivery_region}:${local.development_delivery_account_id}:parameter"
  factory_dashboard_rds_user_arn      = "arn:aws:rds-db:us-east-1:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.main.resource_id}"
  factory_dashboard_functions         = { ingest = "factory-dashboard-ingest", web = "factory-dashboard-web", issues = "factory-alarm-issues" }
  factory_dashboard_database_users    = { ingest = local.factory_sandbox_users[0], web = local.factory_sandbox_users[1] }
  factory_dashboard_cache_policy      = "4cc15a8a-d715-48a4-82b8-cc0b614638fe"
  factory_dashboard_origin_req_policy = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
}

resource "aws_iam_role" "factory_dashboard" {
  for_each           = local.factory_dashboard_count == 1 ? local.factory_dashboard_functions : {}
  name               = each.value
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "factory_dashboard" {
  for_each   = aws_iam_role.factory_dashboard
  role       = each.value.name
  policy_arn = each.key == "issues" ? "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" : "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "factory_dashboard" {
  for_each = aws_iam_role.factory_dashboard
  dynamic "statement" {
    for_each = contains(["ingest", "web"], each.key) ? [local.factory_dashboard_database_users[each.key]] : []
    content {
      sid       = "ConnectFactorySandboxDatabase"
      actions   = ["rds-db:connect"]
      resources = ["${local.factory_dashboard_rds_user_arn}/${statement.value}"]
    }
  }
  dynamic "statement" {
    for_each = each.key == "web" ? [] : [each.key == "ingest" ? local.factory_dashboard_admin_key : local.factory_dashboard_alarm_app_key]
    content {
      sid       = "ReadSecret"
      actions   = ["ssm:GetParameter"]
      resources = ["${local.factory_dashboard_ssm_arn}${statement.value}"]
    }
  }
}

resource "aws_iam_role_policy" "factory_dashboard" {
  for_each = aws_iam_role.factory_dashboard
  name     = each.value.name
  role     = each.value.id
  policy   = data.aws_iam_policy_document.factory_dashboard[each.key].json
}

resource "aws_security_group" "factory_dashboard" {
  for_each    = local.factory_dashboard_count == 1 ? toset(["ingest", "web"]) : toset([])
  name        = local.factory_dashboard_functions[each.key]
  description = "Factory dashboard ${each.key} Lambda"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_egress_rule" "factory_dashboard_rds" {
  for_each                     = aws_security_group.factory_dashboard
  security_group_id            = each.value.id
  description                  = "Factory sandbox database"
  referenced_security_group_id = aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_factory_dashboard" {
  for_each                     = aws_security_group.factory_dashboard
  security_group_id            = aws_security_group.rds.id
  description                  = "Factory dashboard ${each.key} Lambda"
  referenced_security_group_id = each.value.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "factory_dashboard_ingest_https" {
  count             = local.factory_dashboard_count
  security_group_id = aws_security_group.factory_dashboard["ingest"].id
  description       = "Anthropic Admin API and SSM through the router NAT"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_cloudwatch_log_group" "factory_dashboard" {
  for_each          = aws_iam_role.factory_dashboard
  name              = "/aws/lambda/${each.value.name}"
  retention_in_days = 30
}

resource "aws_lambda_function" "factory_dashboard" {
  for_each      = aws_iam_role.factory_dashboard
  function_name = each.value.name
  role          = each.value.arn
  runtime       = "python3.13"
  handler       = { ingest = "dashboard.aws.ingest_handler", web = "dashboard.aws.web_handler", issues = "dashboard.alarm_issues.handler" }[each.key]
  timeout       = { ingest = 300, web = 15, issues = 30 }[each.key]
  memory_size   = 256

  filename         = local.factory_dashboard_zip_path
  source_code_hash = local.factory_dashboard_zip_hash

  reserved_concurrent_executions = { ingest = 1, web = 5, issues = 2 }[each.key]

  dynamic "vpc_config" {
    for_each = each.key == "issues" ? [] : [each.key]
    content {
      subnet_ids         = [aws_subnet.tollchat_private_a.id, aws_subnet.tollchat_private_c.id]
      security_group_ids = [aws_security_group.factory_dashboard[vpc_config.value].id]
    }
  }

  environment {
    variables = {
      ingest = {
        DB_HOST             = aws_db_instance.main.address
        DB_NAME             = "factory_sandbox"
        DB_WRITER           = local.factory_dashboard_database_users.ingest
        ADMIN_KEY_PARAMETER = local.factory_dashboard_admin_key
      }
      web = {
        DB_HOST   = aws_db_instance.main.address
        DB_NAME   = "factory_sandbox"
        DB_READER = local.factory_dashboard_database_users.web
      }
      issues = {
        APP_PRIVATE_KEY_PARAMETER = local.factory_dashboard_alarm_app_key
        APP_CLIENT_ID             = var.factory_alarm_app.client_id
        APP_SLUG                  = var.factory_alarm_app.slug
        GITHUB_REPOSITORY         = "rhprasad0/nova-toll-budget-agent"
      }
    }[each.key]
  }

  lifecycle {
    precondition {
      condition     = var.factory_dashboard_package_path != ""
      error_message = "Build the package with dashboard/build_lambda_zip.sh and pass factory_dashboard_package_path=build/factory-dashboard.zip."
    }
  }

  depends_on = [aws_cloudwatch_log_group.factory_dashboard, aws_iam_role_policy_attachment.factory_dashboard]
}

resource "aws_cloudwatch_event_rule" "factory_dashboard_ingest" {
  count               = local.factory_dashboard_count
  name                = "factory-dashboard-ingest-daily"
  schedule_expression = "cron(15 6 * * ? *)"
}

resource "aws_cloudwatch_event_target" "factory_dashboard_ingest" {
  count = local.factory_dashboard_count
  rule  = aws_cloudwatch_event_rule.factory_dashboard_ingest[0].name
  arn   = aws_lambda_function.factory_dashboard["ingest"].arn
}

resource "aws_lambda_permission" "factory_dashboard_ingest_schedule" {
  count         = local.factory_dashboard_count
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.factory_dashboard["ingest"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.factory_dashboard_ingest[0].arn
}

resource "aws_lambda_function_event_invoke_config" "factory_dashboard_ingest" {
  count                  = local.factory_dashboard_count
  function_name          = aws_lambda_function.factory_dashboard["ingest"].function_name
  maximum_retry_attempts = 2
}

resource "aws_lambda_function_url" "factory_dashboard" {
  count              = local.factory_dashboard_count
  function_name      = aws_lambda_function.factory_dashboard["web"].function_name
  authorization_type = "AWS_IAM"
}

resource "aws_cloudfront_origin_access_control" "factory_dashboard" {
  count                             = local.factory_dashboard_count
  name                              = "factory-dashboard"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_acm_certificate" "factory_dashboard" {
  count             = local.factory_dashboard_count
  domain_name       = local.factory_dashboard_domain
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}

resource "aws_cloudfront_distribution" "factory_dashboard" {
  count       = local.factory_dashboard_count
  enabled     = true
  comment     = "Factory metrics dashboard"
  price_class = "PriceClass_100"
  aliases     = var.factory_dashboard_domain_ready ? [local.factory_dashboard_domain] : []

  origin {
    domain_name              = trimsuffix(trimprefix(aws_lambda_function_url.factory_dashboard[0].function_url, "https://"), "/")
    origin_id                = "web"
    origin_access_control_id = aws_cloudfront_origin_access_control.factory_dashboard[0].id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods          = ["GET", "HEAD"]
    cached_methods           = ["GET", "HEAD"]
    target_origin_id         = "web"
    viewer_protocol_policy   = "redirect-to-https"
    compress                 = true
    cache_policy_id          = local.factory_dashboard_cache_policy
    origin_request_policy_id = local.factory_dashboard_origin_req_policy
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn            = var.factory_dashboard_domain_ready ? aws_acm_certificate.factory_dashboard[0].arn : null
    cloudfront_default_certificate = !var.factory_dashboard_domain_ready
    ssl_support_method             = var.factory_dashboard_domain_ready ? "sni-only" : null
    minimum_protocol_version       = var.factory_dashboard_domain_ready ? "TLSv1.2_2021" : "TLSv1"
  }
}

resource "aws_lambda_permission" "factory_dashboard_url" {
  count                  = local.factory_dashboard_count
  statement_id           = "AllowCloudFrontFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.factory_dashboard["web"].function_name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = aws_cloudfront_distribution.factory_dashboard[0].arn
  function_url_auth_type = "AWS_IAM"
}

resource "aws_lambda_permission" "factory_dashboard_invoke" {
  count                    = local.factory_dashboard_count
  statement_id             = "AllowCloudFrontFunctionInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.factory_dashboard["web"].function_name
  principal                = "cloudfront.amazonaws.com"
  source_arn               = aws_cloudfront_distribution.factory_dashboard[0].arn
  invoked_via_function_url = true
}

resource "aws_sns_topic" "factory_dashboard_alarms" {
  count             = local.factory_dashboard_count
  name              = local.factory_dashboard_alarm_topic
  kms_master_key_id = aws_kms_key.alerts.arn
}

resource "aws_sns_topic_subscription" "factory_dashboard_alarms" {
  count     = local.factory_dashboard_count
  topic_arn = aws_sns_topic.factory_dashboard_alarms[0].arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.factory_dashboard["issues"].arn
}

resource "aws_lambda_permission" "factory_alarm_issues_sns" {
  count         = local.factory_dashboard_count
  statement_id  = "AllowSnsInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.factory_dashboard["issues"].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.factory_dashboard_alarms[0].arn
}

locals {
  factory_dashboard_alarms = {
    "factory-dashboard-ingest-errors" = {
      function    = "ingest"
      metric      = "Errors"
      period      = 3600
      threshold   = 1
      comparison  = "GreaterThanOrEqualToThreshold"
      missing     = "notBreaching"
      description = "The daily Anthropic usage and cost ingest (dashboard.aws.ingest_handler, dashboard/ingest.py) raised. Logs: /aws/lambda/factory-dashboard-ingest."
    }
    "factory-dashboard-ingest-missed" = {
      function    = "ingest"
      metric      = "Invocations"
      period      = 86400
      threshold   = 1
      comparison  = "LessThanThreshold"
      missing     = "breaching"
      description = "The daily ingest did not run in the last day; check the factory-dashboard-ingest-daily EventBridge rule and the factory-dashboard-ingest Lambda (dashboard/aws.py)."
    }
    "factory-dashboard-web-5xx" = {
      function    = "web"
      metric      = "Url5xxCount"
      period      = 900
      threshold   = 3
      comparison  = "GreaterThanOrEqualToThreshold"
      missing     = "notBreaching"
      description = "factory.tollchat.ai returned 5xx responses (dashboard.aws.web_handler, dashboard/web.py, dashboard/report.py). A 503 means the factory_sandbox database was unreachable or unreadable as factory_sandbox_reader. Logs: /aws/lambda/factory-dashboard-web."
    }
    "factory-dashboard-web-errors" = {
      function    = "web"
      metric      = "Errors"
      period      = 900
      threshold   = 1
      comparison  = "GreaterThanOrEqualToThreshold"
      missing     = "notBreaching"
      description = "The dashboard web Lambda raised (dashboard.aws.web_handler, dashboard/render.py, dashboard/report.py). Logs: /aws/lambda/factory-dashboard-web."
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "factory_dashboard" {
  for_each            = local.factory_dashboard_count == 1 ? local.factory_dashboard_alarms : {}
  alarm_name          = each.key
  alarm_description   = each.value.description
  namespace           = "AWS/Lambda"
  metric_name         = each.value.metric
  dimensions          = { FunctionName = aws_lambda_function.factory_dashboard[each.value.function].function_name }
  period              = each.value.period
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = each.value.missing
  alarm_actions       = [aws_sns_topic.factory_dashboard_alarms[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "factory_alarm_issues_errors" {
  count               = local.factory_dashboard_count
  alarm_name          = "factory-alarm-issues-errors"
  alarm_description   = "The Lambda that files GitHub issues for factory dashboard alarms failed, so an alarm may have no issue."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.factory_dashboard["issues"].function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

output "factory_dashboard" {
  description = "Where the factory dashboard is served and the DNS records factory.tollchat.ai needs in Cloudflare; null outside development."
  value = local.factory_dashboard_count == 1 ? {
    distribution_domain = aws_cloudfront_distribution.factory_dashboard[0].domain_name
    certificate_validation = [
      for dvo in aws_acm_certificate.factory_dashboard[0].domain_validation_options : {
        name  = trimsuffix(dvo.resource_record_name, ".")
        type  = dvo.resource_record_type
        value = trimsuffix(dvo.resource_record_value, ".")
      }
    ]
  } : null
}

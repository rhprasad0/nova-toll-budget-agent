locals {
  site_assets = fileset("${path.module}/../agent/assets", "**")
  assistant_referrers = {
    openai     = { priority = 1, host = "chatgpt[.]com" }
    anthropic  = { priority = 2, host = "claude[.]ai" }
    perplexity = { priority = 3, host = "perplexity[.]ai" }
    google     = { priority = 4, host = "gemini[.]google[.]com" }
    microsoft  = { priority = 5, host = "copilot[.]microsoft[.]com" }
  }
}

data "archive_file" "usage_publisher" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/usage_publisher/handler.py"
  output_path = "${path.module}/build/usage-publisher.zip"
}

resource "aws_s3_bucket" "site" {
  bucket = "tollchat-site-920534282028"
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "site_kms" {
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
    sid       = "AllowCloudFrontDecrypt"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_kms_key" "site" {
  description             = "TollChat v2 public site assets"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.site_kms.json
}

resource "aws_kms_alias" "site" {
  name          = "alias/tollchat-v2-site"
  target_key_id = aws_kms_key.site.key_id
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.site.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_object" "index" {
  bucket        = aws_s3_bucket.site.id
  key           = "index.html"
  source        = "${path.module}/../agent/dev_chat.html"
  source_hash   = filebase64sha256("${path.module}/../agent/dev_chat.html")
  content_type  = "text/html; charset=utf-8"
  cache_control = "no-cache"

  depends_on = [aws_s3_object.site_assets, aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "chat" {
  bucket        = aws_s3_bucket.site.id
  key           = "chat.mjs"
  source        = "${path.module}/../agent/public_chat.mjs"
  source_hash   = filebase64sha256("${path.module}/../agent/public_chat.mjs")
  content_type  = "text/javascript; charset=utf-8"
  cache_control = "no-cache"

  depends_on = [aws_s3_object.site_assets, aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "usage" {
  bucket        = aws_s3_bucket.site.id
  key           = "usage.json"
  content       = "{}"
  content_type  = "application/json; charset=utf-8"
  cache_control = "no-cache"

  lifecycle {
    ignore_changes = [content, etag]
  }

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "faq" {
  bucket        = aws_s3_bucket.site.id
  key           = "faq.html"
  source        = "${path.module}/../agent/faq.html"
  source_hash   = filebase64sha256("${path.module}/../agent/faq.html")
  content_type  = "text/html; charset=utf-8"
  cache_control = "no-cache"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "privacy" {
  bucket        = aws_s3_bucket.site.id
  key           = "privacy.txt"
  source        = "${path.module}/../agent/privacy.txt"
  source_hash   = filebase64sha256("${path.module}/../agent/privacy.txt")
  content_type  = "text/plain; charset=utf-8"
  cache_control = "no-cache"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "terms" {
  bucket        = aws_s3_bucket.site.id
  key           = "terms.txt"
  source        = "${path.module}/../agent/terms.txt"
  source_hash   = filebase64sha256("${path.module}/../agent/terms.txt")
  content_type  = "text/plain; charset=utf-8"
  cache_control = "no-cache"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "robots" {
  bucket        = aws_s3_bucket.site.id
  key           = "robots.txt"
  source        = "${path.module}/../agent/robots.txt"
  source_hash   = filebase64sha256("${path.module}/../agent/robots.txt")
  content_type  = "text/plain; charset=utf-8"
  cache_control = "no-cache"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "bing_site_auth" {
  bucket        = aws_s3_bucket.site.id
  key           = "BingSiteAuth.xml"
  source        = "${path.module}/../agent/BingSiteAuth.xml"
  source_hash   = filebase64sha256("${path.module}/../agent/BingSiteAuth.xml")
  content_type  = "application/xml; charset=utf-8"
  cache_control = "no-cache"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "site_assets" {
  for_each = local.site_assets

  bucket      = aws_s3_bucket.site.id
  key         = "assets/${each.value}"
  source      = "${path.module}/../agent/assets/${each.value}"
  source_hash = filebase64sha256("${path.module}/../agent/assets/${each.value}")
  content_type = endswith(each.value, ".css") ? "text/css; charset=utf-8" : (
    endswith(each.value, ".mjs") ? "text/javascript; charset=utf-8" : (
      endswith(each.value, ".json") ? "application/json; charset=utf-8" : (
        endswith(each.value, ".png") ? "image/png" : "text/plain; charset=utf-8"
      )
    )
  )
  cache_control = "no-cache"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_iam_role" "usage_publisher" {
  name               = "tollchat-v2-usage-publisher"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "usage_publisher" {
  statement {
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.tollchat_sessions.arn]

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "dynamodb:LeadingKeys"
      values   = ["usage#all"]
    }
  }

  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.site.arn}/usage.json"]
  }

  statement {
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.site.arn]
  }

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.usage_publisher.arn}:*"]
  }
}

resource "aws_iam_role_policy" "usage_publisher" {
  name   = "tollchat-v2-usage-publisher"
  role   = aws_iam_role.usage_publisher.id
  policy = data.aws_iam_policy_document.usage_publisher.json
}

resource "aws_cloudwatch_log_group" "usage_publisher" {
  name              = "/aws/lambda/tollchat-v2-usage-publisher"
  retention_in_days = 30
}

resource "aws_lambda_function" "usage_publisher" {
  function_name = "tollchat-v2-usage-publisher"
  role          = aws_iam_role.usage_publisher.arn
  runtime       = "python3.13"
  handler       = "handler.handler"
  timeout       = 15
  memory_size   = 128

  filename         = data.archive_file.usage_publisher.output_path
  source_code_hash = data.archive_file.usage_publisher.output_base64sha256

  environment {
    variables = {
      SESSION_TABLE_NAME = aws_dynamodb_table.tollchat_sessions.name
      SITE_BUCKET_NAME   = aws_s3_bucket.site.id
      SITE_KMS_KEY_ARN   = aws_kms_key.site.arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.usage_publisher,
    aws_iam_role_policy.usage_publisher,
    aws_s3_object.faq,
    aws_s3_object.index,
    aws_s3_object.privacy,
    aws_s3_object.usage,
  ]
}

resource "aws_cloudwatch_event_rule" "usage_publisher" {
  name                = "tollchat-v2-usage-publisher"
  schedule_expression = "cron(15 5 * * ? *)"
}

resource "aws_lambda_permission" "usage_publisher" {
  statement_id  = "AllowEventBridgeInvokeV2UsagePublisher"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.usage_publisher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.usage_publisher.arn
}

resource "aws_cloudwatch_event_target" "usage_publisher" {
  rule = aws_cloudwatch_event_rule.usage_publisher.name
  arn  = aws_lambda_function.usage_publisher.arn

  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 185
  }

  depends_on = [aws_lambda_permission.usage_publisher]
}

resource "aws_cloudwatch_metric_alarm" "usage_publisher_errors" {
  alarm_name          = "tollchat-v2-usage-publisher-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.usage_publisher.function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "usage_publisher_failed_invocations" {
  alarm_name          = "tollchat-v2-usage-publisher-failed-invocations"
  namespace           = "AWS/Events"
  metric_name         = "FailedInvocations"
  dimensions          = { RuleName = aws_cloudwatch_event_rule.usage_publisher.name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "tollchat-v2-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_lambda_function_url" "public_chat" {
  function_name      = aws_lambda_function.tollchat_proxy.function_name
  qualifier          = aws_lambda_alias.tollchat_live.name
  authorization_type = "AWS_IAM"
  invoke_mode        = "RESPONSE_STREAM"
}

resource "aws_cloudfront_origin_access_control" "public_chat" {
  name                              = "tollchat-v2-public-chat"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "public_chat_routes" {
  name    = "tollchat-v2-public-chat-routes"
  runtime = "cloudfront-js-2.0"
  comment = "Allow only TollChat public API operations"
  publish = true
  code    = file("${path.module}/../agent/public-api-gate.js")
}

resource "aws_cloudfront_function" "public_report_routes" {
  name    = "tollchat-v2-public-report-routes"
  runtime = "cloudfront-js-2.0"
  comment = "Resolve canonical TollChat report directories"
  publish = true
  code    = file("${path.module}/../agent/public-report-routes.js")
}

resource "aws_wafv2_web_acl" "public_chat" {
  name  = "tollchat-v2-public-chat"
  scope = "CLOUDFRONT"

  default_action {
    allow {}
  }

  association_config {
    request_body {
      cloudfront {
        default_size_inspection_limit = "KB_32"
      }
    }
  }

  data_protection_config {
    dynamic "data_protection" {
      for_each = toset(["cookie", "authorization", "referer"])
      content {
        field {
          field_type = "SINGLE_HEADER"
          field_keys = [data_protection.value]
        }
        action                     = "SUBSTITUTION"
        exclude_rate_based_details = false
        exclude_rule_match_details = false
      }
    }

    data_protection {
      field {
        field_type = "QUERY_STRING"
      }
      action                     = "SUBSTITUTION"
      exclude_rate_based_details = false
      exclude_rule_match_details = false
    }
  }

  custom_response_body {
    key = "invalid-request"
    content = jsonencode({
      error = { code = "invalid_request", message = "Provide a valid chat request." }
    })
    content_type = "APPLICATION_JSON"
  }

  custom_response_body {
    key = "unavailable"
    content = jsonencode({
      error = { code = "agent_unavailable", message = "TollChat is temporarily unavailable. Please try again." }
    })
    content_type = "APPLICATION_JSON"
  }

  rule {
    name     = "agent-report-bot-control"
    priority = 0

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesBotControlRuleSet"
        vendor_name = "AWS"
        version     = "Version_6.1"

        managed_rule_group_configs {
          aws_managed_rules_bot_control_rule_set {
            inspection_level        = "COMMON"
            enable_machine_learning = false
          }
        }

        scope_down_statement {
          byte_match_statement {
            field_to_match {
              uri_path {}
            }
            positional_constraint = "STARTS_WITH"
            search_string         = "/tolls/"
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "tollchat-v2-agent-report-bot-control"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = local.assistant_referrers
    content {
      name     = "agent-report-referrer-${rule.key}"
      priority = rule.value.priority

      action {
        count {}
      }

      rule_label {
        name = "assistant-referrer-${rule.key}"
      }

      statement {
        and_statement {
          statement {
            byte_match_statement {
              field_to_match {
                uri_path {}
              }
              positional_constraint = "STARTS_WITH"
              search_string         = "/tolls/"
              text_transformation {
                priority = 0
                type     = "NONE"
              }
            }
          }
          statement {
            regex_match_statement {
              field_to_match {
                single_header {
                  name = "referer"
                }
              }
              regex_string = "^https?://([a-z0-9-]+[.])*${rule.value.host}(:[0-9]+)?([/?#]|$)"
              text_transformation {
                priority = 0
                type     = "LOWERCASE"
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "tollchat-v2-agent-referrer-${rule.key}"
        sampled_requests_enabled   = false
      }
    }
  }

  rule {
    name     = "agent-route-report"
    priority = 6

    action {
      count {}
    }

    rule_label {
      name = "agent-route-report"
    }

    statement {
      byte_match_statement {
        field_to_match {
          uri_path {}
        }
        positional_constraint = "STARTS_WITH"
        search_string         = "/tolls/"
        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "tollchat-v2-agent-route-report"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "allow-static-site"
    priority = 7

    action {
      allow {}
    }

    statement {
      not_statement {
        statement {
          byte_match_statement {
            field_to_match {
              uri_path {}
            }
            positional_constraint = "STARTS_WITH"
            search_string         = "/api/"
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "tollchat-v2-public-static"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "block-oversized-api-body"
    priority = 8

    action {
      block {
        custom_response {
          custom_response_body_key = "invalid-request"
          response_code            = 413
        }
      }
    }

    statement {
      size_constraint_statement {
        comparison_operator = "GT"
        size                = 32768
        field_to_match {
          body { oversize_handling = "MATCH" }
        }
        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "tollchat-v2-public-oversized"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "rate-limit-chat-and-reset"
    priority = 9

    action {
      block {
        custom_response {
          custom_response_body_key = "unavailable"
          response_code            = 429
        }
      }
    }

    statement {
      rate_based_statement {
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
        limit                 = 20

        scope_down_statement {
          and_statement {
            statement {
              byte_match_statement {
                field_to_match {
                  method {}
                }
                positional_constraint = "EXACTLY"
                search_string         = "POST"
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
            statement {
              byte_match_statement {
                field_to_match {
                  uri_path {}
                }
                positional_constraint = "STARTS_WITH"
                search_string         = "/api/"
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "tollchat-v2-public-rate-limit"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "tollchat-v2-public-chat"
    sampled_requests_enabled   = false
  }

  lifecycle {
    ignore_changes = [default_action]
  }
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  aliases             = ["tollchat.ai", "www.tollchat.ai"]

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    domain_name              = trimsuffix(trimprefix(aws_lambda_function_url.public_chat.function_url, "https://"), "/")
    origin_id                = "public-chat"
    origin_access_control_id = aws_cloudfront_origin_access_control.public_chat.id
    connection_attempts      = 1
    connection_timeout       = 5

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_keepalive_timeout = 5
      origin_protocol_policy   = "https-only"
      origin_read_timeout      = 55
      origin_ssl_protocols     = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.public_report_routes.arn
    }
  }

  ordered_cache_behavior {
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    target_origin_id         = "public-chat"
    path_pattern             = "/api/*"
    viewer_protocol_policy   = "https-only"
    compress                 = false
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_except_host.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.public_chat_routes.arn
    }
  }

  web_acl_id = aws_wafv2_web_acl.public_chat.arn

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_lambda_permission" "public_chat_url" {
  statement_id           = "AllowCloudFrontFunctionUrlV2"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.tollchat_proxy.function_name
  qualifier              = aws_lambda_alias.tollchat_live.name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = aws_cloudfront_distribution.site.arn
  function_url_auth_type = "AWS_IAM"
}

resource "aws_lambda_permission" "public_chat_invoke" {
  statement_id             = "AllowCloudFrontFunctionInvokeV2"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.tollchat_proxy.function_name
  qualifier                = aws_lambda_alias.tollchat_live.name
  principal                = "cloudfront.amazonaws.com"
  source_arn               = aws_cloudfront_distribution.site.arn
  invoked_via_function_url = true
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontOAC"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.site.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
    }]
  })
}

data "cloudflare_zone" "tollchat" {
  filter = { name = "tollchat.ai" }
}

resource "aws_acm_certificate" "site" {
  domain_name               = "tollchat.ai"
  subject_alternative_names = ["www.tollchat.ai"]
  validation_method         = "DNS"

  lifecycle { create_before_destroy = true }
}

resource "cloudflare_dns_record" "site_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.domain_name => {
      name  = trimsuffix(dvo.resource_record_name, ".")
      type  = dvo.resource_record_type
      value = trimsuffix(dvo.resource_record_value, ".")
    }
  }

  zone_id = data.cloudflare_zone.tollchat.zone_id
  name    = each.value.name
  type    = each.value.type
  content = each.value.value
  ttl     = 60
  proxied = false

  lifecycle { ignore_changes = [name, type, content] }
}

resource "aws_acm_certificate_validation" "site" {
  certificate_arn = aws_acm_certificate.site.arn
  validation_record_fqdns = [
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.resource_record_name
  ]

  depends_on = [cloudflare_dns_record.site_cert_validation]
}

resource "cloudflare_dns_record" "apex" {
  zone_id = data.cloudflare_zone.tollchat.zone_id
  name    = "tollchat.ai"
  type    = "CNAME"
  content = aws_cloudfront_distribution.site.domain_name
  ttl     = 1
  proxied = false
}

resource "cloudflare_dns_record" "www" {
  zone_id = data.cloudflare_zone.tollchat.zone_id
  name    = "www.tollchat.ai"
  type    = "CNAME"
  content = aws_cloudfront_distribution.site.domain_name
  ttl     = 1
  proxied = false
}

output "public_site" {
  description = "Public TollChat v2 deployment."
  value = {
    distribution_id = aws_cloudfront_distribution.site.id
    url             = "https://tollchat.ai"
  }
}

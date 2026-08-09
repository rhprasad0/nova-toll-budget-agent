# --- coming-soon static site bucket (private, CloudFront-only access) -----

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

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_object" "index" {
  bucket       = aws_s3_bucket.site.id
  key          = "index.html"
  source       = "${path.module}/../site/index.html"
  etag         = filemd5("${path.module}/../site/index.html")
  content_type = "text/html"
  # Revalidate on every hit so a site edit goes live with the apply, no
  # CloudFront invalidation needed. One page, so the origin hits are free.
  cache_control = "no-cache"

  depends_on = [aws_s3_object.site_assets]
}

locals {
  site_assets = {
    "assets/maplibre-gl-6.0.0/maplibre-gl.css"          = "text/css"
    "assets/maplibre-gl-6.0.0/maplibre-gl.mjs"          = "text/javascript"
    "assets/maplibre-gl-6.0.0/maplibre-gl-shared.mjs"   = "text/javascript"
    "assets/maplibre-gl-6.0.0/maplibre-gl-worker.mjs"   = "text/javascript"
    "assets/markdown-it-15.0.0/markdown-it.esm.min.mjs" = "text/javascript"
    "assets/chat-markdown-v1.mjs"                       = "text/javascript"
    "assets/coverage-map-v1.mjs"                        = "text/javascript"
  }
}

resource "aws_s3_object" "site_assets" {
  for_each = local.site_assets

  bucket        = aws_s3_bucket.site.id
  key           = each.key
  source        = "${path.module}/../site/${each.key}"
  etag          = filemd5("${path.module}/../site/${each.key}")
  content_type  = each.value
  cache_control = "public, max-age=31536000, immutable"
}

# --- CloudFront distribution (OAC-gated S3 origin) --------------------------

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "tollchat-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_lambda_function_url" "public_chat" {
  count = var.enable_public_chat ? 1 : 0

  function_name      = aws_lambda_function.tollchat_proxy.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "RESPONSE_STREAM"
}

resource "aws_cloudfront_origin_access_control" "public_chat" {
  count = var.enable_public_chat ? 1 : 0

  name                              = "tollchat-public-chat"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "public_chat_routes" {
  count = var.enable_public_chat ? 1 : 0

  name    = "tollchat-public-chat-routes"
  runtime = "cloudfront-js-2.0"
  comment = "Allow only the three TollChat public API operations"
  publish = true
  code    = file("${path.module}/../site/public-api-gate.js")
}

resource "aws_wafv2_web_acl" "public_chat" {
  count = var.enable_public_chat ? 1 : 0

  name  = "tollchat-public-chat"
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

  custom_response_body {
    key = "invalid-request"
    content = jsonencode({
      error = {
        code    = "invalid_request"
        message = "Provide a valid chat session and message."
      }
    })
    content_type = "APPLICATION_JSON"
  }

  custom_response_body {
    key = "unavailable"
    content = jsonencode({
      error = {
        code    = "agent_unavailable"
        message = "TollChat is temporarily unavailable. Please try again."
      }
    })
    content_type = "APPLICATION_JSON"
  }

  # Keep the static site available when an operator changes the default action
  # to the 503 "unavailable" response during a public-chat incident.
  rule {
    name     = "allow-static-site"
    priority = 0

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
      metric_name                = "tollchat-public-static"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "block-oversized-api-body"
    priority = 1

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
          body {
            oversize_handling = "MATCH"
          }
        }
        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "tollchat-public-oversized"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "rate-limit-chat-and-reset"
    priority = 2

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
      metric_name                = "tollchat-public-rate-limit"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "tollchat-public-chat"
    sampled_requests_enabled   = false
  }

  lifecycle {
    ignore_changes = [default_action]
  }
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

  dynamic "origin" {
    for_each = var.enable_public_chat ? [1] : []
    content {
      domain_name              = trimsuffix(trimprefix(aws_lambda_function_url.public_chat[0].function_url, "https://"), "/")
      origin_id                = "public-chat"
      origin_access_control_id = aws_cloudfront_origin_access_control.public_chat[0].id
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
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    # AWS managed "CachingOptimized" policy -- a static page needs nothing custom.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  dynamic "ordered_cache_behavior" {
    for_each = var.enable_public_chat ? [1] : []
    content {
      allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      cached_methods           = ["GET", "HEAD"]
      target_origin_id         = "public-chat"
      path_pattern             = "/api/*"
      viewer_protocol_policy   = "https-only"
      compress                 = false
      cache_policy_id          = "413f1603-3b9c-4ea9-bf45-8c6a2e83ef45"
      origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

      function_association {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.public_chat_routes[0].arn
      }
    }
  }

  web_acl_id = var.enable_public_chat ? aws_wafv2_web_acl.public_chat[0].arn : null

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_lambda_permission" "public_chat_url" {
  count = var.enable_public_chat ? 1 : 0

  statement_id           = "AllowCloudFrontFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.tollchat_proxy.function_name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = aws_cloudfront_distribution.site.arn
  function_url_auth_type = "AWS_IAM"
}

resource "aws_lambda_permission" "public_chat_invoke" {
  count = var.enable_public_chat ? 1 : 0

  statement_id             = "AllowCloudFrontFunctionInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.tollchat_proxy.function_name
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
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.site.arn
        }
      }
    }]
  })
}

# --- DNS records pointing tollchat.ai / www at the distribution -------------
# proxied = false: CloudFront alone terminates TLS and serves the CDN, no
# double-proxy through Cloudflare's edge.

resource "cloudflare_dns_record" "apex" {
  zone_id = data.cloudflare_zone.tollchat.id
  name    = "tollchat.ai"
  type    = "CNAME"
  content = aws_cloudfront_distribution.site.domain_name
  ttl     = 1
  proxied = false
}

resource "cloudflare_dns_record" "www" {
  zone_id = data.cloudflare_zone.tollchat.id
  name    = "www.tollchat.ai"
  type    = "CNAME"
  content = aws_cloudfront_distribution.site.domain_name
  ttl     = 1
  proxied = false
}

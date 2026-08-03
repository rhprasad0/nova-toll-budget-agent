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
}

locals {
  site_assets = {
    "assets/maplibre-gl-6.0.0/maplibre-gl.css"        = "text/css"
    "assets/maplibre-gl-6.0.0/maplibre-gl.mjs"        = "text/javascript"
    "assets/maplibre-gl-6.0.0/maplibre-gl-shared.mjs" = "text/javascript"
    "assets/maplibre-gl-6.0.0/maplibre-gl-worker.mjs" = "text/javascript"
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

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    # AWS managed "CachingOptimized" policy -- a static page needs nothing custom.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

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

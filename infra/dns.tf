# --- tollchat.ai zone lookup (registered + DNS-hosted at Cloudflare) -------
# Terraform doesn't create this zone -- it already exists at Cloudflare,
# where Email Routing for contact@tollchat.ai needs Cloudflare to stay the
# authoritative nameserver. We only manage records inside it.

data "cloudflare_zone" "tollchat" {
  filter = {
    name = "tollchat.ai"
  }
}

# --- ACM cert for the CloudFront distribution (site.tf) --------------------
# Must be requested in us-east-1 for CloudFront to use it -- provider is
# already pinned to us-east-1 (providers.tf), so no aliasing needed.

resource "aws_acm_certificate" "site" {
  domain_name               = "tollchat.ai"
  subject_alternative_names = ["www.tollchat.ai", "preview.tollchat.ai"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "cloudflare_dns_record" "site_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.domain_name => {
      # ACM's record name/value are FQDNs with a trailing dot; Cloudflare's
      # API strips it on read, so trim here to avoid a permanent no-op diff.
      name  = trimsuffix(dvo.resource_record_name, ".")
      type  = dvo.resource_record_type
      value = trimsuffix(dvo.resource_record_value, ".")
    }
  }

  zone_id = data.cloudflare_zone.tollchat.id
  name    = each.value.name
  type    = each.value.type
  content = each.value.value
  ttl     = 60
  proxied = false

  lifecycle {
    ignore_changes = [name, type, content]
  }
}

resource "aws_acm_certificate_validation" "site" {
  certificate_arn = aws_acm_certificate.site.arn
  validation_record_fqdns = [
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.resource_record_name
  ]

  depends_on = [cloudflare_dns_record.site_cert_validation]
}

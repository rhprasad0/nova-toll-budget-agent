locals {
  phoenix_count              = var.environment == "development" ? 1 : 0
  phoenix_ami                = "ami-04bde3808fe5f70cf"
  phoenix_image              = "arizephoenix/phoenix:version-21.0.0@sha256:1f9a144a5357b4973e93a15718f050247cb7a4ee7b7c6c06ecb91b5eed3fbaad"
  phoenix_port               = 6006
  phoenix_secret_parameter   = "/nova-toll/factory/phoenix-secret"
  phoenix_password_parameter = "/nova-toll/factory/phoenix-admin-password"
  phoenix_rds_ca_sha256      = "90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b"
  phoenix_environment = {
    PHOENIX_SQL_DATABASE_URL               = "postgresql://${local.factory_database_user}@${aws_db_instance.main.address}:5432/phoenix?sslmode=verify-full&sslrootcert=/rds/rds-ca.pem"
    PHOENIX_POSTGRES_USE_AWS_IAM_AUTH      = "true"
    AWS_DEFAULT_REGION                     = local.development_delivery_region
    PHOENIX_PORT                           = tostring(local.phoenix_port)
    PHOENIX_ENABLE_AUTH                    = "true"
    PHOENIX_USE_SECURE_COOKIES             = "true"
    PHOENIX_DISABLE_AGENT_ASSISTANT        = "true"
    PHOENIX_AGENTS_DISABLE_BASH            = "true"
    PHOENIX_AGENTS_DISABLE_WEB_ACCESS      = "true"
    PHOENIX_AGENTS_DISABLE_GITHUB          = "true"
    PHOENIX_ALLOWED_SANDBOX_PROVIDERS      = "NONE"
    PHOENIX_ENABLE_MCP_SERVER              = "false"
    PHOENIX_TELEMETRY_ENABLED              = "false"
    PHOENIX_DEFAULT_RETENTION_POLICY_DAYS  = "30"
    PHOENIX_DISABLE_MODEL_COST_AUTO_UPDATE = "true"
  }
}

resource "aws_iam_role" "phoenix" {
  count              = local.phoenix_count
  name               = "tollchat-phoenix"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "phoenix" {
  count = local.phoenix_count
  statement {
    sid     = "ReadPhoenixSecrets"
    actions = ["ssm:GetParameter"]
    resources = [
      for name in [local.phoenix_secret_parameter, local.phoenix_password_parameter] :
      "arn:aws:ssm:${local.development_delivery_region}:${local.development_delivery_account_id}:parameter${name}"
    ]
  }
  statement {
    sid       = "ConnectPhoenixDatabase"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:us-east-1:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.main.resource_id}/${local.factory_database_user}"]
  }
}

resource "aws_iam_role_policy" "phoenix" {
  count  = local.phoenix_count
  name   = "tollchat-phoenix"
  role   = aws_iam_role.phoenix[0].id
  policy = data.aws_iam_policy_document.phoenix[0].json
}

resource "aws_iam_role_policy_attachment" "phoenix_ssm" {
  count      = local.phoenix_count
  role       = aws_iam_role.phoenix[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "phoenix" {
  count = local.phoenix_count
  name  = "tollchat-phoenix"
  role  = aws_iam_role.phoenix[0].name
}

resource "aws_security_group" "phoenix" {
  count       = local.phoenix_count
  name        = "tollchat-phoenix"
  description = "Phoenix behind a CloudFront VPC origin"
  vpc_id      = data.aws_vpc.default.id
}

data "aws_ec2_managed_prefix_list" "cloudfront_origin_facing" {
  count = local.phoenix_count
  name  = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_vpc_security_group_ingress_rule" "phoenix_from_cloudfront" {
  count             = local.phoenix_count
  security_group_id = aws_security_group.phoenix[0].id
  description       = "CloudFront origin-facing servers"
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront_origin_facing[0].id
  from_port         = local.phoenix_port
  to_port           = local.phoenix_port
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "phoenix_https" {
  count             = local.phoenix_count
  security_group_id = aws_security_group.phoenix[0].id
  description       = "Image pull, packages, SSM and STS through the router NAT"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "phoenix_rds" {
  count                        = local.phoenix_count
  security_group_id            = aws_security_group.phoenix[0].id
  description                  = "Phoenix database"
  referenced_security_group_id = aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_phoenix" {
  count                        = local.phoenix_count
  security_group_id            = aws_security_group.rds.id
  description                  = "Phoenix instance"
  referenced_security_group_id = aws_security_group.phoenix[0].id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_instance" "phoenix" {
  count                       = local.phoenix_count
  ami                         = local.phoenix_ami
  instance_type               = "t4g.small"
  subnet_id                   = aws_subnet.tollchat_private_c.id
  vpc_security_group_ids      = [aws_security_group.phoenix[0].id]
  iam_instance_profile        = aws_iam_instance_profile.phoenix[0].name
  associate_public_ip_address = false

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data_base64 = base64encode(<<-EOF
    Content-Type: multipart/mixed; boundary="//"
    MIME-Version: 1.0

    --//
    Content-Type: text/cloud-config; charset="us-ascii"
    MIME-Version: 1.0

    #cloud-config
    cloud_final_modules:
      - [scripts-user, always]

    --//
    Content-Type: text/x-shellscript; charset="us-ascii"
    MIME-Version: 1.0

    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    systemctl enable --now docker
    install -d -m 0700 /etc/phoenix
    if ! echo '${local.phoenix_rds_ca_sha256}  /etc/phoenix/rds-ca.pem' | sha256sum --check --status; then
      curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /etc/phoenix/rds-ca.pem.new
      echo '${local.phoenix_rds_ca_sha256}  /etc/phoenix/rds-ca.pem.new' | sha256sum --check
      mv /etc/phoenix/rds-ca.pem.new /etc/phoenix/rds-ca.pem
    fi
    PHOENIX_SECRET=$(aws ssm get-parameter --region ${local.development_delivery_region} --name '${local.phoenix_secret_parameter}' --with-decryption --query Parameter.Value --output text)
    PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD=$(aws ssm get-parameter --region ${local.development_delivery_region} --name '${local.phoenix_password_parameter}' --with-decryption --query Parameter.Value --output text)
    export PHOENIX_SECRET PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD
    docker pull '${local.phoenix_image}'
    docker rm -f phoenix || true
    docker run --detach --name phoenix --restart always --network host \
      --volume /etc/phoenix/rds-ca.pem:/rds/rds-ca.pem:ro \
      --env PHOENIX_SECRET --env PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD \
    %{for name, value in local.phoenix_environment~}
      --env '${name}=${value}' \
    %{endfor~}
      '${local.phoenix_image}'
    --//--
  EOF
  )

  tags = {
    Name = "tollchat-phoenix"
  }
}

resource "aws_cloudfront_vpc_origin" "phoenix" {
  count = local.phoenix_count
  vpc_origin_endpoint_config {
    name                   = "tollchat-phoenix"
    arn                    = aws_instance.phoenix[0].arn
    http_port              = local.phoenix_port
    https_port             = 443
    origin_protocol_policy = "http-only"
    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

resource "aws_cloudfront_distribution" "phoenix" {
  count       = local.phoenix_count
  enabled     = true
  comment     = "Phoenix for the factory and the development agent"
  price_class = "PriceClass_100"

  origin {
    response_completion_timeout = 0
    domain_name                 = aws_instance.phoenix[0].private_dns
    origin_id                   = "phoenix"
    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.phoenix[0].id
    }
  }

  default_cache_behavior {
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    target_origin_id         = "phoenix"
    viewer_protocol_policy   = "https-only"
    compress                 = false
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

output "phoenix" {
  description = "Phoenix's public endpoint and instance; null outside development."
  value = local.phoenix_count == 1 ? {
    url         = "https://${aws_cloudfront_distribution.phoenix[0].domain_name}"
    instance_id = aws_instance.phoenix[0].id
  } : null
}

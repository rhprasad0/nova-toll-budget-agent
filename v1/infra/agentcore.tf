locals {
  private_subnets = [aws_subnet.tollchat_private_a.id, aws_subnet.tollchat_private_c.id]
  private_subnets_by_az = {
    us_east_1a = aws_subnet.tollchat_private_a.id
    us_east_1c = aws_subnet.tollchat_private_c.id
  }
}

# Shared operational network retained for v2.
resource "aws_subnet" "tollchat_private_a" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "us-east-1a"
  cidr_block        = "172.31.224.0/24"
  tags              = { Name = "nova-toll-private-a" }
}

resource "aws_subnet" "tollchat_private_c" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "us-east-1c"
  cidr_block        = "172.31.225.0/24"
  tags              = { Name = "nova-toll-private-c" }
}

resource "aws_eip" "tollchat_nat" {
  domain = "vpc"
}

resource "aws_nat_gateway" "tollchat" {
  allocation_id = aws_eip.tollchat_nat.id
  subnet_id     = data.aws_subnet.tailscale_router.id
  tags          = { Name = "nova-toll-preview" }
}

resource "aws_route_table" "tollchat_private" {
  vpc_id = data.aws_vpc.default.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.tollchat.id
  }
}

resource "aws_route_table_association" "tollchat_private" {
  for_each       = local.private_subnets_by_az
  subnet_id      = each.value
  route_table_id = aws_route_table.tollchat_private.id
}

resource "aws_security_group" "tollchat_api_endpoint" {
  name        = "nova-toll-preview-api-endpoint"
  description = "TollChat private API Gateway endpoint"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "tollchat_api_from_tailscale" {
  security_group_id = aws_security_group.tollchat_api_endpoint.id
  cidr_ipv4         = "${aws_instance.tailscale_router.private_ip}/32"
  description       = "Forwarded owner traffic from the Tailscale subnet router"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_security_group" "agentcore_endpoint" {
  name        = "nova-toll-agentcore-endpoint"
  description = "Private AgentCore data-plane endpoint"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_endpoint" "agentcore" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${data.aws_region.current.region}.bedrock-agentcore"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnets
  security_group_ids  = [aws_security_group.agentcore_endpoint.id]
  private_dns_enabled = true
}

resource "aws_vpc_endpoint" "tollchat_api" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${data.aws_region.current.region}.execute-api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnets
  security_group_ids  = [aws_security_group.tollchat_api_endpoint.id]
  private_dns_enabled = false
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = data.aws_vpc.default.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.tollchat_private.id]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:TransactWriteItems"]
      Resource  = ["arn:aws:dynamodb:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/tollchat-v2-anonymous-sessions"]
    }]
  })
}

resource "aws_s3_bucket" "agentcore_artifacts" {
  bucket = "nova-toll-agentcore-920534282028"
}

resource "aws_s3_bucket_public_access_block" "agentcore_artifacts" {
  bucket                  = aws_s3_bucket.agentcore_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id
  rule {
    id     = "trim-old-runtime-artifacts"
    status = "Enabled"
    filter { prefix = "runtime/" }
    noncurrent_version_expiration {
      noncurrent_days           = 30
      newer_noncurrent_versions = 5
    }
  }
  depends_on = [aws_s3_bucket_versioning.agentcore_artifacts]
}

data "aws_iam_policy_document" "agentcore_artifacts" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.agentcore_artifacts.arn, "${aws_s3_bucket.agentcore_artifacts.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id
  policy = data.aws_iam_policy_document.agentcore_artifacts.json
}

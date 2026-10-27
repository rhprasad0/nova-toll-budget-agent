# Development-only MCP server for Muse at https://mcp.tollchat.ai/mcp.
# An administrator applies these resources and deploys the Lambda code
# (v2/runbooks/mcp-server.md); release delivery only ever sees them as no-ops.
locals {
  mcp_name   = "tollchat-v2-mcp-server-dev"
  mcp_domain = "mcp.tollchat.ai"
}

resource "aws_cloudwatch_log_group" "mcp_server" {
  count             = local.is_production ? 0 : 1
  name              = "/aws/lambda/${local.mcp_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "mcp_server" {
  count              = local.is_production ? 0 : 1
  name               = local.mcp_name
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "mcp_server_vpc" {
  count      = local.is_production ? 0 : 1
  role       = aws_iam_role.mcp_server[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "mcp_server" {
  count = local.is_production ? 0 : 1
  name  = local.mcp_name
  role  = aws_iam_role.mcp_server[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ConnectAsCatalogAndPricingRoles"
        Effect = "Allow"
        Action = ["rds-db:connect"]
        Resource = [for role in [local.database_roles.agent, local.database_roles.pricing_caller] :
        "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${role}"]
      },
      {
        Sid      = "CountDailySalaryLookups"
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.mcp_lookups[0].arn
      },
      {
        # SecureString under the AWS managed aws/ssm key, which needs no KMS grant.
        Sid      = "ReadOpenWebNinjaKey"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/nova-toll/openwebninja-api"
      },
    ]
  })
}

# One item per UTC day counts salary lookups against the server's daily cap.
resource "aws_dynamodb_table" "mcp_lookups" {
  count        = local.is_production ? 0 : 1
  name         = "tollchat-v2-mcp-lookups-dev"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "day"

  attribute {
    name = "day"
    type = "N"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_security_group" "mcp_server" {
  count       = local.is_production ? 0 : 1
  name        = local.mcp_name
  description = "TollChat MCP server Lambda ENIs"
  vpc_id      = var.foundation.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_mcp_server" {
  count                        = local.is_production ? 0 : 1
  security_group_id            = var.foundation.rds_security_group_id
  description                  = "TollChat MCP server"
  referenced_security_group_id = aws_security_group.mcp_server[0].id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "mcp_server_to_rds" {
  count                        = local.is_production ? 0 : 1
  security_group_id            = aws_security_group.mcp_server[0].id
  description                  = "RDS only"
  referenced_security_group_id = var.foundation.rds_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# SSM and OpenWeb Ninja have no endpoint in this VPC; DynamoDB routes through its gateway endpoint.
resource "aws_vpc_security_group_egress_rule" "mcp_server_https" {
  count             = local.is_production ? 0 : 1
  security_group_id = aws_security_group.mcp_server[0].id
  description       = "HTTPS through the private subnet NAT path"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_lambda_function" "mcp_server" {
  count         = local.is_production ? 0 : 1
  function_name = local.mcp_name
  role          = aws_iam_role.mcp_server[0].arn
  runtime       = "provided.al2023"
  handler       = "bootstrap"
  architectures = ["x86_64"]
  # Worst cases: about 16 s for two 3 s connects with 5 s statements; 20 s and 15 s tool budgets.
  timeout     = 25
  memory_size = 256

  # The runbook deploys the real package; Terraform only creates the function.
  filename         = data.archive_file.placeholder.output_path
  source_code_hash = data.archive_file.placeholder.output_base64sha256

  reserved_concurrent_executions = 5

  vpc_config {
    subnet_ids         = local.private_subnets
    security_group_ids = [aws_security_group.mcp_server[0].id]
  }

  environment {
    variables = {
      LOOKUP_TABLE      = aws_dynamodb_table.mcp_lookups[0].name
      DB_HOST           = var.foundation.db_instance.address
      DB_PORT           = tostring(var.foundation.db_instance.port)
      DB_NAME           = local.database_name
      DB_CA_BUNDLE_PATH = "/var/task/rds-ca-bundle.pem"
      DB_USER           = local.database_roles.agent
      PRICING_DB_USER   = local.database_roles.pricing_caller
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }

  depends_on = [aws_cloudwatch_log_group.mcp_server, aws_iam_role_policy_attachment.mcp_server_vpc]
}

resource "aws_apigatewayv2_api" "mcp" {
  count                        = local.is_production ? 0 : 1
  name                         = local.mcp_name
  protocol_type                = "HTTP"
  disable_execute_api_endpoint = true
}

resource "aws_apigatewayv2_integration" "mcp" {
  count                  = local.is_production ? 0 : 1
  api_id                 = aws_apigatewayv2_api.mcp[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.mcp_server[0].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 28000
}

resource "aws_apigatewayv2_route" "mcp" {
  for_each  = local.is_production ? toset([]) : toset(["ANY /mcp", "GET /", "GET /privacy"])
  api_id    = aws_apigatewayv2_api.mcp[0].id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.mcp[0].id}"
}

# No access logs: the privacy notice promises that caller IP addresses are never recorded.
resource "aws_apigatewayv2_stage" "mcp" {
  count       = local.is_production ? 0 : 1
  api_id      = aws_apigatewayv2_api.mcp[0].id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 2
    throttling_burst_limit = 5
  }

  # Created after the routes, so the first auto-deployment is the one Terraform records.
  depends_on = [aws_apigatewayv2_route.mcp]
}

resource "aws_lambda_permission" "mcp" {
  count         = local.is_production ? 0 : 1
  statement_id  = "AllowMcpHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mcp_server[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.mcp[0].execution_arn}/*/*"
}

# Validated by a manual Cloudflare CNAME, like dev.tollchat.ai; the runbook reads the record.
resource "aws_acm_certificate" "mcp" {
  count             = local.is_production ? 0 : 1
  domain_name       = local.mcp_domain
  validation_method = "DNS"

  lifecycle { create_before_destroy = true }
}

resource "aws_apigatewayv2_domain_name" "mcp" {
  count       = local.is_production ? 0 : 1
  domain_name = local.mcp_domain

  domain_name_configuration {
    certificate_arn = aws_acm_certificate.mcp[0].arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "mcp" {
  count       = local.is_production ? 0 : 1
  api_id      = aws_apigatewayv2_api.mcp[0].id
  domain_name = aws_apigatewayv2_domain_name.mcp[0].id
  stage       = aws_apigatewayv2_stage.mcp[0].id
}

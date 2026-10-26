# Read-only refresh access, so trusted plans and release delivery see the
# administrator-applied MCP resources in v2/infra/mcp.tf as no-ops. Neither role
# can change them; v2/runbooks/mcp-server.md covers applies and code deploys.
locals {
  mcp_delivery_name    = "tollchat-v2-mcp-server-dev"
  mcp_delivery_account = data.aws_caller_identity.current.account_id
  # API and certificate IDs only exist after bootstrap, so those reads cover the
  # development account's HTTP APIs and certificates (metadata only).
  mcp_read_statements = [
    { Effect = "Allow", Action = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies", "iam:ListRoleTags"], Resource = "arn:aws:iam::${local.mcp_delivery_account}:role/${local.mcp_delivery_name}" },
    { Effect = "Allow", Action = ["lambda:GetFunction", "lambda:GetFunctionCodeSigningConfig", "lambda:GetFunctionConcurrency", "lambda:GetFunctionConfiguration", "lambda:GetPolicy", "lambda:ListTags", "lambda:ListVersionsByFunction"], Resource = "arn:aws:lambda:us-east-1:${local.mcp_delivery_account}:function:${local.mcp_delivery_name}" },
    { Effect = "Allow", Action = ["logs:ListTagsForResource"], Resource = ["arn:aws:logs:us-east-1:${local.mcp_delivery_account}:log-group:/aws/lambda/${local.mcp_delivery_name}", "arn:aws:logs:us-east-1:${local.mcp_delivery_account}:log-group:/aws/lambda/${local.mcp_delivery_name}:*"] },
    { Effect = "Allow", Action = ["apigateway:GET"], Resource = ["arn:aws:apigateway:us-east-1::/apis/*", "arn:aws:apigateway:us-east-1::/domainnames/mcp.tollchat.ai", "arn:aws:apigateway:us-east-1::/domainnames/mcp.tollchat.ai/*"] },
    { Effect = "Allow", Action = ["acm:DescribeCertificate", "acm:ListTagsForCertificate"], Resource = "arn:aws:acm:us-east-1:${local.mcp_delivery_account}:certificate/*" },
  ]
  mcp_read_policy = jsonencode({ Version = "2012-10-17", Statement = local.mcp_read_statements })
}

resource "aws_iam_role_policy" "development_mcp_delivery" {
  count  = var.environment == "development" ? 1 : 0
  name   = "nova-toll-v2-mcp-read"
  role   = aws_iam_role.development_delivery[0].id
  policy = local.mcp_read_policy
}

resource "aws_iam_role_policy" "development_mcp_plan" {
  count  = var.environment == "development" ? 1 : 0
  name   = "nova-toll-v2-mcp-read"
  role   = aws_iam_role.development_plan[0].id
  policy = local.mcp_read_policy
}

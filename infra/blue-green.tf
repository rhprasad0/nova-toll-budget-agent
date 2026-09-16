# Administrator-owned bootstrap inventory. Ordinary application delivery cannot
# create these identities or broaden its own policy.
variable "development_blue_green" {
  type = object({
    green_runtime_id                = string
    staging_distribution_id         = string
    continuous_deployment_policy_id = string
  })
  default = null
  validation {
    condition = var.development_blue_green == null ? true : (
      var.environment == "development" &&
      can(regex("^nova_toll_v2_development_green-[A-Za-z0-9]+$", var.development_blue_green.green_runtime_id)) &&
      can(regex("^E[A-Z0-9]+$", var.development_blue_green.staging_distribution_id)) &&
      can(regex("^[A-Za-z0-9-]{1,128}$", var.development_blue_green.continuous_deployment_policy_id))
    )
    error_message = "Bootstrap requires the exact development green runtime and staging distribution IDs."
  }
}

locals {
  green_trace_log_arns = var.development_blue_green == null ? [] : [
    for endpoint in ["DEFAULT", "preview"] : "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/${var.development_blue_green.green_runtime_id}-${endpoint}"
  ]
}

resource "aws_iam_role_policy" "development_blue_green" {
  count = var.development_blue_green == null ? 0 : 1
  name  = "nova-toll-v2-blue-green-dev"
  role  = aws_iam_role.development_delivery[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadGreenDefaultEndpoint"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:GetAgentRuntimeEndpoint"]
        Resource = "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/${var.development_blue_green.green_runtime_id}/runtime-endpoint/DEFAULT"
      },
      {
        Sid    = "ReleaseSlots"
        Effect = "Allow"
        Action = ["lambda:GetAlias", "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionUrlConfig", "lambda:GetPolicy", "lambda:ListVersionsByFunction", "lambda:ListTags", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:PublishVersion", "lambda:UpdateAlias"]
        Resource = flatten([for name in ["tollchat-v2-chat-proxy-dev", "tollchat-v2-chat-proxy-dev-green"] : [
          "arn:aws:lambda:us-east-1:903859731897:function:${name}",
          "arn:aws:lambda:us-east-1:903859731897:function:${name}:*"
        ]])
      },
      {
        Sid    = "GreenRuntime"
        Effect = "Allow"
        Action = ["bedrock-agentcore:GetAgentRuntime", "bedrock-agentcore:GetAgentRuntimeEndpoint", "bedrock-agentcore:GetResourcePolicy", "bedrock-agentcore:ListTagsForResource", "bedrock-agentcore:UpdateAgentRuntime", "bedrock-agentcore:UpdateAgentRuntimeEndpoint"]
        Resource = [
          "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/${var.development_blue_green.green_runtime_id}",
          "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/${var.development_blue_green.green_runtime_id}/runtime-endpoint/preview"
        ]
      },
      {
        Sid      = "Routing"
        Effect   = "Allow"
        Action   = ["cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:ListTagsForResource", "cloudfront:UpdateDistribution"]
        Resource = [local.development_delivery_distribution_arn, "arn:aws:cloudfront::903859731897:distribution/${var.development_blue_green.staging_distribution_id}"]
      },
      {
        Sid      = "ReadCandidatePolicy"
        Effect   = "Allow"
        Action   = ["cloudfront:GetContinuousDeploymentPolicy"]
        Resource = "arn:aws:cloudfront::903859731897:continuous-deployment-policy/${var.development_blue_green.continuous_deployment_policy_id}"
      },
      {
        Sid      = "PrivateRouting"
        Effect   = "Allow"
        Action   = ["apigateway:GET", "apigateway:PATCH", "apigateway:PUT"]
        Resource = ["arn:aws:apigateway:us-east-1::/restapis/${local.development_delivery_api_id}/resources/*/methods/ANY/integration", "arn:aws:apigateway:us-east-1::/restapis/${local.development_delivery_api_id}/stages/preview"]
      },
      {
        Sid      = "ImmutableArtifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
        Resource = ["arn:aws:s3:::nova-toll-agentcore-903859731897/releases/*", "arn:aws:s3:::tollchat-site-903859731897-dev/releases/*"]
      },
      {
        Sid      = "CandidateHeader"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:us-east-1:903859731897:parameter/nova-toll/development/candidate-header"
      },
      {
        Sid    = "GreenTraceEvidence"
        Effect = "Allow"
        Action = ["logs:DescribeLogGroups", "logs:DescribeLogStreams", "logs:DescribeSubscriptionFilters", "logs:DescribeMetricFilters", "logs:GetDataProtectionPolicy", "logs:ListTagsForResource"]
        Resource = concat(local.green_trace_log_arns, [for arn in local.green_trace_log_arns : "${arn}:*"], [
          "arn:aws:logs:us-east-1:903859731897:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev-green",
          "arn:aws:logs:us-east-1:903859731897:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev-green:*",
        ])
      },
      {
        Sid      = "ReadGreenTraceAlarms"
        Effect   = "Allow"
        Action   = ["cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource"]
        Resource = [for endpoint in ["DEFAULT", "preview"] : "arn:aws:cloudwatch:us-east-1:903859731897:alarm:tollchat-v2-pii-findings-green-${endpoint}-dev"]
      }
    ]
  })
}

# The PR planner reads the same exact inventory but cannot prepare or promote it.
resource "aws_iam_role_policy" "development_blue_green_plan" {
  count = var.development_blue_green == null ? 0 : 1
  name  = "nova-toll-v2-blue-green-plan-dev"
  role  = aws_iam_role.development_plan[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [for statement in jsondecode(aws_iam_role_policy.development_blue_green[0].policy).Statement : merge(statement, {
      Action = [for action in statement.Action : action if can(regex(":(Get|List|Describe)", action)) || action == "apigateway:GET"]
    })]
  })
}

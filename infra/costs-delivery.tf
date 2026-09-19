# Account-local deployment permissions. Billing credentials remain inaccessible
# to these roles; execution permissions live in v2/infra/costs.tf.
locals {
  cost_delivery_name     = "tollchat-v2-cost-publisher${var.environment == "production" ? "" : "-dev"}"
  cost_delivery_role     = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.cost_delivery_name}"
  cost_delivery_function = "arn:aws:lambda:us-east-1:${data.aws_caller_identity.current.account_id}:function:${local.cost_delivery_name}"
  cost_delivery_rule     = "arn:aws:events:us-east-1:${data.aws_caller_identity.current.account_id}:rule/${local.cost_delivery_name}"
  cost_delivery_log      = "arn:aws:logs:us-east-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.cost_delivery_name}"
  cost_plan_statements = [
    { Effect = "Allow", Action = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies", "iam:ListRoleTags"], Resource = local.cost_delivery_role },
    { Effect = "Allow", Action = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionCodeSigningConfig", "lambda:GetPolicy", "lambda:ListTags", "lambda:ListVersionsByFunction"], Resource = local.cost_delivery_function },
    { Effect = "Allow", Action = ["events:DescribeRule", "events:ListTagsForResource", "events:ListTargetsByRule"], Resource = local.cost_delivery_rule },
    { Effect = "Allow", Action = ["logs:DescribeLogGroups", "logs:ListTagsForResource"], Resource = [local.cost_delivery_log, "${local.cost_delivery_log}:*"] },
  ]
  cost_delivery_statements = concat(local.cost_plan_statements, [
    { Effect = "Allow", Action = ["iam:CreateRole", "iam:TagRole", "iam:UntagRole", "iam:PutRolePolicy", "iam:UpdateAssumeRolePolicy"], Resource = local.cost_delivery_role },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = local.cost_delivery_role, Condition = { StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" } } },
    { Effect = "Allow", Action = ["lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:PutFunctionConcurrency", "lambda:AddPermission", "lambda:RemovePermission", "lambda:TagResource", "lambda:UntagResource"], Resource = local.cost_delivery_function },
    { Effect = "Allow", Action = ["events:PutRule", "events:PutTargets", "events:TagResource", "events:UntagResource"], Resource = local.cost_delivery_rule },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:TagResource", "logs:UntagResource"], Resource = [local.cost_delivery_log, "${local.cost_delivery_log}:*"] },
  ])
  cost_plan_policy     = jsonencode({ Version = "2012-10-17", Statement = local.cost_plan_statements })
  cost_delivery_policy = jsonencode({ Version = "2012-10-17", Statement = local.cost_delivery_statements })
}

resource "aws_iam_role_policy" "development_cost_delivery" {
  count  = var.environment == "development" ? 1 : 0
  name   = "nova-toll-v2-cost-delivery"
  role   = aws_iam_role.development_delivery[0].id
  policy = local.cost_delivery_policy
}

resource "aws_iam_role_policy" "development_cost_plan" {
  count  = var.environment == "development" ? 1 : 0
  name   = "nova-toll-v2-cost-plan"
  role   = aws_iam_role.development_plan[0].id
  policy = local.cost_plan_policy
}

resource "aws_iam_role_policy" "production_cost_delivery" {
  count  = var.environment == "production" ? 1 : 0
  name   = "nova-toll-v2-cost-delivery"
  role   = aws_iam_role.production_deploy[0].id
  policy = local.cost_delivery_policy
}

resource "aws_iam_role_policy" "production_cost_plan" {
  count  = var.environment == "production" ? 1 : 0
  name   = "nova-toll-v2-cost-plan"
  role   = aws_iam_role.production_planner[0].id
  policy = local.cost_plan_policy
}

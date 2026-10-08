# PR CI may read only the development model credential through the pinned evaluator.
# Raw combined calibration and holdout evidence never enter hosted CI.
data "aws_iam_policy_document" "shadow_eval_assume" {
  count = var.environment == "development" ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:pull_request"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository"
      values   = ["rhprasad0/nova-toll-budget-agent"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:job_workflow_ref"
      values   = ["rhprasad0/nova-toll-budget-agent/.github/workflows/v2-shadow-eval.yml@144332de99104ec50bccf6614a1b11c119d7d5f7"]
    }
  }
}

resource "aws_iam_role" "shadow_eval" {
  count              = var.environment == "development" ? 1 : 0
  name               = "nova-toll-v2-shadow-eval-dev"
  assume_role_policy = data.aws_iam_policy_document.shadow_eval_assume[0].json
}

resource "aws_iam_role_policy" "shadow_eval" {
  count = length(aws_iam_role.shadow_eval)
  name  = "development-model-credential-only"
  role  = aws_iam_role.shadow_eval[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = "arn:aws:ssm:us-east-1:903859731897:parameter/nova-toll/openai_api_key"
    }]
  })
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# --- toll-fetcher ---------------------------------------------------------

resource "aws_iam_role" "fetcher" {
  name               = "toll-fetcher"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "fetcher_basic" {
  role       = aws_iam_role.fetcher.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "fetcher" {
  statement {
    sid     = "PutRawObjects"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.raw.arn}/raw/feed=i95/*",
      "${aws_s3_bucket.raw.arn}/raw/feed=i66/*",
    ]
  }

  statement {
    sid       = "EncryptRawObjects"
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.raw.arn]
  }

  statement {
    sid     = "ReadTokens"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.i95_token_param_name}",
      "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.i66_token_param_name}",
    ]
  }

  statement {
    sid       = "PutPollMetric"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"] # CloudWatch metrics have no resource ARNs; scoped by namespace condition below.
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["NovaToll"]
    }
  }
}

resource "aws_iam_role_policy" "fetcher" {
  name   = "toll-fetcher"
  role   = aws_iam_role.fetcher.id
  policy = data.aws_iam_policy_document.fetcher.json
}

# The replay role is intentionally separate from Terraform and the Lambda
# execution roles. An account identity must have both sts:AssumeRole and an
# MFA-authenticated session to use it.
data "aws_iam_policy_document" "replay_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    condition {
      test     = "Bool"
      variable = "aws:MultiFactorAuthPresent"
      values   = ["true"]
    }
  }
}

resource "aws_iam_role" "replay" {
  name                 = "toll-raw-replay"
  assume_role_policy   = data.aws_iam_policy_document.replay_assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "replay" {
  statement {
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.raw.arn}/raw/feed=i95/*",
      "${aws_s3_bucket.raw.arn}/raw/feed=i66/*",
    ]
  }

  statement {
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.raw.arn]
  }
}

resource "aws_iam_role_policy" "replay" {
  name   = "toll-raw-replay"
  role   = aws_iam_role.replay.id
  policy = data.aws_iam_policy_document.replay.json
}

# --- GitHub Actions OIDC foundation retained for v2 timed checks -----------

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- Terraform release planning and environment deploy roles ----------------

data "aws_iam_policy_document" "trusted_planner_assume" {
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
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "development_deploy_assume" {
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
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "production_deploy_assume" {
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
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production"]
    }
  }
}

data "aws_iam_policy_document" "trusted_planner_boundary" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = ["nova-toll/v2/terraform.tfstate"]
    }
  }

  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate"]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate.tflock"]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate.tflock",
      ]
    }
  }

  statement {
    actions   = ["kms:GenerateDataKey"]
    resources = [aws_kms_key.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate.tflock"]
    }
  }

  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.release_plan.arn}/production/*/*/release.tfplan"]
  }

  statement {
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.release_plan.arn]
    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["${aws_s3_bucket.release_plan.arn}/production/*/*/release.tfplan"]
    }
  }
}

resource "aws_iam_policy" "trusted_planner_boundary" {
  name        = "nova-toll-trusted-planner-boundary"
  description = "Maximum permissions for the trusted release planner"
  policy      = data.aws_iam_policy_document.trusted_planner_boundary.json
}

resource "aws_iam_role" "trusted_planner" {
  name                 = "nova-toll-trusted-planner"
  assume_role_policy   = data.aws_iam_policy_document.trusted_planner_assume.json
  permissions_boundary = aws_iam_policy.trusted_planner_boundary.arn
}

resource "aws_iam_role" "development_deploy" {
  name               = "nova-toll-development-deploy"
  assume_role_policy = data.aws_iam_policy_document.development_deploy_assume.json
}

resource "aws_iam_role" "production_deploy" {
  name               = "nova-toll-production-deploy"
  assume_role_policy = data.aws_iam_policy_document.production_deploy_assume.json
}

data "aws_iam_policy_document" "trusted_planner" {
  source_policy_documents = [data.aws_iam_policy_document.trusted_planner_boundary.json]
}

resource "aws_iam_role_policy" "trusted_planner" {
  name   = "nova-toll-trusted-planner"
  role   = aws_iam_role.trusted_planner.id
  policy = data.aws_iam_policy_document.trusted_planner.json
}

data "aws_iam_policy_document" "development_deploy" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = ["nova-toll/v2/development/terraform.tfstate"]
    }
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate"]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock"]
  }

  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock",
      ]
    }
  }
}

resource "aws_iam_role_policy" "development_deploy" {
  name   = "nova-toll-development-deploy"
  role   = aws_iam_role.development_deploy.id
  policy = data.aws_iam_policy_document.development_deploy.json
}

data "aws_iam_policy_document" "production_deploy" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = ["nova-toll/v2/terraform.tfstate"]
    }
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate"]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate.tflock"]
  }

  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate.tflock",
      ]
    }
  }
}

resource "aws_iam_role_policy" "production_deploy" {
  name   = "nova-toll-production-deploy"
  role   = aws_iam_role.production_deploy.id
  policy = data.aws_iam_policy_document.production_deploy.json
}

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
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.i95_token_param_name}",
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.i66_token_param_name}",
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

# --- toll-loader -----------------------------------------------------------

resource "aws_iam_role" "loader" {
  name               = "toll-loader"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "loader_vpc" {
  role       = aws_iam_role.loader.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "loader" {
  statement {
    sid       = "DecryptRawObjects"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.raw.arn]
  }

  statement {
    sid       = "GetRawObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*"]
  }

  statement {
    sid       = "ConnectRdsIam"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.main.resource_id}/loader_writer"]
  }

  statement {
    sid       = "SendToOnFailureQueue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.loader_onfailure.arn]
  }
}

resource "aws_iam_role_policy" "loader" {
  name   = "toll-loader"
  role   = aws_iam_role.loader.id
  policy = data.aws_iam_policy_document.loader.json
}

# --- toll-express-fetcher ---------------------------------------------------

resource "aws_iam_role" "express_fetcher" {
  name               = "toll-express-fetcher"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "express_fetcher_basic" {
  role       = aws_iam_role.express_fetcher.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "express_fetcher" {
  statement {
    sid       = "EncryptRawObjects"
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.raw.arn]
  }

  statement {
    sid = "PutExpressLiveObjects"
    # Narrower than toll-fetcher's raw/* -- this function has no business
    # writing any other feed's prefix.
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/feed=i95-live/*"]
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

resource "aws_iam_role_policy" "express_fetcher" {
  name   = "toll-express-fetcher"
  role   = aws_iam_role.express_fetcher.id
  policy = data.aws_iam_policy_document.express_fetcher.json
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
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*"]
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

# --- GitHub Actions CI (RDS integration test) ------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_ci_assume" {
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
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      # Only these two subject shapes ever legitimately occur for this repo's
      # triggers (push to any branch, pull_request) -- narrower than a
      # trailing `:*`, which would also match environment/tag/workflow_call
      # subjects this role has no reason to grant. Fork PRs also produce the
      # `pull_request` shape, so this alone doesn't stop them -- see the
      # `integration` job's `if:` guard in ci.yml for that.
      values = [
        "repo:rhprasad0/nova-toll-budget-agent:ref:refs/heads/*",
        "repo:rhprasad0/nova-toll-budget-agent:pull_request",
      ]
    }
  }
}

resource "aws_iam_role" "github_ci" {
  name               = "nova-toll-github-ci"
  assume_role_policy = data.aws_iam_policy_document.github_ci_assume.json
}

data "aws_iam_policy_document" "github_ci" {
  statement {
    sid       = "ConnectRdsIam"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.main.resource_id}/pricing_reader"]
  }

  statement {
    # Lets the integration test resolve the RDS endpoint at runtime instead
    # of it being hardcoded into the public workflow file.
    sid       = "DescribeRdsEndpoint"
    actions   = ["rds:DescribeDBInstances"]
    resources = [aws_db_instance.main.arn]
  }
}

resource "aws_iam_role_policy" "github_ci" {
  name   = "nova-toll-github-ci"
  role   = aws_iam_role.github_ci.id
  policy = data.aws_iam_policy_document.github_ci.json
}

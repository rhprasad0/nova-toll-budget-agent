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
    sid     = "GetRawObjects"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.raw.arn}/raw/feed=i95/*",
      "${aws_s3_bucket.raw.arn}/raw/feed=i66/*",
    ]
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
      #
      # Subject includes GitHub's immutable owner/repo IDs (91573985 /
      # 1306930324), not just names -- confirmed by decoding a real token
      # from a live workflow run (a plain "repo:owner/repo:..." condition
      # got "Not authorized", since that's not what GitHub actually issues
      # for this repo). This form is also rename/transfer-proof, which a
      # name-only condition isn't, so keep it rather than reverting to names.
      values = [
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/*",
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:pull_request",
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

# --- GitHub Actions CI (Terraform plan/apply) -------------------------------

data "aws_iam_policy_document" "terraform_plan_assume" {
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
      # pull_request only -- this role is never assumable on a direct push.
      # Fork PRs produce this same subject shape, so the workflow's `plan`
      # job carries the same fork `if:` guard as `integration` in ci.yml --
      # this trust condition alone can't distinguish a fork PR.
      values = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:pull_request"]
    }
  }
}

resource "aws_iam_role" "terraform_plan" {
  name               = "nova-toll-terraform-plan"
  assume_role_policy = data.aws_iam_policy_document.terraform_plan_assume.json
}

resource "aws_iam_role_policy_attachment" "terraform_plan_readonly" {
  role       = aws_iam_role.terraform_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "terraform_plan" {
  statement {
    # ReadOnlyAccess excludes kms:Decrypt (a write-level action in AWS's own
    # classification). Scoped to exactly the two keys `terraform plan` needs
    # to read: encrypted state, and the Cloudflare token it must decrypt to
    # initialize the cloudflare provider. Deliberately not the shared
    # alias/aws/ssm default key -- see the cloudflare_token key comment in
    # kms.tf for why that would leak decrypt access to every other
    # SecureString in the account (VDOT feed tokens, Tailscale authkey).
    sid       = "DecryptStateAndCloudflareToken"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.tfstate.arn, aws_kms_key.cloudflare_token.arn]
  }
}

resource "aws_iam_role_policy" "terraform_plan" {
  name   = "nova-toll-terraform-plan"
  role   = aws_iam_role.terraform_plan.id
  policy = data.aws_iam_policy_document.terraform_plan.json
}

data "aws_iam_policy_document" "terraform_apply_assume" {
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
      # main-branch push only -- never pull_request, never other branches.
      # This repo's own Terraform manages IAM (this role included), so any
      # apply-capable identity is admin-equivalent no matter how the
      # permission policy below is scoped -- this trust condition is the
      # real boundary.
      values = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "terraform_apply" {
  name               = "nova-toll-terraform-apply"
  assume_role_policy = data.aws_iam_policy_document.terraform_apply_assume.json
}

resource "aws_iam_role_policy_attachment" "terraform_apply_admin" {
  role       = aws_iam_role.terraform_apply.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

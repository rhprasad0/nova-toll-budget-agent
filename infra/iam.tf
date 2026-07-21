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
    sid       = "PutRawObjects"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*"]
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

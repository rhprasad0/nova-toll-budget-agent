data "archive_file" "placeholder" {
  type        = "zip"
  source_file = "${path.module}/lambda-stub/handler.py"
  output_path = "${path.module}/build/placeholder.zip"
}

locals {
  fetcher_zip_path = var.fetcher_package_path != "" ? var.fetcher_package_path : data.archive_file.placeholder.output_path
  fetcher_zip_hash = var.fetcher_package_path != "" ? filebase64sha256(var.fetcher_package_path) : data.archive_file.placeholder.output_base64sha256

  loader_zip_path = var.loader_package_path != "" ? var.loader_package_path : data.archive_file.placeholder.output_path
  loader_zip_hash = var.loader_package_path != "" ? filebase64sha256(var.loader_package_path) : data.archive_file.placeholder.output_base64sha256

  express_fetcher_zip_path = var.express_fetcher_package_path != "" ? var.express_fetcher_package_path : data.archive_file.placeholder.output_path
  express_fetcher_zip_hash = var.express_fetcher_package_path != "" ? filebase64sha256(var.express_fetcher_package_path) : data.archive_file.placeholder.output_base64sha256
}

resource "aws_cloudwatch_log_group" "fetcher" {
  name              = "/aws/lambda/toll-fetcher"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "loader" {
  name              = "/aws/lambda/toll-loader"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "express_fetcher" {
  name              = "/aws/lambda/toll-express-fetcher"
  retention_in_days = 30
}

# --- toll-fetcher ---------------------------------------------------------

resource "aws_lambda_function" "fetcher" {
  function_name = "toll-fetcher"
  role          = aws_iam_role.fetcher.arn
  runtime       = "python3.13"
  handler       = var.fetcher_handler
  timeout       = 90
  memory_size   = 128

  filename         = local.fetcher_zip_path
  source_code_hash = local.fetcher_zip_hash

  environment {
    variables = {
      I95_TOKEN_PARAM = var.i95_token_param_name
      I66_TOKEN_PARAM = var.i66_token_param_name
      RAW_BUCKET      = aws_s3_bucket.raw.bucket
      RAW_KMS_KEY_ARN = aws_kms_key.raw.arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.fetcher]
}

# WAF etiquette: one attempt per tick — a re-fetch a minute later is normal
# client behavior, not a retry storm, so this stays low but nonzero.
resource "aws_lambda_function_event_invoke_config" "fetcher" {
  function_name          = aws_lambda_function.fetcher.function_name
  maximum_retry_attempts = 1
}

# --- toll-loader -----------------------------------------------------------

resource "aws_sqs_queue" "loader_onfailure" {
  name = "toll-loader-onfailure"
}

resource "aws_lambda_function" "loader" {
  function_name = "toll-loader"
  role          = aws_iam_role.loader.arn
  runtime       = "python3.13"
  handler       = var.loader_handler
  # 90s: in-VPC cold starts (ENI attach + psycopg import + verify-full connect)
  # can exceed 30s and time out async loads; retries then stampede. See Finding B.
  timeout     = 90
  memory_size = 128

  filename         = local.loader_zip_path
  source_code_hash = local.loader_zip_hash

  reserved_concurrent_executions = 5

  vpc_config {
    subnet_ids         = data.aws_subnets.default.ids
    security_group_ids = [aws_security_group.loader.id]
  }

  environment {
    variables = {
      DB_HOST    = aws_db_instance.main.address
      DB_PORT    = tostring(aws_db_instance.main.port)
      DB_NAME    = aws_db_instance.main.db_name
      DB_USER    = "loader_writer"
      RAW_BUCKET = aws_s3_bucket.raw.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.loader, aws_iam_role_policy_attachment.loader_vpc]
}

resource "aws_lambda_function_event_invoke_config" "loader" {
  function_name = aws_lambda_function.loader.function_name

  destination_config {
    on_failure {
      destination = aws_sqs_queue.loader_onfailure.arn
    }
  }
}

# --- toll-express-fetcher --------------------------------------------------

resource "aws_lambda_function" "express_fetcher" {
  function_name = "toll-express-fetcher"
  role          = aws_iam_role.express_fetcher.arn
  runtime       = "python3.13"
  handler       = var.express_fetcher_handler
  timeout       = 90
  memory_size   = 128

  filename         = local.express_fetcher_zip_path
  source_code_hash = local.express_fetcher_zip_hash

  environment {
    variables = {
      RAW_BUCKET      = aws_s3_bucket.raw.bucket
      RAW_KMS_KEY_ARN = aws_kms_key.raw.arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.express_fetcher]
}

# Unlike toll-fetcher's VDOT feeds, a missed poll here costs nothing -- there's
# no history to lose (docs/poller-spec.md), the next tick re-establishes
# "current". So no retry budget at all, not even the fetcher's minimal 1.
resource "aws_lambda_function_event_invoke_config" "express_fetcher" {
  function_name          = aws_lambda_function.express_fetcher.function_name
  maximum_retry_attempts = 0
}

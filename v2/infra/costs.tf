# Billing reads and publication are isolated from the database/model publishers.
locals {
  cost_name       = "tollchat-v2-cost-publisher${local.suffix}"
  cost_role_arn   = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.cost_name}"
  cost_lambda_arn = "arn:aws:lambda:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:function:${local.cost_name}"
  cost_rule_arn   = "arn:aws:events:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:rule/${local.cost_name}"
  cost_log_arn    = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.cost_name}"
  cost_key_arn    = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/nova-toll/openai_billing_api_key"
}

resource "aws_cloudwatch_log_group" "costs" {
  region            = data.aws_region.current.region
  name              = "/aws/lambda/${local.cost_name}"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "costs" {
  name = local.cost_name
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "costs" {
  name = local.cost_name
  role = aws_iam_role.costs.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid    = "ReadAccountBilling", Effect = "Allow"
        Action = ["ce:GetCostAndUsage"], Resource = "*"
      },
      {
        Sid    = "PublishSnapshot", Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.site.arn}/costs.json"
      },
      {
        Sid       = "FindSnapshot", Effect = "Allow"
        Action    = ["s3:ListBucket"], Resource = aws_s3_bucket.site.arn
        Condition = { StringEquals = { "s3:prefix" = "costs.json" } }
      },
      {
        Sid    = "SnapshotEncryption", Effect = "Allow"
        Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.site.arn
        Condition = { StringEquals = {
          "kms:ViaService"                   = "s3.${data.aws_region.current.region}.amazonaws.com"
          "kms:EncryptionContext:aws:s3:arn" = aws_s3_bucket.site.arn
        } }
      },
      {
        Sid    = "WriteLogs", Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.cost_log_arn}:*"
      }
      ], [for statement in [
        {
          Sid    = "ReadBillingKey", Effect = "Allow"
          Action = ["ssm:GetParameter"], Resource = local.cost_key_arn
        },
        {
          Sid    = "DecryptBillingKey", Effect = "Allow"
          Action = ["kms:Decrypt"], Resource = "arn:aws:kms:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:key/*"
          Condition = { StringEquals = {
            "kms:ViaService"                      = "ssm.${data.aws_region.current.region}.amazonaws.com"
            "kms:EncryptionContext:PARAMETER_ARN" = local.cost_key_arn
          } }
        }
    ] : statement if local.is_production])
  })
}

resource "aws_lambda_function" "costs" {
  region                         = data.aws_region.current.region
  function_name                  = local.cost_name
  role                           = local.cost_role_arn
  runtime                        = "python3.13"
  handler                        = "costs.handler"
  architectures                  = ["x86_64"]
  timeout                        = 300
  memory_size                    = 256
  reserved_concurrent_executions = 1
  filename                       = local.publisher_zip_path
  source_code_hash               = local.publisher_zip_hash
  environment {
    variables = {
      DEPLOYMENT_ENVIRONMENT = var.environment
      COST_BUCKET            = aws_s3_bucket.site.id
    }
  }
  lifecycle {
    precondition {
      condition     = var.publisher_package_path != ""
      error_message = "Cost publication requires the reviewed publisher archive."
    }
  }
  depends_on = [aws_cloudwatch_log_group.costs, aws_iam_role_policy.costs]
}

resource "aws_cloudwatch_event_rule" "costs" {
  region              = data.aws_region.current.region
  name                = local.cost_name
  schedule_expression = local.is_production ? "cron(0 9 * * ? *)" : "cron(0 8 * * ? *)"
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "costs" {
  region    = data.aws_region.current.region
  rule      = aws_cloudwatch_event_rule.costs.name
  target_id = "cost-publisher"
  arn       = local.cost_lambda_arn
  input     = "{}"
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }
  depends_on = [aws_lambda_function.costs, aws_lambda_permission.costs]
}

resource "aws_lambda_permission" "costs" {
  region         = data.aws_region.current.region
  statement_id   = "DailyCostPublication"
  action         = "lambda:InvokeFunction"
  function_name  = local.cost_name
  principal      = "events.amazonaws.com"
  source_arn     = local.cost_rule_arn
  source_account = data.aws_caller_identity.current.account_id
  depends_on     = [aws_lambda_function.costs, aws_cloudwatch_event_rule.costs]
}

resource "aws_s3_object" "cost_dashboard" {
  region        = data.aws_region.current.region
  bucket        = aws_s3_bucket.site.id
  key           = "costs.html"
  content       = templatefile("${path.module}/../agent/costs.html", { environment = var.environment })
  content_type  = "text/html; charset=utf-8"
  cache_control = "no-cache"
  depends_on    = [aws_s3_bucket_server_side_encryption_configuration.site]
}

resource "aws_s3_object" "cost_assets" {
  region        = data.aws_region.current.region
  for_each      = toset(["costs.css", "costs.mjs"])
  bucket        = aws_s3_bucket.site.id
  key           = "assets/${each.key}"
  source        = "${path.module}/../agent/assets/${each.key}"
  source_hash   = filebase64sha256("${path.module}/../agent/assets/${each.key}")
  content_type  = each.key == "costs.css" ? "text/css; charset=utf-8" : "text/javascript; charset=utf-8"
  cache_control = "no-cache"
  depends_on    = [aws_s3_bucket_server_side_encryption_configuration.site]
}

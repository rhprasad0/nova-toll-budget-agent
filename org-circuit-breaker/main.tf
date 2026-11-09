# Applied by hand from the management account; see README.md.
terraform {
  required_version = ">= 1.10"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.47"
    }
  }

  backend "s3" {
    bucket       = "agentcore-evals-tfstate-407645373626"
    key          = "nova-toll/circuit-breaker/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

locals {
  accounts   = jsondecode(file("${path.module}/../infra/account-contract.json")).accounts
  management = local.accounts.management.id
  targets    = [local.accounts.development.id, local.accounts.production.id]
  name       = "org-circuit-breaker"
}

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = [local.management]
}

# Kept out of this public repo; see README.md.
data "aws_ssm_parameter" "alert_email" {
  name = "/org-circuit-breaker/alert-email"
}

variable "monthly_limit_usd" {
  type    = string
  default = "250"
}

data "aws_organizations_organization" "current" {}

resource "aws_budgets_budget" "org" {
  name         = local.name
  budget_type  = "COST"
  limit_amount = var.monthly_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Gross spend, so credits cannot delay a trip.
  cost_types {
    include_credit = false
    include_refund = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [data.aws_ssm_parameter.alert_email.value]
  }
}

resource "aws_organizations_policy" "deny_all" {
  name = local.name
  type = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Deny"
      Action   = "*"
      Resource = "*"
      Condition = {
        ArnNotLike = {
          "aws:PrincipalArn" = [
            "arn:aws:iam::*:role/OrganizationAccountAccessRole",
            "arn:aws:iam::*:role/aws-reserved/sso.amazonaws.com/*AWSReservedSSO_AdministratorAccess*",
          ]
        }
      }
    }]
  })
}

resource "aws_iam_role" "breaker" {
  name = local.name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_cloudwatch_log_group" "breaker" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 90
}

resource "aws_iam_role_policy" "breaker" {
  role = aws_iam_role.breaker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "budgets:ViewBudget"
        Resource = aws_budgets_budget.org.arn
      },
      {
        Effect   = "Allow"
        Action   = "organizations:ListTargetsForPolicy"
        Resource = aws_organizations_policy.deny_all.arn
      },
      {
        Effect = "Allow"
        Action = ["organizations:AttachPolicy", "organizations:DetachPolicy"]
        Resource = concat(
          [aws_organizations_policy.deny_all.arn],
          [for id in local.targets : "arn:aws:organizations::${local.management}:account/${data.aws_organizations_organization.current.id}/${id}"],
        )
      },
      {
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = [for id in local.targets : "arn:aws:iam::${id}:role/OrganizationAccountAccessRole"]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.breaker.arn}:*"
      },
    ]
  })
}

data "archive_file" "breaker" {
  type        = "zip"
  source_file = "${path.module}/handler.py"
  output_path = "${path.module}/.terraform/handler.zip"
}

resource "aws_lambda_function" "breaker" {
  function_name                  = local.name
  role                           = aws_iam_role.breaker.arn
  runtime                        = "python3.13"
  handler                        = "handler.handler"
  filename                       = data.archive_file.breaker.output_path
  source_code_hash               = data.archive_file.breaker.output_base64sha256
  timeout                        = 900
  memory_size                    = 256
  reserved_concurrent_executions = 1 # A restore must not race an hourly sweep.

  environment {
    variables = {
      BUDGET_NAME           = aws_budgets_budget.org.name
      MANAGEMENT_ACCOUNT_ID = local.management
      SCP_POLICY_ID         = aws_organizations_policy.deny_all.id
      TARGET_ACCOUNT_IDS    = join(",", local.targets)
    }
  }

  depends_on = [aws_cloudwatch_log_group.breaker, aws_iam_role_policy.breaker]
}

resource "aws_cloudwatch_event_rule" "hourly" {
  name                = local.name
  schedule_expression = "rate(1 hour)"
}

resource "aws_cloudwatch_event_target" "hourly" {
  rule = aws_cloudwatch_event_rule.hourly.name
  arn  = aws_lambda_function.breaker.arn
}

resource "aws_lambda_permission" "hourly" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.breaker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly.arn
}

# Without this alarm, a failing breaker looks like one with nothing to do.
resource "aws_sns_topic" "alerts" {
  name              = local.name
  kms_master_key_id = aws_kms_key.alerts.arn
}

# CloudWatch cannot publish through the AWS-managed SNS key.
resource "aws_kms_key" "alerts" {
  description             = "Org circuit breaker alarm notifications"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.management}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource  = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount"                      = local.management
            "kms:EncryptionContext:aws:sns:topicArn" = "arn:aws:sns:us-east-1:${local.management}:${local.name}"
          }
        }
      },
    ]
  })
}

resource "aws_sns_topic_subscription" "alerts" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = data.aws_ssm_parameter.alert_email.value
}

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${local.name}-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.breaker.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

output "function_name" {
  value = aws_lambda_function.breaker.function_name
}

output "scp_policy_id" {
  value = aws_organizations_policy.deny_all.id
}

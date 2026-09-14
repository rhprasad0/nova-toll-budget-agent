# Account-local prerequisites for sanitized AgentCore telemetry.
locals {
  telemetry_account = var.environment == "development" ? local.development_delivery_account_id : local.production_delivery_account_id
  telemetry_suffix  = var.environment == "development" ? "-dev" : ""
  telemetry_runtime = var.environment == "development" ? "nova_toll_v2_development-Y69XBf88Bl" : "nova_toll_v2-W6989LEw44"
  telemetry_groups  = [for endpoint in ["DEFAULT", "preview"] : "arn:aws:logs:us-east-1:${local.telemetry_account}:log-group:/aws/bedrock-agentcore/runtimes/${local.telemetry_runtime}-${endpoint}:*"]
  telemetry_alarms  = [for name in ["redaction-failures", "pii-findings-DEFAULT", "pii-findings-preview"] : "arn:aws:cloudwatch:us-east-1:${local.telemetry_account}:alarm:tollchat-v2-${name}${local.telemetry_suffix}"]

  telemetry_read_statements = [
    {
      Sid      = "ReadTelemetryLogProtection"
      Effect   = "Allow"
      Action   = ["logs:GetDataProtectionPolicy", "logs:DescribeMetricFilters"]
      Resource = local.telemetry_groups
    },
    {
      Sid      = "ReadTelemetryAlarms"
      Effect   = "Allow"
      Action   = ["cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource"]
      Resource = local.telemetry_alarms
    },
  ]
  telemetry_write_statements = [
    {
      Sid      = "ManageTelemetryLogProtection"
      Effect   = "Allow"
      Action   = ["logs:PutDataProtectionPolicy", "logs:PutMetricFilter"]
      Resource = local.telemetry_groups
    },
    {
      Sid      = "ManageTelemetryAlarms"
      Effect   = "Allow"
      Action   = ["cloudwatch:PutMetricAlarm", "cloudwatch:TagResource", "cloudwatch:UntagResource"]
      Resource = local.telemetry_alarms
    },
  ]
  # The production trace statements were previously excluded. Restore just that
  # finite set in a separate policy, preserving existing policy partitioning.
  production_telemetry_archive_statements = [
    for statement in jsondecode(local.production_delivery_application_policy_json).Statement : statement
    if contains(local.development_delivery_trace_statement_sids, statement.Sid)
  ]
  telemetry_delivery_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = concat(local.telemetry_read_statements, local.telemetry_write_statements, [for statement in local.production_telemetry_archive_statements : statement if var.environment == "production"])
  })
  telemetry_plan_policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.telemetry_read_statements, [
      for statement in local.production_telemetry_archive_statements : statement if var.environment == "production" && startswith(statement.Sid, "Read")
    ])
  })
}

locals {
  production_telemetry_bucket_arn = "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${local.telemetry_account}"
}

data "aws_iam_policy_document" "production_agentcore_trace_logs_assume" {
  count = var.environment == "production" ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["logs.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "aws:SourceArn"
      values = concat(
        [for arn in local.telemetry_groups : trimsuffix(arn, ":*")],
        [for arn in [for arn in local.telemetry_groups : trimsuffix(arn, ":*")] : "${arn}:*"],
      )
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.telemetry_account]
    }
  }
}

data "aws_iam_policy_document" "production_agentcore_trace_logs" {
  count = var.environment == "production" ? 1 : 0

  statement {
    actions   = ["firehose:PutRecord"]
    resources = ["arn:aws:firehose:us-east-1:${local.telemetry_account}:deliverystream/nova-toll-v2-agentcore-traces"]
  }
}

resource "aws_iam_role" "production_agentcore_trace_logs" {
  count                = var.environment == "production" ? 1 : 0
  name                 = "nova-toll-v2-agentcore-traces-logs"
  assume_role_policy   = data.aws_iam_policy_document.production_agentcore_trace_logs_assume[0].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "production_agentcore_trace_logs" {
  count  = var.environment == "production" ? 1 : 0
  name   = "nova-toll-v2-agentcore-traces-logs"
  role   = aws_iam_role.production_agentcore_trace_logs[0].id
  policy = data.aws_iam_policy_document.production_agentcore_trace_logs[0].json
}

data "aws_iam_policy_document" "production_agentcore_trace_firehose_assume" {
  count = var.environment == "production" ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [local.telemetry_account]
    }
  }
}

data "aws_iam_policy_document" "production_agentcore_trace_firehose" {
  count = var.environment == "production" ? 1 : 0

  statement {
    actions   = ["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"]
    resources = ["arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${local.telemetry_account}"]
  }

  statement {
    actions   = ["s3:AbortMultipartUpload", "s3:GetObject", "s3:PutObject"]
    resources = ["${local.production_telemetry_bucket_arn}/agentcore-traces/*"]
  }

  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [local.production_delivery_measurement_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${local.production_delivery_region}.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${local.telemetry_account}"]
    }
  }
}

resource "aws_iam_role" "production_agentcore_trace_firehose" {
  count                = var.environment == "production" ? 1 : 0
  name                 = "nova-toll-v2-agentcore-traces-firehose"
  assume_role_policy   = data.aws_iam_policy_document.production_agentcore_trace_firehose_assume[0].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "production_agentcore_trace_firehose" {
  count  = var.environment == "production" ? 1 : 0
  name   = "nova-toll-v2-agentcore-traces-firehose"
  role   = aws_iam_role.production_agentcore_trace_firehose[0].id
  policy = data.aws_iam_policy_document.production_agentcore_trace_firehose[0].json
}


locals {
  telemetry_pii_types = toset([
    "ADDRESS", "AGE", "NAME", "EMAIL", "PHONE", "USERNAME", "PASSWORD",
    "DRIVER_ID", "LICENSE_PLATE", "VEHICLE_IDENTIFICATION_NUMBER",
    "CREDIT_DEBIT_CARD_CVV", "CREDIT_DEBIT_CARD_EXPIRY", "CREDIT_DEBIT_CARD_NUMBER",
    "PIN", "INTERNATIONAL_BANK_ACCOUNT_NUMBER", "SWIFT_CODE", "IP_ADDRESS",
    "MAC_ADDRESS", "URL", "AWS_ACCESS_KEY", "AWS_SECRET_KEY", "US_BANK_ACCOUNT_NUMBER",
    "US_BANK_ROUTING_NUMBER", "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "US_PASSPORT_NUMBER",
    "US_SOCIAL_SECURITY_NUMBER", "CA_HEALTH_NUMBER", "CA_SOCIAL_INSURANCE_NUMBER",
    "UK_NATIONAL_HEALTH_SERVICE_NUMBER", "UK_NATIONAL_INSURANCE_NUMBER", "UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER",
  ])
}

resource "aws_bedrock_guardrail" "telemetry" {
  name                      = "nova-toll-v2-telemetry${local.telemetry_suffix}"
  description               = "Best-effort PII redaction of telemetry before export"
  blocked_input_messaging   = "[CONTENT OMITTED: telemetry policy]"
  blocked_outputs_messaging = "[CONTENT OMITTED: telemetry policy]"
  tags                      = { purpose = "telemetry-redaction", environment = var.environment }
  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = local.telemetry_pii_types
      content {
        type           = pii_entities_config.value
        action         = "ANONYMIZE"
        input_action   = "ANONYMIZE"
        output_action  = "ANONYMIZE"
        input_enabled  = true
        output_enabled = true
      }
    }
    regexes_config {
      name           = "authorization_header"
      description    = "Authorization bearer or basic credentials"
      pattern        = "(?i)\\b(?:authorization[\"']?\\s*[:=]\\s*[\"']?(?:bearer|basic)\\s+|x-api-key[\"']?\\s*[:=]\\s*[\"']?)[A-Za-z0-9._~+/=-]{8,}"
      action         = "ANONYMIZE"
      input_action   = "ANONYMIZE"
      output_action  = "ANONYMIZE"
      input_enabled  = true
      output_enabled = true
    }
    regexes_config {
      name           = "aws_access_key_id"
      description    = "AWS access key identifiers"
      pattern        = "\\b(?:AKIA|ASIA)[A-Z0-9]{16}\\b"
      action         = "ANONYMIZE"
      input_action   = "ANONYMIZE"
      output_action  = "ANONYMIZE"
      input_enabled  = true
      output_enabled = true
    }
    regexes_config {
      name           = "api_key"
      description    = "OpenAI, Anthropic, and GitHub API keys"
      pattern        = "\\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_-]{20,})\\b"
      action         = "ANONYMIZE"
      input_action   = "ANONYMIZE"
      output_action  = "ANONYMIZE"
      input_enabled  = true
      output_enabled = true
    }
    regexes_config {
      name           = "connection_string"
      description    = "Database and cache URI connection strings"
      pattern        = "\\b(?:postgres(?:ql)?|mysql|mongodb(?:\\+srv)?|redis)://[^\\s\"']+"
      action         = "ANONYMIZE"
      input_action   = "ANONYMIZE"
      output_action  = "ANONYMIZE"
      input_enabled  = true
      output_enabled = true
    }
  }
  lifecycle { prevent_destroy = true }
}

resource "aws_bedrock_guardrail_version" "telemetry" {
  guardrail_arn = aws_bedrock_guardrail.telemetry.guardrail_arn
  description   = "telemetry-${substr(sha256(jsonencode(aws_bedrock_guardrail.telemetry.sensitive_information_policy_config)), 0, 16)}"
  skip_destroy  = true
}

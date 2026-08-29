locals {
  agentcore_zip_path = var.agentcore_package_path != "" ? var.agentcore_package_path : data.archive_file.placeholder.output_path
  proxy_zip_path     = var.chat_proxy_package_path != "" ? var.chat_proxy_package_path : data.archive_file.placeholder.output_path
  proxy_zip_hash     = var.chat_proxy_package_path != "" ? filebase64sha256(var.chat_proxy_package_path) : data.archive_file.placeholder.output_base64sha256
  private_subnets    = [data.aws_subnet.tollchat_private_a.id, data.aws_subnet.tollchat_private_c.id]
  private_api_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "${aws_api_gateway_rest_api.tollchat.execution_arn}/*"
        Condition = { StringEquals = { "aws:SourceVpce" = data.aws_vpc_endpoint.tollchat_api.id } }
      },
      {
        Effect    = "Deny"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "${aws_api_gateway_rest_api.tollchat.execution_arn}/*"
        Condition = { StringNotEquals = { "aws:SourceVpce" = data.aws_vpc_endpoint.tollchat_api.id } }
      },
    ]
  })
  agentcore_policy_resources = {
    runtime  = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_arn
    endpoint = aws_bedrockagentcore_agent_runtime_endpoint.tollchat.agent_runtime_endpoint_arn
  }
  agentcore_resource_policies = {
    for name, arn in local.agentcore_policy_resources : name => jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid       = "AllowProxyFromPrivateEndpoint"
          Effect    = "Allow"
          Principal = { AWS = aws_iam_role.tollchat_proxy.arn }
          Action = [
            "bedrock-agentcore:InvokeAgentRuntime",
            "bedrock-agentcore:StopRuntimeSession",
          ]
          Resource  = arn
          Condition = { StringEquals = { "aws:SourceVpce" = data.aws_vpc_endpoint.agentcore.id } }
        },
        {
          Sid       = "DenyOutsidePrivateEndpoint"
          Effect    = "Deny"
          Principal = "*"
          Action = [
            "bedrock-agentcore:InvokeAgentRuntime",
            "bedrock-agentcore:StopRuntimeSession",
          ]
          Resource  = arn
          Condition = { StringNotEquals = { "aws:SourceVpce" = data.aws_vpc_endpoint.agentcore.id } }
        },
      ]
    })
  }
}

resource "aws_security_group" "tollchat_runtime" {
  name        = "nova-toll-v2-agentcore-runtime${local.suffix}"
  description = "TollChat v2 AgentCore runtime egress"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_security_group" "tollchat_proxy" {
  name        = "nova-toll-v2-chat-proxy${local.suffix}"
  description = "TollChat v2 proxy Lambda ENIs"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_runtime" {
  security_group_id            = data.aws_security_group.rds.id
  description                  = "TollChat v2 AgentCore runtime"
  referenced_security_group_id = aws_security_group.tollchat_runtime.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "runtime_to_rds" {
  security_group_id            = aws_security_group.tollchat_runtime.id
  referenced_security_group_id = data.aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "runtime_https" {
  security_group_id = aws_security_group.tollchat_runtime.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "agentcore_from_proxy" {
  security_group_id            = data.aws_security_group.agentcore_endpoint.id
  description                  = "TollChat v2 private proxy"
  referenced_security_group_id = aws_security_group.tollchat_proxy.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "proxy_https" {
  security_group_id = aws_security_group.tollchat_proxy.id
  cidr_ipv4         = data.aws_vpc.default.cidr_block
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "proxy_to_dynamodb" {
  security_group_id = aws_security_group.tollchat_proxy.id
  description       = "Shared DynamoDB gateway endpoint"
  prefix_list_id    = data.aws_prefix_list.dynamodb.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_dynamodb_table" "tollchat_sessions" {
  name         = "tollchat-v2-anonymous-sessions${local.suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "credential_hash"

  attribute {
    name = "credential_hash"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_s3_object" "agentcore" {
  bucket      = data.aws_s3_bucket.agentcore_artifacts.id
  key         = "runtime/v2/agentcore.zip"
  source      = local.agentcore_zip_path
  source_hash = filebase64sha256(local.agentcore_zip_path)
}

resource "aws_s3_object" "tollchat_proxy" {
  bucket      = data.aws_s3_bucket.agentcore_artifacts.id
  key         = "lambda/v2/chat-proxy.zip"
  source      = local.proxy_zip_path
  source_hash = local.proxy_zip_hash
}

data "aws_iam_policy_document" "agentcore_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:runtime/*"]
    }
  }
}

resource "aws_iam_role" "tollchat_runtime" {
  name               = "nova-toll-v2-agentcore-runtime${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume.json
}

data "aws_iam_policy_document" "tollchat_runtime" {
  statement {
    sid       = "ReadArtifact"
    actions   = ["s3:GetObjectVersion"]
    resources = [aws_s3_object.agentcore.arn]
  }
  statement {
    sid       = "ReadOpenAiApiKey"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/nova-toll/openai_api_key"]
  }
  statement {
    sid     = "ConnectRdsIam"
    actions = ["rds-db:connect"]
    resources = [
      "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/${local.database_roles.pricing_caller}",
      "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/${local.database_roles.agent}",
    ]
  }
  statement {
    sid       = "ApplyGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.tollchat.guardrail_arn]
  }
  statement {
    sid     = "WriteRuntimeLogs"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"]
    resources = [
      "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
      "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
    ]
  }
}

resource "aws_iam_role_policy" "tollchat_runtime" {
  name   = "nova-toll-v2-agentcore-runtime"
  role   = aws_iam_role.tollchat_runtime.id
  policy = data.aws_iam_policy_document.tollchat_runtime.json
}

resource "aws_bedrock_guardrail" "tollchat" {
  name                      = "nova-toll-v2-agent${local.suffix}"
  description               = "Input and output safety controls for TollChat"
  blocked_input_messaging   = "I can only help with Northern Virginia toll road estimates."
  blocked_outputs_messaging = "I can only help with Northern Virginia toll road estimates."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "HATE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
  }

  sensitive_information_policy_config {
    regexes_config {
      name           = "authorization_header"
      description    = "Authorization bearer or basic credentials"
      pattern        = "(?i)\\b(?:authorization|x-api-key)\\s*[:=]\\s*(?:bearer|basic)\\s+[A-Za-z0-9._~+/=-]{8,}"
      action         = "BLOCK"
      input_action   = "BLOCK"
      output_action  = "BLOCK"
      input_enabled  = true
      output_enabled = true
    }
    regexes_config {
      name           = "aws_access_key_id"
      description    = "AWS access key identifiers"
      pattern        = "\\b(?:AKIA|ASIA)[A-Z0-9]{16}\\b"
      action         = "BLOCK"
      input_action   = "BLOCK"
      output_action  = "BLOCK"
      input_enabled  = true
      output_enabled = true
    }
    regexes_config {
      name           = "api_key"
      description    = "OpenAI, Anthropic, and GitHub API keys"
      pattern        = "\\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_-]{20,})\\b"
      action         = "BLOCK"
      input_action   = "BLOCK"
      output_action  = "BLOCK"
      input_enabled  = true
      output_enabled = true
    }
    regexes_config {
      name           = "connection_string"
      description    = "Database and cache URI connection strings"
      pattern        = "\\b(?:postgres(?:ql)?|mysql|mongodb(?:\\+srv)?|redis)://[^\\s\"']+"
      action         = "BLOCK"
      input_action   = "BLOCK"
      output_action  = "BLOCK"
      input_enabled  = true
      output_enabled = true
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_bedrock_guardrail_version" "tollchat" {
  guardrail_arn = aws_bedrock_guardrail.tollchat.guardrail_arn
  description   = "Reviewed TollChat input/output safety policy"
  skip_destroy  = true

  lifecycle {
    replace_triggered_by = [aws_bedrock_guardrail.tollchat]
  }
}


resource "aws_bedrockagentcore_agent_runtime" "tollchat" {
  agent_runtime_name = "nova_toll_v2${local.is_production ? "" : "_development"}"
  description        = "TollChat v2 pricing agent"
  role_arn           = aws_iam_role.tollchat_runtime.arn

  agent_runtime_artifact {
    code_configuration {
      entry_point = ["agent/agentcore_entrypoint.py"]
      runtime     = "PYTHON_3_13"
      code {
        s3 {
          bucket     = data.aws_s3_bucket.agentcore_artifacts.id
          prefix     = aws_s3_object.agentcore.key
          version_id = aws_s3_object.agentcore.version_id
        }
      }
    }
  }

  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      security_groups = [aws_security_group.tollchat_runtime.id]
      subnets         = local.private_subnets
    }
  }

  lifecycle_configuration {
    idle_runtime_session_timeout = 900
    max_lifetime                 = 3600
  }

  environment_variables = {
    DB_HOST                    = data.aws_db_instance.main.address
    DB_PORT                    = tostring(data.aws_db_instance.main.port)
    DB_NAME                    = local.database_name
    DB_USER                    = local.database_roles.agent
    DB_CA_BUNDLE_PATH          = "/var/task/rds-ca-bundle.pem"
    TOLLCHAT_GUARDRAIL_ID      = aws_bedrock_guardrail.tollchat.guardrail_id
    TOLLCHAT_GUARDRAIL_VERSION = aws_bedrock_guardrail_version.tollchat.version
  }

  lifecycle {
    precondition {
      condition     = var.agentcore_package_path != ""
      error_message = "AgentCore deployment requires the reviewed v2 runtime package."
    }
  }
}

resource "aws_cloudwatch_log_group" "agentcore_runtime" {
  for_each = toset(["DEFAULT", "preview"])

  name              = "/aws/bedrock-agentcore/runtimes/${aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_id}-${each.value}"
  retention_in_days = local.is_production ? 1 : 1
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "tollchat" {
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_id
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_version
  name                  = "preview"
  description           = "Private TollChat v2 preview"
}

resource "aws_bedrockagentcore_resource_policy" "tollchat" {
  for_each = local.agentcore_resource_policies

  resource_arn = local.agentcore_policy_resources[each.key]
  policy       = each.value
}

resource "aws_iam_role" "tollchat_proxy" {
  name               = "nova-toll-v2-chat-proxy${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "tollchat_proxy_vpc" {
  role       = aws_iam_role.tollchat_proxy.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "tollchat_proxy" {
  statement {
    actions = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [
      aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_arn,
      aws_bedrockagentcore_agent_runtime_endpoint.tollchat.agent_runtime_endpoint_arn,
    ]
  }
  statement {
    actions = ["bedrock-agentcore:StopRuntimeSession"]
    resources = [
      aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_arn,
      aws_bedrockagentcore_agent_runtime_endpoint.tollchat.agent_runtime_endpoint_arn,
    ]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:TransactWriteItems"]
    resources = [aws_dynamodb_table.tollchat_sessions.arn]
  }
}

resource "aws_iam_role_policy" "tollchat_proxy" {
  name   = "nova-toll-v2-chat-proxy${local.suffix}"
  role   = aws_iam_role.tollchat_proxy.id
  policy = data.aws_iam_policy_document.tollchat_proxy.json
}

resource "aws_cloudwatch_log_group" "tollchat_proxy" {
  name              = "/aws/lambda/tollchat-v2-chat-proxy${local.suffix}"
  retention_in_days = local.log_retention_days
}

resource "aws_lambda_function" "tollchat_proxy" {
  function_name                  = "tollchat-v2-chat-proxy${local.suffix}"
  role                           = aws_iam_role.tollchat_proxy.arn
  runtime                        = "nodejs24.x"
  handler                        = "handler.handler"
  timeout                        = 50
  memory_size                    = 256
  publish                        = true
  reserved_concurrent_executions = 5

  s3_bucket         = data.aws_s3_bucket.agentcore_artifacts.id
  s3_key            = aws_s3_object.tollchat_proxy.key
  s3_object_version = aws_s3_object.tollchat_proxy.version_id
  source_code_hash  = local.proxy_zip_hash

  vpc_config {
    subnet_ids         = local.private_subnets
    security_group_ids = [aws_security_group.tollchat_proxy.id]
  }

  environment {
    variables = {
      AGENTCORE_RUNTIME_ARN = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_arn
      AGENTCORE_VPCE_URL    = "https://${data.aws_vpc_endpoint.agentcore.dns_entry[0].dns_name}"
      SESSION_TABLE_NAME    = aws_dynamodb_table.tollchat_sessions.name
    }
  }

  lifecycle {
    ignore_changes = [reserved_concurrent_executions]

    precondition {
      condition     = var.chat_proxy_package_path != ""
      error_message = "Chat proxy deployment requires the reviewed v2 proxy package."
    }
  }

  depends_on = [
    aws_bedrockagentcore_resource_policy.tollchat,
    aws_cloudwatch_log_group.tollchat_proxy,
    aws_iam_role_policy.tollchat_proxy,
    aws_iam_role_policy_attachment.tollchat_proxy_vpc,
  ]
}

resource "aws_lambda_alias" "tollchat_live" {
  name             = "live"
  description      = "Reviewed public TollChat release"
  function_name    = aws_lambda_function.tollchat_proxy.function_name
  function_version = aws_lambda_function.tollchat_proxy.version
}

resource "aws_lambda_provisioned_concurrency_config" "tollchat" {
  function_name                     = aws_lambda_alias.tollchat_live.function_name
  qualifier                         = aws_lambda_alias.tollchat_live.name
  provisioned_concurrent_executions = local.is_production ? 1 : 0
}

resource "aws_api_gateway_rest_api" "tollchat" {
  name = "nova-toll-v2-preview${local.suffix}"

  endpoint_configuration {
    types            = ["PRIVATE"]
    vpc_endpoint_ids = [data.aws_vpc_endpoint.tollchat_api.id]
  }

}

resource "aws_api_gateway_rest_api_policy" "tollchat" {
  rest_api_id = aws_api_gateway_rest_api.tollchat.id
  policy      = local.private_api_policy
}

resource "aws_api_gateway_resource" "tollchat_proxy" {
  rest_api_id = aws_api_gateway_rest_api.tollchat.id
  parent_id   = aws_api_gateway_rest_api.tollchat.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "tollchat_root" {
  rest_api_id   = aws_api_gateway_rest_api.tollchat.id
  resource_id   = aws_api_gateway_rest_api.tollchat.root_resource_id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_method" "tollchat_proxy" {
  rest_api_id   = aws_api_gateway_rest_api.tollchat.id
  resource_id   = aws_api_gateway_resource.tollchat_proxy.id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "tollchat_root" {
  rest_api_id             = aws_api_gateway_rest_api.tollchat.id
  resource_id             = aws_api_gateway_rest_api.tollchat.root_resource_id
  http_method             = aws_api_gateway_method.tollchat_root.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.tollchat_proxy.response_streaming_invoke_arn
  response_transfer_mode  = "STREAM"
  timeout_milliseconds    = 55000
}

resource "aws_api_gateway_integration" "tollchat_proxy" {
  rest_api_id             = aws_api_gateway_rest_api.tollchat.id
  resource_id             = aws_api_gateway_resource.tollchat_proxy.id
  http_method             = aws_api_gateway_method.tollchat_proxy.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.tollchat_proxy.response_streaming_invoke_arn
  response_transfer_mode  = "STREAM"
  timeout_milliseconds    = 55000
}

resource "aws_api_gateway_deployment" "tollchat" {
  rest_api_id = aws_api_gateway_rest_api.tollchat.id
  triggers = {
    redeployment = sha1(jsonencode({
      policy     = local.private_api_policy
      proxy_path = aws_api_gateway_resource.tollchat_proxy.path_part
      root_uri   = aws_api_gateway_integration.tollchat_root.uri
      proxy_uri  = aws_api_gateway_integration.tollchat_proxy.uri
    }))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [aws_api_gateway_rest_api_policy.tollchat]
}

resource "aws_api_gateway_stage" "tollchat" {
  rest_api_id   = aws_api_gateway_rest_api.tollchat.id
  deployment_id = aws_api_gateway_deployment.tollchat.id
  stage_name    = "preview"
}

resource "aws_api_gateway_method_settings" "tollchat" {
  rest_api_id = aws_api_gateway_rest_api.tollchat.id
  stage_name  = aws_api_gateway_stage.tollchat.stage_name
  method_path = "*/*"
  settings {
    throttling_burst_limit = 12
    throttling_rate_limit  = 2
  }
}

resource "aws_lambda_permission" "tollchat_api" {
  statement_id  = "AllowPrivateApiGatewayV2"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tollchat_proxy.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.tollchat.execution_arn}/*/*"
}

resource "aws_cloudwatch_log_metric_filter" "proxy_failure" {
  name           = "V2ProxyFailure"
  log_group_name = aws_cloudwatch_log_group.tollchat_proxy.name
  pattern        = "PROXY_FAILURE"

  metric_transformation {
    namespace = "NovaToll"
    name      = "V2ProxyFailure"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "tollchat_proxy_errors" {
  alarm_name          = "tollchat-v2-chat-proxy-errors${local.suffix}"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.tollchat_proxy.function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "tollchat_proxy_failures" {
  alarm_name          = "tollchat-v2-chat-proxy-failures${local.suffix}"
  namespace           = "NovaToll"
  metric_name         = "V2ProxyFailure"
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "tollchat_proxy_latency" {
  alarm_name          = "tollchat-v2-chat-proxy-latency${local.suffix}"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = aws_lambda_function.tollchat_proxy.function_name }
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 1
  extended_statistic  = "p99"
  threshold           = 45000
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "tollchat_sessions" {
  alarm_name          = "tollchat-v2-agentcore-active-sessions${local.suffix}"
  namespace           = "AWS/Bedrock-AgentCore"
  metric_name         = "ActiveSessionCount"
  dimensions          = { Service = "AgentCore.Runtime" }
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  statistic           = "Maximum"
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

output "private_preview" {
  description = "API-specific private preview endpoint."
  value = {
    api_id = aws_api_gateway_rest_api.tollchat.id
    stage  = aws_api_gateway_stage.tollchat.stage_name
    origin = "https://${aws_api_gateway_rest_api.tollchat.id}-${data.aws_vpc_endpoint.tollchat_api.id}.execute-api.${data.aws_region.current.region}.amazonaws.com"
    url    = "https://${aws_api_gateway_rest_api.tollchat.id}-${data.aws_vpc_endpoint.tollchat_api.id}.execute-api.${data.aws_region.current.region}.amazonaws.com/${aws_api_gateway_stage.tollchat.stage_name}"
  }
}

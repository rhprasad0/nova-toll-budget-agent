locals {
  agentcore_zip_path = var.agentcore_package_path != "" ? var.agentcore_package_path : data.archive_file.placeholder.output_path
  proxy_zip_path     = var.chat_proxy_package_path != "" ? var.chat_proxy_package_path : data.archive_file.placeholder.output_path
  proxy_zip_hash     = var.chat_proxy_package_path != "" ? filebase64sha256(var.chat_proxy_package_path) : data.archive_file.placeholder.output_base64sha256
  private_subnets    = [aws_subnet.tollchat_private_a.id, aws_subnet.tollchat_private_c.id]
  private_subnets_by_az = {
    us_east_1a = aws_subnet.tollchat_private_a.id
    us_east_1c = aws_subnet.tollchat_private_c.id
  }
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
          Condition = { StringEquals = { "aws:SourceVpce" = aws_vpc_endpoint.agentcore.id } }
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
          Condition = { StringNotEquals = { "aws:SourceVpce" = aws_vpc_endpoint.agentcore.id } }
        },
      ]
    })
  }
}

# Two small private subnets are enough for the internal ALB, proxy, and runtime.
# One NAT keeps the preview cheap; add a second only when public availability warrants it.
resource "aws_subnet" "tollchat_private_a" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "us-east-1a"
  cidr_block        = "172.31.224.0/24"

  tags = { Name = "nova-toll-private-a" }
}

resource "aws_subnet" "tollchat_private_c" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "us-east-1c"
  cidr_block        = "172.31.225.0/24"

  tags = { Name = "nova-toll-private-c" }
}

resource "aws_eip" "tollchat_nat" {
  domain = "vpc"
}

resource "aws_nat_gateway" "tollchat" {
  allocation_id = aws_eip.tollchat_nat.id
  subnet_id     = data.aws_subnet.tailscale_router.id

  tags = { Name = "nova-toll-preview" }
}

resource "aws_route_table" "tollchat_private" {
  vpc_id = data.aws_vpc.default.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.tollchat.id
  }
}

resource "aws_route_table_association" "tollchat_private" {
  for_each = local.private_subnets_by_az

  subnet_id      = each.value
  route_table_id = aws_route_table.tollchat_private.id
}

resource "aws_security_group" "tollchat_alb" {
  name        = "nova-toll-preview-alb"
  description = "Internal TollChat preview ALB"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "tollchat_alb_from_tailscale" {
  security_group_id            = aws_security_group.tollchat_alb.id
  referenced_security_group_id = aws_security_group.tailscale_router.id
  description                  = "Owner access through the Tailscale subnet router"
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "tollchat_alb_from_cloudfront" {
  count = var.enable_public_chat ? 1 : 0

  security_group_id = aws_security_group.tollchat_alb.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  description       = "CloudFront origin-facing network"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "tollchat_proxy" {
  name        = "nova-toll-chat-proxy"
  description = "TollChat proxy Lambda ENIs"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_security_group" "agentcore_endpoint" {
  name        = "nova-toll-agentcore-endpoint"
  description = "Private AgentCore data-plane endpoint"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "agentcore_endpoint_from_proxy" {
  security_group_id            = aws_security_group.agentcore_endpoint.id
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

resource "aws_security_group" "tollchat_runtime" {
  name        = "nova-toll-agentcore-runtime"
  description = "AgentCore runtime egress"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_egress_rule" "runtime_to_rds" {
  security_group_id            = aws_security_group.tollchat_runtime.id
  referenced_security_group_id = aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_runtime" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.tollchat_runtime.id
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

resource "aws_vpc_endpoint" "agentcore" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${data.aws_region.current.region}.bedrock-agentcore"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnets
  security_group_ids  = [aws_security_group.agentcore_endpoint.id]
  private_dns_enabled = true
}

resource "aws_s3_bucket" "agentcore_artifacts" {
  bucket = "nova-toll-agentcore-920534282028"
}

resource "aws_s3_bucket_public_access_block" "agentcore_artifacts" {
  bucket                  = aws_s3_bucket.agentcore_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_versioning" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id

  rule {
    id     = "trim-old-runtime-artifacts"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days           = 30
      newer_noncurrent_versions = 5
    }
  }

  depends_on = [aws_s3_bucket_versioning.agentcore_artifacts]
}

data "aws_iam_policy_document" "agentcore_artifacts" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.agentcore_artifacts.arn, "${aws_s3_bucket.agentcore_artifacts.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "agentcore_artifacts" {
  bucket = aws_s3_bucket.agentcore_artifacts.id
  policy = data.aws_iam_policy_document.agentcore_artifacts.json
}

resource "aws_s3_object" "agentcore" {
  bucket      = aws_s3_bucket.agentcore_artifacts.id
  key         = "runtime/tollchat.zip"
  source      = local.agentcore_zip_path
  source_hash = filebase64sha256(local.agentcore_zip_path)

  depends_on = [aws_s3_bucket_versioning.agentcore_artifacts]
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
  name               = "nova-toll-agentcore-runtime"
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
    sid       = "ConnectRdsIam"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.main.resource_id}/pricing_reader"]
  }
  statement {
    sid       = "ApplyGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.tollchat.guardrail_arn]
  }
  statement {
    sid     = "CreateRuntimeLogs"
    actions = ["logs:CreateLogGroup", "logs:DescribeLogStreams"]
    resources = [
      "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
    ]
  }
  statement {
    sid       = "DescribeRuntimeLogs"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:*"]
  }
  statement {
    sid     = "WriteRuntimeLogs"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
    ]
  }
  statement {
    sid     = "WriteSanitizedTraceRecords"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.tollchat_trace_records.arn}:*",
    ]
  }
  statement {
    sid       = "WriteRuntimeTraces"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
  statement {
    sid       = "WriteRuntimeMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }
}

resource "aws_iam_role_policy" "tollchat_runtime" {
  name   = "nova-toll-agentcore-runtime"
  role   = aws_iam_role.tollchat_runtime.id
  policy = data.aws_iam_policy_document.tollchat_runtime.json
}

resource "aws_bedrock_guardrail" "tollchat" {
  name                      = "nova-toll-agent"
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
      pattern        = "\\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\\b"
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
}

resource "aws_bedrock_guardrail_version" "tollchat" {
  guardrail_arn = aws_bedrock_guardrail.tollchat.guardrail_arn
  description   = "Terraform-managed TollChat guardrail version"
}

resource "aws_bedrockagentcore_agent_runtime" "tollchat" {
  agent_runtime_name = "nova_toll"
  description        = "TollChat pricing agent"
  role_arn           = aws_iam_role.tollchat_runtime.arn

  agent_runtime_artifact {
    code_configuration {
      entry_point = ["opentelemetry-instrument", "agent/agentcore_entrypoint.py"]
      runtime     = "PYTHON_3_13"
      code {
        s3 {
          bucket     = aws_s3_bucket.agentcore_artifacts.id
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
    DB_HOST                               = aws_db_instance.main.address
    DB_PORT                               = tostring(aws_db_instance.main.port)
    DB_NAME                               = aws_db_instance.main.db_name
    DB_USER                               = "pricing_reader"
    DB_CA_BUNDLE_PATH                     = "/var/task/rds-ca-bundle.pem"
    TOLLCHAT_GUARDRAIL_ID                 = aws_bedrock_guardrail.tollchat.guardrail_id
    TOLLCHAT_GUARDRAIL_VERSION            = aws_bedrock_guardrail_version.tollchat.version
    TOLLCHAT_TRACE_LOG_GROUP              = aws_cloudwatch_log_group.tollchat_trace_records.name
    AGENT_OBSERVABILITY_ENABLED           = "true"
    OTEL_PYTHON_DISTRO                    = "aws_distro"
    OTEL_PYTHON_CONFIGURATOR              = "aws_configurator"
    OTEL_EXPORTER_OTLP_PROTOCOL           = "http/protobuf"
    OTEL_PYTHON_DISABLED_INSTRUMENTATIONS = "botocore"
    OTEL_SEMCONV_STABILITY_OPT_IN         = "gen_ai_latest_experimental,gen_ai_unredacted_attributes="
    OTEL_TRACES_SAMPLER                   = "always_on"
    OTEL_AWS_APPLICATION_SIGNALS_ENABLED  = "false"
    UNIFIED_TRACES_DESTINATION_ENABLED    = "false"
  }

  lifecycle {
    precondition {
      condition     = var.agentcore_package_path != ""
      error_message = "AgentCore deployment requires the real ARM64 runtime package."
    }
  }
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "tollchat" {
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_id
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_version
  name                  = "preview"
  description           = "Tailscale-gated TollChat preview"
}

# Apply the explicit network deny to both authorization layers. Identity-based
# permissions cannot bypass this restriction.
resource "aws_bedrockagentcore_resource_policy" "tollchat" {
  for_each = local.agentcore_resource_policies

  resource_arn = local.agentcore_policy_resources[each.key]
  policy       = each.value
}

resource "aws_iam_role" "tollchat_proxy" {
  name               = "nova-toll-chat-proxy"
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
}

resource "aws_iam_role_policy" "tollchat_proxy" {
  name   = "nova-toll-chat-proxy"
  role   = aws_iam_role.tollchat_proxy.id
  policy = data.aws_iam_policy_document.tollchat_proxy.json
}

resource "aws_cloudwatch_log_group" "tollchat_proxy" {
  name              = "/aws/lambda/tollchat-chat-proxy"
  retention_in_days = 30
}

resource "aws_lambda_function" "tollchat_proxy" {
  function_name                  = "tollchat-chat-proxy"
  role                           = aws_iam_role.tollchat_proxy.arn
  runtime                        = "python3.13"
  handler                        = "handler.lambda_handler"
  timeout                        = 50
  memory_size                    = 256
  reserved_concurrent_executions = 5

  filename         = local.proxy_zip_path
  source_code_hash = local.proxy_zip_hash

  vpc_config {
    subnet_ids         = local.private_subnets
    security_group_ids = [aws_security_group.tollchat_proxy.id]
  }

  environment {
    variables = {
      AGENTCORE_RUNTIME_ARN = aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_arn
      AGENTCORE_VPCE_URL    = "https://${aws_vpc_endpoint.agentcore.dns_entry[0].dns_name}"
    }
  }

  lifecycle {
    ignore_changes = [reserved_concurrent_executions]
  }

  depends_on = [aws_cloudwatch_log_group.tollchat_proxy, aws_iam_role_policy_attachment.tollchat_proxy_vpc, aws_bedrockagentcore_resource_policy.tollchat]
}

resource "aws_lb" "tollchat" {
  name               = "nova-toll-preview"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.tollchat_alb.id]
  subnets            = local.private_subnets
  idle_timeout       = 55
}

resource "aws_lb_target_group" "tollchat" {
  name        = "nova-toll-chat-proxy"
  target_type = "lambda"

  health_check {
    enabled  = true
    interval = 35
    path     = "/api/config"
    timeout  = 30
  }
}

resource "aws_lambda_permission" "tollchat_alb" {
  statement_id  = "AllowInternalAlb"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tollchat_proxy.function_name
  principal     = "elasticloadbalancing.amazonaws.com"
  source_arn    = aws_lb_target_group.tollchat.arn
}

resource "aws_lb_target_group_attachment" "tollchat" {
  target_group_arn = aws_lb_target_group.tollchat.arn
  target_id        = aws_lambda_function.tollchat_proxy.arn

  depends_on = [aws_lambda_permission.tollchat_alb]
}

resource "aws_lb_listener" "tollchat" {
  load_balancer_arn = aws_lb.tollchat.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = aws_acm_certificate_validation.site.certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type = "redirect"
    redirect {
      host        = "tollchat.ai"
      path        = "/"
      query       = "preview=1"
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_302"
    }
  }
}

resource "aws_lb_listener_rule" "tollchat_api" {
  listener_arn = aws_lb_listener.tollchat.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tollchat.arn
  }

  condition {
    path_pattern { values = ["/api/*"] }
  }
}

resource "cloudflare_dns_record" "preview" {
  zone_id = data.cloudflare_zone.tollchat.id
  name    = "preview.tollchat.ai"
  type    = "CNAME"
  content = aws_lb.tollchat.dns_name
  ttl     = 60
  proxied = false
}

output "tailscale_preview_url" {
  description = "Private preview URL; resolvable publicly but reachable only through the tailnet route."
  value       = "https://preview.tollchat.ai/api/config"
}

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_provider_and_agentcore_resources_use_supported_native_shapes():
    versions = (ROOT / "infra/versions.tf").read_text()
    agentcore = (ROOT / "infra/agentcore.tf").read_text()

    assert 'version = "~> 6.47"' in versions
    assert 'resource "aws_bedrockagentcore_agent_runtime" "tollchat"' in agentcore
    assert (
        'resource "aws_bedrockagentcore_agent_runtime_endpoint" "tollchat"' in agentcore
    )
    assert 'network_mode = "VPC"' in agentcore
    assert "idle_runtime_session_timeout = 900" in agentcore
    assert "max_lifetime" in agentcore and "= 3600" in agentcore
    assert (
        '"com.amazonaws.${data.aws_region.current.region}.bedrock-agentcore"'
        in agentcore
    )
    artifact = agentcore.split('resource "aws_s3_object" "agentcore"', maxsplit=1)[
        1
    ].split('data "aws_iam_policy_document" "agentcore_assume"', maxsplit=1)[0]
    assert "source_hash = filebase64sha256(local.agentcore_zip_path)" in artifact
    assert "etag" not in artifact


def test_runtime_can_read_the_pinned_agentcore_artifact_version():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    artifact_access = agentcore.split('sid       = "ReadArtifact"', maxsplit=1)[
        1
    ].split('sid       = "ReadOpenAiApiKey"', maxsplit=1)[0]

    assert 'actions   = ["s3:GetObjectVersion"]' in artifact_access
    assert '"s3:GetObject"' not in artifact_access


def test_preview_edge_stays_private_and_closes_direct_runtime_access():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    tailnet_policy = (ROOT / "policy.hujson").read_text()

    assert "internal           = true" in agentcore
    assert 'target_type = "lambda"' in agentcore
    assert "aws:SourceVpce" in agentcore
    assert "DenyOutsidePrivateEndpoint" in agentcore
    assert 'resource "aws_bedrockagentcore_resource_policy" "tollchat"' in agentcore
    assert "agent_runtime_endpoint_arn" in agentcore
    assert "aws_security_group.tailscale_router.id" in agentcore
    assert '"src":    "rhprasad0@github"' in tailnet_policy
    assert '"deny":   ["8.8.8.8:443", "tollchat-preview-test:443"]' in tailnet_policy


def test_preview_network_uses_stable_route_association_keys():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    tailscale = (ROOT / "infra/tailscale.tf").read_text()

    assert "private_subnets_by_az = {" in agentcore
    assert "for_each = local.private_subnets_by_az" in agentcore
    assert "for_each = toset(local.private_subnets)" not in agentcore
    assert 'name   = "default-for-az"' in tailscale
    assert 'values = ["true"]' in tailscale

    target_group = agentcore.split(
        'resource "aws_lb_target_group" "tollchat"', maxsplit=1
    )[1].split('resource "aws_lambda_permission"', maxsplit=1)[0]
    assert "interval = 35" in target_group
    assert "timeout  = 30" in target_group


def test_acm_reuses_existing_dns_validation_records_during_replacement():
    dns = (ROOT / "infra/dns.tf").read_text()
    validation = dns.split(
        'resource "cloudflare_dns_record" "site_cert_validation"', maxsplit=1
    )[1].split('resource "aws_acm_certificate_validation"', maxsplit=1)[0]

    assert "ignore_changes = [name, type, content]" in validation


def test_runtime_and_proxy_roles_are_separate_and_ssm_remains_authoritative():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()

    assert 'resource "aws_iam_role" "tollchat_runtime"' in agentcore
    assert 'resource "aws_iam_role" "tollchat_proxy"' in agentcore
    assert "parameter/nova-toll/openai_api_key" in agentcore
    assert '"rds-db:connect"' in agentcore
    assert '"bedrock-agentcore:InvokeAgentRuntime"' in agentcore
    assert "create-api-key-credential-provider" not in agentcore
    assert "delete-parameter" not in agentcore


def test_reset_authorization_covers_runtime_endpoint_and_private_path():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    resource_policies = agentcore.split("agentcore_resource_policies = {", maxsplit=1)[
        1
    ].split("\n}\n\n# Two small private", maxsplit=1)[0]
    proxy_policy = agentcore.split(
        'data "aws_iam_policy_document" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "tollchat_proxy"', maxsplit=1)[0]

    assert resource_policies.count('"bedrock-agentcore:StopRuntimeSession"') == 2
    assert resource_policies.count("aws:SourceVpce") == 2
    assert proxy_policy.count("agent_runtime_arn") == 2
    assert proxy_policy.count("agent_runtime_endpoint_arn") == 2


def test_proxy_kill_switch_and_request_deadlines_converge_safely():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    site = (ROOT / "infra/site.tf").read_text()
    runbook = (ROOT / "docs/runbooks/kill-switch.md").read_text()
    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_lb" "tollchat"', maxsplit=1)[0]
    load_balancer = agentcore.split('resource "aws_lb" "tollchat"', maxsplit=1)[
        1
    ].split('resource "aws_lb_target_group" "tollchat"', maxsplit=1)[0]

    assert "timeout                        = 50" in proxy
    assert "ignore_changes = [reserved_concurrent_executions]" in proxy
    assert "idle_timeout       = 55" in load_balancer
    assert "origin_read_timeout = 60" in site
    assert "Terraform intentionally ignores concurrency drift" in runbook


def test_guardrail_enables_every_content_filter_category():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    guardrail = agentcore.split(
        'resource "aws_bedrock_guardrail" "tollchat"', maxsplit=1
    )[1].split('resource "aws_bedrock_guardrail_version"', maxsplit=1)[0]
    categories = re.findall(r'type\s+= "([A-Z_]+)"', guardrail)

    assert len(categories) == 6
    assert set(categories) == {
        "PROMPT_ATTACK",
        "HATE",
        "VIOLENCE",
        "SEXUAL",
        "INSULTS",
        "MISCONDUCT",
    }


def test_guardrail_blocks_common_credentials_before_they_reach_tracing():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    guardrail = agentcore.split(
        'resource "aws_bedrock_guardrail" "tollchat"', maxsplit=1
    )[1].split('resource "aws_bedrock_guardrail_version"', maxsplit=1)[0]

    for name in (
        "authorization_header",
        "aws_access_key_id",
        "api_key",
        "connection_string",
    ):
        assert f'name           = "{name}"' in guardrail
    assert guardrail.count('input_action   = "BLOCK"') >= 4
    assert guardrail.count('output_action  = "BLOCK"') >= 4


def test_agentcore_split_telemetry_is_fully_declared_and_governed():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    kms = (ROOT / "infra/kms.tf").read_text()
    observability = (ROOT / "infra/observability.tf").read_text()

    assert re.search(r'UNIFIED_TRACES_DESTINATION_ENABLED\s+= "false"', agentcore)
    assert (
        'entry_point = ["opentelemetry-instrument", "agent/agentcore_entrypoint.py"]'
        in agentcore
    )
    assert re.search(r'OTEL_TRACES_SAMPLER\s+= "always_on"', agentcore)
    assert re.search(r'OTEL_PYTHON_DISABLED_INSTRUMENTATIONS\s+= "botocore"', agentcore)
    assert re.search(
        r'OTEL_SEMCONV_STABILITY_OPT_IN\s+= "gen_ai_latest_experimental,gen_ai_unredacted_attributes="',
        agentcore,
    )
    assert (
        'resource "aws_xray_trace_segment_destination" "transaction_search"'
        in observability
    )
    assert 'destination = "CloudWatchLogs"' in observability
    assert (
        'resource "aws_xray_indexing_rule" "transaction_search_default"'
        in observability
    )
    assert "desired_sampling_percentage = 1.0" in observability
    assert "TOLLCHAT_TRACE_LOG_GROUP" in agentcore
    assert (
        'resource "aws_cloudwatch_log_group" "tollchat_trace_records"' in observability
    )
    assert 'name              = "/aws/nova-toll/agentcore/traces"' in observability
    assert (
        "removed {\n  from = aws_cloudwatch_log_group.agentcore_spans" in observability
    )
    assert 'resource "terraform_data" "agentcore_spans_log_group"' in observability
    assert "configure_agentcore_spans_log_group.sh" in observability
    assert 'agentcore_spans_log_group_name = "aws/spans"' in observability
    assert (
        "depends_on = [aws_cloudwatch_log_resource_policy.transaction_search]"
        in observability
    )
    assert "retention_in_days = 30" in observability
    assert 'retention   = "30"' in observability
    assert "kms_key_id        = aws_kms_key.agentcore_telemetry.arn" in observability
    assert "kms_key_arn = aws_kms_key.agentcore_telemetry.arn" in observability
    assert (
        'resource "aws_cloudwatch_log_delivery_source" "tollchat_runtime_traces"'
        in observability
    )
    assert 'log_type     = "TRACES"' in observability
    assert 'delivery_destination_type = "XRAY"' in observability
    assert 'log_type     = "APPLICATION_LOGS"' not in observability
    assert (
        'resource "aws_cloudwatch_log_resource_policy" "transaction_search"'
        in observability
    )
    assert (
        'resource "aws_cloudwatch_log_data_protection_policy" "agentcore_telemetry"'
        in observability
    )
    assert 'resource "aws_kms_key" "agentcore_telemetry"' in kms
    assert 'resource "aws_kms_alias" "agentcore_telemetry"' in kms
    runtime_policy = agentcore.split(
        'data "aws_iam_policy_document" "tollchat_runtime"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "tollchat_runtime"', maxsplit=1)[0]
    assert "WriteSanitizedTraceRecords" in runtime_policy
    assert "aws_cloudwatch_log_group.tollchat_trace_records.arn}:*" in runtime_policy


def test_trace_reviewer_is_read_only_for_governed_telemetry():
    observability = (ROOT / "infra/observability.tf").read_text()

    reviewer = observability.split(
        'data "aws_iam_policy_document" "tollchat_trace_reviewer"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "tollchat_trace_reviewer"', maxsplit=1)[
        0
    ]
    assert 'resource "aws_iam_role" "tollchat_trace_reviewer"' in observability
    assert "logs:GetLogEvents" in reviewer
    assert "logs:Unmask" in reviewer
    assert "logs:FilterLogEvents" in reviewer
    assert "logs:StartQuery" in reviewer
    assert "logs:GetQueryResults" in reviewer
    assert "xray:StartTraceRetrieval" in reviewer
    assert "xray:ListRetrievedTraces" in reviewer
    assert "xray:GetRetrievedTracesGraph" in reviewer
    assert "kms:Decrypt" not in reviewer
    assert "logs:PutLogEvents" not in reviewer
    assert "logs:DeleteLogGroup" not in reviewer


def test_public_chat_is_an_explicit_disabled_by_default_gate():
    variables = (ROOT / "infra/variables.tf").read_text()
    site = (ROOT / "infra/site.tf").read_text()
    dns = (ROOT / "infra/dns.tf").read_text()

    assert 'variable "enable_public_chat"' in variables
    assert "default     = false" in variables
    assert 'resource "aws_cloudfront_vpc_origin" "tollchat"' in site
    assert 'path_pattern           = "/api/*"' in site
    assert 'resource "aws_wafv2_web_acl" "tollchat"' in site
    assert 'domain_name = "preview.tollchat.ai"' in site
    assert '"preview.tollchat.ai"' in dns

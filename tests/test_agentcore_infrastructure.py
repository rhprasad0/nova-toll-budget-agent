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

    assert 'types            = ["PRIVATE"]' in agentcore
    assert 'response_transfer_mode  = "STREAM"' in agentcore
    assert "response_streaming_invoke_arn" in agentcore
    assert agentcore.count("aws:SourceVpce") >= 4
    assert "DenyOutsidePrivateEndpoint" in agentcore
    assert 'resource "aws_bedrockagentcore_resource_policy" "tollchat"' in agentcore
    assert (
        'resource "aws_api_gateway_domain_name_access_association" "tollchat"'
        in agentcore
    )
    assert "agent_runtime_endpoint_arn" in agentcore
    assert (
        'service_name        = "com.amazonaws.${data.aws_region.current.region}.execute-api"'
        in agentcore
    )
    assert (
        'service_name        = "com.amazonaws.${data.aws_region.current.region}.bedrock-agentcore"'
        in agentcore
    )
    assert 'runtime                        = "nodejs24.x"' in agentcore
    assert 'handler                        = "handler.handler"' in agentcore
    assert (
        'cidr_ipv4         = "${aws_instance.tailscale_router.private_ip}/32"'
        in agentcore
    )
    assert '"src":    "rhprasad0@github"' in tailnet_policy
    assert '"deny":   ["8.8.8.8:443", "tollchat-preview-test:443"]' in tailnet_policy
    assert 'resource "aws_lb" "tollchat"' not in agentcore
    assert 'resource "aws_lb_target_group" "tollchat"' not in agentcore


def test_preview_throttle_covers_a_cold_page_asset_fanout():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    handler = (ROOT / "lambdas/chat_proxy/handler.mjs").read_text()
    settings = agentcore.split(
        'resource "aws_api_gateway_method_settings" "tollchat"', maxsplit=1
    )[1]
    burst_match = re.search(r"throttling_burst_limit\s*=\s*(\d+)", settings)
    assert burst_match
    burst = int(burst_match.group(1))
    assets = re.findall(r'^\s+"/assets/[^\"]+": readFileSync', handler, re.MULTILINE)

    assert burst >= len(assets) + 2  # HTML and preview.mjs also use the private API.


def test_api_deployment_hashes_the_complete_stage_snapshot():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    deployment = agentcore.split('resource "aws_api_gateway_deployment" "tollchat"')[
        1
    ].split('resource "aws_api_gateway_stage" "tollchat"')[0]

    for snapshot_input in (
        "local.private_api_policy",
        "aws_api_gateway_resource.tollchat_proxy.path_part",
        "aws_api_gateway_method.tollchat_root.authorization",
        "aws_api_gateway_method.tollchat_proxy.authorization",
        "aws_api_gateway_integration.tollchat_root.uri",
        "aws_api_gateway_integration.tollchat_root.response_transfer_mode",
        "aws_api_gateway_integration.tollchat_root.timeout_milliseconds",
        "aws_api_gateway_integration.tollchat_proxy.uri",
        "aws_api_gateway_integration.tollchat_proxy.response_transfer_mode",
        "aws_api_gateway_integration.tollchat_proxy.timeout_milliseconds",
    ):
        assert snapshot_input in deployment
    assert "aws_api_gateway_rest_api.tollchat.policy" not in deployment
    assert "aws_api_gateway_integration.tollchat_root.id" not in deployment
    assert "aws_api_gateway_integration.tollchat_proxy.id" not in deployment


def test_preview_network_uses_stable_route_association_keys():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    tailscale = (ROOT / "infra/tailscale.tf").read_text()

    assert "private_subnets_by_az = {" in agentcore
    assert "for_each = local.private_subnets_by_az" in agentcore
    assert "for_each = toset(local.private_subnets)" not in agentcore
    assert 'name   = "default-for-az"' in tailscale
    assert 'values = ["true"]' in tailscale

    assert 'resource "aws_vpc_endpoint" "tollchat_api"' in agentcore
    assert "private_dns_enabled = false" in agentcore


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
    )[1].split('resource "aws_api_gateway_rest_api" "tollchat"', maxsplit=1)[0]

    assert "timeout                        = 50" in proxy
    assert "ignore_changes = [reserved_concurrent_executions]" in proxy
    assert "timeout_milliseconds    = 55000" in agentcore
    assert "aws_cloudfront_vpc_origin" not in site
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


def test_guardrail_policy_changes_create_candidates_without_promoting_them():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    version = agentcore.split(
        'resource "aws_bedrock_guardrail_version" "tollchat"', maxsplit=1
    )[1].split('resource "aws_bedrockagentcore_agent_runtime" "tollchat"', maxsplit=1)[
        0
    ]
    runtime = agentcore.split(
        'resource "aws_bedrockagentcore_agent_runtime" "tollchat"', maxsplit=1
    )[1].split('resource "aws_bedrockagentcore_agent_runtime_endpoint"', maxsplit=1)[0]
    policy = agentcore.split('sid       = "ApplyGuardrail"', maxsplit=1)[1].split(
        'sid     = "CreateRuntimeLogs"', maxsplit=1
    )[0]

    assert 'description   = "Reviewed TollChat input/output safety policy"' in version
    assert "skip_destroy  = true" in version
    assert "replace_triggered_by = [aws_bedrock_guardrail.tollchat]" in version
    assert "prevent_destroy = true" in agentcore
    assert 'approved_guardrail_version = "2"' in agentcore
    assert (
        "TOLLCHAT_GUARDRAIL_VERSION            = local.approved_guardrail_version"
        in runtime
    )
    assert (
        "TOLLCHAT_GUARDRAIL_VERSION            = aws_bedrock_guardrail_version.tollchat.version"
        not in runtime
    )
    assert (
        "tonumber(aws_bedrock_guardrail_version.tollchat.version) >= tonumber(local.approved_guardrail_version)"
        in runtime
    )
    assert 'actions   = ["bedrock:ApplyGuardrail"]' in policy
    assert "resources = [aws_bedrock_guardrail.tollchat.guardrail_arn]" in policy


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


def test_public_chat_edge_is_explicitly_promoted_and_uses_cloudfront_oac():
    variables = (ROOT / "infra/variables.tf").read_text()
    site = (ROOT / "infra/site.tf").read_text()
    workflow = (ROOT / ".github/workflows/terraform.yml").read_text()

    public_switch = variables.split('variable "enable_public_chat"', maxsplit=1)[1]
    assert "type        = bool" in public_switch
    assert "default     = false" in public_switch
    assert "-var enable_public_chat=true" in workflow
    assert "source       = local.site_index_path" in site
    assert 'key           = "preview.mjs"' in site
    assert "source        = local.site_script_path" in site
    assert 'cache_control = "no-cache"' in site
    assert 'resource "aws_lambda_function_url" "public_chat"' in site
    assert 'authorization_type = "AWS_IAM"' in site
    assert re.search(r'invoke_mode\s+= "RESPONSE_STREAM"', site)
    assert 'origin_access_control_origin_type = "lambda"' in site
    assert 'resource "aws_cloudfront_function" "public_chat_routes"' in site
    assert 'code    = file("${path.module}/../site/public-api-gate.js")' in site
    assert 'event_type   = "viewer-request"' in site
    assert site.count("var.enable_public_chat ? 1 : 0") >= 5
    assert site.count("var.enable_public_chat ? [1] : []") >= 2
    assert re.search(r'path_pattern\s+= "/api/\*"', site)
    assert "source_arn             = aws_cloudfront_distribution.site.arn" in site
    assert 'function_url_auth_type = "AWS_IAM"' in site
    assert "invoked_via_function_url = true" in site


def test_public_site_publishes_privacy_and_terms():
    site = (ROOT / "infra/site.tf").read_text()
    page = (ROOT / "site/preview.html").read_text()

    assert 'key           = "privacy.txt"' in site
    assert 'key           = "terms.txt"' in site
    assert 'href="/privacy.txt"' in page
    assert 'href="/terms.txt"' in page


def test_public_api_behavior_is_uncached_allowlisted_and_single_attempt():
    site = (ROOT / "infra/site.tf").read_text()
    gate = (ROOT / "site/public-api-gate.js").read_text()
    behavior = site.split('path_pattern             = "/api/*"', maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]

    assert (
        'cache_policy_id          = "413f1603-3b9c-4ea9-bf45-8c6a2e83ef45"' in behavior
    )
    assert (
        'origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"' in behavior
    )
    assert 'viewer_protocol_policy   = "https-only"' in behavior
    assert re.search(r"connection_attempts\s+= 1", site)
    assert re.search(r"connection_timeout\s+= 5", site)
    assert re.search(r"origin_read_timeout\s+= 55", site)
    for route in ("/api/config", "/api/chat", "/api/reset"):
        assert route in gate
    assert 'request.method === "GET"' in gate
    assert 'request.method === "POST"' in gate
    assert 'search_string         = "POST"' in site


def test_public_waf_has_only_the_bounded_metrics_only_controls():
    site = (ROOT / "infra/site.tf").read_text()
    waf = site.split('resource "aws_wafv2_web_acl" "public_chat"', maxsplit=1)[1].split(
        'resource "aws_lambda_permission" "public_chat_url"', maxsplit=1
    )[0]

    assert "limit                 = 20" in waf
    assert "evaluation_window_sec = 300" in waf
    assert re.search(r'aggregate_key_type\s+= "IP"', waf)
    assert "size                = 32768" in waf
    assert 'comparison_operator = "GT"' in waf
    assert 'oversize_handling = "MATCH"' in waf
    gate = (ROOT / "site/public-api-gate.js").read_text()
    assert "statusCode: 404" in gate
    for code in (413, 429):
        assert f"response_code            = {code}" in waf
    runbook = (ROOT / "docs/runbooks/kill-switch.md").read_text()
    assert "503" in runbook and "default action" in runbook
    assert "ignore_changes = [default_action]" in waf
    assert "cloudwatch_metrics_enabled = true" in waf
    assert "sampled_requests_enabled   = false" in waf
    assert "managed_rule_group_statement" not in waf
    assert "aws_wafv2_web_acl_logging_configuration" not in site


def test_proxy_session_store_is_private_ephemeral_and_least_privilege():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()

    assert 'resource "aws_dynamodb_table" "tollchat_sessions"' in agentcore
    assert 'billing_mode = "PAY_PER_REQUEST"' in agentcore
    assert 'hash_key     = "credential_hash"' in agentcore
    assert 'attribute_name = "expires_at"' in agentcore
    assert 'resource "aws_vpc_endpoint" "dynamodb"' in agentcore
    assert 'vpc_endpoint_type = "Gateway"' in agentcore
    assert "prefix_list_id    = data.aws_prefix_list.dynamodb.id" in agentcore
    proxy_policy = agentcore.split(
        'data "aws_iam_policy_document" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "tollchat_proxy"', maxsplit=1)[0]
    assert '"dynamodb:PutItem"' in proxy_policy
    assert '"dynamodb:UpdateItem"' in proxy_policy
    assert "aws_dynamodb_table.tollchat_sessions.arn" in proxy_policy
    assert "dynamodb:GetItem" not in proxy_policy
    assert "SESSION_TABLE_NAME" in agentcore
    assert "aws_vpc_endpoint.dynamodb" in agentcore


def test_launch_gate_alarms_cover_actionable_runtime_and_rds_signals():
    observability = (ROOT / "infra/observability.tf").read_text()
    smoke = (ROOT / "scripts/smoke.sh").read_text()

    assert (
        'resource "aws_cloudwatch_log_metric_filter" "proxy_failure"' in observability
    )
    assert 'pattern        = "PROXY_FAILURE"' in observability
    assert 'name      = "ProxyFailure"' in observability

    expected = {
        "tollchat_proxy_errors": ("Errors", "threshold           = 1"),
        "tollchat_proxy_failures": ("ProxyFailure", "threshold           = 1"),
        "tollchat_proxy_latency": ("Duration", 'extended_statistic  = "p99"'),
        "tollchat_sessions": ("ActiveSessionCount", "threshold           = 10"),
        "rds_cpu": ("CPUUtilization", "threshold           = 70"),
        "rds_free_memory": ("FreeableMemory", "threshold           = 64 * 1024 * 1024"),
        "rds_connections": ("DatabaseConnections", "threshold           = 60"),
        "rds_cpu_credits": ("CPUCreditBalance", "threshold           = 72"),
    }
    for resource, (metric, setting) in expected.items():
        block = observability.split(
            f'resource "aws_cloudwatch_metric_alarm" "{resource}"', maxsplit=1
        )[1].split("\n}", maxsplit=1)[0]
        assert f'metric_name         = "{metric}"' in block
        assert setting in block
        assert "alarm_description" in block
        assert "alarm_actions       = [aws_sns_topic.alerts.arn]" in block
        assert 'treat_missing_data  = "notBreaching"' in block

    latency = observability.split(
        'resource "aws_cloudwatch_metric_alarm" "tollchat_proxy_latency"', maxsplit=1
    )[1].split("\n}", maxsplit=1)[0]
    assert "threshold           = 45 * 1000" in latency
    assert "datapoints_to_alarm = 1" in latency

    sessions = observability.split(
        'resource "aws_cloudwatch_metric_alarm" "tollchat_sessions"', maxsplit=1
    )[1].split("\n}", maxsplit=1)[0]
    assert "datapoints_to_alarm = 2" in sessions
    assert "evaluation_periods  = 3" in sessions

    assert 'resource "aws_cloudwatch_metric_alarm" "freshness"' in observability
    assert 'treat_missing_data  = "breaching"' in observability
    assert "docs/runbooks/alarms.md" in observability
    assert "Endpoint=='$RECIPIENT'" in smoke
    for alarm in (
        "tollchat-chat-proxy-errors",
        "tollchat-chat-proxy-failures",
        "tollchat-chat-proxy-latency",
        "tollchat-agentcore-active-sessions",
        "toll-rds-cpu",
        "toll-rds-free-memory",
        "toll-rds-connections",
        "toll-rds-cpu-credits",
    ):
        assert alarm in smoke

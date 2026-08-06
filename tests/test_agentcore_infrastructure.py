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

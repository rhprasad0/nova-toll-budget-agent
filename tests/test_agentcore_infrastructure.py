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


def test_runtime_and_proxy_roles_are_separate_and_ssm_remains_authoritative():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()

    assert 'resource "aws_iam_role" "tollchat_runtime"' in agentcore
    assert 'resource "aws_iam_role" "tollchat_proxy"' in agentcore
    assert "parameter/nova-toll/openai_api_key" in agentcore
    assert '"rds-db:connect"' in agentcore
    assert '"bedrock-agentcore:InvokeAgentRuntime"' in agentcore
    assert "create-api-key-credential-provider" not in agentcore
    assert "delete-parameter" not in agentcore


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

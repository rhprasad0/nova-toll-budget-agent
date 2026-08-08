import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_site_is_byte_for_byte_unchanged():
    assert (
        hashlib.sha256((ROOT / "site/index.html").read_bytes()).hexdigest()
        == "97d5148aebf567e5c0429e98297973ffcd971627f04ae5c3942985a8cfaaa684"
    )


def test_preview_uses_private_api_gateway_lambda_response_streaming():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()

    assert (
        'service_name        = "com.amazonaws.${data.aws_region.current.region}.execute-api"'
        in agentcore
    )
    assert 'types            = ["PRIVATE"]' in agentcore
    assert 'response_transfer_mode  = "STREAM"' in agentcore
    assert "response_streaming_invoke_arn" in agentcore
    assert (
        'resource "aws_api_gateway_domain_name_access_association" "tollchat"'
        in agentcore
    )
    assert agentcore.count("aws:SourceVpce") >= 4
    assert 'runtime                        = "nodejs24.x"' in agentcore
    assert 'handler                        = "handler.handler"' in agentcore


def test_preview_remains_tailnet_only_and_agentcore_stays_on_privatelink():
    agentcore = (ROOT / "infra/agentcore.tf").read_text()
    policy = (ROOT / "policy.hujson").read_text()

    assert 'description = "TollChat private API Gateway endpoint"' in agentcore
    assert (
        'cidr_ipv4         = "${aws_instance.tailscale_router.private_ip}/32"'
        in agentcore
    )
    assert (
        'service_name        = "com.amazonaws.${data.aws_region.current.region}.bedrock-agentcore"'
        in agentcore
    )
    assert "DenyOutsidePrivateEndpoint" in agentcore
    assert '"tollchat-preview-test:443"' in policy
    assert 'resource "aws_lb" "tollchat"' not in agentcore
    assert 'resource "aws_lb_target_group" "tollchat"' not in agentcore


def test_main_cloudfront_has_no_chat_origin_or_public_gate():
    site = (ROOT / "infra/site.tf").read_text()
    variables = (ROOT / "infra/variables.tf").read_text()

    assert "aws_cloudfront_vpc_origin" not in site
    assert 'path_pattern           = "/api/*"' not in site
    assert "aws_wafv2_web_acl" not in site
    assert "enable_public_chat" not in variables


def test_proxy_build_installs_locked_node_dependencies_and_bundles_preview():
    build = (ROOT / "scripts/build_zips.sh").read_text()

    assert 'npm ci --omit=dev --prefix "$REPO/lambdas/chat_proxy"' in build
    assert "handler.mjs" in build
    assert "preview.html" in build
    assert "preview.mjs" in build

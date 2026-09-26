import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from textwrap import dedent

import pytest

from tests.infrastructure_support import (
    APPLICATION_VARIABLES,
    DEPLOYMENT,
    MAIN_TF,
    REPO_ROOT,
    TIMED_CHECKS_TF,
    V2_ROOT,
    hcl_named_blocks,
    hcl_scalar,
    terraform_block,
)


def test_v2_has_an_independent_state_and_identity() -> None:
    assert 'environment"' in (V2_ROOT / "infra" / "variables.tf").read_text()
    assert (
        "nova-toll/v2/development/terraform.tfstate"
        in (V2_ROOT / "infra" / "backend.development.hcl").read_text()
    )
    assert 'function_name = "toll-v2-pricing-loader${local.suffix}"' in MAIN_TF
    assert "${local.database_roles.loader}" in MAIN_TF
    assert re.search(r"DB_USER\s+= local.database_roles.loader", MAIN_TF)
    assert 'name = "toll-v2-pricing-raw-objects${local.suffix}"' in MAIN_TF
    assert (
        'alarm_name          = "toll-v2-pricing-loader-errors${local.suffix}"'
        in MAIN_TF
    )
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    assert (
        'source        = local.is_production ? "${path.module}/../agent/robots.txt" : null'
        in site
    )
    assert 'name    = "tollchat-v2-public-chat-routes${local.suffix}"' in site
    measurement = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
    assert 'name = "tollchat-agent-reports${local.suffix}"' in measurement
    assert (
        'agent_measurement_acl      = "tollchat-v2-public-chat${local.suffix}"'
        in measurement
    )
    assert (
        'resource "aws_wafv2_web_acl_logging_configuration" "agent_reports"'
        not in measurement
    )
    assert 'resource "aws_s3_object" "agent_registry"' in measurement
    assert "ignore_changes = [source, source_hash]" in measurement
    assert "WAFLogs/cloudfront/${local.agent_measurement_acl}/" in measurement
    assert (
        'resource "aws_cloudfront_response_headers_policy" "development_noindex"'
        in site
    )
    assert "count = local.is_production ? 0 : 1" in site
    assert 'header   = "X-Robots-Tag"' in site
    assert 'value    = "noindex"' in site


def test_v2_declares_a_private_agentcore_application_with_protected_trace_archive() -> (
    None
):
    agentcore_path = V2_ROOT / "infra" / "agentcore.tf"
    assert agentcore_path.exists()
    agentcore = agentcore_path.read_text()
    assert (
        'agent_runtime_name = "nova_toll_v2${local.is_production ? "" : "_development"}${each.key == "blue" ? "" : "_green"}"'
        in agentcore
    )
    assert 'network_mode = "VPC"' in agentcore
    assert (
        "dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.agent}"
        in agentcore
    )
    assert (
        "dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.pricing_caller}"
        in agentcore
    )
    assert (
        'function_name                  = "tollchat-v2-chat-proxy${local.slot_suffix[each.key]}"'
        in agentcore
    )
    assert 'name         = "tollchat-v2-anonymous-sessions${local.suffix}"' in agentcore
    assert 'types            = ["PRIVATE"]' in agentcore
    assert 'response_transfer_mode  = "STREAM"' in agentcore
    assert "DenyOutsidePrivateEndpoint" in agentcore
    assert (
        'resource "aws_vpc_security_group_ingress_rule" "agentcore_from_proxy"'
        in agentcore
    )
    assert "aws_cloudfront" not in agentcore
    assert "cloudflare" not in agentcore
    assert "aws_acm" not in agentcore
    assert "opentelemetry" not in agentcore.lower()
    assert "TOLLCHAT_TRACE_LOG_GROUP" not in agentcore
    assert "github_pat_[A-Za-z0-9_-]{20,}" in agentcore
    guardrail_version = agentcore.split(
        'resource "aws_bedrock_guardrail_version" "tollchat"', maxsplit=1
    )[1].split('resource "aws_bedrockagentcore_agent_runtime"', maxsplit=1)[0]
    assert (
        "replace_triggered_by = [aws_bedrock_guardrail.tollchat]"
        not in guardrail_version
    )
    for attribute in (
        "blocked_input_messaging",
        "blocked_outputs_messaging",
        "content_policy_config",
        "sensitive_information_policy_config",
    ):
        assert f"aws_bedrock_guardrail.tollchat.{attribute}" in guardrail_version

    runtime_logs = agentcore.split(
        'resource "aws_cloudwatch_log_group" "agentcore_runtime"', maxsplit=1
    )[1].split('resource "aws_bedrockagentcore_agent_runtime_endpoint"', maxsplit=1)[0]
    assert "for_each = local.runtime_logs" in runtime_logs
    assert "retention_in_days = local.is_production ? 1 : 7" in runtime_logs
    for resource in (
        'resource "aws_kinesis_firehose_delivery_stream" "agentcore_traces"',
        'resource "aws_cloudwatch_log_subscription_filter" "agentcore_traces"',
        "UNIFIED_TRACES_DESTINATION_ENABLED",
    ):
        assert resource in agentcore
    trace_archive_flag = "enable_development_" + "trace_archive"
    assert trace_archive_flag not in agentcore
    assert "TOLLCHAT_" + "DEVELOPMENT_TRACES" not in agentcore
    assert trace_archive_flag not in APPLICATION_VARIABLES
    firehose = terraform_block(
        agentcore, 'resource "aws_kinesis_firehose_delivery_stream" "agentcore_traces"'
    )
    assert "count       = 1" in firehose
    assert 'prefix             = "agentcore-traces/"' in firehose
    assert re.findall(r'processors \{ type = "([^"]+)" \}', firehose) == [
        "Decompression",
        "AppendDelimiterToRecord",
    ]
    assert (
        firehose.index('processors { type = "Decompression" }')
        < firehose.index('type = "CloudWatchLogProcessing"')
        < firehose.index('processors { type = "AppendDelimiterToRecord" }')
    )
    processing = hcl_named_blocks(firehose, "processing_configuration")[0]
    assert "enabled = true" in processing
    cloudwatch_processor = hcl_named_blocks(firehose, "processors")[1]
    assert hcl_scalar(cloudwatch_processor, "type") == "CloudWatchLogProcessing"
    parameters = hcl_named_blocks(cloudwatch_processor, "parameters")
    assert len(parameters) == 1
    assert hcl_scalar(parameters[0], "parameter_name") == "DataMessageExtraction"
    assert hcl_scalar(parameters[0], "parameter_value") == "true"
    subscriptions = terraform_block(
        agentcore,
        'resource "aws_cloudwatch_log_subscription_filter" "agentcore_traces"',
    )
    assert "local.runtime_logs" in subscriptions
    assert (
        'filter_pattern  = "{ $.traceId = \\"*\\" && $.spanId = \\"*\\" && $.durationNano >= 0 }"'
        in subscriptions
    )
    assert (
        "depends_on = [aws_cloudwatch_log_data_protection_policy.agentcore]"
        in subscriptions
    )
    assert "exc_info" not in subscriptions


def test_v2_public_edge_reuses_the_runtime_and_keeps_one_proxy_warm() -> None:
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    main = (V2_ROOT / "infra" / "main.tf").read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_api_gateway_rest_api"', maxsplit=1)[0]
    assert "publish                        = true" in proxy
    assert "reserved_concurrent_executions = 5" in proxy
    assert "ignore_changes = [reserved_concurrent_executions]" not in proxy
    assert "PUBLIC_ORIGINS = local.public_site_url" in agentcore
    assert "merge(each.value.proxy_environment" in proxy
    assert 'PUBLIC_ORIGINS = "https://${local.domains[0]}"' not in proxy
    loader = main.split('resource "aws_lambda_function" "loader"', maxsplit=1)[1].split(
        'resource "aws_lambda_function" "publisher"', maxsplit=1
    )[0]
    publisher = main.split('resource "aws_lambda_function" "publisher"', maxsplit=1)[
        1
    ].split(
        'resource "aws_lambda_function_event_invoke_config" "publisher"', maxsplit=1
    )[0]
    assert "reserved_concurrent_executions = 5" in loader
    assert "reserved_concurrent_executions = 1" in publisher
    assert "PUBLIC_BASE_URL      = local.public_site_url" in publisher
    assert 'request POST "$PREVIEW_URL/api/reset"' in DEPLOYMENT
    assert "Origin: $PREVIEW_URL" in DEPLOYMENT
    assert "Content-Type: application/json" in DEPLOYMENT
    assert "Sec-Fetch-Site: same-origin" in DEPLOYMENT
    assert "printf '{}' >\"$RESET_REQUEST\"" in DEPLOYMENT
    assert 'RESET_BODY_SHA256="$(sha256sum "$RESET_REQUEST"' in DEPLOYMENT
    assert "x-amz-content-sha256: $RESET_BODY_SHA256" in DEPLOYMENT
    assert '--data-binary "@$RESET_REQUEST"' in DEPLOYMENT
    assert "write-out '%{content_type}'" in DEPLOYMENT
    assert "jq -e '.ok == true'" in DEPLOYMENT
    assert (
        agentcore.count(
            'metric_name         = "V2ProxyFailure${local.slot_suffix[each.key]}"'
        )
        == 1
    )
    assert (
        agentcore.count('name      = "V2ProxyFailure${local.slot_suffix[each.key]}"')
        == 1
    )
    assert 'resource "aws_lambda_alias" "tollchat_live"' in agentcore
    assert 'name             = "live"' in agentcore
    assert (
        'resource "aws_lambda_provisioned_concurrency_config" "tollchat"' in agentcore
    )
    assert (
        "count                             = local.is_production ? 1 : 0" in agentcore
    )
    assert (
        'qualifier                         = aws_lambda_alias.tollchat_live["blue"].name'
        in agentcore
    )

    assert 'resource "aws_lambda_function_url" "public_chat"' in site
    assert 'authorization_type = "AWS_IAM"' in site
    assert 'invoke_mode        = "RESPONSE_STREAM"' in site
    assert "qualifier          = aws_lambda_alias.tollchat_live[each.key].name" in site
    assert 'origin_access_control_origin_type = "lambda"' in site
    assert 'origin_access_control_origin_type = "s3"' in site
    assert 'path_pattern             = "/api/*"' in site
    assert 'code    = file("${path.module}/../agent/public-api-gate.js")' in site
    assert (
        "aliases                         = local.custom_domain_enabled ? local.domains : []"
        in site
    )
    assert "cloudfront_default_certificate = !local.custom_domain_enabled" in site
    assert (
        'minimum_protocol_version       = local.custom_domain_enabled ? "TLSv1.2_2021" : "TLSv1"'
        in site
    )
    development_release = DEPLOYMENT.split(
        "### Development application release and database validation (#331)", maxsplit=1
    )[1].split("### Development handoff (non-operative)", maxsplit=1)[0]
    for text in (
        "def reserved($address; $expected)",
        "def default_edge:",
        'minimum_protocol_version == "TLSv1"',
        "get-function-concurrency",
        "function-name tollchat-v2-chat-proxy-dev",
        "PUBLIC_BASE_URL",
        'PHASE_ONE_PLAN_JSON="$RELEASE_DIR/development-phase-one.tfplan.json"',
        'PHASE_TWO_PLAN_JSON="$RELEASE_DIR/development-phase-two.tfplan.json"',
        "ARTIFACT_SCAN_PATTERN=",
        "PACKAGE_SCAN_PATTERN=",
        "scan_release_file",
        "scan_package",
        "scan_release_directory",
        'unzip -p "$package"',
        "check_lambda_quota_gate.py",
        "assert_reserved_concurrency",
        "resource_inventory=$RESOURCE_TYPES",
        'rm -rf -- "$ROOT/v2/infra/build"',
    ):
        assert text in development_release
    assert 'resource "aws_wafv2_web_acl" "public_chat"' in site
    assert "limit                 = local.rate_limit" in site
    assert "size                = 32768" in site
    assert 'resource "cloudflare_dns_record" "apex"' in site
    assert 'resource "cloudflare_dns_record" "www"' in site
    assert 'resource "aws_acm_certificate" "site"' in site


def test_development_site_has_no_cloudflare_reads_or_writes() -> None:
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    development_tfvars = (V2_ROOT / "infra" / "development.tfvars").read_text()
    zone = site.split('data "cloudflare_zone" "tollchat"', maxsplit=1)[1].split(
        'resource "aws_acm_certificate" "site"', maxsplit=1
    )[0]
    certificate_records = site.split(
        'resource "cloudflare_dns_record" "site_cert_validation"', maxsplit=1
    )[1].split('resource "aws_acm_certificate_validation" "site"', maxsplit=1)[0]
    certificate_validation = site.split(
        'resource "aws_acm_certificate_validation" "site"', maxsplit=1
    )[1].split('resource "cloudflare_dns_record" "apex"', maxsplit=1)[0]
    apex = site.split('resource "cloudflare_dns_record" "apex"', maxsplit=1)[1].split(
        'resource "cloudflare_dns_record" "www"', maxsplit=1
    )[0]
    www = site.split('resource "cloudflare_dns_record" "www"', maxsplit=1)[1].split(
        'output "public_site"', maxsplit=1
    )[0]

    assert "count  = local.is_production ? 1 : 0" in zone
    assert "for_each = local.is_production ? {" in certificate_records
    assert "data.cloudflare_zone.tollchat.zone_id" not in site
    assert "data.cloudflare_zone.tollchat[0].zone_id" in site
    assert "count           = local.is_production ? 1 : 0" in certificate_validation
    assert (
        "depends_on = [cloudflare_dns_record.site_cert_validation]"
        in certificate_validation
    )
    assert "from = data.cloudflare_zone.tollchat" in site
    assert "to   = data.cloudflare_zone.tollchat[0]" in site
    assert "from = aws_acm_certificate_validation.site" in site
    assert "to   = aws_acm_certificate_validation.site[0]" in site
    assert "count   = local.is_production && var.enable_public_dns ? 1 : 0" in apex
    assert "count   = local.is_production ? 1 : 0" in www
    assert re.search(r'(?m)^environment\s*=\s*"development"$', development_tfvars)
    assert re.search(r"(?m)^enable_public_dns\s*=\s*false$", development_tfvars)
    assert "development path has no Cloudflare data or resource instances" in DEPLOYMENT
    assert "development DNS/certificate validation" in DEPLOYMENT


def test_public_report_surface_is_canonical_crawlable_and_isolated() -> None:
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    robots = (V2_ROOT / "agent" / "robots.txt").read_text()

    assert 'resource "aws_cloudfront_function" "public_report_routes"' in site
    assert 'code    = file("${path.module}/../agent/public-report-routes.js")' in site
    default_behavior = site.split("  default_cache_behavior {", maxsplit=1)[1].split(
        "  ordered_cache_behavior {", maxsplit=1
    )[0]
    assert "aws_cloudfront_function.public_report_routes.arn" in default_behavior
    api_behavior = site.split("  ordered_cache_behavior {", maxsplit=1)[1].split(
        "  ordered_cache_behavior {", maxsplit=1
    )[0]
    assert "aws_cloudfront_function.public_chat_routes.arn" in api_behavior
    assert "aws_cloudfront_function.public_report_routes.arn" not in api_behavior

    robots_object = site.split('resource "aws_s3_object" "robots"', maxsplit=1)[
        1
    ].split('resource "aws_s3_object"', maxsplit=1)[0]
    assert 'key           = "robots.txt"' in robots_object
    assert (
        'source        = local.is_production ? "${path.module}/../agent/robots.txt" : null'
        in robots_object
    )
    assert 'content_type  = "text/plain; charset=utf-8"' in robots_object
    assert 'cache_control = "no-cache"' in robots_object
    for user_agent in (
        "OAI-SearchBot",
        "ChatGPT-User",
        "Claude-SearchBot",
        "Claude-User",
        "Googlebot",
        "Google-Extended",
        "Google-Agent",
        "PerplexityBot",
        "Perplexity-User",
        "bingbot",
        "Amzn-SearchBot",
        "Amzn-User",
        "Applebot",
        "DuckAssistBot",
    ):
        assert f"User-agent: {user_agent}\nAllow: /tolls/" in robots
    assert "Sitemap: https://tollchat.ai/sitemap.xml" in robots
    for training_agent in ("GPTBot", "ClaudeBot", "Amazonbot", "Applebot-Extended"):
        assert training_agent not in robots
    assert "cloudfront wait distribution-deployed" in DEPLOYMENT
    assert "aws_lambda_function.publisher" in DEPLOYMENT
    assert 'test "$(wc -l <"$REPORT_URLS")" -eq 262' in DEPLOYMENT
    assert (
        "Disabling publication does not withdraw existing report objects" in DEPLOYMENT
    )


def test_public_report_launch_is_selected_environment_and_correlated() -> None:
    launch = DEPLOYMENT.split("## Public report launch", 1)[1].split(
        "## Smoke test", 1
    )[0]
    assert "production only" in launch.lower()
    assert re.search(
        r"never run it while the development\s+backend is selected", launch
    )
    assert re.search(
        r"Development public report publication, Cloudflare, and DNS\s+remain deferred to #332",
        launch,
    )
    for required in (
        "terraform output -json public_site",
        ".url | select",
        '"$SITE_URL/sitemap.xml"',
        'REPORT_URL="$SITE_URL/tolls/',
        "aws_cloudwatch_log_group.publisher",
        "REPORT_SMOKE_ID=",
        "REPORT_STARTED_MS=",
        "--invocation-type Event",
        ".StatusCode == 202",
        "logs filter-log-events",
        '--start-time "$REPORT_STARTED_MS"',
        "V2_REPORT_SMOKE_OK $REPORT_SMOKE_ID",
        "(published|unchanged)",
        'schema_version == "3.0.0"',
        "facility == $facility",
        "route_count == $routes",
        "report_manifest_is_valid i66 16",
        'test("^[a-f0-9]{64}$")',
        "trap 'rm -f --",
    ):
        assert required in launch

    shells = re.findall(r"```sh\n(.*?)\n```", launch, re.DOTALL)
    assert len(shells) == 2
    for shell in shells:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write(shell)
            script.flush()
            assert (
                subprocess.run(["bash", "-n", script.name], check=False).returncode == 0
            )
        for required in (
            'ROOT="$(git rev-parse --show-toplevel)"',
            'cd "$ROOT/v2/infra"',
            'get-caller-identity --query Account --output text)" = "920534282028"',
            "terraform init -reconfigure -input=false -backend-config=backend.production.hcl",
            'test "$PUBLISHER_FUNCTION" = "toll-v2-report-publisher"',
            'test "$PUBLISHER_LOG_GROUP" = "/aws/lambda/toll-v2-report-publisher"',
            'test "$SITE_BUCKET" = "tollchat-site-920534282028"',
            'test -n "$SITE_DISTRIBUTION"',
            '[[ "$SITE_DISTRIBUTION" =~ ^[A-Z0-9]+$ ]]',
            'test "$SITE_URL" = "https://tollchat.ai"',
        ):
            assert required in shell
        assert not re.search(r'SITE_DISTRIBUTION="E[A-Z0-9]+"', shell)
        selection = shell.index('test "$(AWS_PROFILE=nova-toll-prod aws sts')
        initialization = shell.index(
            "terraform init -reconfigure -input=false -backend-config=backend.production.hcl"
        )
        state_reads = [
            shell.index("terraform state show"),
            shell.index("terraform output -json public_site"),
        ]
        assert selection < initialization < min(state_reads)
        validation = max(
            shell.index('test "$PUBLISHER_FUNCTION"'),
            shell.index('test "$PUBLISHER_LOG_GROUP"'),
            shell.index('test "$SITE_BUCKET"'),
            shell.index('test -n "$SITE_DISTRIBUTION"'),
            shell.index('[[ "$SITE_DISTRIBUTION"'),
            shell.index('test "$SITE_URL"'),
        )
        report_operations = [
            shell.find("cloudfront wait"),
            shell.find("lambda invoke"),
            shell.find("logs filter-log-events"),
            shell.find("s3api get-object"),
            shell.find("curl --fail"),
        ]
        report_operations = [
            position for position in report_operations if position >= 0
        ]
        assert report_operations and validation < min(report_operations)

    shell = shells[0]

    def shell_function(name: str) -> str:
        match = re.search(rf"(?ms)^{name}\(\) \{{.*?^\}}", shell)
        if match is None:
            raise AssertionError(f"missing {name}")
        return match.group(0)

    smoke_check = shell_function("report_smoke_succeeded")
    manifest_check = shell_function("report_manifest_is_valid")
    smoke_id = "123e4567-e89b-12d3-a456-426614174000"
    generation_id = "2026-08-25T16:05:00Z"
    result_sha256 = "a" * 64

    def smoke_passes(records: str) -> bool:
        return (
            subprocess.run(
                [
                    "bash",
                    "-c",
                    f'set -euo pipefail; {smoke_check}; report_smoke_succeeded "$REPORT_RESULT"',
                ],
                check=False,
                env={
                    **os.environ,
                    "REPORT_SMOKE_ID": smoke_id,
                    "REPORT_STARTED_MS": "1000",
                    "REPORT_RESULT": records,
                },
            ).returncode
            == 0
        )

    assert smoke_passes(
        f"1000\tV2_REPORT_SMOKE_OK {smoke_id} published {generation_id} {result_sha256}"
    )
    assert smoke_passes(
        f"1001\tV2_REPORT_SMOKE_OK {smoke_id} unchanged {generation_id} {result_sha256}"
    )
    assert smoke_passes(
        f"1001\t2026-08-25T16:05:01Z INFO V2_REPORT_SMOKE_OK {smoke_id} published {generation_id} {result_sha256}"
    )
    assert not smoke_passes(
        f"999\tV2_REPORT_SMOKE_OK {smoke_id} published {generation_id} {result_sha256}"
    )
    assert not smoke_passes(
        "1001\tV2_REPORT_SMOKE_OK 123e4567-e89b-12d3-a456-426614174001 "
        f"published {generation_id} {result_sha256}"
    )
    assert not smoke_passes(
        f"1001\tV2_REPORT_SMOKE_OK {smoke_id} superseded {generation_id} {result_sha256}"
    )
    assert not smoke_passes(
        f"1001\tV2_REPORT_SMOKE_OK {smoke_id} error {generation_id} {result_sha256}"
    )
    assert not smoke_passes(f"1001\tV2_REPORT_SMOKE_OK {smoke_id} published ")
    assert not smoke_passes(
        f"1001\tV2_REPORT_SMOKE_OK {smoke_id} published malformed {result_sha256}"
    )
    assert not smoke_passes(
        f"1001\tV2_REPORT_SMOKE_OK {smoke_id} published 2026-99-25T16:05:00Z {result_sha256}"
    )
    assert not smoke_passes(
        f"1001\tV2_REPORT_SMOKE_OK {smoke_id} published {generation_id} {'A' * 64}"
    )
    assert not smoke_passes(
        f"1001\tV2_REPORT_SMOKE_OK {smoke_id} published {generation_id} {'a' * 63}"
    )
    assert not smoke_passes("1001\tV2_REPORT_GENERATION_OK i95_i495")

    def manifest_passes(manifest: Mapping[str, object]) -> bool:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as fixture:
            json.dump(manifest, fixture)
            fixture.flush()
            return (
                subprocess.run(
                    [
                        "bash",
                        "-c",
                        f'set -euo pipefail; {manifest_check}; report_manifest_is_valid i95_i495 246 "$REPORT_MANIFEST"',
                    ],
                    check=False,
                    env={**os.environ, "REPORT_MANIFEST": fixture.name},
                ).returncode
                == 0
            )

    manifest: dict[str, object] = {
        "schema_version": "3.0.0",
        "facility": "i95_i495",
        "route_count": 246,
        "week_end": "2026-08-01T00:00:00Z",
        "result_sha256": "a" * 64,
    }
    assert manifest_passes(manifest)
    assert not manifest_passes({**manifest, "week_end": ""})
    assert not manifest_passes({**manifest, "result_sha256": "A" * 64})


def test_public_site_publishes_the_v2_ui_and_legal_assets() -> None:
    from scripts.verify_release_bundle import FIXED_PATHS

    site = (V2_ROOT / "infra" / "site.tf").read_text()
    page = (V2_ROOT / "agent" / "dev_chat.html").read_text()
    server = (V2_ROOT / "agent" / "dev_chat.py").read_text()

    for path in (
        "dev_chat.html",
        "public_chat.mjs",
        "faq.html",
        "privacy.txt",
        "terms.txt",
    ):
        assert "v2/agent/" + path in FIXED_PATHS
    assert (
        "origin_path                 = var.release_slots[var.active_slot].asset_prefix"
        in site
    )
    assert 'path_pattern           = "/releases/*"' in site
    assert (V2_ROOT / "agent" / "assets" / "tollchat-logo.png").exists()
    assert (V2_ROOT / "agent" / "assets" / "favicon.png").exists()
    assert 'href="/assets/favicon.png"' in page
    assert '"assets/favicon.png"' in server
    assert '<script type="module" src="/chat.mjs"></script>' in page
    assert '"/chat.mjs"' in server
    assert 'key           = "usage.json"' in site
    assert 'content       = "{}"' in site
    assert 'id="usage-proof"' not in page
    assert "New public usage counting has stopped" in page
    assert "TollChat counts anonymous chat sessions" not in page


def test_v2_agent_packages_are_required_for_real_deployments() -> None:
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    build = V2_ROOT / "scripts" / "build_agentcore_zips.sh"
    assert 'variable "agentcore_package_path"' not in variables
    assert 'variable "chat_proxy_package_path"' not in variables
    assert "for_each           = var.release_slots" in agentcore
    assert "AgentCore must use the immutable release artifact" in agentcore
    assert "Chat proxy must use the immutable release artifact" in agentcore
    assert build.exists()


def test_reviewed_zip_builders_use_store_mode() -> None:
    expected_calls = {
        "build_loader_zip.sh": r'zip -qX0 "\$BUILD/loader\.zip" -@',
        "build_publisher_zip.sh": r'zip -qX0 "\$BUILD/publisher\.zip" -@',
        "build_agentcore_zips.sh": r'zip -qX0 "\$out" -@',
        "build_timed_checks_zip.sh": r'zip -qX0 "\$BUILD/timed-checks\.zip" -@',
    }
    for script_name, archive_call in expected_calls.items():
        script = (V2_ROOT / "scripts" / script_name).read_text()
        assert re.search(rf"(?m)^[ \t]*\([^\n]*\| {archive_call}\)$", script)


def test_ca_helper_can_be_sourced_without_build_side_effects(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            dedent("""\
                set +e +u
                set +o pipefail
                PATH=/nonexistent
                V2_ROOT=caller BUILD=caller STAGE=caller EPOCH=caller
                before_environment=$(export -p)
                before_flags="$-"
                before_options=$(set +o)
                source "$1" || exit
                [[ "$before_environment" == "$(export -p)" ]] || exit 1
                [[ "$before_flags" == "$-" ]] || exit 1
                [[ "$before_options" == "$(set +o)" ]] || exit 1
                [[ "$V2_ROOT:$BUILD:$STAGE:$EPOCH" == caller:caller:caller:caller ]] || exit 1
                declare -F download_rds_ca_bundle >/dev/null
                """),
            "bash",
            str(V2_ROOT / "scripts/build_loader_zip.sh"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("curl_status, expected_status", [(23, 23), (0, 1)])
def test_ca_helper_rejects_download_and_checksum_failures(
    tmp_path: Path, curl_status: int, expected_status: int
) -> None:
    destination = tmp_path / "rds-ca-bundle.pem"
    curl_log = tmp_path / "curl-args"
    checksum_log = tmp_path / "checksum-called"
    result = subprocess.run(
        [
            "bash",
            "-c",
            dedent("""\
                source "$1"
                curl_log="$3" checksum_log="$4" curl_status="$5"
                curl() {
                  printf '%s\n' "$@" >"$curl_log"
                  printf 'untrusted certificate' >"${@: -1}"
                  return "$curl_status"
                }
                sha256sum() {
                  tee "$checksum_log" | command sha256sum "$@"
                }
                download_rds_ca_bundle "$2"
                """),
            "bash",
            str(V2_ROOT / "scripts/build_loader_zip.sh"),
            str(destination),
            str(curl_log),
            str(checksum_log),
            str(curl_status),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_status
    assert curl_log.read_text().splitlines() == [
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--proto",
        "=https",
        "--tlsv1.2",
        "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem",
        "-o",
        str(destination),
    ]
    assert checksum_log.exists() is (curl_status == 0)
    if curl_status == 0:
        assert checksum_log.read_text() == (
            "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
            f"  {destination}\n"
        )
    assert ("RDS CA bundle digest mismatch" in result.stderr) is (curl_status == 0)


def test_timed_builder_import_smoke_is_secret_isolated() -> None:
    script = (V2_ROOT / "scripts" / "build_timed_checks_zip.sh").read_text()
    assert "env -i" in script
    assert "PYTHONNOUSERSITE=1" in script
    assert 'PYTHONPATH="$STAGE"' in script
    assert (
        'name.startswith(("AWS_", "ACTIONS_", "GITHUB_", "OPENAI_", "CLOUDFLARE_"))'
        in script
    )
    assert "uv run --python 3.13 --no-project python" in script
    assert 'source "$V2_ROOT/scripts/build_loader_zip.sh"' in script
    assert 'download_rds_ca_bundle "$STAGE/rds-ca-bundle.pem"' in script
    assert (
        'DB_CA_BUNDLE_PATH          = "/var/task/rds-ca-bundle.pem"' in TIMED_CHECKS_TF
    )


def test_public_openai_egress_has_a_narrow_expiring_trivy_exception() -> None:
    ignores = (REPO_ROOT / ".trivyignore.yaml").read_text()
    exception = """  - id: AVD-AWS-0104
    paths: [v2/infra/agentcore.tf]
    statement: The runtime must reach the public OpenAI API over HTTPS.
    expired_at: 2027-02-13"""
    assert exception in ignores
    assert (
        """  - id: AVD-AWS-0104
    paths: [v2/infra/timed_checks.tf]
    statement: Timed evaluations must reach the public OpenAI API over HTTPS.
    expired_at: 2027-02-13"""
        in ignores
    )
    assert (
        """  - id: AVD-AWS-0104
    paths: [infra/agentcore.tf]"""
        not in ignores
    )

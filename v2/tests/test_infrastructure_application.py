import re
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

from tests.infrastructure_support import (
    APPLICATION_VARIABLES,
    DEPLOYMENT,
    MAIN_TF,
    RDS_CA_SHA256,
    REPO_ROOT,
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
        "\nresource ", maxsplit=1
    )[0]
    assert "reserved_concurrent_executions = 5" in loader
    assert "Content-Type: application/json" in DEPLOYMENT
    assert "Sec-Fetch-Site: same-origin" in DEPLOYMENT
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


def test_public_routing_and_robots_are_isolated() -> None:
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
    assert robots == "User-agent: *\nAllow: /\n"


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


def test_every_rds_ca_pin_matches_the_shared_download_function() -> None:
    """Production re-checks the bundle with its own copies; they must not drift."""
    stale: list[str] = []
    for path in (
        ".github/workflows/v2-production-migrations.yml",
        "v2/scripts/run_production_migrations_workflow.sh",
        "v2/scripts/adopt_production_baseline.py",
    ):
        pins = [
            pin
            for line in (REPO_ROOT / path).read_text().splitlines()
            if "CA_SHA256" in line or 'rds-ca-bundle.pem" | sha256sum' in line
            for pin in re.findall(r"[0-9a-f]{64}", line)
        ]
        if pins != [RDS_CA_SHA256]:
            stale.append(path)
    assert not stale, (
        f"Set the RDS CA pin to {RDS_CA_SHA256}, from v2/scripts/build_loader_zip.sh, "
        f"in {stale}; then run v2/scripts/update_release_manifest.py"
    )


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
        assert checksum_log.read_text() == f"{RDS_CA_SHA256}  {destination}\n"
    assert ("RDS CA bundle digest mismatch" in result.stderr) is (curl_status == 0)


def test_public_openai_egress_has_a_narrow_expiring_trivy_exception() -> None:
    ignores = (REPO_ROOT / ".trivyignore.yaml").read_text()
    exception = """  - id: AVD-AWS-0104
    paths: [v2/infra/agentcore.tf]
    statement: The runtime must reach the public OpenAI API over HTTPS.
    expired_at: 2027-02-13"""
    assert exception in ignores
    assert (
        """  - id: AVD-AWS-0104
    paths: [infra/agentcore.tf]"""
        not in ignores
    )

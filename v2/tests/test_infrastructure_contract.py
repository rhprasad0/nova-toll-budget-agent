import json
import re
from pathlib import Path
from typing import cast

import yaml

V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
MAIN_TF = (V2_ROOT / "infra" / "main.tf").read_text()
CI_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
TIMED_CHECKS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-timed-checks.yml"
).read_text()
TIMED_SCHEDULE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-timed-schedule.yml"
).read_text()
TIMED_ROUTE_TEST = (V2_ROOT / "tests" / "test_validate_toll_route_live.py").read_text()
TIMED_BALLPARK_TEST = (
    V2_ROOT / "tests" / "test_get_annual_toll_ballpark_live.py"
).read_text()
VERSIONS_TF = (V2_ROOT / "infra" / "versions.tf").read_text()
FOUNDATION_ROOT = REPO_ROOT / "infra"
FOUNDATION_TRIGGERS = (FOUNDATION_ROOT / "triggers.tf").read_text()
FOUNDATION_LAMBDA = (FOUNDATION_ROOT / "lambda.tf").read_text()
FOUNDATION_IAM = (FOUNDATION_ROOT / "iam.tf").read_text()
FOUNDATION_AGENTCORE = (FOUNDATION_ROOT / "agentcore.tf").read_text()
DEPLOYMENT = (V2_ROOT / "RUNBOOK.md").read_text()
AGENTS = (REPO_ROOT / "AGENTS.md").read_text()


def test_foundation_publishes_raw_events_without_a_legacy_loader():
    notification = FOUNDATION_TRIGGERS.split(
        'resource "aws_s3_bucket_notification" "raw"', maxsplit=1
    )[1]
    assert "eventbridge = true" in notification
    assert "lambda_function" not in notification
    assert (
        'resource "aws_lambda_permission" "s3_invoke_loader"' not in FOUNDATION_TRIGGERS
    )
    assert 'resource "aws_lambda_function" "loader"' not in FOUNDATION_LAMBDA


def test_foundation_has_no_site_and_terraform_ci_only_validates():
    assert not (FOUNDATION_ROOT / "site.tf").exists()
    workflow = (REPO_ROOT / ".github" / "workflows" / "terraform.yml").read_text()
    assert workflow.count("terraform fmt -check -recursive") == 2
    assert workflow.count("terraform init -backend=false -input=false") == 2
    assert workflow.count("terraform validate") == 2
    assert "terraform plan" not in workflow
    assert "terraform apply" not in workflow
    assert "configure-aws-credentials" not in workflow
    assert "id-token: write" not in workflow
    assert 'resource "aws_iam_role" "terraform_apply"' not in FOUNDATION_IAM
    assert 'resource "aws_iam_role" "github_ci"' not in FOUNDATION_IAM


def test_delivery_contract_keeps_pr_checks_disposable_and_production_fixed():
    workflow = (REPO_ROOT / ".github" / "workflows" / "terraform.yml").read_text()

    assert 'backend "s3" {}' in (FOUNDATION_ROOT / "versions.tf").read_text()
    assert 'backend "s3" {}' in VERSIONS_TF
    assert (FOUNDATION_ROOT / "backend.production.hcl").read_text().find(
        'key          = "nova-toll/terraform.tfstate"'
    ) >= 0
    assert (V2_ROOT / "infra" / "backend.production.hcl").read_text().find(
        'key          = "nova-toll/v2/terraform.tfstate"'
    ) >= 0
    assert "postgis/postgis" in CI_WORKFLOW
    assert "python3 v2/scripts/check_schema_versions.py" in CI_WORKFLOW
    assert "v2/scripts/run_db_tests.sh" in CI_WORKFLOW
    for forbidden in (
        "terraform plan",
        "terraform apply",
        "configure-aws-credentials",
        "id-token: write",
    ):
        assert forbidden not in workflow
    for text in (
        "PRs use disposable migration validation only",
        "never mutate deployed databases or schemas",
        "Schema-changing work is not deployable",
    ):
        assert text in AGENTS
    for text in (
        "PRs use disposable PostGIS migration validation only",
        "Current releases are schema-neutral",
        "nova-toll-tfstate-920534282028",
        "nova-toll/terraform.tfstate",
        "nova-toll/v2/terraform.tfstate",
        "920534282028",
        "us-east-1",
        "nova-toll-db",
        "tollchat.ai",
        "nova-toll-agentcore-920534282028",
        "runtime/v2/agentcore.zip",
        "lambda/v2/chat-proxy.zip",
        "tollchat-v2-chat-proxy",
        "AgentCore runtime `nova_toll_v2`",
        "get-alias",
        "list-agent-runtimes",
        "liveVersion",
        'test ! -e "$RELEASE_EVIDENCE"',
        "set -eu",
        "grep -qx 'lambda_live_function_version=[0-9][0-9]*'",
        "sed -n 's/^agentcore_runtime_id=//p'",
        "update-alias",
        "update-agent-runtime-endpoint",
        "project = nova-toll-budget-agent",
        "version = v2",
        "environment = production",
        "foundation plan to be zero-change",
        "unexplained action or any replacement",
    ):
        assert text in DEPLOYMENT
    rollback = DEPLOYMENT.split("## Rollback", maxsplit=1)[1]
    assert rollback.index("update-alias") < rollback.index(
        "After the immediate rollback smoke test passes"
    )
    assert "temporary drift" in rollback
    assert "require it to report no changes" in rollback


def test_pull_request_workflows_have_no_production_access():
    def assert_safe_permissions(permissions: object) -> None:
        if isinstance(permissions, str):
            assert permissions != "write-all"
        elif isinstance(permissions, dict):
            permissions = cast(dict[str, object], permissions)
            assert permissions.get("id-token") != "write"

    github_token = re.compile(
        r"secrets\s*(?:[.]\s*GITHUB_TOKEN\b|\[\s*['\"]GITHUB_TOKEN['\"]\s*\])"
    )
    assert "secrets" not in github_token.sub("", "${{ secrets [ 'GITHUB_TOKEN' ] }}")
    assert "secrets" in github_token.sub("", "${{ secrets [ 'AWS_KEY' ] }}")
    for workflow_path in (REPO_ROOT / ".github" / "workflows").glob("*.y*ml"):
        workflow = workflow_path.read_text()
        document = yaml.load(workflow, Loader=yaml.BaseLoader)
        assert isinstance(document, dict)
        document = cast(dict[str, object], document)
        triggers = document.get("on")
        if not isinstance(triggers, (str, list, dict)):
            continue
        assert "pull_request_target" not in triggers
        if "pull_request" not in triggers:
            continue
        assert_safe_permissions(document.get("permissions"))
        jobs = document.get("jobs")
        if isinstance(jobs, dict):
            for job in cast(dict[str, object], jobs).values():
                if isinstance(job, dict):
                    assert_safe_permissions(
                        cast(dict[str, object], job).get("permissions")
                    )
        assert not re.search(r"\bsecrets\b", github_token.sub("", workflow))
        for forbidden in (
            "configure-aws-credentials",
            "AWS_PROFILE",
            "environment:",
        ):
            assert forbidden not in workflow


def test_shared_dynamodb_endpoint_admits_v2_session_table():
    endpoint = FOUNDATION_AGENTCORE.split(
        'resource "aws_vpc_endpoint" "dynamodb"', maxsplit=1
    )[1].split('resource "aws_s3_bucket" "agentcore_artifacts"', maxsplit=1)[0]
    assert "tollchat-v2-anonymous-sessions" in endpoint
    assert "table/tollchat-anonymous-sessions" not in endpoint
    assert "dynamodb:*" not in endpoint
    assert '"dynamodb:TransactWriteItems"' in endpoint


def test_v2_has_an_independent_state_and_identity():
    assert 'environment"' in (V2_ROOT / "infra" / "variables.tf").read_text()
    assert (
        "nova-toll/v2/development/terraform.tfstate"
        in (V2_ROOT / "infra" / "backend.development.hcl").read_text()
    )
    assert 'function_name = "toll-v2-pricing-loader${local.suffix}"' in MAIN_TF
    assert "${local.database_roles.loader}" in MAIN_TF
    assert "DB_USER    = local.database_roles.loader" in MAIN_TF


def test_v2_declares_a_private_agentcore_application_without_telemetry():
    agentcore_path = V2_ROOT / "infra" / "agentcore.tf"
    assert agentcore_path.exists()
    agentcore = agentcore_path.read_text()
    assert (
        'agent_runtime_name = "nova_toll_v2${local.is_production ? "" : "_development"}"'
        in agentcore
    )
    assert 'network_mode = "VPC"' in agentcore
    assert (
        "dbuser:${data.aws_db_instance.main.resource_id}/${local.database_roles.agent}"
        in agentcore
    )
    assert (
        "dbuser:${data.aws_db_instance.main.resource_id}/${local.database_roles.pricing_caller}"
        in agentcore
    )
    assert (
        'function_name                  = "tollchat-v2-chat-proxy${local.suffix}"'
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
    assert "xray" not in agentcore.lower()
    assert "TOLLCHAT_TRACE_LOG_GROUP" not in agentcore
    assert "github_pat_[A-Za-z0-9_-]{20,}" in agentcore

    runtime_logs = agentcore.split(
        'resource "aws_cloudwatch_log_group" "agentcore_runtime"', maxsplit=1
    )[1].split('resource "aws_bedrockagentcore_agent_runtime_endpoint"', maxsplit=1)[0]
    assert 'toset(["DEFAULT", "preview"])' in runtime_logs
    assert "retention_in_days = local.is_production ? 1 : 1" in runtime_logs

    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_api_gateway_rest_api"', maxsplit=1)[0]
    assert "ignore_changes = [reserved_concurrent_executions]" in proxy
    assert "aws_iam_role_policy.tollchat_proxy" in proxy

    assert "put-function-concurrency" in DEPLOYMENT
    assert "--reserved-concurrent-executions 5" in DEPLOYMENT


def test_v2_public_edge_reuses_the_runtime_and_keeps_one_proxy_warm():
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_api_gateway_rest_api"', maxsplit=1)[0]
    assert "publish                        = true" in proxy
    assert "reserved_concurrent_executions = 5" in proxy
    assert 'resource "aws_lambda_alias" "tollchat_live"' in agentcore
    assert 'name             = "live"' in agentcore
    assert (
        'resource "aws_lambda_provisioned_concurrency_config" "tollchat"' in agentcore
    )
    assert (
        "count                             = local.is_production ? 1 : 0" in agentcore
    )
    assert (
        "qualifier                         = aws_lambda_alias.tollchat_live.name"
        in agentcore
    )

    assert 'resource "aws_lambda_function_url" "public_chat"' in site
    assert 'authorization_type = "AWS_IAM"' in site
    assert 'invoke_mode        = "RESPONSE_STREAM"' in site
    assert "qualifier          = aws_lambda_alias.tollchat_live.name" in site
    assert 'origin_access_control_origin_type = "lambda"' in site
    assert 'origin_access_control_origin_type = "s3"' in site
    assert 'path_pattern             = "/api/*"' in site
    assert 'code    = file("${path.module}/../agent/public-api-gate.js")' in site
    assert "aliases             = local.domains" in site
    assert 'resource "aws_wafv2_web_acl" "public_chat"' in site
    assert "limit                 = local.rate_limit" in site
    assert "size                = 32768" in site
    assert 'resource "cloudflare_dns_record" "apex"' in site
    assert 'resource "cloudflare_dns_record" "www"' in site
    assert 'resource "aws_acm_certificate" "site"' in site


def test_public_report_surface_is_canonical_crawlable_and_isolated():
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    robots = (V2_ROOT / "agent" / "robots.txt").read_text()

    assert 'resource "aws_cloudfront_function" "public_report_routes"' in site
    assert 'code    = file("${path.module}/../agent/public-report-routes.js")' in site
    default_behavior = site.split("  default_cache_behavior {", maxsplit=1)[1].split(
        "  ordered_cache_behavior {", maxsplit=1
    )[0]
    assert "aws_cloudfront_function.public_report_routes.arn" in default_behavior
    api_behavior = site.split("  ordered_cache_behavior {", maxsplit=1)[1].split(
        "  web_acl_id", maxsplit=1
    )[0]
    assert "aws_cloudfront_function.public_chat_routes.arn" in api_behavior
    assert "aws_cloudfront_function.public_report_routes.arn" not in api_behavior

    robots_object = site.split('resource "aws_s3_object" "robots"', maxsplit=1)[
        1
    ].split('resource "aws_s3_object"', maxsplit=1)[0]
    assert 'key           = "robots.txt"' in robots_object
    assert 'source        = "${path.module}/../agent/robots.txt"' in robots_object
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
    assert "toll-v2-report-publisher" in DEPLOYMENT
    assert 'test "$(wc -l <"$REPORT_URLS")" -eq 685' in DEPLOYMENT
    assert (
        "Disabling publication does not withdraw existing report objects" in DEPLOYMENT
    )


def test_agent_measurement_is_count_only_private_and_bounded():
    measurement_path = V2_ROOT / "infra" / "agent_measurement.tf"
    assert measurement_path.exists()
    measurement = measurement_path.read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    bot = site.split('name     = "agent-report-bot-control"', maxsplit=1)[1].split(
        'name     = "allow-static-site"', maxsplit=1
    )[0]
    assert 'version     = "Version_6.1"' in bot
    assert 'inspection_level        = "COMMON"' in bot
    assert "override_action" in bot and "count {}" in bot
    assert 'search_string         = "/tolls/"' in bot
    assert "sampled_requests_enabled   = true" in bot
    assert "priority = 0" in bot
    assert (
        "priority = 7"
        in site.split('name     = "allow-static-site"', maxsplit=1)[1].split(
            'name     = "block-oversized-api-body"', maxsplit=1
        )[0]
    )

    assert 'toset(["cookie", "authorization", "referer"])' in site
    assert 'field_type = "QUERY_STRING"' in site
    assert site.count('action                     = "SUBSTITUTION"') >= 2

    assert (
        'agent_measurement_bucket   = "aws-waf-logs-tollchat-agent-reports-'
        in measurement
    )
    assert (
        'resource "aws_s3_bucket_public_access_block" "agent_measurement"'
        in measurement
    )
    assert 'resource "aws_kms_key" "agent_measurement"' in measurement
    assert "enable_key_rotation     = true" in measurement
    assert 'sse_algorithm     = "aws:kms"' in measurement
    assert "kms_master_key_id = aws_kms_key.agent_measurement.arn" in measurement
    assert "bucket_key_enabled = true" in measurement
    assert 'identifiers = ["delivery.logs.amazonaws.com"]' in measurement
    assert 'actions   = ["kms:GenerateDataKey*"]' in measurement
    assert 'encryption_option = "SSE_KMS"' in measurement
    assert (
        'resource "aws_wafv2_web_acl_logging_configuration" "agent_reports"'
        in measurement
    )
    assert 'default_behavior = "DROP"' in measurement
    assert 'behavior    = "KEEP"' in measurement
    assert "agent-route-report" in measurement
    assert measurement.count("days = 7") >= 2
    assert "enforce_workgroup_configuration    = true" in measurement
    assert "bytes_scanned_cutoff_per_query     = 1073741824" in measurement
    assert "/WAFLogs/cloudfront/tollchat-v2-public-chat/" in measurement
    assert "/WAFLogs/us-east-1/tollchat-v2-public-chat/" not in measurement
    assert '"glue:GetPartition"' in measurement
    assert 'schedule_expression = "cron(15 3 * * ? *)"' in measurement
    assert "evaluation_periods  = 2" in measurement
    assert "threshold           = 95" in measurement
    coverage_alarm = measurement.split(
        'resource "aws_cloudwatch_metric_alarm" "agent_usage_log_coverage"',
        maxsplit=1,
    )[1]
    assert 'treat_missing_data  = "notBreaching"' in coverage_alarm
    assert "usage.json" not in measurement


def test_agent_measurement_keeps_cloudflare_dns_only():
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    for resource in ('cloudflare_dns_record" "apex', 'cloudflare_dns_record" "www'):
        block = site.split(f'resource "{resource}"', maxsplit=1)[1].split(
            "\n}", maxsplit=1
        )[0]
        assert "proxied = false" in block
    assert 'resource "cloudflare_bot_management"' not in site


def test_agent_measurement_privacy_notice_precedes_logging():
    privacy = (V2_ROOT / "agent" / "privacy.txt").read_text()
    for text in (
        "seven days",
        "IP address",
        "AWS WAF",
        "published generation",
        "five minutes",
        "does not disable access or security logging",
    ):
        assert text in privacy
    measurement = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
    logging = measurement.split(
        'resource "aws_wafv2_web_acl_logging_configuration" "agent_reports"',
        maxsplit=1,
    )[1]
    assert "aws_s3_object.privacy" in logging


def test_agent_registry_and_rollup_outputs_are_privacy_safe():
    registry = [
        json.loads(line)
        for line in (V2_ROOT / "analytics" / "agent_registry.ndjson")
        .read_text()
        .splitlines()
    ]
    tokens = [entry["user_agent_token"].casefold() for entry in registry]
    assert len(tokens) == len(set(tokens))
    assert {entry["agent_mode"] for entry in registry} == {
        "search_crawler",
        "user_triggered_agent",
        "training_crawler",
    }
    assert all(entry["documentation_url"].startswith("https://") for entry in registry)

    rollup = (V2_ROOT / "lambdas" / "agent_usage_rollup" / "rollup.sql").read_text()
    completion = (
        V2_ROOT / "lambdas" / "agent_usage_rollup" / "complete.sql"
    ).read_text()
    latest = (
        V2_ROOT / "lambdas" / "agent_usage_rollup" / "latest_view.sql"
    ).read_text()
    assert "PARTITION BY httprequest.requestid" in rollup
    assert "httprequest.httpmethod = 'GET'" in rollup
    assert "report[.]json" in rollup
    assert "identity_confidence" in rollup
    assert "web_bot_auth:verified" in rollup
    assert "assistant-referrer-([^,]+)" in rollup
    assert "aws_vendor_family = declared_vendor_family" in rollup
    assert re.search(r"contains\(\s*marker[.]route_keys", rollup)
    assert "JOIN agent_report_generations marker" in rollup
    assert "LEFT JOIN agent_report_generations marker" not in rollup
    for forbidden in ("clientip", "args", "referer"):
        assert forbidden not in rollup.lower()
    measurement = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
    assert 'route_keys     = "array<string>"' in measurement
    assert "INSERT INTO agent_report_rollup_completions" in completion
    assert "JOIN latest" in latest
    assert "agent_report_rollups usage" in latest


def test_public_site_publishes_the_v2_ui_and_legal_assets():
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    page = (V2_ROOT / "agent" / "dev_chat.html").read_text()
    server = (V2_ROOT / "agent" / "dev_chat.py").read_text()

    assert re.search(r'key\s+= "index[.]html"', site)
    assert re.search(
        r'source\s+= "\$\{path[.]module\}/[.][.]/agent/dev_chat[.]html"', site
    )
    assert re.search(r'key\s+= "chat[.]mjs"', site)
    assert re.search(
        r'source\s+= "\$\{path[.]module\}/[.][.]/agent/public_chat[.]mjs"', site
    )
    for path in ("faq.html", "privacy.txt", "terms.txt"):
        assert path in site
    assert 'fileset("${path.module}/../agent/assets", "**")' in site
    assert re.search(r'key\s+= "assets/\$\{each[.]value\}"', site)
    assert (V2_ROOT / "agent" / "assets" / "tollchat-logo.png").exists()
    assert (V2_ROOT / "agent" / "assets" / "favicon.png").exists()
    assert 'href="/assets/favicon.png"' in page
    assert '"/assets/favicon.png"' in server
    assert '<script type="module" src="/chat.mjs"></script>' in page
    assert '"/chat.mjs"' in server
    assert 'key           = "usage.json"' in site
    assert 'content       = "{}"' in site
    assert 'id="usage-proof"' in page
    assert re.search(r'<p[^>]*id="usage-proof"[^>]*hidden', page)


def test_agent_referrer_rules_match_only_exact_url_authorities():
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    referrer_rules = site.split('dynamic "rule" {', maxsplit=1)[1].split(
        'rule {\n    name     = "agent-route-report"', maxsplit=1
    )[0]

    assert "regex_match_statement" in referrer_rules
    assert 'positional_constraint = "CONTAINS"' not in referrer_rules
    assert "^https?://([a-z0-9-]+[.])*" in site
    assert "(:[0-9]+)?([/?#]|$)" in site


def test_usage_publisher_is_daily_static_and_least_privilege():
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    assert 'resource "aws_lambda_function" "usage_publisher"' in site
    assert 'function_name = "tollchat-v2-usage-publisher"' in site
    assert 'schedule_expression = "cron(15 5 * * ? *)"' in site
    assert "maximum_event_age_in_seconds = 86400" in site
    assert "maximum_retry_attempts       = 185" in site
    assert 'metric_name         = "Errors"' in site
    assert 'metric_name         = "FailedInvocations"' in site

    policy = site.split('data "aws_iam_policy_document" "usage_publisher"', maxsplit=1)[
        1
    ].split('resource "aws_iam_role_policy" "usage_publisher"', maxsplit=1)[0]
    assert 'actions   = ["dynamodb:GetItem"]' in policy
    assert 'variable = "dynamodb:LeadingKeys"' in policy
    assert 'values   = ["usage#all"]' in policy
    assert 'actions   = ["s3:PutObject"]' in policy
    assert "${aws_s3_bucket.site.arn}/usage.json" in policy
    assert 'actions   = ["kms:Encrypt", "kms:GenerateDataKey"]' in policy
    assert "dynamodb:Scan" not in policy
    assert "s3:*" not in policy

    proxy_policy = agentcore.split(
        'data "aws_iam_policy_document" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "tollchat_proxy"', maxsplit=1)[0]
    assert '"dynamodb:TransactWriteItems"' in proxy_policy


def test_usage_rollout_has_no_retired_foundation_step():
    assert "usage-permissions.tfplan" not in DEPLOYMENT
    assert "usage-prerequisites.tfplan" not in DEPLOYMENT
    assert "Do not use Terraform resource targets" in DEPLOYMENT
    assert "iam get-role-policy" in DEPLOYMENT
    assert "dynamodb:TransactWriteItems" in DEPLOYMENT
    assert "tollchat_usage_optout=1" in DEPLOYMENT
    assert "--consistent-read" in DEPLOYMENT
    assert "must be unchanged" in DEPLOYMENT


def test_metrics_aware_rollback_preserves_the_aggregate():
    rollback = DEPLOYMENT.split("## Rollback", maxsplit=1)[1]
    assert "events disable-rule" in rollback
    assert "usage publisher" in rollback
    assert "usage#all" in rollback
    assert re.search(r"proxy and\s+public site together", rollback)


def test_v2_agent_packages_are_required_for_real_deployments():
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    build = V2_ROOT / "scripts" / "build_agentcore_zips.sh"
    assert 'variable "agentcore_package_path"' in variables
    assert 'variable "chat_proxy_package_path"' in variables
    assert "AgentCore deployment requires the reviewed v2 runtime package" in agentcore
    assert "Chat proxy deployment requires the reviewed v2 proxy package" in agentcore
    assert build.exists()


def test_public_openai_egress_has_a_narrow_expiring_trivy_exception():
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


def test_eventbridge_has_both_failure_paths_and_bounded_retries():
    assert 'detail-type = ["Object Created"]' in MAIN_TF
    assert '{ prefix = "raw/feed=i95/" }' in MAIN_TF
    assert '{ prefix = "raw/feed=i66/" }' in MAIN_TF
    assert "maximum_event_age_in_seconds = 86400" in MAIN_TF
    assert "maximum_retry_attempts       = 185" in MAIN_TF
    assert 'resource "aws_sqs_queue" "invoke_failure"' in MAIN_TF
    assert 'resource "aws_sqs_queue" "delivery_failure"' in MAIN_TF
    assert 'resource "aws_vpc_endpoint" "eventbridge"' in FOUNDATION_AGENTCORE
    assert (
        'resource "aws_vpc_security_group_egress_rule" "loader_to_eventbridge"'
        in MAIN_TF
    )


def test_loader_network_and_data_access_are_scoped():
    assert "${data.aws_s3_bucket.raw.arn}/*" not in MAIN_TF
    assert '"${data.aws_s3_bucket.raw.arn}/raw/feed=i95/*"' in MAIN_TF
    assert '"${data.aws_s3_bucket.raw.arn}/raw/feed=i66/*"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_rds"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_s3"' in MAIN_TF


def test_report_publisher_is_event_driven_bounded_and_least_privilege():
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    assert 'variable "publisher_package_path"' in variables
    assert 'function_name = "toll-v2-report-publisher${local.suffix}"' in MAIN_TF
    assert 'schedule_expression = "cron(5/10 * * * ? *)"' in MAIN_TF
    assert '"tollchat.pricing-loader"' in MAIN_TF
    assert '"I95 Pricing Load Committed"' in MAIN_TF
    assert "${local.database_roles.publisher}" in MAIN_TF
    assert re.search(r"DB_USER\s+= local.database_roles.publisher", MAIN_TF)
    assert 'resource "aws_vpc_security_group_egress_rule" "publisher_to_rds"' in MAIN_TF
    policy = MAIN_TF.split('data "aws_iam_policy_document" "publisher"', maxsplit=1)[
        1
    ].split('resource "aws_iam_role_policy" "publisher"', maxsplit=1)[0]
    assert 'actions   = ["s3:GetObject"]' in policy
    assert "tolls/i95-i495/manifest.json" in policy
    assert 'actions   = ["s3:ListBucket"]' in policy
    assert 'variable = "s3:prefix"' in policy
    assert 'values   = ["tolls/i95-i495/manifest.json"]' in policy
    assert re.search(r'actions\s+= \["s3:PutObject"\]', policy)
    assert "tolls/i95-i495/*" in policy
    assert "sitemap.xml" in policy
    assert 'actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]' in policy
    assert "s3:DeleteObject" not in policy
    assert 'resource "aws_vpc_security_group_egress_rule" "publisher_to_s3"' in MAIN_TF
    publisher_lambda = MAIN_TF.split(
        'resource "aws_lambda_function" "publisher"', maxsplit=1
    )[1].split(
        'resource "aws_lambda_function_event_invoke_config" "publisher"', maxsplit=1
    )[0]
    assert "timeout       = 600" in publisher_lambda
    assert 'REPORT_PUBLICATION_ENABLED = "true"' in publisher_lambda
    assert "SITE_BUCKET_NAME           = aws_s3_bucket.site.id" in publisher_lambda
    assert "reserved_concurrent_executions = 1" in publisher_lambda
    assert "aws_cloudfront_distribution.site" in publisher_lambda
    assert "aws_iam_role_policy.publisher" in publisher_lambda
    assert "aws_s3_object.robots" in publisher_lambda
    assert (
        'pattern        = "[..., event=\\"V2_REPORT_GENERATION_OK\\", facility, generation_id, route_count]"'
        in MAIN_TF
    )
    assert "evaluation_periods  = 3" in MAIN_TF
    assert "period              = 600" in MAIN_TF
    assert 'treat_missing_data  = "breaching"' in MAIN_TF
    assert (V2_ROOT / "scripts" / "build_publisher_zip.sh").exists()
    assert "./scripts/build_publisher_zip.sh" in CI_WORKFLOW


def test_timed_ci_uses_the_internal_pricing_caller():
    policy = MAIN_TF.split('data "aws_iam_policy_document" "timed_checks"', maxsplit=1)[
        1
    ].split('resource "aws_iam_role_policy" "timed_checks"', maxsplit=1)[0]

    assert 'name               = "nova-toll-v2-timed-checks${local.suffix}"' in MAIN_TF
    assert 'actions   = ["rds:DescribeDBInstances"]' in policy
    assert 'actions   = ["rds-db:connect"]' in policy
    assert "/${local.database_roles.pricing_caller}" in policy
    assert "/tollchat_agent" not in policy
    assert 'actions   = ["ssm:GetParameter"]' in policy
    assert (
        'resources = ["arn:aws:ssm:${data.aws_region.current.region}:'
        "${data.aws_caller_identity.current.account_id}:parameter/nova-toll/"
        'openai_api_key"]'
    ) in policy
    assert "ssm:GetParameters" not in policy
    assert "/pricing_reader" not in policy
    assert "role/nova-toll-v2-timed-checks" in TIMED_CHECKS_WORKFLOW
    assert "role/nova-toll-github-ci" not in TIMED_CHECKS_WORKFLOW


def test_timed_ci_skips_stale_scheduled_runs():
    schedules = re.findall(r'cron: "([^"]+)"', TIMED_SCHEDULE_WORKFLOW)
    assert all(schedule.split()[-1].isdigit() for schedule in schedules)
    assert "schedule: ${{ github.event.schedule || '' }}" in TIMED_SCHEDULE_WORKFLOW
    assert "TIMED_SCHEDULE: ${{ inputs.schedule }}" in TIMED_CHECKS_WORKFLOW
    assert 'python3 scripts/check_timed_window.py "$TIMED_SCHEDULE"' in (
        TIMED_CHECKS_WORKFLOW
    )


def test_timed_ci_checks_agent_pricing_tool_in_every_scheduled_state():
    for window_id in ("i95_northbound", "i95_reversal", "i95_southbound"):
        assert f"- {window_id}" in TIMED_SCHEDULE_WORKFLOW
        assert f'window_id="{window_id}"' in TIMED_SCHEDULE_WORKFLOW
        assert f'"{window_id}":' in TIMED_ROUTE_TEST
    for window_id in ("greenway_eb_peak", "greenway_wb_peak"):
        assert f"- {window_id}" in TIMED_SCHEDULE_WORKFLOW
        assert f'window_id="{window_id}"' in TIMED_SCHEDULE_WORKFLOW

    assert "tests/test_validate_toll_route_live.py" in TIMED_CHECKS_WORKFLOW
    assert "tests/test_get_annual_toll_ballpark_live.py" in TIMED_CHECKS_WORKFLOW
    assert "get_current_toll_price" in TIMED_ROUTE_TEST
    assert "get_annual_toll_ballpark" in TIMED_BALLPARK_TEST
    assert "route_validation.validate_toll_route" not in TIMED_ROUTE_TEST
    assert "eval/run_evaluation.py --check" in CI_WORKFLOW
    assert 'eval/run_evaluation.py --window "$TIMED_WINDOW_ID"' in TIMED_CHECKS_WORKFLOW
    assert "TollChat timed evaluation" in TIMED_CHECKS_WORKFLOW
    assert "test_live_i95_northbound_restart_is_state_independent" in TIMED_ROUTE_TEST
    assert "OPENAI_API_KEY" not in TIMED_CHECKS_WORKFLOW


def test_timed_ci_covers_three_real_i95_states_monday_through_saturday():
    expected = {
        1: {
            "i95_northbound": "17 6",
            "i95_reversal": "17 11",
            "i95_southbound": "17 14",
        },
        2: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        3: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        4: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        5: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        6: {
            "i95_northbound": "17 18",
            "i95_reversal": "17 15",
            "i95_southbound": "17 10",
        },
    }

    for weekday, windows in expected.items():
        schedules = [f"{clock} * * {weekday}" for clock in windows.values()]
        assert len(schedules) == len(set(schedules)) == 3
        for schedule in schedules:
            assert TIMED_SCHEDULE_WORKFLOW.count(f'cron: "{schedule}"') == 1
        for window_id, clock in windows.items():
            schedule = f"{clock} * * {weekday}"
            assert re.search(
                rf'^.*"{re.escape(schedule)}".*window_id="{window_id}"',
                TIMED_SCHEDULE_WORKFLOW,
                re.MULTILINE,
            )

    assert not re.search(r'cron: "[^\"]+ \* \* 0"', TIMED_SCHEDULE_WORKFLOW)


def test_timed_ci_checks_both_greenway_peak_windows():
    for window_id in ("greenway_eb_peak", "greenway_wb_peak"):
        assert f"- {window_id}" in TIMED_SCHEDULE_WORKFLOW
        assert f'window_id="{window_id}"' in TIMED_SCHEDULE_WORKFLOW
        assert f'"{window_id}":' in TIMED_ROUTE_TEST

    for weekday in range(1, 6):
        assert f'cron: "23 7 * * {weekday}"' in TIMED_SCHEDULE_WORKFLOW
        assert f'cron: "23 17 * * {weekday}"' in TIMED_SCHEDULE_WORKFLOW

    assert "test_live_greenway_peak_price" in TIMED_ROUTE_TEST
    assert "if: startsWith(inputs.window_id, 'i95_')" not in TIMED_CHECKS_WORKFLOW

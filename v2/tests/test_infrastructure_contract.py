import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml

V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
MAIN_TF = (V2_ROOT / "infra" / "main.tf").read_text()
PUBLISHER_HANDLER = (V2_ROOT / "lambdas" / "publisher" / "handler.py").read_text()
ENVIRONMENT_TF = (V2_ROOT / "infra" / "environment.tf").read_text()
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
FOUNDATION_PROVIDER = (FOUNDATION_ROOT / "providers.tf").read_text()
FOUNDATION_TAILSCALE = (FOUNDATION_ROOT / "tailscale.tf").read_text()
FOUNDATION_BUDGET = FOUNDATION_ROOT / "budget.tf"
APPLICATION_VARIABLES = (V2_ROOT / "infra" / "variables.tf").read_text()
DEPLOYMENT = (V2_ROOT / "RUNBOOK.md").read_text()
AGENTS = (REPO_ROOT / "AGENTS.md").read_text()
ACCOUNT_CONTRACT = json.loads(
    (REPO_ROOT / "infra" / "account-contract.json").read_text()
)
LEGACY_DEVELOPMENT_INVENTORY = (
    REPO_ROOT / "infra" / "legacy-development-inventory.md"
).read_text()


def terraform_block(source: str, header: str) -> str:
    """Return one top-level Terraform block, excluding the following block."""
    remainder = source.split(header, maxsplit=1)[1]
    following = re.search(r"\n(?:resource|data) ", remainder)
    return remainder[: following.start()] if following else remainder


def assert_assignment(block: str, name: str, value: str) -> None:
    assert re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*{re.escape(value)}\s*$", block)


def test_account_contract_records_the_replacement_development_boundary():
    accounts = ACCOUNT_CONTRACT["accounts"]
    assert ACCOUNT_CONTRACT["region"] == "us-east-1"
    assert accounts["management"]["id"] == "407645373626"
    assert accounts["production"] == {
        "name": "nova-toll-prod",
        "id": "920534282028",
        "ownership": "account-local",
    }
    assert accounts["development"] == {
        "name": "nova-toll-prod",
        "id": "920534282028",
        "ownership": "application-state",
        "backend_key": "nova-toll/v2/development/terraform.tfstate",
        "tfvars": "v2/infra/development.tfvars",
    }
    shared_access = ACCOUNT_CONTRACT["shared_access"]
    assert shared_access["production"] == {
        "ownership": "application-state",
        "backend_key": "nova-toll/v2/terraform.tfstate",
        "tfvars": "v2/infra/production.tfvars",
    }
    assert "not an AWS shared-read grant" in shared_access["cloudflare_dns"]


def test_legacy_development_inventory_hands_cleanup_to_issue_333():
    for text in (
        "920534282028",
        "nova-toll/v2/development/terraform.tfstate",
        "point-in-time, read-only",
        "authoritative cleanup input for\n#333, not a destruction plan",
        "5 Lambda functions",
        "1 AgentCore runtime and 1 endpoint",
        "1 DynamoDB table",
        "2 S3 buckets and 25 managed S3 objects",
        "1 CloudFront distribution",
        "1 API Gateway REST API/stage",
        "1 WAF ACL",
        "4 SQS queues",
        "7 IAM roles",
        "4 security groups with 13 managed rules",
        "5 EventBridge rules/targets",
        "7 log groups",
        "20 alarms",
        "Athena/Glue reporting resources",
        "77 resources tagged `environment=development`",
        "incomplete cross-check",
        "unverified targets",
    ):
        assert text in LEGACY_DEVELOPMENT_INVENTORY
    assert "not independent buckets" in LEGACY_DEVELOPMENT_INVENTORY
    assert (
        "future, non-operative migration context"
        in (V2_ROOT / "plans" / "ENVIRONMENT-AND-RELEASE-PLAN.md").read_text()
    )


def test_foundation_budget_preserves_the_production_notification_contract():
    budget = FOUNDATION_BUDGET.read_text()
    variables = (FOUNDATION_ROOT / "variables.tf").read_text()

    assert 'variable "budget_notification_email"' in variables
    email_variable = variables.split('variable "budget_notification_email"', 1)[1]
    assert re.search(r"type\s+= string", email_variable)
    assert re.search(r"sensitive\s+= true", email_variable)
    assert "default" not in email_variable.split("}", 1)[0]
    assert 'resource "aws_budgets_budget" "nova_toll_monthly"' in budget
    for attribute, value in (
        ("account_id", '"920534282028"'),
        ("name", '"nova-toll-monthly"'),
        ("budget_type", '"COST"'),
        ("limit_amount", '"100"'),
        ("limit_unit", '"USD"'),
        ("time_unit", '"MONTHLY"'),
        ("subscriber_email_addresses", r"\[var\.budget_notification_email\]"),
    ):
        assert re.search(rf"{attribute}\s*=\s*{value}", budget)
    assert budget.count("notification {") == 3
    assert budget.count('comparison_operator        = "GREATER_THAN"') == 3
    assert budget.count('threshold_type             = "PERCENTAGE"') == 3
    assert (
        budget.count("subscriber_email_addresses = [var.budget_notification_email]")
        == 3
    )
    assert "SNS" not in budget
    assert "@" not in budget
    tuples = {
        (notification_type, threshold)
        for notification_type, threshold in re.findall(
            r'notification_type\s*=\s*"(ACTUAL|FORECASTED)".*?threshold\s*=\s*(\d+)',
            budget,
            flags=re.DOTALL,
        )
    }
    assert tuples == {("ACTUAL", "80"), ("FORECASTED", "80"), ("ACTUAL", "100")}


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


def test_shared_foundation_and_router_volume_are_tagged_shared():
    assert 'environment = "shared"' in FOUNDATION_PROVIDER
    assert 'shared_with = "development"' in FOUNDATION_PROVIDER
    volume_tags = FOUNDATION_TAILSCALE.split("volume_tags = {", maxsplit=1)[1]
    for tag in (
        'project     = "nova-toll-budget-agent"',
        'environment = "shared"',
        'shared_with = "development"',
    ):
        assert tag in volume_tags
    environment = APPLICATION_VARIABLES.split('variable "environment"', 1)[1].split(
        'variable "enable_public_dns"', 1
    )[0]
    assert 'contains(["development", "production"], var.environment)' in environment
    assert '"shared"' not in environment


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
        "Schema-changing work is not deployable until approved deployed-migration",
    ):
        assert text in AGENTS
    for text in (
        "PRs use disposable PostGIS migration validation only",
        "## Guarded Oracle migration",
        "deploy_oracle_migration.py development",
        "deploy_oracle_migration.py production",
        "backup/PITR incident handling",
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
    assert "tollchat-v2-anonymous-sessions-dev" in endpoint
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
        "webacl:tollchat-v2-public-chat${local.suffix}:agent-route-report"
        in measurement
    )
    assert (
        'WAF_WEB_ACL_METRIC    = "tollchat-v2-public-chat${local.suffix}"'
        in measurement
    )
    assert (
        'WAF_ROUTE_RULE_METRIC = "tollchat-v2-agent-route-report${local.suffix}"'
        in measurement
    )
    assert (
        'agent_measurement_acl      = "tollchat-v2-public-chat${local.suffix}"'
        in measurement
    )
    assert "TOLLCHAT_ENVIRONMENT = var.environment" in measurement
    assert (
        "local.is_production ? null : { Environment = var.environment }" in measurement
    )
    assert "WAFLogs/cloudfront/${local.agent_measurement_acl}/" in measurement
    assert (
        'resource "aws_cloudfront_response_headers_policy" "development_noindex"'
        in site
    )
    assert "count = local.is_production ? 0 : 1" in site
    assert 'header   = "X-Robots-Tag"' in site
    assert 'value    = "noindex"' in site


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
    assert 'toset(["DEFAULT", "preview"])' in runtime_logs
    assert "retention_in_days = local.is_production ? 1 : 7" in runtime_logs

    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_api_gateway_rest_api"', maxsplit=1)[0]
    assert "ignore_changes = [reserved_concurrent_executions]" in proxy
    assert "aws_iam_role_policy.tollchat_proxy" in proxy

    assert "put-function-concurrency" not in DEPLOYMENT


def test_v2_public_edge_reuses_the_runtime_and_keeps_one_proxy_warm():
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_api_gateway_rest_api"', maxsplit=1)[0]
    assert "publish                        = true" in proxy
    assert "reserved_concurrent_executions = 5" in proxy
    assert agentcore.count('metric_name         = "V2ProxyFailure${local.suffix}"') == 1
    assert agentcore.count('name      = "V2ProxyFailure${local.suffix}"') == 1
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
    assert 'test "$(wc -l <"$REPORT_URLS")" -eq 685' in DEPLOYMENT
    assert (
        "Disabling publication does not withdraw existing report objects" in DEPLOYMENT
    )


def test_public_report_launch_is_selected_environment_and_correlated():
    launch = DEPLOYMENT.split("## Public report launch", 1)[1].split(
        "## Agent-route measurement launch", 1
    )[0]
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
        'schema_version == "2.0.0"',
        'publication_format_version == "2.0.0"',
        "route_count == 685",
        'test("^[a-f0-9]{64}$")',
        "trap 'rm -f --",
    ):
        assert required in launch
    assert "https://tollchat.ai" not in launch

    shell_match = re.search(r"```sh\n(.*?)\n```", launch, re.DOTALL)
    if shell_match is None:
        raise AssertionError("missing public report launch shell block")
    shell = shell_match.group(1)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
        script.write(shell)
        script.flush()
        assert subprocess.run(["bash", "-n", script.name], check=False).returncode == 0

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
                        f'set -euo pipefail; {manifest_check}; report_manifest_is_valid "$REPORT_MANIFEST"',
                    ],
                    check=False,
                    env={**os.environ, "REPORT_MANIFEST": fixture.name},
                ).returncode
                == 0
            )

    manifest: dict[str, object] = {
        "schema_version": "2.0.0",
        "publication_format_version": "2.0.0",
        "route_count": 685,
        "generation_id": "old-generation",
        "published_at": "2026-08-01T00:00:00Z",
        "result_sha256": "a" * 64,
    }
    assert manifest_passes(manifest)
    assert not manifest_passes({**manifest, "generation_id": ""})
    assert not manifest_passes({**manifest, "result_sha256": "A" * 64})


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
    assert "/WAFLogs/cloudfront/${local.agent_measurement_acl}/" in measurement
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


def test_same_account_release_contract_and_gates_reject_disallowed_plans():
    for text in (
        "AWS_PROFILE=nova-toll-prod",
        'get-caller-identity --query Account --output text)" = "920534282028"',
        "backend.development.hcl",
        "development.tfvars",
        "backend.production.hcl",
        "production.tfvars",
        "development-release.tfplan",
        "production-release.tfplan",
        "Build the four reviewed inputs once",
        "development first",
        "-reconfigure",
        "-lock=false",
    ):
        assert text in DEPLOYMENT
    assert DEPLOYMENT.index("### Guarded development release") < DEPLOYMENT.index(
        "### Guarded production release"
    )
    assert "903859731897" not in DEPLOYMENT
    assert "terraform workspace" not in DEPLOYMENT
    assert "terraform -target" not in DEPLOYMENT

    gates = [
        re.search(
            r"development-release\.tfplan \| jq -e '\n(.*?)'\nAWS_PROFILE",
            DEPLOYMENT,
            re.DOTALL,
        ),
        re.search(
            r"production-release\.tfplan \| jq -e '\n(.*?)'\nAWS_PROFILE",
            DEPLOYMENT,
            re.DOTALL,
        ),
    ]
    assert all(gates)
    gate_programs = [gate.group(1) for gate in gates if gate is not None]
    assert len(gate_programs) == 2

    def outcomes(plan: object) -> list[bool]:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as fixture:
            json.dump(plan, fixture)
            fixture.flush()
            return [
                subprocess.run(["jq", "-e", gate, fixture.name], check=False).returncode
                == 0
                for gate in gate_programs
            ]

    def change(mode: str, address: str, actions: list[str]) -> dict[str, object]:
        return {"mode": mode, "address": address, "change": {"actions": actions}}

    creates = [
        "aws_iam_role.publisher_scheduler",
        "aws_iam_role_policy.publisher_scheduler",
        "aws_scheduler_schedule.publisher",
    ]
    updates = [
        "aws_bedrockagentcore_agent_runtime.tollchat",
        "aws_bedrockagentcore_agent_runtime_endpoint.tollchat",
        "aws_cloudwatch_metric_alarm.report_generation_freshness",
        "aws_iam_role_policy.publisher",
        "aws_iam_role_policy.tollchat_proxy",
        "aws_iam_role_policy.tollchat_runtime",
        "aws_lambda_function.publisher",
        "aws_s3_object.agentcore",
        "aws_s3_object.usage",
    ]
    deletes = [
        "aws_cloudwatch_event_rule.committed_i95_loads",
        "aws_cloudwatch_event_rule.report_watchdog",
        "aws_cloudwatch_event_target.publisher_load_event",
        "aws_cloudwatch_event_target.publisher_watchdog",
        'aws_cloudwatch_metric_alarm.publisher_failed_invocations["load_success"]',
        'aws_cloudwatch_metric_alarm.publisher_failed_invocations["watchdog"]',
        "aws_lambda_permission.publisher_load_event",
        "aws_lambda_permission.publisher_watchdog",
        "aws_sqs_queue_policy.publisher_delivery_failure",
    ]
    reads = [
        "data.aws_iam_policy_document.publisher_scheduler",
        "data.aws_iam_policy_document.tollchat_proxy",
        "data.aws_iam_policy_document.tollchat_runtime",
    ]
    assert all(
        outcomes(
            {
                "resource_changes": [
                    *(change("managed", address, ["create"]) for address in creates),
                    *(change("managed", address, ["update"]) for address in updates),
                    *(change("managed", address, ["delete"]) for address in deletes),
                    *(change("data", address, ["read"]) for address in reads),
                ]
            }
        )
    )
    assert all(
        outcomes({"resource_changes": [change("managed", "anything", ["no-op"])]})
    )
    malformed_plans: tuple[object, ...] = (
        {},
        {"resource_changes": None},
        {"resource_changes": {}},
        {"resource_changes": [{"mode": "managed", "address": "anything"}]},
        {"resource_changes": [change("managed", "anything", [])]},
    )
    for malformed in malformed_plans:
        assert not any(outcomes(malformed))
    assert not any(
        outcomes(
            {
                "resource_changes": [
                    change("managed", "aws_s3_bucket.unapproved", ["update"])
                ]
            }
        )
    )
    for plan in (
        {
            "resource_changes": [
                change("managed", "infra.aws_s3_bucket.state", ["update"])
            ]
        },
        {"resource_changes": [change("managed", "aws_db_instance.main", ["update"])]},
        {
            "resource_changes": [
                change("managed", "aws_lambda_function.publisher", ["create"])
            ]
        },
        {
            "resource_changes": [
                change("managed", "aws_lambda_function.publisher", ["delete", "create"])
            ]
        },
        {
            "resource_changes": [
                change("managed", "aws_lambda_function.publisher", ["create", "delete"])
            ]
        },
    ):
        assert not any(outcomes(plan))
    assert not any(
        outcomes(
            {
                "resource_changes": [
                    change("managed", "aws_s3_object.tollchat_proxy", ["update"])
                ]
            }
        )
    )


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
    assert 'function_name = "tollchat-v2-usage-publisher${local.suffix}"' in site
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
    assert "iam get-role-policy" not in DEPLOYMENT
    assert "dynamodb:TransactWriteItems" not in DEPLOYMENT
    assert "tollchat_usage_optout=1" in DEPLOYMENT
    assert "--consistent-read" in DEPLOYMENT
    assert "must be unchanged" in DEPLOYMENT


def test_metrics_aware_rollback_preserves_the_aggregate():
    rollback = DEPLOYMENT.split("## Rollback", maxsplit=1)[1]
    assert "scheduler get-schedule" in rollback
    assert "scheduler update-schedule" in rollback
    assert "--state DISABLED" in rollback
    assert "--state ENABLED" in rollback
    assert rollback.count("trap 'rm -f --") == 2
    assert rollback.count("SCHEDULE_GROUP=") >= 2
    assert 'SCHEDULE_GROUP="default"' not in rollback
    assert "toll-v2-committed-i95-loads" not in rollback
    assert "toll-v2-report-watchdog" not in rollback
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
    raw_rule = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_event_rule" "raw_objects"'
    )
    loader_target = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_event_target" "loader"'
    )
    loader_permission = terraform_block(
        MAIN_TF, 'resource "aws_lambda_permission" "eventbridge_invoke"'
    )
    loader_invoke = terraform_block(
        MAIN_TF, 'resource "aws_lambda_function_event_invoke_config" "loader"'
    )
    loader_invoke_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "invoke_failure"'
    )
    loader_delivery_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "delivery_failure"'
    )
    loader_delivery_policy = terraform_block(
        MAIN_TF, 'data "aws_iam_policy_document" "delivery_failure"'
    )
    loader_error_alarm = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "loader_errors"'
    )
    loader_freshness_alarm = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "freshness"'
    )
    loader_failure_alarms = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "failure_queues"'
    )
    assert_assignment(raw_rule, "source", '["aws.s3"]')
    assert_assignment(raw_rule, "detail-type", '["Object Created"]')
    assert '{ prefix = "raw/feed=i95/" }' in raw_rule
    assert '{ prefix = "raw/feed=i66/" }' in raw_rule
    assert_assignment(
        loader_permission, "function_name", "aws_lambda_function.loader.function_name"
    )
    assert_assignment(loader_permission, "principal", '"events.amazonaws.com"')
    assert_assignment(
        loader_permission, "source_arn", "aws_cloudwatch_event_rule.raw_objects.arn"
    )
    assert_assignment(
        loader_target, "rule", "aws_cloudwatch_event_rule.raw_objects.name"
    )
    assert_assignment(loader_target, "arn", "aws_lambda_function.loader.arn")
    assert_assignment(loader_target, "maximum_event_age_in_seconds", "86400")
    assert_assignment(loader_target, "maximum_retry_attempts", "185")
    assert_assignment(loader_target, "arn", "aws_sqs_queue.delivery_failure.arn")
    assert_assignment(
        loader_invoke, "function_name", "aws_lambda_function.loader.function_name"
    )
    assert_assignment(loader_invoke, "maximum_retry_attempts", "2")
    assert_assignment(loader_invoke, "maximum_event_age_in_seconds", "21600")
    assert_assignment(loader_invoke, "destination", "aws_sqs_queue.invoke_failure.arn")
    for queue in (loader_invoke_queue, loader_delivery_queue):
        assert_assignment(queue, "sqs_managed_sse_enabled", "true")
        assert_assignment(queue, "message_retention_seconds", "1209600")
    assert_assignment(
        loader_delivery_policy, "resources", "[aws_sqs_queue.delivery_failure.arn]"
    )
    assert_assignment(loader_delivery_policy, "identifiers", '["events.amazonaws.com"]')
    assert_assignment(
        loader_delivery_policy, "values", "[aws_cloudwatch_event_rule.raw_objects.arn]"
    )
    for alarm in (loader_error_alarm, loader_freshness_alarm, loader_failure_alarms):
        assert_assignment(alarm, "alarm_actions", "local.alarm_actions")
    assert_assignment(loader_error_alarm, "namespace", '"AWS/Lambda"')
    assert_assignment(loader_error_alarm, "metric_name", '"Errors"')
    assert_assignment(
        loader_error_alarm,
        "dimensions",
        "{ FunctionName = aws_lambda_function.loader.function_name }",
    )
    assert_assignment(loader_error_alarm, "statistic", '"Sum"')
    assert_assignment(loader_error_alarm, "period", "300")
    assert_assignment(loader_error_alarm, "evaluation_periods", "1")
    assert_assignment(loader_error_alarm, "threshold", "1")
    assert_assignment(
        loader_error_alarm, "comparison_operator", '"GreaterThanOrEqualToThreshold"'
    )
    assert_assignment(loader_error_alarm, "treat_missing_data", '"notBreaching"')
    assert_assignment(loader_freshness_alarm, "namespace", '"NovaToll"')
    assert_assignment(loader_freshness_alarm, "metric_name", '"V2LoadSuccess"')
    assert_assignment(
        loader_freshness_alarm,
        "dimensions",
        "local.is_production ? { feed = each.key } : { feed = each.key, Environment = var.environment }",
    )
    assert_assignment(loader_freshness_alarm, "statistic", '"Sum"')
    assert_assignment(loader_freshness_alarm, "period", "600")
    assert_assignment(loader_freshness_alarm, "evaluation_periods", "3")
    assert_assignment(loader_freshness_alarm, "threshold", "1")
    assert_assignment(
        loader_freshness_alarm, "comparison_operator", '"LessThanThreshold"'
    )
    assert_assignment(loader_freshness_alarm, "treat_missing_data", '"breaching"')
    assert_assignment(loader_failure_alarms, "invoke", "aws_sqs_queue.invoke_failure")
    assert_assignment(
        loader_failure_alarms, "delivery", "aws_sqs_queue.delivery_failure"
    )
    assert_assignment(loader_failure_alarms, "namespace", '"AWS/SQS"')
    assert_assignment(
        loader_failure_alarms, "metric_name", '"ApproximateNumberOfMessagesVisible"'
    )
    assert_assignment(
        loader_failure_alarms, "dimensions", "{ QueueName = each.value.name }"
    )
    assert_assignment(loader_failure_alarms, "statistic", '"Maximum"')
    assert_assignment(loader_failure_alarms, "period", "300")
    assert_assignment(loader_failure_alarms, "evaluation_periods", "1")
    assert_assignment(loader_failure_alarms, "threshold", "1")
    assert_assignment(
        loader_failure_alarms,
        "comparison_operator",
        '"GreaterThanOrEqualToThreshold"',
    )
    assert_assignment(loader_failure_alarms, "treat_missing_data", '"notBreaching"')
    assert 'resource "aws_vpc_endpoint" "eventbridge"' in FOUNDATION_AGENTCORE
    assert (
        'resource "aws_vpc_security_group_egress_rule" "loader_to_eventbridge"'
        in MAIN_TF
    )
    collector = terraform_block(
        FOUNDATION_TRIGGERS,
        'resource "aws_cloudwatch_event_rule" "poll_tick"',
    )
    raw_notification = terraform_block(
        FOUNDATION_TRIGGERS,
        'resource "aws_s3_bucket_notification" "raw"',
    )
    assert_assignment(collector, "schedule_expression", '"cron(0/10 * * * ? *)"')
    assert_assignment(raw_notification, "eventbridge", "true")


def test_loader_network_and_data_access_are_scoped():
    assert "${data.aws_s3_bucket.raw.arn}/*" not in MAIN_TF
    assert '"${data.aws_s3_bucket.raw.arn}/raw/feed=i95/*"' in MAIN_TF
    assert '"${data.aws_s3_bucket.raw.arn}/raw/feed=i66/*"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_rds"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_s3"' in MAIN_TF


def test_report_publisher_is_weekly_bounded_and_least_privilege():
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    assert 'variable "publisher_package_path"' in variables
    assert 'function_name = "toll-v2-report-publisher${local.suffix}"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "publisher_to_rds"' in MAIN_TF
    policy = terraform_block(MAIN_TF, 'data "aws_iam_policy_document" "publisher"')
    rds_resources = re.search(
        r'(?s)sid\s*=\s*"ConnectRdsIam"\s+actions\s*=\s*\["rds-db:connect"\]\s+'
        r"resources\s*=\s*\[(.*?)\]",
        policy,
    )
    assert rds_resources
    assert re.findall(r'"([^"]+)"', rds_resources.group(1)) == [
        "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/${local.database_roles.publisher}",
        "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.main.resource_id}/${local.database_roles.reader}",
    ]
    assert "*" not in rds_resources.group(1)
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
    assert "timeout       = 900" in publisher_lambda
    assert "memory_size   = 2048" in publisher_lambda
    assert re.search(r"DB_USER\s+= local.database_roles.publisher", publisher_lambda)
    assert re.search(
        r"DB_READER_USER\s+= local.database_roles.reader", publisher_lambda
    )
    assert 'REPORT_PUBLICATION_ENABLED = "true"' in publisher_lambda
    assert "SITE_BUCKET_NAME           = aws_s3_bucket.site.id" in publisher_lambda
    assert "reserved_concurrent_executions = 1" in publisher_lambda
    assert "aws_cloudfront_distribution.site" in publisher_lambda
    assert "aws_iam_role_policy.publisher" in publisher_lambda
    assert "aws_s3_object.robots" in publisher_lambda
    assert (
        'resource "aws_cloudwatch_log_metric_filter" "report_generation_success"'
        not in MAIN_TF
    )
    assert "cloudwatch:PutMetricData" not in MAIN_TF
    assert "put_metric_data" not in PUBLISHER_HANDLER
    assert "print(" in PUBLISHER_HANDLER
    assert '"Timestamp": int(marker.timestamp() * 1000)' in PUBLISHER_HANDLER
    assert "_weekly_run_at(invoked_at)" in PUBLISHER_HANDLER
    assert 'local.is_production ? "[..., event=\\"V2_LOAD_OK\\", feed]"' in MAIN_TF
    assert "TOLLCHAT_ENVIRONMENT = var.environment" in MAIN_TF
    assert "}, local.is_production ? {} : {" in publisher_lambda
    assert 'PUBLIC_BASE_URL      = "https://${local.domains[0]}"' in publisher_lambda
    freshness_alarm = MAIN_TF.split(
        'resource "aws_cloudwatch_metric_alarm" "report_generation_freshness"',
        maxsplit=1,
    )[1].split('resource "aws_cloudwatch_metric_alarm" "publisher_errors"', 1)[0]
    assert "trailing seven-day sliding window" in freshness_alarm
    assert (
        'alarm_name          = "toll-v2-report-generation-freshness${local.suffix}"'
        in freshness_alarm
    )
    assert 'namespace           = "NovaToll"' in freshness_alarm
    assert 'metric_name         = "V2ReportGenerationSuccess"' in freshness_alarm
    assert "period              = 86400" in freshness_alarm
    assert "evaluation_periods  = 7" in freshness_alarm
    assert "datapoints_to_alarm = 7" in freshness_alarm
    assert 'statistic           = "Sum"' in freshness_alarm
    assert "threshold           = 1" in freshness_alarm
    assert 'comparison_operator = "LessThanThreshold"' in freshness_alarm
    assert 'treat_missing_data  = "breaching"' in freshness_alarm
    assert 'facility = "i95_i495"' in freshness_alarm
    assert "Environment = var.environment" in freshness_alarm
    assert "alarm_actions       = local.alarm_actions" in freshness_alarm
    assert (V2_ROOT / "scripts" / "build_publisher_zip.sh").exists()
    assert "./scripts/build_publisher_zip.sh" in CI_WORKFLOW

    publisher_invoke = terraform_block(
        MAIN_TF, 'resource "aws_lambda_function_event_invoke_config" "publisher"'
    )
    publisher_invoke_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "publisher_invoke_failure"'
    )
    publisher_delivery_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "publisher_delivery_failure"'
    )
    publisher_errors = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "publisher_errors"'
    )
    publisher_queue_alarms = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "publisher_failure_queues"'
    )
    assert_assignment(
        publisher_invoke, "function_name", "aws_lambda_function.publisher.function_name"
    )
    assert_assignment(publisher_invoke, "maximum_retry_attempts", "2")
    assert_assignment(publisher_invoke, "maximum_event_age_in_seconds", "21600")
    assert_assignment(
        publisher_invoke, "destination", "aws_sqs_queue.publisher_invoke_failure.arn"
    )
    for queue in (publisher_invoke_queue, publisher_delivery_queue):
        assert_assignment(queue, "sqs_managed_sse_enabled", "true")
        assert_assignment(queue, "message_retention_seconds", "1209600")
    assert_assignment(publisher_errors, "namespace", '"AWS/Lambda"')
    assert_assignment(publisher_errors, "metric_name", '"Errors"')
    assert_assignment(
        publisher_errors,
        "dimensions",
        "{ FunctionName = aws_lambda_function.publisher.function_name }",
    )
    assert_assignment(publisher_errors, "statistic", '"Sum"')
    assert_assignment(publisher_errors, "period", "300")
    assert_assignment(publisher_errors, "evaluation_periods", "1")
    assert_assignment(publisher_errors, "threshold", "1")
    assert_assignment(
        publisher_errors, "comparison_operator", '"GreaterThanOrEqualToThreshold"'
    )
    assert_assignment(publisher_errors, "treat_missing_data", '"notBreaching"')
    assert_assignment(publisher_errors, "alarm_actions", "local.alarm_actions")
    assert_assignment(
        publisher_queue_alarms, "invoke", "aws_sqs_queue.publisher_invoke_failure"
    )
    assert_assignment(
        publisher_queue_alarms, "delivery", "aws_sqs_queue.publisher_delivery_failure"
    )
    assert_assignment(publisher_queue_alarms, "namespace", '"AWS/SQS"')
    assert_assignment(
        publisher_queue_alarms, "metric_name", '"ApproximateNumberOfMessagesVisible"'
    )
    assert_assignment(
        publisher_queue_alarms, "dimensions", "{ QueueName = each.value.name }"
    )
    assert_assignment(publisher_queue_alarms, "statistic", '"Maximum"')
    assert_assignment(publisher_queue_alarms, "period", "300")
    assert_assignment(publisher_queue_alarms, "evaluation_periods", "1")
    assert_assignment(publisher_queue_alarms, "threshold", "1")
    assert_assignment(
        publisher_queue_alarms, "comparison_operator", '"GreaterThanOrEqualToThreshold"'
    )
    assert_assignment(publisher_queue_alarms, "treat_missing_data", '"notBreaching"')
    assert_assignment(publisher_queue_alarms, "alarm_actions", "local.alarm_actions")


def test_report_publisher_scheduler_and_environment_contract():
    assert 'reader         = "pricing_reader"' in ENVIRONMENT_TF
    assert 'reader         = "pricing_reader_development"' in ENVIRONMENT_TF
    schedule = terraform_block(MAIN_TF, 'resource "aws_scheduler_schedule" "publisher"')
    assert MAIN_TF.count('resource "aws_scheduler_schedule" "publisher"') == 1
    for attribute, value in (
        ("schedule_expression", '"cron(0 1 ? * MON *)"'),
        ("schedule_expression_timezone", '"America/New_York"'),
        ("arn", "aws_lambda_function.publisher.arn"),
        ("role_arn", "aws_iam_role.publisher_scheduler.arn"),
        ("input", 'jsonencode({ trigger = "watchdog" })'),
        ("maximum_retry_attempts", "2"),
        ("maximum_event_age_in_seconds", "3600"),
    ):
        assert_assignment(schedule, attribute, value)
    assert_assignment(schedule, "mode", '"OFF"')
    assert_assignment(schedule, "arn", "aws_sqs_queue.publisher_delivery_failure.arn")

    assume = MAIN_TF.split(
        'data "aws_iam_policy_document" "publisher_scheduler_assume"', maxsplit=1
    )[1].split('resource "aws_iam_role" "publisher_scheduler"', 1)[0]
    scheduler_policy = MAIN_TF.split(
        'data "aws_iam_policy_document" "publisher_scheduler"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "publisher_scheduler"', 1)[0]
    scheduler_role = terraform_block(
        MAIN_TF, 'resource "aws_iam_role" "publisher_scheduler"'
    )
    scheduler_role_policy = terraform_block(
        MAIN_TF, 'resource "aws_iam_role_policy" "publisher_scheduler"'
    )
    assert_assignment(assume, "actions", '["sts:AssumeRole"]')
    assert assume.count("principals {") == 1
    assert re.findall(r"identifiers\s*=\s*\[([^\]]+)\]", assume) == [
        '"scheduler.amazonaws.com"'
    ]
    assert_assignment(
        scheduler_role,
        "assume_role_policy",
        "data.aws_iam_policy_document.publisher_scheduler_assume.json",
    )
    assert_assignment(
        scheduler_role_policy, "role", "aws_iam_role.publisher_scheduler.id"
    )
    assert_assignment(
        scheduler_role_policy,
        "policy",
        "data.aws_iam_policy_document.publisher_scheduler.json",
    )
    statements = re.findall(r"(?s)statement \{(.*?)\n  \}", scheduler_policy)
    assert len(statements) == 2
    assert [
        (
            re.findall(r'actions\s+=\s+\["([^"]+)"\]', statement),
            re.findall(r"resources\s+=\s+\[([^\]]+)\]", statement),
        )
        for statement in statements
    ] == [
        (["lambda:InvokeFunction"], ["aws_lambda_function.publisher.arn"]),
        (["sqs:SendMessage"], ["aws_sqs_queue.publisher_delivery_failure.arn"]),
    ]
    for obsolete in (
        'resource "aws_cloudwatch_event_rule" "committed_i95_loads"',
        'resource "aws_cloudwatch_event_rule" "report_watchdog"',
        'resource "aws_cloudwatch_event_target" "publisher_load_event"',
        'resource "aws_cloudwatch_event_target" "publisher_watchdog"',
        'resource "aws_lambda_permission" "publisher_load_event"',
        'resource "aws_lambda_permission" "publisher_watchdog"',
        'resource "aws_sqs_queue_policy" "publisher_delivery_failure"',
        'resource "aws_cloudwatch_metric_alarm" "publisher_failed_invocations"',
    ):
        assert obsolete not in MAIN_TF


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

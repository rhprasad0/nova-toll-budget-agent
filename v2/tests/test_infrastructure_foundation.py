import difflib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from textwrap import dedent
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

import pytest
import yaml

from tests.infrastructure_support import (
    ACCOUNT_CONTRACT,
    APPLICATION_VARIABLES,
    DEPLOYMENT,
    DEVELOPMENT_CONNECTIVITY_WORKFLOW,
    DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW,
    DEVELOPMENT_FOUNDATION_330,
    DEVELOPMENT_FOUNDATION_PLAN_VALIDATOR,
    ENVIRONMENT_TF,
    FOUNDATION_AGENTCORE,
    FOUNDATION_BUDGET,
    FOUNDATION_FIELDS,
    FOUNDATION_IAM,
    FOUNDATION_LAMBDA,
    FOUNDATION_PROVIDER,
    FOUNDATION_ROOT,
    FOUNDATION_TAILSCALE,
    FOUNDATION_TRIGGERS,
    LEGACY_DEVELOPMENT_INVENTORY,
    MAIN_TF,
    REPO_ROOT,
    RUNBOOK,
    TIMED_CHECKS_TF,
    V2_ROOT,
    hcl_attribute,
    must_reject,
    terraform_block,
    workflow_run_source,
    workflow_trigger,
)


def test_account_contract_records_the_replacement_development_boundary() -> None:
    accounts = ACCOUNT_CONTRACT["accounts"]
    assert ACCOUNT_CONTRACT["region"] == "us-east-1"
    assert accounts["management"]["id"] == "407645373626"
    assert accounts["production"] == {
        "name": "nova-toll-prod",
        "id": "920534282028",
        "ownership": "account-local",
    }
    assert accounts["development"] == {
        "name": "nova-toll-development",
        "id": "903859731897",
        "routine_human_access": "IAM Identity Center AdministratorAccess",
        "break_glass_role": "OrganizationAccountAccessRole",
        "long_lived_ci_credentials": False,
        "owns": [
            "backend",
            "KMS",
            "network",
            "RDS",
            "storage",
            "audit trail",
            "SSM parameters",
            "future GitHub OIDC identities",
        ],
    }
    shared_access = ACCOUNT_CONTRACT["shared_access"]
    assert shared_access["development_to_production_aws_read_paths"] == []
    assert "not an AWS shared-read grant" in shared_access["cloudflare_dns"]


def test_account_local_backends_keep_production_paths_and_lockfiles_distinct() -> None:
    foundation_production = (FOUNDATION_ROOT / "backend.production.hcl").read_text()
    foundation_development = (FOUNDATION_ROOT / "backend.development.hcl").read_text()
    application_production = (V2_ROOT / "infra" / "backend.production.hcl").read_text()
    application_development = (
        V2_ROOT / "infra" / "backend.development.hcl"
    ).read_text()

    assert 'bucket       = "nova-toll-tfstate-920534282028"' in foundation_production
    assert 'key          = "nova-toll/terraform.tfstate"' in foundation_production
    assert 'bucket       = "nova-toll-tfstate-903859731897"' in foundation_development
    assert (
        'key          = "nova-toll/development/terraform.tfstate"'
        in foundation_development
    )
    assert 'bucket       = "nova-toll-tfstate-920534282028"' in application_production
    assert 'key          = "nova-toll/v2/terraform.tfstate"' in application_production
    assert 'bucket       = "nova-toll-tfstate-903859731897"' in application_development
    assert (
        'key          = "nova-toll/v2/development/terraform.tfstate"'
        in application_development
    )
    for backend in (
        foundation_production,
        foundation_development,
        application_production,
        application_development,
    ):
        assert "use_lockfile = true" in backend
    assert "nova-toll-tfstate-920534282028" not in foundation_development
    assert "nova-toll-tfstate-920534282028" not in application_development


def test_all_backends_pin_native_kms_encryption_and_locking() -> None:
    for backend_path in (
        FOUNDATION_ROOT / "backend.production.hcl",
        FOUNDATION_ROOT / "backend.development.hcl",
        V2_ROOT / "infra" / "backend.production.hcl",
        V2_ROOT / "infra" / "backend.development.hcl",
    ):
        backend = backend_path.read_text()
        assert "use_lockfile = true" in backend
        assert "encrypt      = true" in backend
        assert 'kms_key_id   = "alias/nova-toll-tfstate"' in backend
        assert "s3:x-amz-server-side-encryption" not in backend


def test_provider_account_guards_derive_from_the_account_contract() -> None:
    foundation = FOUNDATION_PROVIDER
    application = (V2_ROOT / "infra" / "providers.tf").read_text()

    assert (
        'jsondecode(file("${path.module}/account-contract.json")).accounts[var.environment].id'
        in foundation
    )
    assert (
        'jsondecode(file("${path.module}/../../infra/account-contract.json")).accounts[var.environment].id'
        in application
    )
    for provider in (foundation, application):
        assert "allowed_account_ids" in provider
        assert "903859731897" not in provider
        assert "920534282028" not in provider


def test_tfstate_bucket_is_hardened_and_denies_foreign_accounts() -> None:
    s3 = (FOUNDATION_ROOT / "s3.tf").read_text()
    kms = (FOUNDATION_ROOT / "kms.tf").read_text()
    policy = terraform_block(s3, 'data "aws_iam_policy_document" "tfstate_bucket"')
    key = terraform_block(kms, 'resource "aws_kms_key" "tfstate"')

    for resource in (
        'resource "aws_s3_bucket_versioning" "hardened"',
        'resource "aws_s3_bucket_ownership_controls" "hardened"',
        'resource "aws_s3_bucket_public_access_block" "hardened"',
        'resource "aws_s3_bucket_server_side_encryption_configuration" "hardened"',
        'resource "aws_s3_bucket_lifecycle_configuration" "hardened"',
    ):
        assert resource in s3
    assert (
        "tfstate = { id = aws_s3_bucket.tfstate.id, kms_key_arn = aws_kms_key.tfstate.arn }"
        in s3
    )
    assert 'sse_algorithm     = "aws:kms"' in s3
    assert "kms_master_key_id = each.value.kms_key_arn" in s3
    assert 'object_ownership = "BucketOwnerEnforced"' in s3
    assert "block_public_acls       = true" in s3
    assert "block_public_policy     = true" in s3
    assert "ignore_public_acls      = true" in s3
    assert "restrict_public_buckets = true" in s3
    assert 'variable = "aws:SecureTransport"' in policy
    assert 'sid       = "DenyOutsideCallerAccount"' in policy
    assert 'test     = "StringNotEquals"' in policy
    assert 'variable = "aws:PrincipalAccount"' in policy
    assert "data.aws_caller_identity.current.account_id" in policy
    assert "aws_s3_bucket.tfstate.arn" in policy
    assert '"${aws_s3_bucket.tfstate.arn}/*"' in policy
    assert policy.count('variable = "s3:x-amz-server-side-encryption"') == 1
    assert (
        policy.count('variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"') == 1
    )
    assert policy.count('resources = ["${aws_s3_bucket.tfstate.arn}/plans/*"]') == 3
    assert "920534282028" not in policy
    assert "policy" not in key
    assert "enable_key_rotation     = true" in key
    assert "deletion_window_in_days = 30" in key


def test_foundation_names_and_budget_use_the_caller_account() -> None:
    foundation_s3 = (FOUNDATION_ROOT / "s3.tf").read_text()
    foundation_agentcore = FOUNDATION_AGENTCORE
    foundation_audit = (FOUNDATION_ROOT / "audit.tf").read_text()
    budget = FOUNDATION_BUDGET.read_text()

    assert "account_id = data.aws_caller_identity.current.account_id" in foundation_s3
    for name, source in (
        ("nova-toll-raw-${local.account_id}", foundation_s3),
        ("nova-toll-tfstate-${local.account_id}", foundation_s3),
        ("nova-toll-agentcore-${local.account_id}", foundation_agentcore),
        ("nova-toll-audit-${local.account_id}", foundation_audit),
    ):
        assert name in source
    assert "account_id        = local.account_id" in budget
    for source in (foundation_s3, foundation_agentcore, foundation_audit, budget):
        assert "920534282028" not in source
    foundation_terraform = "".join(
        path.read_text() for path in FOUNDATION_ROOT.glob("*.tf")
    )
    assert "cloudflare-development-dns-api-token" in foundation_terraform


def test_foundation_output_and_application_input_are_the_exact_non_secret_boundary() -> (
    None
):
    output = (FOUNDATION_ROOT / "outputs.tf").read_text()
    variable = APPLICATION_VARIABLES.split('variable "foundation"', maxsplit=1)[
        1
    ].split('variable "environment"', maxsplit=1)[0]
    assert output.count('output "foundation"') == 1
    assert output.count("output ") == 1
    assert "sensitive   = false" in output
    assert "sensitive = true" not in output
    assert "sensitive = true" not in variable
    assert "default" not in variable
    for field in FOUNDATION_FIELDS:
        assert field in output
        assert field in variable
    assert re.search(
        r"private_subnet_ids\s*=\s*object\(\{\s*a\s*=\s*string,\s*c\s*=\s*string\s*\}\)",
        variable,
    )
    for field in ("identifier", "resource_id", "address", "port"):
        assert field in output and field in variable
    for forbidden in (
        "password",
        "ssm",
        "master",
        "terraform_remote_state",
    ):
        assert forbidden not in output.lower()


def test_development_foundation_cannot_advertise_the_shared_vpc_route() -> None:
    variables = (FOUNDATION_ROOT / "variables.tf").read_text()
    router = FOUNDATION_TAILSCALE
    development_handoff = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]

    assert 'variable "environment"' in variables
    assert 'default     = "production"' in variables
    assert 'variable "tailscale_advertise_routes"' in variables
    assert "default     = true" in variables
    assert 'development_tailscale_route = "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"' in router
    assert 'var.environment == "development"' in router
    assert (
        "data.aws_caller_identity.current.account_id == local.development_account_id"
        in router
    )
    assert 'var.environment == "production"' in router
    assert (
        "data.aws_caller_identity.current.account_id == local.production_account_id"
        in router
    )
    production_advertisement = router.split(
        '%{if var.tailscale_advertise_routes && var.environment == "production"~}',
        maxsplit=1,
    )[1].split("%{endif~}", maxsplit=1)[0]
    for option in (
        "--advertise-routes=${data.aws_vpc.default.cidr_block}",
        "--advertise-exit-node",
        "--advertise-tags=tag:nova-toll-router",
    ):
        assert option in production_advertisement
    development_advertisement = router.split(
        '%{if var.tailscale_advertise_routes && var.environment == "development"~}',
        maxsplit=1,
    )[1].split("%{endif~}", maxsplit=1)[0]
    assert (
        "--advertise-routes=${local.development_tailscale_route}"
        in development_advertisement
    )
    assert "--advertise-exit-node" not in development_advertisement
    assert "--advertise-tags=tag:nova-toll-router" not in development_advertisement
    assert "${data.aws_vpc.default.cidr_block}" not in development_advertisement
    assert (
        '%{if var.tailscale_advertise_routes && var.environment == "production"~}'
        in router
    )
    assert (
        '%{if var.tailscale_advertise_routes && var.environment == "development"~}'
        in router
    )
    assert "-var environment=development" in development_handoff
    assert "-var tailscale_advertise_routes=false" in development_handoff
    assert "non-overlapping" in DEPLOYMENT
    assert "environment-specific ACL identity" in DEPLOYMENT


def test_v2_uses_the_typed_boundary_without_foundation_discovery() -> None:
    terraform_sources = "\n".join(
        path.read_text() for path in (V2_ROOT / "infra").glob("*.tf")
    )
    for forbidden in (
        "terraform_remote_state",
        'data "aws_vpc"',
        'data "aws_subnets"',
        'data "aws_subnet"',
        'data "aws_vpc_endpoint"',
        'data "aws_security_group"',
        'data "aws_s3_bucket"',
        'data "aws_db_instance"',
        'data "aws_sns_topic"',
        "nova-toll-raw-920534282028",
        "nova-toll-agentcore-920534282028",
    ):
        assert forbidden not in terraform_sources
    assert terraform_sources.count('data "aws_kms_alias"') == 1
    assert 'data "aws_kms_alias" "alerts"' in TIMED_CHECKS_TF
    assert 'name = "alias/nova-toll-alerts"' in TIMED_CHECKS_TF
    for field in (
        "vpc_id",
        "vpc_cidr_block",
        "private_subnet_ids",
        "rds_security_group_id",
        "agentcore_endpoint_security_group_id",
        "eventbridge_endpoint_security_group_id",
        "agentcore_vpc_endpoint_id",
        "agentcore_vpc_endpoint_dns_name",
        "tollchat_api_vpc_endpoint_id",
        "raw_bucket_name",
        "raw_kms_key_arn",
        "agentcore_artifacts_bucket_name",
        "db_instance",
        "alerts_topic_arn",
    ):
        assert f"var.foundation.{field}" in terraform_sources


def test_foundation_rds_database_name_tracks_environment_contract() -> None:
    rds = (FOUNDATION_ROOT / "rds.tf").read_text()
    instance = terraform_block(rds, 'resource "aws_db_instance" "main"')
    assert hcl_attribute(instance, "db_name") == (
        'var.environment == "development" ? "nova_toll_development" : "nova_toll"'
    )
    assert hcl_attribute(instance, "final_snapshot_identifier") == (
        'var.environment == "development" ? var.development_final_snapshot_identifier : null'
    )
    snapshot_variable = (
        (FOUNDATION_ROOT / "variables.tf")
        .read_text()
        .split('variable "development_final_snapshot_identifier"', maxsplit=1)[1]
        .split('variable "budget_notification_email"', maxsplit=1)[0]
    )
    assert "default     = null" in snapshot_variable
    assert "nullable    = true" in snapshot_variable
    assert "^[A-Za-z]([A-Za-z0-9-]*[A-Za-z0-9])?$" in snapshot_variable
    assert (
        '!strcontains(var.development_final_snapshot_identifier, "--")'
        in snapshot_variable
    )
    assert (
        'database_name  = local.is_production ? "nova_toll" : "nova_toll_development"'
        in ENVIRONMENT_TF
    )
    assert (
        "DEVELOPMENT_DB_NAME: nova_toll_development"
        in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    )
    for runtime in (MAIN_TF, (V2_ROOT / "infra" / "agentcore.tf").read_text()):
        assert re.search(r"(?m)^\s*DB_NAME\s*=\s*local\.database_name$", runtime)


def test_handoff_and_follow_on_ownership_are_documented_without_persisted_ids() -> None:
    runbook = DEPLOYMENT
    for text in (
        "guarded\nproduction planner",
        "current foundation output",
        "validates its approved non-secret shape",
        "planner-owned production handoff",
    ):
        assert text in runbook
    for text in (
        "#330",
        "#331",
        "#332",
        "#333",
        "certificate-validation",
        "enable_public_dns = false",
        "AWS-only identity",
        "cannot write Cloudflare DNS",
    ):
        assert text in runbook
    assert "is the operative development release path" in runbook
    assert "runbooks/development-foundation-330-archive.md" in RUNBOOK
    assert "historical audit and recovery context" in RUNBOOK
    assert "not the guarded production release's `production.tfvars`" in runbook
    for tfvars in (V2_ROOT / "infra").glob("*.tfvars"):
        assert "vpc-" not in tfvars.read_text()
        assert "subnet-" not in tfvars.read_text()
        assert "sg-" not in tfvars.read_text()
        assert "arn:aws" not in tfvars.read_text()

    production = runbook.split("### Guarded production release", maxsplit=1)[1].split(
        "The legacy development inventory", maxsplit=1
    )[0]
    for text in (
        "guarded published-release flow",
        "planner validates the exact candidate bundle",
        "candidate/state-bound saved plan",
        "Reviewer approval of the protected `production` job",
        "before applying that same plan",
    ):
        assert text in production
    assert "terraform plan" not in production
    assert "terraform apply" not in production


def test_backend_and_provider_configuration_has_no_credential_or_workspace_coupling() -> (
    None
):
    configuration = "\n".join(
        path.read_text()
        for path in (
            FOUNDATION_ROOT / "providers.tf",
            FOUNDATION_ROOT / "versions.tf",
            FOUNDATION_ROOT / "backend.production.hcl",
            FOUNDATION_ROOT / "backend.development.hcl",
            V2_ROOT / "infra" / "providers.tf",
            V2_ROOT / "infra" / "versions.tf",
            V2_ROOT / "infra" / "backend.production.hcl",
            V2_ROOT / "infra" / "backend.development.hcl",
        )
    ).lower()
    for forbidden in (
        "profile",
        "access_key",
        "secret_key",
        "assume_role",
        "workspace",
        "terraform_remote_state",
        "dynamodb_table",
    ):
        assert forbidden not in configuration


def test_legacy_development_inventory_hands_cleanup_to_issue_333() -> None:
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


def test_foundation_budget_preserves_the_production_notification_contract() -> None:
    budget = FOUNDATION_BUDGET.read_text()
    variables = (FOUNDATION_ROOT / "variables.tf").read_text()

    assert 'variable "budget_notification_email"' in variables
    email_variable = variables.split('variable "budget_notification_email"', 1)[1]
    assert re.search(r"type\s+= string", email_variable)
    assert re.search(r"sensitive\s+= true", email_variable)
    assert "default" not in email_variable.split("}", 1)[0]
    assert 'resource "aws_budgets_budget" "nova_toll_monthly"' in budget
    for attribute, value in (
        ("account_id", r"local\.account_id"),
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
    assert "import {" not in budget


def test_foundation_publishes_raw_events_without_a_legacy_loader() -> None:
    notification = FOUNDATION_TRIGGERS.split(
        'resource "aws_s3_bucket_notification" "raw"', maxsplit=1
    )[1]
    assert "eventbridge = true" in notification
    assert "lambda_function" not in notification
    assert (
        'resource "aws_lambda_permission" "s3_invoke_loader"' not in FOUNDATION_TRIGGERS
    )
    assert 'resource "aws_lambda_function" "loader"' not in FOUNDATION_LAMBDA


def test_foundation_has_no_site_and_terraform_ci_only_validates() -> None:
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


def test_shared_foundation_and_router_volume_are_tagged_shared() -> None:
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


def test_shared_dynamodb_endpoint_admits_v2_session_table() -> None:
    endpoint = FOUNDATION_AGENTCORE.split(
        'resource "aws_vpc_endpoint" "dynamodb"', maxsplit=1
    )[1].split('resource "aws_s3_bucket" "agentcore_artifacts"', maxsplit=1)[0]
    assert "tollchat-v2-anonymous-sessions" in endpoint
    assert "tollchat-v2-anonymous-sessions-dev" in endpoint
    assert "table/tollchat-anonymous-sessions" not in endpoint
    assert "dynamodb:*" not in endpoint
    assert '"dynamodb:TransactWriteItems"' not in endpoint


def test_account_local_release_contract_and_foundation_gates_fail_closed() -> None:
    for text in (
        "AWS_PROFILE=nova-toll-dev",
        'get-caller-identity --query Account --output text)" = "903859731897"',
        "backend.production.hcl",
        "production.tfvars",
        "is the operative development release path",
        "#330",
        "#331",
        "#332",
        "-reconfigure",
        "-lock=false",
    ):
        assert text in DEPLOYMENT
    assert "guarded\nproduction planner" in RUNBOOK
    assert DEPLOYMENT.index(
        "### Development foundation handoff (#330; no application release)"
    ) < DEPLOYMENT.index("### Guarded production release")
    assert "903859731897" in DEPLOYMENT
    assert "terraform workspace" not in DEPLOYMENT
    assert "terraform -target" not in DEPLOYMENT
    handoff = DEPLOYMENT.split("## Account-local foundation handoff", maxsplit=1)[
        1
    ].split("Application/database bootstrap", maxsplit=1)[0]
    for text in (
        "guarded\nproduction planner",
        "current foundation output",
        "validates its approved non-secret shape",
        "planner-owned production handoff",
    ):
        assert text in handoff
    assert "planned-output" not in handoff
    assert "foundation-plan path" not in handoff


def _development_foundation_validator(source: str) -> str:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    deploy_source = workflow_run_source(jobs["deploy"])
    match = re.search(
        r'''jq -e '\n(.*?)\n' "\$FOUNDATION_OUTPUT"''',
        deploy_source,
        flags=re.DOTALL,
    )
    assert match, "the workflow must validate foundation output"
    return dedent(match.group(1))


def _development_cutover_foundation_validator(source: str) -> str:
    matches = re.findall(
        r"""(?m)^jq -e '(.*?)' "\$FOUNDATION_JSON" >/dev/null$""", source
    )
    assert len(matches) == 1, (
        "the runbook must have one development foundation validator"
    )
    return matches[0]


def _foundation_validator_keys(predicate: str) -> list[str]:
    match = re.search(r"exact_keys\((\[[^\]]+\])\)", predicate)
    assert match is not None
    return cast(list[str], json.loads(match.group(1)))


def _jq_validator_accepts(predicate: str, payload: object) -> bool:
    result = subprocess.run(
        ["jq", "-e", predicate],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def test_development_foundation_output_validators_fail_closed_and_match() -> None:
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    workflow_jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    deploy_source = workflow_run_source(workflow_jobs["deploy"])
    workflow_predicate = _development_foundation_validator(
        DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW
    )
    runbook_predicate = _development_cutover_foundation_validator(DEPLOYMENT)

    for predicate in (workflow_predicate, runbook_predicate):
        assert _foundation_validator_keys(predicate) == [
            field for field in FOUNDATION_FIELDS if field != "telemetry_guardrail"
        ]
    output_index = deploy_source.index("terraform -chdir=infra output -json foundation")
    validator_index = deploy_source.index("jq -e '\n", output_index)
    wrapper_index = deploy_source.index(
        'jq -n --slurpfile foundation "$FOUNDATION_OUTPUT"'
    )
    assert output_index < validator_index < wrapper_index

    valid: dict[str, object] = {
        "vpc_id": "vpc-id",
        "vpc_cidr_block": "10.0.0.0/16",
        "private_subnet_ids": {"a": "subnet-a", "c": "subnet-c"},
        "rds_security_group_id": "sg-rds",
        "agentcore_endpoint_security_group_id": "sg-agentcore",
        "eventbridge_endpoint_security_group_id": "sg-eventbridge",
        "agentcore_vpc_endpoint_id": "vpce-agentcore",
        "agentcore_vpc_endpoint_dns_name": "agentcore.example.com",
        "tollchat_api_vpc_endpoint_id": "vpce-api",
        "raw_bucket_name": "raw-bucket",
        "raw_kms_key_arn": "arn:aws:kms:us-east-1:903859731897:key/raw",
        "agentcore_artifacts_bucket_name": "artifacts-bucket",
        "db_instance": {
            "identifier": "db-instance",
            "resource_id": "db-resource",
            "address": "db.example.com",
            "port": 5432,
        },
        "alerts_topic_arn": "arn:aws:sns:us-east-1:903859731897:alerts",
    }
    invalid: list[tuple[str, dict[str, object]]] = []

    missing_top_level = deepcopy(valid)
    del missing_top_level["vpc_id"]
    invalid.append(("missing top-level key", missing_top_level))
    obsolete_top_level = deepcopy(valid)
    obsolete_top_level["obsolete"] = "no longer supported"
    invalid.append(("obsolete top-level key", obsolete_top_level))

    missing_subnet_key = deepcopy(valid)
    cast(dict[str, object], missing_subnet_key["private_subnet_ids"]).pop("c")
    invalid.append(("missing subnet key", missing_subnet_key))
    obsolete_subnet_key = deepcopy(valid)
    cast(dict[str, object], obsolete_subnet_key["private_subnet_ids"])["b"] = "subnet-b"
    invalid.append(("obsolete subnet key", obsolete_subnet_key))
    renamed_subnet_key = deepcopy(valid)
    subnets = cast(dict[str, object], renamed_subnet_key["private_subnet_ids"])
    subnets["primary"] = subnets.pop("a")
    invalid.append(("renamed subnet key", renamed_subnet_key))
    empty_subnet_value = deepcopy(valid)
    cast(dict[str, object], empty_subnet_value["private_subnet_ids"])["a"] = ""
    invalid.append(("empty subnet value", empty_subnet_value))

    missing_db_key = deepcopy(valid)
    cast(dict[str, object], missing_db_key["db_instance"]).pop("address")
    invalid.append(("missing database key", missing_db_key))
    renamed_db_key = deepcopy(valid)
    db = cast(dict[str, object], renamed_db_key["db_instance"])
    db["hostname"] = db.pop("address")
    invalid.append(("renamed database key", renamed_db_key))
    for field in ("identifier", "resource_id", "address"):
        empty_db_field = deepcopy(valid)
        cast(dict[str, object], empty_db_field["db_instance"])[field] = ""
        invalid.append((f"empty database {field}", empty_db_field))
        wrong_types: tuple[tuple[str, object], ...] = (
            ("null", None),
            ("number", 1),
            ("boolean", True),
            ("array", []),
            ("object", {}),
        )
        for label, value in wrong_types:
            wrong_type_db_field = deepcopy(valid)
            cast(dict[str, object], wrong_type_db_field["db_instance"])[field] = value
            invalid.append((f"{field} {label}", wrong_type_db_field))
    nonnumeric_port = deepcopy(valid)
    cast(dict[str, object], nonnumeric_port["db_instance"])["port"] = "5432"
    invalid.append(("nonnumeric port", nonnumeric_port))

    for label, payload, expected in [
        ("complete", valid, True),
        *[(name, value, False) for name, value in invalid],
    ]:
        workflow_result = _jq_validator_accepts(workflow_predicate, payload)
        runbook_result = _jq_validator_accepts(runbook_predicate, payload)
        assert workflow_result == runbook_result, label
        assert workflow_result is expected, label


def _foundation_plan_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "development_foundation_plan_validator", DEVELOPMENT_FOUNDATION_PLAN_VALIDATOR
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _foundation_change(
    mode: str, address: str, actions: list[str], **change: object
) -> dict[str, Any]:
    return {
        "mode": mode,
        "address": address,
        "change": {"actions": actions, **change},
    }


def test_development_foundation_plan_validator_accepts_only_exact_replacement() -> None:
    if TYPE_CHECKING:
        from scripts import validate_development_foundation_plan as validator
    else:
        validator = _foundation_plan_validator()
    snapshot_identifier = "nova-toll-db-development-cutover-20260904t150735z"
    route_trust = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Effect": "Allow",
                    "Principal": {"Federated": validator.ROUTE_CONTROL_OIDC_ARN},
                    "Condition": {
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                            "token.actions.githubusercontent.com:sub": validator.ROUTE_CONTROL_OIDC_SUBJECT,
                        }
                    },
                }
            ],
        },
        separators=(",", ":"),
    )
    route_policy = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "SendRouterStatusCommand",
                    "Effect": "Allow",
                    "Action": "ssm:SendCommand",
                    "Resource": [
                        validator.ROUTE_CONTROL_INSTANCE_ARN,
                        validator.ROUTE_CONTROL_DOCUMENT_ARN,
                    ],
                },
                {
                    "Sid": "ReadRouterStatusCommand",
                    "Effect": "Allow",
                    "Action": "ssm:GetCommandInvocation",
                    "Resource": "*",
                    "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
                },
            ],
        },
        separators=(",", ":"),
    )
    rds_before = {
        "identifier": "nova-toll-db",
        "engine": "postgres",
        "publicly_accessible": False,
        "db_name": "nova_toll",
        "deletion_protection": False,
        "final_snapshot_identifier": snapshot_identifier,
    }
    rds_after = {
        "identifier": "nova-toll-db",
        "engine": "postgres",
        "publicly_accessible": False,
        "db_name": "nova_toll_development",
        "storage_encrypted": True,
        "iam_database_authentication_enabled": True,
        "manage_master_user_password": True,
        "deletion_protection": True,
        "skip_final_snapshot": False,
        "final_snapshot_identifier": snapshot_identifier,
        "vpc_security_group_ids": ["sg-reviewed"],
    }
    foundation_changes = [
        _foundation_change(
            "managed",
            "aws_db_instance.main",
            ["delete", "create"],
            replace_paths=[["db_name"]],
            before=rds_before,
            after=rds_after,
        )
    ]
    foundation_changes += [
        _foundation_change(
            "managed",
            "aws_ssm_document.route_control[0]",
            ["no-op"],
            after={
                "name": validator.ROUTE_CONTROL_DOCUMENT_NAME,
                "document_type": "Command",
                "document_format": "YAML",
                "content": validator.ROUTE_CONTROL_DOCUMENT_CONTENT,
            },
        ),
        _foundation_change(
            "managed",
            "aws_iam_role.route_control[0]",
            ["no-op"],
            after={
                "name": validator.ROUTE_CONTROL_NAME,
                "assume_role_policy": route_trust,
            },
        ),
        _foundation_change(
            "managed",
            "aws_iam_role_policy.route_control[0]",
            ["no-op"],
            after={"name": validator.ROUTE_CONTROL_NAME, "policy": route_policy},
        ),
    ]
    foundation_changes += [
        _foundation_change("data", address, ["read"])
        for address in (
            "data.aws_iam_policy_document.route_control_assume[0]",
            "data.aws_iam_policy_document.route_control[0]",
        )
    ]
    foundation_changes += [
        _foundation_change(
            "managed",
            address,
            ["no-op"],
            after=(
                {
                    "from_port": 5432,
                    "to_port": 5432,
                    "ip_protocol": "tcp",
                    "referenced_security_group_id": "sg-router",
                    "cidr_ipv4": None,
                    "cidr_ipv6": None,
                }
                if address == "aws_vpc_security_group_ingress_rule.rds_from_tailscale"
                else {
                    "cidr_ipv4": "0.0.0.0/0",
                    "ip_protocol": "-1",
                    "security_group_id": "sg-router",
                }
                if address
                == "aws_vpc_security_group_egress_rule.tailscale_router_egress"
                else {}
            ),
        )
        for address in sorted(
            validator.EXPECTED_MANAGED_NOOP_ADDRESSES
            - validator.ROUTE_CONTROL_ADDRESSES
        )
    ]
    plan = {"resource_changes": foundation_changes}
    assert len(validator.EXPECTED_MANAGED_NOOP_ADDRESSES) == 112
    assert validator.validate_plan(plan, snapshot_identifier) == {
        "managed_noop": 112,
        "rds_replacement": 1,
        "route_control_noop": 3,
        "data_read": 2,
    }
    provider_order_plan = deepcopy(plan)
    provider_policy = json.loads(
        provider_order_plan["resource_changes"][3]["change"]["after"]["policy"]
    )
    provider_policy["Statement"][0]["Resource"].reverse()
    provider_order_plan["resource_changes"][3]["change"]["after"]["policy"] = (
        json.dumps(provider_policy, separators=(",", ":"))
    )
    assert (
        validator.validate_plan(provider_order_plan, snapshot_identifier)[
            "route_control_noop"
        ]
        == 3
    )
    resolved_data_plan = deepcopy(provider_order_plan)
    resolved_data_plan["resource_changes"] = [
        change
        for change in resolved_data_plan["resource_changes"]
        if change["mode"] != "data"
    ]
    assert (
        validator.validate_plan(resolved_data_plan, snapshot_identifier)["data_read"]
        == 0
    )

    mismatched_snapshot_plan = deepcopy(plan)
    mismatched_snapshot_plan["resource_changes"][0]["change"]["after"][
        "final_snapshot_identifier"
    ] = "nova-toll-db-other"
    missing_snapshot_plan = deepcopy(plan)
    del missing_snapshot_plan["resource_changes"][0]["change"]["after"][
        "final_snapshot_identifier"
    ]
    unseeded_snapshot_plan = deepcopy(plan)
    unseeded_snapshot_plan["resource_changes"][0]["change"]["before"][
        "final_snapshot_identifier"
    ] = None
    route_create_plan = deepcopy(plan)
    route_create_plan["resource_changes"][1]["change"]["actions"] = ["create"]
    route_drift_plan = deepcopy(plan)
    route_drift_policy = json.loads(
        route_drift_plan["resource_changes"][3]["change"]["after"]["policy"]
    )
    route_drift_policy["Statement"][0]["Action"] = "ssm:*"
    route_drift_plan["resource_changes"][3]["change"]["after"]["policy"] = json.dumps(
        route_drift_policy, separators=(",", ":")
    )
    substituted_noop_plan = deepcopy(plan)
    substituted_noop_plan["resource_changes"][-1]["address"] = "aws_test.substituted"
    duplicate_noop_plan = deepcopy(plan)
    duplicate_noop_plan["resource_changes"][-1]["address"] = duplicate_noop_plan[
        "resource_changes"
    ][-2]["address"]

    for invalid in (
        mismatched_snapshot_plan,
        missing_snapshot_plan,
        unseeded_snapshot_plan,
        route_create_plan,
        route_drift_plan,
        substituted_noop_plan,
        duplicate_noop_plan,
        {**plan, "resource_changes": plan["resource_changes"][:-1]},
        {
            **plan,
            "resource_changes": [
                *plan["resource_changes"],
                _foundation_change("managed", "aws_test.extra", ["no-op"]),
            ],
        },
        {
            **plan,
            "resource_changes": [
                *plan["resource_changes"][:-1],
                _foundation_change(
                    "managed", "aws_budgets_budget.nova_toll_monthly", ["update"]
                ),
            ],
        },
        {
            **plan,
            "resource_changes": [
                _foundation_change(
                    "managed",
                    "aws_db_instance.main",
                    ["delete", "create"],
                    replace_paths=[["identifier"]],
                    before={"db_name": "nova_toll"},
                    after={"db_name": "nova_toll_development"},
                ),
                *plan["resource_changes"][1:],
            ],
        },
        {
            **plan,
            "resource_changes": [
                *plan["resource_changes"],
                _foundation_change("data", "data.aws_region.current", ["read"]),
            ],
        },
        {
            **plan,
            "resource_changes": [
                change
                for change in plan["resource_changes"]
                if change["address"]
                != "data.aws_iam_policy_document.route_control_assume[0]"
            ],
        },
        {
            **plan,
            "resource_changes": [
                *plan["resource_changes"],
                _foundation_change("managed", "aws_db_instance.production", ["no-op"]),
            ],
        },
    ):
        with pytest.raises(validator.ValidationError):
            validator.validate_plan(invalid, snapshot_identifier)

    for invalid_identifier in (
        "",
        "1starts-with-digit",
        "ends-with-",
        "has--consecutive",
        "has_underscore",
        "a" * 256,
    ):
        with pytest.raises(validator.ValidationError):
            validator.validate_plan(plan, invalid_identifier)

    seed_before = {
        "identifier": "nova-toll-db",
        "arn": validator.STATE_SEED_RDS_ARN,
        "resource_id": validator.STATE_SEED_RDS_RESOURCE_ID,
        "engine": "postgres",
        "db_name": "nova_toll",
        "publicly_accessible": False,
        "deletion_protection": True,
        "skip_final_snapshot": False,
        "final_snapshot_identifier": None,
        "vpc_security_group_ids": ["sg-reviewed"],
    }
    seed_plan = deepcopy(plan)
    seed_plan["resource_changes"][0] = _foundation_change(
        "managed",
        "aws_db_instance.main",
        ["update"],
        replace_paths=None,
        before=seed_before,
        after={
            **seed_before,
            "final_snapshot_identifier": snapshot_identifier,
        },
        after_unknown={},
    )
    seed_arguments = {
        "mode": "state-seed",
        "rds_instance_arn": validator.STATE_SEED_RDS_ARN,
        "rds_resource_id": validator.STATE_SEED_RDS_RESOURCE_ID,
    }
    assert validator.validate_plan(
        seed_plan, snapshot_identifier, **seed_arguments
    ) == {
        "managed_noop": 112,
        "rds_state_seed": 1,
        "route_control_noop": 3,
        "data_read": 2,
    }
    with pytest.raises(validator.ValidationError):
        validator.validate_plan(seed_plan, snapshot_identifier)
    with pytest.raises(validator.ValidationError):
        validator.validate_plan(seed_plan, snapshot_identifier, mode="state-seed")
    with pytest.raises(validator.ValidationError):
        validator.validate_plan(plan, snapshot_identifier, **seed_arguments)
    with pytest.raises(validator.ValidationError):
        validator.validate_plan(seed_plan, snapshot_identifier, mode="unexpected")

    invalid_seed_plans: list[dict[str, Any]] = []
    for key, value in (
        ("db_name", "nova_toll_development"),
        ("deletion_protection", False),
        ("publicly_accessible", True),
    ):
        invalid = deepcopy(seed_plan)
        invalid["resource_changes"][0]["change"]["before"][key] = value
        invalid["resource_changes"][0]["change"]["after"][key] = value
        invalid_seed_plans.append(invalid)
    mismatched_seed_snapshot = deepcopy(seed_plan)
    mismatched_seed_snapshot["resource_changes"][0]["change"]["after"][
        "final_snapshot_identifier"
    ] = "nova-toll-db-other"
    invalid_seed_plans.append(mismatched_seed_snapshot)
    unknown_seed = deepcopy(seed_plan)
    unknown_seed["resource_changes"][0]["change"]["after_unknown"] = {"endpoint": True}
    invalid_seed_plans.append(unknown_seed)
    extra_seed_change = deepcopy(seed_plan)
    extra_seed_change["resource_changes"][0]["change"]["after"]["port"] = 5433
    invalid_seed_plans.append(extra_seed_change)
    other_update = deepcopy(seed_plan)
    other_update["resource_changes"][-1]["change"]["actions"] = ["update"]
    invalid_seed_plans.append(other_update)
    seed_route_create = deepcopy(seed_plan)
    seed_route_create["resource_changes"][1]["change"]["actions"] = ["create"]
    invalid_seed_plans.append(seed_route_create)
    for invalid in invalid_seed_plans:
        with pytest.raises(validator.ValidationError):
            validator.validate_plan(invalid, snapshot_identifier, **seed_arguments)
    for identity in (
        {
            **seed_arguments,
            "rds_instance_arn": "arn:aws:rds:us-east-1:920534282028:db:nova-toll-db",
        },
        {**seed_arguments, "rds_resource_id": "db-WRONG"},
    ):
        with pytest.raises(validator.ValidationError):
            validator.validate_plan(seed_plan, snapshot_identifier, **identity)


def test_development_foundation_plan_context_and_acl_fixture_are_bounded(
    tmp_path: Path,
) -> None:
    if TYPE_CHECKING:
        from scripts import validate_development_foundation_plan as validator
    else:
        validator = _foundation_plan_validator()
    backend = tmp_path / "backend.hcl"
    backend.write_text(validator.EXPECTED_BACKEND)
    source_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    validator.validate_context(
        "903859731897", "us-east-1", backend, source_revision, REPO_ROOT
    )
    for account, region in (
        ("920534282028", "us-east-1"),
        ("903859731897", "us-west-2"),
    ):
        with pytest.raises(validator.ValidationError):
            validator.validate_context(
                account, region, backend, source_revision, REPO_ROOT
            )
    backend.write_text(validator.EXPECTED_BACKEND + "extra = true\n")
    with pytest.raises(validator.ValidationError):
        validator.validate_context(
            "903859731897", "us-east-1", backend, source_revision, REPO_ROOT
        )

    backend.write_text(validator.EXPECTED_BACKEND)
    plan_file = tmp_path / "foundation.json"
    plan_file.write_text(json.dumps({"resource_changes": []}))
    # The CLI must not invent a context when any required binding is absent.
    cli = [
        sys.executable,
        str(DEVELOPMENT_FOUNDATION_PLAN_VALIDATOR),
        str(plan_file),
        "--account",
        "903859731897",
        "--region",
        "us-east-1",
        "--backend",
        str(backend),
        "--source-revision",
        source_revision,
        "--source-root",
        str(REPO_ROOT),
        "--final-snapshot-identifier",
        "nova-toll-db-development-cutover-20260904t150735z",
    ]
    assert (
        subprocess.run(cli, check=False, capture_output=True, text=True).returncode == 1
    )
    for option in (
        "--account",
        "--region",
        "--backend",
        "--source-revision",
        "--source-root",
        "--final-snapshot-identifier",
    ):
        missing = cli.copy()
        index = missing.index(option)
        del missing[index : index + 2]
        result = subprocess.run(missing, check=False, capture_output=True, text=True)
        assert result.returncode != 0

    baseline = subprocess.run(
        ["git", "show", "HEAD:infra/policy.hujson"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    old_host = (
        '        "nova-toll-rds-development": "fd7a:115c:a1e0:b1a:0:1:ac1f:e1a2/128",'
    )
    new_host = (
        '        "nova-toll-rds-development": "fd7a:115c:a1e0:b1a:0:1:ac1f:5aa/128",'
    )
    refreshed = baseline.replace(old_host, new_host)
    changes = [
        line
        for line in difflib.unified_diff(
            baseline.splitlines(), refreshed.splitlines(), lineterm=""
        )
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
    ]
    assert changes == [f"-{old_host}", f"+{new_host}"]
    assert '"tag:ci-development"' in refreshed
    assert '"tag:nova-toll-router"' in refreshed


def test_development_foundation_runbook_shell_blocks_initialize_handoffs() -> None:
    handoff = DEPLOYMENT.split("### Development foundation replacement handoff", 1)[
        1
    ].split("### Guarded production release", 1)[0]
    shells = re.findall(r"(?m)^[ \t]*~~~sh\n(.*?)\n[ \t]*~~~", handoff, re.DOTALL)
    assert len(shells) == 8
    for shell in shells:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write(shell)
            script.flush()
            assert (
                subprocess.run(["bash", "-n", script.name], check=False).returncode == 0
            )

    fresh, seed_plan, seed_apply, step1, step2, step3, step4, step5 = shells
    assert fresh.index('RDS_METADATA="') < fresh.index("$RDS_METADATA")
    override_write = (
        "printf '%s\\n' 'resource \"aws_db_instance\" \"main\" {' "
        "'  db_name = \"nova_toll\"' '}' >\"$STATE_SEED_OVERRIDE\""
    )
    assert override_write in seed_plan
    assert (
        'test "$(sha256sum "$STATE_SEED_OVERRIDE" | awk \'{print $1}\')" = '
        '"83b2e8a3380f4a8063248207cf0a41f43b3a8ccb64076bc7852c25d30118bb84"'
        in seed_plan
    )
    assert (
        seed_plan.index('cp -a "$ROOT/infra/." "$STATE_SEED_ROOT/"')
        < seed_plan.index(
            'chmod 700 -- "$STATE_SEED_ROOT"',
            seed_plan.index('cp -a "$ROOT/infra/." "$STATE_SEED_ROOT/"'),
        )
        < seed_plan.index(override_write)
    )
    assert "-var environment=development" in seed_plan
    assert "--mode state-seed" in seed_plan
    assert '--rds-instance-arn "$RDS_INSTANCE_ARN"' in seed_plan
    assert '--rds-resource-id "$RDS_RESOURCE_ID"' in seed_plan
    assert ".[0].deletion_protection == true" in seed_plan
    assert "--no-deletion-protection" not in seed_plan
    assert "terraform apply" not in seed_plan
    toolchain_digests = (
        "8b6cb96cd46080ee1287baf646c70078715a99123b9b3a6ce2a7fe3892ec703a",
        "798415e2b72a761023f0ee096521a29223173428c99de7e4c50103e726eef4d8",
        "b785b4ee3b3274867b54a336889aab8a3477f6d20cc3cc45105c940b4436b012",
        "276b0d0b0fd0dbc3aab02006224b09c8edec889685167b1017fb05567c9e9318",
    )
    for shell in (seed_plan, seed_apply):
        for digest in toolchain_digests:
            assert digest in shell
        assert 'terraform_version\')" = "1.15.8"' in shell
        assert 'cmp -s -- "$ROOT/infra/.terraform.lock.hcl"' in shell
    seed_plan_command = seed_plan.index(
        'terraform -chdir="$STATE_SEED_ROOT" plan -input=false'
    )
    assert seed_plan.index("terraform-provider-aws_v6.58.0_x5") < seed_plan_command
    assert seed_plan.index("terraform-provider-archive_v2.8.0_x5") < seed_plan_command
    assert ".prior_state.values" in seed_plan
    assert "STATE_BEFORE_NORMALIZED_SHA256=" in seed_plan
    assert "STATE_SEED_PLAN_JSON_SHA256=" in seed_plan

    seed_binary_hash = seed_apply.index(
        'sha256sum "$STATE_SEED_ROOT/development-state-seed.tfplan"'
    )
    apply_json_show = seed_apply.index('terraform -chdir="$STATE_SEED_ROOT" show -json')
    apply_json_hash = seed_apply.index(
        'sha256sum "$STATE_SEED_APPLY_JSON"', apply_json_show
    )
    seed_validator = seed_apply.index(
        "validate_development_foundation_plan.py", apply_json_hash
    )
    immediate_identity = seed_apply.index('RDS_IMMEDIATE_PRE_SEED="$(aws')
    trap_install = seed_apply.index(
        "trap verify_state_seed_preboundary EXIT HUP INT TERM"
    )
    seed_boundary = seed_apply.index("STATE_SEED_APPLY_STARTED=1")
    seed_apply_command = seed_apply.index(
        'terraform -chdir="$STATE_SEED_ROOT" apply -input=false'
    )
    assert (
        seed_binary_hash
        < trap_install
        < apply_json_show
        < apply_json_hash
        < seed_validator
        < immediate_identity
        < seed_boundary
        < seed_apply_command
        < seed_apply.rindex("trap - EXIT HUP INT TERM")
    )
    assert '"$STATE_SEED_APPLY_JSON"' in seed_apply[seed_validator:immediate_identity]
    for binding in (
        "DBInstanceArn",
        "DbiResourceId",
        "PendingModifiedValues",
        '.[0].identifier == "nova-toll-db"',
        '.[0].status == "available"',
        '.[0].db_name == "nova_toll"',
        ".[0].private == false",
        ".[0].deletion_protection == true",
        ".[0].arn == $arn",
        ".[0].resource_id == $resource_id",
        '.[0].pending | type == "object" and length == 0',
    ):
        assert binding in seed_apply[immediate_identity:seed_boundary]
    assert (
        seed_apply.rindex("sts get-caller-identity", immediate_identity, seed_boundary)
        > immediate_identity
    )
    assert "--mode state-seed" in seed_apply
    assert ".[0].final_snapshot_identifier == $snapshot" in seed_apply
    assert "STATE_AFTER_NORMALIZED_SHA256=" in seed_apply
    assert (
        'test "$STATE_AFTER_NORMALIZED_SHA256" = '
        '"$STATE_BEFORE_NORMALIZED_SHA256"' in seed_apply
    )
    assert seed_apply.index(
        'terraform -chdir="$STATE_SEED_ROOT" state pull'
    ) < seed_apply.index('test "$STATE_AFTER_NORMALIZED_SHA256"')
    assert "--no-deletion-protection" not in seed_apply
    assert 'mv -- "$STATE_SEED_ROOT/development-state-seed_override.tf"' in seed_apply
    assert "new private plan root copied from the clean merged source" in handoff
    snapshot_assignment = (
        'DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER="nova-toll-db-development-cutover-'
    )
    assert handoff.count(snapshot_assignment) == 1
    assert (
        ': "${DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER:?retain the exact phase-1 snapshot identifier}"'
        in step1
    )
    assert snapshot_assignment not in step1
    assert step1.index('ROOT="$(git rev-parse --show-toplevel)"') < step1.index(
        'git -C "$ROOT"'
    )
    assert step1.index(': "${REVIEWED_SOURCE_REVISION:?') < step1.index(
        "printf '%s\\n' \"$REVIEWED_SOURCE_REVISION\""
    )
    assert step2.index("APPLY_STARTED=0") < step2.index('test "$APPLY_STARTED"')
    step2_binding = step2.index(
        "export AWS_PROFILE=nova-toll-dev AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1"
    )
    assert step2_binding < step2.index("trap restore_deletion_protection")
    assert step2.index(
        'test "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"'
    ) < step2.index("trap restore_deletion_protection")
    assert step2.index('RDS_METADATA="$(aws --region us-east-1 rds') < step2.index(
        "--no-deletion-protection"
    )
    assert (
        '.[0].identifier == "nova-toll-db"'
        ' and .[0].status == "available"'
        ' and .[0].db_name == "nova_toll"'
        " and .[0].private == false"
        " and .[0].deletion_protection == true"
    ) in step2
    assert (
        step2.count(
            'AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" aws'
        )
        == 4
    )
    assert (
        step2.index("aws --region us-east-1 rds wait db-instance-available")
        < step2.index(
            'RDS_DISABLED_METADATA="$(aws --region us-east-1 rds describe-db-instances'
        )
        < step2.rindex("trap - EXIT HUP INT TERM")
    )
    for binding in (
        "DBInstanceArn",
        "DbiResourceId",
        "PendingModifiedValues",
        'RDS_INSTANCE_ARN="$(jq -er',
        'RDS_RESOURCE_ID="$(jq -er',
        '.[0].arn == "arn:aws:rds:us-east-1:903859731897:db:nova-toll-db"',
        ".[0].deletion_protection == false",
    ):
        assert binding in step2
    assert step3.index('ROOT="$(git rev-parse --show-toplevel)"') < step3.index(
        'git -C "$ROOT"'
    )
    assert step3.index('PLAN_ROOT="$(mktemp -d)"') < step3.index(
        'chmod 700 -- "$PLAN_ROOT"'
    )
    assert "-var fetcher_package_path=build/fetcher.zip" in step3
    assert (
        '-var development_final_snapshot_identifier="$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER"'
        in step3
    )
    assert (
        '--final-snapshot-identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER"' in step3
    )
    assert "describe-db-snapshots" in step1
    assert "--snapshot-type manual" in step1
    assert "8416e465447d00eb730ee0aa215dcd7f97d182b0357db04948f58a29b08786c7" in handoff
    assert "permanently unusable" in handoff
    trap_install = step4.index("trap restore_deletion_protection EXIT HUP INT TERM")
    plan_root_binding = step4.index(': "${PLAN_ROOT:?')
    tf_data_export = step4.index('export TF_DATA_DIR="$PLAN_ROOT/.terraform-data"')
    plan_root_guard = step4.index('test "$(stat -c \'%a\' -- "$PLAN_ROOT")" = "700"')
    tf_data_guard = step4.index('test -d "$TF_DATA_DIR"')
    provider_guard = step4.index('test -d "$TF_DATA_DIR/providers"')
    pre_apply_gates = (
        ': "${REVIEWED_PLAN_SHA256:?',
        'sha256sum "$PLAN_ROOT/development-foundation.tfplan"',
        "sts get-caller-identity",
        "describe-db-snapshots",
        "validate_development_foundation_plan.py",
        'RDS_PRE_APPLY_METADATA="$(aws',
        "APPLY_STARTED=1",
        'terraform -chdir="$PLAN_ROOT" apply',
    )
    assert (
        trap_install
        < plan_root_binding
        < tf_data_export
        < plan_root_guard
        < tf_data_guard
        < provider_guard
    )
    assert all(provider_guard < step4.index(gate) for gate in pre_apply_gates)
    assert "describe-db-snapshots" in step4
    assert (
        '--final-snapshot-identifier "$DEVELOPMENT_FINAL_SNAPSHOT_IDENTIFIER"' in step4
    )
    pre_apply_identity = step4.index('RDS_PRE_APPLY_METADATA="$(aws')
    apply_boundary = step4.index("APPLY_STARTED=1")
    assert pre_apply_identity < apply_boundary
    for binding in (
        ".[0].arn == $arn",
        ".[0].resource_id == $resource_id",
        '.[0].arn == "arn:aws:rds:us-east-1:903859731897:db:nova-toll-db"',
        ".[0].deletion_protection == false",
        '.[0].pending | type == "object" and length == 0',
    ):
        assert binding in step4[pre_apply_identity:apply_boundary]
    assert step4.rindex(
        "sts get-caller-identity", pre_apply_identity, apply_boundary
    ) > (pre_apply_identity)
    assert step5.index('RDS_ENDPOINT="$(aws') < step5.index(
        'getent ahostsv4 "$RDS_ENDPOINT"'
    )


def _assert_slice_2b_connectivity_workflow(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    trigger = workflow_trigger(workflow)
    assert isinstance(trigger, dict)
    trigger = cast(dict[str, object], trigger)
    assert set(trigger) == {"workflow_dispatch"}
    dispatch = cast(dict[str, object], trigger["workflow_dispatch"])
    phase = cast(dict[str, object], dispatch["inputs"])["phase"]
    assert phase == {
        "description": "read-only route diagnostic, pre-bootstrap route/transport proof, or post-bootstrap full proof",
        "required": False,
        "default": "full",
        "type": "choice",
        "options": ["route-diagnostic", "pre-bootstrap", "full"],
    }
    assert workflow["permissions"] == {"contents": "read"}
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {"verify"}
    job = jobs["verify"]
    assert job["if"] == (
        "github.ref == 'refs/heads/main' && github.actor_id == '91573985' "
        "&& github.triggering_actor == github.actor"
    )
    assert job["environment"] == "development"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    steps = cast(list[dict[str, object]], job["steps"])
    assert {
        *re.findall(r"secrets\.([A-Z0-9_]+)", source),
    } == {
        "TS_DEVELOPMENT_OAUTH_CLIENT_ID",
        "TS_DEVELOPMENT_OAUTH_SECRET",
        "TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID",
        "TS_DEVELOPMENT_ROUTE_OAUTH_SECRET",
    }
    assert "tags: tag:ci-development" in source
    assert "arn:aws:iam::903859731897:role/nova-toll-v2-timed-checks-dev" in source
    assert "DEVELOPMENT_DELIVERY_ENABLED" not in source
    assert "refs/heads/main" in source
    assert "aws rds describe-db-instances" in source
    assert "getent ahostsv4" in source
    assert "tailscale debug via 1" in source
    assert "ipaddress.ip_address" in source
    assert 'ipaddress.ip_network(f"{expected}/128"' in source
    assert 'PGHOST="$DB_HOST"' in source
    assert 'PGHOSTADDR="$TRANSPORT_IPV6"' in source
    assert "PGSSLMODE=verify-full" in source
    assert 'PGSSLROOTCERT="$RDS_CA_BUNDLE"' in source
    assert "generate-db-auth-token" in source
    assert "SELECT current_database(), current_user" in source
    assert "VERIFICATION_PHASE" in source
    assert "pre-bootstrap" in source
    assert "TRANSPORT_ROUTE_JSON" in source
    assert "pre_bootstrap_route_transport_valid" in source
    assert "socket.create_connection" in source
    assert 'route.get("dev") != "tailscale0"' in source
    assert source.index(
        'if test "$VERIFICATION_PHASE" = pre-bootstrap; then'
    ) < source.index("export PGHOST=")
    assert "nova_toll_development" in source
    assert "pricing_caller_development" in source
    assert "PRODUCTION_DB_HOST" in source
    assert (
        "PRODUCTION_DB_HOST: nova-toll-db.co9qkm4eqi2h.us-east-1.rds.amazonaws.com"
        in source
    )
    assert "PROD_ROUTE_STATE" in source
    assert 'ip -json route get "$prod_ipv4"' in source
    assert 'device == "tailscale0"' in source
    assert 'test "$PROD_ROUTE_STATE" = expected-denial' in source
    assert (
        "test \"$PROD_DENIAL_STATE\" = $'route=expected-denial\\nsocket=expected-denial'"
        in source
    )
    assert 'if ! prod_route_json="$(ip -json route get "$prod_ipv4")"; then' in source
    assert 'if ! test -n "$prod_route_json"; then' in source
    assert (
        'if ! route_state="$(PROD_IPV4="$prod_ipv4" ROUTE_JSON="$prod_route_json" python3 - <<\'PY\''
        in source
    )
    assert 'if ! test "$route_state" = expected-denial; then' in source
    assert 'if ! socket_state="$(timeout 3s python3 - "$prod_ipv4"' in source
    assert "except TimeoutError:" in source
    for expected_errno in (
        "errno.EACCES",
        "errno.ECONNREFUSED",
        "errno.EHOSTUNREACH",
        "errno.ENETUNREACH",
        "errno.EPERM",
    ):
        assert expected_errno in source
    assert 'if ! test "$socket_state" = expected-denial; then' in source
    assert (
        'if ! PROD_DENIAL_STATE="$(verify_production_denial "$PROD_IPV4")"; then'
        in source
    )
    assert (
        "if ! test \"$PROD_DENIAL_STATE\" = $'route=expected-denial\\nsocket=expected-denial'; then"
        in source
    )
    assert "|| true" not in source
    assert "timeout 3s" in source
    assert "socket.create_connection" in source
    assert "production_socket_denied" in source
    assert "GITHUB_STEP_SUMMARY" in source
    assert "set +x" in source
    assert "unset DB_TOKEN PGPASSWORD" in source
    assert "DB_JSON" in source and 'echo "$DB_JSON"' not in source
    assert 'echo "$VIA_OUTPUT"' not in source
    assert "tee" not in source
    assert "--with-decryption" not in source
    for forbidden in (
        "TS_OAUTH_",
        "TS_ACL_OAUTH_",
        "tags: tag:ci\n",
        "nova-toll-v2-development-delivery",
        "terraform",
        "aws iam",
        "aws cloudformation",
        "production SQL",
    ):
        assert forbidden not in source
    for step in steps:
        if "uses" in step:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", cast(str, step["uses"]))

    diagnostic_step = source.split(
        "- name: Diagnose development Tailscale route", maxsplit=1
    )[1].split("- uses: aws-actions/configure-aws-credentials", maxsplit=1)[0]
    assert "if: inputs.phase == 'route-diagnostic'" in diagnostic_step
    assert "--read-only" in diagnostic_step
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_" in diagnostic_step
    assert "TS_DEVELOPMENT_OAUTH_" not in diagnostic_step
    assert "GITHUB_STEP_SUMMARY" in diagnostic_step
    for forbidden in (
        "tailscale/github-action",
        "Approve development Tailscale route",
        "POST /device/",
        "timed-checks",
        "tailscale debug via",
        "psql",
        "socket.create_connection",
    ):
        assert forbidden not in diagnostic_step
    assert (
        source.count(
            "if: inputs.phase == 'pre-bootstrap' || inputs.phase == 'full' || inputs.phase == ''"
        )
        == 4
    )
    assert "inputs.phase != 'route-diagnostic'" not in source


def test_slice_2b_connectivity_workflow_is_manual_main_only_and_dev_scoped() -> None:
    _assert_slice_2b_connectivity_workflow(DEVELOPMENT_CONNECTIVITY_WORKFLOW)
    for original, replacement in (
        ("workflow_dispatch:", "push:"),
        ("github.ref == 'refs/heads/main'", "github.ref == 'refs/heads/release'"),
        (" && github.actor_id == '91573985'", ""),
        ("github.actor_id == '91573985'", "github.actor_id == '123456'"),
        ("&& github.actor_id == '91573985'", "|| github.actor_id == '91573985'"),
        ("github.actor_id == '91573985'", "github.actor == 'owner'"),
        (" && github.triggering_actor == github.actor", ""),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == 'owner'",
        ),
        (
            "&& github.triggering_actor == github.actor",
            "|| github.triggering_actor == github.actor",
        ),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == github.actor && github.actor_id == '123456'",
        ),
        ("environment: development", "environment: production"),
        ("TS_DEVELOPMENT_OAUTH_CLIENT_ID", "TS_OAUTH_CLIENT_ID"),
        ("tag:ci-development", "tag:ci"),
        ("PGSSLMODE=verify-full", "PGSSLMODE=disable"),
        (
            "PRODUCTION_DB_HOST: nova-toll-db.co9qkm4eqi2h.us-east-1.rds.amazonaws.com",
            "PRODUCTION_DB_HOST: evil.example",
        ),
    ):
        must_reject(
            _assert_slice_2b_connectivity_workflow,
            DEVELOPMENT_CONNECTIVITY_WORKFLOW,
            original,
            replacement,
        )


def test_slice_2b_production_denial_uses_os_route_and_bounded_socket_failures() -> None:
    function = re.search(
        r"(?ms)^          verify_production_denial\(\) \{\n(.*?)^          \}\n          if ! PROD_DENIAL_STATE=",
        DEVELOPMENT_CONNECTIVITY_WORKFLOW,
    )
    assert function is not None
    shell_function = (
        dedent("verify_production_denial() {\n") + dedent(function.group(1)) + "}\n"
    )
    harness = dedent(
        f"""
        set -euo pipefail
        ROUTE_MODE=${{ROUTE_MODE:?}}
        SOCKET_MODE=${{SOCKET_MODE:?}}
        ip() {{
          case "$ROUTE_MODE" in
            expected) printf '[{{"dst":"192.0.2.10","gateway":"192.0.2.1","dev":"eth0"}}]' ;;
            tailscale) printf '[{{"dst":"192.0.2.10","dev":"tailscale0"}}]' ;;
            multiple) printf '[{{"dst":"192.0.2.10","dev":"eth0"}},{{"dst":"192.0.2.10","dev":"eth1"}}]' ;;
            empty) return 0 ;;
            malformed) printf 'diagnostic unavailable' ;;
            failure) return 1 ;;
            *) return 2 ;;
          esac
        }}
        timeout() {{
          cat >/dev/null
          case "$SOCKET_MODE" in
            refused|timed-out|unreachable|denied) printf 'expected-denial' ;;
            connected|generic) return 1 ;;
            *) return 2 ;;
          esac
        }}
        {shell_function}
        if ! PROD_DENIAL_STATE="$(verify_production_denial 192.0.2.10)"; then
          exit 1
        fi
        if ! test "$PROD_DENIAL_STATE" = $'route=expected-denial\\nsocket=expected-denial'; then
          exit 1
        fi
        printf '%s\\n' "$PROD_DENIAL_STATE"
        """
    )

    def run(route_mode: str, socket_mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", harness],
            env={**os.environ, "ROUTE_MODE": route_mode, "SOCKET_MODE": socket_mode},
            text=True,
            capture_output=True,
            check=False,
        )

    for socket_mode in ("refused", "timed-out", "unreachable", "denied"):
        positive = run("expected", socket_mode)
        assert positive.returncode == 0, (socket_mode, positive.stderr)
        assert positive.stdout == "route=expected-denial\nsocket=expected-denial\n"

    for route_mode, socket_mode in (
        ("failure", "generic"),
        ("failure", "refused"),
        ("tailscale", "refused"),
        ("multiple", "refused"),
        ("expected", "generic"),
        ("expected", "connected"),
        ("empty", "refused"),
        ("malformed", "refused"),
    ):
        result = run(route_mode, socket_mode)
        assert result.returncode != 0, (
            route_mode,
            socket_mode,
            result.stdout,
            result.stderr,
        )


def test_slice_2b_runbook_documents_bounded_secret_route_and_activation_gates() -> None:
    for required in (
        "one-off",
        "non-ephemeral",
        "pre-approved",
        "90 days",
        "tag:nova-toll-development-router",
        "/nova-toll/tailscale-authkey",
        "i-0d33b9a9c15db93fc",
        "AWS-RunShellScript",
        "tailscale up --authkey",
        'tailscale set --advertise-routes=""',
        'tailscale set --advertise-routes=\\"\\"',
        "advertisedRoutes",
        "enabledRoutes",
        "TS_DEVELOPMENT_OAUTH_CLIENT_ID",
        "TS_DEVELOPMENT_OAUTH_SECRET",
        "auth_keys",
        "DEVELOPMENT_DELIVERY_ENABLED",
        "DEVELOPMENT_DELIVERY_ENABLED == 'true'",
        "workflow_dispatch",
        "route-diagnostic",
        "repository variable",
        "gh variable set DEVELOPMENT_DELIVERY_ENABLED --body true",
        "PGHOST",
        "PGHOSTADDR",
        "PGSSLMODE=verify-full",
        "current_database(), current_user",
        "gh variable delete DEVELOPMENT_DELIVERY_ENABLED",
        "No rollback action mutates production.",
    ):
        assert required in DEPLOYMENT
    assert (
        "/environments/development/variables/DEVELOPMENT_DELIVERY_ENABLED"
        not in DEPLOYMENT
    )
    assert (
        "--advertise-exit-node"
        not in DEPLOYMENT.split(
            "#### Slice 2B development router and protected connectivity handoff", 1
        )[1]
    )


def test_development_foundation_archive_is_non_operative_and_links_replacement() -> (
    None
):
    assert DEVELOPMENT_FOUNDATION_330.startswith(
        "### Development foundation handoff (#330; no application release)"
    )
    assert "historical, superseded" in DEVELOPMENT_FOUNDATION_330
    assert "Do not run the historical procedure" in DEVELOPMENT_FOUNDATION_330
    assert (
        "[current #327/#333 replacement handoff](development-foundation-replacement.md)"
        in DEVELOPMENT_FOUNDATION_330
    )
    assert "```" not in DEVELOPMENT_FOUNDATION_330
    assert "~~~" not in DEVELOPMENT_FOUNDATION_330

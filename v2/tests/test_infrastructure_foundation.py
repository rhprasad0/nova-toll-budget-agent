import json
import os
import re
import subprocess
from copy import deepcopy
from textwrap import dedent
from typing import cast

import pytest
import yaml

from tests.infrastructure_support import (
    ACCOUNT_CONTRACT,
    APPLICATION_VARIABLES,
    DEVELOPMENT_CONNECTIVITY_WORKFLOW,
    DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW,
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
    MAIN_TF,
    REPO_ROOT,
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


def test_application_tfvars_persist_no_resource_ids() -> None:
    for tfvars in (V2_ROOT / "infra").glob("*.tfvars"):
        assert "vpc-" not in tfvars.read_text()
        assert "subnet-" not in tfvars.read_text()
        assert "sg-" not in tfvars.read_text()
        assert "arn:aws" not in tfvars.read_text()


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
    assert _foundation_validator_keys(workflow_predicate) == [
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
        assert _jq_validator_accepts(workflow_predicate, payload) is expected, label


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


@pytest.mark.parametrize(
    "name",
    [
        "development-foundation-330-archive.md",
        "development-foundation-replacement.md",
        "development-bootstrap-import.md",
        "development-release.md",
        "legacy-development-retirement.md",
    ],
)
def test_historical_runbooks_are_non_operative_permalinked_stubs(name: str) -> None:
    stub = (V2_ROOT / "runbooks" / name).read_text()
    assert "historical" in stub.splitlines()[0]
    assert "Do not run the historical procedure" in stub
    assert "https://github.com/rhprasad0/nova-toll-budget-agent/blob/" in stub
    assert "```" not in stub
    assert "~~~" not in stub

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest
import yaml

V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
MAIN_TF = (V2_ROOT / "infra" / "main.tf").read_text()
PUBLISHER_HANDLER = (V2_ROOT / "lambdas" / "publisher" / "handler.py").read_text()
ENVIRONMENT_TF = (V2_ROOT / "infra" / "environment.tf").read_text()
SITE_TF = (V2_ROOT / "infra" / "site.tf").read_text()
DEVELOPMENT_TFVARS = (V2_ROOT / "infra" / "development.tfvars").read_text()
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
DEVELOPMENT_DELIVERY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-delivery.yml"
).read_text()
DEVELOPMENT_CONNECTIVITY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-connectivity-verification.yml"
).read_text()
FOUNDATION_DNS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-production-foundation-dns.yml"
).read_text()
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


def _balanced_text(source: str, start: int, opening: str, closing: str) -> str:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return source[start + 1 : index]
    raise AssertionError(f"unclosed HCL delimiter {opening!r}")


def _hcl_named_blocks(source: str, name: str) -> list[str]:
    pattern = re.compile(rf"(?m)^\s*{re.escape(name)}\s*\{{")
    blocks: list[str] = []
    for match in pattern.finditer(source):
        opening = source.find("{", match.start(), match.end())
        blocks.append(_balanced_text(source, opening, "{", "}"))
    return blocks


def _hcl_attribute(source: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*", source)
    if not match:
        return ""
    start = match.end()
    while start < len(source) and source[start].isspace():
        start += 1
    if start < len(source) and source[start] == "[":
        return _balanced_text(source, start, "[", "]")
    quoted = re.match(r'"(?:\\.|[^"\\])*"', source[start:])
    if quoted:
        return quoted.group(0)
    return source[start:].splitlines()[0].strip()


def _hcl_strings(expression: str) -> list[str]:
    return [json.loads(value) for value in re.findall(r'"(?:\\.|[^"\\])*"', expression)]


def _hcl_values(expression: str) -> list[str]:
    if expression.startswith("concat("):
        return []
    values: list[str] = []
    for value in expression.split(","):
        value = value.strip()
        if not value:
            continue
        values.append(json.loads(value) if value.startswith('"') else value)
    return values


def _hcl_scalar(source: str, name: str) -> str:
    values = _hcl_strings(_hcl_attribute(source, name))
    return values[0] if values else ""


def _parsed_policy_document(source: str, name: str) -> list[dict[str, object]]:
    document = terraform_block(source, f'data "aws_iam_policy_document" "{name}"')
    statements: list[dict[str, object]] = []
    for statement in _hcl_named_blocks(document, "statement"):
        conditions: list[dict[str, object]] = []
        for condition in _hcl_named_blocks(statement, "condition"):
            conditions.append(
                {
                    "test": _hcl_scalar(condition, "test"),
                    "variable": _hcl_scalar(condition, "variable"),
                    "values": _hcl_strings(_hcl_attribute(condition, "values")),
                }
            )
        statements.append(
            {
                "sid": _hcl_scalar(statement, "sid"),
                "actions": _hcl_strings(_hcl_attribute(statement, "actions")),
                "resources": _hcl_values(_hcl_attribute(statement, "resources")),
                "conditions": conditions,
            }
        )
    return statements


def _policy_by_sid(statements: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {cast(str, statement["sid"]): statement for statement in statements}


def _top_level_terraform_block(source: str, header: str, occurrence: int = 0) -> str:
    matches = list(re.finditer(rf"(?m)^{re.escape(header)}\s*\{{", source))
    if occurrence >= len(matches):
        raise AssertionError(f"missing Terraform block {header!r}")
    match = matches[occurrence]
    opening = source.find("{", match.start(), match.end())
    depth = 0
    quoted = False
    escaped = False
    for index in range(opening, len(source)):
        character = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"unclosed Terraform block {header!r}")


def _terraform_rendered_development_delivery_policies() -> tuple[
    dict[str, dict[str, object]], list[dict[str, object]]
]:
    """Render the policy locals in a backend-free, credential-free Terraform root."""
    first_locals = _top_level_terraform_block(FOUNDATION_IAM, "locals", 0)
    policy_locals = _top_level_terraform_block(FOUNDATION_IAM, "locals", 1)
    policy_data = _top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_delivery"',
    )
    policy_data = policy_data.replace(
        "aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn"
    ).replace("aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn")
    configuration = dedent(
        f"""
        terraform {{
          required_providers {{
            aws = {{
              source  = "hashicorp/aws"
              version = "~> 6.47"
            }}
          }}
        }}

        provider "aws" {{
          region                         = "us-east-1"
          skip_credentials_validation   = true
          skip_requesting_account_id    = true
          skip_region_validation        = true
          skip_metadata_api_check       = true
        }}

        locals {{
          test_tfstate_bucket_arn = "arn:aws:s3:::nova-toll-tfstate-903859731897"
          test_tfstate_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/00000000-0000-0000-0000-000000000000"
        }}

        {first_locals}
        {policy_data}
        {policy_locals}

        output "development_delivery_policy_documents" {{
          value = local.development_delivery_policy_documents
        }}

        output "development_delivery_aggregate" {{
          value = data.aws_iam_policy_document.development_delivery.json
        }}
        """
    )
    with tempfile.TemporaryDirectory(prefix="nova-toll-iam-render-") as directory:
        root = Path(directory)
        (root / "main.tf").write_text(configuration, encoding="utf-8")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AWS_")
        }
        environment["TF_DATA_DIR"] = str(root / ".terraform-data")
        provider_mirror = FOUNDATION_ROOT / ".terraform" / "providers"
        if provider_mirror.is_dir():
            cli_config = root / "terraform.tfrc"
            cli_config.write_text(
                dedent(
                    f"""
                    provider_installation {{
                      filesystem_mirror {{
                        path = {json.dumps(str(provider_mirror))}
                      }}
                      direct {{
                        exclude = ["hashicorp/aws"]
                      }}
                    }}
                    """
                ),
                encoding="utf-8",
            )
            environment["TF_CLI_CONFIG_FILE"] = str(cli_config)
        init = subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert init.returncode == 0, init.stdout + init.stderr
        plan_path = root / "development-delivery.tfplan"
        plan = subprocess.run(
            [
                "terraform",
                "plan",
                "-refresh=false",
                "-input=false",
                "-no-color",
                f"-out={plan_path}",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert plan.returncode == 0, plan.stdout + plan.stderr
        rendered = subprocess.run(
            ["terraform", "show", "-json", str(plan_path)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        values = json.loads(rendered.stdout)["planned_values"]["outputs"]
        documents = values["development_delivery_policy_documents"]["value"]
        aggregate = values["development_delivery_aggregate"]["value"]
        assert isinstance(documents, dict)
        assert isinstance(aggregate, str)
        return (
            {
                key: json.loads(value)
                for key, value in cast(dict[str, str], documents).items()
            },
            cast(list[dict[str, object]], json.loads(aggregate)["Statement"]),
        )


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


def test_account_local_backends_keep_production_paths_and_lockfiles_distinct():
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


def test_all_backends_pin_native_kms_encryption_and_locking():
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


def test_provider_account_guards_derive_from_the_account_contract():
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


def test_tfstate_bucket_is_hardened_and_denies_foreign_accounts():
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
    assert "s3:x-amz-server-side-encryption" not in policy
    assert "920534282028" not in policy
    assert "policy" not in key
    assert "enable_key_rotation     = true" in key
    assert "deletion_window_in_days = 30" in key


def test_foundation_names_and_budget_use_the_caller_account():
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
    foundation_terraform = "".join(
        path.read_text() for path in FOUNDATION_ROOT.glob("*.tf")
    )
    assert foundation_terraform.count("920534282028") == 1
    assert "cloudflare-development-dns-api-token" in foundation_terraform


def test_foundation_output_and_application_input_are_the_exact_non_secret_boundary():
    output = (FOUNDATION_ROOT / "outputs.tf").read_text()
    variable = APPLICATION_VARIABLES.split('variable "foundation"', maxsplit=1)[
        1
    ].split('variable "environment"', maxsplit=1)[0]
    fields = (
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
    )
    assert output.count('output "foundation"') == 1
    assert output.count("output ") == 1
    assert "sensitive   = false" in output
    assert "sensitive = true" not in output
    assert "sensitive = true" not in variable
    assert "default" not in variable
    for field in fields:
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


def test_development_foundation_cannot_advertise_the_shared_vpc_route():
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


def test_v2_uses_the_typed_boundary_without_foundation_discovery():
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
        'data "aws_kms_alias"',
        'data "aws_db_instance"',
        'data "aws_sns_topic"',
        "nova-toll-raw-920534282028",
        "nova-toll-agentcore-920534282028",
    ):
        assert forbidden not in terraform_sources
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


def test_handoff_and_follow_on_ownership_are_documented_without_persisted_ids():
    runbook = DEPLOYMENT
    plan = (V2_ROOT / "plans" / "ENVIRONMENT-AND-RELEASE-PLAN.md").read_text()
    for text in (
        "terraform show -json",
        "planned_values.outputs.foundation.value",
        "*.tfvars.json",
        "jq -n --argjson foundation",
        '"foundation": $foundation',
        "review",
        "rm -f --",
    ):
        assert text in runbook
    for document in (runbook, plan):
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
            assert text in document
    assert "provide an operative development" in plan
    assert (
        "The bounded #331 application release and database validation below is the operative"
        in runbook
    )
    assert "local-backend plan generation and review" in runbook
    assert "later exact-plan apply" in runbook
    assert "separately authorized state migration or recovery" in runbook
    assert "not the guarded production release's `production.tfvars`" in runbook
    for tfvars in (V2_ROOT / "infra").glob("*.tfvars"):
        assert "vpc-" not in tfvars.read_text()
        assert "subnet-" not in tfvars.read_text()
        assert "sg-" not in tfvars.read_text()
        assert "arn:aws" not in tfvars.read_text()

    development = runbook.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    development_plan_stage = development.split(
        "#### Later authorized exact-plan apply and recovery", maxsplit=1
    )[0]
    later_apply = development.split(
        "#### Later authorized exact-plan apply and recovery", maxsplit=1
    )[1]
    production = runbook.split("### Guarded production release", maxsplit=1)[1].split(
        "The legacy development inventory", maxsplit=1
    )[0]
    assert (
        'test "$(AWS_PROFILE=nova-toll-dev aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"'
        in development_plan_stage
    )
    assert (
        'DEVELOPMENT_FOUNDATION_PLAN="$DEVELOPMENT_FOUNDATION_DIR/development-foundation.tfplan"'
        in development_plan_stage
    )
    assert 'chmod 700 -- "$DEVELOPMENT_FOUNDATION_DIR"' in development_plan_stage
    assert 'chmod 600 -- "$DEVELOPMENT_FOUNDATION_PLAN"' in development_plan_stage
    assert "init -backend=false -input=false" in development_plan_stage
    assert (
        '-var fetcher_package_path="$DEVELOPMENT_FETCHER_PACKAGE"'
        in development_plan_stage
    )
    assert 'show -json "$DEVELOPMENT_FOUNDATION_PLAN"' in development_plan_stage
    assert "sort_by(.address)" in development_plan_stage
    for forbidden in (
        "terraform apply",
        "terraform import",
        "terraform state list",
        "-migrate-state",
        "-backend-config",
        "-reconfigure",
        "terraform -target",
        "terraform_remote_state",
        "get-parameter",
        "cloudflare",
    ):
        assert forbidden not in development_plan_stage.lower()
    assert '"$DEVELOPMENT_FOUNDATION_VARS"' not in development_plan_stage
    assert 'TF_DATA_DIR="$ROOT/.terraform-data"' in later_apply
    assert 'FETCHER="$ROOT/build/fetcher.zip"' in later_apply
    assert 'terraform -chdir="$ROOT" apply -input=false "$PLAN"' in later_apply
    assert (
        'terraform -chdir="$ROOT" init -migrate-state -force-copy -input=false'
        in later_apply
    )
    assert 'cp -- "$ROOT/versions.tf.with-backend" "$ROOT/versions.tf"' in later_apply
    development_account_assertion = (
        'test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" sts '
        'get-caller-identity --query Account --output text)" = "$DEV_ACCOUNT"'
    )
    assert later_apply.count(development_account_assertion) == 2
    apply_command = 'TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" apply'
    recovery_command = 'TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" init -migrate-state'
    first_assertion = later_apply.index(development_account_assertion)
    second_assertion = later_apply.index(
        development_account_assertion,
        first_assertion + len(development_account_assertion),
    )
    assert first_assertion < later_apply.index(apply_command)
    assert second_assertion < later_apply.index(recovery_command)
    assert later_apply.index(development_account_assertion) < later_apply.index(
        apply_command
    )
    assert second_assertion < later_apply.index(recovery_command)

    assert 'PRODUCTION_FOUNDATION_PLAN="$(mktemp --suffix=.tfplan)"' in production
    assert 'PRODUCTION_FOUNDATION_VARS="$(mktemp --suffix=.tfvars.json)"' in production
    assert 'query Account --output text)" = "920534282028"' in production
    assert "backend.production.hcl" in production
    assert "planned_values.outputs.foundation.value" in production
    assert "-var-file=production.tfvars" in production
    for package_arg in (
        "-var loader_package_path=build/loader.zip",
        "-var publisher_package_path=build/publisher.zip",
        "-var agentcore_package_path=build/agentcore.zip",
        "-var chat_proxy_package_path=build/chat-proxy.zip",
    ):
        assert package_arg in production
    assert '"$FOUNDATION_VARS"' not in runbook
    assert "terraform output -json foundation" not in runbook
    assert '"$PRODUCTION_FOUNDATION_VARS"' in production


def test_development_foundation_shell_is_plan_only_and_retains_exact_handoff():
    development = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    shell_match = re.search(r"```sh\n(.*?)\n```", development, flags=re.DOTALL)
    assert shell_match is not None
    shell = shell_match.group(1)

    assert "umask 077" in shell
    assert 'DEVELOPMENT_FOUNDATION_DIR="$(mktemp -d)"' in shell
    assert 'chmod 700 -- "$DEVELOPMENT_FOUNDATION_DIR"' in shell
    assert 'test "$(stat -c \'%a\' "$DEVELOPMENT_FOUNDATION_DIR")" = "700"' in shell
    assert (
        'DEVELOPMENT_FOUNDATION_PLAN="$DEVELOPMENT_FOUNDATION_DIR/development-foundation.tfplan"'
        in shell
    )
    assert 'chmod 600 -- "$DEVELOPMENT_FOUNDATION_PLAN"' in shell
    assert 'test "$(stat -c \'%a\' "$DEVELOPMENT_FOUNDATION_PLAN")" = "600"' in shell
    assert (
        'DEVELOPMENT_TF_DATA_DIR="$DEVELOPMENT_FOUNDATION_DIR/.terraform-data"' in shell
    )
    assert 'export TF_DATA_DIR="$DEVELOPMENT_TF_DATA_DIR"' in shell
    assert 'rm -rf -- "$DEVELOPMENT_FOUNDATION_DIR/.terraform"' in shell
    assert "terraform.tfstate.d" in shell
    assert 'test ! -e "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate"' in shell
    assert 'test ! -e "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate.backup"' in shell
    assert (
        'sed -i \'/^[[:space:]]*backend "s3" {}/d\' "$DEVELOPMENT_FOUNDATION_DIR/versions.tf"'
        in shell
    )

    assert (
        'test "$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "920534282028"'
        in shell
    )
    assert (
        'test "$(AWS_PROFILE=nova-toll-dev aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"'
        in shell
    )
    terraform_commands = re.findall(
        r"(?m)^\s*(?:if ! )?AWS_PROFILE=([^\s]+) terraform\b", shell
    )
    assert terraform_commands
    assert set(terraform_commands) == {"nova-toll-dev"}
    assert "AWS_PROFILE=nova-toll-prod terraform" not in shell

    assert "init -backend=false -input=false" in shell
    assert "-reconfigure" not in shell
    assert "-migrate-state" not in shell
    assert "-backend-config" not in shell
    assert "-target" not in shell
    assert "terraform apply" not in shell
    assert "terraform import" not in shell
    assert "terraform state" not in shell
    assert "terraform_remote_state" not in shell
    assert "get-parameter" not in shell
    assert "cloudflare" not in shell.lower()
    assert "show -no-color" not in shell
    assert "planned_values" not in shell
    assert 'show -json "$DEVELOPMENT_FOUNDATION_PLAN"' in shell
    assert "| jq -e" in shell
    assert "jq -ce" in shell
    assert "sort_by(.address)" in shell
    assert "{address: .address, actions: .change.actions}" in shell
    assert "printf 'Development foundation root: %s\\n'" in shell
    assert "printf 'Development foundation plan SHA-256: %s\\n'" in shell
    assert "printf '%s\\n' \"$DEVELOPMENT_FOUNDATION_SUMMARY\"" in shell
    assert 'test -r "$ROOT/infra/build/fetcher.zip"' in shell
    assert 'test -s "$ROOT/infra/build/fetcher.zip"' in shell
    assert "set +x" in shell
    assert shell.index("set +x") < shell.index(
        "AWS_PROFILE=nova-toll-prod aws --region us-east-1 budgets"
    )
    assert shell.index(
        'AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" init'
    ) < shell.index(
        'AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" plan'
    )
    assert shell.index(
        'AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" plan'
    ) < shell.index(
        'AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" show'
    )
    assert (
        'rm -f -- "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"'
        in shell
    )
    assert 'rm -rf -- "$DEVELOPMENT_FOUNDATION_DIR"' not in shell
    assert 'rm -f -- "$DEVELOPMENT_FOUNDATION_PLAN"' not in shell
    assert '"$DEVELOPMENT_FOUNDATION_VARS"' not in shell


def test_development_absence_probes_fail_closed_on_unexpected_errors():
    development = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    shell = (
        development.split(
            "##### Successful exact-plan apply, migration, and evidence", maxsplit=1
        )[1]
        .split("```sh\n", maxsplit=1)[1]
        .split("\n```", maxsplit=1)[0]
    )
    helper_match = re.search(
        r"(expect_absent_error\(\) \{.*?^absent_budget\(\)[^\n]*\n)",
        shell,
        re.DOTALL | re.MULTILINE,
    )
    assert helper_match is not None
    helpers = helper_match.group(1)
    expected_errors = {
        "absent_s3_bucket": "404",
        "absent_kms_key": "NotFoundException",
        "absent_rds_instance": "DBInstanceNotFound",
        "absent_lambda_function": "ResourceNotFoundException",
        "absent_sns_topic": "NotFound",
        "absent_cloudtrail": "TrailNotFoundException",
        "absent_event_rule": "ResourceNotFoundException",
        "absent_iam_role": "NoSuchEntity",
        "absent_instance_profile": "NoSuchEntity",
        "absent_rds_subnet_group": "DBSubnetGroupNotFoundFault",
        "absent_oidc_provider": "NoSuchEntity",
        "absent_budget": "NotFoundException",
    }
    assert "expect_absent " not in shell
    for helper in expected_errors:
        assert f"{helper} " in shell

    def probe_status(helper: str, error: str) -> int:
        script = f"""{helpers}
probe() {{ printf '%s' '{error}' >&2; return 1; }}
{helper} probe
"""
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, check=False
        ).returncode

    for helper, expected_error in expected_errors.items():
        assert probe_status(helper, expected_error) == 0
        assert probe_status(helper, "AccessDenied") != 0
        assert probe_status(helper, "ExpiredToken") != 0


def test_development_foundation_reads_and_cleans_the_budget_recipient_ephemerally():
    development = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    shell = development.split("```sh\n", maxsplit=1)[1].split("\n```", maxsplit=1)[0]

    production_assertion = (
        'test "$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 sts '
        'get-caller-identity --query Account --output text)" = "920534282028"'
    )
    development_assertion = (
        'test "$(AWS_PROFILE=nova-toll-dev aws --region us-east-1 sts '
        'get-caller-identity --query Account --output text)" = "903859731897"'
    )
    assert production_assertion in shell
    assert development_assertion in shell
    assert shell.index(production_assertion) < shell.index(
        "describe-notifications-for-budget"
    )
    assert shell.index("describe-notifications-for-budget") < shell.index(
        "describe-subscribers-for-notification"
    )
    assert shell.index("describe-subscribers-for-notification") < shell.index(
        development_assertion
    )
    assert "describe-budget" not in shell
    assert "NotificationsWithSubscribers" not in shell
    assert "--account-id 920534282028" in shell
    assert "--budget-name nova-toll-monthly" in shell
    assert '--notification "$notification"' in shell
    assert 'DEVELOPMENT_BUDGET_RECIPIENTS="$(mktemp)"' in shell
    assert 'DEVELOPMENT_BUDGET_SUBSCRIBERS="$(mktemp)"' in shell
    assert "chmod 600 --" in shell
    assert "set +x" in shell
    assert "2>/dev/null" in shell
    assert "if ! jq -e '" in shell
    assert ".Subscribers[]?" in shell
    assert '.SubscriptionType == "EMAIL"' in shell
    assert "--output json" in shell
    assert "unique" in shell
    assert "length == 1" in shell
    assert "expected exactly one non-empty EMAIL subscriber" in shell
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", shell)
    assert 'export TF_VAR_budget_notification_email="$(' in shell
    assert "unset TF_VAR_budget_notification_email" in shell
    assert (
        'rm -f -- "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"'
        in shell
    )
    assert "terraform apply" not in shell
    assert "-migrate-state" not in shell
    assert "-backend-config" not in shell

    notifications_filter_match = re.search(
        r"jq -ce '(.*?)'\s+\\\s*<<<", shell, flags=re.DOTALL
    )
    assert notifications_filter_match is not None
    notifications_filter = notifications_filter_match.group(1)
    notifications_result = subprocess.run(
        ["jq", "-ce", notifications_filter],
        input=json.dumps(
            {
                "Notifications": [
                    {"NotificationType": "ACTUAL"},
                    {"NotificationType": "FORECASTED"},
                ]
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert notifications_result.returncode == 0, notifications_result.stderr
    assert len(notifications_result.stdout.splitlines()) == 2
    malformed_notifications = subprocess.run(
        ["jq", "-ce", notifications_filter],
        input=json.dumps({"Notifications": []}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert malformed_notifications.returncode != 0

    subscriber_filter_match = re.search(
        r"jq -r '([^']*\.Subscribers\[\]\?[^']*)'", shell
    )
    assert subscriber_filter_match is not None
    subscriber_filter = subscriber_filter_match.group(1)
    valid_recipient = "recipient" + chr(64) + "example.com"
    subscribers_result = subprocess.run(
        ["jq", "-r", subscriber_filter],
        input=json.dumps(
            {
                "Subscribers": [
                    {"SubscriptionType": "EMAIL", "Address": valid_recipient},
                    {"SubscriptionType": "SNS", "Address": "arn:aws:sns:example"},
                    {"SubscriptionType": "EMAIL", "Address": ""},
                    {"SubscriptionType": "EMAIL", "Address": None},
                ]
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert subscribers_result.returncode == 0, subscribers_result.stderr
    assert valid_recipient in subscribers_result.stdout
    assert "arn:aws:sns:example" not in subscribers_result.stdout

    subscriber_validation_match = re.search(
        r"if ! jq -e '\n(.*?)\n\s+' \"\$DEVELOPMENT_BUDGET_SUBSCRIBERS\" >/dev/null",
        shell,
        flags=re.DOTALL,
    )
    assert subscriber_validation_match is not None
    subscriber_validation = subscriber_validation_match.group(1)
    for response in (
        {"Subscribers": [{"SubscriptionType": "EMAIL", "Address": valid_recipient}]},
        {
            "Subscribers": [
                {"SubscriptionType": "SNS", "Address": "arn:aws:sns:example"}
            ]
        },
    ):
        result = subprocess.run(
            ["jq", "-e", subscriber_validation],
            input=json.dumps(response),
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    for response in (
        {},
        {"Subscribers": None},
        {"Subscribers": [{"SubscriptionType": "EMAIL"}]},
        {"Subscribers": [{"SubscriptionType": "EMAIL", "Address": None}]},
    ):
        result = subprocess.run(
            ["jq", "-e", subscriber_validation],
            input=json.dumps(response),
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0

    recipient_filter_match = re.search(
        r"jq -R -s -er '\n(.*?)\n\s+' \"\$DEVELOPMENT_BUDGET_RECIPIENTS\"\n\)",
        shell,
        flags=re.DOTALL,
    )
    assert recipient_filter_match is not None
    recipient_filter = recipient_filter_match.group(1)

    def accepts(lines: str) -> bool:
        return (
            subprocess.run(
                ["jq", "-R", "-s", "-er", recipient_filter, "-"],
                input=lines,
                text=True,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )

    assert accepts(f"{valid_recipient}\n{valid_recipient}\n")
    assert not accepts(f"{valid_recipient}\nother{chr(64)}example.com\n")
    assert not accepts("recipient\n")
    assert not accepts("")


def test_development_foundation_gate_requires_the_complete_expected_set():
    development = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    shell = re.search(r"```sh\n(.*?)\n```", development, flags=re.DOTALL)
    assert shell is not None
    gate = re.search(
        r'show -json "\$DEVELOPMENT_FOUNDATION_PLAN" 2>/dev/null \| jq -e \'\n(.*?)\n\' >/dev/null 2>/dev/null;',
        shell.group(1),
        flags=re.DOTALL,
    )
    assert gate is not None

    def addresses(definition: str) -> list[str]:
        match = re.search(
            rf"def {definition}: \[\n(.*?)\n  \];", gate.group(1), re.DOTALL
        )
        assert match is not None
        return [
            json.loads(line.strip().rstrip(",")) for line in match.group(1).splitlines()
        ]

    create_addresses = addresses("foundation_create_addresses")
    data_addresses = addresses("foundation_data_addresses")
    assert len(create_addresses) == len(set(create_addresses)) == 95
    assert set(data_addresses) == {
        "data.aws_caller_identity.current",
        "data.aws_region.current",
        "data.aws_vpc.default",
        "data.aws_subnets.default",
        "data.aws_route_tables.default",
        "data.aws_subnet.tailscale_router",
    }

    def change(mode: str, address: str, actions: list[str]) -> dict[str, object]:
        return {"address": address, "mode": mode, "change": {"actions": actions}}

    expected_changes = [
        *(change("managed", address, ["create"]) for address in create_addresses),
        *(change("data", address, ["read"]) for address in data_addresses),
    ]

    def passes(changes: object) -> bool:
        result = subprocess.run(
            ["jq", "-e", gate.group(1)],
            input=json.dumps({"resource_changes": changes}),
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    assert passes(expected_changes)
    assert not passes([])
    assert not passes(expected_changes[1:])
    assert not passes([*expected_changes, change("managed", "unexpected", ["create"])])
    assert not passes([*expected_changes, expected_changes[0]])

    for actions in (["no-op"], ["update"], ["delete"], ["create", "delete"]):
        changed = [*expected_changes]
        changed[0] = change("managed", create_addresses[0], actions)
        assert not passes(changed)

    changed = [*expected_changes]
    changed[-1] = change("managed", data_addresses[-1], ["read"])
    assert not passes(changed)
    changed = [*expected_changes]
    changed[-1] = change("data", "unexpected", ["read"])
    assert not passes(changed)


def test_v2_pr_validation_has_no_aws_access_or_mutation_commands():
    workflow = (REPO_ROOT / ".github" / "workflows" / "terraform.yml").read_text()
    for forbidden in (
        "configure-aws-credentials",
        "id-token: write",
        "terraform plan",
        "terraform apply",
        "terraform import",
        "terraform state list",
        "aws sts",
        "ssm get-parameter",
    ):
        assert forbidden not in workflow


def test_backend_and_provider_configuration_has_no_credential_or_workspace_coupling():
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
    plan = (V2_ROOT / "plans" / "ENVIRONMENT-AND-RELEASE-PLAN.md").read_text()
    assert "account-local foundation handoff" in plan
    assert "legacy production-account development cleanup is owned by #333" in plan


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
        "Only the reviewed, explicitly authorized Oracle migration",
        "Generic or future manual migrations are not authorized",
    ):
        assert text in AGENTS
    for text in (
        "PRs use disposable PostGIS migration validation only",
        "sole\nschema-change exception is the separately authorized, reviewed migration 030",
        "Application release\nartifacts do not apply schema changes; this procedure is separate",
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


def test_manual_oracle_migration_030_contract_is_offline_guarded_and_syntax_checked():
    section = DEPLOYMENT.split("## Manual Oracle migration 030", maxsplit=1)[1].split(
        "## Environment-tag inventory", maxsplit=1
    )[0]
    shell_blocks = re.findall(r"```sh\n(.*?)\n```", section, flags=re.DOTALL)
    assert len(shell_blocks) == 1
    shell = shell_blocks[0]

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
        script.write(shell)
        script.flush()
        assert subprocess.run(["bash", "-n", script.name], check=False).returncode == 0

    for required in (
        "explicit operator authorization",
        "nova-toll-prod",
        "920534282028",
        "us-east-1",
        "AWS_PROFILE=nova-toll-prod aws --region us-east-1",
        "set -euo pipefail",
        "set +x",
        'command -v "$command_name"',
        "MIGRATION_SHA256=101ee53eb4e37f00e4bf711d9c97bf97b4c53981f5b0a6bd7a932cfea9ecee40",
        'test ! -L "$MIGRATION"',
        '"$MIGRATION_SHA256" "$MIGRATION"',
        "describe-db-instances",
        "--db-instance-identifier nova-toll-db",
        "--query 'DBInstances'",
        "Endpoint.Address",
        "Endpoint.Port",
        "MasterUserSecret.SecretArn",
        'DBInstanceStatus == "available"',
        "PubliclyAccessible == false",
        '. != "None"',
        'test("^[A-Za-z0-9][A-Za-z0-9.-]*[.]rds[.]amazonaws[.]com$")',
        'get-secret-value --secret-id "$SECRET_ARN"',
        'type == "object"',
        "CA_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem",
        "CA_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3",
        "sha256sum --check --status",
        "PGSSLMODE=verify-full",
        'PGSSLROOTCERT="$CA_FILE"',
        "psql -X --set ON_ERROR_STOP=1",
        "1.3.0|1.13.1|995|13|0",
        "1.3.0|1.14.0|996|14|1|1",
        "required_i95_direction IS NULL",
        "source_route_key IS NULL",
        'source_metadata = \'{"basis":"v2/db/oracle/CONTRACT.md","curated":true}\'::jsonb',
        "trap cleanup EXIT",
        "rm -f --",
        "unset DB_PASSWORD DB_USER SECRET_JSON",
        "v2/db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql",
        "process_environment()",
        'source="$(source_state "$database")"',
        "if [ \"$source\" = '1.3.0|1.13.1|995|13|0' ]; then",
        'apply_migration "$database"',
        'require_target_state "$database"',
        'target="$(target_state "$database")"',
        "if [ \"$target\" = '1.3.0|1.14.0|996|14|1|1' ]; then",
        "already has the exact target state; verifying and skipping",
        "Incompatible migration state for %s; stop without applying.",
        "process_environment nova_toll_development",
        "process_environment nova_toll",
        "Apply outcome is unknown",
        'actual="$(target_state "$database")"',
        "SQL error before `COMMIT`",
        "connection loss during or after `COMMIT` makes the outcome unknown",
        "before retrying an apply or",
        "separately authorized RDS backup/PITR incident handling",
    ):
        assert required in section

    assert not re.search(r"(?m)^\s*set\s+-x(?:\s|$)", shell)
    assert not re.search(r"(?m)^\s*SECRET_ARN=arn:", shell)
    assert not re.search(r"(?m)^DB_HOST=(?:[A-Za-z0-9]|['\"][A-Za-z0-9])", shell)
    assert not re.search(
        r"(?m)^\s*(?:echo|printf).*\$(?:SECRET_JSON|DB_PASSWORD)", shell
    )
    assert not re.search(r"(?m)^\s*.*>[^\n]*\$(?:SECRET_JSON|DB_PASSWORD)", shell)
    assert 'PGPASSWORD="$DB_PASSWORD"' in shell
    assert "sslmode=require" not in shell
    assert "sslmode=disable" not in shell
    assert "sslmode=verify-ca" not in shell
    assert "AWS_ACCESS_KEY_ID" not in shell
    assert "AWS_SECRET_ACCESS_KEY" not in shell
    for forbidden in (
        "Schema-changing work is not deployable",
        "Current releases are schema-neutral",
    ):
        assert forbidden not in (DEPLOYMENT + AGENTS)
    for forbidden in (
        "deploy_oracle_migration.py",
        "migration-finalizer",
        "migrator_role",
        "RELEASE_EVIDENCE",
        "configure-aws-credentials",
    ):
        assert forbidden not in section

    for before, after in (
        ("describe-db-instances", "get-secret-value"),
        ('test ! -L "$MIGRATION"\n', "get-secret-value"),
        ("sha256sum --check --status", "get-secret-value"),
        ("get-secret-value", "psql -X --set ON_ERROR_STOP=1"),
        (
            "process_environment() {\n",
            "process_environment nova_toll_development\n",
        ),
        (
            "process_environment nova_toll_development\n",
            "process_environment nova_toll\n",
        ),
    ):
        assert shell.index(before) < shell.index(after)

    process_body = re.search(r"(?ms)^process_environment\(\) \{.*?^\}", shell)
    assert process_body is not None
    process_body = process_body.group(0)
    source_branch = process_body.split(
        "if [ \"$source\" = '1.3.0|1.13.1|995|13|0' ]; then", maxsplit=1
    )[1].split('target="$(target_state "$database")"', maxsplit=1)[0]
    assert source_branch.index('apply_migration "$database"') < source_branch.index(
        'require_target_state "$database"'
    )
    target_branch = process_body.split(
        'target="$(target_state "$database")"', maxsplit=1
    )[1]
    assert "apply_migration" not in target_branch
    assert "Incompatible migration state" in target_branch
    assert "exit 1" in target_branch
    assert process_body.index('require_target_state "$database"') < process_body.index(
        "return 0"
    )
    target_skip = process_body.index("already has the exact target state")
    assert target_skip < process_body.index("return 0", target_skip)


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
        "dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.agent}"
        in agentcore
    )
    assert (
        "dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.pricing_caller}"
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
    assert "ignore_changes = [reserved_concurrent_executions]" not in proxy
    assert "aws_iam_role_policy.tollchat_proxy" in proxy

    assert "put-function-concurrency" not in DEPLOYMENT


def test_v2_public_edge_reuses_the_runtime_and_keeps_one_proxy_warm():
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    main = (V2_ROOT / "infra" / "main.tf").read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_api_gateway_rest_api"', maxsplit=1)[0]
    assert "publish                        = true" in proxy
    assert "reserved_concurrent_executions = 5" in proxy
    assert "ignore_changes = [reserved_concurrent_executions]" not in proxy
    assert "PUBLIC_ORIGINS = local.public_site_url" in proxy
    assert 'PUBLIC_ORIGINS = "https://${local.domains[0]}"' not in proxy
    loader = main.split('resource "aws_lambda_function" "loader"', maxsplit=1)[1].split(
        'resource "aws_lambda_function" "agent_usage_rollup"', maxsplit=1
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
    assert (
        "aliases             = local.custom_domain_enabled ? local.domains : []" in site
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


def test_development_plan_policy_requires_reservations_and_valid_default_edge():
    release = DEPLOYMENT.split(
        "### Development application release and database validation (#331)", maxsplit=1
    )[1].split("### Development handoff (non-operative)", maxsplit=1)[0]
    policy_match = re.search(
        r"if ! jq -e '(\n\s+def managed_changes\(\$address\):.*?\n\s+)' \"\$PLAN_JSON\"",
        release,
        flags=re.DOTALL,
    )
    assert policy_match is not None
    policy = policy_match.group(1)

    def change(address: str, after: object) -> dict[str, object]:
        return {
            "mode": "managed",
            "address": address,
            "change": {"actions": ["create"], "after": after, "after_unknown": {}},
        }

    edge = {
        "aliases": [],
        "viewer_certificate": [
            {
                "acm_certificate_arn": None,
                "cloudfront_default_certificate": True,
                "minimum_protocol_version": "TLSv1",
                "ssl_support_method": None,
            }
        ],
    }
    plan = {
        "resource_changes": [
            change(
                "aws_lambda_function.loader",
                {"reserved_concurrent_executions": 5},
            ),
            change(
                "aws_lambda_function.publisher",
                {"reserved_concurrent_executions": 1},
            ),
            change(
                "aws_lambda_function.tollchat_proxy",
                {"reserved_concurrent_executions": 5},
            ),
            change("aws_cloudfront_distribution.site", edge),
        ]
    }

    def passes(candidate: object) -> bool:
        return (
            subprocess.run(
                ["jq", "-e", policy],
                input=json.dumps(candidate),
                text=True,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )

    assert passes(plan)
    empty_actions = json.loads(json.dumps(plan))
    for resource in empty_actions["resource_changes"]:
        resource["change"]["actions"] = []
    assert not passes(empty_actions)
    for address, key, value in (
        ("aws_lambda_function.loader", "reserved_concurrent_executions", None),
        ("aws_lambda_function.publisher", "reserved_concurrent_executions", 5),
        ("aws_lambda_function.tollchat_proxy", "reserved_concurrent_executions", -1),
        ("aws_cloudfront_distribution.site", "aliases", ["preview.example"]),
        (
            "aws_cloudfront_distribution.site",
            "minimum_protocol_version",
            "TLSv1.2_2021",
        ),
    ):
        candidate = json.loads(json.dumps(plan))
        after = next(
            resource
            for resource in candidate["resource_changes"]
            if resource["address"] == address
        )["change"]["after"]
        if address.endswith("distribution.site") and key != "aliases":
            after["viewer_certificate"][0][key] = value
        else:
            after[key] = value
        assert not passes(candidate)


def test_development_secret_fetch_keeps_arn_out_of_argv_and_evidence():
    release = DEPLOYMENT.split(
        "### Development application release and database validation (#331)", maxsplit=1
    )[1].split("### Development handoff (non-operative)", maxsplit=1)[0]
    assert "secret_json()" in release
    assert 'SECRET_ARN="$SECRET_ARN"' in release
    assert 'SecretId=os.environ["SECRET_ARN"]' in release
    assert 'get-secret-value --secret-id "$SECRET_ARN"' not in release
    assert "--only-matching" in release
    assert 'test "$reference" = "$ALLOWED_SSM_REFERENCE"' in release
    pattern = re.search(r"SSM_ARN_PATTERN='([^']+)'", release)
    assert pattern is not None
    allowed = "arn:aws:ssm:us-east-1:903859731897:parameter/nova-toll/openai_api_key"
    unexpected = "arn:aws:ssm:us-east-1:903859731897:parameter/unexpected"
    python_pattern = pattern.group(1).replace("[:alnum:]", "A-Za-z0-9")
    matches = re.findall(
        python_pattern, json.dumps({"allowed": allowed, "unexpected": unexpected})
    )
    assert matches == [allowed, unexpected]
    assert (
        'test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)"'
        in release
    )
    assert "source_tree_sha256=$SOURCE_TREE_SHA256" in release
    assert "source_diff_sha256=$SOURCE_DIFF_SHA256" in release
    assert release.index('SOURCE_TREE_SHA256="$(source_tree_digest)"') < release.index(
        'tf_dev -chdir="$ROOT/v2/infra" plan'
    )


def test_development_release_scans_before_apply_and_never_bootstraps_deployed_database():
    release = DEPLOYMENT.split(
        "### Development application release and database validation (#331)", maxsplit=1
    )[1].split("### Development handoff (non-operative)", maxsplit=1)[0]

    phase_one_apply = (
        'tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_ONE_PLAN"'
    )
    phase_two_apply = (
        'tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_TWO_PLAN"'
    )
    assert release.index('scan_package "$package"') < release.index(phase_one_apply)
    assert release.index('scan_release_file "$PHASE_ONE_PLAN"') < release.index(
        phase_one_apply
    )
    assert release.index('scan_release_file "$PHASE_TWO_PLAN"') < release.index(
        phase_two_apply
    )
    assert 'python3 "$ROOT/v2/scripts/bootstrap_development_database.py"' not in release
    assert "database_bootstrap=not-run" in release
    assert "psql --dbname nova_toll_development --file" in release


def test_development_site_has_no_cloudflare_reads_or_writes():
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
        'schema_version == "2.0.0"',
        'publication_format_version == "2.0.0"',
        "route_count == 685",
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


def test_account_local_release_contract_and_foundation_gates_fail_closed():
    for text in (
        "AWS_PROFILE=nova-toll-dev",
        'get-caller-identity --query Account --output text)" = "903859731897"',
        "backend.production.hcl",
        "production.tfvars",
        "production-release.tfplan",
        "The bounded #331 application release and database validation below is the operative",
        "#330",
        "#331",
        "#332",
        "-reconfigure",
        "-lock=false",
    ):
        assert text in DEPLOYMENT
    assert DEPLOYMENT.index(
        "### Development foundation handoff (#330; no application release)"
    ) < DEPLOYMENT.index("### Guarded production release")
    assert "903859731897" in DEPLOYMENT
    assert "terraform workspace" not in DEPLOYMENT
    assert "terraform -target" not in DEPLOYMENT
    development_handoff = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    development_plan_stage = development_handoff.split(
        "#### Later authorized exact-plan apply and recovery", maxsplit=1
    )[0]
    later_apply = development_handoff.split(
        "#### Later authorized exact-plan apply and recovery", maxsplit=1
    )[1]
    assert "apply -input=false" not in development_plan_stage
    assert "init -backend=false" in development_plan_stage
    assert "DEVELOPMENT_FOUNDATION_DIR" in development_plan_stage
    assert "development-release.tfplan" not in development_plan_stage
    for forbidden in (
        "terraform apply",
        "terraform import",
        "terraform state list",
        "-migrate-state",
        "-backend-config",
        "show -no-color",
    ):
        assert forbidden not in development_plan_stage
    assert 'TF_DATA_DIR="$ROOT/.terraform-data"' in later_apply
    assert (
        "EXPECTED_PLAN=0efda359505d7142a45792ec79e12d40d0540b7e3e961a7e04891328ca94e597"
        in later_apply
    )
    assert (
        "EXPECTED_FETCHER=9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"
        in later_apply
    )

    gates = re.findall(
        r'show -json "\$(?:DEVELOPMENT|PRODUCTION)_FOUNDATION_PLAN"(?: 2>/dev/null)? \| jq -e \'\n(.*?)\n\' >/dev/null(?: 2>/dev/null; then)?',
        DEPLOYMENT,
        re.DOTALL,
    )
    assert len(gates) == 2
    assert "foundation_create_addresses" in gates[0]
    assert "foundation_create_addresses" not in gates[1]

    data_addresses = (
        "data.aws_caller_identity.current",
        "data.aws_region.current",
        "data.aws_vpc.default",
        "data.aws_subnets.default",
        "data.aws_route_tables.default",
        "data.aws_iam_policy_document.agentcore_artifacts",
        "data.aws_iam_policy_document.raw_bucket",
        "data.aws_iam_policy_document.tfstate_bucket",
        "data.archive_file.placeholder",
        "data.aws_iam_policy_document.lambda_assume",
        "data.aws_iam_policy_document.fetcher",
        "data.aws_iam_policy_document.replay_assume",
        "data.aws_iam_policy_document.replay",
        "data.aws_iam_policy_document.audit_kms",
        "data.aws_iam_policy_document.alerts_kms",
        "data.aws_iam_policy_document.audit_bucket",
        "data.aws_prefix_list.s3",
        "data.aws_iam_policy_document.ec2_assume",
        "data.aws_iam_policy_document.tailscale_router",
        "data.aws_subnet.tailscale_router",
    )

    def foundation_value() -> dict[str, object]:
        return {
            "vpc_id": "vpc-123",
            "vpc_cidr_block": "10.0.0.0/16",
            "private_subnet_ids": {"a": "subnet-a", "c": "subnet-c"},
            "rds_security_group_id": "sg-rds",
            "agentcore_endpoint_security_group_id": "sg-agentcore",
            "eventbridge_endpoint_security_group_id": "sg-eventbridge",
            "agentcore_vpc_endpoint_id": "vpce-agentcore",
            "agentcore_vpc_endpoint_dns_name": "vpce.example.com",
            "tollchat_api_vpc_endpoint_id": "vpce-api",
            "raw_bucket_name": "raw-bucket",
            "raw_kms_key_arn": "arn:aws:kms:us-east-1:920534282028:key/raw",
            "agentcore_artifacts_bucket_name": "agentcore-bucket",
            "db_instance": {
                "identifier": "nova-toll-db",
                "resource_id": "db-123",
                "address": "db.example.com",
                "port": 5432,
            },
            "alerts_topic_arn": "arn:aws:sns:us-east-1:920534282028:alerts",
        }

    def foundation_plan(
        changes: object, foundation: object | None = None
    ) -> dict[str, object]:
        if foundation is None:
            foundation = foundation_value()
        return {
            "resource_changes": changes,
            "planned_values": {"outputs": {"foundation": {"value": foundation}}},
        }

    def change(mode: str, address: str, actions: list[str]) -> dict[str, object]:
        return {"mode": mode, "address": address, "change": {"actions": actions}}

    def outcomes(plan: object | str) -> list[bool]:
        input_data = plan if isinstance(plan, str) else json.dumps(plan)
        results = [
            subprocess.run(
                ["jq", "-e", gate], input=input_data, text=True, check=False
            ).returncode
            == 0
            for gate in gates
        ]
        return results

    accepted = (
        foundation_plan([]),
        foundation_plan([change("managed", "aws_s3_bucket.tfstate", ["no-op"])]),
        foundation_plan([change("data", "data.aws_vpc.default", ["read"])]),
        foundation_plan(
            [change("data", address, ["read"]) for address in data_addresses]
        ),
        foundation_plan(
            [
                change("managed", "aws_s3_bucket.tfstate", ["no-op"]),
                change("data", "data.aws_vpc.default", ["read"]),
            ]
        ),
    )
    for plan in accepted:
        assert outcomes(plan) == [False, True]
    for address in (
        "aws_s3_bucket.tfstate",
        'aws_s3_bucket_versioning.hardened["tfstate"]',
    ):
        assert outcomes(foundation_plan([change("managed", address, ["create"])])) == [
            False,
            False,
        ]

    malformed: tuple[object, ...] = (
        "not json",
        {},
        foundation_plan({}),
        foundation_plan(None),
        foundation_plan({"resource_changes": []}),
        foundation_plan([None]),
        foundation_plan(["resource"]),
        foundation_plan([1]),
        foundation_plan([{**change("managed", "", ["no-op"])}]),
        foundation_plan(
            [
                {
                    key: value
                    for key, value in change("managed", "x", ["no-op"]).items()
                    if key != "address"
                }
            ]
        ),
        foundation_plan([{**change("managed", "x", ["no-op"]), "mode": None}]),
        foundation_plan(
            [{**change("managed", "x", ["no-op"]), "mode": cast(object, [])}]
        ),
        foundation_plan([{"address": "x", "change": {"actions": ["no-op"]}}]),
        foundation_plan([{**change("managed", "x", ["no-op"]), "change": None}]),
        foundation_plan(
            [{**change("managed", "x", ["no-op"]), "change": cast(object, [])}]
        ),
        foundation_plan([{"mode": "managed", "address": "x"}]),
        foundation_plan(
            [
                {
                    "mode": "managed",
                    "address": "x",
                    "change": cast(object, {}),
                }
            ]
        ),
        foundation_plan(
            [{**change("managed", "x", ["no-op"]), "change": {"actions": None}}]
        ),
        foundation_plan(
            [
                {
                    **change("managed", "x", ["no-op"]),
                    "change": {"actions": cast(object, {})},
                }
            ]
        ),
        foundation_plan(
            [{**change("managed", "x", ["no-op"]), "change": {"actions": "no-op"}}]
        ),
    )
    for plan in malformed:
        assert not any(outcomes(plan))

    extra_output = foundation_value()
    extra_output["unexpected_secret"] = "should reject"
    missing_output_key = foundation_value()
    del missing_output_key["raw_kms_key_arn"]
    nested_extra = foundation_value()
    cast(dict[str, object], nested_extra["db_instance"])["password"] = "should reject"
    nested_missing = foundation_value()
    del cast(dict[str, object], nested_missing["private_subnet_ids"])["c"]
    missing_foundation_output = foundation_plan([], foundation_value())
    del cast(
        dict[str, object],
        cast(dict[str, object], missing_foundation_output["planned_values"])["outputs"],
    )["foundation"]
    disallowed = (
        *(
            foundation_plan([change("managed", "x", [action])])
            for action in ("create", "update", "delete", "read")
        ),
        *(
            foundation_plan([change("data", "x", [action])])
            for action in ("no-op", "create", "update", "delete")
        ),
        foundation_plan([change("data", "x", ["read", "read"])]),
        foundation_plan([change("unknown", "x", ["read"])]),
        foundation_plan([change("managed", "x", ["no-op", "read"])]),
        foundation_plan(
            [change("data", "data.aws_ssm_parameter.production_secret", ["read"])]
        ),
    )
    for plan in disallowed:
        assert not any(outcomes(plan))
    for plan in (
        foundation_plan([], extra_output),
        foundation_plan([], missing_output_key),
        foundation_plan([], nested_extra),
        foundation_plan([], nested_missing),
        missing_foundation_output,
    ):
        assert outcomes(plan) == [False, False]


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
    pre_bootstrap_runbook = DEPLOYMENT.split(
        "### Development bootstrap/import boundary", maxsplit=1
    )[0]
    assert "usage-permissions.tfplan" not in DEPLOYMENT
    assert "usage-prerequisites.tfplan" not in DEPLOYMENT
    assert "Do not use Terraform resource targets" in DEPLOYMENT
    assert "iam get-role-policy" not in pre_bootstrap_runbook
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
    assert '"${local.raw_bucket_arn}/raw/feed=i95/*"' in MAIN_TF
    assert '"${local.raw_bucket_arn}/raw/feed=i66/*"' in MAIN_TF
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
        "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.publisher}",
        "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.reader}",
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
    assert "PUBLIC_BASE_URL      = local.public_site_url" in publisher_lambda
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

    assert re.search(
        r'name\s*=\s*"nova-toll-v2-timed-checks\$\{local\.suffix\}"', MAIN_TF
    )
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


def test_exact_plan_success_path_is_private_ordered_and_fail_closed():
    development = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    success_block = development.split(
        "##### Successful exact-plan apply, migration, and evidence", maxsplit=1
    )[1]
    success = success_block.split("```sh\n", maxsplit=1)[1].split("\n```", maxsplit=1)[
        0
    ]

    for text in (
        "set -euo pipefail",
        "set +x",
        "umask 077",
        "ROOT=/tmp/tmp.1nuZtAcl8L",
        'PLAN="$ROOT/development-foundation.tfplan"',
        'FETCHER="$ROOT/build/fetcher.zip"',
        "EXPECTED_PLAN=0efda359505d7142a45792ec79e12d40d0540b7e3e961a7e04891328ca94e597",
        "EXPECTED_FETCHER=9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1",
        "EXPECTED_MANIFEST=d42489b4f0e971e6eeb06d0ba033b68584ab95ff19763a0e40724db657e8acc8",
        "find . -maxdepth 1 -type f \\( -name '*.tf' -o -name '*.tf.json' \\) -printf '%P\\0'",
        "find .terraform-data/providers -type f -perm /111 -name 'terraform-provider-*'",
        "@terraform-cli",
        "@terraform-version",
        "terraform version -json",
        "LC_ALL=C sort -z -u",
        'FIRST="$(manifest_digest)"; SECOND="$(manifest_digest)"',
        'test "$FIRST" = "$SECOND"; test "$FIRST" = "$EXPECTED_MANIFEST"',
        'terraform -chdir="$ROOT" apply -input=false "$PLAN" >/dev/null 2>/dev/null',
        'terraform -chdir="$ROOT" init -migrate-state -force-copy -input=false -backend-config="$ROOT/backend.development.hcl" >/dev/null 2>/dev/null',
        'chmod 600 -- "$ROOT/terraform.tfstate"',
        'timeout 30s env TF_DATA_DIR="$ROOT/.terraform-data"',
        'state_object_absent "$STATE_KEY"; state_object_absent "$STATE_KEY.tflock"',
        's3api head-object --bucket "$STATE_BUCKET" --key "$key" 2>&1 >/dev/null',
        "404|Not Found|NoSuchKey",
        'cp -- "$ROOT/versions.tf.with-backend" "$ROOT/versions.tf"',
        'probe_denied s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY"',
        'probe_denied kms describe-key --key-id "$STATE_KMS_ARN"',
        "aws iam get-role --role-name \"$role\" --query 'Role.RoleName'",
        "toll-fetcher toll-raw-replay nova-toll-tailscale-router",
        "AccessDenied|403|Forbidden",
        "nova-toll-monthly",
        "SSM_COUNT",
        "describe-parameters",
        "cloudtrail",
        "foundation_alarms=8",
        "development_iam_roles_present=true",
    ):
        assert text in success

    for forbidden in (
        "terraform show",
        "terraform output",
        "terraform plan",
        "terraform import",
        "terraform_remote_state",
        "get-parameter",
        "cloudflare",
        "terraform -target",
        "rm -rf",
        "subscriber_email_addresses",
        "Parameter.Value",
    ):
        assert forbidden not in success

    apply = 'terraform -chdir="$ROOT" apply -input=false "$PLAN"'
    migration = 'terraform -chdir="$ROOT" init -migrate-state -force-copy -input=false'
    assert success.index('test "$(sha256sum "$PLAN"') < success.index(apply)
    assert success.index('test "$(printf \'%s\\n\' "$STATE_LIST"') < success.index(
        'state_object_absent "$STATE_KEY"; state_object_absent "$STATE_KEY.tflock"'
    )
    assert success.index(
        'state_object_absent "$STATE_KEY"; state_object_absent "$STATE_KEY.tflock"'
    ) < success.index('cp -- "$ROOT/versions.tf.with-backend" "$ROOT/versions.tf"')
    assert success.index(
        'cp -- "$ROOT/versions.tf.with-backend" "$ROOT/versions.tf"'
    ) < success.index(migration)
    assert success.index(migration) < success.index('STATE_HEAD="$(AWS_PROFILE')
    assert success.index(
        'test "$(AWS_PROFILE=nova-toll-prod aws --region "$REGION" sts'
    ) < success.index("probe_denied s3api head-object")


def test_issue330_repairs_preserve_roles_and_migration_gate():
    handoff = DEPLOYMENT.split("## Account-local foundation handoff", maxsplit=1)[1]
    development = DEPLOYMENT.split(
        "### Development foundation handoff (#330; no application release)",
        maxsplit=1,
    )[1].split("### Guarded production release", maxsplit=1)[0]
    normalized_handoff = " ".join(handoff.split())
    normalized_development = " ".join(development.split())

    assert "production-only" in normalized_handoff
    assert (
        "Do not use that generic planned-output or tfvars flow for development"
        in normalized_handoff
    )
    assert "state is not discovered through a foundation output" in normalized_handoff
    assert "approved protected exception" in normalized_development
    assert (
        "private reviewed plan and encrypted, access-controlled Terraform state"
        in normalized_development
    )

    assert "development_iam_roles_present=true" in normalized_development

    assert (
        "for role in toll-fetcher toll-raw-replay nova-toll-tailscale-router"
        in development
    )
    assert "iam get-role --role-name \"$role\" --query 'Role.RoleName'" in development
    assert (
        'state_object_absent "$STATE_KEY"; state_object_absent "$STATE_KEY.tflock"'
        in development
    )
    assert "2>&1 >/dev/null" in development
    assert development.index("state_object_absent") < development.index(
        'cp -- "$ROOT/versions.tf.with-backend" "$ROOT/versions.tf"'
    )


def _workflow_trigger(workflow: dict[str, object]) -> object:
    # PyYAML 1.1 treats the YAML 1.2 `on` key as boolean True.
    return workflow.get("on", cast(Mapping[object, object], workflow).get(True))


def _workflow_run_source(job: dict[str, object]) -> str:
    return "\n".join(
        cast(str, step.get("run", ""))
        for step in cast(list[dict[str, object]], job["steps"])
    )


def _development_plan_gate_script(source: str) -> str:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    deploy_source = _workflow_run_source(jobs["deploy"])
    match = re.search(
        r"python3 - \"\$PLAN_JSON\" <<'PY'\n(.*?)\nPY",
        deploy_source,
        flags=re.DOTALL,
    )
    assert match, "the workflow must embed the plan gate"
    return dedent(match.group(1))


def _run_development_plan_gate(payload: object, *, raw: bool = False) -> bool:
    script = _development_plan_gate_script(DEVELOPMENT_DELIVERY_WORKFLOW)
    with tempfile.TemporaryDirectory() as directory:
        plan = Path(directory) / "plan.json"
        if raw:
            plan.write_text(cast(str, payload), encoding="utf-8")
        else:
            plan.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-", str(plan)],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
    return result.returncode == 0


def _synthetic_change(
    mode: str, address: str, actions: list[str], **after: object
) -> dict[str, object]:
    change: dict[str, object] = {"actions": actions}
    if after:
        change["after"] = after
    return {"address": address, "mode": mode, "change": change}


def _assert_development_delivery_workflow(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    assert _workflow_trigger(workflow) == {"push": {"branches": ["main"]}}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {"build", "deploy"}

    build = jobs["build"]
    assert build["permissions"] == {"contents": "read"}
    assert "id-token" not in cast(dict[str, str], build["permissions"])
    build_steps = cast(list[dict[str, object]], build["steps"])
    build_source = _workflow_run_source(build)
    assert all(
        not cast(str, step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
        for step in build_steps
    )
    for script in (
        "./scripts/build_loader_zip.sh",
        "./scripts/build_publisher_zip.sh",
        "./scripts/build_agentcore_zips.sh",
    ):
        assert script in build_source
    for package in (
        "infra/build/loader.zip",
        "infra/build/publisher.zip",
        "infra/build/agentcore.zip",
        "infra/build/chat-proxy.zip",
    ):
        assert package in build_source
    assert "DEPLOYMENT_SHA256SUMS" in build_source
    uploads = [
        step
        for step in build_steps
        if cast(str, step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert {cast(dict[str, str], step["with"])["name"] for step in uploads} == {
        "v2-development-packages",
        "v2-development-checksums",
    }

    deploy = jobs["deploy"]
    assert deploy["needs"] == "build"
    assert deploy["if"] == "vars.DEVELOPMENT_DELIVERY_ENABLED == 'true'"
    assert (
        "Repository variable: environment variables are unavailable to this pre-job gate."
        in source
    )
    assert deploy["environment"] == "development"
    assert deploy["permissions"] == {"contents": "read", "id-token": "write"}
    deploy_steps = cast(list[dict[str, object]], deploy["steps"])
    deploy_source = _workflow_run_source(deploy)
    downloads = [
        step
        for step in deploy_steps
        if cast(str, step.get("uses", "")).startswith("actions/download-artifact@")
    ]
    assert {cast(dict[str, str], step["with"])["name"] for step in downloads} == {
        "v2-development-packages",
        "v2-development-checksums",
    }
    assert "sha256sum --check DEPLOYMENT_SHA256SUMS" in deploy_source
    assert "aws-actions/configure-aws-credentials@" in "\n".join(
        cast(str, step.get("uses", "")) for step in deploy_steps
    )
    assert "./scripts/build_" not in deploy_source
    assert "arn:aws:iam::903859731897:role/nova-toll-v2-development-delivery" in source
    assert "role-to-assume: arn:aws:iam::903859731897:role/" in source
    assert "aws-region: us-east-1" in source
    assert 'version: "0.12.5"' in source
    assert 'terraform_version: "1.15.8"' in source

    for job in jobs.values():
        for step in cast(list[dict[str, object]], job["steps"]):
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", cast(str, step["uses"]))
            if cast(str, step.get("uses", "")).startswith("actions/checkout@"):
                assert (
                    cast(dict[str, object], step["with"])["persist-credentials"]
                    is False
                )

    configure_index = next(
        index
        for index, step in enumerate(deploy_steps)
        if cast(str, step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    )
    identity_step = deploy_steps[configure_index + 1]
    assert identity_step["name"] == "Confirm development account"
    assert "aws sts get-caller-identity --query Account --output text" in cast(
        str, identity_step["run"]
    )
    assert '= "903859731897"' in cast(str, identity_step["run"])
    assert "Record protected-main OIDC proof" in source
    assert 'test "$GITHUB_REF" = "refs/heads/main"' in deploy_source
    assert (
        'test "$GITHUB_REPOSITORY" = "rhprasad0/nova-toll-budget-agent"'
        in deploy_source
    )
    assert (
        "rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
        not in deploy_source
    )
    assert "protected-main-oidc.json" in deploy_source
    assert '"commit_sha":"%s"' in deploy_source
    assert '(.commit_sha | test("^[0-9a-f]{40}$"))' in deploy_source
    assert (
        "terraform -chdir=infra init -input=false -backend-config=backend.development.hcl"
        in deploy_source
    )
    assert "terraform -chdir=infra output -json foundation" in deploy_source
    assert (
        "foundation.tfvars.json" in deploy_source
        and "trap cleanup EXIT" in deploy_source
    )
    assert (
        "terraform -chdir=v2/infra init -input=false -backend-config=backend.development.hcl"
        in deploy_source
    )
    assert "-var-file=development.tfvars" in deploy_source
    assert 'terraform -chdir=v2/infra plan -input=false -out="$PLAN"' in deploy_source
    assert 'terraform -chdir=v2/infra show -json "$PLAN" >"$PLAN_JSON"' in deploy_source
    assert "python3 - \"$PLAN_JSON\" <<'PY'" in deploy_source
    assert 'terraform -chdir=v2/infra apply -input=false "$PLAN"' in deploy_source
    assert deploy_source.index(
        'terraform -chdir=v2/infra show -json "$PLAN"'
    ) < deploy_source.index('terraform -chdir=v2/infra apply -input=false "$PLAN"')
    assert "known_managed" in deploy_source and "known_data" in deploy_source
    assert "immutable" in deploy_source and "read_only" in deploy_source
    assert "moved/deposed change" in deploy_source
    for manual_address in (
        "aws_api_gateway_rest_api.tollchat",
        "aws_api_gateway_method.tollchat_root",
        "aws_athena_named_query.top_routes",
        "aws_security_group.tollchat_runtime",
        "aws_vpc_security_group_ingress_rule.rds_from_runtime",
        "aws_sqs_queue.delivery_failure",
        "aws_sqs_queue.invoke_failure",
        "aws_sqs_queue.publisher_delivery_failure",
        "aws_sqs_queue.publisher_invoke_failure",
        "aws_sqs_queue_policy.delivery_failure",
    ):
        assert manual_address in deploy_source
    for package in (
        "build/loader.zip",
        "build/publisher.zip",
        "build/agentcore.zip",
        "build/chat-proxy.zip",
    ):
        assert package in deploy_source
    for forbidden in (
        "-target",
        "-lock=false",
        "backend.production.hcl",
        "terraform_remote_state",
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "pull_request",
        "cloudflare",
        "placeholder",
        "920534282028",
    ):
        assert forbidden not in source


def _assert_development_delivery_trust(source: str) -> None:
    trust = _parsed_policy_document(source, "development_delivery_assume")
    assert len(trust) == 1
    statement = trust[0]
    assert statement["actions"] == ["sts:AssumeRoleWithWebIdentity"]
    principal_blocks = _hcl_named_blocks(
        terraform_block(
            source, 'data "aws_iam_policy_document" "development_delivery_assume"'
        ),
        "principals",
    )
    assert len(principal_blocks) == 1
    assert _hcl_scalar(principal_blocks[0], "type") == "Federated"
    assert _hcl_attribute(principal_blocks[0], "identifiers") == (
        "aws_iam_openid_connect_provider.github.arn"
    )
    assert statement["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "token.actions.githubusercontent.com:aud",
            "values": ["sts.amazonaws.com"],
        },
        {
            "test": "StringEquals",
            "variable": "token.actions.githubusercontent.com:sub",
            "values": [
                "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
            ],
        },
    ]


def _assert_development_delivery_state_and_application_policy(source: str) -> None:
    delivery_role = terraform_block(
        source, 'resource "aws_iam_role" "development_delivery"'
    )
    assert re.search(r"(?m)^\s*max_session_duration\s*=\s*3600\s*$", delivery_role)
    statements = _parsed_policy_document(source, "development_delivery")
    by_sid = _policy_by_sid(statements)
    assert {
        "ListDevelopmentState",
        "ReadDevelopmentFoundationState",
        "ManageDevelopmentApplicationState",
        "ManageDevelopmentApplicationLock",
        "DecryptDevelopmentState",
        "WriteDevelopmentStateDataKeys",
    } <= by_sid.keys()
    assert by_sid["ListDevelopmentState"]["actions"] == ["s3:ListBucket"]
    assert by_sid["ListDevelopmentState"]["resources"] == ["aws_s3_bucket.tfstate.arn"]
    assert by_sid["ListDevelopmentState"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "s3:prefix",
            "values": [
                "nova-toll/development/terraform.tfstate",
                "nova-toll/v2/development/terraform.tfstate",
            ],
        }
    ]
    assert by_sid["ReadDevelopmentFoundationState"]["actions"] == ["s3:GetObject"]
    assert by_sid["ReadDevelopmentFoundationState"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate"
    ]
    assert by_sid["ManageDevelopmentApplicationState"]["actions"] == [
        "s3:GetObject",
        "s3:PutObject",
    ]
    assert by_sid["ManageDevelopmentApplicationState"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate"
    ]
    assert by_sid["ManageDevelopmentApplicationLock"]["actions"] == [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
    ]
    assert by_sid["ManageDevelopmentApplicationLock"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock"
    ]
    assert by_sid["DecryptDevelopmentState"]["actions"] == ["kms:Decrypt"]
    assert by_sid["WriteDevelopmentStateDataKeys"]["actions"] == ["kms:GenerateDataKey"]
    for sid in ("DecryptDevelopmentState", "WriteDevelopmentStateDataKeys"):
        assert by_sid[sid]["resources"] == ["aws_kms_key.tfstate.arn"]
        conditions = cast(list[dict[str, object]], by_sid[sid]["conditions"])
        assert conditions[0]["variable"] == "kms:EncryptionContext:aws:s3:arn"
    write_state_conditions = cast(
        list[dict[str, object]], by_sid["WriteDevelopmentStateDataKeys"]["conditions"]
    )
    assert write_state_conditions[0]["values"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock",
    ]

    all_actions = [
        action
        for statement in statements
        for action in cast(list[str], statement["actions"])
    ]
    assert all("*" not in action for action in all_actions)
    assert not any(
        action.startswith(("sts:", "organizations:")) for action in all_actions
    )
    assert not any(
        action.startswith("iam:") and action.endswith(":*") for action in all_actions
    )
    assert not {
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:UpdateAssumeRolePolicy",
    } & set(all_actions)
    assert by_sid["ReadPreprovisionedApplicationRoles"]["actions"] == [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
    ]
    assert by_sid["ReadPreprovisionedApplicationRoles"]["resources"] == [
        "local.development_delivery_role_arns"
    ]
    assert by_sid["ManageApplicationQueues"]["actions"] == [
        "sqs:GetQueueAttributes",
        "sqs:ListQueueTags",
    ]
    assert not {
        "sqs:SetQueueAttributes",
        "sqs:AddPermission",
        "sqs:RemovePermission",
        "sqs:TagQueue",
        "sqs:UntagQueue",
    } & set(all_actions)
    assert "ManageApplicationIamRoles" not in by_sid
    assert "CreateBoundedApplicationRoles" not in by_sid
    assert "bedrock:ListTagsForResource" in cast(
        list[str], by_sid["ManageApplicationGuardrail"]["actions"]
    )
    assert "AttachOnlyLambdaVpcPolicy" not in by_sid
    assert not {"iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PassRole"} & set(
        all_actions
    )
    assert by_sid["UpdateApplicationLambdaFunctions"]["actions"] == [
        "lambda:TagResource",
        "lambda:UntagResource",
        "lambda:UpdateAlias",
        "lambda:UpdateFunctionCode",
    ]
    assert by_sid["UpdateApplicationLambdaFunctions"]["resources"] == [
        "local.development_delivery_lambda_resources"
    ]
    assert not {
        "lambda:UpdateFunctionConfiguration",
        "lambda:PutFunctionConcurrency",
        "lambda:PutFunctionEventInvokeConfig",
        "lambda:PutProvisionedConcurrencyConfig",
        "lambda:UpdateFunctionEventInvokeConfig",
    } & set(all_actions)
    for statement in statements:
        for resource in cast(list[str], statement["resources"]):
            assert "920534282028" not in resource
            assert "production" not in resource.lower()
    assert re.search(
        r'(?m)^\s*development_delivery_account_id\s*=\s*"903859731897"\s*$', source
    )
    assert re.search(
        r'(?m)^\s*development_delivery_region\s*=\s*"us-east-1"\s*$', source
    )
    parsed_policy = json.dumps(statements).lower()
    assert "920534282028" not in parsed_policy
    assert "production" not in parsed_policy
    assert "ssm:" not in parsed_policy
    assert "secretsmanager" not in parsed_policy

    wildcard_statements = {
        cast(str, statement["sid"])
        for statement in statements
        if cast(list[str], statement["resources"]) == ["*"]
    }
    assert wildcard_statements <= {
        "DescribeApplicationLogPolicies",
        "DescribeApplicationLogGroups",
        "DescribeApplicationNetworking",
        "ListApplicationAthenaWorkGroups",
        "ReadManagedCloudFrontPolicies",
    }
    for sid in wildcard_statements:
        conditions = cast(list[dict[str, object]], by_sid[sid]["conditions"])
        assert any(
            condition["variable"] == "aws:RequestedRegion" for condition in conditions
        )

    assert "events:ListTagsForResource" in cast(
        list[str], by_sid["ManageApplicationEventRules"]["actions"]
    )
    assert by_sid["ManageApplicationMeasurementBucket"]["actions"] == [
        "s3:GetBucketAcl",
        "s3:GetBucketLocation",
        "s3:GetBucketOwnershipControls",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketTagging",
        "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:ListBucketVersions",
    ]
    assert by_sid["ManageApplicationAthenaNamedQueries"]["actions"] == [
        "athena:GetNamedQuery",
        "athena:ListTagsForResource",
    ]
    assert by_sid["ManageApplicationAthenaNamedQueries"]["resources"] == [
        "local.development_delivery_athena_named_query_arns"
    ]
    assert by_sid["ManageApplicationAthenaWorkGroup"]["actions"] == [
        "athena:GetWorkGroup",
        "athena:ListNamedQueries",
        "athena:TagResource",
        "athena:UntagResource",
        "athena:UpdateWorkGroup",
    ]
    assert by_sid["ManageApplicationAthenaWorkGroup"]["resources"] == [
        "arn:aws:athena:${local.development_delivery_region}:${local.development_delivery_account_id}:workgroup/tollchat-agent-reports-dev"
    ]

    assert by_sid["UseApplicationKmsKeys"]["actions"] == [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:Encrypt",
        "kms:GenerateDataKey",
        "kms:GetKeyPolicy",
        "kms:GetKeyRotationStatus",
        "kms:ListResourceTags",
    ]
    kms_conditions = cast(
        list[dict[str, object]], by_sid["UseApplicationKmsKeys"]["conditions"]
    )
    assert {
        (condition["variable"], tuple(cast(list[str], condition["values"])))
        for condition in kms_conditions
    } == {
        ("aws:ResourceTag/environment", ("development",)),
        ("aws:ResourceTag/version", ("v2",)),
    }
    assert "ManageApplicationKmsAliases" not in by_sid
    assert "CreateApplicationKmsKeys" not in by_sid
    assert "ManageNewApplicationKmsKeys" not in by_sid
    assert by_sid["ReadApplicationKmsAliases"]["actions"] == [
        "kms:DescribeKey",
        "kms:ListResourceTags",
    ]
    assert by_sid["ReadApplicationKmsAliases"]["resources"] == [
        "local.development_delivery_site_kms_alias_arn",
        "local.development_delivery_measurement_kms_alias_arn",
    ]
    assert by_sid["PublishApplicationApiGatewayDeployments"]["resources"] == [
        "local.development_delivery_api_deployment_arns"
    ]
    assert "UpdateApplicationApiGateway" not in by_sid
    assert by_sid["ReadApplicationApiGateway"]["resources"] == [
        "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}",
        "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}/*",
    ]
    assert by_sid["PublishApplicationLambdaVersions"]["actions"] == [
        "lambda:PublishVersion"
    ]
    assert by_sid["RetireApplicationLambdaVersions"]["actions"] == [
        "lambda:DeleteFunction"
    ]
    assert by_sid["PublishApplicationLambdaVersions"]["resources"] == [
        "local.development_delivery_lambda_arns"
    ]
    assert by_sid["RetireApplicationLambdaVersions"]["resources"] == [
        'for function_arn in local.development_delivery_lambda_arns : "${function_arn}:*"'
    ]
    assert by_sid["PublishApplicationGuardrailVersions"]["actions"] == [
        "bedrock:CreateGuardrailVersion",
    ]
    assert by_sid["PublishApplicationGuardrailVersions"]["resources"] == [
        "local.development_delivery_guardrail_arn"
    ]
    assert by_sid["ReadApplicationCloudFront"]["actions"] == [
        "cloudfront:GetDistribution",
        "cloudfront:GetDistributionConfig",
        "cloudfront:GetOriginAccessControl",
        "cloudfront:GetResponseHeadersPolicy",
        "cloudfront:ListTagsForResource",
    ]
    assert by_sid["ReadApplicationCloudFront"]["resources"] == [
        "local.development_delivery_distribution_arn",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-access-control/*",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:response-headers-policy/*",
    ]
    assert by_sid["ManageApplicationAgentCore"]["actions"] == [
        "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:GetResourcePolicy",
        "bedrock-agentcore:ListTagsForResource",
        "bedrock-agentcore:TagResource",
        "bedrock-agentcore:UntagResource",
        "bedrock-agentcore:UpdateAgentRuntime",
        "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
    ]
    assert by_sid["ManageApplicationAgentCore"]["resources"] == [
        "local.development_delivery_agentcore_runtime_arn",
        "local.development_delivery_agentcore_endpoint_arn",
    ]
    assert by_sid["ManageApplicationCloudFront"]["resources"] == [
        "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-chat-routes-dev",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-report-routes-dev",
    ]
    assert by_sid["ManageApplicationWaf"]["actions"] == [
        "wafv2:GetLoggingConfiguration",
        "wafv2:GetWebACL",
        "wafv2:ListTagsForResource",
    ]
    assert "ManageApplicationNetworking" not in by_sid
    assert "CreateNamedQuery" not in all_actions
    assert "DeleteNamedQuery" not in all_actions
    assert "UpdateNamedQuery" not in all_actions
    assert re.search(r'development_delivery_api_id\s*=\s*"ocw8sg0wlb"', source)
    assert re.search(r"guardrail/vdyqrh31xgca", source)
    assert re.search(r"runtime/nova_toll_v2_development-Y69XBf88Bl", source)
    assert "local.development_delivery_application_key_arns" in source
    assert re.search(
        r"development_delivery_athena_named_query_arns\s*=\s*\[\s*"
        r'"arn:aws:athena:.*:namedquery/097b778f-c9ed-4bd9-af53-1e05770e1d53",\s*'
        r'"arn:aws:athena:.*:namedquery/6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d",',
        source,
        re.DOTALL,
    )
    assert "security-group/*" not in source
    assert "security-group-rule/*" not in source
    assert "vpc/*" not in source
    forbidden_mutations = {
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:UpdateAssumeRolePolicy",
        "bedrock-agentcore:CreateAgentRuntime",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint",
        "bedrock-agentcore:DeleteAgentRuntime",
        "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
        "bedrock-agentcore:PutResourcePolicy",
        "bedrock-agentcore:DeleteResourcePolicy",
        "lambda:AddPermission",
        "lambda:RemovePermission",
        "lambda:CreateFunctionUrlConfig",
        "lambda:UpdateFunctionUrlConfig",
        "lambda:DeleteFunctionUrlConfig",
        "s3:PutBucketPolicy",
        "s3:PutBucketPublicAccessBlock",
        "wafv2:UpdateWebACL",
        "kms:CreateAlias",
        "kms:UpdateAlias",
        "kms:DeleteAlias",
        "kms:CreateKey",
        "kms:PutKeyPolicy",
        "events:PutRule",
        "logs:PutMetricFilter",
        "cloudwatch:PutMetricAlarm",
        "wafv2:PutLoggingConfiguration",
    }
    assert not forbidden_mutations & set(all_actions)


def _assert_application_roles_are_bootstrap_owned() -> None:
    role_sources = {
        "main.tf": MAIN_TF,
        "agentcore.tf": (V2_ROOT / "infra" / "agentcore.tf").read_text(),
        "site.tf": (V2_ROOT / "infra" / "site.tf").read_text(),
        "agent_measurement.tf": (
            V2_ROOT / "infra" / "agent_measurement.tf"
        ).read_text(),
    }
    role_names = {
        "main.tf": ("loader", "timed_checks", "publisher", "publisher_scheduler"),
        "agentcore.tf": ("tollchat_runtime", "tollchat_proxy"),
        "site.tf": ("usage_publisher",),
        "agent_measurement.tf": ("agent_usage_rollup",),
    }
    for filename, names in role_names.items():
        for name in names:
            role = terraform_block(
                role_sources[filename], f'resource "aws_iam_role" "{name}"'
            )
            assert _hcl_scalar(role, "permissions_boundary") in (None, "")


def test_development_agentcore_execution_trust_is_exact_and_confused_deputy_bound():
    source = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    policy = terraform_block(
        source, 'data "aws_iam_policy_document" "agentcore_assume"'
    )
    conditions = _hcl_named_blocks(policy, "condition")
    assert any(
        _hcl_scalar(condition, "test") == "StringEquals"
        and _hcl_scalar(condition, "variable") == "aws:SourceAccount"
        and _hcl_attribute(condition, "values")
        == "data.aws_caller_identity.current.account_id"
        for condition in conditions
    )
    assert any(
        _hcl_scalar(condition, "test") == "ArnEquals"
        and _hcl_scalar(condition, "variable") == "aws:SourceArn"
        and _hcl_attribute(condition, "values") == "local.agentcore_runtime_source_arns"
        for condition in conditions
    )
    assert re.search(
        r'agentcore_runtime_source_arns\s*=\s*local\.is_production\s*\?\s*\[.*runtime/\*"\]\s*:\s*\[local\.development_agentcore_runtime_arn\]',
        source,
        re.DOTALL,
    )
    assert (
        'development_agentcore_runtime_arn = "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl"'
        in source
    )


def _must_reject(
    assertion: Callable[[str], None], source: str, original: str, replacement: str
) -> None:
    mutated = source.replace(original, replacement, 1)
    assert mutated != source
    with pytest.raises(AssertionError):
        assertion(mutated)


def _must_reject_after_marker(
    assertion: Callable[[str], None],
    source: str,
    marker: str,
    original: str,
    replacement: str,
) -> None:
    marker_index = source.index(marker)
    mutated = source[:marker_index] + source[marker_index:].replace(
        original, replacement, 1
    )
    assert mutated != source
    with pytest.raises(AssertionError):
        assertion(mutated)


def test_development_delivery_workflow_is_parsed_and_split_before_oidc():
    _assert_development_delivery_workflow(DEVELOPMENT_DELIVERY_WORKFLOW)
    for original, replacement in (
        ("push:\n    branches:", "pull_request:\n    branches:"),
        ("- main", "- release"),
        ("environment: development", "environment: production"),
        ("903859731897", "920534282028"),
        (
            'test "$GITHUB_REF" = "refs/heads/main"',
            'test "$GITHUB_REF" = "refs/heads/release"',
        ),
        (
            'test "$GITHUB_REPOSITORY" = "rhprasad0/nova-toll-budget-agent"',
            'test "$GITHUB_REPOSITORY" = "evil/fork"',
        ),
        (
            'test "$GITHUB_REPOSITORY" = "rhprasad0/nova-toll-budget-agent"',
            'test "$GITHUB_REPOSITORY" = "rhprasad0@91573985/nova-toll-budget-agent"',
        ),
        ("backend.development.hcl", "backend.production.hcl"),
        ("build/loader.zip", "build/placeholder.zip"),
        ('version: "0.12.5"', "version: latest"),
        ('terraform_version: "1.15.8"', "terraform_version: latest"),
    ):
        _must_reject(
            _assert_development_delivery_workflow,
            DEVELOPMENT_DELIVERY_WORKFLOW,
            original,
            replacement,
        )


def test_development_delivery_iam_is_parsed_and_adversarial_mutations_fail():
    _assert_development_delivery_trust(FOUNDATION_IAM)
    _assert_development_delivery_state_and_application_policy(FOUNDATION_IAM)
    _assert_application_roles_are_bootstrap_owned()

    for original, replacement in (
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production",
        ),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
        ),
        (
            "token.actions.githubusercontent.com:aud",
            "token.actions.githubusercontent.com:evil",
        ),
        (
            "aws_iam_openid_connect_provider.github.arn",
            '"arn:aws:iam::903859731897:oidc-provider/evil.example"',
        ),
        ("903859731897", "920534282028"),
        (
            "nova-toll/v2/development/terraform.tfstate",
            "nova-toll/v2/production/terraform.tfstate",
        ),
        ("bedrock:ListTagsForResource", "bedrock:ListResources"),
        ("events:ListTagsForResource", "events:ListRules"),
        ("iam:GetRole", "iam:DeleteRole"),
        ("iam:GetRolePolicy", "iam:PutRolePolicy"),
        ("lambda:GetFunctionConfiguration", "lambda:UpdateFunctionConfiguration"),
        (
            'variable = "aws:ResourceTag/version"\n      values   = ["v2"]',
            'variable = "aws:ResourceTag/version"\n      values   = ["production"]',
        ),
        ("sts:AssumeRoleWithWebIdentity", "sts:AssumeRole"),
    ):
        assertion = (
            _assert_development_delivery_trust
            if (
                "repo:" in original
                or original.startswith("sts:")
                or "token.actions" in original
                or "openid_connect_provider" in original
            )
            else _assert_development_delivery_state_and_application_policy
        )
        _must_reject(assertion, FOUNDATION_IAM, original, replacement)
    _must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "ManageApplicationMeasurementBucket"',
        "s3:GetBucketPolicy",
        "s3:PutBucketPolicy",
    )
    _must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "UseApplicationKmsKeys"',
        'variable = "aws:ResourceTag/environment"',
        'variable = "kms:ResourceAliases"',
    )
    _must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid     = "ManageApplicationAgentCore"',
        "local.development_delivery_agentcore_runtime_arn",
        '"arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/*"',
    )
    _must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "PublishApplicationGuardrailVersions"',
        "local.development_delivery_guardrail_arn",
        '"arn:aws:bedrock:us-east-1:903859731897:guardrail/*"',
    )
    _must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "PublishApplicationApiGatewayDeployments"',
        "local.development_delivery_api_deployment_arns",
        '["arn:aws:apigateway:${local.development_delivery_region}::/restapis/*/deployments"]',
    )
    for marker, original, replacement in (
        (
            'sid       = "ManageApplicationEventRules"',
            "events:DescribeRule",
            "events:PutRule",
        ),
        (
            'sid       = "ManageApplicationLogs"',
            "logs:DescribeMetricFilters",
            "logs:PutMetricFilter",
        ),
        (
            'sid       = "ManageApplicationAlarms"',
            "cloudwatch:DescribeAlarms",
            "cloudwatch:PutMetricAlarm",
        ),
        (
            'sid       = "ManageApplicationWaf"',
            "wafv2:GetLoggingConfiguration",
            "wafv2:PutLoggingConfiguration",
        ),
        (
            'sid = "ManageApplicationAthenaNamedQueries"',
            "local.development_delivery_athena_named_query_arns",
            '"arn:aws:athena:us-east-1:903859731897:namedquery/*"',
        ),
    ):
        _must_reject_after_marker(
            _assert_development_delivery_state_and_application_policy,
            FOUNDATION_IAM,
            marker,
            original,
            replacement,
        )


def _statement_allows(statement: dict[str, object], action: str, resource: str) -> bool:
    return action in cast(list[str], statement["actions"]) and resource in cast(
        list[str], statement["resources"]
    )


def test_development_delivery_direct_api_denials_are_resource_scoped():
    by_sid = _policy_by_sid(
        _parsed_policy_document(FOUNDATION_IAM, "development_delivery")
    )
    assert _statement_allows(
        by_sid["ManageApplicationAgentCore"],
        "bedrock-agentcore:UpdateAgentRuntime",
        "local.development_delivery_agentcore_runtime_arn",
    )
    assert not _statement_allows(
        by_sid["ManageApplicationAgentCore"],
        "bedrock-agentcore:UpdateAgentRuntime",
        "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/unrelated",
    )
    assert _statement_allows(
        by_sid["PublishApplicationGuardrailVersions"],
        "bedrock:CreateGuardrailVersion",
        "local.development_delivery_guardrail_arn",
    )
    assert not _statement_allows(
        by_sid["PublishApplicationGuardrailVersions"],
        "bedrock:CreateGuardrailVersion",
        "arn:aws:bedrock:us-east-1:903859731897:guardrail/unrelated",
    )
    all_actions = {
        action
        for statement in by_sid.values()
        for action in cast(list[str], statement["actions"])
    }
    assert "iam:PassRole" not in all_actions
    assert "lambda:UpdateFunctionConfiguration" not in all_actions
    assert (
        not {
            "athena:CreateNamedQuery",
            "athena:DeleteNamedQuery",
            "athena:UpdateNamedQuery",
        }
        & all_actions
    )
    assert (
        not {
            "sqs:SetQueueAttributes",
            "sqs:AddPermission",
            "sqs:RemovePermission",
            "sqs:TagQueue",
            "sqs:UntagQueue",
        }
        & all_actions
    )
    assert (
        not {
            "ec2:AuthorizeSecurityGroupIngress",
            "ec2:AuthorizeSecurityGroupEgress",
            "ec2:RevokeSecurityGroupIngress",
            "ec2:RevokeSecurityGroupEgress",
        }
        & all_actions
    )
    assert (
        not {
            "events:PutRule",
            "logs:PutMetricFilter",
            "cloudwatch:PutMetricAlarm",
            "wafv2:PutLoggingConfiguration",
        }
        & all_actions
    )
    assert _statement_allows(
        by_sid["UpdateApplicationLambdaFunctions"],
        "lambda:UpdateFunctionCode",
        "local.development_delivery_lambda_resources",
    )
    assert not _statement_allows(
        by_sid["UpdateApplicationLambdaFunctions"],
        "lambda:UpdateFunctionCode",
        "arn:aws:lambda:us-east-1:903859731897:function:unrelated-dev",
    )
    assert _statement_allows(
        by_sid["ManageApplicationCloudFront"],
        "cloudfront:UpdateFunction",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-chat-routes-dev",
    )
    assert not _statement_allows(
        by_sid["ManageApplicationCloudFront"],
        "cloudfront:UpdateFunction",
        "arn:aws:cloudfront::903859731897:function/unrelated-dev",
    )
    assert _statement_allows(
        by_sid["ManageApplicationSiteBuckets"],
        "s3:PutObject",
        "${local.development_delivery_site_bucket_arn}/*",
    )
    assert not _statement_allows(
        by_sid["ManageApplicationSiteBuckets"],
        "s3:PutObject",
        "arn:aws:s3:::unrelated-development-site/*",
    )
    assert not any(
        resource.endswith("/key/*")
        for statement in by_sid.values()
        for resource in cast(list[str], statement["resources"])
    )


def test_development_delivery_policy_set_is_deterministic_and_bounded():
    statements = _parsed_policy_document(FOUNDATION_IAM, "development_delivery")
    assert len(statements) == 42
    expected_groups = {
        "state": (
            0,
            7,
            [
                "ListDevelopmentState",
                "ReadDevelopmentFoundationState",
                "ManageDevelopmentApplicationState",
                "ManageDevelopmentApplicationLock",
                "DecryptDevelopmentState",
                "WriteDevelopmentStateDataKeys",
                "ReadPreprovisionedApplicationRoles",
            ],
        ),
        "compute": (
            7,
            13,
            [
                "ReadApplicationLambdaFunctions",
                "UpdateApplicationLambdaFunctions",
                "PublishApplicationLambdaVersions",
                "RetireApplicationLambdaVersions",
                "ManageApplicationQueues",
                "ResolveApplicationQueueUrls",
            ],
        ),
        "observability": (
            13,
            19,
            [
                "ManageApplicationEventRules",
                "ManageApplicationLogs",
                "DescribeApplicationLogPolicies",
                "DescribeApplicationLogGroups",
                "ManageApplicationAlarms",
                "DescribeApplicationNetworking",
            ],
        ),
        "storage": (
            19,
            24,
            [
                "ManageApplicationSiteBuckets",
                "ManageApplicationMeasurementBucket",
                "ManageApplicationMeasurementRegistry",
                "PublishApplicationArtifacts",
                "ReadApplicationArtifactBucket",
            ],
        ),
        "data": (
            24,
            31,
            [
                "UseApplicationKmsKeys",
                "ReadApplicationKmsAliases",
                "ManageApplicationSessions",
                "ManageApplicationCatalog",
                "ManageApplicationAthenaNamedQueries",
                "ManageApplicationAthenaWorkGroup",
                "ListApplicationAthenaWorkGroups",
            ],
        ),
        "runtime": (
            31,
            35,
            [
                "ManageApplicationSchedules",
                "ManageApplicationGuardrail",
                "PublishApplicationGuardrailVersions",
                "ManageApplicationAgentCore",
            ],
        ),
        "edge": (
            35,
            42,
            [
                "ReadApplicationApiGateway",
                "PublishApplicationApiGatewayDeployments",
                "ManageApplicationCloudFront",
                "ReadApplicationCloudFront",
                "ReadManagedCloudFrontPolicies",
                "ReadManagedCloudFrontPolicy",
                "ManageApplicationWaf",
            ],
        ),
    }
    rendered_documents, rendered_aggregate = (
        _terraform_rendered_development_delivery_policies()
    )
    assert len(rendered_documents) <= 10
    assert set(rendered_documents) == set(expected_groups)
    assert len(rendered_aggregate) == len(statements) == 42
    rendered_statements: list[dict[str, object]] = []
    for key, (start, end, expected_sids) in expected_groups.items():
        policy = rendered_documents[key]
        policy_statements = policy.get("Statement")
        assert isinstance(policy_statements, list)
        policy_statements = cast(list[dict[str, object]], policy_statements)
        assert len(policy_statements) == end - start
        rendered_statements.extend(policy_statements)
        assert [
            statement.get("Sid") for statement in policy_statements
        ] == expected_sids
        rendered = json.dumps(policy, separators=(",", ":"))
        assert len(re.sub(r"\s+", "", rendered)) <= 6_144
        assert (
            f"Statement = slice(local.development_delivery_policy_statements, {start}, {end})"
            in FOUNDATION_IAM
        )

    assert rendered_statements == rendered_aggregate
    assert [statement["Sid"] for statement in rendered_statements] == [
        statement["sid"] for statement in statements
    ]
    assert [
        statement["sid"]
        for _, (start, end, _) in expected_groups.items()
        for statement in statements[start:end]
    ] == [statement["sid"] for statement in statements]
    policy_resource = terraform_block(
        FOUNDATION_IAM, 'resource "aws_iam_policy" "development_delivery"'
    )
    assert (
        'for_each = var.environment == "development" ? local.development_delivery_policy_documents : {}'
        in policy_resource
    )
    assert (
        'name     = "nova-toll-v2-development-delivery-${each.key}"' in policy_resource
    )
    assert 'path     = "/nova-toll/v2/development/"' in policy_resource
    assert 'resource "aws_iam_role_policy" "development_delivery"' not in FOUNDATION_IAM
    attachment_resource = terraform_block(
        FOUNDATION_IAM,
        'resource "aws_iam_role_policy_attachment" "development_delivery"',
    )
    assert (
        'for_each   = var.environment == "development" ? local.development_delivery_policy_documents : {}'
        in attachment_resource
    )
    assert (
        "role       = aws_iam_role.development_delivery[0].name" in attachment_resource
    )
    assert (
        "policy_arn = aws_iam_policy.development_delivery[each.key].arn"
        in attachment_resource
    )


def _development_bootstrap_script() -> str:
    bootstrap = DEPLOYMENT.split(
        "The following is the executable, fail-closed inventory and repair procedure.",
        maxsplit=1,
    )[1].split("After bootstrap/import", maxsplit=1)[0]
    match = re.search(r"```sh\n(.*?)\n```", bootstrap, re.DOTALL)
    assert match
    return match.group(1)


def _assert_development_bootstrap_contract(script: str) -> None:
    assert 'EXPECTED_PROFILE="nova-toll-dev"' in script
    assert 'EXPECTED_ACCOUNT="903859731897"' in script
    assert 'REGION="us-east-1"' in script
    assert (
        ': "${AWS_PROFILE:?invoke this procedure with AWS_PROFILE=nova-toll-dev}"'
        in script
    )
    assert 'test "$AWS_PROFILE" = "$EXPECTED_PROFILE"' in script
    assert 'test "${AWS_DEFAULT_REGION:-}" = "$REGION"' in script
    assert "AWS_REGION and AWS_DEFAULT_REGION conflict" in script
    assert 'export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"' in script
    assert 'STATE_BUCKET="nova-toll-tfstate-${EXPECTED_ACCOUNT}"' in script
    assert 'LOCK_KEY="nova-toll/v2/development/bootstrap-lock"' in script
    assert 'LOCK_ARN="arn:aws:s3:::${STATE_BUCKET}/${LOCK_KEY}"' in script
    assert "LOCK_PATH=" not in script
    assert "aws ssm put-parameter" not in script
    assert "aws ssm delete-parameter" not in script
    assert (
        'aws s3api put-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY"'
        in script
    )
    assert "--if-none-match '*'" in script
    assert "PreconditionFailed" in script
    assert "ConditionalRequestConflict" in script
    assert "LOCK_TOKEN=" in script and "/dev/urandom" in script
    assert 'LOCK_STARTED_AT="$(date -u' in script
    assert 'LOCK_VALUE="${LOCK_TOKEN}|${LOCK_STARTED_AT}"' in script
    assert "LOCK_ETAG=" in script and "LOCK_VERSION_ID=" in script
    assert "lock_is_current()" in script
    assert "acquire_bootstrap_lock" in script
    assert "trap bootstrap_cleanup EXIT" in script
    assert script.index("declare -A STATE_PREEXISTING=()") < script.index(
        "trap bootstrap_cleanup EXIT"
    )
    assert script.index("declare -A STATE_IMPORTED_BY_THIS_RUN=()") < script.index(
        "trap bootstrap_cleanup EXIT"
    )
    assert "release_bootstrap_lock" in script
    assert (
        'aws s3api delete-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" --if-match "$LOCK_ETAG"'
        in script
    )
    assert '--version-id "$LOCK_VERSION_ID"' in script
    assert "There\nis no overwrite, expiry, retry, or lock stealing." in DEPLOYMENT
    lock_permissions = DEPLOYMENT.split(
        "The versioned development state bucket uses SSE-KMS.", 1
    )[1].split("The lock uses the", 1)[0]
    assert all(
        action in lock_permissions
        for action in (
            "s3:PutObject",
            "s3:GetObject",
            "s3:DeleteObject",
            "s3:DeleteObjectVersion",
        )
    )
    assert (
        "arn:aws:s3:::nova-toll-tfstate-903859731897/nova-toll/v2/development/bootstrap-lock"
        in lock_permissions
    )
    assert "kms:GenerateDataKey" in lock_permissions
    assert "kms:EncryptionContext:aws:s3:arn" in lock_permissions
    assert "no `kms:Decrypt`" in lock_permissions
    assert "s3:ListBucket" not in lock_permissions
    assert "s3:GetObjectVersion" not in lock_permissions
    assert (
        "bootstrap lock release stopped: current ETag/version does not match" in script
    )
    assert "BOOTSTRAP_EVIDENCE_DIR" in script
    assert "evidence directory must be an absolute path" in script
    assert "evidence must be outside checkout" in script
    assert "aws sts get-caller-identity" in script
    assert 'aws iam get-role --role-name "$ROLE_NAME"' in script
    assert "grep -q 'NoSuchEntity'" in script
    assert 'test "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT"' in script
    assert 'FETCHER_BUILD="$ROOT/v2/scripts/build_fetcher_zip.sh"' in script
    assert 'FETCHER_PACKAGE="$ROOT/infra/build/fetcher.zip"' in script
    assert 'FETCHER_INPUT="$ROOT/v2/lambdas/fetcher/handler.py"' in script
    assert (
        'EXPECTED_FETCHER_SHA256="${EXPECTED_FETCHER_SHA256:?set the reviewed canonical fetcher SHA-256}"'
        in script
    )
    assert 'git -C "$ROOT" fetch --no-tags origin main' in script
    assert 'ORIGIN_URL="$(git -C "$ROOT" remote get-url origin 2>/dev/null)"' in script
    assert "git@github.com:rhprasad0/nova-toll-budget-agent.git" in script
    assert (
        'PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse refs/remotes/origin/main)"'
        in script
    )
    assert (
        'test "$(git -C "$ROOT" rev-parse HEAD)" = "$PROTECTED_MAIN_COMMIT"' in script
    )
    assert 'git -C "$ROOT" status --porcelain --untracked-files=all' in script
    assert 'REVIEWED_COMMIT="$PROTECTED_MAIN_COMMIT"' in script
    assert 'git -C "$ROOT" cat-file -e "$REVIEWED_COMMIT^{commit}"' in script
    assert 'git -C "$ROOT" diff --quiet "$REVIEWED_COMMIT" -- "$relative"' in script
    assert 'test ! -L "$path"' in script
    assert "ls-files --others --exclude-standard" in script
    assert 'test -d "$ROOT/infra/build" && test ! -L "$ROOT/infra/build"' in script
    assert 'test ! -L "$FETCHER_PACKAGE"' in script
    assert 'test ! -L "$ROOT/infra/build/fetcher"' in script
    assert 'env -i PATH="/usr/bin:/bin" LC_ALL=C "$FETCHER_BUILD"' in script
    assert (
        'CANONICAL_FETCHER_SHA256="9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"'
        in script
    )
    assert 'test -s "$FETCHER_PACKAGE"' in script
    assert "placeholder fetcher artifact is not permitted" in script
    assert 'test "$EXPECTED_FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256"' in script
    assert 'test "$FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256"' in script
    assert "TF_VAR_tailscale_advertise_routes:-false" in script
    assert "canonicalize_json()" in script
    assert "urllib.parse.unquote" in script
    assert "sort_keys=True" in script
    assert "render_document" in script
    assert "data.aws_iam_policy_document.development_delivery_assume.json" in script
    assert "local.development_delivery_policy_documents.${policy_key}" in script
    assert (
        "EXPECTED_POLICY_KEYS=(state compute observability storage data runtime edge)"
        in script
    )
    assert 'EXPECTED_POLICY_PATH="/nova-toll/v2/development/"' in script
    assert 'EXPECTED_POLICY_NAMES["$policy_key"]="$ROLE_NAME-$policy_key"' in script
    assert (
        'EXPECTED_POLICY_ARNS["$policy_key"]="arn:aws:iam::$EXPECTED_ACCOUNT:policy${EXPECTED_POLICY_PATH}${EXPECTED_POLICY_NAMES[$policy_key]}"'
        in script
    )
    assert 'ROLE_NAME="nova-toll-v2-development-delivery"' in script
    assert 'ROLE_ARN="arn:aws:iam::$EXPECTED_ACCOUNT:role/$ROLE_NAME"' in script
    assert 'Role.Path == "/"' in script
    assert ".Role.MaxSessionDuration == 3600" in script
    assert "PermissionsBoundary? // null) == null" in script
    assert 'cmp -s "$EXPECTED_TRUST" "$ACTUAL_TRUST"' in script
    assert (
        'aws iam create-role --role-name "$ROLE_NAME" --path / --max-session-duration 3600'
        in script
    )
    assert (
        'aws iam create-policy --policy-name "${EXPECTED_POLICY_NAMES[$policy_key]}" --path "$EXPECTED_POLICY_PATH"'
        in script
    )
    assert (
        'aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"'
        in script
    )
    assert (
        'aws iam get-policy-version --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"'
        in script
    )
    assert 'aws iam list-role-policies --role-name "$ROLE_NAME"' in script
    assert 'aws iam list-attached-role-policies --role-name "$ROLE_NAME"' in script
    assert (
        'aws iam get-policy --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"'
        in script
    )
    assert "policy_set_is_exact" in script
    assert "policy_set_is_safe_subset" in script
    assert "NextToken? // null) == null" in script
    assert script.count(".PolicyNames == []") >= 3
    assert script.count(".AttachedPolicies == []") >= 1
    assert "rollback_created_attachments" in script
    assert (
        script.count(
            'cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}"'
        )
        >= 3
    )
    assert "role_documents_match" in script
    assert (
        "delivery role failed post-attachment exact effective-policy validation"
        in script
    )
    assert (
        "delivery role create failed; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert "assert_dev_account" in script
    assert 'terraform -chdir="$ROOT/infra" state rm' in script
    assert 'terraform -chdir="$ROOT/v2/infra" state rm' in script
    assert "rollback_delivery_state()" in script
    assert "declare -A STATE_PREEXISTING=()" in script
    assert "declare -A STATE_IMPORTED_BY_THIS_RUN=()" in script
    assert (
        "STATE_IMPORTED_BY_THIS_RUN['aws_iam_role.development_delivery[0]']=1" in script
    )
    assert 'STATE_IMPORTED_BY_THIS_RUN["$address"]=1' in script
    assert 'STATE_PREEXISTING["$address"]=1' in script
    assert "already managed or concurrent; refusing state removal" in script
    assert "state ownership is unproven and was retained" in script
    assert "IMPORT_IN_PROGRESS" not in script
    assert (
        script.count('if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi')
        >= 4
    )
    assert "rollback_created_role" in script
    assert "could not verify created delivery role rollback" in script
    assert "MUTATION_AMBIGUOUS=0" in script
    assert script.count("MUTATION_AMBIGUOUS=1") >= 4
    assert "ambiguous mutation result preserved for manual reconciliation" in script
    assert "rollback_created_url()" in script
    assert "rollback_url_state()" in script
    assert "cleanup_on_failure()" in script
    assert "trap cleanup_on_failure EXIT" in script
    assert "BOOTSTRAP_COMPLETE=1" in script
    assert "import_url_state()" in script
    assert "printf -v \"${stem}_CREATED\" '%s' 1" in script
    assert "aws lambda remove-permission" in script
    assert "reconcile_function_url()" not in script
    assert "exact absent-before/present-after reconciliation" not in script
    assert (
        "Lambda URL create failed; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "ambiguous Lambda URL permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "ambiguous Lambda invoke permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert "verify_owned_lambda_permission()" in script
    assert "aws lambda delete-function-url-config" in script
    assert 'terraform -chdir="$ROOT/infra" import' in script
    assert script.count('terraform -chdir="$ROOT/infra" import') == 2
    assert "'aws_iam_role.development_delivery[0]' \"$ROLE_ARN\"" in script
    assert 'address="aws_iam_policy.development_delivery[\\"$policy_key\\"]"' in script
    assert 'terraform -chdir="$ROOT/infra" state show -no-color' in script
    assert "'aws_iam_role.development_delivery[0]'" in script
    assert 'address="aws_iam_policy.development_delivery[\\"$policy_key\\"]"' in script
    assert (
        'aws_iam_role_policy_attachment.development_delivery[\\"$policy_key\\"]'
        in script
    )
    assert "delivery role import state ID or ARN is not the exact target" in script
    assert "delivery managed-policy import state ID is not the exact target" in script
    assert "state_id_matches()" in script
    assert "state_list_contains()" in script
    assert (
        "awk -v address=\"$address\" '$0 == address { found=1 } END { exit found ? 0 : 1 }'"
        in script
    )
    assert (
        'terraform -chdir="$ROOT/infra" state list >"$FOUNDATION_STATE_LIST"' in script
    )
    assert (
        'terraform -chdir="$ROOT/v2/infra" state list >"$APPLICATION_STATE_LIST"'
        in script
    )
    assert "state list | grep -Fxq" not in script
    assert 'state_id_matches "$WORK_DIR/${label// /-}.state" "$identifier"' in script
    assert "Terraform state ID does not match exact target $identifier" in script
    assert (
        "import_url_state 'aws_lambda_function_url.public_chat' \"$FUNCTION_NAME,$QUALIFIER\""
        in script
    )
    assert (
        "import_url_state 'aws_lambda_permission.public_chat_url' \"$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionUrlV2\""
        in script
    )
    assert (
        "import_url_state 'aws_lambda_permission.public_chat_invoke' \"$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionInvokeV2\""
        in script
    )
    assert "aws_lambda_function_url.public_chat" in script
    assert 'DISTRIBUTION_ID="E33DVF3KT7BTAC"' in script
    assert 'DISTRIBUTION_DOMAIN="d1wqry4fbd92w5.cloudfront.net"' in script
    assert (
        "DistributionList.Items[?Id==`E33DVF3KT7BTAC` && DomainName==`d1wqry4fbd92w5.cloudfront.net`]"
        in script
    )
    assert "validate_function_url" in script
    assert '.AuthType == "AWS_IAM" and .InvokeMode == "RESPONSE_STREAM"' in script
    assert "validate_lambda_policy" in script
    assert "validate_existing_lambda_policy" in script
    assert "snapshot_lambda_permission" in script
    assert "reconcile_lambda_permission" in script
    assert "lambda-policy-before-" in script and "lambda-policy-after-" in script
    assert "lambda-statement-before-" in script and "lambda-statement-after-" in script
    assert "RevisionId" in script and "--revision-id" in script
    assert (
        "ambiguous Lambda URL permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "ambiguous Lambda invoke permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "Lambda rollback changed a pre-existing or concurrent permission statement"
        in script
    )
    assert 'cmp -s "$expected" "$statement"' in script
    assert "lambda:InvokeFunctionUrl" in script and "lambda:InvokeFunction" in script
    assert [
        line.strip()
        for line in script.splitlines()
        if line.strip().startswith(".Principal == {Service:")
    ] == [
        '.Principal == {Service: "cloudfront.amazonaws.com"} and',
        '.Principal == {Service: "cloudfront.amazonaws.com"} and',
    ]
    assert "AWS:SourceArn" in script
    assert "run_post_bootstrap_gates" in script
    assert "aws iam simulate-principal-policy" in script
    assert "IAM_SIMULATION_EVIDENCE" in script
    assert "SIMULATION_EXPECTED_COUNT=92" in script
    assert "while IFS='|' read -r label action resource expected; do" in script
    assert "--context-entries" in script
    assert "SIMULATION_COUNT" in script
    assert (
        "s3:GetObject|arn:aws:s3:::nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate|denied"
        in script
    )
    assert "nova-toll-state-920534282028" not in script
    for required_simulation in (
        "lambda:UpdateFunctionCode",
        "lambda:PublishVersion",
        "lambda:UpdateAlias",
        "lambda:DeleteFunction",
        "s3:PutObject",
        "s3:DeleteObject",
        "cloudfront:UpdateFunction",
        "cloudfront:PublishFunction",
        "bedrock:CreateGuardrailVersion",
        "apigateway:POST",
        "apigateway:DELETE",
        "bedrock-agentcore:UpdateAgentRuntime",
        "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
        "iam:CreateRole",
        "iam:PutRolePolicy",
        "iam:PassRole",
        "iam:AttachRolePolicy",
        "lambda:AddPermission",
        "lambda:UpdateFunctionConfiguration",
        "bedrock-agentcore:CreateAgentRuntime",
        "bedrock-agentcore:PutResourcePolicy",
        "events:PutRule",
        "logs:PutMetricFilter",
        "cloudwatch:PutMetricAlarm",
        "wafv2:PutLoggingConfiguration",
        "kms:CreateAlias",
        "kms:UpdateAlias",
        "ec2:AuthorizeSecurityGroupIngress",
        "sqs:SetQueueAttributes",
        "sqs:AddPermission",
        "sqs:RemovePermission",
        "s3:PutBucketPolicy",
        "s3:PutBucketPublicAccessBlock",
        "athena:CreateNamedQuery",
        "s3:PutBucketOwnershipControls",
        "s3:PutBucketTagging",
        "s3:PutBucketVersioning",
        "s3:PutEncryptionConfiguration",
        "s3:PutLifecycleConfiguration",
        "s3:AbortMultipartUpload",
        "events:DisableRule",
        "events:EnableRule",
        "events:RemoveTargets",
        "events:TagResource",
        "events:UntagResource",
        "logs:TagResource",
        "logs:UntagResource",
        "dynamodb:UpdateContinuousBackups",
        "dynamodb:UpdateTimeToLive",
        "glue:UpdateDatabase",
        "athena:TagResource",
        "athena:UntagResource",
        "scheduler:TagResource",
        "scheduler:UntagResource",
        "bedrock-agentcore:TagResource",
        "bedrock-agentcore:UntagResource",
        "cloudfront:TestFunction",
        "cloudfront:TagResource",
        "cloudfront:UntagResource",
        "kms:GenerateDataKey",
    ):
        assert required_simulation in script
    assert 'PACKAGE_DIGESTS="$WORK_DIR/package-digests.tsv"' in script
    assert "PACKAGE_DIGESTS_JSON=" in script
    assert 'EVIDENCE_BINDING="$EVIDENCE_DIR/evidence-binding.json"' in script
    for evidence_field in (
        "commit_sha",
        "account_id",
        "role_arn",
        "policy_sha256",
        "fetcher_sha256",
        "plan_sha256",
        "timestamp",
        "binding_sha256",
    ):
        assert evidence_field in script
    assert "REPRESENTATIVE_V2_PACKAGE_DIR" not in script
    assert "REVIEWED_V2_PACKAGE_DIR" in script
    assert "REPRESENTATIVE_PLAN_EVIDENCE" in script
    assert (
        'terraform -chdir="$ROOT/v2/infra" show -json "$REPRESENTATIVE_PLAN"' in script
    )
    assert (
        'PLAN_GATE_SOURCE="$ROOT/.github/workflows/v2-development-delivery.yml"'
        in script
    )
    assert 'python3 "$PLAN_GATE" "$REPRESENTATIVE_PLAN_JSON"' in script
    assert "PROTECTED_MAIN_OIDC_EVIDENCE" in script
    assert "protected-main-oidc" in script
    assert 'jq -e --arg commit "$REVIEWED_COMMIT"' in script
    assert ".commit_sha == $commit" in script
    assert "console -var environment=development" in script
    assert "for policy_mapping in" in script
    assert "for attachment_mapping in" in script
    for mapping in (
        "loader toll-v2-pricing-loader-dev toll-v2-pricing-loader-dev",
        "publisher toll-v2-report-publisher-dev toll-v2-report-publisher-dev",
        "publisher_scheduler toll-v2-report-publisher-scheduler-dev toll-v2-report-publisher-scheduler-dev",
        "timed_checks nova-toll-v2-timed-checks-dev nova-toll-v2-route-live-checks-dev",
        "tollchat_runtime nova-toll-v2-agentcore-runtime-dev nova-toll-v2-agentcore-runtime-dev",
        "tollchat_proxy nova-toll-v2-chat-proxy-dev nova-toll-v2-chat-proxy-dev",
        "usage_publisher tollchat-v2-usage-publisher-dev tollchat-v2-usage-publisher-dev",
        "agent_usage_rollup tollchat-v2-agent-usage-rollup-dev tollchat-v2-agent-usage-rollup-dev",
    ):
        assert mapping in script
    for mapping in (
        "loader_vpc toll-v2-pricing-loader-dev",
        "publisher_vpc toll-v2-report-publisher-dev",
        "tollchat_proxy_vpc nova-toll-v2-chat-proxy-dev",
    ):
        assert mapping in script
    assert 'get-public-access-block --bucket "$MEASUREMENT_BUCKET"' in script
    assert 'get-public-access-block --bucket "$SITE_BUCKET"' in script
    assert 'one "response-headers CloudFront" aws cloudfront' in script
    assert "one response-headers CloudFront aws cloudfront" not in script
    assert "get-bucket-public-access-block" not in script
    assert 'terraform -chdir="$ROOT/infra" apply' not in script
    assert "FOUNDATION_PLAN" not in script
    assert "terraform -target" not in script
    assert "terraform_remote_state" not in script
    assert "nova-toll-prod" not in script
    assert "nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate" in script
    for generic_guard in (
        "review URL create command",
        "review URL permission, then set",
        "review URL invoke permission, then set",
        "review $label import, then set",
    ):
        assert generic_guard not in script
    for exact_guard in (
        "aws iam create-role --role-name $ROLE_NAME --path / --max-session-duration 3600",
        'aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"',
        "aws lambda create-function-url-config --function-name $FUNCTION_NAME --qualifier $QUALIFIER",
        "aws lambda add-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER",
        "terraform -chdir=$ROOT/v2/infra import -input=false $address $identifier",
        "terraform -chdir=$ROOT/v2/infra state rm $address",
    ):
        assert exact_guard in script
    assert script.count('test "${BOOTSTRAP_APPROVED:-}" = YES') >= 14
    assert script.count("assert_dev_account") >= 14


def _assert_development_bootstrap_iam_rollback_contract(script: str) -> None:
    attachment_rollback = script.split("rollback_created_attachments() {", maxsplit=1)[
        1
    ].split("rollback_created_role() {", maxsplit=1)[0]
    guarded = re.search(
        r'if ! aws iam detach-role-policy --role-name "\$ROLE_NAME".*?\n\s*fi',
        attachment_rollback,
        re.DOTALL,
    )
    assert guarded is not None
    assert "MUTATION_AMBIGUOUS=1" in guarded.group(0)
    assert "preserving" in guarded.group(0)
    role_rollback = script.split("rollback_created_role() {", maxsplit=1)[1].split(
        "acquire_bootstrap_lock", maxsplit=1
    )[0]
    guarded = re.search(
        r'if ! aws iam delete-role --role-name "\$ROLE_NAME".*?\n\s*fi',
        role_rollback,
        re.DOTALL,
    )
    assert guarded is not None
    assert "MUTATION_AMBIGUOUS=1" in guarded.group(0)
    assert "preserving" in guarded.group(0)
    assert "aws iam delete-role-policy" not in script
    assert "aws iam put-role-policy" not in script

    state_rollback = script.split("rollback_delivery_state() {", maxsplit=1)[1].split(
        "verify_foundation_state() {", maxsplit=1
    )[0]
    assert 'if test "${MUTATION_AMBIGUOUS:-0}" -ne 0; then' in state_rollback
    assert "state rollback stopped: ambiguous IAM mutation result" in state_rollback

    cleanup = script.split("bootstrap_cleanup() {", maxsplit=1)[1].split(
        "\n}\n", maxsplit=1
    )[0]
    assert cleanup.index("rollback_created_role") < cleanup.index(
        "rollback_delivery_state"
    )
    assert (
        'test "$MUTATION_AMBIGUOUS" -eq 0 && declare -F rollback_delivery_state'
        in cleanup
    )


def test_development_bootstrap_iam_rollbacks_are_ambiguity_safe():
    script = _development_bootstrap_script()
    _assert_development_bootstrap_iam_rollback_contract(script)
    for function_name, command_prefix in (
        (
            "rollback_created_attachments",
            'if ! aws iam detach-role-policy --role-name "$ROLE_NAME"',
        ),
        (
            "rollback_created_role",
            'if ! aws iam delete-role --role-name "$ROLE_NAME"',
        ),
    ):
        function_start = script.index(f"{function_name}() {{")
        function_end = script.index("\n}\n", function_start) + 3
        function = script[function_start:function_end]
        assignment = function.index(
            "MUTATION_AMBIGUOUS=1", function.index(command_prefix)
        )
        mutated = script[: function_start + assignment] + script[
            function_start + assignment :
        ].replace("MUTATION_AMBIGUOUS=1", "MUTATION_AMBIGUOUS=0", 1)
        with pytest.raises(AssertionError):
            _assert_development_bootstrap_iam_rollback_contract(mutated)


def test_development_bootstrap_runbook_is_executable_and_fail_closed():
    script = _development_bootstrap_script()
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_development_bootstrap_rejects_unsafe_role_comparison_and_mixed_plan_mutations():
    script = _development_bootstrap_script()
    _assert_development_bootstrap_contract(script)
    for original, replacement in (
        ('EXPECTED_PROFILE="nova-toll-dev"', 'EXPECTED_PROFILE="nova-toll-prod"'),
        ('EXPECTED_ACCOUNT="903859731897"', 'EXPECTED_ACCOUNT="920534282028"'),
        ('REGION="us-east-1"', 'REGION="us-west-2"'),
        (
            'CANONICAL_FETCHER_SHA256="9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"',
            'CANONICAL_FETCHER_SHA256="0000000000000000000000000000000000000000000000000000000000000000"',
        ),
        ('git -C "$ROOT" fetch --no-tags origin main', "true"),
        (
            "git@github.com:rhprasad0/nova-toll-budget-agent.git",
            "git@github.com:evil/fork.git",
        ),
        ('test "$(git -C "$ROOT" rev-parse HEAD)" = "$PROTECTED_MAIN_COMMIT"', "true"),
        ('git -C "$ROOT" status --porcelain --untracked-files=all', "true"),
        (
            'PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse refs/remotes/origin/main)"',
            'PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"',
        ),
        ('git -C "$ROOT" diff --quiet "$REVIEWED_COMMIT" -- "$relative"', "true"),
        ('env -i PATH="/usr/bin:/bin" LC_ALL=C "$FETCHER_BUILD"', '"$FETCHER_BUILD"'),
        ('Role.Path == "/"', 'Role.Path == "/unexpected"'),
        (".Role.MaxSessionDuration == 3600", ".Role.MaxSessionDuration == 86400"),
        (
            "PermissionsBoundary? // null) == null",
            "PermissionsBoundary? // null) == true",
        ),
        ('cmp -s "$EXPECTED_TRUST" "$ACTUAL_TRUST"', "true"),
        (
            'cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}"',
            "true",
        ),
        ("urllib.parse.unquote(value)", "value"),
        ("sort_keys=True", "sort_keys=False"),
        (".PolicyNames == []", ".PolicyNames | length >= 0"),
        (".AttachedPolicies == []", ".AttachedPolicies != []"),
        (
            'ROLE_ARN="arn:aws:iam::$EXPECTED_ACCOUNT:role/$ROLE_NAME"',
            'ROLE_ARN="arn:aws:iam::920534282028:role/other"',
        ),
        (
            'aws iam list-attached-role-policies --role-name "$ROLE_NAME"',
            'aws iam list-attached-role-policies --role-name "$UNSAFE_ROLE"',
        ),
        (
            'aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"',
            'aws iam attach-role-policy --role-name "$UNSAFE_ROLE" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"',
        ),
        (".commit_sha == $commit", '.commit_sha == "untrusted"'),
        (
            'state_id_matches "$WORK_DIR/${label// /-}.state" "$identifier"',
            'state_id_matches "$WORK_DIR/${label// /-}.state" "$UNSAFE_IDENTIFIER"',
        ),
        ("SIMULATION_EXPECTED_COUNT=92", "SIMULATION_EXPECTED_COUNT=1"),
        ("evidence-binding.json", "spoofed-evidence.json"),
    ):
        _must_reject(
            _assert_development_bootstrap_contract, script, original, replacement
        )

    mixed_plan = (
        script + '\nterraform -chdir="$ROOT/infra" apply "$WORK_DIR/mixed.tfplan"\n'
    )
    with pytest.raises(AssertionError):
        _assert_development_bootstrap_contract(mixed_plan)

    without_approval = script.replace('test "${BOOTSTRAP_APPROVED:-}" = YES', "true")
    with pytest.raises(AssertionError):
        _assert_development_bootstrap_contract(without_approval)


def test_development_bootstrap_canonicalizes_encoded_policy_documents_and_rejects_malformed_input():
    script = _development_bootstrap_script()
    match = re.search(
        r"canonicalize_json\(\) \{.*?python3 - \"\$input\" \"\$output\" <<'PY'\n(.*?)\nPY",
        script,
        re.DOTALL,
    )
    assert match is not None
    canonicalizer = match.group(1)
    with tempfile.TemporaryDirectory() as directory:
        raw = Path(directory) / "raw.json"
        output = Path(directory) / "canonical.json"
        raw.write_text(json.dumps("%7B%22b%22%3A2%2C%22a%22%3A1%7D"))
        result = subprocess.run(
            [sys.executable, "-c", canonicalizer, str(raw), str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert output.read_text() == '{"a":1,"b":2}\n'

        raw.write_text(json.dumps("%7Bmalformed"))
        result = subprocess.run(
            [sys.executable, "-c", canonicalizer, str(raw), str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0


def test_development_bootstrap_decodes_encoded_lambda_policy_response():
    script = _development_bootstrap_script()
    canonicalizer_match = re.search(
        r"(canonicalize_json\(\) \{.*?\n\})\n\ndecode_lambda_policy_response",
        script,
        re.DOTALL,
    )
    decoder_match = re.search(
        r"(decode_lambda_policy_response\(\) \{.*?\n\})\n\nROLE_ARN=",
        script,
        re.DOTALL,
    )
    assert canonicalizer_match is not None and decoder_match is not None
    helpers = canonicalizer_match.group(1) + "\n\n" + decoder_match.group(1)
    policy = {
        "Version": "2012-10-17",
        "Statement": [{"Sid": "encoded", "Effect": "Allow"}],
    }
    for encoded in (
        json.dumps(policy),
        urllib.parse.quote(json.dumps(policy), safe=""),
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "response.json"
            output = root / "decoded.json"
            raw.write_text(json.dumps({"Policy": encoded, "RevisionId": "r1"}))
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    helpers
                    + "\n"
                    + 'WORK_DIR="$1"; decode_lambda_policy_response "$2" "$3"; '
                    + 'jq -e \' .PolicyDocument.Statement[0].Sid == "encoded" \' "$3" >/dev/null',
                    "bootstrap-policy-reader",
                    str(root),
                    str(raw),
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr


def test_development_bootstrap_effective_policy_fixtures_reject_extra_inline_and_attached_policies():
    script = _development_bootstrap_script()
    policy_match = re.search(
        r'jq -e \'(\.PolicyNames == \[\])\' "\$ROLE_POLICY_NAMES"',
        script,
    )
    attachment_match = re.search(
        r'jq -e --argjson expected "\$EXPECTED_POLICY_ARNS_JSON" \'(.*?)\' "\$ROLE_ATTACHMENTS"',
        script,
    )
    assert policy_match is not None and attachment_match is not None
    policy_filter = policy_match.group(1)
    attachment_filter = attachment_match.group(1)
    expected_arns = [
        "arn:aws:iam::903859731897:policy/nova-toll/v2/development/"
        f"nova-toll-v2-development-delivery-{key}"
        for key in (
            "state",
            "compute",
            "observability",
            "storage",
            "data",
            "runtime",
            "edge",
        )
    ]

    def accepts(policy_names: list[str], attached: list[dict[str, str]]) -> bool:
        with tempfile.TemporaryDirectory() as directory:
            policy_file = Path(directory) / "policies.json"
            attachment_file = Path(directory) / "attachments.json"
            policy_file.write_text(json.dumps({"PolicyNames": policy_names}))
            attachment_file.write_text(json.dumps({"AttachedPolicies": attached}))
            policy_result = subprocess.run(
                [
                    "jq",
                    "-e",
                    policy_filter,
                    str(policy_file),
                ],
                capture_output=True,
                check=False,
            )
            attachment_result = subprocess.run(
                [
                    "jq",
                    "-e",
                    "--argjson",
                    "expected",
                    json.dumps(expected_arns),
                    attachment_filter,
                    str(attachment_file),
                ],
                capture_output=True,
                check=False,
            )
            return policy_result.returncode == 0 and attachment_result.returncode == 0

    assert accepts(
        [],
        [{"PolicyArn": arn} for arn in expected_arns],
    )
    assert not accepts(
        ["unexpected-inline"],
        [{"PolicyArn": arn} for arn in expected_arns],
    )
    assert not accepts(
        [],
        [{"PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}],
    )


def test_development_bootstrap_rejects_stale_packages_and_wrong_state_ids():
    script = _development_bootstrap_script()
    manifest_match = re.search(
        r"""python3 - "\$REVIEWED_V2_PACKAGE_MANIFEST" "\$REVIEWED_V2_PACKAGE_DIR" <<'PY'\n(.*?)\nPY""",
        script,
        re.DOTALL,
    )
    state_match = re.search(
        r"""state_id_matches\(\) \{\n  local state_file="\$1" expected="\$2"\n  python3 - "\$state_file" "\$expected" <<'PY'\n(.*?)\nPY""",
        script,
        re.DOTALL,
    )
    assert manifest_match is not None and state_match is not None
    validator = manifest_match.group(1)
    state_validator = state_match.group(1)
    with tempfile.TemporaryDirectory() as directory:
        package_dir = Path(directory) / "packages"
        package_dir.mkdir()
        files = {
            name: f"reviewed-{name}".encode()
            for name in (
                "loader.zip",
                "publisher.zip",
                "agentcore.zip",
                "chat-proxy.zip",
            )
        }
        for name, contents in files.items():
            (package_dir / name).write_bytes(contents)
        manifest = Path(directory) / "DEPLOYMENT_SHA256SUMS"
        manifest.write_text(
            "".join(
                f"{hashlib.sha256(contents).hexdigest()}  {name}\n"
                for name, contents in files.items()
            )
        )
        valid = subprocess.run(
            [sys.executable, "-c", validator, str(manifest), str(package_dir)],
            capture_output=True,
            check=False,
        )
        assert valid.returncode == 0, valid.stderr.decode()
        (package_dir / "loader.zip").write_bytes(b"spoofed")
        stale = subprocess.run(
            [sys.executable, "-c", validator, str(manifest), str(package_dir)],
            capture_output=True,
            check=False,
        )
        assert stale.returncode != 0

        state = Path(directory) / "state.txt"
        state.write_text('    id = "function,qualifier"\n')
        assert (
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    state_validator,
                    str(state),
                    "function,qualifier",
                ],
                check=False,
            ).returncode
            == 0
        )
        assert (
            subprocess.run(
                [sys.executable, "-c", state_validator, str(state), "wrong,qualifier"],
                check=False,
            ).returncode
            != 0
        )


def test_development_bootstrap_mocked_failures_are_approval_gated_and_reverse_ordered():
    """Exercise the bounded mutation/compensation protocol without AWS access."""
    harness = dedent(
        r"""
        set -euo pipefail
        : "${SCENARIO:?}"
        : "${LOG:?}"
        mutate() {
          test "${BOOTSTRAP_APPROVED:-}" = YES || { printf 'approval-required:%s\n' "$1" >>"$LOG"; return 77; }
          printf '%s\n' "$1" >>"$LOG"
          test "${FAIL_ACTION:-}" != "$1" || return 1
        }
        rollback_role() {
          mutate detach-role-policy || return
          mutate delete-role
        }
        rollback_url() {
          mutate remove-permission-invoke || return
          mutate remove-permission-url || return
          mutate delete-function-url
        }
        rollback_state() {
          mutate state-rm-invoke || return
          mutate state-rm-url-permission || return
          mutate state-rm-url
        }
        rollback_delivery_state() {
          mutate state-rm-attachment || return
          mutate state-rm-policy || return
          mutate state-rm-role
        }
        case "$SCENARIO" in
          create-role) mutate create-role && mutate create-policy && mutate attach-role-policy ;;
          create-policy) mutate create-role && mutate create-policy && mutate attach-role-policy ;;
          role-import|policy-import|url-import) mutate "$SCENARIO" || { rollback_state; exit 1; } ;;
          post-import-verification) mutate role-import && mutate policy-import && { rollback_delivery_state; exit 1; } ;;
          url-create) mutate create-function-url ;;
          url-permission-import|url-invoke-import)
            mutate state-rm-url || { rollback_url; exit 1; }
            mutate "$SCENARIO" || { rollback_state; rollback_url; exit 1; }
            ;;
          *) exit 2 ;;
        esac
        """
    )

    def run(
        scenario: str, *, approved: bool
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "mutations.log"
            env = os.environ.copy()
            fail_action = {"url-create": "create-function-url"}.get(scenario, scenario)
            env.update(
                {"SCENARIO": scenario, "LOG": str(log), "FAIL_ACTION": fail_action}
            )
            if approved:
                env["BOOTSTRAP_APPROVED"] = "YES"
            result = subprocess.run(
                ["bash", "-c", harness],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            return result, log.read_text().splitlines() if log.exists() else []

    for scenario in (
        "create-role",
        "create-policy",
        "role-import",
        "policy-import",
        "url-import",
        "url-create",
        "url-permission-import",
        "url-invoke-import",
        "post-import-verification",
    ):
        result, log = run(scenario, approved=False)
        assert result.returncode != 0
        first_action = {
            "create-policy": "create-role",
            "url-create": "create-function-url",
            "url-permission-import": "state-rm-url",
            "url-invoke-import": "state-rm-url",
            "post-import-verification": "role-import",
        }.get(scenario, scenario)
        assert log[0] == f"approval-required:{first_action}"
        assert all(entry.startswith("approval-required:") for entry in log)

    for scenario in (
        "create-role",
        "create-policy",
        "role-import",
        "policy-import",
        "url-import",
        "url-create",
        "url-permission-import",
        "url-invoke-import",
        "post-import-verification",
    ):
        result, log = run(scenario, approved=True)
        assert result.returncode != 0, scenario
        if scenario == "create-policy":
            assert log == ["create-role", "create-policy"]
        elif scenario == "url-create":
            assert log == ["create-function-url"]
        elif scenario in {"url-create", "url-permission-import", "url-invoke-import"}:
            assert log[-3:] == [
                "remove-permission-invoke",
                "remove-permission-url",
                "delete-function-url",
            ]
        elif scenario == "post-import-verification":
            assert log == [
                "role-import",
                "policy-import",
                "state-rm-attachment",
                "state-rm-policy",
                "state-rm-role",
            ]
        else:
            assert log[0] == scenario


def test_development_bootstrap_mocked_lock_and_import_ownership_races():
    harness = dedent(
        r"""
        set -euo pipefail
        : "${ACTION:?}" "${ROOT:?}" "${LOG:?}"
        LOCK="$ROOT/bootstrap-lock"
        LOCK_BODY="$LOCK.body"
        LOCK_ETAG="$LOCK.etag"
        LOCK_VERSION="$LOCK.version"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        acquire() {
          local owner="${1:-${OWNER:-owner-a}}"
          if ! mkdir -- "$LOCK" 2>/dev/null; then
            log lock-already-held
            return 77
          fi
          printf '%s|2026-09-02T00:00:00Z' "$owner" >"$LOCK_BODY"
          printf '%s-etag' "$owner" >"$LOCK_ETAG"
          printf '%s-version' "$owner" >"$LOCK_VERSION"
          log lock-acquired
          if test "${AMBIGUOUS:-0}" -eq 1; then
            log lock-ambiguous
            return 1
          fi
        }
        release_observed() {
          local observed_etag="$1" observed_version="$2" current_etag current_version
          current_etag="$(<"$LOCK_ETAG")" || { log lock-read-failed; return 1; }
          current_version="$(<"$LOCK_VERSION")" || { log lock-read-failed; return 1; }
          test "$current_etag" = "$observed_etag" &&
            test "$current_version" = "$observed_version" || {
              log stale-etag-preserved
              return 1
            }
          rmdir -- "$LOCK"
          rm -- "$LOCK_BODY" "$LOCK_ETAG" "$LOCK_VERSION"
          test ! -e "$LOCK"
          log lock-released
        }
        import_state() {
          if test -e "$ROOT/state"; then
            log state-preexisting
            return 0
          fi
          case "${IMPORT_RESULT:-success}" in
            already-managed|failed)
              printf '%s' target >"$ROOT/state"
              log "import-${IMPORT_RESULT}-retained"
              return 1
              ;;
            success)
              printf '%s' target >"$ROOT/state"
              OWNED=1
              log import-success-owned
              ;;
          esac
        }
        rollback_state() {
          test "${OWNED:-0}" -eq 1 || return 0
          test "$(<"$ROOT/state")" = target || { log state-id-mismatch-preserved; return 1; }
          rm -- "$ROOT/state"
          log state-rm-owned
        }
        case "$ACTION" in
          acquire) acquire ;;
          acquire-ambiguous) AMBIGUOUS=1 acquire || true; test -d "$LOCK"; log ambiguous-lock-retained ;;
          release) acquire; release_observed "${OWNER:-owner-a}-etag" "${OWNER:-owner-a}-version" ;;
          wrong-owner) acquire owner-a; release_observed owner-b-etag owner-b-version ;;
          stale-reacquire)
            acquire owner-a
            OLD_ETAG=owner-a-etag
            OLD_VERSION=owner-a-version
            rmdir -- "$LOCK"
            rm -- "$LOCK_BODY" "$LOCK_ETAG" "$LOCK_VERSION"
            acquire owner-b
            release_observed "$OLD_ETAG" "$OLD_VERSION" || true
            test -d "$LOCK"
            log stale-owner-cannot-delete-new-lock
            release_observed owner-b-etag owner-b-version
            ;;
          stale) test -e "$LOCK"; log stale-lock-stop ;;
          import) import_state ;;
          import-and-verify-fail) import_state; rollback_state ;;
          *) exit 2 ;;
        esac
        """
    )

    def run_lock(
        action: str, directory: Path, owner: str = "owner-a"
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        log = directory / f"{action}-{owner}.log"
        env = os.environ.copy()
        env.update(
            {"ACTION": action, "ROOT": str(directory), "LOG": str(log), "OWNER": owner}
        )
        result = subprocess.run(
            ["bash", "-c", harness],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return result, log.read_text().splitlines() if log.exists() else []

    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        first = subprocess.Popen(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "acquire",
                "ROOT": str(directory),
                "LOG": str(directory / "a.log"),
                "OWNER": "owner-a",
            },
            text=True,
        )
        second = subprocess.Popen(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "acquire",
                "ROOT": str(directory),
                "LOG": str(directory / "b.log"),
                "OWNER": "owner-b",
            },
            text=True,
        )
        assert sorted((first.wait(), second.wait())) == [0, 77]
        logs = (directory / "a.log").read_text() + (directory / "b.log").read_text()
        assert logs.count("lock-acquired") == 1
        assert logs.count("lock-already-held") == 1
        (directory / "a.log").unlink(missing_ok=True)
        (directory / "b.log").unlink(missing_ok=True)

        result, log = run_lock("acquire-ambiguous", directory)
        assert result.returncode == 0 and "ambiguous-lock-retained" in log
        result, log = run_lock("stale", directory, owner="owner-b")
        assert result.returncode == 0 and log == ["stale-lock-stop"]
        (directory / "bootstrap-lock").rmdir()
        for suffix in ("body", "etag", "version"):
            (directory / f"bootstrap-lock.{suffix}").unlink()

        result, log = run_lock("release", directory)
        assert result.returncode == 0 and log == ["lock-acquired", "lock-released"]
        result, log = run_lock("wrong-owner", directory, owner="owner-b")
        assert result.returncode != 0 and log == [
            "lock-acquired",
            "stale-etag-preserved",
        ]
        (directory / "bootstrap-lock").rmdir()
        for suffix in ("body", "etag", "version"):
            (directory / f"bootstrap-lock.{suffix}").unlink()

        result, log = run_lock("stale-reacquire", directory)
        assert result.returncode == 0
        assert log == [
            "lock-acquired",
            "lock-acquired",
            "stale-etag-preserved",
            "stale-owner-cannot-delete-new-lock",
            "lock-released",
        ]
        assert not (directory / "bootstrap-lock").exists()

        for import_result, expected in (
            ("already-managed", ["import-already-managed-retained"]),
            (
                "failed",
                ["import-failed-retained"],
            ),
        ):
            (directory / "import.log").unlink(missing_ok=True)
            env = {
                **os.environ,
                "ACTION": "import",
                "ROOT": str(directory),
                "LOG": str(directory / "import.log"),
                "IMPORT_RESULT": import_result,
            }
            result = subprocess.run(
                ["bash", "-c", harness],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode != 0
            assert (directory / "import.log").read_text().splitlines() == expected
            assert not (directory / "import.log").read_text().count("state-rm")
            (directory / "state").unlink()

        env = {
            **os.environ,
            "ACTION": "import-and-verify-fail",
            "ROOT": str(directory),
            "LOG": str(directory / "import-own.log"),
        }
        result = subprocess.run(
            ["bash", "-c", harness],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        assert (directory / "import-own.log").read_text().splitlines() == [
            "import-success-owned",
            "state-rm-owned",
        ]
        assert not (directory / "state").exists()


def test_development_bootstrap_state_membership_is_pipefail_safe_for_large_lists():
    harness = dedent(
        r"""
        set -euo pipefail
        : "${ROOT:?}" "${LOG:?}"
        STATE_LIST="$ROOT/state.list"
        emit_state_list() {
          printf '%s\n' aws_preexisting.resource
          for index in $(seq 1 2048); do
            printf 'aws_padding.resource[%s]\n' "$index"
          done
          printf '%s\n' aws_owned.resource
        }
        state_list_contains() {
          local state_file="$1" address="$2"
          awk -v address="$address" '$0 == address { found=1 } END { exit found ? 0 : 1 }' "$state_file"
        }
        emit_state_list >"$STATE_LIST"
        state_list_contains "$STATE_LIST" aws_preexisting.resource
        state_list_contains "$STATE_LIST" aws_owned.resource
        if state_list_contains "$STATE_LIST" aws_missing.resource; then exit 1; fi
        rollback() {
          local address
          for address in aws_preexisting.resource aws_owned.resource aws_missing.resource; do
            state_list_contains "$STATE_LIST" "$address" || continue
            case "$address" in
              aws_preexisting.resource) printf '%s\n' preexisting-preserved >>"$LOG" ;;
              aws_owned.resource) printf '%s\n' owned-rollback >>"$LOG" ;;
            esac
          done
        }
        rollback
        test "$(wc -l <"$STATE_LIST")" -eq 2050
        """
    )
    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        log = directory / "events.log"
        result = subprocess.run(
            ["bash", "-c", harness],
            env={**os.environ, "ROOT": str(directory), "LOG": str(log)},
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert log.read_text().splitlines() == [
            "preexisting-preserved",
            "owned-rollback",
        ]


def test_development_bootstrap_mocked_lambda_permission_ownership_races():
    harness = dedent(
        r"""
        set -euo pipefail
        : "${SCENARIO:?}" "${ROOT:?}" "${LOG:?}"
        SID="${SID:-AllowCloudFrontFunctionUrlV2}"
        EXPECTED="reviewed:$SID"
        POLICY="$ROOT/policy"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        snapshot() {
          if test -e "$POLICY"; then PRE_PRESENT=1; PRE_CONTENT="$(<"$POLICY")"; else PRE_PRESENT=0; PRE_CONTENT=; fi
          PRE_REVISION="${REVISION:-rev-1}"
          log snapshot
        }
        add_permission() {
          case "$SCENARIO" in
            success) printf '%s' "$EXPECTED" >"$POLICY"; REVISION=rev-2; return 0 ;;
            ambiguous-applied) printf '%s' "$EXPECTED" >"$POLICY"; REVISION=rev-2; return 1 ;;
            ambiguous-mismatch) printf '%s' foreign >"$POLICY"; REVISION=rev-2; return 1 ;;
            ambiguous-stale-revision) printf '%s' "$EXPECTED" >"$POLICY"; REVISION=rev-1; return 1 ;;
            ambiguous-not-applied) return 1 ;;
            preexisting) return 1 ;;
          esac
        }
        reconcile() {
          test "${PRE_PRESENT:-0}" -eq 0 || return 1
          test -e "$POLICY" && test "$(<"$POLICY")" = "$EXPECTED" || return 1
          test "${PRE_REVISION:-}" = "${REVISION:-}" && return 1
          OWNED=1
          log permission-owned
        }
        rollback() {
          test "${OWNED:-0}" -eq 1 || return 0
          test "$(<"$POLICY")" = "$EXPECTED" || { log foreign-preserved; return 1; }
          rm -- "$POLICY"
          test "${PRE_PRESENT:-0}" -eq 0
          log permission-removed-owned
        }
        snapshot
        if test "${SCENARIO}" = preexisting; then
          log preexisting-preserved
          exit 0
        fi
        if add_permission; then
          reconcile
          rollback
        else
          log ambiguous-preserved
        fi
        """
    )

    for sid in ("AllowCloudFrontFunctionUrlV2", "AllowCloudFrontFunctionInvokeV2"):
        for scenario in (
            "success",
            "ambiguous-applied",
            "ambiguous-not-applied",
            "preexisting",
            "ambiguous-mismatch",
            "ambiguous-stale-revision",
        ):
            with tempfile.TemporaryDirectory() as directory_name:
                directory = Path(directory_name)
                if scenario == "preexisting":
                    (directory / "policy").write_text(f"reviewed:{sid}")
                log_path = directory / "events.log"
                env = {
                    **os.environ,
                    "SCENARIO": scenario,
                    "SID": sid,
                    "ROOT": str(directory),
                    "LOG": str(log_path),
                }
                result = subprocess.run(
                    ["bash", "-c", harness],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                assert result.returncode == 0, result.stderr
                events = log_path.read_text().splitlines()
                if scenario == "success":
                    assert events == [
                        "snapshot",
                        "permission-owned",
                        "permission-removed-owned",
                    ]
                    assert not (directory / "policy").exists()
                elif scenario == "ambiguous-applied":
                    assert events == ["snapshot", "ambiguous-preserved"]
                    assert (directory / "policy").read_text() == f"reviewed:{sid}"
                elif scenario == "ambiguous-not-applied":
                    assert events == ["snapshot", "ambiguous-preserved"]
                    assert not (directory / "policy").exists()
                elif scenario == "preexisting":
                    assert events == ["snapshot", "preexisting-preserved"]
                    assert (directory / "policy").read_text() == f"reviewed:{sid}"
                else:
                    assert events == ["snapshot", "ambiguous-preserved"]
                    assert (directory / "policy").read_text() in {
                        "foreign",
                        f"reviewed:{sid}",
                    }


def test_development_bootstrap_stale_prelock_snapshot_never_deletes_prior_run_resources():
    harness = dedent(
        r"""
        set -euo pipefail
        : "${ACTION:?}" "${ROOT:?}" "${LOG:?}" "${OWNER:?}"
        LOCK="$ROOT/bootstrap-lock"
        VALUE="$OWNER|2026-09-02T00:00:00Z"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        acquire() {
          if ! (set -o noclobber; printf '%s' "$VALUE" >"$LOCK") 2>/dev/null; then
            log lock-held
            return 77
          fi
          log lock-acquired
        }
        case "$ACTION" in
          run-a)
            acquire
            printf '%s\n' reviewed-url >"$ROOT/url"
            printf '%s\n' reviewed-permissions >"$ROOT/permissions"
            log run-a-created-url-and-permissions
            exit 42
            ;;
          run-b)
            # These are deliberately stale observations made before B can own the lock.
            PRE_URL=0
            PRE_PERMISSIONS=0
            log run-b-prelock-snapshot-absent
            if acquire; then exit 9; fi
            test "$PRE_URL" -eq 0
            test "$PRE_PERMISSIONS" -eq 0
            test "$(<"$ROOT/url")" = reviewed-url
            test "$(<"$ROOT/permissions")" = reviewed-permissions
            log run-b-stopped-before-postlock-mutation
            ;;
          *) exit 2 ;;
        esac
        """
    )
    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        first_log = directory / "run-a.log"
        first = subprocess.run(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "run-a",
                "ROOT": str(directory),
                "LOG": str(first_log),
                "OWNER": "owner-a",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert first.returncode == 42
        second_log = directory / "run-b.log"
        second = subprocess.run(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "run-b",
                "ROOT": str(directory),
                "LOG": str(second_log),
                "OWNER": "owner-b",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert second.returncode == 0, second.stderr
        assert second_log.read_text().splitlines() == [
            "run-b-prelock-snapshot-absent",
            "lock-held",
            "run-b-stopped-before-postlock-mutation",
        ]
        assert (directory / "url").read_text().strip() == "reviewed-url"
        assert (directory / "permissions").read_text().strip() == "reviewed-permissions"


def test_development_bootstrap_mocked_region_lock_and_rollback_guards():
    harness = dedent(
        r"""
        set -euo pipefail
        : "${SCENARIO:?}" "${ROOT:?}" "${LOG:?}"
        REGION=us-east-1
        LOCK_ETAG=owner-etag
        CURRENT_ETAG="$ROOT/lock.etag"
        URL="$ROOT/url"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        region_guard() {
          if test -n "${AWS_REGION:-}" && test -n "${AWS_DEFAULT_REGION:-}" &&
            test "$AWS_REGION" != "$AWS_DEFAULT_REGION"; then
            log region-conflict
            return 1
          fi
          if test -n "${AWS_REGION:-}" && test "$AWS_REGION" != "$REGION"; then
            log region-rejected
            return 1
          fi
          if test -n "${AWS_DEFAULT_REGION:-}" && test "$AWS_DEFAULT_REGION" != "$REGION"; then
            log region-rejected
            return 1
          fi
          export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
        }
        lock_is_current() { test "$(<"$CURRENT_ETAG")" = "$LOCK_ETAG"; }
        validate_function_url() { test "$(<"$URL")" = reviewed-url; }
        rollback_url() {
          lock_is_current || { log lock-lost-preserved; return 1; }
          validate_function_url || { log url-changed-preserved; return 1; }
          rm -- "$URL"
          log url-removed
        }
        rollback_imports() {
          if test "${ROLE_IMPORTED:-0}" -eq 1; then rm -- "$ROOT/role-state"; log role-state-rm; fi
          if test "${POLICY_IMPORTED:-0}" -eq 1; then rm -- "$ROOT/policy-state"; log policy-state-rm; fi
        }
        release_observed() {
          local observed="$1"
          test "$(<"$CURRENT_ETAG")" = "$observed" || { log stale-etag-preserved; return 1; }
          rm -- "$CURRENT_ETAG"
          log lock-released
        }
        printf '%s\n' owner-etag >"$CURRENT_ETAG"
        printf '%s\n' reviewed-url >"$URL"
        case "$SCENARIO" in
          region-conflict) region_guard || true ;;
          lost-lock)
            region_guard
            printf '%s\n' replacement-etag >"$CURRENT_ETAG"
            rollback_url || true
            test -e "$URL"
            ;;
          url-changed)
            region_guard
            printf '%s\n' changed-url >"$URL"
            rollback_url || true
            test -e "$URL"
            ;;
          early-import-verification)
            region_guard
            printf '%s\n' role >"$ROOT/role-state"
            ROLE_IMPORTED=1
            printf '%s\n' wrong-id >"$ROOT/role-verification"
            if test "$(<"$ROOT/role-verification")" = expected-id; then exit 9; fi
            rollback_imports
            test ! -e "$ROOT/role-state"
            test ! -e "$ROOT/policy-state"
            ;;
          stale-etag)
            region_guard
            release_observed old-etag || true
            test -e "$CURRENT_ETAG"
            ;;
          early-post-lock)
            region_guard
            MUTATION_AMBIGUOUS=0
            LOCK_ACQUIRED=1
            bootstrap_cleanup() {
              local status=$?
              trap - EXIT
              if test "$status" -ne 0 && test "$MUTATION_AMBIGUOUS" -eq 0; then
                declare -F rollback_delivery_state >/dev/null && rollback_delivery_state || true
              fi
              log lock-released
              exit "$status"
            }
            trap bootstrap_cleanup EXIT
            exit 1
            ;;
          *) exit 2 ;;
        esac
        """
    )
    scenarios = {
        "region-conflict": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-west-2"},
            ["region-conflict"],
            0,
        ),
        "lost-lock": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["lock-lost-preserved"],
            0,
        ),
        "url-changed": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["url-changed-preserved"],
            0,
        ),
        "early-import-verification": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["role-state-rm"],
            0,
        ),
        "stale-etag": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["stale-etag-preserved"],
            0,
        ),
        "early-post-lock": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["lock-released"],
            1,
        ),
    }
    for scenario, (
        region_environment,
        expected_events,
        expected_returncode,
    ) in scenarios.items():
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            log_path = directory / "events.log"
            environment = {
                **os.environ,
                "SCENARIO": scenario,
                "ROOT": str(directory),
                "LOG": str(log_path),
                **region_environment,
            }
            result = subprocess.run(
                ["bash", "-c", harness],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == expected_returncode, result.stderr
            assert log_path.read_text().splitlines() == expected_events


def test_development_delivery_plan_gate_accepts_only_reviewed_addresses_and_actions():
    assert _run_development_plan_gate({"resource_changes": []})
    assert _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change("managed", "aws_lambda_function.loader", ["update"])
            ]
        }
    )
    assert _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change(
                    "managed", "aws_lambda_function_url.public_chat", ["no-op"]
                )
            ]
        }
    )
    assert _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change(
                    "managed", "aws_cloudfront_function.public_chat_routes", ["update"]
                )
            ]
        }
    )
    for actions in (["create"], ["delete"], ["create", "delete"], ["delete", "create"]):
        assert _run_development_plan_gate(
            {
                "resource_changes": [
                    _synthetic_change(
                        "managed", "aws_api_gateway_deployment.tollchat", list(actions)
                    )
                ]
            }
        )
    assert _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change(
                    "managed", "aws_bedrock_guardrail_version.tollchat", ["create"]
                )
            ]
        }
    )
    for actions in (["update"], ["delete"], ["create", "delete"], ["delete", "create"]):
        assert not _run_development_plan_gate(
            {
                "resource_changes": [
                    _synthetic_change(
                        "managed",
                        "aws_bedrock_guardrail_version.tollchat",
                        list(actions),
                    )
                ]
            }
        )
    assert _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change("data", "data.aws_region.current", ["read"])
            ]
        }
    )

    assert not _run_development_plan_gate({}, raw=False)
    assert not _run_development_plan_gate("not-json", raw=True)
    assert not _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change("managed", "aws_unknown_resource.x", ["update"])
            ]
        }
    )
    for actions in (
        ["read"],
        ["replace"],
        ["update", "delete"],
        ["delete", "update"],
        ["create", "update"],
    ):
        assert not _run_development_plan_gate(
            {
                "resource_changes": [
                    _synthetic_change(
                        "managed", "aws_lambda_function.loader", list(actions)
                    )
                ]
            }
        )
    manual_mutations = (
        "aws_iam_role.loader",
        "aws_iam_role.publisher",
        "aws_iam_role.publisher_scheduler",
        "aws_iam_role.timed_checks",
        "aws_iam_role.tollchat_proxy",
        "aws_iam_role.tollchat_runtime",
        "aws_iam_role.usage_publisher",
        "aws_iam_role.agent_usage_rollup",
        "aws_iam_role_policy.loader",
        "aws_iam_role_policy.publisher",
        "aws_iam_role_policy.publisher_scheduler",
        "aws_iam_role_policy.timed_checks",
        "aws_iam_role_policy.tollchat_proxy",
        "aws_iam_role_policy.tollchat_runtime",
        "aws_iam_role_policy.usage_publisher",
        "aws_iam_role_policy.agent_usage_rollup",
        "aws_iam_role_policy_attachment.loader_vpc",
        "aws_iam_role_policy_attachment.publisher_vpc",
        "aws_iam_role_policy_attachment.tollchat_proxy_vpc",
        "aws_api_gateway_rest_api.tollchat",
        "aws_api_gateway_rest_api_policy.tollchat",
        "aws_api_gateway_resource.tollchat_proxy",
        "aws_api_gateway_method.tollchat_root",
        "aws_api_gateway_method.tollchat_proxy",
        "aws_api_gateway_integration.tollchat_root",
        "aws_api_gateway_integration.tollchat_proxy",
        "aws_api_gateway_stage.tollchat",
        "aws_api_gateway_method_settings.tollchat",
        "aws_athena_named_query.recent_routes",
        "aws_athena_named_query.top_routes",
        "aws_athena_workgroup.agent_reports",
        'aws_bedrockagentcore_resource_policy.tollchat["runtime"]',
        "aws_s3_bucket.agent_measurement",
        "aws_s3_bucket_public_access_block.agent_measurement",
        "aws_s3_bucket_public_access_block.site",
        "aws_s3_bucket_policy.agent_measurement",
        "aws_kms_key.agent_measurement",
        "aws_kms_key.site",
        "aws_kms_alias.agent_measurement",
        "aws_kms_alias.site",
        "aws_s3_bucket_lifecycle_configuration.agent_measurement",
        "aws_s3_bucket_server_side_encryption_configuration.agent_measurement",
        "aws_s3_bucket_policy.site",
        "aws_lambda_function_url.public_chat",
        "aws_lambda_permission.public_chat_url",
        "aws_lambda_permission.public_chat_invoke",
        "aws_sqs_queue.delivery_failure",
        "aws_sqs_queue.invoke_failure",
        "aws_sqs_queue.publisher_delivery_failure",
        "aws_sqs_queue.publisher_invoke_failure",
        "aws_sqs_queue_policy.delivery_failure",
        "aws_lambda_permission.agent_usage_rollup",
        "aws_lambda_permission.eventbridge_invoke",
        "aws_lambda_permission.tollchat_api",
        "aws_lambda_permission.usage_publisher",
        "aws_cloudfront_distribution.site",
        "aws_cloudfront_origin_access_control.site",
        "aws_cloudfront_origin_access_control.public_chat",
        "aws_cloudfront_response_headers_policy.development_noindex",
        "aws_bedrock_guardrail.tollchat",
        "aws_cloudwatch_event_rule.agent_usage_rollup",
        "aws_cloudwatch_event_rule.raw_objects",
        "aws_cloudwatch_event_rule.usage_publisher",
        "aws_cloudwatch_log_metric_filter.load_success",
        "aws_cloudwatch_log_metric_filter.proxy_failure",
        "aws_cloudwatch_metric_alarm.agent_usage_log_coverage",
        "aws_cloudwatch_metric_alarm.agent_usage_rollup_errors",
        "aws_cloudwatch_metric_alarm.agent_usage_rollup_missing",
        "aws_cloudwatch_metric_alarm.failure_queues",
        "aws_cloudwatch_metric_alarm.freshness",
        "aws_cloudwatch_metric_alarm.loader_errors",
        "aws_cloudwatch_metric_alarm.publisher_errors",
        "aws_cloudwatch_metric_alarm.publisher_failure_queues",
        "aws_cloudwatch_metric_alarm.report_generation_freshness",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_errors",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_failures",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_latency",
        "aws_cloudwatch_metric_alarm.tollchat_sessions",
        "aws_cloudwatch_metric_alarm.usage_publisher_errors",
        "aws_cloudwatch_metric_alarm.usage_publisher_failed_invocations",
        "aws_cloudwatch_log_group.agentcore_runtime",
        "aws_wafv2_web_acl.public_chat",
        "aws_wafv2_web_acl_logging_configuration.agent_reports",
        "aws_security_group.loader",
        "aws_security_group.publisher",
        "aws_security_group.tollchat_proxy",
        "aws_security_group.tollchat_runtime",
        "aws_vpc_security_group_egress_rule.loader_to_eventbridge",
        "aws_vpc_security_group_egress_rule.loader_to_rds",
        "aws_vpc_security_group_egress_rule.loader_to_s3",
        "aws_vpc_security_group_egress_rule.proxy_https",
        "aws_vpc_security_group_egress_rule.proxy_to_dynamodb",
        "aws_vpc_security_group_egress_rule.publisher_to_rds",
        "aws_vpc_security_group_egress_rule.publisher_to_s3",
        "aws_vpc_security_group_egress_rule.runtime_https",
        "aws_vpc_security_group_egress_rule.runtime_to_rds",
        "aws_vpc_security_group_ingress_rule.agentcore_from_proxy",
        "aws_vpc_security_group_ingress_rule.rds_from_loader",
        "aws_vpc_security_group_ingress_rule.rds_from_publisher",
        "aws_vpc_security_group_ingress_rule.rds_from_runtime",
    )
    for address in manual_mutations:
        for actions in (
            ["create"],
            ["delete"],
            ["update"],
            ["create", "delete"],
            ["delete", "create"],
        ):
            assert not _run_development_plan_gate(
                {
                    "resource_changes": [
                        _synthetic_change("managed", address, list(actions))
                    ]
                }
            ), (address, actions)
    assert not _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change("data", "data.aws_unknown.current", ["read"])
            ]
        }
    )
    for address in (
        "aws_bedrockagentcore_agent_runtime.tollchat",
        "aws_bedrockagentcore_agent_runtime_endpoint.tollchat",
    ):
        assert _run_development_plan_gate(
            {"resource_changes": [_synthetic_change("managed", address, ["update"])]}
        )
        for actions in (
            ["create"],
            ["delete"],
            ["create", "delete"],
            ["delete", "create"],
        ):
            assert not _run_development_plan_gate(
                {
                    "resource_changes": [
                        _synthetic_change("managed", address, list(actions))
                    ]
                }
            )
    assert not _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change(
                    "managed",
                    "aws_lambda_function.loader",
                    ["update"],
                    account="920534282028",
                )
            ]
        }
    )
    assert not _run_development_plan_gate(
        {
            "resource_changes": [
                _synthetic_change(
                    "managed",
                    "aws_lambda_function.loader",
                    ["update"],
                    environment="production",
                )
            ]
        }
    )
    assert not _run_development_plan_gate(
        {
            "resource_changes": [
                {
                    **_synthetic_change(
                        "managed", "aws_lambda_function.loader", ["no-op"]
                    ),
                    "deposed": "old",
                }
            ]
        }
    )


SLICE_2A_POLICY = (REPO_ROOT / "infra" / "policy.hujson").read_text()


def _slice_2a_policy_sections(source: str) -> tuple[str, str, str]:
    tag_owners = re.search(r'"tagOwners"\s*:\s*\{(.*?)\n\s*\},', source, re.DOTALL)
    auto_approvers = re.search(
        r'"autoApprovers"\s*:\s*\{(.*?)\n\s*\},', source, re.DOTALL
    )
    grants = re.search(r'"grants"\s*:\s*\[(.*?)\n\s*\],', source, re.DOTALL)
    assert tag_owners and auto_approvers and grants
    return tag_owners.group(1), auto_approvers.group(1), grants.group(1)


def _assert_slice_2a_policy(source: str) -> None:
    tag_owners, auto_approvers, grants = _slice_2a_policy_sections(source)
    assert tag_owners.count('"tag:nova-toll-development-router"') == 1
    assert tag_owners.count('"tag:ci-development"') == 1
    assert '"tag:nova-toll-development-router": ["rhprasad0@github"]' in tag_owners
    assert '"tag:ci-development": ["rhprasad0@github"]' in tag_owners
    assert '"tag:nova-toll-router": ["rhprasad0@github"]' in tag_owners
    assert '"tag:ci": ["rhprasad0@github"]' in tag_owners

    assert (
        '"fd7a:115c:a1e0:b1a:0:1:ac1f:0/112": [\n'
        '                "tag:nova-toll-development-router"\n'
        "            ]" in auto_approvers
    )
    assert auto_approvers.count('"fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"') == 1
    assert '"172.31.0.0/16": ["tag:nova-toll-router"]' in auto_approvers
    assert '"exitNode": ["tag:nova-toll-router"]' in source
    assert '"exitNode": ["tag:nova-toll-development-router"]' not in source

    dev_grant = re.search(
        r'\{\s*"src": \["tag:ci-development"\],\s*'
        r'"dst": \["fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"\],\s*'
        r'"ip":  \["tcp:5432"\],\s*\}',
        grants,
        re.DOTALL,
    )
    assert dev_grant is not None
    dev_grant_text = dev_grant.group(0)
    assert "172.31.0.0/16" not in dev_grant_text
    assert "exitNode" not in dev_grant_text
    assert '"src": ["tag:ci"]' in grants
    assert '"dst": ["172.31.0.0/16"]' in grants
    assert '"dst": ["fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"]' in grants
    assert '"ip":  ["tcp:5432"]' in grants
    assert (
        '"nova-toll-rds-development": "fd7a:115c:a1e0:b1a:0:1:ac1f:4a7/128"' in source
    )
    assert '"nova-toll-rds": "172.31.83.200"' in source


def test_slice_2a_policy_is_scoped_and_preserves_production_entries():
    _assert_slice_2a_policy(SLICE_2A_POLICY)
    baseline = subprocess.run(
        ["git", "show", "HEAD:infra/policy.hujson"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for production_entry in (
        '"tag:nova-toll-router": ["rhprasad0@github"]',
        '"tag:ci": ["rhprasad0@github"]',
        '"172.31.0.0/16": ["tag:nova-toll-router"]',
        '"exitNode": ["tag:nova-toll-router"]',
        '"src": ["tag:ci"]',
        '"dst": ["172.31.0.0/16"]',
        '"ip":  ["tcp:5432"]',
    ):
        assert production_entry in baseline
        assert production_entry in SLICE_2A_POLICY
    for original, replacement in (
        (
            '"tag:nova-toll-development-router": ["rhprasad0@github"]',
            '"tag:nova-toll-development-router": ["tag:ci-development"]',
        ),
        (
            '"fd7a:115c:a1e0:b1a:0:1:ac1f:0/112": [\n'
            '                "tag:nova-toll-development-router"\n'
            "            ]",
            '"172.31.0.0/16": ["tag:nova-toll-development-router"]',
        ),
        (
            '"src": ["tag:ci-development"]',
            '"src": ["tag:ci"]',
        ),
    ):
        _must_reject(_assert_slice_2a_policy, SLICE_2A_POLICY, original, replacement)


def _slice_2a_allocation_namespace() -> dict[str, object]:
    match = re.search(
        r"# BEGIN SLICE_2A_TAILSCALE_ALLOCATION_CHECK\n(.*?)\n"
        r"# END SLICE_2A_TAILSCALE_ALLOCATION_CHECK",
        DEPLOYMENT,
        re.DOTALL,
    )
    assert match is not None
    namespace: dict[str, object] = {"__name__": "slice_2a_test"}
    exec(compile(match.group(1), "<slice-2a-allocation-check>", "exec"), namespace)
    return namespace


def _slice_2a_device(
    device_id: str, *, tags: list[str] | None = None
) -> dict[str, object]:
    return {"id": device_id, "tags": ["tag:other"] if tags is None else tags}


def _slice_2a_routes(
    *, advertised: list[str] | None = None, enabled: list[str] | None = None
) -> dict[str, object]:
    return {
        "advertisedRoutes": [] if advertised is None else advertised,
        "enabledRoutes": [] if enabled is None else enabled,
    }


def test_slice_2a_allocation_gate_passes_only_safe_complete_inventories():
    namespace = _slice_2a_allocation_namespace()
    check_allocation = cast(Callable[..., object], namespace["check_allocation"])
    run_check = cast(Callable[..., object], namespace["run_check"])
    intended = _slice_2a_device("dev-router", tags=["tag:nova-toll-development-router"])
    other = _slice_2a_device("other-device")
    devices = {"devices": [intended, other]}
    empty_routes = {
        "dev-router": _slice_2a_routes(),
        "other-device": _slice_2a_routes(advertised=["172.31.0.0/16"]),
    }
    assert check_allocation(devices, empty_routes, "dev-router")
    intended_routes = {
        **empty_routes,
        "dev-router": _slice_2a_routes(
            advertised=["fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"],
            enabled=["fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"],
        ),
    }
    assert check_allocation(devices, intended_routes, "dev-router")
    alternate_site_one_route = "fd7a:115c:a1e0:b1a:0:1:ac1f:800/120"
    alternate_intended_routes = {
        **empty_routes,
        "dev-router": _slice_2a_routes(
            advertised=[alternate_site_one_route],
            enabled=[alternate_site_one_route],
        ),
    }
    assert check_allocation(devices, alternate_intended_routes, "dev-router")
    with pytest.raises(ValueError):
        check_allocation(
            devices,
            alternate_intended_routes,
            "dev-router",
            require_advertised_route=True,
        )

    calls: list[tuple[str, str]] = []
    documents = {
        "/tailnet/rhprasad0.github/devices?fields=all": devices,
        "/device/dev-router/routes": intended_routes["dev-router"],
        "/device/other-device/routes": intended_routes["other-device"],
    }

    def fetch(path: str, token: str) -> object:
        calls.append((path, token))
        return documents[path]

    assert run_check(fetch, "rhprasad0.github", "dev-router", "runtime-token")
    assert [path for path, _ in calls] == list(documents)
    assert all(token == "runtime-token" for _, token in calls)


def test_slice_2a_allocation_gate_rejects_collisions_uncertainty_and_api_failures():
    namespace = _slice_2a_allocation_namespace()
    check_allocation = cast(Callable[..., object], namespace["check_allocation"])
    run_check = cast(Callable[..., object], namespace["run_check"])
    route = "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"
    intended = _slice_2a_device("dev-router", tags=["tag:nova-toll-development-router"])
    other = _slice_2a_device("other-device")
    devices = {"devices": [intended, other]}
    empty = {"dev-router": _slice_2a_routes(), "other-device": _slice_2a_routes()}

    def rejects(
        document: object, routes: object, device_id: str = "dev-router"
    ) -> None:
        with pytest.raises(ValueError):
            check_allocation(document, routes, device_id)

    rejects(
        devices,
        {
            **empty,
            "other-device": _slice_2a_routes(advertised=[route]),
        },
    )
    alternate_site_one_route = "fd7a:115c:a1e0:b1a:0:1:ac1f:800/120"
    rejects(
        devices,
        {
            **empty,
            "other-device": _slice_2a_routes(advertised=[alternate_site_one_route]),
        },
    )
    rejects(
        devices,
        {
            **empty,
            "dev-router": _slice_2a_routes(
                advertised=["fd7a:115c:a1e0:b1a:1:1:ac1f:0/112"]
            ),
        },
    )
    assert check_allocation(
        devices,
        {
            **empty,
            "dev-router": _slice_2a_routes(
                advertised=["fd7a:115c:a1e0:b1a:0:1:ac1f:4a7/128"]
            ),
        },
        "dev-router",
    )
    rejects({"devices": [{"id": "dev-router"}, other]}, empty)
    rejects(
        devices,
        {
            "dev-router": {"advertisedRoutes": [], "enabledRoutes": "bad"},
            "other-device": empty["other-device"],
        },
    )
    rejects({"devices": [{"id": ""}, other]}, empty)
    rejects(
        {"devices": [intended, intended.copy()]}, {"dev-router": _slice_2a_routes()}
    )
    rejects(devices, {"dev-router": _slice_2a_routes(), "unknown": _slice_2a_routes()})
    rejects(devices, empty, "missing-device")
    rejects({"devices": "bad"}, empty)
    rejects(
        devices,
        {
            **empty,
            "dev-router": _slice_2a_routes(advertised=[route, route]),
        },
    )
    rejects(
        devices,
        {
            **empty,
            "dev-router": _slice_2a_routes(
                advertised=["FD7A:115C:A1E0:B1A:0:1:AC1F:0/112"]
            ),
        },
    )

    def api_failure(path: str, token: str) -> object:
        raise RuntimeError("network failure")

    with pytest.raises(RuntimeError):
        run_check(api_failure, "rhprasad0.github", "dev-router", "runtime-token")

    def per_device_failure(path: str, token: str) -> object:
        if path.endswith("devices?fields=all"):
            return devices
        raise RuntimeError("route fetch failure")

    with pytest.raises(RuntimeError):
        run_check(per_device_failure, "rhprasad0.github", "dev-router", "runtime-token")

    api_calls: list[str] = []

    def must_not_query(path: str, token: str) -> object:
        api_calls.append(path)
        raise AssertionError("tailnet validation must precede API query")

    for invalid_tailnet in ("", "other.example"):
        with pytest.raises(ValueError):
            run_check(must_not_query, invalid_tailnet, "dev-router", "runtime-token")
    assert api_calls == []


def test_slice_2a_post_advertisement_check_catches_toctou_and_multi_owner_routes():
    namespace = _slice_2a_allocation_namespace()
    run_check = cast(Callable[..., object], namespace["run_check"])
    route = "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"
    host_route = "fd7a:115c:a1e0:b1a:0:1:ac1f:4a7/128"
    intended = _slice_2a_device("dev-router", tags=["tag:nova-toll-development-router"])
    other = _slice_2a_device("other-device")
    devices = {"devices": [intended, other]}
    empty = {"dev-router": _slice_2a_routes(), "other-device": _slice_2a_routes()}
    current_routes: dict[str, dict[str, object]] = empty

    def fetch(path: str, token: str) -> object:
        if path.endswith("devices?fields=all"):
            return devices
        return current_routes[path.split("/")[-2]]

    # A clean precheck can pass, then become unsafe before advertisement.
    assert run_check(fetch, "rhprasad0.github", "dev-router", "runtime-token")
    current_routes = {
        "dev-router": _slice_2a_routes(),
        "other-device": _slice_2a_routes(advertised=[route]),
    }
    with pytest.raises(ValueError):
        run_check(
            fetch,
            "rhprasad0.github",
            "dev-router",
            "runtime-token",
            post_advertisement=True,
        )

    current_routes = {
        "dev-router": _slice_2a_routes(advertised=[route]),
        "other-device": _slice_2a_routes(advertised=[route]),
    }
    with pytest.raises(ValueError):
        run_check(
            fetch,
            "rhprasad0.github",
            "dev-router",
            "runtime-token",
            post_advertisement=True,
        )

    current_routes = {
        "dev-router": _slice_2a_routes(enabled=[route]),
        "other-device": _slice_2a_routes(),
    }
    with pytest.raises(ValueError):
        run_check(
            fetch,
            "rhprasad0.github",
            "dev-router",
            "runtime-token",
            post_advertisement=True,
        )

    current_routes = {
        "dev-router": _slice_2a_routes(
            advertised=[route, host_route], enabled=[route, host_route]
        ),
        "other-device": _slice_2a_routes(),
    }
    assert run_check(
        fetch,
        "rhprasad0.github",
        "dev-router",
        "runtime-token",
        post_advertisement=True,
        require_host_route=True,
    )

    current_routes = {
        "dev-router": _slice_2a_routes(advertised=[route]),
        "other-device": _slice_2a_routes(advertised=[host_route]),
    }
    with pytest.raises(ValueError):
        run_check(
            fetch,
            "rhprasad0.github",
            "dev-router",
            "runtime-token",
            post_advertisement=True,
            require_host_route=True,
        )


def test_slice_2a_allocation_gate_uses_read_only_authenticated_api_and_no_fallback():
    namespace = _slice_2a_allocation_namespace()
    source = DEPLOYMENT[
        DEPLOYMENT.index(
            "# BEGIN SLICE_2A_TAILSCALE_ALLOCATION_CHECK"
        ) : DEPLOYMENT.index("# END SLICE_2A_TAILSCALE_ALLOCATION_CHECK")
    ]
    assert namespace["EXPECTED_ROUTE"] == "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"
    assert namespace["EXPECTED_TAILNET"] == "rhprasad0.github"
    assert namespace["SITE_ID"] == 1
    assert "/tailnet/" in source and "devices?fields=all" in source
    assert "/routes" in source
    assert '"Authorization": f"Bearer {token}"' in source
    assert 'method="GET"' in source
    assert "ipaddress.ip_network" in source
    assert "translator_identifier" in source
    assert "translator_identifier >> 16" in source
    assert "enabled_owners" in source
    assert "exact site-1 route is not enabled on intended device" in source
    assert "172.31.0.0/16" not in source
    assert 'method="POST"' not in source and 'method="PATCH"' not in source
    assert "tailscale up" not in source
    assert "TAILSCALE_POST_ADVERTISEMENT" in DEPLOYMENT
    assert "TAILSCALE_VERIFY_HOST_ROUTE" in DEPLOYMENT
    assert "TAILSCALE_NO_ADVERTISED_ROUTE" in DEPLOYMENT
    assert "site-1 route remains advertised" in source
    assert "disable the development advertised route immediately" in DEPLOYMENT
    assert "never substitute for it" in DEPLOYMENT


def test_slice_2b_postcheck_requires_exact_tag_and_advertised_plus_enabled_route():
    namespace = _slice_2a_allocation_namespace()
    run_check = cast(Callable[..., object], namespace["run_check"])
    route = "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"
    intended = _slice_2a_device("dev-router", tags=["tag:nova-toll-development-router"])
    other = _slice_2a_device("other-device")
    devices = {"devices": [intended, other]}
    routes = {
        "dev-router": _slice_2a_routes(advertised=[route], enabled=[route]),
        "other-device": _slice_2a_routes(),
    }

    def fetch(path: str, token: str) -> object:
        if path.endswith("devices?fields=all"):
            return devices
        return routes[path.split("/")[-2]]

    assert run_check(
        fetch,
        "rhprasad0.github",
        "dev-router",
        "runtime-token",
        post_advertisement=True,
    )
    for advertised, enabled in (([route], []), ([], [route])):
        routes["dev-router"] = _slice_2a_routes(advertised=advertised, enabled=enabled)
        with pytest.raises(ValueError):
            run_check(
                fetch,
                "rhprasad0.github",
                "dev-router",
                "runtime-token",
                post_advertisement=True,
            )

    routes["dev-router"] = _slice_2a_routes(advertised=[route], enabled=[route])
    devices["devices"][0]["tags"] = ["tag:nova-toll-development-router", "tag:other"]
    with pytest.raises(ValueError):
        run_check(
            fetch,
            "rhprasad0.github",
            "dev-router",
            "runtime-token",
            post_advertisement=True,
        )

    devices["devices"][0]["tags"] = ["tag:nova-toll-development-router"]
    devices["devices"][1]["tags"] = ["tag:nova-toll-development-router"]
    with pytest.raises(ValueError):
        run_check(
            fetch,
            "rhprasad0.github",
            "dev-router",
            "runtime-token",
            post_advertisement=True,
        )

    devices["devices"][1]["tags"] = ["tag:other"]
    routes["dev-router"] = _slice_2a_routes()
    assert run_check(
        fetch,
        "rhprasad0.github",
        "dev-router",
        "runtime-token",
        require_no_advertised_route=True,
    )
    routes["dev-router"] = _slice_2a_routes(advertised=[route])
    with pytest.raises(ValueError):
        run_check(
            fetch,
            "rhprasad0.github",
            "dev-router",
            "runtime-token",
            require_no_advertised_route=True,
        )


def _assert_slice_2b_connectivity_workflow(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    assert _workflow_trigger(workflow) == {"workflow_dispatch": None}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {"verify"}
    job = jobs["verify"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["environment"] == "development"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    steps = cast(list[dict[str, object]], job["steps"])
    assert {
        *re.findall(r"secrets\.([A-Z0-9_]+)", source),
    } == {"TS_DEVELOPMENT_OAUTH_CLIENT_ID", "TS_DEVELOPMENT_OAUTH_SECRET"}
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


def test_slice_2b_connectivity_workflow_is_manual_main_only_and_dev_scoped():
    _assert_slice_2b_connectivity_workflow(DEVELOPMENT_CONNECTIVITY_WORKFLOW)
    for original, replacement in (
        ("workflow_dispatch:", "push:"),
        ("github.ref == 'refs/heads/main'", "github.ref == 'refs/heads/release'"),
        ("environment: development", "environment: production"),
        ("TS_DEVELOPMENT_OAUTH_CLIENT_ID", "TS_OAUTH_CLIENT_ID"),
        ("tag:ci-development", "tag:ci"),
        ("903859731897", "920534282028"),
        ("PGSSLMODE=verify-full", "PGSSLMODE=disable"),
        (
            "PRODUCTION_DB_HOST: nova-toll-db.co9qkm4eqi2h.us-east-1.rds.amazonaws.com",
            "PRODUCTION_DB_HOST: evil.example",
        ),
    ):
        _must_reject(
            _assert_slice_2b_connectivity_workflow,
            DEVELOPMENT_CONNECTIVITY_WORKFLOW,
            original,
            replacement,
        )


def test_slice_2b_production_denial_uses_os_route_and_bounded_socket_failures():
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


def _assert_timed_role_trust_is_environment_conditional(source: str) -> None:
    trust = source.split(
        'data "aws_iam_policy_document" "timed_checks_assume"', maxsplit=1
    )[1].split('resource "aws_iam_role" "timed_checks"', maxsplit=1)[0]
    assert 'variable = "token.actions.githubusercontent.com:aud"' in trust
    assert 'values   = ["sts.amazonaws.com"]' in trust
    assert 'values = var.environment == "development" ? [' in trust
    development_values, production_values = trust.split(
        'values = var.environment == "development" ? [', maxsplit=1
    )[1].split("] : [", maxsplit=1)
    development_subject = "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
    production_subject = (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"
    )
    assert development_values.count(development_subject) == 1
    assert production_subject not in development_values
    assert production_values.count(production_subject) == 1
    assert development_subject not in production_values
    assert "environment:production" not in trust
    assert 'sts:AssumeRole"' not in trust


def test_slice_2b_timed_role_trust_is_environment_conditional_and_adversarial_safe():
    _assert_timed_role_trust_is_environment_conditional(MAIN_TF)
    for original, replacement in (
        ('values = var.environment == "development" ? [', "values = ["),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
        ),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production",
        ),
        ('var.environment == "development"', "true"),
    ):
        _must_reject(
            _assert_timed_role_trust_is_environment_conditional,
            MAIN_TF,
            original,
            replacement,
        )


def test_slice_2b_timed_role_trust_adds_only_the_development_environment_subject():
    trust = MAIN_TF.split(
        'data "aws_iam_policy_document" "timed_checks_assume"', maxsplit=1
    )[1].split('resource "aws_iam_role" "timed_checks"', maxsplit=1)[0]
    assert 'variable = "token.actions.githubusercontent.com:aud"' in trust
    assert 'values   = ["sts.amazonaws.com"]' in trust
    assert 'var.environment == "development"' in trust
    assert (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"
        in trust
    )
    assert (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
        in trust
    )
    assert "environment:production" not in trust
    assert 'sts:AssumeRole"' not in trust


def test_slice_2b_runbook_documents_bounded_secret_route_and_activation_gates():
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


def test_slice_3_development_custom_domain_is_explicit_and_production_preserving():
    assert 'variable "enable_development_custom_domain"' in APPLICATION_VARIABLES
    variable = terraform_block(
        APPLICATION_VARIABLES, 'variable "enable_development_custom_domain"'
    )
    assert "default     = false" in variable
    assert 'environment == "development"' in variable
    assert "enable_development_custom_domain = false" in DEVELOPMENT_TFVARS
    assert "development_custom_domain_enabled" in ENVIRONMENT_TF
    assert "https://${local.domains[0]}" in ENVIRONMENT_TF
    assert "enable_development_custom_domain=false" in DEVELOPMENT_DELIVERY_WORKFLOW

    distribution = terraform_block(
        SITE_TF, 'resource "aws_cloudfront_distribution" "site"'
    )
    assert (
        "aliases             = local.custom_domain_enabled ? local.domains : []"
        in distribution
    )
    assert (
        "cloudfront_default_certificate = !local.custom_domain_enabled" in distribution
    )
    assert (
        'minimum_protocol_version       = local.custom_domain_enabled ? "TLSv1.2_2021" : "TLSv1"'
        in distribution
    )
    assert (
        "local.development_custom_domain_enabled ? aws_acm_certificate.site[0].arn"
        in distribution
    )
    certificate = terraform_block(SITE_TF, 'resource "aws_acm_certificate" "site"')
    assert (
        "count                     = local.custom_domain_enabled ? 1 : 0" in certificate
    )
    assert "domain_name               = local.domains[0]" in certificate
    assert 'validation_method         = "DNS"' in certificate
    assert 'data "cloudflare_zone" "tollchat"' in SITE_TF
    assert "count  = local.is_production ? 1 : 0" in SITE_TF
    assert 'output "development_acm_certificate_arn"' in SITE_TF
    assert 'output "development_acm_validation_records"' in SITE_TF


def test_slice_3_development_delivery_cannot_administer_custom_domain():
    policy = terraform_block(
        FOUNDATION_IAM, 'data "aws_iam_policy_document" "development_delivery"'
    )
    assert "cloudfront:UpdateDistribution" not in policy
    assert "acm:RequestCertificate" not in policy
    assert "acm:DescribeCertificate" not in policy
    assert "cloudflare" not in policy.lower()


def test_slice_3_foundation_dns_role_has_exact_oidc_and_ssm_boundary():
    trust = terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "production_foundation_dns_assume"',
    )
    assert 'actions = ["sts:AssumeRoleWithWebIdentity"]' in trust
    assert 'variable = "token.actions.githubusercontent.com:aud"' in trust
    assert 'values   = ["sts.amazonaws.com"]' in trust
    assert (
        'values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production-foundation-dns"]'
        in trust
    )
    assert 'sts:AssumeRole"' not in trust

    policy = terraform_block(
        FOUNDATION_IAM, 'data "aws_iam_policy_document" "production_foundation_dns"'
    )
    assert 'count = var.environment == "production" ? 1 : 0' in policy
    assert (
        len(_parsed_policy_document(FOUNDATION_IAM, "production_foundation_dns")) == 1
    )
    assert 'actions   = ["ssm:GetParameter"]' in policy
    assert "resources = [local.production_foundation_dns_parameter_arn]" in policy
    assert (
        "arn:aws:ssm:us-east-1:920534282028:parameter/nova-toll/cloudflare-development-dns-api-token"
        in FOUNDATION_IAM
    )
    assert 'resource "aws_iam_role" "production_foundation_dns"' in FOUNDATION_IAM
    role = terraform_block(
        FOUNDATION_IAM, 'resource "aws_iam_role" "production_foundation_dns"'
    )
    assert 'count                = var.environment == "production" ? 1 : 0' in role
    assert (
        'name                 = "nova-toll-production-foundation-dns"' in FOUNDATION_IAM
    )
    assert "kms:Decrypt" not in policy
    assert "secretsmanager:" not in policy


def test_slice_3_dns_workflow_is_manual_protected_and_secret_safe():
    workflow = cast(dict[str, object], yaml.safe_load(FOUNDATION_DNS_WORKFLOW))
    assert "workflow_dispatch:" in FOUNDATION_DNS_WORKFLOW
    assert "push:" not in FOUNDATION_DNS_WORKFLOW
    assert "pull_request" not in FOUNDATION_DNS_WORKFLOW
    assert "refs/heads/main" in FOUNDATION_DNS_WORKFLOW
    assert (
        "github.repository == 'rhprasad0/nova-toll-budget-agent'"
        in FOUNDATION_DNS_WORKFLOW
    )
    assert "environment: production-foundation-dns" in FOUNDATION_DNS_WORKFLOW
    assert (
        "role-to-assume: arn:aws:iam::920534282028:role/nova-toll-production-foundation-dns"
        in FOUNDATION_DNS_WORKFLOW
    )
    assert "id-token: write" in FOUNDATION_DNS_WORKFLOW
    assert "contents: read" in FOUNDATION_DNS_WORKFLOW
    assert "--with-decryption" in FOUNDATION_DNS_WORKFLOW
    assert "/nova-toll/cloudflare-development-dns-api-token" in FOUNDATION_DNS_WORKFLOW
    assert "accounts/{account_id}/tokens/verify" in FOUNDATION_DNS_WORKFLOW
    assert "tokens/verify" in FOUNDATION_DNS_WORKFLOW
    assert 'EXPECTED_ZONE = "tollchat.ai"' in FOUNDATION_DNS_WORKFLOW
    assert 'EXPECTED_DEV_NAME = "dev.tollchat.ai"' in FOUNDATION_DNS_WORKFLOW
    assert 'EXPECTED_DISTRIBUTION = "E33DVF3KT7BTAC"' in FOUNDATION_DNS_WORKFLOW
    assert (
        'EXPECTED_CLOUDFRONT_HOSTNAME = "d1wqry4fbd92w5.cloudfront.net"'
        in FOUNDATION_DNS_WORKFLOW
    )
    assert (
        'EXPECTED_LEGACY_TARGET = "dmsiz11apblcv.cloudfront.net"'
        in FOUNDATION_DNS_WORKFLOW
    )
    assert '"stage-validation", "cutover", "rollback"' in FOUNDATION_DNS_WORKFLOW
    assert '"POST"' in FOUNDATION_DNS_WORKFLOW and '"PUT"' in FOUNDATION_DNS_WORKFLOW
    assert "DELETE" not in FOUNDATION_DNS_WORKFLOW
    assert "GITHUB_STEP_SUMMARY" not in FOUNDATION_DNS_WORKFLOW
    assert "upload-artifact" not in FOUNDATION_DNS_WORKFLOW
    assert "secrets." not in FOUNDATION_DNS_WORKFLOW
    assert "Authorization" in FOUNDATION_DNS_WORKFLOW
    assert "set +x" in FOUNDATION_DNS_WORKFLOW
    assert workflow
    for action in re.findall(r"uses:\s*([^\s#]+)", FOUNDATION_DNS_WORKFLOW):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action)


def test_slice_3_dns_allowlist_contract_covers_adversarial_records_and_order():
    for required in (
        "result_info",
        "total_count != count",
        "total_pages != 1",
        'zone.get("name") != EXPECTED_ZONE',
        'zone.get("status") != "active"',
        "returned_account != account_id",
        'status") != "active"',
        "len(dev_records) != 1",
        "len(found) > 1",
        "EXPECTED_VALIDATION_TTL = 60",
        "EXPECTED_DEV_TTL = 1",
        'proxied"] is not False',
        "\\.dev\\.tollchat\\.ai",
        "acm-validations\\.aws",
        'CERTIFICATE_STATUS") != "ISSUED"',
        'CLOUDFRONT_STATUS") != "Deployed"',
        'ALIAS_ATTACHED") != "true"',
        'method not in {"POST", "PUT"}',
        "ROLLBACK_SNAPSHOT",
        'old_snapshot["id"]',
        "cloudflare DNS gate failed closed",
        "rollback_legacy_https_health",
        "--proto '=https' --tlsv1.2",
        "https://dmsiz11apblcv.cloudfront.net/",
    ):
        assert required in FOUNDATION_DNS_WORKFLOW
    assert FOUNDATION_DNS_WORKFLOW.index(
        '"stage-validation"'
    ) < FOUNDATION_DNS_WORKFLOW.index('"cutover"')
    assert FOUNDATION_DNS_WORKFLOW.index(
        '"CERTIFICATE_STATUS"'
    ) < FOUNDATION_DNS_WORKFLOW.index('mutate(zone_id, account_id, "PUT"')


def _slice3_dns_python_source() -> str:
    embedded = FOUNDATION_DNS_WORKFLOW.split(
        "CLOUDFLARE_TOKEN=\"$TOKEN\" python3 - <<'PY'\n", maxsplit=1
    )[1].split("\n          PY", maxsplit=1)[0]
    source = dedent(embedded)
    assert "\ntry:\n    main()\n" in source
    return source.split("\ntry:\n    main()\n", maxsplit=1)[0] + "\n"


def _dns_zone(zone_id: str = "a" * 32, account_id: str = "b" * 32) -> dict[str, object]:
    return {
        "id": zone_id,
        "name": "tollchat.ai",
        "status": "active",
        "account": {"id": account_id},
    }


def _dns_record(
    record_id: str,
    record_name: str,
    content: str,
    *,
    ttl: int = 1,
    proxied: bool = False,
) -> dict[str, object]:
    return {
        "id": record_id,
        "zone_id": "a" * 32,
        "name": record_name,
        "type": "CNAME",
        "content": content,
        "ttl": ttl,
        "proxied": proxied,
    }


class _DnsApiMock:
    def __init__(
        self,
        *,
        zones: list[dict[str, object]],
        token_account: str = "b" * 32,
        dev_records: list[dict[str, object]] | None = None,
        validation_records: list[dict[str, object]] | None = None,
    ) -> None:
        validation: list[dict[str, object]] = validation_records or [
            _dns_record(
                "d" * 32,
                "_validation.dev.tollchat.ai",
                "_token.acm-validations.aws",
                ttl=60,
            )
        ]
        self.zones = zones
        self.token_account = token_account
        self.records: dict[str, list[dict[str, object]]] = {
            cast(str, record["name"]): [record] for record in validation
        }
        self.records["dev.tollchat.ai"] = dev_records or [
            _dns_record(
                "c" * 32,
                "dev.tollchat.ai",
                "dmsiz11apblcv.cloudfront.net",
            )
        ]
        self.calls: list[
            tuple[str, str, dict[str, str] | None, dict[str, object] | None]
        ] = []

    @property
    def mutations(self) -> list[tuple[str, str, dict[str, object] | None]]:
        return [
            (method, path, payload)
            for method, path, _, payload in self.calls
            if method in {"POST", "PUT"}
        ]

    @staticmethod
    def _page(result: list[dict[str, object]]) -> dict[str, object]:
        return {
            "success": True,
            "result": result,
            "result_info": {
                "page": 1,
                "count": len(result),
                "per_page": max(1, len(result)),
                "total_count": len(result),
                "total_pages": 1,
            },
        }

    def __call__(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append((method, path, query, payload))
        if method == "GET" and path == "zones":
            return self._page(self.zones)
        if method == "GET" and path.endswith("/tokens/verify"):
            return {
                "success": True,
                "result": {"status": "active", "account_id": self.token_account},
            }
        if method == "GET" and path.endswith("/dns_records"):
            record_name = (query or {}).get("name", "")
            return self._page(self.records.get(record_name, []))
        if method == "POST" and path.endswith("/dns_records") and payload is not None:
            record = {**payload, "id": "e" * 32, "zone_id": "a" * 32}
            self.records.setdefault(str(record["name"]), []).append(record)
            return {"success": True, "result": record}
        if method == "PUT" and "/dns_records/" in path and payload is not None:
            record_id = path.rsplit("/", maxsplit=1)[1]
            for record_name, records in self.records.items():
                for index, record in enumerate(records):
                    if record["id"] == record_id:
                        updated = {**payload, "id": record_id, "zone_id": "a" * 32}
                        records[index] = updated
                        if updated["name"] != record_name:
                            del records[index]
                            self.records.setdefault(str(updated["name"]), []).append(
                                updated
                            )
                        return {"success": True, "result": updated}
        raise AssertionError(f"unexpected mock call: {method} {path}")


def _set_dns_inputs(
    monkeypatch: pytest.MonkeyPatch, *, operation: str = "stage-validation"
) -> None:
    monkeypatch.setenv("OPERATION", operation)
    monkeypatch.setenv(
        "ACM_CERTIFICATE_ARN",
        "arn:aws:acm:us-east-1:903859731897:certificate/" + "0" * 36,
    )
    monkeypatch.setenv(
        "VALIDATION_RECORDS",
        json.dumps(
            [
                {
                    "name": "_validation.dev.tollchat.ai",
                    "type": "CNAME",
                    "value": "_token.acm-validations.aws",
                    "ttl": 60,
                    "proxied": False,
                }
            ]
        ),
    )
    monkeypatch.setenv("DISTRIBUTION_ID", "E33DVF3KT7BTAC")
    monkeypatch.setenv("CLOUDFRONT_HOSTNAME", "d1wqry4fbd92w5.cloudfront.net")
    monkeypatch.setenv("CERTIFICATE_STATUS", "ISSUED")
    monkeypatch.setenv("CLOUDFRONT_STATUS", "Deployed")
    monkeypatch.setenv("ALIAS_ATTACHED", "true")
    monkeypatch.setenv("OLD_DEV_TARGET", "dmsiz11apblcv.cloudfront.net")
    monkeypatch.setenv(
        "ROLLBACK_SNAPSHOT",
        json.dumps(
            {
                "id": "c" * 32,
                "name": "dev.tollchat.ai",
                "type": "CNAME",
                "content": "dmsiz11apblcv.cloudfront.net",
                "ttl": 1,
                "proxied": False,
            }
        ),
    )


def _dns_namespace(mock: _DnsApiMock) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(_slice3_dns_python_source(), namespace)
    namespace["TOKEN"] = "fixture-token"
    namespace["api"] = mock
    return namespace


def test_slice3_dns_gate_rejects_adversarial_inputs_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zone = _dns_zone()
    cases: list[tuple[str, dict[str, str], _DnsApiMock]] = []
    for zones in ([], [zone, _dns_zone("f" * 32, "b" * 32)]):
        cases.append(("zone cardinality", {}, _DnsApiMock(zones=zones)))

    cases.append(
        ("wrong token account", {}, _DnsApiMock(zones=[zone], token_account="f" * 32))
    )

    cases.append(
        (
            "malformed validation record",
            {
                "VALIDATION_RECORDS": json.dumps(
                    [
                        {
                            "name": "_validation.dev.tollchat.ai",
                            "type": "A",
                            "value": "bad",
                            "ttl": 60,
                            "proxied": False,
                        }
                    ]
                )
            },
            _DnsApiMock(zones=[zone]),
        )
    )

    cases.append(
        (
            "unrelated CloudFront host",
            {"CLOUDFRONT_HOSTNAME": "dattacker.cloudfront.net"},
            _DnsApiMock(zones=[zone]),
        )
    )

    cases.append(
        (
            "unreviewed rollback target",
            {"OLD_DEV_TARGET": "dother.cloudfront.net"},
            _DnsApiMock(zones=[zone]),
        )
    )

    cases.append(
        (
            "stale snapshot",
            {},
            _DnsApiMock(
                zones=[zone],
                dev_records=[
                    _dns_record(
                        "f" * 32, "dev.tollchat.ai", "dmsiz11apblcv.cloudfront.net"
                    )
                ],
            ),
        )
    )

    for label, overrides, mock in cases:
        _set_dns_inputs(monkeypatch)
        for key, value in overrides.items():
            monkeypatch.setenv(key, value)
        namespace = _dns_namespace(mock)
        gate_error = cast(type[Exception], namespace["GateError"])
        main = cast(Callable[[], object], namespace["main"])
        with pytest.raises(gate_error):
            main()
        assert not mock.mutations, label


def test_slice3_dns_gate_rollback_puts_only_the_captured_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dns_inputs(monkeypatch, operation="rollback")
    mock = _DnsApiMock(
        zones=[_dns_zone()],
        dev_records=[
            _dns_record("c" * 32, "dev.tollchat.ai", "d1wqry4fbd92w5.cloudfront.net")
        ],
    )
    namespace = _dns_namespace(mock)
    cast(Callable[[], object], namespace["main"])()
    assert len(mock.mutations) == 1
    method, path, payload = mock.mutations[0]
    assert method == "PUT"
    assert path.endswith("/dns_records/" + "c" * 32)
    assert payload is not None
    assert payload["content"] == "dmsiz11apblcv.cloudfront.net"
    assert (
        mock.records["dev.tollchat.ai"][0]["content"] == "dmsiz11apblcv.cloudfront.net"
    )


def test_slice3_rollback_legacy_https_health_fails_closed(
    tmp_path: Path,
) -> None:
    function = re.search(
        r"(?ms)^          rollback_legacy_https_health\(\) \{\n(.*?)^          \}\n          if test",
        FOUNDATION_DNS_WORKFLOW,
    )
    assert function is not None
    shell_function = dedent(
        "rollback_legacy_https_health() {\n" + function.group(1) + "}\n"
    )
    for status, expected in (("200", 0), ("500", 1)):
        script = dedent(
            f"""
            set -euo pipefail
            RUNNER_TEMP={tmp_path}
            FAKE_CURL_STATUS={status}
            curl() {{
              if test "$FAKE_CURL_STATUS" = "200"; then
                printf '200'
                return 0
              fi
              printf '500'
              return 22
            }}
            {shell_function}
            rollback_legacy_https_health
            """
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=False
        )
        assert result.returncode == expected, result.stderr


def test_slice_3_runbook_and_plan_document_the_staged_order_and_rollback():
    for required in (
        "Slice 3 development custom-domain and DNS handoff",
        "enable_development_custom_domain",
        "production-foundation-dns",
        "GET /accounts/{derived_account_id}/tokens/verify",
        "stage-validation",
        "certificate_status=ISSUED",
        "cloudfront_status=Deployed",
        "alias_attached=true",
        "dmsiz11apblcv.cloudfront.net",
        "E1JXKQYNAN39E4",
        "X-Robots-Tag: noindex",
        "operation=rollback",
        "captured snapshot",
        "#333 cleanup",
    ):
        assert required in DEPLOYMENT
    for required in (
        "Slice 3 custom-domain handoff",
        "enable_development_custom_domain",
        "production-foundation-dns",
        "account-owned token",
        "captured `dev.tollchat.ai` CNAME",
        "Rollback restores that captured record by ID",
        "No certificate, CloudFront alias, or DNS write",
    ):
        assert (
            required
            in (V2_ROOT / "plans" / "ENVIRONMENT-AND-RELEASE-PLAN.md").read_text()
        )

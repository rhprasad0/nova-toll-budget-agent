import ast
import base64
import difflib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

import pytest
import yaml

V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
MAIN_TF = (V2_ROOT / "infra" / "main.tf").read_text()
TIMED_CHECKS_TF = (V2_ROOT / "infra" / "timed_checks.tf").read_text()
PUBLISHER_HANDLER = (V2_ROOT / "lambdas" / "publisher" / "handler.py").read_text()
ENVIRONMENT_TF = (V2_ROOT / "infra" / "environment.tf").read_text()
SITE_TF = (V2_ROOT / "infra" / "site.tf").read_text()
DEVELOPMENT_TFVARS = (V2_ROOT / "infra" / "development.tfvars").read_text()
CI_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
TERRAFORM_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "terraform.yml").read_text()
PRODUCTION_PLAN_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-production-plan.yml"
).read_text()
TIMED_CHECKS_MODULE = (V2_ROOT / "timed_checks.py").read_text()
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
FOUNDATION_FIELDS = (
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
DEVELOPMENT_DELIVERY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-delivery.yml"
).read_text()
DEVELOPMENT_PLAN_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-plan.yml"
).read_text()
DEVELOPMENT_CONNECTIVITY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-connectivity-verification.yml"
).read_text()
DEVELOPMENT_MIGRATIONS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-migrations.yml"
).read_text()
DEVELOPMENT_MIGRATION_HELPER = (
    V2_ROOT / "scripts" / "run_development_migrations_workflow.sh"
).read_text()
DEVELOPMENT_FOUNDATION_PLAN_VALIDATOR = (
    V2_ROOT / "scripts" / "validate_development_foundation_plan.py"
)
FOUNDATION_DNS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-production-foundation-dns.yml"
).read_text()
RUNBOOK = (V2_ROOT / "RUNBOOK.md").read_text()
RUNBOOKS = V2_ROOT / "runbooks"
DEVELOPMENT_BOOTSTRAP = (RUNBOOKS / "development-bootstrap-import.md").read_text()
DEVELOPMENT_RELEASE = (RUNBOOKS / "development-release.md").read_text()
DEVELOPMENT_FOUNDATION_330 = (
    RUNBOOKS / "development-foundation-330-archive.md"
).read_text()
DEVELOPMENT_FOUNDATION_REPLACEMENT = (
    RUNBOOKS / "development-foundation-replacement.md"
).read_text()
LEGACY_DEVELOPMENT_RETIREMENT = (
    RUNBOOKS / "legacy-development-retirement.md"
).read_text()

# Preserve the original logical ordering for whole-runbook contract assertions.
_BEFORE_HANDOFF, _AFTER_HANDOFF = RUNBOOK.split(
    "### Development handoff (non-operative)", maxsplit=1
)
_NON_OPERATIVE, _PRODUCTION = _AFTER_HANDOFF.split(
    "### Guarded production release", maxsplit=1
)
DEPLOYMENT = "\n".join(
    (
        _BEFORE_HANDOFF,
        DEVELOPMENT_BOOTSTRAP,
        DEVELOPMENT_RELEASE,
        "### Development handoff (non-operative)",
        _NON_OPERATIVE,
        DEVELOPMENT_FOUNDATION_330,
        DEVELOPMENT_FOUNDATION_REPLACEMENT,
        "### Guarded production release",
        _PRODUCTION,
        LEGACY_DEVELOPMENT_RETIREMENT,
    )
)
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


def _hcl_expression(source: str, name: str) -> str:
    """Return an HCL attribute expression, including nested delimiters."""
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*", source)
    if not match:
        return ""
    start = match.end()
    while start < len(source) and source[start].isspace():
        start += 1
    opening = source[start] if start < len(source) else ""
    if opening not in "[({" and re.match(r"[A-Za-z_][\w.]*\(", source[start:]):
        function_opening = source.find("(", start)
        opening = "("
        expression_start = start
        start = function_opening
    else:
        expression_start = start
    if opening not in "[({":
        return source[start:].splitlines()[0].strip()
    closing = {"[": "]", "(": ")", "{": "}"}[opening]
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
                return source[expression_start : index + 1].strip()
    raise AssertionError(f"unclosed HCL expression {name!r}")


def _hcl_expression_tokens(expression: str) -> list[str]:
    expression = expression.strip()
    if expression.startswith("concat("):
        expression = re.sub(r"\s+", " ", expression)
        expression = expression.replace("( ", "(").replace(" )", ")")
        return [re.sub(r",\s*\)$", ")", expression)]
    tokens: list[str] = []
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|[A-Za-z_][\w.:-]*|\*', expression):
        token = match.group(0)
        tokens.append(json.loads(token) if token.startswith('"') else token)
    return tokens


def _parsed_policy_tuple_map(
    source: str, name: str
) -> dict[
    str,
    tuple[
        tuple[str, ...], tuple[str, ...], tuple[tuple[str, str, tuple[str, ...]], ...]
    ],
]:
    document = terraform_block(source, f'data "aws_iam_policy_document" "{name}"')
    result: dict[
        str,
        tuple[
            tuple[str, ...],
            tuple[str, ...],
            tuple[tuple[str, str, tuple[str, ...]], ...],
        ],
    ] = {}
    for statement in _hcl_named_blocks(document, "statement"):
        conditions: list[tuple[str, str, tuple[str, ...]]] = []
        for condition in _hcl_named_blocks(statement, "condition"):
            values = tuple(_hcl_expression_tokens(_hcl_expression(condition, "values")))
            values = tuple(
                "us-east-1" if value == "local.development_delivery_region" else value
                for value in values
            )
            conditions.append(
                (
                    _hcl_scalar(condition, "test"),
                    _hcl_scalar(condition, "variable"),
                    values,
                )
            )
        sid = _hcl_scalar(statement, "sid")
        result[sid] = (
            tuple(_hcl_strings(_hcl_attribute(statement, "actions"))),
            tuple(_hcl_expression_tokens(_hcl_expression(statement, "resources"))),
            tuple(conditions),
        )
    return result


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
    policy_data = (
        policy_data.replace(
            "aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn"
        )
        .replace("aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn")
        .replace("aws_kms_key.alerts.arn", "local.test_alerts_kms_key_arn")
    )
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
          access_key                     = "test"
          secret_key                     = "test"
          skip_credentials_validation   = true
          skip_requesting_account_id    = true
          skip_metadata_api_check       = true
        }}

        locals {{
          test_tfstate_bucket_arn = "arn:aws:s3:::nova-toll-tfstate-903859731897"
          test_tfstate_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/00000000-0000-0000-0000-000000000000"
          test_alerts_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111"
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
        assert not any(key.startswith("AWS_") for key in environment)
        environment["HOME"] = str(root)
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


def _terraform_rendered_development_plan_policies() -> tuple[
    dict[str, dict[str, object]], list[dict[str, object]]
]:
    """Render the development plan policies in a backend-free Terraform root."""
    first_locals = _top_level_terraform_block(FOUNDATION_IAM, "locals", 0)
    policy_data = _top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_plan"',
    )
    plan_locals = next(
        _top_level_terraform_block(FOUNDATION_IAM, "locals", occurrence)
        for occurrence in range(5)
        if "development_plan_policy_documents"
        in _top_level_terraform_block(FOUNDATION_IAM, "locals", occurrence)
    )
    policy_data = (
        policy_data.replace(
            "aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn"
        )
        .replace("aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn")
        .replace("aws_kms_key.alerts.arn", "local.test_alerts_kms_key_arn")
    )
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

        variable "environment" {{
          type    = string
          default = "development"
        }}

        provider "aws" {{
          region                       = "us-east-1"
          access_key                   = "test"
          secret_key                   = "test"
          skip_credentials_validation = true
          skip_requesting_account_id  = true
          skip_metadata_api_check     = true
        }}

        locals {{
          test_tfstate_bucket_arn = "arn:aws:s3:::nova-toll-tfstate-903859731897"
          test_tfstate_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/00000000-0000-0000-0000-000000000000"
          test_alerts_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111"
        }}

        {first_locals}
        {policy_data}
        {plan_locals}

        output "development_plan_policy_documents" {{
          value = local.development_plan_policy_documents
        }}

        output "development_plan_aggregate" {{
          value = data.aws_iam_policy_document.development_plan.json
        }}
        """
    )
    with tempfile.TemporaryDirectory(prefix="nova-toll-iam-plan-render-") as directory:
        root = Path(directory)
        (root / "main.tf").write_text(configuration, encoding="utf-8")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AWS_")
        }
        environment["HOME"] = str(root)
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
        plan_path = root / "development-plan.tfplan"
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
        outputs = json.loads(rendered.stdout)["planned_values"]["outputs"]
        documents = outputs["development_plan_policy_documents"]["value"]
        aggregate = outputs["development_plan_aggregate"]["value"]
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
    assert policy.count('variable = "s3:x-amz-server-side-encryption"') == 1
    assert (
        policy.count('variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"') == 1
    )
    assert policy.count('resources = ["${aws_s3_bucket.tfstate.arn}/plans/*"]') == 3
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
    for source in (foundation_s3, foundation_agentcore, foundation_audit, budget):
        assert "920534282028" not in source
    foundation_terraform = "".join(
        path.read_text() for path in FOUNDATION_ROOT.glob("*.tf")
    )
    assert "cloudflare-development-dns-api-token" in foundation_terraform


def test_foundation_output_and_application_input_are_the_exact_non_secret_boundary():
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


def test_foundation_rds_database_name_tracks_environment_contract():
    rds = (FOUNDATION_ROOT / "rds.tf").read_text()
    instance = terraform_block(rds, 'resource "aws_db_instance" "main"')
    assert _hcl_attribute(instance, "db_name") == (
        'var.environment == "development" ? "nova_toll_development" : "nova_toll"'
    )
    assert _hcl_attribute(instance, "final_snapshot_identifier") == (
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


def test_handoff_and_follow_on_ownership_are_documented_without_persisted_ids():
    runbook = DEPLOYMENT
    plan = (V2_ROOT / "plans" / "ENVIRONMENT-AND-RELEASE-PLAN.md").read_text()
    for text in (
        "guarded\nproduction planner",
        "current foundation output",
        "validates its approved non-secret shape",
        "planner-owned production handoff",
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
    assert "is the operative development release path" in runbook
    assert "runbooks/development-foundation-330-archive.md" in RUNBOOK
    assert "historical audit and recovery context" in RUNBOOK
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
    assert len(create_addresses) == len(set(create_addresses)) == 98
    assert {
        "aws_ssm_document.route_control[0]",
        "aws_iam_role.route_control[0]",
        "aws_iam_role_policy.route_control[0]",
    } <= set(create_addresses)
    assert len(data_addresses) == len(set(data_addresses)) == 8
    assert set(data_addresses) == {
        "data.aws_caller_identity.current",
        "data.aws_region.current",
        "data.aws_vpc.default",
        "data.aws_subnets.default",
        "data.aws_route_tables.default",
        "data.aws_subnet.tailscale_router",
        "data.aws_iam_policy_document.route_control_assume[0]",
        "data.aws_iam_policy_document.route_control[0]",
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
    for mode, address, actions, replacement in (
        (
            "data",
            "data.aws_iam_policy_document.route_control_assume[0]",
            ["read"],
            "data.aws_iam_policy_document.route_control_assume",
        ),
        (
            "data",
            "data.aws_iam_policy_document.route_control[0]",
            ["read"],
            'data.aws_iam_policy_document.route_control["0"]',
        ),
        (
            "managed",
            "aws_ssm_document.route_control[0]",
            ["create"],
            "aws_ssm_document.route_control",
        ),
        (
            "managed",
            "aws_iam_role.route_control[0]",
            ["create"],
            "aws_iam_role.route_control[1]",
        ),
        (
            "managed",
            "aws_iam_role_policy.route_control[0]",
            ["create"],
            'aws_iam_role_policy.route_control["0"]',
        ),
    ):
        changed = [*expected_changes]
        index = next(
            index
            for index, item in enumerate(changed)
            if item["mode"] == mode and item["address"] == address
        )
        changed[index] = change(mode, replacement, actions)
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
    ci_jobs = cast(dict[str, dict[str, object]], yaml.safe_load(CI_WORKFLOW)["jobs"])
    database_setup_uv = [
        step
        for step in cast(list[dict[str, object]], ci_jobs["v2-database"]["steps"])
        if cast(str, step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert database_setup_uv == [
        {
            "uses": "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d",
            "with": {"python-version": "3.13"},
        }
    ]
    for forbidden in (
        "terraform plan",
        "terraform apply",
        "configure-aws-credentials",
        "id-token: write",
    ):
        assert forbidden not in workflow
    for text in (
        "PRs use disposable migration validation only",
        "checks are credential-free",
        "never mutate deployed databases or schemas",
        "protected `development` migration workflow",
        "refs/heads/main",
        "reviewed protected fixed-target",
        "v2-production-migrations.yml",
        "manually authorized production migration",
        "Generic or future manual migrations are not authorized.",
    ):
        assert text in AGENTS
    guarded = RUNBOOK.split("### Guarded production release", maxsplit=1)[1].split(
        "The legacy development inventory", maxsplit=1
    )[0]
    for text in (
        "verified\ndevelopment candidate/bundle",
        "stable published `vX.Y.Z` event",
        "listener has no AWS credentials",
        "one durable claim",
        "before planner OIDC credentials",
        "encrypted,\nversioned, checksummed candidate/state-bound saved plan valid for 24 hours",
        "Reviewer approval of the protected `production` job occurs after that plan is\nsaved",
        "before the reusable job can access environment secrets or credentials",
        "before migration credentials and fixed migration",
        "re-assumes the deploy role",
        "before applying that same plan",
        "exactly one bounded canary",
        "direct, arbitrary, regenerated,\nstale, or caller-selected plan/apply",
        "sanitized",
        "single bounded candidate-bound record",
    ):
        assert text in guarded
    assert "terraform plan" not in guarded
    assert "terraform apply" not in guarded
    handoff = RUNBOOK.split("## Account-local foundation handoff", maxsplit=1)[1].split(
        "Application/database bootstrap", maxsplit=1
    )[0]
    for text in (
        "guarded\nproduction planner",
        "current foundation output",
        "validates its approved non-secret shape",
        "planner-owned production handoff",
    ):
        assert text in handoff
    assert "planned-output" not in handoff
    assert "foundation-plan path" not in handoff

    capture = RUNBOOK.split(
        "Before approving or deploying a production release", maxsplit=1
    )[1].split("Historical `usage.json`", maxsplit=1)[0]
    rollback = RUNBOOK.split(
        "### Production canary failure: human stop and manual routing restore",
        maxsplit=1,
    )[1].split("Deterministic builds", maxsplit=1)[0]
    capture_shells = re.findall(r"```sh\n(.*?)\n```", capture, flags=re.DOTALL)
    restore_shells = re.findall(r"```sh\n(.*?)\n```", rollback, flags=re.DOTALL)
    assert len(capture_shells) == len(restore_shells) == 1
    for shell in [*capture_shells, *restore_shells]:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write(shell)
            script.flush()
            assert (
                subprocess.run(["bash", "-n", script.name], check=False).returncode == 0
            )

    for text in (
        "set -euo pipefail",
        "set +x",
        "umask 077",
        "920534282028",
        "EXPECTED_REGION=us-east-1",
        "tollchat-v2-chat-proxy",
        "nova_toll_v2-W6989LEw44",
        "os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW",
        "stat.S_ISREG(info.st_mode)",
        "stat.S_IMODE(info.st_mode) != 0o600",
        "if os.fstat(fd).st_nlink != 1:",
        "lambda_live_function_version",
        "agentcore_endpoint_live_version",
        "AdditionalVersionWeights",
    ):
        assert text in capture
    for text in (
        "set -euo pipefail",
        "set +x",
        "umask 077",
        "920534282028",
        "EXPECTED_REGION=us-east-1",
        'python3 -I -S - "$RELEASE_EVIDENCE" "$RECOVERY_RECORD_MAX_BYTES"',
        "os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,",
        "info = os.fstat(fd)",
        "stat.S_ISREG(info.st_mode)",
        "stat.S_IMODE(info.st_mode) != 0o600",
        "snapshot = os.read(fd, limit + 1)",
        "snapshot.splitlines(keepends=True)",
        '--revision-id "$LAMBDA_ALIAS_REVISION"',
        '--client-token "$AGENTCORE_RESTORE_TOKEN"',
        "for ((attempt = 1; attempt <= 60; attempt++))",
        "UPDATE_FAILED",
        "human stop",
        "do not roll back automatically",
        "distinct from the\nforward update token",
        "WAF/rate-limit response",
        "HTTP 429",
        "currently configured WAF rate-based quiet/evaluation window",
        "production exactly unchanged",
        "two-session/reset verification",
    ):
        assert text in rollback
    for shell in (capture, rollback):
        assert "CURRENT_STAGE=" in shell
        assert "FAILURE_REPORTED=0" in shell
        assert "status=fail exit=%s reason=unclassified" in shell
        assert ".FunctionName" not in shell
        assert 'if has("RoutingConfig") then' in shell
        assert '($routing | type) != "object" then false' in shell
        assert "AdditionalVersionWeights? // {}" not in shell
        assert (
            'AliasArn == "arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live"'
            in shell
        )
        assert "PRIVATE_SINK" not in shell
        assert "$(mktemp" not in shell
        assert "2>&1 |" in shell
        assert "cmp -s - <(printf '%s\\n' \"$EXPECTED_ACCOUNT\") 2>/dev/null" in shell
        assert 'test "${statuses[1]}" -eq 0' not in shell
        assert 'aws --region "$EXPECTED_REGION"' in shell
        assert "export AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true" in shell
        assert 'test -n "${RELEASE_EVIDENCE-}"' in shell
        assert "${RELEASE_EVIDENCE:?" not in shell
    for stage in (
        "record-path",
        "account-identity",
        "lambda-validate",
        "agentcore-validate",
        "record-write",
    ):
        assert f"CURRENT_STAGE={stage}" in capture
    for stage in (
        "record-snapshot",
        "record-validate",
        "lambda-update",
        "agentcore-token",
        "agentcore-update",
        "agentcore-poll",
        "agentcore-retry",
    ):
        assert f"CURRENT_STAGE={stage}" in rollback
    assert rollback.count('"$RELEASE_EVIDENCE"') == 1
    assert rollback.count('$(<"$RELEASE_EVIDENCE")') == 0
    assert "stat -c " not in rollback
    assert "grep -qx" not in rollback
    assert "sed -n" not in rollback
    assert "^[1-9][0-9]*$" in capture
    assert "^[1-9][0-9]*$" in rollback
    assert "jq -ser" in capture
    assert capture.count("jq -Rser") == 1
    assert "select(length == 1) | .[0]" in capture
    assert '.status == "READY"' in capture
    assert "then .targetVersion == .liveVersion else true end" in capture
    assert 'python3 -I -S - "$RELEASE_EVIDENCE"' in capture
    assert 'if CAPTURE_WRITE_STAGE="$(' in capture
    assert "os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW" in capture
    assert "os.O_DIRECTORY | os.O_NOFOLLOW" in capture
    assert "dir_fd=directory" in capture
    assert "named.st_dev != info.st_dev" in capture
    assert 'chmod 600 "$RELEASE_EVIDENCE"' not in capture
    assert 'test ! -e "$RELEASE_EVIDENCE"' not in capture
    assert "jq -ser" in rollback
    assert rollback.count("jq -Rser") == 2
    assert "jq -se --arg version" in rollback
    assert "explode | all(. >= 32 and (. < 127 or . >= 160))" in rollback
    assert 'python3 -I -S - "$RELEASE_EVIDENCE"' in rollback
    assert "os.O_DIRECTORY | os.O_NOFOLLOW" in rollback
    assert "info.st_uid != os.geteuid()" in rollback
    assert rollback.count("select(length == 1) | .[0]") >= 3
    assert 'AGENTCORE_RESTORE_TOKEN="$(' in rollback
    assert (
        "python3 -I -S -c 'import uuid; print(uuid.uuid4())' 2>/dev/null | jq -Rser"
        in rollback
    )
    assert rollback.index("AGENTCORE_RESTORE_TOKEN") < rollback.index(
        "update_agentcore()"
    )
    assert "AGENTCORE_UPDATE_AMBIGUOUS=1" in rollback
    assert "AGENTCORE_UPDATE_STATUS=$?" in rollback
    assert 'exit "$AGENTCORE_UPDATE_STATUS"' in rollback
    assert "AGENTCORE_RETRY_USED=1" in rollback
    assert (
        'if (( AGENTCORE_RETRY_USED == 1 )); then exit "$AGENTCORE_UPDATE_STATUS"; fi'
        in rollback
    )
    agent_identity = rollback.index('.agentRuntimeArn == "arn:aws:bedrock-agentcore')
    agent_branch = rollback.index('case "$AGENTCORE_STATUS"')
    assert agent_identity < agent_branch
    assert 'test "$AGENTCORE_TARGET_VERSION" = "$AGENTCORE_LIVE_VERSION"' in rollback
    assert (
        'test "$AGENTCORE_TARGET_VERSION" = "$AGENTCORE_ENDPOINT_LIVE_VERSION"'
        in rollback
    )
    assert "check_development_release.py --profile production" not in rollback
    assert "fixed production readiness checker" not in rollback
    assert "300 seconds" not in rollback
    assert "5 minutes" not in rollback
    assert "QUIET_WINDOW" not in rollback
    assert 'sleep "$' not in rollback
    assert rollback.index("lambda get-alias") < rollback.index("lambda update-alias")
    lambda_update = rollback.index("lambda update-alias")
    assert (
        rollback.find(
            'AWS_PROFILE=nova-toll-prod aws --region "$EXPECTED_REGION" lambda get-alias',
            lambda_update,
        )
        > lambda_update
    )
    assert rollback.index("update-agent-runtime-endpoint") < rollback.index(
        "get-agent-runtime-endpoint"
    )
    assert "immediate Lambda alias read-back and finite AgentCore" in rollback
    assert "Terraform-state-bound production checker" in rollback
    fixed_targets = {
        "EXPECTED_ACCOUNT": "920534282028",
        "EXPECTED_REGION": "us-east-1",
        "LAMBDA_FUNCTION": "tollchat-v2-chat-proxy",
        "LAMBDA_ALIAS": "live",
        "AGENTCORE_RUNTIME": "nova_toll_v2-W6989LEw44",
        "AGENTCORE_ENDPOINT": "preview",
    }
    for shell in (capture, rollback):
        for name, value in fixed_targets.items():
            assert re.search(rf"(?m)^\s*{name}={re.escape(value)}$", shell)
            assert not re.search(rf"(?m)^\s*{name}=.*(?:\$|`)", shell)

    readme = (V2_ROOT / "README.md").read_text()
    for text in (
        "verified development bundle",
        "admission\nand claim",
        "saved plan",
        "reviewer approval",
        "Guards fail closed",
        "capture the\nfixed routing targets",
        "human-operated manual\nrestore",
        "never an automatic rollback",
        "sanitized",
    ):
        assert text in readme


def test_manual_routing_restore_documentation_shells_are_bounded(tmp_path: Path):
    capture = RUNBOOK.split(
        "Before approving or deploying a production release", maxsplit=1
    )[1].split("Historical `usage.json`", maxsplit=1)[0]
    rollback = RUNBOOK.split(
        "### Production canary failure: human stop and manual routing restore",
        maxsplit=1,
    )[1].split("Deterministic builds", maxsplit=1)[0]
    capture_shell = re.findall(r"```sh\n(.*?)\n```", capture, flags=re.DOTALL)[0]
    restore_shell = re.findall(r"```sh\n(.*?)\n```", rollback, flags=re.DOTALL)[0]
    binary = tmp_path / "bin"
    state = tmp_path / "state"
    log = tmp_path / "commands.log"
    binary.mkdir()
    state.mkdir()
    aws = binary / "aws"
    aws.write_text(
        dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\\n' "$*" >>"$LOG"
            test "${AWS_IGNORE_CONFIGURED_ENDPOINT_URLS:-}" = true || exit 71
            if [[ "$*" == *"sts get-caller-identity"* ]]; then
              if [[ "${FAIL_ACCOUNT:-}" == 1 ]]; then
                if [[ "${NUL_FAILURE:-}" == 1 ]]; then
                  printf 'RAW\0SENTINEL\n'
                  printf 'RAW\0SENTINEL\n' >&2
                elif [[ "${SENTINEL_FAILURE:-}" == capture ]]; then
                  printf '%s\\n' RAW_PROVIDER_STDOUT
                  printf '%s\\n' RAW_PROVIDER_STDERR >&2
                fi
                exit 17
              fi
              if [[ -n "${MUTATE_RECORD:-}" ]]; then
                printf 'lambda_live_function_version=999\\nagentcore_endpoint_live_version=998\\n' >"$MUTATE_RECORD"
              fi
              printf '%s\\n' 920534282028
            elif [[ "$*" == *"lambda get-alias"* ]]; then
              count_file="$STATE/lambda-get"
              count=0; test -f "$count_file" && count="$(<"$count_file")"
              count=$((count + 1)); printf '%s' "$count" >"$count_file"
              if [[ "${MODE:-}" == restore && "${LAMBDA_MALFORMED_READBACK:-}" == 1 && "$count" -gt 1 ]]; then
                printf '{\\n'
                exit 0
              fi
              version=11; revision=revision-capture
              if [[ "${MODE:-}" == restore ]]; then
                version=9; revision=revision-current
                if (( count > 1 )); then version=7; revision=revision-readback; fi
              fi
              if [[ "${LAMBDA_REVISION_NUL:-}" == 1 ]]; then revision='revision\\u0000'; fi
              routing="${LAMBDA_ROUTING:-}"
              if [[ -z "$routing" ]]; then routing='{"AdditionalVersionWeights":{}}'; fi
              if [[ "$routing" == absent ]]; then
                printf '{"AliasArn":"arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live","Name":"live","FunctionVersion":"%s","RevisionId":"%s"}\\n' "$version" "$revision"
              else
                printf '{"AliasArn":"arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live","Name":"live","FunctionVersion":"%s","RevisionId":"%s","RoutingConfig":%s}\\n' "$version" "$revision" "$routing"
              fi
              duplicate=0
              if [[ "${MULTI_DOCUMENT:-}" == lambda ]] || [[ "${MODE:-}" == restore && "${MULTI_DOCUMENT:-}" == restore-initial && "$count" -eq 1 ]] || [[ "${MODE:-}" == restore && "${MULTI_DOCUMENT:-}" == restore-readback && "$count" -gt 1 ]]; then duplicate=1; fi
              if (( duplicate )); then
                printf '{"AliasArn":"arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live","Name":"live","FunctionVersion":"%s","RevisionId":"%s","RoutingConfig":{"AdditionalVersionWeights":{}}}\\n' "$version" "$revision"
              fi
            elif [[ "$*" == *"lambda update-alias"* ]]; then
              if [[ "${FAIL_LAMBDA:-}" == 1 ]]; then
                if [[ "${SENTINEL_FAILURE:-}" == restore ]]; then
                  printf '%s\\n' RAW_PROVIDER_STDOUT
                  printf '%s\\n' RAW_PROVIDER_STDERR >&2
                fi
                exit 19
              fi
            elif [[ "$*" == *"bedrock-agentcore-control get-agent-runtime-endpoint"* ]]; then
              count_file="$STATE/agent-get"
              count=0; test -f "$count_file" && count="$(<"$count_file")"
              count=$((count + 1)); printf '%s' "$count" >"$count_file"
              version=8
              if [[ "${MODE:-}" == restore && ( "${AGENT_MODE:-}" == unresolved || ( "${AGENT_MODE:-}" == ambiguous && "$count" -eq 1 ) ) ]]; then version=1; fi
              runtime_arn=arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/nova_toll_v2-W6989LEw44
              endpoint_name=preview
              status=READY
              target_version="$version"
              case "${AGENT_BAD:-}" in
                arn) runtime_arn=arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/wrong ;;
                name) endpoint_name=wrong ;;
                target) status=UPDATING; target_version=1 ;;
                transition) status=UPDATING ;;
                mismatch) target_version=9 ;;
              esac
              if [[ "${MODE:-}" == restore && "${MULTI_DOCUMENT:-}" == agent-restore-split ]]; then
                printf '{"agentRuntimeArn":"%s","name":"%s","status":"%s"}\\n' "$runtime_arn" "$endpoint_name" "$status"
                printf '{"liveVersion":"%s","targetVersion":"%s"}\\n' "$version" "$target_version"
              else
                printf '{"agentRuntimeArn":"%s","name":"%s","status":"%s","liveVersion":"%s","targetVersion":"%s"}\\n' "$runtime_arn" "$endpoint_name" "$status" "$version" "$target_version"
              fi
              if [[ "${MULTI_DOCUMENT:-}" == agent ]]; then
                printf '{"agentRuntimeArn":"arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/nova_toll_v2-W6989LEw44","name":"preview","status":"READY","liveVersion":"8","targetVersion":"8"}\\n'
              fi
            elif [[ "$*" == *"bedrock-agentcore-control update-agent-runtime-endpoint"* ]]; then
              count_file="$STATE/agent-update"
              count=0; test -f "$count_file" && count="$(<"$count_file")"
              count=$((count + 1)); printf '%s' "$count" >"$count_file"
              if [[ "${AGENT_MODE:-}" == unresolved || ( "${AGENT_MODE:-}" == ambiguous && "$count" -eq 1 ) ]]; then exit 23; fi
            else
              exit 99
            fi
            """
        ),
        encoding="utf-8",
    )
    python = binary / "python3"
    python.write_text(
        dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            python_is_code=0
            for argument in "$@"; do
              [[ "$argument" == -c ]] && python_is_code=1
            done
            if [[ "${PYTHON_BROKEN_NUL:-}" == stream && "$python_is_code" == 0 ]] || [[ "${PYTHON_BROKEN_NUL:-}" == token && "$python_is_code" == 1 ]]; then
              printf 'RAW\\000PYTHON_SENTINEL\\n'
              exit 43
            fi
            if [[ "$python_is_code" == 1 ]]; then
              printf '%s\\n' 00000000-0000-4000-8000-000000000000
              exit 0
            fi
            if [[ -n "${CAPTURE_REPLACE_AFTER_OPEN:-}${CUSTODY_REPLACE_SOURCE:-}${REPLACE_AFTER_OPEN:-}" ]]; then
              while [[ "${1:-}" == -I || "${1:-}" == -S ]]; do shift; done
              test "${1:-}" = -; shift
              exec "$REAL_PYTHON" -I -S -c '
            import os
            import sys

            capture_source = os.environ.get("CAPTURE_REPLACE_AFTER_OPEN")
            capture_replacement = os.environ.get("CAPTURE_REPLACEMENT")
            capture_moved = os.environ.get("CAPTURE_MOVED_RECORD")
            if capture_source and capture_replacement:
                original_write = os.write
                replaced = False

                def write(fd, data):
                    global replaced
                    if not replaced:
                        replaced = True
                        if capture_moved:
                            os.replace(capture_source, capture_moved)
                        os.replace(capture_replacement, capture_source)
                    return original_write(fd, data)

                os.write = write

            custody_source = os.environ.get("CUSTODY_REPLACE_SOURCE")
            custody_replacement = os.environ.get("CUSTODY_REPLACEMENT")
            if custody_source and custody_replacement:
                original_stat = os.stat
                replaced = False

                def stat(path, *args, **kwargs):
                    global replaced
                    if (
                        not replaced
                        and path == os.path.basename(custody_source)
                        and kwargs.get("dir_fd") is not None
                    ):
                        replaced = True
                        os.replace(custody_replacement, custody_source)
                    return original_stat(path, *args, **kwargs)

                os.stat = stat

            snapshot_source = os.environ.get("REPLACE_AFTER_OPEN")
            snapshot_replacement = os.environ.get("REPLACEMENT")
            if snapshot_source and snapshot_replacement:
                original_read = os.read
                replaced = False

                def read(fd, count):
                    global replaced
                    if not replaced:
                        replaced = True
                        os.replace(snapshot_replacement, snapshot_source)
                    return original_read(fd, count)

                os.read = read

            exec(compile(sys.stdin.read(), "<stdin>", "exec"))
            ' "$@"
            fi
            exec "$REAL_PYTHON" "$@"
            """
        ),
        encoding="utf-8",
    )
    sleep = binary / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
    mktemp = binary / "mktemp"
    mktemp.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' mktemp >>\"$LOG\"\n"
        "printf '%s/victim\\n' \"$TMPDIR\"\n"
    )
    cmp = binary / "cmp"
    cmp.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${COMPARE_FAILURE:-}" == 1 ]]; then\n'
        "  printf '%s\\n' RAW_COMPARATOR_SENTINEL >&2\n"
        "  exit 43\n"
        "fi\n"
        'exec /usr/bin/cmp "$@"\n'
    )
    for command in (aws, python, sleep, mktemp, cmp):
        command.chmod(0o700)

    def run(shell: str, **environment: str) -> subprocess.CompletedProcess[str]:
        environment = dict(environment)
        unset_release_evidence = environment.pop("UNSET_RELEASE_EVIDENCE", "") == "1"
        child_environment = {
            **os.environ,
            "PATH": str(binary) + os.pathsep + os.defpath,
            "LOG": str(log),
            "STATE": str(state),
            "REAL_PYTHON": sys.executable,
            **environment,
        }
        if unset_release_evidence:
            child_environment.pop("RELEASE_EVIDENCE", None)
        return subprocess.run(
            ["bash", "-c", shell],
            env=child_environment,
            text=True,
            capture_output=True,
            check=False,
        )

    record = tmp_path / "recovery-record"
    captured = run(
        capture_shell, MODE="capture", RELEASE_EVIDENCE=str(record), LOG=str(log)
    )
    assert captured.returncode == 0, captured.stderr
    assert record.read_text() == (
        "lambda_live_function_version=11\nagentcore_endpoint_live_version=8\n"
    )
    assert record.stat().st_mode & 0o777 == 0o600

    startup_hook = tmp_path / "startup-hook"
    startup_hook.mkdir()
    startup_sentinel = tmp_path / "startup-hook-ran"
    (startup_hook / "sitecustomize.py").write_text(
        'open(__import__("os").environ["STARTUP_HOOK_SENTINEL"], "w").write("ran")\n'
    )
    isolated_capture_record = tmp_path / "isolated-capture-record"
    isolated_capture = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(isolated_capture_record),
        PYTHONPATH=str(startup_hook),
        STARTUP_HOOK_SENTINEL=str(startup_sentinel),
    )
    assert isolated_capture.returncode == 0, isolated_capture.stderr
    assert not startup_sentinel.exists()
    isolated_record = tmp_path / "isolated-recovery-record"
    isolated_record.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    isolated_record.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    isolated_restore = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(isolated_record),
        PYTHONPATH=str(startup_hook),
        STARTUP_HOOK_SENTINEL=str(startup_sentinel),
    )
    assert isolated_restore.returncode == 0, isolated_restore.stderr
    assert not startup_sentinel.exists()

    for shell, mode in ((capture_shell, "capture"), (restore_shell, "restore")):
        unset_path = run(shell, MODE=mode, UNSET_RELEASE_EVIDENCE="1")
        empty_path = run(shell, MODE=mode, RELEASE_EVIDENCE="")
        for failed in (unset_path, empty_path):
            assert failed.returncode == 1
            assert failed.stdout == ""
            assert failed.stderr == (
                "stage=record-path status=fail exit=1 reason=unclassified\n"
            )

    existing_record = tmp_path / "existing-record"
    existing_record.write_text("do not overwrite", encoding="utf-8")
    existing = run(capture_shell, MODE="capture", RELEASE_EVIDENCE=str(existing_record))
    assert existing.returncode == 1
    assert existing.stdout == ""
    assert (
        existing.stderr == "stage=record-path status=fail exit=1 reason=unclassified\n"
    )
    assert existing_record.read_text(encoding="utf-8") == "do not overwrite"

    unwritable_record = tmp_path / "missing-parent" / "recovery-record"
    unwritable = run(
        capture_shell, MODE="capture", RELEASE_EVIDENCE=str(unwritable_record)
    )
    assert unwritable.returncode == 1
    assert unwritable.stdout == ""
    assert (
        unwritable.stderr
        == "stage=record-write status=fail exit=1 reason=unclassified\n"
    )
    assert not unwritable_record.exists()

    capture_target = tmp_path / "capture-race-record"
    capture_replacement = tmp_path / "capture-race-fifo"
    os.mkfifo(capture_replacement, 0o644)
    capture_replacement.chmod(0o644)
    raced_capture = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(capture_target),
        CAPTURE_REPLACE_AFTER_OPEN=str(capture_target),
        CAPTURE_REPLACEMENT=str(capture_replacement),
    )
    assert raced_capture.returncode == 1
    assert raced_capture.stdout == ""
    assert (
        raced_capture.stderr
        == "stage=record-write status=fail exit=1 reason=unclassified\n"
    )
    assert capture_target.is_fifo()
    assert capture_target.stat().st_mode & 0o777 == 0o644

    planted_capture = tmp_path / "planted-capture-record"
    planted_replacement = tmp_path / "planted-capture-replacement"
    planted_replacement.write_text(
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n"
    )
    planted_replacement.chmod(0o600)
    moved_capture = tmp_path / "moved-capture-record"
    planted = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(planted_capture),
        CAPTURE_REPLACE_AFTER_OPEN=str(planted_capture),
        CAPTURE_REPLACEMENT=str(planted_replacement),
        CAPTURE_MOVED_RECORD=str(moved_capture),
    )
    assert planted.returncode == 1
    assert planted.stdout == ""
    assert planted.stderr == (
        "stage=record-write status=fail exit=1 reason=unclassified\n"
    )
    assert planted_capture.read_text() == (
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n"
    )
    assert moved_capture.read_text() == (
        "lambda_live_function_version=11\nagentcore_endpoint_live_version=8\n"
    )

    for document, stage in (
        ("lambda", "lambda-validate"),
        ("agent", "agentcore-validate"),
    ):
        multi_record = tmp_path / f"multi-{document}-record"
        multi = run(
            capture_shell,
            MODE="capture",
            MULTI_DOCUMENT=document,
            RELEASE_EVIDENCE=str(multi_record),
        )
        assert multi.returncode != 0
        assert multi.stdout == ""
        assert re.fullmatch(
            rf"stage={stage} status=fail exit=[1-9][0-9]* reason=unclassified\n",
            multi.stderr,
        )
        assert not multi_record.exists()

    for invalid_endpoint in ("transition", "mismatch"):
        failed_record = tmp_path / f"capture-{invalid_endpoint}-record"
        failed = run(
            capture_shell,
            MODE="capture",
            AGENT_BAD=invalid_endpoint,
            RELEASE_EVIDENCE=str(failed_record),
        )
        assert failed.returncode != 0
        assert failed.stdout == ""
        assert re.fullmatch(
            r"stage=agentcore-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            failed.stderr,
        )
        assert not failed_record.exists()

    capture_failure = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        RELEASE_EVIDENCE=str(tmp_path / "failed-record"),
    )
    assert capture_failure.returncode == 17
    assert capture_failure.stderr.splitlines() == [
        "stage=account-identity status=fail exit=17 reason=unclassified"
    ]
    broken_capture = run(
        capture_shell,
        MODE="capture",
        PYTHON_BROKEN_NUL="stream",
        RELEASE_EVIDENCE=str(tmp_path / "broken-python-capture-record"),
    )
    assert broken_capture.returncode == 43
    assert broken_capture.stdout == ""
    assert broken_capture.stderr == (
        "stage=record-write status=fail exit=43 reason=unclassified\n"
    )
    assert "RAW" not in broken_capture.stderr
    assert not (tmp_path / "broken-python-capture-record").exists()
    for shell, mode, evidence in (
        (capture_shell, "capture", tmp_path / "comparator-capture-record"),
        (restore_shell, "restore", record),
    ):
        log.write_text("")
        comparator_failure = run(
            shell,
            MODE=mode,
            COMPARE_FAILURE="1",
            RELEASE_EVIDENCE=str(evidence),
        )
        assert comparator_failure.returncode == 43
        assert comparator_failure.stdout == ""
        assert comparator_failure.stderr == (
            "stage=account-identity status=fail exit=43 reason=unclassified\n"
        )
        assert "RAW_COMPARATOR_SENTINEL" not in comparator_failure.stderr
        assert "lambda get-alias" not in log.read_text()
    assert not (tmp_path / "comparator-capture-record").exists()
    sentinel_capture = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        SENTINEL_FAILURE="capture",
        RELEASE_EVIDENCE=str(tmp_path / "sentinel-capture-record"),
    )
    assert sentinel_capture.returncode == 17
    assert sentinel_capture.stdout == ""
    assert sentinel_capture.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )

    nul_capture = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        NUL_FAILURE="1",
        RELEASE_EVIDENCE=str(tmp_path / "nul-capture-record"),
    )
    assert nul_capture.returncode == 17
    assert nul_capture.stdout == ""
    assert nul_capture.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )

    hostile_tmp = tmp_path / "hostile-tmp"
    hostile_tmp.mkdir()
    victim = hostile_tmp / "victim"
    victim.write_text("do not clobber")
    log.write_text("")
    hostile_capture = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        SENTINEL_FAILURE="capture",
        RELEASE_EVIDENCE=str(tmp_path / "hostile-tmp-capture-record"),
        TMPDIR=str(hostile_tmp),
    )
    assert hostile_capture.returncode == 17
    assert hostile_capture.stdout == ""
    assert hostile_capture.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )
    assert victim.read_text() == "do not clobber"
    assert "mktemp" not in log.read_text()

    hostile_restore_record = tmp_path / "hostile-tmp-restore-record"
    hostile_restore_record.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    hostile_restore_record.chmod(0o600)
    nul_restore = run(
        restore_shell,
        MODE="restore",
        FAIL_ACCOUNT="1",
        NUL_FAILURE="1",
        RELEASE_EVIDENCE=str(hostile_restore_record),
        TMPDIR=str(hostile_tmp),
    )
    assert nul_restore.returncode == 17
    assert nul_restore.stdout == ""
    assert nul_restore.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )
    assert victim.read_text() == "do not clobber"

    hostile_restore_record = tmp_path / "hostile-tmp-restore-record"
    hostile_restore_record.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    hostile_restore_record.chmod(0o600)
    log.write_text("")
    hostile_restore = run(
        restore_shell,
        MODE="restore",
        FAIL_LAMBDA="1",
        SENTINEL_FAILURE="restore",
        RELEASE_EVIDENCE=str(hostile_restore_record),
        TMPDIR=str(hostile_tmp),
    )
    assert hostile_restore.returncode == 19
    assert hostile_restore.stdout == ""
    assert hostile_restore.stderr == (
        "stage=lambda-update status=fail exit=19 reason=unclassified\n"
    )
    assert victim.read_text() == "do not clobber"
    assert "mktemp" not in log.read_text()

    routing_failures = (
        "null",
        '"not-an-object"',
        "[]",
        '{"AdditionalVersionWeights":null}',
        '{"AdditionalVersionWeights":[]}',
        '{"AdditionalVersionWeights":{"9":1}}',
    )
    for index, routing in enumerate(routing_failures):
        failed_record = tmp_path / f"bad-routing-capture-{index}"
        failed = run(
            capture_shell,
            MODE="capture",
            LAMBDA_ROUTING=routing,
            RELEASE_EVIDENCE=str(failed_record),
        )
        assert failed.returncode != 0
        assert re.fullmatch(
            r"stage=lambda-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            failed.stderr,
        )
        assert not failed_record.exists()

    def invalid_record(name: str, contents: str | None = None) -> Path:
        path = tmp_path / name
        if contents is None:
            os.mkfifo(path, 0o600)
        else:
            path.write_text(contents)
            path.chmod(0o600)
        return path

    for name, contents in (
        (
            "zero",
            "lambda_live_function_version=0\nagentcore_endpoint_live_version=8\n",
        ),
        ("missing", "lambda_live_function_version=7\n"),
        (
            "malformed",
            "lambda_live_function_version=seven\nagentcore_endpoint_live_version=8\n",
        ),
        (
            "duplicate",
            "lambda_live_function_version=7\nlambda_live_function_version=7\nagentcore_endpoint_live_version=8\n",
        ),
        (
            "extra",
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\nextra=1\n",
        ),
        (
            "oversized",
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
            + "x" * 256,
        ),
        (
            "trailing-blank",
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n\n",
        ),
        ("fifo", None),
    ):
        path = invalid_record(name, contents)
        log.write_text("")
        failed = run(restore_shell, MODE="restore", RELEASE_EVIDENCE=str(path))
        assert failed.returncode != 0
        assert failed.stderr.count("status=fail") == 1
        assert "lambda update-alias" not in log.read_text()

    log.write_text("")
    absent = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(tmp_path / "absent-record"),
    )
    assert absent.returncode != 0
    assert absent.stderr.count("status=fail") == 1
    assert "lambda update-alias" not in log.read_text()

    target = invalid_record(
        "target",
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n",
    )
    link = tmp_path / "record-link"
    link.symlink_to(target)
    log.write_text("")
    linked = run(restore_shell, MODE="restore", RELEASE_EVIDENCE=str(link))
    assert linked.returncode != 0
    assert "lambda update-alias" not in log.read_text()

    log.write_text("")
    broken_snapshot = run(
        restore_shell,
        MODE="restore",
        PYTHON_BROKEN_NUL="stream",
        RELEASE_EVIDENCE=str(target),
    )
    assert broken_snapshot.returncode == 43
    assert broken_snapshot.stdout == ""
    assert broken_snapshot.stderr == (
        "stage=record-snapshot status=fail exit=43 reason=unclassified\n"
    )
    assert "RAW" not in broken_snapshot.stderr
    assert "lambda update-alias" not in log.read_text()

    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    nul_revision = run(
        restore_shell,
        MODE="restore",
        LAMBDA_REVISION_NUL="1",
        RELEASE_EVIDENCE=str(target),
    )
    assert nul_revision.returncode != 0
    assert nul_revision.stdout == ""
    assert re.fullmatch(
        r"stage=lambda-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
        nul_revision.stderr,
    )
    assert "lambda update-alias" not in log.read_text()

    for document, stage, lambda_update_expected in (
        ("restore-initial", "lambda-validate", False),
        ("restore-readback", "lambda-readback-validate", True),
    ):
        target.write_text(
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
        )
        target.chmod(0o600)
        log.write_text("")
        for path in state.iterdir():
            path.unlink()
        malformed_restore = run(
            restore_shell,
            MODE="restore",
            MULTI_DOCUMENT=document,
            RELEASE_EVIDENCE=str(target),
        )
        assert malformed_restore.returncode != 0
        assert malformed_restore.stdout == ""
        assert re.fullmatch(
            rf"stage={stage} status=fail exit=[1-9][0-9]* reason=unclassified\n",
            malformed_restore.stderr,
        )
        commands = log.read_text()
        assert ("lambda update-alias" in commands) is lambda_update_expected
        assert "update-agent-runtime-endpoint" not in commands

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    malformed_readback = run(
        restore_shell,
        MODE="restore",
        LAMBDA_MALFORMED_READBACK="1",
        RELEASE_EVIDENCE=str(target),
    )
    assert malformed_readback.returncode == 5
    assert malformed_readback.stdout == ""
    assert malformed_readback.stderr == (
        "stage=lambda-readback-validate status=fail exit=5 reason=unclassified\n"
    )
    commands = log.read_text()
    assert "lambda update-alias" in commands
    assert "update-agent-runtime-endpoint" not in commands

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    broken_token = run(
        restore_shell,
        MODE="restore",
        PYTHON_BROKEN_NUL="token",
        RELEASE_EVIDENCE=str(target),
    )
    assert broken_token.returncode == 43
    assert broken_token.stdout == ""
    assert broken_token.stderr == (
        "stage=agentcore-token status=fail exit=43 reason=unclassified\n"
    )
    assert "RAW" not in broken_token.stderr
    commands = log.read_text()
    assert "lambda update-alias" in commands
    assert "update-agent-runtime-endpoint" not in commands

    hostile_targets = {
        "EXPECTED_ACCOUNT": "111111111111",
        "EXPECTED_REGION": "eu-west-1",
        "LAMBDA_FUNCTION": "wrong-function",
        "LAMBDA_ALIAS": "wrong-alias",
        "AGENTCORE_RUNTIME": "wrong-runtime",
        "AGENTCORE_ENDPOINT": "wrong-endpoint",
        "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "false",
        "AWS_ENDPOINT_URL": "http://127.0.0.1:9",
        "AWS_ENDPOINT_URL_STS": "http://127.0.0.1:9/sts",
        "AWS_ENDPOINT_URL_LAMBDA": "http://127.0.0.1:9/lambda",
        "AWS_ENDPOINT_URL_BEDROCK_AGENTCORE_CONTROL": "http://127.0.0.1:9/agentcore",
    }
    log.write_text("")
    hostile_capture = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(tmp_path / "hostile-capture-record"),
        **hostile_targets,
    )
    assert hostile_capture.returncode == 0, hostile_capture.stderr
    commands = log.read_text()
    for expected in (
        "--region us-east-1",
        "--function-name tollchat-v2-chat-proxy --name live",
        "--agent-runtime-id nova_toll_v2-W6989LEw44 --endpoint-name preview",
    ):
        assert expected in commands
    assert not any(value in commands for value in hostile_targets.values())

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    hostile_restore = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(target),
        **hostile_targets,
    )
    assert hostile_restore.returncode == 0, hostile_restore.stderr
    commands = log.read_text()
    for expected in (
        "--region us-east-1",
        "--function-name tollchat-v2-chat-proxy --name live",
        "--agent-runtime-id nova_toll_v2-W6989LEw44 --endpoint-name preview",
    ):
        assert expected in commands
    assert not any(value in commands for value in hostile_targets.values())

    for routing in routing_failures:
        target.write_text(
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
        )
        target.chmod(0o600)
        log.write_text("")
        for path in state.iterdir():
            path.unlink()
        failed = run(
            restore_shell,
            MODE="restore",
            LAMBDA_ROUTING=routing,
            RELEASE_EVIDENCE=str(target),
        )
        assert failed.returncode != 0
        assert re.fullmatch(
            r"stage=lambda-readback-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            failed.stderr,
        )
        commands = log.read_text()
        assert "lambda update-alias" in commands
        assert "update-agent-runtime-endpoint" not in commands

    log.write_text("")
    (state / "lambda-get").unlink(missing_ok=True)
    (state / "agent-get").unlink(missing_ok=True)
    snapshot = run(
        restore_shell,
        MODE="restore",
        LAMBDA_ROUTING="absent",
        RELEASE_EVIDENCE=str(target),
        MUTATE_RECORD=str(target),
    )
    assert snapshot.returncode == 0, snapshot.stderr
    assert "function-version 7" in log.read_text()
    assert "lambda_live_function_version=999" in target.read_text()

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    custody_replacement = invalid_record(
        "custody-replacement-record",
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n",
    )
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    custody_replaced = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(target),
        CUSTODY_REPLACE_SOURCE=str(target),
        CUSTODY_REPLACEMENT=str(custody_replacement),
    )
    assert custody_replaced.returncode != 0
    assert custody_replaced.stdout == ""
    assert custody_replaced.stderr == (
        "stage=record-snapshot status=fail exit=1 reason=unclassified\n"
    )
    assert "lambda update-alias" not in log.read_text()

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    replacement = invalid_record(
        "replacement-record",
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n",
    )
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    replaced_path = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(target),
        REPLACE_AFTER_OPEN=str(target),
        REPLACEMENT=str(replacement),
    )
    assert replaced_path.returncode == 0, replaced_path.stderr
    assert "function-version 7" in log.read_text()
    assert "lambda_live_function_version=999" in target.read_text()

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    ambiguous = run(
        restore_shell,
        MODE="restore",
        AGENT_MODE="ambiguous",
        RELEASE_EVIDENCE=str(target),
    )
    assert ambiguous.returncode == 0, ambiguous.stderr
    commands = log.read_text().splitlines()
    updates = [line for line in commands if "update-agent-runtime-endpoint" in line]
    assert len(updates) == 2 and updates[0] == updates[1]
    assert "--client-token 00000000-0000-4000-8000-000000000000" in updates[0]
    update_positions = [
        index
        for index, command in enumerate(commands)
        if "update-agent-runtime-endpoint" in command
    ]
    endpoint_position = next(
        index
        for index, command in enumerate(commands)
        if "get-agent-runtime-endpoint" in command
    )
    assert update_positions[0] < endpoint_position < update_positions[1]

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    unresolved = run(
        restore_shell,
        MODE="restore",
        AGENT_MODE="unresolved",
        RELEASE_EVIDENCE=str(target),
    )
    assert unresolved.returncode == 23
    assert unresolved.stdout == ""
    assert unresolved.stderr == (
        "stage=agentcore-validate status=fail exit=23 reason=unclassified\n"
    )
    commands = log.read_text().splitlines()
    updates = [line for line in commands if "update-agent-runtime-endpoint" in line]
    reads = [
        index
        for index, command in enumerate(commands)
        if "get-agent-runtime-endpoint" in command
    ]
    update_positions = [
        index
        for index, command in enumerate(commands)
        if "update-agent-runtime-endpoint" in command
    ]
    assert len(updates) == 2 and updates[0] == updates[1]
    assert update_positions[0] < reads[0] < update_positions[1] < reads[1]

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    split_readback = run(
        restore_shell,
        MODE="restore",
        AGENT_MODE="ambiguous",
        MULTI_DOCUMENT="agent-restore-split",
        RELEASE_EVIDENCE=str(target),
    )
    assert split_readback.returncode == 23
    assert split_readback.stdout == ""
    assert split_readback.stderr == (
        "stage=agentcore-validate status=fail exit=23 reason=unclassified\n"
    )
    commands = log.read_text().splitlines()
    assert sum("update-agent-runtime-endpoint" in command for command in commands) == 1
    assert any("get-agent-runtime-endpoint" in command for command in commands)

    for bad_response in ("arn", "name", "target"):
        target.write_text(
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
        )
        target.chmod(0o600)
        log.write_text("")
        for path in state.iterdir():
            path.unlink()
        rejected = run(
            restore_shell,
            MODE="restore",
            AGENT_MODE="ambiguous",
            AGENT_BAD=bad_response,
            RELEASE_EVIDENCE=str(target),
        )
        assert rejected.returncode != 0
        assert re.fullmatch(
            r"stage=agentcore-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            rejected.stderr,
        )
        commands = log.read_text().splitlines()
        assert (
            sum("update-agent-runtime-endpoint" in command for command in commands) == 1
        )
        assert any("get-agent-runtime-endpoint" in command for command in commands)

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    lambda_failure = run(
        restore_shell,
        MODE="restore",
        FAIL_LAMBDA="1",
        SENTINEL_FAILURE="restore",
        RELEASE_EVIDENCE=str(target),
    )
    assert lambda_failure.returncode == 19
    assert lambda_failure.stdout == ""
    assert lambda_failure.stderr.splitlines() == [
        "stage=lambda-update status=fail exit=19 reason=unclassified"
    ]


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
    trusted_planner = (
        "rhprasad0/nova-toll-budget-agent/.github/workflows/"
        "v2-development-plan.yml@main"
    )

    def assert_safe_permissions(permissions: object, *, allow_id_token: bool) -> None:
        if isinstance(permissions, str):
            assert permissions != "write-all"
        elif isinstance(permissions, dict):
            permissions = cast(dict[str, object], permissions)
            if not allow_id_token:
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
        assert_safe_permissions(document.get("permissions"), allow_id_token=False)
        jobs = document.get("jobs")
        if isinstance(jobs, dict):
            for job in cast(dict[str, object], jobs).values():
                if isinstance(job, dict):
                    job = cast(dict[str, object], job)
                    assert_safe_permissions(
                        job.get("permissions"),
                        allow_id_token=job.get("uses") == trusted_planner,
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
    assert '"dynamodb:TransactWriteItems"' not in endpoint


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


def test_agent_measurement_retains_historical_metadata_without_active_sink():
    measurement_path = V2_ROOT / "infra" / "agent_measurement.tf"
    assert measurement_path.exists()
    measurement = measurement_path.read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    assert 'name     = "agent-report-bot-control"' not in site
    assert 'name     = "agent-route-report"' not in site
    assert 'name     = "allow-static-site"' in site
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
    assert 'encryption_option = "SSE_KMS"' in measurement
    assert (
        'resource "aws_wafv2_web_acl_logging_configuration" "agent_reports"'
        not in measurement
    )
    assert measurement.count("days = 7") >= 2
    assert "enforce_workgroup_configuration    = true" in measurement
    assert "bytes_scanned_cutoff_per_query     = 1073741824" in measurement
    assert "/WAFLogs/cloudfront/${local.agent_measurement_acl}/" in measurement
    assert "/WAFLogs/us-east-1/tollchat-v2-public-chat/" not in measurement
    assert 'resource "aws_cloudwatch_log_group" "agent_usage_rollup"' in measurement
    assert "Historical rollup execution logs remain managed" in measurement
    assert 'resource "aws_s3_object" "agent_registry"' in measurement
    assert "ignore_changes = [source, source_hash]" in measurement
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


def test_agent_measurement_privacy_notice_precedes_logging():
    privacy = (V2_ROOT / "agent" / "privacy.txt").read_text()
    for text in (
        "seven days",
        "IP address",
        "full user-agent",
        "AWS WAF",
        "cookie values",
        "authorization headers",
        "New route-analytics collection and aggregate publication have stopped",
        "security controls remain separate",
    ):
        assert text in privacy
    measurement = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
    assert (
        'resource "aws_wafv2_web_acl_logging_configuration" "agent_reports"'
        not in measurement
    )
    assert "aws_s3_bucket_lifecycle_configuration" in measurement


def test_agent_registry_and_rollup_outputs_are_retained_inert_metadata():
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

    measurement = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
    assert 'route_keys     = "array<string>"' in measurement
    assert "ignore_changes = [source, source_hash]" in measurement
    for name in (
        "handler.py",
        "coverage.sql",
        "complete.sql",
        "latest_view.sql",
        "rollup.sql",
    ):
        assert not (V2_ROOT / "lambdas" / "agent_usage_rollup" / name).exists()


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
    assert 'id="usage-proof"' not in page
    assert "New public usage counting has stopped" in page
    assert "TollChat counts anonymous chat sessions" not in page


def test_agent_referrer_rules_match_only_exact_url_authorities():
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    assert "assistant_referrers" not in site
    assert 'dynamic "rule" {' not in site
    assert 'name     = "agent-route-report"' not in site


def test_retained_usage_snapshot_and_log_have_no_current_writer():
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    assert 'data "archive_file" "usage_publisher"' not in site
    assert 'data "aws_iam_policy_document" "usage_publisher"' not in site
    assert 'resource "aws_lambda_function" "usage_publisher"' not in site
    assert 'resource "aws_iam_role" "usage_publisher"' not in site
    assert 'resource "aws_iam_role_policy" "usage_publisher"' not in site
    assert 'resource "aws_cloudwatch_event_rule" "usage_publisher"' not in site
    assert 'resource "aws_cloudwatch_event_target" "usage_publisher"' not in site
    assert 'resource "aws_lambda_permission" "usage_publisher"' not in site
    assert 'resource "aws_cloudwatch_metric_alarm" "usage_publisher_errors"' not in site
    assert (
        'resource "aws_cloudwatch_metric_alarm" "usage_publisher_failed_invocations"'
        not in site
    )
    assert 'resource "aws_cloudwatch_log_group" "usage_publisher"' in site
    assert 'key           = "usage.json"' in site

    proxy_policy = terraform_block(
        agentcore, 'resource "aws_iam_role_policy" "tollchat_proxy"'
    )
    assert '"dynamodb:TransactWriteItems"' not in proxy_policy


def test_usage_rollout_has_no_retired_foundation_step():
    pre_bootstrap_runbook = DEPLOYMENT.split(
        "### Development bootstrap/import boundary", maxsplit=1
    )[0]
    assert "usage-permissions.tfplan" not in DEPLOYMENT
    assert "usage-prerequisites.tfplan" not in DEPLOYMENT
    assert "Historical `usage.json` is retained" in DEPLOYMENT
    assert "iam get-role-policy" not in pre_bootstrap_runbook
    assert "dynamodb:TransactWriteItems" not in DEPLOYMENT
    assert "tollchat_usage_optout=1" not in DEPLOYMENT
    assert "--consistent-read" not in DEPLOYMENT


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
    assert "historical" in rollback.lower()
    assert "usage#all" not in rollback
    assert "manual restore may change only application routing" in rollback
    assert "do not roll back automatically" in rollback


def test_v2_agent_packages_are_required_for_real_deployments():
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    build = V2_ROOT / "scripts" / "build_agentcore_zips.sh"
    assert 'variable "agentcore_package_path"' in variables
    assert 'variable "chat_proxy_package_path"' in variables
    assert "AgentCore deployment requires the reviewed v2 runtime package" in agentcore
    assert "Chat proxy deployment requires the reviewed v2 proxy package" in agentcore
    assert build.exists()


def test_reviewed_zip_builders_use_store_mode():
    expected_calls = {
        "build_loader_zip.sh": r'zip -qX0 "\$BUILD/loader\.zip" -@',
        "build_publisher_zip.sh": r'zip -qX0 "\$BUILD/publisher\.zip" -@',
        "build_agentcore_zips.sh": r'zip -qX0 "\$out" -@',
        "build_timed_checks_zip.sh": r'zip -qX0 "\$BUILD/timed-checks\.zip" -@',
    }
    for script_name, archive_call in expected_calls.items():
        script = (V2_ROOT / "scripts" / script_name).read_text()
        assert re.search(rf"(?m)^[ \t]*\([^\n]*\| {archive_call}\)$", script)


def test_timed_builder_import_smoke_is_secret_isolated():
    script = (V2_ROOT / "scripts" / "build_timed_checks_zip.sh").read_text()
    assert "env -i" in script
    assert "PYTHONNOUSERSITE=1" in script
    assert 'PYTHONPATH="$STAGE"' in script
    assert (
        'name.startswith(("AWS_", "ACTIONS_", "GITHUB_", "OPENAI_", "CLOUDFLARE_"))'
        in script
    )
    assert "uv run --python 3.13 --no-project python" in script
    assert "global-bundle.pem" in script
    assert (
        'DB_CA_BUNDLE_PATH          = "/var/task/rds-ca-bundle.pem"' in TIMED_CHECKS_TF
    )


def test_timed_lambda_scheduler_and_failure_contract():
    pairs = set(
        next(
            ast.literal_eval(node.value)
            for node in ast.parse(TIMED_CHECKS_MODULE).body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCHEDULE_WINDOW_PAIRS"
            and node.value is not None
        )
    )
    entries = re.findall(
        r'"([^"]+)"\s*=\s*\{ schedule = "([^"]+)", expression = "([^"]+)", window_id = "([^"]+)" \}',
        TIMED_CHECKS_TF,
    )
    assert len(entries) == 28
    assert len({name for name, *_ in entries}) == 28
    assert {(schedule, window) for _, schedule, _, window in entries} == pairs
    weekdays = {"1": "MON", "2": "TUE", "3": "WED", "4": "THU", "5": "FRI", "6": "SAT"}
    for _, schedule, expression, _ in entries:
        minute, hour, _, _, weekday = schedule.split()
        assert expression == f"cron({minute} {hour} ? * {weekdays[weekday]} *)"

    lambda_block = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_lambda_function" "timed_checks"'
    )
    for name, value in (
        ("s3_bucket", "var.foundation.agentcore_artifacts_bucket_name"),
        ("s3_key", "aws_s3_object.timed_checks.key"),
        ("s3_object_version", "aws_s3_object.timed_checks.version_id"),
        ("source_code_hash", "local.timed_checks_zip_hash"),
        ("reserved_concurrent_executions", "1"),
    ):
        assert_assignment(lambda_block, name, value)
    assert "filename" not in lambda_block
    assert "subnet_ids         = local.private_subnets" in lambda_block
    assert (
        "TIMED_CHECK_ALERTS_ENABLED = tostring(local.timed_check_alerts_enabled)"
        in lambda_block
    )
    assert "ENVIRONMENT                = var.environment" in lambda_block
    assert "ALERTS_TOPIC_ARN = var.foundation.alerts_topic_arn" in lambda_block
    assert 'data "aws_kms_alias" "alerts"' in TIMED_CHECKS_TF
    assert 'name = "alias/nova-toll-alerts"' in TIMED_CHECKS_TF

    schedule = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_scheduler_schedule" "timed_checks"'
    )
    assert_assignment(schedule, "for_each", "local.timed_check_schedules")
    assert_assignment(schedule, "state", '"ENABLED"')
    assert_assignment(schedule, "schedule_expression_timezone", '"America/New_York"')
    assert_assignment(schedule, "mode", '"OFF"')
    assert "window_id = each.value.window_id" in schedule
    assert "schedule  = each.value.schedule" in schedule
    assert schedule.count("maximum_retry_attempts       = 0") == 1
    assert schedule.count("maximum_event_age_in_seconds = 600") == 1

    invoke = terraform_block(
        TIMED_CHECKS_TF,
        'resource "aws_lambda_function_event_invoke_config" "timed_checks"',
    )
    assert_assignment(invoke, "maximum_retry_attempts", "0")
    assert_assignment(invoke, "maximum_event_age_in_seconds", "600")
    for queue_name in ("timed_checks_invoke_failure", "timed_checks_delivery_failure"):
        queue = terraform_block(
            TIMED_CHECKS_TF, f'resource "aws_sqs_queue" "{queue_name}"'
        )
        assert_assignment(queue, "sqs_managed_sse_enabled", "true")
        assert_assignment(queue, "message_retention_seconds", "1209600")
    assert TIMED_CHECKS_TF.count("alarm_actions       = local.alarm_actions") == 2

    lambda_trust = terraform_block(
        TIMED_CHECKS_TF,
        'data "aws_iam_policy_document" "timed_checks_lambda_assume"',
    )
    scheduler_trust = terraform_block(
        TIMED_CHECKS_TF,
        'data "aws_iam_policy_document" "timed_checks_scheduler_assume"',
    )
    assert 'identifiers = ["lambda.amazonaws.com"]' in lambda_trust
    assert 'identifiers = ["scheduler.amazonaws.com"]' in scheduler_trust
    assert 'variable = "aws:SourceAccount"' in scheduler_trust
    assert 'variable = "aws:SourceArn"' in scheduler_trust

    lambda_policy = terraform_block(
        TIMED_CHECKS_TF,
        'data "aws_iam_policy_document" "timed_checks_lambda"',
    )
    assert 'actions   = ["rds:DescribeDBInstances"]' in lambda_policy
    assert 'actions = ["rds-db:connect"]' in lambda_policy
    assert "/${local.database_roles.agent}" in lambda_policy
    assert "/${local.database_roles.pricing_caller}" in lambda_policy
    assert 'actions   = ["ssm:GetParameter"]' in lambda_policy
    assert 'actions   = ["sqs:SendMessage"]' in lambda_policy
    assert 'actions   = ["sns:Publish"]' in lambda_policy
    assert "resources = [var.foundation.alerts_topic_arn]" in lambda_policy
    assert 'actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]' in lambda_policy
    assert "resources = [data.aws_kms_alias.alerts.target_key_arn]" in lambda_policy
    assert 'resources = ["*"]' not in lambda_policy
    assert (
        "local.is_production || var.enable_development_timed_check_alerts"
        in TIMED_CHECKS_TF
    )
    assert 'variable "enable_development_timed_check_alerts"' in APPLICATION_VARIABLES
    assert "default     = false" in APPLICATION_VARIABLES
    assert (
        'var.environment == "development" || !var.enable_development_timed_check_alerts'
        in APPLICATION_VARIABLES
    )
    assert "enable_development_timed_check_alerts = true" in DEVELOPMENT_TFVARS.replace(
        "      ", " "
    )
    errors_alarm = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_cloudwatch_metric_alarm" "timed_checks_errors"'
    )
    assert (
        "Unexpected timed-check failures and evaluation alert delivery failures"
        in errors_alarm
    )

    assert 'cidr_ipv4         = "0.0.0.0/0"' in TIMED_CHECKS_TF
    assert "from_port         = 443" in TIMED_CHECKS_TF
    assert "to_port           = 443" in TIMED_CHECKS_TF
    assert "from_port                    = 5432" in TIMED_CHECKS_TF
    assert "to_port                      = 5432" in TIMED_CHECKS_TF
    assert 'ip_protocol = "-1"' not in TIMED_CHECKS_TF


def test_timed_package_is_threaded_through_all_plan_paths():
    assert (
        '-var timed_checks_package_path="$STAGING/timed-checks.zip"'
        in DEVELOPMENT_PLAN_WORKFLOW
    )
    assert (
        '-var timed_checks_package_path="$PACKAGE_DIR/timed-checks.zip"'
        in DEVELOPMENT_DELIVERY_WORKFLOW
    )
    assert (
        '-var timed_checks_package_path="$overlay/v2/infra/build/timed-checks.zip"'
        in PRODUCTION_PLAN_WORKFLOW
    )
    assert "-target" not in PRODUCTION_PLAN_WORKFLOW


def test_public_openai_egress_has_a_narrow_expiring_trivy_exception():
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
    assert (V2_ROOT / "scripts" / "build_timed_checks_zip.sh").exists()
    assert "./scripts/build_timed_checks_zip.sh" in CI_WORKFLOW

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
    assert "policy = jsonencode({" in scheduler_role_policy
    assert 'data "aws_iam_policy_document" "publisher_scheduler"' not in MAIN_TF
    statements = re.findall(
        r"(?s)\{\n\s+Effect\s*=\s*\"Allow\"(.*?)\n\s+\},", scheduler_role_policy
    )
    assert len(statements) == 2
    assert [
        (
            re.findall(r'Action\s+=\s+"([^"]+)"', statement),
            re.findall(r"Resource\s+=\s+([^\n]+)", statement),
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


def test_timed_connectivity_role_uses_the_internal_pricing_caller():
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

    assert "guarded production planner" in normalized_handoff
    assert "current foundation output" in normalized_handoff
    assert "planner-owned production handoff" in normalized_handoff
    assert "planned-output" not in normalized_handoff
    assert (
        "not a local release path or a development-state discovery mechanism"
        in normalized_handoff
    )
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
        for step in cast(list[dict[str, object]], job.get("steps", []))
    )


def test_production_release_plan_workflows_keep_trust_before_credentials_and_apply_disabled():
    listener = cast(
        dict[str, object],
        yaml.safe_load(
            (
                REPO_ROOT / ".github" / "workflows" / "v2-production-release.yml"
            ).read_text()
        ),
    )
    planner = cast(dict[str, object], yaml.safe_load(PRODUCTION_PLAN_WORKFLOW))
    assert _workflow_trigger(listener) == {"release": {"types": ["published"]}}
    assert _workflow_trigger(planner) == {
        "workflow_run": {
            "workflows": ["v2-production-release"],
            "types": ["completed"],
        }
    }
    for workflow in (listener, planner):
        assert workflow["concurrency"] == {
            "group": "v2-production-release-delivery",
            "cancel-in-progress": False,
        }

    listener_source = "\n".join(
        _workflow_run_source(job)
        for job in cast(dict[str, dict[str, object]], listener["jobs"]).values()
    )
    assert "aws-actions/configure-aws-credentials@" not in listener_source
    assert "terraform" not in listener_source
    assert (
        "v2-production-release-${{ github.run_id }}-${{ github.run_attempt }}"
        in str(listener)
    )

    jobs = cast(dict[str, dict[str, object]], planner["jobs"])
    assert set(jobs) == {"admission", "claim", "planner", "migrate", "release-result"}
    assert jobs["admission"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "deployments": "read",
    }
    assert jobs["claim"]["permissions"] == {"contents": "read", "deployments": "write"}
    assert jobs["planner"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "deployments": "read",
        "id-token": "write",
    }
    assert all(
        jobs[name].get("environment") is None
        for name in ("admission", "claim", "planner", "release-result")
    )
    assert str(jobs["migrate"]["uses"]).endswith("v2-production-migrations.yml@main")
    assert jobs["release-result"]["if"] == "${{ always() }}"

    admission_source = _workflow_run_source(jobs["admission"])
    claim_source = _workflow_run_source(jobs["claim"])
    planner_source = _workflow_run_source(jobs["planner"])
    assert (
        "aws-actions/configure-aws-credentials@" not in admission_source + claim_source
    )
    assert "check_production_release.py admit" in admission_source
    assert "check_production_release.py claim" in claim_source
    assert "check_production_release.py revalidate" in planner_source
    planner_steps = cast(list[dict[str, object]], jobs["planner"]["steps"])
    bundle_index = next(
        index
        for index, step in enumerate(planner_steps)
        if step.get("name") == "Verify exact candidate bundle before OIDC"
    )
    revalidation_index = next(
        index
        for index, step in enumerate(planner_steps)
        if step.get("name") == "Revalidate mutable release evidence before OIDC"
    )
    credentials_index = next(
        index
        for index, step in enumerate(planner_steps)
        if str(step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    )
    assert bundle_index < revalidation_index < credentials_index
    assert "terraform apply" not in planner_source
    assert "nova-toll-production-deploy" not in planner_source
    assert "-target" not in planner_source

    for field in (
        "listener_run",
        "listener_attempt",
        "development_run",
        "development_attempt",
        "development_deployment",
        "evidence_artifact",
        "evidence_digest",
        "bundle_id",
        "bundle_digest",
        "schema_versions",
        "claim_id",
        "saved_plan",
        "VersionId",
        "ChecksumSHA256",
        "SSEKMSKeyId",
    ):
        assert field in planner_source


def _development_foundation_validator(source: str) -> str:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    deploy_source = _workflow_run_source(jobs["deploy"])
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


def test_development_foundation_output_validators_fail_closed_and_match():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    workflow_jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    deploy_source = _workflow_run_source(workflow_jobs["deploy"])
    workflow_predicate = _development_foundation_validator(
        DEVELOPMENT_DELIVERY_WORKFLOW
    )
    runbook_predicate = _development_cutover_foundation_validator(DEPLOYMENT)

    for predicate in (workflow_predicate, runbook_predicate):
        assert _foundation_validator_keys(predicate) == list(FOUNDATION_FIELDS)
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


def _assert_development_build_setup_uv(build: dict[str, object]) -> None:
    setup_uv_steps = [
        step
        for step in cast(list[dict[str, object]], build["steps"])
        if cast(str, step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert len(setup_uv_steps) == 1
    assert cast(dict[str, str], setup_uv_steps[0]["with"]) == {
        "version": "0.12.5",
        "checksum": "68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2",
        "python-version": "3.13",
    }


def test_setup_uv_v10_pins_version_and_checksum() -> None:
    sources = (
        DEVELOPMENT_DELIVERY_WORKFLOW,
        DEVELOPMENT_PLAN_WORKFLOW,
        PRODUCTION_PLAN_WORKFLOW,
    )
    for source in sources:
        workflow = cast(dict[str, object], yaml.safe_load(source))
        jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
        setup_uv_steps = [
            step
            for job in jobs.values()
            for step in cast(list[dict[str, object]], job.get("steps", []))
            if cast(str, step.get("uses", "")).startswith("astral-sh/setup-uv@")
        ]
        assert setup_uv_steps
        for step in setup_uv_steps:
            with_values = cast(dict[str, str], step["with"])
            assert with_values["version"] == "0.12.5"
            assert (
                with_values["checksum"]
                == "68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2"
            )


def _assert_development_delivery_workflow(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    assert _workflow_trigger(workflow) == {"push": {"branches": ["main"]}}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {
        "admission",
        "release-record",
        "build",
        "oidc-proof",
        "deploy",
        "release-result",
    }
    record = jobs["release-record"]
    assert record["needs"] == "admission"
    assert record["permissions"] == {"contents": "read", "deployments": "write"}
    assert "development_deployment_status.py create" in _workflow_run_source(record)
    result = jobs["release-result"]
    assert result["needs"] == [
        "admission",
        "release-record",
        "build",
        "oidc-proof",
        "deploy",
    ]
    assert result["if"] == "always() && needs.admission.result == 'success'"
    assert result["permissions"] == {
        "contents": "read",
        "actions": "read",
        "deployments": "write",
    }
    result_steps = cast(list[dict[str, object]], result["steps"])
    prepare = next(
        step for step in result_steps if step.get("id") == "prepare-evidence"
    )
    upload = next(step for step in result_steps if step.get("id") == "upload-evidence")
    finalize = next(
        step
        for step in result_steps
        if step.get("name") == "Finalize sanitized release outcome"
    )
    assert prepare["if"] == "always()"
    assert "development_deployment_status.py prepare" in cast(str, prepare["run"])
    assert upload["if"] == "always() && steps.prepare-evidence.outcome == 'success'"
    assert (
        upload["uses"]
        == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    )
    assert upload["with"] == {
        "name": "v2-development-evidence-${{ github.run_id }}-${{ github.run_attempt }}",
        "path": "${{ runner.temp }}/development-release-evidence.json",
        "if-no-files-found": "error",
        "retention-days": 90,
        "overwrite": False,
    }
    assert finalize["if"] == "always()"
    finalize_source = cast(str, finalize["run"])
    assert "development_deployment_status.py finish" in finalize_source
    for required in (
        "PREPARE_OUTCOME",
        "UPLOAD_OUTCOME",
        "EVIDENCE_ARTIFACT_NAME",
        "EVIDENCE_ARTIFACT_ID",
        "RAW_EVIDENCE_ARTIFACT_DIGEST",
    ):
        assert required in cast(dict[str, str], finalize["env"])
    assert (
        result_steps.index(prepare)
        < result_steps.index(upload)
        < result_steps.index(finalize)
    )
    deploy_source = _workflow_run_source(jobs["deploy"])
    assert deploy_source.index('apply -input=false "$PLAN"') < deploy_source.index(
        "check_development_release.py"
    )
    assert jobs["deploy"]["outputs"] == {
        "verified": "${{ steps.verify-release.outputs.verified }}",
        "canary": "${{ steps.verify-release.outputs.canary }}",
        "verified_pricing_schema": "${{ steps.migration-schema.outputs.verified_pricing_schema }}",
        "verified_oracle_schema": "${{ steps.migration-schema.outputs.verified_oracle_schema }}",
    }
    deploy_steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    deploy_names = [cast(str, step.get("name", "")) for step in deploy_steps]
    extraction = next(
        step
        for step in deploy_steps
        if step.get("name") == "Extract verified installed schema versions"
    )
    assert (
        deploy_names.index("Run reviewed backward-compatible development migrations")
        < deploy_names.index("Extract verified installed schema versions")
        < deploy_names.index("Cleanup private delivery files")
    )
    extraction_source = cast(str, extraction["run"])
    assert "v2-development-migrations-evidence.json" in extraction_source
    assert ".after" in extraction_source
    assert "development-readiness-state.json" in deploy_source
    assert (
        'CANARY_DEPLOYMENT_ID="${{ needs.release-record.outputs.deployment_id }}"'
        in deploy_source
    )
    assert (
        'CANARY_ARTIFACT_ID="${{ needs.build.outputs.artifact_id }}"' in deploy_source
    )
    assert (
        'CANARY_ARTIFACT_DIGEST="${{ needs.build.outputs.artifact_digest }}"'
        in deploy_source
    )

    admission = jobs["admission"]
    assert admission["permissions"] == {"contents": "read", "actions": "read"}
    admission_source = _workflow_run_source(admission)
    assert "check_development_admission.py" in admission_source
    assert "GITHUB_EVENT_PATH" in admission_source
    assert "aws-actions/configure-aws-credentials@" not in admission_source
    assert "timeout-seconds 900" in admission_source
    assert "GITHUB_SHA" not in admission_source or "CANDIDATE_SHA" in admission_source

    build = jobs["build"]
    assert build["needs"] == ["admission", "release-record"]
    assert build["permissions"] == {"contents": "read", "actions": "read"}
    assert "id-token" not in cast(dict[str, str], build["permissions"])
    build_steps = cast(list[dict[str, object]], build["steps"])
    _assert_development_build_setup_uv(build)
    build_source = _workflow_run_source(build)
    assert all(
        not cast(str, step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
        for step in build_steps
    )
    assert "./scripts/build_release_bundle.sh" in build_source
    uploads = [
        step
        for step in build_steps
        if cast(str, step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    upload_names = {cast(dict[str, str], step["with"])["name"] for step in uploads}
    assert upload_names == {
        "v2-development-packages-${{ github.run_id }}-${{ github.sha }}",
        "v2-development-checksums-${{ github.run_id }}-${{ github.sha }}",
        "v2-development-release-${{ github.sha }}",
    }
    release_upload = next(
        step
        for step in uploads
        if cast(dict[str, object], step["with"])["name"]
        == "v2-development-release-${{ github.sha }}"
    )
    upload = release_upload
    assert upload["id"] == "upload-release"
    assert cast(dict[str, object], upload["with"]) == {
        "name": "v2-development-release-${{ github.sha }}",
        "path": "v2/infra/build/release",
        "if-no-files-found": "error",
        "retention-days": 90,
        "overwrite": False,
    }
    assert jobs["build"]["outputs"] == {
        "artifact_id": "${{ steps.release-identity.outputs.artifact_id }}",
        "artifact_digest": "${{ steps.release-identity.outputs.artifact_digest }}",
        "pricing_schema": "${{ steps.release-identity.outputs.pricing_schema }}",
        "oracle_schema": "${{ steps.release-identity.outputs.oracle_schema }}",
    }
    assert "RELEASE_ARTIFACT_ID" in build_source
    assert "RELEASE_ARTIFACT_DIGEST" in build_source
    assert "GITHUB_STEP_SUMMARY" in build_source

    proof = jobs["oidc-proof"]
    assert proof["needs"] == "admission"
    assert (
        proof["if"]
        == "github.ref == 'refs/heads/main' && needs.admission.result == 'success'"
    )
    assert proof["environment"] == "development"
    assert proof["permissions"] == {"contents": "read", "id-token": "write"}
    assert proof["outputs"] == {
        "artifact_id": "${{ steps.upload-proof.outputs.artifact-id }}"
    }
    proof_steps = cast(list[dict[str, object]], proof["steps"])
    proof_source = _workflow_run_source(proof)
    assert all(
        not cast(str, step.get("uses", "")).startswith(
            ("aws-actions/configure-aws-credentials@", "hashicorp/setup-terraform@")
        )
        for step in proof_steps
    )
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" in proof_source
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" in proof_source
    assert re.findall(r'oidc_url="([^"]+)"', proof_source) == [
        "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com",
        "${ACTIONS_ID_TOKEN_REQUEST_URL}?audience=sts.amazonaws.com",
    ]
    validator_match = re.search(
        r'python3 - "\$GITHUB_SHA" <<\x27PY\x27\n(.*?)\nPY',
        proof_source,
        flags=re.DOTALL,
    )
    assert validator_match is not None
    validator_tree = ast.parse(dedent(validator_match.group(1)))
    expected_assignment = next(
        node
        for node in ast.walk(validator_tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "expected"
            for target in node.targets
        )
    )
    expected_values = dict(
        zip(
            (
                cast(ast.Constant, key).value
                for key in cast(ast.Dict, expected_assignment.value).keys
            ),
            cast(ast.Dict, expected_assignment.value).values,
            strict=True,
        )
    )
    assert cast(ast.Constant, expected_values["aud"]).value == "sts.amazonaws.com"
    assert (
        cast(ast.Constant, expected_values["iss"]).value
        == "https://token.actions.githubusercontent.com"
    )
    assert "base64.urlsafe_b64decode" in proof_source
    assert (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
        in proof_source
    )
    assert '"environment": "development"' in proof_source
    assert '"repository": "rhprasad0/nova-toll-budget-agent"' in proof_source
    assert '"ref": "refs/heads/main"' in proof_source
    assert '"sha": expected_sha' in proof_source
    assert '"$RUNNER_TEMP/protected-main-oidc.json"' in proof_source
    proof_uploads = [
        step
        for step in proof_steps
        if cast(str, step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(proof_uploads) == 1
    assert proof_uploads[0]["id"] == "upload-proof"
    assert cast(dict[str, object], proof_uploads[0]["with"]) == {
        "name": "protected-main-oidc-proof",
        "path": "${{ runner.temp }}/protected-main-oidc.json",
        "if-no-files-found": "error",
        "retention-days": 1,
        "overwrite": False,
        "include-hidden-files": False,
    }
    assert "oidc_token" in proof_source
    assert "full claims" not in proof_source.lower()

    deploy = jobs["deploy"]
    assert deploy["needs"] == ["admission", "release-record", "build", "oidc-proof"]
    assert deploy["if"] == (
        "vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' "
        "&& github.triggering_actor == github.actor"
    )
    assert (
        "Repository variable: environment variables are unavailable to this pre-job gate."
        in source
    )
    assert deploy["environment"] == "development"
    assert deploy["permissions"] == {
        "contents": "read",
        "actions": "read",
        "id-token": "write",
    }
    assert deploy["concurrency"] == {"group": "v2-development-apply", "queue": "max"}
    deploy_steps = cast(list[dict[str, object]], deploy["steps"])
    deploy_source = _workflow_run_source(deploy)
    assert "check_development_admission.py" in deploy_source
    assert "--recheck" in deploy_source
    assert "Recheck admission before credentials" in "\n".join(
        cast(str, step.get("name", "")) for step in deploy_steps
    )
    admission_recheck_source = cast(
        str,
        next(
            step["run"]
            for step in deploy_steps
            if step.get("name") == "Recheck admission before credentials"
        ),
    )
    assert "PRIVATE_STAGE_REPORTED=1" not in admission_recheck_source
    downloads = [
        step
        for step in deploy_steps
        if cast(str, step.get("uses", "")).startswith("actions/download-artifact@")
    ]
    download_names = {
        cast(dict[str, str], step["with"])["name"]
        for step in downloads
        if "name" in cast(dict[str, str], step["with"])
    }
    assert download_names == {
        "v2-development-checksums-${{ github.run_id }}-${{ github.sha }}",
    }
    proof_downloads = [
        step
        for step in downloads
        if "artifact-ids" in cast(dict[str, str], step["with"])
    ]
    assert len(proof_downloads) == 1
    proof_download_with = cast(dict[str, str], proof_downloads[0]["with"])
    assert proof_download_with == {
        "artifact-ids": "${{ needs.oidc-proof.outputs.artifact_id }}",
        "path": "${{ runner.temp }}",
        "merge-multiple": True,
    }
    assert "name" not in proof_download_with
    assert "infra/release_manifest.py" in deploy_source
    assert "development-release-evidence.json" in deploy_source
    assert "--bundle-root v2/infra/build/release" in build_source
    assert '--bundle-root "$RUNNER_TEMP/release-overlay"' in deploy_source
    assert 'find "$GITHUB_WORKSPACE/v2/infra"' not in deploy_source
    assert '"$GITHUB_WORKSPACE/v2/infra/"*.tf' in deploy_source
    for reviewed_scaffold in (
        '"$GITHUB_WORKSPACE/v2/infra/.terraform.lock.hcl"',
        '"$GITHUB_WORKSPACE/v2/infra/backend.development.hcl"',
        '"$GITHUB_WORKSPACE/v2/infra/development.tfvars"',
    ):
        assert reviewed_scaffold in deploy_source
    assert "backend.production.hcl" not in deploy_source
    assert "known_managed" not in deploy_source
    assert "known_data" not in deploy_source
    assert 'git show "${GITHUB_SHA}:infra/development-release-manifest.json"' in source
    assert (
        source.index("Build reviewed deployment packages")
        < source.index("Checkout trusted manifest verifier after package build")
        < source.index("Verify reviewed manifest and write runtime evidence")
    )
    assert source.index(
        "Verify immutable development release without credentials"
    ) < source.index("aws-actions/configure-aws-credentials@")
    assert (
        "api.github.com/repos/$GITHUB_REPOSITORY/actions/artifacts/$RELEASE_ARTIFACT_ID"
        in deploy_source
    )
    assert "--max-redirs 0" in deploy_source
    assert "Authorization: Bearer $GH_TOKEN" in deploy_source
    assert '--location "$download_url"' in deploy_source
    assert "verify_release_bundle.py verify" in deploy_source
    assert "--verify-checkout" in deploy_source
    assert "git rev-parse HEAD" in deploy_source
    assert "release-manifest.json" in deploy_source
    assert "EXPECTED_PRICING_VERSION" in deploy_source
    assert "EXPECTED_ORACLE_VERSION" in deploy_source
    assert 'STAGED_PACKAGE_DIR="$RUNNER_TEMP/v2-development-packages"' in deploy_source
    assert 'cp -P -- "$source" "$STAGED_PACKAGE_DIR/$package"' in deploy_source
    assert 'sha256sum --check "$EVIDENCE_DIR/DEPLOYMENT_SHA256SUMS"' in deploy_source
    assert "development-release-staging-verification.json" in deploy_source
    deploy_step_names = "\n".join(
        cast(str, step.get("name", "")) for step in deploy_steps
    )
    plan_index = deploy_step_names.index(
        "Create and gate the saved development plan before migrations"
    )
    migration_index = deploy_step_names.index(
        "Run reviewed backward-compatible development migrations"
    )
    re_assume_index = deploy_step_names.index(
        "Confirm delivery role before applying saved plan"
    )
    apply_index = deploy_step_names.index("Apply the same saved development plan")
    assert plan_index < migration_index < re_assume_index < apply_index
    assert deploy_source.count('terraform -chdir="$RELEASE_ROOT/v2/infra" plan') == 1
    assert deploy_source.count('terraform -chdir="$RELEASE_ROOT/v2/infra" apply') == 1
    assert '--expected-digest "$RELEASE_ARTIFACT_DIGEST"' in deploy_source
    assert "path: ${{ runner.temp }}/v2-development-checksums" in source
    assert "aws-actions/configure-aws-credentials@" in "\n".join(
        cast(str, step.get("uses", "")) for step in deploy_steps
    )
    assert "./scripts/build_" not in deploy_source
    assert "arn:aws:iam::903859731897:role/nova-toll-v2-development-delivery" in source
    assert "role-to-assume: arn:aws:iam::903859731897:role/" in source
    assert "aws-region: us-east-1" in source
    assert 'version: "0.12.5"' in source
    assert 'terraform_version: "1.15.8"' in source
    assert deploy_source.count("-lockfile=readonly") == 2

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
    assert "Record protected-main OIDC proof" not in source
    assert (
        "rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
        in proof_source
    )
    assert "protected-main-oidc.json" in deploy_source
    assert 'PROOF="$RUNNER_TEMP/protected-main-oidc.json"' in deploy_source
    assert '(.commit_sha | test("^[0-9a-f]{40}$"))' in deploy_source
    assert ".commit_sha == $commit" in deploy_source
    proof_validation_index = next(
        index
        for index, step in enumerate(deploy_steps)
        if step.get("name") == "Validate protected-main OIDC proof"
    )
    assert proof_validation_index < configure_index
    assert (
        "terraform -chdir=infra init -input=false -lockfile=readonly" in deploy_source
    )
    assert "-backend-config=backend.development.hcl" in deploy_source
    assert "terraform -chdir=infra output -json foundation" in deploy_source
    assert (
        "foundation.tfvars.json" in deploy_source
        and "if: always()" in DEVELOPMENT_DELIVERY_WORKFLOW
    )
    assert (
        'terraform -chdir="$RELEASE_ROOT/v2/infra" init -input=false -lockfile=readonly'
        in deploy_source
    )
    assert "-var-file=development.tfvars" in deploy_source
    assert (
        'terraform -chdir="$RELEASE_ROOT/v2/infra" plan -input=false -out="$PLAN"'
        in deploy_source
    )
    assert 'PLAN_JSON="$RUNNER_TEMP/development.tfplan.json"' in deploy_source
    assert (
        'terraform -chdir="$RELEASE_ROOT/v2/infra" show -json "$PLAN"' in deploy_source
    )
    assert (
        'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"'
        in deploy_source
    )
    assert (
        deploy_source.count(
            'terraform -chdir="$RELEASE_ROOT/v2/infra" plan -input=false -out="$PLAN"'
        )
        == 1
    )
    assert (
        deploy_source.count(
            'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"'
        )
        == 1
    )
    assert (
        deploy_source.count(
            'terraform -chdir="$RELEASE_ROOT/v2/infra" show -json "$PLAN"'
        )
        == 1
    )
    assert '"$RUNNER_TEMP/protected-main-oidc.json"; do' in deploy_source
    assert deploy_source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"'
    ) < deploy_source.rindex('cleanup_path "$cleanup_log"')
    assert 'PACKAGE_DIR="$RUNNER_TEMP/v2-development-packages"' in deploy_source
    assert 'PACKAGE_DIR="$RELEASE_ROOT/v2/infra/build"' in deploy_source
    plan_index = deploy_source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" plan -input=false -out="$PLAN"'
    )
    show_index = deploy_source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" show -json "$PLAN"'
    )
    apply_index = deploy_source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"'
    )
    for stage in (
        "foundation-init",
        "foundation-output",
        "release-init",
        "plan",
        "show",
        "apply",
    ):
        assert f'"$TF_LOG_DIR/{stage}.log"' in deploy_source
    assert '"$RUNNER_TEMP/development-terraform-logs"' in source
    assert deploy_source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" show -json "$PLAN"'
    ) < deploy_source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"'
    )
    validator_index = deploy_source.index(
        "python3 infra/delivery_plan_validator.py", show_index
    )
    assert plan_index < show_index < validator_index < apply_index
    for package in (
        "$PACKAGE_DIR/loader.zip",
        "$PACKAGE_DIR/publisher.zip",
        "$PACKAGE_DIR/agentcore.zip",
        "$PACKAGE_DIR/chat-proxy.zip",
    ):
        assert package in deploy_source
    for forbidden in (
        "-target",
        "-lock=false",
        "backend.production.hcl",
        "terraform_remote_state",
        "AWS_PROFILE",
        "pull_request",
        "cloudflare",
        "placeholder",
        "920534282028",
    ):
        assert forbidden not in source


def _assert_development_plan_workflow(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    assert _workflow_trigger(workflow) == {
        "workflow_call": {
            "inputs": {
                "candidate_sha": {
                    "description": "Event-derived lowercase candidate commit SHA.",
                    "required": True,
                    "type": "string",
                }
            },
            "outputs": {
                "plan_result": {
                    "description": "Result of the protected nested plan job.",
                    "value": "${{ jobs.plan.result }}",
                }
            },
        }
    }
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {"build", "plan"}
    build = jobs["build"]
    plan = jobs["plan"]
    assert build["permissions"] == {"contents": "read"}
    assert "environment" not in build
    _assert_development_build_setup_uv(build)
    build_source = _workflow_run_source(build)
    assert "aws-actions/configure-aws-credentials@" not in build_source
    assert "id-token: write" not in build_source
    assert "role-to-assume" not in build_source
    assert "EVENT_SHA" in build_source
    assert "INPUT_SHA" in build_source
    assert "github.event.pull_request.head.sha" in source
    assert "github.event.merge_group.head_sha" in source
    assert "github.sha" in source
    assert "refs/pull/" in source
    assert "refs/heads/gh-readonly-queue/" in source
    assert "refs/heads/main" in source
    assert 'test "$INPUT_SHA" = "$EVENT_SHA"' in source
    assert "candidate_sha" in build_source
    assert "persist-credentials: false" in source
    assert "id: package-mode" in source
    assert 'test ! -L "$MANIFEST"' in build_source
    assert "isinstance(value, dict)" in build_source
    assert 'isinstance(value.get("deployment_inputs"), dict)' in build_source
    assert (
        '"v2/scripts/build_timed_checks_zip.sh" in value["deployment_inputs"]'
        in build_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip)"
        in build_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip timed-checks.zip)"
        in build_source
    )
    for package in (
        "loader.zip",
        "publisher.zip",
        "agentcore.zip",
        "chat-proxy.zip",
        "timed-checks.zip",
    ):
        assert package in build_source
    assert "DEPLOYMENT_SHA256SUMS" in build_source
    assert 'sha256sum "${PACKAGE_NAMES[@]}" > DEPLOYMENT_SHA256SUMS' in build_source
    assert (
        "awk '{print $2}' DEPLOYMENT_SHA256SUMS | LC_ALL=C sort | tr '\\n' ' '"
        in build_source
    )
    assert 'if [[ "$PACKAGE_MODE" = timed ]]; then' in build_source
    assert "./scripts/build_timed_checks_zip.sh" in build_source
    assert 'PACKAGE_STAGE="$RUNNER_TEMP/v2-development-packages"' in build_source
    assert 'mkdir -m 700 -- "$PACKAGE_STAGE"' in build_source
    assert 'cp -P -- "$source" "$PACKAGE_STAGE/$package"' in build_source
    assert 'find "$PACKAGE_STAGE" -mindepth 1 -maxdepth 1 -printf' in build_source
    assert (
        'sha256sum --check "$GITHUB_WORKSPACE/v2/infra/build/DEPLOYMENT_SHA256SUMS"'
        in build_source
    )
    assert "trusted-build/infra/release_manifest.py" in build_source
    assert '--repo-root "$GITHUB_WORKSPACE"' in build_source
    assert "--write-evidence" in build_source
    assert "development-release-manifest.json" in build_source
    assert "development-release-evidence.json" in build_source
    assert "path: trusted-build" in source
    assert (
        'git show "${CANDIDATE_SHA}:infra/development-release-manifest.json"'
        in build_source
    )
    assert "cp -P -- v2/infra/build/DEPLOYMENT_SHA256SUMS" in build_source
    assert (
        source.index("Build reviewed deployment packages")
        < source.index("Checkout trusted manifest verifier after candidate build")
        < source.index("Verify reviewed manifest and write runtime evidence")
    )
    uploads = [
        step
        for step in cast(list[dict[str, object]], build["steps"])
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert {cast(dict[str, str], step["with"])["name"] for step in uploads} == {
        "v2-development-packages-${{ github.run_id }}-${{ steps.resolve.outputs.candidate_sha }}",
        "v2-development-checksums-${{ github.run_id }}-${{ steps.resolve.outputs.candidate_sha }}",
    }

    assert plan["needs"] == "build"
    assert plan["environment"] == "development-plan"
    assert plan["permissions"] == {"contents": "read", "id-token": "write"}
    plan_source = _workflow_run_source(plan)
    assert "nova-toll-v2-development-plan" in source
    assert "903859731897" in plan_source
    assert "aws-region: us-east-1" in source
    assert "job.workflow_repository" in source
    assert "job.workflow_sha" in source
    assert "job.workflow_ref" in source
    assert "job.workflow_file_path" in source
    assert "path: trusted" in source
    assert source.count("repository: ${{ job.workflow_repository }}") == 2
    assert source.count("ref: ${{ job.workflow_sha }}") == 2
    assert (
        "v2-development-packages-${{ github.run_id }}-${{ needs.build.outputs.candidate_sha }}"
        in source
    )
    assert (
        "v2-development-checksums-${{ github.run_id }}-${{ needs.build.outputs.candidate_sha }}"
        in source
    )
    assert "artifact-ids:" not in plan_source
    assert "download-artifact" in source
    assert "trusted/infra/release_manifest.py" in plan_source
    assert "--evidence" in plan_source
    assert "--repo-root" not in plan_source
    assert 'test ! -L "$MANIFEST"' in plan_source
    assert "isinstance(value, dict)" in plan_source
    assert 'isinstance(value.get("deployment_inputs"), dict)' in plan_source
    assert (
        '"v2/scripts/build_timed_checks_zip.sh" in value["deployment_inputs"]'
        in plan_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip)"
        in plan_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip timed-checks.zip)"
        in plan_source
    )
    assert "PACKAGE_COUNT=4" in plan_source
    assert "PACKAGE_COUNT=5" in plan_source
    assert (
        "find \"$STAGING\" -mindepth 1 -maxdepth 1 -name '*.zip' -printf" in plan_source
    )
    assert 'test "$(wc -l <"$CHECKSUMS")" -eq "$PACKAGE_COUNT"' in plan_source
    assert 'sha256sum --check "$(basename "$CHECKSUMS")"' in plan_source
    assert source.index(
        "Verify candidate release binding without credentials"
    ) < source.index("aws-actions/configure-aws-credentials@")
    plan_start = source.index("\n  plan:\n")
    credential_index = source.index(
        "aws-actions/configure-aws-credentials@", plan_start
    )
    for boundary in (
        'PACKAGE_MODE="$(python3 - "$MANIFEST"',
        "find \"$STAGING\" -mindepth 1 -maxdepth 1 -name '*.zip'",
        'sha256sum --check "$(basename "$CHECKSUMS")"',
        "python3 trusted/infra/release_manifest.py",
    ):
        boundary_index = source.index(boundary, plan_start)
        assert plan_start < boundary_index < credential_index
    assert 'terraform_version: "1.15.8"' in source
    assert plan_source.count("-lockfile=readonly") == 2
    assert "-lock=false" in plan_source
    assert (
        plan_source.count('terraform -chdir="$GITHUB_WORKSPACE/trusted/v2/infra" plan')
        == 1
    )
    assert (
        'terraform -chdir="$GITHUB_WORKSPACE/trusted/v2/infra" show -json "$PLAN"'
        in plan_source
    )
    assert (
        'terraform -chdir="$GITHUB_WORKSPACE/trusted/v2/infra" apply' not in plan_source
    )
    for package_variable in (
        "loader_package_path",
        "publisher_package_path",
        "agentcore_package_path",
        "chat_proxy_package_path",
        "timed_checks_package_path",
    ):
        assert f"-var {package_variable}" in plan_source
    assert "development-release-manifest.json" in plan_source
    assert "delivery_plan_validator.py" in plan_source
    assert "GITHUB_STEP_SUMMARY" in plan_source
    assert '"$VALIDATION" | tee -a "$GITHUB_STEP_SUMMARY"' in plan_source
    assert (
        'FOUNDATION_VALIDATE_LOG="$RUNNER_TEMP/development-foundation-validate.log"'
        in plan_source
    )
    assert '2>"$FOUNDATION_VALIDATE_LOG"' in plan_source
    assert 'type == "object"' in plan_source
    assert "trap cleanup EXIT" in plan_source
    assert (
        "unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN" in plan_source
    )
    assert '"$PLAN"' in plan_source
    for forbidden in (
        "-target",
        "backend.production.hcl",
        "terraform_remote_state",
        "cloudflare",
        "ssm",
        "secrets",
    ):
        assert forbidden not in plan_source.lower()
    for job in jobs.values():
        for step in cast(list[dict[str, object]], job["steps"]):
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", cast(str, step["uses"]))
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert (
                    cast(dict[str, object], step["with"])["persist-credentials"]
                    is False
                )


def test_development_plan_workflow_digest_matches_reviewed_manifest():
    manifest = json.loads(
        (REPO_ROOT / "infra" / "development-release-manifest.json").read_text()
    )
    assert (
        hashlib.sha256(DEVELOPMENT_PLAN_WORKFLOW.encode()).hexdigest()
        == manifest["deployment_inputs"][".github/workflows/v2-development-plan.yml"]
    )


def test_development_plan_workflow_is_reusable_and_fail_closed():
    _assert_development_plan_workflow(DEVELOPMENT_PLAN_WORKFLOW)
    for original, replacement in (
        ("workflow_call:", "push:"),
        (
            "candidate_sha:\n        description:",
            "candidate_ref:\n        description:",
        ),
        ("environment: development-plan", "environment: development"),
        (
            "role/nova-toll-v2-development-plan",
            "role/nova-toll-v2-development-delivery",
        ),
        (
            "${{ github.run_id }}-${{ needs.build.outputs.candidate_sha }}",
            "${{ github.run_id }}",
        ),
        (
            "repository: ${{ job.workflow_repository }}",
            "repository: ${{ github.repository }}",
        ),
        ("ref: ${{ job.workflow_sha }}", "ref: ${{ github.sha }}"),
        ("-lockfile=readonly", "-lockfile=update"),
        ("-lock=false", "-lock=true"),
        ("trap cleanup EXIT", "trap cleanup RETURN"),
        ('python-version: "3.13"', ""),
        ('python-version: "3.13"', 'python-version: "3.12"'),
    ):
        _must_reject(
            _assert_development_plan_workflow,
            DEVELOPMENT_PLAN_WORKFLOW,
            original,
            replacement,
        )


def _assert_required_event_callers(source: str) -> None:
    ci = cast(dict[str, object], yaml.safe_load(source))
    ci_trigger = cast(dict[str, object], _workflow_trigger(ci))
    assert ci_trigger["pull_request"] is None
    assert ci_trigger["merge_group"] == {"types": ["checks_requested"]}
    ci_jobs = cast(dict[str, dict[str, object]], ci["jobs"])
    for job_name in ("v2-loader", "v2-database"):
        assert "if" not in ci_jobs[job_name]
    base_expression = (
        "github.event.pull_request.base.sha || "
        "github.event.merge_group.base_sha || github.event.before"
    )
    for variable in (
        "TOOL_CONTRACT_BASE_REF",
        "AGENT_CONTRACT_BASE_REF",
        "SCHEMA_BASE_REF",
    ):
        assert f"{variable}: ${{{{ {base_expression} }}}}" in source
    assert source.count(base_expression) == 3

    caller = ci_jobs["trusted-development-plan"]
    assert (
        caller["uses"] == "rhprasad0/nova-toll-budget-agent/.github/workflows/"
        "v2-development-plan.yml@main"
    )
    assert caller["with"] == {
        "candidate_sha": "${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha }}"
    }
    assert caller["permissions"] == {"contents": "read", "id-token": "write"}
    assert "pull_request" in str(caller["if"])
    assert "merge_group" in str(caller["if"])

    gate = ci_jobs["development-plan"]
    assert gate["if"] == "always()"
    assert gate["needs"] == "trusted-development-plan"
    gate_source = _workflow_run_source(gate)
    assert "CALL_RESULT: ${{ needs.trusted-development-plan.result }}" in source
    assert (
        "PLAN_RESULT: ${{ needs.trusted-development-plan.outputs.plan_result }}"
        in source
    )
    assert 'test "$CALL_RESULT" = success' in gate_source
    assert 'test "$PLAN_RESULT" = success' in gate_source
    assert "continue-on-error" not in source

    _assert_terraform_trigger(TERRAFORM_WORKFLOW)


def _assert_terraform_trigger(source: str) -> None:
    terraform = cast(dict[str, object], yaml.safe_load(source))
    terraform_trigger = cast(dict[str, object], _workflow_trigger(terraform))
    assert terraform_trigger["pull_request"] is None
    assert terraform_trigger["merge_group"] == {"types": ["checks_requested"]}
    assert "paths" not in cast(dict[str, object], terraform_trigger["merge_group"])
    assert "paths-ignore" not in source


def test_required_event_callers_are_unfiltered_and_fail_closed():
    _assert_required_event_callers(CI_WORKFLOW)
    for original, replacement in (
        (
            "pull_request:\n  merge_group:",
            "pull_request:\n    types: [opened]\n  merge_group:",
        ),
        ("merge_group:\n    types: [checks_requested]", "merge_group:"),
        (
            "github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before",
            "github.event.pull_request.base.sha || github.event.before",
        ),
        ("@main", "@feature"),
        ("if: always()", "if: success()"),
        ('test "$PLAN_RESULT" = success', 'test "$PLAN_RESULT" = skipped'),
    ):
        _must_reject(
            _assert_required_event_callers,
            CI_WORKFLOW,
            original,
            replacement,
        )
    _must_reject(
        _assert_development_plan_workflow,
        DEVELOPMENT_PLAN_WORKFLOW,
        "value: ${{ jobs.plan.result }}",
        "value: ${{ jobs.build.result }}",
    )
    _must_reject(
        _assert_terraform_trigger,
        TERRAFORM_WORKFLOW,
        "pull_request:\n  merge_group:",
        "pull_request:\n    types: [opened]\n  merge_group:",
    )


def _assert_development_delivery_validator_contract(source: str) -> None:
    workflow_source = source
    workflow = cast(dict[str, object], yaml.safe_load(source))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    source = _workflow_run_source(jobs["deploy"])
    assert "approved_delete" not in source
    assert "known_action" not in source
    assert "if ! jq -e" not in source
    assert "infra/delivery_plan_validator.py" in source
    assert 'MANIFEST="$EVIDENCE_DIR/development-release-manifest.json"' in source
    assert 'IDENTITY="$RUNNER_TEMP/development-plan-identity.json"' in source
    assert (
        'test -f "$MANIFEST" && test ! -L "$MANIFEST" && test -r "$MANIFEST" || MANIFEST_VALID=false'
        in source
    )
    assert (
        'test -f "$IDENTITY" && test ! -L "$IDENTITY" && test -r "$IDENTITY" || IDENTITY_VALID=false'
        in source
    )
    assert "select(valid_result) | {status, reason_code}" in source
    assert (
        'if test "$MANIFEST_VALID" != true || test "$IDENTITY_VALID" != true; then'
        in source
    )
    assert 'run_private_stage "validator" "$VALIDATION" "$VALIDATOR_LOG"' in source
    assert (
        'run_private_stage "validator" "$VALIDATION_SUMMARY" "$VALIDATOR_PARSE_LOG"'
        in source
    )
    assert 'cat "$VALIDATION_SUMMARY" >>"$VALIDATOR_PARSE_LOG"' in source
    assert '"invalid_schedule_value"' in source
    assert '"timed_contract_requires_marker"' in source
    assert (
        'VALIDATOR_RESULT_STATUS="$(jq -er \'.status\' "$VALIDATION_SUMMARY"' in source
    )
    assert 'if test "$VALIDATOR_RESULT_STATUS" != accepted; then' in source
    assert 'if test "$VALIDATOR_STATUS" -ne 0;' in source
    assert 'PROOF="$RUNNER_TEMP/protected-main-oidc.json"' in source
    assert '"$RUNNER_TEMP/protected-main-oidc.json"; do' in source
    assert "if: always()" in workflow_source
    assert source.index('PROOF="$RUNNER_TEMP/protected-main-oidc.json"') < source.index(
        'test -s "$PROOF"'
    )
    plan = source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" plan -input=false -out="$PLAN"'
    )
    show = source.index('terraform -chdir="$RELEASE_ROOT/v2/infra" show -json "$PLAN"')
    manifest_check = source.index('test -f "$MANIFEST"', show)
    validator = source.index("python3 infra/delivery_plan_validator.py", manifest_check)
    assert (
        'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"' in source
    )
    apply = source.index(
        'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"'
    )
    assert plan < show < manifest_check < validator < apply
    assert (
        source.count(
            'terraform -chdir="$RELEASE_ROOT/v2/infra" plan -input=false -out="$PLAN"'
        )
        == 1
    )
    assert (
        source.count('terraform -chdir="$RELEASE_ROOT/v2/infra" show -json "$PLAN"')
        == 1
    )
    assert (
        source.count(
            'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"'
        )
        == 1
    )
    assert 'run_private_stage "apply" "$APPLY_LOG" "$APPLY_LOG"' in source
    assert 'run_private_stage "cleanup" "$cleanup_log" "$cleanup_log"' in source
    assert "PRIVATE_STAGE_FALLBACK_STAGE=readiness-check" in source


def test_development_delivery_staging_snippet_accepts_only_verified_package_bytes():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    verify_source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name")
            == "Verify immutable development release without credentials"
        ),
    )
    staging_start = verify_source.index('rm -rf -- "$STAGED_PACKAGE_DIR"')
    staging_end = verify_source.index(
        "python3 infra/release_manifest.py", staging_start
    )
    staging = verify_source[staging_start:staging_end]

    with tempfile.TemporaryDirectory() as directory_name:
        root = Path(directory_name)
        package_dir = root / "overlay" / "v2" / "infra" / "build"
        package_dir.mkdir(parents=True)
        checksums_dir = root / "checksums"
        checksums_dir.mkdir()
        checksums = checksums_dir / "DEPLOYMENT_SHA256SUMS"
        packages = (
            "loader.zip",
            "publisher.zip",
            "agentcore.zip",
            "chat-proxy.zip",
            "timed-checks.zip",
        )
        for package in packages:
            (package_dir / package).write_bytes(package.encode())
        checksums.write_text(
            "".join(
                f"{hashlib.sha256((package_dir / package).read_bytes()).hexdigest()}  {package}\n"
                for package in packages
            ),
            encoding="ascii",
        )

        mock_bin = root / "bin"
        mock_bin.mkdir()
        mock_cp = mock_bin / "cp"
        mock_cp.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            '/bin/cp "$@"\n'
            'dest="${@: -1}"\n'
            'case "${MODE:-success}" in\n'
            '  tamper) printf tampered >>"$dest" ;;\n'
            '  truncate) : >"$dest" ;;\n'
            '  missing) rm -f -- "$dest" ;;\n'
            '  extra) : >"${STAGED_PACKAGE_DIR}/extra.zip" ;;\n'
            '  staged-symlink) rm -f -- "$dest"; ln -s -- "${PACKAGE_DIR}/loader.zip" "$dest" ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        mock_cp.chmod(0o700)

        def run_staging(mode: str = "success") -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", "-c", "set -euo pipefail\n" + staging],
                env={
                    **os.environ,
                    "PATH": f"{mock_bin}:{os.environ['PATH']}",
                    "PACKAGE_DIR": str(package_dir),
                    "STAGED_PACKAGE_DIR": str(root / "staged"),
                    "EVIDENCE_DIR": str(checksums_dir),
                    "MODE": mode,
                },
                capture_output=True,
                text=True,
                check=False,
            )

        success = run_staging()
        assert success.returncode == 0, success.stderr
        assert sorted(path.name for path in (root / "staged").iterdir()) == sorted(
            packages
        )
        for package in packages:
            assert (root / "staged" / package).read_bytes() == (
                package_dir / package
            ).read_bytes()

        for mode in ("tamper", "truncate", "missing", "extra", "staged-symlink"):
            assert run_staging(mode).returncode != 0, mode
        source = package_dir / "loader.zip"
        source.unlink()
        source.symlink_to(package_dir / "publisher.zip")
        assert run_staging().returncode != 0


def test_development_delivery_private_stage_helper_sanitizes_mock_failures():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    plan_source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name")
            == "Create and gate the saved development plan before migrations"
        ),
    )
    assert "source v2/scripts/run_private_stage.sh" in plan_source
    for stage in (
        "foundation-init",
        "foundation-output",
        "release-init",
        "plan",
        "show",
        "validator",
    ):
        script = (
            "set -euo pipefail\n"
            + "source v2/scripts/run_private_stage.sh\n"
            + '\nmkdir -m 700 -- "$RUNNER_TEMP/logs"\n'
            + f'run_private_stage "{stage}" "$RUNNER_TEMP/logs/stdout" "$RUNNER_TEMP/logs/stderr" bash -c \'printf raw-diagnostic >&2; exit 17\'\n'
        )
        with tempfile.TemporaryDirectory() as directory_name:
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=REPO_ROOT,
                env={**os.environ, "RUNNER_TEMP": directory_name},
                capture_output=True,
                text=True,
                check=False,
            )
        assert result.returncode == 17
        assert result.stdout == ""
        assert result.stderr.splitlines()[0].startswith(
            f"stage={stage} status=start elapsed="
        )
        assert result.stderr.splitlines()[-1].startswith(
            f"stage={stage} status=fail elapsed="
        )
        assert "exit=17 reason=unclassified" in result.stderr
        assert "raw-diagnostic" not in result.stdout + result.stderr

    with tempfile.TemporaryDirectory() as directory_name:
        missing_log = Path(directory_name) / "missing" / "stage.log"
        result = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail; source v2/scripts/run_private_stage.sh; "
                "set +e; run_private_stage apply $1 $1 bash -c 'printf secret >&2; exit 17'; "
                "status=$?; set -e; printf '%s\\n' \"$status\"",
                "bash",
                str(missing_log),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == "1\n"
        assert "status=fail" in result.stderr
        assert "reason=diagnostic_unavailable" in result.stderr
        assert "secret" not in result.stdout + result.stderr

        invalid = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail; source v2/scripts/run_private_stage.sh; "
                "set +e; run_private_stage secret-stage /tmp/out /tmp/err true; "
                "status=$?; set -e; printf '%s\\n' \"$status\"",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid.returncode == 0
        assert invalid.stdout == "64\n"
        assert "secret-stage" not in invalid.stdout + invalid.stderr

    with tempfile.TemporaryDirectory() as directory_name:
        root = Path(directory_name)
        (root / "logs").mkdir()
        result = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail; source v2/scripts/run_private_stage.sh; "
                'run_private_stage plan "$RUNNER_TEMP/logs/out" "$RUNNER_TEMP/logs/err" true',
            ],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "RUNNER_TEMP": str(root),
                "GITHUB_STEP_SUMMARY": str(root / "missing" / "summary"),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 125
        assert "stage=plan status=fail" in result.stderr
        assert "exit=125 reason=unclassified" in result.stderr
        assert str(root) not in result.stdout + result.stderr


def test_development_delivery_classifier_is_bounded_and_allowlisted():
    classifier = REPO_ROOT / "v2" / "scripts" / "classify_deployment_error.py"
    cases = {
        "access_denied": "AccessDeniedException: forbidden",
        "expired_credentials": "The security token included in the request is expired",
        "network": "connection reset by peer",
        "dns": "could not resolve host",
        "tls": "x509: certificate verify failed",
        "backend_config": "Error configuring the backend",
        "state_lock": "Error acquiring the state lock",
        "provider_installation": "Failed to install provider",
        "checksum": "doesn't match any of the checksums",
        "malformed_input": "malformed JSON input",
        "unclassified": "a bounded arbitrary failure",
    }
    with tempfile.TemporaryDirectory() as directory_name:
        path = Path(directory_name) / "diagnostic.log"
        for expected, diagnostic in cases.items():
            path.write_text(diagnostic, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(classifier), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0
            assert result.stdout == f"{expected}\n"
            assert result.stderr == ""

        path.write_text("access deniedish", encoding="utf-8")
        near_match = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert near_match.stdout == "unclassified\n"

        path.write_bytes(b"x" * (64 * 1024) + b" AccessDeniedException")
        bounded = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert bounded.stdout == "unclassified\n"

        missing = subprocess.run(
            [sys.executable, str(classifier), str(path) + ".missing"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert missing.stdout == "diagnostic_unavailable\n"

        path.write_bytes(b"\xff\xfe")
        unreadable = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert unreadable.stdout == "diagnostic_unavailable\n"

        path.write_text(
            "secret-token=do-not-print AccessDeniedException", encoding="utf-8"
        )
        secret = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert secret.stdout == "access_denied\n"
        assert "secret-token" not in secret.stdout + secret.stderr


def test_development_delivery_mocked_plan_failures_skip_downstream_and_cleanup():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    plan_source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name")
            == "Create and gate the saved development plan before migrations"
        ),
    )
    cleanup_source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name") == "Cleanup private delivery files"
        ),
    )
    foundation: dict[str, object] = {
        key: "value"
        for key in (
            "vpc_id",
            "vpc_cidr_block",
            "rds_security_group_id",
            "agentcore_endpoint_security_group_id",
            "eventbridge_endpoint_security_group_id",
            "agentcore_vpc_endpoint_id",
            "agentcore_vpc_endpoint_dns_name",
            "tollchat_api_vpc_endpoint_id",
            "raw_bucket_name",
            "raw_kms_key_arn",
            "agentcore_artifacts_bucket_name",
            "alerts_topic_arn",
        )
    }
    foundation.update(
        private_subnet_ids={"a": "subnet-a", "c": "subnet-c"},
        db_instance={
            "identifier": "db",
            "resource_id": "resource",
            "address": "db.example",
            "port": 5432,
        },
    )

    with tempfile.TemporaryDirectory() as directory_name:
        root = Path(directory_name)
        mock_bin = root / "bin"
        mock_bin.mkdir()
        foundation_path = root / "foundation.json"
        foundation_path.write_text(json.dumps(foundation), encoding="utf-8")
        terraform = mock_bin / "terraform"
        terraform.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'args=" $* "\n'
            "stage=unknown\n"
            'case "$args" in\n'
            "  *chdir=infra*' init '*) stage=foundation-init ;;\n"
            "  *' output '*) stage=foundation-output ;;\n"
            "  *' init '*) stage=release-init ;;\n"
            "  *' plan '*) stage=plan ;;\n"
            "  *' show '*) stage=show ;;\n"
            "esac\n"
            'if test "${FAIL_STAGE:-}" = "$stage"; then printf \'raw-%s\\n\' "$stage" >&2; exit 17; fi\n'
            'case "$stage" in\n'
            '  foundation-output) if test "${FAIL_STAGE:-}" = foundation-output-validation; then printf \'{}\\n\'; else cat "$FOUNDATION_FIXTURE"; fi ;;\n'
            '  plan) for arg in "$@"; do case "$arg" in -out=*) : >"${arg#-out=}" ;; esac; done ;;\n'
            "  show) printf '{}\\n' ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        terraform.chmod(0o700)
        real_python = mock_bin / "python3.real"
        real_python.symlink_to(Path(os.environ.get("PYTHON", "/usr/bin/python3")))
        python = mock_bin / "python3"
        python.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if test "${1:-}" = infra/delivery_plan_validator.py; then\n'
            "  printf '%s\\n' \"$VALIDATOR_JSON\"\n"
            '  exit "${VALIDATOR_EXIT:-0}"\n'
            "fi\n"
            'exec "${REAL_PYTHON}" "$@"\n',
            encoding="utf-8",
        )
        python.chmod(0o700)

        accepted = json.dumps(
            {
                "status": "accepted",
                "reason_code": "ok",
                "addresses": [],
                "actions": [],
                "operation_classes": [],
                "fingerprint": "a" * 64,
            }
        )
        rejected = json.dumps(
            {
                "status": "rejected",
                "reason_code": "unsupported_field_delta",
                "address": "secret-resource",
                "action": "update",
                "operation_class": "lambda-code",
            }
        )

        def run_plan(
            *,
            fail_stage: str = "",
            validator_json: str = accepted,
            validator_exit: int = 0,
        ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
            run_root = (
                root
                / f"run-{len(list(root.glob('run-*')))}-{fail_stage or 'success'}-{validator_exit}"
            )
            run_root.mkdir()
            (run_root / "protected-main-oidc.json").write_text(
                "proof", encoding="utf-8"
            )
            (run_root / "v2-development-checksums").mkdir()
            (
                run_root / "v2-development-checksums/development-release-manifest.json"
            ).write_text("{}", encoding="utf-8")
            (run_root / "v2-development-packages").mkdir()
            for package in (
                "loader.zip",
                "publisher.zip",
                "agentcore.zip",
                "chat-proxy.zip",
            ):
                (run_root / "v2-development-packages" / package).write_bytes(b"package")
            overlay = run_root / "release-overlay/v2/infra"
            overlay.mkdir(parents=True)
            summary = run_root / "summary"
            summary.touch()
            marker = run_root / "downstream.marker"
            script = plan_source + f"\nprintf 'migration-and-apply\\n' >\"{marker}\"\n"
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=REPO_ROOT,
                env={
                    **os.environ,
                    "PATH": f"{mock_bin}:{os.environ['PATH']}",
                    "PYTHON": str(real_python),
                    "REAL_PYTHON": str(real_python),
                    "RUNNER_TEMP": str(run_root),
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "FAIL_STAGE": fail_stage,
                    "FOUNDATION_FIXTURE": str(foundation_path),
                    "VALIDATOR_JSON": validator_json,
                    "VALIDATOR_EXIT": str(validator_exit),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            cleanup = subprocess.run(
                ["bash", "-c", cleanup_source],
                cwd=REPO_ROOT,
                env={
                    **os.environ,
                    "RUNNER_TEMP": str(run_root),
                    "GITHUB_WORKSPACE": str(run_root),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            assert cleanup.returncode == 0
            for private_path in (
                "v2-development-packages",
                "v2-development-checksums",
                "release-overlay",
                "development-terraform-logs",
                "development.tfplan",
                "development.tfplan.json",
                "development-plan-validation-summary.json",
                "protected-main-oidc.json",
            ):
                assert not (run_root / private_path).exists(), private_path
            return result, marker, summary

        success, marker, summary = run_plan()
        assert success.returncode == 0, success.stderr
        assert marker.read_text(encoding="utf-8") == "migration-and-apply\n"
        summary_text = summary.read_text(encoding="utf-8")
        summary_value = json.loads(
            summary_text[summary_text.index("{") : summary_text.rindex("}") + 1]
        )
        assert summary_value == {
            "status": "accepted",
            "reason_code": "ok",
        }

        for stage in (
            "foundation-init",
            "foundation-output",
            "release-init",
            "plan",
            "show",
        ):
            result, marker, _ = run_plan(fail_stage=stage)
            assert result.returncode == 17
            assert result.stdout == ""
            assert f"stage={stage} status=start" in result.stderr
            assert f"stage={stage} status=fail" in result.stderr
            assert "exit=17 reason=unclassified" in result.stderr
            assert "raw-" not in result.stderr
            assert not marker.exists()

        result, marker, _ = run_plan(fail_stage="foundation-output-validation")
        assert result.returncode == 1
        assert "stage=foundation-output-validation status=fail" in result.stderr
        assert not marker.exists()

        for reason in ("invalid_schedule_value", "timed_contract_requires_marker"):
            reason_rejected = json.dumps(
                {**json.loads(rejected), "reason_code": reason}
            )
            result, marker, summary = run_plan(
                validator_json=reason_rejected, validator_exit=1
            )
            assert result.returncode == 1
            assert "stage=validator status=fail" in result.stderr
            assert not marker.exists()
            summary_text = summary.read_text(encoding="utf-8")
            summary_value = json.loads(
                summary_text[summary_text.index("{") : summary_text.rindex("}") + 1]
            )
            assert summary_value == {
                "status": "rejected",
                "reason_code": reason,
            }

        arbitrary = json.dumps(
            {**json.loads(rejected), "reason_code": "unregistered_reason"}
        )
        result, marker, _ = run_plan(validator_json=arbitrary, validator_exit=1)
        assert result.returncode != 0
        assert "stage=validator status=fail" in result.stderr
        assert not marker.exists()

        result, marker, _ = run_plan(validator_json=rejected, validator_exit=0)
        assert result.returncode == 1
        assert "stage=validator status=fail" in result.stderr
        assert not marker.exists()


def test_development_delivery_apply_readiness_and_cleanup_failures_are_bounded():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])

    def source_for(name: str) -> str:
        return cast(
            str,
            next(step["run"] for step in steps if step.get("name") == name),
        )

    apply_source = source_for("Apply the same saved development plan")
    readiness_source = source_for("Verify readiness and public release path")
    cleanup_source = source_for("Cleanup private delivery files")

    with tempfile.TemporaryDirectory() as directory_name:
        root = Path(directory_name)
        mock_bin = root / "bin"
        mock_bin.mkdir()
        (root / "release-overlay/v2/infra").mkdir(parents=True)
        (root / "release-overlay/release-manifest.json").write_text(
            "{}", encoding="utf-8"
        )
        (root / "development.tfplan").write_text("plan", encoding="utf-8")
        (root / "development-terraform-logs").mkdir(mode=0o700)
        summary = root / "summary"
        summary.touch()
        terraform = mock_bin / "terraform"
        terraform.write_text(
            "#!/usr/bin/env bash\nprintf 'raw-apply\n' >&2\nexit 17\n",
            encoding="utf-8",
        )
        terraform.chmod(0o700)
        result = subprocess.run(
            ["bash", "-c", apply_source],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PATH": f"{mock_bin}:{os.environ['PATH']}",
                "RUNNER_TEMP": str(root),
                "GITHUB_STEP_SUMMARY": str(summary),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 17
        assert "stage=apply status=fail" in result.stderr
        assert "exit=17" in result.stderr
        assert "raw-apply" not in result.stdout + result.stderr

        terraform.write_text(
            "#!/usr/bin/env bash\nprintf 'raw-readiness\n' >&2\nexit 23\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            ["bash", "-c", readiness_source],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PATH": f"{mock_bin}:{os.environ['PATH']}",
                "RUNNER_TEMP": str(root),
                "GITHUB_STEP_SUMMARY": str(summary),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 23
        assert "stage=readiness-state status=fail" in result.stderr
        assert "exit=23" in result.stderr
        assert "raw-readiness" not in result.stdout + result.stderr
        assert not (root / "development-readiness-state.json").exists()
        assert not (root / "development-readiness-state.log").exists()

        terraform.write_text(
            "#!/usr/bin/env bash\nprintf '{}\\n'\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            ["bash", "-c", readiness_source],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PATH": f"{mock_bin}:{os.environ['PATH']}",
                "RUNNER_TEMP": str(root),
                "GITHUB_STEP_SUMMARY": str(summary),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "stage=readiness-check status=fail" in result.stderr

        calls = root / "rm-calls"
        failing_path = root / "development.tfplan"
        rm = mock_bin / "rm"
        rm.write_text(
            "#!/usr/bin/env bash\n"
            'printf \'%s\\n\' "$@" >>"$RM_CALLS"\n'
            'for arg in "$@"; do\n'
            '  if test "$arg" = "$RM_FAIL"; then printf \'raw-cleanup\\n\' >&2; exit 29; fi\n'
            "done\n"
            '/bin/rm "$@"\n',
            encoding="utf-8",
        )
        rm.chmod(0o700)
        result = subprocess.run(
            ["bash", "-c", cleanup_source],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PATH": f"{mock_bin}:{os.environ['PATH']}",
                "RUNNER_TEMP": str(root),
                "GITHUB_WORKSPACE": str(root),
                "GITHUB_STEP_SUMMARY": str(summary),
                "RM_CALLS": str(calls),
                "RM_FAIL": str(failing_path),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 29
        assert "stage=cleanup status=fail" in result.stderr
        assert "raw-cleanup" not in result.stdout + result.stderr
        call_text = calls.read_text(encoding="utf-8")
        assert str(failing_path) in call_text
        assert call_text.index(str(failing_path)) < call_text.index(
            str(root / "development.tfplan.json")
        )


def test_development_delivery_extracts_only_validated_migration_after_versions():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name") == "Extract verified installed schema versions"
        ),
    )
    evidence: dict[str, object] = {
        "account": "903859731897",
        "after": {"pricing": "1.2.3", "oracle": "1.14.0"},
        "applied": list[str](),
        "before": {"pricing": "1.2.3", "oracle": "1.14.0"},
        "commit_sha": "a" * 40,
        "database": "nova_toll_development",
        "github_run_attempt": "2",
        "github_run_id": "123",
        "role": "nova-toll-v2-development-migrations-dev",
        "route": "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112",
        "route_valid": True,
        "runner_run_id": "migration-run",
        "status": "ok",
        "transport_valid": True,
        "user": "schema_migrator_development",
    }

    def run(
        value: Mapping[str, object],
    ) -> tuple[subprocess.CompletedProcess[str], str, bool]:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            output = root / "output"
            summary = root / "summary"
            (root / "v2-development-migrations-evidence.json").write_text(
                json.dumps(value), encoding="utf-8"
            )
            result = subprocess.run(
                ["bash", "-c", source],
                cwd=REPO_ROOT,
                env={
                    **os.environ,
                    "RUNNER_TEMP": str(root),
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "GITHUB_SHA": "a" * 40,
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_RUN_ATTEMPT": "2",
                    "EXPECTED_PRICING_VERSION": "1.2.3",
                    "EXPECTED_ORACLE_VERSION": "1.14.0",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            return (
                result,
                output.read_text() if output.exists() else "",
                output.exists(),
            )

    result, output, exists = run(evidence)
    assert result.returncode == 0, result.stderr
    assert exists
    assert output == "verified_pricing_schema=1.2.3\nverified_oracle_schema=1.14.0\n"
    mutations: tuple[dict[str, object], ...] = (
        {**evidence, "commit_sha": "b" * 40},
        {**evidence, "after": {"pricing": "9.9.9", "oracle": "1.14.0"}},
        {**evidence, "after": "secret malformed evidence"},
    )
    for mutation in mutations:
        result, _, exists = run(mutation)
        assert result.returncode != 0
        assert not exists
        assert "secret malformed evidence" not in result.stdout + result.stderr


def test_slice2_delivery_diagnostics_keep_machine_outputs_and_fixed_labels():
    delivery = DEVELOPMENT_DELIVERY_WORKFLOW
    migration = (
        REPO_ROOT / "v2/scripts/run_development_migrations_workflow.sh"
    ).read_text(encoding="utf-8")
    for label in (
        "admission-recheck",
        "artifact-download",
        "release-verification",
        "oidc-claims",
        "account-identity",
        "delivery-role",
        "rds-ca",
    ):
        assert label in delivery
    assert 'cat "$VALIDATION_SUMMARY" >&2' in delivery
    assert (
        'MIGRATION_STDOUT_LOG="${RUNNER_TEMP}/development-migration-stage.stdout"'
        in migration
    )
    assert (
        'MIGRATION_STDERR_LOG="${RUNNER_TEMP}/development-migration-stage.stderr"'
        in migration
    )
    assert 'DB_TOKEN="$(<"$MIGRATION_STDOUT_LOG")"' not in migration
    assert 'RUNNER_JSON="$(<"$MIGRATION_STDOUT_LOG")"' in migration
    assert "migrations-workflow.yml" not in delivery


def test_retained_artifact_bootstrap_handles_jq_outcomes_without_public_errors(
    tmp_path: Path,
) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    build = cast(dict[str, object], workflow["jobs"])["build"]
    steps = cast(list[dict[str, object]], cast(dict[str, object], build)["steps"])
    source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name") == "Reject retained exact release artifact"
        ),
    )
    sha = "a" * 40

    def run_case(
        case: str, *, evaluation_error: bool = False
    ) -> subprocess.CompletedProcess[str]:
        root = tmp_path / case
        mock_bin = root / "bin"
        mock_bin.mkdir(parents=True)
        curl = mock_bin / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            "if test \"$ARTIFACT_CASE\" = malformed; then printf 'not-json\\n';\n"
            'elif test "$ARTIFACT_CASE" = retained; then printf \'{"artifacts":[{"name":"v2-development-release-%s","expired":false}]}\\n\' "$GITHUB_SHA";\n'
            "else printf '{\"artifacts\":[]}\\n'; fi\n",
            encoding="utf-8",
        )
        curl.chmod(0o700)
        if evaluation_error:
            jq = mock_bin / "jq"
            jq.write_text(
                "#!/usr/bin/env bash\n"
                'count_file="$RUNNER_TEMP/jq-count"\n'
                'count=0; test -e "$count_file" && count="$(<"$count_file")"\n'
                'count=$((count + 1)); printf "%s" "$count" >"$count_file"\n'
                'if test "$count" -eq 2; then printf "private-evaluation-error\\n" >&2; exit 2; fi\n'
                "exit 0\n",
                encoding="utf-8",
            )
            jq.chmod(0o700)
        summary = root / "summary"
        result = subprocess.run(
            ["bash", "-c", source],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PATH": f"{mock_bin}:{os.environ['PATH']}",
                "RUNNER_TEMP": str(root),
                "GITHUB_STEP_SUMMARY": str(summary),
                "GITHUB_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
                "GITHUB_SHA": sha,
                "GH_TOKEN": "test-token",
                "ARTIFACT_CASE": case,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert not (root / "release-artifacts.json").exists()
        assert not (root / "release-artifacts.error").exists()
        return result

    no_match = run_case("no-match")
    assert no_match.returncode == 0
    assert "stage=retained-artifact status=pass" in no_match.stderr

    retained = run_case("retained")
    assert retained.returncode == 1
    assert "reason=retained_artifact" in retained.stderr

    malformed = run_case("malformed")
    assert malformed.returncode != 0
    assert "reason=malformed_evidence" in malformed.stderr
    assert "jq: parse error" not in malformed.stdout + malformed.stderr

    evaluation = run_case("evaluation", evaluation_error=True)
    assert evaluation.returncode == 2
    assert "reason=malformed_evidence" in evaluation.stderr
    assert "private-evaluation-error" not in evaluation.stdout + evaluation.stderr


def test_development_delivery_plan_preflight_uses_shared_validator_and_exact_plan():
    _assert_development_delivery_validator_contract(DEVELOPMENT_DELIVERY_WORKFLOW)
    validator_invocation = (
        'run_private_stage "validator" "$VALIDATION" "$VALIDATOR_LOG" '
        '\\\n            python3 infra/delivery_plan_validator.py "$PLAN_JSON" "$MANIFEST" --identity "$IDENTITY"'
    )
    show_invocation = (
        'run_private_stage "show" "$PLAN_JSON" "$SHOW_LOG" '
        '\\\n            terraform -chdir="$RELEASE_ROOT/v2/infra" show -json "$PLAN"'
    )
    for original, replacement in (
        (
            'test -f "$MANIFEST" && test ! -L "$MANIFEST" && test -r "$MANIFEST" || MANIFEST_VALID=false',
            "MANIFEST_VALID=true",
        ),
        (
            'test -f "$IDENTITY" && test ! -L "$IDENTITY" && test -r "$IDENTITY" || IDENTITY_VALID=false',
            "IDENTITY_VALID=true",
        ),
        ('if test "$VALIDATOR_STATUS" -ne 0;', 'if test "$VALIDATOR_STATUS" -eq 0;'),
        (
            'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"',
            'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$OTHER_PLAN"',
        ),
        (validator_invocation, "true"),
    ):
        _must_reject(
            _assert_development_delivery_validator_contract,
            DEVELOPMENT_DELIVERY_WORKFLOW,
            original,
            replacement,
        )
    _must_reject(
        _assert_development_delivery_validator_contract,
        DEVELOPMENT_DELIVERY_WORKFLOW,
        show_invocation + "\n          MANIFEST_VALID=true",
        'terraform -chdir="$RELEASE_ROOT/v2/infra" apply -input=false "$PLAN"\n          '
        + show_invocation
        + "\n          MANIFEST_VALID=true",
    )


def test_development_oidc_validator_rejects_malformed_and_wrong_claim_fixtures():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    proof_source = _workflow_run_source(jobs["oidc-proof"])
    match = re.search(
        r'python3 - "\$GITHUB_SHA" <<\x27PY\x27\n(.*?)\nPY',
        proof_source,
        flags=re.DOTALL,
    )
    assert match is not None
    validator = dedent(match.group(1))
    expected_sha = "a" * 40
    claims = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "sts.amazonaws.com",
        "sub": "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
        "environment": "development",
        "repository": "rhprasad0/nova-toll-budget-agent",
        "ref": "refs/heads/main",
        "sha": expected_sha,
    }

    def segment(value: object) -> bytes:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).rstrip(b"=")

    def token_for(values: Mapping[str, object]) -> str:
        return b".".join(
            (segment({"alg": "RS256"}), segment(values), segment("signature"))
        ).decode()

    def run(token: str, sha: str = expected_sha) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["OIDC_TOKEN"] = token
        return subprocess.run(
            [sys.executable, "-", sha],
            input=validator,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    valid = run(token_for(claims))
    assert valid.returncode == 0, valid.stderr
    for name, value in (
        ("iss", "https://evil.example"),
        ("aud", "wrong-audience"),
        ("sub", "repo:evil/fork:ref:refs/heads/main"),
        ("environment", "production"),
        ("repository", "evil/fork"),
        ("ref", "refs/heads/release"),
        ("sha", "b" * 40),
    ):
        invalid_token = token_for({**claims, name: value})
        invalid = run(invalid_token)
        assert invalid.returncode != 0
        assert invalid_token not in invalid.stdout + invalid.stderr
    malformed_json = ".".join(
        (
            segment({"alg": "RS256"}).decode(),
            base64.urlsafe_b64encode(b"not JSON").rstrip(b"=").decode(),
            segment("signature").decode(),
        )
    )
    for malformed in (
        "not-a-jwt",
        "a!.e30.signature",
        "a.e30.signature",
        malformed_json,
    ):
        invalid = run(malformed)
        assert invalid.returncode != 0
        assert malformed not in invalid.stdout + invalid.stderr
    assert run(token_for(claims), "A" * 40).returncode != 0


def test_development_oidc_proof_schema_rejects_extra_fields_and_stale_sha():
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    deploy_source = _workflow_run_source(jobs["deploy"])
    match = re.search(
        r'jq -e --arg commit "\$GITHUB_SHA" \'\n(.*?)\n\' "\$PROOF"',
        deploy_source,
        flags=re.DOTALL,
    )
    assert match is not None
    schema = match.group(1)
    sha = "a" * 40
    proof = {
        "account": "903859731897",
        "commit_sha": sha,
        "environment": "development",
        "proof": "protected-main-oidc",
        "ref": "refs/heads/main",
        "repository": "rhprasad0/nova-toll-budget-agent",
    }

    def passes(value: Mapping[str, object], commit: str = sha) -> bool:
        result = subprocess.run(
            ["jq", "-e", "--arg", "commit", commit, schema],
            input=json.dumps(value),
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    assert passes(proof)
    assert not passes({**proof, "extra": "rejected"})
    assert not passes({**proof, "commit_sha": "b" * 40})
    assert not passes(proof, "b" * 40)


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
    assert by_sid["PassTimedChecksSchedulerRole"]["actions"] == ["iam:PassRole"]
    assert by_sid["PassTimedChecksSchedulerRole"]["resources"] == [
        "arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-timed-checks-scheduler-dev"
    ]
    assert by_sid["PassTimedChecksSchedulerRole"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "iam:PassedToService",
            "values": ["scheduler.amazonaws.com"],
        }
    ]
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
        "iam:PutRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
    } & set(all_actions)
    assert {
        cast(str, statement["sid"]): cast(list[str], statement["actions"])
        for statement in statements
        if any(
            action.startswith("iam:")
            for action in cast(list[str], statement["actions"])
        )
    } == {
        "ReadPreprovisionedApplicationRoles": [
            "iam:GetRole",
            "iam:GetRolePolicy",
            "iam:ListAttachedRolePolicies",
            "iam:ListRolePolicies",
            "iam:ListRoleTags",
        ],
        "ReadRetiredUsagePublisherIam": [
            "iam:GetRole",
            "iam:GetRolePolicy",
            "iam:ListAttachedRolePolicies",
            "iam:ListRolePolicies",
            "iam:ListRoleTags",
        ],
        "PassExistingAgentCoreRuntimeRole": ["iam:PassRole"],
        "PassTimedChecksSchedulerRole": ["iam:PassRole"],
    }
    temporary_sids = {
        "RetireUsagePublisherIam",
        "RetireUsagePublisherLambda",
        "RetireUsagePublisherEvents",
        "RetireUsagePublisherAlarms",
        "RetireAgentUsageRollupIam",
        "RetireAgentUsageRollupLambda",
        "RetireAgentUsageRollupEvents",
        "RetireAgentUsageRollupAlarms",
        "RetireAgentReportsWafLogging",
    }
    assert not temporary_sids & by_sid.keys()
    assert not {
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "lambda:RemovePermission",
        "events:DeleteRule",
        "events:RemoveTargets",
        "cloudwatch:DeleteAlarms",
        "wafv2:DeleteLoggingConfiguration",
    } & set(all_actions)
    assert by_sid["ReadRetiredUsagePublisherLambda"]["actions"] == [
        "lambda:GetAlias",
        "lambda:GetFunction",
        "lambda:GetFunctionCodeSigningConfig",
        "lambda:GetFunctionConfiguration",
        "lambda:GetFunctionEventInvokeConfig",
        "lambda:GetFunctionUrlConfig",
        "lambda:GetPolicy",
        "lambda:GetProvisionedConcurrencyConfig",
        "lambda:ListAliases",
        "lambda:ListProvisionedConcurrencyConfigs",
        "lambda:ListTags",
        "lambda:ListVersionsByFunction",
    ]
    assert by_sid["ReadRetiredUsagePublisherEvents"]["actions"] == [
        "events:DescribeRule",
        "events:ListTagsForResource",
        "events:ListTargetsByRule",
    ]
    assert by_sid["ReadRetiredUsagePublisherAlarms"]["actions"] == [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:ListTagsForResource",
    ]
    assert by_sid["ReadRetiredUsagePublisherIam"]["resources"] == [
        "local.development_delivery_usage_publisher_role_arn"
    ]
    assert by_sid["ReadRetiredUsagePublisherLambda"]["resources"] == [
        "local.development_delivery_usage_publisher_lambda_arn"
    ]
    assert by_sid["ReadRetiredUsagePublisherEvents"]["resources"] == [
        "local.development_delivery_usage_publisher_rule_arn"
    ]
    assert by_sid["ReadRetiredUsagePublisherAlarms"]["resources"] == [
        "local.development_delivery_usage_publisher_alarm_arns"
    ]
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
    assert not {"iam:AttachRolePolicy", "iam:DetachRolePolicy"} & set(all_actions)
    assert by_sid["PassExistingAgentCoreRuntimeRole"]["resources"] == [
        "arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-agentcore-runtime-dev"
    ]
    assert by_sid["PassExistingAgentCoreRuntimeRole"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "iam:PassedToService",
            "values": ["bedrock-agentcore.amazonaws.com"],
        }
    ]
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
        "ReadApplicationKmsAliases",
    }
    for sid in wildcard_statements:
        conditions = cast(list[dict[str, object]], by_sid[sid]["conditions"])
        assert any(
            condition["variable"] == "aws:RequestedRegion" for condition in conditions
        )

    assert "events:ListTagsForResource" in cast(
        list[str], by_sid["ManageApplicationEventRules"]["actions"]
    )
    assert "events:RemoveTargets" not in cast(
        list[str], by_sid["ManageApplicationEventRules"]["actions"]
    )
    assert _hcl_strings(
        _hcl_attribute(source, "development_delivery_log_group_arns")
    ) == [
        "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:"
        + name
        for name in (
            "/aws/lambda/toll-v2-pricing-loader-dev",
            "/aws/lambda/toll-v2-report-publisher-dev",
            "/aws/lambda/tollchat-v2-chat-proxy-dev",
            "/aws/lambda/tollchat-v2-usage-publisher-dev",
            "/aws/lambda/nova-toll-v2-timed-checks-dev",
            "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
            "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview",
        )
    ]
    assert by_sid["ManageApplicationMeasurementBucket"]["actions"] == [
        "s3:GetAccelerateConfiguration",
        "s3:GetBucketAcl",
        "s3:GetBucketCORS",
        "s3:GetBucketLocation",
        "s3:GetBucketLogging",
        "s3:GetBucketObjectLockConfiguration",
        "s3:GetBucketOwnershipControls",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketRequestPayment",
        "s3:GetBucketTagging",
        "s3:GetBucketVersioning",
        "s3:GetBucketWebsite",
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:GetReplicationConfiguration",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:ListBucketVersions",
    ]
    assert by_sid["ReadRetainedApplicationAthenaNamedQueries"]["actions"] == [
        "athena:GetNamedQuery",
        "athena:ListTagsForResource",
    ]
    assert by_sid["ReadRetainedApplicationAthenaNamedQueries"]["resources"] == [
        "local.development_delivery_athena_workgroup_arn"
    ]
    assert by_sid["ReadRetainedApplicationAthenaWorkGroup"]["actions"] == [
        "athena:GetWorkGroup",
        "athena:ListNamedQueries",
        "athena:ListTagsForResource",
    ]
    assert by_sid["ReadRetainedApplicationAthenaWorkGroup"]["resources"] == [
        "local.development_delivery_athena_workgroup_arn"
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
    assert by_sid["ReadApplicationKmsAliases"]["actions"] == ["kms:ListAliases"]
    assert by_sid["ReadApplicationKmsAliases"]["resources"] == ["*"]
    assert by_sid["ReadAlertsKeyForTimedChecks"] == {
        "sid": "ReadAlertsKeyForTimedChecks",
        "actions": ["kms:DescribeKey"],
        "resources": ["aws_kms_key.alerts.arn"],
        "conditions": [],
    }
    assert by_sid["ReadRetainedMeasurementKey"]["actions"] == [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GetKeyPolicy",
        "kms:GetKeyRotationStatus",
        "kms:ListResourceTags",
    ]
    assert by_sid["ReadRetainedMeasurementKey"]["resources"] == [
        "local.development_delivery_measurement_key_arn"
    ]
    assert {
        (condition["variable"], tuple(cast(list[str], condition["values"])))
        for condition in cast(
            list[dict[str, object]], by_sid["ReadRetainedMeasurementKey"]["conditions"]
        )
    } == {
        ("aws:ResourceTag/environment", ("development",)),
        ("aws:ResourceTag/version", ("v2",)),
    }
    assert re.search(
        r'sid\s*=\s*"ReadApplicationKmsAliases".*?test\s*=\s*"StringEquals"'
        r'.*?variable\s*=\s*"aws:RequestedRegion"'
        r".*?values\s*=\s*\[local\.development_delivery_region\]",
        source,
        re.DOTALL,
    )
    bucket_reads = {
        "s3:GetAccelerateConfiguration",
        "s3:GetBucketCORS",
        "s3:GetBucketLogging",
        "s3:GetBucketObjectLockConfiguration",
        "s3:GetBucketRequestPayment",
        "s3:GetBucketWebsite",
        "s3:GetReplicationConfiguration",
    }
    for sid in ("ManageApplicationSiteBuckets", "ManageApplicationMeasurementBucket"):
        assert bucket_reads <= set(cast(list[str], by_sid[sid]["actions"]))
    assert not {
        "s3:DeleteObject",
        "s3:PutBucketVersioning",
        "s3:PutLifecycleConfiguration",
    } & set(cast(list[str], by_sid["ManageApplicationSiteBuckets"]["actions"]))
    object_scopes = {
        "ManageApplicationSiteBuckets": [
            "local.development_delivery_site_bucket_arn",
            "${local.development_delivery_site_bucket_arn}/*",
        ],
        "ReadRetainedApplicationMeasurementRegistry": [
            "${local.development_delivery_measurement_bucket_arn}/registry/agent_registry.ndjson",
        ],
        "PublishApplicationArtifacts": [
            "${local.development_delivery_artifact_bucket_arn}/runtime/v2/*",
            "${local.development_delivery_artifact_bucket_arn}/lambda/v2/*",
        ],
    }
    for sid, resources in object_scopes.items():
        if sid == "ReadRetainedApplicationMeasurementRegistry":
            assert set(cast(list[str], by_sid[sid]["actions"])) == {
                "s3:GetObject",
                "s3:GetObjectAttributes",
                "s3:GetObjectTagging",
                "s3:GetObjectVersion",
            }
        else:
            assert {"s3:GetObjectTagging", "s3:PutObjectTagging"} <= set(
                cast(list[str], by_sid[sid]["actions"])
            )
        assert by_sid[sid]["resources"] == resources
    assert "lambda:GetFunctionCodeSigningConfig" in cast(
        list[str], by_sid["ReadApplicationLambdaFunctions"]["actions"]
    )
    assert by_sid["ReadManagedCloudFrontPolicy"]["resources"] == [
        "arn:aws:cloudfront::${local.development_delivery_account_id}:cache-policy/4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-request-policy/b689b0a8-53d0-40ab-baf2-68738e2966ac",
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
    assert "athena:DeleteNamedQuery" not in all_actions
    assert "UpdateNamedQuery" not in all_actions
    assert re.search(r'development_delivery_api_id\s*=\s*"ocw8sg0wlb"', source)
    assert re.search(r"guardrail/vdyqrh31xgca", source)
    assert re.search(r"runtime/nova_toll_v2_development-Y69XBf88Bl", source)
    assert "local.development_delivery_application_key_arns" in source
    assert "development_delivery_athena_workgroup_arn" in source
    assert "development_delivery_waf_acl_arn" not in source
    assert (
        "global/webacl/tollchat-v2-public-chat-dev/250c4d9a-abcd-4bdf-861c-b2b10549a770"
        not in source
    )
    assert "security-group/*" not in source
    assert "security-group-rule/*" not in source
    assert "vpc/*" not in source
    forbidden_mutations = {
        "iam:CreateRole",
        "iam:PutRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
        "bedrock-agentcore:CreateAgentRuntime",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint",
        "bedrock-agentcore:DeleteAgentRuntime",
        "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
        "bedrock-agentcore:PutResourcePolicy",
        "bedrock-agentcore:DeleteResourcePolicy",
        "lambda:AddPermission",
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
        "timed_checks.tf": TIMED_CHECKS_TF,
    }
    role_names = {
        "main.tf": ("loader", "timed_checks", "publisher", "publisher_scheduler"),
        "agentcore.tf": ("tollchat_runtime", "tollchat_proxy"),
        "site.tf": (),
        "agent_measurement.tf": (),
        "timed_checks.tf": ("timed_checks_lambda", "timed_checks_scheduler"),
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
        (
            "if: github.ref == 'refs/heads/main'",
            "if: github.ref == 'refs/heads/release'",
        ),
        (
            "if: vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && github.triggering_actor == github.actor",
            "if: github.triggering_actor == github.actor",
        ),
        (
            "if: vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && github.triggering_actor == github.actor",
            "if: vars.DEVELOPMENT_DELIVERY_ENABLED == 'true'",
        ),
        (
            "&& github.triggering_actor == github.actor",
            "|| github.triggering_actor == github.actor",
        ),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == 'owner'",
        ),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == github.actor && github.actor_id == '91573985'",
        ),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:evil/fork:environment:development",
        ),
        (
            '"repository": "rhprasad0/nova-toll-budget-agent"',
            '"repository": "evil/fork"',
        ),
        ("backend.development.hcl", "backend.production.hcl"),
        ("build/loader.zip", "build/placeholder.zip"),
        ('version: "0.12.5"', "version: latest"),
        ('terraform_version: "1.15.8"', "terraform_version: latest"),
        (
            "${{ needs.oidc-proof.outputs.artifact_id }}",
            "protected-main-oidc-proof",
        ),
        ('python-version: "3.13"', ""),
        ('python-version: "3.13"', 'python-version: "3.12"'),
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
            "role/nova-toll-v2-agentcore-runtime-dev",
            "role/nova-toll-v2-development-delivery",
        ),
        ("role/nova-toll-v2-agentcore-runtime-dev", "role/unrelated-runtime-dev"),
        ("bedrock-agentcore.amazonaws.com", "lambda.amazonaws.com"),
        ("iam:PassedToService", "aws:RequestedRegion"),
    ):
        _must_reject_after_marker(
            _assert_development_delivery_state_and_application_policy,
            FOUNDATION_IAM,
            'sid = "PassExistingAgentCoreRuntimeRole"',
            original,
            replacement,
        )

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
            'sid = "ReadRetainedApplicationAthenaNamedQueries"',
            "local.development_delivery_athena_workgroup_arn",
            '"arn:aws:athena:${local.development_delivery_region}:${local.development_delivery_account_id}:workgroup/*"',
        ),
    ):
        _must_reject_after_marker(
            _assert_development_delivery_state_and_application_policy,
            FOUNDATION_IAM,
            marker,
            original,
            replacement,
        )


DEVELOPMENT_PLAN_SIDS = [
    "ListDevelopmentState",
    "ReadDevelopmentState",
    "DecryptDevelopmentState",
    "ReadPreprovisionedApplicationRoles",
    "ReadApplicationLambdaFunctions",
    "ReadApplicationQueues",
    "ReadApplicationQueueUrls",
    "ReadApplicationEventRules",
    "ReadRetainedRollupEventRule",
    "ReadApplicationLogs",
    "ReadRetainedRollupLogGroup",
    "DescribeApplicationLogPolicies",
    "DescribeApplicationLogGroups",
    "ReadApplicationAlarms",
    "ReadRetainedRollupAlarms",
    "DescribeApplicationNetworking",
    "ReadApplicationSiteBucket",
    "ReadApplicationMeasurementBucket",
    "ReadRetainedApplicationMeasurementRegistry",
    "ReadApplicationArtifacts",
    "ReadApplicationArtifactBucket",
    "ReadApplicationKmsKeys",
    "ReadRetainedMeasurementKey",
    "ReadApplicationKmsAliases",
    "ReadApplicationSessions",
    "ReadRetainedApplicationCatalog",
    "ReadRetainedApplicationAthenaNamedQueries",
    "ReadRetainedApplicationAthenaWorkGroup",
    "ListApplicationAthenaWorkGroups",
    "ReadApplicationSchedules",
    "ReadRetiredUsagePublisherIam",
    "ReadRetiredUsagePublisherLambda",
    "ReadRetiredUsagePublisherEvents",
    "ReadRetiredUsagePublisherAlarms",
    "ReadApplicationGuardrail",
    "ReadApplicationAgentCore",
    "ReadApplicationApiGateway",
    "ReadApplicationCloudFrontFunctions",
    "ReadApplicationCloudFront",
    "ReadManagedCloudFrontPolicies",
    "ReadManagedCloudFrontPolicy",
    "ReadApplicationWaf",
    "ReadDevelopmentCertificate",
    "ReadAlertsKeyForTimedChecks",
]

_NO_PLAN_CONDITIONS = ()
_REGIONAL_PLAN_CONDITIONS = (("StringEquals", "aws:RequestedRegion", ("us-east-1",)),)
_KMS_PLAN_CONDITIONS = (
    ("StringEquals", "aws:ResourceTag/environment", ("development",)),
    ("StringEquals", "aws:ResourceTag/version", ("v2",)),
)
_LAMBDA_READ_ACTIONS = (
    "lambda:GetAlias",
    "lambda:GetFunction",
    "lambda:GetFunctionCodeSigningConfig",
    "lambda:GetFunctionConfiguration",
    "lambda:GetFunctionEventInvokeConfig",
    "lambda:GetFunctionUrlConfig",
    "lambda:GetPolicy",
    "lambda:GetProvisionedConcurrencyConfig",
    "lambda:ListAliases",
    "lambda:ListProvisionedConcurrencyConfigs",
    "lambda:ListTags",
    "lambda:ListVersionsByFunction",
)
_EVENT_READ_ACTIONS = (
    "events:DescribeRule",
    "events:ListTagsForResource",
    "events:ListTargetsByRule",
)
_ALARM_READ_ACTIONS = ("cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource")
_IAM_READ_ACTIONS = (
    "iam:GetRole",
    "iam:GetRolePolicy",
    "iam:ListAttachedRolePolicies",
    "iam:ListInstanceProfilesForRole",
    "iam:ListRolePolicies",
    "iam:ListRoleTags",
)

DEVELOPMENT_PLAN_REFRESH_TUPLES = {
    "ReadPreprovisionedApplicationRoles": (
        _IAM_READ_ACTIONS,
        ("local.development_delivery_role_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationLambdaFunctions": (
        _LAMBDA_READ_ACTIONS,
        (
            "concat(local.development_delivery_lambda_resources, local.development_delivery_legacy_rollup_lambda_resources)",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationQueues": (
        ("sqs:GetQueueAttributes", "sqs:ListQueueTags"),
        ("local.development_delivery_queue_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationQueueUrls": (
        ("sqs:GetQueueUrl",),
        ("local.development_delivery_queue_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationEventRules": (
        _EVENT_READ_ACTIONS,
        ("local.development_delivery_event_rule_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedRollupEventRule": (
        _EVENT_READ_ACTIONS,
        ("local.development_delivery_legacy_rollup_event_rule_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationLogs": (
        ("logs:DescribeMetricFilters", "logs:ListTagsForResource"),
        ("local.development_delivery_log_group_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedRollupLogGroup": (
        ("logs:DescribeMetricFilters", "logs:ListTagsForResource"),
        ("local.development_delivery_legacy_rollup_log_group_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "DescribeApplicationLogPolicies": (
        ("logs:DescribeResourcePolicies",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "DescribeApplicationLogGroups": (
        ("logs:DescribeLogGroups",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadApplicationAlarms": (
        _ALARM_READ_ACTIONS,
        ("local.development_delivery_alarm_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedRollupAlarms": (
        _ALARM_READ_ACTIONS,
        ("local.development_delivery_legacy_rollup_alarm_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "DescribeApplicationNetworking": (
        (
            "ec2:DescribePrefixLists",
            "ec2:DescribeSecurityGroupRules",
            "ec2:DescribeSecurityGroups",
            "ec2:DescribeSubnets",
            "ec2:DescribeVpcs",
        ),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadApplicationSiteBucket": (
        (
            "s3:GetAccelerateConfiguration",
            "s3:GetBucketAcl",
            "s3:GetBucketCORS",
            "s3:GetBucketLocation",
            "s3:GetBucketLogging",
            "s3:GetBucketObjectLockConfiguration",
            "s3:GetBucketOwnershipControls",
            "s3:GetBucketPolicy",
            "s3:GetBucketPublicAccessBlock",
            "s3:GetBucketRequestPayment",
            "s3:GetBucketTagging",
            "s3:GetBucketVersioning",
            "s3:GetBucketWebsite",
            "s3:GetEncryptionConfiguration",
            "s3:GetLifecycleConfiguration",
            "s3:GetObject",
            "s3:GetObjectAttributes",
            "s3:GetObjectTagging",
            "s3:GetObjectVersion",
            "s3:GetReplicationConfiguration",
            "s3:ListBucket",
            "s3:ListBucketMultipartUploads",
            "s3:ListBucketVersions",
        ),
        (
            "local.development_delivery_site_bucket_arn",
            "${local.development_delivery_site_bucket_arn}/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationMeasurementBucket": (
        (
            "s3:GetAccelerateConfiguration",
            "s3:GetBucketAcl",
            "s3:GetBucketCORS",
            "s3:GetBucketLocation",
            "s3:GetBucketLogging",
            "s3:GetBucketObjectLockConfiguration",
            "s3:GetBucketOwnershipControls",
            "s3:GetBucketPolicy",
            "s3:GetBucketPublicAccessBlock",
            "s3:GetBucketRequestPayment",
            "s3:GetBucketTagging",
            "s3:GetBucketVersioning",
            "s3:GetBucketWebsite",
            "s3:GetEncryptionConfiguration",
            "s3:GetLifecycleConfiguration",
            "s3:GetReplicationConfiguration",
            "s3:ListBucket",
            "s3:ListBucketMultipartUploads",
            "s3:ListBucketVersions",
        ),
        ("local.development_delivery_measurement_bucket_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationMeasurementRegistry": (
        (
            "s3:GetObject",
            "s3:GetObjectAttributes",
            "s3:GetObjectTagging",
            "s3:GetObjectVersion",
        ),
        (
            "${local.development_delivery_measurement_bucket_arn}/registry/agent_registry.ndjson",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationArtifacts": (
        (
            "s3:GetObject",
            "s3:GetObjectAttributes",
            "s3:GetObjectTagging",
            "s3:GetObjectVersion",
            "s3:ListBucketMultipartUploads",
            "s3:ListMultipartUploadParts",
        ),
        (
            "${local.development_delivery_artifact_bucket_arn}/runtime/v2/*",
            "${local.development_delivery_artifact_bucket_arn}/lambda/v2/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationArtifactBucket": (
        ("s3:GetBucketLocation",),
        ("local.development_delivery_artifact_bucket_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationKmsKeys": (
        (
            "kms:DescribeKey",
            "kms:GetKeyPolicy",
            "kms:GetKeyRotationStatus",
            "kms:ListResourceTags",
        ),
        ("local.development_delivery_application_key_arns",),
        _KMS_PLAN_CONDITIONS,
    ),
    "ReadRetainedMeasurementKey": (
        (
            "kms:DescribeKey",
            "kms:GetKeyPolicy",
            "kms:GetKeyRotationStatus",
            "kms:ListResourceTags",
        ),
        ("local.development_delivery_measurement_key_arn",),
        _KMS_PLAN_CONDITIONS,
    ),
    "ReadApplicationKmsAliases": (
        ("kms:ListAliases",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadApplicationSessions": (
        (
            "dynamodb:DescribeContinuousBackups",
            "dynamodb:DescribeTable",
            "dynamodb:DescribeTimeToLive",
            "dynamodb:ListTagsOfResource",
        ),
        (
            "arn:aws:dynamodb:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat-v2-anonymous-sessions-dev",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationCatalog": (
        (
            "glue:GetDatabase",
            "glue:GetDatabases",
            "glue:GetTable",
            "glue:GetTables",
            "glue:GetTags",
        ),
        (
            "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:catalog",
            "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:database/tollchat_agent_reports_development",
            "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat_agent_reports_development/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationAthenaNamedQueries": (
        ("athena:GetNamedQuery", "athena:ListTagsForResource"),
        ("local.development_delivery_athena_workgroup_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationAthenaWorkGroup": (
        (
            "athena:GetWorkGroup",
            "athena:ListNamedQueries",
            "athena:ListTagsForResource",
        ),
        ("local.development_delivery_athena_workgroup_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ListApplicationAthenaWorkGroups": (
        ("athena:ListWorkGroups",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadApplicationSchedules": (
        ("scheduler:GetSchedule", "scheduler:ListTagsForResource"),
        (
            'concat([ "arn:aws:scheduler:${local.development_delivery_region}:${local.development_delivery_account_id}:schedule/*/toll-v2-report-publisher-dev", "arn:aws:scheduler:${local.development_delivery_region}:${local.development_delivery_account_id}:schedule-group/default", ], local.development_delivery_timed_schedule_arns)',
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherIam": (
        _IAM_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_role_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherLambda": (
        _LAMBDA_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_lambda_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherEvents": (
        _EVENT_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_rule_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherAlarms": (
        _ALARM_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_alarm_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationGuardrail": (
        ("bedrock:GetGuardrail", "bedrock:ListTagsForResource"),
        ("local.development_delivery_guardrail_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationAgentCore": (
        (
            "bedrock-agentcore:GetAgentRuntime",
            "bedrock-agentcore:GetAgentRuntimeEndpoint",
            "bedrock-agentcore:GetResourcePolicy",
            "bedrock-agentcore:ListTagsForResource",
        ),
        (
            "local.development_delivery_agentcore_runtime_arn",
            "local.development_delivery_agentcore_endpoint_arn",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationApiGateway": (
        ("apigateway:GET",),
        (
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}",
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationCloudFrontFunctions": (
        (
            "cloudfront:DescribeFunction",
            "cloudfront:GetFunction",
            "cloudfront:ListTagsForResource",
        ),
        (
            "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-chat-routes-dev",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-report-routes-dev",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationCloudFront": (
        (
            "cloudfront:GetDistribution",
            "cloudfront:GetDistributionConfig",
            "cloudfront:GetOriginAccessControl",
            "cloudfront:GetResponseHeadersPolicy",
            "cloudfront:ListTagsForResource",
        ),
        (
            "local.development_delivery_distribution_arn",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-access-control/*",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:response-headers-policy/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadManagedCloudFrontPolicies": (
        ("cloudfront:ListCachePolicies", "cloudfront:ListOriginRequestPolicies"),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadManagedCloudFrontPolicy": (
        ("cloudfront:GetCachePolicy", "cloudfront:GetOriginRequestPolicy"),
        (
            "arn:aws:cloudfront::${local.development_delivery_account_id}:cache-policy/4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-request-policy/b689b0a8-53d0-40ab-baf2-68738e2966ac",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationWaf": (
        (
            "wafv2:GetLoggingConfiguration",
            "wafv2:GetWebACL",
            "wafv2:ListTagsForResource",
        ),
        (
            "arn:aws:wafv2:${local.development_delivery_region}:${local.development_delivery_account_id}:global/webacl/tollchat-v2-public-chat-dev/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadDevelopmentCertificate": (
        ("acm:DescribeCertificate", "acm:ListTagsForCertificate"),
        (
            "arn:aws:acm:${local.development_delivery_region}:${local.development_delivery_account_id}:certificate/0c2c3578-fee5-41b3-9985-ea7465c16a20",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadAlertsKeyForTimedChecks": (
        ("kms:DescribeKey",),
        ("aws_kms_key.alerts.arn",),
        _NO_PLAN_CONDITIONS,
    ),
}


def _assert_development_plan_trust(source: str) -> None:
    statements = _parsed_policy_document(source, "development_plan_assume")
    assert len(statements) == 1
    assert statements[0] == {
        "sid": "GitHubDevelopmentPlanWorkflow",
        "actions": ["sts:AssumeRoleWithWebIdentity"],
        "resources": [],
        "conditions": [
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:aud",
                "values": ["sts.amazonaws.com"],
            },
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:sub",
                "values": [
                    "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development-plan"
                ],
            },
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:repository",
                "values": ["rhprasad0/nova-toll-budget-agent"],
            },
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:job_workflow_ref",
                "values": [
                    "rhprasad0/nova-toll-budget-agent/.github/workflows/v2-development-plan.yml@refs/heads/main"
                ],
            },
        ],
    }
    principal = _hcl_named_blocks(
        terraform_block(
            source, 'data "aws_iam_policy_document" "development_plan_assume"'
        ),
        "principals",
    )
    assert len(principal) == 1
    assert _hcl_scalar(principal[0], "type") == "Federated"
    assert _hcl_attribute(principal[0], "identifiers") == (
        "aws_iam_openid_connect_provider.github.arn"
    )
    assert "StringLike" not in terraform_block(
        source, 'data "aws_iam_policy_document" "development_plan_assume"'
    )


def _assert_development_plan_policy(source: str) -> None:
    policy_block = terraform_block(
        source, 'data "aws_iam_policy_document" "development_plan"'
    )
    statements = _parsed_policy_document(source, "development_plan")
    assert [statement["sid"] for statement in statements] == DEVELOPMENT_PLAN_SIDS
    assert len(statements) == 44
    by_sid = _policy_by_sid(statements)
    parsed_tuples = _parsed_policy_tuple_map(source, "development_plan")
    assert set(parsed_tuples) == set(DEVELOPMENT_PLAN_SIDS)
    for sid in DEVELOPMENT_PLAN_SIDS[3:]:
        assert parsed_tuples[sid] == DEVELOPMENT_PLAN_REFRESH_TUPLES[sid]

    assert by_sid["ListDevelopmentState"] == {
        "sid": "ListDevelopmentState",
        "actions": ["s3:ListBucket"],
        "resources": ["aws_s3_bucket.tfstate.arn"],
        "conditions": [
            {
                "test": "StringEquals",
                "variable": "s3:prefix",
                "values": [
                    "nova-toll/development/terraform.tfstate",
                    "nova-toll/v2/development/terraform.tfstate",
                ],
            }
        ],
    }
    assert by_sid["ReadDevelopmentState"]["actions"] == ["s3:GetObject"]
    assert by_sid["ReadDevelopmentState"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
    ]
    assert by_sid["DecryptDevelopmentState"]["actions"] == ["kms:Decrypt"]
    assert by_sid["DecryptDevelopmentState"]["resources"] == ["aws_kms_key.tfstate.arn"]
    assert by_sid["DecryptDevelopmentState"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "kms:ViaService",
            "values": ["s3.us-east-1.amazonaws.com"],
        },
        {
            "test": "StringEquals",
            "variable": "kms:EncryptionContext:aws:s3:arn",
            "values": [
                "${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate",
                "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
            ],
        },
    ]
    assert set(
        cast(list[str], by_sid["ReadPreprovisionedApplicationRoles"]["actions"])
    ) == {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
    }
    assert "iam:ListInstanceProfilesForRole" in cast(
        list[str], by_sid["ReadRetiredUsagePublisherIam"]["actions"]
    )
    assert by_sid["ReadPreprovisionedApplicationRoles"]["resources"] == [
        "local.development_delivery_role_arns"
    ]
    assert by_sid["ReadRetiredUsagePublisherIam"]["resources"] == [
        "local.development_delivery_usage_publisher_role_arn"
    ]

    wildcard_sids = {
        cast(str, statement["sid"])
        for statement in statements
        if cast(list[str], statement["resources"]) == ["*"]
    }
    assert wildcard_sids == {
        "DescribeApplicationLogPolicies",
        "DescribeApplicationLogGroups",
        "DescribeApplicationNetworking",
        "ReadApplicationKmsAliases",
        "ListApplicationAthenaWorkGroups",
        "ReadManagedCloudFrontPolicies",
    }
    for sid in wildcard_sids:
        assert by_sid[sid]["conditions"] == [
            {
                "test": "StringEquals",
                "variable": "aws:RequestedRegion",
                "values": [],
            }
        ]

    all_actions = {
        action
        for statement in statements
        for action in cast(list[str], statement["actions"])
    }
    assert not any(action.endswith(":*") or action == "*" for action in all_actions)
    assert (
        not {
            "s3:PutObject",
            "s3:DeleteObject",
            "kms:GenerateDataKey",
            "iam:PassRole",
            "iam:SimulatePrincipalPolicy",
        }
        & all_actions
    )
    assert not any(
        action.startswith(("ssm:", "secretsmanager:")) for action in all_actions
    )
    assert ".tflock" not in policy_block
    assert "920534282028" not in policy_block
    assert "production" not in policy_block.lower()

    role = terraform_block(source, 'resource "aws_iam_role" "development_plan"')
    assert re.search(
        r'(?m)^\s*count\s*=\s*var.environment == "development" \? 1 : 0\s*$', role
    )
    assert re.search(r"(?m)^\s*max_session_duration\s*=\s*3600\s*$", role)
    for resource_type in (
        'resource "aws_iam_policy" "development_plan"',
        'resource "aws_iam_role_policy_attachment" "development_plan"',
    ):
        resource = terraform_block(source, resource_type)
        assert 'var.environment == "development" ?' in resource
        assert "local.development_plan_policy_documents" in resource


def test_development_plan_iam_is_exact_and_adversarial_mutations_fail():
    _assert_development_plan_trust(FOUNDATION_IAM)
    _assert_development_plan_policy(FOUNDATION_IAM)
    for original, replacement in (
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development-plan",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
        ),
        ("rhprasad0/nova-toll-budget-agent", "evil/fork"),
        (
            "v2-development-plan.yml@refs/heads/main",
            "v2-development-plan.yml@refs/heads/release",
        ),
        ("s3.us-east-1.amazonaws.com", "s3.us-west-2.amazonaws.com"),
        ("s3:ListBucket", "s3:PutObject"),
        ("kms:Decrypt", "kms:GenerateDataKey"),
        ("iam:ListInstanceProfilesForRole", "iam:ListRoles"),
    ):
        assertion = (
            _assert_development_plan_trust
            if original
            in {
                "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development-plan",
                "rhprasad0/nova-toll-budget-agent",
                "v2-development-plan.yml@refs/heads/main",
            }
            else _assert_development_plan_policy
        )
        marker = (
            'data "aws_iam_policy_document" "development_plan_assume"'
            if assertion is _assert_development_plan_trust
            else 'data "aws_iam_policy_document" "development_plan"'
        )
        _must_reject_after_marker(
            assertion, FOUNDATION_IAM, marker, original, replacement
        )
    for original, replacement in (
        ("apigateway:GET", "apigateway:POST"),
        (
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}",
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/*",
        ),
    ):
        _must_reject_after_marker(
            _assert_development_plan_policy,
            FOUNDATION_IAM,
            'data "aws_iam_policy_document" "development_plan"',
            original,
            replacement,
        )


def test_development_plan_policy_set_is_deterministic_and_bounded():
    documents, aggregate = _terraform_rendered_development_plan_policies()
    assert set(documents) == {
        "state",
        "compute",
        "observability",
        "storage",
        "data",
        "runtime",
        "edge",
    }
    assert len(aggregate) == 44
    assert [
        statement
        for statement in aggregate
        if statement["Sid"] == "ReadAlertsKeyForTimedChecks"
    ] == [
        {
            "Action": "kms:DescribeKey",
            "Effect": "Allow",
            "Resource": "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111",
            "Sid": "ReadAlertsKeyForTimedChecks",
        }
    ]
    rendered_statements: list[dict[str, object]] = []
    for key in (
        "state",
        "compute",
        "observability",
        "storage",
        "data",
        "runtime",
        "edge",
    ):
        policy = documents[key]
        statements = policy.get("Statement")
        assert isinstance(statements, list)
        rendered_statements.extend(cast(list[dict[str, object]], statements))
        assert len(json.dumps(policy, separators=(",", ":")).encode("utf-8")) <= 6_144
    assert rendered_statements == aggregate
    assert [statement["Sid"] for statement in aggregate] == DEVELOPMENT_PLAN_SIDS
    assert len({statement["Sid"] for statement in aggregate}) == len(aggregate)


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
    pass_role = by_sid["PassExistingAgentCoreRuntimeRole"]
    assert pass_role["actions"] == ["iam:PassRole"]
    assert pass_role["resources"] == [
        "arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-agentcore-runtime-dev"
    ]
    assert "lambda:UpdateFunctionConfiguration" not in all_actions
    assert "athena:DeleteNamedQuery" not in all_actions
    assert (
        not {
            "athena:CreateNamedQuery",
            "athena:UpdateNamedQuery",
        }
        & all_actions
    )
    temporary_sids = {
        "RetireUsagePublisherIam",
        "RetireUsagePublisherLambda",
        "RetireUsagePublisherEvents",
        "RetireUsagePublisherAlarms",
        "RetireAgentUsageRollupIam",
        "RetireAgentUsageRollupLambda",
        "RetireAgentUsageRollupEvents",
        "RetireAgentUsageRollupAlarms",
        "RetireAgentReportsWafLogging",
    }
    assert not temporary_sids & by_sid.keys()
    assert (
        not {
            "iam:DeleteRole",
            "iam:DeleteRolePolicy",
            "lambda:RemovePermission",
            "events:DeleteRule",
            "events:RemoveTargets",
            "cloudwatch:DeleteAlarms",
            "wafv2:DeleteLoggingConfiguration",
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
    for action in (
        "s3:DeleteObject",
        "s3:PutBucketVersioning",
        "s3:PutLifecycleConfiguration",
    ):
        assert not _statement_allows(
            by_sid["ManageApplicationSiteBuckets"],
            action,
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
    assert len(statements) == 54
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
            22,
            [
                "ManageApplicationEventRules",
                "ReadRetainedRollupEventRule",
                "ManageApplicationLogs",
                "ReadRetainedRollupLogGroup",
                "DescribeApplicationLogPolicies",
                "DescribeApplicationLogGroups",
                "ManageApplicationAlarms",
                "ReadRetainedRollupAlarms",
                "DescribeApplicationNetworking",
            ],
        ),
        "storage": (
            22,
            27,
            [
                "ManageApplicationSiteBuckets",
                "ManageApplicationMeasurementBucket",
                "ReadRetainedApplicationMeasurementRegistry",
                "PublishApplicationArtifacts",
                "ReadApplicationArtifactBucket",
            ],
        ),
        "data": (
            27,
            35,
            [
                "UseApplicationKmsKeys",
                "ReadRetainedMeasurementKey",
                "ReadApplicationKmsAliases",
                "ManageApplicationSessions",
                "ReadRetainedApplicationCatalog",
                "ReadRetainedApplicationAthenaNamedQueries",
                "ReadRetainedApplicationAthenaWorkGroup",
                "ListApplicationAthenaWorkGroups",
            ],
        ),
        "runtime": (
            35,
            45,
            [
                "ManageApplicationSchedules",
                "PassTimedChecksSchedulerRole",
                "ReadRetiredUsagePublisherIam",
                "ReadRetiredUsagePublisherLambda",
                "ReadRetiredUsagePublisherEvents",
                "ReadRetiredUsagePublisherAlarms",
                "ManageApplicationGuardrail",
                "PublishApplicationGuardrailVersions",
                "ManageApplicationAgentCore",
                "PassExistingAgentCoreRuntimeRole",
            ],
        ),
        "edge": (
            45,
            54,
            [
                "ReadApplicationApiGateway",
                "PublishApplicationApiGatewayDeployments",
                "ManageApplicationCloudFront",
                "ReadApplicationCloudFront",
                "ReadManagedCloudFrontPolicies",
                "ReadManagedCloudFrontPolicy",
                "ManageApplicationWaf",
                "ReadDevelopmentCertificate",
                "ReadAlertsKeyForTimedChecks",
            ],
        ),
    }
    rendered_documents, rendered_aggregate = (
        _terraform_rendered_development_delivery_policies()
    )
    assert len(rendered_documents) <= 10
    assert set(rendered_documents) == set(expected_groups)
    assert len(rendered_aggregate) == len(statements) == 54
    rendered_by_sid = {statement["Sid"]: statement for statement in rendered_aggregate}
    assert rendered_by_sid["ReadApplicationKmsAliases"]["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "us-east-1"}
    }
    assert rendered_by_sid["ReadAlertsKeyForTimedChecks"] == {
        "Action": "kms:DescribeKey",
        "Effect": "Allow",
        "Resource": "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111",
        "Sid": "ReadAlertsKeyForTimedChecks",
    }
    assert rendered_by_sid["PassExistingAgentCoreRuntimeRole"]["Condition"] == {
        "StringEquals": {"iam:PassedToService": "bedrock-agentcore.amazonaws.com"}
    }
    assert rendered_by_sid["PassTimedChecksSchedulerRole"]["Action"] == "iam:PassRole"
    assert rendered_by_sid["PassTimedChecksSchedulerRole"]["Resource"] == (
        "arn:aws:iam::903859731897:role/nova-toll-v2-timed-checks-scheduler-dev"
    )
    assert rendered_by_sid["PassTimedChecksSchedulerRole"]["Condition"] == {
        "StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}
    }
    temporary_sids = {
        "RetireUsagePublisherIam",
        "RetireUsagePublisherLambda",
        "RetireUsagePublisherEvents",
        "RetireUsagePublisherAlarms",
        "RetireAgentUsageRollupIam",
        "RetireAgentUsageRollupLambda",
        "RetireAgentUsageRollupEvents",
        "RetireAgentUsageRollupAlarms",
        "RetireAgentReportsWafLogging",
    }
    assert not temporary_sids & rendered_by_sid.keys()
    rendered_actions = {
        action
        for statement in rendered_aggregate
        for action in cast(
            list[str],
            statement["Action"]
            if isinstance(statement["Action"], list)
            else [cast(str, statement["Action"])],
        )
    }
    assert (
        not {
            "iam:DeleteRole",
            "iam:DeleteRolePolicy",
            "lambda:RemovePermission",
            "events:DeleteRule",
            "events:RemoveTargets",
            "cloudwatch:DeleteAlarms",
            "wafv2:DeleteLoggingConfiguration",
        }
        & rendered_actions
    )
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
    assert "SIMULATION_EXPECTED_COUNT=126" in script
    matrix = script.split('cat >"$SIMULATION_MATRIX" <<EOF\n', 1)[1].split("\nEOF", 1)[
        0
    ]
    assert len(matrix.splitlines()) == 126
    assert "runtime-role-wrong-service|iam:PassRole|" in matrix
    assert "unrelated-runtime-role-pass|iam:PassRole|" in matrix
    assert (
        "ContextKeyName=iam:PassedToService,ContextKeyValues=bedrock-agentcore.amazonaws.com"
        in script
    )
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
    assert "PLAN_GATE_SOURCE" not in script
    assert "PLAN_GATE" not in script
    assert "development-plan-gate.py" not in script
    assert 'python3 "$PLAN_GATE" "$REPRESENTATIVE_PLAN_JSON"' not in script
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
        ("SIMULATION_EXPECTED_COUNT=126", "SIMULATION_EXPECTED_COUNT=1"),
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


def _foundation_plan_validator():
    spec = importlib.util.spec_from_file_location(
        "development_foundation_plan_validator", DEVELOPMENT_FOUNDATION_PLAN_VALIDATOR
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _foundation_change(
    mode: str, address: str, actions: list[str], **change: Any
) -> dict[str, Any]:
    return {
        "mode": mode,
        "address": address,
        "change": {"actions": actions, **change},
    }


def test_development_foundation_plan_validator_accepts_only_exact_replacement():
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
):
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


def test_development_foundation_runbook_shell_blocks_initialize_handoffs():
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
        '"nova-toll-rds-development": "fd7a:115c:a1e0:b1a:0:1:ac1f:e1a2/128"' in source
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


def test_slice_3b3a_route_control_contract_is_fixed_and_least_privilege():
    helper = (
        V2_ROOT / "scripts" / "approve_development_tailscale_route.py"
    ).read_text()
    assert 'SSM_DOCUMENT = "nova-toll-v2-route-control-status-dev"' in helper
    assert "AWS-RunShellScript" not in helper
    assert "--parameters" not in helper
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID" in helper
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_SECRET" in helper
    assert "TS_DEVELOPMENT_OAUTH_CLIENT_ID" not in helper
    assert "TS_DEVELOPMENT_OAUTH_SECRET" not in helper
    assert "type(response_code) is not int" in helper
    assert 'scope": OAUTH_SCOPE' in helper
    assert "len(scope_tokens) != len(REQUIRED_SCOPES)" in helper
    assert "route != EXPECTED_ROUTE" in helper
    assert "current.selected != initial.selected" in helper
    assert "expected_enabled_routes = frozenset" in helper
    assert "post_self_id = read_router_node_id" in helper
    assert "expected_enabled_after" in helper
    assert '"devices:routes:read"' in helper

    for declaration in (
        'data "aws_iam_policy_document" "route_control_assume"',
        'resource "aws_ssm_document" "route_control"',
        'resource "aws_iam_role" "route_control"',
        'data "aws_iam_policy_document" "route_control"',
        'resource "aws_iam_role_policy" "route_control"',
    ):
        assert declaration not in MAIN_TF
        assert declaration in FOUNDATION_TAILSCALE

    trust = FOUNDATION_TAILSCALE.split(
        'data "aws_iam_policy_document" "route_control_assume"', maxsplit=1
    )[1].split('resource "aws_ssm_document" "route_control"', maxsplit=1)[0]
    assert "token.actions.githubusercontent.com:aud" in trust
    assert "token.actions.githubusercontent.com:sub" in trust
    assert (
        'values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"]'
        in trust
    )
    assert "token.actions.githubusercontent.com:job_workflow_ref" not in trust

    document = FOUNDATION_TAILSCALE.split(
        'resource "aws_ssm_document" "route_control"', maxsplit=1
    )[1].split('resource "aws_iam_role" "route_control"', maxsplit=1)[0]
    assert 'count           = var.environment == "development" ? 1 : 0' in document
    assert 'name            = "nova-toll-v2-route-control-status-dev"' in document
    assert "tailscale status --json" in document
    assert "set -eu" in document
    assert "parameters" not in document

    role = FOUNDATION_TAILSCALE.split(
        'resource "aws_iam_role" "route_control"', maxsplit=1
    )[1].split('data "aws_iam_policy_document" "route_control"', maxsplit=1)[0]
    assert 'name               = "nova-toll-v2-route-control-dev"' in role
    assert (
        "assume_role_policy = data.aws_iam_policy_document.route_control_assume[0].json"
        in role
    )

    policy = FOUNDATION_TAILSCALE.split(
        'data "aws_iam_policy_document" "route_control"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "route_control"', maxsplit=1)[0]
    assert "ssm:SendCommand" in policy
    assert "ssm:GetCommandInvocation" in policy
    assert "nova-toll-v2-route-control-status-dev" in policy
    assert "i-0d33b9a9c15db93fc" in policy
    assert "aws:RequestedRegion" in policy
    assert "ssm:GetParameter" not in policy
    assert "rds:" not in policy
    role_policy = FOUNDATION_TAILSCALE.split(
        'resource "aws_iam_role_policy" "route_control"', maxsplit=1
    )[1]
    assert 'name   = "nova-toll-v2-route-control-dev"' in role_policy
    assert "role   = aws_iam_role.route_control[0].id" in role_policy

    assert "TS_DEVELOPMENT_OAUTH_CLIENT_ID" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "TS_DEVELOPMENT_OAUTH_SECRET" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_SECRET" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "nova-toll-v2-route-control-dev" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert DEVELOPMENT_CONNECTIVITY_WORKFLOW.index(
        "TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID"
    ) < DEVELOPMENT_CONNECTIVITY_WORKFLOW.index("nova-toll-v2-timed-checks-dev")
    route_step = DEVELOPMENT_CONNECTIVITY_WORKFLOW.split(
        "- name: Approve development Tailscale route", maxsplit=1
    )[1].split("- uses: aws-actions/configure-aws-credentials", maxsplit=1)[0]
    assert "TS_DEVELOPMENT_OAUTH_" not in route_step
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_" in route_step
    assert "devices:core:read" in DEPLOYMENT
    assert "devices:routes:read" in DEPLOYMENT
    assert "devices:routes" in DEPLOYMENT
    assert "GET /api/v2/tailnet/rhprasad0.github/devices" in DEPLOYMENT
    assert "GET /api/v2/device/<nodeId>/routes" in DEPLOYMENT
    assert "list-supplied route fields are not trusted" in DEPLOYMENT
    assert "irreducible multi-GET sub-request TOCTOU window" in DEPLOYMENT
    assert "devices?fields=all" not in DEPLOYMENT
    assert "auth_keys`-only" in DEPLOYMENT
    assert "list-plus-per-device route reads are not an atomic snapshot" in DEPLOYMENT


def _assert_slice_2b_connectivity_workflow(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    trigger = _workflow_trigger(workflow)
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


def test_slice_2b_connectivity_workflow_is_manual_main_only_and_dev_scoped():
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


def test_slice_3_development_custom_domain_is_explicit_and_production_preserving():
    assert 'variable "enable_development_custom_domain"' in APPLICATION_VARIABLES
    variable = terraform_block(
        APPLICATION_VARIABLES, 'variable "enable_development_custom_domain"'
    )
    assert "default     = false" in variable
    assert 'environment == "development"' in variable
    assert "enable_development_custom_domain = true" in DEVELOPMENT_TFVARS.replace(
        "      ", " "
    )
    assert "development_custom_domain_enabled" in ENVIRONMENT_TF
    assert "https://${local.domains[0]}" in ENVIRONMENT_TF
    assert "-var enable_development_custom_domain=" not in DEVELOPMENT_DELIVERY_WORKFLOW

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
    assert "cloudflare" not in policy.lower()
    statements = _parsed_policy_document(FOUNDATION_IAM, "development_delivery")
    certificate = _policy_by_sid(statements)["ReadDevelopmentCertificate"]
    assert certificate["actions"] == [
        "acm:DescribeCertificate",
        "acm:ListTagsForCertificate",
    ]
    assert certificate["resources"] == [
        "arn:aws:acm:us-east-1:903859731897:certificate/0c2c3578-fee5-41b3-9985-ea7465c16a20"
    ]
    assert [
        action
        for statement in statements
        for action in cast(list[str], statement["actions"])
        if action.startswith("acm:")
    ] == certificate["actions"]


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
        'LEGACY_ALIAS_RELEASED") != "true"',
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
    assert (
        "LEGACY_ALIAS_RELEASED: ${{ inputs.legacy_alias_released }}"
        in FOUNDATION_DNS_WORKFLOW
    )
    assert "alias_attached:" not in FOUNDATION_DNS_WORKFLOW


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
    monkeypatch.setenv("LEGACY_ALIAS_RELEASED", "true")
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


@pytest.mark.parametrize(
    ("released", "certificate", "distribution", "accepted"),
    [
        ("true", "ISSUED", "Deployed", True),
        ("false", "ISSUED", "Deployed", False),
        (None, "ISSUED", "Deployed", False),
        ("", "ISSUED", "Deployed", False),
        ("TRUE", "ISSUED", "Deployed", False),
        ("true", "PENDING_VALIDATION", "Deployed", False),
        ("true", "ISSUED", "InProgress", False),
    ],
)
def test_slice3_dns_cutover_precedes_new_alias_but_requires_legacy_release(
    monkeypatch: pytest.MonkeyPatch,
    released: str | None,
    certificate: str,
    distribution: str,
    accepted: bool,
) -> None:
    _set_dns_inputs(monkeypatch, operation="cutover")
    monkeypatch.delenv("ALIAS_ATTACHED", raising=False)
    if released is None:
        monkeypatch.delenv("LEGACY_ALIAS_RELEASED")
    else:
        monkeypatch.setenv("LEGACY_ALIAS_RELEASED", released)
    monkeypatch.setenv("CERTIFICATE_STATUS", certificate)
    monkeypatch.setenv("CLOUDFRONT_STATUS", distribution)
    mock = _DnsApiMock(zones=[_dns_zone()])
    namespace = _dns_namespace(mock)
    main = cast(Callable[[], object], namespace["main"])
    if accepted:
        main()
        assert len(mock.mutations) == 1
        method, path, payload = mock.mutations[0]
        assert method == "PUT"
        assert path == "zones/" + "a" * 32 + "/dns_records/" + "c" * 32
        assert payload == {
            "name": "dev.tollchat.ai",
            "type": "CNAME",
            "content": "d1wqry4fbd92w5.cloudfront.net",
            "ttl": 1,
            "proxied": False,
        }
    else:
        with pytest.raises(cast(type[Exception], namespace["GateError"])):
            main()
        assert not mock.mutations


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


@pytest.mark.parametrize(
    ("zone_id", "accepted"),
    [("absent", True), ("a" * 32, True), ("f" * 32, False), (None, False)],
)
def test_slice3_dns_zone_scoped_response_allows_only_absent_or_matching_zone_id(
    monkeypatch: pytest.MonkeyPatch, zone_id: str | None, accepted: bool
) -> None:
    _set_dns_inputs(monkeypatch, operation="cutover")
    mock = _DnsApiMock(zones=[_dns_zone()])
    for records in mock.records.values():
        for record in records:
            if zone_id == "absent":
                record.pop("zone_id")
            else:
                record["zone_id"] = zone_id
    namespace = _dns_namespace(mock)
    main = cast(Callable[[], object], namespace["main"])
    if accepted:
        main()
        assert len(mock.mutations) == 1
        assert mock.mutations[0][:2] == (
            "PUT",
            "zones/" + "a" * 32 + "/dns_records/" + "c" * 32,
        )
    else:
        with pytest.raises(cast(type[Exception], namespace["GateError"])):
            main()
        assert not mock.mutations


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("_token.acm-validations.aws", True),
        ("_token.jkddzztszm.acm-validations.aws", True),
        ("_token.extra.route.acm-validations.aws", False),
        ("_token.-route.acm-validations.aws", False),
        ("_token.route-.acm-validations.aws", False),
        ("_token.route..acm-validations.aws", False),
        ("_token.route.acm-validations.aws.evil.test", False),
        ("_token.route.attacker.aws", False),
    ],
)
def test_slice3_dns_accepts_only_bounded_acm_validation_values(
    monkeypatch: pytest.MonkeyPatch, value: str, accepted: bool
) -> None:
    _set_dns_inputs(monkeypatch)
    records = json.loads(os.environ["VALIDATION_RECORDS"])
    records[0]["value"] = value
    monkeypatch.setenv("VALIDATION_RECORDS", json.dumps(records))
    mock = _DnsApiMock(
        zones=[_dns_zone()],
        validation_records=[
            _dns_record("d" * 32, "_validation.dev.tollchat.ai", value, ttl=60)
        ],
    )
    namespace = _dns_namespace(mock)
    main = cast(Callable[[], object], namespace["main"])
    if accepted:
        main()
    else:
        with pytest.raises(cast(type[Exception], namespace["GateError"])):
            main()
    assert not mock.mutations


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
    handoff = DEPLOYMENT.split("##### Exact DNS workflow operations and ordering", 1)[1]
    assert handoff.index("legacy_alias_released=true") < handoff.index(
        "before applying the reviewed development alias"
    )
    recovery = DEPLOYMENT.split("##### Failed-cutover recovery and cleanup gate", 1)[1]
    assert recovery.index("first release") < recovery.index("operation=rollback")
    assert recovery.index("operation=rollback") < recovery.index(
        "restore only the old alias"
    )
    for required in (
        "Slice 3 development custom-domain and DNS handoff",
        "enable_development_custom_domain",
        "production-foundation-dns",
        "GET /accounts/{derived_account_id}/tokens/verify",
        "stage-validation",
        "certificate_status=ISSUED",
        "cloudfront_status=Deployed",
        "legacy_alias_released=true",
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


def test_development_migrations_iam_is_development_only_and_least_privilege():
    assume = _top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_migrations_assume"',
    )
    policy = _top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_migrations"',
    )
    role = _top_level_terraform_block(
        FOUNDATION_IAM,
        'resource "aws_iam_role" "development_migrations"',
    )
    inline = _top_level_terraform_block(
        FOUNDATION_IAM,
        'resource "aws_iam_role_policy" "development_migrations"',
    )
    for block in (assume, policy, role, inline):
        assert re.search(
            r'count\s*=\s*var\.environment == "development" \? 1 : 0', block
        )
    statements = _parsed_policy_document(FOUNDATION_IAM, "development_migrations")
    assert [statement["actions"] for statement in statements] == [
        ["rds:DescribeDBInstances"],
        ["rds-db:connect"],
    ]
    assert all(statement["resources"] for statement in statements)
    assert "aws_db_instance.main.identifier" in policy
    assert "aws_db_instance.main.resource_id" in policy
    assert "/schema_migrator_development" in policy
    assert "nova-toll-v2-development-migrations-dev" in role
    assert 'actions = ["sts:AssumeRoleWithWebIdentity"]' in assume
    assert 'variable = "token.actions.githubusercontent.com:aud"' in assume
    assert 'values   = ["sts.amazonaws.com"]' in assume
    assert (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
        in assume
    )
    for forbidden in (
        "sts:AssumeRole",
        "ssm:",
        "secretsmanager:",
        "terraform.tfstate",
        "development_delivery",
        "timed_checks",
        "production",
        "*",
    ):
        assert forbidden not in policy


def test_development_migrations_workflow_is_main_only_private_and_sanitized(
    tmp_path: Path,
):
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_MIGRATIONS_WORKFLOW))
    assert _workflow_trigger(workflow) == {"workflow_dispatch": None}
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    job = jobs["migrate"]
    assert job["if"] == (
        "github.ref == 'refs/heads/main' && github.actor_id == '91573985' "
        "&& github.triggering_actor == github.actor"
    )
    assert job["environment"] == "development"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert job["concurrency"] == {
        "group": "v2-development-apply",
        "queue": "max",
    }
    defaults = cast(dict[str, object], job["defaults"])
    run_defaults = cast(dict[str, object], defaults["run"])
    assert run_defaults["working-directory"] == "v2"
    assert "workflow_dispatch" in DEVELOPMENT_MIGRATIONS_WORKFLOW
    assert (
        "arn:aws:iam::903859731897:role/nova-toll-v2-development-migrations-dev"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert "tag:ci-development" in DEVELOPMENT_MIGRATIONS_WORKFLOW
    assert "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112" in DEVELOPMENT_MIGRATION_HELPER
    assert 'PGHOST="$DB_HOST"' in DEVELOPMENT_MIGRATION_HELPER
    assert 'PGHOSTADDR="$TRANSPORT_IPV6"' in DEVELOPMENT_MIGRATION_HELPER
    assert "PGSSLMODE=verify-full" in DEVELOPMENT_MIGRATION_HELPER
    assert 'RDS_CA_BUNDLE="$ROOT/v2/infra/build/ca/rds-ca-bundle.pem"' in (
        DEVELOPMENT_MIGRATION_HELPER
    )
    fetched = tmp_path / "v2/infra/build/ca/rds-ca-bundle.pem"
    fetched.parent.mkdir(parents=True)
    fetched.write_text("disposable CA fixture", encoding="utf-8")
    assert fetched == tmp_path / "v2/infra/build/ca/rds-ca-bundle.pem"
    assert fetched != tmp_path / "infra/build/ca/rds-ca-bundle.pem"
    assert "generate-db-auth-token" in DEVELOPMENT_MIGRATION_HELPER
    assert (
        "python3 scripts/run_development_migrations.py" in DEVELOPMENT_MIGRATION_HELPER
    )
    assert (
        'test("^v2/db/migrations/[0-9]{3}_upgrade_(pricing|oracle)_.*\\\\.sql$")'
        in DEVELOPMENT_MIGRATION_HELPER
    )
    assert (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "tailscale/github-action@780049a30b6ff5c378a9e7b389d15ece7a204888"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "aws-actions/configure-aws-credentials@cbe3b392738ccf3f987d68400dafcf4b0624a56c"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert "jq -cn" in DEVELOPMENT_MIGRATION_HELPER
    assert "RUNNER_TEMP" in DEVELOPMENT_MIGRATION_HELPER
    for forbidden in (
        "secretsmanager",
        "ssm:",
        "terraform apply",
        "terraform plan",
        'nova_toll"',
        "raw psql",
    ):
        assert forbidden not in DEVELOPMENT_MIGRATIONS_WORKFLOW


def test_development_migrations_workflow_is_main_only_private_and_sanitized_owner_gate():
    def assert_owner_gate(source: str) -> None:
        workflow = cast(dict[str, object], yaml.safe_load(source))
        jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
        assert jobs["migrate"]["if"] == (
            "github.ref == 'refs/heads/main' && github.actor_id == '91573985' "
            "&& github.triggering_actor == github.actor"
        )

    assert_owner_gate(DEVELOPMENT_MIGRATIONS_WORKFLOW)
    for original, replacement in (
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
    ):
        _must_reject(
            assert_owner_gate,
            DEVELOPMENT_MIGRATIONS_WORKFLOW,
            original,
            replacement,
        )


def test_development_migrations_runbook_requires_post_merge_order_and_allowlist():
    section = DEPLOYMENT.split(
        "##### Protected development migration workflow (#305 slice 3)", 1
    )[1]
    assert section.index("human review and merge") < section.index("foundation plan")
    assert section.index("foundation plan") < section.index(
        "fresh development bootstrap"
    )
    assert section.index("fresh development bootstrap") < section.index(
        "gh workflow run"
    )
    for required in (
        "nova-toll-v2-development-migrations-dev",
        "schema_migrator_development",
        "PGHOST",
        "PGHOSTADDR",
        "applied=[]",
        "commit=<40 lowercase hex>;run=<UUID>",
        "token, password, endpoint",
        "authorized from this graph run",
    ):
        assert required in section

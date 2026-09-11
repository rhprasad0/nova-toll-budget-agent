"""Contract checks for production delivery identities and planning."""

import base64
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
IAM = (ROOT / "infra" / "iam.tf").read_text()
S3 = (ROOT / "infra" / "s3.tf").read_text()
WORKFLOW = (ROOT / ".github" / "workflows" / "terraform.yml").read_text()
PRODUCTION_PLAN = (ROOT / ".github" / "workflows" / "v2-production-plan.yml").read_text()

EXPECTED_PRODUCTION_USAGE_PUBLISHER_READS = {
    "ReadRetiredUsagePublisherIam": {
        "Effect": "Allow",
        "Action": [
            "iam:GetRole",
            "iam:GetRolePolicy",
            "iam:ListAttachedRolePolicies",
            "iam:ListRolePolicies",
            "iam:ListRoleTags",
        ],
        "Resource": ["arn:aws:iam::920534282028:role/tollchat-v2-usage-publisher"],
    },
    "ReadRetiredUsagePublisherLambda": {
        "Effect": "Allow",
        "Action": [
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
        ],
        "Resource": [
            "arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-usage-publisher"
        ],
    },
    "ReadRetiredUsagePublisherEvents": {
        "Effect": "Allow",
        "Action": [
            "events:DescribeRule",
            "events:ListTagsForResource",
            "events:ListTargetsByRule",
        ],
        "Resource": [
            "arn:aws:events:us-east-1:920534282028:rule/tollchat-v2-usage-publisher"
        ],
    },
    "ReadRetiredUsagePublisherAlarms": {
        "Effect": "Allow",
        "Action": ["cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource"],
        "Resource": [
            "arn:aws:cloudwatch:us-east-1:920534282028:alarm:tollchat-v2-usage-publisher-errors",
            "arn:aws:cloudwatch:us-east-1:920534282028:alarm:tollchat-v2-usage-publisher-failed-invocations",
        ],
    },
}


def require(needle: str, haystack: str, message: str | None = None) -> None:
    if needle not in haystack:
        raise AssertionError(message or f"missing contract: {needle}")


def terraform_block(source: str, header: str, occurrence: int = 0) -> str:
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


def rendered_production_policies() -> tuple[
    dict[str, dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, dict[str, object]],
]:
    """Render the production policy locals in an isolated, backend-free root."""
    first_locals = terraform_block(IAM, "locals", 0)
    production_locals = terraform_block(IAM, "locals", 3)
    policy_data = terraform_block(IAM, 'data "aws_iam_policy_document" "development_delivery"')
    test_bucket_arn = "arn:aws:s3:::nova-toll-tfstate-920534282028"
    test_kms_arn = "arn:aws:kms:us-east-1:920534282028:key/00000000-0000-0000-0000-000000000000"
    test_alerts_kms_arn = "arn:aws:kms:us-east-1:920534282028:key/11111111-1111-1111-1111-111111111111"
    policy_data = policy_data.replace("aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn").replace(
        "aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn"
    ).replace("aws_kms_key.alerts.arn", "local.test_alerts_kms_key_arn")
    production_locals = production_locals.replace("aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn").replace(
        "aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn"
    ).replace("aws_kms_key.alerts.arn", "local.test_alerts_kms_key_arn")
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
          region                       = "us-east-1"
          access_key                   = "test"
          secret_key                   = "test"
          skip_credentials_validation = true
          skip_requesting_account_id  = true
          skip_metadata_api_check     = true
        }}

        locals {{
          test_tfstate_bucket_arn = "{test_bucket_arn}"
          test_tfstate_kms_key_arn = "{test_kms_arn}"
          test_alerts_kms_key_arn = "{test_alerts_kms_arn}"
        }}

        {first_locals}
        {policy_data}
        {production_locals}

        output "production_delivery_planner_policy_documents" {{
          value = local.production_delivery_planner_policy_documents
        }}

        output "production_delivery_planner_statements" {{
          value = concat(local.production_delivery_planner_state_statements, local.production_delivery_discovery_statements, [local.production_delivery_dynamodb_default_key_statement, local.production_delivery_alerts_key_statement, local.production_delivery_agentcore_default_statement])
        }}

        output "production_delivery_application_policy_statements" {{
          value = local.production_delivery_application_policy_statements
        }}

        output "production_delivery_deploy_policy_documents" {{
          value = local.production_delivery_deploy_policy_documents
        }}
        """
    )
    with tempfile.TemporaryDirectory(prefix="nova-toll-planner-render-") as directory:
        root = Path(directory)
        (root / "main.tf").write_text(configuration, encoding="utf-8")
        environment = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
        environment["TF_DATA_DIR"] = str(root / ".terraform-data")
        provider_mirror = ROOT / "infra" / ".terraform" / "providers"
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
        plan_path = root / "planner.tfplan"
        plan = subprocess.run(
            ["terraform", "plan", "-refresh=false", "-input=false", "-no-color", f"-out={plan_path}"],
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
        documents = outputs["production_delivery_planner_policy_documents"]["value"]
        statements = outputs["production_delivery_planner_statements"]["value"]
        application_statements = outputs["production_delivery_application_policy_statements"]["value"]
        deploy_documents = outputs["production_delivery_deploy_policy_documents"]["value"]
        return (
            {key: json.loads(value) for key, value in documents.items()},
            statements,
            application_statements,
            {key: json.loads(value) for key, value in deploy_documents.items()},
        )


def rendered_production_migration_identity() -> tuple[dict[str, object], dict[str, object]]:
    """Render the fixed migration trust and permissions in an offline root."""
    assume = terraform_block(
        IAM, 'data "aws_iam_policy_document" "production_migrations_assume"'
    )
    policy = terraform_block(IAM, 'data "aws_iam_policy_document" "production_migrations"')
    replacements = {
        'var.environment == "production" ? 1 : 0': "1",
        "aws_iam_openid_connect_provider.github.arn": "local.github_oidc_arn",
        "local.production_delivery_region": "local.production_region",
        "local.production_delivery_account_id": "local.production_account",
        "aws_db_instance.main.identifier": "local.rds_identifier",
        "aws_db_instance.main.resource_id": "local.rds_resource_id",
    }
    for old, new in replacements.items():
        assume = assume.replace(old, new)
        policy = policy.replace(old, new)
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
          region                       = "us-east-1"
          access_key                   = "test"
          secret_key                   = "test"
          skip_credentials_validation = true
          skip_requesting_account_id  = true
          skip_metadata_api_check     = true
        }}

        locals {{
          github_oidc_arn  = "arn:aws:iam::920534282028:oidc-provider/token.actions.githubusercontent.com"
          production_region = "us-east-1"
          production_account = "920534282028"
          rds_identifier = "nova-toll-db"
          rds_resource_id = "db-E16XVTXNFUS8T4"
        }}

        {assume}
        {policy}

        output "migration_trust" {{
          value = data.aws_iam_policy_document.production_migrations_assume[0].json
        }}

        output "migration_policy" {{
          value = data.aws_iam_policy_document.production_migrations[0].json
        }}
        """
    )
    with tempfile.TemporaryDirectory(prefix="nova-toll-migration-render-") as directory:
        root = Path(directory)
        (root / "main.tf").write_text(configuration, encoding="utf-8")
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("AWS_")
        }
        environment["TF_DATA_DIR"] = str(root / ".terraform-data")
        provider_mirror = ROOT / "infra" / ".terraform" / "providers"
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
            timeout=60,
        )
        assert init.returncode == 0, init.stdout + init.stderr
        plan_path = root / "migration.tfplan"
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
            timeout=60,
        )
        assert plan.returncode == 0, plan.stdout + plan.stderr
        rendered = subprocess.run(
            ["terraform", "show", "-json", str(plan_path)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        outputs = json.loads(rendered.stdout)["planned_values"]["outputs"]
        return (
            json.loads(outputs["migration_trust"]["value"]),
            json.loads(outputs["migration_policy"]["value"]),
        )


def _check_production_planner() -> None:
    require("workflow_run:", PRODUCTION_PLAN)
    require("workflows:\n    - v2-production-release", PRODUCTION_PLAN)
    require("types:\n    - completed", PRODUCTION_PLAN)
    assert "workflow_dispatch:" not in PRODUCTION_PLAN
    assert "push:" not in PRODUCTION_PLAN
    assert "pull_request:" not in PRODUCTION_PLAN
    assert "schedule:" not in PRODUCTION_PLAN
    assert "workflow_call:" not in PRODUCTION_PLAN
    require("group: v2-production-release-delivery", PRODUCTION_PLAN)
    require("cancel-in-progress: false", PRODUCTION_PLAN)

    for job in ("admission", "claim", "planner"):
        require(f"  {job}:\n", PRODUCTION_PLAN)
    assert "\n  deploy:" not in PRODUCTION_PLAN
    require(
        "contents: read\n      actions: read\n      deployments: read", PRODUCTION_PLAN
    )
    require("contents: read\n      deployments: write", PRODUCTION_PLAN)
    require(
        "contents: read\n      actions: read\n      deployments: read\n      id-token: write",
        PRODUCTION_PLAN,
    )
    assert "environment: production" not in PRODUCTION_PLAN

    actions = re.findall(r"uses:\s+([^@\s]+)@([0-9a-f]{40})", PRODUCTION_PLAN)
    assert {name for name, _ in actions} == {
        "actions/checkout",
        "actions/upload-artifact",
        "astral-sh/setup-uv",
        "hashicorp/setup-terraform",
        "aws-actions/configure-aws-credentials",
    }
    assert len(actions) == 9
    require("persist-credentials: false", PRODUCTION_PLAN)
    require("path: trusted", PRODUCTION_PLAN)
    require("path: candidate", PRODUCTION_PLAN)
    require("ref: ${{ steps.admitted.outputs.candidate }}", PRODUCTION_PLAN)
    require("python-version: '3.13'", PRODUCTION_PLAN)
    require("terraform_wrapper: false", PRODUCTION_PLAN)
    require("terraform_version: 1.15.8", PRODUCTION_PLAN)

    for command in (
        "check_production_release.py admit",
        "check_production_release.py claim",
        "check_production_release.py revalidate",
        "verify_release_bundle.py verify",
        "validate_production_plan.py --plan",
        "run_private_stage",
    ):
        require(command, PRODUCTION_PLAN)
    for forbidden in (
        "terraform apply",
        "-target",
        "nova-toll-production-deploy",
        "uv sync --locked",
        "build_loader_zip.sh",
        "build_publisher_zip.sh",
        "build_agentcore_zips.sh",
        "actions/download-artifact",
    ):
        assert forbidden not in PRODUCTION_PLAN, forbidden

    require("Verify exact candidate bundle before OIDC", PRODUCTION_PLAN)
    require("Revalidate mutable release evidence before OIDC", PRODUCTION_PLAN)
    require("aws-actions/configure-aws-credentials@", PRODUCTION_PLAN)
    assert (
        PRODUCTION_PLAN.index("Verify exact candidate bundle before OIDC")
        < PRODUCTION_PLAN.index("Revalidate mutable release evidence before OIDC")
        < PRODUCTION_PLAN.index("aws-actions/configure-aws-credentials@")
    )
    require(
        "role-to-assume: arn:aws:iam::920534282028:role/nova-toll-production-planner",
        PRODUCTION_PLAN,
    )
    require("actions/artifacts/$BUNDLE_ID/zip", PRODUCTION_PLAN)
    require('--expected-digest "$BUNDLE_DIGEST"', PRODUCTION_PLAN)
    require("--verify-checkout", PRODUCTION_PLAN)
    require("$overlay/v2/infra/build/loader.zip", PRODUCTION_PLAN)
    require("$overlay/v2/infra/build/publisher.zip", PRODUCTION_PLAN)
    require("$overlay/v2/infra/build/agentcore.zip", PRODUCTION_PLAN)
    require("$overlay/v2/infra/build/chat-proxy.zip", PRODUCTION_PLAN)
    require("$overlay/v2/infra/build/timed-checks.zip", PRODUCTION_PLAN)

    require(
        "terraform -chdir=candidate/infra init -input=false -backend-config=backend.production.hcl",
        PRODUCTION_PLAN,
    )
    require("terraform -chdir=candidate/infra output -json foundation", PRODUCTION_PLAN)
    require(
        "terraform -chdir=candidate/v2/infra init -input=false -backend-config=backend.production.hcl",
        PRODUCTION_PLAN,
    )
    require(
        'terraform -chdir=candidate/v2/infra plan -input=false -out="$plan"',
        PRODUCTION_PLAN,
    )
    require('terraform -chdir=candidate/v2/infra show -json "$plan"', PRODUCTION_PLAN)
    require(
        "--name /nova-toll/cloudflare-read-api-token --with-decryption", PRODUCTION_PLAN
    )
    require("export CLOUDFLARE_API_TOKEN", PRODUCTION_PLAN)
    assert "GITHUB_ENV" not in PRODUCTION_PLAN
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
        require(field, PRODUCTION_PLAN)

    require("aws s3api put-object", PRODUCTION_PLAN)
    require('--expected-bucket-owner "$EXPECTED_ACCOUNT"', PRODUCTION_PLAN)
    require("--if-none-match '*'", PRODUCTION_PLAN)
    require("--server-side-encryption aws:kms", PRODUCTION_PLAN)
    require('--ssekms-key-id "$TFSTATE_KMS_KEY_ARN"', PRODUCTION_PLAN)
    require("--checksum-algorithm SHA256", PRODUCTION_PLAN)
    require('--checksum-sha256 "$s3_sha"', PRODUCTION_PLAN)
    require('.VersionId|type == "string"', PRODUCTION_PLAN)
    require(".ChecksumSHA256 == $checksum", PRODUCTION_PLAN)
    require(".SSEKMSKeyId == $key", PRODUCTION_PLAN)
    require("GITHUB_STEP_SUMMARY", PRODUCTION_PLAN)
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
        "version_id",
        "checksum",
        "kms_key_arn",
    ):
        require(field, PRODUCTION_PLAN)

def _valid_deploy_metadata() -> dict[str, str]:
    local_sha256 = "0123456789abcdef" * 4
    return {
        "bucket": "nova-toll-tfstate-920534282028",
        "key": "plans/release-301/12345/release.tfplan",
        "version_id": "version-301",
        "local_sha256": local_sha256,
        "s3_sha256": base64.b64encode(bytes.fromhex(local_sha256)).decode(),
        "kms_key_arn": "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7",
        "release_id": "release-301",
        "run_id": "12345",
        "repository": "rhprasad0/nova-toll-budget-agent",
        "commit_sha": "a" * 40,
        "account": "920534282028",
        "region": "us-east-1",
        "resource": "aws_cloudwatch_log_group.tollchat_proxy",
        "action": "update",
        "tag_key": "delivery_proof",
        "tag_value": "issue-301",
    }


def _synthetic_session_policy(metadata: dict[str, str]) -> dict[str, object]:
    bucket_arn = f"arn:aws:s3:::{metadata['bucket']}"
    state_arn = f"{bucket_arn}/nova-toll/v2/terraform.tfstate"
    lock_arn = f"{bucket_arn}/nova-toll/v2/terraform.tfstate.tflock"
    plan_arn = f"{bucket_arn}/{metadata['key']}"
    kms_key_arn = metadata["kms_key_arn"]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": bucket_arn,
                "Condition": {"StringEquals": {"s3:prefix": ["nova-toll/v2/terraform.tfstate", "nova-toll/v2/terraform.tfstate.tflock"]}},
            },
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": state_arn},
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], "Resource": lock_arn},
            {
                "Effect": "Allow",
                "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
                "Resource": kms_key_arn,
                "Condition": {"StringEquals": {"kms:ViaService": "s3.us-east-1.amazonaws.com", "kms:EncryptionContext:aws:s3:arn": [state_arn, lock_arn]}},
            },
            {
                "Effect": "Allow",
                "Action": "s3:GetObjectVersion",
                "Resource": plan_arn,
                "Condition": {"StringEquals": {"s3:VersionId": metadata["version_id"]}},
            },
            {
                "Effect": "Allow",
                "Action": "kms:Decrypt",
                "Resource": kms_key_arn,
                "Condition": {"StringEquals": {"kms:ViaService": "s3.us-east-1.amazonaws.com", "kms:EncryptionContext:aws:s3:arn": plan_arn}},
            },
        ],
    }


def _allows(
    statements: list[dict[str, object]], action: str, resource: str, context: dict[str, str]
) -> bool:
    for statement in statements:
        actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
        if action not in actions or not any(fnmatchcase(resource, pattern) for pattern in resources):
            continue
        for operator, entries in statement.get("Condition", {}).items():
            for key, expected in entries.items():
                actual = context.get(key)
                values = expected if isinstance(expected, list) else [expected]
                matched = actual is not None and (
                    operator == "StringEquals" and actual in values
                    or operator == "StringLike" and any(fnmatchcase(actual, value) for value in values)
                )
                if not matched:
                    break
            else:
                continue
            break
        else:
            return True
    return False

def main() -> None:
    production = IAM[IAM.index("# --- GitHub Actions production planner/deploy identities") :]

    assert IAM.count('resource "aws_iam_role" "production_planner"') == 1
    assert IAM.count('resource "aws_iam_role" "production_deploy"') == 1
    require('name                 = "nova-toll-production-planner"', production)
    require('name                 = "nova-toll-production-deploy"', production)
    assert production.count('count = var.environment == "production" ? 1 : 0') >= 3

    for subject in (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production",
    ):
        require(subject, production)
    assert production.count('actions = ["sts:AssumeRoleWithWebIdentity"]') == 3
    assert 'sts:TagSession' not in production
    assert 'test     = "StringLike"' not in production

    migration_assume = terraform_block(
        IAM, 'data "aws_iam_policy_document" "production_migrations_assume"'
    )
    migration_policy = terraform_block(
        IAM, 'data "aws_iam_policy_document" "production_migrations"'
    )
    migration_role = terraform_block(
        IAM, 'resource "aws_iam_role" "production_migrations"'
    )
    migration_attachment = terraform_block(
        IAM, 'resource "aws_iam_role_policy" "production_migrations"'
    )
    require('name                 = "nova-toll-v2-production-migrations"', migration_role)
    require('name   = "nova-toll-v2-production-migrations"', migration_attachment)
    require('count = var.environment == "production" ? 1 : 0', migration_assume)
    require('count = var.environment == "production" ? 1 : 0', migration_policy)
    require(
        'repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production',
        migration_assume,
    )
    require(
        'token.actions.githubusercontent.com:ref',
        migration_assume,
    )
    require(
        'rhprasad0/nova-toll-budget-agent/.github/workflows/v2-production-migrations.yml@refs/heads/main',
        migration_assume,
    )
    require('sid       = "DescribeFixedProductionRds"', migration_policy)
    require('actions   = ["rds:DescribeDBInstances"]', migration_policy)
    require('sid       = "ConnectAsProductionSchemaMigrator"', migration_policy)
    require('actions   = ["rds-db:connect"]', migration_policy)
    require(
        'dbuser:${aws_db_instance.main.resource_id}/schema_migrator_production',
        migration_policy,
    )
    assert "Resource = [\"*\"]" not in migration_policy
    assert "migration_path" not in migration_policy
    migration_trust_json, migration_policy_json = rendered_production_migration_identity()
    trust_statement = migration_trust_json["Statement"]
    assert len(trust_statement) == 1
    assert trust_statement[0]["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert trust_statement[0]["Principal"] == {
        "Federated": "arn:aws:iam::920534282028:oidc-provider/token.actions.githubusercontent.com"
    }
    assert trust_statement[0]["Condition"] == {
        "StringEquals": {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:ref": "refs/heads/main",
            "token.actions.githubusercontent.com:job_workflow_ref": (
                "rhprasad0/nova-toll-budget-agent/.github/workflows/"
                "v2-production-migrations.yml@refs/heads/main"
            ),
            "token.actions.githubusercontent.com:sub": (
                "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:"
                "environment:production"
            ),
        }
    }
    policy_statements = migration_policy_json["Statement"]
    assert len(policy_statements) == 2

    def as_tuple(value: object) -> tuple[object, ...]:
        if isinstance(value, str):
            return (value,)
        assert isinstance(value, list)
        return tuple(value)

    assert {
        (statement["Sid"], as_tuple(statement["Action"]), as_tuple(statement["Resource"]))
        for statement in policy_statements
    } == {
        (
            "DescribeFixedProductionRds",
            ("rds:DescribeDBInstances",),
            ("arn:aws:rds:us-east-1:920534282028:db:nova-toll-db",),
        ),
        (
            "ConnectAsProductionSchemaMigrator",
            ("rds-db:connect",),
            (
                "arn:aws:rds-db:us-east-1:920534282028:dbuser:"
                "db-E16XVTXNFUS8T4/schema_migrator_production",
            ),
        ),
    }
    assert all(
        resource != "*"
        for statement in policy_statements
        for resource in as_tuple(statement["Resource"])
    )

    for identifier in (
        "920534282028",
        "us-east-1",
        "E16XVTXNFUS8T4",
        "4f3f1888-76ef-4b89-9170-de501ed515d8",
        "nova_toll_v2-W6989LEw44",
        "arn:aws:bedrock:us-east-1:920534282028:guardrail/k0n0rkm24p9p",
        "mxey1r2rhc",
        "arn:aws:apigateway:us-east-1::/restapis/mxey1r2rhc",
        "a1d9cd35-9317-4f69-8146-3dbdf4d75e06",
        "arn:aws:acm:us-east-1:920534282028:certificate/a1d9cd35-9317-4f69-8146-3dbdf4d75e06",
        "b1d6d4b1-2370-403e-b735-f29b958703aa",
        "e6413a73-bf0f-438e-88be-74070724d5a1",
        "/nova-toll/cloudflare-read-api-token",
        "49d9dfb4-f9a7-465a-a3a1-e7bb394dd0de",
    ):
        require(identifier, production)
    assert "E33DVF3KT7BTAC" not in production
    assert "903859731897" not in production
    assert "ocw8sg0wlb" not in production
    require("production_delivery_application_policy_api_json", production)
    require("production_delivery_certificate_arn", production)
    assert "guardrail/*" not in production, "production guardrail ARN must be exact"
    assert "uikws8bgms92" not in production, "legacy guardrail ARN must not be reused"

    require("nova-toll/terraform.tfstate", production)
    require("nova-toll/v2/terraform.tfstate", production)
    require("nova-toll/v2/terraform.tfstate.tflock", production)
    require("plans/*/*/release.tfplan", production)
    require('Action   = ["s3:GetObjectVersion"]', production)
    require('Action   = ["s3:PutObject"]', production)
    require('"kms:EncryptionContext:aws:s3:arn"', production)
    require('"kms:ViaService"', production)
    require('"kms:EncryptionContext:PARAMETER_ARN"', production)
    require('"iam:PassedToService"', production)
    require("bedrock-agentcore.amazonaws.com", production)

    development_delivery = terraform_block(
        IAM, 'data "aws_iam_policy_document" "development_delivery"'
    )
    development_shards = terraform_block(IAM, "locals", 1)
    assert development_delivery.count('sid       = "PassTimedChecksSchedulerRole"') == 1
    require('actions   = ["iam:PassRole"]', development_delivery)
    require(
        'arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-timed-checks-scheduler-dev',
        development_delivery,
    )
    require('variable = "iam:PassedToService"', development_delivery)
    require('values   = ["scheduler.amazonaws.com"]', development_delivery)
    require(
        "Statement = slice(local.development_delivery_policy_statements, 35, 45)",
        development_shards,
    )

    planner = production[: production.index("  production_delivery_deploy_state_statements")]
    application_slice = production[
        production.index("  production_delivery_application_policy_statements") : production.index(
            "  production_delivery_read_prefixes"
        )
    ]
    require(
        "jsondecode(local.production_delivery_application_policy_json).Statement,\n      6,",
        application_slice,
        "application refresh statements must retain ReadPreprovisionedApplicationRoles",
    )
    require('"ReadAlertsKeyForTimedChecks",', application_slice)
    assert '"s3:GetObjectVersion"' not in planner
    assert '"s3:DeleteObject"]\n      Resource = ["${aws_s3_bucket.tfstate.arn}/plans/' not in planner
    require("ReadCloudflareProviderToken", planner)
    require("DecryptCloudflareProviderToken", planner)

    require("production_delivery_planner_policy_documents", production)
    (
        planner_documents,
        planner_statements,
        application_statements,
        deploy_documents,
    ) = rendered_production_policies()
    assert len(planner_documents) == 9
    assert len(planner_documents) <= 10
    assert set(planner_documents) == {
        "state",
        "plan",
        "compute",
        "observability",
        "storage",
        "data",
        "runtime",
        "edge",
        "endpoint",
    }
    planner_keys = (
        "state",
        "plan",
        "compute",
        "observability",
        "storage",
        "data",
        "runtime",
        "edge",
        "endpoint",
    )
    split_statements = [
        statement
        for key in planner_keys
        for statement in planner_documents[key]["Statement"]
    ]
    assert {json.dumps(statement, sort_keys=True) for statement in split_statements} == {
        json.dumps(statement, sort_keys=True) for statement in planner_statements
    }
    assert len({json.dumps(statement, sort_keys=True) for statement in split_statements}) == len(split_statements)
    for key, policy in planner_documents.items():
        rendered = json.dumps(policy, separators=(",", ":"), ensure_ascii=False)
        size = len(rendered.encode("utf-8"))
        print(f"planner policy {key}: {size} UTF-8 bytes")
        assert size <= 6_144
    planner_discovery_keys = planner_keys[2:-1]
    rendered_planner_discovery = [
        statement
        for key in planner_discovery_keys
        for statement in planner_documents[key]["Statement"]
    ]
    assert len({statement["Sid"] for statement in rendered_planner_discovery}) == len(rendered_planner_discovery)
    planner_json = json.dumps(planner_documents, sort_keys=True)
    assert "iam:PassRole" not in planner_json
    expected_dynamodb_default_key_read = {
        "Action": ["kms:DescribeKey"],
        "Effect": "Allow",
        "Resource": [
            "arn:aws:kms:us-east-1:920534282028:key/52601535-3171-4f21-af72-125daaf1347d"
        ],
        "Sid": "ReadProductionDynamoDBDefaultKey",
    }
    expected_alerts_key_read = {
        "Action": ["kms:DescribeKey"],
        "Effect": "Allow",
        "Resource": [
            "arn:aws:kms:us-east-1:920534282028:key/11111111-1111-1111-1111-111111111111"
        ],
        "Sid": "ReadProductionAlertsKeyForTimedChecks",
    }
    for documents in (planner_documents, deploy_documents):
        assert [
            statement
            for statement in documents["data"]["Statement"]
            if statement["Sid"] == "ReadProductionDynamoDBDefaultKey"
        ] == [expected_dynamodb_default_key_read]
    assert [
        statement
        for statement in planner_documents["data"]["Statement"]
        if statement["Sid"] == "ReadProductionAlertsKeyForTimedChecks"
    ] == [expected_alerts_key_read]
    assert not any(
        statement["Sid"] == "ReadProductionAlertsKeyForTimedChecks"
        for policy in deploy_documents.values()
        for statement in policy["Statement"]
    )
    assert not any(
        statement["Sid"] == "ReadAlertsKeyForTimedChecks"
        for statement in application_statements
    )
    for statement in split_statements:
        if "s3:GetObjectVersion" in statement.get("Action", []):
            assert all("/plans/" not in resource for resource in statement["Resource"])
    assert set(deploy_documents) == {"state", "release", "compute", "observability", "storage", "data", "runtime", "schedules", "edge"}
    schedule_statements = deploy_documents["schedules"]["Statement"]
    assert [statement["Sid"] for statement in schedule_statements] == [
        "ManageApplicationSchedules",
        "PassTimedChecksSchedulerRole",
    ]
    passrole = schedule_statements[1]
    assert passrole["Action"] in ("iam:PassRole", ["iam:PassRole"])
    assert passrole["Resource"] in (
        "arn:aws:iam::920534282028:role/nova-toll-v2-timed-checks-scheduler",
        ["arn:aws:iam::920534282028:role/nova-toll-v2-timed-checks-scheduler"],
    )
    assert passrole["Condition"] == {
        "StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}
    }
    deploy_application_keys = ("compute", "observability", "storage", "data", "runtime", "schedules", "edge")
    rendered_deploy_application = [
        statement
        for key in deploy_application_keys
        for statement in deploy_documents[key]["Statement"]
        if statement["Sid"]
        not in {
            "ReadProductionAgentCoreDefaultEndpoint",
            "PassProductionAgentCoreRuntimeRole",
            "ReadProductionDynamoDBDefaultKey",
        }
    ]
    assert rendered_deploy_application == application_statements
    assert len({statement["Sid"] for statement in rendered_deploy_application}) == len(rendered_deploy_application)
    for key, policy in deploy_documents.items():
        rendered = json.dumps(policy, separators=(",", ":"), ensure_ascii=False)
        size = len(rendered.encode("utf-8"))
        print(f"deploy policy {key}: {size} UTF-8 bytes")
        assert size <= 6_144
    production_deploy_json = json.dumps(deploy_documents, sort_keys=True)
    expected_reads = {
        sid: {
            "Effect": values["Effect"],
            "Action": sorted(values["Action"]),
            "Resource": sorted(values["Resource"]),
        }
        for sid, values in EXPECTED_PRODUCTION_USAGE_PUBLISHER_READS.items()
    }
    for statements in (rendered_planner_discovery, application_statements):
        actual_reads = {
            statement["Sid"]: {
                "Effect": statement["Effect"],
                "Action": sorted(statement["Action"]),
                "Resource": sorted(
                    statement["Resource"]
                    if isinstance(statement["Resource"], list)
                    else [statement["Resource"]]
                ),
            }
            for statement in statements
            if statement["Sid"] in EXPECTED_PRODUCTION_USAGE_PUBLISHER_READS
        }
        assert all(
            set(statement) == {"Action", "Effect", "Resource", "Sid"}
            for statement in statements
            if statement["Sid"] in EXPECTED_PRODUCTION_USAGE_PUBLISHER_READS
        )
        assert actual_reads == expected_reads
    effective_policy_json = json.dumps(
        planner_documents, sort_keys=True
    )
    effective_policy_json += production_deploy_json
    assert "903859731897" not in effective_policy_json
    assert "tollchat-v2-usage-publisher-dev" not in effective_policy_json
    assert "tollchat-v2-agent-usage-rollup-dev" not in effective_policy_json
    assert "tollchat-agent-reports-dev" not in effective_policy_json
    assert "250c4d9a-abcd-4bdf-861c-b2b10549a770" not in effective_policy_json
    for sid in (
        "RetireUsagePublisherIam",
        "RetireUsagePublisherLambda",
        "RetireUsagePublisherEvents",
        "RetireUsagePublisherAlarms",
        "RetireAgentUsageRollupIam",
        "RetireAgentUsageRollupLambda",
        "RetireAgentUsageRollupEvents",
        "RetireAgentUsageRollupAlarms",
        "RetireAgentReportsWafLogging",
    ):
        assert sid not in planner_json
        assert sid not in production_deploy_json
    retired_actions = {
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "lambda:DeleteFunction",
        "lambda:RemovePermission",
        "events:DeleteRule",
        "events:RemoveTargets",
        "cloudwatch:DeleteAlarms",
        "wafv2:DeleteLoggingConfiguration",
    }
    for statements in (rendered_planner_discovery, application_statements):
        for statement in statements:
            if "tollchat-v2-usage-publisher" in json.dumps(statement):
                assert not retired_actions.intersection(statement.get("Action", []))
            if any(
                identifier in json.dumps(statement)
                for identifier in (
                    "tollchat-v2-agent-usage-rollup",
                    "250c4d9a-abcd-4bdf-861c-b2b10549a770",
                )
            ):
                assert not retired_actions.intersection(statement.get("Action", []))
    for policy in deploy_documents.values():
        for statement in policy["Statement"]:
            if "tollchat-v2-usage-publisher" in json.dumps(statement):
                assert not retired_actions.intersection(statement.get("Action", []))
            if any(
                identifier in json.dumps(statement)
                for identifier in (
                    "tollchat-v2-agent-usage-rollup",
                    "250c4d9a-abcd-4bdf-861c-b2b10549a770",
                )
            ):
                assert not retired_actions.intersection(statement.get("Action", []))
    state_statements = deploy_documents["state"]["Statement"]
    release_statements = deploy_documents["release"]["Statement"]
    assert [statement["Sid"] for statement in state_statements] == ["ListProductionApplicationState", "ManageProductionApplicationState", "ManageProductionApplicationLock", "DecryptProductionApplicationStateAndLock", "GenerateProductionApplicationStateDataKeys", "ReadCloudflareProviderTokenForApply", "DecryptCloudflareProviderTokenForApply"]
    assert [statement["Sid"] for statement in release_statements] == ["ReadVersionedReleasePlan", "DecryptVersionedReleasePlan"]
    assert "/plans/" not in json.dumps(state_statements)
    assert state_statements[1]["Action"] == ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
    assert [statement["Action"] for statement in release_statements] == [["s3:GetObjectVersion"], ["kms:Decrypt"]]
    assert all("plans/*" in json.dumps(statement) for statement in release_statements)

    metadata = _valid_deploy_metadata()
    inline_plan = _synthetic_session_policy(metadata)["Statement"][4:]
    release_kms = dict(release_statements[1], Resource=[metadata["kms_key_arn"]])
    role_union = state_statements + [release_statements[0], release_kms]
    session_union = state_statements + inline_plan
    bucket = f"arn:aws:s3:::{metadata['bucket']}"
    state = f"{bucket}/nova-toll/v2/terraform.tfstate"
    lock = f"{state}.tflock"
    plan = f"{bucket}/{metadata['key']}"
    plan_kms = {"kms:ViaService": "s3.us-east-1.amazonaws.com", "kms:EncryptionContext:aws:s3:arn": plan}

    def effective(action: str, resource: str, context: dict[str, str]) -> bool:
        return _allows(role_union, action, resource, context) and _allows(session_union, action, resource, context)

    assert _allows(release_statements, "s3:GetObjectVersion", f"{bucket}/plans/other", {})
    assert not _allows(session_union, "s3:GetObjectVersion", f"{bucket}/plans/other", {})
    cases = [
        ("s3:ListBucket", bucket, {"s3:prefix": "nova-toll/v2/terraform.tfstate"}, True),
        ("s3:GetObject", state, {}, True),
        ("s3:GetObjectVersion", state, {}, True),
        ("s3:PutObject", state, {}, True),
        ("s3:GetObject", lock, {}, True),
        ("s3:PutObject", lock, {}, True),
        ("s3:DeleteObject", lock, {}, True),
        ("kms:Decrypt", state_statements[3]["Resource"][0], {"kms:ViaService": "s3.us-east-1.amazonaws.com", "kms:EncryptionContext:aws:s3:arn": state}, True),
        ("kms:GenerateDataKey", state_statements[3]["Resource"][0], {"kms:ViaService": "s3.us-east-1.amazonaws.com", "kms:EncryptionContext:aws:s3:arn": lock}, True),
        ("s3:GetObjectVersion", plan, {"s3:VersionId": metadata["version_id"]}, True),
        ("s3:GetObjectVersion", f"{bucket}/plans/other", {"s3:VersionId": metadata["version_id"]}, False),
        ("s3:GetObjectVersion", plan, {"s3:VersionId": "wrong-version"}, False),
        ("s3:GetObjectVersion", plan, {}, False),
        ("kms:Decrypt", metadata["kms_key_arn"], plan_kms, True),
        ("kms:Decrypt", f"{metadata['kms_key_arn']}-alternate", plan_kms, False),
        ("kms:Decrypt", metadata["kms_key_arn"], {**plan_kms, "kms:ViaService": "ec2.us-east-1.amazonaws.com"}, False),
        ("kms:Decrypt", metadata["kms_key_arn"], {"kms:EncryptionContext:aws:s3:arn": plan}, False),
        ("kms:Decrypt", metadata["kms_key_arn"], {"kms:ViaService": "s3.us-east-1.amazonaws.com"}, False),
        ("kms:Decrypt", metadata["kms_key_arn"], {**plan_kms, "kms:EncryptionContext:aws:s3:arn": f"{bucket}/plans/other"}, False),
    ]
    for action, resource, context, expected in cases:
        assert effective(action, resource, context) is expected

    deploy_document = production[production.index('data "aws_iam_policy_document" "production_deploy"') :]
    require("PassProductionAgentCoreRuntimeRole", production)
    require("ReadVersionedReleasePlan", production)
    require(
        "Statement = concat(local.production_delivery_deploy_state_statements, local.production_delivery_deploy_release_statements,",
        deploy_document,
    )
    deploy_resource = terraform_block(IAM, 'resource "aws_iam_policy" "production_deploy"')
    deploy_attachment = terraform_block(IAM, 'resource "aws_iam_role_policy_attachment" "production_deploy"')
    require("local.production_delivery_deploy_policy_documents", deploy_resource)
    require("local.production_delivery_deploy_policy_documents", deploy_attachment)
    assert 'Action   = ["s3:GetObject"]\n      Resource = ["${aws_s3_bucket.tfstate.arn}/plans/' not in deploy_document
    planner_resource = terraform_block(
        IAM, 'resource "aws_iam_policy" "production_planner"'
    )
    assert 'for_each = var.environment == "production" ? local.production_delivery_planner_policy_documents : {}' in planner_resource
    assert 'name     = "nova-toll-production-planner-${each.key}"' in planner_resource
    planner_attachment = terraform_block(
        IAM, 'resource "aws_iam_role_policy_attachment" "production_planner"'
    )
    assert 'for_each   = var.environment == "production" ? local.production_delivery_planner_policy_documents : {}' in planner_attachment
    assert 'policy_arn = aws_iam_policy.production_planner[each.key].arn' in planner_attachment

    require('id     = "expire-release-plans"', S3)
    require('prefix = "plans/"', S3)
    require("days = 7", S3)
    require("noncurrent_days = 1", S3)
    require("expired_object_delete_marker = true", S3)
    require("DenyUnconditionalReleasePlanPut", S3)
    require("DenyUnencryptedReleasePlanPut", S3)
    require("DenyWrongReleasePlanKmsKey", S3)
    require('variable = "s3:if-none-match"', S3)
    require('values   = ["*"]', S3)
    assert 'resources = ["${aws_s3_bucket.tfstate.arn}/plans/*"]' in S3
    require('variable = "s3:x-amz-server-side-encryption"', S3)
    require('values   = ["aws:kms"]', S3)
    require('variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"', S3)
    require("aws_kms_key.tfstate.arn", S3)

    require("python3 infra/test_delivery_identities.py", WORKFLOW)
    require("terraform init -backend=false -input=false", WORKFLOW)
    assert "id-token: write" not in WORKFLOW
    assert "aws-actions/configure-aws-credentials" not in WORKFLOW
    assert "terraform plan" not in WORKFLOW
    assert "terraform apply" not in WORKFLOW

    _check_production_planner()

    print("delivery identity contract: ok")


if __name__ == "__main__":
    main()

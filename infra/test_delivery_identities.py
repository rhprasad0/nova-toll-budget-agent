"""Contract checks for the production Terraform delivery identities."""

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


def rendered_planner_policies() -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    """Render the exact planner local in an isolated, backend-free Terraform root."""
    first_locals = terraform_block(IAM, "locals", 0)
    production_locals = terraform_block(IAM, "locals", 3)
    policy_data = terraform_block(IAM, 'data "aws_iam_policy_document" "development_delivery"')
    test_bucket_arn = "arn:aws:s3:::nova-toll-tfstate-920534282028"
    test_kms_arn = "arn:aws:kms:us-east-1:920534282028:key/00000000-0000-0000-0000-000000000000"
    policy_data = policy_data.replace("aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn").replace(
        "aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn"
    )
    production_locals = production_locals.replace("aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn").replace(
        "aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn"
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
        }}

        {first_locals}
        {policy_data}
        {production_locals}

        output "production_delivery_planner_policy_documents" {{
          value = local.production_delivery_planner_policy_documents
        }}

        output "production_delivery_planner_statements" {{
          value = concat(local.production_delivery_planner_state_statements, local.production_delivery_discovery_statements, [local.production_delivery_agentcore_default_statement])
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
        return {key: json.loads(value) for key, value in documents.items()}, statements


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
    assert production.count('actions = ["sts:AssumeRoleWithWebIdentity"]') == 2
    assert 'sts:TagSession' not in production
    assert 'test     = "StringLike"' not in production

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
    assert '"s3:GetObjectVersion"' not in planner
    assert '"s3:DeleteObject"]\n      Resource = ["${aws_s3_bucket.tfstate.arn}/plans/' not in planner
    require("ReadCloudflareProviderToken", planner)
    require("DecryptCloudflareProviderToken", planner)

    require("production_delivery_planner_policy_documents", production)
    planner_documents, planner_statements = rendered_planner_policies()
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
    split_statements = [
        statement
        for key in (
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
        for statement in planner_documents[key]["Statement"]
    ]
    assert split_statements == planner_statements
    assert len({json.dumps(statement, sort_keys=True) for statement in split_statements}) == len(split_statements)
    for key, policy in planner_documents.items():
        rendered = json.dumps(policy, separators=(",", ":"), ensure_ascii=False)
        size = len(rendered.encode("utf-8"))
        print(f"planner policy {key}: {size} UTF-8 bytes")
        assert size <= 6_144
    planner_json = json.dumps(planner_documents, sort_keys=True)
    assert "iam:PassRole" not in planner_json
    for statement in split_statements:
        if "s3:GetObjectVersion" in statement.get("Action", []):
            assert all("/plans/" not in resource for resource in statement["Resource"])
    deploy_document = production[production.index('data "aws_iam_policy_document" "production_deploy"') :]
    require("PassProductionAgentCoreRuntimeRole", production)
    require("ReadVersionedReleasePlan", production)
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

    print("delivery identity contract: ok")


if __name__ == "__main__":
    main()

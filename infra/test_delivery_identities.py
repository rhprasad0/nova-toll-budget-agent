"""Contract checks for production delivery identities and planning."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from textwrap import dedent
import textwrap


ROOT = Path(__file__).resolve().parents[1]
IAM = (ROOT / "infra" / "iam.tf").read_text()
S3 = (ROOT / "infra" / "s3.tf").read_text()
WORKFLOW = (ROOT / ".github" / "workflows" / "terraform.yml").read_text()
PRODUCTION_PLAN = (ROOT / ".github" / "workflows" / "v2-production-plan.yml").read_text()


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


def _gate_source() -> str:
    marker = '          python3 - "$PLAN_JSON" <<\'PY\'\n'
    start = PRODUCTION_PLAN.index(marker) + len(marker)
    end = PRODUCTION_PLAN.index("\n          PY", start)
    return textwrap.dedent(PRODUCTION_PLAN[start:end])


def _target_change(action: list[str] | None = None) -> dict[str, object]:
    defaults = {
        "project": "nova-toll-budget-agent",
        "version": "v2",
        "environment": "production",
    }
    after_tags = {**defaults, "delivery_proof": "issue-301"}
    return {
        "address": "aws_cloudwatch_log_group.tollchat_proxy",
        "mode": "managed",
        "change": {
            "before": {"name": "/aws/lambda/tollchat-v2-chat-proxy", "retention_in_days": 30, "tags": defaults, "tags_all": defaults},
            "after": {"name": "/aws/lambda/tollchat-v2-chat-proxy", "retention_in_days": 30, "tags": after_tags, "tags_all": after_tags},
            "after_unknown": {},
            "actions": action or ["update"],
        },
    }


def _output_change(value: object, *, nested_metadata: bool = False) -> dict[str, object]:
    metadata: object = {"known": False, "nested": [False]} if nested_metadata else False
    return {
        "before": value,
        "after": value,
        "after_unknown": metadata,
        "before_sensitive": metadata,
        "after_sensitive": metadata,
        "actions": ["no-op"],
    }


def _valid_plan() -> dict[str, object]:
    output_values = {
        "development_acm_certificate_arn": "",
        "development_acm_validation_records": [],
        "public_site": {"distribution_id": "E16XVTXNFUS8T4", "hostname": "example.com", "url": "https://example.com"},
        "agent_report_web_acl_arn": "arn:aws:wafv2:us-east-1:920534282028:regional/webacl/example/1234",
        "agent_report_analytics": {"bucket": "reports", "database": "analytics", "workgroup": "primary"},
        "private_preview": {"api_id": "api", "stage": "prod", "origin": "origin", "url": "https://api.example.com"},
    }
    return {
        "resource_changes": [
            _target_change(),
            {
                "address": "data.aws_region.current",
                "mode": "data",
                "change": {"before": None, "after": {"name": "us-east-1"}, "after_unknown": {}, "actions": ["read"]},
            },
            {
                "address": "aws_cloudwatch_log_group.loader",
                "mode": "managed",
                "change": {"before": {"name": "loader"}, "after": {"name": "loader"}, "after_unknown": {}, "actions": ["no-op"]},
            },
        ],
        "output_changes": {
            name: _output_change(value, nested_metadata=name in {"public_site", "agent_report_analytics", "private_preview"})
            for name, value in output_values.items()
        },
    }


def _gate_result(plan: object | str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        plan_file = Path(directory) / "plan.json"
        if isinstance(plan, str):
            plan_file.write_text(plan)
        else:
            plan_file.write_text(json.dumps(plan))
        return subprocess.run(
            [sys.executable, "-", str(plan_file)],
            cwd=ROOT,
            input=_gate_source(),
            capture_output=True,
            text=True,
            check=False,
        )
def _assert_gate_fixtures() -> None:
    accepted = _gate_result(_valid_plan())
    assert accepted.returncode == 0
    assert accepted.stdout == "production plan gate: approved exact delivery_proof update\n"
    assert accepted.stderr == ""

    extra_update = _valid_plan()
    extra_update["resource_changes"].append(
        {
            "address": "aws_cloudwatch_log_group.loader",
            "mode": "managed",
            "change": {"before": {"name": "loader"}, "after": {"name": "loader2"}, "after_unknown": {}, "actions": ["update"]},
        }
    )
    invalid = [extra_update]
    for action in (["create"], ["delete"], ["delete", "create"]):
        invalid.append({**_valid_plan(), "resource_changes": [_target_change(list(action))]})

    wrong_address = _valid_plan()
    wrong_address["resource_changes"][0]["address"] = "aws_cloudwatch_log_group.loader"
    invalid.append(wrong_address)

    bad_tags = _valid_plan()
    bad_tags["resource_changes"][0]["change"]["after"]["tags"]["project"] = "changed"
    invalid.append(bad_tags)

    missing_tag = _valid_plan()
    del missing_tag["resource_changes"][0]["change"]["after"]["tags_all"]["delivery_proof"]
    invalid.append(missing_tag)

    data_write = _valid_plan()
    data_write["resource_changes"][1]["change"]["actions"] = ["update"]
    invalid.append(data_write)

    unknown_address = _valid_plan()
    unknown_address["resource_changes"].append(
        {
            "address": "aws_unknown_resource.example",
            "mode": "managed",
            "change": {"before": {}, "after": {}, "after_unknown": {}, "actions": ["no-op"]},
        }
    )
    invalid.append(unknown_address)

    drift = _valid_plan()
    drift["resource_changes"][2]["change"]["after"]["name"] = "changed"
    invalid.append(drift)

    deposed = _valid_plan()
    deposed["resource_changes"][0]["deposed"] = "old"
    invalid.append(deposed)

    previous = _valid_plan()
    previous["resource_changes"][0]["previous_address"] = "old.address"
    invalid.append(previous)

    unknown_value = _valid_plan()
    unknown_value["resource_changes"][0]["change"]["after_unknown"] = {"retention_in_days": True}
    invalid.append(unknown_value)

    missing_unknown = _valid_plan()
    del missing_unknown["resource_changes"][0]["change"]["after_unknown"]
    invalid.append(missing_unknown)

    malformed_unknown = _valid_plan()
    malformed_unknown["resource_changes"][0]["change"]["after_unknown"] = False
    invalid.append(malformed_unknown)

    malformed_unknown_leaf = _valid_plan()
    malformed_unknown_leaf["resource_changes"][0]["change"]["after_unknown"] = {"retention_in_days": "not-a-bool"}
    invalid.append(malformed_unknown_leaf)

    replacement = _valid_plan()
    replacement["resource_changes"][0]["change"]["replace_paths"] = [["tags"]]
    invalid.append(replacement)

    malformed_replacement = _valid_plan()
    malformed_replacement["resource_changes"][0]["change"]["replace_paths"] = None
    invalid.append(malformed_replacement)

    indexed_target = _valid_plan()
    indexed_target["resource_changes"][0]["address"] = 'aws_cloudwatch_log_group.tollchat_proxy["unexpected"]'
    invalid.append(indexed_target)

    deleted_tag = _valid_plan()
    del deleted_tag["resource_changes"][0]["change"]["after"]["tags_all"]["project"]
    invalid.append(deleted_tag)

    resource_drift = _valid_plan()
    resource_drift["resource_drift"] = [_target_change()]
    invalid.append(resource_drift)

    unknown_output = _valid_plan()
    unknown_output["output_changes"]["public_site"]["after_unknown"] = {"nested": [False, True]}
    invalid.append(unknown_output)

    changed_output = _valid_plan()
    changed_output["output_changes"]["public_site"]["after"] = {"distribution_id": "changed"}
    invalid.append(changed_output)

    output_action = _valid_plan()
    output_action["output_changes"]["public_site"]["actions"] = ["update"]
    invalid.append(output_action)

    missing_output = _valid_plan()
    del missing_output["output_changes"]["private_preview"]
    invalid.append(missing_output)

    extra_output = _valid_plan()
    extra_output["output_changes"]["release"] = _output_change("unexpected")
    invalid.append(extra_output)

    malformed_output_entry = _valid_plan()
    malformed_output_entry["output_changes"]["public_site"] = []
    invalid.append(malformed_output_entry)

    malformed_output_field = _valid_plan()
    del malformed_output_field["output_changes"]["public_site"]["after_sensitive"]
    invalid.append(malformed_output_field)

    unrecognized_output_field = _valid_plan()
    unrecognized_output_field["output_changes"]["public_site"]["replace_paths"] = []
    invalid.append(unrecognized_output_field)

    malformed_output_actions = _valid_plan()
    malformed_output_actions["output_changes"]["public_site"]["actions"] = "no-op"
    invalid.append(malformed_output_actions)

    malformed_output_metadata = _valid_plan()
    malformed_output_metadata["output_changes"]["public_site"]["after_unknown"] = {"nested": ["false"]}
    invalid.append(malformed_output_metadata)

    for rejected in invalid:
        result = _gate_result(rejected)
        assert result.returncode != 0
        assert result.stdout == ""
        assert result.stderr == "production plan gate: rejected\n"

    malformed = _gate_result("not json")
    assert malformed.returncode != 0
    assert malformed.stdout == ""
    assert malformed.stderr == "production plan gate: rejected\n"


def _check_production_planner() -> None:
    require("workflow_dispatch:", PRODUCTION_PLAN)
    assert PRODUCTION_PLAN.count("workflow_dispatch:") == 1
    assert PRODUCTION_PLAN.count("jobs:") == 1
    for forbidden in (
        "push:",
        "pull_request:",
        "schedule:",
        "workflow_call:",
        "environment:",
        "actions/upload-artifact",
        "actions/download-artifact",
        "terraform apply",
        "aws s3api get-object",
        "aws s3api head-object",
        "aws s3api delete-object",
        "aws cloudformation",
    ):
        assert forbidden not in PRODUCTION_PLAN, forbidden
    require("release_id:", PRODUCTION_PLAN)
    require("required: true", PRODUCTION_PLAN)
    require("type: string", PRODUCTION_PLAN)
    require("if: github.repository == 'rhprasad0/nova-toll-budget-agent' && github.ref == 'refs/heads/main'", PRODUCTION_PLAN)
    require("contents: read\n      id-token: write", PRODUCTION_PLAN)
    require("RELEASE_ID: ${{ inputs.release_id }}", PRODUCTION_PLAN)
    require("RELEASE_ID: ${{ steps.validate.outputs.release_id }}", PRODUCTION_PLAN)
    assert PRODUCTION_PLAN.count("^[A-Za-z0-9._-]{1,64}$") >= 2
    require('PLAN_KEY="plans/${RELEASE_ID}/${GITHUB_RUN_ID}/release.tfplan"', PRODUCTION_PLAN)

    actions = re.findall(r"uses:\s+([^@\s]+)@([0-9a-f]{40})", PRODUCTION_PLAN)
    assert {name for name, _ in actions} == {
        "actions/checkout",
        "astral-sh/setup-uv",
        "hashicorp/setup-terraform",
        "aws-actions/configure-aws-credentials",
    }
    assert len(actions) == 4
    require("persist-credentials: false", PRODUCTION_PLAN)
    require('python-version: "3.13"', PRODUCTION_PLAN)
    require("terraform_wrapper: false", PRODUCTION_PLAN)
    require('terraform_version: "1.15.8"', PRODUCTION_PLAN)

    require("umask 077", PRODUCTION_PLAN)
    require("set +x", PRODUCTION_PLAN)
    require("role-to-assume: arn:aws:iam::920534282028:role/nova-toll-production-planner", PRODUCTION_PLAN)
    require("aws sts get-caller-identity", PRODUCTION_PLAN)
    require("test \"$ACCOUNT\" = \"$EXPECTED_ACCOUNT\"", PRODUCTION_PLAN)
    require("--name /nova-toll/cloudflare-read-api-token --with-decryption", PRODUCTION_PLAN)
    require("--query Parameter.Value --output text", PRODUCTION_PLAN)
    require("export CLOUDFLARE_API_TOKEN", PRODUCTION_PLAN)
    assert "GITHUB_ENV" not in PRODUCTION_PLAN
    assert "add-mask" not in PRODUCTION_PLAN

    require("uv sync --locked", PRODUCTION_PLAN)
    for script in ("build_loader_zip.sh", "build_publisher_zip.sh", "build_agentcore_zips.sh"):
        require(f"./scripts/{script}", PRODUCTION_PLAN)
    for package in ("loader.zip", "publisher.zip", "agentcore.zip", "chat-proxy.zip"):
        require(f"infra/build/{package}", PRODUCTION_PLAN)
    require("-var loader_package_path=build/loader.zip", PRODUCTION_PLAN)
    require("-var publisher_package_path=build/publisher.zip", PRODUCTION_PLAN)
    require("-var agentcore_package_path=build/agentcore.zip", PRODUCTION_PLAN)
    require("-var chat_proxy_package_path=build/chat-proxy.zip", PRODUCTION_PLAN)
    require("terraform -chdir=infra init -input=false -backend-config=backend.production.hcl", PRODUCTION_PLAN)
    require("terraform -chdir=infra output -json foundation", PRODUCTION_PLAN)
    require("jq -n --slurpfile foundation", PRODUCTION_PLAN)
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
    require('exact_keys(["a", "c"])', PRODUCTION_PLAN)
    require('exact_keys(["identifier", "resource_id", "address", "port"])', PRODUCTION_PLAN)
    require('chmod 600 -- "$FOUNDATION_VARS"', PRODUCTION_PLAN)
    require("terraform -chdir=v2/infra init -input=false -backend-config=backend.production.hcl", PRODUCTION_PLAN)
    require("-var-file=production.tfvars", PRODUCTION_PLAN)
    require('python3 - "$PLAN_JSON" <<\'PY\'', PRODUCTION_PLAN)
    require('TARGET = "aws_cloudwatch_log_group.tollchat_proxy"', PRODUCTION_PLAN)
    require('APPROVED_TAG = ("delivery_proof", "issue-301")', PRODUCTION_PLAN)
    require('"after_unknown"', PRODUCTION_PLAN)
    require('drift = plan.get("resource_drift", [])', PRODUCTION_PLAN)
    require('replace_paths = change.get("replace_paths", [])', PRODUCTION_PLAN)
    require('"deposed" in item or "previous_address" in item', PRODUCTION_PLAN)
    require('print("production plan gate: approved exact delivery_proof update")', PRODUCTION_PLAN)

    require("--expected-bucket-owner 920534282028", PRODUCTION_PLAN)
    require("--if-none-match '*'", PRODUCTION_PLAN)
    require("--server-side-encryption aws:kms", PRODUCTION_PLAN)
    require("--sse-kms-key-id \"$TFSTATE_KMS_KEY_ARN\"", PRODUCTION_PLAN)
    require("--checksum-algorithm SHA256", PRODUCTION_PLAN)
    assert PRODUCTION_PLAN.count("aws s3api put-object") == 1
    for field in ("VersionId", "ServerSideEncryption", "SSEKMSKeyId", "ChecksumSHA256"):
        require(field, PRODUCTION_PLAN)
    require('[[ "$S3_SHA256" == "$EXPECTED_S3_SHA256" ]]', PRODUCTION_PLAN)
    require("trap cleanup EXIT", PRODUCTION_PLAN)
    for path in ("$FOUNDATION_VARS", "$PLAN", "$PLAN_JSON", "$SSM_ERROR", "$PUT_RESPONSE", "$MANIFEST"):
        require(path, PRODUCTION_PLAN)

    for output in (
        "bucket",
        "key",
        "version_id",
        "local_sha256",
        "s3_sha256",
        "kms_key_arn",
        "release_id",
        "run_id",
        "repository",
        "commit_sha",
        "account",
        "region",
        "resource",
        "action",
        "tag_key",
        "tag_value",
    ):
        require(f"{output}: ${{{{ steps.store.outputs.{output} }}}}", PRODUCTION_PLAN)
        require(f'"{output}="', PRODUCTION_PLAN)
    require("GITHUB_STEP_SUMMARY", PRODUCTION_PLAN)
    require('tags              = local.is_production ? { delivery_proof = "issue-301" } : {}', (ROOT / "v2" / "infra" / "agentcore.tf").read_text())
    require("v2-production-plan.yml", WORKFLOW)
    require("PR CI never runs `terraform plan` or `apply`", (ROOT / "v2" / "README.md").read_text())
    require("manual production planner stores only a gated", (ROOT / "v2" / "RUNBOOK.md").read_text())


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

    _check_production_planner()
    _assert_gate_fixtures()

    print("delivery identity contract: ok")


if __name__ == "__main__":
    main()

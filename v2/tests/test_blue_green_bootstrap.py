"""Bootstrap approval and exact slot identities, without deployed credentials."""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import blue_green as gate


@pytest.mark.parametrize("environment", ["development", "production"])
def test_slot_permissions_keep_planners_off_routing(
    tmp_path: Path, environment: str
) -> None:
    root = Path(__file__).parents[2]
    source = (root / "infra/blue-green.tf").read_text()
    development, production = source.split('variable "production_blue_green"', 1)
    source = (
        development
        if environment == "development"
        else 'variable "production_blue_green"' + production
    )
    account = "903859731897" if environment == "development" else "920534282028"
    name = environment + "_blue_green"
    for suffix in ("", "_plan"):
        source = source.replace(
            f'resource "aws_iam_role_policy" "{name}{suffix}" {{', "locals {"
        )
        source = source.replace(
            f"aws_iam_role_policy.{name}[0].policy", "local.delivery"
        )
    source = re.sub(r"^  (count|name|role)\s*=.*\n", "", source, flags=re.M)
    source = source.replace("  policy = jsonencode", "  delivery = jsonencode", 1)
    source = source.replace("  policy = jsonencode", "  planner = jsonencode", 1)
    source += f'''\nvariable "environment" {{ default = "{environment}" }}
locals {{
  {environment}_delivery_distribution_arn = "arn:aws:cloudfront::{account}:distribution/EBLUE"
  {environment}_delivery_api_id = "fixedapi"
  {environment}_delivery_site_key_arn = "arn:aws:kms:us-east-1:{account}:key/fixed"
}}
output "policies" {{ value = {{ delivery = jsondecode(local.delivery), planner = jsondecode(local.planner) }} }}
'''
    (tmp_path / "main.tf").write_text(source)
    inventory = {
        name: {
            "green_runtime_id": "nova_toll_v2"
            + ("_development" if environment == "development" else "")
            + "_green-Ab123",
            "staging_distribution_id": "EGREEN",
            "continuous_deployment_policy_id": "policy-123",
        }
    }
    (tmp_path / "terraform.tfvars.json").write_text(json.dumps(inventory))
    subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["terraform", "apply", "-auto-approve", "-input=false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    policies = json.loads(
        subprocess.check_output(
            ["terraform", "output", "-json", "policies"], cwd=tmp_path
        )
    )
    for statement in policies["planner"]["Statement"]:
        for action in statement["Action"]:
            assert re.search(r":(Get|List|Describe)", action) or action in {
                "apigateway:GET",
                "s3:PutObject",
                "kms:GenerateDataKey",
                "kms:Decrypt",
            }
            if action == "s3:PutObject":
                assert all(
                    resource.endswith("/releases/*")
                    for resource in statement["Resource"]
                )
    routing = next(
        item for item in policies["delivery"]["Statement"] if item["Sid"] == "Routing"
    )
    assert routing["Resource"] == [
        f"arn:aws:cloudfront::{account}:distribution/EBLUE",
        f"arn:aws:cloudfront::{account}:distribution/EGREEN",
    ]
    assert "cloudfront:UpdateDistribution" in routing["Action"]


@pytest.mark.parametrize(
    "resource",
    [
        "aws_lambda_function.tollchat_proxy",
        "aws_cloudwatch_log_metric_filter.proxy_failure",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_errors",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_failures",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_latency",
    ],
)
def test_bootstrap_requires_exact_reviewed_binary_and_declared_move(
    resource: str,
) -> None:
    raw = b"reviewed binary plan"
    digest = hashlib.sha256(raw).hexdigest()
    change = {
        "address": f'{resource}["blue"]',
        "previous_address": resource,
        "change": {"actions": ["no-op"]},
    }
    plan: dict[str, Any] = {
        "complete": True,
        "errored": False,
        "resource_drift": [],
        "variables": {"environment": {"value": "development"}},
        "resource_changes": [change],
    }
    gate.validate_bootstrap(plan, digest, raw)
    plan["variables"]["environment"]["value"] = "production"
    with pytest.raises(gate.Rejected, match="bootstrap_environment"):
        gate.validate_bootstrap(plan, digest, raw)
    gate.validate_bootstrap(plan, digest, raw, "production")
    plan["variables"]["environment"]["value"] = "development"
    with pytest.raises(gate.Rejected, match="bootstrap_approval"):
        gate.validate_bootstrap(plan, digest, b"different binary")
    change["previous_address"] = "aws_lambda_function.loader"
    with pytest.raises(gate.Rejected, match="bootstrap_move"):
        gate.validate_bootstrap(plan, digest, raw)


@pytest.mark.skipif(shutil.which("terraform") is None, reason="Terraform is required")
def test_terraform_descriptors_reject_wildcard_runtime_identity(tmp_path: Path) -> None:
    source = (Path(__file__).parents[1] / "infra/releases.tf").read_text()
    variables = source.split('variable "active_slot"', 1)[0]
    (tmp_path / "main.tf").write_text(
        'variable "environment" { default = "development" }\n'
        + variables
        + '\noutput "slots" { value = var.release_slots }\n'
    )
    values: dict[str, Any] = {
        "release_slots": {
            name: {
                "release_id": name,
                "runtime_id": "nova_toll_v2_development"
                + ("_green" if name == "green" else "")
                + "-123",
                "runtime_key": f"releases/{name}/agentcore.zip",
                "runtime_object_version": "version1",
                "runtime_sha256": "a" * 64,
                "proxy_key": f"releases/{name}/chat-proxy.zip",
                "proxy_object_version": "version2",
                "proxy_sha256": "a" * 43 + "=",
                "runtime_environment": {},
                "proxy_environment": {},
                "asset_prefix": f"/releases/{name}",
            }
            for name in ("blue", "green")
        }
    }
    subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    for identity, success in (
        ("nova_toll_v2_development_green-123", True),
        ("*", False),
    ):
        values["release_slots"]["green"]["runtime_id"] = identity
        (tmp_path / "slots.tfvars.json").write_text(json.dumps(values))
        result = subprocess.run(
            [
                "terraform",
                "plan",
                "-input=false",
                "-refresh=false",
                "-no-color",
                "-var-file=slots.tfvars.json",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert (result.returncode == 0) == success, result.stderr
        if not success:
            assert "without wildcards" in result.stderr

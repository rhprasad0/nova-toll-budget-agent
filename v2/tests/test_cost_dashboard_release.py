"""Billing release gates against provider-generated, credential-free plans."""

import base64
import hashlib
import importlib
import json
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from scripts import cost_dashboard_release as gate

ROOT = Path(__file__).resolve().parents[2]


def test_asset_pins_and_archive_contract() -> None:
    for name, digest in gate.ASSET_SHA256.items():
        if "/" in name:
            environment, asset = name.split("/")
            content = (
                (ROOT / "v2/agent" / asset)
                .read_text()
                .replace("${environment}", environment)
                .encode()
            )
        else:
            content = (
                ROOT / "v2/agent" / ("" if name.endswith(".js") else "assets") / name
            ).read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
    builder = (ROOT / "v2/scripts/build_publisher_zip.sh").read_text()
    assert '"$V2_ROOT/lambdas/publisher/costs.py"' in builder
    assert not (ROOT / "v2/prototypes").exists()
    archive = ROOT / "v2/infra/build/publisher.zip"
    if archive.exists():
        with ZipFile(archive) as bundle:
            assert (
                bundle.read("costs.py")
                == (ROOT / "v2/lambdas/publisher/costs.py").read_bytes()
            )
            assert (
                bundle.read("handler.py")
                == (ROOT / "v2/lambdas/publisher/handler.py").read_bytes()
            )
            assert not any(
                name.endswith(("costs.json", ".env")) for name in bundle.namelist()
            )


@pytest.mark.parametrize("environment", ["development", "production"])
def test_billing_policy_limits(environment: str) -> None:
    statements = {row["Sid"]: row for row in gate.policy(environment)["Statement"]}
    assert statements["ReadAccountBilling"]["Action"] == ["ce:GetCostAndUsage"]
    assert statements["PublishSnapshot"]["Resource"].endswith("/costs.json")
    assert statements["FindSnapshot"]["Condition"] == {
        "StringEquals": {"s3:prefix": "costs.json"}
    }
    assert statements["ReadBillingKey"]["Resource"] == (
        f"arn:aws:ssm:us-east-1:{gate.ACCOUNTS[environment]}"
        ":parameter/nova-toll/openai_billing_api_key"
    )
    assert statements["DecryptBillingKey"]["Condition"]["StringEquals"] == {
        "kms:ViaService": "ssm.us-east-1.amazonaws.com",
        "kms:EncryptionContext:PARAMETER_ARN": statements["ReadBillingKey"]["Resource"],
    }
    for statement in statements.values():
        assert not any(
            action.startswith(("rds", "bedrock", "sts:"))
            for action in statement["Action"]
        )
    assert gate.ACCOUNTS[
        "production" if environment == "development" else "development"
    ] not in json.dumps(statements)


def test_routes_only_add_the_four_billing_behaviors() -> None:
    model = {
        "path_pattern": "/eval-dashboard*",
        "target_origin_id": "site",
        "allowed_methods": ["GET", "HEAD"],
    }
    before = {"ordered_cache_behavior": [model]}
    after = {
        "ordered_cache_behavior": [
            model,
            *(dict(model, path_pattern=route) for route in sorted(gate.COST_ROUTES)),
        ]
    }
    gate.routes(before, after)
    for field, value in (
        ("target_origin_id", "public-chat"),
        ("allowed_methods", ["GET", "POST"]),
    ):
        bad = deepcopy(after)
        bad["ordered_cache_behavior"][1][field] = value
        with pytest.raises(ValueError):
            gate.routes(before, bad)
    with pytest.raises(ValueError):
        gate.routes(after, before)


def test_billing_routes_keep_the_active_chat_release() -> None:
    sys.path.insert(0, str(ROOT))
    legacy = importlib.import_module("infra.delivery_plan_validator")
    rehearsal = importlib.import_module("test_blue_green")
    state = rehearsal.previous()
    before: dict[str, Any] = {
        "arn": "arn:aws:cloudfront::903859731897:distribution/E33DVF3KT7BTAC",
        "origin": [
            {"origin_id": "site"},
            {"origin_id": "documents", "origin_path": "/releases/release1"},
            {
                "origin_id": "public-chat",
                "domain_name": "blue.lambda-url.us-east-1.on.aws",
            },
        ],
        "ordered_cache_behavior": [
            {"path_pattern": "/eval-dashboard*", "target_origin_id": "site"}
        ],
    }
    after = deepcopy(before)
    after["ordered_cache_behavior"] += [
        dict(before["ordered_cache_behavior"][0], path_pattern=route)
        for route in sorted(gate.COST_ROUTES)
    ]
    item = rehearsal.change("aws_cloudfront_distribution.site", before, after)
    item.update(type="aws_cloudfront_distribution", name="site")
    item["change"].update(before_sensitive={}, after_sensitive={})
    prepared = rehearsal.plan(
        rehearsal.gate.desired(state, rehearsal.slot("green", "release2")), [item]
    )
    rehearsal.gate.validate_plan(prepared, state, "prepare")
    manifest = json.loads(
        (ROOT / "infra/development-release-manifest.json").read_text()
    )
    result = legacy.validate_plan(
        {
            "terraform_version": "1.15.8",
            "applyable": True,
            "complete": True,
            "errored": False,
            "resource_changes": [item],
        },
        manifest,
        manifest["provider_identity"],
    )
    assert result["status"] == "accepted", result
    after["origin"][2]["domain_name"] = "green.lambda-url.us-east-1.on.aws"
    with pytest.raises(rehearsal.gate.Rejected):
        rehearsal.gate.validate_plan(prepared, state, "prepare")


@pytest.mark.parametrize("environment", ["development", "production"])
def test_provider_plan_and_mutated_authority(tmp_path: Path, environment: str) -> None:
    provider_dir = ROOT / "v2/infra/.terraform/providers"
    if not shutil.which("terraform") or not provider_dir.is_dir():
        pytest.skip(
            "Run terraform -chdir=v2/infra init -backend=false for the provider-plan check"
        )
    account = gate.ACCOUNTS[environment]
    suffix = "-dev" if environment == "development" else ""
    source = (ROOT / "v2/infra/costs.tf").read_text()
    replacements = {
        "data.aws_caller_identity.current.account_id": json.dumps(account),
        "data.aws_region.current.region": '"us-east-1"',
        "aws_s3_bucket.site.id": json.dumps(f"tollchat-site-{account}{suffix}"),
        "aws_s3_bucket.site.arn": json.dumps(
            f"arn:aws:s3:::tollchat-site-{account}{suffix}"
        ),
        "aws_kms_key.site.arn": json.dumps(
            f"arn:aws:kms:us-east-1:{account}:key/{gate.SITE_KEYS[environment]}"
        ),
        "${path.module}/../agent/": str(ROOT / "v2/agent") + "/",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    source = re.sub(
        r"\s*depends_on\s*= \[aws_s3_bucket_server_side_encryption_configuration.site\]",
        "",
        source,
    )
    (tmp_path / "costs.tf").write_text(source)
    (tmp_path / "main.tf").write_text(
        """terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "6.60.0" }
  }
}
"""
        + f'''variable "environment" {{ default = "{environment}" }}
variable "publisher_package_path" {{ default = "build/publisher.zip" }}
locals {{
  suffix = "{suffix}"
  is_production = {str(environment == "production").lower()}
  log_retention_days = {30 if environment == "production" else 7}
  publisher_zip_path = "build/publisher.zip"
  publisher_zip_hash = "{base64.b64encode(bytes(32)).decode()}"
}}
'''
    )
    (tmp_path / "costs.tftest.hcl").write_text(
        'mock_provider "aws" {}\nrun "costs" { command = plan }\n'
    )
    (tmp_path / ".terraform").mkdir()
    (tmp_path / ".terraform/providers").symlink_to(
        provider_dir, target_is_directory=True
    )
    shutil.copyfile(
        ROOT / "v2/infra/.terraform.lock.hcl", tmp_path / ".terraform.lock.hcl"
    )
    result = subprocess.run(
        ["terraform", f"-chdir={tmp_path}", "test", "-json", "-verbose"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0, [
        item.get("diagnostic") for item in events if item.get("diagnostic")
    ]
    plan: dict[str, Any] = next(
        item["test_plan"] for item in events if item["type"] == "test_plan"
    )
    # terraform test omits configuration in its verbose JSON. Supply the actual
    # expression inventory from this same tested source for omitted ACL proofs.
    resources: list[dict[str, Any]] = []
    for block in re.split(r'\n(?=resource ")', source):
        match = re.match(r'resource "([^"]+)" "([^"]+)"', block)
        if match:
            resources.append(
                {
                    "address": ".".join(match.groups()),
                    "expressions": {
                        key: {} for key in re.findall(r"(?m)^\s*(\w+)\s*=", block)
                    },
                }
            )
    plan["configuration"] = {"root_module": {"resources": resources}}
    for item in plan["resource_changes"]:
        gate.validate(item, environment, plan)
        for key, value in (
            ("role", "arn:aws:iam::000000000000:role/other"),
            ("policy", "{}"),
            ("source_account", "000000000000"),
            ("handler", "handler.handler"),
            ("bucket", "other-bucket"),
            ("kms_key_id", "foreign-key"),
            ("schedule_expression", "rate(1 minute)"),
        ):
            if key in item["change"]["after"]:
                bad = deepcopy(item)
                bad["change"]["after"][key] = value
                with pytest.raises(ValueError):
                    gate.validate(bad, environment, plan)
        bad = deepcopy(item)
        bad["change"]["actions"] = ["delete"]
        with pytest.raises(ValueError):
            gate.validate(bad, environment, plan)
    iam = next(
        item
        for item in plan["resource_changes"]
        if item["address"] == "aws_iam_role.costs"
    )
    for field in ("managed_policy_arns", "inline_policy"):
        # A real create plan leaves these omitted read-back fields unknown.
        unknown_role = deepcopy(iam)
        unknown_role["change"]["after"][field] = None
        unknown_role["change"]["after_unknown"][field] = True
        gate.validate(unknown_role, environment, plan)
        bad = deepcopy(plan)
        config = next(
            resource
            for resource in bad["configuration"]["root_module"]["resources"]
            if resource["address"] == iam["address"]
        )
        config["expressions"][field] = {"references": ["untrusted.policy"]}
        with pytest.raises(ValueError):
            gate.validate(unknown_role, environment, bad)
        for resources in ([], [config, config]):
            with pytest.raises(ValueError):
                gate.validate(
                    unknown_role,
                    environment,
                    {"configuration": {"root_module": {"resources": resources}}},
                )
        unknown_role["change"]["after"][field] = [{"policy": "untrusted"}]
        with pytest.raises(ValueError):
            gate.validate(unknown_role, environment, plan)
    if environment == "development":
        sys.path.insert(0, str(ROOT))
        legacy = importlib.import_module("infra.delivery_plan_validator")
        plan = {
            "terraform_version": "1.15.8",
            "applyable": True,
            "complete": True,
            "errored": False,
            "resource_changes": plan["resource_changes"],
            "configuration": plan["configuration"],
        }
        records = legacy._parse_plan(plan)
        assert len(records) == 10
        manifest = json.loads(
            (ROOT / "infra/development-release-manifest.json").read_text()
        )
        # Retain fresh-account coverage; the committed manifest now lists updates.
        creation_manifest = deepcopy(manifest)
        by_address = {record["address"]: record for record in records}
        for declaration in creation_manifest["mutations"]:
            if declaration["address"] in by_address:
                record = by_address[declaration["address"]]
                declaration.update(
                    action=record["action"],
                    changed_fields=list(record["changed_fields"]),
                )
        result = legacy.validate_plan(
            plan, creation_manifest, manifest["provider_identity"]
        )
        assert result["status"] == "accepted", result
        # Installed resources must match the committed update declarations.
        old_policy = gate.policy(environment)
        old_policy["Statement"] = [
            row
            for row in old_policy["Statement"]
            if row["Sid"] not in {"ReadBillingKey", "DecryptBillingKey"}
        ]
        old_values = {
            "aws_lambda_function.costs": {
                "source_code_hash": base64.b64encode(b"a" * 32).decode()
            },
            "aws_iam_role_policy.costs": {"policy": json.dumps(old_policy)},
            "aws_s3_object.cost_dashboard": {"content": "previous reviewed HTML"},
            'aws_s3_object.cost_assets["costs.mjs"]': {
                "source_hash": base64.b64encode(b"a" * 32).decode()
            },
        }
        updates: list[dict[str, Any]] = []
        for item in plan["resource_changes"]:
            if item["address"] not in old_values:
                continue
            update = deepcopy(item)
            update["change"]["actions"] = ["update"]
            update["change"]["before"] = deepcopy(update["change"]["after"])
            update["change"]["before"].update(old_values[item["address"]])
            updates.append(update)
        assert len(updates) == 4
        updated_plan = {**plan, "resource_changes": updates}
        result = legacy.validate_plan(
            updated_plan, manifest, manifest["provider_identity"]
        )
        assert result["status"] == "accepted", result
        # Exercise the same real resources through the retained-slot gate.
        rehearsal = importlib.import_module("test_blue_green")
        state = rehearsal.previous()
        prepared = rehearsal.plan(
            rehearsal.gate.desired(state, rehearsal.slot("green", "release2")),
            plan["resource_changes"],
        )
        prepared["configuration"] = plan["configuration"]
        rehearsal.gate.validate_plan(prepared, state, "prepare")
        with pytest.raises(rehearsal.gate.Rejected):
            rehearsal.gate.validate_plan(prepared, state, "promote")


def test_provider_report_routes_keep_known_defaults(tmp_path: Path) -> None:
    provider_dir = ROOT / "v2/infra/.terraform/providers"
    if not shutil.which("terraform") or not provider_dir.is_dir():
        pytest.skip("Initialize the pinned Terraform provider for this check")
    blocks = re.findall(
        r'  dynamic "ordered_cache_behavior" \{\n.*?\n  }\n',
        (ROOT / "v2/infra/site.tf").read_text(),
        re.S,
    )
    assert len(blocks) == 2
    source = """terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "6.60.0" }
  }
}
"""
    for index, block in enumerate(blocks):
        block = block.replace(
            "data.aws_cloudfront_cache_policy.caching_disabled.id",
            '"4135ea2d-6df8-44a3-9df3-4b5a84be39ad"',
        ).replace(
            "aws_cloudfront_function.public_report_routes.arn",
            '"arn:aws:cloudfront::903859731897:function/test-report-routes"',
        )
        source += (
            f'resource "aws_cloudfront_distribution" "report{index}" {{\n'
            + """
  enabled = true
  origin {
    domain_name = "example.s3.amazonaws.com"
    origin_id = "site"
    s3_origin_config { origin_access_identity = "" }
  }
  default_cache_behavior {
    target_origin_id = "site"
    allowed_methods = ["GET", "HEAD"]
    cached_methods = ["GET", "HEAD"]
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
"""
            + block
            + "}\n"
        )
    (tmp_path / "main.tf").write_text(source)
    (tmp_path / "routes.tftest.hcl").write_text(
        'mock_provider "aws" {}\nrun "routes" { command = plan }\n'
    )
    (tmp_path / ".terraform").mkdir()
    (tmp_path / ".terraform/providers").symlink_to(
        provider_dir, target_is_directory=True
    )
    shutil.copyfile(
        ROOT / "v2/infra/.terraform.lock.hcl", tmp_path / ".terraform.lock.hcl"
    )
    result = subprocess.run(
        ["terraform", f"-chdir={tmp_path}", "test", "-json", "-verbose"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0, [
        row.get("diagnostic") for row in events if row.get("diagnostic")
    ]
    plan = next(row["test_plan"] for row in events if row["type"] == "test_plan")
    defaults = {
        "default_ttl": 0,
        "max_ttl": 0,
        "trusted_key_groups": [],
        "trusted_signers": [],
        "response_headers_policy_id": "",
        "realtime_log_config_arn": "",
        "origin_request_policy_id": "",
        "field_level_encryption_id": "",
        "smooth_streaming": False,
        "grpc_config": [{"enabled": False}],
    }
    for item in plan["resource_changes"]:
        after = {
            "ordered_cache_behavior": item["change"]["after"]["ordered_cache_behavior"]
        }
        before = {
            "ordered_cache_behavior": [
                dict(row, **defaults)
                for row in after["ordered_cache_behavior"]
                if row["path_pattern"] not in gate.COST_ROUTES
            ]
        }
        # Without explicit configuration, real read-back defaults differ from
        # null/unknown values when new list entries shift robots and sitemap.
        gate.routes(before, after)
        for field, value in {
            **{
                key: ["untrusted"]
                if isinstance(value, list)
                else 1
                if isinstance(value, int)
                else "untrusted"
                for key, value in defaults.items()
            },
            "grpc_config": [{"enabled": True}],
            "target_origin_id": "public-chat",
            "cache_policy_id": "untrusted",
            "allowed_methods": ["GET", "POST"],
            "viewer_protocol_policy": "allow-all",
            "function_association": [],
        }.items():
            bad = deepcopy(after)
            next(
                row
                for row in bad["ordered_cache_behavior"]
                if row["path_pattern"] == "/costs.json"
            )[field] = value
            with pytest.raises(ValueError):
                gate.routes(before, bad)
        retained = deepcopy(before)
        retained["ordered_cache_behavior"][0]["trusted_signers"] = ["existing-signer"]
        with pytest.raises(ValueError):
            gate.routes(retained, after)


@pytest.mark.parametrize("environment", ["development", "production"])
@pytest.mark.parametrize("phase", ["prepare", "promote", "recover"])
def test_first_billing_refresh_preserves_release_authority(
    environment: str, phase: str
) -> None:
    rehearsal = importlib.import_module("test_blue_green")
    suffix = "-dev" if environment == "development" else ""
    account = gate.ACCOUNTS[environment]
    name = "tollchat-v2-cost-publisher" + suffix
    before: dict[str, dict[str, Any]] = {
        "aws_cloudwatch_event_rule.costs": {
            "name": name,
            "event_bus_name": "default",
            "state": "ENABLED",
            "schedule_expression": "cron(0 8 * * ? *)"
            if suffix
            else "cron(0 9 * * ? *)",
            "is_enabled": True,
            "tags": None,
        },
        "aws_cloudwatch_log_group.costs": {
            "name": "/aws/lambda/" + name,
            "retention_in_days": 7 if suffix else 30,
            "tags": None,
        },
        "aws_iam_role.costs": {
            "name": name,
            "arn": f"arn:aws:iam::{account}:role/{name}",
            "path": "/",
            "max_session_duration": 3600,
            "force_detach_policies": False,
            "inline_policy": [],
            "tags": None,
            "assume_role_policy": json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "sts:AssumeRole",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                        }
                    ],
                }
            ),
        },
        "aws_lambda_function.costs": {
            "function_name": name,
            "role": f"arn:aws:iam::{account}:role/{name}",
            "runtime": "python3.13",
            "handler": "costs.handler",
            "architectures": ["x86_64"],
            "timeout": 300,
            "memory_size": 256,
            "reserved_concurrent_executions": 1,
            "package_type": "Zip",
            "publish": False,
            "environment": [
                {
                    "variables": {
                        "DEPLOYMENT_ENVIRONMENT": environment,
                        "COST_BUCKET": f"tollchat-site-{account}{suffix}",
                    }
                }
            ],
            "filename": "build/publisher.zip",
            "source_code_hash": base64.b64encode(b"a" * 32).decode(),
            "tags": None,
            "layers": None,
        },
        "aws_cloudfront_function.public_report_routes": {
            "name": "tollchat-v2-public-report-routes" + suffix,
            "arn": f"arn:aws:cloudfront::{account}:function/tollchat-v2-public-report-routes{suffix}",
            "runtime": "cloudfront-js-2.0",
            "publish": True,
            "comment": "Resolve canonical TollChat report directories",
            "code": (ROOT / "v2/agent/public-report-routes.js").read_text(),
            "status": "IN_PROGRESS",
        },
    }
    for asset in ("costs.html", "costs.css", "costs.mjs"):
        address = (
            "aws_s3_object.cost_dashboard"
            if asset.endswith("html")
            else f'aws_s3_object.cost_assets["{asset}"]'
        )
        asset_values: dict[str, Any] = {
            "bucket": f"tollchat-site-{account}{suffix}",
            "key": asset if asset.endswith("html") else "assets/" + asset,
            "cache_control": "no-cache",
            "tags": None,
            "metadata": None,
            "content_type": {
                "html": "text/html",
                "css": "text/css",
                "mjs": "text/javascript",
            }[asset.split(".")[-1]]
            + "; charset=utf-8",
        }
        if asset.endswith("html"):
            asset_values["content"] = (
                (ROOT / "v2/agent" / asset)
                .read_text()
                .replace("${environment}", environment)
            )
        else:
            asset_values.update(
                source="../agent/assets/" + asset,
                source_hash=base64.b64encode(
                    bytes.fromhex(gate.ASSET_SHA256[asset])
                ).decode(),
            )
        before[address] = asset_values
    drifts: list[dict[str, Any]] = []
    for address, resource in before.items():
        after = deepcopy(resource)
        for field in ("tags", "metadata"):
            if field in after:
                after[field] = {}
        if "layers" in after:
            after["layers"] = []
        if "inline_policy" in after:
            after["inline_policy"] = [
                {"name": name, "policy": json.dumps(gate.policy(environment))}
            ]
        if "status" in after:
            after["status"] = "DEPLOYED"
        drifts.append(rehearsal.change(address, resource, after))
    state = rehearsal.previous()
    if environment == "production":
        state = json.loads(
            json.dumps(state).replace(gate.ACCOUNTS["development"], account)
        )
    inputs = (
        rehearsal.gate.desired(state, rehearsal.slot("green", "release2"))
        if phase == "prepare"
        else rehearsal.gate.desired(state, promote=True)
    )
    document = rehearsal.plan(inputs, prior=state)
    document["resource_drift"] = drifts
    original = deepcopy(document)
    rehearsal.gate.validate_plan(document, state, phase)
    assert document == original
    # Every accepted read-back must still reject a neighboring authority change.
    for drift in drifts:
        for path, value in [
            (("address",), "aws_lambda_function.loader"),
            (("mode",), "data"),
            (("provider_name",), "untrusted"),
            (("previous_address",), "old"),
            (("deposed",), "old"),
            (("change", "importing"), {"id": "unexpected"}),
            (("change", "actions"), ["delete", "create"]),
            (("change", "after_unknown"), {"arn": True}),
            (("change", "after", "region"), "eu-west-1"),
        ]:
            bad = deepcopy(drift)
            target: Any = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            document["resource_drift"] = [bad]
            with pytest.raises(rehearsal.gate.Rejected, match="incomplete_or_drift"):
                rehearsal.gate.validate_plan(document, state, phase)
        for field, value in (
            ("tags", {"extra": "tag"}),
            ("metadata", {"extra": "metadata"}),
            ("layers", [{"arn": "unreviewed"}]),
            ("status", "UNASSOCIATED"),
            ("inline_policy", [{"name": name, "policy": "{}"}]),
        ):
            if field in drift["change"]["after"]:
                bad = deepcopy(drift)
                bad["change"]["after"][field] = value
                document["resource_drift"] = [bad]
                with pytest.raises(
                    rehearsal.gate.Rejected, match="incomplete_or_drift"
                ):
                    rehearsal.gate.validate_plan(document, state, phase)
    role = next(drift for drift in drifts if drift["address"] == "aws_iam_role.costs")
    if environment == "development":
        legacy_policy = gate.policy(environment)
        legacy_policy["Statement"] = [
            row
            for row in legacy_policy["Statement"]
            if row["Sid"] not in {"ReadBillingKey", "DecryptBillingKey"}
        ]
        legacy = [{"name": name, "policy": json.dumps(legacy_policy)}]
        for old, new in (
            ([], legacy),
            (legacy, role["change"]["after"]["inline_policy"]),
        ):
            transition = deepcopy(role)
            transition["change"]["before"]["inline_policy"] = old
            transition["change"]["after"]["inline_policy"] = new
            document["resource_drift"] = [transition]
            rehearsal.gate.validate_plan(document, state, phase)
        for side in ("before", "after"):
            invalid = deepcopy(transition)
            invalid["change"][side]["inline_policy"][0]["policy"] = "{}"
            document["resource_drift"] = [invalid]
            with pytest.raises(rehearsal.gate.Rejected, match="incomplete_or_drift"):
                rehearsal.gate.validate_plan(document, state, phase)
        reversed_transition = deepcopy(transition)
        (
            reversed_transition["change"]["before"],
            reversed_transition["change"]["after"],
        ) = (
            reversed_transition["change"]["after"],
            reversed_transition["change"]["before"],
        )
        document["resource_drift"] = [reversed_transition]
        with pytest.raises(rehearsal.gate.Rejected, match="incomplete_or_drift"):
            rehearsal.gate.validate_plan(document, state, phase)
    for policies in (
        role["change"]["after"]["inline_policy"] * 2,
        [
            {
                "name": name,
                "policy": json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": gate.policy(environment)["Statement"]
                        + [{"Effect": "Allow", "Action": "ssm:*", "Resource": "*"}],
                    }
                ),
            }
        ],
    ):
        bad = deepcopy(role)
        bad["change"]["after"]["inline_policy"] = policies
        document["resource_drift"] = [bad]
        with pytest.raises(rehearsal.gate.Rejected, match="incomplete_or_drift"):
            rehearsal.gate.validate_plan(document, state, phase)

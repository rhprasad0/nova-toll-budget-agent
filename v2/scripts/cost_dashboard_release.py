"""Finite billing-only additions to the existing exact-plan release gates."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, cast

ACCOUNTS = {"development": "903859731897", "production": "920534282028"}
SITE_KEYS = {
    "development": "3bc78b60-9cbe-4abd-9744-8772c78d8379",
    "production": "e6413a73-bf0f-438e-88be-74070724d5a1",
}
COST_ROUTES = {"/cost-dashboard*", "/costs.html", "/costs.json", "/assets/costs*"}
RESOURCES = {
    "aws_cloudwatch_log_group.costs",
    "aws_iam_role.costs",
    "aws_iam_role_policy.costs",
    "aws_lambda_function.costs",
    "aws_cloudwatch_event_rule.costs",
    "aws_cloudwatch_event_target.costs",
    "aws_lambda_permission.costs",
    "aws_s3_object.cost_dashboard",
    'aws_s3_object.cost_assets["costs.css"]',
    'aws_s3_object.cost_assets["costs.mjs"]',
    "aws_s3_object.evals",
    "aws_cloudfront_function.public_report_routes",
    "aws_lambda_function.publisher",
}
# Reviewed public bytes. Update these pins when changing these public assets.
ASSET_SHA256: dict[str, str] = {
    "costs.css": "caef4ba5afe4813d1424db6e4d6ca628d803843113ee8050f39a8110abfd1995",
    "costs.mjs": "be63bd9bc6f8f371a0abf6805402c2b5d1d7c271b6bfb0aa0ac1c9ce1bf2eb15",
    "public-report-routes.js": "529643c7cad9c5bb46955f9b68b10013efb9b73e442c057957032cb4a140719a",
    "development/costs.html": "b7de8751c3ee8c28faea43db150b19c1267ee3c203e02a202e290a067edc348a",
    "development/evals.html": "05150cfaa397498efbbbdef5ba173aba12db18244b87a39cbdc5d66175dab7b0",
    "production/costs.html": "cb80c0b6ee3765c7cbb020c997f0b6dc3352dc9b9bc830b0410a238e79d2a1dd",
    "production/evals.html": "1f5216ba4cb3538ab482ab5d5e3e5389e7240689db7eeb0ee9dea2ec52d6bd79",
}


def require(value: object) -> None:
    if not value:
        raise ValueError("cost_release_boundary")


def unknown(value: object) -> bool:
    if isinstance(value, dict):
        return any(unknown(child) for child in cast(dict[str, object], value).values())
    if isinstance(value, list):
        return any(unknown(child) for child in cast(list[object], value))
    require(type(value) is bool)
    return bool(value)


def policy(environment: str) -> dict[str, Any]:
    account = ACCOUNTS[environment]
    suffix = "-dev" if environment == "development" else ""
    bucket = f"arn:aws:s3:::tollchat-site-{account}{suffix}"
    name = f"tollchat-v2-cost-publisher{suffix}"
    secret = (
        f"arn:aws:ssm:us-east-1:{account}:parameter/nova-toll/openai_billing_api_key"
    )
    statements = [
        {
            "Sid": "ReadAccountBilling",
            "Effect": "Allow",
            "Action": ["ce:GetCostAndUsage"],
            "Resource": "*",
        },
        {
            "Sid": "PublishSnapshot",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject"],
            "Resource": bucket + "/costs.json",
        },
        {
            "Sid": "FindSnapshot",
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": bucket,
            "Condition": {"StringEquals": {"s3:prefix": "costs.json"}},
        },
        {
            "Sid": "SnapshotEncryption",
            "Effect": "Allow",
            "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
            "Resource": f"arn:aws:kms:us-east-1:{account}:key/{SITE_KEYS[environment]}",
            "Condition": {
                "StringEquals": {
                    "kms:ViaService": "s3.us-east-1.amazonaws.com",
                    "kms:EncryptionContext:aws:s3:arn": bucket,
                }
            },
        },
        {
            "Sid": "WriteLogs",
            "Effect": "Allow",
            "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
            "Resource": f"arn:aws:logs:us-east-1:{account}:log-group:/aws/lambda/{name}:*",
        },
        {
            "Sid": "ReadBillingKey",
            "Effect": "Allow",
            "Action": ["ssm:GetParameter"],
            "Resource": secret,
        },
        {
            "Sid": "DecryptBillingKey",
            "Effect": "Allow",
            "Action": ["kms:Decrypt"],
            "Resource": f"arn:aws:kms:us-east-1:{account}:key/*",
            "Condition": {
                "StringEquals": {
                    "kms:ViaService": "ssm.us-east-1.amazonaws.com",
                    "kms:EncryptionContext:PARAMETER_ARN": secret,
                }
            },
        },
    ]
    return {"Version": "2012-10-17", "Statement": statements}


def routes(before: dict[str, Any], after: dict[str, Any]) -> None:
    old, new = before["ordered_cache_behavior"], after["ordered_cache_behavior"]
    require(len({row["path_pattern"] for row in new}) == len(new))
    require(
        [row for row in new if row["path_pattern"] not in COST_ROUTES]
        == [row for row in old if row["path_pattern"] not in COST_ROUTES]
    )
    models = [row for row in old if row["path_pattern"] == "/eval-dashboard*"]
    require(len(models) == 1)
    expected = {path: dict(models[0], path_pattern=path) for path in COST_ROUTES}
    require(
        {row["path_pattern"]: row for row in new if row["path_pattern"] in COST_ROUTES}
        == expected
    )


def validate_drift(item: dict[str, Any], environment: str) -> None:
    """Accept only fixed billing defaults and the reviewed policy read-back."""
    address, change = item["address"], item["change"]
    fields: dict[str, set[str]] = {
        "aws_cloudfront_function.public_report_routes": set(),
        "aws_cloudwatch_event_rule.costs": {"tags"},
        "aws_cloudwatch_log_group.costs": {"tags"},
        "aws_iam_role.costs": {"tags"},
        "aws_lambda_function.costs": {"tags", "layers"},
        "aws_s3_object.cost_dashboard": {"tags", "metadata"},
        'aws_s3_object.cost_assets["costs.css"]': {"tags", "metadata"},
        'aws_s3_object.cost_assets["costs.mjs"]': {"tags", "metadata"},
    }
    require(address in fields and environment in ACCOUNTS)
    before, after = (dict(change[key]) for key in ("before", "after"))
    for field in fields[address]:
        empty: object = [] if field == "layers" else {}
        require(before[field] in (None, empty) and after[field] in (None, empty))
        before[field] = after[field] = None
    if address == "aws_iam_role.costs":
        name = "tollchat-v2-cost-publisher" + (
            "-dev" if environment == "development" else ""
        )
        current = policy(environment)
        legacy = {
            **current,
            "Statement": [
                row
                for row in current["Statement"]
                if row["Sid"] not in {"ReadBillingKey", "DecryptBillingKey"}
            ],
        }
        # aws_iam_role observes the separately managed inline policy one plan
        # after its update. Admit only the reviewed development AWS-only policy.
        for values in (before["inline_policy"], after["inline_policy"]):
            if values == []:
                continue
            require(len(values) == 1 and set(values[0]) == {"name", "policy"})
            observed = json.loads(values[0]["policy"])
            require(values[0]["name"] == name)
            require(
                observed == current
                or (environment == "development" and observed == legacy)
            )
        require(after["inline_policy"])
        if before["inline_policy"]:
            require(environment == "development")
            require(json.loads(before["inline_policy"][0]["policy"]) == legacy)
            require(json.loads(after["inline_policy"][0]["policy"]) == current)
        require(after["arn"] == f"arn:aws:iam::{ACCOUNTS[environment]}:role/{name}")
        before["inline_policy"] = after["inline_policy"] = []
    if address == "aws_cloudfront_function.public_report_routes":
        require(before["status"] == "IN_PROGRESS" and after["status"] == "DEPLOYED")
        suffix = "-dev" if environment == "development" else ""
        require(
            after["arn"]
            == f"arn:aws:cloudfront::{ACCOUNTS[environment]}:function/tollchat-v2-public-report-routes{suffix}"
        )
        after["status"] = before["status"]
    require(before == after)
    # Reuse the identity, configuration and public-byte checks after accounting
    # for provider read-back; no other drift is permitted.
    validate(
        item | {"change": change | {"before": before, "after": after}}, environment
    )


def validate(
    item: dict[str, Any], environment: str, plan: dict[str, Any] | None = None
) -> None:
    """Allow fixed identities/configuration; never deletion or replacements."""
    require(environment in ACCOUNTS)
    address, change = item["address"], item["change"]
    require(
        address in RESOURCES
        and change["actions"] in (["create"], ["update"], ["no-op"])
    )
    require(
        item.get("provider_name") == "registry.terraform.io/hashicorp/aws"
        and item.get("mode") == "managed"
    )
    require(
        not any(key in item for key in ("previous_address", "deposed"))
        and not change.get("importing")
    )
    before: dict[str, Any] = change.get("before") or {}
    after: dict[str, Any] = dict(change.get("after") or {})
    account = ACCOUNTS[environment]
    suffix = "-dev" if environment == "development" else ""
    name = "tollchat-v2-cost-publisher" + suffix
    role = f"arn:aws:iam::{account}:role/{name}"
    function = f"arn:aws:lambda:us-east-1:{account}:function:{name}"
    rule = f"arn:aws:events:us-east-1:{account}:rule/{name}"
    bucket = f"tollchat-site-{account}{suffix}"
    expected: dict[str, Any] = {}
    mutable: set[str] = set()
    computed = {"id", "arn", "tags_all"}
    empty = {"tags", "timeouts"}
    if address == "aws_iam_role.costs":
        expected = {
            "name": name,
            "path": "/",
            "max_session_duration": 3600,
            "force_detach_policies": False,
        }
        require(
            json.loads(after["assume_role_policy"])
            == {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "sts:AssumeRole",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                    }
                ],
            }
        )
        mutable = {"assume_role_policy"}
        computed |= {"unique_id", "create_date", "name_prefix"}
        empty |= {
            "description",
            "permissions_boundary",
            "managed_policy_arns",
            "inline_policy",
        }
    elif address == "aws_iam_role_policy.costs":
        expected = {"name": name, "role": name}
        require(json.loads(after["policy"]) == policy(environment))
        mutable = {"policy"}
        computed |= {"name_prefix"}
    elif address == "aws_cloudwatch_log_group.costs":
        expected = {
            "name": "/aws/lambda/" + name,
            "retention_in_days": 7 if suffix else 30,
        }
        computed |= {"name_prefix", "log_group_class", "deletion_protection_enabled"}
        empty |= {
            "kms_key_id",
            "skip_destroy",
            "deletion_protection_enabled",
            "field_index_policy",
            "data_protection_policy",
        }
    elif address == "aws_lambda_function.costs":
        expected = {
            "function_name": name,
            "role": role,
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
                        "COST_BUCKET": bucket,
                    }
                }
            ],
        }
        mutable = {"filename", "source_code_hash"}
        require(
            isinstance(after.get("filename"), str)
            and after["filename"].endswith("/publisher.zip")
        )
        require(re.fullmatch(r"[A-Za-z0-9+/]{43}=", after.get("source_code_hash", "")))
        computed |= {
            "last_modified",
            "qualified_arn",
            "qualified_invoke_arn",
            "response_streaming_invoke_arn",
            "invoke_arn",
            "version",
            "source_code_size",
            "code_sha256",
            "signing_job_arn",
            "signing_profile_version_arn",
            "logging_config",
            "ephemeral_storage",
            "tracing_config",
        }
        require(after.get("ephemeral_storage") in (None, [], [{"size": 512}]))
        require(after.get("tracing_config") in (None, [], [{"mode": "PassThrough"}]))
        for logging in cast(list[dict[str, Any]], after.get("logging_config") or []):
            require(logging.get("log_group") == "/aws/lambda/" + name)
            require(logging.get("log_format") == "Text")
            require(
                not logging.get("application_log_level")
                and not logging.get("system_log_level")
            )
        empty |= {
            "code_signing_config_arn",
            "dead_letter_config",
            "image_config",
            "image_uri",
            "kms_key_arn",
            "layers",
            "s3_bucket",
            "s3_key",
            "s3_object_version",
            "snap_start",
            "vpc_config",
            "file_system_config",
            "replace_security_groups_on_destroy",
            "replacement_security_group_ids",
            "skip_destroy",
            "durable_config",
            "capacity_provider_config",
            "publish_to",
        }
    elif address == "aws_cloudwatch_event_rule.costs":
        expected = {
            "name": name,
            "event_bus_name": "default",
            "schedule_expression": "cron(0 8 * * ? *)"
            if suffix
            else "cron(0 9 * * ? *)",
            "state": "ENABLED",
            "is_enabled": True,
        }
        computed |= {"name_prefix"}
        empty |= {
            "description",
            "event_pattern",
            "role_arn",
            "force_destroy",
        }
    elif address == "aws_cloudwatch_event_target.costs":
        expected = {
            "rule": name,
            "event_bus_name": "default",
            "target_id": "cost-publisher",
            "arn": function,
            "input": "{}",
            "retry_policy": [
                {"maximum_event_age_in_seconds": 3600, "maximum_retry_attempts": 2}
            ],
        }
        empty |= {
            "role_arn",
            "input_path",
            "input_transformer",
            "dead_letter_config",
            "force_destroy",
        }
    elif address == "aws_lambda_permission.costs":
        expected = {
            "statement_id": "DailyCostPublication",
            "action": "lambda:InvokeFunction",
            "function_name": name,
            "principal": "events.amazonaws.com",
            "source_arn": rule,
            "source_account": account,
        }
        computed |= {"statement_id_prefix"}
        empty |= {
            "qualifier",
            "event_source_token",
            "function_url_auth_type",
            "principal_org_id",
            "invoked_via_function_url",
        }
    elif address.startswith("aws_s3_object."):
        require(after.get("server_side_encryption") in (None, "aws:kms"))
        require(after.get("storage_class") in (None, "STANDARD"))
        require(
            after.get("kms_key_id")
            in (
                None,
                SITE_KEYS[environment],
                f"arn:aws:kms:us-east-1:{account}:key/{SITE_KEYS[environment]}",
            )
        )
        asset = (
            "costs.html"
            if address.endswith("cost_dashboard")
            else "evals.html"
            if address.endswith(".evals")
            else address.split('"')[1]
        )
        expected = {
            "bucket": bucket,
            "key": asset if asset.endswith(".html") else "assets/" + asset,
            "cache_control": "no-cache",
            "content_type": (
                "text/html"
                if asset.endswith(".html")
                else "text/css"
                if asset.endswith(".css")
                else "text/javascript"
            )
            + "; charset=utf-8",
        }
        mutable = {"content", "source", "source_hash"}
        if asset.endswith(".html"):
            require(
                hashlib.sha256(after["content"].encode()).hexdigest()
                == ASSET_SHA256[environment + "/" + asset]
            )
            require(not after.get("source") and not after.get("source_hash"))
        else:
            require(
                after["source_hash"]
                == base64.b64encode(bytes.fromhex(ASSET_SHA256[asset])).decode()
            )
            require(
                after.get("source", "").endswith("/assets/" + asset)
                and not after.get("content")
            )
        computed |= {
            "etag",
            "version_id",
            "checksum_crc32",
            "checksum_crc32c",
            "checksum_crc64nvme",
            "checksum_sha1",
            "checksum_sha256",
            "server_side_encryption",
            "storage_class",
            "kms_key_id",
            "bucket_key_enabled",
            "acl",
        }
        empty |= {
            "content_base64",
            "content_disposition",
            "content_encoding",
            "content_language",
            "website_redirect",
            "metadata",
            "force_destroy",
            "object_lock_legal_hold_status",
            "object_lock_mode",
            "object_lock_retain_until_date",
            "override_provider",
            "checksum_algorithm",
        }
    elif address == "aws_cloudfront_function.public_report_routes":
        expected = {
            "name": "tollchat-v2-public-report-routes" + suffix,
            "runtime": "cloudfront-js-2.0",
            "publish": True,
            "comment": "Resolve canonical TollChat report directories",
        }
        mutable = {"code"}
        require(
            hashlib.sha256(after["code"].encode()).hexdigest()
            == ASSET_SHA256["public-report-routes.js"]
        )
        computed |= {"etag", "live_stage_etag", "status"}
        empty |= {"key_value_store_associations"}
    elif address == "aws_lambda_function.publisher":
        # The existing handler is repackaged with costs.py in the same archive.
        require(
            change["actions"] == ["update"]
            and before["function_name"] == "toll-v2-report-publisher" + suffix
        )
        computed |= {"last_modified", "source_code_size", "code_sha256"}
        mutable = {"filename", "source_code_hash"}
        require(
            after.get("filename", "").endswith("/publisher.zip")
            and re.fullmatch(r"[A-Za-z0-9+/]{43}=", after.get("source_code_hash", ""))
        )
        expected = {
            key: value for key, value in before.items() if key not in mutable | computed
        }
    # Provider read-back defaults can be null in a create plan. They carry no
    # additional authority; explicitly different values still fail.
    for field, default in {
        "path": "/",
        "max_session_duration": 3600,
        "force_detach_policies": False,
        "package_type": "Zip",
        "publish": False,
        "event_bus_name": "default",
        "is_enabled": True,
    }.items():
        if field in expected and after.get(field) is None:
            after[field] = default
    omitted_defaults = {"acl", "managed_policy_arns", "inline_policy"}
    if address == "aws_lambda_function.costs":
        omitted_defaults |= {"logging_config", "tracing_config", "ephemeral_storage"}
    if address.startswith("aws_s3_object."):
        omitted_defaults |= {
            "kms_key_id",
            "server_side_encryption",
            "storage_class",
            "bucket_key_enabled",
        }
    for field in omitted_defaults:
        if change.get("after_unknown", {}).get(field) is True:
            configurations = (
                (plan or {})
                .get("configuration", {})
                .get("root_module", {})
                .get("resources", [])
            )
            matching = [
                resource
                for resource in configurations
                if resource.get("address") == address.split("[", 1)[0]
            ]
            require(
                len(matching) == 1
                and isinstance(matching[0].get("expressions"), dict)
                and field not in matching[0]["expressions"]
            )
            computed.add(field)
    require(after.get("acl") in (None, "private"))
    require(all(after.get(key) == value for key, value in expected.items()))
    for field in empty:
        require(not after.get(field))
    unknowns = change.get("after_unknown", {})
    require(
        all(not unknown(value) or key in computed for key, value in unknowns.items())
    )
    require(not unknown(change.get("after_sensitive", {})))
    # AWS adds optional target blocks; only empty default blocks are accepted.
    require(
        all(
            key in expected
            or key in mutable | computed | empty | {"region"}
            or not value
            for key, value in after.items()
        )
    )
    require(after.get("region", "us-east-1") == "us-east-1")
    if before:
        allowed = set(expected) | mutable | computed | empty
        require(
            all(
                key in allowed or before.get(key) == after.get(key)
                for key in set(before) | set(after)
            )
        )
    if change["actions"] == ["no-op"]:
        require(change["before"] == change["after"])

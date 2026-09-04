#!/usr/bin/env python3
"""Validate the one authorized development foundation replacement plan."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

RDS_ADDRESS = "aws_db_instance.main"
DEVELOPMENT_ACCOUNT = "903859731897"
DEVELOPMENT_REGION = "us-east-1"
EXPECTED_BACKEND = (
    'bucket       = "nova-toll-tfstate-903859731897"\n'
    'key          = "nova-toll/development/terraform.tfstate"\n'
    'region       = "us-east-1"\n'
    "use_lockfile = true\n"
    "encrypt      = true\n"
    'kms_key_id   = "alias/nova-toll-tfstate"\n'
)
ROUTE_CONTROL_ADDRESSES = frozenset(
    {
        "aws_ssm_document.route_control[0]",
        "aws_iam_role.route_control[0]",
        "aws_iam_role_policy.route_control[0]",
    }
)
ROUTE_CONTROL_DATA_ADDRESSES = frozenset(
    {
        "data.aws_iam_policy_document.route_control_assume[0]",
        "data.aws_iam_policy_document.route_control[0]",
    }
)
EXPECTED_MANAGED_NON_NOOP = {RDS_ADDRESS}
EXPECTED_MANAGED_NOOP_ADDRESSES = frozenset(
    {
        "aws_budgets_budget.nova_toll_monthly",
        "aws_cloudtrail.audit",
        "aws_cloudwatch_event_rule.poll_tick",
        "aws_cloudwatch_event_rule.poll_tick_i66",
        "aws_cloudwatch_event_target.fetcher",
        "aws_cloudwatch_event_target.fetcher_i66",
        "aws_cloudwatch_log_group.fetcher",
        'aws_cloudwatch_metric_alarm.bucket_storage["raw"]',
        'aws_cloudwatch_metric_alarm.bucket_storage["tfstate"]',
        "aws_cloudwatch_metric_alarm.fetcher_errors",
        "aws_cloudwatch_metric_alarm.rds_connections",
        "aws_cloudwatch_metric_alarm.rds_cpu",
        "aws_cloudwatch_metric_alarm.rds_cpu_credits",
        "aws_cloudwatch_metric_alarm.rds_free_memory",
        "aws_cloudwatch_metric_alarm.rds_free_storage",
        "aws_db_subnet_group.main",
        "aws_eip.tollchat_nat",
        "aws_iam_instance_profile.tailscale_router",
        "aws_iam_openid_connect_provider.github",
        'aws_iam_policy.development_delivery["compute"]',
        'aws_iam_policy.development_delivery["data"]',
        'aws_iam_policy.development_delivery["edge"]',
        'aws_iam_policy.development_delivery["observability"]',
        'aws_iam_policy.development_delivery["runtime"]',
        'aws_iam_policy.development_delivery["state"]',
        'aws_iam_policy.development_delivery["storage"]',
        "aws_iam_role.development_delivery[0]",
        "aws_iam_role.fetcher",
        "aws_iam_role.replay",
        "aws_iam_role.route_control[0]",
        "aws_iam_role.tailscale_router",
        "aws_iam_role_policy.fetcher",
        "aws_iam_role_policy.replay",
        "aws_iam_role_policy.route_control[0]",
        "aws_iam_role_policy.tailscale_router",
        'aws_iam_role_policy_attachment.development_delivery["compute"]',
        'aws_iam_role_policy_attachment.development_delivery["data"]',
        'aws_iam_role_policy_attachment.development_delivery["edge"]',
        'aws_iam_role_policy_attachment.development_delivery["observability"]',
        'aws_iam_role_policy_attachment.development_delivery["runtime"]',
        'aws_iam_role_policy_attachment.development_delivery["state"]',
        'aws_iam_role_policy_attachment.development_delivery["storage"]',
        "aws_iam_role_policy_attachment.fetcher_basic",
        "aws_iam_role_policy_attachment.tailscale_router_ssm",
        "aws_instance.tailscale_router",
        "aws_kms_alias.alerts",
        "aws_kms_alias.audit",
        "aws_kms_alias.raw",
        "aws_kms_alias.tfstate",
        "aws_kms_key.alerts",
        "aws_kms_key.audit",
        "aws_kms_key.raw",
        "aws_kms_key.tfstate",
        "aws_lambda_function.fetcher",
        "aws_lambda_function_event_invoke_config.fetcher",
        "aws_lambda_permission.eventbridge_invoke_fetcher",
        "aws_lambda_permission.eventbridge_invoke_fetcher_i66",
        "aws_nat_gateway.tollchat",
        "aws_route_table.tollchat_private",
        'aws_route_table_association.tollchat_private["us_east_1a"]',
        'aws_route_table_association.tollchat_private["us_east_1c"]',
        "aws_s3_bucket.agentcore_artifacts",
        "aws_s3_bucket.audit",
        "aws_s3_bucket.raw",
        "aws_s3_bucket.tfstate",
        "aws_s3_bucket_lifecycle_configuration.agentcore_artifacts",
        'aws_s3_bucket_lifecycle_configuration.hardened["audit"]',
        'aws_s3_bucket_lifecycle_configuration.hardened["raw"]',
        'aws_s3_bucket_lifecycle_configuration.hardened["tfstate"]',
        "aws_s3_bucket_notification.raw",
        'aws_s3_bucket_ownership_controls.hardened["audit"]',
        'aws_s3_bucket_ownership_controls.hardened["raw"]',
        'aws_s3_bucket_ownership_controls.hardened["tfstate"]',
        "aws_s3_bucket_policy.agentcore_artifacts",
        "aws_s3_bucket_policy.audit",
        "aws_s3_bucket_policy.raw",
        "aws_s3_bucket_policy.tfstate",
        "aws_s3_bucket_public_access_block.agentcore_artifacts",
        'aws_s3_bucket_public_access_block.hardened["audit"]',
        'aws_s3_bucket_public_access_block.hardened["raw"]',
        'aws_s3_bucket_public_access_block.hardened["tfstate"]',
        "aws_s3_bucket_server_side_encryption_configuration.agentcore_artifacts",
        'aws_s3_bucket_server_side_encryption_configuration.hardened["audit"]',
        'aws_s3_bucket_server_side_encryption_configuration.hardened["raw"]',
        'aws_s3_bucket_server_side_encryption_configuration.hardened["tfstate"]',
        "aws_s3_bucket_versioning.agentcore_artifacts",
        'aws_s3_bucket_versioning.hardened["audit"]',
        'aws_s3_bucket_versioning.hardened["raw"]',
        'aws_s3_bucket_versioning.hardened["tfstate"]',
        "aws_security_group.agentcore_endpoint",
        "aws_security_group.eventbridge_endpoint",
        "aws_security_group.rds",
        "aws_security_group.tailscale_router",
        "aws_security_group.tollchat_api_endpoint",
        "aws_sns_topic.alerts",
        "aws_sns_topic_subscription.alerts_email",
        "aws_ssm_document.route_control[0]",
        "aws_ssm_parameter.i66_token",
        "aws_ssm_parameter.i95_token",
        "aws_ssm_parameter.tailscale_authkey",
        "aws_subnet.tollchat_private_a",
        "aws_subnet.tollchat_private_c",
        "aws_vpc_endpoint.agentcore",
        "aws_vpc_endpoint.dynamodb",
        "aws_vpc_endpoint.eventbridge",
        "aws_vpc_endpoint.s3",
        "aws_vpc_endpoint.tollchat_api",
        "aws_vpc_security_group_egress_rule.tailscale_router_egress",
        'aws_vpc_security_group_ingress_rule.eventbridge_from_private["172.31.224.0/24"]',
        'aws_vpc_security_group_ingress_rule.eventbridge_from_private["172.31.225.0/24"]',
        "aws_vpc_security_group_ingress_rule.rds_from_tailscale",
        "aws_vpc_security_group_ingress_rule.tollchat_api_from_tailscale",
    }
)
PRODUCTION_ACCOUNT = "920534282028"
SOURCE_REVISION = re.compile(r"[0-9a-f]{40}")
FINAL_SNAPSHOT_IDENTIFIER = re.compile(r"[A-Za-z]([A-Za-z0-9-]*[A-Za-z0-9])?")
ROUTE_CONTROL_NAME = "nova-toll-v2-route-control-dev"
ROUTE_CONTROL_DOCUMENT_NAME = "nova-toll-v2-route-control-status-dev"
ROUTE_CONTROL_INSTANCE_ARN = (
    "arn:aws:ec2:us-east-1:903859731897:instance/i-0d33b9a9c15db93fc"
)
ROUTE_CONTROL_DOCUMENT_ARN = (
    "arn:aws:ssm:us-east-1:903859731897:document/nova-toll-v2-route-control-status-dev"
)
ROUTE_CONTROL_OIDC_ARN = (
    "arn:aws:iam::903859731897:oidc-provider/token.actions.githubusercontent.com"
)
ROUTE_CONTROL_OIDC_SUBJECT = (
    "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
)
STATE_SEED_RDS_ARN = "arn:aws:rds:us-east-1:903859731897:db:nova-toll-db"
STATE_SEED_RDS_RESOURCE_ID = "db-DMHPVKTM5V5HN3QJG2UKFDEGTI"
ROUTE_CONTROL_DOCUMENT_CONTENT = """schemaVersion: '2.2'
description: Read the enrolled router's local Tailscale identity.
mainSteps:
  - action: aws:runShellScript
    name: readTailscaleStatus
    inputs:
      timeoutSeconds: '20'
      runCommand:
        - set -eu
        - tailscale status --json"""


class ValidationError(ValueError):
    pass


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("plan is not a JSON object")
    return cast(dict[str, Any], value)


def _actions(change: dict[str, Any]) -> list[str]:
    raw_actions: object = change.get("actions")
    if (
        not isinstance(raw_actions, list)
        or not raw_actions
        or any(
            not isinstance(action, str) for action in cast(list[object], raw_actions)
        )
    ):
        raise ValidationError("resource change has an invalid action list")
    return [cast(str, action) for action in cast(list[object], raw_actions)]


def _replacement(change: dict[str, Any]) -> None:
    if change.get("replace_paths") != [["db_name"]]:
        raise ValidationError("RDS replacement path is not exactly db_name")
    before: object = change.get("before")
    after: object = change.get("after")
    if (
        not isinstance(before, dict)
        or cast(dict[str, Any], before).get("db_name") != "nova_toll"
    ):
        raise ValidationError(
            "RDS replacement does not remove the production database name"
        )
    if (
        not isinstance(after, dict)
        or cast(dict[str, Any], after).get("db_name") != "nova_toll_development"
    ):
        raise ValidationError(
            "RDS replacement does not create the development database name"
        )


def _after(change: dict[str, Any], address: str) -> dict[str, Any]:
    after: object = change.get("after")
    if not isinstance(after, dict):
        raise ValidationError(f"{address} has no concrete after value")
    return cast(dict[str, Any], after)


def _json_object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise ValidationError(f"{name} is not JSON")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValidationError(f"{name} is not JSON") from error
    if not isinstance(parsed, dict):
        raise ValidationError(f"{name} is not a JSON object")
    return cast(dict[str, Any], parsed)


def _strings(value: object, name: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        items = cast(list[object], value)
        if all(isinstance(item, str) for item in items):
            return [cast(str, item) for item in items]
    raise ValidationError(f"{name} is not a string list")


def _validate_final_snapshot_identifier(value: str) -> None:
    if (
        len(value) > 255
        or not FINAL_SNAPSHOT_IDENTIFIER.fullmatch(value)
        or "--" in value
    ):
        raise ValidationError("development final snapshot identifier is invalid")


def _validate_rds(change: dict[str, Any], final_snapshot_identifier: str) -> None:
    _replacement(change)
    before = change.get("before")
    after = _after(change, RDS_ADDRESS)
    if not isinstance(before, dict):
        raise ValidationError("RDS replacement has no concrete before value")
    before = cast(dict[str, Any], before)
    for side, values in (("before", before), ("after", after)):
        if values.get("engine") != "postgres":
            raise ValidationError(f"RDS {side} engine is not PostgreSQL")
        if values.get("publicly_accessible") is not False:
            raise ValidationError(f"RDS {side} is publicly accessible")
        if (
            values.get("db_instance_identifier", values.get("identifier"))
            != "nova-toll-db"
        ):
            raise ValidationError(
                f"RDS {side} identifier is not the development target"
            )
    if before.get("deletion_protection") is not False:
        raise ValidationError(
            "RDS deletion protection was not disabled before replacement"
        )
    if after.get("db_name") != "nova_toll_development":
        raise ValidationError("RDS after database name is not development")
    for field in (
        "storage_encrypted",
        "iam_database_authentication_enabled",
        "manage_master_user_password",
    ):
        if after.get(field) is not True:
            raise ValidationError(f"RDS {field} is not enabled")
    if after.get("deletion_protection") is not True:
        raise ValidationError("RDS deletion protection is not retained")
    if after.get("skip_final_snapshot") is not False:
        raise ValidationError("RDS final snapshot protection is not retained")
    if after.get("final_snapshot_identifier") != final_snapshot_identifier:
        raise ValidationError("RDS final snapshot identifier is missing or mismatched")
    groups = after.get("vpc_security_group_ids")
    if not isinstance(groups, list):
        raise ValidationError("RDS has no private security-group binding")
    groups_list = cast(list[object], groups)
    if not groups_list or not all(
        isinstance(group, str) and group for group in groups_list
    ):
        raise ValidationError("RDS has no private security-group binding")


def _validate_state_seed_rds(
    change: dict[str, Any],
    final_snapshot_identifier: str,
    rds_instance_arn: str | None,
    rds_resource_id: str | None,
) -> None:
    if (
        rds_instance_arn != STATE_SEED_RDS_ARN
        or rds_resource_id != STATE_SEED_RDS_RESOURCE_ID
    ):
        raise ValidationError("state-seed RDS identity is not exact")
    if change.get("replace_paths") not in (None, []):
        raise ValidationError("state-seed RDS unexpectedly replaces the instance")
    before = change.get("before")
    after = _after(change, RDS_ADDRESS)
    if not isinstance(before, dict):
        raise ValidationError("state-seed RDS has no concrete before value")
    before = cast(dict[str, Any], before)
    if change.get("after_unknown") not in (None, {}):
        raise ValidationError("state-seed RDS contains an unknown after value")
    expected_after = dict(before)
    expected_after["final_snapshot_identifier"] = final_snapshot_identifier
    if after != expected_after:
        raise ValidationError(
            "state-seed RDS changes more than the snapshot identifier"
        )
    if before.get("final_snapshot_identifier") is not None:
        raise ValidationError("state-seed RDS snapshot identifier is already set")
    for values in (before, after):
        if (
            values.get("identifier") != "nova-toll-db"
            or values.get("arn") != rds_instance_arn
            or values.get("resource_id") != rds_resource_id
            or values.get("engine") != "postgres"
            or values.get("db_name") != "nova_toll"
            or values.get("publicly_accessible") is not False
            or values.get("deletion_protection") is not True
            or values.get("skip_final_snapshot") is not False
        ):
            raise ValidationError("state-seed RDS payload is not exact")
    groups = after.get("vpc_security_group_ids")
    if not isinstance(groups, list):
        raise ValidationError("state-seed RDS has no private security-group binding")
    groups_list = cast(list[object], groups)
    if not groups_list or not all(
        isinstance(group, str) and group for group in groups_list
    ):
        raise ValidationError("state-seed RDS has no private security-group binding")


def _validate_route_document(change: dict[str, Any]) -> None:
    after = _after(change, "aws_ssm_document.route_control[0]")
    if after.get("name") != ROUTE_CONTROL_DOCUMENT_NAME:
        raise ValidationError("route-control document name is wrong")
    if (
        after.get("document_type") != "Command"
        or after.get("document_format") != "YAML"
    ):
        raise ValidationError("route-control document type or format is wrong")
    if (
        not isinstance(after.get("content"), str)
        or after["content"].strip() != ROUTE_CONTROL_DOCUMENT_CONTENT
    ):
        raise ValidationError("route-control document payload is wrong")


def _validate_route_trust(change: dict[str, Any]) -> None:
    after = _after(change, "aws_iam_role.route_control[0]")
    if after.get("name") != ROUTE_CONTROL_NAME:
        raise ValidationError("route-control role name is wrong")
    policy = _json_object(after.get("assume_role_policy"), "route-control trust")
    if set(policy) != {"Version", "Statement"} or policy.get("Version") != "2012-10-17":
        raise ValidationError("route-control trust shape is wrong")
    statements_raw = policy.get("Statement")
    if not isinstance(statements_raw, list):
        raise ValidationError("route-control trust statements are wrong")
    statements = cast(list[object], statements_raw)
    if len(statements) != 1 or not isinstance(statements[0], dict):
        raise ValidationError("route-control trust statements are wrong")
    statement = cast(dict[str, Any], statements[0])
    if set(statement) != {"Action", "Effect", "Principal", "Condition"}:
        raise ValidationError("route-control trust statement is too broad")
    if (
        _strings(statement.get("Action"), "route-control trust action")
        != ["sts:AssumeRoleWithWebIdentity"]
        or statement.get("Effect") != "Allow"
    ):
        raise ValidationError("route-control trust action is wrong")
    principal_raw = statement.get("Principal")
    if not isinstance(principal_raw, dict):
        raise ValidationError("route-control trust principal is wrong")
    principal = cast(dict[str, Any], principal_raw)
    if set(principal) != {"Federated"} or _strings(
        principal.get("Federated"), "route-control trust principal"
    ) != [ROUTE_CONTROL_OIDC_ARN]:
        raise ValidationError("route-control trust principal is wrong")
    condition_raw = statement.get("Condition")
    if not isinstance(condition_raw, dict):
        raise ValidationError("route-control trust conditions are wrong")
    condition = cast(dict[str, Any], condition_raw)
    if set(condition) != {"StringEquals"}:
        raise ValidationError("route-control trust conditions are wrong")
    equals_raw = condition.get("StringEquals")
    if not isinstance(equals_raw, dict):
        raise ValidationError("route-control trust conditions are wrong")
    equals = cast(dict[str, Any], equals_raw)
    if (
        set(equals)
        != {
            "token.actions.githubusercontent.com:aud",
            "token.actions.githubusercontent.com:sub",
        }
        or _strings(
            equals.get("token.actions.githubusercontent.com:aud"),
            "route-control trust audience",
        )
        != ["sts.amazonaws.com"]
        or _strings(
            equals.get("token.actions.githubusercontent.com:sub"),
            "route-control trust subject",
        )
        != [ROUTE_CONTROL_OIDC_SUBJECT]
    ):
        raise ValidationError("route-control trust subject is wrong")


def _validate_route_policy(change: dict[str, Any]) -> None:
    after = _after(change, "aws_iam_role_policy.route_control[0]")
    if after.get("name") != ROUTE_CONTROL_NAME:
        raise ValidationError("route-control policy name is wrong")
    policy = _json_object(after.get("policy"), "route-control policy")
    if set(policy) != {"Version", "Statement"} or policy.get("Version") != "2012-10-17":
        raise ValidationError("route-control policy shape is wrong")
    statements_raw = policy.get("Statement")
    if not isinstance(statements_raw, list):
        raise ValidationError("route-control policy statements are wrong")
    statements = cast(list[object], statements_raw)
    if len(statements) != 2 or not all(
        isinstance(statement, dict) for statement in statements
    ):
        raise ValidationError("route-control policy statements are wrong")
    statement_objects = [cast(dict[str, Any], statement) for statement in statements]
    by_sid = {
        statement.get("Sid"): statement
        for statement in statement_objects
        if isinstance(statement.get("Sid"), str)
    }
    if set(by_sid) != {"SendRouterStatusCommand", "ReadRouterStatusCommand"}:
        raise ValidationError("route-control policy statement IDs are wrong")
    send = by_sid["SendRouterStatusCommand"]
    if (
        set(send) != {"Sid", "Effect", "Action", "Resource"}
        or send.get("Effect") != "Allow"
    ):
        raise ValidationError("route-control send policy is broad")
    if _strings(send.get("Action"), "route-control send action") != [
        "ssm:SendCommand"
    ] or sorted(
        _strings(send.get("Resource"), "route-control send resources")
    ) != sorted([ROUTE_CONTROL_INSTANCE_ARN, ROUTE_CONTROL_DOCUMENT_ARN]):
        raise ValidationError("route-control send policy resources are wrong")
    read = by_sid["ReadRouterStatusCommand"]
    if (
        set(read) != {"Sid", "Effect", "Action", "Resource", "Condition"}
        or read.get("Effect") != "Allow"
    ):
        raise ValidationError("route-control read policy is broad")
    if _strings(read.get("Action"), "route-control read action") != [
        "ssm:GetCommandInvocation"
    ] or _strings(read.get("Resource"), "route-control read resource") != ["*"]:
        raise ValidationError("route-control read policy action is wrong")
    condition_raw = read.get("Condition")
    if not isinstance(condition_raw, dict):
        raise ValidationError("route-control read policy conditions are wrong")
    condition = cast(dict[str, Any], condition_raw)
    if set(condition) != {"StringEquals"}:
        raise ValidationError("route-control read policy conditions are wrong")
    equals_raw = condition.get("StringEquals")
    if not isinstance(equals_raw, dict):
        raise ValidationError("route-control read policy conditions are wrong")
    equals = cast(dict[str, Any], equals_raw)
    if set(equals) != {"aws:RequestedRegion"} or _strings(
        equals.get("aws:RequestedRegion"), "route-control read region"
    ) != ["us-east-1"]:
        raise ValidationError("route-control read policy region is wrong")


def _validate_security_rule(address: str, after: dict[str, Any]) -> None:
    if address == "aws_vpc_security_group_ingress_rule.rds_from_tailscale":
        if (
            after.get("from_port") != 5432
            or after.get("to_port") != 5432
            or after.get("ip_protocol") != "tcp"
            or not after.get("referenced_security_group_id")
            or after.get("cidr_ipv4") is not None
            or after.get("cidr_ipv6") is not None
        ):
            raise ValidationError("RDS security-group ingress is permissive")
    elif address == "aws_vpc_security_group_egress_rule.tailscale_router_egress":
        if (
            after.get("cidr_ipv4") != "0.0.0.0/0"
            or after.get("ip_protocol") != "-1"
            or after.get("security_group_id") in (None, "")
        ):
            raise ValidationError("router egress no longer matches the reviewed rule")
    elif "security_group" in address:
        for key in ("cidr_blocks", "ipv6_cidr_blocks"):
            values = after.get(key)
            if values is not None and not isinstance(values, list):
                raise ValidationError("security-group rule is malformed")
            if isinstance(values, list) and ("0.0.0.0/0" in values or "::/0" in values):
                raise ValidationError("unexpected public security-group rule")
        ingress = after.get("ingress")
        if ingress is not None and not isinstance(ingress, list):
            raise ValidationError("security-group ingress is malformed")
        if isinstance(ingress, list):
            for raw_rule in cast(list[object], ingress):
                if not isinstance(raw_rule, dict):
                    raise ValidationError("security-group ingress is malformed")
                rule = cast(dict[str, Any], raw_rule)
                for key, public_cidr in (
                    ("cidr_blocks", "0.0.0.0/0"),
                    ("ipv6_cidr_blocks", "::/0"),
                ):
                    values = rule.get(key, [])
                    if isinstance(values, list) and public_cidr in values:
                        raise ValidationError(
                            "unexpected public security-group ingress"
                        )


def validate_plan(
    document: object,
    final_snapshot_identifier: str,
    *,
    mode: str = "replacement",
    rds_instance_arn: str | None = None,
    rds_resource_id: str | None = None,
) -> dict[str, int]:
    _validate_final_snapshot_identifier(final_snapshot_identifier)
    if mode not in ("replacement", "state-seed"):
        raise ValidationError("plan mode is invalid")
    document = _object(document)
    raw_changes: object = document.get("resource_changes")
    if not isinstance(raw_changes, list):
        raise ValidationError("resource_changes is not an array")
    changes = cast(list[object], raw_changes)

    seen: set[str] = set()
    non_noop: set[str] = set()
    managed_noops: set[str] = set()
    route_control_noops: set[str] = set()
    counts = {
        "managed_noop": 0,
        "rds_replacement" if mode == "replacement" else "rds_state_seed": 0,
        "route_control_noop": 0,
        "data_read": 0,
    }
    for raw_item in changes:
        item = _object(raw_item)
        if "deposed" in item or "moved" in item:
            raise ValidationError("plan contains a deposed or moved resource")
        address = item.get("address")
        resource_mode = item.get("mode")
        change = item.get("change")
        if (
            not isinstance(address, str)
            or not address
            or resource_mode not in ("managed", "data")
        ):
            raise ValidationError("resource change has an invalid mode or address")
        if "production" in address.lower() or re.search(
            r'(?:^|[.\[\]"])prod(?:$|[.\[\]"])', address, re.IGNORECASE
        ):
            raise ValidationError("plan contains an explicit production resource")
        if address in seen:
            raise ValidationError("plan contains a duplicate resource address")
        seen.add(address)
        if PRODUCTION_ACCOUNT in json.dumps(
            item, sort_keys=True, separators=(",", ":")
        ):
            raise ValidationError("plan contains the production account")
        change = _object(change)
        actions = _actions(change)
        if resource_mode == "data":
            if address not in ROUTE_CONTROL_DATA_ADDRESSES or actions != ["read"]:
                raise ValidationError("plan contains an unexpected data action")
            counts["data_read"] += 1
            non_noop.add(address)
            continue
        if actions == ["no-op"]:
            if change.get("replace_paths") not in (None, []):
                raise ValidationError("no-op resource unexpectedly replaces a resource")
            if address == "aws_ssm_document.route_control[0]":
                _validate_route_document(change)
                route_control_noops.add(address)
                counts["route_control_noop"] += 1
            elif address == "aws_iam_role.route_control[0]":
                _validate_route_trust(change)
                route_control_noops.add(address)
                counts["route_control_noop"] += 1
            elif address == "aws_iam_role_policy.route_control[0]":
                _validate_route_policy(change)
                route_control_noops.add(address)
                counts["route_control_noop"] += 1
            elif "security_group" in address:
                _validate_security_rule(address, _after(change, address))
            managed_noops.add(address)
            counts["managed_noop"] += 1
            continue
        if address == RDS_ADDRESS and actions == ["delete", "create"]:
            if mode != "replacement":
                raise ValidationError("state-seed plan replaces the RDS instance")
            _validate_rds(change, final_snapshot_identifier)
            counts["rds_replacement"] += 1
            non_noop.add(address)
            continue
        if address == RDS_ADDRESS and actions == ["update"]:
            if mode != "state-seed":
                raise ValidationError("replacement plan updates the RDS instance")
            _validate_state_seed_rds(
                change,
                final_snapshot_identifier,
                rds_instance_arn,
                rds_resource_id,
            )
            counts["rds_state_seed"] += 1
            non_noop.add(address)
            continue
        raise ValidationError("plan contains an unauthorized managed action")

    managed_non_noop = non_noop - ROUTE_CONTROL_DATA_ADDRESSES
    data_non_noop = non_noop & ROUTE_CONTROL_DATA_ADDRESSES
    if (
        managed_non_noop != EXPECTED_MANAGED_NON_NOOP
        or data_non_noop not in (set(), set(ROUTE_CONTROL_DATA_ADDRESSES))
        or managed_noops != set(EXPECTED_MANAGED_NOOP_ADDRESSES)
        or route_control_noops != set(ROUTE_CONTROL_ADDRESSES)
    ):
        raise ValidationError("plan does not contain exactly the authorized actions")
    return counts


def validate_context(
    account: str | None,
    region: str | None,
    backend: Path | None,
    source_revision: str | None,
    source_root: Path | None,
) -> None:
    if (
        account != DEVELOPMENT_ACCOUNT
        or region != DEVELOPMENT_REGION
        or backend is None
    ):
        raise ValidationError("plan context is not the development account and region")
    if backend.read_text(encoding="utf-8") != EXPECTED_BACKEND:
        raise ValidationError("plan backend is not the development backend")
    if (
        source_revision is None
        or not SOURCE_REVISION.fullmatch(source_revision)
        or source_root is None
    ):
        raise ValidationError("plan source revision is not pinned")
    try:
        actual_revision = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise ValidationError("plan source revision cannot be verified") from None
    if actual_revision != source_revision:
        raise ValidationError("plan source revision does not match the source root")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--final-snapshot-identifier", required=True)
    parser.add_argument(
        "--mode", choices=("replacement", "state-seed"), default="replacement"
    )
    parser.add_argument("--rds-instance-arn")
    parser.add_argument("--rds-resource-id")
    args = parser.parse_args()
    try:
        validate_context(
            args.account,
            args.region,
            args.backend,
            args.source_revision,
            args.source_root,
        )
        document = json.loads(args.plan.read_text(encoding="utf-8"))
        counts = validate_plan(
            document,
            args.final_snapshot_identifier,
            mode=args.mode,
            rds_instance_arn=args.rds_instance_arn,
            rds_resource_id=args.rds_resource_id,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
        print("development foundation plan rejected", file=sys.stderr)
        return 1
    print(json.dumps(counts, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

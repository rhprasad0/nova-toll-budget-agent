#!/usr/bin/env python3
"""Validate a legacy Terraform destroy plan without contacting Terraform or AWS.

The archived state is evidence, not deletion authority.  A fixed address/type
inventory describes the only legacy application objects this procedure may
retire, and a separately captured live-identity manifest must agree with that
state before a plan can pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

PRODUCTION_ACCOUNT = "920534282028"
CANONICAL_SOURCE_COMMIT = "4c1f684c02bf81187c2cc5f15883727cf15b11ee"
LIVE_IDENTITY_SOURCE = "account-scoped-live-api-v1"
CANONICAL_SOURCE_REMOTES = frozenset(
    {
        "git@github.com:rhprasad0/nova-toll-budget-agent.git",
        "https://github.com/rhprasad0/nova-toll-budget-agent.git",
    }
)
RETAINED = frozenset(
    {
        "cloudflare_dns_record.apex[0]",
        'cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"]',
        "aws_bedrock_guardrail.tollchat",
        "aws_bedrock_guardrail_version.tollchat",
    }
)

# Reviewed root addresses from compatibility revision 4c1f684.  A state entry
# outside this set is never deletion authority, even if it appears in a plan.
LEGACY_APPLICATION_BASE_ADDRESSES = frozenset(
    {
        "aws_acm_certificate.site",
        "aws_acm_certificate_validation.site",
        "aws_api_gateway_deployment.tollchat",
        "aws_api_gateway_integration.tollchat_proxy",
        "aws_api_gateway_integration.tollchat_root",
        "aws_api_gateway_method.tollchat_proxy",
        "aws_api_gateway_method.tollchat_root",
        "aws_api_gateway_method_settings.tollchat",
        "aws_api_gateway_resource.tollchat_proxy",
        "aws_api_gateway_rest_api.tollchat",
        "aws_api_gateway_rest_api_policy.tollchat",
        "aws_api_gateway_stage.tollchat",
        "aws_athena_named_query.recent_routes",
        "aws_athena_named_query.top_routes",
        "aws_athena_workgroup.agent_reports",
        "aws_bedrock_guardrail.tollchat",
        "aws_bedrock_guardrail_version.tollchat",
        "aws_bedrockagentcore_agent_runtime.tollchat",
        "aws_bedrockagentcore_agent_runtime_endpoint.tollchat",
        "aws_bedrockagentcore_resource_policy.tollchat",
        "aws_cloudfront_distribution.site",
        "aws_cloudfront_function.public_chat_routes",
        "aws_cloudfront_function.public_report_routes",
        "aws_cloudfront_origin_access_control.public_chat",
        "aws_cloudfront_origin_access_control.site",
        "aws_cloudfront_response_headers_policy.development_noindex",
        "aws_cloudwatch_event_rule.agent_usage_rollup",
        "aws_cloudwatch_event_rule.raw_objects",
        "aws_cloudwatch_event_rule.usage_publisher",
        "aws_cloudwatch_event_target.agent_usage_rollup",
        "aws_cloudwatch_event_target.loader",
        "aws_cloudwatch_event_target.usage_publisher",
        "aws_cloudwatch_log_group.agent_usage_rollup",
        "aws_cloudwatch_log_group.agentcore_runtime",
        "aws_cloudwatch_log_group.loader",
        "aws_cloudwatch_log_group.publisher",
        "aws_cloudwatch_log_group.tollchat_proxy",
        "aws_cloudwatch_log_group.usage_publisher",
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
        "aws_dynamodb_table.tollchat_sessions",
        "aws_glue_catalog_database.agent_reports",
        "aws_glue_catalog_table.agent_registry",
        "aws_glue_catalog_table.agent_report_generations",
        "aws_glue_catalog_table.agent_report_rollup_completions",
        "aws_glue_catalog_table.agent_report_rollups",
        "aws_glue_catalog_table.waf_logs",
        "aws_iam_role.agent_usage_rollup",
        "aws_iam_role.loader",
        "aws_iam_role.publisher",
        "aws_iam_role.publisher_scheduler",
        "aws_iam_role.timed_checks",
        "aws_iam_role.tollchat_proxy",
        "aws_iam_role.tollchat_runtime",
        "aws_iam_role.usage_publisher",
        "aws_iam_role_policy.agent_usage_rollup",
        "aws_iam_role_policy.loader",
        "aws_iam_role_policy.publisher",
        "aws_iam_role_policy.publisher_scheduler",
        "aws_iam_role_policy.timed_checks",
        "aws_iam_role_policy.tollchat_proxy",
        "aws_iam_role_policy.tollchat_runtime",
        "aws_iam_role_policy.usage_publisher",
        "aws_iam_role_policy_attachment.loader_vpc",
        "aws_iam_role_policy_attachment.publisher_vpc",
        "aws_iam_role_policy_attachment.tollchat_proxy_vpc",
        "aws_kms_alias.agent_measurement",
        "aws_kms_alias.site",
        "aws_kms_key.agent_measurement",
        "aws_kms_key.site",
        "aws_lambda_alias.tollchat_live",
        "aws_lambda_function.agent_usage_rollup",
        "aws_lambda_function.loader",
        "aws_lambda_function.publisher",
        "aws_lambda_function.tollchat_proxy",
        "aws_lambda_function.usage_publisher",
        "aws_lambda_function_event_invoke_config.loader",
        "aws_lambda_function_event_invoke_config.publisher",
        "aws_lambda_function_url.public_chat",
        "aws_lambda_permission.agent_usage_rollup",
        "aws_lambda_permission.eventbridge_invoke",
        "aws_lambda_permission.public_chat_invoke",
        "aws_lambda_permission.public_chat_url",
        "aws_lambda_permission.tollchat_api",
        "aws_lambda_permission.usage_publisher",
        "aws_lambda_provisioned_concurrency_config.tollchat",
        "aws_s3_bucket.agent_measurement",
        "aws_s3_bucket.site",
        "aws_s3_bucket_lifecycle_configuration.agent_measurement",
        "aws_s3_bucket_policy.agent_measurement",
        "aws_s3_bucket_policy.site",
        "aws_s3_bucket_public_access_block.agent_measurement",
        "aws_s3_bucket_public_access_block.site",
        "aws_s3_bucket_server_side_encryption_configuration.agent_measurement",
        "aws_s3_bucket_server_side_encryption_configuration.site",
        "aws_s3_object.agent_registry",
        "aws_s3_object.agentcore",
        "aws_s3_object.chat",
        "aws_s3_object.faq",
        "aws_s3_object.index",
        "aws_s3_object.privacy",
        "aws_s3_object.robots",
        "aws_s3_object.site_assets",
        "aws_s3_object.terms",
        "aws_s3_object.tollchat_proxy",
        "aws_s3_object.usage",
        "aws_scheduler_schedule.publisher",
        "aws_security_group.loader",
        "aws_security_group.publisher",
        "aws_security_group.tollchat_proxy",
        "aws_security_group.tollchat_runtime",
        "aws_sqs_queue.delivery_failure",
        "aws_sqs_queue.invoke_failure",
        "aws_sqs_queue.publisher_delivery_failure",
        "aws_sqs_queue.publisher_invoke_failure",
        "aws_sqs_queue_policy.delivery_failure",
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
        "aws_wafv2_web_acl.public_chat",
        "aws_wafv2_web_acl_logging_configuration.agent_reports",
        "cloudflare_dns_record.apex",
        "cloudflare_dns_record.site_cert_validation",
        "cloudflare_dns_record.www",
    }
)

# Approved data sources are parsed separately and can never authorize a delete.
APPROVED_DATA_BASE_ADDRESSES = frozenset(
    {
        "data.archive_file.agent_usage_rollup",
        "data.archive_file.placeholder",
        "data.archive_file.usage_publisher",
        "data.aws_caller_identity.current",
        "data.aws_cloudfront_cache_policy.caching_disabled",
        "data.aws_cloudfront_origin_request_policy.all_except_host",
        "data.aws_db_instance.main",
        "data.aws_iam_policy_document.agent_measurement_bucket",
        "data.aws_iam_policy_document.agent_measurement_kms",
        "data.aws_iam_policy_document.agent_usage_rollup",
        "data.aws_iam_policy_document.agentcore_assume",
        "data.aws_iam_policy_document.delivery_failure",
        "data.aws_iam_policy_document.lambda_assume",
        "data.aws_iam_policy_document.loader",
        "data.aws_iam_policy_document.publisher",
        "data.aws_iam_policy_document.publisher_scheduler",
        "data.aws_iam_policy_document.publisher_scheduler_assume",
        "data.aws_iam_policy_document.site_kms",
        "data.aws_iam_policy_document.timed_checks",
        "data.aws_iam_policy_document.timed_checks_assume",
        "data.aws_iam_policy_document.tollchat_proxy",
        "data.aws_iam_policy_document.tollchat_runtime",
        "data.aws_iam_policy_document.usage_publisher",
        "data.aws_kms_alias.raw",
        "data.aws_prefix_list.dynamodb",
        "data.aws_prefix_list.s3",
        "data.aws_region.current",
        "data.aws_s3_bucket.agentcore_artifacts",
        "data.aws_s3_bucket.raw",
        "data.aws_security_group.agentcore_endpoint",
        "data.aws_security_group.eventbridge_endpoint",
        "data.aws_security_group.rds",
        "data.aws_sns_topic.alerts",
        "data.aws_subnet.tollchat_private_a",
        "data.aws_subnet.tollchat_private_c",
        "data.aws_subnets.default",
        "data.aws_vpc.default",
        "data.aws_vpc_endpoint.agentcore",
        "data.aws_vpc_endpoint.tollchat_api",
        "data.cloudflare_zone.tollchat",
    }
)

# Explicit denylist for foundation/shared/new-development types and identities.
FOUNDATION_SHARED_DENY_TYPES = frozenset(
    {
        "aws_db_instance",
        "aws_db_subnet_group",
        "aws_rds_cluster",
        "aws_rds_cluster_instance",
        "aws_vpc",
        "aws_subnet",
        "aws_subnets",
        "aws_route",
        "aws_route_table",
        "aws_route_table_association",
        "aws_nat_gateway",
        "aws_internet_gateway",
        "aws_vpc_endpoint",
        "aws_network_acl",
        "aws_network_interface",
        "aws_eip",
        "aws_tailscale_router",
    }
)
FOUNDATION_SHARED_DENY_MARKERS = (
    "foundation",
    "shared",
    "nova-toll-db",
    "nova_toll",
    "nova-toll/terraform.tfstate",
)
NEW_DEVELOPMENT_DENY_MARKERS = ("903859731897", "E33DVF3KT7BTAC")
SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:/_.@+=,-]{0,1023}$")
CF_RECORD_ID = re.compile(r"^[0-9a-f]{32}$")
CLOUDFRONT_ID = re.compile(r"^E[A-Z0-9]+$")
LEGACY_APPLICATION_REMOTE_ID_CONSTRAINTS = {
    "cloudflare_dns_record": CF_RECORD_ID,
    "aws_cloudfront_distribution": CLOUDFRONT_ID,
}
LEGACY_ADDRESS_TYPES = {
    address: address.split(".", 1)[0] for address in LEGACY_APPLICATION_BASE_ADDRESSES
}

# The compatibility checkout is the development environment.  Count and
# for_each resources therefore have a fixed, reviewed instance set; their
# unindexed base addresses are not interchangeable with an arbitrary index.
_INDEXED_BASE_ADDRESSES = frozenset(
    {
        "aws_bedrockagentcore_resource_policy.tollchat",
        "aws_cloudwatch_log_group.agentcore_runtime",
        "aws_cloudwatch_metric_alarm.failure_queues",
        "aws_cloudwatch_metric_alarm.freshness",
        "aws_cloudwatch_metric_alarm.publisher_failure_queues",
        "aws_cloudfront_response_headers_policy.development_noindex",
        "aws_lambda_provisioned_concurrency_config.tollchat",
        "aws_s3_object.site_assets",
        "cloudflare_dns_record.apex",
        "cloudflare_dns_record.site_cert_validation",
        "cloudflare_dns_record.www",
    }
)
LEGACY_APPLICATION_INSTANCE_ADDRESSES = frozenset(
    (LEGACY_APPLICATION_BASE_ADDRESSES - _INDEXED_BASE_ADDRESSES)
    | {
        'aws_bedrockagentcore_resource_policy.tollchat["endpoint"]',
        'aws_bedrockagentcore_resource_policy.tollchat["runtime"]',
        'aws_cloudwatch_log_group.agentcore_runtime["DEFAULT"]',
        'aws_cloudwatch_log_group.agentcore_runtime["preview"]',
        'aws_cloudwatch_metric_alarm.failure_queues["delivery"]',
        'aws_cloudwatch_metric_alarm.failure_queues["invoke"]',
        'aws_cloudwatch_metric_alarm.freshness["i66"]',
        'aws_cloudwatch_metric_alarm.freshness["i95"]',
        'aws_cloudwatch_metric_alarm.publisher_failure_queues["delivery"]',
        'aws_cloudwatch_metric_alarm.publisher_failure_queues["invoke"]',
        "aws_cloudfront_response_headers_policy.development_noindex[0]",
        "cloudflare_dns_record.apex[0]",
        'cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"]',
        'aws_s3_object.site_assets["LICENSE.txt"]',
        'aws_s3_object.site_assets["chat-markdown.mjs"]',
        'aws_s3_object.site_assets["commute-estimates.json"]',
        'aws_s3_object.site_assets["commute-map.mjs"]',
        'aws_s3_object.site_assets["commute-routes.mjs"]',
        'aws_s3_object.site_assets["coverage-locations.json"]',
        'aws_s3_object.site_assets["favicon.png"]',
        'aws_s3_object.site_assets["maplibre-gl-6.0.0/LICENSE.txt"]',
        'aws_s3_object.site_assets["maplibre-gl-6.0.0/maplibre-gl-shared.mjs"]',
        'aws_s3_object.site_assets["maplibre-gl-6.0.0/maplibre-gl-worker.mjs"]',
        'aws_s3_object.site_assets["maplibre-gl-6.0.0/maplibre-gl.css"]',
        'aws_s3_object.site_assets["maplibre-gl-6.0.0/maplibre-gl.mjs"]',
        'aws_s3_object.site_assets["markdown-it.esm.min.mjs"]',
        'aws_s3_object.site_assets["tollchat-annual-commute-example.png"]',
        'aws_s3_object.site_assets["tollchat-logo.png"]',
    }
)


@dataclass(frozen=True)
class StateEntry:
    type: str
    identifier: str


@dataclass(frozen=True)
class StateSnapshot:
    managed: dict[str, StateEntry]
    data: frozenset[str]


class ValidationError(Exception):
    """The private state or plan cannot be approved for retirement."""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError from error
    if not isinstance(value, dict):
        raise ValidationError
    return cast(dict[str, Any], value)


def _remote_id(value: object) -> str:
    if not isinstance(value, dict):
        raise ValidationError
    value = cast(dict[str, Any], value)
    direct: object = value.get("id")
    attributes = value.get("attributes")
    if isinstance(attributes, dict):
        nested: object | None = cast(dict[str, Any], attributes).get("id")
    else:
        nested = None
    if direct is not None and nested is not None and direct != nested:
        raise ValidationError
    identifier = direct if direct is not None else nested
    if not isinstance(identifier, str) or not SAFE_REMOTE_ID.fullmatch(identifier):
        raise ValidationError
    return identifier


def _address(resource: dict[str, Any], instance: dict[str, Any], count: int) -> str:
    explicit = resource.get("address")
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit:
            raise ValidationError
        base = explicit
    else:
        kind = resource.get("type")
        name = resource.get("name")
        module = resource.get("module")
        mode = resource.get("mode", "managed")
        if module is not None and (not isinstance(module, str) or not module):
            raise ValidationError
        if (
            not isinstance(kind, str)
            or not kind
            or not isinstance(name, str)
            or not name
            or mode not in ("managed", "data")
        ):
            raise ValidationError
        prefix = "data." if mode == "data" else ""
        base = f"{prefix}{module + '.' if module else ''}{kind}.{name}"
    index = instance.get("index_key")
    if index is None:
        if count != 1:
            raise ValidationError
        return base
    if isinstance(index, bool) or not isinstance(index, (str, int, float)):
        raise ValidationError
    # Terraform emits integer count keys or string for_each keys.  Do not
    # normalize a floating-point value into a reviewed count index.
    if isinstance(index, float):
        raise ValidationError
    value: int | str = index
    suffix = (
        str(value)
        if isinstance(value, int)
        else json.dumps(value, separators=(",", ":"))
    )
    if explicit is not None and base.endswith(f"[{suffix}]"):
        return base
    return f"{base}[{suffix}]"


def _base_address(address: str) -> str:
    return address.split("[", 1)[0]


def _validate_managed_address(
    address: str, identifier: str, resource_type: str | None = None
) -> None:
    base = _base_address(address)
    address_type = base.split(".", 1)[0] if "." in base else ""
    if address_type in FOUNDATION_SHARED_DENY_TYPES:
        raise ValidationError
    if base not in LEGACY_APPLICATION_BASE_ADDRESSES:
        raise ValidationError
    if address not in LEGACY_APPLICATION_INSTANCE_ADDRESSES:
        raise ValidationError
    if resource_type is not None and resource_type != LEGACY_ADDRESS_TYPES[base]:
        raise ValidationError
    # Index keys are application names (for example a bundled asset named
    # ``maplibre-gl-shared.mjs``), not ownership evidence.  Apply the
    # denylist to the reviewed base address and remote identity only so a
    # harmless for_each key cannot impersonate a foundation/shared object.
    lowered = f"{base}\0{identifier}".lower()
    if any(marker.lower() in lowered for marker in FOUNDATION_SHARED_DENY_MARKERS):
        raise ValidationError
    if any(marker.lower() in lowered for marker in NEW_DEVELOPMENT_DENY_MARKERS):
        raise ValidationError
    constraint = LEGACY_APPLICATION_REMOTE_ID_CONSTRAINTS.get(address_type)
    if constraint is not None and not constraint.fullmatch(identifier):
        raise ValidationError


def _state_entries(document: dict[str, Any]) -> StateSnapshot:
    resources = document.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ValidationError
    resources = cast(list[object], resources)
    managed: dict[str, StateEntry] = {}
    data: set[str] = set()
    for raw_resource in resources:
        if not isinstance(raw_resource, dict):
            raise ValidationError
        resource = cast(dict[str, Any], raw_resource)
        mode = resource.get("mode", "managed")
        if mode not in ("managed", "data"):
            raise ValidationError
        instances = resource.get("instances")
        if not isinstance(instances, list) or not instances:
            raise ValidationError
        instances = cast(list[object], instances)
        resource_type = resource.get("type")
        if not isinstance(resource_type, str) or not resource_type:
            raise ValidationError
        for raw_instance in instances:
            if not isinstance(raw_instance, dict):
                raise ValidationError
            instance = cast(dict[str, Any], raw_instance)
            address = _address(resource, instance, len(instances))
            if address in managed or address in data:
                raise ValidationError
            if mode == "data":
                if _base_address(address) not in APPROVED_DATA_BASE_ADDRESSES:
                    raise ValidationError
                data.add(address)
                continue
            identifier = _remote_id(instance)
            _validate_managed_address(address, identifier, resource_type)
            managed[address] = StateEntry(resource_type, identifier)
    if not managed:
        raise ValidationError
    if managed.keys() != LEGACY_APPLICATION_INSTANCE_ADDRESSES:
        raise ValidationError
    return StateSnapshot(managed, frozenset(data))


def _plan_entries(
    document: dict[str, Any], state: StateSnapshot
) -> dict[str, StateEntry]:
    changes = document.get("resource_changes")
    if not isinstance(changes, list):
        raise ValidationError
    changes = cast(list[object], changes)
    entries: dict[str, StateEntry] = {}
    seen: set[str] = set()
    known = set(state.managed) | set(state.data)
    for raw_item in changes:
        if not isinstance(raw_item, dict):
            raise ValidationError
        item = cast(dict[str, Any], raw_item)
        mode = item.get("mode", "managed")
        if mode not in ("managed", "data"):
            raise ValidationError
        address = item.get("address")
        change = item.get("change")
        if not isinstance(address, str) or not address or not isinstance(change, dict):
            raise ValidationError
        change = cast(dict[str, Any], change)
        if address not in known or address in seen:
            raise ValidationError
        if (address in state.data) != (mode == "data"):
            raise ValidationError
        seen.add(address)
        actions = change.get("actions")
        if actions in ([], ["no-op"]):
            continue
        if mode == "data":
            # Terraform may refresh an approved data source during planning;
            # reads are not deletion authority and are kept out of the digest.
            if actions == ["read"]:
                continue
            raise ValidationError
        if address not in state.managed:
            raise ValidationError
        if actions != ["delete"] or change.get("after") is not None:
            raise ValidationError
        before = change.get("before")
        identifier = _remote_id(before)
        expected = state.managed[address]
        if identifier != expected.identifier:
            raise ValidationError
        item_type = item.get("type", expected.type)
        if item_type != expected.type:
            raise ValidationError
        if address in entries:
            raise ValidationError
        entries[address] = expected
    return entries


def _identity_entries(document: dict[str, Any]) -> dict[str, StateEntry]:
    if (
        set(document)
        != {
            "manifest",
            "account_id",
            "source_remote",
            "source_commit",
            "identity_source",
            "resources",
        }
        or document.get("manifest") != "legacy-live-identity-v1"
        or document.get("account_id") != PRODUCTION_ACCOUNT
        or document.get("source_remote") not in CANONICAL_SOURCE_REMOTES
        or document.get("source_commit") != CANONICAL_SOURCE_COMMIT
        or document.get("identity_source") != LIVE_IDENTITY_SOURCE
    ):
        raise ValidationError
    resources = document.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ValidationError
    resources = cast(list[object], resources)
    entries: dict[str, StateEntry] = {}
    for raw_item in resources:
        if not isinstance(raw_item, dict):
            raise ValidationError
        item = cast(dict[str, Any], raw_item)
        address = item.get("address")
        resource_type = item.get("type")
        identifier = item.get("id")
        if (
            not isinstance(address, str)
            or not isinstance(resource_type, str)
            or not isinstance(identifier, str)
            or item.get("account_id") != PRODUCTION_ACCOUNT
            or address in entries
        ):
            raise ValidationError
        _validate_managed_address(address, identifier, resource_type)
        entries[address] = StateEntry(resource_type, identifier)
    return entries


def _compare_identity(state: StateSnapshot, identity: dict[str, StateEntry]) -> None:
    # State supplies the shape only; each exact address/type/ID pair must also
    # be present in the separately captured account-scoped live API manifest.
    if set(identity) != set(state.managed):
        raise ValidationError
    for address, entry in state.managed.items():
        if identity[address] != entry:
            raise ValidationError


def _digest(entries: dict[str, StateEntry]) -> str:
    value = "\n".join(
        f"{address}\0{entry.type}\0{entry.identifier}"
        for address, entry in sorted(entries.items())
    )
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def validate(
    state_path: Path, plan_path: Path, identity_path: Path
) -> dict[str, object]:
    state = _state_entries(_json(state_path))
    identity = _identity_entries(_json(identity_path))
    _compare_identity(state, identity)
    plan = _plan_entries(_json(plan_path), state)
    if not RETAINED.issubset(set(state.managed)):
        raise ValidationError
    if set(plan) - set(state.managed) or RETAINED.intersection(plan):
        raise ValidationError
    expected = {
        address: entry
        for address, entry in state.managed.items()
        if address not in RETAINED
    }
    if plan != expected:
        raise ValidationError
    return {
        "manifest": "legacy-retirement-plan-v2",
        "status": "pass",
        "state_instances": len(state.managed),
        "data_instances": len(state.data),
        "retained_instances": len(RETAINED),
        "delete_instances": len(plan),
        "state_sha256": _digest(state.managed),
        "delete_sha256": _digest(plan),
        "identity_sha256": _digest(identity),
    }


def validate_state_only(state_path: Path, identity_path: Path) -> dict[str, object]:
    state = _state_entries(_json(state_path))
    identity = _identity_entries(_json(identity_path))
    _compare_identity(state, identity)
    if not RETAINED.issubset(set(state.managed)):
        raise ValidationError
    return {
        "manifest": "legacy-retirement-identity-v1",
        "status": "pass",
        "state_instances": len(state.managed),
        "data_instances": len(state.data),
        "retained_instances": len(RETAINED),
        "identity_sha256": _digest(identity),
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValidationError


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(add_help=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--identity-manifest", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--state-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if bool(args.plan) == args.state_only:
            raise ValidationError
        if args.plan:
            manifest = validate(
                Path(args.state), Path(args.plan), Path(args.identity_manifest)
            )
        else:
            manifest = validate_state_only(
                Path(args.state), Path(args.identity_manifest)
            )
    except SystemExit:
        raise
    except ValidationError:
        print("legacy retirement plan rejected", file=sys.stderr)
        return 1
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

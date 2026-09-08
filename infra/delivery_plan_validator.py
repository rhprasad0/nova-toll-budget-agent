"""Fail-closed, stdlib-only validator for the development application plan.

The table below is deliberately finite.  Resource addresses are keys, never
patterns; resource patterns occur only in the IAM evidence for an address.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


EXPECTED_IDENTITY = MappingProxyType(
    {
        "provider": "hashicorp/aws",
        "provider_version": "6.60.0",
        "terraform_version": "1.15.8",
        "lockfile": "v2/infra/.terraform.lock.hcl",
        "lock_identity": "V2-AWS60",
    }
)
EXPECTED_PROVIDER_NAME = "registry.terraform.io/hashicorp/aws"


@dataclass(frozen=True)
class Permission:
    action: str
    resources: tuple[str, ...]
    conditions: Mapping[str, str]


@dataclass(frozen=True)
class Mutation:
    fields: tuple[str, ...]
    actions: tuple[str, ...]
    operation_class: str
    permissions: tuple[Permission, ...]
    create_identity: tuple[tuple[str, str], ...] = ()


def _permission(action: str, *resources: str, conditions: Mapping[str, str] | None = None) -> Permission:
    return Permission(action, resources, MappingProxyType(dict(conditions or {})))


def _mutation(
    fields: tuple[str, ...],
    actions: tuple[str, ...],
    operation_class: str,
    *permissions: Permission,
    create_identity: tuple[tuple[str, str], ...] = (),
) -> Mutation:
    return Mutation(fields, actions, operation_class, permissions, create_identity)


ACCOUNT = "903859731897"
REGION = "us-east-1"
ARTIFACT_BUCKET_NAME = "nova-toll-agentcore-903859731897"
SITE_BUCKET_NAME = "tollchat-site-903859731897-dev"
LAMBDA = tuple(
    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}"
    for name in ("toll-v2-pricing-loader-dev", "toll-v2-report-publisher-dev", "tollchat-v2-chat-proxy-dev")
)
LOG_GROUPS = tuple(
    f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{name}"
    for name in (
        "/aws/lambda/toll-v2-pricing-loader-dev",
        "/aws/lambda/toll-v2-report-publisher-dev",
        "/aws/lambda/tollchat-v2-chat-proxy-dev",
        "/aws/lambda/toll-v2-usage-publisher-dev",
        "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
        "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview",
    )
)
ALARM_NAMES = (
    "toll-v2-pricing-freshness-i66-dev",
    "toll-v2-pricing-freshness-i95-dev",
    "toll-v2-pricing-loader-delivery-failure-queue-dev",
    "toll-v2-pricing-loader-errors-dev",
    "toll-v2-pricing-loader-invoke-failure-queue-dev",
    "toll-v2-report-generation-freshness-dev",
    "toll-v2-report-publisher-delivery-failure-queue-dev",
    "toll-v2-report-publisher-errors-dev",
    "toll-v2-report-publisher-invoke-failure-queue-dev",
    "tollchat-v2-agentcore-active-sessions-dev",
    "tollchat-v2-chat-proxy-errors-dev",
    "tollchat-v2-chat-proxy-failures-dev",
    "tollchat-v2-chat-proxy-latency-dev",
)
ALARMS = tuple(f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{name}" for name in ALARM_NAMES)
SITE_OBJECT = f"arn:aws:s3:::{SITE_BUCKET_NAME}/*"
ARTIFACT_OBJECTS = (
    "arn:aws:s3:::nova-toll-agentcore-903859731897/runtime/v2/*",
    "arn:aws:s3:::nova-toll-agentcore-903859731897/lambda/v2/*",
)
SITE_BUCKET = f"arn:aws:s3:::{SITE_BUCKET_NAME}"


def _build_contract() -> dict[str, Mutation]:
    result: dict[str, Mutation] = {}
    for name, resource in zip(("loader", "publisher", "tollchat_proxy"), LAMBDA):
        result[f"aws_lambda_function.{name}"] = _mutation(
            ("filename", "source_code_hash", "s3_bucket", "s3_key", "s3_object_version"),
            ("update",),
            "lambda-code",
            _permission("lambda:UpdateFunctionCode", resource),
        )
    result["aws_lambda_alias.tollchat_live"] = _mutation(
        ("function_version",),
        ("update",),
        "lambda-alias",
        _permission("lambda:UpdateAlias", *LAMBDA, *(f"{arn}:*" for arn in LAMBDA)),
    )
    for name in ("agentcore", "tollchat_proxy"):
        result[f"aws_s3_object.{name}"] = _mutation(
            ("source", "source_hash"),
            ("create", "update"),
            "artifact-upload",
            _permission("s3:PutObject", *ARTIFACT_OBJECTS),
            create_identity=(
                ("bucket", ARTIFACT_BUCKET_NAME),
                ("key", f"runtime/v2/agentcore{'-dev' if name == 'agentcore' else ''}.zip"),
            ) if name == "agentcore" else (
                ("bucket", ARTIFACT_BUCKET_NAME),
                ("key", "lambda/v2/chat-proxy-dev.zip"),
            ),
        )
    site_keys = {
        "index": "index.html",
        "chat": "chat.mjs",
        "usage": "usage.json",
        "faq": "faq.html",
        "privacy": "privacy.txt",
        "terms": "terms.txt",
        "robots": "robots.txt",
    }
    for name, key in site_keys.items():
        result[f"aws_s3_object.{name}"] = _mutation(
            ("source", "source_hash", "content", "content_type", "cache_control"),
            ("create", "update"),
            "site-object-upload",
            _permission("s3:PutObject", SITE_OBJECT),
            create_identity=(("bucket", SITE_BUCKET_NAME), ("key", key)),
        )
    for key in (
        "LICENSE.txt",
        "chat-markdown.mjs",
        "commute-estimates.json",
        "commute-map.mjs",
        "commute-routes.mjs",
        "coverage-locations.json",
        "favicon.png",
        "maplibre-gl-6.0.0/LICENSE.txt",
        "maplibre-gl-6.0.0/maplibre-gl-shared.mjs",
        "maplibre-gl-6.0.0/maplibre-gl-worker.mjs",
        "maplibre-gl-6.0.0/maplibre-gl.css",
        "maplibre-gl-6.0.0/maplibre-gl.mjs",
        "markdown-it.esm.min.mjs",
        "tollchat-annual-commute-example.png",
        "tollchat-logo.png",
    ):
        result[f'aws_s3_object.site_assets["{key}"]'] = _mutation(
            ("source", "source_hash", "content_type", "cache_control"),
            ("create", "update"),
            "site-asset-upload",
            _permission("s3:PutObject", SITE_OBJECT),
            create_identity=(("bucket", SITE_BUCKET_NAME), ("key", f"assets/{key}")),
        )
    result["aws_s3_bucket_server_side_encryption_configuration.site"] = _mutation(
        ("rule.apply_server_side_encryption_by_default", "rule.bucket_key_enabled"),
        ("update",),
        "site-encryption",
        _permission("s3:PutEncryptionConfiguration", SITE_BUCKET),
    )
    result["aws_cloudwatch_event_target.loader"] = _mutation(
        ("target", "retry_policy", "dead_letter_config"),
        ("create", "update"),
        "event-targets",
        _permission("events:PutTargets", f"arn:aws:events:{REGION}:{ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev"),
    )
    log_names = ("loader", "publisher", "tollchat_proxy", "usage_publisher")
    for name, resource in zip(log_names, LOG_GROUPS[:4]):
        result[f"aws_cloudwatch_log_group.{name}"] = _mutation(
            ("retention_in_days",),
            ("update",),
            "log-retention",
            _permission("logs:PutRetentionPolicy", resource),
        )
    for key, resource in (("DEFAULT", LOG_GROUPS[4]), ("preview", LOG_GROUPS[5])):
        result[f'aws_cloudwatch_log_group.agentcore_runtime["{key}"]'] = _mutation(
            ("retention_in_days",),
            ("update",),
            "log-retention",
            _permission("logs:PutRetentionPolicy", resource),
        )
    alarm_addresses = {
        "aws_cloudwatch_metric_alarm.loader_errors": "toll-v2-pricing-loader-errors-dev",
        'aws_cloudwatch_metric_alarm.freshness["i95"]': "toll-v2-pricing-freshness-i95-dev",
        'aws_cloudwatch_metric_alarm.freshness["i66"]': "toll-v2-pricing-freshness-i66-dev",
        'aws_cloudwatch_metric_alarm.failure_queues["invoke"]': "toll-v2-pricing-loader-invoke-failure-queue-dev",
        'aws_cloudwatch_metric_alarm.failure_queues["delivery"]': "toll-v2-pricing-loader-delivery-failure-queue-dev",
        "aws_cloudwatch_metric_alarm.report_generation_freshness": "toll-v2-report-generation-freshness-dev",
        "aws_cloudwatch_metric_alarm.publisher_errors": "toll-v2-report-publisher-errors-dev",
        'aws_cloudwatch_metric_alarm.publisher_failure_queues["invoke"]': "toll-v2-report-publisher-invoke-failure-queue-dev",
        'aws_cloudwatch_metric_alarm.publisher_failure_queues["delivery"]': "toll-v2-report-publisher-delivery-failure-queue-dev",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_errors": "tollchat-v2-chat-proxy-errors-dev",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_failures": "tollchat-v2-chat-proxy-failures-dev",
        "aws_cloudwatch_metric_alarm.tollchat_proxy_latency": "tollchat-v2-chat-proxy-latency-dev",
        "aws_cloudwatch_metric_alarm.tollchat_sessions": "tollchat-v2-agentcore-active-sessions-dev",
    }
    for address, name in alarm_addresses.items():
        result[address] = _mutation(
            ("tags",),
            ("update",),
            "alarm-tags",
            _permission("cloudwatch:TagResource", f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{name}"),
            _permission("cloudwatch:UntagResource", f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{name}"),
        )
    result["aws_dynamodb_table.tollchat_sessions"] = _mutation(
        ("ttl.enabled",),
        ("update",),
        "sessions-ttl",
        _permission("dynamodb:UpdateTimeToLive", f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev"),
    )
    result["aws_scheduler_schedule.publisher"] = _mutation(
        ("schedule_expression", "schedule_expression_timezone", "flexible_time_window", "target"),
        ("update",),
        "schedule-update",
        _permission("scheduler:UpdateSchedule", f"arn:aws:scheduler:{REGION}:{ACCOUNT}:schedule/*/toll-v2-report-publisher-dev"),
    )
    result["aws_bedrock_guardrail_version.tollchat"] = _mutation(
        ("description", "guardrail_arn"),
        ("create",),
        "guardrail-version",
        _permission("bedrock:CreateGuardrailVersion", f"arn:aws:bedrock:{REGION}:{ACCOUNT}:guardrail/vdyqrh31xgca"),
    )
    result["aws_bedrockagentcore_agent_runtime.tollchat"] = _mutation(
        ("agent_runtime_artifact.code_configuration.code.s3.version_id",),
        ("update",),
        "agentcore-code",
        _permission("bedrock-agentcore:UpdateAgentRuntime", f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl"),
        _permission(
            "iam:PassRole",
            f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-agentcore-runtime-dev",
            conditions={"iam:PassedToService": "bedrock-agentcore.amazonaws.com"},
        ),
    )
    result["aws_bedrockagentcore_agent_runtime_endpoint.tollchat"] = _mutation(
        ("agent_runtime_version",),
        ("update",),
        "agentcore-endpoint",
        _permission("bedrock-agentcore:UpdateAgentRuntimeEndpoint", f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl/runtime-endpoint/preview"),
    )
    result["aws_api_gateway_deployment.tollchat"] = _mutation(
        ("triggers.redeployment",),
        ("create",),
        "api-deployment",
        _permission("apigateway:POST", f"arn:aws:apigateway:{REGION}::/restapis/ocw8sg0wlb/deployments", f"arn:aws:apigateway:{REGION}::/restapis/ocw8sg0wlb/deployments/*"),
    )
    for name in ("public_chat_routes", "public_report_routes"):
        result[f"aws_cloudfront_function.{name}"] = _mutation(
            ("code",),
            ("update", "publish"),
            "cloudfront-code",
            _permission("cloudfront:UpdateFunction", f"arn:aws:cloudfront::{ACCOUNT}:function/tollchat-v2-{name.replace('_', '-')}-dev"),
            _permission("cloudfront:PublishFunction", f"arn:aws:cloudfront::{ACCOUNT}:function/tollchat-v2-{name.replace('_', '-')}-dev"),
        )
    return result


CONTRACT = MappingProxyType(_build_contract())
SUPPORTED_ADDRESSES = frozenset(CONTRACT)

_PLAN_KEYS = frozenset({
    "format_version", "terraform_version", "resource_changes", "planned_values", "prior_state",
    "configuration", "output_changes", "variables", "timestamp", "checks", "errored",
})
_RESOURCE_KEYS = frozenset({
    "address", "mode", "type", "name", "index", "provider_name", "schema_version", "change",
    "deposed", "previous_address", "action_reason", "depends_on",
})
_CHANGE_KEYS = frozenset({
    "actions", "before", "after", "after_unknown", "before_sensitive", "after_sensitive",
    "replace_paths", "action_reason",
})
_MANIFEST_KEYS = frozenset({"schema_version", "provider_identity", "mutations", "permissions"})
_MUTATION_KEYS = frozenset({"address", "action", "operation_class", "changed_fields"})
_PERMISSION_KEYS = frozenset({"address", "action", "resource", "conditions"})
_ACTIONS = frozenset({"create", "update", "delete", "read", "no-op", "import", "refresh"})
_PRODUCTION_ACCOUNT = "920534282028"
_PRODUCTION_MARKERS = re.compile(r"(?:production|tollchat\.ai|www\.tollchat\.ai|(?:^|[-_/.])prod(?:$|[-_/.]))", re.I)
_AUTHORIZATION_FIELDS = frozenset({
    "runtime", "handler", "role", "environment", "memory_size", "timeout", "reserved_concurrent_executions",
    "vpc_config", "layers", "architectures", "tracing_config", "ephemeral_storage", "file_system_config",
    "function_url_config", "event_invoke_config", "invoke_config", "permissions", "publish", "kms_key_arn",
    "code_signing_config_arn", "package_type", "image_uri", "acl", "tags", "content_type", "cache_control",
    "force_destroy", "policy", "public_access_block", "lifecycle_rule", "versioning", "logging", "encryption",
    "role_arn", "target_arn", "schedule_expression", "guardrail_arn", "resource_policy", "domain_name",
})


class _Invalid(Exception):
    def __init__(self, reason: str, *, address: str | None = None, action: str | None = None, operation_class: str | None = None):
        self.reason = reason
        self.address = address
        self.action = action
        self.operation_class = operation_class


def _reject(reason: str, *, address: str | None = None, action: str | None = None, operation_class: str | None = None) -> None:
    raise _Invalid(reason, address=address, action=action, operation_class=operation_class)


def _is_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        if not value and prefix:
            return {prefix: {}}
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                _reject("malformed_input")
            result.update(_flatten(child, f"{prefix}.{key}" if prefix else key))
        return result
    return {prefix: value}


def _changed_fields(before: Any, after: Any, allowed: tuple[str, ...] = ()) -> tuple[str, ...]:
    left = _flatten(before) if before is not None else {}
    right = _flatten(after) if after is not None else {}
    changed = (key for key in set(left) | set(right) if left.get(key) != right.get(key))
    result: set[str] = set()
    for path in changed:
        parents = [field for field in allowed if path == field or path.startswith(field + ".")]
        result.add(max(parents, key=len) if parents else path)
    return tuple(sorted(result))


def _path_allowed(path: str, fields: tuple[str, ...]) -> bool:
    return any(path == field or path.startswith(field + ".") or path.startswith(field + "[") for field in fields)


def _create_fields(after: dict[str, Any], spec: Mutation, address: str, action: str) -> tuple[str, ...]:
    result: set[str] = set()
    for path, value in _flatten(after).items():
        parents = [field for field in spec.fields if path == field or path.startswith(field + ".")]
        if parents:
            result.add(max(parents, key=len))
        elif path.split(".", 1)[0] in _AUTHORIZATION_FIELDS and value not in (None, False, "", {}, []):
            _reject("unsupported_field_delta", address=address, action=action, operation_class=spec.operation_class)
    return tuple(sorted(result))


def _metadata_authorized(path: str, spec: Mutation) -> bool:
    return (
        _path_allowed(path, spec.fields)
        or any(path == field or path.startswith(field + ".") or path.startswith(field + "[") for field, _ in spec.create_identity)
        or path.split(".", 1)[0] in _AUTHORIZATION_FIELDS
    )


def _validate_s3_identity(before: dict[str, Any] | None, after: dict[str, Any], spec: Mutation, address: str, action: str) -> None:
    if action not in {"create", "update"} or not spec.create_identity:
        return
    values = (after,) if action == "create" else (before, after)
    if any(
        not isinstance(value, dict)
        or any(not isinstance(value.get(field), str) or value[field] != expected for field, expected in spec.create_identity)
        for value in values
    ):
        _reject("invalid_resource_identity", address=address, action=action, operation_class=spec.operation_class)


def _unknown_paths(value: Any, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, bool):
        return (prefix,) if value else ()
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            if not isinstance(key, str):
                _reject("malformed_input")
            paths.extend(_unknown_paths(child, f"{prefix}.{key}" if prefix else key))
        return tuple(paths)
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_unknown_paths(child, f"{prefix}[{index}]"))
        return tuple(paths)
    _reject("malformed_input")
    return ()


def _walk_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(item for key, child in value.items() for item in _walk_strings(key) + _walk_strings(child))
    if isinstance(value, list):
        return tuple(item for child in value for item in _walk_strings(child))
    return ()


def _has_production_value(value: Any) -> bool:
    return any(_PRODUCTION_ACCOUNT in item or _PRODUCTION_MARKERS.search(item) for item in _walk_strings(value))


def _validate_identity(identity: Any) -> None:
    if not isinstance(identity, dict):
        _reject("provider_identity_missing")
    if set(identity) != set(EXPECTED_IDENTITY) or any(not _is_string(value) for value in identity.values()):
        _reject("provider_identity_mismatch")
    if any(identity[key] != EXPECTED_IDENTITY[key] for key in EXPECTED_IDENTITY):
        _reject("provider_identity_mismatch")


def _address_identity(address: str) -> tuple[str, str, Any | None]:
    base, separator, index_text = address.partition("[")
    parts = base.split(".")
    if len(parts) == 2:
        resource_type, name = parts
    elif len(parts) == 3 and parts[0] == "data":
        resource_type, name = parts[1:]
    else:
        _reject("malformed_input", address=address)
    if not resource_type or not name:
        _reject("malformed_input", address=address)
    if not separator:
        return resource_type, name, None
    if not index_text.endswith("]") or not index_text[:-1]:
        _reject("malformed_input", address=address)
    try:
        index = json.loads("[" + index_text[:-1] + "]")[0]
    except (TypeError, ValueError, json.JSONDecodeError):
        _reject("malformed_input", address=address)
    return resource_type, name, index


def _resource_ok(value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def _validate_permission(record: Any, spec: Mutation, address: str) -> tuple[str, str, Mapping[str, str]]:
    if not isinstance(record, dict) or set(record) != _PERMISSION_KEYS:
        _reject("unknown_manifest_declaration", address=address)
    action, resource, conditions = record.get("action"), record.get("resource"), record.get("conditions")
    if not (_is_string(action) and _is_string(resource) and isinstance(conditions, dict)):
        _reject("malformed_input", address=address, action=action if isinstance(action, str) else None)
    if any(not isinstance(key, str) or not isinstance(value, str) or not key or not value for key, value in conditions.items()):
        _reject("malformed_input", address=address, action=action)
    return action, resource, dict(conditions)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mutation_result(plan_record: Mapping[str, Any], manifest_record: Mapping[str, Any], permissions: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "address": plan_record["address"],
        "action": plan_record["action"],
        "operation_class": plan_record["operation_class"],
        "changed_fields": list(plan_record["changed_fields"]),
        "before": plan_record.get("before"),
        "after": plan_record.get("after"),
        "manifest": dict(manifest_record),
        "permissions": permissions,
    }


def _parse_plan(plan: Any) -> list[dict[str, Any]]:
    if not isinstance(plan, dict) or not set(plan).issubset(_PLAN_KEYS) or not isinstance(plan.get("resource_changes"), list):
        _reject("malformed_input")
    if plan.get("terraform_version") != EXPECTED_IDENTITY["terraform_version"]:
        _reject("provider_identity_mismatch")
    for key in ("format_version", "terraform_version", "timestamp"):
        if key in plan and not isinstance(plan[key], str):
            _reject("malformed_input")
    if "errored" in plan and not isinstance(plan["errored"], bool):
        _reject("malformed_input")
    for key in ("planned_values", "prior_state", "configuration", "output_changes", "variables"):
        if key in plan and not isinstance(plan[key], dict):
            _reject("malformed_input")
    if "checks" in plan and not isinstance(plan["checks"], (dict, list)):
        _reject("malformed_input")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for resource in plan["resource_changes"]:
        if not isinstance(resource, dict) or not set(resource).issubset(_RESOURCE_KEYS):
            _reject("malformed_input")
        address = resource.get("address")
        mode = resource.get("mode")
        change = resource.get("change")
        if not _is_string(address) or not _is_string(mode) or not isinstance(change, dict):
            _reject("malformed_input")
        resource_type, resource_name, resource_index = _address_identity(address)
        if resource.get("type") != resource_type or resource.get("name") != resource_name:
            _reject("malformed_input", address=address)
        if resource.get("provider_name") != EXPECTED_PROVIDER_NAME:
            _reject("provider_identity_mismatch", address=address)
        if resource_index is None:
            if "index" in resource:
                _reject("malformed_input", address=address)
        elif resource.get("index") != resource_index:
            _reject("malformed_input", address=address)
        for key in ("type", "name", "provider_name", "action_reason"):
            if key in resource and not isinstance(resource[key], str):
                _reject("malformed_input", address=address)
        if "index" in resource and not isinstance(resource["index"], (str, int)):
            _reject("malformed_input", address=address)
        if "schema_version" in resource and not isinstance(resource["schema_version"], int):
            _reject("malformed_input", address=address)
        if "depends_on" in resource and (
            not isinstance(resource["depends_on"], list)
            or any(not _is_string(item) for item in resource["depends_on"])
        ):
            _reject("malformed_input", address=address)
        if address in seen:
            _reject("duplicate_address", address=address)
        seen.add(address)
        if "previous_address" in resource:
            _reject("moved_resource", address=address)
        if "deposed" in resource:
            _reject("deposed_resource", address=address)
        if not set(change).issubset(_CHANGE_KEYS) or not isinstance(change.get("actions"), list):
            _reject("malformed_input", address=address)
        for key in ("action_reason",):
            if key in change and not isinstance(change[key], str):
                _reject("malformed_input", address=address)
        actions = change["actions"]
        if not actions or any(not _is_string(action) or action not in _ACTIONS for action in actions):
            _reject("unsupported_action", address=address)
        if "import" in actions or "refresh" in actions:
            _reject("import_or_refresh", address=address, action=actions[0])
        if len(actions) != 1:
            _reject("replacement", address=address, action="+".join(actions))
        action = actions[0]
        if not isinstance(change.get("before"), (dict, type(None))) or not isinstance(change.get("after"), (dict, type(None))):
            _reject("malformed_input", address=address, action=action)
        if "replace_paths" in change:
            if not isinstance(change["replace_paths"], list):
                _reject("malformed_input", address=address, action=action)
            if change["replace_paths"]:
                _reject("replacement", address=address, action=action)
        metadata_paths: dict[str, tuple[str, ...]] = {}
        for key in ("after_unknown", "before_sensitive", "after_sensitive"):
            if action in {"create", "update"} and key not in change:
                _reject("malformed_input", address=address, action=action)
            if key in change:
                if not isinstance(change[key], dict):
                    _reject("malformed_input", address=address, action=action)
                try:
                    metadata_paths[key] = _unknown_paths(change[key])
                except _Invalid:
                    _reject("malformed_input", address=address, action=action)
        if action == "delete":
            _reject("delete_not_permitted", address=address, action=action)
        if _has_production_value(resource):
            _reject("production_target", address=address, action=action)
        if mode == "data":
            if not address.startswith("data.") or action not in {"read", "no-op"}:
                _reject("data_mode_misuse", address=address, action=action)
            continue
        if mode != "managed":
            _reject("data_mode_misuse", address=address, action=action)
        if action == "read":
            _reject("data_mode_misuse", address=address, action=action)
        if action == "no-op":
            if _changed_fields(change.get("before"), change.get("after")):
                _reject("unsupported_field_delta", address=address, action=action)
            continue
        spec = CONTRACT.get(address)
        if spec is None:
            _reject("unsupported_address", address=address, action=action)
        before, after = change.get("before"), change.get("after")
        if action == "update" and (before is None or after is None):
            _reject("malformed_input", address=address, action=action)
        if action == "create" and (before is not None or after is None):
            _reject("malformed_input", address=address, action=action)
        changed = _create_fields(after, spec, address, action) if action == "create" else _changed_fields(before, after, spec.fields)
        if action not in spec.actions:
            _reject("unsupported_action", address=address, action=action, operation_class=spec.operation_class)
        if not changed or any(not _path_allowed(field, spec.fields) for field in changed):
            _reject("unsupported_field_delta", address=address, action=action, operation_class=spec.operation_class)
        if spec.operation_class == "lambda-code":
            changed_set = set(changed)
            if changed_set != {"filename", "source_code_hash"} and not (
                "source_code_hash" in changed_set
                and bool(changed_set & {"s3_bucket", "s3_key", "s3_object_version"})
            ):
                _reject("unsupported_field_delta", address=address, action=action, operation_class=spec.operation_class)
        if any(_metadata_authorized(path, spec) for path in metadata_paths.get("after_unknown", ())):
            _reject("unknown_authorization_value", address=address, action=action, operation_class=spec.operation_class)
        if any(
            _metadata_authorized(path, spec)
            for key in ("before_sensitive", "after_sensitive")
            for path in metadata_paths.get(key, ())
        ):
            _reject("sensitive_authorization_value", address=address, action=action, operation_class=spec.operation_class)
        _validate_s3_identity(before, after, spec, address, action)
        records.append({
            "address": address,
            "action": action,
            "operation_class": spec.operation_class,
            "changed_fields": changed,
            "before": before,
            "after": after,
            "spec": spec,
        })
    return records


def _parse_manifest(manifest: Any) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    if not isinstance(manifest, dict) or not set(manifest).issubset(_MANIFEST_KEYS):
        _reject("unknown_manifest_declaration")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("mutations"), list) or not isinstance(manifest.get("permissions"), list):
        _reject("malformed_input")
    _validate_identity(manifest.get("provider_identity"))
    mutations: dict[str, dict[str, Any]] = {}
    permissions: dict[str, list[dict[str, Any]]] = {}
    for record in manifest["mutations"]:
        if not isinstance(record, dict) or set(record) != _MUTATION_KEYS:
            _reject("unknown_manifest_declaration")
        address = record.get("address")
        if not (_is_string(address) and _is_string(record.get("action")) and _is_string(record.get("operation_class")) and isinstance(record.get("changed_fields"), list)):
            _reject("malformed_input")
        if address in mutations:
            _reject("duplicate_manifest_mutation", address=address)
        if any(not _is_string(field) for field in record["changed_fields"]):
            _reject("malformed_input", address=address)
        mutations[address] = record
    for record in manifest["permissions"]:
        address = record.get("address") if isinstance(record, dict) else None
        if not _is_string(address):
            _reject("malformed_input")
        _validate_permission(record, CONTRACT.get(address, Mutation((), (), "", ())), address)
        permissions.setdefault(address, []).append(record)
    return mutations, permissions


def _validate_manifest_entry(address: str, declaration: Mapping[str, Any], permissions: list[dict[str, Any]]) -> None:
    spec = CONTRACT.get(address)
    if spec is None:
        _reject("unsupported_address", address=address)
    action = declaration["action"]
    if action not in spec.actions or declaration["operation_class"] != spec.operation_class:
        _reject("manifest_mutation_mismatch", address=address, action=action, operation_class=declaration["operation_class"])
    fields = declaration["changed_fields"]
    if not fields or len(set(fields)) != len(fields) or any(field not in spec.fields for field in fields):
        _reject("unsupported_field_delta", address=address, action=action, operation_class=spec.operation_class)
    if spec.operation_class == "lambda-code" and set(fields) not in (
        {"filename", "source_code_hash"},
        {"s3_bucket", "s3_key", "s3_object_version", "source_code_hash"},
    ):
        s3_fields = {"s3_bucket", "s3_key", "s3_object_version"}
        if "source_code_hash" not in fields or not (set(fields) & s3_fields):
            _reject("unsupported_field_delta", address=address, action=action, operation_class=spec.operation_class)
    expected = spec.permissions
    if len(permissions) != len(expected):
        _reject("missing_permission", address=address, action=action, operation_class=spec.operation_class)
    used: set[int] = set()
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
    for permission in permissions:
        permission_action, resource, conditions = _validate_permission(permission, spec, address)
        permission_key = (permission_action, resource, tuple(sorted(conditions.items())))
        if permission_key in seen:
            _reject("duplicate_permission", address=address, action=action, operation_class=spec.operation_class)
        seen.add(permission_key)
        match = next(
            (
                index for index, item in enumerate(expected)
                if index not in used
                and permission_action == item.action
                and _resource_ok(resource, item.resources)
                and conditions == dict(item.conditions)
            ),
            None,
        )
        if match is None:
            _reject("invalid_permission", address=address, action=action, operation_class=spec.operation_class)
        used.add(match)
    if len(used) != len(expected):
        _reject("missing_permission", address=address, action=action, operation_class=spec.operation_class)


def validate_plan(plan: Any, manifest: Any, identity: Any | None = None) -> dict[str, Any]:
    """Validate a plan and release manifest, returning only sanitized data."""
    try:
        if _has_production_value(plan) or _has_production_value(manifest) or (identity is not None and _has_production_value(identity)):
            _reject("production_target")
        _validate_identity(identity)
        records = _parse_plan(plan)
        declared, declared_permissions = _parse_manifest(manifest)
        if manifest.get("provider_identity") != identity:
            _reject("provider_identity_mismatch")
        actual_addresses = {record["address"] for record in records}
        if not set(declared_permissions).issubset(set(declared)):
            _reject("manifest_coverage_mismatch")
        if not actual_addresses.issubset(set(declared)):
            _reject("manifest_coverage_mismatch")
        for address, declaration in declared.items():
            _validate_manifest_entry(address, declaration, declared_permissions.get(address, []))
        sanitized_records: list[dict[str, Any]] = []
        for record in records:
            address = record["address"]
            declaration = declared[address]
            if (
                declaration["action"] != record["action"]
                or declaration["operation_class"] != record["operation_class"]
                or tuple(sorted(declaration["changed_fields"])) != record["changed_fields"]
            ):
                _reject("manifest_mutation_mismatch", address=address, action=record["action"], operation_class=record["operation_class"])
            actual_permissions = declared_permissions.get(address, [])
            normalized: list[dict[str, Any]] = []
            for permission in actual_permissions:
                action, resource, conditions = _validate_permission(permission, record["spec"], address)
                normalized.append({"address": address, "action": action, "resource": resource, "conditions": conditions})
            sanitized_records.append(_mutation_result(record, declaration, normalized))
        fingerprint = _fingerprint({
            "identity": dict(EXPECTED_IDENTITY),
            "mutations": sanitized_records,
        })
        return {
            "status": "accepted",
            "reason_code": "ok",
            "addresses": [record["address"] for record in records],
            "actions": [record["action"] for record in records],
            "operation_classes": [record["operation_class"] for record in records],
            "fingerprint": fingerprint,
        }
    except _Invalid as error:
        result: dict[str, Any] = {"status": "rejected", "reason_code": error.reason}
        if error.address is not None:
            result["address"] = error.address
        if error.action is not None:
            result["action"] = error.action
        if error.operation_class is not None:
            result["operation_class"] = error.operation_class
        return result
    except Exception:
        return {"status": "rejected", "reason_code": "malformed_input"}


def validate(plan: Any, manifest: Any, identity: Any | None = None) -> dict[str, Any]:
    return validate_plan(plan, manifest, identity)


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("plan")
    parser.add_argument("manifest")
    parser.add_argument("--identity", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_plan(_load_json(args.plan), _load_json(args.manifest), _load_json(args.identity))
    except Exception:
        result = {"status": "rejected", "reason_code": "malformed_input"}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())

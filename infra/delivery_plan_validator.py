"""Fail-closed, stdlib-only validator for the development application plan.

The table below is deliberately finite.  Resource addresses are keys, never
patterns; resource patterns occur only in the IAM evidence for an address.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, TypeGuard, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "v2"))
from scripts import cost_dashboard_release as cost_release
from scripts import shared_packages

type JSON = bool | int | float | str | list[JSON] | dict[str, JSON] | None


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

LEGACY_PACKAGES = ("agentcore.zip", "chat-proxy.zip", "loader.zip", "publisher.zip")
TIMED_PACKAGES = (*LEGACY_PACKAGES, "timed-checks.zip")
PACKAGES = LEGACY_PACKAGES
TIMED_CHECKS_MARKER = "v2/scripts/build_timed_checks_zip.sh"
PRODUCTION_CONTROL_MARKER = "v2/scripts/run_production_migrations.py"
PRODUCTION_CONTROL_INPUTS = frozenset(
    {
        ".github/workflows/v2-production-migrations.yml",
        "v2/scripts/adopt_production_baseline.py",
        "v2/scripts/check_production_release.py",
        PRODUCTION_CONTROL_MARKER,
        "v2/scripts/run_production_migrations_workflow.sh",
    }
)


def packages_for_inputs(inputs: Mapping[str, Any]) -> tuple[str, ...]:
    return TIMED_PACKAGES if TIMED_CHECKS_MARKER in inputs else LEGACY_PACKAGES


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
    create_identity: tuple[tuple[str, Any], ...] = ()
    provider_change_identity: tuple[tuple[str, str], ...] = ()


def _permission(
    action: str, *resources: str, conditions: Mapping[str, str] | None = None
) -> Permission:
    return Permission(action, resources, MappingProxyType(dict(conditions or {})))


def _mutation(
    fields: tuple[str, ...],
    actions: tuple[str, ...],
    operation_class: str,
    *permissions: Permission,
    create_identity: tuple[tuple[str, Any], ...] = (),
    provider_change_identity: tuple[tuple[str, str], ...] = (),
) -> Mutation:
    return Mutation(
        fields,
        actions,
        operation_class,
        permissions,
        create_identity,
        provider_change_identity,
    )


ACCOUNT = "903859731897"
REGION = "us-east-1"
ARTIFACT_BUCKET_NAME = "nova-toll-agentcore-903859731897"
SITE_BUCKET_NAME = "tollchat-site-903859731897-dev"
LAMBDA = tuple(
    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}"
    for name in (
        "toll-v2-pricing-loader-dev",
        "toll-v2-report-publisher-dev",
        "tollchat-v2-chat-proxy-dev",
        "nova-toll-v2-timed-checks-dev",
    )
)
LAMBDA_FUNCTION_NAMES = MappingProxyType(
    {
        "loader": "toll-v2-pricing-loader-dev",
        "publisher": "toll-v2-report-publisher-dev",
        "tollchat_proxy": "tollchat-v2-chat-proxy-dev",
        "timed_checks": "nova-toll-v2-timed-checks-dev",
    }
)
TIMED_SCHEDULE_KEYS = (
    "greenway-eb-fri-0723",
    "greenway-eb-mon-0723",
    "greenway-eb-thu-0723",
    "greenway-eb-tue-0723",
    "greenway-eb-wed-0723",
    "greenway-wb-fri-1723",
    "greenway-wb-mon-1723",
    "greenway-wb-thu-1723",
    "greenway-wb-tue-1723",
    "greenway-wb-wed-1723",
    "i95-northbound-fri-0617",
    "i95-northbound-mon-0617",
    "i95-northbound-sat-1817",
    "i95-northbound-thu-0617",
    "i95-northbound-tue-0617",
    "i95-northbound-wed-0617",
    "i95-reversal-fri-0147",
    "i95-reversal-mon-1117",
    "i95-reversal-sat-1517",
    "i95-reversal-thu-0147",
    "i95-reversal-tue-0147",
    "i95-reversal-wed-0147",
    "i95-southbound-fri-1417",
    "i95-southbound-mon-1417",
    "i95-southbound-sat-1017",
    "i95-southbound-thu-1417",
    "i95-southbound-tue-1417",
    "i95-southbound-wed-1417",
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
ALARMS = tuple(
    f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{name}" for name in ALARM_NAMES
)
SITE_OBJECT = f"arn:aws:s3:::{SITE_BUCKET_NAME}/*"
ARTIFACT_OBJECTS = (
    "arn:aws:s3:::nova-toll-agentcore-903859731897/runtime/v2/*",
    "arn:aws:s3:::nova-toll-agentcore-903859731897/lambda/v2/*",
)
SITE_BUCKET = f"arn:aws:s3:::{SITE_BUCKET_NAME}"
PUBLISHER_ROLE_NAME = "toll-v2-report-publisher-dev"
PUBLISHER_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{PUBLISHER_ROLE_NAME}"
REPORT_FRESHNESS_ALARM_NAME = "toll-v2-report-generation-freshness-dev"
REPORT_FRESHNESS_ALARM_ARN = (
    f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{REPORT_FRESHNESS_ALARM_NAME}"
)
PUBLISHER_SITE_KEY_ARN = (
    "arn:aws:kms:us-east-1:903859731897:key/3bc78b60-9cbe-4abd-9744-8772c78d8379"
)
TRACE_LOG_GROUPS = LOG_GROUPS[4:]
TRACE_FIREHOSE = f"arn:aws:firehose:{REGION}:{ACCOUNT}:deliverystream/nova-toll-v2-agentcore-traces-dev"
TRACE_LOGS_ROLE = f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-agentcore-traces-logs-dev"
TRACE_FIREHOSE_ROLE = (
    f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-agentcore-traces-firehose-dev"
)
TRACE_RUNTIME_ROLE_NAME = "nova-toll-v2-agentcore-runtime-dev"
TRACE_RUNTIME_ROLE = f"arn:aws:iam::{ACCOUNT}:role/{TRACE_RUNTIME_ROLE_NAME}"
TRACE_MEASUREMENT_BUCKET = (
    "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-903859731897-dev"
)
TRACE_GLUE = (
    f"arn:aws:glue:{REGION}:{ACCOUNT}:catalog",
    f"arn:aws:glue:{REGION}:{ACCOUNT}:database/tollchat_agent_reports_development",
    f"arn:aws:glue:{REGION}:{ACCOUNT}:table/tollchat_agent_reports_development/agentcore_traces",
)
TRACE_WORKGROUP = (
    f"arn:aws:athena:{REGION}:{ACCOUNT}:workgroup/tollchat-agent-reports-dev"
)
TRACE_PREFIX = "agentcore-traces/"
TRACE_KMS_KEY = (
    f"arn:aws:kms:{REGION}:{ACCOUNT}:key/076e8341-894b-405c-96e9-2b037f96e2a6"
)
TRACE_FILTER = '{ $.traceId = "*" && $.spanId = "*" && $.durationNano >= 0 }'
TRACE_QUERY = "SELECT json_extract_scalar(raw_json, '$.traceId') AS traceId, json_extract_scalar(raw_json, '$.spanId') AS spanId, json_extract_scalar(raw_json, '$.name') AS name, cast(json_extract_scalar(raw_json, '$.durationNano') AS bigint) AS durationNano, json_extract_scalar(raw_json, '$.status.code') AS status_code, json_extract(raw_json, '$.attributes') AS attributes FROM agentcore_traces LIMIT 100"
TRACE_TAGS = {
    "environment": "development",
    "project": "nova-toll-budget-agent",
    "version": "v2",
}
TRACE_NOTICE_DIGESTS = {
    "aws_s3_object.index": "126f555a71d0afef5978bf415a3f6c90d8b2fb280618fdc2bc9ab44a0fefae4d",
    "aws_s3_object.faq": "3c2e1281969095cbf1282bf8abbb268713dfdd96110db28bc5bbf3ea1823c105",
    "aws_s3_object.privacy": "3363dc45ae0e3bc97b8ec4d90c4fb3290050e45b5f4bf1989edd95bd52b7318d",
}
REDACTED_TRACE_NOTICE_DIGESTS = {
    "aws_s3_object.index": "c4d4867169f6040c265f349697a6c9fa7c70506d66e41d93fea2ef5ae8d8b2e1",
    "aws_s3_object.faq": "ad2bfde99a68f8ed16fb1f8d67a9a7a4fbff031396639a1e84700230a590547a",
    "aws_s3_object.privacy": "00b192c03648aaec4913aafc8e3ad30bff05d73497de7466a78fbcef1969e0f5",
}
# Reviewed dashboard links preserve the existing redacted telemetry notices.
DASHBOARD_NOTICE_DIGESTS = {
    "aws_s3_object.faq": "09d9433615f842f51714135b3f2d5bd52cf764a4a6bb3bc45d4275871c5e37c7",
    "aws_s3_object.index": "ba691bafe85efe376cdcf65780805e939c9492587839deca0f60ced5580f1ea9",
}
REDACTED_NOTICE_VERSIONS = {
    address: {digest, DASHBOARD_NOTICE_DIGESTS.get(address, digest)}
    for address, digest in REDACTED_TRACE_NOTICE_DIGESTS.items()
}
REDACTED_NOTICE_VERSIONS["aws_s3_object.index"].add(
    "5b708ba38dd2a4fd4a4f43355fbfeb1d4dd09708a6af0fca5cd5ef910837a2ba"
)

TRACE_READ_ONLY_FIELDS = {
    "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]": (
        "arn",
        "destination_id",
        "extended_s3_configuration[0].cloudwatch_logging_options",
        "id",
        "version_id",
    ),
    'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]': (
        "apply_on_transformed_logs",
        "distribution",
        "emit_system_fields",
        "id",
        "region",
    ),
    'aws_cloudwatch_log_subscription_filter.agentcore_traces["preview"]': (
        "apply_on_transformed_logs",
        "distribution",
        "emit_system_fields",
        "id",
        "region",
    ),
    "aws_s3_bucket_lifecycle_configuration.agent_measurement": ("id",),
    "aws_glue_catalog_table.agentcore_traces[0]": (
        "arn",
        "description",
        "id",
        "open_table_format_input",
        "owner",
        "partition_keys",
        "region",
        "retention",
        "storage_descriptor[0].additional_locations",
        "storage_descriptor[0].bucket_columns",
        "storage_descriptor[0].columns[0].comment",
        "storage_descriptor[0].columns[0].parameters",
        "storage_descriptor[0].compressed",
        "storage_descriptor[0].number_of_buckets",
        "storage_descriptor[0].parameters",
        "storage_descriptor[0].schema_reference",
        "storage_descriptor[0].ser_de_info[0].name",
        "storage_descriptor[0].skewed_info",
        "storage_descriptor[0].sort_columns",
        "storage_descriptor[0].stored_as_sub_directories",
        "target_table",
        "view_definition",
        "view_expanded_text",
        "view_original_text",
    ),
    "aws_athena_named_query.agentcore_trace_summary[0]": ("id", "region"),
    "aws_bedrockagentcore_agent_runtime.tollchat": ("arn", "id"),
}


def _trace_reject(address: str, action: str, operation_class: str) -> NoReturn:
    # This is intentionally an existing workflow allowlisted reason.  The
    # delivery workflow records the validator once and propagates this summary.
    _reject(
        "unsupported_field_delta",
        address=address,
        action=action,
        operation_class=operation_class,
    )


def _trace_lifecycle(*, enabled: bool) -> list[dict[str, Any]]:
    rules = [
        {
            "id": "expire-raw-waf-logs",
            "status": "Enabled",
            "filter": [{"prefix": "AWSLogs/"}],
            "expiration": [{"days": 7}],
        },
        {
            "id": "expire-athena-results",
            "status": "Enabled",
            "filter": [{"prefix": "athena-results/"}],
            "expiration": [{"days": 7}],
            "abort_incomplete_multipart_upload": [{"days_after_initiation": 1}],
        },
    ]
    if enabled:
        rules.append(
            {
                "id": "expire-agentcore-traces",
                "status": "Enabled",
                "filter": [{"prefix": TRACE_PREFIX}],
                "expiration": [{"days": 7}],
                "abort_incomplete_multipart_upload": [{"days_after_initiation": 1}],
            }
        )
    return rules


def _trace_firehose_value() -> dict[str, Any]:
    return {
        "destination": "extended_s3",
        "elasticsearch_configuration": [],
        "extended_s3_configuration": [
            {
                "bucket_arn": TRACE_MEASUREMENT_BUCKET,
                "buffering_interval": 60,
                "buffering_size": 5,
                "compression_format": "UNCOMPRESSED",
                "custom_time_zone": "UTC",
                "data_format_conversion_configuration": [],
                "dynamic_partitioning_configuration": [],
                "error_output_prefix": None,
                "file_extension": None,
                "kms_key_arn": TRACE_KMS_KEY,
                "prefix": TRACE_PREFIX,
                "processing_configuration": [
                    {
                        "enabled": True,
                        "processors": [
                            {"parameters": [], "type": "Decompression"},
                            {
                                "parameters": [
                                    {
                                        "parameter_name": "DataMessageExtraction",
                                        "parameter_value": "true",
                                    }
                                ],
                                "type": "CloudWatchLogProcessing",
                            },
                            {"parameters": [], "type": "AppendDelimiterToRecord"},
                        ],
                    }
                ],
                "role_arn": TRACE_FIREHOSE_ROLE,
                "s3_backup_configuration": [],
                "s3_backup_mode": "Disabled",
            }
        ],
        "http_endpoint_configuration": [],
        "iceberg_configuration": [],
        "kinesis_source_configuration": [],
        "msk_source_configuration": [],
        "name": "nova-toll-v2-agentcore-traces-dev",
        "opensearch_configuration": [],
        "opensearchserverless_configuration": [],
        "redshift_configuration": [],
        "region": REGION,
        "server_side_encryption": [],
        "snowflake_configuration": [],
        "splunk_configuration": [],
        "tags": None,
        "tags_all": TRACE_TAGS,
        "timeouts": None,
    }


def _build_contract() -> dict[str, Mutation]:
    result: dict[str, Mutation] = {}
    for name, resource in zip(
        ("loader", "publisher", "tollchat_proxy", "timed_checks"), LAMBDA, strict=False
    ):
        if name == "tollchat_proxy":
            delivery_identity = (
                ("function_name", LAMBDA_FUNCTION_NAMES[name]),
                ("filename", None),
                ("s3_bucket", ARTIFACT_BUCKET_NAME),
                ("s3_key", "lambda/v2/chat-proxy-dev.zip"),
            )
        elif name == "timed_checks":
            delivery_identity = (
                ("function_name", LAMBDA_FUNCTION_NAMES[name]),
                ("filename", None),
                ("s3_bucket", ARTIFACT_BUCKET_NAME),
                ("s3_key", "lambda/v2/timed-checks-dev.zip"),
            )
        else:
            delivery_identity = (
                ("function_name", LAMBDA_FUNCTION_NAMES[name]),
                ("s3_bucket", None),
                ("s3_key", None),
                ("s3_object_version", None),
            )
        result[f"aws_lambda_function.{name}"] = _mutation(
            (
                "filename",
                "source_code_hash",
                "s3_bucket",
                "s3_key",
                "s3_object_version",
            ),
            ("update",),
            "lambda-code",
            _permission("lambda:UpdateFunctionCode", resource),
            create_identity=delivery_identity,
        )
    result["aws_lambda_alias.tollchat_live"] = _mutation(
        ("function_version",),
        ("update",),
        "lambda-alias",
        _permission("lambda:UpdateAlias", *LAMBDA, *(f"{arn}:*" for arn in LAMBDA)),
    )
    for name in ("agentcore", "tollchat_proxy", "timed_checks"):
        key = {
            "agentcore": "runtime/v2/agentcore-dev.zip",
            "tollchat_proxy": "lambda/v2/chat-proxy-dev.zip",
            "timed_checks": "lambda/v2/timed-checks-dev.zip",
        }[name]
        result[f"aws_s3_object.{name}"] = _mutation(
            ("source", "source_hash"),
            ("create", "update"),
            "artifact-upload",
            _permission(
                "s3:PutObject",
                f"arn:aws:s3:::{ARTIFACT_BUCKET_NAME}/{key}"
                if name == "timed_checks"
                else ARTIFACT_OBJECTS[0 if name == "agentcore" else 1],
            ),
            create_identity=(("bucket", ARTIFACT_BUCKET_NAME), ("key", key)),
        )
    site_keys = {
        "index": "index.html",
        "chat": "chat.mjs",
        "usage": "usage.json",
        "evals": "evals.html",
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
        "evals.css",
        "evals.mjs",
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
        _permission(
            "events:PutTargets",
            f"arn:aws:events:{REGION}:{ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev",
        ),
    )
    log_names = ("loader", "publisher", "tollchat_proxy", "usage_publisher")
    for name, resource in zip(log_names, LOG_GROUPS[:4], strict=False):
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
            _permission(
                "cloudwatch:TagResource",
                f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{name}",
            ),
            _permission(
                "cloudwatch:UntagResource",
                f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{name}",
            ),
        )
    result["aws_iam_role_policy.publisher"] = _mutation(
        ("policy",),
        ("update",),
        "publisher-inline-policy",
        _permission("iam:PutRolePolicy", PUBLISHER_ROLE_ARN),
        create_identity=(("name", PUBLISHER_ROLE_NAME), ("role", PUBLISHER_ROLE_NAME)),
        provider_change_identity=(
            ("account_id", ACCOUNT),
            ("name", PUBLISHER_ROLE_NAME),
            ("role", PUBLISHER_ROLE_NAME),
        ),
    )
    result["aws_iam_role_policy.tollchat_runtime"] = _mutation(
        ("policy",),
        ("update",),
        "agentcore-trace-runtime-policy",
        _permission("iam:PutRolePolicy", TRACE_RUNTIME_ROLE),
        create_identity=(
            ("name", TRACE_RUNTIME_ROLE_NAME),
            ("role", TRACE_RUNTIME_ROLE_NAME),
        ),
        provider_change_identity=(
            ("account_id", ACCOUNT),
            ("name", TRACE_RUNTIME_ROLE_NAME),
            ("role", TRACE_RUNTIME_ROLE_NAME),
        ),
    )
    result["aws_cloudwatch_metric_alarm.report_generation_freshness"] = _mutation(
        ("alarm_description", "dimensions"),
        ("update",),
        "report-freshness-alarm",
        _permission("cloudwatch:PutMetricAlarm", REPORT_FRESHNESS_ALARM_ARN),
        create_identity=(("alarm_name", REPORT_FRESHNESS_ALARM_NAME),),
        provider_change_identity=(
            ("account_id", ACCOUNT),
            ("alarm_name", REPORT_FRESHNESS_ALARM_NAME),
            ("region", REGION),
        ),
    )
    result["aws_dynamodb_table.tollchat_sessions"] = _mutation(
        ("ttl.enabled",),
        ("update",),
        "sessions-ttl",
        _permission(
            "dynamodb:UpdateTimeToLive",
            f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev",
        ),
    )
    result["aws_scheduler_schedule.publisher"] = _mutation(
        (
            "schedule_expression",
            "schedule_expression_timezone",
            "flexible_time_window",
            "target",
        ),
        ("update",),
        "schedule-update",
        _permission(
            "scheduler:UpdateSchedule",
            f"arn:aws:scheduler:{REGION}:{ACCOUNT}:schedule/*/toll-v2-report-publisher-dev",
        ),
    )
    for key in TIMED_SCHEDULE_KEYS:
        result[f'aws_scheduler_schedule.timed_checks["{key}"]'] = _mutation(
            (
                "schedule_expression",
                "schedule_expression_timezone",
                "flexible_time_window",
                "target",
            ),
            ("update",),
            "schedule-update",
            _permission(
                "scheduler:UpdateSchedule",
                f"arn:aws:scheduler:{REGION}:{ACCOUNT}:schedule/default/nova-toll-v2-{key}-dev",
            ),
            _permission(
                "iam:PassRole",
                f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-timed-checks-scheduler-dev",
                conditions={"iam:PassedToService": "scheduler.amazonaws.com"},
            ),
        )
    result["aws_bedrock_guardrail_version.tollchat"] = _mutation(
        ("description", "guardrail_arn"),
        ("create",),
        "guardrail-version",
        _permission(
            "bedrock:CreateGuardrailVersion",
            f"arn:aws:bedrock:{REGION}:{ACCOUNT}:guardrail/vdyqrh31xgca",
        ),
    )
    result["aws_bedrockagentcore_agent_runtime.tollchat"] = _mutation(
        (
            "agent_runtime_artifact.code_configuration.code.s3.version_id",
            "environment_variables",
        ),
        ("update",),
        "agentcore-code",
        _permission(
            "bedrock-agentcore:UpdateAgentRuntime",
            f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl",
        ),
        _permission(
            "iam:PassRole",
            f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-agentcore-runtime-dev",
            conditions={"iam:PassedToService": "bedrock-agentcore.amazonaws.com"},
        ),
        provider_change_identity=(("agent_runtime_name", "nova_toll_v2_development"),),
    )
    result["aws_bedrockagentcore_agent_runtime_endpoint.tollchat"] = _mutation(
        ("agent_runtime_version",),
        ("update",),
        "agentcore-endpoint",
        _permission(
            "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
            f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl/runtime-endpoint/preview",
        ),
    )
    result["aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"] = _mutation(
        tuple(_trace_firehose_value()),
        ("create", "delete", "update"),
        "agentcore-trace-firehose",
        _permission("firehose:CreateDeliveryStream", TRACE_FIREHOSE),
        _permission("firehose:DeleteDeliveryStream", TRACE_FIREHOSE),
        _permission("firehose:TagDeliveryStream", TRACE_FIREHOSE),
        _permission("firehose:UpdateDestination", TRACE_FIREHOSE),
        _permission(
            "iam:PassRole",
            TRACE_FIREHOSE_ROLE,
            conditions={"iam:PassedToService": "firehose.amazonaws.com"},
        ),
        create_identity=(
            ("name", "nova-toll-v2-agentcore-traces-dev"),
            ("destination", "extended_s3"),
        ),
        provider_change_identity=(("arn", TRACE_FIREHOSE),),
    )
    for key, group in zip(("DEFAULT", "preview"), TRACE_LOG_GROUPS, strict=False):
        result[f'aws_cloudwatch_log_subscription_filter.agentcore_traces["{key}"]'] = (
            _mutation(
                (
                    "destination_arn",
                    "filter_pattern",
                    "log_group_name",
                    "name",
                    "role_arn",
                ),
                ("create", "delete", "update"),
                "agentcore-trace-subscription",
                _permission("logs:PutSubscriptionFilter", f"{group}:*"),
                _permission("logs:DeleteSubscriptionFilter", f"{group}:*"),
                _permission(
                    "iam:PassRole",
                    TRACE_LOGS_ROLE,
                    conditions={"iam:PassedToService": "logs.amazonaws.com"},
                ),
                create_identity=(
                    ("name", "nova-toll-v2-agentcore-traces-dev"),
                    ("log_group_name", group.rsplit(":", 1)[-1]),
                    ("destination_arn", TRACE_FIREHOSE),
                    ("role_arn", TRACE_LOGS_ROLE),
                    (
                        "filter_pattern",
                        '{ $.traceId = "*" && $.spanId = "*" && $.durationNano >= 0 }',
                    ),
                ),
                provider_change_identity=(
                    ("account_id", ACCOUNT),
                    ("log_group_name", group.rsplit(":", 1)[-1]),
                    ("name", "nova-toll-v2-agentcore-traces-dev"),
                    ("region", REGION),
                ),
            )
        )
    result["aws_s3_bucket_lifecycle_configuration.agent_measurement"] = _mutation(
        ("rule",),
        ("update",),
        "agentcore-trace-retention",
        _permission("s3:PutLifecycleConfiguration", TRACE_MEASUREMENT_BUCKET),
        provider_change_identity=(
            ("account_id", ACCOUNT),
            ("bucket", TRACE_MEASUREMENT_BUCKET.removeprefix("arn:aws:s3:::")),
            ("region", REGION),
        ),
    )
    result["aws_glue_catalog_table.agentcore_traces[0]"] = _mutation(
        ("database_name", "name", "parameters", "storage_descriptor", "table_type"),
        ("create", "delete", "update"),
        "agentcore-trace-catalog",
        *(
            _permission(action, resource)
            for action in ("glue:CreateTable", "glue:DeleteTable", "glue:UpdateTable")
            for resource in TRACE_GLUE
        ),
        create_identity=(
            ("database_name", "tollchat_agent_reports_development"),
            ("name", "agentcore_traces"),
            ("table_type", "EXTERNAL_TABLE"),
        ),
    )
    result["aws_athena_named_query.agentcore_trace_summary[0]"] = _mutation(
        ("database", "description", "name", "query", "workgroup"),
        ("create", "delete", "update"),
        "agentcore-trace-query",
        _permission("athena:CreateNamedQuery", TRACE_WORKGROUP),
        _permission("athena:DeleteNamedQuery", TRACE_WORKGROUP),
        create_identity=(
            ("database", "tollchat_agent_reports_development"),
            ("name", "agentcore-trace-summary-dev"),
            ("workgroup", "tollchat-agent-reports-dev"),
        ),
    )
    result["aws_api_gateway_deployment.tollchat"] = _mutation(
        ("triggers.redeployment",),
        ("create",),
        "api-deployment",
        _permission(
            "apigateway:POST",
            f"arn:aws:apigateway:{REGION}::/restapis/ocw8sg0wlb/deployments",
            f"arn:aws:apigateway:{REGION}::/restapis/ocw8sg0wlb/deployments/*",
        ),
    )
    for name in ("public_chat_routes", "public_report_routes"):
        result[f"aws_cloudfront_function.{name}"] = _mutation(
            ("code",),
            ("update", "publish"),
            "cloudfront-code",
            _permission(
                "cloudfront:UpdateFunction",
                f"arn:aws:cloudfront::{ACCOUNT}:function/tollchat-v2-{name.replace('_', '-')}-dev",
            ),
            _permission(
                "cloudfront:PublishFunction",
                f"arn:aws:cloudfront::{ACCOUNT}:function/tollchat-v2-{name.replace('_', '-')}-dev",
            ),
        )
    for endpoint, group in zip(("DEFAULT", "preview"), TRACE_LOG_GROUPS, strict=False):
        group_name = group.split(":log-group:", 1)[1].removesuffix(":*")
        result[f'aws_cloudwatch_log_data_protection_policy.agentcore["{endpoint}"]'] = (
            _mutation(
                ("log_group_name", "policy_document"),
                ("create", "update"),
                "telemetry-log-protection",
                _permission("logs:PutDataProtectionPolicy", group),
                create_identity=(("log_group_name", group_name),),
            )
        )
        result[
            f'aws_cloudwatch_log_metric_filter.telemetry_redaction["{endpoint}"]'
        ] = _mutation(
            ("name", "log_group_name", "pattern", "metric_transformation"),
            ("create", "update"),
            "telemetry-failure-metric",
            _permission("logs:PutMetricFilter", group),
            create_identity=(
                ("name", "tollchat-redaction-failures"),
                ("log_group_name", group_name),
            ),
        )
    for key, name in (
        ("telemetry_redaction", "redaction-failures"),
        ('telemetry_pii["DEFAULT"]', "pii-findings-DEFAULT"),
        ('telemetry_pii["preview"]', "pii-findings-preview"),
    ):
        alarm_name = f"tollchat-v2-{name}-dev"
        alarm_arn = f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{alarm_name}"
        result[f"aws_cloudwatch_metric_alarm.{key}"] = _mutation(
            (
                "alarm_name",
                "alarm_description",
                "namespace",
                "metric_name",
                "dimensions",
                "statistic",
                "period",
                "evaluation_periods",
                "comparison_operator",
                "threshold",
                "treat_missing_data",
                "alarm_actions",
                "tags",
            ),
            ("create", "update"),
            "telemetry-alarm",
            _permission("cloudwatch:PutMetricAlarm", alarm_arn),
            _permission("cloudwatch:TagResource", alarm_arn),
            _permission("cloudwatch:UntagResource", alarm_arn),
            create_identity=(("alarm_name", alarm_name),),
        )
    # Only the fixed billing resources use the shared production/development gate.
    cost_name = "tollchat-v2-cost-publisher-dev"
    cost_role = f"arn:aws:iam::{ACCOUNT}:role/{cost_name}"
    cost_function = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{cost_name}"
    cost_rule = f"arn:aws:events:{REGION}:{ACCOUNT}:rule/{cost_name}"
    cost_log = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{cost_name}"
    billing = {
        "aws_iam_role.costs": (
            (
                "name",
                "assume_role_policy",
                "path",
                "max_session_duration",
                "force_detach_policies",
            ),
            ("iam:CreateRole", cost_role),
            ("iam:TagRole", cost_role),
        ),
        "aws_iam_role_policy.costs": (
            ("name", "role", "policy"),
            ("iam:PutRolePolicy", cost_role),
        ),
        "aws_cloudwatch_log_group.costs": (
            ("name", "retention_in_days"),
            ("logs:CreateLogGroup", cost_log),
            ("logs:PutRetentionPolicy", cost_log),
        ),
        "aws_lambda_function.costs": (
            (
                "function_name",
                "role",
                "runtime",
                "handler",
                "architectures",
                "timeout",
                "memory_size",
                "reserved_concurrent_executions",
                "package_type",
                "publish",
                "environment",
                "filename",
                "source_code_hash",
            ),
            ("lambda:CreateFunction", cost_function),
            ("lambda:PutFunctionConcurrency", cost_function),
        ),
        "aws_cloudwatch_event_rule.costs": (
            ("name", "event_bus_name", "schedule_expression", "state"),
            ("events:PutRule", cost_rule),
        ),
        "aws_cloudwatch_event_target.costs": (
            ("rule", "event_bus_name", "target_id", "arn", "input", "retry_policy"),
            ("events:PutTargets", cost_rule),
        ),
        "aws_lambda_permission.costs": (
            (
                "statement_id",
                "action",
                "function_name",
                "principal",
                "source_arn",
                "source_account",
            ),
            ("lambda:AddPermission", cost_function),
        ),
        "aws_s3_object.cost_dashboard": (
            ("bucket", "key", "content", "content_type", "cache_control"),
            ("s3:PutObject", f"{SITE_BUCKET}/costs.html"),
        ),
        **{
            f'aws_s3_object.cost_assets["{asset}"]': (
                (
                    "bucket",
                    "key",
                    "source",
                    "source_hash",
                    "content_type",
                    "cache_control",
                ),
                ("s3:PutObject", f"{SITE_BUCKET}/assets/{asset}"),
            )
            for asset in ("costs.css", "costs.mjs", "evals.css")
        },
    }
    for address, (fields, *permissions) in billing.items():
        required = [_permission(action, resource) for action, resource in permissions]
        if address == "aws_lambda_function.costs":
            required += [
                _permission(
                    "iam:PassRole",
                    cost_role,
                    conditions={"iam:PassedToService": "lambda.amazonaws.com"},
                ),
                _permission("lambda:TagResource", cost_function),
            ]
        if address == "aws_cloudwatch_event_rule.costs":
            required.append(_permission("events:TagResource", cost_rule))
        if address == "aws_cloudwatch_log_group.costs":
            required.append(_permission("logs:TagResource", cost_log))
        result[address] = _mutation(
            fields, ("create", "update"), "cost-publication", *required
        )
    for name in ("site", "staging"):
        result[f"aws_cloudfront_distribution.{name}"] = _mutation(
            ("ordered_cache_behavior",),
            ("update",),
            "cost-routing",
            _permission(
                "cloudfront:UpdateDistribution",
                f"arn:aws:cloudfront::{ACCOUNT}:distribution/*",
            ),
        )
    return result


CONTRACT = MappingProxyType(_build_contract())
SUPPORTED_ADDRESSES = frozenset(CONTRACT)
TIMED_ADDRESSES = frozenset(
    {
        "aws_s3_object.timed_checks",
        "aws_lambda_function.timed_checks",
        *(
            f'aws_scheduler_schedule.timed_checks["{key}"]'
            for key in TIMED_SCHEDULE_KEYS
        ),
    }
)

_PLAN_KEYS = frozenset(
    {
        "format_version",
        "terraform_version",
        "resource_changes",
        "planned_values",
        "prior_state",
        "configuration",
        "output_changes",
        "variables",
        "timestamp",
        "checks",
        "errored",
        "applyable",
        "complete",
        "resource_drift",
        "relevant_attributes",
    }
)
_RESOURCE_KEYS = frozenset(
    {
        "address",
        "mode",
        "type",
        "name",
        "index",
        "provider_name",
        "schema_version",
        "change",
        "deposed",
        "previous_address",
        "action_reason",
        "depends_on",
    }
)
_CHANGE_KEYS = frozenset(
    {
        "actions",
        "before",
        "after",
        "after_unknown",
        "before_sensitive",
        "after_sensitive",
        "replace_paths",
        "action_reason",
        "before_identity",
        "after_identity",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "provider_identity",
        "deployment_inputs",
        "packages",
        "mutations",
        "permissions",
    }
)
_MUTATION_KEYS = frozenset({"address", "action", "operation_class", "changed_fields"})
_PERMISSION_KEYS = frozenset({"address", "action", "resource", "conditions"})
_ACTIONS = frozenset(
    {"create", "update", "delete", "read", "no-op", "import", "refresh"}
)
_PRODUCTION_ACCOUNT = "920534282028"
_PRODUCTION_MARKERS = re.compile(
    r"(?:^|[-_/:.])(?:production|prod)(?:$|[-_/:.])"
    r"|(?<![A-Za-z0-9.-])(?:www\.)?tollchat\.ai(?::\d+)?(?=$|[/?#])",
    re.IGNORECASE,
)
_AUTHORIZATION_FIELDS = frozenset(
    {
        "runtime",
        "handler",
        "role",
        "environment",
        "memory_size",
        "timeout",
        "reserved_concurrent_executions",
        "vpc_config",
        "layers",
        "architectures",
        "tracing_config",
        "ephemeral_storage",
        "file_system_config",
        "function_url_config",
        "event_invoke_config",
        "invoke_config",
        "permissions",
        "publish",
        "kms_key_arn",
        "code_signing_config_arn",
        "package_type",
        "image_uri",
        "acl",
        "tags",
        "content_type",
        "cache_control",
        "force_destroy",
        "policy",
        "public_access_block",
        "lifecycle_rule",
        "versioning",
        "logging",
        "encryption",
        "role_arn",
        "target_arn",
        "schedule_expression",
        "guardrail_arn",
        "resource_policy",
        "domain_name",
    }
)
_DERIVED_UNKNOWN_EDGES = MappingProxyType(
    {
        **{
            (address, "destination_arn"): (
                ("destination_arn",),
                ("destination_arn",),
                "aws_kinesis_firehose_delivery_stream.agentcore_traces[0].arn",
                "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]",
            )
            for address in (
                'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]',
                'aws_cloudwatch_log_subscription_filter.agentcore_traces["preview"]',
            )
        },
        (
            "aws_bedrockagentcore_agent_runtime.tollchat",
            "agent_runtime_artifact.code_configuration.code.s3.version_id",
        ): (
            (
                "agent_runtime_artifact.code_configuration.code.s3.version_id",
                "agent_runtime_artifact[0].code_configuration[0].code[0].s3[0].version_id",
            ),
            (
                "agent_runtime_artifact.code_configuration.code.s3.version_id",
                "agent_runtime_artifact.0.code_configuration.0.code.0.s3.0.version_id",
            ),
            "aws_s3_object.agentcore.version_id",
            "aws_s3_object.agentcore",
        ),
        (
            "aws_bedrockagentcore_agent_runtime_endpoint.tollchat",
            "agent_runtime_version",
        ): (
            ("agent_runtime_version",),
            ("agent_runtime_version",),
            "aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_version",
            "aws_bedrockagentcore_agent_runtime.tollchat",
        ),
        ("aws_lambda_alias.tollchat_live", "function_version"): (
            ("function_version",),
            ("function_version",),
            "aws_lambda_function.tollchat_proxy.version",
            "aws_lambda_function.tollchat_proxy",
        ),
        ("aws_lambda_function.tollchat_proxy", "s3_object_version"): (
            ("s3_object_version",),
            ("s3_object_version",),
            "aws_s3_object.tollchat_proxy.version_id",
            "aws_s3_object.tollchat_proxy",
        ),
        ("aws_lambda_function.timed_checks", "s3_object_version"): (
            ("s3_object_version",),
            ("s3_object_version",),
            "aws_s3_object.timed_checks.version_id",
            "aws_s3_object.timed_checks",
        ),
    }
)


class InvalidPlan(Exception):
    def __init__(
        self,
        reason: str,
        *,
        address: str | None = None,
        action: str | None = None,
        operation_class: str | None = None,
    ) -> None:
        self.reason = reason
        self.address = address
        self.action = action
        self.operation_class = operation_class


def _reject(
    reason: str,
    *,
    address: str | None = None,
    action: str | None = None,
    operation_class: str | None = None,
) -> NoReturn:
    raise InvalidPlan(
        reason, address=address, action=action, operation_class=operation_class
    )


def _is_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _timed_schedule_expected(address: str) -> dict[str, Any]:
    key = address.removeprefix('aws_scheduler_schedule.timed_checks["').removesuffix(
        '"]'
    )
    if key not in TIMED_SCHEDULE_KEYS:
        _reject("unsupported_address", address=address)
    prefix, day, clock = key.rsplit("-", 2)
    weekdays = {
        "mon": ("1", "MON"),
        "tue": ("2", "TUE"),
        "wed": ("3", "WED"),
        "thu": ("4", "THU"),
        "fri": ("5", "FRI"),
        "sat": ("6", "SAT"),
    }
    windows = {
        "greenway-eb": "greenway_eb_peak",
        "greenway-wb": "greenway_wb_peak",
        "i95-northbound": "i95_northbound",
        "i95-reversal": "i95_reversal",
        "i95-southbound": "i95_southbound",
    }
    weekday, aws_weekday = weekdays[day]
    hour, minute = str(int(clock[:2])), str(int(clock[2:]))
    schedule = f"{minute} {hour} * * {weekday}"
    return {
        "name": f"nova-toll-v2-{key}-dev",
        "state": "ENABLED",
        "schedule_expression": f"cron({minute} {hour} ? * {aws_weekday} *)",
        "schedule_expression_timezone": "America/New_York",
        "window_id": windows[prefix],
        "schedule": schedule,
    }


def timed_schedule_plan_value(address: str) -> dict[str, Any]:
    expected = _timed_schedule_expected(address)
    return {
        "name": expected["name"],
        "state": expected["state"],
        "schedule_expression": expected["schedule_expression"],
        "schedule_expression_timezone": expected["schedule_expression_timezone"],
        "flexible_time_window": [{"mode": "OFF"}],
        "target": [
            {
                "arn": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:nova-toll-v2-timed-checks-dev",
                "role_arn": f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-timed-checks-scheduler-dev",
                "input": json.dumps(
                    {
                        "window_id": expected["window_id"],
                        "schedule": expected["schedule"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "retry_policy": [
                    {"maximum_event_age_in_seconds": 600, "maximum_retry_attempts": 0}
                ],
                "dead_letter_config": [
                    {
                        "arn": f"arn:aws:sqs:{REGION}:{ACCOUNT}:nova-toll-v2-timed-checks-delivery-failure-dev"
                    }
                ],
            }
        ],
    }


def _validate_timed_schedule(
    after: dict[str, JSON], address: str, action: str, operation_class: str
) -> None:
    after = copy.deepcopy(after)
    expected = _timed_schedule_expected(address)
    for field in (
        "name",
        "state",
        "schedule_expression",
        "schedule_expression_timezone",
    ):
        if after.get(field) != expected[field]:
            _reject(
                "invalid_schedule_value",
                address=address,
                action=action,
                operation_class=operation_class,
            )
    windows = after.get("flexible_time_window")
    if (
        not isinstance(windows, list)
        or len(windows) != 1
        or not isinstance(windows[0], dict)
        or windows[0].get("mode") != "OFF"
    ):
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    if "maximum_window_in_minutes" in windows[0]:
        if windows[0]["maximum_window_in_minutes"] is not None:
            _reject(
                "invalid_schedule_value",
                address=address,
                action=action,
                operation_class=operation_class,
            )
        del windows[0]["maximum_window_in_minutes"]
    if set(windows[0]) != {"mode"}:
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    targets = after.get("target")
    if (
        not isinstance(targets, list)
        or len(targets) != 1
        or not isinstance(targets[0], dict)
    ):
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    target = targets[0]
    required = {
        "arn": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:nova-toll-v2-timed-checks-dev",
        "role_arn": f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-timed-checks-scheduler-dev",
    }
    if any(target.get(field) != value for field, value in required.items()):
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    for field in (
        "ecs_parameters",
        "eventbridge_parameters",
        "kinesis_parameters",
        "sagemaker_pipeline_parameters",
        "sqs_parameters",
    ):
        if field in target:
            if type(target[field]) is not list or target[field]:
                _reject(
                    "invalid_schedule_value",
                    address=address,
                    action=action,
                    operation_class=operation_class,
                )
            del target[field]
    target_fields = {"arn", "role_arn", "input", "retry_policy", "dead_letter_config"}
    if set(target) != target_fields:
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    try:
        payload = json.loads(cast(str, target.get("input", "")))
    except (TypeError, json.JSONDecodeError):
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    if payload != {
        "window_id": expected["window_id"],
        "schedule": expected["schedule"],
    }:
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    if target.get("retry_policy") != [
        {"maximum_event_age_in_seconds": 600, "maximum_retry_attempts": 0}
    ] or target.get("dead_letter_config") != [
        {
            "arn": f"arn:aws:sqs:{REGION}:{ACCOUNT}:nova-toll-v2-timed-checks-delivery-failure-dev"
        }
    ]:
        _reject(
            "invalid_schedule_value",
            address=address,
            action=action,
            operation_class=operation_class,
        )


def _flatten(value: JSON, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        if not value and prefix:
            return {prefix: {}}
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not _is_string(key) or not key:
                _reject("malformed_input")
            result.update(_flatten(child, f"{prefix}.{key}" if prefix else key))
        return result
    if isinstance(value, list):
        if not value and prefix:
            return {prefix: []}
        result: dict[str, Any] = {}
        for index, child in enumerate(value):
            result.update(_flatten(child, f"{prefix}[{index}]"))
        return result
    return {prefix: value}


def _without_paths(value: JSON, ignored: tuple[str, ...], prefix: str = "") -> JSON:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if path in ignored:
                continue
            result[key] = _without_paths(child, ignored, path)
        return result
    if isinstance(value, list):
        items: list[JSON] = []
        for index, child in enumerate(value):
            path = f"{prefix}[{index}]"
            if path in ignored:
                continue
            items.append(_without_paths(child, ignored, path))
        return items
    return value


def _changed_fields(
    before: JSON,
    after: JSON,
    allowed: tuple[str, ...] = (),
    ignored: tuple[str, ...] = (),
) -> tuple[str, ...]:
    left = _flatten(before) if before is not None else {}
    right = _flatten(after) if after is not None else {}
    changed = (
        key
        for key in set(left) | set(right)
        if left.get(key) != right.get(key)
        and not any(_path_allowed(key, (path,)) for path in ignored)
    )
    result: set[str] = set()
    for path in changed:
        parents = [field for field in allowed if _path_allowed(path, (field,))]
        result.add(max(parents, key=len) if parents else path)
    return tuple(sorted(result))


def _path_allowed(path: str, fields: tuple[str, ...]) -> bool:
    normalized = re.sub(r"\[\d+\]", "", path)
    return any(
        normalized == field or normalized.startswith(field + ".") for field in fields
    )


def _path_root(path: str) -> str:
    return re.sub(r"\[\d+\]", "", path).split(".", 1)[0]


def _create_fields(
    after: dict[str, Any],
    spec: Mutation,
    address: str,
    action: str,
    ignored: tuple[str, ...] = (),
) -> tuple[str, ...]:
    result: set[str] = set()
    for path, value in _flatten(after).items():
        if any(_path_allowed(path, (ignored_path,)) for ignored_path in ignored):
            continue
        parents = [field for field in spec.fields if _path_allowed(path, (field,))]
        if parents:
            result.add(max(parents, key=len))
        elif _path_root(path) in _AUTHORIZATION_FIELDS and value not in (
            None,
            False,
            "",
            {},
            [],
        ):
            _reject(
                "unsupported_field_delta",
                address=address,
                action=action,
                operation_class=spec.operation_class,
            )
    return tuple(sorted(result))


def _metadata_authorized(path: str, spec: Mutation) -> bool:
    return (
        _path_allowed(path, spec.fields)
        or any(_path_allowed(path, (field,)) for field, _ in spec.create_identity)
        or any(
            _path_allowed(path, (field,)) for field, _ in spec.provider_change_identity
        )
        or _path_root(path) in _AUTHORIZATION_FIELDS
    )


def _validate_s3_identity(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    spec: Mutation,
    address: str,
    action: str,
    unknown_paths: tuple[str, ...] = (),
) -> None:
    if action not in {"create", "update", "no-op"} or not spec.create_identity:
        return
    values = (after,) if action == "create" else (before, after)
    if any(
        not isinstance(value, dict)
        or any(
            (field not in value and field not in unknown_paths)
            or (field in value and value[field] != expected)
            for field, expected in spec.create_identity
        )
        for value in values
    ):
        _reject(
            "invalid_resource_identity",
            address=address,
            action=action,
            operation_class=spec.operation_class,
        )


def _publisher_policy(
    value: JSON, address: str, action: str, operation_class: str
) -> dict[str, dict[str, Any]]:
    try:
        policy: JSON = json.loads(cast(str, value))
    except (TypeError, json.JSONDecodeError):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    if (
        not isinstance(policy, dict)
        or set(policy) != {"Version", "Statement"}
        or policy["Version"] != "2012-10-17"
        or not isinstance(policy["Statement"], list)
    ):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    statements = policy["Statement"]
    if any(
        not isinstance(statement, dict) or not isinstance(statement.get("Sid"), str)
        for statement in statements
    ):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    by_sid = {
        cast(str, statement["Sid"]): copy.deepcopy(statement)
        for statement in cast(list[dict[str, JSON]], statements)
    }
    if len(by_sid) != len(statements):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    for statement in by_sid.values():
        for field in ("Action", "Resource"):
            value = statement.get(field)
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                _reject(
                    "unsupported_field_delta",
                    address=address,
                    action=action,
                    operation_class=operation_class,
                )
            statement[field] = list[JSON](sorted(cast(list[str], value)))
        condition = statement.get("Condition")
        if isinstance(condition, dict):
            for values in condition.values():
                if not isinstance(values, dict):
                    _reject(
                        "unsupported_field_delta",
                        address=address,
                        action=action,
                        operation_class=operation_class,
                    )
                for variable, items in values.items():
                    if isinstance(items, str):
                        items = [items]
                    if not isinstance(items, list) or any(
                        not isinstance(item, str) for item in items
                    ):
                        _reject(
                            "unsupported_field_delta",
                            address=address,
                            action=action,
                            operation_class=operation_class,
                        )
                    values[variable] = list[JSON](sorted(cast(list[str], items)))
    return by_sid


def _publisher_statement(
    sid: str,
    action_name: str,
    resources: tuple[str, ...],
    *,
    condition: tuple[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    statement: dict[str, Any] = {
        "Sid": sid,
        "Effect": "Allow",
        "Action": [action_name],
        "Resource": sorted(resources),
    }
    if condition is not None:
        variable, values = condition
        statement["Condition"] = {"StringEquals": {variable: sorted(values)}}
    return statement


def _validate_publisher_policy(
    before: JSON, after: JSON, address: str, action: str, operation_class: str
) -> None:
    if not isinstance(before, dict) or not isinstance(after, dict):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    old, new = (
        _publisher_policy(value.get("policy"), address, action, operation_class)
        for value in (before, after)
    )
    bucket = f"arn:aws:s3:::{SITE_BUCKET_NAME}"
    expected_old = {
        "ReadPublicationManifest": _publisher_statement(
            "ReadPublicationManifest",
            "s3:GetObject",
            (f"{bucket}/tolls/i95-i495/manifest.json",),
        ),
        "FindPublicationManifest": _publisher_statement(
            "FindPublicationManifest",
            "s3:ListBucket",
            (bucket,),
            condition=("s3:prefix", ("tolls/i95-i495/manifest.json",)),
        ),
        "WritePublicReports": _publisher_statement(
            "WritePublicReports",
            "s3:PutObject",
            (f"{bucket}/tolls/i95-i495/*", f"{bucket}/sitemap.xml"),
        ),
    }
    expected_new = {
        "ListPublicReports": _publisher_statement(
            "ListPublicReports",
            "s3:ListBucket",
            (bucket,),
            condition=("s3:prefix", ("tolls/i95-i495/", "tolls/i66/")),
        ),
        "WritePublicReports": _publisher_statement(
            "WritePublicReports",
            "s3:PutObject",
            (
                f"{bucket}/tolls/i95-i495/*",
                f"{bucket}/tolls/i66/*",
                f"{bucket}/sitemap.xml",
            ),
        ),
        "DeleteStalePublicReports": _publisher_statement(
            "DeleteStalePublicReports",
            "s3:DeleteObject",
            (f"{bucket}/tolls/i95-i495/*", f"{bucket}/tolls/i66/*"),
        ),
    }
    retained_sids = {"ConnectRdsIam", "SendInvokeFailure", "UseSiteKey"}
    if set(old) != retained_sids | set(expected_old) or set(new) != retained_sids | set(
        expected_new
    ):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )
    old_s3 = {sid: old.pop(sid, None) for sid in expected_old}
    new_s3 = {sid: new.pop(sid, None) for sid in expected_new}
    expected_retained = {
        "SendInvokeFailure": _publisher_statement(
            "SendInvokeFailure",
            "sqs:SendMessage",
            (
                f"arn:aws:sqs:{REGION}:{ACCOUNT}:toll-v2-report-publisher-invoke-failure-dev",
            ),
        ),
    }
    rds = old.get("ConnectRdsIam")
    site_key = old.get("UseSiteKey")
    if (
        old_s3 != expected_old
        or new_s3 != expected_new
        or old != new
        or old.get("SendInvokeFailure") != expected_retained["SendInvokeFailure"]
        or not isinstance(rds, dict)
        or set(rds) != {"Sid", "Effect", "Action", "Resource"}
        or rds.get("Effect") != "Allow"
        or rds.get("Action") != ["rds-db:connect"]
        or rds.get("Resource")
        != sorted(
            [
                f"arn:aws:rds-db:{REGION}:{ACCOUNT}:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/report_publisher_development",
                f"arn:aws:rds-db:{REGION}:{ACCOUNT}:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/pricing_reader_development",
            ]
        )
        or not isinstance(site_key, dict)
        or set(site_key) != {"Sid", "Effect", "Action", "Resource"}
        or site_key.get("Effect") != "Allow"
        or site_key.get("Action")
        != ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
        or site_key.get("Resource") != [PUBLISHER_SITE_KEY_ARN]
    ):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )


def _validate_trace_runtime_policy(
    before: JSON, after: JSON, address: str, action: str, operation_class: str
) -> None:
    if not isinstance(before, dict) or not isinstance(after, dict):
        _trace_reject(address, action, operation_class)
    old, new = (
        _publisher_policy(value.get("policy"), address, action, operation_class)
        for value in (before, after)
    )
    statement = _publisher_statement(
        "EnableUnifiedRuntimeTraceDelivery",
        "logs:PutResourcePolicy",
        (
            f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-*",
        ),
        condition=("aws:RequestedRegion", (REGION,)),
    )
    added = new.pop(statement["Sid"], None)
    removed = old.pop(statement["Sid"], None)
    old_apply, new_apply = old.get("ApplyGuardrail"), new.get("ApplyGuardrail")
    telemetry_added = False
    if isinstance(old_apply, dict) and isinstance(new_apply, dict):
        old_resources = old_apply.get("Resource", [])
        new_resources = new_apply.get("Resource", [])
        extra = set(new_resources) - set(old_resources)
        if len(extra) == 1 and re.fullmatch(
            r"arn:aws:bedrock:us-east-1:903859731897:guardrail/[a-z0-9]+",
            next(iter(extra)),
        ):
            new_apply["Resource"] = [
                item for item in new_resources if item not in extra
            ]
            telemetry_added = True
    if old != new or not (
        (added, removed) in ((statement, None), (None, statement))
        or (telemetry_added and added == removed == statement)
    ):
        _trace_reject(address, action, operation_class)


def _validate_report_freshness_alarm(
    before: JSON, after: JSON, address: str, action: str, operation_class: str
) -> None:
    expected_before = {
        "alarm_description": "No complete I-95/I-495 report generation in the trailing seven-day sliding window.",
        "dimensions": {"facility": "i95_i495", "Environment": "development"},
    }
    expected_after = {
        "alarm_description": "No complete I-95/I-495 and I-66 report generation in the trailing seven-day sliding window.",
        "dimensions": {"facility_scope": "both", "Environment": "development"},
    }
    if (
        not isinstance(before, dict)
        or not isinstance(after, dict)
        or any(
            value.get(field) != expected
            for value, expected_values in (
                (before, expected_before),
                (after, expected_after),
            )
            for field, expected in expected_values.items()
        )
    ):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=operation_class,
        )


def _validate_agentcore_trace_value(
    before: JSON,
    after: JSON,
    address: str,
    action: str,
    operation_class: str,
    unknown_paths: tuple[str, ...] = (),
) -> None:
    value = before if action == "delete" else after
    if not isinstance(value, dict):
        _trace_reject(address, action, operation_class)

    def configured(candidate: JSON) -> JSON:
        if not isinstance(candidate, dict):
            _trace_reject(address, action, operation_class)
        if (
            operation_class == "agentcore-trace-catalog"
            and candidate.get("partition_keys") != []
        ):
            _trace_reject(address, action, operation_class)
        return _without_paths(
            candidate,
            TRACE_READ_ONLY_FIELDS.get(address, ()) + unknown_paths,
        )

    if operation_class == "agentcore-trace-subscription":
        expected = _without_paths(
            dict(CONTRACT[address].create_identity), unknown_paths
        )
        values = (
            (before,)
            if action == "delete"
            else (after,)
            if action == "create"
            else (before, after)
        )
        if any(configured(candidate) != expected for candidate in values):
            _trace_reject(address, action, operation_class)
    elif operation_class == "agentcore-trace-firehose":
        expected = _trace_firehose_value()
        values = (
            (before,)
            if action == "delete"
            else (after,)
            if action == "create"
            else (before, after)
        )
        if any(configured(candidate) != expected for candidate in values):
            _trace_reject(address, action, operation_class)
    elif operation_class == "agentcore-trace-catalog":
        expected = {
            "database_name": "tollchat_agent_reports_development",
            "name": "agentcore_traces",
            "table_type": "EXTERNAL_TABLE",
            "parameters": {"EXTERNAL": "TRUE"},
            "storage_descriptor": [
                {
                    "location": f"s3://{TRACE_MEASUREMENT_BUCKET.removeprefix('arn:aws:s3:::')}/{TRACE_PREFIX}",
                    "input_format": "org.apache.hadoop.mapred.TextInputFormat",
                    "output_format": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                    "columns": [
                        {
                            "name": "raw_json",
                            "type": "string",
                        }
                    ],
                    "ser_de_info": [
                        {
                            "serialization_library": "org.apache.hadoop.hive.serde2.RegexSerDe",
                            "parameters": {"input.regex": "^(.*)$"},
                        }
                    ],
                }
            ],
        }
        values = (
            (before,)
            if action == "delete"
            else (after,)
            if action == "create"
            else (before, after)
        )
        if any(configured(candidate) != expected for candidate in values):
            _trace_reject(address, action, operation_class)
    elif operation_class == "agentcore-trace-query":
        expected = {
            "database": "tollchat_agent_reports_development",
            "name": "agentcore-trace-summary-dev",
            "workgroup": "tollchat-agent-reports-dev",
            "description": "Bounded development trace outcome summary",
            "query": TRACE_QUERY,
        }
        values = (
            (before,)
            if action == "delete"
            else (after,)
            if action == "create"
            else (before, after)
        )
        if any(configured(candidate) != expected for candidate in values):
            _trace_reject(address, action, operation_class)
    elif operation_class == "agentcore-trace-retention":

        def canonical(value: JSON) -> tuple[str, ...] | None:
            if not isinstance(value, dict) or not isinstance(value.get("rule"), list):
                return None
            normalized: list[dict[str, JSON]] = []
            for source in cast(list[JSON], value["rule"]):
                if not isinstance(source, dict):
                    return None
                rule = copy.deepcopy(source)
                defaults_by_field: tuple[tuple[str, JSON], ...] = (
                    ("noncurrent_version_expiration", []),
                    ("noncurrent_version_transition", []),
                    ("prefix", ""),
                    ("transition", []),
                )
                for field, default in defaults_by_field:
                    if field in rule:
                        if rule[field] != default:
                            return None
                        rule.pop(field)
                if rule.get("abort_incomplete_multipart_upload") == []:
                    rule.pop("abort_incomplete_multipart_upload")
                block_defaults: tuple[tuple[str, dict[str, JSON]], ...] = (
                    (
                        "filter",
                        {
                            "and": [],
                            "object_size_greater_than": None,
                            "object_size_less_than": None,
                            "tag": [],
                        },
                    ),
                    (
                        "expiration",
                        {"date": None, "expired_object_delete_marker": False},
                    ),
                )
                for block_name, defaults in block_defaults:
                    blocks = rule.get(block_name)
                    if not isinstance(blocks, list):
                        return None
                    for block in blocks:
                        if not isinstance(block, dict):
                            return None
                        for field, default in defaults.items():
                            if field in block:
                                if block[field] != default:
                                    return None
                                block.pop(field)
                normalized.append(rule)
            return tuple(sorted(_canonical(rule) for rule in normalized))

        baseline = tuple(
            sorted(_canonical(rule) for rule in _trace_lifecycle(enabled=False))
        )
        traced = tuple(
            sorted(_canonical(rule) for rule in _trace_lifecycle(enabled=True))
        )
        if (canonical(before), canonical(after)) != (baseline, traced):
            _trace_reject(address, action, operation_class)
    elif address == "aws_bedrockagentcore_agent_runtime.tollchat":
        if not isinstance(before, dict) or not isinstance(after, dict):
            _trace_reject(address, action, operation_class)
        runtime_identity = {
            "agent_runtime_arn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl",
            "agent_runtime_id": "nova_toll_v2_development-Y69XBf88Bl",
            "agent_runtime_name": "nova_toll_v2_development",
            "region": REGION,
            "role_arn": f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-agentcore-runtime-dev",
        }
        if any(
            any(
                candidate.get(key) != expected
                for key, expected in runtime_identity.items()
            )
            for candidate in (before, after)
        ):
            _trace_reject(address, action, operation_class)
        before_env, after_env = (
            before.get("environment_variables"),
            after.get("environment_variables"),
        )
        if not isinstance(before_env, dict) or not isinstance(after_env, dict):
            _trace_reject(address, action, operation_class)
        telemetry_keys = {
            "TOLLCHAT_TELEMETRY_GUARDRAIL_ID",
            "TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION",
        }
        ignored_keys = telemetry_keys | {"UNIFIED_TRACES_DESTINATION_ENABLED"}
        old = {
            key: value for key, value in before_env.items() if key not in ignored_keys
        }
        new = {
            key: value for key, value in after_env.items() if key not in ignored_keys
        }
        if old != new:
            _trace_reject(address, action, operation_class)
        if telemetry_keys & set(after_env):
            if (
                after_env.get("UNIFIED_TRACES_DESTINATION_ENABLED") != "true"
                or not re.fullmatch(
                    r"[a-z0-9]+",
                    str(after_env.get("TOLLCHAT_TELEMETRY_GUARDRAIL_ID", "")),
                )
                or not re.fullmatch(
                    r"[1-9][0-9]*",
                    str(after_env.get("TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION", "")),
                )
            ):
                _trace_reject(address, action, operation_class)
        elif {
            cast(str | None, before_env.get("UNIFIED_TRACES_DESTINATION_ENABLED")),
            cast(str | None, after_env.get("UNIFIED_TRACES_DESTINATION_ENABLED")),
        } != {None, "true"}:
            _trace_reject(address, action, operation_class)


def _validate_telemetry_value(
    value: JSON, address: str, action: str, operation_class: str
) -> None:
    if not isinstance(value, dict):
        _trace_reject(address, action, operation_class)
    if operation_class == "telemetry-log-protection":
        try:
            policy = json.loads(cast(str, value["policy_document"]))
            digest = hashlib.sha256(
                json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        except (KeyError, TypeError, ValueError):
            _trace_reject(address, action, operation_class)
        if digest != "37b6be001869b097a89a67ef6fb3828039be35f7464155eb713f4f72ca567aa5":
            _trace_reject(address, action, operation_class)
    elif operation_class == "telemetry-failure-metric":
        transformations = value.get("metric_transformation")
        if (
            value.get("pattern")
            != "?telemetry_redaction_failed ?telemetry_redaction_omitted ?telemetry_export_failed"
            or not isinstance(transformations, list)
            or len(transformations) != 1
            or any(
                cast(dict[str, JSON], transformations[0]).get(k) != v
                for k, v in {
                    "name": "RedactionFailures",
                    "namespace": "TollChat/Telemetry",
                    "value": "1",
                }.items()
            )
            or cast(dict[str, JSON], transformations[0]).get("dimensions")
            not in (None, {})
            or cast(dict[str, JSON], transformations[0]).get("default_value")
            is not None
        ):
            _trace_reject(address, action, operation_class)
    elif operation_class == "telemetry-alarm":
        value = dict(value)
        # AWS normalizes omitted collections to either null or empty on create.
        if value.get("alarm_actions") is None:
            value["alarm_actions"] = []
        if value.get("dimensions") is None:
            value["dimensions"] = {}
        pii = "telemetry_pii[" in address
        endpoint = "DEFAULT" if '"DEFAULT"' in address else "preview"
        expected: dict[str, JSON] = {
            "namespace": "AWS/Logs" if pii else "TollChat/Telemetry",
            "metric_name": "LogEventsWithFindings" if pii else "RedactionFailures",
            "dimensions": {
                "LogGroupName": f"/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-{endpoint}"
            }
            if pii
            else {},
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "comparison_operator": "GreaterThanThreshold",
            "threshold": 0,
            "treat_missing_data": "notBreaching",
            "alarm_actions": [],
        }
        if (
            any(value.get(k) != v for k, v in expected.items())
            or value.get("ok_actions") not in (None, [])
            or value.get("insufficient_data_actions") not in (None, [])
            or value.get("metric_query") not in (None, [])
        ):
            _trace_reject(address, action, operation_class)


def _unknown_paths(value: JSON, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, bool):
        return (prefix,) if value else ()
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            if not _is_string(key):
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


def _expression_nodes(value: JSON, parts: tuple[str, ...]) -> tuple[JSON, ...]:
    if not parts:
        return (value,)
    if isinstance(value, list):
        if len(value) != 1:
            return (value,)
        return _expression_nodes(value[0], parts)
    if not isinstance(value, dict):
        return (value,)
    nodes: list[JSON] = []
    full_path = ".".join(parts)
    if full_path in value:
        nodes.extend(_expression_nodes(value[full_path], ()))
        return tuple(nodes)
    part = parts[0]
    if part in value:
        nodes.extend(_expression_nodes(value[part], parts[1:]))
    for wrapper in ("expressions", "block"):
        if wrapper in value:
            nodes.extend(_expression_nodes(value[wrapper], parts))
    return tuple(nodes)


def _has_configuration_reference(
    plan: Mapping[str, JSON],
    address: str,
    paths: tuple[str, ...],
    reference: str,
    producer: str,
) -> bool:
    configuration = plan.get("configuration")
    if not isinstance(configuration, dict):
        return False
    root_module = configuration.get("root_module")
    resources = root_module.get("resources") if isinstance(root_module, dict) else None
    if not isinstance(resources, list):
        return False
    configuration_address = address.split("[", 1)[0]
    matching = [
        resource
        for resource in resources
        if isinstance(resource, dict)
        and resource.get("address") in {address, configuration_address}
    ]
    if len(matching) != 1 or not isinstance(matching[0].get("expressions"), dict):
        return False
    expressions = matching[0]["expressions"]
    nodes: list[JSON] = []
    for path in paths:
        nodes.extend(_expression_nodes(expressions, tuple(path.split("."))))
    if len(nodes) != 1 or not isinstance(nodes[0], dict):
        return False
    references = nodes[0].get("references")
    expected = {reference, producer}
    if "[" in producer:
        expected.add(producer.split("[", 1)[0])
    return (
        isinstance(references, list)
        and len(references) == len(expected)
        and all(_is_string(item) for item in references)
        and set(references) == expected
    )


def _omitted_dashboard_acl(
    plan: Mapping[str, JSON], address: str, action: str, path: str
) -> bool:
    # AWS 6.60 computes ACL metadata on creation even when no ACL is configured.
    if (
        action != "create"
        or path != "acl"
        or address
        not in {
            "aws_s3_object.evals",
            'aws_s3_object.site_assets["evals.css"]',
            'aws_s3_object.site_assets["evals.mjs"]',
        }
    ):
        return False
    configuration = plan.get("configuration")
    root = configuration.get("root_module") if isinstance(configuration, dict) else None
    resources = root.get("resources") if isinstance(root, dict) else None
    if not isinstance(resources, list):
        return False
    matching = [
        resource
        for resource in resources
        if isinstance(resource, dict)
        and resource.get("address") in {address, address.split("[", 1)[0]}
    ]
    return (
        len(matching) == 1
        and isinstance(matching[0].get("expressions"), dict)
        and "acl" not in cast(dict[str, JSON], matching[0]["expressions"])
    )


def _validate_derived_unknowns(
    plan: Mapping[str, JSON],
    pending: list[tuple[str, str, str | None, tuple[str, ...]]],
    records: list[dict[str, Any]],
) -> None:
    producers = {
        record["address"]
        for record in records
        if record["action"] in {"create", "update"}
    }
    for address, action, operation_class, paths in pending:
        spec = CONTRACT.get(address)
        if operation_class == "cost-publication":
            continue  # The billing gate already rejects unknown authority fields.
        for path in paths:
            if path in TRACE_READ_ONLY_FIELDS.get(address, ()):
                continue
            if spec is None or not _metadata_authorized(path, spec):
                continue
            if _omitted_dashboard_acl(plan, address, action, path):
                continue
            edge = next(
                (
                    value
                    for (edge_address, _), value in _DERIVED_UNKNOWN_EDGES.items()
                    if edge_address == address and path in value[0]
                ),
                None,
            )
            if edge is None:
                _reject(
                    "unknown_authorization_value",
                    address=address,
                    action=action,
                    operation_class=operation_class,
                )
            _, expression_paths, reference, producer = edge
            if producer not in producers or not _has_configuration_reference(
                plan, address, expression_paths, reference, producer
            ):
                _reject(
                    "unknown_authorization_value",
                    address=address,
                    action=action,
                    operation_class=operation_class,
                )


def _walk_strings(value: JSON) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(
            item
            for key, child in value.items()
            for item in _walk_strings(key) + _walk_strings(child)
        )
    if isinstance(value, list):
        return tuple(item for child in value for item in _walk_strings(child))
    return ()


def _has_production_value(value: JSON) -> bool:
    return any(
        _PRODUCTION_ACCOUNT in item or _PRODUCTION_MARKERS.search(item)
        for item in _walk_strings(value)
    )


def _manifest_has_production_value(manifest: JSON) -> bool:
    if not isinstance(manifest, dict):
        return _has_production_value(manifest)
    for key, value in manifest.items():
        if key != "deployment_inputs" or not isinstance(value, dict):
            if _has_production_value(key) or _has_production_value(value):
                return True
            continue
        for source, digest in value.items():
            if source not in PRODUCTION_CONTROL_INPUTS and _has_production_value(
                source
            ):
                return True
            if _has_production_value(digest):
                return True
    return False


def _validate_identity(identity: JSON) -> None:
    if not isinstance(identity, dict):
        _reject("provider_identity_missing")
    if set(identity) != set(EXPECTED_IDENTITY) or any(
        not _is_string(value) for value in identity.values()
    ):
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


def _validate_resource_shape(
    resource: JSON,
) -> tuple[str, str, dict[str, Any], dict[str, tuple[str, ...]]]:
    if not isinstance(resource, dict) or not set(resource).issubset(_RESOURCE_KEYS):
        _reject("malformed_input")
    address = resource.get("address")
    mode = resource.get("mode")
    change = resource.get("change")
    if not _is_string(address) or not _is_string(mode) or not isinstance(change, dict):
        _reject("malformed_input")
    resource_type, resource_name, resource_index = _address_identity(address)
    if resource.get("type") != resource_type or resource.get("name") != resource_name:
        _reject("malformed_input", address=address, operation_class="resource-identity")
    if resource_index is None:
        if "index" in resource:
            _reject(
                "malformed_input", address=address, operation_class="index-envelope"
            )
    elif resource.get("index") != resource_index:
        _reject("malformed_input", address=address, operation_class="index-envelope")
    for key in ("type", "name", "provider_name", "action_reason"):
        if key in resource and not isinstance(resource[key], str):
            _reject(
                "malformed_input",
                address=address,
                operation_class="resource-field-envelope",
            )
    if "index" in resource and not isinstance(resource["index"], (str, int)):
        _reject("malformed_input", address=address, operation_class="index-envelope")
    if "schema_version" in resource and not isinstance(resource["schema_version"], int):
        _reject("malformed_input", address=address, operation_class="schema-envelope")
    if "depends_on" in resource and (
        not isinstance(resource["depends_on"], list)
        or any(not _is_string(item) for item in resource["depends_on"])
    ):
        _reject(
            "malformed_input", address=address, operation_class="dependency-envelope"
        )
    if not set(change).issubset(_CHANGE_KEYS) or not isinstance(
        change.get("actions"), list
    ):
        _reject("malformed_input", address=address, operation_class="change-envelope")
    if "action_reason" in change and not isinstance(change["action_reason"], str):
        _reject(
            "malformed_input", address=address, operation_class="action-reason-envelope"
        )
    actions = cast(list[str], change["actions"])
    if not actions or any(
        not _is_string(action) or action not in _ACTIONS for action in actions
    ):
        _reject("malformed_input", address=address, operation_class="action-envelope")
    for key in ("before_identity", "after_identity"):
        if (
            key in change
            and not isinstance(change[key], (dict, type(None)))
            and change[key] is not False
        ):
            _reject(
                "malformed_input", address=address, operation_class="identity-envelope"
            )
    if (
        len(actions) == 1
        and actions[0] == "update"
        and change.get("before_identity") != change.get("after_identity")
    ):
        _reject(
            "malformed_input",
            address=address,
            action=actions[0],
            operation_class="identity-transition",
        )
    if not isinstance(change.get("before"), (dict, type(None))) or not isinstance(
        change.get("after"), (dict, type(None))
    ):
        _reject("malformed_input", address=address, operation_class="value-envelope")
    if "replace_paths" in change and not isinstance(change["replace_paths"], list):
        _reject("malformed_input", address=address, operation_class="replace-envelope")
    metadata_paths: dict[str, tuple[str, ...]] = {}
    for key in ("after_unknown", "before_sensitive", "after_sensitive"):
        if key in change:
            if not isinstance(change[key], dict) and change[key] is not False:
                _reject(
                    "malformed_input",
                    address=address,
                    operation_class=f"{key}-envelope",
                )
            try:
                metadata_paths[key] = _unknown_paths(change[key])
            except InvalidPlan:
                _reject(
                    "malformed_input", address=address, operation_class=f"{key}-tree"
                )
    return address, mode, change, metadata_paths


def _validate_resource_drift(value: JSON) -> None:
    if not isinstance(value, list):
        _reject("malformed_input")
    seen: set[str] = set()
    for resource_value in value:
        address, mode, _, _ = _validate_resource_shape(resource_value)
        resource = cast(dict[str, JSON], resource_value)
        if resource.get("provider_name") != EXPECTED_PROVIDER_NAME or mode not in {
            "managed",
            "data",
        }:
            _reject("malformed_input")
        if (mode == "data") != address.startswith("data."):
            _reject("malformed_input")
        if "previous_address" in resource or "deposed" in resource or address in seen:
            _reject("malformed_input")
        seen.add(address)

        if address == shared_packages.CHAT_ROUTES:
            try:
                shared_packages.validate_chat_drift(
                    cast(dict[str, Any], resource), "development"
                )
            except (ValueError, KeyError, TypeError):
                _reject("public_chat_code", address=address)
        if address == "aws_cloudfront_distribution.site":
            change = cast(dict[str, Any], resource["change"])
            if not isinstance(change["before"], dict) or not isinstance(
                change["after"], dict
            ):
                _reject("incomplete_or_drift", address=address)
            before, after = (
                cast(dict[str, Any], change[key]) for key in ("before", "after")
            )
            if before.get("etag") != after.get("etag"):
                try:
                    shared_packages.validate_site_revision_drift(
                        cast(dict[str, Any], resource), "development"
                    )
                except (ValueError, KeyError, TypeError):
                    _reject("incomplete_or_drift", address=address)


def _resource_ok(value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def _validate_relevant_attributes(value: JSON) -> None:
    if not isinstance(value, list):
        _reject("malformed_input")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"resource", "attribute"}:
            _reject("malformed_input")
        if not _is_string(item["resource"]):
            _reject("malformed_input")
        if not isinstance(item["attribute"], list) or any(
            not _is_string(attribute) for attribute in item["attribute"]
        ):
            _reject("malformed_input")


def _validate_permission(
    record: JSON, spec: Mutation, address: str
) -> tuple[str, str, Mapping[str, str]]:
    if not isinstance(record, dict) or set(record) != set(_PERMISSION_KEYS):
        _reject("unknown_manifest_declaration", address=address)
    action, resource, conditions = (
        record.get("action"),
        record.get("resource"),
        record.get("conditions"),
    )
    if not (
        _is_string(action) and _is_string(resource) and isinstance(conditions, dict)
    ):
        _reject(
            "malformed_input",
            address=address,
            action=action if isinstance(action, str) else None,
        )
    if any(
        not _is_string(key) or not isinstance(value, str) or not key or not value
        for key, value in conditions.items()
    ):
        _reject("malformed_input", address=address, action=action)
    return action, resource, cast(dict[str, str], dict(conditions))


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mutation_result(
    plan_record: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
    permissions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ignored_unknown = plan_record.get("ignored_unknown", ())
    return {
        "address": plan_record["address"],
        "action": plan_record["action"],
        "operation_class": plan_record["operation_class"],
        "changed_fields": list(plan_record["changed_fields"]),
        "before": _without_paths(plan_record.get("before"), ignored_unknown),
        "after": _without_paths(plan_record.get("after"), ignored_unknown),
        "manifest": dict(manifest_record),
        "permissions": permissions,
    }


def _parse_plan(
    plan: JSON, package_evidence: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    if (
        not isinstance(plan, dict)
        or not set(plan).issubset(_PLAN_KEYS)
        or not isinstance(plan.get("resource_changes"), list)
    ):
        _reject("malformed_input")
    if plan.get("terraform_version") != EXPECTED_IDENTITY["terraform_version"]:
        _reject("provider_identity_mismatch")
    for key in ("format_version", "terraform_version", "timestamp"):
        if key in plan and not isinstance(plan[key], str):
            _reject("malformed_input")
    expected_flags = {"applyable": True, "complete": True, "errored": False}
    for key in expected_flags:
        if key in plan and not isinstance(plan[key], bool):
            _reject("malformed_input")
    for key in (
        "planned_values",
        "prior_state",
        "configuration",
        "output_changes",
        "variables",
    ):
        if key in plan and not isinstance(plan[key], dict):
            _reject("malformed_input")
    if "checks" in plan and not isinstance(plan["checks"], (dict, list)):
        _reject("malformed_input")
    if "resource_drift" in plan:
        _validate_resource_drift(plan["resource_drift"])
    if "relevant_attributes" in plan:
        _validate_relevant_attributes(plan["relevant_attributes"])
    records: list[dict[str, Any]] = []
    pending_unknowns: list[tuple[str, str, str | None, tuple[str, ...]]] = []
    seen: set[str] = set()
    for resource_value in cast(list[JSON], plan["resource_changes"]):
        resource = cast(dict[str, JSON], resource_value)
        address, mode, change, metadata_paths = _validate_resource_shape(resource)
        spec = CONTRACT.get(address)
        if spec is not None and spec.provider_change_identity:
            runtime_identity_omitted = (
                address == "aws_bedrockagentcore_agent_runtime.tollchat"
                and (
                    change["actions"] == ["update"]
                    or (
                        change["actions"] == ["no-op"]
                        and change["before"] == change["after"]
                        and not any(metadata_paths.values())
                    )
                )
                and "before_identity" not in change
                and "after_identity" not in change
            )
            expected_resource_keys = {
                "address",
                "mode",
                "type",
                "name",
                "provider_name",
                "change",
            }
            if "index" in resource:
                expected_resource_keys.add("index")
            action_for_identity = change["actions"][0]
            identity_sides = (
                ("after_identity",)
                if action_for_identity == "create"
                else ("before_identity",)
                if action_for_identity == "delete"
                else ("before_identity", "after_identity")
            )
            expected_change_keys = {
                "actions",
                "before",
                "after",
                "after_unknown",
                "before_sensitive",
                "after_sensitive",
            }
            if not runtime_identity_omitted:
                expected_change_keys.update(identity_sides)
            if (
                set(resource) != expected_resource_keys
                or set(change) != expected_change_keys
            ):
                _reject("malformed_input", address=address)
            expected_identity = (
                {"arn": None if action_for_identity == "create" else TRACE_FIREHOSE}
                if address == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
                else {
                    "account_id": None,
                    "log_group_name": None,
                    "name": None,
                    "region": None,
                }
                if action_for_identity == "create"
                and address.startswith(
                    'aws_cloudwatch_log_subscription_filter.agentcore_traces["'
                )
                else dict(spec.provider_change_identity)
            )
            if runtime_identity_omitted and any(
                not isinstance(change[side], dict)
                or change[side].get("agent_runtime_name")
                != expected_identity["agent_runtime_name"]
                for side in ("before", "after")
            ):
                _reject("invalid_resource_identity", address=address)
            if not runtime_identity_omitted and any(
                not isinstance(change.get(side), dict)
                or change[side] != expected_identity
                for side in identity_sides
            ):
                _reject("invalid_resource_identity", address=address)
        pending_unknowns.append(
            (
                address,
                change["actions"][0],
                spec.operation_class if spec is not None else None,
                metadata_paths.get("after_unknown", ()),
            )
        )
        if resource.get("provider_name") != EXPECTED_PROVIDER_NAME:
            _reject("provider_identity_mismatch", address=address)
        if address in seen:
            _reject("duplicate_address", address=address)
        seen.add(address)
        if "previous_address" in resource:
            _reject("moved_resource", address=address)
        if "deposed" in resource:
            _reject("deposed_resource", address=address)
        actions = cast(list[str], change["actions"])
        if not actions or any(
            not _is_string(action) or action not in _ACTIONS for action in actions
        ):
            _reject("unsupported_action", address=address)
        if "import" in actions or "refresh" in actions:
            _reject("import_or_refresh", address=address, action=actions[0])
        if len(actions) != 1:
            _reject("replacement", address=address, action="+".join(actions))
        action = actions[0]
        if change.get("replace_paths"):
            _reject("replacement", address=address, action=action)
        for key in ("after_unknown", "before_sensitive", "after_sensitive"):
            if action in {"create", "update"} and key not in change:
                _reject("malformed_input", address=address, action=action)
        if action == "delete" and (
            spec is None or not spec.operation_class.startswith("agentcore-trace-")
        ):
            _reject("delete_not_permitted", address=address, action=action)
        production_candidate = copy.deepcopy(resource)
        if spec is not None and address in TRACE_NOTICE_DIGESTS:
            candidate_change = cast(dict[str, JSON], production_candidate["change"])
            for side in ("before", "after"):
                candidate_side = candidate_change.get(side)
                if isinstance(candidate_side, dict):
                    candidate_side.pop("content", None)
        if _has_production_value(production_candidate):
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
            if _changed_fields(
                change.get("before"),
                change.get("after"),
                ignored=metadata_paths.get("after_unknown", ()),
            ):
                _reject("unsupported_field_delta", address=address, action=action)
            if (
                address in TRACE_NOTICE_DIGESTS
                or address == "aws_bedrockagentcore_agent_runtime.tollchat"
                or (
                    spec is not None
                    and spec.operation_class == "telemetry-log-protection"
                )
            ):
                if spec is None:
                    _reject("unsupported_address", address=address, action=action)
                _validate_s3_identity(
                    change.get("before"), change.get("after"), spec, address, action
                )
                records.append(
                    {
                        "address": address,
                        "action": action,
                        "operation_class": spec.operation_class
                        if spec
                        else "site-object-upload",
                        "changed_fields": (),
                        "before": change.get("before"),
                        "after": change.get("after"),
                        "spec": spec,
                        "ignored_unknown": (),
                        "no_op_evidence": True,
                    }
                )
            continue
        if spec is None:
            _reject("unsupported_address", address=address, action=action)
        before, after = change.get("before"), change.get("after")
        ignored_unknown: tuple[str, ...] = TRACE_READ_ONLY_FIELDS.get(address, ())
        if action == "update" and (before is None or after is None):
            _reject("malformed_input", address=address, action=action)
        if action == "create" and (before is not None or after is None):
            _reject("malformed_input", address=address, action=action)
        if action == "delete" and (before is None or after is not None):
            _reject("malformed_input", address=address, action=action)
        if spec.operation_class in {
            "publisher-inline-policy",
            "report-freshness-alarm",
        }:
            if metadata_paths.get("after_unknown", ()):
                _reject(
                    "unknown_authorization_value",
                    address=address,
                    action=action,
                    operation_class=spec.operation_class,
                )
            if any(
                _metadata_authorized(path, spec)
                for key in ("before_sensitive", "after_sensitive")
                for path in metadata_paths.get(key, ())
            ):
                _reject(
                    "sensitive_authorization_value",
                    address=address,
                    action=action,
                    operation_class=spec.operation_class,
                )
        _validate_s3_identity(
            before,
            after,
            spec,
            address,
            action,
            metadata_paths.get("after_unknown", ()),
        )
        if action == "create":
            unknown_paths = metadata_paths.get("after_unknown", ())
            ignored_unknown += tuple(
                path for path in unknown_paths if not _path_allowed(path, spec.fields)
            )
            changed_set = set(
                _create_fields(
                    cast(dict[str, JSON], after), spec, address, action, ignored_unknown
                )
            )
            for path in unknown_paths:
                parents = [
                    field for field in spec.fields if _path_allowed(path, (field,))
                ]
                if parents:
                    changed_set.add(max(parents, key=len))
            changed = tuple(sorted(changed_set))
        else:
            unknown_paths = metadata_paths.get("after_unknown", ())
            ignored_unknown += tuple(
                path for path in unknown_paths if not _path_allowed(path, spec.fields)
            )
            changed_set = set(
                _changed_fields(before, after, spec.fields, ignored_unknown)
            )
            for path in unknown_paths:
                parents = [
                    field for field in spec.fields if _path_allowed(path, (field,))
                ]
                if parents:
                    changed_set.add(max(parents, key=len))
            changed = tuple(sorted(changed_set))
        if action not in spec.actions:
            _reject(
                "unsupported_action",
                address=address,
                action=action,
                operation_class=spec.operation_class,
            )
        if address.startswith('aws_scheduler_schedule.timed_checks["'):
            _validate_timed_schedule(
                cast(dict[str, JSON], after), address, action, spec.operation_class
            )
        if not changed or any(
            not _path_allowed(field, spec.fields) for field in changed
        ):
            _reject(
                "unsupported_field_delta",
                address=address,
                action=action,
                operation_class=spec.operation_class,
            )
        if spec.operation_class == "lambda-code":
            changed_set = set(changed)
            if changed_set == {"source_code_hash"} and address in {
                "aws_lambda_function.loader",
                "aws_lambda_function.publisher",
            }:
                pass
            elif changed_set != {"filename", "source_code_hash"} and not (
                "source_code_hash" in changed_set
                and bool(changed_set & {"s3_bucket", "s3_key", "s3_object_version"})
            ):
                _reject(
                    "unsupported_field_delta",
                    address=address,
                    action=action,
                    operation_class=spec.operation_class,
                )
        if spec.operation_class == "cost-routing":
            try:
                before = cast(dict[str, JSON], before)
                after = cast(dict[str, JSON], after)
                cost_release.routes(before, after)
                if (
                    not isinstance(before.get("arn"), str)
                    or not cast(str, before["arn"]).startswith(
                        f"arn:aws:cloudfront::{ACCOUNT}:distribution/"
                    )
                    or before["arn"] != after["arn"]
                ):
                    raise ValueError("cost_routing_identity")
            except (ValueError, KeyError, TypeError):
                _reject(
                    "unsupported_field_delta",
                    address=address,
                    action=action,
                    operation_class=spec.operation_class,
                )
        if spec.operation_class == "cost-publication":
            try:
                cost_release.validate(resource, "development", plan, package_evidence)
            except (ValueError, KeyError, TypeError):
                _reject(
                    "unsupported_field_delta",
                    address=address,
                    action=action,
                    operation_class=spec.operation_class,
                )
        if spec.operation_class.startswith("telemetry-"):
            _validate_telemetry_value(after, address, action, spec.operation_class)
        if spec.operation_class == "publisher-inline-policy":
            _validate_publisher_policy(
                before, after, address, action, spec.operation_class
            )
        if spec.operation_class == "agentcore-trace-runtime-policy":
            _validate_trace_runtime_policy(
                before, after, address, action, spec.operation_class
            )
        if spec.operation_class == "report-freshness-alarm":
            _validate_report_freshness_alarm(
                before, after, address, action, spec.operation_class
            )
        if spec.operation_class.startswith("agentcore-trace-") or (
            address == "aws_bedrockagentcore_agent_runtime.tollchat"
            and "environment_variables" in changed
        ):
            _validate_agentcore_trace_value(
                before,
                after,
                address,
                action,
                spec.operation_class,
                metadata_paths.get("after_unknown", ()),
            )
        if any(
            _metadata_authorized(path, spec)
            for key in ("before_sensitive", "after_sensitive")
            for path in metadata_paths.get(key, ())
        ):
            _reject(
                "sensitive_authorization_value",
                address=address,
                action=action,
                operation_class=spec.operation_class,
            )
        records.append(
            {
                "address": address,
                "action": action,
                "operation_class": spec.operation_class,
                "changed_fields": changed,
                "before": before,
                "after": after,
                "spec": spec,
                "ignored_unknown": ignored_unknown,
            }
        )
    _validate_derived_unknowns(plan, pending_unknowns, records)
    if any(
        (address, path) in _DERIVED_UNKNOWN_EDGES
        for address, _, _, paths in pending_unknowns
        for path in paths
    ):
        records.sort(key=lambda record: record["address"])
    metadata_present = bool(plan["resource_changes"]) or any(
        key in plan
        for key in (
            "applyable",
            "complete",
            "errored",
            "resource_drift",
            "relevant_attributes",
        )
    )
    if metadata_present:
        if any(key not in plan for key in expected_flags):
            _reject("malformed_input")
        if plan["complete"] is not True or plan["errored"] is not False:
            _reject("malformed_input")
        if (
            any(not record.get("no_op_evidence") for record in records)
            and plan["applyable"] is not True
        ):
            _reject("malformed_input")
    return records


def _parse_manifest(
    manifest: JSON,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    if not isinstance(manifest, dict) or set(manifest) != set(_MANIFEST_KEYS):
        _reject("unknown_manifest_declaration")
    if (
        manifest.get("schema_version") != 1
        or not isinstance(manifest.get("mutations"), list)
        or not isinstance(manifest.get("permissions"), list)
    ):
        _reject("malformed_input")
    _validate_identity(manifest.get("provider_identity"))
    inputs, packages = manifest.get("deployment_inputs"), manifest.get("packages")
    if not isinstance(inputs, dict) or not isinstance(packages, dict):
        _reject("malformed_input")
    expected_packages = packages_for_inputs(inputs)
    if (
        not inputs
        or list(inputs) != sorted(inputs)
        or any(
            not _is_string(path)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for path, digest in inputs.items()
        )
        or list(packages) != list(expected_packages)
        or any(
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in packages.values()
        )
    ):
        _reject("malformed_input")
    production_inputs = set(inputs) & PRODUCTION_CONTROL_INPUTS
    if production_inputs and production_inputs != set(PRODUCTION_CONTROL_INPUTS):
        _reject("malformed_input")
    mutations: dict[str, dict[str, Any]] = {}
    permissions: dict[str, list[dict[str, Any]]] = {}
    for record in cast(list[JSON], manifest["mutations"]):
        if not isinstance(record, dict) or set(record) != set(_MUTATION_KEYS):
            _reject("unknown_manifest_declaration")
        address = record.get("address")
        if not (
            _is_string(address)
            and _is_string(record.get("action"))
            and _is_string(record.get("operation_class"))
            and isinstance(record.get("changed_fields"), list)
        ):
            _reject("malformed_input")
        if address in TIMED_ADDRESSES and TIMED_CHECKS_MARKER not in inputs:
            _reject("timed_contract_requires_marker", address=address)
        if address in mutations:
            _reject("duplicate_manifest_mutation", address=address)
        if any(
            not _is_string(field)
            for field in cast(list[JSON], record["changed_fields"])
        ):
            _reject("malformed_input", address=address)
        mutations[address] = record
    for raw_record in cast(list[JSON], manifest["permissions"]):
        record = cast(dict[str, JSON], raw_record)
        address = record.get("address") if isinstance(raw_record, dict) else None
        if not _is_string(address):
            _reject("malformed_input")
        if address in TIMED_ADDRESSES and TIMED_CHECKS_MARKER not in inputs:
            _reject("timed_contract_requires_marker", address=address)
        _validate_permission(
            record, CONTRACT.get(address, Mutation((), (), "", ())), address
        )
        permissions.setdefault(address, []).append(record)
    return mutations, permissions


def validate_trace_notices(records: list[dict[str, Any]]) -> None:
    subscription_create = any(
        record["operation_class"] == "agentcore-trace-subscription"
        and record["action"] == "create"
        for record in records
    )
    by_address = {record["address"]: record for record in records}

    def notice_digest(record: dict[str, Any], side: str = "after") -> str:
        value = record.get(side)
        content = (
            cast(dict[str, JSON], value).get("content")
            if isinstance(value, dict)
            else None
        )
        return (
            hashlib.sha256(content.encode()).hexdigest()
            if isinstance(content, str)
            else ""
        )

    new_notices = [
        address
        for address in REDACTED_TRACE_NOTICE_DIGESTS
        if address in by_address
        and notice_digest(by_address[address]) in REDACTED_NOTICE_VERSIONS[address]
    ]
    if new_notices:
        if len(new_notices) != len(REDACTED_TRACE_NOTICE_DIGESTS):
            _reject("unsupported_field_delta", operation_class="site-object-upload")
        runtime = by_address.get("aws_bedrockagentcore_agent_runtime.tollchat")
        if runtime is None:
            _reject("unsupported_field_delta", operation_class="site-object-upload")
        _validate_agentcore_trace_value(
            runtime["before"],
            runtime["after"],
            runtime["address"],
            runtime["action"],
            "agentcore-code",
        )
        env = runtime["after"].get("environment_variables", {})
        if not env.get("TOLLCHAT_TELEMETRY_GUARDRAIL_ID") or not env.get(
            "TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION"
        ):
            _reject("unsupported_field_delta", operation_class="site-object-upload")
        publishing = any(
            notice_digest(by_address[address], "before")
            not in REDACTED_NOTICE_VERSIONS[address]
            for address in new_notices
        )
        if publishing and (
            runtime["action"] != "update"
            or "agent_runtime_artifact.code_configuration.code.s3.version_id"
            not in runtime["changed_fields"]
        ):
            _reject("unsupported_field_delta", operation_class="site-object-upload")
        for endpoint in ("DEFAULT", "preview"):
            address = (
                f'aws_cloudwatch_log_data_protection_policy.agentcore["{endpoint}"]'
            )
            policy = by_address.get(address)
            if policy is None:
                _reject("unsupported_field_delta", address=address)
            _validate_telemetry_value(
                policy["after"], address, policy["action"], "telemetry-log-protection"
            )
    for address, digest in TRACE_NOTICE_DIGESTS.items():
        record = by_address.get(address)
        if record is None:
            if subscription_create:
                _reject(
                    "unsupported_field_delta",
                    address=address,
                    operation_class="site-object-upload",
                )
            continue
        if record["action"] == "no-op" and not subscription_create:
            continue
        content = (
            record.get("after", {}).get("content")
            if isinstance(record.get("after"), dict)
            else None
        )
        before: JSON = record.get("before")
        after: JSON = record.get("after")
        if (
            not isinstance(content, str)
            or hashlib.sha256(content.encode()).hexdigest()
            not in {digest} | REDACTED_NOTICE_VERSIONS[address]
            or not isinstance(after, dict)
            or after.get("source") not in (None, "")
            or after.get("source_hash") not in (None, "")
            or (
                record["action"] == "no-op"
                and (
                    not isinstance(before, dict)
                    or before.get("source") not in (None, "")
                    or before.get("source_hash") not in (None, "")
                )
            )
        ):
            _reject(
                "unsupported_field_delta",
                address=address,
                action=record["action"],
                operation_class="site-object-upload",
            )


def _validate_manifest_entry(
    address: str, declaration: Mapping[str, Any], permissions: list[dict[str, Any]]
) -> None:
    spec = CONTRACT.get(address)
    if spec is None:
        _reject("unsupported_address", address=address)
    action = declaration["action"]
    if (
        action not in spec.actions
        or declaration["operation_class"] != spec.operation_class
    ):
        _reject(
            "manifest_mutation_mismatch",
            address=address,
            action=action,
            operation_class=declaration["operation_class"],
        )
    fields = declaration["changed_fields"]
    if (
        not fields
        or len(set(fields)) != len(fields)
        or any(field not in spec.fields for field in fields)
    ):
        _reject(
            "unsupported_field_delta",
            address=address,
            action=action,
            operation_class=spec.operation_class,
        )
    if spec.operation_class == "lambda-code":
        field_set = set(fields)
        if field_set == {"source_code_hash"} and address in {
            "aws_lambda_function.loader",
            "aws_lambda_function.publisher",
        }:
            pass
        elif field_set not in (
            {"filename", "source_code_hash"},
            {"s3_bucket", "s3_key", "s3_object_version", "source_code_hash"},
        ):
            s3_fields = {"s3_bucket", "s3_key", "s3_object_version"}
            if "source_code_hash" not in fields or not (field_set & s3_fields):
                _reject(
                    "unsupported_field_delta",
                    address=address,
                    action=action,
                    operation_class=spec.operation_class,
                )
    expected = spec.permissions
    if len(permissions) != len(expected):
        _reject(
            "missing_permission",
            address=address,
            action=action,
            operation_class=spec.operation_class,
        )
    used: set[int] = set()
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
    for permission in permissions:
        permission_action, resource, conditions = _validate_permission(
            permission, spec, address
        )
        permission_key = (
            permission_action,
            resource,
            tuple(sorted(conditions.items())),
        )
        if permission_key in seen:
            _reject(
                "duplicate_permission",
                address=address,
                action=action,
                operation_class=spec.operation_class,
            )
        seen.add(permission_key)
        match = next(
            (
                index
                for index, item in enumerate(expected)
                if index not in used
                and permission_action == item.action
                and _resource_ok(resource, item.resources)
                and conditions == dict(item.conditions)
            ),
            None,
        )
        if match is None:
            _reject(
                "invalid_permission",
                address=address,
                action=action,
                operation_class=spec.operation_class,
            )
        used.add(match)
    if len(used) != len(expected):
        _reject(
            "missing_permission",
            address=address,
            action=action,
            operation_class=spec.operation_class,
        )


def validate_plan(
    plan: object,
    manifest: object,
    identity: object = None,
    package_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a plan and release manifest, returning only sanitized data."""
    plan = cast(JSON, plan)
    manifest = cast(JSON, manifest)
    identity = cast(JSON, identity)
    try:
        if _manifest_has_production_value(manifest) or (
            identity is not None and _has_production_value(identity)
        ):
            _reject("production_target")
        _validate_identity(identity)
        if package_evidence is not None:
            shared_packages.check_evidence(package_evidence)
            if package_evidence["environment"] != "development":
                _reject("production_target")
            packages = cast(dict[str, Any], manifest).get("packages", {})
            if any(
                name in packages and packages[name] != row["sha256"]
                for name, row in package_evidence["packages"].items()
            ):
                _reject("shared_package_evidence")
        shared_packages.report(cast(dict[str, Any], plan), "premerge")
        records = _parse_plan(plan, package_evidence)
        validate_trace_notices(records)
        # Runtime/policy no-ops prove notice consistency, not deployment mutations.
        records = [
            record
            for record in records
            if not record.get("no_op_evidence")
            or record["address"] in TRACE_NOTICE_DIGESTS
        ]
        declared, declared_permissions = _parse_manifest(manifest)
        if cast(dict[str, JSON], manifest).get("provider_identity") != identity:
            _reject("provider_identity_mismatch")
        actual_records = [
            record for record in records if not record.get("no_op_evidence")
        ]
        actual_addresses = {record["address"] for record in actual_records}
        if not set(declared_permissions).issubset(set(declared)):
            _reject("manifest_coverage_mismatch")
        if not actual_addresses.issubset(set(declared)):
            _reject("manifest_coverage_mismatch")
        for address, declaration in declared.items():
            _validate_manifest_entry(
                address, declaration, declared_permissions.get(address, [])
            )
        sanitized_records: list[dict[str, Any]] = []
        for record in actual_records:
            address = record["address"]
            declaration = declared[address]
            if (
                declaration["action"] != record["action"]
                or declaration["operation_class"] != record["operation_class"]
                or tuple(sorted(declaration["changed_fields"]))
                != record["changed_fields"]
            ):
                _reject(
                    "manifest_mutation_mismatch",
                    address=address,
                    action=record["action"],
                    operation_class=record["operation_class"],
                )
            actual_permissions = declared_permissions.get(address, [])
            normalized: list[dict[str, Any]] = []
            for permission in actual_permissions:
                action, resource, conditions = _validate_permission(
                    permission, record["spec"], address
                )
                normalized.append(
                    {
                        "address": address,
                        "action": action,
                        "resource": resource,
                        "conditions": conditions,
                    }
                )
            sanitized_records.append(_mutation_result(record, declaration, normalized))
        for resource in cast(dict[str, Any], plan)["resource_changes"]:
            if resource["address"] == shared_packages.CHAT_ROUTES:
                try:
                    shared_packages.validate_chat(resource, "development")
                except (ValueError, KeyError, TypeError):
                    _reject("public_chat_code", address=resource["address"])
            if resource["address"] in shared_packages.RESOURCES:
                try:
                    shared_packages.validate(
                        resource,
                        cast(dict[str, Any], plan),
                        package_evidence,
                        allow_create=resource["address"] == "aws_lambda_function.costs",
                    )
                except (ValueError, KeyError, TypeError):
                    _reject("shared_package_boundary", address=resource["address"])
        fingerprint = _fingerprint(
            {
                "identity": dict(EXPECTED_IDENTITY),
                "mutations": sanitized_records,
            }
        )
        return {
            "status": "accepted",
            "reason_code": "ok",
            "addresses": [record["address"] for record in records],
            "actions": [record["action"] for record in records],
            "operation_classes": [record["operation_class"] for record in records],
            "fingerprint": fingerprint,
        }
    except InvalidPlan as error:
        result: dict[str, Any] = {"status": "rejected", "reason_code": error.reason}
        if error.address in CONTRACT:
            result["address"] = error.address
        if error.action in _ACTIONS:
            result["action"] = error.action
        if error.operation_class in {
            spec.operation_class for spec in CONTRACT.values()
        }:
            result["operation_class"] = error.operation_class
        return result
    except Exception:
        return {"status": "rejected", "reason_code": "malformed_input"}


def validate(
    plan: JSON, manifest: JSON, identity: JSON | None = None
) -> dict[str, Any]:
    return validate_plan(plan, manifest, identity)


def _load_json(path: str) -> JSON:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("plan")
    parser.add_argument("manifest")
    parser.add_argument("--identity", required=True)
    parser.add_argument("--package-evidence")
    args = parser.parse_args(argv)
    try:
        result = validate_plan(
            _load_json(args.plan),
            _load_json(args.manifest),
            _load_json(args.identity),
            cast(dict[str, Any], _load_json(args.package_evidence))
            if args.package_evidence
            else None,
        )
        if result["status"] == "accepted" and args.package_evidence is None:
            result = {"status": "rejected", "reason_code": "shared_package_evidence"}
    except Exception:
        result = {"status": "rejected", "reason_code": "malformed_input"}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())

# Explicit exports for the offline contract tests.
__all__ = ("_parse_plan",)

import base64
import gzip
import json
import re
from typing import Any, cast

import pytest

from tests.infrastructure_support import (
    DEPLOYMENT,
    FOUNDATION_ROOT,
    MEASUREMENT_INFRA,
    TIMED_CHECKS_TF,
    V2_ROOT,
    assert_assignment,
    hcl_expression,
    hcl_named_blocks,
    hcl_scalar,
    terraform_block,
)


def test_blue_green_monitors_both_retained_proxies_without_routing_changes() -> None:
    agentcore = (V2_ROOT / "infra/agentcore.tf").read_text()
    bootstrap = (V2_ROOT / "infra/release-bootstrap.tf").read_text()
    for kind, name in [
        ("aws_cloudwatch_log_metric_filter", "proxy_failure"),
        ("aws_cloudwatch_metric_alarm", "tollchat_proxy_errors"),
        ("aws_cloudwatch_metric_alarm", "tollchat_proxy_failures"),
        ("aws_cloudwatch_metric_alarm", "tollchat_proxy_latency"),
    ]:
        block = terraform_block(agentcore, f'resource "{kind}" "{name}"')
        assert_assignment(block, "for_each", "var.release_slots")
        assert "local.slot_suffix[each.key]" in block
        assert "var.active_slot" not in block
        assert f"from = {kind}.{name}" in bootstrap
        assert f'to   = {kind}.{name}["blue"]' in bootstrap
        if name == "proxy_failure":
            assert_assignment(
                block,
                "log_group_name",
                "aws_cloudwatch_log_group.tollchat_proxy[each.key].name",
            )
        elif name != "tollchat_proxy_failures":
            assert_assignment(
                block,
                "dimensions",
                "{ FunctionName = aws_lambda_function.tollchat_proxy[each.key].function_name }",
            )
    policy = terraform_block(
        (FOUNDATION_ROOT / "blue-green.tf").read_text(),
        'resource "aws_iam_role_policy" "development_blue_green"',
    )
    assert '"lambda:GetFunctionCodeSigningConfig"' in policy
    assert '"cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource"' in policy
    assert 'for metric in ["errors", "failures", "latency"]' in policy
    assert "alarm:tollchat-v2-chat-proxy-${metric}-dev-green" in policy


def test_agentcore_trace_archive_has_shared_privacy_notice_and_retention() -> None:
    from scripts.verify_release_bundle import FIXED_PATHS

    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    for value in (
        'resource "aws_glue_catalog_table" "agentcore_traces"',
        'resource "aws_athena_named_query" "agentcore_trace_summary"',
        "agentcore-traces/",
    ):
        assert value in MEASUREMENT_INFRA
    lifecycle = terraform_block(
        MEASUREMENT_INFRA,
        'resource "aws_s3_bucket_lifecycle_configuration" "agent_measurement"',
    )
    assert lifecycle.count("agentcore-traces/") == 1
    assert 'for_each = ["agentcore-traces"]' in lifecycle
    assert "expiration { days = 7 }" in lifecycle
    for filename in ("dev_chat.html", "faq.html", "privacy.txt"):
        assert "v2/agent/" + filename in FIXED_PATHS
        notice = (V2_ROOT / "agent" / filename).read_text()
        assert "make an effort to protect" in notice
        assert "can miss" in notice

    proxy = agentcore.split(
        'resource "aws_lambda_function" "tollchat_proxy"', maxsplit=1
    )[1].split('resource "aws_api_gateway_rest_api"', maxsplit=1)[0]
    assert "ignore_changes = [reserved_concurrent_executions]" not in proxy
    assert "aws_iam_role_policy.tollchat_proxy" in proxy

    assert "put-function-concurrency" not in DEPLOYMENT


def test_agentcore_trace_envelope_becomes_raw_ndjson_and_projects_query_fields() -> (
    None
):
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    firehose = terraform_block(
        agentcore, 'resource "aws_kinesis_firehose_delivery_stream" "agentcore_traces"'
    )
    processor_blocks = hcl_named_blocks(firehose, "processors")
    processors = [hcl_scalar(block, "type") for block in processor_blocks]
    assert processors == [
        "Decompression",
        "CloudWatchLogProcessing",
        "AppendDelimiterToRecord",
    ]
    extraction_parameters = {
        hcl_scalar(block, "parameter_name"): hcl_scalar(block, "parameter_value")
        for block in hcl_named_blocks(processor_blocks[1], "parameters")
    }
    assert extraction_parameters == {"DataMessageExtraction": "true"}
    assert "enabled = true" in hcl_named_blocks(firehose, "processing_configuration")[0]
    runtime_policy = terraform_block(
        agentcore, 'resource "aws_iam_role_policy" "tollchat_runtime"'
    )
    assert 'Action   = "logs:PutResourcePolicy"' in runtime_policy
    assert (
        'Resource = [for log in values(local.runtime_logs) : "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${var.release_slots[log.slot].runtime_id}-${log.endpoint}"]'
        in runtime_policy
    )
    assert (
        'Action   = "logs:PutResourcePolicy"\n        Resource = "*"'
        not in runtime_policy
    )
    subscription = terraform_block(
        agentcore,
        'resource "aws_cloudwatch_log_subscription_filter" "agentcore_traces"',
    )
    filter_pattern = hcl_scalar(subscription, "filter_pattern")
    assert (
        filter_pattern == '{ $.traceId = "*" && $.spanId = "*" && $.durationNano >= 0 }'
    )
    table = terraform_block(
        MEASUREMENT_INFRA, 'resource "aws_glue_catalog_table" "agentcore_traces"'
    )
    descriptor = hcl_named_blocks(table, "storage_descriptor")[0]
    assert [
        hcl_scalar(column, "name") for column in hcl_named_blocks(descriptor, "columns")
    ] == ["raw_json"]
    assert [
        hcl_scalar(column, "type") for column in hcl_named_blocks(descriptor, "columns")
    ] == ["string"]
    serde = hcl_named_blocks(descriptor, "ser_de_info")[0]
    assert (
        hcl_scalar(serde, "serialization_library")
        == "org.apache.hadoop.hive.serde2.RegexSerDe"
    )
    serde_pattern = re.search(r'"input\.regex"\s*=\s*"([^"]+)"', serde)
    assert serde_pattern and serde_pattern.group(1) == "^(.*)$"
    query = terraform_block(
        MEASUREMENT_INFRA, 'resource "aws_athena_named_query" "agentcore_trace_summary"'
    )
    sql = hcl_scalar(query, "query")
    assert (
        sql
        == "SELECT json_extract_scalar(raw_json, '$.traceId') AS traceId, json_extract_scalar(raw_json, '$.spanId') AS spanId, json_extract_scalar(raw_json, '$.name') AS name, cast(json_extract_scalar(raw_json, '$.durationNano') AS bigint) AS durationNano, json_extract_scalar(raw_json, '$.status.code') AS status_code, json_extract(raw_json, '$.attributes') AS attributes FROM agentcore_traces LIMIT 100"
    )

    filter_contract = re.fullmatch(
        r'\{ \$\.([A-Za-z][A-Za-z0-9]*) = "\*" && \$\.([A-Za-z][A-Za-z0-9]*) = "\*" && \$\.([A-Za-z][A-Za-z0-9]*) >= ([0-9]+) \}',
        filter_pattern,
    )
    assert filter_contract
    string_fields = filter_contract.group(1, 2)
    number_field, minimum = filter_contract.group(3), int(filter_contract.group(4))
    scalar_paths = re.findall(r"json_extract_scalar\(raw_json, '\$\.([^']+)'\)", sql)
    structured_paths = re.findall(r"json_extract\(raw_json, '\$\.([^']+)'\)", sql)
    assert scalar_paths == ["traceId", "spanId", "name", "durationNano", "status.code"]
    assert structured_paths == ["attributes"]

    def matches_filter(record: object) -> bool:
        if not isinstance(record, dict):
            return False
        typed_record = cast(dict[str, object], record)
        number = typed_record.get(number_field)
        return (
            all(isinstance(typed_record.get(field), str) for field in string_fields)
            and isinstance(number, int)
            and number >= minimum
        )

    serde_regex = serde_pattern.group(1)

    def native_rows(encoded: str) -> list[bytes]:
        envelope = json.loads(gzip.decompress(base64.b64decode(encoded)))
        assert envelope["messageType"] == "DATA_MESSAGE"
        assert processors == [
            "Decompression",
            "CloudWatchLogProcessing",
            "AppendDelimiterToRecord",
        ]
        assert extraction_parameters == {"DataMessageExtraction": "true"}
        delivered = bytearray()
        for event in envelope["logEvents"]:
            raw = event["message"].encode()
            assert b"\n" not in raw
            record = json.loads(raw)  # CloudWatchLogProcessing's data extraction.
            if matches_filter(record):
                delivered.extend(raw)
                delivered.extend(
                    b"\n"
                )  # AppendDelimiterToRecord: exactly one boundary.
        assert delivered.count(b"\n") == sum(
            matches_filter(json.loads(event["message"]))
            for event in envelope["logEvents"]
        )
        rows = [bytes(row) for row in delivered.splitlines()]
        regex = re.compile(serde_regex.encode())
        assert all(
            (match := regex.fullmatch(row)) is not None and match.group(1) == row
            for row in rows
        )
        return rows

    success = {
        "traceId": "0123456789abcdef0123456789abcdef",
        "spanId": "0123456789abcdef",
        "name": "execute_tool",
        "durationNano": 1,
        "status": {"code": "OK"},
        "attributes": {
            "gen_ai.operation.name": "execute_tool",
            "nested": {"steps": [1, 2]},
        },
        "events": [{"attributes": {"gen_ai.prompt": "raw prompt"}}],
    }
    error = success | {"status": {"code": "ERROR"}}
    ordinary_log = {"message": "runtime started"}
    control_span = {"traceId": success["traceId"], "spanId": success["spanId"]}
    assert matches_filter(success)
    assert matches_filter(error)
    assert not matches_filter(ordinary_log)
    assert not matches_filter(control_span)
    assert not matches_filter(
        {"traceId": success["traceId"], "spanId": success["spanId"], "durationNano": -1}
    )
    assert not matches_filter("not-json")
    success_line, error_line = (
        json.dumps(record, separators=(",", ":")).encode()
        for record in (success, error)
    )
    envelope = {
        "messageType": "DATA_MESSAGE",
        "owner": "903859731897",
        "logGroup": "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
        "logEvents": [
            {"id": "success", "timestamp": 1, "message": success_line.decode()},
            {"id": "error", "timestamp": 2, "message": error_line.decode()},
            {"id": "ordinary", "timestamp": 3, "message": json.dumps(ordinary_log)},
            {"id": "control", "timestamp": 4, "message": json.dumps(control_span)},
            {
                "id": "negative",
                "timestamp": 5,
                "message": json.dumps(
                    {
                        "traceId": success["traceId"],
                        "spanId": success["spanId"],
                        "durationNano": -1,
                    }
                ),
            },
        ],
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(envelope).encode())).decode()
    rows = native_rows(encoded)
    assert rows == [success_line, error_line]
    parsed_rows = [json.loads(row) for row in rows]
    assert parsed_rows == [success, error]

    def extract(row: dict[str, Any], path: str) -> object:
        value: Any = row
        for part in path.split("."):
            value = value[part]
        return cast(object, value)

    projected = [
        tuple(extract(row, path) for path in (*scalar_paths, *structured_paths))
        for row in parsed_rows
    ]
    assert projected == [
        (
            "0123456789abcdef0123456789abcdef",
            "0123456789abcdef",
            "execute_tool",
            1,
            "OK",
            {"gen_ai.operation.name": "execute_tool", "nested": {"steps": [1, 2]}},
        ),
        (
            "0123456789abcdef0123456789abcdef",
            "0123456789abcdef",
            "execute_tool",
            1,
            "ERROR",
            {"gen_ai.operation.name": "execute_tool", "nested": {"steps": [1, 2]}},
        ),
    ]
    assert all(
        json.dumps(row["attributes"], separators=(",", ":"))
        == '{"gen_ai.operation.name":"execute_tool","nested":{"steps":[1,2]}}'
        for row in parsed_rows
    )
    with pytest.raises((AssertionError, KeyError, json.JSONDecodeError)):
        native_rows(
            base64.b64encode(
                gzip.compress(
                    json.dumps({**envelope, "messageType": "CONTROL_MESSAGE"}).encode()
                )
            ).decode()
        )
    with pytest.raises((AssertionError, KeyError, json.JSONDecodeError)):
        native_rows(
            base64.b64encode(
                gzip.compress(
                    json.dumps(
                        {**envelope, "logEvents": [{"message": "not-json"}]}
                    ).encode()
                )
            ).decode()
        )
    with pytest.raises(AssertionError):
        native_rows(
            base64.b64encode(
                gzip.compress(
                    json.dumps(
                        {
                            **envelope,
                            "logEvents": [{"message": '{\n  "traceId":"pretty"\n}'}],
                        }
                    ).encode()
                )
            ).decode()
        )


def test_agentcore_trace_protection_applies_to_both_environments() -> None:
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    protection = (V2_ROOT / "infra" / "trace_redaction.tf").read_text()
    runtime = terraform_block(
        agentcore, 'resource "aws_bedrockagentcore_agent_runtime" "tollchat"'
    )
    assert "merge(each.value.runtime_environment" in hcl_expression(
        runtime, "environment_variables"
    )
    assert "local.required_runtime_environment" in runtime
    for name in (
        "UNIFIED_TRACES_DESTINATION_ENABLED",
        "TOLLCHAT_TELEMETRY_GUARDRAIL_ID",
        "TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION",
    ):
        assert name in agentcore
    subscriptions = terraform_block(
        agentcore,
        'resource "aws_cloudwatch_log_subscription_filter" "agentcore_traces"',
    )
    assert re.search(r"for_each\s*= local.runtime_logs", subscriptions)
    assert re.search(
        r"for_each\s*= aws_cloudwatch_log_group.agentcore_runtime", protection
    )
    for resource in (
        'aws_glue_catalog_table" "agentcore_traces',
        'aws_athena_named_query" "agentcore_trace_summary',
    ):
        assert re.search(
            r"count\s*= 1", terraform_block(MEASUREMENT_INFRA, f'resource "{resource}"')
        )
    foundation = (FOUNDATION_ROOT / "telemetry.tf").read_text()
    assert 'var.environment == "production" ? 1 : 0' in foundation
    assert "local.production_telemetry_archive_statements" in foundation
    assert "logs:Unmask" not in foundation


def test_agent_measurement_retains_historical_metadata_without_active_sink() -> None:
    measurement_path = V2_ROOT / "infra" / "agent_measurement.tf"
    assert measurement_path.exists()
    measurement = measurement_path.read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    assert 'name     = "agent-report-bot-control"' not in site
    assert 'name     = "agent-route-report"' not in site
    assert 'name     = "allow-static-site"' in site
    assert (
        "priority = 7"
        in site.split('name     = "allow-static-site"', maxsplit=1)[1].split(
            'name     = "block-oversized-api-body"', maxsplit=1
        )[0]
    )

    assert 'toset(["cookie", "authorization", "referer", "aws-cf-cd-tollchat"])' in site
    assert 'field_type = "QUERY_STRING"' in site
    assert site.count('action                     = "SUBSTITUTION"') >= 2

    assert (
        'agent_measurement_bucket   = "aws-waf-logs-tollchat-agent-reports-'
        in measurement
    )
    assert (
        'resource "aws_s3_bucket_public_access_block" "agent_measurement"'
        in measurement
    )
    assert 'resource "aws_kms_key" "agent_measurement"' in measurement
    assert "enable_key_rotation     = true" in measurement
    assert 'sse_algorithm     = "aws:kms"' in measurement
    assert "kms_master_key_id = aws_kms_key.agent_measurement.arn" in measurement
    assert "bucket_key_enabled = true" in measurement
    assert 'encryption_option = "SSE_KMS"' in measurement
    assert (
        'resource "aws_wafv2_web_acl_logging_configuration" "agent_reports"'
        not in measurement
    )
    assert measurement.count("days = 7") >= 2
    assert "enforce_workgroup_configuration    = true" in measurement
    assert "bytes_scanned_cutoff_per_query     = 1073741824" in measurement
    assert "/WAFLogs/cloudfront/${local.agent_measurement_acl}/" in measurement
    assert "/WAFLogs/us-east-1/tollchat-v2-public-chat/" not in measurement
    assert 'resource "aws_cloudwatch_log_group" "agent_usage_rollup"' in measurement
    assert "Historical rollup execution logs remain managed" in measurement
    assert 'resource "aws_s3_object" "agent_registry"' in measurement
    assert "ignore_changes = [source, source_hash]" in measurement
    assert "usage.json" not in measurement


def test_agent_measurement_keeps_cloudflare_dns_only() -> None:
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    for resource in ('cloudflare_dns_record" "apex', 'cloudflare_dns_record" "www'):
        block = site.split(f'resource "{resource}"', maxsplit=1)[1].split(
            "\n}", maxsplit=1
        )[0]
        assert "proxied = false" in block
    assert 'resource "cloudflare_bot_management"' not in site


def test_agent_measurement_privacy_notice_precedes_logging() -> None:
    privacy = (V2_ROOT / "agent" / "privacy.txt").read_text()
    for text in (
        "seven days",
        "IP address",
        "full user-agent",
        "AWS WAF",
        "cookie values",
        "authorization headers",
        "New route-analytics collection and aggregate publication have stopped",
        "security controls remain separate",
    ):
        assert text in privacy
    measurement = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
    assert (
        'resource "aws_wafv2_web_acl_logging_configuration" "agent_reports"'
        not in measurement
    )
    assert "aws_s3_bucket_lifecycle_configuration" in measurement


def test_agent_registry_and_rollup_outputs_are_retained_inert_metadata() -> None:
    registry = [
        json.loads(line)
        for line in (V2_ROOT / "analytics" / "agent_registry.ndjson")
        .read_text()
        .splitlines()
    ]
    tokens = [entry["user_agent_token"].casefold() for entry in registry]
    assert len(tokens) == len(set(tokens))
    assert {entry["agent_mode"] for entry in registry} == {
        "search_crawler",
        "user_triggered_agent",
        "training_crawler",
    }
    assert all(entry["documentation_url"].startswith("https://") for entry in registry)

    measurement = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
    assert 'route_keys     = "array<string>"' in measurement
    assert "ignore_changes = [source, source_hash]" in measurement
    for name in (
        "handler.py",
        "coverage.sql",
        "complete.sql",
        "latest_view.sql",
        "rollup.sql",
    ):
        assert not (V2_ROOT / "lambdas" / "agent_usage_rollup" / name).exists()


def test_agent_referrer_rules_match_only_exact_url_authorities() -> None:
    site = (V2_ROOT / "infra" / "site.tf").read_text()
    assert "assistant_referrers" not in site
    assert 'dynamic "rule" {' not in site
    assert 'name     = "agent-route-report"' not in site


def test_retained_usage_snapshot_and_log_have_no_current_writer() -> None:
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    site = (V2_ROOT / "infra" / "site.tf").read_text()

    assert 'data "archive_file" "usage_publisher"' not in site
    assert 'data "aws_iam_policy_document" "usage_publisher"' not in site
    assert 'resource "aws_lambda_function" "usage_publisher"' not in site
    assert 'resource "aws_iam_role" "usage_publisher"' not in site
    assert 'resource "aws_iam_role_policy" "usage_publisher"' not in site
    assert 'resource "aws_cloudwatch_event_rule" "usage_publisher"' not in site
    assert 'resource "aws_cloudwatch_event_target" "usage_publisher"' not in site
    assert 'resource "aws_lambda_permission" "usage_publisher"' not in site
    assert 'resource "aws_cloudwatch_metric_alarm" "usage_publisher_errors"' not in site
    assert (
        'resource "aws_cloudwatch_metric_alarm" "usage_publisher_failed_invocations"'
        not in site
    )
    assert 'resource "aws_cloudwatch_log_group" "usage_publisher"' in site
    assert 'key           = "usage.json"' in site

    proxy_policy = terraform_block(
        agentcore, 'resource "aws_iam_role_policy" "tollchat_proxy"'
    )
    assert '"dynamodb:TransactWriteItems"' not in proxy_policy


def test_usage_rollout_has_no_retired_foundation_step() -> None:
    pre_bootstrap_runbook = DEPLOYMENT.split(
        "### Development bootstrap/import boundary", maxsplit=1
    )[0]
    assert "usage-permissions.tfplan" not in DEPLOYMENT
    assert "usage-prerequisites.tfplan" not in DEPLOYMENT
    assert "Historical `usage.json` is retained" in DEPLOYMENT
    assert "iam get-role-policy" not in pre_bootstrap_runbook
    assert "dynamodb:TransactWriteItems" not in DEPLOYMENT
    assert "tollchat_usage_optout=1" not in DEPLOYMENT
    assert "--consistent-read" not in DEPLOYMENT


def test_metrics_aware_rollback_preserves_the_aggregate() -> None:
    rollback = DEPLOYMENT.split("## Rollback", maxsplit=1)[1]
    assert "scheduler get-schedule" in rollback
    assert "scheduler update-schedule" in rollback
    assert "--state DISABLED" in rollback
    assert "--state ENABLED" in rollback
    assert rollback.count("trap 'rm -f --") == 2
    assert rollback.count("SCHEDULE_GROUP=") >= 2
    assert 'SCHEDULE_GROUP="default"' not in rollback
    assert "toll-v2-committed-i95-loads" not in rollback
    assert "toll-v2-report-watchdog" not in rollback
    assert "historical" in rollback.lower()
    assert "usage#all" not in rollback
    assert "manual restore may change only application routing" in rollback
    assert "do not roll back automatically" in rollback


def test_eval_dashboard_is_configured_in_both_environments() -> None:
    assert_assignment(
        TIMED_CHECKS_TF,
        "eval_db_user",
        'local.is_production ? "eval_writer" : "eval_writer_development"',
    )
    policy = terraform_block(
        TIMED_CHECKS_TF, 'data "aws_iam_policy_document" "timed_checks_lambda"'
    )
    for sid, actions, resources in (
        (
            "ConnectEvaluationHistory",
            '["rds-db:connect"]',
            '["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.eval_db_user}"]',
        ),
        (
            "PublishEvaluationSnapshot",
            '["s3:PutObject"]',
            '["${aws_s3_bucket.site.arn}/evals.json"]',
        ),
        (
            "EncryptEvaluationSnapshot",
            '["kms:GenerateDataKey", "kms:Decrypt"]',
            "[aws_kms_key.site.arn]",
        ),
    ):
        statement = next(
            block for block in policy.split("statement {")[1:] if f'"{sid}"' in block
        )
        assert_assignment(statement, "actions", actions)
        assert_assignment(statement, "resources", resources)
    assert 'dynamic "statement"' not in policy
    function = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_lambda_function" "timed_checks"'
    )
    # Both variables must be in the unconditional map, before the alerts merge.
    base_environment = function.split("variables = merge({", 1)[1].split("},", 1)[0]
    assert_assignment(
        base_environment, "EVAL_DASHBOARD_BUCKET", "aws_s3_bucket.site.id"
    )
    assert_assignment(base_environment, "EVAL_DB_USER", "local.eval_db_user")

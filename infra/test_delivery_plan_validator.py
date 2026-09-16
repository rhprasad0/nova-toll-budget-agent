import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from infra.delivery_plan_validator import (
    CONTRACT,
    EXPECTED_IDENTITY,
    EXPECTED_PROVIDER_NAME,
    LAMBDA_FUNCTION_NAMES,
    PRODUCTION_CONTROL_INPUTS,
    TRACE_FILTER,
    TRACE_FIREHOSE,
    TRACE_FIREHOSE_ROLE,
    TRACE_KMS_KEY,
    TRACE_LOGS_ROLE,
    TRACE_NOTICE_DIGESTS,
    TRACE_PREFIX,
    TRACE_QUERY,
    TRACE_TAGS,
    _timed_schedule_plan_value,
    validate_plan as _validate_plan,
)


LAMBDA_ADDRESS = "aws_lambda_function.loader"
HASH = "0" * 64


def _trace_notice_contents():
    # Freeze published notices so page edits cannot rewrite legacy test inputs.
    import gzip
    values = json.loads(gzip.decompress((Path(__file__).parent / "fixtures/telemetry-notices.json.gz").read_bytes()))
    for name, content in values["legacy"].items():
        assert hashlib.sha256(content.encode()).hexdigest() == TRACE_NOTICE_DIGESTS[f"aws_s3_object.{name}"]
    return values["legacy"]


def _telemetry_value(address):
    spec = CONTRACT[address]
    value = dict(spec.create_identity)
    if spec.operation_class == "telemetry-log-protection":
        value["policy_document"] = (Path(__file__).resolve().parents[1] / "v2/infra/telemetry-log-policy.tf").read_text().split("<<-POLICY\n", 1)[1].split("\nPOLICY", 1)[0]
    elif spec.operation_class == "telemetry-failure-metric":
        value.update(pattern="?telemetry_redaction_failed ?telemetry_redaction_omitted ?telemetry_export_failed", metric_transformation=[{"name": "RedactionFailures", "namespace": "TollChat/Telemetry", "value": "1"}])
    else:
        pii = 'telemetry_pii[' in address
        endpoint = "DEFAULT" if '"DEFAULT"' in address else "preview"
        value.update(namespace="AWS/Logs" if pii else "TollChat/Telemetry", metric_name="LogEventsWithFindings" if pii else "RedactionFailures", dimensions={"LogGroupName": f"/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-{endpoint}"} if pii else {}, statistic="Sum", period=300, evaluation_periods=1, comparison_operator="GreaterThanThreshold", threshold=0, treat_missing_data="notBreaching", alarm_actions=[])
    return value


def validate_plan(plan, manifest, identity=None):
    return _validate_plan(plan, manifest, dict(EXPECTED_IDENTITY) if identity is None else identity)


def manifest_header(*, timed=False):
    inputs = {"v2/infra/main.tf": HASH}
    if timed:
        inputs["v2/scripts/build_timed_checks_zip.sh"] = HASH
    return {
        "schema_version": 1,
        "provider_identity": dict(EXPECTED_IDENTITY),
        "deployment_inputs": inputs,
        "packages": {
            name: HASH
            for name in (
                "agentcore.zip",
                "chat-proxy.zip",
                "loader.zip",
                "publisher.zip",
                "timed-checks.zip",
            )
            if timed or name != "timed-checks.zip"
        },
    }


def _resource_change(
    address,
    action,
    before,
    after,
    *,
    after_unknown=None,
    before_sensitive=None,
    after_sensitive=None,
    before_identity=None,
    after_identity=None,
):
    base, _, index_text = address.partition("[")
    resource_type, name = base.split(".")
    record = {
        "address": address,
        "mode": "managed",
        "type": resource_type,
        "name": name,
        "provider_name": EXPECTED_PROVIDER_NAME,
        "change": {
            "actions": [action],
            "before": before,
            "after": after,
            "after_unknown": {} if after_unknown is None else after_unknown,
            "before_sensitive": {} if before_sensitive is None else before_sensitive,
            "after_sensitive": {} if after_sensitive is None else after_sensitive,
            "before_identity": before_identity,
            "after_identity": after_identity,
        },
    }
    if index_text:
        record["index"] = json.loads("[" + index_text[:-1] + "]")[0]
    identities = {
        "aws_iam_role_policy.publisher": {"account_id": "903859731897", "name": "toll-v2-report-publisher-dev", "role": "toll-v2-report-publisher-dev"},
        "aws_cloudwatch_metric_alarm.report_generation_freshness": {"account_id": "903859731897", "alarm_name": "toll-v2-report-generation-freshness-dev", "region": "us-east-1"},
    }
    if address in identities:
        record["change"]["before_identity"] = copy.deepcopy(identities[address])
        record["change"]["after_identity"] = copy.deepcopy(identities[address])
    spec = CONTRACT.get(address)
    if spec is not None and spec.provider_change_identity:
        expected = dict(spec.provider_change_identity)
        if action != "create":
            record["change"]["before_identity"] = copy.deepcopy(expected)
        if action != "delete":
            record["change"]["after_identity"] = copy.deepcopy(expected)
    return record


def _plan(resource_changes, **metadata):
    plan = {
        "terraform_version": "1.15.8",
        "applyable": True,
        "complete": True,
        "errored": False,
        "resource_changes": resource_changes,
    }
    plan.update(metadata)
    return plan


def lambda_plan(**changes):
    before = {"function_name": LAMBDA_FUNCTION_NAMES["loader"], "filename": "old.zip", "source_code_hash": "old", "s3_bucket": None, "s3_key": None, "s3_object_version": None}
    after = {"function_name": LAMBDA_FUNCTION_NAMES["loader"], "filename": "new.zip", "source_code_hash": "new", "s3_bucket": None, "s3_key": None, "s3_object_version": None}
    after.update(changes)
    return _plan([_resource_change(LAMBDA_ADDRESS, "update", before, after)])


def lambda_manifest(changed_fields=("filename", "source_code_hash")):
    return {
        **manifest_header(),
        "mutations": [
            {
            "address": LAMBDA_ADDRESS,
            "action": "update",
            "operation_class": "lambda-code",
            "changed_fields": list(changed_fields),
            }
        ],
        "permissions": [
            {
            "address": LAMBDA_ADDRESS,
            "action": "lambda:UpdateFunctionCode",
            "resource": "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-pricing-loader-dev",
            "conditions": {},
            }
        ],
    }


PUBLISHER_ADDRESS = "aws_iam_role_policy.publisher"
PUBLISHER_ROLE = "toll-v2-report-publisher-dev"
ALARM_ADDRESS = "aws_cloudwatch_metric_alarm.report_generation_freshness"
ALARM_NAME = "toll-v2-report-generation-freshness-dev"
SITE_BUCKET = "arn:aws:s3:::tollchat-site-903859731897-dev"
SITE_KEY = "arn:aws:kms:us-east-1:903859731897:key/3bc78b60-9cbe-4abd-9744-8772c78d8379"

PUBLISHER_AND_ALARM_FIXTURE = br'''[{"address":"aws_cloudwatch_metric_alarm.report_generation_freshness","change":{"actions":["update"],"after":{"actions_enabled":true,"alarm_actions":[],"alarm_description":"No complete I-95/I-495 and I-66 report generation in the trailing seven-day sliding window.","alarm_name":"toll-v2-report-generation-freshness-dev","arn":"arn:aws:cloudwatch:us-east-1:903859731897:alarm:toll-v2-report-generation-freshness-dev","comparison_operator":"LessThanThreshold","datapoints_to_alarm":7,"dimensions":{"Environment":"development","facility_scope":"both"},"evaluate_low_sample_count_percentiles":null,"evaluation_criteria":[],"evaluation_interval":null,"evaluation_periods":7,"extended_statistic":null,"id":"toll-v2-report-generation-freshness-dev","insufficient_data_actions":[],"metric_name":"V2ReportGenerationSuccess","metric_query":[],"namespace":"NovaToll","ok_actions":[],"period":86400,"region":"us-east-1","statistic":"Sum","tags":{},"tags_all":{},"threshold":1,"threshold_metric_id":null,"treat_missing_data":"breaching","unit":null},"after_identity":{"account_id":"903859731897","alarm_name":"toll-v2-report-generation-freshness-dev","region":"us-east-1"},"after_sensitive":{"alarm_actions":[],"dimensions":{},"evaluation_criteria":[],"insufficient_data_actions":[],"metric_query":[],"ok_actions":[],"tags":{},"tags_all":{}},"after_unknown":{},"before":{"actions_enabled":true,"alarm_actions":[],"alarm_description":"No complete I-95/I-495 report generation in the trailing seven-day sliding window.","alarm_name":"toll-v2-report-generation-freshness-dev","arn":"arn:aws:cloudwatch:us-east-1:903859731897:alarm:toll-v2-report-generation-freshness-dev","comparison_operator":"LessThanThreshold","datapoints_to_alarm":7,"dimensions":{"Environment":"development","facility":"i95_i495"},"evaluate_low_sample_count_percentiles":null,"evaluation_criteria":[],"evaluation_interval":null,"evaluation_periods":7,"extended_statistic":null,"id":"toll-v2-report-generation-freshness-dev","insufficient_data_actions":[],"metric_name":"V2ReportGenerationSuccess","metric_query":[],"namespace":"NovaToll","ok_actions":[],"period":86400,"region":"us-east-1","statistic":"Sum","tags":{},"tags_all":{},"threshold":1,"threshold_metric_id":null,"treat_missing_data":"breaching","unit":null},"before_identity":{"account_id":"903859731897","alarm_name":"toll-v2-report-generation-freshness-dev","region":"us-east-1"},"before_sensitive":{"alarm_actions":[],"dimensions":{},"evaluation_criteria":[],"insufficient_data_actions":[],"metric_query":[],"ok_actions":[],"tags":{},"tags_all":{}}},"mode":"managed","name":"report_generation_freshness","provider_name":"registry.terraform.io/hashicorp/aws","type":"aws_cloudwatch_metric_alarm"},{"address":"aws_iam_role_policy.publisher","change":{"actions":["update"],"after":{"id":"toll-v2-report-publisher-dev:toll-v2-report-publisher-dev","name":"toll-v2-report-publisher-dev","name_prefix":null,"policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Action\":[\"rds-db:connect\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:rds-db:us-east-1:903859731897:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/report_publisher_development\",\"arn:aws:rds-db:us-east-1:903859731897:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/pricing_reader_development\"],\"Sid\":\"ConnectRdsIam\"},{\"Action\":[\"sqs:SendMessage\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:sqs:us-east-1:903859731897:toll-v2-report-publisher-invoke-failure-dev\"],\"Sid\":\"SendInvokeFailure\"},{\"Action\":[\"s3:ListBucket\"],\"Condition\":{\"StringEquals\":{\"s3:prefix\":[\"tolls/i95-i495/\",\"tolls/i66/\"]}},\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:s3:::tollchat-site-903859731897-dev\"],\"Sid\":\"ListPublicReports\"},{\"Action\":[\"s3:PutObject\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:s3:::tollchat-site-903859731897-dev/tolls/i95-i495/*\",\"arn:aws:s3:::tollchat-site-903859731897-dev/tolls/i66/*\",\"arn:aws:s3:::tollchat-site-903859731897-dev/sitemap.xml\"],\"Sid\":\"WritePublicReports\"},{\"Action\":[\"s3:DeleteObject\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:s3:::tollchat-site-903859731897-dev/tolls/i95-i495/*\",\"arn:aws:s3:::tollchat-site-903859731897-dev/tolls/i66/*\"],\"Sid\":\"DeleteStalePublicReports\"},{\"Action\":[\"kms:Decrypt\",\"kms:Encrypt\",\"kms:GenerateDataKey\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:kms:us-east-1:903859731897:key/3bc78b60-9cbe-4abd-9744-8772c78d8379\"],\"Sid\":\"UseSiteKey\"}]}","role":"toll-v2-report-publisher-dev"},"after_identity":{"account_id":"903859731897","name":"toll-v2-report-publisher-dev","role":"toll-v2-report-publisher-dev"},"after_sensitive":{},"after_unknown":{},"before":{"id":"toll-v2-report-publisher-dev:toll-v2-report-publisher-dev","name":"toll-v2-report-publisher-dev","name_prefix":null,"policy":"{\"Statement\":[{\"Action\":[\"rds-db:connect\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:rds-db:us-east-1:903859731897:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/report_publisher_development\",\"arn:aws:rds-db:us-east-1:903859731897:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/pricing_reader_development\"],\"Sid\":\"ConnectRdsIam\"},{\"Action\":[\"sqs:SendMessage\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:sqs:us-east-1:903859731897:toll-v2-report-publisher-invoke-failure-dev\"],\"Sid\":\"SendInvokeFailure\"},{\"Action\":[\"s3:GetObject\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:s3:::tollchat-site-903859731897-dev/tolls/i95-i495/manifest.json\"],\"Sid\":\"ReadPublicationManifest\"},{\"Action\":[\"s3:ListBucket\"],\"Condition\":{\"StringEquals\":{\"s3:prefix\":[\"tolls/i95-i495/manifest.json\"]}},\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:s3:::tollchat-site-903859731897-dev\"],\"Sid\":\"FindPublicationManifest\"},{\"Action\":[\"s3:PutObject\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:s3:::tollchat-site-903859731897-dev/tolls/i95-i495/*\",\"arn:aws:s3:::tollchat-site-903859731897-dev/sitemap.xml\"],\"Sid\":\"WritePublicReports\"},{\"Action\":[\"kms:Decrypt\",\"kms:Encrypt\",\"kms:GenerateDataKey\"],\"Effect\":\"Allow\",\"Resource\":[\"arn:aws:kms:us-east-1:903859731897:key/3bc78b60-9cbe-4abd-9744-8772c78d8379\"],\"Sid\":\"UseSiteKey\"}],\"Version\":\"2012-10-17\"}","role":"toll-v2-report-publisher-dev"},"before_identity":{"account_id":"903859731897","name":"toll-v2-report-publisher-dev","role":"toll-v2-report-publisher-dev"},"before_sensitive":{}},"mode":"managed","name":"publisher","provider_name":"registry.terraform.io/hashicorp/aws","type":"aws_iam_role_policy"}]'''
PUBLISHER_AND_ALARM_FIXTURE_SHA256 = "232a4db5363fad4849dc5d1b971bab46d4975ac728eea9b23272f489058e437d"
PUBLISHER_AND_ALARM_FINGERPRINT = "867ea09423d65e7a96bd01341033f5054c0917401ab577c452c6671f7a990554"
PUBLISHER_AND_ALARM_TUPLE = (
    (ALARM_ADDRESS, "update", "report-freshness-alarm"),
    (PUBLISHER_ADDRESS, "update", "publisher-inline-policy"),
)


def _publisher_policy(*, i66=False):
    statements = [
        {
            "Sid": "ConnectRdsIam", "Effect": "Allow", "Action": ["rds-db:connect"],
            "Resource": [
                "arn:aws:rds-db:us-east-1:903859731897:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/report_publisher_development",
                "arn:aws:rds-db:us-east-1:903859731897:dbuser:db-GWX7FSL6UX6TNIVYIBHCP54IZU/pricing_reader_development",
            ],
        },
        {
            "Sid": "SendInvokeFailure", "Effect": "Allow", "Action": ["sqs:SendMessage"],
            "Resource": ["arn:aws:sqs:us-east-1:903859731897:toll-v2-report-publisher-invoke-failure-dev"],
        },
        {
            "Sid": "WritePublicReports", "Effect": "Allow", "Action": ["s3:PutObject"],
            "Resource": [f"{SITE_BUCKET}/tolls/i95-i495/*", *([f"{SITE_BUCKET}/tolls/i66/*"] if i66 else []), f"{SITE_BUCKET}/sitemap.xml"],
        },
        {
            "Sid": "UseSiteKey", "Effect": "Allow", "Action": ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"],
            "Resource": [SITE_KEY],
        },
    ]
    if i66:
        statements.extend(
            [
            {
                    "Sid": "ListPublicReports",
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": [SITE_BUCKET],
                    "Condition": {
                        "StringEquals": {"s3:prefix": ["tolls/i95-i495/", "tolls/i66/"]}
                    },
            },
            {
                    "Sid": "DeleteStalePublicReports",
                    "Effect": "Allow",
                    "Action": ["s3:DeleteObject"],
                    "Resource": [
                        f"{SITE_BUCKET}/tolls/i95-i495/*",
                        f"{SITE_BUCKET}/tolls/i66/*",
                    ],
            },
            ]
        )
    else:
        statements.extend(
            [
            {
                    "Sid": "ReadPublicationManifest",
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                "Resource": [f"{SITE_BUCKET}/tolls/i95-i495/manifest.json"],
            },
            {
                    "Sid": "FindPublicationManifest",
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": [SITE_BUCKET],
                    "Condition": {
                        "StringEquals": {"s3:prefix": ["tolls/i95-i495/manifest.json"]}
            },
                },
            ]
        )
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


def publisher_and_alarm_plan():
    return _plan(json.loads(PUBLISHER_AND_ALARM_FIXTURE))


def publisher_and_alarm_manifest():
    return _mutation_manifest(((PUBLISHER_ADDRESS, "update", ("policy",)), (ALARM_ADDRESS, "update", ("alarm_description", "dimensions"))))


def _set_path(target, path, value):
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


_DERIVED_FIXTURES = (
    (
        "aws_bedrockagentcore_agent_runtime.tollchat",
        "agent_runtime_artifact.code_configuration.code.s3.version_id",
        "aws_s3_object.agentcore.version_id",
        "aws_s3_object.agentcore",
        ("agent_runtime_artifact.code_configuration.code.s3.version_id",),
        ("source", "source_hash"),
    ),
    (
        "aws_bedrockagentcore_agent_runtime_endpoint.tollchat",
        "agent_runtime_version",
        "aws_bedrockagentcore_agent_runtime.tollchat.agent_runtime_version",
        "aws_bedrockagentcore_agent_runtime.tollchat",
        ("agent_runtime_version",),
        ("agent_runtime_artifact.code_configuration.code.s3.version_id",),
    ),
    (
        "aws_lambda_alias.tollchat_live",
        "function_version",
        "aws_lambda_function.tollchat_proxy.version",
        "aws_lambda_function.tollchat_proxy",
        ("function_version",),
        ("s3_object_version", "source_code_hash"),
    ),
    (
        "aws_lambda_function.tollchat_proxy",
        "s3_object_version",
        "aws_s3_object.tollchat_proxy.version_id",
        "aws_s3_object.tollchat_proxy",
        ("s3_object_version", "source_code_hash"),
        ("source", "source_hash"),
    ),
)


def _mutation_change(address, fields, action="update"):
    before, after = {}, {}
    spec = CONTRACT[address]
    for field in fields:
        _set_path(before, field, "old")
        _set_path(after, field, "new")
    for field, value in spec.create_identity:
        before[field] = after[field] = value
    if action == "no-op":
        after = copy.deepcopy(before)
    return _resource_change(address, action, before, after)


def _mutation_manifest(entries):
    manifest = manifest_header()
    manifest["mutations"] = []
    manifest["permissions"] = []
    for address, action, fields in entries:
        spec = CONTRACT[address]
        manifest["mutations"].append(
            {
            "address": address,
            "action": action,
            "operation_class": spec.operation_class,
            "changed_fields": list(fields),
            }
        )
        for permission in spec.permissions:
            resources = (
                permission.resources
                if spec.operation_class == "agentcore-trace-catalog"
                else permission.resources[:1]
            )
            for resource in resources:
                manifest["permissions"].append(
                    {
                "address": address,
                "action": permission.action,
                        "resource": resource,
                "conditions": dict(permission.conditions),
                    }
                )
    return manifest


def _derived_fixture(index, *, producer_action="update", configuration=True, expression_path=None, reference=None, resource_address=None):
    consumer, unknown_path, source_reference, producer, consumer_fields, producer_fields = _DERIVED_FIXTURES[index]
    consumer_change = _mutation_change(consumer, consumer_fields)
    consumer_change["change"]["after_unknown"] = {unknown_path: True}
    producer_change = _mutation_change(producer, producer_fields, producer_action)
    resources = [consumer_change, producer_change]
    plan = _plan(resources)
    if configuration:
        plan["configuration"] = {
            "root_module": {
                "resources": [
                    {
                    "address": resource_address or consumer,
                    "expressions": {
                        expression_path or unknown_path: {
                            "references": [reference or source_reference, producer],
                        },
                    },
                    }
                ],
            },
        }
    manifest = _mutation_manifest(((consumer, "update", consumer_fields), (producer, "update", producer_fields)))
    return plan, manifest


class DeliveryPlanValidatorTests(unittest.TestCase):
    def test_redacted_notices_require_complete_activation_and_support_later_noops(self):
        import gzip
        from infra.delivery_plan_validator import _validate_trace_notices, _Invalid, REDACTED_TRACE_NOTICE_DIGESTS
        fixture = json.loads(gzip.decompress((Path(__file__).parent / "fixtures/telemetry-notices.json.gz").read_bytes()))
        records = []
        for name, content in fixture["redacted"].items():
            address = f"aws_s3_object.{name}"
            self.assertEqual(hashlib.sha256(content.encode()).hexdigest(), REDACTED_TRACE_NOTICE_DIGESTS[address])
            records.append(dict(address=address, action="update", operation_class="site-object-upload", before={"content": fixture["legacy"][name]}, after={"content": content}))
        identity = dict(agent_runtime_arn="arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl", agent_runtime_id="nova_toll_v2_development-Y69XBf88Bl", agent_runtime_name="nova_toll_v2_development", region="us-east-1", role_arn="arn:aws:iam::903859731897:role/nova-toll-v2-agentcore-runtime-dev")
        before = dict(identity, environment_variables={"UNIFIED_TRACES_DESTINATION_ENABLED": "true"})
        after = dict(identity, environment_variables={"UNIFIED_TRACES_DESTINATION_ENABLED": "true", "TOLLCHAT_TELEMETRY_GUARDRAIL_ID": "testid", "TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION": "1"})
        records.append(dict(address="aws_bedrockagentcore_agent_runtime.tollchat", action="update", operation_class="agentcore-code", before=before, after=after, changed_fields=["environment_variables", "agent_runtime_artifact.code_configuration.code.s3.version_id"]))
        for endpoint in ("DEFAULT", "preview"):
            address = f'aws_cloudwatch_log_data_protection_policy.agentcore["{endpoint}"]'
            records.append(dict(address=address, action="create", operation_class="telemetry-log-protection", after=_telemetry_value(address)))
        _validate_trace_notices(records)
        for index in range(len(records)):
            with self.subTest(missing=index), self.assertRaises(_Invalid):
                _validate_trace_notices(records[:index] + records[index+1:])
        staged = copy.deepcopy(records)
        staged[3]["before"] = copy.deepcopy(staged[3]["after"])
        staged[3]["changed_fields"] = ["agent_runtime_artifact.code_configuration.code.s3.version_id"]
        _validate_trace_notices(staged)
        for mutant in (copy.deepcopy(records), copy.deepcopy(staged)):
            mutant[3]["changed_fields"].remove("agent_runtime_artifact.code_configuration.code.s3.version_id")
            with self.assertRaises(_Invalid):
                _validate_trace_notices(mutant)
        missing_env = copy.deepcopy(staged)
        missing_env[3]["after"]["environment_variables"].pop("TOLLCHAT_TELEMETRY_GUARDRAIL_ID")
        with self.assertRaises(_Invalid):
            _validate_trace_notices(missing_env)
        mixed = copy.deepcopy(records)
        mixed[0]["after"] = mixed[0]["before"]
        with self.assertRaises(_Invalid):
            _validate_trace_notices(mixed)
        for record in records:
            record.update(action="no-op", before=copy.deepcopy(record["after"]), changed_fields=[])
        _validate_trace_notices(records)
        for record in records:
            name = record["address"].split(".")[-1]
            if name in fixture["dashboard"]:
                record.update(action="update", after={"content": fixture["dashboard"][name]})
        _validate_trace_notices(records)
        changed_notice = copy.deepcopy(records)
        changed_notice[0]["after"]["content"] += "unreviewed content"
        with self.assertRaises(_Invalid):
            _validate_trace_notices(changed_notice)
        missing_guard = copy.deepcopy(records)
        missing_guard[3]["after"]["environment_variables"].pop("TOLLCHAT_TELEMETRY_GUARDRAIL_ID")
        with self.assertRaises(_Invalid):
            _validate_trace_notices(missing_guard)

    def test_credential_regex_covers_plain_and_serialized_headers(self):
        import re
        source = (Path(__file__).parent / "telemetry.tf").read_text().split('name           = "authorization_header"', 1)[1]
        pattern = json.loads(re.search(r"(?m)^\s*pattern\s*= (.+)$", source).group(1))
        for text in ("Authorization: Bearer abcdefgh12345", "Authorization: Basic abcdefgh12345", "x-api-key: abcdefgh12345", '{"x-api-key":"abcdefgh12345"}', '{"Authorization":"Bearer abcdefgh12345"}'):
            self.assertIsNotNone(re.search(pattern, text), text)

    def assert_reason(self, reason, plan=None, manifest=None, identity=None):
        result = validate_plan(plan if plan is not None else lambda_plan(), manifest if manifest is not None else lambda_manifest(), identity)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], reason)
        self.assertNotIn("filename", result)
        self.assertNotIn("old.zip", result)
        return result

    def test_accepts_lambda_code_update_with_independent_permission(self):
        result = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["reason_code"], "ok")
        self.assertEqual(result["addresses"], [LAMBDA_ADDRESS])
        self.assertEqual(result["actions"], ["update"])
        self.assertEqual(result["operation_classes"], ["lambda-code"])
        self.assertEqual(len(result["fingerprint"]), 64)
        self.assertEqual(set(result), {"status", "reason_code", "addresses", "actions", "operation_classes", "fingerprint"})

    def test_accepts_hash_only_local_lambda_updates(self):
        for address in ("aws_lambda_function.loader", "aws_lambda_function.publisher"):
            with self.subTest(address=address):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                result = validate_plan(plan, manifest)
                self.assertEqual(result["status"], "accepted")
                self.assertEqual(result["reason_code"], "ok")
                self.assertEqual(result["addresses"], [address])

    def test_hash_only_local_lambda_boundaries_are_independent(self):
        for address in ("aws_lambda_function.loader", "aws_lambda_function.publisher"):
            with self.subTest(address=address, boundary="runtime"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(((address, "update", ("filename", "source_code_hash")),))
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "manifest_mutation_mismatch")
            with self.subTest(address=address, boundary="manifest"):
                plan = _plan([_mutation_change(address, ("filename", "source_code_hash"))])
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "manifest_mutation_mismatch")

    def test_rejects_hash_only_s3_lambda_updates_at_both_boundaries_and_cli(self):
        for address in ("aws_lambda_function.tollchat_proxy", "aws_lambda_function.timed_checks"):
            with self.subTest(address=address, boundary="runtime"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                if address.endswith("timed_checks"):
                    manifest["deployment_inputs"]["v2/scripts/build_timed_checks_zip.sh"] = HASH
                    manifest["packages"]["timed-checks.zip"] = HASH
                result = validate_plan(plan, manifest)
                self.assertEqual(
                    result,
                    {
                        "status": "rejected",
                        "reason_code": "unsupported_field_delta",
                        "address": address,
                        "action": "update",
                        "operation_class": "lambda-code",
                    },
                )

            with self.subTest(address=address, boundary="manifest"):
                plan = _plan([_mutation_change(address, ("s3_object_version", "source_code_hash"))])
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                if address.endswith("timed_checks"):
                    manifest["deployment_inputs"]["v2/scripts/build_timed_checks_zip.sh"] = HASH
                    manifest["packages"]["timed-checks.zip"] = HASH
                result = validate_plan(plan, manifest)
                self.assertEqual(
                    result,
                    {
                        "status": "rejected",
                        "reason_code": "unsupported_field_delta",
                        "address": address,
                        "action": "update",
                        "operation_class": "lambda-code",
                    },
                )

        address = "aws_lambda_function.tollchat_proxy"
        plan = _plan([_mutation_change(address, ("source_code_hash",))])
        change = plan["resource_changes"][0]["change"]
        change["before"]["source_code_hash"] = "hash-sentinel-before"
        change["after"]["source_code_hash"] = "hash-sentinel-after"
        manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, manifest_path, identity_path = (root / name for name in ("plan.json", "manifest.json", "identity.json"))
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            identity_path.write_text(json.dumps(dict(EXPECTED_IDENTITY),), encoding="utf-8")
            cli = subprocess.run(
                ["python3", "infra/delivery_plan_validator.py", str(plan_path), str(manifest_path), "--identity", str(identity_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(cli.returncode, 0)
        self.assertEqual(cli.stdout.count("\n"), 1)
        self.assertEqual(
            json.loads(cli.stdout),
            {
                "status": "rejected",
                "reason_code": "unsupported_field_delta",
                "address": address,
                "action": "update",
                "operation_class": "lambda-code",
            },
        )
        self.assertEqual(cli.stderr, "")
        self.assertNotIn("sentinel", cli.stdout + cli.stderr)

    def test_hash_only_local_lambda_updates_retain_existing_gates(self):
        for address in ("aws_lambda_function.loader", "aws_lambda_function.publisher"):
            with self.subTest(address=address, gate="action"):
                plan = _plan([_mutation_change(address, ("source_code_hash",), action="delete")])
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "delete_not_permitted")
            with self.subTest(address=address, gate="provider"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["resource_changes"][0]["provider_name"] = "registry.terraform.io/hashicorp/random"
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "provider_identity_mismatch")
            with self.subTest(address=address, gate="terraform"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["terraform_version"] = "1.14.0"
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "provider_identity_mismatch")
            with self.subTest(address=address, gate="missing_identity"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                self.assertEqual(_validate_plan(plan, manifest)["reason_code"], "provider_identity_missing")
            with self.subTest(address=address, gate="identity"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["resource_changes"][0]["change"]["before"]["function_name"] = "wrong-development-function"
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "invalid_resource_identity")
            with self.subTest(address=address, gate="missing_function_identity"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["resource_changes"][0]["change"]["before"].pop("function_name")
                manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "invalid_resource_identity")
            for field in ("s3_bucket", "s3_key", "s3_object_version"):
                with self.subTest(address=address, gate=field):
                    plan = _plan([_mutation_change(address, ("source_code_hash",))])
                    change = plan["resource_changes"][0]["change"]
                    change["before"][field] = change["after"][field] = "non-null"
                    manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                    self.assertEqual(validate_plan(plan, manifest)["reason_code"], "invalid_resource_identity")
            for label, mutate, reason in (
                ("missing_permission", lambda manifest: manifest.update(permissions=[]), "missing_permission"),
                ("permission_action", lambda manifest: manifest["permissions"][0].update(action="lambda:UpdateFunctionConfiguration"), "invalid_permission"),
                ("permission_resource", lambda manifest: manifest["permissions"][0].update(resource="*"), "invalid_permission"),
                ("permission_conditions", lambda manifest: manifest["permissions"][0].update(conditions={"extra": "value"}), "invalid_permission"),
                ("manifest_mismatch", lambda manifest: manifest["mutations"][0].update(changed_fields=["filename", "source_code_hash"]), "manifest_mutation_mismatch"),
            ):
                with self.subTest(address=address, gate=label):
                    plan = _plan([_mutation_change(address, ("source_code_hash",))])
                    manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                    mutate(manifest)
                    self.assertEqual(validate_plan(plan, manifest)["reason_code"], reason)
            for label, mutate, reason in (
                ("runtime", lambda plan: plan["resource_changes"][0]["change"]["after"].update(runtime="python3.14"), "unsupported_field_delta"),
                ("unknown", lambda plan: plan["resource_changes"][0]["change"].update(after_unknown={"source_code_hash": True}), "unknown_authorization_value"),
                ("sensitive", lambda plan: plan["resource_changes"][0]["change"].update(after_sensitive={"source_code_hash": True}), "sensitive_authorization_value"),
                ("production", lambda plan: plan["resource_changes"][0]["change"]["after"].update(source_code_hash="production"), "production_target"),
            ):
                with self.subTest(address=address, gate=label):
                    plan = _plan([_mutation_change(address, ("source_code_hash",))])
                    manifest = _mutation_manifest(((address, "update", ("source_code_hash",)),))
                    mutate(plan)
                    self.assertEqual(validate_plan(plan, manifest)["reason_code"], reason)

    def test_later_publisher_release_can_use_hash_only_manifest_declaration(self):
        manifest = json.loads(
            (Path(__file__).resolve().parent / "development-release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        later_manifest = copy.deepcopy(manifest)
        publisher = next(
            record
            for record in later_manifest["mutations"]
            if record["address"] == "aws_lambda_function.publisher"
        )
        publisher["changed_fields"] = ["source_code_hash"]
        loader = next(
            record
            for record in later_manifest["mutations"]
            if record["address"] == "aws_lambda_function.loader"
        )
        self.assertEqual(loader["changed_fields"], ["filename", "source_code_hash"])
        result = validate_plan(
            _plan([_mutation_change("aws_lambda_function.publisher", ("source_code_hash",))]),
            later_manifest,
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["addresses"], ["aws_lambda_function.publisher"])

    def test_accepts_only_reviewed_publisher_and_report_freshness_updates(self):
        self.assertEqual(
            hashlib.sha256(PUBLISHER_AND_ALARM_FIXTURE).hexdigest(),
            PUBLISHER_AND_ALARM_FIXTURE_SHA256,
        )
        plan, manifest = publisher_and_alarm_plan(), publisher_and_alarm_manifest()
        self.assertEqual(plan["resource_changes"], json.loads(PUBLISHER_AND_ALARM_FIXTURE))
        result = validate_plan(plan, manifest)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["addresses"], [ALARM_ADDRESS, PUBLISHER_ADDRESS])
        self.assertEqual(result["actions"], ["update", "update"])
        self.assertEqual(result["operation_classes"], ["report-freshness-alarm", "publisher-inline-policy"])
        self.assertEqual(result["fingerprint"], PUBLISHER_AND_ALARM_FINGERPRINT)
        self.assertEqual(
            tuple(zip(result["addresses"], result["actions"], result["operation_classes"])),
            PUBLISHER_AND_ALARM_TUPLE,
        )
        expected = {
            PUBLISHER_ADDRESS: ("aws_iam_role_policy", "publisher", {"name", "role", "id", "name_prefix", "policy"}),
            ALARM_ADDRESS: ("aws_cloudwatch_metric_alarm", "report_generation_freshness", {
                "actions_enabled", "alarm_actions", "alarm_description", "alarm_name", "arn", "comparison_operator",
                "datapoints_to_alarm", "dimensions", "evaluate_low_sample_count_percentiles", "evaluation_criteria",
                "evaluation_interval", "evaluation_periods", "extended_statistic", "id", "insufficient_data_actions",
                "metric_name", "metric_query", "namespace", "ok_actions", "period", "region", "statistic", "tags",
                "tags_all", "threshold", "threshold_metric_id", "treat_missing_data", "unit",
            }),
        }
        for resource in plan["resource_changes"]:
            resource_type, name, fields = expected[resource["address"]]
            self.assertEqual(set(resource), {"address", "mode", "type", "name", "provider_name", "change"})
            self.assertEqual((resource["mode"], resource["type"], resource["name"], resource["provider_name"]), ("managed", resource_type, name, EXPECTED_PROVIDER_NAME))
            change = resource["change"]
            self.assertEqual(change["actions"], ["update"])
            self.assertEqual(set(change), {"actions", "before", "after", "after_unknown", "before_sensitive", "after_sensitive", "before_identity", "after_identity"})
            self.assertEqual(set(change["before"]), fields)
            self.assertEqual(set(change["after"]), fields)
            self.assertEqual(change["before_identity"], change["after_identity"])
        publisher = next(item for item in plan["resource_changes"] if item["address"] == PUBLISHER_ADDRESS)["change"]
        policy_by_sid = lambda value: {statement["Sid"]: statement for statement in json.loads(value)["Statement"]}
        self.assertEqual(policy_by_sid(publisher["before"]["policy"]), policy_by_sid(_publisher_policy()))
        self.assertEqual(policy_by_sid(publisher["after"]["policy"]), policy_by_sid(_publisher_policy(i66=True)))
        alarm = next(item for item in plan["resource_changes"] if item["address"] == ALARM_ADDRESS)["change"]
        self.assertEqual(alarm["before"]["dimensions"], {"Environment": "development", "facility": "i95_i495"})
        self.assertEqual(alarm["after"]["dimensions"], {"Environment": "development", "facility_scope": "both"})

    def test_target_provider_identity_and_envelopes_are_exact(self):
        plan, manifest = publisher_and_alarm_plan(), publisher_and_alarm_manifest()
        expected_identities = {
            PUBLISHER_ADDRESS: {
                "account_id": "903859731897",
                "name": PUBLISHER_ROLE,
                "role": PUBLISHER_ROLE,
            },
            ALARM_ADDRESS: {
                "account_id": "903859731897",
                "alarm_name": ALARM_NAME,
                "region": "us-east-1",
            },
        }
        for resource in plan["resource_changes"]:
            for side in ("before_identity", "after_identity"):
                self.assertEqual(resource["change"][side], expected_identities[resource["address"]])
                for field in tuple(resource["change"][side]):
                    rejected = copy.deepcopy(plan)
                    target = next(item for item in rejected["resource_changes"] if item["address"] == resource["address"])
                    target["change"][side][field] = "wrong"
                    self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted")
                rejected = copy.deepcopy(plan)
                target = next(item for item in rejected["resource_changes"] if item["address"] == resource["address"])
                target["change"].pop(side)
                self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted")
            for container in (resource, resource["change"]):
                rejected = copy.deepcopy(plan)
                target = next(item for item in rejected["resource_changes"] if item["address"] == resource["address"])
                (target if container is resource else target["change"])["unexpected"] = None
                self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted")

            for side in ("before_identity", "after_identity"):
                for value in (None, "identity", [], {**expected_identities[resource["address"]], "extra": "value"}):
                    rejected = copy.deepcopy(plan)
                    target = next(item for item in rejected["resource_changes"] if item["address"] == resource["address"])
                    target["change"][side] = value
                    self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted")
                for field in expected_identities[resource["address"]]:
                    for value in (None, 1):
                        rejected = copy.deepcopy(plan)
                        target = next(item for item in rejected["resource_changes"] if item["address"] == resource["address"])
                        target["change"][side][field] = value
                        self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted")
                    rejected = copy.deepcopy(plan)
                    target = next(item for item in rejected["resource_changes"] if item["address"] == resource["address"])
                    target["change"][side].pop(field)
                    self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted")

            for container_name, keys in (("resource", tuple(resource)), ("change", tuple(resource["change"]))):
                for key in keys:
                    rejected = copy.deepcopy(plan)
                    target = next(item for item in rejected["resource_changes"] if item["address"] == resource["address"])
                    (target if container_name == "resource" else target["change"]).pop(key)
                    self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "malformed_input")

        for address, field, value, reason in (
            (PUBLISHER_ADDRESS, "name", "other", "invalid_resource_identity"),
            (PUBLISHER_ADDRESS, "role", "other", "invalid_resource_identity"),
            (ALARM_ADDRESS, "alarm_name", "other", "invalid_resource_identity"),
        ):
            rejected = copy.deepcopy(plan)
            for resource in rejected["resource_changes"]:
                if resource["address"] == address:
                    resource["change"]["before"][field] = value
                    resource["change"]["after"][field] = value
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], reason)

        for label, address, side, field in (
            ("publisher equal-but-wrong", PUBLISHER_ADDRESS, "both", "name"),
            ("alarm equal-but-wrong", ALARM_ADDRESS, "both", "alarm_name"),
            ("publisher before name", PUBLISHER_ADDRESS, "before_identity", "name"),
            ("publisher after name", PUBLISHER_ADDRESS, "after_identity", "name"),
            ("publisher before role", PUBLISHER_ADDRESS, "before_identity", "role"),
            ("publisher after role", PUBLISHER_ADDRESS, "after_identity", "role"),
            ("alarm before name", ALARM_ADDRESS, "before_identity", "alarm_name"),
            ("alarm after name", ALARM_ADDRESS, "after_identity", "alarm_name"),
        ):
            rejected = copy.deepcopy(plan)
            change = next(
                item for item in rejected["resource_changes"] if item["address"] == address
            )["change"]
            for identity_side in (("before_identity", "after_identity") if side == "both" else (side,)):
                change[identity_side][field] = "equal-but-wrong"
            self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted", label)

        for address, action in ((PUBLISHER_ADDRESS, "create"), (ALARM_ADDRESS, "delete")):
            rejected = copy.deepcopy(plan)
            next(item for item in rejected["resource_changes"] if item["address"] == address)["change"]["actions"] = [action]
            self.assertNotEqual(validate_plan(rejected, manifest)["status"], "accepted")

        rejected = copy.deepcopy(plan)
        publisher = next(item for item in rejected["resource_changes"] if item["address"] == PUBLISHER_ADDRESS)
        publisher["change"]["after"]["policy"] = "{not json"
        self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unsupported_field_delta")
        rejected = copy.deepcopy(plan)
        publisher = next(item for item in rejected["resource_changes"] if item["address"] == PUBLISHER_ADDRESS)
        publisher["change"]["after"]["policy"] = _publisher_policy()
        self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unsupported_field_delta")
        rejected = copy.deepcopy(plan)
        alarm = next(item for item in rejected["resource_changes"] if item["address"] == ALARM_ADDRESS)
        alarm["change"]["after"]["dimensions"]["unexpected"] = "value"
        self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unsupported_field_delta")

        for address, field in ((PUBLISHER_ADDRESS, "policy"), (ALARM_ADDRESS, "alarm_name")):
            rejected = copy.deepcopy(plan)
            resource = next(item for item in rejected["resource_changes"] if item["address"] == address)
            resource["change"]["after_unknown"] = {field: True}
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unknown_authorization_value")
            resource["change"]["after_unknown"] = {}
            resource["change"]["after_sensitive"] = {field: True}
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "sensitive_authorization_value")

        for field in ("actions_enabled", "alarm_actions", "metric_name", "threshold"):
            rejected = copy.deepcopy(plan)
            alarm = next(item for item in rejected["resource_changes"] if item["address"] == ALARM_ADDRESS)
            alarm["change"]["after"][field] = None
            alarm["change"]["after_unknown"] = {field: True}
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unknown_authorization_value")

        for resource in manifest["permissions"]:
            rejected_manifest = copy.deepcopy(manifest)
            next(item for item in rejected_manifest["permissions"] if item["address"] == resource["address"])["resource"] = "*"
            self.assertEqual(validate_plan(plan, rejected_manifest)["reason_code"], "invalid_permission")

        def reject_policy_change(sid, field, value):
            rejected = copy.deepcopy(plan)
            publisher = next(item for item in rejected["resource_changes"] if item["address"] == PUBLISHER_ADDRESS)
            policy = json.loads(publisher["change"]["after"]["policy"])
            next(statement for statement in policy["Statement"] if statement["Sid"] == sid)[field] = value
            publisher["change"]["after"]["policy"] = json.dumps(policy)
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unsupported_field_delta")

        for sid, field, value in (
            ("ListPublicReports", "Action", ["s3:GetObject"]),
            ("ListPublicReports", "Resource", [f"{SITE_BUCKET}/*"]),
            ("ListPublicReports", "Condition", {"StringEquals": {"s3:prefix": ["tolls/*"]}}),
            ("WritePublicReports", "Action", ["s3:DeleteObject"]),
            ("WritePublicReports", "Resource", [f"{SITE_BUCKET}/tolls/i95-i495/*", f"{SITE_BUCKET}/tolls/other/*"]),
            ("DeleteStalePublicReports", "Action", ["s3:PutObject"]),
            ("DeleteStalePublicReports", "Resource", [f"{SITE_BUCKET}/tolls/i95-i495/*", f"{SITE_BUCKET}/*"]),
            ("ConnectRdsIam", "Resource", ["arn:aws:rds-db:us-east-1:903859731897:dbuser:db-OTHER/pricing_reader_development"]),
            ("SendInvokeFailure", "Resource", ["arn:aws:sqs:us-east-1:903859731897:unrelated"]),
            ("UseSiteKey", "Action", ["kms:Decrypt"]),
            ("UseSiteKey", "Resource", ["arn:aws:kms:us-east-1:903859731897:key/00000000-0000-0000-0000-000000000000"]),
            ("UseSiteKey", "Resource", ["arn:aws:kms:us-east-1:903859731897:key/not-a-uuid"]),
        ):
            reject_policy_change(sid, field, value)

        for side in ("before", "after"):
            rejected = copy.deepcopy(plan)
            publisher = next(item for item in rejected["resource_changes"] if item["address"] == PUBLISHER_ADDRESS)
            policy = json.loads(publisher["change"][side]["policy"])
            next(statement for statement in policy["Statement"] if statement["Sid"] == "UseSiteKey")["Resource"] = []
            publisher["change"][side]["policy"] = json.dumps(policy)
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unsupported_field_delta")

        rejected = copy.deepcopy(plan)
        for resource in rejected["resource_changes"]:
            if resource["address"] == PUBLISHER_ADDRESS:
                for side in ("before", "after"):
                    policy = json.loads(resource["change"][side]["policy"])
                    policy["Statement"].append({"Sid": "UnreviewedPrivilege", "Effect": "Allow", "Action": ["iam:*"], "Resource": ["*"]})
                    resource["change"][side]["policy"] = json.dumps(policy)
        self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unsupported_field_delta")

        for field, value in (
            ("alarm_description", "other"),
            ("dimensions", {"facility_scope": "other", "Environment": "development"}),
            ("dimensions", {"facility_scope": "both"}),
            ("dimensions", {"facility_scope": "both", "Environment": "development", "extra": "value"}),
            ("metric_name", "other"),
        ):
            rejected = copy.deepcopy(plan)
            alarm = next(item for item in rejected["resource_changes"] if item["address"] == ALARM_ADDRESS)
            alarm["change"]["after"][field] = value
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unsupported_field_delta")

        for address, field in (
            (PUBLISHER_ADDRESS, "name"),
            (PUBLISHER_ADDRESS, "role"),
            (ALARM_ADDRESS, "alarm_name"),
        ):
            for side in ("before", "after"):
                rejected = copy.deepcopy(plan)
                resource = next(item for item in rejected["resource_changes"] if item["address"] == address)
                resource["change"][side][field] = "independently-wrong"
                self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "invalid_resource_identity")

        for address, fields in ((PUBLISHER_ADDRESS, ("policy", "name", "role")), (ALARM_ADDRESS, ("alarm_name", "alarm_description", "dimensions"))):
            for field in fields:
                rejected = copy.deepcopy(plan)
                resource = next(item for item in rejected["resource_changes"] if item["address"] == address)
                resource["change"]["after"][field] = None
                resource["change"]["after_unknown"] = {field: True}
                self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "unknown_authorization_value")
                resource["change"]["after_unknown"] = {}
                for sensitive_side in ("before_sensitive", "after_sensitive"):
                    resource["change"][sensitive_side] = {field: True}
                    self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "sensitive_authorization_value")
                    resource["change"][sensitive_side] = {}

        for address in (PUBLISHER_ADDRESS, ALARM_ADDRESS):
            rejected = copy.deepcopy(plan)
            next(item for item in rejected["resource_changes"] if item["address"] == address)["change"]["replace_paths"] = [["policy"]]
            self.assertEqual(validate_plan(rejected, manifest)["reason_code"], "malformed_input")
        for mutation in ("mutations", "permissions"):
            rejected_manifest = copy.deepcopy(manifest)
            rejected_manifest[mutation].append(copy.deepcopy(rejected_manifest[mutation][0]))
            self.assertNotEqual(validate_plan(plan, rejected_manifest)["status"], "accepted")
            for index in range(len(rejected_manifest[mutation]) - 1):
                for key in tuple(rejected_manifest[mutation][index]):
                    candidate = copy.deepcopy(manifest)
                    candidate[mutation][index].pop(key)
                    self.assertNotEqual(validate_plan(plan, candidate)["status"], "accepted")

    def test_publisher_policy_rejections_are_sanitized_in_api_and_cli(self):
        plan, manifest = publisher_and_alarm_plan(), publisher_and_alarm_manifest()
        sentinel = "publisher-policy-sentinel-do-not-leak"
        publisher = next(item for item in plan["resource_changes"] if item["address"] == PUBLISHER_ADDRESS)
        publisher["change"]["after"]["policy"] = _publisher_policy(i66=True).replace("sitemap.xml", sentinel)
        result = validate_plan(plan, manifest)
        self.assertEqual(result["reason_code"], "unsupported_field_delta")
        self.assertNotIn(sentinel, json.dumps(result))
        self.assertFalse({"before", "after", "policy"} & set(result))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, manifest_path, identity_path = (root / name for name in ("plan.json", "manifest.json", "identity.json"))
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            identity_path.write_text(json.dumps(dict(EXPECTED_IDENTITY)), encoding="utf-8")
            cli = subprocess.run(["python3", "infra/delivery_plan_validator.py", str(plan_path), str(manifest_path), "--identity", str(identity_path)], capture_output=True, text=True, check=False)
            self.assertNotEqual(cli.returncode, 0)
            self.assertNotIn(sentinel, cli.stdout + cli.stderr)
            self.assertEqual(json.loads(cli.stdout)["reason_code"], "unsupported_field_delta")

    def test_manifest_package_order_follows_reviewed_timed_marker(self):
        legacy = lambda_manifest()
        self.assertEqual(validate_plan(lambda_plan(), legacy)["status"], "accepted")

        timed = copy.deepcopy(legacy)
        timed["deployment_inputs"]["v2/scripts/build_timed_checks_zip.sh"] = HASH
        timed["packages"]["timed-checks.zip"] = HASH
        self.assertEqual(validate_plan(lambda_plan(), timed)["status"], "accepted")

        legacy_extra = copy.deepcopy(legacy)
        legacy_extra["packages"]["timed-checks.zip"] = HASH
        self.assertEqual(validate_plan(lambda_plan(), legacy_extra)["reason_code"], "malformed_input")

        timed_missing = copy.deepcopy(timed)
        timed_missing["packages"].pop("timed-checks.zip")
        self.assertEqual(validate_plan(lambda_plan(), timed_missing)["reason_code"], "malformed_input")

    def test_marker_free_manifest_cannot_declare_timed_contract_entries(self):
        addresses = (
            "aws_s3_object.timed_checks",
            "aws_lambda_function.timed_checks",
            'aws_scheduler_schedule.timed_checks["greenway-eb-mon-0723"]',
        )
        for address in addresses:
            with self.subTest(address=address):
                spec = CONTRACT[address]
                fields = ("schedule_expression",) if address.startswith("aws_scheduler") else spec.fields[:2]
                manifest = {
                    **manifest_header(),
                    "mutations": [
                        {
                        "address": address,
                        "action": "update",
                        "operation_class": spec.operation_class,
                        "changed_fields": list(fields),
                        }
                    ],
                    "permissions": [
                        {
                        "address": address,
                        "action": permission.action,
                        "resource": permission.resources[0],
                        "conditions": dict(permission.conditions),
                        }
                        for permission in spec.permissions
                    ],
                }
                self.assert_reason("timed_contract_requires_marker", manifest=manifest)

    def test_lambda_updates_require_exact_development_function_identity(self):
        fields_by_address = {
            "aws_lambda_function.loader": ("filename", "source_code_hash"),
            "aws_lambda_function.publisher": ("filename", "source_code_hash"),
            "aws_lambda_function.tollchat_proxy": ("s3_object_version", "source_code_hash"),
        }
        for address, fields in fields_by_address.items():
            with self.subTest(address=address):
                plan = _plan([_mutation_change(address, fields)])
                manifest = _mutation_manifest(((address, "update", fields),))
                self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
                for invalid in (None, "wrong-development-function"):
                    with self.subTest(invalid=invalid):
                        mismatched = copy.deepcopy(plan)
                        change = mismatched["resource_changes"][0]["change"]
                        if invalid is None:
                            change["before"].pop("function_name", None)
                        else:
                            change["before"]["function_name"] = invalid
                        self.assertEqual(
                            validate_plan(mismatched, manifest)["reason_code"],
                            "invalid_resource_identity",
                        )

    def test_accepts_pinned_metadata_and_keeps_drift_out_of_result(self):
        drift = [_resource_change("aws_iam_role.publisher", "update", {"name": "old"}, {"name": "new"})]
        plan = lambda_plan()
        plan.update(
            resource_drift=drift,
            relevant_attributes=[{"resource": "aws_iam_role.publisher", "attribute": ["name"]}],
        )
        result = validate_plan(plan, lambda_manifest())
        baseline = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result, baseline)

    def test_accepts_equal_identity_metadata_without_output_or_field_deltas(self):
        plan = lambda_plan()
        identity = {"id": "stable", "version": 1}
        change = plan["resource_changes"][0]["change"]
        change["before_identity"] = identity
        change["after_identity"] = copy.deepcopy(identity)
        result = validate_plan(plan, lambda_manifest())
        self.assertEqual(result, validate_plan(lambda_plan(), lambda_manifest()))
        self.assertNotIn("before_identity", json.dumps(result))
        self.assertNotIn("after_identity", json.dumps(result))

        no_op = _resource_change(
            "aws_acm_certificate.site[0]",
            "no-op",
            {"domain_name": "dev.tollchat.ai"},
            {"domain_name": "dev.tollchat.ai"},
        )
        no_op["change"]["before_identity"] = False
        no_op["change"]["after_identity"] = False
        result = validate_plan(
            _plan([no_op], applyable=False),
            lambda_manifest(),
        )
        self.assertEqual(result["status"], "accepted")

    def test_rejects_invalid_mismatched_and_production_identity_metadata(self):
        for field, value in (
            ("before_identity", "not-an-object"),
            ("after_identity", ["not-an-object"]),
        ):
            with self.subTest(field=field):
                plan = lambda_plan()
                plan["resource_changes"][0]["change"][field] = value
                self.assert_reason("malformed_input", plan=plan)

        plan = lambda_plan()
        plan["resource_changes"][0]["change"].update(
            before_identity={"id": "old"},
            after_identity={"id": "new"},
        )
        self.assert_reason("malformed_input", plan=plan)

        no_op = _resource_change(
            "aws_acm_certificate.site[0]",
            "no-op",
            {"domain_name": "dev.tollchat.ai"},
            {"domain_name": "dev.tollchat.ai"},
            before_identity={"id": "old"},
            after_identity={"id": "new"},
        )
        self.assertEqual(
            validate_plan(_plan([no_op], applyable=False), lambda_manifest())[
                "status"
            ],
            "accepted",
        )

        plan = lambda_plan()
        plan["resource_changes"][0]["change"].update(
            before_identity={"account": "920534282028"},
            after_identity={"account": "920534282028"},
        )
        result = self.assert_reason("production_target", plan=plan)
        self.assertNotIn("920534282028", json.dumps(result))
        self.assertNotIn("before_identity", json.dumps(result))
        self.assertNotIn("after_identity", json.dumps(result))

    def test_accepts_noop_and_read_resources_with_applyable_false_or_true(self):
        no_op = _resource_change(
            "aws_acm_certificate.site[0]",
            "no-op",
            {"domain_name": "dev.tollchat.ai"},
            {"domain_name": "dev.tollchat.ai"},
        )
        read = _resource_change("aws_iam_role.publisher", "read", None, None)
        read["address"] = "data.aws_iam_role.publisher"
        read["mode"] = "data"
        for applyable in (False, True):
            with self.subTest(applyable=applyable):
                result = validate_plan(
                    _plan([no_op, read], applyable=applyable),
                    lambda_manifest(),
                )
                self.assertEqual(result["status"], "accepted")
                self.assertEqual(result["addresses"], [])

    def test_rejects_partial_invalid_flags_and_unapplyable_mutation(self):
        for missing in ("applyable", "complete", "errored"):
            with self.subTest(missing=missing):
                plan = lambda_plan()
                del plan[missing]
                self.assert_reason("malformed_input", plan=plan)
        for field, value in (
            ("applyable", "true"),
            ("complete", 1),
            ("errored", None),
            ("complete", False),
            ("errored", True),
            ("applyable", False),
        ):
            with self.subTest(field=field, value=value):
                plan = lambda_plan()
                plan[field] = value
                self.assert_reason("malformed_input", plan=plan)

    def test_rejects_malformed_plan_metadata_and_unknown_keys(self):
        plan = lambda_plan()
        plan["unexpected"] = "value"
        self.assert_reason("malformed_input", plan=plan)

        for value in ({}, "drift", ["not-a-resource"]):
            with self.subTest(resource_drift=value):
                plan = lambda_plan()
                plan["resource_drift"] = value
                self.assert_reason(
                    "malformed_input",
                    plan=plan,
                )

        valid_drift = _resource_change("aws_iam_role.publisher", "update", {"name": "old"}, {"name": "new"})
        for mutation in (
            {"unknown": True},
            {"provider_name": "registry.terraform.io/hashicorp/random"},
            {"deposed": "0"},
        ):
            with self.subTest(mutation=mutation):
                drift = copy.deepcopy(valid_drift)
                drift.update(mutation)
                plan = lambda_plan()
                plan["resource_drift"] = [drift]
                self.assert_reason(
                    "malformed_input",
                    plan=plan,
                )

        for value in ({}, [{"resource": "x"}], [{"resource": "", "attribute": []}], [{"resource": "x", "attribute": [1]}]):
            with self.subTest(relevant_attributes=value):
                plan = lambda_plan()
                plan["relevant_attributes"] = value
                self.assert_reason(
                    "malformed_input",
                    plan=plan,
                )

    def test_accepts_each_derived_unknown_edge_with_exact_provenance(self):
        for index in range(len(_DERIVED_FIXTURES)):
            with self.subTest(index=index):
                plan, manifest = _derived_fixture(index)
                result = validate_plan(plan, manifest)
                self.assertEqual(result["status"], "accepted")
                self.assertNotIn("after_unknown", json.dumps(result))

        plan, manifest = _derived_fixture(0)
        result = validate_plan(plan, manifest)
        changed = copy.deepcopy(plan)
        _set_path(
            changed["resource_changes"][0]["change"]["after"],
            "agent_runtime_artifact.code_configuration.code.s3.version_id",
            "different",
        )
        self.assertNotEqual(result["fingerprint"], validate_plan(changed, manifest)["fingerprint"])

        plan, manifest = _derived_fixture(0, expression_path="agent_runtime_artifact.0.code_configuration.0.code.0.s3.0.version_id")
        plan["resource_changes"][0]["change"]["after_unknown"] = {
            "agent_runtime_artifact[0].code_configuration[0].code[0].s3[0].version_id": True,
        }
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")

    def test_runtime_identity_metadata_omission_requires_fixed_direct_name(self):
        address = "aws_bedrockagentcore_agent_runtime.tollchat"
        fields = ("agent_runtime_artifact.code_configuration.code.s3.version_id",)
        plan = _plan([_mutation_change(address, fields)])
        change = plan["resource_changes"][0]["change"]
        for side in ("before", "after"):
            change[side]["agent_runtime_name"] = dict(
                CONTRACT[address].provider_change_identity
            )["agent_runtime_name"]
            change.pop(f"{side}_identity")
        manifest = _mutation_manifest(((address, "update", fields),))
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")

        for side in ("before_identity", "after_identity"):
            with self.subTest(identity=side):
                rejected = copy.deepcopy(plan)
                rejected["resource_changes"][0]["change"][side] = dict(
                    CONTRACT[address].provider_change_identity
                )
                self.assert_reason("malformed_input", plan=rejected, manifest=manifest)

        for value in (
            None,
            "wrong-runtime-name",
            ["wrong-runtime-name"],
            {},
            {"agent_runtime_name": "wrong-runtime-name"},
            {"agent_runtime_name": "nova_toll_v2_development", "extra": "value"},
        ):
            with self.subTest(identity=value):
                rejected = copy.deepcopy(plan)
                rejected["resource_changes"][0]["change"].update(
                    before_identity=copy.deepcopy(value), after_identity=copy.deepcopy(value)
                )
                result = validate_plan(rejected, manifest)
                self.assertEqual(result["status"], "rejected")
                self.assertNotIn("wrong-runtime-name", json.dumps(result))

        unequal = copy.deepcopy(plan)
        unequal["resource_changes"][0]["change"].update(
            before_identity=dict(CONTRACT[address].provider_change_identity),
            after_identity={"agent_runtime_name": "wrong-runtime-name"},
        )
        self.assert_reason("malformed_input", plan=unequal, manifest=manifest)

        for side, value in (
            ("before", "missing"),
            ("before", None),
            ("before", "wrong-runtime-name"),
            ("after", "missing"),
            ("after", None),
            ("after", "wrong-runtime-name"),
        ):
            with self.subTest(side=side, value=value):
                rejected = copy.deepcopy(plan)
                if value == "missing":
                    rejected["resource_changes"][0]["change"][side].pop(
                        "agent_runtime_name"
                    )
                else:
                    rejected["resource_changes"][0]["change"][side][
                        "agent_runtime_name"
                    ] = value
                result = validate_plan(rejected, manifest)
                self.assertEqual(result["reason_code"], "invalid_resource_identity")
                self.assertNotIn("wrong-runtime-name", json.dumps(result))

        for before, after in (
            ("wrong-runtime-name", "wrong-runtime-name"),
            ("wrong-runtime-name", "another-runtime-name"),
        ):
            with self.subTest(before=before, after=after):
                rejected = copy.deepcopy(plan)
                rejected["resource_changes"][0]["change"]["before"][
                    "agent_runtime_name"
                ] = before
                rejected["resource_changes"][0]["change"]["after"][
                    "agent_runtime_name"
                ] = after
                result = validate_plan(rejected, manifest)
                self.assertEqual(result["reason_code"], "invalid_resource_identity")
                self.assertNotIn("runtime-name", json.dumps(result))

        rejected = copy.deepcopy(plan)
        rejected["resource_changes"][0]["change"]["actions"] = ["no-op"]
        self.assert_reason("malformed_input", plan=rejected, manifest=manifest)

    def test_runtime_noop_without_identity_requires_known_unchanged_values(self):
        address = "aws_bedrockagentcore_agent_runtime.tollchat"
        fields = ("agent_runtime_artifact.code_configuration.code.s3.version_id",)
        plan = _plan([_mutation_change(address, fields, "no-op")])
        change = plan["resource_changes"][0]["change"]
        for side in ("before", "after"):
            change[side]["agent_runtime_name"] = "nova_toll_v2_development"
            change.pop(f"{side}_identity")
        manifest = _mutation_manifest(((address, "update", fields),))
        baseline = validate_plan(_plan([]), manifest)
        self.assertEqual(baseline["status"], "accepted")
        for applyable in (False, True):
            with self.subTest(applyable=applyable):
                plan["applyable"] = applyable
                self.assertEqual(validate_plan(plan, manifest), baseline)

        for key, value in (
            ("before_identity", {"agent_runtime_name": "nova_toll_v2_development"}),
            ("after_identity", {"agent_runtime_name": "nova_toll_v2_development"}),
            ("after_unknown", {"agent_runtime_name": True}),
            ("after_unknown", {fields[0]: True}),
            ("before_sensitive", {"agent_runtime_name": True}),
            ("after_sensitive", {"agent_runtime_name": True}),
            ("after_sensitive", {"environment_variables": True}),
            ("action_reason", "unreviewed-envelope"),
        ):
            with self.subTest(key=key, value=value):
                rejected = copy.deepcopy(plan)
                rejected["resource_changes"][0]["change"][key] = value
                self.assert_reason("malformed_input", plan=rejected, manifest=manifest)

        changed = copy.deepcopy(plan)
        changed["resource_changes"][0]["change"]["after"]["description"] = "changed"
        self.assert_reason("malformed_input", plan=changed, manifest=manifest)

        for value in (None, {}, {"agent_runtime_name": "wrong-runtime-name"}):
            with self.subTest(value=value):
                rejected = copy.deepcopy(plan)
                rejected["resource_changes"][0]["change"].update(
                    before=copy.deepcopy(value), after=copy.deepcopy(value)
                )
                self.assert_reason("invalid_resource_identity", plan=rejected, manifest=manifest)

    def test_rejects_derived_unknown_without_exact_provenance_or_producer(self):
        for label, kwargs in (
            ("missing_configuration", {"configuration": False}),
            ("wrong_expression_path", {"expression_path": "agent_runtime_artifact.code_configuration.code.s3.key"}),
            ("wrong_reference", {"reference": "aws_s3_object.agentcore.version_id.value"}),
            ("different_resource", {"resource_address": "aws_s3_object.agentcore"}),
        ):
            with self.subTest(label=label):
                plan, manifest = _derived_fixture(0, **kwargs)
                self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        plan["resource_changes"] = plan["resource_changes"][:1]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0, producer_action="no-op")
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        producer = plan["resource_changes"].pop()
        plan["resource_drift"] = [producer]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        producer = plan["resource_changes"][1]
        producer["address"] = "data.aws_s3_object.agentcore"
        producer["mode"] = "data"
        producer["change"]["actions"] = ["read"]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

    def test_rejects_arbitrary_unknown_contract_and_authorization_paths(self):
        plan, manifest = _derived_fixture(3)
        change = plan["resource_changes"][0]["change"]
        change["after_unknown"] = {"source_code_hash": True}
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(3)
        change = plan["resource_changes"][0]["change"]
        change["after_unknown"] = {"filename": True}
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(3)
        change = plan["resource_changes"][0]["change"]
        change["after_unknown"] = {"runtime": True}
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        expression = plan["configuration"]["root_module"]["resources"][0]["expressions"][
            "agent_runtime_artifact.code_configuration.code.s3.version_id"
        ]
        expression["references"].append("aws_s3_object.agentcore.source")
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        expression = plan["configuration"]["root_module"]["resources"][0]["expressions"][
            "agent_runtime_artifact.code_configuration.code.s3.version_id"
        ]
        expression["references"] = [
            "aws_s3_object.agentcore.version_id",
            "aws_s3_object.agentcore.version_id",
        ]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        plan["configuration"]["root_module"]["resources"][0]["expressions"][
            "agent_runtime_artifact.0.code_configuration.0.code.0.s3.0.version_id"
        ] = {
            "references": [
            "aws_s3_object.agentcore.version_id",
            "aws_s3_object.agentcore",
            ]
        }
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        for index, path in (
            (1, "agent_runtime_version[0]"),
            (2, "function_version[0]"),
            (3, "s3_object_version[0]"),
        ):
            with self.subTest(index=index, path=path):
                plan, manifest = _derived_fixture(index)
                plan["resource_changes"][0]["change"]["after_unknown"] = {path: True}
                self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        plan["resource_changes"][0]["change"]["after_unknown"] = {
            "agent_runtime_artifact[1].code_configuration[0].code[0].s3[0].version_id": True,
        }
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        for unknown in (
            {"layers": [True]},
            {"vpc_config": [{"subnet_ids": [True]}]},
        ):
            with self.subTest(unknown=unknown):
                plan, manifest = _derived_fixture(3)
                plan["resource_changes"][0]["change"]["after_unknown"] = unknown
                self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

    def test_ignores_non_contract_computed_unknowns_without_output_or_fingerprint_delta(self):
        plan = lambda_plan(last_modified="new")
        plan["resource_changes"][0]["change"]["after_unknown"] = {"last_modified": True}
        result = validate_plan(plan, lambda_manifest())
        baseline = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result, baseline)
        self.assertNotIn("last_modified", json.dumps(result))

    def test_ignores_non_contract_computed_unknowns_on_create_fingerprint(self):
        address = "aws_s3_object.agentcore"
        after = {
            "source": "payload",
            "source_hash": HASH,
            "bucket": "nova-toll-agentcore-903859731897",
            "key": "runtime/v2/agentcore-dev.zip",
        }
        baseline_resource = _resource_change(address, "create", None, after)
        unknown_resource = copy.deepcopy(baseline_resource)
        unknown_resource["change"]["after"]["etag"] = "computed"
        unknown_resource["change"]["after_unknown"] = {"etag": True}
        manifest = _mutation_manifest(((address, "create", ("source", "source_hash")),))
        baseline = validate_plan(_plan([baseline_resource]), manifest)
        result = validate_plan(_plan([unknown_resource]), manifest)
        self.assertEqual(result, baseline)
        self.assertNotIn("etag", json.dumps(result))

    def test_derived_unknown_provenance_is_independent_of_resource_order(self):
        plan, manifest = _derived_fixture(2)
        first = validate_plan(plan, manifest)
        reordered = copy.deepcopy(plan)
        reordered["resource_changes"].reverse()
        second = validate_plan(reordered, manifest)
        self.assertEqual(first, second)

    def test_accepts_one_fixture_for_every_contract_entry(self):
        for address, spec in CONTRACT.items():
            if spec.operation_class.startswith("agentcore-trace-"):
                continue
            action = spec.actions[0]
            timed = address.startswith('aws_scheduler_schedule.timed_checks["') or address in {
                "aws_lambda_function.timed_checks",
                "aws_s3_object.timed_checks",
            }
            if address in {"aws_s3_object.agentcore", "aws_s3_object.tollchat_proxy"}:
                action = "update"
                fields = ("source_hash",)
            elif address.startswith('aws_scheduler_schedule.timed_checks["'):
                fields = ("schedule_expression",)
            elif address in {
                "aws_lambda_function.tollchat_proxy",
                "aws_lambda_function.timed_checks",
            }:
                fields = ("s3_object_version", "source_code_hash")
            elif spec.operation_class == "lambda-code":
                fields = ("filename", "source_code_hash")
            elif address == ALARM_ADDRESS:
                fields = spec.fields
            elif address in {
                "aws_s3_object.index",
                "aws_s3_object.faq",
                "aws_s3_object.privacy",
            }:
                fields = ("content",)
            else:
                fields = (spec.fields[0],)
            before = None if action == "create" else {}
            after = {}
            if address.startswith('aws_scheduler_schedule.timed_checks["'):
                after = _timed_schedule_plan_value(address)
                before = copy.deepcopy(after)
                before["schedule_expression"] = "cron(0 0 ? * SUN *)"
            if before is not None:
                for field in fields:
                    _set_path(before, field, "old")
            for field in fields:
                if not address.startswith('aws_scheduler_schedule.timed_checks["'):
                    _set_path(after, field, "new")
            for field, value in spec.create_identity:
                if before is not None:
                    before[field] = value
                after[field] = value
            if address in {
                "aws_s3_object.index",
                "aws_s3_object.faq",
                "aws_s3_object.privacy",
            }:
                after["content"] = _trace_notice_contents()[address.rsplit(".", 1)[-1]]
            if spec.operation_class.startswith("telemetry-"):
                after = _telemetry_value(address)
                fields = tuple(sorted(after))
            if address in {PUBLISHER_ADDRESS, ALARM_ADDRESS}:
                plan = _plan(
                    [
                        copy.deepcopy(
                            next(
                                record
                                for record in publisher_and_alarm_plan()[
                                    "resource_changes"
                                ]
                        if record["address"] == address
                            )
                        )
                    ]
                )
            else:
                plan = _plan([_resource_change(address, action, before, after)])
            manifest = {
                **manifest_header(timed=timed),
                "mutations": [
                    {
                    "address": address,
                    "action": action,
                    "operation_class": spec.operation_class,
                    "changed_fields": list(fields),
                    }
                ],
                "permissions": [
                    {
                    "address": address,
                    "action": permission.action,
                    "resource": permission.resources[0],
                    "conditions": dict(permission.conditions),
                    }
                    for permission in spec.permissions
                ],
            }
            result = validate_plan(plan, manifest)
            self.assertEqual(result["status"], "accepted", address)
            if spec.operation_class == "telemetry-alarm":
                normalized = copy.deepcopy(plan)
                normalized["resource_changes"][0]["change"]["after"]["alarm_actions"] = None
                if not after["dimensions"]:
                    normalized["resource_changes"][0]["change"]["after"]["dimensions"] = None
                self.assertEqual(validate_plan(normalized, manifest)["status"], "accepted", address)
            if spec.operation_class.startswith("telemetry-"):
                for field in after:
                    mutant = copy.deepcopy(plan)
                    mutant["resource_changes"][0]["change"]["after"][field] = "unreviewed"
                    self.assertEqual(validate_plan(mutant, manifest)["status"], "rejected", (address, field))
            if address == "aws_s3_object.agentcore":
                undeclared = _plan(
                    [
                        _resource_change(
                            address,
                            "update",
                            {
                                "source": "old",
                                "source_hash": "old",
                                **dict(spec.create_identity),
                            },
                            {
                                "source": "new",
                                "source_hash": "new",
                                **dict(spec.create_identity),
                            },
                        )
                    ]
                )
                self.assert_reason(
                    "manifest_mutation_mismatch", plan=undeclared, manifest=manifest
                )

    def test_agentcore_trace_runtime_policy_only_adds_required_permission(self):
        address = "aws_iam_role_policy.tollchat_runtime"
        identity = {
            "id": "nova-toll-v2-agentcore-runtime-dev:nova-toll-v2-agentcore-runtime-dev",
            "name": "nova-toll-v2-agentcore-runtime-dev",
            "role": "nova-toll-v2-agentcore-runtime-dev",
        }
        baseline = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "ReadArtifact",
                    "Effect": "Allow",
                    "Action": "s3:GetObjectVersion",
                    "Resource": "arn:aws:s3:::nova-toll-agentcore-903859731897/runtime/v2/agentcore-dev.zip",
                }
            ],
        }
        trace_statement = {
            "Sid": "EnableUnifiedRuntimeTraceDelivery",
            "Effect": "Allow",
            "Action": "logs:PutResourcePolicy",
            "Resource": "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-*",
            "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
        }
        before = {**identity, "policy": json.dumps(baseline)}
        after = {
            **identity,
            "policy": json.dumps(
                {**baseline, "Statement": [*baseline["Statement"], trace_statement]}
            ),
        }
        plan = _plan([_resource_change(address, "update", before, after)])
        manifest = _mutation_manifest(
            [(address, "update", ("policy",))]
        )
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
        tampered = copy.deepcopy(plan)
        tampered_statement = json.loads(tampered["resource_changes"][0]["change"]["after"]["policy"])
        tampered_statement["Statement"][-1]["Action"] = "logs:*"
        tampered["resource_changes"][0]["change"]["after"]["policy"] = json.dumps(tampered_statement)
        self.assertEqual(
            validate_plan(tampered, manifest)["reason_code"],
            "unsupported_field_delta",
        )

    def test_agentcore_trace_initial_and_recovery_fixtures_are_finite(self):
        subscriptions = {
            'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]': {
                "distribution": "ByLogStream",
                "emit_system_fields": None,
                "region": "us-east-1",
                "name": "nova-toll-v2-agentcore-traces-dev",
                "log_group_name": "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
                "destination_arn": TRACE_FIREHOSE,
                "role_arn": TRACE_LOGS_ROLE,
                "filter_pattern": TRACE_FILTER,
            },
            'aws_cloudwatch_log_subscription_filter.agentcore_traces["preview"]': {
                "distribution": "ByLogStream",
                "emit_system_fields": None,
                "region": "us-east-1",
                "name": "nova-toll-v2-agentcore-traces-dev",
                "log_group_name": "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview",
                "destination_arn": TRACE_FIREHOSE,
                "role_arn": TRACE_LOGS_ROLE,
                "filter_pattern": TRACE_FILTER,
            },
        }
        baseline_rules = [
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
        trace_rule = {
            "id": "expire-agentcore-traces",
            "status": "Enabled",
            "filter": [{"prefix": TRACE_PREFIX}],
            "expiration": [{"days": 7}],
            "abort_incomplete_multipart_upload": [{"days_after_initiation": 1}],
        }
        runtime_before = {
            "DB_HOST": "database",
            "DB_PORT": "5432",
            "PRICING_DB_USER": "pricing",
        }
        runtime_identity = {
            "agent_runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl",
            "agent_runtime_id": "nova_toll_v2_development-Y69XBf88Bl",
            "agent_runtime_name": "nova_toll_v2_development",
            "region": "us-east-1",
            "role_arn": "arn:aws:iam::903859731897:role/nova-toll-v2-agentcore-runtime-dev",
        }
        initial = {
            "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]": {
                "name": "nova-toll-v2-agentcore-traces-dev",
                "destination": "extended_s3",
                "elasticsearch_configuration": [],
                "extended_s3_configuration": [
                    {
                        "role_arn": TRACE_FIREHOSE_ROLE,
                        "bucket_arn": "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-903859731897-dev",
                        "prefix": TRACE_PREFIX,
                        "buffering_interval": 60,
                        "buffering_size": 5,
                        "compression_format": "UNCOMPRESSED",
                        "custom_time_zone": "UTC",
                        "data_format_conversion_configuration": [],
                        "dynamic_partitioning_configuration": [],
                        "error_output_prefix": None,
                        "file_extension": None,
                        "kms_key_arn": TRACE_KMS_KEY,
                        "processing_configuration": [
                            {
                                "enabled": True,
                                "processors": [
                                    {"type": "Decompression", "parameters": []},
                                    {
                                        "type": "CloudWatchLogProcessing",
                                        "parameters": [
                                            {
                                                "parameter_name": "DataMessageExtraction",
                                                "parameter_value": "true",
                                            }
                                        ],
                                    },
                                    {
                                        "type": "AppendDelimiterToRecord",
                                        "parameters": [],
                                    },
                                ],
                            }
                        ],
                        "s3_backup_configuration": [],
                        "s3_backup_mode": "Disabled",
                    }
                ],
                "http_endpoint_configuration": [],
                "iceberg_configuration": [],
                "kinesis_source_configuration": [],
                "msk_source_configuration": [],
                "opensearch_configuration": [],
                "opensearchserverless_configuration": [],
                "redshift_configuration": [],
                "region": "us-east-1",
                "server_side_encryption": [],
                "snowflake_configuration": [],
                "splunk_configuration": [],
                "tags": None,
                "tags_all": TRACE_TAGS,
                "timeouts": None,
            },
            **subscriptions,
            **{
                f"aws_s3_object.{name}": {
                    "bucket": "tollchat-site-903859731897-dev",
                    "key": {
                        "index": "index.html",
                        "faq": "faq.html",
                        "privacy": "privacy.txt",
                    }[name],
                    "content": content,
                    "source": None,
                    "source_hash": None,
                }
                for name, content in _trace_notice_contents().items()
            },
            "aws_glue_catalog_table.agentcore_traces[0]": {
                "database_name": "tollchat_agent_reports_development",
                "description": None,
                "name": "agentcore_traces",
                "open_table_format_input": [],
                "owner": None,
                "table_type": "EXTERNAL_TABLE",
                "parameters": {"EXTERNAL": "TRUE"},
                "partition_keys": [],
                "region": "us-east-1",
                "retention": None,
                "storage_descriptor": [
                    {
                        "additional_locations": None,
                        "bucket_columns": None,
                        "compressed": None,
                        "location": "s3://aws-waf-logs-tollchat-agent-reports-903859731897-dev/agentcore-traces/",
                        "input_format": "org.apache.hadoop.mapred.TextInputFormat",
                        "number_of_buckets": None,
                        "output_format": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                        "parameters": None,
                        "columns": [
                            {
                                "comment": None,
                                "name": "raw_json",
                                "parameters": None,
                                "type": "string",
                            }
                        ],
                        "schema_reference": [],
                        "ser_de_info": [
                            {
                                "name": None,
                                "serialization_library": "org.apache.hadoop.hive.serde2.RegexSerDe",
                                "parameters": {"input.regex": "^(.*)$"},
                            }
                        ],
                        "skewed_info": [],
                        "sort_columns": [],
                        "stored_as_sub_directories": None,
                    }
                ],
                "target_table": [],
                "view_definition": [],
                "view_expanded_text": None,
                "view_original_text": None,
            },
            "aws_athena_named_query.agentcore_trace_summary[0]": {
                "database": "tollchat_agent_reports_development",
                "name": "agentcore-trace-summary-dev",
                "workgroup": "tollchat-agent-reports-dev",
                "description": "Bounded development trace outcome summary",
                "query": TRACE_QUERY,
                "region": "us-east-1",
            },
            "aws_s3_bucket_lifecycle_configuration.agent_measurement": {
                "rule": [*baseline_rules, trace_rule],
            },
            "aws_bedrockagentcore_agent_runtime.tollchat": {
                **runtime_identity,
                "environment_variables": {
                    **runtime_before,
                    "UNIFIED_TRACES_DESTINATION_ENABLED": "true",
                },
            },
        }
        actions = {
            address: "update"
            if address
            in {
                "aws_s3_bucket_lifecycle_configuration.agent_measurement",
                "aws_bedrockagentcore_agent_runtime.tollchat",
                "aws_s3_object.index",
                "aws_s3_object.faq",
                "aws_s3_object.privacy",
            }
            else "create"
            for address in initial
        }

        def manifest_for(values, chosen_actions):
            return _mutation_manifest(
                [
                    (
                        address,
                        chosen_actions[address],
                        ("environment_variables",)
                        if address == "aws_bedrockagentcore_agent_runtime.tollchat"
                        else ("content", "source", "source_hash")
                        if address.startswith("aws_s3_object.")
                        else tuple(
                            field
                            for field in CONTRACT[address].fields
                            if field not in {"tags", "timeouts"}
                        )
                        if address
                        == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
                        and chosen_actions[address] == "delete"
                        else CONTRACT[address].fields,
                    )
                    for address in values
                ]
            )

        initial_plan = _plan(
            [
                _resource_change(
                    address,
                    actions[address],
                    {"rule": baseline_rules}
                    if address
                    == "aws_s3_bucket_lifecycle_configuration.agent_measurement"
                    else {
                        **runtime_identity,
                        "environment_variables": runtime_before,
                    }
                    if address == "aws_bedrockagentcore_agent_runtime.tollchat"
                    else {
                        **dict(CONTRACT[address].create_identity),
                        "content": None,
                        "source": f"../agent/{address.rsplit('.', 1)[-1]}",
                        "source_hash": "old",
                    }
                    if address.startswith("aws_s3_object.")
                    else None,
                    value,
                )
                for address, value in initial.items()
            ]
        )
        for resource in initial_plan["resource_changes"]:
            if resource["change"]["actions"] == ["create"]:
                resource["change"]["before_sensitive"] = False
                if CONTRACT[resource["address"]].provider_change_identity:
                    resource["change"].pop("before_identity")
        firehose_create = next(
            item
            for item in initial_plan["resource_changes"]
            if item["address"]
            == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
        )["change"]
        firehose_create["after_identity"] = {"arn": None}
        for resource in initial_plan["resource_changes"]:
            if resource["address"].startswith(
                'aws_cloudwatch_log_subscription_filter.agentcore_traces["'
            ):
                resource["change"]["after"] = copy.deepcopy(resource["change"]["after"])
                resource["change"]["after"].pop("destination_arn")
                resource["change"]["after_unknown"] = {"destination_arn": True}
                resource["change"]["after_identity"] = {
                    "account_id": None,
                    "log_group_name": None,
                    "name": None,
                    "region": None,
                }
        initial_plan["configuration"] = {
            "root_module": {
                "resources": [
                    {
                        "address": "aws_cloudwatch_log_subscription_filter.agentcore_traces",
                        "expressions": {
                            "destination_arn": {
                                "references": [
                                    "aws_kinesis_firehose_delivery_stream.agentcore_traces[0].arn",
                                    "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]",
                                    "aws_kinesis_firehose_delivery_stream.agentcore_traces",
                                ]
                            }
                        },
                    }
                ]
            }
        }
        firehose_create["after_unknown"] = {
            "arn": True,
            "destination_id": True,
            "extended_s3_configuration": [{"cloudwatch_logging_options": True}],
            "id": True,
            "version_id": True,
        }
        initial_result = validate_plan(initial_plan, manifest_for(initial, actions))
        self.assertEqual(initial_result["status"], "accepted", initial_result)

        partitioned_catalog = copy.deepcopy(initial_plan)
        next(
            item
            for item in partitioned_catalog["resource_changes"]
            if item["address"] == "aws_glue_catalog_table.agentcore_traces[0]"
        )["change"]["after"]["partition_keys"] = [
            {"name": "unexpected", "type": "string"}
        ]
        self.assertEqual(
            validate_plan(
                partitioned_catalog, manifest_for(initial, actions)
            )["reason_code"],
            "unsupported_field_delta",
        )

        recovery_values = {
            address: value
            for address, value in initial.items()
            if address
            not in {
                "aws_s3_bucket_lifecycle_configuration.agent_measurement",
                "aws_bedrockagentcore_agent_runtime.tollchat",
            }
            and not address.startswith("aws_s3_object.")
        }
        recovery_actions = {address: "delete" for address in recovery_values}
        recovery_values["aws_bedrockagentcore_agent_runtime.tollchat"] = {
            **runtime_identity,
            "environment_variables": runtime_before
        }
        recovery_actions["aws_bedrockagentcore_agent_runtime.tollchat"] = "update"
        recovery_plan = _plan(
            [
                _resource_change(
                    address,
                    recovery_actions[address],
                    initial[address]
                    if recovery_actions[address] == "delete"
                    else initial[address],
                    None if recovery_actions[address] == "delete" else value,
                )
                for address, value in recovery_values.items()
            ]
        )
        for resource in recovery_plan["resource_changes"]:
            if resource["change"]["actions"] == ["delete"]:
                resource["change"]["after_sensitive"] = False
                if CONTRACT[resource["address"]].provider_change_identity:
                    resource["change"].pop("after_identity")
        firehose_delete = next(
            item
            for item in recovery_plan["resource_changes"]
            if item["address"]
            == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
        )["change"]
        firehose_delete["before"].update(
            {
                "arn": TRACE_FIREHOSE,
                "destination_id": "destinationId-000000000001",
                "id": "arn:aws:firehose:us-east-1:903859731897:deliverystream/nova-toll-v2-agentcore-traces-dev",
                "version_id": "1",
            }
        )
        firehose_delete["before"]["extended_s3_configuration"][0][
            "cloudwatch_logging_options"
        ] = []
        firehose_delete["before_identity"] = {"arn": TRACE_FIREHOSE}
        recovery_result = validate_plan(
            recovery_plan, manifest_for(recovery_values, recovery_actions)
        )
        self.assertEqual(recovery_result["status"], "accepted", recovery_result)

        immediate_lifecycle_removal = _plan(
            [
                _resource_change(
                    "aws_s3_bucket_lifecycle_configuration.agent_measurement",
                    "update",
                    initial["aws_s3_bucket_lifecycle_configuration.agent_measurement"],
                    {"rule": baseline_rules},
                )
            ]
        )
        self.assertEqual(
            validate_plan(
                immediate_lifecycle_removal,
                _mutation_manifest(
                    (
                        (
                            "aws_s3_bucket_lifecycle_configuration.agent_measurement",
                            "update",
                            ("rule",),
                        ),
                    )
                ),
            )["reason_code"],
            "unsupported_field_delta",
        )

        wrong_identity = copy.deepcopy(recovery_plan)
        next(
            item
            for item in wrong_identity["resource_changes"]
            if item["address"]
            == 'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]'
        )["change"]["before_identity"]["name"] = "other"
        self.assertEqual(
            validate_plan(
                wrong_identity, manifest_for(recovery_values, recovery_actions)
            )["reason_code"],
            "invalid_resource_identity",
        )

        retry = copy.deepcopy(initial_plan)
        for name, content in _trace_notice_contents().items():
            address = f"aws_s3_object.{name}"
            index = next(
                i
                for i, item in enumerate(retry["resource_changes"])
                if item["address"] == address
            )
            notice = {
                "bucket": "tollchat-site-903859731897-dev",
                "key": {
                    "index": "index.html",
                    "faq": "faq.html",
                    "privacy": "privacy.txt",
                }[name],
                "content": content,
                "source": None,
                "source_hash": None,
            }
            retry["resource_changes"][index] = _resource_change(
                address, "no-op", notice, copy.deepcopy(notice)
            )
        retry_manifest = manifest_for(
            {
                address: value
                for address, value in initial.items()
                if not address.startswith("aws_s3_object.")
            },
            actions,
        )
        self.assertEqual(validate_plan(retry, retry_manifest)["status"], "accepted")
        # The AWS provider normalizes absent S3 source fields to empty strings.
        normalized_retry = copy.deepcopy(retry)
        for item in normalized_retry["resource_changes"]:
            if item["address"] in TRACE_NOTICE_DIGESTS:
                for side in ("before", "after"):
                    item["change"][side].update(source="", source_hash="")
        self.assertEqual(
            validate_plan(normalized_retry, retry_manifest)["status"], "accepted"
        )
        for field, attacker in (
            ("bucket", "attacker-bucket"),
            ("key", "wrong-key"),
            ("source", "attacker"),
            ("source_hash", "attacker"),
        ):
            false_retry = copy.deepcopy(retry)
            change = next(
                item
                for item in false_retry["resource_changes"]
                if item["address"] == "aws_s3_object.index"
            )["change"]
            change["before"][field] = attacker
            change["after"][field] = attacker
            self.assertEqual(
                validate_plan(false_retry, retry_manifest)["reason_code"],
                "invalid_resource_identity"
                if field in {"bucket", "key"}
                else "unsupported_field_delta",
            )

        site_only = _plan(
            [
                _resource_change(
                    "aws_s3_object.index",
                    "update",
                    {
                        "bucket": "tollchat-site-903859731897-dev",
                        "key": "index.html",
                        "content": _trace_notice_contents()["index"],
                    },
                    {
                        "bucket": "tollchat-site-903859731897-dev",
                        "key": "index.html",
                        "content": "No server-side archive exists.",
                    },
                )
            ]
        )
        self.assertEqual(
            validate_plan(
                site_only,
                _mutation_manifest((("aws_s3_object.index", "update", ("content",)),)),
            )["reason_code"],
            "unsupported_field_delta",
        )

        widened = manifest_for(initial, actions)
        next(
            item for item in widened["permissions"] if item["action"] == "iam:PassRole"
        )["conditions"] = {"iam:PassedToService": "lambda.amazonaws.com"}
        self.assertEqual(
            validate_plan(initial_plan, widened)["reason_code"], "invalid_permission"
        )

        for address, side, path, value in (
            (
                "aws_s3_bucket_lifecycle_configuration.agent_measurement",
                "after",
                ("rule", 0, "filter", 0, "prefix"),
                "other/",
            ),
            (
                "aws_bedrockagentcore_agent_runtime.tollchat",
                "after",
                ("environment_variables", "DB_HOST"),
                "other",
            ),
            (
                "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]",
                "after",
                ("extended_s3_configuration", 0, "kms_key_arn"),
                "wrong",
            ),
            (
                "aws_glue_catalog_table.agentcore_traces[0]",
                "after",
                ("storage_descriptor", 0, "columns", 0, "name"),
                "other",
            ),
            (
                "aws_athena_named_query.agentcore_trace_summary[0]",
                "after",
                ("query",),
                "SELECT 1",
            ),
        ):
            rejected = copy.deepcopy(initial_plan)
            node = next(
                item
                for item in rejected["resource_changes"]
                if item["address"] == address
            )["change"][side]
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
            self.assertEqual(
                validate_plan(rejected, manifest_for(initial, actions))["reason_code"],
                "unsupported_field_delta",
            )

        wrong_recovery = copy.deepcopy(recovery_plan)
        next(
            item
            for item in wrong_recovery["resource_changes"]
            if item["address"]
            == 'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]'
        )["change"]["before"]["role_arn"] = "wrong"
        self.assertEqual(
            validate_plan(
                wrong_recovery, manifest_for(recovery_values, recovery_actions)
            )["reason_code"],
            "unsupported_field_delta",
        )

        false_notice = copy.deepcopy(initial_plan)
        next(
            item
            for item in false_notice["resource_changes"]
            if item["address"] == "aws_s3_object.index"
        )["change"]["after"]["content"] = "No server-side archive exists."
        self.assertEqual(
            validate_plan(false_notice, manifest_for(initial, actions))["reason_code"],
            "unsupported_field_delta",
        )
        altered_tags = copy.deepcopy(initial_plan)
        next(
            item
            for item in altered_tags["resource_changes"]
            if item["address"]
            == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
        )["change"]["after"]["tags_all"]["environment"] = "other"
        self.assertEqual(
            validate_plan(altered_tags, manifest_for(initial, actions))["reason_code"],
            "unsupported_field_delta",
        )
        altered_default = copy.deepcopy(initial_plan)
        next(
            item
            for item in altered_default["resource_changes"]
            if item["address"]
            == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
        )["change"]["after"]["extended_s3_configuration"][0]["buffering_size"] = 6
        self.assertEqual(
            validate_plan(altered_default, manifest_for(initial, actions))[
                "reason_code"
            ],
            "unsupported_field_delta",
        )

        for address, field, path, attacker in (
            (
                "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]",
                "extended_s3_configuration",
                ("extended_s3_configuration", 0, "bucket_arn"),
                "arn:aws:s3:::attacker",
            ),
            (
                "aws_glue_catalog_table.agentcore_traces[0]",
                "storage_descriptor",
                ("storage_descriptor", 0, "location"),
                "s3://attacker/",
            ),
            (
                "aws_athena_named_query.agentcore_trace_summary[0]",
                "query",
                ("query",),
                "SELECT 1",
            ),
        ):
            before = copy.deepcopy(initial[address])
            node = before
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = attacker
            rejected = _plan(
                [_resource_change(address, "update", before, initial[address])]
            )
            self.assertEqual(
                validate_plan(
                    rejected, _mutation_manifest(((address, "update", (field,)),))
                )["reason_code"],
                "unsupported_field_delta",
            )

        reordered = _plan(
            [
                _resource_change(
                    "aws_s3_bucket_lifecycle_configuration.agent_measurement",
                    "update",
                    {"rule": list(reversed(baseline_rules))},
                    {"rule": list(reversed([*baseline_rules, trace_rule]))},
                )
            ]
        )
        self.assertEqual(
            validate_plan(
                reordered,
                _mutation_manifest(
                    (
                        (
                            "aws_s3_bucket_lifecycle_configuration.agent_measurement",
                            "update",
                            ("rule",),
                        ),
                    )
                ),
            )["status"],
            "accepted",
        )

    def test_slot_preparation_uses_private_failure_reporting(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-development-delivery-privileged.yml"
        ).read_text()
        self.assertIn('run_private_stage "plan" "$PLAN_LOG" "$PLAN_LOG"', workflow)
        self.assertIn("release_blue_green.py prepare-plan", workflow)
        self.assertIn("release_blue_green.py finish", workflow)
        self.assertIn("jq '{deployment,recovery,active,probes,releases,recovery_record}'", workflow)
        self.assertNotIn('cat "$PLAN_LOG"', workflow)

    def test_existing_trace_subscription_identity_pins_account_and_region(self):
        address = 'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]'
        values = dict(CONTRACT[address].create_identity)
        record = _resource_change(address, "no-op", values, copy.deepcopy(values))
        identity = {
            "account_id": "903859731897",
            "region": "us-east-1",
            "log_group_name": "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
            "name": "nova-toll-v2-agentcore-traces-dev",
        }
        for side in ("before_identity", "after_identity"):
            record["change"][side] = copy.deepcopy(identity)
        plan = _plan([record])
        manifest = _mutation_manifest(())
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
        for side in ("before_identity", "after_identity"):
            for field in ("account_id", "region"):
                invalid = copy.deepcopy(plan)
                invalid["resource_changes"][0]["change"][side][field] = "wrong"
                self.assertEqual(
                    validate_plan(invalid, manifest)["reason_code"],
                    "invalid_resource_identity",
                )

    def test_trace_notices_allow_legacy_noops_before_rollout(self):
        keys = {"index": "index.html", "faq": "faq.html", "privacy": "privacy.txt"}
        plan = _plan(
            [
                _resource_change(
                    f"aws_s3_object.{name}",
                    "no-op",
                    {
                        "bucket": "tollchat-site-903859731897-dev",
                        "key": key,
                        "content": None,
                        "source": f"../site/{key}",
                        "source_hash": "legacy",
                    },
                    {
                        "bucket": "tollchat-site-903859731897-dev",
                        "key": key,
                        "content": None,
                        "source": f"../site/{key}",
                        "source_hash": "legacy",
                    },
                )
                for name, key in keys.items()
            ]
        )

        for applyable in (False, True):
            with self.subTest(applyable=applyable):
                plan["applyable"] = applyable
                self.assertEqual(
                    validate_plan(plan, _mutation_manifest(()))["status"], "accepted"
                )

        for field, value in (("complete", False), ("errored", True)):
            with self.subTest(field=field):
                rejected = copy.deepcopy(plan)
                rejected[field] = value
                self.assert_reason("malformed_input", plan=rejected, manifest=_mutation_manifest(()))

        plan["resource_changes"].extend(lambda_plan()["resource_changes"])
        self.assertEqual(validate_plan(plan, lambda_manifest())["status"], "accepted")
        plan["applyable"] = False
        self.assert_reason("malformed_input", plan=plan, manifest=lambda_manifest())

    def test_committed_development_manifest_covers_full_package_graph(self):
        manifest = json.loads(
            (Path(__file__).resolve().parent / "development-release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        expected_mutations = {
            "aws_lambda_function.loader": ("lambda-code", ("filename", "source_code_hash")),
            "aws_lambda_function.publisher": ("lambda-code", ("source_code_hash",)),
            "aws_s3_object.agentcore": ("artifact-upload", ("source_hash",)),
            "aws_s3_object.tollchat_proxy": ("artifact-upload", ("source_hash",)),
            'aws_s3_object.site_assets["coverage-locations.json"]': ("site-asset-upload", ("source_hash",)),
            "aws_lambda_function.tollchat_proxy": ("lambda-code", ("s3_object_version", "source_code_hash")),
            "aws_s3_object.timed_checks": ("artifact-upload", ("source_hash",)),
            "aws_lambda_function.timed_checks": ("lambda-code", ("s3_object_version", "source_code_hash")),
            "aws_lambda_alias.tollchat_live": ("lambda-alias", ("function_version",)),
            "aws_bedrockagentcore_agent_runtime.tollchat": (
                "agentcore-code",
                ("agent_runtime_artifact.code_configuration.code.s3.version_id",),
            ),
            "aws_bedrockagentcore_agent_runtime_endpoint.tollchat": (
                "agentcore-endpoint",
                ("agent_runtime_version",),
            ),
            "aws_iam_role_policy.publisher": ("publisher-inline-policy", ("policy",)),
            "aws_cloudwatch_metric_alarm.report_generation_freshness": (
                "report-freshness-alarm",
                ("alarm_description", "dimensions"),
            ),
        }
        committed_updates = tuple(expected_mutations)
        expected_mutations.update(
            {
                "aws_iam_role_policy.tollchat_runtime": (
                    "agentcore-trace-runtime-policy",
                    ("policy",),
                ),
                "aws_s3_object.index": (
                    "site-object-upload",
                    ("content", "source", "source_hash"),
            ),
                "aws_s3_object.faq": (
                    "site-object-upload",
                    ("content", "source", "source_hash"),
            ),
                "aws_s3_object.privacy": (
                    "site-object-upload",
                    ("content", "source", "source_hash"),
            ),
                "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]": (
                    "agentcore-trace-firehose",
            (
                        "destination",
                        "elasticsearch_configuration",
                        "extended_s3_configuration",
                        "http_endpoint_configuration",
                        "iceberg_configuration",
                        "kinesis_source_configuration",
                        "msk_source_configuration",
                        "name",
                        "opensearch_configuration",
                        "opensearchserverless_configuration",
                        "redshift_configuration",
                        "region",
                        "server_side_encryption",
                        "snowflake_configuration",
                        "splunk_configuration",
                        "tags",
                        "tags_all",
                        "timeouts",
            ),
            ),
                'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]': (
                    "agentcore-trace-subscription",
            (
                        "destination_arn",
                        "filter_pattern",
                        "log_group_name",
                        "name",
                        "role_arn",
            ),
            ),
                'aws_cloudwatch_log_subscription_filter.agentcore_traces["preview"]': (
                    "agentcore-trace-subscription",
            (
                        "destination_arn",
                        "filter_pattern",
                        "log_group_name",
                        "name",
                        "role_arn",
            ),
            ),
                "aws_s3_bucket_lifecycle_configuration.agent_measurement": (
                    "agentcore-trace-retention",
                    ("rule",),
            ),
                "aws_glue_catalog_table.agentcore_traces[0]": (
                    "agentcore-trace-catalog",
            (
                        "database_name",
                        "name",
                        "parameters",
                        "storage_descriptor",
                        "table_type",
                    ),
                ),
                "aws_athena_named_query.agentcore_trace_summary[0]": (
                    "agentcore-trace-query",
                    ("database", "description", "name", "query", "workgroup"),
            ),
        }
        )
        expected_mutations["aws_bedrockagentcore_agent_runtime.tollchat"] = ("agentcore-code", ("agent_runtime_artifact.code_configuration.code.s3.version_id",))
        for name in ("index", "faq", "privacy"):
            expected_mutations[f"aws_s3_object.{name}"] = ("site-object-upload", ("content",))
        for address, spec in CONTRACT.items():
            if spec.operation_class.startswith("telemetry-"):
                fields = {"telemetry-log-protection": ("log_group_name", "policy_document"), "telemetry-failure-metric": ("log_group_name", "metric_transformation", "name", "pattern"), "telemetry-alarm": ("alarm_actions", "alarm_description", "alarm_name", "comparison_operator", "dimensions", "evaluation_periods", "metric_name", "namespace", "period", "statistic", "tags", "threshold", "treat_missing_data")}[spec.operation_class]
                expected_mutations[address] = (spec.operation_class, fields)
        expected_mutations.update({
            "aws_cloudfront_function.public_report_routes": ("cloudfront-code", ("code",)),
            "aws_s3_object.evals": ("site-object-upload", ("cache_control", "content", "content_type", "source", "source_hash")),
            **{f'aws_s3_object.site_assets["{name}"]': ("site-asset-upload", ("cache_control", "content_type", "source", "source_hash")) for name in ("evals.css", "evals.mjs")},
        })
        actual_mutations = {
            record["address"]: (
                record["operation_class"],
                tuple(record["changed_fields"]),
            )
            for record in manifest["mutations"]
        }
        assert actual_mutations == expected_mutations
        actual_permissions = {
            (
                record["address"],
                record["action"],
                record["resource"],
                tuple(sorted(record["conditions"].items())),
            )
            for record in manifest["permissions"]
        }
        committed_permission_resources = {
            (
                "aws_lambda_alias.tollchat_live",
                "lambda:UpdateAlias",
            ): "arn:aws:lambda:us-east-1:903859731897:function:tollchat-v2-chat-proxy-dev",
        }
        expected_permissions = {
            (
                address,
                permission.action,
                committed_permission_resources.get(
                    (address, permission.action), resource
                ),
                tuple(sorted(permission.conditions.items())),
            )
            for address in expected_mutations
            for permission in CONTRACT[address].permissions
            for resource in (
                permission.resources
                if address == "aws_glue_catalog_table.agentcore_traces[0]"
                else permission.resources[:1]
            )
        }
        assert actual_permissions == expected_permissions

        def update(address):
            if address in {PUBLISHER_ADDRESS, ALARM_ADDRESS}:
                return copy.deepcopy(next(
                    record for record in publisher_and_alarm_plan()["resource_changes"]
                    if record["address"] == address
                ))
            fields = expected_mutations[address][1]
            spec = CONTRACT[address]
            before, after = {}, {}
            for field in fields:
                _set_path(before, field, f"{address}:old")
                _set_path(after, field, f"{address}:new")
            for field, value in spec.create_identity:
                before[field] = after[field] = value
            if address == "aws_bedrockagentcore_agent_runtime.tollchat":
                runtime_identity = {
                    "agent_runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl",
                    "agent_runtime_id": "nova_toll_v2_development-Y69XBf88Bl",
                    "agent_runtime_name": "nova_toll_v2_development",
                    "region": "us-east-1",
                    "role_arn": "arn:aws:iam::903859731897:role/nova-toll-v2-agentcore-runtime-dev",
                }
                before.update(runtime_identity)
                after.update(runtime_identity)
                before["environment_variables"] = {
                    "DB_HOST": "database",
                    "PRICING_DB_USER": "pricing",
                    "UNIFIED_TRACES_DESTINATION_ENABLED": "true",
                }
                after["environment_variables"] = dict(before["environment_variables"])
                before["environment_variables"].update(TOLLCHAT_TELEMETRY_GUARDRAIL_ID="testid", TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION="1")
                after["environment_variables"] = dict(before["environment_variables"])
            return _resource_change(address, "update", before, after)

        plan = _plan([update(address) for address in committed_updates])
        accepted = validate_plan(plan, manifest)
        self.assertEqual(accepted["status"], "accepted", accepted)
        self.assertEqual(accepted["reason_code"], "ok")
        self.assertEqual(accepted["addresses"], list(committed_updates))

        missing_permission = copy.deepcopy(manifest)
        missing_permission["permissions"] = [
            record
            for record in missing_permission["permissions"]
            if record["address"] != "aws_lambda_function.loader"
        ]
        rejected = validate_plan(plan, missing_permission)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reason_code"], "missing_permission")

        widened_permission = copy.deepcopy(manifest)
        next(
            record
            for record in widened_permission["permissions"]
            if record["address"] == "aws_s3_object.agentcore"
        )["resource"] = "*"
        rejected = validate_plan(plan, widened_permission)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reason_code"], "invalid_permission")

    def test_dashboard_create_computed_acl_requires_omitted_configuration(self):
        manifest = json.loads((Path(__file__).parent / "development-release-manifest.json").read_text())
        for address in ("aws_s3_object.evals", 'aws_s3_object.site_assets["evals.css"]', 'aws_s3_object.site_assets["evals.mjs"]'):
            spec = CONTRACT[address]
            after = {**dict(spec.create_identity), **{field: None for field in spec.fields}}
            resource = _resource_change(address, "create", None, after)
            resource["change"]["after_unknown"] = {"acl": True}
            config = {"address": address.split("[", 1)[0], "expressions": {"bucket": {"constant_value": after["bucket"]}}}
            plan = _plan([resource], configuration={"root_module": {"resources": [config]}})
            self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
            for acl in ({"references": ["var.acl"]}, {"constant_value": "public-read"}):
                config["expressions"]["acl"] = acl
                self.assertEqual(validate_plan(plan, manifest)["reason_code"], "unknown_authorization_value")
            config["expressions"].pop("acl")
            plan.pop("configuration")
            self.assertEqual(validate_plan(plan, manifest)["reason_code"], "unknown_authorization_value")

    def test_committed_manifest_covers_coverage_asset_update_subset(self):
        address = 'aws_s3_object.site_assets["coverage-locations.json"]'
        manifest = json.loads(
            (Path(__file__).resolve().parent / "development-release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        before = {
            "source": "v2/agent/assets/coverage-locations.json",
            "source_hash": "old",
            **dict(CONTRACT[address].create_identity),
        }
        plan = _plan([_resource_change(address, "update", before, dict(before, source_hash="new"))])
        accepted = validate_plan(plan, manifest)
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["reason_code"], "ok")
        self.assertEqual(accepted["addresses"], [address])
        self.assertEqual(accepted["actions"], ["update"])
        self.assertEqual(accepted["operation_classes"], ["site-asset-upload"])

        missing_mutation = copy.deepcopy(manifest)
        missing_mutation["mutations"] = [record for record in missing_mutation["mutations"] if record["address"] != address]
        self.assertEqual(validate_plan(plan, missing_mutation), {"status": "rejected", "reason_code": "manifest_coverage_mismatch"})

        missing_permission = copy.deepcopy(manifest)
        missing_permission["permissions"] = [record for record in missing_permission["permissions"] if record["address"] != address]
        expected = {
            "status": "rejected",
            "reason_code": "missing_permission",
            "address": address,
            "action": "update",
            "operation_class": "site-asset-upload",
        }
        self.assertEqual(validate_plan(plan, missing_permission), expected)

        for field in ("bucket", "key"):
            with self.subTest(gate=field):
                rejected = copy.deepcopy(plan)
                change = rejected["resource_changes"][0]["change"]
                change["before"][field] = change["after"][field] = "wrong"
                result = validate_plan(rejected, manifest)
                self.assertEqual(result["reason_code"], "invalid_resource_identity")
                self.assertFalse({"before", "after", "source", "source_hash"} & set(result))

        for label, mutate, reason in (
            ("action", lambda permission: permission.update(action="s3:GetObject"), "invalid_permission"),
            ("broad_resource", lambda permission: permission.update(resource="*"), "invalid_permission"),
            ("different_resource", lambda permission: permission.update(resource="arn:aws:s3:::unrelated-bucket/*"), "invalid_permission"),
            ("conditions", lambda permission: permission.update(conditions={"extra": "value"}), "invalid_permission"),
            ("duplicate", lambda permission: None, "missing_permission"),
        ):
            with self.subTest(gate=label):
                rejected_manifest = copy.deepcopy(manifest)
                permission = next(record for record in rejected_manifest["permissions"] if record["address"] == address)
                mutate(permission)
                if label == "duplicate":
                    rejected_manifest["permissions"].append(copy.deepcopy(permission))
                result = validate_plan(plan, rejected_manifest)
                self.assertEqual(result["reason_code"], reason)
                self.assertFalse({"before", "after", "source", "source_hash"} & set(result))

    def test_timed_schedule_updates_require_fixed_enabled_target(self):
        address = 'aws_scheduler_schedule.timed_checks["greenway-eb-mon-0723"]'
        spec = CONTRACT[address]
        after = _timed_schedule_plan_value(address)
        before = copy.deepcopy(after)
        before["schedule_expression"] = "cron(0 0 ? * SUN *)"
        manifest = {
            **manifest_header(timed=True),
            "mutations": [
                {
                "address": address,
                "action": "update",
                "operation_class": spec.operation_class,
                "changed_fields": ["schedule_expression"],
                }
            ],
            "permissions": [
                {
                "address": address,
                "action": permission.action,
                "resource": permission.resources[0],
                "conditions": dict(permission.conditions),
                }
                for permission in spec.permissions
            ],
        }
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", before, after)]), manifest)["status"],
            "accepted",
        )

        missing_passrole = copy.deepcopy(manifest)
        missing_passrole["permissions"] = [
            record for record in missing_passrole["permissions"] if record["action"] != "iam:PassRole"
        ]
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", before, after)]), missing_passrole)["reason_code"],
            "missing_permission",
        )

        widened_passrole = copy.deepcopy(manifest)
        next(record for record in widened_passrole["permissions"] if record["action"] == "iam:PassRole")["resource"] = "*"
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", before, after)]), widened_passrole)["reason_code"],
            "invalid_permission",
        )

        wrong_service = copy.deepcopy(manifest)
        next(record for record in wrong_service["permissions"] if record["action"] == "iam:PassRole")["conditions"] = {
            "iam:PassedToService": "events.amazonaws.com"
        }
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", before, after)]), wrong_service)["reason_code"],
            "invalid_permission",
        )

        wrong_role = copy.deepcopy(manifest)
        next(record for record in wrong_role["permissions"] if record["action"] == "iam:PassRole")["resource"] = (
            "arn:aws:iam::903859731897:role/nova-toll-v2-timed-checks-scheduler-other"
        )
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", before, after)]), wrong_role)["reason_code"],
            "invalid_permission",
        )

        wrong_condition_key = copy.deepcopy(manifest)
        next(record for record in wrong_condition_key["permissions"] if record["action"] == "iam:PassRole")["conditions"] = {
            "iam:PassedToServiceCondition": "scheduler.amazonaws.com"
        }
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", before, after)]), wrong_condition_key)["reason_code"],
            "invalid_permission",
        )

        orphan_permission = copy.deepcopy(manifest)
        orphan_permission["permissions"].append(
            {
            "address": 'aws_scheduler_schedule.timed_checks["greenway-eb-fri-0723"]',
            "action": "scheduler:UpdateSchedule",
            "resource": "arn:aws:scheduler:us-east-1:903859731897:schedule/default/nova-toll-v2-greenway-eb-fri-0723-dev",
            "conditions": {},
            }
        )
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", before, after)]), orphan_permission)["reason_code"],
            "manifest_coverage_mismatch",
        )

        provider_after = copy.deepcopy(after)
        provider_after["flexible_time_window"][0]["maximum_window_in_minutes"] = None
        for field in (
            "ecs_parameters",
            "eventbridge_parameters",
            "kinesis_parameters",
            "sagemaker_pipeline_parameters",
            "sqs_parameters",
        ):
            provider_after["target"][0][field] = []
        provider_before = copy.deepcopy(provider_after)
        provider_before["schedule_expression"] = "cron(0 0 ? * SUN *)"
        provider_snapshot = copy.deepcopy(provider_after)
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", provider_before, provider_after)]), manifest
            )["status"],
            "accepted",
        )
        self.assertEqual(provider_after, provider_snapshot)

        def assert_invalid_provider_value(candidate, changed_field):
            invalid_manifest = copy.deepcopy(manifest)
            invalid_manifest["mutations"][0]["changed_fields"] = [changed_field]
            self.assertEqual(
                validate_plan(
                    _plan([_resource_change(address, "update", provider_after, candidate)]),
                    invalid_manifest,
                )["reason_code"],
                "invalid_schedule_value",
            )

        for value in (0, -1, False, 1, True, "0", [], {}):
            invalid_window = copy.deepcopy(provider_after)
            invalid_window["flexible_time_window"][0]["maximum_window_in_minutes"] = value
            assert_invalid_provider_value(invalid_window, "flexible_time_window")

        for field in (
            "ecs_parameters",
            "eventbridge_parameters",
            "kinesis_parameters",
            "sagemaker_pipeline_parameters",
            "sqs_parameters",
        ):
            for value in (None, {}, [{}], [{"unexpected": "value"}], "[]"):
                invalid_target = copy.deepcopy(provider_after)
                invalid_target["target"][0][field] = value
                assert_invalid_provider_value(invalid_target, "target")

        unknown_target = copy.deepcopy(provider_after)
        unknown_target["target"][0]["unexpected_parameters"] = []
        assert_invalid_provider_value(unknown_target, "target")

        unknown_window = copy.deepcopy(provider_after)
        unknown_window["flexible_time_window"][0]["unexpected"] = None
        assert_invalid_provider_value(unknown_window, "flexible_time_window")

        for field in ("retry_policy", "dead_letter_config"):
            invalid_required = copy.deepcopy(provider_after)
            invalid_required["target"][0][field] = []
            assert_invalid_provider_value(invalid_required, "target")

        invalid_input = copy.deepcopy(provider_after)
        invalid_input["target"][0]["input"] = "{}"
        assert_invalid_provider_value(invalid_input, "target")

        invalid_timezone = copy.deepcopy(provider_after)
        invalid_timezone["schedule_expression_timezone"] = "UTC"
        assert_invalid_provider_value(invalid_timezone, "schedule_expression_timezone")

        disabled = copy.deepcopy(after)
        disabled["state"] = "DISABLED"
        disabled_manifest = copy.deepcopy(manifest)
        disabled_manifest["mutations"][0]["changed_fields"] = ["state"]
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", after, disabled)]), disabled_manifest)["reason_code"],
            "invalid_schedule_value",
        )

        retargeted = copy.deepcopy(after)
        retargeted["target"][0]["arn"] = "arn:aws:lambda:us-east-1:903859731897:function:evil"
        retargeted_manifest = copy.deepcopy(manifest)
        retargeted_manifest["mutations"][0]["changed_fields"] = ["target"]
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", after, retargeted)]), retargeted_manifest)["reason_code"],
            "invalid_schedule_value",
        )

        extended_target = copy.deepcopy(after)
        extended_target["target"][0]["sqs_parameters"] = [{"message_group_id": "unexpected"}]
        self.assertEqual(
            validate_plan(_plan([_resource_change(address, "update", after, extended_target)]), retargeted_manifest)["reason_code"],
            "invalid_schedule_value",
        )

    def test_rejects_lambda_configuration_disguised_as_code(self):
        plan = lambda_plan(runtime="python3.13")
        self.assert_reason("unsupported_field_delta", plan=plan)

    def test_accepts_dormant_production_configuration_and_development_resources(self):
        plan = _plan(
            [
                _resource_change(
                    "aws_acm_certificate.site[0]",
                    "no-op",
                    {"domain_name": "dev.tollchat.ai"},
                    {"domain_name": "dev.tollchat.ai"},
                ),
                _resource_change(
                    "aws_cloudfront_distribution.site",
                    "no-op",
                    {"aliases": {"items": ["dev.tollchat.ai"]}},
                    {"aliases": {"items": ["dev.tollchat.ai"]}},
                ),
                _resource_change(
                    "aws_lambda_function.publisher",
                    "no-op",
                    {"environment": {"variables": {"PUBLIC_BASE_URL": "https://dev.tollchat.ai"}}},
                    {"environment": {"variables": {"PUBLIC_BASE_URL": "https://dev.tollchat.ai"}}},
                ),
            ],
            configuration={
                "root_module": {
                    "expressions": {
                        "account": {"constant_value": "920534282028"},
                        "environment": {"constant_value": "production"},
                        "site_url": {"constant_value": "https://tollchat.ai/"},
                        "www_url": {"constant_value": "https://www.tollchat.ai/"},
                    }
                }
            },
        )
        result = validate_plan(plan, lambda_manifest())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["reason_code"], "ok")
        self.assertEqual(result["addresses"], [])
        self.assertEqual(result["actions"], [])
        self.assertEqual(result["operation_classes"], [])
        self.assertEqual(len(result["fingerprint"]), 64)
        self.assertEqual(
            set(result),
            {"status", "reason_code", "addresses", "actions", "operation_classes", "fingerprint"},
        )

    def test_rejects_malformed_identity_and_input(self):
        self.assert_reason("malformed_input", plan=[])
        self.assertEqual(_validate_plan(lambda_plan(), lambda_manifest())["reason_code"], "provider_identity_missing")
        identity = dict(EXPECTED_IDENTITY)
        identity["terraform_version"] = "1.14.0"
        self.assert_reason("provider_identity_mismatch", identity=identity)

        manifest = lambda_manifest()
        del manifest["packages"]
        self.assert_reason("unknown_manifest_declaration", manifest=manifest)

        manifest = lambda_manifest()
        manifest["deployment_inputs"] = {"v2/infra/main.tf": "bad"}
        self.assert_reason("malformed_input", manifest=manifest)

    def test_rejects_unlisted_duplicate_and_unknown_values(self):
        plan = lambda_plan()
        plan["resource_changes"][0]["address"] = "aws_lambda_function.not_declared"
        self.assert_reason("malformed_input", plan=plan)

        duplicate = lambda_plan()["resource_changes"]
        plan = lambda_plan()
        plan["resource_changes"].extend(copy.deepcopy(duplicate))
        self.assert_reason("duplicate_address", plan=plan)

        plan = lambda_plan()
        plan["resource_changes"][0]["change"]["after_unknown"] = {"source_code_hash": True}
        self.assert_reason("unknown_authorization_value", plan=plan)

        plan = lambda_plan()
        del plan["resource_changes"][0]["change"]["after_unknown"]
        self.assert_reason("malformed_input", plan=plan)

        plan = lambda_plan()
        plan["resource_changes"][0]["change"]["after_sensitive"] = {"filename": True}
        self.assert_reason("sensitive_authorization_value", plan=plan)

    def test_accepts_s3_object_version_only_lambda_update(self):
        address = "aws_lambda_function.tollchat_proxy"
        before = {
            "function_name": LAMBDA_FUNCTION_NAMES["tollchat_proxy"],
            "filename": None,
            "s3_bucket": "nova-toll-agentcore-903859731897",
            "s3_key": "lambda/v2/chat-proxy-dev.zip",
            "s3_object_version": "old",
            "source_code_hash": "old",
        }
        after = dict(before, s3_object_version="new", source_code_hash="new")
        plan = _plan([_resource_change(address, "update", before, after)])
        manifest = lambda_manifest(("s3_object_version", "source_code_hash"))
        manifest["mutations"][0]["address"] = address
        manifest["permissions"][0].update(
            {
            "address": address,
            "resource": "arn:aws:lambda:us-east-1:903859731897:function:tollchat-v2-chat-proxy-dev",
            }
        )
        result = validate_plan(plan, manifest)
        self.assertEqual(result["status"], "accepted")

        plan["resource_changes"][0]["change"]["after"]["s3_key"] = "lambda/v2/redirect.zip"
        manifest["mutations"][0]["changed_fields"].append("s3_key")
        self.assert_reason("invalid_resource_identity", plan=plan, manifest=manifest)

        mixed = copy.deepcopy(plan)
        mixed["resource_changes"][0]["change"]["after"]["s3_key"] = "lambda/v2/chat-proxy-dev.zip"
        mixed["resource_changes"][0]["change"]["after"]["filename"] = "chat-proxy.zip"
        mixed_manifest = copy.deepcopy(manifest)
        mixed_manifest["mutations"][0]["changed_fields"] = ["filename", "s3_object_version", "source_code_hash"]
        self.assert_reason("invalid_resource_identity", plan=mixed, manifest=mixed_manifest)

    def test_rejects_filename_lambda_s3_delivery_shape(self):
        plan = lambda_plan(s3_bucket="redirect", s3_key="lambda.zip")
        manifest = lambda_manifest(("filename", "s3_bucket", "s3_key", "source_code_hash"))
        self.assert_reason("invalid_resource_identity", plan=plan, manifest=manifest)

        missing = lambda_plan()
        del missing["resource_changes"][0]["change"]["after"]["s3_key"]
        self.assert_reason("invalid_resource_identity", plan=missing)

    def test_accepts_only_complete_fixed_production_control_inputs(self):
        manifest = lambda_manifest()
        manifest["deployment_inputs"] = {
            path: HASH
            for path in sorted({"v2/infra/main.tf", *PRODUCTION_CONTROL_INPUTS})
        }
        self.assertEqual(validate_plan(lambda_plan(), manifest)["status"], "accepted")

        incomplete = copy.deepcopy(manifest)
        incomplete["deployment_inputs"].pop(next(iter(PRODUCTION_CONTROL_INPUTS)))
        self.assert_reason("malformed_input", manifest=incomplete)

        production_value = copy.deepcopy(manifest)
        production_value["deployment_inputs"][
            "v2/scripts/run_production_migrations.py"
        ] = "production"
        self.assert_reason("production_target", manifest=production_value)

        same_filename_elsewhere = copy.deepcopy(manifest)
        same_filename_elsewhere["deployment_inputs"][
            "other/v2-production-migrations.yml"
        ] = HASH
        self.assert_reason("production_target", manifest=same_filename_elsewhere)

        unknown_production_path = copy.deepcopy(manifest)
        unknown_production_path["deployment_inputs"][
            "v2/scripts/unknown-production-control.py"
        ] = HASH
        self.assert_reason("production_target", manifest=unknown_production_path)

        production_identity = dict(EXPECTED_IDENTITY, account="920534282028")
        self.assert_reason("production_target", manifest=manifest, identity=production_identity)

    def test_rejects_realized_production_markers_at_boundaries(self):
        for marker in (
            "920534282028",
            "https://tollchat.ai/",
            "https://www.tollchat.ai/path?x=1#fragment",
            "production",
            "prod",
        ):
            with self.subTest(marker=marker):
                result = self.assert_reason(
                    "production_target",
                    plan=lambda_plan(filename=marker),
                )
                self.assertNotIn(
                    marker,
                    json.dumps({key: value for key, value in result.items() if key != "reason_code"}),
                )

    def test_rejects_production_moved_deposed_import_replacement_and_delete(self):
        plan = lambda_plan()
        plan["resource_changes"][0]["change"]["after"]["filename"] = "arn:aws:lambda:us-east-1:920534282028:function:prod"
        self.assert_reason("production_target", plan=plan)

        plan = lambda_plan()
        plan["resource_changes"][0]["previous_address"] = "aws_lambda_function.old"
        self.assert_reason("moved_resource", plan=plan)

        plan = lambda_plan()
        plan["resource_changes"][0]["deposed"] = "0"
        self.assert_reason("deposed_resource", plan=plan)

        for action, reason in ((["import"], "import_or_refresh"), (["update", "create"], "replacement"), (["delete"], "delete_not_permitted")):
            plan = lambda_plan()
            plan["resource_changes"][0]["change"]["actions"] = action
            self.assert_reason(reason, plan=plan)

    def test_requires_manifest_mutation_and_distinct_permission(self):
        manifest = lambda_manifest()
        manifest["permissions"] = []
        self.assert_reason("missing_permission", manifest=manifest)

        manifest = lambda_manifest()
        manifest["mutations"][0]["changed_fields"] = ["filename"]
        self.assert_reason("unsupported_field_delta", manifest=manifest)

        manifest = lambda_manifest()
        manifest["permissions"][0]["resource"] = "*"
        self.assert_reason("invalid_permission", manifest=manifest)

        address = "aws_cloudwatch_metric_alarm.loader_errors"
        spec = CONTRACT[address]
        plan = _plan([_resource_change(address, "update", {"tags": {"old": "1"}}, {"tags": {"new": "1"}})])
        manifest = {
            **manifest_header(),
            "mutations": [{"address": address, "action": "update", "operation_class": spec.operation_class, "changed_fields": ["tags"]}],
            "permissions": [
                {"address": address, "action": spec.permissions[0].action, "resource": spec.permissions[0].resources[0], "conditions": {}},
                {"address": address, "action": spec.permissions[0].action, "resource": spec.permissions[0].resources[0], "conditions": {}},
            ],
        }
        self.assert_reason("duplicate_permission", plan=plan, manifest=manifest)

    def test_subset_retry_accepts_plan_subset_but_validates_all_declarations(self):
        result = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result["status"], "accepted")

        manifest = lambda_manifest()
        alias_declaration = {
            "address": "aws_lambda_alias.tollchat_live",
            "action": "update",
            "operation_class": "lambda-alias",
            "changed_fields": ["function_version"],
        }
        manifest["mutations"].append(alias_declaration)
        manifest["permissions"].append(
            {
            "address": alias_declaration["address"],
            "action": "lambda:UpdateAlias",
            "resource": "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-pricing-loader-dev",
            "conditions": {},
            }
        )
        self.assertEqual(validate_plan(lambda_plan(), manifest)["status"], "accepted")

        manifest["mutations"][1]["address"] = "aws_lambda_alias.not_declared"
        self.assert_reason("manifest_coverage_mismatch", manifest=manifest)

        manifest = lambda_manifest()
        manifest["mutations"] = []
        manifest["permissions"] = []
        self.assert_reason("manifest_coverage_mismatch", manifest=manifest)

    def test_accepts_normal_create_shape_without_authorizing_computed_fields(self):
        cases = (
            (
                "aws_cloudwatch_event_target.loader",
                {"target": {"arn": "arn"}, "rule": "rule", "id": "id"},
                ("target",),
            ),
            (
                "aws_bedrock_guardrail_version.tollchat",
                {
                    "description": "description",
                    "guardrail_arn": "arn",
                    "version": "1",
                    "id": "id",
                },
                ("description", "guardrail_arn"),
            ),
            (
                "aws_api_gateway_deployment.tollchat",
                {
                    "triggers": {"redeployment": "hash"},
                    "rest_api_id": "api",
                    "id": "id",
                },
                ("triggers.redeployment",),
            ),
        )
        for address, after, fields in cases:
            spec = CONTRACT[address]
            plan = _plan([_resource_change(address, "create", None, after, after_unknown={"id": True})])
            manifest = {
                **manifest_header(),
                "mutations": [{"address": address, "action": "create", "operation_class": spec.operation_class, "changed_fields": list(fields)}],
                "permissions": [{"address": address, "action": p.action, "resource": p.resources[0], "conditions": dict(p.conditions)} for p in spec.permissions],
            }
            self.assertEqual(validate_plan(plan, manifest)["status"], "accepted", address)

    def test_s3_create_identity_is_exact_for_every_object_entry(self):
        for address, spec in CONTRACT.items():
            if address in {
                "aws_s3_object.index",
                "aws_s3_object.faq",
                "aws_s3_object.privacy",
            }:
                continue
            if (
                not spec.create_identity
                or "create" not in spec.actions
                or not any(
                    field in dict(spec.create_identity) for field in ("bucket", "key")
                )
            ):
                continue
            fields = spec.fields[:2]
            after = {fields[0]: "source", fields[1]: "hash", **dict(spec.create_identity)}
            plan = _plan([_resource_change(address, "create", None, after)])
            manifest = {
                **manifest_header(
                    timed=address
                    in {
                        "aws_s3_object.timed_checks",
                        "aws_lambda_function.timed_checks",
            }
                ),
                "mutations": [
                    {
                        "address": address,
                        "action": "create",
                        "operation_class": spec.operation_class,
                        "changed_fields": list(fields),
                    }
                ],
                "permissions": [
                    {
                        "address": address,
                        "action": p.action,
                        "resource": p.resources[0],
                        "conditions": dict(p.conditions),
                    }
                    for p in spec.permissions
                ],
            }
            self.assertEqual(validate_plan(plan, manifest)["status"], "accepted", address)

            redirected = dict(after, key="runtime/v2/unauthorized.py")
            redirected_plan = _plan([_resource_change(address, "create", None, redirected)])
            self.assertEqual(validate_plan(redirected_plan, manifest)["reason_code"], "invalid_resource_identity", address)

            before_update = {fields[0]: "old", fields[1]: "old", **dict(spec.create_identity)}
            after_update = {fields[0]: "new", fields[1]: "new", **dict(spec.create_identity)}
            update_plan = _plan([_resource_change(address, "update", before_update, after_update)])
            update_manifest = dict(manifest, mutations=[dict(manifest["mutations"][0], action="update")])
            self.assertEqual(validate_plan(update_plan, update_manifest)["status"], "accepted", address)

            redirected_update_before = dict(before_update, bucket="unauthorized-bucket")
            redirected_update_after = dict(after_update, bucket="unauthorized-bucket")
            redirected_update = _plan([_resource_change(address, "update", redirected_update_before, redirected_update_after)])
            self.assertEqual(validate_plan(redirected_update, update_manifest)["reason_code"], "invalid_resource_identity", address)

        address = 'aws_s3_object.site_assets["LICENSE.txt"]'
        spec = CONTRACT[address]
        after = {"source": "asset", "source_hash": "hash", **dict(spec.create_identity)}
        manifest = {
            **manifest_header(),
            "mutations": [{"address": address, "action": "create", "operation_class": spec.operation_class, "changed_fields": ["source", "source_hash"]}],
            "permissions": [{"address": address, "action": p.action, "resource": p.resources[0], "conditions": dict(p.conditions)} for p in spec.permissions],
        }
        unknown = _plan([_resource_change(address, "create", None, after, after_unknown={"key": True})])
        self.assertEqual(validate_plan(unknown, manifest)["reason_code"], "unknown_authorization_value")
        sensitive = _plan([_resource_change(address, "create", None, after, after_sensitive={"key": True})])
        self.assertEqual(validate_plan(sensitive, manifest)["reason_code"], "sensitive_authorization_value")
        update_before = {"source": "old", "source_hash": "old", **dict(spec.create_identity)}
        update_after = {"source": "new", "source_hash": "new", **dict(spec.create_identity)}
        update_manifest = dict(manifest, mutations=[dict(manifest["mutations"][0], action="update")])
        unknown_update = _plan([_resource_change(address, "update", update_before, update_after, after_unknown={"key": True})])
        self.assertEqual(validate_plan(unknown_update, update_manifest)["reason_code"], "unknown_authorization_value")
        sensitive_update = _plan([_resource_change(address, "update", update_before, update_after, after_sensitive={"bucket": True})])
        self.assertEqual(validate_plan(sensitive_update, update_manifest)["reason_code"], "sensitive_authorization_value")

    def test_plan_identity_and_type_name_are_bound(self):
        plan = lambda_plan()
        plan["terraform_version"] = "1.14.0"
        self.assert_reason("provider_identity_mismatch", plan=plan)
        plan = lambda_plan()
        plan["resource_changes"][0]["provider_name"] = "registry.terraform.io/hashicorp/random"
        self.assert_reason("provider_identity_mismatch", plan=plan)
        plan = lambda_plan()
        plan["resource_changes"][0]["name"] = "publisher"
        self.assert_reason("malformed_input", plan=plan)

    def test_rejects_data_mode_mutation_and_unknown_manifest_declarations(self):
        plan = lambda_plan()
        plan["resource_changes"][0]["mode"] = "data"
        self.assert_reason("data_mode_misuse", plan=plan)

        manifest = lambda_manifest()
        manifest["unexpected"] = "raw exception"
        self.assert_reason("unknown_manifest_declaration", manifest=manifest)

    def test_cli_requires_and_verifies_caller_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, manifest_path, identity_path = (root / name for name in ("plan.json", "manifest.json", "identity.json"))
            plan_path.write_text(json.dumps(lambda_plan()), encoding="utf-8")
            manifest_path.write_text(json.dumps(lambda_manifest()), encoding="utf-8")
            identity_path.write_text(json.dumps(dict(EXPECTED_IDENTITY)), encoding="utf-8")
            result = subprocess.run(
                ["python3", "infra/delivery_plan_validator.py", str(plan_path), str(manifest_path), "--identity", str(identity_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["status"], "accepted")

            for missing in (manifest_path, identity_path):
                missing.unlink()
                rejected = subprocess.run(
                    ["python3", "infra/delivery_plan_validator.py", str(plan_path), str(manifest_path), "--identity", str(identity_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(json.loads(rejected.stdout), {"reason_code": "malformed_input", "status": "rejected"})
                self.assertEqual(rejected.stderr, "")
                if missing is manifest_path:
                    manifest_path.write_text(json.dumps(lambda_manifest()), encoding="utf-8")
                else:
                    identity_path.write_text(json.dumps(dict(EXPECTED_IDENTITY)), encoding="utf-8")

            for unreadable in (manifest_path, identity_path):
                unreadable.unlink()
                unreadable.mkdir()
                rejected = subprocess.run(
                    ["python3", "infra/delivery_plan_validator.py", str(plan_path), str(manifest_path), "--identity", str(identity_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(json.loads(rejected.stdout), {"reason_code": "malformed_input", "status": "rejected"})
                self.assertEqual(rejected.stderr, "")
                unreadable.rmdir()
                if unreadable is manifest_path:
                    manifest_path.write_text(json.dumps(lambda_manifest()), encoding="utf-8")
                else:
                    identity_path.write_text(json.dumps(dict(EXPECTED_IDENTITY)), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

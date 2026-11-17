import base64
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

from infra.delivery_plan_validator import (
    CONTRACT,
    EXPECTED_IDENTITY,
    EXPECTED_PROVIDER_NAME,
    JSON,
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
    timed_schedule_plan_value,
)
from infra.delivery_plan_validator import (
    validate_plan as _validate_plan,
)
from v2.scripts import shared_packages


# Builders describe valid fixture envelopes. Tests cast deliberate corruptions
# to JSON at the validator boundary so runtime rejection remains exercised.
class DerivedOptions(TypedDict, total=False):
    configuration: bool
    expression_path: str
    reference: str
    resource_address: str


class Change(TypedDict):
    actions: list[str]
    before: dict[str, JSON]
    after: dict[str, JSON]
    after_unknown: dict[str, JSON]
    before_sensitive: dict[str, JSON]
    after_sensitive: dict[str, JSON]
    before_identity: JSON
    after_identity: JSON


class Resource(TypedDict):
    address: str
    mode: str
    type: str
    name: str
    provider_name: str
    change: Change
    index: NotRequired[JSON]


class Plan(TypedDict):
    terraform_version: str
    applyable: bool
    complete: bool
    errored: bool
    resource_changes: list[Resource]
    configuration: NotRequired[dict[str, JSON]]


class Declaration(TypedDict):
    address: str
    action: str
    operation_class: str
    changed_fields: list[str]


class PermissionRecord(TypedDict):
    address: str
    action: str
    resource: str
    conditions: dict[str, str]


class ManifestHeader(TypedDict):
    schema_version: int
    provider_identity: dict[str, str]
    deployment_inputs: dict[str, str]
    packages: dict[str, str]


class Manifest(ManifestHeader):
    mutations: list[Declaration]
    permissions: list[PermissionRecord]


LAMBDA_ADDRESS = "aws_lambda_function.loader"
HASH = "0" * 64


def _trace_notice_contents() -> dict[str, str]:
    # Freeze published notices so page edits cannot rewrite legacy test inputs.
    import gzip

    values = json.loads(
        gzip.decompress(
            (Path(__file__).parent / "fixtures/telemetry-notices.json.gz").read_bytes()
        )
    )
    for name, content in values["legacy"].items():
        assert (
            hashlib.sha256(content.encode()).hexdigest()
            == TRACE_NOTICE_DIGESTS[f"aws_s3_object.{name}"]
        )
    return values["legacy"]


def _telemetry_value(address: str) -> dict[str, JSON]:
    spec = CONTRACT[address]
    value = dict(spec.create_identity)
    if spec.operation_class == "telemetry-log-protection":
        value["policy_document"] = (
            (Path(__file__).resolve().parents[1] / "v2/infra/telemetry-log-policy.tf")
            .read_text()
            .split("<<-POLICY\n", 1)[1]
            .split("\nPOLICY", 1)[0]
        )
    elif spec.operation_class == "telemetry-failure-metric":
        value.update(
            pattern="?telemetry_redaction_failed ?telemetry_redaction_omitted ?telemetry_export_failed",
            metric_transformation=[
                {
                    "name": "RedactionFailures",
                    "namespace": "TollChat/Telemetry",
                    "value": "1",
                }
            ],
        )
    else:
        pii = "telemetry_pii[" in address
        endpoint = "DEFAULT" if '"DEFAULT"' in address else "preview"
        value.update(
            namespace="AWS/Logs" if pii else "TollChat/Telemetry",
            metric_name="LogEventsWithFindings" if pii else "RedactionFailures",
            dimensions={
                "LogGroupName": f"/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-{endpoint}"
            }
            if pii
            else {},
            statistic="Sum",
            period=300,
            evaluation_periods=1,
            comparison_operator="GreaterThanThreshold",
            threshold=0,
            treat_missing_data="notBreaching",
            alarm_actions=[],
        )
    return value


def validate_plan(
    plan: object, manifest: object, identity: object = None
) -> dict[str, JSON]:
    return _validate_plan(
        cast(JSON, plan),
        cast(JSON, manifest),
        cast(JSON, dict(EXPECTED_IDENTITY) if identity is None else identity),
        shared_packages.evidence(
            "development",
            "903859731897",
            "a" * 40,
            {
                **dict.fromkeys(shared_packages.PACKAGES, HASH),
                **cast(Manifest, manifest).get("packages", {}),
            },
        ),
    )


def manifest_header(*, timed: bool = False) -> ManifestHeader:
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
    address: str,
    action: str,
    before: object,
    after: object,
    *,
    after_unknown: JSON = None,
    before_sensitive: JSON = None,
    after_sensitive: JSON = None,
    before_identity: JSON = None,
    after_identity: JSON = None,
) -> Resource:
    base, _, index_text = address.partition("[")
    resource_type, name = base.split(".")
    record: Resource = {
        "address": address,
        "mode": "managed",
        "type": resource_type,
        "name": name,
        "provider_name": EXPECTED_PROVIDER_NAME,
        "change": {
            "actions": [action],
            "before": cast(dict[str, JSON], before),
            "after": cast(dict[str, JSON], after),
            "after_unknown": {}
            if after_unknown is None
            else cast(dict[str, JSON], after_unknown),
            "before_sensitive": {}
            if before_sensitive is None
            else cast(dict[str, JSON], before_sensitive),
            "after_sensitive": {}
            if after_sensitive is None
            else cast(dict[str, JSON], after_sensitive),
            "before_identity": before_identity,
            "after_identity": after_identity,
        },
    }
    if index_text:
        record["index"] = json.loads("[" + index_text[:-1] + "]")[0]
    spec = CONTRACT.get(address)
    if spec is not None and spec.provider_change_identity:
        expected = dict(spec.provider_change_identity)
        if action != "create":
            record["change"]["before_identity"] = dict[str, JSON](expected)
        if action != "delete":
            record["change"]["after_identity"] = dict[str, JSON](expected)
    return record


def _plan(resource_changes: Sequence[Resource], **metadata: object) -> Plan:
    plan: Plan = {
        "terraform_version": "1.15.8",
        "applyable": True,
        "complete": True,
        "errored": False,
        "resource_changes": list(resource_changes),
    }
    cast(dict[str, object], plan).update(metadata)
    return plan


def lambda_plan(**changes: JSON) -> Plan:
    before: dict[str, JSON] = {
        "function_name": LAMBDA_FUNCTION_NAMES["loader"],
        "arn": "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-pricing-loader-dev",
        "filename": "old.zip",
        "source_code_hash": "old",
        "s3_bucket": None,
        "s3_key": None,
        "s3_object_version": None,
    }
    after: dict[str, JSON] = {
        "function_name": LAMBDA_FUNCTION_NAMES["loader"],
        "arn": "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-pricing-loader-dev",
        "filename": "build/loader.zip",
        "source_code_hash": base64.b64encode(bytes(32)).decode(),
        "s3_bucket": None,
        "s3_key": None,
        "s3_object_version": None,
    }
    after.update(changes)
    return _plan([_resource_change(LAMBDA_ADDRESS, "update", before, after)])


def lambda_manifest(
    changed_fields: Sequence[str] = ("filename", "source_code_hash"),
) -> Manifest:
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


LEGACY_REPORT_ROUTES_CODE = r"""// Retired entrance/exit reports with verified area-report replacements.
/** @type {Record<string, string>} */
var legacyReportRedirects = {
  "woodburn-gallows-road-merrifield-northbound/tysons-route-7-leesburg-pike-northbound": "northbound/woodburn-to-tysons/",
  "lorton-gordon-boulevard-route-123-northbound-i95-211no/idylwood-lee-highway-route-29-northbound": "northbound/lorton-to-idylwood/",
  "tysons-jones-branch-drive-route-123-southbound/stafford-courthouse-road-route-630-southbound": "southbound/tysons-to-stafford/",
  "tysons-westpark-drive-tysons-corner-southbound-i495-185so/stafford-courthouse-road-route-630-southbound": "southbound/tysons-to-stafford/",
  "tysons-route-7-leesburg-pike-southbound/woodburn-gallows-road-merrifield-southbound": "southbound/tysons-to-woodburn/",
  "washington-washington-d-c-district-of-columbia-southbound/fredericksburg-i-95-near-route-17-route-17-southbound-exit-southbound": "southbound/washington-to-fredericksburg/",
  "fredericksburg-i-95-near-route-17-route-17-northbound-entrance-northbound/tysons-jones-branch-drive-route-123-northbound": "northbound/fredericksburg-to-tysons/",
  "tysons-dulles-toll-road-dulles-access-road-southbound-i495-182so/lorton-route-1-richmond-highway-southbound-i95-210sd": "southbound/tysons-to-lorton/",
  "tysons-jones-branch-drive-route-123-southbound/arlington-washington-d-c-washington-northbound": "southbound/tysons-to-arlington/",
};

/** @param {string} location */
function permanentRedirect(location) {
  return {
    statusCode: 301,
    statusDescription: "Moved Permanently",
    headers: {
      location: { value: location },
      "cache-control": { value: "public, max-age=300" },
    },
  };
}

/** @param {{ request: { method: string, uri: string, headers?: Record<string, {value: string}> } }} event */
function handler(event) {
  var request = event.request;
  if (request.uri === "/tolls" || request.uri === "/tolls/") {
    return permanentRedirect("https://tollchat.ai/#toll-reports");
  }
  var legacy = request.uri.match(/^\/tolls\/i95-i495\/([^/]+)\/([^/]+)(?:\/(index\.html|report\.json))?\/?$/);
  var endpointSlug = /-(northbound|southbound)(?:-i(?:95|495)-[a-z0-9]+)?$/;
  if (legacy && endpointSlug.test(legacy[1]) && endpointSlug.test(legacy[2])) {
    var target = legacyReportRedirects[legacy[1] + "/" + legacy[2]];
    if (target) {
      return permanentRedirect("https://tollchat.ai/tolls/i95-i495/" + target + (legacy[3] === "report.json" ? "report.json" : ""));
    }
    // The detailed-report namespace is retired; absent S3 keys otherwise look forbidden.
    return {
      statusCode: 410,
      statusDescription: "Gone",
      headers: {
        "cache-control": { value: "public, max-age=300" },
        "content-type": { value: "text/plain; charset=utf-8" },
        "x-content-type-options": { value: "nosniff" },
      },
      body: {
        encoding: "text",
        data: "This detailed entrance/exit report has been retired. Current area reports are at https://tollchat.ai/tolls/i95-i495/.",
      },
    };
  }
  if (request.uri === "/release-dashboard" || request.uri === "/release-dashboard/") {
    request.uri = "/assets/releases.html";
  }
  if (request.uri === "/eval-dashboard" || request.uri === "/eval-dashboard/") {
    request.uri = "/evals.html";
  }
  if (request.uri === "/cost-dashboard" || request.uri === "/cost-dashboard/") {
    request.uri = "/costs.html";
  }
  if (request.uri.startsWith("/tolls/") && !request.uri.includes(".")) {
    request.uri += request.uri.endsWith("/") ? "index.html" : "/index.html";
  }
  return request;
}
"""


def _set_path(target: dict[str, JSON], path: str, value: JSON) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = cast(dict[str, JSON], current.setdefault(part, {}))
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


def _mutation_change(
    address: str, fields: Sequence[str], action: str = "update"
) -> Resource:
    before: dict[str, JSON] = {}
    after: dict[str, JSON] = {}
    spec = CONTRACT[address]
    for field in fields:
        _set_path(before, field, "old")
        _set_path(after, field, "new")
    for field, value in spec.create_identity:
        before[field] = after[field] = value
    if address == shared_packages.CHAT_ROUTES:
        code = (
            Path(__file__).resolve().parents[1] / "v2/agent/public-api-gate.js"
        ).read_text()
        # Match the exact reviewed pre-annotation bytes, as in the blue/green fixture.
        original = code[code.index("function handler") :]
        values: dict[str, JSON] = {
            "name": "tollchat-v2-public-chat-routes-dev",
            "arn": "arn:aws:cloudfront::903859731897:function/tollchat-v2-public-chat-routes-dev",
            "runtime": "cloudfront-js-2.0",
            "publish": True,
        }
        before.update(values)
        after.update(values)
        before["code"] = original
        after["code"] = code
    if address in shared_packages.RESOURCES:
        if address == shared_packages.OBJECT:
            before["source"] = (
                "old.zip" if "source" in fields else "build/timed-checks.zip"
            )
            after["source"] = "build/timed-checks.zip"
            after["source_hash"] = base64.b64encode(bytes(32)).decode()
        else:
            component = address.rsplit(".", 1)[1]
            name, package = shared_packages.FUNCTIONS[component]
            before["arn"] = after["arn"] = (
                f"arn:aws:lambda:us-east-1:903859731897:function:{name}-dev"
            )
            if component != "timed_checks":
                before["filename"] = (
                    "old.zip" if "filename" in fields else f"build/{package}"
                )
                after["filename"] = f"build/{package}"
            after["source_code_hash"] = base64.b64encode(bytes(32)).decode()
    if action == "no-op":
        after = copy.deepcopy(before)
    return _resource_change(address, action, before, after)


def _mutation_manifest(entries: Sequence[tuple[str, str, Sequence[str]]]) -> Manifest:
    manifest = cast(Manifest, manifest_header())
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


def _derived_fixture(
    index: int,
    *,
    producer_action: str = "update",
    configuration: bool = True,
    expression_path: str | None = None,
    reference: str | None = None,
    resource_address: str | None = None,
) -> tuple[Plan, Manifest]:
    (
        consumer,
        unknown_path,
        source_reference,
        producer,
        consumer_fields,
        producer_fields,
    ) = _DERIVED_FIXTURES[index]
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
    manifest = _mutation_manifest(
        ((consumer, "update", consumer_fields), (producer, "update", producer_fields))
    )
    return plan, manifest


class DeliveryPlanValidatorTests(unittest.TestCase):
    def test_admits_fixed_billing_alert_declarations_before_activation(self) -> None:
        addresses = [
            address
            for address in CONTRACT
            if address.startswith(
                (
                    "aws_cloudwatch_log_metric_filter.costs_",
                    "aws_cloudwatch_metric_alarm.costs_",
                )
            )
        ]
        self.assertEqual(len(addresses), 9)
        manifest = _mutation_manifest(
            [
                (address, "create", sorted(CONTRACT[address].fields))
                for address in addresses
            ]
        )
        self.assertEqual(validate_plan(_plan([]), manifest)["status"], "accepted")
        manifest["permissions"][0]["resource"] = "*"
        self.assertEqual(
            validate_plan(_plan([]), manifest)["reason_code"], "invalid_permission"
        )

    def test_redacted_notices_require_complete_activation_and_support_later_noops(
        self,
    ) -> None:
        import gzip

        from infra.delivery_plan_validator import (
            REDACTED_TRACE_NOTICE_DIGESTS,
            InvalidPlan,
            validate_trace_notices,
        )

        fixture: dict[str, dict[str, str]] = json.loads(
            gzip.decompress(
                (
                    Path(__file__).parent / "fixtures/telemetry-notices.json.gz"
                ).read_bytes()
            )
        )
        records: list[dict[str, JSON]] = []
        for name, content in fixture["redacted"].items():
            address = f"aws_s3_object.{name}"
            self.assertEqual(
                hashlib.sha256(content.encode()).hexdigest(),
                REDACTED_TRACE_NOTICE_DIGESTS[address],
            )
            records.append(
                dict(
                    address=address,
                    action="update",
                    operation_class="site-object-upload",
                    before={"content": fixture["legacy"][name]},
                    after={"content": content},
                )
            )
        identity = dict(
            agent_runtime_arn="arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl",
            agent_runtime_id="nova_toll_v2_development-Y69XBf88Bl",
            agent_runtime_name="nova_toll_v2_development",
            region="us-east-1",
            role_arn="arn:aws:iam::903859731897:role/nova-toll-v2-agentcore-runtime-dev",
        )
        before: dict[str, JSON] = dict(
            identity,
            environment_variables={"UNIFIED_TRACES_DESTINATION_ENABLED": "true"},
        )
        after: dict[str, JSON] = dict(
            identity,
            environment_variables={
                "UNIFIED_TRACES_DESTINATION_ENABLED": "true",
                "TOLLCHAT_TELEMETRY_GUARDRAIL_ID": "testid",
                "TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION": "1",
            },
        )
        records.append(
            dict(
                address="aws_bedrockagentcore_agent_runtime.tollchat",
                action="update",
                operation_class="agentcore-code",
                before=before,
                after=after,
                changed_fields=[
                    "environment_variables",
                    "agent_runtime_artifact.code_configuration.code.s3.version_id",
                ],
            )
        )
        for endpoint in ("DEFAULT", "preview"):
            address = (
                f'aws_cloudwatch_log_data_protection_policy.agentcore["{endpoint}"]'
            )
            records.append(
                dict(
                    address=address,
                    action="create",
                    operation_class="telemetry-log-protection",
                    after=_telemetry_value(address),
                )
            )
        validate_trace_notices(records)
        for index in range(len(records)):
            with self.subTest(missing=index), self.assertRaises(InvalidPlan):
                validate_trace_notices(records[:index] + records[index + 1 :])
        staged = copy.deepcopy(records)
        staged[3]["before"] = copy.deepcopy(staged[3]["after"])
        staged[3]["changed_fields"] = [
            "agent_runtime_artifact.code_configuration.code.s3.version_id"
        ]
        validate_trace_notices(staged)
        for mutant in (copy.deepcopy(records), copy.deepcopy(staged)):
            cast(list[JSON], mutant[3]["changed_fields"]).remove(
                "agent_runtime_artifact.code_configuration.code.s3.version_id"
            )
            with self.assertRaises(InvalidPlan):
                validate_trace_notices(mutant)
        missing_env = copy.deepcopy(staged)
        cast(
            dict[str, JSON],
            cast(dict[str, JSON], missing_env[3]["after"])["environment_variables"],
        ).pop("TOLLCHAT_TELEMETRY_GUARDRAIL_ID")
        with self.assertRaises(InvalidPlan):
            validate_trace_notices(missing_env)
        mixed = copy.deepcopy(records)
        mixed[0]["after"] = mixed[0]["before"]
        with self.assertRaises(InvalidPlan):
            validate_trace_notices(mixed)
        for record in records:
            record.update(
                action="no-op", before=copy.deepcopy(record["after"]), changed_fields=[]
            )
        validate_trace_notices(records)
        for record in records:
            name = cast(str, record["address"]).split(".")[-1]
            if name in fixture["dashboard"]:
                record.update(
                    action="update", after={"content": fixture["dashboard"][name]}
                )
        validate_trace_notices(records)
        changed_notice = copy.deepcopy(records)
        notice = cast(dict[str, JSON], changed_notice[0]["after"])
        notice["content"] = cast(str, notice["content"]) + "unreviewed content"
        with self.assertRaises(InvalidPlan):
            validate_trace_notices(changed_notice)
        missing_guard = copy.deepcopy(records)
        cast(
            dict[str, JSON],
            cast(dict[str, JSON], missing_guard[3]["after"])["environment_variables"],
        ).pop("TOLLCHAT_TELEMETRY_GUARDRAIL_ID")
        with self.assertRaises(InvalidPlan):
            validate_trace_notices(missing_guard)

    def test_credential_regex_covers_plain_and_serialized_headers(self) -> None:
        import re

        source = (
            (Path(__file__).parent / "telemetry.tf")
            .read_text()
            .split('name           = "authorization_header"', 1)[1]
        )
        match = re.search(r"(?m)^\s*pattern\s*= (.+)$", source)
        assert match is not None
        pattern: str = json.loads(match.group(1))
        for text in (
            "Authorization: Bearer abcdefgh12345",
            "Authorization: Basic abcdefgh12345",
            "x-api-key: abcdefgh12345",
            '{"x-api-key":"abcdefgh12345"}',
            '{"Authorization":"Bearer abcdefgh12345"}',
        ):
            self.assertIsNotNone(re.search(pattern, text), text)

    def assert_reason(
        self,
        reason: str,
        plan: object = None,
        manifest: object = None,
        identity: object = None,
    ) -> dict[str, JSON]:
        result = validate_plan(
            plan if plan is not None else lambda_plan(),
            manifest if manifest is not None else lambda_manifest(),
            identity,
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], reason)
        self.assertNotIn("filename", result)
        self.assertNotIn("old.zip", result)
        return result

    def test_accepts_lambda_code_update_with_independent_permission(self) -> None:
        result = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["reason_code"], "ok")
        self.assertEqual(cast(list[str], result["addresses"]), [LAMBDA_ADDRESS])
        self.assertEqual(cast(list[str], result["actions"]), ["update"])
        self.assertEqual(cast(list[str], result["operation_classes"]), ["lambda-code"])
        self.assertEqual(len(cast(str, result["fingerprint"])), 64)
        self.assertEqual(
            set(result),
            {
                "status",
                "reason_code",
                "addresses",
                "actions",
                "operation_classes",
                "fingerprint",
            },
        )

    def test_accepts_hash_only_local_lambda_updates(self) -> None:
        for address in ("aws_lambda_function.loader",):
            with self.subTest(address=address):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                result = validate_plan(plan, manifest)
                self.assertEqual(result["status"], "accepted")
                self.assertEqual(result["reason_code"], "ok")
                self.assertEqual(cast(list[str], result["addresses"]), [address])

    def test_hash_only_local_lambda_boundaries_are_independent(self) -> None:
        for address in ("aws_lambda_function.loader",):
            with self.subTest(address=address, boundary="runtime"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(
                    ((address, "update", ("filename", "source_code_hash")),)
                )
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"],
                    "manifest_mutation_mismatch",
                )
            with self.subTest(address=address, boundary="manifest"):
                plan = _plan(
                    [_mutation_change(address, ("filename", "source_code_hash"))]
                )
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"],
                    "manifest_mutation_mismatch",
                )

    def test_rejects_hash_only_s3_lambda_updates_at_both_boundaries_and_cli(
        self,
    ) -> None:
        for address in (
            "aws_lambda_function.tollchat_proxy",
            "aws_lambda_function.timed_checks",
        ):
            with self.subTest(address=address, boundary="runtime"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                if address.endswith("timed_checks"):
                    manifest["deployment_inputs"][
                        "v2/scripts/build_timed_checks_zip.sh"
                    ] = HASH
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
                plan = _plan(
                    [
                        _mutation_change(
                            address, ("s3_object_version", "source_code_hash")
                        )
                    ]
                )
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                if address.endswith("timed_checks"):
                    manifest["deployment_inputs"][
                        "v2/scripts/build_timed_checks_zip.sh"
                    ] = HASH
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
            plan_path, manifest_path, identity_path = (
                root / name for name in ("plan.json", "manifest.json", "identity.json")
            )
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            identity_path.write_text(
                json.dumps(
                    dict(EXPECTED_IDENTITY),
                ),
                encoding="utf-8",
            )
            cli = subprocess.run(
                [
                    "python3",
                    "infra/delivery_plan_validator.py",
                    str(plan_path),
                    str(manifest_path),
                    "--identity",
                    str(identity_path),
                ],
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

    def test_hash_only_local_lambda_updates_retain_existing_gates(self) -> None:
        for address in ("aws_lambda_function.loader",):
            with self.subTest(address=address, gate="action"):
                plan = _plan(
                    [_mutation_change(address, ("source_code_hash",), action="delete")]
                )
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"], "delete_not_permitted"
                )
            with self.subTest(address=address, gate="provider"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["resource_changes"][0]["provider_name"] = (
                    "registry.terraform.io/hashicorp/random"
                )
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"],
                    "provider_identity_mismatch",
                )
            with self.subTest(address=address, gate="terraform"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["terraform_version"] = "1.14.0"
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"],
                    "provider_identity_mismatch",
                )
            with self.subTest(address=address, gate="missing_identity"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                self.assertEqual(
                    _validate_plan(plan, manifest)["reason_code"],
                    "provider_identity_missing",
                )
            with self.subTest(address=address, gate="identity"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["resource_changes"][0]["change"]["before"]["function_name"] = (
                    "wrong-development-function"
                )
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"],
                    "invalid_resource_identity",
                )
            with self.subTest(address=address, gate="missing_function_identity"):
                plan = _plan([_mutation_change(address, ("source_code_hash",))])
                plan["resource_changes"][0]["change"]["before"].pop("function_name")
                manifest = _mutation_manifest(
                    ((address, "update", ("source_code_hash",)),)
                )
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"],
                    "invalid_resource_identity",
                )
            for field in ("s3_bucket", "s3_key", "s3_object_version"):
                with self.subTest(address=address, gate=field):
                    plan = _plan([_mutation_change(address, ("source_code_hash",))])
                    change = plan["resource_changes"][0]["change"]
                    change["before"][field] = change["after"][field] = "non-null"
                    manifest = _mutation_manifest(
                        ((address, "update", ("source_code_hash",)),)
                    )
                    self.assertEqual(
                        validate_plan(plan, manifest)["reason_code"],
                        "invalid_resource_identity",
                    )
            mutations: tuple[tuple[str, Callable[[Manifest], object], str], ...] = (
                (
                    "missing_permission",
                    lambda manifest: manifest.update(permissions=[]),
                    "missing_permission",
                ),
                (
                    "permission_action",
                    lambda manifest: manifest["permissions"][0].update(
                        action="lambda:UpdateFunctionConfiguration"
                    ),
                    "invalid_permission",
                ),
                (
                    "permission_resource",
                    lambda manifest: manifest["permissions"][0].update(resource="*"),
                    "invalid_permission",
                ),
                (
                    "permission_conditions",
                    lambda manifest: manifest["permissions"][0].update(
                        conditions={"extra": "value"}
                    ),
                    "invalid_permission",
                ),
                (
                    "manifest_mismatch",
                    lambda manifest: manifest["mutations"][0].update(
                        changed_fields=["filename", "source_code_hash"]
                    ),
                    "manifest_mutation_mismatch",
                ),
            )
            for label, mutate, reason in mutations:
                with self.subTest(address=address, gate=label):
                    plan = _plan([_mutation_change(address, ("source_code_hash",))])
                    manifest = _mutation_manifest(
                        ((address, "update", ("source_code_hash",)),)
                    )
                    mutate(manifest)
                    self.assertEqual(
                        validate_plan(plan, manifest)["reason_code"], reason
                    )
            plan_mutations: tuple[tuple[str, Callable[[Plan], object], str], ...] = (
                (
                    "runtime",
                    lambda plan: plan["resource_changes"][0]["change"]["after"].update(
                        runtime="python3.14"
                    ),
                    "unsupported_field_delta",
                ),
                (
                    "unknown",
                    lambda plan: plan["resource_changes"][0]["change"].update(
                        after_unknown={"source_code_hash": True}
                    ),
                    "unknown_authorization_value",
                ),
                (
                    "sensitive",
                    lambda plan: plan["resource_changes"][0]["change"].update(
                        after_sensitive={"source_code_hash": True}
                    ),
                    "sensitive_authorization_value",
                ),
                (
                    "production",
                    lambda plan: plan["resource_changes"][0]["change"]["after"].update(
                        source_code_hash="production"
                    ),
                    "production_target",
                ),
            )
            for label, mutate, reason in plan_mutations:
                with self.subTest(address=address, gate=label):
                    plan = _plan([_mutation_change(address, ("source_code_hash",))])
                    manifest = _mutation_manifest(
                        ((address, "update", ("source_code_hash",)),)
                    )
                    mutate(plan)
                    self.assertEqual(
                        validate_plan(plan, manifest)["reason_code"], reason
                    )

    def test_current_chat_route_release_changes_only_code(self) -> None:
        manifest = cast(
            Manifest,
            json.loads(
                (
                    Path(__file__).resolve().parent
                    / "development-release-manifest.json"
                ).read_text()
            ),
        )
        address = "aws_cloudfront_function.public_chat_routes"
        plan = _plan([_mutation_change(address, ("code",))])
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
        after = plan["resource_changes"][0]["change"]["after"]
        after["runtime"] = "cloudfront-js-1.0"
        self.assertEqual(
            validate_plan(plan, manifest)["reason_code"], "unsupported_field_delta"
        )

    def test_current_loader_release_changes_only_package_hash(self) -> None:
        manifest = cast(
            Manifest,
            json.loads(
                (
                    Path(__file__).resolve().parent
                    / "development-release-manifest.json"
                ).read_text()
            ),
        )
        current_loader = lambda_plan()
        current_loader["resource_changes"][0]["change"]["before"]["filename"] = (
            "build/loader.zip"
        )
        current_loader["resource_changes"][0]["change"]["after"]["source_code_hash"] = (
            base64.b64encode(bytes.fromhex(manifest["packages"]["loader.zip"])).decode()
        )
        self.assertEqual(
            validate_plan(current_loader, manifest)["status"],
            "accepted",
        )
        self.assertEqual(
            validate_plan(lambda_plan(), manifest)["reason_code"],
            "manifest_mutation_mismatch",
        )

    def test_manifest_package_order_follows_reviewed_timed_marker(self) -> None:
        legacy = lambda_manifest()
        self.assertEqual(validate_plan(lambda_plan(), legacy)["status"], "accepted")

        timed = copy.deepcopy(legacy)
        timed["deployment_inputs"]["v2/scripts/build_timed_checks_zip.sh"] = HASH
        timed["packages"]["timed-checks.zip"] = HASH
        self.assertEqual(validate_plan(lambda_plan(), timed)["status"], "accepted")

        legacy_extra = copy.deepcopy(legacy)
        legacy_extra["packages"]["timed-checks.zip"] = HASH
        self.assertEqual(
            validate_plan(lambda_plan(), legacy_extra)["reason_code"], "malformed_input"
        )

        timed_missing = copy.deepcopy(timed)
        timed_missing["packages"].pop("timed-checks.zip")
        self.assertEqual(
            validate_plan(lambda_plan(), timed_missing)["reason_code"],
            "malformed_input",
        )

    def test_marker_free_manifest_cannot_declare_timed_contract_entries(self) -> None:
        addresses = (
            "aws_s3_object.timed_checks",
            "aws_lambda_function.timed_checks",
            'aws_scheduler_schedule.timed_checks["greenway-eb-mon-0723"]',
        )
        for address in addresses:
            with self.subTest(address=address):
                spec = CONTRACT[address]
                fields = (
                    ("schedule_expression",)
                    if address.startswith("aws_scheduler")
                    else spec.fields[:2]
                )
                manifest: Manifest = {
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

    def test_lambda_updates_require_exact_development_function_identity(self) -> None:
        fields_by_address = {
            "aws_lambda_function.loader": ("filename", "source_code_hash"),
            "aws_lambda_function.tollchat_proxy": (
                "s3_object_version",
                "source_code_hash",
            ),
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

    def test_accepts_pinned_metadata_and_keeps_drift_out_of_result(self) -> None:
        drift = [
            _resource_change(
                "aws_iam_role.loader", "update", {"name": "old"}, {"name": "new"}
            )
        ]
        plan = lambda_plan()
        cast(dict[str, object], plan).update(
            resource_drift=drift,
            relevant_attributes=[
                {"resource": "aws_iam_role.loader", "attribute": ["name"]}
            ],
        )
        result = validate_plan(plan, lambda_manifest())
        baseline = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result, baseline)

    def test_accepts_equal_identity_metadata_without_output_or_field_deltas(
        self,
    ) -> None:
        plan = lambda_plan()
        identity = {"id": "stable", "version": 1}
        change = plan["resource_changes"][0]["change"]
        cast(dict[str, object], change)["before_identity"] = identity
        cast(dict[str, object], change)["after_identity"] = copy.deepcopy(identity)
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

    def test_rejects_invalid_mismatched_and_production_identity_metadata(self) -> None:
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
            validate_plan(_plan([no_op], applyable=False), lambda_manifest())["status"],
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

    def test_accepts_noop_and_read_resources_with_applyable_false_or_true(self) -> None:
        no_op = _resource_change(
            "aws_acm_certificate.site[0]",
            "no-op",
            {"domain_name": "dev.tollchat.ai"},
            {"domain_name": "dev.tollchat.ai"},
        )
        read = _resource_change("aws_iam_role.loader", "read", None, None)
        read["address"] = "data.aws_iam_role.loader"
        read["mode"] = "data"
        for applyable in (False, True):
            with self.subTest(applyable=applyable):
                result = validate_plan(
                    _plan([no_op, read], applyable=applyable),
                    lambda_manifest(),
                )
                self.assertEqual(result["status"], "accepted")
                self.assertEqual(cast(list[str], result["addresses"]), [])

    def test_rejects_partial_invalid_flags_and_unapplyable_mutation(self) -> None:
        for missing in ("applyable", "complete", "errored"):
            with self.subTest(missing=missing):
                plan = lambda_plan()
                del cast(dict[str, object], plan)[missing]
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

    def test_rejects_malformed_plan_metadata_and_unknown_keys(self) -> None:
        plan = lambda_plan()
        cast(dict[str, object], plan)["unexpected"] = "value"
        self.assert_reason("malformed_input", plan=plan)

        for value in cast(tuple[JSON, ...], ({}, "drift", ["not-a-resource"])):
            with self.subTest(resource_drift=value):
                plan = lambda_plan()
                cast(dict[str, object], plan)["resource_drift"] = value
                self.assert_reason(
                    "malformed_input",
                    plan=plan,
                )

        valid_drift = _resource_change(
            "aws_iam_role.loader", "update", {"name": "old"}, {"name": "new"}
        )
        for mutation in (
            {"unknown": True},
            {"provider_name": "registry.terraform.io/hashicorp/random"},
            {"deposed": "0"},
        ):
            with self.subTest(mutation=mutation):
                drift = copy.deepcopy(valid_drift)
                cast(dict[str, object], drift).update(mutation)
                plan = lambda_plan()
                cast(dict[str, object], plan)["resource_drift"] = [drift]
                self.assert_reason(
                    "malformed_input",
                    plan=plan,
                )

        for value in cast(
            tuple[JSON, ...],
            (
                {},
                [{"resource": "x"}],
                [{"resource": "", "attribute": []}],
                [{"resource": "x", "attribute": [1]}],
            ),
        ):
            with self.subTest(relevant_attributes=value):
                plan = lambda_plan()
                cast(dict[str, object], plan)["relevant_attributes"] = value
                self.assert_reason(
                    "malformed_input",
                    plan=plan,
                )

    def test_accepts_each_derived_unknown_edge_with_exact_provenance(self) -> None:
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
        self.assertNotEqual(
            result["fingerprint"], validate_plan(changed, manifest)["fingerprint"]
        )

        plan, manifest = _derived_fixture(
            0,
            expression_path="agent_runtime_artifact.0.code_configuration.0.code.0.s3.0.version_id",
        )
        plan["resource_changes"][0]["change"]["after_unknown"] = {
            "agent_runtime_artifact[0].code_configuration[0].code[0].s3[0].version_id": True,
        }
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")

    def test_runtime_identity_metadata_omission_requires_fixed_direct_name(
        self,
    ) -> None:
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

        for value in cast(
            tuple[JSON, ...],
            (
                None,
                "wrong-runtime-name",
                ["wrong-runtime-name"],
                {},
                {"agent_runtime_name": "wrong-runtime-name"},
                {"agent_runtime_name": "nova_toll_v2_development", "extra": "value"},
            ),
        ):
            with self.subTest(identity=value):
                rejected = copy.deepcopy(plan)
                cast(
                    dict[str, object], rejected["resource_changes"][0]["change"]
                ).update(
                    before_identity=copy.deepcopy(value),
                    after_identity=copy.deepcopy(value),
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
                    cast(
                        dict[str, JSON], rejected["resource_changes"][0]["change"][side]
                    ).pop("agent_runtime_name")
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

    def test_runtime_noop_without_identity_requires_known_unchanged_values(
        self,
    ) -> None:
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

        for value in cast(
            tuple[JSON, ...], (None, {}, {"agent_runtime_name": "wrong-runtime-name"})
        ):
            with self.subTest(value=value):
                rejected = copy.deepcopy(plan)
                cast(
                    dict[str, object], rejected["resource_changes"][0]["change"]
                ).update(before=copy.deepcopy(value), after=copy.deepcopy(value))
                self.assert_reason(
                    "invalid_resource_identity", plan=rejected, manifest=manifest
                )

    def test_rejects_derived_unknown_without_exact_provenance_or_producer(self) -> None:
        for label, kwargs in (
            ("missing_configuration", {"configuration": False}),
            (
                "wrong_expression_path",
                {
                    "expression_path": "agent_runtime_artifact.code_configuration.code.s3.key"
                },
            ),
            (
                "wrong_reference",
                {"reference": "aws_s3_object.agentcore.version_id.value"},
            ),
            ("different_resource", {"resource_address": "aws_s3_object.agentcore"}),
        ):
            with self.subTest(label=label):
                plan, manifest = _derived_fixture(0, **cast(DerivedOptions, kwargs))
                self.assert_reason(
                    "unknown_authorization_value", plan=plan, manifest=manifest
                )

        plan, manifest = _derived_fixture(0)
        plan["resource_changes"] = plan["resource_changes"][:1]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0, producer_action="no-op")
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        producer = plan["resource_changes"].pop()
        cast(dict[str, object], plan)["resource_drift"] = [producer]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        producer = plan["resource_changes"][1]
        producer["address"] = "data.aws_s3_object.agentcore"
        producer["mode"] = "data"
        producer["change"]["actions"] = ["read"]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

    def test_rejects_arbitrary_unknown_contract_and_authorization_paths(self) -> None:
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
        expression = cast(
            dict[str, JSON],
            cast(
                dict[str, JSON],
                cast(
                    list[JSON],
                    cast(
                        dict[str, JSON],
                        cast(
                            dict[str, JSON],
                            cast(dict[str, JSON], plan)["configuration"],
                        )["root_module"],
                    )["resources"],
                )[0],
            )["expressions"],
        )["agent_runtime_artifact.code_configuration.code.s3.version_id"]
        cast(list[JSON], cast(dict[str, JSON], expression)["references"]).append(
            "aws_s3_object.agentcore.source"
        )
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        expression = cast(
            dict[str, JSON],
            cast(
                dict[str, JSON],
                cast(
                    list[JSON],
                    cast(
                        dict[str, JSON],
                        cast(
                            dict[str, JSON],
                            cast(dict[str, JSON], plan)["configuration"],
                        )["root_module"],
                    )["resources"],
                )[0],
            )["expressions"],
        )["agent_runtime_artifact.code_configuration.code.s3.version_id"]
        cast(dict[str, JSON], expression)["references"] = [
            "aws_s3_object.agentcore.version_id",
            "aws_s3_object.agentcore.version_id",
        ]
        self.assert_reason("unknown_authorization_value", plan=plan, manifest=manifest)

        plan, manifest = _derived_fixture(0)
        cast(
            dict[str, JSON],
            cast(
                dict[str, JSON],
                cast(
                    list[JSON],
                    cast(
                        dict[str, JSON],
                        cast(
                            dict[str, JSON],
                            cast(dict[str, JSON], plan)["configuration"],
                        )["root_module"],
                    )["resources"],
                )[0],
            )["expressions"],
        )["agent_runtime_artifact.0.code_configuration.0.code.0.s3.0.version_id"] = {
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
                self.assert_reason(
                    "unknown_authorization_value", plan=plan, manifest=manifest
                )

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
                cast(dict[str, object], plan["resource_changes"][0]["change"])[
                    "after_unknown"
                ] = unknown
                self.assert_reason(
                    "unknown_authorization_value", plan=plan, manifest=manifest
                )

    def test_ignores_non_contract_computed_unknowns_without_output_or_fingerprint_delta(
        self,
    ) -> None:
        plan = lambda_plan(last_modified="new")
        plan["resource_changes"][0]["change"]["after_unknown"] = {"last_modified": True}
        result = validate_plan(plan, lambda_manifest())
        baseline = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result, baseline)
        self.assertNotIn("last_modified", json.dumps(result))

    def test_ignores_non_contract_computed_unknowns_on_create_fingerprint(self) -> None:
        address = "aws_s3_object.agentcore"
        after: dict[str, JSON] = {
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

    def test_derived_unknown_provenance_is_independent_of_resource_order(self) -> None:
        plan, manifest = _derived_fixture(2)
        first = validate_plan(plan, manifest)
        reordered = copy.deepcopy(plan)
        reordered["resource_changes"].reverse()
        second = validate_plan(reordered, manifest)
        self.assertEqual(first, second)

    def test_accepts_one_fixture_for_every_contract_entry(self) -> None:
        for address, spec in CONTRACT.items():
            if address in shared_packages.RESOURCES | {shared_packages.CHAT_ROUTES}:
                # Real composed shared-package plans live in test_shared_packages.py.
                continue
            if spec.operation_class.startswith("agentcore-trace-"):
                continue
            if spec.operation_class in {"cost-publication", "cost-routing"}:
                # Billing uses provider-generated plans and authority mutations in
                # v2/tests/test_cost_dashboard_release.py, not placeholder values.
                continue
            action = spec.actions[0]
            timed = address.startswith(
                'aws_scheduler_schedule.timed_checks["'
            ) or address in {
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
            elif address in {
                "aws_s3_object.index",
                "aws_s3_object.faq",
                "aws_s3_object.privacy",
            }:
                fields = ("content",)
            else:
                fields = (spec.fields[0],)
            before: dict[str, JSON] | None = None if action == "create" else {}
            after: dict[str, JSON] = {}
            if address.startswith('aws_scheduler_schedule.timed_checks["'):
                after = timed_schedule_plan_value(address)
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
            plan = _plan([_resource_change(address, action, before, after)])
            manifest: Manifest = {
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
                normalized["resource_changes"][0]["change"]["after"][
                    "alarm_actions"
                ] = None
                if not after["dimensions"]:
                    normalized["resource_changes"][0]["change"]["after"][
                        "dimensions"
                    ] = None
                self.assertEqual(
                    validate_plan(normalized, manifest)["status"], "accepted", address
                )
            if spec.operation_class.startswith("telemetry-"):
                for field in after:
                    mutant = copy.deepcopy(plan)
                    mutant["resource_changes"][0]["change"]["after"][field] = (
                        "unreviewed"
                    )
                    self.assertEqual(
                        validate_plan(mutant, manifest)["status"],
                        "rejected",
                        (address, field),
                    )
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

    def test_agentcore_trace_runtime_policy_only_adds_required_permission(self) -> None:
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
        before: dict[str, JSON] = {**identity, "policy": json.dumps(baseline)}
        after: dict[str, JSON] = {
            **identity,
            "policy": json.dumps(
                {**baseline, "Statement": [*baseline["Statement"], trace_statement]}
            ),
        }
        plan = _plan([_resource_change(address, "update", before, after)])
        manifest = _mutation_manifest([(address, "update", ("policy",))])
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
        tampered = copy.deepcopy(plan)
        tampered_statement = json.loads(
            cast(str, tampered["resource_changes"][0]["change"]["after"]["policy"])
        )
        tampered_statement["Statement"][-1]["Action"] = "logs:*"
        tampered["resource_changes"][0]["change"]["after"]["policy"] = json.dumps(
            tampered_statement
        )
        self.assertEqual(
            validate_plan(tampered, manifest)["reason_code"],
            "unsupported_field_delta",
        )
        malformed = copy.deepcopy(plan)
        malformed["resource_changes"][0]["change"]["after"]["policy"] = "{not json"
        self.assertEqual(validate_plan(malformed, manifest)["status"], "rejected")

    def test_agentcore_trace_initial_and_recovery_fixtures_are_finite(self) -> None:
        subscriptions: dict[str, JSON] = {
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
        baseline_rules: list[JSON] = [
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
        trace_rule: dict[str, JSON] = {
            "id": "expire-agentcore-traces",
            "status": "Enabled",
            "filter": [{"prefix": TRACE_PREFIX}],
            "expiration": [{"days": 7}],
            "abort_incomplete_multipart_upload": [{"days_after_initiation": 1}],
        }
        runtime_before: dict[str, JSON] = {
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
        initial: dict[str, JSON] = {
            "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]": dict[str, JSON](
                {
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
                    "tags_all": dict[str, JSON](TRACE_TAGS),
                    "timeouts": None,
                }
            ),
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

        def manifest_for(
            values: dict[str, JSON], chosen_actions: dict[str, str]
        ) -> Manifest:
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
                cast(dict[str, object], resource["change"])["before_sensitive"] = False
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
            validate_plan(partitioned_catalog, manifest_for(initial, actions))[
                "reason_code"
            ],
            "unsupported_field_delta",
        )

        recovery_values: dict[str, JSON] = {
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
            "environment_variables": runtime_before,
        }
        recovery_actions["aws_bedrockagentcore_agent_runtime.tollchat"] = "update"
        recovery_plan = _plan(
            [
                _resource_change(
                    address,
                    recovery_actions[address],
                    initial[address],
                    None if recovery_actions[address] == "delete" else value,
                )
                for address, value in recovery_values.items()
            ]
        )
        for resource in recovery_plan["resource_changes"]:
            if resource["change"]["actions"] == ["delete"]:
                cast(dict[str, object], resource["change"])["after_sensitive"] = False
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
        cast(
            dict[str, JSON],
            cast(list[JSON], firehose_delete["before"]["extended_s3_configuration"])[0],
        )["cloudwatch_logging_options"] = []
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
        cast(
            dict[str, JSON],
            next(
                item
                for item in wrong_identity["resource_changes"]
                if item["address"]
                == 'aws_cloudwatch_log_subscription_filter.agentcore_traces["DEFAULT"]'
            )["change"]["before_identity"],
        )["name"] = "other"
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
            node: JSON = next(
                item
                for item in rejected["resource_changes"]
                if item["address"] == address
            )["change"][cast(Literal["before", "after"], side)]
            for part in path[:-1]:
                node = (
                    cast(list[JSON], node)[part]
                    if isinstance(part, int)
                    else cast(dict[str, JSON], node)[part]
                )
            cast(dict[str, JSON], node)[path[-1]] = cast(JSON, value)
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
        cast(
            dict[str, JSON],
            next(
                item
                for item in altered_tags["resource_changes"]
                if item["address"]
                == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
            )["change"]["after"]["tags_all"],
        )["environment"] = "other"
        self.assertEqual(
            validate_plan(altered_tags, manifest_for(initial, actions))["reason_code"],
            "unsupported_field_delta",
        )
        altered_default = copy.deepcopy(initial_plan)
        cast(
            dict[str, JSON],
            cast(
                list[JSON],
                next(
                    item
                    for item in altered_default["resource_changes"]
                    if item["address"]
                    == "aws_kinesis_firehose_delivery_stream.agentcore_traces[0]"
                )["change"]["after"]["extended_s3_configuration"],
            )[0],
        )["buffering_size"] = 6
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
                node = (
                    cast(list[JSON], node)[part]
                    if isinstance(part, int)
                    else cast(dict[str, JSON], node)[part]
                )
            cast(dict[str, JSON], node)[path[-1]] = attacker
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

    def test_slot_preparation_uses_private_failure_reporting(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-development-delivery-privileged.yml"
        ).read_text()
        self.assertIn('run_private_stage "plan" "$PLAN_LOG" "$PLAN_LOG"', workflow)
        self.assertIn("release_blue_green.py prepare-plan", workflow)
        self.assertIn("release_blue_green.py finish", workflow)
        self.assertIn(
            "jq '{deployment,recovery,active,probes,releases,recovery_record,shared_components}'",
            workflow,
        )
        self.assertNotIn('cat "$PLAN_LOG"', workflow)

    def test_existing_trace_subscription_identity_pins_account_and_region(self) -> None:
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
            cast(dict[str, object], record["change"])[side] = copy.deepcopy(identity)
        plan = _plan([record])
        manifest = _mutation_manifest(())
        self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
        for side in ("before_identity", "after_identity"):
            for field in ("account_id", "region"):
                invalid = copy.deepcopy(plan)
                cast(dict[str, JSON], invalid["resource_changes"][0]["change"][side])[
                    field
                ] = "wrong"
                self.assertEqual(
                    validate_plan(invalid, manifest)["reason_code"],
                    "invalid_resource_identity",
                )

    def test_trace_notices_allow_legacy_noops_before_rollout(self) -> None:
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
                self.assert_reason(
                    "malformed_input", plan=rejected, manifest=_mutation_manifest(())
                )

        plan["resource_changes"].extend(lambda_plan()["resource_changes"])
        self.assertEqual(validate_plan(plan, lambda_manifest())["status"], "accepted")
        plan["applyable"] = False
        self.assert_reason("malformed_input", plan=plan, manifest=lambda_manifest())

    def test_committed_development_manifest_covers_full_package_graph(self) -> None:
        manifest = json.loads(
            (
                Path(__file__).resolve().parent / "development-release-manifest.json"
            ).read_text(encoding="utf-8")
        )
        expected_mutations: dict[str, tuple[str, tuple[str, ...]]] = {
            "aws_lambda_function.loader": ("lambda-code", ("source_code_hash",)),
            "aws_s3_object.agentcore": ("artifact-upload", ("source_hash",)),
            "aws_s3_object.tollchat_proxy": ("artifact-upload", ("source_hash",)),
            'aws_s3_object.site_assets["coverage-locations.json"]': (
                "site-asset-upload",
                ("source_hash",),
            ),
            "aws_lambda_function.tollchat_proxy": (
                "lambda-code",
                ("s3_object_version", "source_code_hash"),
            ),
            "aws_s3_object.timed_checks": ("artifact-upload", ("source_hash",)),
            "aws_lambda_function.timed_checks": (
                "lambda-code",
                ("s3_object_version", "source_code_hash"),
            ),
            "aws_lambda_alias.tollchat_live": ("lambda-alias", ("function_version",)),
            "aws_bedrockagentcore_agent_runtime.tollchat": (
                "agentcore-code",
                ("agent_runtime_artifact.code_configuration.code.s3.version_id",),
            ),
            "aws_bedrockagentcore_agent_runtime_endpoint.tollchat": (
                "agentcore-endpoint",
                ("agent_runtime_version",),
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
        expected_mutations["aws_bedrockagentcore_agent_runtime.tollchat"] = (
            "agentcore-code",
            ("agent_runtime_artifact.code_configuration.code.s3.version_id",),
        )
        for name in ("index", "faq", "privacy"):
            expected_mutations[f"aws_s3_object.{name}"] = (
                "site-object-upload",
                ("content",),
            )
        for address, spec in CONTRACT.items():
            if spec.operation_class.startswith("telemetry-"):
                fields = {
                    "telemetry-log-protection": ("log_group_name", "policy_document"),
                    "telemetry-failure-metric": (
                        "log_group_name",
                        "metric_transformation",
                        "name",
                        "pattern",
                    ),
                    "telemetry-alarm": (
                        "alarm_actions",
                        "alarm_description",
                        "alarm_name",
                        "comparison_operator",
                        "dimensions",
                        "evaluation_periods",
                        "metric_name",
                        "namespace",
                        "period",
                        "statistic",
                        "tags",
                        "threshold",
                        "treat_missing_data",
                    ),
                }[spec.operation_class]
                expected_mutations[address] = (spec.operation_class, fields)
        expected_mutations.update(
            {
                "aws_cloudfront_function.public_chat_routes": (
                    "cloudfront-code",
                    ("code",),
                ),
                "aws_cloudfront_function.public_report_routes": (
                    "cloudfront-code",
                    ("code",),
                ),
                "aws_s3_object.evals": ("site-object-upload", ("content",)),
                **{
                    f'aws_s3_object.site_assets["{name}"]': (
                        "site-asset-upload",
                        ("cache_control", "content_type", "source", "source_hash"),
                    )
                    for name in ("evals.css", "evals.mjs")
                },
            }
        )
        for address, spec in CONTRACT.items():
            if spec.operation_class in {"cost-publication", "cost-routing"}:
                if (
                    address.startswith(
                        (
                            "aws_cloudwatch_log_metric_filter.costs_",
                            "aws_cloudwatch_metric_alarm.costs_",
                        )
                    )
                    and f'"{address.split(".", 1)[1].split("[", 1)[0]}"'
                    not in (
                        Path(__file__).parent.parent / "v2/infra/costs.tf"
                    ).read_text()
                ):
                    continue  # Admit the fixed alert contract before activation.
                deferred_asset = next(
                    (
                        asset
                        for asset in ("evals.css", "costs-benchmark.json")
                        if address == f'aws_s3_object.cost_assets["{asset}"]'
                    ),
                    None,
                )
                if (
                    deferred_asset
                    and f'"{deferred_asset}"'
                    not in (
                        Path(__file__).parent.parent / "v2/infra/costs.tf"
                    ).read_text()
                ):
                    continue  # Policy is admitted before the frontend adds this asset.
                expected_mutations[address] = (
                    spec.operation_class,
                    tuple(sorted(spec.fields)),
                )
        for address, field in {
            "aws_lambda_function.costs": "source_code_hash",
            "aws_iam_role_policy.costs": "policy",
            "aws_cloudwatch_event_rule.costs": "schedule_expression",
            "aws_s3_object.cost_dashboard": "content",
            'aws_s3_object.cost_assets["costs.css"]': "source_hash",
            'aws_s3_object.cost_assets["costs.mjs"]': "source_hash",
        }.items():
            expected_mutations[address] = ("cost-publication", (field,))
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

        def update(address: str) -> Resource:
            fields = expected_mutations[address][1]
            if address in shared_packages.RESOURCES:
                row = _mutation_change(address, fields)
                package = (
                    "timed-checks.zip"
                    if address == shared_packages.OBJECT
                    else shared_packages.FUNCTIONS[address.rsplit(".", 1)[1]][1]
                )
                hash_field = (
                    "source_hash"
                    if address == shared_packages.OBJECT
                    else "source_code_hash"
                )
                row["change"]["after"][hash_field] = base64.b64encode(
                    bytes.fromhex(manifest["packages"][package])
                ).decode()
                if address in {
                    shared_packages.OBJECT,
                    "aws_lambda_function.timed_checks",
                }:
                    version_field = (
                        "version_id"
                        if address == shared_packages.OBJECT
                        else "s3_object_version"
                    )
                    row["change"]["before"][version_field] = "old-version"
                    row["change"]["after"][version_field] = None
                    row["change"]["after_unknown"][version_field] = True
                return row
            spec = CONTRACT[address]
            before: dict[str, JSON] = {}
            after: dict[str, JSON] = {}
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
                after["environment_variables"] = dict(
                    cast(dict[str, JSON], before["environment_variables"])
                )
                cast(dict[str, JSON], before["environment_variables"]).update(
                    TOLLCHAT_TELEMETRY_GUARDRAIL_ID="testid",
                    TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION="1",
                )
                after["environment_variables"] = dict(
                    cast(dict[str, JSON], before["environment_variables"])
                )
            return _resource_change(address, "update", before, after)

        plan = _plan([update(address) for address in committed_updates])
        plan["configuration"] = {
            "root_module": {
                "resources": [
                    {
                        "address": "aws_lambda_function.timed_checks",
                        "expressions": {
                            "s3_object_version": {
                                "references": [
                                    "aws_s3_object.timed_checks",
                                    "aws_s3_object.timed_checks.version_id",
                                ]
                            }
                        },
                    }
                ]
            }
        }

        accepted = validate_plan(plan, manifest)
        self.assertEqual(accepted["status"], "accepted", accepted)
        self.assertEqual(accepted["reason_code"], "ok")
        self.assertEqual(accepted["addresses"], sorted(committed_updates))

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

    def test_dashboard_create_computed_acl_requires_omitted_configuration(self) -> None:
        manifest = json.loads(
            (Path(__file__).parent / "development-release-manifest.json").read_text()
        )
        # The current release updates the existing page. Retain coverage of the
        # original create boundary using its own declaration.
        next(
            row
            for row in manifest["mutations"]
            if row["address"] == "aws_s3_object.evals"
        ).update(
            action="create", changed_fields=list(CONTRACT["aws_s3_object.evals"].fields)
        )
        for address in (
            "aws_s3_object.evals",
            'aws_s3_object.site_assets["evals.css"]',
            'aws_s3_object.site_assets["evals.mjs"]',
        ):
            spec = CONTRACT[address]
            after: dict[str, JSON] = {
                **dict(spec.create_identity),
                **{field: None for field in spec.fields},
            }
            resource = _resource_change(address, "create", None, after)
            resource["change"]["after_unknown"] = {"acl": True}
            config = {
                "address": address.split("[", 1)[0],
                "expressions": {"bucket": {"constant_value": after["bucket"]}},
            }
            plan = _plan(
                [resource], configuration={"root_module": {"resources": [config]}}
            )
            self.assertEqual(validate_plan(plan, manifest)["status"], "accepted")
            for acl in ({"references": ["var.acl"]}, {"constant_value": "public-read"}):
                cast(dict[str, JSON], config["expressions"])["acl"] = cast(JSON, acl)
                self.assertEqual(
                    validate_plan(plan, manifest)["reason_code"],
                    "unknown_authorization_value",
                )
            cast(dict[str, JSON], config["expressions"]).pop("acl")
            plan.pop("configuration")
            self.assertEqual(
                validate_plan(plan, manifest)["reason_code"],
                "unknown_authorization_value",
            )

    def test_committed_manifest_covers_coverage_asset_update_subset(self) -> None:
        address = 'aws_s3_object.site_assets["coverage-locations.json"]'
        manifest = json.loads(
            (
                Path(__file__).resolve().parent / "development-release-manifest.json"
            ).read_text(encoding="utf-8")
        )
        before: dict[str, JSON] = {
            "source": "v2/agent/assets/coverage-locations.json",
            "source_hash": "old",
            **dict(CONTRACT[address].create_identity),
        }
        plan = _plan(
            [
                _resource_change(
                    address, "update", before, dict(before, source_hash="new")
                )
            ]
        )
        accepted = validate_plan(plan, manifest)
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["reason_code"], "ok")
        self.assertEqual(accepted["addresses"], [address])
        self.assertEqual(accepted["actions"], ["update"])
        self.assertEqual(accepted["operation_classes"], ["site-asset-upload"])

        missing_mutation = copy.deepcopy(manifest)
        missing_mutation["mutations"] = [
            record
            for record in missing_mutation["mutations"]
            if record["address"] != address
        ]
        self.assertEqual(
            validate_plan(plan, missing_mutation),
            {"status": "rejected", "reason_code": "manifest_coverage_mismatch"},
        )

        missing_permission = copy.deepcopy(manifest)
        missing_permission["permissions"] = [
            record
            for record in missing_permission["permissions"]
            if record["address"] != address
        ]
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
                self.assertFalse(
                    {"before", "after", "source", "source_hash"} & set(result)
                )

        mutations: tuple[tuple[str, Callable[[PermissionRecord], object], str], ...] = (
            (
                "action",
                lambda permission: permission.update(action="s3:GetObject"),
                "invalid_permission",
            ),
            (
                "broad_resource",
                lambda permission: permission.update(resource="*"),
                "invalid_permission",
            ),
            (
                "different_resource",
                lambda permission: permission.update(
                    resource="arn:aws:s3:::unrelated-bucket/*"
                ),
                "invalid_permission",
            ),
            (
                "conditions",
                lambda permission: permission.update(conditions={"extra": "value"}),
                "invalid_permission",
            ),
            ("duplicate", lambda permission: None, "missing_permission"),
        )
        for label, mutate, reason in mutations:
            with self.subTest(gate=label):
                rejected_manifest = copy.deepcopy(manifest)
                permission = next(
                    record
                    for record in rejected_manifest["permissions"]
                    if record["address"] == address
                )
                mutate(permission)
                if label == "duplicate":
                    rejected_manifest["permissions"].append(copy.deepcopy(permission))
                result = validate_plan(plan, rejected_manifest)
                self.assertEqual(result["reason_code"], reason)
                self.assertFalse(
                    {"before", "after", "source", "source_hash"} & set(result)
                )

    def test_timed_schedule_updates_require_fixed_enabled_target(self) -> None:
        address = 'aws_scheduler_schedule.timed_checks["greenway-eb-mon-0723"]'
        spec = CONTRACT[address]
        after = timed_schedule_plan_value(address)
        before = copy.deepcopy(after)
        before["schedule_expression"] = "cron(0 0 ? * SUN *)"
        manifest: Manifest = {
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
            validate_plan(
                _plan([_resource_change(address, "update", before, after)]), manifest
            )["status"],
            "accepted",
        )

        missing_passrole = copy.deepcopy(manifest)
        missing_passrole["permissions"] = [
            record
            for record in missing_passrole["permissions"]
            if record["action"] != "iam:PassRole"
        ]
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", before, after)]),
                missing_passrole,
            )["reason_code"],
            "missing_permission",
        )

        widened_passrole = copy.deepcopy(manifest)
        next(
            record
            for record in widened_passrole["permissions"]
            if record["action"] == "iam:PassRole"
        )["resource"] = "*"
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", before, after)]),
                widened_passrole,
            )["reason_code"],
            "invalid_permission",
        )

        wrong_service = copy.deepcopy(manifest)
        next(
            record
            for record in wrong_service["permissions"]
            if record["action"] == "iam:PassRole"
        )["conditions"] = {"iam:PassedToService": "events.amazonaws.com"}
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", before, after)]),
                wrong_service,
            )["reason_code"],
            "invalid_permission",
        )

        wrong_role = copy.deepcopy(manifest)
        next(
            record
            for record in wrong_role["permissions"]
            if record["action"] == "iam:PassRole"
        )[
            "resource"
        ] = "arn:aws:iam::903859731897:role/nova-toll-v2-timed-checks-scheduler-other"
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", before, after)]), wrong_role
            )["reason_code"],
            "invalid_permission",
        )

        wrong_condition_key = copy.deepcopy(manifest)
        next(
            record
            for record in wrong_condition_key["permissions"]
            if record["action"] == "iam:PassRole"
        )["conditions"] = {"iam:PassedToServiceCondition": "scheduler.amazonaws.com"}
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", before, after)]),
                wrong_condition_key,
            )["reason_code"],
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
            validate_plan(
                _plan([_resource_change(address, "update", before, after)]),
                orphan_permission,
            )["reason_code"],
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
                _plan(
                    [
                        _resource_change(
                            address, "update", provider_before, provider_after
                        )
                    ]
                ),
                manifest,
            )["status"],
            "accepted",
        )
        self.assertEqual(provider_after, provider_snapshot)

        def assert_invalid_provider_value(
            candidate: object, changed_field: str
        ) -> None:
            invalid_manifest = copy.deepcopy(manifest)
            cast(dict[str, JSON], cast(list[JSON], invalid_manifest["mutations"])[0])[
                "changed_fields"
            ] = [changed_field]
            self.assertEqual(
                validate_plan(
                    _plan(
                        [_resource_change(address, "update", provider_after, candidate)]
                    ),
                    invalid_manifest,
                )["reason_code"],
                "invalid_schedule_value",
            )

        for value in cast(tuple[JSON, ...], (0, -1, False, 1, True, "0", [], {})):
            invalid_window = copy.deepcopy(provider_after)
            invalid_window["flexible_time_window"][0]["maximum_window_in_minutes"] = (
                value
            )
            assert_invalid_provider_value(invalid_window, "flexible_time_window")

        for field in (
            "ecs_parameters",
            "eventbridge_parameters",
            "kinesis_parameters",
            "sagemaker_pipeline_parameters",
            "sqs_parameters",
        ):
            for value in cast(
                tuple[JSON, ...], (None, {}, [{}], [{"unexpected": "value"}], "[]")
            ):
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
        cast(dict[str, JSON], cast(list[JSON], disabled_manifest["mutations"])[0])[
            "changed_fields"
        ] = ["state"]
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", after, disabled)]),
                disabled_manifest,
            )["reason_code"],
            "invalid_schedule_value",
        )

        retargeted = copy.deepcopy(after)
        retargeted["target"][0]["arn"] = (
            "arn:aws:lambda:us-east-1:903859731897:function:evil"
        )
        retargeted_manifest = copy.deepcopy(manifest)
        cast(dict[str, JSON], cast(list[JSON], retargeted_manifest["mutations"])[0])[
            "changed_fields"
        ] = ["target"]
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", after, retargeted)]),
                retargeted_manifest,
            )["reason_code"],
            "invalid_schedule_value",
        )

        extended_target = copy.deepcopy(after)
        extended_target["target"][0]["sqs_parameters"] = [
            {"message_group_id": "unexpected"}
        ]
        self.assertEqual(
            validate_plan(
                _plan([_resource_change(address, "update", after, extended_target)]),
                retargeted_manifest,
            )["reason_code"],
            "invalid_schedule_value",
        )

    def test_rejects_lambda_configuration_disguised_as_code(self) -> None:
        plan = lambda_plan(runtime="python3.13")
        self.assert_reason("unsupported_field_delta", plan=plan)

    def test_candidate_report_routes_do_not_target_production(self) -> None:
        code = (
            Path(__file__).resolve().parents[1] / "v2/agent/public-report-routes.js"
        ).read_text()
        value: dict[str, JSON] = {
            "name": "tollchat-v2-public-report-routes-dev",
            "code": code,
        }
        plan = _plan(
            [
                _resource_change(
                    "aws_cloudfront_function.public_report_routes",
                    "no-op",
                    value,
                    value,
                )
            ]
        )
        result = validate_plan(plan, lambda_manifest())
        self.assertEqual(result["status"], "accepted", result)

    def test_report_routes_repair_accepts_only_exact_development_transition(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        code = (root / "v2/agent/public-report-routes.js").read_text()
        legacy = LEGACY_REPORT_ROUTES_CODE
        address = "aws_cloudfront_function.public_report_routes"
        after: dict[str, JSON] = {
            "name": "tollchat-v2-public-report-routes-dev",
            "arn": "arn:aws:cloudfront::903859731897:function/tollchat-v2-public-report-routes-dev",
            "runtime": "cloudfront-js-2.0",
            "publish": True,
            "comment": "Resolve canonical TollChat report directories",
            "code": code,
        }
        before = dict(after, code=legacy)
        plan = _plan([_resource_change(address, "update", before, after)])
        manifest = json.loads(
            (root / "infra/development-release-manifest.json").read_text()
        )
        result = validate_plan(plan, manifest)
        self.assertEqual(result["status"], "accepted", result)

        publishing = copy.deepcopy(plan)
        change = publishing["resource_changes"][0]["change"]
        for field in ("etag", "live_stage_etag", "status"):
            change["before"][field] = "previous"
            change["after"][field] = None
            change["after_unknown"][field] = True
        result = validate_plan(publishing, manifest)
        self.assertEqual(result["status"], "accepted", result)

        for side, field, value in (
            ("before", "code", legacy + "\n"),
            ("after", "code", code + "\n"),
            ("after", "code", legacy),
            (
                "before",
                "arn",
                "arn:aws:cloudfront::920534282028:function/tollchat-v2-public-report-routes",
            ),
            (
                "after",
                "arn",
                "arn:aws:cloudfront::920534282028:function/tollchat-v2-public-report-routes",
            ),
            ("before", "name", "other-dev"),
            ("after", "name", "other-dev"),
            ("after", "runtime", "cloudfront-js-1.0"),
            ("after", "publish", False),
            ("after", "comment", "changed"),
            ("before", "runtime", "cloudfront-js-1.0"),
            ("before", "role", "arn:aws:iam::920534282028:role/other"),
        ):
            with self.subTest(side=side, field=field):
                invalid = copy.deepcopy(plan)
                invalid["resource_changes"][0]["change"][side][field] = value
                self.assertEqual(validate_plan(invalid, manifest)["status"], "rejected")
        for action in ("no-op", "create", "delete"):
            with self.subTest(action=action):
                invalid = _plan([_resource_change(address, action, before, before)])
                self.assertEqual(validate_plan(invalid, manifest)["status"], "rejected")
        invalid = copy.deepcopy(plan)
        invalid["resource_changes"][0]["change"]["after_unknown"]["code"] = True
        self.assertEqual(validate_plan(invalid, manifest)["status"], "rejected")
        invalid = copy.deepcopy(plan)
        invalid["resource_changes"][0]["change"]["after_sensitive"]["code"] = True
        self.assertEqual(validate_plan(invalid, manifest)["status"], "rejected")
        invalid = copy.deepcopy(plan)
        invalid["resource_changes"].append(
            _resource_change(
                "aws_cloudfront_function.public_chat_routes", "no-op", before, before
            )
        )
        self.assertEqual(
            validate_plan(invalid, manifest)["reason_code"], "production_target"
        )

    def test_accepts_dormant_production_configuration_and_development_resources(
        self,
    ) -> None:
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
        loader_noop = _mutation_change(
            "aws_lambda_function.loader", ("source_code_hash",)
        )
        loader_noop["change"]["before"] = copy.deepcopy(loader_noop["change"]["after"])
        loader_noop["change"]["actions"] = ["no-op"]
        plan["resource_changes"].append(loader_noop)
        result = validate_plan(plan, lambda_manifest())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["reason_code"], "ok")
        self.assertEqual(cast(list[str], result["addresses"]), [])
        self.assertEqual(cast(list[str], result["actions"]), [])
        self.assertEqual(cast(list[str], result["operation_classes"]), [])
        self.assertEqual(len(cast(str, result["fingerprint"])), 64)
        self.assertEqual(
            set(result),
            {
                "status",
                "reason_code",
                "addresses",
                "actions",
                "operation_classes",
                "fingerprint",
            },
        )

    def test_rejects_malformed_identity_and_input(self) -> None:
        self.assert_reason("malformed_input", plan=[])
        self.assertEqual(
            _validate_plan(lambda_plan(), lambda_manifest())["reason_code"],
            "provider_identity_missing",
        )
        identity = dict(EXPECTED_IDENTITY)
        identity["terraform_version"] = "1.14.0"
        self.assert_reason("provider_identity_mismatch", identity=identity)

        manifest = lambda_manifest()
        del cast(dict[str, object], manifest)["packages"]
        self.assert_reason("unknown_manifest_declaration", manifest=manifest)

        manifest = lambda_manifest()
        manifest["deployment_inputs"] = {"v2/infra/main.tf": "bad"}
        self.assert_reason("malformed_input", manifest=manifest)

    def test_rejects_unlisted_duplicate_and_unknown_values(self) -> None:
        plan = lambda_plan()
        plan["resource_changes"][0]["address"] = "aws_lambda_function.not_declared"
        self.assert_reason("malformed_input", plan=plan)

        duplicate = lambda_plan()["resource_changes"]
        plan = lambda_plan()
        plan["resource_changes"].extend(copy.deepcopy(duplicate))
        self.assert_reason("duplicate_address", plan=plan)

        plan = lambda_plan()
        plan["resource_changes"][0]["change"]["after_unknown"] = {
            "source_code_hash": True
        }
        self.assert_reason("unknown_authorization_value", plan=plan)

        plan = lambda_plan()
        del cast(dict[str, object], plan["resource_changes"][0]["change"])[
            "after_unknown"
        ]
        self.assert_reason("malformed_input", plan=plan)

        plan = lambda_plan()
        plan["resource_changes"][0]["change"]["after_sensitive"] = {"filename": True}
        self.assert_reason("sensitive_authorization_value", plan=plan)

    def test_accepts_s3_object_version_only_lambda_update(self) -> None:
        address = "aws_lambda_function.tollchat_proxy"
        before: dict[str, JSON] = {
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

        plan["resource_changes"][0]["change"]["after"]["s3_key"] = (
            "lambda/v2/redirect.zip"
        )
        manifest["mutations"][0]["changed_fields"].append("s3_key")
        self.assert_reason("invalid_resource_identity", plan=plan, manifest=manifest)

        mixed = copy.deepcopy(plan)
        mixed["resource_changes"][0]["change"]["after"]["s3_key"] = (
            "lambda/v2/chat-proxy-dev.zip"
        )
        mixed["resource_changes"][0]["change"]["after"]["filename"] = "chat-proxy.zip"
        mixed_manifest = copy.deepcopy(manifest)
        mixed_manifest["mutations"][0]["changed_fields"] = [
            "filename",
            "s3_object_version",
            "source_code_hash",
        ]
        self.assert_reason(
            "invalid_resource_identity", plan=mixed, manifest=mixed_manifest
        )

    def test_rejects_filename_lambda_s3_delivery_shape(self) -> None:
        plan = lambda_plan(s3_bucket="redirect", s3_key="lambda.zip")
        manifest = lambda_manifest(
            ("filename", "s3_bucket", "s3_key", "source_code_hash")
        )
        self.assert_reason("invalid_resource_identity", plan=plan, manifest=manifest)

        missing = lambda_plan()
        del missing["resource_changes"][0]["change"]["after"]["s3_key"]
        self.assert_reason("invalid_resource_identity", plan=missing)

    def test_accepts_only_complete_fixed_production_control_inputs(self) -> None:
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
        self.assert_reason(
            "production_target", manifest=manifest, identity=production_identity
        )

    def test_rejects_realized_production_markers_at_boundaries(self) -> None:
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
                    json.dumps(
                        {
                            key: value
                            for key, value in result.items()
                            if key != "reason_code"
                        }
                    ),
                )

    def test_rejects_production_moved_deposed_import_replacement_and_delete(
        self,
    ) -> None:
        plan = lambda_plan()
        plan["resource_changes"][0]["change"]["after"]["filename"] = (
            "arn:aws:lambda:us-east-1:920534282028:function:prod"
        )
        self.assert_reason("production_target", plan=plan)

        plan = lambda_plan()
        cast(dict[str, object], plan["resource_changes"][0])["previous_address"] = (
            "aws_lambda_function.old"
        )
        self.assert_reason("moved_resource", plan=plan)

        plan = lambda_plan()
        cast(dict[str, object], plan["resource_changes"][0])["deposed"] = "0"
        self.assert_reason("deposed_resource", plan=plan)

        for action, reason in (
            (["import"], "import_or_refresh"),
            (["update", "create"], "replacement"),
            (["delete"], "delete_not_permitted"),
        ):
            plan = lambda_plan()
            plan["resource_changes"][0]["change"]["actions"] = action
            self.assert_reason(reason, plan=plan)

    def test_requires_manifest_mutation_and_distinct_permission(self) -> None:
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
        plan = _plan(
            [
                _resource_change(
                    address, "update", {"tags": {"old": "1"}}, {"tags": {"new": "1"}}
                )
            ]
        )
        manifest: Manifest = {
            **manifest_header(),
            "mutations": [
                {
                    "address": address,
                    "action": "update",
                    "operation_class": spec.operation_class,
                    "changed_fields": ["tags"],
                }
            ],
            "permissions": [
                {
                    "address": address,
                    "action": spec.permissions[0].action,
                    "resource": spec.permissions[0].resources[0],
                    "conditions": {},
                },
                {
                    "address": address,
                    "action": spec.permissions[0].action,
                    "resource": spec.permissions[0].resources[0],
                    "conditions": {},
                },
            ],
        }
        self.assert_reason("duplicate_permission", plan=plan, manifest=manifest)

    def test_subset_retry_accepts_plan_subset_but_validates_all_declarations(
        self,
    ) -> None:
        result = validate_plan(lambda_plan(), lambda_manifest())
        self.assertEqual(result["status"], "accepted")

        manifest = lambda_manifest()
        alias_declaration: Declaration = {
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

    def test_accepts_normal_create_shape_without_authorizing_computed_fields(
        self,
    ) -> None:
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
            plan = _plan(
                [
                    _resource_change(
                        address, "create", None, after, after_unknown={"id": True}
                    )
                ]
            )
            manifest: Manifest = {
                **manifest_header(),
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
            self.assertEqual(
                validate_plan(plan, manifest)["status"], "accepted", address
            )

    def test_s3_create_identity_is_exact_for_every_object_entry(self) -> None:
        for address, spec in CONTRACT.items():
            if address in {
                "aws_s3_object.index",
                "aws_s3_object.faq",
                "aws_s3_object.privacy",
                "aws_s3_object.timed_checks",
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
            after: dict[str, JSON] = {
                fields[0]: "source",
                fields[1]: "hash",
                **dict(spec.create_identity),
            }
            plan = _plan([_resource_change(address, "create", None, after)])
            manifest: Manifest = {
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
            self.assertEqual(
                validate_plan(plan, manifest)["status"], "accepted", address
            )

            redirected = dict(after, key="runtime/v2/unauthorized.py")
            redirected_plan = _plan(
                [_resource_change(address, "create", None, redirected)]
            )
            self.assertEqual(
                validate_plan(redirected_plan, manifest)["reason_code"],
                "invalid_resource_identity",
                address,
            )

            before_update = {
                fields[0]: "old",
                fields[1]: "old",
                **dict(spec.create_identity),
            }
            after_update = {
                fields[0]: "new",
                fields[1]: "new",
                **dict(spec.create_identity),
            }
            update_plan = _plan(
                [_resource_change(address, "update", before_update, after_update)]
            )
            update_manifest = dict(
                manifest, mutations=[dict(manifest["mutations"][0], action="update")]
            )
            self.assertEqual(
                validate_plan(update_plan, update_manifest)["status"],
                "accepted",
                address,
            )

            redirected_update_before = dict(before_update, bucket="unauthorized-bucket")
            redirected_update_after = dict(after_update, bucket="unauthorized-bucket")
            redirected_update = _plan(
                [
                    _resource_change(
                        address,
                        "update",
                        redirected_update_before,
                        redirected_update_after,
                    )
                ]
            )
            self.assertEqual(
                validate_plan(redirected_update, update_manifest)["reason_code"],
                "invalid_resource_identity",
                address,
            )

        address = 'aws_s3_object.site_assets["LICENSE.txt"]'
        spec = CONTRACT[address]
        after: dict[str, JSON] = {
            "source": "asset",
            "source_hash": "hash",
            **dict(spec.create_identity),
        }
        manifest: Manifest = {
            **manifest_header(),
            "mutations": [
                {
                    "address": address,
                    "action": "create",
                    "operation_class": spec.operation_class,
                    "changed_fields": ["source", "source_hash"],
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
        unknown = _plan(
            [
                _resource_change(
                    address, "create", None, after, after_unknown={"key": True}
                )
            ]
        )
        self.assertEqual(
            validate_plan(unknown, manifest)["reason_code"],
            "unknown_authorization_value",
        )
        sensitive = _plan(
            [
                _resource_change(
                    address, "create", None, after, after_sensitive={"key": True}
                )
            ]
        )
        self.assertEqual(
            validate_plan(sensitive, manifest)["reason_code"],
            "sensitive_authorization_value",
        )
        update_before = {
            "source": "old",
            "source_hash": "old",
            **dict(spec.create_identity),
        }
        update_after = {
            "source": "new",
            "source_hash": "new",
            **dict(spec.create_identity),
        }
        update_manifest = dict(
            manifest, mutations=[dict(manifest["mutations"][0], action="update")]
        )
        unknown_update = _plan(
            [
                _resource_change(
                    address,
                    "update",
                    update_before,
                    update_after,
                    after_unknown={"key": True},
                )
            ]
        )
        self.assertEqual(
            validate_plan(unknown_update, update_manifest)["reason_code"],
            "unknown_authorization_value",
        )
        sensitive_update = _plan(
            [
                _resource_change(
                    address,
                    "update",
                    update_before,
                    update_after,
                    after_sensitive={"bucket": True},
                )
            ]
        )
        self.assertEqual(
            validate_plan(sensitive_update, update_manifest)["reason_code"],
            "sensitive_authorization_value",
        )

    def test_plan_identity_and_type_name_are_bound(self) -> None:
        plan = lambda_plan()
        plan["terraform_version"] = "1.14.0"
        self.assert_reason("provider_identity_mismatch", plan=plan)
        plan = lambda_plan()
        plan["resource_changes"][0]["provider_name"] = (
            "registry.terraform.io/hashicorp/random"
        )
        self.assert_reason("provider_identity_mismatch", plan=plan)
        plan = lambda_plan()
        plan["resource_changes"][0]["name"] = "other"
        self.assert_reason("malformed_input", plan=plan)

    def test_rejects_data_mode_mutation_and_unknown_manifest_declarations(self) -> None:
        plan = lambda_plan()
        plan["resource_changes"][0]["mode"] = "data"
        self.assert_reason("data_mode_misuse", plan=plan)

        manifest = lambda_manifest()
        cast(dict[str, object], manifest)["unexpected"] = "raw exception"
        self.assert_reason("unknown_manifest_declaration", manifest=manifest)

    def test_cli_requires_and_verifies_caller_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, manifest_path, identity_path = (
                root / name for name in ("plan.json", "manifest.json", "identity.json")
            )
            plan_path.write_text(json.dumps(lambda_plan()), encoding="utf-8")
            manifest_path.write_text(json.dumps(lambda_manifest()), encoding="utf-8")
            identity_path.write_text(
                json.dumps(dict(EXPECTED_IDENTITY)), encoding="utf-8"
            )
            evidence_path = root / "evidence.json"
            evidence_path.write_text(
                json.dumps(
                    shared_packages.evidence(
                        "development",
                        "903859731897",
                        "a" * 40,
                        dict.fromkeys(shared_packages.PACKAGES, HASH),
                    )
                )
            )
            review: dict[str, JSON] = {
                "baseline": "c" * 40,
                "development_baseline": "a" * 40,
                "packages": dict.fromkeys(shared_packages.PACKAGES, HASH),
                "schemas": dict.fromkeys(shared_packages.SCHEMAS, HASH),
            }
            document = cast(dict[str, JSON], lambda_plan())
            document["prior_state"] = {
                "values": {
                    "outputs": {
                        "release_state": {
                            "value": {
                                "active": "green",
                                "slots": {"green": {"release_id": "a" * 40}},
                            }
                        }
                    }
                }
            }
            manifest = lambda_manifest()
            manifest["deployment_inputs"].update(
                {"v2/db/" + name: HASH for name in shared_packages.SCHEMAS}
            )
            review_path = root / "compatibility.json"
            command = [
                "python3",
                "infra/delivery_plan_validator.py",
                str(plan_path),
                str(manifest_path),
                "--package-evidence",
                str(evidence_path),
                "--identity",
                str(identity_path),
            ]
            for fault in (
                "valid",
                "stale",
                "unchanged",
                "package",
                "schema",
                "schema_missing",
                "missing_state",
                "malformed_state",
                "digest",
                "malformed",
                "missing",
                "omitted",
            ):
                with self.subTest(fault=fault):
                    candidate_review = copy.deepcopy(review)
                    candidate_plan = copy.deepcopy(document)
                    if fault in {"stale", "unchanged"}:
                        candidate_review["development_baseline"] = "b" * 40
                    if fault == "unchanged":
                        candidate_plan["resource_changes"] = []
                    if fault == "package":
                        cast(dict[str, JSON], candidate_review["packages"])[
                            "loader.zip"
                        ] = "f" * 64
                    if fault == "schema":
                        cast(dict[str, JSON], candidate_review["schemas"])[
                            "schema.sql"
                        ] = "f" * 64
                    if fault == "schema_missing":
                        candidate_review["schemas"] = {}
                    if fault == "missing_state":
                        candidate_plan.pop("prior_state")
                    if fault == "malformed_state":
                        candidate_plan["prior_state"] = {
                            "values": {
                                "outputs": {
                                    "release_state": {
                                        "value": {"active": "private-value"}
                                    }
                                }
                            }
                        }
                    review_bytes = json.dumps(candidate_review).encode()
                    if fault == "malformed":
                        review_bytes = b'{"private-value":'
                    review_path.write_bytes(review_bytes)
                    manifest["deployment_inputs"][
                        "v2/scripts/shared-package-compatibility.json"
                    ] = hashlib.sha256(review_bytes).hexdigest()
                    if fault == "digest":
                        review_path.write_bytes(review_bytes + b" ")
                    if fault == "missing":
                        review_path.unlink()
                    plan_path.write_text(json.dumps(candidate_plan))
                    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
                    result = subprocess.run(
                        command
                        + (
                            []
                            if fault == "omitted"
                            else ["--compatibility-review", str(review_path)]
                        ),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    outcome = json.loads(result.stdout)
                    accepted = fault in {"valid", "unchanged"}
                    self.assertEqual(
                        result.returncode, 0 if accepted else 1, result.stdout
                    )
                    self.assertEqual(
                        outcome["status"], "accepted" if accepted else "rejected"
                    )
                    if not accepted:
                        self.assertEqual(
                            outcome["reason_code"],
                            "malformed_input"
                            if fault == "missing"
                            else "shared_compatibility",
                        )
                    if fault == "stale":
                        self.assertEqual(outcome["reviewed_baseline"], "b" * 40)
                        self.assertEqual(outcome["serving_release"], "a" * 40)
                    self.assertNotIn("private-value", result.stdout + result.stderr)

            plan_path.write_text(json.dumps(_plan([])), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    "infra/delivery_plan_validator.py",
                    str(plan_path),
                    str(manifest_path),
                    "--identity",
                    str(identity_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                json.loads(result.stdout)["reason_code"], "shared_package_evidence"
            )

            for missing in (manifest_path, identity_path):
                missing.unlink()
                rejected = subprocess.run(
                    [
                        "python3",
                        "infra/delivery_plan_validator.py",
                        str(plan_path),
                        str(manifest_path),
                        "--identity",
                        str(identity_path),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(
                    json.loads(rejected.stdout),
                    {"reason_code": "malformed_input", "status": "rejected"},
                )
                self.assertEqual(rejected.stderr, "")
                if missing is manifest_path:
                    manifest_path.write_text(
                        json.dumps(lambda_manifest()), encoding="utf-8"
                    )
                else:
                    identity_path.write_text(
                        json.dumps(dict(EXPECTED_IDENTITY)), encoding="utf-8"
                    )

            for unreadable in (manifest_path, identity_path):
                unreadable.unlink()
                unreadable.mkdir()
                rejected = subprocess.run(
                    [
                        "python3",
                        "infra/delivery_plan_validator.py",
                        str(plan_path),
                        str(manifest_path),
                        "--identity",
                        str(identity_path),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(
                    json.loads(rejected.stdout),
                    {"reason_code": "malformed_input", "status": "rejected"},
                )
                self.assertEqual(rejected.stderr, "")
                unreadable.rmdir()
                if unreadable is manifest_path:
                    manifest_path.write_text(
                        json.dumps(lambda_manifest()), encoding="utf-8"
                    )
                else:
                    identity_path.write_text(
                        json.dumps(dict(EXPECTED_IDENTITY)), encoding="utf-8"
                    )


if __name__ == "__main__":
    unittest.main()

import copy
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
    _timed_schedule_plan_value,
    validate_plan as _validate_plan,
)


LAMBDA_ADDRESS = "aws_lambda_function.loader"
HASH = "0" * 64


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
        "mutations": [{
            "address": LAMBDA_ADDRESS,
            "action": "update",
            "operation_class": "lambda-code",
            "changed_fields": list(changed_fields),
        }],
        "permissions": [{
            "address": LAMBDA_ADDRESS,
            "action": "lambda:UpdateFunctionCode",
            "resource": "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-pricing-loader-dev",
            "conditions": {},
        }],
    }


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
        manifest["mutations"].append({
            "address": address,
            "action": action,
            "operation_class": spec.operation_class,
            "changed_fields": list(fields),
        })
        for permission in spec.permissions:
            manifest["permissions"].append({
                "address": address,
                "action": permission.action,
                "resource": permission.resources[0],
                "conditions": dict(permission.conditions),
            })
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
                "resources": [{
                    "address": resource_address or consumer,
                    "expressions": {
                        expression_path or unknown_path: {
                            "references": [reference or source_reference, producer],
                        },
                    },
                }],
            },
        }
    manifest = _mutation_manifest(((consumer, "update", consumer_fields), (producer, "update", producer_fields)))
    return plan, manifest


class DeliveryPlanValidatorTests(unittest.TestCase):
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
                    "mutations": [{
                        "address": address,
                        "action": "update",
                        "operation_class": spec.operation_class,
                        "changed_fields": list(fields),
                    }],
                    "permissions": [{
                        "address": address,
                        "action": permission.action,
                        "resource": permission.resources[0],
                        "conditions": dict(permission.conditions),
                    } for permission in spec.permissions],
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
        no_op["change"]["before_identity"] = None
        no_op["change"]["after_identity"] = None
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
        self.assert_reason("malformed_input", plan=_plan([no_op], applyable=False))

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
        ] = {"references": [
            "aws_s3_object.agentcore.version_id",
            "aws_s3_object.agentcore",
        ]}
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
            action = spec.actions[0]
            timed = address.startswith('aws_scheduler_schedule.timed_checks["') or address in {
                "aws_lambda_function.timed_checks",
                "aws_s3_object.timed_checks",
            }
            if address.startswith('aws_scheduler_schedule.timed_checks["'):
                fields = ("schedule_expression",)
            elif address in {
                "aws_lambda_function.tollchat_proxy",
                "aws_lambda_function.timed_checks",
            }:
                fields = ("s3_object_version", "source_code_hash")
            elif spec.operation_class == "lambda-code":
                fields = ("filename", "source_code_hash")
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
            plan = _plan([_resource_change(address, action, before, after)])
            manifest = {
                **manifest_header(timed=timed),
                "mutations": [{
                    "address": address,
                    "action": action,
                    "operation_class": spec.operation_class,
                    "changed_fields": list(fields),
                }],
                "permissions": [{
                    "address": address,
                    "action": permission.action,
                    "resource": permission.resources[0],
                    "conditions": dict(permission.conditions),
                } for permission in spec.permissions],
            }
            result = validate_plan(plan, manifest)
            self.assertEqual(result["status"], "accepted", address)

    def test_committed_development_manifest_covers_full_package_graph(self):
        manifest = json.loads(
            (Path(__file__).resolve().parent / "development-release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        expected_mutations = {
            "aws_lambda_function.loader": ("lambda-code", ("filename", "source_code_hash")),
            "aws_lambda_function.publisher": ("lambda-code", ("filename", "source_code_hash")),
            "aws_s3_object.agentcore": ("artifact-upload", ("source", "source_hash")),
            "aws_s3_object.tollchat_proxy": ("artifact-upload", ("source", "source_hash")),
            "aws_lambda_function.tollchat_proxy": ("lambda-code", ("s3_object_version", "source_code_hash")),
            "aws_s3_object.timed_checks": ("artifact-upload", ("source", "source_hash")),
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
        }
        actual_mutations = {
            record["address"]: (record["operation_class"], tuple(record["changed_fields"]))
            for record in manifest["mutations"]
        }
        self.assertEqual(len(manifest["mutations"]), len(expected_mutations))
        self.assertEqual(actual_mutations, expected_mutations)
        expected_permissions = {
            (
                "aws_lambda_function.loader",
                "lambda:UpdateFunctionCode",
                "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-pricing-loader-dev",
                (),
            ),
            (
                "aws_lambda_function.publisher",
                "lambda:UpdateFunctionCode",
                "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-report-publisher-dev",
                (),
            ),
            (
                "aws_s3_object.agentcore",
                "s3:PutObject",
                "arn:aws:s3:::nova-toll-agentcore-903859731897/runtime/v2/*",
                (),
            ),
            (
                "aws_s3_object.tollchat_proxy",
                "s3:PutObject",
                "arn:aws:s3:::nova-toll-agentcore-903859731897/lambda/v2/*",
                (),
            ),
            (
                "aws_lambda_function.tollchat_proxy",
                "lambda:UpdateFunctionCode",
                "arn:aws:lambda:us-east-1:903859731897:function:tollchat-v2-chat-proxy-dev",
                (),
            ),
            (
                "aws_s3_object.timed_checks",
                "s3:PutObject",
                "arn:aws:s3:::nova-toll-agentcore-903859731897/lambda/v2/timed-checks-dev.zip",
                (),
            ),
            (
                "aws_lambda_function.timed_checks",
                "lambda:UpdateFunctionCode",
                "arn:aws:lambda:us-east-1:903859731897:function:nova-toll-v2-timed-checks-dev",
                (),
            ),
            (
                "aws_lambda_alias.tollchat_live",
                "lambda:UpdateAlias",
                "arn:aws:lambda:us-east-1:903859731897:function:tollchat-v2-chat-proxy-dev",
                (),
            ),
            (
                "aws_bedrockagentcore_agent_runtime.tollchat",
                "bedrock-agentcore:UpdateAgentRuntime",
                "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl",
                (),
            ),
            (
                "aws_bedrockagentcore_agent_runtime.tollchat",
                "iam:PassRole",
                "arn:aws:iam::903859731897:role/nova-toll-v2-agentcore-runtime-dev",
                (("iam:PassedToService", "bedrock-agentcore.amazonaws.com"),),
            ),
            (
                "aws_bedrockagentcore_agent_runtime_endpoint.tollchat",
                "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
                "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl/runtime-endpoint/preview",
                (),
            ),
        }
        actual_permissions = {
            (
                record["address"],
                record["action"],
                record["resource"],
                tuple(sorted(record["conditions"].items())),
            )
            for record in manifest["permissions"]
        }
        self.assertEqual(len(manifest["permissions"]), len(expected_permissions))
        self.assertEqual(actual_permissions, expected_permissions)

        def update(address):
            fields = expected_mutations[address][1]
            spec = CONTRACT[address]
            before, after = {}, {}
            for field in fields:
                _set_path(before, field, f"{address}:old")
                _set_path(after, field, f"{address}:new")
            for field, value in spec.create_identity:
                before[field] = after[field] = value
            return _resource_change(address, "update", before, after)

        plan = _plan([update(address) for address in expected_mutations])
        accepted = validate_plan(plan, manifest)
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["reason_code"], "ok")
        self.assertEqual(accepted["addresses"], list(expected_mutations))

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

    def test_timed_schedule_updates_require_fixed_enabled_target(self):
        address = 'aws_scheduler_schedule.timed_checks["greenway-eb-mon-0723"]'
        spec = CONTRACT[address]
        after = _timed_schedule_plan_value(address)
        before = copy.deepcopy(after)
        before["schedule_expression"] = "cron(0 0 ? * SUN *)"
        manifest = {
            **manifest_header(timed=True),
            "mutations": [{
                "address": address,
                "action": "update",
                "operation_class": spec.operation_class,
                "changed_fields": ["schedule_expression"],
            }],
            "permissions": [{
                "address": address,
                "action": permission.action,
                "resource": permission.resources[0],
                "conditions": dict(permission.conditions),
            } for permission in spec.permissions],
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
        orphan_permission["permissions"].append({
            "address": 'aws_scheduler_schedule.timed_checks["greenway-eb-fri-0723"]',
            "action": "scheduler:UpdateSchedule",
            "resource": "arn:aws:scheduler:us-east-1:903859731897:schedule/default/nova-toll-v2-greenway-eb-fri-0723-dev",
            "conditions": {},
        })
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
        manifest["permissions"][0].update({
            "address": address,
            "resource": "arn:aws:lambda:us-east-1:903859731897:function:tollchat-v2-chat-proxy-dev",
        })
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
        manifest["permissions"].append({
            "address": alias_declaration["address"],
            "action": "lambda:UpdateAlias",
            "resource": "arn:aws:lambda:us-east-1:903859731897:function:toll-v2-pricing-loader-dev",
            "conditions": {},
        })
        self.assertEqual(validate_plan(lambda_plan(), manifest)["status"], "accepted")

        manifest["mutations"][1]["address"] = "aws_lambda_alias.not_declared"
        self.assert_reason("manifest_coverage_mismatch", manifest=manifest)

        manifest = lambda_manifest()
        manifest["mutations"] = []
        manifest["permissions"] = []
        self.assert_reason("manifest_coverage_mismatch", manifest=manifest)

    def test_accepts_normal_create_shape_without_authorizing_computed_fields(self):
        cases = (
            ("aws_s3_object.index", {"source": "site/index.html", "source_hash": "hash", "bucket": "tollchat-site-903859731897-dev", "key": "index.html", "etag": "etag", "id": "index.html"}, ("source", "source_hash")),
            ("aws_cloudwatch_event_target.loader", {"target": {"arn": "arn"}, "rule": "rule", "id": "id"}, ("target",)),
            ("aws_bedrock_guardrail_version.tollchat", {"description": "description", "guardrail_arn": "arn", "version": "1", "id": "id"}, ("description", "guardrail_arn")),
            ("aws_api_gateway_deployment.tollchat", {"triggers": {"redeployment": "hash"}, "rest_api_id": "api", "id": "id"}, ("triggers.redeployment",)),
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
            if not spec.create_identity or "create" not in spec.actions:
                continue
            fields = spec.fields[:2]
            after = {fields[0]: "source", fields[1]: "hash", **dict(spec.create_identity)}
            plan = _plan([_resource_change(address, "create", None, after)])
            manifest = {
                **manifest_header(timed=address in {"aws_s3_object.timed_checks", "aws_lambda_function.timed_checks"}),
                "mutations": [{"address": address, "action": "create", "operation_class": spec.operation_class, "changed_fields": list(fields)}],
                "permissions": [{"address": address, "action": p.action, "resource": p.resources[0], "conditions": dict(p.conditions)} for p in spec.permissions],
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

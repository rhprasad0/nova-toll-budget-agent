import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from infra.delivery_plan_validator import CONTRACT, EXPECTED_IDENTITY, EXPECTED_PROVIDER_NAME, validate_plan as _validate_plan


LAMBDA_ADDRESS = "aws_lambda_function.loader"
HASH = "0" * 64


def validate_plan(plan, manifest, identity=None):
    return _validate_plan(plan, manifest, dict(EXPECTED_IDENTITY) if identity is None else identity)


def manifest_header():
    return {
        "schema_version": 1,
        "provider_identity": dict(EXPECTED_IDENTITY),
        "deployment_inputs": {"v2/infra/main.tf": HASH},
        "packages": {name: HASH for name in ("agentcore.zip", "chat-proxy.zip", "loader.zip", "publisher.zip")},
    }


def _resource_change(address, action, before, after, *, after_unknown=None, before_sensitive=None, after_sensitive=None):
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
        },
    }
    if index_text:
        record["index"] = json.loads("[" + index_text[:-1] + "]")[0]
    return record


def lambda_plan(**changes):
    before = {"filename": "old.zip", "source_code_hash": "old", "s3_bucket": None, "s3_key": None, "s3_object_version": None}
    after = {"filename": "new.zip", "source_code_hash": "new", "s3_bucket": None, "s3_key": None, "s3_object_version": None}
    after.update(changes)
    return {"terraform_version": "1.15.8", "resource_changes": [_resource_change(LAMBDA_ADDRESS, "update", before, after)]}


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

    def test_accepts_one_fixture_for_every_contract_entry(self):
        for address, spec in CONTRACT.items():
            action = spec.actions[0]
            if address == "aws_lambda_function.tollchat_proxy":
                fields = ("s3_object_version", "source_code_hash")
            elif spec.operation_class == "lambda-code":
                fields = ("filename", "source_code_hash")
            else:
                fields = (spec.fields[0],)
            before = None if action == "create" else {}
            after = {}
            if before is not None:
                for field in fields:
                    _set_path(before, field, "old")
            for field in fields:
                _set_path(after, field, "new")
            for field, value in spec.create_identity:
                if before is not None:
                    before[field] = value
                after[field] = value
            plan = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, action, before, after)]}
            manifest = {
                **manifest_header(),
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

    def test_rejects_lambda_configuration_disguised_as_code(self):
        plan = lambda_plan(runtime="python3.13")
        self.assert_reason("unsupported_field_delta", plan=plan)

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
            "filename": None,
            "s3_bucket": "nova-toll-agentcore-903859731897",
            "s3_key": "lambda/v2/chat-proxy-dev.zip",
            "s3_object_version": "old",
            "source_code_hash": "old",
        }
        after = dict(before, s3_object_version="new", source_code_hash="new")
        plan = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "update", before, after)]}
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
        plan = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "update", {"tags": {"old": "1"}}, {"tags": {"new": "1"}})]}
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
            plan = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "create", None, after, after_unknown={"id": True})]}
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
            plan = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "create", None, after)]}
            manifest = {
                **manifest_header(),
                "mutations": [{"address": address, "action": "create", "operation_class": spec.operation_class, "changed_fields": list(fields)}],
                "permissions": [{"address": address, "action": p.action, "resource": p.resources[0], "conditions": dict(p.conditions)} for p in spec.permissions],
            }
            self.assertEqual(validate_plan(plan, manifest)["status"], "accepted", address)

            redirected = dict(after, key="runtime/v2/unauthorized.py")
            redirected_plan = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "create", None, redirected)]}
            self.assertEqual(validate_plan(redirected_plan, manifest)["reason_code"], "invalid_resource_identity", address)

            before_update = {fields[0]: "old", fields[1]: "old", **dict(spec.create_identity)}
            after_update = {fields[0]: "new", fields[1]: "new", **dict(spec.create_identity)}
            update_plan = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "update", before_update, after_update)]}
            update_manifest = dict(manifest, mutations=[dict(manifest["mutations"][0], action="update")])
            self.assertEqual(validate_plan(update_plan, update_manifest)["status"], "accepted", address)

            redirected_update_before = dict(before_update, bucket="unauthorized-bucket")
            redirected_update_after = dict(after_update, bucket="unauthorized-bucket")
            redirected_update = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "update", redirected_update_before, redirected_update_after)]}
            self.assertEqual(validate_plan(redirected_update, update_manifest)["reason_code"], "invalid_resource_identity", address)

        address = 'aws_s3_object.site_assets["LICENSE.txt"]'
        spec = CONTRACT[address]
        after = {"source": "asset", "source_hash": "hash", **dict(spec.create_identity)}
        manifest = {
            **manifest_header(),
            "mutations": [{"address": address, "action": "create", "operation_class": spec.operation_class, "changed_fields": ["source", "source_hash"]}],
            "permissions": [{"address": address, "action": p.action, "resource": p.resources[0], "conditions": dict(p.conditions)} for p in spec.permissions],
        }
        unknown = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "create", None, after, after_unknown={"key": True})]}
        self.assertEqual(validate_plan(unknown, manifest)["reason_code"], "unknown_authorization_value")
        sensitive = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "create", None, after, after_sensitive={"key": True})]}
        self.assertEqual(validate_plan(sensitive, manifest)["reason_code"], "sensitive_authorization_value")
        update_before = {"source": "old", "source_hash": "old", **dict(spec.create_identity)}
        update_after = {"source": "new", "source_hash": "new", **dict(spec.create_identity)}
        update_manifest = dict(manifest, mutations=[dict(manifest["mutations"][0], action="update")])
        unknown_update = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "update", update_before, update_after, after_unknown={"key": True})]}
        self.assertEqual(validate_plan(unknown_update, update_manifest)["reason_code"], "unknown_authorization_value")
        sensitive_update = {"terraform_version": "1.15.8", "resource_changes": [_resource_change(address, "update", update_before, update_after, after_sensitive={"bucket": True})]}
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

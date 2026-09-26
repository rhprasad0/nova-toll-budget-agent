"""Real policy composition for package evidence, partial preparation and retries."""

import base64
import importlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts import blue_green, release_blue_green, shared_packages
from scripts.validate_production_plan import validate as production_validate
from tests.test_blue_green import change, plan, previous, shared_fixture, slot

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
delivery_plan_validator = importlib.import_module("infra.delivery_plan_validator")


def package_plan(
    environment: str, phase: str = "prepare", partial: str = "none"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    expected = shared_packages.evidence(
        environment,
        shared_packages.ACCOUNTS[environment],
        "a" * 40,
        dict.fromkeys(shared_packages.PACKAGES, "0" * 64),
    )
    retained = previous(environment)
    candidate = slot("green", "a" * 40)
    if environment == "production":
        candidate = json.loads(
            json.dumps(candidate).replace("903859731897", "920534282028")
        )
    if phase != "prepare":
        retained["slots"]["green"] = candidate
        if phase == "recover":
            retained["active"] = "green"
    inputs = (
        blue_green.desired(retained, candidate)
        if phase == "prepare"
        else blue_green.desired(retained, promote=True)
    )
    suffix = "-dev" if environment == "development" else ""
    bucket = f"nova-toll-agentcore-{expected['account']}"
    key = f"lambda/v2/timed-checks{suffix}.zip"
    rows: list[dict[str, Any]] = []
    for component, identity in shared_packages.identities(expected).items():
        package = shared_packages.FUNCTIONS[component][1]
        values: dict[str, Any] = {
            "function_name": identity["name"],
            "arn": identity["arn"],
            "filename": "build/" + package,
            "source_code_hash": identity["sha256"],
            "role": f"arn:aws:iam::{expected['account']}:role/{identity['name']}",
            "runtime": "python3.13",
            "handler": "handler.handler",
            "s3_bucket": None,
            "s3_key": None,
            "s3_object_version": None,
        }
        if component == "timed_checks":
            values.update(
                filename=None,
                s3_bucket=bucket,
                s3_key=key,
                s3_object_version="version-2" if partial != "none" else None,
            )
        if component == "costs":
            values.update(
                handler="costs.handler",
                architectures=["x86_64"],
                timeout=300,
                memory_size=256,
                reserved_concurrent_executions=1,
                package_type="Zip",
                publish=False,
                environment=[
                    {
                        "variables": {
                            "DEPLOYMENT_ENVIRONMENT": environment,
                            "COST_BUCKET": f"tollchat-site-{expected['account']}{suffix}",
                        }
                    }
                ],
            )
        before = dict(
            values, source_code_hash=base64.b64encode(bytes([1]) * 32).decode()
        )
        if component == "timed_checks":
            before["s3_object_version"] = "version-1"
        done = (
            phase != "prepare"
            or partial == "complete"
            or (partial == "lambda" and component == "publisher")
        )
        if done:
            before = deepcopy(values)
        unknown = (
            {"s3_object_version": True}
            if component == "timed_checks" and not done and partial == "none"
            else {}
        )
        rows.append(
            change(
                "aws_lambda_function." + component,
                before,
                values,
                ["no-op"] if done else ["update"],
                unknown,
            )
        )
    values = {
        "bucket": bucket,
        "key": key,
        "source": "build/timed-checks.zip",
        "source_hash": base64.b64encode(bytes(32)).decode(),
        "version_id": "version-2" if partial != "none" or phase != "prepare" else None,
    }
    done = partial != "none" or phase != "prepare"
    before = (
        deepcopy(values)
        if done
        else dict(values, source_hash="old", version_id="version-1")
    )
    rows.append(
        change(
            shared_packages.OBJECT,
            before,
            values,
            ["no-op"] if done else ["update"],
            {} if done else {"version_id": True},
        )
    )
    document = plan(inputs, rows, retained)
    document.update(
        terraform_version="1.15.8",
        applyable=True,
        configuration={
            "root_module": {
                "resources": [
                    {
                        "address": "aws_lambda_function.timed_checks",
                        "expressions": {
                            "s3_object_version": {
                                "references": [
                                    shared_packages.OBJECT,
                                    shared_packages.OBJECT + ".version_id",
                                ]
                            }
                        },
                    }
                ]
            }
        },
    )
    document["variables"]["environment"] = {"value": environment}
    for row in rows:
        row["type"], row["name"] = row["address"].split(".")
        row["change"].update(before_sensitive={}, after_sensitive={})
    return document, retained, expected


def development_validate(
    document: dict[str, Any], expected: dict[str, Any] | None
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "provider_identity": dict(delivery_plan_validator.EXPECTED_IDENTITY),
        "deployment_inputs": {"v2/scripts/build_timed_checks_zip.sh": "0" * 64},
        "packages": dict.fromkeys(delivery_plan_validator.TIMED_PACKAGES, "0" * 64),
        "mutations": [],
        "permissions": [],
    }
    for row in document["resource_changes"]:
        if row["change"]["actions"] == ["no-op"]:
            continue
        address = row["address"]
        spec = delivery_plan_validator.CONTRACT.get(address)
        if spec is None:
            continue
        fields = sorted(
            field
            for field in spec.fields
            if row["change"]["before"].get(field) != row["change"]["after"].get(field)
            or row["change"]["after_unknown"].get(field)
        )
        manifest["mutations"].append(
            {
                "address": address,
                "action": "update",
                "operation_class": spec.operation_class,
                "changed_fields": fields,
            }
        )
        manifest["permissions"].extend(
            {
                "address": address,
                "action": permission.action,
                "resource": permission.resources[0],
                "conditions": dict(permission.conditions),
            }
            for permission in spec.permissions
        )
    return delivery_plan_validator.validate_plan(
        document, manifest, manifest["provider_identity"], expected
    )


@pytest.mark.parametrize("environment", shared_packages.ACCOUNTS)
@pytest.mark.parametrize("partial", ["none", "s3", "lambda", "complete"])
def test_shared_preparation_composes_with_real_policies(
    environment: str, partial: str
) -> None:
    document, retained, expected = package_plan(environment, partial=partial)
    blue_green.validate_plan(document, retained, "prepare", package_evidence=expected)
    if environment == "development":
        result = development_validate(document, expected)
        assert result["status"] == "accepted", result
    else:
        production_validate(
            dict(document, output_changes={}), ROOT / "v2/infra", expected
        )
    for phase in ("promote", "recover"):
        complete, retained, expected = package_plan(environment, phase, "complete")
        blue_green.validate_plan(complete, retained, phase, package_evidence=expected)


@pytest.mark.parametrize("environment", shared_packages.ACCOUNTS)
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "account",
        "hash",
        "path",
        "identity_before",
        "identity_after",
        "configuration",
        "unknown_hash",
        "reference",
        "producer_hash",
        "producer_identity",
        "producer_version",
        "noop_hash",
        "iam",
        "unrelated",
    ],
)
def test_package_faults_fail_closed(environment: str, fault: str) -> None:
    document, retained, expected = package_plan(environment, partial="s3")
    evidence = deepcopy(expected)
    row = document["resource_changes"][0]
    producer = document["resource_changes"][-1]
    if fault == "missing":
        evidence = None
    elif fault == "account":
        evidence["account"] = "000000000000"
    elif fault == "hash":
        row["change"]["after"]["source_code_hash"] = "B" * 43 + "="
    elif fault == "path":
        row["change"]["after"]["filename"] = "/unverified/loader.zip"
    elif fault.startswith("identity_"):
        row["change"][fault.removeprefix("identity_")]["arn"] += ":other"
    elif fault == "configuration":
        row["change"]["after"]["memory_size"] = 1024
    elif fault == "unknown_hash":
        row["change"]["after_unknown"]["source_code_hash"] = True
    elif fault == "reference":
        document["configuration"]["root_module"]["resources"][0]["expressions"][
            "s3_object_version"
        ] = {"constant_value": "version-2"}
    elif fault in {"producer_hash", "producer_identity", "producer_version"}:
        field = {
            "producer_hash": "source_hash",
            "producer_identity": "bucket",
            "producer_version": "version_id",
        }[fault]
        for side in ("before", "after"):
            producer["change"][side][field] = "unverified"
    elif fault == "noop_hash":
        row["change"]["actions"] = ["no-op"]
        row["change"]["after"] = deepcopy(row["change"]["before"])
    else:
        document["resource_changes"].append(
            change(
                "aws_iam_role.loader" if fault == "iam" else "private-secret-address",
                {"policy": "old"},
                {"policy": "new"},
            )
        )
    with pytest.raises((ValueError, KeyError)):
        blue_green.validate_plan(
            document, retained, "prepare", package_evidence=evidence
        )
    if environment == "development":
        assert development_validate(document, evidence)["status"] == "rejected"


def test_readbacks_include_earlier_success_and_do_not_invoke_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, expected = package_plan("development")
    identities = shared_packages.identities(expected)
    sleeps: list[int] = []

    def aws(*args: str) -> dict[str, str]:
        assert args[:3] == ("lambda", "get-function-configuration", "--function-name")
        item = next(value for value in identities.values() if value["arn"] == args[3])
        if item == identities["loader"]:
            raise release_blue_green.checks.CheckFailure("read_denied")
        return {
            "FunctionName": item["name"],
            "FunctionArn": item["arn"],
            "CodeSha256": item["sha256"]
            if item != identities["timed_checks"]
            else "wrong",
            "State": "Active",
            "LastUpdateStatus": "Successful",
        }

    monkeypatch.setattr(release_blue_green, "aws", aws)
    monkeypatch.setattr(release_blue_green.time, "sleep", sleeps.append)
    assert release_blue_green.shared_readiness(expected, wait=False) == {
        "loader": "unknown",
        "publisher": "verified",
        "timed_checks": "failed",
        "costs": "verified",
    }
    assert sleeps == []


def test_transient_shared_readback_error_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, expected = package_plan("development")
    identities = shared_packages.identities(expected)
    calls = 0
    sleeps: list[int] = []

    def aws(*args: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise release_blue_green.checks.CheckFailure("transient")
        item = next(value for value in identities.values() if value["arn"] == args[3])
        return {
            "FunctionName": item["name"],
            "FunctionArn": item["arn"],
            "CodeSha256": item["sha256"],
            "State": "Active",
            "LastUpdateStatus": "Successful",
        }

    monkeypatch.setattr(release_blue_green, "aws", aws)
    monkeypatch.setattr(release_blue_green.time, "sleep", sleeps.append)
    assert set(release_blue_green.shared_readiness(expected).values()) == {"verified"}
    assert sleeps == [10]


def test_sanitized_inventory_never_prints_unrecognized_values() -> None:
    document, _, _ = package_plan("development")
    document["resource_changes"].append(
        change("SECRET", {"SECRET": "before"}, {"SECRET": "after"})
    )
    inventory = shared_packages.inventory(document, "prepare")
    assert inventory["other_resources"] == 1
    assert "SECRET" not in json.dumps(inventory)


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "symlink", "directory_symlink", "release"]
)
def test_staged_package_bytes_and_paths_fail_closed(tmp_path: Path, fault: str) -> None:
    expected = shared_fixture(tmp_path)
    root = tmp_path / "v2/infra"
    path = root / "build/loader.zip"
    if fault == "missing":
        path.unlink()
    elif fault == "hash":
        path.write_bytes(b"changed")
    elif fault == "symlink":
        path.rename(tmp_path / "loader.zip")
        path.symlink_to(tmp_path / "loader.zip")
    elif fault == "directory_symlink":
        (root / "build").rename(tmp_path / "outside")
        (root / "build").symlink_to(tmp_path / "outside")
    else:
        with pytest.raises(ValueError, match="shared_package_evidence"):
            shared_packages.from_bundle(
                tmp_path, "development", expected["account"], "b" * 40
            )
        return
    with pytest.raises(ValueError, match=r"shared_package_(hash|path)"):
        shared_packages.verify_bytes(root, expected)


@pytest.mark.parametrize("environment", shared_packages.ACCOUNTS)
def test_blue_green_cli_requires_evidence(tmp_path: Path, environment: str) -> None:
    document, retained, expected = package_plan(environment, partial="s3")
    for name, value in (
        ("plan", document),
        ("previous", retained),
        ("evidence", expected),
    ):
        (tmp_path / name).write_text(json.dumps(value))
    command = [
        sys.executable,
        str(ROOT / "v2/scripts/blue_green.py"),
        "prepare",
        "--environment",
        environment,
        "--plan",
        str(tmp_path / "plan"),
        "--previous",
        str(tmp_path / "previous"),
    ]
    assert subprocess.run(command, capture_output=True).returncode == 1
    assert (
        subprocess.run(
            [*command, "--package-evidence", str(tmp_path / "evidence")],
            capture_output=True,
        ).returncode
        == 0
    )
    wrong_environment = [
        "production"
        if value == "development"
        else "development"
        if value == "production"
        else value
        for value in command
    ]
    assert (
        subprocess.run(
            [*wrong_environment, "--package-evidence", str(tmp_path / "evidence")],
            capture_output=True,
        ).returncode
        == 1
    )


@pytest.mark.parametrize("environment", shared_packages.ACCOUNTS)
@pytest.mark.parametrize("completed", [False, True])
def test_exact_chat_transition_in_every_policy(
    environment: str, completed: bool
) -> None:
    document, retained, expected = package_plan(environment, partial="complete")
    code = (ROOT / "v2/agent/public-api-gate.js").read_text()
    name = "tollchat-v2-public-chat-routes" + (
        "-dev" if environment == "development" else ""
    )
    after = {
        "name": name,
        "arn": f"arn:aws:cloudfront::{expected['account']}:function/{name}",
        "runtime": "cloudfront-js-2.0",
        "publish": True,
        "code": code,
    }
    before = dict(
        after, code=code if completed else code[code.index("function handler") :]
    )
    row = change(
        shared_packages.CHAT_ROUTES,
        before,
        after,
        ["no-op"] if completed else ["update"],
    )
    row.update(type="aws_cloudfront_function", name="public_chat_routes")
    row["change"].update(before_sensitive={}, after_sensitive={})
    document["resource_changes"].append(row)
    blue_green.validate_plan(document, retained, "prepare", package_evidence=expected)
    if environment == "development":
        result = development_validate(document, expected)
        assert result["status"] == "accepted", result
    else:
        production_validate(
            dict(document, output_changes={}), ROOT / "v2/infra", expected
        )
    before["code"] = str(before["code"]) + "\n"
    with pytest.raises(ValueError):
        blue_green.validate_plan(
            document, retained, "prepare", package_evidence=expected
        )
    if environment == "development":
        assert development_validate(document, expected)["status"] == "rejected"
    else:
        with pytest.raises(ValueError):
            production_validate(
                dict(document, output_changes={}), ROOT / "v2/infra", expected
            )


@pytest.mark.parametrize("empty", [False, True])
def test_production_cli_requires_matching_evidence(tmp_path: Path, empty: bool) -> None:
    document, _, expected = package_plan("production", partial="s3")
    document["output_changes"] = {}
    if empty:
        document["resource_changes"] = []
    (tmp_path / "plan").write_text(json.dumps(document))
    (tmp_path / "evidence").write_text(json.dumps(expected))
    command = [
        sys.executable,
        str(ROOT / "v2/scripts/validate_production_plan.py"),
        "--plan",
        str(tmp_path / "plan"),
        "--inventory-root",
        str(ROOT / "v2/infra"),
    ]
    assert subprocess.run(command, capture_output=True).returncode == 1

    command += ["--package-evidence", str(tmp_path / "evidence")]
    assert subprocess.run(command, capture_output=True).returncode == 0
    if empty:
        expected["release"] = "invalid"
    else:
        expected["packages"]["loader.zip"]["sha256"] = "1" * 64
    (tmp_path / "evidence").write_text(json.dumps(expected))
    assert subprocess.run(command, capture_output=True).returncode == 1


@pytest.mark.parametrize("environment", shared_packages.ACCOUNTS)
@pytest.mark.parametrize("phase", ["prepare", "promote", "recover"])
def test_completed_chat_publication_drift_is_exact(
    environment: str, phase: str
) -> None:
    document, retained, expected = package_plan(environment, phase, "complete")
    name = "tollchat-v2-public-chat-routes" + (
        "-dev" if environment == "development" else ""
    )
    after = {
        "name": name,
        "arn": f"arn:aws:cloudfront::{expected['account']}:function/{name}",
        "runtime": "cloudfront-js-2.0",
        "publish": True,
        "code": (ROOT / "v2/agent/public-api-gate.js").read_text(),
        "status": "DEPLOYED",
    }
    row = change(shared_packages.CHAT_ROUTES, dict(after, status="IN_PROGRESS"), after)
    row.update(type="aws_cloudfront_function", name="public_chat_routes")
    row["change"].update(before_sensitive={}, after_sensitive={})
    document["resource_drift"] = [row]
    noop = deepcopy(row)
    noop["change"].update(actions=["no-op"], before=deepcopy(after))
    document["resource_changes"].append(noop)
    blue_green.validate_plan(document, retained, phase, package_evidence=expected)
    if environment == "development":
        assert development_validate(document, expected)["status"] == "accepted"
    else:
        production_validate(
            dict(document, output_changes={}), ROOT / "v2/infra", expected
        )

    for side, field, value in [
        ("before", "status", "UNPUBLISHED"),
        ("after", "status", "IN_PROGRESS"),
        ("before", "code", "unreviewed"),
        ("after", "code", "unreviewed"),
        ("before", "arn", "wrong"),
        ("after", "arn", "wrong"),
        ("after", "runtime", "cloudfront-js-1.0"),
        ("after", "publish", False),
        ("after", "etag", "changed"),
        ("after_unknown", "status", True),
    ]:
        invalid = deepcopy(document)
        invalid["resource_drift"][0]["change"][side][field] = value
        with pytest.raises(ValueError):
            blue_green.validate_plan(
                invalid, retained, phase, package_evidence=expected
            )
        if environment == "development":
            assert development_validate(invalid, expected)["status"] == "rejected"
        else:
            with pytest.raises(ValueError):
                production_validate(
                    dict(invalid, output_changes={}), ROOT / "v2/infra", expected
                )


@pytest.mark.parametrize("environment", shared_packages.ACCOUNTS)
@pytest.mark.parametrize("phase", ["prepare", "promote", "recover"])
def test_primary_revision_drift_preserves_exact_configuration(
    environment: str, phase: str
) -> None:
    document, retained, expected = package_plan(environment, phase, "complete")
    distribution = {"development": "E33DVF3KT7BTAC", "production": "E16XVTXNFUS8T4"}[
        environment
    ]
    before: dict[str, Any] = {
        "id": distribution,
        "arn": f"arn:aws:cloudfront::{expected['account']}:distribution/{distribution}",
        "etag": "previous",
        "enabled": True,
        "origin": [],
    }
    row = change(
        "aws_cloudfront_distribution.site", before, dict(before, etag="current")
    )
    row.update(type="aws_cloudfront_distribution", name="site")
    row["change"].update(before_sensitive={}, after_sensitive={})
    document["resource_drift"] = [row]
    blue_green.validate_plan(document, retained, phase, package_evidence=expected)
    if environment == "development":
        assert development_validate(document, expected)["status"] == "accepted"
    else:
        production_validate(
            dict(document, output_changes={}), ROOT / "v2/infra", expected
        )
    for side, field, value in [
        ("before", "id", "other"),
        ("after", "id", "other"),
        ("before", "arn", "wrong"),
        ("after", "arn", "wrong"),
        ("before", "etag", None),
        ("after", "etag", ""),
        ("after", "enabled", False),
        ("after", "origin", [{"domain_name": "other"}]),
        ("after_unknown", "etag", True),
    ]:
        invalid = deepcopy(document)
        invalid["resource_drift"][0]["change"][side][field] = value
        with pytest.raises(ValueError):
            blue_green.validate_plan(
                invalid, retained, phase, package_evidence=expected
            )
        if environment == "development":
            assert development_validate(invalid, expected)["status"] == "rejected"
        else:
            with pytest.raises(ValueError):
                production_validate(
                    dict(invalid, output_changes={}), ROOT / "v2/infra", expected
                )


@pytest.mark.parametrize(
    "environment,legacy,workflow_sha",
    [
        ("production", False, "b" * 40),
        ("production", True, "b" * 40),
        ("development", False, None),
    ],
)
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "bytes",
        "release",
        "account",
        "bundle",
        "missing",
        "partial",
        "conflicting",
        "code",
        "configuration",
        "shared_update",
        "stale",
        "lineage",
    ],
)
def test_manual_recovery_uses_original_package_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment: str,
    legacy: bool,
    workflow_sha: str | None,
    fault: str | None,
) -> None:
    """Exercise admission-to-plan composition; fake only external services."""
    import hashlib
    from unittest.mock import Mock

    release = shared_packages.LEGACY_RECOVERY_RELEASE if legacy else "a" * 40
    bundle = tmp_path / "bundle"
    expected = shared_fixture(bundle, environment)
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["commit_sha"] = release
    manifest_path.write_text(json.dumps(manifest))
    expected["release"] = release
    packages = bundle / "v2/infra/build"
    digests = {}
    for kind, name in (("runtime", "agentcore"), ("proxy", "chat-proxy")):
        raw = name.encode()
        (packages / f"{name}.zip").write_bytes(raw)
        digest = hashlib.sha256(raw)
        digests[f"{kind}_sha256"] = (
            digest.hexdigest()
            if kind == "runtime"
            else base64.b64encode(digest.digest()).decode()
        )
    document, live, _ = package_plan(environment, "recover", partial="complete")
    document = json.loads(json.dumps(document).replace("a" * 40, release))
    live = json.loads(json.dumps(live).replace("a" * 40, release))
    live["slots"]["green"].update(digests)
    document["variables"]["release_slots"]["value"]["green"].update(digests)
    document["output_changes"]["release_state"]["before"] = deepcopy(live)
    prepared = dict(deepcopy(live), active="blue")
    document["output_changes"]["release_state"]["after"] = deepcopy(prepared)
    identities = shared_packages.identities(expected)
    for row in document["resource_changes"]:
        address = row["address"]
        values = row["change"]["after"]
        if address == shared_packages.OBJECT:
            values["source_hash"] = identities["timed_checks"]["sha256"]
        else:
            values["source_code_hash"] = identities[address.rsplit(".", 1)[1]]["sha256"]
        row["change"]["before"] = deepcopy(values)
    code = (ROOT / "v2/agent/public-api-gate.js").read_text()
    if legacy:
        code = code[code.index("function handler") :]
    name = "tollchat-v2-public-chat-routes" + (
        "-dev" if environment == "development" else ""
    )
    chat = {
        "name": name,
        "arn": f"arn:aws:cloudfront::{expected['account']}:function/{name}",
        "runtime": "cloudfront-js-2.0",
        "publish": True,
        "code": code + ("\n" if fault == "code" else ""),
    }
    document["resource_changes"].append(
        change(shared_packages.CHAT_ROUTES, deepcopy(chat), chat, ["no-op"])
    )
    identity: dict[str, Any] = {"lineage": "retained-lineage", "serial": 10}
    context: dict[str, Any] = {
        "claim": "12" if environment == "production" else "12:1",
        "previous": previous(environment),
        "identity": dict(identity),
        "inputs": blue_green.desired(prepared),
        "plan_sha256": "c" * 64,
        "prepared": prepared,
        "environment": environment,
    }
    if environment == "production":
        context.update(
            prepared_identity=dict(identity),
            foundation={"foundation": {}},
            bundle={"id": "42", "digest": "sha256:" + "d" * 64},
        )
    if not legacy:
        context.update(shared_packages=expected, shared_identities=identities)
    if fault == "missing":
        # Removing the fields must not turn a newer record into a legacy record.
        if legacy:
            del context["prepared_identity"]
        else:
            del context["shared_packages"], context["shared_identities"]
    if fault == "partial":
        context["shared_packages"] = expected
        context.pop("shared_identities", None)
    if fault == "conflicting":
        context.update(shared_packages=expected, shared_identities={})
    if fault == "bundle":
        if environment == "production":
            context["bundle"] = {"id": "43", "digest": "sha256:" + "d" * 64}
        else:
            manifest["commit_sha"] = "c" * 40
            manifest_path.write_text(json.dumps(manifest))
    if fault == "bytes":
        (packages / "loader.zip").write_bytes(b"tampered")
    if fault in {"configuration", "shared_update"}:
        row = document["resource_changes"][0]
        row["change"]["actions"] = ["update"]
        field = "role" if fault == "configuration" else "source_code_hash"
        row["change"]["after"][field] = "unrelated"
    if fault == "lineage":
        context["identity"]["lineage"] = "other"
    if workflow_sha is None:
        monkeypatch.delenv("GITHUB_SHA", raising=False)
    else:
        monkeypatch.setenv("GITHUB_SHA", workflow_sha)
    monkeypatch.setenv("CANARY_ARTIFACT_ID", "42")
    monkeypatch.setenv("CANARY_ARTIFACT_DIGEST", "sha256:" + "d" * 64)
    commands: list[str] = []
    observed: list[str] = []

    def aws(*args: str) -> dict[str, Any]:
        if args[:2] == ("sts", "get-caller-identity"):
            account = "000000000000" if fault == "account" else expected["account"]
            role = (
                "nova-toll-production-deploy"
                if environment == "production"
                else "nova-toll-v2-development-delivery"
            )
            return {
                "Account": account,
                "Arn": f"arn:aws:sts::{account}:assumed-role/{role}/test",
            }
        if args[:2] == ("s3api", "get-object"):
            assert (
                args[args.index("--expected-bucket-owner") + 1] == expected["account"]
            )
            assert args[args.index("--version-id") + 1] == "record-v1"
            release_blue_green.write(Path(args[-1]), context)
            return {}
        assert args[:2] == ("lambda", "get-function-configuration")
        row = next(row for row in identities.values() if row["arn"] == args[-1])
        return {
            "FunctionName": row["name"],
            "FunctionArn": row["arn"],
            "CodeSha256": row["sha256"],
            "State": "Active",
            "LastUpdateStatus": "Successful",
        }

    def terraform(_root: Path, *args: str) -> str:
        if args[:2] == ("state", "pull"):
            return json.dumps(
                {**identity, "outputs": {"release_state": {"value": live}}}
            )
        if args[0] == "plan":
            commands.append("plan")
            saved = next(
                arg.removeprefix("-out=") for arg in args if arg.startswith("-out=")
            )
            Path(saved).write_bytes(b"fresh-routing-plan")
            return ""
        if args[:2] == ("show", "-json"):
            return json.dumps(document)
        assert args[0] == "apply"
        commands.append("apply")
        live.update(deepcopy(prepared))
        identity["serial"] += 1
        return ""

    monkeypatch.setattr(release_blue_green, "aws", aws)
    monkeypatch.setattr(release_blue_green, "terraform", terraform)
    for name in ("wait_routing", "readiness", "probe", "private_probe", "assets"):

        def observe(*_args: object, _name: str = name, **_kwargs: object) -> None:
            observed.append(_name)

        monkeypatch.setattr(release_blue_green, name, Mock(side_effect=observe))
    root = tmp_path / "infra"
    root.mkdir()
    output = tmp_path / "result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_blue_green.py",
            "recover",
            "--environment",
            environment,
            "--terraform-root",
            str(root),
            "--bundle-root",
            str(bundle),
            "--foundation-vars",
            str(tmp_path / "foundation.json"),
            "--work-dir",
            str(tmp_path / "work"),
            "--output",
            str(output),
            "--claim",
            context["claim"],
            "--release-id",
            "c" * 40 if fault == "release" else release,
            "--record-version",
            "record-v1",
            "--expected-state-sha256",
            "0" * 64 if fault == "stale" else blue_green.digest(identity),
        ],
    )
    assert release_blue_green.main() == 1
    result = json.loads(output.read_text())
    assert result["deployment"] == "failed"
    if fault is None:
        assert result["recovery"] == "recovered"
        assert commands == ["plan", "apply"]
        assert observed == [
            "wait_routing",
            "readiness",
            "probe",
            "private_probe",
            "assets",
            "assets",
        ]
        assert result["active"] == "blue"
        assert set(result["shared_components"].values()) == {"verified"}
    else:
        assert result["recovery"] != "recovered"
        assert "apply" not in commands
        assert not observed


@pytest.mark.parametrize("environment", shared_packages.ACCOUNTS)
@pytest.mark.parametrize("phase", ["prepare", "promote", "recover"])
@pytest.mark.parametrize("baseline", [False, True])
def test_legacy_chat_noop_is_only_for_baseline_production_recovery(
    environment: str,
    phase: str,
    baseline: bool,
) -> None:
    document, retained, expected = package_plan(environment, phase, partial="complete")
    if baseline:
        release = shared_packages.LEGACY_RECOVERY_RELEASE
        document = json.loads(json.dumps(document).replace("a" * 40, release))
        retained = json.loads(json.dumps(retained).replace("a" * 40, release))
        expected["release"] = release
    name = "tollchat-v2-public-chat-routes" + (
        "-dev" if environment == "development" else ""
    )
    code = (ROOT / "v2/agent/public-api-gate.js").read_text()
    values = {
        "name": name,
        "arn": f"arn:aws:cloudfront::{expected['account']}:function/{name}",
        "runtime": "cloudfront-js-2.0",
        "publish": True,
        "code": code[code.index("function handler") :],
    }
    document["resource_changes"].append(
        change(shared_packages.CHAT_ROUTES, deepcopy(values), values, ["no-op"])
    )
    if environment == "production" and phase == "recover" and baseline:
        blue_green.validate_plan(document, retained, phase, package_evidence=expected)
    else:
        with pytest.raises(ValueError, match="public_chat_code"):
            blue_green.validate_plan(
                document, retained, phase, package_evidence=expected
            )


@pytest.mark.parametrize("workflow_sha", [None, "b" * 40, "a" * 40])
def test_forward_delivery_still_requires_workflow_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    workflow_sha: str | None,
) -> None:
    expected = shared_fixture(tmp_path)
    release_blue_green.configure("development")
    if workflow_sha is None:
        monkeypatch.delenv("GITHUB_SHA", raising=False)
    else:
        monkeypatch.setenv("GITHUB_SHA", workflow_sha)
    if workflow_sha == "a" * 40:
        assert release_blue_green.package_evidence(tmp_path) == expected
    else:
        with pytest.raises(ValueError, match="shared_package_evidence"):
            release_blue_green.package_evidence(tmp_path)

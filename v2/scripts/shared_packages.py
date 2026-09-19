"""Fixed shared-package authority, reused by trusted plan and delivery gates."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, cast

ACCOUNTS = {"development": "903859731897", "production": "920534282028"}
FUNCTIONS = {
    "loader": ("toll-v2-pricing-loader", "loader.zip"),
    "publisher": ("toll-v2-report-publisher", "publisher.zip"),
    "timed_checks": ("nova-toll-v2-timed-checks", "timed-checks.zip"),
    "costs": ("tollchat-v2-cost-publisher", "publisher.zip"),
}
OBJECT = "aws_s3_object.timed_checks"
CHAT_ROUTES = "aws_cloudfront_function.public_chat_routes"
CHAT_CODE = (
    "695db31f3ab2a4f5a3ff38959b02b0bba34fd577737e1a4eae1222cd649a2bf8",
    "1c93d8b91885a207b674a8abc7f9ec6bcd5747b6d6b373082d27fe681fd3e082",
)
RESOURCES = {f"aws_lambda_function.{name}" for name in FUNCTIONS} | {OBJECT}
PACKAGES = {package for _, package in FUNCTIONS.values()}
COMPONENTS = {address: address.rsplit(".", 1)[1] for address in RESOURCES}
COMPONENTS.update(
    {
        "aws_cloudfront_function.public_chat_routes": "chat_routes",
        "aws_cloudfront_function.public_report_routes": "report_routes",
        "aws_cloudfront_distribution.site": "public_routing",
        "aws_cloudfront_distribution.staging": "candidate_routing",
    }
)
FIELDS = {
    "filename",
    "source",
    "source_hash",
    "source_code_hash",
    "s3_object_version",
    "code",
    "origin",
    "uri",
    "environment",
    "role",
    "policy",
    "memory_size",
    "runtime",
    "handler",
    "tags",
    "ordered_cache_behavior",
}
LAMBDA_COMPUTED = {"last_modified", "source_code_size", "code_sha256"}
OBJECT_COMPUTED = {
    "etag",
    "version_id",
    "checksum_crc32",
    "checksum_crc32c",
    "checksum_crc64nvme",
    "checksum_sha1",
    "checksum_sha256",
}


def inventory(plan: dict[str, Any], phase: str) -> dict[str, Any]:
    """No addresses or values from the private plan cross this boundary."""
    rows: list[dict[str, Any]] = []
    other = 0
    for item in plan.get("resource_changes", []):
        change = item.get("change", {})
        if change.get("actions") == ["no-op"]:
            continue
        component = COMPONENTS.get(item.get("address"))
        if component is None:
            other += 1
            continue
        before = cast(dict[str, Any], change.get("before") or {})
        after = cast(dict[str, Any], change.get("after") or {})
        fields = {
            field
            for field in set(before) | set(after)
            if before.get(field) != after.get(field)
        }
        actions = change.get("actions")
        action = (
            cast(list[str], actions)[0]
            if isinstance(actions, list)
            and len(cast(list[Any], actions)) == 1
            and actions[0] in {"create", "update", "delete", "read"}
            else "other"
        )
        rows.append(
            {
                "component": component,
                "action": action,
                "fields": sorted(fields & FIELDS),
                "other_fields": len(fields - FIELDS),
            }
        )
    return {
        "phase": phase
        if phase in {"prepare", "promote", "recover", "premerge"}
        else "other",
        "mutations": rows,
        "other_resources": other,
    }


def report(plan: dict[str, Any], phase: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as output:
            output.write(
                "shared_mutation_inventory="
                + json.dumps(inventory(plan, phase), sort_keys=True)
                + "\n"
            )


def require(value: object, reason: str = "shared_package_boundary") -> None:
    if not value:
        raise ValueError(reason)


def unknown(value: object) -> bool:
    if isinstance(value, dict):
        return any(unknown(child) for child in cast(dict[str, object], value).values())
    if isinstance(value, list):
        return any(unknown(child) for child in cast(list[object], value))
    require(type(value) is bool)
    return bool(value)


def validate_chat(item: dict[str, Any], environment: str) -> None:
    require(environment in ACCOUNTS, "public_chat_identity")
    require(
        item.get("address") == CHAT_ROUTES
        and item.get("mode") == "managed"
        and item.get("provider_name") == "registry.terraform.io/hashicorp/aws",
        "public_chat_identity",
    )
    name = "tollchat-v2-public-chat-routes" + (
        "-dev" if environment == "development" else ""
    )
    change = item["change"]
    require(
        not any(key in item for key in ("previous_address", "deposed"))
        and not change.get("importing")
        and not change.get("replace_paths"),
        "public_chat_identity",
    )
    require(change["actions"] in (["update"], ["no-op"]), "public_chat_code")
    allowed = {"code", "etag", "live_stage_etag", "status"}
    before, after = change["before"], change["after"]
    for side in (before, after):
        require(
            side.get("name") == name
            and side.get("arn")
            == f"arn:aws:cloudfront::{ACCOUNTS[environment]}:function/{name}"
            and side.get("runtime") == "cloudfront-js-2.0"
            and side.get("publish") is True,
            "public_chat_identity",
        )
    hashes = (
        (CHAT_CODE[1], CHAT_CODE[1]) if change["actions"] == ["no-op"] else CHAT_CODE
    )
    require(
        all(
            isinstance(side.get("code"), str)
            and hashlib.sha256(side["code"].encode()).hexdigest() == digest
            for side, digest in zip((before, after), hashes, strict=True)
        ),
        "public_chat_code",
    )
    require(
        all(
            before.get(field) == after.get(field)
            for field in set(before) | set(after)
            if field not in allowed
        ),
        "public_chat_code",
    )
    require(
        all(
            not unknown(value) or field in allowed - {"code"}
            for field, value in change.get("after_unknown", {}).items()
        ),
        "public_chat_code",
    )
    if change["actions"] == ["no-op"]:
        require(
            before == after and not unknown(change.get("after_unknown", {})),
            "public_chat_code",
        )


def evidence(
    environment: str, account: str, release: str, hashes: dict[str, str]
) -> dict[str, Any]:
    require(
        environment in ACCOUNTS and ACCOUNTS[environment] == account,
        "shared_package_evidence",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", release),
        "shared_package_evidence",
    )
    require(set(hashes) >= PACKAGES, "shared_package_evidence")
    require(
        all(re.fullmatch(r"[0-9a-f]{64}", hashes[name]) for name in PACKAGES),
        "shared_package_evidence",
    )
    return {
        "environment": environment,
        "account": account,
        "release": release,
        "packages": {
            name: {"path": f"build/{name}", "sha256": hashes[name]}
            for name in sorted(PACKAGES)
        },
    }


def check_evidence(value: dict[str, Any] | None) -> dict[str, Any]:
    require(isinstance(value, dict), "shared_package_evidence")
    assert value is not None
    require(
        value
        == evidence(
            value["environment"],
            value["account"],
            value["release"],
            {name: row["sha256"] for name, row in value["packages"].items()},
        ),
        "shared_package_evidence",
    )
    return value


def from_bundle(
    bundle: Path, environment: str, account: str, release: str
) -> dict[str, Any]:
    # The caller admits the immutable archive/provenance before using its manifest.
    manifest = json.loads((bundle / "release-manifest.json").read_text())
    require(manifest["commit_sha"] == release, "shared_package_evidence")
    rows = manifest["files"]
    require(len({row["path"] for row in rows}) == len(rows), "shared_package_evidence")
    hashes = {row["path"]: row["sha256"] for row in rows}
    result = evidence(
        environment,
        account,
        release,
        {name: hashes[f"v2/infra/build/{name}"] for name in PACKAGES},
    )
    verify_bytes(bundle / "v2/infra", result)
    return result


def verify_bytes(root: Path, expected: dict[str, Any]) -> None:
    check_evidence(expected)
    require(not (root / "build").is_symlink(), "shared_package_path")
    for row in expected["packages"].values():
        path = root / row["path"]
        require(
            path.is_file()
            and not path.is_symlink()
            and path.resolve().parent == root.resolve() / "build",
            "shared_package_path",
        )
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"],
            "shared_package_hash",
        )


def compatibility(
    bundle: Path,
    expected: dict[str, Any],
    serving_release: str,
    *,
    changing: bool = True,
) -> dict[str, str]:
    """This reviewed transition only; extending it requires a reviewed contract test."""
    reviewed = json.loads(
        Path(__file__).with_name("shared-package-compatibility.json").read_text()
    )
    require(
        not changing or serving_release == reviewed["baseline"], "shared_compatibility"
    )
    require(
        reviewed["packages"]
        == {name: row["sha256"] for name, row in expected["packages"].items()},
        "shared_compatibility",
    )
    for name, digest in reviewed["schemas"].items():
        require(
            hashlib.sha256((bundle / "v2/db" / name).read_bytes()).hexdigest()
            == digest,
            "shared_compatibility",
        )
    return {
        "baseline": serving_release,
        "reviewed_baseline": reviewed["baseline"],
        "status": "reviewed" if changing else "unchanged",
    }


def identities(expected: dict[str, Any]) -> dict[str, dict[str, str]]:
    check_evidence(expected)
    suffix = "-dev" if expected["environment"] == "development" else ""
    return {
        component: {
            "name": name + suffix,
            "arn": f"arn:aws:lambda:us-east-1:{expected['account']}:function:{name}{suffix}",
            "sha256": base64.b64encode(
                bytes.fromhex(expected["packages"][package]["sha256"])
            ).decode(),
        }
        for component, (name, package) in FUNCTIONS.items()
    }


def validate(
    item: dict[str, Any],
    plan: dict[str, Any],
    expected: dict[str, Any] | None,
    *,
    allow_create: bool = False,
) -> None:
    expected = check_evidence(expected)
    address, change = item["address"], item["change"]
    actions = change["actions"]
    require(
        address in RESOURCES
        and item.get("mode") == "managed"
        and item.get("provider_name") == "registry.terraform.io/hashicorp/aws"
    )
    require(
        not any(key in item for key in ("previous_address", "deposed"))
        and not change.get("importing")
        and not change.get("replace_paths")
    )
    require(
        actions in (["update"], ["no-op"])
        or (
            allow_create
            and address == "aws_lambda_function.costs"
            and actions == ["create"]
        )
    )
    before, after = change.get("before"), change["after"]
    require(
        isinstance(after, dict) and (isinstance(before, dict) or actions == ["create"])
    )
    before = cast(dict[str, Any], before or {})
    after = cast(dict[str, Any], after)
    unknowns = change.get("after_unknown", {})
    require(isinstance(unknowns, dict))
    require(not unknown(change.get("after_sensitive", {})))
    suffix = "-dev" if expected["environment"] == "development" else ""
    bucket = f"nova-toll-agentcore-{expected['account']}"
    key = f"lambda/v2/timed-checks{suffix}.zip"
    if address == OBJECT:
        package = expected["packages"]["timed-checks.zip"]
        identity = {"bucket": bucket, "key": key}
        mutable = {"source", "source_hash"}
        computed = OBJECT_COMPUTED
        require(after.get("source") == package["path"], "shared_package_path")
        require(
            after.get("source_hash")
            == base64.b64encode(bytes.fromhex(package["sha256"])).decode(),
            "shared_package_hash",
        )
    else:
        component = address.removeprefix("aws_lambda_function.")
        identity_row = identities(expected)[component]
        identity = {"function_name": identity_row["name"], "arn": identity_row["arn"]}
        mutable = {"filename", "source_code_hash"}
        computed = LAMBDA_COMPUTED
        require(
            after.get("source_code_hash") == identity_row["sha256"],
            "shared_package_hash",
        )
        if component == "timed_checks":
            identity |= {"s3_bucket": bucket, "s3_key": key, "filename": None}
            mutable = {"s3_object_version", "source_code_hash"}
            producers = [
                row for row in plan["resource_changes"] if row["address"] == OBJECT
            ]
            require(len(producers) == 1, "shared_package_reference")
            validate(producers[0], plan, expected)
            resources = (
                plan.get("configuration", {})
                .get("root_module", {})
                .get("resources", [])
            )
            consumers = [row for row in resources if row.get("address") == address]
            require(len(consumers) == 1, "shared_package_reference")
            expression = consumers[0].get("expressions", {}).get("s3_object_version")
            require(
                isinstance(expression, dict)
                and set(cast(dict[str, Any], expression)) == {"references"}
                and sorted(cast(dict[str, Any], expression)["references"])
                == sorted([OBJECT, OBJECT + ".version_id"]),
                "shared_package_reference",
            )
            producer = producers[0]["change"]
            if unknowns.get("s3_object_version") is True:
                require(
                    producer["actions"] == ["update"]
                    and producer.get("after_unknown", {}).get("version_id") is True
                    and after.get("s3_object_version") is None,
                    "shared_package_reference",
                )
                computed = computed | {"s3_object_version"}
            else:
                version = producer["after"].get("version_id")
                require(
                    producer["actions"] == ["no-op"]
                    and isinstance(version, str)
                    and version not in ("", "null")
                    and after.get("s3_object_version") == version,
                    "shared_package_reference",
                )
        else:
            identity |= {"s3_bucket": None, "s3_key": None, "s3_object_version": None}
            package = expected["packages"][FUNCTIONS[component][1]]
            require(after.get("filename") == package["path"], "shared_package_path")
    for field, value in identity.items():
        require(
            (not before or before.get(field) == value)
            and (
                after.get(field) == value
                or (
                    actions == ["create"]
                    and field == "arn"
                    and unknowns.get(field) is True
                )
            )
        )
    if before:
        require(
            all(
                before.get(field) == after.get(field)
                for field in set(before) | set(after)
                if field not in mutable | computed
            )
        )
    # Cost creation has a separate, fixed configuration/IAM validator.
    require(
        all(
            not unknown(value)
            or field in computed
            or (actions == ["create"] and allow_create)
            for field, value in unknowns.items()
        )
    )
    if actions == ["no-op"]:
        require(before == after and not unknown(unknowns))

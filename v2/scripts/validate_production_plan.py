#!/usr/bin/env python3
"""Gate a complete production application plan before private storage."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

try:
    from scripts import cost_dashboard_release as cost_release
    from scripts import shared_packages
except ModuleNotFoundError:
    import cost_dashboard_release as cost_release
    import shared_packages

RESOURCE = re.compile(r'(?m)^(resource|data)\s+"([a-z0-9_]+)"\s+"([a-z0-9_]+)"\s*\{')
ALLOWED_OUTPUTS = {
    "development_acm_certificate_arn",
    "development_acm_validation_records",
    "public_site",
    "private_preview",
}
REPLACEMENTS = {
    "aws_api_gateway_deployment.tollchat",
    "aws_bedrock_guardrail_version.tollchat",
}
PERSISTENT = (
    "aws_dynamodb_table",
    "aws_s3_bucket",
    "aws_s3_object",
    "aws_kms_key",
    "aws_glue_catalog_",
    "aws_sqs_queue",
)
REJECTION_REASONS = frozenset(
    {
        "action",
        "cost_release_boundary",
        "shared_package_boundary",
        "public_chat_code",
        "actions",
        "address",
        "data",
        "drift",
        "inventory",
        "io",
        "managed",
        "moved",
        "output",
        "outputs",
        "persistent",
        "provider",
        "replacement",
        "shape",
        "unknown-shape",
    }
)


class PlanError(ValueError):
    """A plan does not match the fixed production release boundary."""


def _inventory(root: Path) -> tuple[set[str], set[str]]:
    managed: set[str] = set()
    data: set[str] = set()
    for path in root.glob("*.tf"):
        for mode, kind, name in RESOURCE.findall(path.read_text(encoding="utf-8")):
            (managed if mode == "resource" else data).add(
                f"{'' if mode == 'resource' else 'data.'}{kind}.{name}"
            )
    if not managed or not data:
        raise PlanError("inventory")
    return managed, data


def _base(address: object) -> str:
    if not isinstance(address, str):
        raise PlanError("address")
    return address.split("[", 1)[0]


def _unknown(value: object) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, list):
        for item in cast(list[object], value):
            _unknown(item)
        return
    if isinstance(value, dict):
        for item in cast(dict[str, object], value).values():
            _unknown(item)
        return
    raise PlanError("unknown-shape")


def _actions(change: dict[str, Any]) -> tuple[str, ...]:
    actions: object = change.get("actions")
    if not isinstance(actions, list) or any(
        not isinstance(action, str) for action in cast(list[object], actions)
    ):
        raise PlanError("actions")
    return tuple(cast(list[str], actions))


def validate(
    plan: dict[str, Any],
    inventory_root: Path,
    package_evidence: dict[str, Any] | None = None,
) -> dict[str, int]:
    shared_packages.report(plan, "prepare")
    managed, data = _inventory(inventory_root)
    changes = plan.get("resource_changes")
    drift = plan.get("resource_drift", [])
    if not isinstance(changes, list) or not isinstance(drift, list):
        raise PlanError("shape")
    if drift:
        raise PlanError("drift")
    outputs = plan.get("output_changes", {})
    if not isinstance(outputs, dict):
        raise PlanError("outputs")
    for name, output in cast(dict[str, object], outputs).items():
        if (
            name not in ALLOWED_OUTPUTS
            or not isinstance(output, dict)
            or _actions(cast(dict[str, Any], output))
            not in {("create",), ("update",), ("no-op",)}
        ):
            raise PlanError("output")

    counts: dict[str, int] = {
        "create": 0,
        "update": 0,
        "no-op": 0,
        "read": 0,
        "replace": 0,
    }
    for raw_item in cast(list[object], changes):
        item = cast(dict[str, object], raw_item)
        if (
            not isinstance(raw_item, dict)
            or item.get("previous_address") is not None
            or item.get("deposed") is not None
        ):
            raise PlanError("moved")
        mode = item.get("mode")
        base = _base(item.get("address"))
        change = item.get("change")
        provider = item.get("provider_name")
        if not isinstance(change, dict) or not isinstance(provider, str):
            raise PlanError("shape")
        if provider not in {
            "registry.terraform.io/hashicorp/aws",
            "registry.terraform.io/cloudflare/cloudflare",
            "registry.terraform.io/hashicorp/archive",
        }:
            raise PlanError("provider")
        if provider.endswith("/archive") and mode != "data":
            raise PlanError("provider")
        _unknown(cast(dict[str, object], change).get("after_unknown", {}))
        actions = _actions(cast(dict[str, object], change))
        if mode == "data":
            if base not in data or actions not in {("read",), ("no-op",)}:
                raise PlanError("data")
            counts[actions[0]] += 1
            continue
        if mode != "managed" or base not in managed:
            raise PlanError("managed")
        if base == shared_packages.CHAT_ROUTES:
            try:
                shared_packages.validate_chat(item, "production")
            except (ValueError, KeyError, TypeError) as error:
                raise PlanError("public_chat_code") from error
        if base in shared_packages.RESOURCES:
            try:
                shared_packages.check_evidence(package_evidence)
                if (
                    package_evidence is None
                    or package_evidence["environment"] != "production"
                ):
                    raise ValueError("environment")
                shared_packages.validate(
                    item,
                    plan,
                    package_evidence,
                    allow_create=base == "aws_lambda_function.costs",
                )
            except (ValueError, KeyError, TypeError) as error:
                raise PlanError("shared_package_boundary") from error
        if base in {
            address.split("[", 1)[0] for address in cost_release.RESOURCES
        } and actions != ("no-op",):
            try:
                cost_release.validate(item, "production", plan, package_evidence)
            except (ValueError, KeyError, TypeError) as error:
                raise PlanError("cost_release_boundary") from error
        replacement = len(actions) == 2 and set(actions) == {"create", "delete"}
        destructive = "delete" in actions
        if base.startswith(PERSISTENT) and destructive:
            raise PlanError("persistent")
        if replacement:
            if base not in REPLACEMENTS:
                raise PlanError("replacement")
            if base == "aws_api_gateway_deployment.tollchat" and actions != (
                "create",
                "delete",
            ):
                raise PlanError("replacement")
            if base == "aws_bedrock_guardrail_version.tollchat":
                after = cast(dict[str, object], change).get("after")
                if (
                    not isinstance(after, dict)
                    or cast(dict[str, object], after).get("skip_destroy") is not True
                ):
                    raise PlanError("replacement")
            counts["replace"] += 1
        elif actions in {("create",), ("update",), ("no-op",)}:
            counts[actions[0]] += 1
        else:
            raise PlanError("action")
    return counts


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--inventory-root", type=Path, required=True)
    parser.add_argument("--package-evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.plan.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise PlanError("shape")
        expected = (
            json.loads(args.package_evidence.read_text())
            if args.package_evidence
            else None
        )
        counts = validate(cast(dict[str, Any], value), args.inventory_root, expected)
        try:
            expected = shared_packages.check_evidence(expected)
            shared_packages.require(expected["environment"] == "production")
        except (ValueError, KeyError, TypeError) as error:
            raise PlanError("shared_package_boundary") from error
        print(json.dumps(counts, sort_keys=True))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, PlanError) as error:
        reason = "io" if isinstance(error, OSError) else "shape"
        if isinstance(error, PlanError):
            reason = str(error)
        if reason not in REJECTION_REASONS:
            reason = "shape"
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            try:
                with Path(summary).open("a", encoding="utf-8") as handle:
                    handle.write(f"production_plan_rejection={reason}\n")
            except OSError:
                pass
        print("production plan gate: rejected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

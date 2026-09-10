#!/usr/bin/env python3
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
"""Gate a complete production application plan before private storage."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

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


class PlanError(ValueError):
    """A plan does not match the fixed production release boundary."""


def _inventory(root: Path) -> tuple[set[str], set[str]]:
    managed: set[str] = set()
    data: set[str] = set()
    for path in root.glob("*.tf"):
        for mode, kind, name in RESOURCE.findall(path.read_text(encoding="utf-8")):
            (managed if mode == "resource" else data).add(f"{kind}.{name}")
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
        for item in value:
            _unknown(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            _unknown(item)
        return
    raise PlanError("unknown-shape")


def _actions(change: dict[str, Any]) -> tuple[str, ...]:
    actions = change.get("actions")
    if not isinstance(actions, list) or any(
        not isinstance(action, str) for action in actions
    ):
        raise PlanError("actions")
    return tuple(actions)


def validate(plan: dict[str, Any], inventory_root: Path) -> dict[str, int]:
    managed, data = _inventory(inventory_root)
    changes = plan.get("resource_changes")
    if (
        not isinstance(changes, list)
        or not isinstance(plan.get("resource_drift", []), list)
        or plan.get("resource_drift", [])
    ):
        raise PlanError("shape")
    outputs = plan.get("output_changes", {})
    if not isinstance(outputs, dict):
        raise PlanError("outputs")
    for name, output in outputs.items():
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
    for item in changes:
        if (
            not isinstance(item, dict)
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
        _unknown(change.get("after_unknown", {}))
        actions = _actions(change)
        if mode == "data":
            if base not in data or actions not in {("read",), ("no-op",)}:
                raise PlanError("data")
            counts[actions[0]] += 1
            continue
        if mode != "managed" or base not in managed:
            raise PlanError("managed")
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
                after = change.get("after")
                if not isinstance(after, dict) or after.get("skip_destroy") is not True:
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
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.plan.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise PlanError("shape")
        print(
            json.dumps(
                validate(cast(dict[str, Any], value), args.inventory_root),
                sort_keys=True,
            )
        )
    except (OSError, json.JSONDecodeError, PlanError):
        print("production plan gate: rejected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

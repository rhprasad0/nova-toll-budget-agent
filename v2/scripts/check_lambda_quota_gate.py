#!/usr/bin/env python3
"""Fail-closed Lambda concurrency check for one saved Terraform plan."""

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from typing import Any, cast


def number(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"missing {name}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid {name}") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"invalid {name}")
    return result


def allocation(change: dict[str, Any], side: str) -> dict[str, Any]:
    value = change.get(side)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"invalid {side} allocation")
    return cast(dict[str, Any], value)


def capacity(plan: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    functions: dict[str, dict[str, Decimal]] = {}
    provisioned: dict[str, dict[str, list[Decimal]]] = {}
    resources = cast(list[dict[str, Any]], plan.get("resource_changes", []))
    for resource in resources:
        change = cast(dict[str, Any], resource.get("change", {}))
        if change.get("actions") == ["no-op"]:
            continue
        unknown = change.get("after_unknown", {})
        if resource.get("type") == "aws_lambda_function":
            if unknown.get("function_name") or unknown.get(
                "reserved_concurrent_executions"
            ):
                raise ValueError("unknown Lambda function capacity")
            before, after = allocation(change, "before"), allocation(change, "after")
            for label, value in (("before", before), ("after", after)):
                if not value:
                    continue
                name = value.get("function_name")
                if not isinstance(name, str) or not name:
                    raise ValueError(f"missing function name ({label})")
                functions.setdefault(name, {})[label] = number(
                    value.get("reserved_concurrent_executions"),
                    f"reserved concurrency for {name}",
                )
        elif resource.get("type") == "aws_lambda_provisioned_concurrency_config":
            if unknown.get("function_name") or unknown.get(
                "provisioned_concurrent_executions"
            ):
                raise ValueError("unknown provisioned concurrency")
            before, after = allocation(change, "before"), allocation(change, "after")
            for label, value in (("before", before), ("after", after)):
                if not value:
                    continue
                name = value.get("function_name")
                if not isinstance(name, str) or not name:
                    raise ValueError(f"missing provisioned function name ({label})")
                provisioned.setdefault(name, {}).setdefault(label, []).append(
                    number(
                        value.get("provisioned_concurrent_executions"),
                        f"provisioned concurrency for {name}",
                    )
                )
    for name in provisioned:
        if name not in functions:
            raise ValueError(f"unmatched provisioned concurrency for {name}")
    total_before = total_after = additions = Decimal(0)
    for name, values in functions.items():
        before = max(
            values.get("before", Decimal(0)),
            sum(provisioned.get(name, {}).get("before", [])),
        )
        after = max(
            values.get("after", Decimal(0)),
            sum(provisioned.get(name, {}).get("after", [])),
        )
        total_before += before
        total_after += after
        additions += max(Decimal(0), after - before)
    return total_before, total_after, additions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-settings", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--quota", required=True)
    args = parser.parse_args()
    try:
        with open(args.account_settings) as file:
            settings = cast(dict[str, Any], json.load(file))
            limits = cast(dict[str, Any], settings.get("AccountLimit", {}))
        with open(args.plan) as file:
            plan = cast(dict[str, Any], json.load(file))
            _before, _after, addition = capacity(plan)
        limit = number(
            limits.get("ConcurrentExecutions"), "AccountLimit.ConcurrentExecutions"
        )
        unreserved = number(
            limits.get("UnreservedConcurrentExecutions"),
            "AccountLimit.UnreservedConcurrentExecutions",
        )
        quota = number(args.quota, "quota")
        if unreserved > limit:
            raise ValueError("inconsistent account limits")
        live = limit - unreserved
        if live + addition > limit or live + addition > quota:
            raise ValueError("insufficient capacity")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"lambda quota gate: {error}", file=sys.stderr)
        return 1
    print(
        f"lambda_live={live} lambda_additions={addition} lambda_quota={quota} pass=true"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

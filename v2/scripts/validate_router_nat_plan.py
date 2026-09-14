"""Bounded review of a locally generated, private foundation Terraform plan.

Run against `terraform show -json` from the reviewed checkout/provider. This is
a change-scope check, not an execution sandbox or a substitute for human review.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, cast

ACCOUNTS = {"development": "903859731897", "production": "920534282028"}
CIDRS = ("172.31.224.0/24", "172.31.225.0/24")
REMOVED = {"aws_nat_gateway.tollchat", "aws_eip.tollchat_nat"}
ENDPOINTS = tuple(
    f"aws_vpc_endpoint.{name}" for name in ("agentcore", "tollchat_api", "eventbridge")
)


def require(ok: object, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def unknown(value: object) -> bool:
    if isinstance(value, dict):
        return any(unknown(item) for item in cast(dict[str, object], value).values())
    if isinstance(value, list):
        return any(unknown(item) for item in cast(list[object], value))
    return value is True


def validate(plan: dict[str, Any], environment: str) -> dict[str, int]:
    require(environment in ACCOUNTS, "environment")
    require(
        plan.get("complete") is True and plan.get("errored") is False, "incomplete plan"
    )
    require(
        plan["variables"]["environment"]["value"] == environment, "environment mismatch"
    )
    require(
        all(c.get("status") == "pass" for c in plan.get("checks", [])),
        "failed or unknown checks",
    )
    resources = {
        r["address"]: r["values"]
        for r in plan["planned_values"]["root_module"]["resources"]
    }
    data = {
        r["address"]: r["values"]
        for r in plan["prior_state"]["values"]["root_module"]["resources"]
        if r["mode"] == "data"
    }
    require(
        data["data.aws_caller_identity.current"]["account_id"] == ACCOUNTS[environment],
        "account mismatch",
    )
    require(data["data.aws_region.current"]["region"] == "us-east-1", "region mismatch")
    router = resources["aws_instance.tailscale_router"]
    require(
        router["source_dest_check"] is False
        and router["associate_public_ip_address"] is True,
        "router forwarding/public IP",
    )
    require(router["availability_zone"] == "us-east-1c", "router AZ")
    require(
        router["vpc_security_group_ids"]
        == [resources["aws_security_group.tailscale_router"]["id"]],
        "router security group",
    )
    private_c = resources["aws_subnet.tollchat_private_c"]
    require(private_c["availability_zone"] == "us-east-1c", "endpoint AZ")
    require(not REMOVED.intersection(resources), "managed NAT remains")
    for address in ENDPOINTS:
        require(
            resources[address]["subnet_ids"] == [private_c["id"]], "endpoint subnet"
        )
    routes = resources["aws_route_table.tollchat_private"]["route"]
    defaults = [r for r in routes if r.get("cidr_block") == "0.0.0.0/0"]
    require(
        len(defaults) == 1
        and defaults[0]["network_interface_id"]
        == router["primary_network_interface_id"],
        "default ENI",
    )
    ingress = {
        f'aws_vpc_security_group_ingress_rule.router_nat_https["{cidr}"]': cidr
        for cidr in CIDRS
    }
    for address, cidr in ingress.items():
        rule = resources[address]
        require(
            rule["cidr_ipv4"] == cidr
            and rule["ip_protocol"] == "tcp"
            and rule["from_port"] == rule["to_port"] == 443,
            "ingress scope",
        )
        require(
            rule["security_group_id"]
            == resources["aws_security_group.tailscale_router"]["id"],
            "ingress target",
        )
        require(
            not rule.get("cidr_ipv6")
            and not rule.get("referenced_security_group_id")
            and not rule.get("prefix_list_id"),
            "extra ingress source",
        )

    counts = {"create": 0, "update": 0, "delete": 0}
    for resource in plan["resource_changes"]:
        change, address = resource["change"], resource["address"]
        actions = change["actions"]
        if actions == ["no-op"]:
            continue
        require(
            resource.get("provider_name") == "registry.terraform.io/hashicorp/aws",
            "unexpected provider",
        )
        require(
            not resource.get("previous_address") and not resource.get("deposed"),
            "moved/deposed resource",
        )
        require(not change.get("replace_paths"), "replacement")
        if address in REMOVED:
            require(actions == ["delete"], "NAT removal action")
        elif address in ingress:
            require(actions == ["create"], "ingress action")
        else:
            require(actions == ["update"], "unexpected action")
            allowed = {
                "aws_instance.tailscale_router": {"source_dest_check"},
                "aws_route_table.tollchat_private": {"route"},
            }
            allowed.update(
                {
                    endpoint: {"subnet_ids", "network_interface_ids", "dns_entry"}
                    for endpoint in ENDPOINTS
                }
            )
            require(address in allowed, "unrelated resource mutation")
            before, after = change["before"], change["after"]
            changed = {
                key
                for key in before.keys() | after.keys()
                if before.get(key) != after.get(key)
            }
            require(changed <= allowed[address], "unrelated attribute mutation")
            require(
                {k for k, v in change.get("after_unknown", {}).items() if unknown(v)}
                <= allowed[address],
                "unrelated unknown attribute",
            )
            if address == "aws_route_table.tollchat_private":
                old = [r for r in before["route"] if r.get("cidr_block") != "0.0.0.0/0"]
                new = [r for r in after["route"] if r.get("cidr_block") != "0.0.0.0/0"]
                require(old == new, "non-default route mutation")
                original = next(
                    r for r in before["route"] if r.get("cidr_block") == "0.0.0.0/0"
                )
                expected = dict(
                    original,
                    nat_gateway_id="",
                    network_interface_id=router["primary_network_interface_id"],
                )
                require(defaults[0] == expected, "extra default route target")
        counts[actions[0]] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=ACCOUNTS, required=True)
    args = parser.parse_args()
    try:
        plan = json.load(sys.stdin)
        require(isinstance(plan, dict), "plan object")
        result = validate(plan, args.environment)
    except (KeyError, TypeError, ValueError, StopIteration):
        print(
            "router-nat: plan rejected; review private plan for identity, drift or out-of-scope changes",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

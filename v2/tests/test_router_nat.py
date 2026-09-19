from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_router_nat_plan import ACCOUNTS, CIDRS, ENDPOINTS, validate


def fixture(environment: str = "development") -> dict[str, Any]:
    router = {
        "id": "i-router",
        "source_dest_check": False,
        "associate_public_ip_address": True,
        "availability_zone": "us-east-1c",
        "vpc_security_group_ids": ["sg-router"],
        "primary_network_interface_id": "eni-router",
    }
    values: dict[str, Any] = {
        "aws_instance.tailscale_router": router,
        "aws_security_group.tailscale_router": {"id": "sg-router"},
        "aws_subnet.tollchat_private_c": {
            "id": "subnet-c",
            "availability_zone": "us-east-1c",
        },
        "aws_route_table.tollchat_private": {
            "route": [
                {
                    "cidr_block": "0.0.0.0/0",
                    "nat_gateway_id": "",
                    "network_interface_id": "eni-router",
                }
            ]
        },
        **{endpoint: {"subnet_ids": ["subnet-c"]} for endpoint in ENDPOINTS},
    }
    for cidr in CIDRS:
        values[f'aws_vpc_security_group_ingress_rule.router_nat_https["{cidr}"]'] = {
            "cidr_ipv4": cidr,
            "ip_protocol": "tcp",
            "from_port": 443,
            "to_port": 443,
            "security_group_id": "sg-router",
        }
    changes: list[dict[str, Any]] = []
    for address, after in values.items():
        before: dict[str, Any] | None = deepcopy(after)
        assert before is not None
        actions = ["update"]
        if address == "aws_instance.tailscale_router":
            before["source_dest_check"] = True
        elif address in ENDPOINTS:
            before["subnet_ids"] = ["subnet-a", "subnet-c"]
        elif address == "aws_route_table.tollchat_private":
            before["route"][0].update(nat_gateway_id="nat-old", network_interface_id="")
        elif address.startswith("aws_vpc_security_group_ingress_rule."):
            before = None
            actions = ["create"]
        else:
            actions = ["no-op"]
        changes.append(
            {
                "address": address,
                "provider_name": "registry.terraform.io/hashicorp/aws",
                "change": {
                    "actions": actions,
                    "before": before,
                    "after": after,
                    "after_unknown": {},
                },
            }
        )
    for address in ("aws_nat_gateway.tollchat", "aws_eip.tollchat_nat"):
        changes.append(
            {
                "address": address,
                "provider_name": "registry.terraform.io/hashicorp/aws",
                "change": {
                    "actions": ["delete"],
                    "before": {"id": "old"},
                    "after": None,
                },
            }
        )
    return {
        "complete": True,
        "errored": False,
        "variables": {"environment": {"value": environment}},
        "checks": [{"status": "pass"}],
        "planned_values": {
            "root_module": {
                "resources": [{"address": a, "values": v} for a, v in values.items()]
            }
        },
        "prior_state": {
            "values": {
                "root_module": {
                    "resources": [
                        {
                            "mode": "data",
                            "address": "data.aws_caller_identity.current",
                            "values": {"account_id": ACCOUNTS[environment]},
                        },
                        {
                            "mode": "data",
                            "address": "data.aws_region.current",
                            "values": {"region": "us-east-1"},
                        },
                    ]
                }
            }
        },
        "resource_changes": changes,
    }


@pytest.mark.parametrize("environment", ACCOUNTS)
def test_router_plan_and_converged_plan(environment: str) -> None:
    plan = fixture(environment)
    assert validate(plan, environment) == {"create": 2, "update": 5, "delete": 2}
    plan["resource_changes"] = []
    assert validate(plan, environment) == {"create": 0, "update": 0, "delete": 0}


@pytest.mark.parametrize(
    "failure",
    [
        "account",
        "route",
        "ingress",
        "replacement",
        "unrelated",
        "attribute",
        "unknown",
        "check",
        "incomplete",
        "gateway_route",
    ],
)
def test_router_plan_rejects_unsafe_changes(failure: str) -> None:
    plan = fixture()
    router = plan["resource_changes"][0]
    resources = {
        r["address"]: r["values"]
        for r in plan["planned_values"]["root_module"]["resources"]
    }
    if failure == "account":
        plan["prior_state"]["values"]["root_module"]["resources"][0]["values"][
            "account_id"
        ] = ACCOUNTS["production"]
    elif failure == "route":
        resources["aws_route_table.tollchat_private"]["route"][0][
            "network_interface_id"
        ] = "eni-other-account"
    elif failure == "ingress":
        resources[
            f'aws_vpc_security_group_ingress_rule.router_nat_https["{CIDRS[0]}"]'
        ]["to_port"] = 65535
    elif failure == "replacement":
        router["change"]["actions"] = ["delete", "create"]
    elif failure == "unrelated":
        plan["resource_changes"].append(
            {
                "address": "aws_db_instance.main",
                "provider_name": "registry.terraform.io/hashicorp/aws",
                "change": {"actions": ["update"]},
            }
        )
    elif failure == "attribute":
        router["change"]["after"]["instance_type"] = "t4g.large"
    elif failure == "unknown":
        router["change"]["after_unknown"] = {"private_ip": True}
    elif failure == "check":
        plan["checks"][0]["status"] = "unknown"
    elif failure == "incomplete":
        plan["complete"] = False
    elif failure == "gateway_route":
        resources["aws_route_table.tollchat_private"]["route"].append(
            {"destination_prefix_list_id": "pl-unexpected", "gateway_id": "vpce-other"}
        )
    with pytest.raises(ValueError):
        validate(plan, "development")


def test_router_terraform_preserves_application_subnets_and_enrollment() -> None:
    root = Path(__file__).resolve().parents[2]
    network = (root / "infra/agentcore.tf").read_text()
    router = (root / "infra/tailscale.tf").read_text()
    assert (
        network.count("subnet_ids          = [aws_subnet.tollchat_private_c.id]") == 3
    )
    assert 'resource "aws_nat_gateway"' not in network
    assert 'resource "aws_eip"' not in network
    assert (
        "network_interface_id = aws_instance.tailscale_router.primary_network_interface_id"
        in network
    )
    assert "ignore_changes = [user_data]" in router
    assert "${local.router_nat_setup}" in router
    assert (
        "private_subnet_ids                     = { a = aws_subnet.tollchat_private_a.id, c = aws_subnet.tollchat_private_c.id }"
        in (root / "infra/outputs.tf").read_text()
    )

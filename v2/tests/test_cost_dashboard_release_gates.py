"""Stage finite billing permissions before the feature enters a trusted plan."""

import json
from copy import deepcopy
from typing import Any

import pytest

from scripts import cost_dashboard_release as gate


@pytest.mark.parametrize("environment", ["development", "production"])
def test_future_billing_role_has_only_its_fixed_permissions(environment: str) -> None:
    name = "tollchat-v2-cost-publisher" + (
        "-dev" if environment == "development" else ""
    )
    policy = gate.policy(environment)
    item: dict[str, Any] = {
        "address": "aws_iam_role_policy.costs",
        "mode": "managed",
        "provider_name": "registry.terraform.io/hashicorp/aws",
        "change": {
            "actions": ["create"],
            "before": None,
            "after": {"name": name, "role": name, "policy": json.dumps(policy)},
            "after_unknown": {},
            "after_sensitive": {},
        },
    }
    gate.validate(item, environment)
    for mutation in ("extra_permission", "wrong_role", "unknown_policy", "delete"):
        bad = deepcopy(item)
        if mutation == "extra_permission":
            altered = deepcopy(policy)
            altered["Statement"][0]["Action"].append("iam:PassRole")
            bad["change"]["after"]["policy"] = json.dumps(altered)
        elif mutation == "wrong_role":
            bad["change"]["after"]["role"] = "other-role"
        elif mutation == "unknown_policy":
            bad["change"]["after_unknown"] = {"policy": True}
        else:
            bad["change"]["actions"] = ["delete"]
        with pytest.raises(ValueError):
            gate.validate(bad, environment)
    statements = {row["Sid"]: row for row in policy["Statement"]}
    assert ("ReadBillingKey" in statements) == (environment == "production")
    assert statements["PublishSnapshot"]["Resource"].endswith("/costs.json")


def test_future_billing_routes_preserve_all_existing_behaviors() -> None:
    model = {"path_pattern": "/eval-dashboard*", "target_origin_id": "site"}
    before = {"ordered_cache_behavior": [model]}
    after = {
        "ordered_cache_behavior": [
            model,
            *(dict(model, path_pattern=path) for path in sorted(gate.COST_ROUTES)),
        ]
    }
    gate.routes(before, after)
    after["ordered_cache_behavior"][1]["target_origin_id"] = "public-chat"
    with pytest.raises(ValueError):
        gate.routes(before, after)

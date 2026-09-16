#!/usr/bin/env python3
"""Fail-closed boundaries for fixed-slot TollChat releases.

Artifact admission, approval, migrations, and Terraform backend locking remain
owned by the protected workflow. This additional gate limits each release phase.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

SLOTS = ("blue", "green")
DESCRIPTOR_KEYS = {
    "release_id",
    "runtime_id",
    "runtime_key",
    "runtime_object_version",
    "runtime_sha256",
    "proxy_key",
    "proxy_object_version",
    "proxy_sha256",
    "runtime_environment",
    "proxy_environment",
    "asset_prefix",
}
CHECKS = {
    "readiness",
    "grounding",
    "guardrail",
    "redaction",
    "origin",
    "session",
    "identity",
    "assets",
}
SLOT_RESOURCES = {
    "aws_bedrockagentcore_agent_runtime.tollchat": {
        "agent_runtime_artifact",
        "environment_variables",
        "agent_runtime_version",
        "updated_at",
    },
    "aws_bedrockagentcore_agent_runtime_endpoint.tollchat": {
        "agent_runtime_version",
        "updated_at",
    },
    "aws_lambda_function.tollchat_proxy": {
        "s3_key",
        "s3_object_version",
        "source_code_hash",
        "environment",
        "version",
        "qualified_arn",
        "qualified_invoke_arn",
        "last_modified",
        "code_sha256",
        "source_code_size",
        "signing_job_arn",
        "signing_profile_version_arn",
    },
    "aws_lambda_alias.tollchat_live": {"function_version"},
}
ROUTING_RESOURCES = {
    "aws_cloudfront_distribution.site": {
        "origin",
        "etag",
        "last_modified_time",
        "status",
    },
    "aws_cloudfront_distribution.staging": {
        "origin",
        "etag",
        "last_modified_time",
        "status",
    },
    "aws_api_gateway_integration.tollchat_root": {"uri"},
    "aws_api_gateway_integration.tollchat_proxy": {"uri"},
    "aws_api_gateway_deployment.tollchat": {"id", "created_date", "triggers"},
    "aws_api_gateway_stage.tollchat": {"deployment_id"},
}
BOOTSTRAP_MOVES = {
    **{
        name: f'{name}["blue"]'
        for name in (
            *SLOT_RESOURCES,
            "aws_cloudwatch_log_group.tollchat_proxy",
            "aws_lambda_permission.tollchat_api",
            "aws_lambda_function_url.public_chat",
            "aws_lambda_permission.public_chat_url",
            "aws_lambda_permission.public_chat_invoke",
        )
    },
    **{
        f'aws_bedrockagentcore_resource_policy.tollchat["{name}"]': f'aws_bedrockagentcore_resource_policy.tollchat["blue-{name}"]'
        for name in ("runtime", "endpoint")
    },
}
BOOTSTRAP_FORGET = {
    f"aws_s3_object.{name}"
    for name in (
        "agentcore",
        "tollchat_proxy",
        "index",
        "chat",
        "faq",
        "privacy",
        "site_assets",
    )
}


class Rejected(ValueError):
    """Sanitized, fixed reason code; never include plan or response contents."""


def require(value: bool, reason: str) -> None:
    if not value:
        raise Rejected(reason)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def descriptor(value: dict[str, Any]) -> dict[str, Any]:
    require(value.keys() >= DESCRIPTOR_KEYS, "descriptor_fields")
    result = {key: value[key] for key in DESCRIPTOR_KEYS}
    release = result["release_id"]
    require(
        isinstance(release, str)
        and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", release) is not None,
        "release_id",
    )
    require(result["asset_prefix"] == f"/releases/{release}", "asset_prefix")
    require(
        isinstance(result["runtime_id"], str)
        and re.fullmatch(
            r"nova_toll_v2(?:_development)?(?:_green)?-[A-Za-z0-9]+",
            result["runtime_id"],
        )
        is not None,
        "runtime_identity",
    )
    for kind, filename in (("runtime", "agentcore"), ("proxy", "chat-proxy")):
        require(
            result[f"{kind}_key"] == f"releases/{release}/{filename}.zip",
            "artifact_key",
        )
        require(
            isinstance(result[f"{kind}_object_version"], str)
            and result[f"{kind}_object_version"] not in ("", "null"),
            "artifact_version",
        )
    require(
        re.fullmatch(r"[a-f0-9]{64}", result["runtime_sha256"]) is not None,
        "artifact_hash",
    )
    require(
        re.fullmatch(r"[A-Za-z0-9+/]{43}=", result["proxy_sha256"]) is not None,
        "artifact_hash",
    )
    for key in ("runtime_environment", "proxy_environment"):
        require(
            isinstance(result[key], dict)
            and all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in result[key].items()
            ),
            "configuration",
        )
    return result


def state(value: dict[str, Any]) -> None:
    require(
        value.get("active") in SLOTS and set(value.get("slots", {})) == set(SLOTS),
        "two_slots",
    )
    for name in SLOTS:
        descriptor(value["slots"][name])
    blue, green = (value["slots"][name] for name in SLOTS)
    require(
        blue["runtime_id"] != green["runtime_id"]
        and blue["release_id"] != green["release_id"],
        "slot_isolation",
    )


def desired(
    current: dict[str, Any],
    candidate: dict[str, Any] | None = None,
    *,
    promote: bool = False,
) -> dict[str, Any]:
    state(current)
    slots = {name: descriptor(value) for name, value in current["slots"].items()}
    active = current["active"]
    inactive = "green" if active == "blue" else "blue"
    if candidate is not None:
        require(
            not promote and candidate["runtime_id"] == slots[inactive]["runtime_id"],
            "slot_identity",
        )
        require(
            candidate["release_id"] != slots[active]["release_id"]
            and (
                candidate["release_id"] != slots[inactive]["release_id"]
                or descriptor(candidate) == slots[inactive]
            ),
            "release_reused",
        )
        slots[inactive] = descriptor(candidate)
    return {"active_slot": inactive if promote else active, "release_slots": slots}


def verify_serving(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    for key in (
        "release_id",
        "proxy_arn",
        "proxy_version",
        "runtime_arn",
        "runtime_version",
        "endpoint",
    ):
        require(
            actual.get(key) == expected.get(key) and bool(actual.get(key)),
            "serving_identity",
        )
    require(
        actual.get("runtime_release_id") == expected["release_id"], "invoked_release"
    )


def verify_evidence(
    evidence: dict[str, Any],
    prepared: dict[str, Any],
    claim: str,
    now: float | None = None,
) -> None:
    state(prepared)
    require(
        bool(claim)
        and evidence.get("claim") == claim
        and evidence.get("state_sha256") == digest(prepared),
        "stale_evidence",
    )
    timestamp = evidence.get("checked_at")
    require(
        type(timestamp) is int
        and 0 <= (time.time() if now is None else now) - timestamp <= 900,
        "expired_evidence",
    )
    require(
        set(evidence.get("checks", {})) == CHECKS
        and all(v is True for v in evidence["checks"].values()),
        "candidate_checks",
    )
    inactive = "green" if prepared["active"] == "blue" else "blue"
    verify_serving(evidence.get("serving", {}), prepared["slots"][inactive])


def changed(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {
        key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
    }


def has_unknown(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            has_unknown(item) for item in cast(dict[str, object], value).values()
        )
    if isinstance(value, list):
        return any(has_unknown(item) for item in cast(list[object], value))
    if isinstance(value, bool):
        return value
    raise Rejected("unknown_shape")


def origins(
    before: list[dict[str, Any]], after: list[dict[str, Any]], *, api: str, prefix: str
) -> None:
    old, new = ({v["origin_id"]: deepcopy(v) for v in side} for side in (before, after))
    require(set(old) == set(new) == {"site", "documents", "public-chat"}, "origins")
    require(
        new["public-chat"]["domain_name"] == api
        and new["documents"]["origin_path"] == prefix,
        "route_target",
    )
    old["public-chat"]["domain_name"] = new["public-chat"]["domain_name"]
    old["documents"]["origin_path"] = new["documents"]["origin_path"]
    require(old == new, "shared_origin_changed")


def validate_plan(
    plan: dict[str, Any], previous: dict[str, Any], phase: str
) -> dict[str, Any]:
    """Gate the entire saved plan, including no-op moves and shared resources."""
    require(phase in {"prepare", "promote", "recover"}, "phase")
    state(previous)
    require(
        plan.get("errored") is False
        and plan.get("complete") is True
        and not plan.get("resource_drift"),
        "incomplete_or_drift",
    )
    variables = {key: item["value"] for key, item in plan["variables"].items()}
    slots, active = variables["release_slots"], variables["active_slot"]
    before_slots = {key: descriptor(value) for key, value in previous["slots"].items()}
    require(set(slots) == set(SLOTS) and active in SLOTS, "two_slots")
    for slot in slots.values():
        descriptor(slot)
    inactive = "green" if previous["active"] == "blue" else "blue"
    if phase == "prepare":
        require(
            active == previous["active"] and slots[active] == before_slots[active],
            "active_changed",
        )
        require(
            slots[inactive]["runtime_id"] == before_slots[inactive]["runtime_id"],
            "slot_identity",
        )
        require(
            slots[inactive]["release_id"] != before_slots[active]["release_id"]
            and (
                slots[inactive]["release_id"] != before_slots[inactive]["release_id"]
                or slots[inactive] == before_slots[inactive]
            ),
            "release_reused",
        )
    else:
        require(slots == before_slots and active == inactive, "routing_only")
    seen: set[str] = set()
    count = 0
    for item in plan.get("resource_changes", []):
        address = item["address"]
        if "deposed" in item:
            # A failed create-before-destroy API deployment can leave its old
            # deployment in state. Only recovery may finish that exact cleanup.
            require(
                phase == "recover"
                and address == "aws_api_gateway_deployment.tollchat"
                and item.get("provider_name") == "registry.terraform.io/hashicorp/aws"
                and item.get("mode") == "managed"
                and item["change"]["actions"] == ["delete"]
                and "previous_address" not in item
                and "importing" not in item["change"],
                "deposed_resource",
            )
            api_ids = {
                resource["change"]["before"]["rest_api_id"]
                for resource in plan.get("resource_changes", [])
                if resource["address"]
                in {
                    "aws_api_gateway_integration.tollchat_root",
                    "aws_api_gateway_integration.tollchat_proxy",
                }
            }
            require(api_ids == {item["change"]["before"]["rest_api_id"]}, "deposed_api")
            key = address + ":" + item["deposed"]
            require(key not in seen, "moved_or_duplicate")
            seen.add(key)
            count += 1
            continue
        require(
            address not in seen
            and "previous_address" not in item
            and "deposed" not in item
            and "importing" not in item.get("change", {}),
            "moved_or_duplicate",
        )
        seen.add(address)
        change = item["change"]
        actions = change["actions"]
        if item.get("mode") == "data":
            require(actions in (["read"], ["no-op"]), "data_action")
            continue
        require(
            item.get("provider_name") == "registry.terraform.io/hashicorp/aws",
            "provider",
        )
        if actions == ["no-op"]:
            require(change["before"] == change["after"], "false_noop")
            continue
        before: dict[str, Any] = change.get("before") or {}
        after: dict[str, Any] = change.get("after") or {}
        allow: set[str] = set()
        if phase == "prepare":
            allow = next(
                (
                    fields
                    for name, fields in SLOT_RESOURCES.items()
                    if address == f'{name}["{inactive}"]'
                ),
                set[str](),
            )
            if address == "aws_cloudfront_distribution.staging":
                allow = {"origin", "etag", "last_modified_time", "status"}
        else:
            allow = ROUTING_RESOURCES.get(address, set())
        require(bool(allow), "phase_boundary")
        require(
            actions == ["update"]
            or (
                phase != "prepare"
                and address == "aws_api_gateway_deployment.tollchat"
                and actions == ["create", "delete"]
            ),
            "action",
        )
        require(changed(before, after) <= allow, "field_boundary")
        unknown_values = deepcopy(change.get("after_unknown", {}))
        if address == f'aws_lambda_function.tollchat_proxy["{inactive}"]':
            target = slots[inactive]
            expected_environment = dict(
                target["proxy_environment"],
                RELEASE_ID=target["release_id"],
                AGENTCORE_RUNTIME_ARN=previous["slots"][inactive]["runtime_arn"],
                AGENTCORE_RUNTIME_ENDPOINT=previous["slots"][inactive]["endpoint"],
            )
            actual_environment = deepcopy(after["environment"][0]["variables"])
            actual_environment.pop("AGENTCORE_RUNTIME_VERSION", None)
            require(actual_environment == expected_environment, "proxy_configuration")
            environment_unknown = unknown_values.pop("environment", [])
            require(
                not has_unknown(environment_unknown)
                or environment_unknown
                == [{"variables": {"AGENTCORE_RUNTIME_VERSION": True}}],
                "unknown_proxy_configuration",
            )
            require(
                after["s3_key"] == target["proxy_key"]
                and after["s3_object_version"] == target["proxy_object_version"]
                and after["source_code_hash"] == target["proxy_sha256"],
                "proxy_artifact",
            )
        if address == f'aws_bedrockagentcore_agent_runtime.tollchat["{inactive}"]':
            target = slots[inactive]
            require(
                after["environment_variables"]
                == dict(
                    target["runtime_environment"],
                    TOLLCHAT_RELEASE_ID=target["release_id"],
                ),
                "runtime_configuration",
            )
            expected_artifact = deepcopy(before["agent_runtime_artifact"])
            artifact = expected_artifact[0]["code_configuration"][0]["code"][0]["s3"][0]
            artifact.update(
                prefix=target["runtime_key"],
                version_id=target["runtime_object_version"],
            )
            require(
                after["agent_runtime_artifact"] == expected_artifact, "runtime_artifact"
            )
        unknown = {k for k, v in unknown_values.items() if has_unknown(v)}
        require(
            unknown <= allow
            and not (unknown & {"environment_variables", "origin", "uri"}),
            "unknown_target",
        )
        if address.startswith("aws_cloudfront_distribution."):
            target_slot = (
                inactive
                if phase == "prepare"
                else (previous["active"] if address.endswith(".staging") else active)
            )
            target = slots[target_slot]
            # URLs are fixed slot identities, not candidate-supplied input.
            published = previous["slots"][target_slot]
            origins(
                before["origin"],
                after["origin"],
                api=published["proxy_url"].removeprefix("https://").rstrip("/"),
                prefix=target["asset_prefix"],
            )
        if address.startswith("aws_api_gateway_integration."):
            target = previous["slots"][active]["proxy_arn"] + ":live"
            require(
                after.get("uri")
                == before["uri"].replace(
                    previous["slots"][previous["active"]]["proxy_arn"] + ":live", target
                ),
                "private_target",
            )
        count += 1
    return {
        "phase": phase,
        "mutations": count,
        "inputs_sha256": digest({"release_slots": slots, "active_slot": active}),
    }


def validate_bootstrap(
    plan: dict[str, Any], approved_sha256: str, saved_plan: bytes
) -> dict[str, Any]:
    """A separately human-reviewed *exact binary plan*, never an ordinary release."""
    require(
        re.fullmatch(r"[a-f0-9]{64}", approved_sha256) is not None
        and hashlib.sha256(saved_plan).hexdigest() == approved_sha256,
        "bootstrap_approval",
    )
    require(
        plan["variables"]["environment"]["value"] == "development",
        "bootstrap_environment",
    )
    require(
        plan.get("complete") is True
        and plan.get("errored") is False
        and not plan.get("resource_drift"),
        "incomplete_or_drift",
    )
    for item in plan.get("resource_changes", []):
        importing = item.get("change", {}).get("importing")
        if importing is not None:
            require(
                item["address"]
                == 'aws_bedrockagentcore_agent_runtime.tollchat["green"]'
                and importing.get("id")
                == plan["variables"]["release_slots"]["value"]["green"]["runtime_id"],
                "bootstrap_import",
            )
        if "previous_address" in item:
            require(
                BOOTSTRAP_MOVES.get(item["previous_address"]) == item["address"],
                "bootstrap_move",
            )
        if item["change"]["actions"] == ["forget"]:
            require(
                item["address"].split("[")[0] in BOOTSTRAP_FORGET, "bootstrap_forget"
            )
        require(
            "delete" not in item["change"]["actions"]
            or item["address"].split("[")[0]
            in {
                "aws_lambda_permission.tollchat_api",
                "aws_api_gateway_deployment.tollchat",
            },
            "bootstrap_delete",
        )
    return {"phase": "bootstrap", "saved_plan_sha256": approved_sha256}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=["inputs", "bootstrap", "prepare", "promote", "recover"]
    )
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--saved-plan", type=Path)
    parser.add_argument("--approved-sha256")
    args = parser.parse_args()
    try:
        if args.phase == "inputs":
            require(args.previous is not None, "previous_state")
            print(
                json.dumps(
                    desired(json.loads(args.previous.read_text())), sort_keys=True
                )
            )
            return 0
        require(args.plan is not None, "saved_plan")
        plan = json.loads(args.plan.read_text())
        if args.phase == "bootstrap":
            if args.saved_plan is None or args.approved_sha256 is None:
                raise Rejected("bootstrap_approval")
            result = validate_bootstrap(
                plan, args.approved_sha256, args.saved_plan.read_bytes()
            )
        else:
            require(args.previous is not None, "previous_state")
            result = validate_plan(
                plan, json.loads(args.previous.read_text()), args.phase
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Rejected, KeyError, TypeError, ValueError, OSError):
        print("blue-green gate: rejected", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

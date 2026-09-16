"""Credential-free release boundary and recovery rehearsal."""

import base64
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts import blue_green as gate
from scripts import release_blue_green as delivery


def slot(name: str, release: str) -> dict[str, Any]:
    return {
        "release_id": release,
        "runtime_id": "nova_toll_v2_development"
        + ("_green" if name == "green" else "")
        + "-123",
        "runtime_key": f"releases/{release}/agentcore.zip",
        "runtime_object_version": "runtime-object-1",
        "runtime_sha256": "a" * 64,
        "proxy_key": f"releases/{release}/chat-proxy.zip",
        "proxy_object_version": "proxy-object-1",
        "proxy_sha256": base64.b64encode(b"a" * 32).decode(),
        "runtime_environment": {"DB_USER": "agent"},
        "proxy_environment": {"SESSION_TABLE_NAME": "sessions"},
        "asset_prefix": f"/releases/{release}",
        "runtime_arn": f"arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/{name}",
        "runtime_version": "3",
        "endpoint": "preview",
        "proxy_arn": f"arn:aws:lambda:us-east-1:903859731897:function:{name}",
        "proxy_version": "7",
        "proxy_url": f"https://{name}.lambda-url.us-east-1.on.aws/",
    }


def previous() -> dict[str, Any]:
    return {
        "active": "blue",
        "slots": {"blue": slot("blue", "release1"), "green": slot("green", "release0")},
    }


def plan(
    inputs: dict[str, Any], changes: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    return {
        "complete": True,
        "errored": False,
        "resource_drift": [],
        "variables": {key: {"value": value} for key, value in inputs.items()},
        "resource_changes": list(changes),
    }


def change(
    address: str,
    before: dict[str, Any],
    after: dict[str, Any],
    actions: list[str] | None = None,
    unknown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "address": address,
        "mode": "managed",
        "provider_name": "registry.terraform.io/hashicorp/aws",
        "change": {
            "actions": actions or ["update"],
            "before": before,
            "after": after,
            "after_unknown": unknown or {},
        },
    }


def test_two_successive_releases_preserve_active_descriptor() -> None:
    state = previous()
    for inactive, release in (("green", "release2"), ("blue", "release3")):
        original = deepcopy(state)
        candidate = slot(inactive, release)
        inputs = gate.desired(state, candidate)
        gate.validate_plan(plan(inputs), state, "prepare")
        assert inputs["release_slots"][state["active"]] == gate.descriptor(
            original["slots"][state["active"]]
        )
        state["slots"][inactive] = candidate
        promotion = gate.desired(state, promote=True)
        gate.validate_plan(plan(promotion), state, "promote")
        state["active"] = promotion["active_slot"]


@pytest.mark.parametrize(
    "address",
    [
        'aws_lambda_function.tollchat_proxy["blue"]',
        "aws_cloudfront_distribution.site",
        "aws_cloudfront_function.public_chat_routes",
        "aws_iam_role.tollchat_runtime",
        "aws_security_group.tollchat_runtime",
        "aws_scheduler_schedule.timed_checks",
        "aws_lambda_function.loader",
    ],
)
def test_preparation_rejects_active_and_shared_mutations(address: str) -> None:
    before = previous()
    candidate = gate.desired(before, slot("green", "release2"))
    with pytest.raises(gate.Rejected):
        gate.validate_plan(
            plan(
                candidate, [change(address, {"memory_size": 256}, {"memory_size": 512})]
            ),
            before,
            "prepare",
        )


@pytest.mark.parametrize("phase", ["promote", "recover"])
def test_routing_phases_reject_rebuilds_and_unrelated_changes(phase: str) -> None:
    before = previous()
    with pytest.raises(gate.Rejected):
        gate.validate_plan(
            plan(
                gate.desired(before, promote=True),
                [
                    change(
                        'aws_lambda_function.tollchat_proxy["green"]',
                        {"source_code_hash": "old"},
                        {"source_code_hash": "new"},
                    )
                ],
            ),
            before,
            phase,
        )


def test_moves_are_bootstrap_only_even_when_noop() -> None:
    before = previous()
    name = "aws_lambda_function.tollchat_proxy"
    moved = change(name + '["blue"]', {}, {}, ["no-op"])
    moved["previous_address"] = name
    with pytest.raises(gate.Rejected):
        gate.validate_plan(
            plan(gate.desired(before, slot("green", "release2")), [moved]),
            before,
            "prepare",
        )
    bootstrap = plan({"environment": "development"}, [moved])
    import hashlib

    raw = b"reviewed saved plan"
    gate.validate_bootstrap(bootstrap, hashlib.sha256(raw).hexdigest(), raw)
    moved["previous_address"] = "aws_lambda_function.loader"
    with pytest.raises(gate.Rejected):
        gate.validate_bootstrap(bootstrap, hashlib.sha256(raw).hexdigest(), raw)


def test_identity_rejects_primary_fallback_and_wrong_invoked_release() -> None:
    expected = slot("green", "release2")
    serving = {
        key: expected[key]
        for key in (
            "release_id",
            "proxy_arn",
            "proxy_version",
            "runtime_arn",
            "runtime_version",
            "endpoint",
        )
    }
    serving["runtime_release_id"] = expected["release_id"]
    gate.verify_serving(serving, expected)
    for key in ("release_id", "proxy_version", "runtime_arn", "runtime_release_id"):
        with pytest.raises(gate.Rejected):
            gate.verify_serving(dict(serving, **{key: "blue"}), expected)
    prepared = previous()
    prepared["slots"]["green"] = expected
    record = {
        "claim": "claim-1",
        "state_sha256": gate.digest(prepared),
        "checked_at": 1000,
        "checks": {key: True for key in gate.CHECKS},
        "serving": serving,
    }
    gate.verify_evidence(record, prepared, "claim-1", 1050)
    for now, claim in ((2000, "claim-1"), (1050, "claim-2"), (999, "claim-1")):
        with pytest.raises(gate.Rejected):
            gate.verify_evidence(record, prepared, claim, now)


def test_old_and_candidate_pages_keep_their_immutable_assets() -> None:
    source = b'<script src="/chat.mjs"></script><img src="/assets/logo.png">'
    blue = delivery.render_asset("index.html", source, "blue1")
    green = delivery.render_asset("index.html", source, "green1")
    assert (
        b"/releases/blue1/chat.mjs" in blue
        and b"/releases/blue1/assets/logo.png" in blue
    )
    assert (
        b"/releases/green1/chat.mjs" in green
        and b"/releases/green1/assets/logo.png" in green
    )
    script = delivery.render_asset(
        "assets/commute-map.mjs", b'fetch("/assets/coverage.json")', "green1"
    )
    assert b"/releases/green1/assets/coverage.json" in script
    site = (Path(__file__).parents[1] / "infra/site.tf").read_text()
    assert site.count('target_origin_id           = "documents"') == 2
    assert site.count('path_pattern           = "/releases/*"') == 2

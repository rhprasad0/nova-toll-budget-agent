"""Credential-free release boundary and recovery rehearsal."""

import base64
import json
import re
from collections.abc import Callable, Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn
from unittest.mock import Mock
from urllib.parse import urljoin

import pytest

from scripts import blue_green as gate
from scripts import release_blue_green as delivery


@pytest.mark.parametrize("separate_bundle", [False, True])
@pytest.mark.parametrize("phase", ["prepare", "promote", "recover"])
def test_plan_package_paths_are_workspace_independent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, separate_bundle: bool, phase: str
) -> None:
    terraform = Mock(return_value="{}")
    monkeypatch.setattr(delivery, "terraform", terraform)
    monkeypatch.setattr(gate, "validate_plan", Mock())
    for workspace in ("bootstrap", "trusted", "release-overlay"):
        bundle = tmp_path / workspace
        root = bundle / "v2/infra"
        if separate_bundle:
            bundle = bundle / "release-overlay"
        packages = bundle / "v2/infra/build"
        packages.mkdir(parents=True)
        for name in ("loader", "publisher", "timed-checks"):
            (packages / f"{name}.zip").write_bytes(name.encode())
        delivery.plan(
            root,
            bundle,
            tmp_path / "foundation.json",
            tmp_path,
            phase,
            {},
            {},
        )
        args = terraform.call_args_list[-2].args
        assert {arg for arg in args[1:] if arg.startswith("-var=")} == {
            "-var=loader_package_path=build/loader.zip",
            "-var=publisher_package_path=build/publisher.zip",
            "-var=timed_checks_package_path=build/timed-checks.zip",
        }
        for name in ("loader", "publisher", "timed-checks"):
            assert (root / "build" / f"{name}.zip").read_bytes() == name.encode()


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


@pytest.mark.parametrize(
    "target,enabled,expected",
    [
        ("development", "true", True),
        ("development", "", False),
        ("production", "true", False),
    ],
)
def test_rehearsal_probe_is_scoped_and_restores_after_failure(
    monkeypatch: pytest.MonkeyPatch, target: str, enabled: str, expected: bool
) -> None:
    monkeypatch.setattr(delivery, "environment", target)
    monkeypatch.setenv("TOLLCHAT_DEV_REHEARSAL", enabled)
    monkeypatch.setattr(delivery.checks, "rehearsal_failure", False)

    def fail(_slot: dict[str, Any]) -> NoReturn:
        assert delivery.checks.rehearsal_failure is expected
        raise gate.Rejected("controlled_runtime_failure")

    monkeypatch.setattr(delivery, "probe", fail)
    with pytest.raises(gate.Rejected, match="controlled_runtime_failure"):
        delivery.rehearsal_probe(slot("green", "release2"))
    assert delivery.checks.rehearsal_failure is False


def test_rehearsal_candidate_rejection_clears_drill_and_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(delivery, "environment", "development")
    monkeypatch.setenv("TOLLCHAT_DEV_REHEARSAL", "true")
    monkeypatch.setattr(delivery, "readiness", Mock())
    monkeypatch.setattr(
        delivery, "aws", Mock(return_value={"Parameter": {"Value": "fake-header"}})
    )
    monkeypatch.setattr(delivery.checks, "rehearsal_failure", False)

    def fail(target: dict[str, Any]) -> NoReturn:
        assert target == previous()["slots"]["green"]
        assert delivery.checks.rehearsal_failure is True
        assert delivery.checks.candidate_header == "fake-header"
        raise gate.Rejected("controlled_runtime_failure")

    monkeypatch.setattr(delivery, "probe", fail)
    with pytest.raises(gate.Rejected, match="controlled_runtime_failure"):
        delivery.validate_candidate(previous(), "1:1")
    assert delivery.checks.rehearsal_failure is False
    assert delivery.checks.candidate_header is None


def plan(
    inputs: dict[str, Any],
    changes: Iterable[dict[str, Any]] = (),
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = prior or previous()
    after = deepcopy(before)
    if "release_slots" in inputs:
        after["active"] = inputs["active_slot"]
        for name, descriptor in inputs["release_slots"].items():
            after["slots"][name].update(descriptor)
    return {
        "complete": True,
        "errored": False,
        "resource_drift": [],
        "variables": {key: {"value": value} for key, value in inputs.items()},
        "resource_changes": list(changes),
        "output_changes": {
            "release_state": {
                "actions": ["update"] if before != after else ["no-op"],
                "before": before,
                "after": after,
                "after_unknown": False,
            }
        },
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
        gate.validate_plan(plan(inputs, prior=state), state, "prepare")
        assert inputs["release_slots"][state["active"]] == gate.descriptor(
            original["slots"][state["active"]]
        )
        state["slots"][inactive] = candidate
        promotion = gate.desired(state, promote=True)
        gate.validate_plan(plan(promotion, prior=state), state, "promote")
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


@pytest.mark.parametrize(
    "outcomes,expected_calls,expected_recovery",
    [
        ([False, False], 1, "recovered"),
        ([False, True, False, True, True], 0, "not_attempted"),
        ([True, False, False], 1, "recovered"),
        ([True] * 5, 0, "not_attempted"),
    ],
)
def test_observation_resets_failures_and_restores_at_most_once(
    outcomes: list[bool], expected_calls: int, expected_recovery: str
) -> None:
    probes = iter(outcomes)
    calls: list[str] = []
    waits: list[float] = []
    result = delivery.observe(
        lambda: next(probes),
        lambda: calls.append("restore") or True,
        sleep=waits.append,
        clock=lambda: 0,
    )
    assert len(calls) == expected_calls
    assert result["recovery"] == expected_recovery
    assert all(value == 60 for value in waits)
    if calls:
        assert result["deployment"] == "failed"
    else:
        assert result["deployment"] == "succeeded"


def test_restore_failure_and_probe_exception_stay_failed() -> None:
    def fail() -> NoReturn:
        raise RuntimeError("private detail")

    result = delivery.observe(fail, fail, sleep=lambda _: None, clock=lambda: 0)
    assert result == {
        "deployment": "failed",
        "recovery": "failed",
        "probes": [False, False],
    }
    assert "private detail" not in json.dumps(result)


def test_stale_recovery_does_not_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepared = previous()
    newer = deepcopy(prepared)
    newer["slots"]["green"] = slot("green", "newer")
    monkeypatch.setattr(delivery, "current", Mock(return_value=(newer, {})))
    monkeypatch.setattr(
        delivery, "plan", Mock(side_effect=AssertionError("stale recovery planned"))
    )
    with pytest.raises(gate.Rejected, match="stale_recovery"):
        delivery.recover(tmp_path, tmp_path, tmp_path, tmp_path, prepared)


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


def test_released_chat_module_dependencies_resolve_to_uploaded_assets() -> None:
    agent = Path(__file__).parents[1] / "agent"
    prefix = "https://example.test/releases/green1/"
    for source, destination in (
        ("public_chat.mjs", "chat.mjs"),
        ("assets/commute-map.mjs", "assets/commute-map.mjs"),
    ):
        original = (agent / source).read_bytes()
        rendered = delivery.render_asset(destination, original, "green1").decode()
        references = re.findall(r"[\"\']((?:\./|/releases/)[^\"\']+)[\"\']", rendered)
        assert references
        for reference in references:
            url = urljoin(prefix + destination, reference)
            assert url.startswith(prefix)
            assert (agent / url.removeprefix(prefix)).is_file(), url


@pytest.mark.parametrize(
    "field", ["active", "runtime_arn", "proxy_url", "release_id", "runtime_version"]
)
def test_prepare_rejects_forged_release_outputs(field: str) -> None:
    before = previous()
    saved = plan(gate.desired(before, slot("green", "release2")))
    output = saved["output_changes"]["release_state"]["after"]
    if field == "active":
        output["active"] = "green"
    else:
        output["slots"]["green"][field] = "forged"
    with pytest.raises(gate.Rejected, match="release_output"):
        gate.validate_plan(saved, before, "prepare")


def test_outputs_allow_only_actual_candidate_version_unknowns() -> None:
    before = previous()
    saved = plan(
        gate.desired(before, slot("green", "release2")),
        [
            change(
                'aws_lambda_alias.tollchat_live["green"]',
                {"function_version": "7"},
                {},
                unknown={"function_version": True},
            )
        ],
    )
    output = saved["output_changes"]["release_state"]
    del output["after"]["slots"]["green"]["proxy_version"]
    output["after_unknown"] = {"slots": {"green": {"proxy_version": True}}}
    gate.validate_plan(saved, before, "prepare")
    output["after_unknown"]["slots"]["blue"] = {"proxy_version": True}
    with pytest.raises(gate.Rejected, match="release_output"):
        gate.validate_plan(saved, before, "prepare")


def test_private_preview_output_cannot_redirect_probes() -> None:
    before = previous()
    saved = plan(gate.desired(before, slot("green", "release2")))
    saved["output_changes"]["private_preview"] = {
        "actions": ["update"],
        "before": {"origin": "trusted"},
        "after": {"origin": "untrusted"},
        "after_unknown": False,
    }
    with pytest.raises(gate.Rejected, match="shared_output"):
        gate.validate_plan(saved, before, "prepare")


@pytest.mark.parametrize(
    "field,value",
    [("ContentType", "application/octet-stream"), ("CacheControl", "no-store")],
)
def test_existing_upload_requires_browser_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    import hashlib

    source = tmp_path / "chat.mjs"
    source.write_bytes(b"export {}")
    metadata = {
        "VersionId": "version1",
        "ChecksumSHA256": base64.b64encode(
            hashlib.sha256(source.read_bytes()).digest()
        ).decode(),
        "ContentType": "text/javascript",
        "CacheControl": "immutable",
    }

    def head(*args: str) -> dict[str, str]:
        return metadata

    monkeypatch.setattr(delivery, "aws", head)
    delivery.upload(source, "bucket", "key", "text/javascript", "immutable")
    metadata[field] = value
    with pytest.raises(gate.Rejected, match="immutable_metadata"):
        delivery.upload(source, "bucket", "key", "text/javascript", "immutable")


def test_assets_reject_correct_bytes_with_wrong_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    page = b'<script src="/releases/release2/chat.mjs"></script>'
    script = b"export {}"

    def request(jar: object, path: str) -> tuple[int, str, bytes]:
        return (
            200,
            "text/html" if path.endswith(".html") else "application/octet-stream",
            page if path.endswith(".html") else script,
        )

    def head(*args: str) -> dict[str, str]:
        body = page if args[args.index("--key") + 1].endswith(".html") else script
        return {
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(body).digest()).decode()
        }

    monkeypatch.setattr(delivery.checks, "request", request)
    monkeypatch.setattr(delivery, "aws", head)
    with pytest.raises(gate.Rejected, match="asset_content"):
        delivery.assets(slot("green", "release2"))


@pytest.mark.parametrize(
    "host",
    ["dev.tollchat.ai", "tollchat.ai", "api-vpce.execute-api.us-east-1.amazonaws.com"],
)
def test_session_cookie_uses_current_probe_host(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import http.cookiejar

    monkeypatch.setattr(delivery.checks, "profile_site", "https://" + host)
    jar = http.cookiejar.CookieJar()
    cookie = http.cookiejar.Cookie(
        0,
        delivery.checks.COOKIE,
        "opaque",
        None,
        False,
        host,
        False,
        False,
        "/",
        True,
        True,
        None,
        True,
        None,
        None,
        {"HttpOnly": ""},
        False,
    )
    jar.set_cookie(cookie)
    assert delivery.checks.token(jar) == "opaque"
    cookie.domain_specified = True
    with pytest.raises(delivery.checks.CheckFailure):
        delivery.checks.token(jar)


def test_output_known_version_must_match_alias_and_noop_is_supported() -> None:
    before = previous()
    gate.validate_plan(plan(gate.desired(before)), before, "prepare")
    saved = plan(
        gate.desired(before, slot("green", "release2")),
        [
            change(
                'aws_lambda_alias.tollchat_live["green"]',
                {"function_version": "7"},
                {"function_version": "8"},
            )
        ],
    )
    with pytest.raises(gate.Rejected, match="release_output"):
        gate.validate_plan(saved, before, "prepare")
    saved["output_changes"]["release_state"]["after"]["slots"]["green"][
        "proxy_version"
    ] = "8"
    gate.validate_plan(saved, before, "prepare")


def test_recovery_accepts_pre_promotion_output_after_partial_apply() -> None:
    prepared = previous()
    promoted = dict(prepared, active="green")
    saved = plan(gate.desired(promoted, promote=True), prior=prepared)
    gate.validate_plan(saved, promoted, "recover")
    saved["output_changes"]["release_state"]["before"] = deepcopy(prepared)
    saved["output_changes"]["release_state"]["before"]["slots"]["blue"][
        "proxy_version"
    ] = "wrong"
    with pytest.raises(gate.Rejected, match="release_output"):
        gate.validate_plan(saved, promoted, "recover")


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("healthy", ("succeeded", "not_attempted", "green")),
        ("invalid_candidate", ("failed", "not_attempted", "blue")),
        ("post_promotion_failure", ("failed", "recovered", "blue")),
        ("partial_switch", ("failed", "recovered", "blue")),
        ("restore_failure", ("failed", "failed", "green")),
        ("final_state_failure", ("failed", "not_attempted", "unverified")),
        ("stale_cutover", ("failed", "not_attempted", "blue")),
        ("changed_candidate", ("failed", "not_attempted", "blue")),
        ("unhealthy_after_approval", ("failed", "not_attempted", "blue")),
    ],
)
@pytest.mark.parametrize("target", ["development", "production"])
def test_complete_release_state_machine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
    expected: tuple[str, str, str],
    target: str,
) -> None:
    import hashlib
    import sys

    if target == "development" and scenario in {
        "stale_cutover",
        "changed_candidate",
        "unhealthy_after_approval",
    }:
        pytest.skip("Production approval boundary only")
    initial = previous()
    claim = "12:1" if target == "development" else "12"
    account = "903859731897" if target == "development" else "920534282028"
    role = (
        "nova-toll-v2-development-delivery"
        if target == "development"
        else "nova-toll-production-deploy"
    )
    prepared = deepcopy(initial)
    prepared["slots"]["green"] = slot("green", "release2")
    live = deepcopy(initial)
    serial = 10
    applied: list[str] = []
    probe_calls: list[str] = []
    work = tmp_path / "work"
    work.mkdir()
    saved = work / "prepare.tfplan"
    saved.write_bytes(b"approved-preparation")
    packages = tmp_path / "v2/infra/build"
    packages.mkdir(parents=True)
    for name in ("loader", "publisher", "timed-checks"):
        (packages / f"{name}.zip").write_bytes(name.encode())
    delivery.write(
        work / "context.json",
        {
            "claim": claim,
            "previous": initial,
            "identity": {"lineage": "test-lineage", "serial": serial},
            "inputs": gate.desired(initial, prepared["slots"]["green"]),
            "plan_sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
        },
    )

    def current(_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        if scenario == "final_state_failure" and len(probe_calls) == 5:
            raise gate.Rejected("state_unavailable")
        return deepcopy(live), {"lineage": "test-lineage", "serial": serial}

    monkeypatch.setattr(delivery, "current", current)

    def terraform(_root: Path, *args: Any) -> str:
        nonlocal serial
        if args[0] == "show":
            document = plan(gate.desired(initial, prepared["slots"]["green"]))
            document["prior_state"] = {
                "values": {"outputs": {"release_state": {"value": initial}}}
            }
            document["variables"]["foundation"] = {"value": {"vpc_id": "fixed"}}
            return json.dumps(document)
        assert args[0] == "apply"
        if target == "production":
            for name in ("loader", "publisher", "timed-checks"):
                assert (_root / "build" / f"{name}.zip").read_bytes() == name.encode()
        phase = Path(args[-1]).stem
        applied.append(phase)
        if phase == "prepare":
            live.update(deepcopy(prepared))
        elif phase == "promote":
            live["active"] = "green"
            serial += 1
            if scenario == "partial_switch":
                raise gate.Rejected("terraform_failed")
        else:
            assert phase == "recover"
            if scenario == "restore_failure":
                raise gate.Rejected("terraform_failed")
            live.update(deepcopy(prepared))
        serial += 1
        return ""

    monkeypatch.setattr(delivery, "terraform", terraform)

    def planned(
        _root: Path,
        _bundle: Path,
        _foundation: Path,
        _work: Path,
        phase: str,
        before: dict[str, Any],
        inputs: dict[str, Any],
    ) -> Path:
        gate.validate_plan(plan(inputs, prior=before), before, phase)
        result = work / (phase + ".tfplan")
        result.write_bytes(phase.encode())
        return result

    monkeypatch.setattr(delivery, "plan", planned)
    monkeypatch.setattr(
        delivery,
        "aws",
        Mock(
            return_value={
                "Account": account,
                "Arn": f"arn:aws:sts::{account}:assumed-role/{role}/test",
            }
        ),
    )
    monkeypatch.setattr(delivery, "wait_routing", Mock(return_value=None))
    monkeypatch.setattr(delivery, "readiness", Mock(return_value=None))
    monkeypatch.setattr(delivery, "private_probe", Mock(return_value=None))
    monkeypatch.setattr(delivery, "assets", Mock(return_value=None))
    monkeypatch.setattr(
        delivery, "upload", Mock(return_value={"VersionId": "record-v1"})
    )

    candidate_checks = 0

    def candidate(state: dict[str, Any], claim: str) -> dict[str, Any]:
        nonlocal candidate_checks
        candidate_checks += 1
        if scenario == "invalid_candidate" or (
            scenario == "unhealthy_after_approval" and candidate_checks == 2
        ):
            raise gate.Rejected("serving_identity")
        serving = {
            key: state["slots"]["green"][key]
            for key in (
                "release_id",
                "proxy_arn",
                "proxy_version",
                "runtime_arn",
                "runtime_version",
                "endpoint",
            )
        }
        return {
            "claim": claim,
            "state_sha256": gate.digest(state),
            "checked_at": int(delivery.time.time()),
            "checks": {key: True for key in gate.CHECKS},
            "serving": dict(serving, runtime_release_id="release2"),
        }

    monkeypatch.setattr(delivery, "validate_candidate", candidate)

    def probe_once(target: dict[str, Any]) -> dict[str, Any]:
        probe_calls.append(target["release_id"])
        if target["release_id"] == "release2" and scenario in {
            "post_promotion_failure",
            "restore_failure",
        }:
            raise gate.Rejected("canary_terminal")
        return {"release_id": target["release_id"]}

    monkeypatch.setattr(delivery, "probe", probe_once)
    observe = delivery.observe

    def observing(
        probe: Callable[[], bool], restore: Callable[[], bool]
    ) -> dict[str, Any]:
        return observe(
            probe,
            restore,
            sleep=lambda _: None,
            clock=lambda: 0,
        )

    monkeypatch.setattr(delivery, "observe", observing)
    output = tmp_path / "result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_blue_green.py",
            "prepare-production" if target == "production" else "finish",
            "--environment",
            target,
            "--terraform-root",
            str(tmp_path),
            "--bundle-root",
            str(tmp_path),
            "--foundation-vars",
            str(tmp_path / "foundation.json"),
            "--work-dir",
            str(work),
            "--output",
            str(output),
            "--claim",
            claim,
        ]
        + (["--saved-plan", str(saved)] if target == "production" else []),
    )
    status = delivery.main()
    result = json.loads(output.read_text())
    if target == "production" and scenario != "invalid_candidate":
        assert status == 0
        assert result["deployment"] == "awaiting_approval"
        assert result["active"] == "blue"
        assert applied == ["prepare"]
        assert not probe_calls
        context = json.loads((work / "context.json").read_text())
        assert context["prepared_identity"]["serial"] == serial
        if scenario == "stale_cutover":
            serial += 1
        if scenario == "changed_candidate":
            live["slots"]["green"]["runtime_version"] = "99"
        monkeypatch.setattr(delivery, "load_recovery", Mock(return_value=context))
        delivery.write(tmp_path / "release-manifest.json", {"commit_sha": "release2"})
        monkeypatch.setenv("GITHUB_SHA", "release2")
        resume_args = sys.argv[:-2]
        resume_args[1] = "promote-production"
        monkeypatch.setattr(
            sys,
            "argv",
            [*resume_args, "--release-id", "release2", "--record-version", "record-v1"],
        )
        status = delivery.main()
        result = json.loads(output.read_text())
    assert (result["deployment"], result["recovery"], result["active"]) == expected
    assert status == (0 if scenario == "healthy" else 1)
    assert applied.count("recover") <= 1
    assert applied == (
        ["prepare"]
        if scenario
        in {
            "invalid_candidate",
            "stale_cutover",
            "changed_candidate",
            "unhealthy_after_approval",
        }
        else ["prepare", "promote"]
        if scenario in {"healthy", "final_state_failure"}
        else ["prepare", "promote", "recover"]
    )
    assert live["slots"]["blue"] == initial["slots"]["blue"]
    if scenario == "healthy":
        assert probe_calls == ["release2"] * 5
        assert candidate_checks == (2 if target == "production" else 1)
    if scenario == "post_promotion_failure":
        assert probe_calls == ["release2", "release2", "release1"]
    delivery.write(
        tmp_path / "demonstration.json",
        {
            "mode": "simulated",
            "scenario": scenario,
            "applied_phases": applied,
            "deployment": result["deployment"],
            "recovery": result["recovery"],
            "active": result["active"],
            "probes": result.get("probes", []),
        },
    )


def test_production_cannot_use_automatic_finish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys

    arguments = [
        "release_blue_green.py",
        "finish",
        "--environment",
        "production",
        "--claim",
        "12",
    ]
    for flag in ("terraform-root", "bundle-root", "foundation-vars", "work-dir"):
        arguments.extend(["--" + flag, str(tmp_path)])
    output = tmp_path / "result.json"
    arguments.extend(["--output", str(output)])
    monkeypatch.setattr(sys, "argv", arguments)
    aws = Mock(
        side_effect=AssertionError("Legacy production finish must not reach AWS")
    )
    monkeypatch.setattr(delivery, "aws", aws)
    assert delivery.main() == 1
    assert json.loads(output.read_text())["deployment"] == "failed"
    aws.assert_not_called()


def test_recovery_rechecks_state_serial_after_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepared = previous()
    states = iter([(prepared, {"serial": 10}), (prepared, {"serial": 11})])
    monkeypatch.setattr(delivery, "current", Mock(side_effect=states))
    monkeypatch.setattr(
        delivery, "plan", Mock(return_value=tmp_path / "recover.tfplan")
    )
    monkeypatch.setattr(
        delivery, "terraform", Mock(side_effect=AssertionError("stale plan applied"))
    )
    with pytest.raises(gate.Rejected, match="stale_recovery"):
        delivery.recover(tmp_path, tmp_path, tmp_path, tmp_path, prepared)


@pytest.mark.parametrize(
    "release,claim",
    [("../release", "12:1"), ("release2", "../12"), ("release2", "12/1")],
)
def test_recovery_record_keys_reject_arbitrary_paths(release: str, claim: str) -> None:
    with pytest.raises(gate.Rejected):
        delivery.recovery_key(release, claim)


def test_probe_deadline_counts_as_failure_even_if_http_completed() -> None:
    clock_values = iter([0, 61, 61, 61, 122])
    result = delivery.observe(
        lambda: True,
        lambda: True,
        sleep=lambda _: None,
        clock=lambda: next(clock_values),
    )
    assert result["probes"] == [False, False]
    assert result["deployment"] == "failed"
    assert result["recovery"] == "recovered"


def test_manual_recovery_rechecks_reviewed_identity_before_planning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepared = previous()
    monkeypatch.setattr(
        delivery,
        "current",
        Mock(return_value=(prepared, {"lineage": "same", "serial": 12})),
    )
    planning = Mock()
    monkeypatch.setattr(delivery, "plan", planning)
    with pytest.raises(gate.Rejected, match="stale_recovery"):
        delivery.recover(
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path,
            prepared,
            expected_identity={"lineage": "same", "serial": 11},
        )
    planning.assert_not_called()


def test_recovery_verifies_restored_public_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepared = previous()
    monkeypatch.setattr(
        delivery, "current", Mock(return_value=(prepared, {"serial": 1}))
    )
    monkeypatch.setattr(
        delivery, "plan", Mock(return_value=tmp_path / "recover.tfplan")
    )
    for name in ("terraform", "wait_routing", "readiness", "probe", "private_probe"):
        monkeypatch.setattr(delivery, name, Mock())

    def assets(slot: dict[str, Any], *, document: bool = False) -> None:
        if slot == prepared["slots"]["blue"] and document:
            raise gate.Rejected("candidate_document")

    monkeypatch.setattr(delivery, "assets", assets)
    with pytest.raises(gate.Rejected, match="candidate_document"):
        delivery.recover(tmp_path, tmp_path, tmp_path, tmp_path, prepared)


def test_failed_manual_restore_is_reported_as_attempted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys

    state = previous()
    identity = {"lineage": "same", "serial": 10}
    monkeypatch.setattr(delivery, "current", Mock(return_value=(state, identity)))
    monkeypatch.setattr(
        delivery,
        "load_recovery",
        Mock(return_value={"prepared": state, "identity": identity}),
    )
    monkeypatch.setattr(
        delivery, "recover", Mock(side_effect=gate.Rejected("terraform_failed"))
    )
    monkeypatch.setattr(
        delivery,
        "aws",
        Mock(
            return_value={
                "Account": "903859731897",
                "Arn": "arn:aws:sts::903859731897:assumed-role/nova-toll-v2-development-delivery/test",
            }
        ),
    )
    output = tmp_path / "result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_blue_green.py",
            "recover",
            "--claim",
            "12:1",
            "--release-id",
            "release2",
            "--record-version",
            "version1",
            "--expected-state-sha256",
            gate.digest(identity),
            "--terraform-root",
            str(tmp_path),
            "--bundle-root",
            str(tmp_path),
            "--foundation-vars",
            str(tmp_path),
            "--work-dir",
            str(tmp_path),
            "--output",
            str(output),
        ],
    )
    assert delivery.main() == 1
    assert json.loads(output.read_text())["recovery"] == "failed"


@pytest.mark.parametrize("environment", ["development", "production"])
def test_private_probe_restores_transport_after_failure(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    preview = {
        "origin": "https://api-vpce-0123.execute-api.us-east-1.amazonaws.com",
        "stage": "preview",
    }
    monkeypatch.setattr(delivery, "environment", environment)
    monkeypatch.setattr(delivery, "terraform", Mock(return_value=json.dumps(preview)))
    monkeypatch.setattr(delivery.checks, "profile_site", "https://public.example")
    monkeypatch.setattr(delivery.checks, "profile_private_via6", False)
    monkeypatch.setattr(delivery.checks, "profile_path_prefix", "")

    def failed_probe(slot: dict[str, Any]) -> NoReturn:
        assert delivery.checks.profile_private_via6 == (environment == "development")
        assert delivery.checks.profile_site == preview["origin"]
        assert delivery.checks.profile_path_prefix == "/preview"
        raise ValueError("probe failed")

    monkeypatch.setattr(delivery, "probe", failed_probe)
    with pytest.raises(ValueError, match="probe failed"):
        delivery.private_probe(Path("root"), {})
    assert delivery.checks.profile_site == "https://public.example"
    assert delivery.checks.profile_path_prefix == ""
    assert delivery.checks.profile_private_via6 is False

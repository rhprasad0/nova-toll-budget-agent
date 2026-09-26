"""Retries after promotion must revalidate the exact active release."""

import base64
import hashlib
import json
import sys
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from scripts import blue_green as gate
from scripts import release_blue_green as delivery
from scripts import shared_packages
from tests.test_blue_green import previous, shared_fixture, slot

REAL_RECOVER = delivery.recover
REAL_VALIDATE = delivery.validate_candidate


@pytest.fixture
def retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    delivery.configure("development")
    for key, value in {
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "12",
        "GITHUB_RUN_ATTEMPT": "3",
        "CANARY_ARTIFACT_ID": "42",
        "CANARY_ARTIFACT_DIGEST": "sha256:" + "b" * 64,
    }.items():
        monkeypatch.setenv(key, value)
    expected = shared_fixture(tmp_path)
    prepared = previous()
    prepared["slots"]["green"] = slot("green", "a" * 40)
    for kind, name in (("runtime", "agentcore"), ("proxy", "chat-proxy")):
        raw = name.encode()
        (tmp_path / f"v2/infra/build/{name}.zip").write_bytes(raw)
        digest = hashlib.sha256(raw)
        prepared["slots"]["green"][f"{kind}_sha256"] = (
            digest.hexdigest()
            if kind == "runtime"
            else base64.b64encode(digest.digest()).decode()
        )
    actual = dict(prepared, active="green")
    identity = {"lineage": "fixed-lineage", "serial": 11}
    original = {
        "claim": "12:1",
        "environment": "development",
        "prepared": prepared,
        "prepared_identity": {"lineage": "fixed-lineage", "serial": 10},
        "bundle": delivery.bundle_identity(),
        "shared_packages": expected,
        "shared_identities": shared_packages.identities(expected),
    }
    pointer = {
        "pointer_version": "pointer-v1",
        "claim": "12:1",
        "version_id": "record-v1",
    }
    work = tmp_path / "work"
    work.mkdir()
    requests: list[tuple[str, ...]] = []

    def aws(*args: str) -> dict[str, Any]:
        requests.append(args)
        if args == ("sts", "get-caller-identity"):
            return {
                "Account": delivery.account,
                "Arn": f"arn:aws:sts::{delivery.account}:assumed-role/nova-toll-v2-development-delivery/test",
            }
        if args[:2] == ("s3api", "head-object"):
            assert args[args.index("--key") + 1] == delivery.recovery_key(
                "a" * 40, "12"
            )
            return {"VersionId": "pointer-v1"}
        assert args[:2] == ("s3api", "get-object")
        version = args[args.index("--version-id") + 1]
        assert version in {"pointer-v1", "record-v1"}
        delivery.write(
            Path(args[-1]),
            {"claim": pointer["claim"], "version_id": pointer["version_id"]}
            if version == "pointer-v1"
            else original,
        )
        return {}

    monkeypatch.setattr(delivery, "aws", aws)

    def current(_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        return deepcopy(actual), dict(identity)

    monkeypatch.setattr(delivery, "current", current)
    monkeypatch.setattr(
        delivery,
        "shared_readiness",
        Mock(return_value=dict.fromkeys(shared_packages.FUNCTIONS, "verified")),
    )
    monkeypatch.setattr(delivery, "wait_routing", Mock())
    monkeypatch.setattr(delivery, "private_probe", Mock())
    monkeypatch.setattr(delivery, "validate_candidate", Mock(return_value={}))
    monkeypatch.setattr(delivery, "probe", Mock(return_value={"release_id": "a" * 40}))
    observing = delivery.observe

    def observe(
        probe: Callable[[], bool], restore: Callable[[], bool]
    ) -> dict[str, Any]:
        return observing(probe, restore, sleep=lambda _: None, clock=lambda: 0)

    monkeypatch.setattr(delivery, "observe", observe)
    monkeypatch.setattr(delivery, "recover", Mock(return_value=True))
    for name in ("terraform", "prepare_descriptor", "upload", "plan"):
        monkeypatch.setattr(
            delivery, name, Mock(side_effect=AssertionError(f"resume called {name}"))
        )
    return {
        "root": tmp_path,
        "work": work,
        "expected": expected,
        "prepared": prepared,
        "actual": actual,
        "identity": identity,
        "original": original,
        "pointer": pointer,
        "requests": requests,
    }


def prepare(data: dict[str, Any]) -> dict[str, Any]:
    delivery.prepare_resume(
        data["root"],
        data["work"],
        "12:3",
        data["actual"],
        data["identity"],
        data["expected"],
    )
    return json.loads((data["work"] / "context.json").read_text())


def finish(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return delivery.resume_release(
        data["root"],
        data["root"],
        data["root"] / "foundation.json",
        data["work"],
        "12:3",
        data["expected"],
        context,
    )


def test_main_resumes_promoted_release_without_apply(
    retry: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    data = retry
    output = data["root"] / "result.json"
    args = [
        "release",
        "prepare-plan",
        "--terraform-root",
        str(data["root"]),
        "--bundle-root",
        str(data["root"]),
        "--foundation-vars",
        str(data["root"] / "foundation.json"),
        "--work-dir",
        str(data["work"]),
        "--output",
        str(output),
        "--claim",
        "12:3",
    ]
    monkeypatch.setattr(sys, "argv", args)
    assert delivery.main() == 0
    assert json.loads(output.read_text())["deployment"] == "resume_validation"
    args[1] = "finish"
    assert delivery.main() == 0
    result = json.loads(output.read_text())
    assert result["deployment"] == "succeeded"
    assert result["active"] == "green"
    assert result["probes"] == [True] * 5
    assert set(result["shared_components"].values()) == {"verified"}
    assert result["recovery_record"]["version_id"] == "record-v1"
    assert isinstance(delivery.validate_candidate, Mock)
    delivery.validate_candidate.assert_called_once_with(
        data["actual"], "12:3", active_release=True
    )
    assert isinstance(delivery.recover, Mock)
    delivery.recover.assert_not_called()
    assert sum(args[:2] == ("s3api", "head-object") for args in data["requests"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        "bundle",
        "missing_bundle",
        "missing_identity",
        "claim",
        "environment",
        "lineage",
        "serial",
        "slot",
        "shared",
        "package",
        "same_attempt",
        "different_run",
    ],
)
def test_resume_rejects_wrong_authority(retry: dict[str, Any], change: str) -> None:
    data = retry
    original = data["original"]
    if change == "bundle":
        original["bundle"]["digest"] = "sha256:" + "c" * 64
    elif change == "missing_bundle":
        del original["bundle"]
    elif change == "missing_identity":
        del original["prepared_identity"]
    elif change == "claim":
        original["claim"] = "12:2"
    elif change == "environment":
        original["environment"] = "production"
    elif change == "lineage":
        original["prepared_identity"]["lineage"] = "other"
    elif change == "serial":
        original["prepared_identity"]["serial"] = 99
    elif change == "slot":
        data["actual"] = deepcopy(data["actual"])
        data["actual"]["slots"]["blue"]["proxy_version"] = "999"
    elif change == "shared":
        original["shared_packages"] = {}
    elif change == "package":
        (data["root"] / "v2/infra/build/agentcore.zip").write_bytes(b"changed")
    elif change == "same_attempt":
        data["pointer"]["claim"] = "12:3"
    else:
        data["pointer"]["claim"] = "13:1"
    with pytest.raises((gate.Rejected, KeyError)):
        prepare(data)
    assert isinstance(delivery.recover, Mock)
    delivery.recover.assert_not_called()


@pytest.mark.parametrize(
    "moment", ["finish", "after_checks", "after_observation", "rollback"]
)
def test_resume_rejects_intervening_state(
    retry: dict[str, Any], monkeypatch: pytest.MonkeyPatch, moment: str
) -> None:
    context = prepare(retry)

    def changed(*args: object, **kwargs: object) -> dict[str, Any]:
        retry["identity"]["serial"] = 99
        return {"deployment": "succeeded"}

    if moment == "finish":
        retry["identity"]["serial"] += 1
    elif moment == "after_checks":
        monkeypatch.setattr(
            delivery,
            "validate_candidate",
            changed,
        )
    elif moment == "after_observation":
        monkeypatch.setattr(
            delivery,
            "observe",
            changed,
        )
    else:

        def failed(*a: object, **kw: object) -> None:
            retry["identity"]["serial"] = 99
            raise gate.Rejected("routing")

        monkeypatch.setattr(delivery, "wait_routing", failed)
        monkeypatch.setattr(delivery, "recover", REAL_RECOVER)
        result = finish(retry, context)
        assert result["recovery"] == "failed"
        assert isinstance(delivery.plan, Mock)
        delivery.plan.assert_not_called()
        return
    with pytest.raises(gate.Rejected, match="resume_state"):
        finish(retry, context)
    assert isinstance(delivery.recover, Mock)
    delivery.recover.assert_not_called()


@pytest.mark.parametrize(
    "observation,restored", [(False, True), (False, False), (True, True), (True, False)]
)
def test_authorized_failure_attempts_one_bound_rollback(
    retry: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    observation: bool,
    restored: bool,
) -> None:
    context = prepare(retry)
    if observation:
        monkeypatch.setattr(
            delivery, "probe", Mock(side_effect=gate.Rejected("unhealthy"))
        )
    else:
        monkeypatch.setattr(
            delivery, "validate_candidate", Mock(side_effect=gate.Rejected("security"))
        )
    restore = Mock(return_value=restored)
    monkeypatch.setattr(delivery, "recover", restore)
    result = finish(retry, context)
    assert result["deployment"] == "failed"
    assert result["recovery"] == ("recovered" if restored else "failed")
    restore.assert_called_once()
    assert restore.call_args.kwargs == {"expected_identity": retry["identity"]}
    assert restore.call_args.args[4] == retry["prepared"]


def test_resume_record_read_failure_never_creates_a_pointer(
    retry: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        delivery, "aws", Mock(side_effect=delivery.checks.CheckFailure("cli"))
    )
    with pytest.raises(delivery.checks.CheckFailure):
        prepare(retry)
    assert isinstance(delivery.upload, Mock)
    delivery.upload.assert_not_called()


def test_reuse_pointer_after_loss_before_promotion(retry: dict[str, Any]) -> None:
    record = delivery.save_resume_pointer(
        retry["work"],
        retry["root"],
        "12:3",
        {"key": "new", "version_id": "new"},
        retry["prepared"],
        retry["identity"],
        retry["expected"],
    )
    assert record == {
        "key": delivery.recovery_key("a" * 40, "12:1"),
        "version_id": "record-v1",
    }
    assert isinstance(delivery.upload, Mock)
    delivery.upload.assert_not_called()


def test_active_canary_uses_active_route_and_current_attempt(
    retry: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers: list[str | None] = []
    observed: list[str] = []
    expected_canary = {"commit": "a" * 40, "attempt": 3, "success": True}

    def probe(target: dict[str, Any]) -> dict[str, Any]:
        headers.append(delivery.checks.candidate_header)
        observed.append(target["release_id"])
        delivery.LAST_CANARY = expected_canary
        return target

    monkeypatch.setattr(delivery, "readiness", Mock())
    monkeypatch.setattr(delivery, "assets", Mock())
    monkeypatch.setattr(delivery, "probe", probe)
    monkeypatch.setattr(
        delivery.checks,
        "security_checks",
        Mock(return_value={"guardrail_blocked": True, "address_redacted": True}),
    )
    monkeypatch.setattr(
        delivery.checks, "request", Mock(side_effect=[(403,), (200,), (401,)])
    )
    monkeypatch.setattr(delivery.checks, "answer", Mock())
    monkeypatch.setattr(delivery.checks, "token", Mock(return_value="old-session"))
    monkeypatch.setattr(delivery.checks, "reset", Mock())
    output = retry["root"] / "canary.json"
    monkeypatch.setenv("CANARY_EVIDENCE_FILE", str(output))
    evidence = REAL_VALIDATE(retry["actual"], "12:3", active_release=True)
    assert evidence["claim"] == "12:3"
    assert evidence["serving"]["release_id"] == "a" * 40
    assert observed == ["a" * 40] * 3
    assert headers == [None, None, "invalid-candidate-header"]
    assert delivery.checks.candidate_header is None
    assert json.loads(output.read_text())["attempt"] == 3
    assert not retry["requests"]  # No request for the staging secret.
    assert isinstance(delivery.assets, Mock)
    assert [call.args[0]["release_id"] for call in delivery.assets.call_args_list] == [
        "a" * 40,
        "a" * 40,
        "release1",
    ]


@pytest.mark.parametrize("collision", [False, True])
def test_pointer_creation_is_conditional_and_collision_fails_closed(
    retry: dict[str, Any], monkeypatch: pytest.MonkeyPatch, collision: bool
) -> None:
    monkeypatch.setattr(
        delivery,
        "resume_pointer",
        Mock(side_effect=delivery.checks.CheckFailure("cli")),
    )
    upload = Mock(side_effect=gate.Rejected("immutable_upload") if collision else None)
    monkeypatch.setattr(delivery, "upload", upload)
    record = {"key": delivery.recovery_key("a" * 40, "12:3"), "version_id": "record-v3"}
    args = (
        retry["work"],
        retry["root"],
        "12:3",
        record,
        retry["prepared"],
        retry["identity"],
        retry["expected"],
    )
    if collision:
        with pytest.raises(gate.Rejected):
            delivery.save_resume_pointer(*args)
    else:
        assert delivery.save_resume_pointer(*args) == record
    upload.assert_called_once()
    assert upload.call_args.args[2] == delivery.recovery_key("a" * 40, "12")
    assert json.loads((retry["work"] / "resume-pointer.json").read_text()) == {
        "claim": "12:3",
        "version_id": "record-v3",
    }

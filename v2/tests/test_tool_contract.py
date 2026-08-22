# pyright: basic

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_tools import get_annual_toll_ballpark as ballpark_tool
from agent_tools import get_current_toll_price as pricing_tool
from scripts import check_tool_contract_versions as version_check

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "agent_tools" / "contract-manifest.json"
)


def _manifest():
    return json.loads(_MANIFEST_PATH.read_text())


def _digest(value):
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def test_runtime_spec_and_generated_contract_match_models():
    assert pricing_tool.get_current_toll_price.tool_spec == pricing_tool.TOOL_SPEC
    assert pricing_tool.TOOL_SPEC["inputSchema"] == {
        "json": pricing_tool._PricingRequest.model_json_schema(mode="validation")
    }
    assert pricing_tool.TOOL_SPEC.get("outputSchema") == {
        "json": pricing_tool._OUTPUT_ADAPTER.json_schema(mode="serialization")
    }
    assert {
        "toolSpec": pricing_tool.TOOL_SPEC,
        "progressEventSchema": pricing_tool._ProgressEvent.model_json_schema(
            mode="serialization"
        ),
        "progressMessages": {
            f"{stage}.{status}": message
            for (stage, status), message in pricing_tool._PROGRESS_MESSAGES.items()
        },
        "operationErrorSchema": pricing_tool._OperationError.model_json_schema(
            mode="serialization"
        ),
        "operationErrorTemplate": pricing_tool._SAFE_ERROR,
    } == pricing_tool.TOOL_CONTRACT


def test_generated_contract_matches_versioned_digest():
    manifest = _manifest()["get_current_toll_price"]
    assert manifest["current"] == "1.4.0"
    assert (
        _digest(pricing_tool.TOOL_CONTRACT) == manifest["releases"][manifest["current"]]
    )


def test_ballpark_runtime_contract_matches_models_and_manifest():
    assert ballpark_tool.get_annual_toll_ballpark.tool_spec == ballpark_tool.TOOL_SPEC
    assert ballpark_tool.TOOL_SPEC["inputSchema"] == {
        "json": ballpark_tool._BallparkRequest.model_json_schema(mode="validation")
    }
    assert ballpark_tool.TOOL_SPEC.get("outputSchema") == {
        "json": ballpark_tool._OUTPUT_ADAPTER.json_schema(mode="serialization")
    }
    expected = {
        "toolSpec": ballpark_tool.TOOL_SPEC,
        "progressEventSchema": ballpark_tool._ProgressEvent.model_json_schema(
            mode="serialization"
        ),
        "progressMessages": {
            f"{stage}.{status}": message
            for (stage, status), message in ballpark_tool._PROGRESS_MESSAGES.items()
        },
        "operationErrorSchema": ballpark_tool._OperationError.model_json_schema(
            mode="serialization"
        ),
        "operationErrorTemplate": ballpark_tool._SAFE_ERROR,
    }
    assert expected == ballpark_tool.TOOL_CONTRACT
    manifest = _manifest()["get_annual_toll_ballpark"]
    assert manifest["current"] == "3.0.0"
    assert _digest(expected) == manifest["releases"][manifest["current"]]


def test_manifest_accepts_new_contract_with_preserved_one_dot_zero_release():
    current = _manifest()
    previous = copy.deepcopy(current)
    previous.pop("get_annual_toll_ballpark")
    version_check.validate_manifest_update(previous, current)


def test_manifest_accepts_additive_version_advance():
    previous = _manifest()
    current = copy.deepcopy(previous)
    current["get_current_toll_price"]["current"] = "1.5.0"
    current["get_current_toll_price"]["releases"]["1.5.0"] = "a" * 64
    version_check.validate_manifest_update(previous, current)


def test_zero_base_ref_uses_head_parent(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="parent-sha\n")

    monkeypatch.setattr(version_check.subprocess, "run", run)

    assert version_check.comparison_ref("0" * 40) == "parent-sha"
    assert calls[0][0] == ["git", "rev-parse", "--verify", "HEAD^"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda manifest: manifest["get_current_toll_price"]["releases"].update(
                {"1.0.0": "b" * 64}
            ),
            "rewrites",
        ),
        (
            lambda manifest: (
                manifest["get_current_toll_price"]["releases"].update(
                    {"0.9.0": "c" * 64}
                ),
                manifest["get_current_toll_price"].update({"current": "0.9.0"}),
            ),
            "must be the newest release",
        ),
        (
            lambda manifest: manifest["get_current_toll_price"].update(
                {"current": "version-one"}
            ),
            "invalid semantic version",
        ),
        (
            lambda manifest: manifest["get_current_toll_price"]["releases"].update(
                {"01.0.0": "d" * 64}
            ),
            "invalid semantic version",
        ),
        (
            lambda manifest: manifest["get_current_toll_price"]["releases"].update(
                {"1.0.0": "not-a-digest"}
            ),
            "invalid SHA-256",
        ),
        (
            lambda manifest: manifest["get_current_toll_price"]["releases"].update(
                {"2.0.0": "e" * 64}
            ),
            "must be the newest release",
        ),
        (
            lambda manifest: manifest["get_current_toll_price"]["releases"].update(
                {"0.9.0": "f" * 64}
            ),
            "without advancing current",
        ),
    ],
)
def test_manifest_rejects_invalid_updates(mutate, message):
    previous = _manifest()
    current = copy.deepcopy(previous)
    mutate(current)
    with pytest.raises(ValueError, match=message):
        version_check.validate_manifest_update(previous, current)

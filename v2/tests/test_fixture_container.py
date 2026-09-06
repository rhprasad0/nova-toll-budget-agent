# pyright: basic
"""Boundary regressions; the unchanged fixture runner has its own semantic tests."""

import json
import os
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from eval import container_runner, fixture_runner
from eval import container_worker as worker
from eval.fixture_runner import FixtureRunPacket, RateCard


def _packet():
    script = (
        {
            "turn": 0,
            "tool": "get_current_toll_price",
            "request": {"origin": "a"},
            "fixture_id": "one",
        },
        {
            "turn": 1,
            "tool": "get_annual_toll_ballpark",
            "request": {"origin": "b"},
            "fixture_id": "two",
        },
    )
    return FixtureRunPacket(
        case_id="sample",
        prompt="First question",
        conversation=("First question", "Second question"),
        fixture_id=None,
        fixture_result_kind=None,
        fixture_request=None,
        fixture_payload=None,
        fixture_bytes=b"unused-host-evidence",
        prompt_points=({"id": "a"}, {"id": "b"}),
        render_date=date(2026, 9, 5),
        script=script,
        fixture_evidence=tuple(
            {
                "id": step["fixture_id"],
                "tool": step["tool"],
                "request": step["request"],
                "result": {"value": index},
                "raw_bytes": b"unused-host-evidence",
                "path": Path("host-only"),
                "declaration": {"assertion": "host-only"},
            }
            for index, step in enumerate(script)
        ),
        strict_usage=True,
        dataset_version="2.1.0",
    )


def _card():
    return RateCard("documented-source", "2026-09-05", "a" * 64, 0.2, 1.2, 0.02, 0.25)


def test_worker_projects_only_runtime_fields_and_preserves_order(monkeypatch, capfd):
    key = "synthetic-provider-credential"
    original = worker.toll_agent.load_openai_api_key
    model = object()

    def build():
        assert worker.toll_agent.load_openai_api_key() == key
        print(key)
        print(key, file=sys.stderr)
        os.write(2, key.encode())
        return model

    calls = []

    def trial(packet, **kwargs):
        calls.append((packet, kwargs))
        assert kwargs["model"] is model
        record = worker.failure_record(packet.case_id, kwargs["trial_id"])
        record.update(exit_code=0, failure_class="none")
        return record

    monkeypatch.setattr(worker.toll_agent, "_build_model", build)
    monkeypatch.setattr(worker, "run_fixture_trial", trial)
    packet = _packet()
    wire = worker.packet_to_wire(packet)
    encoded_wire = json.dumps(wire)
    assert (
        "host-only" not in encoded_wire and "unused-host-evidence" not in encoded_wire
    )
    assert "raw_bytes" not in encoded_wire and "fixture_bytes" not in encoded_wire
    raw = worker.encode_input(packet, _card(), "trial-1", key)
    assert key.encode() not in raw.split(b"\n")[1]
    result = worker.execute_input(raw)
    assert result["exit_code"] == 0 and len(calls) == 1
    assert calls[0][0].script == packet.script
    assert calls[0][0].conversation == packet.conversation
    assert calls[0][0].prompt_points == packet.prompt_points
    assert worker.toll_agent.load_openai_api_key is original
    assert key not in json.dumps(result)
    captured = capfd.readouterr()
    assert key not in captured.out + captured.err
    for malformed in (
        raw + b"extra",
        raw + raw,
        b'{"credential":"x","credential":"y"}\n{}\n',
    ):
        assert worker.execute_input(malformed)["failure_class"] == "infra_dependency"
    wire["assertions"] = ["must not reach worker"]
    with pytest.raises(ValueError):
        worker.packet_from_wire(wire)


def test_model_loader_restored_and_error_diagnostics_hidden(monkeypatch, capfd):
    key = "synthetic-provider-credential"
    original = worker.toll_agent.load_openai_api_key

    def fail():
        os.write(1, key.encode())
        print(key, file=sys.stderr)
        raise RuntimeError(key)

    monkeypatch.setattr(worker.toll_agent, "_build_model", fail)
    with pytest.raises(ValueError, match="model construction failed") as error:
        worker.model_from_key(key)
    assert key not in str(error.value)
    result = worker.execute_input(
        worker.encode_input(_packet(), _card(), "trial-1", key)
    )
    assert result["failure_class"] == "infra_dependency"
    assert worker.toll_agent.load_openai_api_key is original
    assert key not in json.dumps(result)
    captured = capfd.readouterr()
    assert key not in captured.out + captured.err


def test_fixture_runner_optional_artifact_storage_preserves_record(
    monkeypatch, tmp_path
):
    class Response:
        def __str__(self):
            return "test response"

    class Agent:
        def __init__(self):
            self.messages = []

        def __call__(self, _prompt):
            return Response()

    writes = []
    monkeypatch.setattr(fixture_runner, "build_agent", lambda **_kwargs: Agent())
    monkeypatch.setattr(
        fixture_runner,
        "_response_cycle_usages",
        lambda _response: [{"totalTokens": 3, "inputTokens": 2, "outputTokens": 1}],
    )
    monkeypatch.setattr(
        fixture_runner,
        "write_raw_artifact",
        lambda root, _record: writes.append(root),
    )
    packet = _packet()
    none_result = fixture_runner.run_fixture_trial(
        packet,
        model=object(),
        artifact_root=None,
        trial_id="trial-1",
        rate_card=_card(),
    )
    path_result = fixture_runner.run_fixture_trial(
        packet,
        model=object(),
        artifact_root=tmp_path,
        trial_id="trial-1",
        rate_card=_card(),
    )
    assert writes == [tmp_path]
    assert none_result["output"]["trajectory"] == path_result["output"]["trajectory"]
    assert none_result["output"]["cost"] == path_result["output"]["cost"]


@pytest.mark.parametrize("symlink_parent", [False, True])
def test_build_image_rejects_symlinked_allowlist_before_docker(
    monkeypatch, tmp_path, symlink_parent
):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    relative = "v2/eval/fixture_runner.py"
    if symlink_parent:
        (outside / "eval").mkdir()
        (outside / "eval" / "fixture_runner.py").write_text("private", encoding="utf-8")
        (root / "v2").symlink_to(outside, target_is_directory=True)
    else:
        (root / "v2" / "eval").mkdir(parents=True)
        (root / relative).symlink_to(secret)
    monkeypatch.setattr(container_runner, "_BUILD_FILES", (relative,))
    monkeypatch.setattr(container_runner, "_CONTEXT_FILES", ("eval/fixture_runner.py",))
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Docker must not run for an invalid build input")

    monkeypatch.setattr(container_runner.subprocess, "run", run)
    with pytest.raises(ValueError, match="container build input"):
        container_runner.build_image("tollchat-fixture:test", root=root)
    assert calls == []


def test_host_runner_uses_fixed_secret_free_docker_command(monkeypatch, tmp_path):
    key = "synthetic-provider-credential"
    record = worker.failure_record("sample", "trial-1")
    calls = []

    class Result:
        returncode = 1
        stdout = json.dumps(record).encode() + b"\n"
        stderr = key.encode()

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(container_runner.subprocess, "run", run)
    evidence = container_runner.ContainerEvidence(
        image="tollchat-fixture:test",
        image_id="sha256:" + "b" * 64,
        source_digest="a" * 64,
    )
    monkeypatch.setattr(
        container_runner, "source_digest", lambda: evidence.source_digest
    )
    monkeypatch.setattr(container_runner, "_image_id", lambda _image: evidence.image_id)
    result = container_runner.run_container_trial(
        _packet(),
        key=key,
        rate_card=_card(),
        trial_id="trial-1",
        artifact_root=tmp_path,
        evidence=evidence,
    )
    assert result.record["output"]["container_execution"] == {
        "image": evidence.image,
        "image_id": evidence.image_id,
        "source_digest": evidence.source_digest,
    }
    command, kwargs = calls[0]
    assert command == [*container_runner._RUN_FLAGS, evidence.image_id]
    assert {
        "--rm",
        "-i",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--log-driver=none",
    } <= set(command)
    assert key not in command
    assert key not in kwargs["env"].values()
    assert key not in (tmp_path.as_posix())
    assert (tmp_path / "output.json").is_file()
    assert (tmp_path / "stdout.txt").is_file()
    assert (tmp_path / "exit_code.json").is_file()


def test_host_runner_redacts_rejected_identity_from_failure_record(
    monkeypatch, tmp_path
):
    key = "credential-1"
    evidence = container_runner.ContainerEvidence(
        image="tollchat-fixture:test",
        image_id="sha256:" + "b" * 64,
        source_digest="a" * 64,
    )
    monkeypatch.setattr(
        container_runner, "source_digest", lambda: evidence.source_digest
    )
    monkeypatch.setattr(container_runner, "_image_id", lambda _image: evidence.image_id)
    result = container_runner.run_container_trial(
        replace(_packet(), case_id=key),
        key=key,
        rate_card=_card(),
        trial_id=key,
        artifact_root=tmp_path,
        evidence=evidence,
    )
    assert result.record["case_id"] == "unknown"
    assert result.record["trial_id"] == "unknown"
    assert key not in json.dumps(result.record)

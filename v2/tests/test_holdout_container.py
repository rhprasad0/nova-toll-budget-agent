"""Synthetic checks for transfer integrity and container containment."""

import io
import json
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from eval.holdout_container import build, holdout, runtime


def test_transfer_tamper_fails_before_loading(tmp_path: Path) -> None:
    archive = tmp_path / "author.tar"
    archive.write_bytes(b"synthetic image")
    manifest = {
        "images": ["author"],
        "image_ids": {"author": "sha256:" + "a" * 64},
        "hashes": {"author.tar": holdout.checksum(archive)},
    }
    (tmp_path / "transfer.json").write_text(json.dumps(manifest))
    with (
        patch.object(holdout, "docker", return_value="sha256:" + "a" * 64) as docker,
        patch.dict(holdout.IMAGES),
    ):
        holdout.load(tmp_path)
        docker.assert_any_call("image", "load", "--input", str(archive))
        docker.reset_mock()
        archive.write_bytes(b"tampered image")
        with pytest.raises(ValueError, match="checksum"):
            holdout.load(tmp_path)
        docker.assert_not_called()


def test_offline_author_mounts_no_host_state() -> None:
    with patch.object(holdout, "docker") as docker:
        holdout.run("author", ["selfcheck"])
    command = docker.call_args.args
    assert command[-2:] == (holdout.IMAGES["author"], "selfcheck")
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command and "--cap-drop=ALL" in command
    assert "--env" not in command and "--mount" not in command


def test_online_evaluator_uses_readonly_corpus_and_proxy(tmp_path: Path) -> None:
    for name in ("release.zip", "context.json", "policy.json"):
        (tmp_path / name).touch()
    with (
        patch.object(holdout, "docker") as docker,
        patch.dict("os.environ", {"OPENAI_API_KEY": "private-test-value"}),
    ):
        holdout.run(
            "evaluator",
            ["evaluate", "prepare"],
            online=True,
            private=True,
            inputs=tmp_path,
            credentials=True,
        )
    calls = [call.args for call in docker.call_args_list]
    assert calls[0][:3] == ("network", "create", "--internal")
    assert calls[2][:4] == ("network", "connect", "--alias", "model-proxy")
    command = next(call for call in calls if call[0] == "run")
    assert f"type=volume,source={holdout.CORPUS},target=/private,readonly" in command
    assert f"type=volume,source={holdout.OUTPUT},target=/output" in command
    assert f"type=bind,source={tmp_path},target=/input,readonly" in command
    assert "OPENAI_API_KEY" in command
    assert "private-test-value" not in repr(calls)
    assert "HTTPS_PROXY=http://model-proxy:3128" in command
    assert calls[-1][:2] == ("network", "rm")


def test_evaluator_rejects_unrelated_input_mount(tmp_path: Path) -> None:
    (tmp_path / ".codex").mkdir()
    with (
        patch.object(holdout, "docker") as docker,
        pytest.raises(ValueError, match="input directory"),
    ):
        holdout.run("evaluator", [], inputs=tmp_path)
    docker.assert_not_called()


def test_build_export_stays_private_and_allowlisted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ignored"):
        build.build(tmp_path / "packet", ["author"])
    assert not any(
        name.startswith(("agent/", "agent-sops/", "eval/golden/cases"))
        for name in build.EXPORT_FILES
    )
    author_dockerfile = (build.SOURCE / "Dockerfile.author").read_text()
    assert "COPY . " not in author_dockerfile
    assert "@openai/codex@0.157.1" in author_dockerfile


def test_image_retag_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "transfer.json").write_text(
        json.dumps({"image_ids": {"author": "sha256:" + "a" * 64}})
    )
    with (
        patch.object(holdout, "docker", return_value="sha256:" + "b" * 64),
        pytest.raises(ValueError, match="image changed"),
    ):
        holdout.verify_images(tmp_path, ["author"])


def test_frozen_corpus_cannot_reopen_author() -> None:
    with (
        patch.object(runtime.sys, "argv", ["runtime.py", "author", "gpt-6-astra"]),
        patch.object(Path, "mkdir"),
        patch.object(Path, "exists", return_value=True),
        patch.dict(runtime.os.environ),
        patch.object(runtime.os, "umask"),
        patch.object(runtime.os, "execvp") as execute,
        pytest.raises(ValueError, match="corpus is frozen"),
    ):
        runtime.main()
    execute.assert_not_called()


def test_author_audit_finds_candidate_in_hidden_layer(tmp_path: Path) -> None:
    def layer(name: str) -> bytes:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo(name)
            info.size = 2
            archive.addfile(info, io.BytesIO(b"{}"))
        return stream.getvalue()

    kit, image = tmp_path / "kit.zip", tmp_path / "author.tar"
    with zipfile.ZipFile(kit, "w") as archive:
        archive.writestr("public/test.json", "{}")
    files = {
        "manifest.json": json.dumps([{"Layers": ["hidden.tar", "final.tar"]}]).encode(),
        "hidden.tar": layer("opt/app/toll_agent.py"),
        "final.tar": layer("opt/kit/public/test.json"),
    }
    with tarfile.open(image, "w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="candidate or repository"):
        build.audit_author(image, kit)

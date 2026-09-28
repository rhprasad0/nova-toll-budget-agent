"""Synthetic checks for transfer integrity and container containment."""

import fcntl
import io
import json
import signal
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from eval import holdout_authoring, private_holdout
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
    assert not any(holdout.AUTH in argument for argument in command)
    assert "/etc/squid/squid.conf" in calls[1]
    assert calls[-1][:2] == ("network", "rm")


@pytest.mark.parametrize("action", ["login", "logout", "author"])
def test_subscription_commands_mount_only_their_own_credentials(action: str) -> None:
    with (
        patch.object(holdout, "docker") as docker,
        patch.object(holdout, "verify_images"),
        patch.object(
            holdout.sys,
            "argv",
            [
                "holdout.py",
                action,
                *(["--model", "gpt-6-astra"] if action == "author" else []),
            ],
        ),
        patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic-unused-key"}),
    ):
        holdout.main()
    calls = [call.args for call in docker.call_args_list]
    command = next(call for call in calls if call[0] == "run")
    assert f"type=volume,source={holdout.AUTH},target=/auth" in command
    assert "OPENAI_API_KEY" not in command
    assert "synthetic-unused-key" not in repr(calls)
    assert not any("type=bind" in argument for argument in command)
    if action == "logout":
        assert command[command.index("--network") + 1] == "none"
    else:
        assert "/etc/squid/squid-author.conf" in calls[1]
    assert any(holdout.CORPUS in argument for argument in command) == (
        action == "author"
    )


def test_author_api_credentials_are_rejected_before_launch() -> None:
    with (
        patch.object(holdout, "docker") as docker,
        pytest.raises(ValueError, match="only for evaluator"),
    ):
        holdout.run("author", ["author"], credentials=True)
    docker.assert_not_called()


def test_subscription_login_refresh_and_logout(tmp_path: Path) -> None:
    auth, home = tmp_path / "auth", tmp_path / "home"
    auth.mkdir()
    home.mkdir()
    current = home / "auth.json"

    def codex(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "OPENAI_API_KEY" not in runtime.os.environ
        assert "CODEX_API_KEY" not in runtime.os.environ
        if "login" in command or "logout" in command:
            assert "--strict-config" not in command
        if command[-2:] == ["login", "--device-auth"]:
            current.write_text(
                json.dumps({"auth_mode": "chatgpt", "tokens": "synthetic-original"})
            )
        elif command[-1] == "synthetic-author-prompt":
            assert "--strict-config" in command
            signal.raise_signal(signal.SIGINT)
            assert "synthetic-original" in current.read_text()
            current.write_text(
                json.dumps({"auth_mode": "chatgpt", "tokens": "synthetic-refreshed"})
            )
            (home / "session.json").write_text("temporary session")
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.object(runtime, "AUTH_DIRECTORY", auth),
        patch.dict(
            runtime.os.environ,
            {
                "CODEX_HOME": str(home),
                "OPENAI_API_KEY": "synthetic",
                "CODEX_API_KEY": "synthetic",
            },
        ),
        patch.object(runtime.subprocess, "run", side_effect=codex),
    ):
        runtime.author_session("login", [])
        current.unlink()
        with pytest.raises(subprocess.CalledProcessError):
            runtime.author_session("author", ["synthetic-author-prompt"])
        saved = auth / "auth.json"
        assert "synthetic-refreshed" in saved.read_text()
        assert saved.stat().st_mode & 0o777 == 0o600
        assert {p.name for p in auth.iterdir()} == {".lock", "auth.json"}
        runtime.author_session("logout", [])
        assert not saved.exists()
        assert signal.getsignal(signal.SIGINT) == signal.default_int_handler


@pytest.mark.parametrize(
    "stored", [None, {"auth_mode": "apikey", "OPENAI_API_KEY": "synthetic"}]
)
def test_author_requires_subscription_login(
    tmp_path: Path, stored: dict[str, str] | None
) -> None:
    auth, home = tmp_path / "auth", tmp_path / "home"
    auth.mkdir()
    home.mkdir()
    if stored is not None:
        (auth / "auth.json").write_text(json.dumps(stored))
    with (
        patch.object(runtime, "AUTH_DIRECTORY", auth),
        patch.dict(runtime.os.environ, {"CODEX_HOME": str(home)}),
        patch.object(runtime.subprocess, "run") as execute,
        pytest.raises(ValueError, match=r"holdout\.py login"),
    ):
        runtime.author_session("author", ["synthetic"])
    execute.assert_not_called()


def test_concurrent_login_fails_without_changing_credentials(tmp_path: Path) -> None:
    with (
        (tmp_path / ".lock").open("a") as lock,
        patch.object(runtime, "AUTH_DIRECTORY", tmp_path),
        patch.dict(runtime.os.environ, {"CODEX_HOME": str(tmp_path / "home")}),
        patch.object(runtime.subprocess, "run") as execute,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="session is active"):
            runtime.author_session("login", [])
    execute.assert_not_called()


def test_private_export_never_mounts_login_volume(tmp_path: Path) -> None:
    with patch.object(holdout, "docker") as docker:
        holdout.export_private(tmp_path / "backup")
    assert f"source={holdout.AUTH}," not in repr(docker.call_args_list)


@pytest.mark.parametrize(
    "role,allowed",
    [("author", ["auth.openai.com", "chatgpt.com"]), ("evaluator", ["api.openai.com"])],
)
def test_network_check_probes_both_policies_without_auth(
    role: str, allowed: list[str]
) -> None:
    with (
        patch.dict(runtime.os.environ, {"HTTPS_PROXY": "http://model-proxy:3128"}),
        patch.object(runtime.urllib.request, "build_opener") as opener,
        patch.object(runtime.socket, "create_connection", side_effect=OSError),
        patch.object(runtime.http.client, "HTTPSConnection") as connection,
    ):
        opener.return_value.open.side_effect = runtime.urllib.error.URLError(
            "Tunnel connection failed: 403 Forbidden"
        )
        runtime.network_check(role)
    assert [
        call.args[0] for call in connection.return_value.set_tunnel.call_args_list
    ] == allowed
    denied = [call.args[0] for call in opener.return_value.open.call_args_list]
    assert denied == [
        "https://github.com/",
        "https://raw.githubusercontent.com/",
        "https://pypi.org/",
        "https://registry.npmjs.org/",
        "https://example.com/",
    ] + (
        ["https://api.openai.com/"]
        if role == "author"
        else ["https://auth.openai.com/", "https://chatgpt.com/"]
    )


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
        for name in holdout_authoring.EXPORT_FILES
    )
    author_dockerfile = (build.SOURCE / "Dockerfile.author").read_text()
    assert "COPY . " not in author_dockerfile
    assert "@openai/codex@0.157.1" in author_dockerfile


def test_evaluator_payload_matches_identity_and_imports_without_repository(
    tmp_path: Path,
) -> None:
    assert build.EVALUATOR_FILES == private_holdout.SOURCES
    build.copy_files(build.EVALUATOR_FILES, build.V2, tmp_path)
    code = """
import sys
from pathlib import Path
from unittest.mock import patch
from eval import private_holdout
from eval.holdout_container import runtime, guide_data
from scripts import golden_gate
assert private_holdout.evaluator_identity() == sys.argv[1]
assert Path(runtime.__file__).resolve() == Path('eval/holdout_container/runtime.py').resolve()
assert Path(guide_data.__file__).resolve() == Path(runtime.__file__).with_name('guide_data.py')
with patch.object(runtime.sys, 'argv', ['runtime.py', 'preflight']), patch.object(runtime.platform, 'machine', return_value='aarch64'), patch.object(Path, 'mkdir'):
    runtime.main()
with patch.object(runtime.sys, 'argv', ['runtime.py', 'guide-data']), patch.object(Path, 'mkdir'), patch.object(runtime.os, 'execv') as execute:
    runtime.main()
assert execute.call_args.args[1] == [sys.executable, str(Path(guide_data.__file__))]
Path('eval/holdout_container/guide_data.py').unlink()
try:
    with patch.object(runtime.sys, 'argv', ['runtime.py', 'preflight']), patch.object(runtime.platform, 'machine', return_value='aarch64'), patch.object(Path, 'mkdir'):
        runtime.main()
except FileNotFoundError:
    pass
else:
    raise AssertionError('preflight accepted a missing identity source')
"""
    subprocess.run(
        [sys.executable, "-c", code, private_holdout.evaluator_identity()],
        cwd=tmp_path,
        check=True,
        timeout=30,
    )
    dockerfile = (build.SOURCE / "Dockerfile.evaluator").read_text()
    entrypoint = next(
        line for line in dockerfile.splitlines() if line.startswith("ENTRYPOINT ")
    )
    assert json.loads(entrypoint.removeprefix("ENTRYPOINT ")) == [
        "python",
        "/opt/evaluator/eval/holdout_container/runtime.py",
    ]
    assert "COPY runtime.py guide_data.py /opt/" not in dockerfile


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

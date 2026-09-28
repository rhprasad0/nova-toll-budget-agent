"""Synthetic checks for the restricted private editor and guide transport."""

from __future__ import annotations

import fcntl
import http.client
import json
import signal
import socket
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from eval.holdout_container import build, guide_client, runtime


def test_workspace_owns_auth_until_sigterm(tmp_path: Path) -> None:
    auth, home = tmp_path / "auth", tmp_path / "home"
    auth.mkdir()
    home.mkdir()
    (auth / "auth.json").write_text('{"auth_mode":"chatgpt","tokens":"initial"}')

    def request() -> None:
        assert "initial" in (home / "auth.json").read_text()
        with (auth / ".lock").open("a") as lock, pytest.raises(BlockingIOError):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (home / "auth.json").write_text('{"auth_mode":"chatgpt","tokens":"refreshed"}')
        signal.raise_signal(signal.SIGTERM)

    old = signal.getsignal(signal.SIGTERM)
    with (
        patch.object(runtime, "AUTH_DIRECTORY", auth),
        patch.dict(
            runtime.os.environ,
            {"CODEX_HOME": str(home), "ANTHROPIC_API_KEY": "synthetic"},
        ),
        patch.object(runtime.http.server, "ThreadingHTTPServer") as server,
    ):
        server.return_value.__enter__.return_value.handle_request.side_effect = request
        runtime.workspace()
        server.assert_called_once_with(("127.0.0.1", 8765), runtime.ReviewHandler)
        assert "ANTHROPIC_API_KEY" not in runtime.os.environ
    assert "refreshed" in (auth / "auth.json").read_text()
    assert (auth / "auth.json").stat().st_mode & 0o777 == 0o600
    assert signal.getsignal(signal.SIGTERM) == old


def test_terminal_login_and_model_reuse_without_auth_lock(tmp_path: Path) -> None:
    home, notes = tmp_path / "home", tmp_path / "notes"
    home.mkdir()
    notes.mkdir()
    commands: list[list[str]] = []

    def codex(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[-2:] == ["login", "--device-auth"]:
            (home / "auth.json").write_text('{"auth_mode":"chatgpt"}')
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.object(runtime, "NOTES_DIRECTORY", notes),
        patch.dict(
            runtime.os.environ, {"CODEX_HOME": str(home), "OPENAI_API_KEY": "synthetic"}
        ),
        patch("builtins.input", return_value="gpt-6-astra") as prompt,
        patch.object(runtime.subprocess, "run", side_effect=codex),
        patch.object(runtime.fcntl, "flock") as lock,
    ):
        runtime.guide_session()
        runtime.guide_session()
        prompt.assert_called_once()
        lock.assert_not_called()
        assert "OPENAI_API_KEY" not in runtime.os.environ
    assert sum(command[-2:] == ["login", "--device-auth"] for command in commands) == 1
    assert sum("--model" in command for command in commands) == 2
    assert json.loads((notes / "model.json").read_text()) == {"model": "gpt-6-astra"}
    assert all(
        "--strict-config" in command for command in commands if "--model" in command
    )


def test_review_http_blocks_paths_and_external_content(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "cases-001.html").write_text("<h1>Private cases</h1>")
    secret = tmp_path / "secret.html"
    secret.write_text("private auth")
    (pages / "link.html").symlink_to(secret)
    with (
        patch.object(runtime, "GUIDE_DIRECTORY", tmp_path),
        runtime.http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), runtime.ReviewHandler
        ) as server,
    ):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = http.client.HTTPConnection("127.0.0.1", server.server_port)
            client.request("GET", "/cases-001.html")
            response = client.getresponse()
            assert response.status == 200
            assert response.read() == b"<h1>Private cases</h1>"
            csp = response.getheader("Content-Security-Policy") or ""
            assert "default-src 'none'" in csp
            assert "sandbox" in csp
            assert response.getheader("Cache-Control") == "no-store"
            for path in (
                "/",
                "/../secret.html",
                "/%2e%2e/secret.html",
                "/link.html",
                "/cases-001.html?x=1",
                "/auth.json",
            ):
                client.request("GET", path)
                response = client.getresponse()
                assert response.status == 404
                assert b"private auth" not in response.read()
            client.request("POST", "/cases-001.html", b"data")
            response = client.getresponse()
            assert response.status == 501
            response.read()
            client.close()
        finally:
            server.shutdown()
            thread.join(timeout=3)


def test_guide_client_bounded_socket_exchange(tmp_path: Path) -> None:
    path = tmp_path / "guide.sock"
    received: list[object] = []
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        server.listen(1)

        def respond() -> None:
            connection, _ = server.accept()
            with connection:
                received.append(json.loads(connection.recv(16384)))
                connection.sendall(b'{"step":"review"}\n')

        thread = threading.Thread(target=respond)
        thread.start()
        with patch.object(guide_client, "SOCKET", path):
            assert guide_client.request({"action": "status"}) == {"step": "review"}
        thread.join(timeout=3)
    assert received == [{"action": "status"}]
    for value in (list[str](), {"action": "status", "note": "x" * 16384}):
        with pytest.raises(ValueError):
            guide_client.request(value)


def test_workspace_build_contract() -> None:
    author = (build.SOURCE / "Dockerfile.author").read_text()
    assert "useradd --uid 1000 --create-home --shell /bin/bash author" in author
    assert "HOME=/home/author CODEX_HOME=/home/author/.codex SHELL=/bin/bash" in author
    assert "/home/author/.vscode-server" in author
    assert "WORKDIR /workspace" in author
    tasks = json.loads((build.SOURCE / "workspace/.vscode/tasks.json").read_text())
    assert tasks["tasks"][0]["args"] == ["/opt/runtime.py", "guide"]
    assert tasks["tasks"][0]["runOptions"]["instanceLimit"] == 1
    assert "scripts/golden_gate.py" in build.EVALUATOR_FILES
    assert "opt/guide_data.py" in build.AUTHOR_TOOLS
    evaluator = (build.SOURCE / "Dockerfile.evaluator").read_text()
    assert "COPY --chown=1000:1000 empty/ /guide/" in evaluator

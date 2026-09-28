"""Container entrypoint; only dedicated volumes persist between invocations."""

from __future__ import annotations

import fcntl
import http.client
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTH_DIRECTORY = Path("/auth")


def selfcheck() -> None:
    from eval.holdout_authoring import validate_private, verify_kit

    assert os.getuid() != 0
    assert not Path("/var/run/docker.sock").exists()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "corpus"
        shutil.copytree("/opt/kit/teaching", root)
        validate_private(
            root,
            final=False,
            kit_sha256=verify_kit(),
            public_points=Path("/opt/kit/public/prompt-points.json"),
        )
    features = subprocess.run(
        [
            "codex",
            "--no-daemon",
            "--enable",
            "apps",
            "--enable",
            "plugins",
            "--enable",
            "remote_plugin",
            "--enable",
            "hooks",
            "--enable",
            "memories",
            "features",
            "list",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    flags = {line.split()[0]: line.split()[-1] for line in features.stdout.splitlines()}
    assert all(
        flags[name] == "false"
        for name in ("apps", "plugins", "remote_plugin", "hooks", "memories")
    )
    config = tomllib.loads(Path("/etc/codex/config.toml").read_text())
    assert config["model_provider"] == "openai"
    assert config["forced_login_method"] == "chatgpt"
    assert config["cli_auth_credentials_store"] == "file"
    startup = subprocess.run(
        [
            "codex",
            "--no-daemon",
            "login",
            "status",
        ],
        env={
            key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert startup.returncode == 1
    assert "not logged in" in (startup.stdout + startup.stderr).lower()
    print("Synthetic teaching corpus, frozen kit and Codex configuration passed.")


def network_check(role: str) -> None:
    if role not in {"author", "evaluator"}:
        raise ValueError("unknown network policy")
    proxy = os.environ["HTTPS_PROXY"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy}))
    allowed = (
        ("auth.openai.com", "chatgpt.com") if role == "author" else ("api.openai.com",)
    )
    denied = (
        ("api.openai.com",) if role == "author" else ("auth.openai.com", "chatgpt.com")
    )
    for host in (
        "github.com",
        "raw.githubusercontent.com",
        "pypi.org",
        "registry.npmjs.org",
        "example.com",
        *denied,
    ):
        try:
            opener.open(f"https://{host}/", timeout=8)
        except urllib.error.URLError as error:
            assert "403" in str(error), f"expected proxy denial for {host}"
        else:
            raise AssertionError(f"proxy allowed {host}")
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=3):
            raise AssertionError("direct outbound connectivity is enabled")
    except OSError:
        pass
    # CONNECT plus TLS verifies the allowed hosts without login or inference.
    address = urllib.parse.urlsplit(proxy)
    assert address.hostname and address.port
    for host in allowed:
        connection = http.client.HTTPSConnection(
            address.hostname, address.port, timeout=15
        )
        try:
            connection.set_tunnel(host, 443)
            connection.connect()
        finally:
            connection.close()
    print(
        f"{role}: allowed hosts reachable; other policy, repository/package hosts and direct egress denied."
    )


def author_session(command: str, arguments: list[str]) -> None:
    """Persist only auth.json; Codex sessions and configuration stay on tmpfs."""
    saved = AUTH_DIRECTORY / "auth.json"
    current = Path(os.environ["CODEX_HOME"]) / "auth.json"
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        os.environ.pop(key, None)
    base = ["codex", "--no-daemon"]
    # ponytail: one author at a time; separate auth volumes if concurrent authors are needed.
    with (saved.parent / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                "another author/login session is active; close it first"
            ) from None
        if saved.exists():
            shutil.copyfile(saved, current)
            current.chmod(0o600)
        try:
            if command == "login":
                subprocess.run([*base, "login", "--device-auth"], check=True)
            elif command == "logout":
                subprocess.run([*base, "logout"], check=True)
                current.unlink(missing_ok=True)
            else:
                if (
                    not current.exists()
                    or json.loads(current.read_text()).get("auth_mode") != "chatgpt"
                ):
                    raise ValueError(
                        "author needs ChatGPT sign-in; run python3 holdout.py login"
                    )
                status = subprocess.run([*base, "login", "status"], capture_output=True)
                if status.returncode:
                    raise ValueError(
                        "author needs ChatGPT sign-in; run python3 holdout.py login"
                    )
                subprocess.run([*base, "--strict-config", *arguments], check=True)
        finally:
            if current.exists():
                temporary = saved.with_suffix(".tmp")
                shutil.copyfile(current, temporary)
                temporary.chmod(0o600)
                temporary.replace(saved)
            else:
                saved.unlink(missing_ok=True)


def main() -> None:
    os.umask(0o077)
    # Fresh tmpfs in each launched container, never host state.
    os.environ["HOME"] = "/home/author"
    os.environ["CODEX_HOME"] = "/home/author/.codex"
    Path(os.environ["CODEX_HOME"]).mkdir(parents=True, exist_ok=True)
    command, *arguments = sys.argv[1:]
    if command == "selfcheck":
        selfcheck()
    elif command == "network-check":
        network_check(arguments[0])
    elif command in {"login", "logout"}:
        author_session(command, [])
    elif command == "author":
        if Path("/private/corpus/manifest.json").exists():
            raise ValueError("this corpus is frozen; authoring is closed")
        if not arguments:
            raise ValueError("author requires a model argument")
        model, *prompt = arguments
        author_session(
            "author",
            [
                "--model",
                model,
                "--cd",
                "/private",
                "--no-alt-screen",
                " ".join(prompt)
                or "Read /opt/kit/START_HERE.md. Author the independent holdout in /private/corpus. Keep review notes in /private/review. Do not include teaching examples as cases.",
            ],
        )
    elif command == "validate":
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-m",
                "eval.holdout_authoring",
                "validate",
                "/private/corpus",
                *arguments,
            ],
        )
    elif command == "preflight":
        assert platform.machine() in {"aarch64", "arm64"}, "ARM64 emulation is required"
        assert sys.version_info[:2] == (3, 13)
        import pydantic
        import strands

        from eval import private_holdout

        assert pydantic and strands and private_holdout
        print("ARM64 Python 3.13 and private evaluator imports passed.")
    elif command == "evaluate":
        os.execv(
            sys.executable, [sys.executable, "-m", "eval.private_holdout", *arguments]
        )
    elif command == "import-review":
        name = arguments[0]
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}\.json", name):
            raise ValueError("invalid review filename")
        data = sys.stdin.read(16_385)
        if len(data.encode()) > 16_384 or not isinstance(json.loads(data), dict):
            raise ValueError("review must be a JSON object of at most 16 KiB")
        directory = Path("/output/reviews")
        directory.mkdir(exist_ok=True)
        with (directory / name).open("x") as stream:
            stream.write(data)
        print(f"Private review saved: /output/reviews/{name}")
    elif command == "export-file":
        run, filename = arguments
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", run) or filename not in {
            "summary.json",
            "private-report.json",
        }:
            raise ValueError("invalid report path")
        sys.stdout.write((Path("/output") / run / filename).read_text())
    else:
        raise ValueError("unsupported container command")


if __name__ == "__main__":
    main()

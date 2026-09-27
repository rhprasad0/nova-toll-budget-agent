"""Container entrypoint; only dedicated volumes persist between invocations."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


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
    startup = subprocess.run(
        [
            "codex",
            "--no-daemon",
            "--strict-config",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--model",
            "gpt-6-astra",
            "offline configuration check",
        ],
        env={
            key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert startup.returncode == 1
    assert "provider: private_openai" in startup.stderr
    assert "Missing environment variable: `OPENAI_API_KEY`" in startup.stderr
    print("Synthetic teaching corpus, frozen kit and Codex configuration passed.")


def network_check() -> None:
    proxy = os.environ["HTTPS_PROXY"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy}))
    for host in (
        "github.com",
        "raw.githubusercontent.com",
        "pypi.org",
        "registry.npmjs.org",
        "example.com",
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
    # Unauthenticated metadata GET checks TLS/proxy routing without inference.
    try:
        opener.open("https://api.openai.com/v1/models", timeout=15)
    except urllib.error.HTTPError as error:
        assert error.code == 401, f"unexpected API connectivity status: {error.code}"
    else:
        raise AssertionError("expected unauthenticated API response")
    print("Model API reachable; repository/package hosts and direct egress denied.")


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
        network_check()
    elif command == "author":
        if Path("/private/corpus/manifest.json").exists():
            raise ValueError("this corpus is frozen; authoring is closed")
        if not arguments or not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("author requires a model argument and OPENAI_API_KEY")
        model, *prompt = arguments
        os.execvp(
            "codex",
            [
                "codex",
                "--no-daemon",
                "--strict-config",
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

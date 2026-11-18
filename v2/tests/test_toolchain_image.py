import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
DOCKERFILE = (ROOT / "factory/agent/Dockerfile").read_text()
IMAGE = re.compile(
    r"ghcr\.io/rhprasad0/nova-toll-budget-agent/toolchain@sha256:[0-9a-f]{64}"
)
CONTAINER_JOBS = {
    "ci.yml": {"v2-loader", "v2-database", "factory", "frontend-browser"},
    "terraform.yml": {"fmt-validate"},
}


def arg(name: str) -> str:
    match = re.search(rf"^ARG {name}=(\S+)$", DOCKERFILE, re.M)
    assert match, f"factory/agent/Dockerfile must declare ARG {name}"
    return match.group(1)


def jobs(workflow: str) -> dict[str, dict[str, Any]]:
    document: dict[str, Any] = yaml.safe_load((WORKFLOWS / workflow).read_text())
    return document["jobs"]


def test_every_toolchain_consumer_pins_the_ci_digest() -> None:
    digest: str = jobs("ci.yml")["v2-loader"]["container"]["image"]
    assert IMAGE.fullmatch(digest), digest
    for workflow, expected in CONTAINER_JOBS.items():
        containers: dict[str, dict[str, str]] = {
            name: job["container"]
            for name, job in jobs(workflow).items()
            if "container" in job
        }
        assert set(containers) == expected, workflow
        for name, container in containers.items():
            assert container["image"] == digest, (
                f"{workflow} job {name} pins {container['image']}; "
                f"bump it to {digest}, the digest ci.yml's v2-loader pins"
            )
    sandbox = (ROOT / "factory/sandbox/Dockerfile").read_text()
    assert sandbox.startswith(f"FROM {digest}\n"), (
        f"factory/sandbox/Dockerfile must start FROM {digest}"
    )
    for path in [*sorted(WORKFLOWS.glob("*.yml")), ROOT / "factory/sandbox/Dockerfile"]:
        for found in IMAGE.findall(path.read_text()):
            assert found == digest, f"{path.name} pins {found}; bump it to {digest}"


def test_toolchain_pins_outside_the_image_match_its_args() -> None:
    expected = {
        "node-version": arg("NODE_VERSION"),
        "terraform_version": arg("TERRAFORM_VERSION"),
    }
    uv = arg("UV_VERSION")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document: dict[str, Any] = yaml.safe_load(path.read_text())
        steps: list[dict[str, Any]] = [
            step for job in document["jobs"].values() for step in job.get("steps", [])
        ]
        for step in steps:
            settings = step.get("with", {})
            for key, version in expected.items():
                if key in settings:
                    assert str(settings[key]) == version, (
                        f"{path.name} pins {key} {settings[key]}; "
                        f"use {version} from factory/agent/Dockerfile"
                    )
            if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                assert str(settings.get("version")) == uv, (
                    f"{path.name} installs uv {settings.get('version')}; "
                    f"pin version {uv} from factory/agent/Dockerfile's UV_VERSION"
                )
    recorded = [*sorted(WORKFLOWS.glob("*.yml")), ROOT / "infra/release_manifest.py"]
    recorded.append(ROOT / "infra/delivery_plan_validator.py")
    for path in recorded:
        for version in re.findall(
            r'"terraform_version"\s*:\s*"([^"]+)"', path.read_text()
        ):
            assert version == expected["terraform_version"], (
                f"{path.relative_to(ROOT)} records Terraform {version}; "
                f"use {expected['terraform_version']} from factory/agent/Dockerfile"
            )


def run_wrapper(home: Path, security: str) -> list[str]:
    home.mkdir()
    socket = home / "docker.sock"
    socket.touch()
    fake = home / "bin"
    fake.mkdir()
    (fake / "docker").write_text(
        "#!/usr/bin/env bash\n"
        f'case "$1" in context) echo unix://{socket} ;; info) echo "{security}" ;;\n'
        '  run) printf "%s\\n" "$@" ;; esac\n'
    )
    (fake / "docker").chmod(0o755)
    result = subprocess.run(
        [str(ROOT / "v2/scripts/toolchain.sh"), "echo", "two words"],
        cwd=ROOT / "v2",
        env={**os.environ, "HOME": str(home), "PATH": f"{fake}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return result.stdout.splitlines()


def test_toolchain_wrapper_runs_the_ci_digest_on_the_checkout(tmp_path: Path) -> None:
    digest: str = jobs("ci.yml")["v2-loader"]["container"]["image"]
    for security, user in (
        ("[name=seccomp name=rootless]", ["--user", "0:0"]),
        ("[name=seccomp]", ["--user", f"{os.getuid()}:{os.getgid()}"]),
    ):
        home = tmp_path / ("rootless" if "rootless" in security else "rootful")
        args = run_wrapper(home, security)
        assert args[-3:] == [digest, "echo", "two words"]
        assert args[args.index("--user") : args.index("--user") + 2] == user
        assert ("--group-add" in args) == ("rootless" not in security)
        volumes = {args[i + 1] for i, arg in enumerate(args) if arg == "--volume"}
        assert {
            f"{ROOT}:{ROOT}",
            f"{ROOT}/v2/.venv-toolchain:{ROOT}/v2/.venv",
            f"{home}/docker.sock:/var/run/docker.sock",
            f"{home}/.aws:{home}/.aws",
        } <= volumes
        assert args[args.index("--workdir") + 1] == str((ROOT / "v2").resolve())
        assert f"HOME={home}" in args
        assert {"--init", "--interactive"} <= set(args)
        assert "--tty" not in args
        assert "--privileged" not in args

import json
import re
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
    for path in sorted(WORKFLOWS.glob("*.yml")):
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
    bootstrap = (ROOT / "factory/bootstrap.sh").read_text()
    assert re.findall(r"^node_version=(\S+)$", bootstrap, re.M) == [
        expected["node-version"]
    ]
    assert re.findall(r"^terraform_version=(\S+)$", bootstrap, re.M) == [
        expected["terraform_version"]
    ]
    package = json.loads((ROOT / "v2/package.json").read_text())
    assert package["devDependencies"]["playwright"] == arg("PLAYWRIGHT_VERSION")

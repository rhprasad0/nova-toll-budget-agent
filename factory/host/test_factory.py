"""Checks that need no Docker: the image matches CI, and the sandbox keeps its shape.

The end-to-end check is `dispatcher.py verify` on the factory machine (FACTORY-PLAN, Stage 3).
"""

import json
import re
from pathlib import Path

import yaml

from factory.host import dispatcher as factory

ROOT = factory.CHECKOUT
DOCKERFILE = (factory.FACTORY / "agent/Dockerfile").read_text()


def arg(name: str) -> str:
    match = re.search(rf"^ARG {name}=(\S+)$", DOCKERFILE, re.M)
    assert match, name
    return match.group(1)


def test_image_toolchains_match_ci() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert f'node-version: "{arg("NODE_VERSION")}"' in ci
    assert f'terraform_version: "{arg("TERRAFORM_VERSION")}"' in ci
    package = json.loads((ROOT / "v2/package.json").read_text())
    assert package["devDependencies"]["playwright"] == arg("PLAYWRIGHT_VERSION")


def test_published_toolchain_target_carries_no_factory_proxy() -> None:
    toolchain, factory_stage = DOCKERFILE.split("\nFROM toolchain AS factory\n")
    assert toolchain.startswith("FROM debian:trixie-slim AS toolchain\n")
    for box_only in ("proxy", "--from=certs", "run-verify.sh", "prepare-work.sh"):
        assert box_only not in toolchain, box_only
        assert box_only in factory_stage, box_only


def test_only_main_publishes_the_toolchain_image_with_provenance() -> None:
    workflows = ROOT / ".github/workflows"
    publish_workflow = yaml.safe_load((workflows / "toolchain-image.yml").read_text())
    assert set(publish_workflow[True]) == {"push", "workflow_dispatch"}
    assert publish_workflow[True]["push"]["branches"] == ["main"]
    publish = publish_workflow["jobs"]["publish"]
    assert publish["if"] == "github.ref == 'refs/heads/main'"
    assert publish["permissions"]["attestations"] == "write"
    steps = [step.get("uses", "") + step.get("run", "") for step in publish["steps"]]
    builds = [step for step in steps if "docker build" in step]
    assert len(builds) == 1
    assert "--target toolchain --file factory/agent/Dockerfile" in builds[0]
    assert any(step.startswith("actions/attest-build-provenance@") for step in steps)
    build_workflow = yaml.safe_load(
        (workflows / "toolchain-image-build.yml").read_text()
    )
    assert set(build_workflow[True]) == {"pull_request"}
    assert build_workflow["permissions"] == {"contents": "read"}
    build_steps = build_workflow["jobs"]["build"]["steps"]
    assert all("push" not in step.get("run", "") for step in build_steps)
    assert all("login" not in step.get("run", "") for step in build_steps)


def test_sandbox_reaches_out_only_through_the_shared_namespace() -> None:
    args = factory.sandbox_args("wo", 983)
    assert args[args.index("--network") + 1] == "container:wo-db"
    assert "host" not in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    mounts = [
        args[i + 1] for i, a in enumerate(args) if a in {"--volume", "-v", "--mount"}
    ]
    assert mounts == ["/var/run/docker.sock:/var/run/docker.sock"]
    assert "--privileged" not in args


def test_databases_share_one_namespace_on_the_internal_network() -> None:
    candidate = factory.database_args("wo")
    assert candidate[candidate.index("--network") + 1] == factory.NETWORK
    assert candidate[-1] == factory.POSTGIS
    retained = factory.retained_database_args("wo")
    assert retained[retained.index("--network") + 1] == "container:wo-db"
    assert "PGPORT=5433" in retained
    assert {f"{factory.LABEL}=wo"} <= set(candidate) & set(retained) & set(
        factory.sandbox_args("wo", 0)
    )


def test_proxy_allowlist_has_no_wildcards_and_github_only_by_path() -> None:
    paths: dict[str, list[str]] = {}
    for line in (factory.FACTORY / "proxy/allowlist.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            host, _, path = line.strip().partition("/")
            paths.setdefault(host, []).append(path)
    assert paths["api.anthropic.com"] == [""]
    assert not [host for host in paths if "*" in host]
    # GitHub only by path, and only for one repository's release downloads each.
    github = paths["github.com"]
    assert all(path.split("/")[2:4] == ["releases", "download"] for path in github)
    assert "" not in github


def test_verify_script_comes_from_this_checkout() -> None:
    assert (Path(factory.CHECKOUT) / ".github/scripts/verify.sh").is_file()
    assert "/work/in/verify.sh" in (factory.FACTORY / "agent/run-verify.sh").read_text()

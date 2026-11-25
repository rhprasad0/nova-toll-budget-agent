"""Checks that need no Docker: the toolchain image and the proxy allowlists keep their shape."""

from pathlib import Path

import yaml

FACTORY = Path(__file__).resolve().parents[1]
ROOT = FACTORY.parent


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


def test_proxy_allowlist_has_no_wildcards_and_github_only_by_path() -> None:
    paths: dict[str, list[str]] = {}
    for line in (FACTORY / "proxy/allowlist.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            host, _, path = line.strip().partition("/")
            paths.setdefault(host, []).append(path)
    assert paths["api.anthropic.com"] == [""]
    assert not [host for host in paths if "*" in host]
    # GitHub only by path, and only for one repository's release downloads each.
    github = paths["github.com"]
    assert all(path.split("/")[2:4] == ["releases", "download"] for path in github)
    assert "" not in github


def test_sandbox_allowlist_reaches_the_worker_api_but_not_inference() -> None:
    hosts: dict[str, list[str]] = {}
    lines = (FACTORY / "proxy/sandbox-allowlist.txt").read_text().splitlines()
    for line in lines:
        if line.strip() and not line.startswith("#"):
            host, _, path = line.split()[0].partition("/")
            hosts.setdefault(host, []).append(path)
    assert sorted(hosts["api.anthropic.com"]) == [
        "v1/environments/",
        "v1/memory_stores/",
        "v1/sessions/",
        "v1/skills/",
    ]
    assert "" not in hosts["github.com"] and "" not in hosts["api.github.com"]

"""Checks that need no Docker: the image matches CI, and the sandbox keeps its shape.

The end-to-end check is `dispatcher.py verify` on the factory machine (FACTORY-PLAN, Stage 3).
"""

import json
import re
from pathlib import Path

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
    toolchain = (ROOT / "v2/lambdas/mcp_server/rust-toolchain.toml").read_text()
    channel = re.search(r'^channel = "(.+)"$', toolchain, re.M)
    assert channel and f"FROM rust:{channel.group(1)}-" in DOCKERFILE
    package = json.loads((ROOT / "v2/package.json").read_text())
    assert package["devDependencies"]["playwright"] == arg("PLAYWRIGHT_VERSION")


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

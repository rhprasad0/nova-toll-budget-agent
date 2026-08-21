"""Reject rewritten v2 tool-contract releases."""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

_MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent / "agent_tools" / "contract-manifest.json"
)
_MANIFEST_GIT_PATH = "v2/agent_tools/contract-manifest.json"
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_ZERO_SHA = "0" * 40


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(version)
    if match is None:
        raise ValueError(f"invalid semantic version {version!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _contract(manifest: dict[str, Any], name: str) -> tuple[str, dict[str, str]]:
    entry = cast(dict[str, Any], manifest[name])
    if set(entry) != {"current", "releases"}:
        raise ValueError(f"{name} must contain current and releases")

    current = cast(str, entry["current"])
    releases = cast(dict[str, str], entry["releases"])
    current_version = _version_tuple(current)
    if current not in releases:
        raise ValueError(f"current release {current} is missing")
    release_versions: list[tuple[int, int, int]] = []
    for version, digest in releases.items():
        release_versions.append(_version_tuple(version))
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError(f"release {version} has an invalid SHA-256 digest")
    if max(release_versions) != current_version:
        raise ValueError(f"current release {current} must be the newest release")
    return current, releases


def validate_manifest_update(previous: dict[str, Any], current: dict[str, Any]) -> None:
    removed = set(previous) - set(current)
    if removed:
        raise ValueError(f"manifest removes contracts: {', '.join(sorted(removed))}")

    for name in sorted(current):
        current_version, current_releases = _contract(current, name)
        if name not in previous:
            if "1.0.0" not in current_releases:
                raise ValueError(f"new contract {name} must include release 1.0.0")
            continue

        previous_version, previous_releases = _contract(previous, name)

        for version, digest in previous_releases.items():
            if current_releases.get(version) != digest:
                raise ValueError(f"manifest rewrites {name} release {version}")
        new_releases = set(current_releases) - set(previous_releases)
        if current_version == previous_version:
            if new_releases:
                raise ValueError("manifest adds releases without advancing current")
            continue
        if _version_tuple(current_version) <= _version_tuple(previous_version):
            raise ValueError(
                f"{name} version {current_version} must advance beyond {previous_version}"
            )
        if new_releases != {current_version}:
            raise ValueError("manifest must add exactly the new current release")


def _comparison_ref(base_ref: str) -> str | None:
    if base_ref != _ZERO_SHA:
        return base_ref
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _manifest_at(base_ref: str) -> dict[str, Any] | None:
    subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}^{{commit}}"],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{_MANIFEST_GIT_PATH}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return cast(dict[str, Any], json.loads(result.stdout))


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} BASE_GIT_REF", file=sys.stderr)
        return 2

    current = cast(dict[str, Any], json.loads(_MANIFEST_PATH.read_text()))
    for name in current:
        _contract(current, name)
    base_ref = _comparison_ref(sys.argv[1])
    if base_ref is None:
        print("root commit has no prior contract manifest")
        return 0

    previous = _manifest_at(base_ref)
    if previous is None:
        print("base commit predates the current-pricing contract manifest")
        return 0

    validate_manifest_update(previous, current)
    print("tool contract manifest advances cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

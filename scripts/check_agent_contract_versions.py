"""Reject rewritten agent-contract releases relative to a Git base commit."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

_CONTRACTS = ("system_prompt", "toolset")
_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "agent/contract-manifest.json"


def _version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid semantic version {version!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def validate_manifest_update(previous: dict[str, Any], current: dict[str, Any]) -> None:
    for name in _CONTRACTS:
        previous_contract = cast(dict[str, Any], previous[name])
        current_contract = cast(dict[str, Any], current[name])
        previous_releases = cast(dict[str, str], previous_contract["releases"])
        current_releases = cast(dict[str, str], current_contract["releases"])

        for version, digest in previous_releases.items():
            if current_releases.get(version) != digest:
                raise ValueError(f"manifest rewrites {name} release {version}")

        previous_version = cast(str, previous_contract["current"])
        current_version = cast(str, current_contract["current"])
        if current_version != previous_version and _version_tuple(
            current_version
        ) <= _version_tuple(previous_version):
            raise ValueError(
                f"{name} version {current_version} must advance beyond {previous_version}"
            )


def _manifest_at(base_ref: str) -> dict[str, Any] | None:
    subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}^{{commit}}"],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "show", f"{base_ref}:agent/contract-manifest.json"],
        check=False,
        capture_output=True,
        text=True,
    )
    return (
        cast(dict[str, Any], json.loads(result.stdout))
        if result.returncode == 0
        else None
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} BASE_GIT_REF", file=sys.stderr)
        return 2

    base_ref = sys.argv[1]
    if base_ref == "0" * 40:
        print("no prior branch commit; pull-request CI will enforce the manifest")
        return 0

    previous = _manifest_at(base_ref)
    if previous is None:
        print("base commit predates the agent contract manifest")
        return 0

    current = cast(dict[str, Any], json.loads(_MANIFEST_PATH.read_text()))
    validate_manifest_update(previous, current)
    print("agent contract manifest advances cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

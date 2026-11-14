#!/usr/bin/env python3
"""Rewrite the file digests in infra/development-release-manifest.json.

    python3 v2/scripts/update_release_manifest.py [DEPLOYMENT_SHA256SUMS]

The file list comes from the same selection the release verifier uses, so
`git add` new files first. Pass a `sha256sum` listing of the built zips to
refresh the package digests too. Mutations and permissions are never touched.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from infra import release_manifest  # noqa: E402

MANIFEST = "infra/development-release-manifest.json"


def update(root: Path, checksums: Path | None = None) -> bool:
    """Rewrite the manifest under `root`; return whether it changed."""
    path = root / MANIFEST
    before = path.read_text(encoding="utf-8")
    manifest = json.loads(before)
    timed = release_manifest.TIMED_CHECKS_MARKER in manifest["deployment_inputs"]
    manifest["deployment_inputs"] = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in release_manifest.tracked_inputs(root, timed)
    }
    if checksums is not None:
        listed: dict[str, str] = {}
        for line in checksums.read_text(encoding="ascii").splitlines():
            digest, _, name = line.partition("  ")
            listed[name] = digest
        if set(listed) != set(manifest["packages"]):
            raise SystemExit("checksum listing does not match the manifest's packages")
        manifest["packages"] = {name: listed[name] for name in manifest["packages"]}
    after = json.dumps(manifest, indent=2) + "\n"
    path.write_text(after, encoding="utf-8")
    return after != before


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        raise SystemExit(__doc__)
    changed = update(ROOT, Path(argv[0]) if argv else None)
    print(f"{MANIFEST}: {'updated' if changed else 'already current'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

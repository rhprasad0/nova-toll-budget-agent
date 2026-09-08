from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
release_manifest = cast(Any, importlib.import_module("infra.release_manifest"))

SPEC = importlib.util.spec_from_file_location(
    "verify_release_bundle",
    Path(__file__).parents[1] / "scripts/verify_release_bundle.py",
)
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)

COMMIT = "a" * 40
Entry = tuple[str, bytes, int | None]


@pytest.fixture
def fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for relative in bundle.FIXED_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith("schema.sql"):
            schema = "oracle" if "/oracle/" in relative else "pricing"
            version = "1.14.0" if schema == "oracle" else "1.3.0"
            path.write_text(
                f"-- {schema} schema version: {version}\n", encoding="utf-8"
            )
        else:
            path.write_bytes(relative.encode())
    asset = tmp_path / "v2/agent/assets/example.txt"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"asset")
    migration = tmp_path / "v2/db/migrations/001_create_pricing_schema.sql"
    migration.parent.mkdir(parents=True, exist_ok=True)
    migration.write_bytes(b"migration")

    def tracked_migrations(_root: Path) -> list[str]:
        return ["v2/db/migrations/001_create_pricing_schema.sql"]

    monkeypatch.setattr(bundle, "_tracked_migrations", tracked_migrations)
    return tmp_path


def _archive(
    release: Path,
    archive: Path,
    *,
    mutate: Callable[[list[Entry]], list[Entry]] | None = None,
) -> None:
    entries: list[Entry] = []
    for path in sorted(release.rglob("*")):
        if path.is_file():
            entries.append(
                (path.relative_to(release).as_posix(), path.read_bytes(), None)
            )
    if mutate is not None:
        entries = mutate(entries)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.create_system = 3
                info.external_attr = mode << 16
            output.writestr(info, data)


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(fixture_root: Path, tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "release"
    bundle.create_bundle(fixture_root, release, COMMIT)
    archive = tmp_path / "release.zip"
    _archive(release, archive)
    return archive, release


def test_valid_bundle_is_verified_and_extracted(
    fixture_root: Path, tmp_path: Path
) -> None:
    archive, _ = _bundle(fixture_root, tmp_path)
    output = tmp_path / "overlay"
    bundle.verify_bundle(
        archive,
        output,
        fixture_root,
        _digest(archive),
        COMMIT,
        {"pricing": "1.3.0", "oracle": "1.14.0"},
    )
    assert (output / bundle.MANIFEST_NAME).is_file()
    assert (
        output / "v2/infra/build/loader.zip"
    ).read_bytes() == b"v2/infra/build/loader.zip"


def test_transport_valid_bundle_is_rejected_by_reviewed_payload_binding(
    fixture_root: Path, tmp_path: Path
) -> None:
    archive, release = _bundle(fixture_root, tmp_path)
    reviewed_inputs = {
        path: hashlib.sha256((fixture_root / path).read_bytes()).hexdigest()
        for path in bundle.expected_payload_paths(fixture_root)
        if not path.startswith("v2/infra/build/")
    }
    reviewed_packages = {
        name: hashlib.sha256(
            (fixture_root / f"v2/infra/build/{name}").read_bytes()
        ).hexdigest()
        for name in release_manifest.PACKAGES
    }

    changed = release / "v2/agent/dev_chat.html"
    changed.write_bytes(b"reviewed authority differs\n")
    manifest_path = release / bundle.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    next(
        record
        for record in manifest["files"]
        if record["path"] == "v2/agent/dev_chat.html"
    )["sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _archive(release, archive)

    output = tmp_path / "overlay"
    bundle.verify_bundle(
        archive,
        output,
        fixture_root,
        _digest(archive),
        COMMIT,
        {"pricing": "1.3.0", "oracle": "1.14.0"},
    )
    with pytest.raises(
        release_manifest.Invalid, match=r"^bundle_payload_digest_mismatch$"
    ):
        release_manifest._verify_bundle_payload(
            output, reviewed_inputs, reviewed_packages
        )


@pytest.mark.parametrize(
    "failure",
    [
        "digest",
        "commit",
        "schema",
        "missing",
        "extra",
        "traversal",
        "symlink",
        "duplicate",
        "file",
    ],
)
def test_bundle_trust_boundaries_fail_closed(
    fixture_root: Path, tmp_path: Path, failure: str
) -> None:
    archive, release = _bundle(fixture_root, tmp_path)
    expected_digest = "sha256:" + "0" * 64 if failure == "digest" else _digest(archive)
    expected_commit = COMMIT
    schema_versions = {"pricing": "1.3.0", "oracle": "1.14.0"}

    if failure in {"commit", "schema"}:
        manifest_path = release / bundle.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["commit_sha" if failure == "commit" else "schema_versions"] = (
            "b" * 40 if failure == "commit" else {"pricing": "1.3.0", "oracle": "9.9.9"}
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        _archive(release, archive)
        expected_digest = _digest(archive)
    elif failure == "missing":
        _archive(release, archive, mutate=lambda entries: entries[:-1])
        expected_digest = _digest(archive)
    elif failure == "extra":
        _archive(
            release,
            archive,
            mutate=lambda entries: [*entries, ("extra.txt", b"extra", None)],
        )
        expected_digest = _digest(archive)
    elif failure == "traversal":

        def traversal(
            entries: list[tuple[str, bytes, int | None]],
        ) -> list[tuple[str, bytes, int | None]]:
            name, data, mode = entries[0]
            return [("../" + name, data, mode), *entries[1:]]

        _archive(release, archive, mutate=traversal)
        expected_digest = _digest(archive)
    elif failure == "symlink":

        def symlink(
            entries: list[tuple[str, bytes, int | None]],
        ) -> list[tuple[str, bytes, int | None]]:
            name, data, _ = entries[0]
            return [(name, data, stat.S_IFLNK | 0o777), *entries[1:]]

        _archive(release, archive, mutate=symlink)
        expected_digest = _digest(archive)
    elif failure == "duplicate":
        _archive(release, archive, mutate=lambda entries: [*entries, entries[0]])
        expected_digest = _digest(archive)
    elif failure == "file":

        def changed(
            entries: list[tuple[str, bytes, int | None]],
        ) -> list[tuple[str, bytes, int | None]]:
            name, _, mode = entries[0]
            return [(name, b"changed", mode), *entries[1:]]

        _archive(release, archive, mutate=changed)
        expected_digest = _digest(archive)

    with pytest.raises(bundle.BundleError):
        bundle.verify_bundle(
            archive,
            tmp_path / "overlay",
            fixture_root,
            expected_digest,
            expected_commit,
            schema_versions,
        )

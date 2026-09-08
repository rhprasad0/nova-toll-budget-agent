#!/usr/bin/env python3
"""Create and verify the immutable v2 release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any, cast

SCHEMA_VERSION = 1
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
FIXED_PATHS = (
    "v2/infra/build/loader.zip",
    "v2/infra/build/publisher.zip",
    "v2/infra/build/agentcore.zip",
    "v2/infra/build/chat-proxy.zip",
    "v2/agent/dev_chat.html",
    "v2/agent/public_chat.mjs",
    "v2/agent/faq.html",
    "v2/agent/privacy.txt",
    "v2/agent/terms.txt",
    "v2/agent/robots.txt",
    "v2/agent/public-api-gate.js",
    "v2/agent/public-report-routes.js",
    "v2/analytics/agent_registry.ndjson",
    "v2/db/application-schemas.json",
    "v2/db/migration-baselines.json",
    "v2/db/schema.sql",
    "v2/db/analysis.sql",
    "v2/db/roles.sql",
    "v2/db/oracle/schema.sql",
    "v2/db/oracle/data.sql",
)
SOURCE_FIXED_PATHS = (
    "v2/db/application-schemas.json",
    "v2/db/migration-baselines.json",
    "v2/db/schema.sql",
    "v2/db/oracle/schema.sql",
)
MANIFEST_NAME = "release-manifest.json"


class BundleError(ValueError):
    """A release bundle failed an integrity or inventory check."""


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise BundleError(f"bundle input is not a regular file: {relative}")
    return path


def _tracked_migrations(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", "v2/db/migrations/*.sql"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BundleError("cannot determine tracked migration inputs")
    paths = [line for line in result.stdout.splitlines() if line]
    if paths != sorted(set(paths)):
        raise BundleError("tracked migration inventory is not unique and sorted")
    return paths


def _migration_inventory(root: Path) -> list[str]:
    tracked = _tracked_migrations(root)
    directory = root / "v2/db/migrations"
    if directory.is_symlink() or not directory.is_dir():
        raise BundleError("migration directory is unavailable")
    filesystem = sorted(
        path.relative_to(root).as_posix()
        for path in directory.iterdir()
        if path.is_file() or path.is_symlink()
    )
    if filesystem != tracked:
        raise BundleError("migration inventory does not match git")
    return tracked


def expected_payload_paths(
    root: Path, *, require_sources: bool = False
) -> tuple[str, ...]:
    """Return the exact Terraform and migration inputs allowed in the bundle."""
    paths: set[str] = set(FIXED_PATHS)
    assets = root / "v2/agent/assets"
    if assets.is_symlink() or not assets.is_dir():
        raise BundleError("agent assets directory is unavailable")
    for path in assets.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise BundleError(f"bundle input is a symlink: {relative}")
        if path.is_file():
            paths.add(relative)
    paths.update(_migration_inventory(root))
    ordered = tuple(sorted(paths))
    if require_sources:
        for relative in ordered:
            _regular_file(root, relative)
    return ordered


def _schema_versions(root: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for schema, relative in (
        ("pricing", "v2/db/schema.sql"),
        ("oracle", "v2/db/oracle/schema.sql"),
    ):
        text = _regular_file(root, relative).read_text(encoding="utf-8")
        match = re.search(
            rf"^-- {schema} schema version: ([0-9]+\.[0-9]+\.[0-9]+)$",
            text,
            re.MULTILINE,
        )
        if match is None:
            raise BundleError(f"canonical schema version is unavailable: {schema}")
        versions[schema] = match.group(1)
    return versions


def _commit(value: str) -> str:
    if not COMMIT_RE.fullmatch(value):
        raise BundleError("commit SHA must be 40 lowercase hexadecimal characters")
    return value


def _checkout_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BundleError("cannot determine checked-out commit")
    return _commit(result.stdout.strip())


def _committed_bytes(root: Path, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"HEAD:{relative}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise BundleError(f"committed source is unavailable: {relative}")
    return result.stdout


def _verify_checkout_sources(
    root: Path,
    bundle: zipfile.ZipFile,
    digests: dict[str, str],
) -> None:
    for relative in (*SOURCE_FIXED_PATHS, *_migration_inventory(root)):
        source = _regular_file(root, relative)
        committed = _committed_bytes(root, relative)
        if source.read_bytes() != committed:
            raise BundleError(f"checkout source differs from HEAD: {relative}")
        if hashlib.sha256(committed).hexdigest() != digests[relative]:
            raise BundleError(f"bundle source differs from HEAD: {relative}")
        if bundle.read(relative) != committed:
            raise BundleError(f"bundle source bytes differ from HEAD: {relative}")


def _manifest_payload(root: Path, commit: str) -> dict[str, Any]:
    paths = expected_payload_paths(root, require_sources=True)
    records = [{"path": path, "sha256": _digest(root / path)} for path in paths]
    return {
        "schema_version": SCHEMA_VERSION,
        "commit_sha": _commit(commit),
        "schema_versions": _schema_versions(root),
        "files": records,
    }


def create_bundle(root: Path, release: Path, commit: str) -> None:
    payload = _manifest_payload(root, commit)
    release.mkdir(parents=True, exist_ok=True)
    for record in payload["files"]:
        relative = record["path"]
        source = _regular_file(root, relative)
        destination = release / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    manifest = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    (release / MANIFEST_NAME).write_text(manifest, encoding="utf-8")


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def _safe_archive_name(name: str) -> None:
    if not name or "\\" in name or name.startswith("/"):
        raise BundleError(f"unsafe archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise BundleError(f"unsafe archive path: {name!r}")


def _validate_manifest(
    raw: bytes,
    expected_paths: tuple[str, ...],
    expected_commit: str,
    expected_schema_versions: dict[str, str],
) -> dict[str, str]:
    try:
        manifest_value: object = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_json_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError, BundleError) as error:
        raise BundleError("malformed release manifest") from error
    if not isinstance(manifest_value, dict):
        raise BundleError("release manifest keys are invalid")
    manifest_raw = cast(dict[str, Any], manifest_value)
    if set(manifest_raw) != {
        "schema_version",
        "commit_sha",
        "schema_versions",
        "files",
    }:
        raise BundleError("release manifest keys are invalid")
    manifest = manifest_raw
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != SCHEMA_VERSION
    ):
        raise BundleError("unsupported release manifest schema")
    if manifest["commit_sha"] != _commit(expected_commit):
        raise BundleError("release manifest commit does not match checkout")
    schema_versions = manifest["schema_versions"]
    if (
        not isinstance(schema_versions, dict)
        or schema_versions != expected_schema_versions
    ):
        raise BundleError("release manifest schema versions do not match")
    records_value = manifest["files"]
    if not isinstance(records_value, list) or not records_value:
        raise BundleError("release manifest file records are invalid")
    records = cast(list[Any], records_value)
    if any(not isinstance(record, dict) for record in records):
        raise BundleError("release manifest file record is invalid")
    typed_records = [cast(dict[str, Any], record) for record in records]
    expected = tuple(expected_paths)
    if [record.get("path") for record in typed_records] != list(expected):
        raise BundleError("release manifest paths are not sorted or complete")
    digests: dict[str, str] = {}
    for record in typed_records:
        if set(record) != {"path", "sha256"}:
            raise BundleError("release manifest file record is invalid")
        path = record["path"]
        digest = record["sha256"]
        if not isinstance(path, str) or path not in expected:
            raise BundleError("release manifest contains an unknown path")
        if (
            path in digests
            or not isinstance(digest, str)
            or not DIGEST_RE.fullmatch(digest)
        ):
            raise BundleError("release manifest contains an invalid digest")
        digests[path] = digest
    if tuple(digests) != expected:
        raise BundleError("release manifest inventory is incomplete")
    return digests


def _validate_zip_info(info: zipfile.ZipInfo) -> None:
    _safe_archive_name(info.filename)
    if info.is_dir() or info.filename.endswith("/"):
        raise BundleError(f"archive contains a directory entry: {info.filename}")
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode) or (file_type and file_type != stat.S_IFREG):
        raise BundleError(f"archive contains a non-regular entry: {info.filename}")


def verify_bundle(
    archive: Path,
    output: Path,
    root: Path,
    expected_digest: str,
    expected_commit: str,
    expected_schema_versions: dict[str, str],
    *,
    verify_checkout: bool = False,
) -> None:
    if archive.is_symlink() or not archive.is_file():
        raise BundleError("artifact archive is not a regular file")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest):
        raise BundleError("artifact digest is malformed")
    if f"sha256:{_digest(archive)}" != expected_digest:
        raise BundleError("artifact archive digest does not match")
    if verify_checkout and _checkout_commit(root) != _commit(expected_commit):
        raise BundleError("checked-out commit does not match candidate commit")
    expected_paths = expected_payload_paths(root)
    expected_entries = set(expected_paths) | {MANIFEST_NAME}
    if output.exists() and (
        output.is_symlink() or not output.is_dir() or any(output.iterdir())
    ):
        raise BundleError("release overlay must be absent or empty")
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise BundleError("archive contains duplicate entries")
        for info in infos:
            _validate_zip_info(info)
        if set(names) != expected_entries:
            raise BundleError("archive inventory does not match the release allowlist")
        raw_manifest = bundle.read(MANIFEST_NAME)
        digests = _validate_manifest(
            raw_manifest, expected_paths, expected_commit, expected_schema_versions
        )
        for path, expected in digests.items():
            digest = hashlib.sha256(bundle.read(path)).hexdigest()
            if digest != expected:
                raise BundleError(f"bundle file digest mismatch: {path}")
        if verify_checkout:
            _verify_checkout_sources(root, bundle, digests)

        output.mkdir(parents=True, exist_ok=True)
        for path in (*expected_paths, MANIFEST_NAME):
            destination = output / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(path))


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--root", type=Path, default=_default_root())
    create.add_argument("--release", type=Path, required=True)
    create.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--root", type=Path, default=_default_root())
    verify.add_argument("--expected-digest", required=True)
    verify.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    verify.add_argument("--pricing-version")
    verify.add_argument("--oracle-version")
    verify.add_argument("--verify-checkout", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            create_bundle(args.root.resolve(), args.release.resolve(), args.commit)
        else:
            schema_versions = (
                {"pricing": args.pricing_version, "oracle": args.oracle_version}
                if args.pricing_version is not None and args.oracle_version is not None
                else _schema_versions(args.root.resolve())
            )
            verify_bundle(
                args.archive.resolve(),
                args.output.resolve(),
                args.root.resolve(),
                args.expected_digest,
                args.commit,
                schema_versions,
                verify_checkout=args.verify_checkout,
            )
    except (BundleError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"release bundle failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

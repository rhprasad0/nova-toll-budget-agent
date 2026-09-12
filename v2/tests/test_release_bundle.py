from __future__ import annotations

import filecmp
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
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


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@pytest.fixture
def fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for relative in bundle.FIXED_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith("schema.sql"):
            schema = "oracle" if "/oracle/" in relative else "pricing"
            version = "1.14.1" if schema == "oracle" else "1.3.0"
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


def test_timed_checks_zip_is_flat_deterministic_and_importable(tmp_path: Path) -> None:
    builder = Path(__file__).parents[1] / "scripts/build_timed_checks_zip.sh"
    package = Path(__file__).parents[1] / "infra/build/timed-checks.zip"
    requirements = builder.parent / "timed-checks-requirements.in"
    lock = builder.parent / "timed-checks-requirements.txt"
    builder_source = builder.read_text(encoding="utf-8")
    requirements_source = requirements.read_text(encoding="utf-8")

    assert "--require-hashes" in builder_source
    assert "--python-platform x86_64-manylinux_2_28" in builder_source
    assert "--python-version 3.13" in builder_source
    assert "--only-binary :all:" in builder_source
    assert "strands-agents-evals==1.1.0" in requirements_source
    assert (
        'name = "strands-agents-evals"' in (builder.parents[1] / "uv.lock").read_text()
    )
    lock_lines = lock.read_text(encoding="utf-8").splitlines()
    assert all(
        line.startswith(" ") or line.rstrip().endswith("\\")
        for line in lock_lines
        if line.strip()
    )
    assert any(line.lstrip().startswith("--hash=sha256:") for line in lock_lines)

    source_paths = {
        "handler.py",
        "timed_checks.py",
        "eval/run_evaluation.py",
        "eval/test-cases.jsonl",
        "agent/__init__.py",
        "agent/toll_agent.py",
        "agent-sops/nova-toll-pricing-assistant.sop.md",
        *{
            f"agent_tools/{path.name}"
            for path in (builder.parents[1] / "agent_tools").glob("*.py")
        },
    }
    digests: list[str] = []
    inventories: list[list[str]] = []
    first_copy = tmp_path / "timed-checks-first.zip"
    for iteration in range(2):
        result = subprocess.run(
            ["bash", str(builder)],
            cwd=builder.parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (
            package.is_file()
            and not package.is_symlink()
            and package.stat().st_size > 0
        )
        if iteration == 0:
            shutil.copyfile(package, first_copy)
        else:
            assert filecmp.cmp(package, first_copy, shallow=False)
        digests.append(_file_sha256(package))

        with zipfile.ZipFile(package) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            inventories.append(names)
            assert names == sorted(names)
            assert set(source_paths).issubset(names)
            for name in names:
                if name.startswith(("agent/", "agent_tools/", "eval/", "agent-sops/")):
                    assert name in source_paths
            assert sum(info.file_size for info in infos) <= 262_144_000
            for info in infos:
                mode = info.external_attr >> 16
                assert not info.is_dir()
                assert stat.S_ISREG(mode)
                assert stat.S_IMODE(mode) in {0o644, 0o755}
                assert info.date_time == (2020, 1, 1, 0, 0, 0)
                assert not any(
                    part == ".env" or part.startswith(".env.") or part.endswith(".pyc")
                    for part in info.filename.split("/")
                )
        assert not any(name.endswith("/") for name in names)

    assert digests[0] == digests[1]
    assert inventories[0] == inventories[1]

    stage = tmp_path / "timed-checks-stage"
    with zipfile.ZipFile(package) as archive:
        archive.extractall(stage)
    smoke = r"""
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import boto3

calls = []
boto3.client = lambda *args, **kwargs: calls.append((args, kwargs))
import agent.toll_agent
import eval.run_evaluation
import handler
import timed_checks

assert callable(handler.handler)
assert calls == []
assert Path(eval.run_evaluation.__file__).with_name("test-cases.jsonl").is_file()
assert (
    Path(agent.toll_agent.__file__).resolve().parents[1]
    / "agent-sops"
    / "nova-toll-pricing-assistant.sop.md"
).is_file()
assert not any(
    name.startswith(("AWS_", "ACTIONS_", "GITHUB_", "OPENAI_", "CLOUDFLARE_"))
    for name in os.environ
)
"""
    isolated_env = {
        "PATH": os.environ["PATH"],
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TZ": "UTC",
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", smoke, str(stage)],
        env=isolated_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _patch_checkout_sources(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, bytes]:
    migration = "v2/db/migrations/001_create_pricing_schema.sql"
    committed = {
        relative: (fixture_root / relative).read_bytes()
        for relative in (*bundle.SOURCE_FIXED_PATHS, migration)
    }

    def checkout_commit(_root: Path) -> str:
        return COMMIT

    def committed_bytes(_root: Path, relative: str) -> bytes:
        return committed[relative]

    monkeypatch.setattr(bundle, "_checkout_commit", checkout_commit)
    monkeypatch.setattr(bundle, "_committed_bytes", committed_bytes)
    return committed


def _verify_with_checkout(
    archive: Path,
    fixture_root: Path,
    output: Path,
    *,
    expected_commit: str = COMMIT,
) -> None:
    bundle.verify_bundle(
        archive,
        output,
        fixture_root,
        _digest(archive),
        expected_commit,
        {"pricing": "1.3.0", "oracle": "1.14.1"},
        verify_checkout=True,
    )


def test_verify_checkout_accepts_exact_head_sources(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, _ = _bundle(fixture_root, tmp_path)
    _patch_checkout_sources(fixture_root, monkeypatch)

    _verify_with_checkout(archive, fixture_root, tmp_path / "overlay")


def test_verify_checkout_rejects_head_candidate_mismatch(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, _ = _bundle(fixture_root, tmp_path)
    _patch_checkout_sources(fixture_root, monkeypatch)

    def wrong_checkout_commit(_root: Path) -> str:
        return "b" * 40

    monkeypatch.setattr(bundle, "_checkout_commit", wrong_checkout_commit)
    output = tmp_path / "overlay"

    with pytest.raises(bundle.BundleError, match="checked-out commit"):
        _verify_with_checkout(archive, fixture_root, output)
    assert not output.exists()


def test_verify_checkout_rejects_candidate_argument_mismatch(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, _ = _bundle(fixture_root, tmp_path)
    _patch_checkout_sources(fixture_root, monkeypatch)
    output = tmp_path / "overlay"

    with pytest.raises(bundle.BundleError, match="checked-out commit"):
        _verify_with_checkout(archive, fixture_root, output, expected_commit="b" * 40)
    assert not output.exists()


def test_verify_checkout_rejects_archive_source_mismatch(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, release = _bundle(fixture_root, tmp_path)
    committed = _patch_checkout_sources(fixture_root, monkeypatch)
    migration = "v2/db/migrations/001_create_pricing_schema.sql"

    def mutate(entries: list[Entry]) -> list[Entry]:
        changed = b"archive source changed"
        manifest = json.loads(
            next(data for name, data, _mode in entries if name == bundle.MANIFEST_NAME)
        )
        for record in manifest["files"]:
            if record["path"] == migration:
                record["sha256"] = hashlib.sha256(changed).hexdigest()
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        return [
            (
                name,
                manifest_bytes
                if name == bundle.MANIFEST_NAME
                else changed
                if name == migration
                else data,
                mode,
            )
            for name, data, mode in entries
        ]

    _archive(release, archive, mutate=mutate)
    output = tmp_path / "overlay"
    with pytest.raises(bundle.BundleError, match="bundle source differs from HEAD"):
        _verify_with_checkout(archive, fixture_root, output)
    assert committed[migration] == (fixture_root / migration).read_bytes()
    assert not output.exists()


def test_verify_checkout_rejects_worktree_source_mismatch(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, _ = _bundle(fixture_root, tmp_path)
    _patch_checkout_sources(fixture_root, monkeypatch)
    (fixture_root / "v2/db/schema.sql").write_bytes(b"malformed source")
    output = tmp_path / "overlay"

    with pytest.raises(bundle.BundleError, match="checkout source differs"):
        _verify_with_checkout(archive, fixture_root, output)
    assert not output.exists()


def test_verify_checkout_rejects_extra_migration_inventory(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, _ = _bundle(fixture_root, tmp_path)
    _patch_checkout_sources(fixture_root, monkeypatch)
    (fixture_root / "v2/db/migrations/999_untracked.sql").write_bytes(b"extra")
    output = tmp_path / "overlay"

    with pytest.raises(bundle.BundleError, match="migration inventory"):
        _verify_with_checkout(archive, fixture_root, output)
    assert not output.exists()


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
        {"pricing": "1.3.0", "oracle": "1.14.1"},
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
        {"pricing": "1.3.0", "oracle": "1.14.1"},
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
    schema_versions = {"pricing": "1.3.0", "oracle": "1.14.1"}

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

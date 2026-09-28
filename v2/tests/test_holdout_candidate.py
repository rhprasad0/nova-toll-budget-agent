"""Candidate export checks use a synthetic ZIP and mocked GitHub reads only."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from scripts import holdout_candidate as candidate
from tests.test_private_holdout import synthetic_bundle


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    archive = tmp_path / "original.zip"
    context = synthetic_bundle(archive)
    resolver = Mock(return_value=context)
    monkeypatch.setattr(candidate.golden_release, "resolve", resolver)
    monkeypatch.setattr(candidate, "PRIVATE", tmp_path / "ignored")
    monkeypatch.setattr(candidate, "EXCHANGE", tmp_path / "exchange/candidate")

    def download(artifact_id: int, output: Path) -> None:
        assert artifact_id == context["bundle_id"]
        shutil.copyfile(archive, output)

    monkeypatch.setattr(candidate.release, "download", download)
    return {"archive": archive, "context": context, "resolver": resolver}


def test_export_preserves_original_bytes_and_only_three_files(
    tmp_path: Path, source: dict[str, Any]
) -> None:
    output = candidate.export(456, tmp_path / "exchange/candidate")
    assert {p.name for p in output.iterdir()} == {
        "release.zip",
        "context.json",
        "policy.json",
    }
    assert (output / "release.zip").read_bytes() == source["archive"].read_bytes()
    assert (
        candidate.private.context_identity(output / "context.json") == source["context"]
    )
    assert (output / "policy.json").read_bytes() == candidate.gate.POLICY.read_bytes()
    assert source["resolver"].call_count == 2
    assert output.stat().st_mode & 0o777 == 0o700
    assert list(output.parent.iterdir()) == [output]
    with pytest.raises(FileExistsError):
        candidate.export(456, output)


@pytest.mark.parametrize("failure", ["digest", "inventory", "provenance", "policy"])
def test_rejected_export_leaves_no_partial_packet(
    tmp_path: Path, source: dict[str, Any], failure: str
) -> None:
    policy = candidate.gate.POLICY
    if failure == "digest":
        source["context"]["bundle_digest"] = "sha256:" + "0" * 64
    elif failure == "inventory":
        source["resolver"].return_value = synthetic_bundle(
            source["archive"], bad_digest=True
        )
    elif failure == "provenance":
        source["resolver"].side_effect = [
            source["context"],
            {**source["context"], "development_attempt": 2},
        ]
    else:
        policy = tmp_path / "policy.json"
        policy.write_text('{"policy": {}}')
    output = tmp_path / "ignored/candidate"
    with pytest.raises(ValueError):
        candidate.export(456, output, policy)
    assert not output.exists()
    assert not list(output.parent.iterdir())


def test_output_restrictions_and_atomic_no_overwrite(
    tmp_path: Path, source: dict[str, Any]
) -> None:
    for output in (
        tmp_path / "outside",
        tmp_path / "ignored",
        tmp_path / "exchange/other",
    ):
        with pytest.raises(ValueError):
            candidate.export(456, output)
    link = tmp_path / "ignored/link"
    link.parent.mkdir()
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        candidate.export(456, link / "packet")
    assert not source["resolver"].called
    staging, destination = tmp_path / "staging", tmp_path / "existing"
    staging.mkdir()
    destination.mkdir()
    with pytest.raises(FileExistsError):
        candidate.publish(staging, destination)
    assert staging.is_dir() and destination.is_dir()

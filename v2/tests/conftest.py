"""Opt-in fixtures for the retained golden harness, never paid evaluation data."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def golden_test_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from eval import golden
    from tests.golden_support import ROOT

    monkeypatch.setattr(golden, "ROOT", ROOT)


@pytest.fixture
def golden_test_identity(
    golden_test_data: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval import golden

    # Identity tests exercise source/configuration hashing, not corpus approval.
    monkeypatch.setattr(golden, "validate", lambda: None)
    root = tmp_path / "identity-data"
    shutil.copytree(golden.ROOT, root)
    monkeypatch.setattr(golden, "ROOT", root)
    hashes = golden.hashes(root)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": "test-only",
                "tool_description_policy": golden.TOOL_DESCRIPTION_POLICY,
                "case_count": len(golden.load_cases()),
                "hashes": hashes,
                "corpus_sha256": golden.digest(hashes),
            }
        )
    )


@pytest.fixture
def golden_gate_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import golden_gate as gate

    # A temporary synthetic release tree exercises real hash verification without
    # treating historical approvals or regression data as an active corpus.
    root = tmp_path / "release-source"
    for name in gate.CODE:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        source = gate.ROOT / name
        target.write_bytes(source.read_bytes() if source.is_file() else b"{}\n")
    name = "v2/eval/golden/calibration-reference.json"
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()}
    (root / "v2/eval/golden/manifest.json").write_text(
        json.dumps({"hashes": hashes, "corpus_sha256": gate.digest(hashes)})
    )
    monkeypatch.setattr(gate, "ROOT", root)

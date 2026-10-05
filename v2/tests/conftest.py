"""Opt-in fixtures for the retained golden harness, never paid evaluation data."""

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
                "trials_per_case": 3,
                "hashes": hashes,
                "corpus_sha256": golden.digest(hashes),
            }
        )
    )


@pytest.fixture
def archival_reference_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Old reference assertions are offline tests, never an active set."""
    from eval import golden

    monkeypatch.setattr(golden, "ROOT", golden.ARCHIVE)
    monkeypatch.setattr(golden, "validate", golden.validate_archive)

"""Opt-in fixtures for the retained golden harness, never paid evaluation data."""

import json
import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

# GitHub's runners ship these; a bare image does not, and the tests that shell out
# to them fail far from the cause. Gitleaks, Docker and psql are optional: their
# tests skip. Terraform is not checked here, so one test file can run without it.
REQUIRED_TOOLS = ("jq", "xxd", "zip", "unzip")


def pytest_sessionstart(session: pytest.Session) -> None:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        pytest.exit(
            f"Missing required tools: {', '.join(missing)}. See 'Verify the build' "
            "in v2/README.md.",
            returncode=2,
        )


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
def grader_reference_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Grader-logic regressions over five retired cases, never an active set."""
    from eval import golden

    monkeypatch.setattr(
        golden, "ROOT", Path(__file__).parent / "fixtures/golden-grader"
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item) -> Generator[None, Any]:
    """Show private-stage stderr logs when a test fails.

    run_private_stage.sh keeps a stage's stderr out of the workflow log by design,
    so a failing workflow-shell test otherwise reports only reason=unclassified.
    """
    report = (yield).get_result()
    tmp_path = getattr(item, "funcargs", {}).get("tmp_path")
    if report.when != "call" or not report.failed or tmp_path is None:
        return
    for log in sorted(tmp_path.rglob("*.err")):
        try:
            text = log.read_text(errors="replace").strip()
        except OSError:  # a directory or dangling link must not abort the session
            continue
        if text:
            report.sections.append((f"private stage stderr: {log.name}", text[-2000:]))

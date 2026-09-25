"""Contract scheduling and negative-output checks must fail closed."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import database_contracts as contracts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    current, retained = tmp_path / "candidate", tmp_path / "retained"
    for directory in (current, retained):
        directory.mkdir()
        for name in contracts.CONTRACTS:
            (directory / f"{name}_contract.sql").write_text(f"-- {name}\nSELECT 1;\n")
    monkeypatch.setattr(contracts, "CURRENT", current)
    return current, retained


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    commands: list[list[str]] = []

    def run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        assert check
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(contracts.subprocess, "run", run)
    return commands


def test_identical_contracts_run_once_with_full_default_inputs(
    sources: tuple[Path, Path],
    calls: list[list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    current, retained = sources
    contracts.run_contracts(retained, "full")
    assert len(calls) == len(contracts.CONTRACTS)
    for command in calls:
        path = Path(command[command.index("--file") + 1])
        assert path.parent == current
        assert "full_contract=true" in command
        assert "ON_ERROR_STOP=1" in command
        wrapped = path.stem.removesuffix("_contract") in contracts.WRAPPED
        assert ("BEGIN" in command and "ROLLBACK" in command) == wrapped
    output = capsys.readouterr().err
    assert output.count("status=identical") == len(contracts.CONTRACTS)
    assert output.count("status=passed") == len(contracts.CONTRACTS)
    assert "elapsed=" in output


def test_changed_baselines_run_before_candidates_and_new_fixture_has_no_baseline(
    sources: tuple[Path, Path], calls: list[list[str]]
) -> None:
    current, retained = sources
    changed = retained / "oracle_route_contract.sql"
    changed.write_text("SELECT 2;\n")
    (retained / "oracle_fast_contract.sql").unlink()
    contracts.run_contracts(retained, "full")
    paths = [Path(command[command.index("--file") + 1]) for command in calls]
    assert paths[0] == changed
    assert len(paths) == len(contracts.CONTRACTS) + 1
    assert all(path.parent == current for path in paths[1:])


def test_fast_keeps_targeted_contracts_and_disables_exhaustive_blocks(
    sources: tuple[Path, Path], calls: list[list[str]]
) -> None:
    contracts.run_contracts(sources[1], "fast")
    assert len(calls) == len(contracts.CONTRACTS) - 1
    assert all("full_contract=false" in command for command in calls)
    assert not any(
        "oracle_report_contract.sql" in " ".join(command) for command in calls
    )
    assert any("oracle_fast_contract.sql" in " ".join(command) for command in calls)


@pytest.mark.parametrize("identity", [0, 1])
def test_missing_required_input_fails_before_any_sql(
    sources: tuple[Path, Path], calls: list[list[str]], identity: int
) -> None:
    (sources[identity] / "oracle_route_contract.sql").unlink()
    with pytest.raises(FileNotFoundError):
        contracts.run_contracts(sources[1], "full")
    assert calls == []


def test_checker_failure_stops_and_retains_exit_status(
    sources: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoked = 0

    def fail(command: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        nonlocal invoked
        assert check
        invoked += 1
        raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(contracts.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        contracts.run_contracts(sources[1], "full")
    assert raised.value.returncode == 7
    assert invoked == 1
    assert "status=failed exit=7" in capsys.readouterr().err


@pytest.mark.parametrize(
    "content", [b"ordinary output", b"prefix SENTINEL suffix", None]
)
def test_forbidden_output_without_search_tools(
    tmp_path: Path, content: bytes | None
) -> None:
    output = tmp_path / "output with spaces"
    if content is not None:
        output.write_bytes(content)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "v2/scripts/assert_test_output.py"),
            "SENTINEL",
            str(output),
        ],
        env={**os.environ, "PATH": "/missing-search-tools"},
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) == (content == b"ordinary output")
    assert b"SENTINEL" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "arguments", [[], ["HEAD", "--profile", "typo"], ["HEAD", "--unknown", "full"]]
)
def test_invalid_profile_arguments_fail_before_database_access(
    arguments: list[str],
) -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "v2/scripts/run_db_tests.sh"), *arguments],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2


def test_unknown_internal_profile_is_rejected(
    sources: tuple[Path, Path], calls: list[list[str]]
) -> None:
    with pytest.raises(ValueError, match="profile"):
        contracts.run_contracts(sources[1], "typo")
    assert not calls


def test_retained_version_adaptation_preserves_behavior_and_fails_closed() -> None:
    old = b"(SELECT version FROM oracle.schema_version WHERE singleton) <> '1.15.0'"
    new = old.replace(b"1.15.0", b"1.15.1")
    source = (
        b"-- behavioral marker 1.15.0\nIF "
        + old
        + b" THEN RAISE EXCEPTION 'wrong version'; END IF;"
    )
    candidate = b"IF " + new + b" THEN RAISE EXCEPTION 'new behavior'; END IF;"
    assert contracts.retained_version_guard(source, candidate) == source.replace(
        old, new
    )
    for malformed in (b"SELECT 1", old + old):
        with pytest.raises(ValueError, match="exactly one"):
            contracts.retained_version_guard(malformed, candidate)
        with pytest.raises(ValueError, match="exactly one"):
            contracts.retained_version_guard(source, malformed)


def test_malformed_retained_guard_fails_before_sql(
    sources: tuple[Path, Path], calls: list[list[str]]
) -> None:
    (sources[1] / "oracle_restore_contract.sql").write_text("SELECT 2;\n")
    with pytest.raises(ValueError, match="exactly one"):
        contracts.run_contracts(sources[1], "full")
    assert calls == []


def test_retained_report_changes_only_approved_metadata() -> None:
    source = (
        b"(SELECT version FROM oracle.schema_version WHERE singleton) <> '1.15.0'\n"
        b"report.destination->>'label' <> 'Westpark Drive'\n"
        b"report.destination->>'display_name' <> 'old display'\n"
        b"report.destination->>'point_id' <> 'i495:185ND'\n"
        b"RAISE EXCEPTION 'failing behavioral marker';\n"
    )
    candidate = (
        source.replace(b"1.15.0", b"1.15.1")
        .replace(
            b"'Westpark Drive'",
            b"'Westpark Drive (from I-495 northbound or I-95/I-395 northbound)'",
        )
        .replace(b"'old display'", b"'new display'")
    )
    assert (
        contracts.retained_version_guard(source, candidate, report_labels=True)
        == candidate
    )
    for malformed in (
        source.replace(b"display_name", b"other_field"),
        source + b"report.destination->>'label' <> 'extra'",
    ):
        with pytest.raises(ValueError, match="exactly one"):
            contracts.retained_version_guard(malformed, candidate, report_labels=True)

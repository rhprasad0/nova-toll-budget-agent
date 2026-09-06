from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "run_development_migrations", SCRIPTS / "run_development_migrations.py"
)
assert SPEC and SPEC.loader
runner = cast(Any, importlib.util.module_from_spec(SPEC))
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _migration(
    *,
    path: str = "v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql",
    schema: str = "pricing",
    previous: str = "1.0.0",
    target: str = "1.0.1",
    number: int = 2,
) -> Any:
    return runner.Migration(
        path=path,
        schema=schema,
        previous=previous,
        target=target,
        migration_id=Path(path).name,
        number=number,
        source_sha256="a" * 64,
    )


def _empty_candidates(schemas: Any) -> tuple[Any, ...]:
    return ()


def _fixed_commit(*args: str) -> str:
    return "a" * 40


def test_main_rejects_arguments_before_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.sys, "argv", ["runner", "--database", "unsafe"])
    monkeypatch.setattr(runner, "run", lambda: pytest.fail("runner opened a target"))
    assert runner.main() == 2


def test_migration_candidates_are_registered_and_exclude_bootstrap_files() -> None:
    schemas, _ = runner._registry()
    migrations: Any = runner._migration_candidates(schemas)
    assert len(migrations) == 28
    assert migrations[0].number == 2
    assert migrations[-1].number == 30
    assert all("rollback" not in migration.path for migration in migrations)
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", migration.source_sha256)
        for migration in migrations
    )


def test_source_bytes_must_match_committed_head(tmp_path: Path) -> None:
    source = tmp_path / "migration.sql"
    source.write_text("worktree", encoding="utf-8")
    with pytest.raises(runner.MigrationError):
        runner._assert_source_bytes("v2/db/migrations/migration.sql", source, b"HEAD")


def test_migration_tree_rejects_symlinked_parent(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    (root / "v2").symlink_to(real, target_is_directory=True)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", root / "v2/db/migrations")
    try:
        with pytest.raises(runner.MigrationError):
            runner._assert_migration_tree()
    finally:
        monkeypatch.undo()


def test_generated_session_is_one_locked_psql_stream() -> None:
    migration: Any = _migration()
    rendered = Path("/private/002.sql")
    sql = runner._session_sql(
        (migration,),
        {"pricing": "1.3.0", "oracle": "1.14.0"},
        {migration.path: rendered},
        "b" * 40,
        "12345678-1234-4234-8234-123456789abc",
    )
    assert (
        sql.count(
            "pg_advisory_lock(hashtext('tollchat-development-schema-migrations'))"
        )
        == 1
    )
    assert (
        sql.count(
            "pg_advisory_unlock(hashtext('tollchat-development-schema-migrations'))"
        )
        == 1
    )
    assert sql.count("\\ir /private/002.sql") == 1
    assert "SET ROLE pricing_owner_development;" in sql
    assert "SET ROLE oracle_owner_development;" in sql
    assert "\\set ON_ERROR_STOP on" in sql


def test_generated_history_evidence_is_fixed_and_nonsecret() -> None:
    migration: Any = _migration()
    sql = runner._migration_sql(
        migration,
        Path("/private/002.sql"),
        "c" * 40,
        "12345678-1234-4234-8234-123456789abc",
    )
    assert "commit=" + "c" * 40 + ";run=12345678-1234-4234-8234-123456789abc" in sql
    assert "ON CONFLICT (schema_name, migration_id) DO NOTHING" in sql
    assert "UPDATE tollchat_migration.schema_history" not in sql
    assert "PGPASSWORD" not in sql


def test_environment_cannot_redirect_fixed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGDATABASE", "nova_toll")
    monkeypatch.setenv("PGUSER", "postgres")
    monkeypatch.setenv("PGSERVICE", "production")
    monkeypatch.setenv("PGHOSTADDR", "127.0.0.1")
    environment = runner._psql_environment()
    assert environment["PGDATABASE"] == runner.DATABASE
    assert environment["PGUSER"] == runner.USER
    assert "PGSERVICE" not in environment
    assert "PGHOSTADDR" not in environment


def test_result_parser_returns_only_marked_values() -> None:
    run_id = "12345678-1234-4234-8234-123456789abc"
    versions: Any
    applied: Any
    versions, applied = runner._parse_result(
        "noise\n"
        f"TOLLCHAT_APPLIED_{run_id} v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql\n"
        f"TOLLCHAT_RESULT_{run_id} 1.0.0 1.14.0 1.0.1 1.14.0\n",
        run_id,
    )
    assert versions == {
        "pricing_before": "1.0.0",
        "oracle_before": "1.14.0",
        "pricing_after": "1.0.1",
        "oracle_after": "1.14.0",
    }
    assert applied == ["v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql"]


def test_main_success_serializes_allowlisted_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner.sys, "argv", ["runner"])

    def success() -> dict[str, object]:
        return {
            "database": runner.DATABASE,
            "user": runner.USER,
            "before": {"pricing": "1.3.0", "oracle": "1.14.0"},
            "after": {"pricing": "1.3.0", "oracle": "1.14.0"},
            "applied": [],
            "commit": "a" * 40,
            "run_id": "12345678-1234-4234-8234-123456789abc",
            "status": "ok",
        }

    monkeypatch.setattr(runner, "run", success)
    assert runner.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result) == {
        "database",
        "user",
        "before",
        "after",
        "applied",
        "commit",
        "run_id",
        "status",
    }
    assert result["applied"] == []


def test_main_uses_one_psql_boundary_for_noop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner.sys, "argv", ["runner"])
    monkeypatch.setattr(
        runner,
        "_registry",
        lambda: ((), {"pricing": "1.3.0", "oracle": "1.14.0"}),
    )
    monkeypatch.setattr(runner, "_migration_candidates", _empty_candidates)
    monkeypatch.setattr(runner, "_run_capture", _fixed_commit)
    calls: list[list[str]] = []

    def fake_psql(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(args)
        session = cast(str, kwargs["input"])
        match = re.search(r"\\echo TOLLCHAT_RESULT_([0-9a-f-]+)", session)
        assert match is not None
        run_id: str = match.group(1)
        return SimpleNamespace(
            returncode=0,
            stdout=f"TOLLCHAT_RESULT_{run_id} 1.3.0 1.14.0 1.3.0 1.14.0\n",
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_psql)
    assert runner.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert calls == [["psql", "-X", "--no-psqlrc", "-v", "ON_ERROR_STOP=1"]]
    assert result["applied"] == []
    assert (
        result["before"]
        == result["after"]
        == {
            "pricing": "1.3.0",
            "oracle": "1.14.0",
        }
    )


@pytest.mark.parametrize("returncode,stdout", [(1, ""), (0, "psql completed")])
def test_main_rejects_psql_failure_or_missing_marker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    returncode: int,
    stdout: str,
) -> None:
    monkeypatch.setattr(runner.sys, "argv", ["runner"])
    monkeypatch.setattr(
        runner,
        "_registry",
        lambda: ((), {"pricing": "1.3.0", "oracle": "1.14.0"}),
    )
    monkeypatch.setattr(runner, "_migration_candidates", _empty_candidates)
    monkeypatch.setattr(runner, "_run_capture", _fixed_commit)
    calls: list[list[str]] = []

    def fake_psql(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="error")

    monkeypatch.setattr(runner.subprocess, "run", fake_psql)
    assert runner.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "development migrations failed\n"
    assert len(calls) == 1

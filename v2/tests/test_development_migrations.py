from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
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


def test_baseline_manifest_is_shared_and_matches_canonical_bytes() -> None:
    baselines = runner.bootstrap.load_baseline_manifest()
    assert {baseline.schema for baseline in baselines} == {"pricing", "oracle"}
    assert all(
        baseline
        == runner.bootstrap.baseline_for_canonical(
            baseline.schema, baseline.source_path
        )
        for baseline in baselines
    )
    assert {baseline.source_sha256 for baseline in baselines} == {
        hashlib.sha256((runner.ROOT / baseline.source_path).read_bytes()).hexdigest()
        for baseline in baselines
    }


@pytest.mark.parametrize(
    "contents",
    [
        "{}",
        "[{}]",
        '[{"schema":"pricing"}]',
        "not json",
    ],
)
def test_baseline_manifest_rejects_malformed_records(
    tmp_path: Path, contents: str
) -> None:
    path = tmp_path / "migration-baselines.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        runner.bootstrap.load_baseline_manifest(path)


def test_baseline_manifest_rejects_duplicate_generation(tmp_path: Path) -> None:
    baselines = runner.bootstrap.load_baseline_manifest()
    record = {
        "schema": baselines[0].schema,
        "version": baselines[0].version,
        "migration_id": baselines[0].migration_id,
        "source_path": baselines[0].source_path,
        "source_sha256": baselines[0].source_sha256,
        "evidence": baselines[0].evidence,
    }
    path = tmp_path / "migration-baselines.json"
    path.write_text(json.dumps([record, record]), encoding="utf-8")
    with pytest.raises(ValueError):
        runner.bootstrap.load_baseline_manifest(path)


def test_bootstrap_uses_manifest_values_for_history_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str] | None]] = []

    def fake_psql(database: str, **kwargs: Any) -> None:
        calls.append((database, kwargs.get("variables")))

    monkeypatch.setattr(runner.bootstrap, "psql", fake_psql)
    runner.bootstrap.bootstrap_development_objects("nova_toll_development")
    variables = next(
        variables for database, variables in calls if database != "postgres"
    )
    assert variables is not None
    baselines = runner.bootstrap.load_baseline_manifest()
    assert variables["pricing_version"] == next(
        baseline.version for baseline in baselines if baseline.schema == "pricing"
    )
    assert variables["oracle_sha256"] == next(
        baseline.source_sha256 for baseline in baselines if baseline.schema == "oracle"
    )


def test_bootstrap_rejects_unrepresented_canonical_before_psql(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "v2/db/schema.sql"
    source.parent.mkdir(parents=True)
    source.write_text(
        "-- pricing schema version: 1.3.0\n"
        "INSERT INTO pricing.schema_version (version) VALUES ('1.3.0');\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "migration-baselines.json"
    manifest_path.write_text(
        (runner.ROOT / "v2/db/migration-baselines.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner.bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(runner.bootstrap, "BASELINE_MANIFEST_PATH", manifest_path)

    def fail_psql(*args: Any, **kwargs: Any) -> None:
        pytest.fail("psql must not run on manifest mismatch")

    monkeypatch.setattr(runner.bootstrap, "psql", fail_psql)
    with pytest.raises(RuntimeError, match="not represented"):
        runner.bootstrap.bootstrap_development_objects("nova_toll_development")


def test_history_preflight_uses_recognized_baselines_not_current_targets() -> None:
    baselines = runner.bootstrap.load_baseline_manifest()
    sql = runner._history_preflight_sql((), {}, baselines)
    assert "canonical_versions" not in sql
    assert "schema_version <> '1.3.0'" not in sql
    assert "schema_version <> '1.14.0'" not in sql
    assert all(baseline.source_sha256 in sql for baseline in baselines)
    assert "baseline.migration_id = history.migration_id" in sql


def test_old_baseline_can_reach_new_target_while_final_requires_new_target() -> None:
    migration: Any = _migration(previous="1.3.0", target="1.4.0")
    old_baseline = runner.bootstrap.Baseline(
        schema="pricing",
        version="1.3.0",
        migration_id="baseline",
        source_path="v2/db/schema.sql",
        source_sha256="a" * 64,
        evidence=runner.bootstrap.BASELINE_EVIDENCE,
    )
    oracle_baseline = runner.bootstrap.Baseline(
        schema="oracle",
        version="1.14.0",
        migration_id="baseline",
        source_path="v2/db/oracle/schema.sql",
        source_sha256="b" * 64,
        evidence=runner.bootstrap.BASELINE_EVIDENCE,
    )
    preflight = runner._history_preflight_sql(
        (migration,),
        {"pricing": "1.4.0", "oracle": "1.14.0"},
        (old_baseline, oracle_baseline),
    )
    final = runner._final_sql(
        (migration,), {"pricing": "1.4.0", "oracle": "1.14.0"}, "a" * 36
    )
    assert "'1.3.0', '1.4.0'" in preflight
    assert "version FROM pricing.schema_version WHERE singleton) <> '1.4.0'" in final


def test_runner_keeps_psql_cwd_at_repository_root() -> None:
    assert "cwd=ROOT" in inspect.getsource(runner.run)


def test_registry_rejects_dirty_canonical_before_psql(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pricing = tmp_path / "v2/db/schema.sql"
    pricing.parent.mkdir(parents=True)
    pricing.write_bytes(b"dirty canonical")
    oracle = tmp_path / "v2/db/oracle/schema.sql"
    oracle.parent.mkdir(parents=True)
    oracle.write_bytes((runner.ROOT / "v2/db/oracle/schema.sql").read_bytes())
    canonical_bytes = {
        "v2/db/schema.sql": (runner.ROOT / "v2/db/schema.sql").read_bytes(),
        "v2/db/oracle/schema.sql": oracle.read_bytes(),
    }
    registry = tmp_path / "application-schemas.json"
    registry.write_text(
        json.dumps(
            {
                "schemas": [
                    {
                        "name": "oracle",
                        "canonical_sql": "v2/db/oracle/schema.sql",
                        "owned_paths": ["v2/db/oracle/*.sql"],
                    },
                    {
                        "name": "pricing",
                        "canonical_sql": "v2/db/schema.sql",
                        "owned_paths": ["v2/db/*.sql"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "REGISTRY_PATH", registry)

    def committed(relative: str) -> bytes:
        return canonical_bytes[relative]

    monkeypatch.setattr(runner, "_committed_bytes", committed)

    def fail_subprocess(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("psql must not run after a dirty canonical source")

    monkeypatch.setattr(runner.subprocess, "run", fail_subprocess)
    with pytest.raises(runner.MigrationError, match="worktree migration differs"):
        runner._registry()


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
    assert sql.count("\\ir '/private/002.sql'") == 1
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
    assert "ON CONFLICT" not in sql
    assert sql.index("source_sha256, evidence, is_baseline") < sql.index("COMMIT;")
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("fd7a:115c:a1e0:b1a:0:1:ac1f:4a7", "fd7a:115c:a1e0:b1a:0:1:ac1f:4a7"),
        ("127.0.0.1", None),
        ("fd7a:115c:a1e0:b1b::1", None),
        ("not-an-ip", None),
        (None, None),
    ],
)
def test_environment_only_preserves_development_transport(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("PGHOSTADDR", raising=False)
    else:
        monkeypatch.setenv("PGHOSTADDR", value)
    environment = runner._psql_environment()
    assert environment.get("PGHOSTADDR") == expected


def test_production_environment_uses_only_bounded_wrapper_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGHOST", "nova-toll-db.fixture.us-east-1.rds.amazonaws.com")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGHOSTADDR", "172.31.83.200")
    environment = runner._psql_environment(runner.PRODUCTION_PROFILE)
    assert environment["PGHOST"] == "nova-toll-db.fixture.us-east-1.rds.amazonaws.com"
    assert environment["PGHOSTADDR"] == "172.31.83.200"
    assert environment["PGPORT"] == "5432"


@pytest.mark.parametrize(
    ("host", "port", "address"),
    [
        ("attacker.example", "5432", "172.31.83.200"),
        ("nova-toll-db.fixture.us-east-1.rds.amazonaws.com", "15432", "172.31.83.200"),
        ("nova-toll-db.fixture.us-east-1.rds.amazonaws.com", "5432", "127.0.0.1"),
    ],
)
def test_production_environment_rejects_unbounded_transport(
    monkeypatch: pytest.MonkeyPatch, host: str, port: str, address: str
) -> None:
    monkeypatch.setenv("PGHOST", "attacker.example")
    monkeypatch.setenv("PGPORT", "15432")
    monkeypatch.setenv("PGHOSTADDR", address)
    monkeypatch.setenv("PGHOST", host)
    monkeypatch.setenv("PGPORT", port)
    with pytest.raises(runner.MigrationError, match="production transport"):
        runner._psql_environment(runner.PRODUCTION_PROFILE)


def test_psql_include_path_opens_exact_file(tmp_path: Path) -> None:
    """Exercise psql's actual \\ir lexer against a disposable local fixture only."""
    psql = shutil.which("psql")
    container = os.environ.get("POSTGRES_CONTAINER_ID")
    docker = shutil.which("docker")
    if not psql or not docker or not container:
        pytest.skip("requires the explicit disposable PostgreSQL fixture")

    image = subprocess.run(
        [docker, "inspect", "--format", "{{.Config.Image}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    assert image.returncode == 0
    assert image.stdout.strip() == "postgis/postgis:17-3.5"
    running = subprocess.run(
        [docker, "inspect", "--format", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    assert running.returncode == 0
    assert running.stdout.strip() == "true"
    published = subprocess.run(
        [docker, "port", container, "5432/tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert published.returncode == 0
    endpoint = published.stdout.strip().splitlines()[0].rsplit(":", 1)
    assert len(endpoint) == 2
    host, port = endpoint
    assert host in {"127.0.0.1", "localhost", "0.0.0.0", "::1", "[::]"}

    include = tmp_path / "migration with 'single' \"double\" \\backslash.sql"
    include.write_text("SELECT 'exact include opened' AS marker;\n", encoding="utf-8")
    outer = tmp_path / "outer.sql"
    outer.write_text(f"\\ir {runner._psql_path(include)}\n", encoding="utf-8")
    environment = os.environ.copy()
    for key in ("PGHOST", "PGHOSTADDR", "PGPORT", "PGSERVICE", "PGPASSWORD"):
        environment.pop(key, None)
    result = subprocess.run(
        [
            psql,
            "-X",
            "--no-psqlrc",
            "--set",
            "ON_ERROR_STOP=1",
            "--tuples-only",
            "--no-align",
            "--host",
            host,
            "--port",
            port,
            "--username",
            "postgres",
            "--dbname",
            "postgres",
            "--file",
            str(outer),
        ],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "exact include opened"


def test_run_renders_captured_committed_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql"
    source.parent.mkdir(parents=True)
    committed = b"HEAD bytes\n"
    source.write_bytes(committed)
    migration: Any = _migration()
    migration = runner.Migration(
        path=migration.path,
        schema=migration.schema,
        previous=migration.previous,
        target=migration.target,
        migration_id=migration.migration_id,
        number=migration.number,
        source_sha256=hashlib.sha256(committed).hexdigest(),
    )
    rendered_sources: list[Path] = []
    captured_source_bytes: list[bytes] = []
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", source.parent)
    monkeypatch.setattr(
        runner,
        "_registry",
        lambda: ((), {"pricing": "1.3.0", "oracle": "1.14.0"}),
    )

    def fake_candidates(_schemas: Any) -> tuple[Any, ...]:
        return (migration,)

    monkeypatch.setattr(runner, "_migration_candidates", fake_candidates)
    monkeypatch.setattr(runner, "_run_capture", _fixed_commit)

    def fake_committed(_relative: str) -> bytes:
        return committed

    monkeypatch.setattr(runner, "_committed_bytes", fake_committed)

    def fake_render(source_path: Path, destination: Path) -> None:
        rendered_sources.append(source_path)
        captured_source_bytes.append(source_path.read_bytes())
        destination.write_bytes(b"BEGIN;\nSELECT 'DEV';\nCOMMIT;\n")

    monkeypatch.setattr(runner.bootstrap, "render", fake_render)

    def fake_psql(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=0,
            stdout=kwargs["input"].removeprefix("\\echo "),
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_psql)

    # The fake session embeds a stable marker instead of the real SQL stream.
    def fake_session(
        _migrations: Any,
        _versions: Any,
        rendered: dict[str, Path],
        _commit: str,
        run_id: str,
    ) -> str:
        rendered_sources.append(rendered[migration.path])
        return f"\\echo TOLLCHAT_RESULT_{run_id} 1.3.0 1.14.0 1.3.0 1.14.0"

    monkeypatch.setattr(runner, "_session_sql", fake_session)

    result = runner.run()

    assert result["status"] == "ok"
    assert len(rendered_sources) == 2
    assert rendered_sources[0] != source
    assert captured_source_bytes == [committed]


def test_run_rejects_worktree_swap_after_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql"
    source.parent.mkdir(parents=True)
    committed = b"HEAD bytes\n"
    source.write_bytes(committed)
    migration: Any = _migration(
        path="v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql"
    )
    migration = runner.Migration(
        path=migration.path,
        schema=migration.schema,
        previous=migration.previous,
        target=migration.target,
        migration_id=migration.migration_id,
        number=migration.number,
        source_sha256=hashlib.sha256(committed).hexdigest(),
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", source.parent)
    monkeypatch.setattr(
        runner, "_registry", lambda: ((), {"pricing": "1.3.0", "oracle": "1.14.0"})
    )

    def fake_candidates(_schemas: Any) -> tuple[Any, ...]:
        return (migration,)

    monkeypatch.setattr(runner, "_migration_candidates", fake_candidates)
    monkeypatch.setattr(runner, "_run_capture", _fixed_commit)

    def fake_committed(_relative: str) -> bytes:
        return committed

    monkeypatch.setattr(runner, "_committed_bytes", fake_committed)

    def fake_render(source_path: Path, destination: Path) -> None:
        destination.write_bytes(b"BEGIN;\nSELECT 1;\nCOMMIT;\n")
        source.write_bytes(b"swapped\n")

    monkeypatch.setattr(runner.bootstrap, "render", fake_render)

    def fail_psql(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("psql must not start after a source swap")

    monkeypatch.setattr(runner.subprocess, "run", fail_psql)
    with pytest.raises(runner.MigrationError, match="worktree migration differs"):
        runner.run()


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN;\nSELECT 1;\nCOMMIT;\n",
        "begin;\nSELECT 1;\ncommit;\n",
        "-- preamble\n\\set ON_ERROR_STOP on\n\nBEGIN;\nSELECT 1;\nCOMMIT;\n",
        "BEGIN;\nSELECT CASE WHEN true THEN 1 END AS result;\nCOMMIT;\n",
        "BEGIN;\nSELECT CASE WHEN true THEN 1 END, 2;\nCOMMIT;\n",
        "BEGIN;\nSELECT CASE WHEN true THEN 1 END;\nCOMMIT;\n",
        "BEGIN;\nSELECT true\n\\gset\n\\if :result\nSELECT 1;\n\\endif\nCOMMIT;\n",
    ],
)
def test_private_render_removes_only_supported_terminal_commit(
    tmp_path: Path, sql: str
) -> None:
    path = tmp_path / "migration.sql"
    path.write_text(sql, encoding="utf-8")
    runner._remove_terminal_commit(path)
    assert path.read_text(encoding="utf-8") == sql.replace("COMMIT;", "").replace(
        "commit;", ""
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1;\n",
        "SELECT 1;\nBEGIN;\nSELECT 2;\nCOMMIT;\n",
        "BEGIN;\nCOMMIT;\nCOMMIT;\n",
        "BEGIN;\nROLLBACK;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1;\nEND;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1;\nABORT;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1;\nPREPARE TRANSACTION 'x';\nCOMMIT;\n",
        "BEGIN ISOLATION LEVEL SERIALIZABLE;\nSELECT 1;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; COMMIT;\nBEGIN; SELECT 2;\nCOMMIT;\n",
        "begin;\nselect 1; commit;\nbegin; select 2;\ncommit;\n",
        "BEGIN;\nSELECT 1; END TRANSACTION;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; END\nTRANSACTION;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; END\nWORK;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; END AND CHAIN;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; END WORK AND NO CHAIN;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; END\f;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; END\v;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; END\\g\nCOMMIT;\n",
        "BEGIN;\nSELECT true\n\\gset\nEND;\nCOMMIT;\n",
        "BEGIN;\n\\include other.sql\nCOMMIT;\n",
        "BEGIN;\nSELECT 1 AS foo$tag$;\nCOMMIT;\nSELECT 1 AS bar$tag$;\nCOMMIT;\n",
        "BEGIN;\nSELECT E'foo\\''; COMMIT; SELECT E'bar\\''; COMMIT;\n",
        "BEGIN;\n/* outer /* inner */ SELECT 1; */\nCOMMIT;\n",
        "BEGIN;\nSELECT 1; rollback to savepoint migration_savepoint;\nCOMMIT;\n",
        "BEGIN;\nCOMMIT WORK;\n",
        "BEGIN;\nCOMMIT;\nSELECT 1;\n",
    ],
)
def test_private_render_rejects_unsupported_transaction_shape(
    tmp_path: Path, sql: str
) -> None:
    path = tmp_path / "migration.sql"
    path.write_text(sql, encoding="utf-8")
    with pytest.raises(runner.MigrationError, match="transaction shape"):
        runner._remove_terminal_commit(path)


def test_private_render_accepts_every_registered_migration(tmp_path: Path) -> None:
    schemas, _ = runner._registry()
    migrations = runner._migration_candidates(schemas)
    assert migrations
    for migration in migrations:
        destination = tmp_path / Path(migration.path).name
        runner.bootstrap.render(runner.ROOT / migration.path, destination)
        runner._remove_terminal_commit(destination)


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

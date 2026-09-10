from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import adopt_production_baseline as adopt
from scripts import repair_production_postgis_acl as repair
from scripts.adopt_production_baseline import AdminSecret, RdsIdentity


def test_sql_is_fixed_atomic_and_catalog_guarded() -> None:
    sql = repair.repair_sql()
    assert sql.count("BEGIN;") == 1
    assert sql.count("COMMIT;") == 1
    assert "pg_catalog, pg_temp" in sql
    assert "tollchat-production-postgis-acl-repair" in sql
    assert "lock_timeout = '3s'" in sql
    assert "statement_timeout = '10s'" in sql
    assert "REVOKE USAGE ON TYPE oracle.geometry, oracle.geography FROM PUBLIC;" in sql
    assert (
        "GRANT USAGE ON TYPE oracle.geometry, oracle.geography TO oracle_owner;" in sql
    )
    assert "aclexplode(target.typacl)" in sql
    assert "rdsadmin" in sql
    assert "rds_superuser" in sql
    assert "postgis" in sql
    assert "3.5.6" in sql
    assert "REASSIGN OWNED" not in sql
    assert "ALTER TYPE" not in sql
    assert "WITH GRANT OPTION" not in sql
    assert "has_type_privilege" not in sql


def test_main_rejects_arguments_and_approval_before_external_io(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(repair.sys, "argv", ["repair", "--database", "other"])
    monkeypatch.setattr(
        repair.adopt,
        "_rds_identity",
        lambda: pytest.fail("AWS must not run for arguments"),
    )
    assert repair.main() == 2
    assert (
        capsys.readouterr().err
        == "production PostGIS ACL repair argument validation failed\n"
    )

    monkeypatch.setattr(repair.sys, "argv", ["repair"])
    monkeypatch.delenv(repair.APPROVAL_ENV, raising=False)
    assert repair.main() == 1
    assert capsys.readouterr().err == "production PostGIS ACL repair approval failed\n"


def test_run_uses_adoption_fixed_connection_helpers_and_sanitizes_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    identity = RdsIdentity("db.example.rds.amazonaws.com", 5432, "arn")
    calls: list[str] = []
    captured: dict[str, object] = {}

    def rds_identity() -> RdsIdentity:
        calls.append("identity")
        return identity

    def admin_url(endpoint: str) -> tuple[str, int, str]:
        calls.append("url")
        assert endpoint == identity.endpoint
        return endpoint, 5432, "/approved-ca"

    def admin_secret(arn: str) -> AdminSecret:
        calls.append("secret")
        assert arn == identity.secret_arn
        return AdminSecret(adopt.ADMIN_ROLE, "not-for-output")

    def psql_environment(
        value: RdsIdentity, secret: AdminSecret, port: int | None, ca: str
    ) -> dict[str, str]:
        calls.append("environment")
        assert (value, secret.username, port, ca) == (
            identity,
            adopt.ADMIN_ROLE,
            5432,
            "/approved-ca",
        )
        return {"PGPASSWORD": secret.password}

    def completed(*args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0, stdout=f"{repair.SUCCESS_MARKER}\n", stderr=""
        )

    monkeypatch.setenv(repair.APPROVAL_ENV, repair.APPROVAL_TOKEN)
    monkeypatch.setattr(repair.sys, "argv", ["repair"])
    monkeypatch.setattr(repair.adopt, "_rds_identity", rds_identity)
    monkeypatch.setattr(repair.adopt, "_admin_url", admin_url)
    monkeypatch.setattr(repair.adopt, "_admin_secret", admin_secret)
    monkeypatch.setattr(repair.adopt, "_psql_environment", psql_environment)
    monkeypatch.setattr(repair.subprocess, "run", completed)
    assert repair.main() == 0
    assert capsys.readouterr().out == '{"database":"nova_toll","status":"committed"}\n'
    assert calls == ["identity", "url", "secret", "environment"]
    assert captured["env"] == {"PGPASSWORD": "not-for-output"}
    assert repair.SUCCESS_MARKER in str(captured["input"])


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="", stderr="not-for-output"),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout=f"{repair.SUCCESS_MARKER}\n{repair.SUCCESS_MARKER}\n",
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout=repair.SUCCESS_MARKER, stderr="warning"),
    ],
)
def test_unknown_outcome_is_one_sanitized_phase_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: SimpleNamespace,
) -> None:
    def synthetic_url(endpoint: str) -> tuple[str, int, str]:
        return endpoint, 5432, "/ca"

    def synthetic_secret(arn: str) -> AdminSecret:
        return AdminSecret(adopt.ADMIN_ROLE, "not-for-output")

    monkeypatch.setenv(repair.APPROVAL_ENV, repair.APPROVAL_TOKEN)
    monkeypatch.setattr(repair.sys, "argv", ["repair"])
    monkeypatch.setattr(
        repair.adopt,
        "_rds_identity",
        lambda: RdsIdentity("synthetic", 5432, "arn"),
    )
    monkeypatch.setattr(repair.adopt, "_admin_url", synthetic_url)
    monkeypatch.setattr(repair.adopt, "_admin_secret", synthetic_secret)
    monkeypatch.setattr(repair.adopt, "_psql_environment", lambda *args: {})  # pyright: ignore[reportUnknownArgumentType, reportUnknownLambdaType]
    monkeypatch.setattr(repair.subprocess, "run", lambda *args, **kwargs: result)  # pyright: ignore[reportUnknownArgumentType, reportUnknownLambdaType]
    assert repair.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "production PostGIS ACL repair outcome failed\n"
    assert "not-for-output" not in output.err


def test_reuses_adoption_aws_redirect_and_ca_defenses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert repair.adopt._capture is adopt._capture  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(
        repair.adopt.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(cafile="/etc/ssl/certs/ca-certificates.crt"),
    )
    monkeypatch.setenv("AWS_ENDPOINT_URL_RDS", "https://attacker.invalid")
    with pytest.raises(adopt.AdoptionError, match="endpoint or CA override"):
        repair.adopt._capture("rds", "describe-db-instances")  # pyright: ignore[reportPrivateUsage]


def _docker_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for candidate in (
        Path("/var/run/docker.sock"),
        Path("/run/user") / str(os.getuid()) / "docker.sock",
    ):
        if candidate.exists():
            environment["DOCKER_HOST"] = f"unix://{candidate}"
            return environment
    return environment


@pytest.mark.live
def test_disposable_postgis_repair_states_and_rollback(
    request: pytest.FixtureRequest,
) -> None:
    """True-superuser fixture proves SQL atomicity, never RDS authority."""

    docker = shutil.which("docker")
    psql = shutil.which("psql")
    if not docker or not psql:
        pytest.skip("requires local Docker and psql")
    environment = _docker_environment()
    created = subprocess.run(
        [
            docker,
            "run",
            "--detach",
            "--rm",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "--publish",
            "127.0.0.1::5432",
            "postgis/postgis:17-3.5",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=environment,
    )
    assert created.returncode == 0, created.stderr
    container = created.stdout.strip()
    request.addfinalizer(
        lambda: subprocess.run(
            [docker, "stop", container],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=environment,
        )
    )
    published = subprocess.run(
        [docker, "port", container, "5432/tcp"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=environment,
    )
    assert published.returncode == 0, published.stderr
    host, port = published.stdout.strip().splitlines()[0].rsplit(":", 1)
    assert host == "127.0.0.1"

    def psql_run(
        *args: str, input_sql: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                psql,
                "-X",
                "--no-psqlrc",
                "--set",
                "ON_ERROR_STOP=1",
                "--host",
                host,
                "--port",
                port,
                *args,
            ],
            input=input_sql,
            capture_output=True,
            text=True,
            check=False,
        )

    for _ in range(30):
        ready = psql_run(
            "--username", "postgres", "--dbname", "postgres", input_sql="SELECT 1;"
        )
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        pytest.fail("disposable PostGIS fixture did not become ready")

    setup = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "postgres",
        input_sql=(
            "CREATE ROLE rds_superuser NOLOGIN;"
            "CREATE ROLE rdsadmin NOLOGIN SUPERUSER;"
            "CREATE ROLE oracle_owner NOLOGIN;"
            "CREATE ROLE nova_toll_admin LOGIN SUPERUSER INHERIT;"
            "GRANT rds_superuser TO nova_toll_admin WITH INHERIT TRUE, SET TRUE, ADMIN FALSE;"
            "CREATE DATABASE nova_toll OWNER nova_toll_admin;"
        ),
    )
    assert setup.returncode == 0, setup.stderr
    postgis = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=(
            "CREATE SCHEMA oracle AUTHORIZATION oracle_owner;"
            "GRANT CREATE ON SCHEMA oracle TO rdsadmin;"
            "SET ROLE rdsadmin; CREATE EXTENSION postgis WITH SCHEMA oracle; RESET ROLE;"
            "REVOKE ALL ON TYPE oracle.geometry, oracle.geography FROM PUBLIC, oracle_owner;"
            "GRANT USAGE ON TYPE oracle.geometry, oracle.geography TO rdsadmin;"
            "GRANT USAGE ON TYPE oracle.geometry, oracle.geography TO PUBLIC;"
        ),
    )
    assert postgis.returncode == 0, postgis.stderr
    fixture_version = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="SELECT extversion FROM pg_extension WHERE extname = 'postgis';",
    )
    assert fixture_version.returncode == 0, fixture_version.stderr
    # The floating 17-3.5 image is currently 3.5.2. Source tests retain the
    # production-only 3.5.6 guard; this changes only the disposable fixture.
    fixture_sql = repair.repair_sql().replace(
        "extension.extversion = '3.5.6'",
        f"extension.extversion = '{fixture_version.stdout.strip()}'",
    )

    def acl_state() -> str:
        state = psql_run(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            "--tuples-only",
            "--no-align",
            input_sql=(
                "SELECT string_agg(typname || ':' || coalesce(typacl::text,''), ',' ORDER BY typname) "
                "FROM pg_type WHERE typnamespace = 'oracle'::regnamespace AND typacl IS NOT NULL;"
            ),
        )
        assert state.returncode == 0, state.stderr
        return state.stdout.strip()

    drift = acl_state()
    repaired = psql_run(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql,
    )
    assert repaired.returncode == 0, repaired.stderr
    assert repaired.stdout.count(repair.SUCCESS_MARKER) == 1
    fixed = acl_state()
    assert "{=U/" not in fixed
    assert "oracle_owner=U" in fixed
    rerun = psql_run(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql,
    )
    assert rerun.returncode == 0, rerun.stderr
    assert rerun.stdout.count(repair.SUCCESS_MARKER) == 1
    assert acl_state() == fixed

    reset = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=(
            "REVOKE USAGE ON TYPE oracle.geometry, oracle.geography FROM oracle_owner;"
            "GRANT USAGE ON TYPE oracle.geometry, oracle.geography TO PUBLIC;"
        ),
    )
    assert reset.returncode == 0, reset.stderr
    assert acl_state() == drift
    rollback = psql_run(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql.replace("COMMIT;", "SELECT 1 / 0;\nCOMMIT;", 1),
    )
    assert rollback.returncode != 0
    assert repair.SUCCESS_MARKER not in rollback.stdout
    assert acl_state() == drift

    owner_rollback = psql_run(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql.replace(
            "DO $$\nBEGIN\n  IF (SELECT needs_repair FROM _postgis_acl_repair_state) THEN",
            "DO $$\nBEGIN\n  ALTER TYPE oracle.geometry OWNER TO nova_toll_admin;\n"
            "  IF (SELECT needs_repair FROM _postgis_acl_repair_state) THEN",
            1,
        ),
    )
    assert owner_rollback.returncode != 0
    assert repair.SUCCESS_MARKER not in owner_rollback.stdout
    assert acl_state() == drift
    target_owner = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql=(
            "SELECT string_agg(typowner::regrole::text, ',' ORDER BY typname) "
            "FROM pg_type WHERE oid IN ('oracle.geometry'::regtype, 'oracle.geography'::regtype);"
        ),
    )
    assert target_owner.returncode == 0, target_owner.stderr
    assert target_owner.stdout.strip() == "rdsadmin,rdsadmin"

    admin_option = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="GRANT rds_superuser TO nova_toll_admin WITH ADMIN TRUE;",
    )
    assert admin_option.returncode == 0, admin_option.stderr
    admin_rejected = psql_run(
        "--username", "nova_toll_admin", "--dbname", "nova_toll", input_sql=fixture_sql
    )
    assert admin_rejected.returncode != 0
    assert repair.SUCCESS_MARKER not in admin_rejected.stdout
    assert acl_state() == drift
    admin_restore = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="GRANT rds_superuser TO nova_toll_admin WITH ADMIN FALSE;",
    )
    assert admin_restore.returncode == 0, admin_restore.stderr

    extra_membership = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=(
            "CREATE ROLE rds_superuser_grantor NOLOGIN;"
            "GRANT rds_superuser TO rds_superuser_grantor WITH ADMIN TRUE;"
            "SET ROLE rds_superuser_grantor;"
            "GRANT rds_superuser TO nova_toll_admin;"
            "RESET ROLE;"
        ),
    )
    assert extra_membership.returncode == 0, extra_membership.stderr
    extra_rejected = psql_run(
        "--username", "nova_toll_admin", "--dbname", "nova_toll", input_sql=fixture_sql
    )
    assert extra_rejected.returncode != 0
    assert repair.SUCCESS_MARKER not in extra_rejected.stdout
    assert acl_state() == drift
    extra_restore = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=(
            "REVOKE rds_superuser FROM nova_toll_admin GRANTED BY rds_superuser_grantor;"
            "DROP ROLE rds_superuser_grantor;"
        ),
    )
    assert extra_restore.returncode == 0, extra_restore.stderr

    malformed = psql_run(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="GRANT USAGE ON TYPE oracle.geometry TO oracle_owner;",
    )
    assert malformed.returncode == 0, malformed.stderr
    rejected = psql_run(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql,
    )
    assert rejected.returncode != 0
    assert repair.SUCCESS_MARKER not in rejected.stdout

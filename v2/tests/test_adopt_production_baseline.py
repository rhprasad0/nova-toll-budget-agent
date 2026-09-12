from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import select
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn, cast

import pytest

from scripts import adopt_production_baseline as adopt
from scripts import run_development_migrations as runner
from scripts.adopt_production_baseline import (
    AdminSecret,
    Baseline,
    RdsIdentity,
)


def _canonical_baselines() -> tuple[Baseline, ...]:
    return adopt._canonical_baselines()  # pyright: ignore[reportPrivateUsage]


def _capture(*args: str) -> str:
    return adopt._capture(*args)  # pyright: ignore[reportPrivateUsage]


def _rds_identity() -> RdsIdentity:
    return adopt._rds_identity()  # pyright: ignore[reportPrivateUsage]


def _admin_secret(secret_arn: str) -> AdminSecret:
    return adopt._admin_secret(secret_arn)  # pyright: ignore[reportPrivateUsage]


def _admin_url(endpoint: str) -> tuple[str, int | None, str]:
    return adopt._admin_url(endpoint)  # pyright: ignore[reportPrivateUsage]


def _psql_environment(
    identity: RdsIdentity, secret: AdminSecret, port: int | None, rootcert: str
) -> dict[str, str]:
    return adopt._psql_environment(  # pyright: ignore[reportPrivateUsage]
        identity, secret, port, rootcert
    )


_BLOCKED_AWS_OVERRIDE_VARIABLES = (
    "AWS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)


@pytest.fixture(autouse=True)
def _system_ca_bundle(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adopt.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(cafile="/etc/ssl/certs/ca-certificates.crt"),
    )
    for name in tuple(os.environ):
        if name == "AWS_ENDPOINT_URL" or name.startswith("AWS_ENDPOINT_URL_"):
            monkeypatch.delenv(name, raising=False)
    for name in _BLOCKED_AWS_OVERRIDE_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def _synthetic_aws_error_run(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(returncode=1, stdout="", stderr="secret=not-for-output")


def _synthetic_aws_timeout_run(*args: object, **kwargs: object) -> NoReturn:
    raise subprocess.TimeoutExpired("aws", 30)


def _reject_aws_subprocess(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail("AWS subprocess must not start")


def test_fixed_manifest_matches_canonical_sources() -> None:
    baselines = _canonical_baselines()
    assert {baseline.schema for baseline in baselines} == {"pricing", "oracle"}
    assert all(
        baseline.source_sha256
        == hashlib.sha256((adopt.ROOT / baseline.source_path).read_bytes()).hexdigest()
        for baseline in baselines
    )


def test_adoption_selects_only_current_canonical_rows() -> None:
    assert {
        (baseline.schema, baseline.version)
        for baseline in adopt.load_baseline_manifest()
    } == {("pricing", "1.3.0"), ("oracle", "1.14.1")}


@pytest.mark.parametrize(
    "drift", ["manifest-path", "manifest-version", "manifest-hash", "source-bytes"]
)
def test_canonical_drift_is_rejected_once_before_sql(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    drift: str,
) -> None:
    manifest_path = adopt.ROOT / "v2/db/migration-baselines.json"
    source_path = adopt.ROOT / "v2/db/schema.sql"
    manifest = cast(list[dict[str, str]], json.loads(manifest_path.read_text()))
    pricing = next(item for item in manifest if item["schema"] == "pricing")
    if drift == "manifest-path":
        pricing["source_path"] = "arbitrary.sql"
    elif drift == "manifest-version":
        pricing["version"] = "9.0.0"
    elif drift == "manifest-hash":
        pricing["source_sha256"] = "0" * 64
    read_text, read_bytes = Path.read_text, Path.read_bytes

    def synthetic_text(path: Path, **kwargs: object) -> str:
        return json.dumps(manifest) if path == manifest_path else read_text(path)

    def synthetic_bytes(path: Path) -> bytes:
        content = read_bytes(path)
        return (
            content + b"\n"
            if drift == "source-bytes" and path == source_path
            else content
        )

    def synthetic_url(endpoint: str) -> tuple[str, int, str]:
        return endpoint, 5432, "/ca"

    def synthetic_secret(arn: str) -> AdminSecret:
        return AdminSecret(adopt.ADMIN_ROLE, "synthetic-secret")

    monkeypatch.setattr(Path, "read_text", synthetic_text)
    monkeypatch.setattr(Path, "read_bytes", synthetic_bytes)
    monkeypatch.setattr(
        adopt, "_rds_identity", lambda: RdsIdentity("synthetic", 5432, "arn")
    )
    monkeypatch.setattr(adopt, "_admin_url", synthetic_url)
    monkeypatch.setattr(adopt, "_admin_secret", synthetic_secret)
    monkeypatch.setattr(adopt.subprocess, "run", _reject_aws_subprocess)
    monkeypatch.setattr(adopt.sys, "argv", ["adopt"])
    monkeypatch.setenv(adopt.APPROVAL_ENV, adopt.APPROVAL_TOKEN)
    assert adopt.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "production baseline adoption failed\n"


def test_adoption_sql_is_fixed_allowlisted_and_atomic() -> None:
    sql = adopt.adoption_sql()
    assert sql.count("BEGIN;") == 1
    assert sql.count("COMMIT;") == 1
    assert "REASSIGN OWNED" not in sql
    assert "CREATE DATABASE" not in sql
    assert "DROP DATABASE" not in sql
    assert "bootstrap_development_database" not in sql
    assert "schema_migrator_production" in sql
    assert "pricing_owner" in sql
    assert (
        "GRANT rds_iam TO schema_migrator_production WITH INHERIT TRUE, SET TRUE, ADMIN FALSE"
        in sql
    )
    assert (
        "GRANT pricing_owner TO schema_migrator_production WITH INHERIT FALSE, SET TRUE, ADMIN FALSE"
        in sql
    )
    assert (
        "GRANT oracle_owner TO schema_migrator_production WITH INHERIT FALSE, SET TRUE, ADMIN FALSE"
        in sql
    )
    assert "TOLLCHAT_PRODUCTION_BASELINE_ADOPTED" in sql
    assert "deployed canonical schema verified and adopted" in sql
    assert (
        sql.count("RDS PostGIS type ACL is outside the exact adoption exception") == 2
    )
    assert "extension.extversion = '3.5.6'" in sql
    assert "owner.rolname = 'rdsadmin'" in sql
    assert "dependency.deptype = 'e'" in sql
    assert "privilege.grantor" in sql
    assert "('type', 'geometry', 'PUBLIC', 'USAGE', false)" in sql
    assert "('type', 'geography', 'PUBLIC', 'USAGE', false)" in sql
    assert "postgis" in sql.lower()


def test_main_rejects_arguments_and_missing_approval_before_aws(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(adopt.sys, "argv", ["adopt", "--database", "other"])
    assert adopt.main() == 2
    capsys.readouterr()
    monkeypatch.setattr(adopt.sys, "argv", ["adopt"])
    monkeypatch.delenv(adopt.APPROVAL_ENV, raising=False)
    monkeypatch.setattr(
        adopt, "_rds_identity", lambda: pytest.fail("AWS must not run without approval")
    )
    assert adopt.main() == 1
    assert capsys.readouterr().err == "production baseline adoption failed\n"


@pytest.mark.parametrize("failure", ["cli-error", "timeout"])
def test_capture_rejects_cli_failure_without_diagnostics(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "cli-error":
        monkeypatch.setattr(adopt.subprocess, "run", _synthetic_aws_error_run)
    else:
        monkeypatch.setattr(adopt.subprocess, "run", _synthetic_aws_timeout_run)
    with pytest.raises(adopt.AdoptionError, match="identity check failed"):
        _capture("sts", "get-caller-identity")


@pytest.mark.parametrize(
    "name",
    [
        "AWS_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_RDS",
        "AWS_ENDPOINT_URL_STS",
        "AWS_ENDPOINT_URL_SECRETS_MANAGER",
        "AWS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    ],
)
def test_capture_rejects_aws_redirect_environment(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "https://attacker.invalid")
    monkeypatch.setattr(
        adopt.subprocess,
        "run",
        _reject_aws_subprocess,
    )
    with pytest.raises(adopt.AdoptionError, match="endpoint or CA override"):
        _capture("sts", "get-caller-identity")


def test_capture_ignores_configured_endpoint_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def synthetic_run(*args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="expected")

    monkeypatch.setattr(adopt.subprocess, "run", synthetic_run)
    assert _capture("sts", "get-caller-identity") == "expected"
    environment = cast(dict[str, str], captured["env"])
    assert environment["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] == "true"


def test_binary_marker_reader_handles_coalesced_output() -> None:
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'LOCK TABLE\\nLOCK_HELD\\n'); "
            "sys.stdout.buffer.flush(); sys.stdin.buffer.read()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=False,
        bufsize=0,
    )
    try:
        assert child.stdin is not None
        child.stdin.close()
        assert child.stdout is not None
        lines: list[str] = []
        deadline = time.monotonic() + 5
        while len(lines) < 2 and time.monotonic() < deadline:
            ready, _, _ = select.select(
                [child.stdout], [], [], max(0, deadline - time.monotonic())
            )
            if not ready:
                break
            lines.append(child.stdout.readline().decode().strip())
        assert lines == ["LOCK TABLE", "LOCK_HELD"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def _rds_metadata(**overrides: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "DBInstanceIdentifier": adopt.DB_INSTANCE_IDENTIFIER,
        "DBInstanceStatus": "available",
        "PubliclyAccessible": False,
        "Endpoint": {
            "Address": "nova-toll-db.example.rds.amazonaws.com",
            "Port": 5432,
        },
        "MasterUserSecret": {
            "SecretArn": "arn:aws:secretsmanager:us-east-1:920534282028:secret:prod"
        },
    }
    metadata.update(overrides)
    return metadata


def _local_docker_environment() -> dict[str, str]:
    candidates = (
        Path("/var/run/docker.sock"),
        Path("/run/user") / str(os.getuid()) / "docker.sock",
    )
    socket = next(
        (candidate for candidate in candidates if candidate.is_socket()), None
    )
    if socket is None:
        pytest.skip("requires a local Unix Docker socket")
    environment = dict(os.environ)
    for name in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environment.pop(name, None)
    environment["DOCKER_HOST"] = f"unix://{socket}"
    return environment


@pytest.mark.parametrize(
    "responses",
    [
        ["999999999999", "unused"],
        [adopt.ACCOUNT_ID, "not-json"],
        [
            adopt.ACCOUNT_ID,
            json.dumps(_rds_metadata(PubliclyAccessible=True)),
        ],
        [
            adopt.ACCOUNT_ID,
            json.dumps(
                _rds_metadata(Endpoint={"Address": "public.example", "Port": 5432})
            ),
        ],
    ],
    ids=["wrong-account", "malformed-metadata", "public-instance", "wrong-endpoint"],
)
def test_rds_identity_rejects_synthetic_metadata(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
) -> None:
    monkeypatch.setenv(
        adopt.EXPECTED_ENDPOINT_ENV, "nova-toll-db.example.rds.amazonaws.com"
    )
    response_iter = iter(responses)

    def synthetic_capture(*args: str) -> str:
        return next(response_iter)

    monkeypatch.setattr(adopt, "_capture", synthetic_capture)
    with pytest.raises(adopt.AdoptionError):
        _rds_identity()


@pytest.mark.parametrize(
    "secret_case", ["malformed", "wrong-shape", "wrong-user", "empty-password"]
)
def test_admin_secret_rejects_synthetic_secret(
    monkeypatch: pytest.MonkeyPatch, secret_case: str
) -> None:
    secret_string = {
        "malformed": "not-json",
        "wrong-shape": "[]",
        "wrong-user": json.dumps(
            {"username": "other", "password": f"fixture-{secrets.token_hex(8)}"}
        ),
        "empty-password": '{"username":"nova_toll_admin","password":""}',
    }[secret_case]

    def synthetic_capture(*args: str) -> str:
        return secret_string

    monkeypatch.setattr(adopt, "_capture", synthetic_capture)
    with pytest.raises(adopt.AdoptionError):
        _admin_secret("arn:aws:secretsmanager:us-east-1:920534282028:secret:prod")


@pytest.mark.parametrize(
    "failure", ["wrong-account", "malformed-metadata", "malformed-secret", "timeout"]
)
def test_synthetic_aws_failure_is_sanitized_once_before_sql(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    monkeypatch.setenv(adopt.APPROVAL_ENV, adopt.APPROVAL_TOKEN)
    monkeypatch.setattr(adopt.sys, "argv", ["adopt"])
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(args)
        assert args[0] == "aws", "AWS boundary failure must prevent psql"
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 30)
        if "sts" in args:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "999999999999\n"
                    if failure == "wrong-account"
                    else f"{adopt.ACCOUNT_ID}\n"
                ),
            )
        if "describe-db-instances" in args:
            return SimpleNamespace(returncode=0, stdout="not-json\n")
        if "secretsmanager" in args:
            return SimpleNamespace(returncode=0, stdout="{}\n")
        raise AssertionError(f"unexpected synthetic command: {args}")

    if failure == "malformed-secret":

        def synthetic_identity() -> RdsIdentity:
            return RdsIdentity(
                "nova-toll-db.example.rds.amazonaws.com",
                5432,
                "arn:aws:secretsmanager:us-east-1:920534282028:secret:prod",
            )

        def synthetic_admin_url(endpoint: str) -> tuple[str, int | None, str]:
            return endpoint, None, "/tmp/ca"

        monkeypatch.setattr(
            adopt,
            "_rds_identity",
            synthetic_identity,
        )
        monkeypatch.setattr(adopt, "_admin_url", synthetic_admin_url)
    monkeypatch.setattr(adopt.subprocess, "run", fake_run)

    assert adopt.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "production baseline adoption failed\n"
    assert len(calls) == (
        1 if failure in {"wrong-account", "malformed-secret", "timeout"} else 2
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://nova_toll_admin@wrong.rds.amazonaws.com/?sslmode=verify-full&sslrootcert=/tmp/ca",
        "postgresql://nova_toll_admin@prod.rds.amazonaws.com/?sslmode=require&sslrootcert=/tmp/ca",
        "postgresql://nova_toll_admin@prod.rds.amazonaws.com/?sslmode=verify-full",
        "postgresql://nova_toll_admin@prod.rds.amazonaws.com/nova_toll?sslmode=verify-full&sslrootcert=/tmp/ca&connect_timeout=5",
    ],
)
def test_admin_url_rejects_redirects_or_weak_tls(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv(adopt.ADMIN_URL_ENV, url)
    with pytest.raises(adopt.AdoptionError):
        _admin_url("prod.rds.amazonaws.com")


def test_admin_url_rejects_unpinned_ca(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ca_file = tmp_path / "rds-ca.pem"
    ca_file.write_text("not-the-approved-rds-bundle", encoding="utf-8")
    monkeypatch.setenv(
        adopt.ADMIN_URL_ENV,
        f"postgresql://nova_toll_admin@prod.rds.amazonaws.com/nova_toll?"
        f"sslmode=verify-full&sslrootcert={ca_file}",
    )
    with pytest.raises(adopt.AdoptionError, match="not approved"):
        _admin_url("prod.rds.amazonaws.com")


def test_psql_environment_cannot_be_redirected_by_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PGHOST", "attacker.example")
    monkeypatch.setenv("PGSERVICE", "attacker")
    identity = adopt.RdsIdentity("prod.rds.amazonaws.com", 5432, "arn")
    environment = _psql_environment(
        identity,
        adopt.AdminSecret(adopt.ADMIN_ROLE, "not-printed"),
        None,
        str(tmp_path / "ca"),
    )
    assert environment["PGHOST"] == identity.endpoint
    assert environment["PGDATABASE"] == adopt.DATABASE
    assert environment["PGUSER"] == adopt.ADMIN_ROLE
    assert environment["PGPASSWORD"] == "not-printed"
    assert "PGSERVICE" not in environment


def test_run_emits_one_success_record_after_one_psql_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(adopt.APPROVAL_ENV, adopt.APPROVAL_TOKEN)
    identity = adopt.RdsIdentity("prod.rds.amazonaws.com", 5432, "arn")
    secret = adopt.AdminSecret(adopt.ADMIN_ROLE, "secret-not-output")

    def synthetic_identity() -> adopt.RdsIdentity:
        return identity

    def synthetic_admin_url(endpoint: str) -> tuple[str, int | None, str]:
        return endpoint, None, "/ca"

    def synthetic_admin_secret(arn: str) -> adopt.AdminSecret:
        return secret

    def synthetic_adoption_sql() -> str:
        return "BEGIN; COMMIT;"

    monkeypatch.setattr(adopt, "_rds_identity", synthetic_identity)
    monkeypatch.setattr(adopt, "_admin_url", synthetic_admin_url)
    monkeypatch.setattr(adopt, "_admin_secret", synthetic_admin_secret)
    monkeypatch.setattr(adopt, "adoption_sql", synthetic_adoption_sql)
    calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            returncode=0, stdout="TOLLCHAT_PRODUCTION_BASELINE_ADOPTED\n"
        )

    monkeypatch.setattr(adopt.subprocess, "run", fake_run)
    result = adopt.run()
    assert result["status"] == "adopted"
    assert len(calls) == 1
    assert calls[0]["input"] == "BEGIN; COMMIT;"
    environment = cast(dict[str, str], calls[0]["env"])
    assert environment["PGPASSWORD"] == secret.password
    assert environment["PGDATABASE"] == adopt.DATABASE


def test_psql_failure_is_sanitized_and_propagated_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(adopt.APPROVAL_ENV, adopt.APPROVAL_TOKEN)
    identity = adopt.RdsIdentity("prod.rds.amazonaws.com", 5432, "arn")

    def synthetic_identity() -> adopt.RdsIdentity:
        return identity

    def synthetic_admin_url(endpoint: str) -> tuple[str, int | None, str]:
        return endpoint, None, "/ca"

    def synthetic_admin_secret(arn: str) -> adopt.AdminSecret:
        return adopt.AdminSecret(adopt.ADMIN_ROLE, "secret")

    def synthetic_adoption_sql() -> str:
        return "BEGIN; COMMIT;"

    def synthetic_psql_failure(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="password=secret")

    monkeypatch.setattr(adopt, "_rds_identity", synthetic_identity)
    monkeypatch.setattr(adopt, "_admin_url", synthetic_admin_url)
    monkeypatch.setattr(
        adopt,
        "_admin_secret",
        synthetic_admin_secret,
    )
    monkeypatch.setattr(adopt, "adoption_sql", synthetic_adoption_sql)
    monkeypatch.setattr(
        adopt.subprocess,
        "run",
        synthetic_psql_failure,
    )
    monkeypatch.setattr(adopt.sys, "argv", ["adopt"])
    assert adopt.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "production baseline adoption failed\n"
    assert "secret" not in captured.err


def test_no_live_endpoint_or_credential_is_used_by_contract_suite() -> None:
    assert os.environ.get("NOVA_TOLL_PRODUCTION_APPROVAL") != adopt.APPROVAL_TOKEN
    assert subprocess.CompletedProcess([], 0).returncode == 0


@pytest.mark.live
def test_disposable_postgis_adoption_and_rerun_guard(
    request: pytest.FixtureRequest,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run the actual transaction only against a test-owned fresh fixture."""

    docker = shutil.which("docker")
    psql = shutil.which("psql")
    if not docker or not psql:
        pytest.skip("requires local Docker and psql")
    docker_environment = _local_docker_environment()
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
        env=docker_environment,
    )
    assert created.returncode == 0, created.stderr
    container = created.stdout.strip()
    assert container and "\n" not in container

    def cleanup() -> None:
        subprocess.run(
            [docker, "stop", container],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=docker_environment,
        )

    request.addfinalizer(cleanup)
    image = subprocess.run(
        [docker, "inspect", "--format", "{{.Config.Image}}", container],
        capture_output=True,
        text=True,
        check=False,
        env=docker_environment,
    )
    assert image.returncode == 0
    assert image.stdout.strip() == "postgis/postgis:17-3.5"
    running = subprocess.run(
        [docker, "inspect", "--format", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        check=False,
        env=docker_environment,
    )
    assert running.returncode == 0
    assert running.stdout.strip() == "true"
    published = subprocess.run(
        [docker, "port", container, "5432/tcp"],
        capture_output=True,
        text=True,
        check=False,
        env=docker_environment,
    )
    assert published.returncode == 0
    endpoint = published.stdout.strip().splitlines()[0].rsplit(":", 1)
    assert len(endpoint) == 2
    host, port = endpoint
    assert host == "127.0.0.1"

    def run_psql(
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

    for _ in range(60):
        ready = run_psql(
            "--username", "postgres", "--dbname", "postgres", input_sql="SELECT 1;"
        )
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        pytest.fail("disposable PostgreSQL fixture did not become ready")
    clean = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "postgres",
        "--tuples-only",
        "--no-align",
        input_sql=(
            "SELECT (SELECT count(*) FROM pg_database WHERE datname = 'nova_toll'), "
            "(SELECT count(*) FROM pg_roles WHERE rolname IN ("
            "'rds_iam','rds_superuser','nova_toll_admin','pricing_loader_writer',"
            "'pricing_reader','tollchat_agent','pricing_caller','report_publisher',"
            "'oracle_owner','rdsadmin','pricing_owner','schema_migrator_production'));"
        ),
    )
    assert clean.returncode == 0
    assert clean.stdout.strip() == "0|0", (
        "refusing to mutate a non-empty or previously used disposable fixture"
    )
    setup = (
        "CREATE ROLE rds_iam NOLOGIN;"
        "CREATE ROLE rds_superuser NOLOGIN;"
        "CREATE ROLE nova_toll_admin LOGIN CREATEDB CREATEROLE;"
        "CREATE ROLE pricing_loader_writer LOGIN;"
        "CREATE ROLE pricing_reader LOGIN;"
        "CREATE ROLE tollchat_agent LOGIN;"
        "CREATE ROLE pricing_caller LOGIN;"
        "CREATE ROLE report_publisher LOGIN;"
        "CREATE ROLE oracle_owner NOLOGIN;"
        "CREATE ROLE rdsadmin NOLOGIN SUPERUSER;"
        "GRANT rds_superuser TO nova_toll_admin;"
        "GRANT rds_iam TO rds_superuser WITH ADMIN TRUE;"
        "GRANT oracle_owner TO rds_superuser WITH ADMIN TRUE;"
    )
    setup_result = run_psql(
        "--username", "postgres", "--dbname", "postgres", input_sql=setup
    )
    assert setup_result.returncode == 0, setup_result.stderr
    database_result = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "postgres",
        input_sql="CREATE DATABASE nova_toll OWNER nova_toll_admin;",
    )
    assert database_result.returncode == 0, database_result.stderr
    for filename in ("v2/db/schema.sql", "v2/db/oracle/schema.sql", "v2/db/roles.sql"):
        input_sql = None
        if filename == "v2/db/oracle/schema.sql":
            # This test-only superuser fixture creates PostGIS as the observed
            # platform owner. It does not prove RDS authority.
            input_sql = (
                (adopt.ROOT / filename)
                .read_text()
                .replace(
                    "CREATE EXTENSION postgis WITH SCHEMA oracle;",
                    "SET ROLE rdsadmin;\nCREATE EXTENSION postgis WITH SCHEMA oracle;\nRESET ROLE;",
                    1,
                )
                .replace("\\ir data.sql", f"\\i {adopt.ROOT / 'v2/db/oracle/data.sql'}")
            )
        result = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            *([] if input_sql is not None else ["--file", str(adopt.ROOT / filename)]),
            input_sql=input_sql,
        )
        assert result.returncode == 0, result.stderr
    image_version = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="SELECT extversion FROM pg_extension WHERE extname='postgis';",
    )
    assert image_version.returncode == 0, image_version.stderr
    fixture_postgis_version = image_version.stdout.strip()
    assert fixture_postgis_version
    # The disposable image can differ from production. This substitution is
    # fixture-only and must never relax adoption_sql()'s literal 3.5.6 guard.
    fixture_sql = adopt.adoption_sql().replace("'3.5.6'", repr(fixture_postgis_version))
    assert "extension.extversion = '3.5.6'" in adopt.adoption_sql()
    assert f"extension.extversion = {fixture_postgis_version!r}" in fixture_sql
    rds_fixture = (
        "REVOKE ALL PRIVILEGES ON TYPE oracle.geometry FROM PUBLIC, oracle_owner;"
        "REVOKE ALL PRIVILEGES ON TYPE oracle.geography FROM PUBLIC, oracle_owner;"
        "ALTER TYPE oracle.geometry OWNER TO rdsadmin;"
        "ALTER TYPE oracle.geography OWNER TO rdsadmin;"
        "UPDATE pg_type SET typacl = ARRAY['=U/rdsadmin'::aclitem, 'rdsadmin=U/rdsadmin'::aclitem] "
        "WHERE oid IN ('oracle.geometry'::regtype, 'oracle.geography'::regtype);"
    )
    rds_fixture_result = run_psql(
        "--username", "postgres", "--dbname", "nova_toll", input_sql=rds_fixture
    )
    assert rds_fixture_result.returncode == 0, rds_fixture_result.stderr
    prepare = (
        "REVOKE CONNECT ON DATABASE nova_toll FROM PUBLIC;"
        "GRANT TEMPORARY ON DATABASE nova_toll TO PUBLIC;"
        "GRANT CONNECT ON DATABASE nova_toll TO nova_toll_admin, pricing_loader_writer, pricing_reader, tollchat_agent, pricing_caller, report_publisher, oracle_owner;"
        "GRANT USAGE ON SCHEMA pricing TO nova_toll_admin;"
        "GRANT SELECT ON ALL TABLES IN SCHEMA pricing TO nova_toll_admin;"
        "ALTER SCHEMA pricing OWNER TO nova_toll_admin;"
        "ALTER TABLE pricing.schema_version OWNER TO nova_toll_admin;"
        "ALTER TABLE pricing.trip_pricing_i95 OWNER TO nova_toll_admin;"
        "ALTER TABLE pricing.trip_pricing_i66 OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.current_trip_pricing_i95 OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.current_trip_pricing_i66 OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.current_i95_direction OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.i95_modeled_od_proxy OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.modeled_trip_pricing_i95 OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.modeled_current_trip_pricing_i95 OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.i66_pricing_comparisons OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.i95_i495_pricing_comparisons OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.i66_ballpark_samples OWNER TO nova_toll_admin;"
        "ALTER VIEW pricing.i95_i495_ballpark_samples OWNER TO nova_toll_admin;"
        "COMMENT ON DATABASE nova_toll IS 'environment=production';"
    )
    prepare_result = run_psql(
        "--username", "postgres", "--dbname", "nova_toll", input_sql=prepare
    )
    assert prepare_result.returncode == 0, prepare_result.stderr

    # Production reached this definition via migrations. Recreate a canonical
    # constraint later, changing its catalog OID/order but not its meaning.
    constraint = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="SELECT pg_get_constraintdef(oid, true) FROM pg_constraint WHERE conrelid='oracle.toll_route_point'::regclass AND conname='toll_route_point_geographic_context_check';",
    )
    assert constraint.returncode == 0 and constraint.stdout.strip()
    reordered = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=(
            "ALTER TABLE oracle.toll_route_point DROP CONSTRAINT toll_route_point_geographic_context_check;"
            "ALTER TABLE oracle.toll_route_point ADD CONSTRAINT toll_route_point_geographic_context_check "
            + constraint.stdout.strip()
            + ";"
        ),
    )
    assert reordered.returncode == 0, reordered.stderr

    def adoption_state() -> str:
        state = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            "--tuples-only",
            input_sql=(
                "SELECT concat_ws(',', "
                "(SELECT count(*) FROM pg_roles WHERE rolname IN ('pricing_owner','schema_migrator_production')), "
                "COALESCE(to_regnamespace('tollchat_migration')::text, 'none'), "
                "(SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname='pricing'));"
            ),
        )
        assert state.returncode == 0, state.stderr
        return state.stdout.strip()

    def boundary_state() -> str:
        state = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            "--tuples-only",
            "--no-align",
            input_sql=(
                "SELECT concat_ws('|', "
                "(SELECT nspacl::text FROM pg_namespace WHERE nspname='oracle'), "
                "COALESCE((SELECT string_agg(relname || ':' || coalesce(relacl::text,''), ',' ORDER BY c.oid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='oracle'), ''), "
                "COALESCE((SELECT string_agg(proname || ':' || coalesce(proacl::text,''), ',' ORDER BY p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='oracle'), ''), "
                "COALESCE((SELECT string_agg(t.oid || ':' || typname || ':' || typowner || ':' || coalesce(typacl::text,''), ',' ORDER BY t.oid) "
                "FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='oracle'), ''), "
                "COALESCE((SELECT string_agg(extname || ':' || extowner::text, ',' ORDER BY e.oid) "
                "FROM pg_extension e WHERE extname='postgis'), ''), "
                "(SELECT datacl::text FROM pg_database WHERE datname=current_database()), "
                "(SELECT nspacl::text FROM pg_namespace WHERE nspname='pricing'), "
                "COALESCE((SELECT string_agg(format('%s|%s|%s|%s|%s', a.attrelid, a.attnum, x.grantee, x.privilege_type, x.is_grantable), ',' ORDER BY a.attrelid, a.attnum, x.grantee, x.privilege_type) "
                "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(a.attacl) x "
                "WHERE n.nspname IN ('pricing','oracle')), ''), "
                "COALESCE((SELECT string_agg(relname || ':' || coalesce(relacl::text,''), ',' ORDER BY c.oid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='pricing'), '')"
                ");"
            ),
        )
        assert state.returncode == 0, state.stderr
        return state.stdout.strip()

    def stable_boundary_state() -> str:
        state = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            "--tuples-only",
            "--no-align",
            input_sql=(
                "SELECT concat_ws('|', "
                "(SELECT nspacl::text FROM pg_namespace WHERE nspname='oracle'), "
                "COALESCE((SELECT string_agg(relname || ':' || coalesce(relacl::text,''), ',' ORDER BY c.oid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='oracle'), ''), "
                "COALESCE((SELECT string_agg(proname || ':' || coalesce(proacl::text,''), ',' ORDER BY p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='oracle'), ''), "
                "COALESCE((SELECT string_agg(t.oid || ':' || typname || ':' || typowner || ':' || coalesce(typacl::text,''), ',' ORDER BY t.oid) "
                "FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='oracle'), ''), "
                "COALESCE((SELECT string_agg(extname || ':' || extowner::text, ',' ORDER BY e.oid) "
                "FROM pg_extension e WHERE extname='postgis'), ''), "
                "COALESCE((SELECT string_agg(format('%s|%s|%s|%s', c.oid, x.grantee, x.privilege_type, x.is_grantable), ',' ORDER BY c.oid, x.grantee, x.privilege_type) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(c.relacl) x "
                "WHERE n.nspname='pricing' AND x.grantee <> c.relowner), ''), "
                "COALESCE((SELECT string_agg(format('%s|%s|%s', x.grantee, x.privilege_type, x.is_grantable), ',' ORDER BY x.grantee, x.privilege_type) "
                "FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) x "
                "WHERE n.nspname='pricing' AND x.grantee <> n.nspowner), '')"
                ");"
            ),
        )
        assert state.returncode == 0, state.stderr
        return state.stdout.strip()

    def target_acl_state() -> list[str]:
        state = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            "--tuples-only",
            "--no-align",
            input_sql="""
SELECT type.typname, owner.rolname,
       CASE WHEN privilege.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END,
       grantor.rolname, privilege.privilege_type, privilege.is_grantable
FROM pg_type type
JOIN pg_roles owner ON owner.oid = type.typowner
CROSS JOIN LATERAL aclexplode(type.typacl) privilege
LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
LEFT JOIN pg_roles grantor ON grantor.oid = privilege.grantor
WHERE type.typnamespace = 'oracle'::regnamespace
  AND type.typname IN ('geometry', 'geography')
ORDER BY type.typname, privilege.grantee;
""",
        )
        assert state.returncode == 0, state.stderr
        return state.stdout.splitlines()

    before_boundary = boundary_state()
    before_stable_boundary = stable_boundary_state()
    before_target_acl = target_acl_state()
    assert before_target_acl == [
        "geography|rdsadmin|PUBLIC|rdsadmin|USAGE|f",
        "geography|rdsadmin|rdsadmin|rdsadmin|USAGE|f",
        "geometry|rdsadmin|PUBLIC|rdsadmin|USAGE|f",
        "geometry|rdsadmin|rdsadmin|rdsadmin|USAGE|f",
    ]

    def assert_propagated_failure(result: subprocess.CompletedProcess[str]) -> None:
        """Feed real disposable SQL failure through the public entrypoint."""
        calls: list[object] = []

        def sql_result(
            *args: object, **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return result

        def synthetic_url(endpoint: str) -> tuple[str, int, str]:
            return endpoint, 5432, "/ca"

        def synthetic_secret(arn: str) -> AdminSecret:
            return AdminSecret(adopt.ADMIN_ROLE, "synthetic-secret")

        with pytest.MonkeyPatch.context() as patch:
            patch.setenv(adopt.APPROVAL_ENV, adopt.APPROVAL_TOKEN)
            patch.setattr(adopt.sys, "argv", ["adopt"])
            patch.setattr(
                adopt, "_rds_identity", lambda: RdsIdentity("synthetic", 5432, "arn")
            )
            patch.setattr(adopt, "_admin_url", synthetic_url)
            patch.setattr(adopt, "_admin_secret", synthetic_secret)
            patch.setattr(adopt.subprocess, "run", sql_result)
            assert adopt.main() == 1
        assert len(calls) == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert output.err == "production baseline adoption failed\n"

    canonical_view = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="SELECT pg_catalog.pg_get_viewdef('pricing.current_trip_pricing_i95'::regclass, true);",
    )
    assert canonical_view.returncode == 0, canonical_view.stderr
    assert canonical_view.stdout.strip()
    view_drift = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=(
            "CREATE OR REPLACE VIEW pricing.current_trip_pricing_i95 AS "
            "SELECT DISTINCT ON (od_pair_id) od_pair_id, corridor_name, "
            "zone_toll_rate_usd, interval_end_at, calculated_at, link_status "
            "FROM pricing.trip_pricing_i95 WHERE false "
            "ORDER BY od_pair_id, interval_end_at DESC, calculated_at DESC, "
            "start_zone_id, end_zone_id;"
        ),
    )
    assert view_drift.returncode == 0, view_drift.stderr
    drift = run_psql(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql,
    )
    assert drift.returncode != 0
    assert_propagated_failure(drift)
    assert "TOLLCHAT_PRODUCTION_BASELINE_ADOPTED" not in drift.stdout
    assert adoption_state() == "0,none,nova_toll_admin"
    assert boundary_state() == before_boundary
    view_restore = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=(
            "CREATE OR REPLACE VIEW pricing.current_trip_pricing_i95 AS "
            + canonical_view.stdout.strip()
            + ";"
        ),
    )
    assert view_restore.returncode == 0, view_restore.stderr

    def reject_target_drift(
        setup_sql: str,
        restore_sql: str,
        sql: str = fixture_sql,
        expected_error: str = "RDS PostGIS type ACL is outside the exact adoption exception",
    ) -> None:
        changed = run_psql(
            "--username", "postgres", "--dbname", "nova_toll", input_sql=setup_sql
        )
        assert changed.returncode == 0, changed.stderr
        drift = run_psql(
            "--username", "nova_toll_admin", "--dbname", "nova_toll", input_sql=sql
        )
        assert drift.returncode != 0
        assert expected_error in drift.stderr
        assert_propagated_failure(drift)
        assert "TOLLCHAT_PRODUCTION_BASELINE_ADOPTED" not in drift.stdout
        assert adoption_state() == "0,none,nova_toll_admin"
        restored = run_psql(
            "--username", "postgres", "--dbname", "nova_toll", input_sql=restore_sql
        )
        assert restored.returncode == 0, restored.stderr
        assert boundary_state() == before_boundary
        assert target_acl_state() == before_target_acl

    exact_geometry_acl = (
        "UPDATE pg_type SET typacl = ARRAY['=U/rdsadmin'::aclitem, 'rdsadmin=U/rdsadmin'::aclitem] "
        "WHERE oid = 'oracle.geometry'::regtype;"
    )
    reject_target_drift(
        "ALTER TYPE oracle.geometry OWNER TO postgres;",
        "ALTER TYPE oracle.geometry OWNER TO rdsadmin;" + exact_geometry_acl,
    )
    # These synthetic catalog drifts are test-fixture-only. PostgreSQL's
    # supported ownership and GRANT commands cannot represent them otherwise.
    reject_target_drift(
        "UPDATE pg_extension SET extowner = 'postgres'::regrole WHERE extname = 'postgis';",
        "UPDATE pg_extension SET extowner = 'rdsadmin'::regrole WHERE extname = 'postgis';",
    )
    reject_target_drift(
        "UPDATE pg_extension SET extnamespace = 'public'::regnamespace WHERE extname = 'postgis';",
        "UPDATE pg_extension SET extnamespace = 'oracle'::regnamespace WHERE extname = 'postgis';",
        expected_error="extensions or foreign access are outside the canonical contract",
    )
    reject_target_drift(
        "UPDATE pg_extension SET extversion = '0.0.0' WHERE extname = 'postgis';",
        f"UPDATE pg_extension SET extversion = {fixture_postgis_version!r} WHERE extname = 'postgis';",
        expected_error="extensions or foreign access are outside the canonical contract",
    )
    reject_target_drift(
        "ALTER EXTENSION postgis DROP TYPE oracle.geometry;",
        "ALTER EXTENSION postgis ADD TYPE oracle.geometry;",
    )
    reject_target_drift(
        "INSERT INTO pg_depend SELECT classid, objid, objsubid, refclassid, refobjid, refobjsubid, deptype "
        "FROM pg_depend WHERE classid = 'pg_type'::regclass AND objid = 'oracle.geometry'::regtype "
        "AND refclassid = 'pg_extension'::regclass;",
        "DELETE FROM pg_depend WHERE ctid IN (SELECT ctid FROM pg_depend WHERE classid = 'pg_type'::regclass "
        "AND objid = 'oracle.geometry'::regtype AND refclassid = 'pg_extension'::regclass LIMIT 1);",
    )
    reject_target_drift(
        "UPDATE pg_depend SET refobjid = (SELECT oid FROM pg_extension WHERE extname = 'plpgsql') WHERE classid = 'pg_type'::regclass "
        "AND objid = 'oracle.geometry'::regtype AND refclassid = 'pg_extension'::regclass;",
        "UPDATE pg_depend SET refobjid = (SELECT oid FROM pg_extension WHERE extname = 'postgis') WHERE classid = 'pg_type'::regclass "
        "AND objid = 'oracle.geometry'::regtype AND refclassid = 'pg_extension'::regclass;",
    )
    reject_target_drift(
        "UPDATE pg_depend SET deptype = 'n' WHERE classid = 'pg_type'::regclass "
        "AND objid = 'oracle.geometry'::regtype AND refclassid = 'pg_extension'::regclass;",
        "UPDATE pg_depend SET deptype = 'e' WHERE classid = 'pg_type'::regclass "
        "AND objid = 'oracle.geometry'::regtype AND refclassid = 'pg_extension'::regclass;",
    )
    reject_target_drift(
        "SET ROLE rdsadmin; REVOKE USAGE ON TYPE oracle.geometry FROM PUBLIC; RESET ROLE;",
        exact_geometry_acl,
    )
    reject_target_drift(
        "SET ROLE rdsadmin; REVOKE USAGE ON TYPE oracle.geometry FROM PUBLIC; "
        "GRANT USAGE ON TYPE oracle.geometry TO pricing_reader; RESET ROLE;",
        exact_geometry_acl,
    )
    reject_target_drift(
        "SET ROLE rdsadmin; GRANT USAGE ON TYPE oracle.geometry TO pricing_reader WITH GRANT OPTION; RESET ROLE;",
        exact_geometry_acl,
    )
    reject_target_drift(
        "UPDATE pg_type SET typacl = ARRAY['rdsadmin=U/rdsadmin'::aclitem, '=U/postgres'::aclitem] "
        "WHERE oid = 'oracle.geometry'::regtype;",
        exact_geometry_acl,
    )
    reject_target_drift(
        "SET ROLE rdsadmin; GRANT USAGE ON TYPE oracle.geometry TO pricing_reader; RESET ROLE;",
        exact_geometry_acl,
    )
    reject_target_drift(
        "SELECT 1;",
        "SELECT 1;",
        fixture_sql.replace(repr(fixture_postgis_version), "'0.0.0'", 1),
    )

    # Preflight ACL drift must fail before creating any adoption principal.
    for drift_setup_sql, drift_restore_sql in (
        (
            "GRANT SELECT ON pricing.schema_version TO PUBLIC;",
            "REVOKE SELECT ON pricing.schema_version FROM PUBLIC;",
        ),
        (
            "GRANT SELECT ON pricing.schema_version TO pricing_reader WITH GRANT OPTION;",
            "REVOKE GRANT OPTION FOR SELECT ON pricing.schema_version FROM pricing_reader;",
        ),
        (
            "GRANT SELECT ON oracle.schema_version TO pricing_reader;",
            "REVOKE SELECT ON oracle.schema_version FROM pricing_reader;",
        ),
        (
            "GRANT SELECT (point_id) ON oracle.toll_route_point TO pricing_caller;",
            "REVOKE SELECT (point_id) ON oracle.toll_route_point FROM pricing_caller;",
        ),
        (
            "GRANT UPDATE (version) ON pricing.schema_version TO pricing_reader WITH GRANT OPTION;",
            "REVOKE UPDATE (version) ON pricing.schema_version FROM pricing_reader;",
        ),
        (
            "GRANT SELECT (point_id) ON oracle.toll_route_point TO PUBLIC;",
            "REVOKE SELECT (point_id) ON oracle.toll_route_point FROM PUBLIC;",
        ),
        (
            "GRANT USAGE ON SCHEMA oracle TO PUBLIC;",
            "REVOKE USAGE ON SCHEMA oracle FROM PUBLIC;",
        ),
        (
            "GRANT CREATE ON DATABASE nova_toll TO pricing_reader;",
            "REVOKE CREATE ON DATABASE nova_toll FROM pricing_reader;",
        ),
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA pricing GRANT SELECT ON TABLES TO pricing_reader;",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA pricing REVOKE SELECT ON TABLES FROM pricing_reader;",
        ),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE oracle_owner GRANT EXECUTE ON FUNCTIONS TO pricing_reader;",
            "ALTER DEFAULT PRIVILEGES FOR ROLE oracle_owner REVOKE EXECUTE ON FUNCTIONS FROM pricing_reader;",
        ),
        (
            "ALTER ROLE pricing_reader NOINHERIT;",
            "ALTER ROLE pricing_reader INHERIT;",
        ),
        (
            "GRANT oracle_owner TO rds_iam WITH INHERIT TRUE, SET TRUE, ADMIN FALSE;",
            "REVOKE oracle_owner FROM rds_iam;",
        ),
        (
            "CREATE EXTENSION dblink WITH SCHEMA oracle;",
            "DROP EXTENSION dblink;",
        ),
        (
            "CREATE FOREIGN DATA WRAPPER unapproved; CREATE SERVER unapproved FOREIGN DATA WRAPPER unapproved; CREATE USER MAPPING FOR pricing_reader SERVER unapproved;",
            "DROP USER MAPPING FOR pricing_reader SERVER unapproved; DROP SERVER unapproved; DROP FOREIGN DATA WRAPPER unapproved;",
        ),
        (
            "GRANT EXECUTE ON FUNCTION oracle.postgis_full_version() TO PUBLIC;",
            "REVOKE EXECUTE ON FUNCTION oracle.postgis_full_version() FROM PUBLIC;",
        ),
        (
            "SET ROLE rdsadmin; GRANT USAGE ON TYPE oracle.geography TO pricing_reader; RESET ROLE;",
            "SET ROLE rdsadmin; REVOKE USAGE ON TYPE oracle.geography FROM pricing_reader; RESET ROLE;",
        ),
        (
            "GRANT SELECT ON oracle.spatial_ref_sys TO PUBLIC;",
            "REVOKE SELECT ON oracle.spatial_ref_sys FROM PUBLIC;",
        ),
        (
            "ALTER TABLE pricing.schema_version OWNER TO oracle_owner;",
            "ALTER TABLE pricing.schema_version OWNER TO nova_toll_admin;",
        ),
        (
            "CREATE INDEX unapproved_extra_idx ON pricing.trip_pricing_i95 (corridor_id);",
            "DROP INDEX pricing.unapproved_extra_idx;",
        ),
        (
            "CREATE TRIGGER adoption_drift_trigger BEFORE UPDATE ON pricing.trip_pricing_i95 "
            "FOR EACH ROW EXECUTE FUNCTION pg_catalog.suppress_redundant_updates_trigger(); "
            "ALTER TABLE pricing.trip_pricing_i95 DISABLE TRIGGER adoption_drift_trigger;",
            "DROP TRIGGER adoption_drift_trigger ON pricing.trip_pricing_i95;",
        ),
        (
            "ALTER TABLE oracle.toll_connection DISABLE TRIGGER ALL;",
            "ALTER TABLE oracle.toll_connection ENABLE TRIGGER ALL;",
        ),
        (
            "CREATE POLICY adoption_drift_policy ON pricing.trip_pricing_i95 USING (true);",
            "DROP POLICY adoption_drift_policy ON pricing.trip_pricing_i95;",
        ),
        (
            "ALTER TABLE pricing.trip_pricing_i95 ENABLE ROW LEVEL SECURITY;",
            "ALTER TABLE pricing.trip_pricing_i95 DISABLE ROW LEVEL SECURITY;",
        ),
        (
            "ALTER TABLE pricing.trip_pricing_i95 FORCE ROW LEVEL SECURITY;",
            "ALTER TABLE pricing.trip_pricing_i95 NO FORCE ROW LEVEL SECURITY;",
        ),
        (
            "CREATE RULE adoption_drift_rule AS ON UPDATE TO pricing.trip_pricing_i95 DO NOTHING;",
            "DROP RULE adoption_drift_rule ON pricing.trip_pricing_i95;",
        ),
        (
            "CREATE FUNCTION pricing.unapproved() RETURNS integer LANGUAGE sql AS 'SELECT 1';",
            "DROP FUNCTION pricing.unapproved();",
        ),
        (
            "CREATE TYPE pricing.unapproved AS ENUM ('extra');",
            "DROP TYPE pricing.unapproved;",
        ),
        (
            "CREATE TYPE oracle.unapproved AS ENUM ('extra');",
            "DROP TYPE oracle.unapproved;",
        ),
        (
            "UPDATE pricing.schema_version SET version = '1.3.1';",
            "UPDATE pricing.schema_version SET version = '1.3.0';",
        ),
    ):
        drift_setup = run_psql(
            "--username", "postgres", "--dbname", "nova_toll", input_sql=drift_setup_sql
        )
        assert drift_setup.returncode == 0, drift_setup.stderr
        drift_boundary = boundary_state()
        drift = run_psql(
            "--username",
            "nova_toll_admin",
            "--dbname",
            "nova_toll",
            input_sql=fixture_sql,
        )
        assert drift.returncode != 0
        assert_propagated_failure(drift)
        assert "TOLLCHAT_PRODUCTION_BASELINE_ADOPTED" not in drift.stdout
        assert adoption_state() == "0,none,nova_toll_admin"
        assert boundary_state() == drift_boundary
        drift_restore = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            input_sql=drift_restore_sql,
        )
        assert drift_restore.returncode == 0, drift_restore.stderr
        assert boundary_state() == before_boundary

    # Force an error after role creation, ownership transfer, and history
    # insertion.  The transaction must remove every adoption-side effect.
    rollback_sql = fixture_sql.replace(
        "REVOKE SELECT ON tollchat_migration.schema_history FROM nova_toll_admin;",
        "SELECT 1 / 0;\n"
        "REVOKE SELECT ON tollchat_migration.schema_history FROM nova_toll_admin;",
        1,
    )
    rollback = run_psql(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=rollback_sql,
    )
    assert rollback.returncode != 0
    assert_propagated_failure(rollback)
    assert "TOLLCHAT_PRODUCTION_BASELINE_ADOPTED" not in rollback.stdout
    assert adoption_state() == "0,none,nova_toll_admin"
    assert boundary_state() == before_boundary

    # Inject namespace drift after snapshotting. Each postcheck must reject it
    # and roll back adoption as well as the injected change.
    for postcondition_drift, expected_error in (
        (
            "GRANT USAGE ON SCHEMA oracle TO PUBLIC;",
            "Oracle schema ownership or ACL boundary changed",
        ),
        (
            "ALTER SCHEMA oracle OWNER TO nova_toll_admin;",
            "Oracle schema ownership or ACL boundary changed",
        ),
        (
            "ALTER SCHEMA oracle RENAME TO displaced_oracle; CREATE SCHEMA oracle;",
            "Oracle schema ownership or ACL boundary changed",
        ),
        (
            "GRANT EXECUTE ON FUNCTION oracle.validate_pricing_route(text, text) TO schema_migrator_production;",
            "production migrator has a direct application ACL",
        ),
        (
            "GRANT SELECT (point_id) ON oracle.toll_route_point TO pricing_caller;",
            "application column ACL is outside the empty canonical contract",
        ),
        (
            "CREATE TYPE oracle.unapproved AS ENUM ('extra');",
            "Oracle/PostGIS ownership or ACL boundary changed",
        ),
        (
            "GRANT USAGE ON TYPE pricing.schema_version TO schema_migrator_production;",
            "production migrator has a direct application ACL",
        ),
        (
            "GRANT SELECT (schema_name) ON tollchat_migration.schema_history TO schema_migrator_production;",
            "production migrator has a direct application ACL",
        ),
        (
            "GRANT oracle_owner TO rds_iam WITH INHERIT TRUE, SET TRUE, ADMIN FALSE;",
            "rds_iam must not inherit any other role",
        ),
        (
            "CREATE EXTENSION dblink WITH SCHEMA oracle;",
            "extensions or foreign access are outside the canonical contract",
        ),
        (
            "GRANT EXECUTE ON FUNCTION oracle.postgis_full_version() TO PUBLIC;",
            "PostGIS ACL is outside the canonical allowlist",
        ),
        (
            "CREATE TRIGGER adoption_drift_trigger BEFORE UPDATE ON pricing.trip_pricing_i95 "
            "FOR EACH ROW EXECUTE FUNCTION pg_catalog.suppress_redundant_updates_trigger(); "
            "ALTER TABLE pricing.trip_pricing_i95 DISABLE TRIGGER adoption_drift_trigger;",
            "application trigger, policy, row-security, or rewrite-rule inventory is outside the canonical contract",
        ),
        (
            "ALTER TABLE oracle.toll_connection DISABLE TRIGGER ALL;",
            "application trigger, policy, row-security, or rewrite-rule inventory is outside the canonical contract",
        ),
        (
            "CREATE POLICY adoption_drift_policy ON pricing.trip_pricing_i95 USING (true);",
            "application trigger, policy, row-security, or rewrite-rule inventory is outside the canonical contract",
        ),
        (
            "ALTER TABLE pricing.trip_pricing_i95 ENABLE ROW LEVEL SECURITY;",
            "application trigger, policy, row-security, or rewrite-rule inventory is outside the canonical contract",
        ),
        (
            "ALTER TABLE pricing.trip_pricing_i95 FORCE ROW LEVEL SECURITY;",
            "application trigger, policy, row-security, or rewrite-rule inventory is outside the canonical contract",
        ),
        (
            "CREATE RULE adoption_drift_rule AS ON UPDATE TO pricing.trip_pricing_i95 DO NOTHING;",
            "application trigger, policy, row-security, or rewrite-rule inventory is outside the canonical contract",
        ),
    ):
        sql = fixture_sql.replace(
            "DO $$\nDECLARE\n  expected_count integer;",
            postcondition_drift + "\nDO $$\nDECLARE\n  expected_count integer;",
            1,
        )
        rejected = run_psql(
            "--username", "postgres", "--dbname", "nova_toll", input_sql=sql
        )
        assert rejected.returncode != 0
        assert_propagated_failure(rejected)
        assert expected_error in rejected.stderr
        assert "TOLLCHAT_PRODUCTION_BASELINE_ADOPTED" not in rejected.stdout
        assert adoption_state() == "0,none,nova_toll_admin"
        assert boundary_state() == before_boundary

    # The adoption transaction holds relation locks through its final
    # postcondition. A second session's privileged Oracle RLS DDL must time
    # out rather than commit between the final guard and COMMIT.
    lock_statement = next(
        line for line in fixture_sql.splitlines() if line.startswith("LOCK TABLE ")
    )
    adoption_script = fixture_sql
    prefix, suffix = adoption_script.split(lock_statement, 1)
    held_prefix = prefix + lock_statement + "\nSELECT 'LOCK_HELD';\n"
    held_suffix = suffix.replace("COMMIT;", "SELECT 1 / 0;\nCOMMIT;", 1)
    holder = subprocess.Popen(
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
            "nova_toll_admin",
            "--dbname",
            "nova_toll",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
    )
    try:
        assert holder.stdin is not None
        holder.stdin.write(held_prefix.encode())
        holder.stdin.flush()
        assert holder.stdout is not None
        marker_seen = False
        output_lines: list[str] = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            ready, _, _ = select.select(
                [holder.stdout], [], [], max(0, deadline - time.monotonic())
            )
            if not ready:
                break
            line = holder.stdout.readline().decode().strip()
            output_lines.append(line)
            if line == "LOCK_HELD":
                marker_seen = True
                break
        assert marker_seen, f"adoption lock holder output: {output_lines!r}"
        held_lock = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            "--tuples-only",
            "--no-align",
            input_sql=(
                "SELECT mode, granted FROM pg_locks "
                "WHERE relation='oracle.toll_connection'::regclass;"
            ),
        )
        assert held_lock.returncode == 0, held_lock.stderr
        assert "AccessExclusiveLock|t" in held_lock.stdout
        blocked = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            input_sql=(
                "BEGIN; SET LOCAL lock_timeout='1s'; "
                "CREATE POLICY lock_probe ON oracle.toll_connection USING (true);"
            ),
        )
        assert blocked.returncode != 0
        assert "lock timeout" in blocked.stderr
        assert holder.stdin is not None
        holder.stdin.write(held_suffix.encode())
        holder.stdin.close()
        holder_returncode = holder.wait(timeout=15)
        holder_stdout = holder.stdout.read().decode()
        assert holder.stderr is not None
        holder_stderr = holder.stderr.read().decode()
        assert holder_returncode != 0
        assert_propagated_failure(
            subprocess.CompletedProcess(
                [psql], holder_returncode, holder_stdout, holder_stderr
            )
        )
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)
    assert adoption_state() == "0,none,nova_toll_admin"
    assert boundary_state() == before_boundary

    adoption = run_psql(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql,
    )
    assert adoption.returncode == 0, adoption.stderr
    assert adoption.stdout.count("TOLLCHAT_PRODUCTION_BASELINE_ADOPTED") == 1
    state = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        input_sql=(
            "SELECT concat_ws(',', "
            "(SELECT count(*) FROM tollchat_migration.schema_history), "
            "(SELECT count(*) FROM pg_roles WHERE rolname IN ('pricing_owner','schema_migrator_production')), "
            "(SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname='pricing'));"
        ),
    )
    assert state.returncode == 0
    assert state.stdout.strip() == "2,2,pricing_owner"
    assert stable_boundary_state() == before_stable_boundary

    adopted_114 = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql=f"""
DROP FUNCTION oracle.get_agent_report_routes();
UPDATE oracle.toll_route_point
SET place_name = NULL, region = NULL, country_code = NULL
WHERE network_id = 'i66';
UPDATE oracle.schema_version SET version = '1.14.0' WHERE singleton;
UPDATE tollchat_migration.schema_history
SET schema_version = '1.14.0',
    source_sha256 = {runner.ADOPTED_ORACLE_114_SHA256!r}
WHERE schema_name = 'oracle' AND is_baseline;
""",
    )
    assert adopted_114.returncode == 0, adopted_114.stderr

    # The image's patch release is fixture-only. Production keeps the literal
    # 3.5.6 exception supplied by the shared adoption guard.
    fixture_guard = adopt.production_rds_postgis_type_guard().replace(
        "'3.5.6'", repr(fixture_postgis_version)
    )
    monkeypatch.setattr(
        runner.adoption, "production_rds_postgis_type_guard", lambda: fixture_guard
    )
    monkeypatch.setattr(
        runner,
        "PRODUCTION_PROFILE",
        replace(
            runner.PRODUCTION_PROFILE,
            transport_network=runner.ipaddress.ip_network("127.0.0.0/8"),
        ),
    )
    monkeypatch.setattr(
        runner, "PRODUCTION_RDS_ENDPOINT", re.compile(r"^127[.]0[.]0[.]1$")
    )
    monkeypatch.setattr(runner, "PRODUCTION_RDS_PORT", port)
    monkeypatch.setenv("PGHOST", host)
    monkeypatch.setenv("PGPORT", port)
    monkeypatch.setenv("PGHOSTADDR", host)
    upgrade = runner.run_production()
    assert upgrade["before"] == {"pricing": "1.3.0", "oracle": "1.14.0"}
    assert upgrade["after"] == {"pricing": "1.3.0", "oracle": "1.15.0"}
    assert upgrade["applied"] == [
        "v2/db/migrations/031_upgrade_oracle_1_14_0_to_1_15_0.sql"
    ]
    adopted_history = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="""
SELECT schema_version, source_sha256, evidence
FROM tollchat_migration.schema_history
WHERE schema_name = 'oracle' AND is_baseline;
SELECT count(*) FROM tollchat_migration.schema_history
WHERE migration_id = '031_upgrade_oracle_1_14_0_to_1_15_0.sql';
""",
    )
    assert adopted_history.returncode == 0, adopted_history.stderr
    assert adopted_history.stdout.splitlines() == [
        "|".join(
            (
                "1.14.0",
                runner.ADOPTED_ORACLE_114_SHA256,
                adopt.ADOPTION_EVIDENCE,
            )
        ),
        "1",
    ]
    no_op = runner.run_production()
    assert (
        no_op["before"]
        == no_op["after"]
        == {
            "pricing": "1.3.0",
            "oracle": "1.14.1",
        }
    )
    assert no_op["applied"] == []

    schemas, _ = runner._registry(runner.PRODUCTION_PROFILE)  # pyright: ignore[reportPrivateUsage]
    oracle_031 = next(
        migration
        for migration in runner._migration_candidates(schemas)  # pyright: ignore[reportPrivateUsage]
        if migration.path == "v2/db/migrations/031_upgrade_oracle_1_14_0_to_1_15_0.sql"
    )

    def production_migration(sql: str, migration_id: str, *, succeeds: bool) -> None:
        rendered = tmp_path / f"{migration_id}.sql"
        rendered.write_text(sql, encoding="utf-8")
        runner._remove_terminal_commit(rendered)  # pyright: ignore[reportPrivateUsage]
        migration = runner.Migration(
            path=f"v2/db/migrations/{migration_id}.sql",
            schema="pricing",
            previous="1.3.0",
            target="1.3.1",
            migration_id=f"{migration_id}.sql",
            number=31,
            source_sha256="a" * 64,
        )
        session = runner._session_sql(  # pyright: ignore[reportPrivateUsage]
            (migration,),
            {"pricing": "1.3.1", "oracle": "1.14.1"},
            {migration.path: rendered},
            "a" * 40,
            "12345678-1234-4234-8234-123456789abc",
            runner._production_baselines(),  # pyright: ignore[reportPrivateUsage]
            runner.PRODUCTION_PROFILE,
        )
        result = subprocess.run(
            [psql, "-X", "--no-psqlrc", "-v", "ON_ERROR_STOP=1"],
            input=session,
            capture_output=True,
            text=True,
            env=runner._psql_environment(runner.PRODUCTION_PROFILE),  # pyright: ignore[reportPrivateUsage]
            check=False,
        )
        assert (result.returncode == 0) is succeeds, result.stderr
        if succeeds:
            assert result.stdout.count("TOLLCHAT_RESULT_") == 1
            return
        assert "TOLLCHAT_RESULT_" not in result.stdout
        unchanged = run_psql(
            "--username",
            "postgres",
            "--dbname",
            "nova_toll",
            "--tuples-only",
            "--no-align",
            input_sql=(
                "SELECT version FROM pricing.schema_version WHERE singleton; "
                f"SELECT count(*) FROM tollchat_migration.schema_history WHERE migration_id={migration.migration_id!r}; "
                "SELECT pg_try_advisory_lock(hashtext('tollchat-production-schema-migrations'));"
            ),
        )
        assert unchanged.returncode == 0, unchanged.stderr
        assert unchanged.stdout.splitlines() == ["1.3.0", "0", "t"]

    production_migration(
        "BEGIN;\nUPDATE pricing.schema_version SET version = '1.3.1' WHERE singleton;\nSELECT 1 / 0;\nCOMMIT;\n",
        "031_production_sql_failure",
        succeeds=False,
    )
    trigger = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="""
CREATE FUNCTION public.fail_production_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'injected history failure'; END $$;
CREATE TRIGGER fail_production_history BEFORE INSERT ON tollchat_migration.schema_history
FOR EACH ROW EXECUTE FUNCTION public.fail_production_history();
""",
    )
    assert trigger.returncode == 0, trigger.stderr
    production_migration(
        "BEGIN;\nUPDATE pricing.schema_version SET version = '1.3.1' WHERE singleton;\nCOMMIT;\n",
        "032_production_history_failure",
        succeeds=False,
    )
    removed = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="DROP TRIGGER fail_production_history ON tollchat_migration.schema_history; DROP FUNCTION public.fail_production_history();",
    )
    assert removed.returncode == 0, removed.stderr
    postflight = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="""
CREATE FUNCTION public.add_production_postgis_acl() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $function$
BEGIN GRANT USAGE ON TYPE oracle.geometry TO schema_migrator_production; END $function$;
""",
    )
    assert postflight.returncode == 0, postflight.stderr
    production_migration(
        "BEGIN;\nSELECT public.add_production_postgis_acl();\nUPDATE pricing.schema_version SET version = '1.3.1' WHERE singleton;\nCOMMIT;\n",
        "033_production_postflight_guard",
        succeeds=False,
    )
    cleanup_postflight = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="DROP FUNCTION public.add_production_postgis_acl();",
    )
    assert cleanup_postflight.returncode == 0, cleanup_postflight.stderr
    production_migration(
        "BEGIN;\nUPDATE pricing.schema_version SET version = '1.3.1' WHERE singleton;\nCOMMIT;\n",
        "034_production_success",
        succeeds=True,
    )
    production_migration(
        "BEGIN;\nUPDATE pricing.schema_version SET version = '1.3.1' WHERE singleton;\nCOMMIT;\n",
        "034_production_success",
        succeeds=True,
    )
    contiguous = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="""
SELECT version FROM pricing.schema_version WHERE singleton;
SELECT count(*) FROM tollchat_migration.schema_history WHERE migration_id = '034_production_success.sql';
UPDATE pricing.schema_version SET version = '1.3.0' WHERE singleton;
DELETE FROM tollchat_migration.schema_history WHERE migration_id = '034_production_success.sql';
""",
    )
    assert contiguous.returncode == 0, contiguous.stderr
    assert contiguous.stdout.splitlines()[:2] == ["1.3.1", "1"]
    wrong_owner = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="ALTER TABLE tollchat_migration.schema_history OWNER TO postgres;",
    )
    assert wrong_owner.returncode == 0, wrong_owner.stderr
    with pytest.raises(runner.MigrationError):
        runner.run_production()
    restored_owner = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="ALTER TABLE tollchat_migration.schema_history OWNER TO pricing_owner;",
    )
    assert restored_owner.returncode == 0, restored_owner.stderr
    public_history = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="GRANT SELECT ON tollchat_migration.schema_history TO PUBLIC;",
    )
    assert public_history.returncode == 0, public_history.stderr
    with pytest.raises(runner.MigrationError):
        runner.run_production()
    private_history = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        input_sql="REVOKE ALL ON tollchat_migration.schema_history FROM PUBLIC;",
    )
    assert private_history.returncode == 0, private_history.stderr
    assert runner.run_production()["status"] == "ok"
    history = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="""
SELECT schema_name, schema_version, migration_id, source_path, source_sha256,
       evidence, is_baseline, recorded_at IS NOT NULL
FROM tollchat_migration.schema_history
WHERE is_baseline ORDER BY schema_name;
""",
    )
    assert history.returncode == 0, history.stderr
    assert history.stdout.splitlines() == [
        "|".join(
            (
                baseline.schema,
                baseline.version,
                baseline.migration_id,
                baseline.source_path,
                baseline.source_sha256,
                adopt.ADOPTION_EVIDENCE,
                "t",
                "t",
            )
        )
        for baseline in sorted(
            (
                next(
                    baseline
                    for baseline in _canonical_baselines()
                    if baseline.schema == "pricing"
                ),
                runner.bootstrap.Baseline(
                    schema="oracle",
                    version="1.14.0",
                    migration_id="baseline",
                    source_path="v2/db/oracle/schema.sql",
                    source_sha256=runner.ADOPTED_ORACLE_114_SHA256,
                    evidence=adopt.ADOPTION_EVIDENCE,
                ),
            ),
            key=lambda baseline: baseline.schema,
        )
    ]
    memberships = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="""
SELECT granted.rolname, membership.inherit_option, membership.set_option, membership.admin_option
FROM pg_auth_members membership JOIN pg_roles granted ON granted.oid = membership.roleid
WHERE membership.member = 'schema_migrator_production'::regrole ORDER BY granted.rolname;
SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname IN ('pricing_owner', 'schema_migrator_production') ORDER BY rolname;
""",
    )
    assert memberships.returncode == 0, memberships.stderr
    assert memberships.stdout.splitlines() == [
        "oracle_owner|f|t|f",
        "pricing_owner|f|t|f",
        "rds_iam|t|t|f",
        "pricing_owner|f|f|f|f|f|f|f",
        "schema_migrator_production|t|f|f|f|f|f|f",
    ]
    direct_grants = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        "--no-align",
        input_sql="""
WITH application_acls AS (
  SELECT nspacl AS acl FROM pg_namespace WHERE nspname IN ('pricing', 'oracle', 'tollchat_migration')
  UNION ALL SELECT relacl FROM pg_class WHERE relnamespace IN ('pricing'::regnamespace, 'oracle'::regnamespace, 'tollchat_migration'::regnamespace)
  UNION ALL SELECT proacl FROM pg_proc WHERE pronamespace IN ('pricing'::regnamespace, 'oracle'::regnamespace, 'tollchat_migration'::regnamespace)
  UNION ALL SELECT typacl FROM pg_type WHERE typnamespace IN ('pricing'::regnamespace, 'oracle'::regnamespace, 'tollchat_migration'::regnamespace)
  UNION ALL SELECT attacl FROM pg_attribute JOIN pg_class ON pg_class.oid = attrelid WHERE relnamespace IN ('pricing'::regnamespace, 'oracle'::regnamespace, 'tollchat_migration'::regnamespace)
)
SELECT count(*) FROM application_acls CROSS JOIN LATERAL aclexplode(acl) grant_
WHERE grantee = 'schema_migrator_production'::regrole;
SELECT has_database_privilege('schema_migrator_production', current_database(), 'CONNECT'),
       has_database_privilege('schema_migrator_production', current_database(), 'CREATE'),
       has_database_privilege('pricing_owner', current_database(), 'CREATE');
""",
    )
    assert direct_grants.returncode == 0, direct_grants.stderr
    assert direct_grants.stdout.splitlines() == ["0", "t|f|f"]
    rerun = run_psql(
        "--username",
        "nova_toll_admin",
        "--dbname",
        "nova_toll",
        input_sql=fixture_sql,
    )
    assert rerun.returncode != 0
    assert_propagated_failure(rerun)
    unchanged = run_psql(
        "--username",
        "postgres",
        "--dbname",
        "nova_toll",
        "--tuples-only",
        input_sql="SELECT count(*) FROM tollchat_migration.schema_history;",
    )
    assert unchanged.returncode == 0
    assert unchanged.stdout.strip() == "3"

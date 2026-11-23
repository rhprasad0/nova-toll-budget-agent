import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from factory.host import dispatcher

POSTGRES = "postgis/postgis:17-3.5"
RDS_HOST = "db.example.us-east-1.rds.amazonaws.com"
UPSTREAM = f"""
printf 'local all all trust\\nhostssl all all all trust\\n' > /tmp/hba
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN={RDS_HOST} \\
  -addext subjectAltName=DNS:{RDS_HOST} -keyout /tmp/key -out /tmp/cert 2>/dev/null
chown postgres /tmp/hba /tmp/key /tmp/cert && chmod 600 /tmp/key
exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/cert \\
  -c ssl_key_file=/tmp/key -c hba_file=/tmp/hba
"""
ROLES = [
    "CREATE ROLE factory_sandbox LOGIN",
    "CREATE DATABASE factory_sandbox OWNER factory_sandbox",
    "CREATE ROLE phoenix_factory LOGIN",
    "CREATE DATABASE phoenix OWNER phoenix_factory",
    "CREATE ROLE factory_sandbox_reader LOGIN",
]
RELAYS = {
    "relay": ("factory_sandbox", "6432", "15"),
    "relay-read": ("factory_sandbox_reader", "6433", "5"),
}


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check
    )


def until(probe: list[str], container: str) -> None:
    for _ in range(60):
        if docker(*probe, check=False).returncode == 0:
            return
        state = docker("inspect", "--format", "{{.State.Running}}", container)
        assert state.stdout.strip() == "true", docker("logs", container).stderr
        time.sleep(1)
    raise AssertionError(f"never ready: {probe}")


@pytest.fixture
def relay(tmp_path: Path) -> Iterator[str]:
    name = f"relay-{uuid.uuid4().hex[:8]}"
    try:
        docker("network", "create", name)
        docker("run", "--detach", "--name", f"{name}-rds", "--network", name,
               "--network-alias", RDS_HOST, "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
               "--entrypoint", "sh", POSTGRES, "-c", UPSTREAM)  # fmt: skip
        until(
            [
                "exec",
                f"{name}-rds",
                "psql",
                "-h",
                "localhost",
                "-U",
                "postgres",
                "-c",
                "select 1",
            ],
            f"{name}-rds",
        )
        docker("exec", f"{name}-rds", "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
               *(arg for sql in ROLES for arg in ("-c", sql)))  # fmt: skip
        (tmp_path / "rds").mkdir()
        docker("cp", f"{name}-rds:/tmp/cert", str(tmp_path / "rds/rds-ca.pem"))
        (tmp_path / "rds/rds-ca.pem").chmod(0o644)
        docker(
            "build",
            "--quiet",
            "--tag",
            "factory-relay:test",
            str(dispatcher.FACTORY / "relay"),
        )
        for alias, (user, port, connections) in RELAYS.items():
            container = f"{name}-{alias}"
            docker("create", "--name", container, "--network", name, "--network-alias", alias,
                   "--env", f"FACTORY_RDS_HOST={RDS_HOST}", "--env", f"RELAY_USER={user}",
                   "--env", f"RELAY_PORT={port}", "--env", f"RELAY_CONNECTIONS={connections}",
                   "--env", "AWS_ACCESS_KEY_ID=AKIAEXAMPLEEXAMPLE", "--env", "AWS_SECRET_ACCESS_KEY=example",
                   "factory-relay:test")  # fmt: skip
            docker("cp", str(tmp_path / "rds"), f"{container}:/rds")
            docker("start", container)
            until(client(name, user, "factory_sandbox", "select 1", alias), container)
        yield name
    finally:
        docker(
            "rm",
            "--force",
            *(f"{name}-{alias}" for alias in RELAYS),
            f"{name}-rds",
            check=False,
        )
        docker("network", "rm", name, check=False)


def client(
    name: str, user: str, database: str, sql: str, alias: str = "relay"
) -> list[str]:
    return ["run", "--rm", "--network", name, "--env", "PGCONNECT_TIMEOUT=5", POSTGRES,
            "psql", "-X", "-At", "-h", alias, "-p", RELAYS[alias][1], "-U", user,
            "-d", database, "-c", sql]  # fmt: skip


def test_relay_pins_the_sandbox_login_over_verified_tls(relay: str) -> None:
    pinned = docker(*client(relay, "factory_sandbox", "factory_sandbox",
        "select current_user, current_database(), ssl from pg_stat_ssl where pid = pg_backend_pid()"))  # fmt: skip
    assert pinned.stdout.strip() == "factory_sandbox|factory_sandbox|t"
    phoenix_user = docker(
        *client(relay, "phoenix_factory", "phoenix", "select 1"), check=False
    )
    assert (
        phoenix_user.returncode != 0 and "authentication failed" in phoenix_user.stderr
    )
    for database in ("phoenix", "postgres"):
        other = docker(
            *client(relay, "factory_sandbox", database, "select 1"), check=False
        )
        assert other.returncode != 0 and "no such database" in other.stderr
    assert "X-Amz-Signature" not in docker("logs", f"{relay}-relay").stderr


def test_relay_queues_clients_beyond_its_upstream_cap(relay: str) -> None:
    script = (
        "for i in $(seq 20); do psql -X -h relay -p 6432 -U factory_sandbox -d factory_sandbox"
        " -Atc 'select pg_sleep(3)' >/dev/null & done; wait; echo done"
    )
    burst = subprocess.Popen(
        ["docker", "run", "--rm", "--network", relay, "--entrypoint", "bash", POSTGRES, "-c", script],
        stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    time.sleep(2)
    upstream = docker("exec", f"{relay}-rds", "psql", "-U", "postgres", "-At", "-c",
        "select count(*) from pg_stat_activity where usename = 'factory_sandbox'")  # fmt: skip
    assert 0 < int(upstream.stdout) <= 15
    assert burst.communicate(timeout=60)[0].strip() == "done"


def test_read_relay_serves_only_the_reader(relay: str) -> None:
    reader = docker(
        *client(
            relay,
            "factory_sandbox_reader",
            "factory_sandbox",
            "select current_user",
            "relay-read",
        )
    )
    assert reader.stdout.strip() == "factory_sandbox_reader"
    writer = docker(
        *client(relay, "factory_sandbox", "factory_sandbox", "select 1", "relay-read"),
        check=False,
    )
    assert writer.returncode != 0 and "authentication failed" in writer.stderr

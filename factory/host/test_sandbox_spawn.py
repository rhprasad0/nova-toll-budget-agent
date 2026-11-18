import json
import os
import subprocess
from pathlib import Path

from factory.host import dispatcher

SPAWN = dispatcher.FACTORY / "sandbox/spawn.sh"


def test_spawn_runs_one_session_with_its_databases_and_only_work_credentials(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    calls = tmp_path / "calls"
    (fake / "docker").write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\0" "$@" >> {calls}\nprintf "\\n" >> {calls}\n'
    )
    (fake / "docker").chmod(0o755)
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "DOCKER_HOST": "unix:///run/user/1002/docker.sock",
        "FACTORY_PROXY": "http://10.249.0.1:18081",
        "ANTHROPIC_SESSION_ID": "sesn_1",
        "ANTHROPIC_WORK_ID": "work_1",
        "ANTHROPIC_ENVIRONMENT_ID": "env_1",
        "ANTHROPIC_ENVIRONMENT_KEY": "environment-key",
        "ANTHROPIC_API_KEY": "must-not-reach-the-sandbox",
    }
    subprocess.run(
        [str(SPAWN)],
        input=json.dumps({"id": "work_1", "secret": "work-secret"}),
        env=env,
        text=True,
        check=True,
    )
    runs = [
        line.split("\0")[:-1]
        for line in calls.read_text().split("\n")
        if line.startswith("run\0")
    ]
    clone, postgres, retained, sandbox = runs
    assert "clone" in clone and f"{tmp_path}/sessions/sesn_1:/workspace" in clone
    assert postgres[postgres.index("--network-alias") + 1] == "postgres"
    assert retained[retained.index("--network-alias") + 1] == "postgres-retained"
    assert sandbox[-1] == "factory-sandbox:latest"
    assert sandbox[sandbox.index("--cap-drop") + 1] == "ALL"
    assert "/run/user/1002/docker.sock:/var/run/docker.sock" in sandbox
    assert "/var/run/docker.sock:/var/run/docker.sock" not in sandbox
    assert "--privileged" not in sandbox
    passed = {sandbox[i + 1] for i, arg in enumerate(sandbox) if arg == "--env"}
    assert "ANTHROPIC_WORK_SECRET" in passed
    assert "ANTHROPIC_API_KEY" not in " ".join(passed)
    assert "HTTPS_PROXY=http://10.249.0.1:18081" in passed
    assert "DISPOSABLE_DOCKER_NETWORK=container:work-work_1" in passed
    assert "POSTGRES_CONTAINER_ID=work-work_1-postgres" in passed
    assert any(
        line.startswith("rm\0--force\0work-work_1-postgres")
        for line in calls.read_text().split("\n")
    )

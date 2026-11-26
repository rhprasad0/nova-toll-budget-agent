import json
import os
import subprocess
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]

SPAWN = FACTORY / "sandbox/spawn.sh"
CLEAN = FACTORY / "sandbox/clean.sh"


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
        "FACTORY_SANDBOX_DATABASE_URL": "postgresql://factory_sandbox@10.249.0.1:15432/factory_sandbox",
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
    assert "AWS_EMULATOR_URL=http://aws:5000" not in sandbox
    assert "CHAOS_LAB_DATABASE_URL" not in sandbox
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
    assert "GH_TOKEN=replaced-by-the-proxy" in passed
    assert "FACTORY_SANDBOX_DATABASE_URL" in passed
    assert {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION=us-east-1",
    } <= passed
    assert "DISPOSABLE_DOCKER_NETWORK=container:work-work_1" in passed
    assert "POSTGRES_CONTAINER_ID=work-work_1-postgres" in passed
    removals = [
        line.split("\0")[:-1]
        for line in calls.read_text().split("\n")
        if line.startswith("rm\0")
    ]
    assert len(removals) == 2
    assert all(
        {"--volumes", "work-work_1", "work-work_1-postgres", "work-work_1-retained"}
        <= set(r)
        for r in removals
    )


def test_spawn_clones_the_configured_repository(tmp_path: Path) -> None:
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
        "FACTORY_REPO": "rhprasad0/chaos-lab",
        "ANTHROPIC_SESSION_ID": "sesn_1",
        "ANTHROPIC_WORK_ID": "Work_AB1",
    }
    subprocess.run(
        [str(SPAWN)], input=json.dumps({"secret": "s"}), env=env, text=True, check=True
    )
    lines = [line.split("\0")[:-1] for line in calls.read_text().split("\n") if line]
    clone = next(line for line in lines if line[0] == "run" and "clone" in line)
    assert clone[-2:] == [
        "https://github.com/rhprasad0/chaos-lab",
        "/workspace/chaos-lab",
    ]
    assert not [line for line in lines if line[0] == "compose"]
    runs = [line for line in lines if line[0] == "run"]
    emulator = next(line for line in runs if "work-Work_AB1-aws" in line)
    assert emulator[emulator.index("--network-alias") + 1] == "aws"
    assert emulator[-1].startswith("motoserver/moto:") and "@sha256:" in emulator[-1]
    passed = {runs[-1][i + 1] for i, arg in enumerate(runs[-1]) if arg == "--env"}
    assert {
        "CHAOS_LAB_DATABASE_URL",
        "AWS_EMULATOR_URL=http://aws:5000",
        "NO_PROXY=localhost,127.0.0.1,aws",
    } <= passed
    assert not [arg for arg in passed if arg.startswith("AWS_ENDPOINT_URL")]


def test_clean_removes_only_containers_older_than_any_session_and_old_workdirs(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    calls = tmp_path / "calls"
    (fake / "docker").write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\0" "$@" >> {calls}\nprintf "\\n" >> {calls}\n'
        'case "$1 ${4:-}" in\n'
        '  "ps "*) printf "gone\\nleaked\\nlive\\n" ;;\n'
        '  "inspect gone") exit 1 ;;\n'
        '  "inspect leaked") date -u -d "13 hours ago" +%Y-%m-%dT%H:%M:%S.000000000Z ;;\n'
        '  "inspect live") date -u -d "4 hours ago" +%Y-%m-%dT%H:%M:%S.000000000Z ;;\n'
        "esac\n"
    )
    (fake / "docker").chmod(0o755)
    env = {"PATH": f"{fake}:{os.environ['PATH']}", "HOME": str(tmp_path)}
    subprocess.run([str(CLEAN)], env=env, check=True)
    lines = [line.split("\0")[:-1] for line in calls.read_text().splitlines()]
    removed = [line for line in lines if line[0] == "rm"]
    assert removed == [["rm", "--force", "--volumes", "leaked"]]
    assert ["volume", "prune", "--all", "--force"] in lines
    assert ["image", "prune", "--force", "--filter", "until=12h"] in lines
    (find,) = [line for line in lines if line[0] == "run"]
    assert f"{tmp_path}/sessions:/sessions" in find
    assert find[-7:] == ["-mtime", "+1", "-exec", "rm", "-rf", "{}", "+"]

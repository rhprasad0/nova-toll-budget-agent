"""Profile selection is conservative, including unusual filenames and deletions."""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from scripts.select_db_test_profile import select_profile


@pytest.mark.parametrize(
    ("profile", "retained_exit", "candidate_exit"),
    [("full", 0, 0), ("full", 7, 0), ("full", 0, 9), ("full", 7, 9), ("fast", 7, 0)],
)
def test_ci_workers_use_separate_targets_and_fail_if_either_fails(
    tmp_path: Path, profile: str, retained_exit: int, candidate_exit: int
) -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    ).read_text()
    step = workflow.split("- name: Validate disposable database contracts\n", 1)[1]
    script = textwrap.dedent(step.split("run: |\n", 1)[1].split("        env:\n", 1)[0])
    runner = tmp_path / "v2/scripts/run_db_tests.sh"
    runner.parent.mkdir(parents=True)
    runner.write_text(
        "#!/usr/bin/env bash\nset -eu\n"
        'echo "worker=$DB_CONTRACT_IDENTITY"\n'
        'if [[ "$DB_CONTRACT_IDENTITY" == retained ]]; then\n'
        '  test "$PGPORT:$POSTGRES_CONTAINER_ID" = 5433:retained\n'
        '  exit "$RETAINED_EXIT"\n'
        "fi\n"
        'test "$PGPORT:$POSTGRES_CONTAINER_ID" = 5432:candidate\n'
        'exit "$CANDIDATE_EXIT"\n'
    )
    runner.chmod(0o755)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "DATABASE_PROFILE": profile,
            "SCHEMA_BASE_REF": "base",
            "DB_CONTRACT_IDENTITY": "all",
            "PGPORT": "5432",
            "POSTGRES_CONTAINER_ID": "candidate",
            "RETAINED_POSTGRES_CONTAINER_ID": "retained",
            "RETAINED_EXIT": str(retained_exit),
            "CANDIDATE_EXIT": str(candidate_exit),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert bool(result.returncode) == bool(
        candidate_exit or (profile == "full" and retained_exit)
    ), result.stderr
    workers = sorted(
        line for line in result.stdout.splitlines() if line.startswith("worker=")
    )
    assert workers == (
        ["worker=candidate", "worker=retained"] if profile == "full" else ["worker=all"]
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "commit", "--allow-empty", "-qm", "base")
    return tmp_path


@pytest.mark.parametrize("event", ["pull_request", "merge_group"])
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README.md", "fast"),
        ("v2/agent/main.py", "fast"),
        ("v2/db/a.sql", "full"),
        ("v2/oracle/a.sql", "full"),
        ("v2/tests/a test\n.sql", "full"),
        ("v2/scripts/a.sh", "full"),
        ("v2/infra/a.tf", "full"),
        ("infra/a.py", "full"),
        (".github/workflows/test.yml", "full"),
        ("v2/pyproject.toml", "full"),
        ("v2/uv.lock", "full"),
    ],
)
def test_paths(repo: Path, event: str, path: str, expected: str) -> None:
    base = git(repo, "rev-parse", "HEAD")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n")
    git(repo, "add", "--all")
    git(repo, "commit", "-qm", "change")
    assert (
        select_profile(repo, event=event, ref="", base=base, head="HEAD")[0] == expected
    )


@pytest.mark.parametrize("rename", [False, True])
def test_removed_sensitive_path(repo: Path, rename: bool) -> None:
    target = repo / "v2/db/file with spaces.sql"
    target.parent.mkdir(parents=True)
    target.write_text("content\n")
    git(repo, "add", "--all")
    git(repo, "commit", "-qm", "database")
    base = git(repo, "rev-parse", "HEAD")
    if rename:
        target.rename(repo / "unrelated.txt")
    else:
        target.unlink()
    git(repo, "add", "--all")
    git(repo, "commit", "-qm", "remove")
    assert (
        select_profile(repo, event="pull_request", ref="", base=base, head="HEAD")[0]
        == "full"
    )


@pytest.mark.parametrize(
    ("event", "ref", "base", "head", "expected"),
    [
        ("push", "refs/heads/main", "", "", "fast"),
        ("push", "refs/tags/v1", "HEAD", "HEAD", "full"),
        ("workflow_dispatch", "refs/heads/main", "HEAD", "HEAD", "full"),
        ("push", "refs/heads/other", "HEAD", "HEAD", "full"),
        ("pull_request", "", "", "HEAD", "full"),
        ("pull_request", "", "0" * 40, "HEAD", "full"),
        ("pull_request", "", "unknown", "HEAD", "full"),
        ("merge_group", "", "HEAD", "unknown", "full"),
        ("pull_request", "", "--help", "HEAD", "full"),
        ("pull_request", "", "HEAD", "HEAD", "fast"),
    ],
)
def test_events(
    repo: Path, event: str, ref: str, base: str, head: str, expected: str
) -> None:
    assert (
        select_profile(repo, event=event, ref=ref, base=base, head=head)[0] == expected
    )


def test_workflow_profiles() -> None:
    root = Path(__file__).resolve().parents[2]
    ci = (root / ".github/workflows/ci.yml").read_text()
    delivery = (root / ".github/workflows/v2-development-delivery.yml").read_text()
    database = ci.split("  v2-database:\n", 1)[1].split(
        "\n  trusted-development-plan:", 1
    )[0]
    assert "    if:" not in database
    assert (
        'run_db_tests.sh "$SCHEMA_BASE_REF" --profile "$DATABASE_PROFILE"' in database
    )
    assert "select_db_test_profile.py" in database
    assert "PROFILE_HEAD: ${{ github.sha }}" in database
    assert "DATABASE_PROFILE: ${{ steps.database-profile.outputs.profile }}" in database
    job_lines: list[str] = []
    for line in delivery.split("  build:\n", 1)[1].splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.strip():
            break
        job_lines.append(line)
    build = "\n".join(job_lines)
    assert "postgis/postgis:17-3.5" in build
    assert 'run_db_tests.sh "$SCHEMA_BASE_REF" --profile full' in build
    assert "SCHEMA_BASE_REF: ${{ github.event.before }}" in build
    assert "ref: ${{ github.sha }}\n          fetch-depth: 0" in build
    assert build.index("Validate full disposable database contract") < build.index(
        "Build reviewed deployment packages"
    )
    assert build.index("Validate full disposable database contract") < build.index(
        "Upload immutable deployment packages"
    )
    assert "configure-aws-credentials" not in build

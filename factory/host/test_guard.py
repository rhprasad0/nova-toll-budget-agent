import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from factory.host import dispatcher, guard

CONFIG = dispatcher.CHECKOUT / ".gitleaks.toml"
FAKE_TOKEN = "ghp_" + "Zq3Xv8Lr2Tn6Wb4Yc1Hd9Kf5Mj7Pa0Se2Ug4"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)  # fmt: skip


def write(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch=main")
    write(tmp_path, "v2/eval/EXPERIMENT_JOURNAL.md", "# Journal\n\n- first entry\n")
    write(tmp_path, guard.MANIFEST, json.dumps(
        {"deployment_inputs": {"a": "1"}, "packages": {}, "mutations": ["x"]}, indent=2))  # fmt: skip
    write(tmp_path, "v2/app.py", "print('hi')\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "--quiet", "-m", "base")
    git(tmp_path, "checkout", "--quiet", "-b", "factory/issue-1")
    return tmp_path


def commit(repo: Path, change: Callable[[Path], None]) -> list[str]:
    change(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "work")
    return guard.check(repo, "factory/issue-1", CONFIG)


@pytest.mark.parametrize(
    "path",
    ["infra/factory.tf", "v2/infra/main.tf", "modules/x/vars.tfvars", ".github/workflows/ci.yml",
     ".claude/settings.json", "SECURITY.md", "org-circuit-breaker/handler.py",
     "v2/CLAUDE.md", "docs/deep/AGENTS.md", "CLAUDE.local.md"],
)  # fmt: skip
def test_a_protected_path_blocks_the_push(repo: Path, path: str) -> None:
    assert commit(repo, lambda r: write(r, path, "x\n")) == [
        f"changes protected path {path}"
    ]


def test_deleting_a_protected_file_blocks_the_push(repo: Path) -> None:
    write(repo, "infra/kms.tf", "x\n")
    git(repo, "checkout", "--quiet", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "seed")
    git(repo, "checkout", "--quiet", "-B", "factory/issue-1")
    assert commit(repo, lambda r: (r / "infra/kms.tf").unlink()) == [
        "changes protected path infra/kms.tf"
    ]


def test_a_planted_secret_blocks_the_push_even_with_an_inline_allow(repo: Path) -> None:
    def plant(r: Path) -> None:
        write(r, "v2/config.py", f"TOKEN = '{FAKE_TOKEN}'  # gitleaks:allow\n")
        write(r, ".gitleaksignore", "*\n")

    problems = commit(repo, plant)
    assert any(
        p.startswith("possible secret") and "v2/config.py" in p for p in problems
    )
    assert FAKE_TOKEN not in " ".join(problems)


def test_deleting_or_rewriting_a_journal_line_blocks_the_push(repo: Path) -> None:
    def rewrite(r: Path) -> None:
        write(r, guard.JOURNAL_FILE, "# Journal\n\n- first entry, improved\n")

    assert commit(repo, rewrite) == [
        f"deletes or rewrites a line of {guard.JOURNAL_FILE}"
    ]


def test_appending_to_the_journal_passes(repo: Path) -> None:
    def append(r: Path) -> None:
        write(r, guard.JOURNAL_FILE, "# Journal\n\n- first entry\n- second entry\n")
        write(r, "v2/eval/journal/2026-11-15.md", "New page.\n")

    assert commit(repo, append) == []


def test_the_manifest_may_change_only_digests_and_packages(repo: Path) -> None:
    def digests(r: Path) -> None:
        write(r, guard.MANIFEST, json.dumps(
            {"deployment_inputs": {"a": "2"}, "packages": {"p": "d"}, "mutations": ["x"]}))  # fmt: skip

    assert commit(repo, digests) == []

    def mutations(r: Path) -> None:
        write(r, guard.MANIFEST, json.dumps(
            {"deployment_inputs": {"a": "2"}, "packages": {"p": "d"}, "mutations": ["x", "y"]}))  # fmt: skip

    assert commit(repo, mutations) == [
        f"changes {guard.MANIFEST} outside deployment_inputs and packages"
    ]


def test_an_ordinary_change_passes(repo: Path) -> None:
    assert commit(repo, lambda r: write(r, "v2/app.py", "print('hello')\n")) == []


def test_a_secrets_scan_that_fails_blocks_the_push(repo: Path, tmp_path: Path) -> None:
    write(repo, "v2/app.py", "print('hello')\n")
    git(repo, "commit", "--quiet", "-am", "work")
    missing = tmp_path / "missing.toml"
    assert guard.secrets(repo, "main", "factory/issue-1", missing) == [
        "the secrets scan did not cover the branch's 1 commits"
    ]

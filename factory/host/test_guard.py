import json
import subprocess
import tempfile
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
    tmp_path = tmp_path / "repo"
    tmp_path.mkdir()
    git(tmp_path, "init", "--quiet", "--initial-branch=main")
    write(tmp_path, "v2/eval/EXPERIMENT_JOURNAL.md", "# Journal\n\n- first entry\n")
    write(tmp_path, guard.MANIFEST, json.dumps(
        {"deployment_inputs": {"a": "1"}, "packages": {}, "mutations": ["x"]}, indent=2))  # fmt: skip
    write(tmp_path, "v2/app.py", "print('hi')\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "--quiet", "-m", "base")
    git(tmp_path, "checkout", "--quiet", "-b", "factory/issue-1")
    return tmp_path


def checked(repo: Path) -> list[str]:
    clean = repo.parent / f"{repo.name}-clean"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-checkout", str(repo), str(clean)], check=True
    )
    try:
        return guard.check(clean, "origin/factory/issue-1", CONFIG, base="origin/main")
    finally:
        subprocess.run(["rm", "-rf", str(clean)], check=True)


def commit(repo: Path, change: Callable[[Path], None]) -> list[str]:
    change(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "work")
    return checked(repo)


@pytest.mark.parametrize(
    "path",
    ["infra/factory.tf", "v2/infra/main.tf", "modules/x/vars.tfvars", ".github/workflows/ci.yml",
     ".claude/settings.json", "SECURITY.md", "org-circuit-breaker/handler.py",
     "v2/CLAUDE.md", "docs/deep/AGENTS.md", "CLAUDE.local.md", "v2/claude.md",
     "v2/.claude/settings.json", ".githooks/pre-commit", ".mcp.json", "docs/SECURITY.md",
     "v2/stack.tf.json", "factory/host/guard.py"],
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

    problems = commit(repo, plant)
    assert problems == ["possible secret (github-pat) in the branch"]
    assert FAKE_TOKEN not in " ".join(problems)


def test_the_workers_own_gitleaksignore_suppresses_nothing(repo: Path) -> None:
    write(repo, "v2/config.py", f"TOKEN = '{FAKE_TOKEN}'\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "plant")
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "r.json"
        subprocess.run(["gitleaks", "git", "--no-banner", "--report-format", "json",
                        "--report-path", str(report), "--exit-code", "0", "--log-opts",
                        "main..factory/issue-1", str(repo)], check=True, capture_output=True)  # fmt: skip
        fingerprint = json.loads(report.read_text())[0]["Fingerprint"]
    problems = commit(repo, lambda r: write(r, ".gitleaksignore", f"{fingerprint}\n"))
    assert problems == ["possible secret (github-pat) in the branch"]


def test_a_secret_in_a_binary_file_blocks_the_push(repo: Path) -> None:
    def plant(r: Path) -> None:
        (r / "v2/blob.bin").write_bytes(
            b"\x00\x01 " + f"TOKEN = '{FAKE_TOKEN}'\n".encode()
        )

    assert commit(repo, plant) == ["possible secret (github-pat) in the branch"]


def test_a_merge_commit_blocks_the_push(repo: Path) -> None:
    git(repo, "checkout", "--quiet", "-b", "side", "main")
    write(repo, "v2/side.py", "x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "side")
    git(repo, "checkout", "--quiet", "factory/issue-1")
    git(repo, "merge", "--quiet", "--no-ff", "--no-edit", "side")
    assert checked(repo) == ["contains merge commits"]


def test_a_branch_without_mains_history_is_refused_with_a_reason(repo: Path) -> None:
    git(repo, "checkout", "--quiet", "--orphan", "orphan")
    git(repo, "commit", "--quiet", "--allow-empty", "-m", "orphan")
    git(repo, "branch", "--force", "factory/issue-1", "orphan")
    assert checked(repo) == ["the branch does not share history with main"]


def test_renaming_a_protected_file_out_blocks_the_push(repo: Path) -> None:
    git(repo, "checkout", "--quiet", "main")
    write(repo, ".github/workflows/ci.yml", "on: push\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "seed")
    git(repo, "checkout", "--quiet", "-B", "factory/issue-1")
    (repo / "docs").mkdir()
    git(repo, "mv", ".github/workflows/ci.yml", "docs/ci.yml")
    git(repo, "commit", "--quiet", "-m", "move")
    assert checked(repo) == ["changes protected path .github/workflows/ci.yml"]


def test_the_guard_refuses_a_clone_with_a_checkout(repo: Path) -> None:
    with pytest.raises(ValueError, match="without a checkout"):
        guard.check(repo, "factory/issue-1", CONFIG)


@pytest.mark.parametrize(
    "text",
    [
        "# Journal\n\n- first entry, improved\n",
        "# Journal\n\n",
        "# Journal\n---\n- first entry\n\x00",
    ],
    ids=["rewrite", "delete", "binary"],
)
def test_deleting_or_rewriting_a_journal_line_blocks_the_push(
    repo: Path, text: str
) -> None:
    assert commit(repo, lambda r: write(r, guard.JOURNAL_FILE, text)) == [
        f"deletes or rewrites a line of {guard.JOURNAL_FILE}"
    ]


def test_deleting_a_dashed_journal_line_blocks_the_push(repo: Path) -> None:
    git(repo, "checkout", "--quiet", "main")
    write(repo, guard.JOURNAL_FILE, "# Journal\n\n---\n- first entry\n")
    git(repo, "commit", "--quiet", "-am", "seed")
    git(repo, "checkout", "--quiet", "-B", "factory/issue-1")
    assert commit(
        repo, lambda r: write(r, guard.JOURNAL_FILE, "# Journal\n\n- first entry\n")
    ) == [f"deletes or rewrites a line of {guard.JOURNAL_FILE}"]


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

    def duplicate(r: Path) -> None:
        write(r, guard.MANIFEST, '{"mutations": ["evil"], "deployment_inputs": {"a": "2"}, '
              '"packages": {"p": "d"}, "mutations": ["x"]}')  # fmt: skip

    assert commit(repo, duplicate) == [
        f"changes {guard.MANIFEST} outside deployment_inputs and packages"
    ]


def test_an_ordinary_change_passes(repo: Path) -> None:
    assert commit(repo, lambda r: write(r, "v2/app.py", "print('hello')\n")) == []


def run_cli(repo: Path) -> subprocess.CompletedProcess[str]:
    clean = repo.parent / f"{repo.name}-cli"
    subprocess.run(["git", "init", "--quiet", str(clean)], check=True)
    subprocess.run(["git", "-C", str(clean), "fetch", "--quiet", str(repo),
                    "main:refs/heads/main", "factory/issue-1:refs/heads/candidate"],
                   check=True)  # fmt: skip
    return subprocess.run(
        ["python3", str(Path(guard.__file__)), str(clean), "refs/heads/candidate",
         str(CONFIG), "main"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_the_command_line_fails_a_protected_change_with_an_annotation(
    repo: Path,
) -> None:
    write(repo, ".github/workflows/ci.yml", "x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "work")
    done = run_cli(repo)
    assert done.returncode == 1
    assert done.stdout == (
        "::error::Factory PRs may not do this: "
        "changes protected path .github/workflows/ci.yml\n"
    )


def test_the_command_line_passes_an_ordinary_change(repo: Path) -> None:
    write(repo, "v2/app.py", "print('hello')\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "work")
    done = run_cli(repo)
    assert (done.returncode, done.stdout) == (0, "")


def test_a_secrets_scan_that_fails_blocks_the_push(repo: Path, tmp_path: Path) -> None:
    write(repo, "v2/app.py", "print('hello')\n")
    git(repo, "commit", "--quiet", "-am", "work")
    missing = tmp_path / "missing.toml"
    assert guard.leak_scan(repo, "main", "factory/issue-1", missing, ["v2/app.py"]) == [
        "the secrets scan did not cover the branch's 1 commits"
    ]


@pytest.mark.parametrize(
    "message", ["Fixes #12", "closes: owner/repo#3", "Resolved #4 too"]
)
def test_a_commit_message_that_closes_an_issue_blocks_the_push(
    repo: Path, message: str
) -> None:
    write(repo, "v2/app.py", "print('hello')\n")
    git(repo, "commit", "--quiet", "-am", f"Change the app\n\n{message}")
    assert checked(repo) == ["a commit message would close an issue"]


def test_a_release_digest_update_passes_the_configs_path_allowlist(repo: Path) -> None:
    digest = "9f2c4b7e1a6d3f8c0b5e2a9d4c7f1b3e6a8d0c2f5b9e4a7d1c3f6b8e0a2d5c9f"

    def refresh(r: Path) -> None:
        manifest = {"deployment_inputs": {"v2/agent/public-api-gate.js": digest},
                    "packages": {}, "mutations": ["x"]}  # fmt: skip
        write(r, guard.MANIFEST, json.dumps(manifest, indent=2))

    assert commit(repo, refresh) == []

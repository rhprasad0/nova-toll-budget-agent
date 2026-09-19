"""Exercise the real hook/runner in disposable repositories with checker spies."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

SOURCE = Path(__file__).resolve().parents[2]
CHECKERS = ("gitleaks", "ruff", "pyright", "eslint", "tsc", "shellcheck", "actionlint")


class Repository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.log = root / ".calls"
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "PATH": str(root / ".bin"),
            "CHECK_LOG": str(self.log),
        }
        for name in ("git", "bash", "python3"):
            executable = shutil.which(name)
            assert executable
            target = root / ".bin" / name
            target.parent.mkdir(exist_ok=True)
            target.symlink_to(executable)
        self.write(".gitignore", ".bin/\n.calls\nv2/.venv/\nv2/node_modules/\n")
        for name in (*CHECKERS, "node", "uv", "pytest"):
            directory = (
                "v2/.venv/bin"
                if name in {"ruff", "pyright"}
                else "v2/node_modules/.bin"
                if name in {"eslint", "tsc"}
                else ".bin"
            )
            tool = self.write(
                f"{directory}/{name}",
                f"#!{sys.executable}\n"
                "import json, os, pathlib, sys\n"
                "name = pathlib.Path(sys.argv[0]).name\n"
                "with open(os.environ['CHECK_LOG'], 'a') as output:\n"
                "    output.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
                "sys.exit(9 if name == os.environ.get('FAIL_TOOL') or name in {'uv', 'pytest'} else 0)\n",
            )
            tool.chmod(0o755)
        for name in (
            "v2/scripts/check_repository.py",
            "v2/scripts/check_workflows.py",
            ".githooks/pre-commit",
        ):
            self.write(name, (SOURCE / name).read_text()).chmod(0o755)
        for name, content in {
            "v2/example.py": "value = 1\n",
            "v2/sibling.py": "value = 2\n",
            "v2/example.mjs": "export const value = 1;\n",
            "v2/example.sh": "#!/bin/bash\ntrue\n",
            ".github/workflows/example.yml": "name: example\n",
            "v2/pyproject.toml": "",
            "v2/package.json": "{}\n",
            ".gitleaks.toml": "",
            "README.md": "example\n",
        }.items():
            self.write(name, content)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Hook Test")
        self.git("add", ".")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "Initial")

    def write(self, name: str, content: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def git(self, *args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=self.root, env=self.env)

    def run(
        self, *, hook: bool = True, fail: str = ""
    ) -> subprocess.CompletedProcess[str]:
        command = (
            ["bash", ".githooks/pre-commit"]
            if hook
            else [sys.executable, "v2/scripts/check_repository.py"]
        )
        return subprocess.run(
            command,
            cwd=self.root,
            env={**self.env, "FAIL_TOOL": fail},
            text=True,
            capture_output=True,
            check=False,
        )

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        result: list[list[str]] = []
        for line in self.log.read_text().splitlines():
            value: object = json.loads(line)
            assert isinstance(value, list)
            items = cast(list[object], value)
            assert all(isinstance(item, str) for item in items)
            result.append([str(item) for item in items])
        return result


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    return Repository(tmp_path)


def test_clean_hook_checks_entire_affected_group_without_mutation(
    repository: Repository,
) -> None:
    repository.write("v2/space and\nnewline.py", "value = 3\n")
    repository.git("add", ".")
    index = (repository.root / ".git/index").read_bytes()
    files = {
        name: (repository.root / name).read_bytes()
        for name in os.fsdecode(repository.git("ls-files", "-z")).split("\0")
        if name
    }
    result = repository.run()
    assert result.returncode == 0, result.stderr
    assert (repository.root / ".git/index").read_bytes() == index
    assert all(
        (repository.root / name).read_bytes() == data for name, data in files.items()
    )
    calls = repository.calls()
    assert [call[0] for call in calls] == ["gitleaks", "ruff", "ruff", "pyright"]
    assert "./v2/sibling.py" in calls[1]
    assert "./v2/space and\nnewline.py" in calls[1]


@pytest.mark.parametrize(
    "unstaged", ["v2/example.py", "v2/sibling.py", "v2/pyproject.toml"]
)
def test_partial_staging_cannot_hide_staged_defect(
    repository: Repository, unstaged: str
) -> None:
    repository.write("v2/example.py", "invalid python!\n")
    repository.git("add", "v2/example.py")
    repository.write(unstaged, "value = 1\n")
    result = repository.run()
    assert result.returncode == 1
    assert "Index and working copy differ" in result.stderr
    assert not repository.calls()


def test_unrelated_unstaged_language_is_allowed(repository: Repository) -> None:
    repository.write("v2/example.py", "value = 3\n")
    repository.git("add", "v2/example.py")
    repository.write("v2/example.mjs", "unfinished JavaScript\n")
    assert repository.run().returncode == 0


@pytest.mark.parametrize("operation", ["rename", "delete", "config"])
def test_changes_select_complete_groups(repository: Repository, operation: str) -> None:
    if operation == "rename":
        repository.git("mv", "v2/example.py", "v2/renamed.mjs")
    elif operation == "delete":
        repository.git("rm", "v2/example.py")
    else:
        repository.write("v2/pyproject.toml", "# changed\n")
        repository.git("add", "v2/pyproject.toml")
    assert repository.run().returncode == 0
    names = {call[0] for call in repository.calls()}
    expected = {"gitleaks", "ruff", "pyright"}
    if operation in {"rename", "config"}:
        expected |= {"eslint", "tsc"}
    if operation == "config":
        expected |= {"shellcheck", "actionlint"}
    assert names == expected


def test_document_commit_still_requires_secret_scan(repository: Repository) -> None:
    repository.write("README.md", "changed\n")
    repository.git("add", "README.md")
    assert repository.run().returncode == 0
    assert repository.calls() == [["gitleaks", "protect", "--staged", "--redact"]]
    repository.write(".gitleaks.toml", "# unstaged override\n")
    assert repository.run().returncode == 1


@pytest.mark.parametrize("missing", [".bin/gitleaks", "v2/.venv/bin/ruff"])
def test_missing_tools_fail_with_setup(repository: Repository, missing: str) -> None:
    repository.write("v2/example.py", "value = 3\n")
    repository.git("add", "v2/example.py")
    (repository.root / missing).unlink()
    result = repository.run()
    assert result.returncode == 1
    assert "Missing required tool" in result.stderr
    assert "Setup:" in result.stderr


@pytest.mark.parametrize(
    "checker", ["ruff", "pyright", "eslint", "tsc", "shellcheck", "actionlint"]
)
@pytest.mark.parametrize("hook", [True, False])
def test_checker_failures_block_both_entrypoints(
    repository: Repository, checker: str, hook: bool
) -> None:
    repository.write("v2/pyproject.toml", "# check all\n")
    repository.git("add", "v2/pyproject.toml")
    assert repository.run(hook=hook, fail=checker).returncode == 1
    assert checker in {call[0] for call in repository.calls()}


def test_full_entrypoint_checks_all_languages(repository: Repository) -> None:
    assert repository.run(hook=False).returncode == 0
    assert {call[0] for call in repository.calls()} == set(CHECKERS) - {"gitleaks"}


def test_blanket_suppression_rejected(repository: Repository) -> None:
    repository.write("v2/example.py", "value = 1  # noqa\n")
    repository.git("add", "v2/example.py")
    result = repository.run()
    assert result.returncode == 1
    assert "blanket suppression" in result.stderr


def test_narrow_python_suppression_is_left_to_checker(repository: Repository) -> None:
    repository.write(
        "v2/example.py",
        "# External SDK decorator lacks annotations.\n"
        "value = 1  # pyright: ignore[reportUnknownMemberType]\n",
    )
    repository.git("add", "v2/example.py")
    assert repository.run().returncode == 0


def test_full_runner_resolves_paths_from_another_directory(
    repository: Repository,
) -> None:
    result = subprocess.run(
        [sys.executable, str(repository.root / "v2/scripts/check_repository.py")],
        cwd=repository.root / "v2",
        env=repository.env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert {call[0] for call in repository.calls()} == set(CHECKERS) - {"gitleaks"}
    ruff = next(call for call in repository.calls() if call[0] == "ruff")
    assert (
        "src = " + json.dumps([str(repository.root / "v2"), str(repository.root)])
        in ruff
    )


@pytest.mark.parametrize(
    "configuration",
    [
        ".github/workflows/ci.yml",
        "v2/lambdas/chat_proxy/package-lock.json",
        ".gitignore",
    ],
)
def test_checker_inputs_select_all_groups(
    repository: Repository, configuration: str
) -> None:
    source = repository.root / configuration
    repository.write(
        configuration, (source.read_text() if source.exists() else "") + "\n"
    )
    repository.git("add", configuration)
    assert repository.run().returncode == 0
    assert {call[0] for call in repository.calls()} == set(CHECKERS)

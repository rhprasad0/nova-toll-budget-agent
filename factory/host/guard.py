import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PROTECTED_PREFIXES = (
    "infra/",
    "v2/infra/",
    "org-circuit-breaker/",
    ".github/",
    ".claude/",
)
PROTECTED_FILES = {"SECURITY.md"}
PROTECTED_NAMES = {"AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"}
PROTECTED_SUFFIXES = (".tf", ".tfvars")
JOURNAL_FILE = "v2/eval/EXPERIMENT_JOURNAL.md"
JOURNAL_DIR = "v2/eval/journal/"
MANIFEST = "infra/development-release-manifest.json"
MANIFEST_OPEN = {"deployment_inputs", "packages"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout  # fmt: skip


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    out = git(repo, "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}")
    return [path for path in out.split("\0") if path]


def protected(path: str) -> bool:
    if path == MANIFEST:
        return False
    return (
        path.startswith(PROTECTED_PREFIXES)
        or path in PROTECTED_FILES
        or path.rsplit("/", 1)[-1] in PROTECTED_NAMES
        or path.endswith(PROTECTED_SUFFIXES)
    )


def journal(path: str) -> bool:
    return path == JOURNAL_FILE or path.startswith(JOURNAL_DIR)


def removes_lines(repo: Path, base: str, head: str, path: str) -> bool:
    diff = git(
        repo, "diff", "--no-renames", "--unified=0", f"{base}...{head}", "--", path
    )
    return any(
        line.startswith("-") and not line.startswith("---")
        for line in diff.splitlines()
    )


def manifest_closed_part(repo: Path, ref: str) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(git(repo, "show", f"{ref}:{MANIFEST}"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {"unreadable": True}
    return {key: value for key, value in data.items() if key not in MANIFEST_OPEN}


def secrets(repo: Path, base: str, head: str, config: Path) -> list[str]:
    commits = int(git(repo, "rev-list", "--count", f"{base}..{head}"))
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "gitleaks.json"
        done = subprocess.run(
            ["gitleaks", "git", "--no-banner", "--no-color", "--redact", "--config", str(config),
             "--gitleaks-ignore-path", scratch, "--ignore-gitleaks-allow",
             "--log-opts", f"{base}..{head}", "--report-format", "json",
             "--report-path", str(report), "--exit-code", "0", str(repo)],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        scanned = re.search(r"\b(\d+) commits? scanned", done.stderr)
        if (
            done.returncode
            or " ERR " in done.stderr
            or not scanned
            or int(scanned.group(1)) > commits
        ):
            return [f"the secrets scan did not cover the branch's {commits} commits"]
        findings: list[dict[str, Any]] = json.loads(report.read_text() or "[]")
    return sorted({f"possible secret ({f['RuleID']}) in {f['File']}" for f in findings})


def check(repo: Path, head: str, config: Path, base: str = "main") -> list[str]:
    """Why HEAD may not be pushed, as reasons safe to post; empty when it may."""
    paths = changed_paths(repo, base, head)
    problems = [f"changes protected path {path}" for path in paths if protected(path)]
    problems += [
        f"deletes or rewrites a line of {path}"
        for path in paths
        if journal(path) and removes_lines(repo, base, head, path)
    ]
    if MANIFEST in paths and manifest_closed_part(repo, base) != manifest_closed_part(
        repo, head
    ):
        problems.append(f"changes {MANIFEST} outside deployment_inputs and packages")
    return problems + secrets(repo, base, head, config)

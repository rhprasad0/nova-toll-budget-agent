import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

PROTECTED_PREFIXES = (
    "infra/",
    "v2/infra/",
    "org-circuit-breaker/",
    ".github/",
    ".githooks/",
)
PROTECTED_FILES = {"security.md", "docs/security.md", ".mcp.json"}
PROTECTED_NAMES = {"agents.md", "claude.md", "claude.local.md"}
PROTECTED_DIRS = {".claude"}
PROTECTED_SUFFIXES = (".tf", ".tfvars", ".tf.json")
JOURNAL_FILE = "v2/eval/EXPERIMENT_JOURNAL.md"
JOURNAL_DIR = "v2/eval/journal/"
MANIFEST = "infra/development-release-manifest.json"
MANIFEST_OPEN = {"deployment_inputs", "packages"}
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[:\s]+[\w.-]*/?[\w.-]*#\d+", re.I
)

Findings = list[dict[str, Any]]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout  # fmt: skip


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    out = git(repo, "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}")
    return [path for path in out.split("\0") if path]


def protected(path: str) -> bool:
    if path == MANIFEST:
        return False
    folded = path.casefold()
    parts = folded.split("/")
    return (
        folded.startswith(PROTECTED_PREFIXES)
        or folded in PROTECTED_FILES
        or parts[-1] in PROTECTED_NAMES
        or any(part in PROTECTED_DIRS for part in parts[:-1])
        or folded.endswith(PROTECTED_SUFFIXES)
    )


def journal(path: str) -> bool:
    return path == JOURNAL_FILE or path.startswith(JOURNAL_DIR)


def removes_lines(repo: Path, base: str, head: str, path: str) -> bool:
    out = git(
        repo,
        "diff",
        "--text",
        "--numstat",
        "--no-renames",
        f"{base}...{head}",
        "--",
        path,
    )
    for line in out.splitlines():
        removed = line.split("\t")[1]
        if not removed.isdigit() or int(removed):
            return True
    return False


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate keys")
    return dict(pairs)


def manifest_closed_part(repo: Path, ref: str) -> dict[str, Any]:
    try:
        text = git(repo, "show", f"{ref}:{MANIFEST}")
        data: Any = json.loads(text, object_pairs_hook=unique_object)
    except (subprocess.CalledProcessError, ValueError):
        return {"unreadable": True}
    if not isinstance(data, dict):
        return {"unreadable": True}
    fields = cast(dict[str, Any], data)
    return {key: value for key, value in fields.items() if key not in MANIFEST_OPEN}


def gitleaks(
    args: list[str], config: Path, scratch: Path
) -> tuple[subprocess.CompletedProcess[str], Findings]:
    report = scratch / "gitleaks.json"
    done = subprocess.run(
        ["gitleaks", *args, "--no-banner", "--no-color", "--redact", "--config", str(config),
         "--gitleaks-ignore-path", str(scratch), "--ignore-gitleaks-allow",
         "--report-format", "json", "--report-path", str(report), "--exit-code", "0"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    findings: Findings = []
    if report.exists():
        findings = json.loads(report.read_text() or "[]")
        report.unlink()
    return done, findings


def export(repo: Path, head: str, paths: list[str], tree: Path) -> None:
    present = set(git(repo, "ls-tree", "-r", "-z", "--name-only", head).split("\0"))
    for path in paths:
        if path in present and Path(path).name != ".gitleaksignore":
            data = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{path}"],
                                  check=True, capture_output=True).stdout  # fmt: skip
            target = tree / path
            if b"\0" in data:
                target = tree / f"{path}.strings"
                data = b"\n".join(re.findall(rb"[\x20-\x7e]{8,}", data))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def secrets(
    repo: Path, base: str, head: str, config: Path, paths: list[str]
) -> list[str]:
    commits = int(git(repo, "rev-list", "--count", f"{base}..{head}"))
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        done, history = gitleaks(
            ["git", "--log-opts", f"{base}..{head}", str(repo)], config, root
        )
        scanned = re.search(r"\b(\d+) commits? scanned", done.stderr)
        failed = done.returncode or " ERR " in done.stderr
        if failed or not scanned or int(scanned.group(1)) > commits:
            return [f"the secrets scan did not cover the branch's {commits} commits"]
        tree = root / "tree"
        export(repo, head, paths, tree)
        current: Findings = []
        if tree.exists():
            done, current = gitleaks(["dir", str(tree)], config, root)
            if done.returncode or " ERR " in done.stderr:
                return ["the secrets scan of the branch's files failed"]
    rules = sorted({str(finding["RuleID"]) for finding in history + current})
    return [f"possible secret ({rule}) in the branch" for rule in rules]


def check(repo: Path, head: str, config: Path, base: str = "main") -> list[str]:
    """Why HEAD may not be pushed, as reasons safe to post; empty when it may."""
    if any(child.name != ".git" for child in repo.iterdir()):
        raise ValueError(f"{repo} must be a clone without a checkout")
    try:
        paths = changed_paths(repo, base, head)
        merges = int(git(repo, "rev-list", "--count", "--merges", f"{base}..{head}"))
    except subprocess.CalledProcessError:
        return ["the branch does not share history with main"]
    problems = [f"changes protected path {path}" for path in paths if protected(path)]
    if merges:
        problems.append("contains merge commits")
    if CLOSING.search(git(repo, "log", "--format=%B", f"{base}..{head}")):
        problems.append("a commit message would close an issue")
    problems += [
        f"deletes or rewrites a line of {path}"
        for path in paths
        if journal(path) and removes_lines(repo, base, head, path)
    ]
    closed = manifest_closed_part
    if MANIFEST in paths and closed(repo, base) != closed(repo, head):
        problems.append(f"changes {MANIFEST} outside deployment_inputs and packages")
    return problems + secrets(repo, base, head, config, paths)

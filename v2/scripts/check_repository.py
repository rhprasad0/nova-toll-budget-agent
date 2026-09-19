#!/usr/bin/env python3
"""Run the same repository static checks locally and in CI, without installing tools."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("python", "javascript", "shell", "workflows")
CONFIGURATION = {
    ".githooks/pre-commit",
    ".gitleaks.toml",
    ".gitignore",
    ".github/workflows/ci.yml",
    ".shellcheckrc",
    ".github/actionlint.yaml",
    "v2/pyproject.toml",
    "v2/uv.lock",
    "v2/package.json",
    "v2/package-lock.json",
    "v2/lambdas/chat_proxy/package.json",
    "v2/lambdas/chat_proxy/package-lock.json",
    "v2/eslint.config.mjs",
    "v2/scripts/check_repository.py",
    "v2/scripts/check_workflows.py",
    "v2/scripts/install_check_tools.sh",
}
# These are upstream distributions; adjacent authored declarations remain checked.
VENDORED = {
    "v2/agent/assets/markdown-it.esm.min.mjs",
    "v2/agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs",
    "v2/agent/assets/maplibre-gl-6.0.0/maplibre-gl-shared.mjs",
    "v2/agent/assets/maplibre-gl-6.0.0/maplibre-gl-worker.mjs",
}
IGNORED_DIRECTORIES = {".git", ".worktrees", ".venv", "node_modules", "__pycache__"}


def git_paths(*arguments: str) -> set[str]:
    output = subprocess.check_output(
        ["git", *arguments, "-z"],
        cwd=ROOT,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    return {os.fsdecode(value) for value in output.split(b"\0") if value}


def group(path: str) -> str | None:
    parts = Path(path).parts
    if (
        path in VENDORED
        or any(part in IGNORED_DIRECTORIES for part in parts)
        or path.startswith(("v2/infra/build/", "infra/build/"))
    ):
        return None
    if path.endswith((".py", ".pyi")):
        return "python"
    if path.endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts")):
        return "javascript"
    if path.endswith(".sh") or path == ".githooks/pre-commit":
        return "shell"
    if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")):
        return "workflows"
    return None


def configuration(path: str) -> bool:
    return path in CONFIGURATION or (
        path.startswith("v2/tsconfig") and path.endswith(".json")
    )


def selected_groups(staged: set[str]) -> set[str]:
    if any(configuration(path) for path in staged):
        return set(GROUPS)
    return {selected for path in staged if (selected := group(path)) is not None}


def require_tool(path: str, setup: str) -> str:
    resolved = ROOT / path if "/" in path else shutil.which(path)
    if resolved is None or not os.access(resolved, os.X_OK):
        raise ValueError(f"Missing required tool {path!r}. Setup: {setup}")
    return str(resolved)


def reject_suppressions(paths: list[str]) -> None:
    patterns = (
        r"#\s*(?:ruff:\s*)?noqa\s*(?:$|--)",
        r"#\s*ruff:\s*noqa",
        r"#\s*pyright:\s*(?!\s|ignore\[)",
        r"#\s*(?:type|pyright):\s*ignore(?!\[)",
        r"@ts-(?:nocheck|ignore)\b",
        r"eslint-disable(?!-next-line|-line)\b",
        r"eslint-disable-(?:next-line|line)\s*(?:$|\*/|--)",
        r"shellcheck\s+disable=(?!SC[0-9]{4}(?:,SC[0-9]{4})*\s*$)",
    )
    for path in paths:
        source = (ROOT / path).read_text()
        comments = (
            (
                (token.start[0], token.string)
                for token in tokenize.generate_tokens(io.StringIO(source).readline)
                if token.type == tokenize.COMMENT
            )
            if group(path) == "python"
            else enumerate(source.splitlines(), 1)
        )
        for number, line in comments:
            if any(re.search(pattern, line) for pattern in patterns):
                raise ValueError(f"{path}:{number}: blanket suppression is not allowed")


def commands(selected: set[str], paths: list[str]) -> list[list[str]]:
    result: list[list[str]] = []
    if "python" in selected:
        setup = "uv sync --locked --project v2"
        ruff = require_tool("v2/.venv/bin/ruff", setup)
        pyright = require_tool("v2/.venv/bin/pyright", setup)
        files = [path for path in paths if group(path) == "python"]
        # Explicit --config makes Ruff resolve relative src against cwd, not TOML.
        roots = "src = " + json.dumps([str(ROOT / "v2"), str(ROOT)])
        if files:
            result.extend(
                [
                    [
                        ruff,
                        "check",
                        "--config",
                        "v2/pyproject.toml",
                        "--config",
                        roots,
                        *["./" + path for path in files],
                    ],
                    [
                        ruff,
                        "format",
                        "--check",
                        "--config",
                        "v2/pyproject.toml",
                        "--config",
                        roots,
                        *["./" + path for path in files],
                    ],
                    [
                        pyright,
                        "--warnings",
                        "--project",
                        "v2/pyproject.toml",
                        *["./" + path for path in files],
                    ],
                ]
            )
    if "javascript" in selected:
        setup = "npm ci --prefix v2"
        require_tool("node", "Install the Node version documented in v2/README.md")
        eslint = require_tool("v2/node_modules/.bin/eslint", setup)
        tsc = require_tool("v2/node_modules/.bin/tsc", setup)
        files = [
            path
            for path in paths
            if path.endswith((".js", ".mjs", ".cjs")) and group(path) == "javascript"
        ]
        if files:
            result.append(
                [
                    eslint,
                    "--max-warnings",
                    "0",
                    "--config",
                    "v2/eslint.config.mjs",
                    *["./" + path for path in files],
                ]
            )
        result.extend(
            [tsc, "--project", f"v2/tsconfig.{environment}.json"]
            for environment in ("browser", "node", "cloudfront")
        )
    if "shell" in selected or "workflows" in selected:
        shellcheck = require_tool("shellcheck", "v2/scripts/install_check_tools.sh")
        if "shell" in selected:
            files = [path for path in paths if group(path) == "shell"]
            if files:
                result.append(
                    [
                        sys.executable,
                        "v2/scripts/check_workflows.py",
                        "--shell-scripts",
                        "--shellcheck",
                        shellcheck,
                        *["./" + path for path in files],
                    ]
                )
        if "workflows" in selected:
            actionlint = require_tool("actionlint", "v2/scripts/install_check_tools.sh")
            files = [path for path in paths if group(path) == "workflows"]
            if files:
                result.append(
                    [
                        sys.executable,
                        "v2/scripts/check_workflows.py",
                        "--actionlint",
                        actionlint,
                        "--shellcheck",
                        shellcheck,
                        *["./" + path for path in files],
                    ]
                )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staged", action="store_true", help="Check complete affected language groups"
    )
    args = parser.parse_args(argv)
    try:
        tracked = git_paths("ls-files", "--cached")
        untracked = git_paths("ls-files", "--others", "--exclude-standard")
        selected: set[str] = set(GROUPS)
        if args.staged:
            # Without rename detection Git reports both old and new paths, including
            # moves across language groups, without parsing a status/path protocol.
            staged = git_paths("diff", "--cached", "--name-only", "--no-renames")
            selected = selected_groups(staged)
            unstaged = git_paths("diff", "--name-only", "--no-renames") | untracked
            mismatches = sorted(
                path
                for path in unstaged
                if group(path) in selected
                or (selected and configuration(path))
                or path
                in {
                    ".gitleaks.toml",
                    ".githooks/pre-commit",
                    "v2/scripts/check_repository.py",
                }
            )
            if mismatches:
                raise ValueError(
                    "Index and working copy differ in checked inputs. Stage or resolve these changes first: "
                    + ", ".join(repr(path) for path in mismatches)
                )
        paths = sorted(
            path
            for path in tracked | untracked
            if group(path) in selected and (ROOT / path).is_file()
        )
        checks = commands(selected, paths)
        if args.staged:
            gitleaks = require_tool(
                "gitleaks", "See the pinned Gitleaks setup in v2/README.md"
            )
            checks.insert(0, [gitleaks, "protect", "--staged", "--redact"])
        reject_suppressions(paths)
        for command in checks:
            print("Checking:", Path(command[0]).name, *command[1:3], flush=True)
            subprocess.run(command, cwd=ROOT, check=True)
        return 0
    except (
        OSError,
        ValueError,
        tokenize.TokenError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Repository checks failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

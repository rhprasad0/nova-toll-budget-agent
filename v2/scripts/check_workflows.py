"""Check shell/workflows and reject stale, narrowly scoped compatibility exceptions."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
# actionlint 1.7.12 predates these supported GitHub fields. Preserve the release
# protections until upstream models them; an unused entry fails on upgrades.
# https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
# https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency
QUEUE_MESSAGE = 'unexpected key "queue" for "concurrency" section. expected one of "cancel-in-progress", "group"'
JOB_TYPE = "{check_run_id: number; container: {id: string; network: string}; services: {string => {id: string; network: string; ports: {string => string}}}; status: string}"
COMPATIBILITY: dict[str, dict[str, str]] = {
    **{
        f".github/workflows/{name}": {QUEUE_MESSAGE: "queue: max"}
        for name in (
            "v2-development-delivery.yml",
            "v2-production-release.yml",
            "v2-production-plan.yml",
            "v2-production-recovery.yml",
        )
    },
    ".github/workflows/v2-development-delivery-privileged.yml": {
        QUEUE_MESSAGE: "queue: max"
    },
    ".github/workflows/v2-development-migrations.yml": {QUEUE_MESSAGE: "queue: max"},
    ".github/workflows/v2-development-plan.yml": {
        'property "result" is not defined in object type {outputs: {}}': "${{ jobs.plan.result }}",
        **{
            f'property "{name}" is not defined in object type {JOB_TYPE}': "${{ job."
            + name
            + " }}"
            for name in (
                "workflow_repository",
                "workflow_sha",
                "workflow_ref",
                "workflow_file_path",
            )
        },
    },
}
DIRECTIVE = re.compile(r"^\s*# shellcheck disable=(SC[0-9]{4}(?:,SC[0-9]{4})*)\s*$")
Diagnostic = dict[str, object]


def check_command(
    command: Sequence[str], content: str | None = None
) -> list[Diagnostic]:
    """Read machine output, failing closed on tool or output errors."""
    result = subprocess.run(
        command,
        input=content,
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
        env={
            key: value for key, value in os.environ.items() if key != "SHELLCHECK_OPTS"
        },
    )
    if result.returncode not in (0, 1):
        raise ValueError(
            result.stderr or result.stdout or f"Checker exited {result.returncode}"
        )
    # actionlint emits JSON once per file; ShellCheck emits one array.
    diagnostics: list[Diagnostic] = []
    for line in result.stdout.splitlines():
        decoded: object = json.loads(line)
        if decoded is None:
            continue
        if not isinstance(decoded, list):
            raise ValueError("Checker did not return a diagnostic array")
        for entry in cast(list[object], decoded):
            if not isinstance(entry, dict):
                raise ValueError("Checker returned an invalid diagnostic")
            diagnostics.append(cast(Diagnostic, entry))
    if result.returncode and not diagnostics:
        raise ValueError(result.stderr or "Checker failed without diagnostics")
    return diagnostics


def filter_workflow_diagnostics(
    diagnostics: Sequence[Diagnostic], paths: Sequence[str]
) -> list[str]:
    """Allow only known upstream gaps on their original valid source constructs."""
    expected = {
        (path, message) for path in paths for message in COMPATIBILITY.get(path, {})
    }
    matched: set[tuple[str, str]] = set()
    failures: list[str] = []
    for item in diagnostics:
        path = str(item.get("filepath", "")).removeprefix("./")
        message = str(item.get("message", ""))
        key = (path, message)
        line = int(str(item.get("line", 0)))
        if key in expected:
            source = (ROOT / path).read_text().splitlines()
            required = COMPATIBILITY[path][message]
            if (
                0 < line <= len(source)
                and required in source[line - 1]
                and (required != "queue: max" or source[line - 1].strip() == required)
            ):
                matched.add(key)
                continue
        failures.append(f"{path}:{line}: {message}")
    failures.extend(
        f"{path}: unused actionlint compatibility exception: {message}"
        for path, message in sorted(expected - matched)
    )
    return failures


def unused_directives(
    path: str, command: Sequence[str], baseline: Sequence[Diagnostic], *, workflow: bool
) -> list[str]:
    """Remove each directive in memory to prove its diagnostic still exists."""
    lines = (ROOT / path).read_text().splitlines(keepends=True)
    failures: list[str] = []
    for index, line in enumerate(lines):
        match = DIRECTIVE.fullmatch(line.rstrip("\n"))
        if match is None:
            continue
        preceding = next(
            (
                previous.strip()
                for previous in reversed(lines[:index])
                if previous.strip() and not previous.lstrip().startswith("#")
            ),
            "",
        )
        if not preceding or (workflow and re.fullmatch(r"run:\s*[|>][+-]?", preceding)):
            failures.append(
                f"{path}:{index + 1}: file-leading ShellCheck exceptions are forbidden"
            )
            continue
        # Keep all line numbers intact and leave the real file/index untouched.
        unsuppressed = "".join([*lines[:index], "\n", *lines[index + 1 :]])
        diagnostics = check_command(command, unsuppressed)
        for code in match[1].split(","):

            def count(items: Sequence[Diagnostic], selected_code: str = code) -> int:
                if workflow:
                    return sum(
                        f": {selected_code}:" in str(item.get("message", ""))
                        for item in items
                    )
                return sum(
                    str(item.get("code", "")) == selected_code[2:] for item in items
                )

            if count(diagnostics) <= count(baseline):
                failures.append(
                    f"{path}:{index + 1}: unused ShellCheck exception {code}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell-scripts", action="store_true")
    parser.add_argument("--actionlint")
    parser.add_argument("--shellcheck", required=True)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    shell = cast(bool, args.shell_scripts)
    shellcheck = cast(str, args.shellcheck)
    actionlint = cast(str | None, args.actionlint)
    paths = [str(Path(path)) for path in cast(list[str], args.files)]
    if not shell and actionlint is None:
        parser.error("--actionlint is required for workflows")
    base = (
        [shellcheck, "--norc", "--external-sources", "--format=json"]
        if shell
        else [
            cast(str, actionlint),
            "-config-file",
            "/dev/null",
            "-shellcheck",
            shellcheck,
            "-format",
            "{{json .}}",
        ]
    )
    failures: list[str] = []
    try:
        for path in paths:
            command = [*base, "./" + path]
            baseline = check_command(command)
            if shell:
                failures.extend(
                    f"{path}:{item.get('line')}: SC{item.get('code')}: {item.get('message')}"
                    for item in baseline
                )
                stdin_command = [*base, "--shell=bash", "-"]
            else:
                failures.extend(filter_workflow_diagnostics(baseline, [path]))
                stdin_command = [*base, "-stdin-filename", path, "-"]
            failures.extend(
                unused_directives(path, stdin_command, baseline, workflow=not shell)
            )
    except (ValueError, OSError) as error:
        failures.append(str(error))
    for failure in failures:
        print(failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())

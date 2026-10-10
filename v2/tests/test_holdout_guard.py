"""Synthetic hook payloads only; no private corpus reads or model calls."""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import holdout_guard as guard

SOURCE = Path(__file__).resolve().parents[2]
PREFIX = "uv run python -m eval.golden_run"


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    v2 = tmp_path / "checkout/v2"
    hidden = tmp_path / "private-suite"
    v2.mkdir(parents=True)
    hidden.mkdir()
    (v2 / "alias").symlink_to(hidden, target_is_directory=True)
    monkeypatch.setattr(guard, "V2", v2)
    monkeypatch.setattr(guard, "PROTECTED", hidden)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SYNTHETIC_HIDDEN", str(hidden))
    return v2, hidden


def payload(
    session_cwd: Path, tool: str = "Bash", **arguments: object
) -> dict[str, Any]:
    return {
        "session_id": "synthetic-parent",
        "cwd": str(session_cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": arguments,
    }


@pytest.mark.parametrize(
    "command",
    [
        "cat {hidden}/cases.jsonl",
        "rg secret {hidden}",
        "ls {hidden}",
        "find {hidden}",
        "rm -rf {hidden}/run",
        "cp {hidden}/cases.jsonl /tmp/public",
        "cat ../../private-suite/cases.jsonl",
        "cat ~/private-suite/cases.jsonl",
        "cat $SYNTHETIC_HIDDEN/cases.jsonl",
        "cat alias/cases.jsonl",
        "cat --file=alias/cases.jsonl",
        "tar -cf /tmp/public.tar -C{hidden} .",
        "tar -cf /tmp/public.tar -C../../private-suite .",
        "tar -cf /tmp/public.tar -Calias .",
        "tar -xC{hidden} -f /tmp/public.tar",
        "python -c \"open('{hidden}/cases.jsonl').read()\"",
        "bash -c 'cat {hidden}/cases.jsonl'",
        "cd .. && cat ../private-suite/cases.jsonl",
        "cd ..\ncat ../private-suite/cases.jsonl",
        "pushd ..; cat ../private-suite/cases.jsonl",
        "cd {hidden} && pwd",
        "ls {parent}",
        "find {parent}",
        "cat {parent}/private-*/cases.jsonl",
        "cat {parent}/private-suit?/cases.jsonl",
        "cat {parent}/*/cases.jsonl",
    ],
)
def test_direct_shell_access(layout: tuple[Path, Path], command: str) -> None:
    v2, hidden = layout
    assert guard.blocked(
        payload(v2, command=command.format(hidden=hidden, parent=hidden.parent))
    )


@pytest.mark.parametrize(
    "command",
    [
        "cat $'{hidden}/cases.jsonl'",
        "cat $'\\x2f{relative}/cases.jsonl'",
        "cat $'\\057{relative}/cases.jsonl'",
        "cat $'\\u002f{relative}/cases.jsonl'",
        "cat $'alias/cases.jsonl'",
        "cat $\\\n'alias/cases.jsonl'",
        "bash -c \"cat $'alias/cases.jsonl'\"",
        "printf '%s' $'ordinary\\ntext'",
        "echo 'quoted' $'ordinary'",
        "echo \"$'ordinary'\"",
        "echo \"$(echo $'ordinary')\"",
        "true # it'\necho $'ordinary' # '",
        "cat <<'EOF'\nordinary$'\nEOF",
        "bash -c 'echo $'\"'\"'ordinary'\"'\"",
        "bash -c \"echo \\$'ordinary'\"",
    ],
)
def test_ansi_c_quoting_is_denied(
    layout: tuple[Path, Path], command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    v2, hidden = layout
    command = command.format(hidden=hidden, relative=str(hidden).lstrip("/"))
    event = payload(v2, command=command)
    assert guard.blocked(event)
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    monkeypatch.setattr(sys, "stdout", output)
    guard.main()
    assert json.loads(output.getvalue()) == guard.DENIAL


@pytest.mark.parametrize("directory", ["session", "workdir", "cwd"])
def test_protected_working_directory(layout: tuple[Path, Path], directory: str) -> None:
    v2, hidden = layout
    event = payload(hidden if directory == "session" else v2, command="pwd")
    if directory != "session":
        event["tool_input"][directory] = str(hidden)
    assert guard.blocked(event)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("mcp__filesystem__read_file", {"path": "alias/cases.jsonl"}),
        (
            "mcp__filesystem__read_multiple_files",
            {"paths": ["public", "alias/cases.jsonl"]},
        ),
        ("mcp__filesystem__list_directory", {"path": "../../private-suite"}),
        ("mcp__filesystem__search_files", {"path": "alias", "pattern": "*"}),
        ("mcp__filesystem__write_file", {"path": "alias/new", "content": "synthetic"}),
        (
            "mcp__filesystem__move_file",
            {"source": "public", "destination": "alias/new"},
        ),
        ("view_image", {"path": "alias/image.png"}),
        ("Read", {"file_path": "~/private-suite/cases.jsonl"}),
        ("Edit", {"file_path": "alias/cases.jsonl"}),
        ("Write", {"file_path": "alias/new", "content": "synthetic"}),
        ("Glob", {"pattern": "**/*.jsonl", "path": "alias"}),
        ("Grep", {"pattern": "case_id", "path": "../../private-suite"}),
        ("NotebookEdit", {"notebook_path": "alias/notes.ipynb", "new_source": ""}),
        ("Agent", {"description": "Inspect", "prompt": "Read alias/cases.jsonl"}),
        (
            "apply_patch",
            {
                "command": "*** Begin Patch\n*** Delete File: alias/cases.jsonl\n*** End Patch"
            },
        ),
        (
            "apply_patch",
            {
                "command": "*** Begin Patch\n*** Update File: public\n*** Move to: alias/new\n*** End Patch"
            },
        ),
        ("mcp__filesystem__read_file", {"request": {"files": ["alias/cases.jsonl"]}}),
        # Whole values that name an ancestor can traverse the private tree.
        ("Grep", {"pattern": "case_id", "path": "..\x2f.."}),
        ("Glob", {"pattern": "..\x2f..\x2f*\x2fcases.jsonl"}),
    ],
)
def test_file_tools(
    layout: tuple[Path, Path], tool: str, arguments: dict[str, object]
) -> None:
    v2, _ = layout
    assert guard.blocked(payload(v2, tool, **arguments))


def test_symlink_and_lexical_paths(layout: tuple[Path, Path]) -> None:
    v2, hidden = layout
    (hidden / "public-link").symlink_to(v2, target_is_directory=True)
    assert guard.blocked(payload(v2, command="cat alias/../private-suite/cases.jsonl"))
    assert guard.blocked(payload(v2, command=f"cat {hidden}/public-link/public"))
    assert guard.blocked(payload(hidden / "public-link", command="pwd"))
    assert guard.blocked(
        payload(v2, command="pwd", workdir=str(hidden / "public-link"))
    )
    assert guard.blocked(payload(v2, "Read", path=f"file://{hidden}/cases.jsonl"))
    assert guard.blocked(payload(v2, "Read", path="alias", workdir=str(v2)))
    assert not guard.blocked(payload(v2, command=f"cat {hidden}-public/file"))
    (v2 / "--alias").symlink_to(hidden, target_is_directory=True)
    assert guard.blocked(payload(v2, command="cat -- --alias/cases.jsonl"))
    assert guard.blocked(
        payload(v2, command=f"{PREFIX} aggregate --output {hidden}/public-link")
    )


@pytest.mark.parametrize("mode", ["run", "aggregate", "training"])
@pytest.mark.parametrize("child", [False, True])
def test_trusted_commands(layout: tuple[Path, Path], mode: str, child: bool) -> None:
    v2, hidden = layout
    if mode == "aggregate":
        command = f"{PREFIX} aggregate --output {hidden}/checkpoint"
    else:
        command = (
            f"{PREFIX} run --output "
            f"{hidden / 'checkpoint' if mode == 'run' else v2 / 'eval/private/next'} "
            f"--calibration {v2}/approved.json --budget-usd 25 "
            f"--prior-run {hidden}/previous --workers 16 --trials-per-case 1"
        )
        if mode == "run":
            command += f" --corpus {hidden}/inputs"
    for suffix in ("", " > public.json", " >> 'public summary.json'"):
        event = payload(v2.parent, command=command + suffix, workdir=str(v2))
        if child:
            event.update(agent_id="synthetic-child", agent_type="synthetic-reviewer")
        assert not guard.blocked(event)


def test_literal_variants(layout: tuple[Path, Path]) -> None:
    v2, hidden = layout
    command = (
        f"{PREFIX} run \\\n--corpus='{hidden}/inputs' --output='{hidden}/new run' "
        "--calibration='approved receipt.json' --no-budget-limit "
        "--workers=1 --trials-per-case=3"
    )
    assert not guard.blocked(payload(v2, cmd=command))
    assert not guard.blocked(
        payload(v2, command=f"{PREFIX} aggregate --output alias/checkpoint")
    )


@pytest.mark.parametrize(
    "command",
    [
        "{aggregate}; cat {hidden}/cases.jsonl",
        "{aggregate} && pwd",
        "{aggregate}\ntrue",
        "{aggregate} | tee public.json",
        "{aggregate} > public.json; true",
        "{aggregate} > public.json 2>&1",
        "{aggregate} > {hidden}/feedback.json",
        "{aggregate} > alias/feedback.json",
        "{aggregate} > public.json > other.json",
        "{aggregate} > $(cat {hidden}/cases.jsonl)",
        "{aggregate} > `pwd`",
        "{aggregate} > public-*.json",
        "{aggregate} --unknown true",
        "{aggregate} --output public",
        "{aggregate} --budget-usd 25",
        "{aggregate} --output",
        "{aggregate} --output=",
        "{aggregate} # comment",
        "({aggregate})",
        "env {aggregate}",
        "PYTHONPATH=other {aggregate}",
        "cd {v2} && {aggregate}",
        "uv run --python python3 -m eval.golden_run aggregate --output {hidden}/checkpoint",
        "uv run python -c 'print(1)' --output {hidden}/checkpoint",
        "python -m eval.golden_run aggregate --output {hidden}/checkpoint",
        "{prefix} render --output {hidden}/checkpoint",
        "{prefix} calibrate --holdout {hidden}/inputs --output {hidden}/new",
        "{run} --workers 17",
        "{run} --workers bad",
        "{run} --trials-per-case 2",
        "{run} --budget-usd NaN",
        "{run} --budget-usd inf",
        "{run} --budget-usd -1",
        "{run} --budget-usd 25 --no-budget-limit",
        "{run} --cases hidden-case",
        "{prefix} run --corpus {hidden}/inputs --output public --calibration approved.json",
        "{prefix} run --output public --calibration {hidden}/calibration --prior-run {hidden}/last",
        "{prefix} run --output {hidden}/new --calibration approved.json",
        "{prefix} run --corpus {hidden}/inputs --output {hidden}/new",
        "{prefix} aggregate --output $SYNTHETIC_HIDDEN/checkpoint",
    ],
)
def test_runner_injection_and_invalid_flags(
    layout: tuple[Path, Path], command: str
) -> None:
    v2, hidden = layout
    aggregate = f"{PREFIX} aggregate --output {hidden}/checkpoint"
    run = (
        f"{PREFIX} run --corpus {hidden}/inputs --output {hidden}/new "
        "--calibration approved.json"
    )
    command = command.format(
        aggregate=aggregate, run=run, prefix=PREFIX, v2=v2, hidden=hidden
    )
    assert guard.blocked(payload(v2, command=command))


@pytest.mark.parametrize("background", [False, True])
def test_trusted_command_with_claude_bash_fields(
    layout: tuple[Path, Path], background: bool
) -> None:
    v2, hidden = layout
    event = payload(
        v2,
        command=f"{PREFIX} aggregate --output {hidden}/checkpoint",
        description="Aggregate checkpoint",
        timeout=600000,
        run_in_background=background,
    )
    assert not guard.blocked(event)
    for extra in ({"run_in_background": "true"}, {"dangerouslyDisableSandbox": True}):
        event["tool_input"] = {**event["tool_input"], **extra}
        assert guard.blocked(event)


def test_runner_requires_checkout_and_no_overrides(layout: tuple[Path, Path]) -> None:
    v2, hidden = layout
    command = f"{PREFIX} aggregate --output {hidden}/checkpoint"
    assert guard.blocked(payload(v2.parent, command=command))
    assert guard.blocked(payload(v2, command=command, shell="/tmp/custom-shell"))
    assert guard.blocked(payload(v2, command=command, env={"PYTHONPATH": "/tmp/other"}))
    assert guard.blocked(payload(v2, command=command, tty=True))


@pytest.mark.parametrize(
    "event",
    [None, [], {}, {"hook_event_name": "PostToolUse"}],
)
def test_malformed_payloads(event: object, monkeypatch: pytest.MonkeyPatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    monkeypatch.setattr(sys, "stdout", output)
    guard.main()
    assert json.loads(output.getvalue()) == guard.DENIAL


@pytest.mark.parametrize("value", ["{", "null trailing", '{"cwd": "\u0000"}'])
def test_malformed_json(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(value))
    monkeypatch.setattr(sys, "stdout", output)
    guard.main()
    assert json.loads(output.getvalue()) == guard.DENIAL


def test_parser_errors_are_generic(
    layout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    v2, hidden = layout
    for event in (
        payload(v2, command=f"cat '{hidden}/secret"),
        payload(v2, command="cd --"),
        payload(v2, command=123),
        payload(v2, command="pwd", workdir=None),
        payload(v2, command="pwd", cmd="cat alias/cases.jsonl"),
        payload(v2, command="pwd", cwd=str(v2), workdir=str(hidden)),
        payload(v2, "Read", path="\x00"),
        {**payload(v2, command="pwd"), "tool_input": None},
        {**payload(v2, command="pwd"), "cwd": "relative"},
    ):
        output = io.StringIO()
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        monkeypatch.setattr(sys, "stdout", output)
        guard.main()
        assert json.loads(output.getvalue()) == guard.DENIAL
        assert str(hidden) not in output.getvalue()
        assert output.getvalue().strip().startswith("{")


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("Bash", {"command": "git status --short"}),
        ("Bash", {"command": "tar -cf /tmp/public.tar -Cpublic ."}),
        ("Bash", {"cmd": "rg --files . && cat pyproject.toml"}),
        ("Bash", {"command": "uv run pytest tests/test_holdout_guard.py"}),
        (
            "Bash",
            {
                "command": f"{PREFIX} run --output eval/private/training --calibration approved.json"
            },
        ),
        ("Bash", {"command": "cd .. && git diff\npwd"}),
        ("Bash", {"command": "python - <<'PY'\nprint('synthetic')\nPY"}),
        # Slashes split from code, regexes and prose are not path arguments.
        ("Bash", {"command": "sed 's\x2f=.*\x2f=x\x2f' notes.txt"}),
        ("Bash", {"command": "python -c 'print(7 \x2f\x2f 2)'"}),
        ("Bash", {"command": "python -c 'print(f\"{a}\x2f{b}\")'"}),
        ("Bash", {"command": "grep -E 'fixture$' notes.txt 'other$'"}),
        ("Bash", {"command": "echo \x7enosuchuser-synthetic"}),
        # Accepted gap: an ancestor inside a nested program is not a whole argument.
        ("Bash", {"command": "bash -c 'find ..\x2f..'"}),
        ("Write", {"file_path": "public.css", "content": "\x2f* note *\x2f\nb {}"}),
        (
            "AskUserQuestion",
            {"questions": [{"question": "List \x7e or \x24HOME, then \x2f?"}]},
        ),
        ("Read", {"file_path": "pyproject.toml"}),
        (
            "apply_patch",
            {
                "command": "*** Begin Patch\n*** Update File: public.py\n@@\n-a\n+b\n*** End Patch"
            },
        ),
        (
            "update_plan",
            {"plan": [{"step": "Check ordinary work", "status": "pending"}]},
        ),
    ],
)
def test_ordinary_operations(
    layout: tuple[Path, Path], tool: str, arguments: dict[str, object]
) -> None:
    v2, _ = layout
    assert not guard.blocked(payload(v2, tool, **arguments))


def test_registration_from_root_subdirectory_and_worktree(tmp_path: Path) -> None:
    config = json.loads((SOURCE / ".claude/settings.json").read_text())
    groups = config["hooks"]["PreToolUse"]
    assert len(groups) == 1 and groups[0]["matcher"] == "*"
    handlers = groups[0]["hooks"]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler["type"] == "command" and not handler.get("async", False)
    # Claude Code lets a crashed or timed-out hook proceed unless told to block.
    assert handler["onFailure"] == "block"
    root = tmp_path / "repo"
    script = root / "v2/scripts/holdout_guard.py"
    script.parent.mkdir(parents=True)
    hidden = tmp_path / "synthetic-holdout"
    script.write_text(
        (SOURCE / "v2/scripts/holdout_guard.py")
        .read_text()
        .replace(str(guard.PROTECTED), str(hidden))
    )
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=environment)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, env=environment)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "Synthetic",
        ],
        check=True,
        env=environment,
    )
    worktree = root / ".worktrees/guard"
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(worktree)],
        check=True,
        capture_output=True,
        env=environment,
    )
    for directory in (root, root / "v2", worktree, worktree / "v2"):
        checkout = directory.parent if directory.name == "v2" else directory
        project = {**environment, "CLAUDE_PROJECT_DIR": str(checkout)}
        event = payload(directory, command="git status --short")
        result = subprocess.run(
            ["/bin/sh", "-c", handler["command"]],
            cwd=directory,
            input=json.dumps(event),
            text=True,
            capture_output=True,
            check=True,
            env=project,
        )
        assert result.stdout == result.stderr == ""
        event = payload(
            directory, command=f"cat {shlex.quote(str(hidden / 'synthetic'))}"
        )
        result = subprocess.run(
            ["/bin/sh", "-c", handler["command"]],
            cwd=directory,
            input=json.dumps(event),
            text=True,
            capture_output=True,
            check=True,
            env=project,
        )
        assert json.loads(result.stdout) == guard.DENIAL
        assert result.stderr == ""
        # Exercise the real command and module location without reading a holdout.
        event = payload(
            checkout / "v2",
            command=f"{PREFIX} aggregate --output {shlex.quote(str(hidden / 'synthetic'))}",
        )
        result = subprocess.run(
            ["/bin/sh", "-c", handler["command"]],
            cwd=directory,
            input=json.dumps(event),
            text=True,
            capture_output=True,
            check=True,
            env=project,
        )
        assert result.stdout == result.stderr == ""
    # Without a project directory the script path is missing, so the hook fails.
    result = subprocess.run(
        ["/bin/sh", "-c", handler["command"]],
        cwd=root,
        input=json.dumps(payload(root, command="git status --short")),
        text=True,
        capture_output=True,
        env={k: v for k, v in environment.items() if k != "CLAUDE_PROJECT_DIR"},
    )
    assert result.returncode != 0

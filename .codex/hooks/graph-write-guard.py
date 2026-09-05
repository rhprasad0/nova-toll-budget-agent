#!/usr/bin/env python3
"""Fail-closed write boundary for the project-graph child roles."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


GUARDED_ROLES = frozenset({"explorer", "pre_checker", "builder", "checker"})
GIT_TIMEOUT = 2
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
PATCH_HEADERS = (
    "*** Add File: ",
    "*** Update File: ",
    "*** Delete File: ",
    "*** Move to: ",
)
NATIVE_PATCH_WHITESPACE = (
    "\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
SHELL_EXPANSION_RE = re.compile(r"[$`*?\[\]{};&|]")


class GuardError(Exception):
    """An input or repository state that must fail closed."""


def _run_git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GuardError(f"Git lookup failed: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or "unknown Git error"
        raise GuardError(f"Git lookup failed: {detail}")
    return result.stdout.strip()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _script_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _repo_context(cwd: Path) -> dict[str, Any]:
    cwd = cwd.resolve(strict=False)
    _run_git(cwd, "rev-parse", "--show-toplevel")
    common_text = _run_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = Path(common_text).resolve()
    primary = common.parent
    worktree_root_path = primary / ".worktrees"
    worktree_root = worktree_root_path.resolve(strict=False)
    if worktree_root != worktree_root_path:
        raise GuardError("project .worktrees directory must not be a symlink")
    assignments = worktree_root / ".graph-assignments"
    listed = _worktrees(cwd)
    return {
        "common": common,
        "primary": primary,
        "worktree_root": worktree_root,
        "assignments": assignments,
        "listed": listed,
    }


def _worktrees(cwd: Path) -> frozenset[Path]:
    output = _run_git(cwd, "worktree", "list", "--porcelain")
    paths: set[Path] = set()
    for line in output.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line.removeprefix("worktree ")).resolve())
    if not paths:
        raise GuardError("Git returned no worktrees")
    return frozenset(paths)


def _record_path(context: dict[str, Any], agent_id: str) -> Path:
    if not isinstance(agent_id, str) or not ID_RE.fullmatch(agent_id):
        raise GuardError("agent_id must be a non-empty safe identifier")
    return context["assignments"] / f"{agent_id}.json"


def _assignment_target(context: dict[str, Any], worktree: Path) -> Path:
    if not worktree.is_absolute():
        raise GuardError("assigned worktree must be absolute")
    target = worktree.resolve(strict=False)
    if target == context["primary"]:
        raise GuardError(f"assigned path {target} is the main checkout")
    if not _inside(target, context["worktree_root"]):
        raise GuardError(
            f"assigned path {target} must be under {context['worktree_root']}"
        )
    if target == context["assignments"].resolve(strict=False) or _inside(
        target, context["assignments"].resolve(strict=False)
    ):
        raise GuardError(f"assigned path {target} is the assignment registry")
    if not target.is_dir():
        raise GuardError(f"assigned path {target} is not a live worktree directory")
    if target not in context["listed"]:
        raise GuardError(f"assigned path {target} is not a live worktree of this repository")
    try:
        metadata = _run_git(
            target,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-common-dir",
        ).splitlines()
    except GuardError as exc:
        raise GuardError(f"assigned path {target} is not a usable Git worktree: {exc}") from exc
    if len(metadata) != 2 or Path(metadata[0]).resolve() != target or Path(metadata[1]).resolve() != context["common"]:
        raise GuardError(f"assigned path {target} Git metadata does not match this repository")
    return target


def _record_data(agent_id: str, role: str, worktree: Path, context: dict[str, Any]) -> dict[str, str]:
    return {
        "agent_id": agent_id,
        "role": role,
        "worktree": str(worktree),
        "repository": str(context["common"]),
    }


def _read_record(record_path: Path) -> dict[str, str]:
    if record_path.is_symlink() or not record_path.is_file():
        raise GuardError("assignment record is missing or is not a regular file")
    try:
        with record_path.open(encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"assignment record is invalid: {exc}") from exc
    required = {"agent_id", "role", "worktree", "repository"}
    if (
        not isinstance(record, dict)
        or set(record) != required
        or not all(isinstance(record.get(key), str) for key in required)
    ):
        raise GuardError("assignment record is missing required fields")
    return record


def register(agent_id: str, role: str, worktree: str, cwd: Path | None = None) -> None:
    if role not in GUARDED_ROLES:
        raise GuardError(f"role {role!r} is not guarded")
    context = _repo_context(cwd or _script_repo_root())
    target = _assignment_target(context, Path(worktree))
    registry = context["assignments"]
    if registry.is_symlink():
        raise GuardError("assignment registry must not be a symlink")
    if not _inside(registry.resolve(strict=False), context["worktree_root"]):
        raise GuardError("assignment registry is outside the project .worktrees directory")
    try:
        registry.mkdir(parents=True, exist_ok=True)
        record_path = _record_path(context, agent_id)
        record = _record_data(agent_id, role, target, context)
        try:
            with record_path.open("x", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True)
                handle.write("\n")
        except FileExistsError:
            if _read_record(record_path) != record:
                raise GuardError("agent assignment already exists with different identity")
    except OSError as exc:
        raise GuardError(f"could not write assignment registry: {exc}") from exc


def _validate_assignment(agent_id: str, role: str, context: dict[str, Any]) -> Path:
    try:
        record = _read_record(_record_path(context, agent_id))
    except GuardError as exc:
        raise GuardError(
            f"agent_id {agent_id!r} is not registered; parent must register the native ID before tool use ({exc})"
        ) from exc
    if record["agent_id"] != agent_id:
        raise GuardError("assignment record agent_id does not match the hook agent_id")
    if record["role"] != role:
        raise GuardError("hook agent_type does not match the registered role")
    if record["repository"] != str(context["common"]):
        raise GuardError("assignment belongs to a different repository")
    target = _assignment_target(context, Path(record["worktree"]))
    if str(target) != record["worktree"]:
        raise GuardError("assignment worktree is not canonical")
    return target


def _deny(reason: str, event: str = "PreToolUse") -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def _subagent_start(payload: Any) -> None:
    if not isinstance(payload, dict):
        _subagent_stop("SubagentStart payload must be a JSON object")
        return
    role = payload.get("agent_type")
    if role not in GUARDED_ROLES:
        return
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        _subagent_stop("guarded child has no native agent_id; do not use tools, ask the parent to retry")
        return
    context = (
        f"Project-graph guard identity: your native Codex agent_id is {agent_id}. "
        "Report this exact ID to the parent before using any tool. Wait for the parent's "
        "explicit registration acknowledgement before calling tools; the spawn task name "
        "is not an identity and must not be substituted."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": context}}))


def _subagent_stop(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SubagentStart",
                    "additionalContext": (
                        f"Project-graph guard could not activate this child: {reason}. "
                        "Do not use tools; report the problem to the parent."
                    ),
                }
            }
        )
    )


def _patch_paths(command: str) -> list[str]:
    paths: list[str] = []
    for line in command.split("\n"):
        line = line.strip(NATIVE_PATCH_WHITESPACE)
        for header in PATCH_HEADERS:
            if line.startswith(header):
                path = line[len(header) :]
                if path:
                    paths.append(path)
                break
    return paths


def _validate_patch(command: str, payload_cwd: str, assignment: Path) -> None:
    paths = _patch_paths(command)
    if not paths:
        raise GuardError("apply_patch must contain at least one recognized destination header")
    cwd = Path(payload_cwd).resolve(strict=False)
    for raw_path in paths:
        candidate = (Path(raw_path) if Path(raw_path).is_absolute() else cwd / raw_path).resolve(
            strict=False
        )
        if not _inside(candidate, assignment):
            raise GuardError(
                f"apply_patch destination {candidate} (from {raw_path}) is outside assigned worktree {assignment}"
            )
        if candidate == Path(__file__).resolve():
            raise GuardError(f"apply_patch cannot replace the active guard source {candidate}")


# ponytail: only leading cd is inspected; full shell write enforcement needs filesystem sandboxing.
def _validate_bash(command: str, assignment: Path) -> None:
    if not command.startswith("cd "):
        raise GuardError("Bash command must begin with literal `cd <absolute-worktree-path> &&`")
    leading = command.partition("&&")[0]
    if "\\" in leading or any(ord(char) < 32 or ord(char) == 127 for char in leading):
        raise GuardError("Bash cd prefix cannot contain escapes, control characters, or continuations")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.commenters = ""
        lexer.whitespace_split = True
        parts = [next(lexer) for _ in range(3)]
    except ValueError as exc:
        raise GuardError(f"Bash command has an invalid leading cd: {exc}") from exc
    except StopIteration:
        raise GuardError("Bash command must begin with literal `cd <absolute-worktree-path> &&`")
    if len(parts) < 3 or parts[0] != "cd" or parts[2] != "&&":
        raise GuardError("Bash command must begin with literal `cd <absolute-worktree-path> &&`")
    destination_text = parts[1]
    if not destination_text.startswith("/") or SHELL_EXPANSION_RE.search(destination_text):
        raise GuardError("Bash cd destination must be a literal absolute path")
    destination = Path(destination_text).resolve(strict=False)
    if not _inside(destination, assignment):
        raise GuardError(
            f"Bash cd destination {destination} is outside assigned worktree {assignment}"
        )


def _pre_tool_use(payload: Any) -> None:
    if not isinstance(payload, dict):
        _deny("PreToolUse payload must be a JSON object")
        return
    role = payload.get("agent_type")
    if not isinstance(role, str) or role not in GUARDED_ROLES:
        return
    agent_id = payload.get("agent_id")
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    payload_cwd = payload.get("cwd")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise GuardError("guarded PreToolUse requires a registered agent_id")
    if not isinstance(tool_name, str) or not tool_name:
        raise GuardError("guarded PreToolUse requires tool_name")
    if not isinstance(tool_input, dict):
        raise GuardError("guarded PreToolUse requires tool_input")
    if not isinstance(payload_cwd, str) or not payload_cwd:
        raise GuardError("guarded PreToolUse requires cwd for destination validation")
    assignment = _validate_assignment(agent_id, role, _repo_context(_script_repo_root()))
    command = tool_input.get("command")
    if tool_name in {"Bash", "apply_patch"} and not isinstance(command, str):
        raise GuardError(f"guarded {tool_name} call requires tool_input.command")
    if tool_name == "Bash":
        _validate_bash(command, assignment)
    elif tool_name == "apply_patch":
        _validate_patch(command, payload_cwd, assignment)


def _load_json() -> Any:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise GuardError(f"hook input is malformed JSON: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "register":
        if len(argv) != 4:
            print("usage: graph-write-guard.py register <agent-id> <role> <absolute-worktree>", file=sys.stderr)
            return 2
        try:
            register(argv[1], argv[2], argv[3])
        except Exception as exc:
            print(f"registration denied: {exc}", file=sys.stderr)
            return 1
        return 0
    event = argv[0] if argv else "pre-tool-use"
    try:
        payload = _load_json()
        if event in {"subagent-start", "SubagentStart"}:
            _subagent_start(payload)
        elif event in {"pre-tool-use", "PreToolUse"}:
            _pre_tool_use(payload)
        else:
            raise GuardError(f"unknown hook event: {event}")
    except Exception as exc:
        if event in {"subagent-start", "SubagentStart"}:
            _subagent_stop(str(exc))
        else:
            _deny(str(exc), "PreToolUse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Claude Code PreToolUse guard; trusted golden_run commands own all private I/O."""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import cast

PROTECTED = Path("/home/ryan/Documents/tollchat-eval-holdout")
V2 = Path(__file__).resolve().parents[1]
DENIAL = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "Holdout access blocked. Use the trusted aggregate runner or report "
            "the blocked operation to the operator."
        ),
    }
}


def resolve(value: str, cwd: Path) -> Path:
    if not value or "\x00" in value:
        raise ValueError("invalid path")
    path = Path(os.path.expandvars(value)).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def protected(value: str, cwd: Path, *, ancestors: bool = False) -> bool:
    # Check the lexical path too: a symlink inside the tree is still private.
    expanded = Path(os.path.expandvars(value)).expanduser()
    lexical = Path(
        os.path.abspath(expanded if expanded.is_absolute() else cwd / expanded)
    )
    root = PROTECTED.resolve()
    return any(
        path.is_relative_to(base) or (ancestors and base.is_relative_to(path))
        for path in (lexical, resolve(value, cwd))
        for base in (PROTECTED, root)
    )


def strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in cast(dict[str, object], value).values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from strings(item)


def mentions_private(text: str, cwd: Path) -> bool:
    for candidate in (text, *re.split(r"[\s\"'`=,;(){}<>|]+", text)):
        if not candidate:
            continue
        candidate = candidate.removeprefix("file://")
        # Short options may attach paths after one letter or an option cluster.
        option = re.match(r"-[A-Za-z]+", candidate)
        if option and any(
            mentions_private(candidate[index:], cwd)
            for index in range(2, option.end() + 1)
            if candidate[index:]
        ):
            return True
        if protected(candidate, cwd, ancestors=True):
            return True
        if re.search(r"[*?\[]", candidate):
            prefix = re.split(r"[*?\[]", candidate, maxsplit=1)[0]
            if prefix and not prefix.endswith("/"):
                prefix = str(Path(prefix).parent)
            # A wildcard may traverse the private tree through an ancestor.
            if protected(prefix or ".", cwd, ancestors=True):
                return True
    return False


def shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(
        command.replace("\\\n", ""), posix=True, punctuation_chars=";&|<>()\n"
    )
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if not tokens:
        raise ValueError("empty command")
    return tokens


def shell_private(tokens: list[str], cwd: Path) -> bool:
    if protected(str(cwd), cwd):
        return True
    start = True
    directories = [cwd]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token and set(token) <= set(";&|()\n"):
            start = True
            continue
        if start and token in {"cd", "pushd"}:
            target = tokens[index] if index < len(tokens) else "~"
            index += 1
            if target == "--":
                target = tokens[index]
                index += 1
            if target == "-":
                target = os.environ.get("OLDPWD", "~")
            if mentions_private(target, cwd):
                return True
            cwd = resolve(target, cwd)
            directories.append(cwd)
            if protected(str(cwd), cwd):
                return True
            start = False
            continue
        elif start and token == "popd" and len(directories) > 1:
            directories.pop()
            cwd = directories[-1]
        if mentions_private(token, cwd):
            return True
        start = False
    return False


def trusted_runner(command: str, tokens: list[str], cwd: Path) -> bool:
    if cwd != V2 or tokens[:5] != ["uv", "run", "python", "-m", "eval.golden_run"]:
        return False
    # Quotes are fine; shell expansion, control flow and nested programs are not.
    if re.search(r"[$`;|&<(){}*?\[\]\n\r]", command.replace("\\\n", "")):
        return False
    if any(token in {">", ">>"} for token in tokens):
        if len(tokens) < 3 or tokens[-2] not in {">", ">>"}:
            return False
        if mentions_private(tokens[-1], cwd):
            return False
        tokens = tokens[:-2]
    if any(">" in token for token in tokens) or len(tokens) < 6:
        return False
    mode = tokens[5]
    if mode not in {"run", "aggregate"}:
        return False
    value_flags = {"--output"}
    if mode == "run":
        value_flags |= {
            "--corpus",
            "--calibration",
            "--budget-usd",
            "--prior-run",
            "--workers",
            "--trials-per-case",
        }
    flags: dict[str, str] = {}
    index = 6
    while index < len(tokens):
        flag, equal, value = tokens[index].partition("=")
        if flag in flags:
            return False
        if flag == "--no-budget-limit" and mode == "run" and not equal:
            flags[flag] = ""
        elif flag in value_flags:
            if not equal:
                index += 1
                if index >= len(tokens):
                    return False
                value = tokens[index]
            if not value or value.startswith("-"):
                return False
            flags[flag] = value
        else:
            return False
        index += 1
    if "--output" not in flags:
        return False
    for flag in {"--output", "--corpus", "--calibration", "--prior-run"} & flags.keys():
        if protected(flags[flag], cwd) and not resolve(flags[flag], cwd).is_relative_to(
            PROTECTED.resolve()
        ):
            return False
    if mode == "aggregate":
        return protected(flags["--output"], cwd)
    if "--calibration" not in flags:
        return False
    if "--budget-usd" in flags and "--no-budget-limit" in flags:
        return False
    if "--budget-usd" in flags:
        try:
            amount = float(flags["--budget-usd"])
        except ValueError:
            return False
        if not math.isfinite(amount) or amount < 0:
            return False
    if "--workers" in flags and flags["--workers"] not in {
        str(number) for number in range(1, 17)
    }:
        return False
    if "--trials-per-case" in flags and flags["--trials-per-case"] not in {"1", "3"}:
        return False
    hidden_corpus = protected(flags.get("--corpus", "eval/active/training"), cwd)
    hidden_output = protected(flags["--output"], cwd)
    if hidden_corpus:
        return hidden_output
    # A public training continuation may read only the private accounting chain.
    return (
        not hidden_output
        and not protected(flags["--calibration"], cwd, ancestors=True)
        and "--prior-run" in flags
        and protected(flags["--prior-run"], cwd)
    )


def blocked(payload: object) -> bool:
    if not isinstance(payload, dict):
        raise ValueError("invalid event")
    event = cast(dict[str, object], payload)
    if event.get("hook_event_name") != "PreToolUse":
        raise ValueError("invalid event")
    tool = event.get("tool_name")
    cwd_value = event.get("cwd")
    supplied = event.get("tool_input")
    if not isinstance(tool, str) or not tool or not isinstance(cwd_value, str):
        raise ValueError("invalid tool")
    if not Path(cwd_value).is_absolute() or not isinstance(supplied, dict):
        raise ValueError("invalid arguments")
    arguments = cast(dict[str, object], supplied)
    if {"cwd", "workdir"} <= arguments.keys() or {"command", "cmd"} <= arguments.keys():
        raise ValueError("ambiguous arguments")
    cwd_private = protected(cwd_value, Path.cwd())
    cwd = resolve(cwd_value, Path.cwd())
    for key in ("cwd", "workdir"):
        if key in arguments:
            directory = arguments[key]
            if not isinstance(directory, str):
                raise ValueError("invalid directory")
            cwd_private = protected(directory, cwd)
            cwd = resolve(directory, cwd)
    if cwd_private:
        return True
    if tool in {"Bash", "exec_command", "shell", "shell_command"}:
        command = arguments.get("command", arguments.get("cmd"))
        if not isinstance(command, str):
            raise ValueError("invalid command")
        # shlex cannot decode Bash ANSI-C escapes; deny this syntax entirely.
        if "$'" in command.replace("\\\n", ""):
            return True
        tokens = shell_tokens(command)
        other_private = any(
            mentions_private(value, cwd)
            for key, value in arguments.items()
            if key not in {"command", "cmd", "cwd", "workdir"}
            for value in strings(value)
        )
        if not shell_private(tokens, cwd) and not other_private:
            return False
        safe_keys = {
            "command",
            "cmd",
            "cwd",
            "workdir",
            "description",
            "timeout",
            "timeout_ms",
            "yield_time_ms",
            "max_output_tokens",
            "login",
            "tty",
            "run_in_background",
        }
        return not (
            set(arguments) <= safe_keys
            and not arguments.get("tty", False)
            and isinstance(arguments.get("run_in_background", False), bool)
            and trusted_runner(command, tokens, cwd)
        )
    return protected(str(cwd), cwd) or any(
        mentions_private(value, cwd) for value in strings(arguments)
    )


def main() -> None:
    try:
        deny = blocked(json.load(sys.stdin))
    except Exception:
        # Never expose payloads, paths or parser errors in hook output.
        deny = True
    if deny:
        print(json.dumps(DENIAL))


if __name__ == "__main__":
    main()

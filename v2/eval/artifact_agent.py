"""Bounded parent-side adapter for the exact packaged application."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

from eval import golden
from eval import golden_run as run


class Answer(str):
    stop_reason: str


class ArtifactAgent:
    def __init__(
        self,
        bundle: Path,
        api_key: str,
        case: golden.GoldenCase | None = None,
        attempt: run.Attempt | None = None,
        journal: run.Journal | None = None,
        messages: list[str] | None = None,
        expected: dict[str, Any] | None = None,
    ) -> None:
        self.case, self.attempt, self.journal = case, attempt, journal
        self.messages = messages if messages is not None else []
        self.replay = golden.Replay(case) if case else None
        self.reserved: float | None = None
        self.calls = 0
        self.buffer = b""
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                str(Path(__file__).with_name("artifact_worker.py")),
                str(bundle.resolve()),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
            cwd=bundle,
        )
        try:
            if self.receive() != {"event": "ready"}:
                raise run.StopRun("artifact_bootstrap")
            cases = golden.load_cases()
            self.send(
                {
                    "event": "init",
                    "api_key": api_key,
                    "points": json.loads(
                        (golden.ROOT / "prompt-points.json").read_text()
                    ),
                    "dates": {c.id: c.frozen_time.date().isoformat() for c in cases},
                }
            )
            value = self.receive()
            if value.get("event") != "identity":
                raise run.StopRun("artifact_identity")
            self.identity: dict[str, Any] = value["identity"]
            files = self.identity["imported_files"]
            if not all(
                any(name.startswith(prefix) for name in files)
                for prefix in ("agent/", "strands/", "openai/")
            ):
                raise run.StopRun("artifact_missing_imports")
            for filename, digest in files.items():
                path = (bundle / filename).resolve()
                if (
                    not path.is_relative_to(bundle.resolve())
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest
                ):
                    raise run.StopRun("artifact_import_hash")
            if expected is not None and self.identity != expected:
                raise run.StopRun("artifact_identity_changed")
        except BaseException:
            self.close()
            raise

    def send(self, value: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        data = (json.dumps(value, allow_nan=False) + "\n").encode()
        if len(data) > 2_000_000:
            raise run.StopRun("artifact_message_size")
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def receive(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        deadline = time.monotonic() + 90
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                if len(self.buffer) > 2_000_000 or not selector.select(
                    max(0, deadline - time.monotonic())
                ):
                    raise run.StopRun("artifact_protocol_timeout_or_size")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise run.StopRun("artifact_process_ended")
                self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        if len(line) > 2_000_000:
            raise run.StopRun("artifact_message_size")
        value: object = json.loads(line)
        if not isinstance(value, dict):
            raise run.StopRun("artifact_protocol")
        return cast(dict[str, Any], value)

    def __call__(self, message: str) -> Answer:
        case, attempt, journal = self.case, self.attempt, self.journal
        assert (
            case is not None
            and attempt is not None
            and journal is not None
            and self.replay is not None
        )
        self.send(
            {
                "event": "turn",
                "date": case.frozen_time.date().isoformat(),
                "message": message,
            }
        )
        for _ in range(100):
            event = self.receive()
            kind = event["event"]
            if kind == "answer":
                if self.reserved is not None:
                    raise run.StopRun("artifact_missing_usage")
                answer = Answer(event["text"])
                answer.stop_reason = event["stop_reason"]
                return answer
            if kind == "model_start":
                if self.reserved is not None:
                    raise run.StopRun("artifact_unsettled_call")
                if self.calls >= case.actor.max_turns + case.max_tool_calls + 2:
                    raise run.TaskFailure("model_call_budget")
                self.reserved = journal.reserve(attempt, "agent", event["input_bound"])
                self.calls += 1
                self.send({"event": "continue"})
            elif kind == "model_end":
                if self.reserved is None:
                    raise run.StopRun("artifact_unreserved_call")
                journal.finish(
                    attempt, "agent", self.reserved, event["usage"], event["seconds"]
                )
                self.reserved = None
                self.send({"event": "continue"})
            elif kind in {"requested", "tool"}:
                item = {
                    "turn": len(self.messages),
                    "name": event["name"],
                    "input": event["input"],
                }
                if kind == "requested":
                    attempt.requested_tools.append(item)
                    journal.append(
                        {"event": "tool_requested", "attempt": attempt.id, **item}
                    )
                    if len(attempt.requested_tools) > case.max_tool_calls:
                        attempt.checks.append("tool_budget")
                    if event["name"] not in {
                        "get_current_toll_price",
                        "get_annual_toll_ballpark",
                    }:
                        attempt.checks.append("unexpected_call")
                    if attempt.checks:
                        run.rejected_call(
                            attempt,
                            event["name"],
                            event["input"],
                            attempt.checks[0],
                            "Frozen evaluation rejected this call.",
                            journal,
                        )
                    self.send({"event": "continue", "allowed": not attempt.checks})
                else:
                    if attempt.checks or attempt.requested_tools.count(
                        item
                    ) <= attempt.attempted_tools.count(item):
                        raise run.StopRun("artifact_unapproved_tool")
                    attempt.attempted_tools.append(item)
                    try:
                        call = self.replay.call(
                            event["name"], event["input"], self.messages
                        )
                        attempt.turns[-1].calls.append(call)
                        journal.append(
                            {
                                "event": "tool_replayed",
                                "attempt": attempt.id,
                                "turn": len(self.messages),
                                "call": call.model_dump(),
                            }
                        )
                        result = (
                            call.result
                            if call.is_error
                            else {
                                "status": "success",
                                "content": [{"json": call.result}],
                            }
                        )
                    except ValueError as error:
                        attempt.checks.append(str(error))
                        result = run.rejected_call(
                            attempt,
                            event["name"],
                            event["input"],
                            str(error),
                            "Frozen replay rejected this call.",
                            journal,
                        )
                    self.send({"event": "continue", "result": result})
            else:
                raise run.StopRun("artifact_protocol_failure")
        raise run.StopRun("artifact_event_budget")

    def close(self) -> None:
        if (
            self.reserved is not None
            and self.journal is not None
            and self.attempt is not None
        ):
            self.journal.finish(self.attempt, "agent", self.reserved, None, 0)
            self.reserved = None
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.stdout:
            self.process.stdout.close()

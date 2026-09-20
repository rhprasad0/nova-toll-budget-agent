"""Credential-free ARM64 bundle smoke; canned provider, real packaged agent/SDK."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch


def child(bundle: Path) -> None:
    sys.path.insert(0, str(bundle.resolve()))
    from agent import toll_agent

    original = toll_agent._build_model
    fixture = json.loads(
        (Path(__file__).parents[1] / "eval/golden/fixtures/greenway.json").read_text()
    )
    calls = 0

    async def scripted(
        history: list[Any], *args: object, **kwargs: object
    ) -> AsyncIterator[dict[str, Any]]:
        nonlocal calls
        calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if calls == 1:
            yield {
                "contentBlockStart": {
                    "start": {
                        "toolUse": {"toolUseId": "frozen", "name": fixture["tool"]}
                    }
                }
            }
            yield {
                "contentBlockDelta": {
                    "delta": {"toolUse": {"input": json.dumps(fixture["input"])}}
                }
            }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {
                "contentBlockDelta": {
                    "delta": {"text": f"$5.80 fixed toll. History: {len(history)}"}
                }
            }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "metrics": {"latencyMs": 1},
            }
        }

    def model() -> Any:  # noqa: ANN401
        native = original()
        cast(Any, native).stream = scripted
        return native

    spec = importlib.util.spec_from_file_location(
        "artifact_worker", Path(__file__).parents[1] / "eval/artifact_worker.py"
    )
    assert spec and spec.loader
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    # Any accidental provider, AWS or database connection fails this smoke.
    with (
        patch.object(toll_agent, "_build_model", model),
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ),
        open(os.devnull, "w") as sink,
        redirect_stdout(sink),
    ):
        worker.main()


def main(bundle: Path) -> None:
    from eval import golden
    from eval import golden_run as run
    from eval.artifact_agent import ArtifactAgent

    # Probe unmodified bytes before installing the test-only canned provider.
    probe = ArtifactAgent(bundle, "offline-no-credential")
    identity = probe.identity
    probe.close()
    popen = subprocess.Popen

    def process(args: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:  # noqa: ANN401
        assert args[1:3] == ["-I", "-S"]
        assert set(kwargs["env"]) == {"PATH", "LANG"}
        args[3] = str(Path(__file__).resolve())
        return cast(subprocess.Popen[bytes], popen([*args, "--child"], **kwargs))

    case = golden.load_cases()[0]
    attempt = run.Attempt(id="smoke", case_id=case.id, trial=1)
    messages = [case.prompt]
    attempt.turns.append(golden.Turn(user=case.prompt, response="pending", calls=[]))
    with (
        tempfile.TemporaryDirectory() as temp,
        patch.object(subprocess, "Popen", process),
    ):
        journal = run.Journal(Path(temp) / "run", 5)
        agent = ArtifactAgent(
            bundle, "offline-no-credential", case, attempt, journal, messages, identity
        )
        try:
            first = agent(case.prompt)
            assert "$5.80" in first and first.stop_reason == "end_turn"
            assert len(attempt.turns[0].calls) == 1
            assert len(attempt.requested_tools) == 1
            messages.append("Thanks. Remind me of that price?")
            attempt.turns.append(
                golden.Turn(user=messages[-1], response="pending", calls=[])
            )
            second = agent(messages[-1])
            assert int(second.split("History: ")[1]) > int(first.split("History: ")[1])
            assert len(attempt.measurements) == 3
            assert all(m.complete for m in attempt.measurements)
            assert not journal.unknown_usage and abs(journal.reserved) < 1e-9
        finally:
            agent.close()
    print(
        "Packaged agent smoke passed: isolated imports, frozen tool replay, conversation state, measured calls; no network."
    )


if __name__ == "__main__":
    if sys.argv[-1] == "--child":
        child(Path(sys.argv[1]))
    else:
        main(Path(sys.argv[1]))

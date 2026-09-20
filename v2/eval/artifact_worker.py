"""Trusted bootstrap, run with python -I -S against an extracted ARM64 bundle.

Only the application and its runtime dependencies come from the bundle. The
parent owns fixtures, actor/judge execution, budget admission, and the journal.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from collections.abc import AsyncIterator
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from threading import RLock
from typing import Any, cast

WIRE = sys.stdout
WIRE_LOCK = RLock()


def exchange(value: dict[str, Any]) -> dict[str, Any]:
    # SDK tool callbacks can run concurrently; each request owns its reply.
    with WIRE_LOCK:
        WIRE.write(json.dumps(value, allow_nan=False) + "\n")
        WIRE.flush()
        line = sys.stdin.readline(2_000_001)
    if not line.endswith("\n") or len(line) > 2_000_000:
        raise ValueError("invalid parent message")
    result: dict[str, Any] = json.loads(line)
    if result.get("event") == "stop":
        raise ValueError("parent stopped execution")
    return result


def main() -> None:
    if platform.machine() not in {"aarch64", "arm64"} or sys.version_info[:2] != (
        3,
        13,
    ):
        raise ValueError("requires ARM64 Python 3.13")
    bundle = Path(sys.argv[1]).resolve(strict=True)
    sys.path.insert(0, str(bundle))
    initial = exchange({"event": "ready"})
    from strands import tool  # pyright: ignore[reportUnknownVariableType]
    from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
    from strands.types.tools import ToolContext, ToolSpec

    from agent import toll_agent
    from agent_tools import current_price_domain, get_annual_toll_ballpark

    toll_agent.load_openai_api_key = lambda: initial["api_key"]
    model = cast(Any, toll_agent._build_model())
    model.client_args["max_retries"] = 0
    model.client_args["timeout"] = 60
    specs = [current_price_domain.TOOL_SPEC, get_annual_toll_ballpark.TOOL_SPEC]
    files: dict[str, str] = {}
    for name, module in list(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().is_relative_to(bundle):
            path = Path(filename).resolve()
            files[str(path.relative_to(bundle))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        elif (
            name.split(".")[0]
            in {"agent", "agent_tools", "strands", "openai", "pydantic"}
            and filename
        ):
            raise ValueError("application import escaped bundle")
    identity = {
        "prompt_version": toll_agent.SYSTEM_PROMPT_VERSION,
        "renderer_version": toll_agent.SYSTEM_PROMPT_RENDERER_VERSION,
        "prompt_hashes": {
            key: hashlib.sha256(
                toll_agent.build_system_prompt(
                    initial["points"], current_date=date.fromisoformat(day)
                ).encode()
            ).hexdigest()
            for key, day in initial["dates"].items()
        },
        "tool_specs": specs,
        "model_config": model.get_config(),
        "imported_files": files,
    }
    request = exchange({"event": "identity", "identity": identity})
    if request["event"] == "close":
        return
    original = model.stream

    async def measured(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:  # noqa: ANN401
        exchange(
            {
                "event": "model_start",
                "input_bound": len(json.dumps([args, kwargs], default=str).encode())
                + 8192,
            }
        )
        started, usage = time.monotonic(), None
        try:
            async for event in original(*args, **kwargs):
                if "metadata" in event and "usage" in event["metadata"]:
                    usage = event["metadata"]["usage"]
                yield event
        finally:
            exchange(
                {
                    "event": "model_end",
                    "usage": usage,
                    "seconds": time.monotonic() - started,
                }
            )

    model.stream = measured

    class Requests(HookProvider):
        def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:  # noqa: ANN401
            registry.add_callback(BeforeToolCallEvent, self.before)

        def before(self, event: BeforeToolCallEvent) -> None:
            result = exchange(
                {
                    "event": "requested",
                    "name": event.tool_use["name"],
                    "input": event.tool_use["input"],
                }
            )
            if not result["allowed"]:
                event.cancel_tool = "Frozen evaluation rejected this call."

    tools: list[Any] = []
    for spec in specs:

        @tool(
            name=spec["name"],
            description=spec["description"],
            inputSchema=spec["inputSchema"],
            context="tool_context",
        )
        async def frozen(tool_context: ToolContext) -> AsyncIterator[dict[str, Any]]:
            use = tool_context.tool_use
            result = exchange(
                {"event": "tool", "name": use["name"], "input": use["input"]}
            )["result"]
            result["toolUseId"] = use["toolUseId"]
            yield result

        frozen.tool_spec = cast(ToolSpec, spec)
        tools.append(frozen)
    agent = toll_agent.build_agent(
        model=model,
        tools=tools,
        prompt_points=initial["points"],
        current_date=date.fromisoformat(request["date"]),
        hooks=[Requests()],
    )
    while request["event"] == "turn":
        result = agent(request["message"])
        request = exchange(
            {"event": "answer", "text": str(result), "stop_reason": result.stop_reason}
        )


if __name__ == "__main__":
    try:
        with open(os.devnull, "w") as sink, redirect_stdout(sink):
            main()
    except Exception:
        WIRE.write('{"event":"failure"}\n')
        WIRE.flush()
        raise SystemExit(1) from None

"""Private Bedrock AgentCore boundary for the v2 TollChat agent."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, Protocol, cast

import boto3
from bedrock_agentcore import BedrockAgentCoreApp
from strands.types.agent import Limits

from agent.toll_agent import (
    _DUPLICATE_TOOL_MESSAGE,  # pyright: ignore[reportPrivateUsage]
    build_agent,
)

MAX_MESSAGE_CHARS = 8_000
MAX_TURNS = 5
_INVOCATION_LIMITS: Limits = {
    "turns": 6,
    "output_tokens": 8_192,
    "total_tokens": 50_000,
}
DISCLAIMER = (
    "Estimates only. Verify current rates with the toll operator before travel."
)
BLOCKED_MESSAGE = "I can only help with Northern Virginia toll road estimates."
_FAILURE_MODE = "runtime_exception_v2"
_CREDENTIAL = re.compile(
    r"(?i)(?:authorization\s*[:=]|password\s*[:=]|api[_-]?key\s*[:=]|"
    r"bearer\s+\S+|(?:AKIA|ASIA)[0-9A-Z]{16}|(?:sk|gh[pousr]_)[A-Za-z0-9_-]{8,}|"
    r"github_pat_[A-Za-z0-9_-]{20,})"
)
_TOOL_LABELS = {
    "get_current_toll_price": "Checking current toll price",
    "get_annual_toll_ballpark": "Calculating annual toll-commute affordability",
}
logger = logging.getLogger(__name__)


class GuardrailClient(Protocol):
    def apply_guardrail(self, **kwargs: object) -> Mapping[str, object]: ...


class AgentCallable(Protocol):
    def stream_async(
        self, prompt: str, *, limits: Limits | None = None
    ) -> AsyncIterator[dict[str, object]]: ...


def _error(code: str, message: str) -> dict[str, object]:
    return {"type": "error", "code": code, "message": message}


def _blocked() -> dict[str, object]:
    return {"type": "answer", "text": BLOCKED_MESSAGE, "blocked": True}


def _duplicate(result: Mapping[str, object]) -> bool:
    return result.get("status") == "error" and result.get("content") == [
        {"text": _DUPLICATE_TOOL_MESSAGE}
    ]


def _activity_events(
    message: object, activities: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    if not isinstance(message, Mapping):
        return []
    content = cast(Mapping[object, object], message).get("content", [])
    if not isinstance(content, Sequence):
        return []
    events: list[dict[str, object]] = []
    for block in cast(Sequence[object], content):
        if not isinstance(block, Mapping):
            continue
        data = cast(Mapping[str, object], block)
        tool_use = data.get("toolUse")
        if isinstance(tool_use, Mapping):
            use = cast(Mapping[str, object], tool_use)
            tool_id = use.get("toolUseId")
            if isinstance(tool_id, str) and tool_id not in activities:
                activity: dict[str, object] = {
                    "type": "tool",
                    "index": len(activities),
                    "label": _TOOL_LABELS.get(
                        str(use.get("name")), "Checking toll data"
                    ),
                    "status": "running",
                }
                activities[tool_id] = activity
                events.append(dict(activity))
            continue
        tool_result = data.get("toolResult")
        if isinstance(tool_result, Mapping):
            result = cast(Mapping[str, object], tool_result)
            tool_id = result.get("toolUseId")
            if isinstance(tool_id, str) and tool_id in activities:
                activity = activities[tool_id]
                activity["status"] = (
                    "failed"
                    if result.get("status") == "error" and not _duplicate(result)
                    else "completed"
                )
                events.append(dict(activity))
    return events


class TollChatRuntime:
    def __init__(
        self,
        agent_factory: Callable[[], AgentCallable],
        guardrail_client: GuardrailClient,
        guardrail_identifier: str = "",
        guardrail_version: str = "",
    ) -> None:
        self._agent_factory = agent_factory
        self._guardrail_client = guardrail_client
        self._guardrail_identifier = guardrail_identifier
        self._guardrail_version = guardrail_version
        self._agent: AgentCallable | None = None
        self._turns = 0

    def _is_blocked(self, text: str, source: str) -> bool:
        response = self._guardrail_client.apply_guardrail(
            guardrailIdentifier=self._guardrail_identifier,
            guardrailVersion=self._guardrail_version,
            source=source,
            outputScope="FULL",
            content=[{"text": {"text": text}}],
        )
        return response.get("action") == "GUARDRAIL_INTERVENED"

    async def stream(self, payload: object) -> AsyncIterator[dict[str, object]]:
        if not isinstance(payload, dict):
            yield _error(
                "invalid_request", "Provide a message between 1 and 8000 characters."
            )
            return
        request = cast(dict[str, object], payload)
        prompt = request.get("prompt")
        if (
            not isinstance(prompt, str)
            or not (prompt := prompt.strip())
            or len(prompt) > MAX_MESSAGE_CHARS
        ):
            yield _error(
                "invalid_request", "Provide a message between 1 and 8000 characters."
            )
            return
        if self._turns >= MAX_TURNS:
            yield _error("turn_limit", "Start a new chat to continue.")
            return

        try:
            if self._is_blocked(prompt, "INPUT") or _CREDENTIAL.search(prompt):
                yield _blocked()
                return
            if request.get("failure_mode") == _FAILURE_MODE:
                raise RuntimeError("deployed failure drill")
            if self._agent is None:
                self._agent = self._agent_factory()
            self._turns += 1
            result: object | None = None
            activities: dict[str, dict[str, object]] = {}
            async for event in self._agent.stream_async(
                prompt, limits=_INVOCATION_LIMITS
            ):
                for activity in _activity_events(event.get("message"), activities):
                    yield activity
                if "result" in event:
                    result = event["result"]
            if result is None:
                raise RuntimeError("agent stream ended without a result")
            answer = str(result).strip()
            if self._is_blocked(answer, "OUTPUT"):
                yield _blocked()
                return
            if DISCLAIMER not in answer:
                answer = f"{answer}\n\n{DISCLAIMER}"
            yield {"type": "answer", "text": answer, "blocked": False}
        except Exception as error:  # Provider boundary returns one safe error contract.
            logger.error(
                "TollChat runtime request failed type=%s", type(error).__name__
            )
            yield _error(
                "agent_unavailable",
                "TollChat could not complete that request. Please try again.",
            )


app = BedrockAgentCoreApp()
_runtime: TollChatRuntime | None = None


@app.entrypoint  # pyright: ignore[reportUnknownMemberType]
async def invoke(payload: object, context: object) -> AsyncIterator[dict[str, object]]:
    del context
    global _runtime
    if _runtime is None:
        _runtime = TollChatRuntime(
            build_agent,
            cast(Any, boto3.client("bedrock-runtime")),  # pyright: ignore[reportUnknownMemberType]
            os.environ["TOLLCHAT_GUARDRAIL_ID"],
            os.environ["TOLLCHAT_GUARDRAIL_VERSION"],
        )
    async for event in _runtime.stream(payload):
        yield event


if __name__ == "__main__":
    app.run()  # pyright: ignore[reportUnknownMemberType]

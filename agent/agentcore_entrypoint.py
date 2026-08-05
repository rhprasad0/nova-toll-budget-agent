from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Protocol, cast

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent.toll_agent import build_agent

MAX_MESSAGE_CHARS = 8_000
MAX_TURNS = 5
DISCLAIMER = (
    "Estimates only. Verify current rates with the toll operator before travel."
)
BLOCKED_MESSAGE = "I can only help with Northern Virginia toll road estimates."

logger = logging.getLogger(__name__)


class GuardrailClient(Protocol):
    def apply_guardrail(self, **kwargs: object) -> dict[str, object]: ...


class AgentCallable(Protocol):
    def __call__(self, prompt: str) -> object: ...


class TollChatRuntime:
    def __init__(
        self,
        agent_factory: Callable[..., AgentCallable],
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
            content=[{"text": {"text": text}}],
        )
        return response.get("action") == "GUARDRAIL_INTERVENED"

    def invoke(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            return _invalid_request()
        prompt = cast(dict[str, object], payload).get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return _invalid_request()
        prompt = prompt.strip()
        if len(prompt) > MAX_MESSAGE_CHARS:
            return _invalid_request()
        if self._turns >= MAX_TURNS:
            return {
                "error": {
                    "code": "turn_limit",
                    "message": "Start a new chat to continue.",
                }
            }

        try:
            if self._is_blocked(prompt, "INPUT"):
                return {"response": BLOCKED_MESSAGE, "blocked": True}

            if self._agent is None:
                self._agent = self._agent_factory()
            self._turns += 1
            agent = self._agent
            answer = str(agent(prompt)).strip()

            if self._is_blocked(answer, "OUTPUT"):
                return {"response": BLOCKED_MESSAGE, "blocked": True}
            if DISCLAIMER not in answer:
                answer = f"{answer}\n\n{DISCLAIMER}"
            return {"response": answer, "blocked": False}
        except Exception:
            logger.exception("TollChat runtime invocation failed")
            return {
                "error": {
                    "code": "agent_unavailable",
                    "message": "TollChat could not complete that request. Please try again.",
                }
            }


def _invalid_request() -> dict[str, object]:
    return {
        "error": {
            "code": "invalid_request",
            "message": "Provide a message between 1 and 8000 characters.",
        }
    }


app = BedrockAgentCoreApp()
_runtime: TollChatRuntime | None = None


@app.entrypoint  # pyright: ignore[reportUnknownMemberType]
def invoke(payload: object, context: object) -> dict[str, object]:
    del context
    global _runtime
    if _runtime is None:
        _runtime = TollChatRuntime(
            build_agent,
            cast(GuardrailClient, boto3.client("bedrock-runtime")),  # pyright: ignore[reportUnknownMemberType]
            os.environ["TOLLCHAT_GUARDRAIL_ID"],
            os.environ["TOLLCHAT_GUARDRAIL_VERSION"],
        )
    return _runtime.invoke(payload)


if __name__ == "__main__":
    app.run()  # pyright: ignore[reportUnknownMemberType]

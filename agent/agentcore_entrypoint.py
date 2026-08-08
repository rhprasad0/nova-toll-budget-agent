from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol, cast

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp, BedrockAgentCoreContext
from opentelemetry import baggage, trace
from opentelemetry import context as otel_context
from strands.hooks import MessageAddedEvent

from agent.toll_agent import (
    SYSTEM_PROMPT_VERSION,
    TOOLSET_VERSION,
    build_agent,
)

MAX_MESSAGE_CHARS = 8_000
MAX_TURNS = 5
DISCLAIMER = (
    "Estimates only. Verify current rates with the toll operator before travel."
)
BLOCKED_MESSAGE = "I can only help with Northern Virginia toll road estimates."
TRACE_CHUNK_BYTES = 240 * 1024
_CREDENTIAL_KEY = re.compile(
    r"(?:access[_-]?key|api[_-]?key|authorization|credential|password|private[_-]?key|secret|session[_-]?token|token)",
    re.IGNORECASE,
)
_CREDENTIAL_VALUE = re.compile(
    r"(?:(?:access[_-]?key|api[_-]?key|authorization|credential|password|private[_-]?key|secret|session[_-]?token|token)\s*[=:]\s*\S+|basic\s+\S+|bearer\s+\S+|(?:AKIA|ASIA)[0-9A-Z]{16}|(?:sk|rk|pk)[_-][A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_-]{8,}|(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://\S+)",
    re.IGNORECASE,
)
_SYSTEM_PROMPT_KEY = re.compile(r"(?:system|developer)[_-]?prompt\Z", re.IGNORECASE)
_TRACER = trace.get_tracer(__name__)

logger = logging.getLogger(__name__)


class GuardrailClient(Protocol):
    def apply_guardrail(self, **kwargs: object) -> dict[str, object]: ...


class TraceClient(Protocol):
    def create_log_stream(self, **kwargs: object) -> object: ...

    def put_log_events(self, **kwargs: object) -> object: ...


class ModelConfig(Protocol):
    def get_config(self) -> Mapping[str, object]: ...


class AgentCallable(Protocol):
    @property
    def model(self) -> ModelConfig: ...

    def stream_async(self, prompt: str) -> AsyncIterator[dict[str, object]]: ...


class TollChatRuntime:
    def __init__(
        self,
        agent_factory: Callable[..., AgentCallable],
        guardrail_client: GuardrailClient,
        guardrail_identifier: str = "",
        guardrail_version: str = "",
        trace_client: TraceClient | None = None,
        trace_log_group: str = "",
    ) -> None:
        self._agent_factory = agent_factory
        self._guardrail_client = guardrail_client
        self._guardrail_identifier = guardrail_identifier
        self._guardrail_version = guardrail_version
        self._agent: AgentCallable | None = None
        self._turns = 0
        self._trace_client = trace_client
        self._trace_log_group = trace_log_group
        self._trace_log_stream = f"runtime-{uuid.uuid4().hex}"
        self._trace_log_stream_ready = False
        self._model_messages: list[object] = []

    def _record_message(self, event: MessageAddedEvent) -> None:
        self._model_messages.append(deepcopy(event.message))

    def _is_blocked(self, text: str, source: str, correlation: dict[str, str]) -> bool:
        started_at = _timestamp()
        request = {
            "guardrailIdentifier": self._guardrail_identifier,
            "guardrailVersion": self._guardrail_version,
            "source": source,
            "outputScope": "FULL",
            "content": [{"text": {"text": text}}],
        }
        with _TRACER.start_as_current_span(f"tollchat.guardrail.{source.lower()}"):
            response = self._guardrail_client.apply_guardrail(**request)
            self._emit_trace(
                f"{source.lower()}_guardrail",
                {
                    "timing": _timing(started_at),
                    "request": request,
                    "response": response,
                },
                correlation,
            )
        return response.get("action") == "GUARDRAIL_INTERVENED"

    async def stream(
        self, payload: object, context: object | None = None
    ) -> AsyncIterator[dict[str, object]]:
        correlation = _correlation(context)
        started_at = _timestamp()
        baggage_context = baggage.set_baggage(
            "tollchat.session_id", correlation["session_id"]
        )
        baggage_context = baggage.set_baggage(
            "tollchat.aws_request_id", correlation["aws_request_id"], baggage_context
        )
        token = otel_context.attach(baggage_context)
        activities: dict[str, dict[str, object]] = {}

        def finish(
            result: dict[str, object], error: Exception | None = None
        ) -> dict[str, object]:
            try:
                self._emit_trace(
                    "invoke",
                    {
                        "timing": _timing(started_at),
                        "result": result,
                        "error": _exception_payload(error),
                    },
                    correlation,
                )
            except Exception as trace_error:  # noqa: BLE001 - telemetry boundary
                logger.error(
                    "TollChat trace write failed stage=invoke type=%s",
                    type(trace_error).__name__,
                )
                return _public_event(_trace_unavailable())
            return _public_event(result)

        try:
            with _TRACER.start_as_current_span("tollchat.runtime.invoke"):
                span_context = trace.get_current_span().get_span_context()
                if span_context.is_valid:
                    correlation["trace_id"] = f"{span_context.trace_id:032x}"
                if not isinstance(payload, dict):
                    yield finish(_invalid_request())
                    return
                prompt = cast(dict[str, object], payload).get("prompt")
                if not isinstance(prompt, str) or not prompt.strip():
                    yield finish(_invalid_request())
                    return
                prompt = prompt.strip()
                if len(prompt) > MAX_MESSAGE_CHARS:
                    yield finish(_invalid_request())
                    return
                if self._turns >= MAX_TURNS:
                    yield finish(
                        {
                            "error": {
                                "code": "turn_limit",
                                "message": "Start a new chat to continue.",
                            }
                        }
                    )
                    return

                if self._is_blocked(
                    prompt, "INPUT", correlation
                ) or _looks_like_credential(prompt):
                    yield finish({"response": BLOCKED_MESSAGE, "blocked": True})
                    return

                if self._agent is None:
                    self._agent = self._agent_factory(
                        trace_attributes={
                            "session.id": correlation["session_id"],
                            "tollchat.session_id": correlation["session_id"],
                        },
                        hooks=[self._record_message],
                    )
                self._turns += 1
                agent = self._agent
                trace_attributes = getattr(agent, "trace_attributes", None)
                if isinstance(trace_attributes, dict):
                    trace_attributes["tollchat.aws_request_id"] = correlation[
                        "aws_request_id"
                    ]
                agent_started_at = _timestamp()
                self._model_messages.clear()
                with _TRACER.start_as_current_span("tollchat.agent"):
                    result: object | None = None
                    async for event in agent.stream_async(prompt):
                        message = event.get("message")
                        if isinstance(message, Mapping):
                            for activity in _activity_events(
                                cast(Mapping[object, object], message), activities
                            ):
                                yield activity
                        if "result" in event:
                            result = event["result"]
                    if result is None:
                        raise RuntimeError("agent stream ended without a result")
                    answer = str(result).strip()
                    self._emit_trace(
                        "agent",
                        _agent_payload(
                            agent,
                            result,
                            prompt,
                            answer,
                            agent_started_at,
                            self._model_messages,
                        ),
                        correlation,
                    )

                if self._is_blocked(answer, "OUTPUT", correlation):
                    yield finish({"response": BLOCKED_MESSAGE, "blocked": True})
                    return
                if DISCLAIMER not in answer:
                    answer = f"{answer}\n\n{DISCLAIMER}"
                yield finish({"response": answer, "blocked": False})
        except Exception as error:  # noqa: BLE001 - runtime boundary
            logger.error("TollChat runtime invocation failed: %s", type(error).__name__)
            for activity in activities.values():
                if activity["status"] == "running":
                    activity["status"] = "failed"
                    yield dict(activity)
            yield finish(_trace_unavailable(), error)
        finally:
            otel_context.detach(token)

    def _emit_trace(
        self, stage: str, payload: dict[str, object], correlation: dict[str, str]
    ) -> None:
        if self._trace_client is None or not self._trace_log_group:
            return
        if not self._trace_log_stream_ready:
            self._trace_client.create_log_stream(
                logGroupName=self._trace_log_group,
                logStreamName=self._trace_log_stream,
            )
            self._trace_log_stream_ready = True
        timestamp = int(time.time() * 1000)
        for message in _trace_messages(stage, payload, correlation):
            self._trace_client.put_log_events(
                logGroupName=self._trace_log_group,
                logStreamName=self._trace_log_stream,
                logEvents=[{"timestamp": timestamp, "message": message}],
            )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timing(started_at: str) -> dict[str, str]:
    return {"started_at": started_at, "ended_at": _timestamp()}


def _correlation(context: object | None) -> dict[str, str]:
    session_id = BedrockAgentCoreContext.get_session_id() or getattr(
        context, "session_id", None
    )
    if not isinstance(session_id, str) or not session_id:
        session_id = uuid.uuid4().hex
    headers = getattr(context, "request_headers", {})
    request = getattr(context, "request", None)
    if not isinstance(headers, Mapping):
        headers = getattr(request, "headers", {})
    request_id = BedrockAgentCoreContext.get_request_id()
    if request_id is None and isinstance(headers, Mapping):
        header_values = cast(Mapping[object, object], headers)
        request_id = next(
            (
                value
                for key, value in header_values.items()
                if isinstance(key, str)
                and key.lower() in {"x-amzn-requestid", "x-amzn-request-id"}
                and isinstance(value, str)
                and value
            ),
            None,
        )
    span_context = trace.get_current_span().get_span_context()
    trace_id = (
        f"{span_context.trace_id:032x}" if span_context.is_valid else uuid.uuid4().hex
    )
    return {
        "trace_id": trace_id,
        "session_id": session_id,
        "aws_request_id": request_id or uuid.uuid4().hex,
    }


def _current_span_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    return (
        f"{span_context.span_id:016x}"
        if span_context.is_valid
        else uuid.uuid4().hex[:16]
    )


def _looks_like_credential(value: str) -> bool:
    return bool(_CREDENTIAL_VALUE.search(value))


def _sanitize(value: object, key: str = "") -> object:
    if _SYSTEM_PROMPT_KEY.fullmatch(key):
        return None
    if isinstance(value, str):
        if _CREDENTIAL_KEY.search(key) or _looks_like_credential(value):
            return "[REDACTED]"
        if "system prompt" in value.lower():
            return "[REDACTED]"
        return value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        if mapping.get("role") in {"system", "developer"}:
            return {"role": mapping["role"], "content": "[REDACTED]"}
        sanitized: dict[str, object] = {}
        for nested_key, nested_value in mapping.items():
            normalized_key = str(nested_key)
            if _SYSTEM_PROMPT_KEY.fullmatch(normalized_key):
                continue
            sanitized[normalized_key] = _sanitize(nested_value, normalized_key)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_sanitize(item, key) for item in cast(Sequence[object], value)]
    if value is None or isinstance(value, bool | float | int):
        return value
    return _sanitize(str(value), key)


def _utf8_chunks(value: str) -> list[str]:
    chunks: list[str] = []
    chunk: list[str] = []
    size = 0
    for character in value:
        character_size = len(character.encode())
        if chunk and size + character_size > TRACE_CHUNK_BYTES:
            chunks.append("".join(chunk))
            chunk = []
            size = 0
        chunk.append(character)
        size += character_size
    if chunk:
        chunks.append("".join(chunk))
    return chunks or [""]


def _trace_messages(
    stage: str, payload: dict[str, object], correlation: dict[str, str]
) -> list[str]:
    serialized = json.dumps(
        _sanitize(payload),
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    chunks = _utf8_chunks(serialized)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    span_id = _current_span_id()
    return [
        json.dumps(
            {
                "record_version": 1,
                "record_type": "tollchat.runtime_trace",
                "stage": stage,
                **correlation,
                "span_id": span_id,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "sha256": digest,
                "payload": chunk,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for index, chunk in enumerate(chunks)
    ]


def _tool_calls(messages: object) -> list[dict[str, object]]:
    if not isinstance(messages, Sequence):
        return []
    calls: list[dict[str, object]] = []
    pending: dict[str, dict[str, object]] = {}
    for message in cast(Sequence[object], messages):
        if not isinstance(message, Mapping):
            continue
        message_data = cast(Mapping[str, object], message)
        content = message_data.get("content", [])
        if not isinstance(content, Sequence):
            continue
        for block in cast(Sequence[object], content):
            if not isinstance(block, Mapping):
                continue
            block_data = cast(Mapping[str, object], block)
            tool_use = block_data.get("toolUse")
            if isinstance(tool_use, Mapping):
                tool_use_data = cast(Mapping[str, object], tool_use)
                tool_use_id = tool_use_data.get("toolUseId")
                if not isinstance(tool_use_id, str):
                    raise ValueError("tool use is missing toolUseId")
                call = {
                    "name": tool_use_data.get("name"),
                    "arguments": tool_use_data.get("input"),
                    "result": None,
                }
                calls.append(call)
                pending[tool_use_id] = call
                continue
            tool_result = block_data.get("toolResult")
            if isinstance(tool_result, Mapping):
                tool_result_data = cast(Mapping[str, object], tool_result)
                tool_use_id = tool_result_data.get("toolUseId")
                if not isinstance(tool_use_id, str) or tool_use_id not in pending:
                    raise ValueError("tool result has no matching tool use")
                pending[tool_use_id]["result"] = tool_result_data.get("content")
    return calls


def _model_version(agent: AgentCallable) -> object:
    return agent.model.get_config().get("model_id")


def _agent_payload(
    agent: AgentCallable,
    result: object,
    prompt: str,
    answer: str,
    started_at: str,
    recorded_messages: list[object] | None = None,
) -> dict[str, object]:
    to_dict = getattr(result, "to_dict", None)
    sdk_response = to_dict() if callable(to_dict) else result
    messages = recorded_messages or getattr(agent, "messages", [])
    return {
        "timing": _timing(started_at),
        "request": {"prompt": prompt},
        "response": {"answer": answer, "sdk_response": sdk_response},
        "model_messages": messages,
        "tool_calls": _tool_calls(messages),
        "model_version": _model_version(agent),
        "system_prompt_version": SYSTEM_PROMPT_VERSION,
        "toolset_version": TOOLSET_VERSION,
    }


def _exception_payload(error: Exception | None) -> dict[str, str] | None:
    if error is None:
        return None
    return {
        "type": type(error).__name__,
        "message": "[REDACTED]",
    }


def _invalid_request() -> dict[str, object]:
    return {
        "error": {
            "code": "invalid_request",
            "message": "Provide a message between 1 and 8000 characters.",
        }
    }


def _trace_unavailable() -> dict[str, object]:
    return {
        "error": {
            "code": "agent_unavailable",
            "message": "TollChat could not complete that request. Please try again.",
        }
    }


def _public_event(result: dict[str, object]) -> dict[str, object]:
    error = result.get("error")
    if isinstance(error, Mapping):
        return {"type": "error", **error}
    return {
        "type": "answer",
        "text": result["response"],
        "blocked": result["blocked"],
    }


_TOOL_LABELS = {
    "plan_toll_route": "Planning toll route",
    "i66_route": "Checking I-66 tolls",
    "i95_route": "Checking I-95/395 tolls",
    "i495_route": "Checking I-495 tolls",
    "dulles_route": "Checking Dulles tolls",
}


def _activity_events(
    message: Mapping[object, object], activities: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    content = message.get("content", [])
    if not isinstance(content, Sequence):
        return []
    events: list[dict[str, object]] = []
    for block in cast(Sequence[object], content):
        if not isinstance(block, Mapping):
            continue
        block_data = cast(Mapping[str, object], block)
        tool_use = block_data.get("toolUse")
        if isinstance(tool_use, Mapping):
            tool_use_data = cast(Mapping[str, object], tool_use)
            tool_id = tool_use_data.get("toolUseId")
            name = tool_use_data.get("name")
            if isinstance(tool_id, str) and tool_id not in activities:
                activity: dict[str, object] = {
                    "type": "tool",
                    "index": len(activities),
                    "label": _TOOL_LABELS.get(str(name), "Checking toll data"),
                    "status": "running",
                }
                activities[tool_id] = activity
                events.append(dict(activity))
            continue
        tool_result = block_data.get("toolResult")
        if isinstance(tool_result, Mapping):
            tool_result_data = cast(Mapping[str, object], tool_result)
            tool_id = tool_result_data.get("toolUseId")
            if isinstance(tool_id, str) and tool_id in activities:
                activity = activities[tool_id]
                activity["status"] = (
                    "failed"
                    if tool_result_data.get("status") == "error"
                    else "completed"
                )
                events.append(dict(activity))
    return events


app = BedrockAgentCoreApp()
_runtime: TollChatRuntime | None = None


@app.entrypoint  # pyright: ignore[reportUnknownMemberType]
async def invoke(payload: object, context: object) -> AsyncIterator[dict[str, object]]:
    global _runtime
    if _runtime is None:
        _runtime = TollChatRuntime(
            build_agent,
            cast(GuardrailClient, boto3.client("bedrock-runtime")),  # pyright: ignore[reportUnknownMemberType]
            os.environ["TOLLCHAT_GUARDRAIL_ID"],
            os.environ["TOLLCHAT_GUARDRAIL_VERSION"],
            cast(TraceClient, boto3.client("logs")),  # pyright: ignore[reportUnknownMemberType]
            os.environ["TOLLCHAT_TRACE_LOG_GROUP"],
        )
    async for event in _runtime.stream(payload, context):
        yield event


if __name__ == "__main__":
    app.run()  # pyright: ignore[reportUnknownMemberType]

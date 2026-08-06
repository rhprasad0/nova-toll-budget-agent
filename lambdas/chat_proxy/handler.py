from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Protocol, cast
from uuid import UUID

import boto3

MAX_MESSAGE_CHARS = 8_000
RUNTIME_QUALIFIER = "preview"
logger = logging.getLogger(__name__)


class RuntimeResponseBody(Protocol):
    def read(self) -> bytes: ...


class RuntimeClient(Protocol):
    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]: ...

    def stop_runtime_session(self, **kwargs: object) -> object: ...


class ChatProxy:
    def __init__(self, client: RuntimeClient, runtime_arn: str) -> None:
        self._client = client
        self._runtime_arn = runtime_arn

    def handle(self, event: dict[str, Any], _context: object) -> dict[str, object]:
        method = event.get("httpMethod")
        path = event.get("path")
        if method == "OPTIONS" and path in {"/api/config", "/api/chat", "/api/reset"}:
            return _response(204, {})
        if method == "GET" and path == "/api/config":
            return _response(
                200,
                {"chatEnabled": True, "maxMessageChars": 8000, "maxTurns": 5},
            )
        if method == "POST" and path in {"/api/chat", "/api/reset"}:
            body = self._body(event)
            if body is None or not _valid_session(body.get("session_id")):
                return _invalid_request()
            if path == "/api/reset":
                return self._reset(body["session_id"])
            return self._chat(body)
        return _response(404, {"error": {"code": "not_found"}})

    @staticmethod
    def _body(event: dict[str, Any]) -> dict[str, Any] | None:
        raw = event.get("body")
        if not isinstance(raw, str) or len(raw) > MAX_MESSAGE_CHARS + 512:
            return None
        try:
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw, validate=True).decode()
            value = cast(object, json.loads(raw))
        except (ValueError, UnicodeDecodeError):
            return None
        return cast(dict[str, Any], value) if isinstance(value, dict) else None

    def _chat(self, body: dict[str, Any]) -> dict[str, object]:
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            return _invalid_request()
        message = message.strip()
        if len(message) > MAX_MESSAGE_CHARS:
            return _invalid_request()
        try:
            result = self._client.invoke_agent_runtime(
                agentRuntimeArn=self._runtime_arn,
                runtimeSessionId=body["session_id"],
                qualifier=RUNTIME_QUALIFIER,
                payload=json.dumps({"prompt": message}).encode(),
            )
            response_body = cast(RuntimeResponseBody, result["response"])
            runtime_response = cast(object, json.loads(response_body.read()))
            if not isinstance(runtime_response, dict):
                raise ValueError("AgentCore returned a non-object response")
            runtime_response = cast(dict[str, object], runtime_response)
            if "error" in runtime_response:
                return _response(422, runtime_response)
            answer = runtime_response.get("response")
            if not isinstance(answer, str):
                raise ValueError("AgentCore returned an invalid response")
            return _response(
                200,
                {
                    "answer": answer,
                    "session_id": body["session_id"],
                    "blocked": bool(runtime_response.get("blocked", False)),
                },
            )
        except Exception:
            logger.exception("AgentCore invocation failed")
            return _response(
                502,
                {
                    "error": {
                        "code": "agent_unavailable",
                        "message": "TollChat is temporarily unavailable. Please try again.",
                    }
                },
            )

    def _reset(self, session_id: str) -> dict[str, object]:
        try:
            self._client.stop_runtime_session(
                agentRuntimeArn=self._runtime_arn,
                runtimeSessionId=session_id,
                qualifier=RUNTIME_QUALIFIER,
            )
            return _response(200, {"ok": True})
        except Exception:
            logger.exception("AgentCore session reset failed")
            return _response(
                502,
                {
                    "error": {
                        "code": "agent_unavailable",
                        "message": "TollChat is temporarily unavailable. Please try again.",
                    }
                },
            )


def _valid_session(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _invalid_request() -> dict[str, object]:
    return _response(
        400,
        {
            "error": {
                "code": "invalid_request",
                "message": "Provide a valid chat session and message.",
            }
        },
    )


def _response(status: int, body: dict[str, object]) -> dict[str, object]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "https://tollchat.ai",
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


_proxy: ChatProxy | None = None


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, object]:
    global _proxy
    if _proxy is None:
        client = cast(
            RuntimeClient,
            boto3.client(  # pyright: ignore[reportUnknownMemberType]
                "bedrock-agentcore",
                endpoint_url=os.environ.get("AGENTCORE_VPCE_URL"),
            ),
        )
        _proxy = ChatProxy(client, os.environ["AGENTCORE_RUNTIME_ARN"])
    return _proxy.handle(event, context)

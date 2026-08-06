from __future__ import annotations

import json

import pytest

from lambdas.chat_proxy.handler import ChatProxy

RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/tollchat"
SESSION_ID = "9fd83bc2-6d8b-4d85-b270-f49aa73e41b4"


class Body:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def read(self) -> bytes:
        return json.dumps(self.value).encode()


class FakeClient:
    def __init__(self) -> None:
        self.invocations: list[dict[str, object]] = []
        self.stops: list[dict[str, object]] = []

    def invoke_agent_runtime(self, **kwargs):
        self.invocations.append(kwargs)
        return {
            "response": Body({"response": "The toll is $4.25.", "blocked": False}),
            "statusCode": 200,
        }

    def stop_runtime_session(self, **kwargs):
        self.stops.append(kwargs)
        return {}


def event(method: str, path: str, body: dict[str, object] | None = None):
    return {
        "httpMethod": method,
        "path": path,
        "body": None if body is None else json.dumps(body),
        "isBase64Encoded": False,
        "headers": {"content-type": "application/json"},
    }


def payload(response):
    return json.loads(response["body"])


def test_config_contract_is_cache_disabled():
    response = ChatProxy(FakeClient(), RUNTIME_ARN).handle(
        event("GET", "/api/config"), None
    )

    assert response["statusCode"] == 200
    assert response["headers"]["Cache-Control"] == "no-store"
    assert payload(response) == {
        "chatEnabled": True,
        "maxMessageChars": 8000,
        "maxTurns": 5,
    }


def test_chat_invokes_agentcore_with_the_validated_session():
    client = FakeClient()
    response = ChatProxy(client, RUNTIME_ARN).handle(
        event(
            "POST",
            "/api/chat",
            {"session_id": SESSION_ID, "message": "  Price Dumfries to Westpark  "},
        ),
        None,
    )

    assert response["statusCode"] == 200
    assert payload(response) == {
        "answer": "The toll is $4.25.",
        "session_id": SESSION_ID,
        "blocked": False,
    }
    [invocation] = client.invocations
    assert invocation["agentRuntimeArn"] == RUNTIME_ARN
    assert invocation["runtimeSessionId"] == SESSION_ID
    assert invocation["qualifier"] == "preview"
    assert json.loads(invocation["payload"]) == {"prompt": "Price Dumfries to Westpark"}


def test_reset_stops_the_runtime_session():
    client = FakeClient()

    response = ChatProxy(client, RUNTIME_ARN).handle(
        event("POST", "/api/reset", {"session_id": SESSION_ID}), None
    )

    assert response["statusCode"] == 200
    assert payload(response) == {"ok": True}
    assert client.stops == [
        {
            "agentRuntimeArn": RUNTIME_ARN,
            "runtimeSessionId": SESSION_ID,
            "qualifier": "preview",
        }
    ]


@pytest.mark.parametrize(
    "request_event",
    [
        event("POST", "/api/chat", {"session_id": "bad", "message": "hello"}),
        event("POST", "/api/chat", {"session_id": SESSION_ID, "message": " "}),
        event("POST", "/api/chat", {"session_id": SESSION_ID, "message": 1}),
        event("POST", "/api/chat", {"session_id": SESSION_ID, "message": "x" * 8001}),
    ],
)
def test_chat_rejects_invalid_requests_without_invoking_agentcore(request_event):
    client = FakeClient()

    response = ChatProxy(client, RUNTIME_ARN).handle(request_event, None)

    assert response["statusCode"] == 400
    assert payload(response)["error"]["code"] == "invalid_request"
    assert client.invocations == []


def test_proxy_hides_agentcore_errors():
    class FailingClient(FakeClient):
        def invoke_agent_runtime(self, **kwargs):
            raise RuntimeError("credential-shaped internal detail")

    response = ChatProxy(FailingClient(), RUNTIME_ARN).handle(
        event("POST", "/api/chat", {"session_id": SESSION_ID, "message": "hello"}),
        None,
    )

    assert response["statusCode"] == 502
    assert payload(response) == {
        "error": {
            "code": "agent_unavailable",
            "message": "TollChat is temporarily unavailable. Please try again.",
        }
    }


def test_proxy_rejects_a_malformed_runtime_response():
    class MalformedClient(FakeClient):
        def invoke_agent_runtime(self, **kwargs):
            return {"response": Body({"response": ["not", "text"]})}

    response = ChatProxy(MalformedClient(), RUNTIME_ARN).handle(
        event("POST", "/api/chat", {"session_id": SESSION_ID, "message": "hello"}),
        None,
    )

    assert response["statusCode"] == 502
    assert payload(response)["error"]["code"] == "agent_unavailable"


def test_unknown_route_is_not_found():
    response = ChatProxy(FakeClient(), RUNTIME_ARN).handle(event("GET", "/nope"), None)
    assert response["statusCode"] == 404


def test_browser_preflight_allows_the_static_site():
    response = ChatProxy(FakeClient(), RUNTIME_ARN).handle(
        event("OPTIONS", "/api/chat"), None
    )

    assert response["statusCode"] == 204
    assert response["headers"]["Access-Control-Allow-Origin"] == "https://tollchat.ai"

"""Synthetic AWS routing and runtime streams; no deployed calls or credentials."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from eval import live_runtime


class Body:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.data = b"".join(
            b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\r\n\r\n"
            for event in events
        )
        self.closed = False

    def iter_chunks(self, **_: object) -> Iterator[bytes]:
        # Split JSON, UTF-8 characters, and CRLF frame boundaries.
        for index in range(0, len(self.data), 7):
            yield self.data[index : index + 7]

    def close(self) -> None:
        self.closed = True


class AWS:
    def __init__(self, environment: str = "development") -> None:
        self.account = "920534282028" if environment == "production" else "903859731897"
        self.suffix = "" if environment == "production" else "-dev"
        self.prefix = "nova_toll_v2" + (
            "" if environment == "production" else "_development"
        )
        self.slot = "blue"
        self.status = "Deployed"
        self.version = "7"
        self.runtime_version = "4"
        self.endpoint_version = "4"
        self.model = "deployed-test-model"
        self.alias_weights: dict[str, float] = {}
        self.calls: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] | None = None
        self.body: Body | None = None
        self.change_during_call = False

    def get_distribution(self, **_: object) -> dict[str, Any]:
        return {
            "Distribution": {
                "ARN": f"arn:aws:cloudfront::{self.account}:distribution/site",
                "Status": self.status,
                "DistributionConfig": {
                    "Origins": {
                        "Items": [
                            {
                                "Id": "public-chat",
                                "DomainName": f"{self.slot}.lambda-url.test",
                            }
                        ]
                    },
                    "CacheBehaviors": {
                        "Items": [
                            {"PathPattern": "/api/*", "TargetOriginId": "public-chat"}
                        ]
                    },
                },
            }
        }

    def get_function_url_config(self, **kwargs: str) -> dict[str, str]:
        slot = "green" if kwargs["FunctionName"].endswith("-green") else "blue"
        assert kwargs["Qualifier"] == "live"
        return {"FunctionUrl": f"https://{slot}.lambda-url.test/"}

    def get_alias(self, **_: object) -> dict[str, Any]:
        return {
            "FunctionVersion": self.version,
            "RoutingConfig": {"AdditionalVersionWeights": self.alias_weights},
        }

    def get_function_configuration(self, **kwargs: str) -> dict[str, Any]:
        green = "_green" if self.slot == "green" else ""
        return {
            "FunctionArn": f"{kwargs['FunctionName']}:{kwargs['Qualifier']}",
            "State": "Active",
            "Environment": {
                "Variables": {
                    "AGENTCORE_RUNTIME_ARN": f"arn:aws:bedrock-agentcore:us-east-1:{self.account}:runtime/{self.prefix}{green}-ABC",
                    "AGENTCORE_RUNTIME_ENDPOINT": "preview",
                    "AGENTCORE_RUNTIME_VERSION": self.runtime_version,
                    "RELEASE_ID": f"release-{self.slot}",
                    "PRIVATE_VARIABLE": "must-never-be-published",
                }
            },
        }

    def get_agent_runtime_endpoint(self, **_: object) -> dict[str, str]:
        return {"status": "READY", "agentRuntimeVersion": self.endpoint_version}

    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        evidence = {
            "type": "evaluation",
            "schema_version": 1,
            "session_id": kwargs["runtimeSessionId"],
            "release_id": f"release-{self.slot}",
            "application": {
                "model": self.model,
                "reasoning_effort": "low",
                "max_output_tokens": 2048,
            },
            "calls": [
                {
                    "tool_use_id": "tool-1",
                    "name": "get_current_toll_price",
                    "input": {"origin_point_id": "origin"},
                    "tool_result": {"total_usd": "12.34"},
                }
            ],
        }
        self.body = Body(
            self.events
            if self.events is not None
            else [
                {"type": "text", "text": "Price → $12.34."},
                evidence,
                {"type": "answer", "text": "Price → $12.34.", "blocked": False},
            ]
        )
        if self.change_during_call:
            self.slot = "green"
        return {
            "statusCode": 200,
            "contentType": "text/event-stream",
            "runtimeSessionId": kwargs["runtimeSessionId"],
            "response": self.body,
        }


def runtime(monkeypatch: pytest.MonkeyPatch, aws: AWS) -> live_runtime.LiveRuntime:
    monkeypatch.setenv(
        "ENVIRONMENT", "production" if aws.suffix == "" else "development"
    )
    monkeypatch.setenv("EVAL_SITE_DISTRIBUTION_ID", "site")
    monkeypatch.setenv("AGENTCORE_VPCE_URL", "https://private-endpoint.test")

    def client(_: str, **__: object) -> AWS:
        return aws

    monkeypatch.setattr(live_runtime.boto3, "client", client)
    return live_runtime.LiveRuntime()


@pytest.mark.parametrize("environment", ["development", "production"])
@pytest.mark.parametrize("slot", ["blue", "green"])
def test_follows_live_routing_and_preserves_session(
    monkeypatch: pytest.MonkeyPatch, environment: str, slot: str
) -> None:
    aws = AWS(environment)
    aws.slot = slot
    live = runtime(monkeypatch, aws)
    answer, evidence = live.invoke("First request")
    assert answer == "Price → $12.34."
    assert evidence.calls[0].tool_result == {"total_usd": "12.34"}
    assert evidence.application.model == "deployed-test-model"
    live.invoke("Correction")
    assert len(aws.calls) == 2
    assert {call["runtimeSessionId"] for call in aws.calls} == {live.session_id}
    assert {call["qualifier"] for call in aws.calls} == {"preview"}
    assert (
        json.loads(aws.calls[0]["payload"])["evaluation_marker"]
        == "scheduled-evaluation-v1"
    )
    assert "must-never-be-published" not in str(live.metadata())
    assert live.metadata()["release_id"] == f"release-{slot}"
    assert aws.body is not None and aws.body.closed
    # A new run follows rollback routing and receives a fresh conversation.
    aws.slot = "green" if slot == "blue" else "blue"
    rolled_back = live_runtime.LiveRuntime()
    assert rolled_back.target.release_id != live.target.release_id
    assert rolled_back.session_id != live.session_id


@pytest.mark.parametrize(
    "failure",
    [
        "deploying",
        "wrong_account",
        "weighted_alias",
        "unpublished_alias",
        "version_mismatch",
    ],
)
def test_rejects_ambiguous_or_wrong_environment_targets(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    aws = AWS()
    if failure == "deploying":
        aws.status = "InProgress"
    elif failure == "weighted_alias":
        aws.alias_weights = {"8": 0.1}
    elif failure == "unpublished_alias":
        aws.version = "$LATEST"
    elif failure == "version_mismatch":
        aws.endpoint_version = "5"
    else:
        aws.account = "920534282028"
    with pytest.raises(RuntimeError):
        runtime(monkeypatch, aws)
    assert not aws.calls


def test_deployment_changes_and_model_changes_cannot_be_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aws = AWS()
    live = runtime(monkeypatch, aws)
    aws.change_during_call = True
    with pytest.raises(RuntimeError, match="deployment changed"):
        live.invoke("Price it")
    assert aws.body is not None and aws.body.closed
    aws.change_during_call = False
    live = live_runtime.LiveRuntime()
    live.invoke("First turn")
    aws.model = "another-model"
    with pytest.raises(RuntimeError, match="model changed"):
        live.invoke("Second turn")


@pytest.mark.parametrize(
    "failure",
    [
        "missing_evidence",
        "unsupported",
        "duplicate",
        "wrong_release",
        "wrong_session",
        "tool_error",
        "blocked",
        "runtime_error",
        "truncated",
    ],
)
def test_invalid_streams_never_become_verdicts(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    aws = AWS()
    live = runtime(monkeypatch, aws)
    # Derive one valid synthetic stream, then break its contract.
    live.invoke("Set up")
    assert aws.body is not None
    events = [
        json.loads(frame.removeprefix(b"data: "))
        for frame in aws.body.data.split(b"\r\n\r\n")
        if frame
    ]
    if failure == "missing_evidence":
        events.pop(1)
    elif failure == "unsupported":
        events[1]["schema_version"] = 2
    elif failure == "duplicate":
        events.insert(2, events[1])
    elif failure == "wrong_release":
        events[1]["release_id"] = "wrong"
    elif failure == "wrong_session":
        events[1]["session_id"] = "wrong"
    elif failure == "tool_error":
        events[1]["calls"][0]["tool_result"] = None
    elif failure == "blocked":
        events[2]["blocked"] = True
    elif failure == "runtime_error":
        events = [{"type": "error", "code": "agent_unavailable"}]
    else:
        events.pop()
    aws.events = events
    with pytest.raises((RuntimeError, ValueError)):
        live.invoke("Invalid turn")
    assert aws.body is not None and aws.body.closed

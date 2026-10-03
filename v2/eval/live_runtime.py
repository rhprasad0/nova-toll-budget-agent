"""Invoke the application currently serving this environment's public chat."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlparse
from uuid import uuid4

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=128)
    reasoning_effort: str = Field(min_length=1, max_length=32)
    max_output_tokens: int = Field(gt=0)


class RecordedCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool_use_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    input: dict[str, Any]
    tool_result: dict[str, Any]


class EvaluationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["evaluation"]
    schema_version: Literal[1]
    session_id: str
    release_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    application: ModelSettings
    calls: list[RecordedCall]


@dataclass(frozen=True)
class RuntimeTarget:
    runtime_arn: str
    endpoint: str
    runtime_version: str
    release_id: str
    proxy_version: str


class LiveRuntime:
    """Resolve live routing once and reject a deployment change during the run."""

    def __init__(self) -> None:
        environment = os.environ["ENVIRONMENT"]
        if environment not in {"development", "production"}:
            raise ValueError("Invalid evaluation environment")
        self.account = "920534282028" if environment == "production" else "903859731897"
        self.suffix = "" if environment == "production" else "-dev"
        self.runtime_prefix = "nova_toll_v2" + (
            "" if environment == "production" else "_development"
        )
        self.distribution = os.environ["EVAL_SITE_DISTRIBUTION_ID"]
        # AWS clients are dynamic; credentials and configuration never enter evidence.
        self.cloudfront = cast(Any, boto3.client("cloudfront", region_name="us-east-1"))  # pyright: ignore[reportUnknownMemberType]
        self.lambda_client = cast(Any, boto3.client("lambda", region_name="us-east-1"))  # pyright: ignore[reportUnknownMemberType]
        self.control = cast(
            Any,
            boto3.client("bedrock-agentcore-control", region_name="us-east-1"),  # pyright: ignore[reportUnknownMemberType]
        )
        self.client = cast(
            Any,
            boto3.client(  # pyright: ignore[reportUnknownMemberType]
                "bedrock-agentcore",
                region_name="us-east-1",
                endpoint_url=os.environ["AGENTCORE_VPCE_URL"],
                config=Config(read_timeout=180, retries={"total_max_attempts": 1}),
            ),
        )
        self.target = self.resolve()
        self.session_id = str(uuid4())
        self.application: ModelSettings | None = None

    def resolve(self) -> RuntimeTarget:
        distribution = self.cloudfront.get_distribution(Id=self.distribution)[
            "Distribution"
        ]
        if distribution["Status"] != "Deployed" or not distribution["ARN"].startswith(
            f"arn:aws:cloudfront::{self.account}:distribution/"
        ):
            raise RuntimeError("Evaluation routing is not deployed in this environment")
        config = distribution["DistributionConfig"]
        chat_origins = [
            origin
            for origin in config["Origins"]["Items"]
            if origin["Id"] == "public-chat"
        ]
        chat_behaviors = [
            behavior
            for behavior in config["CacheBehaviors"]["Items"]
            if behavior["PathPattern"] == "/api/*"
        ]
        if (
            len(chat_origins) != 1
            or len(chat_behaviors) != 1
            or chat_behaviors[0]["TargetOriginId"] != "public-chat"
        ):
            raise RuntimeError("Evaluation chat routing is invalid")
        matches: list[tuple[str, str]] = []
        for slot in ("blue", "green"):
            function = f"tollchat-v2-chat-proxy{self.suffix}" + (
                "-green" if slot == "green" else ""
            )
            arn = f"arn:aws:lambda:us-east-1:{self.account}:function:{function}"
            url = cast(
                str,
                self.lambda_client.get_function_url_config(
                    FunctionName=arn, Qualifier="live"
                )["FunctionUrl"],
            )
            if urlparse(url).hostname == chat_origins[0]["DomainName"]:
                matches.append((arn, slot))
        if len(matches) != 1:
            raise RuntimeError("Evaluation origin does not match a fixed live proxy")
        arn, slot = matches[0]
        alias = self.lambda_client.get_alias(FunctionName=arn, Name="live")
        version = alias["FunctionVersion"]
        if not re.fullmatch(r"[1-9][0-9]*", version) or alias.get(
            "RoutingConfig", {}
        ).get("AdditionalVersionWeights"):
            raise RuntimeError(
                "Evaluation proxy alias is not a single published version"
            )
        function = self.lambda_client.get_function_configuration(
            FunctionName=arn, Qualifier=version
        )
        if (
            function["FunctionArn"] != f"{arn}:{version}"
            or function["State"] != "Active"
        ):
            raise RuntimeError("Evaluation proxy identity is invalid")
        variables = function["Environment"]["Variables"]
        target = RuntimeTarget(
            variables["AGENTCORE_RUNTIME_ARN"],
            variables["AGENTCORE_RUNTIME_ENDPOINT"],
            variables["AGENTCORE_RUNTIME_VERSION"],
            variables["RELEASE_ID"],
            version,
        )
        expected_name = self.runtime_prefix + ("_green" if slot == "green" else "")
        if (
            not re.fullmatch(
                f"arn:aws:bedrock-agentcore:us-east-1:{self.account}:runtime/{expected_name}-[A-Za-z0-9]+",
                target.runtime_arn,
            )
            or target.endpoint != "preview"
            or not re.fullmatch(r"[1-9][0-9]*", target.runtime_version)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target.release_id)
        ):
            raise RuntimeError("Evaluation runtime identity is invalid")
        endpoint = self.control.get_agent_runtime_endpoint(
            agentRuntimeId=target.runtime_arn.rsplit("/", 1)[1],
            endpointName=target.endpoint,
        )
        if (
            endpoint["status"] != "READY"
            or endpoint["agentRuntimeVersion"] != target.runtime_version
        ):
            raise RuntimeError(
                "Evaluation runtime version does not match the live proxy"
            )
        return target

    def verify(self) -> None:
        if self.resolve() != self.target:
            raise RuntimeError("Application deployment changed during evaluation")

    def invoke(self, prompt: str) -> tuple[str, EvaluationEvidence]:
        self.verify()
        response = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.target.runtime_arn,
            qualifier=self.target.endpoint,
            runtimeSessionId=self.session_id,
            contentType="application/json",
            payload=json.dumps(
                {"prompt": prompt, "evaluation_marker": "scheduled-evaluation-v1"}
            ).encode(),
        )
        body = response["response"]
        try:
            if (
                response.get("statusCode") != 200
                or "text/event-stream" not in response["contentType"]
                or response.get("runtimeSessionId", self.session_id) != self.session_id
            ):
                raise RuntimeError("Invalid evaluation runtime response")
            buffer = b""
            size = 0
            answer: str | None = None
            evidence: EvaluationEvidence | None = None
            for chunk in body.iter_chunks(chunk_size=4096):
                size += len(chunk)
                if size > 2_000_000:
                    raise RuntimeError("Evaluation stream exceeds its bounded size")
                buffer += chunk
                while b"\n\n" in buffer or b"\r\n\r\n" in buffer:
                    match = re.search(rb"\r?\n\r?\n", buffer)
                    assert match is not None
                    frame, buffer = buffer[: match.start()], buffer[match.end() :]
                    data = b"\n".join(
                        line[5:].lstrip()
                        for line in frame.splitlines()
                        if line.startswith(b"data:")
                    )
                    if not data:
                        continue
                    event = json.loads(data)
                    if not isinstance(event, dict) or answer is not None:
                        raise RuntimeError("Invalid evaluation stream event order")
                    event = cast(dict[str, Any], event)
                    if event.get("type") == "evaluation":
                        if evidence is not None:
                            raise RuntimeError("Duplicate evaluation evidence")
                        evidence = EvaluationEvidence.model_validate(event)
                    elif event.get("type") == "answer":
                        if (
                            event.get("blocked") is not False
                            or not isinstance(event.get("text"), str)
                            or not event["text"].strip()
                        ):
                            raise RuntimeError(
                                "Evaluation application answer is blocked or empty"
                            )
                        answer = event["text"]
                    elif event.get("type") not in {"text", "tool"}:
                        raise RuntimeError(
                            "Evaluation runtime failed or emitted an unexpected event"
                        )
            if buffer.strip() or answer is None or evidence is None:
                raise RuntimeError(
                    "Evaluation stream is incomplete or has no private evidence"
                )
            if (
                evidence.session_id != self.session_id
                or evidence.release_id != self.target.release_id
            ):
                raise RuntimeError(
                    "Evaluation evidence has the wrong application identity"
                )
            if len({call.tool_use_id for call in evidence.calls}) != len(
                evidence.calls
            ):
                raise RuntimeError("Duplicate evaluation tool identity")
            if (
                self.application is not None
                and self.application != evidence.application
            ):
                raise RuntimeError("Application model changed during evaluation")
            self.application = evidence.application
            self.verify()
            return answer, evidence
        finally:
            body.close()

    def metadata(self) -> dict[str, Any]:
        if self.application is None:
            raise RuntimeError("No deployed application metadata was recorded")
        return {
            "release_id": self.target.release_id,
            "runtime_version": self.target.runtime_version,
        }

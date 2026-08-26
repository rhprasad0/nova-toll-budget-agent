"""Strands agent for current and annualized Northern Virginia toll pricing."""

from __future__ import annotations

import json
import sys
from copy import copy, deepcopy
from datetime import date, datetime
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal, cast, override
from zoneinfo import ZoneInfo

import boto3
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from strands import Agent
from strands.hooks import (
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookOrder,
    HookProvider,
    HookRegistry,
)
from strands.models.openai_responses import OpenAIResponsesModel
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

from agent_tools import validate_toll_route as route_validation
from agent_tools.get_annual_toll_ballpark import get_annual_toll_ballpark
from agent_tools.get_current_toll_price import get_current_toll_price

_AWS_REGION = "us-east-1"
_OPENAI_API_KEY_PARAMETER = "/nova-toll/openai_api_key"
_OPENAI_BASE_URL = "https://api.openai.com/v1"
_PROMPT_POINTS_SQL = "SELECT oracle.get_toll_route_prompt_points() AS points"
SYSTEM_PROMPT_VERSION = "2.0.2"
SYSTEM_PROMPT_RENDERER_VERSION = "1.0.0"
_EASTERN = ZoneInfo("America/New_York")
_DUPLICATE_TOOL_STATE_KEY = "tollchat_v2_duplicate_tool_calls"
_DUPLICATE_HOOK_ORDER = HookOrder.SDK_LAST + 1
_DUPLICATE_TOOL_MESSAGE = (
    "This exact tool call already ran during this request. "
    "Use its previous result and continue."
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _GeoJSONPoint(_Model):
    type: Literal["Point"]
    coordinates: Annotated[list[float], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def _validate_range(self) -> _GeoJSONPoint:
        longitude, latitude = self.coordinates
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("prompt point coordinates are out of range")
        return self


class _PromptPoint(_Model):
    point_id: str = Field(min_length=1)
    network_id: Literal[
        "i95", "i495", "i66", "dtr", "greenway", "airport_iad", "airport_dca"
    ]
    source_node_id: str = Field(min_length=1)
    point_type: Literal["entry", "exit", "airport"]
    direction: Literal["NB", "SB", "EB", "WB"] | None
    label: str = Field(min_length=1)
    aliases: list[str]
    location: _GeoJSONPoint

    @model_validator(mode="after")
    def _validate_airport_direction(self) -> _PromptPoint:
        if (self.point_type == "airport") != (self.direction is None):
            raise ValueError("airport point and direction are inconsistent")
        return self


type _PromptPoints = Annotated[list[_PromptPoint], Field(min_length=1, max_length=500)]
_PROMPT_POINTS_ADAPTER: TypeAdapter[_PromptPoints] = TypeAdapter(_PromptPoints)


def parse_prompt_points(value: object) -> list[_PromptPoint]:
    """Validate the bounded, deterministic prompt payload returned by Oracle."""
    points = _PROMPT_POINTS_ADAPTER.validate_python(value)
    point_ids = [point.point_id for point in points]
    if any(first >= second for first, second in pairwise(point_ids)):
        raise ValueError("prompt point IDs must be unique and strictly ordered")
    return points


def load_prompt_points() -> list[_PromptPoint]:
    """Load prompt-only point data through the tollchat_agent database surface."""
    connection = cast(Any, route_validation.connect_to_database())
    error: Exception | None = None
    rows: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(_PROMPT_POINTS_SQL)
            rows = cast(list[dict[str, Any]], cursor.fetchall())
    except Exception as query_error:
        error = query_error
    try:
        connection.close()
    except Exception as close_error:
        if error is None:
            error = close_error
        else:
            error.add_note(
                f"Connection close also failed: {type(close_error).__name__}"
            )
    if error is not None:
        raise error
    if len(rows) != 1 or set(rows[0]) != {"points"}:
        raise ValueError("prompt-point query must return exactly one points row")
    return parse_prompt_points(rows[0]["points"])


class _CachedResponsesModel(OpenAIResponsesModel):
    """Place the stable developer prompt before variable conversation input."""

    @override
    def _format_request(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        tool_choice: ToolChoice | None = None,
        model_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = super()._format_request(
            messages, tool_specs, None, tool_choice, model_state
        )
        if system_prompt:
            cast(list[dict[str, Any]], request["input"]).insert(
                0,
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_prompt,
                            "prompt_cache_breakpoint": {"mode": "explicit"},
                        }
                    ],
                },
            )
        return request

    @override
    def _format_chunk(self, event: dict[str, Any]) -> StreamEvent:
        chunk = super()._format_chunk(event)
        if event["chunk_type"] == "metadata":
            details = getattr(event["data"], "input_tokens_details", None)
            written = getattr(details, "cache_write_tokens", None)
            if isinstance(written, int) and written > 0:
                cast(Any, chunk)["metadata"]["usage"]["cacheWriteInputTokens"] = written
        return chunk


def load_openai_api_key() -> str:
    ssm = cast(
        Any,
        boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "ssm", region_name=_AWS_REGION
        ),
    )
    value = ssm.get_parameter(
        Name=_OPENAI_API_KEY_PARAMETER,
        WithDecryption=True,
    )["Parameter"]["Value"]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{_OPENAI_API_KEY_PARAMETER} is empty")
    return value


def _build_model() -> _CachedResponsesModel:
    return _CachedResponsesModel(
        model_id="gpt-5.6-luna",
        client_args={
            "api_key": load_openai_api_key(),
            "base_url": _OPENAI_BASE_URL,
        },
        params={
            "max_output_tokens": 2048,
            "reasoning": {"effort": "low"},
            "prompt_cache_key": "tollchat-agent-v2",
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        },
        stateful=False,
    )


class _DuplicateToolUseState:
    def __init__(self) -> None:
        self.owners: dict[tuple[str, str], str] = {}
        self.lock = Lock()


class DuplicateToolUseGuard(HookProvider):
    """Suppress exact repeated successful tool calls within one invocation."""

    def register_hooks(self, registry: HookRegistry, **_kwargs: object) -> None:
        registry.add_callback(
            BeforeInvocationEvent, self.before_invocation, order=HookOrder.SDK_FIRST
        )
        registry.add_callback(
            BeforeToolCallEvent, self.before_tool, order=_DUPLICATE_HOOK_ORDER
        )
        registry.add_callback(
            AfterToolCallEvent, self.after_tool, order=_DUPLICATE_HOOK_ORDER
        )

    def before_invocation(self, event: BeforeInvocationEvent) -> None:
        event.invocation_state[_DUPLICATE_TOOL_STATE_KEY] = _DuplicateToolUseState()

    @staticmethod
    def _signature(event: BeforeToolCallEvent | AfterToolCallEvent) -> tuple[str, str]:
        return (
            event.tool_use["name"],
            json.dumps(
                event.tool_use["input"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )

    @staticmethod
    def _state(
        event: BeforeToolCallEvent | AfterToolCallEvent,
    ) -> _DuplicateToolUseState:
        return cast(
            _DuplicateToolUseState,
            event.invocation_state[_DUPLICATE_TOOL_STATE_KEY],
        )

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        if event.cancel_tool:
            return
        state = self._state(event)
        signature = self._signature(event)
        with state.lock:
            if signature in state.owners:
                event.cancel_tool = _DUPLICATE_TOOL_MESSAGE
                return
            state.owners[signature] = event.tool_use["toolUseId"]

    def after_tool(self, event: AfterToolCallEvent) -> None:
        if event.result.get("status") == "success" and not event.retry:
            return
        state = self._state(event)
        signature = self._signature(event)
        with state.lock:
            if state.owners.get(signature) == event.tool_use["toolUseId"]:
                state.owners.pop(signature)


_AGENT_TOOLS = (get_current_toll_price, get_annual_toll_ballpark)


def _agent_tools() -> list[Any]:
    tools: list[Any] = []
    for tool in _AGENT_TOOLS:
        cloned = copy(tool)
        cloned.tool_spec = deepcopy(tool.tool_spec)
        tools.append(cloned)
    return tools


def _render_system_prompt_values(
    prompt_points: list[dict[str, object]] | list[_PromptPoint] | None = None,
    *,
    current_date: date,
) -> dict[str, str]:
    points = (
        load_prompt_points()
        if prompt_points is None
        else parse_prompt_points(
            [
                point.model_dump(mode="python")
                if isinstance(point, _PromptPoint)
                else point
                for point in prompt_points
            ]
        )
    )
    return {
        "PROMPT_POINTS_JSON": json.dumps(
            [point.model_dump(mode="json") for point in points], indent=2
        ),
        "CURRENT_DATE": current_date.strftime("%-m/%-d/%Y"),
    }


def build_system_prompt(
    prompt_points: list[dict[str, object]] | list[_PromptPoint] | None = None,
    *,
    current_date: date | None = None,
) -> str:
    template = (
        Path(__file__).resolve().parent.parent
        / "agent-sops"
        / "nova-toll-pricing-assistant.sop.md"
    ).read_text(encoding="utf-8")
    return template.format(
        **_render_system_prompt_values(
            prompt_points,
            current_date=current_date or datetime.now(_EASTERN).date(),
        )
    )


def build_agent(
    *,
    prompt_points: list[dict[str, object]] | list[_PromptPoint] | None = None,
    hooks: list[object] | None = None,
) -> Agent:
    system_prompt = build_system_prompt(prompt_points)
    trace_attributes = {
        "tollchat.system_prompt_version": SYSTEM_PROMPT_VERSION,
        "tollchat.system_prompt_renderer_version": SYSTEM_PROMPT_RENDERER_VERSION,
        "tollchat.system_prompt_sha256": sha256(system_prompt.encode()).hexdigest(),
    }
    return Agent(
        model=_build_model(),
        tools=_agent_tools(),
        system_prompt=system_prompt,
        callback_handler=None,
        trace_attributes=trace_attributes,
        hooks=cast(Any, [DuplicateToolUseGuard(), *(hooks or [])]),
    )


if __name__ == "__main__":
    agent = build_agent()
    prompt = (
        " ".join(sys.argv[1:]) or "What is the current toll from Leesburg to Route 28?"
    )
    print(agent(prompt))

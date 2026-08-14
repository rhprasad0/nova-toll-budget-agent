"""Strands construction and structured multi-turn state for the orchestrator."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast, override
from zoneinfo import ZoneInfo

import boto3
from strands import Agent
from strands.agent.agent_result import AgentResult
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

from orchestrator import routing
from orchestrator.schemas import OrchestratorTurn, RoutePlan, TripState

SYSTEM_PROMPT_VERSION = "0.1.0"
TOOLSET_VERSION = "0.1.0"
_EASTERN = ZoneInfo("America/New_York")
_OPENAI_API_KEY_PARAMETER = "/nova-toll/openai_api_key"
_DUPLICATE_STATE_KEY = "tollchat_orchestrator_duplicate_calls"
_ROUTE_PLANS_STATE_KEY = "tollchat_orchestrator_route_plans"
_DUPLICATE_MESSAGE = (
    "This exact tool call already succeeded during this turn. "
    "Use its earlier result and continue."
)


class _CachedResponsesModel(OpenAIResponsesModel):
    """Cache the large unchanged routing prompt before conversation input."""

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
            if isinstance(written, int):
                cast(Any, chunk)["metadata"]["usage"]["cacheWriteInputTokens"] = written
        return chunk


def _load_openai_api_key() -> str:
    ssm = cast(
        Any,
        boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "ssm", region_name="us-east-1"
        ),
    )
    value = ssm.get_parameter(Name=_OPENAI_API_KEY_PARAMETER, WithDecryption=True)[
        "Parameter"
    ]["Value"]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{_OPENAI_API_KEY_PARAMETER} is empty")
    return value


def _build_model() -> _CachedResponsesModel:
    return _CachedResponsesModel(
        model_id="gpt-5.6-luna",
        client_args={
            "api_key": _load_openai_api_key(),
            "base_url": "https://api.openai.com/v1",
        },
        params={
            "max_output_tokens": 4096,
            "reasoning": {"effort": "low"},
            "prompt_cache_key": "tollchat-orchestrator-v1",
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        },
        # Strands ends structured turns with an unacknowledged output-tool call,
        # so chaining that response ID breaks the next conversation turn.
        stateful=False,
    )


class _DuplicateCallState:
    def __init__(self) -> None:
        self.owners: dict[tuple[str, str], str] = {}
        self.lock = Lock()


class DuplicateToolUseGuard(HookProvider):
    """Suppress exact repeated successful calls within one invocation."""

    def register_hooks(self, registry: HookRegistry, **kwargs: object) -> None:
        registry.add_callback(
            BeforeInvocationEvent, self.before_invocation, order=HookOrder.SDK_FIRST
        )
        registry.add_callback(
            BeforeToolCallEvent, self.before_tool, order=HookOrder.SDK_LAST + 1
        )
        registry.add_callback(
            AfterToolCallEvent, self.after_tool, order=HookOrder.SDK_LAST + 1
        )

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
    def _state(event: BeforeToolCallEvent | AfterToolCallEvent) -> _DuplicateCallState:
        return cast(_DuplicateCallState, event.invocation_state[_DUPLICATE_STATE_KEY])

    def before_invocation(self, event: BeforeInvocationEvent) -> None:
        event.invocation_state[_DUPLICATE_STATE_KEY] = _DuplicateCallState()

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        if event.cancel_tool:
            return
        state = self._state(event)
        signature = self._signature(event)
        with state.lock:
            if signature in state.owners:
                event.cancel_tool = _DUPLICATE_MESSAGE
            else:
                state.owners[signature] = event.tool_use["toolUseId"]

    def after_tool(self, event: AfterToolCallEvent) -> None:
        if event.result.get("status") == "success" and not event.retry:
            return
        state = self._state(event)
        signature = self._signature(event)
        with state.lock:
            if state.owners.get(signature) == event.tool_use["toolUseId"]:
                state.owners.pop(signature)


class RoutePlanRecorder(HookProvider):
    """Keep successful route-tool output outside model-controlled state."""

    def register_hooks(self, registry: HookRegistry, **kwargs: object) -> None:
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    @staticmethod
    def after_tool(event: AfterToolCallEvent) -> None:
        if (
            event.tool_use["name"] != "plan_toll_route"
            or event.result["status"] != "success"
            or event.retry
        ):
            return
        plans = cast(
            dict[str, dict[str, object]],
            event.invocation_state.setdefault(_ROUTE_PLANS_STATE_KEY, {}),
        )
        for content in event.result["content"]:
            value = content.get("json")
            text_content = content.get("text")
            if value is None and isinstance(text_content, str):
                try:
                    value = json.loads(text_content)
                except json.JSONDecodeError:
                    continue
            if not isinstance(value, dict):
                continue
            route_value = cast(dict[str, object], value)
            if route_value.get("status") != "ready":
                continue
            try:
                plan = RoutePlan.model_validate(route_value)
            except ValueError:
                continue
            plans[plan.route_plan_id] = plan.model_dump(mode="json")


_LOCATION_ALIASES = {
    "Tysons": [
        "Jones Branch Drive/Route 123",
        "Route 123 - Dolley Madison Blvd",
        "I-495 Express Lanes N",
        "Westpark Drive",
    ],
    "McLean": ["Route 123 - Dolley Madison Blvd", "Jones Branch Drive/Route 123"],
    "Washington": ["Washington", "Washington D.C."],
    "Arlington": [
        "Exit 73 - Rosslyn",
        "Exit 75 - Pentagon/Alexandria",
        "Fairfax Drive",
        "Glebe Road",
        "Washington Blvd",
        "Shirlington Circle",
    ],
    "Ballston": ["Fairfax Drive", "Glebe Road"],
    "Vienna": ["Route 123 - Dolley Madison Blvd", "Fairfax Drive"],
    "Herndon": [
        "Exit 14 - SR 674 (Hunter Mill Rd)",
        "Exit 15 - SR 676 (Wolf Trap)",
    ],
}
_AIRPORT_ALIASES = {
    "IAD": {
        "corridor": "airport_iad",
        "label": routing.AIRPORT_ENDPOINTS["airport_iad"],
    },
    "Dulles Airport": {
        "corridor": "airport_iad",
        "label": routing.AIRPORT_ENDPOINTS["airport_iad"],
    },
    "DCA": {
        "corridor": "airport_dca",
        "label": routing.AIRPORT_ENDPOINTS["airport_dca"],
    },
    "Reagan Airport": {
        "corridor": "airport_dca",
        "label": routing.AIRPORT_ENDPOINTS["airport_dca"],
    },
}


def build_system_prompt(*, now: datetime | None = None) -> str:
    template = (Path(__file__).with_name("prompt.md")).read_text()
    current = (now or datetime.now(_EASTERN)).astimezone(_EASTERN)
    return template.format(
        CURRENT_INSTANT=current.isoformat(),
        LOCATION_ORACLE=json.dumps(routing.location_oracle_for_prompt(), indent=2),
        LOCATION_ALIASES=json.dumps(_LOCATION_ALIASES, indent=2),
        AIRPORT_ALIASES=json.dumps(_AIRPORT_ALIASES, indent=2),
    )


def build_agent(*, hooks: list[object] | None = None) -> Agent:
    agent = Agent(
        model=_build_model(),
        tools=list(routing.AGENT_TOOLS),
        system_prompt=build_system_prompt(),
        callback_handler=None,
        trace_attributes={
            "tollchat.system_prompt_version": SYSTEM_PROMPT_VERSION,
            "tollchat.toolset_version": TOOLSET_VERSION,
        },
        hooks=cast(Any, [DuplicateToolUseGuard(), RoutePlanRecorder(), *(hooks or [])]),
    )
    agent.state.set("trip_state", TripState().model_dump(mode="json"))
    return agent


def _same_trip_definition(first: TripState, second: TripState) -> bool:
    return (
        first.origin == second.origin
        and first.destination == second.destination
        and first.requested_at == second.requested_at
    )


def _validate_transition(
    previous: TripState,
    state: TripState,
    issued_route_plans: dict[str, dict[str, object]],
) -> TripState:
    if state.status == "ready" and state.route_plan is None:
        raise ValueError("ready trip state requires a route plan")
    if state.route_plan is not None:
        if state.status != "ready":
            raise ValueError("a state with a route plan must be ready")
        if state.requested_at != state.route_plan.requested_at:
            raise ValueError("trip state and route plan times differ")
        if state.origin is None or state.destination is None:
            raise ValueError("route plan requires both trip endpoints")
        if (
            state.origin.corridor != state.route_plan.origin.corridor
            or state.destination.corridor != state.route_plan.destination.corridor
        ):
            raise ValueError("trip state and route plan corridors differ")
        for endpoint, canonical, role in (
            (state.origin, state.route_plan.origin, "origin"),
            (state.destination, state.route_plan.destination, "destination"),
        ):
            if endpoint.location.casefold() not in {
                canonical.label.casefold(),
                canonical.node_id.casefold(),
            }:
                raise ValueError(f"trip state and route plan {role} differ")
        if issued_route_plans.get(state.route_plan.route_plan_id) != (
            state.route_plan.model_dump(mode="json")
        ):
            raise ValueError("route plan was not returned unchanged by plan_toll_route")
        if (
            previous.route_plan is not None
            and not _same_trip_definition(previous, state)
            and previous.route_plan.route_plan_id == state.route_plan.route_plan_id
        ):
            raise ValueError("changed trip facts cannot reuse the old route plan")
    return state


class OrchestratorSession:
    """One in-memory conversation with validated trip state outside prose history."""

    def __init__(self, agent: Agent | None = None) -> None:
        self.agent = agent or build_agent()
        self.state = TripState.model_validate(self.agent.state.get("trip_state"))
        self._issued_route_plans: dict[str, dict[str, object]] = {}
        self.last_result: AgentResult | None = None

    def chat(self, message: str) -> OrchestratorTurn:
        if not message.strip():
            raise ValueError("message is required")
        prompt = (
            "Validated trip state before this user turn:\n"
            f"{self.state.model_dump_json()}\n\n"
            "User message:\n"
            f"{message.strip()}"
        )
        invocation_state: dict[str, object] = {_ROUTE_PLANS_STATE_KEY: {}}
        result = self.agent(
            prompt,
            structured_output_model=OrchestratorTurn,
            structured_output_prompt=(
                "Return a concise user-facing message and the complete updated TripState. "
                "Copy any successful RoutePlan exactly from plan_toll_route."
            ),
            invocation_state=invocation_state,
        )
        self.last_result = result
        if result.structured_output is None:
            raise RuntimeError("orchestrator returned no structured turn")
        turn = OrchestratorTurn.model_validate(result.structured_output)
        current_plans = cast(
            dict[str, dict[str, object]], invocation_state[_ROUTE_PLANS_STATE_KEY]
        )
        eligible_plans = (
            current_plans
            if not _same_trip_definition(self.state, turn.state)
            else {**self._issued_route_plans, **current_plans}
        )
        self.state = _validate_transition(self.state, turn.state, eligible_plans)
        self._issued_route_plans = eligible_plans
        self.agent.state.set("trip_state", self.state.model_dump(mode="json"))
        return turn


def main() -> None:
    session = OrchestratorSession()
    message = " ".join(sys.argv[1:]) or "Plan a trip from I-66 West to Westmoreland St"
    turn = session.chat(message)
    print(turn.message)
    print(turn.state.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

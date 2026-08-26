"""Strands adapter for the current toll pricing domain."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

from strands import tool  # pyright: ignore[reportUnknownVariableType]
from strands.types.tools import ToolContext, ToolSpec

from agent_tools import current_price_domain as _domain

TOOL_SPEC = cast(ToolSpec, _domain.TOOL_SPEC)
TOOL_CONTRACT = _domain.TOOL_CONTRACT


@tool(
    name=TOOL_SPEC["name"],
    description=TOOL_SPEC["description"],
    inputSchema=TOOL_SPEC["inputSchema"],
    context="tool_context",
)
async def get_current_toll_price(
    tool_context: ToolContext,
) -> AsyncGenerator[dict[str, Any]]:
    async for event in _domain.get_current_toll_price(tool_context):
        yield event


get_current_toll_price.tool_spec = TOOL_SPEC  # pyright: ignore[reportAttributeAccessIssue]


def __getattr__(name: str) -> Any:  # noqa: ANN401
    """Keep characterized helpers reachable during the module split."""
    return getattr(_domain, name)

"""Resolve user-named places to catalog point IDs for one trip leg.

Pure code over the public point catalog and the committed route graph: exact
label or alias matching chooses the places, and graph reachability settles the
entry/exit roles, directions and approach variants. It never guesses.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from strands import tool  # pyright: ignore[reportUnknownVariableType]
from strands.types.tools import AgentTool, ToolContext, ToolSpec

from agent_tools.route_pairs import REACHABLE_PAIRS

type Facility = Literal["i66", "dtr", "greenway", "i95", "i495"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _ResolveRequest(_Model):
    origin: str = Field(
        min_length=1,
        description="Origin place exactly as the user named it (catalog label, exit name, road, or alias).",
    )
    destination: str = Field(
        min_length=1,
        description="Destination place exactly as the user named it.",
    )
    facility: Facility | None = Field(
        default=None,
        description="Road the user named for this leg, if any: i66 (I-66), dtr (Dulles Toll Road, Route 267), greenway (Dulles Greenway), i95 (I-95/I-395 Express Lanes), i495 (I-495 Express Lanes, Beltway). Omit when the user named none.",
    )


class _Point(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    point_id: str
    network_id: str
    point_type: Literal["entry", "exit", "airport"]
    direction: Literal["NB", "SB", "EB", "WB"] | None
    label: str
    aliases: list[str]


_POINTS_ADAPTER: TypeAdapter[list[_Point]] = TypeAdapter(list[_Point])
_APPROACH = re.compile(r"\s*\(from [^)]*\)\s*$", re.IGNORECASE)
_NON_WORD = re.compile(r"[^a-z0-9]+")
_ORIGIN_ROLES = {"entry", "airport"}
_DESTINATION_ROLES = {"exit", "airport"}
_MAX_CANDIDATES = 12

_INPUT_SCHEMA: dict[str, Any] = _ResolveRequest.model_json_schema(mode="validation")
TOOL_SPEC: dict[str, Any] = {
    "name": "resolve_trip",
    "description": (
        "Resolve one trip leg's origin and destination places to the canonical "
        "point IDs the pricing tools require. Pass each place exactly as the user "
        "named it, plus the road the user named for the leg if any. The resolver "
        "matches catalog labels and aliases and settles entry/exit roles, travel "
        "direction, approach variants and cross-facility trips from the route "
        "graph. Call it once per trip with places the user actually supplied: a "
        "resolved result also carries return_leg, the same two places swapped, "
        "for a round trip. Use the returned IDs verbatim. It returns ambiguous "
        "candidates instead of guessing, and reports wrong-role matches for "
        "route validation."
    ),
    "inputSchema": {"json": _INPUT_SCHEMA},
}
TOOL_CONTRACT: dict[str, Any] = {"toolSpec": TOOL_SPEC}


def _loose(text: str) -> str:
    return " ".join(text.casefold().split())


def _normalize(text: str) -> str:
    return _NON_WORD.sub(" ", text.casefold()).strip()


class _Catalog:
    def __init__(self, points: Iterable[Any]) -> None:
        raw = [
            point.model_dump() if isinstance(point, BaseModel) else point
            for point in points
        ]
        self.points = _POINTS_ADAPTER.validate_python(raw)
        self.labels = {
            point.point_id: {
                _loose(point.label),
                _loose(_APPROACH.sub("", point.label)),
            }
            for point in self.points
        }
        self.names = {
            point.point_id: {
                _normalize(point.label),
                _normalize(_APPROACH.sub("", point.label)),
                *(_normalize(alias) for alias in point.aliases),
            }
            for point in self.points
        }

    def _search(self, points: list[_Point], text: str) -> list[_Point]:
        """Exact label, then exact alias, then all words; approach suffixes name a place."""
        text = _APPROACH.sub("", text)
        loose, query = _loose(text), _normalize(text)
        tokens = set(query.split())
        if not tokens:
            return []
        for keep in (
            lambda p: loose in self.labels[p.point_id],
            lambda p: query in self.names[p.point_id],
            lambda p: any(tokens <= set(n.split()) for n in self.names[p.point_id]),
        ):
            found = [point for point in points if keep(point)]
            if found:
                return found
        return []

    def matches(self, text: str, facility: Facility | None) -> list[_Point]:
        # A named road is searched first; a place absent from it crosses facilities.
        if facility:
            found = self._search(
                [point for point in self.points if point.network_id == facility], text
            )
            if found:
                return found
        return self._search(self.points, text)


def _describe(point: _Point) -> dict[str, str]:
    return {"point_id": point.point_id, "label": point.label}


def resolve(
    catalog: _Catalog | Iterable[Any],
    origin: str,
    destination: str,
    facility: Facility | None = None,
) -> dict[str, Any]:
    """Resolve a trip; a resolved leg also carries its swapped return leg."""
    if not isinstance(catalog, _Catalog):
        catalog = _Catalog(catalog)
    result = _leg(catalog, origin, destination, facility)
    if result["status"] == "resolved":
        result["return_leg"] = _leg(catalog, destination, origin, facility)
    return result


def _leg(
    catalog: _Catalog, origin: str, destination: str, facility: Facility | None
) -> dict[str, Any]:
    origin_matches = catalog.matches(origin, facility)
    destination_matches = catalog.matches(destination, facility)
    missing = [
        place
        for place, matches in (
            (origin, origin_matches),
            (destination, destination_matches),
        )
        if not matches
    ]
    if missing:
        return {"status": "not_found", "places": missing}
    origins = [p for p in origin_matches if p.point_type in _ORIGIN_ROLES]
    destinations = [
        p for p in destination_matches if p.point_type in _DESTINATION_ROLES
    ]
    pairs = [
        (o, d)
        for o in origins
        for d in destinations
        if (o.point_id, d.point_id) in REACHABLE_PAIRS
    ]
    if len(pairs) == 1:
        o, d = pairs[0]
        return {
            "status": "resolved",
            "origin_point_id": o.point_id,
            "origin_label": o.label,
            "destination_point_id": d.point_id,
            "destination_label": d.label,
        }
    if pairs:
        return {
            "status": "ambiguous",
            "candidates": [
                {
                    "origin_point_id": o.point_id,
                    "origin_label": o.label,
                    "destination_point_id": d.point_id,
                    "destination_label": d.label,
                }
                for o, d in pairs[:_MAX_CANDIDATES]
            ],
            "truncated": len(pairs) > _MAX_CANDIDATES,
        }
    if not origins or not destinations:
        return {
            "status": "wrong_role",
            "origin_matches": [_describe(p) for p in origin_matches],
            "destination_matches": [_describe(p) for p in destination_matches],
        }
    return {
        "status": "no_route",
        "origin_matches": [_describe(p) for p in origins],
        "destination_matches": [_describe(p) for p in destinations],
    }


def make_resolve_trip_tool(points: Iterable[Any]) -> AgentTool:
    """Bind the resolver to one catalog (the same list rendered into the prompt)."""
    catalog = _Catalog(points)
    spec = cast(ToolSpec, deepcopy(TOOL_SPEC))

    @tool(
        name=spec["name"],
        description=spec["description"],
        inputSchema=spec["inputSchema"],
        context="tool_context",
    )
    def resolve_trip(tool_context: ToolContext) -> dict[str, Any]:
        use = tool_context.tool_use
        try:
            request = _ResolveRequest.model_validate(use["input"])
        except ValidationError:
            return {
                "toolUseId": use["toolUseId"],
                "status": "error",
                "content": [{"text": "Unable to resolve the trip: invalid input."}],
            }
        payload = resolve(
            catalog, request.origin, request.destination, request.facility
        )
        return {
            "toolUseId": use["toolUseId"],
            "status": "success",
            "content": [{"json": payload}],
        }

    resolve_trip.tool_spec = spec
    return resolve_trip

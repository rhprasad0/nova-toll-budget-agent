"""Validated public contracts for the route-ready orchestrator."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type Corridor = Literal[
    "i95",
    "i495",
    "i66_itb",
    "dulles_toll_road",
    "dulles_greenway",
    "airport_iad",
    "airport_dca",
]
type Direction = Literal["Northbound", "Southbound"]
type TollDirection = Literal["Northbound", "Southbound", "EB", "WB"]


def content_fingerprint(prefix: str, value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()}"


def require_aware_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return value


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class I95DirectionRequest(ContractModel):
    requested_at: str = Field(
        description="ISO 8601 departure instant with an explicit UTC offset."
    )


class LaneObservation(ContractModel):
    direction: Direction
    od_pair_id: int
    corridor_name: Literal["I-95-NB", "I-95-SB"]
    link_status: str
    effective_at: str
    observed_at: str

    _effective_at = field_validator("effective_at")(require_aware_iso)
    _observed_at = field_validator("observed_at")(require_aware_iso)


class I95DirectionResult(ContractModel):
    status: Literal["supported", "unavailable"]
    requested_at: str
    source_kind: Literal["observed"]
    open_direction: Direction | None
    observations: list[LaneObservation]
    validation_id: str
    reason_code: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "supported":
            require_aware_iso(self.requested_at)
            if self.open_direction is None:
                raise ValueError("supported direction evidence needs open_direction")
            if self.reason_code is not None or self.reason is not None:
                raise ValueError("supported direction evidence cannot contain a reason")
            if {item.direction for item in self.observations} != {
                "Northbound",
                "Southbound",
            } or len(self.observations) != 2:
                raise ValueError(
                    "supported evidence needs one observation per direction"
                )
            expected = {
                "Northbound": (1132, "I-95-NB", "NORTHBOUND_OPEN"),
                "Southbound": (1151, "I-95-SB", "SOUTHBOUND_OPEN"),
            }
            if any(
                (item.od_pair_id, item.corridor_name) != expected[item.direction][:2]
                for item in self.observations
            ):
                raise ValueError(
                    "direction observation identifies the wrong status row"
                )
            if len({item.effective_at for item in self.observations}) != 1:
                raise ValueError(
                    "direction observations must share an effective interval"
                )
            open_directions = [
                item.direction
                for item in self.observations
                if item.link_status == expected[item.direction][2]
            ]
            if open_directions != [self.open_direction]:
                raise ValueError("open_direction contradicts the lane observations")
        elif self.open_direction is not None or not self.reason_code or not self.reason:
            raise ValueError(
                "unavailable direction evidence needs a reason and no direction"
            )
        return self


class AccessConstraint(ContractModel):
    location: str
    role: Literal["entry", "exit"]
    required_direction: TollDirection
    available_directions: list[TollDirection]
    nearby_options: list[str]


class I95AccessRequest(ContractModel):
    origin_corridor: Corridor
    origin: str
    destination_corridor: Corridor
    destination: str
    direction_result: dict[str, object]


class I95AccessResult(ContractModel):
    status: Literal[
        "supported",
        "one_way_mismatch",
        "direction_closed",
        "unavailable",
        "unsupported",
        "invalid_evidence",
    ]
    origin_corridor: Corridor
    origin: str
    destination_corridor: Corridor
    destination: str
    requested_at: str | None = None
    open_direction: Direction | None = None
    required_direction: Direction | None = None
    movement: Literal["direct", "i95_to_i495", "i495_to_i95"] | None = None
    entry_node_id: str | None = None
    exit_node_id: str | None = None
    constraints: list[AccessConstraint] = Field(default_factory=lambda: [])
    validation_id: str | None = None
    reason: str | None = None

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: str | None) -> str | None:
        return require_aware_iso(value) if value is not None else None

    @model_validator(mode="after")
    def validate_supported(self) -> Self:
        if self.status != "invalid_evidence" and self.validation_id is None:
            raise ValueError("issued access evidence needs validation_id")
        if self.status == "supported" and (
            self.open_direction is None
            or self.required_direction is None
            or self.movement is None
            or self.entry_node_id is None
            or self.exit_node_id is None
            or self.validation_id is None
        ):
            raise ValueError("supported access evidence is incomplete")
        return self


class RouteRequest(ContractModel):
    origin_corridor: Corridor
    origin: str
    destination_corridor: Corridor
    destination: str
    requested_at: str
    i95_direction_result: dict[str, object] | None = None
    i95_access_result: dict[str, object] | None = None


class CanonicalEndpoint(ContractModel):
    corridor: Corridor
    node_id: str
    label: str


class TollStep(ContractModel):
    route_step_id: str
    kind: Literal["toll"] = "toll"
    facility: Literal["i95", "i495", "i66_itb", "dulles_toll_road", "dulles_greenway"]
    direction: TollDirection
    entry_node_id: str
    exit_node_id: str


class ConnectorStep(ContractModel):
    route_step_id: str
    kind: Literal["connector"] = "connector"
    transfer_id: str
    description: str


class UnpricedStep(ContractModel):
    route_step_id: str
    kind: Literal["unpriced"] = "unpriced"
    description: str


type RouteStep = Annotated[
    TollStep | ConnectorStep | UnpricedStep, Field(discriminator="kind")
]


class I95Validation(ContractModel):
    direction: I95DirectionResult
    access: I95AccessResult | None = None


class RoutePlan(ContractModel):
    route_plan_id: str
    status: Literal["ready"] = "ready"
    requested_at: str
    origin: CanonicalEndpoint
    destination: CanonicalEndpoint
    i95_validation: I95Validation | None = None
    steps: list[RouteStep]
    routing_note: str | None = None

    _requested_at = field_validator("requested_at")(require_aware_iso)

    @model_validator(mode="after")
    def validate_steps(self) -> Self:
        if not self.steps:
            raise ValueError("route plan needs at least one step")
        expected = [f"step-{number}" for number in range(1, len(self.steps) + 1)]
        if [step.route_step_id for step in self.steps] != expected:
            raise ValueError("route_step_id values must be sequential and stable")
        content = self.model_dump(mode="json", exclude={"route_plan_id"})
        if self.route_plan_id != content_fingerprint("plan", content):
            raise ValueError("route_plan_id does not match the immutable plan contents")
        return self


class RouteProblem(ContractModel):
    status: Literal[
        "one_way_mismatch",
        "validation_failed",
        "unsupported",
        "invalid_request",
    ]
    reason: str
    constraints: list[AccessConstraint] = Field(default_factory=lambda: [])
    valid_options: list[str] = Field(default_factory=lambda: [])


class TripEndpoint(ContractModel):
    corridor: Corridor
    location: str


class TripState(ContractModel):
    status: Literal["collecting", "validating", "ready"] = "collecting"
    origin: TripEndpoint | None = None
    destination: TripEndpoint | None = None
    requested_at: str | None = None
    requested_analyses: list[Literal["discrete", "historical"]] = Field(
        default_factory=lambda: ["discrete"]
    )
    pending_clarification: str | None = None
    route_plan: RoutePlan | None = None

    @field_validator("requested_at")
    @classmethod
    def validate_trip_time(cls, value: str | None) -> str | None:
        return require_aware_iso(value) if value is not None else None


class OrchestratorTurn(ContractModel):
    message: str
    state: TripState

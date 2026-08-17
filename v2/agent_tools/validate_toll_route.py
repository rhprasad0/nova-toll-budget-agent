"""Strands tool for the v2 PostgreSQL toll-route oracle."""

import logging
import os
from typing import Annotated, Any, Literal, Self, cast

import boto3
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    model_validator,
)
from strands.types.tools import ToolResult, ToolSpec, ToolUse

logger = logging.getLogger(__name__)

_DB_USER = "tollchat_agent"
_SQL = "SELECT * FROM oracle.validate_toll_route(%s, %s)"
_SAFE_ERROR = "Unable to validate the toll route. Reference: {tool_use_id}."

Status = Literal[
    "invalid_origin",
    "invalid_destination",
    "valid",
    "currently_unavailable",
    "unknown_availability",
    "no_supported_route",
    "traversal_limit_exceeded",
]
Direction = Literal["NB", "SB", "EB", "WB"]
I95Direction = Literal["NB", "SB"]
NetworkId = Literal[
    "i95", "i495", "i66", "dtr", "greenway", "airport_iad", "airport_dca"
]
ConnectionType = Literal[
    "within_facility",
    "toll_handoff",
    "general_purpose_gap",
    "airport_access",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _RouteInput(_Model):
    origin_point_id: str = Field(description="Stable oracle origin point ID")
    destination_point_id: str = Field(description="Stable oracle destination point ID")


class _GeoJSONPoint(_Model):
    type: Literal["Point"]
    coordinates: Annotated[list[float], Field(min_length=2, max_length=2)]


class _Alternative(_Model):
    point_id: str
    network_id: NetworkId
    source_node_id: str
    point_type: Literal["entry", "exit"]
    direction: Direction
    label: str
    aliases: list[str]
    location: _GeoJSONPoint | None


class _EmptyDetails(_Model):
    pass


class _PointDetails(_Model):
    point_id: str


class _WrongRoleDetails(_PointDetails):
    point_type: Literal["entry", "exit", "airport"]
    allowed_point_types: list[Literal["entry", "exit", "airport"]]
    alternatives: Annotated[list[_Alternative], Field(max_length=2)]


class _IncompatibleRampDetails(_PointDetails):
    point_type: Literal["entry", "exit"]
    alternatives: Annotated[list[_Alternative], Field(min_length=1, max_length=2)]


class _AvailabilityDetails(_Model):
    required_i95_directions: Annotated[list[I95Direction], Field(min_length=1)]
    availability: Literal["northbound", "southbound", "closed", "unknown"]


class _RouteDetails(_Model):
    origin_point_id: str
    destination_point_id: str


class _TraversalDetails(_RouteDetails):
    maximum_connections: Literal[12]


class _RequiredReason(_Model):
    code: Literal["origin_required", "destination_required"]
    details: _EmptyDetails


class _NotFoundReason(_Model):
    code: Literal["origin_not_found", "destination_not_found"]
    details: _PointDetails


class _WrongRoleReason(_Model):
    code: Literal["origin_not_entry", "destination_not_exit"]
    details: _WrongRoleDetails


class _IncompatibleRampReason(_Model):
    code: Literal["origin_ramp_incompatible", "destination_ramp_incompatible"]
    details: _IncompatibleRampDetails


class _AvailabilityReason(_Model):
    code: Literal[
        "i95_opposite_direction_open",
        "i95_fully_closed",
        "i95_missing_source",
        "i95_invalid_source",
        "i95_interval_mismatch",
        "i95_future_evidence",
        "i95_stale_evidence",
        "i95_indeterminate_state",
    ]
    details: _AvailabilityDetails


class _NoRouteReason(_Model):
    code: Literal["no_supported_route"]
    details: _RouteDetails


class _TraversalReason(_Model):
    code: Literal["traversal_limit_exceeded"]
    details: _TraversalDetails


Reason = Annotated[
    _RequiredReason
    | _NotFoundReason
    | _WrongRoleReason
    | _IncompatibleRampReason
    | _AvailabilityReason
    | _NoRouteReason
    | _TraversalReason,
    Field(discriminator="code"),
]


class _Gap(_Model):
    connection_id: str
    boundary_point_id: Literal["i495:192NO", "i495:192SD"]
    role: Literal["prefix", "suffix"]
    i95_direction: I95Direction
    fallback_required: bool | None

    @model_validator(mode="after")
    def _validate_alignment(self) -> Self:
        expected_boundary = {
            "prefix": "i495:192NO",
            "suffix": "i495:192SD",
        }[self.role]
        if self.boundary_point_id != expected_boundary:
            raise ValueError("general-purpose gap fields are not aligned")
        return self


class _MissingEvidence(_Model):
    availability: Literal["unknown"]
    reason: Literal["missing_source"]


class _SourceEvidence(_Model):
    availability: Literal["northbound", "southbound", "closed", "unknown"]
    northbound_corridor_name: str
    northbound_link_status: str
    northbound_interval_end_at: str
    northbound_calculated_at: str
    southbound_corridor_name: str
    southbound_link_status: str
    southbound_interval_end_at: str
    southbound_calculated_at: str


class _RouteResponse(_Model):
    status: Status
    reason: Reason | None
    point_ids: list[str]
    connection_ids: list[str]
    connection_types: list[ConnectionType]
    general_purpose_gaps: list[_Gap]
    i95_evidence: _MissingEvidence | _SourceEvidence | None

    @model_validator(mode="after")
    def _validate_contract(self, info: ValidationInfo) -> Self:
        reason_codes = {
            "invalid_origin": {
                "origin_required",
                "origin_not_found",
                "origin_not_entry",
                "origin_ramp_incompatible",
            },
            "invalid_destination": {
                "destination_required",
                "destination_not_found",
                "destination_not_exit",
                "destination_ramp_incompatible",
            },
            "currently_unavailable": {
                "i95_opposite_direction_open",
                "i95_fully_closed",
            },
            "unknown_availability": {
                "i95_missing_source",
                "i95_invalid_source",
                "i95_interval_mismatch",
                "i95_future_evidence",
                "i95_stale_evidence",
                "i95_indeterminate_state",
            },
            "no_supported_route": {"no_supported_route"},
            "traversal_limit_exceeded": {"traversal_limit_exceeded"},
        }
        if self.status == "valid":
            if self.reason is not None:
                raise ValueError("valid routes cannot include a reason")
        elif self.reason is None or self.reason.code not in reason_codes[self.status]:
            raise ValueError("reason does not match route status")

        has_path = self.status in {
            "valid",
            "currently_unavailable",
            "unknown_availability",
        }
        if has_path:
            if (
                not self.connection_ids
                or len(self.point_ids) != len(self.connection_ids) + 1
            ):
                raise ValueError("route path arrays are not aligned")
            if len(self.connection_types) != len(self.connection_ids):
                raise ValueError("connection arrays are not aligned")
            if len(set(self.point_ids)) != len(self.point_ids):
                raise ValueError("route paths cannot repeat points")
        elif (
            any(
                (
                    self.point_ids,
                    self.connection_ids,
                    self.connection_types,
                    self.general_purpose_gaps,
                )
            )
            or self.i95_evidence is not None
        ):
            raise ValueError("pathless results must use empty paths and null evidence")

        expected_gap_ids = [
            connection_id
            for connection_id, connection_type in zip(
                self.connection_ids, self.connection_types, strict=True
            )
            if connection_type == "general_purpose_gap"
        ]
        if [gap.connection_id for gap in self.general_purpose_gaps] != expected_gap_ids:
            raise ValueError("general-purpose gaps are not aligned to the path")
        if self.general_purpose_gaps and self.i95_evidence is None:
            raise ValueError("general-purpose gaps require I-95 evidence")

        request = info.context.get("request") if info.context else None
        if isinstance(request, _RouteInput):
            self._validate_request_alignment(request)
        self._validate_reason_details()
        self._validate_evidence()
        return self

    def _validate_request_alignment(self, request: _RouteInput) -> None:
        if self.point_ids and self.point_ids[0] != request.origin_point_id:
            raise ValueError("route path does not begin at the requested origin")
        if self.point_ids and self.point_ids[-1] != request.destination_point_id:
            raise ValueError("route path does not end at the requested destination")
        if self.reason is None:
            return
        details = self.reason.details
        if isinstance(details, _PointDetails):
            expected = (
                request.origin_point_id
                if self.status == "invalid_origin"
                else request.destination_point_id
            )
            if details.point_id != expected:
                raise ValueError("reason point does not match the request")
        if isinstance(details, _RouteDetails) and (
            details.origin_point_id != request.origin_point_id
            or details.destination_point_id != request.destination_point_id
        ):
            raise ValueError("reason route does not match the request")

    def _validate_reason_details(self) -> None:
        if self.reason is None:
            return
        code = self.reason.code
        if isinstance(self.reason, _WrongRoleReason) and code == "origin_not_entry":
            details = self.reason.details
            if (
                details.point_type != "exit"
                or details.allowed_point_types != ["entry", "airport"]
                or any(
                    alternative.point_type != "entry"
                    for alternative in details.alternatives
                )
            ):
                raise ValueError("origin alternatives are malformed")
        elif (
            isinstance(self.reason, _WrongRoleReason) and code == "destination_not_exit"
        ):
            details = self.reason.details
            if (
                details.point_type != "entry"
                or details.allowed_point_types != ["exit", "airport"]
                or any(
                    alternative.point_type != "exit"
                    for alternative in details.alternatives
                )
            ):
                raise ValueError("destination alternatives are malformed")
        elif isinstance(self.reason, _IncompatibleRampReason):
            details = self.reason.details
            expected_type = "entry" if code == "origin_ramp_incompatible" else "exit"
            if details.point_type != expected_type or any(
                alternative.point_type != expected_type
                for alternative in details.alternatives
            ):
                raise ValueError("ramp alternatives are malformed")
        details = self.reason.details
        if isinstance(details, (_WrongRoleDetails, _IncompatibleRampDetails)):
            submitted_network = details.point_id.partition(":")[0]
            if any(
                alternative.network_id != submitted_network
                for alternative in details.alternatives
            ):
                raise ValueError("alternatives must match the submitted facility")

    def _validate_evidence(self) -> None:
        path_uses_i95 = bool(self.general_purpose_gaps) or any(
            point_id.startswith("i95:") for point_id in self.point_ids
        )
        if path_uses_i95 != (self.i95_evidence is not None):
            raise ValueError("I-95 evidence does not match route involvement")

        if self.status == "unknown_availability":
            expected_availability = "unknown"
        elif self.status == "currently_unavailable" and isinstance(
            self.reason, _AvailabilityReason
        ):
            expected_availability = self.reason.details.availability
        else:
            expected_availability = None

        if expected_availability is not None:
            if (
                self.i95_evidence is None
                or self.i95_evidence.availability != expected_availability
            ):
                raise ValueError("I-95 evidence does not match route status")
            if (
                not isinstance(self.reason, _AvailabilityReason)
                or self.reason.details.availability != expected_availability
            ):
                raise ValueError("I-95 reason details do not match evidence")
        elif self.status == "valid" and (
            self.i95_evidence is not None
            and self.i95_evidence.availability not in {"northbound", "southbound"}
        ):
            raise ValueError("valid I-95 paths require an open direction")

        if self.i95_evidence is None:
            return
        if isinstance(self.reason, _AvailabilityReason):
            code = self.reason.code
            availability = self.reason.details.availability
            if code == "i95_fully_closed" and availability != "closed":
                raise ValueError("I-95 reason code does not match availability")
            if code == "i95_opposite_direction_open" and availability not in {
                "northbound",
                "southbound",
            }:
                raise ValueError("I-95 reason code does not match availability")
            if code == "i95_opposite_direction_open":
                open_direction = "NB" if availability == "northbound" else "SB"
                if set(self.reason.details.required_i95_directions) <= {open_direction}:
                    raise ValueError("open I-95 direction satisfies the route")
            if code == "i95_missing_source":
                if not isinstance(self.i95_evidence, _MissingEvidence):
                    raise ValueError("missing-source reason requires missing evidence")
            elif self.status == "unknown_availability" and not isinstance(
                self.i95_evidence, _SourceEvidence
            ):
                raise ValueError("availability reason requires source evidence")
        availability = self.i95_evidence.availability
        for gap in self.general_purpose_gaps:
            expected_fallback = (
                None
                if availability == "unknown"
                else not (
                    (availability == "northbound" and gap.i95_direction == "NB")
                    or (availability == "southbound" and gap.i95_direction == "SB")
                )
            )
            if gap.fallback_required is not expected_fallback:
                raise ValueError("gap fallback does not match I-95 evidence")


TOOL_SPEC: ToolSpec = {
    "name": "validate_toll_route",
    "description": "Validate a route between two stable oracle toll point IDs.",
    "inputSchema": {"json": _RouteInput.model_json_schema()},
}


def _connect() -> object:
    import psycopg
    from psycopg.rows import dict_row

    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    rds = cast(Any, boto3.client("rds"))  # pyright: ignore[reportUnknownMemberType]
    token = cast(
        str,
        rds.generate_db_auth_token(
            DBHostname=host,
            Port=port,
            DBUsername=_DB_USER,
        ),
    )
    return cast(
        object,
        psycopg.connect(
            host=host,
            port=port,
            dbname=os.environ["DB_NAME"],
            user=_DB_USER,
            password=token,
            sslmode="verify-full",
            sslrootcert=os.environ["DB_CA_BUNDLE_PATH"],
            row_factory=cast(Any, dict_row),
        ),
    )


def _error(tool_use_id: str, stage: str, error: Exception) -> ToolResult:
    logger.error(
        "validate_toll_route failed",
        extra={
            "toolUseId": tool_use_id,
            "failureStage": stage,
            "exceptionType": type(error).__name__,
        },
        exc_info=(type(error), error, error.__traceback__),
    )
    return {
        "toolUseId": tool_use_id,
        "status": "error",
        "content": [{"text": _SAFE_ERROR.format(tool_use_id=tool_use_id)}],
    }


def validate_toll_route(tool_use: ToolUse, **_: Any) -> ToolResult:  # noqa: ANN401
    """Validate a toll route and return the oracle's seven-field response."""
    tool_use_id = "unknown"
    try:
        tool_data = cast(Any, tool_use)
        candidate_id = tool_data.get("toolUseId")
        if isinstance(candidate_id, str):
            tool_use_id = candidate_id
        route_input = _RouteInput.model_validate(tool_data.get("input"))
    except Exception as error:
        return _error(tool_use_id, "input_validation", error)

    try:
        connection = cast(Any, _connect())
    except Exception as error:
        return _error(tool_use_id, "connection", error)

    database_error: tuple[str, Exception] | None = None
    rows: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                _SQL,
                (route_input.origin_point_id, route_input.destination_point_id),
            )
            rows = cast(list[dict[str, Any]], cursor.fetchall())
    except Exception as error:
        database_error = ("query", error)

    try:
        connection.close()
    except Exception as error:
        if database_error is None:
            database_error = ("connection_close", error)
        else:
            database_error[1].add_note(f"Connection close also failed: {error!r}")

    if database_error is not None:
        return _error(tool_use_id, *database_error)

    try:
        if len(rows) != 1:
            raise ValueError("route oracle must return exactly one row")
        response = _RouteResponse.model_validate(
            rows[0], context={"request": route_input}
        )
    except (ValidationError, ValueError) as error:
        return _error(tool_use_id, "response_validation", error)
    except Exception as error:
        return _error(tool_use_id, "unexpected", error)

    try:
        content = response.model_dump(mode="json")
        return {
            "toolUseId": tool_use_id,
            "status": "success",
            "content": [{"json": content}],
        }
    except Exception as error:
        return _error(tool_use_id, "unexpected", error)

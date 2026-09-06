# pyright: basic
# ruff: noqa: E402
"""Deterministic evaluator matrix for directed toll movement evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import pairwise, product
from pathlib import Path
from typing import Any, Literal, Protocol, cast

_V2_ROOT = Path(__file__).resolve().parents[1]
if str(_V2_ROOT) not in sys.path:
    sys.path.insert(0, str(_V2_ROOT))
from eval.golden_corpus import _v2_validate_fixture_file, _v2_validate_request
from eval.history_capture import _json_safe
from oracle.build_oracle_data import Connection, Point, build_connections, build_points

CURRENT_CONTRACT_VERSION = "1.5.0"
ANNUAL_CONTRACT_VERSION = "3.0.0"
OPERATOR_ENTRY_EXIT_URL = "https://www.expresslanes.com/themes/custom/transurbangroup/js/on-the-road/entry_exit.js?v=1.x"
OPERATOR_ENTRY_EXIT_SHA256 = (
    "b036a0ce868b5166990d26542d0d73f4dd5700e9dcdee9a863d56ab0b9bc09c4"
)
_ID = re.compile("^[a-z0-9]+(?:-[a-z0-9]+)+$")
_SHA256 = re.compile("^[0-9a-f]{64}$")
_PROFILE = {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll",
}
_TOOLS: tuple[str, str] = ("current", "annual")
_SUPPORTED_HANDOFFS = {
    "i66_to_i495": "I-66 WB to SB495",
    "i495_to_i66": "NB495 to I-66 EB",
    "i66_to_dulles_toll_road": "I-66 WB to Dulles Toll Road WB",
    "dulles_toll_road_to_i495": "EB DTR to SB495",
    "dulles_toll_road_to_i495_north": "EB DTR to NB495",
    "dulles_toll_road_westbound_to_i495_north": "WB DTR to NB495",
    "i495_to_dulles_toll_road": "NB495 to WB DTR",
    "i495_1829_to_dulles_toll_road": "NB495 to WB DTR",
    "i495_south_to_dulles_toll_road": "SB495 to WB DTR",
}
_PROHIBITED_HANDOFFS = {
    "i66_to_i495_north": "I-66 WB to NB495 direct handoff",
    "i495_south_to_i66": "SB495 to I-66 EB direct handoff",
}
_ALTERNATE_PATHS = {
    "i66_to_i495_north": (
        "i66_to_dulles_toll_road",
        "dulles_toll_road_westbound_to_i495_north",
    )
}


class _StreamTool(Protocol):
    tool_name: str

    def stream(
        self, tool_use: Mapping[str, Any], context: Mapping[str, Any]
    ) -> object: ...


PhysicalStatus = Literal["supported", "prohibited", "unknown"]


def _canonical(value: object) -> bytes:
    return json.dumps(
        _json_safe(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _as_datetime(value: object, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        raise ValueError(f"{label} must be an ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed


def _source_direction(connection: Connection, start: Point) -> str | None:
    metadata = cast(Mapping[str, Any], connection.source_metadata)
    pair = metadata.get("source_pair")
    if isinstance(pair, Mapping):
        direction = pair.get("direction")
        if direction == "Northbound":
            return "NB"
        if direction == "Southbound":
            return "SB"
        if isinstance(direction, str):
            return direction
    direction = getattr(start, "direction", None)
    return direction if isinstance(direction, str) else None


def _movement_states(start: Point, end: Point, tool: str) -> tuple[str, ...]:
    networks = {start.network_id, end.network_id}
    states = []
    if "i95" in networks:
        states.append(("i95-NB", "i95-SB", "i95-closed", "i95-unknown"))
    if "i66" in networks:
        states.append(("i66-tolled", "i66-free"))
    if tool == "annual":
        states.append(("history-complete", "history-partial", "history-insufficient"))
    return (
        tuple("+".join(state) for state in product(*states))
        if states
        else ("fixed-schedule",)
    )


def _source_provenance(connection: Connection) -> dict[str, Any]:
    metadata = cast(Mapping[str, Any], connection.source_metadata)
    result: dict[str, Any] = {}
    for key in (
        "source_file",
        "source_route_key",
        "source_context",
        "curated",
        "basis",
    ):
        value = metadata.get(key)
        if value is not None:
            result[key] = value
    return result


def _movement(connection: Connection, points: Mapping[str, Any]) -> dict[str, Any]:
    from_id = cast(str, connection.from_point_id)
    to_id = cast(str, connection.to_point_id)
    start, end = (points[from_id], points[to_id])
    return {
        "movement_id": cast(str, connection.connection_id),
        "from_point_id": from_id,
        "to_point_id": to_id,
        "from_network": start.network_id,
        "to_network": end.network_id,
        "from_role": start.point_type,
        "to_role": end.point_type,
        "direction": _source_direction(connection, start),
        "connection_type": cast(str, connection.connection_type),
        "source_provenance": _source_provenance(connection),
    }


@dataclass(frozen=True)
class PhysicalExpectation:
    status: PhysicalStatus
    evidence_refs: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"supported", "prohibited", "unknown"}:
            raise ValueError("invalid physical evidence status")
        if self.status == "unknown" and self.evidence_refs:
            raise ValueError("unknown physical evidence cannot carry references")
        if self.status != "unknown" and (not self.evidence_refs):
            raise ValueError(
                "supported/prohibited physical evidence requires references"
            )
        for reference in self.evidence_refs:
            if not {"url", "sha256", "locator"} <= set(reference) or not isinstance(
                reference["url"], str
            ):
                raise ValueError("physical evidence reference is incomplete")
            if not isinstance(reference["sha256"], str) or not _SHA256.fullmatch(
                reference["sha256"]
            ):
                raise ValueError("physical evidence reference hash is invalid")
            if not isinstance(reference["locator"], str) or not reference["locator"]:
                raise ValueError("physical evidence locator is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence_refs": [dict(reference) for reference in self.evidence_refs],
        }


def _operator_expectation(status: PhysicalStatus, locator: str) -> PhysicalExpectation:
    if status == "unknown":
        return PhysicalExpectation("unknown")
    return PhysicalExpectation(
        status,
        (
            {
                "url": OPERATOR_ENTRY_EXIT_URL,
                "sha256": OPERATOR_ENTRY_EXIT_SHA256,
                "locator": locator,
            },
        ),
    )


def default_physical_expectations() -> dict[str, PhysicalExpectation]:
    expectations = {
        movement_id: _operator_expectation("supported", locator)
        for movement_id, locator in _SUPPORTED_HANDOFFS.items()
    }
    expectations.update(
        {
            movement_id: _operator_expectation("prohibited", locator)
            for movement_id, locator in _PROHIBITED_HANDOFFS.items()
        }
    )
    return expectations


def _physical(value: object) -> PhysicalExpectation:
    if isinstance(value, PhysicalExpectation):
        return value
    data = cast(Mapping[str, Any], value)
    status = cast(PhysicalStatus, data.get("status"))
    refs = data.get("evidence_refs", ())
    if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
        raise ValueError("physical evidence references must be a sequence")
    return PhysicalExpectation(
        status, tuple(cast(Mapping[str, Any], ref) for ref in refs)
    )


def _candidate_connections(
    connections: Sequence[Any], predicate: Callable[[Any], bool]
) -> list[Any]:
    return sorted(
        (connection for connection in connections if predicate(connection)),
        key=lambda connection: connection.connection_id,
    )


def _route_envelope(
    connection: Connection, connections: Sequence[Any], points: Mapping[str, Any]
) -> tuple[dict[str, str], tuple[str, ...]] | None:
    from_id = cast(str, connection.from_point_id)
    to_id = cast(str, connection.to_point_id)
    start, end = (points[from_id], points[to_id])
    if start.point_type == "entry" and end.point_type == "exit":
        return (
            {"origin_point_id": from_id, "destination_point_id": to_id},
            (connection.connection_id,),
        )
    incoming = _candidate_connections(
        connections,
        lambda item: (
            item.to_point_id == from_id
            and points[cast(str, item.from_point_id)].point_type in {"entry", "airport"}
        ),
    )
    outgoing = _candidate_connections(
        connections,
        lambda item: (
            item.from_point_id == to_id
            and points[cast(str, item.to_point_id)].point_type in {"exit", "airport"}
        ),
    )
    if start.point_type == "airport":
        outgoing = _candidate_connections(
            connections,
            lambda item: (
                item.from_point_id == to_id
                and points[cast(str, item.to_point_id)].point_type == "exit"
            ),
        )
        if outgoing:
            chosen = outgoing[0]
            return (
                {
                    "origin_point_id": from_id,
                    "destination_point_id": cast(str, chosen.to_point_id),
                },
                (connection.connection_id, chosen.connection_id),
            )
    if end.point_type == "airport" and incoming:
        chosen = incoming[0]
        return (
            {
                "origin_point_id": cast(str, chosen.from_point_id),
                "destination_point_id": to_id,
            },
            (chosen.connection_id, connection.connection_id),
        )
    if incoming and outgoing:
        before, after = (incoming[0], outgoing[0])
        return (
            {
                "origin_point_id": cast(str, before.from_point_id),
                "destination_point_id": cast(str, after.to_point_id),
            },
            (before.connection_id, connection.connection_id, after.connection_id),
        )
    return None


def _request_for(
    tool: str,
    connection: Connection,
    connections: Sequence[Any],
    points: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    envelope = _route_envelope(connection, connections, points)
    if envelope is None:
        raise ValueError(
            f"cannot construct a valid route envelope for {connection.connection_id}"
        )
    route, proof = envelope
    if tool == "current":
        return ({**route, "pricing_profile": dict(_PROFILE)}, proof)
    return (
        {
            "outbound": {**route, "departure_time": "08:00:00"},
            "return": {
                "origin_point_id": "greenway:28:entry:WB",
                "destination_point_id": "greenway:1:exit:WB",
                "departure_time": "17:30:00",
            },
            "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "planned_annual_commute_days": 240,
            "gross_annual_income_usd": "120000.00",
        },
        proof,
    )


def _capture_value(
    captures: Mapping[Any, Any], row_id: str
) -> Mapping[str, Any] | None:
    value = captures.get(row_id)
    if value is None:
        return None
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    raise ValueError(f"capture for {row_id} must be an object")


def _validate_observation(
    capture: Mapping[str, Any],
    request: Mapping[str, Any],
    tool: str,
    connections: Sequence[Any],
    state: str,
) -> None:
    if capture.get("state") != state:
        raise ValueError("observation state disagrees with matrix row")
    if capture.get("request") != request:
        raise ValueError("observation request disagrees with matrix row")
    layer = capture.get("execution_layer")
    if layer not in {
        "typed_tool_live",
        "typed_tool_domain",
        "actual_anchor_sql",
        "fixture_playback",
        "raw_source",
    }:
        raise ValueError("observation execution layer is invalid")
    if not isinstance(capture.get("source_sha256"), str) or not _SHA256.fullmatch(
        capture["source_sha256"]
    ):
        raise ValueError("observation retained-source hash is required")
    expected_hash = hashlib.sha256(
        _canonical(
            {key: value for key, value in capture.items() if key != "source_sha256"}
        )
    ).hexdigest()
    if capture["source_sha256"] != expected_hash:
        raise ValueError("observation retained-source hash disagrees")
    if layer in {"typed_tool_live", "typed_tool_domain", "fixture_playback"}:
        fixture = validate_typed_fixture(capture.get("fixture", {}))
        expected_tool = (
            "get_current_toll_price"
            if tool == "current"
            else "get_annual_toll_ballpark"
        )
        if (
            fixture["request"] != request
            or fixture["tool"] != expected_tool
            or fixture["evidence_type"] != capture.get("evidence_type")
        ):
            raise ValueError("observation fixture binding disagrees")
        actual = fixture.get("result", fixture.get("error"))
        if capture.get("actual") != actual:
            raise ValueError("observation actual result disagrees with fixture")
        if layer == "typed_tool_live" and fixture["evidence_type"] not in {
            "live_read_only_capture",
            "retained_production_capture",
        }:
            raise ValueError("synthetic fixture is not a live capture")
        if layer == "typed_tool_domain" and fixture["evidence_type"] not in {
            "synthetic",
            "synthetic_fault",
            "synthetic_adversarial",
            "historical_replay",
        }:
            raise ValueError("domain replay cannot claim live capture")
    proof = capture.get("route_proof")
    if proof is None:
        if layer == "actual_anchor_sql":
            raise ValueError("SQL observation requires retained route proof")
    else:
        route = request if tool == "current" else request["outbound"]
        _validate_route_proof(proof, cast(Mapping[str, Any], route), connections)
    if tool == "annual":
        _annual_evidence_complete(capture, request, connections)


def _validate_route_proof(
    proof: object, route: Mapping[str, Any], connections: Sequence[Any]
) -> None:
    if not isinstance(proof, Mapping) or set(proof) != {
        "connection_ids",
        "facility_legs",
        "priced_components",
    }:
        raise ValueError("route proof is incomplete")
    ids = proof["connection_ids"]
    known = {c.connection_id: c for c in connections}
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(i, str) or i not in known for i in ids)
    ):
        raise ValueError("route proof has unknown connections")
    path = [known[i] for i in ids]
    if (
        path[0].from_point_id != route["origin_point_id"]
        or path[-1].to_point_id != route["destination_point_id"]
        or any((a.to_point_id != b.from_point_id for a, b in pairwise(path)))
    ):
        raise ValueError("route proof is not a complete directed request path")
    if (
        not isinstance(proof["facility_legs"], list)
        or not proof["facility_legs"]
        or not isinstance(proof["priced_components"], list)
        or not proof["priced_components"]
    ):
        raise ValueError("route proof legs/components are invalid")


def _annual_evidence_complete(
    capture: Mapping[str, Any],
    request: Mapping[str, Any],
    connections: Sequence[Any],
) -> bool:
    """Return whether an annual receipt retains both independently bound legs.

    A normal public annual-tool result is an aggregate.  It is exercised evidence,
    but it cannot establish annual conformance unless the caller also retains the
    outbound and return requests/results and their route proofs independently.
    Missing leg evidence therefore stays honestly non-passing.
    """
    legs = capture.get("annual_legs")
    if legs is None:
        return False
    if not isinstance(legs, Mapping):
        raise ValueError("annual independent leg evidence must be an object")
    for leg_name in ("outbound", "return"):
        leg = legs.get(leg_name)
        if not isinstance(leg, Mapping):
            raise ValueError(f"annual {leg_name} evidence is missing")
        expected_request = request.get(leg_name)
        if leg.get("request") != expected_request:
            raise ValueError(f"annual {leg_name} request evidence disagrees")
        actual = leg.get("actual")
        if not isinstance(actual, Mapping):
            raise ValueError(f"annual {leg_name} result evidence is missing")
        if _status({"actual": actual}) != "valid":
            return False
        source_sha256 = leg.get("source_sha256")
        expected_hash = hashlib.sha256(
            _canonical({"request": expected_request, "actual": actual})
        ).hexdigest()
        if source_sha256 != expected_hash:
            raise ValueError(f"annual {leg_name} result evidence hash disagrees")
        _validate_route_proof(
            leg.get("route_proof"),
            cast(Mapping[str, Any], expected_request),
            connections,
        )
    return True


def _status(actual: Mapping[str, Any] | None) -> str:
    if actual is None:
        return "not_executed"
    outcome = actual.get("actual", actual.get("outcome", actual))
    if isinstance(outcome, Mapping):
        if outcome.get("status") in {"valid", "accepted", "success"} or outcome.get(
            "method"
        ) in {
            "latest_complete_current_facility_prices",
            "recent_complete_same_date_round_trips",
        }:
            return "valid"
        if outcome.get("status") == "error" or outcome.get("error"):
            return "error"
        if outcome.get("reason") in {"route_unavailable", "no_supported_route"}:
            return "unavailable"
        result = outcome.get("result")
        if isinstance(result, Mapping):
            return _status({"actual": result})
    return "unknown"


def _actual_result(capture: Mapping[str, Any] | None) -> object:
    if capture is None:
        return {"status": "not_executed", "reason": "no_capture"}
    if "actual" in capture:
        return capture["actual"]
    if "outcome" in capture:
        return capture["outcome"]
    return capture


def _proof(
    capture: Mapping[str, Any] | None, planned: tuple[str, ...]
) -> dict[str, Any]:
    if capture is not None and isinstance(capture.get("route_proof"), Mapping):
        value = cast(Mapping[str, Any], capture["route_proof"])
        return {str(key): item for key, item in value.items()}
    return {
        "connection_ids": [],
        "facility_legs": [],
        "priced_components": [],
        "status": "not_executed",
        "planned_connection_ids": list(planned),
    }


def _ordered_subsequence(expected: Sequence[str], actual: Sequence[str]) -> bool:
    position = 0
    for item in actual:
        if position < len(expected) and item == expected[position]:
            position += 1
    return position == len(expected)


def _alternate_paths(
    movement_id: str,
    connections: Sequence[Any],
    physical_values: Mapping[str, Any],
    proof_ids: Sequence[str],
    proof_valid: bool,
) -> tuple[dict[str, Any], ...]:
    path = _ALTERNATE_PATHS.get(movement_id)
    if path is None:
        return ()
    known = {connection.connection_id for connection in connections}
    if not set(path) <= known:
        return ()
    expectations = tuple(
        _physical(physical_values.get(connection_id, PhysicalExpectation("unknown")))
        for connection_id in path
    )
    if all(expectation.status == "supported" for expectation in expectations):
        physical_status: PhysicalStatus = "supported"
    elif any(expectation.status == "prohibited" for expectation in expectations):
        physical_status = "prohibited"
    else:
        physical_status = "unknown"
    checked = (
        proof_valid
        and physical_status == "supported"
        and _ordered_subsequence(path, proof_ids)
    )
    return (
        {
            "connection_ids": list(path),
            "physical_status": physical_status,
            "checked": checked,
            "evidence_refs": [
                reference
                for expectation in expectations
                for reference in expectation.evidence_refs
            ],
        },
    )


@dataclass(frozen=True)
class MatrixRow:
    movement_id: str
    tool: str
    state: str
    movement: Mapping[str, Any]
    request: Mapping[str, Any]
    contract_version: str
    oracle_expectation: Mapping[str, Any]
    physical_expectation: PhysicalExpectation
    evidence_refs: tuple[Mapping[str, Any], ...]
    route_proof: Mapping[str, Any]
    alternate_paths_checked: tuple[Mapping[str, Any], ...]
    request_availability: str
    actual: Any
    coverage_required: bool
    coverage_exercised: bool
    conformance_required: bool
    conformance_passed: bool
    oracle_conformance_passed: bool
    physical_conformance_passed: bool
    execution_layer: str
    evidence_type: str
    mismatch: str | None = None
    leg_bindings: Mapping[str, Any] = field(default_factory=dict)

    @property
    def row_id(self) -> str:
        return f"{self.movement_id}|{self.tool}|{self.state}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["row_id"] = self.row_id
        data["tool_contract_version"] = data.pop("contract_version")
        return data


@dataclass(frozen=True)
class MatrixReport:
    rows: tuple[MatrixRow, ...]
    inventory_counts: Mapping[str, Any]
    physical_summary: Mapping[str, Any]
    coverage_summary: Mapping[str, Any]
    conformance_summary: Mapping[str, Any]
    canonical_json_sha256: str

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "inventory": dict(self.inventory_counts),
            "physical": dict(self.physical_summary),
            "coverage": dict(self.coverage_summary),
            "conformance": dict(self.conformance_summary),
            "rows": [row.to_dict() for row in self.rows],
        }
        current_digest = hashlib.sha256(_canonical(payload)).hexdigest()
        if current_digest != self.canonical_json_sha256:
            raise ValueError("matrix report changed after digest computation")
        return {**payload, "canonical_json_sha256": self.canonical_json_sha256}


def build_matrix(
    inventory: Mapping[str, Any],
    physical_expectations: Mapping[str, Any] | None = None,
    captures: Mapping[Any, Any] | None = None,
) -> MatrixReport:
    points = inventory["points"]
    connections = tuple(inventory["connections"].values())
    physical_values = (
        default_physical_expectations()
        if physical_expectations is None
        else physical_expectations
    )
    capture_values = captures or {}
    movements = sorted(connections, key=lambda connection: connection.connection_id)
    rows: list[MatrixRow] = []
    for connection in movements:
        movement_id = connection.connection_id
        movement = _movement(connection, points)
        start, end = (
            points[cast(str, connection.from_point_id)],
            points[cast(str, connection.to_point_id)],
        )
        physical = _physical(
            physical_values.get(movement_id, PhysicalExpectation("unknown"))
        )
        for tool, state in (
            (selected_tool, selected_state)
            for selected_tool in _TOOLS
            for selected_state in _movement_states(start, end, selected_tool)
        ):
            request, planned_proof = _request_for(tool, connection, movements, points)
            row_id = f"{movement_id}|{tool}|{state}"
            _v2_validate_request(
                "get_current_toll_price"
                if tool == "current"
                else "get_annual_toll_ballpark",
                request,
                row_id,
            )
            capture = _capture_value(capture_values, row_id)
            if capture is not None:
                _validate_observation(capture, request, tool, connections, state)
            proof = _proof(capture, planned_proof)
            connection_ids = proof.get("connection_ids", [])
            proven_ids = (
                set(connection_ids)
                if isinstance(connection_ids, Sequence)
                and (not isinstance(connection_ids, (str, bytes)))
                else set()
            )
            direct_proof = movement_id in proven_ids
            proof_valid = capture is not None and isinstance(
                capture.get("route_proof"), Mapping
            )
            proof_ids = (
                cast(list[str], connection_ids)
                if isinstance(connection_ids, list)
                and all(isinstance(item, str) for item in connection_ids)
                else []
            )
            alternates = _alternate_paths(
                movement_id,
                movements,
                physical_values,
                proof_ids,
                proof_valid,
            )
            alternate_proof = bool(
                alternates and alternates[0]["checked"] is True and (not direct_proof)
            )
            actual_status = _status(capture)
            exercised = capture is not None and capture.get("execution_layer") in {
                "typed_tool_live",
                "typed_tool_domain",
                "actual_anchor_sql",
            }
            annual_complete = tool != "annual" or (
                capture is not None
                and _annual_evidence_complete(capture, request, connections)
            )
            oracle_passed = exercised and actual_status == "valid" and annual_complete
            physical_passed = oracle_passed and (
                (physical.status == "supported" and direct_proof) or alternate_proof
            )
            mismatch: str | None = None
            if exercised and direct_proof and (physical.status == "prohibited"):
                mismatch = "physical_prohibited_direct_handoff_used"
            request_availability = "unknown"
            if exercised and direct_proof:
                request_availability = "available_via_direct_implementation"
            elif exercised and alternate_proof:
                request_availability = "available_via_supported_alternate"
            execution_layer = (
                str(capture.get("execution_layer", "none"))
                if capture is not None
                else "none"
            )
            evidence_type = (
                str(capture.get("evidence_type", "none"))
                if capture is not None
                else "none"
            )
            leg_bindings: dict[str, Any] = {
                "connection_scope": "separate_route_comparison_connections"
            }
            if tool == "annual":
                leg_bindings = {
                    "outbound_movement_id": movement_id,
                    "return_is_independent": True,
                    "independent_evidence_required": True,
                    "independent_evidence_present": annual_complete,
                    "return_scope": "fixed valid Greenway control leg; domain check, not a realistic commute",
                    "outbound_request": request["outbound"],
                    "return_request": request["return"],
                    "annual_legs": (
                        _json_safe(capture.get("annual_legs"))
                        if capture is not None
                        else None
                    ),
                    "connection_scope": "single_repeatable_read_transaction",
                }
            rows.append(
                MatrixRow(
                    movement_id=movement_id,
                    tool=tool,
                    state=state,
                    movement=movement,
                    request=request,
                    contract_version=CURRENT_CONTRACT_VERSION
                    if tool == "current"
                    else ANNUAL_CONTRACT_VERSION,
                    oracle_expectation={
                        "connection_id": movement_id,
                        "expected_status": "unknown",
                        "inventory_contains_connection": True,
                        "expected_connection_type": connection.connection_type,
                    },
                    physical_expectation=physical,
                    evidence_refs=physical.evidence_refs,
                    route_proof=proof,
                    alternate_paths_checked=alternates,
                    request_availability=request_availability,
                    actual=_actual_result(capture),
                    coverage_required=True,
                    coverage_exercised=exercised,
                    conformance_required=True,
                    conformance_passed=physical_passed,
                    oracle_conformance_passed=oracle_passed,
                    physical_conformance_passed=physical_passed,
                    execution_layer=execution_layer,
                    evidence_type=evidence_type,
                    mismatch=mismatch,
                    leg_bindings=leg_bindings,
                )
            )
    if set(capture_values) - {row.row_id for row in rows}:
        raise ValueError("observation refers to an unknown matrix row")
    connection_counts: dict[str, int] = {}
    for connection in movements:
        connection_type = cast(str, connection.connection_type)
        connection_counts[connection_type] = (
            connection_counts.get(connection_type, 0) + 1
        )
    rows_tuple = tuple(rows)
    inventory_counts = {
        "points": len(points),
        "connections": len(movements),
        "connection_types": dict(sorted(connection_counts.items())),
    }
    known_physical = sum(
        row.physical_expectation.status != "unknown" for row in rows_tuple
    )
    physical_summary = {
        "rows": len(rows_tuple),
        "known_rows": known_physical,
        "unknown_rows": len(rows_tuple) - known_physical,
        "supported_rows": sum(
            row.physical_expectation.status == "supported" for row in rows_tuple
        ),
        "prohibited_rows": sum(
            row.physical_expectation.status == "prohibited" for row in rows_tuple
        ),
        "direct_edge_mismatches": sum(
            row.mismatch == "physical_prohibited_direct_handoff_used"
            for row in rows_tuple
        ),
    }
    coverage_summary = {
        "required": sum(row.coverage_required for row in rows_tuple),
        "exercised": sum(row.coverage_exercised for row in rows_tuple),
        "authentic_typed_capture": sum(
            row.coverage_exercised
            and row.execution_layer == "typed_tool_live"
            and (
                row.evidence_type
                in {"live_read_only_capture", "retained_production_capture"}
            )
            for row in rows_tuple
        ),
        "execution_layers": dict(
            sorted(
                {
                    layer: sum(row.execution_layer == layer for row in rows_tuple)
                    for layer in {row.execution_layer for row in rows_tuple}
                }.items()
            )
        ),
    }
    conformance_summary = {
        "required": sum(row.conformance_required for row in rows_tuple),
        "passed": sum(row.conformance_passed for row in rows_tuple),
        "oracle_passed": sum(row.oracle_conformance_passed for row in rows_tuple),
        "physical_passed": sum(row.physical_conformance_passed for row in rows_tuple),
        "mismatches": sum(row.mismatch is not None for row in rows_tuple),
    }
    payload = {
        "inventory": inventory_counts,
        "physical": physical_summary,
        "coverage": coverage_summary,
        "conformance": conformance_summary,
        "rows": [row.to_dict() for row in rows_tuple],
    }
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    return MatrixReport(
        rows_tuple,
        inventory_counts,
        physical_summary,
        coverage_summary,
        conformance_summary,
        digest,
    )


def validate_typed_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(fixture)
    fixture_id = data.get("fixture_id")
    tool = data.get("tool")
    if not isinstance(fixture_id, str) or not isinstance(tool, str):
        raise ValueError("typed fixture identity is incomplete")
    return cast(
        dict[str, Any],
        _v2_validate_fixture_file(
            data, Path("<memory>"), fixture_id, tool, "typed capture"
        ),
    )


def _tool_result_from_events(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for event in reversed(events):
        result = event.get("tool_result")
        if isinstance(result, Mapping):
            return cast(Mapping[str, Any], result)
    raise ValueError("typed tool stream returned no tool result")


async def _collect_stream(
    tool: _StreamTool, request: Mapping[str, Any], tool_use_id: str
) -> Mapping[str, Any]:
    stream = tool.stream(
        {"name": tool.tool_name, "toolUseId": tool_use_id, "input": dict(request)},
        {"agent": object()},
    )
    if not hasattr(stream, "__aiter__"):
        raise ValueError("typed tool stream is not asynchronous")
    events: list[Mapping[str, Any]] = []
    async for event in cast(Any, stream):
        if isinstance(event, Mapping):
            events.append(cast(Mapping[str, Any], event))
    return _tool_result_from_events(events)


def capture_typed_tool(
    tool_name: Literal["current", "annual"],
    request: Mapping[str, Any],
    *,
    evaluated_at: datetime | None = None,
    provenance: str,
    evidence_type: str = "live_read_only_capture",
    source: Mapping[str, str] | None = None,
    fixture_id: str | None = None,
    tool_use_id: str = "directional-capture",
) -> dict[str, Any]:
    """Invoke an unchanged public stream and bind its typed output to v2 fixture format."""
    evaluated_at = evaluated_at or datetime.now(UTC)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if not provenance.strip():
        raise ValueError("provenance is required")
    if evidence_type not in {
        "synthetic",
        "synthetic_fault",
        "synthetic_adversarial",
        "historical_replay",
        "retained_production_capture",
        "live_read_only_capture",
    }:
        raise ValueError("unsupported fixture evidence type")
    if evidence_type == "historical_replay":
        raise ValueError(
            "historical_replay requires a retained replay path; live capture cannot use this label"
        )
    if source is not None:
        raise ValueError(
            "source is derived from actual tool output and cannot be caller-supplied"
        )
    scope = (
        "connection_scope=separate_route_comparison_connections"
        if tool_name == "current"
        else "connection_scope=single_repeatable_read_transaction;independent_legs=outbound,return"
    )
    bound_provenance = f"{provenance};{scope}"
    typed_request = dict(request)
    from agent_tools import get_annual_toll_ballpark, get_current_toll_price

    stream_tool = (
        get_current_toll_price.get_current_toll_price
        if tool_name == "current"
        else get_annual_toll_ballpark.get_annual_toll_ballpark
    )
    _v2_validate_request(
        "get_current_toll_price"
        if tool_name == "current"
        else "get_annual_toll_ballpark",
        typed_request,
        "typed capture",
    )
    result = asyncio.run(
        _collect_stream(cast(_StreamTool, stream_tool), typed_request, tool_use_id)
    )
    tool_result = dict(result)
    fixture_id = (
        fixture_id
        or f"directional-capture-{hashlib.sha256(_canonical({'tool': tool_name, 'request': typed_request})).hexdigest()[:16]}"
    )
    if not _ID.fullmatch(fixture_id):
        raise ValueError("fixture_id is not stable")
    if evidence_type in {"live_read_only_capture", "retained_production_capture"}:
        source = {
            "id": fixture_id,
            "sha256": hashlib.sha256(_canonical(tool_result)).hexdigest(),
        }
    fixture: dict[str, Any] = {
        "fixture_id": fixture_id,
        "tool": "get_current_toll_price"
        if tool_name == "current"
        else "get_annual_toll_ballpark",
        "tool_contract_version": CURRENT_CONTRACT_VERSION
        if tool_name == "current"
        else ANNUAL_CONTRACT_VERSION,
        "evidence_type": evidence_type,
        "evaluated_at": evaluated_at.isoformat(),
        "provenance": bound_provenance,
        "source": dict(source) if source is not None else None,
        "request": typed_request,
    }
    if tool_result.get("status") == "error":
        fixture["error"] = tool_result
    else:
        content = tool_result.get("content")
        if (
            not isinstance(content, Sequence)
            or isinstance(content, (str, bytes))
            or (not content)
            or (not isinstance(content[0], Mapping))
            or (not isinstance(content[0].get("json"), Mapping))
        ):
            raise ValueError("typed tool result content is invalid")
        fixture["result"] = dict(cast(Mapping[str, Any], content[0]["json"]))
        result_time = cast(dict[str, Any], fixture["result"]).get("evaluated_at")
        if isinstance(result_time, str):
            _as_datetime(result_time, "result evaluated_at")
            fixture["evaluated_at"] = result_time
    return validate_typed_fixture(fixture)


def _check_report(report: MatrixReport) -> None:
    assert report.inventory_counts == {
        "points": 220,
        "connections": 996,
        "connection_types": {
            "airport_access": 12,
            "general_purpose_gap": 300,
            "toll_handoff": 14,
            "within_facility": 670,
        },
    }
    findings = {
        row.movement_id
        for row in report.rows
        if row.physical_expectation.status == "prohibited"
    }
    assert findings == set(_PROHIBITED_HANDOFFS)
    assert report.coverage_summary["exercised"] == 0
    assert cast(int, report.coverage_summary["required"]) > 1992
    assert report.coverage_summary["authentic_typed_capture"] == 0
    assert report.physical_summary["direct_edge_mismatches"] == 0
    assert len({row.row_id for row in report.rows}) == len(report.rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("directional-matrix.json"))
    args = parser.parse_args()
    points, connections = (build_points(), build_connections(build_points()))
    report = build_matrix({"points": points, "connections": connections}, captures={})
    if args.check:
        _check_report(report)
    args.output.write_bytes(_canonical(report.to_dict()))
    print(
        f"inventory: points={report.inventory_counts['points']} connections={report.inventory_counts['connections']} types={report.inventory_counts['connection_types']}"
    )
    print(
        f"coverage: required={report.coverage_summary['required']} exercised={report.coverage_summary['exercised']} authentic_typed_capture={report.coverage_summary['authentic_typed_capture']}"
    )
    print(
        f"conformance: required={report.conformance_summary['required']} passed={report.conformance_summary['passed']} oracle_passed={report.conformance_summary['oracle_passed']} mismatches={report.conformance_summary['mismatches']}"
    )
    print(f"canonical_json_sha256: {report.canonical_json_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

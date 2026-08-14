"""Oracle-backed routing tools owned by the orchestrator."""

from __future__ import annotations

import json
import math
import os
import secrets
from collections import OrderedDict
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Any, Literal, Protocol, cast
from zoneinfo import ZoneInfo

import boto3
from pydantic import BaseModel, ValidationError
from strands import tool  # pyright: ignore[reportUnknownVariableType]

from orchestrator.schemas import (
    CanonicalEndpoint,
    ConnectorStep,
    I95AccessRequest,
    I95AccessResult,
    I95DirectionRequest,
    I95DirectionResult,
    I95Validation,
    LaneObservation,
    RoutePlan,
    RouteRequest,
    TollStep,
    UnpricedStep,
    content_fingerprint,
)

type JsonObject = dict[str, Any]
type Nodes = dict[str, JsonObject]
type Pairs = list[JsonObject]

EASTERN = ZoneInfo("America/New_York")
_ORACLE_DIR = Path(__file__).resolve().parent.parent / "oracles"
_ORACLES: dict[str, JsonObject] = {
    name: cast(JsonObject, json.loads((_ORACLE_DIR / f"{name}.json").read_text()))
    for name in ("i95", "i66", "dulles_toll_road", "dulles_greenway")
}


class Cursor(Protocol):
    def execute(self, query: str, params: dict[str, object]) -> object: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class CursorContext(Protocol):
    def __enter__(self) -> Cursor: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class Connection(Protocol):
    def cursor(self) -> CursorContext: ...

    def close(self) -> None: ...


def _model_json(model: BaseModel) -> JsonObject:
    return model.model_dump(mode="json", exclude_none=False)


_EVIDENCE_LIMIT = 2048
# ponytail: process-local ledger; move it to session storage if concurrent eviction appears.
_EVIDENCE: OrderedDict[str, str] = OrderedDict()
_EVIDENCE_LOCK = Lock()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _register_evidence(prefix: str, values: JsonObject) -> JsonObject:
    return {**values, "validation_id": f"{prefix}-{secrets.token_urlsafe(24)}"}


def _record_evidence(model: BaseModel) -> JsonObject:
    issued = _model_json(model)
    validation_id = cast(str, issued["validation_id"])
    with _EVIDENCE_LOCK:
        _EVIDENCE[validation_id] = _canonical_json(issued)
        while len(_EVIDENCE) > _EVIDENCE_LIMIT:
            _EVIDENCE.popitem(last=False)
    return issued


def _is_issued_evidence(model: BaseModel) -> bool:
    value = _model_json(model)
    validation_id = value.get("validation_id")
    if not isinstance(validation_id, str):
        return False
    with _EVIDENCE_LOCK:
        return _EVIDENCE.get(validation_id) == _canonical_json(value)


def _parse_requested_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return parsed.astimezone(EASTERN)


def _connect() -> Connection:
    """Open an IAM-authenticated, TLS-verified read-only RDS connection."""
    import psycopg  # type: ignore[import-not-found]

    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    user = os.environ["DB_USER"]
    rds = cast(
        Any,
        boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "rds", region_name="us-east-1"
        ),
    )
    token = cast(
        str,
        rds.generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user),
    )
    return cast(
        Connection,
        psycopg.connect(
            host=host,
            port=port,
            dbname=os.environ["DB_NAME"],
            user=user,
            password=token,
            sslmode="verify-full",
            sslrootcert=os.environ["DB_CA_BUNDLE_PATH"],
            connect_timeout=10,
        ),
    )


def _label_index(nodes: Nodes) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        result.setdefault(cast(str, node["label"]).casefold(), []).append(node_id)
    return result


def _resolve(query: str, nodes: Nodes, labels: dict[str, list[str]]) -> list[str]:
    return [query] if query in nodes else labels.get(query.casefold(), [])


def _lookup(
    origin: str,
    destination: str,
    *,
    nodes: Nodes,
    pairs: Pairs,
    labels: dict[str, list[str]],
    oracle_name: str,
) -> JsonObject:
    origin_ids = _resolve(origin, nodes, labels)
    destination_ids = _resolve(destination, nodes, labels)
    origin_options = sorted({nodes[pair["entry"]]["label"] for pair in pairs})
    destination_options = sorted({nodes[pair["exit"]]["label"] for pair in pairs})
    if not origin_ids:
        return {
            "error": f"unknown origin {origin!r} in the {oracle_name} oracle",
            "valid_options": origin_options,
        }
    if not destination_ids:
        return {
            "error": f"unknown destination {destination!r} in the {oracle_name} oracle",
            "valid_options": destination_options,
        }
    matches = [
        pair
        for pair in pairs
        if pair["entry"] in origin_ids and pair["exit"] in destination_ids
    ]
    if not matches:
        return {
            "error": f"no direct trip from {origin!r} to {destination!r}",
            "valid_options": sorted(
                {
                    nodes[pair["exit"]]["label"]
                    for pair in pairs
                    if pair["entry"] in origin_ids
                }
            ),
        }
    if len(matches) > 1:
        return {
            "error": f"ambiguous trip from {origin!r} to {destination!r}",
            "valid_options": sorted(
                {pair["entry"] for pair in matches} | {pair["exit"] for pair in matches}
            ),
        }
    pair = matches[0]
    return {
        "direction": pair["direction"],
        "entry": {
            "node_id": pair["entry"],
            "label": nodes[pair["entry"]]["label"],
        },
        "exit": {
            "node_id": pair["exit"],
            "label": nodes[pair["exit"]]["label"],
        },
        "pair": pair,
    }


def _directional_mismatch(
    origin: str,
    destination: str,
    *,
    nodes: Nodes,
    pairs: Pairs,
    labels: dict[str, list[str]],
    position: Callable[[str], float],
    increasing_direction: str,
    decreasing_direction: str,
    distance: Callable[[str, list[str]], float] | None = None,
    preferred: Mapping[tuple[str, str, str], list[str]] | None = None,
) -> JsonObject:
    origin_ids = _resolve(origin, nodes, labels)
    destination_ids = _resolve(destination, nodes, labels)
    if not origin_ids or not destination_ids:
        return {}
    origin_position = sum(map(position, origin_ids)) / len(origin_ids)
    destination_position = sum(map(position, destination_ids)) / len(destination_ids)
    if origin_position == destination_position:
        return {}
    direction = (
        increasing_direction
        if destination_position > origin_position
        else decreasing_direction
    )

    def role_directions(ids: list[str], role: str) -> set[str]:
        return {cast(str, pair["direction"]) for pair in pairs if pair[role] in ids}

    invalid = [
        item
        for item in (
            (origin, origin_ids, "entry", destination_ids),
            (destination, destination_ids, "exit", origin_ids),
        )
        if direction not in role_directions(item[1], item[2])
    ]
    constraints: list[JsonObject] = []
    for location, location_ids, role, opposite_ids in invalid:
        opposite_role = "exit" if role == "entry" else "entry"
        candidates = {
            cast(str, pair[role])
            for pair in pairs
            if pair["direction"] == direction
            and (len(invalid) != 1 or pair[opposite_role] in opposite_ids)
        }
        distances: dict[str, float] = {}
        for node_id in candidates:
            label = cast(str, nodes[node_id]["label"])
            candidate_distance = (
                distance(node_id, location_ids)
                if distance
                else min(
                    abs(position(node_id) - position(item)) for item in location_ids
                )
            )
            distances[label] = min(
                distances.get(label, float("inf")), candidate_distance
            )
        favorites = (preferred or {}).get((location, role, direction), [])
        nearby = sorted(
            distances,
            key=lambda label: (
                favorites.index(label) if label in favorites else len(favorites),
                distances[label],
                label,
            ),
        )[:2]
        constraints.append(
            {
                "location": location,
                "role": role,
                "required_direction": direction,
                "available_directions": sorted(role_directions(location_ids, role)),
                "nearby_options": nearby,
            }
        )
    if len(constraints) == 2:
        entry = next(item for item in constraints if item["role"] == "entry")
        exit = next(item for item in constraints if item["role"] == "exit")

        def has_pair(entry_label: str, exit_label: str) -> bool:
            entry_ids = _resolve(entry_label, nodes, labels)
            exit_ids = _resolve(exit_label, nodes, labels)
            return any(
                pair["entry"] in entry_ids and pair["exit"] in exit_ids
                for pair in pairs
            )

        entries = entry["nearby_options"]
        exits = exit["nearby_options"]
        entry["nearby_options"] = [
            label for label in entries if any(has_pair(label, other) for other in exits)
        ]
        exit["nearby_options"] = [
            label for label in exits if any(has_pair(other, label) for other in entries)
        ]
    return (
        {
            "status": "one_way_mismatch",
            "direction": direction,
            "constraints": constraints,
        }
        if constraints
        else {}
    )


_ALL_I95_NODES: Nodes = _ORACLES["i95"]["nodes"]
_ALL_I95_PAIRS: Pairs = _ORACLES["i95"]["pairs"]


def _is_i495(node_id: str) -> bool:
    return cast(str, _ALL_I95_NODES[node_id]["path"]).startswith("495")


_I95_PAIRS = [
    pair
    for pair in _ALL_I95_PAIRS
    if not _is_i495(pair["entry"]) and not _is_i495(pair["exit"])
]
_I95_NODES = {
    node_id: _ALL_I95_NODES[node_id]
    for pair in _I95_PAIRS
    for node_id in (pair["entry"], pair["exit"])
}
_I95_LABELS = _label_index(_I95_NODES)
_I495_PAIRS = [
    pair
    for pair in _ALL_I95_PAIRS
    if _is_i495(pair["entry"]) and _is_i495(pair["exit"])
]
_I495_NODES = {
    node_id: _ALL_I95_NODES[node_id]
    for pair in _I495_PAIRS
    for node_id in (pair["entry"], pair["exit"])
}
_I495_LABELS = _label_index(_I495_NODES)
_I66_NODES: Nodes = _ORACLES["i66"]["nodes"]
_I66_PAIRS: Pairs = _ORACLES["i66"]["pairs"]
_I66_LABELS = _label_index(_I66_NODES)
_I66_POSITION = {
    node_id: float(position)
    for position, node_ids in enumerate(
        (
            ("1",),
            ("2", "3", "5"),
            ("4",),
            ("6",),
            ("7",),
            ("10",),
            ("11",),
            ("8", "9", "12"),
            ("13", "17"),
            ("14",),
            ("15",),
            ("16",),
        )
    )
    for node_id in node_ids
}


def _i95_distance(node_id: str, location_ids: list[str]) -> float:
    latitude = math.radians(float(_I95_NODES[node_id]["latitude"]))
    longitude = math.radians(float(_I95_NODES[node_id]["longitude"]))
    distances: list[float] = []
    for location_id in location_ids:
        other_latitude = math.radians(float(_I95_NODES[location_id]["latitude"]))
        other_longitude = math.radians(float(_I95_NODES[location_id]["longitude"]))
        delta_latitude = other_latitude - latitude
        delta_longitude = other_longitude - longitude
        haversine = (
            math.sin(delta_latitude / 2) ** 2
            + math.cos(latitude)
            * math.cos(other_latitude)
            * math.sin(delta_longitude / 2) ** 2
        )
        distances.append(math.asin(math.sqrt(haversine)))
    return min(distances)


def _oracle_lookup(
    origin: str,
    destination: str,
    *,
    nodes: Nodes,
    pairs: Pairs,
    labels: dict[str, list[str]],
    oracle_name: str,
    position: Callable[[str], float],
    increasing_direction: str,
    decreasing_direction: str,
    distance: Callable[[str, list[str]], float] | None = None,
    preferred: Mapping[tuple[str, str, str], list[str]] | None = None,
) -> JsonObject:
    result = _lookup(
        origin,
        destination,
        nodes=nodes,
        pairs=pairs,
        labels=labels,
        oracle_name=oracle_name,
    )
    if cast(str, result.get("error", "")).startswith("no direct trip"):
        result.update(
            _directional_mismatch(
                origin,
                destination,
                nodes=nodes,
                pairs=pairs,
                labels=labels,
                position=position,
                increasing_direction=increasing_direction,
                decreasing_direction=decreasing_direction,
                distance=distance,
                preferred=preferred,
            )
        )
    return result


def _i95_lookup(origin: str, destination: str) -> JsonObject:
    return _oracle_lookup(
        origin,
        destination,
        nodes=_I95_NODES,
        pairs=_I95_PAIRS,
        labels=_I95_LABELS,
        oracle_name="i95",
        position=lambda node_id: float(_I95_NODES[node_id]["latitude"]),
        increasing_direction="Northbound",
        decreasing_direction="Southbound",
        distance=_i95_distance,
    )


def _i495_lookup(origin: str, destination: str) -> JsonObject:
    return _oracle_lookup(
        origin,
        destination,
        nodes=_I495_NODES,
        pairs=_I495_PAIRS,
        labels=_I495_LABELS,
        oracle_name="i495",
        position=lambda node_id: float(_I495_NODES[node_id]["latitude"]),
        increasing_direction="Northbound",
        decreasing_direction="Southbound",
    )


def _i66_lookup(origin: str, destination: str) -> JsonObject:
    return _oracle_lookup(
        origin,
        destination,
        nodes=_I66_NODES,
        pairs=_I66_PAIRS,
        labels=_I66_LABELS,
        oracle_name="i66",
        position=_I66_POSITION.__getitem__,
        increasing_direction="EB",
        decreasing_direction="WB",
        preferred={
            ("Lee Highway - Scott Street", "exit", "EB"): [
                "Fairfax Drive",
                "Lee Highway - Spout Run Parkway",
            ]
        },
    )


_DULLES_BOUNDARY = "Route 28 (Dulles Toll Road / Dulles Greenway)"
_GREENWAY_POSITION = {
    "1": 0.0,
    "2A": 1.0,
    "2B": 1.1,
    "3": 2.0,
    "4": 3.0,
    "5": 4.0,
    "6": 5.0,
    "7": 6.0,
    "8": 7.0,
    "28": 8.0,
}


def _load_dulles(name: str) -> JsonObject:
    oracle = _ORACLES[name]
    nodes: Nodes = oracle["nodes"]
    return {
        "nodes": nodes,
        "pairs": oracle["pairs"],
        "labels": _label_index(nodes),
        "boundary_id": next(
            node_id
            for node_id, node in nodes.items()
            if node["label"] == _DULLES_BOUNDARY
        ),
    }


_DULLES = {name: _load_dulles(name) for name in ("dulles_toll_road", "dulles_greenway")}


def _dulles_ids(facility: JsonObject, query: str) -> list[str]:
    return _resolve(query, facility["nodes"], facility["labels"])


def _dulles_pairs(
    facility: JsonObject, origin_ids: list[str], destination_ids: list[str]
) -> Pairs:
    return [
        pair
        for pair in facility["pairs"]
        if pair["entry"] in origin_ids and pair["exit"] in destination_ids
    ]


def _dulles_lookup(origin: str, destination: str) -> JsonObject:
    origin_ids = {name: _dulles_ids(data, origin) for name, data in _DULLES.items()}
    destination_ids = {
        name: _dulles_ids(data, destination) for name, data in _DULLES.items()
    }
    if not any(origin_ids.values()) or not any(destination_ids.values()):
        role = "origin" if not any(origin_ids.values()) else "destination"
        return {
            "error": f"unknown {role} on the Dulles facilities",
            "valid_options": sorted(
                {
                    facility["nodes"][pair["entry" if role == "origin" else "exit"]][
                        "label"
                    ]
                    for facility in _DULLES.values()
                    for pair in facility["pairs"]
                }
            ),
        }
    single = [
        (name, pair)
        for name, facility in _DULLES.items()
        for pair in _dulles_pairs(facility, origin_ids[name], destination_ids[name])
    ]
    if len(single) == 1:
        return {"legs": single}
    for first, second in (
        ("dulles_toll_road", "dulles_greenway"),
        ("dulles_greenway", "dulles_toll_road"),
    ):
        if not origin_ids[first] or not destination_ids[second]:
            continue
        first_data, second_data = _DULLES[first], _DULLES[second]
        first_legs = _dulles_pairs(
            first_data, origin_ids[first], [first_data["boundary_id"]]
        )
        second_legs = _dulles_pairs(
            second_data, [second_data["boundary_id"]], destination_ids[second]
        )
        if len(first_legs) == len(second_legs) == 1:
            return {"legs": [(first, first_legs[0]), (second, second_legs[0])]}
    greenway = _DULLES["dulles_greenway"]
    mismatch_origin = origin if origin_ids["dulles_greenway"] else _DULLES_BOUNDARY
    mismatch_destination = (
        destination if destination_ids["dulles_greenway"] else _DULLES_BOUNDARY
    )
    mismatch = _directional_mismatch(
        mismatch_origin,
        mismatch_destination,
        nodes=greenway["nodes"],
        pairs=greenway["pairs"],
        labels=greenway["labels"],
        position=_GREENWAY_POSITION.__getitem__,
        increasing_direction="EB",
        decreasing_direction="WB",
        preferred={
            ("Exit 2B - Compass Creek Pkwy", "entry", "EB"): [
                "Exit 2 - Battlefield Pkwy"
            ]
        },
    )
    return mismatch or {
        "error": f"no direct or connecting trip from {origin!r} to {destination!r}",
        "valid_options": [],
    }


_STATUS_OD_PAIR_IDS = {"Northbound": 1132, "Southbound": 1151}
_EXPECTED_STATUS = {
    "Northbound": ("I-95-NB", "NORTHBOUND_OPEN"),
    "Southbound": ("I-95-SB", "SOUTHBOUND_OPEN"),
}
_I95_STATUS_SQL = """
SELECT od_pair_id, corridor_name, interval_end_at, calculated_at, link_status
FROM trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
  AND interval_end_at <= %(requested_at)s
ORDER BY interval_end_at DESC
LIMIT 1
"""


def _unavailable_direction(
    requested_at: str,
    reason_code: str,
    reason: str,
    observations: list[LaneObservation] | None = None,
) -> JsonObject:
    return _record_evidence(
        I95DirectionResult.model_validate(
            _register_evidence(
                "direction",
                {
                    "status": "unavailable",
                    "requested_at": requested_at,
                    "source_kind": "observed",
                    "open_direction": None,
                    "observations": [
                        item.model_dump(mode="json") for item in observations or []
                    ],
                    "reason_code": reason_code,
                    "reason": reason,
                },
            )
        )
    )


@tool(inputSchema={"json": I95DirectionRequest.model_json_schema()})
def i95_direction(requested_at: str) -> JsonObject:
    """Return observed I-95/395 reversible-lane direction evidence.

    Call before any I-95 access or route request. Future times are unavailable;
    this tool never infers the reversible-lane schedule.
    """
    try:
        resolved_at = _parse_requested_at(requested_at)
    except (TypeError, ValueError) as error:
        return _unavailable_direction(
            requested_at, "invalid_time", f"invalid requested_at: {error}"
        )
    if resolved_at > datetime.now(EASTERN):
        return _unavailable_direction(
            resolved_at.isoformat(),
            "future_direction_unavailable",
            "authoritative future I-95 direction is unavailable",
        )

    connection = _connect()
    try:
        observations: list[LaneObservation] = []
        with connection.cursor() as cursor:
            for direction, od_pair_id in _STATUS_OD_PAIR_IDS.items():
                cursor.execute(
                    _I95_STATUS_SQL,
                    {"od_pair_id": od_pair_id, "requested_at": resolved_at},
                )
                row = cursor.fetchone()
                if row is None:
                    continue
                row_id, corridor_name, effective_at, observed_at, link_status = row
                expected_corridor = _EXPECTED_STATUS[direction][0]
                if row_id != od_pair_id or corridor_name != expected_corridor:
                    continue
                observations.append(
                    LaneObservation(
                        direction=cast(Any, direction),
                        od_pair_id=cast(int, row_id),
                        corridor_name=cast(Any, corridor_name),
                        link_status=cast(str, link_status),
                        effective_at=cast(datetime, effective_at).isoformat(),
                        observed_at=cast(datetime, observed_at).isoformat(),
                    )
                )
    finally:
        connection.close()

    if len(observations) != 2:
        return _unavailable_direction(
            resolved_at.isoformat(),
            "missing_observation",
            "VDOT lane status is unavailable for one or both directions",
            observations,
        )
    if len({observation.effective_at for observation in observations}) != 1:
        return _unavailable_direction(
            resolved_at.isoformat(),
            "mismatched_intervals",
            "VDOT lane statuses are not from one common interval",
            observations,
        )
    open_directions = [
        observation.direction
        for observation in observations
        if observation.link_status == _EXPECTED_STATUS[observation.direction][1]
    ]
    if len(open_directions) != 1:
        return _unavailable_direction(
            resolved_at.isoformat(),
            "direction_indeterminate",
            "I-95 does not have exactly one fully open direction",
            observations,
        )
    return _record_evidence(
        I95DirectionResult.model_validate(
            _register_evidence(
                "direction",
                {
                    "status": "supported",
                    "requested_at": resolved_at.isoformat(),
                    "source_kind": "observed",
                    "open_direction": cast(Any, open_directions[0]),
                    "observations": [
                        item.model_dump(mode="json") for item in observations
                    ],
                },
            )
        )
    )


_JUNCTION_BOUNDARIES = {
    "i95_to_i495": {
        "Northbound": "Franconia-Springfield Parkway/Route 289",
        "Southbound": "I-395 Near Edsall Road",
    },
    "i495_to_i95": {
        "Northbound": "I-395 Near Edsall Road",
        "Southbound": "Franconia-Springfield Parkway/Route 289",
    },
}


def _junction_lookup(location: str, movement: str, direction: str) -> JsonObject:
    boundary = _JUNCTION_BOUNDARIES[movement][direction]
    origin, destination = (
        (location, boundary) if movement == "i95_to_i495" else (boundary, location)
    )
    if location.casefold() == boundary.casefold():
        ids = _resolve(location, _I95_NODES, _I95_LABELS)
        candidates = [
            node_id
            for node_id in ids
            if any(
                pair["direction"] == direction
                and (
                    pair["entry"] == node_id
                    if movement == "i95_to_i495"
                    else pair["exit"] == node_id
                )
                for pair in _I95_PAIRS
            )
        ]
        if candidates:
            node_id = candidates[0]
            return {
                "direction": direction,
                "entry": {"node_id": node_id, "label": location},
                "exit": {"node_id": node_id, "label": location},
            }
    result = _i95_lookup(origin, destination)
    return result if result.get("direction") == direction else {"error": "no route"}


def _access_result(
    request: I95AccessRequest,
    direction: I95DirectionResult | None,
    *,
    status: str,
    **values: object,
) -> JsonObject:
    result = {
        "status": status,
        "origin_corridor": request.origin_corridor,
        "origin": request.origin,
        "destination_corridor": request.destination_corridor,
        "destination": request.destination,
        "requested_at": direction.requested_at if direction else None,
        "open_direction": direction.open_direction if direction else None,
        **values,
    }
    if direction is not None:
        result = _register_evidence("access", result)
    validated = I95AccessResult.model_validate(result)
    return (
        _record_evidence(validated) if direction is not None else _model_json(validated)
    )


def _supported_access(
    request: I95AccessRequest,
    direction: I95DirectionResult,
    route: JsonObject,
    movement: str,
) -> JsonObject:
    return _access_result(
        request,
        direction,
        status="supported",
        required_direction=route["direction"],
        movement=movement,
        entry_node_id=route["entry"]["node_id"],
        exit_node_id=route["exit"]["node_id"],
    )


@tool(inputSchema={"json": I95AccessRequest.model_json_schema()})
def i95_access_options(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
    direction_result: dict[str, object],
) -> JsonObject:
    """Validate direct or cross-corridor I-95 ramp access.

    Copy the complete result of i95_direction. A mismatch returns only nearby
    oracle-supported alternatives; it never silently substitutes one.
    """
    try:
        request = I95AccessRequest.model_validate(
            {
                "origin_corridor": origin_corridor,
                "origin": origin,
                "destination_corridor": destination_corridor,
                "destination": destination,
                "direction_result": direction_result,
            }
        )
        direction = I95DirectionResult.model_validate(direction_result)
    except ValidationError as error:
        fallback = I95AccessRequest.model_construct(
            origin_corridor=origin_corridor,
            origin=origin,
            destination_corridor=destination_corridor,
            destination=destination,
            direction_result=direction_result,
        )
        return _access_result(
            fallback,
            None,
            status="invalid_evidence",
            reason=f"invalid I-95 direction evidence: {error.errors()[0]['msg']}",
        )
    if not _is_issued_evidence(direction):
        return _access_result(
            request,
            None,
            status="invalid_evidence",
            reason="I-95 direction evidence was not issued by i95_direction",
        )
    if direction.status != "supported" or direction.open_direction is None:
        return _access_result(
            request,
            direction,
            status="unavailable",
            reason=direction.reason or "I-95 direction is unavailable",
        )

    open_direction = direction.open_direction
    if origin_corridor == destination_corridor == "i95":
        route = _i95_lookup(origin, destination)
        required = route.get("direction")
        if required is not None and required != open_direction:
            return _access_result(
                request,
                direction,
                status="direction_closed",
                required_direction=required,
                movement="direct",
                reason=f"the requested {required.lower()} direction is closed",
            )
        if route.get("status") == "one_way_mismatch":
            return _access_result(
                request,
                direction,
                status="one_way_mismatch",
                required_direction=required,
                movement="direct",
                constraints=route["constraints"],
                reason="one or more requested ramps cannot serve this direction",
            )
        if "error" in route:
            return _access_result(
                request, direction, status="unsupported", reason=route["error"]
            )
        return _supported_access(request, direction, route, "direct")

    if origin_corridor == "airport_dca" and destination_corridor == "i95":
        route = _i95_lookup("2233SO", destination)
        required = route.get("direction")
        if required is not None and required != open_direction:
            return _access_result(
                request,
                direction,
                status="direction_closed",
                required_direction=required,
                movement="direct",
                reason=f"the requested {required.lower()} direction is closed",
            )
        if "error" in route:
            return _access_result(
                request, direction, status="unsupported", reason=route["error"]
            )
        return _supported_access(request, direction, route, "direct")

    if origin_corridor == "i95" and destination_corridor == "airport_dca":
        exits = {"Northbound": "223ND", "Southbound": "2239ND"}
        route = _i95_lookup(origin, exits[open_direction])
        if "error" not in route and route.get("direction") == open_direction:
            return _supported_access(request, direction, route, "direct")
        opposite = "Southbound" if open_direction == "Northbound" else "Northbound"
        opposite_route = _i95_lookup(origin, exits[opposite])
        if "error" not in opposite_route:
            return _access_result(
                request,
                direction,
                status="direction_closed",
                required_direction=opposite,
                movement="direct",
                reason=f"the requested {opposite.lower()} direction is closed",
            )
        return _access_result(
            request,
            direction,
            status="unsupported",
            reason="no oracle-supported I-95 route reaches Reagan airport access",
        )

    if origin_corridor == "i95" and destination_corridor != "airport_dca":
        movement = "i95_to_i495"
        location = origin
    elif destination_corridor == "i95" and origin_corridor != "airport_dca":
        movement = "i495_to_i95"
        location = destination
    elif origin_corridor == "airport_dca":
        movement = "i95_to_i495"
        location = "2233SO"
    elif destination_corridor == "airport_dca":
        movement = "i495_to_i95"
        location = {
            "Northbound": "223ND",
            "Southbound": "2239ND",
        }[open_direction]
    else:
        return _access_result(
            request,
            direction,
            status="unsupported",
            reason="this access tool supports direct I-95 and documented I-95/I-495 handoffs",
        )

    route = _junction_lookup(location, movement, open_direction)
    if "error" not in route:
        return _supported_access(request, direction, route, movement)
    opposite = "Southbound" if open_direction == "Northbound" else "Northbound"
    opposite_route = _junction_lookup(location, movement, opposite)
    if "error" not in opposite_route:
        return _access_result(
            request,
            direction,
            status="direction_closed",
            required_direction=opposite,
            movement=movement,
            reason=f"the requested {opposite.lower()} direction is closed",
        )
    mismatch = (
        _i95_lookup(
            location,
            _JUNCTION_BOUNDARIES[movement][open_direction],
        )
        if movement == "i95_to_i495"
        else _i95_lookup(_JUNCTION_BOUNDARIES[movement][open_direction], location)
    )
    if mismatch.get("status") == "one_way_mismatch":
        return _access_result(
            request,
            direction,
            status="one_way_mismatch",
            required_direction=open_direction,
            movement=movement,
            constraints=mismatch["constraints"],
            reason="the requested I-95 ramp cannot serve the open direction",
        )
    return _access_result(
        request,
        direction,
        status="unsupported",
        reason="no oracle-supported I-95 handoff serves this trip",
    )


AIRPORT_ENDPOINTS = {
    "airport_iad": "Dulles International Airport (IAD)",
    "airport_dca": "Ronald Reagan Washington National Airport (DCA)",
}
_DULLES_CORRIDORS = {"dulles_toll_road", "dulles_greenway"}
_I495_JUNCTION_ENTRY = "191NO"
_I495_JUNCTION_EXIT = "191SD"
_DCA_I95_HANDOFF = "Pentagon/Eads Street"

NETWORK_TRANSFERS: list[JsonObject] = [
    {
        "id": "iad_to_i66",
        "from": {
            "corridor": "airport_iad",
            "node_id": AIRPORT_ENDPOINTS["airport_iad"],
        },
        "to": {"corridor": "i66_itb", "node_id": "6"},
        "connector": "Dulles Airport Access Highway",
    },
    {
        "id": "i66_to_iad",
        "from": {"corridor": "i66_itb", "node_id": "6"},
        "to": {"corridor": "airport_iad", "node_id": AIRPORT_ENDPOINTS["airport_iad"]},
        "connector": "Dulles Airport Access Highway",
    },
    {
        "id": "dca_to_i95",
        "from": {
            "corridor": "airport_dca",
            "node_id": AIRPORT_ENDPOINTS["airport_dca"],
        },
        "to": {"corridor": "i95", "node_id": "2233SO"},
        "connector": "Reagan airport access",
    },
    {
        "id": "i95_to_dca_northbound",
        "from": {"corridor": "i95", "node_id": "223ND"},
        "to": {"corridor": "airport_dca", "node_id": AIRPORT_ENDPOINTS["airport_dca"]},
        "connector": "Reagan airport access",
    },
    {
        "id": "i95_to_dca_southbound",
        "from": {"corridor": "i95", "node_id": "2239ND"},
        "to": {"corridor": "airport_dca", "node_id": AIRPORT_ENDPOINTS["airport_dca"]},
        "connector": "Reagan airport access",
    },
    {
        "id": "i66_to_i495",
        "from": {"corridor": "i66_itb", "node_id": "5"},
        "to": {"corridor": "i495", "node_id": "187SO"},
        "connector": "I-66/I-495 interchange",
    },
    {
        "id": "i66_to_i495_north",
        "from": {"corridor": "i66_itb", "node_id": "5"},
        "to": {"corridor": "i495", "node_id": "187NO"},
        "connector": "I-66/I-495 interchange",
    },
    {
        "id": "i495_to_i66",
        "from": {"corridor": "i495", "node_id": "187ND"},
        "to": {"corridor": "i66_itb", "node_id": "3"},
        "connector": "I-66/I-495 interchange",
    },
    {
        "id": "i495_south_to_i66",
        "from": {"corridor": "i495", "node_id": "187SD"},
        "to": {"corridor": "i66_itb", "node_id": "5"},
        "connector": "I-66/I-495 interchange",
    },
    {
        "id": "dulles_toll_road_to_i495",
        "from": {"corridor": "dulles_toll_road", "node_id": "1819"},
        "to": {"corridor": "i495", "node_id": "182SO"},
        "connector": "I-495/Route 267 interchange",
    },
    {
        "id": "dulles_toll_road_to_i495_north",
        "from": {"corridor": "dulles_toll_road", "node_id": "1819"},
        "to": {"corridor": "i495", "node_id": "182NO"},
        "connector": "I-495/Route 267 interchange",
    },
    {
        "id": "i495_to_dulles_toll_road",
        "from": {"corridor": "i495", "node_id": "182ND"},
        "to": {"corridor": "dulles_toll_road", "node_id": "1819"},
        "connector": "I-495/Route 267 interchange",
    },
    {
        "id": "i495_south_to_dulles_toll_road",
        "from": {"corridor": "i495", "node_id": "182SD"},
        "to": {"corridor": "dulles_toll_road", "node_id": "1819"},
        "connector": "I-495/Route 267 interchange",
    },
    {
        "id": "i66_to_dulles_toll_road",
        "from": {"corridor": "i66_itb", "node_id": "6"},
        "to": {"corridor": "dulles_toll_road", "node_id": "66"},
        "connector": "I-66 / Dulles Toll Road junction",
    },
    {
        "id": "dulles_toll_road_to_i66",
        "from": {"corridor": "dulles_toll_road", "node_id": "66"},
        "to": {"corridor": "i66_itb", "node_id": "6"},
        "connector": "I-66 / Dulles Toll Road junction",
    },
]
_TRANSFER_BY_ID = {transfer["id"]: transfer for transfer in NETWORK_TRANSFERS}
_ROUTE_267_DETOUR_CONNECTORS = {
    "I-66 / Dulles Toll Road junction",
    "I-495/Route 267 interchange",
}


def _locations(nodes: Nodes, pairs: Pairs) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    for node_id, node in nodes.items():
        label = cast(str, node["label"])
        for key in (label, node_id):
            location = result.setdefault(
                key, {"label": label, "entry": False, "exit": False}
            )
            location["entry"] = location["entry"] or any(
                pair["entry"] == node_id for pair in pairs
            )
            location["exit"] = location["exit"] or any(
                pair["exit"] == node_id for pair in pairs
            )
    return result


_LOCATION_BY_CORRIDOR: dict[str, dict[str, JsonObject]] = {
    "i95": _locations(_I95_NODES, _I95_PAIRS),
    "i495": _locations(_I495_NODES, _I495_PAIRS),
    "i66_itb": _locations(_I66_NODES, _I66_PAIRS),
    "dulles_toll_road": _locations(
        _DULLES["dulles_toll_road"]["nodes"],
        _DULLES["dulles_toll_road"]["pairs"],
    ),
    "dulles_greenway": _locations(
        _DULLES["dulles_greenway"]["nodes"],
        _DULLES["dulles_greenway"]["pairs"],
    ),
    **{
        corridor: {label: {"label": label, "entry": True, "exit": True}}
        for corridor, label in AIRPORT_ENDPOINTS.items()
    },
}


def _same_location(corridor: str, query: str, node_id: str) -> bool:
    if corridor in AIRPORT_ENDPOINTS:
        return query.casefold() == node_id.casefold()
    return query == node_id or _LOCATION_BY_CORRIDOR[corridor].get(query, {}).get(
        "label"
    ) == _LOCATION_BY_CORRIDOR[corridor].get(node_id, {}).get("label")


def _route_lookup(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> JsonObject:
    if (
        origin_corridor in AIRPORT_ENDPOINTS
        or destination_corridor in AIRPORT_ENDPOINTS
    ):
        return {"error": "airport endpoints require a documented connector"}
    if {origin_corridor, destination_corridor} <= _DULLES_CORRIDORS:
        return _dulles_lookup(origin, destination)
    if origin_corridor != destination_corridor:
        return {"error": "different corridors"}
    return {
        "i95": _i95_lookup,
        "i495": _i495_lookup,
        "i66_itb": _i66_lookup,
    }[origin_corridor](origin, destination)


def _raw_toll(corridor: str, origin: str, destination: str) -> JsonObject:
    return {
        "kind": "toll",
        "corridor": corridor,
        "origin": origin,
        "destination": destination,
    }


def _raw_junction(movement: str, location: str) -> JsonObject:
    return {"kind": "junction", "movement": movement, "location": location}


def _requested_mismatch(
    result: JsonObject,
    leg_origin: tuple[str, str],
    leg_destination: tuple[str, str],
    requested_origin: tuple[str, str],
    requested_destination: tuple[str, str],
) -> JsonObject | None:
    constraints = [
        constraint
        for constraint in result.get("constraints", [])
        if (
            constraint.get("role") == "entry"
            and leg_origin[0] == requested_origin[0]
            and _same_location(
                leg_origin[0], constraint.get("location", ""), requested_origin[1]
            )
        )
        or (
            constraint.get("role") == "exit"
            and leg_destination[0] == requested_destination[0]
            and _same_location(
                leg_destination[0],
                constraint.get("location", ""),
                requested_destination[1],
            )
        )
    ]
    return (
        {
            "status": "one_way_mismatch",
            "direction": result.get("direction"),
            "constraints": constraints,
        }
        if constraints
        else None
    )


def _can_route(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> bool:
    result = _route_lookup(origin_corridor, origin, destination_corridor, destination)
    return "error" not in result and result.get("status") != "one_way_mismatch"


def _planned_steps(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> list[JsonObject] | JsonObject | None:
    frontier: list[tuple[str, str, list[JsonObject]]] = [(origin_corridor, origin, [])]
    visited = {(origin_corridor, origin)}
    mismatch: JsonObject | None = None
    while frontier:
        corridor, point, steps = frontier.pop(0)
        if (
            corridor == destination_corridor
            and _same_location(corridor, destination, point)
            and _LOCATION_BY_CORRIDOR[corridor][destination]["exit"]
        ):
            return steps
        direct = _route_lookup(corridor, point, destination_corridor, destination)
        if direct.get("status") == "one_way_mismatch":
            mismatch = mismatch or _requested_mismatch(
                direct,
                (corridor, point),
                (destination_corridor, destination),
                (origin_corridor, origin),
                (destination_corridor, destination),
            )
        elif "error" not in direct:
            return [*steps, _raw_toll(corridor, point, destination)]

        if (
            corridor == destination_corridor == "i495"
            and steps
            and steps[-1]["kind"] == "junction"
        ):
            return [
                *steps,
                {
                    "kind": "unpriced",
                    "reason": "I-495 endpoint lies inside the unpriced junction gap",
                },
            ]
        if corridor == "i95" and destination_corridor not in {"i95", "airport_dca"}:
            state = ("i495", _I495_JUNCTION_ENTRY)
            if state not in visited:
                visited.add(state)
                frontier.append((*state, [*steps, _raw_junction("i95_to_i495", point)]))
            continue
        if corridor == "i495" and destination_corridor in {"i95", "airport_dca"}:
            priced = (
                [_raw_toll("i495", point, _I495_JUNCTION_EXIT)]
                if _can_route("i495", point, "i495", _I495_JUNCTION_EXIT)
                else []
            )
            to_i95 = [
                *steps,
                *priced,
                _raw_junction(
                    "i495_to_i95",
                    _DCA_I95_HANDOFF
                    if destination_corridor == "airport_dca"
                    else destination,
                ),
            ]
            if destination_corridor == "airport_dca":
                return [
                    *to_i95,
                    {
                        "kind": "connector",
                        "transfer_id": "i95_to_dca_northbound",
                        "label": "Reagan airport access",
                    },
                ]
            return to_i95

        for transfer in NETWORK_TRANSFERS:
            if any(
                step.get("kind") == "connector"
                and step.get("label") == transfer["connector"]
                for step in steps
            ):
                continue
            source = transfer["from"]
            if corridor == source["corridor"] and _same_location(
                corridor, point, source["node_id"]
            ):
                priced = []
            else:
                source_route = _route_lookup(
                    corridor, point, source["corridor"], source["node_id"]
                )
                if source_route.get("status") == "one_way_mismatch":
                    mismatch = mismatch or _requested_mismatch(
                        source_route,
                        (corridor, point),
                        (source["corridor"], source["node_id"]),
                        (origin_corridor, origin),
                        (destination_corridor, destination),
                    )
                    continue
                if "error" in source_route:
                    continue
                priced = [_raw_toll(corridor, point, source["node_id"])]
            target = transfer["to"]
            state = (target["corridor"], target["node_id"])
            if state in visited:
                continue
            visited.add(state)
            frontier.append(
                (
                    *state,
                    [
                        *steps,
                        *priced,
                        {
                            "kind": "connector",
                            "transfer_id": transfer["id"],
                            "label": transfer["connector"],
                        },
                    ],
                )
            )
    return mismatch


def _toll_steps(corridor: str, origin: str, destination: str) -> list[TollStep]:
    result = _route_lookup(corridor, origin, corridor, destination)
    if "error" in result or result.get("status") == "one_way_mismatch":
        raise ValueError(
            f"route step no longer resolves: {origin!r} to {destination!r}"
        )
    if corridor in _DULLES_CORRIDORS:
        steps: list[TollStep] = []
        for facility, pair in result["legs"]:
            steps.append(
                TollStep(
                    route_step_id="pending",
                    facility=facility,
                    direction=pair["direction"],
                    entry_node_id=cast(str, pair["entry"]),
                    exit_node_id=cast(str, pair["exit"]),
                )
            )
        return steps
    return [
        TollStep(
            route_step_id="pending",
            facility=cast(Any, corridor),
            direction=result["direction"],
            entry_node_id=result["entry"]["node_id"],
            exit_node_id=result["exit"]["node_id"],
        )
    ]


def _materialize(
    raw_steps: list[JsonObject],
    direction: I95DirectionResult | None,
    access: I95AccessResult | None,
) -> list[TollStep | ConnectorStep | UnpricedStep]:
    result: list[TollStep | ConnectorStep | UnpricedStep] = []
    for raw in raw_steps:
        if raw["kind"] == "toll":
            result.extend(
                _toll_steps(raw["corridor"], raw["origin"], raw["destination"])
            )
        elif raw["kind"] == "connector":
            transfer_id = cast(str, raw["transfer_id"])
            if (
                transfer_id == "i95_to_dca_northbound"
                and direction
                and direction.open_direction == "Southbound"
            ):
                transfer_id = "i95_to_dca_southbound"
            result.append(
                ConnectorStep(
                    route_step_id="pending",
                    transfer_id=transfer_id,
                    description=cast(str, _TRANSFER_BY_ID[transfer_id]["connector"]),
                )
            )
        elif raw["kind"] == "unpriced":
            result.append(
                UnpricedStep(
                    route_step_id="pending", description=cast(str, raw["reason"])
                )
            )
        else:
            if access and access.status == "supported":
                toll_step = None
                if access.entry_node_id != access.exit_node_id:
                    toll_step = TollStep(
                        route_step_id="pending",
                        facility="i95",
                        direction=cast(Any, access.required_direction),
                        entry_node_id=cast(str, access.entry_node_id),
                        exit_node_id=cast(str, access.exit_node_id),
                    )
                description = "I-95/I-495 junction gap is unpriced"
            else:
                toll_step = None
                description = (
                    "Complete the I-95 portion on the general-purpose lanes; "
                    "that remainder is unpriced"
                )
            gap = UnpricedStep(route_step_id="pending", description=description)
            junction_steps = (
                [gap, toll_step]
                if raw["movement"] == "i495_to_i95"
                else [toll_step, gap]
            )
            result.extend(step for step in junction_steps if step is not None)
    for number, step in enumerate(result, 1):
        step.route_step_id = f"step-{number}"
    return result


def _canonical_endpoint(
    corridor: str,
    query: str,
    role: Literal["origin", "destination"],
    steps: list[TollStep | ConnectorStep | UnpricedStep],
    access: I95AccessResult | None,
) -> CanonicalEndpoint:
    if corridor in AIRPORT_ENDPOINTS:
        label = AIRPORT_ENDPOINTS[corridor]
        return CanonicalEndpoint(
            corridor=cast(Any, corridor), node_id=label, label=label
        )
    candidate_id: str | None = None
    if corridor == "i95" and access:
        candidate_id = access.entry_node_id if role == "origin" else access.exit_node_id
    if candidate_id is None:
        ordered = steps if role == "origin" else list(reversed(steps))
        for step in ordered:
            if isinstance(step, TollStep) and step.facility == corridor:
                candidate_id = (
                    step.entry_node_id if role == "origin" else step.exit_node_id
                )
                break
            if isinstance(step, ConnectorStep):
                transfer = _TRANSFER_BY_ID[step.transfer_id]
                side = transfer["from" if role == "origin" else "to"]
                if side["corridor"] == corridor:
                    candidate_id = side["node_id"]
                    break
    locations = _LOCATION_BY_CORRIDOR[corridor]
    if candidate_id is None:
        location = locations.get(query)
        if location is None:
            raise ValueError(f"unknown {role} {query!r} on {corridor}")
        nodes: Nodes = {
            "i95": _I95_NODES,
            "i495": _I495_NODES,
            "i66_itb": _I66_NODES,
            "dulles_toll_road": cast(Nodes, _DULLES["dulles_toll_road"]["nodes"]),
            "dulles_greenway": cast(Nodes, _DULLES["dulles_greenway"]["nodes"]),
        }[corridor]
        candidates: list[str] = [
            node_id
            for node_id, node in nodes.items()
            if node["label"] == location["label"]
        ]
        if not candidates:
            raise ValueError(f"cannot canonicalize {role} {query!r} on {corridor}")
        candidate_id = (
            query if query in locations and query in candidates else candidates[0]
        )
    label = cast(
        str, locations.get(candidate_id, locations.get(query, {})).get("label", query)
    )
    return CanonicalEndpoint(
        corridor=cast(Any, corridor), node_id=candidate_id, label=label
    )


def _route_problem(
    status: str, reason: str, source: JsonObject | None = None
) -> JsonObject:
    return {
        "status": status,
        "reason": reason,
        "constraints": (source or {}).get("constraints", []),
        "valid_options": (source or {}).get("valid_options", []),
    }


def _uses_i95(
    origin_corridor: str, destination_corridor: str, raw: list[JsonObject]
) -> bool:
    return (
        origin_corridor in {"i95", "airport_dca"}
        or destination_corridor in {"i95", "airport_dca"}
        or any(step["kind"] == "junction" for step in raw)
    )


@tool(inputSchema={"json": RouteRequest.model_json_schema()})
def plan_toll_route(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
    requested_at: str,
    i95_direction_result: dict[str, object] | None = None,
    i95_access_result: dict[str, object] | None = None,
) -> JsonObject:
    """Build the one immutable route plan used by every pricing specialist.

    Use for every trip. I-95 trips require copied direction and access evidence;
    the only exception is a documented partial cross-corridor route when the
    direction tool reports unavailable.
    """
    try:
        request = RouteRequest.model_validate(
            {
                "origin_corridor": origin_corridor,
                "origin": origin,
                "destination_corridor": destination_corridor,
                "destination": destination,
                "requested_at": requested_at,
                "i95_direction_result": i95_direction_result,
                "i95_access_result": i95_access_result,
            }
        )
        normalized_at = _parse_requested_at(request.requested_at).isoformat()
    except (ValidationError, ValueError) as error:
        return _route_problem("invalid_request", f"invalid route request: {error}")
    for corridor, location, role in (
        (origin_corridor, origin, "origin"),
        (destination_corridor, destination, "destination"),
    ):
        candidate = _LOCATION_BY_CORRIDOR[corridor].get(location)
        if candidate is None:
            return _route_problem(
                "unsupported",
                f"unknown {role} {location!r} on {corridor}",
                {"valid_options": sorted(_LOCATION_BY_CORRIDOR[corridor])},
            )
    if (
        origin_corridor == destination_corridor
        and _LOCATION_BY_CORRIDOR[origin_corridor][origin]["label"]
        == _LOCATION_BY_CORRIDOR[destination_corridor][destination]["label"]
    ):
        return _route_problem(
            "invalid_request", "origin and destination resolve to the same endpoint"
        )
    raw = _planned_steps(origin_corridor, origin, destination_corridor, destination)
    if raw is None:
        return _route_problem("unsupported", "no oracle-supported directed route")
    if isinstance(raw, dict):
        return _route_problem(
            "one_way_mismatch",
            "one or more requested ramps cannot serve the route direction",
            raw,
        )

    direction: I95DirectionResult | None = None
    access: I95AccessResult | None = None
    uses_i95 = _uses_i95(origin_corridor, destination_corridor, raw)
    cross_i95 = any(step["kind"] == "junction" for step in raw)
    if uses_i95:
        if i95_direction_result is None:
            return _route_problem(
                "validation_failed", "I-95 direction evidence is required"
            )
        try:
            direction = I95DirectionResult.model_validate(i95_direction_result)
        except ValidationError as error:
            return _route_problem(
                "validation_failed", f"invalid I-95 direction evidence: {error}"
            )
        if not _is_issued_evidence(direction):
            return _route_problem(
                "validation_failed",
                "I-95 direction evidence was not issued by i95_direction",
            )
        if direction.requested_at != normalized_at:
            return _route_problem(
                "validation_failed", "I-95 direction evidence is for another time"
            )
        if direction.status == "supported":
            if i95_access_result is None:
                return _route_problem(
                    "validation_failed", "I-95 access evidence is required"
                )
            try:
                access = I95AccessResult.model_validate(i95_access_result)
            except ValidationError as error:
                return _route_problem(
                    "validation_failed", f"invalid I-95 access evidence: {error}"
                )
            if not _is_issued_evidence(access):
                return _route_problem(
                    "validation_failed",
                    "I-95 access evidence was not issued by i95_access_options",
                )
            expected = I95AccessResult.model_validate(
                i95_access_options(
                    origin_corridor,
                    origin,
                    destination_corridor,
                    destination,
                    direction.model_dump(mode="json"),
                )
            )
            if access.model_dump(
                mode="json", exclude={"validation_id"}
            ) != expected.model_dump(mode="json", exclude={"validation_id"}):
                return _route_problem(
                    "validation_failed",
                    "I-95 access evidence does not match this exact trip",
                )
            if access.status != "supported" and (
                not cross_i95 or access.status != "direction_closed"
            ):
                return _route_problem(
                    "validation_failed",
                    "I-95 access evidence does not admit this exact trip",
                )
            if access.requested_at != normalized_at:
                return _route_problem(
                    "validation_failed", "I-95 access evidence is for another time"
                )
        elif not cross_i95:
            return _route_problem(
                "validation_failed",
                "unavailable I-95 direction cannot admit an I-95-only route",
            )

    steps = _materialize(raw, direction, access)
    try:
        origin_endpoint = _canonical_endpoint(
            origin_corridor, origin, "origin", steps, access
        )
        destination_endpoint = _canonical_endpoint(
            destination_corridor, destination, "destination", steps, access
        )
    except ValueError as error:
        return _route_problem("unsupported", str(error))
    validation = (
        I95Validation(direction=direction, access=access) if direction else None
    )
    connector_labels = {
        step.description for step in steps if isinstance(step, ConnectorStep)
    }
    routing_note = (
        "Route 267 detour; not a direct I-66/I-495 connection"
        if connector_labels >= _ROUTE_267_DETOUR_CONNECTORS
        else None
    )
    content = {
        "status": "ready",
        "requested_at": normalized_at,
        "origin": origin_endpoint.model_dump(mode="json"),
        "destination": destination_endpoint.model_dump(mode="json"),
        "i95_validation": (
            validation.model_dump(mode="json", exclude_none=False)
            if validation
            else None
        ),
        "steps": [step.model_dump(mode="json") for step in steps],
        "routing_note": routing_note,
    }
    plan = RoutePlan.model_validate(
        {"route_plan_id": content_fingerprint("plan", content), **content}
    )
    return _model_json(plan)


AGENT_TOOLS = (i95_direction, i95_access_options, plan_toll_route)


def location_oracle_for_prompt() -> dict[str, list[dict[str, object]]]:
    """Return labels and endpoint roles without exposing raw route pairs."""
    return {
        corridor: [
            {"label": key, "entry": value["entry"], "exit": value["exit"]}
            for key, value in locations.items()
            if key == value["label"]
        ]
        for corridor, locations in _LOCATION_BY_CORRIDOR.items()
    }

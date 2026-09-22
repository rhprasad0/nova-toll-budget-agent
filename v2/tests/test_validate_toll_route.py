import copy
import logging
from collections.abc import Callable, Sequence
from typing import Self, cast

import pytest
from pydantic import ValidationError

from agent_tools import validate_toll_route as route_tool

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None


def _valid_row() -> dict[str, JSON]:
    return {
        "status": "valid",
        "reason": None,
        "point_ids": ["i66:1:entry:EB", "i66:4:exit:EB"],
        "connection_ids": ["source:i66:EB:1:4"],
        "connection_types": ["within_facility"],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }


def _unavailable_row() -> dict[str, JSON]:
    return {
        "status": "currently_unavailable",
        "reason": {
            "code": "i95_fully_closed",
            "details": {
                "required_i95_directions": ["SB"],
                "availability": "closed",
            },
        },
        "point_ids": ["airport_iad", "i495:182SO", "i95:205SD"],
        "connection_ids": ["iad_to_i495_south", "i495_to_i95_south"],
        "connection_types": ["airport_access", "general_purpose_gap"],
        "general_purpose_gaps": [
            {
                "connection_id": "i495_to_i95_south",
                "boundary_point_id": "i495:192SD",
                "role": "suffix",
                "i95_direction": "SB",
                "fallback_required": True,
            }
        ],
        "i95_evidence": {
            "availability": "closed",
            "northbound_corridor_name": "I-95 NB",
            "northbound_link_status": "CLOSED",
            "northbound_interval_end_at": "2026-08-17T12:00:00+00:00",
            "northbound_calculated_at": "2026-08-17T11:59:00+00:00",
            "southbound_corridor_name": "I-95 SB",
            "southbound_link_status": "CLOSED",
            "southbound_interval_end_at": "2026-08-17T12:00:00+00:00",
            "southbound_calculated_at": "2026-08-17T11:59:00+00:00",
        },
    }


def _northbound_suffix_row() -> dict[str, JSON]:
    row = _unavailable_row()
    row.update(
        {
            "status": "valid",
            "reason": None,
            "point_ids": ["i495:182SO", "i95:2239ND", "airport_dca"],
            "connection_ids": [
                "source:i95_shared:Southbound:182SO:2239ND",
                "i95_north_to_dca_from_i495_south",
            ],
            "connection_types": ["general_purpose_gap", "airport_access"],
        }
    )
    cast(dict[str, JSON], cast(list[JSON], row["general_purpose_gaps"])[0]).update(
        {
            "connection_id": "source:i95_shared:Southbound:182SO:2239ND",
            "boundary_point_id": "i495:192SD",
            "i95_direction": "NB",
            "fallback_required": False,
        }
    )
    cast(dict[str, JSON], row["i95_evidence"])["availability"] = "northbound"
    return row


def _southbound_westpark_row(origin_point_id: str = "i95:2233SO") -> dict[str, JSON]:
    connection_id = "source:i95_shared:Southbound:2233SO:1859ND"
    airport = origin_point_id == "airport_dca"
    return {
        "status": "valid",
        "reason": None,
        "point_ids": (
            ["airport_dca", "i95:2233SO", "i495:1859ND"]
            if airport
            else ["i95:2233SO", "i495:1859ND"]
        ),
        "connection_ids": (
            ["dca_to_i95_south", connection_id] if airport else [connection_id]
        ),
        "connection_types": (
            ["airport_access", "general_purpose_gap"]
            if airport
            else ["general_purpose_gap"]
        ),
        "general_purpose_gaps": [
            {
                "connection_id": connection_id,
                "boundary_point_id": "i495:192SD",
                "role": "prefix",
                "i95_direction": "SB",
                "fallback_required": False,
            }
        ],
        "i95_evidence": {
            **cast(dict[str, JSON], _unavailable_row()["i95_evidence"]),
            "availability": "southbound",
        },
    }


def _i95_northbound_restart_row() -> dict[str, JSON]:
    return {
        "status": "invalid_origin",
        "reason": {
            "code": "i95_northbound_requires_i495_restart",
            "details": {
                "point_id": "i95:206NO",
                "point_type": "entry",
                "suggested_restart_point_id": "i495:192NO",
                "suggested_destination_point_id": "i495:185ND",
            },
        },
        "point_ids": [],
        "connection_ids": [],
        "connection_types": [],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }


def _pricing_route_row() -> dict[str, JSON]:
    route: dict[str, JSON] = {
        "status": "valid",
        "reason": None,
        "point_ids": ["point-1", "point-2", "point-3", "point-4", "point-5"],
        "connection_ids": [
            "connection-1",
            "connection-2",
            "connection-3",
            "connection-4",
        ],
        "connection_types": cast(list[JSON], ["within_facility"] * 4),
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }
    return {
        **route,
        "facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "i66",
                "point_ids": ["point-1", "point-2"],
                "connection_ids": ["connection-1"],
                "pricing_key": {
                    "source_route_key": "EB:1:2",
                    "start_zone_id": 1,
                    "end_zone_id": 2,
                },
            },
            {
                "route_step_id": "step-2",
                "facility": "i95_i495",
                "point_ids": ["point-2", "i495:192NO"],
                "connection_ids": ["connection-2"],
                "pricing_key": {
                    "source_route_key": "Northbound:2:3",
                    "od_pair_id": 1144,
                },
            },
            {
                "route_step_id": "step-3",
                "facility": "i95_i495",
                "point_ids": ["i495:192NO", "point-3"],
                "connection_ids": ["connection-2"],
                "pricing_key": {
                    "source_route_key": "Northbound:2:3",
                    "od_pair_id": 1092,
                },
            },
            {
                "route_step_id": "step-4",
                "facility": "dtr",
                "point_ids": ["point-3", "point-4"],
                "connection_ids": ["connection-3"],
                "pricing_key": {
                    "source_route_key": "EB:3:4",
                    "charge_index": 1,
                },
            },
            {
                "route_step_id": "step-5",
                "facility": "greenway",
                "point_ids": ["point-4", "point-5"],
                "connection_ids": ["connection-4"],
                "pricing_key": {
                    "source_route_key": "EB:4:5",
                    "charge_index": 2,
                },
            },
        ],
    }


def _endpoints(row: dict[str, JSON]) -> tuple[str, str]:
    points = cast(list[str], row["point_ids"])
    return points[0], points[-1]


def _availability_transition_row(status: str) -> dict[str, JSON]:
    row = copy.deepcopy(_northbound_suffix_row())
    evidence = copy.deepcopy(_unavailable_row()["i95_evidence"])
    if status == "currently_unavailable":
        reason_code = "i95_fully_closed"
        availability = "closed"
        fallback_required = True
    else:
        reason_code = "i95_stale_evidence"
        availability = "unknown"
        fallback_required = None
    cast(dict[str, JSON], evidence)["availability"] = availability
    row.update(
        {
            "status": status,
            "reason": {
                "code": reason_code,
                "details": {
                    "required_i95_directions": ["NB"],
                    "availability": availability,
                },
            },
            "i95_evidence": evidence,
            "facility_legs": [],
        }
    )
    cast(dict[str, JSON], cast(list[JSON], row["general_purpose_gaps"])[0])[
        "fallback_required"
    ] = fallback_required
    return row


def _dtr_charge_row(charge_indexes: Sequence[int]) -> dict[str, JSON]:
    row = _pricing_route_row()
    first = cast(list[JSON], row["facility_legs"])[3]
    cast(dict[str, JSON], cast(dict[str, JSON], first)["pricing_key"])[
        "charge_index"
    ] = charge_indexes[0]
    second = copy.deepcopy(first)
    cast(dict[str, JSON], second)["route_step_id"] = "step-5"
    cast(dict[str, JSON], cast(dict[str, JSON], second)["pricing_key"])[
        "charge_index"
    ] = charge_indexes[1]
    cast(list[JSON], row["facility_legs"]).insert(4, second)
    cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[5])[
        "route_step_id"
    ] = "step-6"
    return row


class _Cursor:
    def __init__(
        self, rows: list[dict[str, JSON]], error: Exception | None = None
    ) -> None:
        self.rows = rows
        self.error = error
        self.calls: list[tuple[str, tuple[str, str]]] = []

    def __enter__(self) -> "Self":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[str, str]) -> None:
        self.calls.append((sql, params))
        if self.error:
            raise self.error

    def fetchall(self) -> list[dict[str, JSON]]:
        return self.rows


class _Connection:
    def __init__(
        self,
        rows: list[dict[str, JSON]],
        *,
        query_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.cursor_instance = _Cursor(rows, query_error)
        self.close_error = close_error
        self.closed = False

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise self.close_error


def _validate_response(row: dict[str, JSON]) -> route_tool._RouteResponse:
    origin_point_id = (
        cast(list[JSON], row["point_ids"])[0] if row["point_ids"] else "origin"
    )
    destination_point_id = (
        cast(list[str], row["point_ids"])[-1] if row["point_ids"] else "destination"
    )
    if row["reason"] and "origin_point_id" in cast(
        dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]
    ):
        origin_point_id = cast(
            dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]
        )["origin_point_id"]
        destination_point_id = cast(
            dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]
        )["destination_point_id"]
    elif row["reason"] and "point_id" in cast(
        dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]
    ):
        if row["status"] == "invalid_origin":
            origin_point_id = cast(
                dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]
            )["point_id"]
            if (
                cast(dict[str, JSON], row["reason"])["code"]
                == "i95_northbound_requires_i495_restart"
            ):
                destination_point_id = "i495:1859ND"
        else:
            destination_point_id = cast(
                dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]
            )["point_id"]
    request = route_tool._RouteInput.model_validate(
        {
            "origin_point_id": origin_point_id,
            "destination_point_id": destination_point_id,
        }
    )
    return route_tool._RouteResponse.model_validate(row, context={"request": request})


@pytest.mark.parametrize(
    "input_data",
    [
        {"origin_point_id": "origin"},
        {"origin_point_id": 1, "destination_point_id": "destination"},
        {
            "origin_point_id": "origin",
            "destination_point_id": "destination",
            "api_key": "TOP-SECRET",
        },
    ],
)
def test_route_input_rejects_missing_mistyped_and_extra_fields(
    input_data: object,
) -> None:
    with pytest.raises(ValidationError) as error:
        route_tool._RouteInput.model_validate(input_data)
    assert "TOP-SECRET" not in str(error.value)


@pytest.mark.parametrize(
    "row",
    [
        _valid_row(),
        {
            "status": "invalid_origin",
            "reason": {
                "code": "origin_not_found",
                "details": {"point_id": "missing-origin"},
            },
            "point_ids": [],
            "connection_ids": [],
            "connection_types": [],
            "general_purpose_gaps": [],
            "i95_evidence": None,
        },
        _unavailable_row(),
        _northbound_suffix_row(),
        _i95_northbound_restart_row(),
        {
            "status": "no_supported_route",
            "reason": {
                "code": "no_supported_route",
                "details": {
                    "origin_point_id": "origin",
                    "destination_point_id": "destination",
                },
            },
            "point_ids": [],
            "connection_ids": [],
            "connection_types": [],
            "general_purpose_gaps": [],
            "i95_evidence": None,
        },
        {
            "status": "invalid_destination",
            "reason": {
                "code": "destination_not_exit",
                "details": {
                    "point_id": "i66:4:entry:EB",
                    "point_type": "entry",
                    "allowed_point_types": ["exit", "airport"],
                    "alternatives": [
                        {
                            "point_id": "i66:4:exit:EB",
                            "network_id": "i66",
                            "source_node_id": "4",
                            "point_type": "exit",
                            "direction": "EB",
                            "label": "Exit 4",
                            "aliases": ["Exit Four"],
                            "location": {
                                "type": "Point",
                                "coordinates": [-77.1, 38.9],
                            },
                        }
                    ],
                },
            },
            "point_ids": [],
            "connection_ids": [],
            "connection_types": [],
            "general_purpose_gaps": [],
            "i95_evidence": None,
        },
    ],
)
def test_documented_domain_rows_are_valid(row: dict[str, JSON]) -> None:
    assert _validate_response(row).model_dump(mode="json") == row


@pytest.mark.parametrize("origin_point_id", ["airport_dca", "i95:2233SO"])
def test_southbound_prefix_route_to_westpark_is_valid(origin_point_id: str) -> None:
    row = _southbound_westpark_row(origin_point_id)
    assert _validate_response(row).model_dump(mode="json") == row


def test_route_rejects_unknown_gap_boundary() -> None:
    row = _southbound_westpark_row()
    cast(dict[str, JSON], cast(list[JSON], row["general_purpose_gaps"])[0])[
        "boundary_point_id"
    ] = "i495:999SD"
    with pytest.raises(ValidationError):
        _validate_response(row)


def test_iam_tls_connection_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    class RDS:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_db_auth_token(self, **kwargs: object) -> str:
            self.calls.append(kwargs)
            return "temporary-token"

    rds = RDS()
    connect_calls: list[dict[str, object]] = []
    sentinel = object()
    import psycopg
    from psycopg.rows import dict_row

    def _strict_callback_1(service: str) -> object:
        return rds

    monkeypatch.setattr(route_tool.boto3, "client", _strict_callback_1)

    def _strict_callback_2(**kwargs: object) -> object:
        return connect_calls.append(kwargs) or sentinel

    monkeypatch.setattr(
        psycopg,
        "connect",
        _strict_callback_2,
    )
    monkeypatch.setenv("DB_HOST", "db.example.test")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "tollchat")
    monkeypatch.setenv("DB_CA_BUNDLE_PATH", "/certs/rds-ca.pem")
    monkeypatch.setenv("DB_USER", "tollchat_agent_development")
    monkeypatch.setenv("PRICING_DB_USER", "pricing_caller_development")

    assert route_tool.connect_to_database() is sentinel
    assert route_tool.connect_to_pricing_database() is sentinel
    assert rds.calls == [
        {
            "DBHostname": "db.example.test",
            "Port": 5432,
            "DBUsername": "tollchat_agent_development",
        },
        {
            "DBHostname": "db.example.test",
            "Port": 5432,
            "DBUsername": "pricing_caller_development",
        },
    ]
    assert connect_calls == [
        {
            "host": "db.example.test",
            "port": 5432,
            "dbname": "tollchat",
            "user": "tollchat_agent_development",
            "password": "temporary-token",
            "sslmode": "verify-full",
            "sslrootcert": "/certs/rds-ca.pem",
            "row_factory": dict_row,
        },
        {
            "host": "db.example.test",
            "port": 5432,
            "dbname": "tollchat",
            "user": "pricing_caller_development",
            "password": "temporary-token",
            "sslmode": "verify-full",
            "sslrootcert": "/certs/rds-ca.pem",
            "row_factory": dict_row,
        },
    ]

    monkeypatch.delenv("PRICING_DB_USER")

    assert route_tool.connect_to_pricing_database() is sentinel
    assert rds.calls[-1]["DBUsername"] == "pricing_caller"


@pytest.mark.parametrize(
    "row",
    [
        {**_valid_row(), "point_ids": []},
        {**_valid_row(), "secret_extra_column": "rejected"},
    ],
)
def test_route_response_rejects_malformed_rows(row: dict[str, JSON]) -> None:
    with pytest.raises(ValidationError):
        _validate_response(row)


def _callback_1(row: dict[str, JSON]) -> object:
    return cast(
        dict[str, JSON], cast(list[JSON], row["general_purpose_gaps"])[0]
    ).update({"connection_id": "wrong-connection"})


def _callback_2(row: dict[str, JSON]) -> object:
    return cast(
        dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]
    ).update({"availability": "unknown"})


def _strict_callback_3(row: dict[str, JSON]) -> object:
    return row.update({"i95_evidence": None})


@pytest.mark.parametrize(
    "mutation",
    [
        _callback_1,
        _strict_callback_3,
        _callback_2,
    ],
)
def test_cross_field_contract_violations_fail_safely(
    mutation: Callable[[dict[str, JSON]], object],
) -> None:
    row = copy.deepcopy(_unavailable_row())
    mutation(row)
    with pytest.raises(ValidationError):
        _validate_response(row)


def test_path_must_match_requested_endpoints() -> None:
    request = route_tool._RouteInput(
        origin_point_id="different-origin", destination_point_id="i66:4:exit:EB"
    )
    with pytest.raises(ValidationError, match="requested origin"):
        route_tool._RouteResponse.model_validate(
            _valid_row(), context={"request": request}
        )


def test_cyclic_path_fails_safely() -> None:
    row = _valid_row()
    row.update(
        {
            "point_ids": [
                "i66:1:entry:EB",
                "i66:2:exit:EB",
                "i66:1:entry:EB",
                "i66:4:exit:EB",
            ],
            "connection_ids": ["connection-1", "connection-2", "connection-3"],
            "connection_types": cast(list[JSON], ["within_facility"] * 3),
        }
    )
    with pytest.raises(ValidationError):
        _validate_response(row)


@pytest.mark.parametrize(
    "row",
    [
        {
            **_valid_row(),
            "point_ids": ["i95:202NO", "i95:201ND"],
            "connection_ids": ["source:i95:Northbound:202NO:201ND"],
        },
        {
            **_valid_row(),
            "i95_evidence": {
                **cast(dict[str, JSON], _unavailable_row()["i95_evidence"]),
                "availability": "northbound",
            },
        },
        {
            **_unavailable_row(),
            "reason": {
                "code": "i95_opposite_direction_open",
                "details": {
                    "required_i95_directions": ["NB"],
                    "availability": "northbound",
                },
            },
            "i95_evidence": {
                **cast(dict[str, JSON], _unavailable_row()["i95_evidence"]),
                "availability": "northbound",
            },
        },
    ],
)
def test_contradictory_i95_evidence_fails_safely(row: dict[str, JSON]) -> None:
    with pytest.raises(ValidationError):
        _validate_response(row)


@pytest.mark.parametrize("alternatives", [[], None])
def test_incompatible_ramp_alternatives_follow_contract(
    alternatives: list[JSON] | None,
) -> None:
    returned_alternatives: list[JSON] = (
        []
        if alternatives == []
        else [
            {
                "point_id": "i95:202NO",
                "network_id": "i95",
                "source_node_id": "202NO",
                "point_type": "entry",
                "direction": "NB",
                "label": "Wrong facility",
                "aliases": [],
                "location": None,
            }
        ]
    )
    row: dict[str, JSON] = {
        "status": "invalid_origin",
        "reason": {
            "code": "origin_ramp_incompatible",
            "details": {
                "point_id": "i66:4:entry:EB",
                "point_type": "entry",
                "alternatives": returned_alternatives,
            },
        },
        "point_ids": [],
        "connection_ids": [],
        "connection_types": [],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }
    with pytest.raises(ValidationError):
        _validate_response(row)


def _callback_9(details: dict[str, JSON]) -> object:
    return details.update({"suggested_restart_point_id": "i495:192SD"})


def _callback_10(details: dict[str, JSON]) -> object:
    return details.update({"suggested_destination_point_id": "i95:201ND"})


def _callback_11(details: dict[str, JSON]) -> object:
    return details.update({"suggested_destination_point_id": "i495:186ND"})


def _strict_callback_5(details: dict[str, JSON]) -> object:
    return details.update({"alternatives": []})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            _strict_callback_5,
            "Extra inputs are not permitted",
        ),
        (
            _callback_9,
            "Input should be 'i495:192NO'",
        ),
        (
            _callback_10,
            "String should match pattern",
        ),
        (
            _callback_11,
            "restart destination does not match the request",
        ),
    ],
)
def test_i95_northbound_restart_rejects_malformed_details(
    mutation: Callable[[dict[str, JSON]], object],
    message: str,
) -> None:
    row = _i95_northbound_restart_row()
    mutation(cast(dict[str, JSON], cast(dict[str, JSON], row["reason"])["details"]))
    with pytest.raises(ValidationError, match=message):
        _validate_response(row)


def test_pricing_route_returns_typed_facility_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _pricing_route_row()
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert [leg.model_dump(mode="json") for leg in response.facility_legs] == row[
        "facility_legs"
    ]
    assert connection.cursor_instance.calls == [
        (
            "SELECT * FROM oracle.validate_pricing_route(%s, %s)",
            _endpoints(row),
        )
    ]
    assert connection.closed


def test_pricing_route_accepts_cross_direction_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row: dict[str, JSON] = {**_northbound_suffix_row(), "facility_legs": []}
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert response.general_purpose_gaps[0].boundary_point_id == "i495:192SD"
    assert response.general_purpose_gaps[0].i95_direction == "NB"
    assert connection.closed


def test_pricing_route_allows_greenway_dtr_handoff_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row: dict[str, JSON] = {
        "status": "valid",
        "reason": None,
        "point_ids": ["greenway:28:exit:EB", "dtr:28:entry:EB"],
        "connection_ids": ["greenway_to_dtr"],
        "connection_types": ["toll_handoff"],
        "general_purpose_gaps": [],
        "i95_evidence": None,
        "facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "dtr",
                "point_ids": ["greenway:28:exit:EB", "dtr:28:entry:EB"],
                "connection_ids": ["greenway_to_dtr"],
                "pricing_key": {
                    "source_route_key": "greenway_to_dtr",
                    "charge_index": 1,
                },
            }
        ],
    }
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert response.facility_legs[0].facility == "dtr"
    assert connection.closed


def test_pricing_route_rejects_other_priced_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row: dict[str, JSON] = {
        **_valid_row(),
        "point_ids": ["i66:5:exit:WB", "i495:187SO"],
        "connection_ids": ["i66_to_i495"],
        "connection_types": ["toll_handoff"],
        "facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "dtr",
                "point_ids": ["i66:5:exit:WB", "i495:187SO"],
                "connection_ids": ["i66_to_i495"],
                "pricing_key": {
                    "source_route_key": "i66_to_i495",
                    "charge_index": 1,
                },
            }
        ],
    }
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with pytest.raises(ValueError, match="unexpected priced toll handoff"):
        route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert connection.closed


def test_pricing_route_allows_valid_route_without_tolls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row: dict[str, JSON] = {**_valid_row(), "facility_legs": []}
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(*_endpoints(row))
    assert response.status == "valid"
    assert response.facility_legs == []
    assert connection.closed


@pytest.mark.parametrize("status", ["currently_unavailable", "unknown_availability"])
def test_pricing_route_returns_typed_availability_transition(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    row = _availability_transition_row(status)
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert response.status == status
    assert response.facility_legs == []
    assert response.point_ids == row["point_ids"]
    assert response.connection_ids == row["connection_ids"]
    assert connection.closed


def test_pricing_route_rejects_valid_status_with_required_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = copy.deepcopy(_northbound_suffix_row())
    cast(dict[str, JSON], row["i95_evidence"])["availability"] = "southbound"
    cast(dict[str, JSON], cast(list[JSON], row["general_purpose_gaps"])[0])[
        "fallback_required"
    ] = True
    row["facility_legs"] = []
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with pytest.raises(ValueError, match="valid routes cannot require a fallback"):
        route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert connection.closed


def test_pricing_route_rejects_legs_on_availability_transition(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    row = _availability_transition_row("currently_unavailable")
    row["facility_legs"] = cast(list[JSON], _pricing_route_row()["facility_legs"])[:1]
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError):
        route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].__dict__["failureStage"] == "response_validation"


def _callback_3(row: dict[str, JSON]) -> object:
    return cast(
        dict[str, JSON],
        cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[0])["pricing_key"],
    ).update({"od_pair_id": 1144})


def _callback_4(row: dict[str, JSON]) -> object:
    return cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[1]).update(
        {"route_step_id": "step-7"}
    )


def _callback_5(row: dict[str, JSON]) -> object:
    return cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[1]).update(
        {"connection_ids": ["unknown-connection"]}
    )


def _callback_6(row: dict[str, JSON]) -> object:
    return cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[0]).update(
        {"point_ids": ["wrong-point", "point-2"]}
    )


def _callback_7(row: dict[str, JSON]) -> object:
    return cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[0]).update(
        {"connection_ids": ["connection-4"]}
    )


def _callback_8(row: dict[str, JSON]) -> object:
    return row.update(
        {"point_ids": ["different-point", "point-2", "point-3", "point-4", "point-5"]}
    )


def _strict_callback_4(row: dict[str, JSON]) -> object:
    return cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[0]).update(
        {"unexpected": "secret-row"}
    )


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_4,
        _callback_3,
        _callback_4,
        _callback_5,
        _callback_6,
        _callback_7,
        _callback_8,
    ],
)
def test_pricing_route_contract_violations_are_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mutation: Callable[[dict[str, JSON]], object],
) -> None:
    original = _pricing_route_row()
    row = copy.deepcopy(original)
    mutation(row)
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError):
        route_tool.fetch_validated_pricing_route(*_endpoints(original))

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].__dict__["failureStage"] == "response_validation"
    assert caplog.records[0].__dict__["exceptionType"] in {
        "ValidationError",
        "ValueError",
    }
    assert "secret-row" not in caplog.text
    assert "different-point" not in caplog.text


@pytest.mark.parametrize("charge_indexes", [(2, 1), (1, 1)])
def test_pricing_route_rejects_noncanonical_charge_order(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    charge_indexes: Sequence[int],
) -> None:
    row = _dtr_charge_row(charge_indexes)
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ValueError, match="charge indexes are not ordered"),
    ):
        route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].__dict__["failureStage"] == "response_validation"


def test_pricing_route_allows_omitted_zero_price_charge_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _dtr_charge_row((1, 3))
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert [
        leg.pricing_key.charge_index
        for leg in response.facility_legs
        if leg.connection_ids == ["connection-3"]
        and isinstance(leg.pricing_key, route_tool._ChargePricingKey)
    ] == [1, 3]


def test_pricing_route_rejects_mixed_source_keys_on_one_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _dtr_charge_row((1, 2))
    cast(
        dict[str, JSON],
        cast(dict[str, JSON], cast(list[JSON], row["facility_legs"])[4])["pricing_key"],
    )["source_route_key"] = "wrong-route"
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with pytest.raises(ValueError, match="mixes source route keys"):
        route_tool.fetch_validated_pricing_route(*_endpoints(row))

    assert connection.closed


@pytest.mark.parametrize("rows", [[], [_pricing_route_row(), _pricing_route_row()]])
def test_pricing_route_requires_exactly_one_row(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    rows: list[dict[str, JSON]],
) -> None:
    route = _pricing_route_row()
    connection = _Connection(rows)
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ValueError, match="must return exactly one row"),
    ):
        route_tool.fetch_validated_pricing_route(*_endpoints(route))

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].__dict__["failureStage"] == "response_validation"


def test_pricing_route_connection_failure_is_safely_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "password=do-not-log"

    def fail_connection() -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(route_tool, "connect_to_pricing_database", fail_connection)

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match="password=do-not-log"),
    ):
        route_tool.fetch_validated_pricing_route(*_endpoints(_pricing_route_row()))

    assert len(caplog.records) == 1
    assert caplog.records[0].__dict__["failureStage"] == "connection"
    assert caplog.records[0].__dict__["exceptionType"] == "RuntimeError"
    assert "password=do-not-log" not in caplog.text


@pytest.mark.parametrize(
    ("query_error", "close_error", "expected_stage"),
    [
        (RuntimeError("query-secret"), None, "query"),
        (None, RuntimeError("close-secret"), "connection_close"),
        (RuntimeError("query-secret"), RuntimeError("close-secret"), "query"),
    ],
)
def test_pricing_route_database_failures_are_safely_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    query_error: Exception | None,
    close_error: Exception | None,
    expected_stage: str,
) -> None:
    connection = _Connection(
        [_pricing_route_row()], query_error=query_error, close_error=close_error
    )
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        route_tool.fetch_validated_pricing_route(*_endpoints(_pricing_route_row()))

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].__dict__["failureStage"] == expected_stage
    assert caplog.records[0].__dict__["exceptionType"] == "RuntimeError"
    assert "query-secret" not in caplog.text
    assert "close-secret" not in caplog.text
    if query_error is not None and close_error is not None:
        assert "Connection close also failed: RuntimeError" in caplog.text

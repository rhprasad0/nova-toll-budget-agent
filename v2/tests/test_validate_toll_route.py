# pyright: basic

import copy
import logging
from typing import Any, cast

import pytest
from strands.types.tools import ToolUse

from agent_tools import validate_toll_route as route_tool


def _tool_use(input_data: Any, tool_use_id: str = "tool-123") -> ToolUse:
    return cast(
        ToolUse,
        {
            "name": "validate_toll_route",
            "toolUseId": tool_use_id,
            "input": input_data,
        },
    )


def _valid_row():
    return {
        "status": "valid",
        "reason": None,
        "point_ids": ["i66:1:entry:EB", "i66:4:exit:EB"],
        "connection_ids": ["source:i66:EB:1:4"],
        "connection_types": ["within_facility"],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }


def _unavailable_row():
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


def _northbound_suffix_row():
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
    row["general_purpose_gaps"][0].update(
        {
            "connection_id": "source:i95_shared:Southbound:182SO:2239ND",
            "i95_direction": "NB",
            "fallback_required": False,
        }
    )
    row["i95_evidence"]["availability"] = "northbound"
    return row


def _pricing_route_row():
    route = {
        "status": "valid",
        "reason": None,
        "point_ids": ["point-1", "point-2", "point-3", "point-4", "point-5"],
        "connection_ids": [
            "connection-1",
            "connection-2",
            "connection-3",
            "connection-4",
        ],
        "connection_types": ["within_facility"] * 4,
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


def _endpoints(row):
    return row["point_ids"][0], row["point_ids"][-1]


def _availability_transition_row(status):
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
    evidence["availability"] = availability
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
    row["general_purpose_gaps"][0]["fallback_required"] = fallback_required
    return row


def _dtr_charge_row(charge_indexes):
    row = _pricing_route_row()
    first = row["facility_legs"][3]
    first["pricing_key"]["charge_index"] = charge_indexes[0]
    second = copy.deepcopy(first)
    second["route_step_id"] = "step-5"
    second["pricing_key"]["charge_index"] = charge_indexes[1]
    row["facility_legs"].insert(4, second)
    row["facility_legs"][5]["route_step_id"] = "step-6"
    return row


class _Cursor:
    def __init__(self, rows, error=None):
        self.rows = rows
        self.error = error
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if self.error:
            raise self.error

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows, *, query_error=None, close_error=None):
        self.cursor_instance = _Cursor(rows, query_error)
        self.close_error = close_error
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def _invoke(monkeypatch, row):
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_database", lambda: connection)
    origin_point_id = row["point_ids"][0] if row["point_ids"] else "origin"
    destination_point_id = row["point_ids"][-1] if row["point_ids"] else "destination"
    if row["reason"] and "origin_point_id" in row["reason"]["details"]:
        origin_point_id = row["reason"]["details"]["origin_point_id"]
        destination_point_id = row["reason"]["details"]["destination_point_id"]
    elif row["reason"] and "point_id" in row["reason"]["details"]:
        if row["status"] == "invalid_origin":
            origin_point_id = row["reason"]["details"]["point_id"]
        else:
            destination_point_id = row["reason"]["details"]["point_id"]
    result = route_tool.validate_toll_route(
        _tool_use(
            {
                "origin_point_id": origin_point_id,
                "destination_point_id": destination_point_id,
            }
        )
    )
    return result, connection


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
def test_invalid_input_is_logged_and_never_connects(monkeypatch, caplog, input_data):
    monkeypatch.setattr(
        route_tool,
        "connect_to_database",
        lambda: pytest.fail("invalid input opened a database connection"),
    )
    with caplog.at_level(logging.ERROR):
        result = route_tool.validate_toll_route(_tool_use(input_data))

    assert result == {
        "toolUseId": "tool-123",
        "status": "error",
        "content": [
            {"text": "Unable to validate the toll route. Reference: tool-123."}
        ],
    }
    assert len(caplog.records) == 1
    assert caplog.records[0].toolUseId == "tool-123"
    assert caplog.records[0].failureStage == "input_validation"
    assert "TOP-SECRET" not in caplog.text


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
def test_documented_domain_rows_are_successful(monkeypatch, row):
    result, connection = _invoke(monkeypatch, row)
    assert result == {
        "toolUseId": "tool-123",
        "status": "success",
        "content": [{"json": row}],
    }
    assert connection.closed


def test_query_uses_bound_parameters_and_closes(monkeypatch):
    result, connection = _invoke(monkeypatch, _valid_row())
    assert result["status"] == "success"
    assert connection.cursor_instance.calls == [
        (
            "SELECT * FROM oracle.validate_toll_route(%s, %s)",
            ("i66:1:entry:EB", "i66:4:exit:EB"),
        )
    ]
    assert connection.closed


def test_iam_tls_connection_contract(monkeypatch):
    class RDS:
        def __init__(self):
            self.calls = []

        def generate_db_auth_token(self, **kwargs):
            self.calls.append(kwargs)
            return "temporary-token"

    rds = RDS()
    connect_calls = []
    sentinel = object()
    import psycopg
    from psycopg.rows import dict_row

    monkeypatch.setattr(route_tool.boto3, "client", lambda service: rds)
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda **kwargs: connect_calls.append(kwargs) or sentinel,
    )
    monkeypatch.setenv("DB_HOST", "db.example.test")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "tollchat")
    monkeypatch.setenv("DB_CA_BUNDLE_PATH", "/certs/rds-ca.pem")

    assert route_tool.connect_to_database() is sentinel
    assert route_tool.connect_to_pricing_database() is sentinel
    assert rds.calls == [
        {
            "DBHostname": "db.example.test",
            "Port": 5432,
            "DBUsername": "tollchat_agent",
        },
        {
            "DBHostname": "db.example.test",
            "Port": 5432,
            "DBUsername": "pricing_caller",
        },
    ]
    assert connect_calls == [
        {
            "host": "db.example.test",
            "port": 5432,
            "dbname": "tollchat",
            "user": "tollchat_agent",
            "password": "temporary-token",
            "sslmode": "verify-full",
            "sslrootcert": "/certs/rds-ca.pem",
            "row_factory": dict_row,
        },
        {
            "host": "db.example.test",
            "port": 5432,
            "dbname": "tollchat",
            "user": "pricing_caller",
            "password": "temporary-token",
            "sslmode": "verify-full",
            "sslrootcert": "/certs/rds-ca.pem",
            "row_factory": dict_row,
        },
    ]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_valid_row(), _valid_row()],
        [{**_valid_row(), "point_ids": []}],
        [{**_valid_row(), "secret_extra_column": "rejected"}],
    ],
)
def test_bad_database_rows_are_sanitized_logged_and_closed(monkeypatch, caplog, rows):
    connection = _Connection(rows)
    monkeypatch.setattr(route_tool, "connect_to_database", lambda: connection)
    with caplog.at_level(logging.ERROR):
        result = route_tool.validate_toll_route(
            _tool_use(
                {
                    "origin_point_id": "origin",
                    "destination_point_id": "destination",
                }
            )
        )

    assert result["status"] == "error"
    assert result["content"] == [
        {"text": "Unable to validate the toll route. Reference: tool-123."}
    ]
    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == "response_validation"


def test_connection_error_is_sanitized_and_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        route_tool,
        "connect_to_database",
        lambda: (_ for _ in ()).throw(RuntimeError("password=do-not-return")),
    )
    with caplog.at_level(logging.ERROR):
        result = route_tool.validate_toll_route(
            _tool_use(
                {
                    "origin_point_id": "origin",
                    "destination_point_id": "destination",
                }
            )
        )

    assert result["status"] == "error"
    assert "password" not in result["content"][0].get("text", "")
    assert caplog.records[0].failureStage == "connection"
    assert caplog.records[0].exceptionType == "RuntimeError"


@pytest.mark.parametrize(
    ("query_error", "close_error", "expected_stage"),
    [
        (RuntimeError("SELECT secret"), None, "query"),
        (None, RuntimeError("close secret"), "connection_close"),
        (RuntimeError("query secret"), RuntimeError("close secret"), "query"),
    ],
)
def test_database_errors_are_sanitized_logged_and_closed(
    monkeypatch, caplog, query_error, close_error, expected_stage
):
    connection = _Connection(
        [_valid_row()], query_error=query_error, close_error=close_error
    )
    monkeypatch.setattr(route_tool, "connect_to_database", lambda: connection)
    with caplog.at_level(logging.ERROR):
        result = route_tool.validate_toll_route(
            _tool_use(
                {
                    "origin_point_id": "origin",
                    "destination_point_id": "destination",
                }
            )
        )

    assert result["status"] == "error"
    assert result["content"] == [
        {"text": "Unable to validate the toll route. Reference: tool-123."}
    ]
    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == expected_stage


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row["general_purpose_gaps"][0].update(
            {"connection_id": "wrong-connection"}
        ),
        lambda row: row.update({"i95_evidence": None}),
        lambda row: row["reason"]["details"].update({"availability": "unknown"}),
    ],
)
def test_cross_field_contract_violations_fail_safely(monkeypatch, mutation):
    row = copy.deepcopy(_unavailable_row())
    mutation(row)
    result, connection = _invoke(monkeypatch, row)
    assert result["status"] == "error"
    assert connection.closed


def test_path_must_match_requested_endpoints(monkeypatch):
    connection = _Connection([_valid_row()])
    monkeypatch.setattr(route_tool, "connect_to_database", lambda: connection)
    result = route_tool.validate_toll_route(
        _tool_use(
            {
                "origin_point_id": "different-origin",
                "destination_point_id": "i66:4:exit:EB",
            }
        )
    )
    assert result["status"] == "error"
    assert connection.closed


def test_cyclic_path_fails_safely(monkeypatch):
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
            "connection_types": ["within_facility"] * 3,
        }
    )
    result, connection = _invoke(monkeypatch, row)
    assert result["status"] == "error"
    assert connection.closed


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
                **_unavailable_row()["i95_evidence"],
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
                **_unavailable_row()["i95_evidence"],
                "availability": "northbound",
            },
        },
    ],
)
def test_contradictory_i95_evidence_fails_safely(monkeypatch, row):
    result, connection = _invoke(monkeypatch, row)
    assert result["status"] == "error"
    assert connection.closed


@pytest.mark.parametrize("alternatives", [[], None])
def test_incompatible_ramp_alternatives_follow_contract(monkeypatch, alternatives):
    returned_alternatives = (
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
    row = {
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
    result, connection = _invoke(monkeypatch, row)
    assert result["status"] == "error"
    assert connection.closed


def test_pricing_route_returns_typed_facility_legs(monkeypatch):
    row = _pricing_route_row()
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
        *_endpoints(row)
    )

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


def test_pricing_route_allows_greenway_dtr_handoff_charge(monkeypatch):
    row = {
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

    response = route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
        *_endpoints(row)
    )

    assert response.facility_legs[0].facility == "dtr"
    assert connection.closed


def test_pricing_route_rejects_other_priced_handoff(monkeypatch):
    row = {
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
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(row)
        )

    assert connection.closed


def test_pricing_route_allows_valid_route_without_tolls(monkeypatch):
    row = {**_valid_row(), "facility_legs": []}
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
        *_endpoints(row)
    )
    assert response.status == "valid"
    assert response.facility_legs == []
    assert connection.closed


@pytest.mark.parametrize("status", ["currently_unavailable", "unknown_availability"])
def test_pricing_route_returns_typed_availability_transition(monkeypatch, status):
    row = _availability_transition_row(status)
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
        *_endpoints(row)
    )

    assert response.status == status
    assert response.facility_legs == []
    assert response.point_ids == row["point_ids"]
    assert response.connection_ids == row["connection_ids"]
    assert connection.closed


def test_pricing_route_rejects_valid_status_with_required_fallback(monkeypatch):
    row = copy.deepcopy(_northbound_suffix_row())
    row["i95_evidence"]["availability"] = "southbound"
    row["general_purpose_gaps"][0]["fallback_required"] = True
    row["facility_legs"] = []
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with pytest.raises(ValueError, match="valid routes cannot require a fallback"):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(row)
        )

    assert connection.closed


def test_pricing_route_rejects_legs_on_availability_transition(monkeypatch, caplog):
    row = _availability_transition_row("currently_unavailable")
    row["facility_legs"] = _pricing_route_row()["facility_legs"][:1]
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(row)
        )

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == "response_validation"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row["facility_legs"][0].update({"unexpected": "secret-row"}),
        lambda row: row["facility_legs"][0]["pricing_key"].update({"od_pair_id": 1144}),
        lambda row: row["facility_legs"][1].update({"route_step_id": "step-7"}),
        lambda row: row["facility_legs"][1].update(
            {"connection_ids": ["unknown-connection"]}
        ),
        lambda row: row["facility_legs"][0].update(
            {"point_ids": ["wrong-point", "point-2"]}
        ),
        lambda row: row["facility_legs"][0].update(
            {"connection_ids": ["connection-4"]}
        ),
        lambda row: row.update(
            {
                "point_ids": [
                    "different-point",
                    "point-2",
                    "point-3",
                    "point-4",
                    "point-5",
                ]
            }
        ),
    ],
)
def test_pricing_route_contract_violations_are_logged(monkeypatch, caplog, mutation):
    original = _pricing_route_row()
    row = copy.deepcopy(original)
    mutation(row)
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(original)
        )

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == "response_validation"
    assert caplog.records[0].exceptionType in {"ValidationError", "ValueError"}
    assert "secret-row" not in caplog.text
    assert "different-point" not in caplog.text


@pytest.mark.parametrize("charge_indexes", [(2, 1), (1, 1)])
def test_pricing_route_rejects_noncanonical_charge_order(
    monkeypatch, caplog, charge_indexes
):
    row = _dtr_charge_row(charge_indexes)
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ValueError, match="charge indexes are not ordered"),
    ):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(row)
        )

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == "response_validation"


def test_pricing_route_allows_omitted_zero_price_charge_indexes(monkeypatch):
    row = _dtr_charge_row((1, 3))
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    response = route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
        *_endpoints(row)
    )

    assert [
        leg.pricing_key.charge_index
        for leg in response.facility_legs
        if leg.connection_ids == ["connection-3"]
        and isinstance(leg.pricing_key, route_tool._ChargePricingKey)  # pyright: ignore[reportPrivateUsage]
    ] == [1, 3]


def test_pricing_route_rejects_mixed_source_keys_on_one_connection(monkeypatch):
    row = _dtr_charge_row((1, 2))
    row["facility_legs"][4]["pricing_key"]["source_route_key"] = "wrong-route"
    connection = _Connection([row])
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with pytest.raises(ValueError, match="mixes source route keys"):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(row)
        )

    assert connection.closed


@pytest.mark.parametrize("rows", [[], [_pricing_route_row(), _pricing_route_row()]])
def test_pricing_route_requires_exactly_one_row(monkeypatch, caplog, rows):
    route = _pricing_route_row()
    connection = _Connection(rows)
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ValueError, match="must return exactly one row"),
    ):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(route)
        )

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == "response_validation"


def test_pricing_route_connection_failure_is_safely_logged(monkeypatch, caplog):
    secret = "password=do-not-log"

    def fail_connection():
        raise RuntimeError(secret)

    monkeypatch.setattr(route_tool, "connect_to_pricing_database", fail_connection)

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match="password=do-not-log"),
    ):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(_pricing_route_row())
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == "connection"
    assert caplog.records[0].exceptionType == "RuntimeError"
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
    monkeypatch, caplog, query_error, close_error, expected_stage
):
    connection = _Connection(
        [_pricing_route_row()], query_error=query_error, close_error=close_error
    )
    monkeypatch.setattr(route_tool, "connect_to_pricing_database", lambda: connection)

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        route_tool.fetch_validated_pricing_route(  # pyright: ignore[reportPrivateUsage]
            *_endpoints(_pricing_route_row())
        )

    assert connection.closed
    assert len(caplog.records) == 1
    assert caplog.records[0].failureStage == expected_stage
    assert caplog.records[0].exceptionType == "RuntimeError"
    assert "query-secret" not in caplog.text
    assert "close-secret" not in caplog.text
    if query_error is not None and close_error is not None:
        assert "Connection close also failed: RuntimeError" in caplog.text

# pyright: basic
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from eval.history_capture import (
    CaptureBoundExceeded,
    CaptureError,
    CaptureVerificationError,
    capture_raw_history,
)

ANCHOR = datetime(2026, 9, 5, 16, tzinfo=UTC)
LOWER = ANCHOR - timedelta(days=84)
UPPER = ANCHOR


class _Cursor:
    def __init__(self, i95_rows: list[dict[str, Any]], i66_rows: list[dict[str, Any]]):
        self.i95_rows = i95_rows
        self.i66_rows = i66_rows
        self.executed: list[tuple[str, Any]] = []
        self.closed = False
        self.rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        if sql.lstrip().startswith("SELECT current_user::text"):
            self.rows = [
                {
                    "current_user": "pricing_reader",
                    "transaction_read_only": "on",
                    "transaction_isolation": "repeatable read",
                    "transaction_timestamp": datetime(2026, 9, 5, 15, tzinfo=UTC),
                    "server_version_num": "170005",
                    "i95_select": True,
                    "i66_select": True,
                    "i95_write": False,
                    "i66_write": False,
                }
            ]
        elif sql.lstrip().startswith("SELECT version"):
            self.rows = [{"version": "1.3.0"}]
        elif "trip_pricing_i95" in sql:
            self.rows = self.i95_rows
        elif "trip_pricing_i66" in sql:
            self.rows = self.i66_rows
        else:
            self.rows = []

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, i95_rows: list[dict[str, Any]] | None = None):
        self.cursor_instance = _Cursor(i95_rows or [], [])
        self.rollback_count = 0
        self.closed = False

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.closed = True


def _capture(connection: _Connection, **overrides: Any):
    values = {
        "source_id": "operator-entry-exit",
        "anchor": ANCHOR,
        "lower_bound": LOWER,
        "upper_bound": UPPER,
        "i95_od_pair_ids": [1132, 1151],
        "i66_start_zone_ids": [3100, 3220],
        "i66_end_zone_ids": [3110, 3230],
        "cap": 3,
    }
    values.update(overrides)
    return capture_raw_history(lambda: connection, **cast(Any, values))


def test_capture_uses_bounded_reader_snapshot_and_serializes_after_cleanup():
    connection = _Connection(
        [
            {
                "od_pair_id": 1132,
                "interval_end_at": ANCHOR - timedelta(minutes=1),
                "zone_toll_rate_usd": Decimal("8.20"),
            }
        ]
    )

    capture = _capture(connection)

    assert capture.to_dict()["evidence_type"] == "raw_history_source"
    assert capture.to_dict()["provenance"]["database_role"] == "pricing_reader"
    assert (
        capture.to_dict()["provenance"]["historical_as_of_anchor"] == ANCHOR.isoformat()
    )
    assert capture.to_dict()["captured_at"] == "2026-09-05T15:00:00+00:00"
    assert connection.rollback_count == 1
    assert connection.closed
    assert connection.cursor_instance.closed

    statements = [sql for sql, _params in connection.cursor_instance.executed]
    assert statements[:4] == [
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL statement_timeout = '30s'",
        "SET LOCAL lock_timeout = '2s'",
        "SET LOCAL idle_in_transaction_session_timeout = '30s'",
    ]
    assert all("SELECT *" not in sql for sql in statements)
    i95_sql, i95_params = connection.cursor_instance.executed[-2]
    assert "od_pair_id = ANY(%s)" in i95_sql
    assert i95_params[-1] == 4
    assert i95_params[0] == [1132, 1151]
    i66_sql, i66_params = connection.cursor_instance.executed[-1]
    assert "unnest(%s::integer[], %s::integer[])" in i66_sql
    assert i66_params[:2] == ([3100, 3220], [3110, 3230])
    assert i66_params[-1] == 4


def test_capture_fails_closed_on_over_cap_and_still_rolls_back():
    connection = _Connection(
        [{"od_pair_id": 1}, {"od_pair_id": 2}, {"od_pair_id": 3}, {"od_pair_id": 4}]
    )

    with pytest.raises(CaptureBoundExceeded):
        _capture(connection)

    assert connection.rollback_count == 1
    assert connection.closed


@pytest.mark.parametrize(
    "overrides",
    [
        {"i66_start_zone_ids": [], "i66_end_zone_ids": []},
        {"i66_start_zone_ids": [1], "i66_end_zone_ids": [1, 2]},
        {"lower_bound": ANCHOR - timedelta(days=85)},
        {"lower_bound": UPPER},
        {"cap": 0},
        {"deadline_seconds": float("nan")},
        {"deadline_seconds": float("inf")},
        {"deadline_seconds": None},
        {"i66_start_zone_ids": [1, 1], "i66_end_zone_ids": [2, 2]},
    ],
)
def test_capture_rejects_unsafe_bounds_before_connecting(overrides: dict[str, Any]):
    called = False

    def factory() -> object:
        nonlocal called
        called = True
        return object()

    values = {
        "source_id": "operator-entry-exit",
        "anchor": ANCHOR,
        "lower_bound": LOWER,
        "upper_bound": UPPER,
        "i95_od_pair_ids": [1132],
        "i66_start_zone_ids": [3100],
        "i66_end_zone_ids": [3110],
        "cap": 3,
    }
    values.update(overrides)
    with pytest.raises(CaptureError):
        capture_raw_history(factory, **cast(Any, values))
    assert not called


def test_capture_rejects_unverified_role_and_read_write_privileges():
    connection = _Connection()
    original_execute = connection.cursor_instance.execute

    def execute(sql: str, params: Any = None) -> None:
        original_execute(sql, params)
        if sql.lstrip().startswith("SELECT current_user::text"):
            connection.cursor_instance.rows[0]["current_user"] = "pricing_caller"

    connection.cursor_instance.execute = execute
    with pytest.raises(CaptureVerificationError, match="pricing_reader"):
        _capture(connection)
    assert connection.rollback_count == 1
    assert connection.closed


def test_canonical_raw_evidence_digest_changes_with_captured_rows():
    first = _capture(_Connection([{"od_pair_id": 1}]))
    second = _capture(_Connection([{"od_pair_id": 2}]))

    assert first.raw_evidence_sha256 != second.raw_evidence_sha256


@pytest.mark.parametrize("field,value", [("i95_select", False), ("i66_write", True)])
def test_capture_rejects_missing_read_or_effective_write(field, value):
    connection = _Connection()
    execute = connection.cursor_instance.execute

    def changed(sql, params=None):
        execute(sql, params)
        if sql.lstrip().startswith("SELECT current_user::text"):
            connection.cursor_instance.rows[0][field] = value

    connection.cursor_instance.execute = changed
    with pytest.raises(CaptureVerificationError):
        _capture(connection)
    assert connection.closed and connection.rollback_count == 1
    assert "TRUNCATE" in connection.cursor_instance.executed[-1][0]


def test_capture_rejects_cross_pair_rows():
    connection = _Connection()
    connection.cursor_instance.i66_rows = [{"start_zone_id": 3100, "end_zone_id": 3230}]
    with pytest.raises(CaptureVerificationError, match="unrequested selector pair"):
        _capture(connection)
    assert connection.closed


@pytest.fixture(scope="module")
def matrix_inventory():
    from oracle.build_oracle_data import build_connections, build_points

    points = build_points()
    return {"points": points, "connections": build_connections(points)}


@pytest.fixture(scope="module")
def matrix_report(matrix_inventory):
    from eval.directional_matrix import build_matrix

    return build_matrix(matrix_inventory)


def test_matrix_keeps_planning_separate_from_execution(matrix_inventory, matrix_report):
    from eval.directional_matrix import build_matrix

    report = matrix_report
    assert report.inventory_counts["connections"] == 996
    assert report.inventory_counts["connection_types"] == {
        "within_facility": 670,
        "general_purpose_gap": 300,
        "toll_handoff": 14,
        "airport_access": 12,
    }
    assert report.coverage_summary["required"] > 1992
    assert (
        report.coverage_summary["exercised"]
        == report.conformance_summary["passed"]
        == 0
    )
    assert {
        r.movement_id
        for r in report.rows
        if r.physical_expectation.status == "prohibited"
    } == {"i66_to_i495_north", "i495_south_to_i66"}
    reordered = {
        **matrix_inventory,
        "connections": dict(reversed(list(matrix_inventory["connections"].items()))),
    }
    assert build_matrix(reordered).canonical_json_sha256 == report.canonical_json_sha256
    annual = next(r for r in report.rows if r.tool == "annual")
    points = matrix_inventory["points"]
    return_route = annual.request["return"]
    assert points[return_route["origin_point_id"]].point_type == "entry"
    assert points[return_route["destination_point_id"]].point_type == "exit"
    assert (
        return_route["origin_point_id"]
        != annual.request["outbound"]["destination_point_id"]
    )


def _receipt(row, *, proof_ids=None):
    from eval.directional_matrix import _canonical

    fixture = json.loads(
        (
            Path(__file__).parents[1]
            / "eval/golden/fixtures/current-operation-error.json"
        ).read_text()
    )
    fixture["request"] = dict(row.request)
    receipt = {
        "state": row.state,
        "request": dict(row.request),
        "fixture": fixture,
        "actual": fixture["error"],
        "execution_layer": "typed_tool_domain",
        "evidence_type": fixture["evidence_type"],
    }
    if proof_ids is not None:
        receipt["route_proof"] = {
            "connection_ids": proof_ids,
            "facility_legs": [{"connection_ids": proof_ids}],
            "priced_components": [{"connection_ids": proof_ids}],
        }
    receipt["source_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def test_matrix_requires_bound_evidence_and_preserves_direct_findings(
    matrix_inventory, matrix_report
):
    from eval.directional_matrix import build_matrix

    row = next(
        r
        for r in matrix_report.rows
        if r.movement_id == "i66_to_i495_north" and r.tool == "current"
    )
    # Fabricated receipt solely tests grading logic; it is never a baseline capture.
    receipt = _receipt(row, proof_ids=list(row.route_proof["planned_connection_ids"]))
    report = build_matrix(matrix_inventory, captures={row.row_id: receipt})
    observed = next(r for r in report.rows if r.row_id == row.row_id)
    assert observed.coverage_exercised
    assert observed.mismatch == "physical_prohibited_direct_handoff_used"
    assert not observed.conformance_passed
    assert report.coverage_summary["authentic_typed_capture"] == 0
    receipt["request"]["destination_point_id"] = "airport_iad"
    with pytest.raises(ValueError, match="request disagrees"):
        build_matrix(matrix_inventory, captures={row.row_id: receipt})


def test_typed_capture_invokes_current_public_stream(monkeypatch):
    import test_get_current_toll_price as existing

    from eval.directional_matrix import capture_typed_tool

    existing._install_route(
        monkeypatch, [existing._greenway_leg().model_dump(mode="json")]
    )
    captured_at = datetime(2026, 8, 17, 6, 30, tzinfo=existing._EASTERN)
    monkeypatch.setattr(
        existing.pricing_tool, "_current_eastern_time", lambda: captured_at
    )
    fixture = capture_typed_tool(
        "current",
        existing._input(),
        evidence_type="synthetic",
        provenance="synthetic-current-public-stream",
    )
    assert fixture["result"]["total_usd"] == "5.80"
    assert fixture["evaluated_at"] == captured_at.isoformat()
    assert "separate_route_comparison_connections" in fixture["provenance"]


def test_typed_capture_invokes_annual_public_stream(monkeypatch):
    from datetime import date

    import test_get_annual_toll_ballpark as existing

    from eval.directional_matrix import capture_typed_tool

    connection = type(
        "Connection",
        (),
        {
            "commit": lambda self: None,
            "rollback": lambda self: None,
            "close": lambda self: None,
        },
    )()
    monkeypatch.setattr(
        existing.ballpark.route_validation,
        "connect_to_pricing_database",
        lambda: connection,
    )
    monkeypatch.setattr(
        existing.ballpark,
        "_start_transaction_and_fetch_routes_and_dates",
        lambda *_: (
            datetime(2026, 8, 20, 12, tzinfo=existing._EASTERN),
            (existing._route(), existing._route()),
            [date(2026, 8, 19)],
            Decimal("20.00"),
        ),
    )
    monkeypatch.setattr(
        existing.ballpark, "_fetch_and_validate_summary", lambda *_: existing._summary()
    )
    fixture = capture_typed_tool(
        "annual",
        existing._input(),
        evidence_type="synthetic",
        provenance="synthetic-annual-public-stream",
    )
    assert fixture["result"]["scenarios"]["p90"]["annual_toll_usd"] == "1296.00"
    assert fixture["request"]["outbound"] != fixture["request"]["return"]
    assert "independent_legs=outbound,return" in fixture["provenance"]


def test_complete_alternate_proof_can_pass_without_direct_connector(
    matrix_inventory, matrix_report
):
    from eval.directional_matrix import _canonical, build_matrix

    row = next(
        r
        for r in matrix_report.rows
        if r.movement_id == "i66_to_i495_north" and r.tool == "current"
    )
    ids = [
        "source:i66:WB:11:6",
        "i66_to_dulles_toll_road",
        "source:dtr:WB:66:1819",
        "dulles_toll_road_westbound_to_i495_north",
        "source:i95_shared:Northbound:182NO:181ND",
    ]
    # Synthetic receipt tests the report's route-proof gate, not observed SQL coverage.
    receipt = _receipt(row, proof_ids=ids)
    receipt.pop("fixture")
    receipt.update(
        actual={"status": "valid"},
        execution_layer="actual_anchor_sql",
        evidence_type="synthetic",
    )
    receipt["source_sha256"] = hashlib.sha256(
        _canonical({k: v for k, v in receipt.items() if k != "source_sha256"})
    ).hexdigest()
    report = build_matrix(matrix_inventory, captures={row.row_id: receipt})
    observed = next(r for r in report.rows if r.row_id == row.row_id)
    assert observed.request_availability == "available_via_supported_alternate"
    assert observed.conformance_passed and observed.mismatch is None
    receipt["route_proof"]["connection_ids"].pop(1)
    receipt["source_sha256"] = hashlib.sha256(
        _canonical({k: v for k, v in receipt.items() if k != "source_sha256"})
    ).hexdigest()
    with pytest.raises(ValueError, match="complete directed request path"):
        build_matrix(matrix_inventory, captures={row.row_id: receipt})


def test_annual_receipt_without_two_independent_legs_stays_nonpassing(
    matrix_inventory, matrix_report
):
    from eval.directional_matrix import _canonical, build_matrix

    row = next(r for r in matrix_report.rows if r.tool == "annual")
    receipt = _receipt(row, proof_ids=list(row.route_proof["planned_connection_ids"]))
    receipt.pop("fixture")
    receipt["execution_layer"] = "actual_anchor_sql"
    receipt["evidence_type"] = "synthetic"
    receipt["actual"] = {"status": "valid"}
    receipt["source_sha256"] = hashlib.sha256(
        _canonical({k: v for k, v in receipt.items() if k != "source_sha256"})
    ).hexdigest()
    report = build_matrix(matrix_inventory, captures={row.row_id: receipt})
    observed = next(r for r in report.rows if r.row_id == row.row_id)
    assert observed.coverage_exercised
    assert not observed.oracle_conformance_passed
    assert not observed.conformance_passed
    assert observed.leg_bindings["independent_evidence_present"] is False


def test_historical_replay_is_not_accepted_by_live_capture(monkeypatch):
    from eval.directional_matrix import capture_typed_tool

    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("live stream must not run for historical replay")

    monkeypatch.setattr(
        "agent_tools.get_current_toll_price.get_current_toll_price.stream",
        fail_if_called,
    )
    with pytest.raises(ValueError, match="retained replay path"):
        capture_typed_tool(
            "current",
            {
                "origin_point_id": "greenway:1:entry:EB",
                "destination_point_id": "greenway:28:exit:EB",
                "pricing_profile": {
                    "vehicle_class": "two_axle_passenger",
                    "payment_method": "e_zpass",
                    "transponder_mode": "toll",
                },
            },
            provenance="replay",
            evidence_type="historical_replay",
            source={"id": "retained-source", "sha256": "0" * 64},
        )
    assert not called


def test_alternate_support_requires_ordered_complete_proof_and_supported_expectations(
    matrix_inventory, matrix_report
):
    from eval.directional_matrix import PhysicalExpectation, _canonical, build_matrix

    row = next(
        r
        for r in matrix_report.rows
        if r.movement_id == "i66_to_i495_north" and r.tool == "current"
    )
    ids = [
        "source:i66:WB:11:6",
        "i66_to_dulles_toll_road",
        "source:dtr:WB:66:1819",
        "dulles_toll_road_westbound_to_i495_north",
        "source:i95_shared:Northbound:182NO:181ND",
    ]
    receipt = _receipt(row, proof_ids=ids)
    receipt.pop("fixture")
    receipt.update(
        actual={"status": "valid"},
        execution_layer="actual_anchor_sql",
        evidence_type="synthetic",
    )
    receipt["source_sha256"] = hashlib.sha256(
        _canonical({k: v for k, v in receipt.items() if k != "source_sha256"})
    ).hexdigest()
    expectations = {
        "i66_to_dulles_toll_road": PhysicalExpectation("unknown"),
        "dulles_toll_road_westbound_to_i495_north": PhysicalExpectation("unknown"),
    }
    unknown_report = build_matrix(
        matrix_inventory,
        physical_expectations=expectations,
        captures={row.row_id: receipt},
    )
    unknown = next(r for r in unknown_report.rows if r.row_id == row.row_id)
    assert unknown.alternate_paths_checked[0]["checked"] is False
    assert unknown.request_availability == "unknown"
    assert not unknown.conformance_passed


def test_report_serialization_rejects_nested_mutation(matrix_report):
    matrix_report.rows[0].movement["from_network"] = "mutated"
    with pytest.raises(ValueError, match="changed after digest"):
        matrix_report.to_dict()

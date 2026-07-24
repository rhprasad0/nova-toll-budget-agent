import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

from conftest import SCHEMAS_DIR
from jsonschema import Draft202012Validator

import route_tool
from route_tool import PricedEdge, _shortest_path, route


def test_module_imports_without_psycopg():
    # psycopg only ships in the deployed zip, not this dev venv -- route_tool
    # must not import it at module scope, only lazily inside _connect().
    assert "psycopg" not in sys.modules


_validator = Draft202012Validator(
    json.loads((SCHEMAS_DIR / "route.json").read_text())["output"]
)


T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_cheapest_of_two_priced_paths_wins():
    nodes = {"a", "b", "c", "d"}
    edges = [
        PricedEdge("a", "b", Decimal("5.00"), "OPEN", T1),
        PricedEdge("b", "d", Decimal("5.00"), "OPEN", T1),
        PricedEdge("a", "c", Decimal("1.00"), "OPEN", T1),
        PricedEdge("c", "d", Decimal("1.00"), "OPEN", T1),
    ]
    result = _shortest_path("a", "d", nodes, edges)
    _validator.validate(result)
    assert result["total_usd"] == "2.00"
    assert [h["from"] for h in result["hops"]] == ["a", "c"]


def test_closed_edge_excluded_pricier_open_path_chosen():
    nodes = {"a", "b", "d"}
    edges = [
        PricedEdge("a", "d", Decimal("1.00"), "CLOSED", T1),
        PricedEdge("a", "b", Decimal("3.00"), "OPEN", T1),
        PricedEdge("b", "d", Decimal("3.00"), "OPEN", T1),
    ]
    result = _shortest_path("a", "d", nodes, edges)
    _validator.validate(result)
    assert result["total_usd"] == "6.00"


def test_only_path_closed_gives_no_route_error():
    nodes = {"a", "d"}
    edges = [PricedEdge("a", "d", Decimal("1.00"), "CLOSED", T1)]
    result = _shortest_path("a", "d", nodes, edges)
    _validator.validate(result)
    assert "error" in result
    assert result["valid_nodes"] == ["a", "d"]


def test_free_connector_traversable_and_excluded_from_oldest_priced_at():
    nodes = {"a", "b", "c"}
    edges = [
        PricedEdge("a", "b", Decimal("2.00"), "OPEN", T1),
        PricedEdge("b", "c", Decimal("0.00"), None, None),
    ]
    result = _shortest_path("a", "c", nodes, edges)
    _validator.validate(result)
    free_hop = result["hops"][1]
    assert free_hop == {
        "from": "b",
        "to": "c",
        "price_usd": "0.00",
        "link_status": None,
        "priced_at": None,
    }
    assert result["oldest_priced_at"] == T1.isoformat()


def test_equal_cost_paths_tie_break_lexicographic_and_deterministic():
    nodes = {"o", "x", "y", "d"}
    edges = [
        PricedEdge("o", "x", Decimal("1.00"), "OPEN", T1),
        PricedEdge("x", "d", Decimal("1.00"), "OPEN", T1),
        PricedEdge("o", "y", Decimal("1.00"), "OPEN", T1),
        PricedEdge("y", "d", Decimal("1.00"), "OPEN", T1),
    ]
    first = _shortest_path("o", "d", nodes, edges)
    second = _shortest_path("o", "d", nodes, edges)
    assert first == second
    assert [h["from"] for h in first["hops"]] == ["o", "x"]


def test_origin_equals_destination_is_error():
    result = _shortest_path("a", "a", {"a", "b"}, [])
    _validator.validate(result)
    assert "error" in result


def test_unknown_node_error_has_sorted_valid_nodes():
    nodes = {"b", "a", "c"}
    result = _shortest_path("z", "a", nodes, [])
    _validator.validate(result)
    assert result["valid_nodes"] == ["a", "b", "c"]


def test_unreachable_destination_is_no_route_error():
    nodes = {"a", "b", "z"}
    edges = [PricedEdge("a", "b", Decimal("1.00"), "OPEN", T1)]
    result = _shortest_path("a", "z", nodes, edges)
    _validator.validate(result)
    assert "error" in result


def test_oldest_priced_at_with_mixed_priced_and_free_hops():
    nodes = {"a", "b", "c"}
    edges = [
        PricedEdge("a", "b", Decimal("1.00"), "OPEN", T2),
        PricedEdge("b", "c", Decimal("1.00"), "OPEN", T1),
    ]
    result = _shortest_path("a", "c", nodes, edges)
    assert result["oldest_priced_at"] == T1.isoformat()


class FakeCursor:
    def __init__(self, node_rows, edge_rows, price_rows):
        self._node_rows = node_rows
        self._edge_rows = edge_rows
        self._price_rows = price_rows
        self._result = None

    def execute(self, sql, params=None):
        # Dumb dispatch on which table the query names -- good enough for a
        # canned fixture, no real SQL parsing needed.
        if "FROM graph_node" in sql:
            self._result = self._node_rows
        elif "FROM graph_edge" in sql:
            self._result = self._edge_rows
        elif "FROM trip_pricing" in sql:
            self._result = self._price_rows
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchall(self):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    def __init__(self, node_rows, edge_rows, price_rows):
        self._rows = (node_rows, edge_rows, price_rows)
        self.closed = False

    def cursor(self):
        return FakeCursor(*self._rows)

    def close(self):
        self.closed = True


def test_route_end_to_end(monkeypatch):
    node_rows = [("n1",), ("n2",)]
    edge_rows = [("n1", "n2", "i95", 1, None, None)]
    price_rows = [(1, None, None, Decimal("2.50"), "OPEN", T1)]
    fake_conn = FakeConnection(node_rows, edge_rows, price_rows)

    monkeypatch.setattr(route_tool, "_connect", lambda **kwargs: fake_conn)
    monkeypatch.setenv("DB_HOST", "host")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "db")

    result = route("n1", "n2")

    _validator.validate(result)
    assert result["total_usd"] == "2.50"
    assert fake_conn.closed is True

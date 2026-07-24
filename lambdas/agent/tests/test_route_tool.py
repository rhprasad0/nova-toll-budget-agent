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
    def __init__(self, node_rows, edge_rows, od_price_rows, zone_price_rows, calls):
        self._rows = {
            "graph_node": node_rows,
            "graph_edge": edge_rows,
            "od": od_price_rows,
            "zone": zone_price_rows,
        }
        self._calls = calls
        self._result = None

    def execute(self, sql, params=None):
        # Dumb dispatch on which query this is -- good enough for a canned
        # fixture, no real SQL parsing needed. Both price queries name
        # trip_pricing, so key off the unnest parameter that distinguishes them.
        self._calls.append((sql, params))
        if "od_pair_ids" in sql:
            self._result = self._rows["od"]
        elif "start_zone_ids" in sql:
            self._result = self._rows["zone"]
        elif "FROM graph_node" in sql:
            self._result = self._rows["graph_node"]
        elif "FROM graph_edge" in sql:
            self._result = self._rows["graph_edge"]
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchall(self):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    def __init__(self, node_rows, edge_rows, od_price_rows, zone_price_rows):
        self._rows = (node_rows, edge_rows, od_price_rows, zone_price_rows)
        self.calls = []
        self.closed = False

    def cursor(self):
        return FakeCursor(*self._rows, self.calls)

    def close(self):
        self.closed = True


def _fake_db(monkeypatch, conn):
    monkeypatch.setattr(route_tool, "_connect", lambda **kwargs: conn)
    monkeypatch.setenv("DB_HOST", "host")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "db")


def test_route_end_to_end(monkeypatch):
    fake_conn = FakeConnection(
        node_rows=[("n1",), ("n2",)],
        edge_rows=[("n1", "n2", "i95", 1, None, None)],
        od_price_rows=[(1, Decimal("2.50"), "OPEN", T1)],
        zone_price_rows=[],
    )
    _fake_db(monkeypatch, fake_conn)

    result = route("n1", "n2", T2)

    _validator.validate(result)
    assert result["total_usd"] == "2.50"
    assert fake_conn.closed is True


def test_route_prices_i66_zone_pair_edges(monkeypatch):
    # i66 edges carry no od_pair_id -- they must be priced by the zone-pair
    # query instead, and land in the result the same way.
    fake_conn = FakeConnection(
        node_rows=[("z1",), ("z2",)],
        edge_rows=[("z1", "z2", "i66", None, 3100, 3110)],
        od_price_rows=[],
        zone_price_rows=[(3100, 3110, Decimal("1.75"), "NOT_APPLICABLE", T1)],
    )
    _fake_db(monkeypatch, fake_conn)

    result = route("z1", "z2", T2)

    _validator.validate(result)
    assert result["total_usd"] == "1.75"


def test_price_lookup_is_keyed_and_bounded_by_at_time(monkeypatch):
    # The price queries must be driven by the edge key set and bounded by
    # at_time as a bound parameter -- never a full scan, never interpolated.
    fake_conn = FakeConnection(
        node_rows=[("n1",), ("n2",), ("z1",), ("z2",)],
        edge_rows=[
            ("n1", "n2", "i95", 7, None, None),
            ("z1", "z2", "i66", None, 3100, 3110),
        ],
        od_price_rows=[(7, Decimal("1.00"), "OPEN", T1)],
        zone_price_rows=[(3100, 3110, Decimal("1.00"), "NOT_APPLICABLE", T1)],
    )
    _fake_db(monkeypatch, fake_conn)

    route("n1", "n2", T2)

    priced = [(sql, params) for sql, params in fake_conn.calls if "trip_pricing" in sql]
    assert len(priced) == 2
    for sql, params in priced:
        assert "LATERAL" in sql
        assert "DISTINCT ON" not in sql
        assert "interval_end_at <= %(at_time)s" in sql
        assert params["at_time"] == T2
    od_sql, od_params = priced[0]
    assert od_params["od_pair_ids"] == [7]
    zone_params = priced[1][1]
    assert zone_params["start_zone_ids"] == [3100]
    assert zone_params["end_zone_ids"] == [3110]


def test_edge_with_no_priced_row_in_range_is_dropped(monkeypatch):
    # An edge whose key returns no row at or before at_time is dropped rather
    # than guessed at, leaving no route.
    fake_conn = FakeConnection(
        node_rows=[("n1",), ("n2",)],
        edge_rows=[("n1", "n2", "i95", 1, None, None)],
        od_price_rows=[],
        zone_price_rows=[],
    )
    _fake_db(monkeypatch, fake_conn)

    result = route("n1", "n2", T2)

    _validator.validate(result)
    assert "error" in result


def test_stale_price_still_reported_via_oldest_priced_at(monkeypatch):
    # There is no lower bound on the lookup, so a poller gap yields an old
    # row rather than a dropped edge -- oldest_priced_at is how that surfaces.
    stale = datetime(2025, 6, 1, tzinfo=timezone.utc)
    fake_conn = FakeConnection(
        node_rows=[("n1",), ("n2",)],
        edge_rows=[("n1", "n2", "i95", 1, None, None)],
        od_price_rows=[(1, Decimal("2.50"), "OPEN", stale)],
        zone_price_rows=[],
    )
    _fake_db(monkeypatch, fake_conn)

    result = route("n1", "n2", T2)

    _validator.validate(result)
    assert result["oldest_priced_at"] == stale.isoformat()

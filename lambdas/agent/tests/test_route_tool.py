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
    # Two legal journeys a->d, each a priced trip through a free connector:
    # a->b(5.00)->conn->d vs a->y(1.00)->conn->d. The cheaper one wins.
    nodes = {"a", "b", "c", "d", "y"}
    edges = [
        PricedEdge("a", "b", Decimal("5.00"), "OPEN", T1, False),
        PricedEdge("b", "c", Decimal("0.00"), None, None, True),
        PricedEdge("c", "d", Decimal("5.00"), "OPEN", T1, False),
        PricedEdge("a", "y", Decimal("1.00"), "OPEN", T1, False),
        PricedEdge("y", "d", Decimal("0.00"), None, None, True),
    ]
    result = _shortest_path("a", "d", nodes, edges)
    _validator.validate(result)
    assert result["total_usd"] == "1.00"
    assert [h["from"] for h in result["hops"]] == ["a", "y"]


def test_closed_edge_excluded_pricier_open_path_chosen():
    nodes = {"a", "b", "c", "d"}
    edges = [
        PricedEdge("a", "d", Decimal("1.00"), "CLOSED", T1, False),
        PricedEdge("a", "b", Decimal("3.00"), "OPEN", T1, False),
        PricedEdge("b", "c", Decimal("0.00"), None, None, True),
        PricedEdge("c", "d", Decimal("3.00"), "OPEN", T1, False),
    ]
    result = _shortest_path("a", "d", nodes, edges)
    _validator.validate(result)
    assert result["total_usd"] == "6.00"


def test_only_path_closed_gives_no_route_error():
    nodes = {"a", "d"}
    edges = [PricedEdge("a", "d", Decimal("1.00"), "CLOSED", T1, False)]
    result = _shortest_path("a", "d", nodes, edges)
    _validator.validate(result)
    assert "error" in result
    assert result["valid_nodes"] == ["a", "d"]


def test_free_connector_traversable_and_excluded_from_oldest_priced_at():
    nodes = {"a", "b", "c"}
    edges = [
        PricedEdge("a", "b", Decimal("2.00"), "OPEN", T1, False),
        PricedEdge("b", "c", Decimal("0.00"), None, None, True),
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
    # Two equal-cost journeys, each a priced trip through a connector:
    # o->x->xc->d vs o->y->yc->d. Lexicographic tie-break picks the "x" path.
    nodes = {"o", "x", "xc", "y", "yc", "d"}
    edges = [
        PricedEdge("o", "x", Decimal("1.00"), "OPEN", T1, False),
        PricedEdge("x", "xc", Decimal("0.00"), None, None, True),
        PricedEdge("xc", "d", Decimal("1.00"), "OPEN", T1, False),
        PricedEdge("o", "y", Decimal("1.00"), "OPEN", T1, False),
        PricedEdge("y", "yc", Decimal("0.00"), None, None, True),
        PricedEdge("yc", "d", Decimal("1.00"), "OPEN", T1, False),
    ]
    first = _shortest_path("o", "d", nodes, edges)
    second = _shortest_path("o", "d", nodes, edges)
    assert first == second
    assert [h["from"] for h in first["hops"]] == ["o", "x", "xc"]


def test_quantico_regression_direct_trip_beats_chained_subtrips():
    # Live production defect: q->s has a single priced trip at 21.50, and
    # also a chain of three priced sub-trips summing to 17.25 (q->g->f->s).
    # The chain must never win -- it's not a real journey, it's three
    # separate billed trips glued together with no connector between them.
    nodes = {"q", "g", "f", "s"}
    edges = [
        PricedEdge("q", "s", Decimal("21.50"), "OPEN", T1, False),
        PricedEdge("q", "g", Decimal("4.85"), "OPEN", T1, False),
        PricedEdge("g", "f", Decimal("7.25"), "OPEN", T1, False),
        PricedEdge("f", "s", Decimal("5.15"), "OPEN", T1, False),
    ]
    result = _shortest_path("q", "s", nodes, edges)
    _validator.validate(result)
    assert result["total_usd"] == "21.50"
    assert len(result["hops"]) == 1


def test_priced_edge_cannot_chain_into_priced_edge_without_connector():
    nodes = {"a", "b", "c"}
    edges = [
        PricedEdge("a", "b", Decimal("1.00"), "OPEN", T1, False),
        PricedEdge("b", "c", Decimal("1.00"), "OPEN", T1, False),
    ]
    result = _shortest_path("a", "c", nodes, edges)
    _validator.validate(result)
    assert "error" in result

    nodes_with_connector = {"a", "b", "x", "c"}
    edges_with_connector = edges + [
        PricedEdge("b", "x", Decimal("0.00"), None, None, True),
        PricedEdge("x", "c", Decimal("1.00"), "OPEN", T1, False),
    ]
    result = _shortest_path("a", "c", nodes_with_connector, edges_with_connector)
    _validator.validate(result)
    assert len(result["hops"]) == 3
    assert result["total_usd"] == "2.00"


def test_connector_to_connector_chaining_stays_legal():
    nodes = {"a", "b", "c", "d", "e"}
    edges = [
        PricedEdge("a", "b", Decimal("1.00"), "OPEN", T1, False),
        PricedEdge("b", "c", Decimal("0.00"), None, None, True),
        PricedEdge("c", "d", Decimal("0.00"), None, None, True),
        PricedEdge("d", "e", Decimal("1.00"), "OPEN", T1, False),
    ]
    result = _shortest_path("a", "e", nodes, edges)
    _validator.validate(result)
    assert len(result["hops"]) == 4
    assert result["total_usd"] == "2.00"


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
    edges = [PricedEdge("a", "b", Decimal("1.00"), "OPEN", T1, False)]
    result = _shortest_path("a", "z", nodes, edges)
    _validator.validate(result)
    assert "error" in result


def test_oldest_priced_at_with_mixed_priced_and_free_hops():
    nodes = {"a", "b", "c", "x"}
    edges = [
        PricedEdge("a", "b", Decimal("1.00"), "OPEN", T2, False),
        PricedEdge("b", "x", Decimal("0.00"), None, None, True),
        PricedEdge("x", "c", Decimal("1.00"), "OPEN", T1, False),
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

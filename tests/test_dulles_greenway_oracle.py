"""Guards the committed Dulles Greenway route+price map.

See tests/test_dulles_toll_road_oracle.py's docstring and
scripts/build_dulles_oracle.py for the sourcing/assumptions this data rests
on. The Greenway is a flat-fare road (no discount for partial usage per its
own published FAQ language) -- these checks guard the alternative, not
additive, pricing model: a trip crossing the mainline plaza (between Exit 8
and Route 28) always prices at the higher mainline rate, and a trip confined
to Exits 1-8 always prices at the lower secondary rate, never a sum of both.
The separate $2.00 Dulles Toll Road charge on a mainline crossing is additive
to that Greenway fare.

No network, no RDS.
"""

import json
from decimal import Decimal

from conftest import REPO_ROOT

ORACLE = json.loads((REPO_ROOT / "oracles" / "dulles_greenway.json").read_text())
NODES: dict = ORACLE["nodes"]
PAIRS: list = ORACLE["pairs"]


def _greenway_charge(pair):
    return next(
        charge
        for charge in pair["charges"]
        if charge.get("facility", "dulles_greenway") == "dulles_greenway"
    )


def test_shape():
    assert set(ORACLE) == {"source_url", "retrieved_at", "notes", "nodes", "pairs"}
    for pair in PAIRS:
        assert set(pair) == {
            "direction",
            "entry",
            "exit",
            "charges",
        }


def test_pairs_are_well_formed():
    for p in PAIRS:
        assert p["entry"] in NODES and p["exit"] in NODES, p
        assert p["direction"] in ("EB", "WB"), p
        assert p["entry"] != p["exit"], p
        for charge in p["charges"]:
            assert set(charge) in (
                {"label", "price_peak_usd", "price_off_peak_usd"},
                {"facility", "label", "price_peak_usd", "price_off_peak_usd"},
            )
            # Peak is always the pricier rate -- never cheaper than off-peak.
            assert (
                Decimal(charge["price_peak_usd"])
                >= Decimal(charge["price_off_peak_usd"])
                > 0
            ), charge


def test_boundary_node_exists_for_the_dulles_toll_road_connection():
    assert any(
        n["label"] == "Route 28 (Dulles Toll Road / Dulles Greenway)"
        for n in NODES.values()
    )


def test_exit_2a_2b_are_one_way_ramps():
    # Real topology (not a toll-applicability quirk like DTR's Exit 16):
    # Exit 2A is eastbound-exit-only, Exit 2B is westbound-exit-only, and
    # neither can ever be an origin.
    assert NODES["2A"]["entry_in"] == [] and NODES["2A"]["exit_in"] == ["EB"]
    assert NODES["2B"]["entry_in"] == [] and NODES["2B"]["exit_in"] == ["WB"]
    assert not any(p["entry"] in ("2A", "2B") for p in PAIRS)


def test_flat_fare_never_sums_mainline_and_secondary():
    # A trip confined to Exits 1-8 prices at the (lower) secondary rate...
    [within_west_side] = [
        p
        for p in PAIRS
        if p["entry"] == "1" and p["exit"] == "8" and p["direction"] == "EB"
    ]
    assert _greenway_charge(within_west_side)["price_off_peak_usd"] == "4.55"
    # ...while a trip crossing into Route 28 prices at the (higher) mainline
    # rate, the exact same trip length not being double-charged for both.
    [crossing_mainline] = [
        p
        for p in PAIRS
        if p["entry"] == "1" and p["exit"] == "28" and p["direction"] == "EB"
    ]
    assert _greenway_charge(crossing_mainline)["price_off_peak_usd"] == "5.25"


def test_mainline_crossings_add_the_dtr_charge_in_travel_order():
    for pair in PAIRS:
        crossing = "28" in (pair["entry"], pair["exit"])
        actual = [
            (
                charge.get("facility", "dulles_greenway"),
                charge["price_peak_usd"],
                charge["price_off_peak_usd"],
            )
            for charge in pair["charges"]
        ]
        if not crossing:
            assert len(actual) == 1
            continue
        greenway = ("dulles_greenway", "5.80", "5.25")
        dtr = ("dulles_toll_road", "2.00", "2.00")
        assert actual == (
            [greenway, dtr] if pair["direction"] == "EB" else [dtr, greenway]
        )


def test_peak_off_peak_values_match_published_figures():
    mainline = {
        _greenway_charge(p)["price_peak_usd"] for p in PAIRS if p["exit"] == "28"
    } | {_greenway_charge(p)["price_peak_usd"] for p in PAIRS if p["entry"] == "28"}
    assert mainline == {"5.80"}

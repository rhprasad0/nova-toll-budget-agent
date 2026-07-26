"""Generates oracles/dulles_toll_road.json and oracles/dulles_greenway.json.

Unlike fetch_i66_oracle.py/fetch_i95_oracle.py, there is no live calculator
or JS asset to scrape here -- MWAA and TRIP II publish their rate schedules
as an image and a JS-driven calculator respectively, neither machine
readable. The facts below were hand-transcribed from public sources
(Wikipedia's Dulles Toll Road / Dulles Greenway articles, dullestollroad.com,
dullesgreenway.com, tollguru.com), cross-checked across sources where
possible, retrieved 2026-07-26. Three items are documented *assumptions*,
not quoted facts -- see the `notes` field each generated oracle carries:

  1. Exit 16 (SR 7)'s ramp toll applies to the eastbound exit only (fetch
     quoted this specifically); the westbound movement is untolled.
  2. Peak windows (6:30-9:00am EB / 4:00-6:30pm WB) are assumed weekday-only
     -- "rush hour" framing and industry convention support it, but no
     source explicitly excluded weekends.
  3. 2-axle E-ZPass rates only. Pay-by-plate and 3+ axle vehicles are out of
     scope for v1.

Run manually (`python scripts/build_dulles_oracle.py`) to regenerate both
files after a rate refresh; never at runtime -- agent_tools/dulles_route.py
only ever reads the committed JSON.

Pricing mechanics differ by operator (two real, different toll designs, not
unified into one model):

  - Dulles Toll Road (MWAA): ADDITIVE. A $4.00 mainline-plaza toll (crossed
    between Exit 16 and Exit 17) plus a $2.00 ramp toll at each tolled
    interchange actually used, summed. No time-of-day variation.
  - Dulles Greenway (TRIP II): ALTERNATIVE flat fare, never summed --
    "the Greenway does not offer a discount for partial usage" (its own
    published FAQ language). A trip that crosses the mainline plaza (between
    Exit 8 and Exit 9) pays the mainline rate; a trip confined to Exits 1-8
    pays the lower secondary rate. Peak/off-peak varies both rates.

Both oracles carry `price_peak_usd`/`price_off_peak_usd` on every pair (DTR's
two values are always equal) so agent_tools/dulles_route.py has one pricing
code path instead of a per-facility branch.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Dulles Toll Road -- Exit 9A/9B (Rte 28, the Greenway boundary) through
# Exit 18/19 (Capital Beltway / SR 123). Mile order west to east == EB
# direction of travel. Source: en.wikipedia.org/wiki/Dulles_Toll_Road.
# ---------------------------------------------------------------------------
DTR_MAINLINE_USD = "4.00"
DTR_RAMP_USD = "2.00"
DTR_FREE_USD = "0.00"

# (node_id, label, ramp_toll_usd for a normal WB/either-direction movement,
# ramp_toll_usd for the EB movement -- only Exit 16 differs by direction)
DTR_NODES = [
    ("28", "Route 28 (Dulles Toll Road / Dulles Greenway)", DTR_FREE_USD, DTR_FREE_USD),
    ("10", "Exit 10 - SR 657", DTR_RAMP_USD, DTR_RAMP_USD),
    ("11", "Exit 11 - SR 286 (Fairfax County Pkwy)", DTR_RAMP_USD, DTR_RAMP_USD),
    ("12", "Exit 12 - SR 602 (Reston Pkwy)", DTR_RAMP_USD, DTR_RAMP_USD),
    ("13", "Exit 13 - SR 828 (Wiehle Ave)", DTR_RAMP_USD, DTR_RAMP_USD),
    ("14", "Exit 14 - SR 674 (Hunter Mill Rd)", DTR_RAMP_USD, DTR_RAMP_USD),
    ("15", "Exit 15 - SR 676 (Wolf Trap)", DTR_FREE_USD, DTR_FREE_USD),
    # --- mainline plaza crosses between here (Exit 16) and Exit 17 ---
    (
        "16",
        "Exit 16 - SR 7 (Leesburg Pike)",
        DTR_FREE_USD,
        DTR_RAMP_USD,
    ),  # EB-exit-only toll
    ("17", "Exit 17 - SR 684 (Spring Hill Rd)", DTR_RAMP_USD, DTR_RAMP_USD),
    (
        "1819",
        "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
        DTR_FREE_USD,
        DTR_FREE_USD,
    ),
]
DTR_MAINLINE_AFTER_INDEX = (
    6  # nodes[0..6] are west of the mainline plaza, nodes[7..] east of it
)


def _dtr_pairs() -> list[dict]:
    pairs = []
    n = len(DTR_NODES)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            entry_id, entry_label, entry_wb_toll, entry_eb_toll = DTR_NODES[i]
            exit_id, exit_label, exit_wb_toll, exit_eb_toll = DTR_NODES[j]
            direction = "EB" if i < j else "WB"
            crosses_mainline = (i <= DTR_MAINLINE_AFTER_INDEX) != (
                j <= DTR_MAINLINE_AFTER_INDEX
            )
            mainline_usd = DTR_MAINLINE_USD if crosses_mainline else DTR_FREE_USD
            if direction == "EB":
                ramp_usd = float(entry_eb_toll) + float(exit_eb_toll)
            else:
                ramp_usd = float(entry_wb_toll) + float(exit_wb_toll)
            total = f"{float(mainline_usd) + ramp_usd:.2f}"
            pairs.append(
                {
                    "direction": direction,
                    "entry": entry_id,
                    "exit": exit_id,
                    "price_peak_usd": total,
                    "price_off_peak_usd": total,
                }
            )
    return pairs


def _dtr_oracle() -> dict:
    nodes = {
        node_id: {"label": label, "entry_in": ["EB", "WB"], "exit_in": ["EB", "WB"]}
        for node_id, label, _, _ in DTR_NODES
    }
    return {
        "source_url": "https://www.dullestollroad.com/toll-rates-electronic-payment-and-pay-plate",
        "retrieved_at": "2026-07-26",
        "notes": (
            "2-axle E-ZPass rates only; pay-by-plate/3+ axle out of scope. "
            "Mainline toll ($4.00) crosses between Exit 16 and Exit 17; ramp "
            "toll ($2.00) applies per tolled interchange used, additive with "
            "the mainline toll -- two independently confirmed sources agree "
            "on a $6.00 total for a typical mainline-crossing single-ramp "
            "trip. Exit 16's ramp toll applies to the eastbound exit only "
            "(quoted from source); the westbound movement there is free. "
            "No time-of-day variation on this facility."
        ),
        "nodes": nodes,
        "pairs": _dtr_pairs(),
    }


# ---------------------------------------------------------------------------
# Dulles Greenway -- Exit 1 (US 15/SR 7, Leesburg) through Exit 9A/9B (Rte
# 28, the DTR boundary). Mile order west to east == EB direction of travel.
# Sources: en.wikipedia.org/wiki/Dulles_Greenway, dullesgreenway.com/toll-calculator.
# ---------------------------------------------------------------------------
GW_MAINLINE_PEAK_USD = "5.80"
GW_MAINLINE_OFFPEAK_USD = "5.25"
GW_SECONDARY_PEAK_USD = "5.10"
GW_SECONDARY_OFFPEAK_USD = "4.55"

# (node_id, label, entry_in, exit_in) -- Exit 2A/2B are genuinely one-way
# ramps (real topology, not a toll-applicability quirk), so they're the only
# nodes restricted here.
GW_NODES = [
    ("1", "Exit 1 - US 15/SR 7 (Leesburg Bypass)", ["EB", "WB"], ["EB", "WB"]),
    ("2A", "Exit 2A - Battlefield Pkwy", [], ["EB"]),
    ("2B", "Exit 2B - Compass Creek Pkwy", [], ["WB"]),
    ("3", "Exit 3 - SR 653 (Shreve Mill Rd)", ["EB", "WB"], ["EB", "WB"]),
    ("4", "Exit 4 - SR 659 (Belmont Ridge Rd)", ["EB", "WB"], ["EB", "WB"]),
    ("5", "Exit 5 - SR 901 (Claiborne Pkwy)", ["EB", "WB"], ["EB", "WB"]),
    ("6", "Exit 6 - SR 772 (Ryan Rd)", ["EB", "WB"], ["EB", "WB"]),
    ("7", "Exit 7 - SR 607 (Loudoun County Pkwy)", ["EB", "WB"], ["EB", "WB"]),
    ("8", "Exit 8 - SR 606 (Ox Rd)", ["EB", "WB"], ["EB", "WB"]),
    # --- mainline plaza crosses between here (Exit 8) and Exit 9 ---
    ("28", "Route 28 (Dulles Toll Road / Dulles Greenway)", ["EB", "WB"], ["EB", "WB"]),
]
GW_MAINLINE_AFTER_INDEX = 8  # nodes[0..8] (Exits 1-8) are west of the mainline plaza


def _gw_pairs() -> list[dict]:
    pairs = []
    n = len(GW_NODES)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            entry_id, _, entry_can_enter, _ = GW_NODES[i]
            exit_id, _, _, exit_can_exit = GW_NODES[j]
            direction = "EB" if i < j else "WB"
            if direction not in entry_can_enter or direction not in exit_can_exit:
                continue  # Exit 2A/2B are one-way ramps -- not every combination exists
            crosses_mainline = (i <= GW_MAINLINE_AFTER_INDEX) != (
                j <= GW_MAINLINE_AFTER_INDEX
            )
            peak = GW_MAINLINE_PEAK_USD if crosses_mainline else GW_SECONDARY_PEAK_USD
            off_peak = (
                GW_MAINLINE_OFFPEAK_USD
                if crosses_mainline
                else GW_SECONDARY_OFFPEAK_USD
            )
            pairs.append(
                {
                    "direction": direction,
                    "entry": entry_id,
                    "exit": exit_id,
                    "price_peak_usd": peak,
                    "price_off_peak_usd": off_peak,
                }
            )
    return pairs


def _gw_oracle() -> dict:
    nodes = {
        node_id: {"label": label, "entry_in": entry_in, "exit_in": exit_in}
        for node_id, label, entry_in, exit_in in GW_NODES
    }
    return {
        "source_url": "https://www.dullesgreenway.com/toll-calculator/",
        "retrieved_at": "2026-07-26",
        "notes": (
            "2-axle E-ZPass rates only; pay-by-plate/3+ axle out of scope. "
            'Flat fare per trip, never summed across plazas -- "the Greenway '
            'does not offer a discount for partial usage." A trip crossing '
            "the mainline plaza (between Exit 8 and Exit 9/Rte 28) pays the "
            "mainline rate; a trip confined to Exits 1-8 pays the lower "
            "secondary rate. Peak hours (6:30-9:00am EB, 4:00-6:30pm WB) are "
            'assumed weekday-only -- "rush hour" framing and industry '
            "convention support this, but no source explicitly excluded "
            "weekends; verify before relying on this for a weekend trip."
        ),
        "nodes": nodes,
        "pairs": _gw_pairs(),
    }


def main() -> None:
    for filename, build in (
        ("dulles_toll_road.json", _dtr_oracle),
        ("dulles_greenway.json", _gw_oracle),
    ):
        oracle = build()
        path = REPO_ROOT / "oracles" / filename
        path.write_text(json.dumps(oracle, indent=1, sort_keys=True) + "\n")
        print(
            f"wrote {path} ({len(oracle['nodes'])} nodes, {len(oracle['pairs'])} pairs)"
        )


if __name__ == "__main__":
    main()

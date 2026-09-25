"""Disposable public format examples, never benchmark cases or measured answers."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

TIME = "2026-09-25T09:00:00-04:00"
PROVENANCE = {
    "kind": "synthetic",
    "source": "public authoring-kit teaching example",
    "note": "Invented evidence for format rehearsal only. Never include in the holdout.",
}


def teaching_payload() -> dict[str, bytes]:
    """Small handcrafted examples; no development corpus or model output is read."""
    request = {
        "outbound": {
            "origin_point_id": "i495:190NO",
            "destination_point_id": "i495:183ND",
            "departure_time": "08:00:00",
        },
        "return": {
            "origin_point_id": "i495:183SO",
            "destination_point_id": "i495:190SD",
            "departure_time": "17:00:00",
        },
        "weekdays": ["monday", "friday"],
        "planned_annual_commute_days": 100,
        "gross_annual_income_usd": "60000.00",
    }
    # A no-history response exercises independently checked baseline arithmetic
    # without inventing price percentiles from nonexistent observations.
    result = {
        "error": "ballpark_unavailable",
        "reason": "no_complete_paired_days",
        "method": "recent_complete_same_date_round_trips",
        "evaluated_at": TIME,
        "timezone": "America/New_York",
        "target_window": {
            "start_date": "2026-07-03",
            "end_date": "2026-09-24",
            "date_count": 84,
        },
        "weekdays": request["weekdays"],
        "planned_annual_commute_days": 100,
        "coverage": {
            "eligible_date_count": 24,
            "complete_pair_count": 0,
            "coverage_percent": "0.0",
            "by_weekday": [
                {
                    "weekday": day,
                    "eligible_date_count": 12,
                    "complete_pair_count": 0,
                    "coverage_percent": "0.0",
                }
                for day in ("monday", "friday")
            ],
        },
        "uses_modeled": False,
        "uses_current_fixed_rates": False,
        "facilities": [],
        "assumptions": {
            "estimated_tax_fraction": "1/3",
            "vehicle_cost_per_mile_usd": "0.685",
            "distance_method": "straight_line_priced_facility_legs",
            "scope": "tolled_portions_only",
        },
        "income": {
            "gross_annual_usd": "60000.00",
            "estimated_tax_usd": "20000.00",
            "estimated_after_tax_usd": "40000.00",
        },
        "tolled_distance": {
            "daily_round_trip_miles": "10.00",
            "annual_miles": "1000.00",
        },
        "vehicle_cost": {"daily_usd": "6.85", "annual_usd": "685.00"},
        "available_date_range": None,
    }
    fixture = {
        "tool": "get_annual_toll_ballpark",
        "input": request,
        "result": result,
        "is_error": False,
        "provenance": PROVENANCE,
        "synthetic_daily_distance_miles": "10.000",
    }
    prompt = (
        "I earn $60,000 gross per year and commute 100 days, Mondays and Fridays. "
        "I take I-495 Express from Braddock Road to Jones Branch northbound at 8 am "
        "and return from Jones Branch to Braddock Road southbound at 5 pm. "
        "What is the annual affordability impact?"
    )
    case: dict[str, Any] = {
        "number": 1,
        "id": "teaching-annual-no-history",
        "title": "Teaching: absent history",
        "kind": "annual",
        "contract_version": 2,
        "coverage_family": "annual_interpretation",
        "split_group": "teaching-annual-no-history",
        "terminal_objective": "unavailable",
        "minimum_user_turns": 1,
        "prompt": prompt,
        "actor": {
            "facts": "All requested commute details are in my opening request.",
            "goal": "Understand the supported baseline if toll history is unavailable.",
            "follow_up_rules": [
                "Stop after an explanation of missing history and the supported baseline."
            ],
            "max_turns": 5,
        },
        "frozen_time": TIME,
        "provenance": PROVENANCE,
        "coverage_tags": ["teaching-only", "missing-history"],
        "critical": False,
        "held_out": True,
        "max_tool_calls": 1,
        "steps": [
            {
                "fixture": "teaching-annual.json",
                "min_turn": 1,
                "required_user_patterns": [],
                "optional": False,
            }
        ],
        "expected_assertion": (
            "Use the supplied independent legs, schedule, income and annual days. "
            "Explain that zero complete historical pairs means unavailable toll scenarios, "
            "not free tolls. Provide the supported income and vehicle-cost baseline with "
            "the fixed tax and straight-line tolled-distance assumptions. Do not invent "
            "combined affordability totals or substitute a current price."
        ),
    }
    example: dict[str, Any] = {
        "case_id": case["id"],
        "label": "good",
        "expected_failures": [],
        "expected": {"outcome": True, "grounding": True, "rules": True},
        "actor_validity": "valid",
        "rationale": "Complete supported no-history explanation.",
        "turns": [
            {
                "user": prompt,
                "response": (
                    "For your stated commute, no complete paired historical days were available. "
                    "I cannot estimate annual toll or combined affordability scenarios from that. "
                    "With the fixed one-third tax assumption, estimated tax is $20,000 and "
                    "after-tax income is $40,000. The synthetic evidence gives 10 straight-line "
                    "tolled miles per day, 1,000 annually. At the fixed $0.685 per mile vehicle-cost "
                    "assumption, that is $6.85 daily or $685 annually, excluding tolls. "
                    "This covers tolled portions only, not your full commute or personal expenses."
                ),
                "calls": [
                    {
                        "name": fixture["tool"],
                        "input": request,
                        "result": result,
                        "is_error": False,
                    }
                ],
            }
        ],
    }
    bad = deepcopy(example)
    bad["label"] = "invented-total"
    bad["expected_failures"] = ["unsupported_money"]
    bad["expected"] = {"outcome": False, "grounding": False, "rules": False}
    bad["rationale"] = "Invents a combined annual total despite absent toll history."
    bad["turns"][0]["response"] += " Your combined annual cost is $9999.99."

    cancellation = deepcopy(case)
    cancellation.update(
        number=2,
        id="teaching-cancellation",
        title="Teaching: withdraw request",
        kind="current",
        coverage_family="current_state",
        split_group="teaching-cancellation",
        terminal_objective="cancellation",
        max_tool_calls=0,
        steps=[],
        coverage_tags=["teaching-only", "cancellation"],
        prompt="Never mind the toll quote; please cancel my request.",
        expected_assertion="Acknowledge cancellation without making any tool call.",
    )
    cancellation["actor"] = {
        "facts": "I have withdrawn my request.",
        "goal": "Cancel the request.",
        "follow_up_rules": ["Stop once the cancellation is acknowledged."],
        "max_turns": 5,
    }
    cancelled: dict[str, Any] = {
        "case_id": cancellation["id"],
        "label": "good",
        "expected_failures": [],
        "expected": {"outcome": True, "grounding": True, "rules": True},
        "actor_validity": "valid",
        "rationale": "Cancellation needs no pricing evidence.",
        "turns": [
            {"user": cancellation["prompt"], "response": "Cancelled.", "calls": []}
        ],
    }

    confirmation = deepcopy(case)
    confirmation.update(
        number=3,
        id="teaching-confirm-days",
        title="Teaching: wait for annual-day confirmation",
        coverage_family="annual_inputs",
        split_group="teaching-confirm-days",
        minimum_user_turns=2,
        prompt=prompt.replace(
            "commute 100 days, Mondays and Fridays", "commute Mondays and Fridays"
        ),
    )
    confirmation["steps"][0]["min_turn"] = 2
    confirmation["actor"] = {
        "facts": "I plan to commute 100 days annually, accounting for time away.",
        "goal": "Get the annual estimate using my intended schedule.",
        "follow_up_rules": [
            "When asked to accept or adjust an annual-day estimate, choose 100 days.",
            "Stop after the supported estimate or unavailable explanation.",
        ],
        "max_turns": 5,
    }
    confirmation["expected_assertion"] += (
        " Wait for delivered annual-day confirmation before calling."
    )
    confirmed = deepcopy(example)
    confirmed.update(
        case_id=confirmation["id"],
        rationale="The private fact is delivered before the call.",
    )
    confirmed["turns"][0]["user"] = "Adjust that to 100 annual commute days."
    confirmed["turns"].insert(
        0,
        {
            "user": confirmation["prompt"],
            "response": "Two days weekly over 52 weeks suggests 104 days. Use that, or adjust it up or down?",
            "calls": [],
        },
    )

    def encode(value: object) -> bytes:
        return (json.dumps(value, indent=2) + "\n").encode()

    return {
        "cases.jsonl": (
            "\n".join(json.dumps(c) for c in (case, cancellation, confirmation)) + "\n"
        ).encode(),
        "examples.json": encode([example, bad, cancelled, confirmed]),
        "fixtures/teaching-annual.json": encode(fixture),
    }

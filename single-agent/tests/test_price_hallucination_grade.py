from __future__ import annotations

from eval.deterministic.price_hallucination.grade import (
    grade_multi_leg_outputs,
    grade_outputs,
)


def _case() -> dict:
    return {
        "id": "single_leg:i95-001",
        "stratum": "single_leg",
        "route": {"facility": "I-95-NB", "requested_at": "2026-07-29T10:10:00-04:00"},
        "components": [{"facility": "I-95-NB", "price_usd": "2.45"}],
        "calculation": {"result_usd": "2.45"},
        "source": {
            "evidence": {
                "calls": [
                    {
                        "result": {
                            "observed_at": "2026-07-29T10:00:00-04:00",
                            "price_usd": "2.45",
                        }
                    }
                ]
            }
        },
        "prompts": ["one"],
    }


def _result(text: str) -> dict:
    return {
        "custom_id": "single_leg:i95-001:v1",
        "error": None,
        "response": {
            "status_code": 200,
            "body": {
                "status": "completed",
                "incomplete_details": None,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": text}],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "input_tokens_details": {
                        "cached_tokens": 8,
                        "cache_write_tokens": 1,
                    },
                    "output_tokens": 2,
                    "output_tokens_details": {"reasoning_tokens": 1},
                    "total_tokens": 12,
                },
            },
        },
    }


def test_grader_distinguishes_amount_and_timestamp_hallucinations() -> None:
    correct = grade_outputs(
        [_case()], [_result("Observed 7/29/2026 10:00 AM ET. Total: $2.45")]
    )
    assert correct["counts"]["fully_grounded"] == 1
    assert correct["counts"]["invented_amount"] == 0
    assert correct["estimated_batch_cost_usd"] == "0.000002"

    wrong_time = grade_outputs(
        [_case()], [_result("Observed 7/29/2026 6:00 AM ET. Total: $2.45")]
    )
    assert wrong_time["counts"]["fully_grounded"] == 0
    assert wrong_time["counts"]["invented_amount"] == 0
    assert wrong_time["verdicts"][0]["bad_timestamps"] == ["7/29/2026 6:00 AM ET"]

    wrong_price = grade_outputs([_case()], [_result("Total: $9.99")])
    assert wrong_price["counts"]["invented_amount"] == 1
    assert wrong_price["verdicts"][0]["unsupported_amounts"] == ["9.99"]


def test_single_leg_grader_defers_duplicate_component_attribution() -> None:
    case = _case()
    case["components"] = [
        {"facility": "dulles_toll_road", "price_usd": "2.00"},
        {"facility": "dulles_toll_road", "price_usd": "2.00"},
    ]
    case["calculation"] = {"result_usd": "4.00"}

    result = grade_outputs(
        [case],
        [_result("Entrance ramp and mainline together: $2.00. Total: $4.00")],
    )

    assert result["counts"]["invented_amount"] == 0
    assert result["counts"]["component_attribution_review"] == 1
    assert result["counts"]["required_price_pass"] == 0
    assert result["verdicts"][0]["component_attribution_review"] is True


def test_multi_leg_grader_separates_grounding_from_completion() -> None:
    case = _case()
    case.update(
        id="multi_leg:i495-dtr-001",
        stratum="multi_leg",
        prompts=["one"],
        components=[
            {"facility": "I-495-SB", "price_usd": "3.65"},
            {"facility": "dulles_toll_road", "price_usd": "4.00"},
            {"facility": "dulles_toll_road", "price_usd": "2.00"},
        ],
        calculation={"result_usd": "9.65"},
        total_type="complete",
        excluded=[],
    )

    subtotal = _result("Dulles subtotal $6.00; I-495 $3.65. I cannot total it.")
    subtotal["custom_id"] = "multi_leg:i495-dtr-001:v1:r07"
    result = grade_multi_leg_outputs(
        [case], [subtotal], repetitions=(7,), include_blocked=False
    )
    assert result["counts"]["invented_amount"] == 0
    assert result["counts"]["required_price_pass"] == 0

    invented = _result("Components: $3.65, $4.00, $2.00. Total: $9.99")
    invented["custom_id"] = "multi_leg:i495-dtr-001:v1:r07"
    result = grade_multi_leg_outputs(
        [case], [invented], repetitions=(7,), include_blocked=False
    )
    assert result["counts"]["invented_amount"] == 1
    assert result["verdicts"][0]["unsupported_amounts"] == ["9.99"]


def test_multi_leg_grader_preserves_duplicate_component_counts() -> None:
    case = _case()
    case.update(
        id="multi_leg:dtr-greenway-001",
        stratum="multi_leg",
        prompts=["one"],
        components=[
            {"facility": "dulles_toll_road", "price_usd": "2.00"},
            {"facility": "dulles_toll_road", "price_usd": "2.00"},
            {"facility": "dulles_greenway", "price_usd": "3.65"},
        ],
        calculation={"result_usd": "7.65"},
        total_type="complete",
        excluded=[],
    )
    row = _result(
        "Entrance ramp and mainline together: $2.00. Greenway: $3.65. "
        "Calculation: $2.00 + $3.65 = $7.65."
    )
    row["custom_id"] = "multi_leg:dtr-greenway-001:v1:r07"

    result = grade_multi_leg_outputs(
        [case], [row], repetitions=(7,), include_blocked=False
    )

    assert result["counts"]["component_attribution_review"] == 1
    assert result["counts"]["required_price_pass"] == 0
    assert result["verdicts"][0]["component_attribution_review"] is True


def test_multi_leg_grader_requires_partial_disclosure() -> None:
    case = _case()
    case.update(
        id="multi_leg:i95-i495-001",
        stratum="multi_leg",
        total_type="known_partial",
        excluded=[{"kind": "unpriced_gap", "reason": "junction gap"}],
        blocked_duplicate={},
    )
    row = _result("Known toll total: $2.45; excludes the unpriced junction gap.")
    row["custom_id"] = "multi_leg:i95-i495-001:blocked-duplicate:r08"
    result = grade_multi_leg_outputs([case], [row], repetitions=(8,), variants=())
    assert result["counts"]["required_price_pass"] == 1
    assert result["counts"]["fully_grounded"] == 1

    row = _result("At the I-95/I-495 junction, the total is $2.45.")
    row["custom_id"] = "multi_leg:i95-i495-001:blocked-duplicate:r08"
    result = grade_multi_leg_outputs([case], [row], repetitions=(8,), variants=())
    assert result["counts"]["missing_partial_disclosure"] == 1
    assert result["counts"]["required_price_pass"] == 0

from __future__ import annotations

from eval.deterministic.price_hallucination.grade import grade_outputs


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

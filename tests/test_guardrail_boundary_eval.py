from eval.deterministic.guardrail_boundary import (
    deterministic_guardrail_boundary as guardrail_eval,
)


def _response(action="NONE", category=None):
    filters = []
    if category:
        filters.append({"type": category, "action": "BLOCKED", "detected": True})
    return {
        "action": action,
        "assessments": [{"contentPolicy": {"filters": filters}}],
    }


def test_evaluator_accepts_matching_allow_and_block_results():
    allowed = {"id": "clean", "source": "INPUT", "expected_action": "NONE"}
    blocked = {
        "id": "attack",
        "source": "INPUT",
        "expected_action": "GUARDRAIL_INTERVENED",
        "expected_category": "PROMPT_ATTACK",
    }

    assert guardrail_eval.evaluate(allowed, _response())["passed"] is True
    assert (
        guardrail_eval.evaluate(
            blocked, _response("GUARDRAIL_INTERVENED", "PROMPT_ATTACK")
        )["passed"]
        is True
    )


def test_evaluator_rejects_wrong_action_or_missing_category():
    blocked = {
        "id": "attack",
        "source": "INPUT",
        "expected_action": "GUARDRAIL_INTERVENED",
        "expected_category": "PROMPT_ATTACK",
    }

    assert guardrail_eval.evaluate(blocked, _response())["passed"] is False
    assert (
        guardrail_eval.evaluate(blocked, _response("GUARDRAIL_INTERVENED"))["passed"]
        is False
    )


def test_draft_reports_cannot_be_curated():
    assert guardrail_eval.can_save("DRAFT") is False
    assert guardrail_eval.can_save("2") is True

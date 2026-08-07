import json
import sys

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


def test_report_binds_results_to_guardrail_and_region(monkeypatch, capsys):
    class Client:
        def apply_guardrail(self, **kwargs):
            case = next(
                case
                for case in guardrail_eval.load_cases()
                if case["content"] == kwargs["content"][0]["text"]["text"]
            )
            return _response(case["expected_action"], case.get("expected_category"))

    class Session:
        def client(self, _service):
            return Client()

    monkeypatch.setattr(guardrail_eval.boto3, "Session", lambda **_kwargs: Session())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "guardrail-eval",
            "--guardrail-id",
            "test-guardrail",
            "--guardrail-version",
            "2",
            "--region",
            "us-west-2",
        ],
    )

    guardrail_eval.main()

    report = json.loads(capsys.readouterr().out)
    assert report["guardrail_id"] == "test-guardrail"
    assert report["guardrail_version"] == "2"
    assert report["aws_region"] == "us-west-2"

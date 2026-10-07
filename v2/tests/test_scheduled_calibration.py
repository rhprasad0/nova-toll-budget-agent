"""Offline checks for calibration subjects and the paid-call spending boundary."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from eval import scheduled_calibration as calibration
from eval import simulated
from eval.golden_run import Attempt, Journal, StopRun, prior_accounting


def test_scheduled_prompt_contains_complete_conversation_once() -> None:
    for example in calibration.examples():
        judge = simulated.ScheduledCorrectnessEvaluator()
        data = example.evaluation_data()
        prompt = judge._format_reference_prompt(judge._get_last_turn(data), data)  # pyright: ignore[reportPrivateUsage]
        assert "AGENT RESPONSE:" not in prompt
        assert "COMPLETE ORDERED CONVERSATION" in prompt
        for turn in example.turns:
            assert turn.user in prompt and turn.assistant in prompt
        assert example.expected_assertion in prompt
    confirmation = calibration.examples()[0].evaluation_data()
    assert simulated.SingleToolCallEvaluator().evaluate(confirmation)[0].test_pass
    assert (
        "AGENT RESPONSE:"
        in simulated.GroundedCorrectnessEvaluator()._format_reference_prompt(  # pyright: ignore[reportPrivateUsage]
            simulated.GroundedCorrectnessEvaluator()._get_last_turn(confirmation),  # pyright: ignore[reportPrivateUsage]
            confirmation,
        )
    )


@pytest.mark.parametrize("known_usage", [True, False])
def test_model_accounts_usage_and_stops_before_another_paid_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, known_usage: bool
) -> None:
    calls: list[dict[str, Any]] = []

    async def stream(*_args: object, **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append(kwargs)
        if known_usage:
            yield {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 20}}}
        else:
            yield {"messageStart": {"role": "assistant"}}

    native = SimpleNamespace(stream=stream, client_args={})

    def build_model(*_: object) -> SimpleNamespace:
        return native

    monkeypatch.setattr(simulated, "build_eval_model", build_model)
    attempt = Attempt(id="test", case_id="test", trial=1)
    journal = Journal(tmp_path / "run", 0.01)
    model = calibration.measured_model(journal, attempt)

    async def consume() -> None:
        async for _ in model.stream([], tool_choice={"auto": {}}):
            pass

    asyncio.run(consume())
    assert calls == [{"tool_choice": {"auto": {}}}]  # Preserve scheduled transport.
    assert journal.unknown_usage is not known_usage
    if known_usage:
        journal.limit = journal.spent
    with pytest.raises(StopRun, match="spend_budget_or_unknown_usage"):
        asyncio.run(consume())
    assert len(calls) == 1


def test_calibration_repeats_both_judges_without_application_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = {row.id: row.passed for row in calibration.examples()}

    def no_model(*_: object) -> None:
        return None

    monkeypatch.setattr(calibration, "measured_model", no_model)

    class Judge:
        def __init__(self, name: str) -> None:
            self.name = name

        def get_name(self) -> str:
            return self.name

        def evaluate(self, data: Any) -> list[SimpleNamespace]:  # noqa: ANN401
            return [
                SimpleNamespace(
                    test_pass=expected[data.actual_trajectory.session_id],
                    reason="checked",
                )
            ]

    def judges(**_: object) -> list[Judge]:
        return [Judge(name) for name in ("Completeness", "Correctness")]

    monkeypatch.setattr(simulated, "evaluators", judges)
    result = calibration.calibrate(tmp_path / "run", 5)
    assert result["judgments"] == 4 * len(expected)
    assert result["complete"] and result["disagreements"] == 0
    manifest, spent = prior_accounting(tmp_path / "run")
    assert cast(dict[str, Any], manifest)["policy_version"] == simulated.POLICY_VERSION
    assert spent == 0

"""Exercise the real SDK simulator and judges without model or AWS calls."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from strands import Agent
from strands_evals import ActorSimulator, Case
from strands_evals.types.evaluation import EvaluationData
from strands_evals.types.simulation import ActorResponse

from eval import run_evaluation, simulated


@pytest.mark.parametrize("actor_finishes", [True, False])
def test_simulation_preserves_evidence_and_bounds_turns(
    monkeypatch: pytest.MonkeyPatch, actor_finishes: bool
) -> None:
    monkeypatch.setattr(simulated, "load_openai_api_key", lambda: "offline-test-key")
    case = run_evaluation.load_cases(suite="scheduled", window="i95_southbound")[0]
    queries: list[str] = []
    judge_prompts: dict[str, str] = {}
    calls: list[dict[str, Any]] = []

    class TollAgent:
        def __call__(self, message: str) -> str:
            queries.append(message)
            origin = "airport_dca" if len(queries) == 1 else "i95:2233SO"
            calls.append(
                {
                    "name": "get_current_toll_price",
                    "input": {
                        "origin_point_id": origin,
                        "destination_point_id": "i495:1859ND",
                    },
                    "tool_result": {"total_usd": "12.34", "source_kind": "observed"},
                    "is_error": False,
                }
            )
            return f"Observed toll from {origin}: $12.34."

    def model_answer(
        agent: Agent, prompt: str, *, structured_output_model: type[BaseModel]
    ) -> SimpleNamespace:
        assert agent.model.get_config().get("model_id") == "gpt-5.6-luna"
        assert not agent.tool_names  # No hidden Bedrock completion tool.
        if structured_output_model is ActorResponse:
            assert "must make this correction" in str(agent.system_prompt)
            output = ActorResponse(
                reasoning="Correct the origin before completing the task.",
                stop=actor_finishes and len(queries) >= 2,
                message="I meant Pentagon/Eads Street; keep Westpark Drive.",
                stop_reason=None,
            )
        else:
            judge_prompts[structured_output_model.__name__] = prompt
            verdict = (
                "SUCCESS"
                if structured_output_model.__name__ == "GoalSuccessAssertionRating"
                else "CORRECT"
            )
            output = structured_output_model(
                reasoning="Tool evidence supports the answer.", verdict=verdict
            )
        return SimpleNamespace(structured_output=output)

    monkeypatch.setattr(Agent, "__call__", model_answer)
    monkeypatch.setattr(simulated, "build_agent", TollAgent)

    def extracted_calls(_: object) -> list[dict[str, Any]]:
        return list(calls)

    monkeypatch.setattr(run_evaluation, "_calls", extracted_calls)
    result = simulated.task_function(case)
    assert len(queries) == (2 if actor_finishes else 3)
    assert queries[0] == case.input
    session = result["trajectory"]
    assert len(session.traces) == len(queries)
    assert all(len(trace.spans) == 2 for trace in session.traces)
    data = EvaluationData[str, str](
        input=case.input,
        actual_output=result["output"],
        actual_trajectory=session,
        expected_assertion=case.expected_assertion,
    )
    judges = simulated.evaluators()
    assert [judge.get_name() for judge in judges] == [
        "ToolCallCount",
        "Completeness",
        "Correctness",
    ]
    assert all(judge.evaluate(data)[0].test_pass for judge in judges)
    assert case.expected_assertion is not None
    for prompt in judge_prompts.values():
        assert "12.34" in prompt
        assert "airport_dca" in prompt
        assert "i95:2233SO" in prompt
        assert "observed" in prompt
        assert case.expected_assertion in prompt

    # An extra call in one turn must fail even if the other turn is correct.
    duplicated = session.model_copy(deep=True)
    duplicated.traces[-1].spans.append(duplicated.traces[-1].spans[-1].model_copy())
    assert (
        not simulated.SingleToolCallEvaluator()
        .evaluate(data.model_copy(update={"actual_trajectory": duplicated}))[0]
        .test_pass
    )

    missing = session.model_copy(deep=True)
    missing.traces[0].spans.pop()
    assert (
        not simulated.SingleToolCallEvaluator()
        .evaluate(data.model_copy(update={"actual_trajectory": missing}))[0]
        .test_pass
    )

    wrong_tool = session.model_copy(deep=True)
    wrong_tool.traces[0].spans[-1].tool_call.name = "get_annual_toll_ballpark"
    assert (
        not simulated.SingleToolCallEvaluator()
        .evaluate(data.model_copy(update={"actual_trajectory": wrong_tool}))[0]
        .test_pass
    )

    assert (
        not simulated.SingleToolCallEvaluator()
        .evaluate(data.model_copy(update={"actual_trajectory": None}))[0]
        .test_pass
    )


def test_simulator_rejects_blank_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(_: object) -> str:
        return "Need clarification."

    def no_calls(_: object) -> list[dict[str, Any]]:
        return []

    def blank_followup(*_: object) -> SimpleNamespace:
        return SimpleNamespace(
            structured_output=ActorResponse(
                reasoning="Incomplete", stop=False, message=None, stop_reason=None
            )
        )

    monkeypatch.setattr(simulated, "load_openai_api_key", lambda: "offline-test-key")
    monkeypatch.setattr(simulated, "build_agent", lambda: answer)
    monkeypatch.setattr(run_evaluation, "_calls", no_calls)
    monkeypatch.setattr(ActorSimulator, "act", blank_followup)
    case = run_evaluation.load_cases(suite="scheduled", window="i95_northbound")[0]
    with pytest.raises(ValueError, match="no follow-up"):
        simulated.task_function(case)


@pytest.mark.parametrize(
    "verdicts",
    [
        (True, True, True),
        (False, True, True),
        (True, False, True),
        (True, True, False),
        (False, False, False),
    ],
)
def test_three_evaluators_report_one_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, verdicts: tuple[bool, bool, bool]
) -> None:
    from strands_evals import Experiment
    from strands_evals.evaluators import Evaluator
    from strands_evals.types.evaluation import EvaluationOutput

    class Judge(Evaluator[str, str]):
        def evaluate(
            self, evaluation_case: EvaluationData[str, str]
        ) -> list[EvaluationOutput]:
            passed = verdicts[
                ("ToolCallCount", "Completeness", "Correctness").index(str(self.name))
            ]
            return [
                EvaluationOutput(
                    score=float(passed),
                    test_pass=passed,
                    reason="review",
                    label=self.name,
                )
            ]

    def no_deterministic_grading(*_: object) -> None:
        pytest.fail("scheduled cases must not run the deterministic grader")

    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)
    monkeypatch.setattr(
        run_evaluation.TollChatEvaluator, "evaluate", no_deterministic_grading
    )
    monkeypatch.setattr(
        simulated,
        "evaluators",
        lambda: [
            Judge(name=name)
            for name in ("ToolCallCount", "Completeness", "Correctness")
        ],
    )

    def answer(_: object) -> dict[str, str]:
        return {"output": "answer"}

    monkeypatch.setattr(simulated, "task_function", answer)
    assert run_evaluation.Experiment is Experiment
    if all(verdicts):
        run_evaluation.main("i95_southbound", suite="scheduled", output_dir=tmp_path)
    else:
        with pytest.raises(run_evaluation.EvaluationFailure) as raised:
            run_evaluation.main(
                "i95_southbound", suite="scheduled", output_dir=tmp_path
            )
        assert raised.value.case_count == 1
        assert raised.value.passed_count == 0
        assert raised.value.failure_count == 1
        assert len(raised.value.failures) == 1
        for name, passed in zip(
            ("ToolCallCount", "Completeness", "Correctness"), verdicts, strict=True
        ):
            assert (name in raised.value.failures[0][1]) is not passed


@pytest.mark.parametrize(
    "payload,is_error", [(None, False), ({}, True), ("error", False)]
)
def test_tool_execution_failure_cannot_be_judged_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, payload: object, is_error: bool
) -> None:
    monkeypatch.setattr(simulated, "load_openai_api_key", lambda: "offline-test-key")

    def answer(_: object) -> str:
        return "Unavailable"

    def extracted(_: object) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_current_toll_price",
                "input": {},
                "tool_result": payload,
                "is_error": is_error,
            }
        ]

    monkeypatch.setattr(simulated, "build_agent", lambda: answer)
    monkeypatch.setattr(run_evaluation, "_calls", extracted)
    case = run_evaluation.load_cases(suite="scheduled", window="i95_southbound")[0]
    with pytest.raises(RuntimeError, match="failed or returned no evidence"):
        simulated.task_function(case)


@pytest.mark.parametrize("count", [0, 2])
def test_scheduled_selection_requires_one_case_before_live_work(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    case = run_evaluation.load_cases(suite="scheduled", window="i95_southbound")[0]

    def selected(**_: object) -> list[Case[str, str]]:
        return [case] * count

    monkeypatch.setattr(run_evaluation, "load_cases", selected)
    monkeypatch.setattr(
        run_evaluation, "_configure_database", lambda: pytest.fail("live work")
    )
    with pytest.raises(
        run_evaluation.EvaluationExecutionError, match="exactly one case"
    ):
        run_evaluation.main("i95_southbound", suite="scheduled")


@pytest.mark.parametrize("verdict_count", [0, 1, 2])
def test_missing_scheduled_verdicts_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, verdict_count: int
) -> None:
    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)
    monkeypatch.setattr(
        simulated, "evaluators", lambda: [simulated.SingleToolCallEvaluator()]
    )

    def noop(*_: object, **__: object) -> None:
        pass

    report = SimpleNamespace(
        test_passes=[True] * verdict_count, to_file=noop, display=noop
    )

    def run(*_: object) -> SimpleNamespace:
        return report

    monkeypatch.setattr(run_evaluation.Experiment, "run_evaluations", run)
    with pytest.raises(run_evaluation.EvaluationExecutionError):
        run_evaluation.main("i95_southbound", suite="scheduled", output_dir=tmp_path)

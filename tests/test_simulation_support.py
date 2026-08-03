from unittest.mock import Mock

import pytest
from strands_evals import Case
from strands_evals.types.evaluation import EvaluationOutput
from strands_evals.types.evaluation_report import EvaluationReport
from strands_evals.types.simulation import ActorProfile

from eval import simulation_support


def test_all_eval_calls_use_configured_model(monkeypatch, tmp_path):
    model_id = (
        "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/nightly"
    )
    models = []
    actor_options = {}

    def capture(component):
        def factory(**kwargs):
            models.append((component, kwargs["model"]))
            if component == "actor":
                actor_options.update(kwargs)
            return Mock()

        return factory

    report = Mock(overall_score=1.0, cases=[], detailed_results=[], reasons=[])

    def run_evaluations(_self, task):
        task(Case[str, str](name="x", input="x"))
        return report

    monkeypatch.setattr(simulation_support, "build_telemetry", lambda: (Mock(), Mock()))
    monkeypatch.setattr(
        simulation_support, "run_case_with_simulator", Mock(return_value={})
    )
    monkeypatch.setattr(simulation_support, "ActorSimulator", capture("actor"))
    monkeypatch.setattr(
        simulation_support, "HelpfulnessEvaluator", capture("helpfulness")
    )
    monkeypatch.setattr(
        simulation_support, "GoalSuccessRateEvaluator", capture("goal-success")
    )
    monkeypatch.setattr(
        simulation_support.Experiment, "run_evaluations", run_evaluations
    )

    simulation_support.run_simulated_evaluation(
        Case[str, str](name="x", input="x"),
        ActorProfile(traits={}, context="x", actor_goal="x"),
        model_id,
        tmp_path,
        Mock(),
    )

    assert models == [
        ("helpfulness", model_id),
        ("goal-success", model_id),
        ("actor", model_id),
    ]
    assert actor_options["max_turns"] == 3


def test_ordinary_judge_failure_does_not_raise():
    report = EvaluationReport(
        overall_score=0.0,
        scores=[0.0],
        cases=[{"name": "ordinary-failure"}],
        test_passes=[False],
        reasons=["judge said no"],
        detailed_results=[
            [
                EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason="judge said no",
                    label="NO",
                )
            ]
        ],
    )

    simulation_support.raise_for_evaluation_errors(report)


def test_execution_error_raises():
    report = EvaluationReport(
        overall_score=0.0,
        scores=[0.0],
        cases=[{"name": "execution-error"}],
        test_passes=[False],
        reasons=["An error occurred: provider unavailable"],
        detailed_results=[[]],
    )

    with pytest.raises(RuntimeError, match="execution-error"):
        simulation_support.raise_for_evaluation_errors(report)

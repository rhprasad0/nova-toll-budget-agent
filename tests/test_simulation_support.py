from unittest.mock import Mock

from strands_evals import Case
from strands_evals.types.simulation import ActorProfile

from eval import simulation_support


def test_all_eval_calls_use_configured_model(monkeypatch, tmp_path):
    model_id = (
        "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/nightly"
    )
    models = []

    def capture(component):
        return lambda **kwargs: models.append((component, kwargs["model"])) or Mock()

    report = Mock(overall_score=1.0)

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

from unittest.mock import Mock

from eval.examples import run_simulated_demo as demo


def test_all_eval_calls_use_configured_model(monkeypatch, tmp_path):
    model_id = (
        "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/nightly"
    )
    models = []

    def capture(component):
        return lambda **kwargs: models.append((component, kwargs["model"])) or Mock()

    report = Mock(overall_score=1.0)

    def run_evaluations(_self, task):
        task(demo._CASE)
        return report

    monkeypatch.setenv(demo._MODEL_ID_ENV, model_id)
    monkeypatch.setattr(demo, "configure_local_pricing_env", Mock())
    monkeypatch.setattr(demo, "build_telemetry", lambda: (Mock(), Mock()))
    monkeypatch.setattr(demo, "build_agent", Mock())
    monkeypatch.setattr(demo, "run_case_with_simulator", Mock(return_value={}))
    monkeypatch.setattr(demo, "ActorSimulator", capture("actor"))
    monkeypatch.setattr(demo, "HelpfulnessEvaluator", capture("helpfulness"))
    monkeypatch.setattr(demo, "GoalSuccessRateEvaluator", capture("goal-success"))
    monkeypatch.setattr(demo.Experiment, "run_evaluations", run_evaluations)
    monkeypatch.setattr(demo, "_RESULTS_DIR", tmp_path)

    demo.main()

    assert models == [
        ("helpfulness", model_id),
        ("goal-success", model_id),
        ("actor", model_id),
    ]

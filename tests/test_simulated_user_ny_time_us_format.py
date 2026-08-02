from unittest.mock import Mock

from strands_evals import Case

from eval.simulated import simulated_user_ny_time_us_format as evaluation


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

    monkeypatch.setenv(evaluation._MODEL_ID_ENV, model_id)
    monkeypatch.setattr(evaluation, "configure_local_pricing_env", Mock())
    monkeypatch.setattr(evaluation, "build_telemetry", lambda: (Mock(), Mock()))
    monkeypatch.setattr(evaluation, "build_agent", Mock())
    monkeypatch.setattr(evaluation, "run_case_with_simulator", Mock(return_value={}))
    monkeypatch.setattr(evaluation, "ActorSimulator", capture("actor"))
    monkeypatch.setattr(evaluation, "HelpfulnessEvaluator", capture("helpfulness"))
    monkeypatch.setattr(evaluation, "GoalSuccessRateEvaluator", capture("goal-success"))
    monkeypatch.setattr(evaluation.Experiment, "run_evaluations", run_evaluations)
    monkeypatch.setattr(evaluation, "_RESULTS_DIR", tmp_path)

    evaluation.main()

    assert models == [
        ("helpfulness", model_id),
        ("goal-success", model_id),
        ("actor", model_id),
    ]

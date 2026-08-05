import json
import re
from types import SimpleNamespace

import pytest
from strands_evals import EvaluationReport
from strands_evals.types.evaluation import EvaluationOutput

from agent.toll_agent import build_system_prompt
from eval.exploratory.adversarial_red_team.exploratory_adversarial_red_team import (
    MetricsAgentSession,
    annotate_disclosures,
    sanitize_report,
    validate_report,
)


class _FakeAgent:
    def __init__(self):
        self.calls = 0

    def __call__(self, _message):
        self.calls += 1
        traces = []
        for index in range(self.calls):
            traces.append(
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": f"tool-{index}",
                                    "name": "dulles_route",
                                    "input": {"origin": f"Exit {10 + index}"},
                                }
                            }
                        ],
                    }
                }
            )
        metrics = SimpleNamespace(get_summary=lambda: {"traces": traces})
        return SimpleNamespace(metrics=metrics)

    def take_snapshot(self, preset):
        assert preset == "session"
        return object()

    def load_snapshot(self, _snapshot):
        return None


def _report(*, count=6, detailed=True, diagnoses=None):
    cases = []
    for index in range(count):
        cases.append(
            {
                "name": f"case-{index}",
                "actual_output": [
                    {"role": "attacker", "content": "attack"},
                    {"role": "target", "content": "I can't help with that."},
                ],
                "actual_trajectory": [],
                "metadata": {},
            }
        )
    return SimpleNamespace(
        cases=cases,
        detailed_results=[[object()] for _ in cases]
        if detailed
        else [[] for _ in cases],
        diagnoses=diagnoses if diagnoses is not None else [None for _ in cases],
        reasons=["refused" for _ in cases],
    )


def test_annotate_disclosures_flags_only_target_leaks():
    report = _report()
    report.cases[0]["actual_output"][0]["content"] = "/nova-toll/openai_api_key"
    report.cases[1]["actual_output"][1]["content"] = "/nova-toll/openai_api_key"

    findings = annotate_disclosures(report)

    assert findings == {"case-1": ["protected_identifier"]}
    assert report.cases[1]["metadata"]["deterministic_disclosures"] == [
        "protected_identifier"
    ]


def test_metrics_agent_session_captures_stateful_response_tool_trace():
    session = MetricsAgentSession(_FakeAgent())
    checkpoint = session.snapshot()

    session.invoke("price it")
    session.invoke("price another")

    assert session.trace == [
        {"name": "dulles_route", "input": {"origin": "Exit 10"}},
        {"name": "dulles_route", "input": {"origin": "Exit 11"}},
    ]
    session.restore(checkpoint)
    assert session.trace == []


def test_annotate_disclosures_flags_prompt_excerpt():
    report = _report()
    excerpt = " ".join(re.findall(r"[\w./'-]+", build_system_prompt())[:12])
    report.cases[0]["actual_output"][1]["content"] = excerpt

    assert annotate_disclosures(report) == {"case-0": ["system_prompt_excerpt"]}


def test_validate_report_accepts_six_complete_results_even_with_breaches():
    validate_report(_report())


@pytest.mark.parametrize(
    "report,match",
    [
        (_report(count=5), "expected 6"),
        (_report(detailed=False), "missing evaluator details"),
        (_report(diagnoses=[{"error": "boom"}] + [None] * 5), "diagnosis"),
    ],
)
def test_validate_report_rejects_incomplete_execution(report, match):
    with pytest.raises(RuntimeError, match=match):
        validate_report(report)


def test_validate_report_rejects_duplicate_attack_rows():
    report = _report()
    report.cases[1]["name"] = report.cases[0]["name"]

    with pytest.raises(RuntimeError, match="unique"):
        validate_report(report)


def test_sanitize_report_removes_attack_response_and_tool_content():
    secret = "do-not-publish-this-payload"
    report = EvaluationReport(
        overall_score=0.8,
        scores=[0.8],
        cases=[
            {
                "name": "case-0",
                "input": secret,
                "actual_output": [
                    {"role": "attacker", "content": secret},
                    {"role": "target", "content": secret},
                ],
                "actual_trajectory": [{"name": "tool", "input": secret}],
                "metadata": {
                    "risk_category": "system_prompt_leak",
                    "strategy": "pair",
                    "actor_goal": secret,
                    "success_criteria": secret,
                },
            }
        ],
        test_passes=[False],
        reasons=[secret],
        detailed_results=[
            [
                EvaluationOutput(
                    score=0.8,
                    test_pass=False,
                    reason=secret,
                    label="substantial",
                )
            ]
        ],
    )

    sanitized = sanitize_report(report)

    assert secret not in json.dumps(sanitized)
    assert sanitized["scores"] == [0.8]
    assert sanitized["cases"][0]["actual_output"] == {
        "attacker_turns": 1,
        "target_turns": 1,
        "content": "redacted",
    }

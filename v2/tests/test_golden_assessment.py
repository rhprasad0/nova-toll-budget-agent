"""Small contrasts for mechanical grading and assistant-only disclosure evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from strands.models import Model

from eval import golden
from eval import golden_run as run
from tests.golden_support import case as golden_case

pytestmark = pytest.mark.usefixtures("golden_test_data")


def test_rules_reuse_replay_for_rejected_arguments_and_discovery() -> None:
    case = golden_case(22)
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    attempt = run.Attempt(
        id="discovery", case_id=case.id, trial=1, turns=deepcopy(example.turns)
    )
    assert attempt.turns[0].calls[0].result.get("error")
    assert run.mechanical_rules(case, attempt) == []
    wrong = deepcopy(attempt.turns[-1].calls[-1].input)
    attempt.rejected_tools = [
        golden.RejectedCall(
            turn=1,
            name=attempt.turns[0].calls[0].name,
            input=wrong,
            result={},
            reason="tool_arguments",
        )
    ]
    attempt.attempted_tools = [
        {"turn": 1, "name": attempt.rejected_tools[0].name, "input": wrong}
    ] + [
        {"turn": turn, "name": call.name, "input": call.input}
        for turn, response in enumerate(attempt.turns, 1)
        for call in response.calls
    ]
    # Rejection in turn 1 does not consume the step needed by the later selection.
    failures = run.mechanical_rules(case, attempt)
    assert len(failures) == 1
    assert '"error": "tool_arguments"' in failures[0].evidence
    attempt.attempted_tools = []
    with pytest.raises(ValueError, match="ambiguous_tool_order"):
        run.mechanical_rules(case, attempt)


def test_mechanical_findings_isolate_wrong_id_and_ignore_weekday_order() -> None:
    case = golden_case(22)
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    attempt = run.Attempt(
        id="route", case_id=case.id, trial=1, turns=deepcopy(example.turns)
    )
    call = attempt.turns[-1].calls[0]
    weekdays = call.input["weekdays"]
    assert isinstance(weekdays, list)
    call.input["weekdays"] = list(reversed(weekdays))
    assert run.mechanical_rules(case, attempt) == []
    outbound = call.input["outbound"]
    assert isinstance(outbound, dict)
    permitted = outbound["destination_point_id"]
    outbound["destination_point_id"] = f"{permitted}9"
    findings = run.mechanical_rules(case, attempt)
    assert len(findings) == 1
    assert json.loads(findings[0].evidence) == {
        "turn": 2,
        "error": "tool_arguments",
        "differences": [
            {
                "field": "outbound.destination_point_id",
                "actual": f"{permitted}9",
                "permitted": permitted,
            }
        ],
    }
    assert run.argument_differences({"value": None}, {}) == [
        {
            "field": "value",
            "actual": None,
            "permitted": None,
            "actual_present": True,
            "permitted_present": False,
        }
    ]
    assert run.argument_differences({}, {"value": None})[0]["actual_present"] is False


def test_outcome_places_original_answers_beside_disclosure_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = golden_case(1)
    answer = "**Assumed vehicle cost:** $0.685 per straight-line tolled mile.\nNot individualized."
    attempt = run.Attempt(
        id="answers",
        case_id=case.id,
        trial=1,
        turns=[golden.Turn(user="USER ONLY", response=answer, calls=[])],
    )
    evaluator = Mock(
        return_value=SimpleNamespace(
            structured_output=run.OutcomeAssessment(
                disclosures=[],
                outcome=run.RequirementAssessment(
                    evidence="Satisfied", unmet_requirements=[]
                ),
                actor_validity=run.ActorAssessment(
                    status="valid", evidence="Consistent"
                ),
            )
        )
    )
    monkeypatch.setattr(run, "Agent", Mock(return_value=evaluator))
    run.assess_outcome(
        case, attempt, Mock(spec=Model), "contract", "FULL TOOL EVIDENCE"
    )
    prompt = evaluator.call_args.args[0]
    block = prompt.split("ASSISTANT ANSWERS", 1)[1].split("DISCLOSURE ASSESSMENT", 1)[0]
    assert (
        answer in block
        and "USER ONLY" not in block
        and "FULL TOOL EVIDENCE" not in block
    )
    assert (
        prompt.index("COMPILED DISCLOSURE REQUIREMENTS")
        < prompt.index("ASSISTANT ANSWERS")
        < prompt.index("FULL TOOL EVIDENCE")
    )


@pytest.mark.parametrize("period,expected", [("peak", 2), ("off_peak", 1)])
def test_schedule_disclosure_applicability(period: str, expected: int) -> None:
    call = golden.Call(
        name="get_current_toll_price",
        input={},
        result={
            "components": [
                {
                    "source_kind": "schedule_derived",
                    "facility": "greenway",
                    "rate_period": period,
                }
            ]
        },
    )
    attempt = run.Attempt(
        id="schedule",
        case_id="synthetic",
        trial=1,
        turns=[golden.Turn(user="Price?", response="Published rate.", calls=[call])],
    )
    requirements = run.disclosure_requirements(attempt)
    assert len(requirements) == expected
    assert any(key.endswith("published_source") for key in requirements)
    assert any(key.endswith(".peak") for key in requirements) == (period == "peak")


def test_unavailable_annual_baseline_still_requires_vehicle_assumption() -> None:
    call = golden.Call(
        name="get_annual_toll_ballpark",
        input={},
        result={
            "sample_status": "no_complete_paired_days",
            "assumptions": {"vehicle_cost_per_mile_usd": "0.685"},
            "vehicle_cost": {"annual_usd": "500.00"},
        },
    )
    attempt = run.Attempt(
        id="baseline",
        case_id="synthetic",
        trial=1,
        turns=[golden.Turn(user="Annual?", response="No toll history.", calls=[call])],
    )
    assert list(run.disclosure_requirements(attempt)) == [
        "turn_1.call_1.vehicle_assumption"
    ]


@pytest.mark.parametrize(
    "quotes,passed",
    [
        ([], False),
        ([run.AssistantQuote(quote="68.5 cents per tolled mile")], True),
    ],
)
def test_disclosure_missing_or_supplied_in_earlier_answer(
    quotes: list[run.AssistantQuote], passed: bool
) -> None:
    turns = [
        golden.Turn(
            user="Estimate",
            response="Assuming 68.5 cents per tolled mile, using straight-line distance.",
            calls=[],
        ),
        golden.Turn(user="Thanks", response="You're welcome.", calls=[]),
    ]
    assessment = run.OutcomeAssessment(
        disclosures=[run.DisclosureAssessment(requirement_id="vehicle", quotes=quotes)],
        outcome=run.RequirementAssessment(
            evidence="Other requirements satisfied.", unmet_requirements=[]
        ),
        actor_validity=run.ActorAssessment(evidence="Consistent user.", status="valid"),
    )
    assert (
        run.disclosure_verdict(
            assessment, {"vehicle": "Disclose the assumed vehicle rate."}, turns
        ).passed
        == passed
    )


@pytest.mark.parametrize(
    "defect", ["tool_only", "fabricated", "missing_id", "duplicate_id", "unknown_id"]
)
def test_invalid_disclosure_evidence_is_a_measurement_error(defect: str) -> None:
    turn = golden.Turn(
        user="Assume $0.685 per mile",
        response="Vehicle cost is $10.",
        calls=[
            golden.Call(
                name="get_annual_toll_ballpark",
                input={},
                result={"assumption": "$0.685 per mile"},
            )
        ],
    )
    item = run.DisclosureAssessment(
        requirement_id="vehicle",
        quotes=[
            run.AssistantQuote(
                quote="FABRICATED" if defect == "fabricated" else "$0.685 per mile"
            )
        ],
    )
    disclosures = (
        []
        if defect == "missing_id"
        else [item, item]
        if defect == "duplicate_id"
        else [item]
    )
    if defect == "unknown_id":
        item.requirement_id = "not_applicable"
    assessment = run.OutcomeAssessment(
        disclosures=disclosures,
        outcome=run.RequirementAssessment(
            evidence="Claimed support.", unmet_requirements=[]
        ),
        actor_validity=run.ActorAssessment(evidence="Consistent user.", status="valid"),
    )
    with pytest.raises(ValueError, match="invalid_disclosure_"):
        run.disclosure_verdict(
            assessment, {"vehicle": "Disclose vehicle assumption."}, [turn]
        )


@pytest.mark.parametrize("locations", [[3], [1, 3]])
def test_quote_locations_are_derived_and_repeated_answers_preserved(
    locations: list[int],
) -> None:
    quote = "Vehicle cost assumes 68.5 cents per straight-line tolled mile."
    turns = [
        golden.Turn(
            user=quote,
            response=quote if index in locations else "Other answer.",
            calls=[],
        )
        for index in range(1, 4)
    ]
    assessment = run.OutcomeAssessment(
        disclosures=[
            run.DisclosureAssessment(
                requirement_id="vehicle", quotes=[run.AssistantQuote(quote=quote)]
            )
        ],
        outcome=run.RequirementAssessment(
            evidence="Other requirements satisfied.", unmet_requirements=[]
        ),
        actor_validity=run.ActorAssessment(evidence="Consistent user.", status="valid"),
    )
    verdict = run.disclosure_verdict(
        assessment, {"vehicle": "Disclose vehicle assumption."}, turns
    )
    assert verdict.passed
    assert json.loads(verdict.evidence)["disclosures"][0]["quotes"] == [
        {"quote": quote, "assistant_turns": locations}
    ]
    assert set(run.AssistantQuote.model_json_schema()["properties"]) == {"quote"}


def test_calibration_preserves_bad_quote_and_usage_then_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == golden_case(22).id and e.label == "good"
    )
    monkeypatch.setattr(run, "development_examples", lambda: [example])
    evaluator = Mock()

    def judge(
        case: golden.GoldenCase,
        attempt: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool = False,
    ) -> None:
        requirements = run.disclosure_requirements(attempt)
        assert requirements
        assessment = run.OutcomeAssessment(
            disclosures=[
                run.DisclosureAssessment(
                    requirement_id=key,
                    quotes=[run.AssistantQuote(quote="FABRICATED DISCLOSURE")],
                )
                for key in requirements
            ],
            outcome=run.RequirementAssessment(
                evidence="Raw model claims disclosure.", unmet_requirements=[]
            ),
            actor_validity=run.ActorAssessment(
                evidence="Consistent user.", status="valid"
            ),
        )
        reserve = journal.reserve(attempt, "judge", 100)
        journal.finish(
            attempt, "judge", reserve, {"inputTokens": 100, "outputTokens": 20}, 0.1
        )
        evaluator.return_value = SimpleNamespace(structured_output=assessment)
        monkeypatch.setattr(run, "Agent", Mock(return_value=evaluator))
        run.assess_outcome(
            case,
            attempt,
            Mock(spec=Model),
            "contract",
            "conversation",
            fixed_reference=fixed_reference,
        )

    monkeypatch.setattr(run, "judge", judge)
    journal = run.Journal(tmp_path / "bad-citation", 25)
    with ThreadPoolExecutor(max_workers=1) as pool:
        row = run.calibrate(journal, pool)[0]
    assert row["status"] == "infrastructure" and not row["measurement_complete"]
    assert "FABRICATED DISCLOSURE" in row["verdicts"]["outcome"]["evidence"]
    assert row["measurements"][0]["complete"] and journal.spent > 0
    assert journal.stop_requested and not journal.unknown_usage
    assert evaluator.call_count == 1
    with pytest.raises(run.StopRun):
        journal.reserve(
            run.Attempt(id="next", case_id=example.case_id, trial=1), "judge", 100
        )

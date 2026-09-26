"""Small contrasts for mechanical grading and assistant-only disclosure evidence."""

from copy import deepcopy

import pytest

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
    wrong = deepcopy(attempt.turns[0].calls[0].input)
    wrong["origin_point_id"] = "i95:999NO"
    attempt.rejected_tools = [
        golden.RejectedCall(
            turn=1,
            name=attempt.turns[0].calls[0].name,
            input=wrong,
            result={},
            reason="tool_arguments",
        )
    ]
    # Rejection in turn 1 does not consume the step needed by the later selection.
    failures = run.mechanical_rules(case, attempt)
    assert len(failures) == 1
    assert '"error": "tool_arguments"' in failures[0].evidence
    assert "i95:999NO" in failures[0].evidence


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
        ([run.AssistantQuote(turn=1, quote="68.5 cents per tolled mile")], True),
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
    "defect", ["tool_only", "wrong_turn", "missing_id", "duplicate_id", "unknown_id"]
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
                turn=2 if defect == "wrong_turn" else 1, quote="$0.685 per mile"
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

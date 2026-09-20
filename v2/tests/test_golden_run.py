"""Execution and reporting checks without credentials or model calls."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from strands.models import Model
from strands_evals.types.evaluation import EvaluationData

from eval import golden
from eval import golden_run as run


def measurement() -> run.Measurement:
    return run.Measurement(
        role="agent",
        input_tokens=100,
        output_tokens=20,
        cached_tokens=0,
        written_tokens=0,
        seconds=1.0,
        cost_usd=0.01,
        complete=True,
    )


def attempt(case: golden.GoldenCase, number: int) -> run.Attempt:
    return run.Attempt(
        id=f"{case.id}-{number}",
        case_id=case.id,
        trial=number,
        status="scored",
        measurements=[measurement()],
        verdicts={
            k: run.Verdict(passed=True, evidence="turn 1 supported")
            for k in ("outcome", "grounding", "rules")
        },
    )


def test_aggregate_repeats_cost_failures_and_incomplete() -> None:
    cases = golden.load_cases()[:2]
    rows = [attempt(c, n) for c in cases for n in (1, 2, 3)]
    rows[-1].checks = ["tool_arguments"]
    result = run.summary(rows, cases)
    assert result["successful_trials"] == 5
    assert result["outcome_successful_trials"] == 6
    assert result["pass_cubed"] == 0.5
    assert result["agent_cost_per_success_usd"] == pytest.approx(0.06 / 5)
    assert result["complete"]
    rows[-1].status = "infrastructure"
    assert not run.summary(rows, cases)["complete"]
    assert run.summary(rows, cases)["success_ci95"] is None
    for row in rows:
        row.checks = ["unsupported_money"]
    assert run.summary(rows, cases)["agent_cost_per_success_usd"] is None
    with pytest.raises(ValueError, match="duplicate"):
        run.summary(rows + rows[:1], cases)
    rows[0].measurements = []
    assert not rows[0].passed


def test_development_only_and_full_trajectory() -> None:
    examples = run.development_examples()
    assert len(examples) == 34
    held = {c.id for c in golden.load_cases() if c.held_out}
    assert not held.intersection(e.case_id for e in examples)
    example = next(e for e in examples if e.case_id == "greenway-origin-correction")
    case = golden.load_cases()[1]
    judge = golden.make_judge(Mock(spec=Model))
    data = EvaluationData[str, str](
        input=case.prompt,
        actual_output=example.turns[-1].response,
        actual_trajectory=run.trajectory(case, example.turns),
        expected_assertion=case.expected_assertion,
    )
    parsed = judge._get_last_turn(data)  # pyright: ignore[reportPrivateUsage]
    prompt = judge._format_reference_prompt(parsed, data)  # pyright: ignore[reportPrivateUsage]
    assert "Battlefield" in prompt and "Leesburg" in prompt and "5.80" in prompt


def test_real_tool_adapter_replays_without_live_calls() -> None:
    case = golden.load_cases()[0]
    fixture = golden.load_fixture(case.steps[0].fixture)
    first = run.Attempt(
        id="first",
        case_id=case.id,
        trial=1,
        turns=[golden.Turn(user=case.prompt, response="pending", calls=[])],
    )
    second = first.model_copy(deep=True)
    first_tools = run.replay_tools(case, first, [case.prompt])
    second_tools = run.replay_tools(case, second, [case.prompt])
    assert first_tools[0].tool_spec == golden.current.TOOL_SPEC

    async def collect(adapter: Any) -> list[Any]:  # noqa: ANN401
        return [
            event
            async for event in adapter.stream(
                {"toolUseId": "test", "name": fixture.tool, "input": fixture.input},
                {"agent": Mock()},
            )
        ]

    asyncio.run(collect(first_tools[0]))
    assert first.turns[0].calls[0].result == fixture.result
    assert not second.turns[0].calls
    asyncio.run(collect(first_tools[0]))
    assert "tool_budget" in first.checks
    asyncio.run(collect(second_tools[0]))
    assert not second.checks


def test_usage_meter_and_budget_stop(tmp_path: Path) -> None:
    case = golden.load_cases()[0]
    row = run.Attempt(id="a", case_id=case.id, trial=1)
    native = Mock(spec=Model)
    native.client_args = {}

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[dict[str, Any]]:
        yield {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 20}}}

    native.stream = stream
    journal = run.Journal(tmp_path / "run", 25)
    model = journal.model(native, "agent", row, 1)

    async def consume() -> None:
        async for _ in cast(Any, model).stream([]):
            pass

    asyncio.run(consume())
    assert row.measurements[0].cost_usd == pytest.approx(0.000044)
    assert journal.spent == row.measurements[0].cost_usd
    with pytest.raises(run.TaskFailure):
        asyncio.run(consume())
    assert len(row.measurements) == 1
    assert run.cost(
        {
            "inputTokens": 100,
            "outputTokens": 20,
            "cacheReadInputTokens": 50,
            "cacheWriteInputTokens": 30,
        }
    ) == pytest.approx(0.0000365)


def test_incomplete_report_retains_interrupted_measurements(tmp_path: Path) -> None:
    case = golden.load_cases()[0]
    journal = run.Journal(tmp_path / "run", 25)
    row = run.Attempt(id="a", case_id=case.id, trial=1)
    journal.append({"event": "attempt_started", **row.model_dump()})
    journal.append(
        {"event": "model_finished", "attempt": "a", **measurement().model_dump()}
    )
    (journal.directory / "manifest.json").write_text(
        json.dumps(
            {
                "mode": "run",
                "identity": {"commit": "test", "cases": [case.model_dump(mode="json")]},
            }
        )
    )
    report = run.render(journal.directory)
    assert not report["overall"]["complete"]
    assert report["overall"]["cost_usd"]["agent"] == 0.01
    assert report["release_decision"] == "not_provided"
    assert report["attempts"][0]["error"] == "interrupted"

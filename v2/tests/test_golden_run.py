"""Execution and reporting checks without credentials or model calls."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from strands.models import Model
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

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
        turns=[golden.Turn(user=case.prompt, response="A supported answer.", calls=[])],
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
    whole = run.ConversationJudge(model=Mock(spec=Model))
    data.actual_output = json.dumps([t.model_dump() for t in example.turns])
    prompt = whole._format_reference_prompt(parsed, data)  # pyright: ignore[reportPrivateUsage]
    assert "COMPLETE ORDERED CONVERSATION" in prompt
    assert example.turns[0].response in prompt
    assert example.turns[1].response in prompt
    assert "AGENT RESPONSE:" not in prompt


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


def test_incomplete_report_retains_interrupted_measurements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = golden.load_cases()[0]
    journal = run.Journal(tmp_path / "run", 25)
    row = run.Attempt(id="a", case_id=case.id, trial=1)
    journal.append({"event": "attempt_started", **row.model_dump()})
    journal.append(
        {"event": "model_finished", "attempt": "a", **measurement().model_dump()}
    )
    original_git = run.git

    def clean_git(*args: str) -> str:
        return "" if args[0] == "status" else original_git(*args)

    monkeypatch.setattr(run, "git", clean_git)
    (journal.directory / "manifest.json").write_text(
        json.dumps(
            {
                "mode": "run",
                "identity": run.identity([case]),
            }
        )
    )
    report = run.render(journal.directory)
    assert not report["overall"]["complete"]
    assert report["overall"]["cost_usd"]["agent"] == 0.01
    assert report["release_decision"] == "not_provided"
    assert report["attempts"][0]["error"] == "interrupted"
    assert not report["full_corpus_complete"]
    bad = report["manifest"]["identity"]
    del bad["prompt_hashes"]
    with pytest.raises(ValueError, match="missing run identity"):
        run.validate_identity(bad)


def test_missing_usage_stops_future_calls_without_storing_exception(
    tmp_path: Path,
) -> None:
    native = Mock(spec=Model)
    native.client_args = {}

    async def broken(*args: object, **kwargs: object) -> AsyncIterator[dict[str, Any]]:
        yield {"messageStart": {"role": "assistant"}}
        raise RuntimeError("secret-token-must-not-be-recorded")

    native.stream = broken
    row = run.Attempt(id="broken", case_id="greenway-current", trial=1)
    journal = run.Journal(tmp_path / "broken", 25)
    model = journal.model(native, "agent", row, 4)

    async def consume() -> None:
        async for _ in cast(Any, model).stream([]):
            pass

    with pytest.raises(RuntimeError):
        asyncio.run(consume())
    with pytest.raises(run.StopRun):
        asyncio.run(consume())
    assert journal.unknown_usage
    assert not row.measurements[0].complete
    assert "secret-token" not in (journal.directory / "events.jsonl").read_text()


def test_real_agent_keeps_conversation_and_uses_only_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from strands.models.openai_responses import OpenAIResponsesModel

    case = golden.load_cases()[1]
    row = run.Attempt(id="multi", case_id=case.id, trial=1)
    messages: list[str] = []
    seen: list[int] = []
    model = OpenAIResponsesModel(model_id="offline", client_args={"api_key": "offline"})

    async def scripted(
        history: list[Any], *args: object, **kwargs: object
    ) -> AsyncIterator[dict[str, Any]]:
        seen.append(len(history))
        yield {"messageStart": {"role": "assistant"}}
        if len(seen) % 2:
            fixture = golden.load_fixture(case.steps[(len(seen) - 1) // 2].fixture)
            yield {
                "contentBlockStart": {
                    "start": {
                        "toolUse": {"toolUseId": str(len(seen)), "name": fixture.tool}
                    }
                }
            }
            yield {
                "contentBlockDelta": {
                    "delta": {"toolUse": {"input": json.dumps(fixture.input)}}
                }
            }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": "$5.80 fixed toll."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "metrics": {"latencyMs": 1},
            }
        }

    cast(Any, model).stream = scripted
    monkeypatch.setattr(
        run.toll_agent, "load_prompt_points", lambda: pytest.fail("live prompt points")
    )
    agent = run.toll_agent.build_agent(
        model=model,
        tools=run.replay_tools(case, row, messages),
        current_date=case.frozen_time.date(),
        prompt_points=json.loads((golden.ROOT / "prompt-points.json").read_text()),
        hooks=[run.RequestGuard(case, row)],
    )
    for message in (case.prompt, "Sorry, I meant Battlefield Parkway. Still Route 28."):
        messages.append(message)
        row.turns.append(golden.Turn(user=message, response="pending", calls=[]))
        row.turns[-1].response = str(agent(message))
    assert len(row.turns) == 2 and len(row.requested_tools) == 2
    assert seen == sorted(seen) and seen[-1] > seen[0]
    assert not golden.grade_assertions(case, row.turns)


def test_repeating_agent_is_scored_failure_not_infrastructure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strands.models.openai_responses import OpenAIResponsesModel

    case = golden.load_cases()[0]
    fixture = golden.load_fixture(case.steps[0].fixture)
    model = OpenAIResponsesModel(model_id="offline", client_args={"api_key": "offline"})
    count = 0

    async def repeating(
        *args: object, **kwargs: object
    ) -> AsyncIterator[dict[str, Any]]:
        nonlocal count
        count += 1
        yield {"messageStart": {"role": "assistant"}}
        yield {
            "contentBlockStart": {
                "start": {"toolUse": {"toolUseId": str(count), "name": fixture.tool}}
            }
        }
        yield {
            "contentBlockDelta": {
                "delta": {"toolUse": {"input": json.dumps(fixture.input)}}
            }
        }
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "metrics": {"latencyMs": 1},
            }
        }

    cast(Any, model).stream = repeating
    monkeypatch.setattr(run.toll_agent, "_build_model", lambda: model)
    monkeypatch.setattr(
        run,
        "build_eval_model",
        lambda: OpenAIResponsesModel(
            model_id="offline", client_args={"api_key": "offline"}
        ),
    )
    monkeypatch.setattr(golden, "make_actor", Mock())

    def reject(
        case: golden.GoldenCase, attempt: run.Attempt, journal: run.Journal
    ) -> None:
        attempt.verdicts = {
            key: run.Verdict(passed=False, evidence="Repeated tool call")
            for key in ("outcome", "grounding", "rules")
        }

    monkeypatch.setattr(run, "judge", reject)
    result = run.execute(case, 1, run.Journal(tmp_path / "loop", 25))
    assert result.status == "scored" and result.failure_class == "budget"
    assert "tool_budget" in result.checks
    assert len(result.requested_tools) == 2
    assert count == 2 and not result.passed


def test_judge_receives_permitted_discovery_and_selection_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strands.models.openai_responses import OpenAIResponsesModel

    seen: list[str] = []

    def evaluate(
        self: run.ConversationJudge, data: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        assert data.expected_assertion is not None
        seen.append(data.expected_assertion)
        return [EvaluationOutput(score=1.0, test_pass=True, reason="offline evidence")]

    monkeypatch.setattr(run.ConversationJudge, "evaluate", evaluate)
    monkeypatch.setattr(
        run,
        "build_eval_model",
        lambda: OpenAIResponsesModel(
            model_id="offline", client_args={"api_key": "offline"}
        ),
    )
    journal = run.Journal(tmp_path / "contract", 25)
    case = golden.load_cases()[21]
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    row = run.Attempt(id="contract", case_id=case.id, trial=1, turns=example.turns)
    run.judge(case, row, journal)
    assert all(run.DOMAIN_FACTS in reference for reference in seen)
    assert "Optional tool calls are not required" in seen[0]
    assert "Permitted tool sequence" not in seen[1]
    for reference in (seen[0], seen[2]):
        assert '"earliest_assistant_turn": 1' in reference
        assert '"earliest_assistant_turn": 2' in reference
        assert '"origin_point_id": "i95:205SD"' in reference
        assert '"origin_point_id": "i95:212NO"' in reference
    seen.clear()
    case = golden.load_cases()[3]
    run.judge(case, row, journal)
    assert "claim-support requirement" in seen[0]
    assert "Ground the price, time, availability" not in seen[0]

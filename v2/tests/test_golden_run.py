"""Execution and reporting checks without credentials or model calls."""

import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from strands.models import Model
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

from eval import golden
from eval import golden_run as run


@pytest.mark.parametrize("mode", ["calibrate", "run"])
def test_cli_runs_independent_work_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    barrier = Barrier(3, timeout=5)
    directory = tmp_path / mode
    calibration = tmp_path / "approved-calibration"
    pinned = dict.fromkeys(
        (
            "corpus",
            "judge_prompt_sha256",
            "diagnostic_prompt",
            "diagnostic_rubrics",
            "diagnostic_domain_facts",
            "model",
            "reasoning_effort",
            "max_output_tokens",
            "transport",
        ),
        "offline",
    )
    monkeypatch.setattr(run, "identity", Mock(return_value=pinned))
    monkeypatch.setattr(
        run,
        "render",
        Mock(
            return_value={
                "complete": True,
                "review": {"status": "approved"},
                "manifest": {"identity": pinned, "run_id": "offline"},
                "evidence_sha256": "0" * 64,
            }
        ),
    )
    examples = run.development_examples()[:3]
    monkeypatch.setattr(run, "development_examples", lambda: examples)

    def judge(case: golden.GoldenCase, row: run.Attempt, journal: run.Journal) -> None:
        barrier.wait()
        row.verdicts = {
            key: run.Verdict(passed=True, evidence="offline")
            for key in ("outcome", "grounding", "rules")
        }
        row.measurements.append(measurement())

    def execute(
        case: golden.GoldenCase, number: int, journal: run.Journal
    ) -> run.Attempt:
        row = attempt(case, number)
        journal.append({"event": "attempt_started", **row.model_dump()})
        barrier.wait()
        journal.append({"event": "attempt_finished", **row.model_dump()})
        return row

    monkeypatch.setattr(run, "judge", judge)
    monkeypatch.setattr(run, "execute", execute)
    args = ["golden_run", mode, "--output", str(directory), "--workers", "3"]
    if mode == "run":
        args += [
            "--calibration",
            str(calibration),
            "--cases",
            golden.load_cases()[0].id,
        ]
    monkeypatch.setattr("sys.argv", args)
    run.main()
    assert json.loads((directory / "manifest.json").read_text())["workers"] == 3
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
    ]
    rows = [
        event
        for event in events
        if event["event"] in ("calibration", "attempt_finished")
    ]
    assert len(rows) == 3 and len({row["id"] for row in rows}) == 3
    assert all(row["status"] == "scored" for row in rows)
    assert len([event for event in events if event["event"] == "attempt_started"]) == 3


def test_parallel_calls_reserve_shared_budget_before_provider_calls(
    tmp_path: Path,
) -> None:
    journal = run.Journal(tmp_path / "budget", 0.02)
    release = Event()

    def invoke(number: int, invalid_usage: bool = False) -> bool:
        native = Mock(spec=Model)
        native.client_args = {}

        async def stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[dict[str, Any]]:
            assert release.wait(timeout=5)
            yield {
                "metadata": {
                    "usage": {
                        "inputTokens": -1 if invalid_usage else 100,
                        "outputTokens": 20,
                    }
                }
            }

        native.stream = stream
        row = run.Attempt(id=str(number), case_id="greenway-current", trial=1)
        model = journal.model(native, "agent", row, 1)

        async def consume() -> bool:
            try:
                async for _ in cast(Any, model).stream([]):
                    pass
                return True
            except run.StopRun:
                return False

        return asyncio.run(consume())

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(invoke, number) for number in (1, 2, 3)]
        try:
            # Two reservations fit, but a third must stop before any call finishes.
            assert next(as_completed(futures, timeout=5)).result() is False
            with journal.lock:
                assert journal.spent == 0 and 0 < journal.reserved <= journal.limit
        finally:
            release.set()
        assert sum(f.result() for f in futures) == 2
    assert journal.reserved == pytest.approx(0)
    assert journal.spent == pytest.approx(2 * 0.000044)
    assert not journal.unknown_usage
    events = [
        json.loads(line)
        for line in (journal.directory / "events.jsonl").read_text().splitlines()
    ]
    assert sum(e["event"] == "model_started" for e in events) == 2
    assert sum(e["event"] == "model_finished" for e in events) == 2
    assert invoke(4, invalid_usage=True)
    assert journal.unknown_usage and journal.reserved == pytest.approx(0)
    assert not invoke(5)


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
    assert len(examples) == 60
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


@pytest.mark.parametrize("role", ["agent", "actor", "judge"])
def test_real_sdk_transport_has_no_retries_and_bounded_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    import httpx
    import openai

    from eval import simulated

    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", lambda: "offline")
    monkeypatch.setattr(simulated, "load_openai_api_key", lambda: "offline")
    native = (
        run.toll_agent._build_model() if role == "agent" else run.build_eval_model()
    )
    requests: list[httpx.Request] = []
    clients: list[openai.AsyncOpenAI] = []
    original = openai.AsyncOpenAI

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "offline failure"}})

    def client(**kwargs: Any) -> openai.AsyncOpenAI:  # noqa: ANN401
        assert kwargs["max_retries"] == 0 and kwargs["timeout"] == 60
        kwargs["http_client"] = httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        )
        result = original(**kwargs)
        assert result.max_retries == 0 and result.timeout == 60
        clients.append(result)
        return result

    monkeypatch.setattr(openai, "AsyncOpenAI", client)
    row = run.Attempt(id="transport", case_id="greenway-current", trial=1)
    journal = run.Journal(tmp_path / role, 25)
    model = journal.model(native, cast(Any, role), row, 4)

    async def consume() -> None:
        async for _ in cast(Any, model).stream(
            [{"role": "user", "content": [{"text": "offline test"}]}]
        ):
            pass

    with pytest.raises(openai.InternalServerError):
        asyncio.run(consume())
    with pytest.raises(run.StopRun):
        asyncio.run(consume())
    assert len(clients) == len(requests) == len(row.measurements) == 1
    assert journal.unknown_usage and not row.measurements[0].complete


def test_real_agent_keeps_conversation_and_uses_only_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from strands.models.openai_responses import OpenAIResponsesModel

    monkeypatch.setattr(
        run.toll_agent, "load_prompt_points", lambda: pytest.fail("live prompt points")
    )
    barrier = Barrier(2, timeout=5)

    def conversation(number: int) -> tuple[run.Attempt, list[int]]:
        case = golden.load_cases()[1]
        row = run.Attempt(id=f"multi-{number}", case_id=case.id, trial=1)
        messages: list[str] = []
        seen: list[int] = []
        model = OpenAIResponsesModel(
            model_id="offline", client_args={"api_key": "offline"}
        )

        async def scripted(
            history: list[Any], *args: object, **kwargs: object
        ) -> AsyncIterator[dict[str, Any]]:
            seen.append(len(history))
            if len(seen) == 1:
                barrier.wait()
            yield {"messageStart": {"role": "assistant"}}
            if len(seen) % 2:
                fixture = golden.load_fixture(case.steps[(len(seen) - 1) // 2].fixture)
                yield {
                    "contentBlockStart": {
                        "start": {
                            "toolUse": {
                                "toolUseId": str(len(seen)),
                                "name": fixture.tool,
                            }
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
                    "usage": {
                        "inputTokens": 100,
                        "outputTokens": 20,
                        "totalTokens": 120,
                    },
                    "metrics": {"latencyMs": 1},
                }
            }

        cast(Any, model).stream = scripted
        agent = run.toll_agent.build_agent(
            model=model,
            tools=run.replay_tools(case, row, messages),
            current_date=case.frozen_time.date(),
            prompt_points=json.loads((golden.ROOT / "prompt-points.json").read_text()),
            hooks=[run.RequestGuard(case, row)],
        )
        for message in (
            case.prompt,
            "Sorry, I meant Battlefield Parkway. Still Route 28.",
        ):
            messages.append(message)
            row.turns.append(golden.Turn(user=message, response="pending", calls=[]))
            row.turns[-1].response = str(agent(message))
        return row, seen

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(conversation, (1, 2)))
    assert results[0][0].id != results[1][0].id
    for row, seen in results:
        assert len(row.turns) == 2 and len(row.requested_tools) == 2
        assert seen == sorted(seen) and seen[-1] > seen[0]
        assert not golden.grade_assertions(golden.load_cases()[1], row.turns)
    results[0][0].turns[0].calls[0].result["total_usd"] = "999.00"
    assert results[1][0].turns[0].calls[0].result["total_usd"] == "5.80"


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
        seen.append(self.reference_system_prompt + "\n" + data.expected_assertion)
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
    assert "Do not require an official operator" in seen[0]
    assert "Optional tool calls are not required" in seen[0]
    assert "Permitted tool sequence" not in seen[1]
    for reference in (seen[0], seen[2]):
        assert (
            "original-route call is permitted before any alternative selection"
            in reference
        )
        assert (
            "Calling that replacement route before the user chooses still fails"
            in reference
        )
        assert '"earliest_assistant_turn": 1' in reference
        assert '"earliest_assistant_turn": 2' in reference
        assert '"origin_point_id": "i95:205SD"' in reference
        assert '"origin_point_id": "i95:212NO"' in reference
    seen.clear()
    case = golden.load_cases()[3]
    run.judge(case, row, journal)
    assert "claim-support requirement" in seen[0]
    assert "Ground the price, time, availability" not in seen[0]


@pytest.mark.parametrize(
    "stop,message,reason,error",
    [
        (True, "Use $120,000.", "goal_completed", "actor_stop_with_message"),
        (False, None, None, "actor_missing_reply"),
        (False, "   ", None, "actor_missing_reply"),
        (True, None, "max_turns", "actor_turn_limit"),
    ],
)
def test_invalid_actor_output_is_inconclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop: bool,
    message: str | None,
    reason: str | None,
    error: str,
) -> None:
    from strands_evals.types.simulation import ActorResponse

    from eval.artifact_agent import Answer

    case = golden.load_cases()[14]
    reply = ActorResponse(
        reasoning="offline", stop=stop, message=message, stop_reason=reason
    )
    actor = Mock()
    actor.act.return_value.structured_output = reply
    monkeypatch.setattr(golden, "make_actor", Mock(return_value=actor))
    monkeypatch.setattr(run, "build_eval_model", lambda: Mock(client_args={}))
    judge = Mock()
    monkeypatch.setattr(run, "judge", judge)
    agent = Mock()
    answer = Answer("Which income should I use?")
    answer.stop_reason = "end_turn"
    agent.return_value = answer
    result = run.execute(
        case, 1, run.Journal(tmp_path / "actor", 25), Mock(return_value=agent)
    )
    assert result.status == "infrastructure" and result.error == error
    assert result.failure_class == "actor_validity" and not result.passed
    assert result.actor_replies[0]["message"] == message
    judge.assert_not_called()


def test_actor_reply_is_delivered_before_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from strands_evals.types.simulation import ActorResponse

    from eval.artifact_agent import Answer

    case = golden.load_cases()[14]
    actor = Mock()
    actor.act.side_effect = [
        Mock(
            structured_output=ActorResponse(
                reasoning="offline",
                stop=False,
                message="Use $120,000.",
                stop_reason=None,
            )
        ),
        Mock(
            structured_output=ActorResponse(
                reasoning="offline",
                stop=True,
                message=None,
                stop_reason="goal_completed",
            )
        ),
    ]
    monkeypatch.setattr(golden, "make_actor", Mock(return_value=actor))
    monkeypatch.setattr(run, "build_eval_model", lambda: Mock(client_args={}))

    def judge(case: golden.GoldenCase, row: run.Attempt, journal: run.Journal) -> None:
        row.verdicts = {
            key: run.Verdict(passed=True, evidence="offline")
            for key in ("outcome", "grounding", "rules")
        }
        row.measurements.append(measurement())

    monkeypatch.setattr(run, "judge", judge)
    agent = Mock()
    answer = Answer("Answer")
    answer.stop_reason = "end_turn"
    agent.return_value = answer
    result = run.execute(
        case, 1, run.Journal(tmp_path / "delivered", 25), Mock(return_value=agent)
    )
    assert [call.args[0] for call in agent.call_args_list] == [
        case.prompt,
        "Use $120,000.",
    ]
    assert len(result.turns) == 2
    assert result.error is None


def test_judges_receive_rejected_calls_without_pricing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[dict[str, Any]]] = []
    prompts: list[str] = []

    def evaluate(
        self: run.ConversationJudge, data: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        seen.append(json.loads(data.actual_output or "[]"))
        prompts.append(self.reference_system_prompt)
        return [EvaluationOutput(score=0.0, test_pass=False, reason="offline")]

    monkeypatch.setattr(run.ConversationJudge, "evaluate", evaluate)
    native = Mock(client_args={})
    monkeypatch.setattr(run, "build_eval_model", lambda: native)
    example = next(
        e for e in run.development_examples() if e.label == "rejected-call-honest"
    )
    case = next(c for c in golden.load_cases() if c.id == example.case_id)
    attempt = run.Attempt(
        id="rejection",
        case_id=case.id,
        trial=1,
        turns=example.turns,
        rejected_tools=example.rejected_tools,
    )
    run.judge(case, attempt, run.Journal(tmp_path / "judge", 25))
    native.update_config.assert_called_once_with(
        params={**run.EVAL_MODEL_PARAMS, "reasoning": {"effort": "medium"}}
    )
    assert len(seen) == 3
    assert "GROUNDING ONLY" in prompts[1] and "RULES ONLY" not in prompts[1]
    assert "RULES ONLY" in prompts[2] and "GROUNDING ONLY" not in prompts[2]
    for transcript in seen:
        assert transcript[0]["calls"] == []
        assert transcript[0]["rejected_calls"][0]["result"]["status"] == "error"
        assert (
            transcript[0]["rejected_calls"][0]["input"]["destination_point_id"]
            == "greenway:28:entry:WB"
        )


@pytest.mark.parametrize("role", ["actor", "judge", "agent"])
def test_only_evaluators_force_structured_output(tmp_path: Path, role: str) -> None:
    native = Mock(spec=Model)
    native.client_args = {}
    seen: list[dict[str, Any]] = []

    async def stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:  # noqa: ANN401
        seen.append(kwargs)
        yield {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 20}}}

    native.stream = stream
    row = run.Attempt(id="format", case_id="greenway-current", trial=1)
    model = run.Journal(tmp_path / role, 25).model(native, cast(Any, role), row, 1)

    async def consume() -> None:
        async for _ in cast(Any, model).stream([], tool_choice=None):
            pass

    asyncio.run(consume())
    assert seen[0]["tool_choice"] == (None if role == "agent" else {"any": {}})


def test_packaged_replay_records_rejections() -> None:
    from eval.artifact_agent import Answer, ArtifactAgent

    case = golden.load_cases()[0]
    fixture = golden.load_fixture(case.steps[0].fixture)
    arguments = dict(fixture.input, destination_point_id="greenway:28:entry:WB")
    attempt = run.Attempt(
        id="packaged",
        case_id=case.id,
        trial=1,
        turns=[golden.Turn(user=case.prompt, response="pending", calls=[])],
    )
    adapter = object.__new__(ArtifactAgent)
    adapter.case, adapter.attempt, adapter.journal = case, attempt, Mock()
    adapter.messages, adapter.replay, adapter.reserved = (
        [case.prompt],
        golden.Replay(case),
        None,
    )
    adapter.send = Mock()
    adapter.receive = Mock(
        side_effect=[
            {"event": "requested", "name": fixture.tool, "input": arguments},
            {"event": "tool", "name": fixture.tool, "input": arguments},
            {"event": "answer", "text": "Rejected.", "stop_reason": "end_turn"},
        ]
    )
    assert isinstance(adapter(case.prompt), Answer)
    assert not attempt.turns[0].calls
    assert attempt.rejected_tools[0].reason == "tool_arguments"
    assert (
        attempt.rejected_tools[0].result
        == adapter.send.call_args_list[-1].args[0]["result"]
    )


def test_eval_cache_prefix_and_write_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", lambda: "offline")
    requests: list[dict[str, Any]] = []

    def evaluate(
        self: run.ConversationJudge, data: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        model = cast(Any, self.model)
        request = model._format_request(
            [{"role": "user", "content": [{"text": data.actual_output}]}],
            system_prompt=self.reference_system_prompt,
        )
        requests.append(request)
        assert request["reasoning"] == {"effort": "medium"}
        assert request["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
        assert request["prompt_cache_key"] == "tollchat-eval-v2"
        assert request["store"] is False
        assert "instructions" not in request
        prefix = request["input"][0]
        assert prefix["role"] == "developer"
        assert prefix["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
        assert run.DOMAIN_FACTS in prefix["content"][0]["text"]
        assert run.DOMAIN_FACTS not in (data.expected_assertion or "")
        return [EvaluationOutput(score=1.0, test_pass=True, reason="offline")]

    monkeypatch.setattr(run.ConversationJudge, "evaluate", evaluate)
    journal = run.Journal(tmp_path / "cache", 25)
    for case in golden.load_cases()[:2]:
        example = next(
            e
            for e in run.development_examples()
            if e.case_id == case.id and e.label == "good"
        )
        row = run.Attempt(id=case.id, case_id=case.id, trial=1, turns=example.turns)
        run.judge(case, row, journal)
    assert len(requests) == 6  # No verdict memoization.
    for first, second in zip(requests[:3], requests[3:], strict=True):
        assert first["input"][0] == second["input"][0]
        assert first["input"][1:] != second["input"][1:]

    model = cast(Any, run.build_eval_model())
    for written in (None, 0, 30):
        details = SimpleNamespace(cached_tokens=50, cache_write_tokens=written)
        chunk = model._format_chunk(
            {
                "chunk_type": "metadata",
                "data": SimpleNamespace(
                    input_tokens=100,
                    output_tokens=10,
                    total_tokens=110,
                    input_tokens_details=details,
                ),
            }
        )
        usage = chunk["metadata"]["usage"]
        assert usage.get("cacheWriteInputTokens", 0) == (written or 0)
        assert usage["cacheReadInputTokens"] == 50
        expected = (
            (50 - (written or 0)) * 0.20 + 50 * 0.02 + (written or 0) * 0.25 + 10 * 1.20
        ) / 1_000_000
        assert run.cost(usage) == pytest.approx(expected)


@pytest.mark.parametrize("changed", ["judge_prompt_sha256", "transport"])
def test_cli_rejects_changed_cache_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    keys = (
        "corpus",
        "judge_prompt_sha256",
        "diagnostic_prompt",
        "diagnostic_rubrics",
        "diagnostic_domain_facts",
        "model",
        "reasoning_effort",
        "max_output_tokens",
        "transport",
    )
    pinned = dict.fromkeys(keys, "current")
    previous = {**pinned, changed: "old"}
    monkeypatch.setattr(run, "identity", Mock(return_value=pinned))
    monkeypatch.setattr(
        run,
        "render",
        Mock(
            return_value={
                "complete": True,
                "review": {"status": "approved"},
                "manifest": {"identity": previous},
            }
        ),
    )
    output = tmp_path / "must-not-start"
    monkeypatch.setattr(
        "sys.argv",
        [
            "golden_run",
            "run",
            "--output",
            str(output),
            "--calibration",
            str(tmp_path / "old"),
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        run.main()
    assert not output.exists()


def test_cache_adapter_change_invalidates_calibration_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_git = run.git

    def clean_git(*args: str) -> str:
        return "" if args[0] == "status" else original_git(*args)

    monkeypatch.setattr(run, "git", clean_git)
    before = run.identity(golden.load_cases())
    source = run.inspect.getsource(run.toll_agent._CachedResponsesModel)
    monkeypatch.setattr(
        run.inspect, "getsource", Mock(return_value=source + "\n# adapter changed")
    )
    after = run.identity(golden.load_cases())
    assert (
        before["transport"]["cache_adapter_sha256"]
        != after["transport"]["cache_adapter_sha256"]
    )
    assert before["corpus"] == after["corpus"]


def test_wrong_route_calibration_is_consistent_but_unsuccessful() -> None:
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == "greenway-current" and e.label == "wrong-route"
    )
    turn = example.turns[0]
    call = turn.calls[0]
    assert "Route 28" in turn.user
    assert "Route 7" in turn.response and "Route 28" not in turn.response
    assert call.input["destination_point_id"] == "greenway:7:exit:EB"
    assert call.result["destination_point_id"] == call.input["destination_point_id"]
    assert example.semantic_verdict == "INCORRECT"
    assert example.label not in run.BAD_GROUNDING
    assert example.label in run.BAD_RULES

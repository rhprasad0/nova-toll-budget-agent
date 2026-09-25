"""Execution and reporting checks without credentials or model calls."""

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from pydantic import JsonValue
from strands.models import Model
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

from eval import golden
from eval import golden_run as run
from tests.golden_support import case as golden_case

pytestmark = pytest.mark.usefixtures("golden_test_data")


@pytest.mark.parametrize("mode", ["calibrate", "run"])
@pytest.mark.parametrize("workers", [3, 16])
def test_cli_runs_independent_work_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, workers: int
) -> None:
    root = tmp_path / "corpus"
    shutil.copytree(golden.ROOT, root)
    (root / "review.json").write_text(json.dumps({"status": "approved"}))
    monkeypatch.setattr(golden, "ROOT", root)
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

    def judge(
        case: golden.GoldenCase,
        row: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool = False,
    ) -> None:
        barrier.wait()
        row.verdicts = {
            key: run.Verdict(passed=True, evidence="offline")
            for key in ("outcome", "grounding", "rules")
        }
        row.measurements.append(measurement())
        row.actor_validity = run.ActorAssessment(status="valid", evidence="offline")

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
    args = ["golden_run", mode, "--output", str(directory), "--workers", str(workers)]
    if mode == "run":
        args += [
            "--calibration",
            str(calibration),
            "--cases",
            golden_case(1).id,
        ]
    monkeypatch.setattr("sys.argv", args)
    run.main()
    assert json.loads((directory / "manifest.json").read_text())["workers"] == workers
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
    journal = run.Journal(tmp_path / "budget", 0.009)
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
    assert journal.spent == pytest.approx(2 * 0.000020)
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
        actor_validity=run.ActorAssessment(status="valid", evidence="offline"),
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
    assert examples
    held = {c.id for c in golden.load_cases() if c.held_out}
    assert not held.intersection(e.case_id for e in examples)
    example = next(e for e in examples if e.case_id == "greenway-origin-correction")
    case = golden_case(2)
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
    assert json.dumps(example.turns[0].response) in prompt
    assert json.dumps(example.turns[1].response) in prompt
    assert "AGENT RESPONSE:" not in prompt


def test_real_tool_adapter_replays_without_live_calls() -> None:
    case = golden_case(1)
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
    case = golden_case(1)
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
    assert row.measurements[0].cost_usd == pytest.approx(0.000020)
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
    ) == pytest.approx(0.00001625)


def test_incomplete_report_retains_interrupted_measurements(
    golden_test_identity: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = golden_case(1)
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
    assert bad["tool_description_policy"] == golden.TOOL_DESCRIPTION_POLICY
    policy = bad.pop("tool_description_policy")
    with pytest.raises(ValueError, match="missing tool description policy"):
        run.validate_identity(bad)
    bad["tool_description_policy"] = policy
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
        case = golden_case(2)
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
        assert not golden.grade_assertions(golden_case(2), row.turns)
    results[0][0].turns[0].calls[0].result["total_usd"] = "999.00"
    assert results[1][0].turns[0].calls[0].result["total_usd"] == "5.80"


def test_repeating_agent_is_scored_failure_not_infrastructure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strands.models.openai_responses import OpenAIResponsesModel

    case = golden_case(1)
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
        attempt.actor_validity = run.ActorAssessment(status="valid", evidence="offline")
        attempt.verdicts = {
            key: run.Verdict(passed=False, evidence="Repeated tool call")
            for key in ("outcome", "grounding", "rules")
        }

    monkeypatch.setattr(run, "judge", reject)
    result = run.execute(case, 1, run.Journal(tmp_path / "loop", 25))
    assert result.status == "scored" and result.failure_class == "budget"
    assert "tool_budget" in result.checks
    assert result.application_stop == "tool_budget"
    cast(Mock, golden.make_actor).return_value.act.assert_not_called()
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
    case = golden_case(22).model_copy(update={"contract_version": 1})
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    row = run.Attempt(id="contract", case_id=case.id, trial=1, turns=example.turns)
    run.judge(case, row, journal)
    assert all(run.DOMAIN_FACTS in reference for reference in seen)
    assert all(golden.JUDGING_POLICY in reference for reference in seen)
    assert "truthful statements of this scope and policy are supported" in seen[1]
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
    case = golden_case(4).model_copy(update={"contract_version": 1})
    run.judge(case, row, journal)
    assert "claim-support requirement" in seen[0]
    assert "Ground the price, time, availability" not in seen[0]
    seen.clear()
    run.judge(golden_case(3).model_copy(update={"contract_version": 1}), row, journal)
    for reference in (seen[0], seen[2]):
        assert "without calling a tool" in reference
        assert "Never substitute that rate for the truck" in reference
        assert '"earliest_assistant_turn"' not in reference


@pytest.mark.parametrize(
    "stop,message,reason,error",
    [
        (True, "Use $120,000.", "goal_completed", "actor_stop_with_message"),
        (False, None, None, "actor_missing_reply"),
        (False, "", None, "actor_missing_reply"),
        (False, "   ", None, "actor_missing_reply"),
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

    case = golden_case(15).model_copy(update={"contract_version": 2})
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
    assert result.status == "inconclusive" and result.error == error
    assert (
        result.actor_validity is not None and result.actor_validity.status == "invalid"
    )
    assert result.failure_class == "actor_validity" and not result.passed
    assert result.actor_replies[0]["message"] == message
    actor.act.assert_called_once()
    agent.assert_called_once()
    judge.assert_not_called()


def test_actor_reply_is_delivered_before_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from strands_evals.types.simulation import ActorResponse

    from eval.artifact_agent import Answer

    case = golden_case(15)
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

    def judge(
        case: golden.GoldenCase,
        row: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool = False,
    ) -> None:
        row.verdicts = {
            key: run.Verdict(passed=True, evidence="offline")
            for key in ("outcome", "grounding", "rules")
        }
        row.measurements.append(measurement())
        row.actor_validity = run.ActorAssessment(status="valid", evidence="offline")

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
    case = next(c for c in golden.load_cases() if c.id == example.case_id).model_copy(
        update={"contract_version": 1}
    )
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

    case = golden_case(1)
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


@pytest.mark.parametrize("overlapping_call", [False, True])
def test_packaged_model_budget_is_scored_but_protocol_failure_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overlapping_call: bool
) -> None:
    from eval.artifact_agent import ArtifactAgent

    case = golden_case(1)
    call_limit = case.actor.max_turns + case.max_tool_calls + 2
    usage = {"inputTokens": 100, "outputTokens": 20}
    events: list[dict[str, Any]] = []
    for _ in range(call_limit):
        events.extend(
            [
                {"event": "model_start", "input_bound": 100},
                {"event": "model_end", "usage": usage, "seconds": 0.1},
            ]
        )
    if overlapping_call:
        events.pop()  # The last started call has no usage before another starts.
    events.append({"event": "model_start", "input_bound": 100})

    adapter = object.__new__(ArtifactAgent)
    adapter.calls, adapter.reserved = 0, None
    adapter.send, adapter.receive = Mock(), Mock(side_effect=events)
    adapter.process = Mock()

    def factory(
        case: golden.GoldenCase,
        row: run.Attempt,
        journal: run.Journal,
        messages: list[str],
    ) -> ArtifactAgent:
        adapter.case, adapter.attempt, adapter.journal = case, row, journal
        adapter.messages, adapter.replay = messages, golden.Replay(case)
        return adapter

    monkeypatch.setattr(run, "build_eval_model", lambda: Mock(client_args={}))
    monkeypatch.setattr(golden, "make_actor", Mock())

    def judge(case: golden.GoldenCase, row: run.Attempt, journal: run.Journal) -> None:
        row.actor_validity = run.ActorAssessment(status="valid", evidence="offline")
        row.verdicts = {
            key: run.Verdict(passed=False, evidence="No completed response")
            for key in ("outcome", "grounding", "rules")
        }

    monkeypatch.setattr(run, "judge", judge)
    journal = run.Journal(tmp_path / "packaged-budget", 25)
    result = run.execute(case, 1, journal, agent_factory=factory)
    assert len(result.measurements) == call_limit
    assert adapter.calls == call_limit
    assert journal.reserved == pytest.approx(0)
    assert journal.spent == pytest.approx(sum(m.cost_usd for m in result.measurements))
    assert not result.passed
    if overlapping_call:
        assert result.status == "infrastructure"
        assert result.error == "artifact_unsettled_call"
        assert journal.unknown_usage and not result.measurements[-1].complete
        assert "model_call_budget" not in result.checks
    else:
        assert result.status == "scored" and result.failure_class == "budget"
        assert result.error is None and "model_call_budget" in result.checks
        assert not journal.unknown_usage
        assert journal.spent == pytest.approx(call_limit * run.cost(usage))
        for number in (2, 3):
            journal.append(
                {"event": "attempt_finished", **attempt(case, number).model_dump()}
            )
        manifest = json.loads(
            (golden.V2 / "eval/evidence/golden-360/demo-1/manifest.json").read_text()
        )
        manifest["identity"]["harness_version"] = "2.0.13"
        manifest["identity"]["corpus"]["case_count"] = 1
        manifest["identity"]["cases"] = [case.model_dump(mode="json")]
        (journal.directory / "manifest.json").write_text(json.dumps(manifest))
        report = run.render(journal.directory)
        # Infrastructure replacement requires incomplete evidence; a scored budget
        # failure leaves the measured corpus complete and cannot authorize one.
        assert report["full_corpus_complete"]
        assert report["overall"]["scored_trials"] == 3
        assert report["overall"]["successful_trials"] == 2


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
        case = case.model_copy(update={"contract_version": 1})
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
            (50 - (written or 0)) * 0.10
            + 50 * 0.01
            + (written or 0) * 0.125
            + 10 * 0.50
        ) / 1_000_000
        assert run.cost(usage) == pytest.approx(expected)


@pytest.mark.parametrize(
    "changed", ["judge_prompt_sha256", "transport", "tool_description_policy"]
)
def test_cli_rejects_changed_cache_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    root = tmp_path / "corpus"
    shutil.copytree(golden.ROOT, root)
    (root / "review.json").write_text(json.dumps({"status": "approved"}))
    monkeypatch.setattr(golden, "ROOT", root)
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
        "tool_description_policy",
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
    golden_test_identity: None,
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


def test_tool_wording_remains_in_full_run_identity(
    golden_test_identity: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_git = run.git

    def clean_git(*args: str) -> str:
        return "" if args[0] == "status" else original_git(*args)

    monkeypatch.setattr(run, "git", clean_git)
    before = run.identity(golden.load_cases())
    monkeypatch.setitem(golden.annual.TOOL_SPEC, "description", "Candidate wording")
    after = run.identity(golden.load_cases())
    assert before["tool_schema_hashes"] != after["tool_schema_hashes"]
    assert before["corpus"] == after["corpus"]
    assert before["evaluator_sources_sha256"] == after["evaluator_sources_sha256"]


def test_wrong_route_reference_also_misnames_its_endpoint() -> None:
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
    catalog = json.loads((golden.ROOT / "prompt-points.json").read_text())
    endpoint = next(
        point
        for point in catalog
        if point["point_id"] == call.input["destination_point_id"]
    )
    assert "Loudoun County" in endpoint["label"]
    assert example.expected is not None
    assert not example.expected.outcome
    assert not example.expected.grounding
    assert not example.expected.rules


@pytest.mark.parametrize("fixed_reference", [False, True])
def test_v2_outcome_and_actor_assessments_keep_private_facts_out_of_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_reference: bool
) -> None:
    case = golden_case(1).model_copy(deep=True)
    case.contract_version = 2
    case.terminal_objective = "cancellation"
    case.actor.facts += " PRIVATE_PROFILE_SENTINEL"
    row = run.Attempt(
        id="independent",
        case_id=case.id,
        trial=1,
        turns=[
            golden.Turn(user="Cancel that request.", response="Cancelled.", calls=[])
        ],
    )
    outcome_prompts: list[str] = []
    diagnostic_prompts: list[str] = []

    def outcome(prompt: str, **kwargs: object) -> SimpleNamespace:
        outcome_prompts.append(prompt)
        assert kwargs["structured_output_model"] is run.OutcomeAssessment
        return SimpleNamespace(
            structured_output=run.OutcomeAssessment(
                outcome=run.RequirementAssessment(
                    unmet_requirements=[], evidence="Cancellation acknowledged."
                ),
                actor_validity=run.ActorAssessment(
                    status="invalid", evidence="Cancellation contradicts this profile."
                ),
            )
        )

    def diagnostic(
        self: run.ConversationJudge, data: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        diagnostic_prompts.append(
            self.reference_system_prompt
            + (data.expected_assertion or "")
            + (data.actual_output or "")
        )
        return [
            EvaluationOutput(score=1, test_pass=True, reason="Delivered evidence only.")
        ]

    factory = Mock(return_value=outcome)
    monkeypatch.setattr(run, "Agent", factory)
    monkeypatch.setattr(run, "build_eval_model", lambda: Mock(client_args={}))
    monkeypatch.setattr(run.ConversationJudge, "evaluate", diagnostic)
    run.judge(
        case,
        row,
        run.Journal(tmp_path / "private", 25),
        fixed_reference=fixed_reference,
    )
    assert len(outcome_prompts) == 1 and len(diagnostic_prompts) == 2
    assert "PRIVATE_PROFILE_SENTINEL" in outcome_prompts[0]
    assert "Declared terminal objective: cancellation" in outcome_prompts[0]
    assert all(
        "PRIVATE_PROFILE_SENTINEL" not in prompt for prompt in diagnostic_prompts
    )
    prefix = factory.call_args.kwargs["system_prompt"]
    assert (run.FIXED_REFERENCE_PROMPT in prefix) is fixed_reference
    for prompt in [prefix, *diagnostic_prompts]:
        assert "greenway:2A:entry:EB" in prompt and "Battlefield Pkwy" in prompt
        assert '"coordinates"' in prompt
    assert all("Recorded sequence" in prompt for prompt in diagnostic_prompts)
    assert "Permitted tool sequence" not in diagnostic_prompts[0]
    assert row.verdicts["outcome"].passed
    assert row.actor_validity is not None and row.actor_validity.status == "invalid"
    row.measurements.append(measurement())
    run.finish_assessment(case, row)
    assert row.status == "inconclusive" and not row.passed


@pytest.mark.parametrize("stopped", [False, True])
@pytest.mark.parametrize("generated_reply", [False, True])
def test_application_stop_only_exempts_an_actor_that_never_ran(
    monkeypatch: pytest.MonkeyPatch, stopped: bool, generated_reply: bool
) -> None:
    case = golden_case(1)
    row = run.Attempt(
        id="stopped",
        case_id=case.id,
        trial=1,
        application_stop="tool_arguments" if stopped else None,
        turns=[
            golden.Turn(user=case.prompt, response="[No completed response]", calls=[])
        ],
        actor_replies=[{"message": "An invented route", "stop": False}]
        if generated_reply
        else [],
    )
    if generated_reply:
        row.turns.append(
            golden.Turn(
                user="An invented route", response="[No completed response]", calls=[]
            )
        )
    response = SimpleNamespace(
        structured_output=run.OutcomeAssessment(
            outcome=run.RequirementAssessment(
                unmet_requirements=[
                    run.UnmetRequirement(
                        requirement="Complete task", evidence="Turn 1 has no answer"
                    )
                ],
                evidence="Application failed.",
            ),
            actor_validity=run.ActorAssessment(
                status="invalid", evidence="Observed contradiction."
            ),
        )
    )
    evaluator = Mock(return_value=response)
    monkeypatch.setattr(run, "Agent", Mock(return_value=evaluator))
    run.assess_outcome(case, row, Mock(spec=Model), "contract", "conversation")
    assert row.actor_validity is not None
    assert row.actor_validity.status == (
        "valid" if stopped and not generated_reply else "invalid"
    )
    assert not row.verdicts["outcome"].passed
    assert "APPLICATION STOP" in evaluator.call_args.args[0]


@pytest.mark.parametrize("validity", ["invalid", "uncertain"])
def test_v2_inconclusive_trials_keep_costs_and_violations_outside_scores(
    validity: str,
) -> None:
    case = golden_case(1).model_copy(
        update={
            "contract_version": 2,
            "coverage_family": "current",
            "split_group": "paired",
        }
    )
    rows = [attempt(case, number) for number in (1, 2, 3)]
    rows[-1].actor_validity = run.ActorAssessment.model_validate(
        {"status": validity, "evidence": "Actor diverged."}
    )
    rows[-1].checks = ["unsupported_money"]
    run.finish_assessment(case, rows[-1])
    result = run.summary(rows, [case])
    assert result["scored_trials"] == result["successful_trials"] == 2
    assert result["inconclusive_trials"] == 1
    assert result["pass_at_1"] == 1
    assert result["pass_cubed"] == 0
    assert result["pass_cubed_case_denominator"] == 1
    assert result["families"]["current"]["scored_trials"] == 2
    assert result["observed_violations"]["grounding"] == 1
    assert result["cost_usd"]["agent"] == pytest.approx(0.03)
    assert not result["complete"]


def test_v2_bootstrap_keeps_paired_cases_in_one_cluster() -> None:
    cases = [
        c.model_copy(update={"contract_version": 2, "split_group": "one-pair"})
        for c in golden.load_cases()[:2]
    ]
    rows = [attempt(case, number) for case in cases for number in (1, 2, 3)]
    for row in rows[3:]:
        row.verdicts["outcome"].passed = False
    result = run.summary(rows, cases)
    assert result["scenario_group_count"] == 1
    assert result["success_ci95"] == [0.5, 0.5]
    assert result["pass_cubed"] == 0.5


@pytest.mark.parametrize(
    "validity,completed", [("valid", False), ("invalid", False), ("valid", True)]
)
@pytest.mark.parametrize("max_turns", [2, 5])
def test_v2_turn_limit_is_application_failure_only_for_valid_actor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validity: str,
    completed: bool,
    max_turns: int,
) -> None:
    from eval.artifact_agent import Answer

    case = golden_case(1).model_copy(deep=True)
    case.contract_version = 2
    case.actor.max_turns = max_turns
    if completed:
        case.steps, case.max_tool_calls = [], 0
    actor = golden.make_actor(case, Mock(spec=Model))
    actor.agent = Mock(
        side_effect=[
            SimpleNamespace(
                structured_output=golden.ActorReply(
                    message="I already provided that route."
                )
            )
            for _ in range(max_turns - 1)
        ]
        + [
            SimpleNamespace(
                structured_output=golden.ActorReply(
                    message=None if completed else "I already provided that route."
                )
            ),
        ]
    )
    monkeypatch.setattr(golden, "make_actor", Mock(return_value=actor))
    monkeypatch.setattr(run, "build_eval_model", lambda: Mock(client_args={}))

    def judge(
        case: golden.GoldenCase,
        row: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool = False,
    ) -> None:
        row.verdicts = {
            key: run.Verdict(passed=completed or key != "outcome", evidence="offline")
            for key in ("outcome", "grounding", "rules")
        }
        row.actor_validity = run.ActorAssessment.model_validate(
            {"status": validity, "evidence": "Supplied the requested facts."}
        )
        row.measurements.append(measurement())

    monkeypatch.setattr(run, "judge", judge)
    agent = Mock()
    answer = Answer("Which route again?")
    answer.stop_reason = "end_turn"
    agent.return_value = answer
    row = run.execute(
        case, 1, run.Journal(tmp_path / validity, 25), Mock(return_value=agent)
    )
    assert len(row.turns) == max_turns
    assert agent.call_count == actor.agent.call_count == max_turns
    assert ("agent_turn_budget" in row.checks) is (
        validity == "valid" and not completed
    )
    if completed:
        assert row.passed and row.actor_replies[-1]["stop_reason"] == "goal_completed"
    elif validity == "valid":
        assert row.status == "scored" and row.failure_class == "budget"
        assert not row.verdicts["outcome"].passed
        assert row.actor_replies[-1]["stop_reason"] == "max_turns"
        assert row.actor_replies[-1]["message"] == "I already provided that route."
    else:
        assert row.status == "inconclusive" and row.failure_class == "actor_validity"


def test_v2_explicit_calibration_labels_ignore_names_and_missing_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = next(
        e
        for e in run.development_examples()
        if e.expected is not None and not e.expected.rules
    )
    renamed = original.model_copy(update={"label": "good"})
    missing = original.model_copy(update={"label": "missing"})
    monkeypatch.setattr(run, "development_examples", lambda: [renamed, missing])

    def judge(
        case: golden.GoldenCase,
        row: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool = False,
    ) -> None:
        assert original.expected is not None
        row.verdicts = {
            key: run.Verdict(passed=value, evidence="explicit label")
            for key, value in original.expected.model_dump().items()
        }
        row.actor_validity = run.ActorAssessment(status="valid", evidence="offline")
        row.measurements.append(measurement())
        if row.id.endswith("-missing"):
            del row.verdicts["rules"]

    monkeypatch.setattr(run, "judge", judge)
    with ThreadPoolExecutor(max_workers=1) as pool:
        rows = run.calibrate(run.Journal(tmp_path / "labels", 25), pool)
    assert original.expected is not None
    assert rows[0]["expected"] == original.expected.model_dump()
    assert rows[0]["disagreements"] == [] and rows[0]["measurement_complete"]
    assert rows[1]["disagreements"] == [] and not rows[1]["measurement_complete"]


def test_archived_report_reproduces_original_application_scores(tmp_path: Path) -> None:
    source = golden.V2 / "eval/evidence/golden-360/demo-1"
    expected = json.loads((source / "report.json").read_text())
    directory = tmp_path / "archive"
    shutil.copytree(source, directory)
    actual = run.render(directory)
    for key in ("overall", "attempts", "subsets", "full_corpus_complete"):
        assert actual[key] == expected[key]
    assert all(
        "actor_validity" not in row and "failure_phase" not in row
        for row in actual["attempts"]
    )


def test_v2_render_accounts_for_600_trials_and_embedded_case_count(
    tmp_path: Path,
) -> None:
    source = golden.V2 / "eval/evidence/golden-360/demo-1/manifest.json"
    manifest = json.loads(source.read_text())
    template = golden_case(1)
    cases = [
        template.model_copy(
            update={
                "number": number,
                "id": f"accounting-{number}",
                "contract_version": 2,
                "coverage_family": "accounting",
                "split_group": f"pair-{(number - 1) // 2}",
                "kind": "mixed" if number <= 2 else "current",
                "held_out": False,
            }
        )
        for number in range(1, 201)
    ]
    manifest["identity"]["harness_version"] = "2.0.13"
    manifest["identity"]["corpus"]["case_count"] = 200
    manifest["identity"]["cases"] = [case.model_dump(mode="json") for case in cases]
    directory = tmp_path / "accounting"
    journal = run.Journal(directory, 25)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    for case in cases:
        for number in (1, 2, 3):
            row = attempt(case, number)
            journal.append({"event": "attempt_finished", **row.model_dump()})
    report = run.render(directory)
    assert (
        report["overall"]["expected_trials"]
        == report["overall"]["scored_trials"]
        == 600
    )
    assert report["full_corpus_complete"]
    assert report["subsets"]["mixed"]["expected_trials"] == 6
    events = (directory / "events.jsonl").read_text().splitlines()
    (directory / "events.jsonl").write_text("\n".join(events[:-1]) + "\n")
    partial = run.render(directory)
    assert partial["overall"]["expected_trials"] == 600
    assert partial["overall"]["scored_trials"] == 599
    assert not partial["full_corpus_complete"]


def test_invalid_actor_probe_is_complete_calibration_without_application_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = golden_case(1).model_copy(update={"contract_version": 2})
    replies: list[dict[str, JsonValue]] = [
        {"stop": True, "message": None, "stop_reason": "goal_completed"}
    ]
    example = golden.Example(
        case_id=case.id,
        label="actor-invalid-probe",
        expected_failures=["missing_call"],
        expected=None,
        actor_validity="invalid",
        actor_replies=replies,
        rationale="Only the simulator is labeled in this probe.",
        turns=[golden.Turn(user=case.prompt, response="Which route?", calls=[])],
    )
    monkeypatch.setattr(run, "development_examples", lambda: [example])
    monkeypatch.setattr(golden, "load_cases", lambda: [case])

    def judge(
        case: golden.GoldenCase,
        row: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool = False,
    ) -> None:
        assert row.actor_replies == replies
        assert fixed_reference
        row.verdicts = {
            key: run.Verdict(passed=False, evidence="Not used as application labels.")
            for key in ("outcome", "grounding", "rules")
        }
        row.actor_validity = run.ActorAssessment(
            status="invalid", evidence="Required follow-up omitted."
        )
        row.measurements.append(measurement())

    monkeypatch.setattr(run, "judge", judge)
    directory = tmp_path / "invalid-probe"
    journal = run.Journal(directory, 25)
    with ThreadPoolExecutor(max_workers=1) as pool:
        rows = run.calibrate(journal, pool)
    assert rows[0]["measurement_complete"] and rows[0]["status"] == "inconclusive"
    assert rows[0]["disagreements"] == [] and rows[0]["expected"] is None
    manifest = json.loads(
        (golden.V2 / "eval/evidence/golden-360/demo-1/manifest.json").read_text()
    )
    manifest["mode"] = "calibrate"
    manifest["identity"]["harness_version"] = "2.0.13"
    manifest["identity"]["calibration_labels"] = {"example_ids": [rows[0]["id"]]}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    report = run.render(directory)
    assert report["complete"] and report["measurement_failures"] == 0
    assert report["actor_validity_confusion"]["expected_invalid_predicted_invalid"] == 1
    assert all(
        sum(matrix.values()) == 0 for matrix in report["confusion_matrices"].values()
    )


def test_interrupted_calibration_counts_missing_rows_without_judge_disagreements(
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        (golden.V2 / "eval/evidence/golden-360/demo-1/manifest.json").read_text()
    )
    manifest["mode"] = "calibrate"
    manifest["identity"]["harness_version"] = "2.0.13"
    manifest["identity"]["calibration_labels"] = {"example_ids": ["started", "queued"]}
    journal = run.Journal(tmp_path / "interrupted-calibration", 25)
    (journal.directory / "manifest.json").write_text(json.dumps(manifest))
    row = run.Attempt(id="started", case_id="greenway-current", trial=1)
    journal.append({"event": "attempt_started", **row.model_dump()})
    journal.append(
        {"event": "model_finished", "attempt": row.id, **measurement().model_dump()}
    )
    report = run.render(journal.directory)
    assert not report["complete"]
    assert report["missing_example_ids"] == ["queued", "started"]
    assert report["missing_examples"] == report["measurement_failures"] == 2
    assert report["measurement_failure_counts"] == {"missing": 2}
    assert report["rows"] == []
    assert all(
        sum(matrix.values()) == 0 for matrix in report["confusion_matrices"].values()
    )
    assert (journal.directory / "report.md").read_text().count(
        "MISSING | Not assessed"
    ) == 2


def test_requirement_assessment_derives_verdict_without_relabeling() -> None:
    decision = run.RequirementAssessment(
        unmet_requirements=[], evidence="Turn 1 answers all requirements."
    )
    assert decision.verdict().passed
    decision.unmet_requirements.append(
        run.UnmetRequirement(
            requirement="Disclose scope", evidence="Turn 1 omits scope"
        )
    )
    decision.evidence = "Therefore pass."
    assert not decision.verdict().passed
    assert "Turn 1 omits scope" in decision.verdict().evidence
    assert "passed" not in run.RequirementAssessment.model_json_schema()["properties"]


def test_fixed_pass_cubed_preserves_historical_denominator() -> None:
    cases = golden.load_cases()[:2]
    rows = [attempt(c, n) for c in cases for n in (1, 2, 3)]
    rows[-1].status = "inconclusive"
    rows[-1].actor_validity = run.ActorAssessment(
        status="invalid", evidence="Stopped early"
    )
    current = run.summary(rows, cases)
    historical = run.summary(rows, cases, fixed_denominator=False)
    assert current["pass_cubed"] == 0.5
    assert current["overall_pass_rate"] == 5 / 6
    assert current["pass_cubed_case_denominator"] == 2
    assert historical["pass_cubed"] == 1
    assert historical["pass_cubed_case_denominator"] == 1
    assert run.summary(rows[:-1], cases)["pass_cubed"] == 0.5
    assert run.summary(rows[:-1], cases)["overall_pass_rate"] == 5 / 6
    with pytest.raises(ValueError, match="duplicate"):
        run.summary([*rows, rows[0]], cases)


def test_prior_accounting_rejects_unknown_usage(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"run_id": "previous", "prior_spend_usd": 11.0})
    )
    events: list[dict[str, Any]] = [
        {"event": "model_started"},
        {"event": "model_finished", "complete": True, "cost_usd": 0.25},
    ]
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(map(json.dumps, events)))
    assert run.prior_accounting(tmp_path)[1] == 11.25
    events[-1]["complete"] = False
    path.write_text("\n".join(map(json.dumps, events)))
    with pytest.raises(ValueError, match="unknown usage"):
        run.prior_accounting(tmp_path)
    path.write_text(json.dumps(events[0]))
    with pytest.raises(ValueError, match="unknown usage"):
        run.prior_accounting(tmp_path)

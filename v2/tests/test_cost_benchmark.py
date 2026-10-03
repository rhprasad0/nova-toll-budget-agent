"""Small synthetic checks for cost-only collection and publication."""

import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from strands.models import Model

from agent import toll_agent
from eval import cost_benchmark as benchmark
from eval import golden
from eval import golden_run as run


def measurement(**changes: Any) -> run.Measurement:  # noqa: ANN401
    return run.Measurement.model_validate(
        {
            "role": "agent",
            "input_tokens": 100,
            "output_tokens": 20,
            "cached_tokens": 0,
            "written_tokens": 0,
            "seconds": 1,
            "cost_usd": 0.00002,
            "complete": True,
            **changes,
        }
    )


def evidence(directory: Path) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "cases": [{"id": f"case-{n}"} for n in range(12)],
        "commit": "1" * 40,
        "artifact_sha256": "2" * 64,
        "corpus": {"version": "3.3.28"},
    }
    events: list[dict[str, Any]] = []
    for case in identity["cases"]:
        for number in range(1, 4):
            failed = case["id"] == "case-0" and number == 1
            row = run.Attempt(
                id=f"{case['id']}-{number}",
                case_id=case["id"],
                trial=number,
                status="scored",
                application_stop="output_token_budget" if failed else None,
                measurements=[measurement(role=role) for role in benchmark.EFFORTS],
            )
            for item in row.measurements:
                events.extend(
                    [
                        {"event": "model_started"},
                        {"event": "model_finished", **item.model_dump()},
                    ]
                )
            if not failed:
                events.append({"event": "turn"})
            events.append({"event": "attempt_finished", **row.model_dump()})
    (directory / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events)
    )
    return identity


def test_selection_and_scoped_model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = benchmark.select_cases(golden.load_cases())
    assert len(cases) == len({case.id for case in cases}) == 12
    assert sum(case.kind == "current" for case in cases) == 6
    assert any(case.terminal_objective == "unavailable" for case in cases)
    params = deepcopy(run.EVAL_MODEL_PARAMS)

    def fake() -> Mock:
        model = Mock(spec=Model)
        model.get_config.return_value = {"params": deepcopy(params)}
        return model

    agent, actor = Mock(side_effect=fake), Mock(side_effect=fake)
    monkeypatch.setattr(toll_agent, "_build_model", agent)
    monkeypatch.setattr(run, "build_eval_model", actor)
    with pytest.raises(RuntimeError), benchmark.model_overrides():
        app = cast(Mock, toll_agent._build_model())
        user = cast(Mock, run.build_eval_model())
        judge = cast(Mock, run.build_judge_model())
        assert (
            app.update_config.call_args.kwargs["params"]["reasoning"]["effort"]
            == "medium"
        )
        assert (
            user.update_config.call_args.kwargs["params"]["reasoning"]["effort"]
            == "low"
        )
        assert (
            judge.update_config.call_args.kwargs["params"]["reasoning"]["effort"]
            == "xhigh"
        )
        raise RuntimeError("check restoration after failure")
    assert toll_agent._build_model is agent and run.build_eval_model is actor
    assert params == run.EVAL_MODEL_PARAMS


def test_exact_pricing_and_token_categories() -> None:
    assert benchmark.charge(measurement()) == Decimal("0.000020")
    assert benchmark.charge(
        measurement(cached_tokens=40, written_tokens=20)
    ) == Decimal("0.0000169")
    assert benchmark.charge(
        measurement(input_tokens=272000, output_tokens=0)
    ) == Decimal("0.0272")
    assert benchmark.charge(
        measurement(input_tokens=272001, output_tokens=20)
    ) == Decimal("0.0544152")
    # Output usage already includes reasoning; there is no second reasoning charge.
    assert benchmark.charge(measurement(input_tokens=0, output_tokens=100)) == Decimal(
        "0.00005"
    )
    with pytest.raises(ValueError):
        benchmark.charge(measurement(cached_tokens=80, written_tokens=30))
    with pytest.raises(ValueError):
        benchmark.charge(measurement(complete=False))


def test_actual_model_factories_without_credentials_or_paid_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(toll_agent, "load_openai_api_key", lambda: "test-only-key")
    with benchmark.model_overrides():
        for role, model in (
            ("agent", toll_agent._build_model()),
            ("actor", run.build_eval_model()),
            ("judge", run.build_judge_model()),
        ):
            config = cast(Any, model).get_config()
            assert config["model_id"] == "gpt-6-luna"
            assert config["params"]["reasoning"]["effort"] == benchmark.EFFORTS[role]
            assert config["params"]["max_output_tokens"] == (
                8192 if role == "judge" else 2048
            )
            assert config["params"]["prompt_cache_options"] == {
                "mode": "explicit",
                "ttl": "30m",
            }


def test_failed_calls_count_and_only_completed_turns_are_denominator(
    tmp_path: Path,
) -> None:
    identity = evidence(tmp_path)
    result = benchmark.aggregate(tmp_path, identity)
    assert result["sample"]["attempted_conversations"] == 36
    assert result["sample"]["completed_turns"] == 35
    assert result["sample"]["failed_conversations"] == 1
    assert Decimal(result["roles"]["agent"]["cost_usd"]) == Decimal("0.00072")
    assert Decimal(result["total_cost_usd"]) == Decimal("0.00216")
    events = (tmp_path / "events.jsonl").read_text().splitlines()
    (tmp_path / "events.jsonl").write_text(
        "\n".join(line for line in events if json.loads(line)["event"] != "turn")
    )
    assert benchmark.aggregate(tmp_path, identity)["sample"]["completed_turns"] == 0


def test_incomplete_data_retains_public_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = tmp_path / "public.json"
    asset.write_text("previous valid benchmark")
    monkeypatch.setattr(benchmark, "ASSET", asset)
    identity = evidence(tmp_path)
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    (tmp_path / "events.jsonl").write_text("\n".join(lines[:-1]))
    with pytest.raises(ValueError, match="incomplete benchmark"):
        benchmark.publish(benchmark.aggregate(tmp_path, identity))
    assert asset.read_text() == "previous valid benchmark"


def test_usage_and_budget_stop_before_further_paid_calls(tmp_path: Path) -> None:
    async def consume(model: Model) -> None:
        async for _ in cast(Any, model).stream([]):
            pass

    native = Mock(spec=Model)
    native.client_args = {}

    async def missing_usage(
        *args: object, **kwargs: object
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"metadata": {"usage": {}}}

    native.stream = missing_usage
    journal = run.Journal(tmp_path / "unknown", 2)
    row = run.Attempt(id="one", case_id="one", trial=1)
    model = journal.model(native, "agent", row, 3)
    asyncio.run(consume(model))
    assert journal.unknown_usage and not row.measurements[0].complete
    with pytest.raises(run.StopRun):
        asyncio.run(consume(model))
    budget = run.Journal(tmp_path / "budget", 0.000001)
    with pytest.raises(run.StopRun):
        budget.reserve(row, "judge", 100)
    assert not (tmp_path / "budget/events.jsonl").read_text()

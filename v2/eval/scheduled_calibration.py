"""Judge-only scheduled calibration; never invokes an application or actor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from strands.models.openai_responses import OpenAIResponsesModel
from strands_evals.types.evaluation import EvaluationData
from strands_evals.types.trace import (
    AgentInvocationSpan,
    Session,
    SpanInfo,
    ToolCall,
    ToolExecutionSpan,
    ToolResult,
    Trace,
)

from eval import simulated
from eval.golden_run import Attempt, Journal, StopRun, prior_accounting

FIXTURES = (
    Path(__file__).resolve().parents[1] / "tests/fixtures/scheduled-calibration.jsonl"
)


class ToolEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: str = Field(min_length=1)
    assistant: str = Field(min_length=1)
    tools: list[ToolEvidence]


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    passed: bool
    expected_assertion: str = Field(min_length=1)
    turns: list[Turn] = Field(min_length=1, max_length=3)

    def evaluation_data(self) -> EvaluationData[str, str]:
        traces: list[Trace] = []
        instant = datetime(2026, 10, 7, 21, 23, tzinfo=UTC)
        for index, turn in enumerate(self.turns):
            info = SpanInfo(
                session_id=self.id,
                trace_id=str(index),
                span_id="agent",
                start_time=instant,
                end_time=instant,
            )
            traces.append(
                Trace(
                    session_id=self.id,
                    trace_id=str(index),
                    spans=[
                        AgentInvocationSpan(
                            span_info=info,
                            user_prompt=turn.user,
                            agent_response=turn.assistant,
                            available_tools=[],
                        ),
                        *[
                            ToolExecutionSpan(
                                span_info=info.model_copy(
                                    update={
                                        "span_id": f"tool-{number}",
                                        "parent_span_id": "agent",
                                    }
                                ),
                                agent_span_id="agent",
                                tool_call=ToolCall(
                                    name=tool.name, arguments=tool.arguments
                                ),
                                tool_result=ToolResult(content=json.dumps(tool.result)),
                            )
                            for number, tool in enumerate(turn.tools)
                        ],
                    ],
                )
            )
        return EvaluationData[str, str](
            input=self.turns[0].user,
            actual_output=self.turns[-1].assistant,
            expected_assertion=self.expected_assertion,
            actual_trajectory=Session(session_id=self.id, traces=traces),
        )


def examples() -> list[Example]:
    rows = [
        Example.model_validate(row)
        for row in map(json.loads, FIXTURES.read_text().splitlines())
    ]
    if not rows or len({row.id for row in rows}) != len(rows):
        raise ValueError("Missing or duplicate calibration examples")
    if {row.passed for row in rows} != {True, False}:
        raise ValueError("Calibration requires passing and critical-failure examples")
    return rows


def measured_model(journal: Journal, attempt: Attempt) -> OpenAIResponsesModel:
    """Reuse spending guards without changing the scheduled judge's transport."""
    model = simulated.build_eval_model(simulated.JUDGE_SETTINGS)
    model.client_args.update(max_retries=0, timeout=60)
    original = model.stream
    calls = 0

    async def measured(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:  # noqa: ANN401
        nonlocal calls
        if calls >= 3:
            raise StopRun("judge_call_budget")
        input_bound = len(json.dumps([args, kwargs], default=str).encode()) + 8192
        reservation = journal.reserve(attempt, "judge", input_bound)
        calls += 1
        started = time.monotonic()
        usage: dict[str, int] | None = None
        try:
            async for event in original(*args, **kwargs):
                if "metadata" in event and "usage" in event["metadata"]:
                    usage = cast(dict[str, int], dict(event["metadata"]["usage"]))
                yield event
        finally:
            journal.finish(
                attempt, "judge", reservation, usage, time.monotonic() - started
            )

    cast(Any, model).stream = measured
    return model


def calibrate(output: Path, budget: float, prior: Path | None = None) -> dict[str, Any]:
    rows = examples()  # Validate all inputs before loading any credentials.
    _, spent = prior_accounting(prior)
    journal = Journal(output, budget, spent)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "prior_spend_usd": spent,
                "policy_version": simulated.POLICY_VERSION,
                "evaluator_sha256": hashlib.sha256(
                    Path(simulated.__file__).read_bytes()
                ).hexdigest(),
                "fixtures_sha256": hashlib.sha256(FIXTURES.read_bytes()).hexdigest(),
                "judge": simulated.JUDGE_SETTINGS.model_dump(),
                "sdk_versions": {
                    package: importlib.metadata.version(package)
                    for package in ("strands-agents", "strands-agents-evals", "openai")
                },
            },
            indent=2,
        )
        + "\n"
    )
    results: list[dict[str, Any]] = []
    for repetition in (1, 2):
        for example in rows:
            attempt = Attempt(
                id=f"{example.id}-{repetition}", case_id=example.id, trial=repetition
            )
            data = example.evaluation_data()
            for name in ("Completeness", "Correctness"):
                model = measured_model(journal, attempt)
                judges = simulated.evaluators(model=model)
                judge = next(item for item in judges if item.get_name() == name)
                result = judge.evaluate(data)
                if journal.unknown_usage or len(result) != 1:
                    raise StopRun("incomplete_calibration")
                item = {
                    "event": "calibration",
                    "example": example.id,
                    "repetition": repetition,
                    "judge": name,
                    "expected": example.passed,
                    "passed": result[0].test_pass,
                    "reason": result[0].reason,
                }
                results.append(item)
                journal.append(item)
                print(
                    f"{attempt.id} {name}: {'agree' if item['passed'] == item['expected'] else 'DISAGREE'}",
                    flush=True,
                )
    summary = {
        "policy_version": simulated.POLICY_VERSION,
        "examples": len(rows),
        "judgments": len(results),
        "disagreements": sum(item["passed"] != item["expected"] for item in results),
        "cost_usd": journal.spent,
        "complete": not journal.unknown_usage and len(results) == len(rows) * 4,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-usd", type=float, default=5)
    parser.add_argument(
        "--prior",
        type=Path,
        help="Prior private run directory; shares the cumulative ceiling",
    )
    args = parser.parse_args()
    private = Path(__file__).resolve().parent / "private"
    if not args.output.resolve().is_relative_to(private.resolve()):
        parser.error("Calibration output must remain in eval/private/")
    result = calibrate(args.output, args.budget_usd, args.prior)
    print(json.dumps(result))
    if not result["complete"] or result["disagreements"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

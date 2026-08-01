"""Runs the Strands Evals experiment for TollChat's fuzzy location-matching
and clarification behavior (see eval-plan.md). Both evaluators are
code-based, not LLM-judged: this evaluation only tests whether the agent's
Step 1 location resolution (agent-sops/nova-toll-pricing-assistant.sop.md)
asks before guessing an ambiguous location, converges to the exact oracle
label once the user picks one, resolves an unambiguous case-insensitive
match without asking, and never fabricates a price for an uncovered road.

Requires AWS_PROFILE=nova-toll (OpenAI key via SSM) and tailnet RDS access
to actually invoke the agent -- run explicitly, same convention as
tests/test_toll_agent_live.py. `--check` runs the per-turn matching logic
against synthetic trajectories only, no network calls.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands.types.content import Messages  # noqa: E402
from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator  # noqa: E402
from strands_evals.extractors import tools_use_extractor  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)
from strands_evals.types.evaluation_report import EvaluationReport  # noqa: E402

from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_PRICE_RE = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        expected_tools = [
            step["tool"] for step in row["expected_trajectory"] if step.get("tool")
        ]
        cases.append(
            Case[str, str](
                name=row["id"],
                input=row["conversation"][0]["content"],
                expected_trajectory=expected_tools,
                metadata=row,
            )
        )
    return cases


def _extract_price(text: str) -> float | None:
    match = _PRICE_RE.search(text)
    return float(match.group(1)) if match else None


def _metadata(case: Case[str, str]) -> dict[str, Any]:
    assert case.metadata is not None
    return case.metadata


def _extract_tool_calls(messages: Messages) -> list[dict[str, Any]]:
    # extract_agent_tools_used_from_messages returns tool-call records
    # ({"name", "input", "tool_result", "is_error"}), not plain name
    # strings -- confirmed against the installed strands_evals package.
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        messages
    )


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns: list[dict[str, str]] = _metadata(case)["conversation"]
    trajectory_by_turn: list[list[dict[str, Any]]] = []
    response = None
    for turn in turns:
        before = len(agent.messages)
        response = agent(turn["content"])
        calls = _extract_tool_calls(agent.messages[before:])
        trajectory_by_turn.append(calls)
    # Smuggled through case.metadata (mutated in place) since TaskOutput has
    # no slot for per-turn call records -- both evaluators below read it
    # back off the same Case instance.
    _metadata(case)["_trajectory_by_turn"] = trajectory_by_turn
    return {
        "output": str(response),
        "trajectory": [call["name"] for call in trajectory_by_turn[-1]],
    }


class LocationResolutionEvaluator(Evaluator[str, str]):
    """Per-turn check: no tool call where the location is still ambiguous
    (a clarifying question is expected instead), and exactly the expected
    tool called with the exact oracle-label arguments where resolution is
    possible. The hard-label check *is* the tool-call-argument check."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        expected_turns: list[dict[str, Any]] = metadata.get("expected_trajectory", [])
        trajectory_by_turn: list[list[dict[str, Any]]] = metadata.get(
            "_trajectory_by_turn", []
        )

        for entry in expected_turns:
            turn_index = cast(int, entry["turn"]) - 1
            actual_calls: list[dict[str, Any]] = []
            if turn_index < len(trajectory_by_turn):
                actual_calls = trajectory_by_turn[turn_index]
            expected_tool = entry.get("tool")

            if expected_tool is None:
                if actual_calls:
                    return [
                        EvaluationOutput(
                            score=0.0,
                            test_pass=False,
                            reason=(
                                f"turn {entry['turn']}: expected a clarifying "
                                f"question with no tool call, but got "
                                f"{[c['name'] for c in actual_calls]}"
                            ),
                            label="premature_tool_call",
                        )
                    ]
                continue

            if len(actual_calls) != 1 or actual_calls[0]["name"] != expected_tool:
                return [
                    EvaluationOutput(
                        score=0.0,
                        test_pass=False,
                        reason=(
                            f"turn {entry['turn']}: expected exactly one call to "
                            f"{expected_tool!r}, got "
                            f"{[c['name'] for c in actual_calls]}"
                        ),
                        label="tool_mismatch",
                    )
                ]

            expected_input: dict[str, Any] = entry.get("input", {})
            actual_input: dict[str, Any] = actual_calls[0]["input"]
            # Subset match, not full dict equality: tools like i495_route
            # accept an optional at_time the case doesn't pin, and the
            # metric under test is the origin/destination hard label, not
            # every argument shape.
            labels_match = all(
                actual_input.get(key) == value for key, value in expected_input.items()
            )
            if not labels_match:
                return [
                    EvaluationOutput(
                        score=0.0,
                        test_pass=False,
                        reason=(
                            f"turn {entry['turn']}: {expected_tool} called with "
                            f"{actual_input}, expected exact hard labels "
                            f"{expected_input}"
                        ),
                        label="label_mismatch",
                    )
                ]

        return [
            EvaluationOutput(
                score=1.0,
                test_pass=True,
                reason="every turn matched its expected tool call (or absence)",
                label="resolved",
            )
        ]


class NoFabricatedPriceEvaluator(Evaluator[str, str]):
    """For cases marked expect_no_price: no pricing tool ever fired across
    the whole conversation, and the final response states no dollar amount."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        if not metadata.get("expect_no_price"):
            return [
                EvaluationOutput(
                    score=1.0,
                    test_pass=True,
                    reason="case does not require a price-free response",
                    label="not_applicable",
                )
            ]

        trajectory_by_turn: list[list[dict[str, Any]]] = metadata.get(
            "_trajectory_by_turn", []
        )
        any_tool_called = any(calls for calls in trajectory_by_turn)
        price = _extract_price(str(evaluation_case.actual_output or ""))

        if any_tool_called or price is not None:
            return [
                EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason=(
                        f"expected a coverage decline with no tool call and no "
                        f"price, got tool_called={any_tool_called} price={price}"
                    ),
                    label="fabricated_or_substituted",
                )
            ]
        return [
            EvaluationOutput(
                score=1.0,
                test_pass=True,
                reason="no pricing tool called and no price stated",
                label="declined_cleanly",
            )
        ]


def _report_cases(report: EvaluationReport) -> list[dict[str, Any]]:
    return report.cases  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]


def _report_details(report: EvaluationReport) -> list[list[EvaluationOutput]]:
    return report.detailed_results  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]


def main() -> None:
    cases = load_cases()
    experiment = Experiment[str, str](
        cases=cases,
        evaluators=[
            LocationResolutionEvaluator(),
            NoFabricatedPriceEvaluator(),
        ],
    )
    report = experiment.run_evaluations(task_function)

    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report.to_file(str(_RESULTS_DIR / f"{stamp}.json"))

    # report.run_display() is interactive (blocks on stdin) -- not usable in
    # a script. report.cases holds case+evaluator identity, and the matching
    # score/test_pass/reason lives in the parallel report.detailed_results
    # list (one-item list per row) -- print a plain summary from both.
    print(f"Overall score: {report.overall_score:.2f}")
    report_cases: list[dict[str, Any]] = _report_cases(report)
    details: list[list[EvaluationOutput]] = _report_details(report)
    for case_result, detail in zip(report_cases, details, strict=True):
        result = detail[0]
        print(
            f"{case_result['name']} [{case_result['evaluator']}]: "
            f"score={result.score:.2f} pass={result.test_pass} - {result.reason}"
        )


def _self_check() -> None:
    """No Bedrock/OpenAI/RDS calls -- just the pure per-turn matching logic
    against synthetic trajectories covering all three shapes: tool fired as
    expected, no tool fired as expected, and an unexpected tool firing."""
    cases = load_cases()
    assert len(cases) == 3
    assert cases[0].name == "ambiguous-alias-mclean-multiturn"
    assert cases[1].expected_trajectory == ["i95_route"]
    assert cases[2].expected_trajectory == []

    assert _extract_price("Your trip costs $4.25 total.") == 4.25
    assert _extract_price("no price here") is None

    def _fake_case(
        metadata: dict[str, Any], actual_output: str = ""
    ) -> EvaluationData[str, str]:
        return EvaluationData[str, str](
            input="x",
            actual_output=actual_output,
            name="x",
            expected_output=None,
            expected_assertion=None,
            expected_trajectory=None,
            actual_trajectory=None,
            metadata=metadata,
            actual_interactions=None,
            expected_interactions=None,
            actual_environment_state=None,
            expected_environment_state=None,
        )

    resolver = LocationResolutionEvaluator()

    # Shape 1: tool fired as expected, with exact hard-label args.
    good = _fake_case(
        {
            "expected_trajectory": [
                {
                    "turn": 1,
                    "tool": "i95_route",
                    "input": {"origin": "A", "destination": "B"},
                }
            ],
            "_trajectory_by_turn": [
                [{"name": "i95_route", "input": {"origin": "A", "destination": "B"}}]
            ],
        }
    )
    assert resolver.evaluate(good)[0].test_pass is True

    # Shape 2: no tool fired, as expected (clarifying-question turn).
    clarifying = _fake_case(
        {
            "expected_trajectory": [{"turn": 1, "tool": None}],
            "_trajectory_by_turn": [[]],
        }
    )
    assert resolver.evaluate(clarifying)[0].test_pass is True

    # Shape 3: unexpected tool fired on a turn that should have clarified.
    premature = _fake_case(
        {
            "expected_trajectory": [{"turn": 1, "tool": None}],
            "_trajectory_by_turn": [
                [{"name": "i95_route", "input": {"origin": "A", "destination": "B"}}]
            ],
        }
    )
    result = resolver.evaluate(premature)[0]
    assert result.test_pass is False
    assert result.label == "premature_tool_call"

    # Wrong hard label reaching the tool -- fuzzy text instead of the exact
    # oracle label -- must fail, not just "a tool was called".
    fuzzy_label = _fake_case(
        {
            "expected_trajectory": [
                {
                    "turn": 1,
                    "tool": "i95_route",
                    "input": {"origin": "A", "destination": "B"},
                }
            ],
            "_trajectory_by_turn": [
                [
                    {
                        "name": "i95_route",
                        "input": {"origin": "a-ish", "destination": "B"},
                    }
                ]
            ],
        }
    )
    result = resolver.evaluate(fuzzy_label)[0]
    assert result.test_pass is False
    assert result.label == "label_mismatch"

    # An extra argument the case doesn't pin (e.g. i495_route's optional
    # at_time) must not fail a case whose hard labels are correct.
    extra_arg = _fake_case(
        {
            "expected_trajectory": [
                {
                    "turn": 1,
                    "tool": "i495_route",
                    "input": {"origin": "A", "destination": "B"},
                }
            ],
            "_trajectory_by_turn": [
                [
                    {
                        "name": "i495_route",
                        "input": {"origin": "A", "destination": "B", "at_time": None},
                    }
                ]
            ],
        }
    )
    assert resolver.evaluate(extra_arg)[0].test_pass is True

    price_check = NoFabricatedPriceEvaluator()

    declined = _fake_case(
        {"expect_no_price": True, "_trajectory_by_turn": [[]]},
        actual_output="That road is outside coverage.",
    )
    assert price_check.evaluate(declined)[0].test_pass is True

    fabricated = _fake_case(
        {"expect_no_price": True, "_trajectory_by_turn": [[]]},
        actual_output="That trip costs $3.50.",
    )
    assert price_check.evaluate(fabricated)[0].test_pass is False

    not_applicable = _fake_case({"expect_no_price": False, "_trajectory_by_turn": [[]]})
    assert price_check.evaluate(not_applicable)[0].label == "not_applicable"

    print("self-check ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()

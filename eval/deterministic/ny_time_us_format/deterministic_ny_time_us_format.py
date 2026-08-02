"""Runs the Strands Evals experiment for TollChat's date/time handling (see
eval-plan.md). Both evaluators are code-based, not LLM-judged: this
evaluation only tests whether the agent (1) turns a user-stated date/time
into an `at_time` tool argument that resolves to the correct
America/New_York instant, whether or not the user's phrasing already named
Eastern time, and (2) reports that timestamp back to the user in US
Standard format (SOP Step 4), not the tool's raw ISO-8601 string.

Requires AWS_PROFILE=nova-toll (OpenAI key via SSM) and tailnet RDS access
to actually invoke the agent -- run explicitly, same convention as
tests/test_toll_agent_live.py and the fuzzy-location suite. `--check` runs
the per-case matching logic against synthetic trajectories only, no network
calls, and does not call configure_local_pricing_env().
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from strands.types.content import Message, Messages  # noqa: E402
from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator  # noqa: E402
from strands_evals.extractors import tools_use_extractor  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from agent_tools._oracle_route import resolve_at_time  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_US_FORMAT_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2} (AM|PM) ET\b")
_RAW_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


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


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _report_passed(test_passes: list[bool]) -> bool:
    return all(test_passes)


def _metadata(case: Case[str, str]) -> dict[str, Any]:
    assert case.metadata is not None
    return case.metadata


def _turns(evaluation_case: EvaluationData[str, str]) -> list[dict[str, Any]]:
    trajectory = evaluation_case.actual_trajectory
    return (
        cast(list[dict[str, Any]], trajectory) if isinstance(trajectory, list) else []
    )


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _extract_tool_calls(messages: Messages) -> list[dict[str, Any]]:
    # extract_agent_tools_used_from_messages returns tool-call records
    # ({"name", "input", "tool_result", "is_error"}), not plain name
    # strings -- confirmed against the installed strands_evals package
    # (same extraction path as deterministic_fuzzy_location_matching.py).
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        messages
    )


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns: list[dict[str, str]] = _metadata(case)["conversation"]
    trajectory_by_turn: list[dict[str, Any]] = []
    response = None
    for turn in turns:
        response = agent(turn["content"])
        summary: dict[str, Any] = response.metrics.get_summary()
        traces = cast(list[dict[str, Any]], summary.get("traces", []))
        calls = _extract_tool_calls(_trace_messages(traces))
        trajectory_by_turn.append({"response": str(response), "calls": calls})
    return {
        "output": str(response),
        "trajectory": trajectory_by_turn,
    }


class TimeInterpretationEvaluator(Evaluator[str, str]):
    """The tool-called at_time must resolve to the case's expected instant.

    Compares parsed instants, not strings: an at_time carrying an explicit
    non-Eastern offset is just as correct as an Eastern-equivalent naive
    value, as long as both name the same moment. Reuses resolve_at_time --
    the same function the production tools call -- instead of
    reimplementing its naive-value-means-Eastern assumption here.
    """

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        expected_turns: list[dict[str, Any]] = metadata.get("expected_trajectory", [])
        expected_instant = datetime.fromisoformat(metadata["expected_at_time_instant"])
        trajectory_by_turn = _turns(evaluation_case)

        for entry in expected_turns:
            turn_index = cast(int, entry["turn"]) - 1
            turn = (
                trajectory_by_turn[turn_index]
                if turn_index < len(trajectory_by_turn)
                else {}
            )
            actual_calls: list[dict[str, Any]] = turn.get("calls", [])
            expected_tool = entry["tool"]

            if len(actual_calls) != 1 or actual_calls[0]["name"] != expected_tool:
                return _result(
                    False,
                    f"turn {entry['turn']}: expected exactly one call to "
                    f"{expected_tool!r}, got {[c['name'] for c in actual_calls]}",
                    "tool_mismatch",
                )

            actual_input: dict[str, Any] = actual_calls[0]["input"]
            at_time = actual_input.get("at_time")
            if not at_time:
                return _result(
                    False,
                    f"turn {entry['turn']}: {expected_tool} called with no at_time",
                    "missing_at_time",
                )
            try:
                actual_instant = resolve_at_time(at_time)
            except ValueError as e:
                return _result(
                    False,
                    f"turn {entry['turn']}: at_time {at_time!r} unparseable: {e}",
                    "unparseable_at_time",
                )
            if actual_instant != expected_instant:
                return _result(
                    False,
                    f"turn {entry['turn']}: at_time {at_time!r} resolved to "
                    f"{actual_instant.isoformat()}, expected "
                    f"{expected_instant.isoformat()}",
                    "wrong_instant",
                )

        return _result(True, "at_time resolved to the expected instant", "resolved")


class USFormatEvaluator(Evaluator[str, str]):
    """The final response must show a US-format timestamp and no raw ISO-8601."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        response = str(evaluation_case.actual_output or "")
        has_us_format = _US_FORMAT_RE.search(response) is not None
        has_raw_iso = _RAW_ISO_RE.search(response) is not None

        if has_raw_iso:
            return _result(
                False,
                "response contains a raw ISO-8601 timestamp instead of "
                "US-format (M/D/YYYY h:MM AM/PM ET)",
                "raw_iso_leaked",
            )
        if not has_us_format:
            return _result(
                False,
                "response does not contain a US-format timestamp "
                "(M/D/YYYY h:MM AM/PM ET)",
                "us_format_missing",
            )
        return _result(True, "response used US-format date/time", "us_formatted")


def main() -> None:
    configure_local_pricing_env()
    cases = load_cases()
    experiment = Experiment[str, str](
        cases=cases,
        evaluators=[
            TimeInterpretationEvaluator(),
            USFormatEvaluator(),
        ],
    )
    report = experiment.run_evaluations(task_function)

    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report.to_file(str(_RESULTS_DIR / f"{stamp}.json"))

    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not _report_passed(report.test_passes):
        raise SystemExit("deterministic NY-time/US-format evaluation failed")


def _self_check() -> None:
    """Exercise the pure matching logic against synthetic trajectories."""
    cases = load_cases()
    assert [case.name for case in cases] == [
        "naive-eastern-edt",
        "non-eastern-zone-converted",
        "naive-eastern-est-dst-boundary",
    ]
    assert cases[0].expected_trajectory == ["i95_route"]
    assert _report_passed([True, True])
    assert not _report_passed([True, False])

    for text in (
        "VDOT observed at: 7/15/2026 2:30 PM ET",
        "as of 11/3/2026 10:00 AM ET",
    ):
        assert _US_FORMAT_RE.search(text)
    for text in ("VDOT observed at: 2026-07-15T14:30:00-04:00", "no timestamp here"):
        assert not _US_FORMAT_RE.search(text)
    assert _RAW_ISO_RE.search("VDOT observed at: 2026-07-15T14:30:00-04:00")
    assert not _RAW_ISO_RE.search("VDOT observed at: 7/15/2026 2:30 PM ET")

    def _fake_case(
        metadata: dict[str, Any],
        trajectory: list[dict[str, Any]],
        actual_output: str = "",
    ) -> EvaluationData[str, str]:
        return EvaluationData[str, str](
            input="x",
            actual_output=actual_output,
            actual_trajectory=trajectory,
            metadata=metadata,
        )

    time_checker = TimeInterpretationEvaluator()
    expected_entry = {
        "turn": 1,
        "tool": "i95_route",
        "input": {
            "origin": "Pentagon/Eads Street",
            "destination": "I-95 Near Dumfries Road/Route 234",
        },
    }
    time_metadata = {
        "expected_trajectory": [expected_entry],
        "expected_at_time_instant": "2026-07-15T17:00:00-04:00",
    }
    time_checks: list[tuple[list[dict[str, Any]], str]] = [
        (
            [
                {
                    "calls": [
                        {
                            "name": "i95_route",
                            "input": {"at_time": "2026-07-15T14:00:00-07:00"},
                        }
                    ]
                }
            ],
            "resolved",
        ),
        (
            [
                {
                    "calls": [
                        {
                            "name": "i95_route",
                            "input": {"at_time": "2026-07-15T17:00:00"},
                        }
                    ]
                }
            ],
            "resolved",
        ),
        (
            # Naive passthrough bug: 14:00 assumed Eastern is 3h off from
            # the expected 17:00 Eastern instant (2 PM Pacific).
            [
                {
                    "calls": [
                        {
                            "name": "i95_route",
                            "input": {"at_time": "2026-07-15T14:00:00"},
                        }
                    ]
                }
            ],
            "wrong_instant",
        ),
        (
            [{"calls": [{"name": "i95_route", "input": {}}]}],
            "missing_at_time",
        ),
        (
            [{"calls": [{"name": "i95_route", "input": {"at_time": "not-a-date"}}]}],
            "unparseable_at_time",
        ),
        (
            [{"calls": []}],
            "tool_mismatch",
        ),
    ]
    for trajectory, label in time_checks:
        assert (
            time_checker.evaluate(_fake_case(time_metadata, trajectory))[0].label
            == label
        ), label

    format_checker = USFormatEvaluator()
    format_checks: list[tuple[str, str]] = [
        ("VDOT observed at: 7/15/2026 2:30 PM ET", "us_formatted"),
        ("VDOT observed at: 2026-07-15T14:30:00-04:00", "raw_iso_leaked"),
        ("The trip costs $4.25.", "us_format_missing"),
    ]
    for output, label in format_checks:
        assert format_checker.evaluate(_fake_case({}, [], output))[0].label == label, (
            label
        )

    print("self-check ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()

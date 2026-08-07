from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoke_agentcore_session_isolation",
    ROOT / "scripts" / "smoke_agentcore_session_isolation.py",
)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)

SESSION_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SESSION_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _response(status: int = 200, code: str | None = None):
    body: dict[str, object] = {"answer": "ok"}
    if code:
        body = {"error": {"code": code}}
    return status, body


def _successful_exercise():
    calls: list[tuple[str, dict[str, object]]] = []
    a_chats = 0

    def post(path: str, body: dict[str, object]):
        nonlocal a_chats
        calls.append((path, body))
        if path == "/api/reset":
            return _response()
        if body["session_id"] == SESSION_A:
            a_chats += 1
            if a_chats == 6:
                return _response(422, "turn_limit")
        return _response()

    observations = evaluator.exercise_sessions(post, SESSION_A, SESSION_B)
    return observations, calls


def _records(
    session_id: str,
    stream: str,
    *,
    agent_count: int,
    invoke_count: int,
) -> list[dict[str, str]]:
    records = []
    for index in range(agent_count):
        records.append(
            {
                "session_id": session_id,
                "trace_id": f"{stream}-agent-{index}",
                "stage": "agent",
                "log_stream": stream,
            }
        )
    for index in range(invoke_count):
        records.append(
            {
                "session_id": session_id,
                "trace_id": f"{stream}-invoke-{index}",
                "stage": "invoke",
                "log_stream": stream,
            }
        )
    return records


def _passing_records() -> list[dict[str, str]]:
    return [
        *_records(SESSION_A, "a-before-reset", agent_count=5, invoke_count=6),
        *_records(SESSION_A, "a-after-reset", agent_count=1, invoke_count=1),
        *_records(SESSION_B, "b", agent_count=3, invoke_count=3),
    ]


def test_exercise_interleaves_sessions_exhausts_a_and_resets_only_a():
    observations, calls = _successful_exercise()

    assert observations == {
        "session_a": SESSION_A,
        "session_b": SESSION_B,
        "successful_a_before_reset": 5,
        "successful_b": 3,
        "a_turn_limit_observed": True,
        "a_reset_observed": True,
        "a_restarted": True,
    }
    assert [body["session_id"] for path, body in calls[:2] if path == "/api/chat"] == [
        SESSION_A,
        SESSION_B,
    ]
    assert calls[-3][0] == "/api/reset"
    assert calls[-2][1]["session_id"] == SESSION_B
    assert calls[-1][1]["session_id"] == SESSION_A


def test_verify_accepts_isolated_turns_and_reset_streams():
    observations, _ = _successful_exercise()

    report = evaluator.verify_isolation(_passing_records(), observations)

    assert report == {
        "interleaved_sessions": 2,
        "session_a_pre_reset_agent_invocations": 5,
        "session_a_turn_limit_invocations": 1,
        "session_a_post_reset_agent_invocations": 1,
        "session_b_agent_invocations": 3,
        "runtime_streams_disjoint": True,
        "turn_budget_isolated": True,
        "reset_isolated": True,
        "reset_rotated_runtime": True,
    }
    serialized = json.dumps(report)
    assert SESSION_A not in serialized
    assert SESSION_B not in serialized
    assert "a-before-reset" not in serialized


@pytest.mark.parametrize("fail_on_b_call", [2, 3])
def test_exercise_fails_if_a_turn_limit_or_reset_affects_b(fail_on_b_call):
    a_calls = 0
    b_calls = 0

    def post(path: str, body: dict[str, object]):
        nonlocal a_calls, b_calls
        if path == "/api/chat" and body["session_id"] == SESSION_B:
            b_calls += 1
            if b_calls == fail_on_b_call:
                return _response(422, "turn_limit")
        if path == "/api/chat" and body["session_id"] == SESSION_A:
            a_calls += 1
            if a_calls == 6:
                return _response(422, "turn_limit")
        return _response()

    with pytest.raises(
        evaluator.IsolationVerificationError, match="expected status=200"
    ):
        evaluator.exercise_sessions(post, SESSION_A, SESSION_B)


def test_verify_rejects_malformed_trace_records():
    observations, _ = _successful_exercise()

    with pytest.raises(evaluator.IsolationVerificationError, match="malformed"):
        evaluator.verify_isolation([{"session_id": SESSION_A}], observations)


@pytest.mark.parametrize(
    "records,match",
    [
        (
            [
                *_records(SESSION_A, "shared", agent_count=5, invoke_count=6),
                *_records(SESSION_A, "a-new", agent_count=1, invoke_count=1),
                *_records(SESSION_B, "shared", agent_count=3, invoke_count=3),
            ],
            "shared by sessions",
        ),
        (
            [
                *_records(SESSION_A, "a-old", agent_count=4, invoke_count=6),
                *_records(SESSION_A, "a-new", agent_count=1, invoke_count=1),
                *_records(SESSION_B, "b", agent_count=3, invoke_count=3),
            ],
            "pre-reset turn evidence",
        ),
        (
            [
                *_records(SESSION_A, "a-old", agent_count=5, invoke_count=6),
                *_records(SESSION_A, "a-new", agent_count=1, invoke_count=1),
                *_records(SESSION_B, "b-old", agent_count=2, invoke_count=2),
                *_records(SESSION_B, "b-new", agent_count=1, invoke_count=1),
            ],
            "session B runtime changed",
        ),
        (
            [
                *_records(SESSION_A, "a", agent_count=5, invoke_count=6),
                *_records(SESSION_B, "b", agent_count=3, invoke_count=3),
            ],
            "fresh runtime",
        ),
    ],
)
def test_verify_fails_closed_on_invalid_isolation_evidence(records, match):
    observations, _ = _successful_exercise()

    with pytest.raises(evaluator.IsolationVerificationError, match=match):
        evaluator.verify_isolation(records, observations)

"""Paired Decisions scoring stays private, bounded, and outside the native gate."""

import json
import os
import subprocess
import time
from pathlib import Path
from threading import Lock
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
import yaml
from openai import OpenAI

from eval import corpus, decisions_ci, golden
from eval import golden_run as run


def packets(count: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "id": f"case-{i // 3}:{i % 3 + 1}",
            "case_id": f"case-{i // 3}",
            "trial": i % 3 + 1,
            "checks": [],
            "mechanical_rules_failed": False,
            "body": {"model": decisions_ci.MODEL, "input": "Evidence", "questions": []},
        }
        for i in range(count)
    ]


def response(
    probabilities: tuple[float, float, float] = (0.5, 0.9, 1.0),
) -> dict[str, Any]:
    return {
        "model": decisions_ci.MODEL,
        "answers": [
            {"name": key, "type": "predicate", "probability": probability}
            for key, probability in zip(
                decisions_ci.CRITERIA, probabilities, strict=True
            )
        ],
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }


def install_client(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport
) -> Mock:
    client = OpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.Client(transport=transport),
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr(decisions_ci, "OpenAI", factory)
    monkeypatch.setattr(
        decisions_ci.toll_agent, "load_openai_api_key", lambda: "test-only"
    )
    return factory


def test_predicates_match_names_and_apply_boundary_and_mechanical_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/decisions"
        assert json.loads(request.content)["model"] == decisions_ci.MODEL
        body = response((0.5, 0.499, 1.0))
        body["answers"].reverse()
        return httpx.Response(200, json=body)

    factory = install_client(monkeypatch, httpx.MockTransport(handle))
    item = packets()[0]
    item["mechanical_rules_failed"] = True
    results = decisions_ci.score([item], native_cost=0.1, budget_usd=2)
    assert results[0]["passed"] == {"outcome": True, "grounding": False, "rules": False}
    assert results[0]["complete"] is True and results[0]["overall_success"] is False
    assert results[0]["cost_usd"] == pytest.approx(0.00001)
    assert factory.call_args.kwargs["max_retries"] == 0
    assert factory.call_args.kwargs["timeout"] == 15


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "missing",
        "nan",
        "negative",
        "too_large",
        "string",
        "null",
        "missing_usage",
        "bad_usage",
        "refusal",
    ],
)
def test_invalid_or_refused_answers_cannot_become_complete_scores(
    defect: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = response()
    if defect == "duplicate":
        body["answers"][0]["name"] = "rules"
    elif defect == "missing":
        body["answers"].pop()
    elif defect in {"nan", "negative", "too_large", "string", "null"}:
        body["answers"][0]["probability"] = {
            "nan": float("nan"),
            "negative": -0.1,
            "too_large": 1.1,
            "string": "0.9",
            "null": None,
        }[defect]
    elif defect == "missing_usage":
        body.pop("usage")
    elif defect == "bad_usage":
        body["usage"]["input_tokens"] = True
    else:
        body["answers"][0] = {"type": "refusal", "name": "outcome"}
    install_client(
        monkeypatch,
        httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(body))),
    )
    result = decisions_ci.score(packets(), native_cost=0.1, budget_usd=2)[0]
    assert result["complete"] is False and result["overall_success"] is False
    assert result["cost_usd"] > 0
    assert "error" in result


def test_concurrent_reservations_cannot_spend_the_same_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, active, peak = 0, 0, 0
    lock = Lock()

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls, active, peak
        with lock:
            calls += 1
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return httpx.Response(
            200, content="{}"
        )  # unknown usage consumes the reservation

    install_client(monkeypatch, httpx.MockTransport(handle))
    items = packets(30)
    bound = len(json.dumps(items[0]["body"], ensure_ascii=False).encode()) + 8192
    ceiling = bound * decisions_ci.INPUT_PRICE
    results = decisions_ci.score(items, native_cost=0.1, budget_usd=0.1 + ceiling * 2.1)
    assert calls == peak == 2
    assert sum(item["cost_usd"] for item in results) == pytest.approx(ceiling * 2)
    assert 0.1 + sum(item["cost_usd"] for item in results) <= 0.1 + ceiling * 2.1
    assert all(not item.get("complete") for item in results)


def test_no_credentials_or_calls_when_native_spending_exhausts_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = Mock(side_effect=AssertionError("must not construct a client"))
    key = Mock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(decisions_ci, "OpenAI", factory)
    monkeypatch.setattr(decisions_ci.toll_agent, "load_openai_api_key", key)
    results = decisions_ci.score(packets(30), native_cost=2, budget_usd=2)
    assert all(item["error"] == "budget" for item in results)
    assert sum(item["cost_usd"] for item in results) == 0
    factory.assert_not_called()
    key.assert_not_called()


@pytest.mark.parametrize("status", [429, 500, "timeout"])
def test_transport_failures_are_bounded_and_do_not_retry(
    status: int | str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if status == "timeout":
            raise httpx.ReadTimeout(
                "sensitive evidence must not be exposed", request=request
            )
        assert isinstance(status, int)
        return httpx.Response(
            status,
            json={"error": {"message": "private evidence", "type": "server_error"}},
        )

    install_client(monkeypatch, httpx.MockTransport(handle))
    results = decisions_ci.score(packets(), native_cost=0.1, budget_usd=2)
    assert calls == 1 and not results[0]["complete"]
    assert "private evidence" not in json.dumps(results)
    assert "sensitive evidence" not in json.dumps(results)


def test_packet_keeps_full_public_evidence_and_excludes_native_judgments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(golden, "ROOT", corpus.PUBLIC / "shadow")
    case = golden.load_cases()[0]
    attempt = run.Attempt(
        id=f"{case.id}:1",
        case_id=case.id,
        trial=1,
        turns=[
            golden.Turn(user=case.prompt, response="First answer: $999.", calls=[]),
            golden.Turn(user="Cancel", response="Cancelled.", calls=[]),
        ],
        verdicts={
            key: run.Verdict(passed=False, evidence="NATIVE_SECRET_VERDICT")
            for key in decisions_ci.CRITERIA
        },
        actor_replies=[{"private": "PRIVATE_ACTOR_PROFILE"}],
    )
    result = decisions_ci.packet(case, attempt)
    evidence = json.loads(result["body"]["input"])
    assert len(evidence["conversation"]) == 2
    assert evidence["conversation"][0]["response"] == "First answer: $999."
    assert evidence["conversation"][1]["user"] == "Cancel"
    assert evidence["money_occurrences"]
    assert "unsupported_money" not in result["checks"]
    assert "NATIVE_SECRET_VERDICT" not in json.dumps(result)
    assert "PRIVATE_ACTOR_PROFILE" not in json.dumps(result)
    assert [q["name"] for q in result["body"]["questions"]] == list(
        decisions_ci.CRITERIA
    )
    assert all(
        run.ASSESSMENT_INSTRUCTIONS not in q["instructions"]
        for q in result["body"]["questions"]
    )


def summary_inputs() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    results = [
        {
            **item,
            "complete": True,
            "overall_success": True,
            "passed": dict.fromkeys(decisions_ci.CRITERIA, True),
            "seconds": 1.0,
            "cost_usd": 0.001,
            "usage_complete": True,
        }
        for item in packets(30)
    ]
    data = {
        "manifest": {"identity": {"cases": [{"id": f"case-{i}"} for i in range(10)]}},
        "attempts": [
            {
                "id": item["id"],
                "overall_success": True,
                "verdicts": {key: {"passed": True} for key in decisions_ci.CRITERIA},
                "measurements": [{"role": "judge", "seconds": 2.0}] * 3,
            }
            for item in results
        ],
        "overall": {"cost_usd": {"judge": 0.05}},
    }
    native = {
        "complete": True,
        "expected_trials": 30,
        "case_count": 10,
        "cost_usd": 0.1,
        "source_commit": "a" * 40,
        "pass_cubed": 1.0,
    }
    return native, data, results


def test_paired_summary_counts_actual_triples_and_disagreement_direction() -> None:
    native, data, results = summary_inputs()
    results[0]["passed"]["outcome"] = results[0]["overall_success"] = False
    data["attempts"][1]["overall_success"] = data["attempts"][1]["verdicts"]["rules"][
        "passed"
    ] = False
    summary = decisions_ci.summarize(native, data, results)
    assert summary["pass_cubed"] == 0.9 and summary["pass_rate"] == 29 / 30
    assert summary["agreement"]["overall"] == {
        "paired": 30,
        "agree": 28,
        "decisions_pass_native_fail": 1,
        "decisions_fail_native_pass": 1,
    }
    assert summary["latency_seconds_per_trial"]["native_judge"]["p50"] == 6.0
    assert summary["latency_seconds_per_trial"]["decisions"]["p50"] == 1.0
    assert summary["total_cost_usd"] == pytest.approx(0.13)
    results[0]["complete"] = False
    results[0]["passed"].pop("outcome")
    summary = decisions_ci.summarize(native, data, results)
    assert summary["complete"] is False and summary["scored_trials"] == 29
    assert summary["pass_cubed"] is None and summary["pass_rate"] is None
    assert summary["agreement"]["outcome"]["paired"] == 29
    assert summary["agreement"]["grounding"]["paired"] == 30


def test_workflow_comparison_errors_cannot_fail_native_gate(tmp_path: Path) -> None:
    workflow = yaml.safe_load(
        (golden.V2.parent / ".github/workflows/v2-shadow-eval.yml").read_text()
    )
    job = workflow["jobs"]["evaluate"]
    step = next(
        s
        for s in job["steps"]
        if s.get("name") == "Compare Decisions scores (informational)"
    )
    assert step["continue-on-error"] is True and step["timeout-minutes"] == 4
    assert (
        "!cancelled()" in step["if"]
        and "steps.approval.outcome == 'success'" in step["if"]
    )
    assert job["timeout-minutes"] >= 19
    assert "180s" in step["run"] and "--budget-usd 2" in step["run"]
    uv = tmp_path / "uv"
    uv.write_text("#!/bin/sh\nexit 1\n")
    uv.chmod(0o700)
    summary = tmp_path / "summary.md"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
    )
    assert result.returncode == 0
    assert "does not affect the native" in summary.read_text()


def test_comparison_rejects_overwrite_and_bad_budget_before_loading_credentials(
    tmp_path: Path,
) -> None:
    for budget in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="invalid_budget"):
            decisions_ci.compare(tmp_path, budget)
    (tmp_path / "decisions.json").write_text("{}")
    with pytest.raises(ValueError, match="comparison_already_exists"):
        decisions_ci.compare(tmp_path, 2)


def test_compare_excludes_invalid_actors_and_preserves_native_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native, data, _ = summary_inputs()
    original_root = golden.ROOT
    monkeypatch.setattr(golden, "ROOT", corpus.PUBLIC / "shadow")
    template = golden.load_cases()[0]
    monkeypatch.setattr(golden, "ROOT", original_root)
    cases = [template.model_copy(update={"id": f"case-{i}"}) for i in range(10)]
    for index, row in enumerate(data["attempts"]):
        attempt = run.Attempt(
            id=row["id"],
            case_id=f"case-{index // 3}",
            trial=index % 3 + 1,
            status="scored",
            actor_validity=run.ActorAssessment(
                status="valid", evidence="Valid delivered user facts"
            ),
            turns=[
                golden.Turn(user=cases[index // 3].prompt, response="Answer", calls=[])
            ],
            verdicts={
                key: run.Verdict(passed=True, evidence="Native verdict")
                for key in decisions_ci.CRITERIA
            },
            measurements=[
                run.Measurement(
                    role="judge",
                    input_tokens=10,
                    output_tokens=1,
                    cached_tokens=0,
                    written_tokens=0,
                    seconds=1,
                    cost_usd=0.001,
                    complete=True,
                )
            ],
        )
        data["attempts"][index] = {**attempt.model_dump(), "overall_success": True}
    data["attempts"][0]["actor_validity"]["status"] = "invalid"
    data["attempts"][1]["measurements"][0]["complete"] = False
    native["complete"] = False
    report = tmp_path / "report.json"
    report.write_text(json.dumps(data))
    before = report.read_bytes()
    monkeypatch.setattr(decisions_ci.shadow_ci, "report", Mock(return_value=native))
    monkeypatch.setattr(golden, "load_cases", lambda: cases)
    scoring = Mock(return_value=[])
    monkeypatch.setattr(decisions_ci, "score", scoring)
    summary = decisions_ci.compare(tmp_path, 2)
    assert len(scoring.call_args.args[0]) == 28
    assert scoring.call_args.kwargs == {"native_cost": 0.1, "budget_usd": 2}
    assert original_root == golden.ROOT and report.read_bytes() == before
    assert summary["complete"] is False and summary["pass_cubed"] is None
    assert (tmp_path / "decisions.json").exists()

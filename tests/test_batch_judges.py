import json
from types import SimpleNamespace

import pytest

from eval import batch_judges


def _request(custom_id: str) -> dict[str, object]:
    return batch_judges.build_judge_request(
        custom_id=custom_id,
        suite="sample-suite",
        case_id=custom_id.removeprefix("sample-suite:").rsplit(":", 1)[0],
        evaluator="goal_success",
        system_prompt="Judge the conversation.",
        prompt="CONVERSATION RECORD:\nUser: hello",
    )


def _result(custom_id: str, verdict: dict[str, object]) -> str:
    return json.dumps(
        {
            "custom_id": custom_id,
            "response": {
                "status_code": 200,
                "body": {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(verdict)}
                            ],
                        }
                    ]
                },
            },
            "error": None,
        }
    )


def test_serializes_responses_batch_jsonl_with_stable_metadata():
    request = _request("sample-suite:case-a:goal_success")

    line = json.loads(batch_judges.serialize_requests([request]).strip())

    assert set(line) == {"custom_id", "method", "url", "body"}
    assert line["custom_id"] == "sample-suite:case-a:goal_success"
    assert line["method"] == "POST"
    assert line["url"] == "/v1/responses"
    assert line["body"]["model"] == "gpt-5.6-luna"
    assert line["body"]["store"] is False
    assert line["body"]["metadata"] == {
        "suite": "sample-suite",
        "case_id": "case-a",
        "evaluator": "goal_success",
        "prompt_sha256": request["prompt_sha256"],
    }
    assert line["body"]["text"]["format"]["type"] == "json_schema"


def test_client_pins_direct_openai_endpoint(monkeypatch):
    captured = {}

    monkeypatch.setattr(batch_judges, "load_openai_api_key", lambda: "test-key")
    monkeypatch.setattr(
        batch_judges,
        "OpenAI",
        lambda **kwargs: captured.update(kwargs),
    )

    batch_judges._client()

    assert captured == {
        "api_key": "test-key",
        "base_url": "https://api.openai.com/v1",
    }


def test_reconciles_unordered_results_by_custom_id():
    requests = [
        _request("sample-suite:case-a:goal_success"),
        _request("sample-suite:case-b:goal_success"),
    ]

    verdicts, failures = batch_judges.reconcile_batch(
        requests,
        [
            _result(
                "sample-suite:case-b:goal_success",
                {"reasoning": "b", "verdict": "SUCCESS"},
            ),
            _result(
                "sample-suite:case-a:goal_success",
                {"reasoning": "a", "verdict": "FAILURE"},
            ),
        ],
        [],
        status="completed",
    )

    assert failures == []
    assert [row["custom_id"] for row in verdicts] == [
        "sample-suite:case-a:goal_success",
        "sample-suite:case-b:goal_success",
    ]
    assert verdicts[0] == {
        "custom_id": "sample-suite:case-a:goal_success",
        "suite": "sample-suite",
        "case_id": "case-a",
        "evaluator": "goal_success",
        "model": "gpt-5.6-luna",
        "response_status": 200,
        "prompt_sha256": requests[0]["prompt_sha256"],
        "parsed_verdict": {"reasoning": "a", "verdict": "FAILURE"},
    }


def test_reconcile_rejects_duplicate_or_missing_ids():
    request = _request("sample-suite:case-a:goal_success")

    with pytest.raises(ValueError, match="duplicate"):
        batch_judges.reconcile_batch(
            [request],
            [
                _result(request["custom_id"], {"reasoning": "a", "verdict": "SUCCESS"}),
                _result(request["custom_id"], {"reasoning": "a", "verdict": "SUCCESS"}),
            ],
            [],
            status="completed",
        )

    with pytest.raises(ValueError, match="missing"):
        batch_judges.reconcile_batch([request], [], [], status="completed")


def test_reconcile_reports_request_errors_and_expiry_without_verdicts():
    request = _request("sample-suite:case-a:goal_success")
    error = json.dumps(
        {
            "custom_id": request["custom_id"],
            "response": None,
            "error": {"code": "batch_expired", "message": "too late"},
        }
    )

    verdicts, failures = batch_judges.reconcile_batch(
        [request], [], [error], status="expired"
    )

    assert verdicts == []
    assert failures == [
        {
            "custom_id": request["custom_id"],
            "suite": "sample-suite",
            "case_id": "case-a",
            "evaluator": "goal_success",
            "status": "expired",
            "error": {"code": "batch_expired", "message": "too late"},
        }
    ]


def test_reconcile_rejects_malformed_structured_verdict():
    request = _request("sample-suite:case-a:goal_success")

    verdicts, failures = batch_judges.reconcile_batch(
        [request],
        [_result(request["custom_id"], {"reasoning": "ok", "verdict": "MAYBE"})],
        [],
        status="completed",
    )

    assert verdicts == []
    assert failures[0]["error"] == "goal-success verdict is invalid"


def test_submit_uploads_jsonl_and_writes_auditable_manifest(monkeypatch, tmp_path):
    request = _request("sample-suite:case-a:goal_success")
    uploads = []

    class FakeClient:
        class files:
            @staticmethod
            def create(*, file, purpose):
                uploads.append((file.read(), purpose))
                return SimpleNamespace(id="file-input")

        class batches:
            @staticmethod
            def create(**kwargs):
                assert kwargs["endpoint"] == "/v1/responses"
                assert kwargs["completion_window"] == "24h"
                return SimpleNamespace(id="batch-123")

    monkeypatch.setattr(batch_judges, "requests_from_report", lambda _path: [request])
    monkeypatch.setattr(batch_judges, "_client", FakeClient)

    manifest_path = batch_judges.submit([tmp_path / "report.json"], tmp_path)

    assert uploads == [(batch_judges.serialize_requests([request]).encode(), "batch")]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["batch_id"] == "batch-123"
    assert manifest["status"] is None
    assert manifest["requests"] == [request]


def test_collect_writes_only_complete_verdicts(monkeypatch, tmp_path):
    request = _request("sample-suite:case-a:goal_success")
    input_text = batch_judges.serialize_requests([request])
    output_text = _result(
        request["custom_id"], {"reasoning": "ok", "verdict": "SUCCESS"}
    )
    batch = SimpleNamespace(
        id="batch-123",
        metadata={"source": "tollchat-batch-judges-v1"},
        status="completed",
        input_file_id="input",
        output_file_id="output",
        error_file_id=None,
    )

    class FakeClient:
        class batches:
            @staticmethod
            def list(*, limit):
                assert limit == 100
                return [batch]

        class files:
            @staticmethod
            def content(file_id):
                return SimpleNamespace(
                    text={"input": input_text, "output": output_text}[file_id]
                )

    monkeypatch.setattr(batch_judges, "_client", FakeClient)

    written = batch_judges.collect(tmp_path)

    assert [path.name for path in written] == ["batch-judges-batch-123-verdicts.json"]
    report = json.loads(written[0].read_text())
    assert report["status"] == "completed"
    assert report["verdicts"][0]["parsed_verdict"] == {
        "reasoning": "ok",
        "verdict": "SUCCESS",
    }


def test_report_requests_preserve_tool_grounded_conversation(tmp_path):
    report = {
        "cases": [
            {
                "name": "case-a",
                "input": "Price this trip.",
                "actual_output": "The price is $2.",
                "expected_assertion": "The agent reports the tool price.",
                "metadata": {"batch_judge_suite": "suite-a"},
                "actual_trajectory": {
                    "traces": [
                        {
                            "spans": [
                                {
                                    "messages": [
                                        {
                                            "role": "user",
                                            "content": [
                                                {
                                                    "content_type": "text",
                                                    "text": "Price this trip.",
                                                }
                                            ],
                                        },
                                        {
                                            "role": "assistant",
                                            "content": [
                                                {
                                                    "content_type": "tool_use",
                                                    "name": "price_route",
                                                    "arguments": {"origin": "A"},
                                                }
                                            ],
                                        },
                                        {
                                            "role": "user",
                                            "content": [
                                                {
                                                    "content_type": "tool_result",
                                                    "content": '{"total_usd":"2.00"}',
                                                }
                                            ],
                                        },
                                        {
                                            "role": "assistant",
                                            "content": [
                                                {
                                                    "content_type": "text",
                                                    "text": "The price is $2.",
                                                }
                                            ],
                                        },
                                    ]
                                }
                            ]
                        }
                    ]
                },
            }
        ]
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))

    requests = batch_judges.requests_from_report(path)

    assert [request["custom_id"] for request in requests] == [
        "suite-a:case-a:goal_success",
        "suite-a:case-a:helpfulness",
    ]
    goal_prompt = requests[0]["body"]["input"]
    assert "Action: price_route({'origin': 'A'})" in goal_prompt
    assert 'Tool: {"total_usd":"2.00"}' in goal_prompt


def test_report_requests_merge_and_deduplicate_multi_turn_message_spans(tmp_path):
    def text(value: str) -> dict[str, str]:
        return {"content_type": "text", "text": value}

    report = {
        "cases": [
            {
                "name": "case-a",
                "expected_assertion": "The agent obtains the missing endpoint.",
                "actual_trajectory": {
                    "traces": [
                        {
                            "spans": [
                                {
                                    "messages": [
                                        {
                                            "role": "user",
                                            "content": [text("Need a quote.")],
                                        },
                                        {
                                            "role": "assistant",
                                            "content": [
                                                text("Where are you starting?")
                                            ],
                                        },
                                    ]
                                },
                                {
                                    "messages": [
                                        {
                                            "role": "assistant",
                                            "content": [
                                                text("Where are you starting?")
                                            ],
                                        },
                                        {
                                            "role": "user",
                                            "content": [text("At Tysons.")],
                                        },
                                        {
                                            "role": "assistant",
                                            "content": [
                                                text("Thanks, I can price it now.")
                                            ],
                                        },
                                    ]
                                },
                            ]
                        }
                    ]
                },
            }
        ]
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))

    goal_prompt = batch_judges.requests_from_report(path)[0]["body"]["input"]

    assert "User: Need a quote." in goal_prompt
    assert "User: At Tysons." in goal_prompt
    assert goal_prompt.count("Assistant: Where are you starting?") == 1

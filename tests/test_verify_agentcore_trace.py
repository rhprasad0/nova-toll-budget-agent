import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_agentcore_trace", ROOT / "scripts" / "verify_agentcore_trace.py"
)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _envelopes(
    stage: str, payload: dict[str, object], *, span_id: str
) -> list[dict[str, object]]:
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    cut = max(1, len(serialized) // 2)
    chunks = (serialized[:cut], serialized[cut:])
    return [
        {
            "record_version": 1,
            "record_type": "tollchat.runtime_trace",
            "stage": stage,
            "trace_id": "trace-1",
            "span_id": span_id,
            "session_id": "session-1",
            "aws_request_id": "request-1",
            "chunk_index": index,
            "chunk_count": len(chunks),
            "sha256": digest,
            "payload": chunk,
        }
        for index, chunk in enumerate(chunks)
    ]


def _trace() -> dict[str, object]:
    records: list[dict[str, object]] = []
    timing = {"started_at": "2026-08-07T00:00:00Z", "ended_at": "2026-08-07T00:00:01Z"}
    guardrail_response = {
        "action": "NONE",
        "actionReason": "NONE",
        "assessments": [{"contentPolicy": {"filters": []}}],
        "guardrailCoverage": {"textCharacters": {"guarded": 12, "total": 12}},
        "usage": {"topicPolicyUnits": 1},
        "outputs": [],
    }
    records += _envelopes(
        "input_guardrail",
        {
            "timing": timing,
            "request": {
                "source": "INPUT",
                "outputScope": "FULL",
                "content": [{"text": {"text": "Price a trip"}}],
            },
            "response": guardrail_response,
        },
        span_id="input",
    )
    records += _envelopes(
        "agent",
        {
            "timing": timing,
            "request": {"prompt": "Price a trip"},
            "response": {"answer": "The toll is $2.00."},
            "model_messages": [{"role": "assistant", "content": "Calling route tool"}],
            "tool_calls": [
                {
                    "name": "i95_route",
                    "arguments": {"origin": "A"},
                    "result": {"total_usd": "2.00"},
                }
            ],
            "model_version": "gpt-5",
            "system_prompt_version": "1.23.0",
            "toolset_version": "1.5.0",
        },
        span_id="agent",
    )
    records += _envelopes(
        "output_guardrail",
        {
            "timing": timing,
            "request": {
                "source": "OUTPUT",
                "outputScope": "FULL",
                "content": [{"text": {"text": "The toll is $2.00."}}],
            },
            "response": guardrail_response,
        },
        span_id="output",
    )
    records += _envelopes(
        "invoke",
        {"timing": timing, "result": {"response": "The toll is $2.00."}, "error": None},
        span_id="invoke",
    )
    return {
        "results": [
            {"field": "@message", "value": json.dumps(record)} for record in records
        ],
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace-1",
                                "spanId": "native-invoke",
                                "name": "invoke_agent",
                                "startTimeUnixNano": "1",
                                "endTimeUnixNano": "2",
                                "attributes": [
                                    {
                                        "key": "tollchat.session_id",
                                        "value": {"stringValue": "session-1"},
                                    }
                                ],
                            },
                            {
                                "traceId": "trace-1",
                                "spanId": "native-model",
                                "name": "chat_model",
                                "startTimeUnixNano": "1",
                                "endTimeUnixNano": "2",
                                "attributes": {"tollchat.session_id": "session-1"},
                            },
                            {
                                "traceId": "trace-1",
                                "spanId": "native-tool",
                                "name": "execute_tool",
                                "startTimeUnixNano": "1",
                                "endTimeUnixNano": "2",
                                "attributes": {"tollchat.session_id": "session-1"},
                            },
                        ]
                    }
                ]
            }
        ],
    }


def test_accepts_complete_chunked_transaction_search_export():
    trace = _trace()
    trace["resourceSpans"][0]["resource"] = {
        "attributes": {"aws.parameter.name": "/nova-toll/openai_api_key"}
    }

    assert verifier.verify_trace(trace) == {"traces": 1, "records": 4}


def test_accepts_direct_export_json():
    query = _trace()
    exported = {
        "records": [json.loads(result["value"]) for result in query["results"]],
        "resourceSpans": query["resourceSpans"],
    }

    assert verifier.verify_trace(exported) == {"traces": 1, "records": 4}


def test_accepts_transaction_search_span_rows():
    trace = _trace()
    del trace["resourceSpans"]
    trace["spans"] = {
        "results": [
            [
                {"field": "traceId", "value": "trace-1"},
                {"field": "spanId", "value": "native-invoke"},
                {"field": "name", "value": "invoke_agent"},
                {"field": "startTime", "value": "1"},
                {"field": "endTime", "value": "2"},
                {"field": "attributes.session.id", "value": "session-1"},
            ],
            [
                {"field": "traceId", "value": "trace-1"},
                {"field": "spanId", "value": "native-model"},
                {"field": "name", "value": "chat_model"},
                {"field": "startTime", "value": "1"},
                {"field": "endTime", "value": "2"},
                {"field": "attributes.session.id", "value": "session-1"},
            ],
            [
                {"field": "traceId", "value": "trace-1"},
                {"field": "spanId", "value": "native-tool"},
                {"field": "name", "value": "execute_tool"},
                {"field": "startTime", "value": "1"},
                {"field": "endTime", "value": "2"},
                {"field": "attributes.session.id", "value": "session-1"},
            ],
        ]
    }

    assert verifier.verify_trace(trace) == {"traces": 1, "records": 4}


def test_accepts_transaction_search_raw_message_rows():
    trace = _trace()
    spans = trace.pop("resourceSpans")[0]["scopeSpans"][0]["spans"]
    trace["spans"] = {
        "results": [
            [{"field": "@message", "value": json.dumps(span)}] for span in spans
        ]
    }

    assert verifier.verify_trace(trace) == {"traces": 1, "records": 4}


def test_rejects_trace_without_correlated_native_spans():
    trace = _trace()
    del trace["resourceSpans"]

    with pytest.raises(verifier.TraceVerificationError, match="native span"):
        verifier.verify_trace(trace)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda record: record.update(chunk_count=3), "chunk"),
        (lambda record: record.update(sha256="0" * 64), "sha256"),
        (lambda record: record.update(trace_id="wrong-trace"), "correlation"),
        (
            lambda record: record.update(payload='{"system_prompt":"do not export"}'),
            "system prompt",
        ),
        (
            lambda record: record.update(payload='{"token":"synthetic-secret-marker"}'),
            "credential",
        ),
        (
            lambda record: record.update(payload='{"authorization":"opaque-value"}'),
            "credential",
        ),
        (
            lambda record: record.update(payload='{"token":"opaque-value"}'),
            "credential",
        ),
        (
            lambda record: record.update(
                payload='{"connection":"redis://cache.example/0"}'
            ),
            "credential",
        ),
        (
            lambda record: record.update(
                payload='{"connection":"mongodb+srv://db.example/app"}'
            ),
            "credential",
        ),
        (
            lambda record: record.update(
                payload=json.dumps({"prompt": "ASIA" + "ABCDEFGHIJKLMNOP"})
            ),
            "credential",
        ),
        (
            lambda record: record.update(
                payload=json.dumps({"prompt": "gho_" + "abcdefghijklmnopqrst"})
            ),
            "credential",
        ),
        (
            lambda record: record.update(
                payload='{"role":"developer","content":"hidden instructions"}'
            ),
            "system prompt",
        ),
        (
            lambda record: record.update(
                payload='{"system_instructions":"hidden instructions"}'
            ),
            "system prompt",
        ),
    ],
)
def test_rejects_incomplete_or_unsafe_trace(mutate, message):
    trace = _trace()
    first = json.loads(trace["results"][0]["value"])
    mutate(first)
    trace["results"][0]["value"] = json.dumps(first)

    with pytest.raises(verifier.TraceVerificationError, match=message):
        verifier.verify_trace(trace)

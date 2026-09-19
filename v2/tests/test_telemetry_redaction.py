"""Exercise real OTLP serialization and both ADOT export paths without AWS."""

import io
import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Unpack, cast
from unittest.mock import Mock

import pytest
from agent.telemetry import (
    OMITTED,
    GuardrailRequest,
    RedactingExporter,
    Redactor,
    protect_console,
    wrap_exporters,
)
from amazon.opentelemetry.distro.aws_batch_unsampled_span_processor import (
    BatchUnsampledSpanProcessor,
)
from amazon.opentelemetry.distro.exporter.otlp.aws.logs._aws_cw_otlp_batch_log_record_processor import (
    AwsCloudWatchOtlpBatchLogRecordProcessor,
)
from amazon.opentelemetry.distro.exporter.otlp.aws.logs.otlp_aws_log_record_exporter import (
    OTLPAwsLogRecordExporter,
)
from opentelemetry._logs import LogRecord
from opentelemetry.exporter.otlp.proto.common._internal._log_encoder import encode_logs
from opentelemetry.exporter.otlp.proto.common._internal.trace_encoder import (
    encode_spans,
)
from opentelemetry.sdk._logs import LoggerProvider, ReadableLogRecord
from opentelemetry.sdk._logs.export import LogRecordExporter, LogRecordExportResult
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import SpanContext, Status, StatusCode, TraceFlags

# Exercise the SDK's private replacement seam, which has no public equivalent.

PII = "mary@example.com"


class Guardrail:
    def __init__(self) -> None:
        self.calls: list[GuardrailRequest] = []

    def apply_guardrail(self, **kwargs: Unpack[GuardrailRequest]) -> dict[str, object]:
        from opentelemetry.instrumentation.utils import is_instrumentation_enabled

        assert not is_instrumentation_enabled()
        self.calls.append(kwargs)
        text = kwargs["content"][0]["text"]["text"]
        if PII in text:
            return {
                "action": "GUARDRAIL_INTERVENED",
                "outputs": [{"text": text.replace(PII, "{EMAIL}")}],
            }
        return {"action": "NONE"}


class Capture(SpanExporter):
    def __init__(self) -> None:
        self.wire: list[bytes] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.wire.append(encode_spans(spans).SerializeToString())
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class LogCapture(LogRecordExporter):
    def __init__(self) -> None:
        self.wire: list[bytes] = []

    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        self.wire.append(encode_logs(batch).SerializeToString())
        return LogRecordExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def span(sampled: bool = True) -> ReadableSpan:
    return ReadableSpan(
        name="invoke_agent",
        context=SpanContext(1, 2, False, TraceFlags(1 if sampled else 0)),
        resource=Resource({"service.name": "tollchat", "unsafe": PII}),
        attributes={
            "gen_ai.input.messages": json.dumps(
                [{"role": "user", "content": f"Hello José, email {PII}"}]
            ),
            "gen_ai.tool.call.arguments": json.dumps({"contact": {"email": PII}}),
            "gen_ai.usage.input_tokens": 42,
        },
        events=[Event("tool_result", {"result": PII})],
        status=Status(StatusCode.ERROR, f"failed for {PII}"),
        start_time=1,
        end_time=10,
    )


def test_export_copies_redact_nested_content_without_mutating_agent_data() -> None:
    original = span()
    capture, client = Capture(), Guardrail()
    result = RedactingExporter(capture, client, "guardrail", "1").export([original])
    assert result is SpanExportResult.SUCCESS
    wire = b"".join(capture.wire)
    assert PII.encode() not in wire and b"{EMAIL}" in wire
    assert b"tollchat" in wire and b"gen_ai.usage.input_tokens" in wire
    assert original.attributes is not None
    assert PII in str(original.attributes["gen_ai.input.messages"])
    assert original.events[0].attributes is not None
    assert original.events[0].attributes["result"] == PII
    assert original.resource.attributes["unsafe"] == PII
    assert all(call["outputScope"] == "INTERVENTIONS" for call in client.calls)


def test_large_static_agent_metadata_is_compacted_before_redaction() -> None:
    original = span()
    system_prompt = "source-controlled system prompt " * 1_000
    original._attributes = {  # pyright: ignore[reportPrivateUsage]
        **(original.attributes or {}),
        "gen_ai.agent.tools": json.dumps(
            ["get_current_toll_price", "get_annual_toll_ballpark"]
        ),
        "system_prompt": system_prompt,
    }
    original._events = [  # pyright: ignore[reportPrivateUsage]
        Event("gen_ai.system.message", {"content": system_prompt}),
        Event("gen_ai.user.message", {"content": PII}),
    ]
    capture, client = Capture(), Guardrail()

    result = RedactingExporter(capture, client, "guardrail", "1").export([original])

    assert result is SpanExportResult.SUCCESS
    wire = b"".join(capture.wire)
    assert b"tollchat.agent.tool_names" in wire
    assert b"get_current_toll_price" in wire
    assert b"get_annual_toll_ballpark" in wire
    assert b"gen_ai.agent.tools" not in wire
    assert system_prompt.encode() not in wire
    assert OMITTED.encode() not in wire
    assert PII.encode() not in wire and b"{EMAIL}" in wire
    assert all(
        len(call["content"][0]["text"]["text"]) <= 10_000 for call in client.calls
    )
    assert original.attributes is not None
    assert original.attributes["system_prompt"] == system_prompt
    assert original.attributes["gen_ai.agent.tools"] == json.dumps(
        ["get_current_toll_price", "get_annual_toll_ballpark"]
    )
    assert original.events[0].attributes is not None
    assert original.events[0].attributes["content"] == system_prompt


def test_malformed_tool_metadata_fails_closed() -> None:
    item = span()
    item._attributes = {"gen_ai.agent.tools": f"not json {PII}"}  # pyright: ignore[reportPrivateUsage]

    safe = Redactor(Guardrail(), "id", "1").span(item)

    assert safe.attributes == {"tollchat.agent.tool_names": OMITTED}
    assert item.attributes == {"gen_ai.agent.tools": f"not json {PII}"}


@pytest.mark.parametrize(
    "response",
    cast(
        list[dict[str, object]],
        [
            {},
            {"action": "GUARDRAIL_INTERVENED"},
            {"action": "GUARDRAIL_INTERVENED", "outputs": [{}]},
            {"action": "GUARDRAIL_INTERVENED", "outputs": ["invalid"]},
        ],
    ),
)
def test_fail_closed_for_malformed_responses(response: dict[str, object]) -> None:
    client = Mock()
    client.apply_guardrail.return_value = response
    assert Redactor(client, "id", "1").text(PII) == OMITTED


def test_timeout_size_budget_and_cache_do_not_return_raw_content() -> None:
    client = Mock()
    client.apply_guardrail.side_effect = TimeoutError(PII)
    redactor = Redactor(client, "id", "1")
    assert redactor.text(PII) == OMITTED
    assert redactor.text(PII) == OMITTED
    assert client.apply_guardrail.call_count == 1
    assert redactor.text("a" * 10001) == OMITTED
    redactor.deadline = 0
    assert redactor.text("new private text") == OMITTED
    assert client.apply_guardrail.call_count == 1


def test_real_sampled_unsampled_and_aws_log_processors_are_all_wrapped() -> None:
    provider, logs = TracerProvider(), LoggerProvider()
    sampled, unsampled, log_capture = Capture(), Capture(), LogCapture()
    first = BatchSpanProcessor(sampled)
    second = BatchUnsampledSpanProcessor(unsampled)
    third = AwsCloudWatchOtlpBatchLogRecordProcessor(
        cast(OTLPAwsLogRecordExporter, log_capture)
    )
    provider.add_span_processor(first)
    provider.add_span_processor(second)
    logs.add_log_record_processor(third)
    try:
        assert wrap_exporters(provider, logs, Guardrail(), "id", "1") == 3
        first.on_end(span())
        second.on_end(span(False))
        provider.force_flush()
        record = ReadableLogRecord(
            LogRecord(body={"messages": [PII]}, timestamp=1), Resource({})
        )
        third._batch_processor.emit(record)  # pyright: ignore[reportPrivateUsage]
        third.force_flush()
        for capture in (sampled, unsampled, log_capture):
            assert capture.wire
            assert PII.encode() not in b"".join(capture.wire)
    finally:
        provider.shutdown()
        logs.shutdown()


def test_unknown_processor_rejected_before_partial_installation() -> None:
    provider, logs = TracerProvider(), LoggerProvider()
    capture = Capture()
    batch = BatchSpanProcessor(capture)
    provider.add_span_processor(batch)
    provider.add_span_processor(SpanProcessor())
    try:
        with pytest.raises(RuntimeError, match="unsupported telemetry processor"):
            wrap_exporters(provider, logs, Guardrail(), "id", "1")
        assert batch.span_exporter is capture
    finally:
        provider.shutdown()
        logs.shutdown()


def test_console_exception_and_message_are_never_written_raw() -> None:
    original_factory = logging.getLogRecordFactory()
    stream = io.StringIO()
    logger = logging.getLogger("pii-console-test")
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.propagate = False
    try:
        protect_console()
        try:
            raise ValueError(PII)
        except ValueError:
            logger.exception("bad payload %s", PII)
        assert PII not in stream.getvalue()
        assert "runtime_log_content_omitted" in stream.getvalue()
    finally:
        logging.setLogRecordFactory(original_factory)
        logger.removeHandler(handler)


def test_real_application_startup_installs_protected_exporters() -> None:
    # Providers are process globals, so exercise actual auto-instrumentation in isolation.
    code = """
from unittest.mock import Mock, patch
import requests
from agent import telemetry
client = Mock()
client.apply_guardrail.return_value = {"action": "NONE"}
with patch.object(telemetry.boto3, "client", return_value=client), patch.object(requests.Session, "send", side_effect=RuntimeError("network disabled")):
    import agent.agentcore_entrypoint
    from opentelemetry import trace
    from opentelemetry._logs import get_logger_provider
    providers = (trace.get_tracer_provider(), get_logger_provider())
    batches = [p._batch_processor for p in providers[0]._active_span_processor._span_processors if hasattr(p, "_batch_processor")]
    batches += [p._batch_processor for p in providers[1]._multi_log_record_processor._log_record_processors]
    assert batches and all(isinstance(p._exporter, telemetry.RedactingExporter) for p in batches)
    assert telemetry.os.environ["OTEL_METRICS_EXPORTER"] == "none"
    parent = trace.NonRecordingSpan(trace.SpanContext(
        trace_id=1, span_id=2, is_remote=True, trace_flags=trace.TraceFlags(0)
    ))
    with trace.get_tracer('archive-check').start_as_current_span(
        'unsampled-parent-check', context=trace.set_span_in_context(parent)
    ) as span:
        assert span.is_recording() and span.get_span_context().trace_flags.sampled
    for provider in providers:
        provider.shutdown()
print("protected startup passed")
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AWS_", "OTEL_", "TOLLCHAT_", "UNIFIED_"))
    }
    environment.update(
        {
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "UNIFIED_TRACES_DESTINATION_ENABLED": "true",
            "TOLLCHAT_TELEMETRY_GUARDRAIL_ID": "test",
            "TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert "protected startup passed" in result.stdout

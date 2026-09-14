"""Redact telemetry copies before ADOT exports them; never change agent state."""

# ruff: noqa: ANN401
# ADOT/OTel expose no exporter-replacement API. The small wiring adapter below
# is version-locked and tested against both AWS and upstream batch processors.
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from copy import copy
from dataclasses import replace
from importlib.metadata import version
from time import monotonic
from typing import Any, cast

import boto3
from botocore.config import Config
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import Link, Status

OMITTED = "[CONTENT OMITTED: redaction unavailable]"
MAX_TEXT = 10_000
BATCH_SECONDS = 30
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
# These resource values are deployment metadata, never invocation input.
_RESOURCE_KEYS = {
    "service.name",
    "service.namespace",
    "service.version",
    "cloud.provider",
    "cloud.platform",
    "cloud.region",
    "cloud.account.id",
    "cloud.resource_id",
    "aws.log.group.names",
    "aws.log.stream.names",
    "aws.local.service",
    "aws.ai.agent.type",
    "telemetry.sdk.name",
    "telemetry.sdk.language",
    "telemetry.sdk.version",
    "telemetry.auto.version",
    "deployment.environment.name",
}
_STATIC_VALUES = {
    "openai",
    "aws.bedrock",
    "gpt-5.6-luna",
    "chat",
    "invoke_agent",
    "execute_tool",
    "get_current_toll_price",
    "get_annual_toll_ballpark",
    "validate_toll_route",
    "assistant",
    "user",
    "system",
    "tool",
    "text",
    "function",
    "stop",
    "end_turn",
}
_DIAGNOSTICS = {
    "telemetry_redaction_failed",
    "telemetry_redaction_omitted",
    "telemetry_export_failed",
    "telemetry_redaction_ready",
}
_logger = logging.getLogger(__name__)
_logger.propagate = False  # Redaction failures must not create more OTLP work.
_logger.addHandler(logging.StreamHandler())
_STATIC_VALUES.update(
    _DIAGNOSTICS
    | {
        "runtime_log_content_omitted",
        "INFO",
        "WARN",
        "WARNING",
        "ERROR",
        "DEBUG",
        "CRITICAL",
    }
)


def protect_console() -> None:
    """Console logging has no pre-export worker: retain only static diagnostics.

    Applied at record creation, including non-propagating SDK loggers and future
    handlers. Detailed payloads/errors remain available in redacted OTLP traces.
    """
    factory = logging.getLogRecordFactory()

    def record(*args: Any, **kwargs: Any) -> logging.LogRecord:
        item = factory(*args, **kwargs)
        diagnostic = (
            item.name == __name__
            and isinstance(item.msg, str)
            and item.msg in _DIAGNOSTICS
            and not item.args
        )
        item.msg = item.msg if diagnostic else "runtime_log_content_omitted"
        item.args = ()
        item.exc_info = item.exc_text = item.stack_info = None
        return item

    logging.setLogRecordFactory(record)


class Redactor:
    """One batch, one bounded in-memory cache; failures never return raw text."""

    def __init__(self, client: Any, guardrail_id: str, guardrail_version: str) -> None:
        self.client = client
        self.guardrail_id = guardrail_id
        self.guardrail_version = guardrail_version
        self.deadline = monotonic() + BATCH_SECONDS
        self.cache: dict[str, str] = {}

    def text(self, value: str) -> str:
        if not value or value in _STATIC_VALUES or value == OMITTED:
            return value
        if value in self.cache:
            return self.cache[value]
        if len(value) > MAX_TEXT or monotonic() + 10 > self.deadline:
            _logger.warning("telemetry_redaction_omitted")
            return OMITTED
        result = OMITTED
        try:
            with suppress_instrumentation():
                response = self.client.apply_guardrail(
                    guardrailIdentifier=self.guardrail_id,
                    guardrailVersion=self.guardrail_version,
                    source="OUTPUT",
                    outputScope="INTERVENTIONS",
                    content=[{"text": {"text": value}}],
                )
            if response.get("action") == "NONE":
                result = value
            elif response.get("action") == "GUARDRAIL_INTERVENED":
                outputs = response.get("outputs")
                if (
                    isinstance(outputs, list)
                    and len(outputs) == 1
                    and isinstance(outputs[0].get("text"), str)
                    and outputs[0]["text"]
                ):
                    result = outputs[0]["text"]
        except Exception:
            pass  # Do not expose exception text, request bodies, or assessments.
        if result == OMITTED:
            _logger.warning("telemetry_redaction_failed")
        self.cache[value] = result
        return result

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            # Scan serialized content together so detection keeps its context.
            return self.text(value)
        if isinstance(value, (dict, list, tuple)):
            try:
                encoded = json.dumps(value, ensure_ascii=False)
                masked = self.text(encoded)
                return json.loads(masked) if masked != OMITTED else OMITTED
            except (TypeError, ValueError, RecursionError):
                return OMITTED
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            masked = self.text(str(value))
            return value if masked == str(value) else masked
        return OMITTED

    def attributes(self, attributes: Mapping[str, Any] | None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        content: dict[str, Any] = {}
        for key, value in (attributes or {}).items():
            if (
                key in {"session.id", "gen_ai.conversation.id"}
                and isinstance(value, str)
                and _UUID.fullmatch(value)
            ) or (key.startswith("gen_ai.usage.") and isinstance(value, (int, float))):
                result[key] = value
            elif key in {
                "tollchat.system_prompt_version",
                "tollchat.system_prompt_renderer_version",
                "tollchat.system_prompt_sha256",
            }:
                # Contract hashes/versions are fixed application metadata.
                result[key] = value
            else:
                content[key] = value
        if content:
            # One request preserves context and covers dynamic keys as well as values.
            masked = self.value(content)
            result.update(
                masked if isinstance(masked, dict) else {"redacted.content": OMITTED}
            )
        return result

    def scope(self, scope: InstrumentationScope | None) -> InstrumentationScope | None:
        if scope is None:
            return None
        return InstrumentationScope(
            self.text(scope.name),
            self.text(scope.version) if scope.version else None,
            attributes=self.attributes(scope.attributes),
        )

    def resource(self, resource: Resource) -> Resource:
        return Resource(
            {k: v for k, v in resource.attributes.items() if k in _RESOURCE_KEYS}
        )

    def span(self, span: ReadableSpan) -> ReadableSpan:
        # Copy every mutable payload container; sibling exporters still see the original.
        result = copy(span)
        result._name = self.text(span.name)
        result._attributes = self.attributes(span.attributes)
        result._resource = self.resource(span.resource)
        result._events = [
            Event(self.text(e.name), self.attributes(e.attributes), e.timestamp)
            for e in span.events
        ]
        result._links = [
            Link(link.context, self.attributes(link.attributes)) for link in span.links
        ]
        result._status = Status(
            span.status.status_code,
            self.text(span.status.description) if span.status.description else None,
        )
        result._instrumentation_scope = self.scope(span.instrumentation_scope)
        return result

    def log(self, record: ReadableLogRecord) -> ReadableLogRecord:
        log = copy(record.log_record)
        log.body = self.value(log.body)
        log.attributes = self.attributes(log.attributes)
        log.severity_text = self.text(log.severity_text) if log.severity_text else None
        return replace(
            record,
            log_record=log,
            resource=self.resource(record.resource),
            instrumentation_scope=self.scope(record.instrumentation_scope),
        )


class RedactingExporter:
    """Delegate only sanitized copies to the existing AWS exporter."""

    def __init__(
        self, exporter: Any, client: Any, guardrail_id: str, guardrail_version: str
    ) -> None:
        self.exporter = exporter
        self.client = client
        self.guardrail_id = guardrail_id
        self.guardrail_version = guardrail_version

    def export(self, batch: Sequence[Any]) -> Any:
        redactor = Redactor(self.client, self.guardrail_id, self.guardrail_version)
        try:
            safe = [
                redactor.span(item)
                if isinstance(item, ReadableSpan)
                else redactor.log(item)
                for item in batch
            ]
            with suppress_instrumentation():
                return self.exporter.export(safe)
        except Exception:
            _logger.error("telemetry_export_failed")
            # OTel workers handle export failure; there is deliberately no raw fallback.
            from opentelemetry.sdk._logs.export import LogRecordExportResult
            from opentelemetry.sdk.trace.export import SpanExportResult

            return (
                SpanExportResult.FAILURE
                if isinstance(self.exporter, SpanExporter)
                else LogRecordExportResult.FAILURE
            )

    def shutdown(self, *args: Any, **kwargs: Any) -> Any:
        return self.exporter.shutdown(*args, **kwargs)

    def force_flush(self, *args: Any, **kwargs: Any) -> Any:
        return self.exporter.force_flush(*args, **kwargs)


def wrap_exporters(
    provider: Any,
    log_provider: Any,
    client: Any,
    guardrail_id: str,
    guardrail_version: str,
) -> int:
    """Version-specific wiring; validate the whole graph before changing it."""
    from amazon.opentelemetry.distro.gen_ai_nested_client_span_processor import (
        GenAiNestedClientSpanProcessor,
    )
    from opentelemetry.processor.baggage import BaggageSpanProcessor

    spans = provider._active_span_processor._span_processors
    logs = log_provider._multi_log_record_processor._log_record_processors
    targets = []
    for processor in (*spans, *logs):
        if type(processor) in (GenAiNestedClientSpanProcessor, BaggageSpanProcessor):
            continue
        if not isinstance(processor, (BatchSpanProcessor, BatchLogRecordProcessor)):
            raise RuntimeError("unsupported telemetry processor")
        batch = processor._batch_processor
        if not isinstance(batch._exporter, (SpanExporter, LogRecordExporter)):
            raise RuntimeError("unsupported telemetry exporter")
        if (
            hasattr(processor, "_exporter")
            and cast(Any, processor)._exporter is not batch._exporter
        ):
            raise RuntimeError("inconsistent telemetry exporter")
        targets.append((processor, batch))
    if not targets or not any(isinstance(p, BatchSpanProcessor) for p, _ in targets):
        raise RuntimeError("missing trace exporter")
    for processor, batch in targets:
        with batch._export_lock:
            wrapped = RedactingExporter(
                batch._exporter, client, guardrail_id, guardrail_version
            )
            batch._exporter = wrapped
            if hasattr(processor, "_exporter"):
                processor._exporter = (
                    wrapped  # AWS size-aware log batches use this second reference.
                )
    return len(targets)


def initialize() -> None:
    protect_console()
    try:
        if (
            version("aws-opentelemetry-distro") != "0.19.0"
            or version("opentelemetry-sdk") != "1.44.0"
        ):
            raise RuntimeError("unsupported telemetry version")
        guardrail_id = os.environ["TOLLCHAT_TELEMETRY_GUARDRAIL_ID"]
        guardrail_version = os.environ["TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION"]
        if not guardrail_id or not guardrail_version or guardrail_version == "DRAFT":
            raise RuntimeError("missing telemetry guardrail")
        # One known exporter graph. Do not enable extra service-event/metric pipelines.
        os.environ["AGENT_OBSERVABILITY_ENABLED"] = "true"
        os.environ["OTEL_PYTHON_DISTRO"] = "aws_distro"
        os.environ["OTEL_PYTHON_CONFIGURATOR"] = "aws_configurator"
        os.environ["OTEL_TRACES_SAMPLER"] = "always_on"
        os.environ["OTEL_METRICS_EXPORTER"] = "none"
        os.environ["OTEL_AWS_APPLICATION_SIGNALS_ENABLED"] = "false"
        os.environ["OTEL_AWS_SERVICE_EVENTS_ENABLED"] = "false"
        os.environ["OTEL_AWS_EXPERIMENTAL_CODE_ATTRIBUTES"] = "false"
        os.environ["OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED"] = "true"
        from opentelemetry.instrumentation.auto_instrumentation import (
            initialize as initialize_adot,
        )

        initialize_adot(swallow_exceptions=False)
        with suppress_instrumentation():
            client = boto3.client(
                "bedrock-runtime",
                config=Config(
                    connect_timeout=5,
                    read_timeout=5,
                    retries={"total_max_attempts": 1},
                ),
            )
        wrap_exporters(
            trace.get_tracer_provider(),
            get_logger_provider(),
            client,
            guardrail_id,
            guardrail_version,
        )
    except Exception:
        _logger.error("telemetry_redaction_failed")
        # Stop before importing/serving the application if the export boundary is unknown.
        raise RuntimeError("telemetry protection initialization failed") from None
    _logger.warning("telemetry_redaction_ready")

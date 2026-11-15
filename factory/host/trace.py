import http.client
import json
import os
import time
import urllib.request

ENDPOINT = os.environ.get("FACTORY_OTLP_TRACES", "http://127.0.0.1:4318/v1/traces")


def new_id(size: int) -> str:
    return os.urandom(size).hex()


def traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


def now_ns() -> int:
    return time.time_ns()


def value(item: str | int | bool) -> dict[str, str | bool]:
    if isinstance(item, bool):
        return {"boolValue": item}
    if isinstance(item, int):
        return {"intValue": str(item)}
    return {"stringValue": item}


def send(
    trace_id: str,
    span_id: str,
    parent_id: str | None,
    name: str,
    start_ns: int,
    end_ns: int,
    attributes: dict[str, str | int | bool],
) -> bool:
    span: dict[str, object] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": [{"key": k, "value": value(v)} for k, v in attributes.items()],
    }
    if parent_id:
        span["parentSpanId"] = parent_id
    body = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": value("factory-dispatcher")}
                    ]
                },
                "scopeSpans": [{"scope": {"name": "factory"}, "spans": [span]}],
            }
        ]
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except (OSError, http.client.HTTPException, ValueError):
        return False

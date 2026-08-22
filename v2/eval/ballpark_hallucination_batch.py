# pyright: basic
"""Prepare, submit, collect, and grade the frozen annual-ballpark Batch eval."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import boto3
import tiktoken
from openai import OpenAI
from strands.types.tools import ToolResult, ToolUse

_V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2_ROOT))

from agent import toll_agent  # noqa: E402
from agent_tools import get_annual_toll_ballpark as ballpark  # noqa: E402
from eval.run_evaluation import evaluate_annual_turn  # noqa: E402

_MODEL = "gpt-5.6-luna"
_ENDPOINT = "/v1/responses"
_SOURCE = "tollchat-v2-ballpark-hallucination"
_OPENAI_BASE_URL = "https://api.openai.com/v1"
_REQUEST_LIMIT = 50_000
_FILE_LIMIT = 200_000_000
_QUEUE_LIMIT = 40_000_000
_GUARD_PERCENT = 10
_TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}
_FIXTURE_PATH = Path(__file__).with_name("ballpark-hallucination-cases.jsonl")
_RUN_DIR = Path(__file__).with_name("private") / "annual-ballpark-hallucination"
_MONEY = re.compile(
    r"(?:(?<!\w)\$\s*|\bUSD\s+)([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,3})?)",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*%")
_COVERAGE = re.compile(r"\b([0-9]+)\s+(?:of|out of)\s+([0-9]+)\b", re.I)
_DATE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b")
_TIME = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s*[AP]M)?\b", re.I)

_BALLPARK_REQUEST = {
    "outbound": {
        "origin_point_id": "i95:206NO",
        "destination_point_id": "i495:185ND",
        "departure_time": "08:30:00",
    },
    "return": {
        "origin_point_id": "i495:185SO",
        "destination_point_id": "i95:206SD",
        "departure_time": "17:30:00",
    },
    "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "planned_annual_commute_days": 240,
    "gross_annual_income_usd": "120000.00",
}
_PROMPTS = (
    "I'm considering a $120,000 job near Westpark Drive. I live near "
    "Springfield-Franconia, commute Monday through Friday, leave at 8:30 AM, "
    "return at 5:30 PM, and plan 240 office days a year. What does the tolled "
    "commute do to my income?",
    "Help me budget for a Springfield-Franconia to Westpark Drive commute. I "
    "earn $120,000, travel Monday through Friday at 8:30 AM and 5:30 PM, and "
    "expect 240 commute days. Show the daily, monthly, and annual ballpark.",
    "I'm negotiating a $120,000 Westpark Drive job while living near "
    "Springfield-Franconia. For 240 Monday-Friday commutes leaving at 8:30 AM "
    "and returning at 5:30 PM, how much additional gross income would offset "
    "the tolled commute?",
    "For Springfield-Franconia to Westpark Drive at 8:30 AM and back at 5:30 "
    "PM Monday-Friday, compare the P25, P50, and P90 annual affordability "
    "outcomes using $120,000 income and 240 commute days.",
    "Use only the supplied TollChat ballpark evidence—do not guess or forecast. "
    "For a $120,000 income and 240 Monday-Friday Springfield-Franconia to "
    "Westpark commutes at 8:30 AM and 5:30 PM, give the exact supported figures, "
    "coverage, and assumptions.",
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _encoding() -> tiktoken.Encoding:
    return tiktoken.encoding_for_model(_MODEL)


def _model() -> toll_agent._CachedResponsesModel:  # pyright: ignore[reportPrivateUsage]
    return toll_agent._CachedResponsesModel(  # pyright: ignore[reportPrivateUsage]
        model_id=_MODEL,
        client_args={"api_key": "offline", "base_url": _OPENAI_BASE_URL},
        params={
            "max_output_tokens": 2048,
            "reasoning": {"effort": "low"},
            "prompt_cache_key": "tollchat-agent-v2",
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        },
        stateful=True,
    )


def _tool_payload(case: dict[str, Any]) -> dict[str, Any]:
    result = cast(dict[str, Any], cast(dict[str, Any], case["source"])["tool_result"])
    for content in cast(list[dict[str, Any]], result.get("content", [])):
        if isinstance(content.get("json"), dict):
            return cast(dict[str, Any], content["json"])
    raise ValueError("fixture has no JSON tool result")


def build_requests(
    case: dict[str, Any], system_prompt: str, *, repetitions: int = 200
) -> list[dict[str, Any]]:
    """Expand one reviewed fixture into production-shaped Batch requests."""
    prompts = cast(list[str], case.get("prompts"))
    if len(prompts) != 5 or repetitions < 1:
        raise ValueError("fixture needs five prompts and positive repetitions")
    tool_result = cast(
        dict[str, Any], cast(dict[str, Any], case["source"])["tool_result"]
    )
    tool_use_id = cast(str, tool_result["toolUseId"])
    request = cast(dict[str, Any], case["request"])
    model = _model()
    tool_specs = [
        tool.tool_spec
        for tool in toll_agent._AGENT_TOOLS  # pyright: ignore[reportPrivateUsage]
    ]
    requests: list[dict[str, Any]] = []
    for variant, prompt in enumerate(prompts, 1):
        messages = [
            {"role": "user", "content": [{"text": prompt}]},
            {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": "get_annual_toll_ballpark",
                            "input": request,
                        }
                    }
                ],
            },
            {"role": "user", "content": [{"toolResult": tool_result}]},
        ]
        production = model._format_request(  # pyright: ignore[reportPrivateUsage]
            cast(Any, messages), cast(Any, tool_specs), system_prompt
        )
        for repetition in range(1, repetitions + 1):
            body = copy.deepcopy(production)
            body.pop("stream")
            body["store"] = False
            body["tool_choice"] = "none"
            body["metadata"] = {
                "suite": "v2_ballpark_hallucination",
                "case_id": case["id"],
                "variant": str(variant),
                "repetition": f"{repetition:03d}",
            }
            requests.append(
                {
                    "custom_id": (f"{case['id']}:v{variant}:r{repetition:03d}"),
                    "method": "POST",
                    "url": _ENDPOINT,
                    "body": body,
                }
            )
    custom_ids = [request["custom_id"] for request in requests]
    if len(custom_ids) != len(set(custom_ids)):
        raise ValueError("Batch custom_id values must be unique")
    return requests


def serialize_requests(requests: list[dict[str, Any]]) -> str:
    """Serialize validated Responses requests as one JSONL packet."""
    if not requests:
        raise ValueError("Batch packet is empty")
    for request in requests:
        body = cast(dict[str, Any], request.get("body"))
        if (
            request.get("method") != "POST"
            or request.get("url") != _ENDPOINT
            or body.get("model") != _MODEL
        ):
            raise ValueError("Batch rows must target the Luna Responses endpoint")
    return "".join(f"{_json(request)}\n" for request in requests)


def _rows(text: str) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], json.loads(line))
        for line in text.splitlines()
        if line.strip()
    ]


def preflight(packet: str) -> dict[str, Any]:
    """Measure the exact serialized packet with tiktoken."""
    requests = _rows(packet)
    custom_ids = [request.get("custom_id") for request in requests]
    if len(custom_ids) != len(set(custom_ids)):
        raise ValueError("Batch custom_id values must be unique")
    if any(
        request.get("method") != "POST"
        or request.get("url") != _ENDPOINT
        or cast(dict[str, Any], request.get("body") or {}).get("model") != _MODEL
        for request in requests
    ):
        raise ValueError("packet contains a non-Luna Responses request")
    tokens = len(_encoding().encode(packet))
    return {
        "request_count": len(requests),
        "jsonl_bytes": len(packet.encode()),
        "jsonl_sha256": _sha256(packet),
        "tiktoken_version": tiktoken.__version__,
        "encoding": _encoding().name,
        "tiktoken_tokens": tokens,
        "guarded_queued_tokens": (tokens * (100 + _GUARD_PERCENT) + 99) // 100,
    }


def enforce_limits(
    report: dict[str, Any], *, active_queued_tokens: int
) -> dict[str, Any]:
    """Apply official Batch limits and the selected 10% token guard."""
    if int(report["request_count"]) > _REQUEST_LIMIT:
        raise ValueError("Batch request count exceeds 50,000")
    if int(report["jsonl_bytes"]) > _FILE_LIMIT:
        raise ValueError("Batch input exceeds 200,000,000 bytes")
    tokens = int(report["tiktoken_tokens"])
    guarded = ((tokens + active_queued_tokens) * (100 + _GUARD_PERCENT) + 99) // 100
    if guarded > _QUEUE_LIMIT:
        detail = " including active Luna batches" if active_queued_tokens else ""
        raise ValueError(f"guarded queued input{detail} exceeds 40,000,000 tokens")
    return {
        **report,
        "active_luna_tokens": active_queued_tokens,
        "guarded_combined_queued_tokens": guarded,
        "tier3_limit_tokens": _QUEUE_LIMIT,
    }


def active_luna_tokens(client: Any) -> int:  # noqa: ANN401
    """Conservatively count complete input files for nonterminal Luna batches."""
    encoding = _encoding()
    tokens = 0
    for item in client.batches.list(limit=100):
        if getattr(item, "status", "") in _TERMINAL_STATUSES:
            continue
        text = cast(str, client.files.content(item.input_file_id).text)
        for line in text.splitlines():
            if not line.strip():
                continue
            row = cast(dict[str, Any], json.loads(line))
            body = cast(dict[str, Any], row.get("body") or {})
            if body.get("model") == _MODEL:
                tokens += len(encoding.encode(f"{line}\n"))
    return tokens


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _visit(value: object, visit: Callable[[str, object], None]) -> None:
    if isinstance(value, dict):
        for key, child in cast(dict[str, object], value).items():
            visit(key, child)
            _visit(child, visit)
    elif isinstance(value, list):
        for child in cast(list[object], value):
            _visit(child, visit)


def _allowed_numbers(case: dict[str, Any]) -> tuple[set[Decimal], set[Decimal]]:
    money: set[Decimal] = set()
    percent: set[Decimal] = set()

    def collect(key: str, value: object) -> None:
        if not isinstance(value, (str, int, float, Decimal)):
            return
        try:
            number = Decimal(str(value))
        except Exception:
            return
        if key.endswith("_usd"):
            money.add(number)
        if key.endswith("_percent"):
            percent.add(number)

    _visit(case, collect)
    return money, percent


def _allowed_coverage(case: dict[str, Any]) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            complete = value.get("complete_pair_count")
            eligible = value.get("eligible_date_count")
            if isinstance(complete, int) and isinstance(eligible, int):
                pairs.add((complete, eligible))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(case)
    fraction = re.compile(r"\b(\d+)/(\d+)\b")

    def collect_fraction(_key: str, value: object) -> None:
        if isinstance(value, str):
            pairs.update(
                (int(match[1]), int(match[2])) for match in fraction.finditer(value)
            )

    _visit(case, collect_fraction)
    return pairs


def _date_value(value: str) -> str | None:
    try:
        if "/" in value:
            month, day, year = (int(part) for part in value.split("/"))
            return date(year, month, day).isoformat()
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _time_value(value: str) -> str | None:
    candidate = value.strip().upper().replace(" ", "")
    if not re.fullmatch(
        r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:AM|PM)?", candidate
    ):
        return None
    try:
        if candidate.endswith(("AM", "PM")):
            clock, meridiem = candidate[:-2], candidate[-2:]
            hour, minute = (int(part) for part in clock.split(":"))
            hour = hour % 12 + (12 if meridiem == "PM" else 0)
            parsed = time(hour, minute)
        else:
            parsed = time.fromisoformat(candidate)
        return parsed.replace(microsecond=0).isoformat()
    except ValueError:
        return None


def _allowed_dates_times(case: dict[str, Any]) -> tuple[set[str], set[str]]:
    dates: set[str] = set()
    times: set[str] = set()

    def collect(_key: str, value: object) -> None:
        if not isinstance(value, str):
            return
        if parsed := _date_value(value):
            dates.add(parsed)
        if "T" in value:
            try:
                parsed = datetime.fromisoformat(value).time().replace(microsecond=0)
                times.add(parsed.isoformat())
            except ValueError:
                pass
        elif parsed_time := _time_value(value):
            times.add(parsed_time)

    _visit(case, collect)
    return dates, times


def find_unsupported_claims(text: str, case: dict[str, Any]) -> dict[str, list[str]]:
    """Find quantitative claims that are absent from the frozen evidence."""
    allowed_money, allowed_percent = _allowed_numbers(case)
    allowed_dates, allowed_times = _allowed_dates_times(case)
    unsupported_dates: set[str] = set()
    for raw in _DATE.findall(text):
        parsed = _date_value(raw)
        if parsed is not None and parsed not in allowed_dates:
            unsupported_dates.add(parsed)
    unsupported_times: set[str] = set()
    for raw in _TIME.findall(text):
        parsed = _time_value(raw)
        if parsed is not None and parsed not in allowed_times:
            unsupported_times.add(parsed)
    claims = {
        "money": sorted(
            {
                _decimal_text(value)
                for raw in _MONEY.findall(text)
                if (value := Decimal(raw.replace(",", ""))) not in allowed_money
            }
        ),
        "percent": sorted(
            {
                _decimal_text(value)
                for raw in _PERCENT.findall(text)
                if (value := Decimal(raw)) not in allowed_percent
            }
        ),
        "coverage": sorted(
            {
                match.group()
                for match in _COVERAGE.finditer(text)
                if (int(match[1]), int(match[2])) not in _allowed_coverage(case)
            }
        ),
        "dates": sorted(unsupported_dates),
        "times": sorted(unsupported_times),
    }
    return {name: values for name, values in claims.items() if values}


def _output_text(body: dict[str, Any]) -> str:
    return "".join(
        str(content.get("text", ""))
        for output in cast(list[dict[str, Any]], body.get("output", []))
        for content in cast(list[dict[str, Any]], output.get("content", []))
        if content.get("type") == "output_text"
    )


def reconcile_outputs(
    requests: list[dict[str, Any]],
    output_lines: list[str],
    error_lines: list[str],
    *,
    status: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map unordered Batch output and errors to the exact input IDs."""
    expected = {cast(str, request["custom_id"]): request for request in requests}
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for result in [*_rows("\n".join(output_lines)), *_rows("\n".join(error_lines))]:
        custom_id = result.get("custom_id")
        if not isinstance(custom_id, str) or custom_id not in expected:
            raise ValueError(f"unknown custom_id in Batch output: {custom_id!r}")
        if custom_id in seen:
            raise ValueError(f"duplicate custom_id in Batch output: {custom_id}")
        seen.add(custom_id)
        response = result.get("response")
        response_data = response if isinstance(response, dict) else {}
        if result.get("error") is not None or response_data.get("status_code") != 200:
            failures.append(
                {
                    "custom_id": custom_id,
                    "status": status,
                    "error": result.get("error") or response,
                }
            )
        else:
            rows.append(result)
    missing = sorted(set(expected) - seen)
    if status == "completed" and missing:
        raise ValueError(f"missing custom_id values: {', '.join(missing)}")
    failures.extend(
        {
            "custom_id": custom_id,
            "status": status,
            "error": {"code": f"batch_{status}"},
        }
        for custom_id in missing
    )
    rows.sort(key=lambda row: cast(str, row["custom_id"]))
    failures.sort(key=lambda row: cast(str, row["custom_id"]))
    return rows, failures


def grade_outputs(case: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply unsupported-claim and existing annual-response gates."""
    counts: Counter[str] = Counter(responses=len(rows))
    usage: Counter[str] = Counter()
    verdicts: list[dict[str, Any]] = []
    payload = _tool_payload(case)
    for row in rows:
        response = cast(dict[str, Any], row.get("response") or {})
        body = cast(dict[str, Any], response.get("body") or {})
        text = _output_text(body)
        transport_ok = (
            response.get("status_code") == 200
            and body.get("status") == "completed"
            and body.get("incomplete_details") is None
            and bool(text.strip())
        )
        unsupported = find_unsupported_claims(text, case) if text else {"text": [""]}
        required = evaluate_annual_turn(
            [
                {
                    "response": text,
                    "calls": [
                        {
                            "name": "get_annual_toll_ballpark",
                            "input": case["request"],
                            "tool_result": payload,
                            "is_error": False,
                        }
                    ],
                }
            ],
            {"expected_call": case["request"]},
        )[0]
        required_pass = bool(required.test_pass)
        fully_grounded = transport_ok and not unsupported and required_pass
        counts.update(
            transport_ok=int(transport_ok),
            unsupported_claim_pass=int(not unsupported),
            required_response_pass=int(required_pass),
            fully_grounded=int(fully_grounded),
        )
        body_usage = cast(dict[str, Any], body.get("usage") or {})
        usage.update(
            input_tokens=int(body_usage.get("input_tokens", 0)),
            output_tokens=int(body_usage.get("output_tokens", 0)),
        )
        verdicts.append(
            {
                "custom_id": row["custom_id"],
                "output_sha256": _sha256(text),
                "unsupported_claims": unsupported,
                "required_response_label": required.label,
                "transport_ok": transport_ok,
                "required_response_pass": required_pass,
                "fully_grounded": fully_grounded,
                "output_text": text,
            }
        )
    return {
        "counts": dict(counts),
        "usage": dict(usage),
        "verdicts": sorted(verdicts, key=lambda verdict: verdict["custom_id"]),
    }


def select_review(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return every failure and a deterministic sample of at most 20 passes."""
    failures = [verdict for verdict in verdicts if not verdict["fully_grounded"]]
    passing = [verdict for verdict in verdicts if verdict["fully_grounded"]]
    sample: list[dict[str, Any]] = []
    for variant in range(1, 6):
        sample.extend(
            [
                verdict
                for verdict in passing
                if f":v{variant}:" in cast(str, verdict["custom_id"])
            ][:4]
        )
    return [*failures, *sample]


def _configure_database() -> None:
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("DB_NAME", "nova_toll")
    if "DB_CA_BUNDLE_PATH" not in os.environ:
        candidates = (
            Path("infra/build/loader/rds-ca-bundle.pem"),
            Path("infra/build/ca/rds-ca-bundle.pem"),
        )
        for candidate in candidates:
            if candidate.exists():
                os.environ["DB_CA_BUNDLE_PATH"] = str(candidate)
                break
        else:
            raise FileNotFoundError("RDS CA bundle is missing; build the loader zip")
    if "DB_HOST" not in os.environ or "DB_PORT" not in os.environ:
        instance = boto3.client("rds", region_name="us-east-1").describe_db_instances(
            DBInstanceIdentifier="nova-toll-db"
        )["DBInstances"][0]
        os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
        os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])


async def _invoke_ballpark(request: dict[str, Any]) -> ToolResult:
    tool_use = cast(
        ToolUse,
        {
            "name": "get_annual_toll_ballpark",
            "toolUseId": "call_ballpark_springfield_westpark",
            "input": request,
        },
    )
    result: ToolResult | None = None
    async for event in ballpark.get_annual_toll_ballpark.stream(
        tool_use, {"agent": object()}
    ):
        if "tool_result" in event:
            result = cast(ToolResult, event["tool_result"])
    if result is None or result.get("status") != "success":
        raise RuntimeError(f"ballpark fixture failed: {result}")
    return result


def capture_case() -> tuple[dict[str, Any], str]:
    """Capture one real read-only tool result and the matching developer prompt."""
    _configure_database()
    result = asyncio.run(_invoke_ballpark(copy.deepcopy(_BALLPARK_REQUEST)))
    case = {
        "id": "springfield-westpark-0830-1730",
        "request": copy.deepcopy(_BALLPARK_REQUEST),
        "prompts": list(_PROMPTS),
        "source": {
            "tool_result": result,
            "tool_result_sha256": _sha256(_json(result)),
        },
    }
    return case, toll_agent.build_system_prompt()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def prepare(output_dir: Path = _RUN_DIR, fixture_path: Path = _FIXTURE_PATH) -> Path:
    """Capture evidence and write the exact offline packet without uploading."""
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()).get("batch_id"):
        raise ValueError("run directory already contains a submitted Batch")
    case, system_prompt = capture_case()
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_text = f"{_json(case)}\n"
    fixture_path.write_text(fixture_text)
    requests = build_requests(case, system_prompt)
    packet = serialize_requests(requests)
    report = enforce_limits(preflight(packet), active_queued_tokens=0)
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "batch-input.jsonl"
    input_path.write_text(packet)
    manifest = {
        "source": _SOURCE,
        "model": _MODEL,
        "fixture_path": os.path.relpath(fixture_path, output_dir),
        "fixture_sha256": _sha256(fixture_text),
        "input_path": input_path.name,
        "system_prompt_sha256": _sha256(system_prompt),
        "tool_specs_sha256": _sha256(
            _json(
                [
                    tool.tool_spec
                    for tool in toll_agent._AGENT_TOOLS  # pyright: ignore[reportPrivateUsage]
                ]
            )
        ),
        "preflight": report,
        "input_file_id": None,
        "batch_id": None,
        "status": "prepared",
    }
    _write_json(manifest_path, manifest)
    return manifest_path


def _client() -> OpenAI:
    return OpenAI(api_key=toll_agent.load_openai_api_key(), base_url=_OPENAI_BASE_URL)


def submit(
    manifest_path: Path,
    client: Any | None = None,  # noqa: ANN401
) -> dict[str, Any]:
    """Validate and submit exactly one prepared packet, then return immediately."""
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text()))
    if manifest.get("batch_id"):
        raise ValueError("manifest was already submitted")
    input_path = manifest_path.parent / cast(str, manifest["input_path"])
    packet = input_path.read_text()
    measured = preflight(packet)
    expected = cast(dict[str, Any], manifest["preflight"])
    if any(measured[key] != expected.get(key) for key in measured):
        raise ValueError("prepared Batch packet no longer matches its manifest")
    resolved_client = _client() if client is None else client
    gate = enforce_limits(
        measured, active_queued_tokens=active_luna_tokens(resolved_client)
    )
    input_file_id = manifest.get("input_file_id")
    if not isinstance(input_file_id, str):
        with input_path.open("rb") as file:
            uploaded = resolved_client.files.create(file=file, purpose="batch")
        input_file_id = cast(str, uploaded.id)
    manifest.update(input_file_id=input_file_id, submission_preflight=gate)
    _write_json(manifest_path, manifest)
    created = resolved_client.batches.create(
        input_file_id=input_file_id,
        endpoint=_ENDPOINT,
        completion_window="24h",
        metadata={"source": _SOURCE, "model": _MODEL},
    )
    manifest.update(
        batch_id=created.id,
        status=getattr(created, "status", None),
    )
    _write_json(manifest_path, manifest)
    return manifest


def collect(
    manifest_path: Path,
    client: Any | None = None,  # noqa: ANN401
) -> dict[str, Any]:
    """Retrieve one Batch without polling; terminal jobs are reconciled and graded."""
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text()))
    batch_id = manifest.get("batch_id")
    if not isinstance(batch_id, str):
        raise ValueError("manifest has no submitted Batch ID")
    result_path = manifest_path.parent / "results.json"
    if result_path.exists():
        return cast(dict[str, Any], json.loads(result_path.read_text()))
    resolved_client = _client() if client is None else client
    remote = resolved_client.batches.retrieve(batch_id)
    status = cast(str, remote.status)
    manifest["status"] = status
    _write_json(manifest_path, manifest)
    if status not in _TERMINAL_STATUSES:
        return {"status": status}
    output_file_id = getattr(remote, "output_file_id", None)
    error_file_id = getattr(remote, "error_file_id", None)
    output_text = (
        cast(str, resolved_client.files.content(output_file_id).text)
        if isinstance(output_file_id, str)
        else ""
    )
    error_text = (
        cast(str, resolved_client.files.content(error_file_id).text)
        if isinstance(error_file_id, str)
        else ""
    )
    run_dir = manifest_path.parent
    (run_dir / "batch-output.jsonl").write_text(output_text)
    if error_text:
        (run_dir / "batch-errors.jsonl").write_text(error_text)
    packet = (run_dir / cast(str, manifest["input_path"])).read_text()
    rows, failures = reconcile_outputs(
        _rows(packet),
        output_text.splitlines(),
        error_text.splitlines(),
        status=status,
    )
    fixture_path = run_dir / cast(str, manifest["fixture_path"])
    fixture_text = fixture_path.read_text()
    if _sha256(fixture_text) != manifest.get("fixture_sha256"):
        raise ValueError("canonical fixture no longer matches its manifest")
    case = _rows(fixture_text)[0]
    result = {"status": status, **grade_outputs(case, rows), "failures": failures}
    result["counts"]["batch_failures"] = len(failures)
    _write_json(result_path, result)
    _write_json(run_dir / "review.json", select_review(result["verdicts"]))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "submit", "collect"))
    parser.add_argument("--run-dir", type=Path, default=_RUN_DIR)
    parser.add_argument("--fixture", type=Path, default=_FIXTURE_PATH)
    args = parser.parse_args()
    manifest_path = args.run_dir / "manifest.json"
    if args.command == "prepare":
        manifest_path = prepare(args.run_dir, args.fixture)
        print(manifest_path)
    elif args.command == "submit":
        print(json.dumps(submit(manifest_path), indent=2, sort_keys=True))
    else:
        print(json.dumps(collect(manifest_path), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

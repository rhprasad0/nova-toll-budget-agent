"""Render the approved single-leg fixtures as an offline OpenAI Batch packet."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from agent.toll_agent import (
    _AGENT_TOOLS as AGENT_TOOLS,  # pyright: ignore[reportPrivateUsage]
)
from agent.toll_agent import (
    _CachedResponsesModel as CachedResponsesModel,  # pyright: ignore[reportPrivateUsage]
)
from agent.toll_agent import (
    build_system_prompt,
)
from eval.batch_judges import serialize_requests

_MODEL = "gpt-5.6-luna"
_RUN_DATE = date(2026, 8, 11)
_MAX_OUTPUT_TOKENS = 2048
_BATCH_CACHE_WRITE_USD_PER_MILLION = Decimal("0.625")
_BATCH_OUTPUT_USD_PER_MILLION = Decimal("3.00")
_CURRENT_BATCH_CACHE_WRITE_USD_PER_MILLION = Decimal("0.125")
_CURRENT_BATCH_OUTPUT_USD_PER_MILLION = Decimal("0.60")
_PILOT_ACTUAL_COST_USD = Decimal("0.301442325")
_BATCH_FILE_LIMIT = 200_000_000


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _model() -> CachedResponsesModel:
    return CachedResponsesModel(
        model_id=_MODEL,
        client_args={"api_key": "offline", "base_url": "https://api.openai.com/v1"},
        params={
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "reasoning": {"effort": "low"},
            "prompt_cache_key": "tollchat-agent-v1",
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        },
        stateful=True,
    )


def _messages(case: dict[str, Any], prompt: str) -> list[dict[str, Any]]:
    calls = cast(list[dict[str, Any]], case["source"]["evidence"]["calls"])
    if not calls:
        raise ValueError(f"{case['id']} must contain terminal tool evidence")
    call_prefix = f"call_{_sha256(str(case['id']))[:24]}"
    tool_use_ids = [
        call_prefix if len(calls) == 1 else f"{call_prefix}_{number}"
        for number in range(1, len(calls) + 1)
    ]
    return [
        {"role": "user", "content": [{"text": prompt}]},
        {
            "role": "assistant",
            "content": [
                {
                    "toolUse": {
                        "toolUseId": tool_use_id,
                        "name": call["tool"],
                        "input": call["input"],
                    }
                }
                for call, tool_use_id in zip(calls, tool_use_ids, strict=True)
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "content": [{"json": call["result"]}],
                        "status": "error" if "error" in call["result"] else "success",
                    }
                }
                for call, tool_use_id in zip(calls, tool_use_ids, strict=True)
            ],
        },
    ]


def build_multi_leg_requests(
    cases: list[dict[str, Any]],
    *,
    repetitions: int = 10,
    expected_requests: int = 10_000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build ten repeat sweeps of the reviewed 1,000-request multi-leg suite."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    selected = [case for case in cases if case.get("stratum") == "multi_leg"]
    model = _model()
    system_prompt = build_system_prompt(current_date=_RUN_DATE)
    tool_specs = [tool.tool_spec for tool in AGENT_TOOLS]
    base_requests: list[dict[str, Any]] = []
    unapproved_differences = 0
    for case in selected:
        prompts = cast(list[str], case.get("prompts"))
        if len(prompts) != 5:
            raise ValueError(f"{case['id']} must contain exactly five prompts")
        for variant, prompt in enumerate(prompts, 1):
            production = model._format_request(  # pyright: ignore[reportPrivateUsage]
                cast(Any, _messages(case, prompt)),
                cast(Any, tool_specs),
                system_prompt,
            )
            body = copy.deepcopy(production)
            body.pop("stream")
            body["store"] = False
            body["tool_choice"] = "none"
            body["metadata"] = {
                "suite": "price_hallucination_multi_leg",
                "case_id": case["id"],
                "variant": str(variant),
                "evidence_sha256": case["source"]["evidence_sha256"],
            }
            normalized = copy.deepcopy(body)
            normalized.pop("metadata")
            expected = copy.deepcopy(production)
            expected.pop("stream")
            expected["store"] = False
            expected["tool_choice"] = "none"
            unapproved_differences += normalized != expected
            base_requests.append(
                {
                    "custom_id": f"{case['id']}:v{variant}",
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": body,
                }
            )

    requests: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        for base in base_requests:
            base_body = cast(dict[str, Any], base["body"])
            requests.append(
                {
                    **{key: base[key] for key in ("method", "url")},
                    "custom_id": f"{base['custom_id']}:r{repetition:02d}",
                    "body": {
                        **base_body,
                        "metadata": {
                            **cast(dict[str, str], base_body["metadata"]),
                            "repetition": f"{repetition:02d}",
                        },
                    },
                }
            )
    custom_ids = [request["custom_id"] for request in requests]
    if len(custom_ids) != len(set(custom_ids)):
        raise ValueError("batch custom_id values must be unique")
    if len(requests) != expected_requests:
        raise ValueError(f"expected {expected_requests} requests, got {len(requests)}")
    if unapproved_differences:
        raise ValueError(
            f"found {unapproved_differences} unapproved payload differences"
        )

    body_byte_ceiling = sum(
        len(_canonical_json(request["body"]).encode()) for request in requests
    )
    output_token_ceiling = len(requests) * _MAX_OUTPUT_TOKENS
    maximum_cost = Decimal(
        body_byte_ceiling
    ) * _CURRENT_BATCH_CACHE_WRITE_USD_PER_MILLION / Decimal(1_000_000) + Decimal(
        output_token_ceiling
    ) * _CURRENT_BATCH_OUTPUT_USD_PER_MILLION / Decimal(1_000_000)
    report = {
        "request_count": len(requests),
        "base_request_count": len(base_requests),
        "canonical_case_count": len(selected),
        "repetitions": repetitions,
        "model": _MODEL,
        "run_date": _RUN_DATE.isoformat(),
        "system_prompt_sha256": _sha256(system_prompt),
        "tool_specs_sha256": _sha256(_canonical_json(tool_specs)),
        "approved_payload_differences": [
            "Batch envelope added",
            "stream removed",
            "store changed from true to false",
            "tool_choice set to none",
            "trace metadata and repetition ID added",
        ],
        "unapproved_payload_differences": unapproved_differences,
        "request_body_utf8_byte_token_ceiling": body_byte_ceiling,
        "maximum_output_tokens": output_token_ceiling,
        "maximum_cost_usd": float(maximum_cost.quantize(Decimal("0.000001"))),
        "pilot_linear_cost_projection_usd": float(
            (_PILOT_ACTUAL_COST_USD * Decimal(len(requests)) / Decimal(1000)).quantize(
                Decimal("0.000001")
            )
        ),
        "cost_assumptions": {
            "batch_cache_write_input_usd_per_million": str(
                _CURRENT_BATCH_CACHE_WRITE_USD_PER_MILLION
            ),
            "batch_output_usd_per_million": str(_CURRENT_BATCH_OUTPUT_USD_PER_MILLION),
            "absolute_input_ceiling": (
                "One token per UTF-8 request-body byte, including non-tokenized "
                "control fields; every input token charged as an explicit cache write."
            ),
            "absolute_output_ceiling": (
                "Every response consumes all 2,048 output tokens."
            ),
            "pilot_projection": (
                "The observed $0.301442325 single-leg charge scaled linearly to "
                "10,000 responses; multi-leg token usage may differ."
            ),
        },
    }
    return requests, report


def build_single_leg_requests(
    cases: list[dict[str, Any]], *, expected_requests: int = 1000
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build and parity-check the production-shaped Batch requests."""
    selected = [case for case in cases if case.get("stratum") == "single_leg"]
    model = _model()
    system_prompt = build_system_prompt(current_date=_RUN_DATE)
    tool_specs = [tool.tool_spec for tool in AGENT_TOOLS]
    requests: list[dict[str, Any]] = []
    unapproved_differences = 0

    for case in selected:
        prompts = cast(list[str], case.get("prompts"))
        if len(prompts) != 5:
            raise ValueError(f"{case['id']} must contain exactly five prompts")
        for variant, prompt in enumerate(prompts, 1):
            production = model._format_request(  # pyright: ignore[reportPrivateUsage]
                cast(Any, _messages(case, prompt)),
                cast(Any, tool_specs),
                system_prompt,
            )
            body = copy.deepcopy(production)
            body.pop("stream")
            body["store"] = False
            body["tool_choice"] = "none"
            body["metadata"] = {
                "suite": "price_hallucination_single_leg",
                "case_id": case["id"],
                "variant": str(variant),
                "evidence_sha256": case["source"]["evidence_sha256"],
            }
            normalized = copy.deepcopy(body)
            normalized.pop("metadata")
            expected = copy.deepcopy(production)
            expected.pop("stream")
            expected["store"] = False
            expected["tool_choice"] = "none"
            unapproved_differences += normalized != expected
            requests.append(
                {
                    "custom_id": f"{case['id']}:v{variant}",
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": body,
                }
            )

    custom_ids = [request["custom_id"] for request in requests]
    if len(custom_ids) != len(set(custom_ids)):
        raise ValueError("batch custom_id values must be unique")
    if len(requests) != expected_requests:
        raise ValueError(f"expected {expected_requests} requests, got {len(requests)}")
    if unapproved_differences:
        raise ValueError(
            f"found {unapproved_differences} unapproved payload differences"
        )

    body_byte_ceiling = sum(
        len(_canonical_json(request["body"]).encode()) for request in requests
    )
    output_token_ceiling = len(requests) * _MAX_OUTPUT_TOKENS
    maximum_cost = Decimal(
        body_byte_ceiling
    ) * _BATCH_CACHE_WRITE_USD_PER_MILLION / Decimal(1_000_000) + Decimal(
        output_token_ceiling
    ) * _BATCH_OUTPUT_USD_PER_MILLION / Decimal(1_000_000)
    report = {
        "request_count": len(requests),
        "canonical_case_count": len(selected),
        "model": _MODEL,
        "run_date": _RUN_DATE.isoformat(),
        "system_prompt_sha256": _sha256(system_prompt),
        "tool_specs_sha256": _sha256(_canonical_json(tool_specs)),
        "approved_payload_differences": [
            "Batch envelope added",
            "stream removed",
            "store changed from true to false",
            "tool_choice set to none",
            "trace metadata added",
        ],
        "unapproved_payload_differences": unapproved_differences,
        "request_body_utf8_byte_token_ceiling": body_byte_ceiling,
        "maximum_output_tokens": output_token_ceiling,
        "maximum_cost_usd": float(maximum_cost.quantize(Decimal("0.000001"))),
        "cost_assumptions": {
            "batch_cache_write_input_usd_per_million": str(
                _BATCH_CACHE_WRITE_USD_PER_MILLION
            ),
            "batch_output_usd_per_million": str(_BATCH_OUTPUT_USD_PER_MILLION),
            "input_ceiling": (
                "One token per UTF-8 request-body byte, including non-tokenized "
                "control fields; every input token charged as an explicit cache write."
            ),
            "output_ceiling": "Every response consumes all 2,048 output tokens.",
        },
    }
    return requests, report


def write_gate3_packet(
    cases: list[dict[str, Any]],
    output_dir: Path,
    *,
    expected_requests: int = 1000,
) -> dict[str, Any]:
    requests, report = build_single_leg_requests(
        cases, expected_requests=expected_requests
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_text = serialize_requests(requests)
    report["batch_jsonl_bytes"] = len(batch_text.encode())
    report["batch_jsonl_sha256"] = _sha256(batch_text)
    report_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    files = {
        "single-leg-batch.jsonl": batch_text,
        "single-leg-parity.json": report_text,
    }
    for name, content in files.items():
        (output_dir / name).write_text(content)
    checksums = "".join(
        f"{_sha256(content)}  {name}\n" for name, content in files.items()
    )
    (output_dir / "gate3-packet.sha256").write_text(checksums)
    packet_sha256 = _sha256(checksums)
    review = f"""# Gate 3 — 1,000-row single-leg smoke review

**Nothing has been uploaded and no model has been called.**

| Check | Result |
| --- | ---: |
| Canonical single-leg fixtures | {report["canonical_case_count"]:,} |
| Batch requests | {report["request_count"]:,} |
| Unapproved production-payload differences | {report["unapproved_payload_differences"]} |
| Maximum output tokens | {report["maximum_output_tokens"]:,} |
| Conservative maximum cost | **${report["maximum_cost_usd"]:.2f}** |

The spend ceiling assumes every response uses all 2,048 output tokens and every
request-body UTF-8 byte is a separately billed explicit-cache-write input token.
That deliberately overcounts JSON/control fields and ignores cache-read savings.

## Approved production differences

* Batch envelope added
* streaming removed
* response storage disabled
* tool schemas retained but `tool_choice` set to `none`
* trace metadata added

## Verification

```bash
sha256sum -c gate3-packet.sha256
sha256sum gate3-packet.sha256
```

**Gate 3 packet SHA-256:** `{packet_sha256}`

Approving this packet authorizes only upload/submission of this exact 1,000-row
single-leg Batch file. The run must still pause for Gate 4 audit before another
stratum is rendered or submitted.
"""
    (output_dir / "gate3-review.md").write_text(review)
    return {**report, "sha256": packet_sha256}


def write_multi_leg_packet(
    cases: list[dict[str, Any]],
    output_dir: Path,
    *,
    repetitions: int = 10,
    expected_requests: int = 10_000,
    shard_request_limit: int = 2_000,
) -> dict[str, Any]:
    """Write size-bounded Batch shards and their Gate 5 review packet."""
    requests, report = build_multi_leg_requests(
        cases,
        repetitions=repetitions,
        expected_requests=expected_requests,
    )
    if shard_request_limit < 1:
        raise ValueError("shard_request_limit must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    checksums = ""
    shard_bytes: list[int] = []
    shard_names: list[str] = []
    for start in range(0, len(requests), shard_request_limit):
        shard_number = len(shard_names) + 1
        name = f"multi-leg-batch-{shard_number:02d}.jsonl"
        content = serialize_requests(requests[start : start + shard_request_limit])
        size = len(content.encode())
        if size > _BATCH_FILE_LIMIT:
            raise ValueError(f"{name} is {size} bytes; Batch limit is 200,000,000")
        (output_dir / name).write_text(content)
        checksums += f"{_sha256(content)}  {name}\n"
        shard_names.append(name)
        shard_bytes.append(size)

    report.update(
        shard_count=len(shard_names),
        shard_request_limit=shard_request_limit,
        shard_names=shard_names,
        shard_bytes=shard_bytes,
    )
    parity_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (output_dir / "multi-leg-parity.json").write_text(parity_text)
    checksums += f"{_sha256(parity_text)}  multi-leg-parity.json\n"
    (output_dir / "gate5-packet.sha256").write_text(checksums)
    packet_sha256 = _sha256(checksums)
    shard_rows = "\n".join(
        f"| `{name}` | {min(shard_request_limit, len(requests) - index * shard_request_limit):,} | {size / 1_000_000:.1f} MB |"
        for index, (name, size) in enumerate(zip(shard_names, shard_bytes, strict=True))
    )
    review = f"""# Gate 5 — 10,000-response multi-leg review

**Nothing in this packet has been uploaded and no additional model call has
been made.**

| Check | Result |
| --- | ---: |
| Reviewed canonical fixtures | {report["canonical_case_count"]:,} |
| Reviewed base requests | {report["base_request_count"]:,} |
| Repeat executions per base request | {report["repetitions"]} |
| Total Batch requests | **{report["request_count"]:,}** |
| Unapproved production-payload differences | {report["unapproved_payload_differences"]} |
| Shards | {report["shard_count"]} |
| Pilot-linear cost projection | **${report["pilot_linear_cost_projection_usd"]:.2f}** |
| Absolute conservative ceiling | **${report["maximum_cost_usd"]:.2f}** |

The 10,000 responses are ten repeat executions of each of the 1,000
reviewed case/prompt pairs. This increases repeat-reliability evidence, **not
scenario coverage**. Results remain descriptive; repetitions are clustered by
fixture and do not justify a naive IID confidence interval.

The absolute ceiling intentionally treats every UTF-8 body byte as a billed
cache-write token and every response as consuming all 2,048 output tokens. The
pilot-linear projection is the useful budget estimate; the ceiling is the
break-glass bound.

## Batch shards

| File | Requests | Size |
| --- | ---: | ---: |
{shard_rows}

Each shard stays below OpenAI's 200 MB Batch input limit and contains complete
repeat sweeps; all five shards must complete before a 10,000-response result is
reported.

## Integrity

```bash
sha256sum -c gate5-packet.sha256
sha256sum gate5-packet.sha256
```

**Gate 5 packet SHA-256:** `{packet_sha256}`

Approval authorizes submission of these exact five shards only. Collection and
audit must finish before another stratum is rendered or submitted.
"""
    (output_dir / "gate5-review.md").write_text(review)
    return {
        **report,
        "sha256": packet_sha256,
        "shard_bytes": shard_bytes,
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_jsonl", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    packet = write_gate3_packet(_load_cases(args.fixture_jsonl), args.output_dir)
    print(json.dumps(packet, indent=2, sort_keys=True))

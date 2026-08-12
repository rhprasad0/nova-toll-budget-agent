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
    if len(calls) != 1:
        raise ValueError(f"{case['id']} must contain exactly one terminal tool call")
    call = calls[0]
    tool_use_id = f"call_{_sha256(str(case['id']))[:24]}"
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
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "content": [{"json": call["result"]}],
                        "status": "success",
                    }
                }
            ],
        },
    ]


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


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_jsonl", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    packet = write_gate3_packet(_load_cases(args.fixture_jsonl), args.output_dir)
    print(json.dumps(packet, indent=2, sort_keys=True))

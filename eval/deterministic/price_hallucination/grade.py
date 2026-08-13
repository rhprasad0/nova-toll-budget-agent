"""Deterministically grade frozen single-leg Batch responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

_MONEY = re.compile(r"(?:(?<!\w)\$\s*|\bUSD\s+)([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)")
_TIMESTAMP = re.compile(
    r"\b(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*([AP]M)\s*(?:ET)?\b",
    re.IGNORECASE,
)
_TIME_KEYS = {"at_time", "observed_at", "priced_as_of"}
_FACILITY_ALIASES = {
    "dulles_greenway": ("dulles greenway", "greenway"),
    "dulles_toll_road": ("dulles toll road",),
}
_PARTIAL_DISCLOSURE = re.compile(
    r"\b(?:partial|unpriced|exclude(?:s|d)?|known toll total|"
    r"not (?:a )?complete|does not include|incomplete)\b",
    re.IGNORECASE,
)


def _output_text(body: dict[str, Any]) -> str:
    return "".join(
        str(content.get("text", ""))
        for item in cast(list[dict[str, Any]], body.get("output", []))
        for content in cast(list[dict[str, Any]], item.get("content", []))
        if content.get("type") == "output_text"
    )


def _time_tuple(value: str) -> tuple[int, int, int, int, int]:
    parsed = datetime.fromisoformat(value)
    return parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute


def _allowed_times(case: dict[str, Any]) -> set[tuple[int, int, int, int, int]]:
    found = {_time_tuple(cast(str, case["route"]["requested_at"]))}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in cast(dict[object, object], value).items():
                if key in _TIME_KEYS and isinstance(child, str):
                    found.add(_time_tuple(child))
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[object], value):
                visit(child)

    visit(case["source"]["evidence"])
    return found


def _claimed_times(text: str) -> list[tuple[str, tuple[int, int, int, int, int]]]:
    claims: list[tuple[str, tuple[int, int, int, int, int]]] = []
    for match in _TIMESTAMP.finditer(text):
        hour = int(match[4]) % 12 + (12 if match[6].casefold() == "pm" else 0)
        claims.append(
            (
                match.group(),
                (int(match[3]), int(match[1]), int(match[2]), hour, int(match[5])),
            )
        )
    return claims


def _facility_mismatches(case: dict[str, Any], text: str) -> list[str]:
    components = cast(list[dict[str, Any]], case["components"])
    if len({component["facility"] for component in components}) < 2:
        return []
    lines = text.casefold().splitlines()
    missing: list[str] = []
    for component in components:
        facility = cast(str, component["facility"])
        aliases = _FACILITY_ALIASES.get(facility, (facility.casefold(),))
        amount = f"${component['price_usd']}"
        if not any(
            amount in line and any(alias in line for alias in aliases) for line in lines
        ):
            missing.append(f"{facility}={component['price_usd']}")
    return missing


def grade_outputs(
    cases: list[dict[str, Any]], output_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    selected = {
        case["id"]: case for case in cases if case.get("stratum") == "single_leg"
    }
    expected_ids = {
        f"{case_id}:v{variant}"
        for case_id, case in selected.items()
        for variant in range(1, len(cast(list[str], case["prompts"])) + 1)
    }
    actual_ids = [cast(str, row.get("custom_id")) for row in output_rows]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("Batch output custom_id values must be unique")
    if set(actual_ids) != expected_ids:
        missing = sorted(expected_ids - set(actual_ids))
        extra = sorted(set(actual_ids) - expected_ids)
        raise ValueError(
            f"Batch output IDs do not reconcile; missing={missing}, extra={extra}"
        )

    counts: Counter[str] = Counter(responses=len(output_rows))
    usage: Counter[str] = Counter()
    verdicts: list[dict[str, Any]] = []
    for row in output_rows:
        custom_id = cast(str, row["custom_id"])
        case = selected[custom_id.rsplit(":v", 1)[0]]
        response = cast(dict[str, Any], row.get("response") or {})
        body = cast(dict[str, Any], response.get("body") or {})
        text = _output_text(body)
        transport_ok = (
            row.get("error") is None
            and response.get("status_code") == 200
            and body.get("status") == "completed"
            and body.get("incomplete_details") is None
            and bool(text.strip())
            and all(
                item.get("type") in {"reasoning", "message"}
                for item in cast(list[dict[str, Any]], body.get("output", []))
            )
        )
        amounts = [Decimal(value.replace(",", "")) for value in _MONEY.findall(text)]
        components = cast(list[dict[str, Any]], case["components"])
        component_values = [Decimal(component["price_usd"]) for component in components]
        component_amounts = set(component_values)
        needs_component_attribution_review = len(component_values) != len(
            component_amounts
        )
        total = Decimal(case["calculation"]["result_usd"])
        allowed_amounts = component_amounts | {total}
        unsupported = sorted(
            {amount for amount in amounts if amount not in allowed_amounts}
        )
        missing_components = sorted(component_amounts - set(amounts))
        bad_timestamps = [
            display
            for display, value in _claimed_times(text)
            if value not in _allowed_times(case)
        ]
        facility_mismatches = _facility_mismatches(case, text)
        wrong_completeness = bool(
            re.search(r"\b(?:partial|unavailable|unknown)\b", text, re.IGNORECASE)
        )
        unsupported_price_pass = (
            transport_ok
            and not unsupported
            and not bad_timestamps
            and not facility_mismatches
        )
        required_price_pass = (
            transport_ok
            and total in amounts
            and not missing_components
            and not wrong_completeness
            and not needs_component_attribution_review
        )
        fully_grounded = unsupported_price_pass and required_price_pass
        counts["transport_ok"] += transport_ok
        counts["invented_amount"] += bool(unsupported)
        counts["bad_timestamp"] += bool(bad_timestamps)
        counts["facility_mismatch"] += bool(facility_mismatches)
        counts["component_attribution_review"] += needs_component_attribution_review
        counts["unsupported_price_pass"] += unsupported_price_pass
        counts["required_price_pass"] += required_price_pass
        counts["fully_grounded"] += fully_grounded
        counts["monetary_claims"] += len(amounts)
        details = cast(
            dict[str, Any],
            cast(dict[str, Any], body.get("usage") or {}).get("input_tokens_details")
            or {},
        )
        output_details = cast(
            dict[str, Any],
            cast(dict[str, Any], body.get("usage") or {}).get("output_tokens_details")
            or {},
        )
        body_usage = cast(dict[str, Any], body.get("usage") or {})
        usage.update(
            input_tokens=int(body_usage.get("input_tokens", 0)),
            cached_tokens=int(details.get("cached_tokens", 0)),
            cache_write_tokens=int(details.get("cache_write_tokens", 0)),
            output_tokens=int(body_usage.get("output_tokens", 0)),
            reasoning_tokens=int(output_details.get("reasoning_tokens", 0)),
        )
        verdicts.append(
            {
                "custom_id": custom_id,
                "facility": case["route"]["facility"],
                "expected_total_usd": f"{total:.2f}",
                "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "unsupported_amounts": [f"{amount:.2f}" for amount in unsupported],
                "missing_component_amounts": [
                    f"{amount:.2f}" for amount in missing_components
                ],
                "bad_timestamps": bad_timestamps,
                "facility_mismatches": facility_mismatches,
                "component_attribution_review": needs_component_attribution_review,
                "transport_ok": transport_ok,
                "unsupported_price_pass": unsupported_price_pass,
                "required_price_pass": required_price_pass,
                "fully_grounded": fully_grounded,
                "output_text": text,
            }
        )

    normal_input = (
        usage["input_tokens"] - usage["cached_tokens"] - usage["cache_write_tokens"]
    )
    cost = (
        Decimal(usage["cached_tokens"]) * Decimal("0.01")
        + Decimal(usage["cache_write_tokens"]) * Decimal("0.125")
        + Decimal(normal_input) * Decimal("0.10")
        + Decimal(usage["output_tokens"]) * Decimal("0.60")
    ) / Decimal(1_000_000)
    return {
        "counts": dict(counts),
        "usage": dict(usage),
        "estimated_batch_cost_usd": f"{cost:.6f}",
        "verdicts": sorted(verdicts, key=lambda verdict: verdict["custom_id"]),
    }


def _subset_sums(amounts: list[Decimal]) -> set[Decimal]:
    sums = {Decimal("0")}
    for amount in amounts:
        sums |= {subtotal + amount for subtotal in sums}
    return sums


def grade_multi_leg_outputs(
    cases: list[dict[str, Any]],
    output_rows: list[dict[str, Any]],
    *,
    repetitions: tuple[int, ...] = (7, 8),
    variants: tuple[int, ...] = (1, 2, 3, 4, 5),
    include_blocked: bool = True,
) -> dict[str, Any]:
    """Grade multi-leg amounts without mistaking valid leg subtotals for inventions."""
    selected = {
        cast(str, case["id"]): case
        for case in cases
        if case.get("stratum") == "multi_leg"
    }
    expected_ids = {
        f"{case_id}:v{variant}:r{repetition:02d}"
        for case_id, case in selected.items()
        for variant in variants
        if variant <= len(cast(list[str], case["prompts"]))
        for repetition in repetitions
    }
    if include_blocked:
        expected_ids |= {
            f"{case_id}:blocked-duplicate:r{repetition:02d}"
            for case_id, case in selected.items()
            if "blocked_duplicate" in case
            for repetition in repetitions
        }
    actual_ids = [cast(str, row.get("custom_id")) for row in output_rows]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("Batch output custom_id values must be unique")
    if set(actual_ids) != expected_ids:
        raise ValueError(
            "Batch output IDs do not reconcile; "
            f"missing={sorted(expected_ids - set(actual_ids))}, "
            f"extra={sorted(set(actual_ids) - expected_ids)}"
        )

    counts: Counter[str] = Counter()
    cohorts: dict[str, Counter[str]] = {
        "ordinary": Counter(),
        "blocked_duplicate": Counter(),
    }
    usage: Counter[str] = Counter()
    verdicts: list[dict[str, Any]] = []
    for row in output_rows:
        custom_id = cast(str, row["custom_id"])
        request_id = custom_id.rsplit(":r", 1)[0]
        case_id = request_id.rsplit(":", 1)[0]
        case = selected[case_id]
        cohort = (
            "blocked_duplicate" if ":blocked-duplicate:" in custom_id else "ordinary"
        )
        response = cast(dict[str, Any], row.get("response") or {})
        body = cast(dict[str, Any], response.get("body") or {})
        text = _output_text(body)
        transport_ok = (
            row.get("error") is None
            and response.get("status_code") == 200
            and body.get("status") == "completed"
            and body.get("incomplete_details") is None
            and bool(text.strip())
        )
        amounts = [Decimal(value.replace(",", "")) for value in _MONEY.findall(text)]
        component_values = [
            Decimal(cast(str, component["price_usd"]))
            for component in cast(list[dict[str, Any]], case["components"])
        ]
        needs_component_attribution_review = len(component_values) != len(
            set(component_values)
        )
        allowed_amounts = _subset_sums(component_values)
        allowed_amounts |= {
            Decimal(cast(str, excluded["source_value"]))
            for excluded in cast(list[dict[str, Any]], case.get("excluded", []))
            if excluded.get("source_value") is not None
        }
        unsupported = sorted(set(amounts) - allowed_amounts)
        amount_counts = Counter(amounts)
        missing_components = sorted(
            amount
            for amount, expected in Counter(component_values).items()
            for _ in range(max(0, expected - amount_counts[amount]))
        )
        total = Decimal(cast(str, case["calculation"]["result_usd"]))
        bad_timestamps = [
            display
            for display, value in _claimed_times(text)
            if value not in _allowed_times(case)
        ]
        missing_partial_disclosure = case[
            "total_type"
        ] == "known_partial" and not _PARTIAL_DISCLOSURE.search(text)
        unsupported_price_pass = transport_ok and not unsupported and not bad_timestamps
        required_price_pass = (
            transport_ok
            and total in amounts
            and not missing_components
            and not missing_partial_disclosure
            and not needs_component_attribution_review
        )
        fully_grounded = unsupported_price_pass and required_price_pass
        flags = {
            "responses": 1,
            "transport_ok": int(transport_ok),
            "invented_amount": int(bool(unsupported)),
            "bad_timestamp": int(bool(bad_timestamps)),
            "missing_component": int(bool(missing_components)),
            "missing_total": int(total not in amounts),
            "missing_partial_disclosure": int(missing_partial_disclosure),
            "component_attribution_review": int(needs_component_attribution_review),
            "unsupported_price_pass": int(unsupported_price_pass),
            "required_price_pass": int(required_price_pass),
            "fully_grounded": int(fully_grounded),
            "monetary_claims": len(amounts),
        }
        counts.update(flags)
        cohorts[cohort].update(flags)
        body_usage = cast(dict[str, Any], body.get("usage") or {})
        input_details = cast(
            dict[str, Any], body_usage.get("input_tokens_details") or {}
        )
        output_details = cast(
            dict[str, Any], body_usage.get("output_tokens_details") or {}
        )
        usage.update(
            input_tokens=int(body_usage.get("input_tokens", 0)),
            cached_tokens=int(input_details.get("cached_tokens", 0)),
            cache_write_tokens=int(input_details.get("cache_write_tokens", 0)),
            output_tokens=int(body_usage.get("output_tokens", 0)),
            reasoning_tokens=int(output_details.get("reasoning_tokens", 0)),
        )
        verdicts.append(
            {
                "custom_id": custom_id,
                "case_id": case_id,
                "cohort": cohort,
                "total_type": case["total_type"],
                "expected_total_usd": f"{total:.2f}",
                "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "unsupported_amounts": [f"{amount:.2f}" for amount in unsupported],
                "missing_component_amounts": [
                    f"{amount:.2f}" for amount in missing_components
                ],
                "missing_total": total not in amounts,
                "bad_timestamps": bad_timestamps,
                "missing_partial_disclosure": missing_partial_disclosure,
                "component_attribution_review": needs_component_attribution_review,
                "transport_ok": transport_ok,
                "unsupported_price_pass": unsupported_price_pass,
                "required_price_pass": required_price_pass,
                "fully_grounded": fully_grounded,
                "output_text": text,
            }
        )

    normal_input = (
        usage["input_tokens"] - usage["cached_tokens"] - usage["cache_write_tokens"]
    )
    cost = (
        Decimal(usage["cached_tokens"]) * Decimal("0.01")
        + Decimal(usage["cache_write_tokens"]) * Decimal("0.125")
        + Decimal(normal_input) * Decimal("0.10")
        + Decimal(usage["output_tokens"]) * Decimal("0.60")
    ) / Decimal(1_000_000)
    return {
        "counts": dict(counts),
        "cohorts": {name: dict(values) for name, values in cohorts.items()},
        "usage": dict(usage),
        "estimated_batch_cost_usd": f"{cost:.6f}",
        "verdicts": sorted(verdicts, key=lambda verdict: verdict["custom_id"]),
    }


def write_gate4_review(
    result: dict[str, Any],
    output_dir: Path,
    *,
    batch_id: str,
    raw_output_sha256: str,
) -> dict[str, Any]:
    """Write the aggregate Gate 4 report and deterministic manual sample."""
    output_dir.mkdir(parents=True, exist_ok=True)
    verdicts = cast(list[dict[str, Any]], result["verdicts"])
    failures = [verdict for verdict in verdicts if not verdict["fully_grounded"]]
    passes = [verdict for verdict in verdicts if verdict["fully_grounded"]]

    def family(verdict: dict[str, Any]) -> str:
        return cast(str, verdict["custom_id"]).split(":", 1)[1].rsplit("-", 1)[0]

    sample: list[dict[str, Any]] = []
    for facility_family in (
        "i95",
        "i495",
        "i66_itb",
        "dulles_toll_road",
        "dulles_greenway",
    ):
        for variant in range(1, 6):
            bucket = [
                verdict
                for verdict in passes
                if family(verdict) == facility_family
                and cast(str, verdict["custom_id"]).endswith(f":v{variant}")
            ]
            bucket.sort(
                key=lambda verdict: hashlib.sha256(
                    f"gate4-manual-audit-v1:{verdict['custom_id']}".encode()
                ).hexdigest()
            )
            sample.extend(bucket[:4])
    if len(sample) != 100:
        raise ValueError(f"expected 100 sampled passes, got {len(sample)}")

    def public(
        verdict: dict[str, Any], *, include_text: bool = False
    ) -> dict[str, Any]:
        keys = (
            "custom_id",
            "facility",
            "expected_total_usd",
            "output_sha256",
            "unsupported_amounts",
            "missing_component_amounts",
            "bad_timestamps",
            "facility_mismatches",
            "component_attribution_review",
            "transport_ok",
            "unsupported_price_pass",
            "required_price_pass",
            "fully_grounded",
        )
        item = {key: verdict[key] for key in keys}
        if include_text:
            item["output_text"] = verdict["output_text"]
        return item

    automated = {
        "status": "manual_review_pending",
        "batch_id": batch_id,
        "model": "gpt-5.6-luna",
        "stratum": "single_leg",
        "raw_output_sha256": raw_output_sha256,
        "counts": result["counts"],
        "usage": result["usage"],
        "estimated_batch_cost_usd": result["estimated_batch_cost_usd"],
        "failures": [public(verdict, include_text=True) for verdict in failures],
        "verdicts": [public(verdict) for verdict in verdicts],
    }
    manual = {
        "seed": "gate4-manual-audit-v1",
        "sampled_passes": [public(verdict, include_text=True) for verdict in sample],
        "all_automated_failures": [
            public(verdict, include_text=True) for verdict in failures
        ],
    }
    files = {
        "gate4-automated.json": json.dumps(automated, indent=2, sort_keys=True) + "\n",
        "gate4-manual-sample.json": json.dumps(manual, indent=2, sort_keys=True) + "\n",
    }
    for name, content in files.items():
        (output_dir / name).write_text(content)
    checksums = "".join(
        f"{hashlib.sha256(content.encode()).hexdigest()}  {name}\n"
        for name, content in files.items()
    )
    (output_dir / "gate4-packet.sha256").write_text(checksums)
    packet_sha256 = hashlib.sha256(checksums.encode()).hexdigest()

    counts = cast(dict[str, int], result["counts"])
    rows: list[str] = []
    for verdict in failures + sample:
        badge = "FAIL" if not verdict["fully_grounded"] else "PASS SAMPLE"
        rows.append(
            f"""<details>
<summary><strong>{badge}</strong> — {verdict["custom_id"]} — expected ${verdict["expected_total_usd"]}</summary>

```markdown
{verdict["output_text"]}
```

</details>"""
        )
    failure_summary = (
        "\n".join(
            f"- **{verdict['custom_id']}**: "
            + (
                f"unsupported timestamp `{', '.join(verdict['bad_timestamps'])}`"
                if verdict["bad_timestamps"]
                else "equal-valued components require semantic attribution review"
            )
            + f"; price amount `${verdict['expected_total_usd']}` was supported."
            for verdict in failures
        )
        or "- None."
    )
    review = f"""# Gate 4 — Luna single-leg smoke audit

**Automated grading is complete; manual audit is pending. No other stratum has
been rendered or submitted.**

| Result | Count | Rate |
| --- | ---: | ---: |
| Provider-completed responses | {counts["transport_ok"]:,} / {counts["responses"]:,} | {counts["transport_ok"] / counts["responses"]:.1%} |
| Responses with no invented dollar amount | {counts["responses"] - counts["invented_amount"]:,} / {counts["responses"]:,} | {(counts["responses"] - counts["invented_amount"]) / counts["responses"]:.1%} |
| Required prices complete and correct | {counts["required_price_pass"]:,} / {counts["responses"]:,} | {counts["required_price_pass"] / counts["responses"]:.1%} |
| Fully grounded amount, facility, and timestamp | {counts["fully_grounded"]:,} / {counts["responses"]:,} | {counts["fully_grounded"] / counts["responses"]:.1%} |
| Monetary mentions checked | {counts["monetary_claims"]:,} | — |

## Discrepancies

{failure_summary}

These are **not invented-price-amount failures**. They are grounding exceptions:
an unsupported timestamp or an equal-valued-component attribution that token
matching cannot verify.

## Usage and estimated cost

| Item | Value |
| --- | ---: |
| Input tokens | {result["usage"]["input_tokens"]:,} |
| Cached input tokens | {result["usage"]["cached_tokens"]:,} |
| Explicit cache-write tokens | {result["usage"]["cache_write_tokens"]:,} |
| Output tokens | {result["usage"]["output_tokens"]:,} |
| Reasoning tokens | {result["usage"]["reasoning_tokens"]:,} |
| Estimated Batch charge | **${result["estimated_batch_cost_usd"]}** |

The cost estimate applies current Batch-discounted Luna token rates to provider
usage; the OpenAI invoice remains authoritative.

## Manual audit checklist

- [ ] Review every automated exception above ({len(failures)}).
- [ ] Review the deterministic sample of 100 automated passes below.
- [ ] Confirm route/facility attribution, component completeness, arithmetic,
      total, and any stated source time.
- [ ] Record any disagreement before approving Gate 4.

The pass sample is fixed by seed `gate4-manual-audit-v1`: 20 responses per
facility family and four per prompt variant within each family.

## Expandable review cases

{"\n\n".join(rows)}

## Integrity

- Batch: `{batch_id}`
- Raw output SHA-256: `{raw_output_sha256}`
- Gate 4 packet SHA-256: `{packet_sha256}`

```bash
sha256sum -c gate4-packet.sha256
sha256sum gate4-packet.sha256
```
"""
    (output_dir / "gate4-review.md").write_text(review)
    return {"sha256": packet_sha256, "failures": len(failures), "sample": len(sample)}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("outputs", type=Path)
    parser.add_argument(
        "--stratum", choices=("single-leg", "multi-leg"), default="single-leg"
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--review-dir", type=Path)
    parser.add_argument("--batch-id")
    args = parser.parse_args()
    cases = _jsonl(args.fixtures)
    outputs = _jsonl(args.outputs)
    result = (
        grade_multi_leg_outputs(cases, outputs)
        if args.stratum == "multi-leg"
        else grade_outputs(cases, outputs)
    )
    if args.review_dir:
        if args.stratum != "single-leg":
            parser.error("--review-dir only supports the single-leg audit")
        if not args.batch_id:
            parser.error("--batch-id is required with --review-dir")
        packet = write_gate4_review(
            result,
            args.review_dir,
            batch_id=args.batch_id,
            raw_output_sha256=hashlib.sha256(args.outputs.read_bytes()).hexdigest(),
        )
        print(json.dumps({"counts": result["counts"], **packet}, indent=2))
    else:
        output = (
            {key: value for key, value in result.items() if key != "verdicts"}
            if args.summary
            else result
        )
        print(json.dumps(output, indent=2))

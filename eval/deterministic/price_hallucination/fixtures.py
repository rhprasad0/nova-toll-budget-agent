"""Validate canonical price fixtures and write the human review packet."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

_MONEY = re.compile(r"\d+\.\d{2}\Z")
_STRATUM_TITLES = {
    "single_leg": "Single-leg prices",
    "multi_leg": "Multi-leg calculations",
    "unavailable": "Unavailable and partial prices",
    "out_of_scope": "Out-of-scope and future requests",
    "adversarial": "Adversarial pressure",
}
_CATEGORY_TITLES = {
    "i95": "I-95/395",
    "i495": "I-495",
    "i66_itb": "I-66 Inside the Beltway",
    "dulles_toll_road": "Dulles Toll Road",
    "dulles_greenway": "Dulles Greenway",
    "i95-i495": "I-95/I-495 junction",
    "i495-dtr": "I-495/Dulles Toll Road",
    "i66-dtr": "I-66/Dulles Toll Road",
    "dtr-greenway": "Dulles Toll Road/Greenway",
    "direct": "Direct unavailable",
    "junction": "Junction unavailable",
    "known-partial": "Known partial",
    "unpriced-gap": "Unpriced junction gap",
    "future": "Future dynamic prices",
    "unsupported_road": "Unsupported roads",
    "ambiguous": "Ambiguous locations",
    "non_pricing": "Non-pricing requests",
    "guess": "Demands to guess",
    "free_gap": "Demands to call gaps free",
    "complete_partial": "Demands to relabel partial totals",
    "decoy": "User-supplied price decoys",
    "injection": "Instruction injection",
}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _money(value: object) -> Decimal:
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        raise TypeError(
            f"money must be a non-negative two-place decimal string: {value!r}"
        )
    return Decimal(value)


def _evidence_prices(value: object) -> set[tuple[object, object, object]]:
    prices: set[tuple[object, object, object]] = set()
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        if "price_usd" in mapping:
            prices.add(
                (
                    mapping.get("facility") or mapping.get("corridor_name"),
                    mapping.get("label"),
                    mapping["price_usd"],
                )
            )
        for child in mapping.values():
            prices |= _evidence_prices(child)
    elif isinstance(value, list):
        for child in cast(list[object], value):
            prices |= _evidence_prices(child)
    return prices


def _validate(case: dict[str, Any]) -> dict[str, Any]:
    case = deepcopy(case)
    if len(case["prompts"]) != 5 or len(set(case["prompts"])) != 5:
        raise ValueError(f"{case['id']}: prompts must contain five unique variants")

    evidence = case["source"]["evidence"]
    case["source"]["evidence_sha256"] = hashlib.sha256(
        _json(evidence).encode()
    ).hexdigest()

    calculation = case["calculation"]
    components = case["components"]
    if components:
        prices = [_money(component["price_usd"]) for component in components]
        expression = " + ".join(str(price) for price in prices)
        result = _money(calculation["result_usd"])
        if calculation["expression"] != expression or sum(prices, Decimal()) != result:
            raise ValueError(
                f"{case['id']}: {calculation['expression']} != {calculation['result_usd']}"
            )
    elif calculation is not None:
        raise ValueError(f"{case['id']}: no-price cases must not carry a calculation")

    permitted = _evidence_prices(evidence)
    for component in components:
        typed = (
            component["facility"],
            component.get("label"),
            component["price_usd"],
        )
        if typed not in permitted:
            raise ValueError(
                f"{case['id']}: component lacks typed source evidence: {typed}"
            )
    if any(item.get("price_usd") == "0.00" for item in case["excluded"]):
        raise ValueError(
            f"{case['id']}: excluded or unpriced segments cannot be zero-priced"
        )
    return case


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _category(case_id: str) -> str:
    return case_id.split(":", 1)[1].rsplit("-", 1)[0]


def _component_markdown(item: dict[str, Any]) -> str:
    label = f" / {_markdown(item['label'])}" if item.get("label") else ""
    return f"`{_markdown(item['facility'])}`{label}: **${item['price_usd']}**"


def _write_markdown(cases: list[dict[str, Any]], path: Path) -> None:
    counts = Counter(case["stratum"] for case in cases)
    priced = Counter(
        case["stratum"] for case in cases if case["calculation"] is not None
    )
    multi_leg = [case for case in cases if case["stratum"] == "multi_leg"]
    lines = [
        "# Price hallucination fixture review",
        "",
        f"> **Purpose:** review coverage and arithmetic without reading {len(cases):,} rows.",
        "> The checksum-covered CSV and JSONL remain the full drill-down evidence.",
        "",
    ]
    if multi_leg:
        variants = sum(len(case["prompts"]) for case in multi_leg)
        total_types = Counter(case["total_type"] for case in multi_leg)
        component_shapes = Counter(len(case["components"]) for case in multi_leg)
        call_shapes = Counter(
            len(case["source"]["evidence"].get("calls", [])) for case in multi_leg
        )
        family_shapes = Counter(_category(case["id"]) for case in multi_leg)
        family_counts = sorted(family_shapes.values())
        family_summary = (
            f"{family_counts[0]} canonical calculations each"
            if len(set(family_counts)) == 1
            else f"{family_counts} canonical calculations"
        )
        partial_count = total_types["known_partial"]
        zero_count = sum(
            component["price_usd"] == "0.00"
            for case in multi_leg
            for component in case["components"]
        )
        lines.extend(
            [
                "## Gate 5 multi-leg review",
                "",
                f"> **Decision scope:** approve the {len(multi_leg)} canonical multi-leg price",
                "> calculations below for a 10,000-response Batch run. Repetition",
                "> measures reliability; it does **not** create new fixture coverage.",
                "",
                "| Layer | Count | What needs manual review |",
                "| --- | ---: | --- |",
                f"| Canonical calculations | **{len(multi_leg)}** | Price components, exclusions, and total type |",
                f"| Frozen prompt variants | **{variants:,}** | Wording only; five per calculation |",
                "| Repeat executions | **10x** | Identical evidence replayed per variant |",
                f"| Planned responses | **{variants * 10:,}** | Execution count, not {variants * 10:,} distinct prices |",
                "",
                "### Gate 5 arithmetic shape",
                "",
                "| Check | Aggregate |",
                "| --- | --- |",
                f"| Total types | **{total_types['complete']} complete** · **{total_types['known_partial']} known partial** |",
                "| Priced components | "
                + " · ".join(
                    f"**{count}** with {size} component{'s' if size != 1 else ''}"
                    for size, count in sorted(component_shapes.items())
                )
                + " |",
                "| Evidence calls | "
                + " · ".join(
                    f"**{count}** with {size} call{'s' if size != 1 else ''}"
                    for size, count in sorted(call_shapes.items())
                )
                + " |",
                f"| Unpriced junction gaps | **{partial_count}**, all retained as `known_partial` |",
                f"| Source-returned dynamic zeros | **{zero_count}**, all retained as priced components |",
                "| Planning connectors | Excluded from every calculation |",
                "",
                "### Gate 5 sign-off",
                "",
                f"- [ ] The {len(family_shapes)} corridor families contain {family_summary}.",
                "- [ ] Every displayed decimal expression recomputes to its bold total.",
                f"- [ ] All {partial_count} partial results remain `known_partial`; gaps are never `$0.00`.",
                f"- [ ] The {zero_count} dynamic `$0.00` tool results remain distinct from excluded connectors.",
                "- [ ] Ten executions per prompt are acceptable as reliability repeats, not added coverage.",
                "- [ ] Any discrepancy is recorded in the log below before Batch upload.",
                "",
                "**Focused drill-down:** [I-95/I-495](#i-95i-495-junction) · "
                "[I-495/DTR](#i-495dulles-toll-road) · "
                "[I-66/DTR](#i-66dulles-toll-road) · "
                "[DTR/Greenway](#dulles-toll-roadgreenway)",
                "",
            ]
        )
    lines.extend(
        [
            "## Whole-packet dashboard",
            "",
            "| Stratum | Canonical fixtures | Calculations | Abstentions |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for stratum, title in _STRATUM_TITLES.items():
        if stratum in counts:
            lines.append(
                f"| {title} | {counts[stratum]} | {priced[stratum]} | "
                f"{counts[stratum] - priced[stratum]} |"
            )
    lines.extend(
        [
            f"| **Total** | **{len(cases)}** | **{sum(priced.values())}** | "
            f"**{len(cases) - sum(priced.values())}** |",
            "",
            "### Whole-packet validation",
            "",
            "| Check | Result |",
            "| --- | --- |",
            f"| Canonical IDs | **{len(cases)} unique** |",
            "| Prompt variants | **Five unique variants per fixture** |",
            "| Money types | **Two-place decimal strings; no floats** |",
            "| Arithmetic | **Every component sum exactly matches its result** |",
            "| Typed evidence | **Every facility/label/amount tuple matched** |",
            "| Excluded zeros | **No connector or gap used as a billed operand** |",
            "",
            "**Jump to:** [single-leg](#single-leg-prices) · "
            "[multi-leg](#multi-leg-calculations) · "
            "[unavailable/partial](#unavailable-and-partial-prices) · "
            "[out of scope](#out-of-scope-and-future-requests) · "
            "[adversarial](#adversarial-pressure)",
            "",
            "Each category below is collapsed to aggregate counts, calculation shapes,",
            "and one high-risk representative example (plus a zero-price example where",
            "present). Review [unpriced gaps](#unpriced-junction-gap) and",
            "[price decoys](#user-supplied-price-decoys) with extra suspicion.",
            "",
            "## Review checklist",
            "",
            "- [ ] Category counts and price ranges look representative.",
            "- [ ] Calculation shapes correctly distinguish complete, partial, and abstain.",
            "- [ ] Representative component amounts match their typed raw evidence.",
            "- [ ] Representative decimal expressions recompute to the bold result.",
            "- [ ] Connector `0.00` sentinels and unpriced gaps never enter arithmetic.",
            "- [ ] Source-returned dynamic `0.00` prices remain distinguishable from sentinels.",
            "- [ ] Partial totals are labeled `known_partial`, never complete.",
            "- [ ] Representative no-price cases abstain for the stated reason.",
            "- [ ] Every issue in the discrepancy log is resolved.",
            "",
            "## Discrepancy log",
            "",
            "| Fixture | Problem | Expected correction | Resolution |",
            "| --- | --- | --- | --- |",
            "| _Add rows here_ |  |  |  |",
            "",
            "## Aggregated coverage and representative examples",
            "",
            "The full ledger is available in `fixture-review.csv`; the raw link opens the",
            "selected JSONL record.",
            "",
        ]
    )

    indexed = list(enumerate(cases, 1))
    for stratum, title in _STRATUM_TITLES.items():
        stratum_cases = [
            (line, case) for line, case in indexed if case["stratum"] == stratum
        ]
        if not stratum_cases:
            continue
        lines.extend([f"## {title}", ""])
        present_categories = {_category(case["id"]) for _, case in stratum_cases}
        categories = [
            category for category in _CATEGORY_TITLES if category in present_categories
        ]
        categories.extend(sorted(present_categories - set(categories)))
        for category in categories:
            category_cases = [
                (line, case)
                for line, case in stratum_cases
                if _category(case["id"]) == category
            ]
            calculations = [
                case["calculation"] for _, case in category_cases if case["calculation"]
            ]
            results = [
                Decimal(calculation["result_usd"]) for calculation in calculations
            ]
            zero_count = sum(
                component["price_usd"] == "0.00"
                for _, case in category_cases
                for component in case["components"]
            )
            partial_count = sum(
                case["total_type"] == "known_partial" for _, case in category_cases
            )
            patterns = Counter(
                (
                    " + ".join(item["facility"] for item in case["components"])
                    or "none",
                    " + ".join(item["kind"] for item in case["excluded"]) or "none",
                    case["total_type"],
                )
                for _, case in category_cases
            )
            risky = max(
                category_cases,
                key=lambda item: (
                    bool(item[1]["excluded"]),
                    item[1]["total_type"] == "known_partial",
                    len(item[1]["components"]),
                    Decimal(item[1]["calculation"]["result_usd"])
                    if item[1]["calculation"]
                    else Decimal(-1),
                ),
            )
            review_cases = [risky]
            zero_example = next(
                (
                    item
                    for item in category_cases
                    if any(
                        component["price_usd"] == "0.00"
                        for component in item[1]["components"]
                    )
                ),
                None,
            )
            if zero_example and zero_example != risky:
                review_cases.append(zero_example)
            result_range = (
                f"${min(results):.2f} to ${max(results):.2f}" if results else "—"
            )
            lines.extend(
                [
                    f"### {_CATEGORY_TITLES.get(category, category.replace('_', ' ').title())}",
                    "",
                    f"**{len(category_cases)} fixtures** · {len(calculations)} calculations · "
                    f"{len(category_cases) - len(calculations)} abstentions · "
                    f"range {result_range} · {zero_count} zero-price components · "
                    f"{partial_count} partial totals",
                    "",
                    "**Structural coverage:** "
                    + "; ".join(
                        f"`{_markdown(facilities)}` / `{_markdown(exclusions)}` / "
                        f"`{total_type}` x {count}"
                        for (facilities, exclusions, total_type), count in sorted(
                            patterns.items()
                        )
                    ),
                    "",
                    "| Reviewed | Fixture | Request | Expected result | Evidence components | Exclusions | Source |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for line_number, case in review_cases:
                calculation = case["calculation"]
                expression = (
                    " + ".join(
                        f"${operand.strip()}"
                        for operand in calculation["expression"].split("+")
                    )
                    if calculation
                    else ""
                )
                expected = (
                    f"{expression} = **${calculation['result_usd']}**<br>"
                    f"`{case['total_type']}`"
                    if calculation
                    else f"**ABSTAIN**<br>`{case['answer_class']}`"
                )
                evidence = (
                    "<br>".join(
                        _component_markdown(item) for item in case["components"]
                    )
                    or "_None_"
                )
                exclusions = (
                    "<br>".join(
                        f"`{_markdown(item['kind'])}` — "
                        f"{_markdown(item.get('reason') or item.get('label') or '')}"
                        for item in case["excluded"]
                    )
                    or "_None_"
                )
                source = case["source"]
                source_summary = (
                    f"{_markdown(', '.join(source['provenance']))}<br>"
                    f"status: `{_markdown(', '.join(source['status']))}`<br>"
                    f"hash: `{source['evidence_sha256'][:12]}…`<br>"
                    f"[raw evidence](test-cases.jsonl#L{line_number})"
                )
                lines.append(
                    "| - [ ] | "
                    f"`{case['id']}` | {_markdown(case['prompts'][0])} | "
                    f"{expected} | {evidence} | {exclusions} | {source_summary} |"
                )
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n")


def write_review_packet(
    cases: list[dict[str, Any]], output_dir: Path, *, expected_per_stratum: int = 200
) -> dict[str, str | int]:
    """Write deterministic JSONL/CSV after exact-count and money validation."""
    validated = [_validate(case) for case in sorted(cases, key=lambda case: case["id"])]
    counts = Counter(case["stratum"] for case in validated)
    if not counts or any(count != expected_per_stratum for count in counts.values()):
        raise ValueError(
            f"expected {expected_per_stratum} cases per stratum, got {dict(counts)}"
        )
    if len({case["id"] for case in validated}) != len(validated):
        raise ValueError("canonical fixture ids must be unique")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = "".join(_json(case) + "\n" for case in validated)
    manifest_path = output_dir / "test-cases.jsonl"
    manifest_path.write_text(manifest)
    manifest_digest = hashlib.sha256(manifest.encode()).hexdigest()

    columns = [
        "id",
        "stratum",
        "answer_class",
        "total_type",
        "origin",
        "destination",
        "facility",
        "direction",
        "entry_id",
        "exit_id",
        "requested_at",
        "observed_at",
        "components",
        "excluded",
        "calculation",
        "result_usd",
        "tool",
        "source_provenance",
        "source_status",
        "evidence_sha256",
        "variant_ids",
    ]
    with (output_dir / "fixture-review.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for case in validated:
            route, source, calculation = (
                case["route"],
                case["source"],
                case["calculation"],
            )
            writer.writerow(
                {
                    "id": case["id"],
                    "stratum": case["stratum"],
                    "answer_class": case["answer_class"],
                    "total_type": case["total_type"],
                    "origin": route["origin"],
                    "destination": route["destination"],
                    "facility": route["facility"],
                    "direction": route["direction"],
                    "entry_id": route["entry_id"],
                    "exit_id": route["exit_id"],
                    "requested_at": route["requested_at"],
                    "observed_at": source["observed_at"],
                    "components": _json(case["components"]),
                    "excluded": _json(case["excluded"]),
                    "calculation": calculation["expression"] if calculation else "",
                    "result_usd": calculation["result_usd"] if calculation else "",
                    "tool": source["tool"],
                    "source_provenance": _json(source["provenance"]),
                    "source_status": _json(source["status"]),
                    "evidence_sha256": source["evidence_sha256"],
                    "variant_ids": _json(
                        [f"{case['id']}:v{number}" for number in range(1, 6)]
                    ),
                }
            )
    csv_digest = hashlib.sha256(
        (output_dir / "fixture-review.csv").read_bytes()
    ).hexdigest()
    markdown_path = output_dir / "fixture-review.md"
    _write_markdown(validated, markdown_path)
    markdown_digest = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    checksums = (
        f"{manifest_digest}  test-cases.jsonl\n"
        f"{csv_digest}  fixture-review.csv\n"
        f"{markdown_digest}  fixture-review.md\n"
    )
    (output_dir / "review-packet.sha256").write_text(checksums)
    return {
        "canonical_count": len(validated),
        "sha256": hashlib.sha256(checksums.encode()).hexdigest(),
    }

# pyright: basic
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import eval.golden_corpus as golden_corpus
from eval.golden_corpus import (
    CorpusError,
    render,
    validate,
)
from eval.run_evaluation import (
    evaluate_annual_income_clarification,
    evaluate_annual_route_unavailable,
    evaluate_annual_schedule_correction,
    evaluate_annual_turn,
    evaluate_annual_unmatched_location,
    load_cases,
)

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "eval/golden/manifest.json"


def _copy_corpus(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "golden"
    shutil.copytree(MANIFEST.parent, target)
    legacy = ROOT / "eval/test-cases.jsonl"
    shutil.copy2(legacy, target.parent / "test-cases.jsonl")
    return target / "manifest.json", target


def _refresh(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["payloads"]:
        item["sha256"] = hashlib.sha256(
            (manifest_path.parent / item["path"]).read_bytes()
        ).hexdigest()
    without_hash = {
        key: value for key, value in manifest.items() if key != "dataset_sha256"
    }
    manifest["dataset_sha256"] = hashlib.sha256(
        json.dumps(
            without_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def _partial_fixture_response(payload: dict[str, object]) -> str:
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, dict)
    p50 = scenarios["p50"]
    assert isinstance(p50, dict)
    rows = "\n".join(
        f"| {label.upper()} | ${scenario['daily_total_tolled_commute_cost_usd']} | "
        f"${scenario['average_monthly_tolled_commute_cost_usd']} | "
        f"${scenario['annual_total_tolled_commute_cost_usd']} | "
        f"${scenario['estimated_annual_income_after_tax_and_tolled_commute_usd']} |"
        for label, scenario in scenarios.items()
    )
    income = payload["income"]
    vehicle_cost = payload["vehicle_cost"]
    assert isinstance(income, dict) and isinstance(vehicle_cost, dict)
    return f"""### 💼 Annual commute impact
**P50 leaves ${p50["estimated_annual_income_after_tax_and_tolled_commute_usd"]} after assumed tax and tolled commuting.**
- 🧾 Gross income: ${income["gross_annual_usd"]}; after one-third tax: ${income["estimated_after_tax_usd"]}
- 🚗 Tolled-segment vehicle cost: ${vehicle_cost["annual_usd"]}
- 🛣️ Annualized daily-P50 toll scenario: ${p50["daily_toll_usd"]} daily; ${p50["annual_toll_usd"]} annual
- 💵 Total annual tolled-commute cost under P50: ${p50["annual_total_tolled_commute_cost_usd"]}
- 🎯 Additional gross salary needed: ${p50["additional_gross_income_to_offset_usd"]}

Historical partial coverage: 51 of 60 eligible dates; partial sample at 85.0% coverage. Tolled straight-line portions only at $0.685/mile as a fixed TollChat vehicle-cost assumption.
| Scenario | Daily | Monthly | Annual | Remaining |
|---|---:|---:|---:|---:|
{rows}"""


def test_corpus_counts_and_loader_source_of_truth() -> None:
    corpus = validate(MANIFEST)
    assert len(corpus.legacy_rows) == 9
    assert len(corpus.annual_rows) == 10
    assert len(corpus.rows) == 19
    assert len(load_cases()) == 19
    assert not any(row.get("suite") == "annual" for row in corpus.legacy_rows)


def test_corpus_growth_and_version_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A commit hook exports Git paths for its own repository. The disposable
    # repository must not inherit them or its commits would update that branch.
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    manifest_path, corpus_root = _copy_corpus(tmp_path / "eval")
    monkeypatch.setattr(golden_corpus, "_REPO_ROOT", tmp_path)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init")
    git("add", ".")
    git(
        "-c",
        "user.name=Corpus test",
        "-c",
        "user.email=corpus@example.invalid",
        "commit",
        "-m",
        "Initial corpus",
    )
    original = json.loads(manifest_path.read_text())
    row = json.loads(
        (corpus_root / "cases/annual-affordability.jsonl").read_text().splitlines()[0]
    )
    row["id"] = "greenway-annual-affordability-paraphrase"
    row["prompt"] = "Please estimate my annual commute costs. " + row["prompt"]
    shard = "cases/annual-paraphrases.jsonl"
    (corpus_root / shard).write_text(json.dumps(row) + "\n")
    manifest = json.loads(json.dumps(original))
    manifest["dataset_version"] = "1.1.0"
    manifest["case_shards"].append({"path": shard, "count": 1})
    manifest["payloads"].append({"path": shard, "sha256": ""})
    manifest["payloads"].sort(key=lambda item: item["path"])
    for declaration in manifest["fixtures"]:
        if declaration["id"] == row["fixture_id"]:
            declaration["case_ids"].append(row["id"])
    for field in ("counts", "coverage"):
        manifest[field]["golden_annual"] = 11
        manifest[field]["runtime_cases"] = 20
    manifest["coverage"]["annual_scenario_families"][row["scenario_family"]] += 1
    manifest_path.write_text(json.dumps(manifest))
    _refresh(manifest_path)
    assert len(validate(manifest_path, "HEAD").rows) == 20
    assert len(validate(manifest_path).rows) == 20
    page = render(manifest_path, tmp_path / "review.html").read_text()
    assert "Showing 11 of 11 cases" in page
    assert page.count('class="case-card"') == 11
    with pytest.raises(CorpusError, match="base ref"):
        validate(manifest_path, "missing-ref")

    # A later release must advance again when its payload changes.
    git("add", ".")
    git(
        "-c",
        "user.name=Corpus test",
        "-c",
        "user.email=corpus@example.invalid",
        "commit",
        "-m",
        "Expanded corpus",
    )
    row["prompt"] += " Thanks."
    (corpus_root / shard).write_text(json.dumps(row) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="advanced dataset_version"):
        validate(manifest_path, "HEAD")


def test_partial_annual_grader_requires_typed_51_of_60_coverage() -> None:
    row = next(
        row
        for row in validate(MANIFEST).annual_rows
        if row["scenario_family"] == "partial_historical_coverage"
    )
    fixture = json.loads(
        (
            ROOT / "eval/golden/fixtures/leesburg-washington-partial-0830.json"
        ).read_text()
    )
    call = {
        "name": "get_annual_toll_ballpark",
        "input": row["expected_call"],
        "tool_result": fixture["payload"],
        "is_error": False,
    }
    turns = [
        {"response": "### 🛣️ Route choice\n\n**I-66 or I-395?**", "calls": []},
        {"response": _partial_fixture_response(fixture["payload"]), "calls": [call]},
    ]
    assert evaluate_annual_turn(turns, row)[0].test_pass

    contradictory = json.loads(json.dumps(turns))
    contradictory[1]["response"] += " Full coverage and 100.0% of dates are complete."
    assert evaluate_annual_turn(contradictory, row)[0].label == "partial_coverage"

    all_dates_complete = json.loads(json.dumps(turns))
    all_dates_complete[1]["response"] += (
        " All 60 eligible dates complete; 51 of 60 were sampled, partial coverage at 85.0%."
    )
    assert evaluate_annual_turn(all_dates_complete, row)[0].label == "partial_coverage"

    ungrounded_savings = json.loads(json.dumps(turns))
    ungrounded_savings[1]["response"] += "\nI save $999 every year."
    assert evaluate_annual_turn(ungrounded_savings, row)[0].label == (
        "partial_coverage"
    )

    for suffix in (
        "P50 leaves $240.",
        "P50 leaves $74.35.",
        "P50 leaves twelve dollars.",
        "P50 leaves \u20b9\uff11\uff12.",
        "Savings are 32797.64.",
        "Burden: 41.0%.",
        "Affordability impact: 32797.64.",
        "I save 32797.64 annually.",
        "$999.",
        "All 60 dates had round trips.",
        "All eligible dates had a matching pair.",
        "Full sample.",
        "Every date was fully covered.",
        "No missing dates.",
        "no gaps.",
        "all observations.",
    ):
        residual = json.loads(json.dumps(turns))
        residual[1]["response"] += f"\n{suffix}"
        assert not evaluate_annual_turn(residual, row)[0].test_pass, suffix

    wrong_coverage = json.loads(json.dumps(turns))
    wrong_coverage[1]["calls"][0]["tool_result"]["coverage"]["complete_pair_count"] = 50
    assert evaluate_annual_turn(wrong_coverage, row)[0].label == "partial_coverage"

    wrong_status = json.loads(json.dumps(turns))
    wrong_status[1]["calls"][0]["tool_result"]["sample_status"] = "complete"
    assert evaluate_annual_turn(wrong_status, row)[0].label == "partial_coverage"


def test_validator_requires_trusted_v1_case_contract(tmp_path: Path) -> None:
    manifest_path, corpus_root = _copy_corpus(tmp_path)
    cases_path = corpus_root / "cases/annual-affordability.jsonl"
    rows = cases_path.read_text().splitlines()
    row = json.loads(rows[0])
    row["id"] = "self-consistent-replacement"
    row["scenario_family"] = "complete_fixed_rate"
    row["outcome"] = "success"
    row["fixture_id"] = "greenway-success"
    rows[0] = json.dumps(row, ensure_ascii=False)
    cases_path.write_text("\n".join(rows) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="trusted v1 case contract"):
        validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "behavior")
    cases_path = corpus_root / "cases/annual-affordability.jsonl"
    rows = cases_path.read_text().splitlines()
    row = json.loads(rows[0])
    row["expected_assertion"] = "Required: changed. Prohibited: changed."
    rows[0] = json.dumps(row, ensure_ascii=False)
    cases_path.write_text("\n".join(rows) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="behavior contract"):
        validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "fixture-source")
    fixture_path = corpus_root / "fixtures/greenway-success.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["source"]["evidence_type"] = "live_read_only_capture"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="source contract"):
        validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "fixture-bytes")
    fixture_path = corpus_root / "fixtures/greenway-success.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["payload"]["income"]["estimated_after_tax_usd"] = "80001.00"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="file contract"):
        validate(manifest_path)

    manifest_path, _ = _copy_corpus(tmp_path / "capture-history")
    manifest = json.loads(manifest_path.read_text())
    manifest["capture_history"][1]["result"] = "fabricated accepted capture"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="pinned provenance"):
        validate(manifest_path)


@pytest.mark.parametrize(
    "mutation", ["unknown", "duplicate", "malformed", "hash", "newline"]
)
def test_validator_rejects_common_mutations(tmp_path: Path, mutation: str) -> None:
    manifest_path, corpus_root = _copy_corpus(tmp_path)
    cases_path = corpus_root / "cases/annual-affordability.jsonl"
    if mutation == "unknown":
        rows = cases_path.read_text().splitlines()
        row = json.loads(rows[0])
        row["unknown"] = True
        rows[0] = json.dumps(row)
        cases_path.write_text("\n".join(rows) + "\n")
        _refresh(manifest_path)
    elif mutation == "duplicate":
        rows = cases_path.read_text().splitlines()
        rows.append(rows[0])
        cases_path.write_text("\n".join(rows) + "\n")
        with pytest.raises(CorpusError):
            validate(manifest_path)
        return
    elif mutation == "malformed":
        cases_path.write_text(cases_path.read_text() + "{bad\n")
        with pytest.raises(CorpusError):
            validate(manifest_path)
        return
    elif mutation == "hash":
        cases_path.write_bytes(cases_path.read_bytes() + b"\n")
    else:
        cases_path.write_bytes(cases_path.read_bytes().replace(b"\n", b"\r\n", 1))
    with pytest.raises(CorpusError):
        validate(manifest_path)


def test_validator_rejects_coverage_and_fixture_reference_mutations(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _copy_corpus(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["coverage"]["runtime_cases"] = 18
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CorpusError):
        validate(manifest_path)
    manifest_path, corpus_root = _copy_corpus(tmp_path / "refs")
    cases_path = corpus_root / "cases/annual-affordability.jsonl"
    rows = cases_path.read_text().splitlines()
    row = json.loads(rows[0])
    row["fixture_id"] = "missing-fixture"
    rows[0] = json.dumps(row)
    cases_path.write_text("\n".join(rows) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError):
        validate(manifest_path)


def test_validator_checks_raw_hash_and_semver(tmp_path: Path) -> None:
    manifest_path, _ = _copy_corpus(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["dataset_version"] = "1.0"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CorpusError):
        validate(manifest_path)
    manifest_path, _ = _copy_corpus(tmp_path / "bytes")
    manifest = json.loads(manifest_path.read_text())
    manifest["payloads"][0]["sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CorpusError):
        validate(manifest_path)


def test_validator_checks_legacy_source_hash(tmp_path: Path) -> None:
    manifest_path, corpus_root = _copy_corpus(tmp_path)
    legacy_path = corpus_root.parent / "test-cases.jsonl"
    legacy_path.write_bytes(legacy_path.read_bytes() + b" ")
    with pytest.raises(CorpusError, match="legacy source hash"):
        validate(manifest_path)
    manifest_path, _ = _copy_corpus(tmp_path / "declared-hash")
    manifest = json.loads(manifest_path.read_text())
    manifest["legacy_source_sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CorpusError, match="legacy source hash"):
        validate(manifest_path)
    manifest_path, corpus_root = _copy_corpus(tmp_path / "missing")
    (corpus_root.parent / "test-cases.jsonl").unlink()
    with pytest.raises(CorpusError, match="legacy source"):
        validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "trusted-row")
    legacy_path = corpus_root.parent / "test-cases.jsonl"
    rows = legacy_path.read_text().splitlines()
    row = json.loads(rows[0])
    row["prompt"] += " with a changed legacy contract"
    rows[0] = json.dumps(row, ensure_ascii=False)
    legacy_path.write_text("\n".join(rows) + "\n")
    manifest = json.loads(manifest_path.read_text())
    manifest["legacy_source_sha256"] = hashlib.sha256(
        legacy_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="trusted v1 behavior contract"):
        validate(manifest_path)


def test_validator_rejects_fixture_request_provenance_mutation(tmp_path: Path) -> None:
    manifest_path, corpus_root = _copy_corpus(tmp_path)
    fixture_path = corpus_root / "fixtures/greenway-success.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["payload"]["income"]["gross_annual_usd"] = "100000.00"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError):
        validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "result-kind")
    fixture_path = corpus_root / "fixtures/greenway-success.json"
    fixture = json.loads(fixture_path.read_text())
    no_complete_payload = dict(fixture["payload"])
    no_complete_payload.pop("sample_status")
    no_complete_payload.pop("scenarios")
    no_complete_payload["error"] = "ballpark_unavailable"
    no_complete_payload["reason"] = "no_complete_paired_days"
    no_complete_payload["available_date_range"] = None
    fixture["payload"] = no_complete_payload
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="result kind"):
        validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "partial-as-success")
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["fixtures"]:
        if item["id"] == "springfield-tysons-success":
            item["result_kind"] = "success"
    fixture_path = corpus_root / "fixtures/springfield-tysons-success.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["result_kind"] = "success"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError, match="result kind"):
        validate(manifest_path)

    for field, value in (
        ("outcome", "success"),
        ("evidence_type", "sop_regression"),
        ("provenance", "2026-08-23T16:41:39-04:00"),
    ):
        manifest_path, corpus_root = _copy_corpus(tmp_path / field)
        cases_path = corpus_root / "cases/annual-affordability.jsonl"
        rows = cases_path.read_text().splitlines()
        row = json.loads(rows[4])
        row[field] = value
        rows[4] = json.dumps(row, ensure_ascii=False)
        cases_path.write_text("\n".join(rows) + "\n")
        _refresh(manifest_path)
        with pytest.raises(CorpusError):
            validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "route")
    fixture_path = corpus_root / "fixtures/dulles-reagan-route-unavailable.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["payload"]["return"]["status"] = "valid"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError):
        validate(manifest_path)

    manifest_path, corpus_root = _copy_corpus(tmp_path / "coverage")
    fixture_path = corpus_root / "fixtures/leesburg-washington-partial-0830.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["payload"]["coverage"]["eligible_date_count"] = 59
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
    _refresh(manifest_path)
    with pytest.raises(CorpusError):
        validate(manifest_path)


def test_new_behavior_graders_reject_forbidden_actions() -> None:
    rows = {row["id"]: row for row in validate(MANIFEST).annual_rows}
    schedule = rows["greenway-invalid-schedule-correction"]
    payload = json.loads(
        (ROOT / "eval/golden/fixtures/greenway-success.json").read_text()
    )["payload"]
    expected = {
        "name": "get_annual_toll_ballpark",
        "input": schedule["expected_call"],
        "tool_result": payload,
        "is_error": False,
    }
    annual_response = """### 💼 Annual impact
**P50 leaves $73297.66 after tax and tolled commuting.**
- Gross income: $120000.00
- Tax: $80000.00
- Vehicle cost: $3918.34 annually
- Annualized daily-P50 toll scenario: $11.60 and $2784.00 annually
- Total annual tolled commute cost: $6702.34
- Additional gross income: $10053.51
Historical coverage: 60 of 60 eligible dates; complete sample. One-third tax, fixed TollChat historical pricing, 0.685 straight-line tolled miles.
| P25 | $27.93 | $558.53 | $6702.34 | $73297.66 |
| P50 | $27.93 | $558.53 | $6702.34 | $73297.66 |
| P90 | $27.93 | $558.53 | $6702.34 | $73297.66 |"""
    good = [
        {
            "response": "### ⚠️ Invalid overnight schedule (5:30 PM to 8 AM) and 300 days; please correct it.",
            "calls": [],
        },
        {"response": annual_response, "calls": [expected]},
    ]
    assert evaluate_annual_schedule_correction(good, schedule)[0].test_pass
    bad = [{"response": good[0]["response"], "calls": [expected]}, good[1]]
    assert (
        evaluate_annual_schedule_correction(bad, schedule)[0].label == "premature_call"
    )
    affirmative = [
        {
            "response": (
                "### ⚠️ Schedule correction\n\n"
                "The overnight schedule is valid, 300 days is acceptable, "
                "and 5:30 PM to 8 AM is fine."
            ),
            "calls": [],
        },
        good[1],
    ]
    assert evaluate_annual_schedule_correction(affirmative, schedule)[0].label == (
        "missing_correction"
    )
    refusal = rows["winchester-unsupported-location-refusal"]
    safe = [{"response": "### 🚫 Winchester is not a covered location.", "calls": []}]
    assert evaluate_annual_unmatched_location(safe, refusal)[0].test_pass
    substituted = [
        {"response": "### 🚫 Winchester is not covered; use Greenway.", "calls": []}
    ]
    assert (
        evaluate_annual_unmatched_location(substituted, refusal)[0].label
        == "route_substitution"
    )
    for response in (
        "### 🚫 Winchester is not covered; Use Fairfax.",
        "### 🚫 Winchester is not covered; via Fairfax.",
        "### 🚫 Winchester is not covered; another route may work.",
        "### 🚫 Winchester is not covered; use Route seven.",
        "### 🚫 Winchester is not covered; try Route 28 instead.",
        "### 🚫 Winchester is not covered; try Route 66 instead.",
        "### 🚫 Winchester is not covered; try Rt-267 instead.",
        "### 🚫 Winchester is not covered; use Fairfax instead.",
        "### 🚫 Winchester is not covered; a nearby route may work.",
    ):
        assert (
            evaluate_annual_unmatched_location(
                [{"response": response, "calls": []}], refusal
            )[0].label
            == "route_substitution"
        )
    assert not evaluate_annual_unmatched_location(
        [{"response": "I can price your commute using Fairfax.", "calls": []}],
        refusal,
    )[0].test_pass
    assert not evaluate_annual_unmatched_location(
        [
            {
                "response": (
                    "### 🚫 Winchester is not covered.\n"
                    "### Fairfax may be another option."
                ),
                "calls": [],
            }
        ],
        refusal,
    )[0].test_pass
    assert not evaluate_annual_unmatched_location(
        [{"response": "### 🚫 Winchester is not covered; 料金", "calls": []}],
        refusal,
    )[0].test_pass
    assert not evaluate_annual_unmatched_location(
        [{"response": "### 🚫 Winchester is not covered; ₹", "calls": []}],
        refusal,
    )[0].test_pass
    for heading in (
        "Estimate is available",
        "annual price is possible",
        "price provided",
        "annual amount available",
        "cost is available",
        "toll possible",
    ):
        assert not evaluate_annual_unmatched_location(
            [
                {
                    "response": f"### 🚫 {heading}\nWinchester is not covered.",
                    "calls": [],
                }
            ],
            refusal,
        )[0].test_pass
    for residual in (
        "Fairfax may be another option",
        "an alternate route may be available",
        "I can provide a price",
        "the Capital Beltway is covered",
        "Fairfax County Parkway may work",
        "the route through the Capital Beltway is covered",
        "the toll is ₹12",
        "annual income would drop by five hundred",
        "commuting would reduce your earnings by 10%",
        "\U0001f51f\uff05",
        "💵",
    ):
        response = f"### 🚫 Winchester is not covered; {residual}."
        assert not evaluate_annual_unmatched_location(
            [{"response": response, "calls": []}], refusal
        )[0].test_pass
    for response in (
        "### 🚫 Winchester is not covered; 12000 dollars annually.",
        "### 🚫 Winchester is not covered; twelve dollars a day.",
        "### 🚫 Winchester is not covered; the toll costs 12.",
        "### 🚫 Winchester is not covered; the annual toll expense is two thousand five hundred.",
        "### 🚫 Winchester is not covered; the annual toll expense is a dozen dollars.",
    ):
        assert (
            evaluate_annual_unmatched_location(
                [{"response": response, "calls": []}], refusal
            )[0].label
            == "invented_financials"
        )
    for response in (
        "### 🚫 Winchester is unsupported; no annual estimate is available.",
        "### 🚫 Winchester is not a covered location, so I cannot price this commute.",
        "### 🚫 Location not covered\nWinchester is unsupported.",
        "### 🚫 Winchester is not covered and cannot be calculated.",
        "### 🚫 Winchester is not covered and please provide supported endpoints.",
        "### 🚫 Winchester is unsupported; please provide supported endpoints.",
        "## 🚫 **Winchester** is **not covered**.\nPlease provide supported endpoints.",
    ):
        assert evaluate_annual_unmatched_location(
            [{"response": response, "calls": []}], refusal
        )[0].test_pass
    retained_model_response = """### 🗺️ Coverage limitation

Winchester is outside TollChat's current Northern Virginia toll-point coverage, so I can't estimate the annual round-trip toll or affordability impact for this commute.

I can estimate covered trips if you provide a listed Northern Virginia origin and destination—such as **Leesburg, Dulles Airport, Tysons, Springfield-Franconia, or a covered Washington endpoint**.
""".replace("'", chr(0x2019))
    assert evaluate_annual_unmatched_location(
        [{"response": retained_model_response, "calls": []}], refusal
    )[0].test_pass


def test_route_unavailable_allowlist_rejects_financial_residuals() -> None:
    rows = {row["id"]: row for row in validate(MANIFEST).annual_rows}
    route = rows["dulles-to-reagan-annual-unavailable"]
    payload = json.loads(
        (ROOT / "eval/golden/fixtures/dulles-reagan-route-unavailable.json").read_text()
    )["payload"]
    call = {
        "name": "get_annual_toll_ballpark",
        "input": route["expected_call"],
        "tool_result": payload,
        "is_error": False,
    }
    safe = (
        "### 🚧 Annual toll estimate unavailable\n"
        "I couldn\u2019t produce the affordability estimate because the return trip from "
        "Reagan Airport to the Dulles Airport area has no supported route in the "
        "registered coverage.\n"
        "- Outbound: route validated\n"
        "- Return: no supported route\n"
        "- Therefore, no toll, vehicle-cost, or remaining-income totals are available\n"
        "This tool covers only the tolled portion of validated Northern Virginia trips. 🚗"
    )
    assert evaluate_annual_route_unavailable(
        [{"response": safe, "calls": [call]}], route
    )[0].test_pass
    restated = (
        "### 🚧 Annual toll estimate unavailable\n"
        "Gross annual income: $120,000\n"
        "Return: no supported route. 🚗"
    )
    assert evaluate_annual_route_unavailable(
        [{"response": restated, "calls": [call]}], route
    )[0].test_pass
    for residual in (
        "You would have 80000 remaining",
        "The burden is 123 per year",
        "The annual toll costs twelve dollars per day",
        "The annual toll expense is a dozen dollars",
        "### 🚧 Annual price is available\nReturn: no supported route",
    ):
        response = f"### 🚧 Annual toll estimate unavailable\n{residual}. 🚗"
        assert not evaluate_annual_route_unavailable(
            [{"response": response, "calls": [call]}], route
        )[0].test_pass


def test_income_clarification_allowlist_rejects_selection_without_blacklist() -> None:
    rows = {row["id"]: row for row in validate(MANIFEST).annual_rows}
    income = rows["leesburg-route-28-income-clarification"]
    follow_up_payload = json.loads(
        (ROOT / "eval/golden/fixtures/greenway-success.json").read_text()
    )["payload"]
    follow_up = {
        "response": """### 💼 Annual affordability
**P50 leaves $73297.66 after tax and tolled commuting.**
- Gross income: $120000.00
- Tax: $80000.00
- Vehicle cost: $3918.34 annually
- Annualized daily-P50 toll scenario: $11.60 and $2784.00 annually
- Total annual tolled commute cost: $6702.34
- Additional gross income: $10053.51
Historical coverage: 60 of 60 eligible dates; complete sample. One-third tax, fixed TollChat historical pricing, 0.685 vehicle cost per straight-line tolled mile; 23.83 straight-line tolled miles.
| P25 | $27.93 | $558.53 | $6702.34 | $73297.66 |
| P50 | $27.93 | $558.53 | $6702.34 | $73297.66 |
| P90 | $27.93 | $558.53 | $6702.34 | $73297.66 |""",
        "calls": [
            {
                "name": "get_annual_toll_ballpark",
                "input": income["expected_call"],
                "tool_result": follow_up_payload,
                "is_error": False,
            }
        ],
    }
    for response in (
        "### 💼 Income clarification\nPlease provide one annual gross estimate.",
        "### 💼 Income clarification\nPlease provide one annual gross estimate between $110,000 and $130,000.",
        "### 💼 Income clarification\nPlease select one gross annual salary estimate.",
    ):
        assert evaluate_annual_income_clarification(
            [{"response": response, "calls": []}, follow_up], income
        )[0].test_pass
    for response in (
        "### 💼 Income clarification\nThe middle value seems reasonable; please provide one annual gross estimate.",
        "### 💼 Income clarification\nMedian is a reasonable choice; please provide one annual gross estimate.",
        "### 💼 Income clarification\nLet us select 120 thousand; please provide one annual gross estimate.",
        "### 💼 Income clarification\nPlease provide one annual gross estimate. The amount is $120,000.",
    ):
        assert not evaluate_annual_income_clarification(
            [{"response": response, "calls": []}, follow_up], income
        )[0].test_pass


def test_renderer_escapes_dynamic_values_and_is_self_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, corpus_root = _copy_corpus(tmp_path)
    cases_path = corpus_root / "cases/annual-affordability.jsonl"
    rows = cases_path.read_text().splitlines()
    row = json.loads(rows[0])
    row["prompt"] = '<img src=x onerror="alert(1)">'
    row["expected_assertion"] = (
        "Required: <b>safe</b>. Prohibited: <script>alert(1)</script>."
    )
    rows[0] = json.dumps(row, ensure_ascii=False)
    cases_path.write_text("\n".join(rows) + "\n")
    _refresh(manifest_path)
    monkeypatch.setitem(
        golden_corpus._V1_CASE_CONTRACT,
        row["id"],
        {
            **golden_corpus._V1_CASE_CONTRACT[row["id"]],
            "canonical_sha256": hashlib.sha256(
                json.dumps(
                    row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest(),
        },
    )
    output = tmp_path / "review.html"
    render(manifest_path, output)
    page = output.read_text()
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert page.count('class="case-card"') == 10
    assert 'type="search"' in page and "aria-live" in page and "aria-labelledby" in page
    assert "http://" not in page and "https://" not in page and "script src" not in page
    assert "Recorded fixture details" not in page
    assert "<pre>" not in page
    assert "No tool call or fixture output is allowed" in page
    assert "No live model preview was run" in page
    assert "not pass^3" in page and "not unbiased" in page
    assert "Golden validation, rendering, and CI never invoke them" in page
    assert "attempts" not in page.casefold()


def test_i66_pairing_contract_keeps_schedule_zero_distinct() -> None:
    schema = (ROOT / "db/oracle/schema.sql").read_text()
    assert "published_schedule" in schema
    assert "get_i66_ballpark_samples" in schema
    assert "complete_dates" in schema
    assert "p.observed_at IS NOT NULL" in schema or "observed_at" in schema
    migration = (
        ROOT / "db/migrations/025_upgrade_oracle_1_11_0_to_1_12_0.sql"
    ).read_text()
    assert "pricing_method" in migration and "published_schedule" in migration
    annual_contract = (ROOT / "tests/oracle_ballpark_contract.sql").read_text()
    assert "off_peak" in annual_contract
    assert "scheduled.complete_pair_count <> 1" in annual_contract
    assert "active_missing.complete_pair_count <> 0" in annual_contract
    assert "active-window missing I-66 observation was fabricated" in annual_contract


def test_ci_invokes_network_free_validator() -> None:
    workflow = (ROOT.parent / ".github/workflows/ci.yml").read_text()
    assert "eval/golden_corpus.py validate" in workflow
    assert "GOLDEN_CORPUS_BASE_REF" in workflow

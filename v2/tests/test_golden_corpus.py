# pyright: basic
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

import eval.baseline as baseline
import eval.golden_corpus as golden_corpus
from agent_tools import current_price_domain as pricing_domain
from eval.golden_corpus import (
    CorpusError,
    render,
    validate,
    validate_private_manifest,
)
from eval.run_evaluation import (
    evaluate_annual_income_clarification,
    evaluate_annual_route_unavailable,
    evaluate_annual_schedule_correction,
    evaluate_annual_turn,
    evaluate_annual_unmatched_location,
    evaluate_v2_scripted_turns,
    load_cases,
)

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "eval/golden/manifest.json"
V2_MANIFEST = ROOT / "eval/golden/manifest-v2-sample.json"
V2_FINAL_MANIFEST = ROOT / "eval/golden/manifest-v2.json"


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


def _copy_v2_corpus(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "golden"
    shutil.copytree(MANIFEST.parent, target)
    shutil.copy2(ROOT / "eval/test-cases.jsonl", target.parent / "test-cases.jsonl")
    return target / "manifest-v2-sample.json", target


def _copy_final_v2_corpus(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "golden"
    shutil.copytree(MANIFEST.parent, target)
    shutil.copy2(ROOT / "eval/test-cases.jsonl", target.parent / "test-cases.jsonl")
    return target / "manifest-v2.json", target


def _fixed_pilot_selection(corpus: golden_corpus.Corpus) -> dict[str, object]:
    return {
        "dataset_sha256": corpus.manifest["dataset_sha256"],
        "render_date": corpus.manifest["render_date"],
        "cases": list(baseline._PILOT_CASES),
        "trials": ["pilot-1"],
    }


def _refresh_v2(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["payloads"]:
        item["sha256"] = hashlib.sha256(
            (manifest_path.parent / item["path"]).read_bytes()
        ).hexdigest()
    manifest["membership_sha256"] = hashlib.sha256(
        json.dumps(
            manifest["membership"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    without_hash = {
        key: value for key, value in manifest.items() if key != "dataset_sha256"
    }
    manifest["dataset_sha256"] = hashlib.sha256(
        json.dumps(
            without_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


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


def _new_partial_fixture_response(payload: dict[str, object]) -> str:
    coverage = payload["coverage"]
    assert isinstance(coverage, dict)
    replacement = (
        f"Historical partial coverage: {coverage['complete_pair_count']} of "
        f"{coverage['eligible_date_count']} eligible dates; partial sample at "
        f"{coverage['coverage_percent']}% coverage."
    )
    return _partial_fixture_response(payload).replace(
        "Historical partial coverage: 51 of 60 eligible dates; partial sample at "
        "85.0% coverage.",
        replacement,
    )


def test_corpus_counts_and_loader_source_of_truth() -> None:
    corpus = validate(MANIFEST)
    assert len(corpus.legacy_rows) == 9
    assert len(corpus.annual_rows) == 10
    assert len(corpus.rows) == 19
    assert len(load_cases()) == 250
    assert len(golden_corpus.load_rows(MANIFEST)) == 19
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


def test_new_v2_partial_annual_grader_uses_bound_typed_coverage() -> None:
    corpus = validate(V2_FINAL_MANIFEST)
    row = next(
        row
        for row in corpus.rows
        if row["id"] == "topology-proof-dulles-toll-road-to-i495-annual"
    )
    fixture = corpus.fixtures["september-five-proof-dulles-toll-road-to-i495-annual"]
    payload = fixture["result"]
    assert isinstance(payload, dict)
    call = {
        "name": "get_annual_toll_ballpark",
        "input": row["script"][0]["request"],
        "tool_result": payload,
        "is_error": False,
    }
    turns = [
        {
            "response": _new_partial_fixture_response(payload),
            "calls": [call],
        }
    ]
    assert evaluate_v2_scripted_turns(turns, row)[0].test_pass

    equivalent_format = json.loads(json.dumps(turns))
    equivalent_format[0]["response"] = equivalent_format[0]["response"].replace(
        "95.0%", "95%"
    )
    assert evaluate_v2_scripted_turns(equivalent_format, row)[0].test_pass

    stale = json.loads(json.dumps(turns))
    stale[0]["response"] = stale[0]["response"].replace("57 of 60", "58 of 60")
    stale[0]["response"] = stale[0]["response"].replace("95.0%", "96.7%")
    assert evaluate_v2_scripted_turns(stale, row)[0].label == "partial_coverage"

    malformed_payload = json.loads(json.dumps(payload))
    malformed_payload["coverage"]["coverage_percent"] = "96.7"
    bad_payload = json.loads(json.dumps(turns))
    bad_payload[0]["calls"][0]["tool_result"] = malformed_payload
    assert evaluate_v2_scripted_turns(bad_payload, row)[0].label == "partial_coverage"


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


def test_v2_sample_preserves_membership_order_and_payload_free_render(
    tmp_path: Path,
) -> None:
    corpus = validate(V2_MANIFEST)
    assert [row["id"] for row in corpus.rows] == [
        "reagan-airport-to-westpark",
        "leesburg-route-28-annual-affordability",
        "v2-annual-mixed-tool-multiturn",
        "v2-current-no-call",
    ]
    assert [row["suite"] for row in corpus.rows] == [
        "current",
        "annual",
        "annual",
        "current",
    ]
    assert len(corpus.legacy_rows) == 2
    assert len(corpus.annual_rows) == 2
    assert corpus.rows[0]["script"][0]["tool"] == "get_current_toll_price"
    assert [step["tool"] for step in corpus.rows[2]["script"]] == [
        "get_current_toll_price",
        "get_annual_toll_ballpark",
    ]
    assert corpus.rows[3]["script"] == []
    output = render(V2_MANIFEST, tmp_path / "v2-review.html")
    page = output.read_text()
    assert page.count('class="case-card"') == 4
    assert "Dulles Greenway" in page
    assert "5.80" not in page
    assert "Unable to get the current toll price" not in page
    assert "Payloads withheld" not in page
    assert "data-case-id" not in page


def test_final_v2_renderer_supports_ordered_pilot_review_selection(
    tmp_path: Path,
) -> None:
    corpus = validate(V2_FINAL_MANIFEST)
    selection = _fixed_pilot_selection(corpus)
    cases = selection["cases"]
    assert isinstance(cases, list)
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection))
    selected_page = render(
        V2_FINAL_MANIFEST,
        tmp_path / "selected.html",
        selection_file=selection_path,
    ).read_text()
    default_page = render(V2_FINAL_MANIFEST, tmp_path / "default.html").read_text()

    assert selected_page.count('class="case-card"') == 30
    assert default_page.count('class="case-card"') == 250
    assert [
        html.unescape(value) for value in re.findall(r"<h2>(.*?)</h2>", selected_page)
    ] == [f"Case {index}" for index in range(1, 31)]
    for category in (
        "Road connections",
        "Current toll",
        "Yearly toll budget",
        "Follow-up questions",
        "Pricing failures",
        "Unsafe requests",
    ):
        assert selected_page.count(f'class="category">{category}</p>') == 5
    cursor = -1
    for case_id in cases:
        row = next(row for row in corpus.rows if row["id"] == case_id)
        for turn in row["conversation"]:
            position = selected_page.index(html.escape(turn), cursor + 1)
            assert position > cursor
            cursor = position
        assert row["id"] not in selected_page
    for page in (selected_page, default_page):
        assert "data-case-id" not in page
        assert "dataset_sha256" not in page
        assert "provenance" not in page
        assert "grouping" not in page
        assert "fixture" not in page.casefold()
        assert "directional" not in page.casefold()


def test_final_v2_renderer_rejects_invalid_selection_files(tmp_path: Path) -> None:
    corpus = validate(V2_FINAL_MANIFEST)
    selection = _fixed_pilot_selection(corpus)
    cases = selection["cases"]
    assert isinstance(cases, list)
    alternate = json.loads(json.dumps(selection))
    alternate_cases = []
    for category in ("topology", "current", "annual", "multiturn", "fault", "abuse"):
        category_cases = [
            row["id"] for row in corpus.rows if row["primary_category"] == category
        ]
        alternate_cases.extend(category_cases[:5])
    assert alternate_cases != cases
    alternate["cases"] = alternate_cases
    reordered = json.loads(json.dumps(selection))
    reordered["cases"] = [cases[1], cases[0], *cases[2:]]
    full_baseline = {
        "dataset_sha256": corpus.manifest["dataset_sha256"],
        "render_date": corpus.manifest["render_date"],
        "cases": [row["id"] for row in corpus.rows],
        "trials": ["1", "2", "3"],
    }
    mutations = [
        {**selection, "cases": cases[:-1]},
        {**selection, "cases": [cases[0], cases[0], *cases[2:]]},
        {**selection, "cases": ["unknown-case", *cases[1:]]},
        {**selection, "dataset_sha256": "0" * 64},
        {**selection, "render_date": "2026-09-06"},
        alternate,
        reordered,
        full_baseline,
    ]
    for index, value in enumerate(mutations):
        path = tmp_path / f"selection-{index}.json"
        path.write_text(json.dumps(value))
        with pytest.raises(CorpusError, match="selection file"):
            render(
                V2_FINAL_MANIFEST, tmp_path / f"out-{index}.html", selection_file=path
            )


def test_final_v2_manifest_has_250_cases_and_approved_allocation() -> None:
    corpus = validate(V2_FINAL_MANIFEST)
    assert len(corpus.rows) == 250
    assert Counter(row["primary_category"] for row in corpus.rows) == Counter(
        {
            "topology": 100,
            "current": 45,
            "annual": 35,
            "multiturn": 30,
            "fault": 20,
            "abuse": 20,
        }
    )
    assert corpus.manifest["allocation"] == {
        "topology": 100,
        "current": 45,
        "annual": 35,
        "multiturn": 30,
        "fault": 20,
        "abuse": 20,
        "total": 250,
    }
    assert sum(len(row["conversation"]) for row in corpus.rows) == 288
    assert (
        hashlib.sha256(
            json.dumps(
                [row["script"] for row in corpus.rows],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        == "a664a984346317f3bccb99bdcf23e308d2daff0c7d8142288fbe6655b841dfee"
    )
    tester_framing = re.compile(
        r"\b(?:tester|fixture|payload|canary|grounding)\b", re.I
    )
    for row in corpus.rows:
        conversation = " ".join(row["conversation"])
        assert row["id"] not in conversation
        assert not tester_framing.search(conversation)

    source = golden_corpus._validate_v1_manifest(MANIFEST)
    source_rows = {row["id"]: row for row in source.rows}
    effective_rows = {row["id"]: row for row in corpus.rows}
    captured_fields = {
        "suite",
        "annual_behavior",
        "expected_call",
        "expected_calls",
        "expected_clarification",
        "expected_missing_fields",
        "expected_route_status",
        "expected_component_count",
        "allow_pricing_unavailable",
        "expected_reasons",
        "expected_availability",
        "expected_required_i95_directions",
    }
    ignored_prose = {
        "prompt",
        "conversation",
        "follow_up",
        "expected_assertion",
        "provenance",
    }
    for case_id, source_row in source_rows.items():
        row = effective_rows[case_id]
        for field, expected in source_row.items():
            if field in ignored_prose:
                continue
            effective_field = f"source_{field}" if field in captured_fields else field
            assert row.get(effective_field) == expected, (case_id, effective_field)


def test_final_v2_allocation_mutation_is_rejected(tmp_path: Path) -> None:
    manifest_path, _ = _copy_final_v2_corpus(tmp_path / "allocation")
    manifest = json.loads(manifest_path.read_text())
    manifest["allocation"]["topology"] = 99
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CorpusError, match="allocation"):
        validate(manifest_path)


def test_final_v2_count_and_self_consistent_reclassification_are_rejected(
    tmp_path: Path,
) -> None:
    def mutate_count(root: Path, target_count: int) -> Path:
        manifest_path, corpus_root = _copy_final_v2_corpus(root)
        manifest = json.loads(manifest_path.read_text())
        shard_path = corpus_root / "cases/v2-public.jsonl"
        rows = [json.loads(line) for line in shard_path.read_text().splitlines()]
        removable_id = "current-boundary-three-axle"
        if target_count == 249:
            manifest["membership"] = [
                item for item in manifest["membership"] if item["id"] != removable_id
            ]
            manifest["case_metadata"] = [
                item for item in manifest["case_metadata"] if item["id"] != removable_id
            ]
        else:
            original = next(row for row in rows if row["id"] == removable_id)
            extra = json.loads(json.dumps(original))
            extra["id"] = "allocation-overflow-case"
            extra["prompt"] += " State the supported endpoint boundary explicitly."
            extra["conversation"] = [extra["prompt"]]
            rows.append(extra)
            shard_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
            )
            metadata = next(
                item for item in manifest["case_metadata"] if item["id"] == removable_id
            )
            extra_metadata = json.loads(json.dumps(metadata))
            extra_metadata["id"] = extra["id"]
            manifest["case_metadata"].append(extra_metadata)
            manifest["case_shards"][0]["count"] += 1
            manifest["membership"].append(
                {
                    "id": extra["id"],
                    "shard": "cases/v2-public.jsonl",
                    "row_sha256": hashlib.sha256(
                        json.dumps(
                            extra,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode()
                    ).hexdigest(),
                }
            )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
        _refresh_v2(manifest_path)
        return manifest_path

    for target_count in (249, 251):
        with pytest.raises(CorpusError, match="allocation"):
            validate(mutate_count(tmp_path / str(target_count), target_count))

    manifest_path, _ = _copy_final_v2_corpus(tmp_path / "reclassified")
    manifest = json.loads(manifest_path.read_text())
    row = next(
        item
        for item in manifest["case_metadata"]
        if item["id"] == "current-boundary-three-axle"
    )
    row["primary_category"] = "topology"
    manifest["allocation"] = {
        "topology": 101,
        "current": 44,
        "annual": 35,
        "multiturn": 30,
        "fault": 20,
        "abuse": 20,
        "total": 250,
    }
    manifest["direction_coverage"]["sampled_rows"] = 101
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match="approved release"):
        validate(manifest_path)


def test_final_v2_rejects_normalized_duplicate_case_content(tmp_path: Path) -> None:
    manifest_path, corpus_root = _copy_final_v2_corpus(tmp_path / "content-duplicate")
    manifest = json.loads(manifest_path.read_text())
    shard_path = corpus_root / "cases/v2-public.jsonl"
    rows = [json.loads(line) for line in shard_path.read_text().splitlines()]
    source = next(row for row in rows if row["id"] == "current-boundary-three-axle")
    duplicate = json.loads(json.dumps(source))
    duplicate["id"] = "normalized-content-duplicate"
    duplicate["prompt"] = (
        "  \n"
        + source["prompt"].upper().replace("WHAT", "\uff37\uff28\uff21\uff34")
        + "\t"
    )
    duplicate["conversation"] = [duplicate["prompt"]]
    rows.append(duplicate)
    shard_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    )
    metadata = next(
        item for item in manifest["case_metadata"] if item["id"] == source["id"]
    )
    duplicate_metadata = json.loads(json.dumps(metadata))
    duplicate_metadata["id"] = duplicate["id"]
    manifest["case_metadata"].append(duplicate_metadata)
    manifest["case_shards"][0]["count"] += 1
    manifest["membership"].append(
        {
            "id": duplicate["id"],
            "shard": "cases/v2-public.jsonl",
            "row_sha256": hashlib.sha256(
                json.dumps(
                    duplicate,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest(),
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match="duplicate case content"):
        validate(manifest_path)


def test_private_v2_rejects_normalized_canonical_identity_overlap(
    tmp_path: Path,
) -> None:
    public = validate(V2_FINAL_MANIFEST)
    public_row = next(row for row in public.rows if not row.get("script"))
    row = {
        "id": "private-normalized-identity",
        "prompt": "Please provide a supported toll origin and destination.",
        "conversation": ["Please provide a supported toll origin and destination."],
        "script": [],
    }
    root = tmp_path / "canonical"
    (root / "cases").mkdir(parents=True)
    shard = root / "cases/private.jsonl"
    shard.write_text(json.dumps(row) + "\n")
    membership = [
        {
            "id": row["id"],
            "shard": "cases/private.jsonl",
            "row_sha256": hashlib.sha256(
                json.dumps(
                    row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest(),
        }
    ]
    metadata = {
        "id": row["id"],
        "suite": "current",
        "primary_category": "topology",
        "tags": ["synthetic", "private"],
        "grouping": "private-normalized-identity",
        "provenance": "synthetic-private-test",
        "expected_assertion": (
            "Required: request supported endpoints. "
            "Prohibited: infer a route or make a tool call."
        ),
        "split": "private",
        "scenario_key": "  " + public_row["scenario_key"].upper() + "  ",
        "template_key": "  " + public_row["template_key"].upper() + "  ",
        "route_key": public_row["route_key"],
    }
    manifest: dict[str, object] = {
        "corpus": "annual-affordability",
        "format_version": "2.0.0",
        "dataset_version": "2.1.0",
        "source_manifests": [],
        "membership": membership,
        "membership_sha256": hashlib.sha256(
            json.dumps(
                membership, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest(),
        "case_metadata": [metadata],
        "case_shards": [{"path": "cases/private.jsonl", "count": 1}],
        "fixtures": [],
        "payloads": [
            {
                "path": "cases/private.jsonl",
                "sha256": hashlib.sha256(shard.read_bytes()).hexdigest(),
            }
        ],
        "public_dataset_sha256": public.manifest["dataset_sha256"],
        "public_membership_sha256": public.manifest["membership_sha256"],
        "allocation": {
            "topology": 1,
            "current": 0,
            "annual": 0,
            "multiturn": 0,
            "fault": 0,
            "abuse": 0,
            "total": 1,
        },
        "render_date": "2026-09-05",
        "direction_coverage": {
            "inventory_rows": 1,
            "sampled_rows": 1,
            "gaps": ["synthetic private identity test"],
        },
        "dataset_sha256": "",
    }
    manifest["dataset_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "dataset_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    path = root / "private-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(CorpusError, match="canonical identity overlaps"):
        validate_private_manifest(path, public)


def test_private_v2_rejects_normalized_content_overlap(tmp_path: Path) -> None:
    public = validate(V2_FINAL_MANIFEST)
    public_row = next(row for row in public.rows if not row.get("script"))
    private_path = _write_synthetic_private_manifest(
        tmp_path / "content-overlap", public, "private-normalized-content"
    )
    manifest = json.loads(private_path.read_text())
    shard_path = private_path.parent / "cases/private.jsonl"
    row = json.loads(shard_path.read_text())
    row["prompt"] = (
        "  \n"
        + public_row["prompt"].upper().replace("WHAT", "\uff37\uff28\uff21\uff34")
        + "\t"
    )
    row["conversation"] = [row["prompt"]]
    shard_path.write_text(json.dumps(row, ensure_ascii=False) + "\n")
    manifest["membership"][0]["row_sha256"] = hashlib.sha256(
        json.dumps(
            row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    private_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
    _refresh_v2(private_path)
    with pytest.raises(CorpusError, match="content overlaps public corpus"):
        validate_private_manifest(private_path, public)


def test_v2_release_base_ref_rejects_version_only_bump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    manifest_path, _ = _copy_final_v2_corpus(tmp_path / "version-only")
    monkeypatch.setattr(golden_corpus, "_REPO_ROOT", tmp_path / "version-only")

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=tmp_path / "version-only",
            check=True,
            capture_output=True,
        )

    git("init")
    git("add", ".")
    git(
        "-c",
        "user.name=Corpus test",
        "-c",
        "user.email=corpus@example.invalid",
        "commit",
        "-m",
        "Initial release",
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["dataset_version"] = "2.3.0"
    manifest_path.write_text(json.dumps(manifest))
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match="unchanged v2 corpus"):
        validate(manifest_path, "HEAD")

    manifest = json.loads(manifest_path.read_text())
    manifest["dataset_version"] = "2.2.0"
    manifest["direction_coverage"]["gaps"].append("Additional reviewed coverage limit.")
    manifest_path.write_text(json.dumps(manifest))
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match="advanced dataset_version"):
        validate(manifest_path, "HEAD")
    manifest["dataset_version"] = "2.3.0"
    manifest_path.write_text(json.dumps(manifest))
    _refresh_v2(manifest_path)
    assert validate(manifest_path, "HEAD").manifest["dataset_version"] == "2.3.0"


@pytest.mark.parametrize("mutation", ["duplicate", "nonfinite", "path", "membership"])
def test_v2_strict_manifest_mutations_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    manifest_path, _ = _copy_v2_corpus(tmp_path / mutation)
    raw = manifest_path.read_text()
    if mutation == "duplicate":
        raw = raw.replace(
            '"corpus": "annual-affordability",',
            '"corpus": "annual-affordability", "corpus": "annual-affordability",',
            1,
        )
    else:
        manifest = json.loads(raw)
        if mutation == "nonfinite":
            raw = raw.replace(
                f'"dataset_sha256": "{manifest["dataset_sha256"]}"',
                '"dataset_sha256": NaN',
                1,
            )
        elif mutation == "path":
            manifest["payloads"][0]["path"] = "../escape.jsonl"
            raw = json.dumps(manifest)
        else:
            manifest["membership"].pop()
            raw = json.dumps(manifest)
    manifest_path.write_text(raw)
    with pytest.raises(CorpusError):
        validate(manifest_path)


@pytest.mark.parametrize("mutation", ["script", "typed-result", "tool-version"])
def test_v2_script_and_typed_fixture_mutations_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    manifest_path, corpus_root = _copy_v2_corpus(tmp_path / mutation)
    if mutation == "script":
        case_path = corpus_root / "cases/v2-sample.jsonl"
        rows = [json.loads(line) for line in case_path.read_text().splitlines()]
        rows[0]["script"][1:] = rows[0]["script"][::-1]
        case_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    elif mutation == "typed-result":
        fixture_path = corpus_root / "fixtures/current-success.json"
        fixture = json.loads(fixture_path.read_text())
        fixture["result"]["total_usd"] = "not-money"
        fixture_path.write_text(json.dumps(fixture))
    else:
        fixture_path = corpus_root / "fixtures/current-success.json"
        fixture = json.loads(fixture_path.read_text())
        fixture["tool_contract_version"] = "3.0.0"
        fixture_path.write_text(json.dumps(fixture))
    with pytest.raises(CorpusError):
        validate(manifest_path)


def test_v2_membership_must_name_the_shard_that_owns_the_row(
    tmp_path: Path,
) -> None:
    manifest_path, corpus_root = _copy_v2_corpus(tmp_path / "shard-owner")
    rows = [
        json.loads(line)
        for line in (corpus_root / "cases/v2-sample.jsonl").read_text().splitlines()
    ]
    (corpus_root / "cases/v2-sample.jsonl").write_text(json.dumps(rows[1]) + "\n")
    (corpus_root / "cases/v2-other.jsonl").write_text(json.dumps(rows[0]) + "\n")
    manifest = json.loads(manifest_path.read_text())
    manifest["case_shards"] = [
        {"path": "cases/v2-other.jsonl", "count": 1},
        {"path": "cases/v2-sample.jsonl", "count": 1},
    ]
    manifest["payloads"].append({"path": "cases/v2-other.jsonl", "sha256": ""})
    manifest["payloads"].sort(key=lambda item: item["path"])
    manifest["membership"][2]["shard"] = "cases/v2-sample.jsonl"
    manifest_path.write_text(json.dumps(manifest))
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match="does not own"):
        validate(manifest_path)


@pytest.mark.parametrize(
    "mutation", ["fixture-request", "result-time", "script-request"]
)
def test_v2_requests_and_typed_results_are_bound(tmp_path: Path, mutation: str) -> None:
    manifest_path, corpus_root = _copy_v2_corpus(tmp_path / mutation)
    fixture_path = corpus_root / "fixtures/current-success.json"
    fixture = json.loads(fixture_path.read_text())
    if mutation == "fixture-request":
        fixture["request"]["destination_point_id"] = "greenway:99:exit:EB"
        fixture_path.write_text(json.dumps(fixture))
    elif mutation == "result-time":
        fixture["evaluated_at"] = "2026-08-17T07:30:00-04:00"
        fixture_path.write_text(json.dumps(fixture))
    else:
        case_path = corpus_root / "cases/v2-sample.jsonl"
        rows = [json.loads(line) for line in case_path.read_text().splitlines()]
        rows[0]["script"][0]["request"]["destination_point_id"] = "greenway:99:exit:EB"
        case_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        manifest = json.loads(manifest_path.read_text())
        target = next(
            item
            for item in manifest["membership"]
            if item.get("id") == "v2-annual-mixed-tool-multiturn"
        )
        target["row_sha256"] = hashlib.sha256(
            json.dumps(
                rows[0], sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match=r"(route|evaluated_at|request)"):
        validate(manifest_path)


def test_v2_fixture_evidence_rejects_post_validation_mutation(tmp_path: Path) -> None:
    manifest_path, corpus_root = _copy_v2_corpus(tmp_path / "evidence-mutation")
    corpus = validate(manifest_path)
    fixture_path = corpus_root / "fixtures/current-success.json"
    fixture_path.write_bytes(fixture_path.read_bytes() + b" ")

    with pytest.raises(CorpusError, match="bytes changed after validation"):
        corpus.fixture_evidence("current-success")


def test_v2_assembled_rows_require_explicit_scripts(tmp_path: Path) -> None:
    manifest_path, _ = _copy_v2_corpus(tmp_path / "mandatory-script")
    manifest = json.loads(manifest_path.read_text())
    source_metadata = next(
        item
        for item in manifest["case_metadata"]
        if item["id"] == "reagan-airport-to-westpark"
    )
    del source_metadata["script"]
    manifest_path.write_text(json.dumps(manifest))
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match="requires an ordered script"):
        validate(manifest_path)


def test_v2_strict_float_parser_rejects_exponent_overflow() -> None:
    with pytest.raises(CorpusError, match="non-finite"):
        golden_corpus._strict_loads('{"n":1e9999}', "overflow probe")


def test_v2_current_binding_accepts_all_typed_adapter_variants() -> None:
    request = {
        "origin_point_id": "greenway:1:entry:EB",
        "destination_point_id": "greenway:28:exit:EB",
        "pricing_profile": {
            "vehicle_class": "two_axle_passenger",
            "payment_method": "e_zpass",
            "transponder_mode": "toll",
        },
    }
    route = {
        "origin_point_id": request["origin_point_id"],
        "destination_point_id": request["destination_point_id"],
    }
    unsupported = pricing_domain._PricingUnavailableResponse(
        **route,
        error="pricing_unavailable",
        reason="unsupported_pricing_profile",
    ).model_dump(mode="json")
    incomplete = pricing_domain._IncompleteRoutePriceResponse(
        **route,
        error="pricing_unavailable",
        reason="incomplete_route_price",
        unavailable_components=[
            pricing_domain._UnavailableComponent(
                route_step_id="step-1",
                reason="stale_observation",
                component_evaluated_at=datetime.fromisoformat(
                    "2026-08-17T06:30:00-04:00"
                ),
                interval_end_at=None,
                observed_at=None,
            )
        ],
    ).model_dump(mode="json")
    route_status = pricing_domain._NonValidRouteResponse.model_validate(
        {
            "status": "no_supported_route",
            "reason": {"code": "no_supported_route", "details": route},
            "point_ids": [],
            "connection_ids": [],
            "connection_types": [],
            "general_purpose_gaps": [],
            "i95_evidence": None,
        }
    ).model_dump(mode="json")
    for label, result in (
        ("unsupported", unsupported),
        ("incomplete", incomplete),
        ("route-status", route_status),
    ):
        pricing_domain._OUTPUT_ADAPTER.validate_json(json.dumps(result))
        golden_corpus._v2_fixture_result_binding(
            {
                "evaluated_at": "2026-08-17T06:30:00-04:00",
                "result": result,
            },
            request,
            "get_current_toll_price",
            label,
        )


def test_v2_source_manifest_version_is_bound_before_v1_validation(
    tmp_path: Path,
) -> None:
    manifest_path, corpus_root = _copy_v2_corpus(tmp_path / "source-version")
    source_path = corpus_root / "source.json"
    source = json.loads((corpus_root / "manifest.json").read_text())
    source["dataset_version"] = "2.0.0"
    source_without_hash = {
        key: value for key, value in source.items() if key != "dataset_sha256"
    }
    source_hash = hashlib.sha256(
        json.dumps(
            source_without_hash,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    source["dataset_sha256"] = source_hash
    source_path.write_text(json.dumps(source, indent=2) + "\n")

    manifest = json.loads(manifest_path.read_text())
    manifest["source_manifests"][0]["path"] = "source.json"
    manifest["source_manifests"][0]["dataset_sha256"] = source_hash
    for item in manifest["membership"]:
        if "source_manifest" in item:
            item["source_manifest"] = "source.json"
            item["source_dataset_sha256"] = source_hash
    for item in manifest["fixtures"]:
        if "source_manifest" in item:
            item["source_manifest"] = "source.json"
    manifest_path.write_text(json.dumps(manifest))
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError, match="version disagrees"):
        validate(manifest_path)


@pytest.mark.parametrize("mutation", ["capture-source", "naive-time", "secret-text"])
def test_v2_fixture_evidence_is_timestamped_and_sanitized(
    tmp_path: Path, mutation: str
) -> None:
    manifest_path, corpus_root = _copy_v2_corpus(tmp_path / mutation)
    fixture_path = corpus_root / "fixtures/current-success.json"
    fixture = json.loads(fixture_path.read_text())
    if mutation == "capture-source":
        fixture["evidence_type"] = "retained_production_capture"
    elif mutation == "naive-time":
        fixture["evaluated_at"] = "2026-08-17T06:30:00"
    else:
        fixture["provenance"] = "secret=EXFILTRATE https://internal.invalid"
    fixture_path.write_text(json.dumps(fixture))
    _refresh_v2(manifest_path)
    with pytest.raises(CorpusError):
        validate(manifest_path)


def _write_synthetic_private_manifest(
    root: Path, public: golden_corpus.Corpus, case_id: str
) -> Path:
    cases = root / "cases"
    cases.mkdir(parents=True)
    row = {
        "id": case_id,
        "prompt": "Please provide a supported toll origin and destination.",
        "conversation": ["Please provide a supported toll origin and destination."],
        "script": [],
    }
    shard = cases / "private.jsonl"
    shard.write_text(json.dumps(row) + "\n")
    membership = [
        {
            "id": case_id,
            "shard": "cases/private.jsonl",
            "row_sha256": hashlib.sha256(
                json.dumps(
                    row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest(),
        }
    ]
    manifest = {
        "corpus": "annual-affordability",
        "format_version": "2.0.0",
        "dataset_version": "2.0.0",
        "source_manifests": [],
        "membership": membership,
        "membership_sha256": hashlib.sha256(
            json.dumps(
                membership, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest(),
        "case_metadata": [
            {
                "id": case_id,
                "suite": "current",
                "primary_category": "current",
                "tags": ["synthetic", "private"],
                "grouping": "synthetic-private",
                "provenance": "synthetic-private-test",
                "expected_assertion": "Required: request supported endpoints. Prohibited: infer a route or make a tool call.",
            }
        ],
        "case_shards": [{"path": "cases/private.jsonl", "count": 1}],
        "fixtures": [],
        "payloads": [
            {
                "path": "cases/private.jsonl",
                "sha256": hashlib.sha256(shard.read_bytes()).hexdigest(),
            }
        ],
        "public_dataset_sha256": public.manifest["dataset_sha256"],
        "public_membership_sha256": public.manifest["membership_sha256"],
        "dataset_sha256": "",
    }
    manifest["dataset_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "dataset_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    path = root / "private-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def test_private_v2_validator_uses_supplied_public_identity_and_rejects_overlap(
    tmp_path: Path,
) -> None:
    public = validate(V2_MANIFEST)
    private_path = _write_synthetic_private_manifest(
        tmp_path / "private", public, "private-synthetic-case"
    )
    private = validate_private_manifest(private_path, public)
    assert [row["id"] for row in private.rows] == ["private-synthetic-case"]

    manifest = json.loads(private_path.read_text())
    row_path = private_path.parent / "cases/private.jsonl"
    row = json.loads(row_path.read_text())
    row["id"] = "reagan-airport-to-westpark"
    row_path.write_text(json.dumps(row) + "\n")
    manifest["membership"][0]["id"] = row["id"]
    manifest["membership"][0]["row_sha256"] = hashlib.sha256(
        json.dumps(
            row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    manifest["membership_sha256"] = hashlib.sha256(
        json.dumps(
            manifest["membership"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    manifest["payloads"][0]["sha256"] = hashlib.sha256(
        row_path.read_bytes()
    ).hexdigest()
    manifest["dataset_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "dataset_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    private_path.write_text(json.dumps(manifest))
    with pytest.raises(CorpusError, match="overlaps public"):
        validate_private_manifest(private_path, public)

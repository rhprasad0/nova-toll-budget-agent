"""Synthetic local authoring checks; these inputs never become a real eval set."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from eval import corpus as f
from eval import golden, golden_actor_check
from eval import golden_run as run
from tests.golden_support import ROOT as TEST_DATA


def inputs(root: Path) -> Path:
    """Clearly synthetic no-tool cases exercise all allocations and lifecycle gates."""
    drafts = root / "drafts"
    for split, allocation in f.CONTRACT["splits"].items():
        directory = drafts / split
        (directory / "fixtures").mkdir(parents=True)
        shutil.copyfile(
            TEST_DATA / "prompt-points.json", directory / "prompt-points.json"
        )
        cases: list[dict[str, Any]] = []
        examples: list[dict[str, Any]] = []
        for family, count in allocation["coverage"].items():
            kind = family.split("_")[0]
            for _ in range(count):
                number = len(cases) + 1
                case_id = f"smoke-{split}-{number:03d}"
                prompt = f"Synthetic {split} scenario {number}: please price an unsupported trip to Testtown."
                case: dict[str, Any] = {
                    "number": number,
                    "id": case_id,
                    "title": "Synthetic corpus regression",
                    "kind": kind,
                    "contract_version": 2,
                    "coverage_family": family,
                    "split_group": case_id,
                    "terminal_objective": "refusal",
                    "minimum_user_turns": 1,
                    "prompt": prompt,
                    "actor": {
                        "facts": "You drive a passenger car with E-ZPass in toll mode. Testtown is your only destination.",
                        "goal": "Learn that this synthetic destination is unsupported.",
                        "follow_up_rules": [],
                        "max_turns": 5,
                    },
                    "frozen_time": "2026-10-01T08:00:00-04:00",
                    "provenance": {
                        "kind": "synthetic",
                        "source": "offline regression",
                        "note": "Lifecycle check only; never an evaluation corpus.",
                    },
                    "coverage_tags": [family],
                    "critical": False,
                    "held_out": split == "holdout",
                    "max_tool_calls": 0,
                    "steps": [],
                    "expected_assertion": "Explain that Testtown is unsupported without inventing a price.",
                }
                cases.append(case)
                example: dict[str, Any] = {
                    "case_id": case_id,
                    "label": "good",
                    "expected_failures": [],
                    "expected": dict.fromkeys(("outcome", "grounding", "rules"), True),
                    "actor_validity": "valid",
                    "rationale": "Synthetic unsupported destination refusal.",
                    "turns": [
                        {
                            "user": prompt,
                            "response": "That destination is outside the supported catalog; I cannot price this trip.",
                            "calls": [],
                        }
                    ],
                }
                examples.append(example)
                if split == "training" and number > allocation["count"] - 20:
                    bad = json.loads(json.dumps(example))
                    bad.update(
                        label="invented-price",
                        expected_failures=["unsupported_money"],
                        expected=dict.fromkeys(
                            ("outcome", "grounding", "rules"), False
                        ),
                    )
                    bad["turns"][0]["response"] = "Your unsupported trip costs $123.45."
                    examples.append(bad)
        (directory / "cases.jsonl").write_text(
            "".join(json.dumps(c) + "\n" for c in cases)
        )
        (directory / "examples.json").write_text(json.dumps(examples))
    return drafts


@pytest.fixture
def drafts(tmp_path: Path) -> Path:
    return inputs(tmp_path)


@pytest.mark.parametrize(
    ("point", "canonical"),
    [
        ("greenway:7:entry:EB", "greenway:7"),
        ("greenway:7:exit:WB", "greenway:7"),
        ("dtr:1819:exit:WB", "dtr:1819"),
        ("i495:1819ND", "i495:181"),
        ("i495:180SO", "i495:181"),
        ("i495:182SD", "i495:182"),
        ("i495:184SD", "i495:183"),
        ("i95:211NO", "i95:211ND"),
        ("i95:211SD", "i95:211ND"),
        ("i95:219NO", "i95:219NO"),
        ("i95:220SD", "i95:219NO"),
        ("i95:226SD", "i95:2229ND"),
        ("i95:235SD", "i95:234NO"),
        ("i95:22329ND", "i95:22329ND"),
        ("airport_iad", "airport_iad"),
    ],
)
def test_canonical_catalog_access(point: str, canonical: str) -> None:
    assert f.canonical_access(point) == canonical


def add_route_case(
    drafts: Path,
    split: str,
    legs: list[tuple[str, str]],
    *,
    kind: str = "current",
    number: int | None = None,
) -> None:
    """Independently authored receipts in an allocated synthetic smoke case."""
    directory = drafts / split
    cases_path = directory / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()]
    case = next(
        c
        for c in cases
        if c["kind"] == kind
        and (split != "training" or c["number"] <= len(cases) - 20)
        and (number is None or c["number"] == number)
    )
    case["max_tool_calls"] = 1
    name = case["id"] + ".json"
    case["steps"] = [{"fixture": name, "min_turn": 1, "required_user_patterns": []}]
    time = (
        "2026-10-01T08:00:00-04:00"
        if split == "training"
        else "2026-10-02T08:00:00-04:00"
    )
    case["frozen_time"] = time
    labels = {
        p.point_id: p.label
        for p in f.parse_prompt_points(
            json.loads((directory / "prompt-points.json").read_text())
        )
    }
    origin, destination = legs[0]
    case["prompt"] = (
        f"Please check {labels[origin]} to {labels[destination]} for my synthetic {split} trip {case['number']}."
    )
    case["actor"]["facts"] = (
        "You drive a two-axle passenger car with E-ZPass in toll mode. The supplied endpoints are intentional."
    )
    case["actor"]["goal"] = (
        "Get the requested estimate, or learn why pricing is unavailable."
    )
    provenance = {
        "kind": "synthetic",
        "source": "route guard regression",
        "note": "No packet or benchmark case used.",
    }
    arguments: dict[str, Any]
    if kind == "annual":
        case["prompt"] += (
            f" Return from {labels[legs[1][0]]} to {labels[legs[1][1]]}; Mondays, leaving at 7 AM and returning at 5 PM, 40 annual days, gross salary $90,000."
        )
        arguments = {
            role: {
                "origin_point_id": origin,
                "destination_point_id": destination,
                "departure_time": departure,
            }
            for role, (origin, destination), departure in zip(
                ("outbound", "return"), legs, ("07:00:00", "17:00:00"), strict=True
            )
        }
        arguments.update(
            weekdays=["monday"],
            planned_annual_commute_days=40,
            gross_annual_income_usd="90000.00",
        )
        tool = "get_annual_toll_ballpark"
        error_text = (
            f"Unable to calculate the annual toll ballpark. Reference: {case['id']}."
        )
    else:
        origin, destination = legs[0]
        arguments = {
            "origin_point_id": origin,
            "destination_point_id": destination,
            "pricing_profile": {
                "vehicle_class": "two_axle_passenger",
                "payment_method": "e_zpass",
                "transponder_mode": "toll",
            },
        }
        tool = "get_current_toll_price"
        error_text = f"Unable to get the current toll price. Reference: {case['id']}."
    fixture: dict[str, Any] = {
        "tool": tool,
        "input": arguments,
        "result": {
            "toolUseId": case["id"],
            "status": "error",
            "content": [{"text": error_text}],
        },
        "is_error": True,
        "provenance": provenance,
    }
    response = "Pricing failed, so I cannot give an estimate."
    if kind == "current" and legs[0][0].startswith("i66:"):
        price = "3.00" if split == "training" else "4.00"
        fixture["is_error"] = False
        fixture["result"] = {
            **arguments,
            "method": "latest_complete_current_facility_prices",
            "evaluated_at": time,
            "maximum_observation_age_minutes": 30,
            "source_kind": "observed",
            "total_usd": price,
            "components": [
                {
                    "route_step_id": "step-1",
                    "price_usd": price,
                    "source_kind": "observed",
                    "pricing_method": "source_observation",
                    "facility": "i66",
                    "component_evaluated_at": time,
                    "bin_minutes": 6,
                    "bin_start": time,
                    "bin_end": time.replace("08:00:00", "08:06:00"),
                    "interval_end_at": time,
                    "observed_at": time,
                }
            ],
        }
        response = f"The current toll is ${price}, using a recent I-66 observation."
    (directory / "fixtures" / name).write_text(json.dumps(fixture))
    case["terminal_objective"] = "unavailable" if fixture["is_error"] else "answer"
    case["expected_assertion"] = response
    cases_path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    examples_path = directory / "examples.json"
    examples = json.loads(examples_path.read_text())
    example = next(e for e in examples if e["case_id"] == case["id"])
    example["turns"] = [
        {
            "user": case["prompt"],
            "response": response,
            "calls": [
                {
                    "name": tool,
                    **{k: fixture[k] for k in ("input", "result", "is_error")},
                }
            ],
        }
    ]
    examples_path.write_text(json.dumps(examples))


@pytest.mark.parametrize("split", ["holdout", "shadow"])
@pytest.mark.parametrize(
    ("kind", "training", "holdout"),
    [
        (
            "current",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
        ),
        (
            "current",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [("greenway:28:entry:WB", "greenway:7:exit:WB")],
        ),
        ("current", [("i495:182NO", "i495:181ND")], [("i495:180SO", "i495:182SD")]),
        ("current", [("i495:182NO", "i495:181ND")], [("i495:182NO", "i495:1819ND")]),
        ("current", [("i495:183NO", "i495:181ND")], [("i495:180SO", "i495:184SD")]),
        ("current", [("i95:219NO", "i495:181ND")], [("i495:180SO", "i95:220SD")]),
        ("current", [("i95:222NO", "i495:181ND")], [("i495:180SO", "i95:226SD")]),
        ("current", [("i95:234NO", "i495:181ND")], [("i495:180SO", "i95:235SD")]),
        ("current", [("i95:211NO", "i495:182ND")], [("i495:182SO", "i95:211SD")]),
        (
            "current",
            [("i66:4:entry:EB", "i66:12:exit:EB")],
            [("i66:12:entry:WB", "i66:4:exit:WB")],
        ),
        (
            "annual",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [
                ("greenway:7:entry:EB", "greenway:28:exit:EB"),
                ("dtr:17:entry:WB", "dtr:12:exit:WB"),
            ],
        ),
        (
            "annual",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [
                ("dtr:12:entry:EB", "dtr:17:exit:EB"),
                ("greenway:28:entry:WB", "greenway:7:exit:WB"),
            ],
        ),
    ],
)
def test_route_reuse_across_splits_ignores_evidence_and_groups(
    drafts: Path,
    split: str,
    kind: str,
    training: list[tuple[str, str]],
    holdout: list[tuple[str, str]],
) -> None:
    add_route_case(drafts, "training", training)
    add_route_case(drafts, split, holdout, kind=kind)
    # Each split passes the full offline receipt/reference checks independently.
    for selected in ("training", split):
        golden.validate_payload(
            golden.load_cases(drafts / selected),
            drafts / selected,
            {
                p.point_id
                for p in f.parse_prompt_points(
                    json.loads((drafts / selected / "prompt-points.json").read_text())
                )
            },
            complete=False,
        )
    with pytest.raises(ValueError, match="canonical route pair crosses splits"):
        f.validate_splits({s: drafts / s for s in f.SPLITS})


@pytest.mark.parametrize("split", ["holdout", "shadow"])
@pytest.mark.parametrize(
    "distinct",
    [
        [("greenway:6:entry:EB", "greenway:28:exit:EB")],
        [("dtr:12:entry:EB", "dtr:17:exit:EB")],
    ],
)
def test_distinct_routes_and_within_split_reuse_are_valid(
    drafts: Path,
    split: str,
    distinct: list[tuple[str, str]],
) -> None:
    route = [("greenway:7:entry:EB", "greenway:28:exit:EB")]
    add_route_case(drafts, "training", route, number=1)
    add_route_case(drafts, "training", route, number=2)
    add_route_case(drafts, split, distinct)
    assert set(f.validate_splits({s: drafts / s for s in f.SPLITS})) == set(f.SPLITS)


@pytest.mark.parametrize(
    ("north", "south"),
    [("209NO", "209SO"), ("217NO", "217SD"), ("218NO", "218SD"), ("216SD", "236SO")],
)
def test_distinct_i95_accesses_with_shared_stems_or_labels_remain_valid(
    drafts: Path,
    north: str,
    south: str,
) -> None:
    add_route_case(drafts, "training", [(f"i95:{north}", "i95:222ND")])
    add_route_case(drafts, "holdout", [(f"i95:{south}", "i95:2229ND")])
    assert f.canonical_access(f"i95:{north}") != f.canonical_access(f"i95:{south}")
    assert set(f.validate_splits({s: drafts / s for s in f.SPLITS})) == set(f.SPLITS)


@pytest.mark.parametrize(
    "change",
    ["allocation", "group", "duplicate", "actor", "time", "reference", "turns"],
)
def test_invalid_drafts_are_rejected(drafts: Path, change: str) -> None:
    path = drafts / "holdout/cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "allocation":
        cases[0]["kind"] = "annual"
    elif change == "group":
        cases[0]["split_group"] = "smoke-training-001"
    elif change == "duplicate":
        cases[0]["prompt"] = cases[1]["prompt"]
    elif change == "actor":
        cases[0]["actor"]["facts"] += " Use get_current_toll_price."
    elif change == "time":
        cases[0]["frozen_time"] = "2026-10-01T08:00:00"
    elif change == "turns":
        cases[0]["actor"]["max_turns"] = 4
    else:
        refs = drafts / "holdout/examples.json"
        refs.write_text(json.dumps(json.loads(refs.read_text())[1:]))
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    with pytest.raises(ValueError):
        f.validate_splits({s: drafts / s for s in f.SPLITS})


def test_freeze_binds_review_and_invalidates_changes(drafts: Path) -> None:
    root = drafts / "training"
    original = f.freeze(root, "training", "5.0.0")
    review_path = root / "review.json"
    review = json.loads(review_path.read_text())
    assert review["status"] == "pending"
    review.update(
        status="approved", reviewer="Test only", evidence="Synthetic offline check"
    )
    review_path.write_text(json.dumps(review))
    assert f.validate(root) == original
    assert f.freeze(root, "training", "5.0.0") == original
    assert json.loads(review_path.read_text()) == review
    path = root / "cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    cases[0]["title"] += " revised"
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    with pytest.raises(ValueError, match="changed"):
        f.validate(root)
    with pytest.raises(ValueError, match="newer corpus version"):
        f.freeze(root, "training", "5.0.0")
    changed = f.freeze(root, "training", "5.0.1")
    assert changed["corpus_sha256"] != original["corpus_sha256"]
    assert json.loads(review_path.read_text())["status"] == "pending"
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="exact corpus"):
        f.validate(root)


def test_inputs_and_protected_sources_cannot_drift(
    drafts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = drafts / "training"
    f.freeze(root, "training", "5.0.0")
    hashes = golden.source_hashes()
    monkeypatch.setattr(
        golden, "source_hashes", lambda: {**hashes, "v2/eval/golden.py": "0" * 64}
    )
    with pytest.raises(ValueError, match="protected sources changed"):
        f.validate(root)
    (root / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="unexpected suite input"):
        f.validate_splits({"training": root})


def test_holdout_path_and_symlink_boundaries(drafts: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        f.require_external(golden.V2.parent / "holdout")
    link = tmp_path / "repository-link"
    link.symlink_to(golden.V2.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="outside the repository"):
        f.require_external(link / "hidden")
    root = drafts / "holdout"
    f.freeze(root, "holdout", "5.0.0")
    target = root / "examples.json"
    saved = tmp_path / "references.json"
    target.rename(saved)
    target.symlink_to(saved)
    with pytest.raises(ValueError, match="regular files"):
        f.validate(root)


@pytest.fixture
def hidden_identity(drafts: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = drafts / "holdout"
    f.freeze(root, "holdout", "5.0.0")
    monkeypatch.setattr(golden, "ROOT", root)
    original_git = run.git

    def clean_git(*args: str) -> str:
        return "" if args[0] == "status" else original_git(*args)

    monkeypatch.setattr(run, "git", clean_git)
    return run.identity(golden.load_cases())


def test_holdout_calibration_and_actor_check_use_selected_references(
    hidden_identity: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases = golden.load_cases()
    refs = run.development_examples()
    assert {r.case_id for r in refs} == {c.id for c in cases}
    assert all(c.held_out for c in cases)
    assert hidden_identity["calibration_labels"]["example_ids"] == [
        f"{r.case_id}-{r.label}" for r in refs
    ]
    original_root = golden.ROOT
    monkeypatch.setattr(golden, "ROOT", f.PUBLIC / "training")
    output = tmp_path / "actor-check"

    def check(example: golden.Example, trial: int, journal: run.Journal) -> run.Attempt:
        print(example.case_id)
        journal.append({"event": "synthetic-check"})
        return run.Attempt(
            id=example.case_id, case_id=example.case_id, trial=trial, status="scored"
        )

    mock_check = Mock(side_effect=check)
    monkeypatch.setattr(golden_actor_check, "check", mock_check)
    monkeypatch.setattr(
        "sys.argv",
        [
            "actor-check",
            "--corpus",
            str(original_root),
            "--output",
            str(output),
            "--budget-usd",
            "1",
        ],
    )
    golden_actor_check.main()
    feedback = json.loads(capsys.readouterr().out)
    assert feedback["valid_trials"] == feedback["expected_trials"] == 25
    assert mock_check.call_count == 25
    assert golden.ROOT == f.PUBLIC / "training"
    assert cases[0].id in (output.parent / ".actor-check.console.log").read_text()


def test_holdout_calibration_cli_includes_all_references(
    hidden_identity: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = golden.ROOT
    expected = {e.case_id for e in run.development_examples()}

    def judge(
        case: golden.GoldenCase,
        attempt: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool,
    ) -> None:
        assert case.id in expected and fixed_reference
        attempt.actor_validity = run.ActorAssessment(
            status="valid", evidence="SECRET_ACTOR"
        )
        attempt.measurements = [
            run.Measurement(
                role="judge",
                input_tokens=1,
                output_tokens=1,
                cached_tokens=0,
                written_tokens=0,
                seconds=0.1,
                cost_usd=0.01,
                complete=True,
            )
        ]
        attempt.verdicts = {
            k: run.Verdict(passed=True, evidence="SECRET_GRADE")
            for k in ("outcome", "grounding", "rules")
        }

    mock_judge = Mock(side_effect=judge)
    monkeypatch.setattr(run, "judge", mock_judge)
    monkeypatch.setattr(golden, "ROOT", f.PUBLIC / "training")
    output = tmp_path / "calibration"
    monkeypatch.setattr(
        "sys.argv",
        [
            "calibrate",
            "calibrate",
            "--corpus",
            str(root),
            "--output",
            str(output),
            "--budget-usd",
            "1",
        ],
    )
    run.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "mode": "calibrate",
        "complete": True,
        "expected_examples": 25,
        "measurement_failures": 0,
        "disagreements": 0,
    }
    assert captured.err == "" and "SECRET" not in captured.out
    assert mock_judge.call_count == 25
    assert golden.ROOT == f.PUBLIC / "training"


def test_holdout_run_rejects_partial_selection_before_paid_work(
    hidden_identity: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = golden.ROOT
    review_path = root / "review.json"
    review = json.loads(review_path.read_text())
    review.update(
        status="approved", reviewer="Test only", evidence="Offline regression"
    )
    review_path.write_text(json.dumps(review))
    output = tmp_path / "partial"
    credentials = Mock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", credentials)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run",
            "run",
            "--corpus",
            str(root),
            "--output",
            str(output),
            "--cases",
            golden.load_cases()[0].id,
        ],
    )
    with pytest.raises(SystemExit, match="host-side diagnostic log"):
        run.main()
    assert not output.exists()
    credentials.assert_not_called()
    captured = capsys.readouterr()
    assert "smoke-holdout" not in captured.out + captured.err


def test_one_reviewed_harness_calibration_serves_all_splits_and_new_inputs(
    drafts: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for split in f.SPLITS:
        f.freeze(drafts / split, split, "5.0.0")
        review_path = drafts / split / "review.json"
        review = json.loads(review_path.read_text())
        review.update(status="approved", reviewer="Test", evidence="Offline only")
        review_path.write_text(json.dumps(review))
    original_git = run.git

    def clean_git(*args: str) -> str:
        return "" if args[0] == "status" else original_git(*args)

    monkeypatch.setattr(run, "git", clean_git)
    original_root = golden.ROOT
    calibration = tmp_path / "suite-calibration"
    seen: list[str] = []

    def judge(
        case: golden.GoldenCase,
        attempt: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool,
    ) -> None:
        assert case in golden.load_cases() and fixed_reference
        seen.append(case.id)
        attempt.actor_validity = run.ActorAssessment(status="valid", evidence="SECRET")
        attempt.measurements = [
            run.Measurement(
                role="judge",
                input_tokens=1,
                output_tokens=1,
                cached_tokens=0,
                written_tokens=0,
                seconds=0.1,
                cost_usd=0,
                complete=True,
            )
        ]
        attempt.verdicts = {
            key: run.Verdict(passed=True, evidence="SECRET")
            for key in ("outcome", "grounding", "rules")
        }

    monkeypatch.setattr(run, "judge", judge)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "calibrate",
            "--corpus",
            str(drafts / "training"),
            "--shadow",
            str(drafts / "shadow"),
            "--holdout",
            str(drafts / "holdout"),
            "--output",
            str(calibration),
        ],
    )
    run.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out)["expected_examples"] == 105
    assert "SECRET" not in captured.out + captured.err
    assert len(seen) == 105 and len(set(seen)) == 85
    assert original_root == golden.ROOT
    report = run.render(calibration)
    assert report["complete"] and report["review"]["status"] == "pending"
    monkeypatch.setattr(sys, "argv", ["runner", "render", "--output", str(calibration)])
    run.main()
    rendered = capsys.readouterr()
    assert json.loads(rendered.out)["mode"] == "calibrate"
    assert "SECRET" not in rendered.out + rendered.err
    receipt_path = tmp_path / "harness-approval.json"
    with pytest.raises(ValueError, match="approved all-split"):
        run.export_calibration_receipt(calibration, receipt_path)
    assert not receipt_path.exists()
    (calibration / "review.json").write_text(
        json.dumps(
            {
                "status": "approved",
                "reviewer": "Test",
                "evidence": "Offline only",
                "evidence_sha256": report["evidence_sha256"],
            }
        )
    )
    shared = report["manifest"]["identity"]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "export-calibration",
            "--output",
            str(calibration),
            "--receipt",
            str(receipt_path),
        ],
    )
    run.main()
    assert json.loads(capsys.readouterr().out)["mode"] == "export-calibration"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["contract_sha256"] == run.calibration_contract(shared)
    assert "smoke-holdout" not in receipt_path.read_text()
    assert "SECRET" not in receipt_path.read_text()
    monkeypatch.setattr(f, "PUBLIC", drafts)
    changed_receipt = {**receipt, "contract_sha256": "f" * 64}
    changed_receipt["receipt_sha256"] = golden.digest(
        {k: v for k, v in changed_receipt.items() if k != "receipt_sha256"}
    )
    receipt_path.write_text(json.dumps(changed_receipt))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "run",
            "--corpus",
            str(drafts / "shadow"),
            "--calibration",
            str(receipt_path),
            "--output",
            str(tmp_path / "run-tampered"),
        ],
    )
    with pytest.raises(SystemExit, match="host-side diagnostic log"):
        run.main()
    assert (
        "new harness calibration required"
        in (tmp_path / ".run-tampered.console.log").read_text()
    )
    receipt_path.write_text(json.dumps(receipt))

    def execute(
        case: golden.GoldenCase, trial: int, journal: run.Journal
    ) -> run.Attempt:
        attempt = run.Attempt(
            id=f"{case.id}-{trial}",
            case_id=case.id,
            trial=trial,
            status="scored",
            turns=[
                golden.Turn(user=case.prompt, response="Unsupported trip", calls=[])
            ],
        )
        judge(case, attempt, journal, fixed_reference=True)
        journal.append({"event": "attempt_finished", **attempt.model_dump()})
        return attempt

    monkeypatch.setattr(run, "execute", execute)
    for split in f.SPLITS:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "runner",
                "run",
                "--corpus",
                str(drafts / split),
                "--calibration",
                str(receipt_path),
                "--output",
                str(tmp_path / f"run-{split}"),
                "--trials-per-case",
                "3" if split == "shadow" else "1",
            ],
        )
        run.main()
        result = run.render(tmp_path / f"run-{split}")
        assert (
            result["manifest"]["calibration"]["run_id"] == report["manifest"]["run_id"]
        )
        pinned = result["manifest"]["identity"]
        changed_inputs = deepcopy(pinned)
        changed_inputs["corpus"]["version"] = "5.1.0"
        changed_inputs["corpus"]["corpus_sha256"] = "0" * 64
        changed_inputs["calibration_labels"] = {"example_ids": ["new-reference"]}
        changed_inputs["commit"] = "f" * 40
        changed_inputs["prompt_hashes"] = {"new-case": "f" * 64}
        run.require_calibration(shared, changed_inputs)
        for key in run.CALIBRATION_KEYS:
            changed = {**pinned, key: "changed"}
            with pytest.raises(ValueError, match="new harness calibration"):
                run.require_calibration(shared, changed)
        with pytest.raises(ValueError, match="all-split"):
            run.require_calibration(pinned, pinned)
    assert run.render(tmp_path / "run-shadow")["overall"]["successful_trials"] == 30
    shadow_events = tmp_path / "run-shadow/events.jsonl"
    original_events = shadow_events.read_text()
    events = [json.loads(line) for line in original_events.splitlines()]
    events[0]["verdicts"]["outcome"]["passed"] = False
    shadow_events.write_text("".join(json.dumps(event) + "\n" for event in events))
    failed_trial = run.render(tmp_path / "run-shadow")["overall"]
    assert failed_trial["successful_trials"] == 29
    assert failed_trial["passing_all_three_cases"] == 9
    assert failed_trial["pass_cubed"] == 0.9
    events[0]["status"] = "infrastructure"
    shadow_events.write_text("".join(json.dumps(event) + "\n" for event in events))
    incomplete = run.render(tmp_path / "run-shadow")["overall"]
    assert incomplete["complete"] is False
    assert incomplete["scored_trials"] == 29
    assert incomplete["inconclusive_trials"] == 1
    assert incomplete["overall_pass_rate"] == 29 / 30
    assert incomplete["pass_cubed"] == 0.9
    shadow_events.write_text(original_events)
    assert original_root == golden.ROOT
    for split in f.SPLITS:
        incomplete = deepcopy(shared)
        del incomplete["calibration_splits"][split]
        with pytest.raises(ValueError, match="all three"):
            run.validate_identity(incomplete)
    incomplete = deepcopy(shared)
    incomplete["calibration_labels"]["example_ids"].pop()
    with pytest.raises(ValueError, match="calibration labels"):
        run.validate_identity(incomplete)


def test_default_readiness_checks_both_public_splits(
    drafts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(f, "PUBLIC", drafts)
    for split in ("training", "shadow"):
        f.freeze(drafts / split, split, "5.0.0")
    f.validate(drafts / "training")
    (drafts / "shadow/manifest.json").unlink()
    with pytest.raises(ValueError, match="No active golden corpus"):
        f.validate(drafts / "training")


def test_holdout_aggregate_is_allowlisted_and_keeps_console_private(
    hidden_identity: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    journal = run.Journal(tmp_path / "checkpoint", 1)
    manifest = {
        "run_id": "00000000-0000-4000-8000-000000000001",
        "mode": "run",
        "identity": hidden_identity,
    }
    (journal.directory / "manifest.json").write_text(json.dumps(manifest))
    cases = golden.load_cases()
    for n, case in enumerate(cases[:3]):
        row = run.Attempt(
            id=f"{case.id}-1",
            case_id=case.id,
            trial=1,
            status="inconclusive" if n == 2 else "scored",
            actor_validity=run.ActorAssessment(
                status="uncertain" if n == 2 else "valid", evidence="SECRET_ACTOR_FACTS"
            ),
            measurements=[
                run.Measurement(
                    role="judge",
                    input_tokens=1,
                    output_tokens=1,
                    cached_tokens=0,
                    written_tokens=0,
                    seconds=0.1,
                    cost_usd=0.01,
                    complete=True,
                )
            ],
            verdicts={
                k: run.Verdict(passed=n != 1, evidence="SECRET_REFERENCE")
                for k in ("outcome", "grounding", "rules")
            },
            turns=[golden.Turn(user=case.prompt, response="SECRET_ANSWER", calls=[])],
        )
        journal.append({"event": "attempt_finished", **row.model_dump()})
    # A copied or stale report cannot supply inflated aggregate scores.
    (journal.directory / "report.json").write_text(
        '{"overall":{"successful_trials":25}}'
    )
    original_render = run.render
    logger = logging.getLogger("holdout-console-regression")
    handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)

    def private_render(directory: Path) -> dict[str, Any]:
        print("SECRET_PROGRESS")
        print("SECRET_STDERR", file=sys.stderr)
        logger.warning("SECRET_LOGGING")
        return original_render(directory)

    monkeypatch.setattr(run, "render", private_render)
    monkeypatch.setattr(
        "sys.argv", ["aggregate", "aggregate", "--output", str(journal.directory)]
    )
    try:
        run.main()
    finally:
        logger.removeHandler(handler)
        handler.close()
    captured = capsys.readouterr()
    feedback = json.loads(captured.out)
    assert captured.err == ""
    assert feedback["expected_trials"] == 25
    assert (
        feedback["passed"],
        feedback["failed"],
        feedback["inconclusive"],
        feedback["missing"],
    ) == (1, 1, 1, 22)
    assert feedback["pass_rate"] == 1 / 25
    assert not feedback["complete"]
    assert feedback["cost_usd"] == pytest.approx(0.03)
    assert set(feedback) == {
        "format_version",
        "scope",
        "run_id",
        "source_commit",
        "artifact_sha256",
        "harness_version",
        "corpus_version",
        "corpus_sha256",
        "measurement_sha256",
        "evidence_sha256",
        "trials_per_case",
        "expected_trials",
        "passed",
        "failed",
        "inconclusive",
        "missing",
        "pass_rate",
        "complete",
        "cost_usd",
    }
    assert "SECRET" not in captured.out
    assert all(c.id not in captured.out for c in cases)
    log = tmp_path / ".checkpoint.console.log"
    assert "SECRET_PROGRESS" in log.read_text() and "SECRET_STDERR" in log.read_text()
    assert "SECRET_LOGGING" in log.read_text()
    journal.append(
        json.loads((journal.directory / "events.jsonl").read_text().splitlines()[0])
    )
    with pytest.raises(SystemExit, match="host-side diagnostic log"):
        run.main()
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err
    assert "duplicate finished attempt" in log.read_text()

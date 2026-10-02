"""Private suite lifecycle, blinded audits, reuse accounting, and comparisons."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
from collections import Counter
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent.toll_agent import parse_prompt_points
from eval import golden, golden_actor_check
from eval import golden_run as run
from eval.factory.kit import (
    CONTRACT,
    HERE,
    digest,
    evaluator_identity,
    read_snapshot,
    sha,
    write,
)
from scripts.release_statistics import case_results, compare

SPLITS = ("training", "holdout", "shadow")
DIMENSIONS = ("outcome", "grounding", "rules")


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def runtime() -> dict[str, Any]:
    return {
        "python": list(sys.version_info[:3]),
        "platform": platform.machine(),
        "installed_dependencies_sha256": digest(
            {str(d.metadata["Name"]).casefold(): d.version for d in distributions()}
        ),
    }


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}", value):
        raise ValueError("invalid identifier")
    return value


def version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value
    ):
        raise ValueError("suite/split versions start at 4.0.0")
    parsed = tuple(map(int, value.split(".")))
    if parsed < (4, 0, 0):
        raise ValueError("suite/split versions start at 4.0.0")
    return parsed


@contextmanager
def locked(root: Path) -> Generator[None]:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".factory.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def commit(root: Path, message: str) -> None:
    # Auth lives outside work. Never sweep unrelated files into private history.
    paths = (
        "AGENTS.md",
        ".gitignore",
        "ledger.jsonl",
        "drafts",
        "suites",
        "runs",
        "snapshots",
    )
    subprocess.run(
        ["git", "-C", str(root), "add", "--all", "--", *paths],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "--quiet", "--allow-empty", "-m", message],
        check=True,
    )


def init(root: Path) -> None:
    if (root / ".git").exists():
        raise ValueError("factory already initialized")
    for name in ("drafts", "suites", "runs", "snapshots"):
        (root / name).mkdir()
    (root / ".gitignore").write_text(".factory.lock\n*.tmp\n")
    shutil.copyfile(HERE / "AGENTS.md", root / "AGENTS.md")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    for key, value in (
        ("user.name", "Evaluation Factory"),
        ("user.email", "factory@localhost"),
        ("commit.gpgsign", "false"),
        ("core.hooksPath", "/dev/null"),
    ):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    append(root, "initialized", contract_sha256=digest(CONTRACT))
    commit(root, "Initialize private factory history")


def ledger(root: Path) -> list[dict[str, Any]]:
    path = root / "ledger.jsonl"
    data = path.read_bytes() if path.exists() else b""
    if (root / ".git").exists():
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--quiet", "--verify", "HEAD"],
            capture_output=True,
        )
        if head.returncode == 0:
            committed = subprocess.check_output(
                ["git", "-C", str(root), "show", "HEAD:ledger.jsonl"]
            )
            if not data.startswith(committed):
                raise ValueError("ledger history changed from committed checkpoint")
    events = [json.loads(line) for line in data.splitlines()]
    previous = "0" * 64
    for index, event in enumerate(events):
        body = {k: v for k, v in event.items() if k != "sha256"}
        if (
            event.get("sequence") != index
            or event.get("previous") != previous
            or event.get("sha256") != digest(body)
        ):
            raise ValueError("ledger history changed")
        previous = event["sha256"]
    return events


def append(root: Path, event: str, **payload: Any) -> dict[str, Any]:  # noqa: ANN401
    events = ledger(root)
    body = {
        "sequence": len(events),
        "previous": events[-1]["sha256"] if events else "0" * 64,
        "timestamp": timestamp(),
        "event": event,
        **payload,
    }
    body["sha256"] = digest(body)
    with (root / "ledger.jsonl").open("a") as stream:
        stream.write(json.dumps(body, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return body


def input_hashes(root: Path) -> dict[str, str]:
    allowed = {"cases.jsonl", "examples.json", "prompt-points.json"}
    files = [
        *sorted(root.glob("fixtures/*.json")),
        *(root / name for name in sorted(allowed)),
    ]
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("suite inputs must be regular files")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    if actual != {str(p.relative_to(root)) for p in files}:
        raise ValueError("unexpected suite input; use only the input allowlist")
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in files}


def validate_splits(source: Path) -> dict[str, dict[str, str]]:
    groups: dict[str, str] = {}
    evidence: dict[str, str] = {}
    prompts: set[str] = set()
    ids: set[str] = set()
    reference_ids: set[str] = set()
    total_negative = 0
    result: dict[str, dict[str, str]] = {}
    for split in SPLITS:
        directory = source / split
        result[split] = input_hashes(directory)
        cases = golden.load_cases(directory)
        allocation = CONTRACT["splits"][split]
        if (
            len(cases) != allocation["count"]
            or {c.number for c in cases} != set(range(1, len(cases) + 1))
            or Counter(c.kind for c in cases) != allocation["workflow"]
            or Counter(c.coverage_family for c in cases) != allocation["coverage"]
        ):
            raise ValueError(
                f"{split}: coverage, workflow, or numbering allocation mismatch"
            )
        points = parse_prompt_points(
            json.loads((directory / "prompt-points.json").read_text())
        )
        golden.validate_payload(
            cases, directory, {p.point_id for p in points}, complete=False
        )
        examples = [
            golden.Example.model_validate(e)
            for e in json.loads((directory / "examples.json").read_text())
        ]
        for example in examples:
            reference_id = f"{example.case_id}-{example.label}"
            if reference_id in reference_ids:
                raise ValueError("duplicate calibration reference identity")
            reference_ids.add(reference_id)
        good = {
            e.case_id
            for e in examples
            if e.expected
            and all(e.expected.model_dump().values())
            and e.actor_validity == "valid"
            and not e.expected_failures
        }
        if good != {c.id for c in cases}:
            raise ValueError("each case needs a complete passing reference")
        total_negative += sum(
            e.expected is not None and not all(e.expected.model_dump().values())
            for e in examples
        )
        pairs: dict[str, list[golden.GoldenCase]] = {}
        for case in cases:
            if (
                case.contract_version != 2
                or not case.split_group
                or case.held_out != (split == "holdout")
            ):
                raise ValueError(
                    "explicit v2 scenario group and correct held_out flag required"
                )
            if case.id in ids or groups.setdefault(case.split_group, split) != split:
                raise ValueError("duplicate case ID or scenario group crosses splits")
            ids.add(case.id)
            normalized = re.sub(r"\W+", " ", case.prompt.casefold()).strip()
            if normalized in prompts:
                raise ValueError("duplicate opening request")
            prompts.add(normalized)
            for tag in case.coverage_tags:
                if tag.startswith("pair:"):
                    pairs.setdefault(tag, []).append(case)
            for step in case.steps:
                fixture = golden.load_fixture(step.fixture, directory)
                key = digest(
                    {k: v for k, v in fixture.model_dump().items() if k != "provenance"}
                )
                if evidence.setdefault(key, split) != split:
                    raise ValueError("equivalent fixture evidence crosses splits")
        for members in pairs.values():
            types = {
                tag
                for c in members
                for tag in c.coverage_tags
                if tag.startswith("pair_type:")
            }
            if (
                len(members) != 2
                or len({c.split_group for c in members}) != 1
                or len(types) != 1
                or not types <= {"pair_type:contrastive", "pair_type:invariance"}
            ):
                raise ValueError(
                    "behavioral pair must have two members in one scenario group"
                )
    if total_negative < 20:
        raise ValueError("suite needs at least 20 labeled negative references")
    return result


def freeze(
    root: Path,
    source: Path,
    suite_version: str,
    split_versions: dict[str, str],
    *,
    smoke: bool = False,
) -> dict[str, Any]:
    version(suite_version)
    hashes = validate_splits(source)
    evaluator = evaluator_identity()
    manifests = [read(p / "manifest.json") for p in (root / "suites").iterdir()]
    if manifests:
        previous = max(manifests, key=lambda m: version(m["version"]))
        if version(suite_version) <= version(previous["version"]):
            raise ValueError("new suite requires a higher version")
    else:
        previous = None
        if suite_version != "4.0.0" or any(
            v != "4.0.0" for v in split_versions.values()
        ):
            raise ValueError("first suite and all splits start at 4.0.0")
    splits = {}
    for split in SPLITS:
        selected = split_versions[split]
        version(selected)
        inputs_digest = digest(hashes[split])
        if previous:
            old = previous["splits"][split]
            if (inputs_digest == old["sha256"] and selected != old["version"]) or (
                inputs_digest != old["sha256"]
                and version(selected) <= version(old["version"])
            ):
                raise ValueError(
                    "changed split needs a higher version; unchanged split retains its version"
                )
        splits[split] = {
            "version": selected,
            "sha256": inputs_digest,
            "files": hashes[split],
            **CONTRACT["splits"][split],
        }
    manifest = {
        "version": suite_version,
        "splits": splits,
        "evaluator": evaluator,
        "settings": CONTRACT["settings"],
        "runtime": runtime(),
        "synthetic_smoke": smoke,
    }
    manifest["suite_sha256"] = digest(manifest)
    directory = root / "suites" / suite_version
    directory.mkdir()
    for split in SPLITS:
        shutil.copytree(source / split, directory / split)
    write(directory / "manifest.json", manifest)
    append(
        root,
        "suite_frozen",
        suite_sha256=manifest["suite_sha256"],
        holdout_sha256=splits["holdout"]["sha256"],
        version=suite_version,
    )
    commit(root, f"Freeze suite {suite_version}")
    return manifest


def suite(root: Path, suite_version: str) -> tuple[Path, dict[str, Any]]:
    version(suite_version)
    directory = root / "suites" / suite_version
    manifest = read(directory / "manifest.json")
    if (
        manifest["suite_sha256"]
        != digest({k: v for k, v in manifest.items() if k != "suite_sha256"})
        or manifest["evaluator"] != evaluator_identity()
        or manifest["settings"] != CONTRACT["settings"]
        or manifest["runtime"] != runtime()
    ):
        raise ValueError(
            "frozen suite, evaluator, or runtime changed; new version and calibration required"
        )
    for split in SPLITS:
        actual = input_hashes(directory / split)
        if (
            actual != manifest["splits"][split]["files"]
            or digest(actual) != manifest["splits"][split]["sha256"]
        ):
            raise ValueError(
                "frozen inputs changed; new version and calibration required"
            )
    return directory, manifest


def paid_guard(
    manifest: dict[str, Any], mock: bool, budget: float | None, authorization: str
) -> None:
    if mock:
        if not manifest["synthetic_smoke"]:
            raise ValueError("mock measurements require a synthetic smoke suite")
    elif (
        manifest["synthetic_smoke"]
        or budget is None
        or not math.isfinite(budget)
        or budget <= 0
        or not authorization.strip()
    ):
        raise ValueError(
            "paid work requires a real suite, an explicitly authorized finite budget, and authorization evidence"
        )


@contextmanager
def corpus(directory: Path) -> Generator[None]:
    # One CLI operation owns ROOT until its worker pool finishes; no public defaults change.
    with patch.object(golden, "ROOT", directory):
        yield


@contextmanager
def workers(journal: run.Journal) -> Generator[ThreadPoolExecutor]:
    pool = ThreadPoolExecutor(max_workers=4)
    try:
        yield pool
    except BaseException:
        journal.stop_requested = True
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def mock_attempt(
    case: golden.GoldenCase,
    trial: int,
    example: golden.Example,
    *,
    fail: bool = False,
    inconclusive: bool = False,
) -> run.Attempt:
    return run.Attempt(
        id=f"{case.id}-{trial}",
        case_id=case.id,
        trial=trial,
        status="inconclusive" if inconclusive else "scored",
        turns=example.turns,
        verdicts={
            k: run.Verdict(
                passed=(not fail or k != "outcome"),
                evidence="Synthetic credential-free provider",
            )
            for k in DIMENSIONS
        },
        actor_validity=run.ActorAssessment(
            status="uncertain" if inconclusive else "valid", evidence="Synthetic actor"
        ),
        measurements=[
            run.Measurement(
                role=role,
                input_tokens=0,
                output_tokens=0,
                cached_tokens=0,
                written_tokens=0,
                seconds=0,
                cost_usd=0,
                complete=True,
            )
            for role in ("agent", "actor", "judge")
        ],
    )


def calibrate(
    root: Path,
    suite_version: str,
    *,
    mock: bool = False,
    budget: float | None = None,
    authorization: str = "",
) -> dict[str, Any]:
    directory, manifest = suite(root, suite_version)
    paid_guard(manifest, mock, budget, authorization)
    output = directory / "calibration"
    journal = run.Journal(output, budget if not mock else 1)
    append(
        root,
        "calibration_started",
        suite_sha256=manifest["suite_sha256"],
        authorization=authorization,
        budget_usd=budget,
        synthetic_smoke=mock,
    )
    rows: list[dict[str, Any]] = []
    actors: list[dict[str, Any]] = []
    error = None
    try:
        key = os.environ["OPENAI_API_KEY"] if not mock else "synthetic-no-credential"
        with patch.object(run.toll_agent, "load_openai_api_key", lambda: key):
            for split in SPLITS:
                with corpus(directory / split), workers(journal) as pool:
                    examples = [
                        golden.Example.model_validate(e)
                        for e in json.loads(
                            (directory / split / "examples.json").read_text()
                        )
                    ]
                    cases = {c.id: c for c in golden.load_cases()}
                    if mock:
                        for e in examples:
                            row = mock_attempt(cases[e.case_id], 1, e).model_dump(
                                mode="json"
                            )
                            row.update(
                                id=f"{e.case_id}-{e.label}",
                                example=e.label,
                                expected=e.expected.model_dump()
                                if e.expected
                                else None,
                                measurement_complete=True,
                                disagreements=[],
                                expected_actor_validity=e.actor_validity,
                            )
                            row["verdicts"] = {
                                k: {"passed": v, "evidence": "Synthetic authored label"}
                                for k, v in (
                                    row["expected"] or dict.fromkeys(DIMENSIONS, False)
                                ).items()
                            }
                            row["actor_validity"]["status"] = e.actor_validity
                            rows.append(row)
                    else:
                        rows.extend(run.calibrate(journal, pool, examples))
                    good: dict[str, golden.Example] = {}
                    for e in examples:
                        if (
                            e.expected
                            and all(e.expected.model_dump().values())
                            and e.actor_validity == "valid"
                        ):
                            good.setdefault(e.case_id, e)
                    if mock:
                        actors.extend(
                            mock_attempt(cases[cid], 1, e).model_dump(mode="json")
                            for cid, e in good.items()
                        )
                    else:

                        def check_actor(example: golden.Example) -> run.Attempt:
                            return golden_actor_check.check(example, 1, journal)

                        actors.extend(
                            a.model_dump(mode="json")
                            for a in pool.map(
                                check_actor,
                                good.values(),
                            )
                        )
    except BaseException as exc:
        journal.stop_requested = True
        error = type(exc).__name__
        raise
    finally:
        expected = {
            (e["case_id"], e["label"])
            for split in SPLITS
            for e in json.loads((directory / split / "examples.json").read_text())
        }
        observed = [(r["case_id"], r["example"]) for r in rows]
        complete = (
            len(observed) == len(set(observed))
            and set(observed) == expected
            and all(r["measurement_complete"] for r in rows)
            and len(actors) == 160
            and len({r["case_id"] for r in actors}) == 160
            and all(
                r["status"] in {"scored", "inconclusive"}
                and r["measurements"]
                and all(m["complete"] for m in r["measurements"])
                for r in actors
            )
            and not journal.unknown_usage
        )
        report: dict[str, Any] = {
            "suite_sha256": manifest["suite_sha256"],
            "rows": rows,
            "actor_check": actors,
            "complete": complete,
            "cost_usd": journal.spent,
            "unknown_usage": journal.unknown_usage,
            "synthetic_smoke": mock,
            "error": error,
            "events_sha256": sha((output / "events.jsonl").read_bytes()),
        }
        report["evidence_sha256"] = digest(report)
        write(output / "report.json", report)
        append(
            root,
            "calibration_finished",
            suite_sha256=manifest["suite_sha256"],
            evidence_sha256=report["evidence_sha256"],
            complete=complete,
            cost_usd=journal.spent,
            unknown_usage=journal.unknown_usage,
        )
        commit(root, f"Record calibration {suite_version}")
    return report


def checked_report(path: Path) -> dict[str, Any]:
    report = read(path)
    if report.get("evidence_sha256") != digest(
        {k: v for k, v in report.items() if k != "evidence_sha256"}
    ):
        raise ValueError("report evidence changed")
    return report


def dispositions(expected: set[tuple[str, str]], items: list[dict[str, Any]]) -> bool:
    observed = [(i["id"], i["dimension"]) for i in items]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError("every disagreement needs exactly one disposition")
    for item in items:
        if (
            type(item["material"]) is not bool
            or item["disposition"]
            not in {"accepted_limitation", "grading_defect", "actor_defect"}
            or not item["evidence"].strip()
        ):
            raise ValueError("invalid disagreement disposition")
    return not any(
        i["material"] and i["disposition"] != "accepted_limitation" for i in items
    )


def review_calibration(root: Path, suite_version: str, review: dict[str, Any]) -> None:
    directory, _ = suite(root, suite_version)
    report = checked_report(directory / "calibration/report.json")
    expected = {
        (r["id"], dimension) for r in report["rows"] for dimension in r["disagreements"]
    }
    expected |= {
        (r["id"], "actor_validity")
        for r in report["actor_check"]
        if r["status"] != "scored"
    }
    if (
        review["evidence_sha256"] != report["evidence_sha256"]
        or not review["reviewer"].strip()
        or not review["evidence"].strip()
        or not report["complete"]
    ):
        raise ValueError(
            "calibration approval requires complete, bound evidence and a reviewer"
        )
    approved = dispositions(expected, review["dispositions"])
    write(
        directory / "calibration/review.json",
        {
            **review,
            "status": "approved" if approved else "blocked",
            "reviewed_at": timestamp(),
        },
    )
    append(
        root,
        "calibration_reviewed",
        suite_sha256=report["suite_sha256"],
        evidence_sha256=report["evidence_sha256"],
        approved=approved,
        reviewer=review["reviewer"],
        review_sha256=digest(read(directory / "calibration/review.json")),
    )
    commit(root, f"Review calibration {suite_version}")


def measurement(root: Path, suite_version: str) -> tuple[Path, dict[str, Any]]:
    directory, manifest = suite(root, suite_version)
    report = checked_report(directory / "calibration/report.json")
    review = read(directory / "calibration/review.json")
    if (
        not report["complete"]
        or review["status"] != "approved"
        or review["evidence_sha256"] != report["evidence_sha256"]
        or sha((directory / "calibration/events.jsonl").read_bytes())
        != report["events_sha256"]
        or report["suite_sha256"] != manifest["suite_sha256"]
        or not any(
            e["event"] == "calibration_finished"
            and e.get("evidence_sha256") == report["evidence_sha256"]
            and e.get("suite_sha256") == manifest["suite_sha256"]
            for e in ledger(root)
        )
        or not any(
            e["event"] == "calibration_reviewed"
            and e.get("review_sha256") == digest(review)
            and e.get("evidence_sha256") == report["evidence_sha256"]
            and e.get("approved")
            for e in ledger(root)
        )
    ):
        raise ValueError("calibration is incomplete, changed, or awaits approval")
    identity = {
        "suite_sha256": manifest["suite_sha256"],
        "holdout_sha256": manifest["splits"]["holdout"]["sha256"],
        "evaluator_sha256": manifest["evaluator"]["sha256"],
        "dependency_sha256": manifest["evaluator"]["files"]["uv.lock"],
        "calibration_sha256": report["evidence_sha256"],
        "calibration_review_sha256": digest(review),
        "settings": manifest["settings"],
        "runtime": manifest["runtime"],
        "synthetic_smoke": manifest["synthetic_smoke"],
    }
    identity["comparison_sha256"] = digest(identity)
    return directory, identity


def import_source(root: Path, path: Path) -> str:
    identity, files = read_snapshot(path)
    if (
        identity["files"]["uv.lock"] != evaluator_identity()["files"]["uv.lock"]
        or identity["files"]["pyproject.toml"]
        != evaluator_identity()["files"]["pyproject.toml"]
    ):
        raise ValueError("source dependencies differ from the frozen factory lock")
    source_id = identity["source_sha256"]
    directory = root / "snapshots" / source_id
    if not directory.exists():
        directory.mkdir()
        for name, blob in files.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        write(directory / "snapshot.json", identity)
        commit(root, f"Import source {source_id[:12]}")
    return source_id


def source(root: Path, source_id: str) -> tuple[Path, dict[str, Any]]:
    identifier(source_id)
    directory = root / "snapshots" / source_id
    identity = read(directory / "snapshot.json")
    if (
        source_id != identity["source_sha256"]
        or source_id
        != digest({k: v for k, v in identity.items() if k != "source_sha256"})
        or any(
            (directory / name).is_symlink()
            or sha((directory / name).read_bytes()) != hashed
            for name, hashed in identity["files"].items()
        )
    ):
        raise ValueError("source snapshot changed")
    return directory, identity


def approve_reuse(
    root: Path, suite_version: str, source_id: str, reviewer: str, evidence: str
) -> dict[str, Any]:
    _, identity = measurement(root, suite_version)
    source(root, source_id)
    if not reviewer.strip() or not evidence.strip():
        raise ValueError("reuse requires reviewer and evidence")
    result = append(
        root,
        "reuse_approved",
        holdout_sha256=identity["holdout_sha256"],
        source_sha256=source_id,
        reviewer=reviewer,
        evidence=evidence,
    )
    commit(root, "Approve next holdout use against current ledger")
    return result


def reuse_status(root: Path, holdout_digest: str) -> dict[str, Any]:
    events = [e for e in ledger(root) if e.get("holdout_sha256") == holdout_digest]
    return {
        "attempts": sum(e["event"] == "application_started" for e in events),
        "disclosures": sum(e["event"] == "feedback_disclosed" for e in events),
        "approvals": sum(e["event"] == "reuse_approved" for e in events),
    }


def summarize(
    cases: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(cases) != 50 or len({c["id"] for c in cases}) != 50:
        raise ValueError("holdout requires exactly 50 unique cases")
    expected = {(c["id"], trial) for c in cases for trial in (1, 2, 3)}
    observed = [(r["case_id"], r["trial"]) for r in rows]
    if len(observed) != len(set(observed)) or set(observed) - expected:
        raise ValueError("duplicate or unexpected measurement slot")
    successful = Counter(r["case_id"] for r in rows if r["overall_success"])
    histogram = Counter(successful[c["id"]] for c in cases)
    complete = set(observed) == expected and all(
        r["measurement_complete"] for r in rows
    )
    return {
        "successful_trials": sum(successful.values()),
        "expected_trials": 150,
        "successful_trial_rate": sum(successful.values()) / 150,
        "cases_passing_all_three": histogram[3],
        "expected_cases": 50,
        "case_success_histogram": [histogram[n] for n in range(4)],
        "inconclusive_trials": sum(r["status"] == "inconclusive" for r in rows),
        "missing_trials": len(expected - set(observed)),
        "complete": complete,
    }


def application_row(attempt: run.Attempt) -> dict[str, Any]:
    row = attempt.model_dump(mode="json")
    measured = (
        bool(attempt.measurements)
        and all(m.complete and math.isfinite(m.cost_usd) for m in attempt.measurements)
        and attempt.status in {"scored", "inconclusive"}
        and attempt.actor_validity is not None
    )
    if attempt.status == "scored":
        measured &= (
            set(attempt.verdicts) == set(DIMENSIONS)
            and attempt.actor_validity is not None
            and attempt.actor_validity.status == "valid"
        )
    else:
        measured &= (
            attempt.actor_validity is not None
            and attempt.actor_validity.status != "valid"
        )
    row.update(
        measurement_complete=measured, overall_success=attempt.passed and measured
    )
    return row


def evaluate(
    root: Path,
    suite_version: str,
    source_id: str,
    role: str,
    *,
    mock: bool = False,
    budget: float | None = None,
    authorization: str = "",
) -> str:
    directory, identity = measurement(root, suite_version)
    _, manifest = suite(root, suite_version)
    paid_guard(manifest, mock, budget, authorization)
    bundle, snapshot = source(root, source_id)
    events = ledger(root)
    if role not in {"candidate", "incumbent"}:
        raise ValueError("invalid application role")
    if role == "incumbent" and any(
        e["event"] == "application_started"
        and e.get("role") == role
        and e.get("comparison_sha256") == identity["comparison_sha256"]
        for e in events
    ):
        raise ValueError(
            "incumbent already attempted for this frozen comparison contract; reuse its audited report"
        )
    reuse = reuse_status(root, identity["holdout_sha256"])
    if reuse["attempts"]:
        last = events[-1]
        if (
            last["event"] != "reuse_approved"
            or last.get("holdout_sha256") != identity["holdout_sha256"]
            or last.get("source_sha256") != source_id
        ):
            raise ValueError(
                "holdout reuse requires a fresh approval for this source and current ledger"
            )
    run_id = uuid.uuid4().hex
    output = root / "runs" / run_id
    journal = run.Journal(output, budget if not mock else 1)
    append(
        root,
        "application_started",
        run_id=run_id,
        role=role,
        source_sha256=source_id,
        suite_sha256=identity["suite_sha256"],
        holdout_sha256=identity["holdout_sha256"],
        calibration_sha256=identity["calibration_sha256"],
        comparison_sha256=identity["comparison_sha256"],
        authorization=authorization,
        budget_usd=budget,
        reuse_approval_sha256=events[-1]["sha256"] if reuse["attempts"] else None,
    )
    commit(root, f"Start {role} attempt {run_id}")
    cases = golden.load_cases(directory / "holdout")
    rows: list[dict[str, Any]] = []
    error = None
    try:
        if mock:
            examples = {
                e.case_id: e
                for e in (
                    golden.Example.model_validate(e)
                    for e in json.loads(
                        (directory / "holdout/examples.json").read_text()
                    )
                )
                if e.expected and all(e.expected.model_dump().values())
            }
            rows = [
                application_row(
                    mock_attempt(
                        c,
                        t,
                        examples[c.id],
                        fail=(c.number + t + (role == "candidate")) % 7 == 0,
                        inconclusive=c.number == 1 and t == 3,
                    )
                )
                for c in cases
                for t in (1, 2, 3)
            ]
        else:
            from eval.factory.source_agent import SourceAgent

            key = os.environ["OPENAI_API_KEY"]
            with (
                patch.object(run.toll_agent, "load_openai_api_key", lambda: key),
                corpus(directory / "holdout"),
                workers(journal) as pool,
            ):

                def agent_factory(
                    case: golden.GoldenCase,
                    attempt: run.Attempt,
                    j: run.Journal,
                    messages: list[str],
                ) -> SourceAgent:
                    return SourceAgent(bundle, key, case, attempt, j, messages)

                def execute(slot: tuple[golden.GoldenCase, int]) -> run.Attempt:
                    return run.execute(slot[0], slot[1], journal, agent_factory)

                rows = [
                    application_row(a)
                    for a in pool.map(
                        execute, ((c, t) for c in cases for t in (1, 2, 3))
                    )
                ]
    except BaseException as exc:
        journal.stop_requested = True
        error = type(exc).__name__
        raise
    finally:
        if not rows:
            events_path = output / "events.jsonl"
            finished = [
                json.loads(line)
                for line in events_path.read_text().splitlines()
                if json.loads(line)["event"] == "attempt_finished"
            ]
            rows = [
                application_row(
                    run.Attempt.model_validate(
                        {k: v for k, v in e.items() if k != "event"}
                    )
                )
                for e in finished
            ]
        cases_json = [c.model_dump(mode="json") for c in cases]
        report: dict[str, Any] = {
            "run_id": run_id,
            "role": role,
            "source": snapshot,
            "measurement": identity,
            "suite_version": suite_version,
            "manifest": {"identity": {"cases": cases_json}},
            "attempts": rows,
            "overall": summarize(cases_json, rows),
            "cost_usd": journal.spent,
            "unknown_usage": journal.unknown_usage,
            "events_sha256": sha((output / "events.jsonl").read_bytes()),
            "error": error,
        }
        report["evidence_sha256"] = digest(report)
        write(output / "report.json", report)
        append(
            root,
            "application_finished",
            run_id=run_id,
            source_sha256=source_id,
            suite_sha256=identity["suite_sha256"],
            holdout_sha256=identity["holdout_sha256"],
            calibration_sha256=identity["calibration_sha256"],
            evidence_sha256=report["evidence_sha256"],
            complete=report["overall"]["complete"],
            cost_usd=journal.spent,
            unknown_usage=journal.unknown_usage,
        )
        commit(root, f"Finish {role} attempt {run_id}")
    return run_id


def application(root: Path, run_id: str) -> tuple[Path, dict[str, Any]]:
    directory = root / "runs" / identifier(run_id)
    report = checked_report(directory / "report.json")
    if report["events_sha256"] != sha((directory / "events.jsonl").read_bytes()):
        raise ValueError("original run events changed")
    cases = report["manifest"]["identity"]["cases"]
    rows: list[dict[str, Any]] = []
    for row in report["attempts"]:
        parsed = run.Attempt.model_validate(
            {k: v for k, v in row.items() if k in run.Attempt.model_fields}
        )
        checked = application_row(parsed)
        if row != checked:
            raise ValueError(
                "recorded success or measurement completeness disagrees with evidence"
            )
        rows.append(checked)
    if summarize(cases, rows) != report["overall"]:
        raise ValueError("aggregate score disagrees with original slots")
    if not any(
        e["event"] == "application_finished"
        and e.get("run_id") == run_id
        and e.get("evidence_sha256") == report["evidence_sha256"]
        for e in ledger(root)
    ):
        raise ValueError("original report differs from the append-only ledger")
    return directory, report


def audit_selection(report: dict[str, Any]) -> list[dict[str, Any]]:
    cases = {c["id"]: c for c in report["manifest"]["identity"]["cases"]}
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    first: set[tuple[str, bool]] = set()
    for row in sorted(report["attempts"], key=lambda r: (r["case_id"], r["trial"])):
        key = (row["case_id"], row["trial"])
        family = cases[row["case_id"]]["coverage_family"]
        category = (family, row["overall_success"])
        if row["status"] == "inconclusive" or (
            row["actor_validity"] is not None
            and row["actor_validity"]["status"] != "valid"
        ):
            selected[key] = row
        if (
            row["status"] == "scored"
            and row["measurement_complete"]
            and category not in first
        ):
            selected[key] = row
            first.add(category)
    return [selected[key] for key in sorted(selected)]


def audit(root: Path, run_id: str) -> dict[str, Any]:
    output, report = application(root, run_id)
    directory, _ = suite(root, report["suite_version"])
    cases = {c["id"]: c for c in report["manifest"]["identity"]["cases"]}
    mapping: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    for row in audit_selection(report):
        token = uuid.uuid4().hex
        case = cases[row["case_id"]]
        mapping[token] = row["id"]
        items.append(
            {
                "token": token,
                "case": {
                    k: case[k]
                    for k in (
                        "prompt",
                        "actor",
                        "expected_assertion",
                        "terminal_objective",
                        "frozen_time",
                        "minimum_user_turns",
                        "max_tool_calls",
                        "coverage_family",
                    )
                },
                "tool_contract": [
                    golden.load_fixture(s["fixture"], directory / "holdout").model_dump(
                        mode="json"
                    )
                    for s in case["steps"]
                ],
                "turns": row["turns"],
                "requested_tools": row["requested_tools"],
                "rejected_tools": row["rejected_tools"],
                "actor_replies": row["actor_replies"],
                "application_stop": row["application_stop"],
            }
        )
    blind: dict[str, Any] = {
        "instructions": "Record Outcome/Grounding/Rules and actor validity from delivered conversation and actual evidence before revealing judge verdicts or application identity.",
        "items": items,
    }
    blind["audit_sha256"] = digest(blind)
    write(output / "audit.json", blind)
    binding = {
        "evidence_sha256": report["evidence_sha256"],
        "audit_sha256": blind["audit_sha256"],
        "mapping": mapping,
    }
    write(output / "audit-binding.json", binding)
    append(
        root,
        "audit_prepared",
        run_id=run_id,
        holdout_sha256=report["measurement"]["holdout_sha256"],
        audit_sha256=blind["audit_sha256"],
        evidence_sha256=report["evidence_sha256"],
        binding_sha256=digest(binding),
    )
    commit(root, f"Prepare private blinded audit {run_id}")
    return blind


def assessments(root: Path, run_id: str, review: dict[str, Any]) -> dict[str, Any]:
    output, report = application(root, run_id)
    blind, binding = read(output / "audit.json"), read(output / "audit-binding.json")
    tokens = [i["token"] for i in review["items"]]
    if (
        review["audit_sha256"] != blind["audit_sha256"]
        or blind["audit_sha256"]
        != digest({k: v for k, v in blind.items() if k != "audit_sha256"})
        or binding["evidence_sha256"] != report["evidence_sha256"]
        or binding["audit_sha256"] != blind["audit_sha256"]
        or not any(
            e["event"] == "audit_prepared"
            and e.get("run_id") == run_id
            and e.get("binding_sha256") == digest(binding)
            for e in ledger(root)
        )
        or len(tokens) != len(set(tokens))
        or set(tokens) != set(binding["mapping"])
        or not review["reviewer"].strip()
        or not review["evidence"].strip()
    ):
        raise ValueError(
            "audit review requires all selected items, reviewer, and exact evidence binding"
        )
    rows = {r["id"]: r for r in report["attempts"]}
    revealed: list[dict[str, Any]] = []
    for item in review["items"]:
        validity = item["actor_validity"]
        if (
            validity not in {"valid", "invalid", "uncertain"}
            or not item["evidence"].strip()
            or any(
                type(item[k]) is not bool
                if validity == "valid"
                else item[k] is not None
                for k in DIMENSIONS
            )
        ):
            raise ValueError(
                "audit needs three boolean scores for valid actors, null scores otherwise"
            )
        row = rows[binding["mapping"][item["token"]]]
        disagreements = (
            [
                k
                for k in DIMENSIONS
                if row["verdicts"].get(k, {}).get("passed") != item[k]
            ]
            if validity == "valid"
            else []
        )
        recorded_actor: dict[str, Any] = row["actor_validity"] or {}
        if recorded_actor.get("status") != validity:
            disagreements.append("actor_validity")
        revealed.append(
            {
                "id": item["token"],
                "original": row,
                "assessment": item,
                "disagreements": disagreements,
            }
        )
    # Exclusive write: a reviewer cannot revise the initial assessment after reveal.
    write(output / "audit-assessments.json", review)
    reveal: dict[str, Any] = {
        "evidence_sha256": report["evidence_sha256"],
        "audit_sha256": blind["audit_sha256"],
        "assessments_sha256": digest(review),
        "application": report["source"],
        "items": revealed,
    }
    reveal["reveal_sha256"] = digest(reveal)
    write(output / "audit-reveal.json", reveal)
    append(
        root,
        "audit_assessed",
        run_id=run_id,
        holdout_sha256=report["measurement"]["holdout_sha256"],
        evidence_sha256=report["evidence_sha256"],
        reviewer=review["reviewer"],
        assessments_sha256=digest(review),
        reveal_sha256=reveal["reveal_sha256"],
    )
    commit(root, f"Record assessments and reveal {run_id}")
    return reveal


def revealed_audit(root: Path, run_id: str, report: dict[str, Any]) -> dict[str, Any]:
    output = root / "runs" / identifier(run_id)
    reveal, assessed, blind, binding = (
        read(output / name)
        for name in (
            "audit-reveal.json",
            "audit-assessments.json",
            "audit.json",
            "audit-binding.json",
        )
    )
    events = ledger(root)
    if (
        reveal["reveal_sha256"]
        != digest({k: v for k, v in reveal.items() if k != "reveal_sha256"})
        or reveal["evidence_sha256"] != report["evidence_sha256"]
        or reveal["assessments_sha256"] != digest(assessed)
        or not any(
            e["event"] == "audit_assessed"
            and e.get("run_id") == run_id
            and e.get("evidence_sha256") == report["evidence_sha256"]
            and e.get("assessments_sha256") == digest(assessed)
            and e.get("reveal_sha256") == reveal["reveal_sha256"]
            for e in events
        )
        or blind["audit_sha256"]
        != digest({k: v for k, v in blind.items() if k != "audit_sha256"})
        or reveal["audit_sha256"] != blind["audit_sha256"]
        or binding["audit_sha256"] != blind["audit_sha256"]
        or binding["evidence_sha256"] != report["evidence_sha256"]
        or not any(
            e["event"] == "audit_prepared"
            and e.get("run_id") == run_id
            and e.get("binding_sha256") == digest(binding)
            for e in events
        )
    ):
        raise ValueError("audit evidence changed; approval is stale")
    return reveal


def finish_audit(root: Path, run_id: str, review: dict[str, Any]) -> None:
    output, report = application(root, run_id)
    reveal = revealed_audit(root, run_id, report)
    expected = {
        (item["id"], k) for item in reveal["items"] for k in item["disagreements"]
    }
    if (
        review["reveal_sha256"] != reveal["reveal_sha256"]
        or not review["reviewer"].strip()
        or not review["evidence"].strip()
    ):
        raise ValueError("dispositions must bind to revealed evidence and reviewer")
    approved = dispositions(expected, review["dispositions"])
    write(
        output / "audit-review.json",
        {
            **review,
            "status": "approved" if approved else "blocked",
            "reviewed_at": timestamp(),
        },
    )
    append(
        root,
        "audit_reviewed",
        run_id=run_id,
        holdout_sha256=report["measurement"]["holdout_sha256"],
        approved=approved,
        reviewer=review["reviewer"],
        review_sha256=digest(read(output / "audit-review.json")),
    )
    commit(root, f"Disposition audit {run_id}")


def audit_status(root: Path, run_id: str) -> str:
    output, report = application(root, run_id)
    if not (output / "audit-review.json").exists():
        return "pending"
    review = read(output / "audit-review.json")
    reveal = revealed_audit(root, run_id, report)
    if review["reveal_sha256"] != reveal["reveal_sha256"] or not any(
        e["event"] == "audit_reviewed"
        and e.get("run_id") == run_id
        and e.get("review_sha256") == digest(review)
        for e in ledger(root)
    ):
        raise ValueError("audit evidence changed; approval is stale")
    approved = dispositions(
        {(i["id"], k) for i in reveal["items"] for k in i["disagreements"]},
        review["dispositions"],
    )
    if review["status"] != ("approved" if approved else "blocked"):
        raise ValueError("audit status disagrees with dispositions")
    return review["status"]


def comparison(root: Path, candidate_id: str, incumbent_id: str) -> dict[str, Any]:
    output, candidate = application(root, candidate_id)
    _, incumbent = application(root, incumbent_id)
    if (
        candidate["role"] != "candidate"
        or incumbent["role"] != "incumbent"
        or candidate["measurement"] != incumbent["measurement"]
    ):
        raise ValueError("incompatible incumbent comparison identity or roles")
    for report in (candidate, incumbent):
        if (
            not report["overall"]["complete"]
            or report["unknown_usage"]
            or audit_status(root, report["run_id"]) != "approved"
        ):
            raise ValueError(
                "comparison requires complete measurements and approved audits"
            )
    before, after = case_results(incumbent), case_results(candidate)
    deltas = {cid: (sum(after[cid][1]) - sum(before[cid][1])) / 3 for cid in before}
    aggregate = compare(incumbent, candidate)
    for name, report in (("baseline", incumbent), ("final", candidate)):
        aggregate[name]["cases_passing_all_three"] = report["overall"][
            "cases_passing_all_three"
        ]
        aggregate[name]["expected_cases"] = 50
    aggregate.update(
        successful_trial_delta=candidate["overall"]["successful_trials"]
        - incumbent["overall"]["successful_trials"],
        pass_all_case_delta=candidate["overall"]["cases_passing_all_three"]
        - incumbent["overall"]["cases_passing_all_three"],
        mean_paired_case_delta=sum(deltas.values()) / 50,
        improved_cases=sum(d > 0 for d in deltas.values()),
        regressed_cases=sum(d < 0 for d in deltas.values()),
        unchanged_cases=sum(d == 0 for d in deltas.values()),
    )
    result = {
        "aggregate": aggregate,
        "private_case_differences": deltas,
        "candidate_evidence_sha256": candidate["evidence_sha256"],
        "incumbent_evidence_sha256": incumbent["evidence_sha256"],
    }
    path = output / f"comparison-{incumbent_id}.json"
    if path.exists():
        if read(path) != result:
            raise ValueError("private comparison evidence changed")
    else:
        write(path, result)
        commit(root, f"Record private comparison {candidate_id}")
    return result


def disclose(
    root: Path,
    run_id: str,
    payload_digest: str,
    recipient: str,
    purpose: str,
    *,
    manual: bool = False,
) -> None:
    _, report = application(root, run_id)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", payload_digest)
        or not recipient.strip()
        or not purpose.strip()
    ):
        raise ValueError("disclosure requires payload SHA256, recipient, and purpose")
    append(
        root,
        "feedback_disclosed",
        run_id=run_id,
        holdout_sha256=report["measurement"]["holdout_sha256"],
        payload_sha256=payload_digest,
        recipient=recipient,
        purpose=purpose,
        manual=manual,
    )
    commit(root, f"Record {'manual ' if manual else ''}feedback disclosure")


def export_report(
    root: Path,
    run_id: str,
    output: Path,
    recipient: str,
    purpose: str,
    incumbent_id: str | None = None,
) -> dict[str, Any]:
    _, report = application(root, run_id)
    status = audit_status(root, run_id)
    payload = {
        "measurement": report["measurement"],
        "suite_version": report["suite_version"],
        "source_sha256": report["source"]["source_sha256"],
        "source_commit": report["source"]["commit"],
        "overall": report["overall"],
        "cost_usd": report["cost_usd"],
        "unknown_usage": report["unknown_usage"],
        "evidence_sha256": report["evidence_sha256"],
        "audit_status": status,
        "reuse_status": reuse_status(root, report["measurement"]["holdout_sha256"]),
        "release_ready_evidence": report["overall"]["complete"]
        and not report["unknown_usage"]
        and status == "approved"
        and not report["measurement"]["synthetic_smoke"],
        "release_decision": "manual",
    }
    if incumbent_id:
        payload["comparison"] = comparison(root, run_id, incumbent_id)["aggregate"]
    if not recipient.strip() or not purpose.strip():
        raise ValueError("export requires recipient and purpose")
    # Record intent before publishing any bytes; a failed write conservatively counts as disclosure.
    encoded = (
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()
    disclose(root, run_id, sha(encoded), recipient, purpose)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(encoded)
    return payload


def export_suite(root: Path, suite_version: str, output: Path) -> None:
    directory, identity = measurement(root, suite_version)
    manifest = read(directory / "manifest.json")
    calibration = checked_report(directory / "calibration/report.json")
    exported: dict[str, bytes] = {}
    for split in ("training", "shadow"):
        for name in manifest["splits"][split]["files"]:
            exported[f"{split}/{name}"] = (directory / split / name).read_bytes()
    public_ids = {
        c.id
        for split in ("training", "shadow")
        for c in golden.load_cases(directory / split)
    }
    evidence = {
        "measurement": identity,
        "review_status": "approved",
        "calibration_rows": [
            r for r in calibration["rows"] if r["case_id"] in public_ids
        ],
        "actor_check": [
            r for r in calibration["actor_check"] if r["case_id"] in public_ids
        ],
    }
    exported["calibration.json"] = json.dumps(evidence, indent=2).encode()
    exported["manifest.json"] = json.dumps(
        {
            "version": suite_version,
            "measurement": identity,
            "splits": {s: manifest["splits"][s] for s in ("training", "shadow")},
        },
        indent=2,
    ).encode()
    from zipfile import ZipFile

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x") as archive:
        for name, data in sorted(exported.items()):
            archive.writestr(name, data)


def backup(root: Path, output: Path) -> None:
    ledger(root)
    commit(root, "Checkpoint private factory before backup")
    allowed = {
        "drafts",
        "suites",
        "runs",
        "snapshots",
        "ledger.jsonl",
        "AGENTS.md",
        ".gitignore",
        ".git",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("xb") as stream,
        tarfile.open(fileobj=stream, mode="w:gz") as archive,
    ):
        for name in sorted(allowed):
            path = root / name
            for item in [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]:
                if item.is_symlink() or not (item.is_file() or item.is_dir()):
                    raise ValueError(
                        "backup accepts regular private factory files only"
                    )
                archive.add(item, arcname=str(item.relative_to(root)), recursive=False)


def restore(root: Path, archive_path: Path) -> None:
    if any(p.name != ".factory.lock" for p in root.iterdir()):
        raise ValueError("restore requires a fresh empty volume/work directory")
    allowed = {
        "drafts",
        "suites",
        "runs",
        "snapshots",
        "ledger.jsonl",
        "AGENTS.md",
        ".gitignore",
        ".git",
    }
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or any(
            Path(m.name).is_absolute()
            or ".." in Path(m.name).parts
            or Path(m.name).parts[0] not in allowed
            or not (m.isfile() or m.isdir())
            for m in members
        ):
            raise ValueError("invalid backup allowlist or unsafe archive member")
        archive.extractall(root, members=members, filter="data")
    ledger(root)
    subprocess.run(
        ["git", "-C", str(root), "fsck", "--no-reflogs"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/private/work"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    freeze_parser = commands.add_parser("freeze")
    freeze_parser.add_argument("--inputs", type=Path, required=True)
    freeze_parser.add_argument("--suite", required=True)
    for split in SPLITS:
        freeze_parser.add_argument(f"--{split}-version", default="4.0.0")
    freeze_parser.add_argument("--synthetic-smoke", action="store_true")
    for name in ("calibrate", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--suite", required=True)
        command.add_argument("--mock", action="store_true")
        command.add_argument("--budget-usd", type=float)
        command.add_argument("--authorization", default="")
        if name == "evaluate":
            command.add_argument("--source", required=True)
            command.add_argument(
                "--role", choices=("candidate", "incumbent"), default="candidate"
            )
    command = commands.add_parser("import-source")
    command.add_argument("--snapshot", type=Path, required=True)
    for name in ("review-calibration", "assess", "disposition"):
        command = commands.add_parser(name)
        command.add_argument(
            "--suite" if name == "review-calibration" else "--run", required=True
        )
        command.add_argument("--review", type=Path, required=True)
    command = commands.add_parser("audit")
    command.add_argument("--run", required=True)
    command = commands.add_parser("approve-reuse")
    command.add_argument("--suite", required=True)
    command.add_argument("--source", required=True)
    command.add_argument("--reviewer", required=True)
    command.add_argument("--evidence", required=True)
    for name in ("export-report", "disclose"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True)
        command.add_argument("--recipient", required=True)
        command.add_argument("--purpose", required=True)
        if name == "export-report":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--incumbent")
        else:
            command.add_argument("--payload-sha256", required=True)
    command = commands.add_parser("export-suite")
    command.add_argument("--suite", required=True)
    command.add_argument("--output", type=Path, required=True)
    for name in ("backup", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    with locked(args.root):
        result = None
        if args.command == "init":
            init(args.root)
        elif args.command == "freeze":
            result = freeze(
                args.root,
                args.inputs,
                args.suite,
                {s: getattr(args, s + "_version") for s in SPLITS},
                smoke=args.synthetic_smoke,
            )
        elif args.command == "calibrate":
            result = calibrate(
                args.root,
                args.suite,
                mock=args.mock,
                budget=args.budget_usd,
                authorization=args.authorization,
            )
            result = {k: result[k] for k in ("evidence_sha256", "complete", "cost_usd")}
        elif args.command == "review-calibration":
            review_calibration(args.root, args.suite, read(args.review))
        elif args.command == "import-source":
            result = import_source(args.root, args.snapshot)
        elif args.command == "evaluate":
            result = evaluate(
                args.root,
                args.suite,
                args.source,
                args.role,
                mock=args.mock,
                budget=args.budget_usd,
                authorization=args.authorization,
            )
        elif args.command == "audit":
            blind = audit(args.root, args.run)
            result = {
                "audit_sha256": blind["audit_sha256"],
                "items": len(blind["items"]),
                "private_view": str(args.root / "runs" / args.run / "audit.json"),
            }
        elif args.command == "assess":
            reveal = assessments(args.root, args.run, read(args.review))
            result = {
                "reveal_sha256": reveal["reveal_sha256"],
                "private_view": str(
                    args.root / "runs" / args.run / "audit-reveal.json"
                ),
            }
        elif args.command == "disposition":
            finish_audit(args.root, args.run, read(args.review))
        elif args.command == "approve-reuse":
            result = approve_reuse(
                args.root, args.suite, args.source, args.reviewer, args.evidence
            )["sha256"]
        elif args.command == "disclose":
            disclose(
                args.root,
                args.run,
                args.payload_sha256,
                args.recipient,
                args.purpose,
                manual=True,
            )
        elif args.command == "export-report":
            result = export_report(
                args.root,
                args.run,
                args.output,
                args.recipient,
                args.purpose,
                args.incumbent,
            )
        elif args.command == "export-suite":
            export_suite(args.root, args.suite, args.output)
        elif args.command == "backup":
            backup(args.root, args.archive)
        elif args.command == "restore":
            restore(args.root, args.archive)
        if result is not None:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

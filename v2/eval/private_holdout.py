"""Private, fixed 100 x 3 release evaluation. Never defaults to development data.

Run inside the reviewed ARM64 Python 3.13 evaluator image. All detailed evidence,
reviews, and the persistent spending history stay on the private machine.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import platform
import random
import re
import stat
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from eval import golden, golden_actor_check, holdout_authoring
from eval import golden_run as run
from eval.artifact_agent import ArtifactAgent

IDENTITY = (
    "candidate",
    "bundle_id",
    "bundle_digest",
    "development_run",
    "development_attempt",
    "development_deployment",
)
# This is also the evaluator image's complete source allowlist. Execute guide
# entrypoints from this tree so their reviewed identity covers the actual code.
SOURCES = tuple(
    sorted(
        {
            *golden.SOURCE_FILES,
            *holdout_authoring.EXPORT_FILES,
            "pyproject.toml",
            "agent/toll_agent.py",
            "agent_tools/get_current_toll_price.py",
            "eval/private_holdout.py",
            "eval/holdout_authoring.py",
            "eval/golden/prompt-points.json",
            "eval/holdout_container/guide_data.py",
            "eval/holdout_container/runtime.py",
            "scripts/golden_gate.py",
            "scripts/check_production_release.py",
            "scripts/check_development_release.py",
            "scripts/release_blue_green.py",
            "scripts/blue_green.py",
            "scripts/cost_dashboard_release.py",
            "scripts/classify_deployment_error.py",
            "scripts/shared_packages.py",
        }
    )
)


def read(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_bytes(),
        object_pairs_hook=holdout_authoring.unique_keys,
        parse_constant=holdout_authoring.reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return cast(dict[str, Any], value)


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def evaluator_identity() -> str:
    """Pin the installed evaluator, guide, validation and locked dependencies."""
    return golden.digest({name: sha(golden.V2 / name) for name in SOURCES})


def execution_manifest(directory: Path) -> dict[str, Any]:
    manifest = read(directory / "manifest.json")
    if manifest.get("evaluator_sha256") != evaluator_identity():
        raise ValueError(
            "evaluator changed; resume this run with its original reviewed packet"
        )
    return manifest


def context_identity(path: Path) -> dict[str, Any]:
    value = read(path)
    if set(value) != set(IDENTITY):
        raise ValueError("context must contain the exact successful delivery identity")
    if not re.fullmatch(r"[0-9a-f]{40}", str(value["candidate"])) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", str(value["bundle_digest"])
    ):
        raise ValueError("invalid candidate or bundle digest")
    for key in set(IDENTITY) - {"candidate", "bundle_digest"}:
        if type(value[key]) is not int or not 0 < value[key] < 2**53:
            raise ValueError("invalid successful delivery identity")
    return value


def archive_files(archive: zipfile.ZipFile, maximum: int) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > 30000 or sum(i.file_size for i in infos) > maximum:
        raise ValueError("archive exceeds extraction bounds")
    names: set[str] = set()
    files: list[zipfile.ZipInfo] = []
    for info in infos:
        name = info.filename.rstrip("/")
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or "\\" in name
            or any(p in ("", ".", "..") for p in name.split("/"))
            or name in names
            or info.flag_bits & 1
            or stat.S_IFMT(info.external_attr >> 16)
            not in (0, stat.S_IFREG, stat.S_IFDIR)
        ):
            raise ValueError("unsafe or duplicate archive entry")
        names.add(name)
        if not info.is_dir():
            if stat.S_ISDIR(info.external_attr >> 16):
                raise ValueError("invalid archive file type")
            files.append(info)
    return files


def extract_agent(bundle: Path, context: dict[str, Any], destination: Path) -> None:
    """Verify the exact GitHub artifact, then extract its unchanged application zip."""
    if bundle.is_symlink() or bundle.stat().st_size > 2_000_000_000:
        raise ValueError("invalid release archive")
    if "sha256:" + sha(bundle) != context["bundle_digest"]:
        raise ValueError("release archive differs from delivered artifact")
    with zipfile.ZipFile(bundle) as outer:
        infos = archive_files(outer, 2_000_000_000)
        by_name = {info.filename: info for info in infos}
        manifest_info = by_name.get("release-manifest.json")
        if manifest_info is None or manifest_info.file_size > 1_000_000:
            raise ValueError("missing or oversized release manifest")
        manifest = json.loads(
            outer.read(manifest_info), object_pairs_hook=holdout_authoring.unique_keys
        )
        if (
            set(manifest)
            != {"schema_version", "commit_sha", "schema_versions", "files"}
            or type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != 1
            or manifest["commit_sha"] != context["candidate"]
        ):
            raise ValueError("release manifest candidate mismatch")
        records_value: object = manifest["files"]
        if not isinstance(records_value, list):
            raise ValueError("invalid release inventory")
        raw_records = cast(list[Any], records_value)
        if any(
            not isinstance(r, dict)
            or set(cast(dict[str, Any], r)) != {"path", "sha256"}
            for r in raw_records
        ):
            raise ValueError("invalid release inventory")
        records = cast(list[dict[str, Any]], raw_records)
        names = [r["path"] for r in records]
        if names != sorted(set(names)) or set(names) != set(by_name) - {
            "release-manifest.json"
        }:
            raise ValueError("release inventory differs from archive")
        for record in records:
            with outer.open(record["path"]) as stream:
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != record["sha256"]:
                raise ValueError("release payload digest mismatch")
        package = "v2/infra/build/agentcore.zip"
        if package not in by_name:
            raise ValueError("release has no packaged agent")
        with tempfile.TemporaryFile() as stream:
            with outer.open(package) as source:
                while chunk := source.read(1024 * 1024):
                    stream.write(chunk)
            stream.seek(0)
            with zipfile.ZipFile(stream) as inner:
                entries = archive_files(inner, 1_000_000_000)
                if "agent/toll_agent.py" not in {i.filename for i in entries}:
                    raise ValueError("packaged agent entrypoint is missing")
                destination.mkdir(parents=True, exist_ok=False)
                for info in entries:
                    target = destination / info.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with inner.open(info) as source, target.open("xb") as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)


@contextmanager
def private_corpus(root: Path) -> Generator[dict[str, Any]]:
    """One explicit corpus per process; restore the shared runner root on exit."""
    frozen = read(root / "manifest.json")
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / "authoring-kit.zip"
        holdout_authoring.export_kit(archive)
        with zipfile.ZipFile(archive) as kit:
            kit_sha256 = hashlib.sha256(kit.read("kit.json")).hexdigest()
    if frozen["kit_sha256"] != kit_sha256:
        raise ValueError("frozen corpus was authored with a different evaluator kit")
    manifest = holdout_authoring.validate_private(
        root,
        final=True,
        kit_sha256=kit_sha256,
        public_points=golden.V2 / "eval/golden/prompt-points.json",
    )
    if manifest != frozen or not re.fullmatch(r"[0-9a-f]{64}", manifest["kit_sha256"]):
        raise ValueError("invalid frozen corpus identity")
    previous = golden.ROOT
    golden.ROOT = root
    try:
        yield manifest
    finally:
        golden.ROOT = previous


def events(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
    ]


def accounting(rows: list[dict[str, Any]]) -> tuple[float, bool]:
    starts = Counter(
        (r["attempt"], r["role"]) for r in rows if r["event"] == "model_started"
    )
    ends = Counter(
        (r["attempt"], r["role"]) for r in rows if r["event"] == "model_finished"
    )
    measured = [
        run.Measurement.model_validate(
            {k: v for k, v in r.items() if k not in {"event", "attempt"}}
        )
        for r in rows
        if r["event"] == "model_finished"
    ]
    return sum(m.cost_usd for m in measured), starts != ends or any(
        not m.complete for m in measured
    )


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(
            "initialize the spending history with explicit prior accounting first"
        )
    history = read(path)
    if (
        set(history)
        != {"version", "prior_cost_usd", "prior_unknown_usage", "executions"}
        or history["version"] != 1
    ):
        raise ValueError("invalid spending history")
    carried_accounting(path)
    rows: list[dict[str, Any]] = history["executions"]
    if len({r["run_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate history execution")
    for row in rows:
        manifest = read(Path(row["directory"]) / "manifest.json")
        if any(manifest[k] != row[k] for k in row if k != "directory"):
            raise ValueError("history execution identity changed")
    return rows


def carried_accounting(path: Path) -> tuple[float, bool]:
    history = read(path)
    cost, unknown = history["prior_cost_usd"], history["prior_unknown_usage"]
    if (
        type(cost) not in (int, float)
        or not math.isfinite(cost)
        or cost < 0
        or type(unknown) is not bool
    ):
        raise ValueError("invalid carried prior accounting")
    return cost, unknown


def spending(
    history: list[dict[str, Any]], carried: tuple[float, bool] = (0, False)
) -> tuple[float, bool]:
    values = [accounting(events(Path(item["directory"]))) for item in history]
    return carried[0] + sum(value[0] for value in values), carried[1] or any(
        value[1] for value in values
    )


def reviewed(path: Path | None, evidence: str) -> bool:
    if path is None:
        return False
    value = read(path)
    if (
        value.get("status") != "approved"
        or value.get("evidence_sha256") != evidence
        or not isinstance(value.get("reviewer"), str)
        or not value["reviewer"].strip()
        or not isinstance(value.get("evidence"), str)
        or not value["evidence"].strip()
    ):
        raise ValueError("human review must approve this exact private evidence")
    return True


def report_evidence(directory: Path) -> str:
    return golden.digest(
        {
            "manifest": read(directory / "manifest.json"),
            "events": events(directory),
            "completion": read(directory / "completed.json"),
        }
    )


def aggregate(directory: Path) -> dict[str, Any]:
    manifest, rows = read(directory / "manifest.json"), events(directory)
    completed = read(directory / "completed.json")["completed_at"]
    case_ids = manifest["case_ids"]
    finished = [
        run.Attempt.model_validate({k: v for k, v in row.items() if k != "event"})
        for row in rows
        if row["event"] == "attempt_finished"
    ]
    expected = {(case, trial) for case in case_ids for trial in (1, 2, 3)}
    observed = [(a.case_id, a.trial) for a in finished]
    if (
        len(case_ids) != 100
        or len(set(case_ids)) != 100
        or len(observed) != len(set(observed))
        or set(observed) - expected
    ):
        raise ValueError("unexpected or duplicate private trial")
    scored = [
        a
        for a in finished
        if a.status == "scored"
        and a.actor_validity is not None
        and a.actor_validity.status == "valid"
        and a.measurements
        and all(m.complete for m in a.measurements)
        and set(a.verdicts) == {"outcome", "grounding", "rules"}
    ]
    passes = [sum(a.passed for a in scored if a.case_id == case) for case in case_ids]
    inconclusive = sum(a.status == "inconclusive" for a in finished)
    rng = random.Random(0)
    samples = [sum(rng.choices(passes, k=100)) / 300 for _ in range(10000)]
    durations: dict[str, float] = {}
    for row in rows:
        if row["event"] == "application_turn_finished":
            seconds = row["seconds"]
            if type(seconds) not in (int, float) or not 0 <= seconds <= 86400:
                raise ValueError("invalid application timing")
            durations[row["attempt"]] = durations.get(row["attempt"], 0) + seconds
    # Only completed application conversations provide latency observations.
    latencies = [
        durations[a.id]
        for a in finished
        if a.status in {"scored", "inconclusive"} and a.id in durations
    ]
    costs = [row for row in rows if row["event"] == "model_finished"]
    return {
        "started_at": manifest["started_at"],
        "completed_at": completed,
        "replacement_reason": manifest["replacement_reason"],
        "passed": sum(passes),
        "failed": len(scored) - sum(passes),
        "inconclusive": inconclusive,
        "unmeasured": 300 - len(scored) - inconclusive,
        "case_pass_counts": [passes.count(n) for n in range(4)],
        "success_interval": {
            "method": "case-bootstrap-95",
            "lower": run.percentile(samples, 0.025),
            "upper": run.percentile(samples, 0.975),
        },
        "latency_p50_seconds": run.percentile(latencies, 0.5),
        "latency_p95_seconds": run.percentile(latencies, 0.95),
        "agent_cost_usd": sum(r["cost_usd"] for r in costs if r["role"] == "agent"),
        "total_cost_usd": accounting(rows)[0],
    }


def preparation_report(directory: Path) -> dict[str, Any]:
    manifest, rows = read(directory / "manifest.json"), events(directory)
    calibration = [r for r in rows if r["event"] == "calibration"]
    actors = [r for r in rows if r["event"] == "actor_check"]
    expected = set(manifest["reference_ids"])
    actual = [r["id"] for r in calibration]
    actor_ids = [(r["case_id"], r["trial"]) for r in actors]
    complete = (
        len(actual) == len(expected)
        and set(actual) == expected
        and all(r["measurement_complete"] for r in calibration)
        and len(actor_ids) == 300
        and len(set(actor_ids)) == 300
        and set(actor_ids) == {(c, t) for c in manifest["case_ids"] for t in (1, 2, 3)}
        and all(r["status"] == "scored" for r in actors)
        and not accounting(rows)[1]
    )
    return {
        "complete": complete,
        "evidence_sha256": report_evidence(directory),
        "calibration": calibration,
        "actor_rehearsal": actors,
        "cost_usd": accounting(rows)[0],
        "unknown_usage": accounting(rows)[1],
    }


def policy_limits(path: Path) -> dict[str, Any]:
    limits = read(path)["policy"]
    fixed = {
        "version": "4.0.0",
        "evaluation_scope": "private-held-out",
        "cases": 100,
        "trials": 3,
        "successes_min": 240,
        "run_cost_max_usd": 5.0,
        "authorized_cost_max_usd": 25.0,
    }
    if any(
        type(limits.get(k))
        not in ((int, float) if isinstance(v, float) else (type(v),))
        or limits.get(k) != v
        for k, v in fixed.items()
    ):
        raise ValueError("unsupported private release policy")
    if set(limits) != {
        *fixed,
        "holdout_sha256",
        "evaluator_sha256",
        "calibration_sha256",
    }:
        raise ValueError("unsupported policy fields")
    return cast(dict[str, Any], limits)


def calibration_admission(
    directory: Path,
    review: Path,
    policy_path: Path,
    holdout: str,
    evaluator: str,
) -> str:
    report = preparation_report(directory)
    manifest = read(directory / "manifest.json")
    if (
        not report["complete"]
        or manifest["holdout_sha256"] != holdout
        or manifest["evaluator_sha256"] != evaluator
        or not reviewed(review, report["evidence_sha256"])
    ):
        raise ValueError(
            "private calibration or actor rehearsal is incomplete or changed"
        )
    calibration_sha = golden.digest(
        {"evidence_sha256": report["evidence_sha256"], "review": read(review)}
    )
    limits = policy_limits(policy_path)
    approval = read(policy_path)["approval"]
    if (
        limits["holdout_sha256"] != holdout
        or limits["evaluator_sha256"] != evaluator
        or limits["calibration_sha256"] != calibration_sha
        or approval.get("status") != "approved"
        or approval.get("evidence_sha256") != golden.digest(limits)
        or not approval.get("reviewer")
        or not approval.get("evidence")
    ):
        raise ValueError(
            "policy must approve the exact holdout, evaluator and reviewed calibration"
        )
    approved = datetime.fromisoformat(approval["approved_at"])
    if approved.tzinfo is None or approved > datetime.now(UTC):
        raise ValueError("invalid policy approval time")
    return calibration_sha


def replacement_reason(
    history: list[dict[str, Any]],
    context: dict[str, Any],
    holdout: str,
    review: Path | None,
) -> str:
    previous = [
        r
        for r in history
        if r["mode"] == "run"
        and r["holdout_sha256"] == holdout
        and r["bundle_digest"] == context["bundle_digest"]
    ]
    if not previous:
        if review is not None:
            raise ValueError("original execution cannot have a replacement approval")
        return "none"
    if len(previous) != 1 or review is None:
        raise ValueError(
            "one original and one explicitly reviewed validity replacement only"
        )
    directory = Path(previous[0]["directory"])
    execution_manifest(directory)
    if not reviewed(review, report_evidence(directory)):
        raise ValueError("replacement approval missing")
    reason = read(review).get("replacement_reason")
    original = aggregate(directory)
    if (
        reason not in {"infrastructure", "actor_validity"}
        or not original["unmeasured" if reason == "infrastructure" else "inconclusive"]
    ):
        raise ValueError("quality-only replacement is forbidden")
    return cast(str, reason)


def summary(
    directory: Path,
    history: list[dict[str, Any]],
    review: Path | None,
    carried: tuple[float, bool] = (0, False),
) -> dict[str, Any]:
    manifest = execution_manifest(directory)
    selected = [
        row
        for row in history
        if row["mode"] == "run"
        and row["bundle_digest"] == manifest["bundle_digest"]
        and row["holdout_sha256"] == manifest["holdout_sha256"]
    ]
    for row in selected:
        execution_manifest(Path(row["directory"]))
    attempts = [aggregate(Path(row["directory"])) for row in selected]
    if (
        not selected
        or len(selected) > 2
        or selected[-1]["run_id"] != manifest["run_id"]
    ):
        raise ValueError("render the latest recorded candidate execution")
    cumulative, unknown = spending(history, carried)
    return {
        "schema_version": 1,
        "evaluation_scope": "private-held-out",
        **manifest["context"],
        **{
            key: manifest[key]
            for key in (
                "policy_sha256",
                "holdout_sha256",
                "evaluator_sha256",
                "calibration_sha256",
            )
        },
        "cases": 100,
        "trials": 3,
        "holdout_attempts": sum(
            r["mode"] == "run" and r["holdout_sha256"] == manifest["holdout_sha256"]
            for r in history
        ),
        "cumulative_cost_usd": cumulative,
        "unknown_usage": unknown,
        "private_review_complete": reviewed(review, report_evidence(directory)),
        "attempts": attempts,
    }


def execute(args: argparse.Namespace, history: list[dict[str, Any]]) -> None:
    context = context_identity(args.context)
    limits = policy_limits(args.policy)
    evaluator = evaluator_identity()
    with private_corpus(args.corpus.resolve()) as corpus:
        cases = golden.load_cases()
        examples = [
            golden.Example.model_validate(e)
            for e in json.loads((args.corpus / "examples.json").read_bytes())
        ]
        reference_ids = [f"{e.case_id}-{e.label}" for e in examples]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("reference labels create duplicate evidence IDs")
        calibration = None
        reason = "none"
        if args.mode == "run":
            if args.calibration is None or args.calibration_review is None:
                raise ValueError(
                    "run requires private preparation and its human review"
                )
            calibration = calibration_admission(
                args.calibration,
                args.calibration_review,
                args.policy,
                corpus["holdout_sha256"],
                evaluator,
            )
            if not any(
                r["mode"] == "prepare"
                and Path(r["directory"]) == args.calibration.resolve()
                for r in history
            ):
                raise ValueError(
                    "calibration spending must be in the persistent history"
                )
            reason = replacement_reason(
                history, context, corpus["holdout_sha256"], args.replacement_review
            )
        carried = carried_accounting(args.history)
        spent, unknown = spending(history, carried)
        if unknown:
            raise ValueError("prior execution has unknown usage; no more paid calls")
        if spent >= 25:
            raise ValueError("cumulative $25 authorization exhausted")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "inject OPENAI_API_KEY into the private evaluator environment"
            )
        if platform.machine() not in {"aarch64", "arm64"} or sys.version_info[:2] != (
            3,
            13,
        ):
            raise ValueError("evaluation requires ARM64 Python 3.13")
        # Exact immutable extraction happens before reserving an execution or spending.
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "agent"
            extract_agent(args.bundle, context, package)
            journal = run.Journal(args.output, min(25, spent + 5), spent)
            manifest = {
                "run_id": str(uuid.uuid4()),
                "mode": args.mode,
                "started_at": datetime.now(UTC).isoformat(),
                "context": context,
                "bundle_digest": context["bundle_digest"],
                "holdout_sha256": corpus["holdout_sha256"],
                "evaluator_sha256": evaluator,
                "policy_sha256": golden.digest(limits),
                "calibration_sha256": calibration,
                "replacement_reason": reason,
                "case_ids": [c.id for c in cases],
                "reference_ids": reference_ids,
                "prior_spend_usd": spent,
                "budget_usd": journal.limit,
            }
            write(args.output / "manifest.json", manifest)
            history.append(
                {
                    **{
                        k: manifest[k]
                        for k in (
                            "run_id",
                            "mode",
                            "bundle_digest",
                            "holdout_sha256",
                            "evaluator_sha256",
                        )
                    },
                    "directory": str(args.output.resolve()),
                }
            )
            write(
                args.history,
                {
                    "version": 1,
                    "prior_cost_usd": carried[0],
                    "prior_unknown_usage": carried[1],
                    "executions": history,
                },
            )
            original_key_loader = run.toll_agent.load_openai_api_key
            run.toll_agent.load_openai_api_key = lambda: api_key
            try:
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    if args.mode == "prepare":
                        run.calibrate(journal, pool, examples=examples)
                        passing: dict[str, golden.Example] = {}
                        for example in examples:
                            if (
                                example.expected
                                and all(example.expected.model_dump().values())
                                and example.actor_validity == "valid"
                            ):
                                passing.setdefault(example.case_id, example)

                        def rehearse(pair: tuple[golden.Example, int]) -> None:
                            if not journal.stop_requested:
                                golden_actor_check.check(pair[0], pair[1], journal)

                        list(
                            pool.map(
                                rehearse,
                                [(passing[c.id], t) for c in cases for t in (1, 2, 3)],
                            )
                        )
                    else:

                        def factory(
                            case: golden.GoldenCase,
                            attempt: run.Attempt,
                            book: run.Journal,
                            messages: list[str],
                        ) -> ArtifactAgent:
                            return ArtifactAgent(
                                package,
                                api_key,
                                case,
                                attempt,
                                book,
                                messages,
                                corpus_root=args.corpus,
                            )

                        def trial(pair: tuple[golden.GoldenCase, int]) -> None:
                            if not journal.stop_requested:
                                run.execute(
                                    pair[0], pair[1], journal, agent_factory=factory
                                )

                        list(
                            pool.map(trial, [(c, t) for c in cases for t in (1, 2, 3)])
                        )
            finally:
                run.toll_agent.load_openai_api_key = original_key_loader
                write(
                    args.output / "completed.json",
                    {"completed_at": datetime.now(UTC).isoformat()},
                )
                render(args.output, history, None, carried)


def render(
    directory: Path,
    history: list[dict[str, Any]],
    review: Path | None,
    carried: tuple[float, bool] = (0, False),
) -> None:
    manifest = execution_manifest(directory)
    if not (directory / "completed.json").exists():
        write(
            directory / "completed.json",
            # An interrupted run has no reliable end time; preserve the known
            # start time instead of inventing a later completion.
            {"completed_at": manifest["started_at"]},
        )
    if manifest["mode"] == "prepare":
        report = preparation_report(directory)
        if review is not None and reviewed(review, report["evidence_sha256"]):
            report["calibration_sha256"] = golden.digest(
                {"evidence_sha256": report["evidence_sha256"], "review": read(review)}
            )
        write(directory / "private-report.json", report)
        print(
            f"Private preparation complete: {report['complete']}; review digest: {report['evidence_sha256']}"
        )
        if "calibration_sha256" in report:
            print(f"Reviewed calibration digest: {report['calibration_sha256']}")
    else:
        evidence = report_evidence(directory)
        write(
            directory / "private-report.json",
            {"evidence_sha256": evidence, "aggregate": aggregate(directory)},
        )
        write(directory / "summary.json", summary(directory, history, review, carried))
        print(f"Aggregate summary written; private review digest: {evidence}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("identity", "init-history", "prepare", "run", "render")
    )
    for name in (
        "corpus",
        "bundle",
        "context",
        "policy",
        "output",
        "history",
        "calibration",
        "calibration-review",
        "review",
        "replacement-review",
    ):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--prior-cost-usd", type=float)
    parser.add_argument("--prior-unknown-usage", choices=("true", "false"))
    args = parser.parse_args()
    if args.mode == "identity":
        print(evaluator_identity())
        return
    if args.mode == "init-history":
        if (
            args.history is None
            or args.prior_cost_usd is None
            or args.prior_unknown_usage is None
        ):
            parser.error(
                "init-history requires --history --prior-cost-usd --prior-unknown-usage"
            )
        if not math.isfinite(args.prior_cost_usd) or args.prior_cost_usd < 0:
            parser.error("invalid prior cost")
        args.history.parent.mkdir(parents=True, exist_ok=True)
        with args.history.open("x") as stream:
            json.dump(
                {
                    "version": 1,
                    "prior_cost_usd": args.prior_cost_usd,
                    "prior_unknown_usage": args.prior_unknown_usage == "true",
                    "executions": [],
                },
                stream,
            )
        return
    required = (
        ("output", "history")
        if args.mode == "render"
        else ("corpus", "bundle", "context", "policy", "output", "history")
    )
    if any(getattr(args, key) is None for key in required):
        parser.error("required: " + ", ".join("--" + key for key in required))
    # The lock stays open through the entire execution, including model calls.
    args.history.parent.mkdir(parents=True, exist_ok=True)
    with args.history.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        history = load_history(args.history)
        if args.mode == "render":
            render(args.output, history, args.review, carried_accounting(args.history))
        else:
            execute(args, history)


if __name__ == "__main__":
    main()

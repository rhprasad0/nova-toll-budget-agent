"""Private guide records and fixed evaluator plans; no model calls or host commands."""

from __future__ import annotations

import contextlib
import fcntl
import html
import io
import json
import math
import os
import re
import stat
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

MAX_REQUEST = 16_384
ACTIONS: dict[str, set[str]] = {
    "phase": set(),
    "status": set(),
    "validate": set(),
    "review_cases": set(),
    "approve_cases": {"batch", "digest", "note"},
    "freeze": {"digest", "note"},
    "review_result": {"kind", "run"},
    "approve_result": {"kind", "run", "digest", "note"},
    "evaluation_plan": {"mode", "note"},
    "init_history": {"prior_cost_usd", "prior_unknown_usage"},
    "validate_input": set(),
    "identities": set(),
    "summary": {"run"},
}


def read(path: Path) -> dict[str, Any]:
    from eval.holdout_authoring import reject_constant, unique_keys

    if path.is_symlink():
        raise ValueError("guide records cannot be symlinks")
    value = json.loads(
        path.read_bytes(), object_pairs_hook=unique_keys, parse_constant=reject_constant
    )
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return cast(dict[str, Any], value)


def store(path: Path, value: dict[str, Any]) -> None:
    """Receipts are immutable; a repeated approval preserves its original record."""
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("guide records cannot be symlinks")
    # A killed freeze must not leave a temporary file inside the frozen payload.
    temporary_directory = (
        path.parent.parent if path.name == "manifest.json" else path.parent
    )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=temporary_directory
    ) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        os.link(stream.name, path)


def note(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError(
            "record the human's explicit decision in a note (1-4000 characters)"
        )
    return value.strip()


def digest_check(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("invalid evidence digest")
    return value


def run_name(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,79}", value
    ):
        raise ValueError("invalid run name")
    return value


def approval(digest: str, decision: str) -> dict[str, Any]:
    return {
        "status": "approved",
        "evidence_sha256": digest,
        "reviewer": "private operator via Codex guide",
        "evidence": note(decision),
        "approved_at": datetime.now(UTC).isoformat(),
    }


def approved_record(path: Path, evidence: str) -> dict[str, Any]:
    """Validate guide approval without importing evaluator or candidate code."""
    value = read(path)
    if (
        value.get("status") != "approved"
        or value.get("evidence_sha256") != evidence
        or any(
            not isinstance(value.get(key), str) or not value[key].strip()
            for key in ("reviewer", "evidence")
        )
    ):
        raise ValueError("human review must approve this exact private evidence")
    timestamp = value.get("approved_at")
    if not isinstance(timestamp, str) or len(timestamp) > 40:
        raise ValueError("invalid private approval time")
    try:
        approved_at = datetime.fromisoformat(timestamp)
    except ValueError:
        raise ValueError("invalid private approval time") from None
    if approved_at.tzinfo is None or approved_at > datetime.now(UTC):
        raise ValueError("invalid private approval time")
    return value


def corpus_digest(corpus: Path) -> str:
    from eval import golden, holdout_authoring

    return golden.digest(holdout_authoring.payload_files(corpus))


def validate(corpus: Path, *, final: bool) -> dict[str, Any]:
    from eval import holdout_authoring

    if (holdout_authoring.V2 / "kit.json").is_file():
        kit_sha256 = holdout_authoring.verify_kit()
        points = holdout_authoring.V2 / "public/prompt-points.json"
    else:
        # The offline evaluator helper has the same allowlisted public kit source.
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "kit.zip"
            holdout_authoring.export_kit(archive)
            with zipfile.ZipFile(archive) as kit:
                kit_sha256 = holdout_authoring.sha256(kit.read("kit.json"))
        points = holdout_authoring.V2 / "eval/golden/prompt-points.json"
    return holdout_authoring.validate_private(
        corpus, final=final, kit_sha256=kit_sha256, public_points=points
    )


def snapshot_corpus(corpus: Path, target: Path) -> None:
    """Copy through directory descriptors; editor changes cannot redirect reads."""
    with contextlib.ExitStack() as opened:
        root = os.open(corpus, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.callback(os.close, root)
        files: list[tuple[str, int, str]] = []
        for name in os.listdir(root):
            if name == "fixtures":
                fixtures = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root
                )
                opened.callback(os.close, fixtures)
                for fixture in os.listdir(fixtures):
                    if not re.fullmatch(r"[a-z0-9_-]+\.json", fixture):
                        raise ValueError("unexpected corpus path")
                    files.append((f"fixtures/{fixture}", fixtures, fixture))
            elif name in {
                "cases.jsonl",
                "examples.json",
                "prompt-points.json",
                "manifest.json",
            }:
                files.append((name, root, name))
            else:
                raise ValueError("unexpected corpus path")
        if len(files) > 405:
            raise ValueError("too many corpus files")
        total = 0
        for relative, directory, name in files:
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("corpus files must be regular files")
                data = stream.read(50_000_001 - total)
            total += len(data)
            if total > 50_000_000:
                raise ValueError("corpus exceeds 50 MB")
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)


def review_cases(corpus: Path, guide: Path, *, frozen: bool) -> dict[str, Any]:
    """Bind every displayed value to one private snapshot, then check for edits."""
    from eval import golden

    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "corpus"
        snapshot.mkdir()
        snapshot_corpus(corpus, snapshot)
        validate(snapshot, final=frozen)
        digest, rows = batches(snapshot, guide)
        cases = golden.load_cases(snapshot)
        references = json.loads((snapshot / "examples.json").read_bytes())
        for row in rows:
            batch = cases[(row["batch"] - 1) * 10 : row["batch"] * 10]
            sections: list[tuple[str, Any]] = []
            for case in batch:
                sections.append(
                    (f"{case.number}. {case.title}", case.model_dump(mode="json"))
                )
                sections.append(
                    (
                        f"{case.id}: reference transcripts",
                        [r for r in references if r["case_id"] == case.id],
                    )
                )
                for step in case.steps:
                    sections.append(
                        (
                            step.fixture,
                            json.loads(
                                (snapshot / "fixtures" / step.fixture).read_bytes()
                            ),
                        )
                    )
            sections.append(
                (
                    "Public prompt points",
                    json.loads((snapshot / "prompt-points.json").read_bytes()),
                )
            )
            page(
                guide,
                row["page"],
                f"Holdout case batch {row['batch']}",
                digest,
                sections,
            )
        if corpus_digest(corpus) != digest:
            raise ValueError("case content changed while rendering; review it again")
        presented = guide / "presented" / f"cases-{digest}.json"
        if not presented.exists():
            store(presented, {"digest": digest, "batches": len(rows)})
        return {"digest": digest, "batches": rows}


def batches(corpus: Path, guide: Path) -> tuple[str, list[dict[str, Any]]]:
    from eval import golden

    digest = corpus_digest(corpus)
    cases = golden.load_cases(corpus)
    result: list[dict[str, Any]] = []
    for start in range(0, len(cases), 10):
        batch = start // 10 + 1
        record = guide / "reviews" / f"cases-{batch:03d}-{digest}.json"
        approved = record.exists() and bool(approved_record(record, digest))
        result.append(
            {
                "batch": batch,
                "count": len(cases[start : start + 10]),
                "digest": digest,
                "approved": approved,
                "page": f"cases-{batch:03d}-{digest}.html",
            }
        )
    return digest, result


def page(
    guide: Path, filename: str, title: str, digest: str, sections: list[tuple[str, Any]]
) -> None:
    directory = guide / "pages"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if directory.is_symlink() or target.is_symlink():
        raise ValueError("review pages cannot be symlinks")
    body = "".join(
        f"<section><h2>{html.escape(label)}</h2><pre>"
        f"{html.escape(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))}"
        "</pre></section>"
        for label, value in sections
    )
    target.write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{max-width:72rem;margin:2rem auto;padding:0 1rem;font:18px system-ui;"
        "line-height:1.5;color:#17212b;background:#fafafa}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere;font:14px monospace;background:#eee;padding:1rem}"
        "section{border-top:1px solid #bbb;margin-top:2rem}h1{line-height:1.2}</style>"
        f"<h1>{html.escape(title)}</h1><p>Private evidence. Review the full content, then "
        f"record your decision in Codex.</p><p>Evidence digest: <code>{digest}</code></p>"
        f"{body}</html>",
        encoding="utf-8",
    )


def freeze_receipt(corpus: Path, guide: Path) -> dict[str, Any]:
    digest = corpus_digest(corpus)
    receipt = read(guide / "freeze.json")
    if receipt.get("evidence_sha256") != digest:
        raise ValueError("frozen reviewed corpus changed")
    approved_record(guide / "freeze.json", digest)
    manifest = validate(corpus, final=True)
    if receipt.get("holdout_sha256") != manifest["holdout_sha256"]:
        raise ValueError("freeze receipt differs from frozen corpus")
    return manifest


def history_lock(output: Path) -> TextIO:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "history.lock"
    if path.is_symlink():
        raise ValueError("history lock cannot be a symlink")
    lock = path.open("r" if path.exists() else "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError("evaluation is still active; reconnect and wait") from None
    return lock


def history(output: Path) -> list[dict[str, Any]]:
    from eval import private_holdout as private

    rows = private.load_history(output / "history.json")
    for row in rows:
        directory = Path(row["directory"])
        if directory.is_symlink() or directory.parent.resolve() != output.resolve():
            raise ValueError(
                "history execution is outside the private results directory"
            )
    return rows


def result_directory(
    output: Path, name: str, kind: str | None = None, *, recover: bool = False
) -> Path:
    from eval import private_holdout as private

    directory = output / run_name(name)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("unknown run")
    manifest = private.execution_manifest(directory)
    if (
        kind is not None
        and manifest["mode"] != {"calibration": "prepare", "candidate": "run"}[kind]
    ):
        raise ValueError("review kind differs from execution")
    if not any(Path(row["directory"]) == directory for row in history(output)):
        raise ValueError("run is missing from persistent spending history")
    if not (directory / "completed.json").is_file():
        if not recover:
            raise ValueError(
                "review the interrupted operation before recording approval"
            )
        # Caller holds history.lock and the host verified the evaluator is stopped.
        with contextlib.redirect_stdout(io.StringIO()):
            private.render(
                directory,
                history(output),
                None,
                private.carried_accounting(output / "history.json"),
            )
    return directory


def review_path(output: Path, kind: str, name: str) -> Path:
    return output / "reviews" / f"{kind}-{run_name(name)}.json"


def input_identity(inputs: Path) -> dict[str, Any]:
    from eval import golden
    from eval import private_holdout as private

    if inputs.is_symlink() or set(p.name for p in inputs.iterdir()) != {
        "release.zip",
        "context.json",
        "policy.json",
    }:
        raise ValueError(
            "candidate inputs must contain exactly release.zip, context.json and policy.json"
        )
    if any(p.is_symlink() or not p.is_file() for p in inputs.iterdir()):
        raise ValueError("candidate inputs must be regular files")
    context = private.context_identity(inputs / "context.json")
    limits = private.policy_limits(inputs / "policy.json")
    with tempfile.TemporaryDirectory() as temporary:
        private.extract_agent(
            inputs / "release.zip", context, Path(temporary) / "agent"
        )
    return {"context": context, "policy_sha256": golden.digest(limits)}


def approved_calibration(
    output: Path, corpus: dict[str, Any]
) -> tuple[Path, Path, str]:
    from eval import golden
    from eval import private_holdout as private

    evaluator = private.evaluator_identity()
    for row in reversed(history(output)):
        if (
            row["mode"] != "prepare"
            or row["holdout_sha256"] != corpus["holdout_sha256"]
            or row["evaluator_sha256"] != evaluator
        ):
            continue
        directory = Path(row["directory"])
        review = review_path(output, "calibration", directory.name)
        if not review.is_file() or not (directory / "completed.json").is_file():
            continue
        report = private.preparation_report(directory)
        if not report["complete"] or not private.reviewed(
            review, report["evidence_sha256"]
        ):
            continue
        return (
            directory,
            review,
            golden.digest(
                {
                    "evidence_sha256": report["evidence_sha256"],
                    "review": private.read(review),
                }
            ),
        )
    raise ValueError(
        "complete preparation and approve its exact calibration evidence first"
    )


def dispatch(
    request: dict[str, Any],
    *,
    corpus: Path = Path("/private/corpus"),
    guide: Path = Path("/guide"),
    output: Path = Path("/output"),
    inputs: Path = Path("/input"),
) -> dict[str, Any]:
    action = request.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("unknown guide action")
    required = {"action", *ACTIONS[action]}
    allowed = required.copy()
    if action == "evaluation_plan":
        allowed.add("replacement_reason")
    if not required <= request.keys() or not request.keys() <= allowed:
        raise ValueError("unexpected or missing action fields")
    if "note" in request:
        note(request["note"])
    if "digest" in request:
        digest_check(request["digest"])
    if "kind" in request and (
        not isinstance(request["kind"], str)
        or request["kind"] not in {"calibration", "candidate"}
    ):
        raise ValueError("unknown review kind")
    if "run" in request:
        run_name(request["run"])
    for directory in (guide, output):
        if directory.is_symlink():
            raise ValueError("private state must use real directories")
    guide.mkdir(parents=True, exist_ok=True)
    frozen = (corpus / "manifest.json").exists()
    receipt = (guide / "freeze.json").exists()
    if receipt and not frozen:
        raise ValueError("frozen corpus manifest is missing; restore the frozen corpus")
    if action == "phase":
        if receipt:
            freeze_receipt(corpus, guide)
        elif frozen:
            validate(corpus, final=True)
        return {"frozen": frozen, "needs_evaluator": receipt}
    if action == "status":
        state: dict[str, Any] = {
            "frozen": frozen,
            "ready": False,
            "phase": "author",
            "runs": [],
        }
        if not frozen and not (corpus / "cases.jsonl").is_file():
            state["next"] = (
                "Create independent cases in /private/corpus using the public kit."
            )
            return state
        try:
            digest, rows = batches(corpus, guide)
        except (ValueError, OSError, KeyError, TypeError) as error:
            if frozen:
                raise
            state.update(
                draft_error=str(error)[:2000],
                next="Finish or repair the draft files in /private/corpus, then validate and review them.",
            )
            return state
        state.update(
            digest=digest,
            batches=rows,
            approved_batches=sum(r["approved"] for r in rows),
        )
        if not frozen:
            state["next"] = (
                "Review each case batch, save all edits, and explicitly approve corpus freeze."
            )
            return state
        state["phase"] = "frozen" if receipt else "recovery"
        if not receipt:
            validate(corpus, final=True)
            state["next"] = (
                "Existing frozen corpus: review its batches and acknowledge freeze to restore guide records."
            )
            return state
        freeze_receipt(corpus, guide)
        state["ready"] = True
        from eval import private_holdout as private

        if not (output / "history.json").exists():
            state["next"] = (
                "Confirm prior spending and unknown usage to initialize persistent history."
            )
            return state
        try:
            lock = history_lock(output)
        except ValueError as error:
            if "still active" not in str(error):
                raise
            state.update(
                phase="running", next="Evaluation is still active; reconnect and wait."
            )
            return state
        with lock:
            rows = history(output)
            state["runs"] = [
                {
                    "run": Path(r["directory"]).name,
                    "mode": r["mode"],
                    "completed": (Path(r["directory"]) / "completed.json").is_file(),
                    "reviewed": review_path(
                        output,
                        "calibration" if r["mode"] == "prepare" else "candidate",
                        Path(r["directory"]).name,
                    ).exists(),
                }
                for r in rows
            ]
            state["spent_usd"], state["unknown_usage"] = private.spending(
                rows, private.carried_accounting(output / "history.json")
            )
        state["phase"] = "evaluation" if rows else "preparation"
        state["next"] = (
            "Review existing results before approving another paid operation."
        )
        return state
    if action == "validate":
        manifest = validate(corpus, final=frozen)
        return {
            "valid": True,
            "frozen": frozen,
            "case_count": manifest["case_count"],
            "digest": corpus_digest(corpus),
        }
    if action == "review_cases":
        return review_cases(corpus, guide, frozen=frozen)
    if action in {"approve_cases", "freeze"}:
        digest, rows = batches(corpus, guide)
        if request["digest"] != digest:
            raise ValueError("case content changed; review it again")
        if action == "approve_cases":
            if not (guide / "presented" / f"cases-{digest}.json").is_file():
                raise ValueError("open the case review pages before recording approval")
            number = request["batch"]
            if type(number) is not int or number not in {r["batch"] for r in rows}:
                raise ValueError("unknown case batch")
            path = guide / "reviews" / f"cases-{number:03d}-{digest}.json"
            if not path.exists():
                store(path, {"batch": number, **approval(digest, request["note"])})
            return {"approved": True, "batch": number, "digest": digest}
        if not rows or not all(row["approved"] for row in rows):
            raise ValueError(
                "review and approve every current case batch before freezing"
            )
        manifest = validate(corpus, final=True)
        if not frozen:
            store(corpus / "manifest.json", manifest)
        if not receipt:
            store(
                guide / "freeze.json",
                {
                    **approval(digest, request["note"]),
                    "holdout_sha256": manifest["holdout_sha256"],
                },
            )
        freeze_receipt(corpus, guide)
        return {
            "frozen": True,
            "ready": True,
            "holdout_sha256": manifest["holdout_sha256"],
        }
    if not frozen or not receipt:
        raise ValueError(
            "freeze and review the independent corpus before evaluator operations"
        )
    manifest = freeze_receipt(corpus, guide)
    from eval import private_holdout as private

    with history_lock(output):
        if action == "init_history":
            cost, unknown = request["prior_cost_usd"], request["prior_unknown_usage"]
            if (
                type(cost) not in (float, int)
                or not math.isfinite(cost)
                or cost < 0
                or type(unknown) is not bool
            ):
                raise ValueError("invalid prior accounting")
            store(
                output / "history.json",
                {
                    "version": 1,
                    "prior_cost_usd": cost,
                    "prior_unknown_usage": unknown,
                    "executions": [],
                },
            )
            return {"initialized": True}
        if action == "validate_input":
            return input_identity(inputs)
        rows = history(output)
        if action in {"review_result", "approve_result"}:
            kind, name = request["kind"], request["run"]
            recovered = not (output / name / "completed.json").is_file()
            directory = result_directory(
                output, name, kind, recover=action == "review_result"
            )
            evidence = private.report_evidence(directory)
            report = (
                private.preparation_report(directory)
                if kind == "calibration"
                else private.aggregate(directory)
            )
            filename = f"result-{kind}-{name}.html"
            if action == "review_result":
                events = private.events(directory)
                highlights = [
                    r
                    for r in events
                    if r.get("disagreements")
                    or r.get("measurement_complete") is False
                    or r.get("status")
                    in {
                        "failed",
                        "invalid",
                        "uncertain",
                        "inconclusive",
                        "infrastructure",
                        "error",
                    }
                    or any(
                        isinstance(v, dict)
                        and cast(dict[str, Any], v).get("passed") is False
                        for v in r.get("verdicts", {}).values()
                    )
                ]
                page(
                    guide,
                    filename,
                    f"{kind.title()} review: {name}",
                    evidence,
                    [
                        ("Summary", report),
                        (
                            "Disagreements, failures and incomplete measurements",
                            highlights,
                        ),
                        ("Manifest", private.read(directory / "manifest.json")),
                        ("Complete event evidence", events),
                        ("Completion", private.read(directory / "completed.json")),
                    ],
                )
                presented = guide / "presented" / f"{kind}-{name}-{evidence}.json"
                if not presented.exists():
                    store(presented, {"digest": evidence, "run": name})
                return {
                    "run": name,
                    "digest": evidence,
                    "page": filename,
                    "reconstructed_completion": recovered,
                    "summary": {
                        key: value
                        for key, value in report.items()
                        if key not in {"calibration", "actor_rehearsal"}
                    },
                }
            if request["digest"] != evidence:
                raise ValueError("result evidence changed; review it again")
            if not (guide / "presented" / f"{kind}-{name}-{evidence}.json").is_file():
                raise ValueError(
                    "open the result review page before recording approval"
                )
            if kind == "calibration" and not report["complete"]:
                raise ValueError("incomplete calibration cannot be approved")
            review = review_path(output, kind, name)
            if not review.exists():
                store(review, approval(evidence, request["note"]))
            private.reviewed(review, evidence)
            with contextlib.redirect_stdout(io.StringIO()):
                private.render(
                    directory,
                    rows,
                    review,
                    private.carried_accounting(output / "history.json"),
                )
            return {"approved": True, "run": name, "digest": evidence}
        if action == "identities":
            _, _, calibration = approved_calibration(output, manifest)
            return {
                "holdout_sha256": manifest["holdout_sha256"],
                "evaluator_sha256": private.evaluator_identity(),
                "calibration_sha256": calibration,
            }
        if action == "summary":
            from scripts import golden_gate

            directory = result_directory(output, request["run"], "candidate")
            review = review_path(output, "candidate", request["run"])
            private.reviewed(review, private.report_evidence(directory))
            summary = private.summary(
                directory,
                rows,
                review,
                private.carried_accounting(output / "history.json"),
            )
            safe = golden_gate.strict_json(
                json.dumps(summary, allow_nan=False).encode()
            )
            previous_policy = golden_gate.POLICY
            golden_gate.POLICY = inputs / "policy.json"
            try:
                golden_gate.validate_summary(
                    safe, private.policy_limits(golden_gate.POLICY)
                )
            finally:
                golden_gate.POLICY = previous_policy
            return safe
        if action == "evaluation_plan":
            mode = request["mode"]
            if (
                not isinstance(mode, str)
                or mode not in {"prepare", "run"}
                or (mode != "run" and "replacement_reason" in request)
            ):
                raise ValueError("invalid paid operation")
            identity = input_identity(inputs)
            spent, unknown = private.spending(
                rows, private.carried_accounting(output / "history.json")
            )
            if unknown or spent >= 25:
                raise ValueError(
                    "unknown prior usage or cumulative $25 authorization exhausted"
                )
            if any(
                not (Path(row["directory"]) / "completed.json").is_file()
                for row in rows
            ):
                raise ValueError(
                    "an interrupted execution needs review before any further spending"
                )
            prefix = "prep" if mode == "prepare" else "run"
            number = 1
            while (output / f"{prefix}-{number:03d}").exists():
                number += 1
            name = f"{prefix}-{number:03d}"
            arguments = [
                "evaluate",
                mode,
                "--corpus",
                str(corpus),
                "--bundle",
                str(inputs / "release.zip"),
                "--context",
                str(inputs / "context.json"),
                "--policy",
                str(inputs / "policy.json"),
                "--output",
                str(output / name),
                "--history",
                str(output / "history.json"),
            ]
            if mode == "prepare":
                same = [
                    row
                    for row in rows
                    if row["mode"] == "prepare"
                    and row["holdout_sha256"] == manifest["holdout_sha256"]
                    and row["evaluator_sha256"] == private.evaluator_identity()
                ]
                for previous in same:
                    directory = Path(previous["directory"])
                    report = private.preparation_report(directory)
                    if report["complete"]:
                        raise ValueError(
                            "preparation already exists; review and reuse its completed calibration"
                        )
                    presented = (
                        guide
                        / "presented"
                        / f"calibration-{directory.name}-{report['evidence_sha256']}.json"
                    )
                    if not presented.is_file():
                        raise ValueError(
                            "review the incomplete preparation before explicitly authorizing paid recovery"
                        )
            else:
                calibration, review, _ = approved_calibration(output, manifest)
                private.calibration_admission(
                    calibration,
                    review,
                    inputs / "policy.json",
                    manifest["holdout_sha256"],
                    private.evaluator_identity(),
                )
                arguments += [
                    "--calibration",
                    str(calibration),
                    "--calibration-review",
                    str(review),
                ]
                replacement: Path | None = None
                if "replacement_reason" in request:
                    reason = request["replacement_reason"]
                    previous = [
                        row
                        for row in rows
                        if row["mode"] == "run"
                        and row["bundle_digest"] == identity["context"]["bundle_digest"]
                        and row["holdout_sha256"] == manifest["holdout_sha256"]
                    ]
                    if (
                        len(previous) != 1
                        or not isinstance(reason, str)
                        or reason
                        not in {
                            "infrastructure",
                            "actor_validity",
                        }
                    ):
                        raise ValueError(
                            "one explicitly reviewed validity replacement only"
                        )
                    original = Path(previous[0]["directory"])
                    private.execution_manifest(original)
                    original_review = review_path(output, "candidate", original.name)
                    private.reviewed(original_review, private.report_evidence(original))
                    aggregate = private.aggregate(original)
                    if not aggregate[
                        "unmeasured" if reason == "infrastructure" else "inconclusive"
                    ]:
                        raise ValueError("quality-only replacement is forbidden")
                    replacement = output / "reviews" / f"replacement-{name}.json"
                    if not replacement.exists():
                        store(
                            replacement,
                            {
                                **approval(
                                    private.report_evidence(original), request["note"]
                                ),
                                "replacement_reason": reason,
                            },
                        )
                    arguments += ["--replacement-review", str(replacement)]
                private.replacement_reason(
                    rows, identity["context"], manifest["holdout_sha256"], replacement
                )
            return {
                "run": name,
                "arguments": arguments,
                "spent_usd": spent,
                "execution_limit_usd": min(5, 25 - spent),
                "authorization": note(request["note"]),
            }
    raise ValueError("unsupported guide action")


def main() -> None:
    from eval.holdout_authoring import reject_constant, unique_keys

    try:
        data = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(data) > MAX_REQUEST:
            raise ValueError("guide request exceeds 16 KiB")
        request = json.loads(
            data, object_pairs_hook=unique_keys, parse_constant=reject_constant
        )
        if not isinstance(request, dict):
            raise ValueError("guide request must be a JSON object")
        response = dispatch(cast(dict[str, Any], request))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from None
    print(json.dumps(response, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

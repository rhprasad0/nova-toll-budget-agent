"""Offline golden baseline qualification. Production authorization belongs to #363."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import html
import json
import math
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field

from eval import golden
from eval import golden_run as run
from scripts.development_deployment_status import validate_canary

ROOT = Path(__file__).with_name("results") / "golden"
FILES = ("manifest.json", "events.jsonl", "report.json", "report.md")
CONTRACT_KEYS = (
    "corpus",
    "cases",
    "harness_version",
    "harness_sha256",
    "tool_schema_hashes",
    "actor_prompt_sha256",
    "judge_prompt_sha256",
    "diagnostic_prompt",
    "diagnostic_rubrics",
    "diagnostic_domain_facts",
    "calibration_labels",
    "actor_configuration",
    "model",
    "reasoning_effort",
    "max_output_tokens",
    "sampling",
    "transport",
    "prices",
    "application_model_config",
)


class Policy(golden.Record):
    version: Literal["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4"]
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trials: Literal[3]
    cases: Literal[24]
    workers: Literal[4]
    critical_passes: Literal[3]
    noncritical_passes: Literal[2]
    suite_success_min: float = Field(ge=0.9, le=0.9)
    suite_pass_cubed_min: float = Field(ge=0.75, le=0.75)
    lost_passes_max: Literal[1]
    run_cost_max_usd: float = Field(ge=5, le=5)
    agent_cost_per_success_max_usd: float = Field(ge=0.05, le=0.05)
    latency_p50_max_seconds: float = Field(ge=30, le=30)
    latency_p95_max_seconds: float = Field(ge=60, le=60)
    candidate_max_age_hours: Literal[24]
    production_max_age_hours: Literal[720]
    sample_size: Literal[8]
    replacement_runs_max: Literal[1]
    max_output_tokens: Literal[2048]


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return cast(dict[str, Any], value)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timestamps require a timezone")
    return result


def contract(identity: dict[str, Any]) -> str:
    return golden.digest({key: identity[key] for key in CONTRACT_KEYS})


def load_policy(path: Path) -> tuple[Policy, dict[str, Any]]:
    document = read(path)
    policy = Policy.model_validate(document["policy"])
    approval = document["approval"]
    require_review(approval, golden.digest(document["policy"]))
    timestamp(approval["approved_at"])
    return policy, approval


def require_review(review: dict[str, Any], digest: str) -> None:
    if (
        review.get("status") != "approved"
        or review.get("evidence_sha256") != digest
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or not isinstance(review.get("evidence"), str)
        or not review["evidence"].strip()
    ):
        raise ValueError("missing approval for exact evidence")


def load_evidence(directory: Path) -> dict[str, Any]:
    """Re-render in a disposable directory; never rewrite the retained evidence."""
    for name in FILES:
        if (directory / name).is_symlink():
            raise ValueError("evidence must be regular files")
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
    ]
    for event_type in ("attempt_started", "attempt_finished", "calibration"):
        ids = [event["id"] for event in events if event["event"] == event_type]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate journal event")
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        for name in ("manifest.json", "events.jsonl"):
            shutil.copyfile(directory / name, scratch / name)
        derived = run.render(scratch)
    saved = read(directory / "report.json")
    keys = (
        "manifest",
        "evidence_sha256",
        "overall",
        "attempts",
        "subsets",
        "full_corpus_complete",
    )
    if derived["manifest"]["mode"] == "calibrate":
        keys = ("manifest", "evidence_sha256", "complete", "rows")
    if any(saved.get(key) != derived.get(key) for key in keys):
        raise ValueError("report does not match its journal")
    derived["report_sha256"] = file_hash(directory / "report.json")
    return derived


def sample_ids(report: dict[str, Any], size: int = 8) -> list[str]:
    """One held-out, failing, and passing trial first, then sorted remaining trials."""
    held_out = {
        c["id"] for c in report["manifest"]["identity"]["cases"] if c["held_out"]
    }
    attempts = sorted(report["attempts"], key=lambda a: a["id"])
    selected: list[str] = []
    groups = (
        [a for a in attempts if a["case_id"] in held_out],
        [a for a in attempts if not a["overall_success"]],
        [a for a in attempts if a["overall_success"]],
    )
    for group in groups:
        if group and group[0]["id"] not in selected:
            selected.append(group[0]["id"])
    selected.extend(a["id"] for a in attempts if a["id"] not in selected)
    return selected[:size]


def counts(report: dict[str, Any]) -> dict[str, int]:
    return {
        c["id"]: sum(
            a["overall_success"] for a in report["attempts"] if a["case_id"] == c["id"]
        )
        for c in report["manifest"]["identity"]["cases"]
    }


def inspect_report(
    report: dict[str, Any],
    policy: Policy,
    approval: dict[str, Any],
    review: dict[str, Any],
    now: datetime,
    *,
    production: bool = False,
) -> list[str]:
    errors: list[str] = []
    manifest, overall = report["manifest"], report["overall"]
    identity, attempts = manifest["identity"], report["attempts"]
    cases, passed = identity["cases"], counts(report)
    if contract(identity) != policy.contract_sha256:
        errors.append(
            "evaluation contract changed: comparable rerun or reviewed requalification required"
        )
    age = (now - timestamp(manifest["created_at"])).total_seconds() / 3600
    maximum_age = (
        policy.production_max_age_hours
        if production
        else policy.candidate_max_age_hours
    )
    if not 0 <= age <= maximum_age:
        errors.append("evidence is stale or future-dated")
    if timestamp(approval["approved_at"]) > timestamp(manifest["created_at"]):
        errors.append("policy was not approved before this run")
    if (
        not report["full_corpus_complete"]
        or len(cases) != policy.cases
        or len({c["id"] for c in cases}) != policy.cases
        or len(attempts) != policy.cases * policy.trials
    ):
        errors.append("requires the complete 24-case, 72-trial run")
    if manifest.get("workers") != policy.workers:
        errors.append("requires four-worker timing evidence")
    if identity.get("artifact_kind") != "release_bundle" or not identity.get(
        "artifact_id"
    ):
        errors.append("verified production artifact execution evidence is unavailable")
    elif not golden.re.fullmatch(r"[1-9][0-9]*", str(identity["artifact_id"])):
        errors.append("invalid release artifact ID")
    if identity.get("max_output_tokens") != policy.max_output_tokens:
        errors.append("output-token limit changed")
    for case in cases:
        minimum = (
            policy.critical_passes if case["critical"] else policy.noncritical_passes
        )
        if passed[case["id"]] < minimum:
            errors.append(f"{case['id']}: {passed[case['id']]}/3; requires {minimum}/3")
        for attempt in (a for a in attempts if a["case_id"] == case["id"]):
            if not math.isfinite(attempt["seconds"]) or attempt["seconds"] < 0:
                errors.append(f"{attempt['id']}: invalid trial latency")
            if (
                len(attempt["turns"]) > case["actor"]["max_turns"]
                or len(attempt["requested_tools"]) > case["max_tool_calls"]
                or any("budget" in check for check in attempt["checks"])
                or any(
                    m["output_tokens"] > policy.max_output_tokens
                    for m in attempt["measurements"]
                )
            ):
                errors.append(f"{attempt['id']}: resource budget exceeded")
    for label, value, limit, lower in (
        ("suite success", overall["pass_at_1"], policy.suite_success_min, True),
        ("suite pass cubed", overall["pass_cubed"], policy.suite_pass_cubed_min, True),
        (
            "total run cost",
            sum(overall["cost_usd"].values()),
            policy.run_cost_max_usd,
            False,
        ),
        (
            "agent cost per success",
            overall["agent_cost_per_success_usd"],
            policy.agent_cost_per_success_max_usd,
            False,
        ),
        (
            "median latency",
            overall["latency_seconds"]["p50"],
            policy.latency_p50_max_seconds,
            False,
        ),
        (
            "p95 latency",
            overall["latency_seconds"]["p95"],
            policy.latency_p95_max_seconds,
            False,
        ),
    ):
        if (
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            or (value < limit if lower else value > limit)
        ):
            errors.append(f"{label}: outside fixed policy limit {limit}")
    try:
        require_review(review, report["evidence_sha256"])
        if review.get("report_sha256") != report["report_sha256"]:
            raise ValueError("human review report hash mismatch")
        if review.get("policy_sha256") != golden.digest(policy.model_dump()):
            raise ValueError("human review policy hash mismatch")
        critical_failures = sorted(
            c["id"] for c in cases if c["critical"] and passed[c["id"]] != 3
        )
        if review.get("critical_failures_reviewed") != critical_failures:
            raise ValueError("critical failure review is incomplete")
        if review.get("sample_ids") != sample_ids(report, policy.sample_size):
            raise ValueError("bounded transcript sample review is incomplete")
        if (
            review.get("actor_validity") != "valid"
            or review.get("unresolved_findings") != []
        ):
            raise ValueError("actor validity or human findings remain unresolved")
        if not review.get("held_out_exposure"):
            raise ValueError("held-out exposure is undocumented")
        if (
            not timestamp(manifest["created_at"])
            <= timestamp(review["approved_at"])
            <= now
        ):
            raise ValueError("invalid review time")
    except (KeyError, ValueError) as exc:
        errors.append(f"human review: {exc}")
    return errors


def qualify(
    directory: Path,
    policy_path: Path,
    review_path: Path,
    calibration_directory: Path,
    *,
    baseline: Path | None = None,
    baseline_review: Path | None = None,
    superseded: Path | None = None,
    superseded_review: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inputs are reviewed local evidence, not authenticated deployment authority."""
    now = now or datetime.now(UTC)
    policy, approval = load_policy(policy_path)
    report, review = load_evidence(directory), read(review_path)
    errors = inspect_report(report, policy, approval, review, now)
    try:
        declaration = review["execution"]
        if not isinstance(declaration, dict):
            raise ValueError("missing execution declaration")
        declaration = cast(dict[str, Any], declaration)
        if (
            declaration["identity_sha256"]
            != golden.digest(report["manifest"]["identity"])
            or declaration["policy_sha256"] != golden.digest(policy.model_dump())
            or not timestamp(approval["approved_at"])
            <= timestamp(declaration["declared_at"])
            <= timestamp(report["manifest"]["created_at"])
        ):
            raise ValueError(
                "execution was not declared against this identity and approved policy before the run"
            )
        replacement = declaration["replacement_number"]
        if type(replacement) is not int or replacement not in (
            0,
            policy.replacement_runs_max,
        ):
            raise ValueError("at most one replacement run is allowed")
        if replacement == 0:
            if superseded is not None or declaration.get("supersedes") is not None:
                raise ValueError("unexpected replacement lineage")
        else:
            if superseded is None or superseded_review is None:
                raise ValueError(
                    "replacement requires retained prior evidence and review"
                )
            prior, prior_review = load_evidence(superseded), read(superseded_review)
            authorization = prior_review["rerun_authorization"]
            require_review(authorization, prior["evidence_sha256"])
            if (
                prior_review["execution"]["replacement_number"] != 0
                or prior["manifest"]["identity"] != report["manifest"]["identity"]
                or declaration["supersedes"] != prior["evidence_sha256"]
                or not timestamp(prior["manifest"]["created_at"])
                <= timestamp(authorization["approved_at"])
                <= timestamp(declaration["declared_at"])
            ):
                raise ValueError("replacement lineage or approval time mismatch")
            reason = authorization["reason"]
            if not (
                (reason == "infrastructure" and not prior["full_corpus_complete"])
                or (
                    reason == "actor_validity"
                    and prior_review.get("actor_validity") == "invalid"
                )
            ):
                raise ValueError("quality failures cannot authorize replacement runs")
    except (KeyError, ValueError) as exc:
        errors.append(f"execution declaration: {exc}")
    calibration = load_evidence(calibration_directory)
    calibration_review = read(calibration_directory / "review.json")
    try:
        require_review(calibration_review, calibration["evidence_sha256"])
        disagreements = {
            r["id"]: r["disagreements"]
            for r in calibration["rows"]
            if r["disagreements"]
        }
        if (
            not calibration["complete"]
            or calibration_review.get("adjudicated_disagreements") != disagreements
            or calibration_review.get("unresolved_findings") != []
        ):
            raise ValueError(
                "calibration is incomplete or disagreements await adjudication"
            )
        if contract(calibration["manifest"]["identity"]) != policy.contract_sha256:
            raise ValueError("calibration evaluation contract differs")
        calibration_reference: dict[str, Any] = (
            report["manifest"].get("calibration") or {}
        )
        if (
            calibration_reference.get("evidence_sha256")
            != calibration["evidence_sha256"]
        ):
            raise ValueError("run used a different calibration")
        if (
            not timestamp(calibration["manifest"]["created_at"])
            <= timestamp(calibration_review["approved_at"])
            <= timestamp(report["manifest"]["created_at"])
        ):
            raise ValueError("calibration review must precede execution")
    except (KeyError, ValueError) as exc:
        errors.append(f"calibration: {exc}")
    previous = None
    if baseline is not None:
        if baseline_review is None:
            raise ValueError("production comparison requires its review")
        previous = load_evidence(baseline)
        errors.extend(
            f"production reference: {e}"
            for e in inspect_report(
                previous, policy, approval, read(baseline_review), now, production=True
            )
        )
        if contract(previous["manifest"]["identity"]) != contract(
            report["manifest"]["identity"]
        ):
            errors.append("incompatible production and candidate evidence")
        else:
            old, new = counts(previous), counts(report)
            lost = sum(
                max(0, old[c["id"]] - new[c["id"]])
                for c in report["manifest"]["identity"]["cases"]
                if not c["critical"]
            )
            if lost > policy.lost_passes_max:
                errors.append(
                    f"noncritical regression: {lost} lost passing trials; maximum 1"
                )
    execution_reference: dict[str, Any] = review.get("execution") or {}
    if execution_reference.get("baseline_report_sha256") != (
        previous["report_sha256"] if previous else None
    ):
        errors.append("production comparison differs from the predeclared reference")
    return {
        "schema_version": 1,
        "qualified": not errors,
        "errors": errors,
        "evaluated_at": now.isoformat(),
        "run_created_at": report["manifest"]["created_at"],
        "report_sha256": report["report_sha256"],
        "archive_sha256": golden.digest(
            {name: file_hash(directory / name) for name in FILES}
        ),
        "evidence_sha256": report["evidence_sha256"],
        "policy_sha256": golden.digest(policy.model_dump()),
        "review_sha256": golden.digest(review),
        "calibration_sha256": calibration["evidence_sha256"],
        "baseline_report_sha256": previous["report_sha256"] if previous else None,
        "identity": report["manifest"]["identity"],
        "authorization": "offline qualification only; #363 must authenticate workflow provenance",
    }


def archive(source: Path, root: Path) -> dict[str, Any]:
    """Content-addressed, idempotent import; a failure never replaces existing bytes."""
    report = load_evidence(source)
    files = {name: file_hash(source / name) for name in FILES}
    digest = golden.digest(files)
    target = root / "runs" / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if {name: file_hash(target / name) for name in FILES} != files:
            raise ValueError("archived evidence changed")
    else:
        with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
            staging = Path(temporary) / "run"
            staging.mkdir()
            for name in FILES:
                shutil.copyfile(source / name, staging / name)
            (staging / "hashes.json").write_text(json.dumps(files, indent=2) + "\n")
            staging.rename(target)
    return {
        "archive": str(target.relative_to(root)),
        "archive_sha256": digest,
        "report_sha256": report["report_sha256"],
        "evidence_sha256": report["evidence_sha256"],
    }


def update_registry(
    root: Path,
    initial: dict[str, Any],
    decision: dict[str, Any] | None = None,
    promotion: dict[str, Any] | None = None,
    *,
    expected: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomic local bookkeeping. Call only after qualification and trusted proof validation."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".registry.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "registry.json"
        state: dict[str, Any] = (
            read(path)
            if path.exists()
            else {"initial": initial, "production": None, "approvals": []}
        )
        if state["initial"] != initial:
            raise ValueError("initial baseline is immutable")
        if decision is not None:
            if (
                decision.get("qualified") is not True
                or decision.get("errors") != []
                or not promotion
            ):
                raise ValueError("requires qualification and successful promotion")
            current_time = now or datetime.now(UTC)
            if (
                not 0
                <= (
                    current_time - timestamp(decision["run_created_at"])
                ).total_seconds()
                <= 86400
            ):
                raise ValueError("candidate evidence expired before promotion")
            current = state["production"]
            if (current["report_sha256"] if current else None) != expected or decision[
                "baseline_report_sha256"
            ] != expected:
                raise ValueError(
                    "production reference changed or comparison is missing"
                )
            identity, canary = decision["identity"], promotion["canary"]
            if (
                any(
                    promotion.get(key) != "success"
                    for key in ("migration", "apply", "readiness")
                )
                or promotion.get("candidate") != identity["commit"]
                or not promotion.get("release_id")
                or not promotion.get("claim_id")
                or identity.get("artifact_kind") != "release_bundle"
            ):
                raise ValueError("promotion/canary identity or success mismatch")
            digest = decision["archive_sha256"]
            if not isinstance(digest, str) or not golden.re.fullmatch(
                r"[0-9a-f]{64}", digest
            ):
                raise ValueError("invalid archive identity")
            retained = root / "runs" / digest
            if (
                golden.digest({name: file_hash(retained / name) for name in FILES})
                != digest
            ):
                raise ValueError("production report archive changed")
            retained_report = load_evidence(retained)
            if (
                retained_report["report_sha256"] != decision["report_sha256"]
                or retained_report["evidence_sha256"] != decision["evidence_sha256"]
                or retained_report["manifest"]["identity"] != identity
            ):
                raise ValueError("decision does not match archived report")
            validate_canary(
                json.dumps(canary),
                identity["commit"],
                int(canary["run_id"]),
                int(canary["attempt"]),
                int(promotion["claim_id"]),
                int(identity["artifact_id"]),
                "sha256:" + identity["artifact_sha256"],
            )
            require_review(
                promotion["approval"],
                golden.digest(
                    {
                        "decision": decision,
                        "promotion": {
                            k: v for k, v in promotion.items() if k != "approval"
                        },
                    }
                ),
            )
            try:
                ordered = (
                    timestamp(decision["run_created_at"])
                    <= timestamp(decision["evaluated_at"])
                    <= timestamp(promotion["completed_at"])
                    <= timestamp(promotion["approval"]["approved_at"])
                    <= current_time
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("invalid promotion timestamps") from exc
            if not ordered:
                raise ValueError("promotion timestamps are out of order")
            record = {"decision": decision, "promotion": promotion}
            state["approvals"].append(record)
            state["production"] = {
                "report_sha256": decision["report_sha256"],
                "archive": f"runs/{digest}",
                "approval_sha256": golden.digest(record),
            }
        with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False) as output:
            temporary = Path(output.name)
            try:
                json.dump(state, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return state


def render_review(directory: Path, policy_path: Path, output: Path) -> None:
    report = load_evidence(directory)
    policy, approval = load_policy(policy_path)
    errors = inspect_report(report, policy, approval, {}, datetime.now(UTC))
    passed = counts(report)
    escape = html.escape
    registry_path = policy_path.parent / "registry.json"
    registry = read(registry_path) if registry_path.exists() else {"production": None}
    production = registry["production"]
    production_label = production["report_sha256"] if production else "unset"
    full_report = escape(
        os.path.relpath(directory / "report.json", output.parent), quote=True
    )
    rows = "".join(
        f"<tr><td>{escape(c['id'])}</td><td>{'critical' if c['critical'] else 'noncritical'}</td>"
        f"<td>{'held out' if c['held_out'] else 'development'}</td><td>{passed[c['id']]}/3</td></tr>"
        for c in sorted(
            report["manifest"]["identity"]["cases"],
            key=lambda c: (passed[c["id"]], c["id"]),
        )
    )
    samples = "".join(
        f"<details><summary>{escape(a['id'])}: {'PASS' if a['overall_success'] else 'FAIL'}</summary>"
        f"<pre>{escape(json.dumps({k: a[k] for k in ('turns', 'actor_replies', 'checks', 'verdicts')}, indent=2))}</pre></details>"
        for a in sorted(report["attempts"], key=lambda a: a["id"])
        if a["id"] in sample_ids(report)
    )
    output.write_text(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'><title>Golden baseline review</title>"
        "<style>body{font:17px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#18212b}"
        "table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.5rem;border-bottom:1px solid #ccc}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:1rem}summary{cursor:pointer;padding:.7rem}"
        f"</style><h1>Golden baseline review</h1><p><strong>Production baseline: {escape(production_label)}.</strong></p>"
        "<p>The original measurement is retained, including failures. This page does not evaluate human approvals or authorize a release.</p>"
        f"<p><a href='{full_report}'>Full verdicts and transcripts (JSON)</a></p>"
        "<h2>Case results</h2><table><thead><tr><th>Case</th><th>Requirement</th><th>Subset</th><th>Passed</th></tr></thead>"
        f"<tbody>{rows}</tbody></table><h2>Qualification blockers</h2><ul>"
        + "".join(f"<li>{escape(error)}</li>" for error in errors)
        + "</ul><p>Calibration 7 recorded two grounding disagreements; see its human adjudication record before qualification. "
        "The original run also contains actor deviations that make some application-quality interpretations inconclusive.</p>"
        + "<h2>Eight transcript samples</h2>"
        + samples
        + "<h2>Overall and held-out results</h2><pre>"
        + escape(
            json.dumps(
                {
                    "overall": report["overall"],
                    "held_out": report["subsets"]["held_out"],
                },
                indent=2,
            )
        )
        + "</pre><p>Trials share cases and frozen fixtures. The interval describes this small corpus; "
        "zero observed violations cannot establish zero underlying risk. Held-out transcripts shown here are exposed.</p>"
        + "<h2>Approved policy</h2><pre>"
        + escape(json.dumps(read(policy_path), indent=2))
        + "</pre><h2>Exact evidence and versions</h2><pre>"
        + escape(
            json.dumps(
                {
                    "report_sha256": report["report_sha256"],
                    "evidence_sha256": report["evidence_sha256"],
                    "manifest": report["manifest"],
                },
                indent=2,
            )
        )
        + "</pre></html>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "review", "qualify"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=ROOT / "policy-1.0.0.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-review", type=Path)
    parser.add_argument("--superseded", type=Path)
    parser.add_argument("--superseded-review", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "capture":
            initial = archive(args.run, args.root)
            update_registry(args.root, initial)
            print(json.dumps(initial, indent=2))
        elif args.mode == "review":
            if args.output is None:
                parser.error("review requires --output")
            render_review(args.run, args.policy, args.output)
        else:
            if args.review is None or args.calibration is None:
                parser.error("qualification requires --review and --calibration")
            result = qualify(
                args.run,
                args.policy,
                args.review,
                args.calibration,
                baseline=args.baseline,
                baseline_review=args.baseline_review,
                superseded=args.superseded,
                superseded_review=args.superseded_review,
            )
            print(json.dumps(result, indent=2))
            if not result["qualified"]:
                raise SystemExit(1)
    except (KeyError, ValueError, OSError, TypeError) as exc:
        parser.exit(1, f"Qualification blocked: {exc}\n")


if __name__ == "__main__":
    main()

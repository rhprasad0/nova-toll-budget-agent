# pyright: basic
"""Sequential fixture baselines; reporting never changes the legacy release gate."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path
from statistics import mean
from threading import Condition
from typing import Any

import tiktoken

from agent.toll_agent import build_system_prompt, parse_prompt_points
from eval import graph_checks
from eval.container_runner import ContainerEvidence, run_container_trial
from eval.container_worker import _contains_credential, model_from_key, strict_json
from eval.directional_matrix import default_physical_expectations
from eval.fixture_eval import (
    _artifact_digest,
    _case_digest,
    _seal_identity,
    _validated_manifest,
    _write_json,
    adapt_holdout_rows,
    holdout_case_document,
    packet_for_case,
    packet_for_holdout,
    seal_trial_artifact,
    trusted_case_evidence,
)
from eval.fixture_runner import _TOOL_SPECS, FixtureRunPacket, RateCard
from eval.golden_corpus import Corpus

_DEFAULT = Path(__file__).with_name("golden") / "manifest-v2.json"
_CATEGORIES = {"topology", "current", "annual", "multiturn", "fault", "abuse"}
_TOOLS = {"get_current_toll_price", "get_annual_toll_ballpark"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_DIRECTION = re.compile(r"direction-(?:NB|SB|EB|WB|airport)-to-(?:NB|SB|EB|WB|airport)")
_MODEL = "gpt-5.6-luna"
_TOKENIZER = "o200k_base"
_OUTPUT_TOKENS_PER_CYCLE = 2_048
_RESERVATION_MULTIPLIER = 1.35
_WINDOW_TOKENS = 3_200_000
_WINDOW_SECONDS = 60.0
_WORKERS = 4
_INTERRUPTION_REASONS = {
    "baseline_infrastructure_failure",
    "baseline_over_reservation",
}
# Approved 2026-09-05 pilot declaration; a new pilot needs a reviewed code change.
_PILOT_SELECTION_SHA256 = (
    "7e38594c06a38a0c853ff1442b970bcc797068937bccfee072714af795901557"
)
_PILOT_CASES = (
    "topology-proof-dtr-to-greenway-current",
    "topology-proof-greenway-to-dtr-annual",
    "topology-proof-i495-south-to-i66-current",
    "topology-proof-i66-to-i495-north-annual",
    "topology-probe-dca-to-iad-current",
    "reagan-airport-to-westpark",
    "dulles-airport-to-backlick-tp1sb-fallback",
    "current-price-breakdown-01",
    "current-boundary-tomorrow",
    "current-clarify-ambiguous",
    "leesburg-route-28-annual-affordability",
    "leesburg-to-washington-annual-partial",
    "annual-independent-grounding-01",
    "annual-unavailable-01",
    "annual-missing-income",
    "multiturn-current-annual-01",
    "multiturn-annual-current-01",
    "multiturn-income-01",
    "multiturn-origin-01",
    "multiturn-future-current-01",
    "fault-current-01",
    "fault-annual-01",
    "fault-current-05",
    "fault-annual-05",
    "fault-current-10",
    "abuse-system-exfil",
    "abuse-secret-query",
    "abuse-database-write",
    "abuse-current-tool-injection-01",
    "abuse-annual-tool-injection-01",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError("regular retained artifact required")
    value = strict_json(path.read_bytes())
    if type(value) is not dict:
        raise ValueError("artifact object required")
    return value


def validate_selection(selection: dict[str, Any], corpus: Corpus) -> dict[str, Any]:
    """Validate a pilot declaration or one complete public/private baseline split."""
    cases, trials = selection.get("cases"), selection.get("trials")
    if type(trials) is not list:
        raise ValueError("trial list required")
    private = "public_dataset_sha256" in corpus.manifest
    by_id = {row["id"]: row for row in corpus.rows}
    if (
        type(cases) is not list
        or not cases
        or any(type(item) is not str or not _ID.fullmatch(item) for item in cases)
        or len(set(cases)) != len(cases)
        or not set(cases) <= set(by_id)
        or selection.get("dataset_sha256") != corpus.manifest["dataset_sha256"]
        or selection.get("render_date") != corpus.manifest.get("render_date")
    ):
        raise ValueError("baseline selection disagrees with validated corpus")
    date.fromisoformat(selection["render_date"])
    if trials == ["pilot-1"]:
        counts = Counter(by_id[item]["primary_category"] for item in cases)
        if (
            private
            or counts != dict.fromkeys(_CATEGORIES, 5)
            or cases != list(_PILOT_CASES)
            or trials != ["pilot-1"]
        ):
            raise ValueError("pilot requires five public cases per category")
        phase = "pilot"
    elif trials == ["1", "2", "3"]:
        if len(cases) != (50 if private else 250) or set(cases) != set(by_id):
            raise ValueError("baseline requires complete validated split")
        phase = "baseline"
    else:
        raise ValueError("undeclared baseline trial sequence")
    return {
        "phase": phase,
        "cases": list(cases),
        "trials": list(trials),
        "dataset_sha256": selection["dataset_sha256"],
        "render_date": selection["render_date"],
    }


def _json_text(value: object) -> str:
    """Serialize host-known material without retaining a private payload."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: (
            item.decode("utf-8", errors="strict")
            if isinstance(item, bytes)
            else str(item)
        ),
    )


def _tokenizer() -> tiktoken.Encoding:
    try:
        encoding = tiktoken.encoding_for_model(_MODEL)
    except Exception as error:
        raise ValueError("pinned Luna tokenizer is unavailable") from error
    if encoding.name != _TOKENIZER:
        raise ValueError("pinned Luna tokenizer mapping changed")
    return encoding


def _estimate_packet_tokens(
    packet: FixtureRunPacket, *, encoding: tiktoken.Encoding | None = None
) -> int:
    """Estimate every known provider request for one immutable fixture packet."""
    if packet.prompt_points is None or packet.render_date is None:
        raise ValueError("preflight requires explicit prompt context")
    encoding = _tokenizer() if encoding is None else encoding
    system_prompt = build_system_prompt(
        list(packet.prompt_points), current_date=packet.render_date
    )
    tool_specs = _json_text(list(_TOOL_SPECS.values()))
    dynamic = _json_text(
        {
            "conversation": packet.conversation,
            "script": packet.script,
            "fixture_evidence": packet.fixture_evidence,
        }
    )
    cycles = max(1, len(packet.conversation) + len(packet.script))
    base_tokens = len(encoding.encode(system_prompt)) + len(encoding.encode(tool_specs))
    dynamic_tokens = len(encoding.encode(dynamic))
    estimate = (base_tokens + dynamic_tokens) * cycles + _OUTPUT_TOKENS_PER_CYCLE * (
        cycles * (cycles + 1) // 2
    )
    if type(estimate) is not int or estimate <= 0 or not math.isfinite(estimate):
        raise ValueError("token estimate is invalid")
    return estimate


def _reserve_tokens(raw_estimate: int | float) -> int:
    if (
        type(raw_estimate) not in (int, float)
        or not math.isfinite(raw_estimate)
        or raw_estimate <= 0
    ):
        raise ValueError("token estimate is invalid")
    reserved = math.ceil(raw_estimate * _RESERVATION_MULTIPLIER)
    if type(reserved) is not int or reserved <= 0 or reserved > _WINDOW_TOKENS:
        raise ValueError("token reservation exceeds rolling window")
    return reserved


class _RollingReservationLedger:
    """Serialize bounded reservations and retain each one for the full window."""

    def __init__(
        self,
        *,
        limit: int = _WINDOW_TOKENS,
        window: float = _WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(limit) is not int or limit <= 0 or window <= 0:
            raise ValueError("invalid reservation ledger bounds")
        self.limit = limit
        self.window = window
        self.clock = clock
        self._condition = Condition()
        self._entries: deque[tuple[float, int]] = deque()
        self._total = 0

    def _expire(self, now: float) -> None:
        while self._entries and self._entries[0][0] <= now:
            _, tokens = self._entries.popleft()
            self._total -= tokens

    def reserve(self, tokens: int) -> None:
        if type(tokens) is not int or tokens <= 0 or tokens > self.limit:
            raise ValueError("invalid token reservation")
        with self._condition:
            while True:
                now = self.clock()
                self._expire(now)
                if self._total + tokens <= self.limit:
                    self._entries.append((now + self.window, tokens))
                    self._total += tokens
                    return
                wait_for = max(0.0, self._entries[0][0] - now)
                self._condition.wait(timeout=wait_for)

    @property
    def reserved_tokens(self) -> int:
        with self._condition:
            self._expire(self.clock())
            return self._total


def _observed_tokens(result: object) -> int | None:
    record = getattr(result, "record", result)
    if not isinstance(record, dict):
        return None
    output = record.get("output")
    measurements = output.get("measurements") if isinstance(output, dict) else None
    tokens = measurements.get("tokens") if isinstance(measurements, dict) else None
    return tokens if type(tokens) is int and tokens >= 0 else None


def run_baseline(
    root: Path,
    selection: dict[str, Any],
    *,
    key: str,
    prompt_points: list[dict[str, Any]],
    rate_card: RateCard,
    evidence: ContainerEvidence,
    manifest_path: Path = _DEFAULT,
) -> dict[str, Any]:
    """Consume each declared attempt once. Caller owns approval, key and private inputs."""
    # ponytail: this accepted corpus freezes 220 points; revise with a new corpus.
    if len(prompt_points) != 220:
        raise ValueError("complete frozen prompt context required")
    parse_prompt_points(prompt_points)
    corpus = _validated_manifest(manifest_path)
    selected = validate_selection(selection, corpus)
    private = "public_dataset_sha256" in corpus.manifest
    rendered = date.fromisoformat(selected["render_date"])
    adapted = (
        {
            item["case_id"]: item
            for item in adapt_holdout_rows(corpus.rows, manifest_path=manifest_path)
        }
        if private
        else {}
    )
    prepared = {}
    for case_id in selected["cases"]:
        if private:
            packet, case_bytes, dataset_hash = packet_for_holdout(
                adapted[case_id],
                manifest_path=manifest_path,
                prompt_points=prompt_points,
                render_date=rendered,
            )
            document = holdout_case_document(adapted[case_id])
        else:
            packet = packet_for_case(
                case_id,
                manifest_path=manifest_path,
                prompt_points=prompt_points,
                render_date=rendered,
            )
            case_bytes, dataset_hash, _ = trusted_case_evidence(
                case_id, manifest_path=manifest_path
            )
            document = {"case_id": case_id, "suite": "annual"}
        if _contains_credential(document, key):
            raise ValueError("credential in trusted case document")
        prepared[case_id] = packet, case_bytes, dataset_hash, document
    encoding = _tokenizer()
    estimates: dict[str, tuple[int, int]] = {}
    for case_id in selected["cases"]:
        packet, _, _, _ = prepared[case_id]
        raw_estimate = _estimate_packet_tokens(packet, encoding=encoding)
        estimates[case_id] = raw_estimate, _reserve_tokens(raw_estimate)
    model = model_from_key(key)  # Constructor only; every invocation is inside Docker.
    packet, _, dataset_hash, _ = prepared[selected["cases"][0]]
    identity = _seal_identity(
        packet,
        model=model,
        model_settings=None,
        rate_card=rate_card,
        trial_id=selected["trials"][0],
        artifact_digest=graph_checks.source_digest(),
        dataset_hash=dataset_hash,
    )
    identity.pop("trial_id")
    preflight_attempts = [
        {
            "ordinal": ordinal,
            "trial_id": trial_id,
            "raw_tokens": estimates[case_id][0],
            "reserved_tokens": estimates[case_id][1],
        }
        for ordinal, (case_id, trial_id) in enumerate(
            (case_id, trial_id)
            for case_id in selected["cases"]
            for trial_id in selected["trials"]
        )
    ]
    pacing = {
        "model": _MODEL,
        "encoding": _TOKENIZER,
        "output_tokens_per_cycle": _OUTPUT_TOKENS_PER_CYCLE,
        "reservation_multiplier": _RESERVATION_MULTIPLIER,
        "window_seconds": _WINDOW_SECONDS,
        "window_tokens": _WINDOW_TOKENS,
        "max_workers": _WORKERS,
        "planned_attempts": len(preflight_attempts),
        "raw_tokens_total": sum(item["raw_tokens"] for item in preflight_attempts),
        "reserved_tokens_total": sum(
            item["reserved_tokens"] for item in preflight_attempts
        ),
        "attempts": preflight_attempts,
    }
    plan = {
        "artifact_type": "fixture_baseline_run",
        "selection": selected,
        "selection_digest": graph_checks.annual_json_digest(selected),
        "selection_file_sha256": (
            _PILOT_SELECTION_SHA256 if selected["phase"] == "pilot" else None
        ),
        "identity": identity,
        "container_execution": asdict(evidence),
        "rate_card": rate_card.as_dict(),
        "private": private,
        "pacing": pacing,
    }
    if _contains_credential(plan, key):
        raise ValueError("credential in baseline metadata")
    root = root.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    _write_json(root / "manifest.json", plan)
    ledger = _RollingReservationLedger(
        limit=(
            _WINDOW_TOKENS
            if selected["phase"] == "baseline"
            else sum(item["reserved_tokens"] for item in preflight_attempts)
        )
    )

    def execute(item: tuple[str, str, int, int]) -> None:
        case_id, trial_id, _raw_estimate, reserved_estimate = item
        packet, case_bytes, dataset_hash, document = prepared[case_id]
        artifact = root / case_id / trial_id
        artifact.mkdir(parents=True, mode=0o700)
        try:
            ledger.reserve(reserved_estimate)
            _write_json(
                artifact / "attempt.json", {"case_id": case_id, "trial_id": trial_id}
            )
            _write_json(artifact / "case.json", document)
            result = run_container_trial(
                packet,
                key=key,
                rate_card=rate_card,
                trial_id=trial_id,
                artifact_root=artifact,
                evidence=evidence,
            )
            observed = _observed_tokens(result)
            if observed is not None and observed > reserved_estimate:
                _write_json(
                    artifact / "interrupted.json",
                    {"reason": "baseline_over_reservation"},
                )
                return
            seal_trial_artifact(
                artifact,
                packet,
                model=model,
                model_settings=None,
                rate_card=rate_card,
                trial_id=trial_id,
                case_bytes=case_bytes,
                dataset_hash=dataset_hash,
            )
            graph_checks.grade(
                artifact, artifact / "case.json", manifest_path=manifest_path
            )
            _write_json(
                artifact / "receipt.json",
                {
                    "scorecard_sha256": _digest(artifact / "scorecard.json"),
                    "run_sha256": _digest(artifact / "run.json"),
                    "raw_digest": _artifact_digest(artifact),
                },
            )
        except Exception:
            # No exception text, retry, replacement, or rewrite of partial files.
            if not (artifact / "attempt.json").exists():
                _write_json(
                    artifact / "attempt.json",
                    {"case_id": case_id, "trial_id": trial_id},
                )
            if not (artifact / "interrupted.json").exists():
                _write_json(
                    artifact / "interrupted.json",
                    {"reason": "baseline_infrastructure_failure"},
                )

    work = [
        (case_id, trial_id, *estimates[case_id])
        for case_id in selected["cases"]
        for trial_id in selected["trials"]
    ]
    if selected["phase"] == "pilot":
        for item in work:
            execute(item)
    else:
        with ThreadPoolExecutor(max_workers=_WORKERS) as workers:
            list(workers.map(execute, work))
    return aggregate_baseline(
        root,
        manifest_path=manifest_path,
        expected_identity=identity,
        expected_container_execution=asdict(evidence),
    )


def physical_evidence() -> dict[str, Any]:
    """Summarize retained observations, separately from fixture response grounding."""
    path = Path(__file__).with_name("directional-capture-evidence.json")
    records = _read(path)["records"]
    expectations = default_physical_expectations()
    findings = []
    for record in records:
        index, receipt = record["index"], record["receipt"]
        body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        if (
            graph_checks.annual_json_digest(body) != receipt["receipt_sha256"]
            or index["proof_sha256"] != receipt["receipt_sha256"]
            or graph_checks.annual_json_digest(record["raw_result"])
            != receipt["raw_result_sha256"]
        ):
            raise ValueError("directional receipt identity mismatch")
        observations = receipt["observations"]
        routes = (
            [observations["current_route"]]
            if index["tool"] == "current"
            else list(observations["annual_routes"].values())
        )
        prohibited = sorted(
            {
                edge
                for route in routes
                for edge in route.get("connection_ids", [])
                if edge in expectations and expectations[edge].status == "prohibited"
            }
        )
        for edge in prohibited:
            findings.append(
                {
                    "movement_id": index["movement_id"],
                    "tool": index["tool"],
                    "prohibited_direct_edge": edge,
                    "receipt_sha256": receipt["receipt_sha256"],
                }
            )
    return {
        "evidence_sha256": _digest(path),
        "records": len(records),
        "movements": len({r["index"]["movement_id"] for r in records}),
        "capture_status_counts": dict(Counter(r["index"]["status"] for r in records)),
        "physical_findings": findings,
        "scope": "Retained directional observations; separate from agent grounding. Not exhaustive inventory coverage or historical domain replay.",
    }


def _attempt(
    artifact: Path,
    case_id: str,
    trial_id: str,
    plan: dict[str, Any],
    schema: dict[str, Any],
    expected_identity: dict[str, Any],
    expected_container_execution: dict[str, Any],
    trusted_case_digest: str,
    identity_environment_valid: bool,
) -> dict[str, Any]:
    item = {
        "case_id": case_id,
        "trial_id": trial_id,
        "state": "missing_or_interrupted",
        "retained": artifact.exists(),
        "tokens": None,
        "latency_ms": None,
        "cost_usd": None,
        "total_tool_calls": None,
        "unbound_tool_calls": None,
        "observed_tools": [],
        "scorecard_sha256": None,
    }
    try:
        if not artifact.exists():
            return item
        if artifact.is_symlink() or artifact.parent.is_symlink():
            raise ValueError("attempt directory is not regular")
        if _read(artifact / "attempt.json") != {
            "case_id": case_id,
            "trial_id": trial_id,
        }:
            raise ValueError("attempt identity mismatch")
        required = (
            "receipt.json",
            "scorecard.json",
            "run.json",
            "output.json",
            "stdout.txt",
            "exit_code.json",
        )
        if any(not (artifact / name).exists() for name in required):
            if (artifact / "interrupted.json").exists():
                interruption = _read(artifact / "interrupted.json")
                if interruption.get("reason") not in _INTERRUPTION_REASONS:
                    raise ValueError("invalid interruption record")
                item["state"] = (
                    "over_reservation_failure"
                    if interruption["reason"] == "baseline_over_reservation"
                    else "infrastructure_failure"
                )
            return item
        receipt, score, run, output = (
            _read(artifact / name)
            for name in ("receipt.json", "scorecard.json", "run.json", "output.json")
        )
        graph_checks.validate(score, schema)
        if (
            receipt
            != {
                "scorecard_sha256": _digest(artifact / "scorecard.json"),
                "run_sha256": _digest(artifact / "run.json"),
                "raw_digest": _artifact_digest(artifact),
            }
            or run["output_digest"] != receipt["raw_digest"]
            or run["case_id"] != case_id
            or output["case_id"] != case_id
            or run.get("case_digest") != trusted_case_digest
            or output.get("container_execution") != expected_container_execution
            or not identity_environment_valid
        ):
            raise ValueError("retained evidence identity mismatch")
        item["scorecard_sha256"] = receipt["scorecard_sha256"]
        calls = [call for turn in output["trajectory"] for call in turn["calls"]]
        item["total_tool_calls"] = len(calls)
        item["unbound_tool_calls"] = sum(
            type(call.get("script_sequence")) is not int or not call.get("fixture_id")
            for call in calls
        )
        item["observed_tools"] = sorted(
            {call["name"] if call["name"] in _TOOLS else "other" for call in calls}
        )
        if score["grader"] != expected_identity["grader_digest"]:
            raise ValueError("scorecard grader identity mismatch")
        if (
            score["failure_class"] == "infra_dependency"
            or run["failure_class"] == "infra_dependency"
        ):
            item["state"] = "infrastructure_failure"
            return item
        graph_checks.valid_annual_identity(score["identity"], trial=True)
        if (
            score["identity"] != {**expected_identity, "trial_id": trial_id}
            or run["identity"] != {**expected_identity, "trial_id": trial_id}
            or plan["identity"] != expected_identity
            or score["case_id"] != case_id
            or run["trusted_rate_card"] != plan["rate_card"]
            or score["cost"] != run["cost"]
            or output["cost"] != run["cost"]
            or score["model_settings"] != run["model_settings"]
            or score["candidate_artifact"] != run["candidate_artifact"]
            or score["contract_versions"] != run["contract_versions"]
        ):
            raise ValueError("scored identity mismatch")
        graph_checks._annual_cost(run)
        if (score["failure_class"], score["pass"]) not in (
            ("none", True),
            ("agent_quality", False),
        ):
            raise ValueError("score status is inconsistent")
        item["state"] = "passed" if score["pass"] else "agent_quality_failure"
        for field in ("tokens", "latency_ms"):
            if (
                type(score[field]) is not int
                or score[field] < 0
                or score[field] != run[field]
            ):
                raise ValueError("invalid measurement")
            item[field] = score[field]
        item["cost_usd"] = score["cost"]["total_usd"]
    except Exception:
        item.update(
            state="identity_mismatch_or_inconclusive",
            tokens=None,
            latency_ms=None,
            cost_usd=None,
            total_tool_calls=None,
            unbound_tool_calls=None,
            observed_tools=[],
        )
    return item


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(item["state"] for item in items)
    valid = counts["passed"] + counts["agent_quality_failure"]
    known_costs = [item["cost_usd"] for item in items if item["cost_usd"] is not None]
    complete = len(known_costs) == len(items) and bool(items)

    def total(field: str) -> int | float | None:
        values = [item[field] for item in items]
        return (
            sum(values)
            if values and all(value is not None for value in values)
            else None
        )

    return {
        "scheduled_attempts": len(items),
        "retained_attempts": sum(item["retained"] for item in items),
        "valid_scored_attempts": valid,
        "passed": counts["passed"],
        "agent_quality_failures": counts["agent_quality_failure"],
        "infrastructure_failures": counts["infrastructure_failure"],
        "over_reservation_failures": counts["over_reservation_failure"],
        "identity_mismatch_or_inconclusive": counts[
            "identity_mismatch_or_inconclusive"
        ],
        "missing_or_interrupted": counts["missing_or_interrupted"],
        "pass_rate": {
            "numerator": counts["passed"],
            "denominator": valid,
            "value": counts["passed"] / valid if valid else None,
        },
        "measurement_status": "complete" if complete else "inconclusive",
        "tokens": total("tokens"),
        "latency_ms_total": total("latency_ms"),
        "latency_ms_mean": mean(item["latency_ms"] for item in items)
        if complete
        else None,
        "cost_usd": sum(known_costs) if complete else None,
        "complete_trial_cost_subtotal_usd": sum(known_costs) if known_costs else None,
        "complete_trial_cost_count": len(known_costs),
        "partial_failed_trial_cost_usd": None,
        "total_tool_calls": total("total_tool_calls"),
        "unbound_tool_calls": total("unbound_tool_calls"),
    }


def aggregate_baseline(
    root: Path,
    *,
    manifest_path: Path = _DEFAULT,
    expected_identity: dict[str, Any] | None = None,
    expected_container_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one immutable report, including missing attempts after interruption."""
    root = root.resolve()
    if expected_identity is None or expected_container_execution is None:
        raise ValueError(
            "offline aggregation requires externally pinned identity and image evidence"
        )
    plan = _read(root / "manifest.json")
    corpus = _validated_manifest(manifest_path)
    selection = validate_selection(plan["selection"], corpus)
    private = "public_dataset_sha256" in corpus.manifest
    if (
        plan["artifact_type"] != "fixture_baseline_run"
        or plan["private"] != private
        or plan["selection_digest"] != graph_checks.annual_json_digest(selection)
        or plan.get("selection_file_sha256")
        not in (
            None,
            _PILOT_SELECTION_SHA256 if selection["phase"] == "pilot" else None,
        )
        or plan["identity"] != expected_identity
        or plan["container_execution"] != expected_container_execution
    ):
        raise ValueError("baseline declaration identity mismatch")
    graph_checks.valid_annual_identity(
        {**expected_identity, "trial_id": selection["trials"][0]}, trial=True
    )
    expected_dataset = (
        adapt_holdout_rows(corpus.rows, manifest_path=manifest_path)[0]["dataset_hash"]
        if private
        else corpus.manifest["dataset_sha256"]
    )
    identity_environment_valid = True
    try:
        graph_checks._container_execution(expected_container_execution)
        if expected_identity["dataset_hash"] != expected_dataset:
            raise ValueError("dataset identity mismatch")
        if expected_identity["source_digest"] != graph_checks.source_digest():
            raise ValueError("source identity mismatch")
        if expected_identity["artifact_digest"] != graph_checks.source_digest():
            raise ValueError("artifact identity mismatch")
        if expected_identity["grader_digest"] != graph_checks.grader_digest():
            raise ValueError("grader identity mismatch")
        card = plan["rate_card"]
        if (
            expected_identity["rate_card_source"] != card["source"]
            or expected_identity["rate_card_version"] != card["version"]
            or expected_identity["rate_card_hash"] != card["digest"]
            or expected_identity["rate_card_values_hash"]
            != graph_checks.annual_rate_card_values_digest(card)
        ):
            raise ValueError("rate-card identity mismatch")
    except Exception:
        # Keep stale sealed evidence reportable as inconclusive per attempt.
        identity_environment_valid = False
    schema = _read(Path(__file__).with_name("schemas") / "scorecard.schema.json")
    rows = {row["id"]: row for row in corpus.rows}
    private_digests: dict[str, str] = {}
    if private:
        private_digests = {
            item["case_id"]: item["row_digest"]
            for item in adapt_holdout_rows(corpus.rows, manifest_path=manifest_path)
            if isinstance(item.get("case_id"), str)
            and isinstance(item.get("row_digest"), str)
        }
    trusted_digests = {
        case_id: (
            private_digests[case_id]
            if private
            else _case_digest(
                trusted_case_evidence(case_id, manifest_path=manifest_path)[0]
            )
        )
        for case_id in selection["cases"]
    }
    items = [
        _attempt(
            root / case_id / trial_id,
            case_id,
            trial_id,
            plan,
            schema,
            expected_identity,
            expected_container_execution,
            trusted_digests[case_id],
            identity_environment_valid,
        )
        for case_id in selection["cases"]
        for trial_id in selection["trials"]
    ]
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        name: {} for name in ("category", "authored_tool", "observed_tool", "direction")
    }
    for item in items:
        row = rows[item["case_id"]]
        labels = {
            "category": [row["primary_category"]],
            "authored_tool": sorted({s["tool"] for s in row["script"]}) or ["none"],
            "observed_tool": item["observed_tools"] or ["none_or_unavailable"],
            "direction": [
                tag.removeprefix("direction-")
                for tag in row.get("tags", [])
                if _DIRECTION.fullmatch(tag)
            ]
            or ["unspecified"],
        }
        for dimension, names in labels.items():
            for name in names:
                groups[dimension].setdefault(name, []).append(item)
    report_pacing = plan.get("pacing")
    if private and isinstance(report_pacing, dict):
        report_pacing = {
            key: value for key, value in report_pacing.items() if key != "attempts"
        }
    report = {
        "artifact_type": "fixture_baseline_report",
        "phase": selection["phase"],
        "private": private,
        "manifest_sha256": _digest(root / "manifest.json"),
        "identity": plan["identity"],
        "container_execution": plan["container_execution"],
        "pacing": report_pacing,
        "selection_digest": plan["selection_digest"],
        "selection_file_sha256": plan.get("selection_file_sha256"),
        "summary": _summary(items),
        "breakdowns": {
            dimension: {
                name: _summary(values) for name, values in sorted(group.items())
            }
            for dimension, group in groups.items()
        },
        "physical_evidence": physical_evidence(),
        "limits": [
            "Diagnostic fixture replay, not a population estimate or release gate.",
            "Tool/direction groups may overlap; their counts are not additive.",
            "No scheduled attempt is rerun or substituted; unchanged SDK transport retries remain possible.",
            "Costs use returned provider usage, not invoice reconciliation. Failed-trial partial spend is unknown.",
            "Response checks are bounded heuristics. Physical findings are separate from agent grounding.",
        ],
    }
    if not private:
        report["results"] = [
            {k: v for k, v in item.items() if k != "observed_tools"} for item in items
        ]
    _write_json(root / "report.json", report)
    return report

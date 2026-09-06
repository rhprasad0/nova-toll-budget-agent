# pyright: basic
"""Trusted annual fixture supervisor.

The runner only produces raw observations.  This boundary owns corpus lookup,
identity construction, sealing, and invoking the shared graph grader.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, cast

from agent.toll_agent import (
    SYSTEM_PROMPT_RENDERER_VERSION,
    SYSTEM_PROMPT_VERSION,
    build_system_prompt,
)
from eval import graph_checks
from eval.fixture_runner import (
    _TOOL_SPECS,
    FixtureRunPacket,
    RateCard,
    run_fixture_trial,
)
from eval.golden_corpus import (
    Corpus,
    _canonical,
    _validate_case,
    validate,
    validate_private_manifest,
)

_DEFAULT_MANIFEST = Path(__file__).with_name("golden") / "manifest-v2.json"
_DEFAULT_V2_MANIFEST = Path(__file__).with_name("golden") / "manifest-v2.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _default_script_turn(row: Mapping[str, Any]) -> int:
    if row.get("expected_clarification") or row.get("annual_behavior") in {
        "annual_day_estimate",
        "income_clarification",
        "schedule_correction",
    }:
        conversation = row.get("conversation", [])
        if isinstance(conversation, list) and conversation:
            return len(conversation) - 1
    return 0


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _packet_script(
    corpus: object, row: Mapping[str, Any]
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    """Resolve every authored script step through the validated corpus."""
    script = deepcopy(row.get("script", []))
    if not script and isinstance(row.get("fixture_id"), str):
        request = row.get("expected_call")
        if isinstance(request, dict):
            script = [
                {
                    "turn": _default_script_turn(row),
                    "tool": (
                        "get_current_toll_price"
                        if row.get("suite") == "current"
                        else "get_annual_toll_ballpark"
                    ),
                    "request": deepcopy(request),
                    "fixture_id": row["fixture_id"],
                }
            ]
    if not isinstance(script, list):
        raise ValueError("validated case script is unavailable")
    evidence: list[dict[str, Any]] = []
    for step in script:
        if not isinstance(step, dict) or not isinstance(step.get("fixture_id"), str):
            raise ValueError("script step fixture identity is invalid")
        item = cast(Any, corpus).fixture_evidence(step["fixture_id"])
        if item["tool"] != step.get("tool") or item["request"] != step.get("request"):
            raise ValueError("script step disagrees with fixture evidence")
        evidence.append(item)
    return tuple(cast(dict[str, Any], step) for step in script), tuple(evidence)


def _validated_manifest(
    manifest_path: Path, public_manifest_path: Path | None = None
) -> Corpus:
    """Validate a public or supplied-own private manifest at the trust boundary."""
    manifest = graph_checks.read_json(manifest_path)
    if (
        isinstance(manifest, dict)
        and "public_dataset_sha256" in manifest
        and "public_membership_sha256" in manifest
    ):
        public = validate(public_manifest_path or _DEFAULT_V2_MANIFEST)
        return validate_private_manifest(manifest_path, public)
    return validate(manifest_path)


def _commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise ValueError("commit identity is unavailable")
    return value


def packet_for_case(
    case_id: str,
    *,
    manifest_path: Path = _DEFAULT_MANIFEST,
    prompt_points: Sequence[Mapping[str, Any]] | None = None,
    render_date: date | None = None,
) -> FixtureRunPacket:
    """Adapt one validated public row while omitting grader-only metadata."""
    corpus = _validated_manifest(manifest_path)
    rows = [row for row in corpus.rows if row.get("id") == case_id]
    if len(rows) != 1:
        raise ValueError("annual case is not in the validated corpus")
    row = rows[0]
    fixture_id = row.get("fixture_id")
    v2 = corpus.manifest.get("format_version") == "2.0.0"
    if v2:
        script, evidence = _packet_script(corpus, row)
        primary = evidence[0] if len(evidence) == 1 else None
    else:
        script = ()
        evidence = ()
        primary = corpus.fixtures.get(fixture_id) if fixture_id else None
    fixture_bytes: bytes | None = None
    if primary is not None and "raw_bytes" in primary:
        fixture_bytes = cast(bytes, primary["raw_bytes"])
    turns = list(row.get("conversation", [row["prompt"]]))
    if row.get("follow_up") and row["follow_up"] not in turns:
        turns.append(row["follow_up"])
    return FixtureRunPacket(
        case_id=case_id,
        prompt=row["prompt"],
        conversation=tuple(turns),
        fixture_id=fixture_id,
        fixture_result_kind=(
            primary.get("result_kind") if primary is not None else None
        ),
        fixture_request=deepcopy(primary["request"]) if primary is not None else None,
        fixture_payload=(
            deepcopy(primary.get("result", primary.get("payload")))
            if primary is not None
            else None
        ),
        fixture_bytes=(
            cast(bytes, corpus.fixture_raw_bytes[fixture_id])
            if fixture_id is not None and fixture_id in corpus.fixture_raw_bytes
            else fixture_bytes
        ),
        prompt_points=(
            tuple(deepcopy(dict(point)) for point in prompt_points)
            if prompt_points is not None
            else None
        ),
        render_date=render_date,
        script=script,
        fixture_evidence=evidence,
        strict_usage=v2,
        dataset_version=str(corpus.manifest.get("dataset_version", "1.0.0")),
    )


def trusted_case_evidence(
    case_id: str, *, manifest_path: Path = _DEFAULT_MANIFEST
) -> tuple[bytes, str, str]:
    """Return full adapted case bytes and manifest identity for trusted sealing."""
    corpus = _validated_manifest(manifest_path)
    rows = [row for row in corpus.rows if row.get("id") == case_id]
    if len(rows) != 1:
        raise ValueError("annual case is not in the validated corpus")
    return (
        _canonical(rows[0]),
        str(corpus.manifest["dataset_sha256"]),
        str(rows[0]["id"]),
    )


def _model_settings(
    model: object, settings: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    config: Mapping[str, Any] = {}
    getter = getattr(model, "get_config", None)
    if callable(getter):
        value = getter()
        if isinstance(value, Mapping):
            config = value
    model_id = config.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("model identity is unavailable")
    actual = config.get("params")
    if not isinstance(actual, Mapping):
        raise ValueError("model settings are unavailable")
    if settings is not None and dict(settings) != dict(actual):
        raise ValueError("supplied model settings disagree with model config")
    return model_id, dict(actual)


def _safe_model_settings(
    model: object, settings: Mapping[str, Any] | None
) -> dict[str, Any]:
    model_id, actual_settings = _model_settings(model, settings)
    safe_limit_keys = {"maxtokens", "maxoutputtokens", "maxcompletiontokens"}
    unsafe_containers = {
        "clientargs",
        "extraheaders",
        "defaultheaders",
        "headers",
        "httpheaders",
        "requestheaders",
        "cookies",
    }

    def normalized_key(key: str) -> str:
        return re.sub(r"[^a-z0-9]", "", key.casefold())

    def sensitive_key(key: str) -> bool:
        normalized = normalized_key(key)
        if normalized in safe_limit_keys:
            return False
        return (
            normalized in {"token", "authorization", "privatekey", "accesskey", "auth"}
            or normalized.endswith("token")
            or "apikey" in normalized
            or "accesskey" in normalized
            or "privatekey" in normalized
            or "credential" in normalized
            or "password" in normalized
            or "secret" in normalized
            or normalized in unsafe_containers
        )

    def clean(value: object, key: str = "") -> object:
        if sensitive_key(key):
            return "[redacted]"
        if isinstance(value, Mapping):
            return {
                str(nested_key): clean(nested_value, str(nested_key))
                for nested_key, nested_value in value.items()
                if isinstance(nested_key, str)
            }
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if type(value) in (str, int, float, bool) or value is None:
            return value
        return str(value)

    stateful = getattr(model, "stateful", None)
    if type(stateful) is not bool:
        raise ValueError("model stateful setting is unavailable")
    return {
        "model_id": model_id,
        "stateful": stateful,
        "params": cast(dict[str, Any], clean(actual_settings)),
    }


def _contract_versions(dataset_version: str | None = None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    prompt_manifest = json.loads(
        (root / "agent" / "contract-manifest.json").read_text(encoding="utf-8")
    )
    tool_manifest = json.loads(
        (root / "agent_tools" / "contract-manifest.json").read_text(encoding="utf-8")
    )
    return {
        "dataset_version": dataset_version
        or validate(_DEFAULT_MANIFEST).manifest["dataset_version"],
        "system_prompt": prompt_manifest["system_prompt"]["current"],
        "system_prompt_renderer": prompt_manifest["system_prompt_renderer"]["current"],
        "tools": {
            name: tool_manifest[name]["current"] for name in sorted(tool_manifest)
        },
        "renderer_constant": SYSTEM_PROMPT_RENDERER_VERSION,
        "prompt_constant": SYSTEM_PROMPT_VERSION,
    }


def _prompt_context_hash(packet: FixtureRunPacket) -> str:
    if packet.prompt_points is None or packet.render_date is None:
        raise ValueError("prompt context is incomplete")
    return _sha256(
        _canonical(
            {
                "prompt_points": packet.prompt_points,
                "render_date": packet.render_date.isoformat(),
            }
        )
    )


def _tool_contract_hash() -> str:
    return _sha256(
        _canonical(cast(Any, [_TOOL_SPECS[name] for name in sorted(_TOOL_SPECS)]))
    )


def _artifact_digest(root: Path) -> str:
    entries: list[bytes] = []
    for name in ("output.json", "stdout.txt", "exit_code.json"):
        path = root / name
        if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError("raw artifact is incomplete")
        entries.append(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return _sha256(b"".join(entries))


def _case_digest(case_bytes: bytes) -> str:
    if not case_bytes:
        raise ValueError("trusted adapted case bytes are missing")
    return _sha256(case_bytes)


def _fixture_corpus_hash(corpus: object, manifest_path: Path) -> str:
    corpus_data = cast(Any, corpus)
    entries = []
    for declaration in corpus_data.manifest["fixtures"]:
        evidence = corpus_data.fixture_evidence(declaration["id"])
        entries.append(
            {
                "id": declaration["id"],
                "result_kind": evidence.get("result_kind"),
                "sha256": evidence["raw_sha256"],
            }
        )
    entries.sort(key=lambda item: item["id"])
    return _sha256(_canonical(cast(Any, entries)))


def _write_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("sealed artifact output already exists")
    with path.open("x", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2
            )
            + "\n"
        )


def _report_card(
    case_id: str, trial_id: str, score: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "trial_id": trial_id,
        "pass": score["pass"],
        "failure_class": score["failure_class"],
        "tokens": score["tokens"],
        "input_tokens": score["input_tokens"],
        "output_tokens": score["output_tokens"],
        "cache_tokens": score["cache_tokens"],
        "cache_write_tokens": score.get("cache_write_tokens"),
        "latency_ms": score["latency_ms"],
        "cost": score["cost"],
        "model_settings": score["model_settings"],
        "contract_versions": score["contract_versions"],
        "candidate_artifact": score["candidate_artifact"],
        "identity": score["identity"],
    }


def _sum_measurement(measurements: object, key: str) -> int | None:
    if type(measurements) is not dict or type(measurements.get("turns")) is not list:
        return None
    values: list[object] = [
        turn.get(key) for turn in measurements["turns"] if type(turn) is dict
    ]
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return sum(cast(int, value) for value in values)


def _seal_identity(
    packet: FixtureRunPacket,
    *,
    model: object,
    model_settings: Mapping[str, Any] | None,
    rate_card: RateCard,
    trial_id: str,
    artifact_digest: str,
    dataset_hash: str,
) -> dict[str, str]:
    if packet.render_date is None or packet.prompt_points is None:
        raise ValueError("prompt context is incomplete")
    if not _SHA256.fullmatch(dataset_hash):
        raise ValueError("dataset identity is unavailable")
    model_id, _ = _model_settings(model, model_settings)
    safe_settings = _safe_model_settings(model, model_settings)
    rate_card.validate()
    prompt = build_system_prompt(
        list(packet.prompt_points), current_date=packet.render_date
    )
    return {
        "model": model_id,
        "model_settings_hash": graph_checks.annual_json_digest(safe_settings),
        "prompt_hash": _sha256(prompt.encode()),
        "prompt_context_hash": _prompt_context_hash(packet),
        "render_date": packet.render_date.isoformat(),
        "tool_contract_hash": _tool_contract_hash(),
        "dataset_hash": dataset_hash,
        "commit": _commit(Path(__file__).resolve().parents[2]),
        "artifact_digest": artifact_digest,
        "grader_digest": graph_checks.grader_digest(),
        "source_digest": graph_checks.source_digest(),
        "rate_card_source": rate_card.source,
        "rate_card_version": rate_card.version,
        "rate_card_hash": rate_card.digest,
        "rate_card_values_hash": graph_checks.annual_rate_card_values_digest(
            rate_card.as_dict()
        ),
        "trial_id": trial_id,
    }


def seal_trial_artifact(
    root: Path,
    packet: FixtureRunPacket,
    *,
    model: object,
    model_settings: Mapping[str, Any] | None,
    rate_card: RateCard,
    trial_id: str,
    case_bytes: bytes,
    dataset_hash: str,
) -> dict[str, Any]:
    """Seal raw observations with trusted identity; no runner verdict is copied."""
    root = root.resolve()
    raw = graph_checks.read_json(root / "output.json")
    if type(raw) is not dict:
        raise ValueError("raw output object required")
    measurements = raw.get("measurements")
    failure_class = "none"
    if type(measurements) is not dict:
        failure_class = "infra_dependency"
    else:
        turns = measurements.get("turns")
        if (
            type(turns) is not list
            or not turns
            or any(
                type(turn) is not dict
                or type(turn.get("tokens")) is not int
                or turn["tokens"] < 0
                or type(turn.get("latency_ms")) is not int
                or turn["latency_ms"] < 0
                for turn in cast(list[dict[str, Any]], turns)
            )
        ):
            failure_class = "infra_dependency"
    trusted_rate_card: dict[str, Any] | None = None
    try:
        trusted_rate_card = rate_card.as_dict()
        raw_cost = raw.get("cost")
        if type(raw_cost) is not dict or raw_cost.get("rate_card") != trusted_rate_card:
            raise ValueError("raw rate-card evidence disagrees with trusted card")
        _, model_settings_value = _model_settings(model, model_settings)
        identity = _seal_identity(
            packet,
            model=model,
            model_settings=model_settings,
            rate_card=rate_card,
            trial_id=trial_id,
            artifact_digest=graph_checks.source_digest(),
            dataset_hash=dataset_hash,
        )
    except Exception:
        identity = {key: "0" * 64 for key in graph_checks.ANNUAL_HASH_FIELDS}
        identity.update(
            {
                "model": "unknown",
                "commit": "0" * 40,
                "render_date": "0000-00-00",
                "rate_card_source": "missing",
                "rate_card_version": "missing",
                "trial_id": trial_id,
            }
        )
        failure_class = "infra_dependency"
    if trusted_rate_card is None:
        failure_class = "infra_dependency"
    run = {
        "artifact_type": "annual_fixture_trial",
        "case_id": packet.case_id,
        "case_digest": _case_digest(case_bytes),
        "output_digest": _artifact_digest(root),
        "fixture_id": packet.fixture_id,
        "fixture_result_kind": packet.fixture_result_kind,
        "identity": identity,
        "model_settings": (
            _safe_model_settings(model, model_settings_value)
            if failure_class == "none"
            else None
        ),
        "contract_versions": (
            _contract_versions(packet.dataset_version)
            if failure_class == "none"
            else None
        ),
        "candidate_artifact": {
            "artifact_id": f"source-snapshot:{identity['artifact_digest']}",
            "kind": "source-snapshot",
            "digest": identity["artifact_digest"],
            "deployment_identity": "pending",
        },
        "trusted_rate_card": trusted_rate_card,
        "tokens": measurements.get("tokens")
        if isinstance(measurements, dict)
        else None,
        "input_tokens": _sum_measurement(measurements, "input_tokens"),
        "output_tokens": _sum_measurement(measurements, "output_tokens"),
        "cache_tokens": _sum_measurement(measurements, "cache_tokens"),
        "cache_write_tokens": _sum_measurement(measurements, "cache_write_tokens"),
        "latency_ms": measurements.get("latency_ms")
        if isinstance(measurements, dict)
        else None,
        "cost": raw.get("cost"),
        "failure_class": failure_class,
    }
    _write_json(root / "run.json", run)
    return run


def run_and_seal_trial(
    packet: FixtureRunPacket,
    *,
    model: object,
    artifact_root: Path,
    trial_id: str,
    rate_card: RateCard,
    model_settings: Mapping[str, Any] | None = None,
    case_bytes: bytes,
    dataset_hash: str,
    case_document: Mapping[str, Any] | None = None,
    manifest_path: Path | None = None,
) -> int:
    """Trusted callable boundary for one real-model fixture trial."""
    run_fixture_trial(
        packet,
        model=model,
        artifact_root=artifact_root,
        trial_id=trial_id,
        rate_card=rate_card,
    )
    seal_trial_artifact(
        artifact_root,
        packet,
        model=model,
        model_settings=model_settings,
        rate_card=rate_card,
        trial_id=trial_id,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
    )

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
        json.dump(
            case_document
            if case_document is not None
            else {"case_id": packet.case_id, "suite": "annual"},
            handle,
        )
        handle.flush()
        return graph_checks.grade(
            artifact_root, Path(handle.name), manifest_path=manifest_path
        )


def aggregate_public_run(
    root: Path,
    *,
    cases: Sequence[str],
    identity: Mapping[str, str],
    mode: str = "gate",
) -> Path:
    """Write the trusted public ten-case/three-trial graph manifest and report."""
    if list(cases) != [row["id"] for row in validate(_DEFAULT_MANIFEST).annual_rows]:
        raise ValueError("public annual case order does not match the validated corpus")
    if mode not in {"pin", "improve", "gate"}:
        raise ValueError("invalid graph mode")
    if set(identity) != set(graph_checks.ANNUAL_IDENTITY) - {"trial_id"}:
        raise ValueError("annual run identity is incomplete")
    root = root.resolve()
    scorecards: list[str] = []
    report_cards: list[dict[str, Any]] = []
    schema = graph_checks.read_json(
        Path(__file__).with_name("schemas") / "scorecard.schema.json"
    )
    for case_id in cases:
        for trial_id in ("1", "2", "3"):
            path = root / case_id / trial_id / "scorecard.json"
            if not path.is_file() or path.is_symlink():
                raise ValueError("public run is missing a sealed trial")
            score = graph_checks.read_json(path)
            graph_checks.validate(score, schema)
            graph_checks.valid_annual_identity(score.get("identity"), trial=True)
            if (
                score.get("case_id") != case_id
                or score["identity"]["trial_id"] != trial_id
                or {key: score["identity"][key] for key in identity} != dict(identity)
                or score.get("failure_class") == "infra_dependency"
            ):
                raise ValueError("public trial evidence is not sealed for this run")
            scorecards.append(path.relative_to(root).as_posix())
            report_cards.append(_report_card(case_id, trial_id, score))
    root.mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "manifest.json",
        {
            "artifact_type": "annual_fixture_run",
            "suite": "annual",
            "mode": mode,
            "identity": dict(identity),
            "cases": list(cases),
            "trials": ["1", "2", "3"],
            "trial_count": 3,
            "scorecards": scorecards,
        },
    )
    _write_json(
        root / "report.json",
        {
            "artifact_type": "annual_fixture_report",
            "suite": "annual",
            "mode": mode,
            "identity": dict(identity),
            "results": report_cards,
        },
    )
    return root


def aggregate_holdout_run(
    root: Path,
    *,
    cases: Sequence[str],
    identity: Mapping[str, str],
    mode: str = "gate",
) -> Path:
    """Aggregate opaque, separately sealed holdout cases without public IDs."""
    if not cases or len(cases) != len(set(cases)):
        raise ValueError("holdout case set is invalid")
    public_ids = {row["id"] for row in validate(_DEFAULT_MANIFEST).rows}
    if _DEFAULT_V2_MANIFEST.is_file():
        public_ids.update(row["id"] for row in validate(_DEFAULT_V2_MANIFEST).rows)
    if public_ids.intersection(cases):
        raise ValueError("holdout case IDs must be opaque and outside the public set")
    if mode not in {"pin", "improve", "gate"}:
        raise ValueError("invalid graph mode")
    if set(identity) != set(graph_checks.ANNUAL_IDENTITY) - {"trial_id"}:
        raise ValueError("annual holdout identity is incomplete")
    root = root.resolve()
    scorecards: list[str] = []
    report_cards: list[dict[str, Any]] = []
    schema = graph_checks.read_json(
        Path(__file__).with_name("schemas") / "scorecard.schema.json"
    )
    for case_id in cases:
        for trial_id in ("1", "2", "3"):
            path = root / case_id / trial_id / "scorecard.json"
            if not path.is_file() or path.is_symlink():
                raise ValueError("holdout run is missing a sealed trial")
            score = graph_checks.read_json(path)
            graph_checks.validate(score, schema)
            graph_checks.valid_annual_identity(score.get("identity"), trial=True)
            if (
                score.get("case_id") != case_id
                or score["identity"]["trial_id"] != trial_id
                or {key: score["identity"][key] for key in identity} != dict(identity)
                or score.get("failure_class") == "infra_dependency"
            ):
                raise ValueError("holdout trial evidence is not sealed for this run")
            scorecards.append(path.relative_to(root).as_posix())
            report_cards.append(_report_card(case_id, trial_id, score))
    _write_json(
        root / "manifest.json",
        {
            "artifact_type": "annual_fixture_run",
            "suite": "annual-heldout",
            "mode": mode,
            "identity": dict(identity),
            "cases": list(cases),
            "trials": ["1", "2", "3"],
            "trial_count": 3,
            "scorecards": scorecards,
        },
    )
    _write_json(
        root / "report.json",
        {
            "artifact_type": "annual_fixture_report",
            "suite": "annual-heldout",
            "mode": mode,
            "identity": dict(identity),
            "results": report_cards,
        },
    )
    return root


def adapt_holdout_row(
    row: Mapping[str, Any], *, manifest_path: Path = _DEFAULT_MANIFEST
) -> dict[str, Any]:
    """Adapt one opaque row using a one-row shared membership bundle."""
    return adapt_holdout_rows([row], manifest_path=manifest_path)[0]


def adapt_holdout_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    manifest_path: Path = _DEFAULT_MANIFEST,
) -> list[dict[str, Any]]:
    """Bind opaque holdout rows to one fixture corpus and membership hash.

    The full rows are supplied by the trusted parent executor.  This function
    stores no holdout data itself; it returns envelopes for the caller to seal.
    """
    if not rows:
        raise ValueError("holdout row set is empty")
    corpus = _validated_manifest(manifest_path)
    if corpus.manifest.get("format_version") == "2.0.0":
        public_ids = {item["id"] for item in corpus.rows}
        if "public_dataset_sha256" in corpus.manifest:
            public_ids = {item["id"] for item in validate(_DEFAULT_V2_MANIFEST).rows}
        prepared_v2: list[tuple[str, dict[str, Any], str | None, str]] = []
        seen_v2: set[str] = set()
        for source in rows:
            row = deepcopy(dict(source))
            case_id = row.get("id")
            prompt = row.get("prompt")
            fixture_id = row.get("fixture_id")
            if (
                not isinstance(case_id, str)
                or not case_id
                or case_id in public_ids
                or case_id in seen_v2
                or not isinstance(prompt, str)
                or not prompt
                or (fixture_id is not None and not isinstance(fixture_id, str))
            ):
                raise ValueError("v2 holdout row identity or prompt is invalid")
            if row.get("suite") not in {"current", "annual"}:
                raise ValueError("v2 holdout row suite is invalid")
            try:
                _packet_script(corpus, row)
            except Exception as error:
                raise ValueError("v2 holdout row script is invalid") from error
            seen_v2.add(case_id)
            prepared_v2.append((case_id, row, fixture_id, _sha256(_canonical(row))))
        fixture_hash = _fixture_corpus_hash(corpus, manifest_path)
        membership = [
            [case_id, row_hash]
            for case_id, _row, _fixture_id, row_hash in sorted(prepared_v2)
        ]
        bundle_hash = _sha256(
            _canonical({"fixture_corpus_hash": fixture_hash, "rows": membership})
        )
        return [
            {
                "case_id": case_id,
                "suite": "annual",
                "holdout": True,
                "row": row,
                "dataset_hash": bundle_hash,
                "membership_hash": bundle_hash,
                "holdout_membership": membership,
                "fixture_corpus_hash": fixture_hash,
                "row_digest": row_hash,
                "fixture_id": fixture_id,
                "prompt": row["prompt"],
                "conversation": list(row.get("conversation", [row["prompt"]])),
            }
            for case_id, row, fixture_id, row_hash in prepared_v2
        ]
    public_ids = {item["id"] for item in corpus.rows}
    prepared: list[tuple[str, dict[str, Any], str | None, str]] = []
    seen: set[str] = set()
    for source in rows:
        row = deepcopy(dict(source))
        case_id = row.get("id")
        fixture_id = row.get("fixture_id")
        prompt = row.get("prompt")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in public_ids
            or case_id in seen
            or not isinstance(prompt, str)
            or not prompt
        ):
            raise ValueError("holdout row identity or prompt is invalid")
        if fixture_id is not None and fixture_id not in corpus.fixtures:
            raise ValueError("holdout fixture must be an existing validated fixture")
        try:
            _validate_case(row, f"holdout row {case_id}")
        except Exception as error:
            raise ValueError("holdout row is not a complete annual case") from error
        if (
            fixture_id is not None
            and row.get("expected_call") != corpus.fixtures[fixture_id]["request"]
        ):
            raise ValueError("holdout row disagrees with its validated fixture")
        seen.add(case_id)
        prepared.append((case_id, row, fixture_id, _sha256(_canonical(row))))
    fixture_hash = _fixture_corpus_hash(corpus, manifest_path)
    membership = [
        [case_id, row_hash] for case_id, _row, _fixture_id, row_hash in sorted(prepared)
    ]
    bundle = {"fixture_corpus_hash": fixture_hash, "rows": membership}
    bundle_hash = _sha256(_canonical(cast(Any, bundle)))
    envelopes: list[dict[str, Any]] = []
    for case_id, row, fixture_id, row_hash in prepared:
        envelopes.append(
            {
                "case_id": case_id,
                "suite": "annual",
                "holdout": True,
                "row": row,
                "dataset_hash": bundle_hash,
                "membership_hash": bundle_hash,
                "holdout_membership": membership,
                "fixture_corpus_hash": fixture_hash,
                "row_digest": row_hash,
                "fixture_id": fixture_id,
                "prompt": row["prompt"],
                "conversation": list(row.get("conversation", [row["prompt"]])),
            }
        )
    return envelopes


def holdout_case_document(adapted: Mapping[str, Any]) -> dict[str, Any]:
    """Return the trusted case envelope consumed by the shared annual grader."""
    row = adapted.get("row")
    if type(row) is not dict or adapted.get("holdout") is not True:
        raise ValueError("holdout adapter output is invalid")
    membership = adapted.get("holdout_membership")
    membership_hash = adapted.get("membership_hash")
    dataset_hash = adapted.get("dataset_hash")
    fixture_corpus_hash = adapted.get("fixture_corpus_hash")
    row_digest = adapted.get("row_digest")
    if (
        type(membership) is not list
        or not membership
        or not isinstance(membership_hash, str)
        or not _SHA256.fullmatch(membership_hash)
        or not isinstance(fixture_corpus_hash, str)
        or not _SHA256.fullmatch(fixture_corpus_hash)
        or not isinstance(row_digest, str)
        or not _SHA256.fullmatch(row_digest)
    ):
        raise ValueError("holdout fixture membership identity is invalid")
    if not isinstance(dataset_hash, str) or not _SHA256.fullmatch(dataset_hash):
        raise ValueError("holdout dataset identity is invalid")
    if membership_hash != dataset_hash:
        raise ValueError("holdout membership and dataset identities disagree")
    return {
        "case_id": adapted.get("case_id"),
        "suite": "annual",
        "holdout": True,
        "row": deepcopy(row),
        "dataset_hash": dataset_hash,
        "membership_hash": membership_hash,
        "holdout_membership": deepcopy(membership),
        "fixture_corpus_hash": fixture_corpus_hash,
        "row_digest": row_digest,
    }


def packet_for_holdout(
    adapted: Mapping[str, Any],
    *,
    manifest_path: Path = _DEFAULT_MANIFEST,
    prompt_points: Sequence[Mapping[str, Any]] | None = None,
    render_date: date | None = None,
) -> tuple[FixtureRunPacket, bytes, str]:
    """Build execution input and trusted case bytes for an adapted holdout."""
    case_document = holdout_case_document(adapted)
    row = adapted.get("row")
    if type(row) is not dict or adapted.get("holdout") is not True:
        raise ValueError("holdout adapter output is invalid")
    case_id = adapted.get("case_id")
    fixture_id = adapted.get("fixture_id")
    if not isinstance(case_id, str) or row.get("id") != case_id:
        raise ValueError("holdout identity is invalid")
    corpus = _validated_manifest(manifest_path)
    v2 = corpus.manifest.get("format_version") == "2.0.0"
    if v2:
        if fixture_id and fixture_id not in corpus.fixture_tools:
            raise ValueError("holdout fixture is not in the validated corpus")
        script, evidence = _packet_script(corpus, row)
        primary = evidence[0] if len(evidence) == 1 else None
    else:
        fixture = corpus.fixtures.get(fixture_id) if fixture_id else None
        if fixture_id and fixture is None:
            raise ValueError("holdout fixture is not in the validated corpus")
        script = ()
        evidence = ()
        primary = fixture
    turns = list(row.get("conversation", [row["prompt"]]))
    if row.get("follow_up") and row["follow_up"] not in turns:
        turns.append(row["follow_up"])
    packet = FixtureRunPacket(
        case_id=case_id,
        prompt=str(row["prompt"]),
        conversation=tuple(turns),
        fixture_id=fixture_id,
        fixture_result_kind=primary.get("result_kind") if primary else None,
        fixture_request=deepcopy(primary["request"]) if primary else None,
        fixture_payload=(
            deepcopy(primary.get("result", primary.get("payload"))) if primary else None
        ),
        fixture_bytes=(
            cast(bytes, primary["raw_bytes"])
            if primary and "raw_bytes" in primary
            else (
                cast(bytes, corpus.fixture_raw_bytes[fixture_id])
                if fixture_id is not None and fixture_id in corpus.fixture_raw_bytes
                else None
            )
        ),
        prompt_points=(
            tuple(deepcopy(dict(point)) for point in prompt_points)
            if prompt_points is not None
            else None
        ),
        render_date=render_date,
        script=script,
        fixture_evidence=evidence,
        strict_usage=v2,
        dataset_version=str(corpus.manifest.get("dataset_version", "1.0.0")),
    )
    return packet, _canonical(row), case_document["dataset_hash"]

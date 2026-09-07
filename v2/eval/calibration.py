# pyright: basic
"""Offline evidence binding and blinded human review for fixture baselines."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from eval import baseline, graph_checks
from eval.fixture_eval import (
    _case_digest,
    _validated_manifest,
    adapt_holdout_rows,
    trusted_case_evidence,
)
from eval.fixture_runner import RateCard
from eval.golden_corpus import Corpus

_TRIALS = ["1", "2", "3"]
_LABELS = {"Pass", "Fail", "Unsure"}
_V2_DATASET_VERSION = "2.2.0"
_V2_RENDER_DATE = "2026-09-05"
_V2_PUBLIC_DATASET_SHA256 = (
    "6d0bfbe3950dfb07614488b44545eeee8c25109a4d950bdbebb3f63fd1a4b333"
)
_V2_2_PUBLIC_MANIFEST_SHA256 = (
    "c08cdce610b4b42ca8acbec63db2074e8d72cefc631ccfb95924e4a53b9cb02a"
)
_V2_2_GRADER_DIGEST = "a68f2a8b7f2676530ba0bd54cce9f2cf90a40855e5fb7fd3dbdc8e54035f0812"
_V2_2_EVIDENCE_SHA256 = (
    "917db5b5187ed721b3cb9291185949bc7c1e417e9ac51f223419c5e336a12e09"
)
_V2_3_DATASET_VERSION = "2.3.0"
_V2_3_PUBLIC_DATASET_SHA256 = (
    "6fd9a3944407f1f39a803d8bf8498d032f22891643c4ffca0857d2e259ede49d"
)
_V2_3_MEMBERSHIP_SHA256 = (
    "135021bff4e1ab1fac289a46f734f81dba7b95d452344383c19f3d4dc1dfccbe"
)
_BALANCED_PACKET_SHA256 = (
    "9e017f3a0b01bd3db20f892c344fca033865ceee41676951bdc1d556a5c6fb5d"
)
_FOLLOW_UP_PACKET_SHA256 = (
    "555e2fddecaaccc945813290a2d60ddc27278f6c1f03b89bbb9b062a30a1ea4d"
)
_V2_CATEGORIES = ("topology", "current", "annual", "multiturn", "fault", "abuse")
_V2_FOLLOW_UP_CASES = (
    "multiturn-current-annual-01",
    "multiturn-annual-current-01",
    "multiturn-origin-01",
)
_V2_BALANCED_CASES = (
    "topology-proof-dca-to-i95-north-current",
    "topology-proof-dca-to-i95-north-annual",
    "topology-proof-dca-to-i95-south-current",
    "topology-proof-dca-to-i95-south-annual",
    "topology-proof-dtr-to-greenway-annual",
    "pentagon-eads-to-westpark",
    "springfield-franconia-to-westpark",
    "old-keene-mill-to-reagan-i95-unavailable",
    "dulles-to-reagan-current-price",
    "i66-west-to-route-7-current-price",
    "springfield-franconia-tysons-annual-affordability",
    "leesburg-route-28-schedule-inputs",
    "leesburg-route-28-income-clarification",
    "dulles-to-reagan-annual-unavailable",
    "leesburg-route-28-annual-day-confirmation",
    "multiturn-days-01",
    "multiturn-current-annual-02",
    "multiturn-annual-current-02",
    "multiturn-income-02",
    "multiturn-days-02",
    "fault-current-02",
    "fault-annual-02",
    "fault-current-03",
    "fault-annual-03",
    "fault-current-04",
    "abuse-fake-role",
    "abuse-unrelated-code",
    "abuse-unsupported-override",
    "abuse-fabricate-no-route",
    "abuse-payment-override",
)
_V2_SELECTIONS = {
    "follow-up": _V2_FOLLOW_UP_CASES,
    "balanced": _V2_BALANCED_CASES,
}
_LABEL_SOURCES = {
    "retained_historical_pilot",
    "returned_follow_up_packet",
    "returned_balanced_packet",
}
_FACILITIES = {
    "dulles_toll_road": "Dulles Toll Road",
    "dulles_greenway": "Dulles Greenway",
    "i66": "I-66 Express Lanes",
    "i95_i495": "I-95/I-495 Express Lanes",
}
_SAFE_RESULT_FIELDS = {
    "annual_affordability",
    "annual_total_tolled_commute_cost_usd",
    "annual_toll_usd",
    "availability",
    "calculated_at",
    "component_evaluated_at",
    "components",
    "coverage",
    "coverage_percent",
    "current_delta_usd",
    "daily_round_trip",
    "direction",
    "estimated_after_tax_usd",
    "facility",
    "gross_annual_usd",
    "maximum_usd",
    "median_usd",
    "minimum_usd",
    "modeled_days",
    "net_change_percent",
    "net_change_usd",
    "observed_at",
    "observed_days",
    "paired_days",
    "planned_annual_commute_days",
    "price_usd",
    "pricing_method",
    "prior_week_comparison",
    "reason",
    "recent_movement",
    "result_kind",
    "source_kind",
    "source_status",
    "status",
    "total_usd",
    "unavailable_components",
    "weekdays",
}
_SAFE_REQUEST_FIELDS = {
    "departure_time",
    "gross_annual_income_usd",
    "outbound",
    "payment_method",
    "planned_annual_commute_days",
    "pricing_profile",
    "return",
    "transponder_mode",
    "vehicle_class",
    "weekdays",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("regular calibration input required")
    return path.resolve()


def _application_digest() -> str:
    """Hash only application-agent source, prompt, and tool implementation bytes."""
    root = Path(__file__).resolve().parents[1]
    files = []
    for relative in ("agent", "agent_tools", "agent-sops"):
        directory = root / relative
        files.extend(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and "__pycache__" not in path.parts
            and path.suffix.lower() in {".py", ".md", ".json"}
        )
    return _sha(
        [
            [
                path.relative_to(root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ]
            for path in sorted(files)
        ]
    )


def _trusted_rate_card(path: Path) -> dict[str, Any]:
    value = graph_checks.read_json(_regular(path))
    if not isinstance(value, dict):
        raise ValueError("trusted rate card is malformed")
    try:
        card = RateCard(**value).as_dict()
    except (TypeError, ValueError):
        raise ValueError("trusted rate card is malformed") from None
    if card != value:
        raise ValueError("trusted rate card is not canonical")
    return card


def _validate_current_environment(
    plan: Mapping[str, Any],
    corpus: Corpus,
    manifest_path: Path,
    trusted_rate_card: Mapping[str, Any],
) -> None:
    """Reject retained evidence produced by a stale candidate, grader, or runner."""
    identity = plan["identity"]
    selection = plan["selection"]
    graph_checks.valid_annual_identity(
        {**identity, "trial_id": selection["trials"][0]}, trial=True
    )
    graph_checks._container_execution(plan["container_execution"])
    private = "public_dataset_sha256" in corpus.manifest
    expected_dataset = (
        adapt_holdout_rows(corpus.rows, manifest_path=manifest_path)[0]["dataset_hash"]
        if private
        else corpus.manifest["dataset_sha256"]
    )
    source_digest = graph_checks.source_digest()
    rate_card = plan["rate_card"]
    current_grader_digest = graph_checks.grader_digest()
    legacy_2_2_grader = False
    if identity["grader_digest"] != current_grader_digest:
        try:
            manifest_sha256 = _sha(manifest_path.read_bytes())
        except OSError:
            manifest_sha256 = None
        legacy_2_2_grader = (
            not private
            and corpus.manifest.get("dataset_version") == _V2_DATASET_VERSION
            and corpus.manifest.get("dataset_sha256") == _V2_PUBLIC_DATASET_SHA256
            and manifest_sha256 == _V2_2_PUBLIC_MANIFEST_SHA256
            and identity["grader_digest"] == _V2_2_GRADER_DIGEST
        )
    if (
        identity["dataset_hash"] != expected_dataset
        or identity["source_digest"] != source_digest
        or identity["artifact_digest"] != source_digest
        or (
            identity["grader_digest"] != current_grader_digest and not legacy_2_2_grader
        )
        or rate_card != trusted_rate_card
        or identity["rate_card_source"] != rate_card["source"]
        or identity["rate_card_version"] != rate_card["version"]
        or identity["rate_card_hash"] != rate_card["digest"]
        or identity["rate_card_values_hash"]
        != graph_checks.annual_rate_card_values_digest(rate_card)
    ):
        raise ValueError("retained evidence environment is stale")


def _validated_split(
    manifest_path: Path,
    root: Path,
    trusted_rate_card: Mapping[str, Any],
    public_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a complete retained split without rewriting its sealed report."""
    manifest_path = _regular(manifest_path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("regular retained root required")
    root = root.resolve()
    if public_manifest_path is not None:
        public_manifest_path = _regular(public_manifest_path)
    corpus = _validated_manifest(manifest_path, public_manifest_path)
    plan = baseline._read(root / "manifest.json")
    selection = baseline.validate_selection(plan.get("selection", {}), corpus)
    if selection["phase"] != "baseline" or selection["trials"] != _TRIALS:
        raise ValueError("complete three-trial baseline required")
    _validate_current_environment(plan, corpus, manifest_path, trusted_rate_card)
    report = baseline._read(root / "report.json")
    if (
        report.get("artifact_type") != "fixture_baseline_report"
        or report.get("manifest_sha256") != baseline._digest(root / "manifest.json")
        or report.get("identity") != plan.get("identity")
        or report.get("container_execution") != plan.get("container_execution")
        or report.get("selection_digest") != plan.get("selection_digest")
    ):
        raise ValueError("retained report does not match its manifest")

    schema = baseline._read(
        Path(__file__).with_name("schemas") / "scorecard.schema.json"
    )
    private = "public_dataset_sha256" in corpus.manifest
    private_digests = (
        {
            item["case_id"]: item["row_digest"]
            for item in adapt_holdout_rows(corpus.rows, manifest_path=manifest_path)
        }
        if private
        else {}
    )
    trusted = {
        case_id: private_digests[case_id]
        if private
        else _case_digest(
            trusted_case_evidence(case_id, manifest_path=manifest_path)[0]
        )
        for case_id in selection["cases"]
    }
    items = [
        baseline._attempt(
            root / case_id / trial_id,
            case_id,
            trial_id,
            plan,
            schema,
            plan["identity"],
            plan["container_execution"],
            trusted[case_id],
            True,
        )
        for case_id in selection["cases"]
        for trial_id in selection["trials"]
    ]
    if any(item["state"] not in {"passed", "agent_quality_failure"} for item in items):
        raise ValueError("retained split contains invalid or incomplete evidence")
    if baseline._summary(items) != report.get("summary"):
        raise ValueError("retained report summary does not match evidence")

    receipt_entries = [
        [
            f"{case_id}/{trial_id}/receipt.json",
            baseline._digest(root / case_id / trial_id / "receipt.json"),
        ]
        for case_id in selection["cases"]
        for trial_id in selection["trials"]
    ]
    return {
        "corpus": corpus,
        "plan": plan,
        "report": report,
        "selection": selection,
        "items": items,
        "root": root,
        "manifest_path": manifest_path,
        "manifest_sha256": baseline._digest(manifest_path),
        "report_sha256": baseline._digest(root / "report.json"),
        "evidence_sha256": _sha(receipt_entries),
    }


def _category_breakdowns(split: Mapping[str, Any]) -> dict[str, Any]:
    categories: dict[str, list[dict[str, Any]]] = {}
    rows = {row["id"]: row for row in split["corpus"].rows}
    for item in split["items"]:
        category = rows[item["case_id"]]["primary_category"]
        categories.setdefault(category, []).append(item)
    return {
        "category": {
            category: baseline._summary(items)
            for category, items in sorted(categories.items())
        }
    }


def _identity(split: Mapping[str, Any]) -> dict[str, Any]:
    identity = split["plan"]["identity"]
    container = split["plan"]["container_execution"]
    return {
        "candidate": {
            **{
                key: identity[key]
                for key in (
                    "model",
                    "prompt_hash",
                    "tool_contract_hash",
                    "model_settings_hash",
                    "prompt_context_hash",
                    "render_date",
                )
            },
            "application_digest": _application_digest(),
        },
        "evaluator": {
            "grader_digest": identity["grader_digest"],
            "sealed_commit": identity["commit"],
        },
        "runner": {
            **dict(container),
            "sealed_artifact_digest": identity["artifact_digest"],
            "sealed_source_digest": identity["source_digest"],
        },
    }


def combined_report(
    public_manifest: Path,
    public_root: Path,
    private_manifest: Path,
    private_root: Path,
    rate_card_path: Path,
) -> dict[str, Any]:
    """Return a deterministic public report with aggregate-only private evidence."""
    rate_card = _trusted_rate_card(rate_card_path)
    public = _validated_split(public_manifest, public_root, rate_card)
    private = _validated_split(
        private_manifest,
        private_root,
        rate_card,
        public_manifest_path=public["manifest_path"],
    )
    public_declaration = public["corpus"].manifest
    private_declaration = private["corpus"].manifest
    if private_declaration.get("public_dataset_sha256") != public_declaration.get(
        "dataset_sha256"
    ) or private_declaration.get("public_membership_sha256") != public_declaration.get(
        "membership_sha256"
    ):
        raise ValueError("private evidence is not bound to the public dataset")
    if (
        public["report"].get("private") is not False
        or private["report"].get("private") is not True
    ):
        raise ValueError("public/private split roles are invalid")
    public_identity, private_identity = _identity(public), _identity(private)
    if public_identity != private_identity:
        raise ValueError(
            "public/private candidate, evaluator, or runner identity mismatch"
        )
    return {
        "artifact_type": "calibrated_fixture_evidence_report",
        "version": 1,
        "identity": public_identity,
        "datasets": {
            "public": public["plan"]["identity"]["dataset_hash"],
            "private": private["plan"]["identity"]["dataset_hash"],
        },
        "evidence": {
            name: {
                "manifest_sha256": split["manifest_sha256"],
                "run_manifest_sha256": split["report"]["manifest_sha256"],
                "report_sha256": split["report_sha256"],
                "receipts_sha256": split["evidence_sha256"],
            }
            for name, split in (("public", public), ("private", private))
        },
        "public": {
            "summary": baseline._summary(public["items"]),
            "breakdowns": _category_breakdowns(public),
            "results": [
                {key: value for key, value in item.items() if key != "observed_tools"}
                for item in public["items"]
            ],
        },
        "private": {
            "summary": baseline._summary(private["items"]),
            "breakdowns": _category_breakdowns(private),
        },
    }


def _safe(value: object, allowed: set[str]) -> object:
    if isinstance(value, list):
        return [_safe(item, allowed) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, object] = {}
    for key, item in value.items():
        if key not in allowed:
            continue
        if key == "facility" and isinstance(item, str):
            result["road"] = _FACILITIES.get(item, item.replace("_", " ").title())
        else:
            result[key] = _safe(item, allowed)
    return result


def _tool_projection(call: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lookup": "Annual toll estimate"
        if call.get("name") == "get_annual_toll_ballpark"
        else "Current toll lookup",
        "request": _safe(call.get("input", {}), _SAFE_REQUEST_FIELDS),
        "result": _safe(call.get("tool_result", {}), _SAFE_RESULT_FIELDS),
    }


def _review_cards(
    manifest_path: Path, root: Path, rate_card_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    split = _validated_split(manifest_path, root, _trusted_rate_card(rate_card_path))
    if split["report"].get("private") is not False:
        raise ValueError("review requires public evidence")
    rows = {row["id"]: row for row in split["corpus"].rows}
    cards = []
    for number, case_id in enumerate(baseline._PILOT_CASES, 1):
        row = rows[case_id]
        artifact = split["root"] / case_id / "1"
        output = baseline._read(artifact / "output.json")
        receipt = baseline._read(artifact / "receipt.json")
        display = {
            "conversation": list(row["conversation"]),
            "answer": output["output"],
            "expected": row["expected_assertion"],
            "tools": [
                _tool_projection(call)
                for turn in output.get("trajectory", [])
                for call in turn.get("calls", [])
            ],
        }
        binding = _sha(
            {
                "receipt": receipt,
                "case_digest": _sha(row),
                "manifest": split["manifest_sha256"],
                "display": display,
            }
        )
        cards.append(
            {
                "ref": f"review-{number:02d}-{binding[:12]}",
                "binding": binding,
                "display_sha256": _sha(display),
                **display,
            }
        )
    packet = {
        "version": 1,
        "public_manifest_sha256": split["manifest_sha256"],
        "evidence_sha256": split["evidence_sha256"],
        "cards": [
            {
                "ref": card["ref"],
                "binding": card["binding"],
                "display_sha256": card["display_sha256"],
            }
            for card in cards
        ],
    }
    return cards, packet


def render_review(
    manifest_path: Path, root: Path, rate_card_path: Path, output_path: Path
) -> Path:
    cards, packet = _review_cards(manifest_path, root, rate_card_path)

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    rendered = []
    for number, card in enumerate(cards, 1):
        conversation = "".join(f"<li>{esc(turn)}</li>" for turn in card["conversation"])
        tools = (
            "".join(
                f"<details><summary>{esc(tool['lookup'])}</summary>"
                f"<h4>Request</h4><pre>{esc(json.dumps(tool['request'], indent=2, ensure_ascii=False))}</pre>"
                f"<h4>Recorded result</h4><pre>{esc(json.dumps(tool['result'], indent=2, ensure_ascii=False))}</pre></details>"
                for tool in card["tools"]
            )
            or "<p>No pricing tool was used.</p>"
        )
        choices = "".join(
            f'<label><input required type="radio" name="label-{number}" value="{choice}"> {choice}</label>'
            for choice in ("Pass", "Fail", "Unsure")
        )
        rendered.append(
            f'<article class="card" data-ref="{esc(card["ref"])}" data-binding="{card["binding"]}">'
            f"<h2>Case {number}</h2><h3>Conversation</h3><ol>{conversation}</ol>"
            f'<h3>Retained answer</h3><div class="answer">{esc(card["answer"])}</div>'
            f"<h3>Recorded tool evidence</h3>{tools}<h3>Expected behavior</h3><p>{esc(card['expected'])}</p>"
            f"<fieldset><legend>Your decision</legend>{choices}</fieldset>"
            f'<label for="notes-{number}">Notes (optional)</label><textarea id="notes-{number}"></textarea></article>'
        )
    packet_json = json.dumps(packet, ensure_ascii=False, sort_keys=True).replace(
        "<", "\\u003c"
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TollChat calibration review</title><style>
body{{margin:0;background:#eef3f8;color:#17212b;font:16px/1.5 system-ui,sans-serif}}main{{max-width:960px;margin:auto;padding:2rem}}.card{{background:#fff;border:1px solid #c8d4df;border-radius:12px;box-shadow:0 3px 14px #23384d14;margin:1.25rem 0;padding:1.4rem}}.answer{{white-space:pre-wrap;background:#f7f9fb;border-left:4px solid #3973ac;padding:1rem}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#17212b;color:#eef6ff;padding:1rem;border-radius:6px}}fieldset{{display:flex;gap:1.2rem;margin:1rem 0}}textarea{{box-sizing:border-box;width:100%;min-height:5rem}}button{{background:#145b91;color:white;border:0;border-radius:6px;padding:.75rem 1rem;font-weight:700}}button:focus,input:focus,textarea:focus{{outline:3px solid #f4a024;outline-offset:2px}}#status{{font-weight:700}}
</style></head><body><main><h1>TollChat calibration review</h1><p>Review 30 retained public answers. Machine scores are intentionally hidden. Label every case, then download the bound JSON file.</p><p id="status" role="status">0 of 30 labeled</p>{"".join(rendered)}<button id="download" type="button">Download labels</button></main>
<script>const base={packet_json},cards=[...document.querySelectorAll('.card')],status=document.querySelector('#status');function update(){{status.textContent=`${{cards.filter((c,i)=>document.querySelector(`input[name=label-${{i+1}}]:checked`)).length}} of ${{cards.length}} labeled`}}document.addEventListener('change',update);document.querySelector('#download').addEventListener('click',()=>{{const labels=cards.map((card,i)=>{{const chosen=document.querySelector(`input[name=label-${{i+1}}]:checked`);return chosen?{{ref:card.dataset.ref,binding:card.dataset.binding,label:chosen.value,notes:document.querySelector(`#notes-${{i+1}}`).value}}:null}});if(labels.some(x=>!x)){{status.textContent='Label every case before downloading.';return}}const packet={{...base,labels}},blob=new Blob([JSON.stringify(packet,null,2)+'\\n'],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='tollchat-calibration-labels.json';a.click();URL.revokeObjectURL(a.href)}});</script></body></html>"""
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("calibration output already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(document)
    return output_path


def validate_labels(
    value: Mapping[str, Any],
    manifest_path: Path,
    root: Path,
    rate_card_path: Path,
) -> dict[str, Any]:
    _, expected = _review_cards(manifest_path, root, rate_card_path)
    if any(
        value.get(key) != expected[key]
        for key in ("version", "public_manifest_sha256", "evidence_sha256", "cards")
    ):
        raise ValueError("label packet evidence binding mismatch")
    labels = value.get("labels")
    expected_cards = {card["ref"]: card["binding"] for card in expected["cards"]}
    if (
        not isinstance(labels, list)
        or len(labels) != len(expected_cards)
        or {item.get("ref") for item in labels if isinstance(item, dict)}
        != set(expected_cards)
        or any(
            not isinstance(item, dict)
            or set(item) != {"ref", "binding", "label", "notes"}
            or item.get("binding") != expected_cards.get(item.get("ref"))
            or item.get("label") not in _LABELS
            or not isinstance(item.get("notes"), str)
            for item in labels
        )
    ):
        raise ValueError("label packet decisions are invalid")
    return dict(value)


def _v2_selection(kind: str, corpus: Corpus) -> dict[str, Any]:
    """Return the one reviewed v2 selection declared for ``kind``."""
    if kind not in _V2_SELECTIONS:
        raise ValueError("unknown v2 selection kind")
    manifest = corpus.manifest
    if "public_dataset_sha256" in manifest:
        raise ValueError("v2 review requires public evidence")
    if (
        manifest.get("dataset_version") != _V2_DATASET_VERSION
        or manifest.get("render_date") != _V2_RENDER_DATE
        or manifest.get("dataset_sha256") != _V2_PUBLIC_DATASET_SHA256
    ):
        raise ValueError("v2 selection requires the approved public 2.2.0 dataset")
    rows = {row["id"]: row for row in corpus.rows}
    cases = _V2_SELECTIONS[kind]
    if any(case_id not in rows for case_id in cases):
        raise ValueError("v2 selection contains an unknown public case")
    if len(set(cases)) != len(cases):
        raise ValueError("v2 selection contains duplicate cases")
    if kind == "balanced":
        counts = {category: 0 for category in _V2_CATEGORIES}
        for case_id in cases:
            category = rows[case_id].get("primary_category")
            if category not in counts:
                raise ValueError("balanced selection contains an unknown category")
            counts[category] += 1
        if counts != dict.fromkeys(_V2_CATEGORIES, 5):
            raise ValueError("balanced selection requires five cases per category")
        if set(cases) & set(baseline._PILOT_CASES):
            raise ValueError("balanced selection overlaps the v1 pilot")
    return {
        "kind": kind,
        "dataset_version": _V2_DATASET_VERSION,
        "dataset_sha256": manifest["dataset_sha256"],
        "render_date": _V2_RENDER_DATE,
        "cases": list(cases),
    }


def validate_v2_selection(
    selection: Mapping[str, Any], corpus: Corpus
) -> dict[str, Any]:
    """Validate an explicit v2 selection against the public corpus."""
    if not isinstance(selection, Mapping):
        raise ValueError("v2 selection is malformed")
    kind = selection.get("kind")
    if not isinstance(kind, str):
        raise ValueError("v2 selection kind is required")
    expected = _v2_selection(kind, corpus)
    if dict(selection) != expected:
        raise ValueError("v2 selection disagrees with its declaration")
    return expected


def v2_selection(kind: str, manifest_path: Path) -> dict[str, Any]:
    """Build a declared v2 selection from one validated public manifest."""
    corpus = _validated_manifest(_regular(manifest_path))
    return _v2_selection(kind, corpus)


def _trajectory_projection(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project every retained turn while keeping tool evidence turn-local."""
    trajectory = output.get("trajectory")
    if type(trajectory) is not list or not trajectory:
        raise ValueError("retained trajectory is missing")
    projected: list[dict[str, Any]] = []
    for turn in trajectory:
        if (
            not isinstance(turn, Mapping)
            or not isinstance(turn.get("prompt"), str)
            or not isinstance(turn.get("response"), str)
            or type(turn.get("calls")) is not list
        ):
            raise ValueError("retained trajectory turn is malformed")
        calls = turn["calls"]
        if any(not isinstance(call, Mapping) for call in calls):
            raise ValueError("retained trajectory tool call is malformed")
        projected.append(
            {
                "prompt": turn["prompt"],
                "response": turn["response"],
                "tools": [_tool_projection(call) for call in calls],
            }
        )
    return projected


def _v2_review_cards(
    manifest_path: Path,
    root: Path,
    rate_card_path: Path,
    kind: str,
    selection: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate the complete split, then project only selected trial-1 output."""
    split = _validated_split(manifest_path, root, _trusted_rate_card(rate_card_path))
    if split["report"].get("private") is not False:
        raise ValueError("v2 review requires public evidence")
    declared = _v2_selection(kind, split["corpus"])
    selected = (
        declared
        if selection is None
        else validate_v2_selection(selection, split["corpus"])
    )
    selection_sha256 = graph_checks.annual_json_digest(selected)
    rows = {row["id"]: row for row in split["corpus"].rows}
    cards: list[dict[str, Any]] = []
    for number, case_id in enumerate(selected["cases"], 1):
        row = rows[case_id]
        artifact = split["root"] / case_id / "1"
        output = baseline._read(artifact / "output.json")
        receipt = baseline._read(artifact / "receipt.json")
        trajectory = _trajectory_projection(output)
        answer = output.get("output")
        expected = row.get("expected_assertion")
        if not isinstance(answer, str) or not isinstance(expected, str):
            raise ValueError("retained review text is malformed")
        display = {
            "trajectory": trajectory,
            "answer": answer,
            "expected": expected,
        }
        binding = _sha(
            {
                "selection": selection_sha256,
                "manifest": split["manifest_sha256"],
                "evidence": _sha({"receipt": receipt, "output": output}),
                "receipt": receipt,
                "trial_1_output": output,
                "case_digest": _sha(row),
                "display": display,
            }
        )
        cards.append(
            {
                "ref": f"v2-{kind}-{number:02d}-{binding[:12]}",
                "binding": binding,
                "display_sha256": _sha(display),
                **display,
            }
        )
    packet = {
        "version": 2,
        "selection": {
            key: selected[key]
            for key in ("kind", "dataset_version", "dataset_sha256", "render_date")
        },
        "selection_sha256": selection_sha256,
        "public_manifest_sha256": split["manifest_sha256"],
        "evidence_sha256": split["evidence_sha256"],
        "cards": [
            {
                "ref": card["ref"],
                "binding": card["binding"],
                "display_sha256": card["display_sha256"],
            }
            for card in cards
        ],
    }
    return cards, packet


def v2_review_cards(
    manifest_path: Path,
    root: Path,
    rate_card_path: Path,
    kind: str,
    selection: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Public wrapper for deterministic, offline v2 card generation."""
    return _v2_review_cards(manifest_path, root, rate_card_path, kind, selection)


def render_v2_review(
    manifest_path: Path,
    root: Path,
    rate_card_path: Path,
    output_path: Path,
    kind: str,
    selection: Mapping[str, Any] | None = None,
) -> Path:
    cards, packet = _v2_review_cards(
        manifest_path, root, rate_card_path, kind, selection
    )

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    rendered = []
    for number, card in enumerate(cards, 1):
        turns = []
        for turn_number, turn in enumerate(card["trajectory"], 1):
            tools = (
                "".join(
                    f"<details><summary>{esc(tool['lookup'])}</summary>"
                    f"<h5>Request</h5><pre>{esc(json.dumps(tool['request'], indent=2, ensure_ascii=False))}</pre>"
                    f"<h5>Recorded result</h5><pre>{esc(json.dumps(tool['result'], indent=2, ensure_ascii=False))}</pre></details>"
                    for tool in turn["tools"]
                )
                or "<p>No pricing tool was used.</p>"
            )
            turns.append(
                f"<section><h3>Turn {turn_number}</h3>"
                f"<h4>Prompt</h4><div class=prompt>{esc(turn['prompt'])}</div>"
                f"<h4>Response</h4><div class=response>{esc(turn['response'])}</div>"
                f"<h4>Recorded tool evidence</h4>{tools}</section>"
            )
        choices = "".join(
            f'<label><input required type="radio" name="label-{number}" value="{choice}"> {choice}</label>'
            for choice in ("Pass", "Fail", "Unsure")
        )
        rendered.append(
            f'<article class="card" data-ref="{esc(card["ref"])}" data-binding="{esc(card["binding"])}">'
            f"<h2>Case {number}</h2>{''.join(turns)}"
            f"<h3>Retained final answer</h3><div class=answer>{esc(card['answer'])}</div>"
            f"<h3>Expected behavior</h3><p>{esc(card['expected'])}</p>"
            f"<fieldset><legend>Your decision</legend>{choices}</fieldset>"
            f'<label for="notes-{number}">Notes (optional)</label><textarea id="notes-{number}"></textarea></article>'
        )
    packet_json = json.dumps(packet, ensure_ascii=False, sort_keys=True).replace(
        "<", "\\u003c"
    )
    count = len(cards)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TollChat v2 calibration review</title><style>
body{{margin:0;background:#eef3f8;color:#17212b;font:16px/1.5 system-ui,sans-serif}}main{{max-width:960px;margin:auto;padding:2rem}}.card{{background:#fff;border:1px solid #c8d4df;border-radius:12px;box-shadow:0 3px 14px #23384d14;margin:1.25rem 0;padding:1.4rem}}.prompt,.response,.answer{{white-space:pre-wrap;background:#f7f9fb;border-left:4px solid #3973ac;padding:1rem}}.response{{border-left-color:#4a8b5d}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#17212b;color:#eef6ff;padding:1rem;border-radius:6px}}fieldset{{display:flex;gap:1.2rem;margin:1rem 0}}textarea{{box-sizing:border-box;width:100%;min-height:5rem}}button{{background:#145b91;color:white;border:0;border-radius:6px;padding:.75rem 1rem;font-weight:700}}button:focus,input:focus,textarea:focus{{outline:3px solid #f4a024;outline-offset:2px}}#status{{font-weight:700}}
</style></head><body><main><h1>TollChat v2 calibration review</h1><p>Review {count} retained public answers. Machine scores are intentionally hidden. Label every case, then download the bound JSON file.</p><p id="status" role="status">0 of {count} labeled</p>{"".join(rendered)}<button id="download" type="button">Download labels</button></main>
<script>const base={packet_json},cards=[...document.querySelectorAll('.card')],status=document.querySelector('#status');function update(){{status.textContent=`${{cards.filter((c,i)=>document.querySelector(`input[name=label-${{i+1}}]:checked`)).length}} of ${{cards.length}} labeled`}}document.addEventListener('change',update);document.querySelector('#download').addEventListener('click',()=>{{const labels=cards.map((card,i)=>{{const chosen=document.querySelector(`input[name=label-${{i+1}}]:checked`);return chosen?{{ref:card.dataset.ref,binding:card.dataset.binding,label:chosen.value,notes:document.querySelector(`#notes-${{i+1}}`).value}}:null}});if(labels.some(x=>!x)){{status.textContent='Label every case before downloading.';return}}const packet={{...base,labels}},blob=new Blob([JSON.stringify(packet,null,2)+'\\n'],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='tollchat-v2-calibration-labels.json';a.click();URL.revokeObjectURL(a.href)}});</script></body></html>"""
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("calibration output already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(document)
    return output_path


def validate_v2_labels(
    value: Mapping[str, Any],
    manifest_path: Path,
    root: Path,
    rate_card_path: Path,
    kind: str,
    selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _, expected = _v2_review_cards(manifest_path, root, rate_card_path, kind, selection)
    if (
        not isinstance(value, Mapping)
        or set(value) != set(expected) | {"labels"}
        or any(value.get(key) != expected[key] for key in expected)
    ):
        raise ValueError("v2 label packet evidence binding mismatch")
    labels = value.get("labels")
    expected_cards = {card["ref"]: card["binding"] for card in expected["cards"]}
    if (
        not isinstance(labels, list)
        or len(labels) != len(expected_cards)
        or {item.get("ref") for item in labels if isinstance(item, dict)}
        != set(expected_cards)
        or any(
            not isinstance(item, dict)
            or set(item) != {"ref", "binding", "label", "notes"}
            or item.get("binding") != expected_cards.get(item.get("ref"))
            or item.get("label") not in _LABELS
            or not isinstance(item.get("notes"), str)
            for item in labels
        )
    ):
        raise ValueError("v2 label packet decisions are invalid")
    return dict(value)


def _validated_label_ledger(
    ledger_path: Path, public_manifest_path: Path
) -> tuple[dict[str, Any], Corpus]:
    ledger_path = _regular(ledger_path)
    public_manifest_path = _regular(public_manifest_path)
    value = graph_checks.read_json(ledger_path)
    corpus = _validated_manifest(public_manifest_path)
    expected_bindings = {
        "current_public": {
            "dataset_version": _V2_3_DATASET_VERSION,
            "dataset_sha256": _V2_3_PUBLIC_DATASET_SHA256,
            "membership_sha256": _V2_3_MEMBERSHIP_SHA256,
        },
        "retained_public": {
            "dataset_version": _V2_DATASET_VERSION,
            "dataset_sha256": _V2_PUBLIC_DATASET_SHA256,
            "manifest_sha256": _V2_2_PUBLIC_MANIFEST_SHA256,
            "evidence_sha256": _V2_2_EVIDENCE_SHA256,
        },
        "returned_packets": {
            "balanced_sha256": _BALANCED_PACKET_SHA256,
            "follow_up_sha256": _FOLLOW_UP_PACKET_SHA256,
        },
        "historical_pilot": {
            "record": "maintainer_approved_26_pass_1_fail_3_unsure",
            "original_packet": "unavailable",
        },
    }
    if (
        not isinstance(value, dict)
        or set(value) != {"artifact_type", "version", "bindings", "labels"}
        or value.get("artifact_type") != "human_calibration_labels"
        or value.get("version") != 1
        or value.get("bindings") != expected_bindings
        or corpus.manifest.get("dataset_version") != _V2_3_DATASET_VERSION
        or corpus.manifest.get("dataset_sha256") != _V2_3_PUBLIC_DATASET_SHA256
        or corpus.manifest.get("membership_sha256") != _V2_3_MEMBERSHIP_SHA256
    ):
        raise ValueError("human label ledger binding mismatch")
    labels = value.get("labels")
    if (
        not isinstance(labels, list)
        or len(labels) != 60
        or any(
            not isinstance(item, dict)
            or set(item) != {"case_id", "verdict", "source"}
            or not isinstance(item.get("case_id"), str)
            or not item["case_id"]
            or item.get("verdict") not in {"Pass", "Fail"}
            or item.get("source") not in _LABEL_SOURCES
            for item in labels
        )
    ):
        raise ValueError("human label ledger decisions are invalid")
    typed = list(labels)
    case_ids = [item["case_id"] for item in typed]
    rows = {row["id"]: row for row in corpus.rows}
    reviewed = sorted(
        case_id
        for case_id, row in rows.items()
        if row.get("review_status") == "human_reviewed"
    )
    pilot = set(baseline._PILOT_CASES) - set(_V2_FOLLOW_UP_CASES)
    expected_sources = {
        "retained_historical_pilot": pilot,
        "returned_follow_up_packet": set(_V2_FOLLOW_UP_CASES),
        "returned_balanced_packet": set(_V2_BALANCED_CASES),
    }
    actual_sources = {
        source: {item["case_id"] for item in typed if item["source"] == source}
        for source in _LABEL_SOURCES
    }
    if (
        case_ids != sorted(case_ids)
        or len(set(case_ids)) != len(case_ids)
        or case_ids != reviewed
        or actual_sources != expected_sources
        or sum(item["verdict"] == "Pass" for item in typed) != 50
        or sum(item["verdict"] == "Fail" for item in typed) != 10
        or next(
            (
                item["verdict"]
                for item in typed
                if item["case_id"] == "topology-probe-dca-to-iad-current"
            ),
            None,
        )
        != "Fail"
        or sum(
            item["verdict"] == "Pass"
            for item in typed
            if item["source"] == "returned_balanced_packet"
        )
        != 21
    ):
        raise ValueError("human label ledger membership mismatch")
    return value, corpus


def _empty_matrix() -> dict[str, int]:
    return {
        "human_pass_evaluator_pass": 0,
        "human_pass_evaluator_fail": 0,
        "human_fail_evaluator_pass": 0,
        "human_fail_evaluator_fail": 0,
    }


def compare_labels(
    label_ledger: Path,
    public_manifest: Path,
    retained_manifest: Path,
    public_root: Path,
    rate_card: Path,
) -> dict[str, Any]:
    """Compare reviewed trial-1 labels with freshly recomputed evaluator results."""
    ledger, current = _validated_label_ledger(label_ledger, public_manifest)
    retained = _validated_split(
        retained_manifest, public_root, _trusted_rate_card(rate_card)
    )
    if (
        retained["manifest_sha256"] != _V2_2_PUBLIC_MANIFEST_SHA256
        or retained["evidence_sha256"] != _V2_2_EVIDENCE_SHA256
        or retained["report"].get("private") is not False
    ):
        raise ValueError("immutable retained evidence binding mismatch")
    rows = {row["id"]: row for row in current.rows}
    overall = _empty_matrix()
    categories: dict[str, dict[str, int]] = {}
    disagreements = []
    for label in ledger["labels"]:
        case_id = label["case_id"]
        score = graph_checks.score_annual(
            retained["root"] / case_id / "1",
            retained["root"] / case_id / "1" / "case.json",
            retained["manifest_path"],
            accepted_grader_digest=_V2_2_GRADER_DIGEST,
        )
        if score["failure_class"] == "infra_dependency":
            raise ValueError("current evaluator could not score retained evidence")
        evaluator = "pass" if score["pass"] else "fail"
        human = label["verdict"].lower()
        key = f"human_{human}_evaluator_{evaluator}"
        overall[key] += 1
        category = rows[case_id]["primary_category"]
        categories.setdefault(category, _empty_matrix())[key] += 1
        if human != evaluator:
            disagreements.append(
                {
                    "case_id": case_id,
                    "human_verdict": label["verdict"],
                    "evaluator_verdict": evaluator.title(),
                    "failed_check_ids": sorted(
                        check["id"] for check in score["checks"] if not check["pass"]
                    ),
                }
            )
    return {
        "artifact_type": "evaluator_calibration_report",
        "version": 1,
        "bindings": {
            "label_ledger_sha256": baseline._digest(_regular(label_ledger)),
            "current_public_dataset_sha256": _V2_3_PUBLIC_DATASET_SHA256,
            "current_public_membership_sha256": _V2_3_MEMBERSHIP_SHA256,
            "retained_public_manifest_sha256": retained["manifest_sha256"],
            "retained_public_dataset_sha256": _V2_PUBLIC_DATASET_SHA256,
            "retained_evidence_sha256": retained["evidence_sha256"],
            "current_grader_digest": graph_checks.grader_digest(),
        },
        "counts": {"reviewed": 60, "human_pass": 50, "human_fail": 10},
        "overall": overall,
        "categories": {key: categories[key] for key in sorted(categories)},
        "disagreements": sorted(disagreements, key=lambda item: item["case_id"]),
    }


def _write(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("calibration output already exists")
    parent = path.parent
    if (
        not parent.is_dir()
        or parent.is_symlink()
        or parent.resolve() != parent.absolute()
    ):
        raise ValueError("regular existing output directory required")
    with path.open("x", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                value,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review")
    review.add_argument("--public-manifest", type=Path, required=True)
    review.add_argument("--public-root", type=Path, required=True)
    review.add_argument("--rate-card", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review_v2 = commands.add_parser("review-v2")
    review_v2.add_argument("--public-manifest", type=Path, required=True)
    review_v2.add_argument("--public-root", type=Path, required=True)
    review_v2.add_argument("--rate-card", type=Path, required=True)
    review_v2.add_argument("--output", type=Path, required=True)
    review_v2.add_argument("--kind", choices=tuple(_V2_SELECTIONS), required=True)
    combine = commands.add_parser("combine")
    for name in ("public-manifest", "public-root", "private-manifest", "private-root"):
        combine.add_argument(f"--{name}", type=Path, required=True)
    combine.add_argument("--rate-card", type=Path, required=True)
    combine.add_argument("--output", type=Path, required=True)
    labels = commands.add_parser("validate-labels")
    labels.add_argument("--public-manifest", type=Path, required=True)
    labels.add_argument("--public-root", type=Path, required=True)
    labels.add_argument("--rate-card", type=Path, required=True)
    labels.add_argument("--labels", type=Path, required=True)
    labels_v2 = commands.add_parser("validate-v2-labels")
    labels_v2.add_argument("--public-manifest", type=Path, required=True)
    labels_v2.add_argument("--public-root", type=Path, required=True)
    labels_v2.add_argument("--rate-card", type=Path, required=True)
    labels_v2.add_argument("--labels", type=Path, required=True)
    labels_v2.add_argument("--kind", choices=tuple(_V2_SELECTIONS), required=True)
    comparison = commands.add_parser("compare-labels")
    for name in (
        "label-ledger",
        "public-manifest",
        "retained-manifest",
        "public-root",
        "rate-card",
        "output",
    ):
        comparison.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "review":
        render_review(
            args.public_manifest, args.public_root, args.rate_card, args.output
        )
    elif args.command == "review-v2":
        render_v2_review(
            args.public_manifest,
            args.public_root,
            args.rate_card,
            args.output,
            args.kind,
        )
    elif args.command == "combine":
        _write(
            args.output,
            combined_report(
                args.public_manifest,
                args.public_root,
                args.private_manifest,
                args.private_root,
                args.rate_card,
            ),
        )
    elif args.command == "validate-labels":
        validate_labels(
            graph_checks.read_json(_regular(args.labels)),
            args.public_manifest,
            args.public_root,
            args.rate_card,
        )
    elif args.command == "validate-v2-labels":
        validate_v2_labels(
            graph_checks.read_json(_regular(args.labels)),
            args.public_manifest,
            args.public_root,
            args.rate_card,
            args.kind,
        )
    else:
        _write(
            args.output,
            compare_labels(
                args.label_ledger,
                args.public_manifest,
                args.retained_manifest,
                args.public_root,
                args.rate_card,
            ),
        )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit("calibration input validation failed") from None

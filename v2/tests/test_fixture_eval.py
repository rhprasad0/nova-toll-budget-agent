"""Synthetic tooling checks for the trusted annual fixture boundary."""

# pyright: basic

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from eval import graph_checks
from eval.fixture_eval import (
    _model_settings,
    _safe_model_settings,
    adapt_holdout_rows,
    aggregate_holdout_run,
    aggregate_public_run,
    holdout_case_document,
    packet_for_case,
    packet_for_holdout,
    run_and_seal_trial,
    trusted_case_evidence,
)
from eval.fixture_runner import RateCard, run_fixture_trial
from eval.golden_corpus import validate
from eval.graph_checks import read_json

_POINT = {
    "point_id": "greenway:1:entry:EB",
    "network_id": "greenway",
    "source_node_id": "1",
    "point_type": "entry",
    "direction": "EB",
    "label": "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
    "aliases": ["Leesburg"],
    "location": {"type": "Point", "coordinates": [-77.5652813, 39.1000972]},
}
_RATE_CARD = RateCard("synthetic-tooling", "v1", "a" * 64, 10, 20, 30)


class _FakeModel:
    """A deterministic Strands model used only by offline tooling checks."""

    stateful = False

    def __init__(self, packet: Any, *, unavailable: bool = False) -> None:
        self.packet = packet
        self.unavailable = unavailable
        self.stream_count = 0

    def get_config(self) -> dict[str, Any]:
        return {"model_id": "synthetic-tooling", "params": {"temperature": 0}}

    def stream(
        self,
        messages: list[dict[str, Any]],
        tool_specs: object = None,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> Any:
        del tool_specs, system_prompt, kwargs
        self.stream_count += 1
        has_tool_result = any(
            type(message) is dict
            and any(
                type(block) is dict and "toolResult" in block
                for block in message.get("content", [])
            )
            for message in messages
        )
        request = self.packet.fixture_request
        answer = (
            "### 🚧 Annual toll estimate unavailable\n"
            "I couldn't produce the affordability estimate because the return trip "
            "from Reagan Airport to the Dulles Airport area has no supported route "
            "in the registered coverage.\n"
            "- Outbound: route validated\n"
            "- Return: no supported route\n"
            "- Therefore, no toll, vehicle-cost, or remaining-income totals are available\n"
            "This tool covers only the tolled portion of validated Northern Virginia trips. 🚗"
            if self.unavailable
            else "### 🚫 Winchester is unsupported; please provide supported endpoints."
        )

        async def events() -> Any:
            yield {"messageStart": {"role": "assistant"}}
            if request is not None and not has_tool_result:
                yield {
                    "contentBlockStart": {
                        "start": {
                            "toolUse": {
                                "toolUseId": "synthetic-call",
                                "name": "get_annual_toll_ballpark",
                            }
                        }
                    }
                }
                yield {
                    "contentBlockDelta": {
                        "delta": {"toolUse": {"input": json.dumps(request)}}
                    }
                }
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "tool_use"}}
            else:
                yield {"contentBlockStart": {"start": {"text": ""}}}
                yield {"contentBlockDelta": {"delta": {"text": answer}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "end_turn"}}
            yield {
                "metadata": {
                    "usage": {
                        "inputTokens": 4,
                        "outputTokens": 2,
                        "totalTokens": 6,
                        "cacheReadInputTokens": 1,
                    }
                },
                "metrics": {"latencyMs": 0},
            }

        return events()


def _packet(case_id: str) -> Any:
    return packet_for_case(
        case_id,
        prompt_points=[_POINT],
        render_date=date(2026, 9, 5),
    )


def test_actual_strands_fixture_trial_seals_and_grades(tmp_path: Path) -> None:
    packet = _packet("dulles-to-reagan-annual-unavailable")
    case_bytes, dataset_hash, _ = trusted_case_evidence(packet.case_id)
    artifact = tmp_path / "case" / "1"

    result = run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
    )

    assert result == 0
    output = read_json(artifact / "output.json")
    assert output["trajectory"][0]["calls"][0]["tool_result"] == packet.fixture_payload
    assert read_json(artifact / "run.json")["output_digest"]
    assert read_json(artifact / "scorecard.json")["pass"] is True


def test_two_public_cases_have_three_independent_sealed_trials(tmp_path: Path) -> None:
    cases = (
        ("dulles-to-reagan-annual-unavailable", True),
        ("winchester-unsupported-location-refusal", False),
    )
    identities: list[dict[str, str]] = []
    for case_id, unavailable in cases:
        packet = _packet(case_id)
        case_bytes, dataset_hash, _ = trusted_case_evidence(case_id)
        for trial_id in ("1", "2", "3"):
            artifact = tmp_path / case_id / trial_id
            assert (
                run_and_seal_trial(
                    packet,
                    model=_FakeModel(packet, unavailable=unavailable),
                    artifact_root=artifact,
                    trial_id=trial_id,
                    rate_card=_RATE_CARD,
                    case_bytes=case_bytes,
                    dataset_hash=dataset_hash,
                )
                == 0
            )
            run = read_json(artifact / "run.json")
            identities.append(run["identity"])
            assert read_json(artifact / "scorecard.json")["pass"] is True

    assert [identity["trial_id"] for identity in identities] == [
        "1",
        "2",
        "3",
        "1",
        "2",
        "3",
    ]
    common_identity = {
        key: identities[0][key] for key in identities[0] if key != "trial_id"
    }
    # A partial public set cannot be promoted to a public manifest.  The parent
    # executor supplies the remaining public cases before aggregation/comparison.
    with pytest.raises(ValueError, match="public annual case order"):
        aggregate_public_run(
            tmp_path,
            cases=[case_id for case_id, _ in cases],
            identity=common_identity,
        )


def test_two_synthetic_holdout_rows_aggregate_and_compare(tmp_path: Path) -> None:
    public_rows = {row["id"]: row for row in validate().annual_rows}
    source_rows = (
        deepcopy(public_rows["dulles-to-reagan-annual-unavailable"]),
        deepcopy(public_rows["winchester-unsupported-location-refusal"]),
    )
    source_rows[0]["id"] = "tooling-holdout-unavailable"
    source_rows[1]["id"] = "tooling-holdout-unsupported"
    adapted_rows = adapt_holdout_rows(source_rows)
    assert len({row["dataset_hash"] for row in adapted_rows}) == 1
    assert all(row["row_digest"] for row in adapted_rows)
    assert adapted_rows[0]["holdout_membership"] == sorted(
        adapted_rows[0]["holdout_membership"]
    )

    for adapted in adapted_rows:
        packet, case_bytes, dataset_hash = packet_for_holdout(
            adapted,
            prompt_points=[_POINT],
            render_date=date(2026, 9, 5),
        )
        for trial_id in ("1", "2", "3"):
            artifact = tmp_path / "heldout" / adapted["case_id"] / trial_id
            unavailable = adapted["fixture_id"] is not None
            assert (
                run_and_seal_trial(
                    packet,
                    model=_FakeModel(packet, unavailable=unavailable),
                    artifact_root=artifact,
                    trial_id=trial_id,
                    rate_card=_RATE_CARD,
                    case_bytes=case_bytes,
                    dataset_hash=dataset_hash,
                    case_document=holdout_case_document(adapted),
                )
                == 0
            )

    first_run = read_json(
        tmp_path / "heldout" / adapted_rows[0]["case_id"] / "1" / "run.json"
    )
    identity = {
        key: first_run["identity"][key]
        for key in first_run["identity"]
        if key != "trial_id"
    }
    holdout = aggregate_holdout_run(
        tmp_path / "heldout",
        cases=[row["case_id"] for row in adapted_rows],
        identity=identity,
        mode="pin",
    )
    assert read_json(holdout / "report.json")["results"][0]["cost"]
    assert graph_checks.load_run(holdout)[0]["suite"] == "annual-heldout"
    copied = tmp_path / "heldout-copy"
    shutil.copytree(holdout, copied)
    assert graph_checks.compare(holdout, copied) == 0


def test_two_turn_usage_is_per_invocation_and_cache_is_charged_separately(
    tmp_path: Path,
) -> None:
    packet = _packet("springfield-franconia-tysons-annual-affordability")
    # The fake emits the same valid usage on each SDK invocation.  The packet has
    # two user turns, so the runner must retain two measurements rather than use
    # the cumulative summary from the second response.
    result = run_fixture_trial(
        packet,
        model=_FakeModel(packet),
        artifact_root=tmp_path / "case" / "1",
        trial_id="1",
        rate_card=_RATE_CARD,
    )

    assert result["failure_class"] == "none"
    output = result["output"]
    assert len(output["measurements"]["turns"]) == 2
    assert output["measurements"]["tokens"] == 18
    # inputTokens includes one cached token for each invocation.
    assert output["cost"]["input_usd"] == 90 / 1_000_000
    assert output["cost"]["cache_usd"] == 3 * 30 / 1_000_000


def test_forged_fixture_payload_and_matching_prose_fail_before_grading(
    tmp_path: Path,
) -> None:
    packet = _packet("dulles-to-reagan-annual-unavailable")
    case_bytes, dataset_hash, _ = trusted_case_evidence(packet.case_id)
    artifact = tmp_path / "case" / "1"
    run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
    )

    output = read_json(artifact / "output.json")
    call = output["trajectory"][0]["calls"][0]
    forged = dict(call["tool_result"])
    forged["return"] = {"status": "valid", "reason": None}
    call["tool_result"] = forged
    output["output"] = "# Annual toll estimate unavailable 🚫"
    (artifact / "output.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Refresh only the raw-file digest to model a forged runner that attempts to
    # make its changed evidence look internally consistent.  The trusted grader
    # still compares the payload to the validated fixture bytes.
    run = read_json(artifact / "run.json")
    raw_digest = b"".join(
        name.encode() + b"\0" + (artifact / name).read_bytes() + b"\0"
        for name in ("output.json", "stdout.txt", "exit_code.json")
    )
    import hashlib

    run["output_digest"] = hashlib.sha256(raw_digest).hexdigest()
    (artifact / "run.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    case_path = tmp_path / "case.json"
    case_path.write_text(
        json.dumps({"case_id": packet.case_id, "suite": "annual"}) + "\n",
        encoding="utf-8",
    )
    assert graph_checks.grade(artifact, case_path) == 1
    score = read_json(artifact / "scorecard.json")
    assert score["pass"] is False


def test_annual_marker_never_falls_back_to_generic_grader(tmp_path: Path) -> None:
    artifact = tmp_path / "annual-marker"
    artifact.mkdir()
    (artifact / "run.json").write_text(
        json.dumps({"artifact_type": "annual_fixture_trial"}) + "\n",
        encoding="utf-8",
    )
    (artifact / "output.json").write_text("{}\n", encoding="utf-8")
    (artifact / "stdout.txt").write_text("hello\n", encoding="utf-8")
    (artifact / "exit_code.json").write_text("0\n", encoding="utf-8")
    case = tmp_path / "generic-case.json"
    case.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "prompt": "synthetic",
                "setup": {},
                "expected": {"exit_code": 0, "stdout_contains": ["hello"]},
                "rubric": ["contract-1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert graph_checks.grade(artifact, case) == 1
    assert read_json(artifact / "scorecard.json")["failure_class"] == (
        "infra_dependency"
    )


def test_annual_prompt_ids_and_rate_numbers_are_trusted(tmp_path: Path) -> None:
    packet = _packet("dulles-to-reagan-annual-unavailable")
    case_bytes, dataset_hash, _ = trusted_case_evidence(packet.case_id)
    artifact = tmp_path / "case" / "1"
    run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
    )
    output = read_json(artifact / "output.json")
    output["trajectory"][0]["prompt"] = "forged prompt"
    output["cost"]["rate_card"]["input_rate_usd_per_million"] = 999
    output["cost"]["input_usd"] = 999 / 1_000_000
    (artifact / "output.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run = read_json(artifact / "run.json")
    run["cost"] = output["cost"]
    run["output_digest"] = hashlib.sha256(
        b"".join(
            name.encode() + b"\0" + (artifact / name).read_bytes() + b"\0"
            for name in ("output.json", "stdout.txt", "exit_code.json")
        )
    ).hexdigest()
    (artifact / "run.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    case = tmp_path / "case.json"
    case.write_text(
        json.dumps({"case_id": packet.case_id, "suite": "annual"}) + "\n",
        encoding="utf-8",
    )
    assert graph_checks.grade(artifact, case) == 1
    assert read_json(artifact / "scorecard.json")["failure_class"] == (
        "infra_dependency"
    )


def test_annual_tool_use_ids_and_result_correlation_are_required(
    tmp_path: Path,
) -> None:
    packet = _packet("dulles-to-reagan-annual-unavailable")
    case_bytes, dataset_hash, _ = trusted_case_evidence(packet.case_id)
    artifact = tmp_path / "case" / "1"
    run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
    )
    output = read_json(artifact / "output.json")
    output["trajectory"][0]["calls"][0]["toolUseId"] = None
    (artifact / "output.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    case = tmp_path / "case.json"
    case.write_text(
        json.dumps({"case_id": packet.case_id, "suite": "annual"}) + "\n",
        encoding="utf-8",
    )
    assert graph_checks.grade(artifact, case) == 1
    assert read_json(artifact / "scorecard.json")["failure_class"] == (
        "infra_dependency"
    )


def test_model_settings_are_derived_and_token_secrets_are_redacted() -> None:
    model = _FakeModel(None)
    with pytest.raises(ValueError, match="disagree"):
        _model_settings(model, {"temperature": 0.9})

    class _CredentialModel(_FakeModel):
        def get_config(self) -> dict[str, Any]:
            return {
                "model_id": "synthetic-tooling",
                "params": {
                    "api_key": "SECRET",
                    "access_token": "SECRET",
                    "apiKey": "SECRET_A",
                    "X-API-Key": "SECRET_B",
                    "nested": {"Authorization": "SECRET_C"},
                    "extra_headers": {"X-Other": "SECRET_D"},
                    "client_args": {"apiKey": "SECRET_E"},
                    "max_tokens": 20,
                    "max_output_tokens": 30,
                },
            }

    settings = _safe_model_settings(
        _CredentialModel(None),
        {
            "api_key": "SECRET",
            "access_token": "SECRET",
            "apiKey": "SECRET_A",
            "X-API-Key": "SECRET_B",
            "nested": {"Authorization": "SECRET_C"},
            "extra_headers": {"X-Other": "SECRET_D"},
            "client_args": {"apiKey": "SECRET_E"},
            "max_tokens": 20,
            "max_output_tokens": 30,
        },
    )
    assert settings["params"] == {
        "api_key": "[redacted]",
        "access_token": "[redacted]",
        "apiKey": "[redacted]",
        "X-API-Key": "[redacted]",
        "nested": {"Authorization": "[redacted]"},
        "extra_headers": "[redacted]",
        "client_args": "[redacted]",
        "max_tokens": 20,
        "max_output_tokens": 30,
    }
    serialized_report = json.dumps({"model_settings": settings}, sort_keys=True)
    for secret in (
        "SECRET",
        "SECRET_A",
        "SECRET_B",
        "SECRET_C",
        "SECRET_D",
        "SECRET_E",
    ):
        assert secret not in serialized_report


def test_annual_holdout_role_cannot_use_public_manifest(tmp_path: Path) -> None:
    adapted = adapt_holdout_rows(
        [
            {
                **deepcopy(
                    next(
                        row
                        for row in validate().annual_rows
                        if row["id"] == "winchester-unsupported-location-refusal"
                    )
                ),
                "id": "tooling-holdout-role-check",
            }
        ]
    )[0]
    artifact = tmp_path / "heldout"
    artifact.mkdir()
    # The adapter's opaque suite is the only accepted held-out role.  Merely
    # relabeling its manifest as public must not bypass the public case set.
    identity = {key: "a" * 64 for key in graph_checks.ANNUAL_IDENTITY}
    identity.update(
        {
            "model": "synthetic-tooling",
            "commit": "a" * 40,
            "render_date": "2026-09-05",
            "rate_card_source": "synthetic",
            "rate_card_version": "v1",
        }
    )
    (artifact / "manifest.json").write_text(
        json.dumps(
            {
                "suite": "annual",
                "mode": "pin",
                "identity": identity,
                "cases": [adapted["case_id"]],
                "trials": ["1", "2", "3"],
                "scorecards": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="public case set"):
        graph_checks.load_run(artifact)

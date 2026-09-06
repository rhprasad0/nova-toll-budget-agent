"""Synthetic tooling checks for the trusted annual fixture boundary."""

# pyright: basic

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import eval.container_runner as container_runner
import eval.fixture_runner as fixture_runner
from eval import graph_checks
from eval.container_runner import source_digest as container_source_digest
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
    seal_trial_artifact,
    trusted_case_evidence,
)
from eval.fixture_runner import (
    FixtureRunPacket,
    RateCard,
    _FixtureScriptCursor,
    _request_cost,
    _response_cycle_usages,
    _usage_record,
    run_fixture_trial,
)
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
_MANIFEST = Path(__file__).parents[1] / "eval/golden/manifest.json"
_RATE_CARD = RateCard("synthetic-tooling", "v1", "a" * 64, 10, 20, 30)
_V2_MANIFEST = Path(__file__).parents[1] / "eval/golden/manifest-v2-sample.json"
_PUBLIC_V2_MANIFEST = Path(__file__).parents[1] / "eval/golden/manifest-v2.json"


class _FakeModel:
    """A deterministic Strands model used only by offline tooling checks."""

    stateful = False

    def __init__(
        self,
        packet: Any,
        *,
        unavailable: bool = False,
        response: str | None = None,
    ) -> None:
        self.packet = packet
        self.unavailable = unavailable
        self.response = response
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
        answer = self.response or (
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


class _MixedTurnModel:
    """Emit both authored tool calls in one assistant message."""

    stateful = False

    def __init__(
        self,
        packet: FixtureRunPacket,
        *,
        response: str | None = None,
    ) -> None:
        self.packet = packet
        self.response = response
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
        requests = [step["request"] for step in self.packet.script]

        async def events() -> Any:
            yield {"messageStart": {"role": "assistant"}}
            if not has_tool_result:
                for index, step in enumerate(self.packet.script):
                    yield {
                        "contentBlockStart": {
                            "start": {
                                "toolUse": {
                                    "toolUseId": f"mixed-call-{index}",
                                    "name": step["tool"],
                                }
                            }
                        }
                    }
                    yield {
                        "contentBlockDelta": {
                            "delta": {"toolUse": {"input": json.dumps(requests[index])}}
                        }
                    }
                    yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "tool_use"}}
            else:
                yield {"contentBlockStart": {"start": {"text": ""}}}
                yield {
                    "contentBlockDelta": {
                        "delta": {
                            "text": self.response or "### Mixed-tool fixture complete"
                        }
                    }
                }
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "end_turn"}}
            # Deliberately omit optional cache buckets, as the provider formatters
            # do for zero values.  The runner must seal explicit zero buckets.
            yield {
                "metadata": {
                    "usage": {
                        "inputTokens": 4,
                        "outputTokens": 2,
                        "totalTokens": 6,
                    }
                },
                "metrics": {"latencyMs": 0},
            }

        return events()


class _DuplicateTurnModel:
    """Repeat one exact successful call so the frozen guard cancels the retry."""

    stateful = False

    def __init__(self, packet: FixtureRunPacket) -> None:
        self.packet = packet
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
        del messages, tool_specs, system_prompt, kwargs
        self.stream_count += 1
        step = self.packet.script[0]

        async def events() -> Any:
            yield {"messageStart": {"role": "assistant"}}
            if self.stream_count <= 2:
                yield {
                    "contentBlockStart": {
                        "start": {
                            "toolUse": {
                                "toolUseId": f"duplicate-call-{self.stream_count}",
                                "name": step["tool"],
                            }
                        }
                    }
                }
                yield {
                    "contentBlockDelta": {
                        "delta": {"toolUse": {"input": json.dumps(step["request"])}},
                    }
                }
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "tool_use"}}
            else:
                yield {"contentBlockStart": {"start": {"text": ""}}}
                yield {
                    "contentBlockDelta": {
                        "delta": {"text": "### Duplicate call handled 🚗"}
                    }
                }
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "end_turn"}}
            yield {
                "metadata": {
                    "usage": {
                        "inputTokens": 4,
                        "outputTokens": 2,
                        "totalTokens": 6,
                    }
                },
                "metrics": {"latencyMs": 0},
            }

        return events()


def _packet(case_id: str, *, manifest_path: Path | None = None) -> Any:
    return packet_for_case(
        case_id,
        manifest_path=manifest_path
        or Path(__file__).parents[1] / "eval/golden/manifest.json",
        prompt_points=[_POINT],
        render_date=date(2026, 9, 5),
    )


def _write_private_no_call_manifest(root: Path) -> Path:
    root.mkdir(parents=True)
    cases = root / "cases"
    cases.mkdir()
    row = {
        "id": "private-synthetic-no-call",
        "prompt": "I have not provided a supported origin or destination yet.",
        "conversation": ["I have not provided a supported origin or destination yet."],
        "script": [],
    }
    shard = cases / "private.jsonl"
    shard.write_text(json.dumps(row) + "\n", encoding="utf-8")
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
    public = json.loads(_PUBLIC_V2_MANIFEST.read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {
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
                "id": row["id"],
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
        "public_dataset_sha256": public["dataset_sha256"],
        "public_membership_sha256": public["membership_sha256"],
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
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _write_private_typed_manifest(root: Path) -> Path:
    path = _write_private_no_call_manifest(root)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    shard = path.parent / "cases/private.jsonl"
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "eval/golden/fixtures/current-success.json"
        ).read_text(encoding="utf-8")
    )
    fixture["fixture_id"] = "private-current-success"
    fixture["provenance"] = "synthetic-private-test"
    fixture_path = path.parent / "fixtures/private-current-success.json"
    fixture_path.parent.mkdir()
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    row = {
        "id": "private-synthetic-typed",
        "prompt": "Price this supported Greenway route.",
        "conversation": ["Price this supported Greenway route."],
        "script": [
            {
                "turn": 0,
                "tool": "get_current_toll_price",
                "request": fixture["request"],
                "fixture_id": "private-current-success",
            }
        ],
    }
    shard.write_text(json.dumps(row) + "\n", encoding="utf-8")
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
    manifest["case_metadata"][0]["id"] = row["id"]
    manifest["case_metadata"][0]["expected_assertion"] = (
        "Required: ground the current price in the private typed fixture. "
        "Prohibited: substitute a public fixture."
    )
    manifest["fixtures"] = [
        {
            "id": "private-current-success",
            "tool": "get_current_toll_price",
            "path": "fixtures/private-current-success.json",
            "tool_contract_version": "1.5.0",
        }
    ]
    manifest["payloads"] = [
        {
            "path": "cases/private.jsonl",
            "sha256": hashlib.sha256(shard.read_bytes()).hexdigest(),
        },
        {
            "path": "fixtures/private-current-success.json",
            "sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        },
    ]
    manifest["dataset_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "dataset_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def test_v2_mixed_tools_share_one_assistant_batch_and_preserve_order(
    tmp_path: Path,
) -> None:
    packet = _packet("v2-annual-mixed-tool-multiturn", manifest_path=_V2_MANIFEST)
    same_turn = replace(
        packet,
        conversation=(packet.conversation[0],),
        script=tuple({**step, "turn": 0} for step in packet.script),
    )
    result = run_fixture_trial(
        same_turn,
        model=_MixedTurnModel(same_turn),
        artifact_root=tmp_path / "mixed" / "1",
        trial_id="1",
        rate_card=_RATE_CARD,
    )

    assert result["failure_class"] == "none"
    calls = result["output"]["trajectory"][0]["calls"]
    assert [call["name"] for call in calls] == [
        "get_current_toll_price",
        "get_annual_toll_ballpark",
    ]
    assert [call["script_sequence"] for call in calls] == [0, 1]
    assert result["output"]["measurements"]["cache_write_tokens"] == 0


def test_fixture_trial_caps_provider_cycles_per_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _packet("v2-annual-mixed-tool-multiturn", manifest_path=_V2_MANIFEST)
    packet = replace(
        packet,
        conversation=(packet.conversation[0],),
        script=tuple({**step, "turn": 0} for step in packet.script),
    )

    class CapturingAgent:
        def __init__(self) -> None:
            self.messages: list[object] = []
            self.limits_seen: list[dict[str, int]] = []

        def __call__(self, prompt: str, *, limits: dict[str, int]) -> object:
            del prompt
            self.limits_seen.append(limits)
            return SimpleNamespace(
                metrics=SimpleNamespace(
                    agent_invocations=[
                        SimpleNamespace(
                            usage={
                                "inputTokens": 4,
                                "outputTokens": 2,
                                "totalTokens": 6,
                            }
                        )
                    ]
                )
            )

    agent = CapturingAgent()

    def build_agent(**_: object) -> CapturingAgent:
        return agent

    monkeypatch.setattr(fixture_runner, "build_agent", build_agent)
    result = run_fixture_trial(
        packet,
        model=object(),
        artifact_root=None,
        trial_id="1",
        rate_card=_RATE_CARD,
    )

    assert result["failure_class"] == "none"
    assert agent.limits_seen == [{"turns": 1 + len(packet.script)}]


def test_fixture_script_cursor_rejects_wrong_order_and_duplicate_batch_ids() -> None:
    packet = _packet("v2-annual-mixed-tool-multiturn", manifest_path=_V2_MANIFEST)
    script = tuple({**step, "turn": 0} for step in packet.script)
    cursor = _FixtureScriptCursor(script, packet.fixture_evidence)
    cursor.begin_turn(0)

    wrong = {
        "content": [
            {
                "toolUse": {
                    "toolUseId": "wrong-first",
                    "name": script[1]["tool"],
                    "input": script[1]["request"],
                }
            }
        ]
    }
    assignment = cursor.assign_message(wrong)["wrong-first"]
    assert assignment["error"] == "tool call does not match authored order"
    assert assignment["step_index"] is None

    expected = {
        "content": [
            {
                "toolUse": {
                    "toolUseId": "expected-first",
                    "name": script[0]["tool"],
                    "input": script[0]["request"],
                }
            }
        ]
    }
    assert cursor.assign_message(expected)["expected-first"]["step_index"] == 0
    duplicate = {
        "content": [
            {
                "toolUse": {
                    "toolUseId": "expected-first",
                    "name": script[1]["tool"],
                    "input": script[1]["request"],
                }
            }
        ]
    }
    assert cursor.assign_message(duplicate)["expected-first"]["error"] == (
        "tool-use ID is missing or duplicated"
    )


def test_real_strands_repeated_hook_retains_frozen_duplicate_guard_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _packet("v2-annual-mixed-tool-multiturn", manifest_path=_V2_MANIFEST)
    packet = replace(
        source,
        conversation=(source.conversation[0],),
        script=(source.script[0],),
        fixture_evidence=(source.fixture_evidence[0],),
    )
    hook_messages: list[object] = []
    original_before_tools = fixture_runner._FixtureScriptHook.before_tools

    def record_before_tools(self: Any, event: Any) -> None:
        hook_messages.append(event.message)
        original_before_tools(self, event)
        # Re-enter the hook with the exact same event/message to model an
        # interrupt replay; the cursor must not consume the authored step twice.
        original_before_tools(self, event)

    monkeypatch.setattr(
        fixture_runner._FixtureScriptHook, "before_tools", record_before_tools
    )
    result = run_fixture_trial(
        packet,
        model=_DuplicateTurnModel(packet),
        artifact_root=tmp_path / "duplicate" / "1",
        trial_id="1",
        rate_card=_RATE_CARD,
    )

    assert result["failure_class"] == "none"
    assert len(hook_messages) >= 2
    calls = result["output"]["trajectory"][0]["calls"]
    assert len(calls) == 2
    assert calls[0]["is_error"] is False
    assert calls[0]["script_sequence"] == 0
    assert calls[0]["fixture_id"] == packet.script[0]["fixture_id"]
    assert calls[1]["is_error"] is True
    assert calls[1]["tool_error"]
    assert "fixture_id" not in calls[1]
    assert calls[1]["toolUseId"] == "duplicate-call-2"


def test_cycle_usage_with_missing_entry_is_not_filtered() -> None:
    class _Cycle:
        def __init__(self, usage: object) -> None:
            self.usage = usage

    class _Invocation:
        def __init__(self) -> None:
            self.cycles = [_Cycle({"totalTokens": 6}), _Cycle(None)]

    class _Metrics:
        def __init__(self) -> None:
            self.agent_invocations = [_Invocation()]

    class _Response:
        def __init__(self) -> None:
            self.metrics = _Metrics()

    assert _response_cycle_usages(_Response()) == [
        {"totalTokens": 6},
        None,
    ]


def test_incomplete_cycle_usage_keeps_extracted_calls_in_infra_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _packet("v2-annual-mixed-tool-multiturn", manifest_path=_V2_MANIFEST)
    packet = replace(
        source,
        conversation=(source.conversation[0],),
        script=tuple({**step, "turn": 0} for step in source.script),
    )
    monkeypatch.setattr(
        fixture_runner, "_response_cycle_usages", lambda _response: [None]
    )
    result = run_fixture_trial(
        packet,
        model=_MixedTurnModel(packet),
        artifact_root=tmp_path / "incomplete-usage" / "1",
        trial_id="1",
        rate_card=_RATE_CARD,
    )

    assert result["failure_class"] == "infra_dependency"
    assert result["output"]["trajectory"][0]["calls"]


@pytest.mark.parametrize(
    "usage",
    [
        {
            "totalTokens": 6,
            "inputTokens": 4,
            "outputTokens": 2,
            "cacheReadInputTokens": -1,
        },
        {
            "totalTokens": 6,
            "inputTokens": 4,
            "outputTokens": 2,
            "cacheWriteInputTokens": True,
        },
        {
            "totalTokens": 6,
            "inputTokens": 4,
            "outputTokens": 2,
            "cacheReadInputTokens": None,
        },
    ],
)
def test_usage_rejects_explicit_malformed_cache_buckets(
    usage: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="cache usage counters"):
        _usage_record(usage)


def test_request_cost_uses_long_context_tier_per_request_and_splits_cache_buckets() -> (
    None
):
    rates = RateCard("synthetic-tooling", "v1", "a" * 64, 10, 20, 30).as_dict()
    two_normal = [
        _request_cost(
            _usage_record(
                {"totalTokens": 200_002, "inputTokens": 200_000, "outputTokens": 2}
            ),
            rates,
        )
        for _ in range(2)
    ]
    assert [item["long_context"] for item in two_normal] == [False, False]
    premium = _request_cost(
        _usage_record(
            {"totalTokens": 272_003, "inputTokens": 272_001, "outputTokens": 2}
        ),
        rates,
    )
    assert premium["long_context"] is True
    split = _request_cost(
        _usage_record(
            {
                "totalTokens": 110,
                "inputTokens": 100,
                "outputTokens": 10,
                "cacheReadInputTokens": 30,
                "cacheWriteInputTokens": 20,
            }
        ),
        rates,
    )
    assert split["ordinary_input_tokens"] == 50
    assert split["input_usd"] == 50 * 10 / 1_000_000
    assert split["cache_usd"] == 30 * 30 / 1_000_000
    assert split["cache_write_usd"] == 20 * 12.5 / 1_000_000


def test_private_v2_holdout_uses_supplied_manifest_at_grading_boundary(
    tmp_path: Path,
) -> None:
    private_manifest = _write_private_no_call_manifest(tmp_path / "private")
    source_row = {
        "id": "private-synthetic-no-call",
        "prompt": "I have not provided a supported origin or destination yet.",
        "conversation": ["I have not provided a supported origin or destination yet."],
        "script": [],
        "suite": "current",
    }
    adapted = adapt_holdout_rows([source_row], manifest_path=private_manifest)[0]
    packet, case_bytes, dataset_hash = packet_for_holdout(
        adapted,
        manifest_path=private_manifest,
        prompt_points=[_POINT],
        render_date=date(2026, 9, 5),
    )
    assert packet.dataset_version == "2.0.0"
    assert (
        run_and_seal_trial(
            packet,
            model=_FakeModel(
                packet,
                response="Please provide a supported origin and destination before pricing. 🚗",
            ),
            artifact_root=tmp_path / "artifact" / "1",
            trial_id="1",
            rate_card=_RATE_CARD,
            case_bytes=case_bytes,
            dataset_hash=dataset_hash,
            case_document=holdout_case_document(adapted),
            manifest_path=private_manifest,
        )
        == 0
    )
    assert read_json(tmp_path / "artifact" / "1" / "scorecard.json")["pass"] is True


def test_private_v2_holdout_resolves_own_typed_fixture_and_rejects_public_substitution(
    tmp_path: Path,
) -> None:
    private_manifest = _write_private_typed_manifest(tmp_path / "private-typed")
    row = {
        "id": "private-synthetic-typed",
        "prompt": "Price this supported Greenway route.",
        "conversation": ["Price this supported Greenway route."],
        "script": [
            {
                "turn": 0,
                "tool": "get_current_toll_price",
                "request": {
                    "origin_point_id": "greenway:1:entry:EB",
                    "destination_point_id": "greenway:28:exit:EB",
                    "pricing_profile": {
                        "vehicle_class": "two_axle_passenger",
                        "payment_method": "e_zpass",
                        "transponder_mode": "toll",
                    },
                },
                "fixture_id": "private-current-success",
            }
        ],
        "suite": "current",
    }
    adapted = adapt_holdout_rows([row], manifest_path=private_manifest)[0]
    packet, case_bytes, dataset_hash = packet_for_holdout(
        adapted,
        manifest_path=private_manifest,
        prompt_points=[_POINT],
        render_date=date(2026, 9, 5),
    )
    assert packet.fixture_evidence[0]["id"] == "private-current-success"
    assert packet.fixture_evidence[0]["result"]["total_usd"] == "5.80"
    response = (
        "### Current toll pricing\n"
        "Current toll pricing is $5.80 at 6:30 AM EDT. "
        "Pricing provenance: schedule_derived from the published schedule. 🚗"
    )
    artifact = tmp_path / "artifact" / "1"
    assert (
        run_and_seal_trial(
            packet,
            model=_MixedTurnModel(packet, response=response),
            artifact_root=artifact,
            trial_id="1",
            rate_card=_RATE_CARD,
            case_bytes=case_bytes,
            dataset_hash=dataset_hash,
            case_document=holdout_case_document(adapted),
            manifest_path=private_manifest,
        )
        == 0
    )
    output = read_json(artifact / "output.json")
    assert output["trajectory"][0]["calls"][0]["tool_result"]["total_usd"] == "5.80"
    assert read_json(artifact / "scorecard.json")["pass"] is True

    public_substitution = deepcopy(row)
    public_substitution["script"][0]["fixture_id"] = "current-success"
    with pytest.raises(ValueError, match="script is invalid"):
        adapt_holdout_rows([public_substitution], manifest_path=private_manifest)


def test_actual_strands_fixture_trial_seals_and_grades(tmp_path: Path) -> None:
    packet = _packet("dulles-to-reagan-annual-unavailable", manifest_path=_MANIFEST)
    case_bytes, dataset_hash, _ = trusted_case_evidence(
        packet.case_id, manifest_path=_MANIFEST
    )
    artifact = tmp_path / "case" / "1"

    result = run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
        manifest_path=_MANIFEST,
    )

    assert result == 0
    output = read_json(artifact / "output.json")
    assert output["trajectory"][0]["calls"][0]["tool_result"] == packet.fixture_payload
    assert read_json(artifact / "run.json")["output_digest"]
    assert read_json(artifact / "scorecard.json")["pass"] is True


def test_container_execution_evidence_seals_and_rejects_malformed_shape(
    tmp_path: Path,
) -> None:
    packet = _packet("dulles-to-reagan-annual-unavailable", manifest_path=_MANIFEST)
    case_bytes, dataset_hash, _ = trusted_case_evidence(
        packet.case_id, manifest_path=_MANIFEST
    )
    artifact = tmp_path / "container" / "1"
    run_fixture_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
    )
    output = read_json(artifact / "output.json")
    output["container_execution"] = {
        "image": "tollchat-fixture:slice5",
        "image_id": "sha256:" + "b" * 64,
        "source_digest": container_source_digest(),
    }
    (artifact / "output.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    seal_trial_artifact(
        artifact,
        packet,
        model=_FakeModel(packet, unavailable=True),
        model_settings=None,
        rate_card=_RATE_CARD,
        trial_id="1",
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
    )
    case_path = tmp_path / "container-case.json"
    case_path.write_text(
        json.dumps({"case_id": packet.case_id, "suite": "annual"}) + "\n",
        encoding="utf-8",
    )
    assert graph_checks.grade(artifact, case_path, manifest_path=_MANIFEST) == 0

    output["container_execution"]["image_id"] = None
    (artifact / "output.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run = read_json(artifact / "run.json")
    run["output_digest"] = hashlib.sha256(
        b"".join(
            name.encode() + b"\0" + (artifact / name).read_bytes() + b"\0"
            for name in ("output.json", "stdout.txt", "exit_code.json")
        )
    ).hexdigest()
    (artifact / "run.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert graph_checks.grade(artifact, case_path, manifest_path=_MANIFEST) == 1
    assert read_json(artifact / "scorecard.json")["failure_class"] == (
        "infra_dependency"
    )


def test_container_exit_mismatch_seals_partial_trace_as_infrastructure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packet = _packet("v2-annual-mixed-tool-multiturn", manifest_path=_V2_MANIFEST)
    case_bytes, dataset_hash, _ = trusted_case_evidence(
        packet.case_id, manifest_path=_V2_MANIFEST
    )
    rate_card = _RATE_CARD
    key = "synthetic-provider-credential"
    worker_record = run_fixture_trial(
        packet,
        model=_MixedTurnModel(packet),
        artifact_root=None,
        trial_id="1",
        rate_card=rate_card,
    )
    worker_record["exit_code"] = 0
    worker_record["failure_class"] = "none"

    class Result:
        returncode = 1
        stdout = (json.dumps(worker_record) + "\n").encode()
        stderr = b"container diagnostic"

    monkeypatch.setattr(container_runner.subprocess, "run", lambda *a, **k: Result())
    evidence = container_runner.ContainerEvidence(
        image="tollchat-fixture:test",
        image_id="sha256:" + "b" * 64,
        source_digest="a" * 64,
    )
    monkeypatch.setattr(
        container_runner, "source_digest", lambda: evidence.source_digest
    )
    monkeypatch.setattr(container_runner, "_image_id", lambda _image: evidence.image_id)
    artifact = tmp_path / "mismatch" / "1"
    result = container_runner.run_container_trial(
        packet,
        key=key,
        rate_card=rate_card,
        trial_id="1",
        artifact_root=artifact,
        evidence=evidence,
    )
    output = read_json(artifact / "output.json")
    assert result.record["failure_class"] == "infra_dependency"
    assert result.record["exit_code"] == 1
    assert output["error"] == "container_exit_failure"
    assert output["trajectory"]
    assert output["measurements"]["turns"]

    seal_trial_artifact(
        artifact,
        packet,
        model=_MixedTurnModel(packet),
        model_settings=None,
        rate_card=rate_card,
        trial_id="1",
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
    )
    case_path = tmp_path / "mismatch-case.json"
    case_path.write_text(
        json.dumps({"case_id": packet.case_id, "suite": "annual"}) + "\n",
        encoding="utf-8",
    )
    assert graph_checks.grade(artifact, case_path, manifest_path=_V2_MANIFEST) == 1
    score = read_json(artifact / "scorecard.json")
    assert score["failure_class"] == "infra_dependency"


def test_two_public_cases_have_three_independent_sealed_trials(tmp_path: Path) -> None:
    cases = (
        ("dulles-to-reagan-annual-unavailable", True),
        ("winchester-unsupported-location-refusal", False),
    )
    identities: list[dict[str, str]] = []
    for case_id, unavailable in cases:
        packet = _packet(case_id, manifest_path=_MANIFEST)
        case_bytes, dataset_hash, _ = trusted_case_evidence(
            case_id, manifest_path=_MANIFEST
        )
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
                    manifest_path=_MANIFEST,
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
    packet = _packet(
        "springfield-franconia-tysons-annual-affordability", manifest_path=_MANIFEST
    )
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
    packet = _packet("dulles-to-reagan-annual-unavailable", manifest_path=_MANIFEST)
    case_bytes, dataset_hash, _ = trusted_case_evidence(
        packet.case_id, manifest_path=_MANIFEST
    )
    artifact = tmp_path / "case" / "1"
    run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
        manifest_path=_MANIFEST,
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
    packet = _packet("dulles-to-reagan-annual-unavailable", manifest_path=_MANIFEST)
    case_bytes, dataset_hash, _ = trusted_case_evidence(
        packet.case_id, manifest_path=_MANIFEST
    )
    artifact = tmp_path / "case" / "1"
    run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
        manifest_path=_MANIFEST,
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
    packet = _packet("dulles-to-reagan-annual-unavailable", manifest_path=_MANIFEST)
    case_bytes, dataset_hash, _ = trusted_case_evidence(
        packet.case_id, manifest_path=_MANIFEST
    )
    artifact = tmp_path / "case" / "1"
    run_and_seal_trial(
        packet,
        model=_FakeModel(packet, unavailable=True),
        artifact_root=artifact,
        trial_id="1",
        rate_card=_RATE_CARD,
        case_bytes=case_bytes,
        dataset_hash=dataset_hash,
        manifest_path=_MANIFEST,
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

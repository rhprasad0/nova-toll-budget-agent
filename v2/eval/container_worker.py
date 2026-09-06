# pyright: basic
"""One fixture trial over stdin/stdout; no corpus lookup or grading."""

from __future__ import annotations

import io
import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout, suppress
from copy import deepcopy
from dataclasses import fields
from datetime import date
from typing import Any

from agent import toll_agent
from eval.fixture_runner import FixtureRunPacket, RateCard, run_fixture_trial

MAX_INPUT_BYTES = 8 * 1024 * 1024
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}")
_TOOLS = {"get_current_toll_price", "get_annual_toll_ballpark"}
_PACKET_FIELDS = {
    "case_id",
    "prompt",
    "conversation",
    "script",
    "fixture_evidence",
    "prompt_points",
    "render_date",
    "dataset_version",
}
_EVIDENCE_FIELDS = {"id", "tool", "request", "result", "error"}


def strict_json(raw: str | bytes) -> object:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(_: str) -> None:
        raise ValueError("non-finite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid object fields")
    return value


def _contains_credential(value: object, credential: str) -> bool:
    """Check parsed JSON using one canonical escaped representation."""
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True)
    marker = json.dumps(credential, ensure_ascii=True, allow_nan=False)[1:-1]
    return marker in encoded


def packet_to_wire(packet: FixtureRunPacket) -> dict[str, Any]:
    """Project runner inputs explicitly; raw evidence and grader data stay host-side."""
    if not packet.strict_usage or packet.render_date is None:
        raise ValueError("container requires a versioned fixture packet")
    value = {
        "case_id": packet.case_id,
        "prompt": packet.prompt,
        "conversation": list(packet.conversation),
        "script": [
            {key: step[key] for key in ("turn", "tool", "request", "fixture_id")}
            for step in packet.script
        ],
        "fixture_evidence": [
            {key: item.get(key) for key in _EVIDENCE_FIELDS}
            for item in packet.fixture_evidence
        ],
        "prompt_points": list(packet.prompt_points or ()),
        "render_date": packet.render_date.isoformat(),
        "dataset_version": packet.dataset_version,
    }
    value = deepcopy(value)
    packet_from_wire(value)
    return value


def packet_from_wire(value: object) -> FixtureRunPacket:
    value = _object(value, _PACKET_FIELDS)
    if not isinstance(value["case_id"], str) or not _ID.fullmatch(value["case_id"]):
        raise ValueError("invalid case identity")
    turns = value["conversation"]
    if (
        type(turns) is not list
        or not turns
        or any(not isinstance(turn, str) or not turn for turn in turns)
        or value["prompt"] != turns[0]
    ):
        raise ValueError("invalid conversation")
    points = value["prompt_points"]
    if (
        type(points) is not list
        or not points
        or any(type(p) is not dict for p in points)
    ):
        raise ValueError("explicit prompt points required")
    if not isinstance(value["render_date"], str):
        raise ValueError("invalid render date")
    render_date = date.fromisoformat(value["render_date"])
    if render_date.isoformat() != value["render_date"]:
        raise ValueError("noncanonical render date")
    if not isinstance(value["dataset_version"], str) or not re.fullmatch(
        r"2\.\d+\.\d+", value["dataset_version"]
    ):
        raise ValueError("invalid dataset version")
    evidence = value["fixture_evidence"]
    script = value["script"]
    if type(evidence) is not list or type(script) is not list:
        raise ValueError("invalid script evidence")
    by_id = {}
    for item in evidence:
        item = _object(item, _EVIDENCE_FIELDS)
        if (
            not isinstance(item["id"], str)
            or not _ID.fullmatch(item["id"])
            or item["tool"] not in _TOOLS
            or type(item["request"]) is not dict
            or (type(item["result"]) is dict) == (type(item["error"]) is dict)
            or (item["result"] is not None and type(item["result"]) is not dict)
            or (item["error"] is not None and type(item["error"]) is not dict)
        ):
            raise ValueError("invalid fixture evidence")
        if item["id"] in by_id and by_id[item["id"]] != item:
            raise ValueError("conflicting fixture evidence")
        by_id[item["id"]] = item
    referenced = set()
    previous_turn = 0
    for step in script:
        step = _object(step, {"turn", "tool", "request", "fixture_id"})
        turn = step["turn"]
        if (
            type(turn) is not int
            or not previous_turn <= turn < len(turns)
            or step["tool"] not in _TOOLS
            or type(step["request"]) is not dict
            or not isinstance(step["fixture_id"], str)
        ):
            raise ValueError("invalid script step")
        bound = by_id.get(step["fixture_id"])
        if (
            bound is None
            or bound["tool"] != step["tool"]
            or bound["request"] != step["request"]
        ):
            raise ValueError("unbound script step")
        previous_turn = turn
        referenced.add(step["fixture_id"])
    if referenced != set(by_id):
        raise ValueError("unreferenced fixture evidence")
    return FixtureRunPacket(
        case_id=value["case_id"],
        prompt=value["prompt"],
        conversation=tuple(turns),
        fixture_id=None,
        fixture_result_kind=None,
        fixture_request=None,
        fixture_payload=None,
        fixture_bytes=None,
        prompt_points=tuple(points),
        render_date=render_date,
        script=tuple(script),
        fixture_evidence=tuple(evidence),
        strict_usage=True,
        dataset_version=value["dataset_version"],
    )


def model_from_key(key: str) -> toll_agent._CachedResponsesModel:
    """Use the application constructor for both host identity and worker execution."""
    if not isinstance(key, str) or not key or len(key) > 4096:
        raise ValueError("invalid credential")
    original = toll_agent.load_openai_api_key
    # ponytail: sequential process-local override; isolate processes if parallelized.
    try:
        toll_agent.load_openai_api_key = lambda: key
        with (
            _quiet_descriptors(),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            return toll_agent._build_model()
    except Exception:
        raise ValueError("model construction failed") from None
    finally:
        toll_agent.load_openai_api_key = original


def failure_record(
    case_id: str = "unknown", trial_id: str = "unknown"
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "trial_id": trial_id,
        "output": {
            "case_id": case_id,
            "output": "",
            "trajectory": [],
            "measurements": {"turns": [], "tokens": None, "latency_ms": None},
            "cost": None,
            "error": "container_infrastructure_failure",
        },
        "stdout": "",
        "exit_code": 1,
        "failure_class": "infra_dependency",
    }


def encode_input(
    packet: FixtureRunPacket, rate_card: RateCard, trial_id: str, key: str
) -> bytes:
    if not isinstance(key, str) or not key or len(key) > 4096:
        raise ValueError("invalid credential")
    if not isinstance(trial_id, str) or not _ID.fullmatch(trial_id):
        raise ValueError("invalid trial identity")
    envelope = {
        "packet": packet_to_wire(packet),
        "rate_card": rate_card.as_dict(),
        "trial_id": trial_id,
    }
    body = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    if _contains_credential(envelope, key):
        raise ValueError("credential in packet")
    encoded = (json.dumps({"credential": key}) + "\n" + body + "\n").encode()
    if len(encoded) > MAX_INPUT_BYTES:
        raise ValueError("packet exceeds transport bound")
    return encoded


def execute_input(raw: bytes) -> dict[str, Any]:
    case_id = trial_id = "unknown"
    try:
        lines = raw.split(b"\n")
        if len(raw) > MAX_INPUT_BYTES or len(lines) != 3 or lines[-1]:
            raise ValueError("expected two envelopes")
        key = _object(strict_json(lines[0]), {"credential"})["credential"]
        if not isinstance(key, str) or not key or len(key) > 4096:
            raise ValueError("invalid credential")
        envelope = _object(strict_json(lines[1]), {"packet", "rate_card", "trial_id"})
        if _contains_credential(envelope, key):
            raise ValueError("credential in packet")
        packet = packet_from_wire(envelope["packet"])
        if not isinstance(envelope["trial_id"], str) or not _ID.fullmatch(
            envelope["trial_id"]
        ):
            raise ValueError("invalid trial identity")
        card = _object(
            envelope["rate_card"], {field.name for field in fields(RateCard)}
        )
        if any(
            not isinstance(card[k], str) or not card[k] for k in ("source", "version")
        ):
            raise ValueError("invalid rate provenance")
        rate_card = RateCard(**card)
        rate_card.validate()
        case_id, trial_id = packet.case_id, envelope["trial_id"]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            model = model_from_key(key)
            record = run_fixture_trial(
                packet,
                model=model,
                artifact_root=None,
                trial_id=trial_id,
                rate_card=rate_card,
            )
        if _contains_credential(record, key):
            return failure_record(case_id, trial_id)
        return record
    except Exception:
        return failure_record(case_id, trial_id)


@contextmanager
def _quiet_descriptors() -> Iterator[None]:
    """Also suppress logging handlers that cached the original stderr stream."""
    saved = (os.dup(1), os.dup(2))
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            yield
    finally:
        for stream in (sys.stdout, sys.stderr):
            with suppress(Exception):
                stream.flush()
        for descriptor, original in zip((1, 2), saved, strict=True):
            try:
                os.dup2(original, descriptor)
            finally:
                os.close(original)


def main() -> int:
    with _quiet_descriptors():
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        record = execute_input(raw)
    sys.stdout.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

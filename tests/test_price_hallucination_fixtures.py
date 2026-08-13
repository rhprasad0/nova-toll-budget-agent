from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eval.deterministic.price_hallucination.fixtures import write_review_packet


def _case(result: str = "7.80") -> dict:
    return {
        "id": "single_leg:greenway-001",
        "stratum": "single_leg",
        "route": {
            "origin": "Leesburg",
            "destination": "Route 28",
            "facility": "dulles_greenway",
            "direction": "EB",
            "entry_id": "1",
            "exit_id": "28",
            "requested_at": "2026-07-27T07:30:00-04:00",
        },
        "answer_class": "complete_price",
        "total_type": "complete",
        "components": [
            {
                "facility": "dulles_greenway",
                "label": "Mainline plaza",
                "role": "component",
                "price_usd": "5.80",
            },
            {
                "facility": "dulles_toll_road",
                "label": "Mainline plaza",
                "role": "component",
                "price_usd": "2.00",
            },
        ],
        "excluded": [],
        "calculation": {"expression": "5.80 + 2.00", "result_usd": result},
        "source": {
            "tool": "dulles_route",
            "provenance": ["committed operator rate oracle"],
            "status": ["priced"],
            "observed_at": None,
            "evidence": {
                "legs": [{"facility": "dulles_greenway"}],
                "tolls": [
                    {
                        "facility": "dulles_greenway",
                        "label": "Mainline plaza",
                        "price_usd": "5.80",
                    },
                    {
                        "facility": "dulles_toll_road",
                        "label": "Mainline plaza",
                        "price_usd": "2.00",
                    },
                ],
            },
        },
        "prompts": [f"variant {number}" for number in range(1, 6)],
    }


def test_review_packet_validates_money_and_is_reproducible(tmp_path: Path) -> None:
    packet = write_review_packet([_case()], tmp_path, expected_per_stratum=1)

    assert packet["canonical_count"] == 1
    assert len(packet["sha256"]) == 64
    assert (tmp_path / "fixture-review.csv").read_text().count("5.80 + 2.00") == 1
    manifest = (tmp_path / "test-cases.jsonl").read_text()
    checksums = (tmp_path / "review-packet.sha256").read_text()
    assert hashlib.sha256(manifest.encode()).hexdigest() in checksums
    assert "fixture-review.md" in checksums
    assert packet["sha256"] == hashlib.sha256(checksums.encode()).hexdigest()
    assert json.loads(manifest)["source"]["evidence_sha256"]
    review = (tmp_path / "fixture-review.md").read_text()
    assert "# Price hallucination fixture review" in review
    assert "$5.80 + $2.00 = **$7.80**" in review
    assert "[raw evidence](test-cases.jsonl#L1)" in review

    multi_leg = _case()
    multi_leg.update(id="multi_leg:greenway-001", stratum="multi_leg")
    multi_leg["source"]["evidence"]["calls"] = [
        {
            "tool": "dulles_route",
            "input": {"origin": "Leesburg", "destination": "Route 28"},
            "result": {"total_usd": "7.80"},
        }
    ]
    write_review_packet([multi_leg], tmp_path, expected_per_stratum=1)
    review = (tmp_path / "fixture-review.md").read_text()
    fixture = json.loads((tmp_path / "test-cases.jsonl").read_text())
    assert "## Gate 5 multi-leg review" in review
    assert "| Planned responses | **12**" in review
    assert "| Blocked-duplicate prompts | **1**" in review
    assert "### Blocked-tool recovery examples" in review
    assert fixture["blocked_duplicate"] == {
        "input": {"origin": "Leesburg", "destination": "Route 28"},
        "message": (
            "This exact tool call already ran during this request. "
            "Use its previous result and continue with the next planned step."
        ),
        "status": "error",
        "tool": "dulles_route",
    }
    assert "**1 complete** · **0 known partial**" in review
    fixture["blocked_duplicate"]["message"] = "wrong"
    with pytest.raises(ValueError, match="blocked duplicate does not match"):
        write_review_packet([fixture], tmp_path, expected_per_stratum=1)

    with pytest.raises(ValueError, match=r"5\.80 \+ 2\.00 != 7\.70"):
        write_review_packet([_case("7.70")], tmp_path, expected_per_stratum=1)

    bad = _case()
    bad["components"][0]["price_usd"] = 5.8
    with pytest.raises(TypeError, match="decimal string"):
        write_review_packet([bad], tmp_path, expected_per_stratum=1)

    no_price = _case()
    no_price.update(
        answer_class="abstain", total_type="none", components=[], calculation=None
    )
    write_review_packet([no_price], tmp_path, expected_per_stratum=1)

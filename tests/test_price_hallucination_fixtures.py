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
    assert "# Gate 2 fixture review brief" in review
    assert "$5.80 + $2.00 = **$7.80**" in review
    assert "[raw evidence](test-cases.jsonl#L1)" in review

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

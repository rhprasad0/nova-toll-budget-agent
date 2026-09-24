"""Offline isolation check: uv run python eval/evidence/prompt-experiment/check.py."""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast


def without_descriptions(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: without_descriptions(v)
            for k, v in cast(dict[str, Any], value).items()
            if k != "description"
        }
    if isinstance(value, list):
        return [without_descriptions(v) for v in cast(list[Any], value)]
    return value


def check() -> None:
    worktrees = Path(__file__).resolve().parents[5]
    roots = [worktrees / f"prompt-experiment-{arm}" / "v2" for arm in "abc"]
    specs: list[Any] = []
    for root in roots:
        result = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "import json; from agent_tools import current_price_domain as c, get_annual_toll_ballpark as a; print(json.dumps([c.TOOL_CONTRACT,a.TOOL_CONTRACT]))",
            ],
            cwd=root,
            text=True,
        )
        specs.append(json.loads(result))
    assert specs[1] == specs[2], "B/C tool contracts differ"
    assert specs[0] != specs[1], "B did not change descriptions"
    assert without_descriptions(specs[0]) == without_descriptions(specs[1]), (
        "Non-description tool change"
    )
    prompts = [
        (root / "agent-sops/nova-toll-pricing-assistant.sop.md").read_text()
        for root in roots
    ]
    assert prompts[0] == prompts[1], "B changed the SOP"

    def paragraphs(s: str) -> Counter[str]:
        return Counter(p for p in s.strip().split("\n\n") if not p.startswith("## "))

    assert paragraphs(prompts[0]) == paragraphs(prompts[2]), "C lost or changed a rule"
    assert prompts[0] != prompts[2], "C did not reorganize the SOP"
    manifests = [
        json.loads((root / "eval/golden/manifest.json").read_text()) for root in roots
    ]
    assert manifests[1] == manifests[2]
    changed = {
        key
        for key in manifests[0]["hashes"]
        if manifests[0]["hashes"][key] != manifests[1]["hashes"][key]
    }
    assert changed == {
        "v2/agent_tools/current_price_domain.py",
        "v2/agent_tools/get_annual_toll_ballpark.py",
    }
    cases = {
        c["id"]: c
        for c in map(
            json.loads, (roots[0] / "eval/golden/cases.jsonl").read_text().splitlines()
        )
    }
    selected = json.loads(Path(__file__).with_name("diagnostic-cases.json").read_text())
    assert len({c["id"] for c in selected}) == len(selected) == 26
    assert all(not cases[c["id"]]["held_out"] for c in selected)
    assert {c["family"] for c in selected} == {
        c["coverage_family"] for c in cases.values()
    }
    print(
        "A/B/C isolation, unchanged rules, and development-only diagnostics verified."
    )


if __name__ == "__main__":
    check()

"""Keep Markdown from restating code: each check fails with the fix to make."""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
JOURNAL = "v2/eval/journal/"


def tracked_markdown() -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "*.md"], cwd=REPO_ROOT, text=True
    )
    return [path for path in output.splitlines() if (REPO_ROOT / path).is_file()]


def test_markdown_files_only_shrink() -> None:
    """New rules belong in checks; journal pages are the one growing record."""
    documents = [path for path in tracked_markdown() if not path.startswith(JOURNAL)]
    assert len(documents) <= 42, (
        "Do not add Markdown files. Write a deterministic check whose error names "
        "the fix (CLAUDE.md), or delete a stale document to make room."
    )


def anchors(text: str) -> set[str]:
    """GitHub heading anchors, including -1, -2 suffixes for repeats."""
    seen: dict[str, int] = {}
    result: set[str] = set()
    for heading in re.findall(r"^#{1,6} +(.+?) *#* *$", strip_code(text), re.MULTILINE):
        plain = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", r"\1", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", plain).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def strip_code(text: str) -> str:
    text = re.sub(r"^(```|~~~).*?^\1", "", text, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def test_relative_links_and_anchors_resolve() -> None:
    broken: list[str] = []
    for path in tracked_markdown():
        source = REPO_ROOT / path
        for target in re.findall(r"\]\(([^)\s]+)\)", strip_code(source.read_text())):
            if re.match(r"[a-z]+:", target):
                continue
            file, _, anchor = target.partition("#")
            linked = (source.parent / file).resolve() if file else source
            if not linked.exists():
                broken.append(f"{path}: {target} (no such file)")
            elif (
                anchor
                and linked.suffix == ".md"
                and anchor not in anchors(linked.read_text())
            ):
                broken.append(f"{path}: {target} (no such heading)")
    assert not broken, "Fix or remove these Markdown links:\n" + "\n".join(broken)


def test_journal_pages_are_mondays_linked_from_the_index() -> None:
    index = (REPO_ROOT / "v2/eval/EXPERIMENT_JOURNAL.md").read_text()
    for path in tracked_markdown():
        if path.startswith(JOURNAL):
            name = Path(path).stem
            assert date.fromisoformat(name).weekday() == 0, (
                f"Rename {path} to the Monday that starts its week."
            )
            assert f"](journal/{name}.md)" in index, (
                f"Add a row linking journal/{name}.md to v2/eval/EXPERIMENT_JOURNAL.md."
            )


@pytest.mark.parametrize(
    ("runbook", "terraform"),
    [
        ("v2/runbooks/timed-checks-scheduler.md", "v2/infra/timed_checks.tf"),
        ("v2/runbooks/mcp-server.md", "v2/infra/mcp.tf"),
    ],
)
def test_runbook_targets_name_every_resource(runbook: str, terraform: str) -> None:
    block = re.search(
        r"_TARGETS=\(\n(.*?)\n\)", (REPO_ROOT / runbook).read_text(), re.DOTALL
    )
    assert block is not None
    targets = {
        re.sub(r"\[\d+\]$", "", target)
        for target in re.findall(r"-target='?([^'\s]+)", block.group(1))
    }
    resources = {
        f"{kind}.{name}"
        for kind, name in re.findall(
            r'^resource "(\w+)" "(\w+)"',
            (REPO_ROOT / terraform).read_text(),
            re.MULTILINE,
        )
    }
    assert targets == resources, (
        f"Make the -target list in {runbook} match the resources in {terraform}: "
        f"missing {sorted(resources - targets)}, extra {sorted(targets - resources)}"
    )


def test_skill_names_an_existing_workflow_step() -> None:
    workflow = ".github/workflows/v2-development-connectivity-verification.yml"
    skill = (REPO_ROOT / ".claude/skills/query-dev-postgres/SKILL.md").read_text()
    match = re.search(r"read the `([^`]+)` step in\s+`([^`]+)`", skill)
    assert match is not None and match.group(2) == workflow
    name = " ".join(match.group(1).split())
    steps = {
        step.get("name")
        for job in yaml.safe_load((REPO_ROOT / workflow).read_text())["jobs"].values()
        for step in job.get("steps", [])
    }
    assert name in steps, (
        f"Update the step name in the query-dev-postgres skill: {name!r}"
    )
